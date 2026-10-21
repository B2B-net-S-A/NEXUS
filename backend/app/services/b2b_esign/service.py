"""Wysyłka umowy do podpisu w NEXUSIE, podpis kontraktora, podpis firmy, wycofanie.

Kolejność stron jest stała: kontraktor (link z maila, bez konta), potem
reprezentant B2B Network wskazany przy wysyłce (w NEXUSIE). Każde wgranie:

1. plik musi zaczynać się bajtami poprzedniej wersji (``verdict.builds_on``),
2. walidacja (EU DSS) i ``verdict.judge`` — BEZ blokady wiersza, bo trwa do 30 s,
3. blokada wniosku i ponowne sprawdzenie stanu oraz odcisku — wycofanie albo
   drugie wgranie w czasie walidacji wygrywa (w torze z czerwca wycofanie
   w trakcie walidacji kończyło się „Zakończona”).

Kontrakt nie powstaje tutaj. Po podpisie obu stron wniosek jest ``completed``,
a automatykę „Oznacz jako podpisaną” woła warstwa wyżej.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_signing_request import OPEN_STATUSES, B2BSigningRequest
from app.services import storage_service
from app.services.b2b_esign.verdict import (
    MSG_CHANGED,
    MSG_NOT_PDF,
    Fingerprint,
    builds_on,
    judge,
)
from app.services.signing.provider import ValidationReport

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MIN_DAYS, MAX_DAYS = 1, 30

MSG_LINK = "Link jest nieprawidłowy albo wygasł. Poproś o nowy osobę z B2B Network."
MSG_ALREADY_SIGNED = (
    "Ta umowa jest już przez Ciebie podpisana — czekamy na podpis B2B Network."
)
MSG_CLOSED = "Ta umowa nie czeka już na podpis. Skontaktuj się z osobą z B2B Network."
MSG_RACE = "Stan umowy zmienił się w trakcie sprawdzania podpisu — odśwież stronę."
MSG_OPEN_EXISTS = (
    "Ta umowa jest już wysłana do podpisu w NEXUSIE. Wycofaj tamtą wysyłkę, "
    "zanim wyślesz ponownie."
)
MSG_NOT_SENDABLE = "Do podpisu wysyła się umowę w trakcie, jeszcze niepodpisaną."
MSG_NOT_COMPANY_SIGNER = "Za B2B Network podpisuje osoba wskazana przy wysyłce."
MSG_WAITS_FOR_CONTRACTOR = (
    "Najpierw podpisuje kontraktor — umowa jeszcze na niego czeka."
)
MSG_TOO_BIG = "Plik jest za duży — może mieć najwyżej 20 MB."
MSG_TOO_MANY_ATTEMPTS = (
    "Za dużo nieudanych prób z tego linku. Poproś osobę z B2B Network o nowy link."
)
MSG_NAME_MISSING = (
    "W umowie brakuje imienia i nazwiska osoby podpisującej — popraw umowę "
    "w generatorze i wyślij ponownie."
)
MSG_OPEN_BLOCKS_EDIT = (
    "Umowa jest wysłana do podpisu w NEXUSIE — PDF jest zamrożony. Najpierw "
    "„Przejdź na zwykłą drogę”, potem ją popraw i wyślij ponownie."
)
#: Nieudane wgrania z jednego linku (zły plik albo podpis) — potem nowy link.
MAX_FAILED_ATTEMPTS = 10


class Validator(Protocol):
    """``authoritative`` = walidator sprawdza listę zaufanych dostawców UE
    (pyHanko z EUTL albo EU DSS); bez tego żaden plik nie przejdzie."""

    @property
    def authoritative(self) -> bool: ...

    async def validate(self, signed_pdf: bytes) -> ValidationReport: ...


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """(token do maila, skrót do bazy) — sam token nie trafia do bazy."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def is_link_live(request: B2BSigningRequest, now: datetime) -> bool:
    return request.status == "sent" and request.expires_at > now


