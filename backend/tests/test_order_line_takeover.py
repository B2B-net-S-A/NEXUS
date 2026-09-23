"""Przejęcie pozostałych MD przy zastępstwie + „Usuń szkic" (ticket 09.2026).

Scenariusz z ticketu: Kamila (karta szkicu, kontrakt 85 zł/h) wchodzi za
Konrada (zamówienie CeZ/242/2025, pula w MD, 187 MD pozostało: 17 podstawy
i 170 opcji). Po zapisie Kamila ma na zamówieniu te 187 MD 1:1, Konrad 0 MD
pozostałych, a suma pozycji zamówienia liczy przeniesione MD raz.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.order_line_takeover import (
    POOL_UNIT_AMOUNT,
    POOL_UNIT_MD,
    TRANSFER_DEPARTING_RATE,
    TRANSFER_INCOMING_RATE,
    TRANSFER_ONE_TO_ONE,
    TakeoverError,
    resolve_transfer_method,
    split_transferred,
    transferred_md,
)

_TODAY = date.today()


def _enable_multi(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


# ── Arytmetyka ──────────────────────────────────────────────────────────────


def test_md_pool_moves_one_to_one_without_a_rate_choice():
    assert resolve_transfer_method(POOL_UNIT_MD, None) == TRANSFER_ONE_TO_ONE
    assert transferred_md(
        TRANSFER_ONE_TO_ONE, Decimal("187"), Decimal("800"), None
    ) == Decimal("187")
    with pytest.raises(TakeoverError):
        resolve_transfer_method(POOL_UNIT_MD, TRANSFER_INCOMING_RATE)


def test_amount_pool_requires_an_explicit_choice():
    """Żadna opcja nie jest domyślna — decyzję o liczbie dni podejmuje DL."""
    with pytest.raises(TakeoverError):
        resolve_transfer_method(POOL_UNIT_AMOUNT, None)
    with pytest.raises(TakeoverError):
        resolve_transfer_method(POOL_UNIT_AMOUNT, TRANSFER_ONE_TO_ONE)
    assert (
        resolve_transfer_method(POOL_UNIT_AMOUNT, TRANSFER_DEPARTING_RATE)
        == TRANSFER_DEPARTING_RATE
    )


def test_incoming_rate_divides_the_amount_and_rounds_to_a_tenth():
    # 10 MD × 1000 zł = 10 000 zł ÷ 1200 zł = 8,333… → 8,3 MD
    assert transferred_md(
        TRANSFER_INCOMING_RATE, Decimal("10"), Decimal("1000"), Decimal("1200")
    ) == Decimal("8.3")
    # „Po stawce odchodzącego" zostawia liczbę dni.
    assert transferred_md(
        TRANSFER_DEPARTING_RATE, Decimal("10"), Decimal("1000"), Decimal("1200")
    ) == Decimal("10")


def test_split_keeps_the_optional_scope_as_optional():
    base, optional = split_transferred(
        method=TRANSFER_ONE_TO_ONE,
        base_remaining=Decimal("17"),
        optional_remaining=Decimal("170"),
        has_optional=True,
        departing_rate=Decimal("800"),
        incoming_rate=Decimal("800"),
    )
    assert (base, optional) == (Decimal("17"), Decimal("170"))


def test_entrypoint_mirrors_the_dismissed_card_columns():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()
    assert "orders_card_dismissed_at TIMESTAMPTZ NULL" in entrypoint
    assert "orders_card_dismissed_by INTEGER NULL REFERENCES users(id)" in entrypoint


# ── Dane ────────────────────────────────────────────────────────────────────


async def _seed(
    *,
    source_state: str = "ended",
    input_mode: str = "md",
    with_case: bool = True,
) -> dict:
    """CeZ-podobne zamówienie per osoba: Konrad (odchodzi) + Kamila (szkic)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
    from app.models.client_order_offboarding import (
        OFFBOARDING_STATUS_PENDING,
        ClientOrderOffboardingCase,
    )
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.md_consumption import (
        CONSUMPTION_SOURCE_MANUAL,
        ClientOrderMdConsumption,
    )
    from app.models.order_type import OrderType

    suffix = uuid.uuid4().hex[:6]
    start = _TODAY - timedelta(days=300)
    if source_state == "ended":
        departure = _TODAY - timedelta(days=20)
    else:
        departure = _TODAY + timedelta(days=10)

    async with AsyncSessionLocal() as db:
        client = Client(name=f"TakeoverClient-{suffix}")
        db.add(client)
        await db.flush()
        konrad = Candidate(
            name="Konrad", lastname=f"Sigda-{suffix}", email=f"k-{suffix}@example.com"
        )
        kamila = Candidate(
            name="Kamila",
            lastname=f"Gniewek-{suffix}",
            email=f"g-{suffix}@example.com",
        )
        db.add_all([konrad, kamila])
        await db.flush()
        konrad_contract = Contract(
            candidate_id=konrad.id,
            client_id=client.id,
            status=(
                ContractStatus.ended
                if source_state == "ended"
                else ContractStatus.active
            ),
            start_date=start,
            end_date=departure,
            terminated_at=departure,
            rate_candidate=Decimal("95"),
            rate_client=Decimal("100"),
            rate_unit=RateUnit.hourly,
        )
        kamila_contract = Contract(
            candidate_id=kamila.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=30),
            rate_candidate=Decimal("85"),
            rate_unit=RateUnit.hourly,
        )
        db.add_all([konrad_contract, kamila_contract])
        await db.flush()
        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"CeZ/242/{suffix}",
            start_date=start,
            end_date=None,
            status=GROUP_STATUS_ACTIVE,
            order_type=OrderType.md,
            md_budget_mode="per_person",
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        rate = Decimal("800.00")
        line = ClientOrder(
            client_id=client.id,
            contract_id=konrad_contract.id,
            order_group_id=group.id,
            order_type=OrderType.md,
            title=f"Zamówienie {group.order_number} — Konrad",
            status=(
                ClientOrderStatus.completed
                if source_state == "ended"
                else ClientOrderStatus.active
            ),
            start_date=start,
            end_date=departure,
            md_rate_cost=Decimal("760.00"),
            md_rate_revenue=rate,
            rate_unit=RateUnit.daily,
            billing_hours_per_month=168,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            md_input_mode=input_mode,
            md_input_value=(
                Decimal("190") if input_mode == "md" else Decimal("190") * rate
            ),
            md_total=Decimal("190"),
            md_optional_total=Decimal("170"),
            md_remaining=Decimal("187"),
            md_manual_adjustment=Decimal("0"),
        )
        db.add(line)
        await db.flush()
        db.add(
            ClientOrderMdConsumption(
                order_id=line.id,
                period_month=start.strftime("%Y-%m"),
                md_reported=Decimal("173"),
                source=CONSUMPTION_SOURCE_MANUAL,
            )
        )
        case_id = None
        if source_state == "ended" and with_case:
            case = ClientOrderOffboardingCase(
                contract_id=konrad_contract.id,
                order_id=line.id,
                order_group_id=group.id,
                client_id=client.id,
                effective_date=departure,
                status=OFFBOARDING_STATUS_PENDING,
                version=1,
                uses_shared_md_pool=False,
                remaining_md_snapshot=Decimal("187"),
                rate_revenue_snapshot=rate,
                order_number_snapshot=group.order_number,
            )
            db.add(case)
            await db.flush()
            case_id = case.id
        await db.commit()
        return {
            "client_id": client.id,
            "group_id": group.id,
            "line_id": line.id,
            "case_id": case_id,
            "departure": departure,
            "konrad_contract_id": konrad_contract.id,
            "kamila_contract_id": kamila_contract.id,
        }


