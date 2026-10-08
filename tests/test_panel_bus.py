import threading

from panel.bus import EventBus


def test_events_are_numbered_and_run_start_marks_a_boundary():
    bus = EventBus()
    bus.emit("run", {"state": "started", "id": "a"})
    bus.emit("telemetry", {"x": 1})
    bus.emit("run", {"state": "done"})
    bus.emit("run", {"state": "started", "id": "b"})
    bus.emit("telemetry", {"x": 2})
    events, nxt = bus.current_run()
    assert [e["n"] for e in events] == [3, 4]
    assert events[0]["data"]["id"] == "b"
    assert nxt == 5


def test_wait_returns_new_events_and_times_out_empty():
    bus = EventBus()
    assert bus.wait(0, timeout=0.05) == []
    timer = threading.Timer(0.05, lambda: bus.emit("service", {"name": "orders"}))
    timer.start()
    got = bus.wait(0, timeout=2.0)
    timer.join()
    assert got and got[0]["kind"] == "service"
    assert bus.wait(1, timeout=0.05) == []


def test_empty_bus_has_empty_current_run():
    assert EventBus().current_run() == ([], 0)
