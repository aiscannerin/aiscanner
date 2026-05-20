import { useState } from 'react'
import { LegalLayout, Section, P } from '../components/legal/LegalLayout'

// ── design tokens ─────────────────────────────────────────────────────────────
const T = {
  surface: '#10131c',
  border:  'rgba(255,255,255,0.07)',
  muted:   '#8c90a1',
  text:    '#e1e2ee',
  primary: '#0066ff',
  green:   '#00d97e',
}

// ── FAQ data ──────────────────────────────────────────────────────────────────
const FAQS = [
  {
    q: 'How do I verify my email after registration?',
    a: 'After registering, a 6-digit OTP is sent to your email. Enter it on the verification screen. If you did not receive it, use the "Resend OTP" button. Check your spam folder if needed.',
  },
  {
    q: 'What does "mock mode" mean in the scanner?',
    a: 'Mock mode generates simulated results for demonstration purposes. The data is randomly generated and has no real market basis. Use it to explore the platform interface. Live mode will use real market data when available.',
  },
  {
    q: 'Why is the Stop Hunter Pro scanner locked?',
    a: 'The scanner is available on Pro and Expert plans. Free plan users can see the scanner but cannot run scans. Upgrade from the Pricing page to unlock access.',
  },
  {
    q: 'How do I upgrade my subscription?',
    a: 'Go to Dashboard → Upgrade Plan, or navigate to /pricing. Select your plan and billing cycle, then complete checkout via Razorpay. Your subscription activates immediately after payment verification.',
  },
  {
    q: 'I made a payment but my plan did not upgrade.',
    a: 'Payment verification happens automatically. If your plan did not update within 5 minutes of payment, please contact us at support@stophunterpro.com with your Razorpay order ID. Do not attempt the payment again without contacting us first.',
  },
  {
    q: 'How do I reset my password?',
    a: 'Go to the Login page and click "Forgot password?". Enter your registered email and we will send you an OTP. Use the OTP to verify your identity, then set a new password.',
  },
  {
    q: 'What is the Risk Disclaimer about?',
    a: 'Stop Hunter Pro is a research tool — it does not provide financial advice or guarantee profits. Trading involves risk of loss. Please read the full Risk Disclaimer before using any scanner output.',
  },
  {
    q: 'How do I delete my account?',
    a: 'Account deletion is not yet available from the self-service Settings page. Please email us at support@stophunterpro.com and we will process your request within 5 business days.',
  },
]

