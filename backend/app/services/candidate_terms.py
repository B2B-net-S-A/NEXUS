"""Warunki od kandydata: kto dostaje link, treść maila, przeliczenie stawki.

Decyzje Artura 16–17.11.2026 (makiety https://claude.ai/artifact/7eyYasRzy1WkXYvr7EGL5f,
analiza https://claude.ai/artifact/BFWRPbbq7XaSufWkVoHRfS). Reguła w
``docs/claude/kandydaci-wyszukiwanie/warunki-od-kandydata-formularz-po-aplikacji.md``.

Ten moduł jest czysty: bez bazy i bez sieci, żeby reguły dało się sprawdzić
testem jednostkowym. Kolejka i zapis są w ``candidate_terms_queue`` oraz
``candidate_terms_apply``.
"""

from __future__ import annotations

import hashlib
import html
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

KIND = "candidate_terms"

#: Link działa tyle dni od wysyłki.
LINK_TTL_DAYS = 14
#: Jeden mail z linkiem na osobę na tyle dni (decyzja 16.11).
RESEND_AFTER_DAYS = 30
#: Mail tylko do aplikacji nie starszej niż tyle dni (import przychodzi paczkami).
MAX_APPLICATION_AGE_DAYS = 3
#: Wysyłka w godzinach 8:00–20:00 czasu firmy.
SEND_FROM = time(8, 0)
SEND_UNTIL = time(20, 0)
#: Godzin pracy w miesiącu przy przeliczeniu stawki miesięcznej (jak „Stawka od”).
HOURS_PER_MONTH = Decimal("168")
#: Zakres stawki godzinowej, który przyjmuje formularz.
RATE_MIN_HOURLY = Decimal("20")
RATE_MAX_HOURLY = Decimal("1000")

FIELDS = ("rate", "work_mode", "office", "start")

REMOTE_MODES = ("remote", "hybrid", "onsite")


@dataclass(frozen=True)
class TermsSnapshot:
    """To, co profil już wie o warunkach (bez danych osobowych)."""

    rate: Optional[Decimal] = None
    modes: tuple[str, ...] = ()
    onsite_days: Optional[int] = None
    office_cities: tuple[str, ...] = ()
    availability_date: Optional[date] = None
    notice_period: Optional[int] = None


def missing_fields(snapshot: TermsSnapshot) -> tuple[str, ...]:
    """Których pól brakuje. Pusta krotka = komplet, mail idzie bez linku.

    ``office`` liczy się tylko wtedy, gdy osoba dopuszcza biuro: przy hybrydzie
    brak dni albo miast, przy samym biurze brak miast.
    """
    missing: list[str] = []
    if snapshot.rate is None:
        missing.append("rate")
    if not snapshot.modes:
        missing.append("work_mode")
    else:
        hybrid = "hybrid" in snapshot.modes
        office = hybrid or "onsite" in snapshot.modes
        if (hybrid and snapshot.onsite_days is None) or (
            office and not snapshot.office_cities
        ):
            missing.append("office")
    if snapshot.availability_date is None and snapshot.notice_period is None:
        missing.append("start")
    return tuple(missing)


#: Co wysyłamy: mail z linkiem, samo podziękowanie albo nic.
LINK = "link"
THANKS = "thanks"
NONE = "none"


@dataclass(frozen=True)
class Eligibility:
    action: str
    reason: str
    missing: tuple[str, ...] = field(default_factory=tuple)


def eligibility(
    *,
    email: Optional[str],
    snapshot: TermsSnapshot,
    applied_at: datetime,
    now: datetime,
    last_link_sent_at: Optional[datetime],
    opted_out: bool,
    blacklisted: bool,
    works_here: bool,
) -> Eligibility:
    """Co dostaje osoba po aplikacji. Kolejność sprawdzeń = kolejność powodów.

    Bez maila: brak adresu, czarna lista, żywa umowa, aplikacja starsza niż
    3 dni (import zaległości). Samo podziękowanie: wypis z pytań, link w 30
    dniach, komplet danych. Link: brak choć jednego pola (decyzja 16.11).
    """
    if not (email or "").strip() or "@" not in (email or ""):
        return Eligibility(NONE, "no_email")
    if blacklisted:
        return Eligibility(NONE, "blacklisted")
    if works_here:
        return Eligibility(NONE, "works_here")
    if now - applied_at > timedelta(days=MAX_APPLICATION_AGE_DAYS):
        return Eligibility(NONE, "stale_application")
    if opted_out:
        return Eligibility(THANKS, "opted_out")
    if last_link_sent_at is not None and now - last_link_sent_at < timedelta(
        days=RESEND_AFTER_DAYS
    ):
        return Eligibility(THANKS, "recent_request")
    missing = missing_fields(snapshot)
    if not missing:
        return Eligibility(THANKS, "complete")
    return Eligibility(LINK, "missing", missing)


