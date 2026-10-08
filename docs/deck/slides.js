// Slide content. Numbers come from evaluation/results/summary.json via `S`.
const { pres, S, HEX, COL, THEME, OUT, pct, num, section, content, card, badge, text, bullets, stat, table, barChart, arrow, applyTheme } = require("./build_deck.js");

const D = S.detection, L = S.localization, T = S.tests, A = S.action;
const nFault = S.fault_runs, nControl = S.control_runs, seeds = S.seeds.length;
const loc = (m, k = "top1") => (L[m] ? L[m][k] : undefined);
const MODEL_LABEL = { "": "gpt-5.4-mini", "@gptoss": "gpt-oss-120b" };

// =============================================================== 1. Title
{
  const s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: section("Introduction") });
  [HEX.teal, HEX.amber, HEX.purple].forEach((c, i) => s.addShape(pres.shapes.OVAL, { x: 0.9 + i * 0.5, y: 0.7, w: 0.3, h: 0.3, fill: { color: c }, line: { color: c }, objectName: "motif" }));
  text(s, "PROJECT REVIEW", { x: 0.9, y: 1.5, w: 8, h: 0.35, fontSize: 14, bold: true, color: HEX.amber, charSpacing: 4 });
  text(s, "AIOps Sentinel", { x: 0.9, y: 1.95, w: 11.5, h: 1.1, fontFace: "Cambria", fontSize: 60, bold: true, color: HEX.white });
  text(s, "Tracing shared-server incidents back to the code that caused them", { x: 0.9, y: 3.2, w: 11.5, h: 0.6, fontSize: 26, color: "D6DAEA" });
  text(s, "Monitor every tenant, find the faulty function, prove it with a generated test; a human approves any fix", { x: 0.9, y: 4.2, w: 11.5, h: 0.5, fontSize: 18, italic: true, color: "A0A6BC" });
  const people = [["P1", "Akash", "Monitoring, registry, detection", HEX.teal], ["P2", "Aryan", "Evidence packet, code index, tracing", HEX.amber], ["P3", "Syna", "Test generation, LLM, evaluation", HEX.purple]];
  people.forEach(([p, name, role, c], i) => {
    const x = 0.9 + i * 3.95;
    s.addShape(pres.shapes.OVAL, { x, y: 5.45, w: 0.5, h: 0.5, fill: { color: c }, line: { color: c }, objectName: "team badge" });
    text(s, p, { x, y: 5.45, w: 0.5, h: 0.5, fontFace: "Cambria", fontSize: 14, bold: true, color: c === HEX.amber ? HEX.ink : HEX.white, align: "center", valign: "middle" });
    text(s, name, { x: x + 0.65, y: 5.42, w: 3.2, h: 0.32, fontSize: 16, bold: true, color: HEX.white });
    text(s, role, { x: x + 0.65, y: 5.74, w: 3.2, h: 0.3, fontSize: 12, color: "A0A6BC" });
  });
  s.addNotes("One sentence: Sentinel watches a shared server, and when one tenant breaks it does not just scale it; it finds the function that caused the problem and proves it with a test. Each of us presents one part; the coloured pill on each slide shows who.");
}

// =============================================================== 2. Problem
{
  const s = content("Introduction", "Problem statement", "An alert says something is wrong, not where", "team",
    "Three problems: shared servers hide which tenant is in trouble, scaling hides code faults, and an unproven AI diagnosis is risky.");
  const cards = [
    ["Shared servers hide the tenant", "Host CPU and latency rise for everyone. Which of the services on the box broke, and which function inside it?"],
    ["Scaling hides code faults", "Adding replicas to an N+1 query or a memory leak buys time and money, but the bug ships to every replica."],
    ["Unproven diagnoses are risky", "An LLM can name a plausible cause with confidence. Without evidence a human can rerun, nobody should act on it."],
  ];
  cards.forEach(([h, b], i) => {
    const x = 0.6 + i * 4.13;
    card(s, x, 1.9, 3.7, 3.55);
    badge(s, i + 1, x + 0.3, 2.2);
    text(s, h, { x: x + 0.3, y: 2.9, w: 3.15, h: 0.9, fontFace: "Cambria", fontSize: 22, bold: true });
    text(s, b, { x: x + 0.3, y: 3.85, w: 3.15, h: 1.5, fontSize: 15, color: COL.muted });
  });
  text(s, "Opportunity: join telemetry, logs and the deployment diff to rank the responsible function, then confirm it with a test that fails now and passes once the cause is reverted.",
    { x: 0.6, y: 5.8, w: 12.1, h: 0.75, fontSize: 18, italic: true, color: COL.teal });
}

// =============================================================== 3. v0 audit
{
  const s = content("Introduction", "Where we started", "We rebuilt v0 because it could not be measured", "team",
    "Be candid: the first prototype looked like it worked but every hard part was hard-coded. This slide is why everything after it is new.");
  table(s, ["v0 prototype", "Why it failed", "v1 (this review)"], [
    ["Incident question hard-coded the answer (\"inspect /orders ... N+1\")", "Circular: the diagnosis was given, not found", "Query built only from telemetry, exceptions and diff"],
    ["Model saw 1 chunk, cut to 360 characters", "The cause was rarely in front of the model", "Evidence packet + top-8 function-level candidates"],
    ["Hashed bag-of-words over 44-line windows", "20% file hit rate on its own question set", "AST chunks, BM25 + bge-small, call graph"],
    ["Fixed thresholds on one demo app", "No tenant attribution, misses slow faults", "Per-route, per-process, change-aware robust z"],
    ["\"Generated test\" was a fixed string testing the fast path", "Could never confirm anything", "Test must fail on faulty code and pass on known-good code"],
    ["25 questions about Sentinel's own code", "No ground truth, no baseline", `12 injected faults + 3 controls x ${seeds} seeds, 6+ baselines`],
  ], { x: 0.6, y: 1.75, w: 12.1, colW: [4.2, 3.6, 4.3], fontSize: 13 });
  stat(s, 0.6, 5.05, 5.95, pct(L.legacy_v0.top1), "v0 retriever: faulty function ranked first", "on the same incidents as v1, kept as a baseline", HEX.red);
  stat(s, 6.75, 5.05, 5.95, pct(L.hybrid.top1), "v1 hybrid tracer: faulty function ranked first", `${L.hybrid.n} detected fault runs, ${seeds} seeds`);
}

