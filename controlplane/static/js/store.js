import { api } from './api.js';

export const S = {
  overview: null, services: {}, order: [], series: {}, incidents: [], audit: [], connected: false, next: 0,
  actor: (() => { try { return localStorage.getItem('sentinel.actor') || ''; } catch { return ''; } })(),
};
export function setActor(name) { S.actor = name; try { localStorage.setItem('sentinel.actor', name); } catch { /* storage blocked */ } }
export const actor = () => S.actor || 'operator';

const listeners = new Set();
export const on = fn => (listeners.add(fn), () => listeners.delete(fn));
let queued = false;
export function changed() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; listeners.forEach(fn => fn(S)); });
}

const timers = {};
function soon(key, fn, ms = 250) {
  clearTimeout(timers[key]);
  timers[key] = setTimeout(fn, ms);
}

export async function refreshServices() {
  const list = await api.services();
  S.order = list.map(s => s.name);
  S.services = Object.fromEntries(list.map(s => [s.name, { ...s, latest: s.latest || S.services[s.name]?.latest }]));
  changed();
}
export async function refreshIncidents() { S.incidents = await api.incidents(); changed(); }
export async function refreshOverview() { S.overview = await api.overview(); changed(); }

export async function load() {
  const [overview, incidents, audit] = await Promise.all([api.overview(), api.incidents(), api.audit(200)]);
  S.overview = overview;
  S.order = overview.services.map(s => s.name);
  S.services = Object.fromEntries(overview.services.map(s => [s.name, s]));
  S.incidents = incidents;
  S.audit = audit;
  const series = await Promise.all(S.order.map(n => api.series(n, 900).catch(() => [])));
  S.order.forEach((n, i) => { S.series[n] = series[i]; });
  S.next = (await api.head()).next;
  changed();
}

export function apply(ev) {
  if (ev.n < S.next) return;
  S.next = ev.n + 1;
  const d = ev.data;
  switch (ev.kind) {
    case 'telemetry': {
      const rows = (S.series[d.service] ||= []);
      rows.push(d);
      if (rows.length > 900) rows.shift();
      if (S.services[d.service]) S.services[d.service].latest = d;
      break;
    }
    case 'deployment': soon('svc', refreshServices); soon('ov', refreshOverview, 800); break;
    case 'incident': soon('inc', refreshIncidents); soon('svc', refreshServices); break;
    case 'audit': S.audit.unshift(d); if (S.audit.length > 400) S.audit.pop(); break;
  }
  changed();
}

export function serviceState(s) {
  if (!s) return ['unknown', ''];
  if (s.busy) return ['working…', 'info'];
  if (s.desired === 'stopped') return ['stopped', ''];
  if (s.incident) {
    const st = s.incident.status;
    if (st === 'rolled_back') return ['rolled back', 'warn'];
    if (st === 'needs_attention') return ['needs attention', 'bad'];
    return ['incident', 'bad'];
  }
  if (!s.current) return ['not running', 'warn'];
  if (s.current.status === 'healthy') return ['healthy', 'ok'];
  if (s.current.status === 'starting') return ['starting', 'info'];
  return [s.current.status, 'bad'];
}

export const worstP95 = row => Math.max(0, ...Object.values(row.routes || {}).map(r => r.p95_ms));
export const sumRoutes = (row, key) => Object.values(row.routes || {}).reduce((a, r) => a + (r[key] || 0), 0);
export const ago = t => {
  if (!t) return '—';
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return `${s.toFixed(0)}s ago`;
  if (s < 3600) return `${(s / 60).toFixed(0)}m ago`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h ago`;
  return `${(s / 86400).toFixed(1)}d ago`;
};
export const clock = t => (t ? new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');
