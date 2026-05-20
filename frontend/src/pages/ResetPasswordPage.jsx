/**
 * ResetPasswordPage — /reset-password
 *
 * 2-step flow:
 *  Step 1 — OTP: POST /api/auth/verify-otp { email, otp, purpose:"forgot_password" }
 *            → returns { data: { reset_token } } (15-min JWT)
 *  Step 2 — New password: POST /api/auth/reset-password { reset_token, new_password }
 *            → success → redirect to /login
 *
 * Security:
 *  - reset_token stored ONLY in component state, never in localStorage.
 *  - Passwords cleared from state on success/error.
 *  - OTP never logged.
 */
import { useState, useRef, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { apiVerifyOtp, apiResetPassword } from '../api/auth'

const T = {
  bg:      '#050810',
  surface: '#10131c',
  border:  'rgba(255,255,255,0.08)',
  muted:   '#8c90a1',
  text:    '#e1e2ee',
  primary: '#0066ff',
  red:     '#ff4d4f',
  green:   '#00d97e',
  amber:   '#f59e0b',
}

const slideVariants = {
  enter: (dir) => ({ opacity: 0, x: dir > 0 ? 40 : -40 }),
  center: { opacity: 1, x: 0 },
  exit:  (dir) => ({ opacity: 0, x: dir > 0 ? -40 : 40 }),
}

function FieldError({ msg }) {
  if (!msg) return null
  return (
    <p style={{ margin: '5px 0 0', fontSize: '11px', color: T.red, display: 'flex', alignItems: 'center', gap: '4px' }}>
      ⚠ {msg}
    </p>
  )
}

function StrengthBar({ password }) {
  const has8    = password.length >= 8
  const hasUp   = /[A-Z]/.test(password)
  const hasNum  = /[0-9]/.test(password)
  const score   = [has8, hasUp, hasNum].filter(Boolean).length

  if (!password) return null

  const colors = ['transparent', T.red, T.amber, T.green]
  const labels = ['', 'Weak', 'Almost', 'Strong']

  return (
    <div style={{ marginTop: '10px' }}>
      <div style={{ display: 'flex', gap: '4px', marginBottom: '6px' }}>
        {[1,2,3].map(i => (
          <div key={i} style={{
            flex: 1, height: '3px', borderRadius: '2px',
            background: i <= score ? colors[score] : 'rgba(255,255,255,0.08)',
            transition: 'background 0.2s',
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', gap: '12px', fontSize: '11px', flexWrap: 'wrap' }}>
        {[['8+ chars', has8], ['Uppercase', hasUp], ['Number', hasNum]].map(([l, ok]) => (
          <span key={l} style={{ color: ok ? T.green : T.muted }}>{ok ? '✓' : '○'} {l}</span>
        ))}
      </div>
    </div>
  )
}

// 6-box OTP visual input (same pattern as RegisterPage)
function OtpInput({ value, onChange, disabled }) {
  const inputRef = useRef(null)
  const digits   = (value + '      ').slice(0, 6).split('')

  return (
    <div style={{ position: 'relative' }}>
      {/* hidden real input */}
      <input
        ref={inputRef}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        maxLength={6}
        value={value}
        onChange={e => onChange(e.target.value.replace(/\D/g, '').slice(0, 6))}
        disabled={disabled}
        autoComplete="one-time-code"
        style={{
          position: 'absolute', opacity: 0, width: '100%', height: '100%',
          top: 0, left: 0, cursor: 'text', zIndex: 1,
        }}
      />
      {/* visual boxes */}
      <div
        onClick={() => inputRef.current?.focus()}
        style={{ display: 'flex', gap: '8px', justifyContent: 'center', cursor: 'text' }}
      >
        {digits.map((d, i) => (
          <div key={i} style={{
            width: '44px', height: '52px', borderRadius: '10px',
            background: '#0d1020',
            border: `2px solid ${i === value.length ? T.primary : d.trim() ? 'rgba(179,197,255,0.3)' : T.border}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '22px', fontWeight: 700, color: T.text,
            fontFamily: "'Space Grotesk', monospace",
            transition: 'border-color 0.15s',
          }}>
            {d.trim() || ''}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ResetPasswordPage() {
  const navigate        = useNavigate()
  const [searchParams]  = useSearchParams()

  const [step,        setStep]        = useState(1)  // 1 = OTP, 2 = new password, 3 = done
  const [direction,   setDirection]   = useState(1)

  // step 1
  const [email,       setEmail]       = useState(searchParams.get('email') ?? '')
  const [otp,         setOtp]         = useState('')
  const [emailError,  setEmailError]  = useState('')
  const [otpError,    setOtpError]    = useState('')
  const [step1Err,    setStep1Err]    = useState('')
  const [verifying,   setVerifying]   = useState(false)

  // step 2
  const resetTokenRef   = useRef('')   // never in state — avoids accidental serialisation
  const [newPwd,        setNewPwd]    = useState('')
  const [confirmPwd,    setConfirmPwd]= useState('')
  const [showPwd,       setShowPwd]   = useState(false)
  const [pwdErrors,     setPwdErrors] = useState({})
  const [step2Err,      setStep2Err]  = useState('')
  const [resetting,     setResetting] = useState(false)

  // Clear sensitive state on unmount
  useEffect(() => {
    return () => {
      resetTokenRef.current = ''
    }
  }, [])

  function goStep(n) {
    setDirection(n > step ? 1 : -1)
    setStep(n)
  }

  // ── Step 1: verify OTP ────────────────────────────────────────────────────

  function validateStep1() {
    const errs = {}
    if (!email.trim()) errs.email = 'Email is required.'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) errs.email = 'Enter a valid email.'
    if (!otp || otp.length < 6) errs.otp = 'Enter the 6-digit OTP.'
    return errs
  }

  async function handleVerifyOtp(e) {
    e.preventDefault()
    const errs = validateStep1()
    setEmailError(errs.email ?? '')
    setOtpError(errs.otp ?? '')
    if (Object.keys(errs).length) return

    setStep1Err('')
    setVerifying(true)

    try {
      const res = await apiVerifyOtp({
        email:   email.trim().toLowerCase(),
        otp:     otp.trim(),
        purpose: 'forgot_password',
      })
      const token = res.data?.data?.reset_token
      if (!token) throw new Error('No reset token returned.')
      resetTokenRef.current = token
      goStep(2)
    } catch (err) {
      const msg = err.response?.data?.message ?? 'OTP verification failed. Please try again.'
      setStep1Err(msg)
    } finally {
      setVerifying(false)
    }
  }

  // ── Step 2: reset password ────────────────────────────────────────────────

  function validateStep2() {
    const errs = {}
    if (!newPwd) { errs.newPwd = 'New password is required.' }
    else {
      if (newPwd.length < 8)         errs.newPwd = 'Password must be at least 8 characters.'
      else if (!/[A-Z]/.test(newPwd)) errs.newPwd = 'Password must contain at least one uppercase letter.'
      else if (!/[0-9]/.test(newPwd)) errs.newPwd = 'Password must contain at least one number.'
    }
    if (!confirmPwd) { errs.confirmPwd = 'Please confirm your password.' }
    else if (newPwd !== confirmPwd) { errs.confirmPwd = 'Passwords do not match.' }
    return errs
  }

  async function handleReset(e) {
    e.preventDefault()
    const errs = validateStep2()
    setPwdErrors(errs)
    if (Object.keys(errs).length) return

    setStep2Err('')
    setResetting(true)

    try {
      await apiResetPassword({
        reset_token:  resetTokenRef.current,
        new_password: newPwd,
      })
      // Clear sensitive data immediately
      setNewPwd('')
      setConfirmPwd('')
      resetTokenRef.current = ''
      goStep(3)
    } catch (err) {
      const errCode = err.response?.data?.error_code
      if (errCode === 'RESET_TOKEN_INVALID') {
        setStep2Err('Your reset session has expired. Please start over.')
      } else {
        setStep2Err(err.response?.data?.message ?? 'Password reset failed. Please try again.')
      }
    } finally {
      setResetting(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{
      minHeight: '100vh', background: T.bg,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '24px', fontFamily: 'Inter, ui-sans-serif, sans-serif',
    }}>
      <style>{`
        input:-webkit-autofill { -webkit-box-shadow: 0 0 0 100px #0d1020 inset !important; -webkit-text-fill-color: #e1e2ee !important; }
      `}</style>

      <div style={{ width: '100%', maxWidth: '440px' }}>

        {/* logo */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <div style={{
            width: '44px', height: '44px', background: T.primary, borderRadius: '13px',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '22px', marginBottom: '14px',
          }}>⚡</div>
          <h1 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: T.text }}>
            {step === 1 ? 'Enter your OTP' : step === 2 ? 'Set new password' : 'Password updated!'}
          </h1>
          <p style={{ margin: '8px 0 0', fontSize: '14px', color: T.muted }}>
            {step === 1 && 'Enter the 6-digit OTP sent to your email.'}
            {step === 2 && 'Choose a strong password for your account.'}
            {step === 3 && 'You can now log in with your new password.'}
          </p>
        </div>

        {/* step indicator */}
        {step < 3 && (
          <div style={{ display: 'flex', gap: '6px', justifyContent: 'center', marginBottom: '24px' }}>
            {[1,2].map(s => (
              <div key={s} style={{
                height: '3px', flex: 1, maxWidth: '60px', borderRadius: '2px',
                background: s <= step ? T.primary : 'rgba(255,255,255,0.1)',
                transition: 'background 0.3s',
              }} />
            ))}
          </div>
        )}

        {/* card */}
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: '18px', padding: '32px', overflow: 'hidden',
        }}>
          <AnimatePresence mode="wait" custom={direction}>

            {/* ── Step 1: OTP ── */}
            {step === 1 && (
              <motion.form
                key="step1"
                custom={direction}
                variants={slideVariants}
                initial="enter" animate="center" exit="exit"
                transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
                onSubmit={handleVerifyOtp}
                style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}
              >
                {/* email — editable in case user navigated directly */}
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: T.muted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '8px' }}>
                    Email address
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={e => { setEmail(e.target.value); setEmailError('') }}
                    autoComplete="email"
                    placeholder="you@example.com"
                    style={{
                      width: '100%', boxSizing: 'border-box',
                      background: '#0d1020',
                      border: `1px solid ${emailError ? T.red : T.border}`,
                      borderRadius: '10px', color: T.text,
                      fontSize: '14px', padding: '11px 14px', outline: 'none',
                    }}
                  />
                  <FieldError msg={emailError} />
                </div>

                {/* OTP boxes */}
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: T.muted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '12px' }}>
                    One-Time Password
                  </label>
                  <OtpInput value={otp} onChange={v => { setOtp(v); setOtpError('') }} disabled={verifying} />
                  <FieldError msg={otpError} />
                </div>

                {step1Err && (
                  <div style={{ background: 'rgba(255,77,79,0.08)', border: '1px solid rgba(255,77,79,0.2)', borderRadius: '10px', padding: '10px 14px', fontSize: '13px', color: T.red }}>
                    {step1Err}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={verifying || otp.length < 6}
                  style={{
                    width: '100%', padding: '12px',
                    background: verifying || otp.length < 6
                      ? 'rgba(0,102,255,0.35)'
                      : `linear-gradient(135deg,${T.primary},#0052cc)`,
                    border: 'none', borderRadius: '10px',
                    color: '#fff', fontSize: '14px', fontWeight: 700,
                    cursor: verifying || otp.length < 6 ? 'not-allowed' : 'pointer',
                    boxShadow: otp.length === 6 && !verifying ? '0 0 20px rgba(0,102,255,0.28)' : 'none',
                  }}
                >
                  {verifying ? '⏳ Verifying…' : 'Verify OTP →'}
                </button>

                <p style={{ textAlign: 'center', fontSize: '12px', color: T.muted, margin: 0 }}>
                  Didn&apos;t receive it?{' '}
                  <Link to="/forgot-password" style={{ color: T.primary, textDecoration: 'none', fontWeight: 600 }}>
                    Resend OTP
                  </Link>
                </p>
              </motion.form>
            )}

            {/* ── Step 2: New password ── */}
            {step === 2 && (
              <motion.form
                key="step2"
                custom={direction}
                variants={slideVariants}
                initial="enter" animate="center" exit="exit"
                transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
                onSubmit={handleReset}
                style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}
              >
                {/* new password */}
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: T.muted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '8px' }}>
                    New Password
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type={showPwd ? 'text' : 'password'}
                      value={newPwd}
                      onChange={e => { setNewPwd(e.target.value); setPwdErrors(p => ({ ...p, newPwd: '' })) }}
                      autoComplete="new-password"
                      placeholder="Min 8 chars · uppercase · number"
                      autoFocus
                      style={{
                        width: '100%', boxSizing: 'border-box',
                        background: '#0d1020',
                        border: `1px solid ${pwdErrors.newPwd ? T.red : T.border}`,
                        borderRadius: '10px', color: T.text,
                        fontSize: '14px', padding: '11px 44px 11px 14px', outline: 'none',
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPwd(v => !v)}
                      style={{
                        position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)',
                        background: 'none', border: 'none', color: T.muted, cursor: 'pointer', fontSize: '16px', padding: 0,
                      }}
                    >{showPwd ? '🙈' : '👁'}</button>
                  </div>
                  <FieldError msg={pwdErrors.newPwd} />
                  <StrengthBar password={newPwd} />
                </div>

                {/* confirm password */}
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: T.muted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '8px' }}>
                    Confirm Password
                  </label>
                  <input
                    type={showPwd ? 'text' : 'password'}
                    value={confirmPwd}
                    onChange={e => { setConfirmPwd(e.target.value); setPwdErrors(p => ({ ...p, confirmPwd: '' })) }}
                    autoComplete="new-password"
                    placeholder="Repeat the password"
                    style={{
                      width: '100%', boxSizing: 'border-box',
                      background: '#0d1020',
                      border: `1px solid ${pwdErrors.confirmPwd ? T.red : confirmPwd && confirmPwd === newPwd ? 'rgba(0,217,126,0.4)' : T.border}`,
                      borderRadius: '10px', color: T.text,
                      fontSize: '14px', padding: '11px 14px', outline: 'none',
                    }}
                  />
                  <FieldError msg={pwdErrors.confirmPwd} />
                  {confirmPwd && confirmPwd === newPwd && (
                    <p style={{ margin: '5px 0 0', fontSize: '11px', color: T.green }}>✓ Passwords match</p>
                  )}
                </div>

                {step2Err && (
                  <div style={{ background: 'rgba(255,77,79,0.08)', border: '1px solid rgba(255,77,79,0.2)', borderRadius: '10px', padding: '10px 14px', fontSize: '13px', color: T.red }}>
                    {step2Err}
                    {step2Err.includes('expired') && (
                      <span> <Link to="/forgot-password" style={{ color: T.primary, textDecoration: 'none', fontWeight: 600 }}>Start over</Link></span>
                    )}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={resetting}
                  style={{
                    width: '100%', padding: '12px',
                    background: resetting ? 'rgba(0,102,255,0.35)' : `linear-gradient(135deg,${T.primary},#0052cc)`,
                    border: 'none', borderRadius: '10px',
                    color: '#fff', fontSize: '14px', fontWeight: 700,
                    cursor: resetting ? 'not-allowed' : 'pointer',
                    boxShadow: resetting ? 'none' : '0 0 20px rgba(0,102,255,0.28)',
                  }}
                >
                  {resetting ? '⏳ Updating password…' : 'Set New Password →'}
                </button>

                <button
                  type="button"
                  onClick={() => { goStep(1); setOtp(''); setStep1Err('') }}
                  style={{ background: 'none', border: 'none', color: T.muted, fontSize: '13px', cursor: 'pointer' }}
                >
                  ← Back to OTP
                </button>
              </motion.form>
            )}

            {/* ── Step 3: Success ── */}
            {step === 3 && (
              <motion.div
                key="step3"
                custom={direction}
                variants={slideVariants}
                initial="enter" animate="center" exit="exit"
                transition={{ duration: 0.3 }}
                style={{ display: 'flex', flexDirection: 'column', gap: '20px', textAlign: 'center', alignItems: 'center' }}
              >
                <div style={{ fontSize: '52px' }}>🎉</div>
                <div>
                  <div style={{ fontSize: '17px', fontWeight: 700, color: T.text, marginBottom: '8px' }}>
                    Password updated!
                  </div>
                  <p style={{ fontSize: '13px', color: T.muted, lineHeight: 1.7, margin: 0 }}>
                    Your password has been changed successfully.
                    You can now log in with your new credentials.
                  </p>
                </div>
                <button
                  onClick={() => navigate('/login')}
                  style={{
                    width: '100%', padding: '12px',
                    background: `linear-gradient(135deg,${T.primary},#0052cc)`,
                    border: 'none', borderRadius: '10px',
                    color: '#fff', fontSize: '14px', fontWeight: 700, cursor: 'pointer',
                    boxShadow: '0 0 20px rgba(0,102,255,0.28)',
                  }}
                >
                  Go to Login →
                </button>
              </motion.div>
            )}

          </AnimatePresence>
        </div>

        <p style={{ textAlign: 'center', marginTop: '20px', fontSize: '13px', color: T.muted }}>
          <Link to="/login" style={{ color: T.primary, textDecoration: 'none', fontWeight: 600 }}>
            ← Back to login
          </Link>
        </p>
      </div>
    </div>
  )
}
