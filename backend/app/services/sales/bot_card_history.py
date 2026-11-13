"""Historia karty firmy: co boty wpisały, co zostawiły i skąd to wzięły.

Decyzja Artura z 13.11.2026: wynik bota trafia na kartę od razu, bez
„Przyjmij” i bez oznaczeń przy polach. Jedyny ślad pochodzenia to ta historia
w zakładce Aktywności. Źródłem są wiersze ``sales_bot_results`` rodzajów
``enrich`` (pola karty, ``payload.outcomes``) i ``people`` (osoby dodane na
mapę). Bez migracji: wiersz wyniku już ma firmę, czas, wartości i źródła.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Zapis od razu”).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.services.sales import research_import
from app.services.sales.bot_tasks import enrich, people

BOT_NAMES = {enrich.KIND: "Dane firm", people.KIND: "Kontakty"}

FIELD_LABELS = {
    "domain": "Domena",
    "website_url": "Strona",
    "nip": "NIP",
    "hq_city": "Miasto",
    "industry": "Branża",
    "tier": "Wielkość",
    "parent_name": "Firma matka",
}
TIER_LABELS = {"smb": "Mała", "mid_market": "Średnia", "enterprise": "Duża"}
KEPT_NOTE = "na karcie zostaje wartość wpisana ręcznie"
ADDED_NOTE = "dodana do Kontaktów"


@dataclass(frozen=True)
class Line:
    label: str
    after: Optional[str]
    before: Optional[str] = None
    source: Optional[str] = None
    note: Optional[str] = None
    other_company_id: Optional[int] = None
    other_company_name: Optional[str] = None


@dataclass(frozen=True)
class Entry:
    at: datetime
    bot: str
    lines: list[Line] = field(default_factory=list)


def _shown(key: str, value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if key == "tier":
        return TIER_LABELS.get(str(value), str(value))
    return str(value)


def enrich_lines(payload: dict[str, Any]) -> list[Line]:
    fields: dict[str, dict[str, Any]] = payload.get("fields") or {}
    outcomes: dict[str, dict[str, Any]] = payload.get("outcomes") or {}
    decisions: dict[str, str] = payload.get("decisions") or {}
    lines: list[Line] = []
    for key in enrich.FIELDS:
        item = fields.get(key)
        if not item:
            continue
        label = FIELD_LABELS[key]
        value = _shown(key, item.get("value"))
        source = item.get("source")
        outcome = outcomes.get(key)
        if outcome is None:
            # Wynik sprzed 13.11: liczy się tylko pole przyjęte przez handlowca.
            if decisions.get(key) == "accepted":
                lines.append(Line(label, value, source=source))
            continue
        result = outcome.get("result")
        if result == enrich.APPLIED:
            lines.append(
                Line(label, value, _shown(key, outcome.get("previous")), source)
            )
        elif result == enrich.KEPT:
            lines.append(
                Line(
                    label,
                    value,
                    _shown(key, outcome.get("current")),
                    source,
                    note=KEPT_NOTE,
                )
            )
        elif result == enrich.TAKEN:
            lines.append(
                Line(
                    label,
                    value,
                    source=source,
                    note="jest już na innej karcie, scal karty ręcznie",
                    other_company_id=outcome.get("other_id"),
                    other_company_name=outcome.get("other_name"),
                )
            )
        elif result == enrich.SKIPPED:
            lines.append(Line(label, value, source=source, note=outcome.get("note")))
    return lines


def people_lines(payload: dict[str, Any]) -> list[Line]:
    outcomes: dict[str, str] = payload.get("outcomes") or {}
    lines: list[Line] = []
    for person in payload.get("people") or []:
        if outcomes.get(str(person.get("line"))) != research_import.ADDED:
            continue
        lines.append(
            Line(
                person.get("full_name") or "—",
                person.get("title") or None,
                source=person.get("source_url"),
                note=ADDED_NOTE,
            )
        )
    return lines


def build(
    rows: list[tuple[str, datetime, dict[str, Any]]], *, with_people: bool
) -> list[Entry]:
    """Wpisy od najnowszego; wynik bez żadnej linii nie trafia do historii.

    ``with_people`` = konto z „Sprzedaż: edycja” (mapa osób wymaga edycji).
    """

    entries: list[Entry] = []
    for kind, at, payload in rows:
        if kind == enrich.KIND:
            lines = enrich_lines(payload or {})
        elif kind == people.KIND and with_people:
            lines = people_lines(payload or {})
        else:
            continue
        if lines:
            entries.append(Entry(at=at, bot=BOT_NAMES[kind], lines=lines))
    return sorted(entries, key=lambda entry: entry.at, reverse=True)
