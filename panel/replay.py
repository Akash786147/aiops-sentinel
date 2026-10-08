"""Replay: re-emit a saved run (telemetry, deployment, audit stages) on a compressed clock."""
from __future__ import annotations

import json
import time
from pathlib import Path

from panel import enrich
from panel.paths import Paths
from sentinel.registry import load_registry

MAX_STAGE_GAP_S = 8.0  # analysis steps (LLM, sandbox) take a minute; cap each gap before compressing


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _audit(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_timeline(rec: dict, audit: list[dict], speed: float, owners: dict[str, str]) -> tuple[list[tuple[float, str, dict]], float]:
    """(due_seconds, kind, data) items sorted by due time, and the due time of the last item."""
    t0 = rec["samples"][0]["t"]
    items: list[tuple[float, str, dict]] = []
    seen: set[str] = set()
    for sample in rec["samples"]:
        due = (sample["t"] - t0) / speed
        if sample["service"] not in seen:
            seen.add(sample["service"])
            service = {"name": sample["service"], "owner": owners.get(sample["service"]), "up": sample["up"], "pid": sample.get("pid")}
            items.append((due, "service", service))
        items.append((due, "telemetry", enrich.slim_sample(sample)))
    deploy = {"commits": rec["deployment"], "restarted": rec["restarted"], "at": rec["change_time"]}
    items.append(((rec["change_time"] - t0) / speed, "deploy", deploy))
    due = (rec["end_time"] - t0) / speed + 0.4
    previous = None
    for event in audit:
        if previous is not None:
            due += min(event["at"] - previous, MAX_STAGE_GAP_S) / speed
        previous = event["at"]
        items.append((due, "stage", enrich.stage_payload(event)))
    items.sort(key=lambda item: item[0])
    return items, items[-1][0]


def analysis_from_stored(stored: dict, audit: list[dict]) -> dict:
    traces = [e for e in audit if e["stage"] == "trace"]
    hybrid = next((e for e in traces if e.get("method") == "hybrid"), None)
    llm = next((e for e in traces if e.get("method") == "hybrid+llm"), None)
    context = next((e for e in audit if e["stage"] == "context"), {})
    return {"action": stored.get("action"), "confidence": stored.get("confidence"),
            "suspects": hybrid["top"] if hybrid else [], "llm": llm, "tests": stored.get("tests", {}),
            "packet_digest": context.get("packet_digest")}


def _sleep_until(deadline: float, cancel) -> None:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or cancel.wait(min(remaining, 0.25)):
            return


def run_replay(ctx, scenario: str, seed: int, speed: float) -> None:
    paths: Paths = ctx.paths
    rec = _read(paths.recording(scenario, seed))
    stored = _read(paths.run_result(scenario, seed))
    audit = _audit(paths.audit(scenario, seed))
    owners = {s.name: s.owner for s in load_registry(paths.root / "shared_server").services}
    items, end_due = build_timeline(rec, audit, speed, owners)
    start = time.monotonic()
    for due, kind, data in items:
        _sleep_until(start + due, ctx.cancel)
        if ctx.cancel.is_set():
            return
        ctx.bus.emit(kind, data)
    _sleep_until(start + end_due + 0.3, ctx.cancel)
    ctx.emit_result(enrich.build_result(rec, analysis_from_stored(stored, audit)))
