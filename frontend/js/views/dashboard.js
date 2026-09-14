import { api } from '../api.js';
import {
  arrow, dirClass, fmtPct, fmtPrice, fmtSigned, html, OUTLOOK_LABEL, raw, stockHref, timeAgo,
} from '../format.js';
import { getPrefs, loadLocal, savePrefs, saveLocal, setPrefsLocal } from '../state.js';

const UI_KEY = 'dashboard-ui';
const ui = loadLocal(UI_KEY, { market: 'ALL', group: '', price: '', sort: 'default' });
let data = null;
let dragging = false;

export const isBusy = () => dragging;

export async function render(root, _params, { isStale } = {}) {
  const fresh = await api.dashboard();
  if (isStale?.()) return;
  data = fresh;
  setPrefsLocal(data.prefs);
  draw(root);
}

// ── filtering & sorting ─────────────────────────────────────────────────────
function matches(r) {
  if (ui.market !== 'ALL' && r.market !== ui.market) return false;
  if (ui.group && r.group !== ui.group) return false;
  switch (ui.price) {
    case 'rising': return (r.change ?? 0) > 0;
    case 'falling': return (r.change ?? 0) < 0;
    case 'pred-up': return r.outlook === 'up';
    case 'pred-down': return r.outlook === 'down';
    case 'pred-neutral': return r.outlook === 'neutral';
    default: return true;
  }
}

const SORTS = {
  default: (a, b) => (a.favorite_rank ?? 0) - (b.favorite_rank ?? 0) || a.market.localeCompare(b.market) * -1,
  expected: (a, b) => (b.expected_return ?? -9) - (a.expected_return ?? -9),
  'expected-asc': (a, b) => (a.expected_return ?? 9) - (b.expected_return ?? 9),
  change: (a, b) => (b.change_pct ?? -9) - (a.change_pct ?? -9),
  'change-asc': (a, b) => (a.change_pct ?? 9) - (b.change_pct ?? 9),
  name: (a, b) => a.name.localeCompare(b.name),
};

function sorted(rows, isFavorites) {
  const cmp = SORTS[ui.sort] || SORTS.default;
  if (ui.sort === 'default' && !isFavorites) return rows; // keep watchlist order
  return [...rows].sort(cmp);
}

// ── rendering ───────────────────────────────────────────────────────────────
function pillarChips(p) {
  const fmt = (v) => (v == null ? '–' : v.toFixed(1));
  return html`<div class="pillars">
    <span class="pill" title="Leadership / team">L <b>${fmt(p.leadership)}</b></span>
    <span class="pill" title="Product">P <b>${fmt(p.product)}</b></span>
    <span class="pill" title="Price (valuation)">$ <b>${fmt(p.price)}</b></span>
  </div>`;
}

function rowTpl(r, draggable) {
  const predArrow = r.outlook === 'up' ? '▲' : r.outlook === 'down' ? '▼' : '≈';
  return html`
  <tr class="stock-row" data-ticker="${r.ticker}" ${raw(draggable ? 'draggable="true"' : '')} tabindex="0">
    <td class="col-fav">
      ${draggable ? html`<span class="drag-handle" title="Drag to reorder">⋮⋮</span>` : ''}
      <button class="star ${r.favorite ? 'on' : ''}" data-star="${r.ticker}"
        title="${r.favorite ? 'Remove from favorites' : 'Add to favorites (pins to top)'}">${r.favorite ? '★' : '☆'}</button>
    </td>
    <td class="col-stock">
      <div class="stock-name">${r.name}${r.name_local ? html`<span class="local">${r.name_local}</span>` : ''}</div>
      <div class="stock-sub"><span class="mkt">${r.market}</span>${r.ticker}</div>
      ${r.critical_events.length ? html`<div class="crit-flag">⚠ Critical news</div>` : ''}
    </td>
    <td class="col-ind"><div>${r.group}</div><div class="muted small">${r.segment_label}</div></td>
    <td class="col-price num">
      <div class="big">${fmtPrice(r.price, r.currency)}</div>
      <div class="chg ${dirClass(r.change)}">${arrow(r.change)} ${fmtSigned(r.change)} (${fmtPct(r.change_pct, 2)})</div>
    </td>
    <td class="col-pred num">
      <div class="big pred-${r.outlook}">${fmtPrice(r.predicted_price, r.currency)}</div>
      <div class="pred-chg pred-${r.outlook}" title="${OUTLOOK_LABEL[r.outlook]}">${predArrow} ${fmtPct(r.expected_return)}</div>
    </td>
    <td class="col-pillars">${pillarChips(r.pillars)}</td>
    <td class="col-news num" title="${r.last_news_at ? `Latest: ${timeAgo(r.last_news_at)}` : 'No analyzed news'}">${r.news_count_7d}</td>
  </tr>`;
}

function segmented(name, options) {
  return html`<div class="segmented" role="group">${options.map(([value, label]) =>
    html`<button data-seg="${name}" data-value="${value}" class="${ui[name] === value ? 'on' : ''}">${label}</button>`)}</div>`;
}

function select(name, options, title) {
  return html`<select class="control" data-select="${name}" title="${title}">${options.map(([value, label]) =>
    html`<option value="${value}" ${raw(ui[name] === value ? 'selected' : '')}>${label}</option>`)}</select>`;
}

