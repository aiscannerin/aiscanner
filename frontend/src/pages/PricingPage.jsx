/**
 * PricingPage — /pricing
 *
 * Fetches plans + current subscription from backend.
 * Initiates Razorpay checkout for Pro / Expert upgrades.
 * Backend verify-payment is the sole authority for subscription activation.
 */
import { useEffect, useState, useCallback } from 'react'
import { useNavigate }                       from 'react-router-dom'
import { motion, AnimatePresence }           from 'framer-motion'
import { useAuth }                           from '../context/AuthContext'
import { useShowToast }                      from '../context/ToastContext'
import { useRazorpay }                       from '../hooks/useRazorpay'
import {
  apiGetPlans,
  apiCreateOrder,
  apiVerifyPayment,
  apiGetPaymentHistory,
  apiGetCurrentSub,
} from '../api/pricing'

// ── design tokens ─────────────────────────────────────────────────────────────
const T = {
  bg:      '#050810',
  surface: '#10131c',
  border:  'rgba(255,255,255,0.07)',
  muted:   '#8c90a1',
  text:    '#e1e2ee',
  primary: '#0066ff',
  cyan:    '#00f1fe',
  green:   '#00d97e',
  red:     '#ff4d4f',
  amber:   '#f59e0b',
  purple:  '#b3c5ff',
}

// plan display order
const PLAN_ORDER = { Free: 0, Pro: 1, Expert: 2 }

// hardcoded feature bullets per plan name (backend provides tools list too)
const PLAN_FEATURES = {
  Free: [
    'Basic market scanner access',
    'NIFTY 50 universe',
    'Daily scan limit: 5',
    'Community support',
  ],
  Pro: [
    'All Free features',
    'NIFTY 100 + FNO universes',
    'Unlimited daily scans',
    'Stop Hunter Pro scanner',
    'Priority email support',
  ],
  Expert: [
    'All Pro features',
    'NIFTY 500 universe',
    'All current + future scanners',
    'Advanced filters & scoring',
    'Dedicated support channel',
  ],
}

// per-plan accent color
const PLAN_ACCENT = {
  Free:   { color: T.muted,   glow: 'rgba(140,144,161,0.1)',  border: 'rgba(255,255,255,0.08)' },
  Pro:    { color: T.primary, glow: 'rgba(0,102,255,0.12)',   border: 'rgba(0,102,255,0.3)'    },
  Expert: { color: T.cyan,    glow: 'rgba(0,241,254,0.1)',    border: 'rgba(0,241,254,0.25)'   },
}

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtINR(n) {
  if (!n) return '0'
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

function savingsPct(plan) {
  if (!plan.monthly_price || !plan.yearly_price) return 0
  const monthlyAnnual = plan.monthly_price * 12
  return Math.round(((monthlyAnnual - plan.yearly_price) / monthlyAnnual) * 100)
}

function payStatusColor(s) {
  if (s === 'paid')    return T.green
  if (s === 'failed')  return T.red
  if (s === 'created') return T.amber
  return T.muted
}

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function planTier(name) {
  return PLAN_ORDER[name] ?? -1
}

// ── tiny components ───────────────────────────────────────────────────────────

function Toggle({ yearly, onChange }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', justifyContent: 'center' }}>
      <span style={{ fontSize: '13px', fontWeight: 600, color: !yearly ? T.text : T.muted }}>Monthly</span>
      <div
        onClick={() => onChange(!yearly)}
        style={{
          width: '48px', height: '26px', borderRadius: '13px',
          background: yearly ? T.primary : 'rgba(255,255,255,0.12)',
          position: 'relative', cursor: 'pointer',
          transition: 'background 0.2s',
          border: '1px solid rgba(255,255,255,0.12)',
        }}
      >
        <motion.div
          animate={{ x: yearly ? 22 : 2 }}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          style={{
            position: 'absolute', top: '2px',
            width: '20px', height: '20px',
            borderRadius: '50%', background: '#fff',
          }}
        />
      </div>
      <span style={{ fontSize: '13px', fontWeight: 600, color: yearly ? T.text : T.muted }}>
        Yearly
        <span style={{
          marginLeft: '6px', fontSize: '10px', fontWeight: 700,
          padding: '2px 6px', borderRadius: '20px',
          background: 'rgba(0,217,126,0.15)', color: T.green,
        }}>SAVE UP TO 20%</span>
      </span>
    </div>
  )
}

