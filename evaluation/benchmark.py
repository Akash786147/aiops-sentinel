"""AIOps Sentinel benchmark: record live incidents, run the pipeline and baselines, score them.

    python -m evaluation.benchmark record   --seeds 0 1 2     # live traffic, ~50 s per scenario
    python -m evaluation.benchmark analyze  --seeds 0 1 2     # pipeline + baselines (+ LLM if a key is set)
    python -m evaluation.benchmark analyze-model --provider groq --model openai/gpt-oss-120b --label gptoss
    python -m evaluation.benchmark analyze-model --provider groq --model qwen/qwen3.8-27b --label qwen
    python -m evaluation.benchmark score                      # tables in evaluation/results/

Recordings and workspaces live under data/bench/; per-scenario results and audit logs under
evaluation/results/. Re-running ``analyze`` reuses cached LLM answers (data/llm_cache).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.record import record
from benchmark.scenarios import SCENARIOS, Scenario, by_id
from benchmark.workspace import fixed_copy
from sentinel import llm
from sentinel.audit import AuditLog
from sentinel.context import build_packet, route_baseline_stats
from sentinel.detection import detect, detect_threshold
from sentinel.indexing import CodeIndex
from sentinel.pipeline import analyze
from sentinel.registry import load_registry
from sentinel.testgen import confirm, llm_test
from sentinel.tracing import (
    Suspect,
    incident_query,
    llm_rerank,
    rank,
    rank_recent_changes,
    rank_retriever,
)
from services.retrieval import RepositoryIndex

DATA = ROOT / "data" / "bench"
RESULTS = ROOT / "evaluation" / "results"
ABLATIONS = {
    "no_trace": frozenset({"trace"}),
    "no_call_graph": frozenset({"route", "call_path"}),
    "no_change": frozenset({"changed_lines", "changed_file"}),
    "no_dense": frozenset({"dense"}),
    "no_lexical": frozenset({"lexical"}),
}


def recording_path(scenario: Scenario, seed: int) -> Path:
    return DATA / f"{scenario.id}-s{seed}.json"


# ---- record ------------------------------------------------------------------------------
def cmd_record(args) -> None:
    for seed in args.seeds:
        for scenario in _selected(args):
            out = recording_path(scenario, seed)
            if out.exists() and not args.force:
                continue
            started = time.time()
            record(scenario, DATA / f"{scenario.id}-s{seed}", out, seed=seed, baseline_s=args.seconds, incident_s=args.seconds)
            print(f"recorded {scenario.id} seed {seed} in {time.time() - started:.0f}s", flush=True)


# ---- analyze -----------------------------------------------------------------------------
def _hits(suspects: list[Suspect], truth: dict) -> dict:
    rank_of = next((n for n, s in enumerate(suspects[:10], start=1)
                    if s.path == truth["file"] and s.start <= truth["end_line"] and truth["start_line"] <= s.end), None)
    file_rank = next((n for n, s in enumerate(suspects[:10], start=1) if s.path == truth["file"]), None)
    return {"rank": rank_of, "file_rank": file_rank, "top": [s.chunk_id for s in suspects[:3]]}


def _legacy(root: Path, packet) -> list[Suspect]:
    """v0 Sentinel: 44-line windows, hashed bag-of-words vectors, whole repository, symptom text query."""
    index = RepositoryIndex(root)
    index.ingest()
    question = (f"Production incident: {', '.join(packet.incident['symptoms'])} on {', '.join(packet.incident['routes']) or packet.service}. "
                "Find responsible code and a safe tested remediation.")
    found = index.search(question, limit=10)
    return [Suspect(f"{r['path']}:{r['start_line']}", r["path"].replace("\\", "/"), "window", r["start_line"], r["end_line"], r["score"]) for r in found]


def _rag_llm(root: Path, packet, index: CodeIndex) -> tuple[list[Suspect], dict]:
    """Plain RAG baseline: dense top-8 over the whole repo, no telemetry structure, same LLM."""
    candidates = rank_retriever(index, incident_query(packet), "dense")
    return llm_rerank(index, packet, candidates, with_tags=False)


def analyze_one(scenario: Scenario, seed: int, use_llm: bool) -> dict:
    recording = json.loads(recording_path(scenario, seed).read_text(encoding="utf-8"))
    root = Path(recording["workspace"])
    registry = load_registry(root)
    names = [s.name for s in registry.services]
    truth = recording["truth"]
    audit_path = RESULTS / "audit" / f"{scenario.id}-s{seed}.jsonl"
    audit_path.unlink(missing_ok=True)
    fixed = fixed_copy(root, scenario, DATA / f"{scenario.id}-s{seed}-fixed")

    robust = detect(recording["samples"], recording["change_time"], names, recording["end_time"])
    threshold = detect_threshold(recording["samples"], recording["change_time"], names, recording["end_time"])
    out = {
        "scenario": scenario.id, "seed": seed, "fault_class": scenario.fault_class, "expected_action": scenario.expected_action,
        "truth": truth, "deployment": recording["deployment"],
        "detection": {
            "robust": [{"service": i.service, "symptoms": i.symptoms, "severity": i.severity, "signals": [s.description for s in i.signals[:4]]} for i in robust],
            "threshold": [{"service": i.service, "symptoms": i.symptoms} for i in threshold],
        },
    }
    product = analyze(recording, AuditLog(audit_path), fixed_workspace=fixed, use_llm=use_llm)
    out["action"] = product.get("action", "none")
    out["confidence"] = product.get("confidence")
    out["tests"] = product.get("tests", {})
    if product.get("llm"):
        out["llm_action"] = product["llm"].get("action")

    incident = next((i for i in robust if i.service == truth["service"]), None) if truth["file"] else None
    if incident:
        packet = build_packet(root, registry, incident, recording["samples"])
        index = CodeIndex(root)
        query = incident_query(packet)
        hybrid = rank(index, packet, registry)
        methods = {
            "legacy_v0": _legacy(root, packet),
            "recent_changes": rank_recent_changes(index, packet),
            "bm25": rank_retriever(index, query, "bm25"),
            "dense": rank_retriever(index, query, "dense"),
            "hybrid": hybrid,
            "hybrid_unscoped": rank(index, packet, registry, scoped=False),
            **{name: rank(index, packet, registry, disabled=off) for name, off in ABLATIONS.items()},
        }
        out["localization"] = {name: _hits(suspects, truth) for name, suspects in methods.items()}
        if use_llm and llm.available() and product.get("llm"):
            llm_suspects = [Suspect(**s) for s in product["llm"]["suspects"]]
            out["localization"]["hybrid_llm"] = {**_hits(llm_suspects, truth), **{k: product["llm"].get(k) for k in ("prompt_tokens", "completion_tokens", "latency_s", "valid", "invented_ids")}}
            rag, meta = _rag_llm(root, packet, index)
            out["localization"]["rag_llm"] = {**_hits(rag, truth), **{k: meta.get(k) for k in ("prompt_tokens", "completion_tokens", "latency_s", "valid", "invented_ids")}}
        out["exceptions_in_packet"] = len(packet.exceptions)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "runs").mkdir(exist_ok=True)
    (RESULTS / "runs" / f"{scenario.id}-s{seed}.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def analyze_extra_model(scenario: Scenario, seed: int, label: str, with_tests: bool = True) -> dict | None:
    """Re-run only the LLM steps with another model (GROQ_MODEL) and merge them in under ``@label``."""
    run_file = RESULTS / "runs" / f"{scenario.id}-s{seed}.json"
    out = json.loads(run_file.read_text(encoding="utf-8"))
    recording = json.loads(recording_path(scenario, seed).read_text(encoding="utf-8"))
    root = Path(recording["workspace"])
    registry = load_registry(root)
    truth = recording["truth"]
    robust = detect(recording["samples"], recording["change_time"], [s.name for s in registry.services], recording["end_time"])
    incident = next((i for i in robust if i.service == truth["service"]), None) if truth["file"] else None
    if not incident:
        return None
    packet = build_packet(root, registry, incident, recording["samples"])
    index = CodeIndex(root)
    suspects = rank(index, packet, registry)
    keys = ("prompt_tokens", "completion_tokens", "latency_s", "valid", "invented_ids")
    reranked, meta = llm_rerank(index, packet, suspects)
    out["localization"][f"hybrid_llm@{label}"] = {**_hits(reranked, truth), **{k: meta.get(k) for k in keys}}
    rag, rag_meta = _rag_llm(root, packet, index)
    out["localization"][f"rag_llm@{label}"] = {**_hits(rag, truth), **{k: rag_meta.get(k) for k in keys}}
    if with_tests:
        hypothesis = meta.get("root_cause") or f"{suspects[0].symbol} in {suspects[0].path}"
        module = registry.get(incident.service).module.split(":")[0]
        baselines = {r: route_baseline_stats(recording["samples"], incident.service, r, recording["change_time"])
                     for r in {s["route"] for s in packet.slow_or_failed_requests + packet.exemplar_requests}}
        code, _ = llm_test(index, packet, module, suspects, baselines, hypothesis)
        fixed = DATA / f"{scenario.id}-s{seed}-fixed"
        out["tests"][f"llm@{label}"] = {"code": code, **confirm(root, fixed, code)}
    run_file.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def cmd_analyze_model(args) -> None:
    os.environ["SENTINEL_LLM"] = args.provider
    os.environ["OPENAI_MODEL" if args.provider == "openai" else "GROQ_MODEL"] = args.model
    for seed in args.seeds:
        for scenario in _selected(args):
            if scenario.fault and (RESULTS / "runs" / f"{scenario.id}-s{seed}.json").exists():
                out = analyze_extra_model(scenario, seed, args.label, with_tests=not args.skip_tests)
                if out:
                    test = out["tests"].get(f"llm@{args.label}", {}).get("confirming", "skipped")
                    print(f"{scenario.id} s{seed} @{args.label}: rank={out['localization'][f'hybrid_llm@{args.label}']['rank']} test={test}", flush=True)


def cmd_analyze(args) -> None:
    use_llm = not args.no_llm
    if use_llm and not llm.available():
        print("No LLM key found (.env GROQ_API_KEY); running deterministic methods only.")
    for seed in args.seeds:
        for scenario in _selected(args):
            if not recording_path(scenario, seed).exists():
                continue
            started = time.time()
            result = analyze_one(scenario, seed, use_llm)
            loc = result.get("localization", {}).get("hybrid", {})
            print(f"{scenario.id} s{seed}: action={result['action']} hybrid_rank={loc.get('rank')} "
                  f"tests={ {k: v.get('confirming') for k, v in result['tests'].items()} } ({time.time() - started:.0f}s)", flush=True)


# ---- score -------------------------------------------------------------------------------
def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 3) if values else float("nan")


def cmd_score(_args) -> None:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((RESULTS / "runs").glob("*.json"))]
    faults = [r for r in runs if r["truth"]["file"]]
    controls = [r for r in runs if not r["truth"]["file"]]
    summary: dict = {"runs": len(runs), "fault_runs": len(faults), "control_runs": len(controls), "seeds": sorted({r["seed"] for r in runs})}

    def detected(r, kind):
        return any(i["service"] == r["truth"]["service"] for i in r["detection"][kind])

    def attributed(r, kind):
        return bool(r["detection"][kind]) and r["detection"][kind][0]["service"] == r["truth"]["service"]

    summary["detection"] = {}
    for kind in ("robust", "threshold"):
        quiet = [r for r in controls if r["expected_action"] == "none"]
        summary["detection"][kind] = {
            "fault_recall": _mean([detected(r, kind) for r in faults]),
            "correct_service_top1": _mean([attributed(r, kind) for r in faults]),
            "false_alarm_rate_quiet_controls": _mean([bool(r["detection"][kind]) for r in quiet]),
            "by_class": {c: _mean([detected(r, kind) for r in faults if r["fault_class"] == c]) for c in sorted({r["fault_class"] for r in faults})},
        }

    methods = sorted({m for r in faults for m in r.get("localization", {})})
    summary["localization"] = {}
    for method in methods:
        rows = [r["localization"][method] for r in faults if method in r.get("localization", {})]
        ranks = [row["rank"] for row in rows]
        entry = {
            "n": len(rows),
            "top1": _mean([rk == 1 for rk in ranks]), "top3": _mean([rk is not None and rk <= 3 for rk in ranks]),
            "top5": _mean([rk is not None and rk <= 5 for rk in ranks]),
            "mrr": _mean([1 / rk if rk else 0.0 for rk in ranks]),
            "file_top1": _mean([row["file_rank"] == 1 for row in rows]),
        }
        tokens = [row.get("prompt_tokens", 0) + row.get("completion_tokens", 0) for row in rows if row.get("prompt_tokens")]
        if tokens:
            entry["mean_tokens"] = round(statistics.mean(tokens))
            entry["mean_latency_s"] = _mean([row["latency_s"] for row in rows if row.get("latency_s") is not None])
            entry["invalid_outputs"] = sum(1 for row in rows if row.get("valid") is False)
            entry["invented_ids"] = sum(len(row.get("invented_ids") or []) for row in rows)
        summary["localization"][method] = entry
    summary["localization_heldout_top1"] = {
        method: _mean([r["localization"][method]["rank"] == 1 for r in faults if r["seed"] != 0 and method in r.get("localization", {})])
        for method in methods
    }
    summary["localization_by_class"] = {
        method: {c: _mean([r["localization"][method]["rank"] == 1 for r in faults if r["fault_class"] == c and method in r.get("localization", {})])
                 for c in sorted({r["fault_class"] for r in faults})}
        for method in ("recent_changes", "dense", "hybrid", "hybrid_llm", "rag_llm") if method in methods
    }

    generators = sorted({g for r in faults for g in r.get("tests", {})})
    summary["tests"] = {}
    for generator in generators:
        rows = [r["tests"][generator] for r in faults if generator in r.get("tests", {})]
        summary["tests"][generator] = {
            "n": len(rows),
            "guard_pass": _mean([not row.get("guard") for row in rows]),
            "fails_on_faulty": _mean([bool(row.get("faulty")) and row["faulty"]["outcome"] == "assertion_failed" for row in rows]),
            "passes_on_fixed": _mean([bool(row.get("fixed")) and row["fixed"]["outcome"] == "passed" for row in rows]),
            "confirming": _mean([row.get("confirming", False) for row in rows]),
        }
    summary["tests_by_scenario"] = {f"{r['scenario']}-s{r['seed']}": {g: r["tests"][g].get("confirming") for g in r.get("tests", {})} for r in faults}

    def action_ok(r, action):
        return action == r["expected_action"] or (r["expected_action"] == "none" and action in ("none",))

    summary["action"] = {
        "sentinel": _mean([action_ok(r, r["action"]) for r in runs]),
        "sentinel_llm": _mean([action_ok(r, r.get("llm_action") or r["action"]) for r in runs if "llm_action" in r or not r["detection"]["robust"]]),
        "always_scale_on_alert": _mean([action_ok(r, "capacity_scale" if r["detection"]["threshold"] else "none") for r in runs]),
        "always_scale_on_robust_alert": _mean([action_ok(r, "capacity_scale" if r["detection"]["robust"] else "none") for r in runs]),
        "by_scenario": {f"{r['scenario']}-s{r['seed']}": r["action"] for r in runs},
    }
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (RESULTS / "summary.md").write_text(_markdown(summary), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("tests_by_scenario",)}, indent=2))


def _pct(value) -> str:
    return "n/a" if value is None or math.isnan(value) else f"{round(value * 100)}%"


def _markdown(s: dict) -> str:
    """Human-readable tables generated from summary.json (never edited by hand)."""
    d, loc, tests, act = s["detection"], s["localization"], s["tests"], s["action"]
    intro = (f"{s['runs']} runs ({s['fault_runs']} fault, {s['control_runs']} control), seeds {s['seeds']}. "
             "Generated by `python -m evaluation.benchmark score`.")
    lines = ["# Benchmark results", "", intro, "", "## Detection", "",
             "| Detector | Fault recall | Right service first | False alarms (H01, H02) | " + " | ".join(d["robust"]["by_class"]) + " |",
             "| --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in d["robust"]["by_class"]) + " |"]
    for name, row in d.items():
        lines.append(f"| {name} | {_pct(row['fault_recall'])} | {_pct(row['correct_service_top1'])} | {_pct(row['false_alarm_rate_quiet_controls'])} | "
                     + " | ".join(_pct(v) for v in row["by_class"].values()) + " |")
    lines += ["", "## Localisation (function level)", "", "| Method | n | Top-1 | Top-3 | Top-5 | MRR | File Top-1 | Held-out Top-1 | Tokens/call | Latency s | Invalid | Invented ids |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, row in sorted(loc.items(), key=lambda item: -item[1]["top1"]):
        lines.append(f"| {name} | {row['n']} | {_pct(row['top1'])} | {_pct(row['top3'])} | {_pct(row['top5'])} | {row['mrr']:.2f} | {_pct(row['file_top1'])} | "
                     f"{_pct(s['localization_heldout_top1'].get(name))} | {row.get('mean_tokens', '')} | {row.get('mean_latency_s', '')} | "
                     f"{row.get('invalid_outputs', '')} | {row.get('invented_ids', '')} |")
    lines += ["", "## Confirming tests", "", "| Generator | n | Guard pass | Fails on faulty | Passes on known-good | Confirming |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, row in tests.items():
        lines.append(f"| {name} | {row['n']} | {_pct(row['guard_pass'])} | {_pct(row['fails_on_faulty'])} | {_pct(row['passes_on_fixed'])} | {_pct(row['confirming'])} |")
    lines += ["", "## Action", "", "| Policy | Accuracy |", "| --- | ---: |"]
    lines += [f"| {name} | {_pct(value)} |" for name, value in act.items() if name != "by_scenario"]
    return "\n".join(lines) + "\n"


def _selected(args) -> list[Scenario]:
    return [by_id(s) for s in args.only] if args.only else list(SCENARIOS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["record", "analyze", "analyze-model", "score"])
    parser.add_argument("--provider", default="groq", choices=["groq", "openai", "ollama"], help="provider for analyze-model")
    parser.add_argument("--model", default="qwen/qwen3.8-27b", help="model for analyze-model")
    parser.add_argument("--label", default="qwen", help="suffix for analyze-model results")
    parser.add_argument("--skip-tests", action="store_true", help="analyze-model: localisation only, no generated tests")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--only", nargs="*", help="scenario ids, e.g. F01 H03")
    parser.add_argument("--seconds", type=float, default=20.0, help="traffic seconds before and after the deployment")
    parser.add_argument("--force", action="store_true", help="re-record even if a recording exists")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    {"record": cmd_record, "analyze": cmd_analyze, "analyze-model": cmd_analyze_model, "score": cmd_score}[args.command](args)


if __name__ == "__main__":
    main()
