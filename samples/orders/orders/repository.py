"""In-memory order store. ``_query`` stands in for one database round trip."""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger("orders.repository")

DB_ROUND_TRIP_S = 0.002
CUSTOMERS = {
    f"c{i}": {"id": f"c{i}", "tier": "gold" if i % 5 == 0 else "standard", "region": "eu" if i % 2 else "us"}
    for i in range(50)
}
ORDERS = [
    {
        "id": i,
        "customer_id": f"c{i % 50}",
        "items": [{"sku": f"sku-{(i + k) % 40}", "qty": 1 + k, "price": 5.0 + k} for k in range(3)],
    }
    for i in range(1, 201)
]


def _query(cost: int = 1) -> None:
    time.sleep(DB_ROUND_TRIP_S * cost)


def load_customer(customer_id: str) -> dict | None:
    """Fetch one customer profile."""
    _query()
    return CUSTOMERS.get(customer_id)


def load_customers(customer_ids: set[str]) -> dict[str, dict]:
    """Fetch many customer profiles in a single round trip."""
    _query()
    return {cid: CUSTOMERS[cid] for cid in customer_ids if cid in CUSTOMERS}


def fetch_orders_with_profiles(limit: int = 50) -> list[dict]:
    """Return recent orders joined with their customer profile."""
    orders = ORDERS[:limit]
    profiles = load_customers({order["customer_id"] for order in orders})
    return [{**order, "customer": profiles.get(order["customer_id"])} for order in orders]


def get_order(order_id: int) -> dict | None:
    """Look up one order by id."""
    _query()
    logger.debug("order lookup %s", order_id)
    for order in ORDERS:
        if order["id"] == order_id:
            return order
    return None


def summarize(limit: int = 20) -> dict:
    """Small dashboard summary: order count and the most recent order ids."""
    _query()
    return {"count": len(ORDERS), "recent": [order["id"] for order in ORDERS[-limit:]]}


def export_snapshot() -> str:
    """Serialise the whole table. Used by the nightly export job, never on a request path."""
    return json.dumps(ORDERS)
