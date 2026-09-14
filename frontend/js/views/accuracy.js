import { api } from '../api.js';
import { CATEGORY_LABEL, fmtDate, fmtDateTime, fmtPct, fmtPrice, html, stockHref, timeAgo } from '../format.js';
import { loadLocal, saveLocal } from '../state.js';

const UI_KEY = 'track-ui';
const ui = loadLocal(UI_KEY, { h: null, group: 'market' });

const VERDICT = {
  beating: ['beating', 'Beating the baseline'],
  worse: ['worse', 'Worse than the baseline'],
  unclear: ['unclear', 'Not distinguishable from luck yet'],
  not_enough: ['pending', 'Not enough results yet'],
};
const GROUP_LABEL = { market: 'Market', engine: 'Analysis engine', algo_version: 'Algorithm version' };

const pct0 = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const ci = (x) => (x.ci ? `${pct0(x.ci[0])}–${pct0(x.ci[1])}` : '—');
const tone = (v) => (v == null ? '' : v > 0 ? 'good' : v < 0 ? 'bad' : '');
const verdictPill = (v) => { const [cls, label] = VERDICT[v] || VERDICT.not_enough; return html`<span class="verdict ${cls}">${label}</span>`; };

function horizonCard(x) {
  if (!x.n) {
    return html`
    <section class="card card-pad metric-card">
      <div class="label">${x.label} · ${x.h} trading days</div>
      <div class="metric-big muted">—</div>
      <p class="muted" style="margin:6px 0 0">${x.first_result_eta
        ? `First results around ${fmtDate(x.first_result_eta)}.` : 'Waiting for the first recorded prediction.'}</p>
      <p class="muted small" style="margin:4px 0 0">${x.pending} recorded prediction${x.pending === 1 ? '' : 's'} waiting to mature.</p>
    </section>`;
  }
  return html`
  <section class="card card-pad metric-card">
    <div class="label">${x.label} · ${x.h} trading days</div>
    <div class="metric-big">${pct0(x.hit_rate)}</div>
    <div class="small muted">direction right vs market · baseline ${pct0(x.baseline)} · 95% range ${ci(x)}</div>
    <div style="margin-top:8px">${verdictPill(x.verdict)}</div>
    <dl class="kv compact">
      <dt title="Average return vs market of stocks predicted up, minus stocks predicted down">Up picks minus down picks</dt>
      <dd class="${tone(x.spread)}">${fmtPct(x.spread, 2)}</dd>
      <dt title="Daily rank correlation between predicted and realized moves (0 = no skill, ~0.05+ is useful)">Rank correlation (IC)</dt>
      <dd>${x.ic == null ? '—' : x.ic.toFixed(2)} <span class="muted small">${x.ic_days}d</span></dd>
      <dt title="Mean absolute error of the predicted move vs assuming no change">Error vs "no change"</dt>
      <dd class="${tone(x.error_skill)}">${x.error_skill == null ? '—' : `${x.error_skill >= 0 ? '' : '−'}${pct0(Math.abs(x.error_skill))} ${x.error_skill >= 0 ? 'better' : 'worse'}`}</dd>
      <dt>Direction right (raw, no market adj.)</dt><dd>${pct0(x.hit_rate_raw)}</dd>
      <dt>Scored · directional · waiting</dt><dd>${x.n} · ${x.directional} · ${x.pending}</dd>
    </dl>
  </section>`;
}

function calibrationTable(rows) {
  return html`
  <div class="table-scroll"><table class="log">
    <thead><tr><th>Predicted move</th><th class="num">Predictions</th><th class="num">Avg predicted*</th>
      <th class="num">Avg realized</th><th class="num">Avg vs market</th></tr></thead>
    <tbody>${rows.map((b) => html`<tr>
      <td>${b.label}</td><td class="num">${b.n}</td><td class="num">${fmtPct(b.avg_expected, 2)}</td>
      <td class="num">${fmtPct(b.avg_realized, 2)}</td><td class="num ${tone(b.avg_excess)}">${fmtPct(b.avg_excess, 2)}</td></tr>`)}</tbody>
  </table></div>
  <p class="muted small" style="margin:6px 0 0">A well-calibrated model shows "avg vs market" rising from the top row to the bottom row.
    *Scaled to this horizon.</p>`;
}

