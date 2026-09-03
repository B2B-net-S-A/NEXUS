"""„Pobierz zamówienia z maila" i stan sprawdzenia skrzynki — API kolejki.

Trzy reguły: przycisk jest rolowy (Admin / Finance / Delivery Lead), nie per
klient, bo dotyczy całej skrzynki; Talent Community Manager widzi stan (bez
treści błędów, które cytują nazwy załączników), ale biegu nie uruchamia;
Head of Recruitment odcina bramka sekcji Delivery. Sam bieg jest podstawiony —
test sprawdza kontrakt HTTP i to, że uruchomienie idzie przez rejestr zadań
z powodem ``manual`` (a nie przez gołe ``create_task``).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.api import order_mail_queue as queue_api
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services import order_mail_ingest as svc


async def _headers_for_role(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"order-mail-sync-{role.value}-{tag}@example.com"
    password = f"P4ss_{tag}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Order Mail Sync {role.value}",
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


@pytest.mark.asyncio
async def test_trigger_sync_is_role_gated_and_starts_a_manual_run(
    app_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(queue_api.settings, "ORDER_MAIL_INGEST_ENABLED", True)
    monkeypatch.setattr(queue_api, "ingest_is_running", lambda: False)
    started: list[tuple[str, object]] = []

    def fake_start(*, reason, since=None):
        started.append((reason, since))
        return None

    monkeypatch.setattr(queue_api, "start_ingest_task", fake_start)

    dl = await _headers_for_role(app_client, UserRole.delivery_lead)
    r = await app_client.post("/api/order-mail/sync", headers=dl)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "started"}
    assert started == [("manual", None)]

    finance = await _headers_for_role(app_client, UserRole.finance)
    assert (
        await app_client.post("/api/order-mail/sync", headers=finance)
    ).status_code == 200
    assert len(started) == 2

    tcm = await _headers_for_role(app_client, UserRole.talent_community_manager)
    assert (
        await app_client.post("/api/order-mail/sync", headers=tcm)
    ).status_code == 403
    hor = await _headers_for_role(app_client, UserRole.head_of_recruitment)
    assert (
        await app_client.post("/api/order-mail/sync", headers=hor)
    ).status_code == 403
    assert len(started) == 2, "odmowa nie może uruchomić biegu"

    # Bieg już trwa (np. planowy) → 409; front dołącza do niego zamiast startować drugi.
    monkeypatch.setattr(queue_api, "ingest_is_running", lambda: True)
    assert (
        await app_client.post("/api/order-mail/sync", headers=dl)
    ).status_code == 409
    # Kill-switch → 503, tak jak w wariancie admina.
    monkeypatch.setattr(queue_api, "ingest_is_running", lambda: False)
    monkeypatch.setattr(queue_api.settings, "ORDER_MAIL_INGEST_ENABLED", False)
    assert (
        await app_client.post("/api/order-mail/sync", headers=dl)
    ).status_code == 503
    assert len(started) == 2


@pytest.mark.asyncio
async def test_sync_status_projection_flags_and_tcm_redaction(
    app_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(queue_api.settings, "ORDER_MAIL_INGEST_ENABLED", True)
    monkeypatch.setattr(queue_api, "ingest_is_running", lambda: False)

    # Stan zapisany dokładnie tak, jak robi to zakończony bieg (rekord w ``stats``).
    started_at = datetime(2031, 3, 3, 9, 6, tzinfo=timezone.utc)
    finished_at = started_at + timedelta(seconds=40)
    stats = svc.IngestStats(
        reason="manual", messages=3, new_messages=2, needs_review=1, failed=1
    )
    stats.errors.append("attachments <abc>: boom 'Zamowienie Kowalski.pdf'")
    async with AsyncSessionLocal() as db:
        await svc._write_state(
            db,
            last_run_started_at=started_at,
            last_run_finished_at=finished_at,
            last_status="partial",
            last_error=stats.errors[0],
            stats=svc.completed_record(
                stats,
                started_at=started_at,
                finished_at=finished_at,
                status="partial",
                error=stats.errors[0],
            ),
        )

    admin = await _headers_for_role(app_client, UserRole.admin)
    r = await app_client.get("/api/order-mail/sync/status", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True and body["can_trigger"] is True
    assert body["running"] is False and body["interrupted"] is False
    assert body["interval_minutes"] == svc.poll_interval_minutes()
    last = body["last_completed"]
    assert last["reason"] == "manual" and last["status"] == "partial"
    assert (last["new_messages"], last["needs_review"], last["failed"]) == (2, 1, 1)
    assert last["finished_at"] == finished_at.isoformat()
    assert "Kowalski" in last["errors"][0]

    # TCM: liczby tak, treść błędów (nazwy załączników) nie, przycisku nie.
    tcm = await _headers_for_role(app_client, UserRole.talent_community_manager)
    r = await app_client.get("/api/order-mail/sync/status", headers=tcm)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_trigger"] is False
    assert body["last_completed"]["new_messages"] == 2
    assert "Kowalski" not in json.dumps(body)
    assert body["last_completed"]["errors"] == [
        "Sprawdzenie skrzynki zakończyło się błędem."
    ]

    hor = await _headers_for_role(app_client, UserRole.head_of_recruitment)
    assert (
        await app_client.get("/api/order-mail/sync/status", headers=hor)
    ).status_code == 403

    # Nowy bieg zaczął się i nie zapisał końca (restart w trakcie), blokady nie
    # ma → ``interrupted``; poprzedni wynik zostaje przypisany poprawnie.
    async with AsyncSessionLocal() as db:
        await svc._write_state(
            db,
            last_run_started_at=finished_at + timedelta(hours=1),
            last_status="running",
        )
    body = (await app_client.get("/api/order-mail/sync/status", headers=admin)).json()
    assert body["interrupted"] is True and body["running"] is False
    assert body["started_at"] == (finished_at + timedelta(hours=1)).isoformat()
    assert body["last_completed"]["reason"] == "manual"
    assert body["last_completed"]["finished_at"] == finished_at.isoformat()
