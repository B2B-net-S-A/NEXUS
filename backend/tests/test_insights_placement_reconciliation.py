"""Uzgodnienie placementów: raport ma TŁUMACZYĆ rozjazd, nie go usuwać.

Cała wartość tego endpointu siedzi w wierszach, które są w jednej rodzinie
atrybucji i nie ma ich w drugiej. Test zasila obie rodziny tak, żeby powstały
wszystkie trzy kubełki, i sprawdza, że raport je rozróżnia.

Rok fixture'ów (2036) jest CELOWO nieużywany przez inne pliki: baza testowa
jest wspólna dla przebiegu i nie jest czyszczona, więc rok zajęty przez sąsiada
wraca jako „regresja" w kodzie, którego nikt nie ruszał.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.recruitment_priority import PriorityOriginKind
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole

T0 = datetime(2036, 6, 1, 9, 0, tzinfo=timezone.utc)


async def _seed_placement(db, *, kpi_eligible: bool, tag: str):
    """Jedna para (kandydat, oferta) doprowadzona do `hired`.

    ``kpi_eligible=False`` to jedyna dźwignia, jakiej potrzebuję: widok
    ``analytics_first_milestones`` nie ma ŻADNYCH filtrów, więc złapie ten
    placement zawsze, a ``VERIFIER_ANCHORED_CTE`` wymaga
    ``kpi_eligible IS TRUE`` — czyli ta sama para wypada z drugiej rodziny.
    Dokładnie ten mechanizm produkuje rozjazd na produkcji.
    """
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    mover = User(
        email=f"recon-{u}@example.com",
        password_hash=hash_password("x"),
        name=f"Mover {u}",
        role=UserRole.recruiter,
        is_active=True,
    )
    client = Client(name=f"Recon Client {u}")
    db.add_all([mover, client])
    await db.flush()

    job = Job(title=f"Recon Job {u}", client_id=client.id)
    cand = Candidate(name="Rekon", lastname=f"CIL-{u}")
    db.add_all([job, cand])
    await db.flush()

    db.add_all(
        [
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_at=T0 + timedelta(days=1),
                moved_by=mover.id,
                verification_status=VerificationStatus.active,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=T0 + timedelta(days=4),
                moved_by=mover.id,
            ),
        ]
    )
    db.add(
        RecruitmentProcess(
            candidate_id=cand.id,
            job_id=job.id,
            client_id=client.id,
            attempt_no=1,
            status=ProcessStatus.open,
            origin_kind=PriorityOriginKind.assigned,
            opened_at=T0,
            kpi_eligible=kpi_eligible,
            credit_user_id=mover.id,
        )
    )
    await db.commit()
    return {"candidate_id": cand.id, "job_id": job.id, "mover_id": mover.id}


async def _report(app_client, headers) -> dict:
    r = await app_client.get(
        "/api/insights/reconciliation/placements",
        params={
            "period": "custom",
            "date_from": "2036-06-01",
            "date_to": "2036-06-30",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_report_separates_the_three_buckets(app_client, app_auth_headers):
    """Placement w obu rodzinach i placement tylko w widoku — rozróżnione.

    To jest cały sens tego endpointu. Gdyby raport pokazywał wyłącznie część
    wspólną (INNER JOIN), nie odpowiadałby na jedyne pytanie, które ludzie
    zadają: KTÓRYCH placementów brakuje po drugiej stronie.
    """
    async with AsyncSessionLocal() as db:
        both = await _seed_placement(db, kpi_eligible=True, tag="both")
        only_view = await _seed_placement(db, kpi_eligible=False, tag="viewonly")

    body = await _report(app_client, app_auth_headers)
    by_pair = {(i["candidate_id"], i["job_id"]): i for i in body["items"]}

    row_both = by_pair[(both["candidate_id"], both["job_id"])]
    assert row_both["in_first_hired"] is True
    assert row_both["in_verifier_anchored"] is True

    row_view = by_pair[(only_view["candidate_id"], only_view["job_id"])]
    assert row_view["in_first_hired"] is True
    assert row_view["in_verifier_anchored"] is False, (
        "kpi_eligible=False musi wypadać z rodziny verifier-anchored — "
        "jeśli nie wypada, raport nie pokazuje rozjazdu, tylko go ukrywa"
    )


@pytest.mark.asyncio
async def test_totals_add_up_to_the_row_list(app_client, app_auth_headers):
    """Nagłówek musi zgadzać się z sumą własnych wierszy.

    To jest dokładnie ten defekt, który raport ma tłumaczyć u innych:
    `/api/reports/recruitment` podaje 317 w nagłówku i 332 w wierszach tej
    samej odpowiedzi. Narzędzie do uzgadniania nie może mieć tej wady samo.
    """
    async with AsyncSessionLocal() as db:
        await _seed_placement(db, kpi_eligible=True, tag="sum-a")
        await _seed_placement(db, kpi_eligible=False, tag="sum-b")

    body = await _report(app_client, app_auth_headers)
    t = body["totals"]

    assert t["first_hired"] == t["in_both"] + t["only_first_hired"]
    assert t["verifier_anchored"] == t["in_both"] + t["only_verifier_anchored"]
    assert (
        len(body["items"])
        == t["in_both"] + t["only_first_hired"] + t["only_verifier_anchored"]
    )


@pytest.mark.asyncio
async def test_definition_codes_are_the_shared_constants(app_client, app_auth_headers):
    """Kody muszą być TYMI SAMYMI stringami co na ekranach liczących.

    Własny wariant (`..._by_mover`) dałby maszynowo „inna reguła" tam, gdzie
    reguła jest identyczna — czyli odwrotność tego, do czego to pole służy.
    """
    from app.services.metric_definitions import (
        FIRST_HIRED_PER_CANDIDATE_JOB,
        VERIFIER_ANCHORED_MILESTONES,
    )

    body = await _report(app_client, app_auth_headers)
    assert body["definitions"]["first_hired"] == FIRST_HIRED_PER_CANDIDATE_JOB
    assert body["definitions"]["verifier_anchored"] == VERIFIER_ANCHORED_MILESTONES


@pytest.mark.asyncio
async def test_rejects_a_broken_period_instead_of_guessing(
    app_client, app_auth_headers
):
    r = await app_client.get(
        "/api/insights/reconciliation/placements",
        params={"period": "custom"},  # custom bez dat
        headers=app_auth_headers,
    )
    assert r.status_code == 422
