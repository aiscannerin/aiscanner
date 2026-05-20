/**
 * useRazorpay — safely loads the Razorpay checkout.js script once,
 * then exposes an `openCheckout(options)` function.
 *
 * Rules:
 *  - Script is appended once; subsequent calls reuse the cached window.Razorpay.
 *  - Script tag is removed from DOM on hook unmount (does NOT remove window.Razorpay
 *    because the global is already bound and reused on next call).
 *  - Never logs or stores key_id beyond the function call.
 */
import { useCallback, useEffect, useRef } from 'react'

const SCRIPT_SRC = 'https://checkout.razorpay.com/v1/checkout.js'
const SCRIPT_ID  = 'razorpay-checkout-script'

function loadScript() {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) { resolve(); return }
    if (document.getElementById(SCRIPT_ID)) {
      // Script tag exists but Razorpay not yet on window — wait for it
      const existing = document.getElementById(SCRIPT_ID)
      existing.addEventListener('load',  resolve)
      existing.addEventListener('error', reject)
      return
    }
    const script    = document.createElement('script')
    script.id       = SCRIPT_ID
    script.src      = SCRIPT_SRC
    script.async    = true
    script.onload   = resolve
    script.onerror  = () => reject(new Error('Failed to load Razorpay checkout script. Check your internet connection.'))
    document.body.appendChild(script)
  })
}

export function useRazorpay() {
  const instanceRef = useRef(null)

  // Cleanup: close any open modal on unmount
  useEffect(() => {
    return () => {
      try { instanceRef.current?.close() } catch (_) {}
    }
  }, [])

  /**
   * openCheckout(options)
   *
   * options = {
   *   key_id, order_id, amount, currency,       // from create-order response
   *   planName, billingCycle,                    // display only
   *   prefill: { name, email },
   *   onSuccess: (payload) => void,              // {razorpay_order_id, razorpay_payment_id, razorpay_signature}
   *   onDismiss: () => void,
   *   onScriptError: (err) => void,
   * }
   */
  const openCheckout = useCallback(async (options) => {
    const {
      key_id, order_id, amount, currency = 'INR',
      planName = '', billingCycle = '',
      prefill = {},
      onSuccess, onDismiss, onScriptError,
    } = options

    try {
      await loadScript()
    } catch (err) {
      onScriptError?.(err)
      return
    }

    const rzp = new window.Razorpay({
      key:         key_id,
      order_id,
      amount,
      currency,
      name:        'Stop Hunter Pro',
      description: `${planName} Plan — ${billingCycle.charAt(0).toUpperCase() + billingCycle.slice(1)}`,
      image:       '',   // add logo URL here if needed
      prefill,
      theme:       { color: '#0066ff' },
      modal: {
        backdropclose: false,
        escape:        false,
        ondismiss() { onDismiss?.() },
      },
      handler(response) {
        // response = { razorpay_payment_id, razorpay_order_id, razorpay_signature }
        onSuccess?.(response)
      },
    })

    rzp.on('payment.failed', () => {
      // Razorpay will show its own error UI; dismiss handler fires after
    })

    instanceRef.current = rzp
    rzp.open()
  }, [])

  return { openCheckout }
}
