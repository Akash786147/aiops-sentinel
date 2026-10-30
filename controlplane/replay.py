"""Replay traffic for services that ship a recorded traffic profile (``<package>/profile.json``).

The request mix and the shape of the day come from real data; only the clock is compressed, so a day of load plays in minutes.
"""
from __future__ import annotations

import json
import os
import random
from bisect import bisect_left
from collections.abc import Callable
from itertools import accumulate
from pathlib import Path

DAY_S = float(os.getenv("SENTINEL_REPLAY_DAY_S", "600"))


def load(service_root: Path, package: str | None) -> dict | None:
    path = Path(service_root) / (package or "") / "profile.json"
    return json.loads(path.read_text(encoding="utf-8")) if package and path.is_file() else None


def request_maker(profile: dict) -> Callable[[random.Random], tuple[str, str, dict | None]]:
    endpoints = profile["endpoints"]
    cumulative = list(accumulate(e["share"] for e in endpoints))

    def make(rng: random.Random) -> tuple[str, str, dict | None]:
        spec = endpoints[min(bisect_left(cumulative, rng.random() * cumulative[-1]), len(endpoints) - 1)]
        path = spec["path"].replace("{id}", str(rng.randint(1, 5000)))
        return spec["method"], path, ({} if spec["method"] in ("POST", "PUT") else None)

    return make


def load_factor(profile: dict, now: float, day_s: float = DAY_S) -> float:
    """Load relative to the daily mean (1.0) at ``now``, with a day of real load compressed into ``day_s`` seconds."""
    hour = int((now % day_s) / day_s * 24) % 24
    return profile["hourly_load"][hour] * 24
