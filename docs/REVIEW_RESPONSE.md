# Response to the suggestions other groups received

Other groups' reviewers gave the comments below. We checked each one against our own project, said honestly whether it
applies, and recorded what we already have, what we added, and what is still a gap. Nothing here claims more than the
repository shows.

## 1. Point by point

| # | Comment | Applies to us? | What we have | Gap / action |
| --- | --- | --- | --- | --- |
| 1 | Well-defined future scope | Yes | [PROJECT_STATUS.md](PROJECT_STATUS.md) section 5: research, DevOps and product items, each tied to a limitation | None |
| 2 | Understanding and implementation of trade-offs | Yes | Section 3 below: every design choice with the alternative and what it cost | Extend with timing data once measured |
| 3 | Research done in the background | Yes | Section 4 below: related work, what we took from each, how we differ | Read the cited papers in full before the viva; numbers quoted from abstracts only |
| 4 | Testing, many failure cases, what improved, logs saved | Yes | 45 benchmark runs with every failure reported ([PROJECT_GUIDE.md](PROJECT_GUIDE.md) section 9); fix log in [PROJECT_STATUS.md](PROJECT_STATUS.md) section 6; JSONL audit per run; SQLite audit on the platform; 111 tests | Platform failure cases are tested one at a time; no systematic platform fault campaign yet (next item) |
| 5 | Practical and production oriented | Partly | Real containers, health-gated deploys, rollback, Traefik, Prometheus, Loki, Grafana, systemd, CI with image scan; run on a real Ubuntu server | Single host, no auth or TLS, Docker socket is root-equivalent. Listed as limitations, not hidden |
| 6 | Prometheus and watchdog tools | Yes | Prometheus (Docker service discovery, 5 alert rules), Alertmanager (webhook into Sentinel), cAdvisor, node-exporter. Watchdogs: container health checks and restart policy, Sentinel's own monitor, detector and crash-loop logic, the process runtime's watchdog | Nothing alerts when Sentinel itself is down: [PROJECT_STATUS.md](PROJECT_STATUS.md) item 8 |
| 7 | Monitoring tools | Yes | Same stack as 6, plus Loki + Promtail for logs and Grafana dashboards provisioned from files | OpenTelemetry traces are future scope |
| 8 | Relevance of the selected models | Yes | Section 5 below | Only two LLMs compared; stated as a limitation |
| 9 | More quantitative results and performance analysis | Partly | Tables, ablations, held-out split; **new**: 95% confidence intervals (section 2 below); metric definitions on hover in the console | Platform timings (time to detect, roll back, diagnose) are not yet measured: [PROJECT_STATUS.md](PROJECT_STATUS.md) item 2 |
| 10 | Proper workflow | Yes | Section 6 below; [WORKFLOW.md](WORKFLOW.md) | None |
| 11 | A dataset to increase reliability | Partly | Our benchmark is synthetic and generated (12 faults, 3 seeds). Public candidates identified: RCAEval, BugsInPy, AIOpsLab | Not yet run on any public dataset: the biggest threat to validity, in [PROJECT_STATUS.md](PROJECT_STATUS.md) section 5A |
| 12 | More on the DevOps pipeline | Yes | The platform *is* the DevOps pipeline: build, health gate, swap, post-deploy watch, rollback, CI with lint, test, image scan and compose validation | Webhook-triggered deploys and canary releases are future scope |
| 13 | Strong research backing through a research review | Yes | Section 4 below | As in 3 |
| 14 | Evaluation metric tooltips on hover | Done | The Results page in the console now shows the definition of each metric on hover | None |
| 15 | "Feedback for a project, we need not do this" | n/a | Not a project requirement | None |
| 16 | The scope is vast and looked like an assignment; focus on the research question, not just comparing three models | Applies as a risk | Section 7 below | Keep the story research-first; see the recommended framing |

## 1b. Second review: real data, corporate policies, and "which industries?"

| Comment | Answer | Where |
| --- | --- | --- |
| Use real-time datasets relevant to corporate requirements | Replay service built from a real 126,794-request log, driven by its real daily load; two independent public datasets scored with rules fixed in advance | [ENVIRONMENTS.md](ENVIRONMENTS.md) sections 3, 6, 7 |
| Corporate requirements and policies | Executable policy packs per industry profile: business-journey SLOs, authorised approvers, which actions may be automatic, redaction; enforced on rollback and Approve; audited | section 4 |
| Which industries would use this, and does it work on their data and environment? | Fit criteria and an evidence table per industry; a **data-readiness check** that says which stages work on a given dataset and why; a shadow-mode pilot protocol | sections 5, 8 |
| Strong research backing | Comparison with RCACopilot, in-context GPT-4 RCA, LLM agents and Meta's just-in-time tests | [RESEARCH_COMPARISON.md](RESEARCH_COMPARISON.md) |

