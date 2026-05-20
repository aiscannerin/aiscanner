import { motion } from 'framer-motion'
import {
  Target, Activity, Filter, BarChart2,
  TrendingUp, Cpu, Lock, ArrowRight,
} from 'lucide-react'
import { GlassCard } from '../ui/GlassCard'
import { PulseIndicator } from '../ui/PulseIndicator'
import { Button } from '../ui/Button'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { cn } from '../../utils/cn'

const ICONS = {
  target:   Target,
  activity: Activity,
  filter:   Filter,
  barchart: BarChart2,
  trending: TrendingUp,
  cpu:      Cpu,
}

const PLAN_STYLES = {
  Pro:    { text: 'text-primary',            bg: 'bg-primary/10',            border: 'border-primary/25' },
  Expert: { text: 'text-secondary-container', bg: 'bg-secondary-container/10', border: 'border-secondary-container/25' },
}

export function ToolCard({ tool, onLearnMore }) {
  const reduced = useReducedMotion()
  const Icon = ICONS[tool.icon] ?? Target
  const isLocked = tool.status === 'coming_soon'
  const plan = PLAN_STYLES[tool.plan] ?? PLAN_STYLES.Pro

  return (
    <motion.div
      whileHover={reduced ? {} : { y: -3 }}
      transition={{ type: 'spring', stiffness: 320, damping: 26 }}
      className="relative h-full"
    >
      <GlassCard
        className={cn(
          'relative flex flex-col h-full p-5 overflow-hidden transition-all duration-300',
          'hover:border-[rgba(255,255,255,0.13)]',
          isLocked && 'cursor-default',
        )}
      >
        {/* Accent top-edge glow */}
        <div
          className="absolute top-0 left-0 right-0 h-[2px] rounded-t-lg opacity-60"
          style={{ background: `linear-gradient(90deg, transparent, ${tool.accentColor}, transparent)` }}
        />

        {/* Header row: icon + status */}
        <div className="flex items-start justify-between mb-4">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{
              backgroundColor: tool.accentBg,
              border: `1px solid ${tool.accentColor}22`,
            }}
          >
            <Icon size={18} style={{ color: tool.accentColor }} strokeWidth={1.6} />
          </div>

          {/* Status badge */}
          {isLocked ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-mono text-[10px] font-semibold text-amber border border-amber/30 bg-amber/10">
              <Lock size={9} /> Coming Soon
            </span>
          ) : (
            <PulseIndicator color="bullish" size="xs" label="Live" />
          )}
        </div>

        {/* Tool name */}
        <h3 className="text-headline-sm text-on-surface mb-1.5">{tool.name}</h3>

        {/* Plan badge */}
        <span
          className={cn(
            'self-start inline-flex items-center px-2 py-0.5 rounded font-mono text-[10px] font-bold mb-3',
            'border',
            plan.text, plan.bg, plan.border,
          )}
        >
          {tool.plan} Plan
        </span>

        {/* Description */}
        <p className="text-body-sm text-on-surface-variant leading-relaxed mb-4 flex-1">
          {tool.description}
        </p>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 mb-4">
          {tool.tags.map((tag) => (
            <span
              key={tag}
              className="font-mono text-[10px] px-2 py-0.5 rounded-full text-outline border border-outline-variant/50"
            >
              {tag}
            </span>
          ))}
        </div>

        {/* CTA */}
        {isLocked ? (
          <button
            disabled
            className="mt-auto w-full py-2 rounded font-mono text-[12px] text-outline border border-outline-variant/40 bg-transparent cursor-not-allowed opacity-50"
          >
            Notify Me When Live
          </button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="mt-auto w-full justify-center group"
            onClick={() => onLearnMore?.(tool)}
          >
            Learn More
            <ArrowRight
              size={13}
              className="transition-transform duration-200 group-hover:translate-x-0.5"
            />
          </Button>
        )}

        {/* Coming-soon frosted overlay */}
        {isLocked && (
          <div
            className="absolute inset-0 rounded-lg flex flex-col items-center justify-center gap-3 pointer-events-none"
            style={{
              backdropFilter: 'blur(2px)',
              background: 'rgba(5,8,16,0.15)',
            }}
          />
        )}
      </GlassCard>
    </motion.div>
  )
}
