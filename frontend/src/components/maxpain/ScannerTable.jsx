import { useState, useMemo, useCallback, useRef } from 'react'
import {
  ChevronUp, ChevronDown, ChevronsUpDown,
  TrendingUp, TrendingDown, ExternalLink, Copy, Star,
  BarChart2, Zap,
} from 'lucide-react'
import ConvictionBadge, { deriveConvictionBadges } from './ConvictionBadge'
import SignalExplanation from './SignalExplanation'

// ── Sort presets ─────────────────────────────────────────────────────────────
const SORT_PRESETS = [
  {
    id:    'reversal',
    label: 'Strongest Reversal',
    key:   'reversal_score',
    dir:   'desc',
    icon:  Zap,
  },
  {
    id:    'distance',
    label: 'Highest Deviation',
    key:   'distance_pct',
    dir:   'desc',
    icon:  BarChart2,
  },
  {
    id:    'expiry',
    label: 'Nearest Expiry',
    key:   'days_to_expiry',
    dir:   'asc',
    icon:  ChevronUp,
  },
  {
    id:    'iv',
    label: 'Highest ATM IV',
    key:   'atm_ce_iv',
    dir:   'desc',
    icon:  TrendingUp,
  },
  {
    id:    'pcr',
    label: 'PCR Extreme',
    // sort by |pcr - 1| desc — handled in sorted computation
    key:   '_pcr_imbalance',
    dir:   'desc',
    icon:  TrendingDown,
  },
]

// ── Column definitions ────────────────────────────────────────────────────────
const COLS = [
  { key: 'symbol',        label: 'Symbol',     sortable: true,  width: 'w-36' },
  { key: 'distance_pct',  label: 'Distance',   sortable: true,  width: 'w-28' },
  { key: 'spot_price',    label: 'Spot',       sortable: true,  width: 'w-28' },
  { key: 'max_pain',      label: 'Max Pain',   sortable: true,  width: 'w-28' },
  { key: 'pcr',           label: 'PCR',        sortable: true,  width: 'w-20' },
  { key: 'days_to_expiry',label: 'DTE',        sortable: true,  width: 'w-16' },
  { key: 'reversal_score',label: 'Signal',     sortable: true,  width: 'w-52' },
  { key: '_actions',      label: '',           sortable: false, width: 'w-20' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtINR(n) {
  if (n == null) return '—'
  return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function useDebounce(fn, delay) {
  const timer = useRef(null)
  return useCallback((...args) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => fn(...args), delay)
  }, [fn, delay])
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SortIcon({ colKey, sortKey, sortDir }) {
  if (colKey !== sortKey) return <ChevronsUpDown className="w-3 h-3 text-slate-600 ml-1 flex-shrink-0" />
  return sortDir === 'asc'
    ? <ChevronUp   className="w-3 h-3 text-violet-400 ml-1 flex-shrink-0" />
    : <ChevronDown className="w-3 h-3 text-violet-400 ml-1 flex-shrink-0" />
}

function DistanceBadge({ pct, level }) {
  const cls = level === 'extreme' ? 'text-red-400    bg-red-500/10    border-red-500/20'
    : level === 'high'     ? 'text-orange-400 bg-orange-500/10 border-orange-500/20'
    : level === 'moderate' ? 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20'
    : 'text-slate-400 bg-slate-700/30 border-slate-600/20'
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded border ${cls} font-mono`}>
      {pct?.toFixed(2)}%
    </span>
  )
}

function DirectionChip({ direction }) {
  return direction === 'bullish'
    ? <TrendingUp   className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
    : <TrendingDown className="w-3.5 h-3.5 text-rose-400    flex-shrink-0" />
}

function SignalBar({ score, color }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 bg-slate-800 rounded-full h-1.5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${score}%`, backgroundColor: color }}
        />
      </div>
      <span
        className="text-xs font-bold font-mono w-6 text-right flex-shrink-0"
        style={{ color }}
      >
        {score}
      </span>
    </div>
  )
}

function SkeletonRow({ cols }) {
  return (
    <tr className="border-b border-slate-800/50">
      {cols.map((_, i) => (
        <td key={i} className="px-4 py-3.5">
          <div
            className="h-3.5 bg-slate-800 rounded animate-pulse"
            style={{ width: `${45 + ((i * 37) % 50)}%`, animationDelay: `${i * 60}ms` }}
          />
        </td>
      ))}
    </tr>
  )
}

