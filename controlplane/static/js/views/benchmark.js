// Benchmark results (45 recorded runs), shared with the Sentinel Console.
const S = { results: null, external: null };
import { api } from '../api.js';
import { hbars } from '../charts.js';
import { esc, pct, setHTML, chip } from '../ui.js';

const LABELS = { hybrid: 'Hybrid (no LLM)', hybrid_llm: 'Hybrid + LLM', 'hybrid_llm@gptoss': 'Hybrid + LLM (gpt-oss)', rag_llm: 'Plain RAG + LLM', 'rag_llm@gptoss': 'Plain RAG + LLM (gpt-oss)', recent_changes: 'Blame the deployment', bm25: 'BM25 only', dense: 'Embeddings only', legacy_v0: 'v0 retriever' };
const ABL = [['hybrid', 'Full hybrid'], ['no_trace', '− stack frames'], ['no_call_graph', '− route + call graph'], ['no_change', '− deploy diff'], ['no_dense', '− embeddings'], ['no_lexical', '− BM25'], ['hybrid_unscoped', '− tenant scope']];
const COLS = [['recent_changes', 'Blame deploy'], ['bm25', 'BM25'], ['dense', 'Embed'], ['hybrid', 'Hybrid'], ['hybrid_llm', 'Hybrid+LLM'], ['rag_llm', 'RAG+LLM']];

// Hover definitions: what each metric measures and how it is computed.
const GLOSS = {
  recall: 'Fault recall: share of the 36 fault runs where the detector raised an incident on the faulty service. Higher is better.',
  falsealarm: 'False alarm rate: share of the quiet deployments (docs-only, behaviour-neutral refactor) that still raised an incident. Lower is better.',
  top1: 'Top-1: the faulty function is the first-ranked suspect (the suspect overlaps the faulty lines). Top-3 is the faint bar.',
  confirming: 'Confirming test: fails by assertion on the deployed code AND passes on the known-good code. A test that fails on both proves nothing.',
  action: 'Action accuracy: the recommended action (code_fix / capacity_scale / investigate) equals the expected one for that scenario.',
  guard: 'Guard pass: the generated test passed the static safety check (no os/subprocess/network imports, no eval/exec, has assertions) before it was run.',
  fails: 'Fails on faulty: the test fails by assertion (not by crashing) on the deployed, faulty code.',
  passes: 'Passes on known-good: the same test passes on the version with the fault commit reverted.',
  n: 'Number of runs the figure is based on.',
  ablation: 'Ablation: Top-1 when one kind of evidence is removed from the ranker. A big drop means that evidence matters.',
  heldout: 'Held-out: seeds 1 and 2 only. Seed 0 was used while building, so these are the honest numbers.',
};
const tip = (k, text) => `<span title="${esc(GLOSS[k])}" style="cursor:help;border-bottom:1px dotted currentColor">${text}</span>`;
let loaded = false;

export function mount(root) {
  root.innerHTML = '<div data-r="all"><div class="empty"><b>Loading results…</b></div></div>';
  if (!loaded) api.results().then(r => { S.results = r; loaded = true; update(); }).catch(e => { S.results = { available: false, error: e.message }; update(); });
  api.external().then(r => { S.external = r; update(); }).catch(() => { S.external = {}; });
}

const METHOD_NAMES = { static_threshold: 'Fixed threshold', rolling_zscore: 'Rolling z-score', robust_persistence: 'Sentinel (robust + persistence)', random: 'Random (expected)', latency_ratio: 'Latency ratio (operator view)', robust_change: 'Sentinel (change-aware robust)' };
const f2 = v => (v == null ? '·' : Number(v).toFixed(2));

