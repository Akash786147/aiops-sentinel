import random

from sentinel.detection import detect, detect_threshold


def _samples(values_before, values_after, kind="latency", service="orders", route="GET /orders", start=1000.0):
    """One scrape per second; the change happens between the two lists."""
    samples = []
    t = start
    for phase in (values_before, values_after):
        for value in phase:
            stats = {"count": 10, "errors": 0, "p50_ms": 5.0, "p95_ms": 8.0, "max_ms": 9.0}
            sample = {"t": t, "service": service, "up": True, "routes": {route: stats}, "cpu_percent": 10.0, "rss_mb": 50.0}
            if kind == "latency":
                stats["p95_ms"] = value
            elif kind == "errors":
                stats["errors"] = int(value)
            elif kind == "memory":
                sample["rss_mb"] = value
            samples.append(sample)
            t += 1.0
    return samples, start + len(values_before)


def test_sustained_latency_shift_is_an_incident_for_the_right_service():
    rng = random.Random(1)
    samples, change = _samples([8 + rng.random() for _ in range(15)], [120 + rng.random() for _ in range(15)])
    incidents = detect(samples, change, ["orders"])
    assert incidents and incidents[0].service == "orders"
    assert incidents[0].symptoms == ["latency"]
    assert incidents[0].routes == ["GET /orders"]


def test_noise_and_single_glitch_are_not_incidents():
    rng = random.Random(2)
    after = [8 + rng.random() for _ in range(15)]
    after[7] = 400  # one-bucket glitch
    samples, change = _samples([8 + rng.random() for _ in range(15)], after)
    assert detect(samples, change, ["orders"]) == []


def test_bursty_baseline_does_not_alarm_when_burst_rate_is_unchanged():
    pattern = [5, 5, 5, 60, 5, 5, 5, 5, 60, 5, 5, 5, 5, 60, 5]
    samples, change = _samples(pattern, list(reversed(pattern)))
    assert detect(samples, change, ["orders"]) == []


def test_slow_memory_growth_is_detected_but_not_by_a_fixed_threshold():
    samples, change = _samples([50.0] * 15, [50.0 + 3 * i for i in range(15)], kind="memory")
    incidents = detect(samples, change, ["orders"])
    assert incidents and incidents[0].symptoms == ["memory"]
    assert detect_threshold(samples, change, ["orders"]) == []  # 92 MiB never crosses 500 MiB


def test_errors_on_a_route_are_detected():
    samples, change = _samples([0] * 15, [3] * 15, kind="errors")
    assert detect(samples, change, ["orders"])[0].symptoms == ["errors"]


def test_missing_data_means_cannot_conclude():
    samples, change = _samples([8.0] * 2, [200.0] * 15)  # baseline too short
    assert detect(samples, change, ["orders"]) == []
