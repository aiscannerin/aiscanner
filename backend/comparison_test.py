"""Phase 1 comparison test — 4 configs across 10 NSE symbols."""
import importlib.util, pathlib

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, pathlib.Path(path))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

engine  = load('engine',  'app/services/stop_hunter_engine.py')
yf_prov = load('yf_prov', 'app/providers/yfinance_provider.py')

SYMBOLS = ['RELIANCE','TCS','HDFCBANK','INFY','ICICIBANK','SBIN','LT','AXISBANK','KOTAKBANK','BHARTIARTL']
HTF = '1h'; LTF = '15m'

print('Fetching candles (once)...')
htf_data = {}; ltf_data = {}
for sym in SYMBOLS:
    htf_data[sym] = yf_prov.get_candles(sym+'.NS', timeframe=HTF, limit=200)
    ltf_data[sym] = yf_prov.get_candles(sym+'.NS', timeframe=LTF, limit=200)
    print(f'  {sym}: HTF={len(htf_data[sym])} LTF={len(ltf_data[sym])}')
print()

BASE = {
    'swing_length': 5, 'max_setup_age': 50, 'max_liquidity_age': 150,
    'min_displacement_atr': 0.5, 'min_choch_atr': 0.25,
    'require_fvg': True, 'require_retest': False, 'require_ltf': False,
    'include_near_miss': True, 'max_choch_bars': 25,
    'min_body_pct': 0.60, 'min_close_pct': 0.70, 'min_fvg_atr': 0.15,
    'scan_mode': 'present', 'internal_pivot_length': 3,
}

CONFIGS = [
    ('1_swing_only', 'Swing-only',    {'use_eqh_eql': False, 'use_session_levels': False}),
    ('2_eqh_eql',    '+ EQH/EQL',     {'use_eqh_eql': True,  'use_session_levels': False}),
    ('3_session',    '+ Session Lvls', {'use_eqh_eql': False, 'use_session_levels': True}),
    ('4_full_p1',    'Full Phase 1',   {'use_eqh_eql': True,  'use_session_levels': True}),
]

# ── Run all 4 configs ─────────────────────────────────────────────────────────
all_results = {}
for cfg_id, label, overrides in CONFIGS:
    f = {**BASE, **overrides}
    all_results[cfg_id] = {}
    for sym in SYMBOLS:
        r = engine.analyse_symbol(sym, htf_data[sym], HTF, f, ltf_data[sym])
        all_results[cfg_id][sym] = r

# ── Matrix ────────────────────────────────────────────────────────────────────
SEP = '=' * 90
sep = '-' * 90
print(SEP)
print('COMPARISON MATRIX   [class score liq_source]')
print(SEP)
print(f"{'Symbol':13s} {'Swing-only':22s} {'+ EQH/EQL':22s} {'+ Session Lvls':22s} {'Full Phase 1':22s}")
print(sep)
for sym in SYMBOLS:
    cells = []
    for cfg_id, _, _ in CONFIGS:
        r = all_results[cfg_id][sym]
        if r is None:
            cells.append(f"{'None':22s}")
        else:
            cl  = r['classification'][:4]
            sc  = r['score']
            src = (r['debug_trace'].get('liq_source') or 'swing')[:9]
            cells.append(f'{cl} {sc:5.1f} [{src}]')
    print(f'{sym:13s} {cells[0]:22s} {cells[1]:22s} {cells[2]:22s} {cells[3]:22s}')

# ── Per-config summary ────────────────────────────────────────────────────────
print()
print(SEP)
print('SUMMARY PER CONFIG')
print(SEP)