// =============================================================== 4. Objectives + ownership
{
  const s = content("Introduction", "Objectives", "Four objectives, one of them is restraint", "team",
    "Stress objective four: recommending capacity only when there is no code evidence, and staying quiet on harmless deployments, is part of the result.");
  const objs = [
    ["Attribute", "Turn shared-server telemetry into an incident for one service, one route and one owner."],
    ["Trace", "Rank the functions of that service by evidence and name the most likely cause, with reasons."],
    ["Confirm", "Generate a test that fails on the deployed code and passes on the known-good code, in a sandbox."],
    ["Restrain", "No code evidence means no code fix: recommend capacity or investigation instead; a human approves anything."],
  ];
  objs.forEach(([h, b], i) => {
    const x = 0.6 + (i % 2) * 6.15, y = 1.8 + Math.floor(i / 2) * 2.15;
    card(s, x, y, 5.95, 1.95);
    badge(s, i + 1, x + 0.3, y + 0.3);
    text(s, h, { x: x + 1.0, y: y + 0.3, w: 4.7, h: 0.5, fontFace: "Cambria", fontSize: 20, bold: true });
    text(s, b, { x: x + 1.0, y: y + 0.82, w: 4.7, h: 1.0, fontSize: 15, color: COL.muted });
  });
  card(s, 0.6, 6.15, 12.1, 0.6, COL.mint);
  text(s, "Owners:  P1 Akash  steps 1-2 detection   |   P2 Aryan  steps 3-5 tracing   |   P3 Syna  step 6 tests + evaluation",
    { x: 0.85, y: 6.15, w: 11.7, h: 0.6, fontSize: 14, valign: "middle" });
}

// =============================================================== 4b. Responsibilities
{
  const s = content("Introduction", "Team responsibilities", "Who built and presents what", "team",
    "Each person owns a part end to end: code, experiment and slides. Everyone has run the whole pipeline and can explain every part.");
  const people = [
    ["P1  Akash", COL.teal, COL.white, "Steps 1-2: see and attribute", [
      "Telemetry middleware and collector", "Service registry (services.yaml)", "Robust detector + threshold baseline",
      "Load generator and live recorder", "Results: detection, false alarms"], "common/telemetry.py, sentinel/telemetry.py, registry.py, detection.py"],
    ["P2  Aryan", COL.amber, COL.ink, "Steps 3-5: explain", [
      "Evidence packet, git diff + blame, behavioural diff", "AST index, BM25, embeddings, call graph",
      "Hybrid tracer, LLM re-rank, action decision", "Results: localisation, ablations, 2 LLMs"], "sentinel/context.py, indexing.py, tracing.py"],
    ["P3  Syna", COL.purple, COL.white, "Step 6 + evaluation: prove", [
      "Template and LLM test generators", "Test guard and sandbox (fail faulty, pass good)", "LLM client: OpenAI / Groq, cache",
      "Fault catalog, benchmark harness, scoring", "Results: confirming tests, actions"], "sentinel/testgen.py, llm.py, benchmark/, evaluation/"],
  ];
  people.forEach(([who, fill, tc, role, items, files], i) => {
    const x = 0.6 + i * 4.13;
    card(s, x, 1.75, 3.7, 4.55);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.3, y: 1.95, w: 1.5, h: 0.38, rectRadius: 0.19, fill: { color: fill }, line: { color: fill } });
    text(s, who, { x: x + 0.3, y: 1.95, w: 1.5, h: 0.38, fontSize: 13, bold: true, color: tc, align: "center", valign: "middle" });
    text(s, role, { x: x + 0.3, y: 2.5, w: 3.15, h: 0.45, fontFace: "Cambria", fontSize: 18, bold: true });
    bullets(s, items, { x: x + 0.3, y: 3.05, w: 3.15, h: 2.4, fontSize: 14 });
    text(s, files, { x: x + 0.3, y: 5.55, w: 3.15, h: 0.6, fontSize: 10, fontFace: "Courier New", color: COL.muted });
  });
  card(s, 0.6, 6.45, 12.1, 0.42, COL.mint);
  text(s, "Shared: audit trail, guardrails, pipeline wiring, docs. Every member can run python -m benchmark.demo F01 and explain each step.", { x: 0.85, y: 6.45, w: 11.6, h: 0.42, fontSize: 13, valign: "middle" });
}

// =============================================================== 5. Research question
{
  const s = content("Introduction", "Research question", "Research question", "team",
    "Read the main question aloud. Each presenter reads their own sub-question when their section starts.");
  card(s, 0.6, 1.65, 12.1, 1.55, COL.ink);
  text(s, "On a shared server, can telemetry-grounded hybrid code retrieval, with an LLM, trace a runtime incident to the responsible function and confirm it with a generated test, better than the naive alternatives: fixed alerts, blaming the latest deployment, plain vector RAG, or scaling?",
    { x: 1.0, y: 1.65, w: 11.3, h: 1.55, fontFace: "Cambria", fontSize: 21, color: COL.white, valign: "middle" });
  const subs = [
    ["P1", "Does a change-aware robust detector name the right tenant more often than fixed thresholds, without more false alarms?", COL.teal, COL.white],
    ["P2", "Does fusing routes, call graph, stack frames and a behavioural diff with BM25 + embeddings rank the faulty function first more often?", COL.amber, COL.ink],
    ["P3", "Can a generated test confirm the diagnosis: fail on the faulty code and pass on the known-good code?", COL.purple, COL.white],
  ];
  subs.forEach(([p, q, c, tc], i) => {
    const x = 0.6 + i * 4.13;
    card(s, x, 3.45, 3.7, 1.95);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.25, y: 3.6, w: 0.75, h: 0.32, rectRadius: 0.16, fill: { color: c }, line: { color: c } });
    text(s, p, { x: x + 0.25, y: 3.6, w: 0.75, h: 0.32, fontSize: 12, bold: true, color: tc, align: "center", valign: "middle" });
    text(s, q, { x: x + 0.25, y: 4.0, w: 3.25, h: 1.35, fontSize: 14 });
  });
  card(s, 0.6, 5.6, 12.1, 1.15, COL.mint);
  text(s, [
    { text: "H1 ", options: { bold: true } }, { text: "robust detection beats fixed thresholds.   " },
    { text: "H2 ", options: { bold: true } }, { text: "the hybrid tracer beats every single-signal baseline on Top-1.   " },
    { text: "H3 ", options: { bold: true } }, { text: "an LLM helps as a re-ranker over structured evidence more than as plain RAG.   " },
    { text: "H4 ", options: { bold: true } }, { text: "most generated tests are confirming, and unsafe tests are blocked." },
  ], { x: 0.85, y: 5.65, w: 11.7, h: 1.05, fontSize: 14, valign: "middle" });
}

