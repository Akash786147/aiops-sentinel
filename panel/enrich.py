"""Shape saved or live pipeline output into the payloads the console draws."""
from __future__ import annotations

import statistics
import subprocess
from dataclasses import asdict
from pathlib import Path

from sentinel.context import deployment_changes
from sentinel.detection import FLOORS, MEMORY_MIN_GROWTH_MB, Z_THRESHOLD, detect, split_windows
from sentinel.indexing import CodeIndex

MAX_SOURCE_BYTES = 200_000
READABLE = {".py", ".yaml", ".yml", ".md", ".txt", ".json"}
UNITS = {"latency": "ms", "cpu": "%", "memory": "MiB", "errors": "rate", "traffic": "req/s"}
LLM_KEYS = ("model", "root_cause", "evidence", "confidence", "action", "prompt_tokens", "completion_tokens", "latency_s", "valid")
MAX_GRAPH_NODES = 14


def slim_sample(sample: dict) -> dict:
    routes = {r: {"count": s["count"], "errors": s["errors"], "p95_ms": s["p95_ms"]} for r, s in sample["routes"].items()}
    return {"t": sample["t"], "service": sample["service"], "up": sample["up"], "routes": routes,
            "cpu": sample.get("cpu_percent"), "rss_mb": sample.get("rss_mb")}


def stage_payload(event: dict) -> dict:
    return {k: v for k, v in event.items() if k != "event_id"}


def incident_view(recording: dict) -> dict | None:
    names = sorted({s["service"] for s in recording["samples"]})
    found = detect(recording["samples"], recording["change_time"], names, recording["end_time"])
    return found[0].to_dict() if found else None


def _value(sample: dict, kind: str, route: str | None) -> float | None:
    if not sample["up"]:
        return None
    routes = sample["routes"]
    if kind == "cpu":
        return sample.get("cpu_percent")
    if kind == "memory":
        return sample.get("rss_mb")
    if kind == "traffic":
        return float(sum(r["count"] for r in routes.values()))
    stats = routes.get(route) if route else None
    if kind == "latency":
        return stats["p95_ms"] if stats and stats["count"] >= 2 else None
    if kind == "errors":
        if stats:
            return stats["errors"] / stats["count"] if stats["count"] >= 2 else None
        total = sum(r["count"] for r in routes.values())
        return sum(r["errors"] for r in routes.values()) / total if total >= 2 else None
    return None


def baseline_band(recording: dict, incident: dict) -> dict | None:
    """Pre-change level and the level at which the detector fires, for the signal the chart shows."""
    signal = next((s for s in incident["signals"] if s["kind"] == "latency" and s["route"]), incident["signals"][0])
    kind, route = signal["kind"], signal["route"]
    baseline, _ = split_windows(recording["samples"], recording["change_time"])
    values = [v for s in baseline if s["service"] == incident["service"] and (v := _value(s, kind, route)) is not None]
    if len(values) < 3:
        return None
    median = statistics.median(values)
    mad = 1.4826 * statistics.median(abs(v - median) for v in values)
    if kind in FLOORS:
        floor, min_change = FLOORS[kind](median)
        scale = max(mad, floor)
        bar = median + max(Z_THRESHOLD * scale, min_change)
    else:
        scale = max(mad, 2.0)
        bar = median + MEMORY_MIN_GROWTH_MB
    return {"kind": kind, "route": route, "median": round(median, 2), "scale": round(scale, 2), "bar": round(bar, 2), "unit": UNITS.get(kind, "")}


def deployment(workspace: Path) -> dict | None:
    try:
        commits, ranges = deployment_changes(workspace)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return {"commits": commits, "ranges": [asdict(r) for r in ranges]}


def call_path(workspace: Path, routes: list[str]) -> dict | None:
    if not workspace.exists():
        return None
    index = CodeIndex(workspace, dense=False)
    roots = [i for route in routes for i in index.handlers(route)]
    if not roots:
        return None
    depth = index.reachable(roots, max_depth=3)
    keep = sorted(depth, key=lambda i: (depth[i], index.chunks[i].symbol))[:MAX_GRAPH_NODES]
    kept = set(keep)
    nodes = [{"id": index.chunks[i].id, "symbol": index.chunks[i].symbol, "path": index.chunks[i].path,
              "start": index.chunks[i].start, "end": index.chunks[i].end, "depth": depth[i]} for i in keep]
    edges = [{"from": index.chunks[i].id, "to": index.chunks[j].id}
             for i in keep for j in index.callees(i) if j in kept and depth[j] > depth[i]]
    return {"nodes": nodes, "edges": edges}


def read_source(workspace: Path, rel: str) -> str:
    root = workspace.resolve()
    target = (root / rel).resolve()
    if root not in target.parents or target.suffix not in READABLE:
        raise ValueError("path is outside the run workspace")
    if not target.is_file():
        raise FileNotFoundError(rel)
    data = target.read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("file is too large to display")
    return data.decode("utf-8", errors="replace")


def _run(result: dict | None) -> dict | None:
    return None if not result else {"outcome": result.get("outcome"), "detail": (result.get("detail") or "")[:300]}


def _test(test: dict) -> dict:
    return {"code": test.get("code"), "guard": test.get("guard") or [], "faulty": _run(test.get("faulty")),
            "fixed": _run(test.get("fixed")), "confirming": bool(test.get("confirming"))}


def build_result(recording: dict, analysis: dict) -> dict:
    root = Path(recording["workspace"])
    incident = incident_view(recording)
    info = deployment(root) if root.exists() else None
    llm = analysis.get("llm")
    return {
        "incident": incident,
        "band": baseline_band(recording, incident) if incident else None,
        "action": analysis.get("action"),
        "confidence": analysis.get("confidence"),
        "packet_digest": analysis.get("packet_digest"),
        "suspects": analysis.get("suspects", []),
        "llm": {k: llm.get(k) for k in LLM_KEYS} if llm else None,
        "tests": {name: _test(t) for name, t in analysis.get("tests", {}).items()},
        "truth": recording.get("truth"),
        "deployment": recording.get("deployment", []),
        "commits": info["commits"] if info else None,
        "ranges": info["ranges"] if info else None,
        "call_path": call_path(root, incident["routes"]) if incident and root.exists() else None,
        "code_available": root.exists(),
    }
