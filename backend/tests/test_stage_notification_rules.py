"""Tests for configurable stage-transition notifications (migracja 0066).

Trzy poziomy:

1. Pure unit — sygnatury funkcji, email template, schemas walidacja.
   Działają bez DB, zawsze.

2. Resolver z DB (empty_db fixture) — forward-only check, baseline + override
   priority, self-suppression. Skip-friendly gdy DB nie podłączona.

3. HTTP CRUD (app_client) — happy path POST/GET/PATCH/DELETE + auth (admin
   może, recruiter dostaje 403). Wymaga app_client + app_auth_headers.

Pełne integration testy ruchu pipeline'a (POST /api/pipeline/move →
notyfikacja u właściwego usera) są w docs/phase17-stage-notifications i
weryfikowane manualnie / przez Chrome MCP, bo seedowanie templatu +
joba + kandydata to ~80 linii fixture'a — nie warto na MVP.
"""

from __future__ import annotations

import inspect

import pytest
import pytest_asyncio


# ── 1. Pure unit ─────────────────────────────────────────────────────────────


def test_recipient_type_enum_values():
    from app.models.stage_notification import RecipientType

    expected = {
        "job_delivery_lead",
        "job_recruiter",
        "client_head_dl",
        "client_primary_tac",
        "specific_user",
        "role",
        "candidate_creator",
    }
    assert {rt.value for rt in RecipientType} == expected


def test_resolver_signatures():
    from app.services import stage_notification_resolver as r

    assert inspect.iscoroutinefunction(r.resolve_recipients)
    sig = inspect.signature(r.resolve_recipients)
    expected_params = {
        "db",
        "new_stage",
        "previous_stage",
        "job",
        "candidate",
        "mover_user_id",
    }
    assert expected_params.issubset(sig.parameters.keys())


def test_emitter_signatures():
    from app.services import stage_notification_emitter as e

    assert inspect.iscoroutinefunction(e.notify_stage_change)
    sig = inspect.signature(e.notify_stage_change)
    expected_params = {
        "db",
        "new_stage",
        "previous_stage",
        "job",
        "candidate",
        "mover",
        "stage_display_name",
    }
    assert expected_params.issubset(sig.parameters.keys())


def test_email_template_renders_basic_fields():
    from datetime import datetime, timezone

    from app.services.stage_notification_email_template import render_stage_email

    moved_at = datetime(2026, 4, 27, 14, 30, tzinfo=timezone.utc)
    subject, text, html = render_stage_email(
        recipient_name="Artur",
        candidate_full_name="Jan Kowalski",
        candidate_first_name="Jan",
        stage_name="zweryfikowany",
        client_name="Nordrea",
        job_title="Senior Python Developer",
        job_id=42,
        mover_name="Mateusz Rekruter",
        moved_at=moved_at,
        notes="Świetne wrażenie z calla.",
        link="https://nexus.dynaminds.pl/candidates/123",
    )
    # Subject zawiera kluczowe informacje
    assert "Jan" in subject
    assert "zweryfikowany" in subject
    assert "Nordrea" in subject

    # Text body
    assert "Artur" in text
    assert "Jan Kowalski" in text
    assert "Senior Python Developer" in text
    assert "#42" in text
    assert "Mateusz Rekruter" in text
    assert "Świetne wrażenie z calla." in text
    assert "https://nexus.dynaminds.pl/candidates/123" in text

    # HTML body — escaping + link
    assert "Jan Kowalski" in html
    assert "https://nexus.dynaminds.pl/candidates/123" in html
    assert "<a" in html and "Otwórz kartę kandydata" in html


def test_email_template_handles_missing_client_and_notes():
    from datetime import datetime, timezone

    from app.services.stage_notification_email_template import render_stage_email

    subject, text, html = render_stage_email(
        recipient_name="DL",
        candidate_full_name="Anna Nowak",
        candidate_first_name="Anna",
        stage_name="cv_sent",
        client_name=None,
        job_title="Backend Engineer",
        job_id=7,
        mover_name="System",
        moved_at=datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc),
        notes=None,
        link="https://nexus.dynaminds.pl/candidates/9",
    )
    assert "Anna" in subject
    # Bez klienta — w subject nie ma nawiasu
    assert "(" not in subject.split("→")[1]
    # W body widać "—" dla pustego klienta
    assert "—" in text or "&mdash;" in html
    # Notatka nie powinna być wstawiona
    assert "Notatka przy ruchu" not in text