// =============================================================== 6. System design
{
  const s = content("Method", "Methodology: system design", "Six steps from telemetry to a confirming test", "team",
    "Walk left to right. Teal boxes are built and evaluated. Dashed boxes are designed but deliberately not automated: fix PR, CI/CD rollout and post-deploy watch. Audit is written at every step.");
  const boxes = [
    [0.6, 2.0, "1  Collect", "per-route, per-process"], [2.75, 2.0, "2  Detect", "robust z, change-aware"],
    [4.9, 2.0, "3  Evidence packet", "signals, errors, diff"], [7.05, 2.0, "4  Code index", "AST, BM25, bge-small"],
    [9.2, 2.0, "5  Trace", "hybrid + LLM re-rank"], [9.2, 3.85, "Action decision", "fix / scale / investigate"],
    [7.05, 3.85, "6  Confirming test", "template or LLM"], [4.9, 3.85, "Sandbox", "fail faulty, pass good"],
    [2.75, 3.85, "Owner approves", "named human"],
  ];
  boxes.forEach(([x, y, h, b]) => {
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 1.95, h: 1.15, fill: { color: COL.teal }, line: { color: COL.teal } });
    text(s, h, { x: x + 0.1, y: y + 0.15, w: 1.75, h: 0.45, fontSize: 15, bold: true, color: COL.white, align: "center" });
    text(s, b, { x: x + 0.1, y: y + 0.62, w: 1.75, h: 0.4, fontSize: 12, color: "DDE2F5", align: "center" });
  });
  [[2.55, 2.75], [4.7, 4.9], [6.85, 7.05], [9.0, 9.2]].forEach(([a, b]) => arrow(s, a, 2.575, b, 2.575));
  arrow(s, 10.175, 3.15, 10.175, 3.85);
  [[9.2, 9.0], [7.05, 6.85], [4.9, 4.7]].forEach(([a, b]) => arrow(s, a, 4.425, b, 4.425));
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 3.85, w: 1.95, h: 1.15, fill: { color: COL.white }, line: { color: HEX.amber, width: 1.5, dashType: "dash" } });
  text(s, "7-10  Fix PR, CI/CD, rollout", { x: 0.7, y: 3.95, w: 1.75, h: 0.95, fontSize: 13, bold: true, align: "center", valign: "middle" });
  arrow(s, 2.75, 4.425, 2.55, 4.425);
  card(s, 11.35, 2.0, 1.35, 3.0, COL.mint);
  text(s, "Audit JSONL at every step", { x: 11.4, y: 2.1, w: 1.25, h: 2.8, fontSize: 13, bold: true, align: "center", valign: "middle" });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 5.6, w: 0.45, h: 0.3, fill: { color: COL.teal }, line: { color: COL.teal } });
  text(s, "Built and evaluated", { x: 1.15, y: 5.6, w: 2.5, h: 0.3, fontSize: 13, color: COL.muted, valign: "middle" });
  s.addShape(pres.shapes.RECTANGLE, { x: 3.9, y: 5.6, w: 0.45, h: 0.3, fill: { color: COL.white }, line: { color: HEX.amber, width: 1.25, dashType: "dash" } });
  text(s, "Designed, not automated (by choice)", { x: 4.45, y: 5.6, w: 4, h: 0.3, fontSize: 13, color: COL.muted, valign: "middle" });
  text(s, "Sentinel never edits code, restarts or scales anything. Its output is a diagnosis, a confirming test and a recommended action.", { x: 0.6, y: 6.2, w: 12.1, h: 0.45, fontSize: 15, italic: true, color: COL.teal });
}

// =============================================================== 7. Benchmark
{
  const s = content("Method", "Experiment: the benchmark", "Real faults, real deployments, known answers", "P1",
    "The faults are real code changes deployed through git, hidden among decoy commits, under the same traffic before and after. Because we wrote the faulty commit, we know the exact faulty lines, and reverting it gives a known-good version.");
  const steps = [["Start", "3 FastAPI tenants on one machine: orders, inventory, payments"], ["Baseline", "20 s of mixed traffic, including awkward inputs"],
    ["Deploy", "4 git commits: 1 fault + 3 decoys, seeded order, >=1 decoy in the same service"], ["Incident", "restart changed services, same 20 s traffic (4x on orders for H03)"]];
  steps.forEach(([h, b], i) => {
    const x = 0.6 + i * 3.1;
    card(s, x, 1.8, 2.8, 1.75);
    badge(s, i + 1, x + 0.25, 1.98);
    text(s, h, { x: x + 0.9, y: 2.02, w: 1.8, h: 0.45, fontFace: "Cambria", fontSize: 19, bold: true });
    text(s, b, { x: x + 0.25, y: 2.6, w: 2.35, h: 0.9, fontSize: 13, color: COL.muted });
    if (i < 3) arrow(s, x + 2.8, 2.675, x + 3.1, 2.675);
  });
  stat(s, 0.6, 3.9, 3.9, "12", "injected faults", "latency, CPU, memory, errors across 3 services");
  stat(s, 4.7, 3.9, 3.9, "3", "controls", "docs-only deploy, neutral refactor, 4x traffic surge");
  stat(s, 8.8, 3.9, 3.9, String(S.runs), "live recordings", `${seeds} seeds; seed 0 = development, others held out`);
  card(s, 0.6, 5.5, 12.1, 1.2, COL.mint);
  text(s, "Ground truth per fault: the faulty file and line range (from the patch) and a known-good version (the deployment with only the faulty commit reverted). The registry (services.yaml) maps every path and process to a service and an owner.",
    { x: 0.85, y: 5.55, w: 11.6, h: 1.1, fontSize: 14, valign: "middle" });
}