async def _group(app_client, headers, seed) -> dict:
    resp = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return next(g for g in resp.json()["groups"] if g["id"] == seed["group_id"])


def _takeover_url(seed: dict) -> str:
    return f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}/takeover"


# ── Wejdź za konsultanta ────────────────────────────────────────────────────


async def test_takeover_moves_the_md_pool_one_to_one_and_counts_it_once(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])

    before = await _group(app_client, app_auth_headers, seed)
    konrad_before = next(
        line for line in before["lines"] if line["id"] == seed["line_id"]
    )
    assert konrad_before["takeover_source"] == "ended"
    assert konrad_before["pool_unit"] == "md"
    positions_before = Decimal(str(before["md_positions_total"]))

    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": (seed["departure"] + timedelta(days=1)).isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
            "expected_case_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_line = resp.json()
    assert new_line["status"] == "active"
    assert Decimal(str(new_line["md_total"])) == Decimal("17")
    assert Decimal(str(new_line["md_optional_total"])) == Decimal("170")
    assert Decimal(str(new_line["md_remaining"])) == Decimal("187")
    assert Decimal(str(new_line["rate_cost"])) == Decimal("680")

    after = await _group(app_client, app_auth_headers, seed)
    konrad = next(line for line in after["lines"] if line["id"] == seed["line_id"])
    kamila = next(line for line in after["lines"] if line["id"] == new_line["id"])
    # B2: odchodzący nie pokazuje przeniesionych MD jako „pozostało".
    assert Decimal(str(konrad["md_remaining"])) == Decimal("0")
    assert konrad["replaced_by_kind"] == "takeover"
    assert konrad["replaced_by_order_id"] == new_line["id"]
    assert Decimal(str(konrad["replaced_by_md"])) == Decimal("187")
    assert konrad["offboarding_case"]["status"] == "resolved"
    assert konrad["takeover_source"] is None
    assert kamila["assignment_kind"] == "takeover"
    assert kamila["takeover_method"] == "one_to_one"
    assert Decimal(str(kamila["takeover_md"])) == Decimal("187")
    # Suma pozycji zamówienia się nie zmienia: 173 zużyte + 187 przeniesione.
    assert Decimal(str(after["md_positions_total"])) == positions_before

    events = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}/events",
        headers=app_auth_headers,
    )
    assert events.status_code == 200, events.text
    descriptions = " ".join(e["description"] for e in events.json()["events"])
    assert "Przeniesienie MD" in descriptions
    assert "187 MD (1:1)" in descriptions


