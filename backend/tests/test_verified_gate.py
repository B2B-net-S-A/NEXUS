"""Bramka „Zweryfikowany” (D1) i powód ręcznego zatrudnienia (D2) — 04.10.2026.

D1: wejście na „Zweryfikowany” z Nowych/Screeningu wymaga arkusza screeningu
(albo odpowiedzi w karcie rekomendacji) i stawki kandydata — serwer liczy to
tą samą regułą co okno „Przesuń dalej” (`move_requirements.load_pair_facts`).
Zwrot DL z „QC CV” do poprawy nie jest bramkowany.

D2: ręczny ruch na „Zatrudniony” mówi, jak podpisano umowę.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services import pipeline_move_rules as rules
from tests.test_board_tasks import (
    _cleanup,
    _login,
    _seed_user,
    _seed_world,
    seed_entry_row,
)


@pytest_asyncio.fixture
async def api_client():
    from httpx import ASGITransport

    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def gates_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VERIFIED_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "HIRED_SIGNED_VIA_REQUIRED", True)


async def _post_move(client: AsyncClient, headers: dict, world: dict, **body):
    return await client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["job_id"],
            **body,
        },
    )


async def _add_row(world: dict, *, def_key: str, stage: str, minutes_ago: int, **extra):
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=stage,
                stage_def_id=world["defs"][def_key],
                moved_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
                **extra,
            )
        )
        await db.commit()


# ── Jednostkowe: powód zatrudnienia ──────────────────────────────────────────


def test_hired_reason_is_required_only_for_hired(gates_on) -> None:
    rules.assert_hired_signed_via(PipelineStage.verified, None, None)
    rules.assert_hired_signed_via(PipelineStage.hired, "uop", None)
    with pytest.raises(HTTPException) as missing:
        rules.assert_hired_signed_via(PipelineStage.hired, None, None)
    assert missing.value.status_code == 422
    assert missing.value.detail["code"] == "HIRED_SIGNED_VIA_REQUIRED"
    with pytest.raises(HTTPException) as other:
        rules.assert_hired_signed_via(PipelineStage.hired, "other", "  ")
    assert other.value.status_code == 422
    rules.assert_hired_signed_via(
        PipelineStage.hired, "other", "Umowa na PDF od klienta"
    )


def test_hired_reason_switch_off_lets_the_move_through(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HIRED_SIGNED_VIA_REQUIRED", False)
    rules.assert_hired_signed_via(PipelineStage.hired, None, None)


# ── Integracyjne: bramka „Zweryfikowany” ────────────────────────────────────


@pytest.mark.asyncio
async def test_verified_needs_screening_sheet_and_candidate_rate(
    api_client: AsyncClient, gates_on
) -> None:
    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    verified = world["defs"]["verified"]
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])

        bare = await _post_move(api_client, rec, world, stage_def_id=verified)
        assert bare.status_code == 409, bare.text
        detail = bare.json()["detail"]
        assert detail["code"] == "VERIFIED_REQUIREMENTS_MISSING"
        assert detail["missing"] == ["screening_sheet", "candidate_rate"]
        assert "arkusz screeningu" in detail["message"]

        # Stawka w samym ruchu wystarcza — brakuje już tylko arkusza.
        rate_only = await _post_move(
            api_client,
            rec,
            world,
            stage_def_id=verified,
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        assert rate_only.status_code == 409, rate_only.text
        assert rate_only.json()["detail"]["missing"] == ["screening_sheet"]

        await _add_row(
            world,
            def_key="screening",
            stage="screening",
            minutes_ago=1,
            moved_by=rec_id,
            screening_answers={"answers": [{"id": "q1", "answer": "3 lata"}]},
        )
        ok = await _post_move(
            api_client,
            rec,
            world,
            stage_def_id=verified,
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        assert ok.status_code == 200, ok.text
    finally:
        await _cleanup(world, [rec_id])


@pytest.mark.asyncio
async def test_skipping_over_verified_is_gated_too(
    api_client: AsyncClient, gates_on
) -> None:
    """Audyt 05.10.2026: skok z Nowych ponad „Zweryfikowany” (API, Jarvis)
    omijał arkusz i stawkę — a para bez wiersza `verified` traciła kredyt
    weryfikacji w statystykach."""

    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        skip = await _post_move(
            api_client, rec, world, stage_def_id=world["defs"]["qc"]
        )
        assert skip.status_code == 409, skip.text
        assert skip.json()["detail"]["code"] == "VERIFIED_REQUIREMENTS_MISSING"
    finally:
        await _cleanup(world, [rec_id])


def test_every_column_from_verified_on_is_gated() -> None:
    assert rules.VERIFIED_GATE_TARGETS == {
        "verified",
        "cv_qc",
        "cv_sent",
        "client_interview",
        "contract",
        "hired",
    }


@pytest.mark.asyncio
async def test_return_from_qc_to_verified_is_not_gated(
    api_client: AsyncClient, gates_on
) -> None:
    """„Wróć do poprawy” z „QC CV” nie może się zatrzymać na arkuszu —
    osoba już raz przeszła przez „Zweryfikowany”."""

    world = await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    try:
        await _add_row(world, def_key="qc", stage="interview", minutes_ago=5)
        back = await _post_move(
            api_client, dl, world, stage_def_id=world["defs"]["verified"]
        )
        assert back.status_code == 200, back.text
    finally:
        await _cleanup(world, [dl_id])


@pytest.mark.asyncio
async def test_from_closed_the_gate_counts_the_column_before_closing(
    api_client: AsyncClient, gates_on
) -> None:
    """Odrzucony z „Nowych” nie wraca od razu na „Zweryfikowany” bez arkusza."""

    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            rejected = await db.scalar(
                select(PipelineStageDef.id).where(
                    PipelineStageDef.template_id == world["template_id"],
                    PipelineStageDef.is_terminal.is_(True),
                )
            )
            db.add(
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage="rejected",
                    stage_def_id=rejected,
                    moved_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                )
            )
            await db.commit()
        resp = await _post_move(
            api_client,
            rec,
            world,
            stage_def_id=world["defs"]["verified"],
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["missing"] == ["screening_sheet"]
    finally:
        await _cleanup(world, [rec_id])


@pytest.mark.asyncio
async def test_manual_hire_without_signed_via_is_refused(
    api_client: AsyncClient, gates_on
) -> None:
    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        resp = await _post_move(api_client, rec, world, stage="hired")
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "HIRED_SIGNED_VIA_REQUIRED"
        # „Inna umowa” bez opisu też zostaje zatrzymana. (Ruchu z pełnym
        # powodem tu nie robimy — założyłby kontrakt i zamówienie.)
        other = await _post_move(
            api_client, rec, world, stage="hired", hired_signed_via="other"
        )
        assert other.status_code == 422, other.text
        assert "opisz" in other.json()["detail"]["message"]
    finally:
        await _cleanup(world, [rec_id])
