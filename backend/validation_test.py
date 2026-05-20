"""
Stop Hunter Pro — Large Validation Pass
Nifty 50 + Nifty 100 extra + F&O universe
HTF: 1H  |  LTF: 15M  |  Present mode  |  Fast + Best Setup comparison
"""

import importlib.util, pathlib, time, collections, sys

# ── loader ────────────────────────────────────────────────────────────────────
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, pathlib.Path(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

engine  = load('engine',  'app/services/stop_hunter_engine.py')
yf_prov = load('yf_prov', 'app/providers/yfinance_provider.py')

# ── Redis status ──────────────────────────────────────────────────────────────
# Force Redis connect attempt early so we know if cache is available
_redis_available = False
try:
    r = yf_prov._get_redis()
    _redis_available = (r is not None)
except Exception:
    pass
print(f"Redis candle cache: {'AVAILABLE' if _redis_available else 'UNAVAILABLE (cache disabled)'}")

# ── symbol universes ──────────────────────────────────────────────────────────
NIFTY50 = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
    "BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","TITAN",
    "BAJFINANCE","WIPRO","HCLTECH","ADANIENT","ADANIPORTS","ULTRACEMCO","NTPC",
    "POWERGRID","ONGC","COALINDIA","BAJAJFINSV","NESTLEIND","DIVISLAB","DRREDDY",
    "CIPLA","EICHERMOT","GRASIM","HEROMOTOCO","HINDALCO","JSWSTEEL","M&M",
    "SHRIRAMFIN","SUNPHARMA","TATACONSUM","TATAMOTORS","TATASTEEL","TECHM",
    "TRENT","APOLLOHOSP","BPCL","BRITANNIA","INDUSINDBK","LTIM","SBILIFE",
    "ZOMATO",
]
NIFTY100_EXTRA = [
    "AMBUJACEM","ATGL","BAJAJ-AUTO","BANKBARODA","BEL","BERGEPAINT","CHOLAFIN",
    "DABUR","DMART","GODREJCP","HAVELLS","HDFCLIFE","ICICIPRULI","INDIGO",
    "IRCTC","JIOFIN","LODHA","MANKIND","MARICO","NAUKRI","PIDILITIND",
    "RECLTD","SIEMENS","TORNTPHARM","TVSMOTOR","VBL","VEDL","ZYDUSLIFE",
]
FNO_EXTRA = [
    "ABCAPITAL","ABB","AARTIIND","ACC","APLAPOLLO","AUBANK","ABFRL",
    "ADANIGREEN","ADANIPOWER","ALKEM","AUROPHARMA","BANDHANBNK","BIOCON",
    "BOSCHLTD","BSOFT","CANBK","CANFINHOME","COFORGE","CONCOR","COROMANDEL",
    "CUMMINSIND","DEEPAKNTR","DIXON","DLF","ESCORTS","FEDERALBNK","GAIL",
    "GNFC","GODREJPROP","GRANULES","GUJGASLTD","HAL","HINDPETRO","HINDCOPPER",
    "IDFCFIRSTB","IGL","INDHOTEL","IOB","IPCALAB","JKCEMENT","JSWENERGY",
    "JUBLFOOD","KEI","LICHSGFIN","LICI","LUPIN","MANAPPURAM","MCDOWELL-N",
    "MCX","MFSL","MPHASIS","MUTHOOTFIN","NATIONALUM","NAVINFLUOR","NBCC",
    "NCC","OBEROIRLTY","OFSS","OIL","PAGEIND","PERSISTENT","PFC","PIIND",
    "PNB","POLICYBZR","POLYCAB","RBLBANK","SAIL","SBICARD","SRF","SUPREMEIND",
    "TATACHEM","TATACOMM","TATAELXSI","TIINDIA","TORNTPOWER","TRIDENT",
    "UBL","UNIONBANK","UPL","VOLTAS","WHIRLPOOL","ZEEL",
]

# Deduplicate keeping order
def dedup(lst):
    seen = set(); out = []
    for x in lst:
        if x not in seen: seen.add(x); out.append(x)
    return out

