import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity, RefreshCw, Settings2, AlertTriangle,
  Play, Wifi, Bug, ChevronRight,
  CheckCircle, XCircle, Info, Clock, Archive
} from 'lucide-react'
import SummaryCards from '../components/maxpain/SummaryCards'
import ScannerTable from '../components/maxpain/ScannerTable'
import StockDrawer from '../components/maxpain/StockDrawer'
import { maxpainApi } from '../api/maxpain'

const THRESHOLD_OPTIONS = [
  { label: '0% (All)',     value: 0 },
  { label: '2% (Default)', value: 2 },
  { label: '4% (High)',    value: 4 },
  { label: '6% (Extreme)', value: 6 },
]
const REFRESH_INTERVALS = [
  { label: 'Manual', value: 0 },
  { label: '2 min',  value: 120 },
  { label: '5 min',  value: 300 },
]

function LiveBadge({ active, usingSnapshot }) {
  if (usingSnapshot) {
    return (
      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border bg-blue-500/10 border-blue-500/30 text-blue-400">
        <Archive className="w-3 h-3" />
        SNAPSHOT
      </div>
    )
  }
  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border ${
      active
        ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
        : 'bg-slate-800 border-slate-700 text-slate-500'
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
      {active ? 'LIVE' : 'IDLE'}
    </div>
  )
}

/**
 * SnapshotBanner — blue informational strip shown when serving fallback data.
 * Tells the trader exactly how old the data is and why live data isn't available.
 */
function SnapshotBanner({ snapshotCreatedAt, snapshotAgeMinutes, onDismiss }) {
  if (!snapshotCreatedAt) return null

  // Format "3:29 PM IST" from the ISO timestamp
  const formattedTime = (() => {
    try {
      return new Date(snapshotCreatedAt).toLocaleTimeString('en-IN', {
        hour:   '2-digit',
        minute: '2-digit',
        timeZone: 'Asia/Kolkata',
      }) + ' IST'
    } catch {
      return snapshotCreatedAt
    }
  })()

  const ageText = snapshotAgeMinutes < 60
    ? `${Math.round(snapshotAgeMinutes)} min ago`
    : `${(snapshotAgeMinutes / 60).toFixed(1)}h ago`

  return (
    <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl px-4 py-3 flex items-start gap-3">
      <Archive className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
      <div className="flex-1">
        <p className="text-sm font-semibold text-blue-400">
          Market closed — showing last live snapshot from {formattedTime}
        </p>
        <p className="text-xs text-blue-400/70 mt-0.5">
          Captured {ageText}. Live data will resume when NSE opens (Mon–Fri 9:15–15:30 IST).
          Auto-refresh has been paused.
        </p>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-blue-400/50 hover:text-blue-400 flex-shrink-0 transition-colors"
        >
          ✕
        </button>
      )}
    </div>
  )
}

