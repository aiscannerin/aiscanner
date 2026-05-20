/**
 * ConvictionBadge — derives 1–2 trader-readable signal labels from scanner row metrics.
 *
 * Color semantics (strict — no arbitrary choices):
 *   green  = bullish alignment
 *   red    = bearish risk / extreme distance
 *   amber  = warning / expiry pressure
 *   purple = high volatility regime
 *   blue   = neutral / informational
 */

export function deriveConvictionBadges(row) {
  if (!row) return []
  const badges = []

  const {
    reversal_score = 0,
    distance_pct   = 0,
    distance_level = '',
    direction      = '',
    pcr            = 1,
    days_to_expiry = 99,
    atm_ce_iv      = 0,
    atm_pe_iv      = 0,
    ce_oi_wall_oi  = 0,
    pe_oi_wall_oi  = 0,
    oi_bias        = '',
  } = row

  // ── Primary conviction level ─────────────────────────────────────
  if (reversal_score >= 80 && distance_pct >= 4) {
    badges.push({ label: 'HIGH CONVICTION', variant: 'red' })
  } else if (reversal_score >= 65) {
    badges.push({ label: 'STRONG SIGNAL', variant: direction === 'bullish' ? 'green' : 'red' })
  } else if (reversal_score >= 45) {
    badges.push({ label: 'MODERATE SIGNAL', variant: 'blue' })
  } else {
    badges.push({ label: 'WEAK SIGNAL', variant: 'slate' })
  }

  // ── Expiry pressure (overrides secondary if urgent) ────────────
  if (days_to_expiry <= 2) {
    badges.push({ label: 'EXPIRY PINNING', variant: 'amber' })
  } else if (days_to_expiry <= 5) {
    badges.push({ label: 'NEAR EXPIRY', variant: 'amber' })
  }

  // ── Trending hard away from max pain ─────────────────────────
  if (distance_pct >= 6 && badges.length < 2) {
    badges.push({ label: 'TRENDING AWAY', variant: 'red' })
  }

  // ── Volatility regime ─────────────────────────────────────────
  const maxIv = Math.max(atm_ce_iv || 0, atm_pe_iv || 0)
  if (maxIv >= 30 && badges.length < 2) {
    badges.push({ label: 'HIGH IV ENV', variant: 'purple' })
  } else if (maxIv >= 20 && badges.length < 2) {
    badges.push({ label: 'ELEVATED IV', variant: 'purple' })
  }

  // ── PCR extremes ─────────────────────────────────────────────
  if (pcr >= 1.5 && badges.length < 2) {
    badges.push({ label: 'PCR EXTREME BULL', variant: 'green' })
  } else if (pcr <= 0.6 && badges.length < 2) {
    badges.push({ label: 'PCR EXTREME BEAR', variant: 'red' })
  }

  // ── Wall dominance ────────────────────────────────────────────
  if (pe_oi_wall_oi && ce_oi_wall_oi && badges.length < 2) {
    if (pe_oi_wall_oi > ce_oi_wall_oi * 2) {
      badges.push({ label: 'STRONG PE SUPPORT', variant: 'green' })
    } else if (ce_oi_wall_oi > pe_oi_wall_oi * 2) {
      badges.push({ label: 'STRONG CE RESIST', variant: 'red' })
    }
  }

  // Return at most 2
  return badges.slice(0, 2)
}

const VARIANT_STYLES = {
  red:    'bg-rose-500/15    border-rose-500/30    text-rose-400',
  green:  'bg-emerald-500/15 border-emerald-500/30 text-emerald-400',
  amber:  'bg-amber-500/15   border-amber-500/30   text-amber-400',
  purple: 'bg-violet-500/15  border-violet-500/30  text-violet-400',
  blue:   'bg-blue-500/15    border-blue-500/30    text-blue-400',
  slate:  'bg-slate-700/30   border-slate-600/30   text-slate-400',
}

export default function ConvictionBadge({ row, size = 'sm' }) {
  const badges = deriveConvictionBadges(row)
  const textCls = size === 'xs' ? 'text-[9px]' : 'text-[10px]'

  return (
    <div className="flex flex-wrap gap-1">
      {badges.map(({ label, variant }) => (
        <span
          key={label}
          className={`${textCls} font-bold px-1.5 py-0.5 rounded border tracking-wide whitespace-nowrap
            ${VARIANT_STYLES[variant] ?? VARIANT_STYLES.slate}`}
        >
          {label}
        </span>
      ))}
    </div>
  )
}
