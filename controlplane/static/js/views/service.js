import { S, serviceState, worstP95, sumRoutes, ago, clock, actor } from '../store.js';
import { api } from '../api.js';
import { lineChart } from '../charts.js';
import { esc, fmt, setHTML, pill, chip } from '../ui.js';
import { act, diffView, PALETTE, DEP_KIND } from '../shared.js';
import { notice } from '../main.js';

let P = {}, detail = null, detailKey = '', files = null, current = null, logTimer = null;
const TABS = [['live', 'Live'], ['deployments', 'Deployments'], ['code', 'Code'], ['logs', 'Logs'], ['settings', 'Settings']];

export function mount(root, params) {
  P = params; detail = null; detailKey = ''; files = null; current = null;
  clearInterval(logTimer);
  const n = P.name;
  root.innerHTML = `<div class="hdr"><h1>${esc(n)}</h1><span data-r="state"></span><span class="ver" data-r="ver"></span>
      <div class="acts"><input class="msg" id="msg" placeholder="What changed? (commit message)"><button class="btn" data-a="restart">Restart</button>
      <button class="btn ghost" data-a="rollback">Rollback to last good</button><button class="btn ghost" data-a="stop">Stop</button><button class="btn ghost" data-a="start">Start</button></div></div>
    <div data-r="alert" style="margin-top:12px"></div>
    <nav class="tabs">${TABS.map(([k, l]) => `<a href="#/service/${n}/${k}" class="${P.tab === k ? 'on' : ''}">${l}</a>`).join('')}</nav>
    <div data-r="body"></div>`;
  root.onclick = async e => {
    const a = e.target.closest('[data-a]');
    if (a) {
      const extra = a.dataset.a === 'restart' ? { message: root.querySelector('#msg').value.trim() || undefined } : a.dataset.to ? { to: Number(a.dataset.to) } : {};
      await act(n, a.dataset.a, extra);
      if (a.dataset.a === 'restart') root.querySelector('#msg').value = '';
      return;
    }
    const f = e.target.closest('[data-file]');
    if (f) { e.preventDefault(); openFile(f.dataset.file); }
    if (e.target.id === 'save') saveFile();
    if (e.target.id === 'savesettings') saveSettings();
  };
  const body = root.querySelector('[data-r=body]');
  if (P.tab === 'live') body.innerHTML = `<div class="charts"><div class="card"><h3>p95 latency by route (ms)</h3><div data-r="c1"></div></div><div class="card"><h3>Requests and 5xx per second</h3><div data-r="c2"></div></div>
      <div class="card"><h3>CPU (% of one core)</h3><div data-r="c3"></div></div><div class="card"><h3>Memory (MiB)</h3><div data-r="c4"></div></div></div><div class="legend" data-r="leg"></div>`;
  if (P.tab === 'deployments') body.innerHTML = '<div class="card" style="padding:6px 16px" data-r="deps"></div>';
  if (P.tab === 'code') {
    body.innerHTML = `<div class="editor"><div class="tree" data-r="tree">loading…</div><div><div class="code-h" data-r="fname">Pick a file</div><textarea class="code-edit" id="editor" spellcheck="false" disabled></textarea>
      <div class="acts" style="margin-top:10px"><button class="btn" id="save" disabled>Save</button><span class="muted" style="align-self:center;font-size:12.5px">Saving changes the working copy only. Press <b>Restart</b> to deploy it.</span></div></div></div>
      <div class="sec-h"><h2>Uncommitted changes</h2></div><div data-r="wdiff"></div>`;
    loadFiles();
  }
  if (P.tab === 'logs') {
    body.innerHTML = '<div class="logs" data-r="logs">loading…</div>';
    const pull = () => api.logs(n, 400).then(r => { const el = document.querySelector('[data-r=logs]'); if (el) setHTML(el, r.lines.map(l => `<div class="${/error|exception|traceback/i.test(l) ? 'err' : ''}">${esc(l)}</div>`).join('') || 'no output'); }).catch(() => {});
    pull();
    logTimer = setInterval(() => (location.hash.includes('/logs') ? pull() : clearInterval(logTimer)), 3000);
  }
  if (P.tab === 'settings') body.innerHTML = '<div class="card" data-r="settings"></div>';
  refreshDetail();
}

