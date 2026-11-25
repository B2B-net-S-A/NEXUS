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


_COMPANY = (
    "B2B.NET S.A. · Kopernik Office Buildings, wejście A, Al. Jerozolimskie 180, "
    "02-486 Warszawa · KRS 0000387063 · NIP 5711707392"
)

_F = "font-family:Helvetica,Arial,sans-serif;"
_F_BIG = "font-family:'Arial Black','Helvetica Neue',Helvetica,Arial,sans-serif;font-weight:900;"

#: Kolory wariantu 5 „Czerwień w gradientach tech” (decyzja Artura 25.11.2026,
#: DESIGN.md strony b2bnetwork-www), te same co na `/warunki/<token>`
#: (`warunki.css`): czerwień #C42329, linki #B0222A, burgund-obsydian #1F1115
#: zamiast grafitu, tło w kamieniu różanym #F4EAE8. Bez gradientów, bo klienci
#: poczty (Outlook) ich nie rysują: jednolita czerwień.
#:
#: Ciemny wygląd dla Apple Mail, iOS i Outlooka na Macu. Aplikacje Gmaila
#: tej reguły nie czytają i przyciemniają mail same. Czerwień na karcie #2E1A1F
#: miałaby 2,82:1, więc kropka (``rd``) i zaliczone odcinki (``sgd``) biorą tam
#: ciepły blask #D43424 (3,36:1), a linki morelowy #FFD6C9 (13,7:1).
_STYLE = (
    "@media (prefers-color-scheme: dark){"
    ".bg{background:#1F1115!important}.wh{background:#2E1A1F!important}"
    ".tx{color:#F7EFEC!important}.mu{color:#C4B2B4!important}.ln{border-color:#3D2A2E!important}"
    ".bt{background:#F7EFEC!important}.bt a{color:#1F1115!important}.lk{color:#FFD6C9!important}"
    ".sgo{background:#2E1A1F!important;border-color:#F7EFEC!important}"
    ".sgd{background:#D43424!important;border-color:#D43424!important}.rd{color:#D43424!important}"
    ".lt{display:none!important}.dk{display:block!important}}"
    "@media (max-width:620px){.pad{padding:24px 22px!important}.poster{padding:8px 22px 30px!important}"
    ".big{font-size:44px!important;line-height:46px!important}}"
)


