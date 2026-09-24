"""Ręczne usuwanie klienta z profilu + Historia zdarzeń — testy na żywej bazie.

Baza testowa jest WSPÓLNA dla przebiegu i nie jest czyszczona, więc każdy test
zakłada własnych klientów i użytkowników i czyta Historię zdarzeń wyłącznie po
identyfikatorach, które sam utworzył. Osoby, firmy i numery są zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.client_cleanup import PurgedClient
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.critical_event import CriticalEvent
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.critical_events import audited_deletion
from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio


async def _user(
    app_client: AsyncClient,
    *,
    role: UserRole = UserRole.admin,
    can_delete_clients: bool = False,
) -> tuple[int, dict[str, str]]:
    unique = uuid.uuid4().hex[:8]
    email = f"cdel-{role.value}-{unique}@example.com"
    password = f"P4ss_{unique}!X"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Tester {role.value} {unique}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
            can_delete_clients=can_delete_clients,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _client(
    tag: str,
    *,
    status: ClientStatus = ClientStatus.active,
    category: PortfolioCategory | None = PortfolioCategory.active,
    external_id: str | None = None,
) -> int:
    from app.services.inactive_client_cleanup_signals import code_configured_client_ids

    # ID zaszyte w kodzie (e-Zdrowie, Polkomtel, kanoniczne ID polityk PDF…)
    # robią z klienta „klienta z historią". Baza testowa nadaje ID po kolei,
    # więc to, czy ten klient na takie trafi, zależało od tego, ile klientów
    # założyły wcześniejsze testy w shardzie — test przechodził albo nie
    # w zależności od przetasowania shardów. Zarezerwowane ID omijamy.
    reserved = set(code_configured_client_ids())
    async with AsyncSessionLocal() as db:
        while True:
            client = Client(
                name=f"Firma Testowa {tag} {uuid.uuid4().hex[:6]}",
                status=status,
                external_source="traffit" if external_id else "manual",
                external_id=external_id,
            )
            db.add(client)
            await db.flush()
            if client.id not in reserved:
                break
            # Nie zostawiamy obcego wiersza pod zarezerwowanym ID we wspólnej bazie.
            await db.delete(client)
            await db.flush()
        if category is not None:
            db.add(ClientPortfolioScope(client_id=client.id, category=category))
        await db.commit()
        return client.id


async def _contract(
    client_id: int,
    *,
    status: ContractStatus,
    order_status: ClientOrderStatus | None = None,
) -> tuple[int, int | None]:
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan", lastname=f"Testowy-{suffix}", email=f"cdel-{suffix}@example.com"
        )
        db.add(candidate)
        await db.flush()
        ended = status == ContractStatus.ended
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            status=status,
            start_date=business_today() - timedelta(days=400 if ended else 30),
            end_date=business_today() - timedelta(days=30) if ended else None,
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("140.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.flush()
        order_id = None
        if order_status is not None:
            order = ClientOrder(
                client_id=client_id,
                contract_id=contract.id,
                title=f"ZAM-{suffix}",
                status=order_status,
                order_type="periodic",
                rate_unit=RateUnit.hourly,
                start_date=business_today() - timedelta(days=60),
                end_date=(
                    business_today() - timedelta(days=31)
                    if order_status == ClientOrderStatus.completed
                    else business_today() + timedelta(days=60)
                ),
            )
            db.add(order)
            await db.flush()
            order_id = order.id
        await db.commit()
        return contract.id, order_id


async def _events(client_id: int) -> list[CriticalEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(CriticalEvent)
                    .where(
                        CriticalEvent.event_type == "client.delete",
                        CriticalEvent.client_id == client_id,
                    )
                    .order_by(CriticalEvent.id)
                )
            )
            .scalars()
            .all()
        )


async def _client_row(client_id: int) -> Client | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Client).where(Client.id == client_id))


# ── Uprawnienie imienne ──────────────────────────────────────────────────────


async def test_admin_without_named_permission_is_refused_and_attempt_is_logged(
    app_client: AsyncClient,
):
    client_id = await _client("bez-uprawnien")
    actor_id, headers = await _user(app_client, role=UserRole.admin)

    check = await app_client.post(
        f"/api/clients/{client_id}/deletion-check", headers=headers
    )
    delete = await app_client.delete(
        f"/api/clients/{client_id}", params={"confirmation": "0"}, headers=headers
    )

    assert check.status_code == 403
    assert delete.status_code == 403
    assert await _client_row(client_id) is not None
    events = await _events(client_id)
    # Odmowy „brak uprawnienia" tej samej osoby wobec tego samego klienta są
    # zapisywane raz na okno — powtórki nie zapychają dziennika.
    assert [event.outcome for event in events] == ["blocked"]
    assert events[0].reason_code == "no_permission"
    assert events[0].actor_user_id == actor_id


async def test_me_exposes_the_named_permission(app_client: AsyncClient):
    _, allowed = await _user(app_client, role=UserRole.finance, can_delete_clients=True)
    _, other = await _user(app_client, role=UserRole.admin)

    me_allowed = await app_client.get("/api/auth/me", headers=allowed)
    me_other = await app_client.get("/api/auth/me", headers=other)

    assert me_allowed.json()["can_delete_clients"] is True
    assert me_other.json()["can_delete_clients"] is False


# ── Blokada twarda ───────────────────────────────────────────────────────────


async def test_open_order_blocks_even_when_client_is_marked_inactive(
    app_client: AsyncClient,
):
    client_id = await _client(
        "blad-statusu",
        status=ClientStatus.inactive,
        category=PortfolioCategory.inactive,
    )
    await _contract(
        client_id,
        status=ContractStatus.active,
        order_status=ClientOrderStatus.active,
    )
    _, headers = await _user(app_client, can_delete_clients=True)

    check = await app_client.post(
        f"/api/clients/{client_id}/deletion-check", headers=headers
    )
    assert check.status_code == 200, check.text
    body = check.json()
    assert body["mode"] == "blocked"
    assert body["can_delete"] is False
    codes = {blocker["code"] for blocker in body["blockers"]}
    assert codes == {"open_orders", "active_contractors"}

    delete = await app_client.delete(
        f"/api/clients/{client_id}", params={"confirmation": "0"}, headers=headers
    )
    assert delete.status_code == 409, delete.text
    assert delete.json()["check"]["mode"] == "blocked"

    assert await _client_row(client_id) is not None
    events = await _events(client_id)
    # Kliknięcie „Usuń klienta" i próba wykonania — dwie zablokowane próby.
    assert [event.outcome for event in events] == ["blocked", "blocked"]
    assert "Otwarte zamówienia" in (events[0].reason or "")
    assert "Aktywni kontraktorzy" in (events[0].reason or "")
    assert events[0].details["client_status"] == "inactive"
    # Okno pokazuje nazwiska na żywo, ale dziennik ich nie przechowuje — wpis
    # przeżywa usunięcie osoby (art. 17 RODO).
    assert "Testowy" in str(body["blockers"])
    assert "Testowy" not in str(events[0].details)
    assert "Testowy" not in (events[0].reason or "")


async def test_working_consultant_on_a_closed_md_order_still_blocks(
    app_client: AsyncClient,
):
    """Zamówienie MD zamknięte z datą w przyszłości: grupa `completed`, linia
    nadal `active`, a kontrakt osoby dodanej z bazy to szkic."""

    client_id = await _client("md-zamkniete")
    contract_id, _ = await _contract(client_id, status=ContractStatus.draft)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"MD-{uuid.uuid4().hex[:6]}",
            start_date=business_today() - timedelta(days=60),
            status="completed",
            closure_date=business_today() + timedelta(days=20),
            order_type=None,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                order_group_id=group.id,
                title=f"Zamówienie {group.order_number}",
                status=ClientOrderStatus.active,
                start_date=business_today() - timedelta(days=60),
                rate_unit=RateUnit.daily,
            )
        )
        await db.commit()
    _, headers = await _user(app_client, can_delete_clients=True)

    check = await app_client.post(
        f"/api/clients/{client_id}/deletion-check", headers=headers
    )

    body = check.json()
    assert body["mode"] == "blocked"
    assert [b["code"] for b in body["blockers"]] == ["open_orders"]
    assert body["blockers"][0]["count"] == 1


async def test_candidates_in_open_recruitment_block_deletion(app_client: AsyncClient):
    client_id = await _client("rekrutacja")
    async with AsyncSessionLocal() as db:
        job = Job(
            title="Programista testowy",
            client_id=client_id,
            status=JobStatus.published,
        )
        candidate = Candidate(name="Ewa", lastname=f"Kandydatka-{uuid.uuid4().hex[:6]}")
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id, job_id=job.id, stage=PipelineStage.new
            )
        )
        await db.commit()
    _, headers = await _user(app_client, can_delete_clients=True)

    check = await app_client.post(
        f"/api/clients/{client_id}/deletion-check", headers=headers
    )

    body = check.json()
    assert body["mode"] == "blocked"
    assert [b["code"] for b in body["blockers"]] == ["candidates_in_open_recruitments"]
    assert body["blockers"][0]["count"] == 1


# ── Klient pusty: trwale, po wpisaniu „0" ────────────────────────────────────


async def test_empty_client_needs_zero_and_is_purged_with_tombstone(
    app_client: AsyncClient,
):
    external_id = f"cdel-{uuid.uuid4().hex[:10]}"
    client_id = await _client("pusty", external_id=external_id)
    _, headers = await _user(app_client, role=UserRole.finance, can_delete_clients=True)

    check = await app_client.post(
        f"/api/clients/{client_id}/deletion-check", headers=headers
    )
    assert check.json()["mode"] == "purge"
    assert check.json()["history"] == []
    assert check.json()["confirmation_phrase"] == "0"

    for wrong in ("", "1", "tak"):
        refused = await app_client.delete(
            f"/api/clients/{client_id}",
            params={"confirmation": wrong},
            headers=headers,
        )
        assert refused.status_code == 422
    assert await _client_row(client_id) is not None

    done = await app_client.delete(
        f"/api/clients/{client_id}", params={"confirmation": "0"}, headers=headers
    )
    assert done.status_code == 200, done.text
    assert done.json()["result"] == "purged"

    assert await _client_row(client_id) is None
    async with AsyncSessionLocal() as db:
        tombstone = await db.scalar(
            select(PurgedClient).where(PurgedClient.client_id == client_id)
        )
    assert tombstone is not None
    assert tombstone.run_id is None
    assert tombstone.external_id == external_id

    events = await _events(client_id)
    assert [event.outcome for event in events] == ["executed"]
    assert events[0].reason_code == "purged"
    assert events[0].entity_label and events[0].entity_label.startswith("Firma Testowa")


# ── Klient z historią: znika z list, dane zostają ────────────────────────────


async def test_client_with_history_is_hidden_and_history_is_kept(
    app_client: AsyncClient,
):
    client_id = await _client("historia", status=ClientStatus.active)
    contract_id, order_id = await _contract(
        client_id,
        status=ContractStatus.ended,
        order_status=ClientOrderStatus.completed,
    )
    actor_id, headers = await _user(app_client, can_delete_clients=True)

    check = await app_client.post(
        f"/api/clients/{client_id}/deletion-check", headers=headers
    )
    body = check.json()
    assert body["mode"] == "archive"
    assert body["blockers"] == []
    sentence = body["history_sentence"]
    assert sentence.startswith("U tego klienta występują:")
    assert "archiwum konsultantów" in sentence
    assert "poprzednie zamówienia" in sentence

    done = await app_client.delete(
        f"/api/clients/{client_id}", params={"confirmation": "0"}, headers=headers
    )
    assert done.status_code == 200, done.text
    assert done.json()["result"] == "archived"

    row = await _client_row(client_id)
    assert row is not None
    assert row.deleted_at is not None
    assert row.deleted_by == actor_id
    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, contract_id) is not None
        assert await db.get(ClientOrder, order_id) is not None

    profile = await app_client.get(f"/api/clients/{client_id}", headers=headers)
    assert profile.status_code == 404
    again = await app_client.post(
        f"/api/clients/{client_id}/deletion-check", headers=headers
    )
    assert again.status_code == 404

    events = await _events(client_id)
    assert [event.outcome for event in events] == ["executed"]
    assert events[0].reason_code == "archived"
    assert "dane historyczne zachowane" in (events[0].reason or "")


# ── Historia zdarzeń: odczyt i uprawnienia ───────────────────────────────────


async def test_event_history_is_admin_and_finance_only(app_client: AsyncClient):
    client_id = await _client("dziennik")
    _, deleter = await _user(app_client, can_delete_clients=True)
    await app_client.delete(
        f"/api/clients/{client_id}", params={"confirmation": "0"}, headers=deleter
    )

    _, finance = await _user(app_client, role=UserRole.finance)
    _, admin = await _user(app_client, role=UserRole.admin)
    _, dl = await _user(app_client, role=UserRole.delivery_lead)
    _, recruiter = await _user(app_client, role=UserRole.recruiter)

    for headers in (finance, admin):
        response = await app_client.get(
            "/api/settings/event-history",
            params={"entity_type": "client", "q": "dziennik"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        items = [
            item for item in response.json()["items"] if item["client_id"] == client_id
        ]
        assert len(items) == 1
        assert items[0]["event_label"] == "Usunięcie klienta"
        assert items[0]["outcome_label"] == "Wykonano"
    for headers in (dl, recruiter):
        response = await app_client.get("/api/settings/event-history", headers=headers)
        assert response.status_code == 403


async def test_granting_the_permission_is_itself_logged(app_client: AsyncClient):
    target_id, _ = await _user(app_client, role=UserRole.delivery_lead)
    _, admin = await _user(app_client, role=UserRole.admin)

    granted = await app_client.put(
        f"/api/admin/users/{target_id}",
        json={"can_delete_clients": True},
        headers=admin,
    )
    assert granted.status_code == 200, granted.text
    listing = await app_client.get("/api/admin/users", headers=admin)
    row = next(item for item in listing.json() if item["id"] == target_id)
    assert row["can_delete_clients"] is True

    async with AsyncSessionLocal() as db:
        events = list(
            (
                await db.execute(
                    select(CriticalEvent).where(
                        CriticalEvent.event_type == "user.client_delete_permission",
                        CriticalEvent.entity_id == target_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [event.reason_code for event in events] == ["granted"]


# ── Pozostałe usunięcia w Historii zdarzeń ───────────────────────────────────


async def test_framework_contract_and_order_deletions_are_logged(
    app_client: AsyncClient,
):
    client_id = await _client("umowy")
    _, order_id = await _contract(
        client_id,
        status=ContractStatus.active,
        order_status=ClientOrderStatus.draft,
    )
    async with AsyncSessionLocal() as db:
        framework = ClientFrameworkContract(
            client_id=client_id,
            name="Umowa ramowa testowa",
            status=FrameworkContractStatus.draft,
        )
        db.add(framework)
        await db.commit()
        framework_id = framework.id
    _, admin = await _user(app_client, role=UserRole.admin)

    fc = await app_client.delete(
        f"/api/clients/{client_id}/framework-contracts/{framework_id}", headers=admin
    )
    order = await app_client.delete(
        f"/api/clients/{client_id}/orders/{order_id}", headers=admin
    )
    assert fc.status_code == 204, fc.text
    assert order.status_code == 204, order.text

    async with AsyncSessionLocal() as db:
        rows = {
            event.event_type: event
            for event in (
                await db.execute(
                    select(CriticalEvent).where(CriticalEvent.client_id == client_id)
                )
            )
            .scalars()
            .all()
        }
    assert rows["framework_contract.delete"].entity_type == "agreement"
    assert rows["framework_contract.delete"].entity_label == "Umowa ramowa testowa"
    assert rows["order.delete"].entity_type == "order"
    assert rows["order.delete"].outcome == "executed"
    assert "Szkic" in (rows["order.delete"].reason or "")


async def test_audited_deletion_records_a_refusal_in_its_own_session():
    marker = f"ZAM-ODMOWA-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException):
            async with audited_deletion(
                db,
                actor=None,
                event_type="order.delete",
                entity_type="order",
                entity_id=None,
            ) as audit:
                audit.describe(label=marker)
                raise HTTPException(409, detail="Są rozliczenia na tym zamówieniu.")
        await db.rollback()

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(CriticalEvent).where(CriticalEvent.entity_label == marker)
        )
    assert event is not None
    assert event.outcome == "blocked"
    assert event.reason_code == "http_409"
    assert event.reason == "Są rozliczenia na tym zamówieniu."
