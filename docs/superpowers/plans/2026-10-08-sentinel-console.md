# Sentinel Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web panel (`python -m panel`) that shows the shared server, a live or replayed incident moving through detect → packet → trace → test → hand-off, and the measured benchmark results, with a hand-made dark ops-console design.

**Architecture:** A `panel/` FastAPI package emits one event stream (server-sent events) from either a Live run (real services, real traffic, real `sentinel.pipeline.analyze`) or a Replay run (time-compressed playback of saved recordings). A vanilla-JS single page (no build step, hand-built SVG charts) renders seven views from one client store. Backend logic reuses `sentinel/` and `benchmark/` without changing them.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, pydantic (already in `requirements.txt`); vanilla ES modules, CSS custom properties, inline SVG; pytest + FastAPI `TestClient`; Microsoft Edge headless (or Playwright) for screenshots.

**Spec:** `docs/superpowers/specs/2026-10-08-sentinel-console-design.md`

**No commit steps.** The user asked that nothing is committed during this work. Every task ends with passing tests/lint instead; `git status` is checked at the end.

## Global Constraints

- `python -m panel` serves `http://127.0.0.1:8080`; `--port` overrides; if the port is busy, fail with a message (no auto-increment).
- No Node, no build step, no CDN, works offline; no new Python dependencies.
- Reuse `sentinel/`, `benchmark/`, `evaluation/results/`; **do not change behaviour of anything under `sentinel/` or `benchmark/`** (adding nothing there; the panel composes existing functions).
- The tracer never receives ground truth; the UI shows `truth` only from the `result` event onward.
- The panel writes only under `data/panel/` (and reads `data/bench/`, `evaluation/results/`). `/api/approve` appends an audit event only and never edits code.
- One run at a time (`POST /api/run` returns 409 while active). Replay speed default 3× (about 40 s). The LLM toggle applies to Live only.
- Fonts: system stack only (`system-ui`, `ui-monospace`/Cascadia Mono). Dark theme only. Verified at 1280×720 and 1920×1080.
- Charts are hand-built SVG; colours are the project accents (indigo, orange, green; red only for failure).

## Review Focus

Failure modes the spec implies that no feature task would otherwise test (each has a test in the task that owns the code):

