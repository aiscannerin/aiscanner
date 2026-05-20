import { motion } from 'framer-motion'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { cn } from '../../utils/cn'

const variantStyles = {
  primary:
    'bg-gradient-to-r from-[#0066ff] to-[#0044cc] text-white font-semibold ' +
    'border border-[rgba(179,197,255,0.2)] shadow-glow-btn ' +
    'hover:from-[#1a7aff] hover:to-[#0055dd] hover:shadow-[0_0_28px_rgba(0,102,255,0.65)]',
  ghost:
    'bg-transparent border border-outline-variant text-on-surface-variant font-medium ' +
    'hover:border-primary/50 hover:text-on-surface hover:bg-white/[0.03]',
  outline:
    'bg-transparent border border-primary/40 text-primary font-medium ' +
    'hover:bg-primary/10 hover:border-primary',
  cyan:
    'bg-gradient-to-r from-[#00c8d7] to-[#00f1fe] text-[#002022] font-semibold ' +
    'border border-transparent shadow-glow-cyan ' +
    'hover:shadow-[0_0_28px_rgba(0,241,254,0.55)]',
}

const sizeStyles = {
  sm: 'px-4 py-1.5 text-sm rounded',
  md: 'px-5 py-2 text-sm rounded',
  lg: 'px-7 py-3 text-[15px] rounded',
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  className = '',
  disabled = false,
  ...props
}) {
  const reduced = useReducedMotion()

  return (
    <motion.button
      whileHover={reduced || disabled ? {} : { scale: 1.025 }}
      whileTap={reduced || disabled ? {} : { scale: 0.965 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
      disabled={disabled}
      className={cn(
        'inline-flex items-center gap-2 transition-all duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
        'disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none',
        variantStyles[variant] ?? variantStyles.primary,
        sizeStyles[size] ?? sizeStyles.md,
        className,
      )}
      {...props}
    >
      {children}
    </motion.button>
  )
}
