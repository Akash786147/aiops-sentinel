// Benchmark results (45 recorded runs), shared with the Sentinel Console.
const S = { results: null };
import { api } from '../api.js';
import { hbars } from '../charts.js';
import { esc, pct, setHTML, chip } from '../ui.js';

const LABELS = { hybrid: 'Hybrid (no LLM)', hybrid_llm: 'Hybrid + LLM', 'hybrid_llm@gptoss': 'Hybrid + LLM (gpt-oss)', rag_llm: 'Plain RAG + LLM', 'rag_llm@gptoss': 'Plain RAG + LLM (gpt-oss)', recent_changes: 'Blame the deployment', bm25: 'BM25 only', dense: 'Embeddings only', legacy_v0: 'v0 retriever' };
const ABL = [['hybrid', 'Full hybrid'], ['no_trace', '− stack frames'], ['no_call_graph', '− route + call graph'], ['no_change', '− deploy diff'], ['no_dense', '− embeddings'], ['no_lexical', '− BM25'], ['hybrid_unscoped', '− tenant scope']];
const COLS = [['recent_changes', 'Blame deploy'], ['bm25', 'BM25'], ['dense', 'Embed'], ['hybrid', 'Hybrid'], ['hybrid_llm', 'Hybrid+LLM'], ['rag_llm', 'RAG+LLM']];
let loaded = false;

export function mount(root) {
  root.innerHTML = '<div data-r="all"><div class="empty"><b>Loading results…</b></div></div>';
  if (!loaded) api.results().then(r => { S.results = r; loaded = true; update(); }).catch(e => { S.results = { available: false, error: e.message }; update(); });
}

const cell = rank => (rank === undefined ? '<i class="na">·</i>' : rank === null ? '<i class="miss">×</i>' : `<i class="${rank === 1 ? 'r1' : rank === 2 ? 'r2' : rank <= 3 ? 'r3' : 'rx'}">${rank}</i>`);

export function update() {
  const box = document.getElementById('view').querySelector('[data-r=all]');
  const R = S.results;
  if (!box || !R) return;
  if (!R.available) { setHTML(box, '<div class="empty"><b>No benchmark results found</b>Run <span class="mono">python -m evaluation.benchmark score</span> to create evaluation/results/summary.json.</div>'); return; }
  const s = R.summary, d = s.detection, L = s.localization, T = s.tests, A = s.action, H = s.localization_heldout_top1 || {};
  const methods = Object.keys(L).filter(m => !m.startsWith('no_') && m !== 'hybrid_unscoped').sort((a, b) => L[b].top1 - L[a].top1);
  const kpi = (v, l, sub, c) => `<div class="card kpi"><div class="label">${l}</div><div class="big" style="color:${c}">${v}</div><div class="delta">${sub}</div></div>`;
  const stat = [
    kpi(pct(d.robust.fault_recall), 'Faults detected', `fixed thresholds ${pct(d.threshold.fault_recall)}`, 'var(--indigo)'),
    kpi(pct(L.hybrid.top1), 'Faulty function ranked first', `blame the deploy ${pct(L.recent_changes.top1)} · plain RAG ${pct(L.rag_llm?.top1)}`, 'var(--orange)'),
    kpi(pct(T.template?.confirming), 'Tests that confirm', `template · LLM ${pct(T.llm?.confirming)}`, 'var(--green)'),
    kpi(pct(A.sentinel), 'Right action', `scale on every alert ${pct(A.always_scale_on_robust_alert)}`, 'var(--text)'),
  ].join('');
  const det = hbars([
    { label: 'Fault recall · robust', value: d.robust.fault_recall, color: 'var(--indigo)' }, { label: 'Fault recall · thresholds', value: d.threshold.fault_recall, color: 'var(--amber)' },
    { label: 'False alarms · robust', value: d.robust.false_alarm_rate_quiet_controls, color: 'var(--red)' }, { label: 'False alarms · thresholds', value: d.threshold.false_alarm_rate_quiet_controls, color: 'var(--red)' },
  ]);
  const byClass = hbars(Object.keys(d.robust.by_class).flatMap(c => [{ label: `${c} · robust`, value: d.robust.by_class[c], color: 'var(--indigo)' }, { label: `${c} · thresholds`, value: d.threshold.by_class[c], color: 'var(--amber)' }]));
  const loc = hbars(methods.map(m => ({ label: LABELS[m] || m, value: L[m].top1, ghost: L[m].top3, hi: m === 'hybrid', color: m === 'hybrid' ? 'var(--orange)' : m.includes('llm') ? 'var(--indigo)' : 'var(--dim)' })));
  const abl = hbars(ABL.filter(([m]) => L[m]).map(([m, l]) => ({ label: l, value: L[m].top1, hi: m === 'hybrid', color: m === 'hybrid' ? 'var(--orange)' : 'var(--indigo)' })));
  const tests = `<table class="t"><tr><th>generator</th><th class="n">n</th><th class="n">guard</th><th class="n">fails on faulty</th><th class="n">passes on good</th><th class="n">confirming</th></tr>${Object.entries(T).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v.n}</td><td class="n">${pct(v.guard_pass)}</td><td class="n">${pct(v.fails_on_faulty)}</td><td class="n">${pct(v.passes_on_fixed)}</td><td class="n"><b>${pct(v.confirming)}</b></td></tr>`).join('')}</table>`;
  const grid = `<div class="heat"><div class="hh">scenario</div>${COLS.map(([, l]) => `<div class="hh">${l}</div>`).join('')}${R.grid.filter(g => Object.keys(g.cells).length).map(g => `<div class="rl"><b>${g.scenario}</b>${esc(g.title)}</div>${COLS.map(([m]) => `<div class="cell">${(g.cells[m] || []).map(cell).join('') || cell(undefined)}</div>`).join('')}`).join('')}</div>
    <div class="legend"><span>cell = rank of the true function, one square per seed</span><span class="chip green">1</span><span class="chip">2–3</span><span class="chip orange">4+</span><span class="chip red">× missed / undetected</span></div>`;
  const fails = R.failures.map(f => `<div class="fail"><span class="id">${esc(f.scenario)} · s${f.seed}</span>${chip(f.kind, f.kind === 'false alarm' || f.kind === 'undetected' ? 'red' : 'orange')}<span>${esc(f.text)}</span></div>`).join('') || '<span class="muted">No failures recorded.</span>';
  setHTML(box, `<div class="cols c4">${stat}</div>
    <div class="sec-h"><h2>Detection</h2><span class="sub">${s.fault_runs} fault runs, ${s.control_runs} control runs, seeds ${s.seeds.join(', ')}</span></div>
    <div class="cols eq2"><div class="card">${det}</div><div class="card">${byClass}</div></div>
    <div class="sec-h"><h2>Localisation</h2><span class="sub">Top-1 solid, Top-3 faint · held-out seeds: hybrid ${pct(H.hybrid)}, blame ${pct(H.recent_changes)}</span></div>
    <div class="cols eq2"><div class="card">${loc}</div><div class="card"><div class="label" style="margin-bottom:10px">Ablation: remove one evidence feature</div>${abl}</div></div>
    <div class="sec-h"><h2>Confirming tests</h2></div><div class="card">${tests}</div>
    <div class="sec-h"><h2>Every scenario</h2></div><div class="card">${grid}</div>
    <div class="sec-h"><h2>What failed</h2><span class="sub">reported, not hidden</span></div><div class="card">${fails}</div>`);
}
