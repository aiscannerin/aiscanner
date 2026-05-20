import { useState, useCallback, useRef } from 'react'

let _id = 0

/**
 * Lightweight toast state manager — no external library needed.
 * Returns { toasts, showToast, dismissToast }.
 *
 * Usage:
 *   const { toasts, showToast } = useToast()
 *   showToast('Message here')
 *   showToast('Error!', 'error')
 */
export function useToast() {
  const [toasts, setToasts] = useState([])
  const timers = useRef({})

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    clearTimeout(timers.current[id])
    delete timers.current[id]
  }, [])

  const showToast = useCallback(
    (message, variant = 'info', duration = 3200) => {
      const id = ++_id
      setToasts((prev) => [...prev.slice(-3), { id, message, variant }])
      timers.current[id] = setTimeout(() => dismissToast(id), duration)
      return id
    },
    [dismissToast],
  )

  return { toasts, showToast, dismissToast }
}
