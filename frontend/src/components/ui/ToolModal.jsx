import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  X, CheckCircle2, Target, Activity, Filter,
  BarChart2, TrendingUp, Cpu, Lock,
} from 'lucide-react'
import { Button } from './Button'
import { PulseIndicator } from './PulseIndicator'
import { useShowToast } from '../../context/ToastContext'
import { cn } from '../../utils/cn'

const ICONS = {
  target:   Target,
  activity: Activity,
  filter:   Filter,
  barchart: BarChart2,
  trending: TrendingUp,
  cpu:      Cpu,
}

// Static detail copy per scanner slug
const DETAILS = {
  'stop-hunter-pro': {
    what: 'Scans every symbol in your selected universe for institutional stop-hunt patterns — equal highs/lows sweeps, BSL/SSL grabs, and the subsequent BOS that confirms the real move.',
    howWorks: [
      'Identifies equal highs and equal lows across H1, H4, and D1',
      'Waits for a wick or close beyond the level (the hunt)',
      'Confirms with a Break of Structure in the opposite direction',
      'Scores each setup 0–100 based on confluence strength',
    ],
    bestFor: 'Intraday traders watching NIFTY50/NIFTY100 on 1H and 4H timeframes.',
  },
  'smc-liquidity-scanner': {
    what: 'Full Smart Money Concepts pipeline — order block detection, fair value gap mapping, BOS confirmation, and ChoCH identification across all selected symbols.',
    howWorks: [
      'Maps bullish and bearish order blocks from displacement candles',
      'Tracks unmitigated FVGs and their fill probability',
      'Detects BOS and ChoCH to confirm directional bias',
      'Confluence score weighs OB + FVG + BOS alignment',
    ],
    bestFor: 'Position traders on H4 and Daily timeframes seeking high-confluence SMC setups.',
  },
  'master-screener': {
    what: 'Multi-filter screener combining price structure, volume surge, RSI, and momentum to surface swing trade candidates from 500+ symbols.',
    howWorks: [
      'Applies technical filters: RSI range, volume spike, price vs EMA',
      'Overlays SMC structure bias (bullish / bearish)',
      'Ranks results by a composite momentum-structure score',
      'Refreshes on every bar close',
    ],
    bestFor: 'Swing traders scanning NIFTY500 and FNO for multi-day setups.',
  },
  'volume-profile-scanner': {
    what: 'Builds session and composite volume profiles for every symbol, then alerts when price approaches POC levels, VWAP deviations, or value area breakouts.',
    howWorks: [
      'Calculates VPOC, VAH, VAL for rolling 20-session window',
      'Flags price approaching POC ± 0.2% with structure context',
      'Identifies low-volume nodes as high-velocity target zones',
      'Combines with order block proximity for premium entries',
    ],
    bestFor: 'Traders using volume-based confluence on Banknifty and large-cap FNO.',
  },
  'options-scanner': {
    what: 'Screens the entire NSE options chain for unusual OI buildup, PCR extremes, and max pain price — then aligns findings with the underlying price structure.',
    howWorks: [
      'Calculates Put-Call Ratio per strike and for the chain',
      'Detects OI concentration shifts > 20% intraday',
      'Maps max pain level and compares to current price',
      'Surfaces setups where options positioning confirms SMC bias',
    ],
    bestFor: 'Options traders and hedgers tracking weekly and monthly expiry dynamics.',
  },
  'ai-confluence-engine': {
    what: 'An upcoming multi-model AI layer that cross-validates every signal from all five scanners and assigns a unified confluence probability score.',
    howWorks: [
      'Aggregates signals from all active scanners in real time',
      'Weights each signal by historical accuracy on that symbol',
      'Outputs a 0–100 confluence score with explainability breakdown',
      'Sends alerts only when score exceeds user-defined threshold',
    ],
    bestFor: 'High-frequency traders and algo desks that need pre-filtered, AI-ranked signals.',
  },
}

