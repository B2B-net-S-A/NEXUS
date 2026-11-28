"""Panel trenera z rynku od strony TCM: otwarcie z danymi firmy, zamknięcie, dane do umowy.

Decyzje Artura z 28.11.2026: trener z rynku tylko z firmą (rozliczenie fakturą),
dane firmy wpisuje TCM przy „Otwórz panel trenera” z podpowiedzią z Białej Listy
(jak Generator B2B), a trener widzi je w panelu i zmienia tylko przez TCM — jak
konsultant dane do przelewu. Panel otwiera się tylko trenerowi „w bazie trenerów”.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website_intake import MarketTrainerApplication
from app.services import market_trainer_portal_schema as schema
from app.services.consultant_portal.identity import normalize_email
from app.services.market_trainer_portal import auth
from app.services.order_client_identity import nip_checksum_valid
from app.services.trainings.agreement import EXTRA_KEYS, PARTNER_KEYS, split_address


class PanelError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class CompanyData:
    company_name: str
    nip: str
    regon: str
    company_address: str
    panel_email: str


def clean_nip(raw: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) == 10 and nip_checksum_valid(digits) else None


def clean_regon(raw: Optional[str]) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits and len(digits) not in (9, 14):
        raise PanelError(422, "REGON ma 9 albo 14 cyfr.")
    return digits


def _text(value: Optional[str], limit: int, message: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise PanelError(422, message)
    if len(cleaned) > limit or "\n" in cleaned or "\r" in cleaned:
        raise PanelError(422, f"Pole może mieć najwyżej {limit} znaków w jednej linii.")
    return cleaned


def company_data(
    *,
    company_name: Optional[str],
    nip: Optional[str],
    regon: Optional[str],
    company_address: Optional[str],
    panel_email: Optional[str],
) -> CompanyData:
    """Walidacja danych firmy przed zapisem: bez nich nie powstanie umowa."""
    valid_nip = clean_nip(nip)
    if valid_nip is None:
        raise PanelError(422, "Podaj poprawny NIP firmy trenera (10 cyfr).")
    email = normalize_email(panel_email)
    if not email or "@" not in email or len(email) > 254:
        raise PanelError(422, "Podaj adres e-mail, na który trener dostanie link.")
    return CompanyData(
        company_name=_text(company_name, schema.COMPANY_MAX, "Podaj nazwę firmy."),
        nip=valid_nip,
        regon=clean_regon(regon),
        company_address=_text(
            company_address, schema.ADDRESS_MAX, "Podaj adres siedziby firmy."
        ),
        panel_email=email,
    )


async def _locked(db: AsyncSession, application_id: int) -> MarketTrainerApplication:
    row = await db.scalar(
        select(MarketTrainerApplication)
        .where(MarketTrainerApplication.id == application_id)
        .with_for_update()
    )
    if row is None:
        raise PanelError(404, "Nie ma takiego zgłoszenia.")
    return row


async def open_panel(
    db: AsyncSession,
    application_id: int,
    data: CompanyData,
    *,
    actor_user_id: int,
    now: datetime,
) -> tuple[MarketTrainerApplication, str]:
    """Zapisuje dane firmy i otwiera panel; zwraca link do maila z zaproszeniem.

    Ponowne otwarcie (np. poprawka danych albo nowy adres) zamyka stare sesje,
    bo adres logowania mógł się zmienić.
    """
    row = await _locked(db, application_id)
    if row.status != "accepted":
        raise PanelError(
            409, "Panel otwiera się trenerowi z bazy trenerów, po rozmowie."
        )
    await auth.revoke_all(db, row.id, now=now)
    row.company_name = data.company_name
    row.nip = data.nip
    row.regon = data.regon
    row.company_address = data.company_address
    row.panel_email = data.panel_email
    row.panel_opened_by = actor_user_id
    row.panel_opened_at = now
    row.panel_closed_at = None
    await db.flush()
    raw = await auth.issue_link(db, row, now=now)
    await db.refresh(row)
    return row, raw


async def close_panel(
    db: AsyncSession, application_id: int, *, now: datetime
) -> MarketTrainerApplication:
    row = await _locked(db, application_id)
    if row.panel_opened_at is None or row.panel_closed_at is not None:
        raise PanelError(409, "Panel tego trenera nie jest otwarty.")
    row.panel_closed_at = now
    await auth.revoke_all(db, row.id, now=now)
    await db.flush()
    await db.refresh(row)
    return row


def partner(row: MarketTrainerApplication) -> dict[str, str]:
    """Dane strony umowy szkoleniowej (klucze jak ``partner_from_contract``)."""
    address, postal_city = split_address(row.company_address or "")
    data = {key: "" for key in (*PARTNER_KEYS, *EXTRA_KEYS)}
    data.update(
        {
            "full_name": row.full_name,
            "company": row.company_name or "",
            "address": address,
            "postal_city": postal_city,
            "nip": row.nip or "",
            "regon": row.regon or "",
            "email": row.panel_email or row.email,
        }
    )
    return data


def panel_view(row: MarketTrainerApplication) -> dict[str, Any]:
    """Stan panelu na liście TCM (bez tokenów i sesji)."""
    return {
        "company_name": row.company_name,
        "nip": row.nip,
        "regon": row.regon,
        "company_address": row.company_address,
        "panel_email": row.panel_email,
        "panel_open": row.panel_open,
        "panel_opened_at": (
            row.panel_opened_at.isoformat() if row.panel_opened_at else None
        ),
        "panel_closed_at": (
            row.panel_closed_at.isoformat() if row.panel_closed_at else None
        ),
    }
