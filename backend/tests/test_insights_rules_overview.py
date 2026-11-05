"""Insights → Zasady: zdania przeglądu i bramka `/api/insights/rules-overview`."""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services import job_twin_rules, qc_quality, work_rhythm
from app.services.insights_rules_overview import (
    allocation_now,
    kpi_now,
    league_now,
    placements_now,
    prep_now,
    qc_last_change,
    qc_now,
    ranking_now,
    rhythm_now,
    twin_now,
)
from app.services.insights_scoring_config import SCORING_DEFAULTS
from app.services.request_allocation_rules import AllocationRules


def test_allocation_sentence_follows_mode_and_scope():
    rules = AllocationRules()
    assert allocation_now("auto", rules) == (
        "Przydziela sam · P0 i P1 · 1 os. na P1 · bez limitu obłożenia · przegląd 08:30"
    )
    # Wyłączony automat nie udaje, że dobiera ludzi według zasad.
    assert allocation_now("off", rules) == "Wyłączony · przegląd 08:30"


def test_allocation_sentence_shows_changed_rules():
    rules = AllocationRules(include_p2=True, people_per_p1=2, max_load=6)
    assert allocation_now("shadow", rules) == (
        "Proponuje · P0, P1 i P2 · 2 os. na P1 · limit obłożenia 6 · przegląd 08:30"
    )


def test_twin_sentence_lists_required_rules_from_defaults():
    assert twin_now(job_twin_rules.defaults().model_dump()) == (
        "Podobieństwo od 80% · wymagane: krytyczne, różny DL · najwyżej 3 bliźniaki"
    )


def test_twin_sentence_without_required_rules():
    rules = job_twin_rules.defaults().model_dump()
    rules["critical"]["mode"] = "off"
    rules["different_dl"]["mode"] = "warning"
    assert "bez zasad wymaganych" in twin_now(rules)


def test_ranking_sentence_orders_by_share_and_skips_zero():
    text = ranking_now(
        {"semantic": 66.67, "skills": 11.11, "salary": 16.67, "location": 5.56, "availability": 0.0},
        70,
    )
    assert text == "Podobieństwo CV 67% · stawka 17% · umiejętności 11% · lokalizacja 6% · próg 70"


def test_prep_sentence_orders_by_weight():
    assert prep_now({"topics": 25, "talk_share": 15, "must_answers": 40, "client_questions": 20}) == (
        "must-have 40 · tematy 25 · pytania klienta 20 · proporcja rozmowy 15"
    )


def test_kpi_sentence_mentions_exceptions_only_when_they_exist():
    targets = {
        "daily_completed_calls": 15,
        "daily_first_verifications": 4,
        "weekly_cvs_sent": 15,
        "monthly_placements": 1,
        "monthly_precision": 75,
    }
    assert "wyjątki" not in kpi_now(targets, 0)
    assert kpi_now(targets, 2).endswith("· wyjątki: 2")


def test_league_sentence_uses_every_named_value():
    assert league_now(SCORING_DEFAULTS) == (
        "Placement 150 · rozmowa 15 · rekomendacja 5 · Senior 6 w 6 mies. · Ekspert 12 w 6 mies."
    )


def test_rhythm_sentence_from_default_rules():
    assert rhythm_now(work_rhythm.rules_from_json(None).as_json()) == (
        "Screening 5 · rozmowa u klienta 3 · CV 3 · notatka 2 · norma 120 pkt dziennie"
    )


def test_qc_sentence_ignores_checks_shown_too_rarely():
    states = {
        "critical_skills": {"shown": 124, "precision": 0.798},
        "spelling": {"shown": 3, "precision": 0.1},
    }
    text = qc_now(states, qc_quality.effective_states(states))
    assert "80%" in text
    assert "10%" not in text


def test_qc_sentence_counts_muted_checks():
    states = {"spelling": {"manual": "off"}}
    assert "nieaktywne: 1" in qc_now(states, qc_quality.effective_states(states))


def test_qc_last_change_reads_manual_stamp_only():
    earlier = datetime(2026, 10, 1, tzinfo=timezone.utc)
    later = datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert qc_last_change({"dates": {"shown": 10, "precision": 1.0}}) is None
    assert qc_last_change(
        {
            "dates": {"manual_at": earlier.isoformat(), "manual_by": 1},
            "spelling": {"manual_at": later.isoformat(), "manual_by": 2},
        }
    ) == (later, 2)


def test_placements_sentence_names_series_threshold():
    assert placements_now(227) == "Par poza statystykami: 227 · seria od 10 par dziennie bez CV"


# ── Trasa ────────────────────────────────────────────────────────────────────

_EVERYONE = {"przydzial", "blizniaki", "ranking", "prepy", "cele", "aktywnosc"}
_ADMIN_ONLY = {"qc", "liga", "placementy"}


async def _headers(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"rules-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Rules"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Rules {role.value} {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def rules_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_admin_gets_all_nine_rules(rules_client: AsyncClient):
    headers = await _headers(rules_client, UserRole.admin)
    resp = await rules_client.get("/api/insights/rules-overview", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rules"]
    assert {row["id"] for row in rows} == _EVERYONE | _ADMIN_ONLY
    assert all(row["now"] for row in rows)


@pytest.mark.asyncio
async def test_head_of_recruitment_does_not_get_admin_only_rules(rules_client: AsyncClient):
    headers = await _headers(rules_client, UserRole.head_of_recruitment)
    resp = await rules_client.get("/api/insights/rules-overview", headers=headers)
    assert resp.status_code == 200, resp.text
    assert {row["id"] for row in resp.json()["rules"]} == _EVERYONE


@pytest.mark.parametrize(
    "role", [UserRole.recruiter, UserRole.delivery_lead, UserRole.finance]
)
@pytest.mark.asyncio
async def test_other_roles_are_refused(rules_client: AsyncClient, role: UserRole):
    headers = await _headers(rules_client, role)
    resp = await rules_client.get("/api/insights/rules-overview", headers=headers)
    assert resp.status_code == 403, f"{role.value}: {resp.text}"
