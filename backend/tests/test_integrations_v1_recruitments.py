"""API v1 — rekrutacje (scope ``recruitments:read``).

Bez bazy: podział kwot (stawka do klienta = sprzedaż; budżet rekrutacji,
stawka Championa i stawka kandydata z ruchu = koszt), dwie listy wymagań
z Profilu Championa, brak danych kontaktowych w kształcie karty Tablicy.

Na bazie (CI): lista z filtrami i ``updated_since``, szczegóły, wymagania,
Tablica i historia ruchów z kwotami na trzech poziomach klucza, 403 bez
scope'u, 404 dla rekrutacji, której nie ma albo której klient jest ukryty.

Dane są zmyślone (repo jest publiczne). Baza testowa jest wspólna
i nieczyszczona — każdy test zakłada własnego klienta i filtruje po nim.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job, JobPriority, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
    StageCategoryEnum,
    TerminalType,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.integration_recruitment_reads import (
    CARD_COST_FIELDS,
    CARD_SALES_FIELDS,
    JOB_BUDGET_FIELDS,
    ClientRate,
    MoneyVisibility,
    card_money,
    job_budget,
    requirements_view,
)
from tests.test_service_accounts import _account_with_key

V1 = "/api/integrations/v1"

NONE = MoneyVisibility(sales=False, costs=False)
SALES = MoneyVisibility(sales=True, costs=False)
ALL = MoneyVisibility(sales=True, costs=True)

_PROFILE = {
    "basics": {
        "role_name": "Programista Python",
        "rate_value": 110.0,
        "rate_raw": "100–110 zł/h",
        "language": "polski",
        "seniority_min_years": 5,
    },
    "stack": {
        "must": [{"name": "Python"}, {"name": "Django"}],
        "nice": [{"name": "Docker"}],
        "notes": "Python 3.12",
        "critical": ["Python"],
        "rows": [
            {"words": ["Python"], "level": "critical"},
            {"words": ["Django"], "level": "must"},
            {"words": ["Docker", "Podman"], "level": "nice"},
            {"words": [], "level": "must"},
            "zepsuty wiersz",
        ],
    },
    "experience": {
        "skills": [{"name": "Doświadczenie w przetargach", "level": "must"}],
        "domains": [{"name": "Bankowość", "level": "nice", "min_years": 2}],
    },
    "screening_questions": [
        {"id": "q1", "question": "Ile lat z Django?", "ideal_answer": "3+"},
        {"id": "q2", "question": ""},
    ],
    "project": {"about": "System płatności", "responsibilities": "Rozwój API"},
    "search": {"disqualifiers": ["Brak Pythona"]},
}


def _job(**extra) -> Job:
    values = {
        "id": 7,
        "title": "Python Developer",
        "must_skills": ["Python", "Django"],
        "nice_skills": ["Docker"],
        "champion_profile": _PROFILE,
        "rate_budget_hourly": Decimal("120.00"),
        "rate_budget_hourly_min": Decimal("100.00"),
        "salary_min": 15000,
        "salary_max": 20000,
        "requirements": "Python, Django",
    }
    values.update(extra)
    return Job(**values)


# ── Bez bazy ─────────────────────────────────────────────────────────────────


_CARD = {
    "expected_rate_value": Decimal("100.00"),
    "expected_rate_unit": "hourly",
    "expected_rate_currency": "PLN",
    "budget_max_at_move": 120,
    "budget_exceeded": False,
}
_CLIENT_RATE = ClientRate(value=Decimal("150.00"), unit="hourly", currency="PLN")


class TestCardMoney:
    def test_without_amounts_every_money_field_is_null(self):
        out = card_money(_CARD, client_rate=_CLIENT_RATE, visibility=NONE)
        assert out["amounts_redacted"] is True and out["costs_redacted"] is True
        assert all(out[key] is None for key in (*CARD_SALES_FIELDS, *CARD_COST_FIELDS))

    def test_sales_level_shows_the_client_rate_but_not_the_candidate_cost(self):
        out = card_money(_CARD, client_rate=_CLIENT_RATE, visibility=SALES)
        assert out["amounts_redacted"] is False and out["costs_redacted"] is True
        assert out["client_rate_value"] == Decimal("150.00")
        assert out["client_rate_currency"] == "PLN"
        assert all(out[key] is None for key in CARD_COST_FIELDS)

    def test_all_amounts_show_both_sides(self):
        out = card_money(_CARD, client_rate=_CLIENT_RATE, visibility=ALL)
        assert out["costs_redacted"] is False
        assert out["client_rate_value"] == Decimal("150.00")
        assert out["expected_rate_value"] == Decimal("100.00")
        assert out["budget_max_at_move"] == Decimal("120")
        assert out["budget_exceeded"] is False

    def test_card_without_a_client_rate_has_null_sales_fields(self):
        out = card_money(_CARD, client_rate=None, visibility=ALL)
        assert all(out[key] is None for key in CARD_SALES_FIELDS)


class TestJobBudget:
    @pytest.mark.parametrize("visibility", [NONE, SALES])
    def test_budget_is_a_cost(self, visibility):
        assert job_budget(_job(), visibility=visibility) == {
            key: None for key in JOB_BUDGET_FIELDS
        }

    def test_budget_with_all_amounts(self):
        out = job_budget(_job(), visibility=ALL)
        assert out["rate_budget_hourly"] == Decimal("120.00")
        assert out["rate_budget_hourly_min"] == Decimal("100.00")
        assert out["effective_budget_hourly"] == Decimal("120")
        assert out["effective_budget_hourly_min"] == Decimal("100")
        assert out["salary_max"] == Decimal("20000")

    def test_effective_budget_falls_back_to_the_champion_rate(self, monkeypatch):
        from app.services import scoring_service

        # Stawka Championa w budżecie stoi za flagą sygnałów Championa.
        monkeypatch.setattr(scoring_service, "_champion_signals_enabled", lambda: True)
        out = job_budget(_job(rate_budget_hourly=None), visibility=ALL)
        assert out["rate_budget_hourly"] is None
        assert out["effective_budget_hourly"] == Decimal("110")


class TestRequirementsView:
    def test_two_lists_search_words_and_talk_checks(self):
        view = requirements_view(_job(), visibility=NONE)
        assert view["has_champion_profile"] is True
        assert view["search_rows"] == [
            {"words": ["Python"], "level": "critical"},
            {"words": ["Django"], "level": "must"},
            {"words": ["Docker", "Podman"], "level": "nice"},
        ]
        assert view["must_skills"] == ["Python", "Django"]
        assert view["nice_skills"] == ["Docker"]
        assert [s["name"] for s in view["talk_checks"]["skills"]] == [
            "Doświadczenie w przetargach"
        ]
        assert view["talk_checks"]["domains"][0]["min_years"] == 2
        assert view["disqualifiers"] == ["Brak Pythona"]

    def test_critical_comes_from_the_delivery_lead_decision(self):
        critical = requirements_view(_job(), visibility=NONE)["critical"]
        assert critical["decided"] is True and critical["source"] == "dl"
        assert [c.casefold() for c in critical["effective"]] == ["python"]

    def test_empty_screening_question_is_skipped(self):
        questions = requirements_view(_job(), visibility=NONE)["screening_questions"]
        assert [q["id"] for q in questions] == ["q1"]
        assert questions[0]["ideal_answer"] == "3+"

    @pytest.mark.parametrize("visibility", [NONE, SALES])
    def test_champion_rate_is_a_cost(self, visibility):
        view = requirements_view(_job(), visibility=visibility)
        assert view["costs_redacted"] is True
        assert view["champion_rate_hourly"] is None
        assert view["champion_rate_raw"] is None

    def test_champion_rate_with_all_amounts(self):
        view = requirements_view(_job(), visibility=ALL)
        assert view["champion_rate_hourly"] == Decimal("110")
        assert view["champion_rate_raw"] == "100–110 zł/h"

    def test_job_without_champion_still_has_its_skill_columns(self):
        view = requirements_view(_job(champion_profile=None), visibility=ALL)
        assert view["has_champion_profile"] is False
        assert view["search_rows"] == []
        assert view["must_skills"] == ["Python", "Django"]
        assert view["champion_rate_hourly"] is None


def test_board_card_shape_carries_no_candidate_contact():
    from app.api.integrations_v1.recruitments import BoardCardOut, MoveOut

    for model in (BoardCardOut, MoveOut):
        fields = " ".join(model.model_fields)
        for word in ("email", "phone", "linkedin", "nip"):
            assert word not in fields, (model.__name__, word)


def test_requirements_view_fits_the_response_model():
    from app.api.integrations_v1.recruitments import RecruitmentRequirementsOut

    for visibility in (NONE, ALL):
        out = RecruitmentRequirementsOut.model_validate(
            requirements_view(_job(), visibility=visibility)
        ).model_dump(mode="json")
        expected = "110.00" if visibility is ALL else None
        assert out["champion_rate_hourly"] == expected


def _board_card(**extra):
    from app.schemas.pipeline import CandidateStageResponse

    now = datetime.now(timezone.utc)
    values = {
        "id": 11,
        "candidate_id": 22,
        "job_id": 33,
        "stage": PipelineStage.verified,
        "moved_at": now,
        "moved_by": None,
        "notes": "notatka wewnętrzna",
        "rating": None,
        "created_at": now,
        "name": "Anna",
        "lastname": "Przykładowa",
        "expected_rate_value": Decimal("100.00"),
        "expected_rate_unit": "hourly",
        "expected_rate_currency": "PLN",
        "budget_max_at_move": 120,
        # Tablica bez patrzącego i tak zeruje stawkę do klienta — trasa bierze
        # ją z ``latest_client_rates``, nigdy z karty.
        "client_rate_value": Decimal("999.00"),
        "qc": {"status": "passed", "blocking_failed": 0},
        "card": {"status": "complete", "missing": 0, "rate_hourly": 95.0},
        "warnings": ["budget_exceeded"],
        "process_state_version": 3,
    }
    values.update(extra)
    return CandidateStageResponse(**values)


@pytest.mark.parametrize(
    "visibility,sales_out,cost_out",
    [(NONE, None, None), (SALES, "150.00", None), (ALL, "150.00", "100.00")],
)
def test_board_card_fits_the_response_model(visibility, sales_out, cost_out):
    from app.api.integrations_v1.recruitments import BoardCardOut, _card_out

    out = BoardCardOut.model_validate(
        _card_out(
            _board_card(),
            process=None,
            client_rate=_CLIENT_RATE,
            visibility=visibility,
        )
    ).model_dump(mode="json")
    assert out["candidate"] == {"id": 22, "name": "Anna Przykładowa"}
    assert out["card_id"] == 11 and out["process_state_version"] == 3
    assert out["qc_status"] == "passed"
    assert out["recommendation_card_status"] == "complete"
    assert out["client_rate_value"] == sales_out
    assert out["expected_rate_value"] == cost_out
    assert out["budget_max_at_move"] == ("120.00" if cost_out else None)
    assert "notes" not in out and "rate_hourly" not in str(out)


def test_legacy_columns_fit_the_stage_count_model():
    from app.api.integrations_v1.recruitments import StageCountOut
    from app.api.pipeline import legacy_stage_column_summaries
    from app.services.integration_recruitment_reads import _column_dict

    columns, off = legacy_stage_column_summaries([])
    assert off == 0
    out = [StageCountOut.model_validate(_column_dict(c)) for c in columns]
    assert out[0].stage_def_id is None and out[0].order is None
    assert {c.terminal_type for c in out} >= {"hired", "rejected", "withdrawn"}


def test_status_filter_open_reuses_the_register_clause():
    from app.api.integrations_v1.recruitments import (
        _may_include_closed,
        _status_clause,
    )

    assert _status_clause(["all", "open"]) is None
    assert "!=" in str(_status_clause(["open"]))
    assert _may_include_closed(None) is True
    assert _may_include_closed(["open"]) is False
    assert _may_include_closed(["open", "closed"]) is True


# ── Na bazie ─────────────────────────────────────────────────────────────────


def _h(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]) -> str:
    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return api_key


async def _user(db, role: UserRole, label: str, tag: str) -> User:
    user = User(
        email=f"v1-rec-{label}-{tag}@example.com",
        password_hash=hash_password(f"T3st_{tag}!Rec"),
        name=f"{label} {tag}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _world(*, hidden_client: bool = False) -> dict:
    """Klient z dwiema rekrutacjami: otwarta P1 z Tablicą i zamknięta."""
    tag = uuid.uuid4().hex[:8]
    t0 = datetime.now(timezone.utc) - timedelta(days=3)
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, UserRole.recruiter, "Jan Testowy", tag)
        lead = await _user(db, UserRole.delivery_lead, "Ewa Przykładowa", tag)
        client = Client(name=f"V1 Rekrutacje {tag}", hidden=hidden_client)
        template = PipelineTemplate(name=f"V1 rekrutacje {tag}")
        db.add_all([client, template])
        await db.flush()
        new_def = PipelineStageDef(
            template_id=template.id,
            name="Nowi",
            order=0,
            category=StageCategoryEnum.internal,
            legacy_enum_value="new",
        )
        verified_def = PipelineStageDef(
            template_id=template.id,
            name="Zweryfikowany",
            order=1,
            category=StageCategoryEnum.internal,
            legacy_enum_value="verified",
        )
        rejected_def = PipelineStageDef(
            template_id=template.id,
            name="Odrzucony",
            order=2,
            category=StageCategoryEnum.terminal,
            is_terminal=True,
            terminal_type=TerminalType.rejected,
            legacy_enum_value="rejected",
        )
        contact = Contact(client_id=client.id, name="Maria Klientowa")
        db.add_all([new_def, verified_def, rejected_def, contact])
        await db.flush()
        reason = RejectionReason(
            template_id=template.id,
            name="Za mało doświadczenia",
            category=TerminalType.rejected,
        )
        job = Job(
            title=f"Python Developer {tag}",
            working_title=f"Python · Django {tag}",
            client_reference=f"ZOB-{tag}",
            client_id=client.id,
            status=JobStatus.published,
            priority=JobPriority.urgent,
            recruiter_id=recruiter.id,
            delivery_lead_id=lead.id,
            hiring_manager_contact_id=contact.id,
            pipeline_template_id=template.id,
            must_skills=["Python", "Django"],
            nice_skills=["Docker"],
            champion_profile=_PROFILE,
            rate_budget_hourly=Decimal("120.00"),
            salary_max=20000,
            description="Opis rekrutacji testowej.",
        )
        closed = Job(
            title=f"Analityk archiwalny {tag}",
            client_id=client.id,
            status=JobStatus.closed,
            priority=JobPriority.low,
        )
        anna = Candidate(
            name="Anna",
            lastname=f"Przykładowa-{tag}",
            email=f"anna-{tag}@example.com",
            phone="+48 600 000 000",
        )
        jan = Candidate(
            name="Jan", lastname=f"Testowy-{tag}", email=f"jan-{tag}@example.com"
        )
        db.add_all([reason, job, closed, anna, jan])
        await db.flush()

        def stage(candidate, pipeline_stage, stage_def, minutes, **extra):
            return CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=pipeline_stage,
                stage_def_id=stage_def.id,
                moved_at=t0 + timedelta(minutes=minutes),
                moved_by=recruiter.id,
                **extra,
            )

        rows = [
            stage(anna, PipelineStage.new, new_def, 0),
            stage(jan, PipelineStage.new, new_def, 1),
            stage(
                anna,
                PipelineStage.verified,
                verified_def,
                2,
                expected_rate_value=Decimal("100.00"),
                expected_rate_unit="hourly",
                expected_rate_currency="PLN",
                budget_max_at_move=120,
                client_rate_value=Decimal("150.00"),
                client_rate_unit="hourly",
                client_rate_currency="PLN",
            ),
            stage(
                jan,
                PipelineStage.rejected,
                rejected_def,
                3,
                rejection_reason_id=reason.id,
                ended_by="recruiter",
            ),
        ]
        db.add_all(rows)
        await db.commit()
        return {
            "tag": tag,
            "client_id": client.id,
            "job_id": job.id,
            "closed_id": closed.id,
            "recruiter_id": recruiter.id,
            "lead_id": lead.id,
            "anna": anna.id,
            "jan": jan.id,
            "move_ids": [r.id for r in rows],
        }


async def _ids(app_client: AsyncClient, api_key: str, **params) -> list[int]:
    resp = await app_client.get(
        f"{V1}/recruitments", headers=_h(api_key), params=params
    )
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()["items"]]


class TestRecruitmentList:
    async def test_item_shape_team_and_stage_counts(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        resp = await app_client.get(
            f"{V1}/recruitments",
            headers=_h(api_key),
            params={"client_id": world["client_id"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2 and body["has_more"] is False
        item = body["items"][0]
        assert item["id"] == world["job_id"]
        assert item["client"]["id"] == world["client_id"]
        assert item["client_reference"] == f"ZOB-{world['tag']}"
        assert item["status"] == "published" and item["priority"] == "p1"
        assert [r["id"] for r in item["recruiters"]] == [world["recruiter_id"]]
        assert item["recruiters"][0]["via"] == "owner"
        assert item["delivery_lead"]["id"] == world["lead_id"]
        assert item["candidate_count"] == 2
        counts = {c["name"]: c["count"] for c in item["stage_counts"]}
        assert counts == {"Nowi": 0, "Zweryfikowany": 1, "Odrzucony": 1}
        assert "rate_budget_hourly" not in item

    async def test_filters(self, app_client: AsyncClient, app_auth_headers: dict):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        client = {"client_id": world["client_id"]}
        open_id, closed_id = world["job_id"], world["closed_id"]

        assert await _ids(app_client, api_key, **client) == [open_id, closed_id]
        assert await _ids(app_client, api_key, **client, status="open") == [open_id]
        assert await _ids(app_client, api_key, **client, status="closed") == [closed_id]
        assert await _ids(
            app_client, api_key, **client, status=["draft", "published"]
        ) == [open_id]
        assert await _ids(app_client, api_key, **client, priority="p1") == [open_id]
        assert await _ids(app_client, api_key, **client, priority="accepting") == [
            closed_id
        ]
        assert await _ids(app_client, api_key, recruiter_id=world["recruiter_id"]) == [
            open_id
        ]
        assert await _ids(app_client, api_key, delivery_lead_id=world["lead_id"]) == [
            open_id
        ]
        assert await _ids(
            app_client, api_key, q=f"Python Developer {world['tag']}"
        ) == [open_id]
        assert await _ids(app_client, api_key, q=f"ZOB-{world['tag']}") == [open_id]

    async def test_updated_since(self, app_client: AsyncClient, app_auth_headers: dict):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        client = {"client_id": world["client_id"]}
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert len(await _ids(app_client, api_key, **client, updated_since=past)) == 2
        assert await _ids(app_client, api_key, **client, updated_since=future) == []

    async def test_unknown_filter_value_is_422_in_the_envelope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        resp = await app_client.get(
            f"{V1}/recruitments", headers=_h(api_key), params={"priority": "p9"}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    async def test_hidden_client_job_is_neither_listed_nor_readable(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world(hidden_client=True)
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        assert await _ids(app_client, api_key, client_id=world["client_id"]) == []
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}", headers=_h(api_key)
        )
        assert resp.status_code == 404


class TestRecruitmentDetail:
    @pytest.mark.parametrize(
        "scopes,expected",
        [
            ([], None),
            (["sales_amounts:read"], None),
            (
                ["amounts:read"],
                {
                    "rate_budget_hourly": "120.00",
                    "effective_budget_hourly": "120.00",
                    "salary_max": "20000.00",
                },
            ),
        ],
    )
    async def test_budget_is_a_cost(
        self,
        app_client: AsyncClient,
        app_auth_headers: dict,
        scopes: list[str],
        expected: dict | None,
    ):
        world = await _world()
        api_key = await _key(
            app_client, app_auth_headers, ["recruitments:read", *scopes]
        )
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["description"] == "Opis rekrutacji testowej."
        assert body["must_skills"] == ["Python", "Django"]
        assert body["hiring_manager"]["name"] == "Maria Klientowa"
        assert body["amounts_redacted"] is (not scopes)
        if expected is None:
            assert body["costs_redacted"] is True
            assert body["rate_budget_hourly"] is None
            assert body["effective_budget_hourly"] is None
            assert body["salary_max"] is None
        else:
            assert body["costs_redacted"] is False
            for key, value in expected.items():
                assert body[key] == value, key

    async def test_requirements_without_side_effects(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}/requirements", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [r["level"] for r in body["search_rows"]] == ["critical", "must", "nice"]
        assert body["talk_checks"]["skills"][0]["name"] == (
            "Doświadczenie w przetargach"
        )
        assert body["champion_rate_hourly"] is None
        assert body["costs_redacted"] is True

        api_key = await _key(
            app_client, app_auth_headers, ["recruitments:read", "amounts:read"]
        )
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}/requirements", headers=_h(api_key)
        )
        assert resp.json()["champion_rate_hourly"] == "110.00"


class TestRecruitmentBoard:
    async def _cards(self, app_client, app_auth_headers, scopes) -> dict:
        world = await _world()
        api_key = await _key(
            app_client, app_auth_headers, ["recruitments:read", *scopes]
        )
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}/board", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_id"] == world["job_id"]
        cards = {}
        for column in body["columns"]:
            assert column["count"] == len(column["cards"])
            for card in column["cards"]:
                cards[card["candidate"]["id"]] = {**card, "_column": column["name"]}
        assert body["off_template"] is None
        return {"world": world, "cards": cards, "columns": body["columns"]}

    async def test_columns_cards_and_no_contact(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        out = await self._cards(app_client, app_auth_headers, [])
        world, cards = out["world"], out["cards"]
        assert [c["name"] for c in out["columns"]] == [
            "Nowi",
            "Zweryfikowany",
            "Odrzucony",
        ]
        anna = cards[world["anna"]]
        assert anna["_column"] == "Zweryfikowany"
        assert anna["candidate"]["name"] == f"Anna Przykładowa-{world['tag']}"
        assert anna["stage"] == "verified"
        assert anna["card_id"] == world["move_ids"][2]
        assert anna["added_to_job_by"]["id"] == world["recruiter_id"]
        jan = cards[world["jan"]]
        assert jan["_column"] == "Odrzucony" and jan["ended_by"] == "recruiter"
        flat = str(cards)
        assert "@example.com" not in flat and "600 000 000" not in flat

    async def test_without_amounts(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        out = await self._cards(app_client, app_auth_headers, [])
        anna = out["cards"][out["world"]["anna"]]
        assert anna["amounts_redacted"] is True and anna["costs_redacted"] is True
        assert anna["client_rate_value"] is None
        assert anna["expected_rate_value"] is None
        assert anna["budget_max_at_move"] is None

    async def test_sales_amounts_show_only_the_client_rate(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        out = await self._cards(app_client, app_auth_headers, ["sales_amounts:read"])
        anna = out["cards"][out["world"]["anna"]]
        assert anna["amounts_redacted"] is False and anna["costs_redacted"] is True
        assert anna["client_rate_value"] == "150.00"
        assert anna["client_rate_currency"] == "PLN"
        assert anna["expected_rate_value"] is None
        assert anna["budget_max_at_move"] is None

    async def test_all_amounts(self, app_client: AsyncClient, app_auth_headers: dict):
        out = await self._cards(app_client, app_auth_headers, ["amounts:read"])
        anna = out["cards"][out["world"]["anna"]]
        assert anna["costs_redacted"] is False
        assert anna["client_rate_value"] == "150.00"
        assert anna["expected_rate_value"] == "100.00"
        assert anna["budget_max_at_move"] == "120.00"


class TestMovesAndStages:
    async def test_moves_newest_first_with_reason(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}/moves",
            headers=_h(api_key),
            params={"page_size": 3},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 4 and body["has_more"] is True
        assert [m["id"] for m in body["items"]] == list(reversed(world["move_ids"]))[:3]
        last = body["items"][0]
        assert last["candidate"]["id"] == world["jan"]
        assert last["from_stage_name"] == "Nowi"
        assert last["to_stage_name"] == "Odrzucony"
        assert last["rejection_reason"]["name"] == "Za mało doświadczenia"
        assert last["moved_by"]["id"] == world["recruiter_id"]

        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}/moves",
            headers=_h(api_key),
            params={"page": 2, "page_size": 3},
        )
        assert [m["id"] for m in resp.json()["items"]] == [world["move_ids"][0]]

        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}/moves",
            headers=_h(api_key),
            params={"candidate_id": world["anna"]},
        )
        assert resp.json()["total"] == 2

    async def test_stages_of_the_job_template(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}/stages", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["template_name"] == f"V1 rekrutacje {world['tag']}"
        assert [(s["name"], s["stage"], s["is_terminal"]) for s in body["stages"]] == [
            ("Nowi", "new", False),
            ("Zweryfikowany", "verified", False),
            ("Odrzucony", "rejected", True),
        ]
        assert body["stages"][2]["terminal_type"] == "rejected"


_JOB_ROUTES = ("", "/requirements", "/board", "/moves", "/stages")


class TestAccess:
    @pytest.mark.parametrize(
        "suffix",
        ["/recruitments"] + [f"/recruitments/{{job_id}}{s}" for s in _JOB_ROUTES],
    )
    async def test_other_scope_is_403(
        self, app_client: AsyncClient, app_auth_headers: dict, suffix: str
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["clients:read"])
        resp = await app_client.get(
            f"{V1}{suffix.format(job_id=world['job_id'])}", headers=_h(api_key)
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

    async def test_write_scope_includes_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        resp = await app_client.get(
            f"{V1}/recruitments/{world['job_id']}", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("suffix", _JOB_ROUTES)
    async def test_missing_job_is_404_in_the_envelope(
        self, app_client: AsyncClient, app_auth_headers: dict, suffix: str
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        resp = await app_client.get(
            f"{V1}/recruitments/2147483000{suffix}", headers=_h(api_key)
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "not_found"