def in_send_window(local_now: datetime) -> bool:
    """8:00 ≤ godzina < 20:00 w kalendarzu firmy (``local_now`` już w Europe/Warsaw)."""
    return SEND_FROM <= local_now.time() < SEND_UNTIL


def hourly_rate(amount: Decimal, unit: str) -> Decimal:
    """Stawka z formularza na godzinę: miesiąc ÷ 168, zaokrąglenie do grosza."""
    if unit == "month":
        amount = amount / HOURS_PER_MONTH
    elif unit != "hour":
        raise ValueError("unknown rate unit")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rate_unit_warning(amount: Decimal, unit: str) -> Optional[str]:
    """Podpowiedź, gdy kwota nie pasuje do jednostki (25 000 „za godzinę”)."""
    if unit == "hour" and amount > RATE_MAX_HOURLY:
        return "looks_monthly"
    if unit == "month" and amount < RATE_MIN_HOURLY * HOURS_PER_MONTH / 2:
        return "looks_hourly"
    return None


def new_token() -> tuple[str, str]:
    """``(sekret do linku, skrót do bazy)``. Baza nigdy nie trzyma sekretu."""
    raw = secrets.token_urlsafe(24)
    return raw, token_hash(raw)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Mail ──────────────────────────────────────────────────────────────────────


def one_click_unsubscribe_url(api_base: str, raw_token: Optional[str]) -> Optional[str]:
    """Adres dla ``List-Unsubscribe`` (RFC 8058): POST od Gmaila trafia wprost
    w trasę wypisu w API. Bez tokenu (samo podziękowanie) nie ma czego wypisać."""
    if not raw_token:
        return None
    return f"{api_base.rstrip('/')}/api/public/candidate-terms/{raw_token}/opt-out"


@dataclass(frozen=True)
class TermsEmail:
    subject: str
    text_body: str
    html_body: str


_QUESTIONS = (
    ("Minimalna stawka na B2B", "kwota netto za godzinę albo za miesiąc"),
    ("Tryb pracy", "zdalnie, hybrydowo albo w biurze"),
    ("Dni w biurze", "przy hybrydzie: od 1 do 5 w tygodniu"),
    ("Miasta", "gdzie możesz dojeżdżać do biura"),
    ("Od kiedy możesz zacząć", "data albo okres wypowiedzenia"),
)

_COMPANY = (
    "B2B.NET S.A. · Kopernik Office Buildings, wejście A, Al. Jerozolimskie 180, "
    "02-486 Warszawa · KRS 0000387063 · NIP 5711707392"
)

_F = "font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;"


