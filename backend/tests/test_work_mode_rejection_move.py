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

import pytest
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


# ── Karta dojazdu, wariant D (27.11.2026) ────────────────────────────────────


async def _audit(candidate_id: int, action: str):
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        return (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == action,
                )
            )
        ).all()


@pytest.mark.parametrize(
    "extra",
    [
        {"work_mode_issue": "distance"},
        {"residence_city": "Kraków"},
        {"commute_office_cities": ["Kraków"]},
        {"occasional_commute": True},
        {"relocation_willing": False},
        {"relocation_willing": True, "relocation_targets": ["Wrocław"]},
        {"accepts_more_office_days": True},
    ],
)
async def test_commute_fields_with_another_reason_are_refused(
    app_client: AsyncClient, app_auth_headers, extra
):
    cand, job, _, other = await _seed()
    r = await app_client.post(
        MOVE, json=_move(cand, job, other, **extra), headers=app_auth_headers
    )
    assert r.status_code == 422, r.text
    assert "Lokalizacja lub tryb pracy" in r.json()["detail"]


async def test_relocation_targets_without_consent_are_refused(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(
            cand,
            job,
            reason,
            work_mode_issue="distance",
            relocation_targets=["Wrocław"],
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_office_days_issue_still_needs_days(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(cand, job, reason, work_mode_issue="office_days"),
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Podaj, ile dni w biurze kandydat akceptuje."


async def test_distance_card_writes_city_and_commute_but_not_work_mode(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed(
        profile={
            "preferences": {"remote_modes": ["remote", "hybrid"], "industries": ["x"]},
            "max_onsite_days_per_week": 3,
        }
    )
    r = await app_client.post(
        MOVE,
        json=_move(
            cand,
            job,
            reason,
            work_mode_issue="distance",
            residence_city="Kraków",
            commute_office_cities=["Kraków", "Katowice"],
            occasional_commute=True,
            relocation_willing=True,
            relocation_targets=["Wrocław"],
            notes="oddzwonić",
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == (
        "Za daleko do biura · mieszka: Kraków · dojedzie do: Kraków, Katowice"
        " · inne miasto: raz w miesiącu · przeprowadzka: tak (Wrocław)"
        " — oddzwonić"
    )

    c = await _profile(cand)
    # Bez dni w biurze tryb pracy zostaje — to nie była odmowa biura.
    assert c.preferences["remote_modes"] == ["remote", "hybrid"]
    assert c.max_onsite_days_per_week == 3
    assert WORK_MODE_ORIGIN_KEY not in c.preferences
    assert await _audit(cand, "candidate_work_mode_changed") == []

    assert (c.city, c.country) == ("Kraków", "PL")
    assert c.cv_extracted_data["_manual_override_city"] is True
    (location,) = await _audit(cand, "candidate_location_changed")
    assert location.details["source"] == "rejection"
    assert location.details["job_id"] == job
    assert location.details["stage_id"] == r.json()["id"]

    assert c.preferences["industries"] == ["x"]
    assert c.preferences["office_cities"] == ["Kraków", "Katowice"]
    assert c.preferences["occasional_commute"] is True
    assert c.preferences["relocation"] == {"willing": True, "targets": ["Wrocław"]}
    source = c.preferences["commute_source"]
    assert source["source"] == "rejection" and source["job_id"] == job
    assert source["job_title"].startswith("WM-Job-") and source["at"]
    (commute,) = await _audit(cand, "candidate_commute_changed")
    assert commute.details["source"] == "rejection"
    assert commute.details["stage_id"] == r.json()["id"]
    assert commute.details["changed"]["office_cities"] == {
        "before": None,
        "after": ["Kraków", "Katowice"],
    }

    # Profil oddaje nowe klucze, a zapis innej preferencji ich nie kasuje.
    r = await app_client.patch(
        f"/api/candidates/{cand}",
        json={"preferences": {"industries": ["bank"]}},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    r = await app_client.get(f"/api/candidates/{cand}", headers=app_auth_headers)
    assert r.status_code == 200, r.text
    prefs = r.json()["preferences"]
    assert prefs["industries"] == ["bank"]
    for key in ("office_cities", "occasional_commute", "relocation", "commute_source"):
        assert key in prefs, key


async def test_distance_with_days_writes_work_mode_too(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(
            cand, job, reason, work_mode_issue="distance", work_mode_max_onsite_days=2
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "Za daleko do biura · do 2 dni w biurze"
    c = await _profile(cand)
    assert c.max_onsite_days_per_week == 2
    assert c.preferences["remote_modes"] == ["remote", "hybrid"]


async def test_same_city_leaves_location_alone(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed(profile={"city": "Kraków", "country": "PL"})
    r = await app_client.post(
        MOVE,
        json=_move(
            cand, job, reason, work_mode_issue="distance", residence_city="kraków"
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert (await _profile(cand)).city == "Kraków"
    assert await _audit(cand, "candidate_location_changed") == []
    assert await _audit(cand, "candidate_commute_changed") == []


async def test_unticked_save_to_profile_writes_no_commute(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed(profile={"city": "Łódź"})
    r = await app_client.post(
        MOVE,
        json=_move(
            cand,
            job,
            reason,
            work_mode_issue="distance",
            residence_city="Kraków",
            commute_office_cities=["Kraków"],
            relocation_willing=False,
            work_mode_save_to_profile=False,
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    # Opis i tak niesie odpowiedź — zostaje w historii procesu.
    assert r.json()["notes"].startswith("Za daleko do biura · mieszka: Kraków")
    c = await _profile(cand)
    assert c.city == "Łódź"
    assert not c.preferences
    assert await _audit(cand, "candidate_location_changed") == []
    assert await _audit(cand, "candidate_commute_changed") == []


async def test_office_days_card_saves_consent_for_more_days(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(
            cand,
            job,
            reason,
            work_mode_issue="office_days",
            work_mode_max_onsite_days=2,
            accepts_more_office_days=True,
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == (
        "Chce mniej dni w biurze · do 2 dni · więcej przy wyjątkowym projekcie: tak"
    )
    c = await _profile(cand)
    assert c.max_onsite_days_per_week == 2
    assert c.accepts_more_office_days is True
