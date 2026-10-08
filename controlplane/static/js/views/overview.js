import { S, serviceState, worstP95, sumRoutes, ago } from '../store.js';
import { sparkline } from '../charts.js';
import { esc, fmt, setHTML, pill, chip } from '../ui.js';
import { act, meter } from '../shared.js';

export function mount(root) {
  root.innerHTML = `<div class="sec-h"><h2>Server</h2><span class="sub" data-r="hostsub"></span></div>
    <section class="stats" data-r="host"></section>
    <div class="sec-h"><h2>Services</h2><span class="sub">Sentinel builds, runs and watches each one. Restart deploys the current code.</span></div>
    <section class="svc-grid" data-r="grid"></section>
    <div class="cols c2" style="margin-top:12px"><div><div class="sec-h"><h2>Open incidents</h2></div><div data-r="inc"></div></div>
      <div><div class="sec-h"><h2>Recent activity</h2><a class="sub" href="#/audit">full audit trail →</a></div><div class="log" data-r="feed" style="max-height:340px"></div></div></div>`;
  root.onclick = e => {
    const b = e.target.closest('[data-act]');
    if (b) act(b.dataset.svc, b.dataset.act);
  };
}

function tile(name) {
  const s = S.services[name];
  const [label, kind] = serviceState(s);
  const rows = (S.series[name] || []).slice(-120);
  const last = s.latest || rows[rows.length - 1];
  const spark = sparkline(rows.map(r => [r.t, worstP95(r)]), { color: kind === 'bad' ? 'var(--red)' : 'var(--indigo)', h: 44 });
  const c = s.current;
  const inc = s.incident;
  return `<article class="svc ${kind === 'bad' ? 'bad' : kind === 'warn' ? 'warn' : ''}">
    <div class="svc-h"><span class="sd ${kind}" style="width:9px;height:9px;border-radius:50%"></span><a href="#/service/${name}">${esc(name)}</a>${chip(s.owner || '')}${pill(label, kind)}</div>
    <div class="ver">${c ? `<b>${c.commit.slice(0, 7)}</b> ${esc(c.message)} · ${ago(c.healthy_at || c.created_at)}` : 'not deployed'}${s.last_good && c && s.last_good.id === c.id ? ' · <span style="color:var(--green)">last good</span>' : ''}${s.dirty ? ' · <span style="color:var(--orange)">uncommitted changes</span>' : ''}</div>
    ${inc ? `<div class="alertbar ${inc.status === 'rolled_back' ? 'warn' : ''}"><b>INC-${inc.id}</b>${esc(inc.summary || inc.kind)}<a href="#/incident/${inc.id}">open →</a></div>` : ''}
    ${spark}
    ${meter('CPU', last?.cpu_percent, (s.cpu_limit || 1) * 100, '%', v => fmt(v, 0))}
    ${meter('Memory', last?.rss_mb, s.mem_limit_mb, ' MiB', v => fmt(v, 0))}
    <div class="kv"><div><span class="label">p95</span><b>${last ? fmt(worstP95(last), 0) + ' ms' : '—'}</b></div><div><span class="label">req/s</span><b>${last ? fmt(sumRoutes(last, 'count'), 0) : '—'}</b></div>
      <div><span class="label">5xx</span><b>${last ? fmt(sumRoutes(last, 'errors'), 0) : '—'}</b></div><div><span class="label">restarts</span><b>${last?.restarts ?? '—'}</b></div></div>
    <div class="acts"><button class="btn sm" data-act="restart" data-svc="${name}" ${s.busy ? 'disabled' : ''}>Restart</button>
      <button class="btn ghost sm" data-act="rollback" data-svc="${name}" ${s.busy || !s.last_good ? 'disabled' : ''}>Rollback to last good</button>
      <a class="btn ghost sm" href="#/lab/${name}" style="text-decoration:none">Test lab</a></div>
  </article>`;
}

export function update() {
  const root = document.getElementById('view');
  const o = S.overview;
  if (!o) return;
  const h = o.host;
  const healthy = S.order.filter(n => serviceState(S.services[n])[1] === 'ok').length;
  const open = S.incidents.filter(i => !['resolved', 'dismissed'].includes(i.status));
  setHTML(root.querySelector('[data-r=hostsub]'), `${esc(h.name)} · runtime ${esc(o.runtime)} · traffic ${o.traffic.enabled ? 'on' : 'off'} (${o.traffic.sent} requests sent)`);
  setHTML(root.querySelector('[data-r=host]'), [
    ['Services healthy', `${healthy}/${S.order.length}`, `${S.order.length - healthy} need attention`],
    ['Open incidents', String(open.length), open.length ? `latest: INC-${open[0].id} ${open[0].service}` : 'all clear'],
    ['Host CPU', `${fmt(h.cpu_percent, 0)}%`, `${h.cpus} vCPU${h.load ? ` · load ${h.load.map(x => x.toFixed(2)).join(' ')}` : ''}`],
    ['Host memory', `${fmt(h.mem_used_mb / 1024, 1)} GB`, `of ${fmt(h.mem_total_mb / 1024, 1)} GB`],
  ].map(([l, v, sub]) => `<div class="stat"><div class="label">${l}</div><div class="big">${v}</div><div class="sub">${esc(sub)}</div></div>`).join(''));
  setHTML(root.querySelector('[data-r=grid]'), S.order.map(tile).join('') || '<div class="empty"><b>No services yet</b><a href="#/add">Add one</a></div>');
  setHTML(root.querySelector('[data-r=inc]'), open.length ? `<div class="card" style="padding:6px 16px"><table class="t"><tr><th>id</th><th>service</th><th>kind</th><th>status</th><th>opened</th></tr>${open.slice(0, 8).map(i => `<tr class="click" onclick="location.hash='#/incident/${i.id}'"><td class="mono">INC-${i.id}</td><td>${esc(i.service)}</td><td>${esc(i.kind)}</td><td>${pill(i.status.replace('_', ' '), i.status === 'rolled_back' || i.status === 'diagnosed' ? 'warn' : 'bad')}</td><td>${ago(i.opened_at)}</td></tr>`).join('')}</table></div>` : '<div class="empty sm"><b>No open incidents</b>Use the Test lab to inject a fault and watch Sentinel react.</div>');
  setHTML(root.querySelector('[data-r=feed]'), S.audit.slice(0, 18).map(a => `<div><b>${ago(a.at)}</b><span>${esc(a.actor)} · ${esc(a.action.replaceAll('_', ' '))}${a.service ? ' · ' + esc(a.service) : ''}${a.incident_id ? ' · INC-' + a.incident_id : ''}</span></div>`).join('') || '<div><span>no activity yet</span></div>');
}
