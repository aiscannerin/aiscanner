/**
 * ForgotPasswordPage — /forgot-password
 *
 * Step 1 of the password-reset flow.
 * POSTs to /api/auth/forgot-password with just {email}.
 * Backend always returns the same generic message — never reveals
 * whether the address is registered.
 * On success, shows instructions and a link to /reset-password?email=<email>.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { apiForgotPassword } from '../api/auth'

const T = {
  bg:      '#050810',
  surface: '#10131c',
  border:  'rgba(255,255,255,0.08)',
  muted:   '#8c90a1',
  text:    '#e1e2ee',
  primary: '#0066ff',
  red:     '#ff4d4f',
  green:   '#00d97e',
}

const fadeUp = {
  initial:    { opacity: 0, y: 20 },
  animate:    { opacity: 1, y: 0 },
  transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] },
}

function FieldError({ msg }) {
  if (!msg) return null
  return (
    <p style={{ margin: '5px 0 0', fontSize: '11px', color: T.red, display: 'flex', alignItems: 'center', gap: '5px' }}>
      ⚠ {msg}
    </p>
  )
}

export default function ForgotPasswordPage() {
  const navigate = useNavigate()

  const [email,       setEmail]       = useState('')
  const [submitting,  setSubmitting]  = useState(false)
  const [submitted,   setSubmitted]   = useState(false)   // shows success state
  const [emailError,  setEmailError]  = useState('')
  const [apiError,    setApiError]    = useState('')

  function validate() {
    if (!email.trim()) return 'Email is required.'
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return 'Enter a valid email address.'
    return ''
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const err = validate()
    if (err) { setEmailError(err); return }

    setEmailError('')
    setApiError('')
    setSubmitting(true)

    try {
      await apiForgotPassword({ email: email.trim().toLowerCase() })
      // Backend always returns 200 regardless of whether the email exists
      setSubmitted(true)
    } catch (err) {
      // Only a network/server error — not "email not found" (backend doesn't reveal that)
      setApiError(err.response?.data?.message ?? 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', background: T.bg,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '24px', fontFamily: 'Inter, ui-sans-serif, sans-serif',
    }}>
      <style>{`
        input:-webkit-autofill { -webkit-box-shadow: 0 0 0 100px #0d1020 inset !important; -webkit-text-fill-color: #e1e2ee !important; }
      `}</style>

      <motion.div {...fadeUp} style={{ width: '100%', maxWidth: '420px' }}>

        {/* logo */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <div style={{
            width: '44px', height: '44px', background: T.primary, borderRadius: '13px',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '22px', marginBottom: '16px',
          }}>⚡</div>
          <h1 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: T.text }}>
            Reset your password
          </h1>
          <p style={{ margin: '8px 0 0', fontSize: '14px', color: T.muted }}>
            Enter your email to receive a reset OTP.
          </p>
        </div>

        {/* card */}
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: '18px', padding: '32px',
        }}>

          <AnimatePresence mode="wait">
            {!submitted ? (
              /* ── Email form ── */
              <motion.form
                key="form"
                onSubmit={handleSubmit}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}
              >
                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: T.muted, letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: '8px' }}>
                    Email address
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={e => { setEmail(e.target.value); setEmailError(''); setApiError('') }}
                    placeholder="you@example.com"
                    autoFocus
                    autoComplete="email"
                    style={{
                      width: '100%', boxSizing: 'border-box',
                      background: '#0d1020', border: `1px solid ${emailError ? T.red : T.border}`,
                      borderRadius: '10px', color: T.text,
                      fontSize: '14px', padding: '11px 14px', outline: 'none',
                    }}
                  />
                  <FieldError msg={emailError} />
                </div>

                {apiError && (
                  <div style={{ background: 'rgba(255,77,79,0.08)', border: '1px solid rgba(255,77,79,0.2)', borderRadius: '10px', padding: '10px 14px', fontSize: '13px', color: T.red }}>
                    {apiError}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  style={{
                    width: '100%', padding: '12px',
                    background: submitting ? 'rgba(0,102,255,0.4)' : `linear-gradient(135deg,${T.primary},#0052cc)`,
                    border: 'none', borderRadius: '10px',
                    color: '#fff', fontSize: '14px', fontWeight: 700,
                    cursor: submitting ? 'not-allowed' : 'pointer',
                    boxShadow: submitting ? 'none' : '0 0 20px rgba(0,102,255,0.3)',
                  }}
                >
                  {submitting ? '⏳ Sending OTP…' : 'Send Reset OTP →'}
                </button>

                <p style={{ textAlign: 'center', fontSize: '13px', color: T.muted, margin: 0 }}>
                  Remembered it?{' '}
                  <Link to="/login" style={{ color: T.primary, textDecoration: 'none', fontWeight: 600 }}>
                    Back to login
                  </Link>
                </p>
              </motion.form>

            ) : (
              /* ── Success state ── */
              <motion.div
                key="success"
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: '16px' }}
              >
                <div style={{ fontSize: '44px' }}>📧</div>
                <div>
                  <div style={{ fontSize: '17px', fontWeight: 700, color: T.text, marginBottom: '8px' }}>
                    Check your inbox
                  </div>
                  <p style={{ fontSize: '13px', color: T.muted, lineHeight: 1.7, margin: 0 }}>
                    If <strong style={{ color: T.text }}>{email}</strong> is registered with us,
                    a 6-digit OTP has been sent. It expires in 10 minutes.
                  </p>
                </div>

                <button
                  onClick={() => navigate(`/reset-password?email=${encodeURIComponent(email.trim().toLowerCase())}`)}
                  style={{
                    width: '100%', padding: '12px',
                    background: `linear-gradient(135deg,${T.primary},#0052cc)`,
                    border: 'none', borderRadius: '10px',
                    color: '#fff', fontSize: '14px', fontWeight: 700, cursor: 'pointer',
                    boxShadow: '0 0 20px rgba(0,102,255,0.3)',
                  }}
                >
                  Enter OTP &amp; Reset Password →
                </button>

                <button
                  onClick={() => setSubmitted(false)}
                  style={{
                    width: '100%', padding: '10px',
                    background: 'transparent', border: `1px solid ${T.border}`,
                    borderRadius: '10px', color: T.muted,
                    fontSize: '13px', cursor: 'pointer',
                  }}
                >
                  Try a different email
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    </div>
  )
}