What the independent data actually says (95% intervals in the study guide): on 375 real RCAEval cases the change-aware robust score ranks the faulty service first
89% of the time (85–92%) vs 82% (77–85%) for the latency view an operator watches; the gain is concentrated on CPU and disk faults. On the Microsoft series F1 is about 0.3
for every method; Sentinel's contribution there is the lowest false-alarm rate (about 18 times lower than a fixed threshold). Neither dataset contains code, so function-level
and confirming-test results still rest on our own benchmark and the campus replay, where the change is injected.

## 2. Confidence intervals

Reviewers asked for more quantitative analysis. With 33 to 45 runs a single percentage hides a lot of uncertainty, so here are
Wilson 95% intervals for the headline rates. Counts are derived from the rates in `evaluation/results/summary.md` and n.

| Result | k / n | Rate | 95% interval |
| --- | ---: | ---: | ---: |
| Detection recall, robust detector | 33 / 36 | 92% | 78–97% |
| Detection recall, fixed thresholds | 12 / 36 | 33% | 20–50% |
| False alarms on quiet deployments | 2 / 6 | 33% | 10–70% |
| Hybrid tracer, Top-1 | 28 / 33 | 85% | 69–93% |
| Hybrid tracer, Top-3 | 32 / 33 | 97% | 85–99% |
| Hybrid + LLM (gpt-5.4-mini), Top-1 | 27 / 33 | 82% | 66–91% |
| Hybrid + LLM (gpt-oss-120b), Top-1 | 22 / 33 | 67% | 50–80% |
| Plain RAG + LLM (gpt-5.4-mini), Top-1 | 15 / 33 | 45% | 30–62% |
| Blame the deployment, Top-1 | 12 / 33 | 36% | 22–53% |
| BM25 only, Top-1 | 6 / 33 | 18% | 9–34% |
| Embeddings only, Top-1 | 5 / 33 | 15% | 7–31% |
| Confirming tests, template | 31 / 33 | 94% | 80–98% |
| Confirming tests, LLM (gpt-5.4-mini) | 30 / 33 | 91% | 76–97% |
| Confirming tests, LLM (gpt-oss-120b, seed 0) | 3 / 11 | 27% | 10–57% |
| Action accuracy, Sentinel | 37 / 45 | 82% | 69–91% |
| Action accuracy, scale on every alert | 6 / 45 | 13% | 6–26% |

**How to read this.** The conclusions that survive the uncertainty: the hybrid beats the single-signal baselines (BM25,
embeddings, plain RAG: the intervals do not overlap), detection beats fixed thresholds, and evidence-driven action beats
scaling on every alert. The conclusions that do not: hybrid versus hybrid + LLM (85% vs 82%, intervals overlap almost
completely), template versus LLM tests, and the false-alarm rate (2 of 6 spans 10–70%). The rate "hybrid beats blame the
deployment" (85% vs 36%) is separated, but the 69–93% interval shows how loosely the 85% itself is known. This is why more
seeds are the first statistics item in the future scope.

## 3. Trade-offs we made

| Decision | Chosen | Alternative | What we gained | What it cost |
| --- | --- | --- | --- | --- |
| Telemetry source | In-process middleware | Prometheus + OpenTelemetry only | Per-route latency, exceptions with frames and request exemplars, which the later steps need; runs on a laptop | Services must install it; the platform also exports Prometheus metrics for the production view |
| Detector | Robust z-score vs the pre-change window | Fixed thresholds; trained anomaly model | Explainable, no training data, finds slow regressions | Needs a known change time; hand-set floors miss small faults (F09) |
| Retrieval | Hybrid with telemetry structure | Plain RAG over the repo | 85% vs 46% Top-1 | Needs a call graph and a deployment diff; Python only |
| LLM role | Re-ranker over structured candidates | LLM reads the repo and answers | Cheap, validated output (invented ids caught), no accuracy loss vs deterministic ranking | Adds latency (about 7 s) and cost for no Top-1 gain; kept optional |
| Weights | Fixed before the final runs | Tuned on results | No test-set tuning | Possibly sub-optimal; learning them is future work |
| Confirmation | Fail on faulty and pass on known-good | "Test fails" only | A test that fails on both proves nothing | Needs a known-good version |
| Platform runtime | Docker Engine + Compose | Kubernetes; plain processes | Fits one server, little RAM (about 470 MiB for the whole stack), reproducible | No multi-node scheduling; a process runtime is kept for laptops and tests |
| Automatic action | Rollback to last good only, once per incident | Auto-apply fixes; no automation | Safe, reversible, no history rewritten (rollback is a new commit) | Slow regressions are only proposed |
| State | SQLite | Postgres | One file, no extra service, easy backup | Single writer, single node |
| Entry point | Traefik with Docker labels | Nginx config per service | A new service is routed the moment its container starts | Another moving part; needed an upgrade for Docker 29 |
| Deploys | Restart button (build, health gate, swap) | Git push webhook | Simple and demonstrable without a CI server | No push-to-deploy yet |
| Docker access | Mount the socket | Socket proxy; rootless Docker | Simplest | Root-equivalent; listed as a limitation |

