import { api } from '../api.js';
import { renderPriceChart } from '../components/chart.js';
import { stockNewsCard } from '../components/newsCard.js';
import {
  arrow, dirClass, engineLabel, fmtCompact, fmtDateTime, fmtNumber, fmtPct, fmtPP, fmtPrice, fmtSigned,
  html, OUTLOOK_LABEL, raw, stockHref, timeAgo,
} from '../format.js';
import { getPrefs, loadLocal, savePrefs, saveLocal } from '../state.js';

const UI_KEY = 'stock-ui';
const ui = loadLocal(UI_KEY, { range: '3M', news: 'all' });
let resizeObserver = null;
let detail = null;

export function unmount() {
  resizeObserver?.disconnect();
  resizeObserver = null;
}

export async function render(root, { ticker }, { silent, isStale } = {}) {
  const fresh = await api.stock(ticker);
  if (isStale?.()) return;
  detail = fresh;
  const scrollY = window.scrollY;
  root.innerHTML = page(detail);
  bind(root);
  await drawChart(root, isStale);
  if (silent) window.scrollTo(0, scrollY);
}

// ── sections ────────────────────────────────────────────────────────────────
function hero(d) {
  const predArrow = d.outlook === 'up' ? '▲' : d.outlook === 'down' ? '▼' : '≈';
  return html`
  <section class="card card-pad hero">
    <div>
      <div class="title-row">
        <h1>${d.name}</h1>
        ${d.name_local ? html`<span class="muted" style="font-size:18px">${d.name_local}</span>` : ''}
        <button class="star ${d.favorite ? 'on' : ''}" id="fav-toggle" title="Favorite">${d.favorite ? '★' : '☆'}</button>
      </div>
      <div class="stock-sub" style="margin-top:4px">
        <span class="mkt">${d.market}</span>${d.ticker} · ${d.group} · ${d.segment_label}
      </div>
    </div>
    <div>
      <div class="label">Current price</div>
      <div class="price-xl">${fmtPrice(d.price, d.currency)}</div>
      <div class="sub ${dirClass(d.change)}">${arrow(d.change)} ${fmtSigned(d.change)} (${fmtPct(d.change_pct, 2)}) today</div>
      <div class="muted small">${d.market_time ? `as of ${fmtDateTime(d.market_time)}` : 'price unavailable'}</div>
    </div>
    <div>
      <div class="label">Predicted price · ~${d.horizon_days} days</div>
      <div class="price-xl pred-${d.outlook}">${fmtPrice(d.predicted_price, d.currency)}</div>
      <div class="sub pred-${d.outlook}">${predArrow} ${fmtPct(d.expected_return)} expected
        <span class="outlook-pill">${OUTLOOK_LABEL[d.outlook]}</span></div>
      <div class="muted small">${d.prediction_history.length
        ? `last news-driven update ${timeAgo(d.prediction_history.at(-1).t)}` : 'no news-driven update yet'}</div>
    </div>
  </section>`;
}

function chartCard() {
  return html`
  <section class="card chart-card">
    <div class="chart-head">
      <div class="segmented">${['1W', '1M', '3M', '6M', '1Y', '5Y'].map((r) =>
        html`<button data-range="${r}" class="${ui.range === r ? 'on' : ''}">${r}</button>`)}</div>
      <div class="chart-legend">
        <span><i style="border-color:var(--flat)"></i>Price</span>
        <span><i style="border-top-style:dotted;border-color:var(--pred-neutral)"></i>Past predictions</span>
        <span><i style="border-top-style:dashed;border-color:var(--pred-up)"></i>Projection to predicted price</span>
      </div>
    </div>
    <div class="chart" id="chart"><div class="chart-empty">Loading chart…</div></div>
  </section>`;
}

