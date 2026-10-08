import { S } from '../store.js';
import { api } from '../api.js';
import { FEATURES, featureBar, callGraph, codeView } from '../charts.js';
import { esc, fmt, setHTML, chip } from '../ui.js';

export const id = 'trace';
let sel = 0, shown = null;
const sources = {};

const overlaps = (a, b) => a.path === b.file && a.start <= b.end_line && b.start_line <= a.end;

export function mount(root) {
  shown = null;
  root.innerHTML = '<div data-r="all"></div>';
  root.onclick = e => { const el = e.target.closest('.suspect'); if (el) { sel = Number(el.dataset.i); shown = null; update(); } };
}

function load(path) {
  if (sources[path] !== undefined) return;
  sources[path] = null;
  api.code(path).then(r => { sources[path] = r.text; shown = null; update(); }).catch(() => { sources[path] = false; shown = null; update(); });
}

export function update() {
  const root = document.getElementById('view');
  const box = root.querySelector('[data-r=all]');
  if (!box) return;
  const r = S.result;
  if (!r) { setHTML(box, `<div class="empty"><b>${S.status === 'running' ? 'Waiting for the diagnosis…' : 'No diagnosis yet'}</b>Rankings appear here when the tracer finishes.</div>`); return; }
  const suspects = (r.suspects || []).slice(0, 8);
  if (!suspects.length) { setHTML(box, '<div class="empty"><b>No suspects</b>The tracer found no code evidence for this incident.</div>'); return; }
  sel = Math.min(sel, suspects.length - 1);
  const top = suspects[sel];
  if (top.path) load(top.path);
  const key = `${S.run?.id}|${sel}|${sources[top.path] ? 1 : 0}|${suspects.length}`;
  if (key === shown) return;
  shown = key;

  const maxTotal = Math.max(...suspects.map(s => FEATURES.reduce((a, [k, , , w]) => a + (s.features?.[k] || 0) * w, 0)), 1);
  const truth = r.truth;
  const ranges = (r.ranges || []).filter(x => x.behavioural !== false && x.file === top.path).map(x => [x.start, x.end]);
  const hit = s => truth?.file && overlaps(s, truth);
  const culprit = c => (r.ranges || []).some(x => x.commit === c.sha && x.file === top.path && x.start <= top.end && top.start <= x.end);
  const src = sources[top.path];

  const list = suspects.map((s, i) => `<div class="suspect ${i === sel ? 'on' : ''}" data-i="${i}">
    <div class="suspect-h"><span class="rank">${i + 1}</span><b>${esc(s.symbol)}</b>${hit(s) ? chip('true cause', 'green') : ''}<span class="score">${fmt(s.score, 2)}</span></div>
    <div class="where">${esc(s.path)}:${s.start}–${s.end}</div>${featureBar(s.features || {}, maxTotal)}
    ${i === sel && s.reasons?.length ? `<ul class="reasons">${s.reasons.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}</div>`).join('');

  const legend = FEATURES.map(([, l, c, w]) => `<span><i style="background:${c}"></i>${l} <span class="dim">×${w}</span></span>`).join('');
  const codeBox = src ? `<div class="code-h"><span>${esc(top.path)}</span>${chip('lines ' + top.start + '–' + top.end, 'indigo')}${truth?.file === top.path ? chip('true cause ' + truth.start_line + '–' + truth.end_line, 'green') : ''}</div>${codeView(src, { focus: [top.start, top.end], changed: ranges, truth: truth?.file === top.path ? [truth.start_line, truth.end_line] : null })}`
    : `<div class="empty" style="padding:30px">${src === false || !r.code_available ? 'Source not available for this run.' : 'Loading source…'}</div>`;

  const commits = (r.commits || []).map(c => `<div class="commit ${culprit(c) ? 'cul' : ''}"><code>${esc(c.sha)}</code><span>${esc(c.message)}</span>${culprit(c) ? chip('touches suspect', 'orange') : ''}</div>`).join('') || '<span class="muted">Commit list unavailable.</span>';
  const llm = r.llm;
  setHTML(box, `<div class="cols c2"><div><div class="sec-h"><h2>Ranked suspects</h2><span class="sub">bar length = weighted evidence</span></div><div class="flegend">${legend}</div>${list}</div>
    <div><div class="sec-h"><h2>Source</h2></div>${codeBox}
      <div class="sec-h"><h2>Call path</h2><span class="sub">route handler → callees</span></div><div class="card">${r.call_path ? callGraph(r.call_path, top.chunk_id) : '<span class="muted">Call graph unavailable.</span>'}</div>
      <div class="sec-h"><h2>Deployment</h2></div><div class="card">${commits}</div>
      ${llm ? `<div class="sec-h"><h2>LLM re-rank</h2><span class="sub">${esc(llm.model || '')} · ${llm.prompt_tokens || 0}+${llm.completion_tokens || 0} tokens · ${fmt(llm.latency_s)} s</span></div><div class="card"><p style="margin:0">${esc(llm.root_cause || 'No root-cause text.')}</p>${llm.valid === false ? '<p class="muted">Output invalid; deterministic ranking kept.</p>' : ''}</div>` : ''}</div></div>`);
}
