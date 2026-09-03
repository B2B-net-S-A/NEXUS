"""Trzecia decyzja Delivery Leada: „przywróć konsultanta jako aktywnego".

``remove`` oddaje pulę, ``transfer`` przekazuje ją komuś innemu — obie
zakładają, że współpraca naprawdę się skończyła. Zgłoszone sprawy są trzecim
przypadkiem: współpraca trwa dalej, więc linia ma wrócić na aktywną obsadę
z NIENARUSZONĄ pulą MD. Bez tej wartości jedynym wyjściem ze sprawy było
zapisanie decyzji, która się nie wydarzyła.

Testy pilnują trzech rzeczy, na których ta decyzja stoi lub upada:
pula nie może zostać zdjęta z zamówienia, kontrakt musi wrócić razem z linią
(inaczej nocny cron domknie ją z powrotem), a data zakończenia musi być
DECYZJĄ operatora — oryginalna przepadła przy offboardingu.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.client_order_group import OrderOffboardingResolutionRequest

_TODAY = date.today()


def _enable_multi(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


async def _seed_pending_case(*, shared_pool: bool = False) -> dict:
    """Klient MD + grupa + linia + ZAKOŃCZONY kontrakt ze sprawą `pending`.

    Odwzorowuje stan po ``apply_contract_order_offboarding``: linia
    ``completed`` z datą końca uciętą do dnia terminacji, kontrakt ``ended``,
    sprawa czekająca na decyzję.
    """
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

    suffix = uuid.uuid4().hex[:6]
    ended_on = _TODAY - timedelta(days=1)
    group_end = _TODAY + timedelta(days=120)

    async with AsyncSessionLocal() as db:
        client = Client(name=f"RestoreClient-{suffix}")
        db.add(client)
        await db.flush()

        candidate = Candidate(
            name="Tomasz",
            lastname=f"Plonka-{suffix}",
            email=f"restore-{suffix}@example.com",
        )
        db.add(candidate)
        await db.flush()

        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.ended,
            start_date=_TODAY - timedelta(days=200),
            end_date=ended_on,
            rate_candidate=Decimal("1000.000"),
            rate_client=Decimal("1320.000"),
            rate_unit=RateUnit.daily,
        )
        db.add(contract)
        await db.flush()

        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"3728_{suffix}",
            start_date=_TODAY - timedelta(days=200),
            end_date=group_end,
            status=GROUP_STATUS_ACTIVE,
            # LEGACY (`order_type IS NULL`) świadomie: od migracji 0251 CHECK
            # `ck_client_order_groups_explicit_type_coherence` dopuszcza
            # wspólną pulę przy JAWNYM typie `md` wyłącznie dla dwóch
            # klientowych odmian (Cyfrowy Polsat, Lotte Wedel). Grupy BIK/BNP,
            # o które chodzi w zgłoszeniu, są właśnie legacy.
            order_type=None,
            is_md_budget_based=shared_pool,
            md_budget_total=Decimal("500") if shared_pool else None,
            md_budget_remaining=Decimal("500") if shared_pool else None,
        )
        db.add(group)
        await db.flush()

        line = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            order_group_id=group.id,
            title=f"Zamówienie {group.order_number} — Tomasz Plonka",
            order_type=None,
            status=ClientOrderStatus.completed,
            start_date=_TODAY - timedelta(days=200),
            end_date=ended_on,
            md_rate_cost=Decimal("1000.00"),
            md_rate_revenue=Decimal("1320.00"),
            rate_unit=RateUnit.daily,
            billing_hours_per_month=160,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
        )
        if not shared_pool:
            line.md_input_mode = "md"
            line.md_input_value = Decimal("90")
            line.md_total = Decimal("90")
            line.md_remaining = Decimal("90")
        db.add(line)
        await db.flush()

        case = ClientOrderOffboardingCase(
            contract_id=contract.id,
            order_id=line.id,
            order_group_id=group.id,
            client_id=client.id,
            effective_date=ended_on,
            status=OFFBOARDING_STATUS_PENDING,
            version=1,
            uses_shared_md_pool=shared_pool,
            remaining_md_snapshot=Decimal("0") if shared_pool else Decimal("90"),
            rate_revenue_snapshot=Decimal("1320.00"),
            order_number_snapshot=group.order_number,
        )
        db.add(case)
        await db.commit()

        return {
            "client_id": client.id,
            "group_id": group.id,
            "line_id": line.id,
            "case_id": case.id,
            "contract_id": contract.id,
            "group_end": group_end,
            "ended_on": ended_on,
        }


async def _line_state(line_id: int) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        return {
            "status": line.status.value,
            "end_date": line.end_date,
            "md_total": None if line.md_total is None else Decimal(str(line.md_total)),
            "md_remaining": (
                None if line.md_remaining is None else Decimal(str(line.md_remaining))
            ),
        }


async def _contract_state(contract_id: int) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        return {"status": contract.status.value, "end_date": contract.end_date}


def _resolve_url(seed: dict) -> str:
    return (
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/offboarding-cases/{seed['case_id']}/resolve"
    )


# ── Kontrakt schematu ───────────────────────────────────────────────────────


def test_restore_rejects_a_recipient_and_a_rate_basis():
    """``restore`` niczego nie rozdysponowuje, więc nie ma odbiorcy ani stawki."""
    with pytest.raises(ValidationError):
        OrderOffboardingResolutionRequest(
            action="restore", expected_version=1, target_order_id=44
        )
    with pytest.raises(ValidationError):
        OrderOffboardingResolutionRequest(
            action="restore", expected_version=1, rate_basis="departing"
        )


def test_restore_end_date_belongs_only_to_restore():
    with pytest.raises(ValidationError):
        OrderOffboardingResolutionRequest(
            action="remove", expected_version=1, restore_end_date=_TODAY
        )
    request = OrderOffboardingResolutionRequest(
        action="restore", expected_version=1, restore_end_date=_TODAY
    )
    assert request.restore_end_date == _TODAY


# ── Decyzja end-to-end ──────────────────────────────────────────────────────


async def test_restore_brings_the_line_back_without_touching_the_pool(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Sedno decyzji: pula MD zostaje NIENARUSZONA.

    ``remove``/``transfer`` zdejmują niewykorzystane MD z wartości zamówienia
    (``_reduce_legacy_md_budget``). Tutaj byłoby to zapisaniem faktu, który się
    nie wydarzył — i zabraniem konsultantowi budżetu, na którym właśnie pracuje.
    """
    seed = await _seed_pending_case()
    _enable_multi(monkeypatch, seed["client_id"])
    new_end = seed["group_end"]

    resp = await app_client.post(
        _resolve_url(seed),
        json={
            "action": "restore",
            "restore_end_date": new_end.isoformat(),
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolution"] == "restore"

    line = await _line_state(seed["line_id"])
    assert line["status"] == "active"
    assert line["end_date"] == new_end
    assert line["md_total"] == Decimal("90")
    assert line["md_remaining"] == Decimal("90")


async def test_restore_revives_the_ended_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Bez wskrzeszenia kontraktu decyzja kasuje samą siebie.

    Konsultant zostaje w zakładce „Zakończeni" mimo aktywnej linii, a nocny
    cron widzi ``end_date < today``, stawia ``ended`` i ponownie domyka linię.
    Od 09.2026 wskrzeszona umowa jest BEZTERMINOWA, więc cron w ogóle jej nie
    ogląda (pomija ``end_date IS NULL``) — to ta sama ochrona, mocniejsza.
    """
    seed = await _seed_pending_case()
    _enable_multi(monkeypatch, seed["client_id"])

    resp = await app_client.post(
        _resolve_url(seed),
        json={
            "action": "restore",
            "restore_end_date": seed["group_end"].isoformat(),
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    contract = await _contract_state(seed["contract_id"])
    assert contract["status"] == "active"
    # Data końca umowy nie pochodzi z zamówienia (reguła zakładki
    # „Zakończeni"): wskrzeszona umowa jest bezterminowa, więc nocna promocja
    # statusów jej nie dotyka. Datę wpisuje administracja w Kontraktach.
    assert contract["end_date"] is None


async def test_restore_records_its_own_event(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Historia zamówienia musi odróżniać przywrócenie OSOBY od przywrócenia
    całego zamówienia — stąd osobny typ zdarzenia."""
    seed = await _seed_pending_case()
    _enable_multi(monkeypatch, seed["client_id"])

    resp = await app_client.post(
        _resolve_url(seed),
        json={
            "action": "restore",
            "restore_end_date": seed["group_end"].isoformat(),
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    events = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}/events",
        headers=app_auth_headers,
    )
    assert events.status_code == 200, events.text
    types = [event["event_type"] for event in events.json()["events"]]
    assert "przywrocenie_konsultanta" in types


async def test_restore_without_a_date_is_refused_when_the_order_ends(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Pusta data znaczy „bezterminowo" — linia przeżywałaby własne zamówienie."""
    seed = await _seed_pending_case()
    _enable_multi(monkeypatch, seed["client_id"])

    resp = await app_client.post(
        _resolve_url(seed),
        json={"action": "restore", "restore_end_date": None, "expected_version": 1},
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "datę" in resp.text


async def test_restore_refuses_a_past_end_date(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Data z przeszłości nie przywraca niczego — nocny cron domknie linię."""
    seed = await _seed_pending_case()
    _enable_multi(monkeypatch, seed["client_id"])

    resp = await app_client.post(
        _resolve_url(seed),
        json={
            "action": "restore",
            "restore_end_date": (_TODAY - timedelta(days=2)).isoformat(),
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_restore_refuses_a_date_beyond_the_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_pending_case()
    _enable_multi(monkeypatch, seed["client_id"])

    resp = await app_client.post(
        _resolve_url(seed),
        json={
            "action": "restore",
            "restore_end_date": (seed["group_end"] + timedelta(days=1)).isoformat(),
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_restore_works_on_a_shared_pool_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wspólna pula: nie ma czego przywracać na linii, ale osoba wraca.

    Linia ze wspólnej puli ma ``md_total IS NULL``, więc NIE chroni jej
    ``sync_md_line_status`` — to ją domyka nocny skaner po dacie. Dlatego
    właśnie data zakończenia jest tu obowiązkowa i musi być przyszła.
    """
    seed = await _seed_pending_case(shared_pool=True)
    _enable_multi(monkeypatch, seed["client_id"])

    resp = await app_client.post(
        _resolve_url(seed),
        json={
            "action": "restore",
            "restore_end_date": seed["group_end"].isoformat(),
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    line = await _line_state(seed["line_id"])
    assert line["status"] == "active"
    assert line["md_total"] is None


async def test_a_resolved_case_cannot_be_restored_twice(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_pending_case()
    _enable_multi(monkeypatch, seed["client_id"])
    payload = {
        "action": "restore",
        "restore_end_date": seed["group_end"].isoformat(),
        "expected_version": 1,
    }

    first = await app_client.post(
        _resolve_url(seed), json=payload, headers=app_auth_headers
    )
    assert first.status_code == 200, first.text

    second = await app_client.post(
        _resolve_url(seed), json=payload, headers=app_auth_headers
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "offboarding_case_already_resolved"
