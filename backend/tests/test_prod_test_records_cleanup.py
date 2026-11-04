"""Sprzątanie rekordów testowych z produkcji WYKONANE na bazie testowej (20.10.2026).

Faza startu połyka błąd (``|| echo skipped``), więc pomyłkę w zapytaniu
zobaczylibyśmy dopiero w logu wdrożenia. Baza testowa jest współdzielona:
plan sprzątania jest budowany z własnych wierszy testu i biegnie z własnym
znacznikiem. Osoby i firmy są wymyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.followup_meetings import ERASED_EVENT_TITLE
from app.services.m365.calendar import M365_SOURCE
from app.services.prod_test_records_cleanup import (
    CleanupPlan,
    PinnedContract,
    PinnedDraftOrder,
    PinnedPerson,
    run_prod_test_records_cleanup,
)
from tests.test_client_deletion import _client

MARKER_PATTERN = "TEST-M365-PROBA"


async def _seed() -> dict:
    suffix = uuid.uuid4().hex[:8]
    client_id = await _client(f"sprzatanie {suffix}")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, client_id)
        # Osoba testowa z kontraktem zakończonym przed startem (jak 598805).
        standalone = Candidate(name="QAOSOBA", lastname=f"KONTRAKT{suffix}")
        # Osoba testowa z adresem pracownika (jak 593527).
        mailbox = Candidate(
            name="QAOSOBA",
            lastname=f"SKRZYNKA{suffix}",
            email=f"pracownik-{suffix}@firma-{suffix}.example",
        )
        # Wiersz, który nie zgadza się z odciskiem w planie — zostaje.
        mismatch = Candidate(name="Prawdziwa", lastname=f"Osoba{suffix}")
        # Prawdziwy kandydat ze szkicem na kliencie testowym i uczestnik spotkań.
        real = Candidate(
            name="Jan",
            lastname=f"Kandydat{suffix}",
            email=f"kandydat-{suffix}@example.com",
        )
        db.add_all([standalone, mailbox, mismatch, real])
        await db.flush()
        ended = Contract(
            candidate_id=standalone.id,
            client_id=client_id,
            status=ContractStatus.ended,
            start_date=business_today() + timedelta(days=10),
            end_date=business_today() - timedelta(days=20),
            rate_unit=RateUnit.hourly,
        )
        draft = Contract(
            candidate_id=real.id,
            client_id=client_id,
            status=ContractStatus.draft,
            start_date=business_today(),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("140.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add_all([ended, draft])
        await db.flush()
        cancelled_order = ClientOrder(
            client_id=client_id,
            contract_id=ended.id,
            title="Zamówienie anulowane",
            status=ClientOrderStatus.cancelled,
            order_type="periodic",
        )
        draft_order = ClientOrder(
            client_id=client_id,
            contract_id=draft.id,
            title="Szkic zamówienia",
            status=ClientOrderStatus.draft,
            order_type="periodic",
        )
        db.add_all([cancelled_order, draft_order])

        def _event(title: str, attendees: list[str]) -> CalendarEvent:
            return CalendarEvent(
                title=title,
                event_type=EventType.meeting,
                start_time=now - timedelta(days=3),
                end_time=now - timedelta(days=3) + timedelta(minutes=30),
                attendees=[{"address": a, "name": None} for a in attendees],
                candidate_id=mailbox.id,
                status=EventStatus.scheduled,
                external_source=M365_SOURCE,
                external_id=f"graph-{uuid.uuid4().hex}",
            )

        team_only = _event("Spotkanie zespołu", [mailbox.email])
        with_real = _event("Rozmowa z kandydatem", [mailbox.email, real.email])
        test_event = _event(f"Prep 1: {MARKER_PATTERN}", [mailbox.email])
        db.add_all([team_only, with_real, test_event])
        await db.commit()
        return {
            "suffix": suffix,
            "client_id": client_id,
            "client_name": client.name,
            "standalone": standalone.id,
            "mailbox": mailbox.id,
            "mismatch": mismatch.id,
            "real": real.id,
            "ended": ended.id,
            "draft": draft.id,
            "cancelled_order": cancelled_order.id,
            "draft_order": draft_order.id,
            "team_only": team_only.id,
            "with_real": with_real.id,
            "test_event": test_event.id,
        }


def _plan(seed: dict, *, client_name: str | None = None) -> CleanupPlan:
    suffix = seed["suffix"]
    return CleanupPlan(
        client_id=seed["client_id"],
        client_name=client_name or seed["client_name"],
        people=(
            PinnedPerson(seed["standalone"], "QAOSOBA", f"KONTRAKT{suffix}"),
            PinnedPerson(seed["mailbox"], "QAOSOBA", f"SKRZYNKA{suffix}"),
            PinnedPerson(seed["mismatch"], "QAOSOBA", f"INNA{suffix}"),
        ),
        contracts=(
            PinnedContract(seed["ended"], seed["standalone"], ContractStatus.ended),
            PinnedContract(seed["draft"], seed["real"], ContractStatus.draft),
        ),
        draft_orders=(PinnedDraftOrder(seed["draft_order"], seed["draft"]),),
        test_event_title_pattern=MARKER_PATTERN,
    )


async def _drop(seed: dict, marker: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CalendarEvent).where(
                CalendarEvent.id.in_(
                    [seed["team_only"], seed["with_real"], seed["test_event"]]
                )
            )
        )
        await db.execute(
            delete(Contract).where(Contract.id.in_([seed["ended"], seed["draft"]]))
        )
        await db.execute(
            delete(Candidate).where(
                Candidate.id.in_(
                    [
                        seed["standalone"],
                        seed["mailbox"],
                        seed["mismatch"],
                        seed["real"],
                    ]
                )
            )
        )
        await db.execute(delete(AppSetting).where(AppSetting.key == marker))
        await db.commit()


async def test_cleanup_voids_contracts_releases_meetings_and_erases_people():
    seed = await _seed()
    marker = f"9999_prod_test_cleanup_{seed['suffix']}"
    try:
        async with AsyncSessionLocal() as db:
            result = await run_prod_test_records_cleanup(
                db, marker=marker, plan=_plan(seed)
            )
            await db.commit()
        assert result is not None
        summary, outcomes = result
        assert summary["client_pinned"] is True
        assert summary["draft_orders_deleted"] == [seed["draft_order"]]
        assert sorted(summary["contracts_voided"]) == sorted(
            [seed["ended"], seed["draft"]]
        )
        assert summary["calendar_unlinked"] == 1
        assert summary["calendar_relinked"] == 1
        assert summary["candidates_deleted"] == [seed["standalone"], seed["mailbox"]]
        assert summary["candidates_skipped"] == {
            str(seed["mismatch"]): "fingerprint_mismatch"
        }
        assert [o.candidate_id for o in outcomes] == [
            seed["standalone"],
            seed["mailbox"],
        ]

        async with AsyncSessionLocal() as db:
            for contract_id in (seed["ended"], seed["draft"]):
                contract = await db.get(Contract, contract_id)
                assert contract.status == ContractStatus.void
                assert contract.voided_at is not None
            assert await db.get(ClientOrder, seed["draft_order"]) is None
            cancelled = await db.get(ClientOrder, seed["cancelled_order"])
            assert cancelled.status == ClientOrderStatus.cancelled
            assert await db.get(Candidate, seed["standalone"]) is None
            assert await db.get(Candidate, seed["mailbox"]) is None
            # Prawdziwy kandydat i wiersz spoza odcisku zostają.
            assert await db.get(Candidate, seed["real"]) is not None
            assert await db.get(Candidate, seed["mismatch"]) is not None

            team_only = await db.get(CalendarEvent, seed["team_only"])
            assert team_only.candidate_id is None
            assert team_only.title == "Spotkanie zespołu"
            assert team_only.attendees[0]["address"].startswith("pracownik-")
            with_real = await db.get(CalendarEvent, seed["with_real"])
            assert with_real.candidate_id == seed["real"]
            assert with_real.title == "Rozmowa z kandydatem"
            # Próba audytu zostaje przy osobie i usunięcie ją anonimizuje.
            test_event = await db.get(CalendarEvent, seed["test_event"])
            assert test_event.candidate_id is None
            assert test_event.title == ERASED_EVENT_TITLE

            receipt = await db.get(AppSetting, marker)
            assert receipt.value["candidates_deleted"] == summary["candidates_deleted"]

        async with AsyncSessionLocal() as db:
            again = await run_prod_test_records_cleanup(
                db, marker=marker, plan=_plan(seed)
            )
            await db.commit()
        assert again is None
    finally:
        await _drop(seed, marker)


async def test_cleanup_changes_nothing_when_client_name_differs():
    seed = await _seed()
    marker = f"9999_prod_test_cleanup_{seed['suffix']}"
    try:
        async with AsyncSessionLocal() as db:
            result = await run_prod_test_records_cleanup(
                db, marker=marker, plan=_plan(seed, client_name="Inna firma")
            )
            await db.commit()
        summary, outcomes = result
        assert summary["client_pinned"] is False
        assert outcomes == []
        async with AsyncSessionLocal() as db:
            ended = await db.get(Contract, seed["ended"])
            assert ended.status == ContractStatus.ended
            assert await db.get(ClientOrder, seed["draft_order"]) is not None
            assert await db.get(Candidate, seed["mailbox"]) is not None
            event = await db.get(CalendarEvent, seed["team_only"])
            assert event.candidate_id == seed["mailbox"]
    finally:
        await _drop(seed, marker)


async def test_cleanup_skips_contract_whose_status_moved():
    seed = await _seed()
    marker = f"9999_prod_test_cleanup_{seed['suffix']}"
    try:
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, seed["ended"])
            contract.status = ContractStatus.active
            await db.commit()
        async with AsyncSessionLocal() as db:
            summary, _ = await run_prod_test_records_cleanup(
                db, marker=marker, plan=_plan(seed)
            )
            await db.commit()
        assert summary["contracts_skipped"] == {
            str(seed["ended"]): "fingerprint_mismatch"
        }
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, seed["ended"])
            assert contract.status == ContractStatus.active
            draft_status = await db.scalar(
                select(Contract.status).where(Contract.id == seed["draft"])
            )
            assert draft_status == ContractStatus.void
    finally:
        await _drop(seed, marker)
