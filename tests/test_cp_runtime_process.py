"""ProcessRuntime runs a sample service as a real subprocess with Docker-like semantics."""
import shutil
import time
from pathlib import Path

import httpx
import pytest

from controlplane.runtime.base import ServiceSpec
from controlplane.runtime.process_rt import ProcessRuntime

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "orders"


def spec(mem=256):
    return ServiceSpec(name="orders", module="orders.app:app", port=8000, health_path="/health",
                       metrics_path="/sentinel/metrics", mem_limit_mb=mem, cpu_limit=0.5)


def wait_for(predicate, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("condition not met in time")


@pytest.fixture()
def runtime(tmp_path):
    rt = ProcessRuntime(tmp_path / "home", check_interval=0.3)
    yield rt
    rt.shutdown()


@pytest.fixture()
def workdir(tmp_path):
    target = tmp_path / "work"
    shutil.copytree(SAMPLE, target)
    return target


def test_build_snapshot_then_run_serves_health(runtime, workdir):
    built = runtime.build(spec(), workdir, "abc123")
    assert built.ok and Path(built.image).exists()
    (workdir / "orders" / "app.py").write_text("raise SystemExit('changed after build')\n")  # snapshot is isolated
    inst = runtime.run(spec(), built.image)
    wait_for(lambda: runtime.status(inst.id).health == "healthy")
    assert httpx.get(inst.url + "/health").json()["status"] == "ok"
    stats = runtime.stats(inst.id)
    assert stats.mem_mb and stats.mem_mb > 5 and stats.mem_limit_mb == 256
    runtime.stop(inst.id)
    assert runtime.status(inst.id).running is False
    assert any("Uvicorn running" in line or "Application startup" in line for line in runtime.logs(inst.id, 50))


def test_build_fails_on_syntax_error(runtime, workdir):
    (workdir / "orders" / "pricing.py").write_text("def broken(:\n")
    built = runtime.build(spec(), workdir, "bad")
    assert built.ok is False and "pricing.py" in built.log


def test_crash_on_start_restarts_then_gives_up(runtime, workdir):
    (workdir / "orders" / "app.py").write_text("raise RuntimeError('missing PAYMENT_KEY')\n")
    inst = runtime.run(spec(), runtime.build(spec(), workdir, "crash").image)
    status = wait_for(lambda: (s := runtime.status(inst.id)) and not s.running and s.restarts >= 3 and s, timeout=40)
    assert status.exit_code not in (0, None) and status.oom_killed is False
    assert any("missing PAYMENT_KEY" in line for line in runtime.logs(inst.id, 200))


def test_memory_limit_kills_with_oom_flag(runtime, workdir):
    inst = runtime.run(spec(mem=15), runtime.build(spec(mem=15), workdir, "oom").image)
    status = wait_for(lambda: (s := runtime.status(inst.id)) and s.oom_killed and s, timeout=30)
    assert status.oom_killed is True