ALL_SYMBOLS = dedup(NIFTY50 + NIFTY100_EXTRA + FNO_EXTRA)
print(f"Total unique symbols: {len(ALL_SYMBOLS)}")
print(f"  Nifty 50: {len(NIFTY50)}")
print(f"  + Nifty 100 extra: {len(NIFTY100_EXTRA)}")
print(f"  + F&O extra: {len(FNO_EXTRA)}")
print()

# ── base config ───────────────────────────────────────────────────────────────
BASE = {
    'swing_length': 5, 'max_setup_age': 50, 'max_liquidity_age': 150,
    'min_displacement_atr': 0.5, 'min_choch_atr': 0.25,
    'require_fvg': True, 'require_retest': False, 'require_ltf': False,
    'include_near_miss': True, 'max_choch_bars': 25,
    'min_body_pct': 0.60, 'min_close_pct': 0.70, 'min_fvg_atr': 0.15,
    'scan_mode': 'present', 'internal_pivot_length': 3,
    'use_eqh_eql': True, 'use_session_levels': True,
    'max_sweep_candidates': 5,
}
FAST_F = {**BASE, 'candidate_mode': 'fast'}
BEST_F = {**BASE, 'candidate_mode': 'best_setup'}

HTF = '1h'; LTF = '15m'

# ── fetch candles (batch API — cold cache) ────────────────────────────────────
yf_syms = [s + '.NS' for s in ALL_SYMBOLS]

yf_prov.reset_fetch_stats()
print(f"Fetching candles (batch, cold cache) for {len(yf_syms)} symbols ...")
fetch_start = time.time()

htf_batch = yf_prov.get_candles_multi(yf_syms, timeframe=HTF, limit=200)
ltf_batch = yf_prov.get_candles_multi(yf_syms, timeframe=LTF, limit=200)

cold_fetch_time  = time.time() - fetch_start
cold_fetch_stats = yf_prov.get_fetch_stats()
print(f"Cold fetch: {cold_fetch_time:.1f}s  hits={cold_fetch_stats['cache_hits']}  misses={cold_fetch_stats['cache_misses']}  errors={cold_fetch_stats['fetch_errors']}")

# ── warm cache run ────────────────────────────────────────────────────────────
yf_prov.reset_fetch_stats()
print(f"Re-fetching (warm cache) ...")
warm_start = time.time()
htf_batch2 = yf_prov.get_candles_multi(yf_syms, timeframe=HTF, limit=200)
ltf_batch2 = yf_prov.get_candles_multi(yf_syms, timeframe=LTF, limit=200)
warm_fetch_time  = time.time() - warm_start
warm_fetch_stats = yf_prov.get_fetch_stats()
print(f"Warm fetch: {warm_fetch_time:.1f}s  hits={warm_fetch_stats['cache_hits']}  misses={warm_fetch_stats['cache_misses']}  errors={warm_fetch_stats['fetch_errors']}")
print()

# ── build per-symbol dicts ────────────────────────────────────────────────────
htf_data = {}; ltf_data = {}; failed_fetch = []
for sym in ALL_SYMBOLS:
    h = htf_batch.get(sym + '.NS') or []
    l = ltf_batch.get(sym + '.NS') or []
    if len(h) >= 30:
        htf_data[sym] = h
        ltf_data[sym] = l
    else:
        failed_fetch.append(sym)

SYMBOLS = [s for s in ALL_SYMBOLS if s in htf_data]
fetch_time = cold_fetch_time   # used in later sections as the canonical fetch time
print(f"Usable symbols: {len(SYMBOLS)}  (failed/insufficient: {len(failed_fetch)})")
if failed_fetch:
    print(f"  Failed: {failed_fetch[:10]}{'...' if len(failed_fetch)>10 else ''}")
print()

# ── run engine ────────────────────────────────────────────────────────────────
def run_pass(symbols, filters, label):
    results = {}; sym_times = {}
    t0 = time.time()
    for sym in symbols:
        ts = time.time()
        try:
            r = engine.analyse_symbol(sym, htf_data[sym], HTF, filters, ltf_data[sym])
        except Exception as e:
            r = None
        results[sym] = r
        sym_times[sym] = time.time() - ts
    elapsed = time.time() - t0
    return results, sym_times, elapsed

print("Running FAST mode ...")
fast_res, fast_times, fast_elapsed = run_pass(SYMBOLS, FAST_F, 'fast')
print(f"  Done in {fast_elapsed:.1f}s  avg {fast_elapsed/len(SYMBOLS)*1000:.0f}ms/sym")

