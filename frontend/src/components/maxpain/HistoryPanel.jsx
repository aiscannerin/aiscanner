/**
 * HistoryPanel — tabbed historical data panel shown inside StockDrawer.
 * Tabs: Trend | Drift | OI Wall | Score History
 */

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import TrendChart from './TrendChart'
import OIWallMigrationChart from './OIWallMigrationChart'
import { historyApi } from '../../api/maxpainHistory'

const WINDOWS = ['1h', '4h', '1d', '3d', '7d']

function WindowSelector({ value, onChange }) {
  return (
    <div className="flex gap-1">
      {WINDOWS.map(w => (
        <button
          key={w}
          onClick={() => onChange(w)}
          className={`px-2.5 py-1 text-xs rounded font-medium transition-colors ${
            value === w ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
          }`}
        >
          {w}
        </button>
      ))}
    </div>
  )
}

function StatChip({ label, value, accent }) {
  return (
    <div className="text-center">
      <p className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</p>
      <p className={`text-sm font-bold mt-0.5 ${accent || 'text-slate-300'}`}>{value ?? '—'}</p>
    </div>
  )
}

function DriftArrow({ trend }) {
  if (trend === 'contracting') return <TrendingDown className="w-4 h-4 text-emerald-400" />
  if (trend === 'expanding')   return <TrendingUp className="w-4 h-4 text-rose-400" />
  return <Minus className="w-4 h-4 text-slate-400" />
}

