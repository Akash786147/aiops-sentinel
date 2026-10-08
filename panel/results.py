"""Shape the saved benchmark results for the Results screen."""
from __future__ import annotations

import json

from benchmark.scenarios import SCENARIOS
from panel.paths import Paths

METHODS = ("recent_changes", "bm25", "dense", "hybrid", "hybrid_llm", "rag_llm")


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _detected(run: dict) -> bool:
    """A fault run is detected when the robust detector named the broken service; a control when it alarmed at all."""
    service = run["truth"].get("service")
    robust = run["detection"]["robust"]
    return any(i["service"] == service for i in robust) if run["truth"].get("file") else bool(robust)


def _why(test: dict) -> str:
    if test.get("guard"):
        return f"guard: {test['guard'][0]}"
    faulty = (test.get("faulty") or {}).get("outcome")
    fixed = (test.get("fixed") or {}).get("outcome")
    return f"faulty code {faulty}, known-good code {fixed}"


def failures(runs: list[dict]) -> list[dict]:
    out: list[dict] = []

    def add(kind: str, run: dict, text: str) -> None:
        out.append({"kind": kind, "scenario": run["scenario"], "seed": run["seed"], "text": text})

    for run in sorted(runs, key=lambda r: (r["scenario"], r["seed"])):
        if run["truth"].get("file"):
            if not _detected(run):
                add("undetected", run, "Fault not detected by the robust detector")
                continue
            rank = run.get("localization", {}).get("hybrid", {}).get("rank")
            if rank != 1:
                add("mis-ranked", run, f"True function ranked {rank if rank else 'outside the top 10'} by the hybrid tracer")
            if run["action"] != run["expected_action"]:
                add("wrong action", run, f"Recommended {run['action']}, expected {run['expected_action']}")
            for name, test in run.get("tests", {}).items():
                if not test.get("confirming"):
                    add("test", run, f"{name} test not confirming ({_why(test)})")
        elif run["expected_action"] == "none" and run["detection"]["robust"]:
            add("false alarm", run, "Incident raised on a harmless deployment")
        elif run["action"] != run["expected_action"]:
            add("wrong action", run, f"Recommended {run['action']}, expected {run['expected_action']}")
    return out


def load_results(paths: Paths) -> dict:
    summary_file = paths.results / "summary.json"
    runs_dir = paths.results / "runs"
    if not summary_file.exists() or not runs_dir.exists():
        return {"available": False}
    runs = [_read(p) for p in sorted(runs_dir.glob("*.json"))]
    grid = []
    for scenario in SCENARIOS:
        mine = sorted((r for r in runs if r["scenario"] == scenario.id), key=lambda r: r["seed"])
        row = {"scenario": scenario.id, "title": scenario.title, "class": scenario.fault_class, "service": scenario.service,
               "expected": scenario.expected_action, "seeds": [r["seed"] for r in mine],
               "detected": [_detected(r) for r in mine], "actions": [r["action"] for r in mine], "cells": {}}
        if scenario.fault:
            for method in METHODS:
                row["cells"][method] = [r.get("localization", {}).get(method, {}).get("rank") if _detected(r) else None for r in mine]
        grid.append(row)
    return {"available": True, "summary": _read(summary_file), "grid": grid, "failures": failures(runs), "runs": len(runs)}
