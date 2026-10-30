# Individual work: who owns what, and what each person must be able to explain

The project is graded on, among other things, **individual understanding**. This page gives each member their part: what
it does and why, the code and tests they own, the numbers to quote, the failures to admit, and the questions to expect.

How the work is split follows the ten steps. The original split (steps 1–2, 3–5, 6 + evaluation) is fixed. The platform was
added later, so its split below is **proposed along the same lines**: change it if your actual contributions differ, but keep
every module owned by exactly one person and make sure each person can run their part live.

| Member | Research pipeline | Platform (proposed) | Evaluation role |
| --- | --- | --- | --- |
| **Akash (P1)** | Steps 1–2: telemetry, registry, detector | Runtime, deployer, monitor, detector, policy, ops stack | Benchmark design, detection results |
| **Aryan (P2)** | Steps 3–5: evidence packet, code index, tracer | Investigator (suspects, diagnosis), workspace/git, sample services | Localisation results, ablation |
| **Syna (P3)** | Step 6: confirming tests, LLM layer | Test lab and fault catalogue, patch proposal and approval, Sentinel Console results views | Test-generation results, LLM comparison, statistics |
| **All three** | Audit trail, guardrails, docs, slides | REST API, UI shell, CI, runbook | Limitations, review response |

---

## 1. Akash (P1): see the system and notice that something changed

### 1.1 In one paragraph

Akash owns the front of the pipeline: getting trustworthy per-service signals from a shared server and deciding, per
tenant, that something genuinely changed. On the platform he also owns the machinery that makes the system *act*: running
services as containers, deploying a new version only if it passes a health gate, watching the running containers, and
rolling back.

### 1.2 Research pipeline

| Part | What it does | Why | Files |
| --- | --- | --- | --- |
| Telemetry middleware | Per-route latency (p50/p95/max), 5xx counts, exceptions with frames inside our code, up to 20 slow or failed request samples, one normal exemplar per route | Host CPU says something is wrong, not whose; routes say where, exceptions say which line, samples let step 6 replay | `shared_server/common/telemetry.py` |
| Collector | Scrapes each registered service's `/metrics` every second; per-process CPU and RSS with psutil | Attribution to a tenant without an agent | `sentinel/telemetry.py` |
| Registry | Owner, port and code path of every service | Gives every signal an owner and a code path | `shared_server/services.yaml`, `sentinel/registry.py` |
| Detector | After vs before a change: median and MAD, z ≥ 6 plus an absolute change floor, ≥ 3 anomalous buckets, and an anomalous share ≥ 30 points above the baseline's own; memory by net growth ≥ 10 MiB and a positive Theil–Sen slope | Fixed thresholds miss slow regressions and fire on bursty routes | `sentinel/detection.py` |
| Threshold baseline | p95 > 500 ms, error rate > 5%, CPU > 80%, RSS > 500 MiB | The fair "what an operator has today" comparison | same |

Numbers to quote (45 runs; intervals in [REVIEW_RESPONSE.md](REVIEW_RESPONSE.md)):
- Fault recall **92%** (33 of 36) vs **33%** for fixed thresholds; right service first 92%.
- By class: CPU 100% vs 33%, errors 100% vs 100%, latency 80% vs 0%, memory 100% vs 0%.
- False alarms on quiet deployments **2 of 6** (both on the bursty `/pay` route after a restart).
- Miss: **F09**, a lock held during an audit write, adds about 4 ms and is below every floor in 3 of 3 runs.

### 1.3 Platform

| Module | Responsibility | Test file |
| --- | --- | --- |
| `controlplane/runtime/` | `Runtime` protocol; `DockerRuntime` (build image, run container with CPU/memory limit, labels, health status, OOM flag, stats) and `ProcessRuntime` (laptop and tests, with a memory watchdog) | `test_cp_runtime_docker.py`, `test_cp_runtime_process.py` |
| `controlplane/deployer.py` | Restart = commit working copy → build → start new instance → health gate → swap; a failed gate leaves the old version serving; rollback restores the tree with `git read-tree` and commits (no history rewrite); last good is promoted after the stability window | `test_cp_deployer.py` |
| `controlplane/monitor.py` | 1 s samples of latency, errors, CPU, memory; rolling series for the UI | `test_cp_monitor.py` |
| `controlplane/detector.py` | Lifecycle (crash, OOM, crash loop ≥ 3 restarts in 120 s, unhealthy), resource guards (memory ≥ 95%, CPU ≥ 90% held 30 s), regression against the previous deployment (reuses `sentinel.detection`), Alertmanager alerts; one open incident per service with severity escalation | `test_cp_detector.py` |
| `controlplane/policy.py` | The only automatic action: roll back to last good, once per incident, only for crash loop, OOM, unhealthy, memory | `test_cp_detector.py` |
| `deploy/` | Compose stack, Prometheus rules, Alertmanager, Loki/Promtail, Grafana, install script, systemd unit | `test_deploy_configs.py` |

