import {
  CATEGORY_LABEL, DURATION_LABEL, PILLAR_LABEL, engineLabel, fmtPP, html, safeUrl, stockHref, timeAgo,
} from '../format.js';

const SYMBOL = { positive: '+', negative: '−', neutral: '≈' };

function severityTag(severity) {
  if (severity === 'critical') return html`<span class="tag critical">Critical</span>`;
  if (severity === 'major') return html`<span class="tag major">Major</span>`;
  return '';
}

function alignment(item) {
  if (!item.company_decision || item.market_alignment === 'not_applicable' || !item.alignment_note) return '';
  const label = item.market_alignment === 'against_market' ? 'Goes against the market' : 'Moves with the market';
  return html`<p class="news-alignment"><strong>${label}:</strong> ${item.alignment_note}</p>`;
}

/** A single analysis for one stock (stock detail page). */
export function stockNewsCard(item) {
  return html`
  <article class="news-card ${item.direction}" id="news-${item.article_id}">
    <div class="news-top">
      <span class="impact ${item.direction}" title="Estimated remaining effect on fair value">${SYMBOL[item.direction]} ${fmtPP(item.impact_pct)}</span>
      <span>${item.source || 'Unknown source'}</span>
      <span>·</span>
      <span title="${new Date(item.published_at * 1000).toLocaleString()}">${timeAgo(item.published_at)}</span>
      ${item.scope === 'industry' ? html`<span class="tag">Industry</span>` : ''}
      ${severityTag(item.severity)}
    </div>
    <a class="news-title" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${item.title}</a>
    ${item.reasoning ? html`<p class="news-reason">${item.reasoning}</p>` : ''}
    ${alignment(item)}
    <div class="news-foot">
      <span>Confidence ${Math.round(item.confidence * 100)}%</span>
      <span>${DURATION_LABEL[item.duration] || item.duration}</span>
      <span>${Math.round(item.priced_in * 100)}% priced in</span>
      <span>${CATEGORY_LABEL[item.category] || item.category}</span>
      ${item.pillar_delta ? html`<span>${PILLAR_LABEL[item.pillar]} ${item.pillar_delta > 0 ? '+' : ''}${item.pillar_delta}</span>` : ''}
      <span title="What this item currently adds to the expected move">Now contributes ${fmtPP(item.contribution_pct, 2)}</span>
      <span>by ${engineLabel(item.engine)}</span>
    </div>
  </article>`;
}

/** An article with impacts across one or more stocks (News Hub). */
export function hubNewsCard(item) {
  const top = item.impacts[0];
  return html`
  <article class="news-card ${item.direction}">
    <div class="news-top">
      <span class="impact ${item.direction}" title="Impact score used for ranking">Score ${item.impact_score.toFixed(2)}</span>
      <span>${item.source || 'Unknown source'}</span>
      <span>·</span>
      <span title="${new Date(item.published_at * 1000).toLocaleString()}">${timeAgo(item.published_at)}</span>
      <span class="tag">${item.scope === 'industry' ? 'Industry' : 'Company'}</span>
      ${severityTag(item.severity)}
    </div>
    <a class="news-title" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${item.title}</a>
    ${top?.reasoning ? html`<p class="news-reason">${top.reasoning}</p>` : ''}
    ${top ? alignment(top) : ''}
    <div class="impact-chips">
      ${item.impacts.map((i) => html`
        <a href="${stockHref(i.ticker)}" title="${i.reasoning || ''}">${i.name}
          <span class="${i.direction}">${fmtPP(i.impact_pct)}</span></a>`)}
    </div>
    ${top ? html`<div class="news-foot">
      <span>Confidence ${Math.round(top.confidence * 100)}%</span>
      <span>${DURATION_LABEL[top.duration] || top.duration}</span>
      <span>${CATEGORY_LABEL[top.category] || top.category}</span>
      <span>by ${engineLabel(top.engine)}</span>
    </div>` : ''}
  </article>`;
}
