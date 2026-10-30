"""campus-api: a replay of the Unisphere campus application, driven by a recorded traffic profile."""
import importlib
import random
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from controlplane import replay
from controlplane.config import Settings
from controlplane.core import Core
from controlplane.deployer import Deployer
from controlplane.monitor import Monitor
from controlplane.registry import catalogue, register_sample
from controlplane.traffic import Traffic

ROOT = Path(__file__).resolve().parents[1]
CAMPUS = ROOT / "samples" / "campus-api"


@pytest.fixture()
def campus(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.syspath_prepend(str(CAMPUS))
    for mod in [m for m in sys.modules if m.split(".")[0] in ("campus", "common")]:
        del sys.modules[mod]
    behaviour = importlib.import_module("campus.behaviour")
    app = importlib.import_module("campus.app").app
    yield behaviour, app
    for mod in [m for m in sys.modules if m.split(".")[0] in ("campus", "common")]:
        del sys.modules[mod]


def test_sampled_latency_and_status_follow_the_recorded_profile(campus):
    behaviour, _ = campus
    rng = random.Random(7)
    key = "GET /api/v2/gatepass/all"
    spec = behaviour.endpoints()[key]
    xs = sorted(behaviour.latency_ms(key, rng) for _ in range(20000))
    assert xs[10000] == pytest.approx(spec["latency_ms"]["p50"], abs=1.5)
    assert xs[19000] == pytest.approx(spec["latency_ms"]["p95"], rel=0.25)
    codes = Counter(behaviour.status(key, rng) for _ in range(20000))
    assert codes[200] / 20000 == pytest.approx(float(spec["status"]["200"]), abs=0.02)


def test_service_exposes_the_real_endpoints_and_standard_telemetry(campus):
    behaviour, app = campus
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok", "service": "campus-api"}
    assert client.get("/api/v2/menu").status_code in (200, 401)
    routes = client.get("/sentinel/metrics").json()["routes"]
    assert "GET /api/v2/menu" in routes
    assert any(e["journey"] == "gatepass" for e in behaviour.profile()["endpoints"])


def test_profile_holds_nothing_personal():
    text = (CAMPUS / "campus" / "profile.json").read_text(encoding="utf-8")
    assert "@" not in text and "eyJ" not in text and "Bearer" not in text


def test_request_mix_and_daily_load_come_from_the_profile():
    profile = replay.load(CAMPUS, "campus")
    make = replay.request_maker(profile)
    rng = random.Random(3)
    seen = Counter()
    for _ in range(4000):
        method, path, _body = make(rng)
        assert "{" not in path and method in ("GET", "POST", "PUT", "DELETE")
        seen[(method, path.split("/")[3] if path.count("/") > 3 else path)] += 1
    top = max(profile["endpoints"], key=lambda e: e["share"])
    assert seen[(top["method"], top["path"].split("/")[3])] > 400  # the most-called family dominates, as in the real log
    day = 240.0
    factors = [replay.load_factor(profile, t, day) for t in range(0, 240, 10)]
    assert sum(factors) / len(factors) == pytest.approx(1.0, abs=0.15)
    assert replay.load_factor(profile, day * 7 / 24 + 1, day) > 2 * replay.load_factor(profile, day * 22 / 24 + 1, day)
    assert replay.load(ROOT / "samples" / "orders", "orders") is None


def test_the_synthetic_lab_is_hidden_and_the_campus_environment_is_offered():
    shown = catalogue(ROOT / "samples")
    assert "campus-api" in shown and not {"orders", "inventory", "payments"} & set(shown)


def test_replay_traffic_is_driven_from_the_profile(tmp_path):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", health_timeout_s=20)
    core = Core.create(settings)
    try:
        register_sample(core, "campus-api")
        dep = Deployer(core).deploy("campus-api", trigger="initial", actor="test")
        traffic = Traffic(core, workers=2, think_s=0.01)
        traffic.start()
        try:
            deadline = time.time() + 15
            while traffic.sent < 40 and time.time() < deadline:
                time.sleep(0.2)
        finally:
            traffic.stop()
        assert traffic.sent >= 40
        routes = httpx.get(dep["url"] + "/sentinel/metrics").json()["routes"]
        assert len(routes) >= 3 and Monitor(core).tick()["campus-api"]["up"] is True
    finally:
        core.runtime.shutdown()
