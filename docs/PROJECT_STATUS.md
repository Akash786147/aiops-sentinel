# AIOps Sentinel: status, what is left, and future scope

Last updated 2026-10-09. Read with [PROJECT_GUIDE.md](PROJECT_GUIDE.md) (method and results) and
[RUNBOOK.md](RUNBOOK.md) (operating the platform).

## 1. Where the project stands, in one paragraph

Sentinel exists in two layers. The **research pipeline** (`sentinel/`, `benchmark/`, `evaluation/`) answers the research
question: can telemetry-grounded hybrid code retrieval plus an LLM trace a runtime incident on a shared server to the
responsible function, and confirm it with a generated test, better than the naive alternatives? It is built and
evaluated on 45 recorded runs. The **platform** (`controlplane/`, `samples/`, `deploy/`) is the delivery vehicle: a
long-running service that builds and runs the services it monitors, watches them, rolls back to the last good version when
one crashes or runs out of memory, and then runs the pipeline to investigate and propose a fix for a human to approve. The
platform is built and tested, and its Docker stack has been brought up on a real Ubuntu 24.04 server. Its end-to-end demo on
that server, and its timing measurements, are the main things still to do.

## 2. The ten-step flow: status

| # | Step | Research pipeline | Platform | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Monitor | Built (per-route and per-process telemetry) | Built (1 s scrape, `docker stats`, Prometheus, cAdvisor, Loki) | tests; server: Prometheus scraping 3 services |
| 2 | Detect and attribute | Built + evaluated (92% recall) | Built (crash, OOM, crash loop, unhealthy, memory/CPU guards, regression vs the previous deployment, Alertmanager) | 45 runs; 9 detector tests |
| 3 | Evidence packet | Built | Reused on the bad commit (git worktree, tracebacks from logs) | tests |
| 4 | Code index | Built | Reused | tests |
| 5 | Trace to code | Built + evaluated (85% Top-1) | Reused, with optional LLM re-rank | 45 runs; local end-to-end run |
| 6 | Confirming test | Built + evaluated (94% / 91%) | Reused (start-up test or LLM test, run with `confirm()`) | 45 runs; local end-to-end run |
| 7 | Fix proposal | Designed | **Built**: LLM diff checked with `git apply --check`, else revert of the suspect files; human **Approve** applies it | 4 investigator tests; local run |
| 8 | Deploy / CI-CD | CI only | **Built** (build, start, health gate, swap; failed gate keeps the old version serving). Not built: PR creation, webhook-triggered deploys | 9 deployer tests; server: 3 services deployed |
| 9 | Audit | Built | Built (SQLite `audit` table, live feed, Audit page) | tests |
| 10 | Guardrails | Built for steps 1–6 | Built: auto-action limited to rollback to last good, once per incident, only for crash loop / OOM / unhealthy / memory | policy and detector tests |

## 3. Done

**Research pipeline**
- Per-tenant telemetry, change-aware robust detector, evidence packet, AST code index (BM25 + bge-small), seven-feature
  hybrid tracer, LLM re-rank with validation, template and LLM test generators with an AST guard and a sandbox, audit trail.
- Benchmark of 12 faults + 3 controls × 3 seeds (45 recorded runs), 9 baselines and ablations, a held-out split, and a
  written failure analysis ([PROJECT_GUIDE.md](PROJECT_GUIDE.md) sections 7–9).
- Confidence intervals for the headline rates ([REVIEW_RESPONSE.md](REVIEW_RESPONSE.md) section 2).

**Platform**
- Control plane: FastAPI + SQLite, runtime abstraction (Docker for the server, plain processes for a laptop), deployer with
  health gate and rollback, monitor, detector, auto-rollback policy, investigator, fault lab, REST + SSE API.
- Sentinel Console (web UI): overview, per-service live/deployments/code/logs/settings, incidents with diagnosis and patch,
  Test lab, audit, add-service, benchmark results (with hover definitions of every metric).
- Three deployable sample services (orders, inventory, payments), a bring-your-own-repo path (public git URL, port and health path; no generated traffic; request counts, errors and p95 read from Traefik so curl requests are visible without instrumentation), and a fault catalogue (F01–F12
  plus crash-on-start, memory leak, CPU spin).
- Ops stack on one Ubuntu server: Traefik, Prometheus, Alertmanager, cAdvisor, node-exporter, Loki + Promtail, Grafana
  (provisioned datasources and dashboard), systemd unit, Makefile, install script. CI: ruff, pytest, hadolint, compose
  validation, image builds, Trivy.
- 111 tests pass, 1 skipped (a live test that needs `PANEL_LIVE_TEST=1`). ruff is clean.

