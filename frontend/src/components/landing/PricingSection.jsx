import { useState } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle2, Lock, Zap } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { SectionLabel } from '../ui/SectionLabel'
import { Button } from '../ui/Button'
import { GlassCard } from '../ui/GlassCard'
import { useShowToast } from '../../context/ToastContext'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { PRICING_PLANS } from '../../data/landingData'
import { cn } from '../../utils/cn'

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 24 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: '-60px' },
  transition: { duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] },
})

function PriceDisplay({ plan, yearly }) {
  const price = yearly ? plan.yearlyPrice : plan.monthlyPrice
  if (price === 0) {
    return (
      <div className="flex items-end gap-1 mb-1">
        <span className="text-[36px] font-bold text-on-surface leading-none">₹0</span>
        <span className="text-body-sm text-outline mb-1">/mo</span>
      </div>
    )
  }
  return (
    <div className="flex items-end gap-1 mb-1">
      <span className="text-[36px] font-bold text-on-surface leading-none">
        ₹{price.toLocaleString('en-IN')}
      </span>
      <span className="text-body-sm text-outline mb-1">/mo</span>
    </div>
  )
}

function ToolRow({ tool }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-outline-variant/20 last:border-0">
      <span className={cn('text-body-sm', tool.included ? 'text-on-surface-variant' : 'text-outline line-through')}>
        {tool.name}
      </span>
      {tool.included ? (
        <CheckCircle2 size={14} className="text-bullish flex-shrink-0" />
      ) : (
        <Lock size={12} className="text-outline flex-shrink-0" />
      )}
    </div>
  )
}

function PricingCard({ plan, yearly, index }) {
  const showToast = useShowToast()
  const navigate  = useNavigate()
  const reduced   = useReducedMotion()

  function handleCTA() {
    if (plan.id === 'free') {
      navigate('/register')
    } else {
      showToast('Payment flow UI coming next — we\'ll notify you!', 'warning')
    }
  }

  return (
    <motion.div
      initial={reduced ? {} : { opacity: 0, y: 32, scale: 0.97 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.55, delay: index * 0.1, ease: [0.22, 1, 0.36, 1] }}
      className="relative h-full"
    >
      {plan.highlighted && (
        <div
          className="absolute -inset-px rounded-xl pointer-events-none"
          style={{
            background: `linear-gradient(135deg, ${plan.accentColor}40, transparent 60%, ${plan.accentColor}20)`,
            zIndex: 0,
          }}
        />
      )}

      <div
        className={cn(
          'relative z-10 flex flex-col h-full rounded-xl p-6 overflow-hidden',
          plan.highlighted
            ? 'border border-[rgba(0,102,255,0.5)]'
            : 'border border-outline-variant/30',
        )}
        style={{ background: plan.highlighted ? 'rgba(0,20,60,0.85)' : 'rgba(13,17,30,0.80)', backdropFilter: 'blur(24px)' }}
      >
        {/* Accent top line */}
        <div
          className="absolute top-0 left-0 right-0 h-[2px] rounded-t-xl"
          style={{ background: `linear-gradient(90deg, transparent, ${plan.accentColor}, transparent)` }}
        />

        {/* Recommended badge */}
        {plan.highlighted && (
          <div className="flex justify-end mb-3">
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-mono text-[10px] font-bold"
              style={{ background: `${plan.accentColor}20`, color: plan.accentColor, border: `1px solid ${plan.accentColor}40` }}
            >
              <Zap size={9} fill="currentColor" /> Recommended
            </span>
          </div>
        )}

        {/* Plan name + tagline */}
        <p
          className="font-mono text-label-caps tracking-widest uppercase mb-1"
          style={{ color: plan.accentColor }}
        >
          {plan.name}
        </p>
        <p className="text-body-sm text-outline mb-4">{plan.tagline}</p>

        {/* Price */}
        <PriceDisplay plan={plan} yearly={yearly} />
        {plan.monthlyPrice > 0 && yearly && (
          <p className="font-mono text-[11px] text-outline mb-4">
            Billed ₹{(plan.yearlyPrice * 12).toLocaleString('en-IN')}/year · Save{' '}
            {Math.round((1 - plan.yearlyPrice / plan.monthlyPrice) * 100)}%
          </p>
        )}
        {plan.monthlyPrice === 0 && <p className="font-mono text-[11px] text-outline mb-4">Forever free</p>}
        {plan.monthlyPrice > 0 && !yearly && <p className="font-mono text-[11px] text-outline mb-4">Billed monthly</p>}

        {/* CTA */}
        <Button
          variant={plan.highlighted ? 'primary' : 'outline'}
          className="w-full justify-center mb-6"
          style={plan.highlighted ? {} : { borderColor: `${plan.accentColor}50`, color: plan.accentColor }}
          onClick={handleCTA}
        >
          {plan.cta}
        </Button>

        {/* Scanner access */}
        <p className="font-mono text-[10px] tracking-widest uppercase text-outline mb-2">Scanner Access</p>
        <div className="mb-5">
          {plan.tools.map((t) => <ToolRow key={t.name} tool={t} />)}
        </div>

        {/* Feature list */}
        <p className="font-mono text-[10px] tracking-widest uppercase text-outline mb-2">Includes</p>
        <ul className="flex flex-col gap-2 mt-auto">
          {plan.features.map((f) => (
            <li key={f} className="flex items-start gap-2">
              <CheckCircle2 size={12} className="flex-shrink-0 mt-0.5" style={{ color: plan.accentColor }} />
              <span className="text-body-sm text-on-surface-variant">{f}</span>
            </li>
          ))}
        </ul>
      </div>
    </motion.div>
  )
}

