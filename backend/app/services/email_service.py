"""
Brevo transactional email service.

Uses only Python stdlib (urllib + json) — no extra pip dependency.
The Brevo API key is read from Flask app config at call time,
never at import time, so this module is safe to import anywhere.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"

# ── Purpose → subject map ─────────────────────────────────────────────────────

_SUBJECTS = {
    "signup":          "Verify your Stop Hunter Pro account",
    "forgot_password": "Reset your Stop Hunter Pro password",
    "email_change":    "Confirm your new Stop Hunter Pro email",
}

# ── HTML templates ────────────────────────────────────────────────────────────

def _build_html(otp: str, purpose: str, expires_minutes: int) -> str:
    purpose_line = {
        "signup":          "You requested to create a Stop Hunter Pro account.",
        "forgot_password": "You requested a password reset for your Stop Hunter Pro account.",
        "email_change":    "You requested to change the email on your Stop Hunter Pro account.",
    }.get(purpose, "You requested an action on your Stop Hunter Pro account.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0" />
  <title>Your OTP</title>
</head>
<body style="margin:0;padding:0;background:#050810;font-family:Inter,ui-sans-serif,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#050810;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="480" cellpadding="0" cellspacing="0"
               style="background:#10131c;border:1px solid rgba(255,255,255,0.08);border-radius:16px;overflow:hidden;max-width:480px;width:100%;">

          <!-- Accent bar -->
          <tr>
            <td style="height:3px;background:linear-gradient(90deg,#0066ff,#00f1fe);"></td>
          </tr>

          <!-- Header -->
          <tr>
            <td style="padding:32px 36px 0;text-align:center;">
              <div style="display:inline-flex;align-items:center;gap:10px;margin-bottom:20px;">
                <div style="width:36px;height:36px;background:#0066ff;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;">
                  <span style="color:#fff;font-size:18px;font-weight:700;">&#9889;</span>
                </div>
                <span style="font-family:'Space Grotesk',ui-sans-serif,sans-serif;font-size:13px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#e1e2ee;">
                  Stop Hunter Pro
                </span>
              </div>
              <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#e1e2ee;letter-spacing:-0.01em;">
                Your verification code
              </h1>
              <p style="margin:0;font-size:14px;color:#8c90a1;line-height:1.6;">
                {purpose_line}
              </p>
            </td>
          </tr>

          <!-- OTP box -->
          <tr>
            <td style="padding:28px 36px;">
              <div style="background:#0d1122;border:1px solid rgba(0,102,255,0.35);border-radius:12px;padding:24px;text-align:center;">
                <p style="margin:0 0 8px;font-size:11px;font-family:'Space Grotesk',ui-sans-serif,sans-serif;letter-spacing:0.14em;text-transform:uppercase;color:#8c90a1;">
                  One-Time Password
                </p>
                <div style="font-size:40px;font-weight:700;letter-spacing:0.18em;color:#b3c5ff;font-family:'Space Grotesk',ui-sans-serif,monospace;">
                  {otp}
                </div>
                <p style="margin:12px 0 0;font-size:12px;color:#8c90a1;">
                  Expires in <strong style="color:#f59e0b;">{expires_minutes} minutes</strong>
                </p>
              </div>
            </td>
          </tr>

          <!-- Info rows -->
          <tr>
            <td style="padding:0 36px 28px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding:8px 0;border-top:1px solid rgba(255,255,255,0.06);">
                    <p style="margin:0;font-size:13px;color:#c2c6d8;line-height:1.6;">
                      &#128274;&nbsp; <strong>Do not share this OTP</strong> with anyone.
                      Stop Hunter Pro staff will never ask for it.
                    </p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:8px 0;border-top:1px solid rgba(255,255,255,0.06);">
                    <p style="margin:0;font-size:13px;color:#8c90a1;line-height:1.6;">
                      If you did not request this, you can safely ignore this email.
                      No action is needed on your account.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 36px 28px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
              <p style="margin:0;font-size:11px;color:#424656;font-family:'Space Grotesk',ui-sans-serif,sans-serif;letter-spacing:0.04em;">
                Stop Hunter Pro &middot; NSE / BSE &middot; India market hours
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_text(otp: str, purpose: str, expires_minutes: int) -> str:
    return (
        f"Stop Hunter Pro — Your OTP\n\n"
        f"Your one-time password is: {otp}\n\n"
        f"This OTP expires in {expires_minutes} minutes.\n\n"
        f"Do NOT share this code with anyone. Stop Hunter Pro staff will never ask for it.\n\n"
        f"If you did not request this, ignore this email — no action is needed.\n\n"
        f"— Stop Hunter Pro Team"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def send_transactional_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
    text_content: str = None,
) -> bool:
    """
    Send one transactional email via the Brevo v3 SMTP API.

    Returns True on success, False on any delivery failure.
    Never raises — callers decide what to do with a False return.
    Never logs the API key.
    """
    api_key      = current_app.config.get("BREVO_API_KEY", "")
    sender_email = current_app.config.get("BREVO_SENDER_EMAIL", "")
    sender_name  = current_app.config.get("BREVO_SENDER_NAME", "Stop Hunter Pro")
    is_dev       = os.getenv("FLASK_ENV", "development") == "development"

    if not api_key or not sender_email:
        current_app.logger.error(
            "[email_service] BREVO_API_KEY or BREVO_SENDER_EMAIL is not configured."
        )
        return False

    payload = {
        "sender":       {"name": sender_name, "email": sender_email},
        "to":           [{"email": to_email, "name": to_name}],
        "subject":      subject,
        "htmlContent":  html_content,
    }
    if text_content:
        payload["textContent"] = text_content

    body = json.dumps(payload).encode("utf-8")
    req  = Request(
        _BREVO_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "accept":       "application/json",
            "content-type": "application/json",
            "api-key":      api_key,          # never echoed in logs below
        },
    )

    try:
        with urlopen(req, timeout=10) as resp:
            status = resp.status
            if is_dev:
                current_app.logger.debug(
                    "[email_service] Brevo accepted email to %s — HTTP %s", to_email, status
                )
            return True

    except HTTPError as exc:
        if is_dev:
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = "<unreadable>"
            current_app.logger.warning(
                "[email_service] Brevo HTTP %s for %s — %s",
                exc.code, to_email, body_text,
            )
        else:
            current_app.logger.error(
                "[email_service] Brevo delivery failed (HTTP %s) for %s",
                exc.code, to_email,
            )
        return False

    except URLError as exc:
        current_app.logger.error(
            "[email_service] Brevo network error for %s — %s", to_email, exc.reason
        )
        return False

    except Exception as exc:
        current_app.logger.error(
            "[email_service] Unexpected error sending to %s — %s", to_email, exc
        )
        return False


def send_scanner_alert_email(
    to_email: str,
    to_name: str,
    notification,           # ScannerNotification ORM object
    dashboard_url: str = "",
) -> tuple[bool, str | None]:
    """
    Build and send a scanner alert email for a tracked-symbol notification.

    Returns (sent: bool, error: str | None).
    Never raises.
    """
    api_key      = current_app.config.get("BREVO_API_KEY", "")
    sender_email = current_app.config.get("BREVO_SENDER_EMAIL", "")

    if not api_key or not sender_email:
        current_app.logger.warning(
            "[email_service] scanner alert skipped — BREVO not configured"
        )
        return False, "BREVO_NOT_CONFIGURED"

    subject      = f"Stop Hunter Pro: {notification.title}"
    html_content = _build_scanner_alert_html(notification, dashboard_url)
    text_content = _build_scanner_alert_text(notification, dashboard_url)

    ok = send_transactional_email(
        to_email     = to_email,
        to_name      = to_name,
        subject      = subject,
        html_content = html_content,
        text_content = text_content,
    )
    return (True, None) if ok else (False, "SEND_FAILED")


# ── Scanner alert HTML ─────────────────────────────────────────────────────────

_TYPE_LABEL = {
    "became_confirmed": "Confirmed ✓",
    "improved_level":   "Level Improved ↑",
    "became_watchlist": "Watchlist ◉",
    "degraded_level":   "Degraded ↓",
    "became_near_miss": "Became Near Miss",
}
_TYPE_COLOR = {
    "became_confirmed": "#00d97e",
    "improved_level":   "#00f1fe",
    "became_watchlist": "#b3c5ff",
    "degraded_level":   "#f59e0b",
    "became_near_miss": "#ff4d4f",
}


def _build_scanner_alert_html(notification, dashboard_url: str) -> str:
    n          = notification
    type_label = _TYPE_LABEL.get(n.notification_type, n.notification_type.replace("_", " ").title())
    accent_col = _TYPE_COLOR.get(n.notification_type, "#0066ff")
    scope_badge = (
        '<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
        'background:rgba(0,241,254,0.12);color:#00f1fe;font-size:11px;font-weight:700;">📋 Tracked</span>'
        if n.notification_scope == "tracked" else ""
    )
    dashboard_btn = (
        f'<tr><td style="padding:20px 36px 0;text-align:center;">'
        f'<a href="{dashboard_url}" target="_blank" '
        f'style="display:inline-block;padding:12px 28px;border-radius:10px;'
        f'background:linear-gradient(90deg,#0066ff,#005ce6);color:#fff;'
        f'font-size:13px;font-weight:700;text-decoration:none;letter-spacing:0.03em;">'
        f'Open Dashboard →</a></td></tr>'
    ) if dashboard_url else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0" />
  <title>{n.title}</title>
</head>
<body style="margin:0;padding:0;background:#050810;font-family:Inter,ui-sans-serif,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#050810;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="500" cellpadding="0" cellspacing="0"
               style="background:#10131c;border:1px solid rgba(255,255,255,0.08);border-radius:16px;overflow:hidden;max-width:500px;width:100%;">

          <!-- Accent bar -->
          <tr>
            <td style="height:3px;background:linear-gradient(90deg,{accent_col},{accent_col}aa);"></td>
          </tr>

          <!-- Header -->
          <tr>
            <td style="padding:28px 36px 20px;">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                <div style="display:inline-block;width:32px;height:32px;background:#0066ff;border-radius:8px;text-align:center;line-height:32px;">
                  <span style="color:#fff;font-size:16px;font-weight:700;">&#9889;</span>
                </div>
                <span style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#8c90a1;">
                  Stop Hunter Pro
                </span>
              </div>
              <h1 style="margin:0 0 6px;font-size:22px;font-weight:800;color:#e1e2ee;letter-spacing:-0.02em;">
                {n.symbol}
              </h1>
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="display:inline-block;padding:3px 11px;border-radius:20px;
                      background:{accent_col}18;border:1px solid {accent_col}38;
                      color:{accent_col};font-size:12px;font-weight:700;">
                  {type_label}
                </span>
                {scope_badge}
              </div>
            </td>
          </tr>

          <!-- Message box -->
          <tr>
            <td style="padding:0 36px 20px;">
              <div style="background:#0d1122;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:18px 20px;">
                <p style="margin:0;font-size:14px;color:#c2c6d8;line-height:1.7;">
                  {n.message}
                </p>
              </div>
            </td>
          </tr>

          <!-- Details table -->
          <tr>
            <td style="padding:0 36px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border:1px solid rgba(255,255,255,0.06);border-radius:10px;overflow:hidden;">
                {_detail_row("Symbol",   n.symbol,             first=True)}
                {_detail_row("Event",    type_label)}
                {_detail_row("Priority", str(n.priority))}
                {_detail_row("Scope",    n.notification_scope.title())}
              </table>
            </td>
          </tr>

          {dashboard_btn}

          <!-- Footer -->
          <tr>
            <td style="padding:20px 36px 28px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;margin-top:8px;">
              <p style="margin:0;font-size:11px;color:#3a3f52;letter-spacing:0.04em;">
                Stop Hunter Pro &middot; NSE / BSE &middot; India market hours
              </p>
              <p style="margin:6px 0 0;font-size:10px;color:#2e3245;">
                You received this because you are tracking {n.symbol} with email alerts enabled.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _detail_row(label: str, value: str, first: bool = False) -> str:
    border = "" if first else "border-top:1px solid rgba(255,255,255,0.05);"
    return (
        f'<tr>'
        f'<td style="padding:9px 14px;{border}font-size:11px;'
        f'color:#5a5f72;text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;">{label}</td>'
        f'<td style="padding:9px 14px;{border}font-size:12px;font-weight:600;color:#c2c6d8;text-align:right;">{value}</td>'
        f'</tr>'
    )


def _build_scanner_alert_text(notification, dashboard_url: str) -> str:
    n = notification
    lines = [
        "Stop Hunter Pro — Scanner Alert",
        "=" * 40,
        f"Symbol:  {n.symbol}",
        f"Event:   {_TYPE_LABEL.get(n.notification_type, n.notification_type)}",
        f"Scope:   {n.notification_scope}",
        f"Priority:{n.priority}",
        "",
        n.message,
    ]
    if dashboard_url:
        lines += ["", f"Open Dashboard: {dashboard_url}"]
    lines += [
        "",
        "—",
        f"You received this because you are tracking {n.symbol} with email alerts enabled.",
        "Stop Hunter Pro",
    ]
    return "\n".join(lines)


def send_otp_email(to_email: str, otp: str, purpose: str = "signup") -> bool:
    """
    Build and send the OTP email for a given purpose.

    Returns True if Brevo accepted the message, False otherwise.
    """
    expires_minutes = current_app.config.get("OTP_EXPIRES_MINUTES", 10)
    subject         = _SUBJECTS.get(purpose, "Your Stop Hunter Pro OTP")
    html_content    = _build_html(otp, purpose, expires_minutes)
    text_content    = _build_text(otp, purpose, expires_minutes)

    return send_transactional_email(
        to_email     = to_email,
        to_name      = to_email,       # name not available here; email is fine
        subject      = subject,
        html_content = html_content,
        text_content = text_content,
    )
