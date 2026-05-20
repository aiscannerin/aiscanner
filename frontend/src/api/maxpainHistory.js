import client from './client'

const BASE = '/max-pain/history'

export const historyApi = {
  trend: (symbol, params = {}) =>
    client.get(`${BASE}/trend/${symbol}`, { params }),

  drift: (symbol, params = {}) =>
    client.get(`${BASE}/drift/${symbol}`, { params }),

  oiWall: (symbol, params = {}) =>
    client.get(`${BASE}/oi-wall/${symbol}`, { params }),

  reversalScore: (symbol, params = {}) =>
    client.get(`${BASE}/reversal-score/${symbol}`, { params }),

  latest: (symbols) =>
    client.get(`${BASE}/latest`, { params: { symbols: symbols.join(',') } }),
}