function externalSection(X) {
  if (!X || (!X.microsoft && !X.rcaeval_re1)) return '';
  const ms = X.microsoft && `<div class="card"><div class="label" style="margin-bottom:8px">Microsoft Cloud Monitoring Dataset: detection on ${X.microsoft.series} labelled production series</div>
    <table class="t"><tr><th>method</th><th class="n">${tip('recall', 'recall')}</th><th class="n">precision</th><th class="n">F1</th><th class="n">median delay (points)</th><th class="n">false alarms / 1000 pts, anomaly-free</th></tr>${Object.entries(X.microsoft.methods).map(([k, v]) => `<tr><td>${esc(METHOD_NAMES[k] || k)}</td><td class="n">${f2(v.all.recall)}</td><td class="n">${f2(v.all.precision)}</td><td class="n">${f2(v.all.f1)}</td><td class="n">${v.all.median_delay_points ?? '·'}</td><td class="n">${f2(v.all.false_alarms_per_1000_points_anomaly_free)}</td></tr>`).join('')}</table>
    <p class="muted" style="font-size:12px">Real, expert-labelled series with no deployments or code, so detection only. Rules fixed from granularity before scoring, no tuning.</p></div>`;
  const re = X.rcaeval_re1 && `<div class="card"><div class="label" style="margin-bottom:8px">RCAEval RE1: faulty service ranked first, ${X.rcaeval_re1.cases} real fault-injection cases</div>
    <table class="t"><tr><th>method</th><th class="n">AC@1</th><th class="n">AC@3</th><th class="n">Avg@5</th>${Object.keys(X.rcaeval_re1.methods.robust_change.by_system).map(s => `<th class="n">AC@1 ${esc(s.replace('RE1-', ''))}</th>`).join('')}</tr>${Object.entries(X.rcaeval_re1.methods).map(([k, v]) => `<tr><td>${esc(METHOD_NAMES[k] || k)}</td><td class="n">${f2(v.all['ac@1'])}</td><td class="n">${f2(v.all['ac@3'])}</td><td class="n">${f2(v.all['avg@5'])}</td>${Object.values(v.by_system).map(x => `<td class="n">${f2(x['ac@1'])}</td>`).join('')}</tr>`).join('')}</table>
    <p class="muted" style="font-size:12px">Online Boutique, Sock Shop, Train Ticket. Service-level ranking only (no code in this dataset); the injection time stands in for a known deployment time.</p></div>`;
  return `<div class="sec-h"><h2>Independent data</h2><span class="sub">not written by us: tests whether the results hold outside our own benchmark</span></div><div class="cols eq2">${ms || ''}${re || ''}</div>`;
}

const cell = rank => (rank === undefined ? '<i class="na">·</i>' : rank === null ? '<i class="miss">×</i>' : `<i class="${rank === 1 ? 'r1' : rank === 2 ? 'r2' : rank <= 3 ? 'r3' : 'rx'}">${rank}</i>`);

