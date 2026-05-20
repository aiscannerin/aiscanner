import { useState, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Zap, Eye, EyeOff, ArrowLeft, ArrowRight,
  AlertCircle, CheckCircle2, RotateCcw,
} from 'lucide-react'
import { Button } from '../components/ui/Button'
import { useShowToast } from '../context/ToastContext'
import { apiRegister, apiVerifyOtp, apiSendOtp } from '../api/auth'
import { cn } from '../utils/cn'

// ── Constants matching backend validators ─────────────────────────────────────

const GENDER_OPTIONS = [
  { value: 'male',             label: 'Male' },
  { value: 'female',           label: 'Female' },
  { value: 'other',            label: 'Other' },
  { value: 'prefer_not_to_say', label: 'Prefer not to say' },
]

const EXPERIENCE_OPTIONS = [
  { value: 'beginner',     label: 'Beginner — Less than 1 year' },
  { value: 'intermediate', label: 'Intermediate — 1–3 years' },
  { value: 'advanced',     label: 'Advanced — 3+ years' },
]

const TOTAL_STEPS = 4
const STEP_LABELS = ['Personal', 'Account', 'Profile', 'Verify']

// ── Field components ──────────────────────────────────────────────────────────

function FieldError({ message }) {
  if (!message) return null
  return (
    <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] text-bearish">
      <AlertCircle size={11} className="flex-shrink-0" />
      {message}
    </p>
  )
}

function Label({ children }) {
  return (
    <span className="block font-mono text-[11px] uppercase tracking-widest text-outline mb-2">
      {children}
    </span>
  )
}

function Field({ label, error, children }) {
  return (
    <div className="mb-4">
      <Label>{label}</Label>
      {children}
      <FieldError message={error} />
    </div>
  )
}

function inputStyle(hasError) {
  return {
    background: 'rgba(255,255,255,0.05)',
    border: hasError
      ? '1px solid rgba(255,77,79,0.6)'
      : '1px solid rgba(255,255,255,0.10)',
  }
}

function TextInput({ value, onChange, placeholder, type = 'text', autoComplete, error, onFocus, onBlur }) {
  return (
    <input
      type={type}
      autoComplete={autoComplete}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      className="w-full rounded-lg px-4 py-2.5 text-body-sm text-on-surface placeholder:text-outline transition-colors duration-150 focus:outline-none"
      style={inputStyle(!!error)}
      onFocus={(e) => { if (!error) e.target.style.borderColor = 'rgba(0,102,255,0.7)'; onFocus?.(e) }}
      onBlur={(e)  => { if (!error) e.target.style.borderColor = 'rgba(255,255,255,0.10)'; onBlur?.(e) }}
    />
  )
}

