"""Akceptacja dokumentów z paczki kodem z maila (0754, decyzja Artura 22.11.2026).

Kwalifikowany podpis jest wymagany tylko przy umowie, która przenosi autorskie
prawa majątkowe (art. 53 pr. aut.). NDA, oświadczenia i inne dokumenty
z wymogiem ``any`` kontraktor może podpisać tym samym podpisem
kwalifikowanym albo zaakceptować kodem wysłanym na adres z wysyłki.

Zasady:

* kod ma 6 cyfr, jest jednorazowy i ważny ``CODE_VALID_MINUTES``; w bazie
  zostaje tylko skrót HMAC (``SECRET_KEY``), nie kod;
* nowy kod najwcześniej po ``RESEND_AFTER`` od poprzedniego;
* zły albo przeterminowany kod liczy się do ``contractor_failed_attempts``
  (ten sam limit co nieudane wgrania pliku);
* akceptacja obejmuje tylko dokumenty z wymogiem ``any``; umowa i dokument
  z wymogiem klienta zostają przy podpisie kwalifikowanym;
* zaakceptowany dokument dostaje kopię wydanego PDF-a jako plik
  „podpisany” (te same bajty, ten sam odcisk) i dowód akceptacji
  w ``validation``: adres, chwila, IP, przeglądarka, odcisk pliku.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_config
from app.models.b2b_signing_document import B2BSigningDocument
from app.models.b2b_signing_request import B2BSigningRequest
from app.services import storage_service
from app.services.b2b_esign import documents as esign_docs
from app.services.b2b_esign import service

CODE_VALID_MINUTES = 15
RESEND_AFTER = timedelta(seconds=60)

MSG_NOTHING_TO_ACCEPT = (
    "W tej paczce nie ma dokumentów, które można zaakceptować kodem. Umowę "
    "podpisuje się podpisem kwalifikowanym."
)
MSG_RESEND_TOO_SOON = "Kod już wysłaliśmy. Nowy możesz poprosić za minutę."
MSG_CODE_WRONG = "Kod jest nieprawidłowy. Sprawdź maila i wpisz kod jeszcze raz."
MSG_CODE_EXPIRED = "Kod stracił ważność. Poproś o nowy kod."
MSG_NO_CODE = "Najpierw poproś o kod. Wyślemy go na Twój adres z umowy."
MSG_NEEDS_QUALIFIED = (
    "Tego dokumentu nie można zaakceptować kodem. Wymaga podpisu kwalifikowanego."
)
MSG_MAIL_FAILED = (
    "Nie udało się wysłać kodu. Podpisz dokumenty podpisem kwalifikowanym albo "
    "napisz do osoby z B2Bnetwork, która wysłała link."
)


def new_code() -> str:
    """6 cyfr, z zerami na początku."""
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hash(request_id: int, code: str) -> str:
    """Skrót kodu powiązany z wnioskiem: ten sam kod z innego linku nie pasuje,
    a zrzut bazy nie daje kodu bez ``SECRET_KEY``."""
    digits = "".join(ch for ch in code if ch.isdigit())
    message = f"b2b-esign-accept:{request_id}:{digits}".encode()
    return hmac.new(app_config.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def mask_email(address: str | None) -> str:
    """„a***@o2.pl” — kontraktor widzi, dokąd idzie kod, bez całego adresu."""
    if not address or "@" not in address:
        return ""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


async def acceptable(db: AsyncSession, request_id: int) -> list[B2BSigningDocument]:
    """Niepodpisane dokumenty z wymogiem ``any``."""
    return list(
        (
            await db.scalars(
                select(B2BSigningDocument)
                .where(
                    B2BSigningDocument.request_id == request_id,
                    B2BSigningDocument.requirement == "any",
                    B2BSigningDocument.signed_pdf_path.is_(None),
                )
                .order_by(B2BSigningDocument.position, B2BSigningDocument.id)
            )
        ).all()
    )


async def issue(
    db: AsyncSession, *, request: B2BSigningRequest, now: datetime
) -> tuple[B2BSigningRequest, str]:
    """Nowy kod pod blokadą wniosku. Wołać po ``service.contractor_precheck``.

    Zwraca zablokowany wniosek i kod do maila; wołający robi commit, a przy
    nieudanym mailu ``withdraw_code``."""
    if not await acceptable(db, request.id):
        raise HTTPException(status_code=409, detail=MSG_NOTHING_TO_ACCEPT)
    locked = await service.lock_request(db, request.id)
    sent_at = locked.accept_code_sent_at
    if sent_at is not None and now - sent_at < RESEND_AFTER:
        raise HTTPException(status_code=429, detail=MSG_RESEND_TOO_SOON)
    code = new_code()
    locked.accept_code_hash = code_hash(locked.id, code)
    locked.accept_code_expires_at = now + timedelta(minutes=CODE_VALID_MINUTES)
    locked.accept_code_sent_at = now
    await db.flush()
    return locked, code


def withdraw_code(request: B2BSigningRequest) -> None:
    """Mail nie wyszedł: kod nie działa, a kontraktor może od razu poprosić o nowy."""
    request.accept_code_hash = None
    request.accept_code_expires_at = None
    request.accept_code_sent_at = None


@dataclass(frozen=True)
class Evidence:
    """Dowód akceptacji zapisywany przy dokumencie (``validation``)."""

    ip: Optional[str]
    user_agent: Optional[str]


def _evidence(
    request: B2BSigningRequest,
    item: B2BSigningDocument,
    evidence: Evidence,
    now: datetime,
) -> dict:
    return {
        "method": "email_code",
        "accepted_at": now.isoformat(),
        "email": request.contractor_email,
        "contractor_name": request.contractor_name,
        "source_sha256": item.source_sha256,
        "ip": (evidence.ip or "")[:64] or None,
        "user_agent": (evidence.user_agent or "")[:300] or None,
    }


async def _reject_code(db: AsyncSession, request_id: int, message: str) -> None:
    await service.count_failed_attempt(db, request_id)
    raise HTTPException(status_code=422, detail=message)


async def accept(
    db: AsyncSession,
    *,
    request: B2BSigningRequest,
    code: str,
    document_ids: list[int],
    evidence: Evidence,
    now: datetime,
) -> tuple[B2BSigningRequest, list[B2BSigningDocument]]:
    """Zaakceptuj wskazane dokumenty kodem. Wołać po ``service.contractor_precheck``.

    Kolejność blokad jak przy wgraniu: wiersz rejestru, wniosek, dokumenty."""
    request_id = request.id
    row_id = request.generated_contract_id
    if not document_ids:
        raise HTTPException(status_code=422, detail=MSG_NOTHING_TO_ACCEPT)
    for document_id in document_ids:
        item = await esign_docs.get_in_request(db, request_id, document_id)
        if item.requirement != "any":
            raise HTTPException(status_code=422, detail=MSG_NEEDS_QUALIFIED)
        if item.signed_pdf_path:
            raise HTTPException(status_code=409, detail=esign_docs.MSG_DOC_SIGNED)
    if not request.accept_code_hash:
        raise HTTPException(status_code=422, detail=MSG_NO_CODE)
    if request.accept_code_expires_at is None or request.accept_code_expires_at <= now:
        await _reject_code(db, request_id, MSG_CODE_EXPIRED)
    if not hmac.compare_digest(request.accept_code_hash, code_hash(request_id, code)):
        await _reject_code(db, request_id, MSG_CODE_WRONG)

    row, locked = await service.lock_row_then_request(db, row_id, request_id)
    if not service.row_still_signable(row):
        raise HTTPException(status_code=409, detail=service.MSG_CLOSED)
    if not service.is_link_live(locked, now):
        raise HTTPException(status_code=409, detail=service.MSG_RACE)
    if locked.accept_code_hash != code_hash(request_id, code):
        # Równoległa akceptacja zużyła kod.
        raise HTTPException(status_code=409, detail=service.MSG_RACE)
    items = list(
        (
            await db.scalars(
                select(B2BSigningDocument)
                .where(
                    B2BSigningDocument.request_id == request_id,
                    B2BSigningDocument.id.in_(document_ids),
                )
                .order_by(B2BSigningDocument.position, B2BSigningDocument.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(items) != len(set(document_ids)) or any(
        i.signed_pdf_path or i.requirement != "any" for i in items
    ):
        raise HTTPException(status_code=409, detail=service.MSG_RACE)
    for item in items:
        data = storage_service.read_b2b_signing_pdf(item.source_pdf_path)
        path, _ = storage_service.save_b2b_signing_pdf(
            locked.id, f"dokument_{item.position}_zaakceptowany.pdf", data
        )
        item.signed_pdf_path = path
        item.signed_sha256 = item.source_sha256
        item.signed_at = now
        item.signed_via = "email_code"
        item.validation = _evidence(locked, item, evidence, now)
        service.push_event(locked, "document_accepted", now, title=item.title)
    # Kod jednorazowy.
    withdraw_code(locked)
    await db.flush()
    await service.finish_contractor_if_complete(db, locked, now)
    return locked, items
