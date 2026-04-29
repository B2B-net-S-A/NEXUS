"""Minimalny wrapper do wysyłki emaili przez SMTP.

Feature-gated przez `settings.SMTP_ENABLED` — gdy off, każda funkcja jest
no-op'em i tylko loguje. Dzięki temu można dokleić wysyłkę wszędzie bez
ryzyka wywalenia runtime gdy env nie jest skonfigurowane (dev, CI).

V1: plaintext + optional HTML. Bez kolejkowania — jeśli SMTP padnie, log
warning i idź dalej (email to fallback kanał, nie critical path).

Zależności: standardowy `smtplib` z biblioteki stdlib. Jeśli pojawi się
potrzeba async — przerobimy na `aiosmtplib` + do requirements.txt.
"""

from __future__ import annotations

import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_message(
    to: str, subject: str, text_body: str, html_body: Optional[str] = None
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> bool:
    """Wyślij email. Zwraca True gdy SMTP potwierdził, False gdy no-op lub błąd.

    Nie rzuca wyjątków — wszystko loguje i zwraca bool. Wynik można zignorować
    w ścieżkach fallback.
    """
    if not settings.SMTP_ENABLED:
        logger.debug(
            "email: SMTP_ENABLED=false — skip send to=%s subject=%r", to, subject
        )
        return False
    if not settings.SMTP_HOST:
        logger.warning(
            "email: SMTP_ENABLED=true but SMTP_HOST is empty — skipping to=%s", to
        )
        return False

    msg = _build_message(to, subject, text_body, html_body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as client:
            if settings.SMTP_USE_TLS:
                client.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            client.send_message(msg)
        logger.info("email sent to=%s subject=%r", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("email send failed to=%s subject=%r error=%s", to, subject, exc)
        return False


def send_post_interview_reminder(
    to_email: str,
    recipient_name: str,
    candidate_id: int,
    calendar_event_id: int,
    side: str,
    frontend_url_base: str,
) -> bool:
    """Wrapper z templatem dla post-interview T+45 reminderu."""
    subject = f"Zadzwoń i zbierz feedback — kandydat #{candidate_id}"
    side_label = "klienta" if side == "client_side" else "kandydata"
    link = f"{frontend_url_base}/calendar?event={calendar_event_id}&action=feedback"

    text_body = (
        f"Cześć {recipient_name},\n\n"
        f"Już 45 min od interview z kandydatem #{candidate_id}. "
        f"Zadzwoń do {side_label} i zbierz feedback + pytania.\n\n"
        f"Otwórz modal feedbacku:\n{link}\n\n"
        "— Nexus ATS"
    )
    html_body = (
        f"<p>Cześć {recipient_name},</p>"
        f"<p>Już 45 min od interview z kandydatem <strong>#{candidate_id}</strong>. "
        f"Zadzwoń do <strong>{side_label}</strong> i zbierz feedback + pytania.</p>"
        f'<p><a href="{link}">Otwórz modal feedbacku</a></p>'
        '<hr><p style="color:#888;font-size:12px">Nexus ATS</p>'
    )
    return send_email(to_email, subject, text_body, html_body)


def send_mention_email(
    *,
    to_email: str,
    recipient_name: str,
    author_name: str,
    snippet: str,
    deep_link_path: str,
    context_label: str,
) -> bool:
    """Wysyła notyfikację email gdy ktoś @mention'uje usera w notatce.

    Args:
        to_email: adres email odbiorcy
        recipient_name: imię (lub email) odbiorcy do wstawienia w "Cześć X"
        author_name: imię (lub email) osoby która oznaczyła
        snippet: skrócony fragment treści notatki (≤140 znaków preferowane)
        deep_link_path: ścieżka URL względna od PUBLIC_BASE_URL,
            np. "/candidates/123?tab=notes&note=456"
        context_label: human-readable kontekst, np. "notatce o kandydacie",
            "notatce ze screeningu"

    Wraca `True` gdy SMTP potwierdził, `False` gdy no-op (SMTP off) lub błąd.

    HTML body sanitizes user-controlled content via html.escape() —
    zapobiega XSS gdy ktoś wpisze `<script>` w nazwie usera lub w notatce.
    Plain text leg jest naturalnie safe.
    """
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    link = f"{base}{deep_link_path}" if base else deep_link_path

    subject = f"[Nexus] {author_name} oznaczył(a) Cię w notatce"

    text_body = (
        f"Cześć {recipient_name},\n\n"
        f"{author_name} oznaczył(a) Cię w {context_label}:\n\n"
        f"{snippet}\n\n"
        f"Otwórz w Nexusie: {link}\n\n"
        "— Nexus ATS"
    )

    safe_author = html.escape(author_name)
    safe_recipient = html.escape(recipient_name)
    safe_snippet = html.escape(snippet)
    safe_context = html.escape(context_label)
    safe_link = html.escape(link, quote=True)

    html_body = (
        f"<p>Cześć {safe_recipient},</p>"
        f"<p><strong>{safe_author}</strong> oznaczył(a) Cię w {safe_context}:</p>"
        f'<blockquote style="border-left:3px solid #3b82f6;padding-left:12px;'
        f'color:#374151;margin:16px 0">{safe_snippet}</blockquote>'
        f'<p><a href="{safe_link}" style="display:inline-block;background:#2563eb;'
        f"color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;"
        f'font-weight:500">Otwórz w Nexusie</a></p>'
        '<hr><p style="color:#888;font-size:12px">Nexus ATS</p>'
    )
    return send_email(to_email, subject, text_body, html_body)


def send_chat_fallback_email(
    *,
    to_email: str,
    recipient_name: str,
    notification_title: str,
    notification_message: str,
    deep_link_path: str,
) -> bool:
    """Email fallback dla chatów (>15 min offline).

    Używana z `tasks/chat_email_fallback.py`. Prostszy template niż
    send_mention_email — pokazuje tytuł + wiadomość bez quotation.
    """
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    link = f"{base}{deep_link_path}" if base else deep_link_path

    subject = f"[Nexus] {notification_title}"

    text_body = (
        f"Cześć {recipient_name},\n\n"
        f"{notification_title}\n\n"
        f"{notification_message}\n\n"
        f"Otwórz w Nexusie: {link}\n\n"
        "— Nexus ATS"
    )

    safe_recipient = html.escape(recipient_name)
    safe_title = html.escape(notification_title)
    safe_message = html.escape(notification_message)
    safe_link = html.escape(link, quote=True)

    html_body = (
        f"<p>Cześć {safe_recipient},</p>"
        f"<p><strong>{safe_title}</strong></p>"
        f"<p>{safe_message}</p>"
        f'<p><a href="{safe_link}" style="display:inline-block;background:#2563eb;'
        f"color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;"
        f'font-weight:500">Otwórz w Nexusie</a></p>'
        '<hr><p style="color:#888;font-size:12px">Nexus ATS</p>'
    )
    return send_email(to_email, subject, text_body, html_body)