async function refreshDetail() {
  try { detail = await api.service(P.name); } catch (e) { notice(e.message); return; }
  update(true);
}

async function loadFiles() {
  const r = await api.files(P.name);
  files = r;
  setHTML(document.querySelector('[data-r=tree]'), r.files.map(f => `<a href="#" data-file="${esc(f)}" class="${r.changed.includes(f) ? 'chg' : ''} ${current === f ? 'on' : ''}">${esc(f)}</a>`).join(''));
  const d = await api.diff(P.name);
  setHTML(document.querySelector('[data-r=wdiff]'), diffView(d.diff));
}

async function openFile(path) {
  const r = await api.file(P.name, path);
  current = path;
  const ed = document.getElementById('editor');
  ed.value = r.content; ed.disabled = false;
  document.getElementById('save').disabled = false;
  document.querySelector('[data-r=fname]').textContent = path;
  loadFiles();
}

async function saveFile() {
  try { await api.saveFile(P.name, current, document.getElementById('editor').value, actor()); notice(''); loadFiles(); }
  catch (e) { notice(e.message); }
}

async function saveSettings() {
  const v = id => document.getElementById(id);
  try {
    await api.patchService(P.name, { mem_limit_mb: Number(v('mem').value), cpu_limit: Number(v('cpu').value), auto_rollback: v('auto').checked, owner: v('owner').value });
    notice('Saved. Limits apply from the next Restart.');
    refreshDetail();
  } catch (e) { notice(e.message); }
}

function charts(s) {
  const rows = (S.series[P.name] || []).filter(r => r.t > Date.now() / 1000 - 900);
  const routes = [...new Set(rows.flatMap(r => Object.keys(r.routes || {})))].slice(0, 6);
  const marks = (detail?.deployments || []).filter(d => d.healthy_at && rows.length && d.healthy_at >= rows[0].t)
    .map(d => ({ t: d.healthy_at, label: `#${d.id} ${d.trigger}`, color: d.trigger === 'rollback' ? 'var(--amber)' : 'var(--indigo)' }));
  const lim = (s.cpu_limit || 1) * 100;
  const set = (k, html) => setHTML(document.querySelector(`[data-r=${k}]`), html);
  set('c1', lineChart({ series: routes.map((r, i) => ({ color: PALETTE[i % PALETTE.length], points: rows.map(x => [x.t, x.routes?.[r]?.p95_ms ?? null]) })), marks, h: 260 }));
  set('c2', lineChart({ series: [{ color: 'var(--indigo)', points: rows.map(x => [x.t, sumRoutes(x, 'count')]) }, { color: 'var(--red)', points: rows.map(x => [x.t, sumRoutes(x, 'errors')]) }], marks, h: 260 }));
  set('c3', lineChart({ series: [{ color: 'var(--orange)', points: rows.map(x => [x.t, x.cpu_percent]) }], hlines: [{ y: lim, label: `limit ${lim.toFixed(0)}%`, color: 'var(--red)', dash: true }], marks, h: 260 }));
  set('c4', lineChart({ series: [{ color: 'var(--green)', points: rows.map(x => [x.t, x.rss_mb]) }], hlines: [{ y: s.mem_limit_mb, label: `limit ${s.mem_limit_mb} MiB`, color: 'var(--red)', dash: true }], marks, h: 260 }));
  set('leg', routes.map((r, i) => `<span><i style="border-color:${PALETTE[i % PALETTE.length]}"></i>${esc(r)}</span>`).join('') + '<span><i style="border-color:var(--indigo)"></i>requests</span><span><i style="border-color:var(--red)"></i>5xx / limits</span><span><i style="border-color:var(--amber)"></i>rollback</span>');
}

