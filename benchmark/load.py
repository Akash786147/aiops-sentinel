"""Closed-loop traffic for the three services, including the awkward inputs real users send.

The same request mix runs before and after a deployment, so any change in telemetry comes
from the code (or, in H03, from the traffic multiplier), not from different inputs.
"""
from __future__ import annotations

import asyncio
import random

import httpx

THINK_S = 0.02
WORKERS = 3


def orders_request(rng: random.Random) -> tuple[str, str, dict | None]:
    roll = rng.random()
    if roll < 0.3:
        return "GET", "/orders", None
    if roll < 0.5:
        return "GET", "/orders/summary", None
    if roll < 0.8:
        return "GET", f"/orders/{rng.randint(1, 220)}", None
    items = [{"sku": f"sku-{rng.randint(0, 5)}", "qty": 1, "price": 9.5} for _ in range(rng.choice([0, 0, 2, 3, 3, 3, 3, 3, 3, 3]))]
    return "POST", "/quote", {"items": items, "tier": rng.choice(["gold", "standard"])}


def inventory_request(rng: random.Random) -> tuple[str, str, dict | None]:
    roll = rng.random()
    if roll < 0.45:
        return "GET", f"/stock/sku-{rng.randint(0, 44)}", None
    if roll < 0.9:
        return "POST", "/reserve", {"sku": f"sku-{rng.randint(0, 44)}", "qty": 1}
    return "GET", "/views", None


def payments_request(rng: random.Random) -> tuple[str, str, dict | None]:
    if rng.random() < 0.7:
        roll = rng.random()
        if roll < 0.85:
            email = f"user{rng.randint(1, 999)}@shop.example"
        elif roll < 0.95:
            email = "qa" + "a" * rng.randint(19, 21) + "@example.org"
        else:
            email = "test.bot@example.com"
        return "POST", "/pay", {"email": email, "amount": round(rng.uniform(5, 300), 2)}
    body = {"amount": round(rng.uniform(5, 100), 2)}
    if rng.random() < 0.7:
        body["reason"] = rng.choice(["damaged", "late", " changed mind "])
    return "POST", "/refunds", body


MIX = {"orders": orders_request, "inventory": inventory_request, "payments": payments_request}


async def _worker(client: httpx.AsyncClient, base_url: str, make, rng: random.Random, stop: asyncio.Event) -> None:
    while not stop.is_set():
        method, path, body = make(rng)
        try:
            await client.request(method, base_url + path, json=body)
        except httpx.HTTPError:
            await asyncio.sleep(0.1)  # a down service must not spin the generator
        await asyncio.sleep(THINK_S)


async def run(urls: dict[str, str], seconds: float, multiplier: dict[str, int] | None = None, seed: int = 0) -> None:
    multiplier = multiplier or {}
    stop = asyncio.Event()
    limits = httpx.Limits(max_connections=64, max_keepalive_connections=32)
    async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
        tasks = [
            asyncio.create_task(_worker(client, url, MIX[name], random.Random(f"{seed}-{name}-{n}"), stop))
            for name, url in urls.items()
            for n in range(WORKERS * multiplier.get(name, 1))
        ]
        await asyncio.sleep(seconds)
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