def render_terms_email(
    *,
    job_title: Optional[str],
    link: Optional[str],
    optout_link: Optional[str],
    rodo_url: str,
    logo_url: str,
    logo_light_url: str,
) -> TermsEmail:
    """Mail „Dziękujemy za zgłoszenie”. Bez ``link`` = samo podziękowanie.

    Powitanie bez imienia (jak ``application_confirmation``): imię przychodzi
    z formularza albo portalu i bywa czymkolwiek. Wszystko, co pochodzi
    z bazy, przechodzi przez ``html.escape``.

    Bez Reply-To i bez zachęty do odpowiedzi (decyzja Artura 17.11.2026):
    kandydat ma wypełnić formularz, nie odpisywać na maila.
    """
    title = (job_title or "").strip() or None
    what = f"Twoje zgłoszenie na stanowisko „{title}”" if title else "Twoje zgłoszenie"
    subject = (
        f"Dziękujemy za zgłoszenie: {title}" if title else "Dziękujemy za zgłoszenie"
    )
    no_reply = (
        "Wiadomość wysłana automatycznie, nie odpowiadaj na nią. "
        + ("Swoje warunki podaj w formularzu." if link else "")
    ).strip()

    text_lines = [
        "Dzień dobry,",
        "",
        f"{what} do nas dotarło, CV też. Rekruter przejrzy je i odezwie się, "
        "jeśli profil będzie pasował.",
        "",
    ]
    if link:
        text_lines += [
            "Żeby dopasować do Ciebie tę i podobne oferty, możesz od razu podać "
            "swoje warunki. To ok. 2 minuty i nie jest obowiązkowe:",
            "",
            *[f"{i}. {q}" for i, (q, _) in enumerate(_QUESTIONS, 1)],
            "",
            f"Podaj swoje warunki: {link}",
            f"Link działa {LINK_TTL_DAYS} dni i jest tylko dla Ciebie.",
            "",
            "English: you can answer the same questions in English — the form "
            "has a language switch.",
            "",
        ]
    text_lines += [
        no_reply,
        "",
        _COMPANY,
        f"Informacje o przetwarzaniu danych: {rodo_url}",
    ]
    if optout_link:
        text_lines.append(f"Nie chcę dostawać takich pytań: {optout_link}")
    text_body = "\n".join(text_lines) + "\n"

    e = html.escape
    pre = (
        "5 krótkich pytań, ok. 2 minuty. Pomogą dopasować do Ciebie tę i podobne oferty."
        if link
        else "Twoje zgłoszenie do nas dotarło."
    )
    rows = "".join(
        f'<tr><td style="padding:14px 0;border-top:1px solid #D9D6CA;width:40px;'
        f'vertical-align:top;{_F}font-size:15px;font-weight:800;color:#C42536">{i:02d}</td>'
        f'<td style="padding:14px 0;border-top:1px solid #D9D6CA;vertical-align:top;{_F}">'
        f'<div style="font-size:16px;font-weight:700;color:#141414;line-height:22px">{e(q)}</div>'
        f'<div style="font-size:14px;color:#5C5A55;line-height:20px">{e(h)}</div></td></tr>'
        for i, (q, h) in enumerate(_QUESTIONS, 1)
    )
    ask = ""
    if link:
        ask = (
            f'<p style="margin:0 0 20px;{_F}font-size:16px;line-height:24px;color:#141414">'
            "Żeby dopasować do Ciebie tę i podobne oferty, możesz od razu podać swoje "
            "warunki. To ok. 2 minuty i nie jest obowiązkowe.</p>"
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="border-bottom:1px solid #D9D6CA">{rows}</table>'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:28px 0 12px"><tr><td bgcolor="#C42536" '
            'style="background:#C42536;border-radius:4px">'
            f'<a href="{e(link, quote=True)}" style="display:inline-block;padding:15px 26px;'
            f"{_F}font-size:16px;font-weight:700;color:#FFFFFF;text-decoration:none;"
            'border-radius:4px">Podaj swoje warunki&nbsp;&rarr;</a></td></tr></table>'
            f'<p style="margin:0 0 24px;{_F}font-size:13px;line-height:19px;color:#5C5A55">'
            f"Link działa {LINK_TTL_DAYS} dni i jest tylko dla Ciebie. Nie wymaga logowania. "
            "English version: use the language switch on the form.</p>"
        )
    title_html = f"<b>„{e(title)}”</b>" if title else ""
    lead = (
        f"Twoje zgłoszenie na stanowisko {title_html} do nas dotarło, CV też."
        if title
        else "Twoje zgłoszenie do nas dotarło, CV też."
    )
    optout_html = (
        f' &nbsp;·&nbsp; <a href="{e(optout_link, quote=True)}" '
        'style="color:#F5F4EC;text-decoration:underline">Nie chcę dostawać takich pytań</a>'
        if optout_link
        else ""
    )
    html_body = (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f"<title>{e(subject)}</title></head>"
        '<body style="margin:0;padding:0;background:#F5F4EC">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#F5F4EC">'
        f"{e(pre)}</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'bgcolor="#F5F4EC" style="background:#F5F4EC"><tr><td align="center" '
        'style="padding:24px 12px"><table role="presentation" width="600" cellpadding="0" '
        'cellspacing="0" border="0" style="width:100%;max-width:600px">'
        f'<tr><td style="padding:8px 8px 24px"><img src="{e(logo_url, quote=True)}" '
        'width="132" height="61" alt="B2B Network" style="display:block;border:0"></td></tr>'
        '<tr><td bgcolor="#FFFFFF" style="background:#FFFFFF;padding:36px 32px 32px;'
        'border-top:4px solid #E73748">'
        f'<h1 style="margin:0 0 20px;{_F}font-size:28px;line-height:32px;font-weight:800;'
        'letter-spacing:-0.5px;color:#141414">Dziękujemy za zgłoszenie</h1>'
        f'<p style="margin:0 0 16px;{_F}font-size:16px;line-height:24px;color:#141414">'
        "Dzień dobry,</p>"
        f'<p style="margin:0 0 16px;{_F}font-size:16px;line-height:24px;color:#141414">'
        f"{lead} Rekruter przejrzy je i odezwie się, jeśli profil będzie pasował.</p>"
        f"{ask}"
        "</td></tr>"
        '<tr><td bgcolor="#1A1816" style="background:#1A1816;padding:28px 32px">'
        f'<img src="{e(logo_light_url, quote=True)}" width="96" height="44" alt="B2B Network" '
        'style="display:block;border:0;margin:0 0 16px">'
        f'<p style="margin:0 0 12px;{_F}font-size:12px;line-height:18px;color:#B9B3A8">'
        f"{e(no_reply)}</p>"
        f'<p style="margin:0 0 12px;{_F}font-size:12px;line-height:18px;color:#B9B3A8">'
        f"{e(_COMPANY)}</p>"
        f'<p style="margin:0;{_F}font-size:12px;line-height:18px;color:#B9B3A8">'
        f'<a href="{e(rodo_url, quote=True)}" style="color:#F5F4EC;text-decoration:underline">'
        f"Informacje o przetwarzaniu danych</a>{optout_html}</p>"
        "</td></tr></table></td></tr></table></body></html>"
    )
    return TermsEmail(subject=subject, text_body=text_body, html_body=html_body)
