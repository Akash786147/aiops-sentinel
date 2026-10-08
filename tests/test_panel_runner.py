import json
import socket
import subprocess
import threading
import time

import pytest

from panel import replay as replay_mod
from panel.bus import EventBus
from panel.replay import build_timeline
from panel.runner import Busy, NotReady, Runner, Unavailable


def wait_done(bus, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        events, _ = bus.current_run()
        if any(e["kind"] == "run" and e["data"].get("state") in ("done", "failed") for e in events):
            return events
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_replay_emits_the_whole_story_in_order(panel_root):
    bus = EventBus()
    Runner(bus, panel_root, speed=100000).start("F01", "replay")
    events = wait_done(bus)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run" and events[0]["data"]["state"] == "started"
    assert kinds[-1] == "run" and events[-1]["data"]["state"] == "done"
    assert kinds.index("deploy") < kinds.index("result")
    stages = [e["data"]["stage"] for e in events if e["kind"] == "stage"]
    assert stages[:3] == ["detect", "context", "trace"] and stages[-1] == "handoff"
    assert kinds.count("result") == 1 and kinds.index("result") > max(i for i, k in enumerate(kinds) if k == "stage")
    result = next(e for e in events if e["kind"] == "result")["data"]
    assert result["incident"]["service"] == "orders" and result["truth"]["file"] == "orders/repository.py"
    assert {e["data"]["name"] for e in events if e["kind"] == "service"} == {"orders", "inventory", "payments"}


def test_timeline_is_ordered_and_compressed(panel_root):
    rec = json.loads(panel_root.recording("F01", 0).read_text(encoding="utf-8"))
    audit = [json.loads(line) for line in panel_root.audit("F01", 0).read_text(encoding="utf-8").splitlines()]
    items, end_due = build_timeline(rec, audit, 3.0, {"orders": "team-commerce"})
    dues = [d for d, _, _ in items]
    assert dues == sorted(dues)
    assert items[-1][1] == "stage" and end_due == pytest.approx(dues[-1])
    assert end_due < 60 / 3 + 20  # 50 s of samples at 3x plus capped analysis gaps


def test_second_run_while_active_is_refused(panel_root, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(replay_mod, "run_replay", lambda ctx, *a: gate.wait(5))
    runner = Runner(EventBus(), panel_root)
    runner.start("F01", "replay")
    with pytest.raises(Busy):
        runner.start("F01", "replay")
    gate.set()


def test_unknown_scenario_and_missing_recording(panel_root):
    runner = Runner(EventBus(), panel_root)
    with pytest.raises(KeyError):
        runner.start("F99", "replay")
    assert runner.replay_available("F01", 0) is True
    assert runner.replay_available("F02", 0) is False
    with pytest.raises(Unavailable):
        runner.start("F02", "replay")


def test_live_is_refused_when_a_tenant_port_is_busy(panel_root):
    holder = socket.socket()
    try:
        holder.bind(("127.0.0.1", 9101))
    except OSError:
        pytest.skip("port 9101 already in use on this machine")
    holder.listen()
    try:
        with pytest.raises(Unavailable, match="9101"):
            Runner(EventBus(), panel_root).start("F01", "live")
    finally:
        holder.close()


def test_failure_inside_a_run_is_reported_not_raised(panel_root, monkeypatch):
    def boom(ctx, *a):
        raise RuntimeError("service exploded")

    monkeypatch.setattr(replay_mod, "run_replay", boom)
    bus = EventBus()
    Runner(bus, panel_root).start("F01", "replay")
    events = wait_done(bus)
    assert events[-1]["data"]["state"] == "failed" and "service exploded" in events[-1]["data"]["reason"]


def test_approve_needs_a_result_then_writes_only_an_audit_event(panel_root):
    bus = EventBus()
    runner = Runner(bus, panel_root, speed=100000)
    with pytest.raises(NotReady):
        runner.approve("Akash", "too early")
    runner.start("F01", "replay")
    wait_done(bus)
    stage = runner.approve("Akash", "looks right")
    assert stage["decision"] == "approved" and stage["approver"] == "Akash" and stage["stage"] == "handoff"
    approvals_file = panel_root.panel_data / f"{runner.current['id']}-approvals.jsonl"
    approvals = [json.loads(line) for line in approvals_file.read_text(encoding="utf-8").splitlines()]
    assert approvals[-1]["approver"] == "Akash"
    workspace = runner.workspace()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True, check=True)
    assert status.stdout == ""
    assert runner.workspace("some-other-run") is None
