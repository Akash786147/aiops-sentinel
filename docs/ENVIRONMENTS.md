# Industry environments: study guide

This is the document to study and to run from on a new server. It explains what was added after the review, why, how each part
works, what the numbers say, what is honest to claim, and the exact commands.

Contents: [1 Why](#1-why-this-was-added) · [2 Overview](#2-what-was-built-at-a-glance) · [3 campus-api](#3-campus-api-real-traffic-injected-changes) ·
[4 Policy packs](#4-industry-profiles-and-policy-packs) · [5 Readiness check](#5-the-data-readiness-check) ·
[6 Microsoft](#6-microsoft-cloud-monitoring-dataset-detection-on-real-production-series) · [7 RCAEval](#7-rcaeval-service-level-root-cause-ranking) ·
[8 Which industries](#8-which-industries-would-use-this) · [9 Honest claims](#9-what-you-can-and-cannot-claim) · [10 Run on a new server](#10-run-it-on-a-new-server) ·
[11 Demo](#11-demo-script) · [12 Viva questions](#12-questions-you-should-be-able-to-answer) · [13 File map](#13-file-map)

---

## 1. Why this was added

The reviewer said the project is good and the research is well understood, but it needs **real-time data relevant to corporate
requirements and policies**. The follow-up concern was: *which industries would use this, and does it work on their data and in
their environment?*

Before this work, all evidence came from three services we wrote (`orders`, `inventory`, `payments`) with faults we injected. That
is a valid controlled experiment but it does not show the system survives data it was not designed around. So the project now has:

| Gap named by the review | What answers it |
| --- | --- |
| Real data, not only simulated | A replay service built from a **real** request log (126,794 requests); two **public, independently produced** datasets |
| Real-time | A running platform driven by that traffic with the real daily load curve, detecting and diagnosing a change live |
| Corporate requirements and policies | **Policy packs**: SLOs per business journey, who may approve, what may be automatic, what is redacted |
| Which industries / their data / their environment | An **industry profile** per environment, and a **data-readiness check** that says what Sentinel can do on someone else's data and why |

The synthetic `orders / inventory / payments` services are kept (they have code and ground truth, which nothing else has) but are
hidden by default. Set `SENTINEL_LAB=1` to show them.

## 2. What was built, at a glance

```
raw Unisphere log (private, never in git)
        │ environments/unisphere/build_profile.py   (aggregate, anonymise)
        ▼
samples/campus-api/campus/profile.json  (26 KB: endpoint mix, latency curves, status mix, hourly load)
        │
        ▼
campus-api service ── deployed and watched by the Sentinel platform ── Prometheus / Grafana / Loki
        ▲                          │
 replay traffic (controlplane/     ├─ detector → incident → investigator (rank, confirm, patch)
 replay.py): the real daily        └─ policy pack (environments/policies/campus.yml) decides allow / block / escalate
 load curve, compressed

public datasets (offline evaluation, not services)
   Microsoft Cloud Monitoring  → evaluation/external/microsoft.py  → detection precision / recall / delay / false alarms
   RCAEval RE1                 → evaluation/external/rcaeval.py    → faulty service ranked first

any customer data → evaluation/readiness.py → "this stage: yes / needs input / no, because …"
```

| Environment | Real part | Injected part | Stages it can test |
| --- | --- | --- | --- |
| `campus-api` (Unisphere) | traffic shape, latency, status mix, daily load | the code change ("v2") and its time | detect, attribute, change correlation, trace, confirming test, SLO policy |
| Microsoft Cloud Monitoring | 60 expert-labelled production series | none | detection only |
| RCAEval RE1 | 375 fault-injection cases on 3 systems | faults injected by the dataset authors | service-level root-cause ranking only |
| Synthetic lab (hidden) | none | everything | all stages, with code ground truth |

## 3. campus-api: real traffic, injected changes

### 3.1 What the source data is
A request log from a campus application (gate passes, shuttle tickets, biometric punches, fest events): 126,794 requests over 9 days,
75 distinct endpoints, 1,490 users. Each row has endpoint, method, status code, response time (ms), timestamp, error text, and payloads.

Facts found in it, which shaped the design:
* **Latency is small**: p50 4 ms, p95 13 ms, p99 138 ms. A fixed "p95 > 500 ms" alert would almost never fire.
* **About 10% of responses are 401** ("User or role is inactive"): client/auth noise. The detector counts **5xx only**, which is why it is not
  fooled. A naive "error rate" alert would fire constantly.
* **Only 21 server errors (5xx)**, in three tight bursts (27 Feb, 1 Mar, 2 Mar), five of them a database error. These look like real incidents but
  have no labels, so they are **not** used for scoring.
* **Load follows a daily curve** (peak around 07:00 UTC, near zero at night).
* **No deployments, no CPU/memory, no code** in the log, and the backend is TypeScript. So code-level stages cannot be tested on the raw data.

### 3.2 How it became a service (Option B: semi-synthetic)
Because the log has no deployment records, we do **not** pretend it does:

1. `environments/unisphere/build_profile.py` reads the raw log (kept outside git) and writes `profile.json`: per endpoint the request share, status
   mix and an 11-point latency quantile curve, plus the 24-hour load shape. **Tokens, emails, user ids and payloads never enter the profile**
   (tested: `tests/test_env_unisphere_profile.py`).
2. `samples/campus-api` is a small FastAPI app with one route per real endpoint. Each handler sleeps for a latency drawn from the endpoint's recorded
   curve and answers with a status drawn from its recorded mix. From the outside it looks like the real application (tested: sampled p50/p95 match
   the recorded ones).
3. The handlers live in real source files (`campus/gatepass.py`, `shuttle.py`, `biometric.py`, `directory.py`), so a change to them is a genuine git
   diff the tracer can analyse.
4. `controlplane/replay.py` drives the service with the recorded request mix and the real hour-of-day load curve, compressed (a day in
   `SENTINEL_REPLAY_DAY_S` seconds, default 600).
5. **The change is injected and labelled as such.** Two Test-lab recipes edit the gate-pass source:
   * `slow_gatepass`: re-validates every pass 40 extra times (about 80 ms more per request)
   * `gatepass_error`: creating or updating a pass raises when a department is missing (HTTP 500)

   After **Restart** they are a commit with a known time, so Sentinel's whole pipeline runs on real traffic shape and noise.

### 3.3 What a run showed (local, process runtime)
Apply `slow_gatepass`, Restart. About 30 s later:
* incident `regression`: gate-pass p95 5.84 → 109.48 ms (z = 73), `gatepass/all` 12.0 → 120.4 ms
* top suspect: `process` in `campus/gatepass.py` lines 9–13 (the file that was changed)
* the template test **fails by assertion on the bad version and passes on the last good version** (confirming)
* proposed patch: revert `campus/gatepass.py` to the last good version; applies cleanly
* the Policy tab shows the gate-pass journey **SLO breached**

State this as: *"real traffic shape and noise, injected change at a known time"*, never as "a real production incident".

## 4. Industry profiles and policy packs

A **policy pack** is a versioned YAML file under `environments/policies/`. It is the machine-readable answer to "what is allowed here". The decision
engine (`controlplane/packs.py`) is deterministic: it returns `allow`, `block` or `escalate`, names the **rule** that decided, and every decision is
written to the audit trail. An LLM may explain or propose; it never decides permission.

| Profile (pack) | Data behind it | Emphasis |
| --- | --- | --- |
| `campus` | Unisphere logs | SLOs for gate pass (99.5%, p95 150 ms), shuttle, biometric; only named approvers; confirming test required |
| `ecommerce` | RCAEval Online Boutique, Sock Shop | checkout availability and latency |
| `travel` | RCAEval Train Ticket | booking availability |
| `cloud` | Microsoft series | API latency, crash rate |
| `fintech` | our payments sample | **no automatic rollback at all**: every rollback is a human decision; strict redaction |

All five say in their description that they are **demonstration policies, not any organisation's real policy**.

What a pack contains: business-journey SLOs; which incident kinds may be rolled back automatically; who may approve a patch and whether a confirming
test is required; whether scaling is ever automatic (never, without capacity evidence); what is redacted before data reaches a model.

Where it is enforced (not just displayed):
* **Automatic rollback** (`controlplane/policy.py`): the pack is consulted before a rollback. If the pack says no, the incident is **held for a person** and a
  `policy_decision` is audited once.
* **Approve button** (`Investigator.authorise`): a name not on the pack's list gets HTTP **403** with the reason, and the attempt is audited.
* **Policy tab** on every service: the pack, live SLO status per journey (availability = non-5xx share, p95 request-weighted), and the rules.

Scenario matrix that is unit-tested (`tests/test_policy_packs.py`, `tests/test_policy_integration.py`):

| Situation | Outcome |
| --- | --- |
| crash loop or OOM, default pack | allow rollback |
| latency regression | escalate (a person decides) |
| no known-good version | escalate |
| OOM under the fintech pack | escalate (held for a person), audited once |
| CPU spike without capacity evidence, asked to scale | block |
| capacity evidence present, asked to scale | escalate (scaling is never automatic) |
| approver not on the list | block (HTTP 403) |
| patch without a confirming test | block |
| insufficient evidence | escalate rather than invent a cause |
| unknown action | block |

## 5. The data-readiness check

`python -m evaluation.readiness <file>` answers the evaluator's question *"will it work on our data?"* without running anything. It reads the structure
(JSON, JSON lines or CSV), never prints values, and reports per stage `yes`, `partial`, `needs input` or `no`, with the reason.

On the Unisphere log it says: detection **yes**, service attribution **yes**, SLO policy **yes**, change correlation **needs input** (no deployment field:
supply deployment times or a git history), function tracing and confirming tests **need input** (the source repository), resource scaling **no** (no CPU or
memory), and it warns that access tokens, emails and user ids are present. On a Microsoft series it says detection yes and everything else no, because a
single unnamed series cannot say which service is affected.

This is also the **pilot protocol**: run readiness on a sample of a company's data, agree which stages apply, then run Sentinel in shadow mode (read-only,
no actions) and report detection, false alarms and what could not be done.

## 6. Microsoft Cloud Monitoring Dataset: detection on real production series

* Source: github.com/microsoft/cloud-monitoring-dataset (MIT). 60 CSV series in the repository (the README mentions 67), per hour or per minute, labelled by
  domain experts; 299 labelled anomaly segments; 6 series with no anomalies, to test false alarms.
* It has **no deployments and no code**, so this tests detection only.
* Rules were fixed from the data's granularity before scoring and **nothing was tuned on labels**: window = 7 days of points (at most a quarter of the series),
  persistence 3 points, missing values carried forward. The same rules apply to every method. An alert counts when it falls inside a labelled segment or within
  3 points after it.

Methods: fixed threshold (mean ± 3 sd of the first window, single point; the rule an operator has), rolling z-score (|z| ≥ 3, 3 points), and **Sentinel's method**
(median / MAD, |z| ≥ 6, 3 points, two-sided).

| Method | Precision | Recall | F1 | Median delay | False alarms per 1000 points (anomaly-free series) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed threshold | 0.20 | 0.49 | 0.29 | 1 point | 0.83 |
| Rolling z-score | 0.49 | 0.21 | 0.29 | 3 points | 0.37 |
| **Sentinel (robust + persistence)** | 0.48 | 0.22 | 0.31 | 3 points | **0.05** |

Read it honestly:
* **F1 is about 0.3 for all three.** Sentinel does not win on F1. The dataset is hard and the labelled anomalies are often subtle.
* What Sentinel **does** give is the lowest false-alarm rate: about 18× fewer than the fixed threshold on the anomaly-free series.
* Recall is low (0.22; 95% interval 18–27%). The two halves of the data give the same F1 (0.31 and 0.30), so it is stable, not luck.
* Per domain the picture is uneven: strong precision on crash-rate and purchase series, **zero recall on `mongodb-machine-rps` and `service-unavailable`**.
  Say so.
* The detector was designed for change-aware regressions with a known change time. Here it runs without one, as a plain rolling baseline, which is a weaker
  setting for it.

## 7. RCAEval: service-level root-cause ranking

* Source: Zenodo record 14504481 (CC-BY 4.0), RE1: metrics only (1 Hz CPU, memory, workload, latency, error per service), three systems (Online Boutique, Sock
  Shop, Train Ticket), 375 cases = service × fault type (cpu, mem, disk, delay, loss) × 5 runs. The label is the faulty service; the injection time is given.
* It has **no code or deployments**, so it tests only: *given a known change time, is the faulty service ranked first?* The injection time stands in for a known
  deployment time.
* Rules fixed before scoring: use the compact per-service data (`simple_data.csv` for Sock Shop and Train Ticket, `data.csv` for Online Boutique); candidates
  are services with a CPU metric; no tuning; every case scored, none re-run.

| Method | AC@1 | 95% interval | AC@3 | Avg@5 |
| --- | ---: | ---: | ---: | ---: |
| Random (expected) | 0.06 | 4–8% | 0.17 | 0.17 |
| Latency ratio (what an operator watches) | 0.82 | 77–85% | 0.93 | 0.91 |
| **Sentinel change-aware robust score** | **0.89** | 85–92% | 0.97 | 0.95 |

Per fault type (AC@1, latency ratio vs Sentinel): cpu 0.72 / **0.92**, disk 0.71 / **0.88**, memory 0.93 / 0.96, delay 0.96 / 0.93, loss 0.76 / 0.75.
Per system: Online Boutique 0.72 / **0.90**, Sock Shop 0.94 / 0.95, Train Ticket 0.78 / 0.81.

Read it honestly:
* Sentinel's gain is real but modest overall (+7 points, intervals touching) and concentrated where the symptom is **not** latency: CPU and disk faults, which
  a latency dashboard misses. For delay and packet loss, where latency *is* the symptom, the operator's view is as good or slightly better.
* The score is close in spirit to published robust-z methods; claim it as "the change-aware robust score works on independent data", not as a new algorithm.
* This validates **service attribution** only. It does not validate function tracing or confirming tests; those are validated on our own benchmark and on
  `campus-api`.

## 8. Which industries would use this

Sentinel fits an organisation that has **many services or teams on shared infrastructure, frequent deploys with git history, per-service reliability
targets, and an audit requirement.** Typical examples: SaaS and cloud platforms, e-commerce and travel, fintech, managed hosting and internal developer
platforms, and university or enterprise IT running shared servers.

Evidence we have, per industry (never claim more):

| Industry | Evidence | Strength |
| --- | --- | --- |
| Campus / enterprise operations | real request log, replay service, SLO pack | traffic real, change injected |
| E-commerce, travel | RCAEval Online Boutique, Sock Shop, Train Ticket | real telemetry, service-level only |
| Cloud / SaaS | Microsoft series | detection only |
| Fintech | policy pack and synthetic payments service | policy demonstration only; no real data |
| Healthcare, telecom, government | none | do not claim |

Before a real adoption: run the readiness check, then a shadow-mode pilot on their data and environment, and report what Sentinel could and could not do.

## 9. What you can and cannot claim

Can claim:
* The pipeline runs on traffic shaped by a real application and finds an injected change, ranks the changed file first and confirms it with a test.
* On 375 real fault-injection cases from three systems, the change-aware robust score ranks the faulty service first 89% of the time (85–92%).
* On 60 expert-labelled production series, it gives the lowest false-alarm rate of the three detectors, with F1 similar to the others.
* Policies are executable, versioned, deterministic and audited.

Cannot claim:
* "Tested on production incidents": the campus change is injected.
* "Beats Microsoft or Meta": different scale and different task. Say: *Sentinel adds function-level, deployment-aware, test-verified diagnosis.*
* "Works for any industry": three have some evidence, two have none.
* Function-level accuracy on RCAEval or Microsoft data: they contain no code.
* "Compliance": the packs are demonstration policies.

## 10. Run it on a new server

Assumes a fresh Ubuntu 22.04 / 24.04 server with 4+ GB RAM, 2+ vCPU and about 10 GB free disk (the RE1 archive is 390 MB and is read in place, not unpacked).

```bash
# 1. get the code
git clone <repo-url> aiops-sentinel && cd aiops-sentinel
cp .env.example .env            # optional: OPENAI_API_KEY or GROQ_API_KEY for LLM re-ranking; works without

# 2. if port 80 is taken (for example by nginx), publish Traefik on 8080 instead
grep -n '"80:80"' deploy/docker-compose.yml          # skip if the committed file already says 8080:80
sed -i 's/"80:80"/"8080:80"/' deploy/docker-compose.yml

# 3. install Docker if needed, create the state folder, start the stack
sudo bash deploy/install.sh       # skip if Docker is installed; then:  sudo mkdir -p /srv/sentinel && sudo chown $USER /srv/sentinel
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps           # 9 containers; campus-api is started by Sentinel itself

# 4. look at it
curl -s localhost:8080/api/health
#   browser: http://<server-ip>:8080/     (light mode is the default; "Dark mode" button top right)

# 5. independent-data evaluations (download once, then score)
make fetch-data                  # Microsoft dataset (~10 MB) and RCAEval RE1 (~390 MB) into /srv/sentinel/data
make eval-rcaeval                # about 1 minute
make eval-microsoft              # 5 to 10 minutes
# results are written to /srv/sentinel/data and appear on the console's Results page ("Independent data") with no rebuild
```

Notes:
* `SENTINEL_BOOTSTRAP` now defaults to the campus environment only. `SENTINEL_LAB=1` brings back the three synthetic samples in **Add service**.
* The Unisphere raw log is not needed on the server: `samples/campus-api/campus/profile.json` is in the repository. Keep the raw file out of git (it is ignored).
* To check someone's data: `make readiness FILE=/srv/sentinel/data/theirfile.json`.
* The first `docker compose up` builds the control plane image (several minutes); campus-api builds the first time Sentinel deploys it.
* Clean up: `docker ps -aq --filter label=sentinel.monitor=true | xargs -r docker rm -f; docker compose -f deploy/docker-compose.yml down -v; sudo rm -rf /srv/sentinel`.

Laptop without Docker: `python -m controlplane --port 8800` (processes instead of containers), and the same `python -m evaluation.external.*` commands
with local paths.

## 11. Demo script

1. **Overview**: campus-api healthy, traffic on (the real daily load, compressed). Explain: real traffic shape, injected change.
2. **Service → Policy**: the `campus` pack, three journey SLOs within target, what Sentinel may do automatically.
3. **Test lab → campus-api → `slow_gatepass` → Apply → Restart now.** Show the diff (an injected loop in `gatepass.py`).
4. About 30–60 s later an incident appears. **Incident page**: signals (p95 5.8 → 109 ms), ranked suspects (`process` in `gatepass.py` first), the code at the bad
   version with the changed lines highlighted, the confirming test (fails on bad, passes on last good), the proposed patch.
5. **Policy tab**: gate-pass journey now **SLO breached**.
6. Try **Approve** with a name not on the list: HTTP 403 with the rule that blocked it, visible in **Audit trail**. Then approve as `akash`.
7. **Results page → Independent data**: Microsoft and RCAEval tables. Say what each can and cannot show.
8. Run `make readiness FILE=...` on any file to answer "will it work on our data?"

## 12. Questions you should be able to answer

1. Why is the campus change injected, and why is that still useful? (Real traffic and noise, known change time, whole pipeline testable.)
2. Why not just use the real log directly? (No deployments, no code, no resources; see the readiness report.)
3. How do you know no personal data leaks? (Profile holds aggregates only; test asserts no `@`, token or id; the raw file is git-ignored.)
4. Why does Sentinel not win F1 on the Microsoft data, and why is it still worth having? (Low false alarms; designed for change-aware use.)
5. What does RCAEval validate and what does it not? (Service attribution given a known change time; not code.)
6. Why is the 5xx-only rule important on the campus data? (10% of responses are 401 client noise.)
7. Who decides if a rollback is allowed? (The pack, deterministically; the LLM never does.)
8. What happens if the fintech pack meets an OOM kill? (Held for a person, audited once.)
9. Which industries do you have evidence for, and which not? (Table in section 8.)
10. How would a company pilot this? (Readiness check, agree stages, shadow mode, report.)

## 13. File map

| What | Where |
| --- | --- |
| Profile builder (private log to anonymous profile) | `environments/unisphere/build_profile.py` |
| Campus replay service | `samples/campus-api/` (`campus/behaviour.py`, `gatepass.py`, `profile.json`) |
| Replay traffic and daily load curve | `controlplane/replay.py`, `controlplane/traffic.py` |
| Injected changes (Test lab recipes) | `controlplane/faults.py` (`INJECTED`) |
| Policy packs and engine | `environments/policies/*.yml`, `controlplane/packs.py`, `controlplane/policy.py`, `controlplane/investigator.py` (`authorise`) |
| Policy API and tab | `GET /api/services/{name}/policy`, `controlplane/static/js/views/service.js` |
| Readiness check | `evaluation/readiness.py` |
| Microsoft evaluation | `evaluation/external/microsoft.py`, results `evaluation/results/external/microsoft.json` |
| RCAEval evaluation | `evaluation/external/rcaeval.py`, results `evaluation/results/external/rcaeval_re1.json` |
| Dataset download | `environments/fetch_datasets.sh`, `make fetch-data` |
| Design note | `docs/superpowers/specs/2026-10-30-industry-environments-design.md` |
| Tests | `tests/test_env_*.py`, `tests/test_ext_*.py`, `tests/test_policy_*.py`, `tests/test_readiness.py` |
| Related research | `docs/RESEARCH_COMPARISON.md` |
