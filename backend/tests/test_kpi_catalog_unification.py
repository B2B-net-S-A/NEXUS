"""Jeden katalog KPI, cele po wszystkich rolach, cele liderów (22.09.2026).

Audyt ról, uprawnień i targetów — T1 (dwa systemy KPI), T2 (PowerCalling bez
telefonii), T3 (osoba z kilkoma rolami dostawała cel 0), T4 (trzy progi
weryfikacji), T6 (cele liderów), T7 (hit ratio DL w sześciu plikach).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.call import Call, CallStatus
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, RecruitmentType
from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import kpi_target_normalization as norm
from app.services.kpi_catalog import (
    KPI_CATALOG,
    KPI_ID_ALIASES,
    RETIRED_KPI_IDS,
    canonical_kpi_id,
    get_kpi,
)
from app.services.kpi_engine import evaluate_user_kpis
from app.services.kpi_goals import compute_my_goals
from app.services.kpi_targets import resolve_kpi_target, resolve_org_target
from app.services.metric_definitions import DL_HIT_RATIO_TARGET_PCT

WARSAW = ZoneInfo("Europe/Warsaw")
_OPERATORS = (UserRole.recruiter, UserRole.sourcer, UserRole.tac)


# ── Decyzje Artura 22.09.2026 — liczby przypięte ────────────────────────────


def test_decided_targets_are_pinned():
    def targets(kpi_id: str) -> dict[UserRole, int]:
        kpi = get_kpi(kpi_id)
        assert kpi is not None, kpi_id
        return kpi.default_targets

    for role in _OPERATORS:
        assert targets("monthly_placements")[role] == 1
        assert targets("daily_new_candidates")[role] == 5
        assert targets("daily_first_verifications")[role] == 4
        assert targets("monthly_precision")[role] == 75
    assert targets("weekly_cvs_sent") == {UserRole.recruiter: 15, UserRole.tac: 12}


def test_panel_ids_are_aliases_of_catalog_ids():
    assert canonical_kpi_id("verifications_daily") == "daily_first_verifications"
    assert canonical_kpi_id("cv_added_daily") == "daily_new_candidates"
    assert canonical_kpi_id("placements_monthly") == "monthly_placements"
    assert canonical_kpi_id("precision_monthly") == "monthly_precision"
    assert get_kpi("placements_monthly") is get_kpi("monthly_placements")


def test_normalization_constants_mirror_the_catalog():
    """Moduł SQL nie importuje kodu aplikacji — kopie stałych muszą się zgadzać."""
    assert dict(norm.KPI_ID_RENAMES) == KPI_ID_ALIASES
    assert tuple(norm.RETIRED_KPI_IDS) == tuple(RETIRED_KPI_IDS)
    from_catalog = {
        (kpi.kpi_id, role.value, value)
        for kpi in KPI_CATALOG
        for role, value in kpi.default_targets.items()
    }
    assert set(norm.CATALOG_DEFAULT_ROWS) == from_catalog


def test_single_dl_hit_ratio_constant():
    from app.api import dynareporter_delivery_lead_dashboard as drdl
    from app.api import reports
    from app.schemas.dr_delivery_lead_dashboard import DLMember
    from app.services import competitions, insights_clients, insights_dl_scope

    assert DL_HIT_RATIO_TARGET_PCT == 30.0
    assert competitions.HIT_RATIO_TARGET == DL_HIT_RATIO_TARGET_PCT
    assert reports.HIT_RATIO_TARGET_PCT == DL_HIT_RATIO_TARGET_PCT
    assert insights_dl_scope.HIT_RATIO_TARGET_PCT == DL_HIT_RATIO_TARGET_PCT
    assert insights_clients.HIT_RATIO_TARGET_PCT == DL_HIT_RATIO_TARGET_PCT
    assert drdl.HIT_RATIO_TARGET == int(DL_HIT_RATIO_TARGET_PCT)
    assert DLMember.model_fields["hit_ratio_target"].default == int(
        DL_HIT_RATIO_TARGET_PCT
    )


def test_every_coach_kpi_has_its_own_messages():
    from app.services.kpi_messages import _PRAISE_HIT_PER_KPI, _REMIND_BEHIND_PER_KPI

    coach = {k.kpi_id for k in KPI_CATALOG if k.in_coach}
    assert coach <= set(_PRAISE_HIT_PER_KPI)
    assert coach <= set(_REMIND_BEHIND_PER_KPI)
    # Martwe id z 0034 nie mają już wiadomości.
    for retired in RETIRED_KPI_IDS:
        assert retired not in _PRAISE_HIT_PER_KPI
        assert retired not in _REMIND_BEHIND_PER_KPI


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _seed_user(
    role: UserRole, *, roles: list[UserRole] | None = None, label: str = "u"
) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"kpiu-{label}-{unique}@example.com",
            name=f"KPI {label} {unique}",
            password_hash=hash_password(f"T3st_{unique}!Kpi"),
            role=role,
            roles=[r.value for r in (roles or [role])],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


# ── Migracja 0346 / lustro entrypointu ──────────────────────────────────────


@pytest.mark.asyncio
async def test_normalization_sql_renames_retires_and_drops_seed_copies():
    """Blok SQL na bazie w stanie sprzed 0346 — w transakcji wycofanej na końcu."""
    user_id = await _seed_user(UserRole.recruiter, label="norm")
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM app_settings WHERE key = :k"),
            {"k": norm.KPI_TARGET_NORMALIZATION_MARKER},
        )
        await db.execute(text("DELETE FROM kpi_role_defaults"))
        rows = [
            # martwe id z 0034
            (UserRole.recruiter, "daily_activity_count", 10),
            (UserRole.tac, "weekly_screenings", 7),
            # seed 0034 pod kanonicznym id + seed 0124 pod starym id
            (UserRole.recruiter, "monthly_placements", 2),
            (UserRole.recruiter, "placements_monthly", 1),
            (UserRole.recruiter, "daily_new_candidates", 3),
            (UserRole.recruiter, "cv_added_daily", 5),
            # świadome odstępstwo — ZOSTAJE
            (UserRole.tac, "verifications_daily", 6),
        ]
        for role, kpi_id, value in rows:
            db.add(KpiRoleDefault(role=role, kpi_id=kpi_id, target_value=value))
        db.add(
            UserKpiTarget(user_id=user_id, kpi_id="placements_monthly", target_value=4)
        )
        await db.flush()

        await db.execute(text(norm.KPI_TARGET_NORMALIZATION_SQL))

        left = {
            (r.role, r.kpi_id): r.target_value
            for r in (
                await db.execute(
                    select(
                        KpiRoleDefault.role,
                        KpiRoleDefault.kpi_id,
                        KpiRoleDefault.target_value,
                    )
                )
            ).all()
        }
        personal = (
            await db.execute(
                select(UserKpiTarget.kpi_id, UserKpiTarget.target_value).where(
                    UserKpiTarget.user_id == user_id
                )
            )
        ).all()
        marker = await db.scalar(
            text("SELECT 1 FROM app_settings WHERE key = :k"),
            {"k": norm.KPI_TARGET_NORMALIZATION_MARKER},
        )
        await db.rollback()

    # Tylko świadome odstępstwo przeżywa — pod kanonicznym id.
    assert left == {(UserRole.tac, "daily_first_verifications"): 6}
    # Osobisty cel przepisany, nie skasowany (równy domyślnemu czy nie).
    assert [(r.kpi_id, r.target_value) for r in personal] == [("monthly_placements", 4)]
    assert marker == 1


# ── T3: cele po WSZYSTKICH rolach, maksimum ─────────────────────────────────


@pytest.mark.asyncio
async def test_hybrid_delivery_lead_with_tac_role_gets_tac_targets():
    """Produkcja: DL 90/91/101 z rolą TAC dostawali cel 0 i pusty widget."""
    uid = await _seed_user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead, UserRole.tac],
        label="dltac",
    )
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        assert await resolve_kpi_target(db, user=user, kpi_id="weekly_cvs_sent") == 12
        assert (
            await resolve_kpi_target(db, user=user, kpi_id="daily_new_candidates") == 5
        )
        results = await evaluate_user_kpis(db, user=user)
    by_id = {r.kpi_id: r.target for r in results}
    assert by_id["daily_first_verifications"] == 4
    assert by_id["monthly_placements"] == 1
    # Precyzja nie jest licznikiem narastającym — nie trafia do KPI Coach.
    assert "monthly_precision" not in by_id


@pytest.mark.asyncio
async def test_max_across_roles_and_personal_override_wins():
    uid = await _seed_user(
        UserRole.tac, roles=[UserRole.tac, UserRole.recruiter], label="max"
    )
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        # TAC 12, rekruter 15 → maksimum.
        assert await resolve_kpi_target(db, user=user, kpi_id="weekly_cvs_sent") == 15
        db.add(UserKpiTarget(user_id=uid, kpi_id="weekly_cvs_sent", target_value=3))
        await db.flush()
        assert await resolve_kpi_target(db, user=user, kpi_id="weekly_cvs_sent") == 3
        await db.rollback()


@pytest.mark.asyncio
async def test_role_row_under_legacy_id_still_counts():
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM kpi_role_defaults WHERE role = 'recruiter'"))
        db.add(
            KpiRoleDefault(
                role=UserRole.recruiter, kpi_id="verifications_daily", target_value=6
            )
        )
        await db.flush()
        # Cel organizacyjny (wyścig, raport Power Calling) czyta ten sam wiersz.
        assert await resolve_org_target(db, "daily_first_verifications") == 6
        await db.rollback()


# ── T4: wyścig i raport czytają te same cele ────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_race_thresholds_come_from_kpi_and_config():
    from app.services.competitions import monthly_race_thresholds
    from app.services.insights_scoring_config import invalidate_scoring_cache

    await invalidate_scoring_cache()
    async with AsyncSessionLocal() as db:
        thresholds = await monthly_race_thresholds(db)
    assert thresholds.verifications_per_day == 4
    assert thresholds.precision_pct == 75.0
    # Wyścig z nagrodą ZOSTAJE przy 2, choć cel KPI to 1 (decyzja 22.09).
    assert thresholds.min_placements == 2


# ── T2: PowerCalling bez telefonii ──────────────────────────────────────────


async def _powercalling_notifications(db, user_ids: list[int]) -> int:
    return int(
        await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id.in_(user_ids),
                Notification.notification_type == NotificationType.powercalling_kpi,
            )
        )
        or 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_powercalling_trigger_respects_cloudtalk_switch(monkeypatch, enabled):
    from app.services.notification_triggers import check_powercalling_kpi

    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", enabled)
    recruiter_id = await _seed_user(UserRole.recruiter, label="pc-r")
    hor_id = await _seed_user(UserRole.head_of_recruitment, label="pc-h")
    # Wtorek 11:45 w Warszawie — dokładnie okno raportu.
    now = datetime(2026, 9, 22, 11, 45, tzinfo=WARSAW)
    async with AsyncSessionLocal() as db:
        # Rekruter „ma źródło rozmów" — bez tego alert indywidualny i tak by nie wyszedł.
        candidate = Candidate(name="Pc", lastname=uuid.uuid4().hex[:6])
        db.add(candidate)
        await db.flush()
        db.add(
            Call(
                candidate_id=candidate.id,
                user_id=recruiter_id,
                status=CallStatus.failed,
                started_at=now - timedelta(days=3),
            )
        )
        await db.flush()
        emitted = await check_powercalling_kpi(db, now)
        await db.flush()
        count = await _powercalling_notifications(db, [recruiter_id, hor_id])
        await db.rollback()

    if enabled:
        assert emitted > 0
        assert count >= 1
    else:
        # Zero rozmów + wyłączona telefonia = zero powiadomień (audyt T2).
        assert emitted == 0
        assert count == 0


@pytest.mark.asyncio
async def test_calls_kpi_absent_when_cloudtalk_disabled(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False)
    uid = await _seed_user(UserRole.recruiter, label="calls")
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        ids = {r.kpi_id for r in await evaluate_user_kpis(db, user=user)}
    assert "daily_completed_calls" not in ids


# ── T6: cele liderów ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delivery_lead_goals_use_league_numbers():
    dl_id = await _seed_user(UserRole.delivery_lead, label="dlgoal")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, dl_id)
        empty = await compute_my_goals(db, user=user, now=now)
    assert empty.kind == "delivery_lead"
    by_id = {g.goal_id: g for g in empty.goals}
    # Bez requestów hit ratio jest NIEPOLICZONE, nie zerem.
    assert by_id["dl_hit_ratio_quarter"].current is None
    assert by_id["dl_hit_ratio_quarter"].state is None
    assert by_id["dl_hit_ratio_quarter"].target == DL_HIT_RATIO_TARGET_PCT
    assert by_id["dl_placements_quarter"].target == 3


@pytest.mark.asyncio
async def test_delivery_lead_goals_count_portfolio_placements():
    from app.core.cache import cache_invalidate

    dl_id = await _seed_user(UserRole.delivery_lead, label="dlpl")
    rec_id = await _seed_user(UserRole.recruiter, label="dlpl-r")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"KpiGoal {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"KpiGoal {uuid.uuid4().hex[:6]}",
            client_id=client.id,
            delivery_lead_id=dl_id,
            recruitment_type=RecruitmentType.body_leasing,
        )
        candidate = Candidate(name="Goal", lastname=uuid.uuid4().hex[:6])
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(minutes=5),
                moved_by=rec_id,
            )
        )
        await db.commit()

    await cache_invalidate(f"kpis:goals:dl:{dl_id}")
    async with AsyncSessionLocal() as db:
        user = await db.get(User, dl_id)
        goals = await compute_my_goals(db, user=user, now=now)
    by_id = {g.goal_id: g for g in goals.goals}
    assert by_id["dl_placements_quarter"].current == 1
    assert by_id["dl_hit_ratio_quarter"].current == 100.0
    assert by_id["dl_hit_ratio_quarter"].state == "hit"


@pytest.mark.asyncio
async def test_head_of_recruitment_gets_team_goals_as_sums():
    await _seed_user(UserRole.recruiter, label="team-r")
    hor_id = await _seed_user(UserRole.head_of_recruitment, label="team-h")
    async with AsyncSessionLocal() as db:
        user = await db.get(User, hor_id)
        goals = await compute_my_goals(db, user=user)
    assert goals.kind == "team"
    assert goals.people and goals.people >= 1
    by_id = {g.goal_id: g for g in goals.goals}
    ver = by_id["team_daily_first_verifications"]
    people_with_goal = int(ver.note.rsplit(":", 1)[1])
    # Cel zespołu = suma celów ludzi (4 na osobę, bez odstępstw w bazie).
    assert ver.target == 4 * people_with_goal
    assert ver.current is not None
    assert "team_monthly_precision" in by_id


@pytest.mark.asyncio
async def test_recruiter_has_no_leader_goals():
    uid = await _seed_user(UserRole.recruiter, label="nogoal")
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        goals = await compute_my_goals(db, user=user)
    assert goals.kind == "none"
    assert goals.goals == ()


# ── API ──────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as client:
        yield client


async def _headers(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"kpiapi-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Api"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"KPI API {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_goals_endpoint_shapes(api_client: AsyncClient):
    rec = await _headers(api_client, UserRole.recruiter)
    resp = await api_client.get("/api/kpis/me/goals", headers=rec)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "kind": "none",
        "scope_label": "",
        "people": None,
        "goals": [],
    }

    dl = await _headers(api_client, UserRole.delivery_lead)
    resp = await api_client.get("/api/kpis/me/goals", headers=dl)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "delivery_lead"


@pytest.mark.asyncio
async def test_team_panel_route_requires_team_capability(api_client: AsyncClient):
    rec = await _headers(api_client, UserRole.recruiter)
    resp = await api_client.get("/api/kpis/team/panel", headers=rec)
    assert resp.status_code == 403, resp.text

    hor = await _headers(api_client, UserRole.head_of_recruitment)
    resp = await api_client.get("/api/kpis/team/panel", headers=hor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["precision_target_pct"] == 75


# ── Ścieżka rozwoju: pula po wszystkich rolach ──────────────────────────────


@pytest.mark.asyncio
async def test_seniority_pool_includes_secondary_path_role():
    from datetime import date

    from app.services.insights_seniority import SeniorityThresholds, compute_seniority

    uid = await _seed_user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead, UserRole.tac],
        label="snr",
    )
    async with AsyncSessionLocal() as db:
        result = await compute_seniority(
            db,
            as_of=date(2026, 9, 1),
            thresholds=SeniorityThresholds(
                senior_placements=6,
                senior_window_months=6,
                expert_placements=12,
                expert_window_months=6,
                senior_alt_placements=12,
                senior_alt_window_months=12,
                expert_alt_placements=24,
                expert_alt_window_months=12,
            ),
        )
    row = next((r for r in result.rows if r.user_id == uid), None)
    assert row is not None
    assert row.role == "tac"