function ControlBar({
  threshold, setThreshold, refreshInterval, setRefreshInterval,
  onScan, scanning, lastUpdate, customThreshold, setCustomThreshold,
}) {
  const [showCustom, setShowCustom] = useState(false)

  return (
    <div className="bg-[#0f1117] border border-slate-700/50 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
      {/* Threshold selector */}
      <div className="flex items-center gap-2">
        <Settings2 className="w-3.5 h-3.5 text-slate-500" />
        <span className="text-xs text-slate-500">Threshold:</span>
        <div className="flex gap-1">
          {THRESHOLD_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => { setThreshold(opt.value); setShowCustom(false) }}
              className={`px-2.5 py-1 text-xs rounded font-medium transition-colors ${
                threshold === opt.value && !showCustom
                  ? 'bg-violet-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {opt.label}
            </button>
          ))}
          <button
            onClick={() => setShowCustom(s => !s)}
            className={`px-2.5 py-1 text-xs rounded font-medium transition-colors ${
              showCustom ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            Custom
          </button>
        </div>
        {showCustom && (
          <div className="flex items-center gap-1">
            <input
              type="number"
              min="0"
              max="20"
              step="0.5"
              value={customThreshold}
              onChange={e => { setCustomThreshold(e.target.value); setThreshold(parseFloat(e.target.value) || 0) }}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 w-16 focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
            <span className="text-xs text-slate-500">%</span>
          </div>
        )}
      </div>

      <div className="h-4 w-px bg-slate-700 hidden sm:block" />

      {/* Auto-refresh */}
      <div className="flex items-center gap-2">
        <Wifi className="w-3.5 h-3.5 text-slate-500" />
        <span className="text-xs text-slate-500">Auto:</span>
        <div className="flex gap-1">
          {REFRESH_INTERVALS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setRefreshInterval(opt.value)}
              className={`px-2.5 py-1 text-xs rounded font-medium transition-colors ${
                refreshInterval === opt.value
                  ? 'bg-violet-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-3">
        {lastUpdate && (
          <span className="text-[11px] text-slate-600 hidden sm:block">
            Updated {lastUpdate}
          </span>
        )}
        <button
          onClick={onScan}
          disabled={scanning}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors"
        >
          {scanning
            ? <RefreshCw className="w-4 h-4 animate-spin" />
            : <Play className="w-4 h-4" />
          }
          {scanning ? 'Scanning…' : 'Run Scan'}
        </button>
      </div>
    </div>
  )
}

/**
 * DiagnosticsPanel — shows per-scan metrics and backend error list.
 * Only visible when the scan has run and there's something to show.
 */
function DiagnosticsPanel({ scanMeta, nseOk, fetchErrors, belowThreshold, marketClosed, scanMetrics, threshold }) {
  const [open, setOpen] = useState(false)
  if (!scanMeta) return null

  const hasErrors      = fetchErrors?.length > 0
  const hasMarketClose = marketClosed?.length > 0
  const borderClass    = hasErrors
    ? 'border-amber-500/30 bg-amber-500/5'
    : hasMarketClose
      ? 'border-blue-500/20 bg-blue-500/5'
      : 'border-slate-700/40 bg-[#0f1117]'

  return (
    <div className={`rounded-xl border text-xs overflow-hidden ${borderClass}`}>
      {/* Header */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-800/30 transition-colors"
      >
        <Bug className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
        <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
          Scan Diagnostics
        </span>

        {/* Inline summary chips */}
        <div className="flex items-center gap-2 ml-2 flex-wrap">
          <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-400">
            Scanned: <span className="text-slate-200">{scanMeta.total_scanned ?? '—'}</span>
          </span>
          <span className="px-2 py-0.5 rounded bg-violet-500/10 border border-violet-500/20 text-violet-300">
            Hits: {scanMeta.total_hits ?? 0}
          </span>
          <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-500">
            Below {threshold}%: {belowThreshold?.length ?? scanMeta.total_below_threshold ?? 0}
          </span>
          {hasMarketClose && (
            <span className="px-2 py-0.5 rounded bg-blue-500/15 border border-blue-500/30 text-blue-300">
              Market closed: {marketClosed.length}
            </span>
          )}
          {hasErrors && (
            <span className="px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/30 text-amber-400">
              NSE errors: {fetchErrors.length}
            </span>
          )}
          {scanMetrics?.avg_fetch_ms != null && (
            <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-500">
              avg {Math.round(scanMetrics.avg_fetch_ms)}ms
            </span>
          )}
          {nseOk !== undefined && (
            nseOk
              ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
              : <XCircle    className="w-3.5 h-3.5 text-amber-400" />
          )}
        </div>

        <ChevronRight className={`w-3.5 h-3.5 text-slate-600 ml-auto transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>

      {/* Expanded detail */}
      {open && (
        <div className="px-4 pb-4 border-t border-slate-800 pt-3 space-y-3">

          {/* Scan metrics grid */}
          {scanMetrics && (
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Scan Metrics</p>
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                {[
                  { label: 'Total',        value: scanMetrics.symbols_total },
                  { label: 'Fetch OK',     value: scanMetrics.fetch_success, color: 'text-emerald-400' },
                  { label: 'Fetch Failed', value: scanMetrics.fetch_failed,  color: scanMetrics.fetch_failed > 0 ? 'text-amber-400' : undefined },
                  { label: 'Mkt Closed',  value: scanMetrics.market_closed, color: scanMetrics.market_closed > 0 ? 'text-blue-400' : undefined },
                  { label: 'Filtered',     value: scanMetrics.threshold_filtered },
                  { label: 'Results',      value: scanMetrics.returned_results, color: 'text-violet-400' },
                  { label: 'Avg fetch',    value: scanMetrics.avg_fetch_ms != null ? `${Math.round(scanMetrics.avg_fetch_ms)}ms` : '—' },
                  { label: 'Elapsed',      value: scanMetrics.scan_elapsed_ms != null ? `${(scanMetrics.scan_elapsed_ms/1000).toFixed(1)}s` : '—' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-slate-800/60 rounded px-2 py-1.5">
                    <p className="text-[10px] text-slate-500 mb-0.5">{label}</p>
                    <p className={`text-sm font-bold ${color || 'text-slate-200'}`}>{value ?? '—'}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* NSE status */}
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">NSE Fetch Status</p>
            {hasMarketClose && !hasErrors && (
              <p className="text-blue-400 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                NSE returned empty responses — market is closed. Data available Mon–Fri 9:15–15:30 IST.
              </p>
            )}
            {nseOk === true && !hasMarketClose && (
              <p className="text-emerald-400 flex items-center gap-1.5">
                <CheckCircle className="w-3.5 h-3.5" /> All symbols fetched successfully
              </p>
            )}
            {nseOk === false && hasErrors && (
              <p className="text-amber-400 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                {fetchErrors?.length} symbol(s) failed to fetch from NSE.
              </p>
            )}
          </div>

          {/* Error list */}
          {hasErrors && (
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
                Failed Symbols ({fetchErrors.length})
              </p>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {fetchErrors.map((e, i) => (
                  <div key={i} className="flex items-start gap-2 text-[11px] bg-slate-800/60 rounded px-2 py-1">
                    <span className="text-amber-400 font-mono font-bold flex-shrink-0">{e.symbol}</span>
                    <span className="text-slate-400 break-all">{e.error}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Debug shortcuts */}
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Quick Debug</p>
            <div className="flex flex-wrap gap-2">
              {[
                { label: 'NSE Status',         href: '/api/max-pain/debug/nse-status' },
                { label: 'Live Scan (10)',      href: '/api/max-pain/debug/live-scan' },
                { label: 'Test NIFTY',         href: '/api/max-pain/debug/test-symbol/NIFTY' },
                { label: 'Raw Scan (0%)',       href: '/api/max-pain/debug/raw-scan' },
              ].map(({ label, href }) => (
                <a key={href} href={href} target="_blank" rel="noopener noreferrer"
                  className="px-2.5 py-1 rounded bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors border border-slate-700/50"
                >
                  {label} →
                </a>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * TelemetryBar — live scan metrics strip shown while scanning or after completion.
 * "46 symbols • 41 fetched • 3 failed • avg 312ms • 4 workers"
 */
function TelemetryBar({ scanning, metrics, resultsCount, totalScanned }) {
  if (!scanning && !metrics) return null

  const chips = []

  if (scanning && !metrics) {
    chips.push(
      <span key="scanning" className="flex items-center gap-1.5 text-violet-300">
        <RefreshCw className="w-3 h-3 animate-spin" />
        Scanning NSE…
        {totalScanned > 0 && (
          <span className="text-slate-400">({totalScanned} completed)</span>
        )}
      </span>
    )
  } else if (metrics) {
    if (metrics.symbols_total)       chips.push(<span key="tot" className="text-slate-300">{metrics.symbols_total} symbols</span>)
    if (metrics.fetch_success != null) chips.push(<span key="ok"  className="text-emerald-400">{metrics.fetch_success} fetched</span>)
    if (metrics.fetch_failed)         chips.push(<span key="fail" className="text-amber-400">{metrics.fetch_failed} failed</span>)
    if (metrics.market_closed)        chips.push(<span key="mc"   className="text-blue-400">{metrics.market_closed} mkt closed</span>)
    if (metrics.returned_results != null) chips.push(<span key="res"  className="text-violet-400">{metrics.returned_results} hits</span>)
    if (metrics.avg_fetch_ms != null) chips.push(<span key="ms"  className="text-slate-500">avg {Math.round(metrics.avg_fetch_ms)}ms</span>)
    if (metrics.scan_elapsed_ms != null) chips.push(<span key="el" className="text-slate-500">{(metrics.scan_elapsed_ms/1000).toFixed(1)}s total</span>)
  }

  return (
    <div className="flex items-center gap-2.5 px-4 py-2 bg-slate-900/60 border border-slate-800 rounded-lg text-[11px] flex-wrap">
      <Clock className="w-3 h-3 text-slate-600 flex-shrink-0" />
      {chips.map((c, i) => (
        <span key={i} className="contents">
          {i > 0 && <span className="text-slate-700">•</span>}
          {c}
        </span>
      ))}
    </div>
  )
}

export default function MaxPainScannerPage() {
  const navigate = useNavigate()
  const [results,      setResults]      = useState([])
  const [summary,      setSummary]      = useState(null)
  const [scanning,     setScanning]     = useState(false)
  const [error,        setError]        = useState(null)
  const [selectedStock, setSelectedStock] = useState(null)
  const [threshold,    setThreshold]    = useState(2)
  const [customThreshold, setCustomThreshold] = useState(2)
  const [refreshInterval, setRefreshInterval] = useState(0)
  const [lastUpdate,   setLastUpdate]   = useState(null)
  const [hasScanned,   setHasScanned]   = useState(false)

  // Diagnostic state — populated from backend response
  const [fetchErrors,     setFetchErrors]     = useState([])
  const [belowThreshold,  setBelowThreshold]  = useState([])
  const [marketClosed,        setMarketClosed]        = useState([])
  const [scanMetrics,         setScanMetrics]         = useState(null)
  const [nseOk,               setNseOk]               = useState(undefined)
  const [isMarketClosed,      setIsMarketClosed]      = useState(false)
  // Snapshot fallback state
  const [usingSnapshot,       setUsingSnapshot]       = useState(false)
  const [snapshotCreatedAt,   setSnapshotCreatedAt]   = useState(null)
  const [snapshotAgeMinutes,  setSnapshotAgeMinutes]  = useState(null)
  const [snapshotBannerDismissed, setSnapshotBannerDismissed] = useState(false)
  // Broker (Dhan) connection state — derived from scan response
  const [brokerConnected,     setBrokerConnected]     = useState(true)
  const [brokerTokenInvalid,  setBrokerTokenInvalid]  = useState(false)

  const timerRef = useRef(null)

  const runScan = useCallback(async () => {
    setScanning(true)
    setError(null)
    setIsMarketClosed(false)
    setUsingSnapshot(false)
    setSnapshotBannerDismissed(false)
    try {
      const res = await maxpainApi.scan({ threshold })

      // ── Unwrap envelope ──────────────────────────────────────────────────
      const envelope   = res.data ?? {}
      const data       = envelope.data ?? {}

      // Results live inside data (live scan or flattened snapshot payload)
      const rows       = data.results          ?? []
      const sum        = data.summary          ?? null
      const errs       = data.errors           ?? []
      const below      = data.below_threshold  ?? []
      const closed     = data.market_closed    ?? []

      // Snapshot fallback fields — top-level in the envelope (NOT inside data)
      const snapshotFallback = Boolean(envelope.using_snapshot_fallback)
      const snapshotAge      = envelope.snapshot_age_minutes    ?? null
      const snapshotCreated  = envelope.snapshot_created_at     ?? null
      const fallbackReason   = envelope.snapshot_fallback_reason ?? null

      // Live scan metrics come from meta; hide them when serving a snapshot
      // (they'd show "46 mkt closed, 0 fetched" which confuses users)
      const liveMetrics = snapshotFallback ? null : (envelope.meta?.metrics ?? null)

      // ── Debug: full response visibility ─────────────────────────────────
      console.group('[Scanner] runScan response')
      console.log('envelope keys:', Object.keys(envelope))
      console.log('using_snapshot_fallback:', snapshotFallback)
      console.log('snapshot_fallback_reason:', fallbackReason)
      console.log('snapshot_created_at:', snapshotCreated)
      console.log('snapshot_age_minutes:', snapshotAge)
      console.log('rows.length:', rows.length)
      console.log('rows[0]:', rows[0] ?? '(none)')
      console.log('errs.length:', errs.length)
      console.log('closed.length:', closed.length)
      console.log('market_closed (bool):', envelope.market_closed)
      console.log('data keys:', Object.keys(data))
      console.groupEnd()

      // ── Commit state ─────────────────────────────────────────────────────
      setResults(rows)
      setSummary(sum)
      setFetchErrors(errs)
      setBelowThreshold(below)
      setMarketClosed(closed)
      setScanMetrics(liveMetrics)
      setNseOk(errs.length === 0)
      setLastUpdate(new Date().toLocaleTimeString())
      setHasScanned(true)

      // Broker connection state (Dhan)
      setBrokerConnected(envelope.broker_connected !== false)
      setBrokerTokenInvalid(Boolean(envelope.broker_token_invalid))

      // ── Snapshot fallback active ─────────────────────────────────────────
      // Priority 1: backend served a snapshot — show banner, table renders rows
      if (snapshotFallback) {
        console.log('[Scanner] SNAPSHOT MODE ACTIVE — rows:', rows.length, 'age:', snapshotAge, 'min')
        setUsingSnapshot(true)
        setSnapshotCreatedAt(snapshotCreated)
        setSnapshotAgeMinutes(snapshotAge)
        // Don't set any error — SnapshotBanner handles the user communication
        return
      }

      // ── Priority 2: rows exist (live data above threshold) — no error ────
      if (rows.length > 0) {
        console.log('[Scanner] LIVE DATA — rows:', rows.length)
        return
      }

      // ── Priority 3: market closed, no snapshot available ─────────────────
      const isClosedState = closed.length > 0 && errs.length === 0
      setIsMarketClosed(isClosedState)
      if (isClosedState) {
        console.log('[Scanner] MARKET CLOSED — no snapshot available')
        setError(
          `NSE market is closed — ${closed.length} symbol(s) returned no data. ` +
          `No prior snapshot available yet. ` +
          `Option chain data is only available during market hours (Mon–Fri 9:15–15:30 IST).`
        )
        return
      }

      // ── Priority 4: NSE fetch errors, no snapshot ────────────────────────
      if (errs.length > 0) {
        const firstErr = errs[0]
        console.log('[Scanner] NSE ERRORS — count:', errs.length, 'first:', firstErr?.symbol)
        setError(
          `NSE data unavailable — ${errs.length} symbol(s) failed. ` +
          `First error (${firstErr.symbol}): ${firstErr.error}. ` +
          `Try the NSE Status debug link below.`
        )
        return
      }

      // ── Priority 5: nothing above threshold ──────────────────────────────
      if (below.length > 0) {
        console.log('[Scanner] BELOW THRESHOLD — below:', below.length)
        setError(
          `Scan complete — no symbols exceed the ${threshold}% threshold. ` +
          `Try lowering it to 0% to see all ${below.length} scanned symbols.`
        )
      }
    } catch (e) {
      const msg =
        e?.response?.data?.error ||
        e?.response?.data?.message ||
        (e?.response?.status === 401
          ? 'Authentication error — please log in again.'
          : e.message || 'Scan failed. Check backend connectivity.')
      console.error('[Scanner] runScan exception:', e)
      setError(msg)
    } finally {
      setScanning(false)
    }
  }, [threshold])

  // Auto-refresh — paused when serving snapshot fallback data
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (refreshInterval > 0 && !usingSnapshot) {
      timerRef.current = setInterval(runScan, refreshInterval * 1000)
    }
    return () => clearInterval(timerRef.current)
  }, [refreshInterval, runScan, usingSnapshot])

  return (
    <div className="min-h-screen bg-[#060810] text-slate-200">
      <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-5">

        {/* Page header */}
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <div className="p-2 bg-violet-600/20 rounded-lg border border-violet-500/20">
                <Activity className="w-5 h-5 text-violet-400" />
              </div>
              <h1 className="text-xl font-bold text-slate-100">Max Pain Deviation Scanner</h1>
              <LiveBadge active={refreshInterval > 0 && hasScanned && !usingSnapshot} usingSnapshot={usingSnapshot} />
            </div>
            <p className="text-sm text-slate-500 ml-12">
              Identify F&O stocks trading far from max pain — ranked by deviation strength & reversal probability
            </p>
          </div>
        </div>

        {/* Connect-Dhan banner — shown when the user has no/invalid Dhan token.
            Live refresh needs the user's own Dhan API token. */}
        {hasScanned && (!brokerConnected || brokerTokenInvalid) && (
          <div className="rounded-xl px-4 py-3 flex items-start gap-3 border bg-amber-500/10 border-amber-500/30">
            <Info className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-amber-400">
                {brokerTokenInvalid ? 'Dhan token expired or invalid' : 'Connect your Dhan account for live data'}
              </p>
              <p className="text-xs mt-0.5 leading-relaxed text-amber-400/80">
                {brokerTokenInvalid
                  ? 'Your saved Dhan access token was rejected. Reconnect to refresh live option-chain data. '
                  : 'Live option-chain data is fetched using your own Dhan API token. '}
                {results.length > 0 && 'You are currently viewing the latest shared snapshot.'}
              </p>
            </div>
            <button
              onClick={() => navigate('/settings')}
              className="flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500/20 border border-amber-500/40 text-amber-300 hover:bg-amber-500/30"
            >
              {brokerTokenInvalid ? 'Reconnect Dhan →' : 'Connect Dhan →'}
            </button>
          </div>
        )}

        {/* Error / notice banner — suppressed when rows are already showing
            (snapshot rows take visual priority over any stale error state) */}
        {error && results.length === 0 && (
          <div className={`rounded-xl px-4 py-3 flex items-start gap-3 border ${
            isMarketClosed
              ? 'bg-blue-500/10 border-blue-500/30'
              : 'bg-red-500/10 border-red-500/30'
          }`}>
            {isMarketClosed
              ? <Info className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
              : <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
            }
            <div>
              <p className={`text-sm font-semibold ${isMarketClosed ? 'text-blue-400' : 'text-red-400'}`}>
                {isMarketClosed ? 'Market Closed' : 'Scan Notice'}
              </p>
              <p className={`text-xs mt-0.5 leading-relaxed ${isMarketClosed ? 'text-blue-400/80' : 'text-red-400/80'}`}>{error}</p>
            </div>
            <button onClick={() => setError(null)} className="ml-auto text-slate-500 hover:text-slate-300 flex-shrink-0">✕</button>
          </div>
        )}

        {/* Snapshot fallback banner */}
        {usingSnapshot && !snapshotBannerDismissed && (
          <SnapshotBanner
            snapshotCreatedAt={snapshotCreatedAt}
            snapshotAgeMinutes={snapshotAgeMinutes}
            onDismiss={() => setSnapshotBannerDismissed(true)}
          />
        )}

        {/* Control bar */}
        <ControlBar
          threshold={threshold}
          setThreshold={setThreshold}
          refreshInterval={refreshInterval}
          setRefreshInterval={setRefreshInterval}
          onScan={runScan}
          scanning={scanning}
          lastUpdate={lastUpdate}
          customThreshold={customThreshold}
          setCustomThreshold={setCustomThreshold}
        />

        {/* Summary cards */}
        <SummaryCards summary={summary} loading={scanning && !hasScanned} />

        {/* Telemetry bar */}
        {(scanning || scanMetrics) && (
          <TelemetryBar
            scanning={scanning}
            metrics={scanMetrics}
            resultsCount={results.length}
            totalScanned={scanMetrics?.fetch_success ?? 0}
          />
        )}

        {/* Diagnostics panel — shown after first scan */}
        {hasScanned && (
          <DiagnosticsPanel
            scanMeta={summary}
            nseOk={nseOk}
            fetchErrors={fetchErrors}
            belowThreshold={belowThreshold}
            marketClosed={marketClosed}
            scanMetrics={scanMetrics}
            threshold={threshold}
          />
        )}

        {/* Priority 1 — Scanner table: shown as soon as we have rows OR are scanning.
            Snapshot rows render identically to live rows.
            Checked FIRST so a table with data always takes visual priority. */}
        {(results.length > 0 || scanning) && (
          <ScannerTable
            data={results}
            loading={scanning}
            onRowClick={setSelectedStock}
          />
        )}

        {/* Priority 2 — Pre-scan empty state: only when never scanned yet */}
        {!hasScanned && !scanning && results.length === 0 && (
          <div className="bg-[#0f1117] border border-slate-700/50 rounded-xl py-20 flex flex-col items-center gap-4 text-center">
            <div className="w-14 h-14 bg-violet-600/10 border border-violet-500/20 rounded-2xl flex items-center justify-center">
              <Activity className="w-6 h-6 text-violet-400" />
            </div>
            <div>
              <p className="text-slate-300 font-semibold">Ready to scan</p>
              <p className="text-slate-500 text-sm mt-1">
                Configure your threshold and click <strong className="text-violet-400">Run Scan</strong> to start.
                <br />
                <span className="text-xs">Use <strong className="text-violet-400">0% (All)</strong> to see all symbols regardless of deviation.</span>
              </p>
            </div>
            <button
              onClick={runScan}
              className="flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold rounded-xl transition-colors"
            >
              <Play className="w-4 h-4" />
              Start Scanning
            </button>
          </div>
        )}

        {/* Disclaimer */}
        <p className="text-[11px] text-slate-600 text-center">
          For educational and informational purposes only. Not financial advice.
          Max pain is a theoretical concept — actual price may not gravitate to it.
        </p>
      </div>

      {/* Stock detail drawer */}
      {selectedStock && (
        <StockDrawer
          stock={selectedStock}
          onClose={() => setSelectedStock(null)}
        />
      )}
    </div>
  )
}
