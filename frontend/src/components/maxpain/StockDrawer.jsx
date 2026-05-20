import { useEffect, useState, useCallback } from 'react'
import { X, RefreshCw, TrendingUp, TrendingDown, ExternalLink, Copy } from 'lucide-react'
import MaxPainChart from './MaxPainChart'
import OIChart from './OIChart'
import ScoreBreakdown from './ScoreBreakdown'
import HistoryPanel from './HistoryPanel'
import { maxpainApi } from '../../api/maxpain'
import ConvictionBadge from './ConvictionBadge'
import SignalExplanation from './SignalExplanation'
import { MaxPainBar, OIWallBalance, ReversalGauge, ExpiryCountdown, DistanceBar } from './MiniVisuals'

function Tab({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-xs font-semibold rounded-lg transition-colors ${
        active
          ? 'bg-violet-600 text-white'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
      }`}
    >
      {label}
    </button>
  )
}

function StatRow({ label, value, accent }) {
  return (
    <div className="flex justify-between items-center py-2 border-b border-slate-800/50 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-semibold ${accent || 'text-slate-300'}`}>{value ?? '—'}</span>
    </div>
  )
}

function OIZoneList({ title, zones, keyField, color }) {
  if (!zones?.length) return null
  return (
    <div>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">{title}</p>
      {zones.map((z, i) => (
        <div key={i} className="flex justify-between text-xs py-1 border-b border-slate-800/30 last:border-0">
          <span className="text-slate-400">₹{z.strike?.toLocaleString('en-IN')}</span>
          <span className={color}>{formatOI(z[keyField])}</span>
        </div>
      ))}
    </div>
  )
}