function Skeleton({ h = '18px', w = '100%', r = '6px' }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: r,
      background: 'linear-gradient(90deg,rgba(255,255,255,0.04) 25%,rgba(255,255,255,0.08) 50%,rgba(255,255,255,0.04) 75%)',
      backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite',
    }} />
  )
}

function CheckIcon({ color = T.green }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, marginTop: '2px' }}>
      <circle cx="8" cy="8" r="8" fill={`${color}20`} />
      <path d="M5 8l2 2 4-4" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ── Plan card ─────────────────────────────────────────────────────────────────

function PlanCard({ plan, yearly, currentPlan, onUpgrade, checkingOut }) {
  const accent   = PLAN_ACCENT[plan.name] ?? PLAN_ACCENT.Free
  const isFree   = plan.name === 'Free'
  const isCurrent = currentPlan?.plan?.name === plan.name
  const savings  = savingsPct(plan)
  const currentTier = planTier(currentPlan?.plan?.name ?? 'Free')
  const thisTier    = planTier(plan.name)
  const isUpgrade   = thisTier > currentTier
  const isDowngrade = thisTier < currentTier && !isFree

  const price = isFree
    ? 0
    : yearly
      ? plan.yearly_price
      : plan.monthly_price

  const priceLabel = isFree
    ? 'Free forever'
    : yearly
      ? `₹${fmtINR(plan.yearly_price)} / year`
      : `₹${fmtINR(plan.monthly_price)} / month`

  const perMonthEquiv = isFree
    ? null
    : yearly && plan.yearly_price
      ? `≈ ₹${fmtINR(Math.round(plan.yearly_price / 12))} / month`
      : null

  const isPopular = plan.name === 'Pro'

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
      style={{
        background: isPopular
          ? `radial-gradient(ellipse at top, rgba(0,102,255,0.14), ${T.surface} 65%)`
          : T.surface,
        border: `1px solid ${isCurrent ? accent.color : accent.border}`,
        borderRadius: '20px',
        padding: '28px',
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: isPopular ? `0 0 40px rgba(0,102,255,0.12)` : 'none',
      }}
    >
      {/* badges */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', minHeight: '24px' }}>
        {isPopular && (
          <span style={{
            fontSize: '10px', fontWeight: 700, padding: '3px 10px',
            borderRadius: '20px', letterSpacing: '0.08em',
            background: 'rgba(0,102,255,0.2)', color: accent.color,
            border: `1px solid ${accent.color}40`,
          }}>MOST POPULAR</span>
        )}
        {plan.name === 'Expert' && (
          <span style={{
            fontSize: '10px', fontWeight: 700, padding: '3px 10px',
            borderRadius: '20px', letterSpacing: '0.08em',
            background: 'rgba(0,241,254,0.12)', color: T.cyan,
            border: '1px solid rgba(0,241,254,0.25)',
          }}>ALL ACCESS</span>
        )}
        {isCurrent && (
          <span style={{
            fontSize: '10px', fontWeight: 700, padding: '3px 10px',
            borderRadius: '20px', letterSpacing: '0.08em',
            background: 'rgba(0,217,126,0.12)', color: T.green,
            border: '1px solid rgba(0,217,126,0.25)',
          }}>✓ CURRENT</span>
        )}
      </div>

      {/* plan name */}
      <div style={{ fontSize: '20px', fontWeight: 700, color: accent.color, marginBottom: '6px' }}>
        {plan.name}
      </div>
      <div style={{ fontSize: '13px', color: T.muted, marginBottom: '24px', lineHeight: 1.5, minHeight: '40px' }}>
        {plan.description || `Stop Hunter Pro ${plan.name} plan`}
      </div>

      {/* price */}
      <div style={{ marginBottom: '8px' }}>
        <span style={{ fontSize: '36px', fontWeight: 800, color: T.text, letterSpacing: '-0.02em' }}>
          {isFree ? '₹0' : `₹${fmtINR(price)}`}
        </span>
        {!isFree && (
          <span style={{ fontSize: '14px', color: T.muted, marginLeft: '4px' }}>
            {yearly ? '/ yr' : '/ mo'}
          </span>
        )}
      </div>
      {perMonthEquiv && (
        <div style={{ fontSize: '12px', color: T.muted, marginBottom: '4px' }}>{perMonthEquiv}</div>
      )}
      {!isFree && yearly && savings > 0 && (
        <div style={{ fontSize: '12px', color: T.green, fontWeight: 600, marginBottom: '4px' }}>
          Save {savings}% vs monthly
        </div>
      )}
      <div style={{ height: '1px', background: T.border, margin: '20px 0' }} />

      {/* features */}
      <ul style={{ listStyle: 'none', margin: '0 0 24px', padding: 0, display: 'flex', flexDirection: 'column', gap: '10px', flex: 1 }}>
        {(PLAN_FEATURES[plan.name] ?? []).map(f => (
          <li key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '13px', color: T.muted }}>
            <CheckIcon color={accent.color} />
            <span>{f}</span>
          </li>
        ))}
        {/* tools from backend */}
        {(plan.tools ?? []).map(t => (
          <li key={t.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '13px', color: T.muted }}>
            <CheckIcon color={accent.color} />
            <span>Scanner: {t.name}</span>
          </li>
        ))}
      </ul>

      {/* CTA button */}
      {isFree ? (
        <button disabled style={{
          width: '100%', padding: '12px', borderRadius: '10px',
          background: 'rgba(255,255,255,0.05)',
          border: `1px solid ${T.border}`,
          color: T.muted, fontSize: '14px', fontWeight: 600, cursor: 'not-allowed',
        }}>
          {isCurrent ? '✓ Your current plan' : 'Free forever'}
        </button>
      ) : isCurrent ? (
        <button disabled style={{
          width: '100%', padding: '12px', borderRadius: '10px',
          background: 'rgba(0,217,126,0.08)',
          border: '1px solid rgba(0,217,126,0.25)',
          color: T.green, fontSize: '14px', fontWeight: 600, cursor: 'not-allowed',
        }}>
          ✓ Active plan
        </button>
      ) : isUpgrade ? (
        <button
          onClick={() => onUpgrade(plan, yearly ? 'yearly' : 'monthly')}
          disabled={checkingOut}
          style={{
            width: '100%', padding: '12px', borderRadius: '10px',
            background: checkingOut
              ? 'rgba(0,102,255,0.4)'
              : `linear-gradient(135deg, ${accent.color}, ${plan.name === 'Expert' ? '#0099cc' : '#0052cc'})`,
            border: 'none',
            color: '#fff', fontSize: '14px', fontWeight: 700, cursor: checkingOut ? 'not-allowed' : 'pointer',
            boxShadow: checkingOut ? 'none' : `0 0 24px ${accent.glow}`,
            transition: 'box-shadow 0.2s',
          }}
        >
          {checkingOut ? '⏳ Opening checkout…' : `Upgrade to ${plan.name} →`}
        </button>
      ) : isDowngrade ? (
        <button disabled style={{
          width: '100%', padding: '12px', borderRadius: '10px',
          background: 'rgba(255,255,255,0.04)',
          border: `1px solid ${T.border}`,
          color: T.muted, fontSize: '13px', fontWeight: 600, cursor: 'not-allowed',
        }}>
          Lower tier — contact support
        </button>
      ) : null}
    </motion.div>
  )
}

