"""Background load so monitored services always have real traffic (toggled from the UI).

Only the bundled sample services get traffic, with their realistic request mixes (including the awkward inputs that
trigger the lab faults). A cloned repository is never sent anything: it sees only the requests a person makes.
"""
from __future__ import annotations

import asyncio
import random
import threading
import time

import httpx

from benchmark.load import MIX
from controlplane import replay
from controlplane.core import Core

LIVE = ("healthy", "starting")


class Traffic:
    def __init__(self, core: Core, workers: int = 2, think_s: float = 0.05) -> None:
        self.core, self.workers, self.think_s = core, workers, think_s
        self.enabled = False
        self.sent = 0
        self._urls: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()

    def status(self) -> dict:
        return {"enabled": self.enabled, "sent": self.sent, "workers": self.workers, "targets": sorted(self._urls)}

    def _refresh(self) -> list[dict]:
        services = [svc for svc in self.core.store.list_services() if svc["kind"] == "sample"]
        urls = {}
        for svc in services:
            dep = next((d for d in self.core.store.deployments(svc["name"], limit=5) if d["status"] in LIVE and d["url"]), None)
            if dep:
                urls[svc["name"]] = dep["url"]
        self._urls = urls
        return services

    async def _worker(self, client: httpx.AsyncClient, svc: dict, rng: random.Random) -> None:
        profile = replay.load(self.core.workspace(svc["name"]).root, svc["package"])
        make = MIX.get(svc["package"] or "") or (replay.request_maker(profile) if profile else (lambda _r: ("GET", svc["health_path"], None)))
        while not self._halt.is_set():
            url = self._urls.get(svc["name"])
            if not url:
                await asyncio.sleep(0.5)
                continue
            method, path, body = make(rng)
            try:
                await client.request(method, url + path, json=body)
                self.sent += 1
            except httpx.HTTPError:
                await asyncio.sleep(0.3)
            pace = max(0.2, replay.load_factor(profile, time.time())) if profile else 1.0  # replay: the recorded daily load curve
            await asyncio.sleep(self.think_s / pace)

    async def _main(self) -> None:
        services = self._refresh()
        async with httpx.AsyncClient(timeout=5.0) as client:
            tasks = [asyncio.create_task(self._worker(client, svc, random.Random(f"{svc['name']}-{n}")))
                     for svc in services for n in range(self.workers)]
            while not self._halt.is_set():
                await asyncio.sleep(2.0)
                self._refresh()
            await asyncio.gather(*tasks, return_exceptions=True)

    def start(self) -> None:
        if self.enabled:
            return
        self._halt.clear()
        self.enabled = True
        self._thread = threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True, name="traffic")
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout=8)
        self.enabled = False
