import { api } from '../api.js';
import { engineLabel, fmtDateTime, html, raw, timeAgo } from '../format.js';
import { emit, getPrefs, savePrefs } from '../state.js';

export async function render(root, _params, { isStale } = {}) {
  const [s, status] = await Promise.all([api.settings(), api.status()]);
  if (isStale?.()) return;
  const a = s.analysis;
  const p = s.settings.prediction;
  const prefs = getPrefs();
  const usage = a.usage;

  root.innerHTML = html`
  <section class="page-head"><div><h1>Method &amp; Settings</h1>
    <p class="muted">How predictions are made, what the colors mean, and how to extend the watchlist.</p></div></section>

  <div class="grid-2">
    <section class="card card-pad">
      <h2>Analysis engine</h2>
      <dl class="kv">
        <dt>Active engine</dt><dd><strong>${a.active_engine === 'claude' ? engineLabel(a.model) : 'Keyword heuristic (low confidence)'}</strong></dd>
        <dt>Mode</dt><dd>${a.mode}</dd>
        <dt>Reasoning effort</dt><dd>${a.effort}</dd>
        <dt>Credentials found</dt><dd>${a.credentials_configured ? 'Yes' : 'No'}</dd>
        ${a.llm_error ? html`<dt>Problem</dt><dd class="down">${a.llm_error}</dd>` : ''}
        ${usage ? html`<dt>Usage this session</dt><dd>${usage.requests} requests · ${usage.input_tokens.toLocaleString()} in / ${usage.output_tokens.toLocaleString()} out tokens</dd>` : ''}
      </dl>
      ${a.active_engine !== 'claude' ? html`
        <p style="margin:12px 0 4px">To enable reasoned analysis with Claude, create <code>config/.env</code> containing:</p>
        <pre>ANTHROPIC_API_KEY=sk-ant-...</pre>
        <p class="muted small" style="margin:0">Then restart the app. Articles scored by the heuristic are re-analyzed by Claude automatically.</p>` : ''}
    </section>

    <section class="card card-pad">
      <h2>Refresh</h2>
      <dl class="kv">
        <dt>Auto refresh</dt><dd>on open and every ${Math.round(status.interval_seconds / 60)} min while open</dd>
        <dt>Last refresh</dt><dd>${status.finished_at ? html`${fmtDateTime(status.finished_at)} (${timeAgo(status.finished_at)}) · ${status.last_status}` : '—'}</dd>
        <dt>Articles waiting</dt><dd>${status.pending_articles}</dd>
        <dt>News lookback</dt><dd>${s.settings.news.lookback_days} days · sources: ${s.settings.news.providers.join(', ')}</dd>
      </dl>
      ${status.warnings?.length ? html`<div class="warn" style="margin-top:10px">${status.warnings.map((w) => html`<div>• ${w}</div>`)}</div>` : ''}
      ${status.last_error ? html`<div class="warn down">${status.last_error}</div>` : ''}
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
        <button class="btn primary" id="refresh">Refresh now</button>
        <button class="btn" id="reload">Reload config files</button>
      </div>
      <p class="muted small" id="reload-msg" style="margin:6px 0 0"></p>
    </section>
  </div>

  <section class="card card-pad" style="margin-top:16px">
    <h2>Colors</h2>
    <div class="legend-row"><strong style="min-width:130px">Current price</strong>
      <span><span class="swatch" style="background:var(--up)"></span>up today</span>
      <span><span class="swatch" style="background:var(--down)"></span>down today</span>
      <span class="segmented" style="margin-left:auto">
        <button data-colors="western" class="${prefs.price_colors === 'western' ? 'on' : ''}">Green = up</button>
        <button data-colors="taiwan" class="${prefs.price_colors === 'taiwan' ? 'on' : ''}">Red = up (Taiwan style)</button>
      </span></div>
    <div class="legend-row"><strong style="min-width:130px">Predicted price</strong>
      <span><span class="swatch" style="background:var(--pred-up)"></span>upside</span>
      <span><span class="swatch" style="background:var(--pred-down)"></span>downside</span>
      <span><span class="swatch" style="background:var(--pred-neutral)"></span>within ±${Math.round(p.neutral_band * 100)}%</span></div>
    <div class="legend-row"><strong style="min-width:130px">News frames</strong>
      <span><span class="swatch" style="background:var(--pos)"></span>raises the predicted price</span>
      <span><span class="swatch" style="background:var(--neg)"></span>lowers it</span>
      <span><span class="swatch" style="background:var(--neu)"></span>≈ no change (under 0.5%)</span></div>
  </section>

  <section class="card card-pad" style="margin-top:16px">
    <h2>How a predicted price is built</h2>
    <ol style="margin:6px 0 0;padding-left:20px;display:grid;gap:6px">
      <li><strong>Collect real news.</strong> Every refresh pulls company news (Google News in English and Traditional Chinese, plus Yahoo Finance) and industry news (AI server demand, hyperscaler capex, CoWoS capacity, export controls and more).</li>
      <li><strong>Analyze each article.</strong> ${a.active_engine === 'claude' ? 'Claude' : 'The engine'} estimates the remaining effect on fair value over ~${p.horizon_days} days: impact %, confidence, share already priced in, duration and severity. It traces the effect through the demand–supply chain, judges whether company decisions go with or against the market, and flags duplicates. Bad news gets its full weight; survival-threatening events are marked critical.</li>
      <li><strong>Combine.</strong> Each item contributes <code>impact × confidence × (1 − priced in) × fade</code>. The fade halves every ${p.half_life_days.transient} / ${p.half_life_days.medium} / ${p.half_life_days.structural} days for short-lived / medium / long-term news.
        Positive contributions level off near +${Math.round(p.positive_cap * 100)}%. Negative ones can reach −${Math.round(p.negative_cap * 100)}%, so devastating news isn't capped away.</li>
      <li><strong>Valuation anchor.</strong> ${p.valuation_weight > 0
        ? raw(`Adds ${Math.round(p.valuation_weight * 100)}% of the gap to the analyst mean target (capped at ±${Math.round(p.valuation_cap * 100)}%, needs ≥3 analysts). Set <code>valuation_weight: 0</code> in <code>config/settings.yaml</code> for purely news-driven predictions.`)
        : 'Disabled: predictions are purely news-driven.'}</li>
      <li><strong>Predicted price</strong> = current price × (1 + expected move). The prediction log records a new entry only when the news set or analyst consensus changes.</li>
    </ol>
    <p class="muted small" style="margin:10px 0 0">Pillars: Leadership and Product start from a baseline in <code>watchlist.yaml</code> and move with relevant news. Price is computed from upside to analyst target, forward P/E versus growth, and position in the 52-week range.</p>
  </section>

  <section class="card card-pad" style="margin-top:16px">
    <h2>Adding stocks</h2>
    <p style="margin:6px 0">Watchlist: ${s.stock_count.TW} Taiwan + ${s.stock_count.US} US. To add one:</p>
    <ol style="margin:0;padding-left:20px">
      <li>Add an entry to <code>config/watchlist.yaml</code> (ticker, market, segment, thesis, pillar baselines, keywords, news queries).</li>
      <li>Add its supplier/customer links in <code>config/industry.yaml</code> (and a new segment if needed).</li>
      <li>Click <em>Reload config files</em> above, or restart the app.</li>
    </ol>
  </section>`;

  root.querySelector('#refresh').onclick = () => emit('request-refresh');
  root.querySelector('#reload').onclick = async () => {
    const msg = root.querySelector('#reload-msg');
    try {
      const r = await api.reloadConfig();
      msg.textContent = `Reloaded: ${r.stocks} stocks. Refreshing…`;
      emit('request-refresh');
    } catch (err) {
      msg.textContent = `Config error: ${err.message}`;
    }
  };
  root.querySelectorAll('[data-colors]').forEach((b) => b.addEventListener('click', async () => {
    await savePrefs({ price_colors: b.dataset.colors });
    render(root, _params, {});
  }));
}
