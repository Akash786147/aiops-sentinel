"""Orders service: order listing, lookup, dashboard summary and cart quotes."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.telemetry import Telemetry
from orders import pricing, repository

app = FastAPI(title="orders")
Telemetry("orders").install(app)


class QuoteRequest(BaseModel):
    items: list[dict] = []
    tier: str = "standard"


@app.get("/orders")
def list_orders(limit: int = 50):
    return repository.fetch_orders_with_profiles(limit)


@app.get("/orders/summary")
def order_summary():
    return repository.summarize()


@app.get("/orders/{order_id}")
def order_detail(order_id: int):
    order = repository.get_order(order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    return order


@app.post("/quote")
def quote(request: QuoteRequest):
    return {
        "total": pricing.apply_discounts(request.items, request.tier),
        "average_item_price": pricing.average_item_price(request.items),
    }
