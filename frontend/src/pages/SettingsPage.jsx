/**
 * SettingsPage — /settings
 *
 * Profile fields: read-only (no backend update endpoint yet).
 * Subscription mini-card → /pricing.
 * Change password placeholder → "coming soon" toast.
 * Logout.
 */
import { useEffect, useState } from 'react'
import { useNavigate }         from 'react-router-dom'
import { motion }              from 'framer-motion'
import { useAuth }             from '../context/AuthContext'
import { useShowToast }        from '../context/ToastContext'
import { apiGetMe }            from '../api/auth'
import { apiGetCurrentSub }    from '../api/pricing'

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

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtGender(g) {
  const map = { male: 'Male', female: 'Female', other: 'Other', prefer_not_to_say: 'Prefer not to say' }
  return map[g] ?? g ?? '—'
}

function fmtExp(e) {
  const map = { beginner: 'Beginner', intermediate: 'Intermediate', advanced: 'Advanced' }
  return map[e] ?? e ?? '—'
}

function fmtDob(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'long', year: 'numeric' })
}

function planBadgeStyle(name) {
  if (!name || name === 'Free') return { bg: 'rgba(179,197,255,0.08)', color: T.muted, border: 'rgba(255,255,255,0.1)' }
  if (name === 'Pro')    return { bg: 'rgba(0,102,255,0.15)',   color: '#6096ff',  border: 'rgba(0,102,255,0.3)'   }
  if (name === 'Expert') return { bg: 'rgba(0,241,254,0.12)',   color: T.cyan,     border: 'rgba(0,241,254,0.25)'  }
  return { bg: 'rgba(179,197,255,0.08)', color: T.muted, border: 'rgba(255,255,255,0.1)' }
}

function Skeleton({ h = '18px', w = '100%' }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: '6px',
      background: 'linear-gradient(90deg,rgba(255,255,255,0.04) 25%,rgba(255,255,255,0.08) 50%,rgba(255,255,255,0.04) 75%)',
      backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite',
    }} />
  )
}

// ── sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em',
      textTransform: 'uppercase', color: T.muted,
      marginBottom: '14px', paddingBottom: '8px',
      borderBottom: `1px solid ${T.border}`,
    }}>
      {children}
    </div>
  )
}

function ProfileRow({ label, value, loading }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
      padding: '12px 0', borderBottom: `1px solid rgba(255,255,255,0.04)`,
      gap: '16px',
    }}>
      <span style={{ fontSize: '12px', color: T.muted, minWidth: '130px', flexShrink: 0, paddingTop: '1px' }}>
        {label}
      </span>
      {loading
        ? <Skeleton h="16px" w="160px" />
        : <span style={{ fontSize: '13px', color: T.text, fontWeight: 500, wordBreak: 'break-all', textAlign: 'right' }}>
            {value ?? '—'}
          </span>
      }
    </div>
  )
}

function VerifiedBadge({ verified }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      fontSize: '11px', fontWeight: 700,
      padding: '2px 9px', borderRadius: '20px',
      background: verified ? 'rgba(0,217,126,0.12)' : 'rgba(245,158,11,0.12)',
      color: verified ? T.green : T.amber,
      border: `1px solid ${verified ? 'rgba(0,217,126,0.25)' : 'rgba(245,158,11,0.25)'}`,
    }}>
      {verified ? '✓ Verified' : '⚠ Unverified'}
    </span>
  )
}

// ── main ─────────────────────────────────────────────────────────────────────

const fadeUp = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0, transition: { duration: 0.38 } } }
const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