function groupTable(rows) {
  if (!rows.length) return html`<p class="muted">No scored predictions yet.</p>`;
  return html`
  <div class="table-scroll"><table class="log">
    <thead><tr><th>${GROUP_LABEL[ui.group]}</th><th class="num">Scored</th><th class="num">Directional</th>
      <th class="num">Hit rate</th><th class="num">Baseline</th><th class="num">Up − down</th><th>Verdict</th></tr></thead>
    <tbody>${rows.map((g) => html`<tr>
      <td>${g.key}</td><td class="num">${g.n}</td><td class="num">${g.directional}</td>
      <td class="num">${pct0(g.hit_rate)}</td><td class="num">${pct0(g.baseline)}</td>
      <td class="num ${tone(g.spread)}">${fmtPct(g.spread, 2)}</td><td>${verdictPill(g.verdict)}</td></tr>`)}</tbody>
  </table></div>`;
}

function stockTable(rows) {
  if (!rows.length) return html`<p class="muted">No scored predictions yet.</p>`;
  return html`
  <div class="table-scroll"><table class="log">
    <thead><tr><th>Stock</th><th class="num">Scored</th><th class="num">Hit rate</th>
      <th class="num">Vs market when predicted up</th><th class="num">When predicted down</th></tr></thead>
    <tbody>${rows.map((s) => html`<tr>
      <td><a href="${stockHref(s.ticker)}">${s.name}</a></td><td class="num">${s.n}</td><td class="num">${pct0(s.hit_rate)}</td>
      <td class="num ${tone(s.avg_excess_up)}">${fmtPct(s.avg_excess_up, 2)}</td>
      <td class="num ${tone(s.avg_excess_down)}">${fmtPct(s.avg_excess_down, 2)}</td></tr>`)}</tbody>
  </table></div>`;
}

function recentTable(rows) {
  if (!rows.length) return html`<p class="muted">Nothing scored at this horizon yet.</p>`;
  return html`
  <div class="table-scroll"><table class="log">
    <thead><tr><th>Predicted on</th><th>Stock</th><th class="num">Price then</th><th class="num">Predicted</th>
      <th class="num">Realized</th><th class="num">Market</th><th class="num">Vs market</th><th>Result</th></tr></thead>
    <tbody>${rows.map((r) => html`<tr>
      <td>${r.day}</td><td><a href="${stockHref(r.ticker)}">${r.name}</a></td>
      <td class="num">${fmtPrice(r.price)}</td><td class="num">${fmtPct(r.expected_return)}</td>
      <td class="num">${fmtPct(r.realized_return)}</td><td class="num">${fmtPct(r.benchmark_return)}</td>
      <td class="num ${tone(r.excess)}">${fmtPct(r.excess)}</td>
      <td>${r.hit == null ? html`<span class="muted">neutral</span>` : r.hit ? html`<span class="good">✓ right</span>` : html`<span class="bad">✗ wrong</span>`}</td></tr>`)}</tbody>
  </table></div>`;
}

function newsSection(news) {
  if (!news.total) {
    return html`<p class="muted">No news items scored yet. Items claiming at least a 1% effect are checked 1 and 5 trading days after publication.</p>`;
  }
  return html`
  <div class="table-scroll"><table class="log">
    <thead><tr><th>Engine</th><th>After</th><th class="num">Items</th><th class="num">Direction right</th>
      <th class="num">95% range</th><th class="num">Baseline</th><th class="num">Vs market: raised</th><th class="num">Vs market: lowered</th><th>Verdict</th></tr></thead>
    <tbody>${news.by_engine.map((e) => html`<tr>
      <td>${e.engine}</td><td>${e.label}</td><td class="num">${e.directional}</td><td class="num">${pct0(e.hit_rate)}</td>
      <td class="num">${ci(e)}</td><td class="num">${pct0(e.baseline)}</td>
      <td class="num ${tone(e.avg_excess_up)}">${fmtPct(e.avg_excess_up, 2)}</td>
      <td class="num ${tone(e.avg_excess_down)}">${fmtPct(e.avg_excess_down, 2)}</td><td>${verdictPill(e.verdict)}</td></tr>`)}</tbody>
  </table></div>
  ${news.by_category.length ? html`
  <div class="muted small" style="margin:14px 0 6px">By category, ${news.category_horizon} trading days after publication</div>
  <div class="table-scroll"><table class="log">
    <thead><tr><th>Category</th><th class="num">Items</th><th class="num">Direction right</th><th class="num">Up − down</th></tr></thead>
    <tbody>${news.by_category.map((c) => html`<tr>
      <td>${CATEGORY_LABEL[c.category] || c.category}</td><td class="num">${c.directional}</td>
      <td class="num">${pct0(c.hit_rate)}</td><td class="num ${tone(c.spread)}">${fmtPct(c.spread, 2)}</td></tr>`)}</tbody>
  </table></div>` : ''}`;
}

