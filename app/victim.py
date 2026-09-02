"""Deliberately imperfect order service used only to demonstrate a safe scripted incident."""
from __future__ import annotations

import time
from collections import deque

from fastapi import FastAPI, HTTPException

app = FastAPI(title="AIOps Sentinel victim order service")
orders = [{"id": i, "customer": f"customer-{i % 4}", "total": 20 + i} for i in range(1, 31)]
latencies: deque[float] = deque(maxlen=500)
request_count = 0
error_count = 0


@app.get("/orders")
def list_orders(include_customer_profile: bool = False):
    """Known demo defect: repeated per-order lookup makes the detailed path slow at load."""
    global request_count
    started = time.perf_counter()
    request_count += 1
    result = []
    for order in orders:
        item = order.copy()
        if include_customer_profile:
            # Intentional N+1 style delay. Remediation is batching/cache, never an automatic merge.
            time.sleep(0.025)
            item["customer_profile"] = {"tier": "standard", "id": order["customer"]}
        result.append(item)
    latencies.append((time.perf_counter() - started) * 1000)
    return result


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    for order in orders:
        if order["id"] == order_id:
            return order
    raise HTTPException(404, "order not found")


@app.get("/metrics")
def metrics():
    p95 = sorted(latencies)[max(0, int(len(latencies) * .95) - 1)] if latencies else 0
    return {"request_count": request_count, "error_count": error_count, "error_rate": error_count / request_count if request_count else 0, "p95_ms": round(p95, 1), "sample_count": len(latencies)}
