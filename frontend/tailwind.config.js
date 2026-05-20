/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      // ── Design token colors (from Stitch DESIGN.md) ────────────────────────────
      colors: {
        background:             '#050810',
        surface:                '#10131c',
        'surface-dim':          '#10131c',
        'surface-bright':       '#363943',
        'surface-lowest':       '#0b0e16',
        'surface-low':          '#191b24',
        'surface-container':    '#1d1f28',
        'surface-high':         '#272a33',
        'surface-highest':      '#32343e',
        'on-surface':           '#e1e2ee',
        'on-surface-variant':   '#c2c6d8',
        'inverse-surface':      '#e1e2ee',
        'inverse-on-surface':   '#2e303a',
        outline:                '#8c90a1',
        'outline-variant':      '#424656',
        'surface-tint':         '#b3c5ff',
        primary:                '#b3c5ff',
        'on-primary':           '#002b75',
        'primary-container':    '#0066ff',
        'on-primary-container': '#f8f7ff',
        'inverse-primary':      '#0054d6',
        secondary:              '#ddfcff',
        'on-secondary':         '#00363a',
        'secondary-container':  '#00f1fe',
        'on-secondary-container': '#006a70',
        tertiary:               '#ffb59d',
        'on-tertiary':          '#5d1900',
        'tertiary-container':   '#cc4204',
        'on-tertiary-container': '#fff6f4',
        error:                  '#ffb4ab',
        'error-container':      '#93000a',
        // Functional
        bullish:                '#00d97e',
        bearish:                '#ff4d4f',
        amber:                  '#f59e0b',
      },

      // ── Typography tokens ───────────────────────────────────────────────────────
      fontFamily: {
        sans:  ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono:  ['Space Grotesk', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        'display-xl':  ['48px', { lineHeight: '56px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'display-lg':  ['36px', { lineHeight: '44px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'headline-md': ['24px', { lineHeight: '32px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'headline-sm': ['20px', { lineHeight: '28px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'body-main':   ['15px', { lineHeight: '24px', letterSpacing: '0em',    fontWeight: '400' }],
        'body-sm':     ['13px', { lineHeight: '20px', letterSpacing: '0em',    fontWeight: '400' }],
        'data-mono':   ['14px', { lineHeight: '20px', letterSpacing: '0.02em', fontWeight: '500' }],
        'label-caps':  ['11px', { lineHeight: '16px', letterSpacing: '0.1em',  fontWeight: '700' }],
      },

      // ── Border radius tokens ────────────────────────────────────────────────────
      borderRadius: {
        sm:      '0.125rem',
        DEFAULT: '0.25rem',
        md:      '0.375rem',
        lg:      '0.5rem',
        xl:      '0.75rem',
        '2xl':   '1rem',
        full:    '9999px',
      },

      // ── Glow shadows ────────────────────────────────────────────────────────────
      boxShadow: {
        'glow-primary':     '0 0 24px rgba(179,197,255,0.18), 0 0 64px rgba(179,197,255,0.07)',
        'glow-cyan':        '0 0 24px rgba(0,241,254,0.20), 0 0 64px rgba(0,241,254,0.08)',
        'glow-btn':         '0 0 20px rgba(0,102,255,0.55)',
        'card':             '0 4px 32px rgba(0,0,0,0.5)',
        'card-hover':       '0 8px 40px rgba(0,0,0,0.6)',
      },

      // ── Backdrop blur ───────────────────────────────────────────────────────────
      backdropBlur: {
        glass:       '20px',
        'glass-lg':  '40px',
      },

      // ── Keyframe animations ─────────────────────────────────────────────────────
      keyframes: {
        'ping-slow': {
          '0%':   { transform: 'scale(1)',   opacity: '0.6' },
          '100%': { transform: 'scale(2.2)', opacity: '0' },
        },
        'shimmer': {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition:  '200% 0' },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%':      { transform: 'translateY(-6px)' },
        },
      },
      animation: {
        'ping-slow': 'ping-slow 1.8s cubic-bezier(0,0,0.2,1) infinite',
        'shimmer':   'shimmer 2s linear infinite',
        'float':     'float 4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