function SelectInput({ value, onChange, options, placeholder, error }) {
  return (
    <select
      value={value}
      onChange={onChange}
      className="w-full rounded-lg px-4 py-2.5 text-body-sm text-on-surface transition-colors duration-150 focus:outline-none appearance-none"
      style={{
        ...inputStyle(!!error),
        color: value ? '#e1e2ee' : '#8c90a1',
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238c90a1' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'right 14px center',
      }}
    >
      <option value="" disabled hidden>{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value} style={{ background: '#10131c' }}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

// ── OTP digit input ───────────────────────────────────────────────────────────

function OtpInput({ value, onChange }) {
  const digits = (value + '      ').slice(0, 6).split('')

  function handleChange(e) {
    const raw = e.target.value.replace(/\D/g, '').slice(0, 6)
    onChange(raw)
  }

  function handleKeyDown(e) {
    if (e.key === 'Backspace' && !value) e.preventDefault()
  }

  return (
    <div className="relative">
      {/* Hidden real input */}
      <input
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        maxLength={6}
        className="absolute inset-0 opacity-0 w-full cursor-text"
        aria-label="Enter OTP"
      />
      {/* Visual boxes */}
      <div className="flex gap-2 justify-center">
        {Array.from({ length: 6 }).map((_, i) => {
          const char  = value[i] ?? ''
          const isCur = i === value.length && value.length < 6
          return (
            <div
              key={i}
              className="w-10 h-12 rounded-lg flex items-center justify-center font-mono text-[20px] font-bold text-on-surface transition-all duration-150"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: isCur
                  ? '1px solid rgba(0,102,255,0.8)'
                  : char
                    ? '1px solid rgba(179,197,255,0.4)'
                    : '1px solid rgba(255,255,255,0.10)',
              }}
            >
              {char || (isCur ? <span className="w-0.5 h-5 bg-primary animate-pulse" /> : null)}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function StepProgress({ step }) {
  return (
    <div className="flex items-center justify-between mb-8">
      {STEP_LABELS.map((label, i) => {
        const idx     = i + 1
        const done    = idx < step
        const current = idx === step
        return (
          <div key={label} className="flex flex-col items-center gap-1.5 flex-1">
            <div className="flex items-center w-full">
              {/* Connector left */}
              {i > 0 && (
                <div
                  className="flex-1 h-px transition-colors duration-400"
                  style={{ background: done || current ? 'rgba(0,102,255,0.7)' : 'rgba(255,255,255,0.10)' }}
                />
              )}
              {/* Circle */}
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center font-mono text-[11px] font-bold flex-shrink-0 transition-all duration-300"
                style={{
                  background: done
                    ? 'rgba(0,217,126,0.2)'
                    : current
                      ? 'rgba(0,102,255,0.85)'
                      : 'rgba(255,255,255,0.06)',
                  border: done
                    ? '1px solid rgba(0,217,126,0.6)'
                    : current
                      ? '1px solid rgba(0,102,255,0.9)'
                      : '1px solid rgba(255,255,255,0.12)',
                  color: done ? '#00d97e' : current ? '#fff' : '#8c90a1',
                }}
              >
                {done ? <CheckCircle2 size={13} /> : idx}
              </div>
              {/* Connector right */}
              {i < TOTAL_STEPS - 1 && (
                <div
                  className="flex-1 h-px transition-colors duration-400"
                  style={{ background: done ? 'rgba(0,102,255,0.7)' : 'rgba(255,255,255,0.10)' }}
                />
              )}
            </div>
            <span
              className="font-mono text-[10px] uppercase tracking-widest"
              style={{ color: current ? '#b3c5ff' : done ? '#00d97e' : '#8c90a1' }}
            >
              {label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Backend error extraction ──────────────────────────────────────────────────

function extractErrors(err) {
  const res    = err.response?.data
  const banner = res?.message || 'Something went wrong — please try again'
  const fields  = {}
  if (Array.isArray(res?.errors)) {
    res.errors.forEach(({ field, message }) => { fields[field] = message })
  }
  return { banner, fields }
}

// ── Shared field-clear helper ─────────────────────────────────────────────────

function clearField(setErrors, field) {
  setErrors((p) => ({ ...p, [field]: '' }))
}

// ── Main component ─────────────────────────────────────────────────────────────

const slideVariants = {
  enter: (dir) => ({ opacity: 0, x: dir > 0 ? 40 : -40 }),
  center: { opacity: 1, x: 0 },
  exit:  (dir) => ({ opacity: 0, x: dir > 0 ? -40 : 40 }),
}

export function RegisterPage() {
  const navigate   = useNavigate()
  const showToast  = useShowToast()

  const [step,    setStep]    = useState(1)
  const [dir,     setDir]     = useState(1)   // animation direction
  const [loading, setLoading] = useState(false)
  const [errors,  setErrors]  = useState({})
  const [banner,  setBanner]  = useState('')

  // ── Form state (flat — sent as one object on step 3 submit) ──────────────────
  const [form, setForm] = useState({
    // Step 1
    full_name:  '',
    phone:      '',
    dob:        '',
    gender:     '',
    address:    '',
    // Step 2
    username:   '',
    email:      '',
    password:   '',
    // Step 3
    trading_experience: '',
  })
  const [showPwd, setShowPwd] = useState(false)

  // Step 4
  const [otp, setOtp] = useState('')
  const [resendCooldown, setResendCooldown] = useState(0)

  function set(field) {
    return (e) => {
      const val = e.target ? e.target.value : e
      setForm((p) => ({ ...p, [field]: val }))
      clearField(setErrors, field)
      setBanner('')
    }
  }

  function goTo(next) {
    setDir(next > step ? 1 : -1)
    setStep(next)
    setBanner('')
    setErrors({})
  }

  // ── Per-step frontend validation ──────────────────────────────────────────────

  function validateStep1() {
    const e = {}
    if (!form.full_name.trim())  e.full_name = 'Full name is required'
    if (!form.phone.trim())      e.phone     = 'Phone number is required'
    else if (!/^(?:\+91)?[6-9]\d{9}$/.test(form.phone.trim().replace(/[\s-]/g, '')))
      e.phone = 'Enter a valid Indian mobile number (e.g. 9876543210)'
    if (!form.dob)               e.dob       = 'Date of birth is required'
    else {
      const d = new Date(form.dob)
      if (isNaN(d) || d >= new Date()) e.dob = 'Enter a valid past date'
    }
    if (!form.gender)            e.gender    = 'Please select a gender'
    if (!form.address.trim())    e.address   = 'Address is required'
    else if (form.address.trim().length < 5) e.address = 'Address must be at least 5 characters'
    return e
  }

  function validateStep2() {
    const e = {}
    if (!form.username.trim())   e.username = 'Username is required'
    else if (!/^[a-zA-Z0-9_]{3,50}$/.test(form.username.trim()))
      e.username = '3–50 characters: letters, numbers, and underscores only'
    if (!form.email.trim())      e.email    = 'Email is required'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim()))
      e.email = 'Enter a valid email address'
    if (!form.password)          e.password = 'Password is required'
    else {
      const errs = []
      if (form.password.length < 8)          errs.push('at least 8 characters')
      if (!/[A-Z]/.test(form.password))      errs.push('one uppercase letter')
      if (!/[0-9]/.test(form.password))      errs.push('one number')
      if (errs.length) e.password = `Password needs: ${errs.join(', ')}`
    }
    return e
  }

  function validateStep3() {
    const e = {}
    if (!form.trading_experience) e.trading_experience = 'Please select your experience level'
    return e
  }

  // ── Step handlers ─────────────────────────────────────────────────────────────

  function handleStep1Next() {
    const e = validateStep1()
    if (Object.keys(e).length) { setErrors(e); return }
    goTo(2)
  }

  function handleStep2Next() {
    const e = validateStep2()
    if (Object.keys(e).length) { setErrors(e); return }
    goTo(3)
  }

  async function handleStep3Submit() {
    const e = validateStep3()
    if (Object.keys(e).length) { setErrors(e); return }

    setLoading(true)
    setBanner('')
    try {
      await apiRegister({
        full_name:          form.full_name.trim(),
        phone:              form.phone.trim().replace(/[\s-]/g, ''),
        dob:                form.dob,
        gender:             form.gender,
        address:            form.address.trim(),
        username:           form.username.trim().toLowerCase(),
        email:              form.email.trim().toLowerCase(),
        password:           form.password,
        trading_experience: form.trading_experience,
      })
      showToast('Account created! Check your email for the OTP.', 'success')
      goTo(4)
    } catch (err) {
      const { banner: b, fields } = extractErrors(err)
      if (Object.keys(fields).length) {
        // Step back to the step that owns the failed fields
        const step2Fields = ['username', 'email', 'password']
        const step1Fields = ['full_name', 'phone', 'dob', 'gender', 'address']
        const failedFields = Object.keys(fields)
        if (failedFields.some((f) => step1Fields.includes(f))) goTo(1)
        else if (failedFields.some((f) => step2Fields.includes(f))) goTo(2)
        setErrors(fields)
      } else {
        setBanner(b)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleVerifyOtp() {
    if (otp.length !== 6) {
      setErrors({ otp: 'Enter the 6-digit OTP from your email' })
      return
    }
    setLoading(true)
    setBanner('')
    setErrors({})
    try {
      await apiVerifyOtp({ email: form.email.trim().toLowerCase(), otp, purpose: 'signup' })
      showToast('Email verified! You can now log in.', 'success')
      navigate('/login', { replace: true })
    } catch (err) {
      const { banner: b } = extractErrors(err)
      setBanner(b)
    } finally {
      setLoading(false)
    }
  }

  async function handleResendOtp() {
    if (resendCooldown > 0) return
    setLoading(true)
    setBanner('')
    try {
      await apiSendOtp({ email: form.email.trim().toLowerCase(), purpose: 'signup' })
      showToast('OTP resent — check your email.', 'info')
      // 60-second cooldown
      setResendCooldown(60)
      const iv = setInterval(() => {
        setResendCooldown((c) => {
          if (c <= 1) { clearInterval(iv); return 0 }
          return c - 1
        })
      }, 1000)
    } catch (err) {
      const { banner: b } = extractErrors(err)
      setBanner(b)
    } finally {
      setLoading(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-12 relative overflow-hidden"
      style={{ background: '#050810' }}
    >
      {/* Background glows */}
      <div className="absolute inset-0 pointer-events-none" aria-hidden>
        <div
          className="absolute -top-32 left-1/2 -translate-x-1/2 w-[600px] h-[400px] rounded-full opacity-[0.14]"
          style={{ background: 'radial-gradient(ellipse, #0066ff 0%, transparent 70%)', filter: 'blur(80px)' }}
        />
        <div
          className="absolute top-20 left-1/2 translate-x-24 w-[280px] h-[200px] rounded-full opacity-[0.07]"
          style={{ background: 'radial-gradient(ellipse, #00f1fe 0%, transparent 70%)', filter: 'blur(60px)' }}
        />
        <div
          className="absolute inset-0 opacity-[0.02]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(179,197,255,0.6) 1px,transparent 1px),linear-gradient(90deg,rgba(179,197,255,0.6) 1px,transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />
      </div>

      {/* Back link */}
      <div className="w-full max-w-md mb-5">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 font-mono text-[12px] text-outline hover:text-on-surface transition-colors duration-200"
        >
          <ArrowLeft size={13} /> Back to home
        </Link>
      </div>

      {/* Card */}
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden"
        style={{
          background: 'rgba(13,17,30,0.92)',
          border: '1px solid rgba(255,255,255,0.09)',
          backdropFilter: 'blur(40px)',
          boxShadow: '0 40px 100px rgba(0,0,0,0.6)',
        }}
      >
        {/* Accent line */}
        <div
          className="h-[2px] w-full"
          style={{ background: 'linear-gradient(90deg,transparent,#0066ff,#00f1fe,transparent)' }}
        />

        <div className="p-7">
          {/* Logo + heading */}
          <div className="flex flex-col items-center mb-6">
            <div className="w-10 h-10 rounded-xl bg-primary-container flex items-center justify-center shadow-glow-btn mb-3">
              <Zap size={18} className="text-white" fill="white" />
            </div>
            <h1 className="text-headline-sm text-on-surface mb-1">Create your account</h1>
            <p className="text-body-sm text-outline text-center">Join Stop Hunter Pro · Free to start</p>
          </div>

          {/* Step progress */}
          <StepProgress step={step} />

          {/* Banner error */}
          <AnimatePresence>
            {banner && (
              <motion.div
                key="banner"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="mb-5 flex items-start gap-2.5 rounded-lg px-3.5 py-3"
                style={{ background: 'rgba(255,77,79,0.08)', border: '1px solid rgba(255,77,79,0.25)' }}
              >
                <AlertCircle size={14} className="text-bearish flex-shrink-0 mt-0.5" />
                <p className="text-body-sm text-bearish leading-snug">{banner}</p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Animated step content */}
          <div className="overflow-hidden">
            <AnimatePresence mode="wait" custom={dir}>
              {/* ── Step 1: Personal Details ─────────────────────────────────── */}
              {step === 1 && (
                <motion.div
                  key="step1"
                  custom={dir}
                  variants={slideVariants}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                >
                  <Field label="Full Name" error={errors.full_name}>
                    <TextInput
                      value={form.full_name}
                      onChange={set('full_name')}
                      placeholder="Arjun Mehta"
                      autoComplete="name"
                      error={errors.full_name}
                    />
                  </Field>
                  <Field label="Phone Number" error={errors.phone}>
                    <TextInput
                      value={form.phone}
                      onChange={set('phone')}
                      placeholder="9876543210"
                      type="tel"
                      autoComplete="tel"
                      error={errors.phone}
                    />
                  </Field>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Date of Birth" error={errors.dob}>
                      <input
                        type="date"
                        value={form.dob}
                        onChange={set('dob')}
                        max={new Date().toISOString().split('T')[0]}
                        className="w-full rounded-lg px-4 py-2.5 text-body-sm text-on-surface transition-colors duration-150 focus:outline-none"
                        style={inputStyle(!!errors.dob)}
                      />
                      <FieldError message={errors.dob} />
                    </Field>
                    <Field label="Gender" error={errors.gender}>
                      <SelectInput
                        value={form.gender}
                        onChange={set('gender')}
                        options={GENDER_OPTIONS}
                        placeholder="Select…"
                        error={errors.gender}
                      />
                    </Field>
                  </div>
                  <Field label="Address" error={errors.address}>
                    <TextInput
                      value={form.address}
                      onChange={set('address')}
                      placeholder="123, MG Road, Mumbai, Maharashtra"
                      autoComplete="street-address"
                      error={errors.address}
                    />
                  </Field>

                  <Button className="w-full justify-center mt-2" onClick={handleStep1Next}>
                    Continue <ArrowRight size={14} />
                  </Button>
                </motion.div>
              )}

              {/* ── Step 2: Account Details ───────────────────────────────────── */}
              {step === 2 && (
                <motion.div
                  key="step2"
                  custom={dir}
                  variants={slideVariants}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                >
                  <Field label="Username" error={errors.username}>
                    <TextInput
                      value={form.username}
                      onChange={set('username')}
                      placeholder="arjun_trader"
                      autoComplete="username"
                      error={errors.username}
                    />
                  </Field>
                  <Field label="Email" error={errors.email}>
                    <TextInput
                      value={form.email}
                      onChange={set('email')}
                      placeholder="arjun@example.com"
                      type="email"
                      autoComplete="email"
                      error={errors.email}
                    />
                  </Field>
                  <Field label="Password" error={errors.password}>
                    <div className="relative">
                      <input
                        type={showPwd ? 'text' : 'password'}
                        value={form.password}
                        onChange={set('password')}
                        autoComplete="new-password"
                        placeholder="Min 8 chars, 1 uppercase, 1 number"
                        className="w-full rounded-lg px-4 py-2.5 pr-11 text-body-sm text-on-surface placeholder:text-outline transition-colors duration-150 focus:outline-none"
                        style={inputStyle(!!errors.password)}
                        onFocus={(e) => { if (!errors.password) e.target.style.borderColor = 'rgba(0,102,255,0.7)' }}
                        onBlur={(e)  => { if (!errors.password) e.target.style.borderColor = 'rgba(255,255,255,0.10)' }}
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
                    {/* Password strength hints */}
                    {form.password && (
                      <div className="flex gap-3 mt-2">
                        {[
                          { ok: form.password.length >= 8,     label: '8+ chars' },
                          { ok: /[A-Z]/.test(form.password),   label: 'Uppercase' },
                          { ok: /[0-9]/.test(form.password),   label: 'Number' },
                        ].map(({ ok, label }) => (
                          <span
                            key={label}
                            className="font-mono text-[10px] flex items-center gap-1"
                            style={{ color: ok ? '#00d97e' : '#8c90a1' }}
                          >
                            <CheckCircle2 size={9} /> {label}
                          </span>
                        ))}
                      </div>
                    )}
                  </Field>

                  <div className="flex gap-3 mt-2">
                    <Button variant="ghost" className="flex-1 justify-center" onClick={() => goTo(1)}>
                      <ArrowLeft size={14} /> Back
                    </Button>
                    <Button className="flex-1 justify-center" onClick={handleStep2Next}>
                      Continue <ArrowRight size={14} />
                    </Button>
                  </div>
                </motion.div>
              )}

              {/* ── Step 3: Trading Profile ───────────────────────────────────── */}
              {step === 3 && (
                <motion.div
                  key="step3"
                  custom={dir}
                  variants={slideVariants}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                >
                  <p className="text-body-sm text-on-surface-variant mb-5 leading-relaxed">
                    Tell us about your trading background so we can tailor your scanner experience.
                  </p>

                  <div className="flex flex-col gap-3 mb-5">
                    {EXPERIENCE_OPTIONS.map((opt) => {
                      const selected = form.trading_experience === opt.value
                      return (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => { setForm((p) => ({ ...p, trading_experience: opt.value })); clearField(setErrors, 'trading_experience') }}
                          className={cn(
                            'w-full text-left rounded-lg px-4 py-3.5 transition-all duration-150 cursor-pointer bg-transparent',
                            'flex items-center gap-3',
                          )}
                          style={{
                            background: selected ? 'rgba(0,102,255,0.12)' : 'rgba(255,255,255,0.04)',
                            border: selected ? '1px solid rgba(0,102,255,0.6)' : '1px solid rgba(255,255,255,0.08)',
                          }}
                        >
                          <div
                            className="w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0"
                            style={{
                              border: selected ? '1px solid rgba(0,102,255,0.9)' : '1px solid rgba(255,255,255,0.25)',
                              background: selected ? 'rgba(0,102,255,0.9)' : 'transparent',
                            }}
                          >
                            {selected && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                          </div>
                          <span className={cn('text-body-sm', selected ? 'text-on-surface' : 'text-on-surface-variant')}>
                            {opt.label}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                  <FieldError message={errors.trading_experience} />

                  <div className="flex gap-3 mt-2">
                    <Button variant="ghost" className="flex-1 justify-center" onClick={() => goTo(2)} disabled={loading}>
                      <ArrowLeft size={14} /> Back
                    </Button>
                    <Button className="flex-1 justify-center" onClick={handleStep3Submit} disabled={loading}>
                      {loading ? (
                        <><span className="w-3.5 h-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" aria-hidden /> Creating…</>
                      ) : (
                        <>Create Account <ArrowRight size={14} /></>
                      )}
                    </Button>
                  </div>
                </motion.div>
              )}

              {/* ── Step 4: OTP Verification ──────────────────────────────────── */}
              {step === 4 && (
                <motion.div
                  key="step4"
                  custom={dir}
                  variants={slideVariants}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                >
                  <div className="text-center mb-6">
                    <p className="text-body-sm text-on-surface-variant leading-relaxed">
                      We sent a 6-digit OTP to{' '}
                      <span className="text-primary font-medium">{form.email}</span>.
                      Enter it below to verify your account.
                    </p>
                  </div>

                  <div className="mb-2">
                    <OtpInput value={otp} onChange={(v) => { setOtp(v); clearField(setErrors, 'otp') }} />
                    <FieldError message={errors.otp} />
                  </div>

                  <Button
                    className="w-full justify-center mt-4"
                    onClick={handleVerifyOtp}
                    disabled={loading || otp.length !== 6}
                  >
                    {loading ? (
                      <><span className="w-3.5 h-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" aria-hidden /> Verifying…</>
                    ) : (
                      'Verify OTP'
                    )}
                  </Button>

                  <button
                    type="button"
                    onClick={handleResendOtp}
                    disabled={loading || resendCooldown > 0}
                    className={cn(
                      'w-full mt-3 py-2 flex items-center justify-center gap-2',
                      'font-mono text-[12px] bg-transparent border-0 cursor-pointer transition-colors duration-200',
                      resendCooldown > 0 || loading ? 'text-outline cursor-not-allowed' : 'text-primary hover:text-on-surface',
                    )}
                  >
                    <RotateCcw size={12} />
                    {resendCooldown > 0 ? `Resend OTP in ${resendCooldown}s` : 'Resend OTP'}
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Footer */}
          {step < 4 && (
            <p className="mt-5 text-center text-body-sm text-outline">
              Already have an account?{' '}
              <Link to="/login" className="text-primary hover:text-on-surface transition-colors">
                Sign in
              </Link>
            </p>
          )}
        </div>
      </div>

      <p className="mt-6 font-mono text-[11px] text-outline text-center">
        Stop Hunter Pro · NSE / BSE · India market hours
      </p>
    </div>
  )
}