print("Running BEST SETUP mode ...")
best_res, best_times, best_elapsed = run_pass(SYMBOLS, BEST_F, 'best_setup')
print(f"  Done in {best_elapsed:.1f}s  avg {best_elapsed/len(SYMBOLS)*1000:.0f}ms/sym")
print()

SEP = '=' * 100
sep = '-' * 100

# ══ 1. Classification counts ══════════════════════════════════════════════════
def counts(res):
    c = collections.Counter()
    for r in res.values():
        c[r['classification'] if r else 'no_result'] += 1
    return c

fc = counts(fast_res); bc = counts(best_res)

print(SEP)
print('1. CLASSIFICATION COUNTS')
print(SEP)
print(f"{'':20s} {'FAST':>10s} {'BEST_SETUP':>10s}")
for cl in ['confirmed','watchlist','near_miss','no_result']:
    print(f"  {cl:18s} {fc[cl]:>10d} {bc[cl]:>10d}")
print()

# ══ 2. Watchlist level counts ═════════════════════════════════════════════════
def wl_counts(res):
    c = collections.Counter()
    for r in res.values():
        if r and r['classification'] == 'watchlist':
            c[r.get('watchlist_level') or 'unknown'] += 1
    return c

fwl = wl_counts(fast_res); bwl = wl_counts(best_res)

print(SEP)
print('2. WATCHLIST LEVEL COUNTS')
print(SEP)
print(f"{'':30s} {'FAST':>8s} {'BEST_SETUP':>10s}")
labels = {
    'L1': 'L1 — Awaiting HTF Retest',
    'L2': 'L2 — Awaiting LTF Sweep',
    'L3': 'L3 — Awaiting LTF ChoCH',
    'L4': 'L4 — Awaiting LTF OB 2.0',
}
for lvl, lbl in labels.items():
    print(f"  {lbl:28s} {fwl[lvl]:>8d} {bwl[lvl]:>10d}")
print()

# ══ 3. Top 20 by score (fast mode) ═══════════════════════════════════════════
print(SEP)
print('3. TOP 20 SETUPS BY SCORE  [Fast mode]')
print(SEP)
ranked = sorted(
    [(sym, r) for sym, r in fast_res.items() if r],
    key=lambda x: x[1]['score'], reverse=True
)[:20]

hdr = f"{'#':3s} {'Symbol':12s} {'Dir':5s} {'Class':10s} {'WL':4s} {'Score':6s} {'Gr':3s} {'Liq src':16s} {'TP':12s} {'Stage'}"
print(hdr)
print(sep)
for i, (sym, r) in enumerate(ranked, 1):
    db   = r.get('debug_trace', {})
    src  = (db.get('selected_liq_source') or db.get('liq_source') or 'swing')[:14]
    wl   = r.get('watchlist_level') or '—'
    tpt  = (r.get('trade_plan_type') or '—')[:10]
    stg  = (r.get('current_stage_label') or '—')[:35]
    dire = r['direction'][:4]
    cl   = r['classification'][:8]
    print(f"{i:3d} {sym:12s} {dire:5s} {cl:10s} {wl:4s} {r['score']:6.1f} {r['grade']:3s} {src:16s} {tpt:12s} {stg}")
print()

# ══ 4. Safety checks ══════════════════════════════════════════════════════════
print(SEP)
print('4. SAFETY CHECKS')
print(SEP)

issues = []

