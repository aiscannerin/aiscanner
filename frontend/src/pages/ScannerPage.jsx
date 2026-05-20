import { useState, useCallback, useMemo, useEffect } from 'react'
import { useNavigate }                    from 'react-router-dom'
import { motion, AnimatePresence }        from 'framer-motion'
import { useShowToast }                   from '../context/ToastContext'
import { apiStartScan, apiGetResults, apiRecentScanRuns, apiScanRunResults, apiSymbolHistory } from '../api/scanner'
import { apiGetNotifications, apiMarkRead, apiMarkAllRead } from '../api/notifications'
import { apiGetWatchlist, apiAddToWatchlist, apiRemoveTracked, apiUpdateTracked } from '../api/watchlist'
import { apiGetAlertSettings, apiUpdateAlertSettings } from '../api/alertSettings'

// ─── constants ────────────────────────────────────────────────────────────────

const UNIVERSE_OPTIONS = [
  { value: 'NIFTY50',  label: 'Nifty 50' },
  { value: 'NIFTY100', label: 'Nifty 100' },
  { value: 'NIFTY500', label: 'Nifty 500' },
  { value: 'FNO',      label: 'NSE F&O Stocks' },
]
const TIMEFRAMES = ['15m', '1h', '4h', '1d']

const ACCESS_ERRORS = new Set([
  'TOOL_NOT_IN_PLAN', 'SUBSCRIPTION_REQUIRED',
  'SUBSCRIPTION_EXPIRED', 'TOOL_INACTIVE',
  'EMAIL_NOT_VERIFIED', 'ACCOUNT_INACTIVE',
])

const FILTER_CHIPS = [
  { id: 'all',       label: 'All Setups' },
  { id: 'confirmed', label: 'Confirmed' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'near_miss', label: 'Near Miss' },
  { id: 'ltf_full',  label: 'LTF Full' },
  { id: 'htf_only',  label: 'HTF Only' },
  { id: 'fresh',     label: 'Fresh ≤5b' },
  { id: 'aplus',     label: 'A+ Elite' },
  { id: 'a_above',   label: 'A & Above' },
  { id: 'b_plus',    label: 'B+ Tradable' },
  { id: 'bull',      label: 'Bull Only' },
  { id: 'bear',      label: 'Bear Only' },
  { id: 'hide_weak', label: 'Hide Weak <60' },
]

const SORT_OPTIONS = [
  { id: 'score_desc', label: 'Score ↓' },
  { id: 'score_asc',  label: 'Score ↑' },
  { id: 'age_asc',    label: 'Freshest' },
  { id: 'age_desc',   label: 'Oldest' },
]

const SCORE_MAX = {
  // v3 engine keys
  htf_sweep_quality:    20,
  displacement_strength: 15,
  fvg_quality:           10,
  choch_clarity:         15,
  ob_quality:            10,
  htf_retest:            10,
  ltf_confirmation:      15,
  rr_clarity:             5,
  // legacy v2 keys (kept for old results in DB)
  liquidity_quality: 15, sweep_quality: 20, close_back_quality: 15,
  choch_confirmation: 20, fvg_in_impulse: 20, retest_ob_context: 10,
}

// ─── design tokens ────────────────────────────────────────────────────────────

const T = {
  bg: '#050810', surface: '#10131c', surfaceAlt: '#0c0f1d', surface2: '#131829',
  border: 'rgba(255,255,255,0.07)', border2: 'rgba(255,255,255,0.12)',
  muted: '#8c90a1', muted2: '#5a5f72', text: '#e1e2ee',
  primary: '#0066ff', primaryDim: 'rgba(0,102,255,0.15)',
  cyan: '#00f1fe', cyanDim: 'rgba(0,241,254,0.12)',
  bullish: '#00d97e', bullishDim: 'rgba(0,217,126,0.12)',
  bearish: '#ff4d4f', bearishDim: 'rgba(255,77,79,0.12)',
  amber: '#f59e0b', amberDim: 'rgba(245,158,11,0.12)',
  purple: '#b3c5ff', purpleDim: 'rgba(179,197,255,0.1)',
  violet: '#a78bfa',
}

const CL_COLOR = {
  // v3
  confirmed:  T.bullish,
  watchlist:  T.cyan,
  near_miss:  T.amber,
  rejected:   T.bearish,
  // v2 legacy (DB compatibility)
  valid_setup:   T.bullish,
  partial_setup: T.cyan,
  no_setup:      T.muted,
}
const CL_LABEL = {
  // v3
  confirmed:  'Confirmed',
  watchlist:  'Watchlist',
  near_miss:  'Near Miss',
  rejected:   'Rejected',
  // v2 legacy
  valid_setup:   'Valid Setup',
  partial_setup: 'Watchlist',
  no_setup:      'No Setup',
}

// ─── helpers ──────────────────────────────────────────────────────────────────

const gradeColor = g => ({ 'A+': T.violet, A: T.bullish, B: T.cyan, C: T.amber, NM: T.muted }[g] ?? T.bearish)
const dirColor   = d => d === 'bullish' ? T.bullish : d === 'bearish' ? T.bearish : T.muted

function fmt(n) {
  if (n == null) return '—'
  return '₹ ' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtN(n, d = 2) { return n == null ? '—' : Number(n).toFixed(d) }

function getStage(row) {
  const rd = row?.result_data ?? {}
  const cl = rd.classification

  if (rd.stale) return { label: 'Stale', color: T.muted }

  // v3 classifications
  if (cl === 'confirmed') {
    if (rd.ltf_ob)    return { label: 'LTF OB 2.0 Ready',  color: T.bullish }
    if (rd.ltf_choch) return { label: 'LTF ChoCH Done',    color: T.bullish }
    if (rd.ltf_sweep) return { label: 'LTF Sweep Active',  color: T.cyan    }
    return                   { label: 'Confirmed',          color: T.bullish }
  }
  if (cl === 'watchlist') {
    if (rd.retest)        return { label: 'HTF OB Retesting', color: T.cyan    }
    if (rd.order_block)   return { label: 'OB 1.0 Active',    color: T.cyan    }
    if (rd.choch)         return { label: 'ChoCH — No OB',    color: T.amber   }
    return                       { label: 'Watchlist',         color: T.cyan    }
  }
  if (cl === 'near_miss') {
    if (rd.displacement && rd.choch) return { label: 'Disp + ChoCH — OB Pending', color: T.amber }
    if (rd.displacement && rd.fvg)   return { label: 'Disp + FVG — No ChoCH',    color: T.amber }
    if (rd.displacement)             return { label: 'Displacement — ChoCH Pending', color: T.amber }
    return                                  { label: 'Sweep Only — Incomplete',   color: T.amber }
  }

  // v2 legacy fallback
  if (cl === 'valid_setup') {
    if (rd.retest) return { label: 'Retesting', color: T.cyan }
    return               { label: 'Valid Setup', color: T.bullish }
  }
  if (rd.sweep && rd.choch && rd.fvg) return { label: 'Sweep+ChoCH+FVG', color: T.cyan }
  if (rd.sweep && rd.choch)           return { label: 'Sweep+ChoCH',      color: T.amber }
  if (rd.sweep)                       return { label: 'Sweep Only',        color: T.amber }
  return                                     { label: 'No Setup',           color: T.muted }
}

function tvUrl(symbol) {
  // Strip .NS suffix if present (NSE: prefix handles exchange)
  const clean = (symbol || '').replace(/\.NS$/i, '').toUpperCase()
  return `https://www.tradingview.com/chart/?symbol=NSE%3A${encodeURIComponent(clean)}`
}

function applyChip(rows, chip) {
  const cl = r => r.result_data?.classification
  switch (chip) {
    // v3 classification filters
    case 'confirmed':  return rows.filter(r => cl(r) === 'confirmed' || cl(r) === 'valid_setup')
    case 'watchlist':  return rows.filter(r => cl(r) === 'watchlist'  || cl(r) === 'partial_setup')
    case 'near_miss':  return rows.filter(r => cl(r) === 'near_miss')
    // LTF filters (v3)
    case 'ltf_full':   return rows.filter(r => r.result_data?.ltf_ob === true)
    case 'htf_only':   return rows.filter(r => r.result_data?.retest === true && !r.result_data?.ltf_ob)
    // Age
    case 'fresh':      return rows.filter(r => (r.result_data?.setup_age ?? 999) <= 5 && !r.result_data?.stale)
    // Grade
    case 'aplus':      return rows.filter(r => r.grade === 'A+')
    case 'a_above':    return rows.filter(r => ['A+', 'A'].includes(r.grade))
    case 'b_plus':     return rows.filter(r => ['A+', 'A', 'B+', 'B'].includes(r.grade))
    // Direction
    case 'bull':       return rows.filter(r => r.direction === 'bullish')
    case 'bear':       return rows.filter(r => r.direction === 'bearish')
    // Score gate
    case 'hide_weak':  return rows.filter(r => (r.score ?? 0) >= 60)
    default:           return rows
  }
}

function applySort(rows, sort) {
  const s = [...rows]
  if (sort === 'score_asc')  return s.sort((a, b) => (a.score ?? 0)   - (b.score ?? 0))
  if (sort === 'age_asc')    return s.sort((a, b) => (a.result_data?.setup_age ?? 999) - (b.result_data?.setup_age ?? 999))
  if (sort === 'age_desc')   return s.sort((a, b) => (b.result_data?.setup_age ?? 0)   - (a.result_data?.setup_age ?? 0))
  return                            s.sort((a, b) => (b.score ?? 0) - (a.score ?? 0))  // default: score_desc
}

function exportCSV(rows, showToast) {
  if (!rows.length) { showToast('No results to export.', 'info'); return }
  const headers = ['Symbol', 'Direction', 'Classification', 'Stage', 'Grade', 'Score',
                   'Entry', 'Stop Loss', 'Target 1', 'Target 2', 'Sweep', 'ChoCH', 'FVG', 'Retest', 'Age']
  const lines = rows.map(r => {
    const rd = r.result_data ?? {}
    return [
      r.symbol, r.direction, rd.classification, getStage(r).label,
      r.grade, r.score, rd.entry, rd.stop_loss, rd.target_1, rd.target_2,
      rd.sweep, rd.choch, rd.fvg, rd.retest, rd.setup_age
    ].join(',')
  })
  const csv  = [headers.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a'); a.href = url
  a.download = `sth_${Date.now()}.csv`; a.click()
  URL.revokeObjectURL(url)
  showToast('CSV exported.', 'success')
}

// ─── checklist steps ──────────────────────────────────────────────────────────

function buildChecklist(result) {
  const rd    = result?.result_data ?? {}
  const dbg   = rd.debug_trace        ?? {}
  const sweep = rd.sweep_detail        ?? {}
  const disp  = rd.displacement_detail ?? {}
  const choch = rd.choch_detail        ?? {}
  const fvg   = rd.fvg_detail          ?? {}
  const ob    = rd.ob_detail           ?? {}
  const ret   = rd.retest_detail       ?? {}
  const ltf   = rd.ltf_detail          ?? {}
  // Support both direct keys (v3) and unified alias (checklist.htf / checklist.ltf)
  const htfc  = rd.htf_checklist ?? rd.checklist?.htf ?? {}
  const ltfc  = rd.ltf_checklist ?? rd.checklist?.ltf ?? {}
  const score = result?.score
  const grade = result?.grade

  // ── HTF section ──────────────────────────────────────────────────────────────
  const htfSteps = [
    {
      label:  'Prior Liquidity Identified',
      status: htfc.liquidity_identified ? 'pass' : 'fail',
      detail: rd.liquidity_level != null
        ? `${(rd.liquidity_type ?? '').replace('_', ' ')} at ${fmtN(rd.liquidity_level)}`
        : 'No swing high/low with liquidity found',
    },
    {
      label:  'Liquidity Swept',
      status: htfc.sweep_confirmed ? 'pass' : 'fail',
      detail: rd.sweep
        ? `Bar ${sweep.sweep_idx ?? '—'} · wick ${fmtN(sweep.swept_wick)} pts · close-back ${fmtN(sweep.close_back_size)} pts`
        : 'No sweep detected in lookback window',
    },
    {
      label:  'Displacement After Sweep',
      status: htfc.displacement ? 'pass' : (rd.sweep ? 'fail' : 'info'),
      detail: disp.found
        ? `Bar ${disp.displacement_idx} · ${fmtN(disp.atr_ratio)}× ATR body`
        : 'No displacement candle found after sweep',
    },
    {
      label:    'Post-Sweep FVG Formed',
      status:   htfc.fvg_formed ? 'pass' : 'warn',
      optional: true,
      detail:   fvg.found
        ? `Zone ${fmtN(fvg.zone_low)}–${fmtN(fvg.zone_high)} · ${fmtN(fvg.gap_pct)}% gap · bar ${fvg.fvg_idx}`
        : `FVG not found in displacement impulse (bars ${dbg.fvg_search_start ?? '?'}→${dbg.fvg_idx ?? '?'})`,
    },
    {
      label:  'ChoCH / MSS Confirmed',
      status: htfc.choch_confirmed ? 'pass' : 'fail',
      detail: choch.confirmed
        ? `Bar ${choch.choch_idx} · ref: ${choch.reference_type} · ${choch.bars_after_sweep}b after sweep · break ${fmtN(choch.break_amount)} pts`
        : 'No structural break found after sweep within lookback',
    },
    {
      label:  'HTF OB 1.0 Activated',
      status: htfc.ob_activated ? 'pass' : (htfc.choch_confirmed ? 'fail' : 'info'),
      detail: ob.found
        ? `${ob.ob_type ?? '—'} · zone ${fmtN(ob.zone_low)}–${fmtN(ob.zone_high)} · bar ${ob.ob_idx}`
        : 'Order block not found before displacement impulse',
    },
    {
      label:    'HTF OB 1.0 Retest',
      status:   htfc.ob_retest ? 'pass' : (htfc.ob_activated ? 'warn' : 'info'),
      optional: true,
      detail:   ret.retested
        ? `Retest confirmed at bar ${ret.retest_idx} (${(ret.zone_type ?? '').toUpperCase()})`
        : htfc.ob_activated
          ? `OB active — waiting for price to re-enter zone ${fmtN(ob.zone_low)}–${fmtN(ob.zone_high)}`
          : 'OB must be activated before retest',
    },
  ]

  // ── LTF section ──────────────────────────────────────────────────────────────
  const ltfAvailable = ltf.ltf_available
  const ltfSweep     = ltf.ltf_sweep_detail  ?? {}
  const ltfChoch     = ltf.ltf_choch_detail  ?? {}
  const ltfOb        = ltf.ltf_ob_detail     ?? {}

  const ltfSteps = [
    {
      label:  'LTF Sweep (After HTF Retest)',
      status: ltfc.ltf_sweep ? 'pass' : (ltfAvailable ? 'fail' : 'info'),
      detail: ltfAvailable
        ? (ltfc.ltf_sweep
            ? `Bar ${ltfSweep.sweep_idx ?? '—'} · ${ltfSweep.direction ?? '—'} sweep · ${fmtN(ltfSweep.swept_wick)} pts`
            : 'No LTF sweep found in same direction as HTF')
        : 'LTF data not available (15m HTF has no lower timeframe)',
    },
    {
      label:  'LTF ChoCH / MSS',
      status: ltfc.ltf_choch ? 'pass' : (ltfc.ltf_sweep ? 'fail' : 'info'),
      detail: ltfc.ltf_choch
        ? `ChoCH bar ${ltfChoch.choch_idx ?? '—'} · ${ltfChoch.bars_after_sweep ?? '—'}b after LTF sweep`
        : 'LTF ChoCH not confirmed',
    },
    {
      label:  'LTF OB 2.0 Formed',
      status: ltfc.ltf_ob_formed ? 'pass' : (ltfc.ltf_choch ? 'fail' : 'info'),
      detail: ltfc.ltf_ob_formed
        ? `OB ${fmtN(ltfOb.zone_low)}–${fmtN(ltfOb.zone_high)} · bar ${ltfOb.ob_idx ?? '—'}`
        : 'LTF OB 2.0 not found',
    },
    {
      label:  'Entry Ready',
      status: ltfc.entry_ready ? 'pass' : 'info',
      detail: ltfc.entry_ready
        ? `Full sequence confirmed — entry zone from LTF OB 2.0`
        : `Classification: ${rd.classification ?? '—'} — sequence not fully confirmed`,
    },
  ]

  // ── Score + grade summary step (appended at bottom) ──
  const summaryStep = {
    label:  'Score & Classification',
    status: ['confirmed', 'watchlist', 'valid_setup'].includes(rd.classification) ? 'pass' : 'warn',
    detail: `${score?.toFixed(1) ?? '—'}/100 · Grade ${grade ?? '—'} · ${CL_LABEL[rd.classification] ?? rd.classification ?? '—'}`,
  }

  return { htfSteps, ltfSteps, summaryStep }
}


// ─── small shared components ──────────────────────────────────────────────────

function ClassificationBadge({ value, small }) {
  if (!value) return null
  const color = CL_COLOR[value] ?? T.muted
  const label = CL_LABEL[value] ?? value
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      padding: small ? '2px 7px' : '3px 9px',
      borderRadius: '20px',
      background: `${color}18`, border: `1px solid ${color}38`,
      color, fontSize: small ? '10px' : '11px', fontWeight: 700, whiteSpace: 'nowrap',
    }}>
      <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: color, flexShrink: 0 }} />
      {label}
    </span>
  )
}

function StaleBadge({ small }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '3px',
      padding: small ? '1px 6px' : '2px 7px', borderRadius: '20px',
      background: T.amberDim, border: '1px solid rgba(245,158,11,0.3)',
      color: T.amber, fontSize: '9px', fontWeight: 700, letterSpacing: '0.05em',
    }}>⚠ STALE</span>
  )
}

function NSEBadge() {
  return (
    <span style={{
      fontSize: '9px', fontWeight: 700, padding: '1px 5px', borderRadius: '4px',
      background: 'rgba(0,102,255,0.15)', color: T.primary, letterSpacing: '0.05em',
    }}>NSE</span>
  )
}

function CheckMark({ val, trueColor = T.bullish }) {
  return val
    ? <span style={{ color: trueColor, fontWeight: 700, fontSize: '13px' }}>✓</span>
    : <span style={{ color: T.muted2, fontSize: '12px' }}>—</span>
}

function StatusBadge({ status }) {
  const map = {
    completed: { bg: T.bullishDim, color: T.bullish },
    running:   { bg: T.cyanDim,    color: T.cyan    },
    failed:    { bg: T.bearishDim, color: T.bearish },
    queued:    { bg: T.purpleDim,  color: T.purple  },
  }
  const c = map[status] ?? map.queued
  return (
    <span style={{ display:'inline-flex', alignItems:'center', gap:'5px', padding:'3px 10px', borderRadius:'20px', background:c.bg, color:c.color, fontSize:'11px', fontWeight:600 }}>
      <span style={{ width:'6px', height:'6px', borderRadius:'50%', background:c.color }} />
      {status}
    </span>
  )
}

