import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { Zap, Menu, X } from 'lucide-react'
import { Button } from '../ui/Button'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { useShowToast } from '../../context/ToastContext'
import { scrollToSection } from '../../utils/scrollTo'

const NAV_LINKS = [
  { label: 'Features',     section: 'features' },
  { label: 'How It Works', section: 'how-it-works' },
  { label: 'Scanners',     section: 'scanners' },
  { label: 'Pricing',      section: 'pricing' },
]

export function Navbar() {
  const [scrolled, setScrolled]     = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const reduced    = useReducedMotion()
  const showToast  = useShowToast()
  const navigate   = useNavigate()

  function handleNavClick(link) {
    if (link.section) scrollToSection(link.section)
    setMobileOpen(false)
  }

  function handleSignIn() {
    setMobileOpen(false)
    navigate('/login')
  }

  function handleGetStarted() {
    setMobileOpen(false)
    navigate('/register')
  }

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 72)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const onResize = () => { if (window.innerWidth >= 768) setMobileOpen(false) }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  return (
    <motion.header
      initial={false}
      animate={scrolled ? 'scrolled' : 'top'}
      variants={{
        top: {
          backgroundColor: 'rgba(5, 8, 16, 0)',
          borderBottomColor: 'rgba(66, 70, 86, 0)',
        },
        scrolled: {
          backgroundColor: 'rgba(8, 12, 24, 0.88)',
          borderBottomColor: 'rgba(66, 70, 86, 0.6)',
        },
      }}
      transition={reduced ? { duration: 0 } : { duration: 0.3, ease: 'easeInOut' }}
      style={{ backdropFilter: scrolled ? 'blur(20px)' : 'blur(0px)' }}
      className="fixed top-0 inset-x-0 z-50 border-b"
    >
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">

        {/* ── Logo ──────────────────────────────────────────────────────────── */}
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-2.5 group bg-transparent border-0 p-0 cursor-pointer"
        >
          <div className="w-7 h-7 rounded bg-primary-container flex items-center justify-center shadow-glow-btn group-hover:shadow-[0_0_16px_rgba(0,102,255,0.7)] transition-shadow duration-300">
            <Zap size={14} className="text-white" fill="white" />
          </div>
          <span className="font-mono text-[13px] font-bold text-on-surface tracking-[0.08em] uppercase hidden sm:block">
            Stop Hunter Pro
          </span>
        </button>

        {/* ── Desktop nav ───────────────────────────────────────────────────── */}
        <nav className="hidden md:flex items-center gap-7">
          {NAV_LINKS.map((link) => (
            <button
              key={link.label}
              onClick={() => handleNavClick(link)}
              className="text-body-sm text-on-surface-variant hover:text-on-surface transition-colors duration-200 relative group bg-transparent border-0 p-0 cursor-pointer"
            >
              {link.label}
              <span className="absolute -bottom-0.5 left-0 w-0 h-px bg-primary group-hover:w-full transition-all duration-300" />
            </button>
          ))}
        </nav>

        {/* ── Desktop CTA ───────────────────────────────────────────────────── */}
        <div className="hidden md:flex items-center gap-3">
          <button
            onClick={handleSignIn}
            className="text-body-sm text-on-surface-variant hover:text-on-surface transition-colors duration-200 bg-transparent border-0 p-0 cursor-pointer"
          >
            Sign In
          </button>
          <Button size="sm" onClick={handleGetStarted}>Get Started</Button>
        </div>

        {/* ── Mobile hamburger ──────────────────────────────────────────────── */}
        <button
          className="md:hidden p-1.5 text-on-surface-variant hover:text-on-surface transition-colors"
          onClick={() => setMobileOpen((o) => !o)}
          aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={mobileOpen}
        >
          <AnimatePresence mode="wait" initial={false}>
            {mobileOpen ? (
              <motion.span key="close"
                initial={{ rotate: -90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: 90, opacity: 0 }}
                transition={{ duration: 0.18 }}
              >
                <X size={20} />
              </motion.span>
            ) : (
              <motion.span key="open"
                initial={{ rotate: 90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: -90, opacity: 0 }}
                transition={{ duration: 0.18 }}
              >
                <Menu size={20} />
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      </div>

      {/* ── Mobile drawer ─────────────────────────────────────────────────── */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            key="mobile-menu"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.25, ease: 'easeInOut' }}
            className="md:hidden overflow-hidden border-t border-outline-variant/40"
            style={{ backgroundColor: 'rgba(8, 12, 24, 0.96)', backdropFilter: 'blur(20px)' }}
          >
            <nav className="flex flex-col px-6 py-5 gap-1">
              {NAV_LINKS.map((link) => (
                <button
                  key={link.label}
                  onClick={() => handleNavClick(link)}
                  className="py-3 text-left text-on-surface-variant hover:text-on-surface border-b border-outline-variant/20 last:border-0 transition-colors bg-transparent border-x-0 border-t-0 w-full cursor-pointer"
                >
                  {link.label}
                </button>
              ))}
              <div className="pt-4 flex flex-col gap-3">
                <button
                  onClick={handleSignIn}
                  className="text-center text-on-surface-variant py-2 bg-transparent border-0 cursor-pointer hover:text-on-surface transition-colors"
                >
                  Sign In
                </button>
                <Button className="justify-center" onClick={handleGetStarted}>Get Started</Button>
              </div>
            </nav>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  )
}
