"""Runda 9 audytu (26.09.2026) — reguły ruchu w pipeline.

* R9-N11-3 — weto hiring managera liczone z KOLUMNY docelowej: etapy
  u klienta rozpoznane po nazwie („Preparation Meeting”, kod `interview`)
  nie omijają weta.
* R9-N11-5 — usunięcie z rekrutacji nie zdejmuje weta (rekruter → 409).
* R9-N11-6 — wymóg DL i stawki przy „CV wysłane” dotyczy wysłania, nie
  cofnięcia karty z „Rozmowy u klienta”.
* R9-N11-7 — `/bulk-move` zostawia te same ślady co `/move`.
* R9-N11-8 — `_resolve_stage_def` po kodzie etapu pomija etap-odznakę QC.

Behawioralne na Postgresie (CI).
"""

from __future__ import annotations

from datetime import timedelta

import app.models  # noqa: F401
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from tests.test_manager_rejection_gate import (
    NOW,
    _place_in_target,
    _seed_vetoed_candidate,
)
from tests.test_pipeline_membership_gate import (
    BULK_MOVE,
    MOVE,
    _seed_candidate,
    _seed_job,
    _seed_recruiter,
    _seed_stage,
)


async def _add_stage_def(job_id: int, name: str, legacy: str, category: str) -> int:
    from app.models.job import Job
    from app.models.pipeline_template import PipelineStageDef, StageCategoryEnum

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        sd = PipelineStageDef(
            template_id=job.pipeline_template_id,
            name=name,
            order=50,
            category=StageCategoryEnum(category),
            legacy_enum_value=legacy,
            is_terminal=False,
        )
        db.add(sd)
        await db.commit()
        return sd.id


async def test_veto_follows_the_target_column_not_the_stage_code(
    app_client: AsyncClient, app_auth_headers: dict
):
    """„Preparation Meeting” ma kod `interview`, a leży w kolumnie „Rozmowa
    u klienta” — ruch na nią to postawienie osoby przed klientem."""
    world = await _seed_vetoed_candidate()
    await _place_in_target(world)
    prep_id = await _add_stage_def(
        world["target_job_id"], "Preparation Meeting", "interview", "external"
    )

    resp = await app_client.post(
        MOVE,
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["target_job_id"],
            "stage_def_id": prep_id,
        },
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ELIGIBILITY_WARNING"
    assert detail["reason_code"] == "rejected_by_hiring_manager"


