// Static mock signals for the landing page scanner preview widget.
// No backend connection — purely for visual demonstration.

export const SWEEP_SIGNALS = [
  { id: 'sw1',  symbol: 'RELIANCE',   setup: 'Stop Hunt + BOS',      timeframe: '1h',  score: 92.4, grade: 'A', direction: 'bullish' },
  { id: 'sw2',  symbol: 'HDFCBANK',   setup: 'Equal Highs Sweep',    timeframe: '4h',  score: 87.1, grade: 'A', direction: 'bearish' },
  { id: 'sw3',  symbol: 'SBIN',       setup: 'Liquidity Sweep',      timeframe: '1h',  score: 78.9, grade: 'B', direction: 'bullish' },
  { id: 'sw4',  symbol: 'ICICIBANK',  setup: 'Institutional Run',    timeframe: '1d',  score: 83.6, grade: 'A', direction: 'bullish' },
  { id: 'sw5',  symbol: 'BAJFINANCE', setup: 'Equal Lows Sweep',     timeframe: '15m', score: 71.2, grade: 'B', direction: 'bearish' },
  { id: 'sw6',  symbol: 'TCS',        setup: 'Stop Hunt + BOS',      timeframe: '4h',  score: 94.2, grade: 'A', direction: 'bullish' },
  { id: 'sw7',  symbol: 'BHARTIARTL', setup: 'Inducement Sweep',     timeframe: '1h',  score: 76.8, grade: 'B', direction: 'bearish' },
  { id: 'sw8',  symbol: 'INFY',       setup: 'Buy-side Sweep',       timeframe: '4h',  score: 88.5, grade: 'A', direction: 'bearish' },
  { id: 'sw9',  symbol: 'LT',         setup: 'Stop Hunt + BOS',      timeframe: '1d',  score: 80.3, grade: 'B', direction: 'bullish' },
  { id: 'sw10', symbol: 'MARUTI',     setup: 'Liquidity Sweep',      timeframe: '1h',  score: 69.4, grade: 'C', direction: 'bullish' },
  { id: 'sw11', symbol: 'KOTAKBANK',  setup: 'SSL Sweep',            timeframe: '4h',  score: 91.0, grade: 'A', direction: 'bearish' },
  { id: 'sw12', symbol: 'AXISBANK',   setup: 'BSL + ChoCH',          timeframe: '1h',  score: 85.7, grade: 'A', direction: 'bullish' },
]

export const FVG_SIGNALS = [
  { id: 'fv1',  symbol: 'NIFTY',      setup: 'FVG Rejection',        timeframe: '1h',  score: 91.7, grade: 'A', direction: 'bullish' },
  { id: 'fv2',  symbol: 'BANKNIFTY',  setup: 'HTF FVG + OB',         timeframe: '4h',  score: 85.3, grade: 'A', direction: 'bearish' },
  { id: 'fv3',  symbol: 'WIPRO',      setup: 'Fair Value Gap',       timeframe: '15m', score: 74.6, grade: 'B', direction: 'bullish' },
  { id: 'fv4',  symbol: 'AXISBANK',   setup: 'ChoCH + FVG',          timeframe: '1h',  score: 89.2, grade: 'A', direction: 'bullish' },
  { id: 'fv5',  symbol: 'KOTAKBANK',  setup: 'FVG Rejection',        timeframe: '4h',  score: 77.8, grade: 'B', direction: 'bearish' },
  { id: 'fv6',  symbol: 'ONGC',       setup: 'OB + FVG',             timeframe: '1d',  score: 82.1, grade: 'A', direction: 'bullish' },
  { id: 'fv7',  symbol: 'ASIANPAINT', setup: 'FVG + BOS',            timeframe: '1h',  score: 93.6, grade: 'A', direction: 'bearish' },
  { id: 'fv8',  symbol: 'ULTRACEMCO', setup: 'HTF FVG',              timeframe: '4h',  score: 70.4, grade: 'B', direction: 'bullish' },
  { id: 'fv9',  symbol: 'NTPC',       setup: 'ChoCH + FVG',          timeframe: '1h',  score: 86.9, grade: 'A', direction: 'bullish' },
  { id: 'fv10', symbol: 'POWERGRID',  setup: 'Fair Value Gap',       timeframe: '15m', score: 75.3, grade: 'B', direction: 'bearish' },
  { id: 'fv11', symbol: 'HCLTECH',    setup: 'Bearish FVG + MSS',    timeframe: '4h',  score: 90.1, grade: 'A', direction: 'bearish' },
  { id: 'fv12', symbol: 'SUNPHARMA',  setup: 'FVG Rejection',        timeframe: '1d',  score: 83.4, grade: 'A', direction: 'bullish' },
]