function draw(root) {
  const visible = data.stocks.filter(matches);
  const favorites = sorted(visible.filter((r) => r.favorite), true);
  const others = sorted(visible.filter((r) => !r.favorite), false);
  const canDrag = ui.sort === 'default';

  root.innerHTML = html`
  <section class="page-head">
    <div>
      <h1>Dashboard</h1>
      <p class="muted">${data.stocks.length} stocks · Taiwan AI hardware &amp; US niche AI software · predicted price ≈ ${raw('3-month')} fair-value estimate</p>
    </div>
    <div class="filters">
      ${segmented('market', [['ALL', 'All'], ...data.markets.map((m) => [m, m === 'TW' ? 'Taiwan' : 'US'])])}
      ${select('group', [['', 'All industries'], ...data.groups.map((g) => [g, g])], 'Industry')}
      ${select('price', [['', 'Any price move'], ['rising', 'Rising today'], ['falling', 'Falling today'],
        ['pred-up', 'Predicted upside'], ['pred-down', 'Predicted downside'], ['pred-neutral', 'Predicted neutral']], 'Price')}
      ${select('sort', [['default', 'Sort: my order'], ['expected', 'Sort: predicted upside'],
        ['expected-asc', 'Sort: predicted downside'], ['change', "Sort: today's gainers"],
        ['change-asc', "Sort: today's losers"], ['name', 'Sort: name']], 'Sort')}
    </div>
  </section>

  ${data.alerts.length ? html`
  <div class="alert">
    <strong>⚠ ${data.alerts.length} critical event${data.alerts.length > 1 ? 's' : ''} in the last 14 days</strong>
    <ul>${data.alerts.slice(0, 5).map((a) => html`
      <li><a href="${stockHref(a.ticker)}">${a.name}</a>: ${a.title} <span class="down">(${fmtSigned(a.impact_pct, 1)}%)</span></li>`)}</ul>
  </div>` : ''}

  <div class="card table-card">
    <table class="stocks">
      <thead><tr>
        <th class="col-fav"></th>
        <th class="col-stock">Stock</th>
        <th class="col-ind">Industry</th>
        <th class="col-price num">Current price</th>
        <th class="col-pred num">Predicted price</th>
        <th class="col-pillars">Pillars</th>
        <th class="col-news num" title="Analyzed news items in the last 7 days">News 7d</th>
      </tr></thead>
      ${favorites.length ? html`
      <tbody><tr class="group-label"><td colspan="7">★ Favorites${canDrag ? ' · drag to reorder' : ''}</td></tr></tbody>
      <tbody class="fav-body">${favorites.map((r) => rowTpl(r, canDrag))}</tbody>` : ''}
      ${others.length ? html`
      <tbody>${favorites.length ? html`<tr class="group-label"><td colspan="7">All stocks</td></tr>` : ''}
        ${others.map((r) => rowTpl(r, false))}</tbody>` : ''}
    </table>
    ${visible.length ? '' : html`<div class="empty">No stocks match these filters.</div>`}
  </div>
  <p class="muted small">Current price: ${raw('<span class="up">▲ up</span> / <span class="down">▼ down</span>')} today.
    Predicted price: ${raw('<span class="pred-up">▲ upside</span> / <span class="pred-down">▼ downside</span> / <span class="pred-neutral">≈ neutral</span>')}.
    Pillars: Leadership · Product · Price (0–10).</p>`;

  bind(root);
}

// ── interactions ────────────────────────────────────────────────────────────
function bind(root) {
  root.querySelectorAll('[data-seg]').forEach((btn) => btn.addEventListener('click', () => {
    ui[btn.dataset.seg] = btn.dataset.value;
    saveLocal(UI_KEY, ui);
    draw(root);
  }));
  root.querySelectorAll('[data-select]').forEach((sel) => sel.addEventListener('change', () => {
    ui[sel.dataset.select] = sel.value;
    saveLocal(UI_KEY, ui);
    draw(root);
  }));

  root.querySelectorAll('.stock-row').forEach((tr) => {
    const open = () => { location.hash = stockHref(tr.dataset.ticker); };
    tr.addEventListener('click', (e) => { if (!e.target.closest('button, .drag-handle')) open(); });
    tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
  });

  root.querySelectorAll('[data-star]').forEach((btn) => btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    const ticker = btn.dataset.star;
    const favs = getPrefs().favorites;
    const next = favs.includes(ticker) ? favs.filter((t) => t !== ticker) : [...favs, ticker];
    applyFavorites(next);
    draw(root);
    await savePrefs({ favorites: next });
  }));

  const favBody = root.querySelector('.fav-body');
  if (favBody && ui.sort === 'default') bindDrag(root, favBody);
}

function applyFavorites(list) {
  for (const s of data.stocks) {
    s.favorite = list.includes(s.ticker);
    s.favorite_rank = s.favorite ? list.indexOf(s.ticker) : null;
  }
  setPrefsLocal({ favorites: list });
}

function bindDrag(root, tbody) {
  let dragged = null;
  tbody.addEventListener('dragstart', (e) => {
    dragged = e.target.closest('tr');
    if (!dragged) return;
    dragging = true;
    dragged.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragged.dataset.ticker);
  });
  tbody.addEventListener('dragover', (e) => {
    e.preventDefault();
    const over = e.target.closest('tr');
    if (!dragged || !over || over === dragged) return;
    const rect = over.getBoundingClientRect();
    const after = e.clientY > rect.top + rect.height / 2;
    tbody.insertBefore(dragged, after ? over.nextSibling : over);
  });
  tbody.addEventListener('dragend', async () => {
    dragging = false;
    if (!dragged) return;
    dragged.classList.remove('dragging');
    dragged = null;
    const order = [...tbody.querySelectorAll('tr')].map((tr) => tr.dataset.ticker);
    const hidden = getPrefs().favorites.filter((t) => !order.includes(t)); // filtered-out favorites keep their place at the end
    const next = [...order, ...hidden];
    applyFavorites(next);
    await savePrefs({ favorites: next });
  });
}
