"""Powiadomienia Delivery Leada: cykliczność, obsłużenie i raport.

Sedno testów: powtórka co 7 dni jest NOWYM wierszem (raport ma pokazywać, ile
tygodni sprawa czekała), a obsłużenie ją zatrzymuje — nawet gdy warunek trwa.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

_NOW = datetime.now(timezone.utc)


async def _seed_user(role_value: str, client_id: int | None = None):
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"alert-{role_value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Alert {role_value}",
            role=UserRole(role_value),
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        if client_id is not None and role_value == "delivery_lead":
            db.add(
                DeliveryLeadClientAssignment(
                    client_id=client_id, delivery_lead_user_id=user.id
                )
            )
            await db.commit()
        return user.id, email, password


async def _headers_for(app_client: AsyncClient, email: str, password: str) -> dict:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_client(*, display_name: str | None = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"AlertClient-{uuid.uuid4().hex[:6]}",
            display_name=display_name,
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


# ── Cykliczność ─────────────────────────────────────────────────────────────


async def test_repeat_after_seven_days_is_a_new_row_not_an_update():
    """Ticket: każde ponowienie ma być widoczne osobno w historii i raporcie."""
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_BUDGET_LOW, DlAlert
    from app.services.dl_alerts import emit
    from sqlalchemy import select

    client_id = await _seed_client()
    user_id, _, _ = await _seed_user("delivery_lead", client_id)

    async with AsyncSessionLocal() as db:
        first = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="order:1",
            title="t",
            message="m",
            repeat_every_days=7,
            now=_NOW,
        )
        assert len(first) == 1
        # Ten sam dzień — bez nowego wpisu.
        same_day = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="order:1",
            title="t",
            message="m",
            repeat_every_days=7,
            now=_NOW + timedelta(days=3),
        )
        assert same_day == []
        # Po tygodniu — NOWY wiersz, nie aktualizacja poprzedniego.
        later = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="order:1",
            title="t",
            message="m",
            repeat_every_days=7,
            now=_NOW + timedelta(days=8),
        )
        assert len(later) == 1
        await db.commit()

        rows = (
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.user_id == user_id,
                    DlAlert.alert_type == ALERT_MD_BUDGET_LOW,
                )
            )
        ).all()
        assert len(rows) == 2, "powtórka nadpisała poprzedni wpis zamiast dołożyć nowy"


async def test_handled_alert_stops_further_repeats():
    """Człowiek powiedział „zajęte" — system przestaje o tym mówić."""
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import (
        ALERT_MD_BUDGET_LOW,
        DL_ALERT_STATUS_HANDLED,
        DlAlert,
    )
    from app.services.dl_alerts import emit

    client_id = await _seed_client()
    user_id, _, _ = await _seed_user("delivery_lead", client_id)

    async with AsyncSessionLocal() as db:
        created = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="order:2",
            title="t",
            message="m",
            repeat_every_days=7,
            now=_NOW,
        )
        await db.commit()
        alert = await db.get(DlAlert, created[0].id)
        alert.status = DL_ALERT_STATUS_HANDLED
        alert.handled_at = _NOW
        alert.handled_by_user_id = user_id
        await db.commit()

        again = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="order:2",
            title="t",
            message="m",
            repeat_every_days=7,
            now=_NOW + timedelta(days=30),
        )
        assert again == [], "obsłużona sprawa wróciła po tygodniach"


async def test_one_off_alert_never_repeats():
    """Wyczerpanie budżetu opisuje stan, który się już nie zmienia."""
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_COST_ORDER_EXHAUSTED
    from app.services.dl_alerts import emit

    client_id = await _seed_client()
    user_id, _, _ = await _seed_user("delivery_lead", client_id)

    async with AsyncSessionLocal() as db:
        first = await emit(
            db,
            alert_type=ALERT_COST_ORDER_EXHAUSTED,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="group:1",
            title="t",
            message="m",
            repeat_every_days=None,
            now=_NOW,
        )
        await db.commit()
        assert len(first) == 1
        later = await emit(
            db,
            alert_type=ALERT_COST_ORDER_EXHAUSTED,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="group:1",
            title="t",
            message="m",
            repeat_every_days=None,
            now=_NOW + timedelta(days=365),
        )
        assert later == []


