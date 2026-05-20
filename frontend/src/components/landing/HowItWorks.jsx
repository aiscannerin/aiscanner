import { motion } from 'framer-motion'
import { SectionLabel } from '../ui/SectionLabel'
import { HowItWorksStep } from './HowItWorksStep'
import { HOW_IT_WORKS_STEPS } from '../../data/landingData'
import { useReducedMotion } from '../../hooks/useReducedMotion'

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.18 } },
}

const stepVariants = {
  hidden:  { opacity: 0, y: 28 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] } },
}

export function HowItWorks() {
  const reduced = useReducedMotion()

  return (
    <section id="how-it-works" className="relative py-24 px-6 overflow-hidden">
      {/* Background separator line */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-outline-variant/40 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-outline-variant/40 to-transparent" />

      {/* Faint bg glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 60% 50% at 50% 50%, rgba(0,102,255,0.04) 0%, transparent 100%)',
        }}
      />

      <div className="relative z-10 max-w-5xl mx-auto">
        {/* Section header */}
        <motion.div
          className="text-center mb-16"
          initial={reduced ? {} : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        >
          <SectionLabel className="mb-3 block">The Process</SectionLabel>
          <h2 className="text-[32px] sm:text-[36px] font-bold text-on-surface leading-tight mb-4">
            How It Works
          </h2>
          <p className="text-body-main text-on-surface-variant max-w-lg mx-auto">
            From raw candle data to high-probability setups, delivered in milliseconds.
          </p>
        </motion.div>

        {/* Steps row */}
        <motion.div
          className="grid grid-cols-1 sm:grid-cols-3 gap-10 lg:gap-0"
          variants={reduced ? {} : containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
        >
          {HOW_IT_WORKS_STEPS.map((step, i) => (
            <motion.div key={step.step} variants={reduced ? {} : stepVariants}>
              <HowItWorksStep
                step={step}
                isLast={i === HOW_IT_WORKS_STEPS.length - 1}
              />
            </motion.div>
          ))}
        </motion.div>

        {/* Bottom detail strip */}
        <motion.div
          className="mt-16 grid grid-cols-2 sm:grid-cols-4 gap-4"
          initial={reduced ? {} : { opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.55, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
        >
          {[
            { value: '500+',  label: 'Symbols Scanned' },
            { value: '<1s',   label: 'Scan Latency' },
            { value: '5',     label: 'Scanner Types' },
            { value: '4',     label: 'Timeframes' },
          ].map((stat) => (
            <div
              key={stat.label}
              className="glass rounded-lg px-4 py-3 text-center"
            >
              <div className="font-mono text-[22px] font-bold text-gradient-primary leading-none mb-1">
                {stat.value}
              </div>
              <div className="font-mono text-[11px] text-outline uppercase tracking-wider">
                {stat.label}
              </div>
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
