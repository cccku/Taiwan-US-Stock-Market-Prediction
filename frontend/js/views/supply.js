import { api } from '../api.js';
import { fmtPct, html, stockHref } from '../format.js';

let data = null;
let selected = null;
let onResize = null;

export function unmount() {
  if (onResize) window.removeEventListener('resize', onResize);
  onResize = null;
}

const isDemandLink = (l) => /^demand/i.test(l.what);

/** Column = longest supply path from a raw source (demand links excluded to keep it acyclic). */
function layers(d) {
  const incoming = new Map(d.nodes.map((n) => [n.id, []]));
  d.links.filter((l) => !isDemandLink(l)).forEach((l) => incoming.get(l.target)?.push(l.source));
  const memo = new Map();
  const depth = (id, seen = new Set()) => {
    if (memo.has(id)) return memo.get(id);
    if (seen.has(id)) return 0;
    seen.add(id);
    const parents = incoming.get(id) || [];
    const v = parents.length ? 1 + Math.max(...parents.map((p) => depth(p, seen))) : 0;
    seen.delete(id);
    memo.set(id, v);
    return v;
  };
  d.nodes.forEach((n) => depth(n.id));
  // Pure suppliers sit one column before their nearest customer instead of all at the far left.
  for (const n of d.nodes) {
    if ((incoming.get(n.id) || []).length) continue;
    const customers = d.links.filter((l) => l.source === n.id && !isDemandLink(l)).map((l) => memo.get(l.target));
    if (customers.length) memo.set(n.id, Math.max(0, Math.min(...customers) - 1));
  }
  const cols = [];
  for (const n of d.nodes) (cols[memo.get(n.id)] ||= []).push(n);
  return cols.filter(Boolean).map((col) => col.sort((a, b) =>
    (a.kind === b.kind ? 0 : a.kind === 'stock' ? -1 : 1) || (a.group || '').localeCompare(b.group || '')));
}

function columnTitle(col) {
  const names = [...new Set(col.map((n) => (n.kind === 'stock' ? n.group : n.label)))];
  return names.length > 2 ? `${names.slice(0, 2).join(' · ')} …` : names.join(' · ');
}

function nodeTpl(n) {
  const cls = n.outlook === 'up' ? 'pred-up' : n.outlook === 'down' ? 'pred-down' : 'pred-neutral';
  return html`
  <div class="chain-node ${n.kind} ${selected === n.id ? 'selected' : ''}" data-node="${n.id}" title="${n.detail || ''}">
    <div class="n-name">${n.label}</div>
    <div class="n-sub">${n.kind === 'stock'
      ? html`<span>${n.market} · ${n.id}</span><span class="${cls}">${fmtPct(n.expected_return)}</span>`
      : html`<span>External</span>`}</div>
  </div>`;
}

function detailTpl() {
  if (!selected) return html`<p class="muted" style="margin:0">Select a company or node to see what it buys and sells within the chain.</p>`;
  const node = data.nodes.find((n) => n.id === selected);
  const label = (id) => data.nodes.find((n) => n.id === id)?.label || id;
  const up = data.links.filter((l) => l.target === selected);
  const down = data.links.filter((l) => l.source === selected);
  const link = (id) => (data.nodes.find((n) => n.id === id)?.kind === 'stock'
    ? html`<a href="${stockHref(id)}">${label(id)}</a>` : html`<span>${label(id)}</span>`);
  return html`
    <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline">
      <h2>${node.label}</h2>
      ${node.kind === 'stock' ? html`<a class="btn" href="${stockHref(node.id)}">Open details →</a>` : ''}
    </div>
    <p class="muted" style="margin:4px 0 12px">${node.detail}</p>
    <div class="grid-2">
      <div><div class="muted small">Buys from / depends on</div>
        <ul class="chain-list">${up.length ? up.map((l) => html`<li>${link(l.source)} <span class="muted">${l.what}</span></li>`) : html`<li class="muted">—</li>`}</ul></div>
      <div><div class="muted small">Sells to / enables</div>
        <ul class="chain-list">${down.length ? down.map((l) => html`<li>${link(l.target)} <span class="muted">${l.what}</span></li>`) : html`<li class="muted">—</li>`}</ul></div>
    </div>`;
}

function drawLines(root) {
  const grid = root.querySelector('.chain-grid');
  const svg = root.querySelector('svg.chain-lines');
  if (!grid || !svg) return;
  const base = grid.getBoundingClientRect();
  svg.setAttribute('width', grid.scrollWidth);
  svg.setAttribute('height', grid.scrollHeight);
  const box = (id) => {
    const el = grid.querySelector(`[data-node="${CSS.escape(id)}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { l: r.left - base.left, r: r.right - base.left, y: r.top - base.top + r.height / 2, b: r.bottom - base.top };
  };
  const paths = data.links.map((l) => {
    const a = box(l.source);
    const b = box(l.target);
    if (!a || !b) return '';
    const touches = selected && (l.source === selected || l.target === selected);
    const cls = [isDemandLink(l) ? 'demand' : '', touches ? 'hl' : '', selected && !touches ? 'faded' : ''].join(' ');
    let d;
    if (b.l > a.r) {
      const mid = (a.r + b.l) / 2;
      d = `M${a.r},${a.y}C${mid},${a.y} ${mid},${b.y} ${b.l},${b.y}`;
    } else { // backward (demand) link: loop underneath
      const low = Math.max(a.b, b.b) + 24;
      d = `M${a.l},${a.y}C${a.l - 40},${low} ${b.r + 40},${low} ${b.r},${b.y}`;
    }
    return `<path class="${cls}" d="${d}"/>`;
  });
  svg.innerHTML = paths.join('');
}

function draw(root) {
  const cols = layers(data);
  const connected = new Set(selected ? [selected] : []);
  if (selected) data.links.forEach((l) => {
    if (l.source === selected) connected.add(l.target);
    if (l.target === selected) connected.add(l.source);
  });
  root.innerHTML = html`
  <section class="page-head">
    <div>
      <h1>Supply chain</h1>
      <p class="muted">How demand and supply connect across the watchlist. Lines run from supplier to customer; the dashed line is demand flowing back.
        Percentages are each company's predicted move.</p>
    </div>
  </section>
  <div class="card card-pad">
    <div class="chain-wrap">
      <div class="chain-grid" style="grid-template-columns:repeat(${cols.length}, 176px)">
        <svg class="chain-lines"></svg>
        ${cols.map((col) => html`<div class="chain-col"><div class="chain-col-title">${columnTitle(col)}</div>${col.map(nodeTpl)}</div>`)}
      </div>
    </div>
  </div>
  <div class="card card-pad" style="margin-top:16px">${detailTpl()}</div>`;

  if (selected) root.querySelectorAll('.chain-node').forEach((el) => el.classList.toggle('dim', !connected.has(el.dataset.node)));
  root.querySelectorAll('.chain-node').forEach((el) => {
    el.addEventListener('click', () => { selected = selected === el.dataset.node ? null : el.dataset.node; draw(root); });
    el.addEventListener('dblclick', () => { if (el.classList.contains('stock')) location.hash = stockHref(el.dataset.node); });
  });
  requestAnimationFrame(() => drawLines(root));
}

export async function render(root, _params, { isStale } = {}) {
  const fresh = await api.supplyChain();
  if (isStale?.()) return;
  data = fresh;
  draw(root);
  if (!onResize) {
    onResize = () => drawLines(root);
    window.addEventListener('resize', onResize);
  }
}