// =============================================================== 8. Fault catalog
{
  const s = content("Method", "Experiment: fault catalog", "Twelve realistic faults and three controls", "P1",
    "Each fault is a plausible commit with an innocent message. Read two or three rows; point out that F05 is a config change and F09 only shows up under concurrency.");
  const rows = [
    ["F01", "orders", "N+1 customer lookup per order", "latency"], ["F02", "orders", "quadratic bundle-discount loop", "cpu"],
    ["F03", "inventory", "unbounded view history", "memory"], ["F04", "inventory", "KeyError on unknown SKU", "errors"],
    ["F05", "payments", "gateway timeout raised 10x (config)", "latency"], ["F06", "payments", "connection pool bypassed", "latency"],
    ["F07", "payments", "catastrophic regex backtracking", "cpu"], ["F08", "orders", "whole table serialised per request", "cpu"],
  ];
  const rows2 = [
    ["F09", "inventory", "lock held during audit write", "latency"], ["F10", "orders", "division by zero on empty cart", "errors"],
    ["F11", "payments", "refund reason assumed present", "errors"], ["F12", "orders", "full table scan on order lookup", "latency"],
    ["H01", "payments", "docs-only deployment", "control"], ["H02", "inventory", "behaviour-neutral refactor", "control"],
    ["H03", "orders", "4x traffic surge, no code change", "capacity"],
  ];
  table(s, ["Id", "Service", "Fault", "Class"], rows, { x: 0.6, y: 1.75, w: 5.95, colW: [0.6, 1.15, 3.2, 1.0], fontSize: 12 });
  table(s, ["Id", "Service", "Fault / control", "Class"], rows2, { x: 6.75, y: 1.75, w: 5.95, colW: [0.6, 1.15, 3.2, 1.0], fontSize: 12 });
  text(s, "Commit messages are innocent (\"Load customer profile next to each order\"), so the message alone does not give the answer away.", { x: 0.6, y: 6.25, w: 12.1, h: 0.45, fontSize: 14, italic: true, color: COL.teal });
}

// =============================================================== 9. Detection method
{
  const s = content("Akash: detection", "Methodology: steps 1-2", "Per-tenant telemetry, robust detection", "P1",
    "Telemetry is per route and per process, so every signal has an owner. The detector compares after the change with before, robustly, and must see a sustained shift.");
  card(s, 0.6, 1.75, 5.95, 4.45);
  text(s, "1  Collect (every second)", { x: 0.85, y: 1.9, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: COL.teal });
  bullets(s, ["Per route: p50 / p95 / max latency and 5xx count (FastAPI middleware)", "Per process: CPU % and RSS of each tenant (psutil)",
    "Exceptions with stack frames inside our code", "Up to 20 slow or failed requests + 1 normal request per route, for replay in step 6",
    "services.yaml: path, port and owner of every tenant"], { x: 0.85, y: 2.5, w: 5.5, h: 3.6, fontSize: 15 });
  card(s, 6.75, 1.75, 5.95, 4.45);
  text(s, "2  Detect (after vs before the change)", { x: 7.0, y: 1.9, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: COL.teal });
  bullets(s, ["Robust z = (x - median) / max(1.4826 MAD, floor), fire at z >= 6", "Plus a minimum real change: latency +15 ms and +50%, errors +2 pp, CPU +15",
    ">= 3 anomalous buckets, and 30 pp more often than before the change (stops bursty routes)", "Memory: >= 10 MiB growth with positive Theil-Sen slope",
    "Traffic up alone is not an incident; too little data is \"cannot conclude\""], { x: 7.0, y: 2.5, w: 5.5, h: 3.6, fontSize: 15 });
  text(s, "Baseline: fixed alert rules (p95 > 500 ms, errors > 5%, CPU > 80%, RSS > 500 MiB), no baseline period, no persistence.", { x: 0.6, y: 6.35, w: 12.1, h: 0.4, fontSize: 14, italic: true, color: COL.teal });
}

// =============================================================== 10. Detection results
{
  const r = D.robust, t = D.threshold;
  const s = content("Akash: detection", "Results: detection", "Robust detection versus fixed alert thresholds", "P1",
    `Fault recall is over ${nFault} fault runs; false alarms over the quiet controls H01 and H02. Explain why thresholds miss: most faults raise latency from single-digit milliseconds to around 100 ms, far under a 500 ms alert.`);
  barChart(s, ["Fault recall", "Right service first", "False alarms (quiet controls)"],
    [{ name: "Robust detector", values: [r.fault_recall, r.correct_service_top1, r.false_alarm_rate_quiet_controls], color: HEX.teal },
     { name: "Fixed thresholds", values: [t.fault_recall, t.correct_service_top1, t.false_alarm_rate_quiet_controls], color: HEX.amber }],
    { x: 0.6, y: 1.7, w: 7.0, h: 4.6 });
  const classes = Object.keys(r.by_class);
  table(s, ["Fault class", "Robust", "Threshold"], classes.map((c) => [c, pct(r.by_class[c]), pct(t.by_class[c])]),
    { x: 7.9, y: 1.85, w: 4.8, colW: [2.0, 1.4, 1.4], fontSize: 13 });
  card(s, 7.9, 4.35, 4.8, 1.95, COL.mint);
  text(s, S.notes && S.notes.detection ? S.notes.detection : "", { x: 8.1, y: 4.45, w: 4.4, h: 1.75, fontSize: 14, bold: true, valign: "middle" });
  text(s, `n = ${nFault} fault runs, ${nControl} control runs (${seeds} seeds).`, { x: 0.6, y: 6.4, w: 7, h: 0.35, fontSize: 11, color: COL.muted });
}

