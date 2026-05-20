const FACTOR_LABELS = {
  distance_from_max_pain: { label: 'Distance from Max Pain', max: 30 },
  oi_buildup:             { label: 'OI Buildup Direction',   max: 15 },
  pcr_reading:            { label: 'PCR Extreme Reading',    max: 15 },
  near_expiry:            { label: 'Near Expiry Weight',     max: 10 },
  rsi_extreme:            { label: 'RSI Extreme',            max: 10 },
  volume_expansion:       { label: 'Volume Expansion',       max: 10 },
  vwap_deviation:         { label: 'VWAP Deviation',         max: 10 },
}

export default function ScoreBreakdown({ score, category, color, breakdown, direction }) {
  if (!breakdown) return null

  const categoryClass = score >= 80 ? 'text-red-400' : score >= 60 ? 'text-orange-400'
    : score >= 40 ? 'text-yellow-400' : 'text-slate-400'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <span className={`text-2xl font-black ${categoryClass}`}>{score}</span>
          <span className="text-slate-500 text-sm ml-1">/ 100</span>
        </div>
        <div className="text-right">
          <div className={`text-sm font-bold ${categoryClass}`}>{category} Signal</div>
          <div className={`text-xs ${direction === 'bullish' ? 'text-emerald-400' : 'text-rose-400'} capitalize`}>
            {direction} bias
          </div>
        </div>
      </div>

      {/* Main score bar */}
      <div className="bg-slate-800 rounded-full h-2 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${score}%`, backgroundColor: color }}
        />
      </div>

      {/* Factor breakdown */}
      <div className="space-y-2 pt-1">
        {Object.entries(FACTOR_LABELS).map(([key, { label, max }]) => {
          const val = breakdown[key] ?? 0
          const pct = (val / max) * 100
          return (
            <div key={key} className="space-y-0.5">
              <div className="flex justify-between text-[11px]">
                <span className="text-slate-500">{label}</span>
                <span className="text-slate-400 font-mono">{val.toFixed(1)} / {max}</span>
              </div>
              <div className="bg-slate-800 rounded-full h-1 overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${pct}%`, backgroundColor: color, opacity: 0.7 }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