**Verified on a real server (Ubuntu 24.04, 7.7 GB RAM, nginx already on port 80)**
- Docker installed, stack built and started, nine containers healthy, Traefik on port 8080.
- Sentinel built and started orders, inventory and payments itself; Prometheus scraped all three through Docker discovery;
  the whole stack used about 470 MiB.
- Two bugs that only a real server shows were found and fixed (see section 6).

### Added after the second review (real data and industry relevance)

Full study guide: [ENVIRONMENTS.md](ENVIRONMENTS.md).

- **campus-api**: a replay service built from an anonymised profile of a real 126,794-request campus log; driven with the real daily load curve; injected changes
  (`slow_gatepass`, `gatepass_error`) are labelled as injected. Verified locally end to end: change detected, changed file ranked first, template test
  fails on the bad version and passes on the last good one, revert patch proposed, SLO breach shown.
- **Industry policy packs** (campus, ecommerce, travel, cloud, fintech): executable, versioned, audited; they gate the automatic rollback and the Approve button; a
  Policy tab shows live SLO status per business journey.
- **Independent evaluation**, rules fixed before scoring, no tuning: RCAEval RE1 (375 real cases, faulty service ranked first 89%, 95% interval 85–92%,
  against 82% for the operator's latency view) and the Microsoft Cloud Monitoring Dataset (60 labelled series; F1 about 0.3 for every method, lowest
  false-alarm rate for Sentinel).
- **Data-readiness check** for any company's data, and a documented shadow-mode pilot protocol.
- Light console theme, metric definitions on hover, Results page section for independent data.
- Tests: 156 pass, 1 skipped; ruff clean.

## 4. Left to do

Ordered by value for the final evaluation.

| # | Item | Why it matters | Effort |
| --- | --- | --- | --- |
| 0 | Run the campus-api loop and both external evaluations on the new server, record the numbers and screenshots | Everything in the new environments was verified locally; the Docker build of campus-api and the server-side evaluation runs have not been seen on a server | 1 h |
| 1 | Run the two demo scenarios on the server (inventory + `oom_leak`; orders + `F01`) and record the result | The platform's headline claim has so far only been exercised on a laptop with the process runtime | 30 min |
| 2 | Measure platform timings: time to detect, time to roll back, time to diagnosis, per fault, repeated 5 times; add the table to the guide | The review asked for more quantitative and performance results; today the platform has none | 2 h |
| 3 | Commit and push the doc, UI and compose fixes (Alertmanager flag, Traefik v3.6.1) | They exist only in the working tree | 5 min |
| 4 | Try a bring-your-own repo from GitHub on the server (a small public repo with a Dockerfile) and send curl requests | The path is tested with a local git repo and a fake Prometheus; the Docker build and the Traefik metrics are untested on a real server | 30 min |
| 5 | Update the slide deck with the platform, the status and the review response | The deck still describes the pipeline only | 2 h |
| 6 | Put authentication in front of the console, or restrict it to a VPN or SSH tunnel | The console can restart services and holds the Docker socket | 1–3 h |
| 7 | Rotate the Groq and OpenAI keys that were pasted in chat | They were exposed | 10 min |
| 8 | Alert on Sentinel itself being down (Prometheus rule on the `sentinel` job) | Nothing watches the watcher yet; Compose restarts it, but no one is told | 30 min |

Known limitations of the platform today:
- Single host, single replica per service; a swap briefly runs two instances of the same service.
- One automatic action only (rollback to last good). Latency and error regressions are proposed, never applied.
- Python services only for code tracing; any language can be deployed and monitored for crashes and resources.
- The Docker socket gives Sentinel root-equivalent control of the host.
- The fault lab edits source files by string patching, so a recipe may report "not applicable" after the code changes.
- Regression detection needs about 60 s of traffic after a restart; a service with no traffic cannot regress.

## 5. Future scope

Grouped by the question each item answers. The research items come first on purpose: the platform is a means to measure
the research question in a more realistic setting, not the contribution itself.

### A. Research (strengthens the answer to the research question)

1. **External validity.** *Partly done:* RCAEval RE1 (service level) and the Microsoft series (detection) are evaluated; still to do are RCAEval RE2/RE3 (multi-source, code-level faults) and BugsInPy for the test generator. Run the tracer on public data it was not designed for: RCAEval (RE3 has code-level faults with
   stack traces and microservice telemetry), BugsInPy (real Python bugs with fail-then-pass tests, which maps directly onto
   our "confirming test" definition), and AIOpsLab for the incident-lifecycle tasks. Report accuracy next to the synthetic
   benchmark.
2. **Learn the weights.** Replace the hand-set seven weights with a learning-to-rank model (logistic regression or
   gradient-boosted trees) trained on seeds 0 and evaluated on held-out seeds and on the public data. Compare against the
   hand-set weights; this is the cleanest test of whether the structure features generalise.
