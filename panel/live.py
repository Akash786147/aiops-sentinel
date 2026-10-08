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
        if self.is_alive():
            self.join(2.0)
        self.flush()

    def flush(self) -> None:
        samples = self.collector.samples
        while self._pos < len(samples):
            sample = samples[self._pos]
            self._pos += 1
            name = sample["service"]
            if name in self._up and self._up[name] != sample["up"]:
                state = {"name": name, "owner": self.owners.get(name), "up": sample["up"], "pid": sample.get("pid")}
                self.ctx.bus.emit("service", state)
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
        if self.is_alive():
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
