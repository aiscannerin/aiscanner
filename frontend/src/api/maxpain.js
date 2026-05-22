import client from './client'

export const maxpainApi = {
  /**
   * Run the deviation scanner.
   * @param {object} params – { threshold, symbols, expiry }
   */
  // Dhan rate-limits option-chain to 1 req/3s, so a full 47-symbol scan can
  // take 3-5 minutes on the first run. Allow up to 8 minutes.
  scan: (params = {}) =>
    client.get('/max-pain/scan', { params, timeout: 480000 }),

  /**
   * Full detail for a single symbol.
   */
  symbolDetail: (symbol, expiry = null) =>
    client.get(`/max-pain/symbol/${symbol}`, {
      params:  expiry ? { expiry } : {},
      timeout: 30000,
    }),

  /**
   * Raw option chain for a symbol.
   */
  optionChain: (symbol, expiry = null) =>
    client.get(`/max-pain/option-chain/${symbol}`, {
      params:  expiry ? { expiry } : {},
      timeout: 30000,
    }),

  /**
   * Default F&O universe list.
   */
  universe: () => client.get('/max-pain/universe'),

  // ── Debug endpoints (no JWT required) ──────────────────────────────────────

  /**
   * NSE fetcher health: connectivity probe + cache/fetch stats.
   */
  debugNseStatus: () =>
    client.get('/max-pain/debug/nse-status', { timeout: 20000 }),

  /**
   * Full diagnostic for one symbol — bypasses threshold filter.
   */
  debugTestSymbol: (symbol, expiry = null) =>
    client.get(`/max-pain/debug/test-symbol/${symbol}`, {
      params:  expiry ? { expiry } : {},
      timeout: 60000,
    }),

  /**
   * Raw scan at 0% threshold — returns every successfully fetched symbol.
   * @param {string[]} symbols – defaults to first 5 of default universe
   */
  debugRawScan: (symbols = [], expiry = null) =>
    client.get('/max-pain/debug/raw-scan', {
      params: {
        ...(symbols.length ? { symbols: symbols.join(',') } : {}),
        ...(expiry ? { expiry } : {}),
      },
      timeout: 120000,
    }),

  // ── Snapshot endpoints ────────────────────────────────────────────────────

  /**
   * Most recent successful scan snapshot, optionally filtered by threshold.
   * @param {number|null} threshold
   */
  snapshotLatest: (threshold = null) =>
    client.get('/max-pain/snapshots/latest', {
      params:  threshold != null ? { threshold } : {},
      timeout: 10000,
    }),

  /**
   * History list of scan snapshots (metadata only, no payload).
   * @param {number} limit – max rows to return (default 20)
   */
  snapshotHistory: (limit = 20) =>
    client.get('/max-pain/snapshots/history', { params: { limit }, timeout: 10000 }),
}