3. **Latent bugs and traffic-induced faults.** Today every fault is change-induced. Add faults that were always present and
   only surface under new load, where no commit is to blame, and report how the tracer degrades.
4. **More models, a proper comparison.** Add one local open-weight model and one code-specialised embedding model; report
   cost, latency and accuracy with confidence intervals. Keep this as an ablation of the re-ranker, not the main result.
5. **Statistics.** More seeds (10 per scenario) and paired significance tests; today n = 33 gives intervals about 25 points
   wide.
6. **Detector threshold study.** Sweep z and the minimum-change floors and publish the recall / false-alarm curve instead of
   a single operating point (F09 shows what the floors miss).
7. **Safety evaluation of auto-rollback.** Inject faults where rollback is wrong (a bad deploy of a stateful change, a
   rollback that breaks a dependency) and measure how often the policy acts when it should not.

### B. DevOps and production

1. **Git push and CI-triggered deploys.** A GitHub webhook that triggers build and deploy, a GitHub Actions job that
   calls Sentinel's API, and a draft pull request for an approved patch (steps 7–8 of the original flow).
2. **Progressive delivery.** Canary or weighted traffic split through Traefik, with the detector as the automatic gate,
   instead of "swap after the health check".
3. **Observability depth.** OpenTelemetry traces and exemplars; SLO and error-budget alerts (burn rate) in Prometheus
   instead of fixed rules; Grafana dashboards per service generated from the registry.
4. **Sentinel's own reliability.** External watchdog (a Prometheus rule plus a second small checker), SQLite backups
   on a schedule (`make backup` exists, a timer does not), and a documented restore.
5. **Security.** SSO or at least basic auth in Traefik, TLS (Let's Encrypt through Traefik), a socket proxy that exposes only
   the Docker API calls Sentinel needs, rootless builds, secrets from a vault instead of `.env`, image signing.
6. **Infrastructure as code.** Ansible or Terraform for the server, so the install is reproducible beyond one script.
7. **Scale-out.** Kubernetes runtime behind the same `Runtime` interface (the abstraction already exists), Argo Rollouts for
   progressive delivery, multi-node scheduling.
8. **Multi-language tracing.** tree-sitter chunking for Java, Go and JavaScript so the tracer is not Python-only.

### C. Product

1. Per-team access and ownership (owners already exist in the registry), notifications to Slack or email, an incident
   timeline export, and a post-incident report generated from the audit trail.
2. Cost view: LLM tokens and latency per incident, container CPU-hours per service.
3. A learning loop: keep the approved and rejected patches as labelled data for the ranker and the test generator.

## 6. What testing found, and what changed

The review asked for the failures we hit and what improved. This is the log, in the order we met them. The detailed
benchmark failures are in [PROJECT_GUIDE.md](PROJECT_GUIDE.md) section 9.

| Found | How | Fix | Test |
| --- | --- | --- | --- |
| Bursty routes such as `/pay` would alarm on a plain z-score | Detector design | Persistence (≥ 3 buckets) and an exceedance-rate test against the baseline's own threshold crossings | detection tests; 2 of 6 quiet runs still false-alarm (reported) |
| A faulty deployment was promoted to "last good" before the regression check fired (stability window 20 s < regression window 30 s) | Local end-to-end run | The stability window is now at least `regression_after_s + 15` when regression guarding is on | parametrised deployer test (written after the fix; noted in the plan) |
| Crash-loop test flaked: exit code read as `None` right after exit | Full-suite run | Read `poll()` directly in `ProcessRuntime.status` | repeated suite runs |
| Investigator wrote a log file containing one newline, which crashed the exception parser | Local end-to-end run | Write one JSON object per line, no padding | investigator test |
| After an auto-rollback, the proposed patch "does not apply" (the fix is already live) | UI review | UI says so and offers "Close: keep the rollback" | manual |
| Alertmanager restart-looped on the server | First real server start | It requires an `http(s)://` external URL; removed the flag and kept the route prefix | config test |
| Traefik returned 404 for every route on the server | First real server start | Docker 29 requires API version ≥ 1.44; Traefik 3.1 speaks 1.24. Upgraded to v3.6.1 | config test pins the image |
| `gpt-5.4-mini` returned an empty answer on 3 of 33 test-generation runs | Benchmark | Not re-run (rule: report every run); documented as a model limitation | evaluation tables |
| Third model (qwen3.8-27b) did not run reliably on Groq | Benchmark | Dropped from the comparison and removed from the result files | n/a |

Logs we keep: one JSON line per pipeline stage per run in `evaluation/results/audit/`; every recorded run in
`evaluation/results/runs/`; on the platform, the `audit`, `incidents` and `deployments` tables in
`/srv/sentinel/sentinel.db`, container logs in Loki, metrics in Prometheus (7 days), and the Audit page.