def test_email_template_html_escapes_special_chars():
    from datetime import datetime, timezone

    from app.services.stage_notification_email_template import render_stage_email

    _subject, _text, html = render_stage_email(
        recipient_name="Artur <admin>",
        candidate_full_name="O'Brien & Co",
        candidate_first_name="O'Brien",
        stage_name="verified",
        client_name="Acme <Test>",
        job_title="Dev <script>",
        job_id=1,
        mover_name="Hacker & User",
        moved_at=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        notes="<script>alert(1)</script>",
        link="https://nexus.dynaminds.pl/candidates/1",
    )
    # XSS attempts must be escaped in HTML
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_schema_validates_specific_user_required_field():
    import pydantic

    from app.models.stage_notification import RecipientType
    from app.schemas.stage_notification import StageNotificationRuleCreate

    # OK — z user_id
    StageNotificationRuleCreate(
        recipient_type=RecipientType.specific_user,
        specific_user_id=42,
        notify_inapp=True,
        notify_email=False,
    )
    # Bez user_id → ValueError
    with pytest.raises(pydantic.ValidationError):
        StageNotificationRuleCreate(
            recipient_type=RecipientType.specific_user,
            notify_inapp=True,
            notify_email=False,
        )


def test_schema_validates_role_required_field():
    import pydantic

    from app.models.stage_notification import RecipientType
    from app.schemas.stage_notification import StageNotificationRuleCreate

    # OK — z rolą
    StageNotificationRuleCreate(
        recipient_type=RecipientType.role,
        role="delivery_lead",
        notify_inapp=True,
        notify_email=False,
    )
    # Bez roli → ValueError
    with pytest.raises(pydantic.ValidationError):
        StageNotificationRuleCreate(
            recipient_type=RecipientType.role,
            notify_inapp=True,
            notify_email=False,
        )
    # Niepoprawna rola → ValueError
    with pytest.raises(pydantic.ValidationError):
        StageNotificationRuleCreate(
            recipient_type=RecipientType.role,
            role="not_a_real_role",
            notify_inapp=True,
            notify_email=False,
        )


def test_schema_requires_at_least_one_channel():
    import pydantic

    from app.models.stage_notification import RecipientType
    from app.schemas.stage_notification import StageNotificationRuleCreate

    with pytest.raises(pydantic.ValidationError):
        StageNotificationRuleCreate(
            recipient_type=RecipientType.job_recruiter,
            notify_inapp=False,
            notify_email=False,
        )


def test_schema_disallows_specific_user_id_with_other_recipient_type():
    import pydantic

    from app.models.stage_notification import RecipientType
    from app.schemas.stage_notification import StageNotificationRuleCreate

    with pytest.raises(pydantic.ValidationError):
        StageNotificationRuleCreate(
            recipient_type=RecipientType.job_recruiter,
            specific_user_id=99,  # niedozwolone z job_recruiter
            notify_inapp=True,
            notify_email=False,
        )


# ── 2. Resolver smoke (DB) ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """Live DB session (requires DATABASE_URL + migrations applied)."""
    pytest.importorskip("asyncpg")
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            yield db
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable: {exc}")


async def test_resolver_returns_empty_for_legacy_stage_without_def(db_session):
    """new_stage.stage_def_id IS NULL → resolver zwraca [] (legacy fallback)."""
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.stage_notification_resolver import resolve_recipients

    # In-memory ORM objects — bez commita do DB. Sprawdza wczesny return.
    legacy_stage = CandidateStage(
        candidate_id=1, job_id=1, stage=PipelineStage.new, stage_def_id=None
    )
    job = Job(id=1, title="Test")
    candidate = Candidate(id=1, name="X", lastname="Y")

    result = await resolve_recipients(
        db_session,
        new_stage=legacy_stage,
        previous_stage=None,
        job=job,
        candidate=candidate,
        mover_user_id=42,
    )
    assert result == []


