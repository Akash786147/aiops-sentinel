# Sentinel Platform — design

Status: approved in conversation 2026-10-09 (approach A). Target: one Ubuntu server, 4+ GB RAM, 2+ vCPU.

## Purpose

Turn AIOps Sentinel from a benchmark demonstration into a running service. Sentinel **runs** the services it
monitors (as containers it builds itself), watches them continuously, and when a change goes live through a
**Restart** (a code change in the service's working copy, then Restart) and the service crashes, is OOM-killed,
eats resources or regresses, Sentinel **investigates** automatically with the existing pipeline (evidence packet,
hybrid trace, LLM re-rank, confirming test) and **proposes** a fix. The only automatic action is a rollback to the
service's last good version when it is crash-looping, OOM-killed, unhealthy or out of memory. A **Test lab** page
injects sample faults into a monitored service to show the whole loop.

Decisions taken with the user: full observability stack; no Git push path for now (each service has a Restart
button); auto-rollback only to last good; three sample services plus bring-your-own repo.

Non-goals (now): Git push webhooks / CI-triggered deploys, Kubernetes, multi-host, user accounts, automatic
application of generated fixes.

## Architecture

```text
                     Traefik :80  ── /            → sentinel (UI + API)
                                   ── /grafana     → grafana
                                   ── /prometheus  → prometheus
                                   ── /svc/<name>  → monitored service containers
 ┌──────────── docker network "sentinel" ─────────────────────────────────────────────────┐
 │ sentinel (FastAPI, Docker SDK, SQLite) ──docker.sock──► builds/runs svc-<name> containers │
 │   monitor (1 s scrape of /sentinel/metrics + docker stats) → detector → incidents        │
 │   investigator (sentinel.* pipeline) → proposed patch → human Approve → new deployment   │
 │ prometheus ◄─ docker_sd (label sentinel.monitor=true), cadvisor, node-exporter, sentinel  │
 │ alertmanager ── webhook ──► sentinel /api/alerts                                         │
 │ promtail ── docker logs ──► loki ◄── sentinel (tracebacks) ◄── grafana                   │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
 host: /srv/sentinel/{services/<name> (git working copies), sentinel.db, builds/}
 systemd: sentinel-stack.service → docker compose up
```

| Tool | Role |
| --- | --- |
| Docker Engine + Compose | runtime for everything; Sentinel drives the Docker API through the Python SDK |
| Traefik | single entry point and path routing (Docker label provider) |
| Prometheus | metrics store; Docker service discovery of monitored containers; alert rules |
| Alertmanager | routes alerts to Sentinel's webhook |
| cAdvisor, node-exporter | container and host CPU, memory, restarts, OOM |
| Loki + Promtail | container logs; Sentinel pulls tracebacks for an incident window |
| Grafana | provisioned datasources and a "Sentinel services" dashboard |
| SQLite | Sentinel's registry, deployments, incidents, audit |
| GitHub Actions, hadolint, Trivy | CI: lint, tests, Dockerfile lint, image build and vulnerability scan, compose validation |
| systemd, Makefile, install.sh | one-command install and start on Ubuntu |

## Components (new package `controlplane/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | settings from env: `SENTINEL_HOME`, `SENTINEL_RUNTIME` (`docker`/`process`), network, limits, timings |
| `store.py` | SQLite schema and data access: services, deployments, incidents, audit events |
| `runtime/base.py` | `Runtime` protocol and value types (`Instance`, `InstanceStatus`, `Stats`) |
| `runtime/docker_rt.py` | Docker implementation: build image `sentinel/<svc>:<sha12>`, run `svc-<name>` with labels, CPU/memory limits, health check, restart policy; status (running, exit code, OOM, restart count, health), stats, logs |
| `runtime/process_rt.py` | Process implementation for development and tests: "build" = snapshot of the working copy, "run" = uvicorn subprocess on a free port; memory limit enforced by the runtime (kill + `oom_killed`) |
| `workspace.py` | per-service git working copy: init from a sample or clone a URL; changed files; commit working tree as a deployment; diff; reset to a commit; tag `deploy-prev`/`deploy-current` |
| `deployer.py` | Restart = commit → build → run new instance → health gate → swap → record deployment; Rollback to last good (or any healthy deployment); Stop/Start; marks last good after a deployment stays healthy for the stability window |
| `monitor.py` | every second per running service: scrape `/sentinel/metrics` (JSON interval drain) + runtime stats → sample in the same shape `sentinel.detection` uses; per-service ring buffer; publishes telemetry events |
| `traffic.py` | background load against running services (reuses `benchmark.load` request mixes), toggled from the UI |
| `detector.py` | lifecycle rules (crash, OOM, crash loop, unhealthy), resource guard (memory ≥ 95 % of limit for 30 s, CPU ≥ 90 % of limit for 30 s), regression (robust z of the new deployment vs the previous one, reusing `sentinel.detection.detect`) ; Alertmanager alerts; one open incident per service |
| `policy.py` | auto-rollback decision: crash loop, OOM kill, unhealthy ≥ 45 s, memory exhaustion → roll back to last good if it exists and differs; everything else → investigate and propose |
| `investigator.py` | builds the evidence packet (tags last-good/current, exceptions from logs, samples) and runs the existing tracer, LLM re-rank, template/LLM confirming test (known-good = last-good commit), and a proposed patch (LLM diff validated with `git apply --check`, else a deterministic revert of the culprit hunks) |
| `faults.py` | Test-lab recipes: the 12 benchmark faults for the sample services plus generic ones (crash on start, OOM leak, CPU spin, error burst); apply to the working copy, preview diff, reset |
| `events.py` | in-process event bus (reuses `panel.bus.EventBus`) |
| `app.py` | FastAPI app: REST, SSE, alert webhook, static UI; background loops started on startup |
| `__main__.py` | `python -m controlplane` |

Sample services move to `samples/<name>/` as self-contained repos (package dir, vendored `common/telemetry.py`,
`Dockerfile`, `requirements.txt`). Their telemetry middleware additionally exposes Prometheus metrics
(`prometheus_client`) at `/metrics` and logs exceptions as JSON lines to stdout. The JSON interval drain moves to
`/sentinel/metrics`.

## Data model (SQLite)

* `services(name PK, source, kind sample|git, package, module, port, health_path, metrics_path, mem_limit_mb,
  cpu_limit, owner, auto_rollback, created_at)`
* `deployments(id PK, service, commit, message, image, trigger restart|rollback|approve|initial, status
  building|starting|healthy|failed|rolled_back|superseded|stopped, last_good bool, created_at, healthy_at,
  ended_at, detail)`
* `incidents(id PK, service, deployment_id, kind crash|oom|crash_loop|unhealthy|memory|cpu|regression|alert,
  status open|investigating|diagnosed|rolled_back|resolved|dismissed, opened_at, closed_at, summary,
  signals json, diagnosis json, patch text, auto_action)`
* `audit(id PK, at, actor, service, incident_id, action, detail json)`

## Key flows

**Restart (deploy).** Commit the working copy (if dirty) with a message → build → start the new instance next to
the old one → health gate (HTTP 200 on the health path within 30 s; process must not exit) → stop the old one →
deployment `healthy`; if the gate fails, the deployment is `failed`, the old instance keeps serving, and an incident
`crash`/`unhealthy` opens (no rollback needed because the old one never stopped). A deployment that stays healthy
for the stability window (120 s, no incident) becomes `last_good`.

**Detection.** Every 5 s: lifecycle (exit, OOM flag, restart count, health), resource guard, Alertmanager alerts
(webhook), and 60 s after a deployment went healthy a regression check against the previous deployment's
samples. One open incident per service; later signals attach to it.

**Auto-rollback.** On crash loop, OOM kill, unhealthy ≥ 45 s, or memory exhaustion of a deployment that is not the
last good one: deploy the last-good image (no rebuild), mark the bad deployment `rolled_back`, audit
`auto_rollback`, keep the incident open for investigation. Never more than one automatic rollback per incident.

**Investigation.** For every incident: tag `deploy-prev` = last-good commit, `deploy-current` = incident
deployment commit; packet = signals + exceptions from logs + samples + git diff; hybrid rank (+ LLM if a key is
set); template (and LLM) confirming test run against the incident commit (must fail) and the last-good commit (must
pass); proposed patch. Result stored on the incident. **Approve** applies the patch to the working copy, commits it
as "Sentinel fix for INC-…", and runs the Restart flow.

**Test lab.** Pick a service and a recipe → preview diff → Apply (writes to the working copy) → Restart → watch.
Reset restores the working copy to the last-good commit.

## UI

Same design system as the console (dark, hand-built SVG). Pages: Overview (server, service tiles, open
incidents, traffic toggle, links to Grafana/Prometheus/Alertmanager), Service (live charts with deploy markers,
logs, deployments with last-good, code editor, settings, Restart/Rollback/Stop/Start), Incidents (list; detail with
timeline, evidence, ranked suspects, code, confirming tests, proposed patch, Approve/Dismiss), Test lab, Audit,
Benchmark (existing results), Add service.

## Errors and edge cases

| Situation | Behaviour |
| --- | --- |
| Build fails | deployment `failed` with the build log; old instance keeps serving; incident `crash` with the log tail as evidence |
| No last-good deployment yet | no auto-rollback; incident investigates and proposes |
| Rollback target also fails health | stop trying; incident marked `needs attention`; audit |
| No LLM key | deterministic tracer, template test, revert patch |
| Docker socket missing | `SENTINEL_RUNTIME=docker` fails at startup with a clear message |
| BYO repo without `/sentinel/metrics` | resource and lifecycle monitoring only; regression and tracing limited; UI says so |
| Patch does not apply | proposal shown as "manual"; Approve disabled |
| Two actions on one service at once | per-service lock; second request gets 409 |

## Security

Sentinel holds the Docker socket (it must, to run services): bound to the internal network only; Traefik exposes
only the UI paths; optional basic-auth middleware via `.env`. Generated tests run in Sentinel's sandbox (no
network for the test process is not guaranteed in process mode; documented). API keys only in `.env`.

## Testing

Unit and integration tests run with `ProcessRuntime` on any OS: deploy and health gate; last-good promotion;
crash-on-start fault → failed deployment and incident; OOM fault → runtime kill → auto-rollback; latency fault →
regression incident → investigation finds the injected function, confirming test, proposed patch, Approve
redeploys; alert webhook; API and SSE; fault recipes apply/reset. `DockerRuntime` is tested with a fake Docker
client (labels, limits, health, OOM mapping). Compose and config files are validated structurally in tests and with
`docker compose config` on the server.
