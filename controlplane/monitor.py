"""Per-service telemetry, once a tick: the service's own interval drain plus the runtime's view of the instance.

A service that has no telemetry of its own (a cloned repository) is measured where its requests enter: Traefik. When
``SENTINEL_PROMETHEUS_API`` is set the monitor reads Traefik's per-service counters and latency histogram from
Prometheus and reports them as one route, so curl requests show up with no change to the service.

Samples keep the shape ``sentinel.detection`` already understands (``t``, ``service``, ``up``, ``routes``,
``cpu_percent``, ``rss_mb``, slow/failed request samples, exemplars) plus lifecycle fields for the detector.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import httpx

from controlplane.core import Core

LIVE = ("healthy", "starting")
log = logging.getLogger("sentinel.monitor")


class Monitor:
    def __init__(self, core: Core, interval: float = 1.0, keep: int = 900, edge_every: float = 5.0) -> None:
        self.core, self.interval, self.keep, self.edge_every = core, interval, keep, edge_every
        self._edge: dict[str, dict] = {}
        self._buffers: dict[str, deque] = {}
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="monitor")
        self._client = httpx.Client(timeout=1.5)
        self._prom = httpx.Client(timeout=2.0)

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
            if self.core.settings.prometheus_api:
                sample["routes"] = self._edge_routes(svc["name"])
        stats = runtime.stats(dep["instance"]) if status.running else None
        sample.update(cpu_percent=stats.cpu_percent if stats else None, rss_mb=stats.mem_mb if stats else None,
                      mem_limit_mb=(stats.mem_limit_mb if stats and stats.mem_limit_mb else svc["mem_limit_mb"]),
                      cpu_limit=(stats.cpu_limit if stats and stats.cpu_limit else svc["cpu_limit"]))
        return sample

    def _prom_value(self, query: str) -> float | None:
        try:
            body = self._prom.get(self.core.settings.prometheus_api.rstrip("/") + "/api/v1/query", params={"query": query}).json()
            result = body["data"]["result"]
            value = float(result[0]["value"][1]) if result else None
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return None
        return None if value is None or math.isnan(value) else value  # NaN means no requests in the window

    def _edge_routes(self, name: str) -> dict:
        """Requests since the last look, counted by Traefik: one pseudo-route, empty until the second look."""
        state = self._edge.setdefault(name, {"at": 0.0, "total": None, "errors": None, "p95_ms": None, "count": 0, "bad": 0})
        now = time.time()
        if now - state["at"] >= self.edge_every:
            svc = f'service="svc-{name}@docker"'
            total = self._prom_value(f"sum(traefik_service_requests_total{{{svc}}})")
            errors = self._prom_value(f'sum(traefik_service_requests_total{{{svc},code=~"5.."}})') or 0.0
            p95 = self._prom_value(f"histogram_quantile(0.95, sum by (le) (rate(traefik_service_request_duration_seconds_bucket{{{svc}}}[1m])))")
            state.update(at=now, count=0, bad=0, p95_ms=None if p95 is None else p95 * 1000)
            if total is not None:
                if state["total"] is not None:  # a counter that went down was reset: count from zero
                    state["count"] = int(total - state["total"] if total >= state["total"] else total)
                    state["bad"] = int(errors - state["errors"] if errors >= (state["errors"] or 0) else errors)
                state.update(total=total, errors=errors)
        else:
            state.update(count=0, bad=0)
        if state["total"] is None:
            return {}
        return {"all requests": {"count": state["count"], "errors": state["bad"], "p95_ms": state["p95_ms"] or 0.0}}

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
