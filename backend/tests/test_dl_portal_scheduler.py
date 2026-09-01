"""Test dedup + status promotion w `dl_portal_expiry_scanner`.

Uwaga przy diagnozowaniu flaka w SĄSIEDNIM pliku: te testy wołają prawdziwe
`run_once()`, które skanuje CAŁĄ bazę — promuje statusy umów ramowych i zamówień,
materializuje grupy i wskrzesza kontrakty pod aktywnymi zamówieniami. Dotyka więc
także wierszy zostawionych przez pliki uruchomione WCZEŚNIEJ w tym samym shardzie,
a shard chodzi sekwencyjnie na wspólnej bazie. Podejrzany jest zatem plik, który
liczy globalne agregaty i wykonuje się PO tym pliku. Sprawdzone przy włączaniu go
do CI (2026-09-01): jeden przebieg z 51 plikami dotykającymi umów ramowych,
statusów zamówień i powiadomień — zero failów.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.notification import Notification, NotificationType
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.tasks.dl_portal_expiry_scanner import run_once

pytestmark = pytest.mark.asyncio


async def _setup_dl_with_client() -> tuple[int, int, int]:
    """Zwraca (admin_id, dl_id, client_id) świeżo utworzonych."""
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        admin = User(
            email=f"sched-admin-{suffix}@example.com",
            password_hash=hash_password("x"),
            name=f"Admin {suffix}",
            role=UserRole.admin,
            is_active=True,
        )
        dl = User(
            email=f"sched-dl-{suffix}@example.com",
            password_hash=hash_password("x"),
            name=f"DL {suffix}",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        client = Client(name=f"Sched Client {suffix}")
        db.add_all([admin, dl, client])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl.id, client_id=client.id, is_head=True
            )
        )
        await db.commit()
        return admin.id, dl.id, client.id


async def _new_contract(client_id: int) -> tuple[int, int]:
    """Kontrakt pod zamówienie. Zwraca ``(contract_id, candidate_id)``.

    `client_orders.contract_id` jest NOT NULL, a skaner wygasania łączy się
    z kontraktem przez INNER JOIN — zamówienie bez kontraktu nie jest „prostszym
    przypadkiem", tylko wierszem, którego produkcja nie potrafi wyprodukować.
    """
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=f"Sched Kontraktor {suffix}", lastname=f"Testowy{suffix}"
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            start_date=date.today(),
            rate_client=15000,
            rate_candidate=12000,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        await db.commit()
        return contract.id, candidate.id


async def _cleanup(
    client_id: int, user_ids: list[int], candidate_ids: list[int] | None = None
) -> None:
    async with AsyncSessionLocal() as db:
        for uid in user_ids:
            await db.execute(
                Notification.__table__.delete().where(Notification.user_id == uid)
            )
        # Kolejność jest wymuszona przez klucze obce, nie kosmetyczna:
        # `client_orders` wskazuje ZARÓWNO na `contracts`, JAK I na
        # `client_framework_contracts`, więc zamówienia znikają pierwsze.
        # Wcześniej kasowaliśmy umowy ramowe przed zamówieniami — nie bolało
        # tylko dlatego, że wstawienie zamówienia i tak padało wyżej.
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            Contract.__table__.delete().where(Contract.client_id == client_id)
        )
        await db.execute(
            ClientFrameworkContract.__table__.delete().where(
                ClientFrameworkContract.client_id == client_id
            )
        )
        await db.execute(
            DeliveryLeadClientAssignment.__table__.delete().where(
                DeliveryLeadClientAssignment.client_id == client_id
            )
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        if candidate_ids:
            await db.execute(
                Candidate.__table__.delete().where(Candidate.id.in_(candidate_ids))
            )
        if user_ids:
            await db.execute(User.__table__.delete().where(User.id.in_(user_ids)))
        await db.commit()


async def test_status_promotion_active_to_expired():
    """FC z expiry_date<today → status flippuje na expired."""
    admin_id, dl_id, client_id = await _setup_dl_with_client()
    try:
        async with AsyncSessionLocal() as db:
            fc = ClientFrameworkContract(
                client_id=client_id,
                name="Wygasla MSA",
                status=FrameworkContractStatus.active,
                expiry_date=date.today() - timedelta(days=1),
            )
            db.add(fc)
            await db.commit()
            fc_id = fc.id

        summary = await run_once()
        assert summary["fc_expired"] >= 1

        async with AsyncSessionLocal() as db:
            fc = await db.scalar(
                select(ClientFrameworkContract).where(
                    ClientFrameworkContract.id == fc_id
                )
            )
            assert fc.status == FrameworkContractStatus.expired
    finally:
        await _cleanup(client_id, [admin_id, dl_id])


async def test_alert_dispatch_30d_to_dl_and_admin():
    """30d before expiry → notification do każdego DL z assignmentem + admin."""
    admin_id, dl_id, client_id = await _setup_dl_with_client()
    try:
        async with AsyncSessionLocal() as db:
            fc = ClientFrameworkContract(
                client_id=client_id,
                name="MSA expiring 30d",
                status=FrameworkContractStatus.active,
                expiry_date=date.today() + timedelta(days=30),
            )
            db.add(fc)
            await db.commit()
            fc_id = fc.id

        await run_once()

        async with AsyncSessionLocal() as db:
            notifs = list(
                (
                    await db.execute(
                        select(Notification).where(
                            Notification.related_entity_type
                            == "client_framework_contract",
                            Notification.related_entity_id == fc_id,
                            Notification.notification_type
                            == NotificationType.framework_contract_expiring_30d,
                        )
                    )
                ).scalars()
            )
            recipient_ids = {n.user_id for n in notifs}
            # DL powinien dostać; admin też (ale staff list zawiera wielu adminów —
            # weryfikujemy tylko że nasze targety są w secie)
            assert dl_id in recipient_ids
            assert admin_id in recipient_ids
    finally:
        await _cleanup(client_id, [admin_id, dl_id])


async def test_alert_dedup_no_duplicate_on_second_run():
    """Druga iteracja schedulera nie tworzy duplikatów dla tego samego (entity, ntype)."""
    admin_id, dl_id, client_id = await _setup_dl_with_client()
    try:
        async with AsyncSessionLocal() as db:
            fc = ClientFrameworkContract(
                client_id=client_id,
                name="dedup test MSA",
                status=FrameworkContractStatus.active,
                expiry_date=date.today() + timedelta(days=14),
            )
            db.add(fc)
            await db.commit()
            fc_id = fc.id

        # Run 1
        await run_once()
        async with AsyncSessionLocal() as db:
            count_after_first = await db.scalar(
                select(__import__("sqlalchemy").func.count()).where(
                    Notification.related_entity_type == "client_framework_contract",
                    Notification.related_entity_id == fc_id,
                    Notification.notification_type
                    == NotificationType.framework_contract_expiring_14d,
                )
            )

        # Run 2
        await run_once()
        async with AsyncSessionLocal() as db:
            count_after_second = await db.scalar(
                select(__import__("sqlalchemy").func.count()).where(
                    Notification.related_entity_type == "client_framework_contract",
                    Notification.related_entity_id == fc_id,
                    Notification.notification_type
                    == NotificationType.framework_contract_expiring_14d,
                )
            )

        assert count_after_second == count_after_first
        assert count_after_first >= 2  # at least dl + admin
    finally:
        await _cleanup(client_id, [admin_id, dl_id])


async def test_order_alert_dispatched():
    """Order ending in 7d → notification."""
    admin_id, dl_id, client_id = await _setup_dl_with_client()
    contract_id, candidate_id = await _new_contract(client_id)
    try:
        async with AsyncSessionLocal() as db:
            fc = ClientFrameworkContract(
                client_id=client_id,
                name="MSA",
                status=FrameworkContractStatus.active,
            )
            db.add(fc)
            await db.flush()
            o = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                framework_contract_id=fc.id,
                title="Order ending 7d",
                status=ClientOrderStatus.active,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=7),
            )
            db.add(o)
            await db.commit()
            order_id = o.id

        await run_once()

        async with AsyncSessionLocal() as db:
            notifs = list(
                (
                    await db.execute(
                        select(Notification).where(
                            Notification.related_entity_type == "client_order",
                            Notification.related_entity_id == order_id,
                            Notification.notification_type
                            == NotificationType.client_order_ending_7d,
                        )
                    )
                ).scalars()
            )
            assert len(notifs) >= 2  # dl + admin minimum
    finally:
        await _cleanup(client_id, [admin_id, dl_id], [candidate_id])
