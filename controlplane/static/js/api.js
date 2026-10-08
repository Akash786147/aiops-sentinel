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
const send = (method, url, body) => j(url, { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) });
const enc = encodeURIComponent;
export const api = {
  overview: () => j('/api/overview'),
  services: () => j('/api/services'),
  service: n => j(`/api/services/${enc(n)}`),
  addService: body => send('POST', '/api/services', body),
  patchService: (n, body) => send('PATCH', `/api/services/${enc(n)}`, body),
  act: (n, action, body) => send('POST', `/api/services/${enc(n)}/${action}`, body),
  series: (n, seconds = 600) => j(`/api/services/${enc(n)}/series?seconds=${seconds}`),
  logs: (n, tail = 300) => j(`/api/services/${enc(n)}/logs?tail=${tail}`),
  files: n => j(`/api/services/${enc(n)}/files`),
  file: (n, path, ref) => j(`/api/services/${enc(n)}/file?path=${enc(path)}${ref ? '&ref=' + enc(ref) : ''}`),
  saveFile: (n, path, content, actor) => send('PUT', `/api/services/${enc(n)}/file`, { path, content, actor }),
  diff: n => j(`/api/services/${enc(n)}/diff`),
  incidents: () => j('/api/incidents'),
  incident: id => j(`/api/incidents/${id}`),
  approve: (id, body) => send('POST', `/api/incidents/${id}/approve`, body),
  dismiss: (id, body) => send('POST', `/api/incidents/${id}/dismiss`, body),
  reinvestigate: id => send('POST', `/api/incidents/${id}/investigate`),
  lab: n => j(`/api/lab/${enc(n)}`),
  preview: (n, recipe) => send('POST', `/api/lab/${enc(n)}/preview`, { recipe }),
  applyFault: (n, recipe, actor) => send('POST', `/api/lab/${enc(n)}/apply`, { recipe, actor }),
  resetLab: (n, actor) => send('POST', `/api/lab/${enc(n)}/reset`, { actor }),
  audit: (limit = 200, service) => j(`/api/audit?limit=${limit}${service ? '&service=' + enc(service) : ''}`),
  traffic: enabled => send('POST', '/api/traffic', { enabled }),
  results: () => j('/api/results'),
  head: () => j('/api/events/head'),
};
export function connect(since, onEvent, onStatus) {
  const es = new EventSource('/api/events?since=' + since);
  es.onmessage = m => onEvent(JSON.parse(m.data));
  es.onopen = () => onStatus(true);
  es.onerror = () => onStatus(false);
  return es;
}
