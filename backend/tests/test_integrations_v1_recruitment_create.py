"""API v1 — zakładanie rekrutacji z requestu klienta (15.10.2026).

Dwie części:

* bez bazy — ciało v1 → ``JobCreate`` ekranu (jak ``buildCreateJobPayload``),
  decyzje przy polach (hiring manager, termin, budżet, dni w biurze,
  krytyczne), budżet tylko z ``amounts:write``, propozycja z odczytu AI
  i pusta propozycja przy awarii modelu, wspólne ciało ekranu i API;
* na bazie (CI) — trasy ``/recruitments/read-request`` i ``/recruitments``:
  odczyt z modelem podmienionym w teście i jego awaria, założenie przez klucz
  (Delivery Lead z ciała, autor pusty, bez ``UserActivity``), klient ukryty
  i spoza wyboru, budżet bez ``amounts:write``, próba bez zapisu, powtórka
  paragonu, bramka przekazania, scope.

Dane są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.integrations_v1 import recruitment_create as rc
from app.models.job import JobPriority
from app.services import job_lifecycle
from app.services import job_request_intake as intake_service
from app.services.integration_actor import IntegrationActor

V1 = "/api/integrations/v1"

# ── Bez bazy: ciało v1 → JobCreate ekranu ────────────────────────────────────


def _payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "client_id": 11,
        "title": "Python Developer (ZOB 48213)",
        "delivery_lead_id": 21,
        "recruiter_id": 31,
        "competence_category_id": 41,
        "requirements": [{"words": ["Python"], "level": "must"}],
        "no_critical": True,
        "rate_budget_hourly": 150,
        "remote_policy": "remote",
        "headcount": 1,
        "deadline_not_provided": True,
        "hiring_manager_not_provided": True,
        "project_about": "Platforma płatności dla banku.",
        "screening_questions": [
            {"question": "Python?", "deal_breaker": "Brak Pythona."},
            {"question": "Postgres?", "deal_breaker": "Brak baz danych."},
        ],
    }
    base.update(over)
    return base


def _body(**over: Any) -> rc.RecruitmentCreateIn:
    return rc.RecruitmentCreateIn.model_validate(_payload(**over))


def test_minimal_body_becomes_the_screen_create_request() -> None:
    data = rc.screen_job_create(_body())

    assert data.title == "Python Developer (ZOB 48213)"
    assert data.client_id == 11
    assert data.delivery_lead_id == 21
    assert data.competence_category_id == 41
    assert data.priority == JobPriority.urgent
    assert data.handoff.recruiter_id == 31
    assert data.handoff.assignment_mode == "manual"
    assert data.hiring_manager.not_provided is True
    assert data.deadline is None and data.deadline_not_provided is True
    assert data.rate_budget_hourly == 150
    assert data.must_skills  # pierwsze słowa wierszy; etykiety wpisze Champion
    assert data.similar_job_ids == [] and data.cc_override is None
    assert data.intake_form_id is None and data.from_job_id is None
    # Pola, których nie było w żądaniu, zostają poza `model_fields_set` —
    # numer klienta czyta wtedy serwer z tytułu (jak na ekranie).
    assert "client_reference" not in data.model_fields_set
    assert "headcount" in data.model_fields_set

    champion = data.champion_profile
    assert champion["basics"]["role_name"] == data.title
    assert champion["basics"]["rate_value"] == 150
    assert champion["basics"]["work_mode"] == "zdalnie"
    assert champion["stack"] == {
        "rows": [{"words": ["Python"], "level": "must"}],
        "critical": [],
    }
    assert champion["project"]["about"] == "Platforma płatności dla banku."
    assert [q["id"] for q in champion["screening_questions"]] == ["q1", "q2"]
    assert champion["screening_questions"][0]["deal_breaker"] == "Brak Pythona."


def test_without_a_recruiter_the_automat_assigns() -> None:
    data = rc.screen_job_create(_body(recruiter_id=None))
    assert data.handoff.assignment_mode == "automatic"
    assert data.handoff.recruiter_id is None


@pytest.mark.parametrize(
    ("rows", "no_critical", "critical"),
    [
        ([{"words": ["Python"], "level": "must"}], True, []),
        ([{"words": ["Python"], "level": "must"}], False, None),
        ([{"words": ["Python"], "level": "critical"}], False, None),
    ],
)
def test_critical_decision_follows_the_form(rows, no_critical, critical) -> None:
    payload = rc.job_create_payload(_body(requirements=rows, no_critical=no_critical))
    assert payload["champion_profile"]["stack"]["critical"] == critical
    # Wiersz krytyczny jedzie poziomem — krytyczne wyprowadza serwer.
    assert payload["champion_profile"]["stack"]["rows"] == rows


def test_remote_work_drops_office_fields() -> None:
    payload = rc.job_create_payload(
        _body(remote_policy="remote", location="Warszawa", onsite_days_per_week=2)
    )
    assert "location" not in payload
    assert payload["onsite_days_per_week"] is None
    basics = payload["champion_profile"]["basics"]
    assert basics["candidate_location_pref"] is None
    assert basics["onsite_days_per_week"] is None

    payload = rc.job_create_payload(
        _body(remote_policy="hybrid", location="Warszawa", onsite_days_per_month=4)
    )
    assert payload["location"] == "Warszawa"
    assert payload["onsite_days_per_month"] == 4
    assert payload["champion_profile"]["basics"]["work_mode"] == "hybrydowo"


def test_client_reference_empty_means_no_number() -> None:
    data = rc.screen_job_create(_body(client_reference=""))
    assert "client_reference" in data.model_fields_set
    assert data.client_reference == ""


def test_priority_levels_map_to_the_column() -> None:
    assert rc.screen_job_create(_body(priority="p2")).priority == JobPriority.medium
    assert rc.screen_job_create(_body(priority="accepting")).priority == JobPriority.low


def test_heads_of_rows_go_to_skill_columns_like_the_form() -> None:
    payload = rc.job_create_payload(
        _body(
            requirements=[
                {"words": ["Kafka*", "RabbitMQ"], "level": "critical"},
                {"words": ["Java"], "level": "must"},
                {"words": ["Docker"], "level": "nice"},
            ],
            no_critical=False,
        )
    )
    assert payload["must_skills"] == ["RabbitMQ", "Java"]
    assert payload["nice_skills"] == ["Docker"]


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"hiring_manager_contact_id": 5}, "hiring_manager_contact_id"),
        ({"hiring_manager_not_provided": False}, "hiring_manager_contact_id"),
        ({"deadline": "2026-12-31"}, "deadline_not_provided"),
        (
            {"deadline_not_provided": False, "deadline_time": "10:00"},
            "deadline_time",
        ),
        (
            {"rate_budget_hourly": None, "rate_budget_hourly_min": 90},
            "rate_budget_hourly_min",
        ),
        ({"rate_budget_hourly_min": 150}, "rate_budget_hourly_min"),
        (
            {
                "remote_policy": "hybrid",
                "onsite_days_per_week": 2,
                "onsite_days_per_month": 4,
            },
            "onsite_days_per_month",
        ),
        (
            {"remote_policy": "onsite", "onsite_days_per_month": 4},
            "onsite_days_per_month",
        ),
        (
            {
                "requirements": [
                    {"words": [name], "level": "critical"}
                    for name in ("Java", "Kafka", "SQL", "Docker")
                ],
                "no_critical": False,
            },
            "requirements",
        ),
        (
            {"requirements": [{"words": ["Java"], "level": "critical"}]},
            "no_critical",
        ),
    ],
)
def test_decisions_are_refused_at_the_field(over, field) -> None:
    body = _body(**over)
    with pytest.raises(HTTPException) as refused:
        rc.screen_job_create(body)
    assert refused.value.status_code == 422
    detail = refused.value.detail
    assert detail["error"] == "validation_error"
    assert ["body", field] in [err["loc"] for err in detail["errors"]]


def test_a_typo_in_a_field_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        rc.RecruitmentCreateIn.model_validate(_payload(from_job_id=7))
    with pytest.raises(ValidationError):
        rc.RecruitmentCreateIn.model_validate(
            _payload(requirements=[{"words": ["Java"], "level": "must", "x": 1}])
        )


def test_budget_needs_amounts_write() -> None:
    body = _body(rate_budget_hourly=150, rate_budget_hourly_min=120)
    assert rc.budget_fields_without_scope(body, frozenset({"recruitments:create"})) == [
        "rate_budget_hourly",
        "rate_budget_hourly_min",
    ]
    assert rc.budget_fields_without_scope(
        body, frozenset({"recruitments:create", "amounts:read"})
    ) == ["rate_budget_hourly", "rate_budget_hourly_min"]
    assert (
        rc.budget_fields_without_scope(
            body, frozenset({"recruitments:create", "amounts:write"})
        )
        == []
    )
    no_budget = _body(rate_budget_hourly=None)
    assert rc.budget_fields_without_scope(no_budget, frozenset()) == []


# ── Bez bazy: propozycja z odczytu ───────────────────────────────────────────

_TEXT = "Szukamy Python Developera do banku, praca zdalna, stawka do 150 zł/h."


def _intake(**over: Any) -> dict[str, Any]:
    base = dict(
        role_name="Python Developer",
        client_title="Python Developer",
        client_reference="ZOB 48213",
        requirements=[
            {"words": ["Python"], "level": "must"},
            {"words": ["Docker"], "level": "nice"},
        ],
        descriptive_requirements=["Doświadczenie w bankowości"],
        rate_budget_hourly=150.0,
        rate_note="Stawka netto B2B.",
        remote_policy="hybrid",
        onsite_days_per_week=1,
        onsite_days_per_month=4,
        office_cities=["Warszawa", "Gdańsk"],
        deadline="2026-11-30",
        deadline_time="12:00",
        headcount=2,
        project_about="Platforma płatności.",
        screening_questions=[
            intake_service.IntakeQuestion(
                question="Python?",
                ideal_answer="3 lata",
                from_request=True,
                deal_breaker="Brak Pythona.",
            )
        ],
        advisories=["„Kafka” nie stoi w treści requestu — wiersz pominięty."],
        working_title_suggestion="Python Developer · Python",
        hiring_manager_name="Anna Zmyślona",
        dropped=["Go"],
        missing=["questions"],
    )
    base.update(over)
    return intake_service.RequestIntake(**base).as_dict()


def test_read_response_is_shaped_like_the_create_body() -> None:
    out = rc.read_response(11, _TEXT, _intake())
    proposal = out["proposal"]

    assert out["ai_failed"] is False
    assert proposal["title"] == "Python Developer (ZOB 48213)"
    assert proposal["client_reference"] == "ZOB 48213"
    assert proposal["requirements"] == [
        {"words": ["Python"], "level": "must"},
        {"words": ["Docker"], "level": "nice"},
    ]
    assert proposal["location"] == "Warszawa, Gdańsk"
    # Jedno z dwóch, jak pole formularza: miesięczne wyznacza tygodniowe.
    assert proposal["onsite_days_per_month"] == 4
    assert proposal["onsite_days_per_week"] is None
    assert proposal["description"] == _TEXT
    assert proposal["screening_questions"] == [
        {
            "question": "Python?",
            "ideal_answer": "3 lata",
            "deal_breaker": "Brak Pythona.",
        }
    ]
    assert out["missing"] == ["questions"]
    assert "Stawka netto B2B." in out["notes"]
    assert out["hints"]["hiring_manager_name"] == "Anna Zmyślona"
    assert out["hints"]["dropped_requirements"] == ["Go"]

    # Propozycja + decyzje człowieka = poprawne ciało zapisu (bez literówek).
    validated = rc.ReadRequestOut.model_validate(out).model_dump(mode="json")
    body = rc.RecruitmentCreateIn.model_validate(
        {
            **validated["proposal"],
            "delivery_lead_id": 21,
            "hiring_manager_not_provided": True,
            "no_critical": True,
        }
    )
    assert rc.input_errors(body) == []
    assert rc.screen_job_create(body).rate_budget_hourly == 150


def test_read_response_without_ai_is_an_empty_proposal() -> None:
    out = rc.read_response(11, _TEXT, None)

    assert out["ai_failed"] is True
    assert out["proposal"]["title"] is None
    assert out["proposal"]["requirements"] == []
    assert out["proposal"]["description"] == _TEXT
    assert {"role", "must", "budget", "work_mode", "context", "questions"} <= set(
        out["missing"]
    )
    assert rc.AI_FAILED_NOTE in out["notes"]
    rc.ReadRequestOut.model_validate(out)


def test_remote_proposal_has_no_office() -> None:
    out = rc.read_response(11, _TEXT, _intake(remote_policy="remote"))
    assert out["proposal"]["location"] is None


# ── Bez bazy: jedno ciało dla ekranu i API ───────────────────────────────────


def test_screen_and_key_share_one_create_body() -> None:
    from app.api import jobs

    screen = inspect.getsource(jobs.create_job)
    key = inspect.getsource(rc.create_recruitment)
    assert "job_lifecycle.apply_job_create(" in screen
    assert "job_lifecycle.apply_job_create(" in key
    # Ekran nie składa już łańcucha rdzeni sam — jedna kopia kolejności.
    assert "create_job_core" not in screen
    assert "handoff_core" not in screen


@pytest.mark.asyncio
async def test_create_body_keeps_the_screen_order(monkeypatch) -> None:
    """Kolejność kroków sprzed wydzielenia (``create_job`` do 15.10.2026)."""
    from app.services import job_files, recruitment_allocation

    calls: list[tuple[str, tuple, dict]] = []
    job = SimpleNamespace(id=77)

    def record(name: str, result: Any = None):
        async def step(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result

        return step

    def record_sync(name: str):
        def step(*args, **kwargs):
            calls.append((name, args, kwargs))

        return step

    class _Db:
        async def flush(self) -> None:
            calls.append(("flush", (), {}))

    monkeypatch.setattr(recruitment_allocation, "allocation_lock", record("lock"))
    monkeypatch.setattr(job_lifecycle, "create_job_core", record("create", job))
    monkeypatch.setattr(
        job_lifecycle, "apply_hiring_manager_decision", record("hiring_manager")
    )
    monkeypatch.setattr(job_lifecycle, "save_champion_core", record("champion"))
    monkeypatch.setattr(
        job_lifecycle, "clear_decision_flags", record_sync("clear_flags")
    )
    monkeypatch.setattr(job_lifecycle, "ensure_handoff_ready", record_sync("gate"))
    monkeypatch.setattr(job_lifecycle, "handoff_core", record("handoff"))
    monkeypatch.setattr(job_lifecycle, "link_similar_on_create", record("similar"))
    monkeypatch.setattr(job_lifecycle, "publish_core", record("publish"))
    monkeypatch.setattr(job_lifecycle, "record_cc_override", record_sync("cc"))
    monkeypatch.setattr(job_files, "attach_intake_files", record("files"))
    monkeypatch.setattr(job_lifecycle, "delete_intake_form", record("form"))

    actor = IntegrationActor(name="Integracja: Automat testowy")
    data = rc.screen_job_create(_body())
    effects = job_lifecycle.PostCommit()
    out = await job_lifecycle.apply_job_create(_Db(), data, actor, effects)

    assert out is job
    assert [name for name, *_ in calls] == [
        "lock",
        "create",
        "hiring_manager",
        "champion",
        "clear_flags",
        "flush",
        "gate",
        "handoff",
        "similar",
        "publish",
        "cc",
        "files",
        "form",
    ]
    by_name = {name: (args, kwargs) for name, args, kwargs in calls}
    assert by_name["champion"][1] == {"notify": False}
    assert by_name["publish"][1] == {"sync_status_payload": False}
    assert by_name["files"][1]["user_id"] is None
    # Autor idzie do rdzeni jako konto serwisowe, nigdy jako osoba.
    assert by_name["create"][0][2] is actor
    assert by_name["handoff"][0][3] is actor


def test_service_account_is_not_a_person() -> None:
    actor = IntegrationActor(name="Integracja: Automat testowy")
    assert job_lifecycle.is_service_account(actor)
    assert not job_lifecycle.is_service_account(SimpleNamespace(id=1, name="Osoba"))
    # Bramka roli, do której doszłoby konto serwisowe, wywraca się zamiast
    # przepuścić — konto nie ma ról.
    assert not hasattr(actor, "has_role") and not hasattr(actor, "has_any_role")
    assert actor.id is None


# ── Na bazie (CI): trasy v1 ──────────────────────────────────────────────────


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]) -> str:
    from tests.test_service_accounts import _account_with_key

    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return api_key


def _h(api_key: str, idem: str | None = None) -> dict:
    return {"X-API-Key": api_key, "Idempotency-Key": idem or str(uuid.uuid4())}


_CREATE_SCOPES = ["recruitments:create", "amounts:write"]


@pytest.fixture
def offline_matching(monkeypatch):
    """Migawka dopasowań i wektor po commicie zostają offline i szybkie."""
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)


async def _client(*, selectable: bool = True, hidden: bool = False) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_directory import ClientPortfolioScope, PortfolioCategory

    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1C Klient {uuid.uuid4().hex[:8]}", hidden=hidden)
        db.add(client)
        await db.flush()
        if selectable:
            db.add(
                ClientPortfolioScope(
                    client_id=client.id, category=PortfolioCategory.active
                )
            )
        await db.commit()
        return client.id


async def _delivery_lead() -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"v1c-dl-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("not-a-login"),
            name="Delivery Lead Zmyślony",
            role=UserRole.delivery_lead,
            roles=["delivery_lead"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _create_body(client_id: int, **over: Any) -> dict[str, Any]:
    from tests._job_factory import competence_category_id, new_recruiter

    return _payload(
        client_id=client_id,
        title=f"V1C Python Developer {uuid.uuid4().hex[:6]}",
        delivery_lead_id=await _delivery_lead(),
        recruiter_id=await new_recruiter(),
        competence_category_id=await competence_category_id(),
        **over,
    )


async def _jobs_titled(title: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(select(func.count(Job.id)).where(Job.title == title))
        )


def _fake_read(result: Any):
    async def read_request(_db, *, client_id: int, request_text: str):
        if isinstance(result, Exception):
            raise result
        return result

    return read_request


@pytest.mark.asyncio
class TestReadRequest:
    async def test_returns_a_proposal_and_writes_nothing(
        self, app_client: AsyncClient, app_auth_headers: dict, monkeypatch
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:create"])
        client_id = await _client()
        title = f"V1C Odczyt {uuid.uuid4().hex[:6]}"
        monkeypatch.setattr(
            intake_service,
            "read_request",
            _fake_read(
                intake_service.RequestIntake(
                    role_name="Python Developer",
                    client_title=title,
                    requirements=[{"words": ["Python"], "level": "must"}],
                    rate_budget_hourly=150.0,
                    remote_policy="remote",
                    missing=["questions"],
                )
            ),
        )

        resp = await app_client.post(
            f"{V1}/recruitments/read-request",
            headers={"X-API-Key": api_key},
            json={"client_id": client_id, "text": _TEXT},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ai_failed"] is False
        assert body["proposal"]["title"] == title
        assert body["proposal"]["requirements"] == [
            {"words": ["Python"], "level": "must"}
        ]
        assert body["proposal"]["rate_budget_hourly"] == "150.00"
        assert body["missing"] == ["questions"]
        assert await _jobs_titled(title) == 0

    async def test_model_failure_is_an_empty_proposal_not_an_error(
        self, app_client: AsyncClient, app_auth_headers: dict, monkeypatch
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:create"])
        client_id = await _client()
        monkeypatch.setattr(
            intake_service, "read_request", _fake_read(RuntimeError("model down"))
        )

        resp = await app_client.post(
            f"{V1}/recruitments/read-request",
            headers={"X-API-Key": api_key},
            json={"client_id": client_id, "text": _TEXT},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ai_failed"] is True
        assert body["proposal"]["title"] is None
        assert body["proposal"]["description"] == _TEXT
        assert "budget" in body["missing"]

    async def test_hidden_client_does_not_exist(
        self, app_client: AsyncClient, app_auth_headers: dict, monkeypatch
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:create"])
        client_id = await _client(hidden=True)
        monkeypatch.setattr(
            intake_service, "read_request", _fake_read(AssertionError("bez odczytu"))
        )
        resp = await app_client.post(
            f"{V1}/recruitments/read-request",
            headers={"X-API-Key": api_key},
            json={"client_id": client_id, "text": _TEXT},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
class TestCreateRecruitment:
    async def test_key_creates_a_published_recruitment_for_the_delivery_lead(
        self, app_client: AsyncClient, app_auth_headers: dict, offline_matching
    ):
        from app.core.database import AsyncSessionLocal
        from app.models.activity import Activity
        from app.models.job import Job, JobStatus
        from app.models.notification import Notification
        from app.models.user_activity import UserActivity

        api_key = await _key(app_client, app_auth_headers, _CREATE_SCOPES)
        body = await _create_body(await _client())

        resp = await app_client.post(
            f"{V1}/recruitments", headers=_h(api_key), json=body
        )

        assert resp.status_code == 201, resp.text
        out = resp.json()
        job_id = out["job_id"]
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            assert job.status == JobStatus.published
            assert job.is_open is True
            assert job.work_state == "searching"
            assert job.delivery_lead_id == body["delivery_lead_id"]
            assert job.recruiter_id == body["recruiter_id"]
            assert job.created_by is None
            assert job.reference_number == out["reference_number"]
            assert job.champion_profile["search"]["requirements"]
            # Wpisy łańcucha zakładania (zadania w tle po odpowiedzi mają własne
            # sesje i nie są tu sprawdzane).
            activities = (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "job",
                        Activity.entity_id == job_id,
                        Activity.action.in_(
                            (
                                "created",
                                "hiring_manager_changed",
                                "champion_profile_updated",
                                "handed_off_to_search",
                                "work_state_changed",
                                "published",
                            )
                        ),
                    )
                )
            ).all()
            assert {a.action for a in activities} >= {
                "created",
                "handed_off_to_search",
                "published",
            }
            assert all(a.user_id is None for a in activities)
            assert all(
                str((a.details or {}).get("via", "")).startswith("integration:")
                for a in activities
            )
            assert (
                await db.scalar(
                    select(func.count(UserActivity.id)).where(
                        UserActivity.entity_type == "job",
                        UserActivity.entity_id == job_id,
                    )
                )
                == 0
            )
            bell = await db.scalar(
                select(Notification).where(
                    Notification.user_id == body["delivery_lead_id"],
                    Notification.related_entity_id == job_id,
                    Notification.title == "Nowa rekrutacja z integracji",
                )
            )
            assert bell is not None and "Integracja:" in bell.message

    async def test_gate_refusal_leaves_nothing(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, _CREATE_SCOPES)
        body = await _create_body(await _client(), screening_questions=[])

        resp = await app_client.post(
            f"{V1}/recruitments", headers=_h(api_key), json=body
        )

        assert resp.status_code == 422, resp.text
        error = resp.json()["error"]
        assert error["code"] == "job_not_ready"
        assert "questions" in [b["code"] for b in error["details"]["blockers"]]
        assert await _jobs_titled(body["title"]) == 0

    @pytest.mark.parametrize(
        ("client_kw", "status", "code"),
        [
            ({"hidden": True}, 404, "not_found"),
            ({"selectable": False}, 422, "client_not_selectable"),
        ],
    )
    async def test_client_outside_the_choice_is_refused(
        self,
        app_client: AsyncClient,
        app_auth_headers: dict,
        client_kw: dict,
        status: int,
        code: str,
    ):
        api_key = await _key(app_client, app_auth_headers, _CREATE_SCOPES)
        body = await _create_body(await _client(**client_kw))

        resp = await app_client.post(
            f"{V1}/recruitments", headers=_h(api_key), json=body
        )

        assert resp.status_code == status, resp.text
        assert resp.json()["error"]["code"] == code
        assert await _jobs_titled(body["title"]) == 0

    async def test_budget_without_amounts_write_is_403(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(
            app_client, app_auth_headers, ["recruitments:create", "amounts:read"]
        )
        body = await _create_body(await _client())

        resp = await app_client.post(
            f"{V1}/recruitments", headers=_h(api_key), json=body
        )

        assert resp.status_code == 403, resp.text
        error = resp.json()["error"]
        assert error["code"] == "insufficient_scope"
        assert error["details"]["fields"] == ["rate_budget_hourly"]
        assert error["details"]["missing"] == ["amounts:write"]
        assert await _jobs_titled(body["title"]) == 0

    async def test_dry_run_checks_everything_and_writes_nothing(
        self, app_client: AsyncClient, app_auth_headers: dict, offline_matching
    ):
        api_key = await _key(app_client, app_auth_headers, _CREATE_SCOPES)
        body = await _create_body(await _client())

        resp = await app_client.post(
            f"{V1}/recruitments?dry_run=true", headers=_h(api_key), json=body
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["valid"] is True
        assert resp.json()["dry_run"] is True
        assert await _jobs_titled(body["title"]) == 0

        # Próba też przechodzi bramkę: brak = ta sama odmowa co przy zapisie.
        incomplete = {**body, "screening_questions": []}
        resp = await app_client.post(
            f"{V1}/recruitments?dry_run=true", headers=_h(api_key), json=incomplete
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "job_not_ready"

    async def test_replay_returns_the_receipt_and_creates_once(
        self, app_client: AsyncClient, app_auth_headers: dict, offline_matching
    ):
        from app.services.integration_receipts import REPLAYED_HEADER

        api_key = await _key(app_client, app_auth_headers, _CREATE_SCOPES)
        body = await _create_body(await _client())
        idem = str(uuid.uuid4())

        first = await app_client.post(
            f"{V1}/recruitments", headers=_h(api_key, idem), json=body
        )
        again = await app_client.post(
            f"{V1}/recruitments", headers=_h(api_key, idem), json=body
        )

        assert first.status_code == 201, first.text
        assert again.status_code == 201, again.text
        assert again.headers.get(REPLAYED_HEADER) == "true"
        assert again.json() == first.json()
        assert await _jobs_titled(body["title"]) == 1

    @pytest.mark.parametrize("path", ["/recruitments", "/recruitments/read-request"])
    async def test_other_scopes_are_not_enough(
        self, app_client: AsyncClient, app_auth_headers: dict, path: str
    ):
        api_key = await _key(
            app_client,
            app_auth_headers,
            ["recruitments:write", "recruitments:read", "amounts:write"],
        )
        client_id = await _client()
        payload = (
            {"client_id": client_id, "text": _TEXT}
            if path.endswith("read-request")
            else await _create_body(client_id)
        )

        resp = await app_client.post(f"{V1}{path}", headers=_h(api_key), json=payload)

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"
        resp = await app_client.post(
            f"{V1}{path}", headers=app_auth_headers, json=payload
        )
        assert resp.status_code == 401, resp.text
