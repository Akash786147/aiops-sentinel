"""DockerRuntime against a fake Docker SDK client: labels, limits, policies and state mapping."""
from pathlib import Path

import docker
import pytest

from controlplane.runtime.base import ServiceSpec
from controlplane.runtime.docker_rt import DockerRuntime

SPEC = ServiceSpec(name="orders", module="orders.app:app", port=8000, health_path="/health", metrics_path="/sentinel/metrics",
                   mem_limit_mb=256, cpu_limit=0.5)


class FakeContainer:
    def __init__(self, cid, name, attrs):
        self.id, self.name, self.attrs = cid, name, attrs
        self.stopped = self.removed = False

    def reload(self):
        pass

    def stop(self, timeout=10):
        self.stopped = True

    def remove(self, v=False, force=False):
        self.removed = True

    def logs(self, tail=200, timestamps=False):
        return b"INFO: Uvicorn running\nTraceback: boom\n"

    def stats(self, stream=False):
        return {"cpu_stats": {"cpu_usage": {"total_usage": 3_000_000}, "system_cpu_usage": 20_000_000, "online_cpus": 2},
                "precpu_stats": {"cpu_usage": {"total_usage": 1_000_000}, "system_cpu_usage": 10_000_000},
                "memory_stats": {"usage": 120 * 2**20, "stats": {"inactive_file": 20 * 2**20}, "limit": 256 * 2**20}}


class FakeContainers:
    def __init__(self):
        self.kwargs = None
        self.items = {}

    def run(self, image, **kwargs):
        self.kwargs = {"image": image, **kwargs}
        attrs = {"State": {"Status": "running", "Running": True, "ExitCode": 0, "OOMKilled": False, "Health": {"Status": "starting"}},
                 "RestartCount": 0}
        container = FakeContainer("c1", kwargs["name"], attrs)
        self.items["c1"] = container
        return container

    def get(self, cid):
        if cid not in self.items:
            raise docker.errors.NotFound("gone")
        return self.items[cid]


class FakeImages:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise docker.errors.BuildError("failed", [{"stream": "Step 3/9"}, {"error": "SyntaxError in pricing.py"}])
        return object(), [{"stream": "Step 1/9 : FROM python:3.12-slim\n"}, {"stream": "Successfully built\n"}]

    def remove(self, image, force=False):
        self.removed = image


class FakeClient:
    def __init__(self, fail=False):
        self.images, self.containers = FakeImages(fail), FakeContainers()


def test_build_tags_image_and_returns_log(tmp_path):
    client = FakeClient()
    result = DockerRuntime(network="sentinel", client=client).build(SPEC, Path(tmp_path), "abc123def456")
    assert result.ok and result.image == "sentinel/orders:abc123def456" and "Successfully built" in result.log
    assert client.images.calls[0]["tag"] == "sentinel/orders:abc123def456" and client.images.calls[0]["labels"]["sentinel.service"] == "orders"


def test_build_failure_reports_the_error():
    result = DockerRuntime(client=FakeClient(fail=True)).build(SPEC, Path("."), "t")
    assert result.ok is False and "SyntaxError in pricing.py" in result.log


def test_run_sets_labels_limits_network_and_restart_policy():
    client = FakeClient()
    inst = DockerRuntime(network="sentinel", client=client).run(SPEC, "sentinel/orders:abc123def456")
    kw = client.containers.kwargs
    assert kw["network"] == "sentinel" and kw["detach"] is True
    assert kw["mem_limit"] == "256m" and kw["memswap_limit"] == "256m" and kw["nano_cpus"] == 500_000_000
    assert kw["restart_policy"] == {"Name": "on-failure", "MaximumRetryCount": 3}
    labels = kw["labels"]
    assert labels["sentinel.monitor"] == "true" and labels["sentinel.service"] == "orders" and labels["sentinel.metrics_port"] == "8000"
    assert labels["traefik.enable"] == "true" and labels["traefik.http.routers.svc-orders.rule"] == "PathPrefix(`/svc/orders`)"
    assert labels["traefik.http.middlewares.svc-orders-strip.stripprefix.prefixes"] == "/svc/orders"
    assert inst.url == f"http://{kw['name']}:8000" and kw["name"].startswith("svc-orders-")


def test_status_maps_oom_exit_restarts_and_health():
    client = FakeClient()
    rt = DockerRuntime(client=client)
    inst = rt.run(SPEC, "sentinel/orders:t")
    client.containers.items["c1"].attrs = {"State": {"Status": "exited", "Running": False, "ExitCode": 137, "OOMKilled": True,
                                                     "Health": {"Status": "unhealthy"}}, "RestartCount": 3}
    status = rt.status(inst.id)
    assert (status.running, status.exit_code, status.oom_killed, status.restarts) == (False, 137, True, 3)
    assert rt.status("missing").running is False


def test_stats_logs_and_stop():
    client = FakeClient()
    rt = DockerRuntime(client=client)
    inst = rt.run(SPEC, "sentinel/orders:t")
    stats = rt.stats(inst.id)
    assert stats.cpu_percent == pytest.approx(40.0) and stats.mem_mb == pytest.approx(100.0) and stats.mem_limit_mb == pytest.approx(256.0)
    assert rt.logs(inst.id, 10)[-1] == "Traceback: boom"
    rt.stop(inst.id)
    assert client.containers.items["c1"].stopped and client.containers.items["c1"].removed
