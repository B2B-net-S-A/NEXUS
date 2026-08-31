"""Przedłużenie, którego okres OBEJMUJE dziś, wskrzesza zakończony kontrakt.

Zgłoszenie: „Dodanie przedłużenia do zamówienia z zakładki Zakończone nie
przenosi go do Aktywnych". Kanoniczny mechanizm istniał już dla ``POST
/clients/{id}/orders``, ale omijały go inne równoważne writery: import Nordea,
PATCH kompletujący draft oraz linie zamówień grupowych. Widoczne było to tylko
z zakładki „Zakończeni", bo pigułki czytają ``contract_status``, a kontraktor
aktywny i tak już tam był.

Reguła sprawdzana tutaj zależy WYŁĄCZNIE od dat, nie od zakładki źródłowej.
"""

from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, ContractWorkMode
from app.services.contract_lifecycle import order_period_covers

pytestmark = pytest.mark.asyncio


async def _seed_ended_contract(
    *,
    end_date: date,
    client_order_end_date: date | None = None,
    status: ContractStatus = ContractStatus.ended,
) -> tuple[int, int]:
    """Kontraktor po zakończonym projekcie — wiersz z zakładki „Zakończeni”."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Erste Test {suffix}")
        candidate = Candidate(name=f"Mariusz{suffix}", lastname=f"Testowy{suffix}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            work_mode=ContractWorkMode.remote,
            status=status,
            start_date=end_date - timedelta(days=365),
            end_date=end_date,
            rate_candidate=15000,
            rate_client=20000,
            client_order_end_date=client_order_end_date,
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id


async def _contract_state(contract_id: int) -> tuple[ContractStatus, date | None]:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        return contract.status, contract.end_date


async def _client_order_end(contract_id: int) -> date | None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        return contract.client_order_end_date


async def _post_extension(
    app_client, headers, client_id: int, contract_id: int, *, start: date, end
):
    data = {
        "contract_id": str(contract_id),
        "title": f"K/2026/{uuid.uuid4().hex[:6]}",
        "start_date": start.isoformat(),
        "order_status": "active",
        "rate_client": "20000",
    }
    if end is not None:
        data["end_date"] = end.isoformat()
    return await app_client.post(
        f"/api/clients/{client_id}/orders", data=data, headers=headers
    )


class TestOrderPeriodCovers:
    """Czysta reguła dat — bez DB, bez HTTP."""

    async def test_running_period_covers_today(self):
        today = date(2026, 8, 25)
        assert order_period_covers(date(2026, 7, 1), date(2026, 9, 30), today)

    async def test_future_start_does_not_cover(self):
        today = date(2026, 8, 25)
        assert not order_period_covers(date(2026, 9, 1), date(2026, 12, 31), today)

    async def test_past_period_does_not_cover(self):
        today = date(2026, 8, 25)
        assert not order_period_covers(date(2026, 1, 1), date(2026, 6, 30), today)

    async def test_open_ended_reaches_right_without_bound(self):
        today = date(2026, 8, 25)
        assert order_period_covers(date(2026, 7, 1), None, today)

    async def test_boundaries_are_inclusive(self):
        today = date(2026, 8, 25)
        assert order_period_covers(today, today, today)

    async def test_missing_start_is_not_assumed_to_have_begun(self):
        """Puste pole nie jest dowodem, że współpraca trwa."""
        assert not order_period_covers(None, date(2026, 12, 31), date(2026, 8, 25))


async def test_daily_reconciler_query_is_transition_only_and_lossless():
    """The receipt-bounded catch-up may not cross into audited history."""

    from sqlalchemy.dialects import postgresql

    from app.services.contract_lifecycle import (
        _live_order_reconcile_window,
        reconcile_contracts_to_live_orders,
    )

    class _NoRows:
        def __iter__(self):
            return iter(())

    class _CaptureDb:
        sql = ""

        async def get(self, model, key):
            return SimpleNamespace(
                value={
                    "business_day": "2026-08-29",
                    "audited_contract_ids": [901],
                }
            )

        async def execute(self, statement):
            self.sql = str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            return _NoRows()

    db = _CaptureDb()
    assert await reconcile_contracts_to_live_orders(db, today=date(2026, 8, 31)) == 0
    assert "client_orders.start_date BETWEEN '2026-08-29' AND '2026-08-31'" in db.sql
    # Active add/swap lines in an already-active group use the same transition.
    assert "client_orders.order_group_id IS NULL" not in db.sql
    # The first catch-up pass waits instead of relying on a later retry.
    assert "FOR UPDATE OF client_orders, contracts" in db.sql
    assert "SKIP LOCKED" not in db.sql

    assert _live_order_reconcile_window(
        {
            "business_day": "2026-08-29",
            "audited_contract_ids": [901, 902],
        },
        today=date(2026, 8, 31),
    ) == (date(2026, 8, 29), frozenset({901, 902}))
    # No trustworthy receipt means no historical range expansion.
    assert _live_order_reconcile_window(None, today=date(2026, 8, 31)) == (
        date(2026, 8, 31),
        frozenset(),
    )
    assert _live_order_reconcile_window(
        {"business_day": "not-a-date", "audited_contract_ids": []},
        today=date(2026, 8, 31),
    ) == (date(2026, 8, 31), frozenset())


async def test_daily_reconciler_catches_up_after_a_missed_day_but_skips_cutover_audit():
    """A missed post-deploy start heals; a receipt-audited cutover row does not."""

    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.services.contract_lifecycle import reconcile_contracts_to_live_orders

    cutover = date(2032, 4, 8)
    today = cutover + timedelta(days=2)
    audited_contract = Contract(
        id=901,
        client_id=1,
        status=ContractStatus.ended,
        end_date=cutover - timedelta(days=1),
    )
    missed_contract = Contract(
        id=902,
        client_id=1,
        status=ContractStatus.ended,
        end_date=cutover - timedelta(days=1),
    )
    audited_order = ClientOrder(
        id=1901,
        client_id=1,
        contract_id=audited_contract.id,
        status=ClientOrderStatus.active,
        start_date=cutover,
        end_date=today + timedelta(days=30),
    )
    missed_order = ClientOrder(
        id=1902,
        client_id=1,
        contract_id=missed_contract.id,
        status=ClientOrderStatus.active,
        start_date=cutover + timedelta(days=1),
        end_date=today + timedelta(days=60),
    )

    class _Rows:
        def __iter__(self):
            return iter(
                (
                    (audited_order, audited_contract),
                    (missed_order, missed_contract),
                )
            )

        def one_or_none(self):
            return (
                missed_contract.status,
                missed_contract.end_date,
                missed_contract.client_order_end_date,
            )

    class _FakeDb:
        def __init__(self):
            self.added = []
            self.no_autoflush = nullcontext()

        async def get(self, model, key):
            return SimpleNamespace(
                value={
                    "business_day": cutover.isoformat(),
                    "audited_contract_ids": [audited_contract.id],
                }
            )

        async def execute(self, statement):
            return _Rows()

        def add(self, value):
            self.added.append(value)

    db = _FakeDb()
    assert await reconcile_contracts_to_live_orders(db, today=today) == 1
    assert audited_contract.status == ContractStatus.ended
    assert missed_contract.status == ContractStatus.active
    assert missed_contract.end_date == missed_order.end_date
    assert len(db.added) == 1


async def test_live_order_sync_refreshes_under_lock_and_preserves_concurrent_void():
    """A stale ``ended`` object may not overwrite a terminal ``void`` commit."""

    from sqlalchemy.dialects import postgresql

    from app.services.contract_lifecycle import sync_contract_to_live_order

    today = date(2032, 4, 10)
    original_end = today - timedelta(days=1)
    stale = Contract(
        id=903,
        client_id=1,
        status=ContractStatus.ended,
        end_date=original_end,
    )
    loaded_candidate = Candidate(name="Lock", lastname="Preserved")
    stale.candidate = loaded_candidate

    class _RefreshToVoidDb:
        def __init__(self):
            self.no_autoflush = nullcontext()
            self.sql = ""
            self.added = []

        async def execute(self, statement):
            self.sql = str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            return SimpleNamespace(
                one_or_none=lambda: (ContractStatus.void, original_end, None)
            )

        def add(self, value):
            self.added.append(value)

    db = _RefreshToVoidDb()
    changed = await sync_contract_to_live_order(
        db,
        stale,
        order_start=today - timedelta(days=10),
        order_end=today + timedelta(days=90),
        actor_id=7,
        today=today,
    )

    assert changed is False
    assert "FOR UPDATE" in db.sql
    assert "contracts.candidate_id" not in db.sql
    assert stale.status == ContractStatus.void
    assert stale.end_date == original_end
    assert stale.candidate is loaded_candidate
    assert db.added == []


async def test_live_order_sync_noops_for_missing_or_fresh_draft_contract():
    """A deleted row and a just-flushed draft both stay outside reactivation."""

    from app.services.contract_lifecycle import sync_contract_to_live_order

    today = date(2032, 4, 10)

    class _ScalarDb:
        def __init__(self, result):
            self.result = result
            self.no_autoflush = nullcontext()
            self.added = []

        async def execute(self, statement):
            if self.result is None:
                row = None
            else:
                row = (
                    self.result.status,
                    self.result.end_date,
                    self.result.client_order_end_date,
                )
            return SimpleNamespace(one_or_none=lambda: row)

        def add(self, value):
            self.added.append(value)

    disappeared = Contract(
        id=904,
        client_id=1,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=1),
    )
    missing_db = _ScalarDb(None)
    assert not await sync_contract_to_live_order(
        missing_db,
        disappeared,
        order_start=today,
        order_end=today + timedelta(days=30),
        actor_id=7,
        today=today,
    )
    assert disappeared.status == ContractStatus.ended
    assert missing_db.added == []

    flushed_draft = Contract(
        id=905,
        client_id=1,
        status=ContractStatus.draft,
        start_date=today,
    )
    draft_db = _ScalarDb(flushed_draft)
    assert not await sync_contract_to_live_order(
        draft_db,
        flushed_draft,
        order_start=today,
        order_end=today + timedelta(days=30),
        actor_id=7,
        today=today,
    )
    assert flushed_draft.status == ContractStatus.draft
    assert draft_db.added == []


async def test_patch_contract_sync_gate_only_accepts_lifecycle_changes():
    """Metadata-only active PATCH stays audit-only; transition/period do not."""

    from app.api.client_orders import _patch_requires_contract_sync
    from app.models.client_order import ClientOrder, ClientOrderStatus

    start = date(2026, 8, 1)
    end = date(2026, 12, 31)
    order = ClientOrder(
        status=ClientOrderStatus.active,
        start_date=start,
        end_date=end,
    )

    assert not _patch_requires_contract_sync(
        order,
        previous_status=ClientOrderStatus.active,
        previous_start_date=start,
        previous_end_date=end,
    )
    assert _patch_requires_contract_sync(
        order,
        previous_status=ClientOrderStatus.draft,
        previous_start_date=start,
        previous_end_date=end,
    )
    assert _patch_requires_contract_sync(
        order,
        previous_status=ClientOrderStatus.active,
        previous_start_date=start,
        previous_end_date=end - timedelta(days=1),
    )

    order.status = ClientOrderStatus.cancelled
    assert not _patch_requires_contract_sync(
        order,
        previous_status=ClientOrderStatus.active,
        previous_start_date=start,
        previous_end_date=end,
    )


async def test_running_extension_moves_contractor_back_to_active(
    app_client, app_auth_headers
):
    """Scenariusz (a) z ticketu — przedłużenie trwające dziś."""
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=60)
    )
    new_end = today + timedelta(days=36)

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today - timedelta(days=25),
        end=new_end,
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.active
    # Data końca musi iść za zamówieniem — inaczej nocny `_promote_statuses`
    # zdemotuje wskrzeszony kontrakt z powrotem tej samej nocy.
    assert end_date == new_end


async def test_patch_that_completes_a_running_draft_revives_the_contract(
    app_client, app_auth_headers
):
    """Inline UI flow: POST placeholder draft, then PATCH the missing number.

    This is the path used by a contractor card without a complete order.  The
    POST correctly leaves the placeholder as draft; the PATCH promotes it to
    active and must apply the same Contract invariant as „Dodaj przedluzenie".
    """

    today = date.today()
    previous_end = today - timedelta(days=45)
    new_end = today + timedelta(days=90)
    client_id, contract_id = await _seed_ended_contract(end_date=previous_end)

    created = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data={
            "contract_id": str(contract_id),
            "title": "(bez numeru)",
            "start_date": (today - timedelta(days=2)).isoformat(),
            "end_date": new_end.isoformat(),
            "order_status": "draft",
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"

    completed = await app_client.patch(
        f"/api/clients/{client_id}/orders/{created.json()['id']}",
        json={"title": "285493"},
        headers=app_auth_headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "active"

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.active
    assert end_date == new_end


async def test_active_order_metadata_patch_does_not_backfill_legacy_contract(
    app_client, app_auth_headers
):
    """Only an active transition or period change may heal an audit-only row."""

    from app.models.client_order import ClientOrder, ClientOrderStatus

    today = date.today()
    previous_contract_end = today - timedelta(days=45)
    client_id, contract_id = await _seed_ended_contract(end_date=previous_contract_end)
    original_order_end = today + timedelta(days=30)

    # Reproduce an analogous pre-fix record deliberately left read-only by
    # migration 0250: the Order is live, but its Contract is still ``ended``.
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="LEGACY-AUDIT-ONLY",
            status=ClientOrderStatus.active,
            start_date=today - timedelta(days=10),
            end_date=original_order_end,
            notes="before",
        )
        db.add(order)
        await db.commit()
        order_id = order.id

    metadata_only = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        json={"notes": "after"},
        headers=app_auth_headers,
    )
    assert metadata_only.status_code == 200, metadata_only.text
    assert await _contract_state(contract_id) == (
        ContractStatus.ended,
        previous_contract_end,
    )

    # A real period change is a lifecycle writer and therefore may apply the
    # canonical invariant to the same record.
    extended_order_end = today + timedelta(days=90)
    period_change = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        json={"end_date": extended_order_end.isoformat()},
        headers=app_auth_headers,
    )
    assert period_change.status_code == 200, period_change.text
    assert await _contract_state(contract_id) == (
        ContractStatus.active,
        extended_order_end,
    )


async def test_future_extension_leaves_the_contract_alone(app_client, app_auth_headers):
    """Scenariusz (b) — przedłużenie zaczynające się w przyszłości."""
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(end_date=previous_end)

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today + timedelta(days=30),
        end=today + timedelta(days=120),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.ended
    assert end_date == previous_end


async def test_daily_scanner_revives_only_live_active_orders():
    """Future orders reconcile on their start day, exactly once.

    The same daily pass must ignore every nearby negative case: an order which
    is still future, already expired, a draft, cancelled, or a historical live
    order which started before today.  This is the transition-only temporal
    half of the writer-time rule tested above, not a backlog repair.
    """

    from sqlalchemy import func, select

    from app.core.scheduling import business_today
    from app.models.activity import Activity
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup, GROUP_STATUS_ACTIVE
    from app.tasks.dl_portal_expiry_scanner import _promote_statuses

    today = business_today()
    cases = {
        "live": await _seed_ended_contract(end_date=today - timedelta(days=30)),
        "live_ending": await _seed_ended_contract(
            end_date=today - timedelta(days=30),
            status=ContractStatus.ending,
        ),
        "grouped_live": await _seed_ended_contract(end_date=today - timedelta(days=30)),
        "legacy_live": await _seed_ended_contract(end_date=today - timedelta(days=30)),
        "future": await _seed_ended_contract(end_date=today - timedelta(days=30)),
        "expired": await _seed_ended_contract(end_date=today - timedelta(days=30)),
        "draft": await _seed_ended_contract(end_date=today - timedelta(days=30)),
        "cancelled": await _seed_ended_contract(end_date=today - timedelta(days=30)),
    }

    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=cases["grouped_live"][0],
            order_number="ACTIVE-GROUP-WITH-FUTURE-ADD",
            start_date=today - timedelta(days=120),
            end_date=today + timedelta(days=180),
            status=GROUP_STATUS_ACTIVE,
        )
        db.add(group)
        await db.flush()
        db.add_all(
            [
                ClientOrder(
                    client_id=cases["live"][0],
                    contract_id=cases["live"][1],
                    title="LIVE-PO",
                    status=ClientOrderStatus.active,
                    start_date=today,
                    end_date=today + timedelta(days=120),
                ),
                ClientOrder(
                    client_id=cases["future"][0],
                    contract_id=cases["future"][1],
                    title="FUTURE-PO",
                    status=ClientOrderStatus.active,
                    start_date=today + timedelta(days=1),
                    end_date=today + timedelta(days=120),
                ),
                ClientOrder(
                    client_id=cases["live_ending"][0],
                    contract_id=cases["live_ending"][1],
                    title="LIVE-ENDING-PO",
                    status=ClientOrderStatus.active,
                    start_date=today,
                    end_date=today + timedelta(days=90),
                ),
                ClientOrder(
                    client_id=cases["grouped_live"][0],
                    contract_id=cases["grouped_live"][1],
                    order_group_id=group.id,
                    title="GROUPED-FUTURE-ADD-PO",
                    status=ClientOrderStatus.active,
                    start_date=today,
                    end_date=today + timedelta(days=150),
                ),
                ClientOrder(
                    client_id=cases["legacy_live"][0],
                    contract_id=cases["legacy_live"][1],
                    title="ALREADY-STARTED-LEGACY-PO",
                    status=ClientOrderStatus.active,
                    start_date=today - timedelta(days=10),
                    end_date=today + timedelta(days=120),
                ),
                ClientOrder(
                    client_id=cases["expired"][0],
                    contract_id=cases["expired"][1],
                    title="EXPIRED-PO",
                    status=ClientOrderStatus.active,
                    start_date=today - timedelta(days=120),
                    end_date=today - timedelta(days=1),
                ),
                ClientOrder(
                    client_id=cases["draft"][0],
                    contract_id=cases["draft"][1],
                    title="DRAFT-PO",
                    status=ClientOrderStatus.draft,
                    start_date=today - timedelta(days=1),
                    end_date=today + timedelta(days=120),
                ),
                ClientOrder(
                    client_id=cases["cancelled"][0],
                    contract_id=cases["cancelled"][1],
                    title="CANCELLED-PO",
                    status=ClientOrderStatus.cancelled,
                    start_date=today - timedelta(days=1),
                    end_date=today + timedelta(days=120),
                ),
            ]
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        first = await _promote_statuses(db, business_day=today)
        await db.commit()
    # Other tests share the database and may leave their own eligible rows;
    # all three records created here must be included, without assuming global
    # isolation of the scanner count.
    assert first[3] >= 3

    async with AsyncSessionLocal() as db:
        second = await _promote_statuses(db, business_day=today)
        await db.commit()
    assert second[3] == 0

    live_contract_ids = [
        cases["live"][1],
        cases["live_ending"][1],
        cases["grouped_live"][1],
    ]
    async with AsyncSessionLocal() as db:
        statuses = {
            name: (await db.get(Contract, contract_id)).status
            for name, (_, contract_id) in cases.items()
        }
        live = await db.get(Contract, live_contract_ids[0])
        live_ending = await db.get(Contract, live_contract_ids[1])
        audit_count = await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.entity_type == "contract",
                Activity.entity_id.in_(live_contract_ids),
                Activity.action == "contract_reopened",
            )
        )

    assert statuses == {
        "live": ContractStatus.active,
        "live_ending": ContractStatus.active,
        "grouped_live": ContractStatus.active,
        "legacy_live": ContractStatus.ended,
        "future": ContractStatus.ended,
        "expired": ContractStatus.ended,
        "draft": ContractStatus.ended,
        "cancelled": ContractStatus.ended,
    }
    assert live is not None and live.end_date == today + timedelta(days=120)
    assert live_ending is not None and live_ending.end_date == today + timedelta(
        days=90
    )
    grouped_live = await _contract_state(cases["grouped_live"][1])
    assert grouped_live == (
        ContractStatus.active,
        today + timedelta(days=150),
    )
    assert audit_count == 3


async def test_open_ended_running_extension_makes_the_contract_indefinite(
    app_client, app_auth_headers
):
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=10),
        client_order_end_date=today - timedelta(days=10),
    )

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today,
        end=None,
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.active
    assert end_date is None
    # „Koniec zamówienia u klienta" z PRZESZŁĄ datą na umowie bezterminowej
    # przestał cokolwiek opisywać: profil kontraktu pokazałby go obok „Okres:
    # … – bezterminowo". Alert `_client_orders_ending` tego NIE zgłosi
    # (wymaga `>= today`), więc rozjazd byłby całkowicie niemy. Migracja 0243
    # zeruje tę kolumnę dla wierszy historycznych — runtime musi robić to samo.
    assert await _client_order_end(contract_id) is None


async def test_running_extension_moves_the_tracked_client_order_end(
    app_client, app_auth_headers
):
    """Śledzony „Koniec zamówienia u klienta" idzie za nowym horyzontem…"""
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=60),
        client_order_end_date=today - timedelta(days=60),
    )
    new_end = today + timedelta(days=36)
    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today - timedelta(days=25),
        end=new_end,
    )
    assert resp.status_code == 201, resp.text
    assert await _client_order_end(contract_id) == new_end


