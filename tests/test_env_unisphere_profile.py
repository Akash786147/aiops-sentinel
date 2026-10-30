"""Raw Unisphere request log -> aggregated profile: shape of real traffic, nothing personal."""
import json
import random

import pytest

from environments.unisphere.build_profile import build_profile, normalise

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiJzZWNyZXQifQ.c2lnbmF0dXJl"
EMAIL = "someone.private@example.com"
USER = "b6445d00-f5c8-4ba5-9489-d079b87042f1"


def row(i, endpoint, method="GET", code="200", ms=5.0, hour=9, user=USER, error=None, payload=None):
    return {"logId": i, "userId": user, "endpoint": endpoint, "requestType": method, "requestPayload": payload,
            "responseCode": code, "responsePayload": json.dumps({"email": EMAIL}), "userAgent": "Dart/3.7", "timestamp": f"2026-02-27 {hour:02d}:10:00.000",
            "responseTime": f"{ms:.3f}", "errorMessage": error}


@pytest.fixture()
def rows():
    rng = random.Random(1)
    out = []
    for i in range(400):
        out.append(row(i, "/api/v2/gatepass?page=1&limit=10", ms=rng.uniform(2, 20), hour=9, payload=json.dumps({"accessToken": TOKEN})))
    for i in range(400, 500):
        out.append(row(i, f"/api/v2/gatepass/{USER}", "PUT", ms=rng.uniform(5, 30), hour=10))
    for i in range(500, 560):
        out.append(row(i, "/api/v2/user/me", code="401", ms=3.0, hour=9, user=None, error=f"User {EMAIL} is inactive"))
    out.append(row(900, "/api/v2/rare/once", ms=1.0))
    return out


def test_normalise_strips_queries_and_ids():
    assert normalise(f"/api/v2/gatepass/{USER}?x=1") == "/api/v2/gatepass/{id}"
    assert normalise("/api/v2/shuttle/12345/book") == "/api/v2/shuttle/{id}/book"


def test_profile_keeps_traffic_shape(rows):
    p = build_profile(rows, min_requests=20)
    keys = {e["key"]: e for e in p["endpoints"]}
    assert "GET /api/v2/gatepass" in keys and "PUT /api/v2/gatepass/{id}" in keys
    gate = keys["GET /api/v2/gatepass"]
    assert gate["journey"] == "gatepass" and gate["share"] == pytest.approx(400 / 560, abs=0.01)
    assert gate["latency_ms"]["p50"] < gate["latency_ms"]["p99"] <= gate["latency_ms"]["max"] and len(gate["latency_ms"]["curve"]) == 11
    assert keys["GET /api/v2/user/me"]["status"]["401"] == 1.0
    assert sum(e["share"] for e in p["endpoints"]) == pytest.approx(1.0, abs=1e-6)
    assert "GET /api/v2/rare/once" not in keys and p["other_share"] == pytest.approx(1 / 561, abs=1e-4)
    load = p["hourly_load"]
    assert len(load) == 24 and sum(load) == pytest.approx(1.0) and load[9] > load[10] > 0


def test_nothing_personal_survives(rows):
    text = json.dumps(build_profile(rows, min_requests=20))
    for secret in (TOKEN, EMAIL, USER, "eyJ", "@", "Dart"):
        assert secret not in text
