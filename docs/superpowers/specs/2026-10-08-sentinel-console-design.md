# Sentinel Console — design

Status: draft for review. Date: 2026-10-08. Owner: whole team (build), presented live.

## Purpose

A local web panel that makes AIOps Sentinel's whole story visible in one place while it runs:
the shared server and its tenants, an incident being detected, traced to a function, proven with
a test and handed to a human, plus the measured benchmark results (including failures). It is shown
live to judges, so it must be accurate (real data only), robust (a replay mode that cannot fail),
and well designed (hand-made, dense, no template look).

Non-goals: user accounts, a database, mobile layout, running more than one scenario at once,
changing code or deploying anything.

## Constraints

* One command: `python -m panel` serves `http://127.0.0.1:8080`. `--port` overrides.
* No Node, no build step, no CDN. Works offline. Python deps already in `requirements.txt`.
* Reuse `sentinel/`, `benchmark/`, `evaluation/results/`; do not copy their logic. No changes to
  `sentinel/` behaviour. No ground truth is given to the tracer; the UI only reveals it after a diagnosis.
* The panel never writes outside `data/panel/` and the audit log. Approve writes an audit event only.

## Architecture

```text
browser (vanilla ES modules, SVG)  <-- SSE /api/events --  panel/server.py (FastAPI)
                                   --  REST /api/...   -->     |
                                                               +-- runner.live   starts services, traffic, deploy, analyze()
                                                               +-- runner.replay time-compressed playback of a saved run
                                                               +-- results       reads evaluation/results/*.json
                                                               +-- bus           in-memory event log + subscribers
```

### Files

| Path | Responsibility |
| --- | --- |
| `panel/__main__.py` | CLI: `python -m panel [--port]`, opens the browser |
| `panel/server.py` | FastAPI app, routes, static mount, SSE endpoint |
| `panel/bus.py` | `EventBus`: append-only list of events with an index; subscribers read from an index (late joiners get the history of the current run) |
| `panel/runner.py` | `LiveRun` and `ReplayRun`: produce the same event stream; one active run at a time |
| `panel/results.py` | Loads and shapes `summary.json` and `runs/*.json` for the Results screen |
| `panel/static/` | `index.html`, `app.css`, `js/{main,api,store,charts,code}.js`, `js/views/{floor,incident,trace,proof,decision,results,project}.js` |
| `tests/test_panel.py` | API and event-order tests in replay mode |

### Run modes (same events, same screens)

* **Live.** `LiveRun` composes existing blocks: `benchmark.workspace.build/deploy`, `benchmark.record.start_service/wait_ready`,
  `benchmark.load.run`, `sentinel.telemetry.Collector`, `sentinel.pipeline.analyze`. It polls
  `Collector.samples` every 0.5 s to emit `telemetry` events and tails the run's audit JSONL to emit
  `stage` events as `analyze()` writes them. When `analyze()` returns, it emits `result`. About 2 minutes.
* **Replay.** `ReplayRun` reads `data/bench/<id>-s<seed>.json` (telemetry), `evaluation/results/runs/<id>-s<seed>.json`
  (suspects, tests, action) and `evaluation/results/audit/<id>-s<seed>.jsonl`, and re-emits them on a
  compressed clock (about 40 s). No services, ports or LLM calls. It is the demo safety net and the
  default when Live preconditions fail.

### Event stream (`GET /api/events?since=<n>`, server-sent events)

Every event: `{n, t, kind, data}` where `n` is a monotonically increasing index within the run.

| kind | data |
| --- | --- |
| `run` | `{id, scenario, mode, seed, llm, started}` and `{state: done|failed, reason}` at the end |
| `service` | `{name, owner, up, pid}` per tenant state change |
| `telemetry` | `{t, service, routes:{route:{count,errors,p95_ms}}, cpu, rss_mb}` one per scrape |
| `deploy` | `{commits:[message], restarted:[service]}` |
| `stage` | `{stage: detect|context|trace|test|handoff, decision, ...audit fields}` |
| `result` | the `analyze()` result plus `truth` (revealed only here), changed-line ranges and the commit list |

`GET /api/state` returns the current run's full event list plus tenant info, so a refreshed page recovers.

### REST

| Route | Purpose |
| --- | --- |
| `GET /api/scenarios` | Catalog: id, title, service, fault class, expected action (no file/line ground truth) |
| `POST /api/run` | `{scenario, mode: live|replay, llm: bool, seed}` → starts a run; 409 if one is active |
| `GET /api/state` | Current run snapshot (above) |
| `GET /api/results` | Shaped benchmark results: summary, per-scenario grid, ablation, failures |
| `GET /api/code?path=&run=` | Source of a file in the run's deployed workspace; 404 if unavailable; path must stay inside the workspace |
| `POST /api/approve` | `{approver, note}` → appends an audit event `handoff/approved`; never changes code |
| `GET /api/audit?run=` | The run's audit events |