// ── FAQ accordion item ────────────────────────────────────────────────────────
function FaqItem({ q, a }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{
      borderBottom: '1px solid rgba(255,255,255,0.05)',
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', textAlign: 'left', background: 'none', border: 'none',
          padding: '16px 0', cursor: 'pointer',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px',
        }}
      >
        <span style={{ fontSize: '14px', fontWeight: 600, color: T.text, lineHeight: 1.5 }}>{q}</span>
        <span style={{
          flexShrink: 0, width: '22px', height: '22px',
          borderRadius: '6px', background: open ? 'rgba(0,102,255,0.2)' : 'rgba(255,255,255,0.06)',
          border: `1px solid ${open ? 'rgba(0,102,255,0.4)' : 'rgba(255,255,255,0.1)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '14px', color: open ? '#6096ff' : T.muted,
          transition: 'all 0.15s',
        }}>
          {open ? '−' : '+'}
        </span>
      </button>
      {open && (
        <div style={{
          padding: '0 0 16px',
          fontSize: '13px', color: T.muted, lineHeight: 1.75,
        }}>
          {a}
        </div>
      )}
    </div>
  )
}

// ── Contact form ──────────────────────────────────────────────────────────────
const SUBJECTS = [
  'Account / Login issue',
  'Payment / Subscription issue',
  'Scanner not working',
  'Feature request',
  'Report a bug',
  'Data privacy request',
  'Other',
]

function ContactForm() {
  const [form, setForm]       = useState({ name: '', email: '', subject: SUBJECTS[0], message: '' })
  const [submitted, setSubmitted] = useState(false)

  function set(key, val) { setForm(f => ({ ...f, [key]: val })) }

  function handleSubmit(e) {
    e.preventDefault()
    // UI-only — no backend yet
    setSubmitted(true)
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box',
    background: '#0d1020', border: `1px solid ${T.border}`,
    borderRadius: '10px', color: T.text,
    fontSize: '14px', padding: '11px 14px', outline: 'none',
    fontFamily: 'Inter, ui-sans-serif, sans-serif',
  }

  const labelStyle = {
    display: 'block', fontSize: '11px', fontWeight: 600,
    letterSpacing: '0.06em', textTransform: 'uppercase',
    color: T.muted, marginBottom: '8px',
  }

  if (submitted) {
    return (
      <div style={{
        background: 'rgba(0,217,126,0.07)', border: '1px solid rgba(0,217,126,0.2)',
        borderRadius: '14px', padding: '32px', textAlign: 'center',
      }}>
        <div style={{ fontSize: '36px', marginBottom: '12px' }}>✅</div>
        <div style={{ fontSize: '16px', fontWeight: 700, color: T.text, marginBottom: '8px' }}>
          Message received!
        </div>
        <p style={{ fontSize: '13px', color: T.muted, margin: 0, lineHeight: 1.7 }}>
          Thank you for reaching out. We'll get back to you at <strong style={{ color: T.text }}>{form.email}</strong> within
          1–2 business days.
        </p>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
        <div>
          <label style={labelStyle}>Your name</label>
          <input
            type="text" required
            value={form.name} onChange={e => set('name', e.target.value)}
            placeholder="Full name"
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>Email address</label>
          <input
            type="email" required
            value={form.email} onChange={e => set('email', e.target.value)}
            placeholder="you@example.com"
            style={inputStyle}
          />
        </div>
      </div>

      <div>
        <label style={labelStyle}>Subject</label>
        <select
          value={form.subject} onChange={e => set('subject', e.target.value)}
          style={{
            ...inputStyle,
            appearance: 'none', cursor: 'pointer',
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%238c90a1' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14L2.451 5.658C1.885 5.013 2.345 4 3.204 4h9.592a1 1 0 0 1 .753 1.659l-4.796 5.48a1 1 0 0 1-1.506 0z'/%3E%3C/svg%3E")`,
            backgroundRepeat: 'no-repeat', backgroundPosition: 'right 14px center',
            paddingRight: '36px',
          }}
        >
          {SUBJECTS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <div>
        <label style={labelStyle}>Message</label>
        <textarea
          required rows={5}
          value={form.message} onChange={e => set('message', e.target.value)}
          placeholder="Describe your issue or question in detail..."
          style={{ ...inputStyle, resize: 'vertical', minHeight: '120px' }}
        />
      </div>

      <button
        type="submit"
        style={{
          padding: '12px 28px', borderRadius: '10px', alignSelf: 'flex-start',
          background: `linear-gradient(135deg,${T.primary},#0052cc)`,
          border: 'none', color: '#fff',
          fontSize: '14px', fontWeight: 700, cursor: 'pointer',
          boxShadow: '0 0 20px rgba(0,102,255,0.28)',
        }}
      >
        Send Message →
      </button>

      <p style={{ fontSize: '11px', color: T.muted, margin: 0 }}>
        ⓘ Contact form is currently UI-only. For urgent issues email us directly at{' '}
        <a href="mailto:support@stophunterpro.com" style={{ color: '#b3c5ff', textDecoration: 'none' }}>
          support@stophunterpro.com
        </a>.
      </p>
    </form>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SupportPage() {
  return (
    <LegalLayout
      title="Support &amp; Help"
      subtitle="Find answers to common questions or reach out to our team."
      accent="#00d97e"
    >

      {/* ── Contact channels ──────────────────────────────────────── */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px,1fr))',
        gap: '16px', marginBottom: '40px',
      }}>
        {[
          { icon: '✉', label: 'Email Support', value: 'support@stophunterpro.com', href: 'mailto:support@stophunterpro.com', note: 'Response within 1–2 business days' },
          { icon: '🔒', label: 'Privacy Enquiries', value: 'privacy@stophunterpro.com', href: 'mailto:privacy@stophunterpro.com', note: 'Data protection & account deletion' },
          { icon: '💳', label: 'Payment Issues', value: 'billing@stophunterpro.com', href: 'mailto:billing@stophunterpro.com', note: 'Subscription & refund queries' },
        ].map(c => (
          <a key={c.label} href={c.href} style={{ textDecoration: 'none' }}>
            <div style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: '14px', padding: '20px',
              transition: 'border-color 0.15s',
            }}>
              <div style={{ fontSize: '24px', marginBottom: '10px' }}>{c.icon}</div>
              <div style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: T.muted, marginBottom: '5px' }}>
                {c.label}
              </div>
              <div style={{ fontSize: '13px', color: '#b3c5ff', fontWeight: 500, wordBreak: 'break-all', marginBottom: '4px' }}>
                {c.value}
              </div>
              <div style={{ fontSize: '11px', color: T.muted }}>{c.note}</div>
            </div>
          </a>
        ))}
      </div>

      {/* ── FAQ ───────────────────────────────────────────────────── */}
      <Section title="Frequently Asked Questions">
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: '14px', padding: '8px 24px' }}>
          {FAQS.map(faq => (
            <FaqItem key={faq.q} q={faq.q} a={faq.a} />
          ))}
        </div>
      </Section>

      {/* ── Contact form ──────────────────────────────────────────── */}
      <Section title="Send Us a Message">
        <P>
          Can't find what you're looking for? Fill in the form below and we'll get back
          to you as soon as possible.
        </P>
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: '14px', padding: '28px' }}>
          <ContactForm />
        </div>
      </Section>

      {/* ── Response time note ────────────────────────────────────── */}
      <div style={{
        background: 'rgba(0,217,126,0.06)', border: '1px solid rgba(0,217,126,0.18)',
        borderRadius: '12px', padding: '16px 20px',
      }}>
        <p style={{ margin: 0, fontSize: '13px', color: '#8c90a1', lineHeight: 1.7 }}>
          <strong style={{ color: '#00d97e' }}>Support hours:</strong> Monday – Friday, 9 AM – 6 PM IST.
          We aim to respond to all enquiries within 1–2 business days. For urgent issues, email us directly.
        </p>
      </div>

    </LegalLayout>
  )
}
