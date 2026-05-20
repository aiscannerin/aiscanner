/**
 * LegalLayout — shared wrapper for /terms, /privacy, /risk-disclaimer, /support
 * Provides sticky mini-nav, branded header, and a consistent page chrome.
 * Keeps each legal page focused purely on content.
 */
import { useNavigate, Link } from 'react-router-dom'
import { Zap } from 'lucide-react'

const LEGAL_LINKS = [
  { label: 'Terms',    path: '/terms'           },
  { label: 'Privacy',  path: '/privacy'         },
  { label: 'Risk',     path: '/risk-disclaimer' },
  { label: 'Support',  path: '/support'         },
]

export function LegalLayout({ children, title, subtitle, lastUpdated, accent = '#b3c5ff' }) {
  const navigate = useNavigate()

  return (
    <div style={{
      minHeight: '100vh',
      background: '#050810',
      color: '#e1e2ee',
      fontFamily: 'Inter, ui-sans-serif, sans-serif',
    }}>

      {/* ── Sticky top bar ───────────────────────────────────────────── */}
      <nav style={{
        position: 'sticky', top: 0, zIndex: 50,
        background: 'rgba(5,8,16,0.9)',
        backdropFilter: 'blur(20px)',
        borderBottom: '1px solid rgba(255,255,255,0.07)',
        padding: '0 24px', height: '56px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        {/* logo */}
        <button
          onClick={() => navigate('/')}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          }}
        >
          <div style={{
            width: '28px', height: '28px', background: '#0066ff',
            borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Zap size={13} color="#fff" fill="#fff" />
          </div>
          <span style={{
            fontFamily: "'Space Grotesk', ui-sans-serif, sans-serif",
            fontSize: '12px', fontWeight: 700, letterSpacing: '0.08em',
            textTransform: 'uppercase', color: '#e1e2ee',
          }}>
            Stop Hunter Pro
          </span>
        </button>

        {/* legal page links */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          {LEGAL_LINKS.map(l => {
            const active = typeof window !== 'undefined' && window.location.pathname === l.path
            return (
              <Link
                key={l.path}
                to={l.path}
                style={{
                  padding: '5px 12px', borderRadius: '7px',
                  fontSize: '12px', fontWeight: 600, textDecoration: 'none',
                  color: active ? '#e1e2ee' : '#8c90a1',
                  background: active ? 'rgba(255,255,255,0.08)' : 'transparent',
                  transition: 'color 0.15s, background 0.15s',
                }}
              >
                {l.label}
              </Link>
            )
          })}
        </div>
      </nav>

      {/* ── Page header ──────────────────────────────────────────────── */}
      <div style={{
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        padding: '48px 24px 40px',
        background: 'radial-gradient(ellipse at 50% 0%, rgba(0,102,255,0.08) 0%, transparent 70%)',
      }}>
        <div style={{ maxWidth: '760px', margin: '0 auto' }}>
          {lastUpdated && (
            <div style={{
              fontSize: '11px', fontWeight: 600, letterSpacing: '0.08em',
              textTransform: 'uppercase', color: '#8c90a1', marginBottom: '12px',
            }}>
              Last updated: {lastUpdated}
            </div>
          )}
          <h1 style={{
            margin: '0 0 10px', fontSize: '32px', fontWeight: 800,
            color: '#e1e2ee', letterSpacing: '-0.02em', lineHeight: 1.2,
          }}>
            <span style={{ color: accent }}>{title.split(' ')[0]}</span>{' '}
            {title.split(' ').slice(1).join(' ')}
          </h1>
          {subtitle && (
            <p style={{ margin: 0, fontSize: '15px', color: '#8c90a1', lineHeight: 1.6 }}>
              {subtitle}
            </p>
          )}
        </div>
      </div>

      {/* ── Content ──────────────────────────────────────────────────── */}
      <main style={{ maxWidth: '760px', margin: '0 auto', padding: '48px 24px 80px' }}>
        {children}
      </main>

      {/* ── Bottom strip ─────────────────────────────────────────────── */}
      <footer style={{
        borderTop: '1px solid rgba(255,255,255,0.06)',
        padding: '24px',
        display: 'flex', flexWrap: 'wrap', gap: '12px',
        alignItems: 'center', justifyContent: 'space-between',
        fontSize: '12px', color: '#8c90a1',
      }}>
        <span>© {new Date().getFullYear()} Stop Hunter Pro · NSE / BSE · India</span>
        <div style={{ display: 'flex', gap: '16px' }}>
          {LEGAL_LINKS.map(l => (
            <Link key={l.path} to={l.path} style={{ color: '#8c90a1', textDecoration: 'none' }}>
              {l.label}
            </Link>
          ))}
        </div>
      </footer>
    </div>
  )
}

// ── Shared prose components ───────────────────────────────────────────────────

export function Section({ title, children }) {
  return (
    <section style={{ marginBottom: '40px' }}>
      <h2 style={{
        fontSize: '16px', fontWeight: 700, color: '#e1e2ee',
        margin: '0 0 14px', paddingBottom: '10px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        {title}
      </h2>
      {children}
    </section>
  )
}

export function P({ children, style }) {
  return (
    <p style={{
      margin: '0 0 12px', fontSize: '14px', color: '#8c90a1',
      lineHeight: 1.8, ...style,
    }}>
      {children}
    </p>
  )
}

export function Ul({ items }) {
  return (
    <ul style={{ margin: '0 0 14px', padding: '0 0 0 18px', display: 'flex', flexDirection: 'column', gap: '7px' }}>
      {items.map((item, i) => (
        <li key={i} style={{ fontSize: '14px', color: '#8c90a1', lineHeight: 1.7 }}>{item}</li>
      ))}
    </ul>
  )
}

export function Highlight({ children, color = 'rgba(245,158,11,0.08)', border = 'rgba(245,158,11,0.2)', textColor = '#f59e0b' }) {
  return (
    <div style={{
      background: color, border: `1px solid ${border}`,
      borderRadius: '12px', padding: '16px 20px', marginBottom: '20px',
    }}>
      <p style={{ margin: 0, fontSize: '13px', color: textColor, lineHeight: 1.75 }}>
        {children}
      </p>
    </div>
  )
}
