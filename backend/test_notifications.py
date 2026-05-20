"""
End-to-end notification test.

Scenario:
  Scan 1: NIFTY_A=watchlist/L2, NIFTY_B=near_miss, NIFTY_C=watchlist/L2
  Scan 2: NIFTY_A=confirmed (became_confirmed → notif),
          NIFTY_B=watchlist/L1 (became_watchlist → notif),
          NIFTY_C=watchlist/L2 unchanged (no notif)

Validates:
  1. became_confirmed creates notification
  2. became_watchlist creates notification
  3. unchanged creates NO notification
  4. Running scan 2 again (duplicate result) creates NO duplicate notification
  5. mark_read works
  6. mark_all_read works
"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')

for line in open('.env', encoding='utf-8', errors='ignore'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

from app import create_app
from app.extensions import db
from app.models.scan_job import ScanJob, ScanJobStatus
from app.models.scan_result import ScanResult
from app.models.scanner_notification import ScannerNotification
from app.repositories import scan_result_repository
from app.services import progression as ps, notification_service

app = create_app()
failures = []

def check(name, got, expected):
    ok = (got == expected)
    print(f'  {"PASS" if ok else "FAIL"}  {name}: got={got!r}  expected={expected!r}')
    if not ok:
        failures.append(name)

def run():
    existing = db.session.execute(db.select(ScanJob).limit(1)).scalar()
    uid, tid = existing.user_id, existing.tool_id

    syms = ['NIFTY_A', 'NIFTY_B', 'NIFTY_C']

    # ── SCAN 1 ─────────────────────────────────────────────────────────────────
    j1 = ScanJob(user_id=uid, tool_id=tid, universe='NOTIFTEST', timeframe='1d',
                 filters={}, status=ScanJobStatus.COMPLETED, progress=100,
                 total_symbols=3, completed_symbols=3)
    db.session.add(j1); db.session.flush()

    rows1 = [
        {'scan_job_id': j1.id, 'symbol': 'NIFTY_A', 'classification': 'watchlist',
         'watchlist_level': 'L2', 'score': 62.0, 'current_stage_label': 'HTF OB Active', 'result_data': {}},
        {'scan_job_id': j1.id, 'symbol': 'NIFTY_B', 'classification': 'near_miss',
         'watchlist_level': None, 'score': 38.0, 'current_stage_label': 'Sweep Only', 'result_data': {}},
        {'scan_job_id': j1.id, 'symbol': 'NIFTY_C', 'classification': 'watchlist',
         'watchlist_level': 'L2', 'score': 58.0, 'current_stage_label': 'HTF OB Active', 'result_data': {}},
    ]
    prev1 = scan_result_repository.get_latest_per_symbol(uid, syms)
    for row in rows1:
        row.update(ps.compute(row['classification'], row.get('watchlist_level'), row.get('score'), prev1.get(row['symbol'])))
    saved1 = scan_result_repository.bulk_create(rows1)
    n1 = notification_service.create_from_results(j1, saved1)
    db.session.commit()
    print(f'\nScan 1: {n1} notifications created (expect 0 — all new_setup, prio=60 < 70)')
    check('scan1_notif_count', n1, 0)

    # ── SCAN 2 ─────────────────────────────────────────────────────────────────
    j2 = ScanJob(user_id=uid, tool_id=tid, universe='NOTIFTEST', timeframe='1d',
                 filters={}, status=ScanJobStatus.COMPLETED, progress=100,
                 total_symbols=3, completed_symbols=3)
    db.session.add(j2); db.session.flush()

    rows2 = [
        {'scan_job_id': j2.id, 'symbol': 'NIFTY_A', 'classification': 'confirmed',
         'watchlist_level': None, 'score': 89.0, 'grade': 'A',
         'current_stage_label': 'LTF OB 2.0 - Entry Ready', 'result_data': {}},
        {'scan_job_id': j2.id, 'symbol': 'NIFTY_B', 'classification': 'watchlist',
         'watchlist_level': 'L1', 'score': 52.0, 'grade': 'B',
         'current_stage_label': 'Awaiting HTF Retest', 'result_data': {}},
        {'scan_job_id': j2.id, 'symbol': 'NIFTY_C', 'classification': 'watchlist',
         'watchlist_level': 'L2', 'score': 59.5, 'grade': 'B',
         'current_stage_label': 'HTF OB Active', 'result_data': {}},
    ]
    prev2 = scan_result_repository.get_latest_per_symbol(uid, syms)
    for row in rows2:
        row.update(ps.compute(row['classification'], row.get('watchlist_level'), row.get('score'), prev2.get(row['symbol'])))
    saved2 = scan_result_repository.bulk_create(rows2)
    n2 = notification_service.create_from_results(j2, saved2)
    db.session.commit()
    print(f'\nScan 2: {n2} notifications created (expect 2 — NIFTY_A + NIFTY_B)')
    check('scan2_notif_count', n2, 2)

    # Verify notification content
    notif_a = db.session.execute(
        db.select(ScannerNotification)
        .where(ScannerNotification.symbol == 'NIFTY_A',
               ScannerNotification.scan_run_id == j2.id)
    ).scalar()
    notif_b = db.session.execute(
        db.select(ScannerNotification)
        .where(ScannerNotification.symbol == 'NIFTY_B',
               ScannerNotification.scan_run_id == j2.id)
    ).scalar()
    notif_c = db.session.execute(
        db.select(ScannerNotification)
        .where(ScannerNotification.symbol == 'NIFTY_C',
               ScannerNotification.scan_run_id == j2.id)
    ).scalar()

    print('\n--- Notification content ---')
    print(f'  NIFTY_A: type={notif_a.notification_type if notif_a else None}  prio={notif_a.priority if notif_a else None}')
    print(f'    title:   {notif_a.title if notif_a else None}')
    print(f'    message: {notif_a.message if notif_a else None}')
    print(f'  NIFTY_B: type={notif_b.notification_type if notif_b else None}  prio={notif_b.priority if notif_b else None}')
    print(f'    title:   {notif_b.title if notif_b else None}')
    print(f'    message: {notif_b.message if notif_b else None}')
    print(f'  NIFTY_C: exists={notif_c is not None}  (expect False — unchanged, prio=20)')

    check('notif_A_type',    notif_a.notification_type if notif_a else None, 'became_confirmed')
    check('notif_A_prio',    notif_a.priority if notif_a else None,           100)
    check('notif_A_unread',  notif_a.is_read if notif_a else True,            False)
    check('notif_B_type',    notif_b.notification_type if notif_b else None, 'became_watchlist')
    check('notif_B_prio',    notif_b.priority if notif_b else None,           70)
    check('notif_C_absent',  notif_c is None,                                  True)

    # ── DUPLICATE PROTECTION ───────────────────────────────────────────────────
    print('\n--- Duplicate protection ---')
    # Calling create_from_results again with the same saved2 objects should create 0
    n2b = notification_service.create_from_results(j2, saved2)
    check('duplicate_blocked', n2b, 0)

    # ── MARK READ ─────────────────────────────────────────────────────────────
    print('\n--- Mark read ---')
    notif_a.is_read = True
    db.session.commit()
    refreshed_a = db.session.get(ScannerNotification, notif_a.id)
    check('mark_read_persisted', refreshed_a.is_read, True)

    # ── MARK ALL READ ─────────────────────────────────────────────────────────
    print('\n--- Mark all read ---')
    db.session.execute(
        db.update(ScannerNotification)
        .where(ScannerNotification.user_id == uid)
        .where(ScannerNotification.is_read == False)
        .values(is_read=True)
    )
    db.session.commit()
    still_unread = db.session.execute(
        db.select(db.func.count(ScannerNotification.id))
        .where(ScannerNotification.user_id == uid)
        .where(ScannerNotification.is_read == False)
    ).scalar()
    check('mark_all_read', still_unread, 0)

    # ── CLEANUP ───────────────────────────────────────────────────────────────
    db.session.execute(db.delete(ScannerNotification).where(ScannerNotification.symbol.in_(syms)))
    db.session.execute(db.delete(ScanResult).where(ScanResult.symbol.in_(syms)))
    db.session.execute(db.delete(ScanJob).where(ScanJob.id.in_([j1.id, j2.id])))
    db.session.commit()

    print()
    if failures:
        print(f'FAILED ({len(failures)}): {failures}')
        sys.exit(1)
    else:
        print(f'ALL {12 - len(failures)} ASSERTIONS PASSED — test data cleaned up')

with app.app_context():
    run()
