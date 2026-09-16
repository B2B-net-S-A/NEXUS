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
    """30d before expiry → assigned DL + admin, but never HoR."""
    admin_id, dl_id, client_id = await _setup_dl_with_client()
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        hor = User(
            email=f"sched-hor-{suffix}@example.com",
            password_hash=hash_password("x"),
            name=f"HoR {suffix}",
            role=UserRole.head_of_recruitment,
            is_active=True,
        )
        db.add(hor)
        await db.commit()
        hor_id = hor.id
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
            assert hor_id not in recipient_ids
    finally:
        await _cleanup(client_id, [admin_id, dl_id, hor_id])


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


async def test_extended_order_and_framework_contract_rearm_thresholds():
    """Próg przychodzi raz na DATĘ KOŃCA, nie raz na zawsze.

    Do 09.2026 klucz (odbiorca, encja, próg) bez daty wyciszał próg na zawsze:
    zamówienie przedłużone na nowy okres nie dostawało ostrzeżeń przed kolejnym
    końcem. Wpis z tą samą datą (także sprzed zmiany) nadal deduplikuje.
    """
    from datetime import datetime, timezone

    admin_id, dl_id, client_id = await _setup_dl_with_client()
    renewed_contract, renewed_candidate = await _new_contract(client_id)
    same_contract, same_candidate = await _new_contract(client_id)
    new_end = date.today() + timedelta(days=7)
    fc_end = date.today() + timedelta(days=14)
    long_ago = datetime.now(timezone.utc) - timedelta(days=60)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    try:
        async with AsyncSessionLocal() as db:
            renewed = ClientOrder(
                client_id=client_id,
                contract_id=renewed_contract,
                title="Przedłużone zamówienie",
                status=ClientOrderStatus.active,
                start_date=date.today() - timedelta(days=90),
                end_date=new_end,
            )
            same = ClientOrder(
                client_id=client_id,
                contract_id=same_contract,
                title="To samo zamówienie",
                status=ClientOrderStatus.active,
                start_date=date.today() - timedelta(days=90),
                end_date=new_end,
            )
            fc = ClientFrameworkContract(
                client_id=client_id,
                name="MSA przedłużona",
                status=FrameworkContractStatus.active,
                expiry_date=fc_end,
            )
            db.add_all([renewed, same, fc])
            await db.flush()
            old_end = (date.today() - timedelta(days=53)).isoformat()
            db.add_all(
                [
                    # Poprzedni okres przedłużonego zamówienia — ten sam próg.
                    Notification(
                        user_id=dl_id,
                        title="Zamówienie kończy się za 7 dni",
                        message=f"Zamówienie dla X u Y kończy się {old_end}. Skontaktuj się.",
                        notification_type=NotificationType.client_order_ending_7d,
                        related_entity_type="client_order",
                        related_entity_id=renewed.id,
                        created_at=long_ago,
                    ),
                    # Wpis sprzed zmiany dla TEJ SAMEJ daty — dalej deduplikuje.
                    Notification(
                        user_id=dl_id,
                        title="Zamówienie kończy się za 7 dni",
                        message=(
                            f"Zamówienie dla X u Y kończy się {new_end.isoformat()}. "
                            "Skontaktuj się."
                        ),
                        notification_type=NotificationType.client_order_ending_7d,
                        related_entity_type="client_order",
                        related_entity_id=same.id,
                        created_at=yesterday,
                    ),
                    Notification(
                        user_id=dl_id,
                        title="Umowa ramowa wygasa za 14 dni",
                        message=f"'MSA przedłużona' wygasa {old_end}. Skontaktuj się.",
                        notification_type=NotificationType.framework_contract_expiring_14d,
                        related_entity_type="client_framework_contract",
                        related_entity_id=fc.id,
                        created_at=long_ago,
                    ),
                ]
            )
            await db.commit()
            renewed_id, same_id, fc_id = renewed.id, same.id, fc.id

        async def messages(entity_type, entity_id, ntype):
            async with AsyncSessionLocal() as db:
                return sorted(
                    (
                        await db.scalars(
                            select(Notification.message).where(
                                Notification.user_id == dl_id,
                                Notification.related_entity_type == entity_type,
                                Notification.related_entity_id == entity_id,
                                Notification.notification_type == ntype,
                            )
                        )
                    ).all()
                )

        for _ in range(2):  # drugi przebieg tego samego dnia nie dubluje
            await run_once()
            renewed_msgs = await messages(
                "client_order", renewed_id, NotificationType.client_order_ending_7d
            )
            assert len(renewed_msgs) == 2
            assert any(f"kończy się {new_end.isoformat()}." in m for m in renewed_msgs)
            assert (
                len(
                    await messages(
                        "client_order", same_id, NotificationType.client_order_ending_7d
                    )
                )
                == 1
            )
            fc_msgs = await messages(
                "client_framework_contract",
                fc_id,
                NotificationType.framework_contract_expiring_14d,
            )
            assert len(fc_msgs) == 2
            assert any(f"wygasa {fc_end.isoformat()}." in m for m in fc_msgs)
    finally:
        await _cleanup(
            client_id, [admin_id, dl_id], [renewed_candidate, same_candidate]
        )


