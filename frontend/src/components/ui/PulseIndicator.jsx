import { cn } from '../../utils/cn'

const colorMap = {
  bullish: { dot: 'bg-bullish',            ring: 'border-bullish',            text: 'text-bullish' },
  bearish: { dot: 'bg-bearish',            ring: 'border-bearish',            text: 'text-bearish' },
  primary: { dot: 'bg-primary',            ring: 'border-primary',            text: 'text-primary' },
  cyan:    { dot: 'bg-secondary-container', ring: 'border-secondary-container', text: 'text-secondary-container' },
  amber:   { dot: 'bg-amber',              ring: 'border-amber',              text: 'text-amber' },
}

const sizeMap = {
  xs: { dot: 'w-1.5 h-1.5', ring: 'w-3 h-3' },
  sm: { dot: 'w-2 h-2',     ring: 'w-4 h-4' },
  md: { dot: 'w-2.5 h-2.5', ring: 'w-5 h-5' },
  lg: { dot: 'w-3 h-3',     ring: 'w-6 h-6' },
}

/**
 * Animated "live" pulse dot with optional label.
 * Used for LIVE badges, active scanner status, real-time data indicators.
 */
export function PulseIndicator({ color = 'bullish', size = 'sm', label, labelClass = '' }) {
  const c = colorMap[color] ?? colorMap.bullish
  const s = sizeMap[size]   ?? sizeMap.sm

  return (
    <div className="inline-flex items-center gap-2">
      {/* Dot + expanding ring */}
      <span className="relative inline-flex items-center justify-center">
        <span
          className={cn(
            'absolute rounded-full border animate-ping-slow opacity-50',
            c.ring,
            s.ring,
          )}
        />
        <span className={cn('relative rounded-full', c.dot, s.dot)} />
      </span>

      {label && (
        <span className={cn('font-mono text-label-caps tracking-widest uppercase', c.text, labelClass)}>
          {label}
        </span>
      )}
    </div>
  )
}
