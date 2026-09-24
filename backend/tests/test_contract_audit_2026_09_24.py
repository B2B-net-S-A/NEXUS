"""Audyt modułu Kontrakty 24.09.2026 (blok D) — backend.

W1  zmiana jednostki (godziny ↔ miesiąc) przelicza kwoty — PATCH i aneks,
W2  zapis harmonogramu z formularza zachowuje notatki i autora kroków,
S1  benchmark nie pada na stawce z ułamkiem (Numeric(16, 6) × 168),
S3  zaślepka „(bez numeru)” nie dostaje stawki przychodowej z kontraktu,
S4  anulowanie kontraktu z żywymi zamówieniami = 409,
S5  aneks „wcześniejsze zakończenie” przez API = 409 (okno zakończenia),
S7  zbiorcze przedłużenie: koniec miesiąca, bez `void`, historia tylko
    przy przedłużonych,
S11 eksport zna „Anulowany” i „Do podpisu”,
N1  aneks stawki na kontrakcie bez daty rozpoczęcia nie daje 500,
N6  `/activate` nie ogłasza podpisu w Teams.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.contracts import (
    _CONTRACT_STATUS_LABELS,
    _add_months_keeping_month_end,
    _inherit_rates_into_unpriced_order_drafts,
    _monthly_equivalent,
    _rebuild_rate_schedule,
    _switch_unit_for_patch,
)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import (
    Contract,
    ContractCandidateRate,
    ContractStatus,
    ContractType,
    RateUnit,
)

TODAY = date(2026, 9, 24)


def _memory_contract(**overrides) -> Contract:
    contract = Contract(
        id=1,
        client_id=10,
        candidate_id=5,
        contract_type=ContractType.b2b,
        status=ContractStatus.active,
        start_date=date(2026, 1, 1),
        rate_candidate=Decimal("150"),
        rate_client=Decimal("200"),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=168,
        currency="PLN",
    )
    contract.candidate_rate_schedule = overrides.pop("candidate_rate_schedule", [])
    contract.client_rate_schedule = overrides.pop("client_rate_schedule", [])
    contract.framework_rate_schedule = overrides.pop("framework_rate_schedule", [])
    for key, value in overrides.items():
        setattr(contract, key, value)
    return contract


# ── Testy bez bazy ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 6, 30), 3, date(2026, 9, 30)),
        (date(2026, 6, 30), 1, date(2026, 7, 31)),
        (date(2027, 1, 31), 1, date(2027, 2, 28)),
        (date(2026, 1, 15), 12, date(2027, 1, 15)),
        (date(2026, 11, 29), 3, date(2027, 2, 28)),
    ],
)
def test_bulk_extend_month_arithmetic_keeps_the_month_end(start, months, expected):
    """S7: dawne ``min(day, 28)`` skracało 30.06 + 3 mies. do 28.09."""
    assert _add_months_keeping_month_end(start, months) == expected


def test_benchmark_monthly_equivalent_accepts_fractional_hourly_rates():
    """S1: 125,19375 zł/h × 168 to ułamek — schemat ``int`` dawał 500."""
    value = _monthly_equivalent(Decimal("125.19375"), RateUnit.hourly, 168)
    assert value == pytest.approx(21032.55)
    assert _monthly_equivalent(Decimal("1000"), RateUnit.daily, 168) == 21000.0
    assert _monthly_equivalent(None, RateUnit.hourly, 168) is None


def test_patch_unit_switch_converts_amounts_and_drops_unchanged_form_values():
    """W1: formularz odsyła nieruszone kwoty w STAREJ jednostce — przeliczamy."""
    contract = _memory_contract()
    updates = {
        "rate_unit": RateUnit.monthly,
        "rate_candidate": 150,
        "rate_client": 200,
    }

    keep = _switch_unit_for_patch(
        contract,
        updates,
        RateUnit.monthly,
        previous_rate_client=Decimal("200"),
        today=TODAY,
        schedule_input=None,
        framework_input=None,
    )

    assert keep == (True, True)
    assert "rate_candidate" not in updates and "rate_client" not in updates
    assert contract.rate_unit == RateUnit.monthly
    assert contract.rate_candidate == Decimal("25200")
    assert contract.rate_client == Decimal("33600")


def test_patch_unit_switch_keeps_a_new_value_typed_in_the_new_unit():
    contract = _memory_contract()
    updates = {"rate_unit": RateUnit.monthly, "rate_client": 30000}

    _switch_unit_for_patch(
        contract,
        updates,
        RateUnit.monthly,
        previous_rate_client=Decimal("200"),
        today=TODAY,
        schedule_input=None,
        framework_input=None,
    )

    assert updates["rate_client"] == 30000
    assert contract.rate_candidate == Decimal("25200")


def test_patch_unit_switch_converts_an_unchanged_schedule_and_skips_its_replacement():
    steps = [
        ContractCandidateRate(
            rate=Decimal("150"),
            effective_from=date(2026, 1, 1),
            note="Stawka początkowa",
        ),
        ContractCandidateRate(
            rate=Decimal("160"), effective_from=date(2026, 7, 1), note="Aneks"
        ),
    ]
    contract = _memory_contract(candidate_rate_schedule=steps)
    sent = [
        {"rate": 150, "effective_from": date(2026, 1, 1), "effective_to": None},
        {"rate": 160, "effective_from": date(2026, 7, 1), "effective_to": None},
    ]

    schedule_changed, _ = _switch_unit_for_patch(
        contract,
        {"rate_unit": RateUnit.monthly},
        RateUnit.monthly,
        previous_rate_client=Decimal("200"),
        today=TODAY,
        schedule_input=sent,
        framework_input=None,
    )

    assert schedule_changed is False
    assert [s.rate for s in contract.candidate_rate_schedule] == [
        Decimal("25200"),
        Decimal("26880"),
    ]
    assert [s.note for s in contract.candidate_rate_schedule] == [
        "Stawka początkowa",
        "Aneks",
    ]


def test_schedule_rebuild_keeps_notes_and_authors_of_unchanged_steps():
    """W2: formularz nie wysyła notatek — zapis gubił „Stawka początkowa”."""
    existing = [
        ContractCandidateRate(
            rate=Decimal("150"),
            effective_from=date(2026, 1, 1),
            note="Stawka początkowa",
            created_by=7,
        ),
        ContractCandidateRate(
            rate=Decimal("165"),
            effective_from=date(2026, 1, 1),
            note="Aneks od startu",
            created_by=8,
        ),
    ]
    sent = [
        {"rate": 150, "effective_from": date(2026, 1, 1), "effective_to": None},
        {"rate": 165, "effective_from": date(2026, 1, 1), "effective_to": None},
        {"rate": 180, "effective_from": date(2026, 10, 1), "effective_to": None},
    ]

    rebuilt = _rebuild_rate_schedule(ContractCandidateRate, existing, sent, actor_id=99)

    assert [(s.rate, s.note, s.created_by) for s in rebuilt] == [
        (150, "Stawka początkowa", 7),
        (165, "Aneks od startu", 8),
        (180, None, 99),
    ]


def test_schedule_rebuild_prefers_a_note_sent_explicitly():
    existing = [
        ContractCandidateRate(
            rate=Decimal("150"), effective_from=date(2026, 1, 1), note="Stara"
        )
    ]
    sent = [
        {
            "rate": 150,
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
            "note": "Nowa",
        }
    ]
    rebuilt = _rebuild_rate_schedule(ContractCandidateRate, existing, sent, actor_id=1)
    assert rebuilt[0].note == "Nowa"


@pytest.mark.asyncio
async def test_placeholder_draft_does_not_inherit_the_revenue_rate():
    """S3: zaślepka z przychodem stawała się źródłem okresu i przychodu."""
    contract = Contract(
        id=31,
        rate_candidate=Decimal("80"),
        rate_client=Decimal("100"),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=168,
        rate_candidate_currency="PLN",
        rate_client_currency="PLN",
    )
    shell = ClientOrder(
        id=45,
        client_id=7,
        contract_id=contract.id,
        title="(bez numeru)",
        status=ClientOrderStatus.draft,
        rate_candidate=None,
        rate_client=None,
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [shell]))
    )

    assert await _inherit_rates_into_unpriced_order_drafts(db, contract) == 1
    assert shell.rate_candidate == Decimal("80")
    assert shell.rate_client is None


def test_export_knows_void_and_ready_for_signature():
    assert _CONTRACT_STATUS_LABELS["void"] == "Anulowany"
    assert _CONTRACT_STATUS_LABELS["ready_for_signature"] == "Do podpisu"


def test_activate_does_not_announce_a_signature_in_teams():
    """N6: aktywacja nie jest podpisem (ta sama reguła co PATCH)."""
    source = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "contracts.py"
    ).read_text(encoding="utf-8")
    assert "notify_contract_signed_by_id" not in source


# ── Testy z bazą ────────────────────────────────────────────────────────────


async def _seed(
    *,
    status: ContractStatus = ContractStatus.active,
    start_date: date | None = date(2025, 1, 1),
    end_date: date | None = None,
    rate_candidate: Decimal = Decimal("150"),
    rate_client: Decimal = Decimal("200"),
    billing_hours: int = 168,
    contract_type: ContractType = ContractType.uop,
) -> dict[str, int]:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Audit D {unique}")
        candidate = Candidate(name="Audit", lastname=f"D-{unique}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=status,
            contract_type=contract_type,
            start_date=start_date,
            end_date=end_date,
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=billing_hours,
            rate_candidate=rate_candidate,
            rate_client=rate_client,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return {
            "contract_id": contract.id,
            "client_id": client.id,
            "candidate_id": candidate.id,
        }


async def _contract(contract_id: int) -> Contract:
    async with AsyncSessionLocal() as db:
        return await db.get(Contract, contract_id)


async def test_patch_switching_hourly_to_monthly_converts_the_rates(
    app_client: AsyncClient, app_auth_headers: dict
):
    """W1: 150/200 zł/h → ryczałt = 25 200 / 33 600 zł/mc, nie „150 zł/mc”."""
    ids = await _seed()
    resp = await app_client.patch(
        f"/api/contracts/{ids['contract_id']}",
        json={
            "rate_unit": "monthly",
            "rate_candidate": 150,
            "rate_client": 200,
            "billing_hours_per_month": 168,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    contract = await _contract(ids["contract_id"])
    assert contract.rate_unit == RateUnit.monthly
    assert Decimal(contract.rate_candidate) == Decimal("25200")
    assert Decimal(contract.rate_client) == Decimal("33600")


async def test_rate_change_amendment_switching_unit_converts_the_rates(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed(billing_hours=160)
    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": business_today().isoformat(),
            "new_rate_unit": "monthly",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    contract = await _contract(ids["contract_id"])
    assert contract.rate_unit == RateUnit.monthly
    assert Decimal(contract.rate_candidate) == Decimal("24000")
    assert Decimal(contract.rate_client) == Decimal("32000")


async def test_rate_change_amendment_without_start_date_is_not_a_500(
    app_client: AsyncClient, app_auth_headers: dict
):
    """N1: krok bazowy bez daty = IntegrityError."""
    ids = await _seed(status=ContractStatus.draft, start_date=None)
    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": business_today().isoformat(),
            "new_rate_candidate": 170,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text


async def test_benchmark_with_a_fractional_hourly_rate_is_not_a_500(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed(rate_client=Decimal("125.19375"))
    resp = await app_client.get(
        f"/api/contracts/{ids['contract_id']}/benchmark", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_rate_monthly"] == pytest.approx(21032.55)


async def test_void_with_a_live_order_is_refused(
    app_client: AsyncClient, app_auth_headers: dict
):
    """S4: anulowanie nie domykało zamówień — alerty leciały dalej."""
    ids = await _seed()
    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrder(
                client_id=ids["client_id"],
                contract_id=ids["contract_id"],
                title="PO-VOID-1",
                status=ClientOrderStatus.active,
                start_date=business_today() - timedelta(days=10),
            )
        )
        await db.commit()

    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/void",
        json={"reason": "pomyłka"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["reason"] == "void_has_live_orders"
    assert (await _contract(ids["contract_id"])).status == ContractStatus.active


async def test_bulk_extend_keeps_month_end_skips_void_and_logs_only_extended(
    app_client: AsyncClient, app_auth_headers: dict
):
    extendable = await _seed(end_date=date(2026, 6, 30))
    voided = await _seed(status=ContractStatus.void, end_date=date(2026, 6, 30))

    resp = await app_client.post(
        "/api/contracts/bulk-extend",
        params=[
            ("ids", extendable["contract_id"]),
            ("ids", voided["contract_id"]),
            ("months", 3),
        ],
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extended"] == 1
    assert body["skipped_void"] == [voided["contract_id"]]
    assert (await _contract(extendable["contract_id"])).end_date == date(2026, 9, 30)
    voided_after = await _contract(voided["contract_id"])
    assert voided_after.status == ContractStatus.void
    assert voided_after.end_date == date(2026, 6, 30)

    async with AsyncSessionLocal() as db:
        logged = set(
            (
                await db.scalars(
                    select(Activity.entity_id).where(
                        Activity.entity_type == "contract",
                        Activity.action == "bulk_extended_3m",
                        Activity.entity_id.in_(
                            [extendable["contract_id"], voided["contract_id"]]
                        ),
                    )
                )
            ).all()
        )
    assert logged == {extendable["contract_id"]}
