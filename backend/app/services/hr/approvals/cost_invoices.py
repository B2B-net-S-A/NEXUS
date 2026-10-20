"""Faktury kosztowe spółki z KSeF → dokumenty wydatków (etap 3 zgód, 0486).

Pobieranie faktur zakupowych (``services/hr/ksef/sync.py``, ``Subject2``)
zapisywało dotąd tylko faktury od NIP-ów kontraktorów, a resztę liczyło jako
„pominięte”. Przy włączonym module „Zgody” każda taka faktura staje się
dokumentem wydatku — **z samych metadanych** (sprzedawca, numer, data, kwoty;
decyzja Artura 20.10.2026), bez pobierania XML-a, więc limit pobrań zostaje dla
faktur kontraktorów. Potem ``settlement.match_document``: zgoda ze znanym
sprzedawcą → przypięta; sprzedawca „stały koszt” → poza kolejką; reszta →
„Faktury bez zgody” w Finansach.

Ta sama faktura wgrana wcześniej do zgody jako PDF (ten sam NIP sprzedawcy
i numer) nie dostaje drugiego wiersza: dokument z PDF-u przechodzi na źródło
``ksef`` z kwotami z KSeF (wiążące).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_approval import ApprovalDocument
from app.services.hr.approvals import settlement
from app.services.hr_approval_settlement_schema import (
    INVOICE_NUMBER_MAX_LENGTH,
    SELLER_NAME_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


def _amount(raw: Any) -> Optional[Decimal]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return Decimal(str(raw)).quantize(_CENT)
    except (InvalidOperation, ValueError):
        return None


def _day(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def _text(raw: Any, limit: int) -> Optional[str]:
    text = " ".join(str(raw or "").split())
    return text[:limit] or None


def fields_from_metadata(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Pola dokumentu z rekordu metadanych KSeF; ``None`` = rekord bez kwoty."""

    seller = item.get("seller") or {}
    gross = _amount(item.get("grossAmount"))
    nip = str(seller.get("nip") or "")
    if gross is None or len(nip) != 10 or not nip.isdigit():
        return None
    currency = str(item.get("currency") or "PLN").upper()
    return {
        "seller_nip": nip,
        "seller_name": _text(seller.get("name"), SELLER_NAME_MAX_LENGTH),
        "invoice_number": _text(item.get("invoiceNumber"), INVOICE_NUMBER_MAX_LENGTH),
        "issue_date": _day(item.get("issueDate")),
        "currency": currency if len(currency) == 3 and currency.isalpha() else "PLN",
        "net_amount": _amount(item.get("netAmount")),
        "vat_amount": _amount(item.get("vatAmount")),
        "gross_amount": gross,
        "ksef_invoice_type": _text(item.get("invoiceType"), 16),
    }


async def _upload_twin(
    db: AsyncSession, fields: dict[str, Any]
) -> Optional[ApprovalDocument]:
    if not fields.get("invoice_number"):
        return None
    return await db.scalar(
        select(ApprovalDocument)
        .where(
            ApprovalDocument.source == "upload",
            ApprovalDocument.ksef_number.is_(None),
            ApprovalDocument.seller_nip == fields["seller_nip"],
            func.lower(ApprovalDocument.invoice_number)
            == fields["invoice_number"].lower(),
        )
        .order_by(ApprovalDocument.id)
        .limit(1)
        .with_for_update()
    )


async def store(
    db: AsyncSession, item: dict[str, Any], *, ksef_number: str, now: datetime
) -> Optional[str]:
    """Zapis faktury kosztowej i dopasowanie. Zwraca stan dokumentu albo ``None``
    (już była, rekord bez kwoty, baza odrzuciła)."""

    fields = fields_from_metadata(item)
    if fields is None:
        return None
    existing = await db.scalar(
        select(ApprovalDocument.id).where(ApprovalDocument.ksef_number == ksef_number)
    )
    if existing is not None:
        return None
    twin = await _upload_twin(db, fields)
    try:
        async with db.begin_nested():
            if twin is not None:
                doc = twin
                doc.source = "ksef"
                doc.ksef_number = ksef_number
                for key in (
                    "net_amount",
                    "vat_amount",
                    "gross_amount",
                    "currency",
                    "issue_date",
                    "ksef_invoice_type",
                ):
                    setattr(doc, key, fields[key])
                doc.seller_name = doc.seller_name or fields["seller_name"]
                if doc.topup_status in (None, "rejected"):
                    # Kwota z KSeF wiąże — dopłata liczy się od nowa.
                    settlement._clear_topup(doc)
            else:
                doc = ApprovalDocument(
                    source="ksef",
                    status="unmatched",
                    ksef_number=ksef_number,
                    **fields,
                )
                db.add(doc)
            doc.fetched_at = now
            await db.flush()
    except IntegrityError as exc:
        constraint = (
            getattr(exc.orig, "constraint_name", None) or type(exc.orig).__name__
        )
        logger.warning("ksef: baza odrzuciła fakturę kosztową (%s)", constraint)
        return None
    if twin is None:
        await settlement.match_document(db, doc)
    return doc.status