// =============================================================== 11. Packet + index
{
  const s = content("Aryan: tracing", "Methodology: steps 3-4", "Evidence packet and a structure-aware index", "P2",
    "The packet is what the model is allowed to see, and its hash is in the audit trail. The index splits code the way a human would name a cause: by function.");
  card(s, 0.6, 1.75, 5.95, 4.6);
  text(s, "3  Evidence packet", { x: 0.85, y: 1.9, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: HEX.amber });
  bullets(s, ["Anomalous signals and routes of one service, its owner and code path", "Exceptions in the window, grouped, with stack frames",
    "Slow / failed request samples and one normal request per route", "Deployment: commits, changed line ranges (git diff + blame)",
    "Behavioural-diff flag: did the syntax tree change once comments and docstrings are removed?", "Redaction of secrets and card numbers; SHA-256 digest for the audit trail"],
    { x: 0.85, y: 2.5, w: 5.5, h: 3.8, fontSize: 15 });
  card(s, 6.75, 1.75, 5.95, 4.6);
  text(s, "4  Code index", { x: 7.0, y: 1.9, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: HEX.amber });
  bullets(s, ["Python ast: one chunk per function / method / module block, with line range", "Routes from decorators: @app.get(\"/orders\") -> handler",
    "Call / reference graph from names each chunk calls or reads", "Lexical: BM25 over identifier-aware tokens (load_customer -> load, customer)",
    "Dense: BAAI/bge-small-en-v1.5 (384-d, ONNX on CPU via fastembed)", "Only code of the affected tenant (+ shared code) is searched"],
    { x: 7.0, y: 2.5, w: 5.5, h: 3.8, fontSize: 15 });
}

// =============================================================== 12. Tracing method
{
  const s = content("Aryan: tracing", "Methodology: step 5", "Seven pieces of evidence, one ranked list", "P2",
    "Weights were set before running the benchmark, from how strong each kind of evidence is, and never tuned on results. The LLM only re-orders the top eight and must cite candidate ids.");
  table(s, ["Feature", "Meaning", "Weight"], [
    ["trace", "contains a stack frame of a logged exception", "2.5"], ["call_path", "reachable from an anomalous route handler (1 / depth)", "1.5"],
    ["changed_lines", "overlaps a behaviour-changing line of the deployment", "1.5"], ["route", "is the handler of an anomalous route", "1.0"],
    ["lexical", "BM25 of the incident query", "1.0"], ["dense", "embedding similarity of the same query", "1.0"], ["changed_file", "same file as a change, other lines", "0.3"],
  ], { x: 0.6, y: 1.75, w: 7.2, colW: [1.6, 4.7, 0.9], fontSize: 13 });
  card(s, 8.0, 1.75, 4.7, 2.35);
  text(s, "LLM re-rank (optional)", { x: 8.25, y: 1.88, w: 4.3, h: 0.45, fontFace: "Cambria", fontSize: 18, bold: true, color: HEX.amber });
  bullets(s, ["Top 8 candidates with code and evidence tags", "JSON only; must use candidate ids; invalid -> deterministic list", "Packet is data, not instructions"],
    { x: 8.25, y: 2.4, w: 4.3, h: 1.65, fontSize: 13 });
  card(s, 8.0, 4.3, 4.7, 2.05, COL.mint);
  text(s, "Action decision", { x: 8.25, y: 4.4, w: 4.3, h: 0.4, fontFace: "Cambria", fontSize: 18, bold: true });
  text(s, "code_fix only with code evidence on the call path; capacity_scale only if traffic rose and no code evidence; otherwise investigate.", { x: 8.25, y: 4.85, w: 4.3, h: 1.4, fontSize: 13 });
  text(s, "Incident query = symptom words + anomalous route paths + exception messages. Nothing from the answer is in it.", { x: 0.6, y: 6.3, w: 7.2, h: 0.45, fontSize: 13, italic: true, color: COL.teal });
}

// =============================================================== 13. Localization results
{
  const order = [["legacy_v0", "v0 retriever"], ["recent_changes", "Blame deploy"], ["bm25", "BM25"], ["dense", "Dense"], ["rag_llm", "RAG + LLM"], ["hybrid", "Hybrid"], ["hybrid_llm", "Hybrid + LLM"]].filter(([m]) => L[m]);
  const s = content("Aryan: tracing", "Results: localisation", "Hybrid tracing finds the faulty function first", "P2",
    "Top-1 means the first suspect overlaps the faulty lines. Blame-deploy is the strongest naive baseline because most incidents are change-induced; the hybrid adds call-path and stack-frame evidence to pick the right change.");
  barChart(s, order.map(([, l]) => l), [
    { name: "Top-1", values: order.map(([m]) => L[m].top1), color: HEX.amber },
    { name: "Top-3", values: order.map(([m]) => L[m].top3), color: HEX.teal }], { x: 0.6, y: 1.65, w: 8.3, h: 4.75 });
  stat(s, 9.1, 1.75, 3.6, pct(L.hybrid.top1), "Top-1, hybrid", `MRR ${num(L.hybrid.mrr)}; with LLM ${pct(loc("hybrid_llm"))}`);
  stat(s, 9.1, 3.25, 3.6, pct(L.recent_changes.top1), "Top-1, blame deploy", `best naive baseline; v0 ${pct(L.legacy_v0.top1)}`, HEX.amber);
  card(s, 9.1, 4.75, 3.6, 1.6, COL.mint);
  text(s, S.notes && S.notes.localization ? S.notes.localization : "", { x: 9.3, y: 4.82, w: 3.25, h: 1.45, fontSize: 13, bold: true, valign: "middle" });
  text(s, `n = ${L.hybrid.n} fault runs. Top-1/Top-3 at function level (chunk overlaps the faulty lines).`, { x: 0.6, y: 6.45, w: 8.3, h: 0.3, fontSize: 11, color: COL.muted });
}

