/**
 * SignalExplanation — generates a human-readable trader narrative from scanner row metrics.
 * Pure derived text — no API calls, no side-effects.
 *
 * Answers: WHY is this signal interesting? WHAT supports it?
 */

export function buildExplanation(row) {
  if (!row) return ''

  const {
    symbol           = '—',
    spot_price       = 0,
    max_pain         = 0,
    distance_pct     = 0,
    direction        = 'bearish',
    pcr              = 1,
    pcr_bias         = 'neutral',
    oi_bias          = 'neutral',
    reversal_score   = 0,
    reversal_category = 'Weak',
    days_to_expiry   = 0,
    ce_oi_wall       = null,
    pe_oi_wall       = null,
    atm_ce_iv        = 0,
    atm_pe_iv        = 0,
    distance_level   = 'low',
  } = row

  const parts = []

  // 1. Core position relative to max pain
  const aboveBelow = spot_price > max_pain ? 'above' : 'below'
  const distWord   = distance_level === 'extreme' ? 'significantly'
    : distance_level === 'high' ? 'notably'
    : distance_level === 'moderate' ? 'moderately'
    : 'slightly'
  parts.push(
    `${symbol} is trading ${distWord} ${distance_pct.toFixed(1)}% ${aboveBelow} max pain (₹${max_pain.toLocaleString('en-IN')}).`
  )

  // 2. PCR interpretation
  if (pcr >= 1.5) {
    parts.push(`PCR of ${pcr.toFixed(2)} signals strong put accumulation — bulls are defensively hedged.`)
  } else if (pcr >= 1.2) {
    parts.push(`PCR of ${pcr.toFixed(2)} leans bullish — more protective puts than calls.`)
  } else if (pcr <= 0.6) {
    parts.push(`PCR of ${pcr.toFixed(2)} signals heavy call buying — bearish pressure from writers.`)
  } else if (pcr <= 0.8) {
    parts.push(`PCR of ${pcr.toFixed(2)} leans bearish — call OI dominates.`)
  } else {
    parts.push(`PCR of ${pcr.toFixed(2)} is balanced — no strong directional lean.`)
  }

  // 3. OI wall context
  if (pe_oi_wall && direction === 'bearish') {
    parts.push(`Strong PE support near ₹${pe_oi_wall.toLocaleString('en-IN')} may cushion further downside.`)
  } else if (ce_oi_wall && direction === 'bullish') {
    parts.push(`CE resistance at ₹${ce_oi_wall.toLocaleString('en-IN')} may cap any further upside.`)
  }

  // 4. OI bias alignment
  if (oi_bias === direction) {
    parts.push(`OI buildup aligns with the ${direction} mean-reversion thesis.`)
  } else if (oi_bias !== 'neutral' && oi_bias !== direction) {
    parts.push(`OI bias is ${oi_bias} — partially conflicts with the expected ${direction} move.`)
  }

  // 5. Expiry context
  if (days_to_expiry <= 2) {
    parts.push(`Only ${days_to_expiry} day${days_to_expiry === 1 ? '' : 's'} to expiry — max pain pinning effect is highest.`)
  } else if (days_to_expiry <= 5) {
    parts.push(`${days_to_expiry} days to expiry — entering the high-influence max pain window.`)
  } else {
    parts.push(`${days_to_expiry} days to expiry provides time for mean reversion to play out.`)
  }

  // 6. IV context (only if meaningful)
  const avgIv = ((atm_ce_iv || 0) + (atm_pe_iv || 0)) / 2
  if (avgIv >= 30) {
    parts.push(`ATM IV is elevated at ~${avgIv.toFixed(0)}% — options are expensive; consider premium-selling strategies.`)
  } else if (avgIv >= 18) {
    parts.push(`ATM IV around ${avgIv.toFixed(0)}% — moderate volatility environment.`)
  }

  // 7. Signal strength conclusion
  const conclusion = reversal_score >= 80
    ? `Overall: ${reversal_category} conviction reversal signal (${reversal_score}/100) — worth close monitoring.`
    : reversal_score >= 60
      ? `Overall: ${reversal_category} signal (${reversal_score}/100) — conditions favour mean reversion.`
      : reversal_score >= 40
        ? `Overall: ${reversal_category} signal (${reversal_score}/100) — wait for confirmation before acting.`
        : `Overall: ${reversal_category} signal (${reversal_score}/100) — deviation alone is insufficient; multiple factors needed.`
  parts.push(conclusion)

  return parts.join(' ')
}

export default function SignalExplanation({ row, className = '', maxLines = 3 }) {
  const text = buildExplanation(row)
  if (!text) return null

  return (
    <p
      className={`text-[11px] leading-relaxed text-slate-400 ${
        maxLines === 2 ? 'line-clamp-2' : maxLines === 3 ? 'line-clamp-3' : ''
      } ${className}`}
    >
      {text}
    </p>
  )
}
