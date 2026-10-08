# Sentinel Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Steps use checkbox syntax.

**Goal:** Sentinel runs, monitors, investigates and (only to last good) rolls back real services on one Ubuntu server, with a full Docker Compose observability stack and a Test lab.

**Architecture:** New `controlplane/` package (FastAPI + SQLite + runtime abstraction) reusing `sentinel/` (detection, context, indexing, tracing, testgen, llm, audit) and `panel/bus.py`; sample services become self-contained repos in `samples/`; `deploy/` holds the Compose stack and configs for Traefik, Prometheus, Alertmanager, cAdvisor, node-exporter, Loki, Promtail and Grafana.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, sqlite3, docker SDK 7.x, prometheus_client, psutil, httpx; vanilla JS UI (console design system); Docker Compose v2 on Ubuntu.

**Spec:** `docs/superpowers/specs/2026-10-09-sentinel-platform-design.md`

**Rulings recorded up front:**
- No commits (user instruction from the previous task, kept).
- This plan states each task's files, interfaces and the exact behaviours its tests must pin (test names + assertions), not full implementation listings: the platform is several thousand lines and the user asked to build without stopping, so code is written once, test-first, in the repository. Cost if wrong: less upfront review of implementation detail; mitigated by TDD per task and a whole-branch self-review.
- Docker is not available on the build machine: `ProcessRuntime` carries the integration tests; Docker parts are tested with a fake client and validated on the server by the user (`docker compose config`, runbook).

## Global Constraints

- `python -m controlplane` serves the UI/API on `:8000` (inside Docker, behind Traefik on `:80`).
- `SENTINEL_RUNTIME=docker` on the server, `process` for development/tests; same behaviour contract.
- Only automatic action: rollback to last good on crash loop, OOM, unhealthy ≥ 45 s, memory ≥ 95 % of limit for 30 s. Never apply a generated fix without Approve.
- Per-service lock: concurrent actions on one service → 409.
- Reuse existing modules; do not change behaviour of `sentinel/`, `benchmark/`, `panel/`.
- Every action writes an audit row (actor, service, incident, action, detail).

## Review Focus

1. A deployment that never becomes healthy must leave the previous instance serving (no outage) → Task 5 test.
2. Auto-rollback must not loop (rollback target fails too) → Task 7 test.
3. Incident dedupe: repeated crash events while an incident is open must not create new incidents → Task 7 test.
4. Proposed patch that does not apply must not be approvable → Task 8 test.
5. Path traversal in the code editor endpoint (`../`) → Task 10 test.

---

### Task 1: Sample service repos with Prometheus metrics
**Files:** `samples/{orders,inventory,payments}/` (package, `common/telemetry.py`, `Dockerfile`, `requirements.txt`, `.dockerignore`); `tests/test_samples.py`.
**Interfaces:** each sample serves its routes, `GET /health` → `{"status":"ok"}`, `GET /metrics` (Prometheus text: `http_requests_total{route,method,status}`, `http_request_duration_seconds_bucket{route,method}`), `GET /sentinel/metrics` (existing JSON drain incl. exemplars), exceptions logged as one JSON line to stdout and to `$SENTINEL_LOG_DIR/<svc>.jsonl`.
- [ ] Tests: `test_sample_serves_health_metrics_and_drain` (TestClient per sample: health 200; `/metrics` contains `http_requests_total`; drain has routes after a request); `test_exception_is_logged_as_json` (route raising → 500 and a JSON log line with `exception`, `frames`); `test_dockerfile_runs_uvicorn_on_8000` (Dockerfile text has `EXPOSE 8000`, `HEALTHCHECK`, non-root `USER`).
- [ ] Implement, run `pytest tests/test_samples.py`.