// =============================================================== 14. Ablation + models
{
  const abl = [["hybrid", "Full hybrid"], ["no_trace", "- stack frames"], ["no_call_graph", "- route + call graph"], ["no_change", "- deploy diff"], ["no_dense", "- dense"], ["no_lexical", "- lexical"], ["hybrid_unscoped", "- tenant scope"]].filter(([m]) => L[m]);
  const s = content("Aryan: tracing", "Results: what matters", "Which evidence carries the ranking", "P2",
    "Each bar removes one feature and re-runs the same incidents. The biggest drop tells us which evidence the result depends on. The right-hand table compares three LLMs on the same candidates.");
  barChart(s, abl.map(([, l]) => l), [{ name: "Top-1", values: abl.map(([m]) => L[m].top1), color: HEX.amber }], { x: 0.6, y: 1.65, w: 6.6, h: 4.6 });
  const models = Object.keys(MODEL_LABEL).filter((suffix) => L[`hybrid_llm${suffix}`]);
  table(s, ["LLM", "Hybrid+LLM top-1", "RAG+LLM top-1", "Tokens / call"], models.map((suffix) => [MODEL_LABEL[suffix], pct(L[`hybrid_llm${suffix}`].top1),
    L[`rag_llm${suffix}`] ? pct(L[`rag_llm${suffix}`].top1) : "n/a", String(L[`hybrid_llm${suffix}`].mean_tokens || "n/a")]),
    { x: 7.45, y: 1.85, w: 5.25, colW: [1.55, 1.3, 1.25, 1.15], fontSize: 12 });
  card(s, 7.45, 4.15, 5.25, 2.1, COL.mint);
  text(s, S.notes && S.notes.ablation ? S.notes.ablation : "", { x: 7.65, y: 4.25, w: 4.85, h: 1.9, fontSize: 13, bold: true, valign: "middle" });
}

// =============================================================== 15. Test method
{
  const s = content("Syna: tests", "Methodology: step 6", "A diagnosis is a hypothesis until tested", "P3",
    "Confirmation has a strict definition: fail by assertion on the deployed code AND pass on the known-good code. Crashes, collection errors and timeouts do not count.");
  const flow = [["Generate", "template or LLM writes one pytest file"], ["Guard", "AST check: no os, files, network, eval, skip; >= 1 assert"],
    ["Run on faulty", "fresh copy, keys stripped, 90 s timeout"], ["Run on good", "same test, fault commit reverted"]];
  flow.forEach(([h, b], i) => {
    const x = 0.6 + i * 3.1;
    card(s, x, 1.8, 2.8, 1.7);
    badge(s, i + 1, x + 0.25, 1.98, COL.purple, COL.white);
    text(s, h, { x: x + 0.9, y: 2.02, w: 1.8, h: 0.45, fontFace: "Cambria", fontSize: 18, bold: true });
    text(s, b, { x: x + 0.25, y: 2.6, w: 2.35, h: 0.85, fontSize: 13, color: COL.muted });
    if (i < 3) arrow(s, x + 2.8, 2.65, x + 3.1, 2.65);
  });
  card(s, 0.6, 3.8, 5.95, 2.5);
  text(s, "Template generator (deterministic)", { x: 0.85, y: 3.92, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 18, bold: true, color: HEX.purpleDark });
  bullets(s, ["errors: replay the failing requests, assert no 5xx", "latency / CPU: replay the slowest request 20x; median <= max(3x, +10 ms), p95 <= max(2x, +20 ms) of baseline",
    "memory: 200 rounds of normal requests, tracemalloc growth < 8 MiB"], { x: 0.85, y: 4.45, w: 5.5, h: 1.8, fontSize: 13 });
  card(s, 6.75, 3.8, 5.95, 2.5);
  text(s, "LLM generator", { x: 7.0, y: 3.92, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 18, bold: true, color: HEX.purpleDark });
  bullets(s, ["Gets the packet, top-3 suspect code, observed requests and baselines", "Must assert healthy behaviour on the diagnosed symptom only",
    "One repair round if the guard rejects it; then the guard has the final word", "Can test what a template cannot, e.g. lock contention under concurrency"], { x: 7.0, y: 4.45, w: 5.5, h: 1.8, fontSize: 13 });
}

// =============================================================== 16. Test results
{
  const gens = Object.keys(T);
  const label = (g) => (g === "template" ? "Template" : `LLM ${MODEL_LABEL[g.replace("llm", "")] || g}`);
  const s = content("Syna: tests", "Results: confirming tests", "How often a generated test proves the diagnosis", "P3",
    "Read the confirming bar for each generator. Fails-on-faulty without passes-on-known-good means the test was too strict, which is the main failure mode we saw.");
  barChart(s, ["Guard pass", "Fails on faulty", "Passes on known-good", "Confirming"],
    gens.map((g, i) => ({ name: label(g), values: [T[g].guard_pass, T[g].fails_on_faulty, T[g].passes_on_fixed, T[g].confirming], color: [HEX.purple, HEX.teal, HEX.amber, HEX.grey][i % 4] })),
    { x: 0.6, y: 1.65, w: 7.6, h: 4.75 });
  const byScenario = S.tests_by_scenario_rollup || {};
  const ids = Object.keys(byScenario);
  if (ids.length) {
    table(s, ["Fault", ...gens.map((g) => (g === "template" ? "Tmpl" : (MODEL_LABEL[g.replace("llm", "")] || g).replace("gpt-", "").replace("-27b", "").replace("-120b", ""))) ],
      ids.map((id) => [id, ...gens.map((g) => byScenario[id][g] || "-")]),
      { x: 8.45, y: 1.7, w: 4.25, colW: [0.85, ...gens.map(() => 3.4 / gens.length)], fontSize: 12, margin: [2, 5, 2, 5] });
  }
  text(s, "Cells: confirming / runs with a test. F09 was never detected, so no test. gpt-oss-120b tests ran on seed 0 only (Groq rate limits): its bars use n = 11.",
    { x: 8.45, y: 5.75, w: 4.25, h: 0.9, fontSize: 11, color: COL.muted });
}

