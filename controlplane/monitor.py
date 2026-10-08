"""Per-service telemetry, once a tick: the service's own interval drain plus the runtime's view of the instance.

Samples keep the shape ``sentinel.detection`` already understands (``t``, ``service``, ``up``, ``routes``,
``cpu_percent``, ``rss_mb``, slow/failed request samples, exemplars) plus lifecycle fields for the detector.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import httpx

from controlplane.core import Core

LIVE = ("healthy", "starting")
log = logging.getLogger("sentinel.monitor")


class Monitor:
    def __init__(self, core: Core, interval: float = 1.0, keep: int = 900) -> None:
        self.core, self.interval, self.keep = core, interval, keep
        self._buffers: dict[str, deque] = {}
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="monitor")
        self._client = httpx.Client(timeout=1.5)

    def series(self, service: str, since: float | None = None) -> list[dict]:
        rows = list(self._buffers.get(service, ()))
        return [r for r in rows if since is None or r["t"] >= since]

    def latest(self, service: str) -> dict | None:
        rows = self._buffers.get(service)
        return rows[-1] if rows else None

    def tick(self) -> dict[str, dict]:
        targets = []
        for svc in self.core.store.list_services():
            dep = next((d for d in self.core.store.deployments(svc["name"], limit=5) if d["status"] in LIVE and d["instance"]), None)
            if dep:
                targets.append((svc, dep))
        results = dict(zip([s["name"] for s, _ in targets], self._pool.map(lambda pair: self._sample(*pair), targets), strict=True))
        for name, sample in results.items():
            self._buffers.setdefault(name, deque(maxlen=self.keep)).append(sample)
            self.core.bus.emit("telemetry", self._slim(sample))
        return results

    def _sample(self, svc: dict, dep: dict) -> dict:
        runtime = self.core.runtime
        status = runtime.status(dep["instance"])
        sample = {"t": time.time(), "service": svc["name"], "up": False, "routes": {}, "samples": [], "exemplars": [],
                  "deployment": dep["id"], "running": status.running, "exit_code": status.exit_code, "oom_killed": status.oom_killed,
                  "restarts": status.restarts, "health": status.health}
        if status.running and svc.get("metrics_path"):
            try:
                payload = self._client.get(dep["url"] + svc["metrics_path"]).json()
                sample.update(up=True, routes=payload.get("routes", {}), samples=payload.get("samples", []), exemplars=payload.get("exemplars", []))
            except (httpx.HTTPError, ValueError):
                sample["up"] = False
        elif status.running:
            sample["up"] = status.health != "unhealthy"
        stats = runtime.stats(dep["instance"]) if status.running else None
        sample.update(cpu_percent=stats.cpu_percent if stats else None, rss_mb=stats.mem_mb if stats else None,
                      mem_limit_mb=(stats.mem_limit_mb if stats and stats.mem_limit_mb else svc["mem_limit_mb"]),
                      cpu_limit=(stats.cpu_limit if stats and stats.cpu_limit else svc["cpu_limit"]))
        return sample

    @staticmethod
    def _slim(sample: dict) -> dict:
        routes = {r: {"count": s["count"], "errors": s["errors"], "p95_ms": s["p95_ms"]} for r, s in sample["routes"].items()}
        keep = ("t", "service", "up", "deployment", "running", "restarts", "health", "oom_killed", "cpu_percent", "rss_mb", "mem_limit_mb", "cpu_limit")
        return {**{k: sample[k] for k in keep}, "routes": routes}

    def start(self) -> None:
        self._halt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="monitor")
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._halt.is_set():
            started = time.time()
            try:
                self.tick()
            except Exception:
                log.exception("monitor tick failed")
            self._halt.wait(max(0.05, self.interval - (time.time() - started)))
