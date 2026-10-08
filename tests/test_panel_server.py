import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from panel import replay
from panel.server import create_app


@pytest.fixture()
def client(panel_root):
    with TestClient(create_app(panel_root, speed=100000)) as c:
        yield c


def finish(client, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/state").json()
        last = [e for e in state["events"] if e["kind"] == "run"][-1:]
        if last and last[0]["data"]["state"] in ("done", "failed"):
            return state
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_scenario_catalog_hides_the_answer_and_flags_availability(client):
    scenarios = client.get("/api/scenarios").json()
    assert [s["id"] for s in scenarios][:2] == ["F01", "F02"] and len(scenarios) == 15
    assert all({"file", "start_line", "end_line", "fault", "patches"}.isdisjoint(s) for s in scenarios)
    flags = {s["id"]: s["replay_available"] for s in scenarios}
    assert flags["F01"] is True and flags["F02"] is False


def test_run_replay_then_state_recovers_the_whole_run(client):
    started = client.post("/api/run", json={"scenario": "F01", "mode": "replay"})
    assert started.status_code == 200 and started.json()["run"]["scenario"] == "F01"
    state = finish(client)  # a refreshed page or second tab calls the same endpoint
    kinds = [e["kind"] for e in state["events"]]
    assert kinds[0] == "run" and "result" in kinds and state["next"] >= len(state["events"])
    assert [t["name"] for t in state["tenants"]] == ["orders", "inventory", "payments"]
    assert state["run"]["id"] == started.json()["run"]["id"]


def test_sse_streams_events_until_the_run_is_done(client):
    since = client.post("/api/run", json={"scenario": "F01", "mode": "replay"}).json()["since"]
    seen = []
    with client.stream("GET", f"/api/events?since={since}&until_done=1") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]))
    assert seen[0]["kind"] == "run" and seen[-1]["data"]["state"] == "done"
    assert [e["n"] for e in seen] == sorted(e["n"] for e in seen)


def test_errors_for_bad_run_requests(client):
    assert client.post("/api/run", json={"scenario": "F99", "mode": "replay"}).status_code == 404
    assert client.post("/api/run", json={"scenario": "F02", "mode": "replay"}).status_code == 503
    assert client.post("/api/run", json={"scenario": "F01", "mode": "warp"}).status_code == 422


def test_code_endpoint_serves_workspace_files_and_refuses_traversal(client):
    client.post("/api/run", json={"scenario": "F01", "mode": "replay"})
    finish(client)
    ok = client.get("/api/code", params={"path": "orders/app.py"})
    assert ok.status_code == 200 and "def list_orders" in ok.json()["text"]
    assert client.get("/api/code", params={"path": "../services.yaml"}).status_code == 400
    assert client.get("/api/code", params={"path": "/etc/passwd"}).status_code == 400
    assert client.get("/api/code", params={"path": "orders/nope.py"}).status_code == 404
    assert client.get("/api/code", params={"path": "orders/app.py", "run": "other"}).status_code == 404


def test_approve_validates_and_records_without_touching_code(client):
    assert client.post("/api/approve", json={"approver": "Akash", "note": ""}).status_code == 409  # no run yet
    client.post("/api/run", json={"scenario": "F01", "mode": "replay"})
    finish(client)
    assert client.post("/api/approve", json={"approver": "", "note": ""}).status_code == 422
    done = client.post("/api/approve", json={"approver": "Akash", "note": "ship it"})
    assert done.status_code == 200 and done.json()["decision"] == "approved"
    audit = client.get("/api/audit").json()
    assert audit[-1]["decision"] == "approved" and audit[0]["stage"] == "detect"


def test_results_endpoint_and_static_index(client):
    results = client.get("/api/results").json()
    assert results["available"] is True and results["runs"] == 1
    page = client.get("/")
    assert page.status_code == 200 and "Sentinel Console" in page.text


def test_second_run_request_is_a_409(panel_root, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(replay, "run_replay", lambda ctx, *a: gate.wait(5))
    with TestClient(create_app(panel_root)) as client:
        assert client.post("/api/run", json={"scenario": "F01", "mode": "replay"}).status_code == 200
        assert client.post("/api/run", json={"scenario": "F01", "mode": "replay"}).status_code == 409
        gate.set()