function ScoreSparkline({ series = [], height = 80 }) {
  if (!series.length) return null
  const W = 400, H = height
  const scores = series.map(p => p.score).filter(s => s != null)
  if (!scores.length) return null
  const minS = Math.min(...scores)
  const maxS = Math.max(...scores)
  const range = (maxS - minS) || 1

  const path = series
    .filter(p => p.score != null)
    .map((p, i, arr) => {
      const x = (i / (arr.length - 1 || 1)) * W
      const y = H - ((p.score - minS) / range) * H * 0.8 - H * 0.1
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const last = series[series.length - 1]
  const lastColor = (last?.score ?? 0) >= 80 ? '#ef4444'
    : (last?.score ?? 0) >= 60 ? '#f97316'
    : (last?.score ?? 0) >= 40 ? '#eab308'
    : '#6b7280'

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      <defs>
        <linearGradient id="scoreGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lastColor} stopOpacity="0.4" />
          <stop offset="100%" stopColor={lastColor} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {/* Fill */}
      <path d={`${path} L${W},${H} L0,${H} Z`} fill="url(#scoreGrad)" />
      {/* Line */}
      <path d={path} fill="none" stroke={lastColor} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

export default function HistoryPanel({ symbol, expiry }) {
  const [activeTab, setActiveTab]   = useState('trend')
  const [window,    setWindow]      = useState('1d')
  const [loading,   setLoading]     = useState(false)
  const [data,      setData]        = useState({})

  const load = useCallback(async (tab, win) => {
    setLoading(true)
    const params = { window: win, expiry: expiry || undefined }
    try {
      let res
      if (tab === 'trend')     res = await historyApi.trend(symbol, params)
      if (tab === 'drift')     res = await historyApi.drift(symbol, params)
      if (tab === 'oi-wall')   res = await historyApi.oiWall(symbol, { ...params, side: 'CE' })
      if (tab === 'oi-wall-pe') res = await historyApi.oiWall(symbol, { ...params, side: 'PE' })
      if (tab === 'score')     res = await historyApi.reversalScore(symbol, params)
      setData(prev => ({ ...prev, [`${tab}_${win}`]: res?.data?.data }))
    } catch (e) {
      console.error('History load error:', e)
    } finally {
      setLoading(false)
    }
  }, [symbol, expiry])

  useEffect(() => { load(activeTab, window) }, [activeTab, window, load])

  const cacheKey = `${activeTab}_${window}`
  const d = data[cacheKey]

  const TABS = [
    { id: 'trend',    label: 'Trend' },
    { id: 'drift',    label: 'Drift' },
    { id: 'oi-wall',  label: 'CE Wall' },
    { id: 'oi-wall-pe', label: 'PE Wall' },
    { id: 'score',    label: 'Score History' },
  ]

  return (
    <div className="space-y-4">
      {/* Tab + window selector row */}
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <div className="flex gap-1 flex-wrap">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`px-3 py-1 text-xs rounded-lg font-medium transition-colors ${
                activeTab === t.id
                  ? 'bg-violet-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <WindowSelector value={window} onChange={setWindow} />
          <button
            onClick={() => load(activeTab, window)}
            className="p-1 text-slate-500 hover:text-slate-300"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {loading && (
        <div className="space-y-2">
          {[1,2,3].map(i => (
            <div key={i} className="h-4 bg-slate-800 rounded animate-pulse" style={{ width: `${60 + i * 10}%` }} />
          ))}
          <div className="h-48 bg-slate-800 rounded animate-pulse mt-2" />
        </div>
      )}

      {!loading && activeTab === 'trend' && (
        <div className="space-y-3">
          {d?.points > 0 && (
            <div className="grid grid-cols-3 gap-2 text-center">
              <StatChip label="Data Points" value={d.points} />
              <StatChip
                label="MP Change"
                value={d.series?.length > 1
                  ? `${((d.series.at(-1)?.max_pain - d.series[0]?.max_pain) || 0) > 0 ? '+' : ''}${((d.series.at(-1)?.max_pain - d.series[0]?.max_pain) || 0).toFixed(0)}`
                  : '—'}
              />
              <StatChip
                label="Avg Distance"
                value={d.series?.length
                  ? `${(d.series.reduce((a, p) => a + (p.distance_pct || 0), 0) / d.series.length).toFixed(2)}%`
                  : '—'}
              />
            </div>
          )}
          <TrendChart series={d?.series || []} height={220} />
        </div>
      )}

      {!loading && activeTab === 'drift' && d && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-800/60 rounded-xl p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-2">Max Pain Drift</p>
              <div className="flex items-center gap-2">
                <DriftArrow trend={d.mp_drift_pct > 0 ? 'expanding' : d.mp_drift_pct < 0 ? 'contracting' : 'stable'} />
                <span className={`text-lg font-bold ${
                  (d.mp_drift_pct ?? 0) > 0 ? 'text-emerald-400'
                  : (d.mp_drift_pct ?? 0) < 0 ? 'text-rose-400'
                  : 'text-slate-400'
                }`}>
                  {d.mp_drift_pct != null ? `${d.mp_drift_pct > 0 ? '+' : ''}${d.mp_drift_pct.toFixed(2)}%` : '—'}
                </span>
              </div>
              <p className="text-[10px] text-slate-500 mt-1">
                {d.oldest_max_pain?.toLocaleString('en-IN')} → {d.latest_max_pain?.toLocaleString('en-IN')}
              </p>
            </div>
            <div className="bg-slate-800/60 rounded-xl p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-2">Distance Trend</p>
              <div className="flex items-center gap-2">
                <DriftArrow trend={d.dist_trend} />
                <span className={`text-sm font-bold capitalize ${
                  d.dist_trend === 'contracting' ? 'text-emerald-400'
                  : d.dist_trend === 'expanding' ? 'text-rose-400'
                  : 'text-slate-400'
                }`}>{d.dist_trend}</span>
              </div>
              <p className="text-[10px] text-slate-500 mt-1">
                {d.dist_first?.toFixed(2)}% → {d.dist_last?.toFixed(2)}%
              </p>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <StatChip label="Spot Drift" value={d.spot_drift_pct != null ? `${d.spot_drift_pct > 0 ? '+' : ''}${d.spot_drift_pct.toFixed(2)}%` : '—'} />
            <StatChip label="MP Speed" value={d.mp_speed_pts_hr != null ? `${d.mp_speed_pts_hr} pts/hr` : '—'} />
            <StatChip label="Snapshots" value={d.data_points} />
          </div>
          {d.series?.length > 0 && <TrendChart series={d.series} height={160} />}
        </div>
      )}

      {!loading && (activeTab === 'oi-wall' || activeTab === 'oi-wall-pe') && (
        <OIWallMigrationChart
          data={d}
          side={activeTab === 'oi-wall' ? 'CE' : 'PE'}
          height={220}
        />
      )}

      {!loading && activeTab === 'score' && d && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-2">
            <StatChip label="Current" value={d.current_score?.toFixed(1)} accent={
              (d.current_score ?? 0) >= 80 ? 'text-red-400'
              : (d.current_score ?? 0) >= 60 ? 'text-orange-400'
              : (d.current_score ?? 0) >= 40 ? 'text-yellow-400'
              : 'text-slate-400'
            } />
            <StatChip label="Peak" value={d.peak_score?.toFixed(1)} accent="text-rose-400" />
            <StatChip label="Avg" value={d.avg_score?.toFixed(1)} />
            <StatChip label="Momentum" value={d.momentum} accent={
              d.momentum === 'accelerating' ? 'text-rose-400'
              : d.momentum === 'decelerating' ? 'text-emerald-400'
              : 'text-slate-400'
            } />
          </div>
          <ScoreSparkline series={d.series || []} height={100} />
          {d.momentum && (
            <p className="text-xs text-slate-500 text-center">
              Reversal pressure is <span className={`font-semibold ${
                d.momentum === 'accelerating' ? 'text-rose-400'
                : d.momentum === 'decelerating' ? 'text-emerald-400'
                : 'text-slate-400'
              }`}>{d.momentum}</span> over the last {window}
            </p>
          )}
        </div>
      )}

      {!loading && !d && (
        <div className="text-center py-8 text-slate-500 text-sm">
          No historical data available for this window.
          <br />
          <span className="text-xs">Snapshots are captured every 5 minutes during market hours (09:15–15:30 IST).</span>
        </div>
      )}
    </div>
  )
}
