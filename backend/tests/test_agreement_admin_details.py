"""„Szczegóły administracyjne” umowy z Generatora (0524, decyzje Artura 26.10.2026).

Rekruter i DL to odbiorcy premii z reguły automatu (tylko do odczytu),
wpisuje się replacement i FTE; prowadzący dostaje dzwonek, gdy umowę jego
osoby wygenerował ktoś inny. Część bez bazy biegnie lokalnie; część z bazą
(``app_client``) sprawdza CI — baza wspólna, asercje na własnych wierszach.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract import Contract
from app.schemas.b2b_contract_generator import (
    B2BMandateRenderRequest,
    B2BRenderRequest,
)
from app.services.b2b_contract_generator import admin_details

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0524_agreement_admin_details.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0524", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ── Schemat bazy: migracja i lustro w entrypoincie ───────────────────────────


def test_migration_chains_after_the_single_head() -> None:
    module = _migration()
    assert module.revision == "0524_agreement_admin_details"
    assert module.down_revision == "0522_candidate_client_forms"


def test_entrypoint_mirrors_columns_checks_and_notification_type() -> None:
    module = _migration()
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for statement in module.COLUMNS:
        assert f'"{statement}"' in entrypoint.replace('"\n    "', ""), statement
    for name in (
        "ck_b2b_generated_contracts_fte",
        "ck_b2b_generated_contracts_replacement",
        "ck_contracts_fte",
        "ck_contracts_replacement",
    ):
        assert f"ADD CONSTRAINT {name}" in entrypoint, name
        assert f"ADD CONSTRAINT {name}" in MIGRATION.read_text(encoding="utf-8")
    assert module.ADD_NOTIFICATION_TYPE in entrypoint
    # CHECK-i po kolumnach: _CONSTRAINT_STATEMENTS biegnie po liście ALTER-ów.
    assert entrypoint.index("ck_contracts_fte") > entrypoint.index(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS fte NUMERIC(3, 2)"
    )


def test_models_match_the_ddl() -> None:
    for table in (Contract.__table__, B2BGeneratedContract.__table__):
        fte = table.columns["fte"]
        assert (fte.type.precision, fte.type.scale) == (3, 2)
        assert fte.nullable and table.columns["is_replacement"].nullable
        [fk] = table.columns["replaced_contract_id"].foreign_keys
        assert fk.column.table.name == "contracts" and fk.ondelete == "SET NULL"


# ── Schemat żądania: FTE i stare payloady ────────────────────────────────────


@pytest.mark.parametrize("raw", ["1", "0.75", "0.5", "0.25", 0.5, "0.50", "1.00"])
def test_fte_accepts_the_four_values(raw) -> None:
    req = B2BRenderRequest(fte=raw)
    assert req.fte in admin_details.FTE_VALUES
    assert req.fte == Decimal(str(raw))


@pytest.mark.parametrize("raw", ["0.6", "0", "2", "-1"])
def test_fte_refuses_anything_else(raw) -> None:
    with pytest.raises(ValidationError):
        B2BRenderRequest(fte=raw)


def test_payloads_from_before_0524_still_parse() -> None:
    """``render_payload`` sprzed kafelka odtwarza się przy ponownym pobraniu DOCX."""
    req = B2BRenderRequest(**{"language": "pl", "partner_name": "Zofia"})
    assert (req.is_replacement, req.replaced_contract_id, req.fte) == (None, None, None)
    dumped = B2BRenderRequest(is_replacement=True, replaced_contract_id=7, fte="0.5")
    again = B2BRenderRequest(**dumped.model_dump(mode="json"))
    assert again.fte == Decimal("0.5") and again.replaced_contract_id == 7


def test_mandate_request_carries_the_same_fields() -> None:
    assert {"is_replacement", "replaced_contract_id", "fte"} <= set(
        B2BMandateRenderRequest.model_fields
    )


# ── Walidacja przy generowaniu ───────────────────────────────────────────────


async def test_linked_agreement_requires_replacement_and_fte() -> None:
    row = B2BGeneratedContract()
    for missing in (
        {"is_replacement": None, "fte": Decimal("1")},
        {"is_replacement": False, "fte": None},
    ):
        with pytest.raises(HTTPException) as err:
            await admin_details.apply_admin_details(
                None,  # type: ignore[arg-type]
                row,
                replaced_contract_id=None,
                candidate_id=1,
                linked=True,
                **missing,
            )
        assert err.value.status_code == 422


async def test_replacement_yes_needs_the_person() -> None:
    with pytest.raises(HTTPException) as err:
        await admin_details.apply_admin_details(
            None,  # type: ignore[arg-type]
            B2BGeneratedContract(),
            is_replacement=True,
            replaced_contract_id=None,
            fte=Decimal("1"),
            candidate_id=1,
            linked=True,
        )
    assert err.value.status_code == 422
    assert "za kogo" in err.value.detail


async def test_replacement_no_clears_the_person_and_manual_agreement_is_free() -> None:
    row = B2BGeneratedContract()
    await admin_details.apply_admin_details(
        None,  # type: ignore[arg-type]
        row,
        is_replacement=False,
        replaced_contract_id=123,
        fte=Decimal("0.5"),
        candidate_id=1,
        linked=True,
    )
    assert (row.is_replacement, row.replaced_contract_id, row.fte) == (
        False,
        None,
        Decimal("0.5"),
    )
    manual = B2BGeneratedContract()
    await admin_details.apply_admin_details(
        None,  # type: ignore[arg-type]
        manual,
        is_replacement=None,
        replaced_contract_id=None,
        fte=None,
        candidate_id=None,
        linked=False,
    )
    assert manual.fte is None and manual.is_replacement is None


# ── Podpis: kopia do kontraktu fill-only ─────────────────────────────────────


def test_signature_copies_admin_details_into_an_empty_contract() -> None:
    contract = Contract(id=10)
    row = B2BGeneratedContract(
        is_replacement=True, replaced_contract_id=497, fte=Decimal("0.5")
    )
    filled = admin_details.copy_admin_details_to_contract(contract, row)
    assert filled == ["fte", "is_replacement", "replaced_contract_id"]
    assert (contract.is_replacement, contract.replaced_contract_id, contract.fte) == (
        True,
        497,
        Decimal("0.5"),
    )


def test_signature_keeps_what_the_contract_already_says() -> None:
    contract = Contract(
        id=10, is_replacement=False, replaced_contract_id=None, fte=Decimal("1")
    )
    row = B2BGeneratedContract(
        is_replacement=True, replaced_contract_id=497, fte=Decimal("0.25")
    )
    assert admin_details.copy_admin_details_to_contract(contract, row) == []
    assert (contract.is_replacement, contract.fte) == (False, Decimal("1"))


def test_signature_never_points_a_contract_at_itself() -> None:
    contract = Contract(id=497)
    row = B2BGeneratedContract(is_replacement=True, replaced_contract_id=497)
    admin_details.copy_admin_details_to_contract(contract, row)
    assert contract.is_replacement is True and contract.replaced_contract_id is None


# ── Zastępstwo z tytułu rekrutacji ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Analityk Biznesowy - zastępstwo za: Zofia Przykładowa", "Zofia Przykładowa"),
        ("UX/UI Designer - zastępstwo za: Jan Testowy", "Jan Testowy"),
        ("Klient: 1 X Scrum Master Replacement for Adam (40001)", "Adam"),
    ],
)
def test_replaced_name_is_read_from_the_title(title: str, name: str) -> None:
    assert admin_details._REPLACEMENT_IN_TITLE.search(title)
    match = admin_details._REPLACED_NAME_IN_TITLE.search(title)
    assert match is not None and match.group(1) == name


@pytest.mark.parametrize(
    "title",
    [
        "DevOps - Market Risk (replacement) (40002)",
        "Data Ops - Platforma - Replacement (40003)",
    ],
)
def test_replacement_without_a_name_gives_no_person(title: str) -> None:
    assert admin_details._REPLACEMENT_IN_TITLE.search(title)
    match = admin_details._REPLACED_NAME_IN_TITLE.search(title)
    # Nawias albo koniec tytułu — nie zgadujemy osoby.
    assert match is None


def test_ordinary_title_is_not_a_replacement() -> None:
    assert not admin_details._REPLACEMENT_IN_TITLE.search(
        "Mobile Developer Android/Kotlin Multiplatform"
    )


# ── Ścieżka z bazą (CI) ──────────────────────────────────────────────────────


async def _seed_world(
    *, verifier_id: int, dl_id: int, title: str | None = None
) -> dict:
    """Klient z dwoma kontraktorami (zakończony i aktywny), kandydat zweryfikowany."""

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import ContractStatus, ContractType
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Admin details {unique}")
        candidate = Candidate(
            name="Bartosz", lastname=f"Nowy{unique}", email=f"nowy-{unique}@example.com"
        )
        gone = Candidate(
            name="Wiktoria",
            lastname=f"Odeszla{unique}",
            email=f"odeszla-{unique}@example.com",
        )
        staying = Candidate(
            name="Marcin",
            lastname=f"Zostaje{unique}",
            email=f"zost-{unique}@example.com",
        )
        db.add_all([client, candidate, gone, staying])
        await db.flush()
        job = Job(
            title=title or f"Analityk - zastępstwo za: Wiktoria Odeszla{unique}",
            status=JobStatus.published,
            client_id=client.id,
            delivery_lead_id=dl_id,
        )
        db.add(job)
        await db.flush()
        ended = Contract(
            candidate_id=gone.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.ended,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 8, 31),
        )
        active = Contract(
            candidate_id=staying.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2025, 1, 1),
        )
        db.add_all([ended, active])
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_by=verifier_id,
                moved_at=datetime.now(timezone.utc) - timedelta(days=3),
            )
        )
        await db.commit()
        return {
            "unique": unique,
            "client_id": client.id,
            "candidate_id": candidate.id,
            "job_id": job.id,
            "ended_id": ended.id,
            "active_id": active.id,
        }


def _render_body(world: dict, **overrides) -> dict:
    seq = 300000 + (uuid.uuid4().int % 500000)
    body = {
        "candidate_id": world["candidate_id"],
        "job_id": world["job_id"],
        "language": "pl",
        "contract_number": f"{seq}/2026",
        "partner_name": f"Bartosz Nowy{world['unique']}",
        "client_name": "Klient testowy",
        "signing_date": "2026-10-27",
        "start_date": "2026-11-02",
        "rate_candidate": 120,
    }
    body.update(overrides)
    return body


@pytest.fixture
async def people(app_client: AsyncClient) -> dict:
    from tests.test_b2b_generator_rate_visibility import _seed_user

    _rec_h, recruiter_id = await _seed_user(app_client, "recruiter")
    _dl_h, dl_id = await _seed_user(app_client, "delivery_lead")
    return {"recruiter_id": recruiter_id, "dl_id": dl_id}


async def test_prefill_names_the_bonus_payees_and_the_replaced_person(
    app_client: AsyncClient, app_auth_headers: dict, people: dict
):
    world = await _seed_world(verifier_id=people["recruiter_id"], dl_id=people["dl_id"])
    resp = await app_client.get(
        "/api/b2b-generator/prefill",
        params={"candidate_id": world["candidate_id"], "job_id": world["job_id"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    admin = resp.json()["admin"]
    assert admin["recruiter"]["user_id"] == people["recruiter_id"]
    assert admin["recruiter"]["source"] == "verifier"
    assert admin["delivery_lead"]["user_id"] == people["dl_id"]
    assert admin["delivery_lead"]["source"] == "job"
    assert admin["replacement_from_title"] is True
    assert admin["replaced"]["contract_id"] == world["ended_id"]


async def test_replacement_options_put_people_who_left_first(
    app_client: AsyncClient, app_auth_headers: dict, people: dict
):
    world = await _seed_world(verifier_id=people["recruiter_id"], dl_id=people["dl_id"])
    resp = await app_client.get(
        "/api/b2b-generator/replacement-options",
        params={
            "client_id": world["client_id"],
            "exclude_candidate_id": world["candidate_id"],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = [item["contract_id"] for item in resp.json()]
    assert ids == [world["ended_id"], world["active_id"]]
    assert "rate_candidate" not in resp.json()[0]

    too_short = await app_client.get(
        "/api/b2b-generator/replacement-options",
        params={"q": "a"},
        headers=app_auth_headers,
    )
    assert too_short.status_code == 422


async def test_linked_render_without_admin_details_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, people: dict
):
    world = await _seed_world(verifier_id=people["recruiter_id"], dl_id=people["dl_id"])
    resp = await app_client.post(
        "/api/b2b-generator/render?format=docx",
        json=_render_body(world),
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "Szczegóły administracyjne" in resp.json()["detail"]


async def test_render_stores_details_owner_and_rings_the_owner(
    app_client: AsyncClient, app_auth_headers: dict, people: dict
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    world = await _seed_world(verifier_id=people["recruiter_id"], dl_id=people["dl_id"])
    resp = await app_client.post(
        "/api/b2b-generator/render?format=docx",
        json=_render_body(
            world,
            is_replacement=True,
            replaced_contract_id=world["ended_id"],
            fte="0.5",
        ),
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    generated_id = int(resp.headers["x-generated-contract-id"])
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert row.is_replacement is True
        assert row.replaced_contract_id == world["ended_id"]
        assert row.fte == Decimal("0.5")
        # Admin wygenerował za rekrutera — przypomnienia i dzwonek idą do niego.
        assert row.recruiter_user_id == people["recruiter_id"]
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == people["recruiter_id"],
                    Notification.notification_type
                    == NotificationType.b2b_agreement_ready,
                    Notification.related_entity_id == generated_id,
                )
            )
        ).all()
    assert len(bells) == 1

    form = await app_client.get(
        f"/api/b2b-generator/generated/{generated_id}/form", headers=app_auth_headers
    )
    assert form.status_code == 200, form.text
    assert form.json()["form"]["fte"] == "0.5"
    assert form.json()["replaced"]["contract_id"] == world["ended_id"]


async def test_replacement_cannot_point_at_the_same_person(
    app_client: AsyncClient, app_auth_headers: dict, people: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import ContractStatus, ContractType

    world = await _seed_world(verifier_id=people["recruiter_id"], dl_id=people["dl_id"])
    async with AsyncSessionLocal() as db:
        own = Contract(
            candidate_id=world["candidate_id"],
            client_id=world["client_id"],
            contract_type=ContractType.b2b,
            status=ContractStatus.ended,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
        )
        db.add(own)
        await db.commit()
        own_id = own.id
    resp = await app_client.post(
        "/api/b2b-generator/render?format=docx",
        json=_render_body(
            world, is_replacement=True, replaced_contract_id=own_id, fte="1"
        ),
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "samej siebie" in resp.json()["detail"]


async def test_failed_owner_bell_still_returns_the_document(
    app_client: AsyncClient, app_auth_headers: dict, people: dict, monkeypatch
):
    """Awaria dzwonka po zapisie wiersza nie może zabrać pliku (500)."""

    async def boom(*_args, **_kwargs):
        raise RuntimeError("dzwonek padł")

    monkeypatch.setattr(admin_details, "notify_pair_owner", boom)
    world = await _seed_world(verifier_id=people["recruiter_id"], dl_id=people["dl_id"])
    resp = await app_client.post(
        "/api/b2b-generator/render?format=docx",
        json=_render_body(world, is_replacement=False, fte="1"),
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-generated-contract-id"]