async def test_takeover_without_a_case_records_a_resolved_one(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Linia zakończona bez sprawy też przekazuje pulę — z zapisaną decyzją."""
    seed = await _seed(with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": (seed["departure"] + timedelta(days=1)).isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    group = await _group(app_client, app_auth_headers, seed)
    konrad = next(line for line in group["lines"] if line["id"] == seed["line_id"])
    assert konrad["offboarding_case"]["resolution"] == "transfer"


async def test_amount_pool_takeover_needs_a_method_and_uses_it(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed(input_mode="amount")
    _enable_multi(monkeypatch, seed["client_id"])
    body = {
        "contract_id": seed["kamila_contract_id"],
        "departing_order_id": seed["line_id"],
        "entry_date": (seed["departure"] + timedelta(days=1)).isoformat(),
        "rate_cost": 680,
        "rate_revenue": 1000,
    }
    refused = await app_client.post(
        _takeover_url(seed), json=body, headers=app_auth_headers
    )
    assert refused.status_code == 422, refused.text

    resp = await app_client.post(
        _takeover_url(seed),
        json={**body, "md_transfer_method": "incoming_rate"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    # 187 MD × 800 zł ÷ 1000 zł = 149,6 MD
    assert Decimal(str(resp.json()["md_remaining"])) == Decimal("149.6")


async def test_offboarding_decision_is_blocked_by_a_scheduled_takeover(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zaplanowane zastępstwo za osobę z przyszłą datą zakończenia.

    Nowa linia czeka jako szkic, a w dniu wejścia — gdy odchodzący zakończył
    współpracę — przejmuje pulę z tego dnia i staje się aktywna.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.contract_order_offboarding import (
        apply_contract_order_offboarding,
    )
    from app.services.order_line_takeover import activate_due_takeovers

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    before = await _group(app_client, app_auth_headers, seed)
    konrad = next(line for line in before["lines"] if line["id"] == seed["line_id"])
    assert konrad["takeover_source"] == "leaving"
    assert konrad["departure_date"] == seed["departure"].isoformat()

    too_early = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": seed["departure"].isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
        },
        headers=app_auth_headers,
    )
    assert too_early.status_code == 422, too_early.text

    entry = seed["departure"] + timedelta(days=1)
    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": entry.isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    planned = resp.json()
    assert planned["status"] == "draft"

    group = await _group(app_client, app_auth_headers, seed)
    kamila = next(line for line in group["lines"] if line["id"] == planned["id"])
    konrad = next(line for line in group["lines"] if line["id"] == seed["line_id"])
    assert kamila["takeover_scheduled"] is True
    assert konrad["replaced_by_scheduled"] is True
    assert konrad["replaced_by_start_date"] == entry.isoformat()

    # Dzień po ostatnim dniu Konrada: terminacja domyka linię i zakłada sprawę,
    # a zastępstwo ją rozstrzyga.
    async with AsyncSessionLocal() as db:
        await apply_contract_order_offboarding(
            db,
            contract_id=seed["konrad_contract_id"],
            effective_date=seed["departure"],
            today=entry,
        )
        # Konrad zużył jeszcze 7 MD do końca współpracy.
        from app.models.md_consumption import (
            CONSUMPTION_SOURCE_MANUAL,
            ClientOrderMdConsumption,
        )
        from app.services.client_order_lines import recompute_remaining

        db.add(
            ClientOrderMdConsumption(
                order_id=seed["line_id"],
                period_month=seed["departure"].strftime("%Y-%m"),
                md_reported=Decimal("7"),
                source=CONSUMPTION_SOURCE_MANUAL,
            )
        )
        await db.flush()
        await recompute_remaining(db, await db.get(ClientOrder, seed["line_id"]))
        activated = await activate_due_takeovers(db, today=entry)
        await db.commit()
    assert activated == 1

    after = await _group(app_client, app_auth_headers, seed)
    kamila = next(line for line in after["lines"] if line["id"] == planned["id"])
    konrad = next(line for line in after["lines"] if line["id"] == seed["line_id"])
    assert kamila["status"] == "active"
    assert kamila["takeover_scheduled"] is False
    assert Decimal(str(kamila["md_remaining"])) == Decimal("180")
    assert Decimal(str(konrad["md_remaining"])) == Decimal("0")
    assert konrad["offboarding_case"]["status"] == "resolved"


async def test_manual_decision_refused_while_a_takeover_is_scheduled(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_offboarding import ClientOrderOffboardingCase
    from app.services.contract_order_offboarding import (
        apply_contract_order_offboarding,
    )

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    entry = seed["departure"] + timedelta(days=5)
    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": entry.isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        result = await apply_contract_order_offboarding(
            db,
            contract_id=seed["konrad_contract_id"],
            effective_date=seed["departure"],
            today=seed["departure"] + timedelta(days=1),
        )
        await db.commit()
        case = await db.get(ClientOrderOffboardingCase, result.case_ids[0])
        version = case.version
        case_id = case.id

    refused = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/offboarding-cases/{case_id}/resolve",
        json={"action": "remove", "expected_version": version},
        headers=app_auth_headers,
    )
    assert refused.status_code == 409, refused.text
    assert "zaplanowane zastępstwo" in refused.text


# ── B1 w decyzji o MD i w zamianie ──────────────────────────────────────────


async def _add_recipient(seed: dict) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import RateUnit
    from app.models.order_type import OrderType

    async with AsyncSessionLocal() as db:
        line = ClientOrder(
            client_id=seed["client_id"],
            contract_id=seed["kamila_contract_id"],
            order_group_id=seed["group_id"],
            order_type=OrderType.md,
            title="Zamówienie — Kamila",
            status=ClientOrderStatus.active,
            start_date=_TODAY - timedelta(days=30),
            md_rate_cost=Decimal("680.00"),
            md_rate_revenue=Decimal("1000.00"),
            rate_unit=RateUnit.daily,
            billing_hours_per_month=168,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            md_input_mode="md",
            md_input_value=Decimal("20"),
            md_total=Decimal("20"),
            md_remaining=Decimal("20"),
            md_manual_adjustment=Decimal("0"),
        )
        db.add(line)
        await db.commit()
        return line.id


async def test_offboarding_transfer_of_an_md_pool_is_one_to_one(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Stary przelicznik dałby 187 × 800 ÷ 1000 = 149,6 MD — pula w MD to 187."""
    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    recipient = await _add_recipient(seed)
    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/offboarding-cases/{seed['case_id']}/resolve",
        json={
            "action": "transfer",
            "target_order_id": recipient,
            "md_transfer_method": "one_to_one",
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    group = await _group(app_client, app_auth_headers, seed)
    target = next(line for line in group["lines"] if line["id"] == recipient)
    assert Decimal(str(target["md_remaining"])) == Decimal("207")

    wrong = await _seed()
    _enable_multi(monkeypatch, seed["client_id"], wrong["client_id"])
    other = await _add_recipient(wrong)
    refused = await app_client.post(
        f"/api/clients/{wrong['client_id']}/order-groups/{wrong['group_id']}"
        f"/offboarding-cases/{wrong['case_id']}/resolve",
        json={
            "action": "transfer",
            "target_order_id": other,
            "md_transfer_method": "incoming_rate",
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )
    assert refused.status_code == 422, refused.text


async def test_swap_with_md_pool_transfers_one_to_one(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, seed["konrad_contract_id"])
        contract.end_date = None
        contract.terminated_at = None
        contract.status = ContractStatus.active
        line = await db.get(ClientOrder, seed["line_id"])
        line.end_date = None
        line.status = ClientOrderStatus.active
        await db.commit()

    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/lines/{seed['line_id']}/swap",
        json={
            "contract_id": seed["kamila_contract_id"],
            "rate_cost": 680,
            "rate_revenue": 1000,
            "swap_date": _TODAY.isoformat(),
            "md_transfer_method": "one_to_one",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(str(body["md_total"])) == Decimal("17")
    assert Decimal(str(body["md_optional_total"])) == Decimal("170")


# ── Dołącz + „Usuń szkic" ───────────────────────────────────────────────────


async def test_join_marks_the_line_as_joined(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}/lines",
        json={
            "contract_id": seed["kamila_contract_id"],
            "rate_cost": 680,
            "rate_revenue": 800,
            "input_mode": "md",
            "input_value": 40,
            "optional_md": 10,
            "start_date": _TODAY.isoformat(),
            "assignment": "join",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    group = await _group(app_client, app_auth_headers, seed)
    kamila = next(line for line in group["lines"] if line["id"] == resp.json()["id"])
    assert kamila["assignment_kind"] == "join"


async def _seed_draft_card(*, with_active_order: bool = False) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"DraftCard-{suffix}")
        db.add(client)
        await db.flush()
        person = Candidate(
            name="Ewa", lastname=f"Szkic-{suffix}", email=f"s-{suffix}@example.com"
        )
        db.add(person)
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=10),
            rate_candidate=Decimal("85"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="Ewa — rekrutacja",
            status=(
                ClientOrderStatus.active
                if with_active_order
                else ClientOrderStatus.draft
            ),
            start_date=_TODAY - timedelta(days=10),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(order)
        await db.commit()
        return {
            "client_id": client.id,
            "contract_id": contract.id,
            "order_id": order.id,
        }


async def test_dismiss_draft_hides_the_card_and_keeps_the_contract(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract

    seed = await _seed_draft_card()
    listing = await app_client.get(
        f"/api/clients/{seed['client_id']}/orders", headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text
    card = listing.json()["contractors"][0]
    assert card["draft_card"] is True

    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/contractors/{seed['contract_id']}"
        "/dismiss-draft",
        headers=app_auth_headers,
    )
    assert resp.status_code == 204, resp.text

    listing = await app_client.get(
        f"/api/clients/{seed['client_id']}/orders", headers=app_auth_headers
    )
    assert listing.json()["contractors"] == []
    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, seed["contract_id"]) is not None
        assert await db.get(ClientOrder, seed["order_id"]) is None


async def test_dismiss_refuses_a_card_with_a_live_order(
    app_client: AsyncClient, app_auth_headers: dict
):
    seed = await _seed_draft_card(with_active_order=True)
    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/contractors/{seed['contract_id']}"
        "/dismiss-draft",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
