"""Step 1: collect per-service telemetry on the shared server.

Once per second the collector scrapes every registered service's ``/metrics`` endpoint
(per-route latency, errors, slow/failed request samples) and reads that service's own
process CPU and memory with psutil. Host-level numbers alone cannot say which tenant of a
shared server is in trouble; per-process numbers can.
"""
from __future__ import annotations

import threading
import time

import httpx
import psutil

from sentinel.registry import Registry


class Collector:
    def __init__(self, registry: Registry, interval_s: float = 1.0) -> None:
        self.registry = registry
        self.interval_s = interval_s
        self.samples: list[dict] = []
        self.events: list[dict] = []
        self._processes: dict[int, psutil.Process] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def mark(self, kind: str, **details) -> None:
        """Record an operational event such as a deployment, so detection can compare before/after."""
        self.events.append({"t": time.time(), "kind": kind, **details})

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        with httpx.Client(timeout=2.0) as client:
            while not self._stop.is_set():
                started = time.time()
                for service in self.registry.services:
                    self.samples.append(self.scrape(client, service.name, service.url))
                self._stop.wait(max(0.0, self.interval_s - (time.time() - started)))

    def scrape(self, client: httpx.Client, name: str, url: str) -> dict:
        sample = {"t": time.time(), "service": name, "up": False, "routes": {}, "samples": [], "cpu_percent": None, "rss_mb": None}
        try:
            payload = client.get(f"{url}/metrics").json()
        except (httpx.HTTPError, ValueError):
            return sample
        sample.update(up=True, routes=payload["routes"], samples=payload["samples"], exemplars=payload.get("exemplars", []), pid=payload["pid"])
        try:
            process = self._processes.setdefault(payload["pid"], psutil.Process(payload["pid"]))
            sample["cpu_percent"] = process.cpu_percent(interval=None)
            sample["rss_mb"] = round(process.memory_info().rss / 1024 / 1024, 2)
        except psutil.Error:
            pass
        return sample
