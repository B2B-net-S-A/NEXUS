"""Bliźniacze rekrutacje (0614, decyzje Artura z 28.10.2026).

Bez bazy: lustro DDL, podpowiedź par pytań na prawdziwej parze ZOB-2947 ↔
ZOB-2964, grupy pytań wspólnego screeningu. Z bazą (prawdziwy Postgres,
wspólny i nieczyszczony — każdy test zakłada własne rekrutacje): kto łączy,
rozłączenie, bramka „Zweryfikowany”, stawka w budżecie, propozycje dla HoR.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_similar_link import JobSimilarLink, JobTwinDismissal
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import job_twins
from app.services.job_twin_schema import ALL_DDL, ENUM_DDL
from app.services.screening_question_groups import group_questions

ENTRYPOINT = Path(__file__).resolve().parent.parent / "entrypoint.sh"

# Pytania z Profilu Championa pary ZOB-2947 / ZOB-2964 (kopia produkcji
# z 22.10.2026, skrócone). Reguła tekstu łączyła z nich 0 z 8.
ZOB_2947 = {
    "q1": "Jakie masz praktyczne doświadczenie z Private Cloud oraz OCP/OpenShift "
    "Red Hat, przy jakich aplikacjach lub mikroserwisach wykorzystywałeś/aś te "
    "technologie?",
    "q2": "Na jakim stacku budujesz produkcyjne mikroserwisy w Pythonie i jak "
    "wykorzystywałeś/aś API, bazy danych, Redis oraz Kubernetes/OpenShift?",
    "q3": "Jakie elementy DDD stosowałeś/aś przy projektowaniu mikroserwisów i jak "
    "wpłynęły one na granice domeny lub usług?",
    "q4": "Jakie produkcyjne aplikacje backendowe lub webowe rozwijałeś/aś "
    "w Pythonie i jaki był Twój zakres odpowiedzialności?",
    "q5": "Jakie masz doświadczenie z Git, Gerrit, Jenkins, Jira i Confluence "
    "w codziennej pracy projektowej?",
}
ZOB_2964 = {
    "q1": "Na jakim stacku buduje Pan/Pani produkcyjne mikroserwisy w Pythonie? "
    "Proszę opisać wykorzystanie FastAPI, sposób wystawiania REST API oraz "
    "współpracę z bazami danych.",
    "q2": "W jakim środowisku działały tworzone przez Pana/Panią mikroserwisy? Jakie "
    "ma Pan/Pani praktyczne doświadczenie z Kubernetes/OpenShift/OCP oraz Private "
    "Cloud?",
    "q3": "Jakie elementy DDD stosował/a Pan/Pani faktycznie przy projektowaniu "
    "mikroserwisów? Proszę podać przykład z projektu i powiedzieć, jak podzielił/a "
    "Pan/Pani domenę.",
}


# ── Bez bazy ──────────────────────────────────────────────────────────────


def _flat(text: str) -> str:
    """Sklejone literały Pythona i jedna spacja — lustro porównuje treść SQL."""
    text = re.sub(r'"\s*\n\s*"', "", text)
    return re.sub(r"\s+", " ", text)


def test_entrypoint_mirrors_the_migration_ddl() -> None:
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))
    for statement in (ENUM_DDL, *ALL_DDL):
        assert _flat(statement) in entrypoint, statement[:60]


def test_question_pair_hint_finds_the_three_shared_questions() -> None:
    pairs = job_twins.suggest_question_pairs(ZOB_2947, ZOB_2964)
    assert {(p["own"], p["other"]) for p in pairs} == {
        ("q1", "q2"),  # OpenShift / Private Cloud
        ("q2", "q1"),  # stack mikroserwisów
        ("q3", "q3"),  # DDD
    }


def test_question_pair_hint_never_pairs_rate_questions_by_words() -> None:
    own = {"q1": "Jaka jest Twoja oczekiwana stawka godzinowa na B2B?"}
    other = {"q1": "Jaką stawkę godzinową na B2B oczekujesz w tym projekcie?"}
    assert job_twins.suggest_question_pairs(own, other) == []


def test_validate_question_pairs_refuses_unknown_and_repeated() -> None:
    with pytest.raises(HTTPException) as unknown:
        job_twins.validate_question_pairs(
            [{"own": "q9", "other": "q1"}], ZOB_2947, ZOB_2964
        )
    assert unknown.value.detail["code"] == "twin_question_unknown"
    with pytest.raises(HTTPException) as repeated:
        job_twins.validate_question_pairs(
            [{"own": "q1", "other": "q1"}, {"own": "q2", "other": "q1"}],
            ZOB_2947,
            ZOB_2964,
        )
    assert repeated.value.detail["code"] == "twin_question_repeated"


def test_twin_pairs_merge_questions_the_text_rule_kept_apart() -> None:
    plain = group_questions({1: ZOB_2947, 2: ZOB_2964}, [1, 2])
    assert len(plain) == 8
    pairs = [((1, "q1"), (2, "q2")), ((1, "q2"), (2, "q1")), ((1, "q3"), (2, "q3"))]
    merged = group_questions({1: ZOB_2947, 2: ZOB_2964}, [1, 2], pairs)
    assert len(merged) == 5
    shared = [
        {(m.job_id, m.question_id) for m in group}
        for group in merged
        if len(group) == 2
    ]
    assert {(1, "q3"), (2, "q3")} in shared
    assert {(1, "q2"), (2, "q1")} in shared


# ── Z bazą ────────────────────────────────────────────────────────────────


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"twins-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Twins"),
            name=f"Twins {role.value} {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, role.value)}"
        }


async def _job(
    *,
    dl_id: int | None,
    client_id: int | None = None,
    status: JobStatus = JobStatus.published,
    questions: dict[str, str] | None = None,
    budget: str | None = None,
    priority: JobPriority = JobPriority.medium,
) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        if client_id is None:
            client = Client(name=f"Twins client {tag}")
            db.add(client)
            await db.flush()
            client_id = client.id
        job = Job(
            title=f"Programista Python {tag}",
            client_id=client_id,
            status=status,
            delivery_lead_id=dl_id,
            priority=priority,
            rate_budget_hourly=Decimal(budget) if budget else None,
            champion_profile=(
                {
                    "screening_questions": [
                        {"id": k, "question": v} for k, v in (questions or {}).items()
                    ]
                }
                if questions
                else None
            ),
        )
        db.add(job)
        await db.commit()
        return job.id


async def _client_of(job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.get(Job, job_id)).client_id


async def _kinds(job_id: int, other_id: int) -> dict[tuple[int, int], tuple[str, list]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(JobSimilarLink).where(
                    JobSimilarLink.job_id.in_([job_id, other_id]),
                    JobSimilarLink.similar_job_id.in_([job_id, other_id]),
                )
            )
        ).scalars()
        return {
            (r.job_id, r.similar_job_id): (r.kind, r.question_pairs or []) for r in rows
        }


async def _link_rows(job_id: int, other_id: int) -> None:
    async with AsyncSessionLocal() as db:
        for own, sim_id in ((job_id, other_id), (other_id, job_id)):
            db.add(JobSimilarLink(job_id=own, similar_job_id=sim_id, kind="twin"))
        await db.commit()


async def test_delivery_lead_links_own_requests_also_across_clients(
    app_client: AsyncClient,
) -> None:
    dl_id, dl = await _user(UserRole.delivery_lead)
    a = await _job(dl_id=dl_id, questions=ZOB_2947)
    b = await _job(dl_id=dl_id, questions=ZOB_2964)  # inny klient
    assert await _client_of(a) != await _client_of(b)

    preview = await app_client.get(
        f"/api/jobs/{a}/twins/preview?other_job_id={b}", headers=dl
    )
    assert preview.status_code == 200, preview.text
    hint = preview.json()["question_pairs"]
    assert {(p["own"], p["other"]) for p in hint} == {
        ("q1", "q2"),
        ("q2", "q1"),
        ("q3", "q3"),
    }

    linked = await app_client.post(
        f"/api/jobs/{a}/twins",
        headers=dl,
        json={"other_job_id": b, "question_pairs": [{"own": "q3", "other": "q3"}]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["linked_now"] is True
    assert [t["id"] for t in linked.json()["twins"]] == [b]
    rows = await _kinds(a, b)
    assert rows[(a, b)] == ("twin", [{"own": "q3", "other": "q3"}])
    assert rows[(b, a)] == ("twin", [{"own": "q3", "other": "q3"}])


async def test_delivery_lead_cannot_link_another_leads_request_hor_can(
    app_client: AsyncClient,
) -> None:
    dl_id, dl = await _user(UserRole.delivery_lead)
    other_dl_id, _ = await _user(UserRole.delivery_lead)
    hor_id, hor = await _user(UserRole.head_of_recruitment)
    a = await _job(dl_id=dl_id)
    b = await _job(dl_id=other_dl_id)

    refused = await app_client.post(
        f"/api/jobs/{a}/twins", headers=dl, json={"other_job_id": b}
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "twin_forbidden"
    assert await _kinds(a, b) == {}

    linked = await app_client.post(
        f"/api/jobs/{a}/twins", headers=hor, json={"other_job_id": b}
    )
    assert linked.status_code == 200, linked.text
    # Dzwonek do DL-a każdej strony, bez osoby, która połączyła.
    async with AsyncSessionLocal() as db:
        bells = (
            await db.execute(
                select(Notification.user_id, Notification.link).where(
                    Notification.notification_type == NotificationType.job_twin_linked,
                    Notification.user_id.in_([dl_id, other_dl_id, hor_id]),
                )
            )
        ).all()
    assert {(uid, link) for uid, link in bells} == {
        (dl_id, f"/jobs/{a}"),
        (other_dl_id, f"/jobs/{b}"),
    }


async def test_recruiter_cannot_link_twins(app_client: AsyncClient) -> None:
    _rec_id, rec = await _user(UserRole.recruiter)
    _hor_id, hor = await _user(UserRole.head_of_recruitment)
    a = await _job(dl_id=None)
    b = await _job(dl_id=None)
    async with AsyncSessionLocal() as db:
        (await db.get(Job, a)).recruiter_id = _rec_id
        (await db.get(Job, b)).recruiter_id = _rec_id
        await db.commit()
    refused = await app_client.post(
        f"/api/jobs/{a}/twins", headers=rec, json={"other_job_id": b}
    )
    assert refused.status_code == 403, refused.text
    view = await app_client.get(f"/api/jobs/{a}/twins", headers=rec)
    assert view.status_code == 200, view.text
    assert view.json()["can_manage"] is False
    assert (await app_client.get(f"/api/jobs/{a}/twins", headers=hor)).json()[
        "can_manage"
    ]


async def test_link_refuses_closed_request_and_a_fourth_twin(
    app_client: AsyncClient,
) -> None:
    _hor_id, hor = await _user(UserRole.head_of_recruitment)
    a = await _job(dl_id=None)
    closed = await _job(dl_id=None, status=JobStatus.closed)
    refused = await app_client.post(
        f"/api/jobs/{a}/twins", headers=hor, json={"other_job_id": closed}
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "twin_closed"

    for _ in range(job_twins.MAX_TWINS):
        other = await _job(dl_id=None)
        ok = await app_client.post(
            f"/api/jobs/{a}/twins", headers=hor, json={"other_job_id": other}
        )
        assert ok.status_code == 200, ok.text
    one_more = await _job(dl_id=None)
    full = await app_client.post(
        f"/api/jobs/{a}/twins", headers=hor, json={"other_job_id": one_more}
    )
    assert full.status_code == 422, full.text
    assert full.json()["detail"]["code"] == "twin_limit"


async def test_unlink_returns_to_similar_and_removes_nobody(
    app_client: AsyncClient,
) -> None:
    dl_id, dl = await _user(UserRole.delivery_lead)
    a = await _job(dl_id=dl_id)
    b = await _job(dl_id=dl_id)
    async with AsyncSessionLocal() as db:
        person = Candidate(name="Bliźniak", lastname=uuid.uuid4().hex[:8])
        db.add(person)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=person.id,
                job_id=b,
                stage=PipelineStage.verified,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        person_id = person.id
    await app_client.post(f"/api/jobs/{a}/twins", headers=dl, json={"other_job_id": b})
    gone = await app_client.delete(f"/api/jobs/{a}/twins/{b}", headers=dl)
    assert gone.status_code == 200, gone.text
    assert gone.json()["unlinked_now"] is True and gone.json()["twins"] == []
    assert {kind for kind, _ in (await _kinds(a, b)).values()} == {"similar"}
    async with AsyncSessionLocal() as db:
        still = await db.scalar(
            select(CandidateStage.id).where(
                CandidateStage.candidate_id == person_id, CandidateStage.job_id == b
            )
        )
    assert still is not None


async def test_rate_over_budget_is_refused_only_with_a_twin() -> None:
    a = await _job(dl_id=None, budget="110")
    b = await _job(dl_id=None, budget="120")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, a)
        # Bez bliźniaka — jak dotąd tylko ostrzeżenie w formularzu.
        await job_twins.assert_rate_within_budget(
            db, job=job, amount=Decimal("130"), unit="hourly", currency="PLN"
        )
    await _link_rows(a, b)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, a)
        await job_twins.assert_rate_within_budget(
            db, job=job, amount=Decimal("110"), unit="hourly", currency="PLN"
        )
        # 900 zł/dzień = 112,50 zł/h > 110.
        with pytest.raises(HTTPException) as over:
            await job_twins.assert_rate_within_budget(
                db, job=job, amount=Decimal("900"), unit="daily", currency="PLN"
            )
    assert over.value.status_code == 422
    assert over.value.detail["code"] == "twin_rate_over_budget"
    assert "110" in over.value.detail["message"]


async def test_question_groups_use_twin_pairs(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    a = await _job(dl_id=None, questions=ZOB_2947)
    b = await _job(dl_id=None, questions=ZOB_2964)
    before = await app_client.get(
        f"/api/screening-form/question-groups?job_ids={a}&job_ids={b}",
        headers=app_auth_headers,
    )
    assert before.status_code == 200, before.text
    assert len(before.json()["groups"]) == 8
    linked = await app_client.post(
        f"/api/jobs/{a}/twins",
        headers=app_auth_headers,
        json={
            "other_job_id": b,
            "question_pairs": [
                {"own": "q1", "other": "q2"},
                {"own": "q2", "other": "q1"},
                {"own": "q3", "other": "q3"},
            ],
        },
    )
    assert linked.status_code == 200, linked.text
    after = await app_client.get(
        f"/api/screening-form/question-groups?job_ids={b}&job_ids={a}",
        headers=app_auth_headers,
    )
    groups = after.json()["groups"]
    assert len(groups) == 5
    assert [
        {"job_id": b, "question_id": "q3"},
        {"job_id": a, "question_id": "q3"},
    ] in groups


async def test_hor_sees_suggestions_and_dismisses_a_pair(
    app_client: AsyncClient,
) -> None:
    _dl_id, dl = await _user(UserRole.delivery_lead)
    hor_id, hor = await _user(UserRole.head_of_recruitment)
    assert (
        await app_client.get("/api/job-twins/suggestions", headers=dl)
    ).status_code == 403
    listed = await app_client.get("/api/job-twins/suggestions", headers=hor)
    assert listed.status_code == 200, listed.text
    a = await _job(dl_id=None)
    b = await _job(dl_id=None)
    gone = await app_client.post(
        "/api/job-twins/dismiss", headers=hor, json={"job_ids": [b, a]}
    )
    assert gone.status_code == 200, gone.text
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(JobTwinDismissal).where(JobTwinDismissal.job_low_id == min(a, b))
            )
        ).scalar_one()
    assert (row.job_high_id, row.dismissed_by) == (max(a, b), hor_id)


async def test_open_similar_puts_p1_first_and_marks_who_can_link(
    app_client: AsyncClient, monkeypatch
) -> None:
    from tests.test_job_similar_links import force_lexical_similarity
    from app.services import job_similarity as sim

    force_lexical_similarity(monkeypatch)
    sim.reset_pool_cache()
    dl_id, dl = await _user(UserRole.delivery_lead)
    other_dl_id, _ = await _user(UserRole.delivery_lead)
    tag = uuid.uuid4().hex[:6]

    async def job(dl: int, priority: JobPriority, status=JobStatus.published) -> int:
        job_id = await _job(dl_id=dl, priority=priority, status=status)
        async with AsyncSessionLocal() as db:
            row = await db.get(Job, job_id)
            row.title = f"Kotlin Kafka Engineer {tag}"
            row.must_skills = ["Kotlin", "Kafka", "Spring Boot"]
            await db.commit()
        return job_id

    a = await job(dl_id, JobPriority.medium)
    own = await job(dl_id, JobPriority.medium)
    foreign_p1 = await job(other_dl_id, JobPriority.urgent)
    closed = await job(dl_id, JobPriority.medium, status=JobStatus.closed)
    sim.reset_pool_cache()
    got = await app_client.get(f"/api/jobs/{a}/open-similar", headers=dl)
    assert got.status_code == 200, got.text
    items = [i for i in got.json()["items"] if i["id"] in {own, foreign_p1, closed}]
    assert [i["id"] for i in items] == [foreign_p1, own]
    assert items[0]["p1"] is True and items[0]["can_twin"] is False
    assert items[1]["can_twin"] is True


# ── Bramka „Zweryfikowany” ──────────────────────────────────────────────────


@pytest.fixture
def dl_skips_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "VERIFIED_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "DL_SKIPS_FILL_GATES", True)


async def test_verified_needs_the_twin_screening_or_a_skip_reason(dl_skips_on) -> None:
    from httpx import ASGITransport

    from app.core.rate_limit import limiter as _limiter
    from app.main import app
    from tests.test_board_tasks import (
        _cleanup,
        _login,
        _seed_user,
        _seed_world,
        seed_entry_row,
    )

    _limiter.enabled = False
    world = await _seed_world()
    twin = await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        dl = await _login(client, dl_creds)
        try:
            await seed_entry_row(world["candidate_id"], world["job_id"])
            await _link_rows(world["job_id"], twin["job_id"])
            body = {
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["verified"],
            }
            refused = await client.post("/api/pipeline/move", headers=dl, json=body)
            assert refused.status_code == 409, refused.text
            detail = refused.json()["detail"]
            assert detail["code"] == "TWIN_SCREENING_REQUIRED"
            assert [t["job_id"] for t in detail["twins"]] == [twin["job_id"]]

            bad = await client.post(
                "/api/pipeline/move",
                headers=dl,
                json={**body, "twin_skips": {str(twin["job_id"]): "bo tak"}},
            )
            assert bad.status_code == 409, bad.text

            moved = await client.post(
                "/api/pipeline/move",
                headers=dl,
                json={
                    **body,
                    "twin_skips": {str(twin["job_id"]): "candidate_declined"},
                },
            )
            assert moved.status_code == 200, moved.text
            async with AsyncSessionLocal() as db:
                trace = (
                    await db.execute(
                        select(Activity).where(
                            Activity.action == "job_twin_skipped",
                            Activity.entity_id == world["candidate_id"],
                        )
                    )
                ).scalar_one()
            assert trace.details["twin_job_id"] == twin["job_id"]
            assert trace.details["reason"] == "candidate_declined"
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(Activity).where(
                        Activity.action == "job_twin_skipped",
                        Activity.entity_id == world["candidate_id"],
                    )
                )
                await db.execute(
                    delete(JobSimilarLink).where(
                        JobSimilarLink.job_id.in_([world["job_id"], twin["job_id"]])
                    )
                )
                await db.commit()
            await _cleanup(world, [dl_id])


async def test_person_rejected_in_the_twin_does_not_block(dl_skips_on) -> None:
    from httpx import ASGITransport

    from app.core.rate_limit import limiter as _limiter
    from app.main import app
    from tests.test_board_tasks import (
        _cleanup,
        _login,
        _seed_user,
        _seed_world,
        seed_entry_row,
    )

    _limiter.enabled = False
    world = await _seed_world()
    twin = await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        dl = await _login(client, dl_creds)
        try:
            await seed_entry_row(world["candidate_id"], world["job_id"])
            await _link_rows(world["job_id"], twin["job_id"])
            async with AsyncSessionLocal() as db:
                db.add(
                    CandidateStage(
                        candidate_id=world["candidate_id"],
                        job_id=twin["job_id"],
                        stage=PipelineStage.rejected,
                        moved_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                    )
                )
                await db.commit()
            moved = await client.post(
                "/api/pipeline/move",
                headers=dl,
                json={
                    "candidate_id": world["candidate_id"],
                    "job_id": world["job_id"],
                    "stage_def_id": world["defs"]["verified"],
                },
            )
            assert moved.status_code == 200, moved.text
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(JobSimilarLink).where(
                        JobSimilarLink.job_id.in_([world["job_id"], twin["job_id"]])
                    )
                )
                await db.commit()
            await _cleanup(world, [dl_id])