export function update(force = false) {
  const root = document.getElementById('view');
  const s = S.services[P.name];
  if (!s) { setHTML(root.querySelector('[data-r=body]'), '<div class="empty"><b>Unknown service</b></div>'); return; }
  const k = JSON.stringify([s.current?.id, s.current?.status, s.incident?.id, s.incident?.status, s.busy, s.last_good?.id, s.desired]);
  if (k !== detailKey && !force) { detailKey = k; refreshDetail(); }
  const [label, kind] = serviceState(s);
  setHTML(root.querySelector('[data-r=state]'), pill(label, kind));
  const c = s.current;
  setHTML(root.querySelector('[data-r=ver]'), c ? `running <b>${c.commit.slice(0, 7)}</b> ${esc(c.message)} · since ${ago(c.healthy_at)}${s.last_good ? ` · last good <b>${s.last_good.commit.slice(0, 7)}</b>` : ''}` : 'not running');
  root.querySelectorAll('[data-a]').forEach(b => { b.disabled = s.busy || (b.dataset.a === 'rollback' && !s.last_good) || (b.dataset.a === 'start' && s.desired !== 'stopped') || (b.dataset.a === 'stop' && s.desired === 'stopped'); });
  setHTML(root.querySelector('[data-r=alert]'), s.incident ? `<div class="alertbar ${s.incident.status === 'rolled_back' ? 'warn' : ''}"><b>INC-${s.incident.id}</b> ${esc(s.incident.kind)} · ${esc(s.incident.summary || '')}${s.incident.auto_action ? ` · <b>${esc(s.incident.auto_action)}</b>` : ''}<a href="#/incident/${s.incident.id}">investigation →</a></div>` : s.dirty ? '<div class="alertbar warn">The working copy has uncommitted changes. <b>Restart</b> deploys them.<a href="#/service/' + P.name + '/code">review →</a></div>' : '');
  if (P.tab === 'live') charts(s);
  if (P.tab === 'deployments' && detail) {
    setHTML(root.querySelector('[data-r=deps]'), `<table class="t"><tr><th>#</th><th>commit</th><th>message</th><th>trigger</th><th>status</th><th>started</th><th>healthy</th><th></th></tr>${detail.deployments.map(d => `<tr>
      <td class="mono">${d.id}</td><td class="mono">${d.commit.slice(0, 7)}</td><td>${esc(d.message)}${d.detail?.reason && d.status === 'failed' ? `<br><span class="dim" style="font-size:12px">${esc(d.detail.reason)}</span>` : ''}</td><td>${esc(d.trigger)}</td>
      <td>${pill(d.status.replace('_', ' '), DEP_KIND[d.status] || '')} ${d.last_good ? chip('last good', 'green') : ''}</td><td>${clock(d.created_at)}</td><td>${clock(d.healthy_at)}</td>
      <td>${d.image && d.status !== 'failed' && !(c && c.id === d.id) ? `<button class="btn ghost sm" data-a="rollback" data-to="${d.id}" ${s.busy ? 'disabled' : ''}>Roll back here</button>` : ''}</td></tr>`).join('')}</table>`);
  }
  if (P.tab === 'settings' && detail && !root.querySelector('#mem')) {
    setHTML(root.querySelector('[data-r=settings]'), `<div class="form2"><div class="row2"><label>Memory limit (MiB)<input id="mem" type="number" min="32" value="${detail.mem_limit_mb}"></label><label>CPU limit (cores)<input id="cpu" type="number" step="0.1" min="0.1" value="${detail.cpu_limit}"></label></div>
      <label>Owner<input id="owner" value="${esc(detail.owner || '')}"></label>
      <label style="display:flex;gap:10px;align-items:center"><input id="auto" type="checkbox" ${detail.auto_rollback ? 'checked' : ''}> Roll back automatically on crash loop, OOM kill, sustained unhealthy or memory exhaustion</label>
      <div class="muted" style="font-size:12.5px">Source: ${esc(detail.source)} · module ${esc(detail.module || '—')} · health ${esc(detail.health_path)} · metrics ${esc(detail.metrics_path || 'none')}</div>
      <div><button class="btn" id="savesettings">Save settings</button></div></div>`);
  }
}
