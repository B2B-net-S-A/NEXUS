"""Rekrutacja bez szkiców (decyzja Artura 04.10.2026).

Utworzenie = przekazanie do searchu = publikacja w JEDNYM żądaniu i jednej
transakcji; ponowne otwarcie przechodzi tę samą bramkę; rekrutacja w pracy
odmawia zapisu wyłącznie przy NOWYM braku; stare szkice zamykają się same po
7 dniach od wdrożenia.

Testy bez bazy (reguły bramki, schematy, efekty po commicie) biegną wszędzie;
testy z ``app_client`` potrzebują Postgresa (CI). Baza testowa jest wspólna
i nieczyszczona — asercje tylko na własnych wierszach (uuid).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.models.job import JobStatus
from app.services import job_readiness
from app.services.job_lifecycle import (
    PostCommit,
    assert_no_new_handoff_blockers,
    regression_baseline,
    run_post_commit,
)

_READY_STORED = {
    "project": {"about": "Platforma płatności B2B"},
    "screening_questions": [
        {"id": "q1", "question": "Python?", "deal_breaker": "Brak Pythona."},
        {"id": "q2", "question": "Postgres?", "deal_breaker": "Brak baz danych."},
    ],
    "stack": {"must": [{"name": "Python"}], "critical": []},
    "search": {"requirements": [["Python"]]},
}


def _job(**kw) -> SimpleNamespace:
    """Rekrutacja „gotowa” (bez bazy) — test nadpisuje tylko to, co bada."""
    base = dict(
        title="Senior Python Developer",
        client_id=1,
        champion_profile=_READY_STORED,
        must_skills=[{"name": "Python"}],
        rate_budget_hourly=150,
        remote_policy="remote",
        onsite_days_per_week=None,
        location=None,
        hiring_manager_contact_id=None,
        hiring_manager_not_provided=True,
        deadline=None,
        deadline_not_provided=True,
        competence_category_id=1,
        headcount=1,
        status=JobStatus.published,
        is_open=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _codes(job) -> list[str]:
    return [i["code"] for i in job_readiness.job_handoff_blocker_items(job)]


# ── Bramka: nowe decyzje (bez bazy) ──────────────────────────────────────────


def test_ready_job_has_no_blocker_items():
    assert job_readiness.job_handoff_blocker_items(_job()) == []


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"hiring_manager_not_provided": False}, "hiring_manager"),
        ({"deadline_not_provided": False}, "deadline"),
        ({"competence_category_id": None}, "category"),
        ({"headcount": 0}, "headcount"),
    ],
)
def test_each_decision_has_its_own_code(override, code):
    job = _job(**override)
    assert _codes(job) == [code]
    assert job_readiness.job_handoff_blockers(job) == [
        job_readiness.BLOCKER_CODES[code]
    ]


def test_a_value_is_as_good_as_client_did_not_say():
    job = _job(
        hiring_manager_contact_id=7,
        hiring_manager_not_provided=False,
        deadline=date(2026, 12, 31),
        deadline_not_provided=False,
    )
    assert _codes(job) == []


def test_allocation_brief_gate_ignores_the_decisions():
    """Bramka briefu automatu przydziału (`job_readiness_blockers`) nie czyta
    decyzji — inaczej automat po cichu parkowałby stare requesty."""
    job = _job(
        hiring_manager_not_provided=False,
        deadline_not_provided=False,
        competence_category_id=None,
        headcount=0,
    )
    assert job_readiness.job_readiness_blockers(job) == []
    assert set(_codes(job)) == {"hiring_manager", "deadline", "category", "headcount"}


def test_open_job_counts_deal_breakers_only_when_asked():
    champion = {
        **_READY_STORED,
        "screening_questions": [
            {"id": "q1", "question": "Python?"},
            {"id": "q2", "question": "Postgres?"},
        ],
    }
    job = _job(champion_profile=champion, is_open=True)
    assert "deal_breaker" not in _codes(job)
    items = job_readiness.job_handoff_blocker_items(job, include_open=True)
    assert [i["code"] for i in items] == ["deal_breaker"]


def test_champion_issue_codes_are_prefixed(monkeypatch):
    from app.services import champion_intake

    monkeypatch.setattr(
        champion_intake,
        "validation",
        lambda *_a, **_k: {
            "issues": [
                {
                    "code": "column_conflict",
                    "message": "Stawka w profilu różni się od rekrutacji.",
                    "blocked_operations": ["handoff"],
                }
            ]
        },
    )
    assert _codes(_job()) == ["champion:column_conflict"]


# ── Ochrona rekrutacji w pracy (bez bazy) ────────────────────────────────────


def test_regression_guard_refuses_only_a_new_gap():
    from fastapi import HTTPException

    job = _job(deadline_not_provided=False)
    before = regression_baseline(job)
    assert before == {"deadline"}
    # Brak, który już był, nie blokuje kolejnych zapisów.
    assert_no_new_handoff_blockers(before, job)

    job.hiring_manager_not_provided = False
    with pytest.raises(HTTPException) as refused:
        assert_no_new_handoff_blockers(before, job)
    assert refused.value.status_code == 422
    assert refused.value.detail["code"] == "handoff_regression"
    assert [b["code"] for b in refused.value.detail["blockers"]] == ["hiring_manager"]


def test_a_gap_revealed_by_fixing_its_parent_is_not_new():
    """Pytania dopisane bez odpowiedzi dyskwalifikującej: zapis naprawił brak
    pytań, a odsłonięty brak „deal_breaker” nie blokuje uzupełniania."""
    no_questions = {**_READY_STORED, "screening_questions": []}
    job = _job(champion_profile=no_questions)
    before = regression_baseline(job)
    assert "questions" in before
    job.champion_profile = {
        **_READY_STORED,
        "screening_questions": [
            {"id": "q1", "question": "Python?"},
            {"id": "q2", "question": "Postgres?"},
        ],
    }
    assert_no_new_handoff_blockers(before, job)


def test_regression_guard_skips_jobs_not_in_work():
    job = _job(status=JobStatus.closed, competence_category_id=None)
    assert regression_baseline(job) is None
    assert_no_new_handoff_blockers(None, job)


# ── Schematy (bez bazy) ──────────────────────────────────────────────────────


def test_job_create_requires_the_complete_recruitment():
    from app.schemas.job import JobCreate

    with pytest.raises(ValidationError) as missing:
        JobCreate(title="X", client_id=1)
    fields = {err["loc"][0] for err in missing.value.errors()}
    assert {"champion_profile", "hiring_manager", "handoff"} <= fields

    created = JobCreate(
        title="X",
        client_id=1,
        champion_profile={},
        hiring_manager={"not_provided": True},
        handoff={"recruiter_id": 5},
        status="draft",
    )
    # Pole `status` nie istnieje — szkic nie powstaje nigdy.
    assert "status" not in created.model_dump()
    # Audyt 06.10.2026 (N6): bez domyślnej „1” — pominięte pole zamienia na 1
    # dopiero `create_job_core`, a jawne `null` zatrzymuje bramka przekazania.
    assert created.headcount is None


@pytest.mark.parametrize(
    "decision",
    [{}, {"contact_id": 1, "not_provided": True}, {"clear": True}],
)
def test_create_hiring_manager_needs_exactly_one_decision(decision):
    from app.schemas.job import JobCreateHiringManager

    with pytest.raises(ValidationError):
        JobCreateHiringManager(**decision)


def test_headcount_is_at_least_one():
    from app.schemas.job import JobUpdate

    with pytest.raises(ValidationError):
        JobUpdate(headcount=0)
    with pytest.raises(ValidationError):
        JobUpdate(deadline_not_provided=None)
    assert JobUpdate(headcount=2, deadline_not_provided=True).headcount == 2


def test_publish_body_is_a_handoff_with_a_reason():
    from app.schemas.job import JobPublishRequest

    body = JobPublishRequest(recruiter_id=3, reason="Klient wznowił projekt")
    assert body.assignment_mode == "manual"
    assert body.reason == "Klient wznowił projekt"


# ── Efekty po commicie (bez bazy) ────────────────────────────────────────────


async def test_post_commit_effects_are_isolated_and_keep_results():
    calls: list[str] = []
    effects = PostCommit()

    async def boom():
        calls.append("boom")
        raise RuntimeError("awaria efektu")

    async def snapshot():
        calls.append("snapshot")
        effects.later(lambda: calls.append("later"))
        return 42

    effects.add("boom", boom)
    effects.add("snapshot_id", snapshot)
    await run_post_commit(effects)
    assert calls == ["boom", "snapshot", "later"]
    assert effects.results["snapshot_id"] == 42
    assert "boom" not in effects.results


async def test_post_commit_hands_later_tasks_to_background_tasks():
    queued: list[tuple] = []
    background = SimpleNamespace(add_task=lambda fn, *a, **k: queued.append((fn, a)))
    effects = PostCommit(background)
    effects.later(print, "x")
    await run_post_commit(effects)
    assert queued == [(print, ("x",))]


# ── API (Postgres, CI) ───────────────────────────────────────────────────────


async def _client(name: str = "NoDrafts") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"{name}-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


async def _job_row(job_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        return await db.get(Job, job_id)


@pytest.fixture
def offline_matching(monkeypatch):
    """Migawka dopasowań liczona w tle zostaje offline i szybka."""
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)


@pytest.mark.asyncio
async def test_create_publishes_and_hands_off_in_one_request(
    app_client, app_auth_headers, offline_matching
):
    from tests._job_factory import complete_job_payload

    client_id = await _client()
    payload = await complete_job_payload(client_id)
    recruiter_id = payload["handoff"]["recruiter_id"]

    resp = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "published"
    assert body["is_open"] is True
    assert body["work_state"] == "searching"
    assert body["recruiter_id"] == recruiter_id
    assert body["hiring_manager_not_provided"] is True
    assert body["deadline_not_provided"] is True
    assert body["snapshot_id"] is not None
    job = await _job_row(body["id"])
    assert job.champion_profile["search"]["requirements"]


@pytest.mark.asyncio
async def test_refused_create_leaves_no_rows(app_client, app_auth_headers):
    """422 cofa CAŁĄ transakcję: rekrutację, nowy kontakt (HM) i historię."""
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.contact import Contact
    from app.models.job import Job
    from tests._job_factory import complete_job_payload

    client_id = await _client()
    title = f"Atomowa {uuid.uuid4().hex[:8]}"
    person = f"Anna Atomowa{uuid.uuid4().hex[:6]}"
    payload = await complete_job_payload(
        client_id,
        title=title,
        hiring_manager={"new_person": {"name": person}},
        deadline_not_provided=False,
    )

    resp = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "job_not_ready"
    assert detail["message"] == "Rekrutacja nie powstała — uzupełnij braki."
    assert detail["blockers"] == [
        {"code": "deadline", "message": job_readiness.MSG_DEADLINE}
    ]
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(func.count(Job.id)).where(Job.title == title)) == 0
        )
        assert (
            await db.scalar(
                select(func.count(Contact.id)).where(
                    Contact.client_id == client_id, Contact.name == person
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(Activity.id)).where(
                    Activity.entity_type == "client",
                    Activity.entity_id == client_id,
                )
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"hiring_manager": None}, None),
        ({"competence_category_id": None}, "category"),
        ({"deadline_not_provided": False}, "deadline"),
    ],
)
async def test_create_names_each_missing_decision(
    app_client, app_auth_headers, override, code
):
    from tests._job_factory import complete_job_payload

    payload = await complete_job_payload(await _client(), **override)
    if override.get("hiring_manager", "") is None:
        payload.pop("hiring_manager")
    resp = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)
    assert resp.status_code == 422, resp.text
    if code is None:
        # Bez decyzji o HM żądanie nie przechodzi schematu.
        assert any(err["loc"][-1] == "hiring_manager" for err in resp.json()["detail"])
    else:
        assert [b["code"] for b in resp.json()["detail"]["blockers"]] == [code]


@pytest.mark.asyncio
async def test_create_records_the_category_override_for_a_delivery_lead_or_admin(
    app_client, app_auth_headers, offline_matching
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.cc_feedback import CcSuggestionOverride
    from tests._job_factory import complete_job_payload

    payload = await complete_job_payload(
        await _client(),
        cc_override={"suggested_cc_id": None, "suggested_score": 0.42},
    )
    resp = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CcSuggestionOverride).where(
                CcSuggestionOverride.job_id == resp.json()["id"]
            )
        )
    assert row is not None
    assert row.final_cc_id == payload["competence_category_id"]


@pytest.mark.asyncio
async def test_patch_refuses_draft_and_reopening(
    app_client, app_auth_headers, offline_matching
):
    from tests._job_factory import complete_job_payload

    created = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(await _client()),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    url = f"/api/jobs/{created.json()['id']}"

    draft = await app_client.patch(
        url, json={"status": "draft"}, headers=app_auth_headers
    )
    assert draft.status_code == 422, draft.text
    assert draft.json()["detail"]["code"] == "draft_not_allowed"

    same = await app_client.patch(
        url,
        json={"status": "published", "title": "Ten sam status"},
        headers=app_auth_headers,
    )
    assert same.status_code == 200, same.text

    closed = await app_client.patch(
        url, json={"status": "closed"}, headers=app_auth_headers
    )
    assert closed.status_code == 200, closed.text
    reopened = await app_client.patch(
        url, json={"status": "published"}, headers=app_auth_headers
    )
    assert reopened.status_code == 409, reopened.text
    assert reopened.json()["detail"]["code"] == "reopen_required"


@pytest.mark.asyncio
async def test_patch_refuses_a_new_gap_on_a_job_in_work(
    app_client, app_auth_headers, offline_matching
):
    from tests._job_factory import complete_job_payload

    created = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(await _client()),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    url = f"/api/jobs/{created.json()['id']}"

    refused = await app_client.patch(
        url, json={"deadline_not_provided": False}, headers=app_auth_headers
    )
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "handoff_regression"
    assert [b["code"] for b in detail["blockers"]] == ["deadline"]

    # Data zamiast „Klient nie podał” — brak znika, zapis przechodzi.
    dated = await app_client.patch(
        url,
        json={"deadline": "2027-01-31", "deadline_not_provided": False},
        headers=app_auth_headers,
    )
    assert dated.status_code == 200, dated.text
    assert dated.json()["deadline_not_provided"] is False

    # Zwykła edycja bez nowego braku przechodzi.
    ok = await app_client.patch(url, json={"headcount": 2}, headers=app_auth_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["headcount"] == 2


@pytest.mark.asyncio
async def test_client_change_on_a_job_in_work_is_not_a_regression(
    app_client, app_auth_headers, offline_matching
):
    """Zmiana klienta zdejmuje HM poprzedniego klienta — to skutek zmiany,
    nie nowy brak. Okno edycji wskazuje nowego HM osobnym zapisem po zmianie
    klienta (kontakt musi należeć już do nowego klienta)."""
    from tests._job_factory import complete_job_payload

    first, second = await _client("HmA"), await _client("HmB")
    created = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(
            first, hiring_manager={"new_person": {"name": "Jan Testowy"}}
        ),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["hiring_manager_contact_id"] is not None

    moved = await app_client.patch(
        f"/api/jobs/{created.json()['id']}",
        json={"client_id": second},
        headers=app_auth_headers,
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["client_id"] == second
    assert moved.json()["hiring_manager_contact_id"] is None


@pytest.mark.asyncio
async def test_champion_save_refuses_a_new_gap_on_a_job_in_work(
    app_client, app_auth_headers, offline_matching
):
    from tests._job_factory import complete_job_payload

    created = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(await _client()),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    url = f"/api/jobs/{created.json()['id']}/champion-profile"

    refused = await app_client.put(
        url,
        json={"screening_questions": [{"id": "q1", "question": "Python?"}]},
        headers=app_auth_headers,
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "handoff_regression"
    codes = {b["code"] for b in refused.json()["detail"]["blockers"]}
    assert "questions" in codes

    fine = await app_client.put(
        url,
        json={"project": {"about": "Nowy opis projektu płatności."}},
        headers=app_auth_headers,
    )
    assert fine.status_code == 200, fine.text


@pytest.mark.asyncio
async def test_reopen_goes_through_the_handoff_gate(
    app_client, app_auth_headers, offline_matching
):
    from tests._job_factory import complete_job_payload, new_recruiter

    created = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(await _client()),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "other"},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text

    no_body = await app_client.post(
        f"/api/jobs/{job_id}/publish", headers=app_auth_headers
    )
    assert no_body.status_code == 422, no_body.text
    assert no_body.json()["detail"]["code"] == "handoff_required"

    # Brak (kategoria zdjęta wprost w bazie) = 422 i rekrutacja zostaje zamknięta.
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        category_id = job.competence_category_id
        job.competence_category_id = None
        await db.commit()
    body = {"assignment_mode": "manual", "recruiter_id": await new_recruiter()}
    refused = await app_client.post(
        f"/api/jobs/{job_id}/publish", json=body, headers=app_auth_headers
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "job_not_ready"
    assert [b["code"] for b in refused.json()["detail"]["blockers"]] == ["category"]
    assert (await _job_row(job_id)).status == JobStatus.closed

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.competence_category_id = category_id
        await db.commit()
    reopened = await app_client.post(
        f"/api/jobs/{job_id}/publish",
        json={**body, "reason": "Klient wznowił projekt"},
        headers=app_auth_headers,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["recruiter_id"] == body["recruiter_id"]
    job = await _job_row(job_id)
    assert job.status == JobStatus.published
    assert job.is_open is True
    assert job.closed_at is None

    # W pracy: kolejne „Otwórz ponownie” nic nie zmienia.
    again = await app_client.post(
        f"/api/jobs/{job_id}/publish", headers=app_auth_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["unchanged"] is True


@pytest.mark.asyncio
async def test_handoff_of_a_legacy_draft_publishes_it(
    app_client, app_auth_headers, offline_matching
):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from tests._job_factory import make_job_ready, new_recruiter

    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Stary szkic {uuid.uuid4().hex[:6]}",
            status=JobStatus.draft,
            client_id=await _client(),
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    await make_job_ready(job_id)

    readiness = await app_client.get(
        f"/api/jobs/{job_id}/readiness", headers=app_auth_headers
    )
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["blocker_items"] == []

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        json={"recruiter_id": await new_recruiter()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 202, resp.text
    job = await _job_row(job_id)
    assert job.status == JobStatus.published
    assert job.is_open is True


@pytest.mark.asyncio
async def test_readiness_names_the_codes_also_for_a_closed_job(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Zamknięta {uuid.uuid4().hex[:6]}",
            status=JobStatus.closed,
            client_id=await _client(),
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    resp = await app_client.get(
        f"/api/jobs/{job_id}/readiness", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["closed"] is True
    assert body["ready"] is False
    codes = {item["code"] for item in body["blocker_items"]}
    assert {"hiring_manager", "deadline", "category"} <= codes
    assert body["blockers"] == [item["message"] for item in body["blocker_items"]]


# ── Stare szkice: zamknięcie po 7 dniach (Postgres, CI) ──────────────────────


@pytest.mark.asyncio
async def test_legacy_drafts_close_seven_days_after_deploy_and_leave_a_receipt():
    """Przebieg idzie w transakcji wycofywanej na końcu — baza testowa jest
    wspólna, a przebieg zamyka WSZYSTKIE szkice."""
    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.app_setting import AppSetting
    from app.models.job import Job, JobCloseReason
    from app.services import legacy_draft_autoclose as autoclose

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == autoclose.RECEIPT_KEY)
        )
        await db.execute(
            delete(AppSetting).where(AppSetting.key == autoclose.DEPLOYED_KEY)
        )
        db.add(
            AppSetting(
                key=autoclose.DEPLOYED_KEY,
                value={"deployed_at": (now - timedelta(days=6)).isoformat()},
            )
        )
        draft = Job(
            title=f"Szkic {uuid.uuid4().hex[:6]}",
            status=JobStatus.draft,
            client_id=await _client(),
        )
        db.add(draft)
        await db.flush()

        # Okno trwa: nic się nie dzieje, data zamknięcia jest znana.
        assert (
            await autoclose.run_legacy_draft_autoclose(db, PostCommit(), now=now)
            is None
        )
        assert draft.status == JobStatus.draft
        assert await autoclose.legacy_draft_autoclose_on(db) == (
            (now + timedelta(days=1)).astimezone(ZoneInfo("Europe/Warsaw")).date()
        )

        later = now + timedelta(days=1, minutes=1)
        receipt = await autoclose.run_legacy_draft_autoclose(
            db, PostCommit(), now=later
        )
        assert receipt is not None
        assert draft.id in receipt["closed_ids"]
        assert receipt["count"] == len(receipt["closed_ids"])
        await db.refresh(draft)
        assert draft.status == JobStatus.closed
        assert draft.close_reason == JobCloseReason.other
        assert draft.close_notes == autoclose.CLOSE_NOTE
        # Szkic nie wchodzi do mianownika hit ratio Ligi DL (audyt 05.10.2026).
        assert draft.closed_at is None
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "job",
                Activity.entity_id == draft.id,
                Activity.action == "closed",
            )
        )
        assert activity is not None and activity.user_id is None
        stored = await db.get(AppSetting, autoclose.RECEIPT_KEY)
        assert stored is not None and stored.value["count"] == receipt["count"]

        # Paragon kończy każdy kolejny przebieg od razu.
        assert (
            await autoclose.run_legacy_draft_autoclose(db, PostCommit(), now=later)
            is None
        )
        assert await autoclose.legacy_draft_autoclose_on(db) is None
        await db.rollback()


def test_autoclose_reads_both_marker_shapes():
    from app.services.legacy_draft_autoclose import _parse_moment

    moment = _parse_moment({"deployed_at": "2026-10-04T10:00:00+00:00"})
    assert moment == datetime(2026, 10, 4, 10, tzinfo=timezone.utc)
    assert _parse_moment("2026-10-04T10:00:00Z") == moment
    assert _parse_moment({"deployed_at": "nie data"}) is None
    assert _parse_moment(None) is None