### Task 2: Store and config
**Files:** `controlplane/{__init__,config,store}.py`; `tests/test_cp_store.py`.
**Interfaces:** `Settings.from_env()`; `Store(path)` with `add_service`, `get_service`, `list_services`, `update_service`, `add_deployment`, `update_deployment`, `deployments(service)`, `current_deployment(service)`, `last_good(service)`, `set_last_good(id)`, `open_incident(...)`, `get_incident`, `update_incident`, `incidents(service=None)`, `open_incident_for(service)`, `audit(actor, action, service=None, incident_id=None, **detail)`, `audit_events(limit, service)`.
- [ ] Tests: round trips; `set_last_good` clears the previous flag for that service only; `open_incident_for` returns only status in {open, investigating, diagnosed, rolled_back}; audit ordering newest first.

### Task 3: Runtime abstraction and ProcessRuntime
**Files:** `controlplane/runtime/{__init__,base,process_rt}.py`; `tests/test_cp_runtime_process.py`.
**Interfaces:** `Runtime.build(service, workdir, tag) -> BuildResult(ok, image, log)`, `run(service, image) -> Instance(id, url, image)`, `stop(instance_id)`, `status(instance_id) -> InstanceStatus(running, exit_code, oom_killed, restarts, health)`, `stats(instance_id) -> Stats(cpu_percent, mem_mb, mem_limit_mb)`, `logs(instance_id, tail) -> list[str]`, `remove_image(image)`.
- [ ] Tests (real subprocesses, sample `orders`): build snapshot + run → `/health` 200 via `instance.url`; stop → status not running; a workdir whose app raises at import → instance exits, `status.exit_code != 0`; memory guard: with `mem_limit_mb` tiny the runtime kills it and reports `oom_killed=True`; logs contain uvicorn output.

### Task 4: DockerRuntime (fake client)
**Files:** `controlplane/runtime/docker_rt.py`; `tests/test_cp_runtime_docker.py`.
- [ ] Tests with a fake `docker` client object: build tag `sentinel/<svc>:<tag>`; run sets name `svc-<svc>-<tag>`, network, labels (`sentinel.monitor=true`, `sentinel.service`, `sentinel.metrics_port`, Traefik router/service/stripprefix labels), `mem_limit`, `nano_cpus`, restart policy `on-failure` max 3, healthcheck; status maps `State.OOMKilled`, `ExitCode`, `RestartCount`, `Health.Status`; stats converts Docker stats JSON to cpu % and MiB.

### Task 5: Workspace and deployer
**Files:** `controlplane/{workspace,deployer,locks}.py`; `tests/test_cp_deployer.py`.
**Interfaces:** `Workspace(root).init_from(sample_dir|url)`, `.dirty()`, `.changed_files()`, `.commit(message) -> sha`, `.head()`, `.diff(a, b)`, `.reset_to(sha)`, `.tag(name, sha)`, `.read(path)`, `.write(path, text)`, `.files()`; `Deployer(store, runtime, settings, bus).deploy(service, trigger, message) -> deployment`, `.rollback(service, to=None, actor)`, `.stop(service)`, `.start(service)`, `.promote_stable()` (last-good after stability window).
- [ ] Tests: initial deploy healthy and current; restart with a code change creates a new commit + deployment and stops the old instance; **health-gate failure leaves the previous instance serving and marks the new deployment failed**; `promote_stable` marks last good only after the window; rollback deploys the last-good image without rebuild and marks the bad deployment `rolled_back`; concurrent action → `Busy`.

### Task 6: Monitor and traffic
**Files:** `controlplane/{monitor,traffic}.py`; `tests/test_cp_monitor.py`.
- [ ] Tests: monitor turns `/sentinel/metrics` + runtime stats into samples with `service, t, up, routes, cpu_percent, rss_mb`; ring buffer bounded; down instance → `up False`; traffic start/stop sends requests to running services (counter increases).

### Task 7: Detector, policy, incidents
**Files:** `controlplane/{detector,policy}.py`; `tests/test_cp_detector.py`.
- [ ] Tests: exit → `crash`; OOM flag → `oom`; ≥ 3 restarts/120 s → `crash_loop`; memory ≥ 95 % for 30 s → `memory`; regression of a new deployment vs previous (latency jump) → `regression` with signals; **dedupe: second crash while open attaches**; policy rolls back crash_loop/oom/unhealthy/memory when last good exists and differs, never twice per incident, **and gives up (needs attention) when the rollback target fails**; regression → no rollback; alert webhook payload → `alert` incident or attach.

