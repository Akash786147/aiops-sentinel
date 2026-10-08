"""Hermetic panel fixture: a fake root with one recorded F01 incident, a real git workspace and results."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from benchmark.scenarios import by_id
from benchmark.workspace import build, deploy
from panel.paths import Paths

REPO = Path(__file__).resolve().parents[1]
T0 = 1_800_000_000.0


def _sample(t: float, service: str, route: str, p95: float) -> dict:
    stats = {"count": 10, "errors": 0, "p50_ms": p95 / 2, "p95_ms": p95, "max_ms": p95}
    return {"t": t, "service": service, "up": True, "routes": {route: stats}, "samples": [], "exemplars": [],
            "cpu_percent": 10.0, "rss_mb": 50.0, "pid": 1}


def _audit_events(start: float) -> list[dict]:
    top = {"chunk_id": "orders/repository.py:41-44", "path": "orders/repository.py", "symbol": "fetch_orders_with_profiles",
           "start": 41, "end": 44, "score": 3.5,
           "features": {"lexical": 0.4, "dense": 0.5, "trace": 0.0, "route": 0.0, "call_path": 1.0, "changed_lines": 1.0, "changed_file": 0.0},
           "reasons": ["called (depth 1) from an anomalous route handler", "changed by deployment commit(s): Load customer profile next to each order"]}
    base = {"incident_id": "INC-test0001", "actor": "sentinel"}
    return [
        {"at": start, "stage": "detect", "decision": "1 incident(s)", **base,
         "incidents": [{"service": "orders", "symptoms": ["latency"], "severity": 55.0}]},
        {"at": start + 1, "stage": "context", "decision": "evidence packet built", **base, "packet_digest": "abc123def4567890",
         "packet_version": "1.0", "exceptions": 0, "changes": 4, "owner": "team-commerce"},
        {"at": start + 2, "stage": "trace", "decision": "code_fix", **base, "method": "hybrid", "confidence": 0.89, "top": [top]},
        {"at": start + 12, "stage": "trace", "decision": "code_fix", **base, "method": "hybrid+llm", "model": "test-model",
         "prompt_tokens": 1500, "completion_tokens": 300, "latency_s": 3.2, "valid": True,
         "root_cause": "Customer profile is loaded once per order.", "confidence": 0.9, "action": "code_fix", "top": [top["chunk_id"]]},
        {"at": start + 40, "stage": "test", "decision": "confirming", **base, "generator": "template", "guard": [], "confirming": True,
         "faulty": {"outcome": "assertion_failed", "detail": "AssertionError"}, "fixed": {"outcome": "passed", "detail": ""}},
        {"at": start + 41, "stage": "handoff", "decision": "awaiting human approval", **base, "recommended_action": "code_fix", "approver": None},
    ]


@pytest.fixture(scope="session")
def panel_root(tmp_path_factory) -> Paths:
    root = tmp_path_factory.mktemp("panelroot")
    (root / "shared_server").mkdir()
    shutil.copy(REPO / "shared_server" / "services.yaml", root / "shared_server" / "services.yaml")
    paths = Paths(root)

    scenario = by_id("F01")
    workspace = paths.bench / "F01-s0"
    commits, truth = build(scenario, workspace, 0)
    deploy(workspace, commits, scenario, truth)

    change = T0 + 25
    samples = []
    for i in range(50):
        t = T0 + i
        samples.append(_sample(t, "orders", "GET /orders", 120.0 if t >= change else 8.0 + (i % 3) * 0.3))
        samples.append(_sample(t, "inventory", "GET /stock/{sku}", 6.0))
        samples.append(_sample(t, "payments", "POST /pay", 55.0))
    recording = {"scenario": "F01", "seed": 0, "workspace": str(workspace), "change_time": change, "end_time": T0 + 50,
                 "restarted": ["orders", "inventory", "payments"], "deployment": [c.message for c in commits],
                 "truth": asdict(truth), "samples": samples, "events": []}
    paths.bench.mkdir(parents=True, exist_ok=True)
    paths.recording("F01", 0).write_text(json.dumps(recording), encoding="utf-8")

    template = {"code": "def test_x():\n    assert False\n", "guard": [], "confirming": True,
                "faulty": {"outcome": "assertion_failed", "detail": "AssertionError", "exit_code": 1},
                "fixed": {"outcome": "passed", "detail": "", "exit_code": 0}}
    run_result = {"scenario": "F01", "seed": 0, "fault_class": "latency", "expected_action": "code_fix", "truth": asdict(truth),
                  "deployment": recording["deployment"], "action": "code_fix", "confidence": 0.89,
                  "detection": {"robust": [{"service": "orders", "symptoms": ["latency"], "severity": 55.0, "signals": []}], "threshold": []},
                  "tests": {"template": template},
                  "localization": {"hybrid": {"rank": 1, "file_rank": 1, "top": []}, "bm25": {"rank": 5, "file_rank": 1, "top": []}}}
    (paths.results / "runs").mkdir(parents=True)
    (paths.results / "audit").mkdir(parents=True)
    paths.run_result("F01", 0).write_text(json.dumps(run_result), encoding="utf-8")
    paths.audit("F01", 0).write_text("\n".join(json.dumps(e) for e in _audit_events(T0 + 100)) + "\n", encoding="utf-8")
    (paths.results / "summary.json").write_text(json.dumps({"runs": 1, "fault_runs": 1, "control_runs": 0, "seeds": [0]}), encoding="utf-8")
    return paths
