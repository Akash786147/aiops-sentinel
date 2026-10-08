import { esc } from './ui.js';

export function sparkline(points, o = {}) {
  const { w = 260, h = 54, color = 'var(--indigo)', lo, hi, marks = [], fill = true } = o;
  const pts = points.filter(p => p[1] != null);
  if (pts.length < 2) return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"></svg>`;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const ys = pts.map(p => p[1]);
  const a = lo ?? Math.min(...ys), b = Math.max(hi ?? Math.max(...ys), a + 1e-6);
  const X = t => ((t - t0) / (t1 - t0 || 1)) * w;
  const Y = v => h - 3 - ((v - a) / (b - a)) * (h - 8);
  const d = pts.map(([t, v], i) => `${i ? 'L' : 'M'}${X(t).toFixed(1)} ${Y(v).toFixed(1)}`).join('');
  const area = fill ? `<path d="${d}L${w} ${h}L0 ${h}Z" fill="${color}" opacity=".12"/>` : '';
  const mk = marks.filter(t => t >= t0 && t <= t1).map(t => `<line x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="0" y2="${h}" class="spark-mark"/>`).join('');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${area}${mk}<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

const niceMax = v => {
  const steps = [1, 2, 2.5, 5, 10];
  const p = 10 ** Math.floor(Math.log10(v * 1.1 || 1));
  return steps.find(s => s >= (v * 1.1) / p) * p;
};

export function lineChart(o) {
  const { series, w = 760, h = 340, pad = { l: 54, r: 16, t: 18, b: 32 }, unit = '', marks = [], hlines = [], zones = [], t0, t1 } = o;
  const all = series.flatMap(s => s.points.filter(p => p[1] != null));
  if (all.length < 2) return `<svg class="chart" viewBox="0 0 ${w} ${h}"></svg>`;
  const xs = all.map(p => p[0]);
  const T0 = t0 ?? Math.min(...xs), T1 = t1 ?? Math.max(...xs);
  const top = o.yMax ?? niceMax(Math.max(...all.map(p => p[1]), ...hlines.map(l => l.y)));
  const X = t => pad.l + ((t - T0) / (T1 - T0 || 1)) * (w - pad.l - pad.r);
  const Y = v => h - pad.b - (v / top) * (h - pad.t - pad.b);
  let g = '';
  for (let i = 0; i <= 4; i++) {
    const v = (top * i) / 4;
    g += `<line class="grid" x1="${pad.l}" x2="${w - pad.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${pad.l - 10}" y="${Y(v) + 4}" text-anchor="end">${v >= 100 ? Math.round(v) : v.toFixed(1)}</text>`;
  }
  const span = T1 - T0;
  for (let i = 0; i <= 6; i++) {
    const t = T0 + (span * i) / 6;
    g += `<text x="${X(t)}" y="${h - 10}" text-anchor="middle">${Math.round(t - T0)}s</text>`;
  }
  const z = zones.map(zn => `<rect x="${X(zn.t0)}" y="${pad.t}" width="${Math.max(0, X(Math.min(zn.t1, T1)) - X(zn.t0))}" height="${h - pad.t - pad.b}" fill="${zn.color}" opacity="${zn.opacity ?? 0.07}"/>`).join('');
  const hl = hlines.map(l => `<line x1="${pad.l}" x2="${w - pad.r}" y1="${Y(l.y)}" y2="${Y(l.y)}" stroke="${l.color}" stroke-width="1.2" ${l.dash ? 'stroke-dasharray="5 5"' : ''}/><text x="${w - pad.r}" y="${Y(l.y) - 6}" text-anchor="end" style="fill:${l.color}">${esc(l.label)}</text>`).join('');
  const mk = marks.filter(m => m.t >= T0 && m.t <= T1).map(m => `<line x1="${X(m.t)}" x2="${X(m.t)}" y1="${pad.t}" y2="${h - pad.b}" stroke="${m.color}" stroke-width="1.4" stroke-dasharray="3 4"/><text x="${X(m.t) + 6}" y="${pad.t + 12}" style="fill:${m.color}">${esc(m.label)}</text>`).join('');
  const lines = series.map(s => {
    const pts = s.points.filter(p => p[1] != null);
    if (pts.length < 2) return '';
    const d = pts.map(([t, v], i) => `${i ? 'L' : 'M'}${X(t).toFixed(1)} ${Y(v).toFixed(1)}`).join('');
    const last = pts[pts.length - 1];
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/><circle cx="${X(last[0])}" cy="${Y(last[1])}" r="3.5" fill="${s.color}"/>`;
  }).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}"><text x="${pad.l}" y="10">${esc(unit)}</text>${z}${g}${hl}${mk}${lines}</svg>`;
}

export function hbars(rows, o = {}) {
  const { max = 1, format = v => `${Math.round(v * 100)}%` } = o;
  return `<div class="hbars">${rows.map(r => `<div class="hb"><div class="hb-l ${r.hi ? 'hi' : ''}" title="${esc(r.label)}">${esc(r.label)}</div><div class="hb-t">${r.ghost != null ? `<i class="ghost" style="width:${Math.min(100, (r.ghost / max) * 100)}%;background:${r.color || 'var(--indigo)'}"></i>` : ''}<i style="width:${Math.min(100, ((r.value ?? 0) / max) * 100)}%;background:${r.color || 'var(--indigo)'}"></i></div><div class="hb-v">${r.value == null ? '—' : format(r.value)}</div></div>`).join('')}</div>`;
}

export const FEATURES = [
  ['trace', 'Stack frame', 'var(--red)', 2.5], ['call_path', 'Call path', 'var(--orange)', 1.5], ['changed_lines', 'Changed lines', 'var(--indigo)', 1.5],
  ['route', 'Route handler', 'var(--amber)', 1], ['lexical', 'BM25', 'var(--cyan)', 1], ['dense', 'Embedding', 'var(--green)', 1], ['changed_file', 'Changed file', 'var(--dim)', 0.3],
];
export function featureBar(features, maxTotal) {
  const parts = FEATURES.map(([k, label, color, w]) => ({ label, color, v: (features[k] || 0) * w })).filter(p => p.v > 0);
  const total = parts.reduce((a, p) => a + p.v, 0);
  return `<div class="fbar"><div style="width:${Math.min(100, (total / maxTotal) * 100)}%">${parts.map(p => `<i title="${esc(p.label)}: ${p.v.toFixed(2)}" style="flex:${p.v};background:${p.color}"></i>`).join('')}</div></div>`;
}

export function callGraph({ nodes, edges }, focusId) {
  if (!nodes.length) return '';
  const colW = 196, rowH = 42, pad = 10, nw = 160, nh = 30;
  const cols = {};
  nodes.forEach(n => (cols[n.depth] ||= []).push(n));
  const maxDepth = Math.max(...nodes.map(n => n.depth));
  const rows = Math.max(...Object.values(cols).map(c => c.length));
  const pos = {};
  Object.entries(cols).forEach(([d, list]) => list.forEach((n, i) => { pos[n.id] = { x: pad + d * colW, y: pad + i * rowH }; }));
  const w = pad * 2 + maxDepth * colW + nw, h = pad * 2 + (rows - 1) * rowH + nh;
  const e = edges.map(ed => {
    const a = pos[ed.from], b = pos[ed.to];
    if (!a || !b) return '';
    const x1 = a.x + nw, y1 = a.y + nh / 2, x2 = b.x, y2 = b.y + nh / 2, m = (x1 + x2) / 2;
    return `<path class="ge" d="M${x1} ${y1}C${m} ${y1} ${m} ${y2} ${x2} ${y2}"/>`;
  }).join('');
  const n = nodes.map(nd => {
    const p = pos[nd.id];
    const name = nd.symbol.length > 22 ? nd.symbol.slice(0, 21) + '…' : nd.symbol;
    return `<g><rect class="gn ${nd.id === focusId ? 'f' : ''}" x="${p.x}" y="${p.y}" width="${nw}" height="${nh}" rx="7"/><text x="${p.x + 10}" y="${p.y + 19}">${esc(name)}</text></g>`;
  }).join('');
  return `<svg class="graph" viewBox="0 0 ${w} ${h}" width="100%">${e}${n}</svg>`;
}

const TOK = /(#.*$)|("""[\s\S]*?"""|'''[\s\S]*?''')|("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(def|class|return|if|elif|else|for|while|in|not|and|or|import|from|as|with|try|except|raise|assert|lambda|None|True|False|is|pass|yield|async|await|finally)\b|\b(\d+(?:\.\d+)?)\b/gm;
export function highlight(src) {
  let out = '', last = 0;
  src.replace(TOK, (m, c, ds, s, k, n, off) => {
    out += esc(src.slice(last, off));
    const cls = c ? 'c' : ds || s ? 's' : k ? 'k' : 'n';
    out += m.split('\n').map(p => `<span class="t-${cls}">${esc(p)}</span>`).join('\n');
    last = off + m.length;
    return m;
  });
  return out + esc(src.slice(last));
}

export function codeView(src, o = {}) {
  const { focus, changed = [], truth, ctx = 10 } = o;
  const lines = highlight(src).split('\n');
  let a = 1, b = Math.min(lines.length, 48);
  if (focus) { a = Math.max(1, focus[0] - ctx); b = Math.min(lines.length, focus[1] + ctx); }
  const inR = (n, r) => r && n >= r[0] && n <= r[1];
  const rows = [];
  if (a > 1) rows.push(`<div class="gap">⋯ ${a - 1} lines above</div>`);
  for (let n = a; n <= b; n++) {
    const cls = [inR(n, focus) ? 'hit' : '', changed.some(r => inR(n, r)) ? 'chg' : '', inR(n, truth) ? 'truth' : ''].join(' ');
    rows.push(`<div class="ln ${cls}"><span class="no">${n}</span><span class="tx">${lines[n - 1] || ' '}</span></div>`);
  }
  if (b < lines.length) rows.push(`<div class="gap">⋯ ${lines.length - b} lines below</div>`);
  return `<div class="code">${rows.join('')}</div>`;
}
