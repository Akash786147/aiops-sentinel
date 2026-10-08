async function j(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(typeof body.detail === 'string' ? body.detail : (body.detail?.[0]?.msg || r.statusText));
    e.status = r.status;
    throw e;
  }
  return body;
}
const post = (url, body) => j(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
export const api = {
  state: () => j('/api/state'),
  scenarios: () => j('/api/scenarios'),
  results: () => j('/api/results'),
  run: body => post('/api/run', body),
  approve: body => post('/api/approve', body),
  code: path => j('/api/code?path=' + encodeURIComponent(path)),
};
export function connect(since, onEvent, onStatus) {
  const es = new EventSource('/api/events?since=' + since);
  es.onmessage = m => onEvent(JSON.parse(m.data));
  es.onopen = () => onStatus(true);
  es.onerror = () => onStatus(false);
  return es;
}
