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


# ── (4) klient dwujęzyczny: automat robi JEDNĄ wersję ───────────────────────

_BILINGUAL = dict(cv_language=None, requires_en_copy=True, auto_second_language=True)


async def test_bilingual_client_gets_one_charge_and_one_worker_job(monkeypatch):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    await _publish_policy(monkeypatch, world, **_BILINGUAL)
    seen = _stub_generation(monkeypatch, world)

    assert await _run_automation(world) is not None
    assert seen["charges"] == [world["user_id"]]
    [job] = seen["persisted"]
    assert job["inputs"]["languages"] == "primary_only"
    assert job["inputs"]["language"] == "pl"
    # Polityka nadal mówi prawdę: pakiet wymaga OBU wersji.
    [row] = await _documents(world)
    assert row.central_policy["required_languages"] == ["pl", "en"]


@pytest.mark.asyncio
async def test_manual_path_keeps_generating_both_languages(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    await _publish_policy(monkeypatch, world, **_BILINGUAL)
    seen = _stub_generation(monkeypatch, world)

    manual = await _generate_manually(pv_client, world)
    assert manual.status_code == 202, manual.text
    [job] = seen["persisted"]
    # Snapshot ręcznej generacji bez nowych pól — bajt w bajt jak dotąd.
    assert "languages" not in job["inputs"]
    assert "position_fallback" not in job["inputs"]


def _worker_harness(monkeypatch, *, first_ready: bool):
    """Worker `_run_generate_new_job` bez bazy i modelu (wzór: test ponowień)."""
    from datetime import date
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock, Mock

    from app.services.cv_generator_b2b import job_leases, requirement_map
    from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
    from app.services.cv_generator_b2b.job_snapshot import _encode
    from app.services.cv_generator_b2b.standalone_service import (
        GenerationResult,
        PreparedSourceFacts,
    )

    facts = PreparedSourceFacts("original source", "{}", "sha", "notes")
    primary = NS(
        id=11,
        language="pl",
        status="ready" if first_ready else "processing",
        central_policy={"required_languages": ["pl", "en"]},
        job_id=4,
        candidate_id=2,
        client_id=5,
        candidate_name="Synthetic Person",
        position="Developer",
    )
    job = NS(second_generated_id=None, prepared_source_facts=_encode(facts))
    db = AsyncMock()
    db.add = Mock()
    db.get.side_effect = lambda model, pk: primary if pk == 11 else None
    manager = Mock(
        __aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=None)
    )
    monkeypatch.setattr(api, "AsyncSessionLocal", lambda: manager)
    monkeypatch.setattr(job_leases, "lock_owned_job", AsyncMock(return_value=job))
    monkeypatch.setattr(job_leases, "register_second_document", AsyncMock())
    monkeypatch.setattr(requirement_map, "ensure_requirement_map", AsyncMock())
    monkeypatch.setattr(api, "prepare_source_facts", Mock(return_value=facts))
    second_quota = AsyncMock(
        return_value=api.QuotaState(1, 100, date(2026, 9, 1), str(uuid.uuid4()))
    )
    monkeypatch.setattr(api, "_charge_second_language_or_note", second_quota)
    monkeypatch.setattr(api, "_charge_final_review", AsyncMock(return_value=None))
    pending = AsyncMock(return_value=12)
    monkeypatch.setattr(api, "_create_pending_row", pending)
    monkeypatch.setattr(api, "_finalize_success", AsyncMock(return_value=True))
    rendered: list[dict] = []
    result = GenerationResult(
        candidate_name="Synthetic Person",
        filename="cv.docx",
        docx_bytes=b"docx",
        warnings=[],
        processing_time_ms=1,
        render_payload={},
        job_id=4,
    )

    async def _render(captured, **kwargs):
        rendered.append(kwargs)
        return result

    monkeypatch.setattr(api, "generate_cv_from_candidate_source", _render)
    rule = CvRuleSnapshot(
        filename_pattern=None,
        spaces_to_underscores=False,
        cv_language=None,
        requires_en_copy=True,
        requires_rodo_consent_block=False,
        auto_second_language=True,
    )
    return rule, rendered, second_quota, pending


async def _run_worker(rule, **extra):
    from tests.test_cv_enqueue_sources import source

    await api._run_generate_new_job(
        11,
        candidate_id=2,
        stage_id=3,
        language="pl",
        blind_cv=False,
        user_id=7,
        source=source(),
        rule_snapshot=rule,
        **extra,
    )