async def test_removing_the_vetoing_recruitment_needs_admin_or_hor(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Wiersze odrzucenia po rozmowie z HM to źródło weta — rekruter nie
    zdejmie go usunięciem osoby z rekrutacji; admin (korekta danych) może."""
    world = await _seed_vetoed_candidate()
    rec_headers, _uid = await _seed_recruiter(app_client)
    url = (
        f"/api/candidates/{world['candidate_id']}/recruitments/{world['source_job_id']}"
    )

    refused = await app_client.delete(url, headers=rec_headers)
    assert refused.status_code == 409, refused.text
    assert "weto" in refused.json()["detail"]

    ok = await app_client.delete(url, headers=app_auth_headers)
    assert ok.status_code == 200, ok.text


async def test_removal_respects_the_12h_claim(app_client: AsyncClient):
    """Osoba zarezerwowana przez innego rekrutera w „Nowych” — usunięcie jej
    z rekrutacji to też ruch, więc 423 jak przy `/move`."""
    from app.models.recruitment_process import RecruitmentProcess

    holder_headers, holder_id = await _seed_recruiter(app_client)
    other_headers, _ = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=holder_id)
    cand = await _seed_candidate()
    await _seed_stage(cand, job_id, "new")
    # Pierwszy ruch rekrutera zakłada proces; blokadę ustawiamy wprost.
    moved = await app_client.post(
        MOVE,
        headers=holder_headers,
        json={"candidate_id": cand, "job_id": job_id, "stage": "screening"},
    )
    assert moved.status_code == 200, moved.text
    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.candidate_id == cand,
                RecruitmentProcess.job_id == job_id,
            )
            .order_by(RecruitmentProcess.id.desc())
            .limit(1)
        )
        process.claimed_by_user_id = holder_id
        process.claimed_until = NOW + timedelta(days=365)
        await db.commit()

    refused = await app_client.delete(
        f"/api/candidates/{cand}/recruitments/{job_id}", headers=other_headers
    )
    assert refused.status_code == 423, refused.text


async def test_moving_back_to_cv_sent_needs_no_dl_or_rate(
    app_client: AsyncClient,
):
    """Karta cofnięta z „Rozmowy u klienta” na „CV wysłane” — osoba już jest
    u klienta; wymóg DL i stawki dotyczy wysłania."""
    rec_headers, rec_id = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=rec_id)
    cand = await _seed_candidate()
    await _seed_stage(cand, job_id, "client_interview")

    back = await app_client.post(
        MOVE,
        headers=rec_headers,
        json={"candidate_id": cand, "job_id": job_id, "stage": "cv_sent"},
    )
    assert back.status_code == 200, back.text

    # Wysłanie z „Screeningu” nadal należy do DL (403 dla rekrutera).
    other = await _seed_candidate()
    await _seed_stage(other, job_id, "screening")
    forward = await app_client.post(
        MOVE,
        headers=rec_headers,
        json={"candidate_id": other, "job_id": job_id, "stage": "cv_sent"},
    )
    assert forward.status_code == 403, forward.text


async def test_bulk_move_leaves_the_same_trail_as_move(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.activity import Activity
    from app.models.user_activity import UserActivity

    job_id, _ = await _seed_job(owner_id=None)
    cands = [await _seed_candidate(), await _seed_candidate()]
    for cand in cands:
        await _seed_stage(cand, job_id, "new")

    resp = await app_client.post(
        BULK_MOVE,
        headers=app_auth_headers,
        json={"candidate_ids": cands, "job_id": job_id, "stage": "screening"},
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        activities = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "pipeline",
                    Activity.action == "stage_changed",
                    Activity.details["job_id"].as_integer() == job_id,
                )
            )
        ).all()
        assert sorted(a.details["candidate_id"] for a in activities) == sorted(cands)
        assert all(a.details["stage"] == "screening" for a in activities)
        user_rows = (
            await db.scalars(
                select(UserActivity).where(
                    UserActivity.entity_type == "pipeline",
                    UserActivity.details["job_id"].as_integer() == job_id,
                )
            )
        ).all()
        assert len(user_rows) == 2


async def test_bulk_move_adds_nobody_past_the_entry_columns(
    app_client: AsyncClient, app_auth_headers: dict
):
    """R9-N11-4: osoba spoza rekrutacji nie wchodzi paczką na „Rozmowę”."""
    job_id, _ = await _seed_job(owner_id=None)
    cand = await _seed_candidate()

    resp = await app_client.post(
        BULK_MOVE,
        headers=app_auth_headers,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "client_interview"},
    )
    assert resp.status_code == 422, resp.text

    single = await app_client.post(
        MOVE,
        headers=app_auth_headers,
        json={"candidate_id": cand, "job_id": job_id, "stage": "client_interview"},
    )
    assert single.status_code == 422, single.text
    entry = await app_client.post(
        MOVE,
        headers=app_auth_headers,
        json={"candidate_id": cand, "job_id": job_id, "stage": "new"},
    )
    assert entry.status_code == 200, entry.text


async def test_legacy_code_resolves_to_the_first_non_badge_stage() -> None:
    """R9-N11-8: kod `interview` ma w szablonie i „QC CV”, i zwykłą rozmowę —
    ruch po samym kodzie trafia na zwykły etap, nie na odznakę QC."""
    import uuid

    from app.api.pipeline import _resolve_stage_def
    from app.models.job import Job
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )
    from app.models.recruitment_pipeline import PipelineStage

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(name=f"R9-{tag}")
        db.add(tpl)
        await db.flush()
        qc = PipelineStageDef(
            template_id=tpl.id,
            name="QC CV",
            order=1,
            category=StageCategoryEnum.internal,
            legacy_enum_value="interview",
        )
        talk = PipelineStageDef(
            template_id=tpl.id,
            name="Rozmowa techniczna",
            order=2,
            category=StageCategoryEnum.internal,
            legacy_enum_value="interview",
        )
        db.add_all([qc, talk])
        await db.flush()
        job = Job(title=f"R9 {tag}", pipeline_template_id=tpl.id)
        resolved = await _resolve_stage_def(
            db, job, legacy_stage=PipelineStage.interview
        )
        assert resolved is not None and resolved.id == talk.id
        await db.rollback()