async def test_kill_switch_stops_emission(monkeypatch):
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_BUDGET_LOW
    from app.services.dl_alerts import emit

    client_id = await _seed_client()
    user_id, _, _ = await _seed_user("delivery_lead", client_id)
    monkeypatch.setattr(settings, "DL_ALERTS_ENABLED", False)

    async with AsyncSessionLocal() as db:
        created = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key="order:3",
            title="t",
            message="m",
            repeat_every_days=7,
        )
        assert created == []


# ── API ─────────────────────────────────────────────────────────────────────


async def _make_alert(user_id: int, client_id: int, entity: str = "order:9") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_BUDGET_LOW
    from app.services.dl_alerts import emit

    async with AsyncSessionLocal() as db:
        created = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=[user_id],
            client_id=client_id,
            entity_key=entity,
            title="Mało MD",
            message="⏳ Klient — zamówieniu 445 pozostało mniej niż 15 MD.",
            repeat_every_days=7,
        )
        await db.commit()
        return created[0].id


async def test_dl_sees_only_own_alerts(app_client: AsyncClient):
    canonical_name = f"Canonical Alert Client {uuid.uuid4().hex[:6]}"
    client_id = await _seed_client(display_name=f"  {canonical_name}  ")
    mine_id, mine_email, mine_pass = await _seed_user("delivery_lead", client_id)
    other_id, _, _ = await _seed_user("delivery_lead", client_id)
    await _make_alert(mine_id, client_id, "order:100")
    await _make_alert(other_id, client_id, "order:101")

    headers = await _headers_for(app_client, mine_email, mine_pass)
    resp = await app_client.get("/api/dl-alerts", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_new"] == 1
    assert all(a["recipient_user_id"] == mine_id for a in body["alerts"])
    assert {a["client_name"] for a in body["alerts"]} == {canonical_name}


async def test_marking_handled_keeps_the_row_and_stamps_reaction(
    app_client: AsyncClient,
):
    """Wpis NIE znika — to on jest raportem."""
    client_id = await _seed_client()
    user_id, email, password = await _seed_user("delivery_lead", client_id)
    alert_id = await _make_alert(user_id, client_id, "order:102")
    headers = await _headers_for(app_client, email, password)

    resp = await app_client.post(f"/api/dl-alerts/{alert_id}/handled", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "handled"
    assert body["handled_at"] is not None
    assert body["reaction_seconds"] is not None

    history = await app_client.get(
        "/api/dl-alerts", params={"status": "handled"}, headers=headers
    )
    assert [a["id"] for a in history.json()["alerts"]] == [alert_id]


async def test_cannot_handle_someone_elses_alert(app_client: AsyncClient):
    client_id = await _seed_client()
    owner_id, _, _ = await _seed_user("delivery_lead", client_id)
    _, email, password = await _seed_user("delivery_lead", client_id)
    alert_id = await _make_alert(owner_id, client_id, "order:103")

    headers = await _headers_for(app_client, email, password)
    resp = await app_client.post(f"/api/dl-alerts/{alert_id}/handled", headers=headers)
    # 404, nie 403 — cudzy wpis nie potwierdza nawet swojego istnienia.
    assert resp.status_code == 404, resp.text


async def test_bulk_export_is_limited_to_admin_and_finance(app_client: AsyncClient):
    client_id = await _seed_client()
    dl_id, dl_email, dl_pass = await _seed_user("delivery_lead", client_id)
    await _make_alert(dl_id, client_id, "order:104")
    dl_headers = await _headers_for(app_client, dl_email, dl_pass)

    own = await app_client.get(
        "/api/dl-alerts/export", params={"scope": "mine"}, headers=dl_headers
    )
    assert own.status_code == 200, own.text
    assert own.headers["content-type"].startswith("application/vnd.openxmlformats")

    forbidden = await app_client.get(
        "/api/dl-alerts/export", params={"scope": "all"}, headers=dl_headers
    )
    assert forbidden.status_code == 403, forbidden.text

    _, fin_email, fin_pass = await _seed_user("finance")
    fin_headers = await _headers_for(app_client, fin_email, fin_pass)
    allowed = await app_client.get(
        "/api/dl-alerts/export", params={"scope": "all"}, headers=fin_headers
    )
    assert allowed.status_code == 200, allowed.text


async def test_export_escapes_formula_injection():
    """Treść alertu niesie nazwy wpisane przez ludzi — to tekst obcy."""
    from app.api.dl_alerts import _formula_safe

    assert _formula_safe("=1+1") == "'=1+1"
    assert _formula_safe("@SUM(A1)") == "'@SUM(A1)"
    assert _formula_safe("Polkomtel") == "Polkomtel"


# ── Reguły skanera ──────────────────────────────────────────────────────────


async def test_scanner_flags_draft_consultant_without_order(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus
    from app.models.dl_alert import ALERT_DRAFT_CONSULTANT_UNASSIGNED, DlAlert
    from app.tasks.dl_alerts_scanner import rule_draft_consultant_unassigned
    from sqlalchemy import select

    client_id = await _seed_client()
    user_id, _, _ = await _seed_user("delivery_lead", client_id)

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Szkic",
            lastname=f"Osoba-{uuid.uuid4().hex[:6]}",
            email=f"draft-{uuid.uuid4().hex[:6]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client_id,
            status=ContractStatus.draft,
            rate_candidate=Decimal("100.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract.id,
                title="Do uzupełnienia",
                status=ClientOrderStatus.draft,
            )
        )
        await db.commit()

        created = await rule_draft_consultant_unassigned(db)
        await db.commit()
        assert created >= 1

        rows = (
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.user_id == user_id,
                    DlAlert.alert_type == ALERT_DRAFT_CONSULTANT_UNASSIGNED,
                )
            )
        ).all()
        assert rows, "konsultant w Draft nie wygenerował alertu"


