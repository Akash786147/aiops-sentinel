"""Steps 2-6 for one recorded incident window, with every decision written to the audit log.

    telemetry -> detect -> evidence packet -> code index -> trace (+ optional LLM) -> confirming test

Nothing here changes code, restarts services or scales anything. The output is a diagnosis,
a confirming test and a recommended action, waiting for a named human approver.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from sentinel import llm
from sentinel.audit import AuditLog
from sentinel.context import build_packet, route_baseline_stats
from sentinel.detection import detect
from sentinel.indexing import CodeIndex
from sentinel.registry import load_registry
from sentinel.testgen import confirm, llm_test, template_test
from sentinel.tracing import decide, llm_rerank, rank


def analyze(recording: dict, audit: AuditLog, fixed_workspace: Path | None = None, use_llm: bool = True) -> dict:
    root = Path(recording["workspace"])
    registry = load_registry(root)
    names = [s.name for s in registry.services]
    incidents = detect(recording["samples"], recording["change_time"], names, recording["end_time"])
    audit.record("detect", incidents[0].id if incidents else None, f"{len(incidents)} incident(s)",
                 incidents=[{"service": i.service, "symptoms": i.symptoms, "severity": i.severity} for i in incidents])
    if not incidents:
        return {"incidents": [], "action": "none"}
    incident = incidents[0]

    packet = build_packet(root, registry, incident, recording["samples"])
    audit.record("context", incident.id, "evidence packet built", packet_digest=packet.digest, packet_version=packet.version,
                 exceptions=len(packet.exceptions), changes=len(packet.changes), owner=packet.owner)

    index = CodeIndex(root)
    suspects = rank(index, packet, registry)
    decision = decide(packet.incident, suspects)
    audit.record("trace", incident.id, decision["action"], method="hybrid", confidence=decision["confidence"],
                 top=[asdict(s) for s in suspects[:3]])
    result = {"incidents": [i.to_dict() for i in incidents], "packet_digest": packet.digest,
              "suspects": [asdict(s) for s in suspects[:10]], **decision}

    hypothesis = f"{suspects[0].symbol} in {suspects[0].path} ({'; '.join(suspects[0].reasons) or 'textual match'})"
    if use_llm and llm.available():
        reranked, meta = llm_rerank(index, packet, suspects)
        audit.record("trace", incident.id, str(meta.get("action")), method="hybrid+llm", **meta, top=[s.chunk_id for s in reranked[:3]])
        result["llm"] = {"suspects": [asdict(s) for s in reranked[:10]], **meta}
        if meta.get("valid") and meta.get("root_cause"):
            hypothesis = meta["root_cause"]

    service = registry.get(incident.service)
    module = service.module.split(":")[0]
    baselines = {r: route_baseline_stats(recording["samples"], incident.service, r, recording["change_time"])
                 for r in {s["route"] for s in packet.slow_or_failed_requests + packet.exemplar_requests}}
    tests = {"template": template_test(packet, module, baselines, hypothesis)}
    if use_llm and llm.available():
        tests["llm"], meta = llm_test(index, packet, module, suspects, baselines, hypothesis)
        result["llm_test_meta"] = meta
    result["tests"] = {}
    for name, code in tests.items():
        outcome = confirm(root, fixed_workspace, code) if fixed_workspace and code else {"confirming": False, "guard": ["no test generated"]}
        audit.record("test", incident.id, "confirming" if outcome["confirming"] else "not confirming", generator=name, **outcome)
        result["tests"][name] = {"code": code, **outcome}
    audit.record("handoff", incident.id, "awaiting human approval", recommended_action=decision["action"], approver=None)
    return result
