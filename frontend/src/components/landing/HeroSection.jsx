import { motion } from 'framer-motion'
import { ArrowRight, PlayCircle } from 'lucide-react'
import { Button } from '../ui/Button'
import { PulseIndicator } from '../ui/PulseIndicator'
import { ScannerPreviewWidget } from './ScannerPreviewWidget'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { useNavigate } from 'react-router-dom'
import { useShowToast } from '../../context/ToastContext'
import { scrollToSection } from '../../utils/scrollTo'

const HEADLINE_WORDS = ['Spot', 'Smart', 'Money', 'Setups', 'Before', 'the', 'Crowd']
// Words to highlight with gradient
const HIGHLIGHT = new Set(['Smart', 'Money'])

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.065, delayChildren: 0.25 } },
}

const wordVariants = {
  hidden:   { opacity: 0, y: 22, filter: 'blur(4px)' },
  visible:  { opacity: 1, y: 0,  filter: 'blur(0px)', transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] } },
}

const fadeUp = (delay = 0) => ({
  initial:   { opacity: 0, y: 18 },
  animate:   { opacity: 1, y: 0 },
  transition: { duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] },
})

export function HeroSection() {
  const reduced   = useReducedMotion()
  const showToast = useShowToast()
  const navigate  = useNavigate()

  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden px-6 pt-24 pb-20">

      {/* ── Background radial glows ────────────────────────────────────────── */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
        {/* Primary electric-blue glow centered at top */}
        <div
          className="absolute -top-32 left-1/2 -translate-x-1/2 w-[720px] h-[480px] rounded-full opacity-[0.18]"
          style={{ background: 'radial-gradient(ellipse, #0066ff 0%, transparent 70%)', filter: 'blur(60px)' }}
        />
        {/* Cyan accent glow slightly offset */}
        <div
          className="absolute top-10 left-1/2 -translate-x-1/2 translate-x-24 w-[320px] h-[240px] rounded-full opacity-[0.10]"
          style={{ background: 'radial-gradient(ellipse, #00f1fe 0%, transparent 70%)', filter: 'blur(48px)' }}
        />
        {/* Subtle grid overlay */}
        <div
          className="absolute inset-0 opacity-[0.025]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(179,197,255,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(179,197,255,0.6) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />
      </div>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <div className="relative z-10 w-full max-w-4xl mx-auto flex flex-col items-center text-center">

        {/* Live badge */}
        <motion.div {...(reduced ? {} : fadeUp(0.1))} className="mb-7">
          <span className="inline-flex items-center gap-2.5 rounded-full border border-primary/25 bg-primary/[0.07] px-4 py-1.5">
            <PulseIndicator color="bullish" size="xs" />
            <span className="font-mono text-label-caps text-primary tracking-[0.1em] uppercase">
              Scanner Live · 1,200+ traders active
            </span>
          </span>
        </motion.div>

        {/* Headline — word-by-word stagger */}
        <motion.h1
          className="text-[36px] sm:text-[48px] md:text-display-xl text-on-surface leading-[1.1] mb-6 max-w-2xl"
          variants={containerVariants}
          initial={reduced ? 'visible' : 'hidden'}
          animate="visible"
        >
          {HEADLINE_WORDS.map((word, i) => (
            <motion.span
              key={`${word}-${i}`}
              variants={reduced ? {} : wordVariants}
              className="inline-block mr-[0.22em]"
            >
              {HIGHLIGHT.has(word) ? (
                <span className="text-gradient-primary">{word}</span>
              ) : (
                word
              )}
            </motion.span>
          ))}
        </motion.h1>

        {/* Subtitle */}
        <motion.p
          className="text-body-main text-on-surface-variant max-w-lg mb-9 leading-relaxed"
          {...(reduced ? {} : fadeUp(0.72))}
        >
          Detect liquidity sweeps, order blocks, and high-probability FVG gaps
          in real-time — without the noise.
        </motion.p>

        {/* CTAs */}
        <motion.div
          className="flex flex-col sm:flex-row items-center gap-3 mb-14"
          {...(reduced ? {} : fadeUp(0.88))}
        >
          <Button size="lg" onClick={() => navigate('/register')}>
            Start Free <ArrowRight size={15} />
          </Button>
          <Button variant="ghost" size="lg" onClick={() => scrollToSection('scanners')}>
            <PlayCircle size={15} />
            View Scanners
          </Button>
        </motion.div>

        {/* Trust strip */}
        <motion.div
          className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 mb-14"
          {...(reduced ? {} : fadeUp(1.0))}
        >
          {[
            '✓ No credit card required',
            '✓ 5 scanners included',
            '✓ Real-time on Pro+',
          ].map((item) => (
            <span key={item} className="font-mono text-[12px] text-outline">
              {item}
            </span>
          ))}
        </motion.div>

        {/* Scanner preview widget */}
        <motion.div
          className="w-full"
          initial={reduced ? { opacity: 1 } : { opacity: 0, y: 48 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.75, delay: reduced ? 0 : 1.05, ease: [0.22, 1, 0.36, 1] }}
        >
          {/* Floating label */}
          <div className="flex items-center justify-between mb-2 px-1">
            <span className="font-mono text-label-caps text-outline uppercase tracking-widest">
              Live Scanner Preview
            </span>
            <span className="font-mono text-[11px] text-outline">
              Stop Hunter Pro · NIFTY50 · 1H
            </span>
          </div>
          <ScannerPreviewWidget />
        </motion.div>
      </div>
    </section>
  )
}
