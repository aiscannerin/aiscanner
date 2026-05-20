import { useMemo, useRef, useEffect } from 'react'

// Pure SVG max pain distribution chart
export default function MaxPainChart({ painValues = [], spotPrice, maxPain, height = 200 }) {
  if (!painValues.length) return (
    <div className="flex items-center justify-center h-40 text-slate-500 text-sm">
      No pain data available
    </div>
  )

  const W = 600
  const H = height
  const PAD = { top: 16, right: 20, bottom: 40, left: 56 }

  const maxTotal = Math.max(...painValues.map(p => p.total_pain))
  const minStrike = painValues[0].strike
  const maxStrike = painValues[painValues.length - 1].strike
  const strikeRange = maxStrike - minStrike || 1

  function xPct(strike) {
    return ((strike - minStrike) / strikeRange)
  }

  function xPx(strike) {
    return PAD.left + xPct(strike) * (W - PAD.left - PAD.right)
  }

  function yPx(val) {
    return PAD.top + (1 - val / maxTotal) * (H - PAD.top - PAD.bottom)
  }

  // Build SVG path for the pain curve
  const path = painValues.map((p, i) => {
    const x = xPx(p.strike)
    const y = yPx(p.total_pain)
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')

  // Area fill path
  const areaPath = `${path} L${xPx(maxStrike).toFixed(1)},${(H - PAD.bottom).toFixed(1)} L${xPx(minStrike).toFixed(1)},${(H - PAD.bottom).toFixed(1)} Z`

  const spotX = xPx(spotPrice)
  const maxPainX = xPx(maxPain)

  // Y axis ticks
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
    y: yPx(f * maxTotal),
    label: formatLargeNum(f * maxTotal),
  }))

  // Strike ticks (5 evenly spaced)
  const nTicks = 6
  const xTicks = Array.from({ length: nTicks }, (_, i) => {
    const strike = minStrike + (i / (nTicks - 1)) * strikeRange
    return { x: xPx(strike), label: Math.round(strike).toLocaleString('en-IN') }
  })

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height }}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <linearGradient id="painGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#7c3aed" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#7c3aed" stopOpacity="0.03" />
        </linearGradient>
        <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#4f46e5" />
          <stop offset="100%" stopColor="#7c3aed" />
        </linearGradient>
      </defs>

      {/* Grid lines */}
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={PAD.left} y1={t.y} x2={W - PAD.right} y2={t.y} stroke="#1e293b" strokeWidth="1" />
          <text x={PAD.left - 6} y={t.y + 4} fontSize="9" fill="#475569" textAnchor="end">{t.label}</text>
        </g>
      ))}

      {/* X ticks */}
      {xTicks.map((t, i) => (
        <text key={i} x={t.x} y={H - PAD.bottom + 14} fontSize="9" fill="#475569" textAnchor="middle">{t.label}</text>
      ))}

      {/* Area fill */}
      <path d={areaPath} fill="url(#painGrad)" />

      {/* Main curve */}
      <path d={path} fill="none" stroke="url(#lineGrad)" strokeWidth="2" strokeLinejoin="round" />

      {/* Max pain line */}
      {maxPain >= minStrike && maxPain <= maxStrike && (
        <g>
          <line x1={maxPainX} y1={PAD.top} x2={maxPainX} y2={H - PAD.bottom} stroke="#10b981" strokeWidth="1.5" strokeDasharray="4,3" />
          <text x={maxPainX} y={PAD.top - 4} fontSize="9" fill="#10b981" textAnchor="middle">Max Pain</text>
          <text x={maxPainX} y={PAD.top + 7} fontSize="8" fill="#10b981" textAnchor="middle">
            ₹{maxPain?.toLocaleString('en-IN')}
          </text>
        </g>
      )}

      {/* Spot price line */}
      {spotPrice >= minStrike && spotPrice <= maxStrike && (
        <g>
          <line x1={spotX} y1={PAD.top} x2={spotX} y2={H - PAD.bottom} stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4,3" />
          <text x={spotX} y={PAD.top - 4} fontSize="9" fill="#f59e0b" textAnchor="middle">Spot</text>
          <text x={spotX} y={PAD.top + 7} fontSize="8" fill="#f59e0b" textAnchor="middle">
            ₹{spotPrice?.toLocaleString('en-IN')}
          </text>
        </g>
      )}

      {/* Axes */}
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke="#334155" strokeWidth="1" />
      <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke="#334155" strokeWidth="1" />

      {/* Legend */}
      <g transform={`translate(${W - PAD.right - 110}, ${PAD.top})`}>
        <line x1="0" y1="5" x2="14" y2="5" stroke="#10b981" strokeWidth="1.5" strokeDasharray="4,3" />
        <text x="18" y="8" fontSize="8" fill="#10b981">Max Pain</text>
        <line x1="0" y1="18" x2="14" y2="18" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4,3" />
        <text x="18" y="21" fontSize="8" fill="#f59e0b">Spot Price</text>
      </g>
    </svg>
  )
}

function formatLargeNum(n) {
  if (!n) return '0'
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return Math.round(n).toString()
}
