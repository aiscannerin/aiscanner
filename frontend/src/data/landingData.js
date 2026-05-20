// ── Platform Overview / Features ─────────────────────────────────────────────────

export const FEATURES = [
  {
    id: 'smc',
    icon: 'brain',
    accentColor: '#b3c5ff',
    accentBg: 'rgba(179,197,255,0.08)',
    title: 'Smart Money Concepts',
    description:
      'We scan for Order Blocks, Breaker Blocks, and Market Structure Shifts (BOS) using pure price action — no lagging indicators.',
    bullets: [
      'Real-time Order Block detection',
      'Break of Structure (BOS) alerts',
      'Change of Character (ChoCH) signals',
    ],
  },
  {
    id: 'sweep',
    icon: 'waves',
    accentColor: '#00f1fe',
    accentBg: 'rgba(0,241,254,0.08)',
    title: 'Liquidity Sweeps',
    description:
      'Pinpoint the exact moment institutions grab retail stop-losses before the real move begins.',
    bullets: [
      'Equal highs / equal lows detection',
      'Buy-side & sell-side liquidity maps',
      'Stop-hunt zone identification',
    ],
  },
  {
    id: 'fvg',
    icon: 'gap',
    accentColor: '#00d97e',
    accentBg: 'rgba(0,217,126,0.08)',
    title: 'Fair Value Gaps',
    description:
      'Automatically detects FVG imbalances across all timeframes and tracks when price returns to fill them.',
    bullets: [
      'HTF & LTF FVG mapping',
      'Fill probability scoring',
      'Multi-timeframe confluence alerts',
    ],
  },
  {
    id: 'grade',
    icon: 'grade',
    accentColor: '#b3c5ff',
    accentBg: 'rgba(179,197,255,0.08)',
    title: 'Setup Score & Grade',
    description:
      'Every scan result is scored 0–100 and graded A–D based on confluence across sweep, ChoCH, FVG, and order block alignment.',
    isGradeCard: true,
    grades: [
      { label: 'A', score: 94.2, color: '#00d97e', bg: 'rgba(0,217,126,0.15)' },
      { label: 'B', score: 78.6, color: '#b3c5ff', bg: 'rgba(179,197,255,0.15)' },
      { label: 'C', score: 61.0, color: '#f59e0b', bg: 'rgba(245,158,11,0.15)'  },
    ],
  },
]

// ── How It Works ─────────────────────────────────────────────────────────────────

export const HOW_IT_WORKS_STEPS = [
  {
    step: '01',
    icon: 'globe',
    title: 'Universe Scanning',
    description:
      'Choose NIFTY50, NIFTY100, NIFTY500, or FNO. The engine scans every symbol in the universe for qualifying liquidity structures.',
  },
  {
    step: '02',
    icon: 'crosshair',
    title: 'Setup Identification',
    description:
      'Multi-timeframe analysis pinpoints stop hunts, order blocks, and FVG imbalances. Each setup is scored by confluence strength.',
  },
  {
    step: '03',
    icon: 'shield',
    title: 'ChoCH + FVG Validation',
    description:
      'Only setups confirmed by a Change of Character and an aligned FVG pass through. That keeps signal quality high and noise low.',
  },
]

// ── Pricing ───────────────────────────────────────────────────────────────────────

