import { useState, useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { GlassCard } from '../ui/GlassCard'
import { PulseIndicator } from '../ui/PulseIndicator'
import { SWEEP_SIGNALS, FVG_SIGNALS } from '../../data/mockScannerData'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { cn } from '../../utils/cn'

const TABS = [
  { id: 'sweep', label: 'Liquidity Sweep', data: SWEEP_SIGNALS },
  { id: 'fvg',   label: 'FVG Rejection',   data: FVG_SIGNALS   },
]

const VISIBLE_ROWS = 5
const CYCLE_MS     = 2600

function gradeColors(grade) {
  return {
    A: 'bg-bullish/20 text-bullish border border-bullish/30',
    B: 'bg-primary/20 text-primary border border-primary/30',
    C: 'bg-amber/20 text-amber border border-amber/30',
    D: 'bg-bearish/20 text-bearish border border-bearish/30',
  }[grade] ?? 'bg-outline/20 text-outline'
}

function scoreColor(score) {
  if (score >= 87) return 'text-bullish'
  if (score >= 75) return 'text-primary'
  return 'text-amber'
}

function SignalBadge({ direction }) {
  const bull = direction === 'bullish'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-mono text-[11px] font-semibold',
        bull
          ? 'bg-bullish/15 text-bullish border border-bullish/25'
          : 'bg-bearish/15 text-bearish border border-bearish/25',
      )}
    >
      {bull ? '▲' : '▼'} {bull ? 'BUY' : 'SELL'}
    </span>
  )
}

export function ScannerPreviewWidget() {
  const [activeTab, setActiveTab] = useState('sweep')
  const reduced = useReducedMotion()

  const signals = TABS.find((t) => t.id === activeTab)?.data ?? SWEEP_SIGNALS

  // Visible rows: rotate one entry every CYCLE_MS
  const counterRef = useRef(VISIBLE_ROWS)
  const [rows, setRows] = useState(() =>
    signals.slice(0, VISIBLE_ROWS).map((s, i) => ({ ...s, _uid: `${s.id}-0-${i}` })),
  )

  // Reset rows when tab changes
  useEffect(() => {
    counterRef.current = VISIBLE_ROWS
    setRows(signals.slice(0, VISIBLE_ROWS).map((s, i) => ({ ...s, _uid: `${s.id}-tab-${i}` })))
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cycle rows — skip if reduced motion
  useEffect(() => {
    if (reduced) return
    const id = setInterval(() => {
      const idx = counterRef.current % signals.length
      const next = { ...signals[idx], _uid: `${signals[idx].id}-${counterRef.current}` }
      counterRef.current += 1
      setRows((prev) => [...prev.slice(1), next])
    }, CYCLE_MS)
    return () => clearInterval(id)
  }, [signals, reduced])

  return (
    <GlassCard className="w-full overflow-hidden shadow-card">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-5 pt-4 pb-0">
        {/* Tabs */}
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'px-4 py-2 font-mono text-data-mono text-[13px] rounded-t transition-colors duration-150 relative',
                activeTab === tab.id
                  ? 'text-on-surface'
                  : 'text-on-surface-variant hover:text-on-surface',
              )}
            >
              {tab.label}
              {activeTab === tab.id && (
                <motion.span
                  layoutId="tab-indicator"
                  className="absolute bottom-0 left-0 right-0 h-[2px] bg-primary rounded-full"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
            </button>
          ))}
        </div>

        {/* Live badge */}
        <PulseIndicator color="bullish" size="xs" label="LIVE" />
      </div>

      {/* ── Column headers ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-[80px_1fr_48px_56px_36px_72px] gap-x-3 px-5 pt-3 pb-2 border-t border-b border-outline-variant/20 mt-1">
        {['Symbol', 'Setup', 'TF', 'Score', 'Grd', 'Signal'].map((col) => (
          <span key={col} className="font-mono text-label-caps text-outline uppercase">
            {col}
          </span>
        ))}
      </div>

      {/* ── Signal rows ────────────────────────────────────────────────────── */}
      <div className="overflow-hidden" style={{ height: `${VISIBLE_ROWS * 48}px` }}>
        <AnimatePresence initial={false} mode="popLayout">
          {rows.map((signal) => (
            <motion.div
              key={signal._uid}
              initial={{ opacity: 0, y: reduced ? 0 : 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: reduced ? 0 : -20 }}
              transition={{ duration: 0.32, ease: 'easeInOut' }}
              className="grid grid-cols-[80px_1fr_48px_56px_36px_72px] gap-x-3 px-5 items-center h-12 border-b border-outline-variant/10 last:border-0 hover:bg-white/[0.02] transition-colors"
            >
              {/* Symbol */}
              <span className="font-mono text-[13px] font-bold text-on-surface truncate">
                {signal.symbol}
              </span>

              {/* Setup */}
              <span className="font-mono text-[12px] text-on-surface-variant truncate">
                {signal.setup}
              </span>

              {/* Timeframe */}
              <span className="font-mono text-[12px] text-outline">
                {signal.timeframe}
              </span>

              {/* Score */}
              <span className={cn('font-mono text-[13px] font-semibold tabular-nums', scoreColor(signal.score))}>
                {signal.score.toFixed(1)}
              </span>

              {/* Grade */}
              <span
                className={cn(
                  'inline-flex items-center justify-center w-6 h-6 rounded font-mono text-[11px] font-bold',
                  gradeColors(signal.grade),
                )}
              >
                {signal.grade}
              </span>

              {/* Signal badge */}
              <SignalBadge direction={signal.direction} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="px-5 py-2.5 flex items-center justify-between border-t border-outline-variant/15">
        <span className="font-mono text-[11px] text-outline">
          Showing {VISIBLE_ROWS} of {signals.length} signals · Real-time on Pro+
        </span>
        <button className="font-mono text-[11px] text-primary hover:text-on-primary-container transition-colors">
          View all →
        </button>
      </div>
    </GlassCard>
  )
}
