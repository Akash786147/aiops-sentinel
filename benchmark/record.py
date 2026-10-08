"""Run one scenario live on the local "shared server" and save everything Sentinel needs.

Timeline:  start 3 services -> baseline traffic -> deployment (git commits, restart changed
services) -> same traffic (or a surge for H03) -> stop. The recording (telemetry, events,
ground truth) plus the git workspace on disk are the input to the offline pipeline, so every
later step can be re-run without re-running traffic.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from benchmark import load
from benchmark.scenarios import Scenario
from benchmark.workspace import build, deploy
from sentinel.registry import Registry, load_registry
from sentinel.telemetry import Collector


def start_service(root: Path, registry: Registry, name: str) -> subprocess.Popen:
    service = registry.get(name)
    env = {**os.environ, "PYTHONPATH": str(root), "SENTINEL_LOG_DIR": str(root / "logs"), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-m", "uvicorn", service.module, "--host", "127.0.0.1", "--port", str(service.port), "--log-level", "warning"]
    return subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_ready(url: str, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            httpx.get(f"{url}/metrics", timeout=1.0)
            return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"service at {url} did not start")


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def record(scenario: Scenario, root: Path, output: Path, seed: int = 0, baseline_s: float = 20.0, incident_s: float = 20.0) -> dict:
    commits, truth = build(scenario, root, seed)
    registry = load_registry(root)
    processes = {s.name: start_service(root, registry, s.name) for s in registry.services}
    collector = Collector(registry)
    try:
        for service in registry.services:
            wait_ready(service.url)
        urls = {s.name: s.url for s in registry.services}
        collector.start()
        asyncio.run(load.run(urls, baseline_s, seed=seed))

        change_time = time.time()
        changed = deploy(root, commits, scenario, truth)
        restart = [s.name for s in registry.services] if set(changed) & set(registry.shared_code) else [c for c in changed if c in processes]
        collector.mark("deployment", commits=[c.message for c in commits], restarted=restart)
        for name in restart:
            stop(processes[name])
            processes[name] = start_service(root, registry, name)
        for name in restart:
            wait_ready(registry.get(name).url)
        asyncio.run(load.run(urls, incident_s, multiplier=scenario.traffic_multiplier, seed=seed + 1))
        end_time = time.time()
    finally:
        collector.stop()
        for process in processes.values():
            stop(process)

    recording = {
        "scenario": scenario.id,
        "seed": seed,
        "workspace": str(root),
        "change_time": change_time,
        "end_time": end_time,
        "restarted": restart,
        "deployment": [c.message for c in commits],
        "truth": asdict(truth),
        "samples": collector.samples,
        "events": collector.events,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(recording), encoding="utf-8")
    return recording