for cfg_id, label, _ in CONFIGS:
    res   = all_results[cfg_id]
    valid = {s: r for s, r in res.items() if r}
    conf  = sum(1 for r in valid.values() if r['classification'] == 'confirmed')
    watch = sum(1 for r in valid.values() if r['classification'] == 'watchlist')
    nm    = sum(1 for r in valid.values() if r['classification'] == 'near_miss')
    nores = len(SYMBOLS) - len(valid)
    scores = [r['score'] for r in valid.values()]
    avg   = sum(scores) / len(scores) if scores else 0
    top5  = sorted(valid.items(), key=lambda x: x[1]['score'], reverse=True)[:5]

    print(f'\n{label}')
    print(f'  confirmed={conf}  watchlist={watch}  near_miss={nm}  no_result={nores}  avg_score={avg:.1f}')
    print('  Top 5 by score:')
    for sym, r in top5:
        dbg      = r['debug_trace']
        src      = dbg.get('liq_source', 'swing')
        strng    = dbg.get('liq_strength', 1.0)
        bpct     = dbg.get('disp_body_pct')
        htfc     = r.get('htf_checklist', {})
        ltfc     = r.get('ltf_checklist', {})
        htf_n    = sum(1 for v in htfc.values() if v)
        ltf_n    = sum(1 for v in ltfc.values() if v)
        bpct_str = f'{bpct:.3f}' if bpct else 'n/a'
        print(f'    {sym:12s} {r["classification"]:10s} {r["score"]:5.1f}/{r["grade"]}'
              f'  liq={src:22s}(str={strng})  body={bpct_str}  htf={htf_n}/7 ltf={ltf_n}/4')
        print(f'               stage: "{r["current_stage_label"]}"')

# ── Classification changes vs baseline ───────────────────────────────────────
print()
print(SEP)
print('CLASSIFICATION / SCORE CHANGES vs Swing-only baseline')
print(SEP)

base_res = all_results['1_swing_only']
for cfg_id, label, _ in CONFIGS[1:]:
    res = all_results[cfg_id]
    promoted = []; demoted = []; score_delta = []
    for sym in SYMBOLS:
        b  = base_res[sym]; r = res[sym]
        bc = b['classification'] if b else 'none'
        rc = r['classification'] if r else 'none'
        bs = b['score'] if b else 0.0
        rs = r['score'] if r else 0.0
        src = r['debug_trace'].get('liq_source', '?') if r else '?'
        lvl = r.get('liquidity_level', '?') if r else '?'
        if bc in ('near_miss', 'none') and rc in ('watchlist', 'confirmed'):
            promoted.append((sym, bc, bs, rc, rs, src, lvl))
        elif bc in ('watchlist', 'confirmed') and rc in ('near_miss', 'none'):
            demoted.append((sym, bc, bs, rc, rs, src, lvl))
        elif abs(rs - bs) >= 3.0:
            score_delta.append((sym, bc, bs, rc, rs, src, rs - bs))

    print(f'\n  [{label}]')
    if promoted:
        print('  PROMOTED:')
        for sym, bc, bs, rc, rs, src, lvl in promoted:
            print(f'    UP {sym:12s}: {bc}({bs:.1f}) -> {rc}({rs:.1f})  liq_src={src}  level={lvl}')
    if demoted:
        print('  DEMOTED:')
        for sym, bc, bs, rc, rs, src, lvl in demoted:
            print(f'    DN {sym:12s}: {bc}({bs:.1f}) -> {rc}({rs:.1f})  liq_src={src}  level={lvl}')
    if score_delta:
        print('  SCORE SHIFT (>=3pt, same class):')
        for sym, bc, bs, rc, rs, src, delta in score_delta:
            print(f'    ~ {sym:12s}: {bc}({bs:.1f}) -> {rc}({rs:.1f})  delta={delta:+.1f}  liq_src={src}')
    if not (promoted or demoted or score_delta):
        print('    No changes.')

# ── Deep quality check on every promotion ────────────────────────────────────
print()
print(SEP)
print('DEEP QUALITY CHECK — all promoted setups (full checklist + sweep validity)')
print(SEP)