async def test_worker_first_pass_renders_only_the_primary_language(monkeypatch):
    rule, rendered, second_quota, pending = _worker_harness(
        monkeypatch, first_ready=False
    )
    await _run_worker(rule, languages="primary_only", position_fallback="Java Dev")
    assert [call["language"] for call in rendered] == ["pl"]
    assert rendered[0]["position_fallback"] == "Java Dev"
    # Druga wersja: ani kwoty, ani wiersza — więc pakiet pokaże „brak", nie „błąd".
    second_quota.assert_not_awaited()
    pending.assert_not_awaited()


async def test_worker_default_still_renders_both_languages(monkeypatch):
    rule, rendered, second_quota, pending = _worker_harness(
        monkeypatch, first_ready=False
    )
    await _run_worker(rule)
    assert [call["language"] for call in rendered] == ["pl", "en"]
    assert second_quota.await_count == 1 and pending.await_count == 1


async def test_one_click_retry_adds_the_second_language_to_an_auto_package(
    monkeypatch,
):
    """Ponowienie pakietu odpala TO SAMO zadanie (te same wejścia, więc nadal
    `primary_only`) — z gotowym pierwszym dokumentem druga wersja ma powstać."""
    rule, rendered, second_quota, pending = _worker_harness(
        monkeypatch, first_ready=True
    )
    await _run_worker(rule, languages="primary_only")
    assert [call["language"] for call in rendered] == ["en"]
    assert second_quota.await_count == 1 and pending.await_count == 1


async def test_package_shows_the_second_language_as_missing_not_failed():
    from app.models.cv_generation_job import CvGenerationJob
    from app.services import cv_packages

    world = await _world()
    async with AsyncSessionLocal() as db:
        doc = CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            client_id=world["client_id"],
            candidate_name="Auto CV",
            position="Developer",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="auto.docx",
            status="ready",
            render_payload={"name": "Auto CV"},
            created_by=world["user_id"],
            origin="auto",
            stage_id=world["stage_id"],
            source_cv_revision=world["revision"],
            central_policy={
                **policies.metadata(policies.policy_for(None)),
                "requires_en_copy": True,
                "required_languages": ["pl", "en"],
                "project_ref": "",
                "stage_id": world["stage_id"],
                "publication_version": 1,
            },
        )
        db.add(doc)
        await db.flush()
        db.add(
            CvGenerationJob(
                generated_id=doc.id,
                created_by=world["user_id"],
                kind="new",
                status="complete",
                input_storage_key=f"cv/job-input-{uuid.uuid4().hex}.json",
                input_sha256="0" * 64,
                prepared_source_facts={"facts": True},
            )
        )
        await db.commit()
        state, _data = await cv_packages.assess(db, doc)
    assert state["managed"] is True and state["ready"] is False
    assert state["required_languages"] == ["pl", "en"]
    assert state["available_languages"] == ["pl"]
    assert "Brak wygenerowanej wersji EN." in state["reasons"]
    # Jedyny dokument pakietu jest gotowy; nie ma wiersza „failed" drugiej wersji.
    assert [(d["language"], d["status"]) for d in state["documents"]] == [
        ("pl", "ready")
    ]
    assert state["generation_status"] == "complete"
    # „Jedno kliknięcie" rekrutera: ponowienie pakietu jest dostępne.
    assert state["can_retry"] is True


# ── (5) stanowisko do nazwy pliku: tytuł rekrutacji tylko w automacie ───────


async def test_candidate_without_position_falls_back_to_the_job_title(monkeypatch):
    monkeypatch.setattr(settings, "CV_CENTRAL_POLICIES_ENABLED", True)
    world = await _world()
    await _publish_policy(monkeypatch, world, require_position=True)
    seen = _stub_generation(monkeypatch, world)
    async with AsyncSessionLocal() as db:
        from app.models.job import Job

        title = (await db.get(Job, world["job_id"])).title

    assert await _run_automation(world) is not None
    [row] = await _documents(world)
    assert row.position == title
    assert seen["persisted"][0]["inputs"]["position_fallback"] == title


@pytest.mark.parametrize("pipeline", ["legacy", "v10"])
def test_pipelines_use_the_fallback_only_when_the_cv_gives_no_position(pipeline):
    """Oba potoki: `presentation_position` → stanowisko z CV → fallback automatu."""
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    path = (
        "app/services/cv_generator_b2b/legacy_v7/pipeline.py"
        if pipeline == "legacy"
        else "app/services/cv_generator_b2b/standalone_service.py"
    )
    source_text = " ".join((backend / path).read_text("utf-8").split())
    assert (
        'raw_data.get("presentation_position") or candidate_data.get("position") '
        'or position_fallback or ""'
    ) in source_text
