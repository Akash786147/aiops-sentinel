import { S } from './store.js';
import { api } from './api.js';
import { esc, setHTML } from './ui.js';

let mode = 'replay', scenario = 'F01', useLlm = true;
let el;
const keep = (k, v) => { try { localStorage.setItem('console.' + k, v); } catch { /* storage may be blocked */ } };
const read = (k, d) => { try { return localStorage.getItem('console.' + k) ?? d; } catch { return d; } };

export function notice(text, action) {
  const n = document.getElementById('notice');
  n.innerHTML = text ? `<div class="notice"><span>${esc(text)}</span>${action ? `<button class="btn ghost" id="notice-act">${esc(action.label)}</button>` : ''}</div>` : '';
  if (text && action) document.getElementById('notice-act').onclick = action.run;
}

async function run() {
  notice('');
  try { await api.run({ scenario, mode, llm: useLlm }); }
  catch (e) {
    notice(e.message, mode === 'live' && e.status === 503 ? { label: 'Switch to Replay', run: () => { mode = 'replay'; keep('mode', mode); notice(''); render(); } } : null);
  }
}

function options() {
  const group = (label, items) => `<optgroup label="${label}">${items.map(s => {
    const off = mode === 'replay' && !s.replay_available;
    return `<option value="${s.id}" ${off ? 'disabled' : ''}>${s.id} · ${esc(s.title)}${off ? ' (no recording)' : ''}</option>`;
  }).join('')}</optgroup>`;
  return group('Faults', S.scenarios.filter(s => s.id.startsWith('F'))) + group('Controls', S.scenarios.filter(s => s.id.startsWith('H')));
}

export function updateTopbar() {
  if (!el) return;
  const st = el.querySelector('.state');
  const now = Date.now() / 1000;
  const secs = S.startedAt ? Math.max(0, (S.status === 'running' ? now : (S.endedAt ?? now)) - S.startedAt) : 0;
  st.className = `state ${S.status}`;
  st.innerHTML = `<i></i>${S.status === 'idle' ? 'idle' : `${S.status} · ${secs.toFixed(0)}s`}`;
  el.querySelector('[data-r=where]').innerHTML = `<small>${esc(S.server || 'shared server')}</small><b>${S.run ? `${esc(S.run.scenario)} · ${S.run.mode}` : 'No run yet'}</b>`;
  const btn = el.querySelector('#run');
  btn.disabled = S.status === 'running';
  btn.textContent = S.status === 'running' ? 'Running…' : 'Run';
  el.querySelector('select.pick').disabled = S.status === 'running';
}

export function refreshTopbar() {
  if (!el) return;
  el.querySelector('[data-r=mode]').innerHTML = `<button data-m="replay" class="${mode === 'replay' ? 'on' : ''}">Replay</button><button data-m="live" class="${mode === 'live' ? 'on' : ''}">Live</button>`;
  const pick = el.querySelector('select.pick');
  setHTML(pick, options());
  pick.value = scenario;
  const tog = el.querySelector('.toggle');
  tog.classList.toggle('off', mode !== 'live' || S.status === 'running' || !S.llmAvailable);
  el.querySelector('#llm').checked = useLlm && S.llmAvailable;
  updateTopbar();
}

export function mountTopbar(root) {
  el = root;
  mode = read('mode', 'replay'); scenario = read('scenario', 'F01'); useLlm = read('llm', '1') === '1';
  root.innerHTML = '<div class="where" data-r="where"></div><div class="seg" data-r="mode"></div><select class="pick" aria-label="Scenario"></select><label class="toggle"><input type="checkbox" id="llm"> LLM</label><button class="btn" id="run">Run</button><div class="state idle"><i></i>idle</div>';
  root.querySelector('[data-r=mode]').onclick = e => { const m = e.target.dataset.m; if (m && S.status !== 'running') { mode = m; keep('mode', m); refreshTopbar(); } };
  root.querySelector('select.pick').onchange = e => { scenario = e.target.value; keep('scenario', scenario); };
  root.querySelector('#llm').onchange = e => { useLlm = e.target.checked; keep('llm', useLlm ? '1' : '0'); };
  root.querySelector('#run').onclick = run;
  setInterval(() => { if (S.status === 'running') updateTopbar(); }, 500);
  refreshTopbar();
  return { setScenario: id => { scenario = id; }, setMode: m => { mode = m; } };
}
