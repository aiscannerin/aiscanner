import { motion } from 'framer-motion'
import {
  Brain, Waves, GitBranch, CheckCircle2,
  BarChart2, Star,
} from 'lucide-react'
import { GlassCard } from '../ui/GlassCard'
import { cn } from '../../utils/cn'

// Map string keys from data to lucide icons
const ICONS = {
  brain:  Brain,
  waves:  Waves,
  gap:    GitBranch,
  grade:  Star,
  bar:    BarChart2,
}

// ── Grade display sub-card ────────────────────────────────────────────────────────
function GradeDisplay({ grades }) {
  return (
    <div className="mt-4 flex items-end gap-3">
      {grades.map((g) => (
        <div key={g.label} className="flex flex-col items-center gap-1.5 flex-1">
          {/* Bar */}
          <div className="w-full rounded-sm overflow-hidden bg-white/[0.04]" style={{ height: 48 }}>
            <motion.div
              className="w-full rounded-sm"
              style={{ backgroundColor: g.color, opacity: 0.85 }}
              initial={{ height: 0 }}
              whileInView={{ height: `${(g.score / 100) * 48}px` }}
              viewport={{ once: true }}
              transition={{ duration: 0.8, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>
          {/* Grade letter */}
          <span
            className="w-8 h-8 rounded flex items-center justify-center font-mono text-sm font-bold"
            style={{ backgroundColor: g.bg, color: g.color }}
          >
            {g.label}
          </span>
          {/* Score */}
          <span className="font-mono text-[11px] text-outline tabular-nums">{g.score}</span>
        </div>
      ))}

      {/* Big grade callout */}
      <div className="flex flex-col items-center ml-2">
        <span
          className="font-mono text-[52px] font-bold leading-none"
          style={{
            background: 'linear-gradient(135deg, #b3c5ff 0%, #00f1fe 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          A+
        </span>
        <span className="font-mono text-[11px] text-outline mt-1">Best grade</span>
      </div>
    </div>
  )
}

// ── FeatureCard ───────────────────────────────────────────────────────────────────
export function FeatureCard({ feature, className = '' }) {
  const Icon = ICONS[feature.icon] ?? Brain

  return (
    <GlassCard
      hoverable
      className={cn('p-5 flex flex-col h-full', className)}
    >
      {/* Icon badge */}
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center mb-4 flex-shrink-0"
        style={{ backgroundColor: feature.accentBg, border: `1px solid ${feature.accentColor}22` }}
      >
        <Icon size={17} style={{ color: feature.accentColor }} strokeWidth={1.75} />
      </div>

      {/* Title */}
      <h3 className="text-headline-sm text-on-surface mb-2">{feature.title}</h3>

      {/* Description */}
      <p className="text-body-sm text-on-surface-variant leading-relaxed mb-4">
        {feature.description}
      </p>

      {/* Grade card special rendering */}
      {feature.isGradeCard ? (
        <GradeDisplay grades={feature.grades} />
      ) : (
        <ul className="flex flex-col gap-2 mt-auto">
          {feature.bullets.map((bullet) => (
            <li key={bullet} className="flex items-start gap-2">
              <CheckCircle2
                size={13}
                className="mt-0.5 flex-shrink-0"
                style={{ color: feature.accentColor }}
              />
              <span className="font-mono text-[12px] text-on-surface-variant leading-snug">
                {bullet}
              </span>
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  )
}
