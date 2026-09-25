"""Audyt 25.09.2026, runda 3 — rekrutacja, Champion, CV, strona kariery.

Testy bez bazy (mockowana sesja, czyste funkcje) biegną lokalnie; testy
z ``app_client`` sprawdza CI na prawdziwym Postgresie.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.user import User, UserRole


# ── R3-17: wtyczka LinkedIn dodaje tylko do „Nowi” / „Screening” ──────────


def test_entry_column_rule_is_shared_by_bulk_add_and_linkedin():
    from app.api.proposals_bulk import _is_entry_column
    from app.services.board_stage_badges import is_entry_column

    for legacy in ("posting", "new", "prep_call", "screening"):
        assert is_entry_column(None, legacy)
    for legacy in (
        "verified",
        "interview",
        "cv_sent",
        "client_interview",
        "acceptance",
        "negotiation",
        "onboarding",
        "hired",
        "rejected",
        "withdrawn",
    ):
        assert not is_entry_column(None, legacy), legacy

    def stage(name, legacy, category=None):
        return SimpleNamespace(
            name=name, legacy_enum_value=legacy, category=category, terminal_type=None
        )

    # bulk-add i wtyczka czytają TĘ SAMĄ regułę
    assert _is_entry_column(stage("Screening", "screening"))
    assert not _is_entry_column(stage("NORDEA: Wysłać do Cpro", "screening"))
    assert not _is_entry_column(stage("Odrzucony", "rejected", "terminal"))


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["cv_sent", "rejected", "hired", "verified"])
async def test_linkedin_refuses_stages_past_the_entry_columns(stage):
    from fastapi import BackgroundTasks, HTTPException, Response

    from app.api.candidates import create_candidate_from_linkedin
    from app.models.recruitment_pipeline import PipelineStage
    from app.schemas.candidate import CandidateFromLinkedInCreate

    db = AsyncMock()
    with pytest.raises(HTTPException) as refused:
        await create_candidate_from_linkedin(
            data=CandidateFromLinkedInCreate(
                linkedin_url="https://www.linkedin.com/in/jan-kowalski-r3/",
                job_id=11,
                stage=PipelineStage(stage),
            ),
            current_user=User(
                id=7, role=UserRole.recruiter, roles=[UserRole.recruiter.value]
            ),
            background_tasks=BackgroundTasks(),
            response=Response(),
            db=db,
        )
    assert refused.value.status_code == 422
    assert "„Nowi” albo „Screening”" in refused.value.detail
    # Odmowa przed jakimkolwiek zapisem: ani kandydata, ani procesu.
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()


# ── R3-19: zapis samych notatek Championa nie przelicza dopasowań ─────────


async def _seed_champion_job(profile: dict | None = None) -> int:
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Synthetic R3 {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Synthetic Java role",
            status=JobStatus.published,
            client_id=client.id,
            champion_profile=profile
            or {
                "basics": {"role_name": "Java Developer"},
                "stack": {"must": [{"name": "Java"}], "nice": [], "notes": ""},
                "project": {"about": "Migracja systemu płatności."},
            },
            must_skills=[{"name": "Java", "level": None}],
        )
        db.add(job)
        await db.commit()
        return job.id


def _stored_notes(profile: dict) -> list[dict]:
    return [
        note
        for note in profile.get("insights") or []
        if not str(note.get("id", "")).startswith(("verification:", "legacy:"))
    ]


@pytest.mark.asyncio
async def test_insights_only_save_skips_matching_refresh_and_automations(
    app_client, app_auth_headers, monkeypatch
):
    refreshed: list[int] = []
    enqueued: list[int] = []

    async def fake_refresh(job_id, db):
        refreshed.append(job_id)

    async def fake_enqueue(job_id, *args, **kwargs):
        enqueued.append(job_id)

    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", fake_refresh
    )
    monkeypatch.setattr("app.services.auto_match_outbox.enqueue_job_safe", fake_enqueue)

    jid = await _seed_champion_job()
    route = f"/api/jobs/{jid}/champion-profile"
    first = await app_client.put(
        route,
        json={"project": {"about": "Migracja płatności kartowych."}},
        headers=app_auth_headers,
    )
    assert first.status_code == 200, first.text
    # Kontrola: zmiana wymagań nadal przelicza i budzi automaty.
    assert refreshed == [jid] and enqueued == [jid]
    before = first.json()["champion_profile"]

    refreshed.clear()
    enqueued.clear()
    note = {
        "source": "client",
        "topic": "ask_client",
        "audience": "team",
        "text": "Dopytać o tryb pracy.",
        "done": False,
    }
    added = await app_client.put(
        route, json={"insights": [note]}, headers=app_auth_headers
    )
    assert added.status_code == 200, added.text
    saved = added.json()["champion_profile"]
    assert [n["text"] for n in _stored_notes(saved)] == ["Dopytać o tryb pracy."]
    assert saved["intake"] == before["intake"]
    assert refreshed == [] and enqueued == []

    # Odhaczenie „do dopytania” razem z wierszem wyszukiwania — nadal bez
    # przeliczenia i bez zdarzenia dla automatów.
    stored = _stored_notes(saved)[0]
    both = await app_client.put(
        route,
        json={
            "insights": [{**stored, "done": True}],
            "search": {"requirements": [["Java"]]},
        },
        headers=app_auth_headers,
    )
    assert both.status_code == 200, both.text
    assert refreshed == [] and enqueued == []


def test_requirement_source_ignores_insights_but_not_requirements():
    from app.services import champion_view

    base = {
        "basics": {"role_name": "Java Developer"},
        "stack": {"must": [{"name": "Java"}]},
        "search": {"keywords": "java"},
        "insights": [],
    }
    with_note = {**base, "insights": [{"id": "n-1", "text": "Dopytać"}]}
    with_rows = {**base, "search": {"keywords": "java", "requirements": [["Kafka"]]}}
    with_stack = {**base, "stack": {"must": [{"name": "Kotlin"}]}}
    with_intake = {**base, "intake": {"applied_at": "2026-09-25T10:00:00+00:00"}}

    def key(profile):
        return champion_view.requirement_source(
            profile, ignored=champion_view.RANKING_IGNORED_KEYS
        )

    assert key(with_note) == key(base)
    assert key(with_rows) == key(base)
    assert key(with_stack) != key(base)
    # `intake` wchodzi do odcisku rankingu — jego zmiana nadal przelicza.
    assert key(with_intake) != key(base)


# ── R3-21: pytania screeningowe ze szkicu AI nie giną przez kolizję id ────


def _question(qid: str, text: str) -> dict:
    return {"id": qid, "question": text, "ideal_answer": "", "deal_breaker": ""}


def test_draft_questions_with_colliding_ids_are_all_kept():
    from app.services.champion_draft_service import _merge_screening_questions

    current = [
        _question("q1", "Ile lat pracujesz z Javą?"),
        _question("q2", "Czy znasz Kafkę?"),
        _question("q3", "Jaka jest Twoja dostępność?"),
    ]
    proposed = [_question(f"q{i}", f"Pytanie ze szkicu {i}") for i in range(1, 9)]
    # Ta sama treść co w profilu (inna wielkość liter, spacje, znak zapytania)
    # nie dubluje pytania.
    proposed.append(_question("q9", "  czy znasz   kafkę "))

    merged = _merge_screening_questions(current, proposed)

    assert len(merged) == 11
    assert [q["question"] for q in merged[:3]] == [q["question"] for q in current]
    assert [q["id"] for q in merged[:3]] == ["q1", "q2", "q3"]
    ids = [q["id"] for q in merged]
    assert len(set(ids)) == len(ids)
    assert ids[3:] == [f"q{i}" for i in range(4, 12)]


def test_apply_merges_all_draft_questions_into_the_profile():
    from app.schemas.champion import ChampionProfile
    from app.services.champion_draft_service import _merge_section

    current = ChampionProfile.model_validate(
        {"screening_questions": [_question("q1", "Pytanie z profilu")]}
    ).model_dump(mode="json")["screening_questions"]
    proposed = [_question("q1", "Pierwsze ze szkicu"), _question("q2", "Drugie")]
    merged = _merge_section("screening_questions", current, proposed)
    profile = ChampionProfile.model_validate({"screening_questions": merged})
    assert [q.question for q in profile.screening_questions] == [
        "Pytanie z profilu",
        "Pierwsze ze szkicu",
        "Drugie",
    ]


# ── R3-5: strona kariery pokazuje pola z chwili zatwierdzenia ─────────────


def _career_job(must: list[str], city: str, start: str) -> SimpleNamespace:
    return SimpleNamespace(
        champion_profile={
            "basics": {"start_date": start, "contract_length": "12 miesięcy"},
            "stack": {"must": [{"name": n} for n in must], "nice": []},
        },
        must_skills=None,
        nice_skills=None,
        location=city,
        remote_policy=None,
        onsite_days_per_week=None,
        seniority=None,
    )


def _career_payload(job, sections):
    from app.services import job_public_profile as jpp

    return jpp.public_job_payload(
        job,
        title="Java Developer",
        link_slug="r-java",
        subtitle="Rozwój platformy",
        about="Opis",
        sections=sections,
    )


def test_career_page_serves_the_snapshot_taken_at_approval():
    from app.services import job_public_profile as jpp

    job = _career_job(["Java"], "Warszawa", "od zaraz")
    sections = jpp.normalize_sections(None)
    approved_preview = _career_payload(job, sections)
    stored = jpp.sections_with_approved_content(
        sections, jpp.approved_content(approved_preview)
    )
    # Skrót treści nie widzi migawki — zatwierdzony opis zostaje zatwierdzony.
    assert jpp.content_hash("a", "b", stored) == jpp.content_hash("a", "b", sections)

    # Po zatwierdzeniu ktoś zmienia must-have, miasto i start w rekrutacji.
    changed = _career_job(["Java", "Mainframe PKO"], "Siedziba PKO BP", "styczeń")
    served = _career_payload(changed, stored)
    assert [m["name"] for m in served["must"]] == ["Java"]
    assert served["params"]["city"] == "Warszawa"
    assert served["params"]["start"] == "od zaraz"
    assert served["params"]["duration"] == "12 miesięcy"
    assert served["show"] == sections

    # Opis zatwierdzony przed wdrożeniem (bez migawki) — odczyt na żywo.
    live = _career_payload(changed, sections)
    assert [m["name"] for m in live["must"]] == ["Java", "Mainframe PKO"]
    assert live["params"]["city"] == "Siedziba PKO BP"


def test_career_snapshot_survives_a_sections_save():
    from app.services import job_public_profile as jpp

    stored = jpp.sections_with_approved_content(
        None, {"must": ["Java"], "nice": [], "city": "Kraków"}
    )
    toggled = jpp.sections_with_approved_content(
        {"must": False, "nice": True, "params": True, "process": True},
        jpp.stored_approved_content(stored),
    )
    assert jpp.stored_approved_content(toggled) == {
        "must": ["Java"],
        "nice": [],
        "city": "Kraków",
    }
    assert jpp.normalize_sections(toggled)["must"] is False


@pytest.mark.asyncio
async def test_must_have_change_after_approval_does_not_change_the_public_page(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    jid = await _seed_champion_job()
    base = f"/api/jobs/{jid}/public-profile"
    saved = await app_client.put(
        base,
        json={"subtitle": "rozwój platformy płatności", "about": "Krótki opis roli."},
        headers=app_auth_headers,
    )
    assert saved.status_code == 200, saved.text
    approved = await app_client.post(f"{base}/approve", headers=app_auth_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        job.champion_profile = {
            **(job.champion_profile or {}),
            "stack": {"must": [{"name": "Java"}, {"name": "Cobol"}], "nice": []},
        }
        job.location = "Nowe Miasto"
        await db.commit()

    from app.models.job_public_profile import JobPublicProfile
    from app.services import job_public_profile as jpp

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        profile = await db.get(JobPublicProfile, jid)
        _default, title = await jpp.public_titles(db, job, profile)
        served = jpp.public_job_payload(
            job,
            title=title,
            link_slug=None,
            subtitle=profile.subtitle,
            about=profile.about,
            sections=profile.sections,
        )
    assert [m["name"] for m in served["must"]] == ["Java"]
    assert served["params"]["city"] != "Nowe Miasto"


# ── Niskie: generate-upload ────────────────────────────────────────────────


def _docx_bytes(text: str = "Audyt Testowy. Programista Python.") -> bytes:
    from io import BytesIO

    from docx import Document

    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _upload_app(monkeypatch):
    from typing import get_args

    from fastapi import FastAPI

    from app.api import cv_generator_b2b as api

    monkeypatch.setattr(api.limiter, "enabled", False)
    monkeypatch.setattr(api.central_policies, "enabled", lambda: False)
    monkeypatch.setattr(api, "resolve_client_rule", AsyncMock(return_value=None))
    app = FastAPI()
    app.include_router(api.router)
    app.state.limiter = api.limiter
    db = AsyncMock()

    async def get(model, ident):
        if model is api.Client:
            return SimpleNamespace(id=ident, cv_content_mode_cap=None)
        return SimpleNamespace(id=ident)

    db.get.side_effect = get
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[get_args(api.CandidateWriteAccess)[1].dependency] = (
        lambda: User(id=7, role=UserRole.admin, roles=[UserRole.admin.value])
    )
    charge, pending = AsyncMock(), AsyncMock(return_value=11)
    monkeypatch.setattr(api, "_charge_cv_generation_quota", charge)
    monkeypatch.setattr(api, "_create_pending_row", pending)
    return app, db, charge, pending


@pytest.mark.asyncio
async def test_upload_without_client_or_process_is_refused_before_quota(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    app, _db, charge, pending = _upload_app(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/generate-upload",
            files={"cv_file": ("CV.docx", _docx_bytes())},
        )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Wybierz klienta, dla którego powstaje CV."
    charge.assert_not_awaited()
    pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreadable_cv_is_refused_before_the_paid_champion_preview(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.api import champion_intake as champion_api

    app, _db, charge, pending = _upload_app(monkeypatch)
    preview = AsyncMock(side_effect=AssertionError("podgląd AI nie może ruszyć"))
    monkeypatch.setattr(champion_api, "read_preview", preview)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/generate-upload",
            data={"client_id": "5", "content_mode": "tailored"},
            files={
                "cv_file": ("CV.docx", b"not a zip"),
                "champion_file": ("Champion.docx", _docx_bytes("MUST: Python")),
            },
        )
    assert response.status_code == 422, response.text
    assert "CV:" in response.json()["detail"]
    preview.assert_not_awaited()
    charge.assert_not_awaited()
    pending.assert_not_awaited()


# ── Niskie: zły typ w profilu Championa = 422, nie 500 ────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile",
    [{"basics": "x"}, {"stack": ["Java"]}, {"experience": "x"}, ["a"], "x"],
)
async def test_champion_validate_refuses_bad_types_with_422(profile):
    from fastapi import HTTPException

    from app.api.champion_intake import validate_preview

    handler = getattr(validate_preview, "__wrapped__", validate_preview)
    with pytest.raises(HTTPException) as refused:
        await handler(
            request=None,
            current_user=User(id=7, role=UserRole.admin),
            payload={"profile": profile},
        )
    assert refused.value.status_code == 422
    assert "Traceback" not in str(refused.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"basics": "x"}, {"stack": ["Java"]}])
async def test_champion_put_refuses_bad_types_with_422(
    app_client, app_auth_headers, body
):
    jid = await _seed_champion_job()
    response = await app_client.put(
        f"/api/jobs/{jid}/champion-profile", json=body, headers=app_auth_headers
    )
    assert response.status_code == 422, response.text
    assert "Profil Championa" in response.json()["detail"]


# ── Niskie: przywrócenie wersji reguły CV opublikowanej centralnie ────────


def test_centrally_published_cv_rule_version_is_restorable():
    from fastapi import HTTPException

    from app.api.client_cv_rules import _restorable_recipe, _validated_recipe
    from app.services.cv_generator_b2b import central_policies

    policy = central_policies.catalog()[0]
    recipe = {
        **central_policies.recipe_for(policy),
        "cv_content_mode_cap": None,
        "cv_interactive_enabled": False,
        "managed_policy": central_policies.metadata(policy),
    }
    # Dokładnie ten kształt zapisuje `synchronize` — dotąd 422.
    with pytest.raises(HTTPException):
        _validated_recipe(recipe)
    payload = _validated_recipe(_restorable_recipe(recipe))
    assert payload.omit_sections == []
    assert payload.glossary == []
    assert payload.highlight_terms == []
    assert payload.filename_pattern == policy["filename_pattern"]
    assert payload.cv_language == (policy["cv_language"] or None)


# ── Niskie: skaner zapisanych wyszukiwań i odwrócony zakres ───────────────


def test_reversed_range_is_read_from_stored_list_params():
    from app.tasks.saved_search_alerts import reversed_range

    assert reversed_range({"min_rate": "200", "max_rate": "150"})
    assert reversed_range({"min_experience": 10, "max_experience": 3})
    assert reversed_range({"min_rate": 100, "max_rate": 150}) is None
    assert reversed_range({"min_rate": "abc", "max_rate": 1}) is None
    assert reversed_range({}) is None


@pytest.mark.asyncio
async def test_scanner_treats_a_reversed_range_as_no_matches_and_logs_once(
    caplog, monkeypatch
):
    import logging
    from datetime import datetime, timedelta, timezone

    from app.tasks import saved_search_alerts as scanner

    monkeypatch.setattr(scanner, "_REVERSED_RANGE_LOGGED", set())
    owner = User(
        id=7,
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        authorization_version=1,
    )
    client = AsyncMock()
    db = AsyncMock()
    ss = SimpleNamespace(
        id=4242,
        user_id=7,
        filters={"api": {"min_rate": "200", "max_rate": "150"}},
        last_scanned_at=datetime.now(timezone.utc) - timedelta(hours=1),
        unseen_count=0,
        name="Odwrócona stawka",
    )
    with caplog.at_level(logging.INFO, logger=scanner.logger.name):
        for _ in range(3):
            before = ss.last_scanned_at
            assert await scanner._incremental_one(client, db, ss, owner) is False
            assert ss.last_scanned_at > before  # cichy bieg przesuwa znacznik
        ss.last_scanned_at = None
        await scanner._baseline_one(client, db, ss, owner)
    client.get.assert_not_awaited()  # lista odpowiedziałaby 422
    assert ss.last_scanned_at is not None
    logged = [r for r in caplog.records if "reversed range" in r.getMessage()]
    assert len(logged) == 1


# ── R3-20: import z generatora CV bez `insights` nie kasuje notatek ───────


def test_document_import_without_insights_keeps_team_notes_and_fields():
    from app.services.champion_intake import user_edit

    stored = {
        "basics": {"role_name": "Java Developer", "language": "PL"},
        "project": {"about": "Migracja systemu płatności."},
        "stack": {"must": [{"name": "Java"}]},
        "insights": [
            {
                "id": "n-abc123",
                "source": "client",
                "topic": "ask_client",
                "audience": "team",
                "text": "Dopytać o tryb pracy.",
                "done": False,
                "origin": "manual",
            }
        ],
    }
    # Ładunek z `championImportPayload`: tylko pola niesione przez dokument.
    patch = {"stack": {"must": [{"name": "Java"}, {"name": "Kafka"}]}}
    saved = user_edit(stored, patch, 7, imported=True)
    assert [n["text"] for n in saved["insights"]] == ["Dopytać o tryb pracy."]
    assert saved["project"]["about"] == "Migracja systemu płatności."
    assert saved["basics"]["role_name"] == "Java Developer"
    assert [i["name"] for i in saved["stack"]["must"]] == ["Java", "Kafka"]


# ── R3-22: stawka ze szkicu AI trafia do budżetu tylko z cytatu ───────────


def _basics_payload(**basics) -> dict:
    return {"basics": {"value": {"role_name": "Java", **basics}, "rationale": ""}}


def test_draft_rate_is_computed_from_the_quoted_text_not_the_model_number():
    from app.services.champion_draft_service import _ground_payload_rate

    source = "Szukamy Java Developera. Budżet: 120–140 zł/h netto, B2B."
    payload = _basics_payload(rate_value=130, rate_raw="120–140 zł/h netto")
    _ground_payload_rate(payload, source)
    basics = payload["basics"]["value"]
    # Górna granica przedziału, nie środek podany przez model.
    assert basics["rate_value"] == 140
    assert basics["rate_raw"] == "120–140 zł/h netto"
    assert "górną granicę" in payload["basics"]["rationale"]


@pytest.mark.parametrize(
    "basics",
    [
        {"rate_value": 150},  # sama liczba modelu, bez cytatu
        {"rate_value": 150, "rate_raw": "150 zł/h"},  # cytat spoza źródła
        {"rate_value": 137.5, "rate_raw": "1100 zł/MD"},  # stawka za MD
    ],
)
def test_draft_rate_without_evidence_stays_empty_with_a_note(basics):
    from app.services.champion_draft_service import _ground_payload_rate

    source = "Klient płaci 1100 zł/MD. Praca hybrydowa w Warszawie."
    payload = _basics_payload(**basics)
    _ground_payload_rate(payload, source)
    value = payload["basics"]["value"]
    assert value["rate_value"] is None
    assert value["rate_raw"] is None
    assert "Wpisz" in payload["basics"]["rationale"]


def test_draft_without_any_rate_gets_no_note():
    from app.services.champion_draft_service import _ground_payload_rate

    payload = _basics_payload()
    _ground_payload_rate(payload, "Opis bez stawki.")
    assert payload["basics"]["rationale"] == ""


def test_apply_takes_only_a_rate_derived_from_its_quote():
    from app.services.champion_draft_service import _merge_basics

    current = {"rate_value": 100.0, "rate_raw": None}
    # Propozycja sprzed poprawki: sama liczba modelu — budżet zostaje.
    assert _merge_basics(current, {"rate_value": 180})["rate_value"] == 100.0
    # Liczba niezgodna z cytatem — też zostaje.
    assert (
        _merge_basics(current, {"rate_value": 180, "rate_raw": "do 140 zł/h"})[
            "rate_value"
        ]
        == 100.0
    )
    merged = _merge_basics(current, {"rate_value": 140, "rate_raw": "do 140 zł/h"})
    assert merged["rate_value"] == 140
    assert merged["rate_raw"] == "do 140 zł/h"


def test_recruiter_page_city_and_stale_flag_come_from_the_snapshot():
    """Przegląd PR #1840: lista na stronie rekrutera czyta miasto z migawki
    zatwierdzenia (jak strona rekrutacji), a edytor wie, że rekrutacja
    zmieniła się od zatwierdzenia."""
    from types import SimpleNamespace

    from app.services import job_public_profile as jpp

    job = SimpleNamespace(
        champion_profile={},
        remote_policy=None,
        onsite_days_per_week=None,
        seniority=None,
        location="Warszawa (PKO BP)",
        must_skills=["Java"],
        nice_skills=[],
    )
    snapshot = {
        "must": ["Java"],
        "nice": [],
        "city": "Warszawa",
        "start": None,
        "duration": None,
    }
    sections = jpp.sections_with_approved_content({}, snapshot)
    assert jpp.approved_params(job, sections)["city"] == "Warszawa"
    assert jpp.approved_params(job, {})["city"] == "Warszawa (PKO BP)"
    assert jpp.approved_content_stale(job, sections) is True
    job.location = "Warszawa"
    assert jpp.approved_content_stale(job, sections) is False
    assert jpp.approved_content_stale(job, {}) is False