async def test_untracked_client_order_end_is_not_invented(app_client, app_auth_headers):
    """…ale NULL zostaje NULL-em — nie wymyślamy daty, której nikt nie śledził.

    Lustro `_synced_client_order_end` (ta sama reguła co przy aneksie
    i `/bulk-extend`).
    """
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=60), client_order_end_date=None
    )
    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today - timedelta(days=25),
        end=today + timedelta(days=36),
    )
    assert resp.status_code == 201, resp.text
    assert await _client_order_end(contract_id) is None


async def test_draft_extension_is_not_evidence_of_running_work(
    app_client, app_auth_headers
):
    """Szkic nie jest zobowiązaniem — nie wolno nim wskrzeszać kontraktu."""
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(end_date=previous_end)

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data={
            "contract_id": str(contract_id),
            "title": "(bez numeru)",
            "start_date": (today - timedelta(days=5)).isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(),
            "order_status": "draft",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.ended
    assert end_date == previous_end


async def test_void_contract_is_never_touched_by_an_order(app_client, app_auth_headers):
    """``void`` jest TERMINALNY — zamówienie nie przesuwa daty umowy unieważnionej.

    ``create_order_extension`` nie filtruje statusu kontraktu, więc zamówienie
    da się dopiąć także do soft-skasowanej umowy. Bez bramki wskrzeszenie po
    cichu zmieniałoby jej `end_date` — a `ALLOWED_TRANSITIONS[void]` jest
    pustym zbiorem właśnie dlatego, że z tego stanu nie ma wyjścia.
    """
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(
        end_date=previous_end, status=ContractStatus.void
    )

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today - timedelta(days=5),
        end=today + timedelta(days=90),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.void
    assert end_date == previous_end


async def test_draft_contract_is_not_activated_through_an_order(
    app_client, app_auth_headers
):
    """Szkic ma WŁASNY walidowany cykl życia — nie wchodzi się w przychód bokiem."""
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(
        end_date=previous_end, status=ContractStatus.draft
    )

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today - timedelta(days=5),
        end=today + timedelta(days=90),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.draft
    assert end_date == previous_end


async def test_active_contract_horizon_is_left_alone(app_client, app_auth_headers):
    """Zamówienie NIE rozciąga horyzontu umowy, która i tak obowiązuje.

    Przed tą zmianą dodanie zamówienia nie ruszało `end_date` aktywnej umowy
    i nikt o to nie prosił — rozszerzenie tego „przy okazji" byłoby zmianą
    zachowania poza zakresem ticketu.
    """
    today = date.today()
    contract_end = today + timedelta(days=10)
    client_id, contract_id = await _seed_ended_contract(
        end_date=contract_end, status=ContractStatus.active
    )

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today,
        end=today + timedelta(days=180),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.active
    assert end_date == contract_end