export function update() {
  const box = document.getElementById('view').querySelector('[data-r=all]');
  const R = S.results;
  if (!box || !R) return;
  if (!R.available) { setHTML(box, '<div class="empty"><b>No benchmark results found</b>Run <span class="mono">python -m evaluation.benchmark score</span> to create evaluation/results/summary.json.</div>'); return; }
  const s = R.summary, d = s.detection, L = s.localization, T = s.tests, A = s.action, H = s.localization_heldout_top1 || {};
  const methods = Object.keys(L).filter(m => !m.startsWith('no_') && m !== 'hybrid_unscoped').sort((a, b) => L[b].top1 - L[a].top1);
  const kpi = (v, l, sub, c, k) => `<div class="card kpi" title="${esc(GLOSS[k] || '')}"><div class="label">${l}</div><div class="big" style="color:${c}">${v}</div><div class="delta">${sub}</div></div>`;
  const stat = [
    kpi(pct(d.robust.fault_recall), 'Faults detected', `fixed thresholds ${pct(d.threshold.fault_recall)}`, 'var(--indigo)', 'recall'),
    kpi(pct(L.hybrid.top1), 'Faulty function ranked first', `blame the deploy ${pct(L.recent_changes.top1)} · plain RAG ${pct(L.rag_llm?.top1)}`, 'var(--orange)', 'top1'),
    kpi(pct(T.template?.confirming), 'Tests that confirm', `template · LLM ${pct(T.llm?.confirming)}`, 'var(--green)', 'confirming'),
    kpi(pct(A.sentinel), 'Right action', `scale on every alert ${pct(A.always_scale_on_robust_alert)}`, 'var(--text)', 'action'),
  ].join('');
  const det = hbars([
    { tip: GLOSS.recall, label: 'Fault recall · robust', value: d.robust.fault_recall, color: 'var(--indigo)' }, { tip: GLOSS.recall, label: 'Fault recall · thresholds', value: d.threshold.fault_recall, color: 'var(--amber)' },
    { tip: GLOSS.falsealarm, label: 'False alarms · robust', value: d.robust.false_alarm_rate_quiet_controls, color: 'var(--red)' }, { tip: GLOSS.falsealarm, label: 'False alarms · thresholds', value: d.threshold.false_alarm_rate_quiet_controls, color: 'var(--red)' },
  ]);
  const byClass = hbars(Object.keys(d.robust.by_class).flatMap(c => [{ label: `${c} · robust`, value: d.robust.by_class[c], color: 'var(--indigo)' }, { label: `${c} · thresholds`, value: d.threshold.by_class[c], color: 'var(--amber)' }]));
  const loc = hbars(methods.map(m => ({ tip: GLOSS.top1, label: LABELS[m] || m, value: L[m].top1, ghost: L[m].top3, hi: m === 'hybrid', color: m === 'hybrid' ? 'var(--orange)' : m.includes('llm') ? 'var(--indigo)' : 'var(--dim)' })));
  const abl = hbars(ABL.filter(([m]) => L[m]).map(([m, l]) => ({ tip: GLOSS.ablation, label: l, value: L[m].top1, hi: m === 'hybrid', color: m === 'hybrid' ? 'var(--orange)' : 'var(--indigo)' })));
  const tests = `<table class="t"><tr><th>generator</th><th class="n">${tip('n','n')}</th><th class="n">${tip('guard','guard')}</th><th class="n">${tip('fails','fails on faulty')}</th><th class="n">${tip('passes','passes on good')}</th><th class="n">${tip('confirming','confirming')}</th></tr>${Object.entries(T).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v.n}</td><td class="n">${pct(v.guard_pass)}</td><td class="n">${pct(v.fails_on_faulty)}</td><td class="n">${pct(v.passes_on_fixed)}</td><td class="n"><b>${pct(v.confirming)}</b></td></tr>`).join('')}</table>`;
  const grid = `<div class="heat"><div class="hh">scenario</div>${COLS.map(([, l]) => `<div class="hh">${l}</div>`).join('')}${R.grid.filter(g => Object.keys(g.cells).length).map(g => `<div class="rl"><b>${g.scenario}</b>${esc(g.title)}</div>${COLS.map(([m]) => `<div class="cell">${(g.cells[m] || []).map(cell).join('') || cell(undefined)}</div>`).join('')}`).join('')}</div>
    <div class="legend"><span>cell = rank of the true function, one square per seed</span><span class="chip green">1</span><span class="chip">2–3</span><span class="chip orange">4+</span><span class="chip red">× missed / undetected</span></div>`;
  const fails = R.failures.map(f => `<div class="fail"><span class="id">${esc(f.scenario)} · s${f.seed}</span>${chip(f.kind, f.kind === 'false alarm' || f.kind === 'undetected' ? 'red' : 'orange')}<span>${esc(f.text)}</span></div>`).join('') || '<span class="muted">No failures recorded.</span>';
  setHTML(box, `<div class="cols c4">${stat}</div>
    <div class="sec-h"><h2>Detection</h2><span class="sub">${s.fault_runs} fault runs, ${s.control_runs} control runs, seeds ${s.seeds.join(', ')}</span></div>
    <div class="cols eq2"><div class="card">${det}</div><div class="card">${byClass}</div></div>
    <div class="sec-h"><h2>Localisation</h2><span class="sub">Top-1 solid, Top-3 faint · <span title="${esc(GLOSS.heldout)}" style="cursor:help">held-out seeds</span>: hybrid ${pct(H.hybrid)}, blame ${pct(H.recent_changes)}</span></div>
    <div class="cols eq2"><div class="card">${loc}</div><div class="card"><div class="label" style="margin-bottom:10px">Ablation: remove one evidence feature</div>${abl}</div></div>
    <div class="sec-h"><h2>Confirming tests</h2></div><div class="card">${tests}</div>
    <div class="sec-h"><h2>Every scenario</h2></div><div class="card">${grid}</div>
    ${externalSection(S.external)}
    <div class="sec-h"><h2>What failed</h2><span class="sub">reported, not hidden</span></div><div class="card">${fails}</div>`);
}
