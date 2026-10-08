import { S, actor } from '../store.js';
import { api } from '../api.js';
import { esc, setHTML } from '../ui.js';
import { notice } from '../main.js';

export function mount(root) {
  root.innerHTML = `<div class="sec-h"><h2>Add a service</h2><span class="sub">Sentinel clones it, builds it, runs it with limits and starts watching it</span></div>
    <div class="cols eq2"><div class="card"><b>Bundled sample</b><p class="muted" style="font-size:13px">Ready-made services with Prometheus metrics, health checks and fault recipes.</p><div class="acts" data-r="samples"></div></div>
    <div class="card"><b>Your own repository</b><p class="muted" style="font-size:13px">Any git repository with a <span class="mono">Dockerfile</span> at its root that listens on the port below and answers the health path. Add a <span class="mono">sentinel.json</span> to enable code tracing (see samples/orders/sentinel.json).</p>
      <div class="form2" style="max-width:none"><div class="row2"><label>Name<input id="name" placeholder="billing"></label><label>Branch<input id="branch" placeholder="main"></label></div>
      <label>Git URL<input id="url" placeholder="https://github.com/you/billing.git"></label>
      <div class="row2"><label>Memory limit (MiB)<input id="mem" type="number" value="256"></label><label>CPU limit (cores)<input id="cpu" type="number" step="0.1" value="0.5"></label></div>
      <div><button class="btn" id="add">Add and deploy</button></div></div></div></div>`;
  root.onclick = async e => {
    const s = e.target.closest('[data-sample]');
    try {
      if (s) { await api.addService({ kind: 'sample', name: s.dataset.sample, actor: actor() }); location.hash = '#/service/' + s.dataset.sample; }
      if (e.target.id === 'add') {
        const v = id => document.getElementById(id).value.trim();
        await api.addService({ kind: 'git', name: v('name'), url: v('url'), branch: v('branch') || null, mem_limit_mb: Number(v('mem')), cpu_limit: Number(v('cpu')), actor: actor() });
        location.hash = '#/service/' + v('name');
      }
    } catch (err) { notice(err.message); }
  };
}

export function update() {
  const free = (S.overview?.samples || []).filter(n => !S.services[n]);
  setHTML(document.querySelector('[data-r=samples]'), free.length ? free.map(n => `<button class="btn ghost" data-sample="${n}">${esc(n)}</button>`).join('') : '<span class="muted">All samples are already added.</span>');
}
