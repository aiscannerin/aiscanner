import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { SectionLabel } from '../ui/SectionLabel'
import { ToolCard } from './ToolCard'
import { ToolModal } from '../ui/ToolModal'
import { TOOLS_LIBRARY } from '../../data/landingData'
import { useReducedMotion } from '../../hooks/useReducedMotion'

const FILTERS = [
  { id: 'all',         label: 'All Scanners' },
  { id: 'live',        label: 'Live' },
  { id: 'coming_soon', label: 'Coming Soon' },
]

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.09 } },
}

const cardVariants = {
  hidden:  { opacity: 0, y: 28, scale: 0.97 },
  visible: { opacity: 1, y: 0,  scale: 1, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
}

export function ScannerLibrary() {
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedTool, setSelectedTool] = useState(null)
  const reduced = useReducedMotion()

  const filtered = activeFilter === 'all'
    ? TOOLS_LIBRARY
    : TOOLS_LIBRARY.filter((t) => t.status === activeFilter)

  return (
    <section id="scanners" className="relative py-24 px-6 overflow-hidden">
      {/* Subtle right-side glow */}
      <div
        className="absolute right-0 top-1/3 w-[400px] h-[400px] rounded-full opacity-[0.06] pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse, #00f1fe 0%, transparent 70%)',
          filter: 'blur(80px)',
        }}
      />

      <div className="relative z-10 max-w-6xl mx-auto">
        {/* Section header */}
        <motion.div
          className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-6 mb-10"
          initial={reduced ? {} : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        >
          <div>
            <SectionLabel className="mb-3 block">Scanner Library</SectionLabel>
            <h2 className="text-[32px] sm:text-[36px] font-bold text-on-surface leading-tight mb-2">
              Choose Your Edge
            </h2>
            <p className="text-body-main text-on-surface-variant max-w-md">
              Select from institutional-grade scanners engineered for the Indian market.
            </p>
          </div>

          {/* Filter tabs */}
          <div
            className="inline-flex rounded-lg p-1 flex-shrink-0"
            style={{
              background: 'rgba(10,15,30,0.7)',
              border: '1px solid rgba(255,255,255,0.07)',
            }}
          >
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setActiveFilter(f.id)}
                className="relative px-4 py-1.5 rounded-md font-mono text-[12px] transition-colors duration-150"
              >
                {activeFilter === f.id && (
                  <motion.span
                    layoutId="filter-pill"
                    className="absolute inset-0 rounded-md"
                    style={{ background: 'rgba(179,197,255,0.12)', border: '1px solid rgba(179,197,255,0.2)' }}
                    transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                  />
                )}
                <span
                  className={
                    activeFilter === f.id
                      ? 'relative text-on-surface'
                      : 'relative text-on-surface-variant hover:text-on-surface'
                  }
                >
                  {f.label}
                </span>
              </button>
            ))}
          </div>
        </motion.div>

        {/* Tool cards grid */}
        <AnimatePresence mode="wait">
          <motion.div
            key={activeFilter}
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
            variants={reduced ? {} : containerVariants}
            initial="hidden"
            animate="visible"
            exit={{ opacity: 0, transition: { duration: 0.15 } }}
          >
            {filtered.map((tool) => (
              <motion.div
                key={tool.slug}
                variants={reduced ? {} : cardVariants}
                className="h-full"
              >
                <ToolCard tool={tool} onLearnMore={setSelectedTool} />
              </motion.div>
            ))}
          </motion.div>
        </AnimatePresence>

        {/* Bottom note */}
        <motion.p
          className="mt-8 text-center font-mono text-[12px] text-outline"
          initial={reduced ? {} : { opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.4 }}
        >
          All scanners run on India market hours · NSE / BSE · NIFTY50, NIFTY100, NIFTY500, FNO
        </motion.p>
      </div>

      <ToolModal tool={selectedTool} onClose={() => setSelectedTool(null)} />
    </section>
  )
}