for sym, r in fast_res.items():
    if not r: continue
    cl  = r['classification']
    tpt = r.get('trade_plan_type')
    ttl = r.get('trade_plan_title', '')
    er  = r.get('ltf_ob', False)   # entry_ready ≈ ltf_ob for confirmed
    htfc = r.get('htf_checklist', {})
    ltfc = r.get('ltf_checklist', {})

    # Watchlist with ltf_ob=True: should now be L4 (score-gated), not L2 fallback
    if cl == 'watchlist' and r.get('ltf_ob'):
        wl_lvl = r.get('watchlist_level')
        if wl_lvl != 'L4':
            issues.append(f"FAIL  {sym}: watchlist+ltf_ob but watchlist_level={wl_lvl} (expected L4)")

    # Near miss must not have trade_plan_type = entry
    if cl == 'near_miss' and tpt == 'entry':
        issues.append(f"FAIL  {sym}: near_miss but trade_plan_type=entry")

    # Watchlist must say preparation
    if cl == 'watchlist' and tpt != 'preparation':
        issues.append(f"FAIL  {sym}: watchlist but trade_plan_type={tpt}")

    # Near miss must say no_trade
    if cl == 'near_miss' and tpt != 'no_trade':
        issues.append(f"FAIL  {sym}: near_miss but trade_plan_type={tpt}")

    # Confirmed must have full sequence
    if cl == 'confirmed':
        needs = ['retest','ltf_sweep','ltf_choch','ltf_ob']
        missing = [k for k in needs if not r.get(k)]
        if missing:
            issues.append(f"FAIL  {sym}: confirmed but missing: {missing}")
        if tpt != 'entry':
            issues.append(f"FAIL  {sym}: confirmed but trade_plan_type={tpt}")

    # Watchlist title must START with "Preparation Zone", not "Entry Signal"
    # (note: "Not An Entry Signal" is a valid substring of the correct title)
    if cl == 'watchlist' and ttl.startswith('Entry Signal'):
        issues.append(f"FAIL  {sym}: watchlist title starts with 'Entry Signal': {ttl}")

    # Near miss title must not start with "Entry Signal"
    if cl == 'near_miss' and ttl.startswith('Entry Signal'):
        issues.append(f"FAIL  {sym}: near_miss title starts with 'Entry Signal': {ttl}")

if issues:
    for iss in issues:
        print(f"  {iss}")
else:
    print("  All safety checks passed. No violations found.")
print()

# ══ 5. Fast vs Best Setup comparison ═════════════════════════════════════════
print(SEP)
print('5. FAST vs BEST_SETUP COMPARISON')
print(SEP)

promoted = []; demoted = []; score_up = []; score_dn = []
for sym in SYMBOLS:
    fr = fast_res[sym]; br = best_res[sym]
    fcl = fr['classification'] if fr else 'none'
    bcl = br['classification'] if br else 'none'
    fsc = fr['score'] if fr else 0.0
    bsc = br['score'] if br else 0.0
    delta = bsc - fsc
    CL_R = {'confirmed':0,'watchlist':1,'near_miss':2,'none':3}
    if CL_R.get(fcl,3) > CL_R.get(bcl,3):
        promoted.append((sym, fcl, fsc, bcl, bsc, delta))
    elif CL_R.get(fcl,3) < CL_R.get(bcl,3):
        demoted.append((sym, fcl, fsc, bcl, bsc, delta))
    elif abs(delta) >= 3.0:
        if delta > 0: score_up.append((sym, fcl, fsc, bcl, bsc, delta))
        else:          score_dn.append((sym, fcl, fsc, bcl, bsc, delta))

fast_avg = sum(r['score'] for r in fast_res.values() if r) / max(1, fc['confirmed']+fc['watchlist']+fc['near_miss'])
best_avg = sum(r['score'] for r in best_res.values() if r) / max(1, bc['confirmed']+bc['watchlist']+bc['near_miss'])

print(f"  Avg score  — Fast: {fast_avg:.1f}   Best Setup: {best_avg:.1f}   delta: {best_avg-fast_avg:+.1f}")
print(f"  Promoted (class improved)  : {len(promoted)}")
print(f"  Demoted  (class worsened)  : {len(demoted)}")
print(f"  Score up  >=3pt same class : {len(score_up)}")
print(f"  Score down >=3pt same class: {len(score_dn)}")

if promoted:
    print("\n  PROMOTED:")
    for sym, fc2, fs, bc2, bs, d in promoted[:10]:
        print(f"    {sym:12s}: {fc2}({fs:.1f}) -> {bc2}({bs:.1f})  delta={d:+.1f}")

if demoted:
    print("\n  DEMOTED:")
    for sym, fc2, fs, bc2, bs, d in demoted[:10]:
        print(f"    {sym:12s}: {fc2}({fs:.1f}) -> {bc2}({bs:.1f})  delta={d:+.1f}")