already_shown = set()
for cfg_id, label, _ in CONFIGS[1:]:
    res = all_results[cfg_id]
    for sym in SYMBOLS:
        b = base_res[sym]; r = res[sym]
        bc = b['classification'] if b else 'none'
        rc = r['classification'] if r else 'none'
        key = (sym, cfg_id)
        if bc in ('near_miss', 'none') and rc in ('watchlist', 'confirmed') and key not in already_shown:
            already_shown.add(key)
            dbg  = r['debug_trace']
            htfc = r.get('htf_checklist', {})
            ltfc = r.get('ltf_checklist', {})
            sd   = r.get('sweep_detail', {})
            dd   = r.get('displacement_detail', {})
            fd   = r.get('fvg_detail', {})
            cd   = r.get('choch_detail', {})
            print(f'\n  Config: {label}  |  Symbol: {sym}')
            print(f'  Classification : {bc}({b["score"] if b else 0:.1f}) -> {rc}({r["score"]:.1f})')
            print(f'  Liq source     : {dbg.get("liq_source")}  (strength={dbg.get("liq_strength")})')
            print(f'  Liq level      : {r.get("liquidity_level")}')
            print(f'  Sweep bar      : {sd.get("sweep_idx")}  wick={sd.get("swept_wick")}  close_back={sd.get("close_back_size")}')
            print(f'  Displacement   : found={htfc.get("displacement")}  body_pct={dbg.get("disp_body_pct")}  atr_ratio={dd.get("atr_ratio")}')
            print(f'  FVG            : found={htfc.get("fvg_formed")}  gap_pct={fd.get("gap_pct")}  zone={fd.get("zone_low")}-{fd.get("zone_high")}')
            print(f'  ChoCH          : found={htfc.get("choch_confirmed")}  ref_type={cd.get("reference_type")}  bars_after={cd.get("bars_after_sweep")}  break={cd.get("break_amount")}')
            print(f'  OB 1.0         : found={htfc.get("ob_activated")}')
            print(f'  HTF Retest     : found={htfc.get("ob_retest")}')
            print(f'  LTF sequence   : sweep={ltfc.get("ltf_sweep")}  choch={ltfc.get("ltf_choch")}  ob={ltfc.get("ltf_ob_formed")}')
            print(f'  Stage          : {r["current_stage_label"]}')
            print(f'  Reason         : {r["reason"][:150]}')
            # Logical validity assessment
            issues = []
            if not htfc.get('displacement'):
                issues.append('No displacement — OB/ChoCH may be premature')
            if cd.get('reference_type') and 'fallback' in cd.get('reference_type',''):
                issues.append(f'ChoCH used fallback reference ({cd.get("reference_type")}) — not swing-confirmed')
            if sd.get('close_back_size', 0) < sd.get('swept_wick', 0) * 0.3:
                issues.append('Weak close-back (<30% of wick) — sweep conviction low')
            if fd.get('gap_pct', 0) and fd.get('gap_pct', 0) < 0.1:
                issues.append('Very small FVG gap (<0.1%) — may be noise')
            if cd.get('bars_after_sweep', 999) > 15:
                issues.append(f'ChoCH slow ({cd.get("bars_after_sweep")} bars) — structure may have reset')
            if issues:
                print('  !! CONCERNS:')
                for iss in issues:
                    print(f'      - {iss}')
            else:
                print('  OK LOOKS VALID: all sequence checks passed')

print()
print(SEP)
print('VERDICT SUMMARY')
print(SEP)
print()
print('  Config               confirmed  watchlist  near_miss  avg_score  net_change_vs_baseline')
base_watch = sum(1 for r in all_results['1_swing_only'].values() if r and r['classification']=='watchlist')
base_nm    = sum(1 for r in all_results['1_swing_only'].values() if r and r['classification']=='near_miss')
base_avg   = sum(r['score'] for r in all_results['1_swing_only'].values() if r) / len(SYMBOLS)
print(f'  {"Swing-only":20s} 0          {base_watch}          {base_nm}          {base_avg:.1f}       baseline')
for cfg_id, label, _ in CONFIGS[1:]:
    res   = all_results[cfg_id]
    conf  = sum(1 for r in res.values() if r and r['classification']=='confirmed')
    watch = sum(1 for r in res.values() if r and r['classification']=='watchlist')
    nm    = sum(1 for r in res.values() if r and r['classification']=='near_miss')
    avg   = sum(r['score'] for r in res.values() if r) / len(SYMBOLS)
    prom  = sum(1 for sym in SYMBOLS if
                (base_res[sym] and base_res[sym]['classification'] in ('near_miss','none')) and
                (res[sym] and res[sym]['classification'] in ('watchlist','confirmed')))
    dem   = sum(1 for sym in SYMBOLS if
                (base_res[sym] and base_res[sym]['classification'] in ('watchlist','confirmed')) and
                (res[sym] and res[sym]['classification'] in ('near_miss','none')))
    note  = f'+{prom} promoted' if prom else ''
    if dem: note += f', -{dem} demoted'
    if not note: note = 'no class change'
    print(f'  {label:20s} {conf}          {watch}          {nm}          {avg:.1f}       {note}')