export async function render(root, params, { silent, isStale } = {}) {
  const r = await api.accuracy();
  if (isStale?.()) return;
  const scrollY = window.scrollY;
  const hs = r.horizons;
  if (!hs.some((x) => x.h === ui.h)) ui.h = (hs.find((x) => x.n > 0) || hs[0]).h;
  const t = r.tracking;
  const bench = Object.entries(r.settings.benchmarks).map(([m, s]) => `${m}: ${s}`).join(', ');

  root.innerHTML = html`
  <section class="page-head">
    <div>
      <h1>Track Record</h1>
      <p class="muted">Every refresh records each stock's prediction: one snapshot per market day, frozen once the day ends.
        As trading days pass, the real dividend-adjusted return is compared with the prediction <em>relative to the market</em> (${bench}),
        starting from the first close after the prediction was made.</p>
    </div>
    <a class="btn" href="/api/accuracy/export.csv">Export CSV</a>
  </section>

  <section class="card card-pad" style="margin-bottom:16px">
    <dl class="kv">
      <dt>Tracking since</dt><dd>${t.since || 'not started'}${t.since ? ` · ${t.snapshots} predictions recorded across ${t.stocks} stocks` : ''}</dd>
      <dt>Last recorded</dt><dd>${t.last_snapshot_at ? `${fmtDateTime(t.last_snapshot_at)} (${timeAgo(t.last_snapshot_at)})` : '—'}</dd>
      <dt>Last scored</dt><dd>${t.last_evaluated_at ? `${fmtDateTime(t.last_evaluated_at)} (${timeAgo(t.last_evaluated_at)})` : 'not yet'}</dd>
      <dt>Algorithm version</dt><dd><code>${t.current_version}</code>${t.versions.length > 1 ? html` <span class="muted small">(${t.versions.length} versions recorded, compare them below)</span>` : ''}</dd>
    </dl>
  </section>

  <div class="grid-3">${hs.map(horizonCard)}</div>

  <div class="section-head">
    <h2>Details</h2>
    <div class="segmented">${hs.map((x) => html`<button data-h="${x.h}" class="${ui.h === x.h ? 'on' : ''}">${x.label}</button>`)}</div>
  </div>
  <div class="grid-2">
    <section class="card card-pad"><h2>Calibration</h2>${calibrationTable(r.calibration[ui.h] || [])}</section>
    <section class="card card-pad">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
        <h2 style="margin:0">Breakdown</h2>
        <div class="segmented">${Object.entries(GROUP_LABEL).map(([k, label]) =>
          html`<button data-group="${k}" class="${ui.group === k ? 'on' : ''}">${label}</button>`)}</div>
      </div>
      ${groupTable((r.groups[ui.h] || {})[ui.group] || [])}
    </section>
  </div>
  <section class="card card-pad" style="margin-top:16px"><h2>By stock</h2>${stockTable(r.stocks[ui.h] || [])}</section>
  <section class="card card-pad" style="margin-top:16px"><h2>Recently scored</h2>${recentTable(r.recent[ui.h] || [])}</section>

  <div class="section-head"><h2>News analysis accuracy</h2>
    <span class="muted small">Did each news item's estimated direction match the stock's move vs market?</span></div>
  <section class="card card-pad">${newsSection(r.news)}</section>

  <details class="card card-pad" style="margin-top:16px">
    <summary><strong>How to read this honestly</strong></summary>
    <ul style="margin:8px 0 0;padding-left:20px;display:grid;gap:4px">
      <li><strong>Baseline</strong> is always guessing whichever direction was more common, so a rising market can't make the model look good.</li>
      <li><strong>Neutral predictions</strong> (within ±${Math.round(r.settings.neutral_band * 100)}%) are excluded from hit rates but included in rank correlation and error.</li>
      <li><strong>Daily snapshots overlap:</strong> a prediction on Monday and one on Tuesday share most of the same 1-month window. The 95% ranges account for this, and stocks moving together (e.g. all Taiwan AI suppliers) make true certainty lower still.</li>
      <li><strong>Realistic expectations:</strong> in stock prediction, a 53–56% hit rate or a rank correlation of 0.05–0.10 that holds for months is already meaningful. Treat anything much higher over a short period with suspicion.</li>
      <li><strong>When you change settings or prompts,</strong> a new algorithm version starts. Compare versions in the breakdown instead of mixing them.</li>
    </ul>
  </details>`;

  root.querySelectorAll('[data-h]').forEach((b) => b.addEventListener('click', () => {
    ui.h = Number(b.dataset.h); saveLocal(UI_KEY, ui); render(root, params, { silent: true });
  }));
  root.querySelectorAll('[data-group]').forEach((b) => b.addEventListener('click', () => {
    ui.group = b.dataset.group; saveLocal(UI_KEY, ui); render(root, params, { silent: true });
  }));
  if (silent) window.scrollTo(0, scrollY);
}
