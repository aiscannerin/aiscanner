import { cn } from '../../utils/cn'

/**
 * Small all-caps Space Grotesk label displayed above section headings.
 * Matches "label-caps" typography token from Stitch design system.
 */
export function SectionLabel({ children, className = '' }) {
  return (
    <span
      className={cn(
        'inline-block font-mono text-label-caps tracking-[0.12em] uppercase text-primary',
        className,
      )}
    >
      {children}
    </span>
  )
}
