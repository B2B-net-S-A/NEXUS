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
from sqlalchemy import delete, select, update

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


# Rekrutacja z pytaniami screeningowymi — wtedy bramka pyta o arkusz.
WITH_QUESTIONS = {
    "screening_questions": [{"id": "q1", "question": "Ile lat komercyjnie z Javą?"}]
}


@pytest.fixture
def gates_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VERIFIED_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "HIRED_SIGNED_VIA_REQUIRED", True)


@pytest.fixture
def minimum_on(gates_on, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VERIFIED_MINIMUM_FIELDS_ENABLED", True)


@pytest.fixture
def dl_skips_on(minimum_on, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DL_SKIPS_FILL_GATES", True)


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
    world = await _seed_world(champion_profile=WITH_QUESTIONS)
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
            screening_answers={
                "answers": [{"question_id": "q1", "response": "3 lata"}]
            },
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
async def test_job_without_questions_needs_the_assessment_not_the_sheet(
    api_client: AsyncClient, gates_on
) -> None:
    """Zgłoszenie 12.10.2026: rekrutacja z Traffita bez Profilu Championa nie ma
    pytań, więc arkusza nie da się zapisać — bramka zatrzymywała tam każdego
    i kazała uzupełnić arkusz. Zapisem rozmowy jest „Dlaczego ten kandydat”."""
    from app.models.recommendation_card import RecommendationCard

    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    verified = world["defs"]["verified"]
    rate = {
        "expected_rate_value": "140",
        "expected_rate_unit": "hourly",
        "expected_rate_currency": "PLN",
    }
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])

        bare = await _post_move(api_client, rec, world, stage_def_id=verified)
        assert bare.status_code == 409, bare.text
        detail = bare.json()["detail"]
        assert detail["code"] == "VERIFIED_REQUIREMENTS_MISSING"
        assert detail["missing"] == ["why_candidate", "candidate_rate"]
        assert "Dlaczego ten kandydat" in detail["message"]
        assert "nie ma pytań screeningowych" in detail["message"]
        assert "arkusz screeningu" not in detail["message"]

        rate_only = await _post_move(
            api_client, rec, world, stage_def_id=verified, **rate
        )
        assert rate_only.status_code == 409, rate_only.text
        assert rate_only.json()["detail"]["missing"] == ["why_candidate"]

        async with AsyncSessionLocal() as db:
            db.add(
                RecommendationCard(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    fields_manual={
                        "recommendation": {
                            "raw": "Pięć lat w raportowaniu podatkowym, zna SQL.",
                            "by": rec_id,
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    },
                )
            )
            await db.commit()
        ok = await _post_move(api_client, rec, world, stage_def_id=verified, **rate)
        assert ok.status_code == 200, ok.text
    finally:
        await _cleanup(world, [rec_id])


@pytest.mark.asyncio
async def test_minimum_for_the_delivery_lead_blocks_until_written(
    api_client: AsyncClient, minimum_on
) -> None:
    """Decyzja Artura 21.10.2026: rekomendacje przychodziły do DL bez
    lokalizacji i trybu pracy. Zaślepka „-” nie liczy się jako wartość."""
    from app.models.recommendation_card import RecommendationCard

    world = await _seed_world(champion_profile=WITH_QUESTIONS)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    verified = world["defs"]["verified"]
    rate = {
        "expected_rate_value": "140",
        "expected_rate_unit": "hourly",
        "expected_rate_currency": "PLN",
    }

    def field(raw: str) -> dict:
        # Data po starcie procesu — pole liczy się do bieżącej próby.
        return {"raw": raw, "by": rec_id, "at": datetime.now(timezone.utc).isoformat()}

    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        await _add_row(
            world,
            def_key="screening",
            stage="screening",
            minutes_ago=1,
            moved_by=rec_id,
            screening_answers={
                "answers": [{"question_id": "q1", "response": "3 lata"}]
            },
        )
        async with AsyncSessionLocal() as db:
            db.add(
                RecommendationCard(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    fields_manual={
                        "location": field("-"),
                        "availability": field("od zaraz"),
                    },
                )
            )
            await db.commit()

        refused = await _post_move(
            api_client, rec, world, stage_def_id=verified, **rate
        )
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["missing"] == ["location", "work_mode", "recommendation"]
        assert detail["card_fields"] == ["location", "work_mode", "recommendation"]
        assert "„Lokalizacja”" in detail["message"]
        assert "„Dlaczego ten kandydat”" in detail["message"]

        async with AsyncSessionLocal() as db:
            card = (
                await db.execute(
                    select(RecommendationCard).where(
                        RecommendationCard.candidate_id == world["candidate_id"],
                        RecommendationCard.job_id == world["job_id"],
                    )
                )
            ).scalar_one()
            card.fields_manual = {
                **card.fields_manual,
                "location": field("Warszawa"),
                "work_mode": field("hybryda, 2 dni w biurze"),
                "recommendation": field("6 lat w Javie w bankowości."),
            }
            await db.commit()
        ok = await _post_move(api_client, rec, world, stage_def_id=verified, **rate)
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

    world = await _seed_world(champion_profile=WITH_QUESTIONS)
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


# ── Delivery Lead przesuwa bez bramek pól (decyzja Artura 22.10.2026) ────────


@pytest.mark.asyncio
async def test_delivery_lead_moves_past_the_fill_gates_and_leaves_a_trace(
    api_client: AsyncClient, dl_skips_on
) -> None:
    """DL sam przeprowadza osobę, którą rekruter pominął: bez arkusza, stawki
    i minimum ruch przechodzi, a braki zostają śladem na karcie Tablicy.
    Rekruter na tej samej parze dalej dostaje 409, a jako prowadzący dostaje
    dzwonek o ruchu DL-a."""

    from app.models.activity import Activity
    from app.models.job import Job
    from app.models.notification import Notification

    world = await _seed_world(champion_profile=WITH_QUESTIONS)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    verified = world["defs"]["verified"]
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, world["job_id"])
            job.recruiter_id = rec_id
            await db.commit()

        refused = await _post_move(api_client, rec, world, stage_def_id=verified)
        assert refused.status_code == 409, refused.text
        missing = refused.json()["detail"]["missing"]
        assert missing[:2] == ["screening_sheet", "candidate_rate"]

        moved = await _post_move(api_client, dl, world, stage_def_id=verified)
        assert moved.status_code == 200, moved.text

        async with AsyncSessionLocal() as db:
            trace = (
                await db.execute(
                    select(Activity).where(
                        Activity.action == rules.REQUIREMENTS_SKIPPED_ACTION,
                        Activity.user_id == dl_id,
                    )
                )
            ).scalar_one()
        assert trace.details["missing"] == missing
        assert trace.details["job_id"] == world["job_id"]
        async with AsyncSessionLocal() as db:
            bell = (
                await db.execute(
                    select(Notification).where(
                        Notification.user_id == rec_id,
                        Notification.related_entity_id == world["candidate_id"],
                    )
                )
            ).scalar_one()
        assert "Zweryfikowany" in bell.title
        assert "arkusz screeningu" in bell.message

        board = await api_client.get(
            f"/api/pipeline/kanban/{world['job_id']}", headers=dl
        )
        assert board.status_code == 200, board.text
        cards = [
            item
            for column in board.json()["columns"]
            for item in column["items"]
            if item["candidate_id"] == world["candidate_id"]
        ]
        assert cards and cards[0]["requirements_skipped"] == missing
        assert cards[0]["requirements_skipped_by_name"]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Activity).where(
                    Activity.action == rules.REQUIREMENTS_SKIPPED_ACTION,
                    Activity.user_id == dl_id,
                )
            )
            await db.execute(delete(Notification).where(Notification.user_id == rec_id))
            await db.execute(
                update(Job).where(Job.id == world["job_id"]).values(recruiter_id=None)
            )
            await db.commit()
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_delivery_lead_jump_past_verified_rings_the_recruiter(
    api_client: AsyncClient, dl_skips_on
) -> None:
    """Audyt 22.10.2026 (F58), decyzja Artura: dzwonek do prowadzącego idzie
    przy każdym przejściu DL-a przez „Zweryfikowany” od lewej — także przy
    przeskoku z Nowych od razu na „QC CV”, nie tylko przy ruchu dokładnie
    na „Zweryfikowany”."""

    from app.models.activity import Activity
    from app.models.job import Job
    from app.models.notification import Notification

    world = await _seed_world(champion_profile=WITH_QUESTIONS)
    rec_id, _rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, world["job_id"])
            job.recruiter_id = rec_id
            await db.commit()

        moved = await _post_move(
            api_client, dl, world, stage_def_id=world["defs"]["qc"]
        )
        assert moved.status_code == 200, moved.text

        async with AsyncSessionLocal() as db:
            bells = (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == rec_id,
                        Notification.related_entity_id == world["candidate_id"],
                    )
                )
            ).all()
        skip_bells = [b for b in bells if "bez:" in (b.message or "")]
        assert len(skip_bells) == 1, [b.title for b in bells]
        assert "QC CV" in skip_bells[0].title
        assert "arkusz screeningu" in skip_bells[0].message
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Activity).where(
                    Activity.action == rules.REQUIREMENTS_SKIPPED_ACTION,
                    Activity.user_id == dl_id,
                )
            )
            await db.execute(delete(Notification).where(Notification.user_id == rec_id))
            await db.execute(
                update(Job).where(Job.id == world["job_id"]).values(recruiter_id=None)
            )
            await db.commit()
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_delivery_lead_switch_off_restores_the_gate(
    api_client: AsyncClient, minimum_on
) -> None:
    world = await _seed_world(champion_profile=WITH_QUESTIONS)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        refused = await _post_move(
            api_client, dl, world, stage_def_id=world["defs"]["verified"]
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "VERIFIED_REQUIREMENTS_MISSING"
    finally:
        await _cleanup(world, [dl_id])


@pytest.mark.asyncio
async def test_delivery_lead_bulk_move_keeps_the_gate(
    api_client: AsyncClient, dl_skips_on
) -> None:
    """Ruch zbiorczy nie zostawia śladu `requirements_skipped`, więc bramka pól
    obowiązuje w nim także Delivery Leada (przegląd 22.10.2026)."""

    world = await _seed_world(champion_profile=WITH_QUESTIONS)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        bulk = await api_client.post(
            "/api/pipeline/bulk-move",
            headers=dl,
            json={
                "candidate_ids": [world["candidate_id"]],
                "job_id": world["job_id"],
                "stage": "interview",
            },
        )
        assert bulk.status_code == 409, bulk.text
        assert bulk.json()["detail"]["code"] == "VERIFIED_REQUIREMENTS_MISSING"
    finally:
        await _cleanup(world, [dl_id])


def test_board_badge_keeps_only_what_is_still_missing() -> None:
    from app.api.pipeline import _still_missing

    keys = ["screening_sheet", "candidate_rate", "location", "work_mode", "debrief"]
    gaps = {
        "screening_done": False,
        "expected_rate_value": None,
        "minimum_missing": ["location", "work_mode"],
    }
    assert _still_missing(keys, gaps) == keys
    filled = {
        "screening_done": True,
        "expected_rate_value": "140.00",
        "minimum_missing": ["work_mode"],
    }
    assert _still_missing(keys, filled) == ["work_mode", "debrief"]
    # Stawka z profilu też gasi brak stawki.
    assert (
        _still_missing(["candidate_rate"], {"candidate_expected_rate_hourly": 120})
        == []
    )


@pytest.mark.asyncio
async def test_skip_bell_names_the_gaps_without_the_409_wording(monkeypatch) -> None:
    """Dzwonek do prowadzącego wymienia braki krótko — bez osieroconego
    cudzysłowu i dopisku z komunikatu 409 (audyt 22.10.2026, F93)."""

    from types import SimpleNamespace

    from app.api.pipeline import _notify_recruiter_of_skip
    from app.services import notification_triggers

    sent: list[dict] = []

    async def fake_emit(_db, **kwargs):
        sent.append(kwargs)

    class _Db:
        async def get(self, *_args):
            return None

    monkeypatch.setattr(notification_triggers, "emit", fake_emit)
    await _notify_recruiter_of_skip(
        _Db(),
        job=SimpleNamespace(id=7, title="Java Developer", recruiter_id=2),
        candidate_id=11,
        mover=SimpleNamespace(id=1, name="Anna Nowak"),
        stage_name="Zweryfikowany",
        missing=["why_candidate", "candidate_rate", "location"],
    )
    assert sent[0]["message"] == (
        "Java Developer · bez: Dlaczego ten kandydat, stawka kandydata, Lokalizacja"
    )


def test_board_badge_sums_every_skip_trace_of_the_current_attempt() -> None:
    """Kolejny ruch DL-a mimo braków (przeskok debriefu) nie chowa braków
    z wejścia na „Zweryfikowany”, a ślad z zamkniętej próby nie wraca na kartę
    po ponownym dodaniu osoby (audyt 22.10.2026, F57)."""

    from app.api.pipeline import _merge_skip_traces

    now = datetime.now(timezone.utc)
    rows = [
        (1, {"missing": ["screening_sheet", "candidate_rate"]}, 10, now),
        (1, {"missing": ["candidate_rate", "debrief"]}, 11, now),
        (2, {"missing": ["debrief"]}, 10, now - timedelta(days=30)),
        (2, {"missing": ["screening_sheet"]}, 12, now),
    ]
    merged = _merge_skip_traces(rows, {2: now - timedelta(days=1)})
    assert merged[1] == (["screening_sheet", "candidate_rate", "debrief"], 11)
    assert merged[2] == (["screening_sheet"], 12)


@pytest.mark.asyncio
async def test_requirements_skipped_reads_every_trace_of_the_pair() -> None:
    from app.api.pipeline import _requirements_skipped
    from app.models.activity import Activity

    world = await _seed_world(champion_profile=WITH_QUESTIONS)
    try:
        async with AsyncSessionLocal() as db:
            rows = []
            for minutes_ago, def_key, stage in (
                (30, "verified", PipelineStage.verified),
                (5, "cv_sent", PipelineStage.cv_sent),
            ):
                row = CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage=stage,
                    stage_def_id=world["defs"][def_key],
                    moved_at=datetime.now(timezone.utc)
                    - timedelta(minutes=minutes_ago),
                )
                db.add(row)
                rows.append(row)
            await db.flush()
            for row, missing in zip(
                rows, (["screening_sheet", "candidate_rate"], ["debrief"])
            ):
                db.add(
                    Activity(
                        entity_type="pipeline",
                        entity_id=row.id,
                        action=rules.REQUIREMENTS_SKIPPED_ACTION,
                        details={"missing": missing},
                    )
                )
            await db.commit()
        async with AsyncSessionLocal() as db:
            found = await _requirements_skipped(
                db, job_id=world["job_id"], candidate_ids=[world["candidate_id"]]
            )
        assert found[world["candidate_id"]][0] == [
            "screening_sheet",
            "candidate_rate",
            "debrief",
        ]
    finally:
        async with AsyncSessionLocal() as db:
            stage_ids = select(CandidateStage.id).where(
                CandidateStage.candidate_id == world["candidate_id"]
            )
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "pipeline",
                    Activity.entity_id.in_(stage_ids),
                )
            )
            await db.commit()
        await _cleanup(world, [])
