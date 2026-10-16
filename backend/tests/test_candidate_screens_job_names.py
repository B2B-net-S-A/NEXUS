"""Nazwa rekrutacji na ekranach kandydata jak w nagłówku rekrutacji (16.10.2026).

Zgłoszenie: rekrutacja w nagłówku to „ZOB-… Senior AI Engineer · Java, LLM”
(numer u klienta + tytuł dla rekrutera), a profil, szybki podgląd, lista
kandydatów, oś czasu i notatki pokazywały samą nazwę od klienta. Odpowiedzi
niosą teraz ``job_working_title`` i ``job_client_reference`` obok
``job_title``, który ZOSTAJE nazwą od klienta — z niego profil rozpoznaje
kody CV dla klientów, a do klienta idzie tylko ta nazwa (reguła 0380).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from httpx import AsyncClient
from sqlalchemy.dialects import postgresql

from app.api.notes import _enriched_select
from app.api.recommendations import _shape_seek_job
from app.schemas.candidate import ActiveRecruitmentBrief, CandidateQuickViewRecruitment
from app.schemas.candidate_search import LastRecruitment
from app.schemas.note import EnrichedNoteResponse
from app.services.candidate_job_cards import latest_cards

CLIENT_TITLE = "AI Engineer (ZOB-9001)"
WORKING_TITLE = "Senior AI Engineer · Java, LLM · 5+ lat"
REFERENCE = "ZOB-9001"


def _job(**overrides):
    base = dict(
        id=7,
        title=CLIENT_TITLE,
        working_title=WORKING_TITLE,
        client_reference=REFERENCE,
        client_id=3,
        location=None,
        salary_min=None,
        salary_max=None,
        remote_policy=None,
        seniority=None,
        deadline=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_seeking_contractors_job_keeps_client_title_and_adds_names() -> None:
    shaped = _shape_seek_job(_job())
    assert shaped["title"] == CLIENT_TITLE
    assert shaped["working_title"] == WORKING_TITLE
    assert shaped["client_reference"] == REFERENCE


def test_seeking_contractors_job_without_names_sends_nulls() -> None:
    shaped = _shape_seek_job(_job(working_title=None, client_reference=None))
    assert shaped["title"] == CLIENT_TITLE
    assert shaped["working_title"] is None
    assert shaped["client_reference"] is None


def test_new_fields_are_optional_for_older_payloads() -> None:
    moved = datetime(2026, 10, 1, tzinfo=timezone.utc)
    brief = ActiveRecruitmentBrief(job_id=1, job_title=CLIENT_TITLE, stage="new")
    quick = CandidateQuickViewRecruitment(
        job_id=1, job_title=CLIENT_TITLE, stage_id=2, stage_name="Nowi", moved_at=moved
    )
    last = LastRecruitment(
        job_id=1,
        job_title=WORKING_TITLE,
        stage_label="Nowi",
        column="new",
        moved_on=moved.date(),
    )
    for row in (brief, quick):
        assert row.job_working_title is None
        assert row.job_client_reference is None
    assert last.job_client_reference is None
    assert EnrichedNoteResponse.model_fields["job_working_title"].default is None


def test_integration_api_note_select_keeps_its_column_order() -> None:
    """`integrations_v1` rozpakowuje `_enriched_select()` po pozycjach —
    nowe kolumny dokłada tylko lista notatek (`add_columns`)."""
    names = [d["name"] for d in _enriched_select().column_descriptions]
    assert names == ["Note", "author_name", "job_title", "pinned_by_name"]


class _Db:
    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [])


async def test_last_recruitment_query_reads_client_reference() -> None:
    db = _Db()
    await latest_cards(db, candidate_ids=[1], exclude_job_id=2)
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "jobs.client_reference" in sql


# ── Z bazą (CI) ──────────────────────────────────────────────────────────────


async def _seed() -> tuple[int, int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.note import Note
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    token = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Nazwy-{token}")
        db.add(client)
        await db.flush()
        job = Job(
            title=CLIENT_TITLE,
            working_title=WORKING_TITLE,
            working_title_auto=False,
            client_reference=REFERENCE,
            status=JobStatus.published,
            client_id=client.id,
        )
        person = Candidate(
            name="Nazwy", lastname=f"Test-{token}", email=f"nazwy-{token}@example.com"
        )
        db.add_all([job, person])
        await db.flush()
        db.add_all(
            [
                CandidateStage(
                    candidate_id=person.id,
                    job_id=job.id,
                    stage=PipelineStage.screening,
                    moved_at=datetime.now(timezone.utc),
                ),
                Note(
                    candidate_id=person.id,
                    job_id=job.id,
                    content=f"Rozmowa {token}",
                ),
            ]
        )
        await db.commit()
        return person.id, job.id, person.email


def _assert_names(row: dict) -> None:
    assert row["job_title"] == CLIENT_TITLE
    assert row["job_working_title"] == WORKING_TITLE
    assert row["job_client_reference"] == REFERENCE


async def test_candidate_screens_carry_names_like_the_job_header(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    candidate_id, job_id, email = await _seed()

    listed = await app_client.get(
        "/api/candidates",
        params={"q": email, "include_active_recruitments": "true"},
        headers=app_auth_headers,
    )
    assert listed.status_code == 200, listed.text
    (row,) = [c for c in listed.json()["items"] if c["id"] == candidate_id]
    (active,) = row["active_recruitments"]
    _assert_names(active)

    quick = await app_client.get(
        f"/api/candidates/{candidate_id}/quick-view", headers=app_auth_headers
    )
    assert quick.status_code == 200, quick.text
    (current,) = quick.json()["current_recruitments"]
    _assert_names(current)

    history = await app_client.get(
        f"/api/candidates/{candidate_id}/history", headers=app_auth_headers
    )
    assert history.status_code == 200, history.text
    (entry,) = [j for j in history.json()["jobs"] if j["job_id"] == job_id]
    _assert_names(entry)

    timeline = await app_client.get(
        f"/api/candidates/{candidate_id}/timeline", headers=app_auth_headers
    )
    assert timeline.status_code == 200, timeline.text
    kinds = {
        item["type"]: item
        for item in timeline.json()["timeline"]
        if item.get("job_id") == job_id and item["type"] in {"note", "stage_change"}
    }
    assert set(kinds) == {"note", "stage_change"}
    for item in kinds.values():
        _assert_names(item)

    notes = await app_client.get(
        "/api/notes", params={"candidate_id": candidate_id}, headers=app_auth_headers
    )
    assert notes.status_code == 200, notes.text
    (note,) = notes.json()["items"]
    _assert_names(note)
