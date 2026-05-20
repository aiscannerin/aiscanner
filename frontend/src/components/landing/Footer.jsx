import { motion } from 'framer-motion'
import { Zap } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useShowToast } from '../../context/ToastContext'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { scrollToSection } from '../../utils/scrollTo'

const FOOTER_LINKS = {
  Product: [
    { label: 'Features',     action: 'scroll', target: 'features' },
    { label: 'Scanners',     action: 'scroll', target: 'scanners' },
    { label: 'Pricing',      action: 'scroll', target: 'pricing' },
    { label: 'How It Works', action: 'scroll', target: 'how-it-works' },
  ],
  Scanners: [
    { label: 'Stop Hunter Pro',        action: 'toast', message: 'Scanner page coming next!' },
    { label: 'SMC Liquidity Scanner',  action: 'toast', message: 'Scanner page coming next!' },
    { label: 'Master Screener',        action: 'toast', message: 'Scanner page coming next!' },
    { label: 'Volume Profile Scanner', action: 'toast', message: 'Scanner page coming next!' },
    { label: 'Options Scanner',        action: 'toast', message: 'Scanner page coming next!' },
  ],
  Account: [
    { label: 'Login',    action: 'navigate', target: '/login'    },
    { label: 'Sign Up',  action: 'navigate', target: '/register' },
    { label: 'Support',  action: 'navigate', target: '/support'  },
  ],
  Legal: [
    { label: 'Terms of Service', action: 'navigate', target: '/terms'            },
    { label: 'Privacy Policy',   action: 'navigate', target: '/privacy'          },
    { label: 'Risk Disclaimer',  action: 'navigate', target: '/risk-disclaimer'  },
  ],
}

export function Footer() {
  const showToast = useShowToast()
  const reduced   = useReducedMotion()
  const navigate  = useNavigate()

  function handleLink(link) {
    if (link.action === 'scroll')    scrollToSection(link.target)
    else if (link.action === 'navigate') navigate(link.target)
    else showToast(link.message, 'info')
  }

  return (
    <footer className="relative border-t border-outline-variant/25">
      {/* Subtle top separator glow */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-px pointer-events-none"
        style={{ background: 'linear-gradient(90deg, transparent, rgba(179,197,255,0.2), transparent)' }}
      />

      <div className="max-w-6xl mx-auto px-6 pt-14 pb-8">
        {/* Main grid */}
        <motion.div
          className="grid grid-cols-2 sm:grid-cols-4 gap-8 mb-12"
          initial={reduced ? {} : { opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-40px' }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        >
          {Object.entries(FOOTER_LINKS).map(([section, links]) => (
            <div key={section}>
              <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-outline mb-4">{section}</p>
              <ul className="flex flex-col gap-2.5">
                {links.map((link) => (
                  <li key={link.label}>
                    <button
                      onClick={() => handleLink(link)}
                      className="text-body-sm text-on-surface-variant hover:text-on-surface transition-colors duration-200 bg-transparent border-0 p-0 cursor-pointer text-left"
                    >
                      {link.label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </motion.div>

        {/* Risk disclaimer */}
        <div
          id="risk-disclaimer"
          className="rounded-lg px-5 py-4 mb-10"
          style={{
            background: 'rgba(245,158,11,0.06)',
            border: '1px solid rgba(245,158,11,0.18)',
          }}
        >
          <p className="font-mono text-[10px] uppercase tracking-widest text-amber mb-1.5">Risk Disclaimer</p>
          <p className="text-body-sm text-on-surface-variant leading-relaxed">
            Stop Hunter Pro is a market research and scanning platform. All tools, scanners, scores,
            grades, and outputs are for educational and research purposes only. Nothing on this
            platform constitutes financial advice, investment advice, or a recommendation to buy or
            sell any security. No scanner output guarantees a profitable trade. Past performance and
            mock results do not guarantee future results. Trading involves substantial risk of loss,
            including loss of capital. Always conduct your own analysis and consult a qualified
            SEBI-registered adviser before making any trading or investment decisions.{' '}
            <a href="/risk-disclaimer" className="text-amber underline-offset-2 hover:underline">
              Full disclaimer →
            </a>
          </p>
        </div>

        {/* Bottom bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 border-t border-outline-variant/20">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-primary-container flex items-center justify-center">
              <Zap size={11} className="text-white" fill="white" />
            </div>
            <span className="font-mono text-[12px] font-bold text-on-surface tracking-wider uppercase">
              Stop Hunter Pro
            </span>
          </div>

          <p className="font-mono text-[11px] text-outline text-center sm:text-right">
            © {new Date().getFullYear()} Stop Hunter Pro · Built for Indian markets · NSE / BSE
          </p>
        </div>
      </div>
    </footer>
  )
}