## Screens

A left rail switches views; a top bar always shows server name, mode switch (Live | Replay), scenario
picker, LLM toggle, Run, and run state. All views read one client-side store fed by the event stream.

1. **Live floor.** Three tenant tiles (orders, inventory, payments): up/down, owner, requests/s, p95
   sparkline (last 60 s), CPU, RSS. Under them, the six-step pipeline strip (collect, detect, packet,
   index+trace, test, hand-off), each lighting up with its elapsed time and a one-line result.
2. **Incident.** Telemetry chart of the affected route with the deployment marked, the baseline band
   (median ± robust scale) shaded and the anomalous window highlighted; a table of signals (baseline →
   observed, z, buckets); a "fixed threshold alert" lane showing whether the baseline detector fired.
3. **Trace.** Ranked suspects; each row has a stacked bar of the seven feature contributions and its
   reasons. A code viewer shows the top suspect with changed lines marked. The call path (route →
   handler → callee chain) is drawn as a small graph. The commit list marks which commit touched the
   suspect. After the result arrives, a "ground truth" chip shows whether the rank-1 suspect overlaps
   the real faulty lines.
4. **Proof.** For each generator (template, LLM): the generated test source, the guard verdict, and two
   result cards: on the faulty code (expected red) and on the known-good code (expected green); a
   "confirming" badge only when both hold.
5. **Decision.** Recommended action, confidence, why (evidence ticks), owner, and an Approve control
   that asks for a name and writes the audit event. Below, the audit trail as a vertical timeline with
   stage, decision, packet digest, model, tokens and latency.
6. **Results.** From `/api/results`: detection (robust vs thresholds, by class), localisation bars for
   every method and LLM, ablation, test confirmation rates, action accuracy; a scenario × method grid
   where each cell is the rank of the true function (1 = green … miss = red) across seeds, and a
   "what failed" list (F09 undetected, F07 mis-ranked, false alarms, empty LLM answers).
7. **Project.** Research question, hypotheses, the six steps with tools, and who owns what.

## Visual design

Dark graphite background, one restrained accent set from our deck (indigo, orange, green; red only for
failure). Dense layout on an 8 px grid, large numerals for headline stats, monospace for every measured
value, small caps labels. Cards use hairline borders and subtle depth, not glass or neon. Motion only on
state change: a tile value ticks, a pipeline stage fills, a row slides into rank. Charts are hand-built
SVG (crisp, themeable, no library). Fonts are the system stack (Segoe UI Variable / system-ui, Cascadia
Mono / ui-monospace). Light theme is out of scope. Minimum window 1280×720; verified at that size and 1920×1080.

## Errors and edge cases

| Situation | Behaviour |
| --- | --- |
| Port 9101-9103 busy / service fails to start | Live run fails fast with the reason; the UI offers Replay |
| No LLM key | LLM stages marked "skipped"; deterministic steps run; template test still runs |
| Service dies mid-run | Tile turns red; run ends `failed` with the reason; replay still available |
| Browser refresh / second tab | `/api/state` restores the run; events continue from the last index |
| Recording or workspace missing for Replay | That scenario is greyed out with the missing path; others work |
| Live and Replay both unavailable | The Results and Project screens still work (they only need `evaluation/results/`) |
| `GET /api/code` path escapes the workspace | 400 |

## Testing

* `tests/test_panel.py` (TestClient, replay mode, no network): scenario catalog hides line-level truth;
  a replay emits `run` → `service`/`telemetry` → `stage` (in order detect, context, trace, test, handoff) →
  `result` → `run done`; second `POST /api/run` during a run returns 409; `/api/approve` appends an audit
  event and leaves the workspace unchanged; `/api/code` rejects `../` paths; `/api/results` matches
  `summary.json`.
* Manual end to end: one Live run (F01) and one Live control (H03); one Replay of every scenario.
* Visual QA: screenshots of all seven views at 1280×720 and 1920×1080 during a replay; check overflow,
  contrast, alignment, truncated numbers.

## Open decisions (defaults chosen)

* Replay speed: 3× the real timeline, not instant, so the story is followable. A speed control is a
  non-goal. Replay shows what was recorded, including the LLM stages; the LLM toggle applies to Live only
  and is disabled in Replay.
* Approver name is free text; no authentication (local demo).
* Port 8080; if busy, fail with a message (no auto-increment, so the demo URL is predictable).
