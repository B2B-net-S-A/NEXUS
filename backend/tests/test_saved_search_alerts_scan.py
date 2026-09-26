"""Skaner alertów zapisanych wyszukiwań na prawdziwej bazie (runda 8 audytu).

* R8-N10-1 — jeden zapis, na którym odtworzenie pada, nie może zatrzymać
  przebiegu dla zapisów o wyższym id,
* R8-N10-3 — linia bazowa obejmuje CAŁY zbiór trafień, a przyrost, który nie
  obejrzał ogona, nie przesuwa znaku wodnego.

Każdy test zakłada własnych kandydatów (nonce) i własne zapisy, a skaner
woła zawężony do nich (``scan_once(search_ids=...)``) — baza jest wspólna.
Na końcu alert jest wyłączany, żeby zapis nie wisiał w przebiegach innych testów.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.notification import Notification, NotificationType
from app.models.saved_search import SavedSearch
from app.models.saved_search_alert_log import SavedSearchAlertLog
from app.tasks import saved_search_alerts as alerts


def _nonce() -> str:
    return "ssa" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])


async def _owner_id(client, headers) -> int:
    resp = await client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


async def _seed_candidates(nonce: str, n: int) -> list[int]:
    async with AsyncSessionLocal() as db:
        rows = [
            Candidate(
                name="Alert",
                lastname=f"Skan{nonce}",
                email=f"ssa-{uuid.uuid4().hex[:10]}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=nonce,
            )
            for _ in range(n)
        ]
        db.add_all(rows)
        await db.commit()
        return [r.id for r in rows]


async def _seed_search(owner_id: int, api: dict[str, Any]) -> int:
    async with AsyncSessionLocal() as db:
        ss = SavedSearch(
            user_id=owner_id,
            name=f"Skaner {uuid.uuid4().hex[:6]}",
            entity="candidates",
            filters={"version": 2, "qs": "", "api": api},
            notify_new_matches=True,
        )
        db.add(ss)
        await db.commit()
        return ss.id


async def _load(search_id: int) -> SavedSearch:
    async with AsyncSessionLocal() as db:
        return await db.get(SavedSearch, search_id)


async def _logged(search_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(SavedSearchAlertLog)
                .where(SavedSearchAlertLog.saved_search_id == search_id)
            )
        )


async def _match_notifications(search_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.notification_type
                    == NotificationType.saved_search_match,
                    Notification.related_entity_type == "saved_search",
                    Notification.related_entity_id == search_id,
                )
            )
        )


async def _disable(*search_ids: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SavedSearch)
            .where(SavedSearch.id.in_(search_ids))
            .values(notify_new_matches=False)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_zepsuty_zapis_nie_zatrzymuje_kolejnych(app_client, app_auth_headers):
    nonce = _nonce()
    await _seed_candidates(nonce, 2)
    owner = await _owner_id(app_client, app_auth_headers)
    # Niższe id: status spoza słownika → lista odpowiada 422 w każdym biegu.
    broken = await _seed_search(owner, {"q_all": [nonce], "status": ["zzz-nie-ma"]})
    healthy = await _seed_search(owner, {"q_all": [nonce]})
    try:
        await alerts.scan_once(search_ids=[broken, healthy])
        assert (await _load(broken)).last_scanned_at is None
        ok = await _load(healthy)
        assert ok.last_scanned_at is not None
        assert await _logged(healthy) == 2

        # Drugi przebieg: zapis po awarii dalej działa (przyrost, bez alertu).
        await alerts.scan_once(search_ids=[broken, healthy])
        assert (await _load(healthy)).last_scanned_at > ok.last_scanned_at
    finally:
        await _disable(broken, healthy)


@pytest.mark.asyncio
async def test_linia_bazowa_obejmuje_caly_zbior(
    app_client, app_auth_headers, monkeypatch
):
    nonce = _nonce()
    ids = await _seed_candidates(nonce, 5)
    owner = await _owner_id(app_client, app_auth_headers)
    search_id = await _seed_search(owner, {"q_all": [nonce]})
    monkeypatch.setattr(alerts, "_PAGE_SIZE", 2)
    try:
        # Sufit 2 stron = 4 z 5 trafień: linia bazowa niepełna → brak znaku
        # wodnego (następny przebieg dosieje resztę), zero alertów.
        monkeypatch.setattr(alerts, "_MAX_PAGES", 2)
        await alerts.scan_once(search_ids=[search_id])
        assert (await _load(search_id)).last_scanned_at is None

        monkeypatch.setattr(alerts, "_MAX_PAGES", 10)
        await alerts.scan_once(search_ids=[search_id])
        assert (await _load(search_id)).last_scanned_at is not None
        assert await _logged(search_id) == 5

        # Przebieg w tle dotyka NAJSTARSZEGO trafienia — pasowało od zawsze,
        # więc to nie jest „nowy kandydat”.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Candidate)
                .where(Candidate.id == min(ids))
                .values(updated_at=func.now())
            )
            await db.commit()
        assert await alerts.scan_once(search_ids=[search_id]) == 0
        assert await _match_notifications(search_id) == 0
    finally:
        await _disable(search_id)


@pytest.mark.asyncio
async def test_przyrost_bez_ogona_nie_przesuwa_znaku_wodnego(
    app_client, app_auth_headers, monkeypatch
):
    nonce = _nonce()
    await _seed_candidates(nonce, 1)
    owner = await _owner_id(app_client, app_auth_headers)
    search_id = await _seed_search(owner, {"q_all": [nonce]})
    monkeypatch.setattr(alerts, "_PAGE_SIZE", 2)
    try:
        await alerts.scan_once(search_ids=[search_id])
        watermark = (await _load(search_id)).last_scanned_at
        assert watermark is not None

        await _seed_candidates(nonce, 5)  # 5 nowych trafień, sufit 2 strony × 2
        monkeypatch.setattr(alerts, "_MAX_PAGES", 2)
        assert await alerts.scan_once(search_ids=[search_id]) == 1
        assert (await _load(search_id)).last_scanned_at == watermark

        # Pełny przyrost obejmuje ogon (piąta osoba) i dopiero wtedy idzie dalej.
        monkeypatch.setattr(alerts, "_MAX_PAGES", 10)
        await alerts.scan_once(search_ids=[search_id])
        assert (await _load(search_id)).last_scanned_at > watermark
        assert await _logged(search_id) == 6
    finally:
        await _disable(search_id)