// =============================================================== 17. Action
{
  const s = content("Results", "Results: not scaling blindly", "Evidence-driven actions versus scale-on-alert", "team",
    "The expected action is code_fix for every fault, none for H01/H02 and capacity_scale for H03. Scale-on-alert is what a classic autoscaler does whenever an alert fires.");
  barChart(s, ["Sentinel", "Sentinel + LLM", "Scale on robust alert", "Scale on threshold alert"],
    [{ name: "Action accuracy", values: [A.sentinel, A.sentinel_llm, A.always_scale_on_robust_alert, A.always_scale_on_alert], color: HEX.teal }],
    { x: 0.6, y: 1.65, w: 7.4, h: 4.7, showLegend: false });
  stat(s, 8.3, 1.75, 4.4, pct(A.sentinel), "right action, deterministic", `over all ${S.runs} runs`);
  stat(s, 8.3, 3.25, 4.4, pct(A.always_scale_on_robust_alert), "scale on every alert", "right only when nothing broke or traffic surged", HEX.amber);
  card(s, 8.3, 4.75, 4.4, 1.6, COL.mint);
  text(s, S.notes && S.notes.action ? S.notes.action : "", { x: 8.5, y: 4.82, w: 4.0, h: 1.45, fontSize: 13, bold: true, valign: "middle" });
}

// =============================================================== 18. Worked example
{
  const ex = S.example || {};
  const s = content("Results", "Worked example", ex.title || "One incident, end to end", "team",
    "Walk the four boxes. Then open the audit file to show every stage was recorded.");
  const boxes = [["Detect", ex.detect], ["Trace", ex.trace], ["Confirm", ex.confirm], ["Hand off", ex.handoff]];
  boxes.forEach(([h, b], i) => {
    const x = 0.6 + i * 3.1;
    card(s, x, 1.8, 2.8, 3.2);
    badge(s, i + 1, x + 0.25, 1.98);
    text(s, h, { x: x + 0.9, y: 2.02, w: 1.8, h: 0.45, fontFace: "Cambria", fontSize: 19, bold: true });
    text(s, b || "", { x: x + 0.25, y: 2.65, w: 2.35, h: 2.3, fontSize: 14 });
    if (i < 3) arrow(s, x + 2.8, 3.4, x + 3.1, 3.4);
  });
  card(s, 0.6, 5.3, 12.1, 0.85, COL.ink);
  text(s, ex.audit || "", { x: 0.85, y: 5.35, w: 11.6, h: 0.75, fontSize: 12, fontFace: "Courier New", color: COL.white, valign: "middle" });
}

// =============================================================== 19. Technical implementation
{
  const s = content("Results", "Technical implementation", "Tools, models and retrieval", "team",
    "Be ready to justify each choice: in-process telemetry for reproducibility, own BM25 for transparency, a small CPU embedding model, three hosted LLMs compared on identical prompts.");
  const cols = [
    ["Tools", ["Python, FastAPI, Uvicorn, Pydantic", "httpx, psutil, PyYAML", "git diff / blame / revert", "pytest + JUnit XML sandbox", "Ruff, GitHub Actions"]],
    ["Models", ["Primary LLM: OpenAI gpt-5.4-mini", "Compared: gpt-oss-120b (Groq)", "Embeddings: BAAI/bge-small-en-v1.5", "Detector and tracer weights: no ML training", "Every LLM answer cached by prompt hash"]],
    ["Retrieval", ["AST function-level chunks", "BM25 with identifier splitting", "Dense cosine (fastembed, ONNX, CPU)", "Route map + call graph + stack frames", "Behavioural git diff, tenant-scoped"]],
  ];
  cols.forEach(([h, items], i) => {
    const x = 0.6 + i * 4.13;
    card(s, x, 1.8, 3.7, 3.7);
    text(s, h, { x: x + 0.3, y: 1.95, w: 3.1, h: 0.5, fontFace: "Cambria", fontSize: 20, bold: true, color: COL.teal });
    bullets(s, items, { x: x + 0.3, y: 2.6, w: 3.15, h: 2.8, fontSize: 15 });
  });
  text(s, "Guardrails: tenant-scoped retrieval, redaction, JSON-only LLM output with id validation, test guard + sandbox, no write access, human approval.", { x: 0.6, y: 5.75, w: 12.1, h: 0.6, fontSize: 15, italic: true, color: COL.teal });
}

// =============================================================== 20. Alignment
{
  const s = content("Discussion", "Alignment", "Does the experiment answer the question?", "team",
    "Be candid about the last two rows: steps 7-10 are not evaluated, and everything is one small shared server.");
  table(s, ["Part of the question", "How it is tested", "Status"], [
    ["Right tenant, no false alarms (RQ1)", `${nFault} fault runs + quiet controls vs fixed thresholds`, "Answered"],
    ["Faulty function ranked first (RQ2)", "Top-1/Top-3/MRR vs v0, blame-deploy, BM25, dense, RAG+LLM; 6 ablations", "Answered"],
    ["LLM as re-ranker vs plain RAG (H3)", "Same candidates, 2 LLMs, same prompts", "Answered"],
    ["Generated test confirms the diagnosis (RQ3)", "Fail on faulty and pass on known-good, template vs LLM", "Answered"],
    ["Right action instead of scaling (RQ4)", "Action accuracy vs scale-on-alert", "Answered"],
    ["Fix proposal, PR, CI/CD rollout (steps 7-10)", "Designed; human approval recorded only", "Not evaluated"],
    ["Generalises beyond our 3 services", "One small Python stack, faults written by us", "Open"],
  ], { x: 0.6, y: 1.75, w: 12.1, colW: [4.0, 6.0, 2.1], fontSize: 13 });
  const H = S.localization_heldout_top1;
  text(s, "Held-out check: Top-1 on seeds 1-2 only (seed 0 was used while building)", { x: 0.6, y: 4.75, w: 12.1, h: 0.4, fontFace: "Cambria", fontSize: 18, bold: true });
  [["hybrid", "Hybrid"], ["hybrid_llm", "Hybrid + LLM"], ["rag_llm", "RAG + LLM"], ["recent_changes", "Blame deploy"]].forEach(([m, l], i) => {
    const x = 0.6 + i * 3.06;
    card(s, x, 5.25, 2.86, 1.4);
    text(s, pct(H[m]), { x: x + 0.25, y: 5.3, w: 2.4, h: 0.8, fontFace: "Cambria", fontSize: 36, bold: true, color: i < 2 ? HEX.teal : HEX.amber, valign: "middle" });
    text(s, l, { x: x + 0.25, y: 6.1, w: 2.4, h: 0.4, fontSize: 14, color: COL.muted });
  });
}

