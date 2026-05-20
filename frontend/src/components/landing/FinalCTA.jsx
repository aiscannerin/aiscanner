import { motion } from 'framer-motion'
import { ArrowRight, ChevronDown } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../ui/Button'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { scrollToSection } from '../../utils/scrollTo'

export function FinalCTA() {
  const navigate = useNavigate()
  const reduced  = useReducedMotion()

  return (
    <section className="relative py-28 px-6 overflow-hidden">
      {/* Radial glows */}
      <div
        className="absolute inset-0 pointer-events-none"
        aria-hidden
      >
        <div
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[400px] rounded-full opacity-[0.12]"
          style={{ background: 'radial-gradient(ellipse, #0066ff 0%, transparent 70%)', filter: 'blur(80px)' }}
        />
        <div
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 translate-x-32 w-[300px] h-[200px] rounded-full opacity-[0.08]"
          style={{ background: 'radial-gradient(ellipse, #00f1fe 0%, transparent 70%)', filter: 'blur(60px)' }}
        />
      </div>

      <div className="relative z-10 max-w-3xl mx-auto text-center">
        <motion.h2
          className="text-[32px] sm:text-[44px] md:text-[52px] font-bold text-on-surface leading-[1.1] mb-5"
          initial={reduced ? {} : { opacity: 0, y: 28 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-60px' }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          Start Free.{' '}
          <span className="text-gradient-primary">Upgrade When You Need</span>{' '}
          More Firepower.
        </motion.h2>

        <motion.p
          className="text-body-main text-on-surface-variant max-w-md mx-auto mb-10 leading-relaxed"
          initial={reduced ? {} : { opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-60px' }}
          transition={{ duration: 0.55, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}
        >
          No credit card required. Access your first scanner in minutes and discover
          setups the market is hiding in plain sight.
        </motion.p>

        <motion.div
          className="flex flex-col sm:flex-row items-center justify-center gap-4"
          initial={reduced ? {} : { opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-60px' }}
          transition={{ duration: 0.5, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        >
          <Button
            size="lg"
            onClick={() => navigate('/register')}
          >
            Start Free <ArrowRight size={15} />
          </Button>
          <Button
            variant="ghost"
            size="lg"
            onClick={() => scrollToSection('pricing')}
          >
            <ChevronDown size={15} />
            Compare Plans
          </Button>
        </motion.div>

        <motion.p
          className="mt-8 font-mono text-[12px] text-outline"
          initial={reduced ? {} : { opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.35 }}
        >
          ✓ 7-day free trial on Pro · ✓ Cancel anytime · ✓ NSE / BSE · India market hours
        </motion.p>
      </div>
    </section>
  )
}
