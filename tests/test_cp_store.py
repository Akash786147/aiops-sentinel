from controlplane.config import Settings
from controlplane.store import Store


def _service(store, name="orders"):
    store.add_service({"name": name, "source": f"sample:{name}", "kind": "sample", "package": name, "module": f"{name}.app:app",
                       "port": 8000, "health_path": "/health", "metrics_path": "/sentinel/metrics", "mem_limit_mb": 256,
                       "cpu_limit": 0.5, "owner": "team", "auto_rollback": True})


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_HOME", str(tmp_path))
    monkeypatch.setenv("SENTINEL_RUNTIME", "process")
    s = Settings.from_env()
    assert s.home == tmp_path and s.runtime == "process" and s.db_path == tmp_path / "sentinel.db"
    assert s.services_dir == tmp_path / "services" and s.stability_window_s > 0


def test_service_round_trip_and_update(tmp_path):
    store = Store(tmp_path / "s.db")
    _service(store)
    assert store.get_service("orders")["auto_rollback"] is True
    store.update_service("orders", mem_limit_mb=128, auto_rollback=False)
    svc = store.get_service("orders")
    assert svc["mem_limit_mb"] == 128 and svc["auto_rollback"] is False
    assert [s["name"] for s in store.list_services()] == ["orders"]
    assert store.get_service("nope") is None


def test_deployments_current_and_last_good_are_per_service(tmp_path):
    store = Store(tmp_path / "s.db")
    _service(store)
    _service(store, "payments")
    a = store.add_deployment("orders", commit="a" * 40, message="first", image="img:a", trigger="initial")
    b = store.add_deployment("orders", commit="b" * 40, message="second", image="img:b", trigger="restart")
    p = store.add_deployment("payments", commit="c" * 40, message="p", image="img:c", trigger="initial")
    store.update_deployment(a, status="healthy")
    store.set_last_good(a)
    store.set_last_good(p)
    store.update_deployment(b, status="healthy")
    store.set_last_good(b)
    assert store.last_good("orders")["id"] == b and store.last_good("payments")["id"] == p
    assert store.get_deployment(a)["last_good"] is False
    assert store.current_deployment("orders")["id"] == b
    assert [d["id"] for d in store.deployments("orders")] == [b, a]


def test_open_incident_lookup_and_audit_order(tmp_path):
    store = Store(tmp_path / "s.db")
    _service(store)
    inc = store.open_incident("orders", deployment_id=None, kind="crash", summary="exited 1", signals=[{"kind": "crash"}])
    assert store.open_incident_for("orders")["id"] == inc
    store.update_incident(inc, status="diagnosed", diagnosis={"x": 1})
    assert store.open_incident_for("orders")["id"] == inc and store.get_incident(inc)["diagnosis"] == {"x": 1}
    store.update_incident(inc, status="resolved")
    assert store.open_incident_for("orders") is None
    store.audit("sentinel", "deploy", service="orders", commit="abc")
    store.audit("akash", "approve", service="orders", incident_id=inc)
    events = store.audit_events(limit=10)
    assert [e["action"] for e in events] == ["approve", "deploy"] and events[1]["detail"]["commit"] == "abc"
    assert [e["action"] for e in store.audit_events(limit=10, service="payments")] == []
