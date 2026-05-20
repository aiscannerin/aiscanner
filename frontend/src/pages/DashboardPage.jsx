import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../context/AuthContext'
import { useShowToast } from '../context/ToastContext'
import { apiGetSubscription, apiGetAccessibleTools, apiGetRecentScans } from '../api/dashboard'

// ── Icons (inline SVG) ────────────────────────────────────────────────────────

function IconScan() {
  return (
    <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7V5a2 2 0 012-2h2M17 3h2a2 2 0 012 2v2M21 17v2a2 2 0 01-2 2h-2M7 21H5a2 2 0 01-2-2v-2" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 12h10M12 7v10" />
    </svg>
  )
}

function IconTrend() {
  return (
    <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
    </svg>
  )
}

function IconZap() {
  return (
    <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  )
}

function IconClock() {
  return (
    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <circle cx="12" cy="12" r="10" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6l4 2" />
    </svg>
  )
}

function IconLock() {
  return (
    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 11V7a5 5 0 0110 0v4" />
    </svg>
  )
}

function IconPricing() {
  return (
    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function IconLogout() {
  return (
    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
    </svg>
  )
}

// ── Tool icon map ─────────────────────────────────────────────────────────────

const TOOL_ICONS = {
  'oi-spurts':          <IconTrend />,
  'top-gainers-losers': <IconTrend />,
  'volume-shockers':    <IconZap />,
  'price-action':       <IconScan />,
  'fii-dii-tracker':    <IconTrend />,
}

const TOOL_COLORS = {
  'oi-spurts':          { icon: '#00f1fe', glow: 'rgba(0,241,254,0.12)' },
  'top-gainers-losers': { icon: '#00d97e', glow: 'rgba(0,217,126,0.12)' },
  'volume-shockers':    { icon: '#b3c5ff', glow: 'rgba(179,197,255,0.12)' },
  'price-action':       { icon: '#f59e0b', glow: 'rgba(245,158,11,0.12)' },
  'fii-dii-tracker':    { icon: '#a78bfa', glow: 'rgba(167,139,250,0.12)' },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function planBadgeStyle(plan) {
  if (!plan) return { bg: 'rgba(179,197,255,0.1)', color: '#b3c5ff', border: 'rgba(179,197,255,0.2)' }
  const p = plan.toLowerCase()
  if (p === 'pro')    return { bg: 'rgba(0,102,255,0.15)', color: '#6096ff', border: 'rgba(0,102,255,0.3)' }
  if (p === 'expert') return { bg: 'rgba(0,241,254,0.12)', color: '#00f1fe', border: 'rgba(0,241,254,0.25)' }
  return { bg: 'rgba(179,197,255,0.08)', color: '#8c90a1', border: 'rgba(255,255,255,0.1)' }
}

function statusDot(status) {
  if (status === 'active')   return '#00d97e'
  if (status === 'expiring') return '#f59e0b'
  return '#ff4d4f'
}

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true })
}

function jobStatusColor(status) {
  if (status === 'completed') return '#00d97e'
  if (status === 'running')   return '#00f1fe'
  if (status === 'failed')    return '#ff4d4f'
  return '#8c90a1'
}

// ── Skeleton loader ───────────────────────────────────────────────────────────

function Skeleton({ w = '100%', h = '20px', radius = '6px' }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: radius,
      background: 'linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%)',
      backgroundSize: '200% 100%',
      animation: 'shimmer 1.5s infinite',
    }} />
  )
}

// ── Section animations ────────────────────────────────────────────────────────

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] } },
}

