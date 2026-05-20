import { motion } from 'framer-motion'
import { SectionLabel } from '../ui/SectionLabel'
import { FeatureCard } from './FeatureCard'
import { FEATURES } from '../../data/landingData'
import { useReducedMotion } from '../../hooks/useReducedMotion'

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12 } },
}

const cardVariants = {
  hidden:  { opacity: 0, y: 32 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] } },
}

export function PlatformOverview() {
  const reduced = useReducedMotion()

  return (
    <section id="features" className="relative py-24 px-6 overflow-hidden">
      {/* Subtle background accent */}
      <div
        className="absolute left-1/4 top-1/2 -translate-y-1/2 w-[500px] h-[400px] rounded-full opacity-[0.05] pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse, #b3c5ff 0%, transparent 70%)',
          filter: 'blur(80px)',
        }}
      />

      <div className="relative z-10 max-w-6xl mx-auto">
        {/* Section header */}
        <motion.div
          className="text-center mb-14"
          initial={reduced ? {} : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        >
          <SectionLabel className="mb-3 block">Platform Overview</SectionLabel>
          <h2 className="text-[32px] sm:text-headline-md md:text-[36px] font-bold text-on-surface leading-tight mb-4">
            Master Every Liquidity Concept
          </h2>
          <p className="text-body-main text-on-surface-variant max-w-xl mx-auto">
            Our proprietary engine scans every symbol in your chosen universe and provides
            actionable setups in real-time.
          </p>
        </motion.div>

        {/* 2 × 2 feature grid */}
        <motion.div
          className="grid grid-cols-1 sm:grid-cols-2 gap-4"
          variants={reduced ? {} : containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
        >
          {/* Row 1: SMC (tall) + Liquidity Sweeps */}
          <motion.div variants={reduced ? {} : cardVariants} className="sm:row-span-1">
            <FeatureCard feature={FEATURES[0]} className="min-h-[220px]" />
          </motion.div>

          <motion.div variants={reduced ? {} : cardVariants}>
            <FeatureCard feature={FEATURES[1]} className="min-h-[220px]" />
          </motion.div>

          {/* Row 2: FVG + Grade card */}
          <motion.div variants={reduced ? {} : cardVariants}>
            <FeatureCard feature={FEATURES[2]} className="min-h-[200px]" />
          </motion.div>

          <motion.div variants={reduced ? {} : cardVariants}>
            <FeatureCard feature={FEATURES[3]} className="min-h-[200px]" />
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}