1. Browser refresh or second tab mid-run must recover the run (Task 6: `/api/state` returns the current run's events and `next`).
2. A second run request while one is active returns 409 and does not start a thread (Task 4, Task 6).
3. `/api/code` with `../` or an absolute path returns 400 and never reads outside the workspace (Task 3, Task 6).
4. Approve before any result, or with an empty name, is refused and writes nothing (Task 4, Task 6).
5. A scenario with no saved recording is reported unavailable (greyed out) and a Replay request for it returns 503, not a crash (Task 4, Task 6).
6. A control run with no incident (`incident: null`) must still produce a valid `result` payload and a finished run (Task 3, Task 4).

## File Structure

```text
panel/
  __init__.py        package docstring
  __main__.py        CLI entry
  paths.py           Paths: where recordings, results, panel data live (injectable for tests)
  bus.py             EventBus: ordered events, run boundary, blocking wait
  results.py         shape evaluation/results for the Results screen; failures list
  enrich.py          incident view, baseline band, deployment diff, call path, safe source read, result payload
  replay.py          build_timeline (pure) and run_replay
  live.py            run_live: services + traffic + deploy + analyze, poller, audit tail
  runner.py          Runner: one active run, preconditions, approve
  server.py          create_app: REST + SSE + static
  static/
    index.html  app.css
    js/ main.js topbar.js store.js api.js ui.js charts.js
    js/views/ floor.js incident.js trace.js proof.js decision.js results.js project.js
tests/
  conftest.py        session fixture panel_root (hermetic recording + workspace + results)
  test_panel_bus.py test_panel_results.py test_panel_enrich.py
  test_panel_runner.py test_panel_server.py test_panel_live.py
```

---

### Task 1: Foundation: paths, event bus, shared test fixture

**Files:**
- Create: `panel/__init__.py`, `panel/paths.py`, `panel/bus.py`
- Create: `tests/conftest.py`, `tests/test_panel_bus.py`

**Interfaces:**
- Produces: `Paths(root: Path)` with properties `bench`, `results`, `panel_data` and methods `recording(scenario, seed)`, `run_result(scenario, seed)`, `audit(scenario, seed)`; module constant `DEFAULT`.
- Produces: `EventBus` with `emit(kind: str, data: dict) -> dict`, `current_run() -> tuple[list[dict], int]`, `wait(since: int, timeout: float = 15.0) -> list[dict]`. Event shape `{"n": int, "t": float, "kind": str, "data": dict}`; a `run` event with `data["state"] == "started"` marks the start of the current run.
- Produces: pytest fixture `panel_root` (session scope) returning a `Paths` whose root holds `shared_server/services.yaml`, `data/bench/F01-s0.json` + git workspace `data/bench/F01-s0/`, `evaluation/results/{summary.json,runs/F01-s0.json,audit/F01-s0.jsonl}`.

- [ ] **Step 1: Write the failing bus tests**

`tests/test_panel_bus.py`:
```python
import threading

from panel.bus import EventBus


def test_events_are_numbered_and_run_start_marks_a_boundary():
    bus = EventBus()
    bus.emit("run", {"state": "started", "id": "a"})
    bus.emit("telemetry", {"x": 1})
    bus.emit("run", {"state": "done"})
    bus.emit("run", {"state": "started", "id": "b"})
    bus.emit("telemetry", {"x": 2})
    events, nxt = bus.current_run()
    assert [e["n"] for e in events] == [3, 4]
    assert events[0]["data"]["id"] == "b"
    assert nxt == 5


def test_wait_returns_new_events_and_times_out_empty():
    bus = EventBus()
    assert bus.wait(0, timeout=0.05) == []
    timer = threading.Timer(0.05, lambda: bus.emit("service", {"name": "orders"}))
    timer.start()
    got = bus.wait(0, timeout=2.0)
    timer.join()
    assert got and got[0]["kind"] == "service"
    assert bus.wait(1, timeout=0.05) == []


def test_empty_bus_has_empty_current_run():
    assert EventBus().current_run() == ([], 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_panel_bus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'panel'`.

- [ ] **Step 3: Write `panel/__init__.py`, `panel/paths.py`, `panel/bus.py`**

`panel/__init__.py`:
```python
"""Sentinel Console: a local web panel for the shared-server incident pipeline."""
```

`panel/paths.py`:
```python
"""Where the console reads recordings and results and writes its own files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def bench(self) -> Path:
        return self.root / "data" / "bench"

    @property
    def results(self) -> Path:
        return self.root / "evaluation" / "results"

    @property
    def panel_data(self) -> Path:
        return self.root / "data" / "panel"

    def recording(self, scenario: str, seed: int) -> Path:
        return self.bench / f"{scenario}-s{seed}.json"

    def run_result(self, scenario: str, seed: int) -> Path:
        return self.results / "runs" / f"{scenario}-s{seed}.json"

    def audit(self, scenario: str, seed: int) -> Path:
        return self.results / "audit" / f"{scenario}-s{seed}.jsonl"


DEFAULT = Paths(Path(__file__).resolve().parents[1])
```

`panel/bus.py`:
```python
"""In-memory ordered event log shared by the runner (writer) and SSE clients (readers)."""
from __future__ import annotations

import threading
import time


class EventBus:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._cond = threading.Condition()
        self._run_start = 0

    def emit(self, kind: str, data: dict) -> dict:
        with self._cond:
            event = {"n": len(self._events), "t": round(time.time(), 3), "kind": kind, "data": data}
            if kind == "run" and data.get("state") == "started":
                self._run_start = event["n"]
            self._events.append(event)
            self._cond.notify_all()
            return event

    def current_run(self) -> tuple[list[dict], int]:
        """Events of the latest run and the index the next event will get."""
        with self._cond:
            return list(self._events[self._run_start :]), len(self._events)

    def wait(self, since: int, timeout: float = 15.0) -> list[dict]:
        with self._cond:
            self._cond.wait_for(lambda: len(self._events) > since, timeout)
            return list(self._events[since:])
```

- [ ] **Step 4: Write the shared fixture `tests/conftest.py`**

```python
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
```

- [ ] **Step 5: Run the tests and lint**

Run: `python -m pytest tests/test_panel_bus.py -v; python -m ruff check panel tests`
Expected: 3 passed; ruff `All checks passed!`

---

### Task 2: Results shaper

**Files:**
- Create: `panel/results.py`
- Create: `tests/test_panel_results.py`

**Interfaces:**
- Consumes: `Paths` (Task 1); `benchmark.scenarios.SCENARIOS`.
- Produces: `load_results(paths: Paths) -> dict` returning `{"available": False}` or `{"available": True, "summary": dict, "grid": list[dict], "failures": list[dict], "runs": int}`; `failures(runs: list[dict]) -> list[dict]`; each failure `{"kind": str, "scenario": str, "seed": int, "text": str}`; each grid row `{"scenario","title","class","service","expected","seeds","detected","actions","cells":{method:[rank|None per seed]}}`; module constant `METHODS`.

- [ ] **Step 1: Write the failing tests**

`tests/test_panel_results.py`:
```python
from panel.paths import Paths
from panel.results import failures, load_results


def test_unavailable_without_results(tmp_path):
    assert load_results(Paths(tmp_path)) == {"available": False}


def test_grid_and_summary_from_fixture(panel_root):
    out = load_results(panel_root)
    assert out["available"] and out["runs"] == 1
    row = next(r for r in out["grid"] if r["scenario"] == "F01")
    assert row["detected"] == [True]
    assert row["cells"]["hybrid"] == [1] and row["cells"]["bm25"] == [5]
    assert out["summary"]["runs"] == 1
    assert out["failures"] == []


def _run(scenario, seed, *, fault=True, detected=True, rank=1, action="code_fix", expected="code_fix", tests=None):
    robust = [{"service": "orders" if fault else "payments"}] if detected else []
    return {"scenario": scenario, "seed": seed, "truth": {"file": "x.py" if fault else None, "service": "orders" if fault else None},
            "detection": {"robust": robust}, "action": action, "expected_action": expected,
            "localization": {"hybrid": {"rank": rank}}, "tests": tests or {}}


def test_failures_list_the_real_problems():
    runs = [
        _run("F09", 0, detected=False),
        _run("F07", 0, rank=4),
        _run("F06", 1, tests={"llm": {"confirming": False, "guard": ["no test generated"]}}),
        _run("H01", 2, fault=False, action="investigate", expected="none"),
        _run("H03", 2, fault=False, detected=False, action="none", expected="capacity_scale"),
        _run("F01", 0),
    ]
    kinds = [(f["kind"], f["scenario"]) for f in failures(runs)]
    assert ("undetected", "F09") in kinds
    assert ("mis-ranked", "F07") in kinds
    assert ("test", "F06") in kinds
    assert ("false alarm", "H01") in kinds
    assert ("wrong action", "H03") in kinds
    assert not [k for k in kinds if k[1] == "F01"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_panel_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'panel.results'`.

- [ ] **Step 3: Write `panel/results.py`**

```python
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
```

- [ ] **Step 4: Run tests and lint**

Run: `python -m pytest tests/test_panel_results.py -v; python -m ruff check panel tests`
Expected: 3 passed; `All checks passed!`

---

### Task 3: Enrichment: incident view, baseline band, deploy diff, call path, safe source

**Files:**
- Create: `panel/enrich.py`
- Create: `tests/test_panel_enrich.py`

**Interfaces:**
- Consumes: `sentinel.detection.{detect, split_windows, FLOORS, Z_THRESHOLD, MEMORY_MIN_GROWTH_MB}`, `sentinel.context.deployment_changes`, `sentinel.indexing.CodeIndex`.
- Produces: `slim_sample(sample: dict) -> dict`; `stage_payload(event: dict) -> dict`; `incident_view(recording: dict) -> dict | None`; `baseline_band(recording: dict, incident: dict) -> dict | None` returning `{"kind","route","median","scale","bar","unit"}`; `deployment(workspace: Path) -> dict | None` returning `{"commits": [...], "ranges": [...]}`; `call_path(workspace: Path, routes: list[str]) -> dict | None` returning `{"nodes": [{"id","symbol","path","start","end","depth"}], "edges": [{"from","to"}]}`; `read_source(workspace: Path, rel: str) -> str` (raises `ValueError` outside workspace/too large/unsupported type, `FileNotFoundError` if absent); `build_result(recording: dict, analysis: dict) -> dict` (payload of the `result` event, keys: `incident, band, action, confidence, suspects, llm, tests, truth, deployment, commits, ranges, call_path, code_available, packet_digest`).

- [ ] **Step 1: Write the failing tests**

`tests/test_panel_enrich.py`:
```python
import json
from pathlib import Path

import pytest

from panel import enrich


@pytest.fixture(scope="module")
def recording(panel_root):
    return json.loads(panel_root.recording("F01", 0).read_text(encoding="utf-8"))


def test_incident_view_names_the_broken_tenant_and_route(recording):
    incident = enrich.incident_view(recording)
    assert incident["service"] == "orders"
    assert incident["symptoms"] == ["latency"]
    assert "GET /orders" in incident["routes"]
    assert incident["signals"][0]["z"] > 6


def test_baseline_band_is_the_pre_change_level(recording):
    band = enrich.baseline_band(recording, enrich.incident_view(recording))
    assert band["kind"] == "latency" and band["route"] == "GET /orders" and band["unit"] == "ms"
    assert 7 < band["median"] < 10
    assert band["bar"] > band["median"] + 14


def test_deployment_lists_commits_and_changed_ranges(recording):
    info = enrich.deployment(Path(recording["workspace"]))
    assert len(info["commits"]) == 4
    assert any(r["file"] == "orders/repository.py" and r["behavioural"] for r in info["ranges"])


def test_call_path_reaches_the_helper_from_the_route_handler(recording):
    graph = enrich.call_path(Path(recording["workspace"]), ["GET /orders"])
    symbols = {n["symbol"]: n["depth"] for n in graph["nodes"]}
    assert symbols["list_orders"] == 0 and symbols["fetch_orders_with_profiles"] == 1
    assert all({"from", "to"} == set(e) for e in graph["edges"])


@pytest.mark.parametrize("bad", ["../services.yaml", "/etc/passwd", "orders/../../x.py", "C:/Windows/win.ini"])
def test_read_source_refuses_paths_outside_the_workspace(recording, bad):
    with pytest.raises((ValueError, FileNotFoundError)):
        enrich.read_source(Path(recording["workspace"]), bad)


def test_read_source_reads_a_workspace_file(recording):
    assert "def list_orders" in enrich.read_source(Path(recording["workspace"]), "orders/app.py")


def test_build_result_for_a_run_with_no_incident_is_still_valid(recording):
    flat = dict(recording, samples=[dict(s, routes={r: dict(v, p95_ms=8.0) for r, v in s["routes"].items()}) for s in recording["samples"]])
    payload = enrich.build_result(flat, {"action": "none", "confidence": 0.0, "suspects": [], "tests": {}})
    assert payload["incident"] is None and payload["band"] is None and payload["call_path"] is None
    assert payload["action"] == "none" and payload["truth"]["file"] == "orders/repository.py"


def test_build_result_with_an_incident_carries_everything_the_views_need(recording):
    analysis = {"action": "code_fix", "confidence": 0.9, "packet_digest": "d1",
                "suspects": [{"chunk_id": "orders/repository.py:41-44"}],
                "llm": {"model": "m", "root_cause": "why", "secret_extra": 1},
                "tests": {"template": {"code": "x", "guard": [], "confirming": True,
                                       "faulty": {"outcome": "assertion_failed", "detail": "d" * 500, "exit_code": 1},
                                       "fixed": {"outcome": "passed", "detail": "", "exit_code": 0}}}}
    payload = enrich.build_result(recording, analysis)
    assert payload["incident"]["service"] == "orders" and payload["band"]["median"] > 0
    assert payload["code_available"] and len(payload["commits"]) == 4 and payload["ranges"]
    assert "secret_extra" not in payload["llm"] and payload["llm"]["root_cause"] == "why"
    assert len(payload["tests"]["template"]["faulty"]["detail"]) <= 300
    assert "exit_code" not in payload["tests"]["template"]["faulty"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_panel_enrich.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'panel.enrich'`.

- [ ] **Step 3: Write `panel/enrich.py`**

```python
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
```

- [ ] **Step 4: Run tests and lint**

Run: `python -m pytest tests/test_panel_enrich.py -v; python -m ruff check panel tests`
Expected: all pass (about 12 tests, `read_source` parametrised 4×); `All checks passed!`
If `C:/Windows/win.ini` is not refused: `(root / "C:/Windows/win.ini")` on Windows resolves to the absolute path, whose parents do not include `root`, so it must raise `ValueError`; fix the guard, not the test.

---

### Task 4: Replay, live-run skeleton and runner

**Files:**
- Create: `panel/replay.py`, `panel/runner.py`
- Create: `panel/live.py` (stub raising until Task 5; real code in Task 5)
- Create: `tests/test_panel_runner.py`

**Interfaces:**
- Consumes: `EventBus`, `Paths`, `enrich.{slim_sample, stage_payload, build_result}`, `sentinel.registry.load_registry`, `sentinel.audit.AuditLog`, `benchmark.scenarios.by_id`.
- Produces: `replay.build_timeline(rec: dict, audit: list[dict], speed: float, owners: dict[str, str]) -> tuple[list[tuple[float, str, dict]], float]`; `replay.analysis_from_stored(stored: dict, audit: list[dict]) -> dict`; `replay.run_replay(ctx: RunContext, scenario: str, seed: int, speed: float) -> None`.
- Produces: `runner.RunContext(bus, paths, cancel, incident_id, has_result)` with `emit_result(payload)`; `runner.Runner(bus, paths, speed=3.0)` with `start(scenario_id, mode, use_llm=True, seed=0) -> {"run": dict, "since": int}`, `public() -> dict | None`, `replay_available(scenario_id, seed) -> bool`, `check_live() -> None`, `approve(approver, note) -> dict`, `workspace(run_id=None) -> Path | None`; exceptions `Busy`, `Unavailable`, `NotReady`; `start` raises `KeyError` for an unknown scenario.
- Event data contracts: `service {name, owner, up, pid}`; `telemetry` = `slim_sample` output; `deploy {commits, restarted, at}`; `stage` = audit event minus `event_id`; `run {id, scenario, mode, seed, llm, state, reason?}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_panel_runner.py`:
```python
import json
import socket
import subprocess
import threading
import time

import pytest

from panel import replay as replay_mod
from panel.bus import EventBus
from panel.replay import build_timeline
from panel.runner import Busy, NotReady, Runner, Unavailable


def wait_done(bus, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        events, _ = bus.current_run()
        if any(e["kind"] == "run" and e["data"].get("state") in ("done", "failed") for e in events):
            return events
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_replay_emits_the_whole_story_in_order(panel_root):
    bus = EventBus()
    Runner(bus, panel_root, speed=100000).start("F01", "replay")
    events = wait_done(bus)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run" and events[0]["data"]["state"] == "started"
    assert kinds[-1] == "run" and events[-1]["data"]["state"] == "done"
    assert kinds.index("deploy") < kinds.index("result")
    stages = [e["data"]["stage"] for e in events if e["kind"] == "stage"]
    assert stages[:3] == ["detect", "context", "trace"] and stages[-1] == "handoff"
    assert kinds.count("result") == 1 and kinds.index("result") > max(i for i, k in enumerate(kinds) if k == "stage")
    result = next(e for e in events if e["kind"] == "result")["data"]
    assert result["incident"]["service"] == "orders" and result["truth"]["file"] == "orders/repository.py"
    assert {e["data"]["name"] for e in events if e["kind"] == "service"} == {"orders", "inventory", "payments"}


def test_timeline_is_ordered_and_compressed(panel_root):
    rec = json.loads(panel_root.recording("F01", 0).read_text(encoding="utf-8"))
    audit = [json.loads(line) for line in panel_root.audit("F01", 0).read_text(encoding="utf-8").splitlines()]
    items, end_due = build_timeline(rec, audit, 3.0, {"orders": "team-commerce"})
    dues = [d for d, _, _ in items]
    assert dues == sorted(dues)
    assert items[-1][1] == "stage" and end_due == pytest.approx(dues[-1])
    assert end_due < 60 / 3 + 20  # 50 s of samples at 3x plus capped analysis gaps


def test_second_run_while_active_is_refused(panel_root, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(replay_mod, "run_replay", lambda ctx, *a: gate.wait(5))
    runner = Runner(EventBus(), panel_root)
    runner.start("F01", "replay")
    with pytest.raises(Busy):
        runner.start("F01", "replay")
    gate.set()


def test_unknown_scenario_and_missing_recording(panel_root):
    runner = Runner(EventBus(), panel_root)
    with pytest.raises(KeyError):
        runner.start("F99", "replay")
    assert runner.replay_available("F01", 0) is True
    assert runner.replay_available("F02", 0) is False
    with pytest.raises(Unavailable):
        runner.start("F02", "replay")


def test_live_is_refused_when_a_tenant_port_is_busy(panel_root):
    holder = socket.socket()
    try:
        holder.bind(("127.0.0.1", 9101))
    except OSError:
        pytest.skip("port 9101 already in use on this machine")
    holder.listen()
    try:
        with pytest.raises(Unavailable, match="9101"):
            Runner(EventBus(), panel_root).start("F01", "live")
    finally:
        holder.close()


def test_failure_inside_a_run_is_reported_not_raised(panel_root, monkeypatch):
    def boom(ctx, *a):
        raise RuntimeError("service exploded")

    monkeypatch.setattr(replay_mod, "run_replay", boom)
    bus = EventBus()
    Runner(bus, panel_root).start("F01", "replay")
    events = wait_done(bus)
    assert events[-1]["data"]["state"] == "failed" and "service exploded" in events[-1]["data"]["reason"]


def test_approve_needs_a_result_then_writes_only_an_audit_event(panel_root):
    bus = EventBus()
    runner = Runner(bus, panel_root, speed=100000)
    with pytest.raises(NotReady):
        runner.approve("Akash", "too early")
    runner.start("F01", "replay")
    wait_done(bus)
    stage = runner.approve("Akash", "looks right")
    assert stage["decision"] == "approved" and stage["approver"] == "Akash" and stage["stage"] == "handoff"
    approvals = [json.loads(line) for line in (panel_root.panel_data / f"{runner.current['id']}-approvals.jsonl").read_text(encoding="utf-8").splitlines()]
    assert approvals[-1]["approver"] == "Akash"
    workspace = runner.workspace()
    assert subprocess.run(["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True, check=True).stdout == ""
    assert runner.workspace("some-other-run") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_panel_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'panel.replay'`.

- [ ] **Step 3: Write `panel/replay.py`**

```python
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
            items.append((due, "service", {"name": sample["service"], "owner": owners.get(sample["service"]), "up": sample["up"], "pid": sample.get("pid")}))
        items.append((due, "telemetry", enrich.slim_sample(sample)))
    items.append(((rec["change_time"] - t0) / speed, "deploy", {"commits": rec["deployment"], "restarted": rec["restarted"], "at": rec["change_time"]}))
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
    rec, stored, audit = _read(paths.recording(scenario, seed)), _read(paths.run_result(scenario, seed)), _audit(paths.audit(scenario, seed))
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
```

- [ ] **Step 4: Write `panel/live.py` placeholder and `panel/runner.py`**

`panel/live.py` (replaced in Task 5):
```python
"""Live run: replaced by the full implementation in the next task."""
from __future__ import annotations


def run_live(ctx, scenario_id: str, seed: int, use_llm: bool, run_id: str) -> None:
    raise NotImplementedError("live runs are added in Task 5")
```

`panel/runner.py`:
```python
"""One active run at a time: Live or Replay, plus the human approval record."""
from __future__ import annotations

import json
import shutil
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from benchmark.scenarios import by_id
from panel import live, replay
from panel.bus import EventBus
from panel.paths import Paths
from sentinel.audit import AuditLog
from sentinel.registry import load_registry


class Busy(RuntimeError):
    """A run is already in progress."""


class Unavailable(RuntimeError):
    """The requested mode cannot run here (missing recording, busy port, no git)."""


class NotReady(RuntimeError):
    """There is no finished diagnosis to approve."""


@dataclass
class RunContext:
    bus: EventBus
    paths: Paths
    cancel: threading.Event = field(default_factory=threading.Event)
    incident_id: str | None = None
    has_result: bool = False

    def emit_result(self, payload: dict) -> None:
        self.has_result = True
        incident = payload.get("incident")
        self.incident_id = incident["id"] if incident else None
        self.bus.emit("result", payload)


class Runner:
    def __init__(self, bus: EventBus, paths: Paths, speed: float = 3.0) -> None:
        self.bus, self.paths, self.speed = bus, paths, speed
        self.ctx = RunContext(bus, paths)
        self.current: dict | None = None
        self._lock = threading.Lock()
        self._active = False

    def public(self) -> dict | None:
        if not self.current:
            return None
        return {k: self.current[k] for k in ("id", "scenario", "mode", "seed", "llm")}

    def replay_available(self, scenario_id: str, seed: int) -> bool:
        return all(p.exists() for p in (self.paths.recording(scenario_id, seed), self.paths.run_result(scenario_id, seed),
                                        self.paths.audit(scenario_id, seed)))

    def check_live(self) -> None:
        if shutil.which("git") is None:
            raise Unavailable("git is not on PATH")
        for service in load_registry(self.paths.root / "shared_server").services:
            with socket.socket() as probe:
                probe.settimeout(0.3)
                if probe.connect_ex(("127.0.0.1", service.port)) == 0:
                    raise Unavailable(f"port {service.port} ({service.name}) is already in use")

    def start(self, scenario_id: str, mode: str, use_llm: bool = True, seed: int = 0) -> dict:
        by_id(scenario_id)  # KeyError for an unknown scenario
        with self._lock:
            if self._active:
                raise Busy("a run is already in progress")
            run_id = f"{scenario_id}-{mode}-{int(time.time() * 1000)}"
            if mode == "replay":
                if not self.replay_available(scenario_id, seed):
                    raise Unavailable(f"no saved recording for {scenario_id} seed {seed}")
                workspace = Path(json.loads(self.paths.recording(scenario_id, seed).read_text(encoding="utf-8"))["workspace"])
            else:
                self.check_live()
                workspace = self.paths.panel_data / run_id / "ws"
            self.ctx = RunContext(self.bus, self.paths)
            self.current = {"id": run_id, "scenario": scenario_id, "mode": mode, "seed": seed, "llm": bool(use_llm and mode == "live"),
                            "workspace": str(workspace), "approvals": str(self.paths.panel_data / f"{run_id}-approvals.jsonl")}
            self._active = True
            started = self.bus.emit("run", {**self.public(), "state": "started"})
            threading.Thread(target=self._guard, args=(mode, scenario_id, seed, use_llm, run_id), daemon=True).start()
            return {"run": self.public(), "since": started["n"]}

    def _guard(self, mode: str, scenario_id: str, seed: int, use_llm: bool, run_id: str) -> None:
        final = {"state": "done"}
        try:
            if mode == "replay":
                replay.run_replay(self.ctx, scenario_id, seed, self.speed)
            else:
                live.run_live(self.ctx, scenario_id, seed, use_llm, run_id)
        except Exception as exc:  # noqa: BLE001 - any failure must reach the UI as a failed run
            final = {"state": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        with self._lock:
            self._active = False
        self.bus.emit("run", {**self.public(), **final})

    def approve(self, approver: str, note: str) -> dict:
        if not self.current or not self.ctx.has_result:
            raise NotReady("there is no finished diagnosis to approve")
        log = AuditLog(Path(self.current["approvals"]))
        event = log.record("handoff", self.ctx.incident_id, "approved", actor=approver, approver=approver, note=note)
        from panel import enrich

        stage = enrich.stage_payload(event)
        self.bus.emit("stage", stage)
        return stage

    def workspace(self, run_id: str | None = None) -> Path | None:
        if not self.current or (run_id and run_id != self.current["id"]):
            return None
        return Path(self.current["workspace"])
```
Move `from panel import enrich` to the top import block (the inline import above is only for brevity; ruff `PLC0415` may flag it; keep imports at the top).

- [ ] **Step 5: Run tests and lint**

Run: `python -m pytest tests/test_panel_runner.py -v; python -m ruff check panel tests`
Expected: 7 passed; `All checks passed!`

---

### Task 5: Live run

**Files:**
- Modify (replace stub): `panel/live.py`
- Create: `tests/test_panel_live.py`

**Interfaces:**
- Consumes: `benchmark.record.{start_service, wait_ready, stop}`, `benchmark.load.run`, `benchmark.workspace.{build, deploy, fixed_copy}`, `benchmark.scenarios.by_id`, `sentinel.telemetry.Collector`, `sentinel.pipeline.analyze`, `sentinel.audit.AuditLog`, `sentinel.llm.available`, `sentinel.registry.load_registry`, `enrich.{slim_sample, stage_payload, build_result}`, `RunContext.emit_result`.
- Produces: `live.run_live(ctx, scenario_id: str, seed: int, use_llm: bool, run_id: str) -> None`. Event order: `service` (per tenant up), `telemetry`…, `deploy`, `telemetry`…, `stage`…, `result`. Traffic seconds default 15 before and after; env `PANEL_LIVE_SECONDS` overrides.

- [ ] **Step 1: Write the (opt-in) live test**

`tests/test_panel_live.py`:
```python
"""Real services and traffic: slow (about 1.5 minutes), so opt in with PANEL_LIVE_TEST=1."""
import os
import time

import pytest

from panel.bus import EventBus
from panel.paths import DEFAULT
from panel.runner import Runner

pytestmark = pytest.mark.skipif(not os.getenv("PANEL_LIVE_TEST"), reason="set PANEL_LIVE_TEST=1 to run live tests")


def test_live_f04_detects_and_confirms(monkeypatch):
    monkeypatch.setenv("PANEL_LIVE_SECONDS", "10")
    bus = EventBus()
    Runner(bus, DEFAULT).start("F04", "live", use_llm=False)
    deadline = time.time() + 240
    while time.time() < deadline:
        events, _ = bus.current_run()
        if any(e["kind"] == "run" and e["data"].get("state") in ("done", "failed") for e in events):
            break
        time.sleep(0.5)
    assert events[-1]["data"]["state"] == "done", events[-1]["data"]
    kinds = [e["kind"] for e in events]
    assert {"service", "telemetry", "deploy", "stage", "result"} <= set(kinds)
    result = next(e for e in events if e["kind"] == "result")["data"]
    assert result["incident"]["service"] == "inventory" and result["action"] == "code_fix"
    assert result["tests"]["template"]["confirming"] is True
```

- [ ] **Step 2: Write `panel/live.py`**

```python
"""Live run: start the three tenants, send traffic, deploy a faulty commit, analyse, and stream everything."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

from benchmark import load
from benchmark.record import start_service, stop, wait_ready
from benchmark.scenarios import by_id
from benchmark.workspace import build, deploy, fixed_copy
from panel import enrich
from sentinel import llm
from sentinel.audit import AuditLog
from sentinel.pipeline import analyze
from sentinel.registry import load_registry
from sentinel.telemetry import Collector

POLL_S = 0.5


def _seconds() -> float:
    return float(os.getenv("PANEL_LIVE_SECONDS", "15"))


class _Poller(threading.Thread):
    """Forward new collector samples to the bus as telemetry (and tenant up/down changes as service events)."""

    def __init__(self, ctx, collector: Collector, owners: dict[str, str]) -> None:
        super().__init__(daemon=True)
        self.ctx, self.collector, self.owners = ctx, collector, owners
        self._pos = 0
        self._up: dict[str, bool] = {}
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(POLL_S):
            self.flush()

    def stop(self) -> None:
        self._halt.set()
        self.join(2.0)
        self.flush()

    def flush(self) -> None:
        samples = self.collector.samples
        while self._pos < len(samples):
            sample = samples[self._pos]
            self._pos += 1
            name = sample["service"]
            if name in self._up and self._up[name] != sample["up"]:
                self.ctx.bus.emit("service", {"name": name, "owner": self.owners.get(name), "up": sample["up"], "pid": sample.get("pid")})
            self._up[name] = sample["up"]
            self.ctx.bus.emit("telemetry", enrich.slim_sample(sample))


class _AuditTail(threading.Thread):
    """Emit each audit line the pipeline writes as a stage event."""

    def __init__(self, ctx, path: Path) -> None:
        super().__init__(daemon=True)
        self.ctx, self.path = ctx, path
        self._pos = 0
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(0.3):
            self.flush()

    def stop(self) -> None:
        self._halt.set()
        self.join(2.0)
        self.flush()

    def flush(self) -> None:
        if not self.path.exists():
            return
        lines = self.path.read_text(encoding="utf-8").splitlines()
        while self._pos < len(lines):
            line = lines[self._pos]
            self._pos += 1
            if line.strip():
                self.ctx.bus.emit("stage", enrich.stage_payload(json.loads(line)))


def _traffic(urls: dict[str, str], seconds: float, multiplier: dict[str, int], seed: int) -> None:
    asyncio.run(load.run(urls, seconds, multiplier=multiplier, seed=seed))


def run_live(ctx, scenario_id: str, seed: int, use_llm: bool, run_id: str) -> None:
    scenario = by_id(scenario_id)
    base = ctx.paths.panel_data / run_id
    root = base / "ws"
    commits, truth = build(scenario, root, seed)
    registry = load_registry(root)
    owners = {s.name: s.owner for s in registry.services}
    processes: dict = {}
    collector = Collector(registry)
    poller = _Poller(ctx, collector, owners)
    try:
        for service in registry.services:
            processes[service.name] = start_service(root, registry, service.name)
        for service in registry.services:
            wait_ready(service.url)
            ctx.bus.emit("service", {"name": service.name, "owner": owners[service.name], "up": True, "pid": processes[service.name].pid})
        urls = {s.name: s.url for s in registry.services}
        collector.start()
        poller.start()
        _traffic(urls, _seconds(), {}, seed)

        change_time = time.time()
        changed = deploy(root, commits, scenario, truth)
        everything = bool(set(changed) & set(registry.shared_code))
        restart = [s.name for s in registry.services] if everything else [c for c in changed if c in processes]
        collector.mark("deployment", commits=[c.message for c in commits], restarted=restart)
        ctx.bus.emit("deploy", {"commits": [c.message for c in commits], "restarted": restart, "at": change_time})
        for name in restart:
            stop(processes[name])
            processes[name] = start_service(root, registry, name)
        for name in restart:
            wait_ready(registry.get(name).url)
        _traffic(urls, _seconds(), scenario.traffic_multiplier, seed + 1)
        end_time = time.time()
    finally:
        collector.stop()
        poller.stop()
        for process in processes.values():
            stop(process)

    recording = {"scenario": scenario_id, "seed": seed, "workspace": str(root), "change_time": change_time, "end_time": end_time,
                 "restarted": restart, "deployment": [c.message for c in commits], "truth": asdict(truth),
                 "samples": collector.samples, "events": collector.events}
    audit_path = base / "audit.jsonl"
    tail = _AuditTail(ctx, audit_path)
    tail.start()
    try:
        fixed = fixed_copy(root, scenario, base / "fixed")
        analysis = analyze(recording, AuditLog(audit_path), fixed_workspace=fixed, use_llm=bool(use_llm and llm.available()))
    finally:
        tail.stop()
    ctx.emit_result(enrich.build_result(recording, analysis))
```

- [ ] **Step 3: Run lint and the default (skipped) live test, then the live test once**

Run: `python -m ruff check panel tests; python -m pytest tests/test_panel_live.py -v`
Expected: lint clean; `1 skipped`.
Then run once for real: `$env:PANEL_LIVE_TEST="1"; python -m pytest tests/test_panel_live.py -v -s`
Expected: `1 passed` in about 1.5–2 minutes. If it fails with "port 910x already in use", close stray Python processes first.

---

### Task 6: HTTP server, SSE, CLI

**Files:**
- Create: `panel/server.py`, `panel/__main__.py`
- Create: `panel/static/index.html` (minimal placeholder: `<!doctype html><title>Sentinel Console</title>`; replaced in Task 7)
- Create: `tests/test_panel_server.py`

**Interfaces:**
- Consumes: `Runner`, `EventBus`, `results.load_results`, `enrich.read_source`, `sentinel.llm.available`, `sentinel.registry.load_registry`, `benchmark.scenarios.SCENARIOS`.
- Produces: `server.create_app(paths: Paths = DEFAULT, speed: float = 3.0) -> FastAPI`. Routes: `GET /api/scenarios`, `POST /api/run`, `GET /api/state`, `GET /api/events?since=&until_done=`, `GET /api/results`, `GET /api/code?path=&run=`, `POST /api/approve`, `GET /api/audit`; static files at `/`.
- Response contracts: `/api/scenarios` → `[{id,title,service,fault_class,expected_action,replay_available,code_available}]` (no file/line truth); `/api/run` → `{"run": {...}, "since": int}`; `/api/state` → `{run, events, next, tenants:[{name,owner,port}], llm_available, server}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_panel_server.py`:
```python
import json
import time

import pytest
from fastapi.testclient import TestClient

from panel.server import create_app


@pytest.fixture()
def client(panel_root):
    with TestClient(create_app(panel_root, speed=100000)) as c:
        yield c


def finish(client, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/state").json()
        last = [e for e in state["events"] if e["kind"] == "run"][-1:]
        if last and last[0]["data"]["state"] in ("done", "failed"):
            return state
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_scenario_catalog_hides_the_answer_and_flags_availability(client):
    scenarios = client.get("/api/scenarios").json()
    assert [s["id"] for s in scenarios][:2] == ["F01", "F02"] and len(scenarios) == 15
    assert all({"file", "start_line", "end_line", "fault", "patches"}.isdisjoint(s) for s in scenarios)
    flags = {s["id"]: s["replay_available"] for s in scenarios}
    assert flags["F01"] is True and flags["F02"] is False


def test_run_replay_then_state_recovers_the_whole_run(client):
    started = client.post("/api/run", json={"scenario": "F01", "mode": "replay"})
    assert started.status_code == 200 and started.json()["run"]["scenario"] == "F01"
    state = finish(client)  # a refreshed page or second tab calls the same endpoint
    kinds = [e["kind"] for e in state["events"]]
    assert kinds[0] == "run" and "result" in kinds and state["next"] >= len(state["events"])
    assert [t["name"] for t in state["tenants"]] == ["orders", "inventory", "payments"]
    assert state["run"]["id"] == started.json()["run"]["id"]


def test_sse_streams_events_until_the_run_is_done(client):
    since = client.post("/api/run", json={"scenario": "F01", "mode": "replay"}).json()["since"]
    seen = []
    with client.stream("GET", f"/api/events?since={since}&until_done=1") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]))
    assert seen[0]["kind"] == "run" and seen[-1]["data"]["state"] == "done"
    assert [e["n"] for e in seen] == sorted(e["n"] for e in seen)


def test_errors_for_bad_run_requests(client):
    assert client.post("/api/run", json={"scenario": "F99", "mode": "replay"}).status_code == 404
    assert client.post("/api/run", json={"scenario": "F02", "mode": "replay"}).status_code == 503
    assert client.post("/api/run", json={"scenario": "F01", "mode": "warp"}).status_code == 422


def test_code_endpoint_serves_workspace_files_and_refuses_traversal(client):
    client.post("/api/run", json={"scenario": "F01", "mode": "replay"})
    finish(client)
    ok = client.get("/api/code", params={"path": "orders/app.py"})
    assert ok.status_code == 200 and "def list_orders" in ok.json()["text"]
    assert client.get("/api/code", params={"path": "../services.yaml"}).status_code == 400
    assert client.get("/api/code", params={"path": "/etc/passwd"}).status_code == 400
    assert client.get("/api/code", params={"path": "orders/nope.py"}).status_code == 404
    assert client.get("/api/code", params={"path": "orders/app.py", "run": "other"}).status_code == 404


def test_approve_validates_and_records_without_touching_code(client):
    assert client.post("/api/approve", json={"approver": "Akash", "note": ""}).status_code == 409  # no run yet
    client.post("/api/run", json={"scenario": "F01", "mode": "replay"})
    finish(client)
    assert client.post("/api/approve", json={"approver": "", "note": ""}).status_code == 422
    done = client.post("/api/approve", json={"approver": "Akash", "note": "ship it"})
    assert done.status_code == 200 and done.json()["decision"] == "approved"
    audit = client.get("/api/audit").json()
    assert audit[-1]["decision"] == "approved" and audit[0]["stage"] == "detect"


def test_results_endpoint_and_static_index(client, panel_root):
    results = client.get("/api/results").json()
    assert results["available"] is True and results["runs"] == 1
    page = client.get("/")
    assert page.status_code == 200 and "Sentinel Console" in page.text
```
(A busy-run 409 is covered at the runner level in Task 4; at HTTP level add this test to the same file:)
```python
def test_second_run_request_is_a_409(panel_root, monkeypatch):
    import threading

    from panel import replay

    gate = threading.Event()
    monkeypatch.setattr(replay, "run_replay", lambda ctx, *a: gate.wait(5))
    with TestClient(create_app(panel_root)) as client:
        assert client.post("/api/run", json={"scenario": "F01", "mode": "replay"}).status_code == 200
        assert client.post("/api/run", json={"scenario": "F01", "mode": "replay"}).status_code == 409
        gate.set()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_panel_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'panel.server'`.

- [ ] **Step 3: Write `panel/server.py`, `panel/__main__.py`, `panel/static/index.html`**

`panel/server.py`:
```python
"""HTTP API, server-sent events and static files for the console."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from benchmark.scenarios import SCENARIOS
from panel import enrich, results
from panel.bus import EventBus
from panel.paths import DEFAULT, Paths
from panel.runner import Busy, NotReady, Runner, Unavailable
from sentinel import llm
from sentinel.registry import load_registry

STATIC = Path(__file__).parent / "static"
TERMINAL = ("done", "failed")


class RunRequest(BaseModel):
    scenario: str
    mode: Literal["live", "replay"] = "replay"
    llm: bool = True
    seed: int = Field(default=0, ge=0, le=9)


class ApproveRequest(BaseModel):
    approver: str = Field(min_length=2, max_length=60)
    note: str = Field(default="", max_length=300)


def create_app(paths: Paths = DEFAULT, speed: float = 3.0) -> FastAPI:
    app = FastAPI(title="Sentinel Console")
    bus = EventBus()
    runner = Runner(bus, paths, speed)
    registry = load_registry(paths.root / "shared_server")

    @app.get("/api/scenarios")
    def scenarios() -> list[dict]:
        return [{"id": s.id, "title": s.title, "service": s.service, "fault_class": s.fault_class, "expected_action": s.expected_action,
                 "replay_available": runner.replay_available(s.id, 0), "code_available": (paths.bench / f"{s.id}-s0").exists()}
                for s in SCENARIOS]

    @app.post("/api/run")
    def run(request: RunRequest) -> dict:
        try:
            return runner.start(request.scenario, request.mode, request.llm, request.seed)
        except KeyError:
            raise HTTPException(404, f"unknown scenario {request.scenario}") from None
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None
        except Unavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/api/state")
    def state() -> dict:
        events, following = bus.current_run()
        return {"run": runner.public(), "events": events, "next": following, "server": registry.server,
                "tenants": [{"name": s.name, "owner": s.owner, "port": s.port} for s in registry.services],
                "llm_available": llm.available()}

    @app.get("/api/events")
    def events(since: int = Query(0, ge=0), until_done: bool = False) -> StreamingResponse:
        def stream():
            position = since
            while True:
                batch = bus.wait(position, timeout=10.0)
                for event in batch:
                    yield f"id: {event['n']}\ndata: {json.dumps(event)}\n\n"
                if not batch:
                    yield ": keepalive\n\n"
                    continue
                position = batch[-1]["n"] + 1
                if until_done and any(e["kind"] == "run" and e["data"].get("state") in TERMINAL for e in batch):
                    return

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/results")
    def benchmark_results() -> dict:
        return results.load_results(paths)

    @app.get("/api/code")
    def code(path: str, run: str | None = None) -> dict:
        workspace = runner.workspace(run)
        if workspace is None or not workspace.exists():
            raise HTTPException(404, "no workspace for this run")
        try:
            return {"path": path, "text": enrich.read_source(workspace, path)}
        except FileNotFoundError:
            raise HTTPException(404, path) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/approve")
    def approve(request: ApproveRequest) -> dict:
        try:
            return runner.approve(request.approver.strip(), request.note.strip())
        except NotReady as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/audit")
    def audit() -> list[dict]:
        events, _ = bus.current_run()
        return [e["data"] for e in events if e["kind"] == "stage"]

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
```

`panel/__main__.py`:
```python
"""python -m panel [--port 8080] [--speed 3] [--no-browser]"""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from panel.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m panel", description="Sentinel Console")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--speed", type=float, default=3.0, help="replay speed multiplier (default 3)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Sentinel Console on {url}  (replay speed {args.speed}x)")
    uvicorn.run(create_app(speed=args.speed), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
```

`panel/static/index.html` (placeholder):
```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Sentinel Console</title></head><body>Sentinel Console</body></html>
```

- [ ] **Step 4: Run tests and lint**

Run: `python -m pytest tests/test_panel_server.py -v; python -m ruff check panel tests`
Expected: 8 passed; `All checks passed!`

- [ ] **Step 5: Smoke the real CLI against real data**

Run: `python -m panel --no-browser --port 8765` in a background shell, then `Invoke-RestMethod http://127.0.0.1:8765/api/scenarios | Select-Object -First 3` and `Invoke-RestMethod http://127.0.0.1:8765/api/results | ConvertTo-Json -Depth 2 | Select-Object -First 5`.
Expected: F01–F03 listed with `replay_available: True`; results `available: True`, `runs: 45`. Stop the server afterwards.

---

### Task 7: Frontend foundation and Project view

**Files:**
- Create: `panel/static/index.html` (replace), `panel/static/app.css`
- Create: `panel/static/js/{ui,store,api,charts,topbar,main}.js`, `panel/static/js/views/project.js`
- Create stub views so navigation works: `views/{floor,incident,trace,proof,decision,results}.js` each exporting `id`, `mount(root)` (sets a "coming in a later task" message) and `update()` (no-op). They are replaced in Tasks 8–10.

**Interfaces:**
- Produces (`ui.js`): `esc(s)`, `fmt(v, d=1)`, `pct(v)`, `setHTML(el, html)` (skips when unchanged), `chip(text, kind)`, `pill(text, kind)`, `icon(name)`.
- Produces (`store.js`): `S` (state), `on(fn)`, `changed()`, `apply(ev)`, `resetRun()`, `fmtT(ev)`, `focus()`, `worstRoute(service)`, `metricSeries(service, kind, route)`, `latest(service)`, `COLORS`.
- Produces (`api.js`): `api.{state, scenarios, results, run, approve, code}`, `connect(since, onEvent, onStatus)`.
- Produces (`charts.js`): `sparkline`, `lineChart`, `hbars`, `featureBar`, `FEATURES`, `callGraph`, `highlight`, `codeView`.
- Produces (`topbar.js`): `mountTopbar(el)`, `updateTopbar()`, `notice(text, action)`.
- View contract: each module exports `id`, `mount(root)`, `update()`.

- [ ] **Step 1: Write `index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel Console</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230b0d12'/%3E%3Ccircle cx='16' cy='16' r='8' fill='none' stroke='%237f8cf0' stroke-width='3'/%3E%3Ccircle cx='21.5' cy='10.5' r='3' fill='%23f08a3c'/%3E%3C/svg%3E">
<link rel="stylesheet" href="/app.css">
</head>
<body>
<div class="app">
  <aside class="rail">
    <div class="brand">
      <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true"><circle cx="16" cy="16" r="9" fill="none" stroke="var(--indigo)" stroke-width="3"/><circle cx="22" cy="10" r="3.4" fill="var(--orange)"/></svg>
      <div><b>Sentinel</b><span>console</span></div>
    </div>
    <nav id="nav"></nav>
    <div class="rail-foot" id="railfoot"></div>
  </aside>
  <div class="main">
    <header class="topbar" id="topbar"></header>
    <div id="notice"></div>
    <main id="view"></main>
  </div>
</div>
<script type="module" src="/js/main.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app.css`** (design tokens, shell, shared components, and every class the views in Tasks 8–10 use)

```css
:root {
  --bg: #0a0c11; --panel: #10131a; --panel-2: #151922; --raise: #1a1f2b;
  --line: #232837; --line-soft: #1a1e2a;
  --text: #e8eaf1; --muted: #8b92a8; --dim: #5a6177;
  --indigo: #7f8cf0; --indigo-d: #3d4fa0; --orange: #f08a3c; --green: #4cc38a; --red: #ef5b5b; --amber: #e6b450; --cyan: #5cc8d8;
  --font: system-ui, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace;
  --r: 10px;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text); font: 14px/1.5 var(--font); -webkit-font-smoothing: antialiased; }
button, input, select { font: inherit; color: inherit; }
.mono, .num { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.app { display: grid; grid-template-columns: 224px 1fr; min-height: 100vh; }

/* rail */
.rail { border-right: 1px solid var(--line); padding: 22px 14px; display: flex; flex-direction: column; gap: 22px; position: sticky; top: 0; height: 100vh; background: var(--bg); }
.brand { display: flex; align-items: center; gap: 10px; padding: 0 8px; }
.brand b { display: block; font-size: 16px; letter-spacing: .01em; line-height: 1.1; }
.brand span { font-size: 11px; color: var(--muted); letter-spacing: .14em; text-transform: uppercase; }
#nav { display: flex; flex-direction: column; gap: 2px; }
.nav-h { font-size: 10.5px; letter-spacing: .14em; text-transform: uppercase; color: var(--dim); padding: 14px 10px 6px; }
.nav-i { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 8px; color: var(--muted); text-decoration: none; position: relative; }
.nav-i:hover { background: var(--panel); color: var(--text); }
.nav-i.on { background: var(--raise); color: var(--text); }
.nav-i .ico { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; flex: none; }
.nav-i .dot { margin-left: auto; width: 7px; height: 7px; border-radius: 50%; background: var(--line); }
.nav-i .dot.lit { background: var(--green); box-shadow: 0 0 0 3px rgba(76,195,138,.15); }
.rail-foot { margin-top: auto; padding: 0 10px; color: var(--dim); font-size: 12px; line-height: 1.6; }
.rail-foot b { color: var(--muted); font-weight: 500; }

/* top bar */
.main { min-width: 0; }
.topbar { display: flex; align-items: center; gap: 14px; padding: 14px 28px; border-bottom: 1px solid var(--line); position: sticky; top: 0; background: rgba(10,12,17,.92); backdrop-filter: blur(8px); z-index: 5; }
.topbar .where { display: flex; flex-direction: column; margin-right: auto; }
.topbar .where small { font-size: 10.5px; letter-spacing: .14em; text-transform: uppercase; color: var(--dim); }
.topbar .where b { font-size: 15px; font-weight: 600; }
.seg { display: inline-flex; background: var(--panel); border: 1px solid var(--line); border-radius: 9px; padding: 2px; }
.seg button { background: none; border: 0; padding: 5px 12px; border-radius: 7px; color: var(--muted); cursor: pointer; }
.seg button.on { background: var(--raise); color: var(--text); box-shadow: inset 0 0 0 1px var(--line); }
select.pick { background: var(--panel); border: 1px solid var(--line); border-radius: 9px; padding: 7px 10px; min-width: 250px; max-width: 320px; }
.toggle { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); cursor: pointer; user-select: none; }
.toggle input { accent-color: var(--indigo); }
.toggle.off { opacity: .4; pointer-events: none; }
.btn { background: var(--indigo); color: #0a0c11; border: 0; border-radius: 9px; padding: 8px 16px; font-weight: 600; cursor: pointer; }
.btn:hover { filter: brightness(1.08); }
.btn:disabled { background: var(--raise); color: var(--dim); cursor: default; }
.btn.ghost { background: transparent; color: var(--text); box-shadow: inset 0 0 0 1px var(--line); }
.state { display: inline-flex; align-items: center; gap: 8px; min-width: 120px; color: var(--muted); font-family: var(--mono); font-size: 12.5px; }
.state i { width: 8px; height: 8px; border-radius: 50%; background: var(--dim); }
.state.running i { background: var(--orange); animation: pulse 1.1s ease-in-out infinite; }
.state.done i { background: var(--green); }
.state.failed i { background: var(--red); }
@keyframes pulse { 50% { opacity: .35; } }
#notice:empty { display: none; }
.notice { margin: 14px 28px 0; padding: 10px 14px; border: 1px solid #5a2f2f; background: rgba(239,91,91,.08); border-radius: 9px; display: flex; gap: 12px; align-items: center; }
.notice span { margin-right: auto; }

/* content */
#view { padding: 26px 28px 60px; max-width: 1560px; }
.sec-h { display: flex; align-items: baseline; gap: 12px; margin: 30px 0 12px; }
.sec-h:first-child { margin-top: 0; }
.sec-h h2 { margin: 0; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
.sec-h .sub { color: var(--dim); font-size: 12.5px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r); padding: 18px 20px; }
.card.flat { background: transparent; }
.label { font-size: 10.5px; letter-spacing: .14em; text-transform: uppercase; color: var(--dim); }
.big { font-family: var(--mono); font-size: 34px; font-weight: 600; letter-spacing: -.02em; line-height: 1.1; font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); } .dim { color: var(--dim); }
.empty { padding: 60px 24px; text-align: center; color: var(--muted); border: 1px dashed var(--line); border-radius: var(--r); }
.empty b { display: block; color: var(--text); font-size: 15px; margin-bottom: 4px; }
.cols { display: grid; gap: 18px; }
.cols.c2 { grid-template-columns: 1.65fr 1fr; } .cols.c3 { grid-template-columns: repeat(3, 1fr); } .cols.c4 { grid-template-columns: repeat(4, 1fr); } .cols.eq2 { grid-template-columns: 1fr 1fr; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 99px; font-size: 11.5px; background: var(--raise); color: var(--muted); border: 1px solid var(--line); white-space: nowrap; }
.chip.indigo { color: var(--indigo); } .chip.orange { color: var(--orange); } .chip.green { color: var(--green); } .chip.red { color: var(--red); }
.pill { display: inline-block; padding: 2px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; background: var(--raise); color: var(--muted); }
.pill.ok { background: rgba(76,195,138,.14); color: var(--green); } .pill.bad { background: rgba(239,91,91,.14); color: var(--red); } .pill.warn { background: rgba(230,180,80,.14); color: var(--amber); } .pill.info { background: rgba(127,140,240,.14); color: var(--indigo); }
table.t { width: 100%; border-collapse: collapse; font-size: 13px; }
table.t th { text-align: left; font-weight: 500; font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--dim); padding: 0 10px 8px 0; }
table.t td { padding: 8px 10px 8px 0; border-top: 1px solid var(--line-soft); vertical-align: top; }
table.t td.n { font-family: var(--mono); text-align: right; font-variant-numeric: tabular-nums; }

/* stats strip */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); border-radius: var(--r); background: var(--panel); }
.stat { padding: 16px 20px; border-right: 1px solid var(--line); }
.stat:last-child { border-right: 0; }
.stat .big { margin-top: 6px; } .stat .sub { color: var(--muted); font-size: 12.5px; margin-top: 2px; }

/* tenant tiles */
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-top: 18px; }
.tile { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r); padding: 16px 18px 14px; transition: border-color .35s, box-shadow .35s; }
.tile.hot { border-color: #7a4a24; box-shadow: 0 0 0 1px rgba(240,138,60,.25), 0 8px 30px rgba(240,138,60,.07); }
.tile.down { border-color: #6b2c2c; }
.tile-h { display: flex; align-items: center; gap: 10px; }
.tile-h b { font-size: 15px; } .tile-h .own { margin-left: auto; }
.dotl { width: 8px; height: 8px; border-radius: 50%; background: var(--dim); transition: background .3s; }
.dotl.up { background: var(--green); } .dotl.dn { background: var(--red); }
.tile .val { margin: 12px 0 0; display: flex; align-items: baseline; gap: 8px; }
.tile .val .big { font-size: 30px; } .tile .val small { color: var(--muted); }
.tile .route { color: var(--dim); font-family: var(--mono); font-size: 12px; margin-top: 2px; }
.spark { display: block; width: 100%; height: 54px; margin-top: 8px; overflow: visible; }
.spark-mark { stroke: var(--orange); stroke-width: 1; stroke-dasharray: 3 3; vector-effect: non-scaling-stroke; }
.mini { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line-soft); }
.mini div { display: flex; flex-direction: column; } .mini .label { margin-bottom: 1px; } .mini b { font-family: var(--mono); font-weight: 500; font-size: 13px; font-variant-numeric: tabular-nums; }

/* pipeline */
.steps { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0; position: relative; }
.step { padding: 14px 16px 16px; border: 1px solid var(--line); background: var(--panel); position: relative; transition: background .4s, border-color .4s; min-height: 118px; }
.step:first-child { border-radius: var(--r) 0 0 var(--r); } .step:last-child { border-radius: 0 var(--r) var(--r) 0; } .step + .step { border-left: 0; }
.step .no { font-family: var(--mono); color: var(--dim); font-size: 12px; }
.step b { display: block; margin-top: 2px; font-size: 14.5px; }
.step .res { color: var(--muted); font-size: 12.5px; margin-top: 6px; min-height: 36px; }
.step .tm { position: absolute; right: 14px; top: 14px; font-family: var(--mono); font-size: 12px; color: var(--dim); }
.step::after { content: ""; position: absolute; left: 0; bottom: 0; height: 3px; width: 0; background: var(--indigo); transition: width .6s cubic-bezier(.2,.8,.2,1); border-radius: 0 0 0 var(--r); }
.step.active { background: var(--panel-2); border-color: #3a4172; } .step.active::after { width: 40%; background: var(--orange); animation: scan 1.6s ease-in-out infinite; }
.step.done { background: var(--panel-2); } .step.done::after { width: 100%; background: var(--green); }
@keyframes scan { 0% { margin-left: 0; } 50% { margin-left: 60%; } 100% { margin-left: 0; } }
.log { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r); padding: 10px 16px; font-family: var(--mono); font-size: 12.5px; max-height: 220px; overflow: auto; }
.log div { display: flex; gap: 14px; padding: 3px 0; color: var(--muted); } .log div b { color: var(--dim); font-weight: 400; min-width: 54px; } .log div.k-stage { color: var(--text); }

/* charts */
.chart { width: 100%; height: auto; display: block; }
.chart text { font-family: var(--mono); font-size: 11px; fill: var(--dim); }
.chart .grid { stroke: var(--line-soft); } .chart .axis { stroke: var(--line); }
.legend { display: flex; gap: 18px; flex-wrap: wrap; color: var(--muted); font-size: 12.5px; margin-top: 10px; }
.legend i { display: inline-block; width: 18px; height: 0; border-top: 2px solid; vertical-align: middle; margin-right: 6px; }
.hbars { display: flex; flex-direction: column; gap: 7px; }
.hb { display: grid; grid-template-columns: 170px 1fr 54px; align-items: center; gap: 12px; font-size: 13px; }
.hb-l { color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .hb-l.hi { color: var(--text); font-weight: 600; }
.hb-t { position: relative; height: 12px; background: var(--line-soft); border-radius: 4px; overflow: hidden; }
.hb-t i { position: absolute; inset: 0 auto 0 0; border-radius: 4px; } .hb-t i.ghost { opacity: .28; }
.hb-v { font-family: var(--mono); text-align: right; font-variant-numeric: tabular-nums; }

/* trace */
.suspect { border: 1px solid var(--line); border-radius: var(--r); background: var(--panel); padding: 14px 16px; cursor: pointer; transition: border-color .2s, background .2s; }
.suspect + .suspect { margin-top: 10px; } .suspect:hover { border-color: #3a4172; } .suspect.on { border-color: var(--indigo); background: var(--panel-2); }
.suspect-h { display: flex; align-items: center; gap: 12px; }
.rank { font-family: var(--mono); font-weight: 600; width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; background: var(--raise); }
.suspect:first-child .rank { background: var(--indigo); color: #0a0c11; }
.suspect-h b { font-size: 14.5px; } .suspect-h .score { margin-left: auto; font-family: var(--mono); color: var(--muted); }
.suspect .where { font-family: var(--mono); font-size: 12px; color: var(--dim); margin: 2px 0 10px 40px; }
.fbar { margin-left: 40px; height: 9px; border-radius: 3px; background: var(--line-soft); overflow: hidden; display: flex; }
.fbar > div { display: flex; height: 100%; } .fbar i { display: block; height: 100%; }
.reasons { margin: 10px 0 0 40px; padding: 0; list-style: none; color: var(--muted); font-size: 12.5px; } .reasons li::before { content: "› "; color: var(--dim); }
.flegend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: var(--muted); margin-bottom: 12px; } .flegend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
.code { background: #0c0f15; border: 1px solid var(--line); border-radius: var(--r); font-family: var(--mono); font-size: 12.5px; line-height: 1.6; overflow: auto; max-height: 420px; }
.code .ln { display: flex; min-width: max-content; } .code .no { width: 46px; flex: none; text-align: right; padding-right: 12px; color: var(--dim); user-select: none; }
.code .tx { white-space: pre; padding-right: 16px; } .code .ln.hit { background: rgba(127,140,240,.1); } .code .ln.chg .no { color: var(--orange); box-shadow: inset 3px 0 var(--orange); }
.code .ln.truth { background: rgba(76,195,138,.12); } .code .ln.truth .no { color: var(--green); }
.code .gap { color: var(--dim); padding: 4px 0 4px 46px; }
.t-k { color: #c792ea; } .t-s { color: #a8d08d; } .t-c { color: #667089; font-style: italic; } .t-n { color: #f0b072; }
.code-h { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; font-family: var(--mono); font-size: 12.5px; color: var(--muted); }
.commit { display: flex; gap: 10px; padding: 8px 0; border-top: 1px solid var(--line-soft); font-size: 13px; } .commit:first-child { border-top: 0; }
.commit code { font-family: var(--mono); color: var(--dim); } .commit.cul { color: var(--text); } .commit.cul code { color: var(--orange); } .commit .chip { margin-left: auto; }
.graph text { font-family: var(--mono); font-size: 11.5px; fill: var(--text); } .graph .gn { fill: var(--panel-2); stroke: var(--line); } .graph .gn.f { stroke: var(--orange); stroke-width: 1.6; } .graph .ge { fill: none; stroke: #3a4172; stroke-width: 1.4; }

/* proof */
.proof { display: grid; gap: 18px; grid-template-columns: 1fr 1fr; }
.run-card { border: 1px solid var(--line); border-radius: var(--r); padding: 14px 16px; background: var(--panel); }
.run-card.red { border-color: #6b2c2c; } .run-card.green { border-color: #1f5a41; }
.run-card .out { margin-top: 8px; font-family: var(--mono); font-size: 12.5px; color: var(--muted); white-space: pre-wrap; word-break: break-word; max-height: 90px; overflow: auto; }
.verdict { margin: 14px 0; padding: 12px 16px; border-radius: var(--r); border: 1px solid var(--line); display: flex; gap: 12px; align-items: center; }
.verdict.ok { border-color: #1f5a41; background: rgba(76,195,138,.07); } .verdict.no { border-color: #6b2c2c; background: rgba(239,91,91,.07); }

/* decision */
.gauge { display: grid; place-items: center; width: 150px; height: 150px; position: relative; flex: none; } .gauge svg { position: absolute; inset: 0; transform: rotate(-90deg); } .gauge .big { font-size: 30px; }
.action { font-family: var(--mono); font-size: 26px; font-weight: 600; letter-spacing: -.01em; }
.ticks { list-style: none; padding: 0; margin: 14px 0 0; display: grid; gap: 7px; } .ticks li { display: flex; gap: 10px; align-items: center; color: var(--muted); } .ticks li i { width: 16px; height: 16px; border-radius: 50%; display: grid; place-items: center; font-style: normal; font-size: 10px; background: var(--raise); color: var(--dim); } .ticks li.y { color: var(--text); } .ticks li.y i { background: rgba(76,195,138,.18); color: var(--green); }
.form { display: grid; gap: 10px; margin-top: 16px; } .form input { background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 9px 12px; } .form input:focus { outline: 0; border-color: var(--indigo); }
.timeline { position: relative; padding-left: 22px; } .timeline::before { content: ""; position: absolute; left: 6px; top: 6px; bottom: 6px; width: 1px; background: var(--line); }
.tl { position: relative; padding: 0 0 18px; } .tl::before { content: ""; position: absolute; left: -21px; top: 5px; width: 9px; height: 9px; border-radius: 50%; background: var(--indigo); box-shadow: 0 0 0 3px var(--bg); } .tl.ok::before { background: var(--green); }
.tl b { font-size: 13.5px; } .tl .meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; } .tl time { float: right; font-family: var(--mono); font-size: 12px; color: var(--dim); }
.not { margin-top: 16px; font-size: 12.5px; color: var(--muted); } .not li { margin: 3px 0; }

/* results */
.heat { display: grid; grid-template-columns: 220px repeat(6, 1fr); gap: 4px; font-size: 12px; } .heat .hh { color: var(--dim); font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; padding: 0 0 4px; } .heat .rl { padding: 7px 0; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .heat .rl b { color: var(--text); font-family: var(--mono); margin-right: 8px; }
.cell { display: flex; gap: 3px; padding: 4px; background: var(--panel); border: 1px solid var(--line-soft); border-radius: 6px; } .cell i { flex: 1; height: 18px; border-radius: 3px; display: grid; place-items: center; font-style: normal; font-family: var(--mono); font-size: 10.5px; color: #0a0c11; font-weight: 600; background: var(--raise); }
.cell i.r1 { background: var(--green); } .cell i.r2 { background: #8fd08a; } .cell i.r3 { background: var(--amber); } .cell i.rx { background: #e58a5a; } .cell i.miss { background: var(--red); color: #fff; } .cell i.na { background: transparent; color: var(--dim); }
.fail { display: grid; grid-template-columns: 110px 70px 1fr; gap: 12px; padding: 7px 0; border-top: 1px solid var(--line-soft); font-size: 13px; } .fail:first-child { border-top: 0; } .fail .id { font-family: var(--mono); color: var(--muted); }
.kpi { display: flex; flex-direction: column; gap: 4px; } .kpi .delta { color: var(--muted); font-size: 12.5px; }

/* project */
.rq { font-family: var(--font); font-size: 22px; line-height: 1.4; letter-spacing: -.01em; max-width: 980px; }
.who { display: flex; flex-direction: column; gap: 8px; } .who .tag { align-self: flex-start; }
.who ul, .plain { margin: 6px 0 0; padding-left: 18px; color: var(--muted); } .who li, .plain li { margin: 3px 0; }
.stepcard .no { font-family: var(--mono); color: var(--indigo); } .stepcard b { display: block; margin: 2px 0 6px; } .stepcard p { margin: 0; color: var(--muted); font-size: 13px; }
@media (max-width: 1250px) { .app { grid-template-columns: 76px 1fr; } .brand div, .nav-i span, .nav-h, .rail-foot { display: none; } .tiles, .cols.c3 { grid-template-columns: 1fr; } .steps { grid-template-columns: repeat(3, 1fr); } .cols.c2 { grid-template-columns: 1fr; } }
```

- [ ] **Step 3: Write `ui.js`, `store.js`, `api.js`**

`panel/static/js/ui.js`:
```js
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmt = (v, d = 1) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d));
export const pct = v => (v == null || Number.isNaN(Number(v)) ? '—' : `${Math.round(v * 100)}%`);
export function setHTML(el, html) {
  if (el && el.__html !== html) { el.innerHTML = html; el.__html = html; }
}
export const chip = (text, kind = '') => `<span class="chip ${kind}">${esc(text)}</span>`;
export const pill = (text, kind = '') => `<span class="pill ${kind}">${esc(text)}</span>`;
const ICONS = {
  floor: '<rect x="2.5" y="3" width="6" height="6" rx="1.2"/><rect x="11.5" y="3" width="6" height="6" rx="1.2"/><rect x="2.5" y="11" width="6" height="6" rx="1.2"/><rect x="11.5" y="11" width="6" height="6" rx="1.2"/>',
  incident: '<path d="M2 10h3.5l2-5 3 10 2-5H18"/>',
  trace: '<circle cx="5" cy="4.5" r="1.8"/><circle cx="5" cy="15.5" r="1.8"/><circle cx="15" cy="9" r="1.8"/><path d="M5 6.3v7.4M5 11c0-2 2-2 6-2h2.2"/>',
  proof: '<circle cx="10" cy="10" r="7.5"/><path d="M6.5 10.2l2.5 2.5 4.6-5"/>',
  decision: '<path d="M10 2.5l6 2.2v4.6c0 3.6-2.5 6.4-6 8-3.5-1.6-6-4.4-6-8V4.7z"/>',
  results: '<path d="M4 16V9M10 16V4M16 16v-5"/>',
  project: '<circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.2v.1"/>',
};
export const icon = name => `<svg class="ico" viewBox="0 0 20 20" aria-hidden="true">${ICONS[name] || ''}</svg>`;
```

`panel/static/js/store.js`:
```js
export const COLORS = { indigo: 'var(--indigo)', orange: 'var(--orange)', green: 'var(--green)', red: 'var(--red)', amber: 'var(--amber)', cyan: 'var(--cyan)', dim: 'var(--dim)' };
export const S = {
  next: 0, status: 'idle', reason: null, run: null, startedAt: null, endedAt: null,
  server: '', tenants: [], scenarios: [], llmAvailable: false, connected: false,
  services: {}, tele: {}, deploy: null, stages: [], result: null, approval: null, log: [], results: null,
};
const listeners = new Set();
export const on = fn => (listeners.add(fn), () => listeners.delete(fn));
let queued = false;
export function changed() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; listeners.forEach(fn => fn(S)); });
}
export function resetRun() {
  Object.assign(S, { status: 'idle', reason: null, run: null, startedAt: null, endedAt: null, services: {}, tele: {}, deploy: null, stages: [], result: null, approval: null, log: [] });
}
export const fmtT = ev => `+${((ev.t - (S.startedAt ?? ev.t))).toFixed(1)}s`;

function describe(ev) {
  const d = ev.data;
  switch (ev.kind) {
    case 'run': return d.state === 'started' ? `run started · ${d.scenario} · ${d.mode}` : `run ${d.state}${d.reason ? ' · ' + d.reason : ''}`;
    case 'service': return `${d.name} ${d.up ? 'up' : 'down'}`;
    case 'deploy': return `deployed ${d.commits.length} commits · restarted ${d.restarted.join(', ')}`;
    case 'stage': return `${d.stage}${d.method ? ' · ' + d.method : ''}${d.generator ? ' · ' + d.generator : ''} → ${d.decision}`;
    case 'result': return 'diagnosis ready';
    default: return null;
  }
}

export function apply(ev) {
  if (ev.n < S.next) return;
  S.next = ev.n + 1;
  const d = ev.data;
  switch (ev.kind) {
    case 'run':
      if (d.state === 'started') { resetRun(); S.run = d; S.status = 'running'; S.startedAt = ev.t; }
      else { S.status = d.state; S.reason = d.reason || null; S.endedAt = ev.t; }
      break;
    case 'service': S.services[d.name] = { ...S.services[d.name], ...d }; break;
    case 'telemetry': {
      const rows = (S.tele[d.service] ||= []);
      rows.push(d);
      if (rows.length > 600) rows.shift();
      S.services[d.service] = { ...S.services[d.service], up: d.up };
      break;
    }
    case 'deploy': S.deploy = { ...d, t: ev.t }; break;
    case 'stage':
      if (d.decision === 'approved') S.approval = d;
      S.stages.push({ ...d, t: ev.t });
      break;
    case 'result': S.result = d; break;
  }
  const text = describe(ev);
  if (text) { S.log.push({ t: ev.t, kind: ev.kind, text }); if (S.log.length > 200) S.log.shift(); }
  changed();
}

export function worstRoute(service) {
  const best = {};
  (S.tele[service] || []).forEach(s => Object.entries(s.routes).forEach(([r, v]) => { best[r] = Math.max(best[r] || 0, v.p95_ms); }));
  return Object.entries(best).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

export function focus() {
  const inc = S.result?.incident;
  if (inc) {
    const sig = inc.signals.find(s => s.kind === 'latency' && s.route) || inc.signals.find(s => s.route) || inc.signals[0];
    return { service: inc.service, route: sig?.route ?? null, kind: sig?.kind ?? 'latency' };
  }
  const det = S.stages.find(s => s.stage === 'detect')?.incidents?.[0];
  if (det) return { service: det.service, route: worstRoute(det.service), kind: det.symptoms[0] === 'traffic' ? 'latency' : det.symptoms[0] };
  return null;
}

export function metricSeries(service, kind, route) {
  return (S.tele[service] || []).map(s => {
    let v = null;
    if (!s.up) v = null;
    else if (kind === 'cpu') v = s.cpu;
    else if (kind === 'memory') v = s.rss_mb;
    else if (kind === 'errors') { const r = route ? s.routes[route] : null; v = r && r.count ? r.errors / r.count : null; }
    else v = route ? (s.routes[route]?.p95_ms ?? null) : null;
    return [s.t, v];
  });
}
export const latest = service => { const rows = S.tele[service]; return rows?.[rows.length - 1]; };
```

`panel/static/js/api.js`:
```js
async function j(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(typeof body.detail === 'string' ? body.detail : (body.detail?.[0]?.msg || r.statusText)); e.status = r.status; throw e; }
  return body;
}
const post = (url, body) => j(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
export const api = {
  state: () => j('/api/state'),
  scenarios: () => j('/api/scenarios'),
  results: () => j('/api/results'),
  run: body => post('/api/run', body),
  approve: body => post('/api/approve', body),
  code: path => j('/api/code?path=' + encodeURIComponent(path)),
};
export function connect(since, onEvent, onStatus) {
  const es = new EventSource('/api/events?since=' + since);
  es.onmessage = m => onEvent(JSON.parse(m.data));
  es.onopen = () => onStatus(true);
  es.onerror = () => onStatus(false);
  return es;
}
```

- [ ] **Step 4: Write `charts.js`**

```js
import { esc } from './ui.js';

export function sparkline(points, o = {}) {
  const { w = 260, h = 54, color = 'var(--indigo)', lo, hi, marks = [], fill = true } = o;
  const pts = points.filter(p => p[1] != null);
  if (pts.length < 2) return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"></svg>`;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const ys = pts.map(p => p[1]);
  const a = lo ?? Math.min(...ys), b = Math.max(hi ?? Math.max(...ys), a + 1e-6);
  const X = t => ((t - t0) / (t1 - t0 || 1)) * w;
  const Y = v => h - 3 - ((v - a) / (b - a)) * (h - 8);
  const d = pts.map(([t, v], i) => `${i ? 'L' : 'M'}${X(t).toFixed(1)} ${Y(v).toFixed(1)}`).join('');
  const area = fill ? `<path d="${d}L${w} ${h}L0 ${h}Z" fill="${color}" opacity=".12"/>` : '';
  const mk = marks.filter(t => t >= t0 && t <= t1).map(t => `<line x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="0" y2="${h}" class="spark-mark"/>`).join('');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${area}${mk}<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

const niceMax = v => {
  const steps = [1, 2, 2.5, 5, 10];
  const p = 10 ** Math.floor(Math.log10(v * 1.1 || 1));
  return steps.find(s => s >= (v * 1.1) / p) * p;
};

export function lineChart(o) {
  const { series, w = 900, h = 330, pad = { l: 58, r: 18, t: 16, b: 32 }, unit = '', marks = [], hlines = [], zones = [], t0, t1 } = o;
  const all = series.flatMap(s => s.points.filter(p => p[1] != null));
  if (all.length < 2) return `<svg class="chart" viewBox="0 0 ${w} ${h}"></svg>`;
  const xs = all.map(p => p[0]);
  const T0 = t0 ?? Math.min(...xs), T1 = t1 ?? Math.max(...xs);
  const top = o.yMax ?? niceMax(Math.max(...all.map(p => p[1]), ...hlines.map(l => l.y)));
  const X = t => pad.l + ((t - T0) / (T1 - T0 || 1)) * (w - pad.l - pad.r);
  const Y = v => h - pad.b - (v / top) * (h - pad.t - pad.b);
  let g = '';
  for (let i = 0; i <= 4; i++) {
    const v = (top * i) / 4;
    g += `<line class="grid" x1="${pad.l}" x2="${w - pad.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${pad.l - 10}" y="${Y(v) + 4}" text-anchor="end">${v >= 100 ? Math.round(v) : v.toFixed(1)}</text>`;
  }
  const span = T1 - T0;
  for (let i = 0; i <= 6; i++) {
    const t = T0 + (span * i) / 6;
    g += `<text x="${X(t)}" y="${h - 10}" text-anchor="middle">${Math.round(t - T0)}s</text>`;
  }
  const z = zones.map(zn => `<rect x="${X(zn.t0)}" y="${pad.t}" width="${Math.max(0, X(Math.min(zn.t1, T1)) - X(zn.t0))}" height="${h - pad.t - pad.b}" fill="${zn.color}" opacity="${zn.opacity ?? 0.07}"/>`).join('');
  const hl = hlines.map(l => `<line x1="${pad.l}" x2="${w - pad.r}" y1="${Y(l.y)}" y2="${Y(l.y)}" stroke="${l.color}" stroke-width="1.2" ${l.dash ? 'stroke-dasharray="5 5"' : ''}/><text x="${w - pad.r}" y="${Y(l.y) - 6}" text-anchor="end" style="fill:${l.color}">${esc(l.label)}</text>`).join('');
  const mk = marks.filter(m => m.t >= T0 && m.t <= T1).map(m => `<line x1="${X(m.t)}" x2="${X(m.t)}" y1="${pad.t}" y2="${h - pad.b}" stroke="${m.color}" stroke-width="1.4" stroke-dasharray="3 4"/><text x="${X(m.t) + 6}" y="${pad.t + 12}" style="fill:${m.color}">${esc(m.label)}</text>`).join('');
  const lines = series.map(s => {
    const pts = s.points.filter(p => p[1] != null);
    if (pts.length < 2) return '';
    const d = pts.map(([t, v], i) => `${i ? 'L' : 'M'}${X(t).toFixed(1)} ${Y(v).toFixed(1)}`).join('');
    const last = pts[pts.length - 1];
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/><circle cx="${X(last[0])}" cy="${Y(last[1])}" r="3.5" fill="${s.color}"/>`;
  }).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}"><text x="${pad.l}" y="10">${esc(unit)}</text>${z}${g}${hl}${mk}${lines}</svg>`;
}

export function hbars(rows, o = {}) {
  const { max = 1, format = v => `${Math.round(v * 100)}%` } = o;
  return `<div class="hbars">${rows.map(r => `<div class="hb"><div class="hb-l ${r.hi ? 'hi' : ''}" title="${esc(r.label)}">${esc(r.label)}</div><div class="hb-t">${r.ghost != null ? `<i class="ghost" style="width:${Math.min(100, (r.ghost / max) * 100)}%;background:${r.color || 'var(--indigo)'}"></i>` : ''}<i style="width:${Math.min(100, ((r.value ?? 0) / max) * 100)}%;background:${r.color || 'var(--indigo)'}"></i></div><div class="hb-v">${r.value == null ? '—' : format(r.value)}</div></div>`).join('')}</div>`;
}

export const FEATURES = [
  ['trace', 'Stack frame', 'var(--red)', 2.5], ['call_path', 'Call path', 'var(--orange)', 1.5], ['changed_lines', 'Changed lines', 'var(--indigo)', 1.5],
  ['route', 'Route handler', 'var(--amber)', 1], ['lexical', 'BM25', 'var(--cyan)', 1], ['dense', 'Embedding', 'var(--green)', 1], ['changed_file', 'Changed file', 'var(--dim)', 0.3],
];
export function featureBar(features, maxTotal) {
  const parts = FEATURES.map(([k, label, color, w]) => ({ label, color, v: (features[k] || 0) * w })).filter(p => p.v > 0);
  const total = parts.reduce((a, p) => a + p.v, 0);
  return `<div class="fbar"><div style="width:${Math.min(100, (total / maxTotal) * 100)}%">${parts.map(p => `<i title="${esc(p.label)}: ${p.v.toFixed(2)}" style="flex:${p.v};background:${p.color}"></i>`).join('')}</div></div>`;
}

export function callGraph({ nodes, edges }, focusId) {
  if (!nodes.length) return '';
  const colW = 196, rowH = 42, pad = 10, nw = 160, nh = 30;
  const cols = {};
  nodes.forEach(n => (cols[n.depth] ||= []).push(n));
  const maxDepth = Math.max(...nodes.map(n => n.depth));
  const rows = Math.max(...Object.values(cols).map(c => c.length));
  const pos = {};
  Object.entries(cols).forEach(([d, list]) => list.forEach((n, i) => { pos[n.id] = { x: pad + d * colW, y: pad + i * rowH }; }));
  const w = pad * 2 + maxDepth * colW + nw, h = pad * 2 + (rows - 1) * rowH + nh;
  const e = edges.map(ed => { const a = pos[ed.from], b = pos[ed.to]; if (!a || !b) return ''; const x1 = a.x + nw, y1 = a.y + nh / 2, x2 = b.x, y2 = b.y + nh / 2; const m = (x1 + x2) / 2; return `<path class="ge" d="M${x1} ${y1}C${m} ${y1} ${m} ${y2} ${x2} ${y2}"/>`; }).join('');
  const n = nodes.map(nd => { const p = pos[nd.id]; const name = nd.symbol.length > 22 ? nd.symbol.slice(0, 21) + '…' : nd.symbol; return `<g><rect class="gn ${nd.id === focusId ? 'f' : ''}" x="${p.x}" y="${p.y}" width="${nw}" height="${nh}" rx="7"/><text x="${p.x + 10}" y="${p.y + 19}">${esc(name)}</text></g>`; }).join('');
  return `<svg class="graph" viewBox="0 0 ${w} ${h}" width="100%">${e}${n}</svg>`;
}

const TOK = /(#.*$)|("""[\s\S]*?"""|'''[\s\S]*?''')|("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(def|class|return|if|elif|else|for|while|in|not|and|or|import|from|as|with|try|except|raise|assert|lambda|None|True|False|is|pass|yield|async|await|finally)\b|\b(\d+(?:\.\d+)?)\b/gm;
export function highlight(src) {
  let out = '', last = 0;
  src.replace(TOK, (m, c, ds, s, k, n, off) => {
    out += esc(src.slice(last, off));
    const cls = c ? 'c' : ds || s ? 's' : k ? 'k' : 'n';
    out += m.split('\n').map(p => `<span class="t-${cls}">${esc(p)}</span>`).join('\n');
    last = off + m.length;
    return m;
  });
  return out + esc(src.slice(last));
}

export function codeView(src, o = {}) {
  const { focus, changed = [], truth, ctx = 10 } = o;
  const lines = highlight(src).split('\n');
  let a = 1, b = Math.min(lines.length, 48);
  if (focus) { a = Math.max(1, focus[0] - ctx); b = Math.min(lines.length, focus[1] + ctx); }
  const inR = (n, r) => r && n >= r[0] && n <= r[1];
  const rows = [];
  if (a > 1) rows.push(`<div class="gap">⋯ ${a - 1} lines above</div>`);
  for (let n = a; n <= b; n++) {
    const cls = [inR(n, focus) ? 'hit' : '', changed.some(r => inR(n, r)) ? 'chg' : '', inR(n, truth) ? 'truth' : ''].join(' ');
    rows.push(`<div class="ln ${cls}"><span class="no">${n}</span><span class="tx">${lines[n - 1] || ' '}</span></div>`);
  }
  if (b < lines.length) rows.push(`<div class="gap">⋯ ${lines.length - b} lines below</div>`);
  return `<div class="code">${rows.join('')}</div>`;
}
```

- [ ] **Step 5: Write `topbar.js`, `main.js`, `views/project.js` and the stub views**

`panel/static/js/topbar.js`:
```js
import { S, changed } from './store.js';
import { api } from './api.js';
import { esc, setHTML } from './ui.js';

let mode = 'replay', scenario = 'F01', useLlm = true;
let el;
const keep = (k, v) => { try { localStorage.setItem('console.' + k, v); } catch { /* storage may be blocked */ } };
const read = (k, d) => { try { return localStorage.getItem('console.' + k) ?? d; } catch { return d; } };

export function notice(text, action) {
  const n = document.getElementById('notice');
  n.innerHTML = text ? `<div class="notice"><span>${esc(text)}</span>${action ? `<button class="btn ghost" id="notice-act">${esc(action.label)}</button>` : ''}</div>` : '';
  if (action) document.getElementById('notice-act').onclick = action.run;
}

async function run() {
  notice('');
  try { await api.run({ scenario, mode, llm: useLlm }); }
  catch (e) {
    notice(e.message, mode === 'live' && e.status === 503 ? { label: 'Switch to Replay', run: () => { mode = 'replay'; keep('mode', mode); notice(''); render(); } } : null);
  }
}

function options() {
  const group = (label, items) => `<optgroup label="${label}">${items.map(s => {
    const off = mode === 'replay' && !s.replay_available;
    return `<option value="${s.id}" ${s.id === scenario ? 'selected' : ''} ${off ? 'disabled' : ''}>${s.id} · ${esc(s.title)}${off ? ' (no recording)' : ''}</option>`;
  }).join('')}</optgroup>`;
  return group('Faults', S.scenarios.filter(s => s.id.startsWith('F'))) + group('Controls', S.scenarios.filter(s => s.id.startsWith('H')));
}

function render() {
  const running = S.status === 'running';
  el.querySelector('[data-r=mode]').innerHTML = `<button data-m="replay" class="${mode === 'replay' ? 'on' : ''}">Replay</button><button data-m="live" class="${mode === 'live' ? 'on' : ''}">Live</button>`;
  const pick = el.querySelector('select.pick');
  setHTML(pick, options());
  pick.value = scenario;
  pick.disabled = running;
  const tog = el.querySelector('.toggle');
  tog.classList.toggle('off', mode !== 'live' || running || !S.llmAvailable);
  el.querySelector('#llm').checked = useLlm && S.llmAvailable;
  const btn = el.querySelector('#run');
  btn.disabled = running;
  btn.textContent = running ? 'Running…' : 'Run';
  updateTopbar();
}

export function updateTopbar() {
  if (!el) return;
  const st = el.querySelector('.state');
  const secs = S.startedAt ? Math.max(0, (S.status === 'running' ? Date.now() / 1000 : (S.endedAt ?? Date.now() / 1000)) - S.startedAt) : 0;
  st.className = `state ${S.status}`;
  st.innerHTML = `<i></i>${S.status === 'idle' ? 'idle' : `${S.status} · ${secs.toFixed(0)}s`}`;
  el.querySelector('[data-r=where]').innerHTML = `<small>${esc(S.server || 'shared server')}</small><b>${S.run ? `${esc(S.run.scenario)} · ${S.run.mode}` : 'No run yet'}</b>`;
  const btn = el.querySelector('#run');
  if (btn) { btn.disabled = S.status === 'running'; btn.textContent = S.status === 'running' ? 'Running…' : 'Run'; }
}

export function mountTopbar(root) {
  el = root;
  mode = read('mode', 'replay'); scenario = read('scenario', 'F01'); useLlm = read('llm', '1') === '1';
  root.innerHTML = `<div class="where" data-r="where"></div><div class="seg" data-r="mode"></div><select class="pick" aria-label="Scenario"></select><label class="toggle"><input type="checkbox" id="llm"> LLM</label><button class="btn" id="run">Run</button><div class="state idle"><i></i>idle</div>`;
  root.querySelector('[data-r=mode]').onclick = e => { const m = e.target.dataset.m; if (m && S.status !== 'running') { mode = m; keep('mode', m); render(); } };
  root.querySelector('select.pick').onchange = e => { scenario = e.target.value; keep('scenario', scenario); };
  root.querySelector('#llm').onchange = e => { useLlm = e.target.checked; keep('llm', useLlm ? '1' : '0'); };
  root.querySelector('#run').onclick = run;
  setInterval(() => { if (S.status === 'running') updateTopbar(); }, 500);
  render();
  return { render, setScenario: id => { scenario = id; }, setMode: m => { mode = m; }, run };
}
export const refreshTopbar = () => el && render();
export { changed };
```
(Keep `changed` re-export out if unused; remove to satisfy lint if ruff/eslint complains: this is JS, no linter configured.)

`panel/static/js/main.js`:
```js
import { S, on, apply, changed } from './store.js';
import { api, connect } from './api.js';
import { icon } from './ui.js';
import { mountTopbar, updateTopbar, refreshTopbar, notice } from './topbar.js';
import * as floor from './views/floor.js';
import * as incident from './views/incident.js';
import * as trace from './views/trace.js';
import * as proof from './views/proof.js';
import * as decision from './views/decision.js';
import * as results from './views/results.js';
import * as project from './views/project.js';

const VIEWS = { floor, incident, trace, proof, decision, results, project };
const NAV = [
  ['LIVE RUN', [['floor', 'Live floor'], ['incident', 'Incident'], ['trace', 'Trace'], ['proof', 'Proof'], ['decision', 'Decision']]],
  ['REFERENCE', [['results', 'Results'], ['project', 'Project']]],
];
const LIT = {
  floor: () => S.status !== 'idle', incident: () => !!(S.result?.incident || S.stages.some(s => s.stage === 'detect')),
  trace: () => !!S.result, proof: () => !!S.result, decision: () => !!S.result, results: () => false, project: () => false,
};
let current = null;
const $ = s => document.querySelector(s);

function buildNav() {
  $('#nav').innerHTML = NAV.map(([h, items]) => `<div class="nav-h">${h}</div>${items.map(([id, label]) => `<a class="nav-i" href="#/${id}" data-id="${id}">${icon(id)}<span>${label}</span><i class="dot"></i></a>`).join('')}`).join('');
  $('#railfoot').innerHTML = '<b>AIOps Sentinel</b><br>Akash · Aryan · Syna';
}
function updateNav() {
  document.querySelectorAll('.nav-i').forEach(a => {
    a.classList.toggle('on', a.dataset.id === current);
    a.querySelector('.dot').classList.toggle('lit', LIT[a.dataset.id]());
  });
}
function route() {
  const id = (location.hash.match(/^#\/(\w+)/) || [])[1];
  current = VIEWS[id] ? id : 'floor';
  const root = $('#view');
  root.innerHTML = '';
  VIEWS[current].mount(root);
  VIEWS[current].update();
  updateNav();
}

async function init() {
  buildNav();
  const bar = mountTopbar($('#topbar'));
  const [st, sc] = await Promise.all([api.state(), api.scenarios()]);
  Object.assign(S, { tenants: st.tenants, server: st.server, llmAvailable: st.llm_available, scenarios: sc });
  st.events.forEach(apply);
  S.next = Math.max(S.next, st.next);
  refreshTopbar();
  route();
  window.addEventListener('hashchange', route);
  on(() => { VIEWS[current].update(); updateTopbar(); updateNav(); });
  connect(S.next, apply, ok => { S.connected = ok; changed(); });
  const q = new URLSearchParams(location.search);
  if (q.get('autorun')) {
    bar.setScenario(q.get('autorun')); bar.setMode(q.get('mode') || 'replay'); refreshTopbar();
    api.run({ scenario: q.get('autorun'), mode: q.get('mode') || 'replay', llm: true }).catch(e => notice(e.message));
  }
}
init().catch(e => { document.getElementById('view').innerHTML = `<div class="empty"><b>Console could not start</b>${e.message}</div>`; });
```

`panel/static/js/views/project.js`:
```js
import { esc } from '../ui.js';
export const id = 'project';

const STEPS = [
  ['1 Collect', 'Per-route latency and errors from FastAPI middleware; per-process CPU and memory with psutil; one registry file maps tenants to owners.'],
  ['2 Detect', 'Robust z-score against the pre-change baseline, minimum real change, persistence and exceedance-rate checks. Fixed thresholds as the baseline.'],
  ['3 Packet', 'Anomalous signals, exceptions, slow requests and the deployment diff with git blame and a behaviour-only flag; redacted and hashed.'],
  ['4 Index', 'AST function chunks, routes from decorators, call graph, BM25 and bge-small embeddings.'],
  ['5 Trace', 'Seven weighted evidence features rank functions inside the affected tenant; an LLM may re-rank the top eight.'],
  ['6 Test', 'A generated test must fail on the deployed code and pass on the known-good code, run in a sandbox behind a static guard.'],
];
const TEAM = [
  ['Akash', 'indigo', 'Steps 1–2', ['Telemetry and registry', 'Robust detector and threshold baseline', 'Load generator, live recorder']],
  ['Aryan', 'orange', 'Steps 3–5', ['Evidence packet and deployment diff', 'Code index and hybrid tracer', 'LLM re-rank and action decision']],
  ['Syna', 'green', 'Step 6 + evaluation', ['Template and LLM test generators', 'Guard and sandbox', 'Benchmark harness and scoring']],
];
export function mount(root) {
  root.innerHTML = `
    <div class="sec-h"><h2>Research question</h2></div>
    <div class="card"><p class="rq" style="margin:0">On a shared server, can telemetry-grounded hybrid code retrieval, with an LLM, trace a runtime incident to the responsible function and confirm it with a generated test, better than fixed alerts, blaming the latest deployment, plain vector RAG, or scaling?</p></div>
    <div class="sec-h"><h2>Hypotheses</h2></div>
    <div class="cols c4">${[['H1', 'Robust detection beats fixed thresholds.'], ['H2', 'The hybrid tracer beats every single-signal baseline on Top-1.'], ['H3', 'An LLM helps as a re-ranker over structured evidence more than as plain RAG.'], ['H4', 'Most generated tests are confirming and unsafe tests are blocked.']].map(([k, t]) => `<div class="card"><span class="label">${k}</span><p style="margin:6px 0 0">${t}</p></div>`).join('')}</div>
    <div class="sec-h"><h2>The six steps</h2></div>
    <div class="cols c3">${STEPS.map(([h, t]) => `<div class="card stepcard"><b><span class="no">${esc(h.slice(0, 1))}</span> ${esc(h.slice(2))}</b><p>${esc(t)}</p></div>`).join('')}</div>
    <div class="sec-h"><h2>Team</h2></div>
    <div class="cols c3">${TEAM.map(([n, c, r, items]) => `<div class="card who"><span class="chip ${c} tag">${n}</span><b>${r}</b><ul>${items.map(i => `<li>${esc(i)}</li>`).join('')}</ul></div>`).join('')}</div>
    <div class="sec-h"><h2>Not built, by choice</h2></div>
    <div class="card"><ul class="plain"><li>Steps 7–10: bounded fix proposal, draft PR, CI/CD rollout, post-deploy watch (designed, not automated).</li><li>Sentinel never edits code, restarts or scales; a named human approves any change.</li></ul></div>`;
}
export function update() {}
```

Stub views (`views/floor.js`, `incident.js`, `trace.js`, `proof.js`, `decision.js`, `results.js`), each:
```js
export const id = 'floor'; // use the matching id in each file
export function mount(root) { root.innerHTML = '<div class="empty"><b>Coming in a later task</b>This view is built next.</div>'; }
export function update() {}
```

- [ ] **Step 6: Verify the shell in a browser**

Run (background): `python -m panel --no-browser --port 8765`
Then a headless screenshot of the Project view:
```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
& $edge --headless=new --disable-gpu --hide-scrollbars --window-size=1440,900 --screenshot="$env:TEMP\console-project.png" "http://127.0.0.1:8765/#/project"
```
Expected: the screenshot shows the rail with seven nav items, the top bar (mode switch, scenario select, Run button, idle state) and the Project content with no overflow. Read the PNG and fix layout defects (overflow, alignment, contrast) before moving on. If Edge is missing: `python -m pip install playwright; python -m playwright install chromium` and use `page.screenshot` in a short script.

- [ ] **Step 7: Run the whole test suite and lint**

Run: `python -m pytest -q -p no:cacheprovider; python -m ruff check app services tests scripts sentinel benchmark evaluation panel`
Expected: all tests pass (the 18 earlier + the new panel tests; live test skipped); `All checks passed!`

---

### Task 8: Live floor and Incident views

**Files:**
- Replace: `panel/static/js/views/floor.js`, `panel/static/js/views/incident.js`

**Interfaces:**
- Consumes: `S`, `fmtT`, `focus`, `metricSeries`, `latest`, `worstRoute` (store); `sparkline`, `lineChart` (charts); `esc`, `fmt`, `setHTML`, `chip`, `pill` (ui).
- View contract: `id`, `mount(root)`, `update()`.

- [ ] **Step 1: Write `views/floor.js`**

```js
import { S, fmtT, latest } from '../store.js';
import { sparkline } from '../charts.js';
import { esc, fmt, setHTML, chip } from '../ui.js';

export const id = 'floor';
const STEPS = [['collect', 'Collect', 'per-route · per-process'], ['detect', 'Detect', 'robust z, change-aware'], ['context', 'Packet', 'signals · errors · diff'],
  ['trace', 'Trace', 'hybrid ranking'], ['test', 'Test', 'fail vs pass'], ['handoff', 'Hand-off', 'human approves']];
const OWNER_CHIP = { orders: 'indigo', inventory: 'orange', payments: 'green' };

export function mount(root) {
  root.innerHTML = `
    <div class="sec-h"><h2>Shared server</h2><span class="sub" data-r="sub"></span></div>
    <section class="stats" data-r="stats"></section>
    <section class="tiles">${S.tenants.map(t => `<article class="tile" data-t="${t.name}">
      <div class="tile-h"><span class="dotl"></span><b>${esc(t.name)}</b><span class="chip own ${OWNER_CHIP[t.name] || ''}">${esc(t.owner)}</span></div>
      <div class="val"><span class="big" data-f="p95">—</span><small>ms p95</small></div><div class="route" data-f="route">waiting for traffic</div>
      <div data-f="spark"></div>
      <div class="mini"><div><span class="label">req/s</span><b data-f="rps">—</b></div><div><span class="label">errors</span><b data-f="err">—</b></div><div><span class="label">cpu</span><b data-f="cpu">—</b></div><div><span class="label">rss</span><b data-f="rss">—</b></div></div>
    </article>`).join('')}</section>
    <div class="sec-h"><h2>Pipeline</h2><span class="sub">each stage lights up as the audit trail records it</span></div>
    <section class="steps">${STEPS.map(([k, name, sub], i) => `<div class="step" data-s="${k}"><span class="no">0${i + 1}</span><span class="tm" data-f="tm"></span><b>${name}</b><div class="dim" style="font-size:12px">${sub}</div><div class="res" data-f="res"></div></div>`).join('')}</section>
    <div class="sec-h"><h2>Event log</h2></div>
    <section class="log" data-r="log"></section>`;
}

function pipeline() {
  const by = st => S.stages.filter(s => s.stage === st);
  const detect = by('detect')[0], ctx = by('context')[0], traces = by('trace'), tests = by('test'), hand = by('handoff');
  const running = S.status === 'running';
  const base = S.deploy?.t ?? S.startedAt;
  const first = list => list[0]?.t, last = list => list[list.length - 1]?.t;
  const inc = detect?.incidents?.[0];
  const hybrid = traces.find(t => t.method === 'hybrid'), llmT = traces.find(t => t.method === 'hybrid+llm');
  const defs = {
    collect: { done: !!detect || !!S.result, tele: Object.keys(S.tele).length > 0, res: S.deploy ? `deployed ${S.deploy.commits.length} commits, restarted ${S.deploy.restarted.length} tenants` : Object.keys(S.tele).length ? 'scraping tenants every second' : '', at: S.deploy?.t },
    detect: { done: !!detect, res: detect ? (inc ? `${inc.service} · ${inc.symptoms.join(' + ')} · severity ${fmt(inc.severity)}` : 'no incident detected') : '', at: first([detect].filter(Boolean)) },
    context: { done: !!ctx, res: ctx ? `packet ${String(ctx.packet_digest).slice(0, 8)} · ${ctx.changes} changes · ${ctx.owner}` : '', at: ctx?.t },
    trace: { done: !!hybrid, res: hybrid ? `${hybrid.decision} · confidence ${fmt(hybrid.confidence, 2)}${llmT ? ' · LLM ' + (llmT.valid === false ? 'invalid' : 'agrees') : ''}` : '', at: last(traces) },
    test: { done: tests.length > 0, res: tests.map(t => `${t.generator} ${t.confirming ? '✓ confirming' : '✗ not confirming'}`).join(' · '), at: last(tests) },
    handoff: { done: hand.length > 0, res: S.approval ? `approved by ${S.approval.approver}` : hand.length ? 'awaiting human approval' : '', at: last(hand) },
  };
  let prev = base, activeSet = false;
  STEPS.forEach(([k]) => {
    const d = defs[k];
    d.state = d.done ? 'done' : (!activeSet && running && (k === 'collect' ? d.tele : true)) ? 'active' : 'idle';
    if (d.state === 'active') activeSet = true;
    if (d.done && d.at && prev) { d.time = `${Math.max(0, d.at - prev).toFixed(1)}s`; prev = d.at; }
  });
  return defs;
}

export function update() {
  const root = document.getElementById('view');
  if (!root.querySelector('.tiles')) return;
  const total = { rps: 0, up: 0 };
  S.tenants.forEach(t => {
    const tile = root.querySelector(`[data-t="${t.name}"]`);
    const s = latest(t.name), svc = S.services[t.name];
    const incSvc = S.result?.incident?.service ?? S.stages.find(x => x.stage === 'detect')?.incidents?.[0]?.service;
    tile.classList.toggle('hot', incSvc === t.name);
    tile.classList.toggle('down', svc && svc.up === false);
    tile.querySelector('.dotl').className = `dotl ${svc ? (svc.up ? 'up' : 'dn') : ''}`;
    if (svc?.up) total.up++;
    if (!s) return;
    const routes = Object.entries(s.routes);
    const worst = routes.sort((a, b) => b[1].p95_ms - a[1].p95_ms)[0];
    const rps = routes.reduce((a, [, v]) => a + v.count, 0), err = routes.reduce((a, [, v]) => a + v.errors, 0);
    total.rps += rps;
    const set = (f, v) => { tile.querySelector(`[data-f=${f}]`).textContent = v; };
    set('p95', worst ? fmt(worst[1].p95_ms, worst[1].p95_ms < 100 ? 1 : 0) : '—');
    set('route', worst ? worst[0] : 'idle');
    set('rps', fmt(rps, 0)); set('err', fmt(err, 0)); set('cpu', s.cpu == null ? '—' : `${fmt(s.cpu, 0)}%`); set('rss', s.rss_mb == null ? '—' : `${fmt(s.rss_mb, 0)} MiB`);
    const pts = (S.tele[t.name] || []).slice(-70).map(r => [r.t, Math.max(0, ...Object.values(r.routes).map(v => v.p95_ms))]);
    setHTML(tile.querySelector('[data-f=spark]'), sparkline(pts, { color: incSvc === t.name ? 'var(--orange)' : 'var(--indigo)', marks: S.deploy?.at ? [S.deploy.at] : [] }));
  });

  const det = S.result?.incident ?? S.stages.find(x => x.stage === 'detect')?.incidents?.[0];
  setHTML(root.querySelector('[data-r=stats]'), [
    ['Tenants up', `${total.up}/${S.tenants.length}`, S.server || 'shared server'],
    ['Requests / s', fmt(total.rps, 0), 'all tenants'],
    ['Incident', det ? esc(det.service) : S.status === 'idle' ? '—' : 'none', det ? `${det.symptoms.join(' + ')} · severity ${fmt(det.severity)}` : 'nothing detected yet'],
    ['Run', esc(S.run ? S.run.scenario : '—'), S.run ? `${S.run.mode}${S.run.llm ? ' · LLM on' : ''} · ${S.status}` : 'press Run'],
  ].map(([l, v, sub]) => `<div class="stat"><div class="label">${l}</div><div class="big">${v}</div><div class="sub">${esc(sub)}</div></div>`).join(''));
  setHTML(root.querySelector('[data-r=sub]'), S.connected ? 'stream connected' : 'stream reconnecting…');

  const defs = pipeline();
  STEPS.forEach(([k]) => {
    const el = root.querySelector(`[data-s="${k}"]`), d = defs[k];
    el.className = `step ${d.state}`;
    el.querySelector('[data-f=res]').textContent = d.res || '';
    el.querySelector('[data-f=tm]').textContent = d.time || '';
  });
  setHTML(root.querySelector('[data-r=log]'), S.log.slice(-14).reverse().map(l => `<div class="k-${l.kind}"><b>${fmtT({ t: l.t })}</b><span>${esc(l.text)}</span></div>`).join('') || '<div><b></b><span>no events yet</span></div>');
}
```

- [ ] **Step 2: Write `views/incident.js`**

```js
import { S, focus, metricSeries, latest } from '../store.js';
import { lineChart, sparkline } from '../charts.js';
import { esc, fmt, setHTML, chip, pill } from '../ui.js';

export const id = 'incident';
const UNIT = { latency: 'p95 latency, ms', cpu: 'cpu, %', memory: 'resident memory, MiB', errors: 'error rate' };
const ALERT = { latency: 500, cpu: 80, memory: 500, errors: 0.05 };

export function mount(root) {
  root.innerHTML = `<div data-r="empty"></div><div class="cols c2" data-r="body" style="display:none">
    <div><div class="sec-h"><h2 data-r="title">Affected route</h2></div><div class="card"><div data-r="chart"></div><div class="legend" data-r="legend"></div></div>
      <div class="sec-h"><h2>Other tenants</h2><span class="sub">same window, same scale of time</span></div><div class="cols c2" style="grid-template-columns:1fr 1fr" data-r="others"></div></div>
    <div><div class="sec-h"><h2>Incident</h2></div><div class="card" data-r="card"></div>
      <div class="sec-h"><h2>Signals</h2></div><div class="card" data-r="signals"></div>
      <div class="sec-h"><h2>Fixed-threshold alert</h2></div><div class="card" data-r="thr"></div></div></div>`;
}

export function update() {
  const root = document.getElementById('view');
  const f = focus();
  const body = root.querySelector('[data-r=body]');
  if (!f) {
    body.style.display = 'none';
    setHTML(root.querySelector('[data-r=empty]'), `<div class="empty"><b>${S.status === 'running' ? 'Watching for an incident…' : 'No incident yet'}</b>${S.status === 'running' ? 'The detector compares each tenant after the deployment with its own baseline.' : 'Run a scenario from the top bar.'}</div>`);
    return;
  }
  setHTML(root.querySelector('[data-r=empty]'), '');
  body.style.display = '';
  const pts = metricSeries(f.service, f.kind, f.route);
  const band = S.result?.band;
  const series = [{ name: f.route || f.service, color: 'var(--orange)', points: pts }];
  const hlines = [];
  const maxV = Math.max(0, ...pts.map(p => p[1] ?? 0));
  if (band) {
    hlines.push({ y: band.median, label: `baseline ${fmt(band.median)}`, color: 'var(--green)', dash: false });
    hlines.push({ y: band.bar, label: `detector fires above ${fmt(band.bar)}`, color: 'var(--indigo)', dash: true });
  }
  const alert = ALERT[f.kind];
  if (alert && maxV > alert * 0.4) hlines.push({ y: alert, label: `fixed alert ${alert}`, color: 'var(--red)', dash: true });
  const t0 = pts[0]?.[0];
  const marks = S.deploy?.at ? [{ t: S.deploy.at, label: 'deploy', color: 'var(--amber)' }] : [];
  const zones = S.deploy?.at && pts.length ? [{ t0: S.deploy.at, t1: pts[pts.length - 1][0], color: '#f08a3c' }] : [];
  setHTML(root.querySelector('[data-r=title]'), `${esc(f.service)} · ${esc(f.route || f.kind)}`);
  setHTML(root.querySelector('[data-r=chart]'), lineChart({ series, hlines, marks, zones, unit: UNIT[f.kind] || f.kind, t0 }));
  setHTML(root.querySelector('[data-r=legend]'), `<span><i style="border-color:var(--orange)"></i>${esc(f.route || f.kind)}</span>${band ? '<span><i style="border-color:var(--green)"></i>baseline</span><span><i style="border-color:var(--indigo)"></i>detector firing level</span>' : ''}${alert ? '<span><i style="border-color:var(--red)"></i>fixed alert level</span>' : ''}<span><i style="border-color:var(--amber)"></i>deployment</span>`);

  const inc = S.result?.incident ?? S.stages.find(x => x.stage === 'detect')?.incidents?.[0];
  const owner = S.tenants.find(t => t.name === f.service)?.owner;
  setHTML(root.querySelector('[data-r=card]'), `<div class="label">tenant</div><div class="big" style="margin:4px 0 10px">${esc(f.service)}</div><div style="display:flex;gap:6px;flex-wrap:wrap">${(inc?.symptoms || []).map(s => chip(s, 'orange')).join('')}${owner ? chip(owner) : ''}</div><div class="label" style="margin-top:14px">severity (robust z)</div><div class="big">${fmt(inc?.severity)}</div>`);
  const signals = S.result?.incident?.signals || [];
  setHTML(root.querySelector('[data-r=signals]'), signals.length ? `<table class="t"><tr><th>signal</th><th>baseline → observed</th><th>z</th></tr>${signals.slice(0, 6).map(s => `<tr><td>${esc(s.kind)}${s.route ? `<br><span class="dim mono" style="font-size:11.5px">${esc(s.route)}</span>` : ''}</td><td class="n">${fmt(s.baseline)} → ${fmt(s.observed)}</td><td class="n">${fmt(s.z)}</td></tr>`).join('')}</table>` : '<span class="muted">waiting for the packet…</span>');
  const fired = maxV >= (alert ?? Infinity);
  setHTML(root.querySelector('[data-r=thr]'), `<div style="display:flex;gap:12px;align-items:center">${pill(fired ? 'fired' : 'silent', fired ? 'ok' : 'warn')}<span class="muted">${alert ? `Classic rule: ${f.kind} above ${alert}. Peak seen: ${fmt(maxV, f.kind === 'errors' ? 2 : 0)}.` : 'No fixed rule for this signal.'}</span></div>`);

  const others = S.tenants.filter(t => t.name !== f.service);
  setHTML(root.querySelector('[data-r=others]'), others.map(t => {
    const route = Object.keys(latest(t.name)?.routes || {})[0];
    const p = (S.tele[t.name] || []).map(r => [r.t, Math.max(0, ...Object.values(r.routes).map(v => v.p95_ms))]);
    return `<div class="card"><div style="display:flex;justify-content:space-between"><b>${esc(t.name)}</b><span class="muted mono" style="font-size:12px">${esc(route || '')}</span></div>${sparkline(p, { color: 'var(--indigo)', marks: S.deploy?.at ? [S.deploy.at] : [] })}</div>`;
  }).join(''));
}
```

- [ ] **Step 3: Verify with a replayed run and screenshots**

Run the server with fast replay: `python -m panel --no-browser --port 8765 --speed 40` (background). Screenshots (each view loaded with autorun so the run happens during page load; the virtual-time budget lets it finish):
```powershell
foreach ($v in "floor","incident") {
  & $edge --headless=new --disable-gpu --hide-scrollbars --window-size=1440,900 --virtual-time-budget=30000 --screenshot="$env:TEMP\console-$v.png" "http://127.0.0.1:8765/?autorun=F01&mode=replay#/$v"
}
```
Expected: floor shows three tiles with sparklines, the pipeline strip with steps done and timings, a populated event log; incident shows the orange latency series jumping after the dashed deploy line, baseline and firing-level lines, the signals table and a "silent" fixed-alert card. If virtual time breaks the SSE stream (page shows an empty floor), start a replay with `Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/run -ContentType application/json -Body '{"scenario":"F01","mode":"replay"}'` first, wait 5 s, then screenshot without `autorun` (the page recovers the run from `/api/state`). Read both PNGs, fix defects, rescreenshot.

---

### Task 9: Trace, Proof and Decision views

**Files:**
- Replace: `panel/static/js/views/trace.js`, `proof.js`, `decision.js`

**Interfaces:**
- Consumes: `S`, `fmtT`; `FEATURES`, `featureBar`, `callGraph`, `codeView`, `highlight` (charts); `api.code`, `api.approve`; `esc`, `fmt`, `setHTML`, `chip`, `pill`.
- `result` fields used: `suspects[{chunk_id,path,symbol,start,end,score,features,reasons}]`, `llm`, `truth`, `ranges`, `commits`, `call_path`, `tests`, `action`, `confidence`, `incident`.

- [ ] **Step 1: Write `views/trace.js`**

```js
import { S } from '../store.js';
import { api } from '../api.js';
import { FEATURES, featureBar, callGraph, codeView } from '../charts.js';
import { esc, fmt, setHTML, chip } from '../ui.js';

export const id = 'trace';
let sel = 0, shown = null;
const sources = {};

const overlaps = (a, b) => a.path === b.file && a.start <= b.end_line && b.start_line <= a.end;

export function mount(root) {
  root.innerHTML = '<div data-r="all"></div>';
  root.onclick = e => { const el = e.target.closest('.suspect'); if (el) { sel = Number(el.dataset.i); shown = null; update(); } };
}

function load(path) {
  if (sources[path] !== undefined) return;
  sources[path] = null;
  api.code(path).then(r => { sources[path] = r.text; shown = null; update(); }).catch(() => { sources[path] = false; shown = null; update(); });
}

export function update() {
  const root = document.getElementById('view');
  const box = root.querySelector('[data-r=all]');
  const r = S.result;
  if (!r) { setHTML(box, `<div class="empty"><b>${S.status === 'running' ? 'Waiting for the diagnosis…' : 'No diagnosis yet'}</b>Rankings appear here when the tracer finishes.</div>`); return; }
  const suspects = (r.suspects || []).slice(0, 8);
  if (!suspects.length) { setHTML(box, '<div class="empty"><b>No suspects</b>The tracer found no code evidence for this incident.</div>'); return; }
  sel = Math.min(sel, suspects.length - 1);
  const top = suspects[sel];
  if (top.path) load(top.path);
  const key = `${S.run?.id}|${sel}|${sources[top.path] ? 1 : 0}|${r.suspects.length}`;
  if (key === shown) return;
  shown = key;

  const maxTotal = Math.max(...suspects.map(s => FEATURES.reduce((a, [k, , , w]) => a + (s.features?.[k] || 0) * w, 0)), 1);
  const truth = r.truth;
  const ranges = (r.ranges || []).filter(x => x.behavioural !== false && x.file === top.path).map(x => [x.start, x.end]);
  const hit = s => truth?.file && overlaps(s, truth);
  const culprit = c => (r.ranges || []).some(x => x.commit === c.sha && x.file === top.path && x.start <= top.end && top.start <= x.end);
  const src = sources[top.path];

  const list = suspects.map((s, i) => `<div class="suspect ${i === sel ? 'on' : ''}" data-i="${i}">
    <div class="suspect-h"><span class="rank">${i + 1}</span><b>${esc(s.symbol)}</b>${hit(s) ? chip('true cause', 'green') : ''}<span class="score">${fmt(s.score, 2)}</span></div>
    <div class="where">${esc(s.path)}:${s.start}–${s.end}</div>${featureBar(s.features || {}, maxTotal)}
    ${i === sel && s.reasons?.length ? `<ul class="reasons">${s.reasons.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}</div>`).join('');

  const legend = FEATURES.map(([, l, c, w]) => `<span><i style="background:${c}"></i>${l} <span class="dim">×${w}</span></span>`).join('');
  const codeBox = src ? `<div class="code-h"><span>${esc(top.path)}</span>${chip('lines ' + top.start + '–' + top.end, 'indigo')}${truth?.file === top.path ? chip('true cause ' + truth.start_line + '–' + truth.end_line, 'green') : ''}</div>${codeView(src, { focus: [top.start, top.end], changed: ranges, truth: truth?.file === top.path ? [truth.start_line, truth.end_line] : null })}`
    : `<div class="empty" style="padding:30px">${src === false || !r.code_available ? 'Source not available for this run.' : 'Loading source…'}</div>`;

  const commits = (r.commits || []).map(c => `<div class="commit ${culprit(c) ? 'cul' : ''}"><code>${esc(c.sha)}</code><span>${esc(c.message)}</span>${culprit(c) ? chip('touches suspect', 'orange') : ''}</div>`).join('') || '<span class="muted">Commit list unavailable.</span>';
  const llm = r.llm;
  setHTML(box, `<div class="cols c2"><div><div class="sec-h"><h2>Ranked suspects</h2><span class="sub">bar length = weighted evidence</span></div><div class="flegend">${legend}</div>${list}</div>
    <div><div class="sec-h"><h2>Source</h2></div>${codeBox}
      <div class="sec-h"><h2>Call path</h2><span class="sub">route handler → callees</span></div><div class="card">${r.call_path ? callGraph(r.call_path, top.chunk_id) : '<span class="muted">Call graph unavailable.</span>'}</div>
      <div class="sec-h"><h2>Deployment</h2></div><div class="card">${commits}</div>
      ${llm ? `<div class="sec-h"><h2>LLM re-rank</h2><span class="sub">${esc(llm.model || '')} · ${llm.prompt_tokens || 0}+${llm.completion_tokens || 0} tokens · ${fmt(llm.latency_s)} s</span></div><div class="card"><p style="margin:0">${esc(llm.root_cause || 'No root-cause text.')}</p>${llm.valid === false ? `<p class="muted">Output invalid; deterministic ranking kept.</p>` : ''}</div>` : ''}</div></div>`);
}
```

- [ ] **Step 2: Write `views/proof.js`**

```js
import { S } from '../store.js';
import { highlight } from '../charts.js';
import { esc, setHTML, chip, pill } from '../ui.js';

export const id = 'proof';
let shown = null;
const kind = o => (o === 'assertion_failed' ? 'bad' : o === 'passed' ? 'ok' : 'warn');
const label = o => ({ assertion_failed: 'assertion failed', passed: 'passed', error: 'error', timeout: 'timeout' }[o] || o || 'not run');

export function mount(root) { root.innerHTML = '<div data-r="all"></div>'; }

function runCard(title, expect, run, want) {
  if (!run) return `<div class="run-card"><div class="label">${title}</div><div class="muted" style="margin-top:8px">not run</div></div>`;
  const good = run.outcome === want;
  return `<div class="run-card ${good ? (want === 'passed' ? 'green' : 'red') : ''}"><div style="display:flex;justify-content:space-between;align-items:center"><div class="label">${title}</div>${pill(label(run.outcome), kind(run.outcome))}</div><div class="dim" style="font-size:12px;margin-top:4px">expected: ${expect}</div><div class="out">${esc(run.detail || '—')}</div></div>`;
}

export function update() {
  const box = document.getElementById('view').querySelector('[data-r=all]');
  const r = S.result;
  if (!r) { setHTML(box, `<div class="empty"><b>${S.status === 'running' ? 'Waiting for the tests…' : 'No tests yet'}</b>A confirming test must fail on the deployed code and pass on the known-good code.</div>`); return; }
  const key = `${S.run?.id}|${Object.keys(r.tests).length}`;
  if (key === shown) return;
  shown = key;
  const names = Object.keys(r.tests);
  if (!names.length) { setHTML(box, '<div class="empty"><b>No test generated</b>This run recommended no code fix, so no confirming test was needed.</div>'); return; }
  setHTML(box, names.map(n => {
    const t = r.tests[n];
    const f = t.faulty?.outcome === 'assertion_failed', g = t.fixed?.outcome === 'passed';
    return `<div class="sec-h"><h2>${n === 'template' ? 'Template generator' : 'LLM generator'}</h2><span class="sub">${t.guard.length ? 'guard: ' + esc(t.guard.join('; ')) : 'guard passed'}</span></div>
      <div class="verdict ${t.confirming ? 'ok' : 'no'}">${pill(t.confirming ? 'confirming' : 'not confirming', t.confirming ? 'ok' : 'bad')}<span>${t.guard.length ? 'No test ran: ' + esc(t.guard[0]) : `fails on the faulty code ${f ? '✓' : '✗'} · passes on the known-good code ${g ? '✓' : '✗'}`}</span></div>
      <div class="proof"><div><div class="code">${t.code ? highlight(t.code).split('\n').map((l, i) => `<div class="ln"><span class="no">${i + 1}</span><span class="tx">${l || ' '}</span></div>`).join('') : '<div class="gap">no code</div>'}</div></div>
      <div style="display:grid;gap:14px;align-content:start">${runCard('Deployed code', 'fail (assertion)', t.faulty, 'assertion_failed')}${runCard('Known-good code', 'pass', t.fixed, 'passed')}</div></div>`;
  }).join(''));
}
```

- [ ] **Step 2b: Write `views/decision.js`**

```js
import { S, fmtT } from '../store.js';
import { api } from '../api.js';
import { esc, fmt, setHTML, chip } from '../ui.js';
import { notice } from '../topbar.js';

export const id = 'decision';
const WORDS = { code_fix: 'Propose a code fix', capacity_scale: 'Add capacity', investigate: 'Keep investigating', none: 'No action' };

export function mount(root) {
  root.innerHTML = `<div class="cols c2"><div><div class="sec-h"><h2>Recommendation</h2></div><div class="card" data-r="rec"></div></div>
    <div><div class="sec-h"><h2>Audit trail</h2><span class="sub">every decision, in order</span></div><div class="card"><div class="timeline" data-r="tl"></div></div></div></div>`;
  root.addEventListener('click', async e => {
    if (e.target.id !== 'approve') return;
    const who = root.querySelector('#who').value.trim(), note = root.querySelector('#note').value.trim();
    if (who.length < 2) { notice('Enter the approver name (at least 2 characters).'); return; }
    notice('');
    try { await api.approve({ approver: who, note }); } catch (err) { notice(err.message); }
  });
}

export function update() {
  const root = document.getElementById('view');
  const r = S.result;
  const rec = root.querySelector('[data-r=rec]');
  if (!r) { setHTML(rec, `<div class="empty" style="border:0"><b>No decision yet</b>${S.status === 'running' ? 'Waiting for the pipeline…' : 'Run a scenario first.'}</div>`); }
  else {
    const top = r.suspects?.[0]?.features || {};
    const ticks = [[top.trace > 0 || top.changed_lines > 0, 'Code evidence: a stack frame or a behaviour-changing line'], [top.route > 0 || top.call_path > 0, 'The suspect is on the anomalous route\'s call path'],
      [!!r.tests && Object.values(r.tests).some(t => t.confirming), 'A generated test failed on the faulty code and passed on the known-good code'], [(r.confidence ?? 0) >= 0.6, 'Confidence at or above 0.6']];
    const c = r.confidence ?? 0, circ = 2 * Math.PI * 62;
    const approved = S.approval;
    // the form lives inside `rec`; keep typed text if the card is re-rendered
    const who = root.querySelector('#who')?.value ?? '', note = root.querySelector('#note')?.value ?? '';
    const ownerName = S.tenants.find(t => t.name === r.incident?.service)?.owner;
    setHTML(rec, `<div style="display:flex;gap:24px;align-items:center"><div class="gauge"><svg viewBox="0 0 150 150"><circle cx="75" cy="75" r="62" fill="none" stroke="var(--line)" stroke-width="9"/><circle cx="75" cy="75" r="62" fill="none" stroke="${c >= 0.6 ? 'var(--green)' : 'var(--amber)'}" stroke-width="9" stroke-linecap="round" stroke-dasharray="${(circ * c).toFixed(1)} ${circ.toFixed(1)}"/></svg><div class="big">${fmt(c, 2)}</div></div>
      <div><div class="label">recommended action</div><div class="action">${esc(WORDS[r.action] || r.action || '—')}</div><div class="muted" style="margin-top:6px">${r.incident ? `${esc(r.incident.service)}${ownerName ? ' · owner ' + esc(ownerName) : ''}` : 'no incident detected'}</div></div></div>
      <ul class="ticks">${ticks.map(([y, t]) => `<li class="${y ? 'y' : ''}"><i>${y ? '✓' : '·'}</i>${esc(t)}</li>`).join('')}</ul>
      ${approved ? `<div class="verdict ok" style="margin-top:18px"><span class="pill ok">approved</span><span>by ${esc(approved.approver)}${approved.note ? ' · ' + esc(approved.note) : ''}. No code was changed.</span></div>`
        : r.action === 'none' ? '' : `<div class="form"><input id="who" placeholder="Approver name" value="${esc(who)}"><input id="note" placeholder="Note (optional)" value="${esc(note)}"><button class="btn" id="approve">Approve hand-off</button></div>`}
      <ul class="not plain"><li>Sentinel never edits code, restarts or scales anything.</li><li>Approval records a named human decision in the audit trail only.</li></ul>`);
  }
  const rows = S.stages.map(s => {
    const meta = [s.packet_digest && `packet ${String(s.packet_digest).slice(0, 8)}`, s.model && s.model, s.prompt_tokens && `${s.prompt_tokens}+${s.completion_tokens} tokens`, s.latency_s && `${fmt(s.latency_s)} s`,
      s.confidence != null && `confidence ${fmt(s.confidence, 2)}`, s.approver && s.decision === 'approved' && `by ${s.approver}`].filter(Boolean);
    return `<div class="tl ${s.decision === 'approved' || s.confirming ? 'ok' : ''}"><time>${fmtT({ t: s.t })}</time><b>${esc(s.stage)}${s.method ? ' · ' + esc(s.method) : ''}${s.generator ? ' · ' + esc(s.generator) : ''}</b><div class="muted">${esc(s.decision)}</div><div class="meta">${meta.map(m => chip(m)).join('')}</div></div>`;
  }).join('');
  setHTML(root.querySelector('[data-r=tl]'), rows || '<span class="muted">No audit events yet.</span>');
}
```

- [ ] **Step 3: Verify with screenshots**

With the fast-replay server running and a finished F01 replay in `/api/state`:
```powershell
foreach ($v in "trace","proof","decision") { & $edge --headless=new --disable-gpu --hide-scrollbars --window-size=1440,1000 --screenshot="$env:TEMP\console-$v.png" "http://127.0.0.1:8765/#/$v" }
```
Expected: trace shows ranked suspects with coloured feature bars, the code viewer with the changed lines gutter-marked in orange and the true cause highlighted green, a call graph and the commit list with the culprit tagged; proof shows the generated test with two result cards (red = failed on deployed code, green = passed on known-good); decision shows the confidence ring, tick list, approve form and the audit timeline. Click path check: use `Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/approve -ContentType application/json -Body '{"approver":"Akash","note":"demo"}'` and re-screenshot decision: expect the green "approved by Akash" banner. Read all PNGs and fix defects.

---

### Task 10: Results view

**Files:**
- Replace: `panel/static/js/views/results.js`

**Interfaces:**
- Consumes: `api.results()`, `S.results` cache; `hbars` (charts); `pct`, `esc`, `setHTML`, `chip`.
- `/api/results` shape (Task 2): `{available, summary:{detection:{robust,threshold}, localization:{method:{top1,top3,mrr,n,...}}, localization_heldout_top1, tests:{generator:{...}}, action:{...}, runs, fault_runs, control_runs, seeds}, grid, failures}`.

- [ ] **Step 1: Write `views/results.js`**

```js
import { S } from '../store.js';
import { api } from '../api.js';
import { hbars } from '../charts.js';
import { esc, pct, setHTML, chip } from '../ui.js';

export const id = 'results';
const LABELS = { hybrid: 'Hybrid (no LLM)', hybrid_llm: 'Hybrid + LLM', 'hybrid_llm@gptoss': 'Hybrid + LLM (gpt-oss)', rag_llm: 'Plain RAG + LLM', 'rag_llm@gptoss': 'Plain RAG + LLM (gpt-oss)', recent_changes: 'Blame the deployment', bm25: 'BM25 only', dense: 'Embeddings only', legacy_v0: 'v0 retriever' };
const ABL = [['hybrid', 'Full hybrid'], ['no_trace', '− stack frames'], ['no_call_graph', '− route + call graph'], ['no_change', '− deploy diff'], ['no_dense', '− embeddings'], ['no_lexical', '− BM25'], ['hybrid_unscoped', '− tenant scope']];
const COLS = [['recent_changes', 'Blame deploy'], ['bm25', 'BM25'], ['dense', 'Embed'], ['hybrid', 'Hybrid'], ['hybrid_llm', 'Hybrid+LLM'], ['rag_llm', 'RAG+LLM']];
let loaded = false;

export function mount(root) {
  root.innerHTML = '<div data-r="all"><div class="empty"><b>Loading results…</b></div></div>';
  if (!loaded) api.results().then(r => { S.results = r; loaded = true; update(); }).catch(e => { S.results = { available: false, error: e.message }; update(); });
}

const cell = rank => (rank === undefined ? '<i class="na">·</i>' : rank === null ? '<i class="miss">×</i>' : `<i class="${rank === 1 ? 'r1' : rank === 2 ? 'r2' : rank <= 3 ? 'r3' : 'rx'}">${rank}</i>`);

export function update() {
  const box = document.getElementById('view').querySelector('[data-r=all]');
  const R = S.results;
  if (!R) return;
  if (!R.available) { setHTML(box, `<div class="empty"><b>No benchmark results found</b>Run <span class="mono">python -m evaluation.benchmark score</span> to create evaluation/results/summary.json.</div>`); return; }
  const s = R.summary, d = s.detection, L = s.localization, T = s.tests, A = s.action, H = s.localization_heldout_top1 || {};
  const methods = Object.keys(L).filter(m => !m.startsWith('no_') && m !== 'hybrid_unscoped').sort((a, b) => L[b].top1 - L[a].top1);
  const kpi = (v, l, sub, c) => `<div class="card kpi"><div class="label">${l}</div><div class="big" style="color:${c}">${v}</div><div class="delta">${sub}</div></div>`;
  const stat = [
    kpi(pct(d.robust.fault_recall), 'Faults detected', `fixed thresholds ${pct(d.threshold.fault_recall)}`, 'var(--indigo)'),
    kpi(pct(L.hybrid.top1), 'Faulty function ranked first', `blame the deploy ${pct(L.recent_changes.top1)} · plain RAG ${pct(L.rag_llm?.top1)}`, 'var(--orange)'),
    kpi(pct(T.template?.confirming), 'Tests that confirm', `template · LLM ${pct(T.llm?.confirming)}`, 'var(--green)'),
    kpi(pct(A.sentinel), 'Right action', `scale on every alert ${pct(A.always_scale_on_robust_alert)}`, 'var(--text)'),
  ].join('');
  const det = hbars([
    { label: 'Fault recall · robust', value: d.robust.fault_recall, color: 'var(--indigo)' }, { label: 'Fault recall · thresholds', value: d.threshold.fault_recall, color: 'var(--amber)' },
    { label: 'False alarms · robust', value: d.robust.false_alarm_rate_quiet_controls, color: 'var(--red)' }, { label: 'False alarms · thresholds', value: d.threshold.false_alarm_rate_quiet_controls, color: 'var(--red)' },
  ]);
  const byClass = hbars(Object.keys(d.robust.by_class).flatMap(c => [{ label: `${c} · robust`, value: d.robust.by_class[c], color: 'var(--indigo)' }, { label: `${c} · thresholds`, value: d.threshold.by_class[c], color: 'var(--amber)' }]));
  const loc = hbars(methods.map(m => ({ label: LABELS[m] || m, value: L[m].top1, ghost: L[m].top3, hi: m === 'hybrid', color: m === 'hybrid' ? 'var(--orange)' : m.includes('llm') ? 'var(--indigo)' : 'var(--dim)' })));
  const abl = hbars(ABL.filter(([m]) => L[m]).map(([m, l]) => ({ label: l, value: L[m].top1, hi: m === 'hybrid', color: m === 'hybrid' ? 'var(--orange)' : 'var(--indigo)' })));
  const tests = `<table class="t"><tr><th>generator</th><th class="n">n</th><th class="n">guard</th><th class="n">fails on faulty</th><th class="n">passes on good</th><th class="n">confirming</th></tr>${Object.entries(T).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v.n}</td><td class="n">${pct(v.guard_pass)}</td><td class="n">${pct(v.fails_on_faulty)}</td><td class="n">${pct(v.passes_on_fixed)}</td><td class="n"><b>${pct(v.confirming)}</b></td></tr>`).join('')}</table>`;
  const grid = `<div class="heat"><div class="hh">scenario</div>${COLS.map(([, l]) => `<div class="hh">${l}</div>`).join('')}${R.grid.filter(g => Object.keys(g.cells).length).map(g => `<div class="rl"><b>${g.scenario}</b>${esc(g.title)}</div>${COLS.map(([m]) => `<div class="cell">${(g.cells[m] || []).map(cell).join('') || cell(undefined)}</div>`).join('')}`).join('')}</div>
    <div class="legend"><span>cell = rank of the true function, one square per seed</span><span class="chip green">1</span><span class="chip">2–3</span><span class="chip orange">4+</span><span class="chip red">× missed / undetected</span></div>`;
  const fails = R.failures.map(f => `<div class="fail"><span class="id">${esc(f.scenario)} · s${f.seed}</span>${chip(f.kind, f.kind === 'false alarm' || f.kind === 'undetected' ? 'red' : 'orange')}<span>${esc(f.text)}</span></div>`).join('') || '<span class="muted">No failures recorded.</span>';
  setHTML(box, `<div class="cols c4">${stat}</div>
    <div class="sec-h"><h2>Detection</h2><span class="sub">${s.fault_runs} fault runs, ${s.control_runs} control runs, seeds ${s.seeds.join(', ')}</span></div>
    <div class="cols eq2"><div class="card">${det}</div><div class="card">${byClass}</div></div>
    <div class="sec-h"><h2>Localisation</h2><span class="sub">Top-1 solid, Top-3 faint · held-out seeds: hybrid ${pct(H.hybrid)}, blame ${pct(H.recent_changes)}</span></div>
    <div class="cols eq2"><div class="card">${loc}</div><div class="card"><div class="label" style="margin-bottom:10px">Ablation: remove one evidence feature</div>${abl}</div></div>
    <div class="sec-h"><h2>Confirming tests</h2></div><div class="card">${tests}</div>
    <div class="sec-h"><h2>Every scenario</h2></div><div class="card">${grid}</div>
    <div class="sec-h"><h2>What failed</h2><span class="sub">reported, not hidden</span></div><div class="card">${fails}</div>`);
}
```

- [ ] **Step 2: Verify with screenshots**

```powershell
& $edge --headless=new --disable-gpu --hide-scrollbars --window-size=1440,2400 --virtual-time-budget=8000 --screenshot="$env:TEMP\console-results.png" "http://127.0.0.1:8765/#/results"
```
Expected: four headline cards (92% / 85% / 94% / 82%), detection and localisation bar groups, ablation, the tests table, the scenario × method heat grid with coloured rank squares, and the failures list. Read the PNG; fix overflow and truncation (heat labels, long method names).

---

### Task 11: Visual QA, polish, docs, final verification

**Files:**
- Modify: `.github/workflows/ci.yml` (lint `panel`), `README.md` (Console section), `docs/PROJECT_GUIDE.md` (short Console section), `requirements.txt` (none expected)
- Modify as needed: any `panel/static` file for defects found

- [ ] **Step 1: Screenshot every view at 1280×720 and 1920×1080 and fix defects**

For each size `1280x720` and `1920x1080` and each of `floor incident trace proof decision results project`, run the Edge command used above (a finished replay must exist in `/api/state`; start one with the REST call if needed) and read each PNG. Checklist per image: no text overflow or clipping; nothing under 11px; numbers not wrapped mid-value; consistent card gaps (18px); contrast of muted text acceptable on `--panel`; charts fill their cards; rail and top bar do not overlap content; no horizontal scroll at 1280. Fix the CSS or JS for each defect and re-shoot only the affected views.

- [ ] **Step 2: Run a real Live demo through the UI once**

Stop the fast-replay server. Start `python -m panel --no-browser --port 8765`. In Edge headless this cannot be clicked, so drive it via REST: `Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/run -ContentType application/json -Body '{"scenario":"F01","mode":"live","llm":true}'`, poll `/api/state` until the last `run` event is `done` (about 2 minutes), then screenshot `floor`, `incident`, `trace` and `proof`.
Expected: tiles moved during the run, incident view shows orders, trace shows `fetch_orders_with_profiles` rank 1 with the true-cause chip, proof shows confirming tests. Note any live-only defect (e.g. event rate making the floor flicker) and fix.

- [ ] **Step 3: Docs and CI**

`.github/workflows/ci.yml`: change the ruff line to `ruff check app services tests scripts sentinel benchmark evaluation panel`.

`README.md`: add after "Quick start":
```markdown
## Sentinel Console (live panel)

```bash
python -m panel                 # http://127.0.0.1:8080  (Replay is the default; Live starts the real services)
python -m panel --speed 30      # faster replay, handy for screenshots
```
Seven views: live floor, incident, trace, proof, decision, results, project. Replay needs `data/bench/` and
`evaluation/results/` (created by `python -m evaluation.benchmark record|analyze|score`).
```

`docs/PROJECT_GUIDE.md`: add a short "Sentinel Console" subsection under "How to reproduce" that names `python -m panel`, the two modes, and links to the spec.

- [ ] **Step 4: Full verification**

Run: `python -m pytest -q -p no:cacheprovider; python -m ruff check app services tests scripts sentinel benchmark evaluation panel; git status --short`
Expected: all tests pass (live test skipped), `All checks passed!`, and `git status` lists only new/modified files (nothing committed). The untracked `IDT - Mid Sem Presentation.pptx` stays untracked.

---

## Self-review

**Spec coverage:** Purpose/constraints → Global Constraints, Task 6 CLI. Architecture/files → File Structure, Tasks 1–6. Run modes (Live/Replay) → Tasks 4, 5. Event stream and REST → Tasks 4–6 (contracts listed in Task 4/6 Interfaces; `/api/audit` implemented in Task 6). Screens 1–7 → Tasks 7 (project), 8 (floor, incident), 9 (trace, proof, decision), 10 (results). Visual design → Task 7 CSS + Task 11 QA. Error handling table → port busy (Task 4 test), no LLM key (Task 5 uses `llm.available()`; UI disables toggle), service dies (poller emits `service up:false`; floor `down` class), refresh/second tab (Task 6 test), missing recording (Task 4/6 tests), Results/Project work without runs (Task 10 independent of runs), `/api/code` traversal (Task 3/6 tests). Testing section → Tasks 1–6 tests and Task 7–11 screenshots. Replay speed and LLM-toggle default → Task 4/7. **Addition not in the spec:** a `?autorun=<id>&mode=replay` URL hook in `main.js` and a `--speed` CLI flag, used only for screenshots and demos.

**Placeholder scan:** no TBD/TODO; every code step has full code. Stub views in Task 7 are intentionally replaced in Tasks 8–10 and listed as such.

**Type consistency:** `RunContext.emit_result` (Task 4) is what `replay.run_replay` and `live.run_live` call; `Runner.start` returns `{"run","since"}` (used by server tests); event payload `deploy.at` is produced by both modes and consumed by `store.js`/`incident.js`/`floor.js`; `result.ranges[].commit` (a short sha) matches `result.commits[].sha`; `enrich.build_result` keys match what `trace.js`, `proof.js`, `decision.js` read (`suspects`, `llm`, `truth`, `ranges`, `commits`, `call_path`, `tests`, `action`, `confidence`, `incident`, `band`, `code_available`).

**Risks called out for the reviewer:** (1) headless-Edge screenshots depend on virtual time with SSE; the plan has a REST-driven fallback and a Playwright fallback. (2) Live runs need ports 9101–9103 free and a few minutes; the opt-in live test covers it. (3) Replay needs `data/bench/` workspaces on disk (present on this machine, gitignored), otherwise code/call-graph panels show "Source not available".