function why(d) {
  const val = d.valuation_anchor;
  const outlook = d.outlook_summary;
  return html`
  <section class="card card-pad">
    <h2>Why this prediction</h2>
    <table class="breakdown">
      <tr><td>News impact<div class="muted small">${d.news.length} analyzed item${d.news.length === 1 ? '' : 's'} in the lookback window, faded by age</div></td>
        <td class="num pred-${d.news_return > 0 ? 'up' : d.news_return < 0 ? 'down' : 'neutral'}">${fmtPct(d.news_return)}</td></tr>
      <tr><td>Valuation anchor<div class="muted small">${val
        ? `${Math.round(val.weight * 100)}% of the ${fmtPct(val.gap)} gap to the analyst mean target ${fmtPrice(val.target, d.currency)} (${val.analysts} analysts)`
        : 'Not used (not enough analyst coverage)'}</div></td>
        <td class="num">${fmtPct(d.valuation_return)}</td></tr>
      <tr class="total"><td>Expected move → ${fmtPrice(d.predicted_price, d.currency)}</td>
        <td class="num pred-${d.outlook}">${fmtPct(d.expected_return)}</td></tr>
    </table>
    ${d.drivers.length ? html`
      <div class="muted small" style="margin-top:12px">Biggest drivers right now</div>
      <ul class="drivers">${d.drivers.map((x) => html`
        <li><span class="amt impact ${x.direction}">${fmtPP(x.contribution_pct, 2)}</span>
          <a href="#news-${x.article_id}" data-jump="${x.article_id}">${x.title}</a></li>`)}</ul>` : html`
      <p class="muted">No analyzed news is moving this estimate yet.</p>`}
    ${outlook ? html`
      <div class="outlook-text">${outlook.summary}
        <div class="muted small" style="margin-top:4px">Outlook by ${engineLabel(outlook.engine)} · ${timeAgo(outlook.updated_at)}</div>
      </div>` : ''}
  </section>`;
}

function pillars(d) {
  const p = d.pillars_detail;
  const row = (name, label, score, basis, extra) => html`
    <div class="pillar"><strong>${label}</strong>
      <div class="pillar-bar"><span style="width:${score == null ? 0 : score * 10}%"></span></div>
      <span class="num">${score == null ? '–' : score.toFixed(1)}</span></div>
    <p class="pillar-basis">${basis}${extra ? html` <br>${extra}` : ''}</p>`;
  const adj = (x) => (x.news_events ? `Baseline ${x.baseline} ${x.news_adjustment >= 0 ? '+' : '−'} ${Math.abs(x.news_adjustment).toFixed(2)} from ${x.news_events} news item(s).` : `Baseline ${x.baseline}; no news adjustments yet.`);
  return html`
  <section class="card card-pad">
    <h2>Three pillars</h2>
    ${row('leadership', 'Leadership', p.leadership.score, p.leadership.basis, adj(p.leadership))}
    ${row('product', 'Product', p.product.score, p.product.basis, adj(p.product))}
    ${row('price', 'Price', p.price.score, p.price.basis, 'Computed from live valuation data.')}
  </section>`;
}

function facts(d) {
  const f = d.fundamentals;
  const c = d.currency;
  const items = [
    ['Previous close', fmtPrice(d.prev_close, c)],
    ['52-week range', f.fiftyTwoWeekLow ? `${fmtPrice(f.fiftyTwoWeekLow, c)} – ${fmtPrice(f.fiftyTwoWeekHigh, c)}` : '—'],
    ['Market cap', fmtCompact(f.marketCap, c)],
    ['Forward P/E', f.forwardPE ? fmtNumber(f.forwardPE, 1) : '—'],
    ['Trailing P/E', f.trailingPE ? fmtNumber(f.trailingPE, 1) : '—'],
    ['Price / sales', f.priceToSalesTrailing12Months ? fmtNumber(f.priceToSalesTrailing12Months, 1) : '—'],
    ['Revenue growth', fmtPct(f.revenueGrowth)],
    ['Gross margin', f.grossMargins != null ? `${fmtNumber(f.grossMargins * 100, 1)}%` : '—'],
    ['Analyst target', f.targetMeanPrice ? `${fmtPrice(f.targetMeanPrice, c)} (${f.numberOfAnalystOpinions ?? 0})` : '—'],
    ['Consensus', f.recommendationKey ? f.recommendationKey.replace('_', ' ') : '—'],
  ];
  return html`
  <section class="card card-pad">
    <h2>Key numbers</h2>
    <dl class="facts">${items.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
    <p class="muted small" style="margin:10px 0 0">Valuation data ${d.fundamentals_updated_at ? `updated ${timeAgo(d.fundamentals_updated_at)}` : 'not loaded yet'} · Yahoo Finance</p>
  </section>`;
}

