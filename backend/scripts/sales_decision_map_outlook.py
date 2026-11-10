#!/usr/bin/env python3
"""Jednorazowe uzupełnienie map decyzyjnych wstecz według poczty i spotkań z Outlooka.

Automat (``services/sales/decision_map_outlook.py``) po wdrożeniu liczy tylko nowe
zdarzenia. Ten skrypt przechodzi całą historię aktywności z Outlooka dla osób z map
otwartych szans tymi samymi regułami: status nigdy się nie cofa, a sprzeciw i ręczna
zmiana mają pierwszeństwo.

Drugi krok (decyzja Artura z 10.11.2026): adres e-mail wpisany tylko na mapie trafia
do pustego pola kontaktu tej osoby, regułą okna osoby z 02.11.2026. Niczego nie
nadpisuje, nie zakłada kontaktów, a kontakt w archiwum zostaje. Bez adresu
w kartotece synchronizacja Outlooka nie rozpoznaje poczty z tą osobą.

Domyślnie NA SUCHO: transakcja ``READ ONLY``, raport, wycofanie. ``--apply`` zapisuje
w jednej transakcji i tylko z licznikami z biegu na sucho (``--expect-people``,
``--expect-emails``), więc dane, które zmieniły się od akceptacji, kończą bieg bez
zapisu. Na produkcji ``--apply`` dopiero po „tak” Artura. Drugi bieg nie ma już czego
zmienić.

Uruchomienie (z ``backend/``, baza z ``DATABASE_URL``)::

    python -m scripts.sales_decision_map_outlook
    python -m scripts.sales_decision_map_outlook --apply --expect-people 4 --expect-emails 39

Raport to same liczby i identyfikatory, bez nazwisk i adresów: repo i logi Actions są publiczne.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesContact, SalesOpportunity
from app.services.sales import decision_map, history
from app.services.sales import decision_map_outlook as map_outlook
from app.services.sales.motion import load_contact_index, match_contacts
from app.services.sales_schema import OpportunityEventKind

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2

#: Limit kolumny ``sales_contacts.email``; dłuższy adres zostaje tylko na mapie.
_CONTACT_EMAIL_LIMIT = 255


class Refused(Exception):
    """Warunek biegu niespełniony; nic nie zostało zapisane."""


@dataclass(frozen=True)
class Options:
    apply: bool = False
    expect_people: Optional[int] = None
    expect_emails: Optional[int] = None


@dataclass
class Report:
    mode: str = "dry-run"
    open_maps: int = 0
    people: int = 0
    people_with_contact: int = 0
    skipped_objection: int = 0
    outlook_events: dict[str, int] = field(default_factory=dict)
    people_to_change: int = 0
    transitions: dict[str, int] = field(default_factory=dict)
    last_contact_only: int = 0
    opportunity_ids: list[int] = field(default_factory=list)
    contact_emails_to_fill: int = 0
    contact_ids_to_fill: list[int] = field(default_factory=list)
    changed: int = 0
    emails_filled: int = 0


@dataclass(frozen=True)
class _EmailFill:
    opportunity_id: int
    company_id: int
    entry: dict[str, Any]
    contact_id: int


async def _emails_to_fill(db: AsyncSession) -> list[_EmailFill]:
    """Osoby z adresem na mapie, których aktywny kontakt nie ma adresu."""

    rows = (
        await db.execute(
            select(
                SalesOpportunity.id,
                SalesOpportunity.company_id,
                SalesOpportunity.custom_fields,
            )
            .where(*map_outlook._open_maps())
            .order_by(SalesOpportunity.id)
        )
    ).all()
    maps = [
        (row.id, row.company_id, decision_map.decision_entries(row.custom_fields))
        for row in rows
    ]
    index = await load_contact_index(
        db, [(company, entries) for _, company, entries in maps]
    )
    candidates = [
        _EmailFill(opportunity_id, company_id, entry, contact_id)
        for opportunity_id, company_id, entries in maps
        for entry, contact_id in zip(
            entries, match_contacts(index, company_id, entries)
        )
        if contact_id is not None
        and isinstance(entry.get("email"), str)
        and entry["email"].strip()
        and len(entry["email"]) <= _CONTACT_EMAIL_LIMIT
    ]
    if not candidates:
        return []
    fillable = set(
        (
            await db.scalars(
                select(SalesContact.id).where(
                    SalesContact.id.in_({c.contact_id for c in candidates}),
                    SalesContact.archived_at.is_(None),
                    SalesContact.email.is_(None) | (SalesContact.email == ""),
                )
            )
        ).all()
    )
    planned: list[_EmailFill] = []
    for candidate in candidates:
        # Ta sama osoba na dwóch mapach: adres dostaje raz, z pierwszej.
        if candidate.contact_id in fillable:
            fillable.discard(candidate.contact_id)
            planned.append(candidate)
    return planned


async def _fill_emails(db: AsyncSession, planned: Sequence[_EmailFill]) -> int:
    filled_count = 0
    for item in planned:
        filled = await decision_map.fill_contact(
            db, item.company_id, item.entry, ["email"]
        )
        if not filled:
            continue
        filled_count += 1
        history.record(
            db,
            opportunity_id=item.opportunity_id,
            user_id=None,
            kind=OpportunityEventKind.updated,
            field="decision_map_contact",
            new_value=f"{item.entry.get('name')}: {', '.join(filled)}",
        )
    return filled_count


def _report(
    options: Options, planned: map_outlook.Report, emails: Sequence[_EmailFill]
) -> Report:
    status_changes = [c for c in planned.changes if c.old_status != c.new_status]
    return Report(
        mode="apply" if options.apply else "dry-run",
        open_maps=planned.open_maps,
        people=planned.people,
        people_with_contact=planned.people_with_contact,
        skipped_objection=planned.skipped_objection,
        outlook_events=planned.events,
        people_to_change=len(planned.changes),
        transitions=dict(
            Counter(f"{c.old_status}->{c.new_status}" for c in status_changes)
        ),
        last_contact_only=len(planned.changes) - len(status_changes),
        opportunity_ids=sorted({c.opportunity_id for c in planned.changes}),
        contact_emails_to_fill=len(emails),
        contact_ids_to_fill=sorted(item.contact_id for item in emails),
    )


def _check_counters(options: Options, report: Report) -> None:
    if options.expect_people is None or options.expect_emails is None:
        raise Refused(
            "--apply wymaga --expect-people i --expect-emails z biegu na sucho"
        )
    if options.expect_people != report.people_to_change:
        raise Refused(
            f"--expect-people {options.expect_people}, a jest {report.people_to_change}"
        )
    if options.expect_emails != report.contact_emails_to_fill:
        raise Refused(
            f"--expect-emails {options.expect_emails}, "
            f"a jest {report.contact_emails_to_fill}"
        )


async def run(options: Options, now: Optional[datetime] = None) -> Report:
    moment = now or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        if not options.apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        emails = await _emails_to_fill(db)
        planned = await map_outlook.sync(db, now=moment, since=None, apply=False)
        report = _report(options, planned, emails)
        if not options.apply:
            await db.rollback()
            return report
        _check_counters(options, report)
        report.emails_filled = await _fill_emails(db, emails)
        applied = await map_outlook.sync(db, now=moment, since=None, apply=True)
        report.changed = len(applied.changes)
        await db.commit()
        return report


def _parse(argv: Sequence[str]) -> Options:
    parser = argparse.ArgumentParser(
        description="Mapy decyzyjne według historii poczty i spotkań z Outlooka"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-people", type=int)
    parser.add_argument("--expect-emails", type=int)
    args = parser.parse_args(argv)
    return Options(**vars(args))


def main(argv: Optional[Sequence[str]] = None) -> int:
    options = _parse(sys.argv[1:] if argv is None else argv)
    try:
        report = asyncio.run(run(options))
    except Refused as exc:
        print(f"Odmowa, nic nie zapisano: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # log może być publiczny, więc bez treści wyjątku
        print(f"Błąd: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
