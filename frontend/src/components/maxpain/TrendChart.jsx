/**
 * TrendChart — pure SVG dual-line chart for spot vs max_pain over time.
 * Also renders a small PCR line on a secondary axis.
 */

function fmt(n, dec = 0) {
  if (n == null) return '—'
  return n.toLocaleString('en-IN', { maximumFractionDigits: dec })
}

function fmtTime(iso) {
  const d = new Date(iso)
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
}

export default function TrendChart({ series = [], height = 260 }) {
  if (!series.length) return (
    <div className="flex items-center justify-center" style={{ height }}>
      <p className="text-slate-500 text-sm">No historical data yet — snapshots capture every 5 min during market hours</p>
    </div>
  )

  const W = 640
  const H = height
  const PAD = { top: 20, right: 48, bottom: 44, left: 60 }
  const chartW = W - PAD.left - PAD.right
  const chartH = H - PAD.top - PAD.bottom

  const spots     = series.map(p => p.spot)
  const maxPains  = series.map(p => p.max_pain)
  const pcrs      = series.map(p => p.pcr).filter(Boolean)

  const allPrices = [...spots, ...maxPains].filter(Boolean)
  const minP = Math.min(...allPrices) * 0.999
  const maxP = Math.max(...allPrices) * 1.001
  const priceRange = maxP - minP || 1

  const minPcr = Math.min(...pcrs, 0.5)
  const maxPcr = Math.max(...pcrs, 2.0)
  const pcrRange = maxPcr - minPcr || 1

  function xPx(i) { return PAD.left + (i / (series.length - 1 || 1)) * chartW }
  function yPx(v)  { return PAD.top + (1 - (v - minP) / priceRange) * chartH }
  function yPcr(v) { return PAD.top + (1 - (v - minPcr) / pcrRange) * chartH }

  // Build SVG paths
  const spotPath = series
    .map((p, i) => p.spot != null ? `${i === 0 ? 'M' : 'L'}${xPx(i).toFixed(1)},${yPx(p.spot).toFixed(1)}` : null)
    .filter(Boolean).join(' ')

  const mpPath = series
    .map((p, i) => p.max_pain != null ? `${i === 0 ? 'M' : 'L'}${xPx(i).toFixed(1)},${yPx(p.max_pain).toFixed(1)}` : null)
    .filter(Boolean).join(' ')

  const pcrPath = series
    .map((p, i) => p.pcr != null ? `${i === 0 ? 'M' : 'L'}${xPx(i).toFixed(1)},${yPcr(p.pcr).toFixed(1)}` : null)
    .filter(Boolean).join(' ')

  // Fill under spot
  const spotArea = `${spotPath} L${xPx(series.length - 1).toFixed(1)},${(PAD.top + chartH).toFixed(1)} L${PAD.left},${(PAD.top + chartH).toFixed(1)} Z`

  // X-axis ticks (every ~10% of data)
  const tickStep = Math.max(1, Math.floor(series.length / 6))
  const xTicks = series
    .filter((_, i) => i % tickStep === 0 || i === series.length - 1)
    .map((p, _, arr) => ({ t: p.t, i: series.indexOf(p) }))

  // Y-axis ticks (5 price levels)
  const yTicks = Array.from({ length: 5 }, (_, i) => {
    const v = minP + (i / 4) * priceRange
    return { v, y: yPx(v) }
  })

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="spotFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.01" />
        </linearGradient>
        <clipPath id="chartClip">
          <rect x={PAD.left} y={PAD.top} width={chartW} height={chartH} />
        </clipPath>
      </defs>

      {/* Y-grid + labels */}
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={PAD.left} y1={t.y} x2={W - PAD.right} y2={t.y} stroke="#1e293b" strokeWidth="1" />
          <text x={PAD.left - 6} y={t.y + 4} fontSize="9" fill="#475569" textAnchor="end">
            {fmt(t.v)}
          </text>
        </g>
      ))}

      {/* X-axis ticks */}
      {xTicks.map(({ t, i }) => (
        <text key={i} x={xPx(i)} y={H - PAD.bottom + 14} fontSize="8" fill="#475569" textAnchor="middle">
          {fmtTime(t)}
        </text>
      ))}

      {/* Clipped chart area */}
      <g clipPath="url(#chartClip)">
        {/* Spot fill */}
        <path d={spotArea} fill="url(#spotFill)" />
        {/* Max pain line */}
        <path d={mpPath}   fill="none" stroke="#10b981" strokeWidth="1.5" strokeDasharray="5,3" strokeLinejoin="round" />
        {/* Spot line */}
        <path d={spotPath} fill="none" stroke="#f59e0b" strokeWidth="2"   strokeLinejoin="round" />
        {/* PCR line (secondary axis, thinner) */}
        {pcrPath && <path d={pcrPath} fill="none" stroke="#818cf8" strokeWidth="1" strokeDasharray="2,4" strokeLinejoin="round" opacity="0.6" />}
      </g>

      {/* Axes */}
      <line x1={PAD.left} y1={PAD.top}       x2={PAD.left}        y2={PAD.top + chartH} stroke="#334155" strokeWidth="1" />
      <line x1={PAD.left} y1={PAD.top + chartH} x2={W - PAD.right} y2={PAD.top + chartH} stroke="#334155" strokeWidth="1" />

      {/* Legend */}
      <g transform={`translate(${PAD.left + 8}, ${PAD.top + 6})`}>
        <line x1="0" y1="4" x2="16" y2="4" stroke="#f59e0b" strokeWidth="2" />
        <text x="20" y="7" fontSize="8" fill="#f59e0b">Spot</text>
        <line x1="60" y1="4" x2="76" y2="4" stroke="#10b981" strokeWidth="1.5" strokeDasharray="5,3" />
        <text x="80" y="7" fontSize="8" fill="#10b981">Max Pain</text>
        <line x1="142" y1="4" x2="158" y2="4" stroke="#818cf8" strokeWidth="1" strokeDasharray="2,4" />
        <text x="162" y="7" fontSize="8" fill="#818cf8" opacity="0.8">PCR</text>
      </g>

      {/* PCR right-axis labels */}
      {pcrs.length > 0 && [minPcr, (minPcr + maxPcr) / 2, maxPcr].map((v, i) => (
        <text key={i} x={W - PAD.right + 4} y={yPcr(v) + 4} fontSize="8" fill="#818cf8" opacity="0.7">
          {v.toFixed(2)}
        </text>
      ))}
    </svg>
  )
}