function chain(d) {
  const node = (n) => (n.kind === 'stock'
    ? html`<a class="chip" href="${stockHref(n.id)}">${n.label}</a>`
    : html`<span class="chip external" title="${n.detail}">${n.label}</span>`);
  const list = (items, empty) => (items.length
    ? html`<ul class="chain-list">${items.map((n) => html`<li>${node(n)} <span class="muted">${n.what}</span></li>`)}</ul>`
    : html`<p class="muted">${empty}</p>`);
  return html`
  <section class="card card-pad">
    <h2>Demand &amp; supply</h2>
    <dl class="thesis" style="margin:0 0 12px">
      <dt>Niche</dt><dd>${d.thesis.niche}</dd>
      <dt>Demand</dt><dd>${d.thesis.demand}</dd>
      <dt>Supply</dt><dd>${d.thesis.supply}</dd>
    </dl>
    <div class="grid-2">
      <div><div class="muted small" style="margin-bottom:6px">Buys from (upstream)</div>${list(d.supply_chain.upstream, 'No mapped suppliers')}</div>
      <div><div class="muted small" style="margin-bottom:6px">Sells to (downstream)</div>${list(d.supply_chain.downstream, 'No mapped customers')}</div>
    </div>
  </section>`;
}

function newsSection(d) {
  const counts = { all: d.news.length, positive: 0, negative: 0, neutral: 0 };
  d.news.forEach((n) => { counts[n.direction] += 1; });
  const shown = ui.news === 'all' ? d.news : d.news.filter((n) => n.direction === ui.news);
  return html`
  <div class="section-head">
    <h2>News &amp; impact on the predicted price</h2>
    <div class="segmented">${[['all', 'All'], ['positive', '+ Raises'], ['negative', '− Lowers'], ['neutral', '≈ No change']].map(([k, label]) =>
      html`<button data-news="${k}" class="${ui.news === k ? 'on' : ''}">${label} (${counts[k]})</button>`)}</div>
  </div>
  <div class="news-list">
    ${shown.length ? shown.map(stockNewsCard) : html`<div class="card empty">No analyzed news here yet. New articles are collected and analyzed on every refresh.</div>`}
  </div>`;
}

function predictionLog(d) {
  if (!d.prediction_history.length) return '';
  const rows = [...d.prediction_history].reverse().slice(0, 15);
  return html`
  <div class="section-head"><h2>Prediction update log</h2>
    <span class="muted small">A new entry is added only when news or analyst consensus changes, never just because the price moved.</span></div>
  <div class="card card-pad" style="overflow-x:auto">
    <table class="log">
      <thead><tr><th>When</th><th>Price then</th><th>Predicted</th><th>Expected move</th><th>Why</th></tr></thead>
      <tbody>${rows.map((h) => html`<tr>
        <td>${fmtDateTime(h.t)}</td>
        <td>${fmtPrice(h.base_price, d.currency)}</td>
        <td>${fmtPrice(h.predicted_price, d.currency)}</td>
        <td class="pred-${h.expected_return > 0.01 ? 'up' : h.expected_return < -0.01 ? 'down' : 'neutral'}">${fmtPct(h.expected_return)}</td>
        <td>${h.note}</td></tr>`)}</tbody>
    </table>
  </div>`;
}

