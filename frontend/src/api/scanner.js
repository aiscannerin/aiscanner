import client from './client'

export const apiStartScan      = (payload)         => client.post('/scanners/stop-hunter-pro/start', payload)
export const apiGetJob         = (jobId)           => client.get(`/scanners/jobs/${jobId}`)
export const apiGetResults     = (jobId, page = 1) => client.get(`/scanners/jobs/${jobId}/results`, { params: { page, per_page: 100 } })
export const apiRecentScans    = ()                => client.get('/scanners/recent')

// ── Scan history (persistence layer) ──────────────────────────────────────────
export const apiRecentScanRuns    = ()             => client.get('/scans/recent')
export const apiScanRunResults    = (runId)        => client.get(`/scans/${runId}/results`, { params: { per_page: 200 } })
export const apiSymbolHistory     = (symbol, limit = 20) => client.get(`/scans/symbol/${symbol}/history`, { params: { limit } })
