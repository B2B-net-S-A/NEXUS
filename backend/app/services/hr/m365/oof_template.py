"""Treść i harmonogram autoodpowiedzi urlopowej (czysty moduł).

Zasady przeniesione z Compassa (``lib/mailbox/oof-template.ts``), których nie
cofamy:

* treść NIE zdradza rodzaju nieobecności (D6) — „jestem poza biurem”, także
  przy L4,
* imiona w mianowniku („zastępuje mnie Anna Przykładowa”), bez form
  rodzajowych — kartoteka nie ma płci,
* wewnętrzna po polsku, zewnętrzna po polsku i angielsku; data powrotu
  podana wprost (``return_on`` liczy kalendarz pracy firmy),
* kontakt w pilnych sprawach: zastępca → przełożony (aktywny) → skrzynka
  administracji (``ADMIN_CASES_MAILBOX``), a bez żadnego — bez tej linii.

Każda treść dostaje znacznik ``nexus-managed-oof-v1``: po nim wykonawca
rozpoznaje własną autoodpowiedź i nie myli jej z ustawioną przez osobę.
Własne teksty osoby przechodzą przez czyszczenie z HTML — zostaje sam tekst
z akapitami.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, Optional

from app.core.scheduling import DEFAULT_TZ
from app.services.hr.m365.oof_state import NEXUS_OOF_MARKER
from app.services.m365.html_sanitize import html_to_text

COMPANY_SIGNATURE = "B2B Network"
#: Granica długości własnego tekstu (Exchange przyjmuje więcej, ale to ma być
#: autoodpowiedź, nie list).
CUSTOM_TEXT_LIMIT = 4000

_PL_MONTHS = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)
_EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class Contact:
    kind: Literal["substitute", "manager", "office"]
    email: str
    name: Optional[str] = None


def pl_date(day: date) -> str:
    return f"{day.day} {_PL_MONTHS[day.month - 1]} {day.year}"


def en_date(day: date) -> str:
    return f"{day.day} {_EN_MONTHS[day.month - 1]} {day.year}"


def with_marker(body: str) -> str:
    return body if NEXUS_OOF_MARKER in body else f"{NEXUS_OOF_MARKER}\n{body}"


def custom_html(raw: Optional[str]) -> Optional[str]:
    """Własny tekst osoby → akapity HTML bez znaczników z wejścia.

    ``html_to_text`` (bleach) zdejmuje tagi i escapuje ``<``, ``>``, ``&`` —
    wynik jest bezpieczny jako treść elementu.
    """

    if not raw:
        return None
    text = html_to_text(raw[:CUSTOM_TEXT_LIMIT]).replace("\r\n", "\n").strip()
    if not text:
        return None
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    return "\n".join(
        "<p>" + "<br/>".join(line.strip() for line in part.split("\n")) + "</p>"
        for part in paragraphs
    )


def _mailto(email: str) -> str:
    safe = html.escape(email)
    return f'<a href="mailto:{safe}">{safe}</a>'


def _contact_pl(contact: Optional[Contact]) -> str:
    if contact is None:
        return ""
    if contact.kind == "substitute":
        who = html.escape(contact.name or contact.email)
        return f"<p>W pilnych sprawach zastępuje mnie <strong>{who}</strong> ({_mailto(contact.email)}).</p>\n"
    if contact.kind == "manager":
        who = html.escape(contact.name or contact.email)
        return f"<p>W pilnych sprawach proszę o kontakt: <strong>{who}</strong> ({_mailto(contact.email)}).</p>\n"
    return f"<p>W pilnych sprawach proszę o kontakt z biurem: {_mailto(contact.email)}.</p>\n"


def _contact_en(contact: Optional[Contact]) -> str:
    if contact is None:
        return ""
    if contact.kind == "substitute":
        who = html.escape(contact.name or contact.email)
        return f"<p>For urgent matters, please contact <strong>{who}</strong> ({_mailto(contact.email)}), who is covering for me.</p>\n"
    if contact.kind == "manager":
        who = html.escape(contact.name or contact.email)
        return f"<p>For urgent matters, please contact <strong>{who}</strong> ({_mailto(contact.email)}).</p>\n"
    return f"<p>For urgent matters, please contact our office at {_mailto(contact.email)}.</p>\n"


def default_messages(
    *, employee_name: str, end: date, return_on: date, contact: Optional[Contact]
) -> tuple[str, str]:
    """Domyślna para (wewnętrzna, zewnętrzna) — bez rodzaju nieobecności."""

    name = html.escape(employee_name)
    internal = (
        "<p>Dzień dobry,</p>\n"
        f"<p>jestem poza biurem do <strong>{pl_date(end)}</strong> włącznie — "
        f"odpowiem po powrocie, <strong>{pl_date(return_on)}</strong>.</p>\n"
        f"{_contact_pl(contact)}"
        f"<p>— {name}</p>"
    )
    external = (
        "<p>Dzień dobry,</p>\n"
        f"<p>dziękuję za wiadomość. Jestem poza biurem do <strong>{pl_date(end)}</strong> "
        f"włącznie i odpowiem po powrocie, <strong>{pl_date(return_on)}</strong>.</p>\n"
        f"{_contact_pl(contact)}"
        "<hr/>\n"
        "<p>Hello,</p>\n"
        f"<p>thank you for your email. I am out of office until <strong>{en_date(end)}</strong> "
        f"(inclusive) and will respond after my return on <strong>{en_date(return_on)}</strong>.</p>\n"
        f"{_contact_en(contact)}"
        f"<p>{name}<br/>{COMPANY_SIGNATURE}</p>"
    )
    return internal, external


def schedule_setting(
    *, start: date, end: date, internal_html: str, external_html: str
) -> dict[str, Any]:
    """``automaticRepliesSetting`` od 00:00 pierwszego dnia do 00:00 dnia po końcu.

    Czas ściany w strefie Warszawy — Exchange sam przelicza zmianę czasu;
    przeliczenie na UTC po naszej stronie przesunęłoby okno o godzinę
    w tygodniu zmiany czasu.
    """

    return {
        "status": "scheduled",
        "externalAudience": "all",
        "scheduledStartDateTime": {
            "dateTime": f"{start.isoformat()}T00:00:00",
            "timeZone": DEFAULT_TZ,
        },
        "scheduledEndDateTime": {
            "dateTime": f"{(end + timedelta(days=1)).isoformat()}T00:00:00",
            "timeZone": DEFAULT_TZ,
        },
        "internalReplyMessage": with_marker(internal_html),
        "externalReplyMessage": with_marker(external_html),
    }


def build_setting(
    *,
    start: date,
    end: date,
    return_on: date,
    employee_name: str,
    contact: Optional[Contact],
    internal_custom: Optional[str] = None,
    external_custom: Optional[str] = None,
) -> dict[str, Any]:
    internal, external = default_messages(
        employee_name=employee_name, end=end, return_on=return_on, contact=contact
    )
    return schedule_setting(
        start=start,
        end=end,
        internal_html=custom_html(internal_custom) or internal,
        external_html=custom_html(external_custom) or external,
    )
