"""Telemetry for a service monitored by Sentinel.

Installs four things on a FastAPI app:

* ``GET /health``            liveness for Docker health checks and Sentinel's deploy gate
* ``GET /metrics``           Prometheus exposition (request counter, latency histogram, exceptions)
* ``GET /sentinel/metrics``  one-second interval drain (per-route p50/p95, errors, slow/failed samples,
                             one normal request per route) used by Sentinel's detector
* exception capture          every unhandled exception becomes a 500 and one JSON log line (stdout and
                             ``$SENTINEL_LOG_DIR/<service>.jsonl``) with the stack frames inside this repo
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

WORKSPACE = Path(__file__).resolve().parents[1]
SLOW_SAMPLE_MS = float(os.getenv("SENTINEL_SLOW_SAMPLE_MS", "150"))
MAX_SAMPLES = 20
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
INTERNAL = {"/metrics", "/sentinel/metrics", "/health"}


class Telemetry:
    def __init__(self, service: str) -> None:
        self.service = service
        self.lock = threading.Lock()
        self.interval: list[tuple[str, float, int]] = []
        self.samples: list[dict] = []
        self.exemplars: dict[str, dict] = {}
        self.totals = {"requests": 0, "errors": 0}
        self.registry = CollectorRegistry()
        self.requests = Counter("http_requests_total", "HTTP requests", ["service", "route", "method", "status"], registry=self.registry)
        self.latency = Histogram("http_request_duration_seconds", "HTTP request latency", ["service", "route", "method"],
                                 buckets=BUCKETS, registry=self.registry)
        self.exceptions = Counter("http_exceptions_total", "Unhandled exceptions", ["service", "exception"], registry=self.registry)
        log_dir = Path(os.getenv("SENTINEL_LOG_DIR", WORKSPACE / "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{service}.jsonl"

    def install(self, app: FastAPI) -> None:
        @app.middleware("http")
        async def record(request: Request, call_next):
            if request.url.path in INTERNAL:
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
            seconds = time.perf_counter() - started
            route = getattr(request.scope.get("route"), "path", request.url.path)
            self.requests.labels(self.service, route, request.method, str(status)).inc()
            self.latency.labels(self.service, route, request.method).observe(seconds)
            self._record(f"{request.method} {route}", request, body, seconds * 1000, status)
            return response

        @app.get("/health", include_in_schema=False)
        def health() -> dict:
            return {"status": "ok", "service": self.service}

        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            return Response(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)

        @app.get("/sentinel/metrics", include_in_schema=False)
        def sentinel_metrics() -> dict:
            return self.drain()

    def _record(self, route: str, request: Request, body: bytes, latency_ms: float, status: int) -> None:
        with self.lock:
            self.interval.append((route, latency_ms, status))
            self.totals["requests"] += 1
            if status >= 500:
                self.totals["errors"] += 1
            sample = {"at": time.time(), "route": route, "method": request.method, "path": request.url.path,
                      "query": str(request.url.query), "body": body.decode("utf-8", errors="replace")[:2000],
                      "status": status, "latency_ms": round(latency_ms, 1)}
            if (status >= 500 or latency_ms >= SLOW_SAMPLE_MS) and len(self.samples) < MAX_SAMPLES:
                self.samples.append(sample)
            if status < 400:
                self.exemplars.setdefault(route, sample)

    def _log_exception(self, request: Request, body: bytes, exc: Exception) -> None:
        frames = []
        for frame in traceback.extract_tb(exc.__traceback__):
            try:
                relative = Path(frame.filename).resolve().relative_to(WORKSPACE).as_posix()
            except ValueError:
                continue
            frames.append({"file": relative, "line": frame.lineno, "function": frame.name})
        self.exceptions.labels(self.service, type(exc).__name__).inc()
        event = {"at": time.time(), "service": self.service, "level": "error", "path": request.url.path, "method": request.method,
                 "body": body.decode("utf-8", errors="replace")[:2000], "exception": type(exc).__name__,
                 "message": str(exc)[:500], "frames": frames}
        line = json.dumps(event)
        print(line, file=sys.stdout, flush=True)
        with self.lock, self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

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
            summary[route] = {"count": len(ordered), "errors": stats["errors"], "p50_ms": round(ordered[len(ordered) // 2], 2),
                              "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2), "max_ms": round(ordered[-1], 2)}
        return {"service": self.service, "pid": os.getpid(), "at": time.time(), "routes": summary, "totals": totals,
                "samples": samples, "exemplars": exemplars}