async def test_same_warsaw_day_alert_for_moved_date_does_not_crash_the_run():
    """Data przesunięta o dzień między biegami w jednej warszawskiej dobie.

    Próg liczony od daty UTC trafia wtedy tę samą encję drugi raz tego samego
    warszawskiego dnia, a ``ix_notif_dedup_daily`` nie zna daty końca: drugi
    wpis wywaliłby commit i wycofał cały przebieg (z przejściami statusów).
    """
    admin_id, dl_id, client_id = await _setup_dl_with_client()
    contract_id, candidate_id = await _new_contract(client_id)
    end = date.today() + timedelta(days=7)
    try:
        async with AsyncSessionLocal() as db:
            order = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title="Przesunięte zamówienie",
                status=ClientOrderStatus.active,
                start_date=date.today() - timedelta(days=30),
                end_date=end,
            )
            db.add(order)
            await db.flush()
            # Wpis z DZIŚ dla poprzedniej daty końca (dzień wcześniej).
            db.add(
                Notification(
                    user_id=dl_id,
                    title="Zamówienie kończy się za 7 dni",
                    message=(
                        "Zamówienie dla X u Y kończy się "
                        f"{(end - timedelta(days=1)).isoformat()}. Skontaktuj się."
                    ),
                    notification_type=NotificationType.client_order_ending_7d,
                    related_entity_type="client_order",
                    related_entity_id=order.id,
                )
            )
            await db.commit()
            order_id = order.id

        await run_once()  # nie może rzucić IntegrityError

        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(__import__("sqlalchemy").func.count()).where(
                    Notification.user_id == dl_id,
                    Notification.related_entity_type == "client_order",
                    Notification.related_entity_id == order_id,
                    Notification.notification_type
                    == NotificationType.client_order_ending_7d,
                )
            )
            assert count == 1
    finally:
        await _cleanup(client_id, [admin_id, dl_id], [candidate_id])