function Skeleton({ h = '18px' }) {
  return <div style={{ height:h, borderRadius:'6px', background:'linear-gradient(90deg,rgba(255,255,255,0.04) 25%,rgba(255,255,255,0.08) 50%,rgba(255,255,255,0.04) 75%)', backgroundSize:'200% 100%', animation:'shimmer 1.5s infinite' }} />
}

// ─── scan health bar ──────────────────────────────────────────────────────────

const DQ_CONFIG = {
  good:    { color: '#00d97e', bg: 'rgba(0,217,126,0.10)', border: 'rgba(0,217,126,0.25)', label: 'Good'    },
  partial: { color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', border: 'rgba(245,158,11,0.28)', label: 'Partial' },
  poor:    { color: '#ff4d4f', bg: 'rgba(255,77,79,0.10)',   border: 'rgba(255,77,79,0.28)',   label: 'Poor'    },
}

const MS_ICON = { open: '🟢', closed: '🔴', preopen: '🟡', weekend: '⛔' }

function DataQualityBadge({ quality, small }) {
  if (!quality) return null
  const cfg = DQ_CONFIG[quality] ?? DQ_CONFIG.good
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      padding: small ? '1px 7px' : '2px 9px', borderRadius: '20px',
      background: cfg.bg, border: `1px solid ${cfg.border}`,
      color: cfg.color, fontSize: small ? '9px' : '10px', fontWeight: 700,
      letterSpacing: '0.04em', whiteSpace: 'nowrap',
    }}>
      <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: cfg.color, flexShrink: 0 }} />
      {cfg.label}
    </span>
  )
}

function ScanHealthBar({ health }) {
  const [showWarnings, setShowWarnings] = useState(false)
  if (!health) return null

  const {
    symbols_requested = 0, symbols_scanned = 0, symbols_failed = 0,
    partial_scan = false, cache_hits = 0, cache_misses = 0, cache_hit_rate = 0,
    fetch_time_s = 0, market_state, data_quality = 'good', warnings = [],
  } = health

  const hitPct   = Math.round(cache_hit_rate * 100)
  const msIcon   = MS_ICON[market_state] ?? '●'
  const isPoor   = data_quality === 'poor'
  const isPartial = partial_scan && data_quality !== 'poor'

  return (
    <div style={{ marginBottom: '10px' }}>
      {/* ── main health strip ── */}
      <div style={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '14px',
        padding: '8px 14px', borderRadius: '9px',
        background: T.surface, border: `1px solid ${T.border}`,
        fontSize: '11px',
      }}>
        {/* data quality badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ fontSize: '9px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: T.muted2 }}>Data Quality</span>
          <DataQualityBadge quality={data_quality} small />
        </div>

        <div style={{ width: '1px', height: '14px', background: T.border, flexShrink: 0 }} />

        {/* symbols */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ color: T.muted }}>Symbols</span>
          <span style={{ fontWeight: 700, color: T.text }}>{symbols_scanned}/{symbols_requested}</span>
          {symbols_failed > 0 && (
            <span style={{ fontSize: '10px', fontWeight: 700, padding: '1px 6px', borderRadius: '10px', background: 'rgba(255,77,79,0.12)', color: '#ff4d4f' }}>
              {symbols_failed} failed
            </span>
          )}
        </div>

        <div style={{ width: '1px', height: '14px', background: T.border, flexShrink: 0 }} />

        {/* cache hit rate */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ color: T.muted }}>Cache</span>
          <span style={{ fontWeight: 700, color: hitPct >= 80 ? T.bullish : hitPct >= 50 ? T.cyan : T.amber }}>
            {hitPct}%
          </span>
          <span style={{ color: T.muted2 }}>({cache_hits}H / {cache_misses}M)</span>
        </div>

        <div style={{ width: '1px', height: '14px', background: T.border, flexShrink: 0 }} />

        {/* fetch time */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ color: T.muted }}>Fetch</span>
          <span style={{ fontWeight: 700, color: fetch_time_s > 10 ? T.amber : T.text }}>{Number(fetch_time_s).toFixed(1)}s</span>
        </div>

        <div style={{ width: '1px', height: '14px', background: T.border, flexShrink: 0 }} />

        {/* market state */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ color: T.muted }}>Market</span>
          <span style={{ fontWeight: 600, color: T.text }}>{msIcon} {market_state ?? '—'}</span>
        </div>

        {/* warnings toggle */}
        {warnings.length > 0 && (
          <>
            <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
              <button
                onClick={() => setShowWarnings(v => !v)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                  padding: '2px 8px', borderRadius: '6px', border: `1px solid ${T.amberDim}`,
                  background: 'transparent', color: T.amber, fontSize: '10px', fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                ⚠ {warnings.length} warning{warnings.length !== 1 ? 's' : ''}
                <span style={{ fontSize: '9px' }}>{showWarnings ? '▲' : '▼'}</span>
              </button>
            </div>
          </>
        )}
      </div>

      {/* ── warnings list ── */}
      {showWarnings && warnings.length > 0 && (
        <div style={{
          marginTop: '4px', padding: '8px 12px', borderRadius: '8px',
          background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.2)',
          display: 'flex', flexDirection: 'column', gap: '3px',
        }}>
          {warnings.map((w, i) => (
            <div key={i} style={{ fontSize: '11px', color: T.amber, display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
              <span style={{ color: T.amber, flexShrink: 0, marginTop: '1px' }}>·</span>
              <span style={{ color: T.muted, lineHeight: 1.5 }}>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── partial scan amber banner ── */}
      {isPartial && (
        <div style={{
          marginTop: '4px', padding: '8px 14px', borderRadius: '8px',
          background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)',
          fontSize: '12px', color: T.amber, display: 'flex', alignItems: 'center', gap: '8px',
        }}>
          ⚠ Some symbols failed during fetch. Results may be incomplete.
        </div>
      )}

      {/* ── poor quality red banner ── */}
      {isPoor && (
        <div style={{
          marginTop: '4px', padding: '8px 14px', borderRadius: '8px',
          background: 'rgba(255,77,79,0.08)', border: '1px solid rgba(255,77,79,0.25)',
          fontSize: '12px', color: T.bearish, display: 'flex', alignItems: 'center', gap: '8px',
        }}>
          ✕ Significant data fetch failures — scan results may be severely incomplete. Consider re-scanning.
        </div>
      )}
    </div>
  )
}

function InfoBox({ children, color = T.muted }) {
  return (
    <div style={{ fontSize:'12px', color, padding:'8px 11px', background:`${color}10`, border:`1px solid ${color}28`, borderRadius:'8px', lineHeight:1.6, marginTop:'4px' }}>
      {children}
    </div>
  )
}

function ScoreBar({ label, value, max = 20 }) {
  const pct   = Math.min(100, ((value ?? 0) / max) * 100)
  const color = pct >= 70 ? T.bullish : pct >= 40 ? T.cyan : T.amber
  return (
    <div style={{ marginBottom:'6px' }}>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:'3px' }}>
        <span style={{ fontSize:'11px', color:T.muted, textTransform:'capitalize' }}>{label.replace(/_/g,' ')}</span>
        <span style={{ fontSize:'11px', fontWeight:700, color }}>{fmtN(value,1)} / {max}</span>
      </div>
      <div style={{ height:'3px', borderRadius:'2px', background:'rgba(255,255,255,0.07)' }}>
        <div style={{ width:`${pct}%`, height:'100%', background:color, borderRadius:'2px' }} />
      </div>
    </div>
  )
}

// ─── drawer primitives ────────────────────────────────────────────────────────

function DSection({ title, accent, children, collapsible = false }) {
  const [open, setOpen] = useState(true)
  const col = accent ?? T.muted
  return (
    <div style={{ marginBottom:'20px' }}>
      <div
        onClick={collapsible ? () => setOpen(o => !o) : undefined}
        style={{
          fontSize:'10px', fontWeight:700, letterSpacing:'0.1em', textTransform:'uppercase',
          color:col, marginBottom:open ? '10px' : 0, paddingBottom:'7px',
          borderBottom:`1px solid ${col}28`,
          display:'flex', alignItems:'center', justifyContent:'space-between',
          cursor: collapsible ? 'pointer' : 'default',
        }}
      >
        <span>{title}</span>
        {collapsible && <span style={{ fontSize:'12px' }}>{open ? '▲' : '▼'}</span>}
      </div>
      {open && children}
    </div>
  )
}

function DRow({ label, value, color, mono }) {
  return (
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'4px 0', gap:'8px' }}>
      <span style={{ fontSize:'12px', color:T.muted, flexShrink:0, textTransform:'capitalize' }}>{label}</span>
      <span style={{ fontSize:'12px', fontWeight:600, color:color??T.text, textAlign:'right', fontFamily:mono?"'Space Mono',monospace":'inherit' }}>{value??'—'}</span>
    </div>
  )
}

function DBlock({ label, value, valueColor }) {
  return (
    <div style={{ flex:1, background:T.surface, border:`1px solid ${T.border}`, borderRadius:'10px', padding:'11px 12px', textAlign:'center', minWidth:0 }}>
      <div style={{ fontSize:'9px', color:T.muted, textTransform:'uppercase', letterSpacing:'0.07em', marginBottom:'4px' }}>{label}</div>
      <div style={{ fontSize:'16px', fontWeight:700, color:valueColor??T.text, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{value}</div>
    </div>
  )
}

// ─── strategy checklist ───────────────────────────────────────────────────────

const CL_STATUS_STYLE = {
  pass: { icon:'✓', color:T.bullish, bg:T.bullishDim },
  warn: { icon:'⚠', color:T.amber,   bg:T.amberDim   },
  fail: { icon:'✗', color:T.bearish, bg:T.bearishDim },
  info: { icon:'○', color:T.muted,   bg:'rgba(255,255,255,0.04)' },
}

function ChecklistRow({ step, idx }) {
  const st = CL_STATUS_STYLE[step.status] ?? CL_STATUS_STYLE.info
  return (
    <div style={{ display:'flex', gap:'10px', alignItems:'flex-start', padding:'7px 0', borderBottom:`1px solid ${T.border}` }}>
      <div style={{ width:'22px', height:'22px', borderRadius:'50%', background:st.bg, border:`1px solid ${st.color}40`, display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0, marginTop:'1px' }}>
        <span style={{ fontSize:'11px', color:st.color, fontWeight:700 }}>{st.icon}</span>
      </div>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'center', gap:'6px', marginBottom:'2px' }}>
          <span style={{ fontSize:'9px', color:T.muted2, fontWeight:600 }}>{idx + 1}</span>
          <span style={{ fontSize:'12px', fontWeight:700, color:st.color }}>{step.label}</span>
          {step.optional && <span style={{ fontSize:'9px', color:T.muted2, padding:'1px 5px', borderRadius:'4px', background:'rgba(255,255,255,0.05)' }}>optional</span>}
        </div>
        <div style={{ fontSize:'11px', color:T.muted, lineHeight:1.5 }}>{step.detail}</div>
      </div>
    </div>
  )
}

// ─── notifications panel ──────────────────────────────────────────────────────

const NOTIF_TYPE_ICON = {
  became_confirmed: '🎯',
  improved_level:   '📈',
  became_watchlist: '👁',
}
const NOTIF_TYPE_COLOR = {
  became_confirmed: '#00D97E',
  improved_level:   '#00F1FE',
  became_watchlist: '#B3C5FF',
}

