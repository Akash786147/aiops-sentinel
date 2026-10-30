"""Control-plane HTTP API (process runtime, background loops off; actions still run as background jobs)."""
import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from controlplane.app import create_app
from controlplane.config import Settings


@pytest.fixture()
def client(tmp_path):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", health_timeout_s=20)
    app = create_app(settings, start_background=False, bootstrap=())
    with TestClient(app) as c:
        c.core = app.state.core
        yield c


def wait_healthy(client, name, timeout=40.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        svc = client.get(f"/api/services/{name}").json()
        dep = svc.get("current")
        if dep and dep["status"] == "healthy" and not svc["busy"]:
            return svc
        time.sleep(0.3)
    raise AssertionError(f"{name} never became healthy")


@pytest.fixture()
def orders(client):
    assert client.post("/api/services", json={"kind": "sample", "name": "orders"}).status_code == 200
    return wait_healthy(client, "orders")


def test_add_sample_service_deploys_it(client, orders):
    listed = client.get("/api/services").json()
    assert [s["name"] for s in listed] == ["orders"] and listed[0]["current"]["status"] == "healthy"
    assert client.post("/api/services", json={"kind": "sample", "name": "orders"}).status_code == 400
    assert client.post("/api/services", json={"kind": "sample", "name": "nope"}).status_code == 400


def test_actions_are_refused_while_one_runs_and_unknown_service_is_404(client, orders):
    with client.core.locks.hold("orders"):
        assert client.post("/api/services/orders/restart", json={"actor": "akash"}).status_code == 409
    assert client.post("/api/services/ghost/restart", json={}).status_code == 404


def test_code_editor_endpoints_and_traversal(client, orders):
    files = client.get("/api/services/orders/files").json()
    assert "orders/app.py" in files["files"]
    text = client.get("/api/services/orders/file", params={"path": "orders/pricing.py"}).json()["content"]
    assert "GOLD_DISCOUNT" in text
    assert client.put("/api/services/orders/file", json={"path": "orders/pricing.py", "content": text.replace("0.10", "0.12")}).status_code == 200
    assert "+GOLD_DISCOUNT = 0.12" in client.get("/api/services/orders/diff").json()["diff"]
    assert client.get("/api/services/orders/file", params={"path": "../../etc/passwd"}).status_code == 400
    head = orders["current"]["commit"]
    assert "GOLD_DISCOUNT = 0.10" in client.get("/api/services/orders/file", params={"path": "orders/pricing.py", "ref": head}).json()["content"]
    assert client.get("/api/services/orders/file", params={"path": "orders/pricing.py", "ref": "not-a-sha"}).status_code == 400
    assert client.put("/api/services/orders/file", json={"path": "../evil.py", "content": "x"}).status_code == 400


def test_restart_deploys_the_change(client, orders):
    first = orders["current"]["id"]
    text = client.get("/api/services/orders/file", params={"path": "orders/pricing.py"}).json()["content"]
    client.put("/api/services/orders/file", json={"path": "orders/pricing.py", "content": text.replace("0.10", "0.11")})
    assert client.post("/api/services/orders/restart", json={"actor": "akash", "message": "Raise gold discount"}).status_code == 202
    time.sleep(0.5)
    svc = wait_healthy(client, "orders")
    assert svc["current"]["id"] != first and svc["current"]["message"] == "Raise gold discount"
    assert any(a["action"] == "deployed" and a["actor"] == "akash" for a in client.get("/api/audit").json())


def test_lab_apply_preview_and_reset(client, orders):
    lab = client.get("/api/lab/orders").json()
    assert any(r["id"] == "F01" and r["available"] for r in lab["recipes"])
    assert "load_customer" in client.post("/api/lab/orders/preview", json={"recipe": "F01"}).json()["diff"]
    assert client.post("/api/lab/orders/apply", json={"recipe": "F01", "actor": "syna"}).json()["files"] == ["orders/repository.py"]
    assert client.get("/api/lab/orders").json()["dirty"] is True
    assert client.post("/api/lab/orders/reset", json={"actor": "syna"}).status_code == 200
    assert client.get("/api/lab/orders").json()["dirty"] is False
    assert client.post("/api/lab/orders/apply", json={"recipe": "nope"}).status_code == 404


def test_alert_webhook_incident_and_approve_refused_without_patch(client, orders):
    payload = {"alerts": [{"status": "firing", "labels": {"alertname": "HighErrorRate", "service": "orders"}, "annotations": {"summary": "5xx"}}]}
    assert client.post("/api/alerts", json=payload).json() == {"handled": 1}
    incidents = client.get("/api/incidents").json()
    assert len(incidents) == 1 and incidents[0]["kind"] == "alert"
    detail = client.get(f"/api/incidents/{incidents[0]['id']}").json()
    assert detail["incident"]["service"] == "orders" and detail["audit"]
    assert client.post(f"/api/incidents/{incidents[0]['id']}/approve", json={"approver": "Akash"}).status_code == 409
    assert client.post(f"/api/incidents/{incidents[0]['id']}/dismiss", json={"actor": "Akash"}).json()["status"] == "dismissed"


def test_traffic_overview_metrics_health_and_events(client, orders):
    assert client.post("/api/traffic", json={"enabled": True}).json()["enabled"] is True
    assert client.post("/api/traffic", json={"enabled": False}).json()["enabled"] is False
    overview = client.get("/api/overview").json()
    assert overview["runtime"] == "process" and overview["services"][0]["name"] == "orders" and "host" in overview
    assert "sentinel_open_incidents" in client.get("/metrics").text
    assert client.get("/api/health").json()["status"] == "ok"
    with client.stream("GET", "/api/events?since=0&once=1") as response:
        lines = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    assert any(e["kind"] == "deployment" for e in lines)
    assert client.get("/").status_code == 200


def _git(cwd, *args):
    import subprocess
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_add_service_from_a_git_repository(client, tmp_path):
    """Bring-your-own repo: clone, register from its sentinel.json, deploy, and refuse bad input."""
    import shutil
    from pathlib import Path

    repo = tmp_path / "byo-repo"
    shutil.copytree(Path(__file__).resolve().parents[1] / "samples" / "inventory", repo, ignore=shutil.ignore_patterns("__pycache__"))
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "initial")

    resp = client.post("/api/services", json={"kind": "git", "name": "my-stock", "url": repo.as_uri(), "branch": "main"})
    assert resp.status_code == 200, resp.text
    svc = wait_healthy(client, "my-stock")
    assert svc["kind"] == "git" and svc["current"]["commit"]

    assert client.post("/api/services", json={"kind": "git", "name": "my-stock", "url": repo.as_uri()}).status_code == 400  # duplicate
    assert client.post("/api/services", json={"kind": "git", "name": "two", "url": repo.as_uri(), "port": 99999}).status_code == 422
    assert client.post("/api/services", json={"kind": "git", "name": "two", "url": repo.as_uri(), "health_path": "no-slash"}).status_code == 422
    custom = client.post("/api/services", json={"kind": "git", "name": "two", "url": repo.as_uri(), "port": 5000, "health_path": "/health"})
    assert custom.status_code == 200 and (custom.json()["port"], custom.json()["health_path"]) == (5000, "/health")
    assert client.post("/api/services", json={"kind": "git", "name": "Bad Name", "url": repo.as_uri()}).status_code == 400
    assert client.post("/api/services", json={"kind": "git", "name": "other", "url": "ftp://example.com/x"}).status_code == 400
    assert client.post("/api/services", json={"kind": "git", "name": "ghost", "url": (tmp_path / "missing").as_uri()}).status_code == 400


