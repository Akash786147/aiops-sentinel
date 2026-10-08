"""The three sample services are self-contained repos Sentinel can build and run."""
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
NAMES = ["orders", "inventory", "payments"]
FIRST_ROUTE = {"orders": "/orders", "inventory": "/stock/sku-1", "payments": "/refunds"}


@pytest.fixture()
def load_app(monkeypatch, tmp_path):
    loaded = []

    def _load(name):
        root = SAMPLES / name
        monkeypatch.setenv("SENTINEL_LOG_DIR", str(tmp_path / "logs"))
        monkeypatch.syspath_prepend(str(root))
        for mod in [m for m in sys.modules if m.split(".")[0] in (name, "common")]:
            del sys.modules[mod]
        module = importlib.import_module(f"{name}.app")
        loaded.append(name)
        return module.app

    yield _load
    for mod in [m for m in sys.modules if m.split(".")[0] in loaded + ["common"]]:
        del sys.modules[mod]


@pytest.mark.parametrize("name", NAMES)
def test_sample_serves_health_metrics_and_drain(load_app, name):
    client = TestClient(load_app(name))
    assert client.get("/health").json() == {"status": "ok", "service": name}
    if name == "payments":
        client.post("/refunds", json={"amount": 5, "reason": "late"})
    else:
        client.get(FIRST_ROUTE[name])
    prom = client.get("/metrics")
    assert prom.status_code == 200 and "http_requests_total" in prom.text and "http_request_duration_seconds_bucket" in prom.text
    drain = client.get("/sentinel/metrics").json()
    assert drain["service"] == name and drain["routes"]


def test_exception_is_logged_as_json(load_app, tmp_path, capsys):
    client = TestClient(load_app("orders"))
    from orders import pricing

    original = pricing.average_item_price

    def broken(items):
        return sum(i["price"] for i in items) / len(items)

    pricing.average_item_price = broken
    try:
        assert client.post("/quote", json={"items": [], "tier": "gold"}).status_code == 500
    finally:
        pricing.average_item_price = original
    line = (tmp_path / "logs" / "orders.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    event = json.loads(line)
    assert event["exception"] == "ZeroDivisionError" and event["frames"]
    assert '"exception": "ZeroDivisionError"' in capsys.readouterr().out


@pytest.mark.parametrize("name", NAMES)
def test_repo_has_dockerfile_and_manifest(name):
    root = SAMPLES / name
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "EXPOSE 8000" in dockerfile and "HEALTHCHECK" in dockerfile and "USER app" in dockerfile
    assert f"{name}.app:app" in dockerfile
    manifest = (root / "sentinel.json").read_text(encoding="utf-8")
    assert json.loads(manifest)["module"] == f"{name}.app:app"
    assert "prometheus_client" in (root / "requirements.txt").read_text(encoding="utf-8")
