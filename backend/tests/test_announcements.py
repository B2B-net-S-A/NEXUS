"""„Ogłoszenia” na pulpicie (0617, decyzja Artura 28.10.2026).

Publikują Head of Recruitment i admin; odbiorcy to wszyscy albo wybrane role;
„przeczytane” per osoba; po dniu „widoczne do” ogłoszenie znika samo.
Baza testowa jest wspólna i nieczyszczona — testy asertują tylko po swoich
kontach i ogłoszeniach.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.scheduling import business_today
from app.services import announcements
from app.services.announcements_schema import ENUM_DDL, INDEX_DDL, TABLE_DDL
from app.services.notification_mail_card import build_card

_DB = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL")
BACKEND = Path(__file__).resolve().parents[1]


# ── Bez bazy ──────────────────────────────────────────────────────────────────


def _input(**overrides) -> announcements.AnnouncementInput:
    values = dict(
        title="Piątek: Daily o 9:30",
        body="W piątek Daily wyjątkowo o 9:30.",
        visible_until=business_today() + timedelta(days=3),
    )
    values.update(overrides)
    return announcements.AnnouncementInput(**values)


def test_entrypoint_mirrors_the_migration() -> None:
    entry = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert f'"{ENUM_DDL}"' in entry
    assert "from app.services import announcements_schema" in entry
    assert "*_announcements_schema.TABLE_DDL" in entry
    assert "*_announcements_schema.INDEX_DDL" in entry
    migration = (BACKEND / "alembic/versions/0617_announcements.py").read_text()
    assert "ENUM_DDL, INDEX_DDL, TABLE_DDL" in migration
    assert len(TABLE_DDL) == 2 and len(INDEX_DDL) == 2


def test_clean_normalizes_and_refuses_bad_input() -> None:
    today = business_today()
    data = announcements.clean(
        _input(title="  Nowe   zasady  ", audience_roles=("recruiter", "recruiter"))
    )
    assert data.title == "Nowe zasady"
    assert data.audience_roles == ("recruiter",)
    for bad, needle in (
        (_input(title="ab"), "Tytuł"),
        (_input(body="   "), "Treść"),
        (_input(body="Klik <a href='x'>tu</a>"), "HTML"),
        (_input(visible_until=today - timedelta(days=1)), "przeszłości"),
        (_input(visible_until=today + timedelta(days=91)), "90 dni"),
        (_input(audience_roles=("ceo",)), "ceo"),
        (_input(audience_roles=("user",)), "user"),
    ):
        with pytest.raises(announcements.AnnouncementError) as err:
            announcements.clean(bad)
        assert err.value.status == 422
        assert needle in err.value.detail
    # „a < b” i „<3” to nie znaczniki.
    assert announcements.clean(_input(body="Cel: a < b, dzięki <3")).body


class _U:
    def __init__(self, *roles: str) -> None:
        self.roles = roles

    def has_role(self, role: str) -> bool:
        return role in self.roles


class _A:
    def __init__(self, roles: list[str], until: date, withdrawn=None) -> None:
        self.audience_roles = roles
        self.visible_until = until
        self.withdrawn_at = withdrawn


def test_audience_and_expiry_rules() -> None:
    today = date(2026, 10, 28)
    everyone = _A([], today)
    for_dl = _A(["delivery_lead"], today)
    assert announcements.addressed_to(everyone, _U("recruiter"))
    assert announcements.addressed_to(for_dl, _U("recruiter", "delivery_lead"))
    assert not announcements.addressed_to(for_dl, _U("recruiter"))
    # „Widoczne do” obowiązuje do końca tego dnia, zdjęte nie obowiązuje.
    assert announcements.is_live(everyone, today)
    assert not announcements.is_live(everyone, today + timedelta(days=1))
    assert not announcements.is_live(_A([], today, withdrawn=object()), today)


def test_mail_card_uses_the_announcement_title() -> None:
    card = build_card(
        notification_type="announcement_important",
        kind="announcement",
        title="Od 03.11 Nordea tylko przez Cpro",
        message="Treść (widoczne do 07.11)",
        link="/dashboard",
        required=True,
    )
    assert "Nordea" in card.subject
    assert card.buttons[0].path == "/dashboard"


# ── Z bazą ────────────────────────────────────────────────────────────────────


async def _user(role: str, *, roles: list[str] | None = None):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"ann-{role}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Ann"),
            name=f"Ann {role} {tag}",
            role=UserRole(role),
            roles=roles if roles is not None else [],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, role)}"
        }


def _body(**overrides) -> dict:
    tag = uuid.uuid4().hex[:6]
    body = {
        "title": f"Ogłoszenie {tag}",
        "body": "Od poniedziałku nowa kolejność Daily.",
        "visible_until": (business_today() + timedelta(days=2)).isoformat(),
    }
    body.update(overrides)
    return body


async def _items(app_client: AsyncClient, headers: dict) -> dict[int, dict]:
    res = await app_client.get("/api/announcements", headers=headers)
    assert res.status_code == 200, res.text
    return {item["id"]: item for item in res.json()["items"]}


@_DB
@pytest.mark.asyncio
async def test_recruiter_and_delivery_lead_cannot_publish(app_client: AsyncClient):
    _, hor = await _user("head_of_recruitment")
    created = await app_client.post("/api/announcements", json=_body(), headers=hor)
    assert created.status_code == 201, created.text
    ann_id = created.json()["id"]
    for role in ("recruiter", "delivery_lead"):
        _, headers = await _user(role)
        denied = await app_client.post(
            "/api/announcements", json=_body(), headers=headers
        )
        assert denied.status_code == 403, denied.text
        edit = await app_client.patch(
            f"/api/announcements/{ann_id}", json=_body(), headers=headers
        )
        assert edit.status_code == 403, edit.text
        drop = await app_client.delete(f"/api/announcements/{ann_id}", headers=headers)
        assert drop.status_code == 403, drop.text
        listing = (await app_client.get("/api/announcements", headers=headers)).json()
        assert listing["can_publish"] is False


@_DB
@pytest.mark.asyncio
async def test_read_is_remembered_per_person_and_author_sees_count(
    app_client: AsyncClient,
):
    _, hor = await _user("head_of_recruitment")
    first_id, first = await _user("recruiter")
    _, second = await _user("recruiter")
    older = await app_client.post("/api/announcements", json=_body(), headers=hor)
    newer = await app_client.post("/api/announcements", json=_body(), headers=hor)
    older_id, newer_id = older.json()["id"], newer.json()["id"]

    mine = await _items(app_client, first)
    assert mine[older_id]["read"] is False and mine[older_id]["for_me"] is True
    assert mine[older_id]["read_count"] is None  # licznik tylko dla publikujących
    before = (await _items(app_client, hor))[older_id]

    read = await app_client.post(f"/api/announcements/{older_id}/read", headers=first)
    assert read.status_code == 204, read.text
    again = await app_client.post(f"/api/announcements/{older_id}/read", headers=first)
    assert again.status_code == 204

    res = await app_client.get("/api/announcements", headers=first)
    order = [item["id"] for item in res.json()["items"]]
    # Przeczytane nie znika, tylko schodzi pod nieprzeczytane.
    assert order.index(newer_id) < order.index(older_id)
    assert {item["id"]: item for item in res.json()["items"]}[older_id]["read"] is True
    assert (await _items(app_client, second))[older_id]["read"] is False

    after = (await _items(app_client, hor))[older_id]
    assert after["read_count"] == before["read_count"] + 1
    assert after["recipient_count"] >= 2


@_DB
@pytest.mark.asyncio
async def test_audience_by_role(app_client: AsyncClient):
    _, hor = await _user("head_of_recruitment")
    _, dl = await _user("delivery_lead")
    _, recruiter = await _user("recruiter")
    _, both = await _user("recruiter", roles=["recruiter", "delivery_lead"])
    created = await app_client.post(
        "/api/announcements",
        json=_body(audience_roles=["delivery_lead"]),
        headers=hor,
    )
    ann_id = created.json()["id"]
    assert ann_id in await _items(app_client, dl)
    assert ann_id in await _items(app_client, both)
    assert ann_id not in await _items(app_client, recruiter)
    hidden = await app_client.post(
        f"/api/announcements/{ann_id}/read", headers=recruiter
    )
    assert hidden.status_code == 404
    # Autor widzi także ogłoszenie nie do siebie (żeby je poprawić albo zdjąć).
    own = (await _items(app_client, hor))[ann_id]
    assert own["for_me"] is False and own["audience_roles"] == ["delivery_lead"]


@_DB
@pytest.mark.asyncio
async def test_expired_and_withdrawn_announcements_disappear(app_client: AsyncClient):
    from app.core.database import AsyncSessionLocal
    from app.models.announcement import Announcement

    hor_id, hor = await _user("head_of_recruitment")
    _, recruiter = await _user("recruiter")
    async with AsyncSessionLocal() as db:
        expired = Announcement(
            title="Wczorajsze",
            body="Już nieaktualne",
            visible_until=business_today() - timedelta(days=1),
            author_id=hor_id,
        )
        today = Announcement(
            title="Dzisiejsze",
            body="Do końca dnia",
            visible_until=business_today(),
            author_id=hor_id,
        )
        db.add_all([expired, today])
        await db.commit()
        expired_id, today_id = expired.id, today.id
    seen = await _items(app_client, recruiter)
    assert today_id in seen and expired_id not in seen
    late = await app_client.post(
        f"/api/announcements/{expired_id}/read", headers=recruiter
    )
    assert late.status_code == 404
    stale_edit = await app_client.patch(
        f"/api/announcements/{expired_id}", json=_body(), headers=hor
    )
    assert stale_edit.status_code == 409

    dropped = await app_client.delete(f"/api/announcements/{today_id}", headers=hor)
    assert dropped.status_code == 200, dropped.text
    assert today_id not in await _items(app_client, recruiter)
    assert today_id not in await _items(app_client, hor)
    twice = await app_client.delete(f"/api/announcements/{today_id}", headers=hor)
    assert twice.status_code == 409


@_DB
@pytest.mark.asyncio
async def test_important_rings_recipients_once_without_author(app_client: AsyncClient):
    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    hor_id, hor = await _user("head_of_recruitment")
    tcm_id, _ = await _user("talent_community_manager")
    recruiter_id, _ = await _user("recruiter")
    created = await app_client.post(
        "/api/announcements",
        json=_body(audience_roles=["talent_community_manager", "head_of_recruitment"]),
        headers=hor,
    )
    ann_id = created.json()["id"]
    assert created.json()["notified"] == 0  # bez „ważne” — bez dzwonka

    edited = await app_client.patch(
        f"/api/announcements/{ann_id}",
        json=_body(
            title="Ważne: nowy proces Cpro",
            important=True,
            audience_roles=["talent_community_manager", "head_of_recruitment"],
        ),
        headers=hor,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["notified"] >= 1
    again = await app_client.patch(
        f"/api/announcements/{ann_id}",
        json=_body(
            title="Ważne: nowy proces Cpro (poprawka)",
            important=True,
            audience_roles=["talent_community_manager", "head_of_recruitment"],
        ),
        headers=hor,
    )
    assert again.json()["notified"] == 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.announcement_important,
                    Notification.related_entity_id == ann_id,
                )
            )
        ).all()
    by_user = {row.user_id: row for row in rows}
    assert tcm_id in by_user
    assert hor_id not in by_user and recruiter_id not in by_user
    assert by_user[tcm_id].title == "Ważne: nowy proces Cpro"
    assert by_user[tcm_id].link == "/dashboard"
    assert re.search(r"widoczne do \d\d\.\d\d", by_user[tcm_id].message)
