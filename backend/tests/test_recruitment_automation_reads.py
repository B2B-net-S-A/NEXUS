"""Odczyty automatów rekrutacji (21.09.2026): podpowiedzi w arkuszu screeningu
i zakładka „Praca w tle".

- podpowiedzi stawki/dostępności pochodzą z gotowego ``_notes_insights``:
  zero wywołań modelu, zero zapisów; stawkę widzi tylko rola, która może ją
  wpisać przy ruchu na „Zweryfikowany" (pozostałe dostają ``rate_redacted``);
- „Praca w tle" ma tę samą bramkę co skrzynka „Propozycje", a imię i nazwisko
  kandydata dostaje wyłącznie rola z odczytem kandydatów;
- domyślne wartości wyłączników: wszystkie cztery automaty WŁĄCZONE.
"""

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import Settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services.screening_suggestions import suggestions_from_notes
from tests.test_job_proposals import _user, _world

_INSIGHTS = {
    "expected_rate": {
        "value": "150",
        "currency": "pln",
        "period": "h",
        "raw": "150 zł/h netto B2B",
        "as_of": "2026-08",
    },
    "availability": {
        "raw": "od października",
        "notice_period": "1 miesiąc",
        "available_from": None,
    },
    "_extracted_at": "2026-09-01T10:00:00+00:00",
}


def _candidate(insights):
    return SimpleNamespace(cv_extracted_data={"_notes_insights": insights})


def test_defaults_keep_all_four_automations_on():
    fields = Settings.model_fields
    assert fields["AUTO_FULL_REVIEW_ENABLED"].default is True
    # Audyt 22.09 r2 (PROD-03): 5/noc — przegląd ~190 MB.
    assert fields["AUTO_FULL_REVIEW_MAX_PER_NIGHT"].default == 5
    assert fields["AUTO_FULL_REVIEW_TOP_K"].default == 60
    assert fields["CV_AUTO_GENERATE_ON_VERIFIED"].default is True
    assert fields["AUTO_MATCH_MODE"].default is None  # = propose
    assert fields["AUTO_MATCH_DRY_RUN"].default is None


def test_suggestions_shape():
    out = suggestions_from_notes(_candidate(_INSIGHTS), include_rate=True)
    assert out["rate"] == {
        "value": 150.0,
        "unit": "hour",
        "currency": "PLN",
        "raw": "150 zł/h netto B2B",
        "source_note_id": None,
        "noted_at": "2026-08",
    }
    assert out["availability"] == {
        "raw": "od października",
        "notice_period": "1 miesiąc",
        "available_from": None,
        "source_note_id": None,
        "noted_at": "2026-09-01T10:00:00+00:00",
    }
    assert out["rate_redacted"] is False


def test_rate_is_redacted_not_dropped_silently():
    out = suggestions_from_notes(_candidate(_INSIGHTS), include_rate=False)
    assert "rate" not in out and out["rate_redacted"] is True
    assert "availability" in out


@pytest.mark.parametrize(
    "insights",
    [
        None,
        "garbage",
        {},
        {"expected_rate": {"value": "150-200"}, "availability": {"raw": " "}},
        {"expected_rate": {"value": 0}, "availability": "soon"},
        {"expected_rate": {"value": True}},
    ],
)
def test_missing_or_malformed_insights_give_no_suggestion(insights):
    out = suggestions_from_notes(_candidate(insights), include_rate=True)
    assert out == {"rate_redacted": False}
    assert suggestions_from_notes(
        SimpleNamespace(cv_extracted_data=None), include_rate=True
    ) == {"rate_redacted": False}


async def _stage(world: dict, *, insights=None) -> int:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, world["candidate_ids"][0])
        candidate.cv_extracted_data = {"_notes_insights": insights or _INSIGHTS}
        stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=world["job_id"],
            stage=PipelineStage.screening,
        )
        db.add(stage)
        await db.commit()
        return stage.id


async def test_screening_sheet_carries_suggestions_without_saving_anything(
    app_client: AsyncClient,
):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    sourcer_id, sourcer = await _user(UserRole.sourcer)
    # Arkusz czyta zespół rekrutacji — obie osoby są właścicielami swoich.
    world = await _world(people=1, recruiter_id=recruiter_id)
    stage_id = await _stage(world)
    sourcer_world = await _world(people=1, recruiter_id=sourcer_id)
    sourcer_stage_id = await _stage(sourcer_world)

    response = await app_client.get(
        f"/api/pipeline/stages/{stage_id}/screening", headers=recruiter
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggestions"]["rate"]["value"] == 150.0
    assert body["suggestions"]["availability"]["notice_period"] == "1 miesiąc"
    assert body["screening_answers"] is None

    # Sourcer nie może wpisać stawki przy ruchu na „Zweryfikowany" — i jej nie widzi.
    narrow = await app_client.get(
        f"/api/pipeline/stages/{sourcer_stage_id}/screening", headers=sourcer
    )
    assert narrow.status_code == 200, narrow.text
    assert "rate" not in narrow.json()["suggestions"]
    assert narrow.json()["suggestions"]["rate_redacted"] is True
    assert "availability" in narrow.json()["suggestions"]

    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, stage_id)
        # Nic się nie zapisało: ani na etapie, ani w profilu kandydata.
        assert stage.expected_rate_value is None
        assert not stage.screening_answers
        candidate = await db.get(Candidate, world["candidate_ids"][0])
        assert candidate.expected_rate_hourly is not None  # wartość z seeda, nietknięta
        assert float(candidate.expected_rate_hourly) == 150.0


