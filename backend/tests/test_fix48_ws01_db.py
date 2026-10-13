"""Audyt 48 h (13.10.2026), obszar WS01 — trasy z bazą (CI).

Reguły bez bazy: ``test_fix48_ws01_rules.py``. Dane wyłącznie fikcyjne.

* pkt 5: arkusz z samym sprawdzeniem doświadczenia nie przepuszcza na
  „Zweryfikowany”, a karta Tablicy nie mówi „screening zrobiony”;
* pkt 6: „Pomiń brakujące” bez powodu — 422 w formularzu i w starej trasie
  arkusza; pominięcie zapisane wcześniej nie blokuje ponownego zapisu;
* Nordea: para zamknięta z kolejki Cpro wraca do niej przez akceptację DL,
  `/bulk-move` odmawia jak pojedynczy ruch;
* Tablica: `dl_send_counts` — karta z importu Traffita i karta zamkniętej
  rekrutacji nie liczą się do „Czeka na Ciebie”.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services import pipeline_move_rules as rules
from tests.test_board_tasks import (
    CPRO_RATE,
    _cleanup,
    _login,
    _seed_user,
    _seed_world,
    restore_cpro_sender,
    seed_entry_row,
)
from tests.test_screening_form import URL, _params, _put, _state, _token, _world

WITH_QUESTIONS = {
    "screening_questions": [{"id": "q1", "question": "Ile lat komercyjnie z Javą?"}]
}
EXPERIENCE_ONLY = {
    "answers": [{"question_id": "q1", "response": ""}],
    "experience_checks": [
        {"kind": "domains", "name": "Bankowość", "status": "confirmed", "note": ""}
    ],
    "overall_fit": "fit",
    "notes": "",
}
RATE = {
    "expected_rate_value": "140",
    "expected_rate_unit": "hourly",
    "expected_rate_currency": "PLN",
}


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VERIFIED_GATE_ENABLED", True)


async def _add_row(world: dict, *, def_key: str, stage: str, minutes_ago: int, **extra):
    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=stage,
            stage_def_id=world["defs"][def_key],
            moved_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            **extra,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _move(client: AsyncClient, headers: dict, world: dict, **body):
    return await client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["job_id"],
            **body,
        },
    )


async def _card(client: AsyncClient, headers: dict, world: dict) -> dict:
    res = await client.get(f"/api/pipeline/kanban/{world['job_id']}", headers=headers)
    assert res.status_code == 200, res.text
    return next(
        item
        for col in res.json()["columns"]
        for item in col["items"]
        if item["candidate_id"] == world["candidate_id"]
    )


# ── pkt 5: bramka „Zweryfikowany” liczy odpowiedzi ───────────────────────────


@pytest.mark.asyncio
async def test_experience_check_alone_does_not_pass_the_verified_gate(
    api_client: AsyncClient, gate_on
) -> None:
    world = await _seed_world(champion_profile=WITH_QUESTIONS)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    verified = world["defs"]["verified"]
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        await _add_row(
            world,
            def_key="screening",
            stage="screening",
            minutes_ago=2,
            moved_by=rec_id,
            screening_answers=EXPERIENCE_ONLY,
        )
        refused = await _move(api_client, rec, world, stage_def_id=verified, **RATE)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["missing"] == ["screening_sheet"]
        # Karta mówi to samo co bramka.
        assert (await _card(api_client, rec, world))["screening_done"] is False

        await _add_row(
            world,
            def_key="screening",
            stage="screening",
            minutes_ago=1,
            moved_by=rec_id,
            screening_answers={
                **EXPERIENCE_ONLY,
                "answers": [{"question_id": "q1", "response": "3 lata"}],
            },
        )
        assert (await _card(api_client, rec, world))["screening_done"] is True
        ok = await _move(api_client, rec, world, stage_def_id=verified, **RATE)
        assert ok.status_code == 200, ok.text
    finally:
        await _cleanup(world, [rec_id])


# ── pkt 6: „Pomiń brakujące” tylko z powodem ─────────────────────────────────

ALL_SKIPPED = {
    "answers": [
        {"question_id": "q1", "response": "", "skipped": True},
        {"question_id": "q2", "response": "", "skipped": True},
    ],
    "experience_checks": [],
    "overall_fit": "fit",
    "internal_note": "Pominięte pytania.",
}


async def test_form_refuses_a_skip_without_a_reason(app_client: AsyncClient):
    w = await _world()
    res = await app_client.put(
        URL,
        headers=w["rec_h"],
        json={
            **_params(w),
            "expected_version": 0,
            "state_token": await _token(app_client, w),
            "sheet": ALL_SKIPPED,
        },
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "SCREENING_FORM_INVALID"
    assert "Pomiń brakujące" in res.json()["detail"]["message"]
    assert (await _state(app_client, w))["sheet"] is None


async def test_form_accepts_a_skip_of_a_person_employed_with_us(
    app_client: AsyncClient,
):
    w = await _world()
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client_id = (await db.get(Job, w["job_id"])).client_id
        other = Job(
            title=f"FormEarlier-{tag}", status=JobStatus.published, client_id=client_id
        )
        db.add(other)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=w["cand_id"],
                job_id=other.id,
                stage=PipelineStage.hired,
                moved_at=datetime.now(timezone.utc) - timedelta(days=30),
            )
        )
        await db.commit()
        other_id = other.id
    try:
        saved = await _put(app_client, w, expected=0, sheet=ALL_SKIPPED)
        assert saved["saved_version"] is not None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.job_id == other_id)
            )
            await db.execute(delete(Job).where(Job.id == other_id))
            await db.commit()


async def test_an_earlier_skip_does_not_block_the_next_save(app_client: AsyncClient):
    """Pominięcie zapisane wcześniej (powód mógł zniknąć) — formularz przywraca
    zaznaczenie i zapis przechodzi."""
    w = await _world(
        sheet={
            "answers": [
                {"question_id": "q1", "response": "", "skipped": True},
                {"question_id": "q2", "response": "Chce większy projekt."},
            ],
            "overall_fit": "fit",
            "internal_note": "Pominięte pytania.",
        }
    )
    saved = await _put(
        app_client,
        w,
        expected=0,
        sheet={
            **ALL_SKIPPED,
            "answers": [
                {"question_id": "q1", "response": "", "skipped": True},
                {"question_id": "q2", "response": "Chce większego projektu."},
            ],
        },
    )
    assert saved["saved_version"] is not None


async def test_old_sheet_route_refuses_a_skip_without_a_reason(
    app_client: AsyncClient,
):
    w = await _world()
    res = await app_client.post(
        f"/api/pipeline/stages/{w['stage_id']}/screening",
        headers=w["rec_h"],
        json=ALL_SKIPPED,
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "SCREENING_FORM_INVALID"


# ── Nordea: kolejka Cpro ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pair_closed_in_the_cpro_queue_returns_through_the_dl(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    defs = world["defs"]
    try:
        async with restore_cpro_sender():
            for key in ("verified", "qc"):
                moved = await _move(api_client, hor, world, stage_def_id=defs[key])
                assert moved.status_code == 200, moved.text
            accepted = await _move(
                api_client, dl, world, stage_def_id=defs["cpro"], **CPRO_RATE
            )
            assert accepted.status_code == 200, accepted.text
            closed = await _move(
                api_client,
                hor,
                world,
                stage="rejected",
                rejection_reason="Kandydat przyjął inną ofertę",
            )
            assert closed.status_code == 200, closed.text

            # Rekruter nie wkłada zamkniętej pary z powrotem do kolejki.
            back = await _move(api_client, rec, world, stage_def_id=defs["cpro"])
            assert back.status_code == 403, back.text
            assert back.json()["detail"]["message"] == rules.CPRO_ACCEPT_DENIED_MESSAGE
            # Ani wprost na „Wysłane do Cpro”.
            sent = await _move(api_client, rec, world, stage_def_id=defs["cv_sent"])
            assert sent.status_code == 403, sent.text
            # Delivery Lead akceptuje ponownie — stawka zapisana wcześniej wystarcza.
            again = await _move(api_client, dl, world, stage_def_id=defs["cpro"])
            assert again.status_code == 200, again.text
    finally:
        await _cleanup(world, [hor_id, rec_id, dl_id])


@pytest.mark.asyncio
async def test_bulk_move_at_nordea_refuses_like_a_single_move(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    defs = world["defs"]

    async def bulk(headers: dict, stage: str, **extra):
        return await api_client.post(
            "/api/pipeline/bulk-move",
            headers=headers,
            json={
                "candidate_ids": [world["candidate_id"]],
                "job_id": world["job_id"],
                "stage": stage,
                **extra,
            },
        )

    try:
        async with restore_cpro_sender():
            for key in ("verified", "qc"):
                moved = await _move(api_client, hor, world, stage_def_id=defs[key])
                assert moved.status_code == 200, moved.text
            # Kod „new” w tym szablonie ma tylko etap „Wysłać do Cpro”.
            for stage in ("new", "cv_sent"):
                refused = await bulk(rec, stage)
                assert refused.status_code == 403, refused.text
                assert (
                    refused.json()["detail"]["message"]
                    == rules.CPRO_ACCEPT_DENIED_MESSAGE
                )
            no_rate = await bulk(dl, "new")
            assert no_rate.status_code == 422, no_rate.text
            assert no_rate.json()["detail"] == rules.CPRO_RATE_REQUIRED_MESSAGE
            ok = await bulk(dl, "new", **CPRO_RATE)
            assert ok.status_code == 200, ok.text
    finally:
        await _cleanup(world, [hor_id, rec_id, dl_id])


# ── Tablica: „Czeka na Ciebie” jak pas „Do wysłania” ─────────────────────────


@pytest.mark.asyncio
async def test_board_card_says_whether_it_counts_for_the_dl_queue(
    api_client: AsyncClient,
) -> None:
    """Wymaga pola `dl_send_counts` w `CandidateStageResponse`
    (`app/schemas/pipeline.py`) — bez niego odpowiedź tablicy je zdejmuje."""
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    try:
        row_id = await _add_row(
            world,
            def_key="qc",
            stage="interview",
            minutes_ago=5,
            external_source="traffit",
        )
        assert (await _card(api_client, hor, world))["dl_send_counts"] is False
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CandidateStage)
                .where(CandidateStage.id == row_id)
                .values(external_source="manual")
            )
            await db.commit()
        assert (await _card(api_client, hor, world))["dl_send_counts"] is True
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Job)
                .where(Job.id == world["job_id"])
                .values(status=JobStatus.closed)
            )
            await db.commit()
        assert (await _card(api_client, hor, world))["dl_send_counts"] is False
    finally:
        await _cleanup(world, [hor_id])
