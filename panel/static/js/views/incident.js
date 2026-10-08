import { S, focus, metricSeries, latest } from '../store.js';
import { lineChart, sparkline } from '../charts.js';
import { esc, fmt, setHTML, chip, pill } from '../ui.js';

export const id = 'incident';
const UNIT = { latency: 'p95 latency, ms', cpu: 'cpu, %', memory: 'resident memory, MiB', errors: 'error rate' };
const ALERT = { latency: 500, cpu: 80, memory: 500, errors: 0.05 };

export function mount(root) {
  root.innerHTML = `<div data-r="empty"></div><div class="cols c2" data-r="body" style="display:none">
    <div><div class="sec-h"><h2 data-r="title">Affected route</h2></div><div class="card"><div data-r="chart"></div><div class="legend" data-r="legend"></div></div>
      <div class="sec-h"><h2>Other tenants</h2><span class="sub">same window</span></div><div class="cols eq2" data-r="others"></div></div>
    <div><div class="sec-h"><h2>Incident</h2></div><div class="card" data-r="card"></div>
      <div class="sec-h"><h2>Signals</h2></div><div class="card" data-r="signals"></div>
      <div class="sec-h"><h2>Fixed-threshold alert</h2></div><div class="card" data-r="thr"></div></div></div>`;
}

export function update() {
  const root = document.getElementById('view');
  const f = focus();
  const body = root.querySelector('[data-r=body]');
  if (!f) {
    body.style.display = 'none';
    setHTML(root.querySelector('[data-r=empty]'), `<div class="empty"><b>${S.status === 'running' ? 'Watching for an incident…' : 'No incident yet'}</b>${S.status === 'running' ? 'The detector compares each tenant after the deployment with its own baseline.' : 'Run a scenario from the top bar.'}</div>`);
    return;
  }
  setHTML(root.querySelector('[data-r=empty]'), '');
  body.style.display = '';
  const pts = metricSeries(f.service, f.kind, f.route);
  const band = S.result?.band;
  const hlines = [];
  const maxV = Math.max(0, ...pts.map(p => p[1] ?? 0));
  if (band) {
    hlines.push({ y: band.median, label: `baseline ${fmt(band.median)}`, color: 'var(--green)', dash: false });
    hlines.push({ y: band.bar, label: `detector fires above ${fmt(band.bar)}`, color: 'var(--indigo)', dash: true });
  }
  const alert = ALERT[f.kind];
  if (alert && maxV > alert * 0.4) hlines.push({ y: alert, label: `fixed alert ${alert}`, color: 'var(--red)', dash: true });
  const marks = S.deploy?.at ? [{ t: S.deploy.at, label: 'deploy', color: 'var(--amber)' }] : [];
  const zones = S.deploy?.at && pts.length ? [{ t0: S.deploy.at, t1: pts[pts.length - 1][0], color: '#f08a3c' }] : [];
  setHTML(root.querySelector('[data-r=title]'), `${esc(f.service)} · ${esc(f.route || f.kind)}`);
  setHTML(root.querySelector('[data-r=chart]'), lineChart({ series: [{ name: f.route || f.service, color: 'var(--orange)', points: pts }], hlines, marks, zones, unit: UNIT[f.kind] || f.kind }));
  setHTML(root.querySelector('[data-r=legend]'), `<span><i style="border-color:var(--orange)"></i>${esc(f.route || f.kind)}</span>${band ? '<span><i style="border-color:var(--green)"></i>baseline</span><span><i style="border-color:var(--indigo)"></i>detector firing level</span>' : ''}${alert && maxV > alert * 0.4 ? '<span><i style="border-color:var(--red)"></i>fixed alert level</span>' : ''}<span><i style="border-color:var(--amber)"></i>deployment</span>`);

  const inc = S.result?.incident ?? S.stages.find(x => x.stage === 'detect')?.incidents?.[0];
  const owner = S.tenants.find(t => t.name === f.service)?.owner;
  setHTML(root.querySelector('[data-r=card]'), `<div class="label">tenant</div><div class="big" style="margin:4px 0 10px">${esc(f.service)}</div><div style="display:flex;gap:6px;flex-wrap:wrap">${(inc?.symptoms || []).map(s => chip(s, 'orange')).join('')}${owner ? chip(owner) : ''}</div><div class="label" style="margin-top:14px">severity (robust z)</div><div class="big">${fmt(inc?.severity)}</div>`);
  const signals = S.result?.incident?.signals || [];
  setHTML(root.querySelector('[data-r=signals]'), signals.length ? `<table class="t"><tr><th>signal</th><th class="n">baseline → observed</th><th class="n">z</th></tr>${signals.slice(0, 6).map(s => `<tr><td>${esc(s.kind)}${s.route ? `<br><span class="dim mono" style="font-size:11.5px">${esc(s.route)}</span>` : ''}</td><td class="n">${fmt(s.baseline)} → ${fmt(s.observed)}</td><td class="n">${fmt(s.z)}</td></tr>`).join('')}</table>` : '<span class="muted">waiting for the packet…</span>');
  const fired = alert != null && maxV >= alert;
  setHTML(root.querySelector('[data-r=thr]'), `<div style="display:flex;gap:12px;align-items:center">${pill(fired ? 'fired' : 'silent', fired ? 'ok' : 'warn')}<span class="muted">${alert ? `Classic rule: ${f.kind} above ${alert}. Peak seen: ${fmt(maxV, f.kind === 'errors' ? 2 : 0)}.` : 'No fixed rule for this signal.'}</span></div>`);

  const others = S.tenants.filter(t => t.name !== f.service);
  setHTML(root.querySelector('[data-r=others]'), others.map(t => {
    const route = Object.keys(latest(t.name)?.routes || {})[0];
    const p = (S.tele[t.name] || []).map(r => [r.t, Math.max(0, ...Object.values(r.routes).map(v => v.p95_ms))]);
    return `<div class="card"><div style="display:flex;justify-content:space-between"><b>${esc(t.name)}</b><span class="muted mono" style="font-size:12px">${esc(route || '')}</span></div>${sparkline(p, { color: 'var(--indigo)', marks: S.deploy?.at ? [S.deploy.at] : [] })}</div>`;
  }).join(''));
}
