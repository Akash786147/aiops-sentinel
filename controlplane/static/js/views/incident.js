import { S, ago, clock, actor } from '../store.js';
import { api } from '../api.js';
import { FEATURES, featureBar, codeView, highlight } from '../charts.js';
import { esc, fmt, setHTML, pill, chip } from '../ui.js';
import { diffView, INC_KIND } from '../shared.js';
import { notice } from '../main.js';

let ID = null, data = null, key = '', code = {}, sel = 0;

export function mount(root, params) {
  ID = params.id; data = null; key = ''; code = {}; sel = 0;
  root.innerHTML = '<div data-r="all"><div class="empty"><b>Loading…</b></div></div>';
  root.onclick = async e => {
    const s = e.target.closest('.suspect');
    if (s) { sel = Number(s.dataset.i); render(); return; }
    if (e.target.id === 'approve') {
      const who = document.getElementById('approver').value.trim();
      try { await api.approve(ID, { approver: who, note: document.getElementById('note').value.trim() }); notice(''); fetchData(); }
      catch (err) { notice(err.message); }
    }
    if (e.target.id === 'dismiss') { try { await api.dismiss(ID, { approver: actor(), actor: actor() }); fetchData(); } catch (err) { notice(err.message); } }
    if (e.target.id === 'again') { try { await api.reinvestigate(ID); notice('Investigation restarted.'); } catch (err) { notice(err.message); } }
  };
  fetchData();
}

async function fetchData() {
  try { data = await api.incident(ID); } catch (e) { setHTML(document.querySelector('[data-r=all]'), `<div class="empty"><b>${esc(e.message)}</b></div>`); return; }
  render();
}

function loadCode(path, ref) {
  const k = `${path}@${ref}`;
  if (code[k] !== undefined) return code[k];
  code[k] = null;
  api.file(data.incident.service, path, ref).then(r => { code[k] = r.content; render(); }).catch(() => { code[k] = false; render(); });
  return null;
}