def check_pdf_upload(data: bytes) -> None:
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=MSG_TOO_BIG)
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail=MSG_NOT_PDF)


async def open_request_for(
    db: AsyncSession, generated_id: int
) -> B2BSigningRequest | None:
    return await db.scalar(
        select(B2BSigningRequest).where(
            B2BSigningRequest.generated_contract_id == generated_id,
            B2BSigningRequest.status.in_(OPEN_STATUSES),
        )
    )


def row_still_signable(row: B2BGeneratedContract | None) -> bool:
    """Umowa nadal czeka na podpis — nie oznaczona ręcznie, nie anulowana."""
    return (
        row is not None
        and row.signature_status != "signed_both"
        and row.contract_status == "in_progress"
    )


async def assert_no_open_request(db: AsyncSession, row_id: int) -> None:
    """Poprawka treści po wysyłce rozjechałaby kontrakt z podpisanym PDF-em."""
    if await open_request_for(db, row_id) is not None:
        raise HTTPException(status_code=409, detail=MSG_OPEN_BLOCKS_EDIT)


async def close_open_requests(
    db: AsyncSession,
    *,
    row_id: int,
    actor_id: int | None,
    reason: str,
    now: datetime,
) -> int:
    """Wycofaj wnioski w toku wiersza (ręczne „Oznacz jako podpisaną”, zmiana
    statusu umowy). Wołający trzyma blokadę wiersza — kolejność wiersz →
    wniosek, ta sama co przy wgraniu pliku."""
    open_requests = (
        await db.scalars(
            select(B2BSigningRequest)
            .where(
                B2BSigningRequest.generated_contract_id == row_id,
                B2BSigningRequest.status.in_(OPEN_STATUSES),
            )
            .with_for_update()
        )
    ).all()
    for request in open_requests:
        request.status = "withdrawn"
        request.contractor_token_hash = None
        request.closed_at = now
        request.closed_by = actor_id
        request.close_reason = reason[:500]
    return len(open_requests)


async def _lock_row_then_request(
    db: AsyncSession, row_id: int, request_id: int
) -> tuple[B2BGeneratedContract | None, B2BSigningRequest]:
    """Wiersz rejestru, potem wniosek — ta sama kolejność co ręczne ścieżki
    (``close_open_requests``), więc bez zakleszczenia."""
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return row, await _lock(db, request_id)


def assert_sendable(row: B2BGeneratedContract) -> None:
    if (
        row.source == "excel"
        or row.signature_status == "signed_both"
        or row.contract_status != "in_progress"
    ):
        raise HTTPException(status_code=409, detail=MSG_NOT_SENDABLE)


async def send(
    db: AsyncSession,
    *,
    row: B2BGeneratedContract,
    pdf: bytes,
    actor_id: int,
    contractor_email: str,
    company_signer_id: int,
    days: int,
    now: datetime,
) -> tuple[B2BSigningRequest, str]:
    """Zamroź PDF i otwórz wniosek. Wołający trzyma blokadę wiersza rejestru
    i sprawdził uprawnienia oraz przełącznik. Zwraca (wniosek, token linku)."""
    assert_sendable(row)
    # Kto podpisuje za kontraktora, mówi umowa (osoba z ``partner_name`` —
    # przy spółce osoba reprezentująca), nie nadawca: inaczej nadawca mógłby
    # wpisać siebie i podpisać za kontraktora z otrzymanego linku.
    contractor_name = (row.partner_name or "").strip()
    if not contractor_name:
        raise HTTPException(status_code=422, detail=MSG_NAME_MISSING)
    if await open_request_for(db, row.id) is not None:
        raise HTTPException(status_code=409, detail=MSG_OPEN_EXISTS)
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    token, digest = new_token()
    source = Fingerprint.of(pdf)
    request = B2BSigningRequest(
        generated_contract_id=row.id,
        status="sent",
        contractor_name=contractor_name,
        contractor_email=contractor_email.strip(),
        contractor_token_hash=digest,
        company_signer_id=company_signer_id,
        # Ścieżka dopiero po flush (katalog z id wniosku).
        source_pdf_path="",
        source_sha256=source.sha256,
        source_size=source.size,
        sent_by=actor_id,
        sent_at=now,
        expires_at=now + timedelta(days=days),
    )
    db.add(request)
    await db.flush()
    path, _ = storage_service.save_b2b_signing_pdf(
        request.id, f"umowa_{row.contract_number.replace('/', '_')}.pdf", pdf
    )
    request.source_pdf_path = path
    await db.flush()
    return request, token


