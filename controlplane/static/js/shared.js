import { S, actor } from './store.js';
import { api } from './api.js';
import { esc } from './ui.js';
import { notice } from './main.js';

export const PALETTE = ['var(--orange)', 'var(--indigo)', 'var(--green)', 'var(--cyan)', 'var(--amber)', 'var(--red)'];

export function diffView(text) {
  if (!text || !text.trim()) return '<div class="empty sm">No changes.</div>';
  return `<div class="diff">${text.split('\n').map(l => {
    const cls = l.startsWith('+++') || l.startsWith('---') || l.startsWith('diff ') || l.startsWith('index ') ? 'meta' : l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : '';
    return `<div class="${cls}">${esc(l) || ' '}</div>`;
  }).join('')}</div>`;
}

export async function act(name, action, extra = {}) {
  try {
    await api.act(name, action, { actor: actor(), ...extra });
    notice('');
  } catch (e) {
    notice(e.message);
  }
}

export const meter = (label, value, limit, unit, fmtv) => {
  const ratio = value != null && limit ? Math.min(1, value / limit) : 0;
  return `<div class="meter"><span>${label}</span><div class="tr"><i class="${ratio >= 0.95 ? 'crit' : ratio >= 0.75 ? 'hot' : ''}" style="width:${(ratio * 100).toFixed(1)}%"></i></div><b>${value == null ? '—' : fmtv(value)} / ${fmtv(limit)}${unit}</b></div>`;
};

export const DEP_KIND = { healthy: 'ok', starting: 'info', building: 'info', failed: 'bad', rolled_back: 'warn', superseded: '', stopped: '' };
export const INC_KIND = { open: 'bad', investigating: 'info', diagnosed: 'warn', rolled_back: 'warn', needs_attention: 'bad', resolved: 'ok', dismissed: '' };

export function serviceName(n) { return S.services[n] ? n : null; }
