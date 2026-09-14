async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let message = res.statusText;
    try { message = (await res.json()).detail || message; } catch { /* non-JSON error */ }
    throw new Error(message);
  }
  return res.json();
}

const qs = (params) => {
  const entries = Object.entries(params).filter(([, v]) => v !== '' && v != null);
  return entries.length ? `?${new URLSearchParams(entries)}` : '';
};

export const api = {
  status: () => request('GET', '/api/status'),
  refresh: (reason = 'manual') => request('POST', `/api/refresh${qs({ reason })}`),
  dashboard: () => request('GET', '/api/dashboard'),
  stock: (ticker) => request('GET', `/api/stocks/${encodeURIComponent(ticker)}`),
  history: (ticker, range) => request('GET', `/api/stocks/${encodeURIComponent(ticker)}/history${qs({ range })}`),
  news: (filters) => request('GET', `/api/news${qs(filters)}`),
  supplyChain: () => request('GET', '/api/supply-chain'),
  settings: () => request('GET', '/api/settings'),
  putPrefs: (patch) => request('PUT', '/api/prefs', patch),
  reloadConfig: () => request('POST', '/api/config/reload'),
};