if score_up:
    print("\n  SCORE IMPROVED >=3pt:")
    for sym, fc2, fs, bc2, bs, d in sorted(score_up, key=lambda x: -x[5])[:10]:
        bdb = best_res[sym].get('debug_trace',{})
        src = bdb.get('selected_liq_source','?')
        print(f"    {sym:12s}: {fc2}({fs:.1f}) -> {bc2}({bs:.1f})  delta={d:+.1f}  src={src}")

if score_dn:
    print("\n  SCORE REGRESSED >=3pt:")
    for sym, fc2, fs, bc2, bs, d in sorted(score_dn, key=lambda x: x[5])[:10]:
        bdb = best_res[sym].get('debug_trace',{})
        src = bdb.get('selected_liq_source','?')
        print(f"    {sym:12s}: {fc2}({fs:.1f}) -> {bc2}({bs:.1f})  delta={d:+.1f}  src={src}")

# Suspicious promotions: best_setup promoted but classification doesn't look fully valid
if promoted:
    print("\n  Suspicious-promotion check:")
    any_susp = False
    for sym, fc2, fs, bc2, bs, d in promoted:
        r = best_res[sym]
        if not r: continue
        htfc = r.get('htf_checklist', {})
        cd   = r.get('choch_detail', {})
        sd   = r.get('sweep_detail', {})
        sus = []
        if not htfc.get('displacement'):
            sus.append('no displacement')
        if cd.get('reference_type') and 'fallback' in cd.get('reference_type',''):
            sus.append(f"ChoCH fallback ref")
        cb = sd.get('close_back_size',0) or 0
        wk = sd.get('swept_wick',0) or 0
        if wk > 0 and cb < wk * 0.3:
            sus.append('weak close-back')
        if sus:
            print(f"    SUSPICIOUS  {sym}: {fc2}->{bc2}  issues: {sus}")
            any_susp = True
    if not any_susp:
        print("    No suspicious promotions found.")
print()

# ══ 6. Performance ═══════════════════════════════════════════════════════════
print(SEP)
print('6. PERFORMANCE')
print(SEP)
print(f"  Total symbols scanned      : {len(SYMBOLS)}")
print()
print(f"  --- CANDLE FETCH ---")
print(f"  Cold fetch (batch, network): {cold_fetch_time:.1f}s")
print(f"    cache hits   : {cold_fetch_stats['cache_hits']}")
print(f"    cache misses : {cold_fetch_stats['cache_misses']}")
print(f"    fetch errors : {cold_fetch_stats['fetch_errors']}")
if cold_fetch_stats['slow_fetches']:
    print(f"    slow batches : {cold_fetch_stats['slow_fetches']}")
print()
print(f"  Warm fetch (Redis cache)   : {warm_fetch_time:.3f}s")
print(f"    cache hits   : {warm_fetch_stats['cache_hits']}")
print(f"    cache misses : {warm_fetch_stats['cache_misses']}")
if warm_fetch_time > 0.001:
    speedup = cold_fetch_time / warm_fetch_time
    print(f"  Cache speedup              : {speedup:.0f}x faster")
print()
print(f"  --- ENGINE SCAN ---")
print(f"  Fast mode total            : {fast_elapsed:.1f}s   avg {fast_elapsed/len(SYMBOLS)*1000:.0f}ms/sym")
print(f"  Best Setup mode total      : {best_elapsed:.1f}s   avg {best_elapsed/len(SYMBOLS)*1000:.0f}ms/sym")
print(f"  Best Setup overhead        : {best_elapsed-fast_elapsed:+.1f}s  ({(best_elapsed/max(fast_elapsed,0.001)-1)*100:.0f}% slower)")
slowest_fast = sorted(fast_times.items(), key=lambda x: -x[1])[:5]
slowest_best = sorted(best_times.items(), key=lambda x: -x[1])[:5]
print(f"\n  Slowest (Fast): {[(s, f'{t*1000:.0f}ms') for s, t in slowest_fast]}")
print(f"  Slowest (Best): {[(s, f'{t*1000:.0f}ms') for s, t in slowest_best]}")
print()

# ══ 7. Strong vs Questionable ════════════════════════════════════════════════
print(SEP)
print('7a. TOP 5 STRONGEST VALID-LOOKING SETUPS  [Fast mode]')
print(SEP)

