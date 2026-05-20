import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Target, Activity, Filter, BarChart2, TrendingUp,
  Lock, CheckCircle2, TrendingDown, Zap,
} from 'lucide-react'
import { SectionLabel } from '../ui/SectionLabel'
import { PulseIndicator } from '../ui/PulseIndicator'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { DASHBOARD_RECENT_SCANS } from '../../data/landingData'
import { cn } from '../../utils/cn'

// ── helpers ───────────────────────────────────────────────────────────────────

const GRADE_COLORS = {
  A: { color: '#00d97e', bg: 'rgba(0,217,126,0.15)' },
  B: { color: '#b3c5ff', bg: 'rgba(179,197,255,0.15)' },
  C: { color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
  D: { color: '#ff4d4f', bg: 'rgba(255,77,79,0.15)' },
}

function GradeBadge({ grade }) {
  const s = GRADE_COLORS[grade] ?? GRADE_COLORS.C
  return (
    <span
      className="inline-flex items-center justify-center w-6 h-6 rounded font-mono text-[11px] font-bold flex-shrink-0"
      style={{ color: s.color, background: s.bg }}
    >
      {grade}
    </span>
  )
}

function ScorePill({ score }) {
  const color = score >= 85 ? '#00d97e' : score >= 70 ? '#b3c5ff' : '#f59e0b'
  return (
    <span className="font-mono text-[11px] font-bold" style={{ color }}>
      {score}
    </span>
  )
}

function DirectionBadge({ direction }) {
  return direction === 'bullish' ? (
    <span className="inline-flex items-center gap-0.5 font-mono text-[10px] font-semibold text-bullish">
      <TrendingUp size={10} /> Bull
    </span>
  ) : (
    <span className="inline-flex items-center gap-0.5 font-mono text-[10px] font-semibold text-bearish">
      <TrendingDown size={10} /> Bear
    </span>
  )
}

// ── Scan progress bar ─────────────────────────────────────────────────────────

function ScanProgressBar({ reduced }) {
  const [progress, setProgress] = useState(0)
  const [label, setLabel]       = useState('Scanning NIFTY50…')

  useEffect(() => {
    if (reduced) { setProgress(100); return }
    const labels = [
      'Scanning NIFTY50…',
      'Detecting liquidity sweeps…',
      'Scoring setups…',
      'Scan complete ✓',
    ]
    let pct = 0
    const iv = setInterval(() => {
      pct += Math.random() * 14 + 6
      if (pct >= 100) {
        pct = 100
        clearInterval(iv)
        setTimeout(() => { setProgress(0); setLabel(labels[0]) }, 1800)
      }
      setProgress(Math.min(pct, 100))
      setLabel(labels[Math.min(Math.floor(pct / 34), 3)])
    }, 320)
    return () => clearInterval(iv)
  }, [reduced])

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-1.5">
        <span className="font-mono text-[11px] text-outline">{label}</span>
        <span className="font-mono text-[11px] text-primary">{Math.round(progress)}%</span>
      </div>
      <div className="h-1 w-full rounded-full" style={{ background: 'rgba(255,255,255,0.07)' }}>
        <motion.div
          className="h-1 rounded-full"
          style={{ background: 'linear-gradient(90deg, #0066ff, #00f1fe)', originX: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.35, ease: 'linear' }}
        />
      </div>
    </div>
  )
}

// ── Tool access list ──────────────────────────────────────────────────────────

const ACCESS_TOOLS = [
  { name: 'Stop Hunter Pro',        icon: Target,    color: '#b3c5ff', included: true },
  { name: 'SMC Liquidity Scanner',  icon: Activity,  color: '#00f1fe', included: true },
  { name: 'Master Screener',        icon: Filter,    color: '#a78bfa', included: true },
  { name: 'Volume Profile Scanner', icon: BarChart2, color: '#f59e0b', included: false },
  { name: 'Options Scanner',        icon: TrendingUp,color: '#00d97e', included: false },
]

// ── Setup detail drawer ────────────────────────────────────────────────────────

