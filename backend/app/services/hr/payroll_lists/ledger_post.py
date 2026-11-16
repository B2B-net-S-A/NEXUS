"""Dekret listy płac NEXUSA do księgi (K7b): dokument LP w buforze, tylko dla Płac.

Ten sam dekret co import listy z Enovy (K3c, ``ledger/payroll_lists.decree``):
Wn wynagrodzenia / Ma rozrachunki z tytułu wynagrodzeń (brutto), potrącenia
(składki pracownika, zdrowotna, zaliczka, PPK pracownika) na ZUS, US i PPK,
składki i PPK pracodawcy w koszt. Na rozrachunkach zostaje netto do wypłaty.

* Tylko zatwierdzona lista. Źródło ``payroll_list_nexus`` /
  ``RRRR-MM:<numer listy>``; ponowny dekret przebudowuje szkic, zatwierdzony
  LP poprawia się stornem (409).
* **Jeden miesiąc = jedno źródło LP**: przy żywym LP z Enovy za ten miesiąc
  dekret odmawia (409), a import z Enovy odmawia przy LP z NEXUSA.
* Wrażliwość ``payroll`` (D2): dokument widzą i zatwierdzają Płace i admin.
* Anulowanie listy usuwa szkic LP; przy zatwierdzonym LP anulowanie = 409
  (najpierw storno w księdze).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll_lists import PayrollList, PayrollListLine
from app.models.ledger import LedgerDocument
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.hr import audit
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollForbidden,
)
from app.services.ledger import documents, engine
from app.services.ledger import payroll_lists as ledger_payroll
from app.services.ledger import settings as ledger_settings
from app.services.ledger.documents import DocumentSpec
from app.services.ledger.payroll_lists import NEXUS_SOURCE_TYPE, PayrollRow

#: Pole wyniku silnika → klucz kwoty dekretu K3c.
RESULT_KEYS: dict[str, str] = {
    "gross": "gross",
    "pension_employee": "emp_pension",
    "disability_employee": "emp_disability",
    "sickness_employee": "emp_sickness",
    "health": "health",
    "pit": "pit",
    "ppk_employee": "ppk_emp",
    "net": "net",
    "pension_employer": "er_pension",
    "disability_employer": "er_disability",
    "accident_employer": "accident",
    "labour_fund": "fp",
    "fgsp": "fgsp",
    "ppk_employer": "ppk_er",
}


def grosze(raw: Any) -> int:
    from decimal import Decimal

    return int((Decimal(str(raw or "0")) * 100).to_integral_value())


def row_of(line: PayrollListLine) -> PayrollRow:
    result = line.result or {}
    return PayrollRow(
        line=int(line.id or 0),
        mpk=None,
        amounts={key: grosze(result.get(field)) for field, key in RESULT_KEYS.items()},
        person=line.person_name,
    )


def source_id(lst: PayrollList) -> str:
    return f"{lst.year}-{lst.month:02d}:{lst.number}"


async def _lines(db: AsyncSession, list_id: int) -> list[PayrollListLine]:
    return list(
        await db.scalars(
            select(PayrollListLine)
            .where(PayrollListLine.list_id == list_id)
            .order_by(PayrollListLine.id)
        )
    )


async def document_for(db: AsyncSession, lst: PayrollList) -> Optional[LedgerDocument]:
    return await db.scalar(
        select(LedgerDocument).where(
            LedgerDocument.source_type == NEXUS_SOURCE_TYPE,
            LedgerDocument.source_id == source_id(lst),
            LedgerDocument.reversed_by_id.is_(None),
        )
    )


def _ledger_error(exc: LedgerError) -> PayrollError:
    return PayrollError(exc.message, exc.status)


async def post(db: AsyncSession, *, actor: User, lst: PayrollList) -> dict[str, Any]:
    """LP z zatwierdzonej listy w buforze księgi (bez commita)."""

    settings = await ledger_settings.load(db)
    if not ledger_settings.module_open(actor, settings, "ledger"):
        raise PayrollConflict(
            "Księga NEXUSA jest wyłączona — dekret listy płac powstanie po jej włączeniu.",
            code="ledger_disabled",
        )
    viewer = documents.viewer_for(actor, settings)
    if not viewer.payroll:
        raise PayrollForbidden("Dekret listy płac robią Płace albo administrator.")
    if lst.status != "approved":
        raise PayrollConflict(
            "Do księgi idzie tylko zatwierdzona lista płac.", code="list_not_approved"
        )
    enova = await ledger_payroll.live_lp_for_month(
        db, ledger_payroll.SOURCE_TYPE, lst.year, lst.month
    )
    if enova is not None:
        raise PayrollConflict(
            f"Za {lst.month:02d}.{lst.year} jest już LP z listy z Enovy ("
            f"{enova.number}) — jeden miesiąc ma jedno źródło LP. W okresie "
            "równoległym zostaje LP z Enovy; po przełączeniu zrób jego storno.",
            code="lp_enova_exists",
        )
    rows = [row_of(line) for line in await _lines(db, lst.id)]
    lines, problems = ledger_payroll.decree(rows, settings.payroll)
    if lines:
        plan = await documents.load_plan(db)
        problems.extend(
            engine.check(lines, plan, max_lines=engine.lines_max("LP")).issues
        )
    if problems:
        raise PayrollError(" ".join(problems), 422, code="lp_problems")
    existing = await document_for(db, lst)
    if existing is not None:
        if existing.status != "draft":
            raise PayrollConflict(
                f"LP tej listy jest zatwierdzony (pozycja {existing.journal_no}) — "
                "popraw go stornem w księdze.",
                code="lp_approved",
            )
        try:
            await documents.delete_draft(db, existing.id, viewer=viewer)
        except LedgerError as exc:
            raise _ledger_error(exc) from None
    end = ledger_payroll.last_day(lst.year, lst.month)
    spec = DocumentSpec(
        doc_type="LP",
        op_date=end,
        doc_date=lst.pay_date,
        lines=lines,
        description=f"Lista płac {lst.number} za {lst.month:02d}.{lst.year} (NEXUS)",
        source_type=NEXUS_SOURCE_TYPE,
        source_id=source_id(lst),
        sensitivity="payroll",
        meta={"list": lst.number, "list_id": lst.id, "rows": len(rows)},
    )
    try:
        doc = await documents.create_draft(db, spec, actor_id=actor.id)
    except LedgerError as exc:
        raise _ledger_error(exc) from None
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_list",
        entity_id=lst.id,
        action="payroll_list_posted",
        sensitivity="payroll",
        details={"number": lst.number, "document_id": doc.id},
    )
    total, _mpk = ledger_payroll.totals(rows)
    return {
        "document": {"id": doc.id, "number": doc.number, "status": doc.status},
        "lines": [
            {
                "side": line.side,
                "account": line.account,
                "amount": line.amount,
                "description": line.description,
            }
            for line in lines
        ],
        "totals": {
            "gross": total.gross,
            "employee": total.employee,
            "employer": total.employer,
            "zus": total.zus,
            "pit": total.pit,
            "ppk": total.ppk,
            "net": total.net,
        },
    }


async def on_cancel(db: AsyncSession, *, actor: User, lst: PayrollList) -> None:
    """Anulowanie listy: szkic LP znika, zatwierdzony LP blokuje (409)."""

    doc = await document_for(db, lst)
    if doc is None:
        return
    if doc.status != "draft":
        raise PayrollConflict(
            f"LP tej listy jest zatwierdzony w księdze (pozycja {doc.journal_no}) — "
            "najpierw storno w księdze, potem anulowanie listy.",
            code="lp_approved",
        )
    settings = await ledger_settings.load(db)
    viewer = documents.viewer_for(actor, settings)
    try:
        await documents.delete_draft(db, doc.id, viewer=viewer)
    except LedgerError as exc:
        raise _ledger_error(exc) from None


async def status_of(db: AsyncSession, lst: PayrollList) -> Optional[dict[str, Any]]:
    doc = await document_for(db, lst)
    if doc is None:
        return None
    return {"id": doc.id, "number": doc.number, "status": doc.status}


__all__ = ["RESULT_KEYS", "on_cancel", "post", "row_of", "source_id", "status_of"]