function render() {
  const box = document.querySelector('[data-r=all]');
  if (!box || !data) return;
  const inc = data.incident, dg = inc.diagnosis || {}, dep = data.deployment;
  const working = ['open', 'investigating'].includes(inc.status) && !dg.suspects && !dg.error;
  const signals = (inc.signals || []).slice(-8).reverse();
  const timeline = data.audit.map(a => `<div class="tl ${['auto_rollback', 'approved_fix', 'investigated'].includes(a.action) ? 'ok' : ''}"><time>${clock(a.at)}</time><b>${esc(a.action.replaceAll('_', ' '))}</b><div class="muted">${esc(a.actor)}${a.detail?.summary ? ' · ' + esc(a.detail.summary) : ''}${a.detail?.reason ? ' · ' + esc(a.detail.reason) : ''}${a.detail?.note ? ' · “' + esc(a.detail.note) + '”' : ''}</div></div>`).join('');

  let diag = '';
  if (dg.error) diag = `<div class="alertbar">Investigation failed: ${esc(dg.error)} <a href="#" id="again">try again</a></div>`;
  else if (working) diag = '<div class="empty"><b>Investigating…</b>Building the evidence packet, ranking suspects and running the confirming test in the sandbox.</div>';
  else if (dg.suspects) {
    const suspects = dg.suspects.slice(0, 6);
    sel = Math.min(sel, Math.max(0, suspects.length - 1));
    const top = suspects[sel];
    const maxTotal = Math.max(1, ...suspects.map(s => FEATURES.reduce((a, [k, , , w]) => a + (s.features?.[k] || 0) * w, 0)));
    const ranges = (dg.packet?.changes || []).filter(c => c.behavioural && top && c.file === top.path).map(c => [c.start, c.end]);
    const src = top ? loadCode(top.path, dg.versions?.bad) : null;
    const tests = Object.entries(dg.tests || {}).map(([name, t]) => `<div class="card" style="margin-bottom:14px"><div style="display:flex;gap:10px;align-items:center"><b>${name === 'template' ? 'Template / start-up test' : 'LLM test'}</b>${pill(t.confirming ? 'confirming' : 'not confirming', t.confirming ? 'ok' : 'bad')}
        <span class="muted" style="font-size:12.5px">${t.guard?.length ? 'guard: ' + esc(t.guard.join('; ')) : `bad version: ${esc(t.faulty?.outcome || '—')} · last good version: ${esc(t.fixed?.outcome || '—')}`}</span></div>
        ${t.code ? `<details style="margin-top:10px"><summary class="muted" style="cursor:pointer">test code</summary><div class="code" style="margin-top:8px">${highlight(t.code).split('\n').map((l, i) => `<div class="ln"><span class="no">${i + 1}</span><span class="tx">${l || ' '}</span></div>`).join('')}</div></details>` : ''}
        ${t.faulty?.detail ? `<div class="logs" style="margin-top:10px;max-height:110px">${esc(t.faulty.detail)}</div>` : ''}</div>`).join('');
    const patch = dg.patch || {};
    const canApprove = patch.applies && !['resolved', 'dismissed'].includes(inc.status);
    const restored = inc.status === 'rolled_back' && !patch.applies;
    if (restored) patch.summary = `${patch.summary || ''} (already live: the automatic rollback restored the last good code)`;
    diag = `<div class="sec-h"><h2>Diagnosis</h2><span class="sub">${dg.llm?.model ? 'hybrid trace + ' + esc(dg.llm.model) : 'hybrid trace'} · packet ${esc((dg.packet?.digest || '').slice(0, 8))}</span></div>
      <div class="card" style="font-size:15px;line-height:1.55">${esc(dg.hypothesis || 'No hypothesis.')}</div>
      <div class="cols c2"><div>
        <div class="sec-h"><h2>Ranked suspects</h2><span class="sub">click one to see its code</span></div>${suspects.map((s, i) => `<div class="suspect ${i === sel ? 'on' : ''}" data-i="${i}"><div class="suspect-h"><span class="rank">${i + 1}</span><b>${esc(s.symbol)}</b><span class="score">${fmt(s.score, 2)}</span></div><div class="where">${esc(s.path)}:${s.start}–${s.end}</div>${featureBar(s.features || {}, maxTotal)}${i === sel && s.reasons?.length ? `<ul class="reasons">${s.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}</div>`).join('') || '<div class="empty sm">No code suspects.</div>'}
        ${dg.exceptions?.length ? `<div class="sec-h"><h2>Exceptions</h2></div>${dg.exceptions.map(x => `<div class="card" style="margin-bottom:10px"><b class="mono">${esc(x.exception)}</b> <span class="muted">${esc(x.message)}</span><div class="mono dim" style="font-size:12px;margin-top:6px">${(x.frames || []).map(f => `${esc(f.file)}:${f.line} in ${esc(f.function)}`).join('<br>')}</div></div>`).join('')}` : ''}
      </div><div>
        <div class="sec-h"><h2>Code in the bad version</h2><span class="sub">${dg.versions ? `${dg.versions.bad.slice(0, 7)} vs last good ${dg.versions.good.slice(0, 7)}` : ''}</span></div>
        ${top ? (src ? `<div class="code-h">${esc(top.path)} ${chip('lines ' + top.start + '–' + top.end, 'indigo')}</div>${codeView(src, { focus: [top.start, top.end], changed: ranges })}` : `<div class="empty sm">${src === false ? 'Source not available.' : 'Loading…'}</div>`) : ''}

      </div></div>
      <div class="sec-h"><h2>Confirming tests</h2><span class="sub">must fail on the bad version and pass on the last good version</span></div>${tests || '<div class="empty sm">No test for this incident type.</div>'}
      <div class="sec-h"><h2>Proposed fix</h2><span class="sub">${esc(patch.summary || '')} · ${esc(patch.source || '')}${patch.applies || restored ? '' : ' · does not apply to the current code'}</span></div>
      ${diffView(inc.patch)}
      <div class="card" style="margin-top:14px"><div class="form2" style="max-width:none"><div class="row2"><label>Approver<input id="approver" value="${esc(S.actor)}" placeholder="your name"></label><label>Note<input id="note" placeholder="optional"></label></div>
        <div class="acts"><button class="btn" id="approve" ${canApprove ? '' : 'disabled'}>Approve: apply and deploy</button><button class="btn ghost" id="dismiss" ${['resolved', 'dismissed'].includes(inc.status) ? 'disabled' : ''}>${restored ? 'Close: keep the rollback' : 'Dismiss'}</button><button class="btn ghost" id="again">Investigate again</button></div>
        <div class="muted" style="font-size:12.5px">Approve applies the patch to the working copy, commits it as “Sentinel fix for INC-${inc.id}”, and runs the normal Restart (build, health gate, swap). Nothing is applied without a named approver.</div></div></div>`;
  }

  setHTML(box, `<div class="hdr"><h1>INC-${inc.id}</h1>${pill(inc.kind, 'bad')}${pill(inc.status.replace('_', ' '), INC_KIND[inc.status] || '')}<a class="ver" href="#/service/${inc.service}">${esc(inc.service)}</a><span class="ver">opened ${ago(inc.opened_at)}</span></div>
    <p class="muted" style="margin:10px 0 0">${esc(inc.summary || '')}</p>
    ${inc.auto_action ? `<div class="alertbar warn" style="margin-top:12px"><b>Automatic action:</b> ${esc(inc.auto_action)}</div>` : ''}
    <div class="cols c2" style="margin-top:6px"><div><div class="sec-h"><h2>Signals</h2></div><div class="card" style="padding:6px 16px">${signals.length ? `<table class="t"><tr><th>signal</th><th>detail</th><th>when</th></tr>${signals.map(s => `<tr><td>${esc(s.kind)}</td><td>${esc(s.description || s.summary || (s.exit_code != null ? 'exit code ' + s.exit_code : '') || (s.rss_mb ? fmt(s.rss_mb, 0) + ' MiB' : '') || '')}${s.evidence ? `<div class="logs" style="margin-top:6px;max-height:120px">${esc(s.evidence)}</div>` : ''}</td><td class="mono">${clock(s.at)}</td></tr>`).join('')}</table>` : '<span class="muted">none</span>'}</div>
      ${dep ? `<div class="sec-h"><h2>Deployment</h2></div><div class="card"><b class="mono">#${dep.id} ${dep.commit.slice(0, 7)}</b> ${esc(dep.message)} · ${pill(dep.status.replace('_', ' '), '')}<div class="muted" style="font-size:12.5px;margin-top:6px">${esc(dep.trigger)} · ${clock(dep.created_at)}${data.last_good ? ` · last good #${data.last_good.id} ${data.last_good.commit.slice(0, 7)}` : ''}</div></div>` : ''}</div>
      <div><div class="sec-h"><h2>Timeline</h2></div><div class="card"><div class="timeline">${timeline || '<span class="muted">—</span>'}</div></div></div></div>
    ${diag}`);
}

export function update() {
  const inc = S.incidents.find(i => i.id === ID);
  const k = inc ? `${inc.status}|${inc.kind}|${inc.auto_action}|${(inc.signals || []).length}|${inc.diagnosed}` : '';
  if (k && k !== key) { key = k; fetchData(); }
}
