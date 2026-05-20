import { createContext, useContext } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { X, Info, CheckCircle2, AlertTriangle } from 'lucide-react'
import { useToast } from '../hooks/useToast'

const ToastCtx = createContext(null)

const VARIANT_STYLES = {
  info:    { bar: 'bg-primary',   icon: Info,           iconColor: 'text-primary'  },
  success: { bar: 'bg-bullish',   icon: CheckCircle2,   iconColor: 'text-bullish'  },
  warning: { bar: 'bg-amber',     icon: AlertTriangle,  iconColor: 'text-amber'    },
  error:   { bar: 'bg-bearish',   icon: AlertTriangle,  iconColor: 'text-bearish'  },
}

function ToastItem({ toast, onDismiss }) {
  const { bar, icon: Icon, iconColor } = VARIANT_STYLES[toast.variant] ?? VARIANT_STYLES.info

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 24, scale: 0.94 }}
      animate={{ opacity: 1, y: 0,  scale: 1 }}
      exit={{    opacity: 0, y: -12, scale: 0.94 }}
      transition={{ type: 'spring', stiffness: 380, damping: 30 }}
      className="relative flex items-start gap-3 w-full max-w-sm rounded-lg px-4 py-3 shadow-card overflow-hidden"
      style={{
        background: 'rgba(20, 25, 40, 0.97)',
        border: '1px solid rgba(255,255,255,0.09)',
        backdropFilter: 'blur(20px)',
      }}
    >
      {/* Left accent bar */}
      <div className={`absolute left-0 top-0 bottom-0 w-[3px] rounded-l-lg ${bar}`} />

      {/* Icon */}
      <Icon size={15} className={`flex-shrink-0 mt-0.5 ${iconColor}`} />

      {/* Message */}
      <p className="text-body-sm text-on-surface flex-1 leading-snug pr-2">
        {toast.message}
      </p>

      {/* Dismiss */}
      <button
        onClick={() => onDismiss(toast.id)}
        className="flex-shrink-0 text-outline hover:text-on-surface transition-colors mt-0.5"
        aria-label="Dismiss"
      >
        <X size={13} />
      </button>
    </motion.div>
  )
}

export function ToastProvider({ children }) {
  const { toasts, showToast, dismissToast } = useToast()

  return (
    <ToastCtx.Provider value={showToast}>
      {children}

      {/* Toast stack — bottom-right */}
      <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2 items-end pointer-events-none">
        <AnimatePresence initial={false} mode="popLayout">
          {toasts.map((t) => (
            <div key={t.id} className="pointer-events-auto">
              <ToastItem toast={t} onDismiss={dismissToast} />
            </div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  )
}

/** Hook — use inside any component wrapped by ToastProvider */
export function useShowToast() {
  const ctx = useContext(ToastCtx)
  if (!ctx) throw new Error('useShowToast must be used inside ToastProvider')
  return ctx
}
