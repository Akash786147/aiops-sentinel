import { S, fmtT } from '../store.js';
import { api } from '../api.js';
import { esc, fmt, setHTML, chip } from '../ui.js';
import { notice } from '../topbar.js';

export const id = 'decision';
const WORDS = { code_fix: 'Propose a code fix', capacity_scale: 'Add capacity', investigate: 'Keep investigating', none: 'No action' };

export function mount(root) {
  root.innerHTML = `<div class="cols c2"><div><div class="sec-h"><h2>Recommendation</h2></div><div class="card" data-r="rec"></div></div>
    <div><div class="sec-h"><h2>Audit trail</h2><span class="sub">every decision, in order</span></div><div class="card"><div class="timeline" data-r="tl"></div></div></div></div>`;
  root.onclick = async e => {
    if (e.target.id !== 'approve') return;
    const who = root.querySelector('#who').value.trim(), note = root.querySelector('#note').value.trim();
    if (who.length < 2) { notice('Enter the approver name (at least 2 characters).'); return; }
    notice('');
    try { await api.approve({ approver: who, note }); } catch (err) { notice(err.message); }
  };
}

export function update() {
  const root = document.getElementById('view');
  const rec = root.querySelector('[data-r=rec]');
  if (!rec) return;
  const r = S.result;
  if (!r) {
    setHTML(rec, `<div class="empty" style="border:0"><b>No decision yet</b>${S.status === 'running' ? 'Waiting for the pipeline…' : 'Run a scenario first.'}</div>`);
  } else {
    // keep what the user typed while the card re-renders
    const who = root.querySelector('#who')?.value ?? '', note = root.querySelector('#note')?.value ?? '';
    const focused = document.activeElement?.id;
    const top = r.suspects?.[0]?.features || {};
    const ticks = [
      [top.trace > 0 || top.changed_lines > 0, 'Code evidence: a stack frame or a behaviour-changing line'],
      [top.route > 0 || top.call_path > 0, "The suspect is on the anomalous route's call path"],
      [Object.values(r.tests || {}).some(t => t.confirming), 'A generated test failed on the faulty code and passed on the known-good code'],
      [(r.confidence ?? 0) >= 0.6, 'Confidence at or above 0.6'],
    ];
    const c = r.confidence ?? 0, circ = 2 * Math.PI * 62;
    const approved = S.approval;
    const ownerName = S.tenants.find(t => t.name === r.incident?.service)?.owner;
    setHTML(rec, `<div style="display:flex;gap:24px;align-items:center"><div class="gauge"><svg viewBox="0 0 150 150"><circle cx="75" cy="75" r="62" fill="none" stroke="var(--line)" stroke-width="9"/><circle cx="75" cy="75" r="62" fill="none" stroke="${c >= 0.6 ? 'var(--green)' : 'var(--amber)'}" stroke-width="9" stroke-linecap="round" stroke-dasharray="${(circ * c).toFixed(1)} ${circ.toFixed(1)}"/></svg><div class="big">${fmt(c, 2)}</div></div>
      <div><div class="label">recommended action</div><div class="action">${esc(WORDS[r.action] || r.action || '—')}</div><div class="muted" style="margin-top:6px">${r.incident ? `${esc(r.incident.service)}${ownerName ? ' · owner ' + esc(ownerName) : ''}` : 'no incident detected'}</div></div></div>
      <ul class="ticks">${ticks.map(([y, t]) => `<li class="${y ? 'y' : ''}"><i>${y ? '✓' : '·'}</i>${esc(t)}</li>`).join('')}</ul>
      ${approved ? `<div class="verdict ok" style="margin-top:18px"><span class="pill ok">approved</span><span>by ${esc(approved.approver)}${approved.note ? ' · ' + esc(approved.note) : ''}. No code was changed.</span></div>`
        : r.action === 'none' ? '' : `<div class="form"><input id="who" placeholder="Approver name" value="${esc(who)}"><input id="note" placeholder="Note (optional)" value="${esc(note)}"><button class="btn" id="approve">Approve hand-off</button></div>`}
      <ul class="not plain"><li>Sentinel never edits code, restarts or scales anything.</li><li>Approval records a named human decision in the audit trail only.</li></ul>`);
    if (focused === 'who' || focused === 'note') root.querySelector('#' + focused)?.focus();
  }
  const rows = S.stages.map(s => {
    const meta = [s.packet_digest && `packet ${String(s.packet_digest).slice(0, 8)}`, s.model, s.prompt_tokens && `${s.prompt_tokens}+${s.completion_tokens} tokens`, s.latency_s && `${fmt(s.latency_s)} s`,
      s.confidence != null && `confidence ${fmt(s.confidence, 2)}`, s.approver && s.decision === 'approved' && `by ${s.approver}`].filter(Boolean);
    return `<div class="tl ${s.decision === 'approved' || s.confirming ? 'ok' : ''}"><time>${fmtT({ t: s.t })}</time><b>${esc(s.stage)}${s.method ? ' · ' + esc(s.method) : ''}${s.generator ? ' · ' + esc(s.generator) : ''}</b><div class="muted">${esc(s.decision)}</div><div class="meta">${meta.map(m => chip(m)).join('')}</div></div>`;
  }).join('');
  setHTML(root.querySelector('[data-r=tl]'), rows || '<span class="muted">No audit events yet.</span>');
}
