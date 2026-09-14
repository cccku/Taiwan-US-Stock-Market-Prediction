// ── safe HTML templating ──────────────────────────────────────────────────
// Interpolated values are escaped unless produced by html`` or raw().
export class Raw {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}
export const raw = (s) => new Raw(String(s));

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderValue(v) {
  if (v == null || v === false) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(renderValue).join('');
  return escapeHtml(v);
}

export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((v, i) => { out += renderValue(v) + strings[i + 1]; });
  return new Raw(out);
}

export function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '#';
  } catch { return '#'; }
}

// ── numbers ───────────────────────────────────────────────────────────────
const CURRENCY_PREFIX = { TWD: 'NT$', USD: '$' };

export function fmtNumber(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPrice(v, currency) {
  if (v == null) return '—';
  return (CURRENCY_PREFIX[currency] ?? '') + fmtNumber(v, 2);
}

export function fmtSigned(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  return sign + fmtNumber(Math.abs(v), digits);
}

/** fraction → "+1.2%" */
export const fmtPct = (frac, digits = 1) => (frac == null ? '—' : `${fmtSigned(frac * 100, digits)}%`);
/** percentage points → "+1.2%" */
export const fmtPP = (pp, digits = 1) => (pp == null ? '—' : `${fmtSigned(pp, digits)}%`);

export function fmtCompact(v, currency) {
  if (v == null) return '—';
  return (CURRENCY_PREFIX[currency] ?? '') + Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(v);
}

export const dirClass = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');
export const arrow = (v) => (v > 0 ? '▲' : v < 0 ? '▼' : '•');

// ── time ──────────────────────────────────────────────────────────────────
export function timeAgo(ts) {
  if (!ts) return '—';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return fmtDate(ts);
}

export const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
export const fmtDateTime = (ts) => new Date(ts * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

// ── labels ────────────────────────────────────────────────────────────────
export const OUTLOOK_LABEL = { up: 'Upside', down: 'Downside', neutral: 'Neutral' };
export const DURATION_LABEL = { transient: 'short-lived', medium: 'weeks to months', structural: 'long-term' };
export const PILLAR_LABEL = { leadership: 'Leadership', product: 'Product', price: 'Price', demand_supply: 'Demand/supply', macro: 'Macro' };
export const CATEGORY_LABEL = {
  earnings: 'Earnings', guidance: 'Guidance', product: 'Product', customer_contract: 'Customer / contract',
  capacity_supply: 'Capacity / supply', demand_signal: 'Demand signal', leadership_management: 'Leadership',
  capital_allocation: 'Capital allocation', regulation_geopolitics: 'Regulation / geopolitics',
  legal_governance: 'Legal / governance', competition: 'Competition', analyst_rating: 'Analyst rating',
  macro: 'Macro', other: 'Other',
};

export function engineLabel(engine) {
  if (!engine) return '';
  if (engine.startsWith('heuristic')) return 'keyword heuristic';
  return engine.split('-').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

export const stockHref = (ticker) => `#/stock/${encodeURIComponent(ticker)}`;
