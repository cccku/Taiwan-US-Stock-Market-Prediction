import { api } from './api.js';

const bus = new EventTarget();
export const on = (name, fn) => bus.addEventListener(name, (e) => fn(e.detail));
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));

let prefs = { favorites: [], price_colors: 'western' };

export const getPrefs = () => prefs;

export function setPrefsLocal(patch) {
  prefs = { ...prefs, ...patch };
  document.documentElement.classList.toggle('tw-colors', prefs.price_colors === 'taiwan');
}

export async function savePrefs(patch) {
  setPrefsLocal(patch);
  setPrefsLocal(await api.putPrefs(patch));
  return prefs;
}

export function loadLocal(key, fallback) {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) || '{}') }; } catch { return { ...fallback }; }
}

export function saveLocal(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
