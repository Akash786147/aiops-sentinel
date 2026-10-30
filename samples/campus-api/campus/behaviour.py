"""What the real application looked like from the outside: per-endpoint latency curve and status mix, from profile.json."""
from __future__ import annotations

import json
import random
import time
from functools import lru_cache
from pathlib import Path

PROFILE = Path(__file__).with_name("profile.json")


@lru_cache(maxsize=1)
def profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def endpoints() -> dict[str, dict]:
    return {e["key"]: e for e in profile()["endpoints"]}


def latency_ms(endpoint: str, rng: random.Random) -> float:
    """A latency drawn from the endpoint's recorded quantile curve (linear between quantiles)."""
    spec = endpoints()[endpoint]["latency_ms"]
    points = profile()["curve_quantiles"]
    curve = spec["curve"]
    u = rng.random() * 100
    for i in range(1, len(points)):
        if u <= points[i]:
            lo, hi = points[i - 1], points[i]
            frac = 0.0 if hi == lo else (u - lo) / (hi - lo)
            return curve[i - 1] + frac * (curve[i] - curve[i - 1])
    return curve[-1]


def status(endpoint: str, rng: random.Random) -> int:
    """A status code drawn from the endpoint's recorded mix."""
    u, total = rng.random(), 0.0
    for code, share in endpoints()[endpoint]["status"].items():
        total += share
        if u <= total:
            return int(code)
    return 200


def work(ms: float) -> None:
    time.sleep(max(ms, 0.0) / 1000)
