"""Monitor samples each running service once a tick; traffic keeps services under real load."""
import time
from dataclasses import replace

import httpx
import pytest

from controlplane.config import Settings
from controlplane.core import Core
from controlplane.deployer import Deployer
from controlplane.monitor import Monitor
from controlplane.registry import register_sample
from controlplane.traffic import Traffic


@pytest.fixture()
def running(tmp_path):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", health_timeout_s=20)
    core = Core.create(settings)
    register_sample(core, "orders")
    dep = Deployer(core).deploy("orders", trigger="initial", actor="test")
    yield core, dep
    core.runtime.shutdown()


def test_sample_has_routes_resources_and_lifecycle(running):
    core, dep = running
    monitor = Monitor(core, keep=5)
    httpx.get(dep["url"] + "/orders")
    sample = monitor.tick()["orders"]
    assert sample["up"] is True and "GET /orders" in sample["routes"]
    assert sample["rss_mb"] > 5 and sample["mem_limit_mb"] == 256 and sample["deployment"] == dep["id"]
    assert sample["health"] in ("healthy", "starting") and sample["restarts"] == 0
    for _ in range(7):
        monitor.tick()
    assert len(monitor.series("orders")) == 5
    events = [e for e in core.bus.current_run()[0] if e["kind"] == "telemetry"]
    assert events and "samples" not in events[-1]["data"]


def test_stopped_service_is_reported_down(running):
    core, _ = running
    monitor = Monitor(core)
    Deployer(core).stop("orders", actor="test")
    sample = monitor.tick().get("orders")
    assert sample is None or sample["up"] is False


def test_traffic_hits_running_services(running):
    core, _ = running
    traffic = Traffic(core, workers=2)
    traffic.start()
    try:
        deadline = time.time() + 10
        while traffic.sent < 5 and time.time() < deadline:
            time.sleep(0.2)
    finally:
        traffic.stop()
    assert traffic.sent >= 5 and traffic.enabled is False


def _byo_row(name="byo"):
    return {"name": name, "source": "https://example.test/x.git", "kind": "git", "package": None, "module": None, "port": 8000,
            "health_path": "/health", "metrics_path": None, "mem_limit_mb": 256, "cpu_limit": 0.5, "owner": "unassigned"}


def test_traffic_never_targets_a_cloned_repository(running):
    """Bring-your-own services only see the requests a person sends; Sentinel adds none."""
    core, _ = running
    core.store.add_service(_byo_row())
    dep_id = core.store.add_deployment("byo", "abc", "initial", "img", "initial", status="healthy")
    core.store.update_deployment(dep_id, url="http://127.0.0.1:9", instance="i-1")
    traffic = Traffic(core)
    traffic._refresh()
    assert "orders" in traffic.status()["targets"] or traffic._urls.get("orders")
    assert "byo" not in traffic._urls


class FakePrometheus:
    """Answers the three instant queries the monitor asks for a service it can only see through Traefik."""

    def __init__(self, total="10", errors="2", p95="0.25"):
        self.values = {"total": total, "errors": errors, "p95": p95}
        self.queries = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        self.queries.append(query)
        kind = "p95" if "histogram_quantile" in query else "errors" if 'code=~"5.."' in query else "total"
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector",
                                                                        "result": [{"metric": {}, "value": [1.0, self.values[kind]]}]}})


def test_requests_to_an_uninstrumented_service_are_read_from_traefik(running):
    core, dep = running
    core.store.add_service(_byo_row())  # reuses the running orders process as its instance, but has no metrics_path of its own
    dep_id = core.store.add_deployment("byo", "abc", "initial", "img", "initial", status="healthy")
    core.store.update_deployment(dep_id, url=dep["url"], instance=dep["instance"])
    prom = FakePrometheus()
    core.settings = replace(core.settings, prometheus_api="http://prometheus.test/prometheus")
    monitor = Monitor(core, edge_every=0.0)
    monitor._prom = httpx.Client(transport=httpx.MockTransport(prom))
    monitor._sample(core.store.get_service("byo"), core.store.get_deployment(dep_id))  # first look sets the baseline
    prom.values.update(total="17", errors="3", p95="0.4")
    sample = monitor._sample(core.store.get_service("byo"), core.store.get_deployment(dep_id))
    stats = sample["routes"]["all requests"]
    assert stats["count"] == 7 and stats["errors"] == 1 and stats["p95_ms"] == pytest.approx(400)
    assert any('service="svc-byo@docker"' in q for q in prom.queries)


def test_a_service_with_its_own_telemetry_is_not_looked_up_in_prometheus(running):
    core, _ = running
    core.settings = replace(core.settings, prometheus_api="http://prometheus.test/prometheus")
    prom = FakePrometheus()
    monitor = Monitor(core, edge_every=0.0)
    monitor._prom = httpx.Client(transport=httpx.MockTransport(prom))
    monitor.tick()
    assert prom.queries == []
