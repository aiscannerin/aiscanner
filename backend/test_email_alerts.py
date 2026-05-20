"""
Email alert validation test.

Tests:
  1. BREVO not configured → notification created, email_sent=False, email_error='BREVO_NOT_CONFIGURED'
  2. BREVO mocked (patched) → notification created, email_sent=True, email_sent_at set
  3. Duplicate send attempt → skipped (email_sent=True guard)
  4. email_alerts_enabled=False → no send attempted
  5. global-scope notification → no email sent
  6. tracked-scope notification with email enabled → send attempted
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
from app.models.user_alert_settings import UserAlertSettings
from app.models.user_tracked_symbol import UserTrackedSymbol
from app.repositories import scan_result_repository, user_tracked_symbol_repository as wrepo
from app.repositories import user_alert_settings_repository as asrepo
from app.services import progression as ps, notification_service

app = create_app()
failures = []
call_log = []   # captures patched send calls

def check(name, got, expected):
    ok = (got == expected)
    print(f'  {"PASS" if ok else "FAIL"}  {name}: got={got!r}  expected={expected!r}')
    if not ok:
        failures.append(name)

def make_job(uid, tid):
    j = ScanJob(user_id=uid, tool_id=tid, universe='EMAILTEST', timeframe='1d',
                filters={}, status=ScanJobStatus.COMPLETED, progress=100,
                total_symbols=1, completed_symbols=1)
    db.session.add(j); db.session.flush()
    return j

def seed_watchlist(uid, symbol='EMAIL_A'):
    entry = wrepo.create(uid, symbol, 'Stop Hunter Pro', '1d', None, None)
    return entry

def scan_progress(uid, tid, symbol, from_cl, from_wl, to_cl, to_wl, score):
    """Seed a prev result then run a job that transitions to to_cl."""
    # Seed previous result
    j_prev = make_job(uid, tid)
    prev_map = scan_result_repository.get_latest_per_symbol(uid, [symbol])
    r_prev = {'scan_job_id': j_prev.id, 'symbol': symbol,
              'classification': from_cl, 'watchlist_level': from_wl,
              'score': 50.0, 'grade':'B', 'current_stage_label':'Prior', 'result_data': {}}
    r_prev.update(ps.compute(from_cl, from_wl, 50.0, prev_map.get(symbol)))
    scan_result_repository.bulk_create([r_prev])
    db.session.commit()

    # Run target job
    j = make_job(uid, tid)
    prev2 = scan_result_repository.get_latest_per_symbol(uid, [symbol])
    row = {'scan_job_id': j.id, 'symbol': symbol,
           'classification': to_cl, 'watchlist_level': to_wl,
           'score': score, 'grade':'A', 'current_stage_label':'Test Stage', 'result_data': {}}
    row.update(ps.compute(to_cl, to_wl, score, prev2.get(symbol)))
    saved = scan_result_repository.bulk_create([row])
    return j, saved, [j_prev.id, j.id]

def run():
    from unittest.mock import patch

    existing = db.session.execute(db.select(ScanJob).limit(1)).scalar()
    uid, tid = existing.user_id, existing.tool_id
    syms = ['EMAIL_A', 'EMAIL_B']
    all_job_ids = []

    # ── Setup: track EMAIL_A, NOT EMAIL_B ─────────────────────────────────────
    tracked_a = seed_watchlist(uid, 'EMAIL_A')

    # ── Test 1: BREVO not configured → email_error = BREVO_NOT_CONFIGURED ─────
    print('\n--- Test 1: BREVO not configured ---')
    settings = asrepo.upsert(uid, email_alerts_enabled=True, email_address='test@example.com')
    check('email_enabled_saved', settings.email_alerts_enabled, True)

    j1, saved1, jids1 = scan_progress(uid, tid, 'EMAIL_A', 'near_miss', None, 'watchlist', 'L1', 65.0)
    all_job_ids += jids1
    # Force BREVO_NOT_CONFIGURED by clearing config keys
    with app.app_context():
        app.config['BREVO_API_KEY'] = ''
        app.config['BREVO_SENDER_EMAIL'] = ''
        n1 = notification_service.create_from_results(j1, saved1)

    notif1 = db.session.execute(
        db.select(ScannerNotification)
        .where(ScannerNotification.symbol == 'EMAIL_A',
               ScannerNotification.scan_run_id == j1.id)
    ).scalar()
    check('t1_notif_created',   n1 >= 1,                                 True)
    check('t1_email_sent_false',notif1.email_sent if notif1 else True,   False)
    check('t1_email_error',     notif1.email_error if notif1 else None,  'BREVO_NOT_CONFIGURED')
    check('t1_scope_tracked',   notif1.notification_scope if notif1 else None, 'tracked')

    # ── Test 2: BREVO mocked → email_sent=True ────────────────────────────────
    print('\n--- Test 2: BREVO mocked → email_sent=True ---')

    def mock_send(to_email, to_name, notification, dashboard_url=''):
        call_log.append({'to': to_email, 'title': notification.title, 'scope': notification.notification_scope})
        return True, None

    j2, saved2, jids2 = scan_progress(uid, tid, 'EMAIL_A', 'watchlist', 'L1', 'confirmed', None, 88.0)
    all_job_ids += jids2

    with patch('app.services.email_service.send_scanner_alert_email', side_effect=mock_send):
        n2 = notification_service.create_from_results(j2, saved2)

    notif2 = db.session.execute(
        db.select(ScannerNotification)
        .where(ScannerNotification.symbol == 'EMAIL_A',
               ScannerNotification.scan_run_id == j2.id)
    ).scalar()
    check('t2_notif_created',   n2 >= 1,                                  True)
    check('t2_email_sent_true', notif2.email_sent if notif2 else False,   True)
    check('t2_email_sent_at',   notif2.email_sent_at is not None if notif2 else False, True)
    check('t2_email_error_none',notif2.email_error if notif2 else 'ERR',  None)
    check('t2_call_logged',     len(call_log) >= 1,                       True)
    if call_log:
        check('t2_call_to',     call_log[-1]['to'],   'test@example.com')
        check('t2_call_scope',  call_log[-1]['scope'], 'tracked')

    # ── Test 3: Duplicate send blocked ────────────────────────────────────────
    print('\n--- Test 3: duplicate send blocked ---')
    before = len(call_log)
    # Manually attempt to re-trigger _send_emails_for_tracked on already-sent notif
    with patch('app.services.email_service.send_scanner_alert_email', side_effect=mock_send):
        notification_service._send_emails_for_tracked(uid, [notif2])
    check('t3_no_new_call', len(call_log), before)   # call_log unchanged

    # ── Test 4: email_alerts_enabled=False → no send ──────────────────────────
    print('\n--- Test 4: email disabled → no send ---')
    asrepo.upsert(uid, email_alerts_enabled=False)
    before4 = len(call_log)

    j4, saved4, jids4 = scan_progress(uid, tid, 'EMAIL_A', 'watchlist', 'L2', 'confirmed', None, 90.0)
    all_job_ids += jids4
    with patch('app.services.email_service.send_scanner_alert_email', side_effect=mock_send):
        notification_service.create_from_results(j4, saved4)
    check('t4_no_call', len(call_log), before4)

    # Re-enable for remaining tests
    asrepo.upsert(uid, email_alerts_enabled=True)

    # ── Test 5: global-scope notification → no email ──────────────────────────
    print('\n--- Test 5: global scope → no email ---')
    before5 = len(call_log)

    j5, saved5, jids5 = scan_progress(uid, tid, 'EMAIL_B', 'near_miss', None, 'confirmed', None, 91.0)
    all_job_ids += jids5
    with patch('app.services.email_service.send_scanner_alert_email', side_effect=mock_send):
        notification_service.create_from_results(j5, saved5)

    notif5 = db.session.execute(
        db.select(ScannerNotification)
        .where(ScannerNotification.symbol == 'EMAIL_B',
               ScannerNotification.scan_run_id == j5.id)
    ).scalar()
    check('t5_notif_global',    notif5.notification_scope if notif5 else None, 'global')
    check('t5_no_email_call',   len(call_log), before5)   # no new call for global

    # ── Test 6: tracked + email enabled → send attempted ─────────────────────
    print('\n--- Test 6: tracked + enabled → email sent ---')
    before6 = len(call_log)

    j6, saved6, jids6 = scan_progress(uid, tid, 'EMAIL_A', 'watchlist', 'L2', 'confirmed', None, 92.0)
    all_job_ids += jids6
    with patch('app.services.email_service.send_scanner_alert_email', side_effect=mock_send):
        n6 = notification_service.create_from_results(j6, saved6)
    check('t6_notif_created',   n6 >= 1,            True)
    check('t6_email_attempted', len(call_log) > before6, True)

    # ── cleanup ───────────────────────────────────────────────────────────────
    db.session.execute(db.delete(ScannerNotification).where(ScannerNotification.symbol.in_(syms)))
    db.session.execute(db.delete(ScanResult).where(ScanResult.symbol.in_(syms)))
    db.session.execute(db.delete(ScanJob).where(ScanJob.id.in_(all_job_ids)))
    db.session.execute(db.delete(UserTrackedSymbol).where(UserTrackedSymbol.user_id == uid, UserTrackedSymbol.symbol.in_(syms)))
    db.session.execute(db.delete(UserAlertSettings).where(UserAlertSettings.user_id == uid))
    db.session.commit()

    print()
    if failures:
        print(f'FAILED ({len(failures)}): {failures}')
        sys.exit(1)
    else:
        print(f'ALL ASSERTIONS PASSED — test data cleaned up')

with app.app_context():
    run()
