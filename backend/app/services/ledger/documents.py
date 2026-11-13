"""Dokumenty księgi (K1): bufor, zatwierdzenie z numerem dziennika, storno, listy.

* **Bufor** (``draft``): dokument z poprawnym dekretem (Wn = Ma, konta z planu)
  w otwartym okresie. Można go poprawić albo usunąć. Każda zmiana zostaje
  w śladzie (``ledger_events``).
* **Zatwierdzenie** robi osoba z listy „Księgowi” albo admin. Dokument dostaje
  kolejną pozycję dziennika roku (``journal_no``, ciągła numeracja w roku pod
  blokadą wiersza roku) i od tej chwili jest trwały — pilnuje tego też
  wyzwalacz w bazie (``ledger_schema``).
* **Storno** zatwierdzonego dokumentu: nowy dokument ``ST`` w otwartym okresie
  z tymi samymi kontami i stronami i kwotami z przeciwnym znakiem (storno
  czerwone), od razu zatwierdzony. Oryginał dostaje ``reversed_by_id``; jego
  źródło (np. faktura) może po stornie dostać nowy dokument.
* **Dokumenty płacowe** (``sensitivity = 'payroll'``: listy płac, faktury osób
  zespołu) widzą tylko Płace i admin (D2) — osoba bez Płac nie ma ich na
  liście ani w licznikach, karta daje 404, zatwierdzenie odmawia 404. Sumy
  kont w obrotach i saldach je obejmują, bo księga musi się bilansować.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.finance_posting import FinanceAccount
from app.models.ledger import (
    LedgerDocument,
    LedgerEvent,
    LedgerLine,
    LedgerPeriod,
    LedgerYear,
)
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.hr.payroll_access import is_payroll
from app.services.ledger import engine, years
from app.services.ledger.engine import LineIn, PlanAccount
from app.services.ledger.settings import LedgerSettings, can_approve, is_admin
from app.services.ledger_schema import DOC_TYPES, NUMBER_MAX

PAGE_MAX = 100
PAYROLL_HIDDEN_DETAIL = "Nie ma takiego dokumentu."
EVENT_LABELS: dict[str, str] = {
    "create": "Utworzono",
    "update": "Zmieniono",
    "approve": "Zatwierdzono",
    "reverse": "Storno",
    "delete": "Usunięto szkic",
    "close": "Zamknięto okres",
    "reopen": "Otwarto okres",
    "mode": "Zmieniono tryb roku",
}


@dataclass(frozen=True)
class Viewer:
    user_id: int
    admin: bool
    payroll: bool
    approver: bool


def viewer_for(user: User, settings: LedgerSettings) -> Viewer:
    return Viewer(
        user_id=user.id,
        admin=is_admin(user),
        payroll=is_payroll(user),
        approver=can_approve(user, settings),
    )


@dataclass
class DocumentSpec:
    doc_type: str
    op_date: date
    doc_date: date
    lines: list[LineIn]
    number: Optional[str] = None
    description: str = ""
    counterparty_id: Optional[int] = None
    currency: str = "PLN"
    fx_rate: Optional[Decimal] = None
    fx_date: Optional[date] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    sensitivity: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)


# ── Plan kont ────────────────────────────────────────────────────────────────


async def load_plan(db: AsyncSession) -> dict[str, PlanAccount]:
    rows = await db.execute(
        select(
            FinanceAccount.number,
            FinanceAccount.name,
            FinanceAccount.kind,
            FinanceAccount.active,
            FinanceAccount.dictionary,
        )
    )
    return engine.plan_from_rows(rows.all())


def account_name(number: str, plan: dict[str, PlanAccount]) -> Optional[str]:
    if number in plan:
        return plan[number].name
    resolved, _ = engine.resolve(number, plan)
    if resolved is not None:
        return f"{resolved.plan.name} · analityka"
    return None


# ── Zapis ────────────────────────────────────────────────────────────────────


def _visible(doc: LedgerDocument, viewer: Viewer) -> bool:
    return doc.sensitivity is None or viewer.payroll


async def _visible_document(
    db: AsyncSession, doc_id: int, viewer: Viewer, *, lock: bool = False
) -> LedgerDocument:
    doc = await db.get(
        LedgerDocument, doc_id, with_for_update=lock, populate_existing=lock
    )
    if doc is None or not _visible(doc, viewer):
        raise LedgerError(PAYROLL_HIDDEN_DETAIL, status=404)
    return doc


async def _counterparty_exists(
    db: AsyncSession, counterparty_id: Optional[int]
) -> None:
    if counterparty_id is None:
        return
    found = await db.scalar(
        select(FinanceCounterparty.id).where(FinanceCounterparty.id == counterparty_id)
    )
    if found is None:
        raise LedgerError("Nie ma takiego kontrahenta w kartotece.", status=422)


async def _event(
    db: AsyncSession,
    action: str,
    *,
    actor_id: Optional[int],
    document_id: Optional[int] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    db.add(
        LedgerEvent(
            action=action,
            document_id=document_id,
            actor_id=actor_id,
            detail=detail or {},
        )
    )


def _check_spec(spec: DocumentSpec) -> None:
    if spec.doc_type not in DOC_TYPES or spec.doc_type == "ST":
        raise LedgerError("Niepoprawny typ dokumentu.", status=422)
    if spec.currency != "PLN" and (spec.fx_rate is None or spec.fx_date is None):
        raise LedgerError(
            "Dokument w walucie obcej potrzebuje kursu i jego daty.", status=422
        )
    if (spec.source_type is None) != (spec.source_id is None):
        raise LedgerError("Źródło dokumentu wymaga typu i identyfikatora.", status=422)


async def _next_seq(db: AsyncSession, doc_type: str, period_id: int) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(LedgerDocument)
        .where(
            LedgerDocument.period_id == period_id, LedgerDocument.doc_type == doc_type
        )
    )
    return int(count or 0) + 1


async def _write_lines(
    db: AsyncSession, doc: LedgerDocument, lines: list[LineIn]
) -> None:
    for line_no, line in enumerate(lines, start=1):
        db.add(
            LedgerLine(
                document_id=doc.id,
                line_no=line_no,
                side=line.side,
                account=line.account,
                amount=line.amount,
                currency=line.currency,
                amount_cur=line.amount_cur,
                counterparty_id=line.counterparty_id,
                mpk=line.mpk,
                description=line.description,
            )
        )
    await db.flush()


async def create_draft(
    db: AsyncSession, spec: DocumentSpec, *, actor_id: Optional[int]
) -> LedgerDocument:
    """Nowy dokument w buforze (bez commita). Źródło z dokumentem = 409."""

    _check_spec(spec)
    year, period = await years.period_for(db, spec.op_date)
    plan = await load_plan(db)
    result = engine.ensure_valid(spec.lines, plan)
    await _counterparty_exists(db, spec.counterparty_id)
    for line in spec.lines:
        await _counterparty_exists(db, line.counterparty_id)
    if spec.source_type is not None:
        existing = await db.scalar(
            select(LedgerDocument.id).where(
                LedgerDocument.source_type == spec.source_type,
                LedgerDocument.source_id == spec.source_id,
                LedgerDocument.reversed_by_id.is_(None),
            )
        )
        if existing is not None:
            raise LedgerError("To źródło ma już dokument w księdze.", status=409)
    await years.lock_year(db, year.id)
    number = engine.clean_number(spec.number) or engine.auto_number(
        spec.doc_type, await _next_seq(db, spec.doc_type, period.id), spec.op_date
    )
    doc = LedgerDocument(
        year_id=year.id,
        period_id=period.id,
        doc_type=spec.doc_type,
        number=number,
        op_date=spec.op_date,
        doc_date=spec.doc_date,
        description=engine.clean_description(spec.description),
        counterparty_id=spec.counterparty_id,
        source_type=spec.source_type,
        source_id=spec.source_id,
        currency=spec.currency,
        fx_rate=spec.fx_rate,
        fx_date=spec.fx_date,
        status="draft",
        debit_total=result.debit,
        credit_total=result.credit,
        sensitivity=spec.sensitivity,
        meta=spec.meta,
        created_by=actor_id,
    )
    db.add(doc)
    await db.flush()
    await _write_lines(db, doc, spec.lines)
    await _event(
        db,
        "create",
        actor_id=actor_id,
        document_id=doc.id,
        detail={"number": doc.number, "type": doc.doc_type, "total": result.debit},
    )
    await db.flush()
    return doc


async def update_draft(
    db: AsyncSession, doc_id: int, spec: DocumentSpec, *, viewer: Viewer
) -> LedgerDocument:
    """Poprawka dokumentu z bufora (bez commita): nowe daty, opis i pozycje."""

    _check_spec(spec)
    doc = await _visible_document(db, doc_id, viewer, lock=True)
    if doc.status != "draft":
        raise LedgerError("Zatwierdzony dokument popraw stornem.", status=409)
    if doc.source_type is not None:
        # Dekret dokumentu ze źródła (faktura, wyciąg, lista płac) liczy źródło —
        # ręczna poprawka w buforze rozjechałaby się z nim przy następnym
        # przeliczeniu (przegląd bezpieczeństwa 14.11.2026).
        raise LedgerError(
            "Dokument ze źródła poprawia się w źródle — tu można go tylko zatwierdzić "
            "albo usunąć.",
            status=409,
        )
    await years.period_for(db, doc.op_date)
    year, period = await years.period_for(db, spec.op_date)
    plan = await load_plan(db)
    result = engine.ensure_valid(spec.lines, plan)
    await _counterparty_exists(db, spec.counterparty_id)
    for line in spec.lines:
        await _counterparty_exists(db, line.counterparty_id)
    before = {
        "total": doc.debit_total,
        "op_date": doc.op_date.isoformat(),
        "lines": None,
    }
    old_lines = (
        await db.scalars(select(LedgerLine).where(LedgerLine.document_id == doc.id))
    ).all()
    before["lines"] = len(old_lines)
    for line in old_lines:
        await db.delete(line)
    await db.flush()
    doc.year_id = year.id
    doc.period_id = period.id
    doc.doc_type = spec.doc_type
    doc.number = engine.clean_number(spec.number) or doc.number
    doc.op_date = spec.op_date
    doc.doc_date = spec.doc_date
    doc.description = engine.clean_description(spec.description)
    doc.counterparty_id = spec.counterparty_id
    doc.currency = spec.currency
    doc.fx_rate = spec.fx_rate
    doc.fx_date = spec.fx_date
    doc.debit_total = result.debit
    doc.credit_total = result.credit
    await db.flush()
    await _write_lines(db, doc, spec.lines)
    await _event(
        db,
        "update",
        actor_id=viewer.user_id,
        document_id=doc.id,
        detail={
            "before": before,
            "after": {
                "total": result.debit,
                "op_date": spec.op_date.isoformat(),
                "lines": len(spec.lines),
            },
        },
    )
    await db.flush()
    return doc


async def delete_draft(db: AsyncSession, doc_id: int, *, viewer: Viewer) -> None:
    """Usunięcie szkicu (bez commita); ślad zostaje z numerem i typem."""

    doc = await _visible_document(db, doc_id, viewer, lock=True)
    if doc.status != "draft":
        raise LedgerError(
            "Zatwierdzonego dokumentu nie usuwa się — zrób storno.", status=409
        )
    await years.period_for(db, doc.op_date)
    await _event(
        db,
        "delete",
        actor_id=viewer.user_id,
        document_id=doc.id,
        detail={"number": doc.number, "type": doc.doc_type, "total": doc.debit_total},
    )
    await db.flush()
    await db.delete(doc)
    await db.flush()


async def _lines_of(db: AsyncSession, doc_id: int) -> list[LineIn]:
    rows = (
        await db.scalars(
            select(LedgerLine)
            .where(LedgerLine.document_id == doc_id)
            .order_by(LedgerLine.line_no)
        )
    ).all()
    return [
        LineIn(
            side=row.side,
            account=row.account,
            amount=row.amount,
            description=row.description,
            counterparty_id=row.counterparty_id,
            mpk=row.mpk,
            currency=row.currency,
            amount_cur=row.amount_cur,
        )
        for row in rows
    ]


async def _approval_refusal(
    db: AsyncSession,
    doc: LedgerDocument,
    viewer: Viewer,
    plan: dict[str, PlanAccount],
    year: LedgerYear,
) -> Optional[tuple[int, str]]:
    if not _visible(doc, viewer):
        return 404, PAYROLL_HIDDEN_DETAIL
    if doc.status != "draft":
        return 409, f"Dokument {doc.number} jest już zatwierdzony."
    if year.status != "open":
        return 409, f"Rok obrotowy {year.year} jest zamknięty."
    try:
        await years.period_for(db, doc.op_date)
    except LedgerError as exc:
        return exc.status, exc.message
    result = engine.check(await _lines_of(db, doc.id), plan)
    if result.issues:
        return 422, f"Dokument {doc.number}: {result.issues[0]}"
    return None


async def approve(
    db: AsyncSession, ids: list[int], *, viewer: Viewer, now: datetime
) -> dict[str, Any]:
    """Zatwierdzenie z bufora (bez commita): kolejne pozycje dziennika roku.

    Dokumenty idą w kolejności daty operacji i id; każdy z błędem wraca
    w ``refused`` z kodem i powodem, reszta przechodzi.
    """

    if not viewer.approver:
        raise LedgerError(
            "Dokumenty zatwierdza osoba z listy „Księgowi” albo administrator.",
            status=403,
        )
    unique = sorted(set(ids))
    docs = (
        await db.scalars(
            select(LedgerDocument)
            .where(LedgerDocument.id.in_(unique or [0]))
            .order_by(LedgerDocument.op_date, LedgerDocument.id)
        )
    ).all()
    found = {doc.id for doc in docs}
    refused: list[dict[str, Any]] = [
        {"id": doc_id, "status": 404, "detail": PAYROLL_HIDDEN_DETAIL}
        for doc_id in unique
        if doc_id not in found
    ]
    approved: list[dict[str, Any]] = []
    plan = await load_plan(db)
    for year_id in sorted({doc.year_id for doc in docs}):
        year = await years.lock_year(db, year_id)
        for candidate in [doc for doc in docs if doc.year_id == year_id]:
            doc = await db.get(
                LedgerDocument,
                candidate.id,
                with_for_update=True,
                populate_existing=True,
            )
            if doc is None:  # pragma: no cover — skasowany w międzyczasie
                refused.append(
                    {"id": candidate.id, "status": 404, "detail": PAYROLL_HIDDEN_DETAIL}
                )
                continue
            refusal = await _approval_refusal(db, doc, viewer, plan, year)
            if refusal is not None:
                refused.append(
                    {"id": doc.id, "status": refusal[0], "detail": refusal[1]}
                )
                continue
            doc.status = "approved"
            doc.journal_no = year.next_journal_no
            doc.approved_by = viewer.user_id
            doc.approved_at = now
            year.next_journal_no += 1
            await _event(
                db,
                "approve",
                actor_id=viewer.user_id,
                document_id=doc.id,
                detail={"journal_no": doc.journal_no, "number": doc.number},
            )
            approved.append({"id": doc.id, "journal_no": doc.journal_no})
            await db.flush()
    refused.sort(key=lambda item: item["id"])
    return {"approved": approved, "refused": refused}


def _document_label(doc: LedgerDocument) -> str:
    """„PK 2/10/2026” albo „FVZ FV/12/2026” — typ raz, nawet gdy jest w numerze."""

    if doc.number.upper().startswith(f"{doc.doc_type} "):
        return doc.number
    return f"{doc.doc_type} {doc.number}"


async def reverse(
    db: AsyncSession,
    doc_id: int,
    *,
    viewer: Viewer,
    day: date,
    reason: str,
    now: datetime,
) -> LedgerDocument:
    """Storno czerwone zatwierdzonego dokumentu (bez commita)."""

    if not viewer.approver:
        raise LedgerError(
            "Storno robi osoba z listy „Księgowi” albo administrator.", status=403
        )
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise LedgerError("Podaj powód storna.", status=422)
    original = await _visible_document(db, doc_id, viewer)
    year, period = await years.period_for(db, day)
    await years.lock_year(db, year.id)
    original = await _visible_document(db, doc_id, viewer, lock=True)
    if original.status != "approved":
        raise LedgerError(
            "Szkic popraw albo usuń — storno jest dla zatwierdzonych.", status=409
        )
    if original.doc_type == "ST" or original.reverses_id is not None:
        raise LedgerError(
            "Storna się nie odwraca — zaksięguj dokument ponownie.", status=409
        )
    if original.reversed_by_id is not None:
        raise LedgerError("Ten dokument ma już storno.", status=409)
    lines = engine.reversal(await _lines_of(db, original.id))
    debit, credit = engine.totals(lines)
    storno = LedgerDocument(
        year_id=year.id,
        period_id=period.id,
        doc_type="ST",
        number=f"ST {original.number}"[:NUMBER_MAX],
        op_date=day,
        doc_date=day,
        description=engine.clean_description(
            f"Storno {_document_label(original)}: {reason}"
        ),
        counterparty_id=original.counterparty_id,
        currency=original.currency,
        fx_rate=original.fx_rate,
        fx_date=original.fx_date,
        status="draft",
        debit_total=debit,
        credit_total=credit,
        sensitivity=original.sensitivity,
        reverses_id=original.id,
        meta={"reason": reason},
        created_by=viewer.user_id,
    )
    db.add(storno)
    await db.flush()
    await _write_lines(db, storno, lines)
    year_row = await years.lock_year(db, year.id)
    storno.status = "approved"
    storno.journal_no = year_row.next_journal_no
    storno.approved_by = viewer.user_id
    storno.approved_at = now
    year_row.next_journal_no += 1
    await db.flush()
    original.reversed_by_id = storno.id
    await _event(
        db,
        "reverse",
        actor_id=viewer.user_id,
        document_id=original.id,
        detail={
            "storno_id": storno.id,
            "reason": reason,
            "journal_no": storno.journal_no,
        },
    )
    await _event(
        db,
        "create",
        actor_id=viewer.user_id,
        document_id=storno.id,
        detail={"number": storno.number, "type": "ST", "reverses": original.id},
    )
    await db.flush()
    return storno


# ── Odczyt ───────────────────────────────────────────────────────────────────


def _filtered(
    query: Select[Any],
    viewer: Viewer,
    *,
    year_id: int,
    month: Optional[int],
    doc_type: Optional[str],
    status: Optional[str],
    needle: Optional[str],
) -> Select[Any]:
    query = query.where(LedgerDocument.year_id == year_id)
    if month is not None:
        query = query.where(
            LedgerDocument.period_id.in_(
                select(LedgerPeriod.id).where(
                    LedgerPeriod.year_id == year_id, LedgerPeriod.month == month
                )
            )
        )
    if not viewer.payroll:
        query = query.where(LedgerDocument.sensitivity.is_(None))
    if doc_type:
        query = query.where(LedgerDocument.doc_type == doc_type)
    if status:
        query = query.where(LedgerDocument.status == status)
    if needle:
        pattern = f"%{needle}%"
        query = query.where(
            or_(
                LedgerDocument.number.ilike(pattern),
                LedgerDocument.description.ilike(pattern),
                LedgerDocument.counterparty_id.in_(
                    select(FinanceCounterparty.id).where(
                        FinanceCounterparty.name.ilike(pattern)
                    )
                ),
            )
        )
    return query


async def _names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
    return {user_id: name or "—" for user_id, name in rows.all()}


async def _counterparty_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(FinanceCounterparty.id, FinanceCounterparty.name).where(
            FinanceCounterparty.id.in_(ids)
        )
    )
    return dict(rows.all())


def document_payload(
    doc: LedgerDocument,
    viewer: Viewer,
    *,
    names: dict[int, str],
    counterparties: dict[int, str],
    period_open: bool,
) -> dict[str, Any]:
    reversible = (
        doc.status == "approved"
        and doc.reversed_by_id is None
        and doc.reverses_id is None
        and doc.doc_type != "ST"
    )
    return {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "type_label": engine.DOC_TYPE_LABELS[doc.doc_type],
        "number": doc.number,
        "op_date": doc.op_date.isoformat(),
        "doc_date": doc.doc_date.isoformat(),
        "description": doc.description,
        "counterparty": (
            {"id": doc.counterparty_id, "name": counterparties.get(doc.counterparty_id)}
            if doc.counterparty_id
            else None
        ),
        "source": (
            {"type": doc.source_type, "id": doc.source_id} if doc.source_type else None
        ),
        "currency": doc.currency,
        "fx_rate": str(doc.fx_rate) if doc.fx_rate is not None else None,
        "fx_date": doc.fx_date.isoformat() if doc.fx_date else None,
        "status": doc.status,
        "journal_no": doc.journal_no,
        "debit_total": doc.debit_total,
        "credit_total": doc.credit_total,
        "sensitivity": doc.sensitivity,
        "reverses_id": doc.reverses_id,
        "reversed_by_id": doc.reversed_by_id,
        "created_by_name": names.get(doc.created_by) if doc.created_by else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "approved_by_name": names.get(doc.approved_by) if doc.approved_by else None,
        "approved_at": doc.approved_at.isoformat() if doc.approved_at else None,
        "can_edit": doc.status == "draft" and period_open,
        "can_approve": doc.status == "draft" and period_open and viewer.approver,
        "can_reverse": reversible and viewer.approver,
    }


async def _open_periods(db: AsyncSession, period_ids: set[int]) -> set[int]:
    if not period_ids:
        return set()
    rows = await db.execute(
        select(LedgerPeriod.id)
        .join(LedgerYear, LedgerYear.id == LedgerPeriod.year_id)
        .where(
            LedgerPeriod.id.in_(period_ids),
            LedgerPeriod.status == "open",
            LedgerYear.status == "open",
        )
    )
    return set(rows.scalars().all())


async def list_documents(
    db: AsyncSession,
    viewer: Viewer,
    *,
    year: int,
    month: Optional[int] = None,
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    needle: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    year_row = await db.scalar(select(LedgerYear).where(LedgerYear.year == year))
    if year_row is None:
        return {"items": [], "total": 0, "counts": {}, "drafts": 0, "year": None}
    needle = " ".join((needle or "").split())[:80] or None
    base = _filtered(
        select(LedgerDocument),
        viewer,
        year_id=year_row.id,
        month=month,
        doc_type=doc_type,
        status=status,
        needle=needle,
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await db.scalars(
            base.order_by(LedgerDocument.op_date, LedgerDocument.id)
            .offset(max(0, offset))
            .limit(max(1, min(limit, PAGE_MAX)))
        )
    ).all()
    count_query = _filtered(
        select(LedgerDocument.doc_type, LedgerDocument.status, func.count()),
        viewer,
        year_id=year_row.id,
        month=month,
        doc_type=None,
        status=None,
        needle=needle,
    ).group_by(LedgerDocument.doc_type, LedgerDocument.status)
    counts: dict[str, int] = {}
    drafts = 0
    for doc_type_value, status_value, count in (await db.execute(count_query)).all():
        counts[doc_type_value] = counts.get(doc_type_value, 0) + count
        if status_value == "draft":
            drafts += count
    names = await _names(
        db,
        {doc.created_by for doc in rows if doc.created_by}
        | {doc.approved_by for doc in rows if doc.approved_by},
    )
    counterparties = await _counterparty_names(
        db, {doc.counterparty_id for doc in rows if doc.counterparty_id}
    )
    open_periods = await _open_periods(db, {doc.period_id for doc in rows})
    return {
        "items": [
            document_payload(
                doc,
                viewer,
                names=names,
                counterparties=counterparties,
                period_open=doc.period_id in open_periods,
            )
            for doc in rows
        ],
        "total": int(total or 0),
        "counts": counts,
        "drafts": drafts,
        "year": year_row.year,
    }


async def document_card(
    db: AsyncSession, viewer: Viewer, doc_id: int
) -> dict[str, Any]:
    doc = await _visible_document(db, doc_id, viewer)
    lines = (
        await db.scalars(
            select(LedgerLine)
            .where(LedgerLine.document_id == doc.id)
            .order_by(LedgerLine.line_no)
        )
    ).all()
    events = (
        await db.scalars(
            select(LedgerEvent)
            .where(LedgerEvent.document_id == doc.id)
            .order_by(LedgerEvent.id)
        )
    ).all()
    plan = await load_plan(db)
    names = await _names(
        db,
        {doc.created_by, doc.approved_by, *(event.actor_id for event in events)}
        - {None},  # type: ignore[arg-type]
    )
    counterparties = await _counterparty_names(
        db,
        {doc.counterparty_id, *(line.counterparty_id for line in lines)} - {None},  # type: ignore[arg-type]
    )
    open_periods = await _open_periods(db, {doc.period_id})
    payload = document_payload(
        doc,
        viewer,
        names=names,
        counterparties=counterparties,
        period_open=doc.period_id in open_periods,
    )
    payload["lines"] = [
        {
            "line_no": line.line_no,
            "side": line.side,
            "side_label": engine.SIDE_LABELS[line.side],
            "account": line.account,
            "account_name": account_name(line.account, plan),
            "amount": line.amount,
            "currency": line.currency,
            "amount_cur": line.amount_cur,
            "counterparty": (
                {
                    "id": line.counterparty_id,
                    "name": counterparties.get(line.counterparty_id),
                }
                if line.counterparty_id
                else None
            ),
            "mpk": line.mpk,
            "description": line.description,
        }
        for line in lines
    ]
    payload["events"] = [
        {
            "action": event.action,
            "label": EVENT_LABELS.get(event.action, event.action),
            "actor_name": names.get(event.actor_id) if event.actor_id else None,
            "at": event.created_at.isoformat() if event.created_at else None,
            "detail": event.detail,
        }
        for event in events
    ]
    return payload
