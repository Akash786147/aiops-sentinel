export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmt = (v, d = 1) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d));
export const pct = v => (v == null || Number.isNaN(Number(v)) ? '—' : `${Math.round(v * 100)}%`);
export function setHTML(el, html) {
  if (el && el.__html !== html) { el.innerHTML = html; el.__html = html; }
}
export const chip = (text, kind = '') => `<span class="chip ${kind}">${esc(text)}</span>`;
export const pill = (text, kind = '') => `<span class="pill ${kind}">${esc(text)}</span>`;
const ICONS = {
  floor: '<rect x="2.5" y="3" width="6" height="6" rx="1.2"/><rect x="11.5" y="3" width="6" height="6" rx="1.2"/><rect x="2.5" y="11" width="6" height="6" rx="1.2"/><rect x="11.5" y="11" width="6" height="6" rx="1.2"/>',
  incident: '<path d="M2 10h3.5l2-5 3 10 2-5H18"/>',
  trace: '<circle cx="5" cy="4.5" r="1.8"/><circle cx="5" cy="15.5" r="1.8"/><circle cx="15" cy="9" r="1.8"/><path d="M5 6.3v7.4M5 11c0-2 2-2 6-2h2.2"/>',
  proof: '<circle cx="10" cy="10" r="7.5"/><path d="M6.5 10.2l2.5 2.5 4.6-5"/>',
  decision: '<path d="M10 2.5l6 2.2v4.6c0 3.6-2.5 6.4-6 8-3.5-1.6-6-4.4-6-8V4.7z"/>',
  results: '<path d="M4 16V9M10 16V4M16 16v-5"/>',
  project: '<circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.2v.1"/>',
};
export const icon = name => `<svg class="ico" viewBox="0 0 20 20" aria-hidden="true">${ICONS[name] || ''}</svg>`;
