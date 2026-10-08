import { S, ago } from '../store.js';
import { esc, setHTML, pill } from '../ui.js';
import { INC_KIND } from '../shared.js';

export function mount(root) {
  root.innerHTML = `<div class="sec-h"><h2>Incidents</h2><span class="sub">opened by the detector, Alertmanager or a failed deployment; each one is investigated automatically</span></div>
    <div class="card" style="padding:6px 16px" data-r="list"></div>`;
}

export function update() {
  const root = document.getElementById('view');
  setHTML(root.querySelector('[data-r=list]'), S.incidents.length ? `<table class="t"><tr><th>id</th><th>service</th><th>kind</th><th>status</th><th>summary</th><th>automatic action</th><th>opened</th></tr>${S.incidents.map(i => `<tr class="click" onclick="location.hash='#/incident/${i.id}'">
    <td class="mono">INC-${i.id}</td><td>${esc(i.service)}</td><td>${esc(i.kind)}</td><td>${pill(i.status.replace('_', ' '), INC_KIND[i.status] || '')}</td>
    <td>${esc(i.summary || '')}</td><td>${esc(i.auto_action || '—')}</td><td>${ago(i.opened_at)}</td></tr>`).join('')}</table>` : '<div class="empty sm"><b>No incidents</b>Inject a fault from the Test lab to see one.</div>');
}
