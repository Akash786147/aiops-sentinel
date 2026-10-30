"""Gate-pass journey: request, approve and check passes at the campus gate."""
from __future__ import annotations

import random

from campus import behaviour


def process(endpoint: str, rng: random.Random) -> int:
    """Spend the recorded time on the request and answer with the recorded status mix."""
    behaviour.work(behaviour.latency_ms(endpoint, rng))
    return behaviour.status(endpoint, rng)
