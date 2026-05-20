/**
 * MiniVisuals — lightweight, zero-library visualizations for the scanner drawer.
 *
 * All rendered with CSS/SVG only. No Recharts, no Chart.js.
 *
 * Exports:
 *   MaxPainBar       — horizontal bar showing spot vs max pain
 *   OIWallBalance    — two-sided OI wall strength indicator
 *   ReversalGauge    — arc gauge 0–100
 *   ExpiryCountdown  — colored DTE pill chain
 *   DistanceBar      — simple colored progress bar
 */

// ── Helpers ──────────────────────────────────────────────────────────────────

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v))
}

function fmt(n) {
  if (!n) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e7) return sign + (abs / 1e7).toFixed(1) + 'Cr'
  if (abs >= 1e5) return sign + (abs / 1e5).toFixed(1) + 'L'
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(0) + 'K'
  return n.toString()
}

// ── MaxPainBar ────────────────────────────────────────────────────────────────
/**
 * Shows spot price position relative to max pain on a horizontal number line.
 * The bar spans from min(spot,maxPain)−5% to max(spot,maxPain)+5%.
 */
export function MaxPainBar({ spotPrice, maxPain }) {
  if (!spotPrice || !maxPain) return null

  const spread = Math.abs(spotPrice - maxPain)
  const padding = spread * 0.8 + maxPain * 0.015
  const lo = Math.min(spotPrice, maxPain) - padding
  const hi = Math.max(spotPrice, maxPain) + padding
  const range = hi - lo || 1

  const spotPct  = ((spotPrice - lo) / range) * 100
  const painPct  = ((maxPain  - lo) / range) * 100
  const midPct   = (Math.min(spotPct, painPct) + Math.abs(spotPct - painPct) / 2)
  const spanPct  = Math.abs(spotPct - painPct)

  const isBearish = spotPrice > maxPain

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>₹{lo.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
        <span>Max Pain vs Spot</span>
        <span>₹{hi.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
      </div>

      <div className="relative h-6 bg-slate-800/70 rounded-full overflow-visible">
        {/* Span between spot and max pain */}
        <div
          className={`absolute top-1 h-4 rounded-full opacity-30 ${isBearish ? 'bg-rose-500' : 'bg-emerald-500'}`}
          style={{ left: `${Math.min(spotPct, painPct)}%`, width: `${spanPct}%` }}
        />

        {/* Max pain marker */}
        <div
          className="absolute top-0 flex flex-col items-center"
          style={{ left: `${clamp(painPct, 2, 96)}%`, transform: 'translateX(-50%)' }}
        >
          <div className="w-0.5 h-6 bg-emerald-400/70" />
        </div>

        {/* Spot marker */}
        <div
          className="absolute top-0 flex flex-col items-center"
          style={{ left: `${clamp(spotPct, 2, 96)}%`, transform: 'translateX(-50%)' }}
        >
          <div className="w-2.5 h-2.5 rounded-full bg-amber-400 border-2 border-slate-900 mt-1.5 shadow" />
        </div>
      </div>

      {/* Labels */}
      <div className="flex justify-between text-[10px]">
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-amber-400" />
          <span className="text-slate-400">Spot ₹{spotPrice.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-0.5 h-3 bg-emerald-400/70" />
          <span className="text-slate-400">Max Pain ₹{maxPain.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
        </div>
      </div>
    </div>
  )
}

// ── OIWallBalance ─────────────────────────────────────────────────────────────
/**
 * Two-sided bar: CE wall OI (resistance, left, red) vs PE wall OI (support, right, green).
 * Wider = stronger wall.
 */
export function OIWallBalance({ ceWallStrike, peWallStrike, ceWallOi, peWallOi }) {
  if (!ceWallOi && !peWallOi) return null

  const total = (ceWallOi || 0) + (peWallOi || 0) || 1
  const cePct  = ((ceWallOi || 0) / total) * 100
  const pePct  = ((peWallOi || 0) / total) * 100
  const stronger = cePct > pePct ? 'bearish' : 'bullish'

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-[10px] text-slate-500 mb-1">
        <span className="text-rose-400 font-semibold">CE Resistance</span>
        <span className="text-slate-500">OI Wall Balance</span>
        <span className="text-emerald-400 font-semibold">PE Support</span>
      </div>

      {/* Balance bar */}
      <div className="flex h-4 rounded-full overflow-hidden bg-slate-800">
        <div
          className="bg-rose-500/60 flex items-center justify-end pr-1 transition-all duration-500"
          style={{ width: `${cePct}%` }}
        >
          {cePct > 20 && <span className="text-[9px] text-rose-300">{cePct.toFixed(0)}%</span>}
        </div>
        <div
          className="bg-emerald-500/60 flex items-center pl-1 transition-all duration-500"
          style={{ width: `${pePct}%` }}
        >
          {pePct > 20 && <span className="text-[9px] text-emerald-300">{pePct.toFixed(0)}%</span>}
        </div>
      </div>

      {/* Strike + OI labels */}
      <div className="flex justify-between text-[10px]">
        <div className="text-slate-500">
          <span className="text-rose-400 font-mono">₹{ceWallStrike?.toLocaleString('en-IN')}</span>
          <span className="text-slate-600 ml-1">({fmt(ceWallOi)})</span>
        </div>
        <div className={`text-xs font-semibold ${stronger === 'bullish' ? 'text-emerald-400' : 'text-rose-400'}`}>
          {stronger === 'bullish' ? '▲ Support stronger' : '▼ Resistance stronger'}
        </div>
        <div className="text-slate-500 text-right">
          <span className="text-emerald-400 font-mono">₹{peWallStrike?.toLocaleString('en-IN')}</span>
          <span className="text-slate-600 ml-1">({fmt(peWallOi)})</span>
        </div>
      </div>
    </div>
  )
}

// ── ReversalGauge ─────────────────────────────────────────────────────────────
/**
 * SVG arc gauge (semicircle, top-down) showing reversal score 0–100.
 * Color transitions from slate → yellow → orange → red at thresholds.
 */
export function ReversalGauge({ score = 0, color, category }) {
  const r      = 54
  const cx     = 70
  const cy     = 70
  const stroke = 10
  const circ   = Math.PI * r   // half circle arc length

  const pct       = clamp(score, 0, 100) / 100
  const dashArray = `${pct * circ} ${circ}`

  // Derive color from score if not provided
  const arcColor = color || (
    score >= 80 ? '#f87171' :   // red-400
    score >= 60 ? '#fb923c' :   // orange-400
    score >= 40 ? '#facc15' :   // yellow-400
    '#475569'                   // slate-600
  )

  // Needle angle: -180deg (left) to 0deg (right), 0 = score 0, 180 = score 100
  const needleAngle = -180 + (pct * 180)
  const needleRad   = (needleAngle * Math.PI) / 180
  const nx = cx + (r - 4) * Math.cos(needleRad)
  const ny = cy + (r - 4) * Math.sin(needleRad)

  return (
    <div className="flex flex-col items-center">
      <svg width={140} height={80} viewBox="0 0 140 80" className="overflow-visible">
        {/* Track arc */}
        <path
          d={`M ${cx - r},${cy} A ${r},${r} 0 0,1 ${cx + r},${cy}`}
          fill="none"
          stroke="#1e293b"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Score arc */}
        <path
          d={`M ${cx - r},${cy} A ${r},${r} 0 0,1 ${cx + r},${cy}`}
          fill="none"
          stroke={arcColor}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={dashArray}
          style={{ transition: 'stroke-dasharray 0.8s ease-out' }}
        />
        {/* Tick marks */}
        {[0, 25, 50, 75, 100].map(t => {
          const a   = -180 + (t / 100) * 180
          const rad = (a * Math.PI) / 180
          const x1  = cx + (r + 4) * Math.cos(rad)
          const y1  = cy + (r + 4) * Math.sin(rad)
          const x2  = cx + (r + stroke / 2 + 4) * Math.cos(rad)
          const y2  = cy + (r + stroke / 2 + 4) * Math.sin(rad)
          return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#334155" strokeWidth={1.5} />
        })}
        {/* Needle */}
        <line
          x1={cx} y1={cy}
          x2={nx} y2={ny}
          stroke={arcColor}
          strokeWidth={2.5}
          strokeLinecap="round"
          style={{ transition: 'all 0.8s ease-out' }}
        />
        {/* Center dot */}
        <circle cx={cx} cy={cy} r={4} fill={arcColor} />

        {/* Score label */}
        <text x={cx} y={cy - 18} textAnchor="middle" fill={arcColor} fontSize={22} fontWeight="900">
          {score}
        </text>
        <text x={cx} y={cy - 4} textAnchor="middle" fill="#64748b" fontSize={9}>
          / 100
        </text>
      </svg>

      {category && (
        <p className="text-[11px] font-bold mt-1" style={{ color: arcColor }}>
          {category} Signal
        </p>
      )}
    </div>
  )
}

// ── ExpiryCountdown ───────────────────────────────────────────────────────────
/**
 * Visual expiry pressure indicator.
 * Shows a chain of day segments, highlighting urgency with color.
 */
export function ExpiryCountdown({ daysToExpiry, expiry }) {
  const dte = daysToExpiry ?? 0
  const color = dte <= 2 ? { bar: 'bg-red-500',    text: 'text-red-400',    label: 'EXPIRY CRITICAL' }
    : dte <= 5            ? { bar: 'bg-amber-500',  text: 'text-amber-400',  label: 'NEAR EXPIRY' }
    : dte <= 10           ? { bar: 'bg-yellow-500', text: 'text-yellow-400', label: 'APPROACHING' }
    :                       { bar: 'bg-slate-600',  text: 'text-slate-400',  label: 'AMPLE TIME' }

  // Segments: show up to 30 days
  const maxDisplay = Math.min(dte, 30)
  const segments   = Array.from({ length: 30 }, (_, i) => i < maxDisplay)

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className={`text-[10px] font-bold ${color.text}`}>{color.label}</span>
        <span className="text-[10px] text-slate-500">{expiry}</span>
      </div>

      {/* Segment bar */}
      <div className="flex gap-0.5 h-2.5">
        {segments.map((filled, i) => (
          <div
            key={i}
            className={`flex-1 rounded-sm transition-all ${filled ? color.bar : 'bg-slate-800'}`}
            style={{ opacity: filled ? 1 - (i / 30) * 0.4 : 0.2 }}
          />
        ))}
      </div>

      <div className={`text-lg font-black ${color.text} text-center`}>
        {dte} <span className="text-sm font-normal text-slate-500">days to expiry</span>
      </div>
    </div>
  )
}

// ── DistanceBar ────────────────────────────────────────────────────────────────
/**
 * Simple labelled progress bar for distance % with color levels.
 */
export function DistanceBar({ distancePct, level }) {
  const maxDisplay = 10 // show full bar at 10%+
  const pct = clamp((distancePct || 0) / maxDisplay * 100, 0, 100)

  const color = level === 'extreme' ? 'bg-red-500'
    : level === 'high'     ? 'bg-orange-500'
    : level === 'moderate' ? 'bg-yellow-500'
    : 'bg-slate-500'

  const textColor = level === 'extreme' ? 'text-red-400'
    : level === 'high'     ? 'text-orange-400'
    : level === 'moderate' ? 'text-yellow-400'
    : 'text-slate-400'

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-slate-500">Deviation from Max Pain</span>
        <span className={`font-bold ${textColor}`}>{distancePct?.toFixed(2)}%</span>
      </div>
      <div className="bg-slate-800 rounded-full h-2 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-[9px] text-slate-600">
        <span>0%</span>
        <span className={`font-semibold uppercase ${textColor}`}>{level}</span>
        <span>10%+</span>
      </div>
    </div>
  )
}