async def load_by_token(db: AsyncSession, token: str) -> B2BSigningRequest:
    request = await db.scalar(
        select(B2BSigningRequest).where(
            B2BSigningRequest.contractor_token_hash == token_hash(token)
        )
    )
    if request is None:
        raise HTTPException(status_code=404, detail=MSG_LINK)
    return request


async def _lock(db: AsyncSession, request_id: int) -> B2BSigningRequest:
    locked = await db.scalar(
        select(B2BSigningRequest)
        .where(B2BSigningRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise HTTPException(status_code=404, detail=MSG_LINK)
    return locked


def _with_report(
    request: B2BSigningRequest, party: str, report: ValidationReport
) -> dict:
    # Nowy słownik: zmiana w miejscu nie zostałaby zapisana w kolumnie JSONB.
    return {**(request.validation or {}), party: report.as_db_report()}


async def contractor_precheck(
    db: AsyncSession, token: str, now: datetime
) -> B2BSigningRequest:
    """Token, stan i limit prób — PRZED odczytem pliku (fałszywy link nie
    zmusza serwera do przyjęcia 20 MB)."""
    request = await load_by_token(db, token)
    if request.status in ("contractor_signed", "completed"):
        raise HTTPException(status_code=409, detail=MSG_ALREADY_SIGNED)
    if not is_link_live(request, now):
        raise HTTPException(status_code=410, detail=MSG_CLOSED)
    if request.contractor_failed_attempts >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(status_code=429, detail=MSG_TOO_MANY_ATTEMPTS)
    return request


async def _count_failed_attempt(db: AsyncSession, request_id: int) -> None:
    locked = await _lock(db, request_id)
    locked.contractor_failed_attempts = (locked.contractor_failed_attempts or 0) + 1
    await db.commit()


async def contractor_submit(
    db: AsyncSession,
    *,
    request: B2BSigningRequest,
    data: bytes,
    validator: Validator,
    now: datetime,
) -> B2BSigningRequest:
    """Wołać po ``contractor_precheck`` z tym samym wnioskiem."""
    request_id = request.id
    row_id = request.generated_contract_id
    source = Fingerprint(request.source_sha256, request.source_size)
    contractor_name = request.contractor_name
    check_pdf_upload(data)
    if not builds_on(data, source):
        await _count_failed_attempt(db, request_id)
        raise HTTPException(status_code=422, detail=MSG_CHANGED)
    # Walidacja trwa do 30 s — bez otwartej transakcji i bez połączenia z puli.
    # ``commit`` (nic nie zmieniono), nie ``rollback``: sesja ma
    # ``expire_on_commit=False``, a rollback wygasiłby też zalogowanego
    # użytkownika z tej samej sesji (odczyt jego pól w async = MissingGreenlet).
    await db.commit()
    report = await validator.validate(data)
    verdict = judge(
        report,
        authoritative=validator.authoritative,
        required_signers=[contractor_name],
    )
    if not verdict.accepted:
        # Awaria walidatora to nie wina kontraktora — nie zużywa prób.
        if verdict.code != "no_validator":
            await _count_failed_attempt(db, request_id)
        raise HTTPException(status_code=422, detail=verdict.message)

    row, locked = await _lock_row_then_request(db, row_id, request_id)
    if not row_still_signable(row):
        raise HTTPException(status_code=409, detail=MSG_CLOSED)
    if not is_link_live(locked, now) or locked.source_sha256 != source.sha256:
        raise HTTPException(status_code=409, detail=MSG_RACE)
    path, size = storage_service.save_b2b_signing_pdf(
        locked.id, "podpisana_przez_kontraktora.pdf", data
    )
    signed = Fingerprint.of(data)
    locked.contractor_pdf_path = path
    locked.contractor_sha256 = signed.sha256
    locked.contractor_size = size
    locked.contractor_signed_at = now
    locked.validation = _with_report(locked, "contractor", report)
    locked.status = "contractor_signed"
    await db.flush()
    return locked


async def company_precheck(
    db: AsyncSession, *, request_id: int, actor_id: int, signer_ids: tuple[int, ...]
) -> B2BSigningRequest:
    """Wskazany reprezentant, nadal na liście z ustawień, i kontraktor już podpisał."""
    request = await db.get(B2BSigningRequest, request_id)
    if request is None or request.company_signer_id != actor_id:
        raise HTTPException(status_code=404, detail="Wniosek o podpis nie istnieje.")
    if actor_id not in signer_ids:
        raise HTTPException(status_code=403, detail=MSG_NOT_COMPANY_SIGNER)
    if request.status == "sent":
        raise HTTPException(status_code=409, detail=MSG_WAITS_FOR_CONTRACTOR)
    if request.status != "contractor_signed" or request.contractor_sha256 is None:
        raise HTTPException(status_code=409, detail=MSG_CLOSED)
    return request


async def company_submit(
    db: AsyncSession,
    *,
    request: B2BSigningRequest,
    actor_name: str,
    data: bytes,
    validator: Validator,
    now: datetime,
) -> B2BSigningRequest:
    """Wołać po ``company_precheck`` z tym samym wnioskiem."""
    request_id = request.id
    row_id = request.generated_contract_id
    contractor_name = request.contractor_name
    contractor_version = Fingerprint(
        request.contractor_sha256 or "", request.contractor_size or 0
    )
    check_pdf_upload(data)
    if not builds_on(data, contractor_version):
        raise HTTPException(status_code=422, detail=MSG_CHANGED)
    await db.commit()  # jak wyżej — bez transakcji na czas walidacji
    report = await validator.validate(data)
    verdict = judge(
        report,
        authoritative=validator.authoritative,
        required_signers=[contractor_name, actor_name],
    )
    if not verdict.accepted:
        raise HTTPException(status_code=422, detail=verdict.message)

    row, locked = await _lock_row_then_request(db, row_id, request_id)
    if not row_still_signable(row):
        raise HTTPException(status_code=409, detail=MSG_CLOSED)
    if (
        locked.status != "contractor_signed"
        or locked.contractor_sha256 != contractor_version.sha256
    ):
        raise HTTPException(status_code=409, detail=MSG_RACE)
    path, _ = storage_service.save_b2b_signing_pdf(
        locked.id, "podpisana_przez_obie_strony.pdf", data
    )
    locked.final_pdf_path = path
    locked.completed_at = now
    locked.validation = _with_report(locked, "company", report)
    locked.status = "completed"
    # Link kontraktora nie jest już potrzebny.
    locked.contractor_token_hash = None
    await db.flush()
    return locked


async def withdraw(
    db: AsyncSession,
    *,
    request_id: int,
    actor_id: int,
    reason: str | None,
    now: datetime,
) -> B2BSigningRequest:
    """Wycofaj wysyłkę (np. przejście na drogę zwykłą). Link przestaje działać."""
    locked = await _lock(db, request_id)
    if locked.status not in OPEN_STATUSES:
        raise HTTPException(status_code=409, detail=MSG_CLOSED)
    locked.status = "withdrawn"
    locked.contractor_token_hash = None
    locked.closed_at = now
    locked.closed_by = actor_id
    locked.close_reason = (reason or "").strip()[:500] or None
    await db.flush()
    return locked
