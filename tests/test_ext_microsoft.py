"""Microsoft Cloud Monitoring Dataset: event-level scoring of detectors on labelled production series (no tuning on labels)."""
import math
import random

import pytest

from evaluation.external import microsoft as ms


def series(values, labels=None, name="s", domain="d", step=3600):
    return ms.Series(name, domain, step, list(values), list(labels or [0] * len(values)))


def noisy(n, seed=0, base=100.0, sd=2.0):
    rng = random.Random(seed)
    return [base + rng.gauss(0, sd) for _ in range(n)]


def test_segments_are_contiguous_runs_of_labels():
    assert ms.segments([0, 1, 1, 0, 0, 1, 0, 1, 1, 1]) == [(1, 2), (5, 5), (7, 9)]
    assert ms.segments([0, 0, 0]) == []


def test_a_sustained_shift_is_alerted_inside_the_labelled_segment_and_quiet_data_is_not():
    values = noisy(400)
    for i in range(300, 320):
        values[i] += 60
    labels = [1 if 300 <= i < 320 else 0 for i in range(400)]
    shifted = ms.evaluate(series(values, labels), "robust_persistence")
    assert shifted.detected == [True] and shifted.false_alarms == 0 and 0 <= shifted.delays[0] <= 4
    quiet = ms.evaluate(series(noisy(400, seed=1)), "robust_persistence")
    assert quiet.alerts == 0 and quiet.segments == 0


def test_a_single_point_spike_is_ignored_by_persistence_but_caught_by_a_static_rule():
    values = noisy(400)
    values[350] += 80
    labels = [1 if i == 350 else 0 for i in range(400)]
    assert ms.evaluate(series(values, labels), "robust_persistence").detected == [False]
    assert ms.evaluate(series(values, labels), "static_threshold").detected == [True]


def test_alerts_away_from_labelled_anomalies_are_false_alarms():
    values = noisy(400)
    for i in range(250, 262):
        values[i] += 60  # an unlabelled level shift
    result = ms.evaluate(series(values), "robust_persistence")
    assert result.alerts >= 1 and result.false_alarms == result.alerts


def test_aggregate_metrics():
    a = ms.Result(points=1000, segments=2, detected=[True, False], delays=[2], alerts=3, false_alarms=1, anomaly_free=False)
    b = ms.Result(points=1000, segments=0, detected=[], delays=[], alerts=1, false_alarms=1, anomaly_free=True)
    m = ms.aggregate([a, b])
    assert m["precision"] == pytest.approx(2 / 4) and m["recall"] == pytest.approx(1 / 2)
    assert m["f1"] == pytest.approx(0.5) and m["median_delay_points"] == 2
    assert m["false_alarms_per_1000_points_anomaly_free"] == pytest.approx(1.0) and math.isfinite(m["f1"])


def test_load_series_reads_the_dataset_layout(tmp_path):
    folder = tmp_path / "domain-a"
    folder.mkdir()
    (folder / "x-01.csv").write_text("TimeStamp,Value,Label\n2018-07-03 14:00:00,1,0\n2018-07-03 15:00:00,2,1\n2018-07-03 16:00:00,1,0\n", encoding="utf-8")
    loaded = ms.load_series(tmp_path)
    assert [(s.domain, s.name, s.step, s.values, s.labels) for s in loaded] == [("domain-a", "x-01", 3600, [1.0, 2.0, 1.0], [0, 1, 0])]


def test_missing_values_carry_the_last_observation_forward(tmp_path):
    folder = tmp_path / "domain-a"
    folder.mkdir()
    (folder / "gaps.csv").write_text("TimeStamp,Value,Label\n2018-07-03 14:00:00,,0\n2018-07-03 15:00:00,5,0\n2018-07-03 16:00:00,,0\n2018-07-03 17:00:00,7,1\n", encoding="utf-8")
    assert ms.load_series(tmp_path)[0].values == [5.0, 5.0, 5.0, 7.0]