export default function StockDrawer({ stock: initialStock, onClose }) {
  const [stock, setStock] = useState(initialStock)
  const [tab, setTab] = useState('overview')
  const [loading, setLoading] = useState(false)
  const [expiry, setExpiry] = useState(initialStock?.expiry)

  const refresh = useCallback(async (exp) => {
    if (!initialStock?.symbol) return
    setLoading(true)
    try {
      const res = await maxpainApi.symbolDetail(initialStock.symbol, exp)
      setStock(res.data.data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [initialStock?.symbol])

  useEffect(() => {
    setStock(initialStock)
    setExpiry(initialStock?.expiry)
    setTab('overview')
  }, [initialStock?.symbol])

  if (!stock) return null

  const pcrColor = stock.pcr > 1.2 ? 'text-emerald-400' : stock.pcr < 0.8 ? 'text-rose-400' : 'text-slate-400'
  const distColor = stock.distance_pct >= 6 ? 'text-red-400' : stock.distance_pct >= 4 ? 'text-orange-400'
    : stock.distance_pct >= 2 ? 'text-yellow-400' : 'text-slate-400'

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed right-0 top-0 bottom-0 w-full max-w-xl bg-[#0a0d14] border-l border-slate-700/50 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2 mb-0.5">
                <h2 className="text-lg font-bold text-slate-100">{stock.symbol}</h2>
                {stock.direction === 'bullish'
                  ? <TrendingUp className="w-4 h-4 text-emerald-400" />
                  : <TrendingDown className="w-4 h-4 text-rose-400" />
                }
              </div>
              <p className="text-xs text-slate-500">
                ₹{stock.spot_price?.toLocaleString('en-IN', { maximumFractionDigits: 2 })} spot
                {' · '}
                <span className={distColor}>{stock.distance_pct?.toFixed(2)}% from max pain</span>
              </p>
              <div className="mt-1.5">
                <ConvictionBadge row={stock} size="xs" />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* TradingView link */}
            <a
              href={`https://www.tradingview.com/chart/?symbol=NSE%3A${stock.symbol}`}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1.5 rounded-lg text-slate-400 hover:text-violet-400 hover:bg-slate-800 transition-colors"
              title="Open in TradingView"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
            <button
              onClick={() => navigator.clipboard?.writeText(stock.symbol)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
              title="Copy symbol"
            >
              <Copy className="w-4 h-4" />
            </button>
            {stock.all_expiries?.length > 1 && (
              <select
                className="bg-slate-800 border border-slate-700 rounded text-xs text-slate-300 px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-500/50"
                value={expiry}
                onChange={e => { setExpiry(e.target.value); refresh(e.target.value) }}
              >
                {stock.all_expiries.map(e => <option key={e} value={e}>{e}</option>)}
              </select>
            )}
            <button
              onClick={() => refresh(expiry)}
              disabled={loading}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Signal narrative — replaces plain direction banner */}
        <div className={`px-5 py-2.5 border-b ${
          stock.direction === 'bullish'
            ? 'bg-emerald-500/8 border-emerald-500/20'
            : 'bg-rose-500/8 border-rose-500/20'
        }`}>
          <SignalExplanation row={stock} maxLines={2} /></div>

        {/* Tabs */}
        <div className="flex gap-1 px-4 py-3 border-b border-slate-800">
          {['overview', 'max pain', 'oi chart', 'reversal score', 'history', 'option chain'].map(t => (
            <Tab key={t} label={t.replace(/\b\w/g, c => c.toUpperCase())} active={tab === t} onClick={() => setTab(t)} />
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {tab === 'overview' && (
            <>
              {/* ── Mini Visualizations ─────────────────────────────── */}
              <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800 space-y-5">
                <MaxPainBar spotPrice={stock.spot_price} maxPain={stock.max_pain} />
                <div className="border-t border-slate-800/60 pt-4">
                  <OIWallBalance
                    ceWallStrike={stock.ce_oi_wall}
                    peWallStrike={stock.pe_oi_wall}
                    ceWallOi={stock.ce_oi_wall_oi}
                    peWallOi={stock.pe_oi_wall_oi}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
                  <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-3">Reversal Score</p>
                  <ReversalGauge
                    score={stock.reversal_score}
                    color={stock.reversal_color}
                    category={stock.reversal_category}
                  />
                </div>
                <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
                  <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-3">Expiry Pressure</p>
                  <ExpiryCountdown
                    daysToExpiry={stock.days_to_expiry}
                    expiry={stock.expiry}
                  />
                </div>
              </div>

              <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
                <DistanceBar distancePct={stock.distance_pct} level={stock.distance_level} />
              </div>

              {/* ── Stats ────────────────────────────────────────────── */}
              <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
                <StatRow label="Spot Price" value={`₹${stock.spot_price?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`} />
                <StatRow label="Max Pain Strike" value={`₹${stock.max_pain?.toLocaleString('en-IN')}`} accent="text-emerald-400" />
                <StatRow label="Distance %" value={`${stock.distance_pct?.toFixed(2)}%`} accent={distColor} />
                <StatRow label="PCR" value={stock.pcr?.toFixed(3)} accent={pcrColor} />
                <StatRow label="PCR Bias" value={stock.pcr_bias} accent={pcrColor} />
                <StatRow label="OI Bias" value={stock.oi_bias} />
                <StatRow label="Days to Expiry" value={`${stock.days_to_expiry}d`} accent={stock.days_to_expiry <= 5 ? 'text-orange-400' : undefined} />
                <StatRow label="Expiry" value={stock.expiry} />
                <StatRow label="Total CE OI" value={formatOI(stock.total_ce_oi)} accent="text-indigo-400" />
                <StatRow label="Total PE OI" value={formatOI(stock.total_pe_oi)} accent="text-emerald-400" />
                <StatRow label="CE Wall Strike" value={`₹${stock.ce_oi_wall?.toLocaleString('en-IN')}`} accent="text-indigo-400" />
                <StatRow label="PE Wall Strike" value={`₹${stock.pe_oi_wall?.toLocaleString('en-IN')}`} accent="text-emerald-400" />
              </div>

              {/* OI Zones */}
              {stock.oi_zones && (
                <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800 grid grid-cols-2 gap-4">
                  <OIZoneList title="Resistance Zones (CE OI)" zones={stock.oi_zones.resistance_zones} keyField="ce_oi" color="text-indigo-400" />
                  <OIZoneList title="Support Zones (PE OI)" zones={stock.oi_zones.support_zones} keyField="pe_oi" color="text-emerald-400" />
                </div>
              )}
            </>
          )}

          {tab === 'max pain' && (
            <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
              <p className="text-xs font-semibold text-slate-400 mb-3 uppercase tracking-wider">Max Pain Distribution</p>
              <MaxPainChart
                painValues={stock.pain_values}
                spotPrice={stock.spot_price}
                maxPain={stock.max_pain}
                height={240}
              />
              <div className="mt-3 text-xs text-slate-500 text-center">
                Strike with minimum total option writer loss = Max Pain
              </div>
            </div>
          )}

          {tab === 'oi chart' && (
            <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
              <p className="text-xs font-semibold text-slate-400 mb-3 uppercase tracking-wider">OI Buildup by Strike</p>
              <OIChart
                strikes={stock.option_chain || []}
                spotPrice={stock.spot_price}
                maxPain={stock.max_pain}
                maxStrikes={24}
              />
            </div>
          )}

          {tab === 'reversal score' && (
            <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
              <p className="text-xs font-semibold text-slate-400 mb-4 uppercase tracking-wider">Reversal Probability Score</p>
              <ScoreBreakdown
                score={stock.reversal_score}
                category={stock.reversal_category}
                color={stock.reversal_color}
                breakdown={stock.reversal_breakdown}
                direction={stock.direction}
              />
            </div>
          )}

          {tab === 'history' && (
            <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800">
              <p className="text-xs font-semibold text-slate-400 mb-4 uppercase tracking-wider">Historical Analysis</p>
              <HistoryPanel symbol={stock.symbol} expiry={expiry} />
            </div>
          )}

          {tab === 'option chain' && (
            <OptionChainTable strikes={stock.option_chain || []} spotPrice={stock.spot_price} maxPain={stock.max_pain} />
          )}
        </div>

        {/* Footer timestamp */}
        {stock.timestamp && (
          <div className="px-5 py-2 border-t border-slate-800 text-[10px] text-slate-600">
            Last updated: {new Date(stock.timestamp).toLocaleTimeString()}
          </div>
        )}
      </div>
    </>
  )
}

function OptionChainTable({ strikes, spotPrice, maxPain }) {
  const near = [...strikes]
    .sort((a, b) => Math.abs(a.strike - spotPrice) - Math.abs(b.strike - spotPrice))
    .slice(0, 20)
    .sort((a, b) => b.strike - a.strike)

  return (
    <div className="bg-slate-900/60 rounded-xl border border-slate-800 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-slate-800">
              <th className="px-3 py-2 text-left text-indigo-400 font-semibold">CE OI</th>
              <th className="px-3 py-2 text-left text-indigo-400 font-semibold">CE Chg</th>
              <th className="px-3 py-2 text-left text-indigo-400 font-semibold">CE IV</th>
              <th className="px-3 py-2 text-center text-slate-300 font-bold">Strike</th>
              <th className="px-3 py-2 text-right text-emerald-400 font-semibold">PE IV</th>
              <th className="px-3 py-2 text-right text-emerald-400 font-semibold">PE Chg</th>
              <th className="px-3 py-2 text-right text-emerald-400 font-semibold">PE OI</th>
            </tr>
          </thead>
          <tbody>
            {near.map(s => {
              const isSpot = Math.abs(s.strike - spotPrice) === Math.min(...near.map(n => Math.abs(n.strike - spotPrice)))
              const isMaxPain = s.strike === maxPain
              return (
                <tr
                  key={s.strike}
                  className={`border-b border-slate-800/40 ${isSpot ? 'bg-amber-500/5' : isMaxPain ? 'bg-emerald-500/5' : ''}`}
                >
                  <td className="px-3 py-1.5 text-indigo-300">{formatOI(s.ce_oi)}</td>
                  <td className={`px-3 py-1.5 ${s.ce_oi_change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {s.ce_oi_change >= 0 ? '+' : ''}{formatOI(s.ce_oi_change)}
                  </td>
                  <td className="px-3 py-1.5 text-slate-400">{s.ce_iv?.toFixed(1)}%</td>
                  <td className={`px-3 py-1.5 text-center font-bold ${isSpot ? 'text-amber-400' : isMaxPain ? 'text-emerald-400' : 'text-slate-300'}`}>
                    {s.strike?.toLocaleString('en-IN')}
                    {isSpot && ' ●'}
                    {isMaxPain && ' ▲'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-slate-400">{s.pe_iv?.toFixed(1)}%</td>
                  <td className={`px-3 py-1.5 text-right ${s.pe_oi_change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {s.pe_oi_change >= 0 ? '+' : ''}{formatOI(s.pe_oi_change)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-emerald-300">{formatOI(s.pe_oi)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 text-[10px] text-slate-600 flex gap-4">
        <span className="text-amber-400">●</span> Spot price near
        <span className="text-emerald-400">▲</span> Max pain strike
      </div>
    </div>
  )
}

function formatOI(n) {
  if (!n) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e7) return sign + (abs / 1e7).toFixed(1) + 'Cr'
  if (abs >= 1e5) return sign + (abs / 1e5).toFixed(1) + 'L'
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(0) + 'K'
  return n.toString()
}
