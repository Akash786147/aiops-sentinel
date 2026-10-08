"""Inventory service: stock lookups and reservations."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.telemetry import Telemetry
from inventory import cache, store

app = FastAPI(title="inventory")
Telemetry("inventory").install(app)


class ReserveRequest(BaseModel):
    sku: str
    qty: int = 1


@app.get("/stock/{sku}")
def stock_level(sku: str):
    level = store.get_stock(sku)
    cache.record_view(sku, level)
    if level is None:
        raise HTTPException(404, "unknown sku")
    return {"sku": sku, "level": level}


@app.post("/reserve")
def reserve(request: ReserveRequest):
    if not store.reserve(request.sku, request.qty):
        raise HTTPException(409, "insufficient stock")
    return {"reserved": True}


@app.get("/views")
def views():
    return cache.recent_views()
