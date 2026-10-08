import { esc } from '../ui.js';
export const id = 'project';

const STEPS = [
  ['1 Collect', 'Per-route latency and errors from FastAPI middleware; per-process CPU and memory with psutil; one registry file maps tenants to owners.'],
  ['2 Detect', 'Robust z-score against the pre-change baseline, minimum real change, persistence and exceedance-rate checks. Fixed thresholds as the baseline.'],
  ['3 Packet', 'Anomalous signals, exceptions, slow requests and the deployment diff with git blame and a behaviour-only flag; redacted and hashed.'],
  ['4 Index', 'AST function chunks, routes from decorators, call graph, BM25 and bge-small embeddings.'],
  ['5 Trace', 'Seven weighted evidence features rank functions inside the affected tenant; an LLM may re-rank the top eight.'],
  ['6 Test', 'A generated test must fail on the deployed code and pass on the known-good code, run in a sandbox behind a static guard.'],
];
const TEAM = [
  ['Akash', 'indigo', 'Steps 1–2', ['Telemetry and registry', 'Robust detector and threshold baseline', 'Load generator, live recorder']],
  ['Aryan', 'orange', 'Steps 3–5', ['Evidence packet and deployment diff', 'Code index and hybrid tracer', 'LLM re-rank and action decision']],
  ['Syna', 'green', 'Step 6 + evaluation', ['Template and LLM test generators', 'Guard and sandbox', 'Benchmark harness and scoring']],
];
export function mount(root) {
  root.innerHTML = `
    <div class="sec-h"><h2>Research question</h2></div>
    <div class="card"><p class="rq" style="margin:0">On a shared server, can telemetry-grounded hybrid code retrieval, with an LLM, trace a runtime incident to the responsible function and confirm it with a generated test, better than fixed alerts, blaming the latest deployment, plain vector RAG, or scaling?</p></div>
    <div class="sec-h"><h2>Hypotheses</h2></div>
    <div class="cols c4">${[['H1', 'Robust detection beats fixed thresholds.'], ['H2', 'The hybrid tracer beats every single-signal baseline on Top-1.'], ['H3', 'An LLM helps as a re-ranker over structured evidence more than as plain RAG.'], ['H4', 'Most generated tests are confirming and unsafe tests are blocked.']].map(([k, t]) => `<div class="card"><span class="label">${k}</span><p style="margin:6px 0 0">${t}</p></div>`).join('')}</div>
    <div class="sec-h"><h2>The six steps</h2></div>
    <div class="cols c3">${STEPS.map(([h, t]) => `<div class="card stepcard"><b><span class="no">${esc(h.slice(0, 1))}</span> ${esc(h.slice(2))}</b><p>${esc(t)}</p></div>`).join('')}</div>
    <div class="sec-h"><h2>Team</h2></div>
    <div class="cols c3">${TEAM.map(([n, c, r, items]) => `<div class="card who"><span class="chip ${c} tag">${n}</span><b>${r}</b><ul>${items.map(i => `<li>${esc(i)}</li>`).join('')}</ul></div>`).join('')}</div>
    <div class="sec-h"><h2>Not built, by choice</h2></div>
    <div class="card"><ul class="plain"><li>Steps 7–10: bounded fix proposal, draft PR, CI/CD rollout, post-deploy watch (designed, not automated).</li><li>Sentinel never edits code, restarts or scales; a named human approves any change.</li></ul></div>`;
}
export function update() {}