def _segment(label: str, done: bool) -> str:
    """Odcinek paska: zgłoszenie i CV zaliczone, warunki czekają na kandydata."""
    fill, cls, mark = (
        ("#C42329", "sgd", "&#10003;&nbsp;") if done else ("#FFFFFF", "sgo", "")
    )
    border = "#C42329" if done else "#1F1115"
    return (
        '<td valign="top" width="33%" style="width:33%;padding:0 4px">'
        f'<div class="{cls}" style="height:12px;background:{fill};border:2px solid {border};'
        'border-radius:8px"></div>'
        f'<div class="tx" style="{_F}font-size:14px;line-height:20px;font-weight:bold;'
        f'color:#1F1115;margin-top:8px">{mark}{label}</div></td>'
    )


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

    Wygląd „Pasek postępu” (decyzja Artura 18.11.2026, makiety
    https://claude.ai/artifact/CqKhX41iCPVCwQJyam4ruR): „30 sekund.” i pasek,
    w którym zgłoszenie i CV są zaliczone, a warunki czekają. Wypis, dane
    i adres spółki stoją na końcu bez logo pod nimi, bo Gmail zwija
    powtarzającą się stopkę w kolejnych mailach wątku.

    Powitanie bez imienia (jak ``application_confirmation``): imię przychodzi
    z formularza albo portalu i bywa czymkolwiek. Wszystko, co pochodzi
    z bazy, przechodzi przez ``html.escape``.

    Bez Reply-To i bez zachęty do odpowiedzi (decyzja Artura 17.11.2026):
    kandydat ma wypełnić formularz, nie odpisywać na maila.
    """
    title = (job_title or "").strip() or None
    subject = (
        f"Dziękujemy za zgłoszenie: {title}" if title else "Dziękujemy za zgłoszenie"
    )
    no_reply = "Wiadomość automatyczna, nie odpowiadaj na nią."
    position = f" na stanowisko „{title}”" if title else ""
    text_lines = ["Dzień dobry,", ""]
    if link:
        intro = (
            f"dziękujemy za CV{position}. Jeśli chcesz, daj nam znać, jaka stawka "
            "Ci odpowiada, jak wolisz pracować i kiedy możesz zacząć."
        )
        text_lines += [
            intro,
            "",
            f"Dokończ w 30 sekund: {link}",
            f"Link działa {LINK_TTL_DAYS} dni i jest tylko dla Ciebie. Nie wymaga logowania.",
            "English: the form has a language switch.",
            "",
        ]
    else:
        intro = (
            f"Twoje zgłoszenie{position} i CV do nas dotarły. "
            "Rekruter przejrzy je i odezwie się, jeśli profil będzie pasował."
        )
        text_lines += [intro, ""]
    if optout_link:
        text_lines.append(f"Nie chcesz takich pytań? Wypisz się: {optout_link}")
    text_lines += [
        no_reply,
        f"Informacje o przetwarzaniu danych: {rodo_url}",
        _COMPANY,
    ]
    text_body = "\n".join(text_lines) + "\n"

    e = html.escape
    pre = (
        "Zgłoszenie i CV mamy. 30 sekund dzieli je od kompletu: Twoje warunki."
        if link
        else "Twoje zgłoszenie i CV do nas dotarły."
    )
    job_html = (
        f'<br><b class="tx" style="color:#1F1115">{e(title)}</b>' if title else ""
    )
    header = (
        '<tr><td class="wh pad" bgcolor="#FFFFFF" style="background:#FFFFFF;padding:24px 36px 22px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td><img class="lt" src="{e(logo_url, quote=True)}" width="88" height="41" '
        'alt="B2Bnetwork" style="display:block;border:0">'
        f'<img class="dk" src="{e(logo_light_url, quote=True)}" width="88" height="41" '
        'alt="B2Bnetwork" style="display:none;border:0"></td>'
        f'<td align="right" class="mu" style="{_F}font-size:13px;line-height:18px;color:#5E4A4E">'
        f"Zgłoszenie przyjęte{job_html}</td></tr></table></td></tr>"
    )
    if link:
        poster = (
            '<tr><td class="poster wh ln" bgcolor="#FFFFFF" style="background:#FFFFFF;'
            'padding:10px 32px 34px;border-top:1px solid #E6D6D3">'
            f'<div class="tx big" style="{_F_BIG}font-size:60px;line-height:62px;'
            'letter-spacing:-2px;color:#1F1115;margin:18px 4px 6px">'
            '30 sekund<span class="rd" style="color:#C42329">.</span></div>'
            f'<div class="tx" style="{_F}font-size:19px;line-height:27px;color:#1F1115;'
            'margin:0 4px 26px">Tyle dzieli Twoje zgłoszenie od kompletu.</div>'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            + _segment("Zgłoszenie", True)
            + _segment("CV", True)
            + _segment("Twoje warunki", False)
            + "</tr></table></td></tr>"
        )
        action = (
            '<tr><td class="wh pad" bgcolor="#FFFFFF" style="background:#FFFFFF;padding:30px 36px 32px">'
            f'<p class="tx" style="margin:0 0 24px;{_F}font-size:17px;line-height:26px;color:#1F1115">'
            f"Dzień dobry,<br><br>{e(intro)}</p>"
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:0 0 14px"><tr><td class="bt" bgcolor="#1F1115" '
            'style="background:#1F1115;border-radius:2px">'
            f'<a href="{e(link, quote=True)}" style="display:inline-block;padding:16px 30px;'
            f'{_F}font-size:16px;font-weight:bold;color:#FFFFFF;text-decoration:none">'
            "Dokończ w 30 sekund&nbsp;&nbsp;&rarr;</a></td></tr></table>"
            f'<p class="mu" style="margin:0;{_F}font-size:13px;line-height:20px;color:#5E4A4E">'
            f"Nieobowiązkowe · bez logowania · link działa {LINK_TTL_DAYS} dni i jest tylko "
            "dla Ciebie · English version on the form</p></td></tr>"
        )
    else:
        poster = ""
        action = (
            '<tr><td class="wh pad ln" bgcolor="#FFFFFF" style="background:#FFFFFF;'
            'padding:30px 36px 32px;border-top:1px solid #E6D6D3">'
            f'<h1 class="tx" style="margin:0 0 14px;{_F_BIG}font-size:30px;line-height:34px;'
            'letter-spacing:-1px;color:#1F1115">Dziękujemy za zgłoszenie'
            '<span class="rd" style="color:#C42329">.</span></h1>'
            f'<p class="tx" style="margin:0;{_F}font-size:17px;line-height:26px;color:#1F1115">'
            f"Dzień dobry, {e(intro)}</p></td></tr>"
        )
    optout_html = (
        f'<p class="tx" style="margin:0 0 4px;{_F}font-size:14px;line-height:21px;color:#4A3539">'
        "Nie chcesz takich pytań? "
        f'<a class="lk" href="{e(optout_link, quote=True)}" style="display:inline-block;'
        'padding:6px 0;color:#B0222A;font-weight:bold;text-decoration:underline">'
        "Wypisz się jednym kliknięciem</a></p>"
        if optout_link
        else ""
    )
    footer = (
        '<tr><td class="pad" style="padding:20px 36px 30px">'
        f"{optout_html}"
        f'<p class="mu" style="margin:0 0 6px;{_F}font-size:12px;line-height:18px;color:#5E4A4E">'
        f"{e(no_reply)} "
        f'<a class="lk" href="{e(rodo_url, quote=True)}" style="display:inline-block;'
        'padding:6px 0;color:#B0222A;text-decoration:underline">'
        "Informacje o przetwarzaniu danych</a></p>"
        f'<p class="mu" style="margin:0;{_F}font-size:11px;line-height:17px;color:#76626A">'
        f"{e(_COMPANY)}</p></td></tr>"
    )
    html_body = (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        f"<title>{e(subject)}</title><style>{_STYLE}</style></head>"
        '<body class="bg" style="margin:0;padding:0;background:#F4EAE8">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
        f"{e(pre)}</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'class="bg" bgcolor="#F4EAE8" style="background:#F4EAE8"><tr><td align="center" '
        'style="padding:28px 10px"><table role="presentation" width="600" cellpadding="0" '
        'cellspacing="0" border="0" style="width:100%;max-width:600px">'
        f"{header}{poster}{action}{footer}"
        "</table></td></tr></table></body></html>"
    )
    return TermsEmail(subject=subject, text_body=text_body, html_body=html_body)