Real-server bugs found and fixed: Alertmanager needs an `http(s)` external URL; Traefik 3.1 could not talk to Docker 29's API
(fixed by v3.6.1).

### 1.4 Be ready to answer
1. Why per-process, per-route telemetry on a shared server instead of host metrics?
2. Why compare after-change against before-change, and what happens when the change time is unknown?
3. What is MAD, why 1.4826, and why a robust z instead of mean and standard deviation?
4. Why three conditions (z, absolute change, persistence) and what each one prevents.
5. Why can fixed thresholds not see latency faults that moved a route from 5 ms to 300 ms?
6. Why did F09 escape, and would you lower the floors? What would it cost?
7. Walk through a restart: what happens if the new version never becomes healthy? If it passes the gate and crashes 40 s later?
8. Why is rollback a **new commit** and why is it limited to a few incident kinds, once per incident?
9. What can the Docker socket do, and why is mounting it a risk?
10. What does Prometheus do that Sentinel's own monitor does not, and why have both?

---

## 2. Aryan (P2): turn a symptom into evidence, then into a function

### 2.1 In one paragraph

Aryan owns what happens once an incident exists: collect the evidence, index the code so a symptom can be searched, and rank
the functions most likely to be responsible, combining several kinds of evidence instead of trusting text similarity. On the
platform the same machinery runs on the *bad commit* after a crash or regression.

### 2.2 Research pipeline

| Part | What it does | Why | Files |
| --- | --- | --- | --- |
| Evidence packet | Anomalous signals, grouped exceptions, slow/failed requests, exemplars, owner and code path, and the deployment: commits, changed line ranges (`git diff -U0` + `git blame`), a **behavioural** flag (AST differs after removing comments and docstrings); redaction; digest | The model sees evidence, not the repo; the audit trail names the exact evidence used; a docstring edit must not look like a cause | `sentinel/context.py` |
| Code index | One chunk per function/method, class header and module-level block; routes, calls and defined names → call graph; BM25 over identifier-aware tokens; dense bge-small-en-v1.5 embeddings | Function-level chunks match what a human names in a diagnosis and what the ground truth scores | `sentinel/indexing.py` |
| Hybrid tracer | Seven features and fixed weights: trace 2.5, call_path 1.5, changed_lines 1.5, lexical 1.0, dense 1.0, route 1.0, changed_file 0.3; scoped to the tenant's code | A stack frame is near-proof; a lexical match is weak. Weights were set before the benchmark and not tuned | `sentinel/tracing.py` |
| Action decision | Confidence = 0.35 on-call-path + 0.35 (trace or behavioural change) + 0.3 margin; `capacity_scale` only if traffic rose and there is no code evidence; `code_fix` at ≥ 0.6; otherwise `investigate` | Make "don't scale blindly" explicit | same |
| LLM re-rank | Top 8 candidates and the packet to the LLM, temperature 0 where supported, JSON only, ids validated | LLM as a re-ranker over evidence, not a reader of the repo | `sentinel/llm.py` (shared with Syna) |

Numbers to quote (n = 33 detected fault runs):
- Top-1 **85%**, Top-3 97%, MRR 0.91; held-out Top-1 86%.
- Against: blame the deployment 36%, plain RAG + LLM 46%, BM25 18%, embeddings 15%, old v0 retriever 3%.
- Ablation (Top-1): without the deployment diff 61%, without route + call graph 67%, without stack frames 85%, without tenant
  scope 88%, without embeddings 91%, without BM25 91%.
- Honest reading: structure carries the result; removing text similarity slightly *raises* Top-1. The full hybrid is reported
  because its weights were fixed first.

### 2.3 Platform