# ── „Praca w tle" ───────────────────────────────────────────────────────────


def _events_url(job_id: int) -> str:
    return f"/api/jobs/{job_id}/background-events"


async def _seed_events(world: dict) -> int:
    candidate_id = world["candidate_ids"][0]
    async with AsyncSessionLocal() as db:
        doc = CvGeneratedDocument(
            candidate_id=candidate_id,
            job_id=world["job_id"],
            candidate_name="x",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="",
            status="ready",
            origin="auto",
        )
        db.add(doc)
        await db.flush()

        def _event(action, details):
            return Activity(
                entity_type="job_automation",
                entity_id=world["job_id"],
                action=action,
                details=details,
            )

        db.add_all(
            [
                _event(
                    "auto_full_review_finished",
                    {"run_id": "run-1", "proposals": 7, "eligible": 120},
                ),
                _event(
                    "auto_match_proposed",
                    {"count": 2, "trigger": "cv_upload", "candidate_ids": [1, 2]},
                ),
                _event(
                    "cv_auto_generate_started",
                    {
                        "candidate_id": candidate_id,
                        "stage_id": 1,
                        "generated_id": doc.id,
                    },
                ),
                _event(
                    "cv_auto_generate_skipped",
                    {
                        "candidate_id": candidate_id,
                        "stage_id": 1,
                        "reason": "consent_screenshot_required",
                    },
                ),
                # Zwykła aktywność rekrutacji NIE jest zdarzeniem automatu.
                Activity(
                    entity_type="job", entity_id=world["job_id"], action="updated"
                ),
                _event("something_unrelated", {"secret": "x"}),
            ]
        )
        await db.commit()
        return doc.id


async def test_background_events_list_automation_activity(app_client: AsyncClient):
    world = await _world(people=1)
    doc_id = await _seed_events(world)
    _, headers = await _user(UserRole.recruiter)

    response = await app_client.get(_events_url(world["job_id"]), headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [i["kind"] for i in items] == [
        "cv_auto_generate_skipped",
        "cv_auto_generate",
        "new_cv_proposals",
        "auto_full_review",
    ]
    skipped, generated, new_cv, review = items
    assert skipped["reason"] == "consent_screenshot_required"
    assert skipped["candidate"]["id"] == world["candidate_ids"][0]
    assert skipped["candidate"]["name"].startswith("Propozycja")
    assert generated["generated_id"] == doc_id
    assert generated["document_status"] == "ready"
    assert (new_cv["count"], new_cv["trigger"]) == (2, "cv_upload")
    assert (review["proposals"], review["run_id"]) == (7, "run-1")
    # Surowe `details` nie wychodzą: tylko klucze z allowlisty.
    assert "candidate_ids" not in new_cv and "stage_id" not in skipped

    limited = await app_client.get(
        _events_url(world["job_id"]), params={"limit": 1}, headers=headers
    )
    assert len(limited.json()["items"]) == 1

    # Usunięty dokument nie wisi jako „w toku".
    async with AsyncSessionLocal() as db:
        await db.delete(await db.get(CvGeneratedDocument, doc_id))
        await db.commit()
    after = await app_client.get(_events_url(world["job_id"]), headers=headers)
    assert after.json()["items"][1]["document_status"] == "deleted"


@pytest.mark.parametrize(
    "role,pipeline,expected",
    [
        (UserRole.recruiter, None, 200),
        (UserRole.finance, None, 200),
        (UserRole.recruiter, "none", 403),
    ],
)
async def test_background_events_follow_the_inbox_gate(
    app_client: AsyncClient, role, pipeline, expected
):
    world = await _world(people=1)
    await _seed_events(world)
    _, headers = await _user(role, pipeline=pipeline)
    response = await app_client.get(_events_url(world["job_id"]), headers=headers)
    assert response.status_code == expected, response.text
    assert (await app_client.get(_events_url(world["job_id"]))).status_code == 401
    missing = await app_client.get(_events_url(2_000_000_000), headers=headers)
    assert missing.status_code in (403, 404)


async def test_names_are_only_for_roles_with_candidate_read(
    app_client: AsyncClient, monkeypatch
):
    from app.api import candidate_access

    world = await _world(people=1)
    await _seed_events(world)
    _, headers = await _user(UserRole.recruiter)
    monkeypatch.setattr(candidate_access, "CANDIDATE_READ_ROLES", (UserRole.admin,))
    response = await app_client.get(_events_url(world["job_id"]), headers=headers)
    assert response.status_code == 200, response.text
    candidates = [i["candidate"] for i in response.json()["items"] if "candidate" in i]
    assert candidates and all(c["name"] is None and c["id"] for c in candidates)


async def test_events_are_never_written_by_reading(app_client: AsyncClient):
    world = await _world(people=1)
    _, headers = await _user(UserRole.recruiter)
    response = await app_client.get(_events_url(world["job_id"]), headers=headers)
    assert response.json()["items"] == []
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(Activity.id).where(
                    Activity.entity_type == "job_automation",
                    Activity.entity_id == world["job_id"],
                )
            )
        ) is None
