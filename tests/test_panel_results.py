from panel.paths import Paths
from panel.results import failures, load_results


def test_unavailable_without_results(tmp_path):
    assert load_results(Paths(tmp_path)) == {"available": False}


def test_grid_and_summary_from_fixture(panel_root):
    out = load_results(panel_root)
    assert out["available"] and out["runs"] == 1
    row = next(r for r in out["grid"] if r["scenario"] == "F01")
    assert row["detected"] == [True]
    assert row["cells"]["hybrid"] == [1] and row["cells"]["bm25"] == [5]
    assert out["summary"]["runs"] == 1
    assert out["failures"] == []


def _run(scenario, seed, *, fault=True, detected=True, rank=1, action="code_fix", expected="code_fix", tests=None):
    robust = [{"service": "orders" if fault else "payments"}] if detected else []
    return {"scenario": scenario, "seed": seed, "truth": {"file": "x.py" if fault else None, "service": "orders" if fault else None},
            "detection": {"robust": robust}, "action": action, "expected_action": expected,
            "localization": {"hybrid": {"rank": rank}}, "tests": tests or {}}


def test_failures_list_the_real_problems():
    runs = [
        _run("F09", 0, detected=False),
        _run("F07", 0, rank=4),
        _run("F06", 1, tests={"llm": {"confirming": False, "guard": ["no test generated"]}}),
        _run("H01", 2, fault=False, action="investigate", expected="none"),
        _run("H03", 2, fault=False, detected=False, action="none", expected="capacity_scale"),
        _run("F01", 0),
    ]
    kinds = [(f["kind"], f["scenario"]) for f in failures(runs)]
    assert ("undetected", "F09") in kinds
    assert ("mis-ranked", "F07") in kinds
    assert ("test", "F06") in kinds
    assert ("false alarm", "H01") in kinds
    assert ("wrong action", "H03") in kinds
    assert not [k for k in kinds if k[1] == "F01"]