### Task 8: Investigator and proposed patch
**Files:** `controlplane/investigator.py`; `tests/test_cp_investigator.py`.
- [ ] Tests (process runtime, sample `orders`, F01 recipe deployed after a healthy deployment): investigation ranks `fetch_orders_with_profiles` first, template test confirming (fails on incident commit, passes on last-good), proposed revert patch applies (`git apply --check`); **a non-applying patch is marked not approvable**; approve applies, commits "Sentinel fix for INC-…", deploys, and the incident becomes `resolved` once healthy.

### Task 9: Fault recipes (Test lab)
**Files:** `controlplane/faults.py`; `tests/test_cp_faults.py`.
- [ ] Tests: catalog per service includes benchmark faults for that sample (by target file) and generic `crash_on_start`, `oom_leak`, `cpu_spin`, `error_burst`; `preview` returns a unified diff; `apply` makes the workspace dirty with exactly that change; `reset` returns to last-good commit; recipes for files that do not exist are not offered.

### Task 10: API, SSE, app wiring, CLI
**Files:** `controlplane/{app,events,__main__}.py`; `tests/test_cp_api.py`.
- [ ] Tests: `GET /api/services` (status, current/last-good deployment, limits); `POST /api/services/{s}/restart|rollback|stop|start`; `GET /api/services/{s}/files`, `GET/PUT /api/services/{s}/file?path=` (**`../` → 400**); `GET /api/services/{s}/samples`; `GET /api/incidents`, `GET /api/incidents/{id}`, `POST /api/incidents/{id}/approve|dismiss`; `GET /api/lab/{s}`, `POST /api/lab/{s}/apply|reset`; `POST /api/alerts` (Alertmanager payload); `GET /api/audit`; `POST /api/traffic` on/off; `GET /api/events` SSE; `POST /api/services` add (sample or git URL); 409 on concurrent action.

### Task 11: UI
**Files:** `controlplane/static/{index.html,app.css,js/*.js,js/views/*.js}` (reusing console components).
- [ ] Views: overview, service (live/logs/deployments/code/settings), incidents list + detail (timeline, evidence, suspects, code, tests, patch, approve), lab, audit, results, add service. Verify with headless Edge screenshots against a process-runtime instance (`?nostream`).

### Task 12: Ops stack
**Files:** `deploy/docker-compose.yml`, `deploy/sentinel.Dockerfile`, `deploy/prometheus/{prometheus.yml,alerts.yml}`, `deploy/alertmanager/alertmanager.yml`, `deploy/loki/loki.yml`, `deploy/promtail/promtail.yml`, `deploy/grafana/provisioning/{datasources,dashboards}/*`, `deploy/grafana/dashboards/sentinel.json`, `deploy/traefik/traefik.yml`, `deploy/install.sh`, `deploy/sentinel-stack.service`, `Makefile`, `.env.example`, CI jobs; `tests/test_deploy_configs.py`.
- [ ] Tests: every YAML/JSON parses; compose has all services, the shared network, the docker socket mounts where needed, healthchecks, and ports only on Traefik; Prometheus scrape jobs and docker_sd filter; alert rule names; Grafana dashboard has panels for p95, rps, errors, CPU, memory, logs.

### Task 13: Docs and end-to-end verification
- [ ] README "Run on Ubuntu" + runbook (`docs/RUNBOOK.md`), PROJECT_GUIDE section, full suite, ruff, local end-to-end run with process runtime: restart with F01 → regression incident → diagnosis; `oom_leak` → auto-rollback; screenshots.

## Self-review
Spec coverage: components table → Tasks 2–10; flows → Tasks 5, 7, 8, 9; UI → 11; tools/ops → 12; errors table → Tasks 5, 7, 8, 10 tests; testing section → all. Placeholders: implementation listings intentionally omitted (ruling above); every task names its tests and assertions.
