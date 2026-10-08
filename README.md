# AIOps Sentinel

AIOps Sentinel monitors a **shared server**. When a tenant service gets into trouble it does not
scale it blindly: it attributes the incident to one service and owner, builds an evidence packet
(telemetry, exceptions, the deployment diff), uses **semantic code search and an LLM** to trace the
symptom to the responsible **function**, and **generates a test that confirms it** (fails on the
deployed code, passes on the known-good code). Every decision is written to an audit trail and a
human approves any change.

Start here: **[docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md)** (what, why, how, tools, evaluation,
results, limitations, team responsibilities). Slides: `docs/AIOps_Sentinel_Review.pptx`.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo OPENAI_API_KEY=sk-... > .env                    # or GROQ_API_KEY=gsk-... (optional: LLM steps)

python -m benchmark.demo F01                         # live: shared server -> incident -> diagnosis -> test
pytest -q && ruff check app services tests scripts sentinel benchmark evaluation panel controlplane samples
```

## Sentinel Console (live panel)

```bash
python -m panel                 # http://127.0.0.1:8080  (Replay is the default; Live starts the real services)
python -m panel --speed 30      # faster replay, handy for screenshots
```

```bash
python -m evaluation.benchmark record  --seeds 0 1 2   # ~50 s live traffic per scenario, 45 runs
python -m evaluation.benchmark analyze --seeds 0 1 2   # pipeline + baselines (+ LLM if a key is set)
python -m evaluation.benchmark analyze-model --seeds 0 1 2 --provider groq --model openai/gpt-oss-120b --label gptoss
python -m evaluation.benchmark score                   # evaluation/results/summary.json
```

## Sentinel platform (runs the services it monitors)

The platform is a long-running service. You pick services to monitor (the three samples, or any git repo with a
Dockerfile), it **builds and runs them itself**, watches them, and reacts when something goes wrong. Restart a service from
the UI after a code change and the new version is built and health-checked before it replaces the old one; if it crashes,
runs out of memory, crash-loops or fails its health check, Sentinel rolls back to the last good version, then investigates
and proposes a fix for a human to approve. The **Test lab** page injects sample faults into a monitored service to show this.

```bash
# on an Ubuntu server (22.04/24.04, 2+ vCPU, 4+ GB RAM)
git clone <repo> && cd aiops-sentinel
sudo bash deploy/install.sh            # Docker + compose plugin, starts the stack, enables start on boot
# open http://<server-ip>/             (Grafana at /grafana/, Prometheus at /prometheus/)

# on a laptop, no Docker: processes instead of containers
SENTINEL_BOOTSTRAP=orders,inventory,payments python -m controlplane --port 8800
```

Stack: Traefik (single entry point), Prometheus + Alertmanager, cAdvisor, node-exporter, Loki + Promtail, Grafana, and the
control plane (FastAPI + SQLite). Full steps, day-to-day commands and troubleshooting: **[docs/RUNBOOK.md](docs/RUNBOOK.md)**.
Design: [spec](docs/superpowers/specs/2026-10-09-sentinel-platform-design.md).

## Repository map

| Path | What it is |
| --- | --- |
| `sentinel/` | The pipeline, one module per step: `telemetry`, `detection`, `context`, `indexing`, `tracing`, `testgen`, `audit`, `pipeline`, `llm`, `registry` |
| `shared_server/` | System under observation: orders, inventory, payments + shared telemetry middleware + `services.yaml` |
| `controlplane/` | Sentinel platform: runtime (Docker/process), deployer, monitor, detector, policy, investigator, fault lab, REST + SSE API, UI |
| `samples/` | Deployable versions of orders, inventory, payments (Dockerfile, `/health`, `/metrics`) |
| `deploy/` | Ubuntu stack: Compose, Prometheus/Alertmanager/Loki/Promtail/Grafana configs, install script, systemd unit |
| `panel/` | Sentinel Console: FastAPI + vanilla-JS web panel (live floor, incident, trace, proof, decision, results) |
| `benchmark/` | 12 faults + 3 controls with ground truth, git deployment builder, load generator, live recorder, demo |
| `evaluation/` | `benchmark.py` harness, results (`results/summary.json`, per-run JSON, audit logs) |
| `tests/` | Unit tests for detection, indexing, tracing, test guard (+ v0 tests) |
| `docs/` | Project guide, workflow, slides (+ superseded v0 documents) |
| `app/`, `services/`, `microservices/`, `web/` | v0 prototype; `services/retrieval.py` is kept as the "v0" retrieval baseline |

## Safety boundary

Sentinel reads telemetry, logs and code; it never edits code, restarts or scales services. Generated
tests pass a static guard and run in a throw-away copy with API keys stripped. Steps 7–10 (fix PR,
CI/CD rollout, post-deploy watch) are designed but intentionally not automated.
