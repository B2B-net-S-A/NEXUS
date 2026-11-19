"""Jeden zespół back office'u (decyzje Artura z 10.11 i 19.11.2026).

Skład w ``bo_members``: członek ma wszystkie etykiety (bez „Zastępuję”),
„Na zewnątrz”, „Weź następną”, sprawy osób spoza zespołu wracają do kolejki,
przegląd hurtem, konsultanci i ściąga klienta bez opiekuna.

Baza testowa nie jest czyszczona między testami: asercje dotyczą wyłącznie kart
i kont założonych w danym teście. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.back_office import BoCard, BoClientNote, BoMember, BoTeamMember
from app.models.client import Client
from app.models.user import User, UserRole
from app.services.back_office_schema import BACK_OFFICE_SETTING
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(
    role: str = "recruiter", *, member: bool = False, member_role: str = "member"
) -> User:
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"bo1-{marker}@example.com",
            name=f"Osoba Przykładowa {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if member:
            db.add(BoMember(user_id=user.id, role=member_role))
        await db.commit()
        await db.refresh(user)
        return user


async def _card(**fields) -> BoCard:
    marker = uuid.uuid4().hex[:12]
    values = {
        "team": "orders",
        "lane": "gap",
        "source_kind": "gap",
        "source_key": f"test1:{marker}",
        "title": "Przerwa po zamówieniu",
        "state": "new",
        "meta": {},
    }
    async with AsyncSessionLocal() as db:
        card = BoCard(**{**values, **fields})
        db.add(card)
        await db.commit()
        await db.refresh(card)
        return card


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _clean() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoMember))
        await db.execute(delete(BoTeamMember))
        await db.execute(delete(BoCard).where(BoCard.source_key.like("test1:%")))
        await db.commit()


@pytest_asyncio.fixture
async def one_team():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        settings_row = await db.get(AppSetting, BACK_OFFICE_SETTING)
        previous_settings = settings_row.value if settings_row is not None else None
    await _clean()
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})
    await _clean()
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, BACK_OFFICE_SETTING)
        if previous_settings is None and row is not None:
            await db.delete(row)
        elif row is not None:
            row.value = previous_settings
        await db.commit()


@pytest.mark.asyncio
async def test_member_takes_any_label_and_outsider_is_refused(
    app_client, one_team
) -> None:
    member = await _user(member=True)
    outsider = await _user()
    card = await _card(team="finance", lane="changes", source_kind="gap")
    refused = await app_client.get("/api/back-office/board", headers=_headers(outsider))
    assert refused.status_code == 403
    taken = await app_client.post(
        f"/api/back-office/cards/{card.id}/take", json={}, headers=_headers(member)
    )
    assert taken.status_code == 200
    assert taken.json()["substituting"] is False
    assert taken.json()["amounts"] is None


@pytest.mark.asyncio
async def test_member_reads_negotiation_without_substitute(
    app_client, one_team
) -> None:
    member = await _user(member=True)
    card = await _card(
        team="contracts",
        lane="annex",
        source_kind="case",
        title="Nowa stawka od stycznia",
        person="Osoba Przykładowa",
        meta={"area": "negotiation"},
    )
    seen = await app_client.get(
        f"/api/back-office/cards/{card.id}", headers=_headers(member)
    )
    assert seen.status_code == 200
    assert seen.json()["title"] == "Nowa stawka od stycznia"
    assert seen.json()["person"] == "Osoba Przykładowa"


@pytest.mark.asyncio
async def test_board_shows_one_card_per_event_and_labels(app_client, one_team) -> None:
    member = await _user(member=True)
    exit_case = await _card(team="care", lane="exit", source_kind="case")
    step = await _card(
        team="orders",
        lane="extend",
        source_kind="step",
        parent_card_id=exit_case.id,
        title="Zamknięcie linii zamówienia",
    )
    board = await app_client.get("/api/back-office/board", headers=_headers(member))
    assert board.status_code == 200
    ids = {card["id"] for card in board.json()["cards"]}
    assert exit_case.id in ids
    assert step.id not in ids
    labels = {row["id"]: row["label"] for row in board.json()["labels"]}
    assert labels["extend"] == "Przedłużenie"
    assert {row["id"] for row in board.json()["outside_teams"]} >= {"it", "legal"}


@pytest.mark.asyncio
async def test_outside_needs_a_note_and_any_state_change_clears_it(
    app_client, one_team
) -> None:
    member = await _user(member=True)
    card = await _card()
    headers = _headers(member)
    empty = await app_client.post(
        f"/api/back-office/cards/{card.id}/outside",
        json={"team": "it", "note": " "},
        headers=headers,
    )
    assert empty.status_code == 422
    unknown = await app_client.post(
        f"/api/back-office/cards/{card.id}/outside",
        json={"team": "marketing", "note": "Konto w systemie klienta"},
        headers=headers,
    )
    assert unknown.status_code == 422
    sent = await app_client.post(
        f"/api/back-office/cards/{card.id}/outside",
        json={"team": "it", "note": "Konto w systemie klienta"},
        headers=headers,
    )
    assert sent.status_code == 200
    body = sent.json()
    assert (body["state"], body["outside_team"]) == ("waiting", "it")
    assert body["waiting_on"] == "Konto w systemie klienta"
    # Bez osoby nikt nie pilnowałby odpowiedzi działu.
    assert body["assignee"]["id"] == member.id
    back = await app_client.post(
        f"/api/back-office/cards/{card.id}/state",
        json={"state": "in_progress"},
        headers=headers,
    )
    assert back.status_code == 200
    assert back.json()["outside_team"] is None


@pytest.mark.asyncio
async def test_next_takes_the_oldest_due_and_skips_foreign_priority(
    app_client, one_team
) -> None:
    today = business_today()
    member = await _user(member=True)
    holder = await _user(member=True)
    async with AsyncSessionLocal() as db:
        # Inne testy mogą zostawić stare karty: odsuwamy je poza ten test.
        await db.execute(
            BoCard.__table__.update()
            .where(BoCard.state == "new", BoCard.assignee_user_id.is_(None))
            .where(~BoCard.source_key.like("test1:%"))
            .values(due_on=today + timedelta(days=3650))
        )
        await db.commit()
    priority = await _card(
        due_on=today - timedelta(days=30),
        priority_user_id=holder.id,
        priority_until=today + timedelta(days=2),
    )
    oldest = await _card(due_on=today - timedelta(days=20))
    await _card(due_on=today - timedelta(days=5))
    response = await app_client.post("/api/back-office/next", headers=_headers(member))
    assert response.status_code == 200
    assert response.json()["id"] == oldest.id
    assert response.json()["assignee"]["id"] == member.id
    async with AsyncSessionLocal() as db:
        assert (await db.get(BoCard, priority.id)).assignee_user_id is None


@pytest.mark.asyncio
async def test_next_stops_at_the_limit(app_client, one_team) -> None:
    member = await _user(member=True)
    for _ in range(5):
        await _card(assignee_user_id=member.id, state="in_progress")
    await _card()
    response = await app_client.post("/api/back-office/next", headers=_headers(member))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "limit"


@pytest.mark.asyncio
async def test_team_roles_one_deputy_and_deputy_leads(app_client, one_team) -> None:
    admin = await _user("admin")
    first = await _user()
    second = await _user()
    headers = _headers(admin)
    for person in (first, second):
        added = await app_client.put(
            f"/api/back-office/team/members/{person.id}",
            json={"role": "deputy", "takes_calls": False},
            headers=headers,
        )
        assert added.status_code == 200, added.text
    roles = {row["user_id"]: row["role"] for row in added.json()["members"]}
    # Nowy zastępca zdejmuje rolę poprzedniemu: jeden naraz.
    assert roles == {first.id: "member", second.id: "deputy"}
    lead_view = await app_client.get("/api/back-office/team", headers=_headers(second))
    assert lead_view.status_code == 200
    member_view = await app_client.get("/api/back-office/team", headers=_headers(first))
    assert member_view.status_code == 403
    removed = await app_client.delete(
        f"/api/back-office/team/members/{first.id}", headers=headers
    )
    assert removed.status_code == 200
    assert [row["user_id"] for row in removed.json()["members"]] == [second.id]


@pytest.mark.asyncio
async def test_outside_contacts_need_active_accounts(app_client, one_team) -> None:
    admin = await _user("admin")
    contact = await _user()
    async with AsyncSessionLocal() as db:
        gone = User(
            email=f"bo1-gone-{uuid.uuid4().hex[:8]}@example.com",
            name="Osoba Nieaktywna",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=False,
            profile_completed=True,
        )
        db.add(gone)
        await db.commit()
        await db.refresh(gone)
    bad = await app_client.put(
        "/api/back-office/team/outside-contacts",
        json={"contacts": {"it": gone.id}},
        headers=_headers(admin),
    )
    assert bad.status_code == 422
    ok = await app_client.put(
        "/api/back-office/team/outside-contacts",
        json={"contacts": {"it": contact.id}},
        headers=_headers(admin),
    )
    assert ok.status_code == 200
    it_row = next(row for row in ok.json()["outside_contacts"] if row["id"] == "it")
    assert it_row["contact"]["id"] == contact.id


@pytest.mark.asyncio
async def test_cases_of_people_outside_the_team_go_back_to_the_queue(
    app_client, one_team
) -> None:
    admin = await _user("admin")
    nobody = await app_client.post(
        "/api/back-office/team/release-outsiders", headers=_headers(admin)
    )
    assert nobody.status_code == 422  # bez składu „spoza” nic nie znaczy
    member = await _user(member=True)
    outsider = await _user("delivery_lead")
    kept = await _card(assignee_user_id=member.id, state="in_progress")
    returned = await _card(
        assignee_user_id=outsider.id, state="waiting", waiting_on="klienta"
    )
    team_view = await app_client.get("/api/back-office/team", headers=_headers(admin))
    assert any(row["user_id"] == outsider.id for row in team_view.json()["outsiders"])
    released = await app_client.post(
        "/api/back-office/team/release-outsiders", headers=_headers(admin)
    )
    assert released.status_code == 200
    assert released.json()["released"] >= 1
    async with AsyncSessionLocal() as db:
        back = await db.get(BoCard, returned.id)
        assert (back.assignee_user_id, back.state, back.waiting_on) == (
            None,
            "new",
            None,
        )
        assert (await db.get(BoCard, kept.id)).assignee_user_id == member.id


@pytest.mark.asyncio
async def test_bulk_review_closes_with_a_reason(app_client, one_team) -> None:
    admin = await _user("admin")
    first = await _card(needs_review=True)
    second = await _card(needs_review=True)
    closed = await _card(state="done", closed_at=datetime.now(timezone.utc))
    response = await app_client.post(
        "/api/back-office/review/bulk",
        json={
            "card_ids": [first.id, second.id, closed.id],
            "decision": "close",
            "note": "Przegląd przed startem: starsze niż 60 dni",
        },
        headers=_headers(admin),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"done": 2, "skipped": 1}
    async with AsyncSessionLocal() as db:
        for card_id in (first.id, second.id):
            card = await db.get(BoCard, card_id)
            assert card.state == "done"
            assert card.meta.get("dismissed") is True
            assert card.needs_review is False


@pytest.mark.asyncio
async def test_consultants_and_client_sheet_for_the_team_only(
    app_client, one_team
) -> None:
    member = await _user(member=True)
    outsider = await _user()
    for url in ("/api/back-office/consultants", "/api/back-office/clients"):
        assert (
            await app_client.get(url, headers=_headers(outsider))
        ).status_code == 403
        assert (await app_client.get(url, headers=_headers(member))).status_code == 200
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Przykładowy {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
    url = f"/api/back-office/clients/{client.id}"
    saved = await app_client.put(
        f"{url}/notes/settlement",
        json={"body": "Raport godzin z portalu klienta do 3. dnia roboczego."},
        headers=_headers(member),
    )
    assert saved.status_code == 200, saved.text
    block = next(row for row in saved.json()["blocks"] if row["id"] == "settlement")
    assert block["body"].startswith("Raport godzin")
    assert block["updated_by"] == member.name
    bad = await app_client.put(
        f"{url}/notes/marketing", json={"body": "x"}, headers=_headers(member)
    )
    assert bad.status_code == 422
    cleared = await app_client.put(
        f"{url}/notes/settlement", json={"body": " "}, headers=_headers(member)
    )
    assert cleared.status_code == 200
    async with AsyncSessionLocal() as db:
        assert await db.get(BoClientNote, (client.id, "settlement")) is None
        await db.delete(await db.get(Client, client.id))
        await db.commit()