export default function SettingsPage() {
  const { user: authUser, logout } = useAuth()
  const navigate   = useNavigate()
  const showToast  = useShowToast()

  const [profile,  setProfile]  = useState(null)
  const [sub,      setSub]      = useState(null)
  const [loadingP, setLoadingP] = useState(true)
  const [loadingS, setLoadingS] = useState(true)

  useEffect(() => {
    // Fetch fresh profile from server (covers any updates since login)
    apiGetMe()
      .then(r => setProfile(r.data?.data ?? authUser))
      .catch(() => setProfile(authUser))  // fall back to AuthContext user
      .finally(() => setLoadingP(false))

    apiGetCurrentSub()
      .then(r => setSub(r.data?.data ?? null))
      .catch(() => {})
      .finally(() => setLoadingS(false))
  }, [authUser])

  function handleLogout() {
    logout()
    navigate('/')
  }

  const planName  = sub?.plan?.name ?? 'Free'
  const badge     = planBadgeStyle(planName)
  const loading   = loadingP

  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.text, fontFamily: 'Inter, ui-sans-serif, sans-serif' }}>
      <style>{`
        @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
        ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: #10131c; } ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }
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
              background: 'rgba(255,255,255,0.05)', border: `1px solid ${T.border}`,
              borderRadius: '8px', padding: '6px 13px',
              color: T.muted, fontSize: '13px', cursor: 'pointer',
            }}
          >
            ← Dashboard
          </button>
          <div style={{ width: '1px', height: '20px', background: T.border }} />
          <div>
            <div style={{ fontSize: '15px', fontWeight: 700, color: T.text }}>Settings</div>
            <div style={{ fontSize: '11px', color: T.muted }}>Account &amp; Profile</div>
          </div>
        </div>
        <button
          onClick={handleLogout}
          style={{
            padding: '7px 16px', borderRadius: '8px',
            background: 'rgba(255,77,79,0.08)', border: '1px solid rgba(255,77,79,0.2)',
            color: T.red, fontSize: '13px', fontWeight: 600, cursor: 'pointer',
          }}
        >
          Sign out
        </button>
      </nav>

      {/* ── body ─────────────────────────────────────────────────────── */}
      <div style={{ maxWidth: '720px', margin: '0 auto', padding: '32px 24px 80px' }}>
        <motion.div variants={stagger} initial="hidden" animate="show" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

          {/* ── Profile card ───────────────────────────────────────── */}
          <motion.div variants={fadeUp}>
            <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: '16px', padding: '24px 28px' }}>
              <SectionLabel>Profile Information</SectionLabel>

              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '24px', flexWrap: 'wrap' }}>
                {/* Avatar initials */}
                <div style={{
                  width: '56px', height: '56px', borderRadius: '14px',
                  background: 'linear-gradient(135deg,#0066ff,#00f1fe)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '22px', fontWeight: 800, color: '#fff', flexShrink: 0,
                }}>
                  {loading ? '…' : (profile?.full_name?.[0] ?? profile?.email?.[0] ?? '?').toUpperCase()}
                </div>
                <div>
                  {loading
                    ? <Skeleton h="20px" w="160px" />
                    : <div style={{ fontSize: '18px', fontWeight: 700, color: T.text }}>{profile?.full_name ?? '—'}</div>
                  }
                  {loading
                    ? <Skeleton h="14px" w="120px" />
                    : <div style={{ fontSize: '13px', color: T.muted, marginTop: '3px' }}>@{profile?.username ?? '—'}</div>
                  }
                </div>
                <div style={{ marginLeft: 'auto' }}>
                  {loading
                    ? <Skeleton h="22px" w="80px" />
                    : <VerifiedBadge verified={profile?.email_verified} />
                  }
                </div>
              </div>

              <ProfileRow label="Email"              value={profile?.email}             loading={loading} />
              <ProfileRow label="Phone"              value={profile?.phone}             loading={loading} />
              <ProfileRow label="Date of Birth"      value={fmtDob(profile?.dob)}       loading={loading} />
              <ProfileRow label="Gender"             value={fmtGender(profile?.gender)} loading={loading} />
              <ProfileRow label="Address"            value={profile?.address}           loading={loading} />
              <ProfileRow label="Trading Experience" value={fmtExp(profile?.trading_experience)} loading={loading} />
              <ProfileRow label="Member since"       value={profile?.created_at ? new Date(profile.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'long', year: 'numeric' }) : null} loading={loading} />

              <div style={{ marginTop: '20px' }}>
                <button
                  onClick={() => showToast('Profile editing is coming soon!', 'info')}
                  style={{
                    padding: '9px 20px', borderRadius: '9px',
                    background: 'rgba(179,197,255,0.08)',
                    border: '1px solid rgba(179,197,255,0.2)',
                    color: T.purple, fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  ✏ Edit Profile — coming soon
                </button>
              </div>
            </div>
          </motion.div>

          {/* ── Subscription card ──────────────────────────────────── */}
          <motion.div variants={fadeUp}>
            <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: '16px', padding: '24px 28px' }}>
              <SectionLabel>Subscription</SectionLabel>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
                <div style={{ display: 'flex', align: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ fontSize: '11px', color: T.muted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '5px' }}>Current Plan</div>
                    {loadingS
                      ? <Skeleton h="20px" w="80px" />
                      : (
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', gap: '6px',
                          padding: '3px 12px', borderRadius: '20px', fontSize: '13px', fontWeight: 700,
                          background: badge.bg, color: badge.color, border: `1px solid ${badge.border}`,
                        }}>
                          {planName}
                        </span>
                      )
                    }
                  </div>

                  {!loadingS && sub?.billing_cycle && sub.billing_cycle !== 'free' && (
                    <div>
                      <div style={{ fontSize: '11px', color: T.muted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '5px' }}>Billing</div>
                      <div style={{ fontSize: '13px', color: T.text, fontWeight: 500, textTransform: 'capitalize' }}>{sub.billing_cycle}</div>
                    </div>
                  )}

                  {!loadingS && sub?.days_remaining != null && (
                    <div>
                      <div style={{ fontSize: '11px', color: T.muted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '5px' }}>Days Left</div>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: sub.days_remaining <= 7 ? T.amber : T.green }}>
                        {sub.days_remaining <= 0 ? 'Expired' : `${sub.days_remaining}d`}
                      </div>
                    </div>
                  )}
                </div>

                <button
                  onClick={() => navigate('/pricing')}
                  style={{
                    padding: '9px 20px', borderRadius: '9px',
                    background: `linear-gradient(90deg,${T.primary},#0052cc)`,
                    border: 'none', color: '#fff',
                    fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                    boxShadow: '0 0 16px rgba(0,102,255,0.25)',
                  }}
                >
                  {planName === 'Expert' ? 'Manage Plan →' : 'Upgrade Plan →'}
                </button>
              </div>
            </div>
          </motion.div>

          {/* ── Security card ──────────────────────────────────────── */}
          <motion.div variants={fadeUp}>
            <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: '16px', padding: '24px 28px' }}>
              <SectionLabel>Security</SectionLabel>

              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                flexWrap: 'wrap', gap: '16px',
                padding: '14px 0', borderBottom: `1px solid rgba(255,255,255,0.04)`,
              }}>
                <div>
                  <div style={{ fontSize: '14px', fontWeight: 600, color: T.text, marginBottom: '4px' }}>Password</div>
                  <div style={{ fontSize: '12px', color: T.muted }}>Change your account password via email OTP.</div>
                </div>
                <button
                  onClick={() => navigate('/forgot-password')}
                  style={{
                    padding: '8px 18px', borderRadius: '9px',
                    background: 'rgba(255,255,255,0.06)',
                    border: `1px solid ${T.border}`,
                    color: T.text, fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  Change Password →
                </button>
              </div>

              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                flexWrap: 'wrap', gap: '16px',
                padding: '14px 0',
              }}>
                <div>
                  <div style={{ fontSize: '14px', fontWeight: 600, color: T.text, marginBottom: '4px' }}>Two-Factor Authentication</div>
                  <div style={{ fontSize: '12px', color: T.muted }}>Add an extra layer of security to your account.</div>
                </div>
                <button
                  onClick={() => showToast('2FA is coming soon!', 'info')}
                  style={{
                    padding: '8px 18px', borderRadius: '9px',
                    background: 'rgba(255,255,255,0.04)',
                    border: `1px solid ${T.border}`,
                    color: T.muted, fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  Enable 2FA — soon
                </button>
              </div>

              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                flexWrap: 'wrap', gap: '16px',
                padding: '14px 0',
              }}>
                <div>
                  <div style={{ fontSize: '14px', fontWeight: 600, color: T.text, marginBottom: '4px' }}>Help &amp; Support</div>
                  <div style={{ fontSize: '12px', color: T.muted }}>FAQs, contact form, and legal information.</div>
                </div>
                <button
                  onClick={() => navigate('/support')}
                  style={{
                    padding: '8px 18px', borderRadius: '9px',
                    background: 'rgba(255,255,255,0.06)',
                    border: `1px solid ${T.border}`,
                    color: T.text, fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  Go to Support →
                </button>
              </div>
            </div>
          </motion.div>

          {/* ── Danger zone ────────────────────────────────────────── */}
          <motion.div variants={fadeUp}>
            <div style={{ background: 'rgba(255,77,79,0.04)', border: '1px solid rgba(255,77,79,0.15)', borderRadius: '16px', padding: '24px 28px' }}>
              <SectionLabel>Account</SectionLabel>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <div style={{ fontSize: '14px', fontWeight: 600, color: T.text, marginBottom: '4px' }}>Sign out</div>
                  <div style={{ fontSize: '12px', color: T.muted }}>You will be logged out on this device.</div>
                </div>
                <button
                  onClick={handleLogout}
                  style={{
                    padding: '8px 18px', borderRadius: '9px',
                    background: 'rgba(255,77,79,0.1)',
                    border: '1px solid rgba(255,77,79,0.25)',
                    color: T.red, fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  Sign Out
                </button>
              </div>
            </div>
          </motion.div>

        </motion.div>
      </div>
    </div>
  )
}