// =============================================================== 21. Limitations
{
  const s = content("Discussion", "Limitations and failure cases", "What does not work yet", "team",
    "Each presenter reads their own column. The failure cases come from the runs; the rest are structural.");
  const cols = [
    ["P1  Detection", HEX.teal, S.notes && S.notes.limits_p1 ? S.notes.limits_p1 : []],
    ["P2  Tracing", HEX.amber, S.notes && S.notes.limits_p2 ? S.notes.limits_p2 : []],
    ["P3  Tests", HEX.purple, S.notes && S.notes.limits_p3 ? S.notes.limits_p3 : []],
  ];
  cols.forEach(([h, c, items], i) => {
    const x = 0.6 + i * 4.13;
    card(s, x, 1.75, 3.7, 3.85);
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.95, w: 0.32, h: 0.32, fill: { color: c }, line: { color: c } });
    text(s, h, { x: x + 0.75, y: 1.9, w: 2.8, h: 0.42, fontFace: "Cambria", fontSize: 18, bold: true });
    bullets(s, items, { x: x + 0.3, y: 2.5, w: 3.15, h: 3.0, fontSize: 13 });
  });
  card(s, 0.6, 5.8, 12.1, 0.9, COL.mint);
  text(s, "Across the project: one small Python stack on one machine; faults, decoys and traffic written by us; steps 7-10 not automated; LLM runs once per prompt (cached).", { x: 0.85, y: 5.8, w: 11.6, h: 0.9, fontSize: 14, valign: "middle" });
}

// =============================================================== 22. Threats
{
  const s = content("Discussion", "Threats to validity", "Possible sources of error and bias", "team",
    "Say the first card before the panel does: we wrote the faults and the tracer. That is why weights were fixed in advance and seeds 1-2 are held out.");
  const cards = [
    ["We wrote the faults", "The same team wrote the faults and the tracer. Weights were fixed before the runs; seed 0 was used for development, seeds 1-2 are held out."],
    ["Change-induced faults only", "Every fault arrives in a deployment, which favours diff-based evidence. Latent bugs triggered by new traffic are not covered."],
    ["Small sample", `${S.runs} runs from 15 scenarios. One wrong answer moves a rate by several points; read differences as directional.`],
    ["Timing noise", "Load, tests and services share one laptop. Latency tests can flip near a budget; we report every run, no re-runs."],
    ["LLM variance", "One run per prompt, cached. GPT-5 models expose no temperature; another prompt or model version could change scores."],
    ["Baseline strength", "Fixed thresholds use common defaults, not values tuned to these services. A tuned threshold would do better."],
  ];
  cards.forEach(([h, b], i) => {
    const x = 0.6 + (i % 3) * 4.13, y = 1.75 + Math.floor(i / 3) * 2.45;
    card(s, x, y, 3.7, 2.25);
    text(s, h, { x: x + 0.3, y: y + 0.18, w: 3.15, h: 0.45, fontFace: "Cambria", fontSize: 18, bold: true, color: COL.teal });
    text(s, b, { x: x + 0.3, y: y + 0.7, w: 3.15, h: 1.5, fontSize: 13, color: COL.muted });
  });
}

// =============================================================== 23. Reproducibility
{
  const s = content("Discussion", "Methodology and reproducibility", "Anyone can rerun every number on this deck", "team",
    "Recordings keep raw telemetry, so analysis can be re-run without traffic. LLM answers are cached by prompt hash, so re-scoring costs nothing.");
  card(s, 0.6, 1.75, 7.2, 4.0, COL.ink);
  text(s, [
    "pip install -r requirements.txt",
    "echo OPENAI_API_KEY=... > .env   # or GROQ_API_KEY",
    "",
    "python -m evaluation.benchmark record --seeds 0 1 2",
    "python -m evaluation.benchmark analyze --seeds 0 1 2",
    "python -m evaluation.benchmark analyze-model \\",
    "    --provider groq --model openai/gpt-oss-120b --label gptoss",
    "python -m evaluation.benchmark score",
    "",
    "python -m benchmark.demo F01        # live demo",
    "pytest -q && ruff check .",
  ].join("\n"), { x: 0.9, y: 1.95, w: 6.7, h: 4.2, fontFace: "Courier New", fontSize: 13, color: COL.white });
  card(s, 8.0, 1.75, 4.7, 4.0);
  text(s, "What is fixed", { x: 8.25, y: 1.9, w: 4.2, h: 0.45, fontFace: "Cambria", fontSize: 18, bold: true, color: COL.teal });
  bullets(s, ["Seeded traffic, decoy choice and commit order", "Fixed commit dates, so git history is identical", "Detector constants and tracer weights in code",
    "Prompt versions in the audit trail", "Raw telemetry per run in data/bench", "Per-run results in evaluation/results/runs"], { x: 8.25, y: 2.45, w: 4.2, h: 3.75, fontSize: 14 });
}

// =============================================================== 24. Conclusion
{
  const s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: section("Conclusion") });
  text(s, "CONCLUSION", { x: 0.9, y: 0.7, w: 8, h: 0.35, fontSize: 14, bold: true, color: HEX.amber, charSpacing: 4 });
  text(s, S.notes && S.notes.headline ? S.notes.headline : "", { x: 0.9, y: 1.1, w: 11.5, h: 1.0, fontFace: "Cambria", fontSize: 32, bold: true, color: HEX.white });
  text(s, "What we can say", { x: 0.9, y: 2.45, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: "D6DAEA" });
  bullets(s, S.notes && S.notes.conclusions ? S.notes.conclusions : [], { x: 0.9, y: 3.0, w: 5.6, h: 3.6, fontSize: 15, color: HEX.white });
  text(s, "Next steps", { x: 7.0, y: 2.45, w: 5.5, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: "D6DAEA" });
  bullets(s, ["P1: Prometheus / OpenTelemetry instead of in-process telemetry; latent-fault scenarios",
    "P2: multi-language index (tree-sitter); learn weights on a separate fault set",
    "P3: concurrency-aware test templates; run tests in a container sandbox",
    "Team: step 7-8 draft PR with the confirming test, CI gate and canary, behind approval"], { x: 7.0, y: 3.0, w: 5.6, h: 3.6, fontSize: 15, color: HEX.white });
  s.addNotes("Close by answering the research question with the numbers, then the next steps by owner.");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
