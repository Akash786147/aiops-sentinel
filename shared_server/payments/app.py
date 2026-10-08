"""Payments service: charges and refunds."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.telemetry import Telemetry
from payments import config, fraud, gateway

app = FastAPI(title="payments")
Telemetry("payments").install(app)


class PayRequest(BaseModel):
    email: str
    amount: float


@app.post("/pay")
def pay(request: PayRequest):
    if fraud.is_suspicious(request.email, request.amount):
        raise HTTPException(403, "payment held for review")
    return {**gateway.charge(request.amount), "currency": config.CURRENCY}


@app.post("/refunds")
def refund(payload: dict):
    reason = (payload.get("reason") or "unspecified").strip()
    return {"refunded": float(payload.get("amount", 0)), "reason": reason}
