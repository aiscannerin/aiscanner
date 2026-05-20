import { motion } from 'framer-motion'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { cn } from '../../utils/cn'

/**
 * Base glass card — Level 1 elevation from the Stitch design system.
 * backdrop-blur(20px) + rgba(10,15,30,0.72) fill + 1px rgba(255,255,255,0.07) border.
 */
export function GlassCard({
  children,
  className = '',
  glow = false,
  glowColor = 'primary',
  hoverable = false,
  as: Tag = 'div',
  ...props
}) {
  const reduced = useReducedMotion()

  const glowClass = {
    primary: 'shadow-glow-primary',
    cyan:    'shadow-glow-cyan',
    none:    '',
  }[glowColor] ?? ''

  if (hoverable) {
    return (
      <motion.div
        whileHover={reduced ? {} : { y: -2, boxShadow: '0 12px 48px rgba(0,0,0,0.6)' }}
        transition={{ type: 'spring', stiffness: 300, damping: 28 }}
        className={cn(
          'glass rounded-lg transition-colors duration-200',
          glow && glowClass,
          'hover:border-[rgba(255,255,255,0.12)]',
          className,
        )}
        {...props}
      >
        {children}
      </motion.div>
    )
  }

  return (
    <div
      className={cn(
        'glass rounded-lg',
        glow && glowClass,
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
