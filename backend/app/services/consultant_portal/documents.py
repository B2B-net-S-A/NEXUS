"""Rozliczenia: raporty i faktury z portalu i ze skrzynki ``rozliczenia@``.

Oba kanały kończą w ``store``, więc dają tę samą kartę w kolumnie ``invoice``: karta
to (kontrakt, okres, rodzaj), a nie plik (``sources.document_cards``). Ten sam plik
z drugiego kanału to ten sam wiersz, także gdy czytnik źle zgadł okres. Inny plik za
ten sam okres dokłada się do tej samej karty.

Typ pliku rozpoznaje ``documents_store.check`` po treści; nazwa od człowieka nie trafia
na dysk. Plik czyta wyłącznie właściciel kontraktu (po kodzie SMS) i zespół Finansów.
Raport przyjęty przez Finanse daje konsultantowi sygnał „wystaw fakturę”.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.upload_filename import fit_filename_column
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract
from app.models.consultant_panel import ClientSettlementRule
from app.services import storage_service
from app.services.consultant_portal import identity, portal_mail
from app.services.consultant_portal.auth import PortalContext, PortalError
from app.services.consultant_portal_schema import (
    COMMENT_MAX,
    DOCUMENT_KINDS,
    FILE_NAME_MAX,
)
from app.services.hr import documents_store

logger = logging.getLogger(__name__)

SUBDIR = "consultant_portal"
MONTHS_BACK = 24
#: Starsze miesiące pokazujemy tylko wtedy, gdy mają dokument: rozliczenia sprzed portalu
#: szły mailem i nie mogą wyglądać jak zaległości.
OVERVIEW_MONTHS = 3
MAX_FILE_BYTES = documents_store.MAX_FILE_BYTES
NOT_FOUND = "Nie ma takiego dokumentu."
BAD_PERIOD = "Wybierz miesiąc z ostatnich dwóch lat, najpóźniej bieżący."
BAD_KIND = "Wybierz raport albo fakturę."
ALREADY_DECIDED = "Ten dokument ma już decyzję."


def relative_path(owner: str, digest: str, mime: str) -> str:
    return f"{SUBDIR}/{owner}/{digest}.{documents_store.EXTENSIONS[mime]}"


def _save(owner: str, content: bytes, *, mime: str, digest: str) -> str:
    relative = relative_path(owner, digest, mime)
    target = Path(storage_service.STORAGE_ROOT) / relative
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.part")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return relative


def path_for(relative: str) -> Path:
    """Ścieżka pliku pod katalogiem portalu, bez wyjścia poza niego."""

    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem portalu") from None
    if not path.is_file():
        raise FileNotFoundError("brak pliku")
    return path


def valid_period(year: int, month: int, *, today: date) -> bool:
    if not 1 <= month <= 12:
        return False
    index = year * 12 + month
    current = today.year * 12 + today.month
    return current - MONTHS_BACK <= index <= current


@dataclass(frozen=True)
class Stored:
    document: CpDocument
    duplicate: bool


async def _same_file(
    db: AsyncSession,
    *,
    contract_id: Optional[int],
    kind: str,
    digest: str,
    graph_message_id: Optional[str],
) -> Optional[CpDocument]:
    if contract_id is not None:
        return await db.scalar(
            select(CpDocument)
            .where(
                CpDocument.contract_id == contract_id,
                CpDocument.kind == kind,
                CpDocument.sha256 == digest,
            )
            .order_by(CpDocument.id)
            .limit(1)
        )
    if graph_message_id:
        return await db.scalar(
            select(CpDocument).where(
                CpDocument.graph_message_id == graph_message_id,
                CpDocument.sha256 == digest,
            )
        )
    return None


async def store(
    db: AsyncSession,
    *,
    contract_id: Optional[int],
    kind: str,
    year: int,
    month: int,
    content: bytes,
    file_name: Optional[str],
    channel: str,
    now: datetime,
    period_guessed: bool = False,
    graph_message_id: Optional[str] = None,
    sender_email: Optional[str] = None,
) -> Stored:
    """Jedno wejście obu kanałów. Odrzuca plik zły, a ten sam plik zwraca bez zapisu."""

    if kind not in DOCUMENT_KINDS:
        raise PortalError(BAD_KIND)
    try:
        mime, digest = documents_store.check(content)
    except documents_store.FileRejected as exc:
        raise PortalError(str(exc), code="bad_file") from None
    existing = await _same_file(
        db,
        contract_id=contract_id,
        kind=kind,
        digest=digest,
        graph_message_id=graph_message_id,
    )
    if existing is not None:
        return Stored(existing, True)
    relative = _save(
        str(contract_id) if contract_id else "unmatched",
        content,
        mime=mime,
        digest=digest,
    )
    document = CpDocument(
        contract_id=contract_id,
        kind=kind,
        period_year=year,
        period_month=month,
        period_guessed=period_guessed,
        channel=channel,
        status="received",
        file_path=relative,
        file_name=fit_filename_column(file_name, FILE_NAME_MAX) if file_name else None,
        mime=mime,
        size_bytes=len(content),
        sha256=digest,
        graph_message_id=graph_message_id,
        sender_email=sender_email,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(document)
            await db.flush()
    except IntegrityError:
        # Dwa kanały naraz: wygrywa pierwszy zapis, drugi dostaje ten sam wiersz.
        existing = await _same_file(
            db,
            contract_id=contract_id,
            kind=kind,
            digest=digest,
            graph_message_id=graph_message_id,
        )
        if existing is None:
            raise
        return Stored(existing, True)
    return Stored(document, False)


# ── Konsultant ───────────────────────────────────────────────────────────────


def _doc_row(document: CpDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "kind": document.kind,
        "status": document.status,
        "file_name": document.file_name,
        "channel": document.channel,
        "created_at": document.created_at.isoformat(),
        "reject_reason": document.reject_reason
        if document.status == "rejected"
        else None,
    }


def _best(documents: list[CpDocument], kind: str) -> Optional[CpDocument]:
    """Najważniejszy stan okresu: decyzja pozytywna, potem czekający, potem odrzucony."""

    rank = {"paid": 0, "accepted": 1, "received": 2, "rejected": 3}
    rows = [row for row in documents if row.kind == kind]
    return min(rows, key=lambda row: (rank[row.status], -row.id)) if rows else None


REPORT_LABELS = {
    "received": "Raport: czeka na akceptację",
    "accepted": "Raport: zaakceptowany",
    "paid": "Raport: zaakceptowany",
    "rejected": "Raport: do poprawy",
}
INVOICE_LABELS = {
    "received": "Faktura: przyjęta do sprawdzenia",
    "accepted": "Faktura: przyjęta",
    "paid": "Faktura: opłacona",
    "rejected": "Faktura: do poprawy",
}


def _client_report_row(
    year: int, month: int, documents: list[CpDocument]
) -> dict[str, Any]:
    """Raport przysyła klient, więc konsultant ma tylko krok z fakturą."""

    invoice = _best(documents, "invoice")
    action = "send_invoice" if invoice is None or invoice.status == "rejected" else None
    return {
        "year": year,
        "month": month,
        "report_label": "Raport: przysyła klient",
        "invoice_label": INVOICE_LABELS[invoice.status]
        if invoice
        else "Faktura: czekamy",
        "issue_invoice": action == "send_invoice",
        "action": action,
        "documents": [_doc_row(row) for row in documents],
    }


def month_row(
    year: int,
    month: int,
    documents: list[CpDocument],
    *,
    mode: Optional[str] = None,
) -> dict[str, Any]:
    """Stan miesiąca i następny krok konsultanta (czysta funkcja).

    ``mode`` to szablon rozliczenia klienta; bez szablonu raport wysyła konsultant.
    """

    if mode == "client_report":
        return _client_report_row(year, month, documents)

    report = _best(documents, "report")
    invoice = _best(documents, "invoice")
    if report is None or report.status == "rejected":
        action: Optional[str] = "send_report"
    elif report.status == "received":
        action = None
    elif invoice is None or invoice.status == "rejected":
        # Raport przyjęty: to jest sygnał „wystaw fakturę”.
        action = "send_invoice"
    else:
        action = None
    return {
        "year": year,
        "month": month,
        "report_label": REPORT_LABELS[report.status]
        if report
        else "Raport: do wysłania",
        "invoice_label": INVOICE_LABELS[invoice.status]
        if invoice
        else (
            "Faktura: wystaw i wyślij"
            if action == "send_invoice"
            else "Faktura: po akceptacji raportu"
        ),
        "issue_invoice": action == "send_invoice",
        "action": action,
        "documents": [_doc_row(row) for row in documents],
    }


def _months_back(today: date, count: int) -> list[tuple[int, int]]:
    total = today.year * 12 + today.month - 1
    return [
        ((total - offset) // 12, (total - offset) % 12 + 1) for offset in range(count)
    ]


async def overview(
    db: AsyncSession, context: PortalContext, *, today: date
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(CpDocument)
            .where(CpDocument.contract_id.in_(context.consultant.contract_ids))
            .order_by(CpDocument.period_year.desc(), CpDocument.period_month.desc())
        )
    ).all()
    contract = await db.get(Contract, context.consultant.contract_id)
    start = contract.start_date if contract else None
    by_month: dict[tuple[int, int], list[CpDocument]] = {
        key: []
        for key in _months_back(today, OVERVIEW_MONTHS)
        if start is None or key >= (start.year, start.month)
    }
    for row in rows:
        by_month.setdefault((row.period_year, row.period_month), []).append(row)
    rule = (
        await db.get(ClientSettlementRule, contract.client_id)
        if contract and contract.client_id
        else None
    )
    return [
        month_row(
            year, month, by_month[(year, month)], mode=rule.mode if rule else None
        )
        for year, month in sorted(by_month, reverse=True)
    ]


async def upload_from_portal(
    db: AsyncSession,
    context: PortalContext,
    *,
    kind: str,
    year: int,
    month: int,
    content: bytes,
    file_name: Optional[str],
    today: date,
    now: datetime,
) -> Stored:
    if not valid_period(year, month, today=today):
        raise PortalError(BAD_PERIOD)
    return await store(
        db,
        contract_id=context.consultant.contract_id,
        kind=kind,
        year=year,
        month=month,
        content=content,
        file_name=file_name,
        channel="portal",
        now=now,
        sender_email=context.consultant.email,
    )


async def own_document(
    db: AsyncSession, context: PortalContext, document_id: int
) -> CpDocument:
    document = await db.get(CpDocument, document_id)
    if (
        document is None
        or document.contract_id is None
        or document.contract_id not in context.consultant.contract_ids
    ):
        raise PortalError(NOT_FOUND, status=404, code="not_found")
    return document


# ── Finanse ──────────────────────────────────────────────────────────────────


def staff_row(document: CpDocument) -> dict[str, Any]:
    return {
        **_doc_row(document),
        "contract_id": document.contract_id,
        "period_year": document.period_year,
        "period_month": document.period_month,
        "period_guessed": document.period_guessed,
        "sender_email": document.sender_email,
        "invoice_signal_at": document.invoice_signal_at.isoformat()
        if document.invoice_signal_at
        else None,
    }


async def _notify(
    db: AsyncSession, document: CpDocument, *, subject: str, text: str
) -> None:
    """Mail do konsultanta. Awaria nie cofa decyzji: stan i tak widać w portalu."""

    if document.contract_id is None:
        return
    contract = await db.get(Contract, document.contract_id)
    email = identity.normalize_email(contract.candidate_email if contract else None)
    if not email:
        return
    try:
        await portal_mail.send(
            db, contract_id=document.contract_id, to=email, subject=subject, text=text
        )
    except Exception as exc:  # noqa: BLE001 — mail to dodatek do decyzji
        logger.warning("consultant_portal_documents: mail (%s)", type(exc).__name__)


async def _for_decision(db: AsyncSession, document_id: int) -> CpDocument:
    document = await db.get(CpDocument, document_id)
    if document is None:
        raise PortalError(NOT_FOUND, status=404, code="not_found")
    return document


async def accept(
    db: AsyncSession, document_id: int, *, actor_id: int, now: datetime
) -> CpDocument:
    document = await _for_decision(db, document_id)
    if document.contract_id is None:
        raise PortalError(
            "Najpierw wskaż kontrakt nadawcy.", status=409, code="unmatched"
        )
    if document.status != "received":
        raise PortalError(ALREADY_DECIDED, status=409, code="decided")
    document.status = "accepted"
    document.decided_by = actor_id
    document.decided_at = now
    document.updated_at = now
    if document.kind == "report":
        document.invoice_signal_at = now
        await _notify(
            db,
            document,
            subject="Raport zaakceptowany: możesz wystawić fakturę",
            text=(
                f"Raport za {document.period_month:02d}.{document.period_year} jest "
                "zaakceptowany. Możesz wystawić fakturę i wysłać ją w strefie konsultanta "
                f"albo na adres rozliczeń:\n{portal_mail.portal_url()}"
            ),
        )
    return document


async def reject(
    db: AsyncSession, document_id: int, *, actor_id: int, reason: str, now: datetime
) -> CpDocument:
    document = await _for_decision(db, document_id)
    if document.status != "received":
        raise PortalError(ALREADY_DECIDED, status=409, code="decided")
    clean = reason.replace("\x00", "").strip()[:COMMENT_MAX]
    if not clean:
        raise PortalError("Napisz, co trzeba poprawić.")
    document.status = "rejected"
    document.reject_reason = clean
    document.decided_by = actor_id
    document.decided_at = now
    document.updated_at = now
    await _notify(
        db,
        document,
        subject="Dokument do poprawy",
        text=(
            f"Dokument za {document.period_month:02d}.{document.period_year} wymaga poprawy. "
            f"Szczegóły znajdziesz w strefie konsultanta:\n{portal_mail.portal_url()}"
        ),
    )
    return document


async def mark_paid(
    db: AsyncSession, document_id: int, *, actor_id: int, now: datetime
) -> CpDocument:
    document = await _for_decision(db, document_id)
    if document.kind != "invoice" or document.status != "accepted":
        raise PortalError(
            "Opłacona może być tylko przyjęta faktura.", status=409, code="not_accepted"
        )
    document.status = "paid"
    document.decided_by = actor_id
    document.updated_at = now
    return document


async def assign_contract(
    db: AsyncSession, document_id: int, *, contract_id: int, now: datetime
) -> CpDocument:
    """Plik z nieznanego adresu trafia do kontraktu ręką Finansów."""

    document = await _for_decision(db, document_id)
    if document.contract_id is not None:
        raise PortalError("Dokument ma już kontrakt.", status=409, code="matched")
    if await db.get(Contract, contract_id) is None:
        raise PortalError("Nie ma takiego kontraktu.", status=404, code="no_contract")
    duplicate = await _same_file(
        db,
        contract_id=contract_id,
        kind=document.kind,
        digest=document.sha256,
        graph_message_id=None,
    )
    if duplicate is not None:
        raise PortalError(
            "Ten plik jest już w dokumentach kontraktu.", status=409, code="duplicate"
        )
    document.contract_id = contract_id
    document.updated_at = now
    return document
