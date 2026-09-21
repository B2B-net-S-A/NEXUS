"""Migracja zapisanych wyszukiwań na wspólną semantykę filtrów (P3).

Każdy test zakłada WŁASNE wiersze (kandydaci z nonce, własne zapisy) i woła
``migrate_one`` na swoim zapisie — baza testowa jest wspólna, więc globalnego
przebiegu używamy tylko w trybie ``dry_run``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.notification import Notification, NotificationType
from app.models.saved_search import SavedSearch
from app.models.user import User
from app.services import saved_search_migration as migration
from app.tasks import saved_search_alerts as alerts


def _nonce() -> str:
    return "zm" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])


async def _owner_id(client, headers) -> int:
    resp = await client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


async def _seed_candidates(nonce: str) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        rows = {
            "rate": Candidate(
                name="Rata",
                lastname=f"Mig{nonce}",
                email=f"mig-r-{uuid.uuid4().hex[:8]}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=nonce,
                skills=["Python"],
                tags=["javascript"],
                expected_rate_hourly=Decimal("150"),
            ),
            "norate": Candidate(
                name="Bezstawki",
                lastname=f"Mig{nonce}",
                email=f"mig-n-{uuid.uuid4().hex[:8]}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=nonce,
                skills=["Python"],
            ),
        }
        db.add_all(rows.values())
        await db.commit()
        return {k: v.id for k, v in rows.items()}


async def _seed_search(owner_id: int, filters: dict[str, Any], *, alert: bool) -> int:
    async with AsyncSessionLocal() as db:
        ss = SavedSearch(
            user_id=owner_id,
            name=f"Migracja {uuid.uuid4().hex[:6]}",
            entity="candidates",
            filters=filters,
            notify_new_matches=alert,
        )
        db.add(ss)
        await db.commit()
        return ss.id


async def _migrate(search_id: int) -> str:
    from app.main import app

    async with AsyncSessionLocal() as db:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://migration-test"
        ) as client:
            ss = await db.get(SavedSearch, search_id)
            owner = await db.get(User, ss.user_id)
            outcome = await migration.migrate_one(client, db, ss, owner)
            await db.commit()
            return outcome


async def _load(search_id: int) -> SavedSearch:
    async with AsyncSessionLocal() as db:
        return await db.get(SavedSearch, search_id)


async def _reapproval_notifications(search_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(Notification).where(
                        Notification.notification_type
                        == NotificationType.saved_search_reapproval,
                        Notification.related_entity_type == "saved_search",
                        Notification.related_entity_id == search_id,
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_identyczny_wynik_migruje_po_cichu(app_client, app_auth_headers):
    nonce = _nonce()
    await _seed_candidates(nonce)
    owner = await _owner_id(app_client, app_auth_headers)
    search_id = await _seed_search(
        owner,
        {
            "version": 2,
            "qs": "skills_q=Python",
            "api": {"q_all": [nonce], "skills": ["Python"]},
        },
        alert=True,
    )
    assert await _migrate(search_id) == "identical"
    ss = await _load(search_id)
    assert ss.filters["version"] == 3 and ss.filters["semantics_version"] == 2
    assert ss.filters["qs"].endswith("sv=2")
    assert ss.filters["legacy"]["api"]["skills"] == ["Python"]
    assert ss.requires_reapproval is False and ss.notify_new_matches is True
    assert await _reapproval_notifications(search_id) == []


@pytest.mark.asyncio
async def test_inny_wynik_wstrzymuje_alert_i_powiadamia_raz(
    app_client, app_auth_headers
):
    nonce = _nonce()
    ids = await _seed_candidates(nonce)
    owner = await _owner_id(app_client, app_auth_headers)
    # Lista v1 wycina osobę bez stawki; wspólna semantyka ją zostawia.
    search_id = await _seed_search(
        owner,
        {
            "version": 2,
            "qs": "rate_min=100",
            "api": {"q_all": [nonce], "min_rate": 100},
        },
        alert=True,
    )
    assert await _migrate(search_id) == "different"
    ss = await _load(search_id)
    assert ss.requires_reapproval is True and ss.notify_new_matches is False
    diff = ss.filters["migration"]["diff"]
    assert (diff["legacy_total"], diff["unified_total"]) == (1, 2)
    assert (diff["only_legacy"], diff["only_unified"]) == (0, 1)
    assert ss.filters["migration"]["alert_was_on"] is True
    # tylko liczby — żadnych id ani nazwisk
    assert all(isinstance(v, int) for v in diff.values())
    notes = await _reapproval_notifications(search_id)
    assert len(notes) == 1
    assert (
        f"Mig{nonce}" not in notes[0].message
        and str(ids["norate"]) not in notes[0].message
    )
    assert notes[0].link and f"ss={search_id}" in notes[0].link

    # ponowny przebieg: nic nie robi, nie powiadamia drugi raz
    assert await _migrate(search_id) == "already"
    assert len(await _reapproval_notifications(search_id)) == 1

    # wstrzymany zapis nie jest skanowany
    async with AsyncSessionLocal() as db:
        scanned = await db.scalar(
            select(func.count(SavedSearch.id)).where(
                SavedSearch.id == search_id,
                SavedSearch.notify_new_matches.is_(True),
                SavedSearch.requires_reapproval.is_(False),
            )
        )
    assert scanned == 0


@pytest.mark.asyncio
async def test_akceptacja_wznawia_alert_z_nowa_linia_bazowa(
    app_client, app_auth_headers
):
    from app.main import app

    nonce = _nonce()
    await _seed_candidates(nonce)
    owner_id = await _owner_id(app_client, app_auth_headers)
    search_id = await _seed_search(
        owner_id,
        {
            "version": 2,
            "qs": "rate_min=100",
            "api": {"q_all": [nonce], "min_rate": 100},
        },
        alert=True,
    )
    assert await _migrate(search_id) == "different"

    resp = await app_client.patch(
        f"/api/saved-searches/{search_id}",
        json={"confirm_reapproval": True},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requires_reapproval"] is False and body["notify_new_matches"] is True
    ss = await _load(search_id)
    assert ss.last_scanned_at is None  # linia bazowa do ponownego zasiania
    assert ss.filters["migration"]["alert_was_on"] is False
    assert ss.filters["migration"]["reapproved_at"]

    async with AsyncSessionLocal() as db:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://scanner-test"
        ) as client:
            ss = await db.get(SavedSearch, search_id)
            owner = await db.get(User, owner_id)
            # 1. przebieg: zasiewa OBIE osoby (także tę bez stawki) — bez alertu
            await alerts._baseline_one(client, db, ss, owner)
            await db.commit()
            # 2. przebieg: nic nowego → zero powiadomień (brak burzy)
            assert await alerts._incremental_one(client, db, ss, owner) is False
            await db.commit()

            # nowa osoba pasująca do zapisu → alert działa dalej
            db.add(
                Candidate(
                    name="Nowa",
                    lastname=f"Mig{nonce}",
                    email=f"mig-new-{uuid.uuid4().hex[:8]}@example.com",
                    status=CandidateStatus.active,
                    linkedin_current_company=nonce,
                )
            )
            await db.commit()
            assert await alerts._incremental_one(client, db, ss, owner) is True
            await db.commit()
    ss = await _load(search_id)
    assert ss.unseen_count == 1


@pytest.mark.asyncio
async def test_oba_formaty_legacy_sa_czytane(app_client, app_auth_headers):
    nonce = _nonce()
    await _seed_candidates(nonce)
    owner = await _owner_id(app_client, app_auth_headers)
    # wyszukiwarka: chipy miękkie → ten sam zbiór
    same = await _seed_search(
        owner,
        {"q_all": [nonce], "skills_must": ["Python"], "search_mode": "boolean"},
        alert=False,
    )
    # wyszukiwarka: tag podłańcuchem („java" ⊂ „javascript") → inny zbiór
    other = await _seed_search(owner, {"q_all": [nonce], "tags": ["java"]}, alert=False)
    assert await _migrate(same) == "identical"
    assert await _migrate(other) == "different"
    migrated = await _load(other)
    assert migrated.filters["origin"] == "search_request"
    assert migrated.filters["request"]["tags"] == ["java"]
    assert migrated.filters["migration"]["alert_was_on"] is False
    assert migrated.requires_reapproval is True
    assert len(await _reapproval_notifications(other)) == 1


@pytest.mark.asyncio
async def test_najstarszy_format_bez_api_zostaje_nietkniety(
    app_client, app_auth_headers
):
    owner = await _owner_id(app_client, app_auth_headers)
    search_id = await _seed_search(owner, {"qs": "q=python"}, alert=False)
    assert await _migrate(search_id) == "unreadable"
    assert (await _load(search_id)).filters == {"qs": "q=python"}


@pytest.mark.asyncio
async def test_endpoint_admina_dry_run_niczego_nie_zapisuje(
    app_client, app_auth_headers
):
    nonce = _nonce()
    await _seed_candidates(nonce)
    owner = await _owner_id(app_client, app_auth_headers)
    search_id = await _seed_search(
        owner,
        {
            "version": 2,
            "qs": "rate_min=100",
            "api": {"q_all": [nonce], "min_rate": 100},
        },
        alert=True,
    )
    resp = await app_client.post(
        "/api/saved-searches/migrate-semantics",
        params={"dry_run": "true"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["dry_run"] is True
    assert search_id in summary["needs_reapproval_ids"]
    ss = await _load(search_id)
    assert ss.filters.get("version") == 2 and ss.notify_new_matches is True
    assert await _reapproval_notifications(search_id) == []