export function PricingSection() {
  const [yearly, setYearly] = useState(false)
  const reduced = useReducedMotion()

  return (
    <section id="pricing" className="relative py-24 px-6 overflow-hidden">
      {/* Background glow */}
      <div
        className="absolute left-1/2 top-0 -translate-x-1/2 w-[600px] h-[300px] rounded-full opacity-[0.07] pointer-events-none"
        style={{ background: 'radial-gradient(ellipse, #0066ff 0%, transparent 70%)', filter: 'blur(80px)' }}
      />

      <div className="relative z-10 max-w-6xl mx-auto">
        {/* Header */}
        <motion.div
          className="text-center mb-12"
          {...(reduced ? {} : fadeUp(0))}
        >
          <SectionLabel className="mb-3 block">Pricing</SectionLabel>
          <h2 className="text-[32px] sm:text-[40px] font-bold text-on-surface leading-tight mb-3">
            Simple, Transparent Pricing
          </h2>
          <p className="text-body-main text-on-surface-variant max-w-md mx-auto">
            Start free. Unlock professional scanners as your edge grows.
          </p>
        </motion.div>

        {/* Monthly / Yearly toggle */}
        <motion.div
          className="flex items-center justify-center gap-4 mb-12"
          {...(reduced ? {} : fadeUp(0.1))}
        >
          <span className={cn('font-mono text-[13px] select-none', !yearly ? 'text-on-surface' : 'text-outline')}>
            Monthly
          </span>

          {/* Track */}
          <button
            role="switch"
            aria-checked={yearly}
            aria-label="Toggle yearly billing"
            onClick={() => setYearly((y) => !y)}
            className="relative flex-shrink-0 rounded-full transition-colors duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
            style={{
              width: '44px',
              height: '24px',
              background: yearly ? 'rgba(0,102,255,0.55)' : 'rgba(255,255,255,0.10)',
              border: '1px solid rgba(255,255,255,0.14)',
            }}
          >
            {/* Knob — anchored to left:0, moves via translateX */}
            <motion.span
              className="block rounded-full bg-white shadow-md"
              style={{
                position: 'absolute',
                top: '2px',
                left: '2px',
                width: '18px',
                height: '18px',
              }}
              animate={{ x: yearly ? 20 : 0 }}
              transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 500, damping: 34 }}
            />
          </button>

          <span className={cn('font-mono text-[13px] select-none flex items-center gap-2', yearly ? 'text-on-surface' : 'text-outline')}>
            Yearly
            <span className="px-1.5 py-0.5 rounded font-mono text-[10px] font-bold bg-bullish/15 text-bullish border border-bullish/30">
              Save 25%
            </span>
          </span>
        </motion.div>

        {/* Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {PRICING_PLANS.map((plan, i) => (
            <PricingCard key={plan.id} plan={plan} yearly={yearly} index={i} />
          ))}
        </div>

        {/* Bottom note */}
        <motion.p
          className="mt-10 text-center font-mono text-[11px] text-outline"
          {...(reduced ? {} : fadeUp(0.3))}
        >
          All plans include 7-day free trial · Cancel anytime · GST applicable for Indian residents
        </motion.p>
      </div>
    </section>
  )
}
