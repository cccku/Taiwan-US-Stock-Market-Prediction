import { api } from '../api.js';
import { hubNewsCard } from '../components/newsCard.js';
import { html, raw } from '../format.js';
import { loadLocal, saveLocal } from '../state.js';

const UI_KEY = 'news-ui';
const ui = loadLocal(UI_KEY, { market: '', direction: '', scope: '', days: '7' });

export async function render(root, _params, { silent, isStale } = {}) {
  const data = await api.news(ui);
  if (isStale?.()) return;
  const scrollY = window.scrollY;
  root.innerHTML = html`
  <section class="page-head">
    <div>
      <h1>News Hub</h1>
      <p class="muted">${data.total} analyzed item${data.total === 1 ? '' : 's'}, highest estimated impact first.</p>
    </div>
    <div class="filters">
      ${select('market', [['', 'All markets'], ['TW', 'Taiwan'], ['US', 'US']])}
      ${select('direction', [['', 'Any direction'], ['positive', '+ Positive'], ['negative', '− Negative'], ['neutral', '≈ Neutral']])}
      ${select('scope', [['', 'Company & industry'], ['company', 'Company news'], ['industry', 'Industry news']])}
      ${select('days', [['1', 'Last 24 hours'], ['3', 'Last 3 days'], ['7', 'Last 7 days'], ['30', 'Last 30 days']])}
    </div>
  </section>
  <details class="card card-pad" style="margin-bottom:14px">
    <summary><strong>How the impact score works</strong></summary>
    <p style="margin:8px 0 0">For each company an article affects:
      <code>|impact %| × confidence × (1 − share priced in) × recency fade × severity weight</code>.
      Recency fades by half every 5 days for short-lived news, 21 days for weeks-to-months news, and 90 days for long-term news.
      Severity weight is 1.0 low, 1.2 moderate, 1.5 major and 2.5 critical, so events that threaten a company always rise to the top.
      An article affecting several companies scores its largest impact plus 25% of the rest.
      Frame colors show the net direction: ${raw('<span class="impact positive">green raises</span>, <span class="impact negative">red lowers</span>, <span class="impact neutral">grey ≈ no change</span>')}.</p>
  </details>
  <div class="news-list">
    ${data.items.length ? data.items.map(hubNewsCard) : html`<div class="card empty">No analyzed news for these filters yet.</div>`}
  </div>`;
  root.querySelectorAll('[data-select]').forEach((sel) => sel.addEventListener('change', () => {
    ui[sel.dataset.select] = sel.value;
    saveLocal(UI_KEY, ui);
    render(root, _params, {});
  }));
  if (silent) window.scrollTo(0, scrollY);
}

function select(name, options) {
  return html`<select class="control" data-select="${name}">${options.map(([v, label]) =>
    html`<option value="${v}" ${raw(ui[name] === v ? 'selected' : '')}>${label}</option>`)}</select>`;
}