function RowActions({ row, onPin, pinned }) {
  const tvUrl = `https://www.tradingview.com/chart/?symbol=NSE:${row.symbol}`

  function handleCopy(e) {
    e.stopPropagation()
    navigator.clipboard?.writeText(row.symbol).catch(() => {})
  }

  function handleTV(e) {
    e.stopPropagation()
    window.open(tvUrl, '_blank', 'noopener')
  }

  function handlePin(e) {
    e.stopPropagation()
    onPin?.(row.symbol)
  }

  return (
    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        onClick={handleTV}
        title="Open in TradingView"
        className="p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-700/60 transition-colors"
      >
        <ExternalLink className="w-3 h-3" />
      </button>
      <button
        onClick={handleCopy}
        title="Copy symbol"
        className="p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-700/60 transition-colors"
      >
        <Copy className="w-3 h-3" />
      </button>
      <button
        onClick={handlePin}
        title={pinned ? 'Unpin' : 'Pin symbol'}
        className={`p-1 rounded transition-colors ${
          pinned
            ? 'text-amber-400 hover:text-amber-300'
            : 'text-slate-500 hover:text-slate-200 hover:bg-slate-700/60'
        }`}
      >
        <Star className="w-3 h-3" fill={pinned ? 'currentColor' : 'none'} />
      </button>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function ScannerTable({ data, loading, onRowClick }) {
  const [sortKey,    setSortKey]    = useState('reversal_score')
  const [sortDir,    setSortDir]    = useState('desc')
  const [filterRaw,  setFilterRaw]  = useState('')
  const [filter,     setFilter]     = useState('')
  const [preset,     setPreset]     = useState('reversal')
  const [pinned,     setPinned]     = useState(new Set())
  const [expanded,   setExpanded]   = useState(null)   // symbol with expanded explanation

  // Debounce filter input to avoid re-sorting on every keystroke
  const applyFilter = useCallback((val) => setFilter(val), [])
  const debouncedFilter = useDebounce(applyFilter, 180)

  function handleFilterChange(e) {
    setFilterRaw(e.target.value)
    debouncedFilter(e.target.value)
  }

  function applyPreset(p) {
    setPreset(p.id)
    setSortKey(p.key)
    setSortDir(p.dir)
  }

  function toggleSort(key) {
    setPreset(null)
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  function togglePin(sym) {
    setPinned(prev => {
      const next = new Set(prev)
      next.has(sym) ? next.delete(sym) : next.add(sym)
      return next
    })
  }

  function toggleExpanded(sym) {
    setExpanded(prev => prev === sym ? null : sym)
  }

  const rows = useMemo(() => {
    let list = (data || []).map(r => ({
      ...r,
      _pcr_imbalance: Math.abs((r.pcr || 1) - 1),
    }))

    if (filter) {
      const q = filter.toLowerCase()
      list = list.filter(r => r.symbol?.toLowerCase().includes(q))
    }

    // Pinned rows always first
    const pinnedRows = list.filter(r => pinned.has(r.symbol))
    const restRows   = list.filter(r => !pinned.has(r.symbol))

    function sortList(arr) {
      return [...arr].sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey]
        if (av === bv) return 0
        const cmp = typeof av === 'string' ? av.localeCompare(bv) : (av ?? 0) - (bv ?? 0)
        return sortDir === 'asc' ? cmp : -cmp
      })
    }

    return [...sortList(pinnedRows), ...sortList(restRows)]
  }, [data, sortKey, sortDir, filter, pinned])

  return (
    <div className="bg-[#0f1117] border border-slate-700/50 rounded-xl overflow-hidden">
      {/* Toolbar */}
      <div className="px-4 py-3 border-b border-slate-800 flex flex-wrap items-center gap-3">
        {/* Symbol search */}
        <input
          className="bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-violet-500/50 w-40"
          placeholder="Search…"
          value={filterRaw}
          onChange={handleFilterChange}
        />

        {/* Sort presets */}
        <div className="flex items-center gap-1 flex-wrap">
          <span className="text-[10px] text-slate-600 uppercase tracking-wider mr-1">Sort:</span>
          {SORT_PRESETS.map(p => (
            <button
              key={p.id}
              onClick={() => applyPreset(p)}
              className={`flex items-center gap-1 px-2 py-1 text-[10px] font-semibold rounded transition-colors ${
                preset === p.id
                  ? 'bg-violet-600/80 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              <p.icon className="w-2.5 h-2.5" />
              {p.label}
            </button>
          ))}
        </div>

        <span className="text-xs text-slate-500 ml-auto flex-shrink-0">
          {loading ? 'Loading…' : `${rows.length} result${rows.length !== 1 ? 's' : ''}`}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800">
              {COLS.map(col => (
                <th
                  key={col.key}
                  onClick={() => col.sortable && toggleSort(col.key)}
                  className={`px-4 py-2.5 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap
                    ${col.sortable ? 'cursor-pointer hover:text-slate-300 select-none' : ''}
                    ${col.width ?? ''}`}
                >
                  <span className="flex items-center">
                    {col.label}
                    {col.sortable && <SortIcon colKey={col.key} sortKey={sortKey} sortDir={sortDir} />}
                  </span>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {/* Skeleton rows while loading */}
            {loading && Array.from({ length: 8 }).map((_, i) => (
              <SkeletonRow key={i} cols={COLS} />
            ))}

            {/* Data rows */}
            {!loading && rows.map(row => {
              const isPinned  = pinned.has(row.symbol)
              const isExpanded = expanded === row.symbol
              const badges    = deriveConvictionBadges(row)

              return (
                <>
                  <tr
                    key={row.symbol}
                    onClick={() => onRowClick?.(row)}
                    className={`border-b border-slate-800/40 hover:bg-slate-800/30 cursor-pointer transition-colors group
                      ${isPinned ? 'bg-amber-500/5' : ''}
                      ${isExpanded ? 'bg-slate-800/20' : ''}`}
                  >
                    {/* Symbol */}
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-1.5">
                          {isPinned && <Star className="w-2.5 h-2.5 text-amber-400 flex-shrink-0" fill="currentColor" />}
                          <DirectionChip direction={row.direction} />
                          <span className="font-bold text-slate-100 group-hover:text-violet-300 transition-colors text-sm">
                            {row.symbol}
                          </span>
                        </div>
                        {/* Conviction badges inline */}
                        <div className="flex flex-wrap gap-1">
                          {badges.map(({ label, variant }) => {
                            const VARIANT = {
                              red:    'bg-rose-500/10    text-rose-400    border-rose-500/20',
                              green:  'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
                              amber:  'bg-amber-500/10   text-amber-400   border-amber-500/20',
                              purple: 'bg-violet-500/10  text-violet-400  border-violet-500/20',
                              blue:   'bg-blue-500/10    text-blue-400    border-blue-500/20',
                              slate:  'bg-slate-700/30   text-slate-500   border-slate-600/20',
                            }
                            return (
                              <span key={label}
                                className={`text-[8px] font-bold px-1.5 py-0.5 rounded border tracking-wide ${VARIANT[variant] ?? VARIANT.slate}`}
                              >
                                {label}
                              </span>
                            )
                          })}
                        </div>
                      </div>
                    </td>

                    {/* Distance */}
                    <td className="px-4 py-3">
                      <DistanceBadge pct={row.distance_pct} level={row.distance_level} />
                    </td>

                    {/* Spot */}
                    <td className="px-4 py-3 text-slate-300 font-mono text-xs">
                      {fmtINR(row.spot_price)}
                    </td>

                    {/* Max Pain */}
                    <td className="px-4 py-3 text-slate-400 font-mono text-xs">
                      {fmtINR(row.max_pain)}
                    </td>

                    {/* PCR */}
                    <td className="px-4 py-3">
                      <span className={`font-mono text-xs font-semibold ${
                        row.pcr > 1.2 ? 'text-emerald-400'
                        : row.pcr < 0.8 ? 'text-rose-400'
                        : 'text-slate-400'
                      }`}>
                        {row.pcr?.toFixed(2)}
                      </span>
                    </td>

                    {/* DTE */}
                    <td className="px-4 py-3">
                      <span className={`text-xs font-mono font-semibold ${
                        row.days_to_expiry <= 2 ? 'text-red-400'
                        : row.days_to_expiry <= 5 ? 'text-orange-400'
                        : 'text-slate-400'
                      }`}>
                        {row.days_to_expiry}d
                      </span>
                    </td>

                    {/* Signal bar */}
                    <td className="px-4 py-3 min-w-[180px]">
                      <SignalBar score={row.reversal_score} color={row.reversal_color} />
                      <div className="mt-0.5">
                        <button
                          onClick={(e) => { e.stopPropagation(); toggleExpanded(row.symbol) }}
                          className="text-[9px] text-slate-600 hover:text-slate-400 transition-colors truncate max-w-[170px] block text-left"
                          title="Show explanation"
                        >
                          {isExpanded ? '▲ hide' : '▼ why this signal?'}
                        </button>
                      </div>
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      <RowActions row={row} onPin={togglePin} pinned={isPinned} />
                    </td>
                  </tr>

                  {/* Expandable explanation row */}
                  {isExpanded && (
                    <tr
                      key={`${row.symbol}_exp`}
                      className="border-b border-slate-800/40 bg-slate-800/10"
                      onClick={() => onRowClick?.(row)}
                    >
                      <td colSpan={COLS.length} className="px-6 py-3">
                        <SignalExplanation row={row} maxLines={null} className="text-slate-400" />
                      </td>
                    </tr>
                  )}
                </>
              )
            })}

            {/* Empty state */}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={COLS.length} className="px-4 py-12 text-center">
                  <p className="text-slate-500 text-sm">No results match your filters.</p>
                  <p className="text-slate-600 text-xs mt-1">
                    Try lowering the deviation threshold or selecting 0% to see all symbols.
                  </p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
