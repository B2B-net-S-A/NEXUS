"""Ogłoszenie na Pracuj.pl mailem do opiekuna konta (27.10.2026).

Pracuj.pl nie ma u nas API — ogłoszenie wstawia opiekun konta po mailu.
Decyzje Artura (makiety https://claude.ai/artifact/6cgqm3LhTM7t8MzMXazmEe):

* mail wychodzi ze skrzynki M365 osoby, która go wysyła; bez podłączonej
  skrzynki NEXUS nie wysyła z innego adresu (okno prosi o podłączenie
  i daje tekst do skopiowania);
* wysyła Delivery Lead rekrutacji, Head of Recruitment albo admin
  (``reminders.can_manage``);
* stawkę dla kandydata wpisuje człowiek przy wysyłce — w treści ogłoszenia
  kwot nie ma (reguła z 25.09.2026), mail niesie ją raz, w nagłówku;
* link do ogłoszenia wkleja DL („Oznacz jako opublikowane”), NEXUS nie czyta
  odpowiedzi opiekuna.

Treść maila to pola zakładki Pracuj.pl (``render.pracuj_view``) po kontroli,
poprzedzone faktami rekrutacji. Ślad wysyłki to wiersz Historii zdarzeń
(``ACTION``) — z niego bierze się stan „wysłane, czeka na publikację”
i cisza przypomnień o Pracuj.pl przez ``QUIET_BUSINESS_DAYS`` dni roboczych.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html import escape
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.models.activity import Activity
from app.models.user import User
from app.services.job_ad.fixed_blocks import PracujCaretaker

ACTION = "job_ad_pracuj_requested"
QUIET_BUSINESS_DAYS = 3
RATE_MIN = 1
RATE_MAX = 5000
# Ta sama granica co widełki na JustJoin.IT (`do ≤ 3 × od`).
RATE_SPREAD_MAX = 3

# Fakty z lewej kolumny okna, które idą do nagłówka maila („Wymagania” to
# tylko liczba pozycji — opiekunowi nic nie mówi).
_FACT_KEYS = ("workplace", "city", "contract", "language", "start", "duration")


class RateInvalid(ValueError):
    """Stawka, której nie wyślemy — komunikat po polsku."""


@dataclass(frozen=True)
class PracujMail:
    subject: str
    body_text: str
    body_html: str


@dataclass(frozen=True)
class PracujRequest:
    """Ostatni mail do opiekuna wysłany z NEXUSA."""

    sent_at: datetime
    sent_by: Optional[int]
    sent_by_name: Optional[str]
    to: Optional[str]


def rate_text(rate_from: Optional[int], rate_to: Optional[int]) -> str:
    """„110–125 zł/h netto (B2B)”; jedna granica mówi, którą jest („od 110”, „do 125”)."""
    if rate_from is None and rate_to is None:
        raise RateInvalid("Wpisz stawkę dla kandydata.")
    for value in (rate_from, rate_to):
        if value is not None and not RATE_MIN <= value <= RATE_MAX:
            raise RateInvalid(
                f"Stawka godzinowa powinna mieścić się w {RATE_MIN}–{RATE_MAX} zł."
            )
    if rate_from is not None and rate_to is not None:
        if rate_to < rate_from:
            raise RateInvalid("Stawka „do” nie może być niższa niż „od”.")
        if rate_to > RATE_SPREAD_MAX * rate_from:
            raise RateInvalid(
                "Górna stawka jest ponad trzy razy wyższa od dolnej — sprawdź liczby."
            )
        if rate_to > rate_from:
            return f"{rate_from}–{rate_to} zł/h netto (B2B)"
        return f"{rate_from} zł/h netto (B2B)"
    if rate_from is not None:
        return f"od {rate_from} zł/h netto (B2B)"
    return f"do {rate_to} zł/h netto (B2B)"


def _greeting(caretaker: PracujCaretaker) -> str:
    return f"Dzień dobry {caretaker.name}," if caretaker.name else "Dzień dobry,"


def _field_lines(field: dict[str, Any]) -> list[str]:
    if field["kind"] == "text":
        return [p for p in field["text"].split("\n\n") if p.strip()]
    if field["kind"] == "ordered":
        return [f"{i}. {item}" for i, item in enumerate(field["items"], start=1)]
    return [f"• {item}" for item in field["items"]]


def _field_html(field: dict[str, Any]) -> str:
    if field["kind"] == "text":
        return "".join(f"<p>{escape(p)}</p>" for p in _field_lines(field))
    tag = "ol" if field["kind"] == "ordered" else "ul"
    items = "".join(f"<li>{escape(item)}</li>" for item in field["items"])
    return f"<{tag}>{items}</{tag}>"


def compose(
    rendered: dict[str, Any],
    facts: Iterable[dict[str, str]],
    *,
    caretaker: PracujCaretaker,
    rate: str,
) -> PracujMail:
    """Mail z treści zakładki Pracuj.pl — tej samej, którą sprawdza kontrola.

    Tekst i HTML składa jedna funkcja z tych samych pól; HTML z odpowiedzi
    renderu nie jest wklejany, każdy napis przechodzi przez ``escape``.
    """
    title = rendered["title"]
    fields = [
        f
        for f in rendered["pracuj"]["fields"]
        if f["key"] != "title" and (f["text"].strip() or f["items"])
    ]
    header = [
        (fact["label"], fact["value"])
        for key in _FACT_KEYS
        for fact in facts
        if fact["key"] == key and fact["value"]
    ]
    header.append(("Stawka", rate))
    intro = "proszę o wstawienie ogłoszenia na Pracuj.pl:"
    closing = "Po publikacji proszę o link do ogłoszenia."

    text_parts = [
        _greeting(caretaker),
        "",
        intro,
        "",
        title,
        "",
        *(f"{label}: {value}" for label, value in header),
    ]
    for field in fields:
        text_parts += ["", field["label"], *_field_lines(field)]
    text_parts += ["", closing]

    html_parts = [
        f"<p>{escape(_greeting(caretaker))}</p>",
        f"<p>{escape(intro)}</p>",
        f"<p><b>{escape(title)}</b></p>",
        "<p>"
        + "<br>".join(f"{escape(label)}: {escape(value)}" for label, value in header)
        + "</p>",
    ]
    for field in fields:
        html_parts.append(f"<p><b>{escape(field['label'])}</b></p>{_field_html(field)}")
    html_parts.append(f"<p>{escape(closing)}</p>")

    return PracujMail(
        subject=f"Prośba o publikację ogłoszenia: {title}"[:255],
        body_text="\n".join(text_parts),
        body_html="".join(html_parts),
    )


def _business_days_after(day: date, today: date, tz: str) -> int:
    zone = ZoneInfo(tz)
    count = 0
    cursor = day + timedelta(days=1)
    while cursor <= today:
        if is_business_day(datetime.combine(cursor, time(12), zone), tz):
            count += 1
        cursor += timedelta(days=1)
    return count


def is_waiting(sent_at: datetime, today: date, tz: str = DEFAULT_TZ) -> bool:
    """Opiekun ma czas: dzień wysyłki i ``QUIET_BUSINESS_DAYS`` dni roboczych po nim."""
    sent_day = sent_at.astimezone(ZoneInfo(tz)).date()
    return _business_days_after(sent_day, today, tz) <= QUIET_BUSINESS_DAYS


async def last_requests(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, PracujRequest]:
    """Ostatni mail do opiekuna per rekrutacja (wiersze Historii zdarzeń)."""
    ids = sorted(set(job_ids))
    if not ids:
        return {}
    latest = (
        select(
            Activity.entity_id.label("job_id"),
            func.max(Activity.id).label("activity_id"),
        )
        .where(
            Activity.entity_type == "job",
            Activity.entity_id.in_(ids),
            Activity.action == ACTION,
        )
        .group_by(Activity.entity_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Activity, User.name, User.email)
            .join(latest, latest.c.activity_id == Activity.id)
            .outerjoin(User, User.id == Activity.user_id)
        )
    ).all()
    return {
        activity.entity_id: PracujRequest(
            sent_at=activity.created_at,
            sent_by=activity.user_id,
            sent_by_name=name or email,
            to=(activity.details or {}).get("to"),
        )
        for activity, name, email in rows
    }


__all__ = [
    "ACTION",
    "PracujMail",
    "PracujRequest",
    "QUIET_BUSINESS_DAYS",
    "RateInvalid",
    "compose",
    "is_waiting",
    "last_requests",
    "rate_text",
]
