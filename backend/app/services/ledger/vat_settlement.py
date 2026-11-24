"""Rozliczenie VAT na koniec miesiąca (K5b-3c): dokument typu VAT z JPK_V7M.

Decyzje Artura z 15–16.11.2026: dokument przenosi saldo VAT należnego (222)
i naliczonego (221) okresu na konto „VAT do zapłaty” z Kont wyciągów
(``bank.vat_account`` — rozrachunek z urzędem skarbowym), więc 221 i 222 zerują
się co miesiąc; nadwyżka naliczonego do przeniesienia (P_62) też idzie na to
konto (saldo Wn), a nie zostaje na 221. Różnica groszy (deklaracja w pełnych
złotych, konta w groszach) idzie na konta różnic z zaokrągleń VAT z zakładki
VAT (pozostałe przychody / koszty operacyjne, np. 760 / 761).

* **Kwoty** z JPK miesiąca (ostatni wysłany, inaczej ostatni nieunieważniony):
  VAT należny i naliczony z ewidencji (grosze), do zapłaty = P_38 − (P_48 − P_39)
  w złotych — bez nadwyżki z poprzedniego okresu, bo ta już jest saldem Wn
  konta „VAT do zapłaty”; saldo tego konta wychodzi wtedy samo jako P_51 albo
  P_62.
* **Księga przed dokumentem**: obroty kont 221/222 i VAT należnego importu
  usług (226, ``vat.output_accounts``; z analityką) w zatwierdzonych
  dokumentach miesiąca, bez rozliczeń VAT i BO, z tą samą zasadą co rejestr
  („stan dziś”: dokument ze stornem i samo storno wypadają). Obroty różne od
  podatku w JPK = problem z wyjaśnieniem, dokument nie powstaje. Pozycje
  dokumentu idą per konto z obrotów (analityka 221-1 zeruje się sama).
* **Dokument** (źródło ``vat_settlement`` / RRRR-MM) w buforze, zatwierdza lista
  „Księgowi”; ponowne „Przygotuj” podmienia szkic, zatwierdzonego się nie rusza
  — różnica od dzisiejszych kwot (korekta JPK po rozliczeniu) to flaga
  ``changed``: storno i ponowne „Przygotuj” (jak wycena walut K4c-2).
* **D2**: obroty z fakturami osób zespołu = dokument płacowy
  (``sensitivity = 'payroll'``). Przygotowuje go osoba z listy „Księgowi”
  z Płacami albo administrator (jak JPK); kwoty widzi osoba z Płacami albo
  administrator, reszta — stan i numer dokumentu.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerDocument, LedgerLine, LedgerVatFile
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.posting import money_pl
from app.services.ledger import documents, jpk, sources, vat
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.settings import (
    BANK_ACCOUNT_FIELDS,
    VAT_ACCOUNT_FIELDS,
    LedgerSettings,
)

SOURCE = documents.VAT_SETTLEMENT_SOURCE
DOC_TYPE = "VAT"
#: Dokumenty spoza obrotów okresu: rozliczenia VAT i bilans otwarcia.
SKIPPED_TYPES = ("VAT", "BO")
PREPARE_ONLY = (
    "Rozliczenie VAT obejmuje faktury osób zespołu — przygotowuje je osoba z listy "
    "„Księgowi” z Płacami albo administrator."
)
APPROVED = (
    "Dokument {number} jest zatwierdzony, a dziś wychodzą inne kwoty — najpierw "
    "jego storno."
)
EXPLAIN = (
    "Zwykle to zapis na koncie VAT spoza rejestru (lista „do sprawdzenia” "
    "rejestrów) albo dokument zmieniony po przygotowaniu JPK — wtedy korekta JPK."
)
HIDDEN_PROBLEM = (
    "Obroty kont VAT w księdze różnią się od JPK — szczegóły widzi osoba z Płacami "
    "albo administrator."
)


@dataclass(frozen=True)
class Basis:
    """Kwoty z JPK: podatek z ewidencji (grosze) i saldo deklaracji (zł)."""

    output_tax: int
    input_tax: int
    #: P_38 − (P_48 − P_39): + = do zapłaty, − = nadwyżka naliczonego miesiąca.
    due: int


def basis_of(totals: dict[str, Any]) -> Optional[Basis]:
    """``None`` = wersja JPK bez sum podatku z ewidencji."""

    if "output_tax" not in totals or "input_tax" not in totals:
        return None
    due = int(totals.get("P_38", 0)) - (
        int(totals.get("P_48", 0)) - int(totals.get("P_39", 0))
    )
    return Basis(int(totals["output_tax"]), int(totals["input_tax"]), due)


def rounding(basis: Basis) -> int:
    """Różnica groszy: + = deklaracja wyżej niż konta (koszt), − = przychód."""

    return basis.due * 100 - (basis.output_tax - basis.input_tax)


def settlement_lines(
    output: dict[str, int],
    input_: dict[str, int],
    basis: Basis,
    *,
    tax_account: str,
    gain_account: str,
    loss_account: str,
    text_: str,
) -> list[LineIn]:
    """Pozycje dokumentu: 222 i 221 per konto z obrotów, saldo na „VAT do
    zapłaty” w pełnych złotych, grosze na konta różnic z zaokrągleń.

    ``output`` — obroty Ma − Wn kont VAT należnego, ``input_`` — Wn − Ma kont
    VAT naliczonego (zgodne z JPK; tu tylko zamiana na strony)."""

    lines: list[LineIn] = []
    for account, amount in sorted(output.items()):
        if amount:
            side = "debit" if amount > 0 else "credit"
            lines.append(LineIn(side, account, abs(amount), text_))
    for account, amount in sorted(input_.items()):
        if amount:
            side = "credit" if amount > 0 else "debit"
            lines.append(LineIn(side, account, abs(amount), text_))
    if basis.due:
        side = "credit" if basis.due > 0 else "debit"
        lines.append(LineIn(side, tax_account, abs(basis.due) * 100, text_))
    diff = rounding(basis)
    if diff > 0:
        lines.append(LineIn("debit", loss_account, diff, text_))
    elif diff < 0:
        lines.append(LineIn("credit", gain_account, -diff, text_))
    return lines


def ledger_problem(
    output: int, input_: int, basis: Basis, version: int
) -> Optional[str]:
    """Obroty kont VAT okresu różne od podatku w JPK — z wyjaśnieniem."""

    parts = []
    if output != basis.output_tax:
        parts.append(
            f"VAT należny: księga {money_pl(output)}, JPK {money_pl(basis.output_tax)}"
        )
    if input_ != basis.input_tax:
        parts.append(
            f"VAT naliczony: księga {money_pl(input_)}, JPK {money_pl(basis.input_tax)}"
        )
    if not parts:
        return None
    return (
        f"Obroty kont VAT okresu różnią się od JPK (wersja {version}) — "
        f"{'; '.join(parts)}. {EXPLAIN}"
    )


def key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def missing_accounts(settings: LedgerSettings) -> list[str]:
    missing = []
    if not settings.bank.vat_account:
        missing.append(
            f"{BANK_ACCOUNT_FIELDS['vat_account'][1]} (Ustawienia → Konta wyciągów)"
        )
    for field in ("rounding_gain_account", "rounding_loss_account"):
        if not getattr(settings.vat, field):
            missing.append(f"{VAT_ACCOUNT_FIELDS[field][1]} (zakładka VAT → Konta VAT)")
    return missing


def _matches(account: str, base: str) -> bool:
    return bool(base) and (account == base or account.startswith(base + "-"))


def same_account(
    settings: LedgerSettings, outputs: tuple[str, ...] = ()
) -> Optional[str]:
    """„VAT do zapłaty” nie może być kontem VAT należnego (także importu usług,
    ``outputs``) ani naliczonego."""

    tax = settings.bank.vat_account
    for base in (settings.sales.vat_account, *outputs, settings.vat.input_account):
        if tax and (_matches(tax, base) or _matches(base, tax)):
            return (
                f"Konto „VAT do zapłaty” ({tax}) to konto VAT {base} — ustaw osobne "
                "konto rozrachunku z urzędem skarbowym (Ustawienia → Konta wyciągów)."
            )
    return None


async def basis_file(
    db: AsyncSession, year: int, month: int
) -> Optional[LedgerVatFile]:
    """JPK miesiąca: ostatni wysłany, inaczej ostatni nieunieważniony."""

    files = [
        item for item in await jpk._files(db, year, month) if item.status != "void"
    ]
    sent = [item for item in files if item.status == "sent"]
    return (sent or files)[-1] if files else None


_SIGN = case((LedgerLine.side == "debit", 1), else_=-1)


async def turnovers(
    db: AsyncSession, settings: LedgerSettings, year: int, month: int
) -> tuple[dict[str, int], dict[str, int], bool]:
    """Obroty kont VAT należnego (Ma − Wn) i naliczonego (Wn − Ma) per konto
    i czy są wśród nich dokumenty płacowe (D2) — wszystkie dokumenty, bez
    ograniczeń widoku. VAT należny to też konto importu usług z dekretu FVZ
    (226) — JPK je liczy (``vat.output_accounts``)."""

    input_base = settings.vat.input_account
    output_bases = await vat.output_accounts(db, settings)
    bases = [*output_bases, *([input_base] if input_base else [])]
    if not bases:
        return {}, {}, False
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    on_vat = or_(
        *[
            or_(LedgerLine.account == item, LedgerLine.account.like(f"{item}-%"))
            for item in bases
        ]
    )
    rows = await db.execute(
        select(
            LedgerLine.account,
            func.sum(_SIGN * LedgerLine.amount),
            func.bool_or(LedgerDocument.sensitivity.is_not(None)),
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .where(
            LedgerDocument.status == "approved",
            LedgerDocument.op_date >= start,
            LedgerDocument.op_date < end,
            LedgerDocument.doc_type.not_in(SKIPPED_TYPES),
            # Jak rejestr: dokument ze stornem i samo storno wypadają.
            LedgerDocument.reversed_by_id.is_(None),
            LedgerDocument.reverses_id.is_(None),
            on_vat,
        )
        .group_by(LedgerLine.account)
    )
    output: dict[str, int] = {}
    input_: dict[str, int] = {}
    payroll = False
    for account, amount, sensitive in rows.all():
        payroll = payroll or bool(sensitive)
        if _matches(account, input_base):
            input_[account] = int(amount)
        elif any(_matches(account, base) for base in output_bases):
            output[account] = -int(amount)
    return output, input_, payroll


async def _document(db: AsyncSession, own: str) -> Optional[LedgerDocument]:
    return await db.scalar(
        select(LedgerDocument).where(
            LedgerDocument.source_type == SOURCE,
            LedgerDocument.source_id == own,
            LedgerDocument.reversed_by_id.is_(None),
        )
    )


@dataclass
class Settlement:
    year: int
    month: int
    day: date
    own: str
    file: Optional[LedgerVatFile]
    basis: Optional[Basis]
    output: dict[str, int]
    input_: dict[str, int]
    payroll: bool
    #: Czego brakuje, żeby dokument powstał (do zrobienia).
    blocker: Optional[str]
    #: Księga różni się od JPK (problem, z kwotami).
    problem: Optional[str]
    spec: Optional[DocumentSpec]
    document: Optional[LedgerDocument]

    @property
    def changed(self) -> bool:
        """Zatwierdzony dokument różni się od dzisiejszych kwot (korekta JPK)."""

        doc = self.document
        if doc is None or doc.status != "approved" or self.blocker or self.problem:
            return False
        if self.spec is None:
            return True
        return (doc.meta or {}).get("fingerprint") != sources.fingerprint(self.spec)

    @property
    def stale_draft(self) -> bool:
        """Szkic powstał z innych kwot niż dzisiejsze (np. nowa wersja JPK) —
        „Przygotuj” go przelicza; zatwierdzony bez tego dostałby ``changed``."""

        doc = self.document
        if doc is None or doc.status != "draft" or self.blocker or self.problem:
            return False
        if self.spec is None:
            return True
        return (doc.meta or {}).get("fingerprint") != sources.fingerprint(self.spec)


async def compute(
    db: AsyncSession, settings: LedgerSettings, *, year: int, month: int
) -> Settlement:
    if not 1 <= month <= 12:
        raise LedgerError("Niepoprawny miesiąc.", status=422)
    day = date(year, month, calendar.monthrange(year, month)[1])
    own = key(year, month)
    file = await basis_file(db, year, month)
    output, input_, payroll = await turnovers(db, settings, year, month)
    basis = basis_of(file.totals or {}) if file is not None else None
    blocker: Optional[str] = None
    missing = missing_accounts(settings)
    if missing:
        blocker = f"Do rozliczenia VAT brakuje kont: {'; '.join(missing)}."
    else:
        blocker = same_account(settings, tuple(await vat.output_accounts(db, settings)))
    if blocker is None and file is None:
        blocker = (
            f"Najpierw przygotuj JPK_V7M za {month:02d}.{year} — rozliczenie bierze "
            "kwoty z JPK."
        )
    if blocker is None and file is not None and basis is None:
        blocker = (
            f"JPK wersja {file.version} nie ma sum podatku z ewidencji — przygotuj "
            "nową wersję JPK."
        )
    problem = None
    spec = None
    if blocker is None and basis is not None and file is not None:
        problem = ledger_problem(
            sum(output.values()), sum(input_.values()), basis, file.version
        )
        if problem is None:
            text_ = f"Rozliczenie VAT za {month:02d}.{year}"
            lines = settlement_lines(
                output,
                input_,
                basis,
                tax_account=settings.bank.vat_account,
                gain_account=settings.vat.rounding_gain_account,
                loss_account=settings.vat.rounding_loss_account,
                text_=text_,
            )
            if lines:
                spec = DocumentSpec(
                    doc_type=DOC_TYPE,
                    op_date=day,
                    doc_date=day,
                    lines=lines,
                    description=text_,
                    source_type=SOURCE,
                    source_id=own,
                    sensitivity="payroll" if payroll else None,
                    meta={
                        "vat_settlement": own,
                        "jpk_file_id": file.id,
                        "jpk_version": file.version,
                    },
                )
    return Settlement(
        year=year,
        month=month,
        day=day,
        own=own,
        file=file,
        basis=basis,
        output=output,
        input_=input_,
        payroll=payroll,
        blocker=blocker,
        problem=problem,
        spec=spec,
        document=await _document(db, own),
    )


def _doc_payload(doc: Optional[LedgerDocument]) -> Optional[dict[str, Any]]:
    if doc is None:
        return None
    return {
        "id": doc.id,
        "number": doc.number,
        "status": doc.status,
        "payroll": doc.sensitivity is not None,
    }


async def preview(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, *, year: int, month: int
) -> dict[str, Any]:
    """Rozliczenie VAT miesiąca bez zapisu: JPK, obroty, pozycje, dokument."""

    found = await compute(db, settings, year=year, month=month)
    amounts = jpk.can_download(viewer)
    out: dict[str, Any] = {
        "year": year,
        "month": month,
        "day": found.day.isoformat(),
        "jpk": None
        if found.file is None
        else {
            "id": found.file.id,
            "version": found.file.version,
            "status": found.file.status,
        },
        "document": _doc_payload(found.document),
        "changed": found.changed,
        "stale_draft": found.stale_draft,
        "blocker": found.blocker,
        "problem": (found.problem if amounts else HIDDEN_PROBLEM)
        if found.problem
        else None,
        "to_book": found.spec is not None,
        "payroll": found.payroll,
        "can_prepare": jpk.can_prepare(viewer),
        "can_see_amounts": amounts,
        "amounts": None,
        "lines": [],
    }
    if amounts:
        out["amounts"] = {
            "ledger_output": sum(found.output.values()),
            "ledger_input": sum(found.input_.values()),
            "output_tax": found.basis.output_tax if found.basis else None,
            "input_tax": found.basis.input_tax if found.basis else None,
            "due": found.basis.due if found.basis else None,
            "rounding": rounding(found.basis) if found.basis else None,
        }
        if found.spec is not None:
            plan = await documents.load_plan(db)
            out["lines"] = [
                {
                    "side": line.side,
                    "account": line.account,
                    "name": documents.account_name(line.account, plan) or "",
                    "amount": line.amount,
                }
                for line in found.spec.lines
            ]
    return out


async def prepare(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, *, year: int, month: int
) -> dict[str, Any]:
    """„Przygotuj”: dokument rozliczenia VAT do bufora (bez commita).

    Blokada JPK — wersja JPK nie zmienia się w trakcie (przygotowanie
    i „wysłany” biorą tę samą)."""

    if not jpk.can_prepare(viewer):
        raise LedgerError(PREPARE_ONLY, status=403)
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(jpk.LOCK_KEY))))
    found = await compute(db, settings, year=year, month=month)
    if found.blocker:
        raise LedgerError(found.blocker, status=422)
    if found.problem:
        raise LedgerError(found.problem, status=422)
    existing, spec = found.document, found.spec
    if existing is not None and existing.status != "draft":
        if found.changed:
            raise LedgerError(APPROVED.format(number=existing.number), status=409)
        return {"outcome": "approved", "document": _doc_payload(existing)}
    if spec is None:
        if existing is None:
            return {"outcome": "none", "document": None}
        await documents.delete_draft(db, existing.id, viewer=viewer)
        return {"outcome": "removed", "document": None}
    mark = sources.fingerprint(spec)
    spec.meta["fingerprint"] = mark
    plan = await documents.load_plan(db)
    if existing is not None:
        if (existing.meta or {}).get("fingerprint") == mark:
            return {"outcome": "unchanged", "document": _doc_payload(existing)}
        await documents.delete_draft(db, existing.id, viewer=viewer)
        created = await documents.create_draft(
            db, spec, actor_id=viewer.user_id, plan=plan
        )
        return {"outcome": "rebuilt", "document": _doc_payload(created)}
    created = await documents.create_draft(db, spec, actor_id=viewer.user_id, plan=plan)
    return {"outcome": "created", "document": _doc_payload(created)}