export const PRICING_PLANS = [
  {
    id: 'free',
    name: 'Free',
    monthlyPrice: 0,
    yearlyPrice: 0,
    tagline: 'Get started at zero cost',
    accentColor: '#b3c5ff',
    accentBg: 'rgba(179,197,255,0.08)',
    highlighted: false,
    cta: 'Get Started Free',
    tools: [
      { name: 'Stop Hunter Pro',        included: false },
      { name: 'SMC Liquidity Scanner',  included: false },
      { name: 'Master Screener',        included: false },
      { name: 'Volume Profile Scanner', included: false },
      { name: 'Options Scanner',        included: false },
    ],
    features: [
      'Basic dashboard preview',
      'Market overview widgets',
      'Community access',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    monthlyPrice: 1999,
    yearlyPrice: 1499,
    tagline: 'For active intraday traders',
    accentColor: '#0066ff',
    accentBg: 'rgba(0,102,255,0.10)',
    highlighted: true,
    cta: 'Start Pro Trial',
    tools: [
      { name: 'Stop Hunter Pro',        included: true },
      { name: 'SMC Liquidity Scanner',  included: true },
      { name: 'Master Screener',        included: true },
      { name: 'Volume Profile Scanner', included: false },
      { name: 'Options Scanner',        included: false },
    ],
    features: [
      'All Free features',
      'Real-time scanner alerts',
      'H1, H4, Daily timeframes',
      'NIFTY50 + NIFTY100 universe',
      'Email & in-app alerts',
    ],
  },
  {
    id: 'expert',
    name: 'Expert',
    monthlyPrice: 3999,
    yearlyPrice: 2999,
    tagline: 'Full institutional toolkit',
    accentColor: '#00f1fe',
    accentBg: 'rgba(0,241,254,0.08)',
    highlighted: false,
    cta: 'Go Expert',
    tools: [
      { name: 'Stop Hunter Pro',        included: true },
      { name: 'SMC Liquidity Scanner',  included: true },
      { name: 'Master Screener',        included: true },
      { name: 'Volume Profile Scanner', included: true },
      { name: 'Options Scanner',        included: true },
    ],
    features: [
      'All Pro features',
      'Volume Profile Scanner',
      'Options Chain Scanner',
      'NIFTY500 + FNO universe',
      'Priority support',
      'Early access to AI Engine',
    ],
  },
]

// ── Dashboard Preview Mock Data ───────────────────────────────────────────────────

export const DASHBOARD_RECENT_SCANS = [
  { symbol: 'RELIANCE',  setup: 'BSL Sweep + BOS',   tf: '1H',  score: 91, grade: 'A', direction: 'bullish', time: '10:45 AM' },
  { symbol: 'HDFCBANK',  setup: 'SSL Grab + ChoCH',  tf: '4H',  score: 84, grade: 'A', direction: 'bearish', time: '11:02 AM' },
  { symbol: 'INFY',      setup: 'OB Mitigation + FVG', tf: '1H', score: 77, grade: 'B', direction: 'bullish', time: '11:18 AM' },
  { symbol: 'TATAMOTORS',setup: 'Equal Highs Sweep', tf: 'D1',  score: 88, grade: 'A', direction: 'bearish', time: '11:30 AM' },
  { symbol: 'SBIN',      setup: 'FVG Fill + BOS',    tf: '1H',  score: 69, grade: 'B', direction: 'bullish', time: '11:47 AM' },
  { symbol: 'ICICIBANK', setup: 'BSL Sweep + OB',    tf: '4H',  score: 95, grade: 'A', direction: 'bullish', time: '12:03 PM' },
]

// ── Scanner Library ───────────────────────────────────────────────────────────────

export const TOOLS_LIBRARY = [
  {
    slug: 'stop-hunter-pro',
    name: 'Stop Hunter Pro',
    description:
      'Identifies institutional stop-hunt zones and liquidity sweeps in real time across NIFTY50, NIFTY100, and FNO.',
    status: 'live',
    plan: 'Pro',
    accentColor: '#b3c5ff',
    accentBg: 'rgba(179,197,255,0.10)',
    icon: 'target',
    tags: ['Stop Hunts', 'BOS', 'Liquidity'],
  },
  {
    slug: 'smc-liquidity-scanner',
    name: 'SMC Liquidity Scanner',
    description:
      'Full Smart Money Concepts scanner — detects order blocks, fair value gaps, BOS, and ChoCH with confluence scoring.',
    status: 'live',
    plan: 'Pro',
    accentColor: '#00f1fe',
    accentBg: 'rgba(0,241,254,0.10)',
    icon: 'activity',
    tags: ['Order Blocks', 'FVG', 'ChoCH'],
  },
  {
    slug: 'master-screener',
    name: 'Master Screener',
    description:
      'Multi-filter stock screener combining technical structure with volume and momentum criteria for swing setups.',
    status: 'live',
    plan: 'Pro',
    accentColor: '#a78bfa',
    accentBg: 'rgba(167,139,250,0.10)',
    icon: 'filter',
    tags: ['Momentum', 'Volume', 'Swing'],
  },
  {
    slug: 'volume-profile-scanner',
    name: 'Volume Profile Scanner',
    description:
      'Scans for high-volume nodes, POC levels, and value area breakouts to find institutional accumulation zones.',
    status: 'live',
    plan: 'Expert',
    accentColor: '#f59e0b',
    accentBg: 'rgba(245,158,11,0.10)',
    icon: 'barchart',
    tags: ['POC', 'Value Area', 'Volume'],
  },
  {
    slug: 'options-scanner',
    name: 'Options Scanner',
    description:
      'Screens options chains for unusual OI buildup, PCR signals, and max pain levels tied to price structure.',
    status: 'live',
    plan: 'Expert',
    accentColor: '#00d97e',
    accentBg: 'rgba(0,217,126,0.10)',
    icon: 'trending',
    tags: ['OI', 'PCR', 'Max Pain'],
  },
  {
    slug: 'ai-confluence-engine',
    name: 'AI Confluence Engine',
    description:
      'Multi-timeframe AI engine that cross-validates every setup signal across all scanners for maximum probability.',
    status: 'coming_soon',
    plan: 'Expert',
    accentColor: '#f472b6',
    accentBg: 'rgba(244,114,182,0.10)',
    icon: 'cpu',
    tags: ['AI', 'Multi-TF', 'Confluence'],
  },
]
