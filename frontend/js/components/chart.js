import { fmtPrice } from '../format.js';

function niceTicks(lo, hi, count) {
  const rough = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(v);
  return ticks;
}

function dateLabel(ts, spanDays) {
  const d = new Date(ts * 1000);
  if (spanDays <= 8) return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });
  if (spanDays <= 400) return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
}

/**
 * Price line (solid) + how the prediction evolved (dotted steps) + projection to the
 * current predicted price (dashed, in the shaded area on the right).
 */
export function renderPriceChart(container, { points, currency, predictedPrice, outlook = 'neutral', history = [], horizonDays = 90 }) {
  if (!points?.length) {
    container.innerHTML = '<div class="chart-empty">No price history available right now.</div>';
    return;
  }
  const width = Math.max(320, container.clientWidth || 800);
  const height = width < 600 ? 230 : 300;
  const pad = { l: 8, r: 78, t: 16, b: 26 };
  const plotW = width - pad.l - pad.r;
  const plotH = height - pad.t - pad.b;
  const projW = predictedPrice ? Math.round(plotW * 0.14) : 0;
  const histW = plotW - projW;

  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  // Clamp to the price range so a prediction logged after the last bar doesn't spill into the projection zone.
  const x = (t) => pad.l + (t1 === t0 ? histW : ((Math.min(Math.max(t, t0), t1) - t0) / (t1 - t0)) * histW);

  const inRange = history.filter((h) => h.t >= t0 && h.predicted_price);
  const prior = [...history].reverse().find((h) => h.t < t0 && h.predicted_price);

  const values = points.map((p) => p.c);
  if (predictedPrice) values.push(predictedPrice);
  inRange.forEach((h) => values.push(h.predicted_price));
  if (prior) values.push(prior.predicted_price);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const span = hi - lo || hi * 0.02 || 1;
  lo -= span * 0.08;
  hi += span * 0.08;
  const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * plotH;

  const first = points[0].c;
  const last = points[points.length - 1].c;
  const trend = last > first ? 'up' : last < first ? 'down' : 'flat';
  const spanDays = (t1 - t0) / 86400;

  const parts = [];
  if (projW) {
    parts.push(`<rect class="proj-zone" x="${pad.l + histW}" y="${pad.t}" width="${projW}" height="${plotH}" rx="4" opacity=".6"/>`);
    parts.push(`<text x="${pad.l + histW + projW / 2}" y="${height - 8}" text-anchor="middle">+${horizonDays}d</text>`);
  }
  for (const v of niceTicks(lo, hi, 4)) {
    parts.push(`<line class="grid" x1="${pad.l}" x2="${pad.l + plotW}" y1="${y(v)}" y2="${y(v)}"/>`);
    parts.push(`<text x="${pad.l + plotW + 8}" y="${y(v) + 4}">${fmtPrice(v, currency)}</text>`);
  }
  const labelCount = Math.max(2, Math.min(5, Math.floor(histW / 140)));
  for (let i = 0; i < labelCount; i++) {
    const t = t0 + ((t1 - t0) * i) / (labelCount - 1);
    const anchor = i === 0 ? 'start' : i === labelCount - 1 ? 'end' : 'middle';
    parts.push(`<text x="${x(t)}" y="${height - 8}" text-anchor="${anchor}">${dateLabel(t, spanDays)}</text>`);
  }

  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.c).toFixed(1)}`).join('');
  parts.push(`<path class="price-area ${trend}" opacity=".07" d="${line}L${x(t1)},${pad.t + plotH}L${x(t0)},${pad.t + plotH}Z"/>`);
  parts.push(`<path class="price-line ${trend}" d="${line}"/>`);

  if (inRange.length || prior) {
    const cls = outlook;
    let prev = prior ? prior.predicted_price : inRange[0].predicted_price;
    let d = `M${prior ? x(t0) : x(inRange[0].t)},${y(prev)}`;
    for (const h of inRange) {
      d += `L${x(h.t)},${y(prev)}L${x(h.t)},${y(h.predicted_price)}`;
      prev = h.predicted_price;
    }
    d += `L${x(t1)},${y(prev)}`;
    parts.push(`<path class="pred-hist ${cls}" d="${d}"/>`);
  }

  if (predictedPrice) {
    const ex = pad.l + plotW - 4;
    parts.push(`<path class="proj ${outlook}" d="M${x(t1)},${y(last)}L${ex},${y(predictedPrice)}"/>`);
    parts.push(`<circle cx="${ex}" cy="${y(predictedPrice)}" r="4" class="proj-label ${outlook}"/>`);
    const ly = Math.min(Math.max(y(predictedPrice) - 10, pad.t + 10), pad.t + plotH - 4);
    parts.push(`<text class="proj-label ${outlook}" x="${ex - 6}" y="${ly}" text-anchor="end">${fmtPrice(predictedPrice, currency)}</text>`);
  }

  parts.push(`<line class="cross" x1="0" x2="0" y1="${pad.t}" y2="${pad.t + plotH}" visibility="hidden"/>`);
  parts.push(`<circle class="cross-dot" r="4" visibility="hidden" fill="currentColor"/>`);
  parts.push(`<rect class="hover" x="${pad.l}" y="${pad.t}" width="${histW}" height="${plotH}" fill="transparent"/>`);

  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Price chart">${parts.join('')}</svg><div class="chart-tip" hidden></div>`;

  const svg = container.querySelector('svg');
  const cross = svg.querySelector('.cross');
  const dot = svg.querySelector('.cross-dot');
  const tip = container.querySelector('.chart-tip');
  const hover = svg.querySelector('.hover');
  dot.style.color = getComputedStyle(container).getPropertyValue(`--${trend}`) || 'currentColor';

  hover.addEventListener('mousemove', (e) => {
    const rect = svg.getBoundingClientRect();
    const scale = width / rect.width;
    const px = (e.clientX - rect.left) * scale;
    const t = t0 + ((px - pad.l) / histW) * (t1 - t0);
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(points[i].t - t) < Math.abs(points[best].t - t)) best = i;
    }
    const p = points[best];
    const cx = x(p.t);
    const cy = y(p.c);
    cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', cx); dot.setAttribute('cy', cy); dot.setAttribute('visibility', 'visible');
    const when = new Date(p.t * 1000).toLocaleString(undefined, spanDays <= 8
      ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
      : { year: 'numeric', month: 'short', day: 'numeric' });
    tip.textContent = `${when} · ${fmtPrice(p.c, currency)}`;
    tip.hidden = false;
    tip.style.left = `${cx / scale}px`;
    tip.style.top = `${cy / scale}px`;
  });
  hover.addEventListener('mouseleave', () => {
    cross.setAttribute('visibility', 'hidden');
    dot.setAttribute('visibility', 'hidden');
    tip.hidden = true;
  });
}