export function ToolModal({ tool, onClose }) {
  const showToast = useShowToast()
  const isLocked  = tool?.status === 'coming_soon'
  const Icon      = tool ? (ICONS[tool.icon] ?? Target) : Target
  const detail    = tool ? (DETAILS[tool.slug] ?? null) : null

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Lock body scroll only while a tool is actually open
  useEffect(() => {
    if (!tool) return
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [tool])

  function handleLaunch() {
    onClose()
    showToast('Scanner app coming next — stay tuned!', 'info')
  }

  function handleUpgrade() {
    onClose()
    showToast('Upgrade flow coming soon. We\'ll notify you!', 'warning')
  }

  return (
    <AnimatePresence>
      {tool && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[200] bg-black/70"
            style={{ backdropFilter: 'blur(6px)' }}
            onClick={onClose}
          />

          {/* Panel */}
          <motion.div
            key="panel"
            initial={{ opacity: 0, y: 40, scale: 0.96 }}
            animate={{ opacity: 1, y: 0,  scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ type: 'spring', stiffness: 340, damping: 28 }}
            className="fixed inset-x-4 bottom-0 sm:inset-auto sm:top-1/2 sm:left-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 z-[201] w-full sm:max-w-lg rounded-t-2xl sm:rounded-2xl overflow-hidden"
            style={{
              background: 'rgba(13, 17, 30, 0.98)',
              border: '1px solid rgba(255,255,255,0.10)',
              backdropFilter: 'blur(40px)',
              maxHeight: '90vh',
            }}
          >
            {/* Accent top line */}
            <div
              className="h-[2px] w-full"
              style={{
                background: `linear-gradient(90deg, transparent, ${tool.accentColor}, transparent)`,
              }}
            />

            <div className="overflow-y-auto" style={{ maxHeight: 'calc(90vh - 2px)' }}>
              <div className="p-6">
                {/* Header */}
                <div className="flex items-start justify-between mb-5">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: tool.accentBg, border: `1px solid ${tool.accentColor}30` }}
                    >
                      <Icon size={20} style={{ color: tool.accentColor }} strokeWidth={1.6} />
                    </div>
                    <div>
                      <h2 className="text-headline-sm text-on-surface">{tool.name}</h2>
                      <div className="flex items-center gap-2 mt-1">
                        {isLocked ? (
                          <span className="inline-flex items-center gap-1 font-mono text-[10px] text-amber">
                            <Lock size={9} /> Coming Soon
                          </span>
                        ) : (
                          <PulseIndicator color="bullish" size="xs" label="Live" />
                        )}
                        <span className="font-mono text-[10px] text-outline">· {tool.plan} Plan</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={onClose}
                    className="text-outline hover:text-on-surface transition-colors p-1 rounded"
                    aria-label="Close"
                  >
                    <X size={18} />
                  </button>
                </div>

                {/* What it does */}
                {detail && (
                  <>
                    <p className="text-body-sm text-on-surface-variant leading-relaxed mb-5">
                      {detail.what}
                    </p>

                    {/* How it works */}
                    <div className="mb-5">
                      <p className="font-mono text-label-caps text-outline uppercase tracking-widest mb-3">
                        How It Works
                      </p>
                      <ul className="flex flex-col gap-2.5">
                        {detail.howWorks.map((step, i) => (
                          <li key={i} className="flex items-start gap-2.5">
                            <CheckCircle2
                              size={13}
                              className="flex-shrink-0 mt-0.5"
                              style={{ color: tool.accentColor }}
                            />
                            <span className="text-body-sm text-on-surface-variant leading-snug">
                              {step}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Best for */}
                    <div
                      className="rounded-lg px-4 py-3 mb-6"
                      style={{
                        background: tool.accentBg,
                        border: `1px solid ${tool.accentColor}20`,
                      }}
                    >
                      <p className="font-mono text-label-caps tracking-widest uppercase mb-1"
                        style={{ color: tool.accentColor }}>
                        Best For
                      </p>
                      <p className="text-body-sm text-on-surface-variant">{detail.bestFor}</p>
                    </div>
                  </>
                )}

                {/* Tags */}
                <div className="flex flex-wrap gap-1.5 mb-6">
                  {tool.tags.map((tag) => (
                    <span
                      key={tag}
                      className="font-mono text-[10px] px-2 py-0.5 rounded-full text-outline border border-outline-variant/50"
                    >
                      {tag}
                    </span>
                  ))}
                </div>

                {/* CTA */}
                <div className="flex gap-3">
                  {isLocked ? (
                    <Button className="flex-1 justify-center" variant="outline" onClick={handleUpgrade}>
                      <Lock size={13} /> Upgrade to {tool.plan}
                    </Button>
                  ) : (
                    <Button className="flex-1 justify-center" onClick={handleLaunch}>
                      Launch Scanner →
                    </Button>
                  )}
                  <Button variant="ghost" onClick={onClose} className="px-4">
                    Close
                  </Button>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