| Module | Responsibility | Test file |
| --- | --- | --- |
| `controlplane/investigator.py` | On an incident: git worktree of the bad commit, export of the last-good tree, tags `deploy-prev`/`deploy-current`; parses JSON and plain Python tracebacks; builds the packet, ranks, optional LLM re-rank; proposes a patch (LLM diff checked with `git apply --check`, else revert of the suspect files); **Approve** applies it and deploys | `test_cp_investigator.py` |
| `controlplane/workspace.py` | One git repository per service: commit, diff, restore, tag, export, safe file read and write (blocks path traversal and `.git`) | `test_cp_api.py` |
| `controlplane/registry.py` | Register a sample or a bring-your-own git repo | `test_cp_api.py` |
| `samples/` | The three deployable services, each with Dockerfile, `/health`, `/metrics`, JSON exception logs | `test_samples.py` |

### 2.4 Be ready to answer
1. Why chunk by function using the syntax tree and not by fixed windows? What did the v0 retriever do and why is it 3%?
2. What is BM25, and why identifier-aware tokens (`load_customer` → `load`, `customer`)?
3. What does a bge-small embedding capture that BM25 does not, and why did removing it raise Top-1?
4. Explain each of the seven features and why the weights were not tuned on the results.
5. What is a behavioural diff and why does it matter?
6. Why is "blame the newest commit" a strong baseline, and why does the tracer beat it (36% vs 85%)?
7. Walk through the F07 failure: why does the symptom lead to the function that *uses* the regex and not to the constant?
8. What stops the LLM inventing a function? (candidate ids only, validation, counted: 5 invented ids in 33 runs.)
9. Why is tenant scope a safety property and not an accuracy feature (88% unscoped vs 85%)?
10. How would this fail on a bug that was always present?

---

## 3. Syna (P3): prove the diagnosis, and measure everything honestly

### 3.1 In one paragraph

Syna owns step 6 and the evaluation. A diagnosis is a hypothesis; a test that fails on the deployed code and passes on the
known-good code is evidence. Syna also owns the benchmark and the scoring, so every claim in the other two parts can be
checked.

### 3.2 Research pipeline

| Part | What it does | Why | Files |
| --- | --- | --- | --- |
| Template test generator | Errors → replay failing requests, assert no 5xx; latency/CPU → replay the slowest request 20×, assert median ≤ max(3×, +10 ms) and p95 ≤ max(2×, +20 ms) of baseline; memory → 200 rounds with tracemalloc growth < 8 MiB | Deterministic and explainable | `sentinel/testgen.py` |
| LLM test generator | Gets packet, top-3 suspect code, observed requests, baselines; writes the test itself | Can write tests a template cannot (for example lock contention) | same, `sentinel/llm.py` |
| Guard | Parses; no `os/sys/subprocess/socket/shutil/pathlib/httpx` imports; no `open/eval/exec/__import__`; no skip or xfail; at least one `test_` and one `assert` | Generated code must never be run unchecked | same |
| Sandbox | Fresh copy, API keys stripped, 90 s timeout, JUnit XML so that only an assertion failure counts | A crash is not a confirmation | same |
| Benchmark | 12 faults + 3 controls, 3 seeds, a fault hidden among 3 decoy commits, ground truth by file and line range, live recorder, demo | Ground truth with a hard baseline | `benchmark/`, `evaluation/benchmark.py` |
| Scoring | Detection, localisation, tests and action, all baselines, ablations, held-out split | One command regenerates every number | `evaluation/benchmark.py score` |

Numbers to quote:
- Confirming tests: template **94%** (31/33), LLM gpt-5.4-mini **91%** (30/33), gpt-oss-120b **27%** (3/11, seed 0 only).
- The decisive column is *passes on known-good*: gpt-oss usually asserted incidental behaviour that the correct code also
  failed (36% pass).
- The 3 gpt-5.4-mini failures were empty answers (output budget spent on reasoning), not guard blocks, and were not re-run.
- Action accuracy: Sentinel **82%** vs **13%** for scaling on every alert. 8 wrong decisions, each listed.

### 3.3 Platform

