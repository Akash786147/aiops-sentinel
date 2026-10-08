import os

from fastapi import FastAPI

from services.monitor import collect, is_incident

app = FastAPI(title="AIOps Sentinel Monitoring Service", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "monitor"}


@app.post("/check")
async def check(target_url: str = os.getenv("VICTIM_URL", "http://victim:8001")) -> dict:
    metrics = await collect(target_url)
    return {"metrics": metrics, "incident_detected": is_incident(metrics)}
