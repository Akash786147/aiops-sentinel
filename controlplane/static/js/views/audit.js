import { S, clock, ago } from '../store.js';
import { esc, setHTML, chip } from '../ui.js';

let filter = '';
const SKIP = new Set(['service', 'incident_id']);

export function mount(root) {
  root.innerHTML = `<div class="sec-h"><h2>Audit trail</h2><span class="sub">every action by people and by Sentinel, newest first (stored in SQLite)</span></div>
    <div class="seg" data-r="filter" style="margin-bottom:14px"></div><div class="card" style="padding:6px 16px" data-r="list"></div>`;
  root.onclick = e => { const b = e.target.closest('[data-f]'); if (b) { filter = b.dataset.f; update(); } };
}

export function update() {
  const root = document.getElementById('view');
  setHTML(root.querySelector('[data-r=filter]'), ['', ...S.order].map(n => `<button data-f="${n}" class="${filter === n ? 'on' : ''}">${n || 'all'}</button>`).join(''));
  const rows = S.audit.filter(a => !filter || a.service === filter).slice(0, 300);
  setHTML(root.querySelector('[data-r=list]'), rows.length ? `<table class="t"><tr><th>time</th><th>actor</th><th>action</th><th>service</th><th>incident</th><th>detail</th></tr>${rows.map(a => `<tr>
    <td class="mono" title="${ago(a.at)}">${clock(a.at)}</td><td>${a.actor === 'sentinel' ? chip('sentinel', 'indigo') : esc(a.actor)}</td><td>${esc(a.action.replaceAll('_', ' '))}</td>
    <td>${esc(a.service || '')}</td><td>${a.incident_id ? `<a href="#/incident/${a.incident_id}">INC-${a.incident_id}</a>` : ''}</td>
    <td class="muted" style="font-size:12.5px">${esc(Object.entries(a.detail || {}).filter(([k]) => !SKIP.has(k)).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ').slice(0, 220))}</td></tr>`).join('')}</table>` : '<div class="empty sm">No events.</div>');
}
