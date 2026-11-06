"""„Ostatnie odrzucenie” na liście kandydatów (06.11.2026).

`GET /api/candidates`:

* `rejection_key` (`r:<etykieta>`, `t:<kategoria Traffita>`, `none`),
  `rejection_by` (`client` / `us` / `candidate`), `rejection_within_months`
  (3 / 12) i `rejection_exclude` — filtr po ostatnim odrzuceniu osoby;
* `include_last_rejection` — kolumna (`last_rejection` w wierszu);
* `include_rejection_facets` — pasek „Ostatnie odrzucenie w tym wyniku”.

„Ostatnie odrzucenie” = najnowszy wiersz odrzucenia / rezygnacji, który jest
nadal stanem swojej pary (osoba, rekrutacja). Logika:
`app/services/candidate_last_rejection.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from httpx import AsyncClient

from app.models.recruitment_pipeline import PipelineStage
from app.services import candidate_last_rejection as lr


# ── Testy bez bazy ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reason", "note", "key"),
    [
        ("Brak doświadczenia", None, "r:Brak doświadczenia"),
        # Oba „Inne (…)” to jedno „Inne” — etykieta, nie nazwa w bazie.
        ("Inne (rejected)", "Po CV", "r:Inne"),
        ("Inne (withdrawn)", None, "r:Inne"),
        ("work_mode_mismatch", None, "r:Nie akceptuje trybu pracy (biuro / hybryda)"),
        # Zaślepka importu Traffita to brak powodu — liczy się kategoria.
        (
            "legacy_unknown",
            "Rezygnacja przez Kandydata",
            "t:Rezygnacja przez Kandydata",
        ),
        (None, " Po CV ", "t:Po CV"),
        (None, None, "none"),
        ("legacy_unknown", "  ", "none"),
    ],
)
def test_key_of(reason: Optional[str], note: Optional[str], key: str) -> None:
    assert lr.key_of(reason, note) == key


def test_labels() -> None:
    assert lr.label_of("r:Brak doświadczenia") == "Brak doświadczenia"
    assert lr.label_of("t:Po CV") == "Traffit · Po CV"
    assert lr.label_of("none") == "Bez powodu"


@pytest.mark.parametrize(
    ("ended_by", "stage", "reason", "note", "who"),
    [
        ("recruiter", PipelineStage.rejected, None, None, "us"),
        ("delivery_lead", PipelineStage.rejected, None, None, "us"),
        ("client", PipelineStage.rejected, None, None, "client"),
        ("candidate", PipelineStage.withdrawn, "lost_interest", None, "candidate"),
        # Bez `ended_by` — reguła Insights.
        (None, PipelineStage.withdrawn, "legacy_unknown", None, "candidate"),
        (
            None,
            PipelineStage.rejected,
            None,
            "Odrzucenie oferty przez Kandydata",
            "candidate",
        ),
        (None, PipelineStage.rejected, None, "Rezygnacja przez Klienta", "client"),
        (None, PipelineStage.rejected, None, "Po CV", "us"),
        (None, "rejected", None, None, "us"),
    ],
)
def test_who_of(ended_by, stage, reason, note, who) -> None:
    assert (
        lr.who_of(
            ended_by=ended_by, stage=stage, reason_name=reason, rejection_note=note
        )
        == who
    )


def test_filter_inactive_without_parts() -> None:
    assert not lr.RejectionFilter().active
    assert not lr.RejectionFilter(exclude=True).active
    assert lr.RejectionFilter(who=("client",)).active
    assert lr.RejectionFilter(within_months=3).active


def test_latest_rejection_ignores_a_pair_reopened_later() -> None:
    """Odrzucenie liczy się tylko, gdy w parze nie ma nowszego wiersza."""
    from sqlalchemy.dialects import postgresql

    sql = str(
        lr.latest_rejection_subquery().compile(dialect=postgresql.dialect())
    ).lower()
    assert "not (exists" in sql
    assert "distinct on (candidate_stages.candidate_id)" in sql


# ── Testy z bazą ─────────────────────────────────────────────────────────────


async def _seed_candidate(cohort: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=cohort,
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"rej-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"RejClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Rej-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, cli.id


async def _reason_id(name: str, category: str = "rejected") -> int:
    """Powód ze słownika; brak w bazie testowej → dopisany do pierwszego szablonu."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )

    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(RejectionReason.id).where(RejectionReason.name == name).limit(1)
        )
        if found:
            return found
        template_id = await db.scalar(select(PipelineTemplate.id).limit(1))
        assert template_id, "baza testowa bez szablonu procesu"
        row = RejectionReason(
            template_id=template_id, name=name, category=TerminalType(category)
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage: str,
    *,
    moved_at: datetime,
    reason: Optional[str] = None,
    ended_by: Optional[str] = None,
    rejection_note: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    reason_id = None
    if reason:
        reason_id = await _reason_id(
            reason, "withdrawn" if stage == "withdrawn" else "rejected"
        )
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage(stage),
                moved_at=moved_at,
                rejection_reason_id=reason_id,
                ended_by=ended_by,
                rejection_note=rejection_note,
                notes=notes,
            )
        )
        await db.commit()


