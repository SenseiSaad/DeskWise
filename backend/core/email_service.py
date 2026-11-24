"""Transactional email service with branded HTML + plain-text templates,
non-blocking delivery (transaction.on_commit + background retry thread),
and Resend HTTPS API / standard SMTP support.

Never raises into the request path and never logs credentials or raw tokens.
"""
from __future__ import annotations

import html
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction

logger = logging.getLogger(__name__)


def frontend_url(path: str = "") -> str:
    base = (
        getattr(settings, "FRONTEND_URL", "")
        or getattr(settings, "PUBLIC_BASE_URL", "")
        or "http://localhost:3000"
    ).rstrip("/")
    return f"{base}/{path.lstrip('/')}" if path else base


def _render_html_shell(title: str, intro: str, cta_label: str, cta_url: str, note: str) -> str:
    esc_title = html.escape(title)
    esc_intro = html.escape(intro)
    esc_cta = html.escape(cta_label)
    esc_url = html.escape(cta_url)
    esc_note = html.escape(note)
    support = html.escape(getattr(settings, "SUPPORT_EMAIL", "support@saadops.site"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{esc_title}</title>
</head>
<body style="margin:0;padding:24px 12px;background:#f5f3ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a1815;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:540px;margin:0 auto;background:#ffffff;border:1px solid #e6e1d6;border-radius:16px;overflow:hidden;">
    <tr>
      <td style="padding:28px 28px 16px 28px;border-bottom:1px solid #f0ece1;">
        <div style="font-size:12px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:#8c6a2f;">Deskwise</div>
        <h1 style="margin:10px 0 0 0;font-size:21px;line-height:1.3;color:#1a1815;">{esc_title}</h1>
      </td>
    </tr>
    <tr>
      <td style="padding:24px 28px;">
        <p style="margin:0 0 20px 0;font-size:14px;line-height:1.6;color:#3d3933;">{esc_intro}</p>
        {f'<p style="margin:0 0 22px 0;"><a href="{esc_url}" style="display:inline-block;background:#1a1815;color:#f3efe5;text-decoration:none;font-size:13px;font-weight:600;padding:12px 22px;border-radius:999px;">{esc_cta}</a></p>' if cta_url else ''}
        {f'<p style="margin:0 0 18px 0;font-size:12px;line-height:1.5;color:#6e685f;">Or copy and paste this link into your browser:<br /><a href="{esc_url}" style="color:#8c6a2f;word-break:break-all;">{esc_url}</a></p>' if cta_url else ''}
        <p style="margin:0;font-size:12px;line-height:1.5;color:#6e685f;">{esc_note}</p>
      </td>
    </tr>
    <tr>
      <td style="padding:16px 28px;background:#faf8f4;border-top:1px solid #f0ece1;font-size:11px;line-height:1.5;color:#8a8377;">
        Deskwise · Permission-locked company knowledge base.<br />
        Need help? Contact <a href="mailto:{support}" style="color:#8c6a2f;">{support}</a>.
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_email_content(kind: str, **ctx) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for one of the 5 auth templates."""
    company_name = ctx.get("company_name") or "your workspace"
    url = ctx.get("url") or frontend_url("/enterprise")

    if kind == "verify":
        subject = "Verify your Deskwise email"
        intro = f"Welcome to Deskwise. Confirm your email address within 24 hours to activate access to {company_name}."
        note = "This single-use link expires in 24 hours. If you did not create a Deskwise account, you can safely ignore this email."
        text = f"{intro}\n\nVerify your email:\n{url}\n\n{note}"
        return subject, text, _render_html_shell(subject, intro, "Verify email address", url, note)

    if kind == "reset":
        subject = "Reset your Deskwise password"
        intro = "We received a request to reset the password for your Deskwise account."
        note = "This single-use link expires in 30 minutes. If you did not request a password reset, ignore this email and your password will remain unchanged."
        text = f"{intro}\n\nReset your password within 30 minutes:\n{url}\n\n{note}"
        return subject, text, _render_html_shell(subject, intro, "Choose a new password", url, note)

    if kind == "invite":
        subject = f"You have been invited to {company_name} on Deskwise"
        intro = f"Your administrator invited you to join {company_name} on Deskwise."
        note = "This single-use invitation link is bound to your email address and expires in 7 days."
        text = f"{intro}\n\nAccept your invitation:\n{url}\n\n{note}"
        return subject, text, _render_html_shell(subject, intro, "Accept invitation", url, note)

    if kind == "password_changed":
        subject = "Your Deskwise password was changed"
        intro = "The password on your Deskwise account was just updated, and all previous sessions have been signed out."
        note = "If you made this change, no further action is needed. If you did not change your password, reset it immediately and contact your workspace administrator."
        forgot_url = frontend_url("/auth/forgot")
        text = f"{intro}\n\n{note}\n\nRecover account:\n{forgot_url}"
        return subject, text, _render_html_shell(subject, intro, "Reset password if this wasn't you", forgot_url, note)

    # Default: "welcome"
    subject = f"Welcome to {company_name} on Deskwise"
    intro = f"Your Deskwise account for {company_name} is active and ready to use."
    note = "Sign in with your work email to search approved company documents and ask cited questions."
    text = f"{intro}\n\nOpen workspace:\n{url}\n\n{note}"
    return subject, text, _render_html_shell(subject, intro, "Open Deskwise", url, note)


def _send_via_resend_api(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        return False
    payload = json.dumps({
        "from": settings.DEFAULT_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Deskwise/1.0",
        },
        method="POST",
    )
    timeout = min(int(getattr(settings, "EMAIL_TIMEOUT", 10) or 10), 15)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return 200 <= resp.status < 300


def _mask_email(addr: str) -> str:
    """Log-safe recipient: first character of the local part plus the domain."""
    local, _, domain = str(addr or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _deliver_now(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    """Attempt delivery up to 3 times with short backoff. Never raises."""
    attempts = 3 if getattr(settings, "EMAIL_ASYNC", False) else 1
    for attempt in range(1, attempts + 1):
        try:
            # Prefer Resend HTTPS API when RESEND_API_KEY is explicitly set in prod
            # and we are not using Django's in-memory test locmem backend.
            backend_name = getattr(settings, "EMAIL_BACKEND", "")
            if os.getenv("RESEND_API_KEY", "").strip() and "locmem" not in backend_name:
                if _send_via_resend_api(to_email, subject, text_body, html_body):
                    return True
            timeout = int(getattr(settings, "EMAIL_TIMEOUT", 10) or 10)
            conn = get_connection(fail_silently=False, timeout=timeout)
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
                connection=conn,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=False)
            return True
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:240]
            except Exception:
                pass
            logger.warning(
                "Resend HTTP %s on attempt %d/%d (to=%s, from=%s): %s",
                exc.code,
                attempt,
                attempts,
                _mask_email(to_email),
                settings.DEFAULT_FROM_EMAIL,
                err_body,
            )
            if attempt < attempts:
                time.sleep(0.4 * attempt)
        except Exception as exc:
            logger.warning(
                "Email delivery attempt %d/%d failed (to=%s, subject=%r, err=%s)",
                attempt,
                attempts,
                _mask_email(to_email),
                subject,
                type(exc).__name__,
            )
            if attempt < attempts:
                time.sleep(0.4 * attempt)
    return False


def send_auth_email(user_or_email, kind: str, **ctx) -> bool:
    """Queue or send a branded HTML + plain-text auth email.

    In production (`EMAIL_ASYNC=true`), schedules delivery on `transaction.on_commit`
    in a daemon thread so slow SMTP servers never hang or 500 the HTTP request.
    In tests / synchronous mode, delivers immediately so `mail.outbox` is populated.
    """
    to_email = (
        user_or_email.email
        if hasattr(user_or_email, "email")
        else str(user_or_email or "").strip()
    )
    if not to_email:
        return False
    subject, text_body, html_body = build_email_content(kind, **ctx)
    use_async = getattr(settings, "EMAIL_ASYNC", False) and "locmem" not in getattr(
        settings, "EMAIL_BACKEND", ""
    )
    if not use_async:
        return _deliver_now(to_email, subject, text_body, html_body)

    def _spawn():
        t = threading.Thread(
            target=_deliver_now,
            args=(to_email, subject, text_body, html_body),
            daemon=True,
        )
        t.start()

    try:
        transaction.on_commit(_spawn)
    except Exception:
        _spawn()
    return True
