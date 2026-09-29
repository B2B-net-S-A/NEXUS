"""„Champion po ludzku” (0403): ugruntowanie tekstów, dopasowanie roli, research,
uprawnienia i to, że odczyt nic nie zapisuje.

Decyzje Artura 29.09.2026: stawka i nazwa klienta idą do kandydata od razu,
statystyki roli BEZ stawek, poprawki wiedzy tylko admin + Head of Recruitment,
research w internecie raz i tylko po nazwie.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_playbook import ClientPlaybook
from app.models.job import Job, JobStatus
from app.models.plain_knowledge import JobPlainBrief, PlainTerm, RoleProfile
from app.services import champion_draft_service, skill_normalize
from app.services.plain_knowledge import (
    job_brief,
    knowledge,
    research,
    role_matcher,
    seed,
)

# ── czyste funkcje ─────────────────────────────────────────────────────────


def _inputs(**over):
    base = {
        "title": "Java Developer",
        "client": "Bank Testowy",
        "budget_pln_hourly_b2b_net": 170,
        "onsite_days_per_week": 2,
        "location": "Warszawa",
        "stack_must": ["Java", "Kafka"],
        "screening_questions": [
            {
                "id": "q1",
                "question": "Opisz ostatni system w Spring Boocie.",
                "ideal_answer": "Mikroserwisy, REST, Kafka.",
                "deal_breaker": "Brak Springa.",
            },
            {
                "id": "q2",
                "question": "Jak długo przy kartach?",
                "ideal_answer": "Min. 2 lata.",
                "deal_breaker": "",
            },
        ],
        "terms": ["java", "kafka"],
    }
    base.update(over)
    return base


def test_sentence_with_a_number_outside_the_profile_is_dropped() -> None:
    raw = {
        "pitch": "Projekt w Banku Testowym, do 170 zł netto na B2B. Zespół liczy 8 osób.",
        "one_liner": "Szukamy programisty Javy.",
        "answers": {"team": "Zespół ma 8 osób.", "rate": "Do 170 zł/h netto."},
    }
    out = job_brief.shape_output(raw, _inputs())
    assert out["pitch"] == "Projekt w Banku Testowym, do 170 zł netto na B2B."
    qa = {q["key"]: q for q in out["candidate_qa"]}
    assert qa["team"]["answer"] is None and qa["team"]["source"] is None
    assert qa["rate"]["answer"] == "Do 170 zł/h netto."


def test_rate_answer_is_empty_without_a_budget_and_client_without_a_client() -> None:
    raw = {"answers": {"rate": "Stawka do uzgodnienia.", "client": "Duży bank."}}
    out = job_brief.shape_output(
        raw, _inputs(budget_pln_hourly_b2b_net=None, client="")
    )
    qa = {q["key"]: q for q in out["candidate_qa"]}
    assert qa["rate"]["answer"] is None
    assert qa["client"]["answer"] is None
    assert [q["key"] for q in out["candidate_qa"]] == [
        k for k, _ in job_brief.CANDIDATE_QUESTIONS
    ]


def test_technology_outside_the_profile_is_dropped() -> None:
    skill_normalize.set_tech_taxonomy(
        tech_canonicals={"java", "kafka", "kotlin"},
        alias_to_canonical={"java": "java", "kafka": "kafka", "kotlin": "kotlin"},
    )
    try:
        out = job_brief.shape_output(
            {"one_liner": "Szukamy osoby do Javy i Kafki. Mile widziany Kotlin."},
            _inputs(),
        )
    finally:
        skill_normalize.set_tech_taxonomy(tech_canonicals=set(), alias_to_canonical={})
    assert out["one_liner"] == "Szukamy osoby do Javy i Kafki."


def test_screening_keeps_profile_questions_and_never_invents_a_deal_breaker() -> None:
    raw = {
        "screening": [
            {"id": "q1", "why": "Czy budował w Springu.", "good": "Opisuje usługi."},
            {"id": "q2", "why": "Doświadczenie w kartach.", "reject": "Brak banku."},
            {"id": "q9", "why": "Nowe pytanie spoza profilu."},
        ]
    }
    out = job_brief.shape_output(raw, _inputs())
    screening = out["screening_plain"]
    assert [s["question_id"] for s in screening] == ["q1", "q2"]
    assert screening[0]["good"] == "Opisuje usługi."
    # Model nie przepisał deal breakera → oryginał z profilu.
    assert screening[0]["reject"] == "Brak Springa."
    # Profil nie ma deal breakera → „Odpada” nie powstaje, nawet gdy model go dopisał.
    assert screening[1]["reject"] is None
    assert screening[1]["good"] == "Min. 2 lata."


def test_term_notes_only_for_terms_of_this_job() -> None:
    raw = {"term_notes": {"kafka": "Po niej płyną transakcje.", "docker": "Kontenery."}}
    out = job_brief.shape_output(raw, _inputs())
    assert out["term_notes"] == {"kafka": "Po niej płyną transakcje."}


def test_researchable_terms_skip_sentences_and_years() -> None:
    assert knowledge.researchable_term("Kafka")
    assert knowledge.researchable_term("Karty płatnicze")
    assert not knowledge.researchable_term("10 lat doświadczenia w IT")
    assert not knowledge.researchable_term(
        "Umiejętność pracy w zespole rozproszonym i komunikatywność"
    )
    assert not knowledge.researchable_term("   ")


def test_role_matcher_needs_title_or_half_of_the_skills() -> None:
    rules = [
        role_matcher.rules_of(
            1,
            {
                "title_words": ["tester", "manualny"],
                "skills": ["jira"],
                "category": None,
            },
        ),
        role_matcher.rules_of(
            2,
            {
                "title_words": ["java", "developer"],
                "skills": ["java", "spring boot", "kafka"],
                "category": "software_development",
            },
        ),
    ]
    title = frozenset({"java", "developer"})
    assert (
        role_matcher.best_role(
            rules, title, frozenset({"java", "kafka"}), "software_development"
        )
        == 2
    )
    # Sama kategoria nie wystarcza.
    assert (
        role_matcher.best_role(
            rules, frozenset({"analityk"}), frozenset(), "software_development"
        )
        is None
    )


def test_research_output_is_trimmed_to_known_fields() -> None:
    out = research.clean_structured(
        "term",
        {
            "display_name": "Kafka",
            "summary": "  Taśmociąg   wiadomości. ",
            "cv_hints": ["Apache Kafka", "Apache Kafka", "", "Confluent"],
            "salary": "20 000 zł",
        },
    )
    assert out == {
        "display_name": "Kafka",
        "summary": "Taśmociąg wiadomości.",
        "does": None,
        "cv_hints": ["Apache Kafka", "Confluent"],
        "confused_with": None,
    }


def test_web_research_prompt_carries_only_the_name() -> None:
    from app.services.llm_prompts import PLAIN_WEB_RESEARCH

    prompt = PLAIN_WEB_RESEARCH.render(
        name="Kafka",
        kind_label=research.KIND_LABELS["term"],
        instructions=research.INSTRUCTIONS["term"],
    )
    # Poza nazwą w zapytaniu nie ma żadnego pola rekrutacji ani placeholdera danych.
    assert "Kafka" in prompt
    assert "{" not in prompt


def test_seed_never_overwrites_a_manual_row() -> None:
    assert "WHERE plain_terms.origin <> 'manual'" in seed.TERM_SQL_NAMED
    assert "WHERE role_profiles.origin <> 'manual'" in seed.ROLE_SQL_DOLLAR


def test_new_role_takes_its_name_from_the_champion_role() -> None:
    job = SimpleNamespace(
        title="ZOB-1 Senior Java Dev",
        working_title=None,
        must_skills=["Java"],
        champion_profile={"basics": {"role_name": "Java Developer"}},
    )
    name, rules, _skills = role_matcher.rules_for_new_role(job, None)
    assert name == "Java Developer"
    assert rules["title_words"] == ["developer", "java"]
    assert (
        knowledge.slugify("Tester manualny — płatności") == "tester-manualny-platnosci"
    )


# ── baza i trasy ───────────────────────────────────────────────────────────


async def _headers_for(app_client, role_value: str) -> dict[str, str]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"plain-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Plain {role_value}",
                role=role,
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _drain_background() -> None:
    import asyncio

    from app.core import tasks

    while tasks._bg_tasks:
        await asyncio.gather(*list(tasks._bg_tasks), return_exceptions=True)


async def _seed_job() -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Po Ludzku {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Plainjava Developer {tag}",
            status=JobStatus.published,
            client_id=client.id,
            rate_budget_hourly=170,
            must_skills=[f"Plainkafka{tag}"],
            champion_profile={
                "basics": {"role_name": f"Plainjava Developer {tag}"},
                "project": {"about": "Przebudowa systemu autoryzacji kart."},
                "screening_questions": [
                    {
                        "id": "q1",
                        "question": "Co przesyłaliście przez kolejkę?",
                        "ideal_answer": "Transakcje.",
                        "deal_breaker": "Tylko kurs.",
                    }
                ],
            },
        )
        db.add(job)
        await db.commit()
        return {"job_id": job.id, "client_id": client.id, "tag": tag}


@pytest.fixture
def fake_ai(monkeypatch):
    calls = {"brief": 0, "research": []}

    async def fake_brief(**_):
        calls["brief"] += 1
        return {
            "one_liner": "Szukamy programisty do przebudowy systemu autoryzacji kart.",
            "example": "Gdy ktoś płaci kartą, bank musi szybko odpowiedzieć.",
            "day_to_day": ["Pisze usługi.", "Przenosi stary system."],
            "pitch": "Projekt w banku, stawka do 170 zł netto na godzinę.",
            "answers": {"rate": "Do 170 zł/h netto.", "team": None},
            "screening": [
                {"id": "q1", "why": "Czy używał kolejki.", "good": "Nazywa dane."}
            ],
        }

    async def fake_research(db, kind, name, **_):
        calls["research"].append((kind, name))
        if kind == "client":
            return {
                "about": f"{name} to duży bank.",
                "sources": [{"url": "https://example.com", "title": "O nas"}],
            }
        if kind == "role":
            return {
                "summary": "Programista systemów bankowych.",
                "example": "Obsługa płatności.",
                "day_to_day": ["Pisze kod."],
                "candidate_questions": ["Ile dni w biurze?"],
                "sources": [],
            }
        return {
            "display_name": name,
            "summary": "Taśmociąg wiadomości.",
            "does": "Łączy systemy.",
            "cv_hints": [name],
            "confused_with": None,
            "sources": [{"url": "https://example.com/k", "title": "Dokumentacja"}],
        }

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", fake_brief)
    monkeypatch.setattr(research, "research", fake_research)
    return calls


@pytest.mark.asyncio
async def test_get_reads_without_writing_and_says_it_is_stale(
    app_client, app_auth_headers
) -> None:
    world = await _seed_job()
    resp = await app_client.get(
        f"/api/jobs/{world['job_id']}/plain-brief", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (
        body["status"] == "none" and body["stale"] is True and body["is_open"] is True
    )
    assert body["glossary"][0]["status"] == "missing"
    async with AsyncSessionLocal() as db:
        assert await db.get(JobPlainBrief, world["job_id"]) is None


@pytest.mark.asyncio
async def test_refresh_fills_knowledge_once_and_skips_the_model_when_nothing_changed(
    app_client, app_auth_headers, fake_ai
) -> None:
    world = await _seed_job()
    url = f"/api/jobs/{world['job_id']}/plain-brief"
    first = await app_client.post(f"{url}/refresh", headers=app_auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "ready" and body["stale"] is False
    assert body["pitch"] == "Projekt w banku, stawka do 170 zł netto na godzinę."
    # Hasła słowniczka idą w tle: w odpowiedzi „Szukam opisu…” albo już gotowe
    # (atrapa researchu kończy się, zanim serwer złoży odpowiedź), nigdy błąd.
    assert body["glossary"][0]["status"] in {"researching", "ready"}
    await _drain_background()
    later = (await app_client.get(url, headers=app_auth_headers)).json()
    assert later["glossary"][0]["status"] == "ready"
    assert later["glossary"][0]["sources"][0]["url"] == "https://example.com/k"
    assert body["role"]["name"].startswith("Plainjava Developer")
    # Statystyki roli bez żadnej kwoty.
    assert set(body["role"]["stats"]) == {"jobs", "clients", "hires", "hired_titles"}
    assert body["client"]["origin"] == "web"
    assert body["screening_plain"][0]["reject"] == "Tylko kurs."
    assert fake_ai["brief"] == 1

    second = await app_client.post(f"{url}/refresh", headers=app_auth_headers)
    assert second.status_code == 200
    assert fake_ai["brief"] == 1, "ten sam profil = brak drugiego wywołania modelu"
    kinds = [k for k, _ in fake_ai["research"]]
    assert kinds.count("term") == 1 and kinds.count("client") == 1


@pytest.mark.asyncio
async def test_manual_term_is_never_researched_again(
    app_client, app_auth_headers, fake_ai
) -> None:
    world = await _seed_job()
    key = f"plainkafka{world['tag']}"
    async with AsyncSessionLocal() as db:
        db.add(
            PlainTerm(
                term_key=key,
                display_name="Kafka",
                summary="Ręczna definicja.",
                origin="manual",
                status="failed",
            )
        )
        await db.commit()
        assert not await knowledge.claim_term(db, key, "Kafka")
    await app_client.post(
        f"/api/jobs/{world['job_id']}/plain-brief/refresh", headers=app_auth_headers
    )
    await _drain_background()
    assert ("term", f"Plainkafka{world['tag']}") not in fake_ai["research"]


@pytest.mark.asyncio
async def test_only_admin_and_head_of_recruitment_edit_knowledge(
    app_client, app_auth_headers, fake_ai
) -> None:
    world = await _seed_job()
    recruiter = await _headers_for(app_client, "recruiter")
    hor = await _headers_for(app_client, "head_of_recruitment")
    await app_client.post(
        f"/api/jobs/{world['job_id']}/plain-brief/refresh", headers=app_auth_headers
    )
    await _drain_background()
    async with AsyncSessionLocal() as db:
        role_id = await db.scalar(
            select(Job.role_profile_id).where(Job.id == world["job_id"])
        )
        term_id = await db.scalar(
            select(PlainTerm.id).where(
                PlainTerm.term_key == f"plainkafka{world['tag']}"
            )
        )
    assert role_id and term_id

    view = await app_client.get(
        f"/api/jobs/{world['job_id']}/plain-brief", headers=recruiter
    )
    assert view.status_code == 200
    assert view.json()["can_change_role"] is False
    assert (
        await app_client.put(
            f"/api/role-profiles/{role_id}", json={"summary": "x"}, headers=recruiter
        )
    ).status_code == 403
    assert (
        await app_client.put(
            f"/api/jobs/{world['job_id']}/role-profile",
            json={"role_profile_id": None},
            headers=recruiter,
        )
    ).status_code == 403

    edited = await app_client.put(
        f"/api/role-profiles/{role_id}",
        json={"summary": "Poprawiony opis roli."},
        headers=hor,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["origin"] == "manual"
    assert (
        edited.json()["history"][0]["changes"]["summary"]["new"]
        == "Poprawiony opis roli."
    )
    term = await app_client.put(
        f"/api/skills-admin/plain-terms/{term_id}",
        json={"summary": "Kolejka wiadomości."},
        headers=hor,
    )
    assert term.status_code == 200, term.text
    assert term.json()["origin"] == "manual"


@pytest.mark.asyncio
async def test_manual_client_about_edit_is_no_longer_marked_as_web(
    app_client, app_auth_headers, fake_ai
) -> None:
    world = await _seed_job()
    await app_client.post(
        f"/api/jobs/{world['job_id']}/plain-brief/refresh", headers=app_auth_headers
    )
    card = await app_client.get(
        f"/api/clients/{world['client_id']}/playbook", headers=app_auth_headers
    )
    assert card.json()["about_for_candidate_origin"] == "web"
    payload = {
        k: v
        for k, v in card.json().items()
        if k
        in {
            "sla_business_days",
            "sla_min_candidates",
            "cv_limit_per_process",
            "hold_hours",
            "multi_project_cooldown_days",
            "rate_policy",
            "priority_rules",
            "process_rules_md",
            "onboarding_md",
            "documents",
        }
    }
    payload["about_for_candidate"] = "Opis wpisany przez Delivery Leada."
    saved = await app_client.put(
        f"/api/clients/{world['client_id']}/playbook",
        json=payload,
        headers=app_auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["about_for_candidate_origin"] == "manual"
    assert saved.json()["about_for_candidate_sources"] == []
    async with AsyncSessionLocal() as db:
        events = await db.scalar(
            select(func.count())
            .select_from(ClientPlaybook)
            .where(ClientPlaybook.client_id == world["client_id"])
        )
    assert events == 1


@pytest.mark.asyncio
async def test_seed_upserts_but_keeps_manual_rows(tmp_path) -> None:
    import json

    tag = uuid.uuid4().hex[:8]
    key = f"seedterm{tag}"
    (tmp_path / "terms.json").write_text(
        json.dumps(
            {"terms": [{"term_key": key, "display_name": "Seed", "summary": "Z repo."}]}
        ),
        encoding="utf-8",
    )
    (tmp_path / "roles.json").write_text(json.dumps({"roles": []}), encoding="utf-8")
    async with AsyncSessionLocal() as db:
        await db.run_sync(lambda s: seed.seed_sync(s.connection(), tmp_path))
        await db.commit()
        row = await db.scalar(select(PlainTerm).where(PlainTerm.term_key == key))
        assert row.summary == "Z repo." and row.origin == "seed"
        row.summary, row.origin = "Ręcznie.", "manual"
        await db.commit()
        await db.run_sync(lambda s: seed.seed_sync(s.connection(), tmp_path))
        await db.commit()
        row = await db.scalar(
            select(PlainTerm)
            .where(PlainTerm.term_key == key)
            .execution_options(populate_existing=True)
        )
        assert row.summary == "Ręcznie."
    assert RoleProfile.__tablename__ == "role_profiles"


def test_build_script_cleans_role_names_and_groups_similar_jobs() -> None:
    from scripts.build_plain_knowledge import clean_role_name, cluster_jobs

    assert (
        clean_role_name("ZOB-1725 Senior Java Developer (Kafka) | Bank")
        == "Java Developer"
    )
    java = {
        "title": frozenset({"java", "developer"}),
        "skills": frozenset({"java", "kafka"}),
        "cc": 1,
        "cc_slug": "sd",
    }
    tester = {
        "title": frozenset({"tester", "manualny"}),
        "skills": frozenset({"jira"}),
        "cc": 2,
        "cc_slug": "qa",
    }
    jobs = [{**java, "id": i, "role_name": "Java Developer"} for i in range(5)] + [
        {**tester, "id": 100 + i, "role_name": "Tester manualny"} for i in range(2)
    ]
    groups = cluster_jobs(jobs, min_group=5)
    assert [g["name"] for g in groups] == ["Java Developer"]
    assert groups[0]["jobs"] == 5 and groups[0]["category"] == "sd"


def test_grounding_ignores_json_keys_decimals_and_substring_technologies() -> None:
    skill_normalize.set_tech_taxonomy(
        tech_canonicals={"java", "javascript", "sql", "postgresql"},
        alias_to_canonical={
            "java": "java",
            "javascript": "javascript",
            "sql": "sql",
            "postgresql": "postgresql",
        },
    )
    try:
        g = job_brief.Grounding(
            {
                "budget_pln_hourly_b2b_net": 170,
                "stack_must": ["JavaScript", "PostgreSQL"],
            }
        )
        # „2” z klucza „b2b” nie jest faktem z profilu.
        assert not g.sentence_ok("Praca 2 dni w biurze.")
        # Część dziesiętna też musi się zgadzać.
        assert not g.sentence_ok("Stawka 170,99 zł/h.")
        assert g.sentence_ok("Stawka do 170 zł/h.")
        # „Java” to nie „JavaScript”, „SQL” to nie „PostgreSQL”.
        assert not g.sentence_ok("Szukamy osoby do Javy i Java.")
        assert not g.sentence_ok("Znajomość SQL.")
        assert g.sentence_ok("Znajomość JavaScript i PostgreSQL.")
    finally:
        skill_normalize.set_tech_taxonomy(tech_canonicals=set(), alias_to_canonical={})


def test_stale_researching_term_is_queued_again() -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    stuck = SimpleNamespace(status="researching", claimed_at=now - timedelta(hours=1))
    fresh = SimpleNamespace(status="researching", claimed_at=now)
    assert knowledge.needs_research(None)
    assert knowledge.needs_research(SimpleNamespace(status="failed", claimed_at=None))
    assert knowledge.needs_research(stuck)
    assert not knowledge.needs_research(fresh)
    assert not knowledge.needs_research(
        SimpleNamespace(status="ready", claimed_at=None)
    )


@pytest.mark.asyncio
async def test_model_failure_is_a_status_not_a_500(app_client, monkeypatch) -> None:
    """Rollback po awarii modelu wygasza `current_user` sesji żądania — trasa
    nie może go potem czytać (MissingGreenlet = 500 bez CORS)."""
    world = await _seed_job()
    headers = await _headers_for(app_client, "head_of_recruitment")

    async def boom(**_):
        raise TimeoutError("model timeout")

    async def no_research(db, kind, name, **_):
        return None

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", boom)
    monkeypatch.setattr(research, "research", no_research)
    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/plain-brief/refresh", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed"
    assert body["message"] == job_brief.FAILED
    assert body["can_change_role"] is True


def test_build_journal_skips_done_items_and_retries_empty_results(tmp_path) -> None:
    import json

    from scripts.build_plain_knowledge import load_journal

    path = tmp_path / "plan.json.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"kind": "term", "key": "kafka", "result": {"summary": "x"}}
                ),
                json.dumps({"kind": "term", "key": "jira", "result": None}),
                "zepsuta linia",
            ]
        ),
        encoding="utf-8",
    )
    done = load_journal(path)
    assert set(done) == {("term", "kafka")}


def test_new_role_name_drops_seniority_references_and_headcount() -> None:
    clean = role_matcher.clean_role_name
    assert clean("Starszy Programista Frontend (Angular)") == "Programista Frontend"
    assert clean("3 x Senior FullStack Developer in Corporate Area") == (
        "FullStack Developer in Corporate Area"
    )
    assert clean("Tech Lead Java") == "Tech Lead Java"
    assert clean("Nordea: PM for AI-driven application modernization") == (
        "PM for AI-driven application modernization"
    )
    assert clean("Bank Pocztowy: Tester manualny") == "Tester manualny"