## 4. Research background

What the field already does, what we took from it, and where we differ. Items marked ✓ had their title, authors and venue
checked against a source while writing this document; the figures are from the abstracts. The rest are standard references
from memory: confirm the details before putting them in a report.

| Area | Work | What we use or contrast |
| --- | --- | --- |
| LLMs for cloud incident root cause | ✓ Chen et al., *Automatic Root Cause Analysis via Large Language Models for Cloud Incidents* (RCACopilot), EuroSys 2024 | Same idea of collecting diagnostic data first and then asking an LLM; they predict a root-cause **category** from handler-collected data, we trace to a **function** and confirm with a test |
| Benchmarks for AIOps agents | ✓ Chen et al., *AIOpsLab: A Holistic Framework to Evaluate AI Agents for Enabling Autonomous Clouds*, MLSys 2025 | Our lifecycle (detect, localise, mitigate) matches its task levels; a candidate external benchmark |
| RCA datasets | ✓ Pham et al., *RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data*, WWW 2025 companion (735 failure cases, 3 systems) | RE3 has code-level faults with stack traces; the natural public dataset to test our tracer. A 2026 preprint questions what the benchmark measures, so read that too |
| Safe deployment | ✓ Li et al., *Gandalf: An Intelligent, End-To-End Analytics Service for Safe Deployment in Large-Scale Cloud Infrastructure*, NSDI 2020 | Correlates fault signals with ongoing rollouts and halts bad ones. Our change-aware detector and rollback follow the same principle at tenant scale; they use production data from Azure, we use a synthetic benchmark |
| IR-based bug localisation | ✓ Zhou, Zhang, Lo, *Where should the bugs be fixed?* (BugLocator), ICSE 2012 | Ranks files by text similarity between report and code. Our BM25 and dense baselines are this family; we add runtime structure (stack frames, routes, call path, deployment diff) |
| Real Python bugs with tests | ✓ Widyasari et al., *BugsInPy*, ESEC/FSE 2020 (tool demo) | Each bug has a test that fails on the buggy and passes on the fixed version: the same definition of "confirming test". A dataset to evaluate our test generator |
| Retrieval-augmented generation | Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, NeurIPS 2020 | Our "plain RAG + LLM" baseline |
| Lexical retrieval | Robertson and Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond*, 2009 | Our BM25 retriever |
| Dense retrieval | Xiao et al., *C-Pack: Packaged Resources To Advance General Chinese Embedding* (BGE), 2023 | The embedding family of bge-small-en-v1.5 |
| Robust statistics | Iglewicz and Hoaglin, *How to Detect and Handle Outliers*, 1993 (MAD-based modified z-score); Theil 1950 and Sen 1968 (Theil–Sen slope) | Detector z-score and memory-leak test |
| Spectrum-based fault localisation | Jones and Harrold, *Empirical Evaluation of the Tarantula Automatic Fault-Localization Technique*, 2005 | Ranks statements using test pass/fail coverage. We rank with runtime telemetry instead, because production incidents have no failing test yet |
| Monitoring practice | Beyer et al., *Site Reliability Engineering*, O'Reilly 2016 | Golden signals (latency, traffic, errors, saturation) are the signals we track |
| LLM coding benchmarks | Jimenez et al., *SWE-bench*, ICLR 2024 | The closest "issue to code change" benchmark; ours adds a runtime incident as input |

**How we differ.** Existing work either classifies the root cause (a category or a service) or localises from a written bug
report. Sentinel starts from runtime telemetry on a shared server, names the **function**, and attaches a **test that fails
on the deployed code and passes on the last good one**. The contribution to claim is that combination, and the evidence for
it is the ablation: the deployment diff and the call graph carry the result, text similarity does not.