async def test_scanner_uses_a_single_rule_registry():
    """Dołożenie typu ma być dopisaniem reguły, nie przebudową skanera."""
    from app.models.dl_alert import (
        ALERT_DRAFT_CONSULTANT_UNASSIGNED,
        ALERT_MD_BUDGET_LOW,
        ALERT_MISSING_REVENUE_RATE,
    )
    from app.tasks.dl_alerts_scanner import ALERT_RULES

    assert set(ALERT_RULES) == {
        ALERT_DRAFT_CONSULTANT_UNASSIGNED,
        ALERT_MD_BUDGET_LOW,
        ALERT_MISSING_REVENUE_RATE,
    }


def test_md_threshold_is_global_not_per_client():
    """Ticket wprost zabrania konfiguracji progu per klient."""
    from app.core.config import settings

    assert settings.DL_ALERT_MD_THRESHOLD == pytest.approx(15.0)
    assert settings.DL_ALERT_REPEAT_DAYS == 7


async def test_roles_without_a_reason_to_be_here_are_rejected(app_client: AsyncClient):
    """Bramka jest ZALEŻNOŚCIOWA, nie tylko filtrem w ciele handlera.

    Filtr po `user_id` jest poprawny, ale niewidoczny w OpenAPI i
    nieegzekwowany dla następnego handlera dopisanego do tego routera —
    dokładnie to wychwycił `test_route_authz_contract`.
    """
    for role in ("recruiter", "sourcer", "tac"):
        _, email, password = await _seed_user(role)
        headers = await _headers_for(app_client, email, password)
        resp = await app_client.get("/api/dl-alerts", headers=headers)
        assert resp.status_code == 403, f"{role} -> {resp.status_code}"