// ── Payment history table ─────────────────────────────────────────────────────

function PaymentHistory({ payments, loading, error }) {
  return (
    <div style={{ marginTop: '60px' }}>
      <div style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.muted, marginBottom: '14px' }}>
        Payment History
      </div>
      <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: '16px', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {[1,2,3].map(i => <Skeleton key={i} h="20px" />)}
          </div>
        ) : error ? (
          <div style={{ padding: '20px', color: T.red, fontSize: '13px' }}>{error}</div>
        ) : payments.length === 0 ? (
          <div style={{ padding: '36px', textAlign: 'center' }}>
            <div style={{ fontSize: '28px', marginBottom: '10px' }}>🧾</div>
            <div style={{ fontSize: '14px', color: T.muted }}>No payments yet.</div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  {['Date','Plan','Billing','Amount','Order ID','Status'].map(h => (
                    <th key={h} style={{
                      padding: '11px 16px', textAlign: 'left',
                      fontSize: '10px', fontWeight: 700, letterSpacing: '0.07em',
                      textTransform: 'uppercase', color: T.muted, whiteSpace: 'nowrap',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {payments.map((p, i) => (
                  <tr key={p.id} style={{ borderBottom: i < payments.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
                    <td style={{ padding: '12px 16px', fontSize: '12px', color: T.muted }}>{fmtDate(p.created_at)}</td>
                    <td style={{ padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: T.text }}>{p.plan?.name ?? '—'}</td>
                    <td style={{ padding: '12px 16px', fontSize: '12px', color: T.muted, textTransform: 'capitalize' }}>{p.billing_cycle}</td>
                    <td style={{ padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: T.purple }}>
                      ₹{fmtINR(p.amount)}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: '11px', color: T.muted, fontFamily: 'monospace' }}>
                      {p.razorpay_order_id ? p.razorpay_order_id.slice(0, 20) + '…' : '—'}
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: '5px',
                        fontSize: '11px', fontWeight: 700, textTransform: 'uppercase',
                        color: payStatusColor(p.status),
                        padding: '2px 8px', borderRadius: '20px',
                        background: `${payStatusColor(p.status)}14`,
                      }}>
                        {p.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── main page ─────────────────────────────────────────────────────────────────

const fadeUp = { hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0, transition: { duration: 0.4 } } }

export default function PricingPage() {
  const { user }     = useAuth()
  const navigate     = useNavigate()
  const showToast    = useShowToast()
  const { openCheckout } = useRazorpay()

  const [yearly,       setYearly]       = useState(false)
  const [plans,        setPlans]        = useState([])
  const [currentSub,   setCurrentSub]   = useState(null)
  const [payments,     setPayments]     = useState([])
  const [loading,      setLoading]      = useState({ plans: true, sub: true, payments: true })
  const [errors,       setErrors]       = useState({ plans: null, payments: null })
  const [checkingOut,  setCheckingOut]  = useState(false)

  useEffect(() => {
    apiGetPlans()
      .then(r => {
        const raw = r.data?.data ?? []
        const sorted = [...raw].sort((a, b) => (PLAN_ORDER[a.name] ?? 99) - (PLAN_ORDER[b.name] ?? 99))
        setPlans(sorted)
      })
      .catch(() => setErrors(e => ({ ...e, plans: 'Could not load plans.' })))
      .finally(() => setLoading(l => ({ ...l, plans: false })))

    apiGetCurrentSub()
      .then(r => setCurrentSub(r.data?.data ?? null))
      .catch(() => {})
      .finally(() => setLoading(l => ({ ...l, sub: false })))

    apiGetPaymentHistory()
      .then(r => setPayments(r.data?.data ?? []))
      .catch(() => setErrors(e => ({ ...e, payments: 'Could not load payment history.' })))
      .finally(() => setLoading(l => ({ ...l, payments: false })))
  }, [])

  const handleUpgrade = useCallback(async (plan, billingCycle) => {
    if (checkingOut) return
    setCheckingOut(true)

    let orderData
    try {
      const res = await apiCreateOrder({ plan_id: plan.id, billing_cycle: billingCycle })
      orderData = res.data?.data
      if (!orderData?.order_id) throw new Error('No order_id returned.')
    } catch (err) {
      const msg = err.response?.data?.message ?? 'Could not create payment order. Please try again.'
      showToast(msg, 'error')
      setCheckingOut(false)
      return
    }

    openCheckout({
      key_id:       orderData.key_id,
      order_id:     orderData.order_id,
      amount:       orderData.amount,
      currency:     orderData.currency ?? 'INR',
      planName:     plan.name,
      billingCycle,
      prefill: {
        name:  user?.full_name || user?.username || '',
        email: user?.email || '',
      },

      onDismiss() {
        showToast('Payment cancelled. No charge was made.', 'info')
        setCheckingOut(false)
      },

      onScriptError(err) {
        showToast(err.message ?? 'Payment gateway unavailable. Please try again.', 'error')
        setCheckingOut(false)
      },

      async onSuccess(rzpResponse) {
        try {
          await apiVerifyPayment({
            razorpay_order_id:  rzpResponse.razorpay_order_id,
            razorpay_payment_id: rzpResponse.razorpay_payment_id,
            razorpay_signature:  rzpResponse.razorpay_signature,
          })
          showToast(`🎉 Payment successful! ${plan.name} plan is now active.`, 'success')
          navigate('/dashboard')
        } catch (err) {
          // Signature invalid or server error — user paid but activation may have failed
          const msg = err.response?.data?.message ?? 'Payment received but verification failed. Please contact support.'
          showToast(msg, 'error')
          setCheckingOut(false)
        }
      },
    })
    // setCheckingOut(false) is called inside onDismiss / onScriptError / onSuccess (error path)
    // Do NOT reset here — checkout modal is still open
  }, [checkingOut, openCheckout, user, showToast, navigate])

  const plansLoading = loading.plans || loading.sub

  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.text, fontFamily: 'Inter, ui-sans-serif, sans-serif' }}>
      <style>{`
        @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #10131c; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }
      `}</style>

      {/* ── nav ──────────────────────────────────────────────────────── */}
      <nav style={{
        position: 'sticky', top: 0, zIndex: 50,
        background: 'rgba(5,8,16,0.88)', backdropFilter: 'blur(20px)',
        borderBottom: `1px solid ${T.border}`,
        padding: '0 24px', height: '60px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <button
            onClick={() => navigate('/dashboard')}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              background: 'rgba(255,255,255,0.05)',
              border: `1px solid ${T.border}`, borderRadius: '8px',
              padding: '6px 13px', color: T.muted, fontSize: '13px', cursor: 'pointer',
            }}
          >
            ← Dashboard
          </button>
          <div style={{ width: '1px', height: '20px', background: T.border }} />
          <div>
            <div style={{ fontSize: '15px', fontWeight: 700, color: T.text }}>Plans & Pricing</div>
            <div style={{ fontSize: '11px', color: T.muted }}>Stop Hunter Pro</div>
          </div>
        </div>
        {currentSub?.plan?.name && (
          <div style={{
            fontSize: '11px', fontWeight: 600, padding: '3px 12px',
            borderRadius: '20px', letterSpacing: '0.06em',
            background: 'rgba(179,197,255,0.1)',
            border: '1px solid rgba(179,197,255,0.2)',
            color: T.purple,
          }}>
            Current: {currentSub.plan.name}
          </div>
        )}
      </nav>

      {/* ── body ─────────────────────────────────────────────────────── */}
      <div style={{ maxWidth: '1000px', margin: '0 auto', padding: '48px 24px 80px' }}>

        {/* hero */}
        <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ textAlign: 'center', marginBottom: '40px' }}>
          <h1 style={{ fontSize: '36px', fontWeight: 800, color: T.text, letterSpacing: '-0.02em', margin: '0 0 12px' }}>
            Unlock institutional-grade scanning
          </h1>
          <p style={{ fontSize: '16px', color: T.muted, margin: '0 0 32px', lineHeight: 1.6 }}>
            NSE &amp; BSE · Stop-hunt · Order-block · Smart money flow detection
          </p>
          <Toggle yearly={yearly} onChange={setYearly} />
        </motion.div>

        {/* plan cards */}
        {errors.plans ? (
          <div style={{ color: T.red, textAlign: 'center', padding: '40px', background: 'rgba(255,77,79,0.08)', borderRadius: '14px', border: '1px solid rgba(255,77,79,0.2)', marginBottom: '24px' }}>
            {errors.plans}
          </div>
        ) : plansLoading ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px,1fr))', gap: '20px' }}>
            {[1,2,3].map(i => <Skeleton key={i} h="400px" r="20px" />)}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px,1fr))', gap: '20px' }}>
            {plans.map(plan => (
              <PlanCard
                key={plan.id}
                plan={plan}
                yearly={yearly}
                currentPlan={currentSub}
                onUpgrade={handleUpgrade}
                checkingOut={checkingOut}
              />
            ))}
          </div>
        )}

        {/* fine print */}
        <div style={{ textAlign: 'center', marginTop: '28px', fontSize: '12px', color: T.muted, lineHeight: 1.7 }}>
          All prices in INR · Inclusive of applicable taxes ·&nbsp;
          Payments secured by Razorpay · Subscriptions auto-expire and require manual renewal.
        </div>

        {/* payment history */}
        <PaymentHistory
          payments={payments}
          loading={loading.payments}
          error={errors.payments}
        />
      </div>
    </div>
  )
}