async def _cleanup(candidate_ids: list[int], jobs: list[tuple[int, int]]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == cid)
            )
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        for job_id, client_id in jobs:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.job_id == job_id)
            )
            await db.execute(delete(Job).where(Job.id == job_id))
            await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


async def _list(
    app_client: AsyncClient,
    headers: dict,
    cohort: str,
    params: Optional[list[tuple[str, str]]] = None,
) -> dict:
    r = await app_client.get(
        "/api/candidates",
        params=[("q", cohort), ("page_size", "100"), *(params or [])],
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _ids(payload: dict) -> set[int]:
    return {it["id"] for it in payload["items"]}


@pytest.mark.asyncio
async def test_filter_reads_the_last_rejection_of_each_person(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"Rej{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    job1, job2 = await _seed_job(), await _seed_job()
    # A: starsze odrzucenie „Brak doświadczenia”, nowsze „Za wysokie…”.
    a = await _seed_candidate(cohort)
    # B: odrzucony „Brak doświadczenia”, potem przywrócony w tej samej parze.
    b = await _seed_candidate(cohort)
    # C: odrzucony „Brak doświadczenia”, później proces w toku gdzie indziej.
    c = await _seed_candidate(cohort)
    # D: nigdy nieodrzucony.
    d = await _seed_candidate(cohort)
    try:
        await _seed_stage(
            a,
            job1[0],
            "rejected",
            moved_at=now - timedelta(days=40),
            reason="Brak doświadczenia",
            ended_by="recruiter",
        )
        await _seed_stage(
            a,
            job2[0],
            "rejected",
            moved_at=now - timedelta(days=5),
            reason="Za wysokie oczekiwania finansowe",
            ended_by="client",
        )
        await _seed_stage(
            b,
            job1[0],
            "rejected",
            moved_at=now - timedelta(days=10),
            reason="Brak doświadczenia",
            ended_by="recruiter",
        )
        await _seed_stage(b, job1[0], "screening", moved_at=now - timedelta(days=2))
        await _seed_stage(
            c,
            job1[0],
            "rejected",
            moved_at=now - timedelta(days=10),
            reason="Brak doświadczenia",
            ended_by="recruiter",
        )
        await _seed_stage(c, job2[0], "screening", moved_at=now - timedelta(days=1))
        await _seed_stage(d, job2[0], "screening", moved_at=now - timedelta(days=1))

        everyone = _ids(await _list(app_client, app_auth_headers, cohort))
        assert everyone == {a, b, c, d}

        no_exp = [("rejection_key", "r:Brak doświadczenia")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, no_exp)) == {c}

        hide = [*no_exp, ("rejection_exclude", "true")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, hide)) == {
            a,
            b,
            d,
        }

        by_client = [("rejection_by", "client")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, by_client)) == {a}

        both = [
            ("rejection_key", "r:Brak doświadczenia"),
            ("rejection_key", "r:Za wysokie oczekiwania finansowe"),
            ("rejection_by", "us"),
        ]
        assert _ids(await _list(app_client, app_auth_headers, cohort, both)) == {c}

        recent = [("rejection_within_months", "3"), ("rejection_by", "us")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, recent)) == {c}
    finally:
        await _cleanup([a, b, c, d], [job1, job2])