def quality_score(sym, r):
    if not r: return -999
    htfc = r.get('htf_checklist', {})
    cd   = r.get('choch_detail', {})
    sd   = r.get('sweep_detail', {})
    db   = r.get('debug_trace', {})
    bonus = 0
    if htfc.get('displacement'):    bonus += 2
    if cd.get('reference_type','').startswith('swing'): bonus += 2
    cb = sd.get('close_back_size',0) or 0
    wk = sd.get('swept_wick',0) or 0
    if wk > 0 and cb >= wk * 0.5:  bonus += 2
    if htfc.get('ob_retest'):       bonus += 1
    if r.get('ltf_sweep'):          bonus += 1
    return r['score'] + bonus * 2

def quality_issues(r):
    htfc = r.get('htf_checklist', {})
    cd   = r.get('choch_detail', {})
    sd   = r.get('sweep_detail', {})
    db   = r.get('debug_trace', {})
    fd   = r.get('fvg_detail', {})
    iss  = []
    if not htfc.get('displacement'):
        iss.append('no disp')
    if cd.get('reference_type') and 'fallback' in cd.get('reference_type',''):
        iss.append('ChoCH fallback')
    cb = sd.get('close_back_size',0) or 0
    wk = sd.get('swept_wick',0) or 0
    if wk > 0 and cb < wk * 0.3:
        iss.append('weak close-back')
    gap = fd.get('gap_pct') or 0
    if 0 < gap < 0.05:
        iss.append('tiny FVG')
    bars = cd.get('bars_after_sweep', 0) or 0
    if bars > 15:
        iss.append(f'slow ChoCH({bars}b)')
    return iss

# Strong: no quality issues, score>=50, watchlist or confirmed
strong = [
    (sym, r) for sym, r in fast_res.items()
    if r and r['classification'] in ('watchlist','confirmed')
    and len(quality_issues(r)) == 0
    and r['score'] >= 50
]
strong.sort(key=lambda x: quality_score(x[0], x[1]), reverse=True)

for sym, r in strong[:5]:
    db  = r.get('debug_trace',{})
    src = db.get('selected_liq_source') or db.get('liq_source','swing')
    wl  = r.get('watchlist_level') or '—'
    print(f"  {sym:12s} {r['classification']:10s} {wl:4s} score={r['score']:.1f}/{r['grade']}  src={src}  stage={r.get('current_stage_label','')}")
    print(f"             {r.get('trade_plan_warning') or r.get('trade_plan_title','')[:80]}")
    print()

print(SEP)
print('7b. TOP 5 QUESTIONABLE SETUPS  [Fast mode]')
print(SEP)

questionable = [
    (sym, r, quality_issues(r)) for sym, r in fast_res.items()
    if r and r['classification'] in ('watchlist','confirmed')
    and len(quality_issues(r)) > 0
]
questionable.sort(key=lambda x: x[1]['score'], reverse=True)

for sym, r, iss in questionable[:5]:
    db  = r.get('debug_trace',{})
    src = db.get('selected_liq_source') or db.get('liq_source','swing')
    wl  = r.get('watchlist_level') or '—'
    print(f"  {sym:12s} {r['classification']:10s} {wl:4s} score={r['score']:.1f}/{r['grade']}  src={src}")
    print(f"             Issues: {iss}")
    print(f"             Stage : {r.get('current_stage_label','')}")
    print()

# ══ 8. Logic inconsistency check ═════════════════════════════════════════════
print(SEP)
print('7c. LOGIC INCONSISTENCY CHECK')
print(SEP)

inconsistencies = []
for sym, r in fast_res.items():
    if not r: continue
    cl  = r['classification']
    wl  = r.get('watchlist_level')
    stg = r.get('current_stage_label','')
    htfc = r.get('htf_checklist',{})
    tpt  = r.get('trade_plan_type')

    # watchlist L1 but stage says Monitoring
    if cl=='watchlist' and wl=='L1' and stg=='Monitoring':
        inconsistencies.append(f"  {sym}: watchlist L1 but stage=Monitoring")
    # watchlist but no watchlist_level
    if cl=='watchlist' and not wl:
        inconsistencies.append(f"  {sym}: watchlist but watchlist_level=None")
    # near_miss score > 80 (suspiciously high)
    if cl=='near_miss' and r['score'] > 80:
        inconsistencies.append(f"  {sym}: near_miss score={r['score']:.1f} suspiciously high")
    # trade plan type mismatch
    expected_tpt = 'entry' if cl=='confirmed' else 'preparation' if cl=='watchlist' else 'no_trade'
    if tpt != expected_tpt:
        inconsistencies.append(f"  {sym}: cl={cl} but trade_plan_type={tpt} (expected {expected_tpt})")

