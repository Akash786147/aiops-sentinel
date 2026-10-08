"""Quote calculation for a shopping cart."""
from __future__ import annotations

GOLD_DISCOUNT = 0.10


def line_total(item: dict) -> float:
    return item["qty"] * item["price"]


def apply_discounts(items: list[dict], tier: str) -> float:
    """Cart subtotal after the customer's tier discount."""
    rate = GOLD_DISCOUNT if tier == "gold" else 0.0
    subtotal = sum(line_total(item) for item in items)
    return round(subtotal * (1 - rate), 2)


def average_item_price(items: list[dict]) -> float:
    """Mean unit price, shown on the quote page. An empty cart has no average."""
    if not items:
        return 0.0
    return round(sum(item["price"] for item in items) / len(items), 2)