@pytest.mark.asyncio
async def test_traffit_category_period_and_no_reason(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"Rej{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    job = await _seed_job()
    quit_ = await _seed_candidate(cohort)
    old = await _seed_candidate(cohort)
    bare = await _seed_candidate(cohort)
    try:
        await _seed_stage(
            quit_,
            job[0],
            "rejected",
            moved_at=now - timedelta(days=30),
            rejection_note="Rezygnacja przez Kandydata",
            notes="znalazł inną pracę",
        )
        await _seed_stage(
            old,
            job[0],
            "rejected",
            moved_at=now - timedelta(days=200),
            rejection_note="Po CV",
            notes="stawka 115",
        )
        await _seed_stage(bare, job[0], "rejected", moved_at=now - timedelta(days=20))

        cat = [("rejection_key", "t:Rezygnacja przez Kandydata")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, cat)) == {quit_}
        by_cand = [("rejection_by", "candidate")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, by_cand)) == {
            quit_
        }
        po_cv_3m = [("rejection_key", "t:Po CV"), ("rejection_within_months", "3")]
        assert (
            _ids(await _list(app_client, app_auth_headers, cohort, po_cv_3m)) == set()
        )
        po_cv_12m = [("rejection_key", "t:Po CV"), ("rejection_within_months", "12")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, po_cv_12m)) == {
            old
        }
        none = [("rejection_key", "none")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, none)) == {bare}
        unknown = [("rejection_key", "r:Takiego powodu nie ma")]
        assert _ids(await _list(app_client, app_auth_headers, cohort, unknown)) == set()
        unknown_hide = [*unknown, ("rejection_exclude", "true")]
        assert _ids(
            await _list(app_client, app_auth_headers, cohort, unknown_hide)
        ) == {quit_, old, bare}
    finally:
        await _cleanup([quit_, old, bare], [job])


@pytest.mark.asyncio
async def test_column_and_facets(app_client: AsyncClient, app_auth_headers: dict):
    cohort = f"Rej{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    job = await _seed_job()
    a = await _seed_candidate(cohort)
    b = await _seed_candidate(cohort)
    c = await _seed_candidate(cohort)
    try:
        await _seed_stage(
            a,
            job[0],
            "rejected",
            moved_at=now - timedelta(days=3),
            reason="Inne (rejected)",
            ended_by="delivery_lead",
            notes="podpisał umowę z inną firmą",
        )
        await _seed_stage(
            b,
            job[0],
            "rejected",
            moved_at=now - timedelta(days=3),
            rejection_note="Odrzucenie oferty przez Kandydata",
        )
        params = [
            ("include_last_rejection", "true"),
            ("include_rejection_facets", "true"),
            # Pasek liczy się BEZ samego filtra odrzucenia.
            ("rejection_key", "r:Inne"),
        ]
        payload = await _list(app_client, app_auth_headers, cohort, params)
        assert _ids(payload) == {a}
        row = payload["items"][0]["last_rejection"]
        assert row["key"] == "r:Inne"
        assert row["label"] == "Inne"
        assert row["who"] == "us"
        assert row["ended_by"] == "delivery_lead"
        assert row["note"] == "podpisał umowę z inną firmą"
        assert row["job_id"] == job[0]
        assert row["client_name"]

        facets = payload["rejection_facets"]
        assert facets["total"] == 3
        assert facets["without_rejection"] == 1
        counts = {it["key"]: it["count"] for it in facets["items"]}
        assert counts == {"r:Inne": 1, "t:Odrzucenie oferty przez Kandydata": 1}
        who = {it["key"]: it["count"] for it in facets["who"]}
        assert who == {"client": 0, "us": 1, "candidate": 1}

        plain = await _list(app_client, app_auth_headers, cohort)
        assert plain.get("rejection_facets") is None
        assert all(it.get("last_rejection") is None for it in plain["items"])
    finally:
        await _cleanup([a, b, c], [job])


@pytest.mark.asyncio
async def test_invalid_values_return_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    for params in (
        {"rejection_by": "dl"},
        {"rejection_within_months": "6"},
    ):
        r = await app_client.get(
            "/api/candidates", params=params, headers=app_auth_headers
        )
        assert r.status_code == 422, (params, r.text)
