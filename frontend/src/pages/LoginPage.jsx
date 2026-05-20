import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Zap, Eye, EyeOff, ArrowLeft, AlertCircle } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { useAuth } from '../context/AuthContext'
import { useShowToast } from '../context/ToastContext'
import { apiLogin, apiGetMe } from '../api/auth'

const fadeUp = (delay = 0) => ({
  initial:    { opacity: 0, y: 20 },
  animate:    { opacity: 1, y: 0 },
  transition: { duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] },
})

function FieldError({ message }) {
  if (!message) return null
  return (
    <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] text-bearish">
      <AlertCircle size={11} />
      {message}
    </p>
  )
}

export function LoginPage() {
  const { isAuthenticated, login, loading: authLoading } = useAuth()
  const navigate   = useNavigate()
  const showToast  = useShowToast()

  const [email,       setEmail]       = useState('')
  const [password,    setPassword]    = useState('')
  const [showPwd,     setShowPwd]     = useState(false)
  const [rememberMe,  setRememberMe]  = useState(false)
  const [submitting,  setSubmitting]  = useState(false)
  const [apiError,    setApiError]    = useState('')
  const [fieldErrors, setFieldErrors] = useState({})

  // If already logged in, redirect away from login page
  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, authLoading, navigate])

  function validate() {
    const errors = {}
    if (!email.trim()) {
      errors.email = 'Email is required'
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      errors.email = 'Enter a valid email address'
    }
    if (!password) {
      errors.password = 'Password is required'
    } else if (password.length < 6) {
      errors.password = 'Password must be at least 6 characters'
    }
    return errors
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setApiError('')
    const errors = validate()
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      const loginRes = await apiLogin({ email: email.trim(), password })
      // Backend wraps tokens under response.data.data
      const payload       = loginRes.data?.data ?? {}
      const access_token  = payload.access_token
      const refresh_token = payload.refresh_token

      console.debug('[Login] token exists:', !!access_token)
      if (access_token) {
        console.debug('[Login] token segment count:', access_token.split('.').length)
      }

      if (!access_token || access_token.split('.').length !== 3) {
        throw new Error('Received an invalid access token from server')
      }

      // Store token so the axios interceptor includes it in the /me request
      localStorage.setItem('access_token', access_token)
      const meRes  = await apiGetMe()
      // Backend envelope: { success, message, data: { id, full_name, email, ... } }
      // meRes.data = envelope, meRes.data.data = user object (no extra .user key)
      const meUser = meRes.data?.data ?? null
      if (import.meta.env.DEV) {
        console.debug('[Login /me] response keys:', Object.keys(meRes.data ?? {}))
        console.debug('[Login /me] user keys:',     Object.keys(meUser ?? {}))
      }
      if (!meUser) throw new Error('Could not retrieve user profile after login')

      login(access_token, refresh_token, meUser)
      showToast('Logged in successfully!', 'success')
      navigate('/dashboard', { replace: true })
    } catch (err) {
      // Clean up any partial token write
      localStorage.removeItem('access_token')

      const msg =
        err.response?.data?.message ||
        err.response?.data?.error ||
        (err.response?.status === 401
          ? 'Invalid email or password'
          : err.message?.startsWith('Received an invalid')
            ? err.message
            : 'Something went wrong — please try again')
      setApiError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  // Show nothing while AuthContext is resolving initial session
  if (authLoading) return null

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-12 relative overflow-hidden"
      style={{ background: '#050810' }}
    >
      {/* Background glows */}
      <div className="absolute inset-0 pointer-events-none" aria-hidden>
        <div
          className="absolute -top-32 left-1/2 -translate-x-1/2 w-[600px] h-[400px] rounded-full opacity-[0.15]"
          style={{ background: 'radial-gradient(ellipse, #0066ff 0%, transparent 70%)', filter: 'blur(80px)' }}
        />
        <div
          className="absolute top-20 left-1/2 -translate-x-1/2 translate-x-20 w-[280px] h-[200px] rounded-full opacity-[0.08]"
          style={{ background: 'radial-gradient(ellipse, #00f1fe 0%, transparent 70%)', filter: 'blur(60px)' }}
        />
        {/* Subtle grid */}
        <div
          className="absolute inset-0 opacity-[0.02]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(179,197,255,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(179,197,255,0.6) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />
      </div>

      {/* Back to home */}
      <motion.div {...fadeUp(0)} className="w-full max-w-sm mb-6">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 font-mono text-[12px] text-outline hover:text-on-surface transition-colors duration-200"
        >
          <ArrowLeft size={13} />
          Back to home
        </Link>
      </motion.div>

      {/* Card */}
      <motion.div
        {...fadeUp(0.05)}
        className="w-full max-w-sm rounded-2xl overflow-hidden"
        style={{
          background: 'rgba(13,17,30,0.92)',
          border: '1px solid rgba(255,255,255,0.09)',
          backdropFilter: 'blur(40px)',
          boxShadow: '0 40px 100px rgba(0,0,0,0.6)',
        }}
      >
        {/* Accent top line */}
        <div
          className="h-[2px] w-full"
          style={{ background: 'linear-gradient(90deg, transparent, #0066ff, #00f1fe, transparent)' }}
        />

        <div className="p-8">
          {/* Logo + heading */}
          <motion.div {...fadeUp(0.1)} className="flex flex-col items-center mb-8">
            <div className="w-10 h-10 rounded-xl bg-primary-container flex items-center justify-center shadow-glow-btn mb-4">
              <Zap size={18} className="text-white" fill="white" />
            </div>
            <h1 className="text-headline-md text-on-surface mb-1">Welcome back</h1>
            <p className="text-body-sm text-outline text-center">
              Sign in to your Stop Hunter Pro account
            </p>
          </motion.div>

          {/* API-level error banner */}
          {apiError && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-5 flex items-start gap-2.5 rounded-lg px-3.5 py-3"
              style={{
                background: 'rgba(255,77,79,0.08)',
                border: '1px solid rgba(255,77,79,0.25)',
              }}
            >
              <AlertCircle size={14} className="text-bearish flex-shrink-0 mt-0.5" />
              <p className="text-body-sm text-bearish leading-snug">{apiError}</p>
            </motion.div>
          )}

          <motion.form {...fadeUp(0.15)} onSubmit={handleSubmit} noValidate>
            {/* Email */}
            <div className="mb-4">
              <label className="block font-mono text-[11px] uppercase tracking-widest text-outline mb-2">
                Email
              </label>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setFieldErrors((p) => ({ ...p, email: '' })); setApiError('') }}
                placeholder="you@example.com"
                className="w-full rounded-lg px-4 py-2.5 text-body-sm text-on-surface placeholder:text-outline transition-all duration-200 focus:outline-none"
                style={{
                  background: 'rgba(255,255,255,0.05)',
                  border: fieldErrors.email
                    ? '1px solid rgba(255,77,79,0.6)'
                    : '1px solid rgba(255,255,255,0.10)',
                }}
                onFocus={(e) => { if (!fieldErrors.email) e.target.style.borderColor = 'rgba(0,102,255,0.7)' }}
                onBlur={(e)  => { if (!fieldErrors.email) e.target.style.borderColor = 'rgba(255,255,255,0.10)' }}
              />
              <FieldError message={fieldErrors.email} />
            </div>

            {/* Password */}
            <div className="mb-5">
              <div className="flex items-center justify-between mb-2">
                <label className="block font-mono text-[11px] uppercase tracking-widest text-outline">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => navigate('/forgot-password')}
                  className="font-mono text-[11px] text-primary hover:text-on-surface transition-colors bg-transparent border-0 p-0 cursor-pointer"
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative">
                <input
                  type={showPwd ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setFieldErrors((p) => ({ ...p, password: '' })); setApiError('') }}
                  placeholder="••••••••"
                  className="w-full rounded-lg px-4 py-2.5 pr-11 text-body-sm text-on-surface placeholder:text-outline transition-all duration-200 focus:outline-none"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: fieldErrors.password
                      ? '1px solid rgba(255,77,79,0.6)'
                      : '1px solid rgba(255,255,255,0.10)',
                  }}
                  onFocus={(e) => { if (!fieldErrors.password) e.target.style.borderColor = 'rgba(0,102,255,0.7)' }}
                  onBlur={(e)  => { if (!fieldErrors.password) e.target.style.borderColor = 'rgba(255,255,255,0.10)' }}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-outline hover:text-on-surface transition-colors bg-transparent border-0 p-0 cursor-pointer"
                  aria-label={showPwd ? 'Hide password' : 'Show password'}
                >
                  {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              <FieldError message={fieldErrors.password} />
            </div>

            {/* Remember me */}
            <div className="flex items-center gap-2.5 mb-6">
              <button
                type="button"
                role="checkbox"
                aria-checked={rememberMe}
                onClick={() => setRememberMe((v) => !v)}
                className="w-4 h-4 rounded flex items-center justify-center flex-shrink-0 transition-colors duration-150 bg-transparent border-0 p-0 cursor-pointer"
                style={{
                  background: rememberMe ? 'rgba(0,102,255,0.8)' : 'rgba(255,255,255,0.07)',
                  border: rememberMe ? '1px solid rgba(0,102,255,0.9)' : '1px solid rgba(255,255,255,0.20)',
                }}
              >
                {rememberMe && (
                  <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
                    <path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
              <span className="text-body-sm text-on-surface-variant select-none">Remember me</span>
            </div>

            {/* Submit */}
            <Button
              type="submit"
              className="w-full justify-center"
              disabled={submitting}
            >
              {submitting ? (
                <>
                  <span
                    className="w-3.5 h-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin"
                    aria-hidden
                  />
                  Signing in…
                </>
              ) : (
                'Sign In'
              )}
            </Button>
          </motion.form>

          {/* Footer links */}
          <motion.p {...fadeUp(0.2)} className="mt-6 text-center text-body-sm text-outline">
            Don't have an account?{' '}
            <Link to="/register" className="text-primary hover:text-on-surface transition-colors">
              Sign up free
            </Link>
          </motion.p>
        </div>
      </motion.div>

      {/* Bottom caption */}
      <motion.p {...fadeUp(0.25)} className="mt-6 font-mono text-[11px] text-outline text-center max-w-xs">
        Stop Hunter Pro · NSE / BSE · India market hours
      </motion.p>
    </div>
  )
}