async def test_contract_typed_alert_with_the_same_id_does_not_crash_the_run():
    """Kontrakt #N i zamówienie #N u tego samego odbiorcy, tego samego dnia.

    ``contract_alerts`` pisze ``client_order_ending_30d`` z typem encji
    ``contract``, a ``ix_notif_dedup_daily`` typu encji nie zna — dla indeksu
    to jeden wpis. Skaner szukał bezpiecznika dnia tylko w SWOIM typie encji,
    wstawiał drugi wiersz i UniqueViolation cofał cały przebieg, razem
    z przejściami statusów innych zamówień (przegląd adwersarialny, przypadek J).
    """
    admin_id, dl_id, client_id = await _setup_dl_with_client()
    contract_id, candidate_id = await _new_contract(client_id)
    try:
        async with AsyncSessionLocal() as db:
            order = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title="Kolizja numeru",
                status=ClientOrderStatus.active,
                start_date=date.today() - timedelta(days=30),
                end_date=date.today() + timedelta(days=30),
            )
            # Zamówienie po terminie: jego przejście na „completed” musi
            # przetrwać ten sam przebieg.
            overdue = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title="Zamówienie po terminie",
                status=ClientOrderStatus.active,
                start_date=date.today() - timedelta(days=60),
                end_date=date.today() - timedelta(days=1),
            )
            db.add_all([order, overdue])
            await db.flush()
            db.add(
                Notification(
                    user_id=dl_id,
                    title="[client_order|x] Kontrakt — zamówienie klienta kończy się",
                    message="Zamówienie klienta dla kontraktu wygasa.",
                    notification_type=NotificationType.client_order_ending_30d,
                    related_entity_type="contract",
                    related_entity_id=order.id,
                )
            )
            await db.commit()
            order_id, overdue_id = order.id, overdue.id

        await run_once()  # nie może rzucić IntegrityError

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(
                        Notification.user_id, Notification.related_entity_type
                    ).where(
                        Notification.notification_type
                        == NotificationType.client_order_ending_30d,
                        Notification.related_entity_id == order_id,
                        Notification.user_id.in_([admin_id, dl_id]),
                    )
                )
            ).all()
            # DL: jeden wpis (indeks nie przyjmie drugiego tego dnia), admin:
            # zwykły alert zamówienia.
            assert sorted(rows) == sorted(
                [(dl_id, "contract"), (admin_id, "client_order")]
            )
            overdue_row = await db.get(ClientOrder, overdue_id)
            assert overdue_row.status == ClientOrderStatus.completed
    finally:
        await _cleanup(client_id, [admin_id, dl_id], [candidate_id])


async def test_notification_insert_swallows_only_the_daily_dedup_conflict():
    from sqlalchemy.exc import IntegrityError

    from app.tasks.dl_portal_expiry_scanner import (
        _already_notified,
        _insert_notification,
    )

    admin_id, dl_id, client_id = await _setup_dl_with_client()
    entity_id = 2_000_000_000 - (dl_id % 1_000_000)
    values = dict(
        user_id=dl_id,
        title="Kontrakt — zamówienie klienta kończy się",
        message="Zamówienie klienta dla kontraktu wygasa 2030-01-01.",
        notification_type=NotificationType.client_order_ending_30d,
        related_entity_type="contract",
        related_entity_id=entity_id,
        link="/contracts/1",
    )
    try:
        async with AsyncSessionLocal() as db:
            assert await _insert_notification(db, **values) is True
            # Ten sam odbiorca, typ, numer i dzień — inny typ encji: indeks
            # widzi ten sam wpis, zapis jest pomijany zamiast wywracać przebieg.
            assert (
                await _insert_notification(
                    db, **{**values, "related_entity_type": "client_order"}
                )
                is False
            )
            # Bezpiecznik dnia widzi wpis kontraktu także dla zamówienia #N,
            # choć jego data końca jest inna.
            assert await _already_notified(
                db,
                user_id=dl_id,
                related_entity_type="client_order",
                related_entity_id=entity_id,
                ntype=NotificationType.client_order_ending_30d,
                end_phrase="kończy się 2031-06-30",
            )
            # Inny błąd integralności nie jest połykany.
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    await _insert_notification(
                        db, **{**values, "user_id": -1, "related_entity_id": 1}
                    )
            await db.rollback()
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


async def _order_notification_types(order_id: int, user_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(Notification)
                    .where(
                        Notification.user_id == user_id,
                        Notification.related_entity_type == "client_order",
                        Notification.related_entity_id == order_id,
                    )
                    .order_by(Notification.id)
                )
            ).scalars()
        )
    return [n.notification_type.value for n in rows]


