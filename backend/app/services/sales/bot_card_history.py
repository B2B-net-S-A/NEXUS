"""Historia karty firmy: co boty wpisały, co zostawiły i skąd to wzięły.

Decyzja Artura z 13.11.2026: wynik bota trafia na kartę od razu, bez
„Przyjmij” i bez oznaczeń przy polach. Jedyny ślad pochodzenia to ta historia
w zakładce Aktywności. Źródłem są wiersze ``sales_bot_results`` rodzajów
``enrich`` (pola karty, ``payload.outcomes``) i ``people`` (osoby dodane na
mapę). Bez migracji: wiersz wyniku już ma firmę, czas, wartości i źródła.
Rejestry państwowe (biała lista VAT, KRS) piszą swoją historię w
``custom_fields["registry_history"]`` karty (``registry_cards.py``), a
``registry_entries`` zamienia ją na te same wpisy.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Zapis od razu”).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

from app.services.sales import contact_sync, research_import
from app.services.sales.bot_tasks import enrich, people

BOT_NAMES = {enrich.KIND: "Dane firm", people.KIND: "Kontakty"}
#: Zmiany w zakładce Kontakty (``contact_sync``): autor według źródła biegu.
CONTACT_BOT_NAMES = {contact_sync.BOT: "Kontakty", contact_sync.COGNISM: "Cognism"}
#: Rodzaje wyników z osobami: widzi je tylko konto z „Sprzedaż: edycja”.
PEOPLE_KINDS = (people.KIND, contact_sync.KIND)

FIELD_LABELS = {
    "domain": "Domena",
    "website_url": "Strona",
    "nip": "NIP",
    "hq_city": "Miasto",
    "industry": "Branża",
    "tier": "Wielkość",
    "parent_name": "Firma matka",
    "legal_name": "Nazwa prawna",
    "krs": "KRS",
    "regon": "REGON",
    "hq_country": "Kraj",
    "state": "Stan w rejestrze",
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


def contact_lines(payload: dict[str, Any]) -> list[Line]:
    """Zmiany kontaktów: nowa osoba, nowsze stanowisko, odejście, powrót, porządek nazwiska."""

    lines: list[Line] = []
    for item in payload.get("changes") or []:
        name = item.get("name") or "—"
        change = item.get("change")
        source = item.get("source_url")
        before, after = item.get("before"), item.get("after")
        if change == contact_sync.ADDED:
            lines.append(Line(name, after, source=source, note="nowy kontakt"))
        elif change == contact_sync.TITLE:
            lines.append(
                Line(name, after, before, source, note="nowsze stanowisko ze źródła")
            )
        elif change == contact_sync.LEFT:
            lines.append(
                Line(name, "nie pracuje", before, source, note=_left_note(item))
            )
        elif change == contact_sync.BACK:
            lines.append(Line(name, "pracuje", "nie pracuje", source, note=after))
        elif change == contact_sync.SPLIT:
            lines.append(
                Line(name, after, before, note="imię i nazwisko osobno od stanowiska")
            )
    return lines


def _left_note(item: dict[str, Any]) -> Optional[str]:
    as_of = item.get("as_of")
    return f"według źródła z {as_of}" if as_of else None


REGISTRY_BOT = "Rejestry"
REGISTRY_SOURCES = {"vat": "biała lista VAT", "krs": "KRS"}
STATE_LABELS = {
    "removed": "firma wykreślona z KRS",
    "liquidation": "firma w likwidacji",
    "bankruptcy": "firma w upadłości",
    "vat_removed": "firma wykreślona z rejestru VAT",
}
TAKEN_NOTE = "jest już na innej karcie, scal karty ręcznie"


def _registry_line(line: dict[str, Any]) -> Optional[Line]:
    key = line.get("field")
    result = line.get("result")
    label = FIELD_LABELS.get(str(key))
    if label is None:
        return None
    after = _shown(str(key), line.get("after"))
    before = _shown(str(key), line.get("before"))
    source = line.get("url")
    if result == "applied":
        return Line(label, after, before, source)
    if result == "kept":
        return Line(label, after, before, source, note=KEPT_NOTE)
    if result == "taken":
        return Line(
            label,
            after,
            source=source,
            note=TAKEN_NOTE,
            other_company_id=line.get("other_id"),
            other_company_name=line.get("other_name"),
        )
    if result == "inactive":
        shown = STATE_LABELS.get(str(line.get("after")), after)
        removed_on = line.get("removed_on")
        note = f"od {removed_on}, karta zostaje" if removed_on else "karta zostaje"
        return Line(label, shown, source=source, note=note)
    return None


def registry_entries(custom_fields: Optional[dict[str, Any]]) -> list[Entry]:
    """Wpisy rejestrów z ``custom_fields["registry_history"]`` karty."""

    entries: list[Entry] = []
    for item in (custom_fields or {}).get("registry_history") or []:
        if not isinstance(item, dict):
            continue
        try:
            at = datetime.fromisoformat(str(item.get("at")))
        except ValueError:
            continue
        lines = [
            line
            for line in (
                _registry_line(raw)
                for raw in item.get("lines") or []
                if isinstance(raw, dict)
            )
            if line is not None
        ]
        if lines:
            source = REGISTRY_SOURCES.get(str(item.get("source")))
            bot = f"{REGISTRY_BOT} ({source})" if source else REGISTRY_BOT
            entries.append(Entry(at=at, bot=bot, lines=lines))
    return entries


def build(
    rows: list[tuple[str, datetime, dict[str, Any]]],
    *,
    with_people: bool,
    extra: Sequence[Entry] = (),
) -> list[Entry]:
    """Wpisy od najnowszego; wynik bez żadnej linii nie trafia do historii.

    ``with_people`` = konto z „Sprzedaż: edycja” (mapa osób wymaga edycji).
    ``extra``: gotowe wpisy spoza ``sales_bot_results`` (rejestry państwowe).
    """

    entries: list[Entry] = list(extra)
    for kind, at, payload in rows:
        if kind == enrich.KIND:
            lines = enrich_lines(payload or {})
        elif kind == people.KIND and with_people:
            lines = people_lines(payload or {})
        elif kind == contact_sync.KIND and with_people:
            lines = contact_lines(payload or {})
        else:
            continue
        if lines:
            bot = (
                CONTACT_BOT_NAMES.get((payload or {}).get("source"), "Kontakty")
                if kind == contact_sync.KIND
                else BOT_NAMES[kind]
            )
            entries.append(Entry(at=at, bot=bot, lines=lines))
    return sorted(entries, key=lambda entry: entry.at, reverse=True)
