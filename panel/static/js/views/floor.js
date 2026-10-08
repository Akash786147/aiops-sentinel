import { S, fmtT, latest } from '../store.js';
import { sparkline } from '../charts.js';
import { esc, fmt, setHTML } from '../ui.js';

export const id = 'floor';
const STEPS = [['collect', 'Collect', 'per-route · per-process'], ['detect', 'Detect', 'robust z, change-aware'], ['context', 'Packet', 'signals · errors · diff'],
  ['trace', 'Trace', 'hybrid ranking'], ['test', 'Test', 'fail vs pass'], ['handoff', 'Hand-off', 'human approves']];
const OWNER_CHIP = { orders: 'indigo', inventory: 'orange', payments: 'green' };

export function mount(root) {
  root.innerHTML = `
    <div class="sec-h"><h2>Shared server</h2><span class="sub" data-r="sub"></span></div>
    <section class="stats" data-r="stats"></section>
    <section class="tiles">${S.tenants.map(t => `<article class="tile" data-t="${t.name}">
      <div class="tile-h"><span class="dotl"></span><b>${esc(t.name)}</b><span class="chip own ${OWNER_CHIP[t.name] || ''}">${esc(t.owner)}</span></div>
      <div class="val"><span class="big" data-f="p95">—</span><small>ms p95</small></div><div class="route" data-f="route">waiting for traffic</div>
      <div data-f="spark"></div>
      <div class="mini"><div><span class="label">req/s</span><b data-f="rps">—</b></div><div><span class="label">errors</span><b data-f="err">—</b></div><div><span class="label">cpu</span><b data-f="cpu">—</b></div><div><span class="label">rss</span><b data-f="rss">—</b></div></div>
    </article>`).join('')}</section>
    <div class="sec-h"><h2>Pipeline</h2><span class="sub">each stage lights up as the audit trail records it</span></div>
    <section class="steps">${STEPS.map(([k, name, sub], i) => `<div class="step" data-s="${k}"><span class="no">0${i + 1}</span><span class="tm" data-f="tm"></span><b>${name}</b><div class="dim" style="font-size:12px">${sub}</div><div class="res" data-f="res"></div></div>`).join('')}</section>
    <div class="sec-h"><h2>Event log</h2></div>
    <section class="log" data-r="log"></section>`;
}

function pipeline() {
  const by = st => S.stages.filter(s => s.stage === st);
  const detect = by('detect')[0], ctx = by('context')[0], traces = by('trace'), tests = by('test'), hand = by('handoff');
  const running = S.status === 'running';
  const tele = Object.keys(S.tele).length > 0;
  const inc = detect?.incidents?.[0];
  const hybrid = traces.find(t => t.method === 'hybrid'), llmT = traces.find(t => t.method === 'hybrid+llm');
  const lastT = list => list[list.length - 1]?.t;
  const defs = {
    collect: { done: !!detect || !!S.result, res: S.deploy ? `deployed ${S.deploy.commits.length} commits, restarted ${S.deploy.restarted.length} tenants` : tele ? 'scraping tenants every second' : '', at: S.deploy?.t },
    detect: { done: !!detect, res: detect ? (inc ? `${inc.service} · ${inc.symptoms.join(' + ')} · severity ${fmt(inc.severity)}` : 'no incident detected') : '', at: detect?.t },
    context: { done: !!ctx, res: ctx ? `packet ${String(ctx.packet_digest).slice(0, 8)} · ${ctx.changes} changes · ${ctx.owner}` : '', at: ctx?.t },
    trace: { done: !!hybrid, res: hybrid ? `${hybrid.decision} · confidence ${fmt(hybrid.confidence, 2)}${llmT ? ' · LLM ' + (llmT.valid === false ? 'invalid' : 'agrees') : ''}` : '', at: lastT(traces) },
    test: { done: tests.length > 0, res: tests.map(t => `${t.generator} ${t.confirming ? '✓ confirming' : '✗ not confirming'}`).join(' · '), at: lastT(tests) },
    handoff: { done: hand.length > 0, res: S.approval ? `approved by ${S.approval.approver}` : hand.length ? 'awaiting human approval' : '', at: lastT(hand) },
  };
  let prev = S.deploy?.t ?? S.startedAt, activeSet = false;
  STEPS.forEach(([k]) => {
    const d = defs[k];
    d.state = d.done ? 'done' : (!activeSet && running && (k !== 'collect' || tele)) ? 'active' : 'idle';
    if (d.state === 'active') activeSet = true;
    if (d.done && d.at && prev) { d.time = `${Math.max(0, d.at - prev).toFixed(1)}s`; prev = d.at; }
  });
  return defs;
}