| Module | Responsibility | Test file |
| --- | --- | --- |
| `controlplane/faults.py` | Test lab: benchmark faults F01–F12 for the matching sample, plus `crash_on_start`, `oom_leak` (4 MiB per request) and `cpu_spin` for any service; preview, apply, reset to last good; audited | `test_cp_faults.py` |
| Patch approval flow | Approve with a named approver (empty approver rejected), dismiss, "close: keep the rollback" | `test_cp_api.py` |
| `controlplane/static/js/views/benchmark.js` | Results page: the evaluation tables and charts, with each metric's definition on hover | manual |
| Statistics | Confidence intervals in [REVIEW_RESPONSE.md](REVIEW_RESPONSE.md) | n/a |

### 3.4 Be ready to answer
1. What does "confirming" mean and why must the test also pass on the known-good code?
2. What does the guard block, and what can it not block? What does the sandbox add?
3. Why only count assertion failures (JUnit XML)?
4. Why did gpt-oss-120b fail so often on "passes on known-good"?
5. Why was seed 0 used for development and seeds 1–2 held out? What would break the claim?
6. How do you know the benchmark is not designed to make the tracer look good? What threats remain?
7. Which baseline is the hardest and why? Which results are within noise (see the intervals)?
8. Why were the three empty-answer runs not repeated?
9. How does the Test lab differ from the benchmark? (Lab: injects into a *running platform service* to show the loop; the
   benchmark: scored, repeated runs of recorded deployments.)
10. What would you run on a public dataset, and what would you expect to drop?

---

## 3b. Industry environments (proposed ownership)

Added after the second review; details in [ENVIRONMENTS.md](ENVIRONMENTS.md). Adjust to who actually did what, but give every part one owner who can run and explain it.

| Part | Owner | Files | Must be able to explain |
| --- | --- | --- | --- |
| campus-api replay, traffic profile builder, replay traffic | Akash | `environments/unisphere/`, `samples/campus-api/`, `controlplane/replay.py` | what is real and what is injected; why the profile holds no personal data; why 5xx only |
| Policy packs and enforcement; readiness check | Aryan | `environments/policies/`, `controlplane/packs.py`, `evaluation/readiness.py` | allow / block / escalate and the rule behind each; why the LLM never decides permission; what each stage needs |
| Independent evaluation (RCAEval, Microsoft), statistics, honest claims | Syna | `evaluation/external/`, `docs/REVIEW_RESPONSE.md` | rules fixed before scoring; what each dataset can and cannot validate; why F1 is about 0.3 and why that is reported |

## 4. Shared by all three

| Area | What | Files |
| --- | --- | --- |
| Audit | One JSON line per pipeline stage (run id, decision, confidence, packet digest, model, prompt version, tokens, test outcomes); on the platform an `audit` table, a live feed and an Audit page | `sentinel/audit.py`, `controlplane/store.py` |
| Guardrails | Tenant scope, redaction, JSON-only LLM output with id validation, test guard, sandbox, auto-action limited to rollback to last good, human approval for code | across modules |
| API and UI | FastAPI routes, SSE event stream, single-page console | `controlplane/app.py`, `controlplane/static/` |
| Ops | Compose stack, CI, runbook, status and review documents | `deploy/`, `.github/workflows/ci.yml`, `docs/` |

Everyone must be able to answer:
- What is the research question, and why is it not "which LLM is best"?
- What is each baseline, and which one is hardest?
- What did the ablation show, and which part of the pipeline matters most?
- What does Sentinel do automatically, and what does it never do without a person?
- What does not work (F07, F09, false alarms, the single synthetic benchmark)?
- How do you start the platform on the server, break a service on purpose, and show the rollback?

## 5. Demo split (about 10 minutes)

| Time | Presenter | Content |
| --- | --- | --- |
| 0:00 | Akash | Problem, shared server, the console Overview: three live services |
| 1:30 | Akash | Test lab: apply `oom_leak` to inventory, Restart; show detection and the automatic rollback |
| 3:30 | Aryan | Incident page: evidence packet, ranked suspects with the feature bars, the diff at the bad commit |
| 5:30 | Syna | The confirming test: fails on the bad commit, passes on the last good; the proposed patch and **Approve** |
| 7:00 | Syna | Results page: localisation table, ablation, confidence intervals, hover definitions |
| 8:30 | Aryan | Failure cases (F07, F09, false alarms) and limitations |
| 9:30 | Akash | Server stack (Grafana, Prometheus), future scope |

Backup if the network or the server is unavailable: `python -m panel` (Replay mode) and `python -m controlplane` with the
process runtime run on a laptop and need neither Docker nor a server.
