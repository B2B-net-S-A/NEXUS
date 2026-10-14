"""Odrzucenie „Nie akceptuje trybu pracy” zapisuje tryb pracy na profilu (14.10.2026).

Do tej pory rekruter wybierał „Inne” i pisał „zdalnie” w notatce, a notatka
zostawała wyłącznie w wierszu etapu — profil i wyszukiwanie jej nie widziały.
Teraz ruch z powodem ``work_mode_mismatch`` niesie liczbę dni w biurze, które
kandydat akceptuje, i zapisuje ją na profilu (z rekrutacją jako źródłem),
chyba że rekruter odznaczy „Zapisz na profilu”.

Uses in-process fixtures (real postgres in CI).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services.candidate_notes_facts import WORK_MODE_ORIGIN_KEY
from app.services.rejection_reason_labels import WORK_MODE_MISMATCH

MOVE = "/api/pipeline/move"


async def _seed(*, category: str = "rejected", profile: dict | None = None):
    """Kandydat w „Screeningu” rekrutacji z szablonem, który ma powód trybu pracy.

    Zwraca (candidate_id, job_id, work_mode_reason_id, other_reason_id).
    """
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(name=f"WM-Tpl-{uuid.uuid4().hex[:6]}")
        db.add(tpl)
        await db.flush()
        work_mode = RejectionReason(
            template_id=tpl.id,
            name=WORK_MODE_MISMATCH,
            category=TerminalType(category),
        )
        other = RejectionReason(
            template_id=tpl.id,
            name=f"WM-Other-{uuid.uuid4().hex[:4]}",
            category=TerminalType(category),
        )
        client = Client(name=f"WM-Client-{uuid.uuid4().hex[:6]}")
        db.add_all([work_mode, other, client])
        await db.flush()
        job = Job(
            title=f"WM-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=tpl.id,
        )
        candidate = Candidate(
            name="Tryb",
            lastname=f"Pracy-{uuid.uuid4().hex[:6]}",
            email=f"wm-{uuid.uuid4().hex[:8]}@example.com",
            **(profile or {}),
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.screening,
            )
        )
        await db.commit()
        return candidate.id, job.id, work_mode.id, other.id


async def _profile(candidate_id: int):
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


def _move(candidate_id, job_id, reason_id, *, stage="rejected", **extra):
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "stage": stage,
        "rejection_reason_id": reason_id,
        "send_rejection_email": False,
        **extra,
    }


async def test_rejection_writes_remote_only_with_origin_and_audit(
    app_client: AsyncClient, app_auth_headers
):
    from app.models.activity import Activity

    cand, job, reason, _ = await _seed(
        profile={
            "preferences": {"remote_modes": ["remote", "hybrid"]},
            "max_onsite_days_per_week": 3,
            "accepts_more_office_days": True,
        }
    )
    r = await app_client.post(
        MOVE,
        json=_move(cand, job, reason, work_mode_max_onsite_days=0),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text

    c = await _profile(cand)
    assert c.preferences["remote_modes"] == ["remote"]
    assert c.max_onsite_days_per_week == 0
    # Odmowa biura w rozmowie kasuje dawną zgodę „można dzwonić z większą
    # liczbą dni” — inaczej bramka dalej wpuszczałaby osobę do biura.
    assert c.accepts_more_office_days is None
    origin = c.preferences[WORK_MODE_ORIGIN_KEY]
    assert origin["source"] == "rejection"
    assert origin["job_id"] == job
    assert origin["stage_id"] == r.json()["id"]
    assert origin["job_title"].startswith("WM-Job-")

    async with AsyncSessionLocal() as db:
        audit = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == cand,
                    Activity.action == "candidate_work_mode_changed",
                )
            )
        ).all()
    assert len(audit) == 1
    details = audit[0].details
    assert details["source"] == "rejection" and details["job_id"] == job
    assert details["before"] == {"modes": ["remote", "hybrid"], "max_onsite_days": 3}
    assert details["after"] == {"modes": ["remote"], "max_onsite_days": 0}


async def test_withdrawal_with_one_office_day_writes_hybrid(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed(category="withdrawn")
    r = await app_client.post(
        MOVE,
        json=_move(cand, job, reason, stage="withdrawn", work_mode_max_onsite_days=1),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    c = await _profile(cand)
    assert c.preferences["remote_modes"] == ["remote", "hybrid"]
    assert c.max_onsite_days_per_week == 1


async def test_unticked_save_to_profile_leaves_profile_alone(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed(
        profile={"preferences": {"remote_modes": ["remote", "hybrid"]}}
    )
    r = await app_client.post(
        MOVE,
        json=_move(
            cand,
            job,
            reason,
            work_mode_max_onsite_days=0,
            work_mode_save_to_profile=False,
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    c = await _profile(cand)
    assert c.preferences == {"remote_modes": ["remote", "hybrid"]}
    assert c.max_onsite_days_per_week is None


async def test_work_mode_reason_without_days_is_refused(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE, json=_move(cand, job, reason), headers=app_auth_headers
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Podaj, ile dni w biurze kandydat akceptuje."
    c = await _profile(cand)
    assert c.max_onsite_days_per_week is None


async def test_days_with_another_reason_are_refused(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, _, other = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(cand, job, other, work_mode_max_onsite_days=0),
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert "Nie akceptuje trybu pracy" in r.json()["detail"]


async def test_manual_profile_change_drops_the_rejection_origin(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(cand, job, reason, work_mode_max_onsite_days=0),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text

    # Zapis bez zmiany trybu pracy (np. lata doświadczenia) zostawia źródło.
    # Miasto ma własną trasę — PATCH kandydata go odrzuca (422).
    r = await app_client.patch(
        f"/api/candidates/{cand}",
        json={"years_it_experience": 6},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert WORK_MODE_ORIGIN_KEY in (await _profile(cand)).preferences

    r = await app_client.patch(
        f"/api/candidates/{cand}",
        json={"max_onsite_days_per_week": 2},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert WORK_MODE_ORIGIN_KEY not in (await _profile(cand)).preferences