function SetupDrawer({ scan }) {
  if (!scan) return null
  const g = GRADE_COLORS[scan.grade] ?? GRADE_COLORS.C
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={scan.symbol}
        initial={{ opacity: 0, x: 16 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -8 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="p-4 flex flex-col gap-3"
      >
        <div className="flex items-center justify-between">
          <span className="font-mono text-[13px] font-bold text-on-surface">{scan.symbol}</span>
          <GradeBadge grade={scan.grade} />
        </div>
        <p className="text-body-sm text-on-surface-variant">{scan.setup}</p>

        <div className="flex gap-2 flex-wrap">
          <span className="font-mono text-[10px] px-2 py-0.5 rounded-full border border-outline-variant/50 text-outline">{scan.tf}</span>
          <DirectionBadge direction={scan.direction} />
        </div>

        {/* Score bar */}
        <div>
          <div className="flex justify-between mb-1">
            <span className="font-mono text-[10px] text-outline uppercase tracking-widest">Confluence Score</span>
            <ScorePill score={scan.score} />
          </div>
          <div className="h-1.5 rounded-full" style={{ background: 'rgba(255,255,255,0.07)' }}>
            <div
              className="h-1.5 rounded-full transition-all duration-700"
              style={{ width: `${scan.score}%`, background: g.color }}
            />
          </div>
        </div>

        {/* Fake detail rows */}
        {[
          ['Sweep Type',  scan.direction === 'bullish' ? 'Buy-Side Liquidity' : 'Sell-Side Liquidity'],
          ['BOS Confirm', 'Yes'],
          ['FVG Present', 'Yes'],
          ['Scanned At',  scan.time],
        ].map(([label, val]) => (
          <div key={label} className="flex justify-between text-body-sm">
            <span className="text-outline">{label}</span>
            <span className="text-on-surface-variant">{val}</span>
          </div>
        ))}
      </motion.div>
    </AnimatePresence>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function DashboardPreview() {
  const reduced                 = useReducedMotion()
  const [selected, setSelected] = useState(DASHBOARD_RECENT_SCANS[0])

  return (
    <section className="relative py-24 px-6 overflow-hidden">
      {/* Glow */}
      <div
        className="absolute left-0 top-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-[0.05] pointer-events-none"
        style={{ background: 'radial-gradient(ellipse, #00f1fe 0%, transparent 70%)', filter: 'blur(80px)' }}
      />

      <div className="relative z-10 max-w-6xl mx-auto">
        {/* Header */}
        <motion.div
          className="text-center mb-12"
          initial={reduced ? {} : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-60px' }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        >
          <SectionLabel className="mb-3 block">Dashboard Preview</SectionLabel>
          <h2 className="text-[32px] sm:text-[40px] font-bold text-on-surface leading-tight mb-3">
            Your Command Centre
          </h2>
          <p className="text-body-main text-on-surface-variant max-w-md mx-auto">
            Every signal, score, and setup in one clean view — built for speed, not noise.
          </p>
        </motion.div>

        {/* Dashboard shell */}
        <motion.div
          initial={reduced ? {} : { opacity: 0, y: 40, scale: 0.98 }}
          whileInView={{ opacity: 1, y: 0, scale: 1 }}
          viewport={{ once: true, margin: '-40px' }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="rounded-2xl overflow-hidden"
          style={{
            border: '1px solid rgba(255,255,255,0.08)',
            background: 'rgba(10,14,26,0.95)',
            backdropFilter: 'blur(30px)',
            boxShadow: '0 40px 120px rgba(0,0,0,0.7)',
          }}
        >
          {/* Top bar */}
          <div
            className="flex items-center justify-between px-5 py-3 border-b border-outline-variant/20"
            style={{ background: 'rgba(8,12,22,0.8)' }}
          >
            <div className="flex items-center gap-2.5">
              <div className="w-5 h-5 rounded bg-primary-container flex items-center justify-center">
                <Zap size={11} className="text-white" fill="white" />
              </div>
              <span className="font-mono text-[12px] font-bold text-on-surface tracking-wider uppercase">
                Stop Hunter Pro
              </span>
            </div>
            <div className="flex items-center gap-3">
              <PulseIndicator color="bullish" size="xs" label="Live" />
              <span className="font-mono text-[10px] px-2 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary">
                Pro Plan
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-[1fr_220px] divide-y lg:divide-y-0 lg:divide-x divide-outline-variant/20">

            {/* Left: main panel */}
            <div className="p-5">
              {/* Scan progress */}
              <ScanProgressBar reduced={reduced} />

              {/* Stats row */}
              <div className="grid grid-cols-3 gap-3 mb-5">
                {[
                  { label: 'Signals Today', value: '24', color: '#b3c5ff' },
                  { label: 'A-Grade Setups', value: '7', color: '#00d97e' },
                  { label: 'Symbols Scanned', value: '50', color: '#00f1fe' },
                ].map(({ label, value, color }) => (
                  <div
                    key={label}
                    className="rounded-lg px-3 py-2.5 text-center"
                    style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}
                  >
                    <p className="font-mono text-[20px] font-bold mb-0.5" style={{ color }}>{value}</p>
                    <p className="font-mono text-[10px] text-outline">{label}</p>
                  </div>
                ))}
              </div>

              {/* Scanner results table */}
              <div className="rounded-lg overflow-hidden" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
                {/* Table header */}
                <div
                  className="grid grid-cols-[1fr_2fr_56px_56px_56px_40px] gap-2 px-3 py-2"
                  style={{ background: 'rgba(255,255,255,0.04)' }}
                >
                  {['Symbol', 'Setup', 'TF', 'Score', 'Dir', 'Grd'].map((h) => (
                    <span key={h} className="font-mono text-[10px] uppercase tracking-widest text-outline">{h}</span>
                  ))}
                </div>

                {/* Rows */}
                {DASHBOARD_RECENT_SCANS.map((scan) => (
                  <button
                    key={scan.symbol}
                    onClick={() => setSelected(scan)}
                    className={cn(
                      'w-full grid grid-cols-[1fr_2fr_56px_56px_56px_40px] gap-2 items-center px-3 py-2.5',
                      'border-t border-outline-variant/15 text-left transition-colors duration-150',
                      selected?.symbol === scan.symbol
                        ? 'bg-primary/[0.07]'
                        : 'hover:bg-white/[0.03]',
                    )}
                  >
                    <span className="font-mono text-[12px] font-semibold text-on-surface truncate">{scan.symbol}</span>
                    <span className="text-body-sm text-on-surface-variant truncate">{scan.setup}</span>
                    <span className="font-mono text-[11px] text-outline">{scan.tf}</span>
                    <ScorePill score={scan.score} />
                    <DirectionBadge direction={scan.direction} />
                    <GradeBadge grade={scan.grade} />
                  </button>
                ))}
              </div>
            </div>

            {/* Right: tool access + setup drawer */}
            <div className="flex flex-col divide-y divide-outline-variant/20">
              {/* Tool access */}
              <div className="p-4">
                <p className="font-mono text-[10px] uppercase tracking-widest text-outline mb-3">Scanner Access</p>
                <div className="flex flex-col gap-2">
                  {ACCESS_TOOLS.map(({ name, icon: Icon, color, included }) => (
                    <div key={name} className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Icon size={12} style={{ color, flexShrink: 0 }} />
                        <span className={cn('text-body-sm truncate', included ? 'text-on-surface-variant' : 'text-outline')}>
                          {name}
                        </span>
                      </div>
                      {included
                        ? <CheckCircle2 size={12} className="text-bullish flex-shrink-0" />
                        : <Lock size={11} className="text-outline flex-shrink-0" />}
                    </div>
                  ))}
                </div>
              </div>

              {/* Setup detail */}
              <div className="flex-1">
                <div className="px-4 pt-3 pb-0">
                  <p className="font-mono text-[10px] uppercase tracking-widest text-outline">Setup Detail</p>
                </div>
                <SetupDrawer scan={selected} />
              </div>
            </div>
          </div>
        </motion.div>

        {/* Caption */}
        <p className="mt-4 text-center font-mono text-[11px] text-outline">
          Simulated preview · Not live data · Actual dashboard available after signup
        </p>
      </div>
    </section>
  )
}
