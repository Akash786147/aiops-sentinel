"""The Ubuntu deployment: every config parses and is wired together (validated again on the server with docker compose config)."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def load(rel):
    return yaml.safe_load((DEPLOY / rel).read_text(encoding="utf-8"))


def test_compose_has_the_whole_stack_on_one_network():
    compose = load("docker-compose.yml")
    services = compose["services"]
    assert {"traefik", "sentinel", "prometheus", "alertmanager", "cadvisor", "node-exporter", "loki", "promtail", "grafana"} <= set(services)
    assert compose["networks"]["sentinel"]["name"] == "sentinel"
    assert all("sentinel" in s.get("networks", []) for s in services.values())
    published = [name for name, s in services.items() if s.get("ports")]
    assert published == ["traefik"]  # one entry point; everything else stays internal
    for name, svc in services.items():
        image = svc.get("image", "")
        assert name == "sentinel" or (":" in image and not image.endswith(":latest")), f"{name} must pin an image version"


def test_sentinel_controls_docker_and_keeps_state_on_the_host():
    sentinel = load("docker-compose.yml")["services"]["sentinel"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in sentinel["volumes"]
    assert "/srv/sentinel:/srv/sentinel" in sentinel["volumes"]
    env = sentinel["environment"]
    assert env["SENTINEL_RUNTIME"] == "docker" and env["SENTINEL_NETWORK"] == "sentinel"
    assert sentinel["healthcheck"] and any("PathPrefix(`/`)" in label for label in sentinel["labels"])
    dockerfile = (DEPLOY / "sentinel.Dockerfile").read_text(encoding="utf-8")
    assert "git" in dockerfile and "python\", \"-m\", \"controlplane\"" in dockerfile and "HEALTHCHECK" in dockerfile


def test_prometheus_discovers_monitored_containers_and_loads_rules():
    prom = load("prometheus/prometheus.yml")
    jobs = {j["job_name"]: j for j in prom["scrape_configs"]}
    assert {"services", "sentinel", "cadvisor", "node", "prometheus"} <= set(jobs)
    sd = jobs["services"]["docker_sd_configs"][0]
    assert sd["filters"] == [{"name": "label", "values": ["sentinel.monitor=true"]}]
    targets = {r.get("target_label") for r in jobs["services"]["relabel_configs"]}
    assert {"service", "__address__", "__metrics_path__"} <= targets
    rules = load("prometheus/alerts.yml")["groups"][0]["rules"]
    assert {r["alert"] for r in rules} >= {"ServiceDown", "HighErrorRate", "HighLatencyP95", "ContainerMemoryNearLimit"}
    am = load("alertmanager/alertmanager.yml")
    assert am["receivers"][0]["webhook_configs"][0]["url"] == "http://sentinel:8000/api/alerts"


def test_logs_and_dashboards_are_provisioned():
    assert load("loki/loki.yml")["schema_config"]["configs"][0]["store"] == "tsdb"
    promtail = load("promtail/promtail.yml")
    assert promtail["clients"][0]["url"].startswith("http://loki:3100")
    datasources = {d["type"] for d in load("grafana/provisioning/datasources/datasources.yml")["datasources"]}
    assert datasources == {"prometheus", "loki"}
    board = json.loads((DEPLOY / "grafana" / "dashboards" / "sentinel.json").read_text(encoding="utf-8"))
    titles = " ".join(p["title"].lower() for p in board["panels"])
    for word in ("p95", "requests", "5xx", "cpu", "memory", "incidents", "logs"):
        assert word in titles


def test_install_script_and_systemd_unit():
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert install.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in install
    assert "docker-compose-plugin" in install and "compose -f deploy/docker-compose.yml config" in install
    unit = (DEPLOY / "sentinel-stack.service").read_text(encoding="utf-8")
    assert "Requires=docker.service" in unit and "WantedBy=multi-user.target" in unit
    assert "up" in (ROOT / "Makefile").read_text(encoding="utf-8")
