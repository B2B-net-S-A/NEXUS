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
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_message(
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def email_channel_enabled() -> bool:
    """Czy jakikolwiek kanał wysyłki jest skonfigurowany (Graph app-only lub SMTP).

    Pozwala pre-gate'ować background taski (np. deadline alerts) bez zakładania
    konkretnego kanału — inaczej włączenie tylko Grapha zostawiłoby je uśpione
    na `if not SMTP_ENABLED`.
    """
    if settings.M365_APP_MAIL_ENABLED:
        # Import lokalny — unika cyklu email ↔ m365 i kosztu msal przy imporcie.
        # Gdy flaga Graph jest ON, Graph jest WYBRANYM kanałem — bez cichego
        # fallbacku na SMTP (spójnie z `send_email`, które routuje twardo na
        # Graph). Inaczej misconfig Graph + SMTP dostępny → `_dispatch_emails`
        # rezerwowałby wiersze, a `send_email` no-opował je w pętli.
        from app.services.m365.app_mail import is_configured

        return is_configured()
    return bool(settings.SMTP_ENABLED and settings.SMTP_HOST)


def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """Wyślij email. Zwraca True gdy kanał potwierdził, False gdy no-op lub błąd.

    ``reply_to`` — adres, na który pójdzie odpowiedź (zgody: skrzynka, którą
    czyta NEXUS, ``services/hr/approvals/mail_reader.py``).

    Routing: gdy `M365_APP_MAIL_ENABLED` — idzie przez Microsoft Graph app-only
    (stała skrzynka serwisowa), inaczej przez SMTP. Graph jest wybranym kanałem
    (nie fallbackuje na SMTP), więc jego wynik jest zwracany wprost. Nie rzuca
    wyjątków — wszystko loguje i zwraca bool.
    """
    if settings.M365_APP_MAIL_ENABLED:
        from app.services.m365.app_mail import send_via_graph_app

        return send_via_graph_app(
            to=to,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            reply_to=reply_to,
        )

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

    # P1.18: fail closed on TLS. With SMTP_REQUIRE_TLS (default True) we refuse
    # to send over plaintext, and STARTTLS uses a default SSL context that
    # verifies the server CA + hostname — no MITM, no silent cleartext fallback.
    if settings.SMTP_REQUIRE_TLS and not settings.SMTP_USE_TLS:
        logger.error(
            "email: SMTP_REQUIRE_TLS=true but SMTP_USE_TLS=false — refusing to "
            "send over plaintext to=%s",
            to,
        )
        return False

    msg = _build_message(to, subject, text_body, html_body, reply_to)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as client:
            if settings.SMTP_USE_TLS:
                client.starttls(context=ssl.create_default_context())
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            client.send_message(msg)
        logger.info("email sent to=%s subject=%r", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        # Redact: never log credentials or message body; the exception repr can
        # contain the server banner but not our secrets.
        logger.warning(
            "email send failed to=%s subject=%r error=%s",
            to,
            subject,
            type(exc).__name__,
        )
        return False


# USUNIĘTE: `send_post_interview_reminder()` — rusztowanie kanału SMTP dla
# alertów post-interview T+45, które nigdy nie zostało podpięte. Zero wywołań
# w `app/`, `scripts/` i `tests/`; `check_post_interview_t45` w
# `notification_triggers.py` emituje wyłącznie powiadomienie in-app. W dodatku
# funkcja była NIEPODPINALNA bez przeróbki: żądała argumentu
# `frontend_url_base`, a takiego ustawienia nie ma w `config.py` — reszta
# mailerów buduje linki z `settings.PUBLIC_BASE_URL`. Jeśli kanał mailowy dla
# T+45 ma powstać, pisze się go od nowa w konwencji `send_mention_email`
# (PUBLIC_BASE_URL) i podpina w `check_post_interview_t45` pod strażą
# `settings.SMTP_ENABLED` — martwy wrapper tylko udawał, że to już zrobiono.


def send_mention_email(
    *,
    to_email: str,
    recipient_name: str,
    author_name: str,
    snippet: str,
    deep_link_path: str,
    context_label: str,
    event_at: datetime | None = None,
    edited: bool = False,
) -> bool:
    """Wysyła notyfikację email gdy ktoś @mention'uje usera w notatce.

    ``edited``: autor zmienił notatkę, w której ta osoba już była oznaczona,
    i zaznaczył „Powiadom oznaczonych o zmianie” (21.10.2026).

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

    if edited:
        subject = f"[Nexus] {author_name} zmienił(a) notatkę, w której Cię oznaczył(a)"
        lead = (
            f"zmienił(a) treść w {context_label}, w której Cię oznaczył(a). Nowa treść"
        )
    else:
        subject = f"[Nexus] {author_name} oznaczył(a) Cię w notatce"
        lead = f"oznaczył(a) Cię w {context_label}"

    text_body = (
        f"Cześć {recipient_name},\n\n"
        f"{author_name} {lead}:\n\n"
        f"{snippet}\n\n"
        f"Otwórz w Nexusie: {link}\n\n"
        "— Nexus ATS"
    )

    safe_author = html.escape(author_name)
    safe_recipient = html.escape(recipient_name)
    safe_snippet = html.escape(snippet)
    safe_lead = html.escape(lead)
    safe_link = html.escape(link, quote=True)

    html_body = (
        f"<p>Cześć {safe_recipient},</p>"
        f"<p><strong>{safe_author}</strong> {safe_lead}:</p>"
        f'<blockquote style="border-left:3px solid #3b82f6;padding-left:12px;'
        f'color:#374151;margin:16px 0">{safe_snippet}</blockquote>'
        f'<p><a href="{safe_link}" style="display:inline-block;background:#2563eb;'
        f"color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;"
        f'font-weight:500">Otwórz w Nexusie</a></p>'
        '<hr><p style="color:#888;font-size:12px">Nexus ATS</p>'
    )
    from app.services.notification_delivery import guarded_send

    return guarded_send(
        "mentions", event_at, send_email, to_email, subject, text_body, html_body
    )


def send_password_reset_email(
    *,
    to_email: str,
    recipient_name: str,
    reset_url: str,
    expires_minutes: int = 60,
) -> bool:
    """Wysyła email z linkiem resetowym hasła.

    Args:
        to_email: adres email odbiorcy
        recipient_name: imię (lub email) odbiorcy do "Cześć X"
        reset_url: pełny URL z tokenem (np. https://nexus.dynaminds.pl/login/reset?token=...)
        expires_minutes: TTL linka (do treści maila — backend ustawia faktyczny TTL)

    Treść jest jednoznaczna: link, czas ważności, info "jeśli to nie ty —
    zignoruj". HTML body sanitizes user-controlled content via html.escape().
    """
    subject = "Resetowanie hasła w NEXUS"

    text_body = (
        f"Cześć {recipient_name},\n\n"
        f"Otrzymaliśmy prośbę o zresetowanie hasła do Twojego konta w NEXUS.\n\n"
        f"Aby ustawić nowe hasło, kliknij w poniższy link "
        f"(ważny przez {expires_minutes} minut):\n\n"
        f"{reset_url}\n\n"
        f"Jeśli to nie Ty prosiłeś(-aś) o reset hasła, zignoruj tę wiadomość — "
        f"Twoje konto pozostaje bezpieczne.\n\n"
        "— NEXUS · B2BNet"
    )

    safe_recipient = html.escape(recipient_name)
    safe_link = html.escape(reset_url, quote=True)

    html_body = (
        f"<p>Cześć {safe_recipient},</p>"
        f"<p>Otrzymaliśmy prośbę o zresetowanie hasła do Twojego konta w NEXUS.</p>"
        f'<p><a href="{safe_link}" style="display:inline-block;background:#2563eb;'
        f"color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;"
        f'font-weight:500">Ustaw nowe hasło</a></p>'
        f'<p style="color:#666;font-size:13px">Link jest ważny przez '
        f"<strong>{expires_minutes} minut</strong>. "
        f"Jeśli przycisk nie działa, skopiuj poniższy URL do przeglądarki:</p>"
        f'<p style="color:#666;font-size:12px;word-break:break-all">{safe_link}</p>'
        f'<hr><p style="color:#888;font-size:12px">Jeśli to nie Ty prosiłeś(-aś) '
        f"o reset hasła, zignoruj tę wiadomość — Twoje konto pozostaje bezpieczne.</p>"
        '<p style="color:#888;font-size:12px">NEXUS · B2BNet</p>'
    )
    return send_email(to_email, subject, text_body, html_body)


def send_email_verification_email(
    *,
    to_email: str,
    recipient_name: str,
    verify_url: str,
    expires_minutes: int = 60 * 24,
) -> bool:
    """Wysyła email z linkiem potwierdzającym adres po self-service rejestracji.

    Args:
        to_email: adres email odbiorcy (świeżo zarejestrowany).
        recipient_name: imię (lub email) odbiorcy do "Cześć X".
        verify_url: pełny URL z tokenem
            (np. https://nexus.dynaminds.pl/register/verify?token=...).
        expires_minutes: TTL linka (do treści maila — backend ustawia faktyczny
            TTL; default 24 h).

    Treść: link aktywacyjny + czas ważności + info "jeśli to nie Ty — zignoruj".
    HTML body sanitizes user-controlled content via ``html.escape()``.
    Best-effort: zwraca False (no-op) gdy SMTP wyłączony — rejestracja i tak
    kończy się sukcesem, user może poprosić o ponowny link.
    """
    subject = "Potwierdź swój adres email w NEXUS"

    text_body = (
        f"Cześć {recipient_name},\n\n"
        f"Dziękujemy za rejestrację w NEXUS. Aby aktywować konto, potwierdź "
        f"swój adres email klikając w poniższy link "
        f"(ważny przez {expires_minutes // 60} godzin):\n\n"
        f"{verify_url}\n\n"
        f"Po potwierdzeniu zalogujesz się i uzyskasz dostęp w trybie do "
        f"odczytu. O nadanie szerszych uprawnień poproś administratora.\n\n"
        f"Jeśli to nie Ty zakładałeś(-aś) konto, zignoruj tę wiadomość.\n\n"
        "— NEXUS · B2BNet"
    )

    safe_recipient = html.escape(recipient_name)
    safe_link = html.escape(verify_url, quote=True)

    html_body = (
        f"<p>Cześć {safe_recipient},</p>"
        f"<p>Dziękujemy za rejestrację w NEXUS. Aby aktywować konto, potwierdź "
        f"swój adres email:</p>"
        f'<p><a href="{safe_link}" style="display:inline-block;background:#2563eb;'
        f"color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;"
        f'font-weight:500">Potwierdź adres email</a></p>'
        f'<p style="color:#666;font-size:13px">Link jest ważny przez '
        f"<strong>{expires_minutes // 60} godzin</strong>. "
        f"Jeśli przycisk nie działa, skopiuj poniższy URL do przeglądarki:</p>"
        f'<p style="color:#666;font-size:12px;word-break:break-all">{safe_link}</p>'
        f'<p style="color:#666;font-size:13px">Po potwierdzeniu zalogujesz się '
        f"w trybie do odczytu. O nadanie szerszych uprawnień poproś "
        f"administratora.</p>"
        f'<hr><p style="color:#888;font-size:12px">Jeśli to nie Ty zakładałeś(-aś) '
        f"konto, zignoruj tę wiadomość.</p>"
        '<p style="color:#888;font-size:12px">NEXUS · B2BNet</p>'
    )
    return send_email(to_email, subject, text_body, html_body)


def send_password_changed_notification(
    *,
    to_email: str,
    recipient_name: str,
    by_admin: bool,
    admin_name: Optional[str] = None,
) -> bool:
    """Powiadomienie wysyłane *po* zmianie hasła — security audit trail.

    Wysyłane:
    - po self-service change-password (informacyjne, ``by_admin=False``)
    - po admin-resecie hasła (``by_admin=True``, ``admin_name`` wymagane)
    - po user-driven reset z tokenu (``by_admin=False``)

    Treść powiadomienia mówi *kiedy* i *przez kogo*, zachęca do reakcji
    "jeśli to nie ty". Standard practice — pomaga wykryć compromised
    accounts i daje audit trail.
    """
    subject = "Twoje hasło w NEXUS zostało zmienione"

    if by_admin:
        actor_text = (
            f"przez administratora {admin_name}"
            if admin_name
            else "przez administratora"
        )
        actor_html = (
            f"przez administratora <strong>{html.escape(admin_name)}</strong>"
            if admin_name
            else "przez administratora"
        )
    else:
        actor_text = "z Twojego konta"
        actor_html = "z Twojego konta"

    text_body = (
        f"Cześć {recipient_name},\n\n"
        f"Informujemy, że Twoje hasło w NEXUS zostało właśnie zmienione "
        f"{actor_text}.\n\n"
        f"Jeśli to byłeś(-aś) Ty — możesz zignorować tę wiadomość.\n\n"
        f"Jeśli to NIE Ty zmieniłeś(-aś) hasło — natychmiast skontaktuj się "
        f"z administratorem (admin@b2bnet.pl) lub zaloguj się i ustaw nowe hasło.\n\n"
        "— NEXUS · B2BNet"
    )

    safe_recipient = html.escape(recipient_name)

    html_body = (
        f"<p>Cześć {safe_recipient},</p>"
        f"<p>Informujemy, że <strong>Twoje hasło w NEXUS zostało właśnie zmienione</strong> "
        f"{actor_html}.</p>"
        f'<p style="color:#374151">Jeśli to byłeś(-aś) Ty — możesz zignorować tę wiadomość.</p>'
        f'<div style="background:#fef3c7;border-left:4px solid #f59e0b;padding:12px;'
        f'border-radius:6px;margin:16px 0">'
        f"<strong>⚠️ Jeśli to NIE Ty zmieniłeś(-aś) hasło</strong> — natychmiast skontaktuj się "
        f'z administratorem (<a href="mailto:admin@b2bnet.pl">admin@b2bnet.pl</a>) '
        f"lub zaloguj się i ustaw nowe hasło."
        "</div>"
        '<hr><p style="color:#888;font-size:12px">NEXUS · B2BNet</p>'
    )
    return send_email(to_email, subject, text_body, html_body)


def absolute_link(path: str) -> str:
    """Pełny adres ekranu NEXUSA do maila (ścieżka bez hosta, gdy brak bazy)."""
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}{path}" if base else path


def open_button_html(url: str, label: str = "Otwórz w Nexusie") -> str:
    safe = html.escape(url, quote=True)
    return (
        f'<a href="{safe}" style="display:inline-block;background:#2563eb;'
        "color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;"
        f'font-weight:500">{html.escape(label)}</a>'
    )


# Kolory maila z makiet 26.10.2026 (PPYRVzq7cKrskFgPZdYqrJ). Mail nie ma
# tokenów aplikacji — klient poczty dostaje stałe kolory w stylach inline.
_MAIL_PRIMARY = "#4f46e5"
_MAIL_FG = "#1b1f2a"
_MAIL_MUTED = "#5d6577"
_MAIL_LINE = "#e4e7ee"
_MAIL_SOFT = "#f6f7fb"
_CHIP = ("#eceafd", "#3730a3")
_CHIP_WAITING = ("#fdf0dc", "#8a4705")
REQUIRED_FOOTER = "Ten mail przychodzi zawsze, bo ktoś czeka na Twój ruch."
OPTIONAL_FOOTER = "Ten mail możesz wyłączyć sobie w Ustawienia → Moje konto."


def _mail_button_html(label: str, url: str, style: str) -> str:
    # Przycisk jako tabela `align=left`: Outlook na Windows ignoruje padding
    # na <a>, a tabele wyrównane do lewej zawijają się całe na wąskim ekranie.
    if style == "primary":
        bg, fg, border = _MAIL_PRIMARY, "#ffffff", _MAIL_PRIMARY
    elif style == "neg":
        bg, fg, border = "#ffffff", "#3d4454", "#c9ccd6"
    else:
        bg, fg, border = "#ffffff", _MAIL_PRIMARY, _MAIL_PRIMARY
    return (
        '<table role="presentation" align="left" cellpadding="0" cellspacing="0" '
        'style="margin:0 8px 8px 0"><tr>'
        f'<td bgcolor="{bg}" style="border:1px solid {border};border-radius:7px">'
        f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;'
        f"padding:10px 16px;font-weight:600;font-size:14px;color:{fg};"
        f'white-space:nowrap;text-decoration:none">{html.escape(label)}</a>'
        "</td></tr></table>"
    )


def render_card_email(card) -> tuple[str, str, str]:
    """Mail z karty (`notification_mail_card.MailCard`): (temat, tekst, HTML).

    Znaczek, tytuł, opis, 2–4 fakty sprawy, przyciski z gotową akcją i stopka
    „przychodzi zawsze” dla rodzajów obowiązkowych (decyzja Artura 26.10.2026).
    """
    footer = REQUIRED_FOOTER if card.required else OPTIONAL_FOOTER
    settings_link = absolute_link("/settings?item=my-notifications")
    buttons = [(b.label, absolute_link(b.path), b.style) for b in card.buttons]

    text_lines = [card.title, "", card.text]
    if card.facts:
        text_lines += ["", *(f"{k}: {v}" for k, v in card.facts)]
    text_lines += ["", *(f"{label}: {url}" for label, url, _ in buttons)]
    text_lines += ["", footer, f"NEXUS · Moje maile: {settings_link}"]
    text_body = "\n".join(text_lines)

    chip_bg, chip_fg = _CHIP_WAITING if card.waiting else _CHIP
    facts_html = ""
    if card.facts:
        rows = "".join(
            "<tr>"
            f'<td style="padding:3px 16px 3px 0;color:{_MAIL_MUTED};white-space:nowrap;'
            f'vertical-align:top">{html.escape(k)}</td>'
            f'<td style="padding:3px 0;font-weight:500;color:{_MAIL_FG}">'
            f"{html.escape(v)}</td></tr>"
            for k, v in card.facts
        )
        facts_html = (
            f'<tr><td style="padding:0 0 16px"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" style="background:{_MAIL_SOFT};'
            f'border:1px solid {_MAIL_LINE};border-radius:8px">'
            f'<tr><td style="padding:12px 14px"><table role="presentation" '
            f'cellpadding="0" cellspacing="0" style="font-size:14px">{rows}</table>'
            "</td></tr></table></td></tr>"
        )
    buttons_html = "".join(
        _mail_button_html(label, url, style) for label, url, style in buttons
    )
    html_body = (
        # Podgląd na liście maili: opis sprawy zamiast „NEXUS Czeka na Ciebie”.
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all">'
        f"{html.escape(card.text)}</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:#ffffff"><tr><td>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="max-width:600px;font-family:Segoe UI,Arial,sans-serif;font-size:15px;'
        f'line-height:1.5;color:{_MAIL_FG}">'
        '<tr><td style="padding:0 0 16px"><table role="presentation" width="100%" '
        'cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-weight:700;letter-spacing:1px;font-size:13px;'
        f'color:{_MAIL_PRIMARY}">NEXUS</td>'
        f'<td align="right"><span style="display:inline-block;font-size:12px;'
        f"font-weight:600;padding:3px 10px;border-radius:999px;background:{chip_bg};"
        f'color:{chip_fg}">{html.escape(card.chip)}</span></td>'
        "</tr></table></td></tr>"
        f'<tr><td style="padding:0 0 8px;font-size:20px;font-weight:600;'
        f'line-height:1.3">{html.escape(card.title)}</td></tr>'
        f'<tr><td style="padding:0 0 16px">{html.escape(card.text)}</td></tr>'
        f"{facts_html}"
        f'<tr><td style="padding:0 0 8px">{buttons_html}</td></tr>'
        f'<tr><td style="border-top:1px solid {_MAIL_LINE};padding:12px 0 0;'
        f'font-size:12px;color:{_MAIL_MUTED}">{html.escape(footer)}<br>'
        f'NEXUS · <a href="{html.escape(settings_link, quote=True)}" '
        f'style="color:{_MAIL_MUTED}">Moje maile</a></td></tr>'
        "</table></td></tr></table>"
    )
    return card.subject, text_body, html_body


def render_notification_email(
    *, title: str, message: str, deep_link_path: str
) -> tuple[str, str, str]:
    """Mail z powiadomienia bez opisu w `notification_mail_card.SPECS` (czat).

    Ten sam wygląd co maile z kolejki „od razu” — tytuł jako „co zrobić”
    i jeden przycisk do ekranu.
    """
    from app.services.notification_mail_card import build_card

    return render_card_email(
        build_card(
            notification_type="",
            kind=None,
            title=title,
            message=message,
            link=deep_link_path,
            required=False,
        )
    )


def send_chat_fallback_email(
    *,
    to_email: str,
    notification_title: str,
    notification_message: str,
    deep_link_path: str,
    event_at: datetime | None = None,
) -> bool:
    """Email fallback dla chatów (>15 min offline).

    Używana z `tasks/chat_email_fallback.py`. Prostszy template niż
    send_mention_email — pokazuje tytuł + wiadomość bez quotation.
    """
    subject, text_body, html_body = render_notification_email(
        title=notification_title,
        message=notification_message,
        deep_link_path=deep_link_path,
    )
    from app.services.notification_delivery import guarded_send

    return guarded_send(
        "chat_unread", event_at, send_email, to_email, subject, text_body, html_body
    )
