/**
 * OIWallMigrationChart — shows how the dominant CE/PE OI wall strike
 * migrates over time. Each horizontal step = wall shifted.
 */

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
}

function formatOI(n) {
  if (!n) return '0'
  if (n >= 1e7) return (n / 1e7).toFixed(1) + 'Cr'
  if (n >= 1e5) return (n / 1e5).toFixed(1) + 'L'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K'
  return n.toString()
}

export default function OIWallMigrationChart({ data, side = 'CE', height = 200 }) {
  if (!data || data.error) return (
    <div className="flex items-center justify-center" style={{ height }}>
      <p className="text-slate-500 text-sm">
        {data?.error === 'no_data'
          ? 'No historical wall data yet — requires 5-minute snapshots'
          : 'Could not load wall migration data'}
      </p>
    </div>
  )

  const series = data.series || []
  if (!series.length) return (
    <div className="flex items-center justify-center" style={{ height }}>
      <p className="text-slate-500 text-sm">No data in selected window</p>
    </div>
  )

  const W = 600
  const H = height
  const PAD = { top: 24, right: 20, bottom: 36, left: 64 }
  const chartW = W - PAD.left - PAD.right
  const chartH = H - PAD.top - PAD.bottom

  const strikes = series.map(p => p.strike).filter(Boolean)
  const ois     = series.map(p => p.oi).filter(Boolean)
  const minS = Math.min(...strikes) - 100
  const maxS = Math.max(...strikes) + 100
  const strikeRange = maxS - minS || 1
  const maxOI = Math.max(...ois) || 1

  function xPx(i)   { return PAD.left + (i / (series.length - 1 || 1)) * chartW }
  function yStrike(v) { return PAD.top + (1 - (v - minS) / strikeRange) * chartH }

  // Step-function path for strike migration
  const strikePath = series.map((p, i) => {
    if (!p.strike) return null
    const x = xPx(i).toFixed(1)
    const y = yStrike(p.strike).toFixed(1)
    if (i === 0) return `M${x},${y}`
    // Horizontal then vertical (step)
    const prevX = xPx(i - 1).toFixed(1)
    return `H${x} V${y}`
  }).filter(Boolean).join(' ')

  // OI bar heights (shown as subtle background bars)
  const color = side === 'CE' ? '#4f46e5' : '#10b981'
  const colorLight = side === 'CE' ? '#818cf8' : '#6ee7b7'

  // Y-axis strike ticks
  const uniqueStrikes = [...new Set(strikes)].sort((a, b) => a - b)
  const tickStrikes = uniqueStrikes.length <= 6 ? uniqueStrikes : [
    uniqueStrikes[0],
    uniqueStrikes[Math.floor(uniqueStrikes.length / 3)],
    uniqueStrikes[Math.floor(uniqueStrikes.length * 2 / 3)],
    uniqueStrikes[uniqueStrikes.length - 1],
  ]

  // X-axis ticks
  const tickStep = Math.max(1, Math.floor(series.length / 5))
  const xTicks = series.filter((_, i) => i % tickStep === 0 || i === series.length - 1)
    .map(p => ({ t: p.t, i: series.indexOf(p) }))

  // Shift markers
  const shifts = data.wall_shifts || []

  return (
    <div className="space-y-3">
      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="bg-slate-800/60 rounded-lg p-2">
          <p className="text-[10px] text-slate-500 uppercase">Initial Wall</p>
          <p className="text-sm font-bold text-slate-200">
            ₹{data.initial_strike?.toLocaleString('en-IN') ?? '—'}
          </p>
        </div>
        <div className="bg-slate-800/60 rounded-lg p-2">
          <p className="text-[10px] text-slate-500 uppercase">Current Wall</p>
          <p className={`text-sm font-bold ${side === 'CE' ? 'text-indigo-400' : 'text-emerald-400'}`}>
            ₹{data.current_strike?.toLocaleString('en-IN') ?? '—'}
          </p>
        </div>
        <div className="bg-slate-800/60 rounded-lg p-2">
          <p className="text-[10px] text-slate-500 uppercase">Net Migration</p>
          <p className={`text-sm font-bold ${
            (data.net_migration ?? 0) > 0 ? 'text-emerald-400'
            : (data.net_migration ?? 0) < 0 ? 'text-rose-400'
            : 'text-slate-400'
          }`}>
            {(data.net_migration ?? 0) > 0 ? '+' : ''}{data.net_migration ?? '—'} pts
          </p>
        </div>
      </div>

      {shifts.length > 0 && (
        <div className="text-[11px] text-slate-500 bg-slate-800/40 rounded-lg px-3 py-2">
          <span className="font-semibold text-slate-400">{shifts.length} wall shift{shifts.length > 1 ? 's' : ''}</span>
          {' '}detected — wall moved between strikes during this window
        </div>
      )}

      {/* Chart */}
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} preserveAspectRatio="xMidYMid meet">
        {/* Y-axis labels */}
        {tickStrikes.map((s, i) => (
          <g key={i}>
            <line x1={PAD.left} y1={yStrike(s)} x2={W - PAD.right} y2={yStrike(s)} stroke="#1e293b" strokeWidth="1" />
            <text x={PAD.left - 5} y={yStrike(s) + 4} fontSize="9" fill="#475569" textAnchor="end">
              {s.toLocaleString('en-IN')}
            </text>
          </g>
        ))}

        {/* OI bar background */}
        {series.map((p, i) => {
          if (!p.oi) return null
          const barH = (p.oi / maxOI) * 20
          return (
            <rect
              key={i}
              x={xPx(i) - 1}
              y={PAD.top + chartH - barH}
              width={Math.max(2, chartW / series.length - 1)}
              height={barH}
              fill={color}
              opacity="0.15"
            />
          )
        })}

        {/* Step-function migration path */}
        <path d={strikePath} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" />

        {/* Shift markers */}
        {shifts.map((sh, i) => {
          const idx = series.findIndex(p => p.t >= sh.t)
          if (idx < 0) return null
          return (
            <g key={i}>
              <line
                x1={xPx(idx)} y1={PAD.top}
                x2={xPx(idx)} y2={PAD.top + chartH}
                stroke="#f59e0b" strokeWidth="1" strokeDasharray="3,3" opacity="0.6"
              />
              <circle cx={xPx(idx)} cy={yStrike(sh.to_strike)} r="3" fill="#f59e0b" />
            </g>
          )
        })}

        {/* Data points */}
        {series.filter((_, i) => i % Math.max(1, Math.floor(series.length / 30)) === 0).map((p, i, arr) => (
          p.strike && (
            <circle
              key={i}
              cx={xPx(series.indexOf(p))}
              cy={yStrike(p.strike)}
              r="2"
              fill={colorLight}
              opacity="0.8"
            />
          )
        ))}

        {/* X-axis ticks */}
        {xTicks.map(({ t, i }) => (
          <text key={i} x={xPx(i)} y={H - 6} fontSize="8" fill="#475569" textAnchor="middle">
            {fmtTime(t)}
          </text>
        ))}

        {/* Axes */}
        <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + chartH} stroke="#334155" />
        <line x1={PAD.left} y1={PAD.top + chartH} x2={W - PAD.right} y2={PAD.top + chartH} stroke="#334155" />

        {/* Side label */}
        <text x={W - PAD.right - 4} y={PAD.top - 6} fontSize="9" fill={color} textAnchor="end" fontWeight="600">
          {side} OI Wall (Rank #{data.rank ?? 1})
        </text>
      </svg>
    </div>
  )
}
