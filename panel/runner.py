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
from panel import enrich, live, replay
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
        files = (self.paths.recording(scenario_id, seed), self.paths.run_result(scenario_id, seed), self.paths.audit(scenario_id, seed))
        return all(p.exists() for p in files)

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
                recording = json.loads(self.paths.recording(scenario_id, seed).read_text(encoding="utf-8"))
                workspace = Path(recording["workspace"])
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
        stage = enrich.stage_payload(event)
        self.bus.emit("stage", stage)
        return stage

    def workspace(self, run_id: str | None = None) -> Path | None:
        if not self.current or (run_id and run_id != self.current["id"]):
            return None
        return Path(self.current["workspace"])