# ── Phase 2 candidate_mode validation ─────────────────────────────────────────
print()
print(SEP)
print('PHASE 2: candidate_mode=best_setup  vs  fast  (Full Phase 1 config, all symbols)')
print(SEP)

FULL_P1_BASE = {**BASE, 'use_eqh_eql': True, 'use_session_levels': True}
FAST_CFG     = {**FULL_P1_BASE, 'candidate_mode': 'fast',       'max_sweep_candidates': 5}
BEST_CFG     = {**FULL_P1_BASE, 'candidate_mode': 'best_setup', 'max_sweep_candidates': 5}

fast_res = {}
best_res = {}
for sym in SYMBOLS:
    fast_res[sym] = engine.analyse_symbol(sym, htf_data[sym], HTF, FAST_CFG, ltf_data[sym])
    best_res[sym] = engine.analyse_symbol(sym, htf_data[sym], HTF, BEST_CFG, ltf_data[sym])

print(f"\n{'Symbol':13s} {'FAST mode':30s} {'BEST_SETUP mode':30s} {'Delta score':12s} {'Change'}")
print('-' * 100)
for sym in SYMBOLS:
    fr = fast_res[sym];  br = best_res[sym]
    f_cl  = fr['classification'] if fr else 'none';  f_sc = fr['score'] if fr else 0.0
    b_cl  = br['classification'] if br else 'none';  b_sc = br['score'] if br else 0.0
    f_src = fr['debug_trace'].get('selected_liq_source', fr['debug_trace'].get('liq_source','?')) if fr else '?'
    b_src = br['debug_trace'].get('selected_liq_source', br['debug_trace'].get('liq_source','?')) if br else '?'
    f_cands = fr['debug_trace'].get('candidates_tested', 1) if fr else 0
    b_cands = br['debug_trace'].get('candidates_tested', 1) if br else 0
    delta = b_sc - f_sc
    change = 'IMPROVED' if delta >= 3 else ('REGRESSED' if delta <= -3 else 'same')
    f_str = f'{f_cl[:4]} {f_sc:5.1f} [{f_src[:10]}] cands={f_cands}'
    b_str = f'{b_cl[:4]} {b_sc:5.1f} [{b_src[:10]}] cands={b_cands}'
    print(f'{sym:13s} {f_str:30s} {b_str:30s} {delta:+.1f}        {change}')

# Deep dive: symbols that changed
print()
print('  Candidate summary for changed symbols:')
for sym in SYMBOLS:
    fr = fast_res[sym]; br = best_res[sym]
    f_sc = fr['score'] if fr else 0.0
    b_sc = br['score'] if br else 0.0
    if abs(b_sc - f_sc) >= 3 or (fr and br and fr['classification'] != br['classification']):
        print(f'\n  {sym}:')
        for label2, res2 in [('FAST', fr), ('BEST', br)]:
            if not res2: continue
            dt = res2['debug_trace']
            csum = dt.get('candidate_summary', [])
            print(f'    [{label2}] mode={dt.get("candidate_mode")} tested={dt.get("candidates_tested")} '
                  f'selected_rank={dt.get("selected_candidate_rank")} '
                  f'src={dt.get("selected_liq_source")} str={dt.get("selected_liq_strength")}')
            for c in csum:
                print(f'      #{c["rank"]} {c["liq_source"]:18s} {str(c["classification"]):10s} '
                      f'score={c["score"]} stage={c.get("stage_label","")}')

# Overall counts comparison
print()
print(f'  {"Config":20s} conf  watch  nm    avg')
for label2, res2 in [('fast', fast_res), ('best_setup', best_res)]:
    conf2  = sum(1 for r in res2.values() if r and r['classification']=='confirmed')
    watch2 = sum(1 for r in res2.values() if r and r['classification']=='watchlist')
    nm2    = sum(1 for r in res2.values() if r and r['classification']=='near_miss')
    avg2   = sum(r['score'] for r in res2.values() if r) / len(SYMBOLS)
    print(f'  {label2:20s} {conf2}     {watch2}      {nm2}     {avg2:.1f}')
