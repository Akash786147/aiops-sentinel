# Industry environments: data-backed replay services

Status: direction agreed in conversation 2026-10-30. Builds on the platform spec (2026-10-09).

## Why

The previous review said the project is good but asked which industries would use it and whether it works on their data and
environment. Our evidence so far is synthetic faults in three services we wrote. This adds **environments backed by real data**
that Sentinel monitors exactly as it monitors any service, plus a **data-readiness check** that says what a given data source can
and cannot support.

## Principles

* **Label honestly.** Each environment states what is real (traffic shape, noise, labelled anomalies, failure cases) and what is
  injected (code changes, deployments, faults). No result is called "production" unless it is.
* **Do not invent deployment records.** Where a dataset has none, the evaluation uses only the stages the data supports.
* **No personal data in the repository.** Raw logs stay outside git; only aggregated profiles are committed.
* **The synthetic samples stay** as a controlled lab (they have code and ground truth), hidden from the default UI and bootstrap.

## Environments

| Environment | Real part | Injected part | Stages it supports |
| --- | --- | --- | --- |
| `campus-api` (Unisphere) | 126,794 requests over 8 days: endpoint mix, status mix, per-endpoint latency distribution, hour-of-day load | Code change "v2" in the stub's git history at a known time (slow or failing endpoint) | detect, attribute, change correlation, trace, confirming test, policy/SLO |
| `cloud-metrics` (Microsoft Cloud Monitoring Dataset, MIT) | 67 expert-labelled production series in 8 domains | none | detection only (precision, recall, delay, false alarms) |
| RCAEval (CC-BY 4.0; RE1 390 MB, RE2 4.2 GB, RE3 534 MB) | Failure cases on Online Boutique, Sock Shop and Train Ticket with labelled root-cause service | none | service-level root-cause ranking only |

## Industry profiles and policy packs

Each environment is an **industry profile**: a data source plus a **policy pack**, a versioned YAML file the decision engine
evaluates before any action is recommended or taken. Packs are demonstration policies, labelled as such; none claims to be a real
company's policy.

| Profile | Data | Policy emphasis | Honest label |
| --- | --- | --- | --- |
| Campus / enterprise operations | Unisphere logs (`campus-api`) | Business-journey SLOs (gate pass, shuttle, biometric), access control | Real traffic, your own app; changes injected |
| E-commerce / retail | RCAEval: Online Boutique, Sock Shop | Checkout availability and latency | Real telemetry from benchmark systems; faults injected by the dataset authors |
| Travel / ticketing | RCAEval: Train Ticket | Booking availability | Same |
| Cloud / SaaS | Microsoft Cloud Monitoring series | API latency, crash rate, database query rate | Real production-derived metrics |
| Fintech (optional) | our payments sample | Strict error budgets, mandatory approvals, redaction | Synthetic traffic; policy demonstration only |

A pack contains: SLIs and SLO targets per business journey, severity rules (impact, persistence, affected journeys), which actions
may be automatic, which need a named approver and which roles may approve, rollback eligibility, and data-handling rules
(what is redacted before an LLM or an export). The engine returns `allow`, `block` or `escalate` with the rule that decided it, and
the decision, pack version and approver are written to the audit trail. An LLM may explain or propose; it never decides permission.

## campus-api

* `environments/unisphere/build_profile.py` turns the raw log (kept outside the repository) into `profile.json`: normalised
  endpoints, request share, method, status mix, latency quantiles, error categories (categories only, no messages that carry
  user data) and the hour-of-day load curve. Tokens, emails and user ids never enter the profile.
* `samples/campus-api` is a small FastAPI service with one handler per endpoint family (gate pass, shuttle, biometric, auth, …).
  Handlers sleep and fail according to the profile, so the service looks like the real one from the outside. It exposes `/health`,
  `/metrics` and the standard Sentinel telemetry.
* Replay traffic: the Sentinel traffic generator drives it from the profile, with the day's load curve compressed (24 h in a few
  minutes) and the endpoint mix preserved.
* Injected changes are lab recipes applied to the working copy and deployed with Restart, so each has a commit, a diff and a known
  time: `slow_gatepass` (added work per request) and `gatepass_error` (a bug that returns 500 for a class of requests).

## cloud-metrics and RCAEval

* Offline adapters in `evaluation/external/` convert each dataset to a common record (time series with labels; failure case with
  telemetry and root-cause label) and score Sentinel's detector or service ranking against baselines on a split fixed before tuning.
* A small replay exporter shows a chosen series live in Prometheus and Grafana for the demo.

## Data-readiness check

`python -m evaluation.readiness <file-or-dir>` reads a sample of a user's data and reports: format, time resolution, whether
services/endpoints are identifiable, whether latency, errors and resources are present, whether deployment events or code exist,
and therefore which pipeline stages can run, with the reasons. It is the first step of a shadow-mode pilot.

## Out of scope for now

Streaming ingestion from remote companies (the mechanism is documented: Prometheus remote-write or federation, Promtail or OTLP),
Microsoft/RCAEval live replay beyond a demo exporter, tracing for non-Python code.
