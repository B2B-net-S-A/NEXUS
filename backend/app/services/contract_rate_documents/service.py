"""Stawki z dokumentów kontraktu: odczyt plików, różnice, wpis i cofnięcie (0739).

* ``pending_documents`` / ``read_document_row`` — pliki umów i aneksów, których
  bieżąca wersja czytnika jeszcze nie widziała (pętla w workerze).
* ``refresh_contract`` — różnica każdego odczytu z harmonogramem
  (``compare.compare``), zapisana w ``finding`` / ``has_finding``. Liczona po
  odczycie, po decyzji i co przebieg pętli, bo harmonogram zmieniają też ludzie.
* ``apply_read`` — kroki z różnicy jako aneksy „Zmiana stawki” tą samą ścieżką
  co okno kontraktu (``apply_contract_amendment``): harmonogram, zamówienia,
  oś czasu. ``user=None`` = wpis automatyczny (flaga
  ``CONTRACT_RATE_DOCS_AUTO_APPLY``, tylko kategoria ``auto``).
* ``undo_auto`` — cofnięcie wpisu automatycznego w ciągu ``UNDO_DAYS`` dni:
  usuwa jego kroki harmonogramu i aneksy, przelicza stawkę i zamówienia.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.contract import Contract, ContractStatus
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_document_rate_read import ContractDocumentRateRead
from app.models.user import User
from app.services import storage_service
from app.services.contract_rate_documents import compare, reader

logger = logging.getLogger(__name__)

UNDO_DAYS = 7
DOC_TYPES = (
    ContractDocumentType.contract,
    ContractDocumentType.annex,
    ContractDocumentType.other,
)
CONTRACT_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)


class RateDocumentError(Exception):
    """Odmowa z komunikatem dla człowieka (trasa zamienia ją na 409/422)."""


@dataclass(frozen=True)
class PendingDocument:
    id: int
    contract_id: int
    filename: str
    file_path: str
    content_type: Optional[str]
    content_sha256: Optional[str]


async def pending_documents(db: AsyncSession, limit: int) -> list[PendingDocument]:
    """Pliki żywych kontraktów bez odczytu bieżącą wersją czytnika."""

    read = ContractDocumentRateRead
    rows = (
        await db.execute(
            select(
                ContractDocument.id,
                ContractDocument.contract_id,
                ContractDocument.filename,
                ContractDocument.file_path,
                ContractDocument.content_type,
                ContractDocument.content_sha256,
            )
            .join(Contract, Contract.id == ContractDocument.contract_id)
            .outerjoin(
                read,
                and_(
                    read.contract_document_id == ContractDocument.id,
                    read.reader_version == reader.READER_VERSION,
                ),
            )
            .where(
                read.id.is_(None),
                ContractDocument.doc_type.in_(DOC_TYPES),
                Contract.status.in_(CONTRACT_STATUSES),
            )
            .order_by(ContractDocument.id.desc())
            .limit(limit)
        )
    ).all()
    return [PendingDocument(*row) for row in rows]


async def read_document_row(
    db: AsyncSession, doc: PendingDocument
) -> ContractDocumentRateRead:
    """Odczyt jednego pliku i zapis wiersza (bez commita)."""

    from app.services.ai_quota import ai_feature  # noqa: PLC0415 — cykl importów

    mime = reader.mime_for(doc.filename, doc.content_type)
    result = reader.ReadResult("skipped")
    sha = doc.content_sha256
    if mime is not None:
        try:
            path = storage_service.get_contract_document_path(doc.file_path)
            content = path.read_bytes()
        except (FileNotFoundError, OSError):
            content = None
        if content is not None:
            sha = sha or hashlib.sha256(content).hexdigest()
            async with ai_feature(db, AIFeatureKey.contract_document_rate_read):
                await db.commit()  # połączenie wraca do puli na czas modelu
                result = await reader.read_document(content, mime, doc.filename)
    row = ContractDocumentRateRead(
        contract_document_id=doc.id,
        contract_id=doc.contract_id,
        content_sha256=sha,
        reader_version=reader.READER_VERSION,
        status=result.status,
        result=result.as_json(),
    )
    db.add(row)
    await db.flush()
    return row


def _contract_rates(contract: Contract) -> compare.ContractRates:
    return compare.ContractRates(
        start_date=contract.start_date,
        currency=(
            contract.rate_candidate_currency or contract.currency or "PLN"
        ).upper(),
        baseline_rate=Decimal(str(contract.rate_candidate))
        if contract.rate_candidate is not None
        else None,
        schedule=tuple(
            compare.ScheduleStep(step.effective_from, Decimal(str(step.rate)))
            for step in contract.candidate_rate_schedule
        ),
    )


async def _load_contract(
    db: AsyncSession, contract_id: int, *, lock: bool = False
) -> Optional[Contract]:
    query = (
        select(Contract)
        .where(Contract.id == contract_id)
        .options(selectinload(Contract.candidate_rate_schedule))
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def _reads_of(
    db: AsyncSession, contract_id: int
) -> list[ContractDocumentRateRead]:
    return list(
        (
            await db.execute(
                select(ContractDocumentRateRead)
                .where(
                    ContractDocumentRateRead.contract_id == contract_id,
                    ContractDocumentRateRead.reader_version == reader.READER_VERSION,
                    ContractDocumentRateRead.status == "read",
                )
                .order_by(ContractDocumentRateRead.id)
            )
        ).scalars()
    )


async def refresh_contract(
    db: AsyncSession, contract_id: int, today: Optional[date] = None
) -> list[ContractDocumentRateRead]:
    """Przelicz różnice wszystkich odczytów kontraktu (bez commita)."""

    contract = await _load_contract(db, contract_id)
    reads = await _reads_of(db, contract_id)
    if contract is None or contract.rate_unit is None:
        return reads
    findings = compare.compare(
        _contract_rates(contract),
        [
            compare.ReadInput(r.id, r.result or {}, dismissed=r.decision == "dismissed")
            for r in reads
        ],
        today or business_today(),
    )
    for row in reads:
        if row.decision in ("applied", "auto_applied"):
            # Wpisany dokument trzyma kroki, które wpisał (pasek „Cofnij”,
            # ``created_step_ids``) — nie nadpisujemy ich zgodnością z dziś.
            row.has_finding = False
            continue
        finding = findings.get(row.id)
        row.finding = finding.as_json() if finding else None
        row.has_finding = finding is not None and row.decision != "dismissed"
    await db.flush()
    return reads


async def contracts_with_reads(db: AsyncSession) -> list[int]:
    return list(
        (
            await db.execute(
                select(ContractDocumentRateRead.contract_id)
                .join(Contract, Contract.id == ContractDocumentRateRead.contract_id)
                .where(
                    ContractDocumentRateRead.reader_version == reader.READER_VERSION,
                    Contract.status.in_(CONTRACT_STATUSES),
                )
                .distinct()
            )
        ).scalars()
    )


def _reason(row: ContractDocumentRateRead, filename: str) -> str:
    return f"Stawka z dokumentu „{filename}”"


async def apply_read(
    db: AsyncSession,
    read_id: int,
    *,
    user: Optional[User],
    expected_contract_id: Optional[int] = None,
    finance_authorized: bool = False,
) -> ContractDocumentRateRead:
    """Kroki z różnicy jako aneksy „Zmiana stawki” (bez commita).

    ``user=None`` = wpis automatyczny: tylko różnica kategorii ``auto``.
    ``finance_authorized`` = wołający sprawdził bramkę kwot sam
    (``effects.can_confirm_rate_annex``).
    Różnicę liczymy od nowa po zablokowaniu kontraktu — człowiek mógł w
    międzyczasie zmienić harmonogram.
    """

    from app.api.contracts import apply_contract_amendment  # noqa: PLC0415 — cykl importów
    from app.schemas.contract_amendment import ContractAmendmentCreate  # noqa: PLC0415

    row = await db.get(ContractDocumentRateRead, read_id)
    if row is None or (
        expected_contract_id is not None and row.contract_id != expected_contract_id
    ):
        raise RateDocumentError("Nie ma takiego odczytu dokumentu.")
    if await _load_contract(db, row.contract_id, lock=True) is None:
        raise RateDocumentError("Kontrakt nie istnieje.")
    await refresh_contract(db, row.contract_id)
    await db.refresh(row)
    if row.decision is not None and row.decision != "undone":
        raise RateDocumentError("Ten dokument jest już rozstrzygnięty.")
    finding = row.finding or {}
    if not row.has_finding or not finding.get("steps"):
        raise RateDocumentError("Stawka w kontrakcie zgadza się już z tym dokumentem.")
    if user is None and finding.get("category") != "auto":
        raise RateDocumentError("Ta różnica wymaga decyzji człowieka.")
    # Krok z warunkiem (np. stawka dla innego klienta w tym samym aneksie,
    # „po okresie próbnym”) nie wchodzi jednym klikiem — człowiek wpisuje go
    # w kontrakcie sam, bo tylko on wie, czy warunek dotyczy tego kontraktu.
    steps = [s for s in finding["steps"] if s.get("from") and not s.get("condition")]
    if not steps:
        raise RateDocumentError(
            "Dokument podaje stawkę bez daty albo z warunkiem — wpisz ją w kontrakcie ręcznie."
        )
    document = await db.get(ContractDocument, row.contract_document_id)
    filename = document.filename if document else "dokument"
    loaded = await _load_contract(db, row.contract_id)
    before = {s.id for s in loaded.candidate_rate_schedule}
    rate_before = (
        float(loaded.rate_candidate) if loaded.rate_candidate is not None else None
    )
    amendment_ids: list[int] = []
    for step in sorted(steps, key=lambda s: s["from"]):
        amendment = await apply_contract_amendment(
            contract_id=row.contract_id,
            data=ContractAmendmentCreate(
                amendment_type=ContractAmendmentType.rate_change,
                effective_date=date.fromisoformat(step["from"]),
                new_rate_candidate=Decimal(str(step["rate"])),
                reason=_reason(row, filename),
                document_id=row.contract_document_id,
            ),
            current_user=user,
            db=db,
            # Automat albo wołający, który sam sprawdził
            # `effects.can_confirm_rate_annex` (zmiana kwot albo Delivery Lead
            # u klienta z portfela — ta sama reguła co aneks stawki z Generatora).
            finance_write_authorized=user is None or finance_authorized,
            rate_signal_source="document",
        )
        amendment_ids.append(amendment.id)
    contract = await _load_contract(db, row.contract_id)
    created_steps = sorted(
        s.id for s in contract.candidate_rate_schedule if s.id not in before
    )
    row.decision = "auto_applied" if user is None else "applied"
    row.decision_amendment_ids = amendment_ids
    row.decided_by = user.id if user else None
    row.decided_at = datetime.now(timezone.utc)
    # Cofnięcie usuwa też krok bazowy, który założył pierwszy aneks pustego
    # harmonogramu — wtedy stawkę przywraca ``rate_before`` (kolumna kontraktu
    # przy pustym harmonogramie trzyma już nową stawkę).
    row.finding = {
        **finding,
        "created_step_ids": created_steps,
        "rate_before": rate_before,
    }
    db.add(
        Activity(
            entity_type="contract",
            entity_id=row.contract_id,
            action="rate_document_applied",
            user_id=user.id if user else None,
            details={
                "document_id": row.contract_document_id,
                "automatic": user is None,
                "amendment_ids": amendment_ids,
                "steps": [{"from": s["from"], "rate": s["rate"]} for s in steps],
            },
        )
    )
    await refresh_contract(db, row.contract_id)
    return row


async def dismiss_read(
    db: AsyncSession, read_id: int, *, user: User, expected_contract_id: int
) -> ContractDocumentRateRead:
    row = await db.get(ContractDocumentRateRead, read_id)
    if row is None or row.contract_id != expected_contract_id:
        raise RateDocumentError("Nie ma takiego odczytu dokumentu.")
    if row.decision in ("applied", "auto_applied"):
        raise RateDocumentError(
            "Stawka z tego dokumentu jest już wpisana — cofnij ją albo zmień w kontrakcie."
        )
    row.decision = "dismissed"
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=row.contract_id,
            action="rate_document_dismissed",
            user_id=user.id,
            details={"document_id": row.contract_document_id},
        )
    )
    await refresh_contract(db, row.contract_id)
    return row


def undo_deadline(row: ContractDocumentRateRead) -> Optional[datetime]:
    if row.decision != "auto_applied" or row.decided_at is None:
        return None
    return row.decided_at + timedelta(days=UNDO_DAYS)


async def undo_auto(
    db: AsyncSession, read_id: int, *, user: User, expected_contract_id: int
) -> ContractDocumentRateRead:
    """Cofnięcie wpisu automatycznego: jego kroki i aneksy znikają (bez commita)."""

    from app.services.contract_order_sync import resync_contract_safely  # noqa: PLC0415

    row = await db.get(ContractDocumentRateRead, read_id)
    if row is None or row.contract_id != expected_contract_id:
        raise RateDocumentError("Nie ma takiego odczytu dokumentu.")
    deadline = undo_deadline(row)
    if deadline is None:
        raise RateDocumentError("Cofnąć można tylko wpis automatyczny.")
    if datetime.now(timezone.utc) > deadline:
        raise RateDocumentError("Minęło 7 dni — zmień stawkę w kontrakcie aneksem.")
    contract = await _load_contract(db, row.contract_id, lock=True)
    step_ids = list((row.finding or {}).get("created_step_ids") or [])
    rate_before = (row.finding or {}).get("rate_before")
    amendment_ids = list(row.decision_amendment_ids or [])
    old_rate = contract.rate_candidate
    if step_ids:
        await db.execute(
            delete(ContractCandidateRate).where(ContractCandidateRate.id.in_(step_ids))
        )
    if amendment_ids:
        await db.execute(
            delete(ContractAmendment).where(ContractAmendment.id.in_(amendment_ids))
        )
    contract = await _load_contract(db, row.contract_id)
    if contract.candidate_rate_schedule:
        contract.rate_candidate = contract.effective_candidate_rate(business_today())
    elif rate_before is not None:
        contract.rate_candidate = Decimal(str(rate_before))
    contract.margin = contract.calculate_margin()
    await resync_contract_safely(db, contract, actor_id=user.id, auto_activate=False)
    row.decision = "undone"
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=row.contract_id,
            action="rate_document_undone",
            user_id=user.id,
            details={
                "document_id": row.contract_document_id,
                "amendment_ids": amendment_ids,
                "old": {
                    "rate_candidate": float(old_rate) if old_rate is not None else None
                },
                "new": {
                    "rate_candidate": float(contract.rate_candidate)
                    if contract.rate_candidate is not None
                    else None
                },
            },
        )
    )
    await refresh_contract(db, row.contract_id)
    return row


async def open_findings(
    db: AsyncSession, contract_ids: Optional[Sequence[int]] = None
) -> list[ContractDocumentRateRead]:
    """Odczyty z otwartą różnicą: bez decyzji albo z cofniętym wpisem automatycznym."""

    query = (
        select(ContractDocumentRateRead)
        .join(Contract, Contract.id == ContractDocumentRateRead.contract_id)
        .where(
            ContractDocumentRateRead.reader_version == reader.READER_VERSION,
            ContractDocumentRateRead.has_finding.is_(True),
            # Cofnięty wpis automatyczny wraca na kartę — decyduje człowiek.
            or_(
                ContractDocumentRateRead.decision.is_(None),
                ContractDocumentRateRead.decision == "undone",
            ),
            Contract.status.in_(CONTRACT_STATUSES),
        )
    )
    if contract_ids is not None:
        query = query.where(
            ContractDocumentRateRead.contract_id.in_(list(contract_ids))
        )
    return list((await db.execute(query)).scalars())


def view(
    row: ContractDocumentRateRead, filename: Optional[str], *, amounts: bool
) -> dict[str, Any]:
    """Odczyt dla frontu. Bez prawa do kwot — bez stawek i cytatu."""

    result = row.result or {}
    finding = row.finding or {}
    deadline = undo_deadline(row)
    data: dict[str, Any] = {
        "id": row.id,
        "document_id": row.contract_document_id,
        "filename": filename,
        "kind": result.get("kind"),
        "document_date": result.get("document_date"),
        "category": finding.get("category"),
        "reasons": finding.get("reasons") or [],
        "decision": row.decision,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "undo_until": deadline.isoformat() if deadline else None,
        "read_at": row.created_at.isoformat() if row.created_at else None,
        "steps": [],
        "quote": None,
    }
    if amounts:
        data["steps"] = finding.get("steps") or []
        data["quote"] = result.get("quote")
    else:
        data["steps"] = [
            {"from": s.get("from"), "to": s.get("to"), "condition": s.get("condition")}
            for s in finding.get("steps") or []
        ]
    return data
