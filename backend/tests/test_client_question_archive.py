"""Archiwum pytań z rozmów u klienta (0383): docierają tylko po roli.

Excel rekruterów „Pytania z interview” to ~tysiąc pytań u jednego klienta
z kilkudziesięciu ról. Wgrany jako zwykłe pytania z debriefów dałby każdemu
prepowi ocenę „słaby” (ocena bierze 20 najnowszych pytań klienta bez filtra
roli) i zalał prep-kit. Te testy pilnują, że:

* listy „najnowsze N pytań klienta” (prep-kit, ocena prepu, Luna, panel
  debriefów) nie widzą archiwum;
* archiwum dociera przez technologie roli albo przez przypięcie do podobnej
  rekrutacji — z etykietą „archiwum” i bez zalewania listy;
* ocena prepu liczy pytanie z archiwum dopiero, gdy człowiek je przypnie;
* Baza pytań domyślnie go nie pokazuje, kopia rekrutacji z szablonu go nie
  kopiuje, a pytanie zadane znowu w debriefie staje się debriefem.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.client import Client
from app.models.competence_category import CompetenceCategory
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
    JobQuestionAddedBySource,
)
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services import scoring_service

JAVA_Q = "Jak działa garbage collector w Javie?"
ORACLE_Q = "Jak stroisz wolne zapytania w Oracle?"
GENERIC_Q = "Opowiedz o najtrudniejszym projekcie."


@pytest.fixture(autouse=True)
def _taxonomy():
    saved = dict(scoring_service.ALIAS_MAP)
    scoring_service.set_alias_map(
        {"java": "java", "javie": "java", "oracle": "oracle", "kafka": "kafka"}
    )
    yield
    scoring_service.set_alias_map(saved)


def _hash(text: str) -> str:
    return hashlib.sha256(
        re.sub(r"\s+", " ", text.strip().lower()).encode()
    ).hexdigest()


async def _client(db, tag: str) -> Client:
    client = Client(name=f"ArchiveClient-{tag}-{uuid.uuid4().hex[:6]}")
    db.add(client)
    await db.flush()
    return client


async def _question(db, client_id: int, text: str, tags: list[str], source=None):
    q = InterviewQuestion(
        text=text,
        client_id=client_id,
        source=source or InterviewQuestionSource.legacy_import,
        normalized_text_hash=_hash(text),
        skill_tags=tags,
    )
    db.add(q)
    await db.flush()
    return q


async def _world() -> dict:
    """Klient A: archiwum Java/Oracle/ogólne. Klient B: archiwum Java."""
    async with AsyncSessionLocal() as db:
        a = await _client(db, "A")
        b = await _client(db, "B")
        java = await _question(db, a.id, JAVA_Q, ["java"])
        oracle = await _question(db, a.id, ORACLE_Q, ["oracle"])
        generic = await _question(db, a.id, GENERIC_Q, [])
        other = await _question(db, b.id, "Czym jest JVM w Javie?", ["java"])
        job = Job(
            title="Java Developer",
            status=JobStatus.published,
            client_id=a.id,
            must_skills=["Java"],
        )
        db.add(job)
        await db.commit()
        return {
            "a": a.id,
            "b": b.id,
            "java": java.id,
            "oracle": oracle.id,
            "generic": generic.id,
            "other": other.id,
            "job": job.id,
        }


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"archive-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"Arch1ve_{tag}!pw"),
            name=f"Archive {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return uid, {
        "Authorization": f"Bearer {create_access_token(uid, role.value, roles=[role.value])}"
    }


# ── Lustro migracji ──────────────────────────────────────────────────────────


def test_migration_is_mirrored_in_entrypoint():
    backend = Path(__file__).resolve().parents[1]
    entry = re.sub(r"\s+", " ", (backend / "entrypoint.sh").read_text())
    migration = (
        backend / "alembic/versions/0383_legacy_interview_questions.py"
    ).read_text()
    for needle in (
        "ALTER TYPE interviewquestionsource ADD VALUE IF NOT EXISTS 'legacy_import'",
        "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'interview_question_import'",
    ):
        assert needle in migration, needle
        assert needle in entry, needle


# ── Wybór po roli ────────────────────────────────────────────────────────────


async def test_selector_returns_only_this_clients_questions_about_the_role():
    from app.services.client_question_archive import archive_questions_for_role
    from app.services.question_suggestions import job_requirement_names

    w = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, w["job"])
        matches = await archive_questions_for_role(
            db, client_id=w["a"], requirement_names=job_requirement_names(job)
        )
        # Pytanie bez technologii nie wchodzi tą drogą — nie mówi nic o roli.
        assert [m.question.id for m in matches] == [w["java"]]
        assert matches[0].matched == ("java",)
        assert (
            await archive_questions_for_role(
                db, client_id=w["a"], requirement_names=set()
            )
            == []
        )
        assert (
            await archive_questions_for_role(
                db, client_id=None, requirement_names={"java"}
            )
            == []
        )


async def test_newest_n_readers_never_see_the_archive(app_client: AsyncClient):
    from app.services import prep_review
    from app.services.champion_client_context import debrief_questions
    from app.services.question_suggestions import _tier_client_debrief

    w = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, w["job"])
        assert await _tier_client_debrief(db, job) == []
        assert await debrief_questions(db, w["a"]) == []
        items = await prep_review.build_items(db, job)
        assert not [i for i in items if i.kind == "question"]

    _, rec_h = await _user(UserRole.admin)
    resp = await app_client.get(
        f"/api/interview-cycle/client-questions?job_id={w['job']}", headers=rec_h
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_prep_review_counts_an_archive_question_only_once_pinned():
    from app.services import prep_review

    w = await _world()
    # Przypięcie przez człowieka niesie jego id (API zawsze je zapisuje) —
    # przypięcie importu bez człowieka ocena prepu pomija (audyt runda 4).
    pinned_by, _ = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        db.add(
            JobQuestion(
                job_id=w["job"],
                question_id=w["oracle"],
                is_pinned=True,
                added_by_source=JobQuestionAddedBySource.manual,
                added_by_user_id=pinned_by,
            )
        )
        await db.commit()
        job = await db.get(Job, w["job"])
        items = await prep_review.build_items(db, job)
    assert [i.key for i in items if i.kind == "question"] == [f"q:{w['oracle']}"]


# ── Prep-kit ─────────────────────────────────────────────────────────────────


async def test_prep_kit_shows_archive_by_role_with_its_own_label():
    from app.services.question_suggestions import suggest_questions_for_prep

    w = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, w["job"])
        result = await suggest_questions_for_prep(db, job, target_count=5)
    tiers = {q.text: q.source_tier for q in result.questions}
    assert tiers.get(JAVA_Q) == "client_archive"
    assert ORACLE_Q not in tiers
    assert GENERIC_Q not in tiers
    assert "Czym jest JVM w Javie?" not in tiers  # inny klient


async def test_similar_job_archive_is_labelled_and_capped(monkeypatch):
    from app.services import question_suggestions as qs

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cc = CompetenceCategory(
            slug=f"arch-{tag}",
            name_pl="Test archiwum",
            name_en="Archive test",
            description="test",
            keywords=[],
        )
        client = await _client(db, "S")
        db.add(cc)
        await db.flush()
        old = Job(
            title="Stara rola",
            status=JobStatus.closed,
            client_id=client.id,
            competence_category_id=cc.id,
        )
        new = Job(
            title="Nowa rola",
            status=JobStatus.published,
            client_id=client.id,
            competence_category_id=cc.id,
        )
        db.add_all([old, new])
        await db.flush()
        for n in range(30):
            q = await _question(db, client.id, f"Opowiedz o sytuacji {n} {tag}.", [])
            db.add(
                JobQuestion(
                    job_id=old.id,
                    question_id=q.id,
                    is_pinned=True,
                    added_by_source=JobQuestionAddedBySource.manual,
                    order_index=float(n),
                )
            )
        await db.commit()
        old_id, new_id = old.id, new.id

    async def fake_similar(job_id, top_k, exclude_self):
        return [{"job_id": old_id, "score": 0.93}]

    monkeypatch.setattr(qs, "search_similar_jobs_by_job_id", fake_similar)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, new_id)
        result = await qs.suggest_questions_for_prep(db, job, target_count=5)
    archive = [q for q in result.questions if q.source_tier == "client_archive"]
    assert len(archive) == 5, [q.source_tier for q in result.questions]
    assert len(result.questions) == 5


# ── Trasy ────────────────────────────────────────────────────────────────────


async def test_archive_endpoint_lists_questions_for_the_role(app_client: AsyncClient):
    w = await _world()
    _, headers = await _user(UserRole.admin)
    resp = await app_client.get(
        f"/api/interview-cycle/client-questions/archive?job_id={w['job']}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == [{"id": w["java"], "text": JAVA_Q, "matched": ["java"]}]


async def test_question_bank_hides_archive_unless_asked(app_client: AsyncClient):
    w = await _world()
    _, headers = await _user(UserRole.admin)
    base = f"/api/interview-questions?client_id={w['a']}&limit=200"
    default = await app_client.get(base, headers=headers)
    assert default.status_code == 200, default.text
    assert w["java"] not in {q["id"] for q in default.json()}
    full = await app_client.get(f"{base}&include_archive=true", headers=headers)
    rows = {q["id"]: q["source"] for q in full.json()}
    assert rows.get(w["java"]) == "legacy_import"


async def test_template_copy_skips_archive_pins(
    app_client: AsyncClient, app_auth_headers
):
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = await _client(db, "T")
        src = Job(title=f"Szablon {tag}", status=JobStatus.closed, client_id=client.id)
        db.add(src)
        await db.flush()
        legacy = await _question(db, client.id, f"Pytanie z archiwum {tag}?", [])
        manual = await _question(
            db,
            client.id,
            f"Pytanie przypięte ręcznie {tag}?",
            [],
            source=InterviewQuestionSource.manual,
        )
        for q in (legacy, manual):
            db.add(
                JobQuestion(
                    job_id=src.id,
                    question_id=q.id,
                    is_pinned=True,
                    added_by_source=JobQuestionAddedBySource.manual,
                )
            )
        await db.commit()
        src_id, client_id, manual_id = src.id, client.id, manual.id

    resp = await app_client.post(
        "/api/jobs",
        json={
            "title": f"Kopia {tag}",
            "client_id": client_id,
            "from_job_id": src_id,
            "copy_questions": True,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        copied = (
            (
                await db.execute(
                    select(JobQuestion.question_id).where(
                        JobQuestion.job_id == resp.json()["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert copied == [manual_id]


async def test_debrief_repeating_an_archive_question_makes_it_a_debrief():
    from app.api.interview_cycle import _save_client_questions

    w = await _world()
    user_id, _ = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        saved = await _save_client_questions(
            db,
            questions=[ORACLE_Q],
            client_id=w["a"],
            job_id=w["job"],
            user_id=user_id,
        )
        await db.commit()
        row = await db.get(InterviewQuestion, w["oracle"])
    assert saved == 1
    assert row.source == InterviewQuestionSource.client_debrief


async def test_luna_context_gets_archive_only_for_request_technologies():
    from app.services.champion_client_context import archive_questions_for_request

    w = await _world()
    async with AsyncSessionLocal() as db:
        found = await archive_questions_for_request(
            db, w["a"], "Szukamy doświadczonego programisty Java do banku."
        )
        none = await archive_questions_for_request(
            db, w["a"], "Szukamy analityka biznesowego."
        )
    assert found == [JAVA_Q]
    assert none == []