@pytest.mark.parametrize("days_left", [30, 29, 22, 15])
async def test_thirty_day_threshold_survives_a_missed_scan_day(days_left: int):
    """Uprzedzenie miesięczne wchodzi z ZAKRESU, nie z równości z dniem T-30.

    Do 09.2026 skaner pytał ``end_date == today + 30``. Jeden dzień bez biegu
    (albo przesunięcie doby między UTC a Warszawą) i próg 30-dniowy przepadał
    bezpowrotnie — pierwszy dzwonek wypadał dopiero na 14 dni przed końcem.
    """
    from app.core.scheduling import business_today

    admin_id, dl_id, client_id = await _setup_dl_with_client()
    contract_id, candidate_id = await _new_contract(client_id)
    end = business_today() + timedelta(days=days_left)
    try:
        async with AsyncSessionLocal() as db:
            order = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title=f"Zamówienie T-{days_left}",
                status=ClientOrderStatus.active,
                start_date=date.today() - timedelta(days=90),
                end_date=end,
            )
            db.add(order)
            await db.commit()
            order_id = order.id

        await run_once()

        assert await _order_notification_types(order_id, dl_id) == [
            "client_order_ending_30d"
        ]

        # Drugi bieg tego samego dnia nie dokłada nic.
        await run_once()
        assert await _order_notification_types(order_id, dl_id) == [
            "client_order_ending_30d"
        ]
    finally:
        await _cleanup(client_id, [admin_id, dl_id], [candidate_id])


async def test_order_entered_late_takes_the_tightest_threshold_not_thirty():
    """Zamówienie wpisane 10 dni przed końcem dostaje próg 14, nigdy 30.

    Próg 30-dniowy już minął, zanim zamówienie w ogóle trafiło do Nexusa —
    wysłanie go byłoby kłamstwem („kończy się za 30 dni"). Kubełek wybiera
    najciaśniejszy pasujący próg, więc Delivery Lead dostaje jeden dzwonek
    z prawdziwą liczbą dni.
    """
    from app.core.scheduling import business_today

    admin_id, dl_id, client_id = await _setup_dl_with_client()
    contract_id, candidate_id = await _new_contract(client_id)
    end = business_today() + timedelta(days=10)
    try:
        async with AsyncSessionLocal() as db:
            order = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title="Zamówienie wpisane późno",
                status=ClientOrderStatus.active,
                start_date=date.today() - timedelta(days=5),
                end_date=end,
            )
            db.add(order)
            await db.commit()
            order_id = order.id

        await run_once()

        assert await _order_notification_types(order_id, dl_id) == [
            "client_order_ending_14d"
        ]

        async with AsyncSessionLocal() as db:
            title = await db.scalar(
                select(Notification.title).where(
                    Notification.user_id == dl_id,
                    Notification.related_entity_type == "client_order",
                    Notification.related_entity_id == order_id,
                )
            )
        # Tytuł niesie faktyczną liczbę dni, nie numer progu.
        assert title.endswith("kończy się za 10 dni")
    finally:
        await _cleanup(client_id, [admin_id, dl_id], [candidate_id])


async def test_threshold_bucket_and_lead_phrase():
    from app.tasks.dl_portal_expiry_scanner import _lead_phrase, _threshold_bucket

    assert _threshold_bucket(31) is None
    assert _threshold_bucket(30) == 30
    assert _threshold_bucket(15) == 30
    assert _threshold_bucket(14) == 14
    assert _threshold_bucket(8) == 14
    assert _threshold_bucket(7) == 7
    assert _threshold_bucket(0) == 7

    assert _lead_phrase(22) == "za 22 dni"
    assert _lead_phrase(1) == "za 1 dzień"
    assert _lead_phrase(0) == "dzisiaj"