const stagger = {
  hidden: {},
  show:   { transition: { staggerChildren: 0.07 } },
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { user, logout } = useAuth()
  const showToast = useShowToast()
  const navigate = useNavigate()

  const [sub, setSub]       = useState(null)
  const [tools, setTools]   = useState([])
  const [scans, setScans]   = useState([])
  const [loading, setLoading] = useState({ sub: true, tools: true, scans: true })
  const [error, setError]   = useState({ sub: null, tools: null, scans: null })

  useEffect(() => {
    apiGetSubscription()
      .then(res => setSub(res.data?.data ?? null))
      .catch(() => setError(e => ({ ...e, sub: 'Could not load subscription.' })))
      .finally(() => setLoading(l => ({ ...l, sub: false })))

    apiGetAccessibleTools()
      .then(res => setTools(res.data?.data ?? []))
      .catch(() => setError(e => ({ ...e, tools: 'Could not load tools.' })))
      .finally(() => setLoading(l => ({ ...l, tools: false })))

    apiGetRecentScans()
      .then(res => setScans(res.data?.data ?? []))
      .catch(() => setError(e => ({ ...e, scans: 'Could not load recent scans.' })))
      .finally(() => setLoading(l => ({ ...l, scans: false })))
  }, [])

  function handleLogout() {
    logout()
    navigate('/')
  }

  const planName   = sub?.plan?.name ?? 'Free'
  const planBadge  = planBadgeStyle(planName)
  const displayName = user?.full_name || user?.username || user?.email || 'Trader'

  return (
    <div style={{ minHeight: '100vh', background: '#050810', color: '#e1e2ee', fontFamily: 'Inter, ui-sans-serif, sans-serif' }}>
      {/* shimmer keyframe */}
      <style>{`
        @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
        .tool-card:hover { transform: translateY(-3px); }
        .tool-card { transition: transform 0.2s ease, box-shadow 0.2s ease; }
        .qa-btn:hover { opacity: 0.85; }
        .qa-btn { transition: opacity 0.18s; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #10131c; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }
      `}</style>

      {/* ── Top nav ─────────────────────────────────────────────────────── */}
      <nav style={{
        position: 'sticky', top: 0, zIndex: 50,
        background: 'rgba(5,8,16,0.85)',
        backdropFilter: 'blur(20px)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        padding: '0 24px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: '60px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '32px', height: '32px', background: '#0066ff',
            borderRadius: '9px', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ color: '#fff', fontSize: '16px' }}>⚡</span>
          </div>
          <span style={{ fontFamily: "'Space Grotesk', ui-sans-serif, sans-serif", fontWeight: 700, fontSize: '13px', letterSpacing: '0.08em', textTransform: 'uppercase', color: '#e1e2ee' }}>
            Stop Hunter Pro
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '6px',
            padding: '3px 10px', borderRadius: '20px',
            background: planBadge.bg, border: `1px solid ${planBadge.border}`,
            fontSize: '11px', fontWeight: 600, color: planBadge.color,
            letterSpacing: '0.06em',
          }}>
            {planName.toUpperCase()}
          </div>
          <button
            onClick={() => navigate('/settings')}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '7px 14px', borderRadius: '8px',
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: '#8c90a1', fontSize: '13px', cursor: 'pointer',
            }}
          >
            ⚙ Settings
          </button>
          <button
            onClick={handleLogout}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '7px 14px', borderRadius: '8px',
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: '#8c90a1', fontSize: '13px', cursor: 'pointer',
            }}
          >
            <IconLogout /> Sign out
          </button>
        </div>
      </nav>

      {/* ── Page body ───────────────────────────────────────────────────── */}
      <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '32px 24px 80px' }}>

        {/* ── 1. Welcome card ─────────────────────────────────────────── */}
        <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ marginBottom: '28px' }}>
          <div style={{
            background: 'linear-gradient(135deg, rgba(0,102,255,0.18) 0%, rgba(0,241,254,0.08) 100%)',
            border: '1px solid rgba(0,102,255,0.22)',
            borderRadius: '16px', padding: '28px 32px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            flexWrap: 'wrap', gap: '16px',
          }}>
            <div>
              <p style={{ margin: '0 0 6px', fontSize: '13px', color: '#8c90a1', letterSpacing: '0.04em' }}>
                {new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })} · NSE/BSE
              </p>
              <h1 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#e1e2ee', letterSpacing: '-0.01em' }}>
                Welcome back, <span style={{ color: '#b3c5ff' }}>{displayName}</span>
              </h1>
              <p style={{ margin: '6px 0 0', fontSize: '14px', color: '#8c90a1' }}>{user?.email}</p>
            </div>
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px',
            }}>
              <div style={{
                fontSize: '11px', fontWeight: 600, letterSpacing: '0.08em',
                color: '#8c90a1', textTransform: 'uppercase',
              }}>Current Plan</div>
              <div style={{
                fontSize: '22px', fontWeight: 700,
                background: 'linear-gradient(90deg,#0066ff,#00f1fe)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              }}>{planName}</div>
            </div>
          </div>
        </motion.div>

        {/* ── 2. Subscription status ──────────────────────────────────── */}
        <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ marginBottom: '28px' }}>
          <SectionLabel>Subscription</SectionLabel>
          <div style={{
            background: '#10131c', border: '1px solid rgba(255,255,255,0.07)',
            borderRadius: '16px', padding: '24px 28px',
          }}>
            {loading.sub ? (
              <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                {[180, 120, 100, 140].map((w, i) => <Skeleton key={i} w={`${w}px`} h="18px" />)}
              </div>
            ) : error.sub ? (
              <ErrorMsg>{error.sub}</ErrorMsg>
            ) : !sub?.has_subscription ? (
              <div style={{ color: '#8c90a1', fontSize: '14px' }}>No active subscription found.</div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '28px', alignItems: 'center' }}>
                <SubStat label="Plan" value={sub.plan?.name ?? '—'} />
                <SubStat label="Billing" value={sub.billing_cycle === 'free' ? 'Free forever' : sub.billing_cycle} />
                <SubStat label="Status">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#e1e2ee', fontSize: '14px', fontWeight: 600 }}>
                    <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: statusDot(sub.status), display: 'inline-block' }} />
                    {sub.status ?? '—'}
                  </span>
                </SubStat>
                {sub.expiry_date && <SubStat label="Expires" value={fmtDate(sub.expiry_date)} />}
                {sub.days_remaining != null && (
                  <SubStat label="Days left" value={sub.days_remaining <= 0 ? 'Expired' : `${sub.days_remaining}d`} />
                )}
                <div style={{ marginLeft: 'auto' }}>
                  <button
                    onClick={() => navigate('/pricing')}
                    style={{
                      padding: '9px 20px', borderRadius: '9px',
                      background: 'linear-gradient(90deg,#0066ff,#0052cc)',
                      border: 'none', color: '#fff', fontSize: '13px',
                      fontWeight: 600, cursor: 'pointer',
                    }}
                  >
                    Upgrade Plan
                  </button>
                </div>
              </div>
            )}
          </div>
        </motion.div>

        {/* ── 3. Tool access cards ────────────────────────────────────── */}
        <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ marginBottom: '28px' }}>
          <SectionLabel>Scanner Tools</SectionLabel>
          {loading.tools ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px,1fr))', gap: '16px' }}>
              {[1,2,3,4,5].map(i => <Skeleton key={i} h="120px" radius="14px" />)}
            </div>
          ) : error.tools ? (
            <ErrorMsg>{error.tools}</ErrorMsg>
          ) : (
            <motion.div
              variants={stagger} initial="hidden" animate="show"
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px,1fr))', gap: '16px' }}
            >
              {tools.map(tool => {
                const colors = TOOL_COLORS[tool.slug] ?? { icon: '#b3c5ff', glow: 'rgba(179,197,255,0.1)' }
                const icon   = TOOL_ICONS[tool.slug] ?? <IconScan />
                const locked = !tool.has_access
                return (
                  <motion.div key={tool.id} variants={fadeUp}>
                    <div
                      className="tool-card"
                      onClick={() => {
                        if (import.meta.env.DEV) {
                          console.log('Launching tool:', tool)
                        }
                        if (locked) {
                          navigate('/pricing')
                        } else if (
                          tool.slug === 'stop-hunter-pro' ||
                          tool.name === 'Stop Hunter Pro'
                        ) {
                          navigate('/scanner/stop-hunter-pro')
                        } else if (
                          tool.slug === 'options-scanner' ||
                          tool.name === 'Options Scanner'
                        ) {
                          navigate('/scanner/max-pain')
                        } else {
                          showToast(`${tool.name} scanner coming soon!`, 'success')
                        }
                      }}
                      style={{
                        background: locked ? '#10131c' : `radial-gradient(circle at top left, ${colors.glow}, #10131c 70%)`,
                        border: `1px solid ${locked ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.1)'}`,
                        borderRadius: '14px', padding: '20px',
                        cursor: 'pointer', position: 'relative', overflow: 'hidden',
                        opacity: locked ? 0.6 : 1,
                      }}
                    >
                      <div style={{
                        width: '40px', height: '40px', borderRadius: '10px',
                        background: locked ? 'rgba(255,255,255,0.05)' : `${colors.glow}`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: locked ? '#8c90a1' : colors.icon, marginBottom: '14px',
                        border: `1px solid ${locked ? 'rgba(255,255,255,0.08)' : `${colors.icon}30`}`,
                      }}>
                        {icon}
                      </div>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: locked ? '#8c90a1' : '#e1e2ee', marginBottom: '4px', lineHeight: 1.3 }}>
                        {tool.name}
                      </div>
                      <div style={{ fontSize: '11px', color: '#8c90a1', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        {locked ? <><IconLock /> Locked</> : <span style={{ color: colors.icon }}>● Available</span>}
                      </div>
                      {!locked && (
                        <div style={{
                          position: 'absolute', bottom: '12px', right: '14px',
                          fontSize: '10px', fontWeight: 700, letterSpacing: '0.06em',
                          color: colors.icon, textTransform: 'uppercase',
                        }}>
                          Launch →
                        </div>
                      )}
                    </div>
                  </motion.div>
                )
              })}
            </motion.div>
          )}
        </motion.div>

        {/* ── 4. Recent scans table ───────────────────────────────────── */}
        <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ marginBottom: '28px' }}>
          <SectionLabel>Recent Scans</SectionLabel>
          <div style={{
            background: '#10131c', border: '1px solid rgba(255,255,255,0.07)',
            borderRadius: '16px', overflow: 'hidden',
          }}>
            {loading.scans ? (
              <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {[1,2,3].map(i => <Skeleton key={i} h="20px" />)}
              </div>
            ) : error.scans ? (
              <div style={{ padding: '24px' }}><ErrorMsg>{error.scans}</ErrorMsg></div>
            ) : scans.length === 0 ? (
              <div style={{ padding: '40px', textAlign: 'center' }}>
                <div style={{ fontSize: '32px', marginBottom: '12px' }}>📊</div>
                <div style={{ fontSize: '15px', fontWeight: 600, color: '#e1e2ee', marginBottom: '6px' }}>No scans yet</div>
                <div style={{ fontSize: '13px', color: '#8c90a1' }}>Run a scanner tool above to see results here.</div>
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                      {['Scanner', 'Universe', 'Timeframe', 'Symbols', 'Status', 'Run at'].map(h => (
                        <th key={h} style={{
                          padding: '12px 16px', textAlign: 'left',
                          fontSize: '11px', fontWeight: 600, letterSpacing: '0.06em',
                          color: '#8c90a1', textTransform: 'uppercase',
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {scans.map((job, idx) => (
                      <tr key={job.id} style={{
                        borderBottom: idx < scans.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                      }}>
                        <td style={{ padding: '14px 16px', fontSize: '13px', color: '#e1e2ee', fontWeight: 500 }}>
                          {job.scanner_slug ?? job.id}
                        </td>
                        <td style={{ padding: '14px 16px', fontSize: '13px', color: '#8c90a1' }}>
                          {job.universe ?? '—'}
                        </td>
                        <td style={{ padding: '14px 16px', fontSize: '13px', color: '#8c90a1' }}>
                          {job.timeframe ?? '—'}
                        </td>
                        <td style={{ padding: '14px 16px', fontSize: '13px', color: '#8c90a1' }}>
                          {job.completed_symbols != null && job.total_symbols != null
                            ? `${job.completed_symbols}/${job.total_symbols}`
                            : '—'}
                        </td>
                        <td style={{ padding: '14px 16px' }}>
                          <span style={{
                            display: 'inline-flex', alignItems: 'center', gap: '5px',
                            fontSize: '12px', fontWeight: 600,
                            color: jobStatusColor(job.status),
                          }}>
                            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: jobStatusColor(job.status), display: 'inline-block' }} />
                            {job.status}
                          </span>
                        </td>
                        <td style={{ padding: '14px 16px', fontSize: '12px', color: '#8c90a1', display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <IconClock /> {fmtTime(job.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </motion.div>

        {/* ── 5. Quick actions ────────────────────────────────────────── */}
        <motion.div variants={fadeUp} initial="hidden" animate="show">
          <SectionLabel>Quick Actions</SectionLabel>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
            <QuickAction
              icon={<IconPricing />}
              label="View Pricing"
              color="#0066ff"
              onClick={() => {
                navigate('/')
                setTimeout(() => {
                  const el = document.getElementById('pricing')
                  el?.scrollIntoView({ behavior: 'smooth' })
                }, 300)
              }}
            />
            <QuickAction
              icon={<IconScan />}
              label="Start a Scan"
              color="#00f1fe"
              onClick={() => navigate('/scanner/stop-hunter-pro')}
            />
            <QuickAction
              icon={<IconTrend />}
              label="Manage Subscription"
              color="#00d97e"
              onClick={() => navigate('/pricing')}
            />
          </div>
        </motion.div>

      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: '11px', fontWeight: 700, letterSpacing: '0.1em',
      textTransform: 'uppercase', color: '#8c90a1', marginBottom: '12px',
    }}>
      {children}
    </div>
  )
}

function SubStat({ label, value, children }) {
  return (
    <div>
      <div style={{ fontSize: '11px', color: '#8c90a1', letterSpacing: '0.05em', marginBottom: '4px', textTransform: 'uppercase' }}>{label}</div>
      {children ?? <div style={{ fontSize: '14px', fontWeight: 600, color: '#e1e2ee' }}>{value}</div>}
    </div>
  )
}

function ErrorMsg({ children }) {
  return (
    <div style={{
      color: '#ff4d4f', fontSize: '13px', padding: '10px 14px',
      background: 'rgba(255,77,79,0.08)', borderRadius: '8px',
      border: '1px solid rgba(255,77,79,0.2)',
    }}>
      {children}
    </div>
  )
}

function QuickAction({ icon, label, color, onClick }) {
  return (
    <button
      className="qa-btn"
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        padding: '11px 20px', borderRadius: '10px',
        background: `${color}18`,
        border: `1px solid ${color}35`,
        color: color, fontSize: '13px', fontWeight: 600,
        cursor: 'pointer',
      }}
    >
      {icon} {label}
    </button>
  )
}
