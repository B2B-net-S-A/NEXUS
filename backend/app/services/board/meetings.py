"""Posiedzenia Rady (R5): pakiet informacji Zarządu i kalendarz obowiązków.

**Pakiet** to zamrożony obraz liczb na dzień wysłania: pulpit (faktury),
budżet roku, ostatnie sprawozdanie roczne z wskaźnikami, dokumenty i wpisy
KRS od poprzedniego posiedzenia. Zamrożony, bo faktury kosztowe spływają
z opóźnieniem — Rada ma widzieć to samo, o czym rozmawiała.

**Obowiązki** roku obrotowego (spółka akcyjna), liczone z danych modułu —
każda pozycja mówi, skąd wie, że jest zrobiona:

* sprawozdanie finansowe za rok poprzedni — do 31.03 (art. 52 ust. 1 UoR),
* ocena sprawozdań przez Radę i sprawozdanie Rady — przed ZWZ
  (art. 382 § 3 i § 3¹ KSH),
* zatwierdzenie przez ZWZ — do 30.06 (art. 395 § 1 KSH),
* złożenie do KRS — 15 dni od zatwierdzenia (art. 69 ust. 1 UoR),
* co najmniej trzy posiedzenia Rady w roku obrotowym (art. 389 § 3 KSH).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_document import (
    BoardDocument,
    BoardFinancialStatement,
    BoardMeeting,
)
from app.models.notification import NotificationType
from app.services.board import budget as budget_service
from app.services.board import financials
from app.services.board import krs as krs_service
from app.services.board import summary as summary_service
from app.services.board.notify import recipient_ids
from app.services.hr.notify import notify_each

MIN_MEETINGS = 3
SOON_DAYS = 30
PACK_VERSION = 1
KIND_LABELS = {"meeting": "posiedzenie", "remote": "zdalnie", "circular": "tryb pisemny"}


def _plain(value: Any) -> Any:
    """JSON bez dat i Decimal (pakiet trafia do JSONB)."""

    return json.loads(json.dumps(value, default=str))


def _doc_brief(doc: BoardDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "category": doc.category,
        "organ": doc.organ,
        "number": doc.number,
        "title": doc.title,
        "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
        "has_file": bool(doc.file_path),
    }


async def previous_meeting(
    db: AsyncSession, meeting: BoardMeeting
) -> Optional[BoardMeeting]:
    return (
        await db.execute(
            select(BoardMeeting)
            .where(
                BoardMeeting.id != meeting.id,
                BoardMeeting.status == "held",
                BoardMeeting.held_on < meeting.held_on,
            )
            .order_by(BoardMeeting.held_on.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def build_pack(
    db: AsyncSession, meeting: BoardMeeting, today: date
) -> dict[str, Any]:
    previous = await previous_meeting(db, meeting)
    since = previous.held_on if previous else today - timedelta(days=90)
    documents = (
        await db.execute(
            select(BoardDocument)
            .where(
                or_(
                    BoardDocument.doc_date > since,
                    BoardDocument.created_at
                    >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc),
                )
            )
            .order_by(BoardDocument.doc_date.desc().nulls_last(), BoardDocument.id.desc())
            .limit(100)
        )
    ).scalars()
    snapshot = await krs_service.latest_snapshot(db, krs_service.company_krs())
    krs_entries: list[dict[str, Any]] = []
    if snapshot is not None:
        parsed = krs_service.parse_odpis(snapshot.payload)
        krs_entries = [
            {
                "number": entry.number,
                "day": entry.day.isoformat() if entry.day else None,
                "description": entry.description,
            }
            for entry in parsed.entries
            if entry.day is not None and entry.day > since
        ]
    analysis = await financials.analysis_view(db, today)
    full_years = [y for y in analysis["years"] if y.get("partial_months") is None]
    return _plain(
        {
            "version": PACK_VERSION,
            "as_of": today,
            "since": since,
            "previous_meeting": {"id": previous.id, "held_on": previous.held_on}
            if previous
            else None,
            "summary": await summary_service.company_summary(db, today),
            "budget": await budget_service.budget_view(db, today.year, today),
            "statement": full_years[-1] if full_years else None,
            "documents": [_doc_brief(doc) for doc in documents],
            "krs_entries": krs_entries,
        }
    )


async def notify_pack(db: AsyncSession, meeting: BoardMeeting) -> int:
    day = meeting.held_on.strftime("%d.%m.%Y")
    return await notify_each(
        db,
        await recipient_ids(db),
        title=f"Pakiet na posiedzenie Rady {day}",
        message=f"Zarząd przygotował materiały: {meeting.title}.",
        ntype=NotificationType.board_meeting_pack,
        link=f"/rada?tab=posiedzenia&posiedzenie={meeting.id}",
        related_entity_type="board_meeting",
        related_entity_id=meeting.id,
        log_tag="board",
    )


# ── Obowiązki roku ───────────────────────────────────────────────────────────


def _status(done: bool, due: date, today: date) -> str:
    if done:
        return "done"
    if today > due:
        return "overdue"
    if (due - today).days <= SOON_DAYS:
        return "soon"
    return "pending"


def _mentions(doc: BoardDocument, *needles: str) -> bool:
    text = f"{doc.title} {doc.subject or ''}".lower()
    return any(needle in text for needle in needles)


def obligations(
    *,
    today: date,
    filings: list[krs_service.KrsFiling],
    statement_years: set[int],
    documents: list[BoardDocument],
    meetings: list[BoardMeeting],
) -> list[dict[str, Any]]:
    """Obowiązki roku ``today.year`` (sprawozdanie za rok poprzedni)."""

    year = today.year
    prior = year - 1
    by_kind = {(f.kind, f.year): f for f in filings}
    in_year = [d for d in documents if d.doc_date and d.doc_date.year == year]

    out: list[dict[str, Any]] = []

    filed = by_kind.get(("financial_statement", prior))
    prepared = prior in statement_years or filed is not None
    out.append(
        {
            "key": "statement_prepared",
            "label": f"Sprawozdanie finansowe za {prior} sporządzone przez Zarząd",
            "legal": "art. 52 ust. 1 ustawy o rachunkowości",
            "due": date(year, 3, 31),
            "done": prepared,
            "evidence": "sprawozdanie w Analizie albo wzmianka w KRS"
            if prepared
            else "brak sprawozdania w Analizie i w KRS",
        }
    )

    assessment = next(
        (
            d
            for d in in_year
            if d.category == "resolution_supervisory"
            and _mentions(d, "sprawozd", "ocen")
        ),
        None,
    )
    out.append(
        {
            "key": "board_assessment",
            "label": f"Ocena sprawozdań za {prior} i sprawozdanie Rady dla ZWZ",
            "legal": "art. 382 § 3 i § 3¹ KSH",
            "due": date(year, 6, 30),
            "done": assessment is not None,
            "evidence": f"uchwała Rady „{assessment.title}”"
            if assessment
            else "brak uchwały Rady o sprawozdaniach w Dokumentach",
        }
    )

    approval = by_kind.get(("approval", prior))
    approval_doc = next(
        (
            d
            for d in in_year
            if d.category == "resolution_general" and _mentions(d, "zatwierdz")
        ),
        None,
    )
    out.append(
        {
            "key": "agm_approval",
            "label": f"Zwyczajne Walne Zgromadzenie zatwierdza sprawozdanie za {prior}",
            "legal": "art. 395 § 1 KSH",
            "due": date(year, 6, 30),
            "done": approval is not None or approval_doc is not None,
            "evidence": "wzmianka o uchwale zatwierdzającej w KRS"
            if approval
            else (
                f"uchwała WZA „{approval_doc.title}”"
                if approval_doc
                else "brak uchwały zatwierdzającej (KRS, Dokumenty)"
            ),
        }
    )

    approved_on = (approval_doc.doc_date if approval_doc else None) or date(year, 6, 30)
    out.append(
        {
            "key": "krs_filing",
            "label": f"Złożenie sprawozdania za {prior} do Repozytorium (KRS)",
            "legal": "art. 69 ust. 1 ustawy o rachunkowości",
            "due": approved_on + timedelta(days=15),
            "done": filed is not None,
            "evidence": f"wzmianka w KRS z {filed.filed_on.isoformat()}"
            if filed and filed.filed_on
            else ("wzmianka w KRS" if filed else "brak wzmianki w KRS"),
        }
    )

    held = [m for m in meetings if m.status == "held" and m.held_on.year == year]
    planned = [
        m
        for m in meetings
        if m.status == "planned" and m.held_on.year == year and m.held_on >= today
    ]
    out.append(
        {
            "key": "meetings",
            "label": f"Co najmniej {MIN_MEETINGS} posiedzenia Rady w {year}",
            "legal": "art. 389 § 3 KSH",
            "due": date(year, 12, 31),
            "done": len(held) >= MIN_MEETINGS,
            "evidence": f"odbyte: {len(held)}, zaplanowane: {len(planned)}",
        }
    )
    for item in out:
        item["status"] = _status(item["done"], item["due"], today)
        item["due"] = item["due"].isoformat()
    return out


async def obligations_view(db: AsyncSession, today: date) -> list[dict[str, Any]]:
    snapshot = await krs_service.latest_snapshot(db, krs_service.company_krs())
    filings = (
        krs_service.parse_odpis(snapshot.payload).filings if snapshot is not None else []
    )
    statement_years = set(
        (
            await db.execute(
                select(BoardFinancialStatement.year).where(
                    BoardFinancialStatement.source.in_(("xml", "manual"))
                )
            )
        ).scalars()
    )
    documents = list(
        (
            await db.execute(
                select(BoardDocument).where(
                    BoardDocument.category.in_(
                        ("resolution_supervisory", "resolution_general")
                    )
                )
            )
        ).scalars()
    )
    meetings = list((await db.execute(select(BoardMeeting))).scalars())
    return obligations(
        today=today,
        filings=filings,
        statement_years=statement_years,
        documents=documents,
        meetings=meetings,
    )
