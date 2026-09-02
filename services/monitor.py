from __future__ import annotations

import os
import time

import httpx
import psutil


async def collect(target_url: str) -> dict:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{target_url.rstrip('/')}/metrics")
            response.raise_for_status()
            app_metrics = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        app_metrics = {"request_count": 0, "error_count": 1, "error_rate": 1.0, "p95_ms": 0, "monitor_error": str(exc)}
    return {**app_metrics, "cpu_percent": psutil.cpu_percent(interval=None), "memory_mb": round(psutil.Process().memory_info().rss / 1024 / 1024, 1), "monitor_latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def is_incident(metrics: dict) -> bool:
    return metrics.get("error_rate", 0) >= float(os.getenv("INCIDENT_ERROR_RATE_THRESHOLD", "0.10")) or metrics.get("p95_ms", 0) >= float(os.getenv("INCIDENT_P95_MS_THRESHOLD", "600"))
