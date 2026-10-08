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