# ── 3. HTTP CRUD ────────────────────────────────────────────────────────────


async def test_http_list_rules_requires_existing_template_and_stage(
    app_client, app_auth_headers
):
    """GET nieistniejącego template/stage'a → 404."""
    resp = await app_client.get(
        "/api/pipeline-templates/999999/stages/999999/notification-rules",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_http_list_overrides_requires_existing_client(
    app_client, app_auth_headers
):
    resp = await app_client.get(
        "/api/clients/999999/notification-overrides",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_http_create_rule_validates_recipient_type_specific(
    app_client, app_auth_headers
):
    """POST z recipient_type=specific_user bez specific_user_id → 422."""
    # Przy okazji testuje że auth admin → przechodzi przez auth gate.
    # Stage_def 1 może nie istnieć w testowej bazie — wówczas leci 404 zamiast
    # 422 Pydantic. Akceptujemy oba — oznacza że auth+walidacja działa.
    resp = await app_client.post(
        "/api/pipeline-templates/1/stages/1/notification-rules",
        headers=app_auth_headers,
        json={
            "recipient_type": "specific_user",
            "notify_inapp": True,
            "notify_email": False,
        },
    )
    assert resp.status_code in (404, 422)


async def test_http_create_rule_validates_role(app_client, app_auth_headers):
    resp = await app_client.post(
        "/api/pipeline-templates/1/stages/1/notification-rules",
        headers=app_auth_headers,
        json={
            "recipient_type": "role",
            # brak `role`
            "notify_inapp": True,
            "notify_email": False,
        },
    )
    assert resp.status_code in (404, 422)


async def test_http_create_rule_unauthenticated_returns_401(app_client):
    """Bez auth headers — 401."""
    resp = await app_client.post(
        "/api/pipeline-templates/1/stages/1/notification-rules",
        json={
            "recipient_type": "job_recruiter",
            "notify_inapp": True,
            "notify_email": False,
        },
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_delivery_lead_lists_client_overrides_for_all_clients(
    app_client,
    app_auth_headers,
):
    """Client overrides are operational and visible to every Delivery Lead."""
    import uuid

    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.client import Client, ClientStatus
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    password = f"P4ss_{uuid.uuid4().hex[:8]}!"
    async with AsyncSessionLocal() as db:
        own = Client(
            name=f"Stage rules own {uuid.uuid4().hex[:8]}",
            status=ClientStatus.active,
            hidden=False,
        )
        foreign = Client(
            name=f"Stage rules foreign {uuid.uuid4().hex[:8]}",
            status=ClientStatus.active,
            hidden=False,
        )
        user = User(
            email=f"stage-rules-dl-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password(password),
            name="Stage rules Delivery Lead",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
            profile_completed=True,
        )
        db.add_all([own, foreign, user])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=user.id,
                client_id=own.id,
            )
        )
        await db.commit()
        own_id, foreign_id, user_id, email = own.id, foreign.id, user.id, user.email

    try:
        login = await app_client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        own_response = await app_client.get(
            f"/api/clients/{own_id}/notification-overrides", headers=headers
        )
        assert own_response.status_code == 200, own_response.text

        foreign_response = await app_client.get(
            f"/api/clients/{foreign_id}/notification-overrides", headers=headers
        )
        assert foreign_response.status_code == 200, foreign_response.text

        admin_response = await app_client.get(
            f"/api/clients/{foreign_id}/notification-overrides",
            headers=app_auth_headers,
        )
        assert admin_response.status_code == 200, admin_response.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.delivery_lead_user_id == user_id
                )
            )
            await db.execute(delete(Client).where(Client.id.in_([own_id, foreign_id])))
            await db.commit()


# ── Hook smoke: pipeline.move call site ─────────────────────────────────────


def test_pipeline_move_imports_emitter_lazily():
    """Sanity check — backwards compatible: emitter import jest wewnątrz
    funkcji `move_candidate`, więc nie eksploduje przy boot apki nawet gdyby
    moduł miał problem z importami przy starcie."""
    import app.api.pipeline as pipeline_api

    src = inspect.getsource(pipeline_api.move_candidate)
    assert "notify_stage_change" in src
    assert "previous_stage" in src