function NotificationsPanel({ notifications, unreadCount, onMarkRead, onMarkAllRead, onClose }) {
  const sorted = [...notifications].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

  return (
    <>
      {/* backdrop */}
      <div onClick={onClose} style={{ position:'fixed', inset:0, zIndex:70 }} />

      {/* panel */}
      <div style={{
        position:'fixed', top:'58px', right:'16px', zIndex:71,
        width:'min(380px, calc(100vw - 32px))',
        background:'#0c0f1d', border:'1px solid rgba(255,255,255,0.12)',
        borderRadius:'14px', boxShadow:'0 20px 60px rgba(0,0,0,0.6)',
        overflow:'hidden', fontFamily:'Inter,ui-sans-serif,sans-serif',
      }}>
        {/* header */}
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'13px 16px', borderBottom:'1px solid rgba(255,255,255,0.07)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
            <span style={{ fontSize:'13px', fontWeight:700, color:'#e1e2ee' }}>Notifications</span>
            {unreadCount > 0 && (
              <span style={{ fontSize:'10px', fontWeight:700, padding:'1px 7px', borderRadius:'10px', background:'rgba(0,102,255,0.25)', color:'#6fa3ff' }}>
                {unreadCount} new
              </span>
            )}
          </div>
          <div style={{ display:'flex', gap:'8px', alignItems:'center' }}>
            {unreadCount > 0 && (
              <button onClick={onMarkAllRead} style={{ fontSize:'10px', fontWeight:600, color:'#8c90a1', background:'none', border:'none', cursor:'pointer', padding:'2px 6px' }}>
                Mark all read
              </button>
            )}
            <button onClick={onClose} style={{ fontSize:'16px', color:'#5a5f72', background:'none', border:'none', cursor:'pointer', lineHeight:1 }}>×</button>
          </div>
        </div>

        {/* list */}
        <div style={{ maxHeight:'420px', overflowY:'auto' }}>
          {sorted.length === 0 ? (
            <div style={{ padding:'32px', textAlign:'center', color:'#5a5f72', fontSize:'12px' }}>
              No notifications yet.<br />Run a scan to see setup progressions.
            </div>
          ) : (
            sorted.map(n => {
              const col   = NOTIF_TYPE_COLOR[n.notification_type] ?? '#8c90a1'
              const icon  = NOTIF_TYPE_ICON[n.notification_type]  ?? '●'
              const dt    = new Date(n.created_at).toLocaleString('en-IN', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit' })
              return (
                <div
                  key={n.id}
                  onClick={() => !n.is_read && onMarkRead(n.id)}
                  style={{
                    padding:'11px 16px', borderBottom:'1px solid rgba(255,255,255,0.04)',
                    background: n.is_read ? 'transparent' : 'rgba(0,102,255,0.04)',
                    cursor: n.is_read ? 'default' : 'pointer',
                    transition:'background 0.15s',
                  }}
                >
                  <div style={{ display:'flex', alignItems:'flex-start', gap:'10px' }}>
                    {/* icon + unread dot */}
                    <div style={{ position:'relative', flexShrink:0, marginTop:'1px' }}>
                      <span style={{ fontSize:'16px' }}>{icon}</span>
                      {!n.is_read && (
                        <span style={{ position:'absolute', top:'-2px', right:'-3px', width:'6px', height:'6px', borderRadius:'50%', background:'#0066ff', border:'1px solid #0c0f1d' }} />
                      )}
                    </div>

                    <div style={{ flex:1, minWidth:0 }}>
                      {/* title + time */}
                      <div style={{ display:'flex', justifyContent:'space-between', gap:'6px', marginBottom:'3px' }}>
                        <span style={{ fontSize:'12px', fontWeight:700, color: n.is_read ? '#8c90a1' : col, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                          {n.title}
                        </span>
                        <span style={{ fontSize:'9px', color:'#5a5f72', whiteSpace:'nowrap', flexShrink:0, marginTop:'2px' }}>{dt}</span>
                      </div>
                      {/* message */}
                      <div style={{ fontSize:'11px', color: n.is_read ? '#5a5f72' : '#8c90a1', lineHeight:1.55 }}>
                        {n.message}
                      </div>
                      {/* type pill + scope badge */}
                      <div style={{ marginTop:'4px', display:'flex', gap:'5px', alignItems:'center' }}>
                        <span style={{ fontSize:'9px', fontWeight:600, padding:'1px 5px', borderRadius:'5px', background:`${col}15`, color:col }}>
                          {n.notification_type.replace(/_/g, ' ')} · p{n.priority}
                        </span>
                        {n.notification_scope === 'tracked' && (
                          <span style={{ fontSize:'9px', fontWeight:700, padding:'1px 5px', borderRadius:'5px', background:'rgba(0,241,254,0.1)', color:'#00f1fe' }}>
                            📋 tracked
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </>
  )
}

// ─── watchlist panel ─────────────────────────────────────────────────────────

const WL_CL_COLOR = {
  confirmed: '#00d97e', watchlist: '#00f1fe', near_miss: '#f59e0b',
  valid_setup: '#00d97e', partial_setup: '#00f1fe',
}

// Alert toggle definitions — label, pref key, active color
const ALERT_TOGGLES = [
  { key: 'alert_became_confirmed', label: 'Confirmed', color: '#00d97e' },
  { key: 'alert_improved_level',   label: 'Level ↑',  color: '#00f1fe' },
  { key: 'alert_became_watchlist', label: 'Watchlist', color: '#b3c5ff' },
  { key: 'alert_degraded',         label: 'Degraded',  color: '#f59e0b' },
]

function WatchlistPanel({ watchlist, onRemove, onUpdateNote, onUpdateAlertPref,
                          alertSettings, onSaveAlertSettings, onClose }) {
  const [editingId,   setEditingId]   = useState(null)
  const [noteInput,   setNoteInput]   = useState('')
  const [savingId,    setSavingId]    = useState(null)
  const [removingId,  setRemovingId]  = useState(null)
  const [togglingId,  setTogglingId]  = useState(null)

  // Email settings local state (mirrors alertSettings prop)
  const [emailEnabled, setEmailEnabled] = useState(alertSettings?.email_alerts_enabled ?? false)
  const [emailAddr,    setEmailAddr]    = useState(alertSettings?.email_address ?? '')
  const [emailSaving,  setEmailSaving]  = useState(false)
  const [emailDirty,   setEmailDirty]   = useState(false)

  // Sync when prop changes (on first load)
  useEffect(() => {
    if (alertSettings) {
      setEmailEnabled(alertSettings.email_alerts_enabled)
      setEmailAddr(alertSettings.email_address ?? '')
      setEmailDirty(false)
    }
  }, [alertSettings])

  function startEdit(entry) {
    setEditingId(entry.id)
    setNoteInput(entry.note ?? '')
  }

  async function saveNote(entry) {
    setSavingId(entry.id)
    await onUpdateNote(entry.id, noteInput || null)
    setSavingId(null)
    setEditingId(null)
  }

  async function remove(entry) {
    setRemovingId(entry.id)
    await onRemove(entry.id)
    setRemovingId(null)
  }

  async function togglePref(entry, key, currentVal) {
    setTogglingId(entry.id + key)
    await onUpdateAlertPref(entry.id, { [key]: !currentVal })
    setTogglingId(null)
  }

  async function saveEmailSettings() {
    setEmailSaving(true)
    const ok = await onSaveAlertSettings({
      email_alerts_enabled: emailEnabled,
      email_address:        emailAddr.trim() || null,
    })
    setEmailSaving(false)
    if (ok) setEmailDirty(false)
  }

  return (
    <>
      {/* backdrop */}
      <div onClick={onClose} style={{ position:'fixed', inset:0, zIndex:70 }} />

      {/* panel */}
      <div style={{
        position:'fixed', top:'58px', right:'16px', zIndex:71,
        width:'min(580px, calc(100vw - 32px))',
        background:'#0c0f1d', border:'1px solid rgba(255,255,255,0.12)',
        borderRadius:'14px', boxShadow:'0 20px 60px rgba(0,0,0,0.6)',
        overflow:'hidden', fontFamily:'Inter,ui-sans-serif,sans-serif',
      }}>
        {/* header */}
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'13px 16px', borderBottom:'1px solid rgba(255,255,255,0.07)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
            <span style={{ fontSize:'13px', fontWeight:700, color:'#e1e2ee' }}>Watchlist</span>
            <span style={{ fontSize:'10px', fontWeight:700, padding:'1px 7px', borderRadius:'10px', background:'rgba(0,241,254,0.1)', color:'#00f1fe' }}>
              {watchlist.length} tracked
            </span>
          </div>
          <button onClick={onClose} style={{ fontSize:'16px', color:'#5a5f72', background:'none', border:'none', cursor:'pointer', lineHeight:1 }}>×</button>
        </div>

        {/* list */}
        <div style={{ maxHeight:'560px', overflowY:'auto' }}>
          {watchlist.length === 0 ? (
            <div style={{ padding:'40px', textAlign:'center', color:'#5a5f72', fontSize:'12px', lineHeight:1.8 }}>
              No symbols tracked yet.<br />
              Open any result and click <strong style={{ color:'#8c90a1' }}>Track Symbol</strong> to add it.
            </div>
          ) : (
            watchlist.map(entry => {
              const lat     = entry.latest
              const prefs   = entry.alert_prefs ?? {}
              const clColor = WL_CL_COLOR[lat?.classification] ?? '#5a5f72'
              const prio    = lat?.progression_priority
              const progCol = prio >= 100 ? '#00d97e' : prio >= 70 ? '#00f1fe' : prio >= 60 ? '#b3c5ff' : '#5a5f72'
              const isEdit  = editingId === entry.id
              const isRemov = removingId === entry.id

              return (
                <div key={entry.id} style={{
                  padding:'12px 16px', borderBottom:'1px solid rgba(255,255,255,0.04)',
                  opacity: isRemov ? 0.5 : 1, transition:'opacity 0.2s',
                }}>
                  {/* Row 1: symbol + meta + remove */}
                  <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', gap:'8px', marginBottom:'6px' }}>
                    <div style={{ display:'flex', alignItems:'center', gap:'8px', minWidth:0 }}>
                      <span style={{ fontSize:'14px', fontWeight:800, color:'#e1e2ee' }}>{entry.symbol}</span>
                      <span style={{ fontSize:'9px', fontWeight:600, padding:'1px 5px', borderRadius:'4px', background:'rgba(0,102,255,0.12)', color:'#6fa3ff' }}>{entry.htf}{entry.ltf ? `/${entry.ltf}` : ''}</span>
                      <span style={{ fontSize:'9px', color:'#5a5f72' }}>{entry.scanner_name}</span>
                    </div>
                    <button
                      onClick={() => remove(entry)}
                      disabled={isRemov}
                      style={{ fontSize:'10px', fontWeight:600, padding:'3px 9px', borderRadius:'6px', background:'rgba(255,77,79,0.08)', border:'1px solid rgba(255,77,79,0.18)', color:'#ff4d4f', cursor:'pointer', whiteSpace:'nowrap', flexShrink:0 }}>
                      {isRemov ? '…' : '✕ Remove'}
                    </button>
                  </div>

                  {/* Row 2: latest scan state */}
                  {lat ? (
                    <div style={{ display:'flex', alignItems:'center', gap:'10px', flexWrap:'wrap', marginBottom:'8px' }}>
                      <span style={{ fontSize:'10px', fontWeight:700, padding:'2px 8px', borderRadius:'20px', background:`${clColor}14`, border:`1px solid ${clColor}30`, color:clColor }}>
                        {lat.classification ?? '—'}
                      </span>
                      {lat.watchlist_level && (
                        <span style={{ fontSize:'10px', fontWeight:700, color:'#00f1fe' }}>{lat.watchlist_level}</span>
                      )}
                      <span style={{ fontSize:'12px', fontWeight:700, color:'#b3c5ff' }}>
                        {lat.score != null ? lat.score.toFixed(1) : '—'}
                      </span>
                      {lat.grade && (
                        <span style={{ fontSize:'10px', fontWeight:800, padding:'1px 6px', borderRadius:'5px', background:'rgba(179,197,255,0.1)', color:'#b3c5ff' }}>{lat.grade}</span>
                      )}
                      {lat.progression_label && lat.progression_type !== 'unchanged' && (
                        <span style={{ fontSize:'9px', fontWeight:700, color:progCol }}>
                          {(prio ?? 0) > 0 ? '▲' : '▼'} {lat.progression_label}
                        </span>
                      )}
                      <span style={{ fontSize:'10px', color:'#5a5f72', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:'160px' }} title={lat.current_stage_label}>
                        {lat.current_stage_label ?? '—'}
                      </span>
                    </div>
                  ) : (
                    <div style={{ fontSize:'10px', color:'#5a5f72', marginBottom:'8px' }}>No scan data yet.</div>
                  )}

                  {/* Row 3: alert toggles */}
                  <div style={{ display:'flex', alignItems:'center', gap:'5px', marginBottom:'8px', flexWrap:'wrap' }}>
                    <span style={{ fontSize:'9px', color:'#3a3f52', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.07em', marginRight:'2px' }}>Alerts</span>
                    {ALERT_TOGGLES.map(tog => {
                      const active  = prefs[tog.key] ?? false
                      const loading = togglingId === entry.id + tog.key
                      return (
                        <button
                          key={tog.key}
                          onClick={() => togglePref(entry, tog.key, active)}
                          disabled={loading}
                          title={`${active ? 'Disable' : 'Enable'} ${tog.label} alert`}
                          style={{
                            fontSize:'9px', fontWeight:700, padding:'2px 8px', borderRadius:'20px', cursor:'pointer',
                            border: `1px solid ${active ? tog.color + '50' : 'rgba(255,255,255,0.08)'}`,
                            background: active ? `${tog.color}14` : 'rgba(255,255,255,0.03)',
                            color: active ? tog.color : '#3a3f52',
                            transition:'all 0.15s', opacity: loading ? 0.5 : 1,
                          }}>
                          {loading ? '…' : (active ? '● ' : '○ ')}{tog.label}
                        </button>
                      )
                    })}
                  </div>

                  {/* Row 4: note */}
                  {isEdit ? (
                    <div style={{ display:'flex', gap:'6px', alignItems:'center' }}>
                      <input
                        autoFocus
                        value={noteInput}
                        onChange={e => setNoteInput(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') saveNote(entry); if (e.key === 'Escape') setEditingId(null) }}
                        placeholder="Add a note…"
                        style={{ flex:1, background:'rgba(255,255,255,0.05)', border:'1px solid rgba(255,255,255,0.12)', borderRadius:'7px', padding:'5px 10px', color:'#e1e2ee', fontSize:'11px', outline:'none' }}
                      />
                      <button onClick={() => saveNote(entry)} disabled={savingId === entry.id} style={{ fontSize:'10px', fontWeight:700, padding:'5px 11px', borderRadius:'7px', background:'rgba(0,102,255,0.2)', border:'1px solid rgba(0,102,255,0.3)', color:'#6fa3ff', cursor:'pointer' }}>
                        {savingId === entry.id ? '…' : 'Save'}
                      </button>
                      <button onClick={() => setEditingId(null)} style={{ fontSize:'10px', fontWeight:600, padding:'5px 9px', borderRadius:'7px', background:'rgba(255,255,255,0.05)', border:'1px solid rgba(255,255,255,0.08)', color:'#5a5f72', cursor:'pointer' }}>
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
                      <span style={{ fontSize:'10px', color: entry.note ? '#8c90a1' : '#3a3f52', fontStyle: entry.note ? 'normal' : 'italic', flex:1 }}>
                        {entry.note || 'No note'}
                      </span>
                      <button onClick={() => startEdit(entry)} style={{ fontSize:'9px', fontWeight:600, padding:'2px 8px', borderRadius:'5px', background:'rgba(255,255,255,0.04)', border:'1px solid rgba(255,255,255,0.06)', color:'#5a5f72', cursor:'pointer', whiteSpace:'nowrap' }}>
                        ✏ Edit note
                      </button>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>

        {/* ── Email Alerts settings footer ── */}
        <div style={{ borderTop:'1px solid rgba(255,255,255,0.07)', padding:'14px 16px', background:'rgba(255,255,255,0.015)' }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'10px' }}>
            <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
              <span style={{ fontSize:'11px', fontWeight:700, color:'#8c90a1' }}>📧 Email Alerts</span>
              <span style={{ fontSize:'9px', color:'#3a3f52', fontStyle:'italic' }}>tracked symbols only</span>
            </div>
            {/* Toggle */}
            <button
              onClick={() => { setEmailEnabled(v => !v); setEmailDirty(true) }}
              style={{
                display:'flex', alignItems:'center', gap:'7px', padding:'4px 10px',
                background: emailEnabled ? 'rgba(0,217,126,0.1)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${emailEnabled ? 'rgba(0,217,126,0.3)' : 'rgba(255,255,255,0.08)'}`,
                borderRadius:'7px', cursor:'pointer', color: emailEnabled ? '#00d97e' : '#5a5f72',
                fontSize:'11px', fontWeight:700, transition:'all 0.15s',
              }}>
              <span style={{ width:'26px', height:'14px', borderRadius:'7px', background: emailEnabled ? '#00d97e' : 'rgba(255,255,255,0.1)', position:'relative', display:'inline-block', flexShrink:0 }}>
                <span style={{ position:'absolute', top:'2px', left: emailEnabled ? '14px' : '2px', width:'10px', height:'10px', borderRadius:'50%', background:'#fff', transition:'left 0.15s' }} />
              </span>
              {emailEnabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>

          {emailEnabled && (
            <div style={{ display:'flex', gap:'7px', alignItems:'center' }}>
              <input
                type="email"
                placeholder="your@email.com"
                value={emailAddr}
                onChange={e => { setEmailAddr(e.target.value); setEmailDirty(true) }}
                onKeyDown={e => { if (e.key === 'Enter' && emailDirty) saveEmailSettings() }}
                style={{
                  flex:1, background:'rgba(255,255,255,0.05)', border:'1px solid rgba(255,255,255,0.1)',
                  borderRadius:'7px', padding:'6px 11px', color:'#e1e2ee', fontSize:'12px', outline:'none',
                  fontFamily:'inherit',
                }}
              />
              <button
                onClick={saveEmailSettings}
                disabled={emailSaving || !emailDirty}
                style={{
                  padding:'6px 14px', borderRadius:'7px', fontSize:'11px', fontWeight:700, cursor: (!emailDirty || emailSaving) ? 'not-allowed' : 'pointer',
                  background: emailDirty ? 'rgba(0,102,255,0.2)' : 'rgba(255,255,255,0.03)',
                  border: `1px solid ${emailDirty ? 'rgba(0,102,255,0.35)' : 'rgba(255,255,255,0.06)'}`,
                  color: emailDirty ? '#6fa3ff' : '#3a3f52',
                  transition:'all 0.15s', whiteSpace:'nowrap',
                }}>
                {emailSaving ? '…' : 'Save'}
              </button>
            </div>
          )}

          {!emailEnabled && (
            <div style={{ fontSize:'10px', color:'#3a3f52', lineHeight:1.7 }}>
              When enabled, you'll receive an email for each tracked-symbol alert<br />(Confirmed, Level ↑, Watchlist — based on your per-symbol toggles above).
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ─── symbol history section ───────────────────────────────────────────────────

const PROGRESSION_MAP = [
  // [prevCl, currCl] → label, color
  // curr is newer (index 0), prev is one step older (index 1)
  { match: (p, c) => c === 'confirmed'  && p !== 'confirmed',                        label: '▲ Became Confirmed', color: '#00D97E' },
  { match: (p, c) => c === 'watchlist'  && p === 'near_miss',                        label: '▲ Improved',         color: '#00F1FE' },
  { match: (p, c) => c === 'watchlist'  && p === 'confirmed',                        label: '▼ Degraded',         color: '#F59E0B' },
  { match: (p, c) => c === 'near_miss'  && (p === 'confirmed' || p === 'watchlist'), label: '▼ Became Near Miss', color: '#FF4D4F' },
  { match: (p, c) => c === p,                                                        label: '= Same',             color: '#5a5f72' },
  { match: ()     => true,                                                            label: '~ Changed',          color: '#8c90a1' },
]

function progressionLabel(prevCl, currCl) {
  const p = prevCl ?? ''
  const c = currCl ?? ''
  const found = PROGRESSION_MAP.find(m => m.match(p, c))
  return found ?? { label: '—', color: '#5a5f72' }
}

function SymbolHistorySection({ symbol }) {
  const [entries,   setEntries]   = useState(null)   // null = loading
  const [error,     setError]     = useState(null)
  const [expanded,  setExpanded]  = useState(false)
  const [open,      setOpen]      = useState(false)   // section collapsed by default

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setEntries(null); setError(null)
    apiSymbolHistory(symbol, 10)
      .then(res => {
        if (!cancelled) setEntries(res.data?.data ?? [])
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => { cancelled = true }
  }, [symbol])

  const loading = entries === null && !error

  // Determine which rows to show (5 by default, all if expanded)
  const visible = entries ? (expanded ? entries : entries.slice(0, 5)) : []

  return (
    <div style={{ marginBottom: '20px' }}>
      {/* Section header — toggles collapse */}
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
          color: T.muted, marginBottom: open ? '10px' : 0, paddingBottom: '7px',
          borderBottom: `1px solid ${T.muted}28`, cursor: 'pointer',
        }}
      >
        <span>K · Symbol History</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {entries !== null && (
            <span style={{ fontSize: '9px', padding: '1px 6px', borderRadius: '8px', background: 'rgba(255,255,255,0.06)', color: T.muted2, fontWeight: 600, textTransform: 'none', letterSpacing: 0 }}>
              {entries.length} saved
            </span>
          )}
          <span style={{ fontSize: '12px' }}>{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {open && (
        <div>
          {/* Loading */}
          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {[1,2,3].map(i => <Skeleton key={i} h="36px" />)}
            </div>
          )}

          {/* Error */}
          {error && (
            <div style={{ fontSize: '11px', color: T.muted, padding: '8px 10px', borderRadius: '7px', background: 'rgba(255,77,79,0.06)', border: '1px solid rgba(255,77,79,0.15)' }}>
              Could not load history. Try again later.
            </div>
          )}

          {/* Empty */}
          {entries !== null && entries.length === 0 && !error && (
            <div style={{ fontSize: '11px', color: T.muted2, padding: '8px 0' }}>
              No saved scan history for {symbol} yet.
            </div>
          )}

          {/* History rows */}
          {visible.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              {visible.map((entry, idx) => {
                const prevEntry = visible[idx + 1] ?? null
                const prog = idx < visible.length - 1
                  ? progressionLabel(prevEntry?.classification, entry.classification)
                  : null
                const cl    = entry.classification
                const clCol = CL_COLOR[cl] ?? T.muted
                const run   = entry.scan_run ?? {}
                const tf    = run.timeframe ?? entry.timeframe ?? '—'
                const ltf   = run.ltf ? `/${run.ltf}` : ''
                const dt    = entry.created_at
                  ? new Date(entry.created_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
                  : '—'

                const FLAG_COL = { severe: '#FF4D4F', warn: '#F59E0B', positive: '#00D97E', info: '#00F1FE' }
                const topFlag  = Array.isArray(entry.quality_flags) && entry.quality_flags.length > 0
                  ? entry.quality_flags[0] : null

                return (
                  <div key={entry.id ?? idx} style={{
                    padding: '9px 11px', borderRadius: '9px',
                    background: idx === 0 ? `${clCol}0c` : 'rgba(255,255,255,0.025)',
                    border: `1px solid ${idx === 0 ? clCol + '28' : T.border}`,
                  }}>
                    {/* Row top: date + progression (saved) + cl badge */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '5px', gap: '6px' }}>
                      <span style={{ fontSize: '10px', color: T.muted2, fontWeight: 500 }}>{dt}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flexShrink: 0 }}>
                        {/* Prefer saved progression_label from DB over computed frontend label */}
                        {entry.progression_label && entry.progression_type !== 'unchanged' && (() => {
                          const prio = entry.progression_priority ?? 0
                          const col  = prio >= 100 ? T.bullish : prio >= 60 ? T.cyan : prio >= 0 ? T.muted : T.bearish
                          return (
                            <span style={{ fontSize: '9px', fontWeight: 700, color: col }}>
                              {prio > 0 ? '▲' : '▼'} {entry.progression_label}
                            </span>
                          )
                        })()}
                        {/* Frontend-computed progression (compare adjacent entries) shown only when no saved data */}
                        {!entry.progression_label && prog && (
                          <span style={{ fontSize: '9px', fontWeight: 700, color: prog.color }}>{prog.label}</span>
                        )}
                        <ClassificationBadge value={cl} small />
                      </div>
                    </div>

                    {/* Row details: score, grade, stage, TF, watchlist level */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                      {/* Score */}
                      <span style={{ fontSize: '11px', fontWeight: 700, color: T.purple }}>
                        {entry.score != null ? entry.score.toFixed(1) : '—'}
                      </span>
                      {/* Grade */}
                      <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '5px', fontSize: '10px', fontWeight: 800, background: `${gradeColor(entry.grade)}20`, color: gradeColor(entry.grade), border: `1px solid ${gradeColor(entry.grade)}38` }}>
                        {entry.grade ?? '—'}
                      </span>
                      {/* Stage */}
                      <span style={{ fontSize: '10px', color: T.muted, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {entry.current_stage_label ?? (CL_LABEL[cl] ?? cl ?? '—')}
                      </span>
                    </div>

                    {/* Meta row: TF, universe, watchlist level, top flag */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '9px', color: T.primary, fontWeight: 600, padding: '1px 5px', borderRadius: '4px', background: 'rgba(0,102,255,0.1)' }}>{tf}{ltf}</span>
                      {run.universe && <span style={{ fontSize: '9px', color: T.muted2 }}>{run.universe}</span>}
                      {entry.watchlist_level && (
                        <span style={{ fontSize: '9px', fontWeight: 700, color: T.cyan }}>{entry.watchlist_level}</span>
                      )}
                      {topFlag && (
                        <span style={{ fontSize: '9px', fontWeight: 600, color: FLAG_COL[topFlag.severity] ?? T.muted, opacity: 0.8 }}>
                          {topFlag.label}
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}

              {/* Show more / Show less toggle */}
              {entries.length > 5 && (
                <button
                  onClick={() => setExpanded(e => !e)}
                  style={{
                    marginTop: '2px', padding: '5px', width: '100%', borderRadius: '7px',
                    background: 'transparent', border: `1px dashed ${T.border}`,
                    color: T.muted, fontSize: '10px', fontWeight: 600, cursor: 'pointer',
                    letterSpacing: '0.04em',
                  }}
                >
                  {expanded ? `▲ Show less` : `▼ Show ${entries.length - 5} more`}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── detail drawer ────────────────────────────────────────────────────────────

function DetailDrawer({ result, onClose, trackedEntry, onTrack, onUntrack, trackLoading }) {
  if (!result) return null
  const rd    = result.result_data ?? {}
  const dbg   = rd.debug_trace    ?? {}
  const sweep = rd.sweep_detail   ?? {}
  const choch = rd.choch_detail   ?? {}
  const fvg   = rd.fvg_detail     ?? {}
  const ob    = rd.ob_detail      ?? {}
  const ret   = rd.retest_detail  ?? {}
  // Support both canonical key (classification) and alias (setup_status)
  const cl    = rd.classification ?? rd.setup_status
  const clCol = CL_COLOR[cl] ?? T.muted
  // Stage label: prefer backend-computed value, fall back to frontend derivation
  const stageLabel = rd.current_stage_label ?? getStage(result).label
  const checklist = buildChecklist(result)   // { htfSteps, ltfSteps, summaryStep }

  const rr = (() => {
    const risk   = Math.abs((rd.stop_loss ?? 0) - (rd.entry ?? 0))
    const reward = Math.abs((rd.target_1  ?? 0) - (rd.entry ?? 0))
    return risk > 0 ? (reward / risk).toFixed(1) : null
  })()

  return (
    <AnimatePresence>
      <motion.div key="ov" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}
        onClick={onClose}
        style={{ position:'fixed', inset:0, zIndex:60, background:'rgba(5,8,16,0.75)', backdropFilter:'blur(5px)' }}
      />
      <motion.aside key="dr"
        initial={{x:'100%'}} animate={{x:0}} exit={{x:'100%'}}
        transition={{type:'spring', stiffness:290, damping:33}}
        style={{
          position:'fixed', top:0, right:0, bottom:0, zIndex:61,
          width:'min(500px,100vw)', background:T.surfaceAlt,
          borderLeft:`1px solid ${T.border2}`,
          overflowY:'auto', padding:'22px 20px 60px',
          fontFamily:'Inter,ui-sans-serif,sans-serif',
        }}
      >
        {/* ── header ── */}
        <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', marginBottom:'18px' }}>
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'8px' }}>
              <span style={{ fontSize:'22px', fontWeight:800, color:T.text, letterSpacing:'-0.02em' }}>{result.symbol}</span>
              <NSEBadge />
            </div>
            <div style={{ display:'flex', gap:'6px', flexWrap:'wrap', alignItems:'center' }}>
              <span style={{ fontSize:'11px', fontWeight:700, padding:'2px 9px', borderRadius:'20px', background:result.direction==='bullish'?T.bullishDim:T.bearishDim, color:dirColor(result.direction), textTransform:'uppercase' }}>
                {result.direction==='bullish'?'▲':'▼'} {result.direction}
              </span>
              <ClassificationBadge value={cl} />
              {rd.stale && <StaleBadge />}
            </div>
          </div>
          <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
            {/* Track / Untrack button */}
            {trackedEntry ? (
              <button
                onClick={onUntrack}
                disabled={trackLoading}
                title="Remove from watchlist"
                style={{ display:'flex', alignItems:'center', gap:'5px', padding:'6px 13px', borderRadius:'8px', border:'1px solid rgba(0,241,254,0.3)', background:'rgba(0,241,254,0.1)', color:'#00f1fe', fontSize:'11px', fontWeight:700, cursor:'pointer', whiteSpace:'nowrap' }}>
                {trackLoading ? '…' : '✓ Tracking'}
              </button>
            ) : (
              <button
                onClick={onTrack}
                disabled={trackLoading}
                title="Add to watchlist"
                style={{ display:'flex', alignItems:'center', gap:'5px', padding:'6px 13px', borderRadius:'8px', border:`1px solid ${T.border}`, background:'rgba(255,255,255,0.05)', color:T.muted, fontSize:'11px', fontWeight:600, cursor:'pointer', whiteSpace:'nowrap' }}>
                {trackLoading ? '…' : '+ Track Symbol'}
              </button>
            )}
            <button onClick={onClose} style={{ background:'rgba(255,255,255,0.06)', border:`1px solid ${T.border}`, borderRadius:'8px', padding:'6px 12px', color:T.muted, cursor:'pointer', fontSize:'18px', lineHeight:1 }}>×</button>
          </div>
        </div>

        {/* ── score blocks ── */}
        <div style={{ display:'flex', gap:'9px', marginBottom:'18px' }}>
          <DBlock label="Score"     value={`${result.score?.toFixed(1)??'—'}`} valueColor={T.purple} />
          <DBlock label="Grade"     value={result.grade??'—'}     valueColor={gradeColor(result.grade)} />
          <DBlock label="Timeframe" value={result.timeframe??'—'} />
          <DBlock label="Age"       value={rd.setup_age!=null?`${rd.setup_age}b`:'—'} valueColor={rd.stale?T.amber:rd.setup_age<=5?T.bullish:T.muted} />
        </div>

        {/* ── progression banner ── */}
        {result.progression_type && result.progression_type !== 'unchanged' && (() => {
          const prio  = result.progression_priority ?? 0
          const label = result.progression_label
          const positive = prio > 0
          const col = prio >= 100 ? T.bullish
                    : prio >= 70  ? T.cyan
                    : prio >= 60  ? T.purple
                    : prio >= 0   ? T.muted
                    : T.bearish
          const bgAlpha = positive ? '0c' : '08'
          const borderAlpha = positive ? '28' : '20'
          const prevParts = []
          if (result.previous_status) prevParts.push(result.previous_status)
          if (result.previous_watchlist_level) prevParts.push(result.previous_watchlist_level)
          if (result.previous_score != null) prevParts.push(`score ${result.previous_score.toFixed(1)}`)
          return (
            <div style={{ marginBottom:'14px', padding:'9px 13px', borderRadius:'9px', background:`${col}${bgAlpha}`, border:`1px solid ${col}${borderAlpha}` }}>
              <div style={{ display:'flex', alignItems:'center', gap:'7px' }}>
                <span style={{ fontSize:'13px' }}>{positive ? '▲' : '▼'}</span>
                <span style={{ fontSize:'12px', fontWeight:700, color: col }}>{label}</span>
              </div>
              {prevParts.length > 0 && (
                <div style={{ fontSize:'10px', color:T.muted, marginTop:'3px' }}>
                  Previous: {prevParts.join(' · ')}
                </div>
              )}
            </div>
          )
        })()}

        {/* stale warning */}
        {rd.stale && (
          <div style={{ marginBottom:'16px', padding:'9px 13px', borderRadius:'9px', background:T.amberDim, border:'1px solid rgba(245,158,11,0.3)', fontSize:'12px', color:T.amber, lineHeight:1.6 }}>
            ⚠ <strong>Stale setup</strong> — {dbg.setup_age}b old (max {dbg.max_setup_age}b). Downgraded to near_miss. Do not trade stale signals.
          </div>
        )}

        {/* partial disclaimer */}
        {(cl==='partial_setup'||cl==='near_miss') && !rd.stale && (
          <div style={{ marginBottom:'16px', padding:'9px 13px', borderRadius:'9px', background:`${clCol}0a`, border:`1px solid ${clCol}28`, fontSize:'12px', color:clCol, lineHeight:1.6 }}>
            {cl==='partial_setup'
              ? '⚡ Partial setup — missing one or more key confirmations. Review checklist before any action.'
              : `🔎 Near miss — sweep found but structural confirmation incomplete.${(rd.status_reason||rd.rejection_reason) ? ` Reason: ${rd.status_reason??rd.rejection_reason}` : ''}`}
          </div>
        )}

        {/* ══ A. Setup Summary ══ */}
        <DSection title="A · Setup Summary" accent={clCol}>
          <DRow label="Classification" value={<ClassificationBadge value={cl} />} />
          <DRow label="Stage"         value={<span style={{fontSize:'11px',color:T.cyan,fontWeight:600}}>{stageLabel}</span>} />
          {cl === 'watchlist' && rd.watchlist_level && (
            <DRow label="Watchlist Level" value={
              <span style={{
                fontSize:'11px', fontWeight:700, padding:'2px 9px', borderRadius:'20px',
                background: rd.watchlist_level==='L4' ? 'rgba(0,217,126,0.12)'
                          : rd.watchlist_level==='L3' ? 'rgba(0,241,254,0.10)'
                          : rd.watchlist_level==='L2' ? 'rgba(245,158,11,0.12)'
                          :                             'rgba(148,100,246,0.12)',
                color:      rd.watchlist_level==='L4' ? T.bullish
                          : rd.watchlist_level==='L3' ? T.cyan
                          : rd.watchlist_level==='L2' ? T.amber
                          :                             T.purple,
                border: `1px solid ${
                          rd.watchlist_level==='L4' ? 'rgba(0,217,126,0.3)'
                        : rd.watchlist_level==='L3' ? 'rgba(0,241,254,0.25)'
                        : rd.watchlist_level==='L2' ? 'rgba(245,158,11,0.3)'
                        :                             'rgba(148,100,246,0.3)'
                }`,
              }}>{rd.watchlist_level_label ?? rd.watchlist_level}</span>
            } />
          )}
          <DRow label="Mode"           value={<span style={{fontSize:'11px',padding:'2px 8px',borderRadius:'20px',background:T.cyanDim,color:T.cyan,fontWeight:600}}>{rd.mode??'—'}</span>} />
          <DRow label="Direction"      value={result.direction} color={dirColor(result.direction)} />
          <DRow label="Entry Source"   value={rd.entry_source??'—'} color={rd.entry_source==='last_close'?T.muted:T.cyan} />
          <DRow label="Setup Age"      value={rd.setup_age!=null?`${rd.setup_age} bars`:'—'} color={rd.stale?T.amber:undefined} />
          <DRow label="Stale"          value={rd.stale!=null?(rd.stale?<StaleBadge/>:<span style={{color:T.bullish,fontWeight:600}}>✓ Fresh</span>):'—'} />
          {rd.equal_levels?.equal_highs && <DRow label="Equal Highs" value={<span style={{color:T.amber,fontWeight:600}}>✓ Near swept level</span>} />}
          {rd.equal_levels?.equal_lows  && <DRow label="Equal Lows"  value={<span style={{color:T.amber,fontWeight:600}}>✓ Near swept level</span>} />}
        </DSection>

        {/* ══ B. HTF Checklist ══ */}
        <DSection title="B · HTF Checklist" accent={T.cyan}>
          <div style={{ fontSize:'10px', color:T.muted2, fontWeight:600, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>
            Higher Timeframe Sequence ({result.timeframe})
          </div>
          {checklist.htfSteps.map((step, i) => <ChecklistRow key={i} step={step} idx={i} />)}
        </DSection>

        {/* ══ C. LTF Checklist ══ */}
        <DSection title="C · LTF Checklist" accent={T.purple}>
          <div style={{ fontSize:'10px', color:T.muted2, fontWeight:600, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>
            Lower Timeframe Entry Confirmation
          </div>
          {checklist.ltfSteps.map((step, i) => <ChecklistRow key={i} step={step} idx={i} />)}
          <div style={{ marginTop:'10px' }}>
            <ChecklistRow step={checklist.summaryStep} idx={checklist.ltfSteps.length} />
          </div>
        </DSection>

        {/* ══ D. Trade Plan ══ */}
        {(() => {
          const tpt   = rd.trade_plan_type  ?? (cl==='confirmed' ? 'entry' : cl==='watchlist' ? 'preparation' : 'no_trade')
          const isEntry = tpt === 'entry'
          const isPrep  = tpt === 'preparation'
          const isNone  = tpt === 'no_trade'
          const accentCol = isEntry ? T.bullish : isPrep ? T.amber : T.muted
          const titleText = rd.trade_plan_title ?? (isEntry ? 'Entry Signal' : isPrep ? 'Preparation Zone' : 'No Trade')
          return (
          <DSection title="D · Trade Plan" accent={accentCol}>

            {/* Header bar */}
            <div style={{ marginBottom:'10px', padding:'7px 11px', borderRadius:'8px',
              background: isEntry ? 'rgba(0,217,126,0.08)' : isPrep ? 'rgba(245,158,11,0.07)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${isEntry ? 'rgba(0,217,126,0.25)' : isPrep ? 'rgba(245,158,11,0.25)' : T.border}`,
            }}>
              <div style={{ fontSize:'11px', fontWeight:700, color: accentCol }}>{titleText}</div>
            </div>

            {/* Warning banner — watchlist and near_miss only */}
            {(isPrep || isNone) && rd.trade_plan_warning && (
              <div style={{ marginBottom:'10px', padding:'8px 11px', borderRadius:'8px',
                background: isPrep ? 'rgba(245,158,11,0.06)' : 'rgba(255,77,79,0.06)',
                border: `1px solid ${isPrep ? 'rgba(245,158,11,0.28)' : 'rgba(255,77,79,0.22)'}`,
              }}>
                <div style={{ fontSize:'10px', fontWeight:700, color: isPrep ? T.amber : T.bearish,
                  textTransform:'uppercase', letterSpacing:'0.07em', marginBottom:'4px' }}>
                  {isPrep ? '⚠ Not an entry signal yet' : '✗ No trade — incomplete'}
                </div>
                <div style={{ fontSize:'11px', color: isPrep ? T.amber : T.muted, lineHeight:1.65 }}>
                  {rd.trade_plan_warning}
                </div>
              </div>
            )}

            {/* Entry source pill — only for confirmed */}
            {isEntry && (
              <InfoBox color={rd.entry_source==='ltf_ob'?T.purple:T.cyan}>
                Entry source: <strong>{
                  rd.entry_source==='ltf_ob'       ? 'LTF OB 2.0 — precision limit entry' :
                  rd.entry_source==='ob_retest'    ? 'HTF OB 1.0 retest — limit entry zone' :
                  rd.entry_source==='fvg_retest'   ? 'FVG retest — limit entry zone' :
                  rd.entry_source==='last_close'   ? 'Last close — reference only' :
                  rd.entry_source ?? '—'
                }</strong>
              </InfoBox>
            )}

            {/* Level rows — labels differ by plan type */}
            <div style={{ marginTop:'10px' }}>
              {isEntry && <>
                <DRow label="Entry Zone"         value={fmt(rd.entry)}     color={T.bullish} mono />
                <DRow label="Stop Loss"          value={fmt(rd.stop_loss)} color={T.bearish} mono />
                <DRow label="Target 1 (2R)"      value={fmt(rd.target_1)}  color={T.bullish} mono />
                <DRow label="Target 2 (3.5R)"    value={fmt(rd.target_2)}  color={T.bullish} mono />
                {rr && <DRow label="Risk / Reward (T1)" value={`1 : ${rr}`} color={parseFloat(rr)>=2?T.bullish:parseFloat(rr)>=1.5?T.cyan:T.amber} />}
              </>}
              {isPrep && <>
                <DRow label="Preparation Zone"   value={fmt(rd.entry)}     color={T.amber}   mono />
                <DRow label="Candidate Stop"     value={fmt(rd.stop_loss)} color={T.bearish} mono />
                <DRow label="Potential T1 (2R)"  value={fmt(rd.target_1)}  color={T.muted}   mono />
                <DRow label="Potential T2 (3.5R)"value={fmt(rd.target_2)}  color={T.muted}   mono />
                <DRow label="Not Entry Ready"    value={rd.watchlist_level_label ?? rd.watchlist_level ?? '—'}
                  color={T.amber} />
              </>}
              {isNone && <>
                <DRow label="No Trade"           value="Confirmation incomplete" color={T.muted} />
                <DRow label="Ref. Level"         value={fmt(rd.entry)}     color={T.muted}   mono />
                <DRow label="Missing"            value={rd.rejection_reason ?? '—'} color={T.muted} />
                <DRow label="Failed / Pending"   value={rd.current_stage_label ?? '—'} color={T.muted} />
              </>}
              <DRow label="Grade" value={result.grade??'—'} color={gradeColor(result.grade)} />
            </div>

            {/* Invalidation */}
            {rd.invalidation_text && (
              <div style={{ marginTop:'10px', padding:'7px 10px', borderRadius:'7px',
                background:'rgba(255,77,79,0.05)', border:'1px solid rgba(255,77,79,0.18)' }}>
                <div style={{ fontSize:'10px', fontWeight:700, color:T.bearish, textTransform:'uppercase', letterSpacing:'0.07em', marginBottom:'4px' }}>
                  {isEntry ? 'Invalidation' : isPrep ? 'Candidate Invalidation' : 'Invalidation'}
                </div>
                <div style={{ fontSize:'11px', color:T.muted, lineHeight:1.6 }}>{rd.invalidation_text}</div>
              </div>
            )}

            {/* Reasoning */}
            {rd.reason && (
              <div style={{ marginTop:'10px', padding:'8px 10px', borderRadius:'8px', background:'rgba(255,255,255,0.03)', border:`1px solid ${T.border}` }}>
                <div style={{ fontSize:'10px', fontWeight:600, color:T.muted2, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'5px' }}>Reasoning</div>
                <p style={{ fontSize:'11px', color:T.muted, lineHeight:1.7, margin:0 }}>{rd.reason}</p>
              </div>
            )}
          </DSection>
        )})()}

        {/* ══ E. Displacement ══ */}
        {(() => { const disp = rd.displacement_detail ?? {}; return (
        <DSection title="E · Displacement" accent={disp.found?T.cyan:T.muted}>
          <DRow label="Detected" value={disp.found?<span style={{color:T.bullish,fontWeight:600}}>✓ Yes</span>:<span style={{color:T.muted}}>Not found</span>} />
          {disp.found ? (
            <>
              <DRow label="Disp. Bar"    value={`bar ${disp.displacement_idx}`} />
              <DRow label="Body / ATR"   value={`${fmtN(disp.atr_ratio)}× ATR`} color={disp.atr_ratio>=1?T.bullish:T.cyan} mono />
              <DRow label="Direction"    value={disp.direction??'—'} color={disp.direction==='bullish'?T.bullish:T.bearish} />
            </>
          ) : (
            <InfoBox>No displacement candle (body ≥ 0.5× ATR) found after sweep.</InfoBox>
          )}
        </DSection>
        )})()}

        {/* ══ F. Sweep Detail ══ */}
        <DSection title="F · Liquidity + Sweep" accent={T.bullish}>
          <DRow label="Sweep"          value={rd.sweep?<span style={{color:T.bullish,fontWeight:600}}>✓ Confirmed</span>:<span style={{color:T.muted}}>Not detected</span>} />
          <DRow label="Liquidity Type" value={sweep.liq_type==='buy_side'?<span style={{color:T.bearish,fontWeight:600}}>Buy-Side (above highs)</span>:<span style={{color:T.bullish,fontWeight:600}}>Sell-Side (below lows)</span>} />
          <DRow label="Liq. Level"     value={fmtN(rd.liquidity_level)} mono />
          <DRow label="Sweep Bar"      value={sweep.sweep_idx!=null?`bar ${sweep.sweep_idx}`:'—'} />
          <DRow label="Swept Wick"     value={sweep.swept_wick!=null?`${fmtN(sweep.swept_wick)} pts`:'—'} color={T.cyan} mono />
          <DRow label="Close-Back"     value={sweep.close_back_size!=null?`${fmtN(sweep.close_back_size)} pts`:'—'} color={T.text} mono />
          <DRow label="Liq. Age"       value={dbg.liquidity_age!=null?`${dbg.liquidity_age} bars`:'—'} />
        </DSection>

        {/* ══ G. ChoCH + OB ══ */}
        <DSection title="G · ChoCH + OB 1.0" accent={choch.confirmed?T.cyan:T.muted}>
          <DRow label="ChoCH" value={choch.confirmed?<span style={{color:T.bullish,fontWeight:600}}>✓ Confirmed</span>:<span style={{color:T.muted}}>Not confirmed</span>} />
          {choch.confirmed && (
            <>
              <DRow label="ChoCH Bar"        value={`bar ${choch.choch_idx}`} />
              <DRow label="Ref. Level"        value={fmtN(choch.choch_level)} mono />
              <DRow label="Bars After Sweep"  value={`${choch.bars_after_sweep}b`} color={choch.bars_after_sweep<=2?T.bullish:choch.bars_after_sweep<=5?T.cyan:T.amber} />
              <DRow label="Break Amount"      value={choch.break_amount!=null?`${fmtN(choch.break_amount)} pts`:'—'} color={T.cyan} mono />
              <DRow label="Ref. Type"         value={choch.reference_type??'—'} color={choch.reference_type?.includes('swing')?T.bullish:T.amber} />
            </>
          )}
          <div style={{ marginTop:'6px', borderTop:`1px solid ${T.border}`, paddingTop:'6px' }}>
            <DRow label="OB 1.0" value={ob.found?<span style={{color:T.bullish,fontWeight:600}}>✓ Found</span>:<span style={{color:T.muted}}>Not found</span>} />
            {ob.found && (
              <>
                <DRow label="Type"   value={ob.ob_type??'—'} color={ob.ob_type==='bullish_ob'?T.bullish:T.bearish} />
                <DRow label="Zone"   value={`${fmtN(ob.zone_low)} – ${fmtN(ob.zone_high)}`} mono />
                <DRow label="OB Bar" value={`bar ${ob.ob_idx}`} />
              </>
            )}
          </div>
        </DSection>

        {/* ══ H. FVG + Retest ══ */}
        <DSection title="H · FVG + HTF Retest" accent={fvg.found?T.purple:T.muted}>
          <DRow label="FVG" value={fvg.found?<span style={{color:T.bullish,fontWeight:600}}>✓ Found</span>:<span style={{color:T.muted}}>Not found</span>} />
          {fvg.found && (
            <>
              <DRow label="Zone"    value={`${fmtN(fvg.zone_low)} – ${fmtN(fvg.zone_high)}`} mono />
              <DRow label="Gap %"   value={`${fmtN(fvg.gap_pct)}%`} color={T.cyan} />
              <DRow label="FVG Bar" value={`bar ${fvg.fvg_idx}`} />
            </>
          )}
          <div style={{ marginTop:'6px', borderTop:`1px solid ${T.border}`, paddingTop:'6px' }}>
            <DRow label="HTF OB Retest" value={ret.retested?<span style={{color:T.bullish,fontWeight:600}}>✓ Yes</span>:<span style={{color:T.muted}}>Not yet</span>} />
            {ret.retested && (
              <>
                <DRow label="Zone Type"  value={(ret.zone_type??'').toUpperCase()} color={T.cyan} />
                <DRow label="Retest Bar" value={`bar ${ret.retest_idx}`} />
              </>
            )}
            {!ret.retested && choch.confirmed && (
              <InfoBox color={T.muted}>OB active — price not yet back inside zone {fmtN(ob.zone_low)}–{fmtN(ob.zone_high)}.</InfoBox>
            )}
          </div>
        </DSection>

        {/* ══ H2. Quality Flags ══ */}
        {Array.isArray(rd.quality_flags) && rd.quality_flags.length > 0 && (() => {
          const SEV_COLOR = { severe:'#FF4D4F', warn:T.amber, positive:T.bullish, info:T.cyan }
          const SEV_BG    = { severe:'rgba(255,77,79,0.08)', warn:'rgba(245,158,11,0.07)',
                              positive:'rgba(0,217,126,0.07)', info:'rgba(0,241,254,0.06)' }
          const SEV_BORDER= { severe:'rgba(255,77,79,0.25)', warn:'rgba(245,158,11,0.25)',
                              positive:'rgba(0,217,126,0.22)', info:'rgba(0,241,254,0.18)' }
          const SEV_ICON  = { severe:'✕', warn:'⚠', positive:'✓', info:'ℹ' }
          return (
          <DSection title="H2 · Quality Flags" accent={T.muted} collapsible>
            <div style={{ display:'flex', flexDirection:'column', gap:'6px' }}>
              {rd.quality_flags.map((f, i) => (
                <div key={i} style={{
                  display:'flex', alignItems:'flex-start', gap:'8px',
                  padding:'7px 10px', borderRadius:'7px',
                  background: SEV_BG[f.severity] ?? 'rgba(255,255,255,0.04)',
                  border: `1px solid ${SEV_BORDER[f.severity] ?? T.border}`,
                }}>
                  <span style={{ fontSize:'11px', fontWeight:700, color: SEV_COLOR[f.severity] ?? T.muted, minWidth:'13px', marginTop:'1px' }}>
                    {SEV_ICON[f.severity] ?? '·'}
                  </span>
                  <div style={{ flex:1 }}>
                    <div style={{ fontSize:'11px', fontWeight:700, color: SEV_COLOR[f.severity] ?? T.muted, marginBottom:'2px' }}>
                      {f.label}
                    </div>
                    <div style={{ fontSize:'10px', color:T.muted, lineHeight:1.55 }}>{f.detail}</div>
                  </div>
                  <span style={{ fontSize:'9px', fontWeight:600, color: SEV_COLOR[f.severity] ?? T.muted, opacity:0.6, textTransform:'uppercase', letterSpacing:'0.05em', whiteSpace:'nowrap' }}>
                    {f.severity}
                  </span>
                </div>
              ))}
            </div>
          </DSection>
        )})()}

        {/* ══ I. Debug Trace (collapsible) ══ */}
        <DSection title="I · Debug Trace" accent={T.muted} collapsible>
          <DRow label="Candles Fetched"    value={dbg.candles_fetched??'—'} />
          <DRow label="Swing Highs"        value={dbg.swing_highs_found??'—'} />
          <DRow label="Swing Lows"         value={dbg.swing_lows_found??'—'} />
          <DRow label="Sweeps Found"       value={dbg.sweeps_found??'—'} />
          <DRow label="Sweep at Bar"       value={dbg.sweep_idx??'—'} />
          <DRow label="Disp. at Bar"       value={dbg.displacement_idx??'—'} />
          <DRow label="ChoCH at Bar"       value={dbg.choch_idx??'—'} />
          <DRow label="FVG Search"         value={`${dbg.fvg_search_start??'—'} → ${dbg.fvg_search_end??'—'}`} />
          <DRow label="Retest Scan Start"  value={dbg.retest_scan_start??'N/A'} />
          <DRow label="Liq. Age / Max"     value={`${dbg.liquidity_age??'—'} / ${dbg.max_liquidity_age??'—'}`} />
          <DRow label="Setup Age / Max"    value={`${dbg.setup_age??'—'} / ${dbg.max_setup_age??'—'}`} />
          <DRow label="Rejection Reason"   value={dbg.rejection_reason??rd.rejection_reason??'—'} color={T.muted} />
          <DRow label="LTF Timeframe"      value={dbg.ltf_timeframe??'—'} />
          <DRow label="ChoCH Ref. Type"    value={dbg.choch_reference_type??choch.reference_type??'—'} color={(dbg.choch_reference_type??choch.reference_type??'').includes('swing')?T.bullish:T.amber} />

          {/* Phase 2 candidate mode fields */}
          {dbg.candidate_mode && (<>
            <DRow label="Candidate Mode"     value={dbg.candidate_mode} color={dbg.candidate_mode==='best_setup'?T.cyan:T.muted} />
            <DRow label="Candidates Tested"  value={dbg.candidates_tested??'—'} />
            <DRow label="Selected Rank"      value={dbg.selected_candidate_rank!=null ? `#${dbg.selected_candidate_rank}` : '—'} />
            <DRow label="Selected Src"       value={dbg.selected_liq_source??'—'} color={T.amber} />
            <DRow label="Src Strength"       value={dbg.selected_liq_strength??'—'} />
          </>)}
          {Array.isArray(dbg.candidate_summary) && dbg.candidate_summary.length > 1 && (
            <div style={{ marginTop:'10px' }}>
              <div style={{ fontSize:'10px', fontWeight:700, color:T.muted, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'6px' }}>
                Candidate Summary ({dbg.candidate_summary.length})
              </div>
              <div style={{ display:'flex', flexDirection:'column', gap:'3px' }}>
                {dbg.candidate_summary.map((c, i) => {
                  const isSel = c.rank === dbg.selected_candidate_rank
                  const clColor = c.classification==='watchlist'?T.bullish:c.classification==='confirmed'?T.cyan:T.muted
                  return (
                    <div key={i} style={{
                      fontSize:'11px', display:'flex', gap:'6px', padding:'4px 6px', borderRadius:'5px',
                      background: isSel ? 'rgba(0,241,254,0.07)' : 'transparent',
                      border: isSel ? `1px solid rgba(0,241,254,0.2)` : `1px solid ${T.border}`,
                    }}>
                      <span style={{ color:T.muted2, minWidth:'18px' }}>#{c.rank}</span>
                      <span style={{ color:T.text, minWidth:'88px', fontSize:'10px' }}>{c.liq_source}</span>
                      <span style={{ color:clColor, minWidth:'60px' }}>{c.classification}</span>
                      <span style={{ color:T.amber, minWidth:'36px' }}>{c.score?.toFixed(1)}</span>
                      <span style={{ color:T.muted, fontSize:'10px', flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{c.stage_label}</span>
                      {isSel && <span style={{ color:T.cyan, fontSize:'10px', fontWeight:700 }}>SELECTED</span>}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {dbg.score_breakdown && (
            <div style={{ marginTop:'12px' }}>
              <div style={{ fontSize:'10px', fontWeight:700, color:T.muted, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>Score Breakdown</div>
              {Object.entries(dbg.score_breakdown).map(([k, v]) => <ScoreBar key={k} label={k} value={v} max={SCORE_MAX[k]??20} />)}
            </div>
          )}
          {Array.isArray(dbg.skipped_symbols) && dbg.skipped_symbols.length > 0 && (
            <div style={{ marginTop:'12px' }}>
              <div style={{ fontSize:'10px', fontWeight:700, color:T.muted, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'6px' }}>
                Skipped ({dbg.skipped_symbols.length})
              </div>
              <div style={{ maxHeight:'120px', overflowY:'auto', display:'flex', flexDirection:'column', gap:'3px' }}>
                {dbg.skipped_symbols.map((s, i) => (
                  <div key={i} style={{ fontSize:'11px', display:'flex', gap:'8px', padding:'3px 0', borderBottom:`1px solid ${T.border}` }}>
                    <span style={{ color:T.text, fontWeight:600, minWidth:'80px' }}>{s.symbol}</span>
                    <span style={{ color:T.muted }}>{s.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </DSection>

        {/* ══ K. Symbol History ══ */}
        <SymbolHistorySection symbol={result.symbol} />

        {/* ══ J. TradingView ══ */}
        <DSection title="J · TradingView" accent={T.primary}>
          <a href={tvUrl(result.symbol)} target="_blank" rel="noopener noreferrer"
            style={{
              display:'flex', alignItems:'center', justifyContent:'center', gap:'8px',
              padding:'11px', borderRadius:'10px', width:'100%', boxSizing:'border-box',
              background:`linear-gradient(90deg,${T.primary},#005ce6)`,
              color:'#fff', fontSize:'13px', fontWeight:700,
              textDecoration:'none', letterSpacing:'0.03em',
              boxShadow:'0 0 20px rgba(0,102,255,0.3)',
            }}
          >
            <span>📈</span> Open {result.symbol} on TradingView
          </a>
          <div style={{ marginTop:'8px', fontSize:'11px', color:T.muted, textAlign:'center' }}>
            Opens NSE:{result.symbol} chart in a new tab
          </div>
        </DSection>

      </motion.aside>
    </AnimatePresence>
  )
}

// ─── access denied ────────────────────────────────────────────────────────────

function AccessDenied({ message }) {
  const navigate = useNavigate()
  return (
    <div style={{ background:T.bearishDim, border:'1px solid rgba(255,77,79,0.2)', borderRadius:'16px', padding:'40px', textAlign:'center' }}>
      <div style={{ fontSize:'36px', marginBottom:'14px' }}>🔒</div>
      <div style={{ fontSize:'18px', fontWeight:700, color:T.text, marginBottom:'8px' }}>Tool Locked</div>
      <div style={{ fontSize:'14px', color:T.muted, marginBottom:'24px', lineHeight:1.6, maxWidth:'360px', margin:'0 auto 24px' }}>
        {message || 'Your current plan does not include access to Stop Hunter Pro.'}
      </div>
      <button onClick={() => navigate('/pricing')} style={{ padding:'11px 28px', borderRadius:'10px', background:`linear-gradient(90deg,${T.primary},#0052cc)`, border:'none', color:'#fff', fontSize:'14px', fontWeight:600, cursor:'pointer' }}>
        View Upgrade Options →
      </button>
    </div>
  )
}

// ─── motion presets ───────────────────────────────────────────────────────────

const fadeUp = { hidden:{opacity:0,y:14}, show:{opacity:1,y:0,transition:{duration:0.35,ease:[0.25,0.46,0.45,0.94]}} }
const stagger = { hidden:{}, show:{transition:{staggerChildren:0.04}} }

// ─── toolbar sub-components ───────────────────────────────────────────────────

function SegGroup({ options, value, onChange, accentActive = T.cyan }) {
  return (
    <div style={{ display:'inline-flex', background:'rgba(255,255,255,0.04)', border:`1px solid ${T.border}`, borderRadius:'8px', overflow:'hidden' }}>
      {options.map(o => {
        const active = o.value===value
        return (
          <button key={o.value} onClick={() => onChange(o.value)} style={{
            padding:'6px 13px', border:'none', cursor:'pointer', fontSize:'12px', fontWeight:600,
            background:active?`${accentActive}20`:'transparent',
            color:active?accentActive:T.muted,
            borderRight:`1px solid ${T.border}`,
            transition:'all 0.15s', whiteSpace:'nowrap',
          }}>{o.label}</button>
        )
      })}
    </div>
  )
}

function TFButton({ tf, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      padding:'6px 12px', border:`1px solid ${active?T.cyan:T.border}`, borderRadius:'7px',
      background:active?T.cyanDim:'transparent', color:active?T.cyan:T.muted,
      fontSize:'12px', fontWeight:600, cursor:'pointer', transition:'all 0.15s',
    }}>{tf}</button>
  )
}

function FilterChip({ chip, active, onClick, count }) {
  return (
    <button onClick={onClick} style={{
      padding:'5px 12px', borderRadius:'20px', border:`1px solid ${active?T.cyan:T.border}`,
      background:active?T.cyanDim:'transparent', color:active?T.cyan:T.muted,
      fontSize:'11px', fontWeight:active?700:500, cursor:'pointer',
      transition:'all 0.15s', whiteSpace:'nowrap', display:'inline-flex', alignItems:'center', gap:'5px',
    }}>
      {chip.label}
      {count != null && <span style={{ fontSize:'10px', fontWeight:700, padding:'0 5px', borderRadius:'10px', background:active?'rgba(0,241,254,0.2)':'rgba(255,255,255,0.08)', color:active?T.cyan:T.muted }}>{count}</span>}
    </button>
  )
}

// ─── classification tab bar ───────────────────────────────────────────────────

const CLASS_TABS = [
  { id: 'all',       label: 'All',       color: null,      icon: '◈' },
  { id: 'confirmed', label: 'Confirmed', color: T.bullish, icon: '✓' },
  { id: 'watchlist', label: 'Watchlist', color: T.cyan,    icon: '◉' },
  { id: 'near_miss', label: 'Near Miss', color: T.amber,   icon: '◎' },
  // 'rejected' appended conditionally when debugMode=true
]

function ClassTabBar({ active, counts, onChange, showRejected }) {
  const tabs = showRejected
    ? [...CLASS_TABS, { id: 'rejected', label: 'Rejected', color: T.bearish, icon: '✕' }]
    : CLASS_TABS

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '4px',
      background: T.surface, border: `1px solid ${T.border}`,
      borderRadius: '11px', padding: '5px 6px',
      marginBottom: '10px', overflowX: 'auto',
    }}>
      {tabs.map(tab => {
        const isActive = active === tab.id
        const accent   = tab.color ?? T.muted
        const count    = counts[tab.id] ?? 0
        return (
          <button key={tab.id} onClick={() => onChange(tab.id)} style={{
            display: 'inline-flex', alignItems: 'center', gap: '6px',
            padding: '6px 14px', borderRadius: '8px', border: 'none', cursor: 'pointer',
            background: isActive ? `${accent}18` : 'transparent',
            color: isActive ? accent : T.muted,
            fontWeight: isActive ? 700 : 500, fontSize: '12px',
            transition: 'all 0.14s', whiteSpace: 'nowrap',
            boxShadow: isActive ? `inset 0 0 0 1px ${accent}38` : 'none',
          }}>
            <span style={{ fontSize: '10px' }}>{tab.icon}</span>
            {tab.label}
            <span style={{
              fontSize: '10px', fontWeight: 700,
              padding: '1px 6px', borderRadius: '10px',
              background: isActive ? `${accent}25` : 'rgba(255,255,255,0.07)',
              color: isActive ? accent : T.muted2,
              minWidth: '18px', textAlign: 'center',
            }}>{count}</span>
          </button>
        )
      })}
    </div>
  )
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function ScannerPage() {
  const navigate  = useNavigate()
  const showToast = useShowToast()

  // ── source / market ─────────────────────────────────────────────────────────
  const [sourceTab,   setSourceTab]   = useState('universe')  // universe | custom
  const [marketType,  setMarketType]  = useState('stocks')    // stocks | all

  // ── scan controls ───────────────────────────────────────────────────────────
  const [universe,  setUniverse]  = useState('NIFTY50')
  const [timeframe, setTimeframe] = useState('1d')
  const [mode,      setMode]      = useState('mock')
  const [strict,    setStrict]    = useState(null)   // 'strict' | 'relaxed' | null (custom)

  // ── live filters ────────────────────────────────────────────────────────────
  const [includeNearMiss, setIncludeNearMiss] = useState(true)
  const [requireFvg,      setRequireFvg]      = useState(false)
  const [maxSetupAge,     setMaxSetupAge]     = useState(30)
  const [maxLiqAge,       setMaxLiqAge]       = useState(100)
  const [minScore,        setMinScore]        = useState(40)

  // ── Phase 1 filters ─────────────────────────────────────────────────────────
  const [scanMode,        setScanMode]        = useState('present')  // 'present' | 'historical'
  const [useEqhEql,       setUseEqhEql]       = useState(true)
  const [useSessionLvls,  setUseSessionLvls]  = useState(true)
  const [minBodyPct,      setMinBodyPct]       = useState(60)   // %  → sent as 0.60
  const [minFvgAtr,       setMinFvgAtr]        = useState(15)   // %  → sent as 0.15

  // ── Phase 2 filters ─────────────────────────────────────────────────────────
  const [candidateMode,   setCandidateMode]   = useState('fast')  // 'fast' | 'best_setup'

  // ── result UI state ─────────────────────────────────────────────────────────
  const [activeChip,     setActiveChip]     = useState('all')
  const [activeClassTab, setActiveClassTab] = useState('all')   // all | confirmed | watchlist | near_miss | rejected
  const [debugMode,      setDebugMode]      = useState(false)
  const [sortOrder,      setSortOrder]      = useState('score_desc')
  const [symbolSearch,   setSymbolSearch]   = useState('')
  const [dirFilter,      setDirFilter]      = useState('both')  // both | bull | bear

  // ── scan state ──────────────────────────────────────────────────────────────
  const [scanning,    setScanning]    = useState(false)
  const [jobInfo,     setJobInfo]     = useState(null)
  const [results,     setResults]     = useState(null)
  const [scanHealth,  setScanHealth]  = useState(null)
  const [accessError, setAccessError] = useState(null)
  const [apiError,    setApiError]    = useState(null)
  const [selected,    setSelected]    = useState(null)

  // ── notifications ────────────────────────────────────────────────────────────
  const [notifications,      setNotifications]      = useState([])
  const [unreadCount,        setUnreadCount]         = useState(0)
  const [showNotifications,  setShowNotifications]   = useState(false)

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await apiGetNotifications()
      setNotifications(res.data?.data ?? [])
      setUnreadCount(res.data?.meta?.unread_count ?? 0)
    } catch (_) { /* silent */ }
  }, [])

  useEffect(() => { fetchNotifications() }, [fetchNotifications])

  const handleMarkRead = useCallback(async (id) => {
    try {
      await apiMarkRead(id)
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
      setUnreadCount(prev => Math.max(0, prev - 1))
    } catch (_) {}
  }, [])

  const handleMarkAllRead = useCallback(async () => {
    try {
      await apiMarkAllRead()
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
      setUnreadCount(0)
    } catch (_) {}
  }, [])

  // ── watchlist ─────────────────────────────────────────────────────────────────
  const [watchlist,       setWatchlist]       = useState([])
  const [showWatchlist,   setShowWatchlist]   = useState(false)
  const [trackLoading,    setTrackLoading]    = useState(false)

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await apiGetWatchlist()
      setWatchlist(res.data?.data ?? [])
    } catch (_) {}
  }, [])

  useEffect(() => { fetchWatchlist() }, [fetchWatchlist])

  // Derive whether the currently-open drawer symbol is tracked
  const trackedEntry = useMemo(() => {
    if (!selected) return null
    return watchlist.find(e =>
      e.symbol === selected.symbol &&
      e.htf    === (selected.timeframe ?? '') &&
      e.is_active
    ) ?? null
  }, [watchlist, selected])

  const handleTrack = useCallback(async () => {
    if (!selected || trackLoading) return
    setTrackLoading(true)
    try {
      await apiAddToWatchlist({
        symbol:       selected.symbol,
        scanner_name: 'Stop Hunter Pro',
        htf:          selected.timeframe ?? '1d',
        ltf:          selected.result_data?.ltf_timeframe ?? null,
      })
      await fetchWatchlist()
    } catch (err) {
      const code = err.response?.data?.error_code
      if (code !== 'ALREADY_TRACKED') showToast('Could not add to watchlist.', 'error')
      else await fetchWatchlist()  // might have been added elsewhere — refresh
    } finally { setTrackLoading(false) }
  }, [selected, trackLoading, fetchWatchlist, showToast])

  const handleUntrack = useCallback(async () => {
    if (!trackedEntry || trackLoading) return
    setTrackLoading(true)
    try {
      await apiRemoveTracked(trackedEntry.id)
      setWatchlist(prev => prev.filter(e => e.id !== trackedEntry.id))
    } catch (_) { showToast('Could not remove from watchlist.', 'error') }
    finally { setTrackLoading(false) }
  }, [trackedEntry, trackLoading, showToast])

  const handleWatchlistRemove = useCallback(async (id) => {
    try {
      await apiRemoveTracked(id)
      setWatchlist(prev => prev.filter(e => e.id !== id))
    } catch (_) { showToast('Could not remove from watchlist.', 'error') }
  }, [showToast])

  const handleWatchlistUpdateNote = useCallback(async (id, note) => {
    try {
      const res = await apiUpdateTracked(id, { note })
      const updated = res.data?.data
      if (updated) setWatchlist(prev => prev.map(e => e.id === id ? updated : e))
    } catch (_) { showToast('Could not update note.', 'error') }
  }, [showToast])

  const handleWatchlistUpdateAlertPref = useCallback(async (id, prefs) => {
    // Optimistic: apply toggle locally immediately
    setWatchlist(prev => prev.map(e => {
      if (e.id !== id) return e
      return { ...e, alert_prefs: { ...(e.alert_prefs ?? {}), ...prefs } }
    }))
    try {
      const res = await apiUpdateTracked(id, prefs)
      const updated = res.data?.data
      if (updated) setWatchlist(prev => prev.map(e => e.id === id ? updated : e))
    } catch (_) {
      // Revert on error — re-fetch
      showToast('Could not update alert preference.', 'error')
      fetchWatchlist()
    }
  }, [showToast, fetchWatchlist])

  // ── email alert settings ──────────────────────────────────────────────────────
  const [alertSettings,     setAlertSettings]     = useState(null)   // null = not loaded

  const fetchAlertSettings = useCallback(async () => {
    try {
      const res = await apiGetAlertSettings()
      setAlertSettings(res.data?.data ?? null)
    } catch (_) {}
  }, [])

  useEffect(() => { fetchAlertSettings() }, [fetchAlertSettings])

  const handleSaveAlertSettings = useCallback(async (patch) => {
    try {
      const res = await apiUpdateAlertSettings(patch)
      const updated = res.data?.data
      if (updated) setAlertSettings(updated)
      return true
    } catch (err) {
      const msg = err.response?.data?.message ?? 'Could not save alert settings.'
      showToast(msg, 'error')
      return false
    }
  }, [showToast])

  // ── scan history ─────────────────────────────────────────────────────────────
  const [recentScans,     setRecentScans]     = useState([])
  const [historicalScan,  setHistoricalScan]  = useState(null)   // null = live results
  const [histLoading,     setHistLoading]     = useState(false)
  const [showRecent,      setShowRecent]      = useState(false)

  const fetchRecentScans = useCallback(async () => {
    try {
      const res = await apiRecentScanRuns()
      setRecentScans(res.data?.data ?? [])
    } catch (_) { /* silently ignore */ }
  }, [])

  useEffect(() => { fetchRecentScans() }, [fetchRecentScans])

  const loadHistoricalScan = useCallback(async (run) => {
    setHistLoading(true)
    try {
      const res   = await apiScanRunResults(run.id)
      const items = res.data?.data ?? []
      setResults(items)
      setHistoricalScan(run)
      setScanHealth(run.scan_health ?? null)
      setActiveChip('all')
      setActiveClassTab('all')
      setSelected(null)
      setAccessError(null)
      setApiError(null)
    } catch (err) {
      showToast('Could not load historical scan results.', 'error')
    } finally { setHistLoading(false) }
  }, [showToast])

  const clearHistoricalScan = useCallback(() => {
    setHistoricalScan(null)
    setResults(null)
    setJobInfo(null)
    setScanHealth(null)
  }, [])

  // ── preset helpers ───────────────────────────────────────────────────────────
  function applyPreset(preset) {
    setStrict(preset)
    if (preset === 'strict') {
      setRequireFvg(true); setMinScore(70); setIncludeNearMiss(false)
    } else {
      setRequireFvg(false); setMinScore(40); setIncludeNearMiss(true)
    }
  }

  // ── result derivation ───────────────────────────────────────────────────────
  // Helper: resolve classification from either v3 or v2 field name
  const getCl = r => r.result_data?.classification ?? r.result_data?.setup_status

  // Base rows: direction + search filtered (used for tab counts AND visible rows)
  const baseRows = useMemo(() => {
    let rows = results ?? []
    if (dirFilter === 'bull') rows = rows.filter(r => r.direction === 'bullish')
    if (dirFilter === 'bear') rows = rows.filter(r => r.direction === 'bearish')
    if (symbolSearch.trim()) {
      const q = symbolSearch.trim().toUpperCase()
      rows = rows.filter(r => (r.symbol ?? '').toUpperCase().includes(q))
    }
    return rows
  }, [results, dirFilter, symbolSearch])

  // Classification tab counts (from baseRows, before chip filter)
  const classTabCounts = useMemo(() => {
    const counts = { all: baseRows.length, confirmed: 0, watchlist: 0, near_miss: 0, rejected: 0 }
    for (const r of baseRows) {
      const cl = getCl(r)
      if (cl === 'confirmed' || cl === 'valid_setup')   counts.confirmed++
      else if (cl === 'watchlist' || cl === 'partial_setup') counts.watchlist++
      else if (cl === 'near_miss')                           counts.near_miss++
      else if (cl === 'rejected' || cl === 'no_setup')       counts.rejected++
    }
    return counts
  }, [baseRows])

  const visibleResults = useMemo(() => {
    let rows = baseRows
    // classification tab filter
    if (activeClassTab === 'confirmed') rows = rows.filter(r => { const cl=getCl(r); return cl==='confirmed'||cl==='valid_setup' })
    else if (activeClassTab === 'watchlist') rows = rows.filter(r => { const cl=getCl(r); return cl==='watchlist'||cl==='partial_setup' })
    else if (activeClassTab === 'near_miss') rows = rows.filter(r => getCl(r)==='near_miss')
    else if (activeClassTab === 'rejected')  rows = rows.filter(r => { const cl=getCl(r); return cl==='rejected'||cl==='no_setup' })
    // chip filter (sub-filter within the tab)
    rows = applyChip(rows, activeChip)
    // sort
    rows = applySort(rows, sortOrder)
    return rows
  }, [baseRows, activeClassTab, activeChip, sortOrder])

  // chip count helper (counts within the current tab, before chip filter)
  const chipCount = useMemo(() => {
    let tabRows = baseRows
    if (activeClassTab === 'confirmed') tabRows = baseRows.filter(r => { const cl=getCl(r); return cl==='confirmed'||cl==='valid_setup' })
    else if (activeClassTab === 'watchlist') tabRows = baseRows.filter(r => { const cl=getCl(r); return cl==='watchlist'||cl==='partial_setup' })
    else if (activeClassTab === 'near_miss') tabRows = baseRows.filter(r => getCl(r)==='near_miss')
    else if (activeClassTab === 'rejected')  tabRows = baseRows.filter(r => { const cl=getCl(r); return cl==='rejected'||cl==='no_setup' })
    return Object.fromEntries(FILTER_CHIPS.map(c => [c.id, applyChip(tabRows, c.id).length]))
  }, [baseRows, activeClassTab])

  // ── run scan ────────────────────────────────────────────────────────────────
  const runScan = useCallback(async () => {
    if (scanning) return
    if (sourceTab === 'custom') { showToast('Custom symbol scan coming soon.', 'info'); return }
    if (marketType === 'all')   { showToast('All markets filter coming soon.', 'info'); return }

    setScanning(true); setJobInfo(null); setResults(null); setScanHealth(null)
    setAccessError(null); setApiError(null); setSelected(null)
    setActiveChip('all'); setActiveClassTab('all')

    try {
      const payload = {
        universe, timeframe, mode,
        filters: mode === 'live' ? {
          min_score:         minScore,
          include_near_miss: includeNearMiss,
          require_fvg:       requireFvg,
          max_setup_age:     maxSetupAge,
          max_liquidity_age: maxLiqAge,
          // Phase 1
          scan_mode:           scanMode,
          use_eqh_eql:         useEqhEql,
          use_session_levels:  useSessionLvls,
          min_body_pct:        minBodyPct / 100,
          min_fvg_atr:         minFvgAtr  / 100,
          // Phase 2
          candidate_mode:        candidateMode,
          max_sweep_candidates:  5,
        } : {},
      }
      const startRes = await apiStartScan(payload)
      const job = startRes.data?.data
      setJobInfo(job)
      setScanHealth(job?.scan_health ?? null)
      if (!job?.job_id) throw new Error('No job_id returned.')

      const resRes = await apiGetResults(job.job_id)
      const items  = resRes.data?.data ?? []
      setResults(items)
      setHistoricalScan(null)
      showToast(`Scan complete — ${items.length} setup${items.length !== 1 ? 's' : ''} found.`, 'success')
      fetchRecentScans()
      fetchNotifications()
    } catch (err) {
      const errCode = err.response?.data?.error_code
      const errMsg  = err.response?.data?.message ?? 'Scan failed. Please try again.'
      if (ACCESS_ERRORS.has(errCode)) setAccessError(errMsg)
      else if (err.response?.status === 503) showToast('Live data unavailable. Try again shortly.', 'info')
      else { setApiError(errMsg); showToast(errMsg, 'error') }
    } finally { setScanning(false) }
  }, [scanning, sourceTab, marketType, universe, timeframe, mode, minScore, includeNearMiss, requireFvg, maxSetupAge, maxLiqAge, scanMode, useEqhEql, useSessionLvls, minBodyPct, minFvgAtr, candidateMode, showToast, fetchRecentScans, fetchNotifications])

  // ── render ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight:'100vh', background:T.bg, color:T.text, fontFamily:'Inter,ui-sans-serif,sans-serif' }}>
      <style>{`
        @keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
        .r-hover:hover{background:rgba(179,197,255,0.035)!important;}
        .r-hover{transition:background 0.13s;cursor:pointer;}
        ::-webkit-scrollbar{width:5px;height:5px}
        ::-webkit-scrollbar-track{background:#10131c}
        ::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.11);border-radius:3px}
        select option{background:#10131c}
        input[type=range]{-webkit-appearance:none;height:3px;border-radius:2px;outline:none;}
        input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;cursor:pointer;}
      `}</style>

      {/* ── sticky nav ── */}
      <nav style={{ position:'sticky', top:0, zIndex:50, background:'rgba(5,8,16,0.9)', backdropFilter:'blur(20px)', borderBottom:`1px solid ${T.border}`, padding:'0 20px', height:'56px', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'12px' }}>
          <button onClick={() => navigate('/dashboard')} style={{ display:'flex', alignItems:'center', gap:'5px', background:'rgba(255,255,255,0.05)', border:`1px solid ${T.border}`, borderRadius:'7px', padding:'5px 12px', color:T.muted, fontSize:'12px', cursor:'pointer' }}>
            ← Dashboard
          </button>
          <div style={{ width:'1px', height:'18px', background:T.border }} />
          <div>
            <div style={{ fontSize:'14px', fontWeight:700, color:T.text, letterSpacing:'-0.01em' }}>Stop Hunter Pro</div>
            <div style={{ fontSize:'10px', color:T.muted }}>NSE · Institutional stop-hunt scanner</div>
          </div>
          <div style={{ width:'1px', height:'18px', background:T.border }} />
          <button onClick={() => navigate('/scanner/max-pain')} style={{ display:'flex', alignItems:'center', gap:'5px', background:'rgba(124,58,237,0.12)', border:'1px solid rgba(124,58,237,0.3)', borderRadius:'7px', padding:'5px 12px', color:'#a78bfa', fontSize:'12px', cursor:'pointer', fontWeight:600 }}>
            ⚡ Max Pain Scanner
          </button>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
          {results?.length > 0 && (
            <button onClick={() => exportCSV(visibleResults, showToast)} style={{ padding:'5px 12px', borderRadius:'7px', background:'rgba(255,255,255,0.05)', border:`1px solid ${T.border}`, color:T.muted, fontSize:'11px', fontWeight:600, cursor:'pointer' }}>
              ⬇ Export CSV
            </button>
          )}
          {/* Watchlist button */}
          <button
            onClick={() => { setShowWatchlist(v => !v); setShowNotifications(false) }}
            title="Watchlist"
            style={{ position:'relative', padding:'5px 10px', borderRadius:'7px', background: showWatchlist ? 'rgba(0,241,254,0.12)' : 'rgba(255,255,255,0.05)', border:`1px solid ${showWatchlist ? 'rgba(0,241,254,0.3)' : T.border}`, color: showWatchlist ? T.cyan : T.muted, fontSize:'14px', cursor:'pointer', lineHeight:1, display:'flex', alignItems:'center', gap:'4px' }}>
            📋
            {watchlist.length > 0 && (
              <span style={{ fontSize:'10px', fontWeight:700, color: showWatchlist ? T.cyan : T.muted2 }}>{watchlist.length}</span>
            )}
          </button>

          {/* Notifications bell */}
          <button
            onClick={() => { setShowNotifications(v => !v); setShowWatchlist(false) }}
            title="Notifications"
            style={{ position:'relative', padding:'5px 10px', borderRadius:'7px', background: showNotifications ? 'rgba(0,102,255,0.15)' : 'rgba(255,255,255,0.05)', border:`1px solid ${showNotifications ? 'rgba(0,102,255,0.3)' : T.border}`, color:T.muted, fontSize:'16px', cursor:'pointer', lineHeight:1, display:'flex', alignItems:'center' }}
          >
            🔔
            {unreadCount > 0 && (
              <span style={{ position:'absolute', top:'-4px', right:'-4px', minWidth:'16px', height:'16px', borderRadius:'8px', background:'#0066ff', color:'#fff', fontSize:'9px', fontWeight:800, display:'flex', alignItems:'center', justifyContent:'center', padding:'0 3px', border:'1.5px solid #050810' }}>
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            )}
          </button>
          <div style={{ display:'inline-flex', alignItems:'center', gap:'5px', padding:'3px 11px', borderRadius:'20px', background:T.cyanDim, border:'1px solid rgba(0,241,254,0.2)', fontSize:'11px', fontWeight:600, color:T.cyan }}>
            ⚡ LIVE TOOL
          </div>
        </div>
      </nav>

      {/* ── body ── */}
      <div style={{ maxWidth:'1240px', margin:'0 auto', padding:'20px 20px 80px' }}>

        {/* ════ TOOLBAR ════ */}
        <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ marginBottom:'16px' }}>
          <div style={{ background:T.surface, border:`1px solid ${T.border}`, borderRadius:'14px', padding:'18px 20px' }}>

            {/* Row 1: source / market / universe / search / direction */}
            <div style={{ display:'flex', flexWrap:'wrap', gap:'10px', alignItems:'center', marginBottom:'14px' }}>

              {/* Source tabs */}
              <SegGroup
                options={[{value:'universe',label:'Universe'},{value:'custom',label:'Custom Symbol'}]}
                value={sourceTab} onChange={setSourceTab}
              />

              {/* Market toggle */}
              <SegGroup
                options={[{value:'stocks',label:'Stocks'},{value:'all',label:'All'}]}
                value={marketType} onChange={setMarketType}
              />

              {/* Universe dropdown */}
              <div style={{ position:'relative' }}>
                <select
                  value={universe} onChange={e => setUniverse(e.target.value)}
                  style={{ background:'rgba(0,102,255,0.1)', border:`1px solid rgba(0,102,255,0.25)`, borderRadius:'8px', color:T.text, fontSize:'13px', padding:'7px 32px 7px 12px', cursor:'pointer', outline:'none', appearance:'none', minWidth:'160px',
                    backgroundImage:`url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' fill='%238c90a1' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14L2.451 5.658C1.885 5.013 2.345 4 3.204 4h9.592a1 1 0 0 1 .753 1.659l-4.796 5.48a1 1 0 0 1-1.506 0z'/%3E%3C/svg%3E")`,
                    backgroundRepeat:'no-repeat', backgroundPosition:'right 10px center',
                  }}
                >
                  {UNIVERSE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>

              {/* Symbol search */}
              <div style={{ position:'relative', flex:'1 1 160px', minWidth:'120px' }}>
                <span style={{ position:'absolute', left:'10px', top:'50%', transform:'translateY(-50%)', color:T.muted, fontSize:'12px', pointerEvents:'none' }}>🔍</span>
                <input
                  type="text" placeholder="Filter symbol…" value={symbolSearch}
                  onChange={e => setSymbolSearch(e.target.value)}
                  style={{ width:'100%', boxSizing:'border-box', paddingLeft:'30px', paddingRight:'10px', paddingTop:'7px', paddingBottom:'7px', background:'rgba(255,255,255,0.04)', border:`1px solid ${T.border}`, borderRadius:'8px', color:T.text, fontSize:'12px', outline:'none' }}
                />
              </div>

              {/* Direction */}
              <SegGroup
                options={[{value:'both',label:'Both'},{value:'bull',label:'▲ Bull'},{value:'bear',label:'▼ Bear'}]}
                value={dirFilter} onChange={setDirFilter} accentActive={T.bullish}
              />
            </div>

            {/* Row 2: timeframe / mode / strict-relaxed / scan / export */}
            <div style={{ display:'flex', flexWrap:'wrap', gap:'10px', alignItems:'center' }}>

              {/* Timeframes */}
              <div style={{ display:'flex', gap:'5px' }}>
                {TIMEFRAMES.map(tf => <TFButton key={tf} tf={tf} active={timeframe===tf} onClick={() => setTimeframe(tf)} />)}
              </div>

              <div style={{ width:'1px', height:'22px', background:T.border }} />

              {/* Mode */}
              <SegGroup
                options={[{value:'mock',label:'Mock'},{value:'live',label:'⚡ Live'}]}
                value={mode} onChange={setMode} accentActive={T.cyan}
              />

              {/* Strict / Relaxed */}
              <div style={{ display:'flex', gap:'5px' }}>
                {[{id:'strict',label:'Strict',color:T.bullish},{id:'relaxed',label:'Relaxed',color:T.amber}].map(p => (
                  <button key={p.id} onClick={() => applyPreset(p.id)} style={{
                    padding:'6px 13px', borderRadius:'7px', border:`1px solid ${strict===p.id?p.color:T.border}`,
                    background:strict===p.id?`${p.color}18`:'transparent',
                    color:strict===p.id?p.color:T.muted, fontSize:'12px', fontWeight:600, cursor:'pointer', transition:'all 0.15s',
                  }}>{p.label}</button>
                ))}
              </div>

              <div style={{ flex:'1 0 0' }} />

              {/* Scan button */}
              <button onClick={runScan} disabled={scanning} style={{
                padding:'9px 22px', borderRadius:'9px',
                background:scanning?'rgba(0,102,255,0.4)':`linear-gradient(90deg,${T.primary},#005ce6)`,
                border:'none', color:'#fff', fontSize:'13px', fontWeight:700,
                cursor:scanning?'not-allowed':'pointer', letterSpacing:'0.04em',
                boxShadow:scanning?'none':'0 0 18px rgba(0,102,255,0.4)', transition:'box-shadow 0.2s',
                whiteSpace:'nowrap',
              }}>
                {scanning ? '⏳ Scanning…' : '▶ Start Scan'}
              </button>
            </div>

            {/* Live mode extra filters */}
            {mode === 'live' && (
              <div style={{ marginTop:'14px', paddingTop:'14px', borderTop:`1px solid ${T.border}` }}>
                <div style={{ fontSize:'10px', fontWeight:700, letterSpacing:'0.09em', textTransform:'uppercase', color:T.cyan, marginBottom:'12px' }}>⚡ Live Filters</div>
                <div style={{ display:'flex', flexWrap:'wrap', gap:'14px', alignItems:'center' }}>

                  {/* min score inline */}
                  <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                    <span style={{ fontSize:'11px', color:T.muted, whiteSpace:'nowrap' }}>Min Score</span>
                    <input type="range" min={0} max={100} step={5} value={minScore} onChange={e => {setMinScore(Number(e.target.value));setStrict(null)}}
                      style={{ width:'100px', accentColor:T.primary }} />
                    <span style={{ fontSize:'12px', fontWeight:700, color:T.purple, minWidth:'26px' }}>{minScore}</span>
                  </div>

                  {/* max setup age */}
                  <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                    <span style={{ fontSize:'11px', color:T.muted, whiteSpace:'nowrap' }}>Max Age</span>
                    <input type="range" min={5} max={50} step={5} value={maxSetupAge} onChange={e => setMaxSetupAge(Number(e.target.value))}
                      style={{ width:'80px', accentColor:T.cyan }} />
                    <span style={{ fontSize:'12px', fontWeight:700, color:T.purple, minWidth:'30px' }}>{maxSetupAge}b</span>
                  </div>

                  {/* max liq age */}
                  <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                    <span style={{ fontSize:'11px', color:T.muted, whiteSpace:'nowrap' }}>Liq. Age</span>
                    <input type="range" min={20} max={150} step={10} value={maxLiqAge} onChange={e => setMaxLiqAge(Number(e.target.value))}
                      style={{ width:'80px', accentColor:T.cyan }} />
                    <span style={{ fontSize:'12px', fontWeight:700, color:T.purple, minWidth:'36px' }}>{maxLiqAge}b</span>
                  </div>

                  {/* toggles */}
                  {[
                    {label:'Near Miss',     val:includeNearMiss, set:v=>{setIncludeNearMiss(v);setStrict(null)}},
                    {label:'Req. FVG',      val:requireFvg,      set:v=>{setRequireFvg(v);setStrict(null)}},
                    {label:'EQH/EQL',       val:useEqhEql,       set:setUseEqhEql,       title:'Use equal-high/low liquidity clusters'},
                    {label:'Session Lvls',  val:useSessionLvls,  set:setUseSessionLvls,  title:'Use prev-day/week high-low as liquidity'},
                  ].map(t => (
                    <button key={t.label} onClick={() => t.set(!t.val)} title={t.title} style={{
                      display:'flex', alignItems:'center', gap:'7px', padding:'5px 11px',
                      background:t.val?T.cyanDim:'rgba(255,255,255,0.04)', border:`1px solid ${t.val?'rgba(0,241,254,0.3)':T.border}`,
                      borderRadius:'7px', cursor:'pointer', color:t.val?T.cyan:T.muted, fontSize:'11px', fontWeight:600, transition:'all 0.15s',
                    }}>
                      <span style={{ width:'24px', height:'13px', borderRadius:'7px', background:t.val?T.primary:'rgba(255,255,255,0.1)', position:'relative', flexShrink:0 }}>
                        <span style={{ position:'absolute', top:'2px', left:t.val?'13px':'2px', width:'9px', height:'9px', borderRadius:'50%', background:'#fff', transition:'left 0.15s' }} />
                      </span>
                      {t.label}
                    </button>
                  ))}

                  {/* Phase 1: Scan mode + quality sliders */}
                  <div style={{ display:'flex', alignItems:'center', gap:'5px', padding:'4px 10px', borderRadius:'7px', background:'rgba(255,255,255,0.04)', border:`1px solid ${T.border}` }}>
                    <span style={{ fontSize:'10px', color:T.muted, fontWeight:600, textTransform:'uppercase', letterSpacing:'0.05em' }}>Mode</span>
                    {['present','historical'].map(m => (
                      <button key={m} onClick={() => setScanMode(m)} style={{
                        padding:'3px 9px', borderRadius:'5px', border:'none', cursor:'pointer', fontSize:'10px', fontWeight:700,
                        background: scanMode===m ? T.cyanDim : 'transparent',
                        color: scanMode===m ? T.cyan : T.muted2,
                        boxShadow: scanMode===m ? `inset 0 0 0 1px rgba(0,241,254,0.3)` : 'none',
                        transition:'all 0.13s',
                      }}>{m === 'present' ? '⦿ Present' : '⊙ Historical'}</button>
                    ))}
                  </div>

                  <div style={{ display:'flex', alignItems:'center', gap:'8px' }} title="Minimum displacement candle body% of full range">
                    <span style={{ fontSize:'11px', color:T.muted, whiteSpace:'nowrap' }}>Disp Body</span>
                    <input type="range" min={30} max={90} step={5} value={minBodyPct} onChange={e => setMinBodyPct(Number(e.target.value))}
                      style={{ width:'70px', accentColor:T.amber }} />
                    <span style={{ fontSize:'12px', fontWeight:700, color:T.amber, minWidth:'30px' }}>{minBodyPct}%</span>
                  </div>

                  <div style={{ display:'flex', alignItems:'center', gap:'8px' }} title="Minimum FVG size as % of ATR">
                    <span style={{ fontSize:'11px', color:T.muted, whiteSpace:'nowrap' }}>FVG Size</span>
                    <input type="range" min={5} max={50} step={5} value={minFvgAtr} onChange={e => setMinFvgAtr(Number(e.target.value))}
                      style={{ width:'70px', accentColor:T.purple }} />
                    <span style={{ fontSize:'12px', fontWeight:700, color:T.purple, minWidth:'36px' }}>{minFvgAtr}%×ATR</span>
                  </div>

                  {/* Candidate Mode */}
                  <div style={{ display:'flex', alignItems:'center', gap:'8px' }} title="Fast: stops at first actionable sweep. Best Setup: evaluates top 5 candidates and picks highest quality.">
                    <span style={{ fontSize:'11px', color:T.muted, whiteSpace:'nowrap' }}>Candidates</span>
                    {['fast','best_setup'].map(m => (
                      <button key={m} onClick={() => setCandidateMode(m)} style={{
                        padding:'3px 9px', borderRadius:'5px', border:'none', cursor:'pointer', fontSize:'10px', fontWeight:700,
                        background: candidateMode===m ? 'rgba(0,241,254,0.15)' : 'transparent',
                        color: candidateMode===m ? T.cyan : T.muted2,
                        boxShadow: candidateMode===m ? `inset 0 0 0 1px rgba(0,241,254,0.3)` : 'none',
                        transition:'all 0.13s',
                      }}>{m === 'fast' ? '⚡ Fast' : '🔍 Best Setup'}</button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* job status strip */}
            {jobInfo && (
              <div style={{ marginTop:'14px', padding:'9px 13px', background:T.primaryDim, border:'1px solid rgba(0,102,255,0.2)', borderRadius:'9px', display:'flex', gap:'18px', alignItems:'center', flexWrap:'wrap' }}>
                <StatusBadge status={jobInfo.status} />
                <span style={{ fontSize:'12px', color:T.muted }}>Universe: <b style={{ color:T.text }}>{jobInfo.universe}</b></span>
                <span style={{ fontSize:'12px', color:T.muted }}>TF: <b style={{ color:T.text }}>{jobInfo.timeframe}</b></span>
                <span style={{ fontSize:'12px', color:T.muted }}>Scanned: <b style={{ color:T.text }}>{jobInfo.completed_symbols}/{jobInfo.total_symbols}</b></span>
                {jobInfo.mode && <span style={{ fontSize:'12px', color:T.muted }}>Mode: <b style={{ color:T.cyan }}>{jobInfo.mode}</b></span>}
              </div>
            )}
          </div>
        </motion.div>

        {/* ════ HISTORICAL SCAN BANNER ════ */}
        {historicalScan && (
          <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ marginBottom:'12px' }}>
            <div style={{
              display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:'8px',
              padding:'10px 16px', borderRadius:'10px',
              background:'rgba(179,197,255,0.07)', border:'1px solid rgba(179,197,255,0.2)',
            }}>
              <div style={{ display:'flex', alignItems:'center', gap:'10px', flexWrap:'wrap' }}>
                <span style={{ fontSize:'10px', fontWeight:700, letterSpacing:'0.07em', textTransform:'uppercase', color:T.purple }}>⏱ Historical Scan</span>
                <span style={{ fontSize:'12px', color:T.text }}>
                  {new Date(historicalScan.created_at).toLocaleString('en-IN', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' })}
                </span>
                <span style={{ fontSize:'11px', color:T.muted }}>
                  {historicalScan.universe} · {historicalScan.timeframe}{historicalScan.ltf ? `/${historicalScan.ltf}` : ''} · {historicalScan.scanner_name ?? 'stop-hunter-pro'}
                </span>
                <span style={{ fontSize:'11px', color:T.muted }}>
                  <b style={{ color:T.bullish }}>{historicalScan.confirmed_count ?? '?'}</b> confirmed ·{' '}
                  <b style={{ color:T.cyan }}>{historicalScan.watchlist_count ?? '?'}</b> watchlist ·{' '}
                  <b style={{ color:T.amber }}>{historicalScan.near_miss_count ?? '?'}</b> near miss
                </span>
              </div>
              <button
                onClick={clearHistoricalScan}
                style={{ padding:'5px 14px', borderRadius:'7px', border:`1px solid ${T.border}`, background:'rgba(255,255,255,0.06)', color:T.muted, fontSize:'11px', fontWeight:600, cursor:'pointer' }}
              >
                ← Back to Live Results
              </button>
            </div>
          </motion.div>
        )}

        {/* ════ RECENT SCANS PANEL ════ */}
        {recentScans.length > 0 && (
          <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ marginBottom:'14px' }}>
            <div style={{ background:T.surface, border:`1px solid ${T.border}`, borderRadius:'12px', overflow:'hidden' }}>

              {/* Header / toggle */}
              <button
                onClick={() => setShowRecent(v => !v)}
                style={{
                  width:'100%', display:'flex', alignItems:'center', justifyContent:'space-between',
                  padding:'11px 16px', background:'transparent', border:'none', cursor:'pointer',
                  borderBottom: showRecent ? `1px solid ${T.border}` : 'none',
                }}
              >
                <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
                  <span style={{ fontSize:'10px', fontWeight:700, letterSpacing:'0.09em', textTransform:'uppercase', color:T.muted }}>🕐 Recent Scans</span>
                  <span style={{ fontSize:'10px', padding:'1px 7px', borderRadius:'10px', background:'rgba(255,255,255,0.06)', color:T.muted2, fontWeight:600 }}>{recentScans.length}</span>
                </div>
                <span style={{ color:T.muted2, fontSize:'12px' }}>{showRecent ? '▲' : '▼'}</span>
              </button>

              {showRecent && (
                <div style={{ overflowX:'auto' }}>
                  <table style={{ width:'100%', borderCollapse:'collapse', minWidth:'700px' }}>
                    <thead>
                      <tr style={{ borderBottom:`1px solid ${T.border}` }}>
                        {['Date & Time','Universe','Timeframe','Scanner','Confirmed','Watchlist','Near Miss','Fetch (s)','Quality',''].map(h => (
                          <th key={h} style={{ padding:'8px 12px', textAlign:'left', fontSize:'9px', fontWeight:700, letterSpacing:'0.07em', textTransform:'uppercase', color:T.muted2, whiteSpace:'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {recentScans.map((run, idx) => {
                        const isActive = historicalScan?.id === run.id
                        return (
                          <tr
                            key={run.id}
                            className="r-hover"
                            onClick={() => loadHistoricalScan(run)}
                            style={{
                              borderBottom: idx < recentScans.length - 1 ? `1px solid rgba(255,255,255,0.04)` : 'none',
                              background: isActive ? 'rgba(179,197,255,0.07)' : 'transparent',
                              opacity: histLoading ? 0.6 : 1,
                            }}
                          >
                            <td style={{ padding:'8px 12px', fontSize:'12px', color:T.text, whiteSpace:'nowrap' }}>
                              {new Date(run.created_at).toLocaleString('en-IN', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit' })}
                            </td>
                            <td style={{ padding:'8px 12px', fontSize:'11px', fontWeight:600, color:T.text }}>{run.universe ?? '—'}</td>
                            <td style={{ padding:'8px 12px', fontSize:'11px', color:T.cyan, fontWeight:600 }}>
                              {run.timeframe}{run.ltf ? <span style={{ color:T.muted }}>/{run.ltf}</span> : ''}
                            </td>
                            <td style={{ padding:'8px 12px', fontSize:'10px', color:T.muted }}>{run.scanner_name ?? 'stop-hunter-pro'}</td>
                            <td style={{ padding:'8px 12px', fontSize:'12px', fontWeight:700, color:T.bullish }}>{run.confirmed_count ?? '—'}</td>
                            <td style={{ padding:'8px 12px', fontSize:'12px', fontWeight:700, color:T.cyan }}>{run.watchlist_count ?? '—'}</td>
                            <td style={{ padding:'8px 12px', fontSize:'12px', fontWeight:700, color:T.amber }}>{run.near_miss_count ?? '—'}</td>
                            <td style={{ padding:'8px 12px', fontSize:'11px', color:T.muted }}>
                              {run.fetch_elapsed_s != null ? `${Number(run.fetch_elapsed_s).toFixed(1)}s` : '—'}
                            </td>
                            <td style={{ padding:'8px 12px' }}>
                              <div style={{ display:'flex', alignItems:'center', gap:'5px' }}>
                                <DataQualityBadge quality={run.data_quality} small />
                                {run.partial_scan && (
                                  <span title="Partial scan — some symbols failed" style={{ fontSize:'9px', color:T.amber }}>⚠</span>
                                )}
                              </div>
                            </td>
                            <td style={{ padding:'8px 12px' }}>
                              {isActive
                                ? <span style={{ fontSize:'10px', fontWeight:700, color:T.purple }}>VIEWING</span>
                                : <span style={{ fontSize:'10px', color:T.primary, fontWeight:600 }}>Load →</span>}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </motion.div>
        )}

        {/* ── access denied ── */}
        {accessError && <motion.div variants={fadeUp} initial="hidden" animate="show" style={{marginBottom:'16px'}}><AccessDenied message={accessError} /></motion.div>}

        {/* ── api error ── */}
        {apiError && !accessError && (
          <motion.div variants={fadeUp} initial="hidden" animate="show" style={{marginBottom:'16px'}}>
            <div style={{ background:T.bearishDim, border:'1px solid rgba(255,77,79,0.2)', borderRadius:'11px', padding:'14px 18px', color:T.bearish, fontSize:'13px' }}>{apiError}</div>
          </motion.div>
        )}

        {/* ════ RESULTS ════ */}
        <AnimatePresence>
          {results !== null && !accessError && (
            <motion.div key="results" variants={fadeUp} initial="hidden" animate="show" exit={{opacity:0}}>

              {/* ── scan health bar ── */}
              <ScanHealthBar health={scanHealth} />

              {/* ── classification tabs ── */}
              <ClassTabBar
                active={activeClassTab}
                counts={classTabCounts}
                onChange={tab => { setActiveClassTab(tab); setActiveChip('all') }}
                showRejected={debugMode}
              />

              {/* ── filter chips + sort + debug toggle ── */}
              <div style={{ marginBottom:'10px', display:'flex', gap:'6px', overflowX:'auto', paddingBottom:'4px', alignItems:'center' }}>
                {FILTER_CHIPS.map(chip => (
                  <FilterChip key={chip.id} chip={chip} active={activeChip===chip.id}
                    onClick={() => setActiveChip(chip.id)}
                    count={chipCount[chip.id]}
                  />
                ))}
                <div style={{ marginLeft:'auto', flexShrink:0, display:'flex', alignItems:'center', gap:'8px' }}>
                  {/* debug mode toggle */}
                  <button onClick={() => { setDebugMode(v => !v); if (activeClassTab==='rejected') setActiveClassTab('all') }}
                    title="Debug mode — shows rejected results and extra trace info"
                    style={{
                      display:'inline-flex', alignItems:'center', gap:'5px',
                      padding:'5px 10px', borderRadius:'7px', cursor:'pointer', fontSize:'11px', fontWeight:600,
                      background: debugMode ? T.bearishDim : 'rgba(255,255,255,0.04)',
                      border: `1px solid ${debugMode ? 'rgba(255,77,79,0.3)' : T.border}`,
                      color: debugMode ? T.bearish : T.muted, transition:'all 0.15s',
                    }}>
                    <span style={{ fontSize:'9px' }}>🔬</span> Debug
                    <span style={{ width:'20px', height:'11px', borderRadius:'6px', background:debugMode?T.bearish:'rgba(255,255,255,0.1)', position:'relative', flexShrink:0, display:'inline-block' }}>
                      <span style={{ position:'absolute', top:'1.5px', left:debugMode?'11px':'1.5px', width:'8px', height:'8px', borderRadius:'50%', background:'#fff', transition:'left 0.15s' }} />
                    </span>
                  </button>
                  <select value={sortOrder} onChange={e => setSortOrder(e.target.value)}
                    style={{ background:'rgba(255,255,255,0.04)', border:`1px solid ${T.border}`, borderRadius:'8px', color:T.muted, fontSize:'11px', padding:'5px 10px', cursor:'pointer', outline:'none' }}>
                    {SORT_OPTIONS.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
                  </select>
                </div>
              </div>

              {/* results meta */}
              <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'10px', gap:'8px' }}>
                <div style={{ fontSize:'11px', color:T.muted }}>
                  <b style={{ color:T.text }}>{visibleResults.length}</b> of {results.length} setups
                  {activeClassTab !== 'all' && <span> · tab: <b style={{ color: CLASS_TABS.find(t=>t.id===activeClassTab)?.color ?? T.cyan }}>{CLASS_TABS.find(t=>t.id===activeClassTab)?.label ?? activeClassTab}</b></span>}
                  {activeChip !== 'all' && <span> · filter: <b style={{ color:T.cyan }}>{FILTER_CHIPS.find(c=>c.id===activeChip)?.label}</b></span>}
                  {dirFilter !== 'both' && <span> · {dirFilter}</span>}
                </div>
                {debugMode && (
                  <span style={{ fontSize:'10px', padding:'2px 8px', borderRadius:'5px', background:T.bearishDim, border:'1px solid rgba(255,77,79,0.2)', color:T.bearish, fontWeight:600 }}>
                    🔬 DEBUG
                  </span>
                )}
              </div>

              {/* ── table ── */}
              <div style={{ background:T.surface, border:`1px solid ${T.border}`, borderRadius:'14px', overflow:'hidden' }}>
                {scanning ? (
                  <div style={{ padding:'20px', display:'flex', flexDirection:'column', gap:'10px' }}>
                    {[1,2,3,4].map(i => <Skeleton key={i} h="20px" />)}
                  </div>
                ) : visibleResults.length === 0 ? (
                  <div style={{ padding:'48px', textAlign:'center' }}>
                    <div style={{ fontSize:'32px', marginBottom:'12px' }}>
                      {activeClassTab === 'rejected' ? '🚫' : '🔍'}
                    </div>
                    <div style={{ fontSize:'15px', fontWeight:600, color:T.text, marginBottom:'5px' }}>
                      {activeClassTab === 'rejected'
                        ? 'No rejected results stored'
                        : results.length === 0 ? 'No setups found' : 'No matches for current filter'}
                    </div>
                    <div style={{ fontSize:'12px', color:T.muted, maxWidth:'340px', margin:'0 auto', lineHeight:1.6 }}>
                      {activeClassTab === 'rejected'
                        ? 'Rejected setups (score < 10 or no sweep) are dropped by the engine and never stored. They do not appear in scan results even in debug mode.'
                        : 'Try a different filter chip, tab, or universe.'}
                    </div>
                  </div>
                ) : (
                  <div style={{ overflowX:'auto' }}>
                    <table style={{ width:'100%', borderCollapse:'collapse', minWidth:'1100px' }}>
                      <thead>
                        <tr style={{ borderBottom:'1px solid rgba(255,255,255,0.06)' }}>
                          {['Symbol','Dir','Classification','Stage','Grade','Score','Entry','Stop Loss','T1','T2','Swp','ChoCH','FVG','Ret','Age',''].map(h => (
                            <th key={h} style={{ padding:'10px 12px', textAlign:'left', fontSize:'9px', fontWeight:700, letterSpacing:'0.07em', textTransform:'uppercase', color:T.muted, whiteSpace:'nowrap' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <motion.tbody variants={stagger} initial="hidden" animate="show">
                        {visibleResults.map((row, idx) => {
                          const rd    = row.result_data ?? {}
                          const cl    = rd.classification ?? rd.setup_status
                          const stage = getStage(row)
                          const rowBg = cl==='confirmed'||cl==='valid_setup' ? 'rgba(0,217,126,0.03)'
                                      : cl==='rejected'||cl==='no_setup'    ? 'rgba(255,77,79,0.025)'
                                      : 'transparent'
                          const rowOpacity = (cl==='rejected'||cl==='no_setup') ? 0.6 : 1
                          return (
                            <motion.tr key={row.id ?? idx} variants={fadeUp} className="r-hover"
                              onClick={() => setSelected(row)}
                              style={{ borderBottom:idx<visibleResults.length-1?'1px solid rgba(255,255,255,0.04)':'none', background:rowBg, opacity:rowOpacity }}
                            >
                              {/* Symbol */}
                              <td style={{ padding:'10px 12px', whiteSpace:'nowrap' }}>
                                <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
                                  <span style={{ fontSize:'13px', fontWeight:700, color:T.text, fontFamily:"'Space Grotesk',monospace" }}>{row.symbol}</span>
                                  <NSEBadge />
                                </div>
                                {rd.stale && <div style={{ marginTop:'2px' }}><StaleBadge small /></div>}
                                {cl === 'watchlist' && rd.watchlist_level && !rd.stale && (
                                  <div style={{ marginTop:'3px' }}>
                                    <span style={{
                                      fontSize:'9px', fontWeight:700, padding:'1px 6px', borderRadius:'10px',
                                      letterSpacing:'0.04em',
                                      background: rd.watchlist_level==='L4' ? 'rgba(0,217,126,0.12)'
                                               : rd.watchlist_level==='L3' ? 'rgba(0,241,254,0.10)'
                                               : rd.watchlist_level==='L2' ? 'rgba(245,158,11,0.12)'
                                               :                              'rgba(148,100,246,0.12)',
                                      color:      rd.watchlist_level==='L4' ? T.bullish
                                               : rd.watchlist_level==='L3' ? T.cyan
                                               : rd.watchlist_level==='L2' ? T.amber
                                               :                              T.purple,
                                    }}>{rd.watchlist_level}</span>
                                  </div>
                                )}
                              </td>

                              {/* Direction */}
                              <td style={{ padding:'10px 12px' }}>
                                <span style={{ fontSize:'11px', fontWeight:700, padding:'2px 8px', borderRadius:'20px', background:row.direction==='bullish'?T.bullishDim:T.bearishDim, color:dirColor(row.direction) }}>
                                  {row.direction==='bullish'?'▲':'▼'}
                                </span>
                              </td>

                              {/* Classification */}
                              <td style={{ padding:'10px 12px' }}><ClassificationBadge value={cl} small /></td>

                              {/* Stage + Quality Flags (max 2) + Progression pill */}
                              <td style={{ padding:'10px 12px' }}>
                                <span style={{ fontSize:'11px', fontWeight:600, color:stage.color }}>{stage.label}</span>
                                {Array.isArray(rd.quality_flags) && rd.quality_flags.length > 0 && (() => {
                                  const FLAG_COL = { severe:'#FF4D4F', warn:'#F59E0B', positive:'#00D97E', info:'#00F1FE' }
                                  const FLAG_BG  = { severe:'rgba(255,77,79,0.10)', warn:'rgba(245,158,11,0.10)',
                                                     positive:'rgba(0,217,126,0.10)', info:'rgba(0,241,254,0.08)' }
                                  // show max 2: priority severe > warn > positive > info
                                  const top2 = rd.quality_flags.slice(0, 2)
                                  return (
                                    <div style={{ display:'flex', gap:'4px', marginTop:'4px', flexWrap:'wrap' }}>
                                      {top2.map((f, fi) => (
                                        <span key={fi} title={f.detail} style={{
                                          fontSize:'9px', fontWeight:700, padding:'1px 5px', borderRadius:'8px',
                                          background: FLAG_BG[f.severity] ?? 'rgba(255,255,255,0.06)',
                                          color: FLAG_COL[f.severity] ?? '#aaa',
                                          letterSpacing:'0.02em', whiteSpace:'nowrap', cursor:'default',
                                        }}>{f.label}</span>
                                      ))}
                                    </div>
                                  )
                                })()}
                                {/* Progression pill — only for meaningful moves (|priority| ≥ 60) */}
                                {(() => {
                                  const prio  = row.progression_priority
                                  const label = row.progression_label
                                  if (!label || prio == null) return null
                                  const absPrio = Math.abs(prio)
                                  if (absPrio < 60) return null
                                  const positive = prio > 0
                                  const col = prio >= 100 ? T.bullish
                                            : prio >= 70  ? T.cyan
                                            : prio >= 60  ? T.purple
                                            : T.bearish
                                  return (
                                    <div style={{ marginTop:'4px' }}>
                                      <span style={{
                                        fontSize:'9px', fontWeight:700, padding:'1px 6px', borderRadius:'8px',
                                        background: `${col}18`, color: col,
                                        letterSpacing:'0.02em', whiteSpace:'nowrap',
                                      }}>
                                        {positive ? '▲' : '▼'} {label}
                                      </span>
                                    </div>
                                  )
                                })()}
                              </td>

                              {/* Grade */}
                              <td style={{ padding:'10px 12px' }}>
                                <span style={{ display:'inline-flex', alignItems:'center', justifyContent:'center', width:'28px', height:'28px', borderRadius:'7px', fontSize:'11px', fontWeight:800, background:`${gradeColor(row.grade)}20`, color:gradeColor(row.grade), border:`1px solid ${gradeColor(row.grade)}38` }}>
                                  {row.grade}
                                </span>
                              </td>

                              {/* Score */}
                              <td style={{ padding:'10px 12px' }}>
                                <div style={{ display:'flex', alignItems:'center', gap:'7px' }}>
                                  <div style={{ width:'40px', height:'3px', borderRadius:'2px', background:'rgba(255,255,255,0.07)' }}>
                                    <div style={{ width:`${row.score??0}%`, height:'100%', background:gradeColor(row.grade), borderRadius:'2px' }} />
                                  </div>
                                  <span style={{ fontSize:'12px', fontWeight:700, color:T.purple }}>{row.score?.toFixed(1)??'—'}</span>
                                </div>
                              </td>

                              {/* Entry */}
                              <td style={{ padding:'10px 12px', fontSize:'12px', fontWeight:600, color:T.text, fontFamily:"'Space Mono',monospace" }}>
                                {rd.entry != null ? `₹${Number(rd.entry).toLocaleString('en-IN',{minimumFractionDigits:1,maximumFractionDigits:1})}` : '—'}
                              </td>

                              {/* Stop Loss */}
                              <td style={{ padding:'10px 12px', fontSize:'12px', fontWeight:600, color:T.bearish, fontFamily:"'Space Mono',monospace" }}>
                                {rd.stop_loss != null ? `₹${Number(rd.stop_loss).toLocaleString('en-IN',{minimumFractionDigits:1,maximumFractionDigits:1})}` : '—'}
                              </td>

                              {/* T1 */}
                              <td style={{ padding:'10px 12px', fontSize:'12px', fontWeight:600, color:T.bullish, fontFamily:"'Space Mono',monospace" }}>
                                {rd.target_1 != null ? `₹${Number(rd.target_1).toLocaleString('en-IN',{minimumFractionDigits:1,maximumFractionDigits:1})}` : '—'}
                              </td>

                              {/* T2 */}
                              <td style={{ padding:'10px 12px', fontSize:'12px', fontWeight:600, color:T.bullish, fontFamily:"'Space Mono',monospace", opacity:0.7 }}>
                                {rd.target_2 != null ? `₹${Number(rd.target_2).toLocaleString('en-IN',{minimumFractionDigits:1,maximumFractionDigits:1})}` : '—'}
                              </td>

                              {/* Signal columns — compact */}
                              <td style={{ padding:'10px 8px', textAlign:'center' }}><CheckMark val={rd.sweep} /></td>
                              <td style={{ padding:'10px 8px', textAlign:'center' }}><CheckMark val={rd.choch} /></td>
                              <td style={{ padding:'10px 8px', textAlign:'center' }}><CheckMark val={rd.fvg} /></td>
                              <td style={{ padding:'10px 8px', textAlign:'center' }}>
                                {rd.retest
                                  ? <span style={{ fontSize:'10px', color:T.cyan, fontWeight:700 }}>✓</span>
                                  : <span style={{ color:T.muted2, fontSize:'11px' }}>—</span>}
                              </td>

                              {/* Age */}
                              <td style={{ padding:'10px 12px', fontSize:'11px', color:rd.stale?T.amber:rd.setup_age<=5?T.bullish:T.muted, fontWeight:600 }}>
                                {rd.setup_age != null ? `${rd.setup_age}b` : '—'}
                              </td>

                              {/* Action */}
                              <td style={{ padding:'10px 12px' }}>
                                <div style={{ display:'flex', gap:'5px', alignItems:'center' }}>
                                  <button onClick={e => { e.stopPropagation(); setSelected(row) }}
                                    style={{ padding:'4px 10px', borderRadius:'6px', background:T.purpleDim, border:'1px solid rgba(179,197,255,0.18)', color:T.purple, fontSize:'11px', fontWeight:600, cursor:'pointer', whiteSpace:'nowrap' }}>
                                    View
                                  </button>
                                  <a href={tvUrl(row.symbol)} target="_blank" rel="noopener noreferrer"
                                    onClick={e => e.stopPropagation()}
                                    style={{ padding:'4px 8px', borderRadius:'6px', background:'rgba(0,102,255,0.1)', border:'1px solid rgba(0,102,255,0.25)', color:T.primary, fontSize:'11px', fontWeight:600, textDecoration:'none', display:'inline-flex', alignItems:'center', gap:'3px' }}
                                    title="Open on TradingView">
                                    📈
                                  </a>
                                </div>
                              </td>
                            </motion.tr>
                          )
                        })}
                      </motion.tbody>
                    </table>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── idle state ── */}
        {results === null && !scanning && !accessError && !apiError && (
          <motion.div variants={fadeUp} initial="hidden" animate="show">
            <div style={{ background:T.surface, border:`1px solid ${T.border}`, borderRadius:'14px', padding:'56px', textAlign:'center' }}>
              <div style={{ fontSize:'42px', marginBottom:'16px' }}>⚡</div>
              <div style={{ fontSize:'17px', fontWeight:700, color:T.text, marginBottom:'7px' }}>Ready to hunt</div>
              <div style={{ fontSize:'13px', color:T.muted, lineHeight:1.7 }}>
                Select universe and timeframe · press <b style={{color:T.purple}}>Start Scan</b>
              </div>
              <div style={{ marginTop:'18px', display:'flex', justifyContent:'center', gap:'10px', flexWrap:'wrap' }}>
                {['Liquidity Sweep', 'ChoCH Confirmation', 'FVG Detection', 'Order Block', 'Retest Zones'].map(f => (
                  <span key={f} style={{ fontSize:'11px', padding:'4px 11px', borderRadius:'20px', background:T.cyanDim, color:T.cyan, fontWeight:600 }}>{f}</span>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </div>

      {/* ── detail drawer ── */}
      <AnimatePresence>
        {selected && (
          <DetailDrawer
            result={selected}
            onClose={() => setSelected(null)}
            trackedEntry={trackedEntry}
            onTrack={handleTrack}
            onUntrack={handleUntrack}
            trackLoading={trackLoading}
          />
        )}
      </AnimatePresence>

      {/* ── watchlist panel ── */}
      {showWatchlist && (
        <WatchlistPanel
          watchlist={watchlist}
          onRemove={handleWatchlistRemove}
          onUpdateNote={handleWatchlistUpdateNote}
          onUpdateAlertPref={handleWatchlistUpdateAlertPref}
          alertSettings={alertSettings}
          onSaveAlertSettings={handleSaveAlertSettings}
          onClose={() => setShowWatchlist(false)}
        />
      )}

      {/* ── notifications panel ── */}
      {showNotifications && (
        <NotificationsPanel
          notifications={notifications}
          unreadCount={unreadCount}
          onMarkRead={handleMarkRead}
          onMarkAllRead={handleMarkAllRead}
          onClose={() => setShowNotifications(false)}
        />
      )}
    </div>
  )
}
