"""Dzwonek Finansów: aneks dopisał krok stawki konsultanta („stawka od dnia”).

Przegląd skrzynki umowy@ z 23.11.2026: zmiana stawki szła do Rozliczeń tylko
jako PDF aneksu mailem. ``services/contract_rate_annex_signal.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.api.contracts import apply_contract_amendment
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_amendment import ContractAmendmentType
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.schemas.contract_amendment import ContractAmendmentCreate
from app.services.contract_rate_annex_signal import rate_annex_message


def test_message_names_the_day_and_origin_without_amounts():
    text = rate_annex_message(
        person="Jan Testowy",
        client_name="Klient S.A.",
        effective_from=date(2026, 12, 1),
        source="generator",
    )
    assert text.startswith(
        "Jan Testowy · Klient S.A.: stawka konsultanta zmienia się od 01.12.2026"
    )
    assert "podpisany aneks z Generatora" in text
    assert "zł" not in text and "PLN" not in text


async def _seed() -> tuple[int, int]:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        finance = User(
            email=f"rate-annex-finance-{unique}@example.com",
            password_hash=hash_password(f"F1n_{unique}!Pass"),
            name=f"Rate Annex Finance {unique}",
            role=UserRole.finance,
            roles=[UserRole.finance.value],
            is_active=True,
            email_verified=True,
            profile_completed=True,
        )
        client = Client(name=f"Rate annex client {unique}")
        person = Candidate(name="Jan", lastname=f"Aneks{unique}")
        db.add_all([finance, client, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            start_date=date(2026, 1, 5),
            status=ContractStatus.active,
            rate_candidate=Decimal("100"),
        )
        db.add(contract)
        await db.commit()
        return finance.id, contract.id


@pytest.mark.asyncio
async def test_rate_annex_rings_finance_once_per_amendment():
    finance_id, contract_id = await _seed()
    async with AsyncSessionLocal() as db:
        amendment = await apply_contract_amendment(
            contract_id=contract_id,
            data=ContractAmendmentCreate(
                amendment_type=ContractAmendmentType.rate_change,
                effective_date=date(2026, 12, 1),
                new_rate_candidate=Decimal("110"),
                reason="Aneks z pliku",
            ),
            current_user=None,
            db=db,
            finance_write_authorized=True,
            rate_signal_source="document",
        )
        await db.commit()
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == finance_id,
                    Notification.notification_type
                    == NotificationType.contract_rate_annex,
                )
            )
        ).all()
    assert len(bells) == 1
    assert bells[0].related_entity_type == "contract_amendment"
    assert bells[0].related_entity_id == amendment.id
    assert "od 01.12.2026" in bells[0].message
    assert bells[0].link == f"/contracts/{contract_id}?tab=amendments"


@pytest.mark.asyncio
async def test_client_rate_only_annex_does_not_ring_finance():
    finance_id, contract_id = await _seed()
    async with AsyncSessionLocal() as db:
        await apply_contract_amendment(
            contract_id=contract_id,
            data=ContractAmendmentCreate(
                amendment_type=ContractAmendmentType.rate_change,
                effective_date=date(2026, 12, 1),
                new_rate_client=Decimal("150"),
                reason="Tylko stawka klienta",
            ),
            current_user=None,
            db=db,
            finance_write_authorized=True,
        )
        await db.commit()
        count = len(
            (
                await db.scalars(
                    select(Notification.id).where(
                        Notification.user_id == finance_id,
                        Notification.notification_type
                        == NotificationType.contract_rate_annex,
                    )
                )
            ).all()
        )
    assert count == 0
