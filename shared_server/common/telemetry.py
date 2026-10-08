"""Per-service telemetry shared by every service on the shared server.

Each service installs this middleware. It records per-route latency and status, logs
unhandled exceptions with their stack frames, keeps a few sample requests that were slow
or failed (so an incident can be reproduced), and exposes everything at ``/metrics``.
``/metrics`` drains the interval buffer, so a collector that scrapes once per second gets
one bucket per second.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

WORKSPACE = Path(__file__).resolve().parents[1]
SLOW_SAMPLE_MS = float(os.getenv("SENTINEL_SLOW_SAMPLE_MS", "150"))
MAX_SAMPLES = 20


class Telemetry:
    def __init__(self, service: str) -> None:
        self.service = service
        self.lock = threading.Lock()
        self.interval: list[tuple[str, float, int]] = []
        self.samples: list[dict] = []
        self.exemplars: dict[str, dict] = {}
        self.totals = {"requests": 0, "errors": 0}
        log_dir = Path(os.getenv("SENTINEL_LOG_DIR", WORKSPACE / "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{service}.jsonl"

    def install(self, app: FastAPI) -> None:
        @app.middleware("http")
        async def record(request: Request, call_next):
            if request.url.path == "/metrics":
                return await call_next(request)
            body = await request.body()
            started = time.perf_counter()
            try:
                response = await call_next(request)
                status = response.status_code
            except Exception as exc:  # noqa: BLE001 - every unhandled error becomes evidence
                status = 500
                self._log_exception(request, body, exc)
                response = JSONResponse({"detail": "internal error"}, status_code=500)
            latency_ms = (time.perf_counter() - started) * 1000
            route = request.scope.get("route")
            template = getattr(route, "path", request.url.path)
            self._record(f"{request.method} {template}", request, body, latency_ms, status)
            return response

        @app.get("/metrics", include_in_schema=False)
        def metrics() -> dict:
            return self.drain()

    def _record(self, route: str, request: Request, body: bytes, latency_ms: float, status: int) -> None:
        with self.lock:
            self.interval.append((route, latency_ms, status))
            self.totals["requests"] += 1
            if status >= 500:
                self.totals["errors"] += 1
            sample = {
                "at": time.time(),
                "route": route,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "body": body.decode("utf-8", errors="replace")[:2000],
                "status": status,
                "latency_ms": round(latency_ms, 1),
            }
            if (status >= 500 or latency_ms >= SLOW_SAMPLE_MS) and len(self.samples) < MAX_SAMPLES:
                self.samples.append(sample)
            if status < 400:
                self.exemplars.setdefault(route, sample)  # one normal request per route, for replay

    def _log_exception(self, request: Request, body: bytes, exc: Exception) -> None:
        frames = []
        for frame in traceback.extract_tb(exc.__traceback__):
            path = Path(frame.filename)
            try:
                relative = path.resolve().relative_to(WORKSPACE).as_posix()
            except ValueError:
                continue  # framework frames are not evidence about this service's code
            frames.append({"file": relative, "line": frame.lineno, "function": frame.name})
        event = {
            "at": time.time(),
            "service": self.service,
            "level": "error",
            "path": request.url.path,
            "method": request.method,
            "body": body.decode("utf-8", errors="replace")[:2000],
            "exception": type(exc).__name__,
            "message": str(exc)[:500],
            "frames": frames,
        }
        with self.lock, self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def drain(self) -> dict:
        with self.lock:
            records, self.interval = self.interval, []
            samples, self.samples = self.samples, []
            exemplars, self.exemplars = list(self.exemplars.values()), {}
            totals = dict(self.totals)
        routes: dict[str, dict] = {}
        for route, latency, status in records:
            stats = routes.setdefault(route, {"latencies": [], "errors": 0})
            stats["latencies"].append(latency)
            stats["errors"] += status >= 500
        summary = {}
        for route, stats in routes.items():
            ordered = sorted(stats["latencies"])
            summary[route] = {
                "count": len(ordered),
                "errors": stats["errors"],
                "p50_ms": round(ordered[len(ordered) // 2], 2),
                "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
                "max_ms": round(ordered[-1], 2),
            }
        return {"service": self.service, "pid": os.getpid(), "at": time.time(), "routes": summary, "totals": totals, "samples": samples,
                "exemplars": exemplars}
