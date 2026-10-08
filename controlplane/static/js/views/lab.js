import { S, actor, serviceState } from '../store.js';
import { api } from '../api.js';
import { esc, setHTML, pill, chip } from '../ui.js';
import { act, diffView } from '../shared.js';
import { notice } from '../main.js';

let NAME = null, lab = null, preview = null, labKey = '';

export function mount(root, params) {
  NAME = params.name || S.order[0] || null; lab = null; preview = null; labKey = '';
  root.innerHTML = `<div class="sec-h"><h2>Test lab</h2><span class="sub">put a sample fault into a monitored service, restart it, and watch Sentinel detect, roll back and investigate</span></div>
    <div class="steps2">${[['1 Pick a fault', 'Each one is a realistic code change with a known cause.'], ['2 Apply', 'Writes the change into the service working copy. Nothing runs yet.'],
      ['3 Restart', 'Sentinel commits, builds and deploys it exactly like a real change.'], ['4 Watch', 'Overview and Incidents show detection, rollback and the investigation.']]
      .map(([h, p]) => `<div class="card"><span class="label">${h.slice(0, 1)}</span><b>${h.slice(2)}</b><p>${p}</p></div>`).join('')}</div>
    <div class="hdr" style="margin-bottom:14px"><div class="seg" data-r="pick"></div><span data-r="state"></span>
      <div class="acts"><button class="btn warn" id="restart">Restart now</button><button class="btn ghost" id="reset">Reset to last good</button><a class="btn ghost" data-r="watch" style="text-decoration:none">Watch service →</a></div></div>
    <div data-r="work"></div><div class="sec-h"><h2>Fault recipes</h2></div><div class="recipes" data-r="recipes"></div><div data-r="preview"></div>`;
  root.onclick = async e => {
    const p = e.target.closest('[data-pick]');
    if (p) { location.hash = '#/lab/' + p.dataset.pick; return; }
    const b = e.target.closest('[data-recipe]');
    try {
      if (b && b.dataset.op === 'preview') { preview = { id: b.dataset.recipe, diff: (await api.preview(NAME, b.dataset.recipe)).diff }; render(); }
      if (b && b.dataset.op === 'apply') { await api.applyFault(NAME, b.dataset.recipe, actor()); preview = null; notice(`Applied ${b.dataset.recipe}. Press Restart now to deploy it.`); load(); }
      if (e.target.id === 'reset') { await api.resetLab(NAME, actor()); notice('Working copy restored to the last good version. Restart to deploy it.'); load(); }
      if (e.target.id === 'restart') { const r = lab?.changed?.length ? `Test lab: ${lab.changed.join(', ')}` : undefined; await act(NAME, 'restart', { message: r }); }
    } catch (err) { notice(err.message); }
  };
  load();
}

async function load() {
  if (!NAME) return;
  try { lab = await api.lab(NAME); } catch (e) { notice(e.message); return; }
  render();
}

function render() {
  const root = document.getElementById('view');
  if (!NAME) { setHTML(root.querySelector('[data-r=recipes]'), '<div class="empty"><b>No services</b><a href="#/add">Add one first</a></div>'); return; }
  setHTML(root.querySelector('[data-r=pick]'), S.order.map(n => `<button data-pick="${n}" class="${n === NAME ? 'on' : ''}">${esc(n)}</button>`).join(''));
  root.querySelector('[data-r=watch]').href = `#/service/${NAME}`;
  const s = S.services[NAME];
  const [label, kind] = serviceState(s);
  setHTML(root.querySelector('[data-r=state]'), pill(label, kind));
  root.querySelector('#restart').disabled = !!s?.busy;
  root.querySelector('#reset').disabled = !!s?.busy;
  if (!lab) return;
  setHTML(root.querySelector('[data-r=work]'), lab.dirty ? `<div class="alertbar warn"><b>Working copy changed:</b> ${esc(lab.changed.join(', '))}. Press <b>Restart now</b> to deploy it, or Reset.</div><div style="margin-top:10px">${diffView(lab.diff)}</div>` : '<div class="alertbar warn" style="background:transparent;border-color:var(--line)">Working copy is clean: the running code matches the repository.</div>');
  setHTML(root.querySelector('[data-r=recipes]'), lab.recipes.map(r => `<div class="recipe ${r.available ? '' : 'off'}"><div style="display:flex;gap:8px;align-items:center"><h4>${esc(r.title)}</h4>${chip(r.id, r.kind === 'generic' ? 'orange' : 'indigo')}</div>
    <p>${esc(r.description)}</p><div class="exp">${esc(r.expect)}</div><div class="muted mono" style="font-size:11.5px">${esc(r.files.join(', '))}</div>
    <div class="acts"><button class="btn ghost sm" data-recipe="${r.id}" data-op="preview" ${r.available ? '' : 'disabled'}>Preview</button><button class="btn sm" data-recipe="${r.id}" data-op="apply" ${r.available && !s?.busy ? '' : 'disabled'}>Apply</button>${r.available ? '' : '<span class="muted" style="font-size:12px;align-self:center">already applied or not applicable</span>'}</div></div>`).join(''));
  setHTML(root.querySelector('[data-r=preview]'), preview ? `<div class="sec-h"><h2>Preview: ${esc(preview.id)}</h2></div>${diffView(preview.diff)}` : '');
}

export function update() {
  const s = S.services[NAME];
  const k = JSON.stringify([s?.current?.id, s?.busy, s?.dirty, s?.incident?.status]);
  if (k !== labKey) { labKey = k; load(); } else render();
}
