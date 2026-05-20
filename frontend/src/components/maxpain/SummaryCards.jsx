import { TrendingUp, TrendingDown, Activity, BarChart2, Zap } from 'lucide-react'

function Card({ icon: Icon, label, value, sub, accent, loading }) {
  return (
    <div className={`relative bg-[#0f1117] border rounded-xl p-4 overflow-hidden ${accent}`}>
      <div className="absolute inset-0 bg-gradient-to-br from-white/[0.02] to-transparent pointer-events-none" />
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-[11px] font-medium text-slate-500 uppercase tracking-wider mb-1">{label}</p>
          {loading ? (
            <div className="h-6 w-24 bg-slate-800 rounded animate-pulse" />
          ) : (
            <p className="text-lg font-bold text-slate-100 truncate">{value ?? '—'}</p>
          )}
          {sub && !loading && (
            <p className="text-[11px] text-slate-500 mt-0.5 truncate">{sub}</p>
          )}
        </div>
        <div className={`ml-3 p-2 rounded-lg ${accent.replace('border-', 'bg-').replace('/30', '/10')}`}>
          <Icon className={`w-4 h-4 ${accent.replace('border-', 'text-').replace('/30', '')}`} />
        </div>
      </div>
    </div>
  )
}

export default function SummaryCards({ summary, loading }) {
  const s = summary || {}

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      <Card
        icon={Activity}
        label="Stocks Scanned"
        value={s.total_scanned ?? '—'}
        sub={
          s.total_errors > 0
            ? `${s.total_hits ?? 0} hits · ${s.total_errors} NSE errors`
            : `${s.total_hits ?? 0} hits`
        }
        accent={s.total_errors > 0 ? 'border-amber-500/40' : 'border-slate-700/60'}
        loading={loading}
      />
      <Card
        icon={Zap}
        label="Highest Deviation"
        value={s.highest_deviation ? `${s.highest_deviation.symbol}` : '—'}
        sub={s.highest_deviation ? `${s.highest_deviation.distance_pct?.toFixed(2)}% away` : undefined}
        accent="border-violet-500/30"
        loading={loading}
      />
      <Card
        icon={BarChart2}
        label="Highest PCR"
        value={s.highest_pcr ? s.highest_pcr.symbol : '—'}
        sub={s.highest_pcr ? `PCR ${s.highest_pcr.pcr?.toFixed(2)}` : undefined}
        accent="border-blue-500/30"
        loading={loading}
      />
      <Card
        icon={TrendingUp}
        label="Top Bullish Setup"
        value={s.strongest_bullish ? s.strongest_bullish.symbol : '—'}
        sub={s.strongest_bullish ? `Score ${s.strongest_bullish.reversal_score}` : undefined}
        accent="border-emerald-500/30"
        loading={loading}
      />
      <Card
        icon={TrendingDown}
        label="Top Bearish Setup"
        value={s.strongest_bearish ? s.strongest_bearish.symbol : '—'}
        sub={s.strongest_bearish ? `Score ${s.strongest_bearish.reversal_score}` : undefined}
        accent="border-rose-500/30"
        loading={loading}
      />
    </div>
  )
}
