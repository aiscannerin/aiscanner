import { Globe, Crosshair, ShieldCheck } from 'lucide-react'
import { GlassCard } from '../ui/GlassCard'
import { cn } from '../../utils/cn'

const ICONS = {
  globe:     Globe,
  crosshair: Crosshair,
  shield:    ShieldCheck,
}

export function HowItWorksStep({ step, isLast = false }) {
  const Icon = ICONS[step.icon] ?? Globe

  return (
    <div className="flex flex-col items-center text-center relative">
      {/* Connector line (hidden on last step and mobile) */}
      {!isLast && (
        <div
          className="hidden lg:block absolute top-[28px] left-[calc(50%+44px)] right-[calc(-50%+44px)] h-px"
          style={{
            background:
              'linear-gradient(90deg, rgba(179,197,255,0.3) 0%, rgba(179,197,255,0.08) 100%)',
            backgroundImage:
              'repeating-linear-gradient(90deg, rgba(179,197,255,0.25) 0px, rgba(179,197,255,0.25) 6px, transparent 6px, transparent 14px)',
          }}
        />
      )}

      {/* Step number + icon circle */}
      <div className="relative mb-5 z-10">
        {/* Outer glow ring */}
        <div
          className="absolute inset-0 rounded-full opacity-20 blur-md"
          style={{ background: 'rgba(179,197,255,0.6)', transform: 'scale(1.4)' }}
        />
        {/* Icon circle */}
        <div
          className="relative w-14 h-14 rounded-full flex items-center justify-center"
          style={{
            background: 'rgba(10,15,30,0.9)',
            border: '1px solid rgba(179,197,255,0.25)',
          }}
        >
          <Icon size={22} className="text-primary" strokeWidth={1.6} />
        </div>
        {/* Step number badge */}
        <span
          className="absolute -top-1 -right-1 w-5 h-5 rounded-full flex items-center justify-center font-mono text-[9px] font-bold text-on-primary"
          style={{ background: '#0066ff' }}
        >
          {step.step}
        </span>
      </div>

      {/* Text */}
      <h3 className="text-headline-sm text-on-surface mb-2">{step.title}</h3>
      <p className="text-body-sm text-on-surface-variant leading-relaxed max-w-[220px] mx-auto">
        {step.description}
      </p>
    </div>
  )
}
