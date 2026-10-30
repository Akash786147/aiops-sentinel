"""RCAEval RE1: service-level root-cause ranking from metrics around the injection time (no tuning on labels)."""
import random
import zipfile

import pytest

from evaluation.external import rcaeval as rca

INJECT = 1000


def case_csv(faulty="cartservice", fault="cpu", seed=0, n=600):
    """Three services with cpu/mem/latency. After the injection the faulty service's metric jumps and its caller's latency rises a little."""
    rng = random.Random(seed)
    cols = ["time"] + [f"{s}_{m}" for s in ("adservice", "cartservice", "frontend") for m in ("cpu", "mem", "latency")]
    rows = []
    for i in range(n):
        t = INJECT - 400 + i
        post = t >= INJECT
        row = [t]
        for s in ("adservice", "cartservice", "frontend"):
            for m in ("cpu", "mem", "latency"):
                v = 10 + rng.gauss(0, 1)
                if post and s == faulty and m == fault:
                    v += 40
                if post and s == "frontend" and m == "latency" and faulty == "cartservice":
                    v += 3
                row.append(f"{v:.4f}")
        rows.append(row)
    return "\n".join(",".join(map(str, r)) for r in [cols, *rows]) + "\n"


@pytest.fixture()
def archive(tmp_path):
    path = tmp_path / "RE1.zip"
    with zipfile.ZipFile(path, "w") as z:
        for system, faulty, fault in (("RE1-OB", "cartservice", "cpu"), ("RE1-OB", "adservice", "mem"), ("RE1-TT", "frontend", "latency")):
            for run in (1, 2):
                base = f"RE1/{system}/{faulty}_{fault}/{run}"
                csv_text = case_csv(faulty, fault, seed=run)
                if system == "RE1-TT":  # Sock Shop and Train Ticket ship the compact per-service layout as simple_data.csv
                    z.writestr(f"{base}/data.csv", "time,huge_container-cpu-system-seconds-total\n1,1\n")
                    z.writestr(f"{base}/simple_data.csv", csv_text)
                else:
                    z.writestr(f"{base}/data.csv", csv_text)
                z.writestr(f"{base}/inject_time.txt", str(INJECT))
    return path


def test_cases_are_read_from_the_archive_with_their_labels(archive):
    cases = list(rca.iter_cases(archive))
    assert len(cases) == 6 and {c.system for c in cases} == {"RE1-OB", "RE1-TT"}
    c = next(c for c in cases if c.root_service == "cartservice")
    assert (c.fault, c.inject_time, c.run) == ("cpu", INJECT, 1) and "cartservice" in c.services()
    assert c.services()["cartservice"]["cpu"][0] == pytest.approx(10, abs=5)


def test_robust_score_ranks_the_service_whose_metric_changed_first(archive):
    case = next(c for c in rca.iter_cases(archive) if c.root_service == "cartservice")
    ranking = rca.rank(case, "robust_change")
    assert ranking[0] == "cartservice" and set(ranking) == {"adservice", "cartservice", "frontend"}


def test_latency_ratio_baseline_follows_the_symptom_not_the_cause(archive):
    case = next(c for c in rca.iter_cases(archive) if c.root_service == "cartservice")
    assert rca.rank(case, "latency_ratio")[0] == "frontend"  # the caller's latency rose, the cause is elsewhere


def test_accuracy_metrics():
    ranks = [1, 2, 4, None]  # position of the true cause in each ranking, None when absent
    m = rca.accuracy(ranks)
    assert m["ac@1"] == pytest.approx(0.25) and m["ac@3"] == pytest.approx(0.5) and m["avg@5"] == pytest.approx((0.25 + 0.5 + 0.5 + 0.75 + 0.75) / 5)


def test_run_scores_every_method_per_system_and_fault(archive):
    report = rca.run(archive)
    assert report["cases"] == 6 and set(report["methods"]) == {"random", "latency_ratio", "robust_change"}
    robust = report["methods"]["robust_change"]
    assert robust["all"]["ac@1"] == pytest.approx(1.0) and set(robust["by_system"]) == {"RE1-OB", "RE1-TT"} and "cpu" in robust["by_fault"]
    assert report["methods"]["random"]["all"]["ac@1"] == pytest.approx(1 / 3, abs=0.01)


def test_rows_without_a_timestamp_are_skipped(tmp_path):
    path = tmp_path / "RE1.zip"
    text = case_csv().splitlines()
    text.insert(5, "," + ",".join(["1.0"] * 9))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("RE1/RE1-OB/cartservice_cpu/1/data.csv", "\n".join(text) + "\n")
        z.writestr("RE1/RE1-OB/cartservice_cpu/1/inject_time.txt", str(INJECT))
    case = next(rca.iter_cases(path))
    assert len(case.times) == 600 and all(len(v) == 600 for v in case.columns.values())