def test_synthetic_lab_samples_are_hidden_unless_the_lab_is_enabled(tmp_path, monkeypatch):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process")
    monkeypatch.delenv("SENTINEL_LAB", raising=False)
    with TestClient(create_app(settings, start_background=False, bootstrap=())) as c:
        assert not {"orders", "inventory", "payments"} & set(c.get("/api/overview").json()["samples"])
    monkeypatch.setenv("SENTINEL_LAB", "1")
    with TestClient(create_app(settings, start_background=False, bootstrap=())) as c:
        assert {"orders", "inventory", "payments"} <= set(c.get("/api/overview").json()["samples"])


def test_service_policy_endpoint_reports_the_pack_and_journey_slos(client):
    assert client.post("/api/services", json={"kind": "sample", "name": "campus-api"}).status_code == 200
    wait_healthy(client, "campus-api")
    body = client.get("/api/services/campus-api/policy").json()
    assert body["pack"]["name"] == "campus" and body["pack"]["version"] >= 1 and "demonstration" in body["pack"]["description"].lower()
    assert {j["journey"] for j in body["journeys"]} == {"gatepass", "shuttle", "biometric"}
    assert client.get("/api/services/ghost/policy").status_code == 404


def test_external_validation_results_are_served_when_present(client, tmp_path, monkeypatch):
    import json

    from controlplane import app as app_module

    folder = tmp_path / "external"
    folder.mkdir()
    (folder / "microsoft.json").write_text(json.dumps({"dataset": "ms", "methods": {"robust_persistence": {"all": {"f1": 0.3}}}}), encoding="utf-8")
    monkeypatch.setattr(app_module, "EXTERNAL_RESULTS", folder)
    body = client.get("/api/results/external").json()
    assert body["microsoft"]["methods"]["robust_persistence"]["all"]["f1"] == 0.3 and body["rcaeval_re1"] is None
    (client.core.settings.home / "data").mkdir()  # a result written on the server wins over the one shipped in the repository
    (client.core.settings.home / "data" / "microsoft.json").write_text(json.dumps({"dataset": "server", "methods": {}}), encoding="utf-8")
    assert client.get("/api/results/external").json()["microsoft"]["dataset"] == "server"
