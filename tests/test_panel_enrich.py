import json
from pathlib import Path

import pytest

from panel import enrich


@pytest.fixture(scope="module")
def recording(panel_root):
    return json.loads(panel_root.recording("F01", 0).read_text(encoding="utf-8"))


def test_incident_view_names_the_broken_tenant_and_route(recording):
    incident = enrich.incident_view(recording)
    assert incident["service"] == "orders"
    assert incident["symptoms"] == ["latency"]
    assert "GET /orders" in incident["routes"]
    assert incident["signals"][0]["z"] > 6


def test_baseline_band_is_the_pre_change_level(recording):
    band = enrich.baseline_band(recording, enrich.incident_view(recording))
    assert band["kind"] == "latency" and band["route"] == "GET /orders" and band["unit"] == "ms"
    assert 7 < band["median"] < 10
    assert band["bar"] > band["median"] + 14


def test_deployment_lists_commits_and_changed_ranges(recording):
    info = enrich.deployment(Path(recording["workspace"]))
    assert len(info["commits"]) == 4
    assert any(r["file"] == "orders/repository.py" and r["behavioural"] for r in info["ranges"])


def test_call_path_reaches_the_helper_from_the_route_handler(recording):
    graph = enrich.call_path(Path(recording["workspace"]), ["GET /orders"])
    symbols = {n["symbol"]: n["depth"] for n in graph["nodes"]}
    assert symbols["list_orders"] == 0 and symbols["fetch_orders_with_profiles"] == 1
    assert all({"from", "to"} == set(e) for e in graph["edges"])


@pytest.mark.parametrize("bad", ["../services.yaml", "/etc/passwd", "orders/../../x.py", "C:/Windows/win.ini"])
def test_read_source_refuses_paths_outside_the_workspace(recording, bad):
    with pytest.raises((ValueError, FileNotFoundError)):
        enrich.read_source(Path(recording["workspace"]), bad)


def test_read_source_reads_a_workspace_file(recording):
    assert "def list_orders" in enrich.read_source(Path(recording["workspace"]), "orders/app.py")


def test_build_result_for_a_run_with_no_incident_is_still_valid(recording):
    flat = dict(recording, samples=[dict(s, routes={r: dict(v, p95_ms=8.0) for r, v in s["routes"].items()}) for s in recording["samples"]])
    payload = enrich.build_result(flat, {"action": "none", "confidence": 0.0, "suspects": [], "tests": {}})
    assert payload["incident"] is None and payload["band"] is None and payload["call_path"] is None
    assert payload["action"] == "none" and payload["truth"]["file"] == "orders/repository.py"


def test_build_result_with_an_incident_carries_everything_the_views_need(recording):
    analysis = {"action": "code_fix", "confidence": 0.9, "packet_digest": "d1",
                "suspects": [{"chunk_id": "orders/repository.py:41-44"}],
                "llm": {"model": "m", "root_cause": "why", "secret_extra": 1},
                "tests": {"template": {"code": "x", "guard": [], "confirming": True,
                                       "faulty": {"outcome": "assertion_failed", "detail": "d" * 500, "exit_code": 1},
                                       "fixed": {"outcome": "passed", "detail": "", "exit_code": 0}}}}
    payload = enrich.build_result(recording, analysis)
    assert payload["incident"]["service"] == "orders" and payload["band"]["median"] > 0
    assert payload["code_available"] and len(payload["commits"]) == 4 and payload["ranges"]
    assert "secret_extra" not in payload["llm"] and payload["llm"]["root_cause"] == "why"
    assert len(payload["tests"]["template"]["faulty"]["detail"]) <= 300
    assert "exit_code" not in payload["tests"]["template"]["faulty"]
