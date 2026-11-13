"""Kim jest konsultant portalu: wyłącznie adres z kontraktu.

Konta nie ma, więc tożsamością jest ``contracts.candidate_email``. Adres pasujący
do dwóch różnych osób (wspólna skrzynka, błąd w danych) nie otwiera niczego: nie
da się powiedzieć, czyje sprawy pokazać. Kontrakt zakończony działa jeszcze
``ENDED_GRACE_DAYS``, bo ostatni raport i faktura przychodzą po końcu współpracy.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.services.consultant_portal.portal_settings import PortalSettings

ENDED_GRACE_DAYS = 60
_LIVE = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class Consultant:
    contract_id: int
    email: str
    contract_ids: tuple[int, ...]
    candidate_id: Optional[int]
    first_name: Optional[str]
    phone: Optional[str]


def normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def eligible(contract: Contract, today: date) -> bool:
    if contract.status in _LIVE:
        return True
    return (
        contract.status == ContractStatus.ended
        and contract.end_date is not None
        and contract.end_date >= today - timedelta(days=ENDED_GRACE_DAYS)
    )


async def _contracts_for_email(
    db: AsyncSession, email: str, *, settings: PortalSettings, today: date
) -> list[Contract]:
    rows = (
        await db.scalars(
            select(Contract)
            .where(func.lower(Contract.candidate_email) == email)
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    return [row for row in rows if eligible(row, today) and settings.open_for(row.id)]


async def resolve_by_email(
    db: AsyncSession, email: str, *, settings: PortalSettings, today: date
) -> Optional[Contract]:
    """Kontrakt, na który wolno wysłać link, albo ``None``."""

    address = normalize_email(email)
    if not address:
        return None
    contracts = await _contracts_for_email(db, address, settings=settings, today=today)
    if not contracts:
        return None
    people = {
        row.candidate_id if row.candidate_id else f"c{row.id}" for row in contracts
    }
    return contracts[0] if len(people) == 1 else None


def _tokens(text: Optional[str]) -> set[str]:
    raw = unicodedata.normalize(
        "NFKD", (text or "").replace("ł", "l").replace("Ł", "L")
    )
    folded = raw.encode("ascii", "ignore").decode().lower().replace("-", " ")
    return {token for token in folded.split() if token}


async def resolve_by_name(
    db: AsyncSession, full_name: str, *, settings: PortalSettings, today: date
) -> Optional[Contract]:
    """Kontrakt po imieniu i nazwisku z tematu maila od koordynatora (E6.3).

    Tylko dla maili, które z formatu tematu niosą osobę (KEŚU z Jiry): nadawcą
    jest koordynator, a nie konsultant. Ta sama osoba w dwóch kandydatach albo
    dwie osoby o tym nazwisku = ``None`` (karta do ręcznego przypisania).
    """

    wanted = _tokens(full_name)
    if len(wanted) < 2:
        return None
    lowered = [part.lower() for part in full_name.replace("-", " ").split() if part]
    rows = (
        await db.execute(
            select(Contract, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(func.lower(Candidate.lastname).in_(lowered))
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    matches = [
        contract
        for contract, first, last in rows
        if _tokens(f"{first or ''} {last or ''}") == wanted
        and eligible(contract, today)
        # Osoba z KEŚU nic nie wysyła i nie musi mieć aktywnego panelu; w pilotażu
        # czytnik bierze jednak tylko osoby z pilotażu.
        and (settings.state == "all" or settings.open_for(contract.id))
    ]
    if not matches or len({c.candidate_id for c in matches}) != 1:
        return None
    return matches[0]


async def load_consultant(
    db: AsyncSession,
    *,
    contract_id: int,
    email: str,
    settings: PortalSettings,
    today: date,
) -> Optional[Consultant]:
    """Świeży obraz osoby: kontrakt musi działać i nadal mieć ten sam adres."""

    contract = await db.get(Contract, contract_id)
    if (
        contract is None
        or normalize_email(contract.candidate_email) != email
        or not eligible(contract, today)
        or not settings.open_for(contract.id)
    ):
        return None
    siblings = await _contracts_for_email(db, email, settings=settings, today=today)
    own = [
        row.id
        for row in siblings
        if row.id == contract.id
        or (row.candidate_id is not None and row.candidate_id == contract.candidate_id)
    ]
    candidate = (
        await db.get(Candidate, contract.candidate_id)
        if contract.candidate_id
        else None
    )
    return Consultant(
        contract_id=contract.id,
        email=email,
        contract_ids=tuple(own),
        candidate_id=contract.candidate_id,
        first_name=(candidate.name.strip() or None)
        if candidate and candidate.name
        else None,
        phone=(contract.candidate_phone or "").strip() or None,
    )
