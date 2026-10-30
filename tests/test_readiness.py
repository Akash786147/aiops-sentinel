"""Data-readiness check: what can Sentinel do with this data, and why not the rest."""
import json

from evaluation import readiness

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiJzZWNyZXQifQ.c2lnbmF0dXJl"


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_request_log_supports_detection_and_slos_but_not_code_stages(tmp_path):
    rows = [{"logId": i, "endpoint": "/api/v2/gatepass?x=1", "requestType": "GET", "responseCode": "200" if i % 9 else "500",
             "responseTime": "5.0", "timestamp": f"2026-02-27 08:{i % 60:02d}:00.000", "userId": "u1", "errorMessage": None,
             "requestPayload": json.dumps({"accessToken": TOKEN})} for i in range(300)]
    report = readiness.inspect(write(tmp_path, "log.json", json.dumps(rows)))
    assert report["format"] == "json" and report["rows"] == 300
    assert {"timestamp", "route", "status", "latency", "user", "error"} <= set(report["fields"])
    stages = {s["stage"]: s for s in report["stages"]}
    assert stages["detection"]["status"] == "yes" and stages["slo_policy"]["status"] == "yes"
    assert stages["change_correlation"]["status"] == "needs input" and "deployment" in stages["change_correlation"]["reason"]
    assert stages["function_tracing"]["status"] == "needs input" and "source repository" in stages["function_tracing"]["reason"]
    assert any("token" in w.lower() for w in report["privacy_warnings"])
    assert TOKEN not in json.dumps(report)


def test_a_deployment_column_unlocks_change_correlation(tmp_path):
    lines = ["timestamp,service,route,status,latency_ms,version"] + [f"2026-03-01 10:{i % 60:02d}:00,orders,/orders,200,12,v{1 + i // 150}" for i in range(300)]
    report = readiness.inspect(write(tmp_path, "t.csv", "\n".join(lines)))
    stages = {s["stage"]: s for s in report["stages"]}
    assert "deployment" in report["fields"] and stages["change_correlation"]["status"] == "yes"


def test_a_bare_metric_series_supports_detection_only(tmp_path):
    lines = ["TimeStamp,Value,Label"] + [f"2018-07-03 {i % 24:02d}:00:00,{i % 7},0" for i in range(120)]
    report = readiness.inspect(write(tmp_path, "m.csv", "\n".join(lines)))
    stages = {s["stage"]: s for s in report["stages"]}
    assert stages["detection"]["status"] == "yes" and stages["service_attribution"]["status"] == "no"
    assert stages["function_tracing"]["status"] == "no" and "label" in report["fields"]
    assert report["resolution_seconds"] == 3600


def test_unreadable_input_is_reported_not_raised(tmp_path):
    report = readiness.inspect(write(tmp_path, "x.bin", "\x00\x01 not data"))
    assert report["format"] == "unknown" and report["stages"][0]["status"] == "no"
