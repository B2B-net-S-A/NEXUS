"""Alerty budżetowe dla WSPÓLNEJ PULI MD (Lotte Wedel, Cyfrowy Polsat).

Zamówienie ze wspólną pulą nie dostawało żadnego sygnału o budżecie: reguła
„mało MD" pytała wyłącznie o ``ClientOrder.md_remaining`` (budżet przypisany
osobie), a przy tych dwóch klientach linia konsultanta takiego budżetu nie ma.
Alert o wyczerpaniu emitowała wyłącznie ścieżka kosztowa. W efekcie pula
schodziła do zera po cichu — zamówienie przestawało przyjmować konsultantów,
a Delivery Lead dowiadywał się o tym dopiero z karty.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.services.cyfrowy_polsat_orders import CYFROWY_POLSAT_CLIENT_ID


async def _seed_shared_pool_client() -> int:
    """Klient Cyfrowego Polsatu — po JAWNYM id, bo po nim idzie bramka."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = await db.get(Client, CYFROWY_POLSAT_CLIENT_ID)
        if client is None:
            db.add(Client(id=CYFROWY_POLSAT_CLIENT_ID, name="Cyfrowy Polsat S.A."))
            await db.commit()
        return CYFROWY_POLSAT_CLIENT_ID


async def _seed_delivery_lead(client_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"sharedmd-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!PassX"),
            name="DL wspólnej puli",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client_id, delivery_lead_user_id=user.id
            )
        )
        await db.commit()
        return user.id


async def _seed_group(*, client_id: int, remaining: str, total: str = "100.000000"):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
    from datetime import date

    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"CP-{uuid.uuid4().hex[:6]}",
            start_date=date(2026, 1, 1),
            status=GROUP_STATUS_ACTIVE,
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=True,
            md_budget_total=Decimal(total),
            md_budget_remaining=Decimal(remaining),
        )
        db.add(group)
        await db.commit()
        await db.refresh(group)
        return group.id


async def test_low_shared_pool_produces_an_alert():
    """Pula poniżej progu budzi „mało MD" — reguła po liniach jej nie widziała."""
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_BUDGET_LOW, DlAlert
    from app.tasks.dl_alerts_scanner import rule_md_budget_low
    from sqlalchemy import select

    client_id = await _seed_shared_pool_client()
    user_id = await _seed_delivery_lead(client_id)
    group_id = await _seed_group(client_id=client_id, remaining="4.000000")

    async with AsyncSessionLocal() as db:
        await rule_md_budget_low(db)
        await db.commit()

        rows = (
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.user_id == user_id,
                    DlAlert.alert_type == ALERT_MD_BUDGET_LOW,
                    DlAlert.order_group_id == group_id,
                )
            )
        ).all()

    assert rows, "wspólna pula poniżej progu nie wygenerowała alertu"
    alert = rows[0]
    # Prefiks `group:` — wspólna pula jest sprawą całego zamówienia, więc jej
    # klucz nie może kolidować z kluczem linii (`order:`).
    assert f":group:{group_id}:" in alert.dedupe_key
    assert "wspólnej puli" in alert.message
    assert alert.payload["shared_pool"] is True


async def test_pool_above_threshold_is_quiet():
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_BUDGET_LOW, DlAlert
    from app.tasks.dl_alerts_scanner import rule_md_budget_low
    from sqlalchemy import select

    client_id = await _seed_shared_pool_client()
    user_id = await _seed_delivery_lead(client_id)
    group_id = await _seed_group(client_id=client_id, remaining="40.000000")

    async with AsyncSessionLocal() as db:
        await rule_md_budget_low(db)
        await db.commit()
        rows = (
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.user_id == user_id,
                    DlAlert.alert_type == ALERT_MD_BUDGET_LOW,
                    DlAlert.order_group_id == group_id,
                )
            )
        ).all()

    assert rows == []


def test_stale_flag_alone_does_not_mean_shared_pool():
    """Sama flaga nie wystarcza — na niej stoi filtr reguły „mało MD".

    Rewizja 0246 ustawiała ``is_md_budget_based`` KAŻDEMU jawnemu typowi
    ``md``, a 0251 to cofnęła — ale jej CHECK wszedł jako ``NOT VALID``, więc
    historyczny wiersz innego klienta wciąż może tę flagę nieść. Alert
    o „wspólnej puli" mówiłby wtedy o czymś, czego na jego karcie nie ma,
    dlatego skaner pyta ``uses_shared_md_pool``, a nie samą kolumnę.

    Test jest jednostkowy, bo od 0251 takiego wiersza nie da się już wstawić:
    baza odrzuca go ``ck_client_order_groups_explicit_type_coherence``.
    """
    from app.services.cyfrowy_polsat_orders import CYFROWY_POLSAT_CLIENT_ID
    from app.services.lotte_wedel_orders import LOTTE_WEDEL_CLIENT_ID
    from app.services.shared_md_orders import uses_shared_md_pool

    class _Group:
        def __init__(self, client_id: int, flag: bool) -> None:
            self.client_id = client_id
            self.is_md_budget_based = flag

    assert uses_shared_md_pool(_Group(CYFROWY_POLSAT_CLIENT_ID, True)) is True
    assert uses_shared_md_pool(_Group(LOTTE_WEDEL_CLIENT_ID, True)) is True
    # Zwykły klient z historyczną flagą — budżet ma przy osobie, nie w puli.
    assert uses_shared_md_pool(_Group(12, True)) is False
    assert uses_shared_md_pool(_Group(CYFROWY_POLSAT_CLIENT_ID, False)) is False


async def test_exhausted_pool_alerts_once_per_episode():
    """Podniesienie puli i ponowne wyczerpanie to NOWA sprawa, nie duplikat."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
    from app.models.dl_alert import ALERT_COST_ORDER_EXHAUSTED, DlAlert
    from app.services.dl_alerts import emit_shared_md_pool_exhausted
    from app.services.multi_consultant_orders import EVENT_BUDGET_EXHAUSTED
    from sqlalchemy import select

    client_id = await _seed_shared_pool_client()
    user_id = await _seed_delivery_lead(client_id)
    group_id = await _seed_group(client_id=client_id, remaining="0.000000")

    async def _exhaust_once() -> None:
        async with AsyncSessionLocal() as db:
            group = await db.get(ClientOrderGroup, group_id)
            db.add(
                ClientOrderGroupEvent(
                    group_id=group_id,
                    event_type=EVENT_BUDGET_EXHAUSTED,
                    description="Budżet MD wyczerpany.",
                )
            )
            await db.flush()
            await emit_shared_md_pool_exhausted(db, group)
            await db.commit()

    await _exhaust_once()
    await _exhaust_once()

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.user_id == user_id,
                    DlAlert.alert_type == ALERT_COST_ORDER_EXHAUSTED,
                    DlAlert.order_group_id == group_id,
                )
            )
        ).all()

    assert len(rows) == 2, "drugie wyczerpanie musi być osobną sprawą"
    assert "Zwiększ pulę MD" in rows[0].message, (
        "treść ma mówić o dniach, nie o rozliczeniu kwoty"
    )
