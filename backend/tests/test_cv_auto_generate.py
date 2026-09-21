"""Auto-CV po ruchu na „Zweryfikowany" (21.09.2026) — prawdziwy Postgres.

Kontrakty:

- ruch NIGDY nie zależy od automatu: wyłącznik OFF = zero efektu, wyjątek przy
  odpalaniu zadania nie zmienia odpowiedzi 200, inne etapy niczego nie odpalają;
- reguła klienta wymagająca wejść nie jest omijana: wymagany zrzut zgody RODO
  = pominięcie z kodem powodu BEZ wołania generatora; odmowa 422 ze wspólnej
  ścieżki walidacji = pominięcie z komunikatem;
- idempotencja (etap × wersja CV): drugi ruch nie generuje drugi raz, a baza
  pilnuje tego częściowym UNIQUE-em (ręczne wiersze nietknięte);
- każda awaria kończy się logiem i Activity, nigdy wyjątkiem u wołającego;
- lustro DDL 0332 jest w ``entrypoint.sh``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import cv_auto_generate as auto
from tests.test_pending_gate_removed import (  # noqa: F401  (fixture pv_client)
    _login,
    _seed_candidate,
    _seed_job,
    _seed_user,
    pv_client,
)

_BACKEND = Path(__file__).resolve().parents[1]


async def _world(*, with_cv: bool = True, role: UserRole = UserRole.recruiter) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"cv-auto-{tag}@example.com",
            name="CV Auto",
            role=role,
            is_active=True,
        )
        client = Client(name=f"CV auto client {tag}")
        db.add_all([user, client])
        await db.flush()
        job = Job(
            title=f"CV auto job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            recruiter_id=user.id,
        )
        candidate = Candidate(
            name="Auto",
            lastname=f"CV{tag}",
            cv_extracted_data={"cv_highlights": {"source_hash": f"hash-{tag}"}},
        )
        db.add_all([job, candidate])
        await db.flush()
        if with_cv:
            db.add(
                CandidateDocument(
                    candidate_id=candidate.id, filename="cv.pdf", is_primary=True
                )
            )
        stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.verified,
            moved_by=user.id,
        )
        db.add(stage)
        await db.commit()
        return {
            "user_id": user.id,
            "job_id": job.id,
            "client_id": client.id,
            "candidate_id": candidate.id,
            "stage_id": stage.id,
            "revision": f"hash-{tag}",
        }


async def _events(job_id: int) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Activity)
                    .where(
                        Activity.entity_type == auto.ACTIVITY_ENTITY,
                        Activity.entity_id == job_id,
                    )
                    .order_by(Activity.id)
                )
            ).all()
        )


def _fake_generator(monkeypatch, *, error: HTTPException | None = None) -> list[dict]:
    """Podstaw wspólną ścieżkę generacji: bez magazynu plików i bez modelu."""
    from app.api import cv_generator_b2b as api

    calls: list[dict] = []

    async def _enqueue(db, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        generated_id = await api._create_pending_row(
            db,
            mode="new",
            candidate_id=kwargs["candidate"].id,
            candidate_name="Auto CV",
            position=None,
            language=kwargs["language"],
            blind_cv=kwargs["blind_cv"],
            user_id=kwargs["user_id"],
            content_mode=kwargs["content_mode"],
            client_id=kwargs["client_id"],
            job_id=kwargs["stage"].job_id,
            origin=kwargs["origin"],
            stage_id=kwargs["stage"].id,
            source_cv_revision=kwargs["source_cv_revision"],
        )
        return generated_id, 4242, "Auto CV"

    monkeypatch.setattr(api, "enqueue_candidate_generation", _enqueue)
    return calls


# ── ruch nie zależy od automatu ─────────────────────────────────────────────


async def _move(client: AsyncClient, headers, cand_id, job_id, stage="verified"):
    return await client.post(
        "/api/pipeline/move",
        headers=headers,
        json={"candidate_id": cand_id, "job_id": job_id, "stage": stage},
    )


@pytest.mark.asyncio
async def test_move_spawns_only_for_verified_and_only_when_enabled(
    pv_client: AsyncClient,
    monkeypatch,  # noqa: F811
):
    from app.api import pipeline

    spawned: list[str] = []

    def _spawn(coro, label):
        coro.close()
        spawned.append(label)

    monkeypatch.setattr(pipeline, "_spawn", _spawn)
    uid, email, pw = await _seed_user(UserRole.recruiter, "cvauto")
    headers = await _login(pv_client, email, pw)
    job_id = await _seed_job(recruiter_id=uid)

    monkeypatch.setattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", False)
    off = await _move(pv_client, headers, await _seed_candidate(), job_id)
    assert off.status_code == 200, off.text
    assert spawned == []  # wyłącznik OFF = stan sprzed automatu

    monkeypatch.setattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", True)
    other = await _move(
        pv_client, headers, await _seed_candidate(), job_id, stage="screening"
    )
    assert other.status_code == 200, other.text
    assert spawned == []

    on = await _move(pv_client, headers, await _seed_candidate(), job_id)
    assert on.status_code == 200, on.text
    assert spawned == [f"cv_auto_generate stage={on.json()['id']}"]


@pytest.mark.asyncio
async def test_move_survives_a_broken_automation(
    pv_client: AsyncClient,
    monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", True)

    def _boom(**kwargs):
        raise RuntimeError("automation exploded")

    monkeypatch.setattr(auto, "generate_after_verified", _boom)
    uid, email, pw = await _seed_user(UserRole.recruiter, "cvboom")
    headers = await _login(pv_client, email, pw)
    job_id = await _seed_job(recruiter_id=uid)
    response = await _move(pv_client, headers, await _seed_candidate(), job_id)
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == "verified"


def test_bulk_move_does_not_trigger_generation():
    import ast

    tree = ast.parse((_BACKEND / "app" / "api" / "pipeline.py").read_text("utf-8"))
    users = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and "cv_auto_generate" in ast.unparse(node)
    ]
    assert users == ["move_candidate"]


# ── pominięcia ──────────────────────────────────────────────────────────────


async def test_kill_switch_makes_the_task_a_no_op(monkeypatch):
    world = await _world()
    calls = _fake_generator(monkeypatch)
    monkeypatch.setattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", False)
    await auto.generate_after_verified(
        stage_id=world["stage_id"], user_id=world["user_id"]
    )
    assert calls == [] and await _events(world["job_id"]) == []


async def test_candidate_without_cv_is_skipped_with_a_reason(monkeypatch):
    world = await _world(with_cv=False)
    calls = _fake_generator(monkeypatch)
    async with AsyncSessionLocal() as db:
        assert (
            await auto._enqueue(
                db, stage_id=world["stage_id"], user_id=world["user_id"]
            )
            is None
        )
    [event] = await _events(world["job_id"])
    assert (event.action, event.details["reason"]) == (
        auto.ACTION_SKIPPED,
        "no_cv_document",
    )
    assert calls == []


async def test_required_consent_screenshot_is_never_bypassed(monkeypatch):
    from app.services.cv_generator_b2b import client_rules

    world = await _world()
    calls = _fake_generator(monkeypatch)

    async def _rule(db, client_id):
        return object()

    monkeypatch.setattr(client_rules, "resolve_client_rule", _rule)
    monkeypatch.setattr(
        client_rules,
        "snapshot_rule",
        lambda rule: SimpleNamespace(
            requires_rodo_consent_block=True, cv_language="pl", content_mode=None
        ),
    )
    async with AsyncSessionLocal() as db:
        result = await auto._enqueue(
            db, stage_id=world["stage_id"], user_id=world["user_id"]
        )
    assert result is None
    # Generator nie został nawet zawołany — więc nic nie naliczono.
    assert calls == []
    [event] = await _events(world["job_id"])
    assert event.details["reason"] == "consent_screenshot_required"
    assert event.details["candidate_id"] == world["candidate_id"]
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CvGeneratedDocument.id).where(
                    CvGeneratedDocument.stage_id == world["stage_id"]
                )
            )
        ) is None


async def test_shared_validation_refusal_becomes_a_skip(monkeypatch):
    world = await _world()
    _fake_generator(
        monkeypatch,
        error=HTTPException(422, "Reguła klienta wymaga numeru projektu."),
    )
    async with AsyncSessionLocal() as db:
        assert (
            await auto._enqueue(
                db, stage_id=world["stage_id"], user_id=world["user_id"]
            )
            is None
        )
    [event] = await _events(world["job_id"])
    assert event.action == auto.ACTION_SKIPPED
    assert event.details["reason"] == "client_rule_inputs_missing"
    assert "numeru projektu" in event.details["detail"]


async def test_automation_uses_the_single_shared_validation_path():
    """Automat nie ma własnej kopii walidacji reguł klienta."""
    source = (_BACKEND / "app" / "services" / "cv_auto_generate.py").read_text("utf-8")
    assert "enqueue_candidate_generation" in source
    assert "persist_job" not in source and "required_input_problems" not in source
    api = (_BACKEND / "app" / "api" / "cv_generator_b2b.py").read_text("utf-8")
    shared = api[api.index("async def enqueue_candidate_generation") :]
    shared = shared[: shared.index('@router.post(\n    "/generate"')]
    # Wszystkie odmowy stoją PRZED naliczeniem kwoty.
    for guard in ("_verified_consent(", "required_input_problems(", "validate_cv_file"):
        assert shared.index(guard) < shared.index("_charge_cv_generation_quota")


# ── idempotencja ────────────────────────────────────────────────────────────


async def test_second_move_with_the_same_cv_does_not_generate_again(monkeypatch):
    world = await _world()
    calls = _fake_generator(monkeypatch)
    async with AsyncSessionLocal() as db:
        first = await auto._enqueue(
            db, stage_id=world["stage_id"], user_id=world["user_id"]
        )
    async with AsyncSessionLocal() as db:
        second = await auto._enqueue(
            db, stage_id=world["stage_id"], user_id=world["user_id"]
        )
    assert first == 4242 and second is None
    assert len(calls) == 1
    call = calls[0]
    assert call["origin"] == "auto" and call["user_id"] == world["user_id"]
    assert call["source_cv_revision"] == world["revision"]
    assert (call["language"], call["blind_cv"]) == ("pl", False)
    # Automat nigdy nie podaje zrzutu zgody — nie ma go skąd wziąć.
    assert not call.get("consent_token") and not call.get("consent_key")
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(CvGeneratedDocument).where(
                    CvGeneratedDocument.stage_id == world["stage_id"]
                )
            )
        ).all()
        assert [(r.origin, r.source_cv_revision, r.created_by) for r in rows] == [
            ("auto", world["revision"], world["user_id"])
        ]
    events = await _events(world["job_id"])
    assert [e.action for e in events] == [auto.ACTION_STARTED]
    assert events[0].details["generated_id"] == rows[0].id


async def test_database_enforces_the_idempotency_key():
    world = await _world()

    def _row(origin: str) -> CvGeneratedDocument:
        return CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            candidate_name="x",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="",
            status="processing",
            origin=origin,
            stage_id=world["stage_id"],
            source_cv_revision=world["revision"],
        )

    async with AsyncSessionLocal() as db:
        db.add(_row("auto"))
        await db.commit()
        db.add(_row("auto"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
        # Ręczne dokumenty nie wchodzą do klucza.
        db.add_all([_row("manual"), _row("manual")])
        await db.commit()


# ── awarie ──────────────────────────────────────────────────────────────────


async def test_any_failure_is_swallowed_and_recorded(monkeypatch):
    world = await _world()

    async def _boom(db, *, stage_id, user_id):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", True)
    monkeypatch.setattr(auto, "_enqueue", _boom)
    await auto.generate_after_verified(
        stage_id=world["stage_id"], user_id=world["user_id"]
    )
    [event] = await _events(world["job_id"])
    assert (event.action, event.details["reason"]) == (
        auto.ACTION_FAILED,
        "RuntimeError",
    )


async def test_successful_enqueue_runs_the_durable_job(monkeypatch):
    from app.services.cv_generator_b2b import durable_jobs

    world = await _world()
    _fake_generator(monkeypatch)
    executed: list[int] = []

    async def _execute(job_id):
        executed.append(job_id)

    monkeypatch.setattr(durable_jobs, "execute_job", _execute)
    monkeypatch.setattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", True)
    await auto.generate_after_verified(
        stage_id=world["stage_id"], user_id=world["user_id"]
    )
    assert executed == [4242]


# ── lustro DDL ──────────────────────────────────────────────────────────────


def test_entrypoint_mirrors_migration_0332():
    import re

    raw = (_BACKEND / "entrypoint.sh").read_text("utf-8")
    text = " ".join(re.sub(r'"\s*\n\s*"', "", raw).split())
    for needle in (
        "ADD VALUE IF NOT EXISTS 'auto_match_proposals'",
        "ADD COLUMN IF NOT EXISTS origin VARCHAR(16) NOT NULL DEFAULT 'manual'",
        "ADD COLUMN IF NOT EXISTS stage_id INTEGER",
        "ADD COLUMN IF NOT EXISTS source_cv_revision VARCHAR(64)",
        "ck_cv_generated_documents_origin",
        "ux_cv_generated_documents_auto_stage_revision",
    ):
        assert needle in text, needle
    migration = (
        _BACKEND / "alembic" / "versions" / "0332_recruitment_automations.py"
    ).read_text("utf-8")
    assert 'down_revision = "0331_job_proposals"' in migration
