import { S, on, apply, changed } from './store.js';
import { api, connect } from './api.js';
import { icon } from './ui.js';
import { mountTopbar, updateTopbar, refreshTopbar, notice } from './topbar.js';
import * as floor from './views/floor.js';
import * as incident from './views/incident.js';
import * as trace from './views/trace.js';
import * as proof from './views/proof.js';
import * as decision from './views/decision.js';
import * as results from './views/results.js';
import * as project from './views/project.js';

const VIEWS = { floor, incident, trace, proof, decision, results, project };
const NAV = [
  ['LIVE RUN', [['floor', 'Live floor'], ['incident', 'Incident'], ['trace', 'Trace'], ['proof', 'Proof'], ['decision', 'Decision']]],
  ['REFERENCE', [['results', 'Results'], ['project', 'Project']]],
];
const LIT = {
  floor: () => S.status !== 'idle', incident: () => !!(S.result?.incident || S.stages.some(s => s.stage === 'detect')),
  trace: () => !!S.result, proof: () => !!S.result, decision: () => !!S.result, results: () => false, project: () => false,
};
let current = null;
const $ = s => document.querySelector(s);

function buildNav() {
  $('#nav').innerHTML = NAV.map(([h, items]) => `<div class="nav-h">${h}</div>${items.map(([id, label]) => `<a class="nav-i" href="#/${id}" data-id="${id}">${icon(id)}<span>${label}</span><i class="dot"></i></a>`).join('')}`).join('');
  $('#railfoot').innerHTML = '<b>AIOps Sentinel</b><br>Akash · Aryan · Syna';
}
function updateNav() {
  document.querySelectorAll('.nav-i').forEach(a => {
    a.classList.toggle('on', a.dataset.id === current);
    a.querySelector('.dot').classList.toggle('lit', LIT[a.dataset.id]());
  });
}
function route() {
  const id = (location.hash.match(/^#\/(\w+)/) || [])[1];
  current = VIEWS[id] ? id : 'floor';
  const root = $('#view');
  root.innerHTML = '';
  root.onclick = null;
  VIEWS[current].mount(root);
  VIEWS[current].update();
  updateNav();
}

async function init() {
  buildNav();
  const bar = mountTopbar($('#topbar'));
  const [st, sc] = await Promise.all([api.state(), api.scenarios()]);
  Object.assign(S, { tenants: st.tenants, server: st.server, llmAvailable: st.llm_available, scenarios: sc });
  st.events.forEach(apply);
  S.next = Math.max(S.next, st.next);
  if (S.run) { bar.setScenario(S.run.scenario); bar.setMode(S.run.mode); }
  refreshTopbar();
  route();
  window.addEventListener('hashchange', route);
  on(() => { VIEWS[current].update(); updateTopbar(); updateNav(); });
  const q = new URLSearchParams(location.search);
  if (!q.has('nostream')) connect(S.next, apply, ok => { S.connected = ok; changed(); }); // nostream: QA screenshots only
  if (q.get('autorun')) {
    bar.setScenario(q.get('autorun')); bar.setMode(q.get('mode') || 'replay'); refreshTopbar();
    api.run({ scenario: q.get('autorun'), mode: q.get('mode') || 'replay', llm: true }).catch(e => notice(e.message));
  }
}
init().catch(e => { document.getElementById('view').innerHTML = `<div class="empty"><b>Console could not start</b>${e.message}</div>`; });
