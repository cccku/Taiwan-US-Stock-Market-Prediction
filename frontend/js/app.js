import { api } from './api.js';
import { html, timeAgo } from './format.js';
import { emit, on, setPrefsLocal } from './state.js';
import * as dashboard from './views/dashboard.js';
import * as stock from './views/stock.js';
import * as news from './views/news.js';
import * as supply from './views/supply.js';
import * as settings from './views/settings.js';

const root = document.getElementById('app');
const statusEl = document.getElementById('refresh-status');

const ROUTES = [
  { re: /^#?\/?$/, view: dashboard, nav: 'dashboard', params: () => ({}) },
  { re: /^#\/stock\/(.+)$/, view: stock, nav: 'dashboard', params: (m) => ({ ticker: decodeURIComponent(m[1]) }) },
  { re: /^#\/news$/, view: news, nav: 'news', params: () => ({}) },
  { re: /^#\/supply-chain$/, view: supply, nav: 'supply', params: () => ({}) },
  { re: /^#\/settings$/, view: settings, nav: 'settings', params: () => ({}) },
];

let current = null;
let renderSeq = 0;

async function renderCurrent(silent) {
  if (!current) return;
  const seq = ++renderSeq;
  try {
    await current.view.render(root, current.params, { silent, isStale: () => seq !== renderSeq });
  } catch (err) {
    if (seq !== renderSeq) return;
    if (!silent) root.innerHTML = html`<div class="error-box"><strong>Could not load this page.</strong><br>${err.message}</div>`;
    console.error(err);
  }
}

function route() {
  const hash = location.hash || '#/';
  const match = ROUTES.map((r) => ({ r, m: hash.match(r.re) })).find((x) => x.m);
  if (!match) { location.hash = '#/'; return; }
  current?.view.unmount?.();
  current = { view: match.r.view, params: match.r.params(match.m) };
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === match.r.nav));
  root.innerHTML = '<div class="loading">Loading…</div>';
  window.scrollTo(0, 0);
  renderCurrent(false);
}

// ── refresh loop: on open, then every `interval_seconds` while the app is open ──
const PHASE_TEXT = {
  starting: 'Starting refresh', prices: 'Fetching prices', fundamentals: 'Updating valuations',
  news: 'Collecting news', analysis: 'Analyzing news impact', predictions: 'Updating predictions',
};
let lastStatus = null;
let lastVersion = null;
let pollTimer = null;
let autoTimer = null;

function paintStatus(s) {
  lastStatus = s;
  const dot = s.running ? 'busy' : s.last_status === 'error' ? 'err' : '';
  const text = s.running
    ? `${PHASE_TEXT[s.phase] || 'Refreshing'}…`
    : s.last_status === 'error' ? `Refresh failed · ${timeAgo(s.finished_at)}`
    : s.finished_at ? `Updated ${timeAgo(s.finished_at)}` : 'Not refreshed yet';
  statusEl.innerHTML = html`
    <span class="dot ${dot}"></span>
    <span title="${s.last_error || ''}">${text}</span>
    <button class="icon-btn" id="refresh-now" title="Refresh now" ${s.running ? 'disabled' : ''}>↻</button>`;
  statusEl.querySelector('#refresh-now').onclick = () => triggerRefresh('manual');
  emit('status', s);
}

async function poll() {
  clearTimeout(pollTimer);
  try {
    const s = await api.status();
    const changed = lastVersion !== null && s.data_version !== lastVersion;
    const finished = lastStatus?.running && !s.running;
    lastVersion = s.data_version;
    paintStatus(s);
    if (changed || finished) {
      if (!current?.view.isBusy?.()) renderCurrent(true);
    }
    pollTimer = setTimeout(poll, s.running ? 2500 : 20000);
  } catch {
    statusEl.innerHTML = '<span class="dot err"></span><span>Server unreachable</span>';
    pollTimer = setTimeout(poll, 5000);
  }
}

async function triggerRefresh(reason) {
  try {
    const { status } = await api.refresh(reason);
    paintStatus(status);
  } catch { /* poll() will surface connectivity problems */ }
  poll();
}

function scheduleAuto(intervalSeconds) {
  clearInterval(autoTimer);
  autoTimer = setInterval(() => triggerRefresh('auto'), intervalSeconds * 1000);
}

on('request-refresh', () => triggerRefresh('manual'));
on('rerender', () => renderCurrent(true));

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible' || !lastStatus) return;
  const age = Date.now() / 1000 - (lastStatus.finished_at || 0);
  if (!lastStatus.running && age > (lastStatus.interval_seconds || 300)) triggerRefresh('focus');
});

async function boot() {
  try {
    const d = await api.dashboard();
    setPrefsLocal(d.prefs);
  } catch { /* first render will show the error */ }
  window.addEventListener('hashchange', route);
  route();
  await triggerRefresh('open');
  scheduleAuto(lastStatus?.interval_seconds || 300);
}

boot();
