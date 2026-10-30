# Industry research comparison: AIOps Sentinel

> **Source note.** This comparison was supplied by the team (`newResearch.md`). I checked RCACopilot's venue and claims against search results
> (EuroSys 2024; root-cause category prediction with LLMs on a year of Microsoft incidents). The other three papers' details, and the
> arXiv links, are as supplied and should be confirmed against the papers before they are quoted in a report.

## How to use this table

This comparison covers four industry-backed papers relevant to AIOps Sentinel. The intended claim is **not** that Sentinel is universally better than
Microsoft or Meta systems: those systems have much larger production deployments and datasets. Sentinel's contribution is a specific additional
capability: a controlled, auditable path from a runtime incident to function-level code evidence and a test that confirms the diagnosis across faulty and
known-good revisions.

| Research paper / industry context | What the paper does technically | What AIOps Sentinel takes from the same research direction | How Sentinel differs or adds capability | Why that difference matters in AI-DevOps |
| --- | --- | --- | --- | --- |
| **Automatic Root Cause Analysis via Large Language Models for Cloud Incidents (RCACopilot)**<br><br>Yinfang Chen et al., EuroSys 2024. Microsoft; one year of Microsoft incidents.<br>[arXiv 2305.15778](https://arxiv.org/pdf/2305.15778) | Starts from an alert, matches it to an incident handler, gathers diagnostic information, then uses an LLM to predict a root-cause category and write an explanation. | The same incident-response direction: start from operational signals, gather focused evidence rather than the whole system, and assist a human investigator. | Sentinel continues from incident evidence to a **specific candidate function**. It combines route anomalies, stack frames, request samples, Git diff lines, behavioural-change filtering, call paths, BM25 and dense retrieval, then generates a guarded regression test that must fail on the faulty version and pass on the known-good version. | An LLM explanation can be plausible without being true. Sentinel turns the hypothesis into an **executable artefact** a developer can rerun, and constrains the LLM to pre-ranked candidate functions. |
| **Automated Root Causing of Cloud Incidents using In-Context Learning with GPT-4**<br><br>Xuchao Zhang et al., 2024. Microsoft authors; 100,000 production incidents from an anonymised organisation.<br>[arXiv 2401.13810](https://arxiv.org/pdf/2401.13810) | In-context learning rather than fine-tuning: resolved historical incidents are supplied as examples; GPT-4 predicts the cause of a new incident. | The same aim of cutting on-call investigation time, and the recognition that an LLM needs incident-specific context. | Sentinel does not rely on historical examples or free-form inference. It performs deterministic detection and builds a structured evidence packet from the current deployment and telemetry. The LLM may only select known candidates, and the result is checked with a two-version test. | Historical examples may not match a new regression. Grounding in **current pre/post-change telemetry and the Git diff** gives a direct causal lead; the test is a stronger check than a predicted label. |
| **Exploring LLM-based Agents for Root Cause Analysis**<br><br>Devjeet Roy et al., FSE Companion 2024. Microsoft-affiliated; production incidents and a diagnostic-tools case study.<br>[arXiv 2403.04123](https://arxiv.org/pdf/2403.04123) | A **ReAct agent**: the LLM reasons, calls a retrieval or diagnostic tool, reads logs/metrics, and picks its next action. Dynamic evidence collection is the contribution. | The same evidence-grounded principle: inspect diagnostics, do not answer from general knowledge. | A bounded pipeline instead of an open agent loop: `detect → evidence packet → function ranking → optional LLM re-rank → guarded test → human approval`. Packet hashes and audit events are recorded, keys are stripped in the sandbox, and invented candidate ids are rejected. | Agent freedom makes cost, repeatability and auditability hard. Sentinel's investigation is **reproducible and measurable**: the same packet and ranking features can be rerun and benchmarked. |
| **Just-in-Time Catching Test Generation at Meta**<br><br>Matthew Becker et al., FSE Companion 2026. Meta production engineering.<br>[arXiv 2601.22832](https://arxiv.org/pdf/2601.22832) | Works **before deployment**: identifies risky diffs and generates catching tests; rule-based and LLM assessors reduce false positives before human review. | The same change-aware testing principle: a Git diff is evidence, generated tests should be executable, humans review high-impact findings. | Sentinel works **after an incident**, from observed latency/error/CPU/memory symptoms, failing request samples and the deployment diff. Its confirmation rule is explicit: fail by assertion on faulty code **and** pass on known-good code. | Meta stops risky changes reaching production. Sentinel closes the loop afterwards: operations telemetry becomes a developer-owned regression test. The two-version rule rejects tests that fail for unrelated reasons. |

## Feature-level summary

| Capability | RCACopilot | GPT-4 in-context RCA | LLM RCA agent | Meta JiT tests | AIOps Sentinel |
| --- | --- | --- | --- | --- | --- |
| Incident / alert investigation | Yes | Yes | Yes | No; pre-deployment | **Yes** |
| Telemetry or diagnostics | Yes | Incident context | Retrieved dynamically | No; source diff focused | **Yes: route, latency, errors, CPU, RSS, exceptions** |
| Git deployment diff evidence | Not the core method | Not the core method | Not the core method | Yes | **Yes, with behavioural-change filtering** |
| Function-level source-code candidate | No | No | Not the stated target | Diff-level test target | **Yes** |
| LLM usage | Root-cause category + explanation | In-context cause prediction | Tool-using reasoning agent | Test assessment/generation | **Optional constrained re-ranking and test writing** |
| Generated executable test | No | No | No | Yes, before deployment | **Yes, after incident** |
| Test must fail on faulty and pass on known-good version | No | No | No | Different pre-release objective | **Yes** |
| Human approval / review boundary | On-call assistance | Incident-owner evaluation | Human/diagnostic workflow | Engineer review | **Yes; no autonomous code change** |
| Executable policy per business journey (SLO, approvers, automatic actions) | not the focus | not the focus | not the focus | not the focus | **Yes: versioned policy packs** (added after review) |

## Presentation conclusion

> Microsoft research shows how LLMs can support SREs during production incident RCA, either by explaining incidents, learning from historical incident
> examples, or dynamically retrieving diagnostics. Meta shows how change-aware AI test generation can prevent risky code changes before deployment.
> AIOps Sentinel connects these directions in a post-incident DevOps loop: it uses runtime telemetry and deployment evidence to rank the likely faulty
> function, then creates a guarded regression test that confirms the diagnosis by failing on the faulty version and passing on the known-good version.
> The outcome is auditable and still requires human approval.

## Safe wording for questions

Use: **"Sentinel adds function-level, deployment-aware and test-verified RCA to the scope studied by these papers."**

Avoid: **"Sentinel is better than Microsoft or Meta."** Their systems have production-scale data and infrastructure that Sentinel does not claim to match.

## Where our evidence stands against this literature

* Those papers evaluate on large private incident sets. We evaluate on a 45-run synthetic benchmark we wrote, plus **independent public data** added after the review
  ([ENVIRONMENTS.md](ENVIRONMENTS.md)): RCAEval (375 real fault-injection cases, service-level only) and the Microsoft Cloud Monitoring Dataset (60 labelled production
  series, detection only), plus a replay service built from a real request log with an injected change.
* None of the public data contains code, so the function-level and confirming-test claims still rest on our own benchmark and the campus replay. Say that.