export function update() {
  const root = document.getElementById('view');
  if (!root.querySelector('.tiles')) return;
  const total = { rps: 0, up: 0 };
  const incSvc = S.result?.incident?.service ?? S.stages.find(x => x.stage === 'detect')?.incidents?.[0]?.service;
  S.tenants.forEach(t => {
    const tile = root.querySelector(`[data-t="${t.name}"]`);
    const s = latest(t.name), svc = S.services[t.name];
    tile.classList.toggle('hot', incSvc === t.name);
    tile.classList.toggle('down', !!svc && svc.up === false);
    tile.querySelector('.dotl').className = `dotl ${svc ? (svc.up ? 'up' : 'dn') : ''}`;
    if (svc?.up) total.up++;
    if (!s) return;
    const routes = Object.entries(s.routes);
    const worst = [...routes].sort((a, b) => b[1].p95_ms - a[1].p95_ms)[0];
    const rps = routes.reduce((a, [, v]) => a + v.count, 0), err = routes.reduce((a, [, v]) => a + v.errors, 0);
    total.rps += rps;
    const set = (f, v) => { tile.querySelector(`[data-f=${f}]`).textContent = v; };
    set('p95', worst ? fmt(worst[1].p95_ms, worst[1].p95_ms < 100 ? 1 : 0) : '—');
    set('route', worst ? worst[0] : 'idle');
    set('rps', fmt(rps, 0)); set('err', fmt(err, 0)); set('cpu', s.cpu == null ? '—' : `${fmt(s.cpu, 0)}%`); set('rss', s.rss_mb == null ? '—' : `${fmt(s.rss_mb, 0)} MiB`);
    const pts = (S.tele[t.name] || []).slice(-70).map(r => [r.t, Math.max(0, ...Object.values(r.routes).map(v => v.p95_ms))]);
    setHTML(tile.querySelector('[data-f=spark]'), sparkline(pts, { color: incSvc === t.name ? 'var(--orange)' : 'var(--indigo)', marks: S.deploy?.at ? [S.deploy.at] : [] }));
  });

  const det = S.result?.incident ?? S.stages.find(x => x.stage === 'detect')?.incidents?.[0];
  setHTML(root.querySelector('[data-r=stats]'), [
    ['Tenants up', `${total.up}/${S.tenants.length}`, S.server || 'shared server'],
    ['Requests / s', fmt(total.rps, 0), 'all tenants'],
    ['Incident', det ? esc(det.service) : S.status === 'idle' ? '—' : 'none', det ? `${det.symptoms.join(' + ')} · severity ${fmt(det.severity)}` : 'nothing detected yet'],
    ['Run', esc(S.run ? S.run.scenario : '—'), S.run ? `${S.run.mode}${S.run.llm ? ' · LLM on' : ''} · ${S.status}` : 'press Run'],
  ].map(([l, v, sub]) => `<div class="stat"><div class="label">${l}</div><div class="big">${v}</div><div class="sub">${esc(sub)}</div></div>`).join(''));
  setHTML(root.querySelector('[data-r=sub]'), S.connected ? 'stream connected' : 'stream reconnecting…');

  const defs = pipeline();
  STEPS.forEach(([k]) => {
    const el = root.querySelector(`[data-s="${k}"]`), d = defs[k];
    el.className = `step ${d.state}`;
    el.querySelector('[data-f=res]').textContent = d.res || '';
    el.querySelector('[data-f=tm]').textContent = d.time || '';
  });
  setHTML(root.querySelector('[data-r=log]'), S.log.slice(-14).reverse().map(l => `<div class="k-${l.kind}"><b>${fmtT({ t: l.t })}</b><span>${esc(l.text)}</span></div>`).join('') || '<div><b></b><span>no events yet</span></div>');
}
