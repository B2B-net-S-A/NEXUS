"""Regression tests for independent revenue/cost currencies on contracts."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select, text

from app.api.contracts import (
    _CONTRACT_FINANCE_SCALARS,
    _CONTRACT_FINANCE_WRITE_FIELDS,
)
from app.api.client_orders import _compute_monthly_margin
from app.models.client_order import ClientOrder
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.contract_rates import effective_rate_fields


def _rate_contract(*, client_currency: str, candidate_currency: str) -> Contract:
    contract = Contract(
        rate_client=Decimal("100"),
        rate_candidate=Decimal("300"),
        rate_client_currency=client_currency,
        rate_candidate_currency=candidate_currency,
        currency=client_currency,
        rate_unit=RateUnit.monthly,
        billing_hours_per_month=160,
    )
    contract.__dict__.update(
        candidate_rate_schedule=[],
        client_rate_schedule=[],
        framework_rate_schedule=[],
    )
    return contract


def test_mixed_currency_never_produces_nominal_margin():
    contract = _rate_contract(client_currency="EUR", candidate_currency="PLN")

    fields = effective_rate_fields(contract, date(2026, 8, 27))

    assert fields["rate_client_currency"] == "EUR"
    assert fields["rate_candidate_currency"] == "PLN"
    assert fields["currency"] == "EUR"  # legacy alias = client side
    assert fields["margin"] is None
    assert fields["monthly_margin"] is None
    assert contract.calculate_margin() is None
    assert contract.monthly_margin is None


def test_same_currency_keeps_legacy_margin_semantics():
    contract = _rate_contract(client_currency="EUR", candidate_currency="EUR")

    fields = effective_rate_fields(contract, date(2026, 8, 27))

    assert fields["margin"] == Decimal("-200")
    assert fields["monthly_margin"] == Decimal("-200")
    assert contract.calculate_margin() == Decimal("-200")


def test_order_margin_never_subtracts_unlike_currency_amounts_nominally():
    contract = _rate_contract(client_currency="EUR", candidate_currency="PLN")
    order = ClientOrder(rate_client=None, currency="EUR")

    assert _compute_monthly_margin(order, contract, date(2026, 8, 27)) is None


def test_legacy_only_model_row_falls_back_for_both_sides():
    contract = Contract(currency="gbp")
    contract.rate_client_currency = None
    contract.rate_candidate_currency = None

    assert contract.resolved_rate_client_currency == "GBP"
    assert contract.resolved_rate_candidate_currency == "GBP"


def test_new_currency_fields_are_finance_guarded_and_redacted():
    for field in ("rate_client_currency", "rate_candidate_currency"):
        assert field in _CONTRACT_FINANCE_WRITE_FIELDS
        assert field in _CONTRACT_FINANCE_SCALARS


def test_migration_and_entrypoint_keep_rollout_safe_backfill_and_legacy_sync():
    backend = Path(__file__).resolve().parents[1]
    migration = (
        backend / "alembic/versions/0248_contract_rate_currencies.py"
    ).read_text()
    entrypoint = (backend / "entrypoint.sh").read_text()

    assert 'down_revision = "0247_job_favorite_candidate"' in migration
    for source in (migration, entrypoint):
        assert "ADD COLUMN IF NOT EXISTS" in source
        assert "rate_client_currency VARCHAR(3) NULL" in source
        assert "rate_candidate_currency VARCHAR(3) NULL" in source
        assert "NULLIF(UPPER(BTRIM(currency)), '')" in source
        assert "rate_client_currency IS NULL" in source
        assert "rate_candidate_currency IS NULL" in source
        assert "sync_contract_rate_currencies_from_legacy" in source
        assert "trg_contract_rate_currencies_legacy_sync" in source
        assert (
            "margin, currency, rate_client_currency, rate_candidate_currency" in source
        )
        assert "NEW.currency IS DISTINCT FROM OLD.currency" in source
        assert (
            "NEW.rate_client_currency IS NOT DISTINCT FROM OLD.rate_client_currency"
            in source
        )
        assert (
            "NEW.rate_candidate_currency IS NOT DISTINCT FROM "
            "OLD.rate_candidate_currency" in source
        )


async def _seed_parties_and_source() -> tuple[int, int, int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        candidate = Candidate(
            name="Currency",
            lastname=f"Candidate-{suffix}",
            email=f"currency-{suffix}@example.com",
        )
        source_client = Client(name=f"CurrencySource-{suffix}")
        target_client = Client(name=f"CurrencyTarget-{suffix}")
        db.add_all([candidate, source_client, target_client])
        await db.flush()
        source = Contract(
            candidate_id=candidate.id,
            client_id=source_client.id,
            status=ContractStatus.draft,
            start_date=date.today() - timedelta(days=30),
            rate_client=Decimal("100"),
            rate_candidate=Decimal("80"),
            currency="PLN",
        )
        db.add(source)
        await db.commit()
        return candidate.id, source_client.id, target_client.id, source.id


async def test_create_patch_and_auto_order_currency_compatibility(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    (
        candidate_id,
        _,
        target_client_id,
        source_contract_id,
    ) = await _seed_parties_and_source()
    monkeypatch.setattr("app.api.contracts.is_cost_order_client", lambda _id: False)
    payload = {
        "candidate_id": candidate_id,
        "client_id": target_client_id,
        "source_contract_id": source_contract_id,
        "start_date": date.today().isoformat(),
        "rate_client": 100,
        "rate_candidate": 300,
        "rate_client_currency": "eur",
        "rate_candidate_currency": "pln",
    }

    created = await app_client.post(
        "/api/contracts", json=payload, headers=app_auth_headers
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["currency"] == "EUR"
    assert body["rate_client_currency"] == "EUR"
    assert body["rate_candidate_currency"] == "PLN"
    assert body["margin"] is None
    assert body["draft_order_id"] is not None

    listed = await app_client.get(
        f"/api/contracts?candidate_id={candidate_id}&page_size=100",
        headers=app_auth_headers,
    )
    assert listed.status_code == 200, listed.text
    listed_row = next(row for row in listed.json()["items"] if row["id"] == body["id"])
    assert listed_row["currency"] == "EUR"
    assert listed_row["rate_client_currency"] == "EUR"
    assert listed_row["rate_candidate_currency"] == "PLN"
    assert listed_row["margin"] is None

    grouped = await app_client.get(
        f"/api/contracts?candidate_id={candidate_id}&group_by_candidate=true&page_size=100",
        headers=app_auth_headers,
    )
    assert grouped.status_code == 200, grouped.text
    grouped_row = next(
        row for row in grouped.json()["items"] if row["candidate_id"] == candidate_id
    )
    member = next(
        item for item in grouped_row["group_members"] if item["id"] == body["id"]
    )
    assert member["currency"] == "EUR"
    assert member["rate_client_currency"] == "EUR"
    assert member["rate_candidate_currency"] == "PLN"
    assert member["margin"] is None

    async with AsyncSessionLocal() as db:
        order = await db.scalar(
            select(ClientOrder).where(ClientOrder.id == body["draft_order_id"])
        )
        assert order is not None
        assert order.currency == "EUR"

    patched = await app_client.patch(
        f"/api/contracts/{body['id']}",
        json={"rate_candidate_currency": "gbp"},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["currency"] == "EUR"
    assert patched.json()["rate_client_currency"] == "EUR"
    assert patched.json()["rate_candidate_currency"] == "GBP"

    round_trip = await app_client.patch(
        f"/api/contracts/{body['id']}",
        json={"currency": "EUR", "rate_candidate_currency": "PLN"},
        headers=app_auth_headers,
    )
    assert round_trip.status_code == 200, round_trip.text
    assert round_trip.json()["currency"] == "EUR"
    assert round_trip.json()["rate_client_currency"] == "EUR"
    assert round_trip.json()["rate_candidate_currency"] == "PLN"

    cached_legacy_form = await app_client.patch(
        f"/api/contracts/{body['id']}",
        json={"currency": "EUR", "project_name": "cached legacy edit"},
        headers=app_auth_headers,
    )
    assert cached_legacy_form.status_code == 200, cached_legacy_form.text
    assert cached_legacy_form.json()["rate_client_currency"] == "EUR"
    assert cached_legacy_form.json()["rate_candidate_currency"] == "PLN"

    conflict = await app_client.patch(
        f"/api/contracts/{body['id']}",
        json={"currency": "EUR", "rate_client_currency": "GBP"},
        headers=app_auth_headers,
    )
    assert conflict.status_code == 422, conflict.text
    assert conflict.json()["detail"]["code"] == "contract_currency_conflict"

    legacy_patch = await app_client.patch(
        f"/api/contracts/{body['id']}",
        json={"currency": "usd"},
        headers=app_auth_headers,
    )
    assert legacy_patch.status_code == 200, legacy_patch.text
    assert legacy_patch.json()["currency"] == "USD"
    assert legacy_patch.json()["rate_client_currency"] == "USD"
    assert legacy_patch.json()["rate_candidate_currency"] == "USD"

    # Rolling-deploy guard: an older process knows only `currency`, so the DB
    # trigger itself (not the new API helper) must mirror that write.
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE contracts SET currency = 'CAD' WHERE id = :contract_id"),
            {"contract_id": body["id"]},
        )
        await db.commit()
        mirrored = (
            await db.execute(
                text(
                    "SELECT currency, rate_client_currency, "
                    "rate_candidate_currency FROM contracts WHERE id = :contract_id"
                ),
                {"contract_id": body["id"]},
            )
        ).one()
        assert tuple(mirrored) == ("CAD", "CAD", "CAD")

        # A new process writing explicit mixed sides must not be re-coupled by
        # that compatibility trigger.
        await db.execute(
            text(
                "UPDATE contracts SET currency = 'EUR', "
                "rate_client_currency = 'EUR', rate_candidate_currency = 'PLN' "
                "WHERE id = :contract_id"
            ),
            {"contract_id": body["id"]},
        )
        await db.commit()
        mixed = (
            await db.execute(
                text(
                    "SELECT currency, rate_client_currency, "
                    "rate_candidate_currency, margin "
                    "FROM contracts WHERE id = :contract_id"
                ),
                {"contract_id": body["id"]},
            )
        ).one()
        assert tuple(mixed) == ("EUR", "EUR", "PLN", None)

        # An old ORM process recalculates nominal ``margin`` on every model
        # update. Even when the business edit touches only a non-financial
        # field, the compatibility trigger must discard that false mixed-FX
        # margin during a rolling deployment.
        await db.execute(
            text(
                "UPDATE contracts SET handover_notes = 'legacy writer', "
                "margin = -200 WHERE id = :contract_id"
            ),
            {"contract_id": body["id"]},
        )
        await db.commit()
        legacy_recomputed_margin = await db.scalar(
            text("SELECT margin FROM contracts WHERE id = :contract_id"),
            {"contract_id": body["id"]},
        )
        assert legacy_recomputed_margin is None


async def test_legacy_create_sets_both_and_conflicting_payload_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, _, target_client_id, _ = await _seed_parties_and_source()
    base = {
        "candidate_id": candidate_id,
        "client_id": target_client_id,
        "start_date": date.today().isoformat(),
        "rate_client": 100,
        "rate_candidate": 80,
    }
    legacy = await app_client.post(
        "/api/contracts",
        json={**base, "currency": "eur"},
        headers=app_auth_headers,
    )
    assert legacy.status_code == 201, legacy.text
    assert legacy.json()["currency"] == "EUR"
    assert legacy.json()["rate_client_currency"] == "EUR"
    assert legacy.json()["rate_candidate_currency"] == "EUR"

    other_candidate, _, other_target, _ = await _seed_parties_and_source()
    conflict = await app_client.post(
        "/api/contracts",
        json={
            **base,
            "candidate_id": other_candidate,
            "client_id": other_target,
            "currency": "EUR",
            "rate_client_currency": "PLN",
            "rate_candidate_currency": "EUR",
        },
        headers=app_auth_headers,
    )
    assert conflict.status_code == 422, conflict.text
    assert conflict.json()["detail"]["code"] == "contract_currency_conflict"


async def test_candidate_only_eur_still_exposes_detail_nbp_snapshot(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.fx_rate import FxRate

    candidate_id, _, target_client_id, _ = await _seed_parties_and_source()
    async with AsyncSessionLocal() as db:
        today = business_today()
        row = await db.scalar(
            select(FxRate).where(
                FxRate.currency == "EUR", FxRate.effective_date == today
            )
        )
        if row is None:
            db.add(
                FxRate(
                    currency="EUR",
                    effective_date=today,
                    rate_to_pln=Decimal("4.250000"),
                    source="NBP",
                )
            )
        else:
            row.rate_to_pln = Decimal("4.250000")
            row.source = "NBP"
        await db.commit()

    created = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": candidate_id,
            "client_id": target_client_id,
            "start_date": date.today().isoformat(),
            "rate_client_currency": "PLN",
            "rate_candidate_currency": "EUR",
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text

    detail = await app_client.get(
        f"/api/contracts/{created.json()['id']}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["eur_pln_rate"]["rate"] == 4.25
