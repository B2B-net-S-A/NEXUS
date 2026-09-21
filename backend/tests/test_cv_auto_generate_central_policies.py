"""Auto-CV po „Zweryfikowany" pod CENTRALNYMI regułami CV (0331) — prawdziwy Postgres.

`enqueue_candidate_generation` jest wspólne dla kliknięcia rekrutera
(`POST /generate`) i automatu. Te testy przechodzą przez PRAWDZIWĄ wspólną
ścieżkę (bez podmiany `enqueue_candidate_generation`) — podstawione są tylko
magazyn plików, kwota AI i worker.

Kontrakty:

- z flagą `CV_CENTRAL_POLICIES_ENABLED` automat generuje w trybie i języku
  ustalonym centralnie i stempluje `central_policy` DOKŁADNIE tak jak ręczna
  generacja dla tej samej pary (kandydat, rekrutacja);
- wymóg, którego automat nie ma skąd spełnić (zrzut zgody, numer projektu),
  to POMINIĘCIE z kodem powodu: bez naliczenia AI i bez wiersza dokumentu.
  Centralny przepływ sprawdza je dopiero przy gotowości pakietu, a zapadają
  przy generacji — dokument byłby na zawsze szkicem nie do udostępnienia;
- polityka czekająca na synchronizację (503) to pominięcie, nie „awaria";
- z flagą wyłączoną zachowanie jest takie jak przed centralnymi regułami.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
import json
import uuid

import pytest
from docx import Document
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.api import cv_generator_b2b as api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_document import CandidateDocument
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.services import cv_auto_generate as auto
from app.services.cv_generator_b2b import central_policies as policies
from app.services.cv_generator_b2b import durable_jobs
from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt
from app.services.cv_generator_b2b.standalone_service import (
    CandidateGenerationSource,
)
from tests.test_cv_auto_generate import _events, _headers, _world
from tests.test_pending_gate_removed import pv_client  # noqa: F401


def _docx() -> bytes:
    document = Document()
    document.add_paragraph("Synthetic Person. Developer. Python.")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _stub_generation(monkeypatch, world: dict) -> dict:
    """Prawdziwa wspólna ścieżka; bez magazynu plików, kwoty AI i workera."""
    seen: dict = {"charges": [], "persisted": [], "executed": []}
    cv_bytes = _docx()

    async def _load(db, *, candidate_id, stage_id, language, cv_document_id):
        return CandidateGenerationSource(
            cv_bytes=cv_bytes,
            cv_filename="cv.docx",
            champion_json=json.dumps(asdict(ChampionProfileForPrompt())),
            has_champion=False,
            screening_notes_text="",
            source_warnings=(),
            fallback_name="Auto CV",
            job_id=world["job_id"],
            job_title="CV auto job",
            client_content_mode_cap=None,
            candidate_id=candidate_id,
            stage_id=stage_id,
            cv_document_id=cv_document_id,
            client_id=world["client_id"],
        )

    async def _charge(db, user_id):
        seen["charges"].append(user_id)

    async def _persist(db, **kwargs):
        await kwargs["charge"]()
        seen["persisted"].append(kwargs)
        return 9000 + len(seen["persisted"])

    async def _execute(job_id):
        seen["executed"].append(job_id)

    monkeypatch.setattr(api, "load_candidate_generation_source", _load)
    monkeypatch.setattr(api, "_charge_cv_generation_quota", _charge)
    monkeypatch.setattr(durable_jobs, "persist_job", _persist)
    monkeypatch.setattr(durable_jobs, "execute_job", _execute)
    return seen


async def _publish_policy(monkeypatch, world: dict, **overrides) -> dict:
    """Opublikuj centralną politykę dla klienta testowego PRAWDZIWĄ synchronizacją."""
    external_id = f"cv-auto-cp-{uuid.uuid4().hex}"
    entry = {
        **policies.policy_for(None),
        "key": f"test-policy-{world['client_id']}",
        "client_id": world["client_id"],
        "external_source": "traffit",
        "external_id": external_id,
        **overrides,
    }
    monkeypatch.setattr(policies, "catalog", lambda: (entry,))
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, world["client_id"])
        client.external_source = "traffit"
        client.external_id = external_id
        client.hidden = False
        await db.commit()
        assert await policies.synchronize(db) == 1
    return entry


async def _documents(world: dict) -> list[CvGeneratedDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CvGeneratedDocument)
                    .where(CvGeneratedDocument.candidate_id == world["candidate_id"])
                    .order_by(CvGeneratedDocument.id)
                )
            ).all()
        )


async def _cv_document_id(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateDocument.id).where(
                CandidateDocument.candidate_id == world["candidate_id"]
            )
        )


async def _run_automation(world: dict):
    async with AsyncSessionLocal() as db:
        return await auto._enqueue(
            db, stage_id=world["stage_id"], user_id=world["user_id"]
        )


async def _generate_manually(client: AsyncClient, world: dict, **payload):
    return await client.post(
        "/api/cv-generator/generate",
        headers=_headers(world["user_id"]),
        json={
            "candidate_id": world["candidate_id"],
            "stage_id": world["stage_id"],
            "cv_document_id": await _cv_document_id(world),
            **payload,
        },
    )


# ── (1) parytet z ręczną ścieżką ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_automation_matches_the_manual_path_under_central_policies(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    # Sufit klienta „basic": tryb MUSI wyjść z `central_policies.automatic_mode`
    # (polished → przycięty do basic), a nie z domyślnego trybu automatu.
    async with AsyncSessionLocal() as db:
        (await db.get(Client, world["client_id"])).cv_content_mode_cap = "basic"
        await db.commit()
    policy = await _publish_policy(monkeypatch, world, cv_language="en")
    seen = _stub_generation(monkeypatch, world)

    queued = await _run_automation(world)
    assert queued is not None
    # Rekruter prosi o „polished" — centralna polityka i tak wygrywa.
    manual = await _generate_manually(pv_client, world, content_mode="polished")
    assert manual.status_code == 202, manual.text

    auto_row, manual_row = await _documents(world)
    assert (auto_row.origin, manual_row.origin) == ("auto", "manual")
    assert manual_row.id == manual.json()["id"] and queued[1] == auto_row.id
    for row in (auto_row, manual_row):
        assert (row.language, row.content_mode, row.blind) == ("en", "basic", False)
        assert row.client_id == world["client_id"]
        assert row.job_id == world["job_id"]
    # Ten sam stempel polityki — łącznie z wersją publikacji, etapem i numerem.
    assert auto_row.central_policy == manual_row.central_policy
    stamp = auto_row.central_policy
    assert stamp["key"] == policy["key"]
    assert stamp["required_languages"] == ["en"]
    assert stamp["stage_id"] == world["stage_id"]
    assert stamp["project_ref"] == ""
    assert stamp["publication_version"] >= 1
    assert "external_id" not in stamp and "external_source" not in stamp
    # Worker dostaje te same centralnie ustalone wartości w obu ścieżkach.
    auto_job, manual_job = seen["persisted"]
    for job in (auto_job, manual_job):
        assert (job["inputs"]["language"], job["inputs"]["content_mode"]) == (
            "en",
            "basic",
        )
        assert job["inputs"]["consent_screenshot"] is None
    assert seen["charges"] == [world["user_id"], world["user_id"]]
    assert [e.action for e in await _events(world["job_id"])] == [auto.ACTION_STARTED]


async def test_client_outside_the_catalog_gets_the_standard_stamp(monkeypatch):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    monkeypatch.setattr(policies, "catalog", lambda: ())
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is not None
    [row] = await _documents(world)
    assert (row.origin, row.language, row.content_mode) == ("auto", "pl", "polished")
    assert row.central_policy["key"] == "standard"
    assert row.central_policy["publication_version"] == 0
    assert row.central_policy["required_languages"] == ["pl"]
    assert seen["charges"] == [world["user_id"]]


# ── (2) wymóg, którego automat nie spełni = pominięcie ──────────────────────


async def _assert_skipped(world: dict, seen: dict, *, reason: str) -> dict:
    assert seen["charges"] == [] and seen["persisted"] == []
    assert await _documents(world) == []
    [event] = await _events(world["job_id"])
    assert (event.action, event.details["reason"]) == (auto.ACTION_SKIPPED, reason)
    assert event.details["candidate_id"] == world["candidate_id"]
    assert event.details["stage_id"] == world["stage_id"]
    return event.details


async def test_central_consent_requirement_is_never_bypassed(monkeypatch):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    # Lustro PKO BP: zgoda + numer zapytania.
    await _publish_policy(
        monkeypatch,
        world,
        cv_language="pl",
        requires_rodo_consent_block=True,
        require_project_ref=True,
        filename_pattern="ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
    )
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is None
    await _assert_skipped(world, seen, reason="consent_screenshot_required")


async def test_central_project_ref_requirement_is_a_skip_not_a_dead_draft(
    monkeypatch,
):
    """Energa/Orlen: numer projektu bez zgody. Wspólna ścieżka pod centralnymi
    regułami go NIE wymaga (recepta ma ``require_project_ref=False``), wymaga
    go dopiero gotowość pakietu — a numer zapada przy generacji."""
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    await _publish_policy(
        monkeypatch,
        world,
        cv_language="pl",
        require_project_ref=True,
        filename_pattern="ENERGA_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
    )
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is None
    details = await _assert_skipped(world, seen, reason="client_rule_inputs_missing")
    assert "numeru projektu" in details["detail"]


def test_every_catalog_policy_requiring_automation_inputs_is_covered():
    """Katalog produkcyjny: każda polityka z wymogiem zgody albo numeru projektu
    trafia w jedną z dwóch bramek automatu (flagi czytane z tych samych pól)."""
    gated = [
        p
        for p in policies.catalog()
        if p["requires_rodo_consent_block"] or p["require_project_ref"]
    ]
    assert {p["client_id"] for p in gated} >= {26, 35, 41}
    for policy in gated:
        assert (
            policies.recipe_for(policy)["requires_rodo_consent_block"]
            == (policy["requires_rodo_consent_block"])
        )
        assert (
            policies.metadata(policy)["require_project_ref"]
            == (policy["require_project_ref"])
        )


async def test_policy_awaiting_synchronisation_is_a_skip_not_a_failure(monkeypatch):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    # Klient w katalogu, ale bez opublikowanego wiersza reguły → resolver 503.
    entry = {
        **policies.policy_for(None),
        "key": "test-unsynced",
        "client_id": world["client_id"],
    }
    monkeypatch.setattr(policies, "catalog", lambda: (entry,))
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is None
    details = await _assert_skipped(world, seen, reason="generation_unavailable")
    assert "synchronizację" in details["detail"]


# ── (3) flaga wyłączona = zachowanie sprzed centralnych reguł ───────────────


@pytest.mark.asyncio
async def test_disabled_central_policies_keep_the_previous_behaviour(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    # Wiersz centralnej polityki zostaje w bazie po wyłączeniu flagi: działa
    # wtedy jak zwykła zatwierdzona reguła (język EN), ale BEZ centralnego
    # stempla, trybu automatycznego i bramki numeru projektu z `managed_policy`.
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    await _publish_policy(
        monkeypatch, world, cv_language="en", require_project_ref=True
    )
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", False)
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is not None
    manual = await _generate_manually(pv_client, world, language="en")
    assert manual.status_code == 202, manual.text

    auto_row, manual_row = await _documents(world)
    for row in (auto_row, manual_row):
        assert (row.language, row.content_mode) == ("en", "polished")
        assert row.central_policy is None
    assert (auto_row.origin, auto_row.stage_id, auto_row.source_cv_revision) == (
        "auto",
        world["stage_id"],
        world["revision"],
    )
    assert seen["charges"] == [world["user_id"], world["user_id"]]
    assert [e.action for e in await _events(world["job_id"])] == [auto.ACTION_STARTED]


async def test_mode_is_decided_from_the_stage_recruitment(monkeypatch):
    """`automatic_mode` dostaje rekrutację ETAPU — nie dowolną kandydata."""
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    monkeypatch.setattr(policies, "catalog", lambda: ())
    _stub_generation(monkeypatch, world)
    seen_jobs: list[int | None] = []
    real = policies.automatic_mode

    def _spy(job, cap=None):
        seen_jobs.append(getattr(job, "id", None))
        return real(job, cap)

    monkeypatch.setattr(policies, "automatic_mode", _spy)
    assert await _run_automation(world) is not None
    assert seen_jobs == [world["job_id"]]
