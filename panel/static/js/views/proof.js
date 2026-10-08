import { S } from '../store.js';
import { highlight } from '../charts.js';
import { esc, setHTML, pill } from '../ui.js';

export const id = 'proof';
let shown = null;
const kind = o => (o === 'assertion_failed' ? 'bad' : o === 'passed' ? 'ok' : 'warn');
const label = o => ({ assertion_failed: 'assertion failed', passed: 'passed', error: 'error', timeout: 'timeout' }[o] || o || 'not run');

export function mount(root) { shown = null; root.innerHTML = '<div data-r="all"></div>'; }

function runCard(title, expect, run, want) {
  if (!run) return `<div class="run-card"><div class="label">${title}</div><div class="muted" style="margin-top:8px">not run</div></div>`;
  const good = run.outcome === want;
  return `<div class="run-card ${good ? (want === 'passed' ? 'green' : 'red') : ''}"><div style="display:flex;justify-content:space-between;align-items:center"><div class="label">${title}</div>${pill(label(run.outcome), kind(run.outcome))}</div><div class="dim" style="font-size:12px;margin-top:4px">expected: ${expect}</div><div class="out">${esc(run.detail || '—')}</div></div>`;
}

export function update() {
  const box = document.getElementById('view').querySelector('[data-r=all]');
  if (!box) return;
  const r = S.result;
  if (!r) { setHTML(box, `<div class="empty"><b>${S.status === 'running' ? 'Waiting for the tests…' : 'No tests yet'}</b>A confirming test must fail on the deployed code and pass on the known-good code.</div>`); return; }
  const key = `${S.run?.id}|${Object.keys(r.tests).length}`;
  if (key === shown) return;
  shown = key;
  const names = Object.keys(r.tests);
  if (!names.length) { setHTML(box, '<div class="empty"><b>No test generated</b>This run recommended no code fix, so no confirming test was needed.</div>'); return; }
  setHTML(box, names.map(n => {
    const t = r.tests[n];
    const f = t.faulty?.outcome === 'assertion_failed', g = t.fixed?.outcome === 'passed';
    const code = t.code ? highlight(t.code).split('\n').map((l, i) => `<div class="ln"><span class="no">${i + 1}</span><span class="tx">${l || ' '}</span></div>`).join('') : '<div class="gap">no code</div>';
    return `<div class="sec-h"><h2>${n === 'template' ? 'Template generator' : 'LLM generator'}</h2><span class="sub">${t.guard.length ? 'guard: ' + esc(t.guard.join('; ')) : 'guard passed'}</span></div>
      <div class="verdict ${t.confirming ? 'ok' : 'no'}">${pill(t.confirming ? 'confirming' : 'not confirming', t.confirming ? 'ok' : 'bad')}<span>${t.guard.length ? 'No test ran: ' + esc(t.guard[0]) : `fails on the faulty code ${f ? '✓' : '✗'} · passes on the known-good code ${g ? '✓' : '✗'}`}</span></div>
      <div class="proof"><div><div class="code">${code}</div></div>
      <div style="display:grid;gap:14px;align-content:start">${runCard('Deployed code', 'fail (assertion)', t.faulty, 'assertion_failed')}${runCard('Known-good code', 'pass', t.fixed, 'passed')}</div></div>`;
  }).join(''));
}