if inconsistencies:
    for iss in inconsistencies:
        print(iss)
else:
    print("  No logic inconsistencies found.")


# ══ 8. Quality Flags Report ═══════════════════════════════════════════════════
print(SEP)
print('8. QUALITY FLAGS REPORT  [Fast mode]')
print(SEP)

# 8a. Top 10 most common flag IDs
flag_counter = collections.Counter()
for r in fast_res.values():
    if not r: continue
    for f in (r.get('quality_flags') or []):
        flag_counter[f['id']] += 1

print('8a. Top 10 most common flags:')
for fid, cnt in flag_counter.most_common(10):
    print(f"    {cnt:4d}x  {fid}")
print()

# 8b. Quality flags for up to 5 confirmed setups
print('8b. Quality flags — CONFIRMED setups:')
confirmed_syms = [(sym, r) for sym, r in fast_res.items()
                  if r and r['classification'] == 'confirmed'][:5]
if not confirmed_syms:
    print('    (no confirmed setups in this run)')
for sym, r in confirmed_syms:
    flags = r.get('quality_flags') or []
    print(f"  {sym:12s}  score={r['score']:.1f}  flags({len(flags)}):")
    for f in flags:
        print(f"      [{f['severity'].upper():8s}] {f['label']:38s}  {f['detail'][:70]}")
    if not flags:
        print('      (no flags)')
print()

# 8c. Quality flags for up to 5 questionable watchlist setups
print('8c. Quality flags — QUESTIONABLE watchlist setups:')
q_wl = [(sym, r, quality_issues(r)) for sym, r in fast_res.items()
        if r and r['classification'] == 'watchlist' and len(quality_issues(r)) > 0]
q_wl.sort(key=lambda x: x[1]['score'], reverse=True)
if not q_wl:
    print('    (no questionable watchlist setups)')
for sym, r, iss in q_wl[:5]:
    flags = r.get('quality_flags') or []
    wl = r.get('watchlist_level','?')
    print(f"  {sym:12s}  {wl}  score={r['score']:.1f}  issues={iss}  flags({len(flags)}):")
    for f in flags:
        print(f"      [{f['severity'].upper():8s}] {f['label']:38s}  {f['detail'][:70]}")
    if not flags:
        print('      (no flags)')
print()

# 8d. Quality flags for TATACHEM (near_miss with suspiciously high score)
print('8d. Quality flags — TATACHEM (near_miss high score):')
tc = fast_res.get('TATACHEM')
if tc:
    flags = tc.get('quality_flags') or []
    print(f"  TATACHEM  cl={tc['classification']}  score={tc['score']:.1f}  flags({len(flags)}):")
    for f in flags:
        print(f"      [{f['severity'].upper():8s}] {f['label']:38s}  {f['detail'][:70]}")
    if not flags:
        print('      (no flags)')
else:
    print('  TATACHEM not in results')
print()

# 8e. Validation: all results have quality_flags key
missing_flags = [sym for sym, r in fast_res.items() if r and 'quality_flags' not in r]
if missing_flags:
    print(f'8e. FAIL — {len(missing_flags)} results missing quality_flags key: {missing_flags[:5]}')
else:
    print(f'8e. All {sum(1 for r in fast_res.values() if r)} results contain quality_flags key. OK')
print()

print(SEP)
print('VALIDATION COMPLETE')
print(SEP)
print(f"  {len(SYMBOLS)} symbols  |  Fast {fast_elapsed:.0f}s  |  Best {best_elapsed:.0f}s")
print(f"  Fast:       confirmed={fc['confirmed']} watchlist={fc['watchlist']} near_miss={fc['near_miss']} no_result={fc['no_result']}")
print(f"  Best Setup: confirmed={bc['confirmed']} watchlist={bc['watchlist']} near_miss={bc['near_miss']} no_result={bc['no_result']}")