## 5. Why these models

| Component | Choice | Why | Evidence | Weakness |
| --- | --- | --- | --- | --- |
| Embeddings | BAAI/bge-small-en-v1.5 (384-d, ONNX, CPU) | Small, runs on a laptop and a 2-vCPU server without a GPU, strong for its size | Removing dense retrieval *raised* Top-1 to 91% on this benchmark | Not code-specific; larger code embeddings (for example jina-code, about 640 MB) untested |
| Lexical | Own BM25 | Strong on exact identifiers from stack traces and routes; transparent | Same ablation | Same |
| Primary LLM | OpenAI gpt-5.4-mini | Cheap enough to run on all 33 detected runs; supports JSON output | Re-rank 82% Top-1; tests 91% confirming | Exposes no temperature; returned empty answers on 3 test-generation runs |
| Comparison LLM | Groq gpt-oss-120b | Large open-weight model on a hosted free tier, so the result is not tied to one vendor | Re-rank 67%; tests 27% confirming (seed 0 only, rate limits) | Free-tier limits; weaker on tests |
| Dropped | qwen3.8-27b | Tried on Groq | Did not run reliably | Excluded and said so |

The pattern, not the model, is the finding. With both LLMs, re-ranking structured evidence beats plain RAG by 30 or more points
(82% vs 46%; 67% vs 36%). The weaker model gains less, so the LLM is an optional layer over the evidence, not a replacement
for it. The platform runs without any LLM key: it still deploys, detects, rolls back, and ranks suspects deterministically.

## 6. Workflow

How the team worked, and how the project is built:

1. **Specification before code.** Each large piece has a written design ([platform spec](superpowers/specs/2026-10-09-sentinel-platform-design.md),
   [console spec](superpowers/specs/2026-10-08-sentinel-console-design.md)) and a task plan
   ([platform plan](superpowers/plans/2026-10-09-sentinel-platform.md)).
2. **Tests first for the control plane.** 13 tasks; each started from a failing test. One deviation is recorded: the fix for
   promoting a regressed deployment to "last good" was written before its test, and the test was added immediately after.
3. **Measure, don't claim.** The benchmark has fixed weights, a development seed and two held-out seeds, and every run is
   reported.
4. **Continuous integration.** ruff and pytest on every push; on the platform side hadolint, `docker compose config`, image
   builds and a Trivy scan.
5. **Server deployment is reproducible.** `deploy/install.sh` or the three commands in the [RUNBOOK](RUNBOOK.md); the first
   real deployment found two server-only bugs, and both are fixed and recorded.
6. **Audit everything.** Each pipeline stage and each platform action writes an event.
7. **Human in the loop.** Sentinel proposes; a named person approves.

## 7. Scope: research question first

The comment that fits us best is the one about scope. The project has a research pipeline, a platform, an ops stack and a
UI, which can read like a long list of features, and a comparison of models is the easiest thing to mistake for the point.

**What the research question is not.** It is not "which LLM is best". The models are one ablation of one component (the
re-ranker), and the results say the LLM matters less than the evidence it is given.

**What it is.** *On a shared server, does telemetry-grounded hybrid code retrieval trace a runtime incident to the
responsible function, and confirm it with a generated test, better than the naive alternatives an operator would use?*
Four sub-questions (detection, localisation, test confirmation, action), four hypotheses, nine baselines, and an ablation
that says which evidence matters.

**Recommended framing for the report, viva and slides.**
1. One-sentence contribution: *a change-aware, telemetry-grounded tracer that names the faulty function and proves it with a
   test that fails on the deployed code and passes on the last good one.*
2. The platform is the **experimental and delivery vehicle**: it is the realistic setting in which the pipeline runs and the
   place a human approves the result. Present it after the results, in one or two slides, not before.
3. Lead with the evidence: the localisation table, the ablation (deployment diff −24 points, call graph −18) and the failure
   cases. Say what does not work: F07 and F09, 2 of 6 false alarms, and the wide intervals.
4. Do not present the LLM comparison as the finding. Present it as "the result holds across two models".
5. Be ready for: *why not just blame the last deployment?* (36%, and 85% with structure) and *how do you know it generalises?*
   (it has not been shown beyond the synthetic benchmark: that is the first item in the future scope).

**Biggest remaining threat to validity:** we wrote the faults, the decoys and the tracer. Running on RCAEval RE3 or BugsInPy
is the single most useful thing still to do for the research claim.
