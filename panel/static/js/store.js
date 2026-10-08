export const S = {
  next: 0, status: 'idle', reason: null, run: null, startedAt: null, endedAt: null,
  server: '', tenants: [], scenarios: [], llmAvailable: false, connected: false,
  services: {}, tele: {}, deploy: null, stages: [], result: null, approval: null, log: [], results: null,
};
const listeners = new Set();
export const on = fn => (listeners.add(fn), () => listeners.delete(fn));
let queued = false;
export function changed() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; listeners.forEach(fn => fn(S)); });
}
export function resetRun() {
  Object.assign(S, { status: 'idle', reason: null, run: null, startedAt: null, endedAt: null, services: {}, tele: {}, deploy: null, stages: [], result: null, approval: null, log: [] });
}
export const fmtT = ev => `+${((ev.t - (S.startedAt ?? ev.t))).toFixed(1)}s`;

function describe(ev) {
  const d = ev.data;
  switch (ev.kind) {
    case 'run': return d.state === 'started' ? `run started · ${d.scenario} · ${d.mode}` : `run ${d.state}${d.reason ? ' · ' + d.reason : ''}`;
    case 'service': return `${d.name} ${d.up ? 'up' : 'down'}`;
    case 'deploy': return `deployed ${d.commits.length} commits · restarted ${d.restarted.join(', ')}`;
    case 'stage': return `${d.stage}${d.method ? ' · ' + d.method : ''}${d.generator ? ' · ' + d.generator : ''} → ${d.decision}`;
    case 'result': return 'diagnosis ready';
    default: return null;
  }
}

export function apply(ev) {
  if (ev.n < S.next) return;
  S.next = ev.n + 1;
  const d = ev.data;
  switch (ev.kind) {
    case 'run':
      if (d.state === 'started') { resetRun(); S.run = d; S.status = 'running'; S.startedAt = ev.t; }
      else { S.status = d.state; S.reason = d.reason || null; S.endedAt = ev.t; }
      break;
    case 'service': S.services[d.name] = { ...S.services[d.name], ...d }; break;
    case 'telemetry': {
      const rows = (S.tele[d.service] ||= []);
      rows.push(d);
      if (rows.length > 600) rows.shift();
      S.services[d.service] = { ...S.services[d.service], up: d.up };
      break;
    }
    case 'deploy': S.deploy = { ...d, t: ev.t }; break;
    case 'stage':
      if (d.decision === 'approved') S.approval = d;
      S.stages.push({ ...d, t: ev.t });
      break;
    case 'result': S.result = d; break;
  }
  const text = describe(ev);
  if (text) { S.log.push({ t: ev.t, kind: ev.kind, text }); if (S.log.length > 200) S.log.shift(); }
  changed();
}

export function worstRoute(service) {
  const best = {};
  (S.tele[service] || []).forEach(s => Object.entries(s.routes).forEach(([r, v]) => { best[r] = Math.max(best[r] || 0, v.p95_ms); }));
  return Object.entries(best).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

export function focus() {
  const inc = S.result?.incident;
  if (inc) {
    const sig = inc.signals.find(s => s.kind === 'latency' && s.route) || inc.signals.find(s => s.route) || inc.signals[0];
    return { service: inc.service, route: sig?.route ?? null, kind: sig?.kind ?? 'latency' };
  }
  const det = S.stages.find(s => s.stage === 'detect')?.incidents?.[0];
  if (det) return { service: det.service, route: worstRoute(det.service), kind: det.symptoms[0] === 'traffic' ? 'latency' : det.symptoms[0] };
  return null;
}

export function metricSeries(service, kind, route) {
  return (S.tele[service] || []).map(s => {
    let v = null;
    if (!s.up) v = null;
    else if (kind === 'cpu') v = s.cpu;
    else if (kind === 'memory') v = s.rss_mb;
    else if (kind === 'errors') { const r = route ? s.routes[route] : null; v = r && r.count ? r.errors / r.count : null; }
    else v = route ? (s.routes[route]?.p95_ms ?? null) : null;
    return [s.t, v];
  });
}
export const latest = service => { const rows = S.tele[service]; return rows?.[rows.length - 1]; };