function page(d) {
  return html`
  <a class="back" href="#/">← Dashboard</a>
  ${d.critical_events.length ? html`<div class="alert"><strong>⚠ Critical news:</strong>
    <ul>${d.critical_events.map((e) => html`<li><a href="#" data-jump-title="${e.title}">${e.title}</a> (${fmtSigned(e.impact_pct, 1)}%)</li>`)}</ul></div>` : ''}
  <div class="stack">
    ${hero(d)}
    ${chartCard()}
    <div class="grid-2">${why(d)}${pillars(d)}</div>
    <div class="grid-2">${chain(d)}${facts(d)}</div>
  </div>
  ${newsSection(d)}
  ${predictionLog(d)}`;
}

// ── behaviour ───────────────────────────────────────────────────────────────
async function drawChart(root, isStale) {
  const el = root.querySelector('#chart');
  if (!el) return;
  try {
    const { points } = await api.history(detail.ticker, ui.range);
    if (isStale?.() || !el.isConnected) return;
    const draw = () => renderPriceChart(el, {
      points, currency: detail.currency, predictedPrice: detail.predicted_price, outlook: detail.outlook,
      history: detail.prediction_history, horizonDays: detail.horizon_days,
    });
    draw();
    resizeObserver?.disconnect();
    let lastWidth = el.clientWidth;
    resizeObserver = new ResizeObserver(() => {
      if (Math.abs(el.clientWidth - lastWidth) > 4) { lastWidth = el.clientWidth; draw(); }
    });
    resizeObserver.observe(el);
  } catch (err) {
    el.innerHTML = html`<div class="chart-empty">Price history unavailable: ${err.message}</div>`.s;
  }
}

function bind(root) {
  root.querySelectorAll('[data-range]').forEach((b) => b.addEventListener('click', () => {
    ui.range = b.dataset.range;
    saveLocal(UI_KEY, ui);
    root.querySelectorAll('[data-range]').forEach((x) => x.classList.toggle('on', x === b));
    drawChart(root);
  }));
  root.querySelectorAll('[data-news]').forEach((b) => b.addEventListener('click', () => {
    ui.news = b.dataset.news;
    saveLocal(UI_KEY, ui);
    const scrollY = window.scrollY;
    root.innerHTML = page(detail);
    bind(root);
    drawChart(root);
    window.scrollTo(0, scrollY);
  }));
  root.querySelectorAll('[data-jump]').forEach((a) => a.addEventListener('click', (e) => {
    e.preventDefault();
    jumpTo(root, a.dataset.jump);
  }));
  root.querySelectorAll('[data-jump-title]').forEach((a) => a.addEventListener('click', (e) => {
    e.preventDefault();
    const item = detail.news.find((n) => n.title === a.dataset.jumpTitle);
    if (item) jumpTo(root, item.article_id);
  }));
  root.querySelector('#fav-toggle')?.addEventListener('click', async (e) => {
    const favs = getPrefs().favorites;
    const on = favs.includes(detail.ticker);
    detail.favorite = !on;
    e.currentTarget.classList.toggle('on', !on);
    e.currentTarget.textContent = on ? '☆' : '★';
    await savePrefs({ favorites: on ? favs.filter((t) => t !== detail.ticker) : [...favs, detail.ticker] });
  });
}

function jumpTo(root, articleId) {
  if (ui.news !== 'all') {
    ui.news = 'all';
    root.innerHTML = page(detail);
    bind(root);
    drawChart(root);
  }
  const card = root.querySelector(`#news-${CSS.escape(articleId)}`);
  if (!card) return;
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  card.style.outline = '2px solid var(--accent)';
  setTimeout(() => { card.style.outline = ''; }, 1600);
}
