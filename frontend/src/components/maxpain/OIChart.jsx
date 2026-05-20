// OI Buildup horizontal bar chart — CE vs PE OI per strike
export default function OIChart({ strikes = [], spotPrice, maxPain, maxStrikes = 20 }) {
  if (!strikes.length) return (
    <div className="flex items-center justify-center h-40 text-slate-500 text-sm">No OI data</div>
  )

  // Show strikes nearest to spot price
  const sorted = [...strikes].sort((a, b) => Math.abs(a.strike - spotPrice) - Math.abs(b.strike - spotPrice))
  const visible = sorted.slice(0, maxStrikes).sort((a, b) => b.strike - a.strike)

  const maxOI = Math.max(...visible.flatMap(s => [s.ce_oi, s.pe_oi]))

  const BAR_H = 18
  const GAP = 6
  const LABEL_W = 70
  const BAR_AREA = 220
  const ROW_H = BAR_H * 2 + GAP + 4
  const svgH = visible.length * ROW_H + 40
  const W = LABEL_W + BAR_AREA * 2 + 20

  return (
    <svg viewBox={`0 0 ${W} ${svgH}`} className="w-full" style={{ height: svgH }}>
      {/* Center label */}
      <text x={LABEL_W + BAR_AREA} y={16} fontSize="8" fill="#475569" textAnchor="middle">Strike</text>
      <text x={LABEL_W + BAR_AREA - BAR_AREA / 2} y={16} fontSize="8" fill="#4f46e5" textAnchor="middle">CE OI →</text>
      <text x={LABEL_W + BAR_AREA + BAR_AREA / 2} y={16} fontSize="8" fill="#10b981" textAnchor="middle">← PE OI</text>

      {visible.map((s, i) => {
        const y = 26 + i * ROW_H
        const ceW = maxOI > 0 ? (s.ce_oi / maxOI) * (BAR_AREA - 10) : 0
        const peW = maxOI > 0 ? (s.pe_oi / maxOI) * (BAR_AREA - 10) : 0
        const isSpot = Math.abs(s.strike - spotPrice) < (visible[0]?.strike - visible[1]?.strike || 50) / 2
        const isMaxPain = s.strike === maxPain

        const labelColor = isSpot ? '#f59e0b' : isMaxPain ? '#10b981' : '#94a3b8'

        return (
          <g key={s.strike}>
            {/* Strike label (center) */}
            <text
              x={LABEL_W + BAR_AREA}
              y={y + BAR_H}
              fontSize="9"
              fill={labelColor}
              textAnchor="middle"
              fontWeight={isSpot || isMaxPain ? '700' : '400'}
            >
              {s.strike.toLocaleString('en-IN')}
              {isSpot ? ' ●' : isMaxPain ? ' ▲' : ''}
            </text>

            {/* CE bar (left side, grows left from center) */}
            <rect
              x={LABEL_W + BAR_AREA - ceW}
              y={y + 2}
              width={ceW}
              height={BAR_H - 4}
              rx="2"
              fill={s.ce_oi_change > 0 ? '#4f46e5' : '#312e81'}
              opacity="0.85"
            />
            {ceW > 20 && (
              <text x={LABEL_W + BAR_AREA - ceW + 4} y={y + BAR_H - 3} fontSize="7" fill="#a5b4fc">
                {formatOI(s.ce_oi)}
              </text>
            )}

            {/* PE bar (right side, grows right from center) */}
            <rect
              x={LABEL_W + BAR_AREA + 1}
              y={y + 2}
              width={peW}
              height={BAR_H - 4}
              rx="2"
              fill={s.pe_oi_change > 0 ? '#10b981' : '#065f46'}
              opacity="0.85"
            />
            {peW > 20 && (
              <text x={LABEL_W + BAR_AREA + peW - 4} y={y + BAR_H - 3} fontSize="7" fill="#6ee7b7" textAnchor="end">
                {formatOI(s.pe_oi)}
              </text>
            )}
          </g>
        )
      })}

      {/* Center axis */}
      <line
        x1={LABEL_W + BAR_AREA}
        y1={24}
        x2={LABEL_W + BAR_AREA}
        y2={svgH - 10}
        stroke="#1e293b"
        strokeWidth="1"
      />
    </svg>
  )
}

function formatOI(n) {
  if (!n) return '0'
  if (n >= 1e7) return (n / 1e7).toFixed(1) + 'Cr'
  if (n >= 1e5) return (n / 1e5).toFixed(1) + 'L'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K'
  return n.toString()
}
