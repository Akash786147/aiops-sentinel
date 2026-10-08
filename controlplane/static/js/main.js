import { S, on, load, apply, changed, serviceState, setActor } from './store.js';
import { api, connect } from './api.js';
import { esc, icon } from './ui.js';
import * as overview from './views/overview.js';
import * as service from './views/service.js';
import * as incidents from './views/incidents.js';
import * as incident from './views/incident.js';
import * as lab from './views/lab.js';
import * as audit from './views/audit.js';
import * as benchmark from './views/benchmark.js';
import * as add from './views/add.js';

const ROUTES = [
  [/^#?\/?(overview)?$/, overview, () => ({})],
  [/^#\/service\/([\w-]+)(?:\/(\w+))?$/, service, m => ({ name: m[1], tab: m[2] || 'live' })],
  [/^#\/incidents$/, incidents, () => ({})],
  [/^#\/incident\/(\d+)$/, incident, m => ({ id: Number(m[1]) })],
  [/^#\/lab(?:\/([\w-]+))?$/, lab, m => ({ name: m[1] })],
  [/^#\/audit$/, audit, () => ({})],
  [/^#\/benchmark$/, benchmark, () => ({})],
  [/^#\/add$/, add, () => ({})],
];
const $ = s => document.querySelector(s);
let view = null, key = '';

export function notice(text, kind = '') {
  $('#notice').innerHTML = text ? `<div class="notice ${kind}"><span>${esc(text)}</span><button class="btn ghost sm" id="nclose">Dismiss</button></div>` : '';
  if (text) $('#nclose').onclick = () => notice('');
}

function nav() {
  const open = S.incidents.filter(i => !['resolved', 'dismissed'].includes(i.status)).length;
  const here = location.hash || '#/overview';
  const item = (href, ico, label, extra = '') => `<a class="nav-i ${here.startsWith(href) ? 'on' : ''}" href="${href}">${icon(ico)}<span>${label}</span>${extra}</a>`;
  $('#nav').innerHTML = `<div class="nav-h">PLATFORM</div>${item('#/overview', 'floor', 'Overview')}`
    + `<div class="nav-h">SERVICES</div>${S.order.map(n => { const [, k] = serviceState(S.services[n]); return `<a class="nav-svc ${here.startsWith('#/service/' + n) ? 'on' : ''}" href="#/service/${n}">${esc(n)}<i class="sd ${k}"></i></a>`; }).join('')}`
    + item('#/add', 'project', 'Add service')
    + `<div class="nav-h">OPERATIONS</div>${item('#/incidents', 'incident', 'Incidents', open ? `<span class="badge">${open}</span>` : '')}${item('#/lab', 'proof', 'Test lab')}${item('#/audit', 'decision', 'Audit trail')}`
    + `<div class="nav-h">RESEARCH</div>${item('#/benchmark', 'results', 'Benchmark')}`;
  $('#railfoot').innerHTML = `<b>AIOps Sentinel</b><br>runtime: ${esc(S.overview?.runtime || '…')}<br>Akash · Aryan · Syna`;
}

function topbar() {
  const o = S.overview, t = o?.traffic;
  const healthy = S.order.filter(n => serviceState(S.services[n])[1] === 'ok').length;
  $('#topbar').innerHTML = `<div class="where"><small>${esc(o?.host?.name || 'server')}</small><b>${healthy}/${S.order.length} services healthy</b></div>
    <label class="switch ${t?.enabled ? 'on' : ''}" id="traffic" title="Background load against every running service"><i></i>Traffic</label>
    <input class="msg" id="actor" placeholder="Your name (for the audit trail)" value="${esc(S.actor)}" style="background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:7px 10px;width:220px">
    <div class="links">${o ? Object.entries(o.links).map(([k, v]) => `<a href="${esc(v)}" target="_blank" rel="noopener">${k[0].toUpperCase() + k.slice(1)}</a>`).join('') : ''}</div>
    <div class="state ${S.connected ? 'done' : 'failed'}"><i></i>${S.connected ? 'live' : 'reconnecting'}</div>`;
  $('#traffic').onclick = async () => { try { S.overview.traffic = await api.traffic(!S.overview.traffic.enabled); changed(); } catch (e) { notice(e.message); } };
  $('#actor').onchange = e => setActor(e.target.value.trim());
}

function route() {
  const hash = location.hash || '#/overview';
  for (const [re, mod, params] of ROUTES) {
    const m = hash.match(re);
    if (!m) continue;
    const p = params(m);
    const k = hash;
    if (k !== key) {
      key = k;
      view = mod;
      const root = $('#view');
      root.innerHTML = '';
      root.onclick = null;
      root.oninput = null;
      mod.mount(root, p);
    }
    view.update();
    nav();
    return;
  }
  location.hash = '#/overview';
}

let topbarKey = '';
function refreshChrome() {
  const k = JSON.stringify([S.overview?.traffic?.enabled, S.connected, S.order.map(n => serviceState(S.services[n])[0]), S.overview?.host?.name]);
  if (k !== topbarKey && document.activeElement?.id !== 'actor') { topbarKey = k; topbar(); }
  nav();
}

async function init() {
  await load();
  topbar();
  route();
  window.addEventListener('hashchange', route);
  on(() => { view?.update(); refreshChrome(); });
  const q = new URLSearchParams(location.search);
  if (!q.has('nostream')) connect(S.next, apply, ok => { S.connected = ok; changed(); });
  setInterval(() => api.overview().then(o => { S.overview = o; changed(); }).catch(() => {}), 10000);
}
init().catch(e => { $('#view').innerHTML = `<div class="empty"><b>Sentinel could not load</b>${esc(e.message)}</div>`; });
