"""Zbiorcze dodawanie tagów = te same reguły co pojedynczy tag (runda 9, R9-N8-10).

Do rundy 9 ``add_tags`` doklejało listę ze stanu wczytanego bez blokady wiersza,
porównywało wielkość liter (``Java`` obok ``java``), nie znało limitu tagów
i nie zostawiało śladu w dzienniku ani intencji przeliczenia wektora.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate


async def _candidate(tags: list) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Tagi", lastname=f"Zbiorcze{uuid.uuid4().hex[:6]}", tags=tags
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def test_bulk_add_tags_is_case_insensitive_and_audited(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    source = {"type": "traffit_source", "name": "LinkedIn"}
    cand_id = await _candidate(["Java", source])

    resp = await app_client.post(
        "/api/candidates/bulk",
        json={
            "action": "add_tags",
            "candidate_ids": [cand_id],
            "params": {"tags": ["java", "  Kotlin  ", "kotlin"]},
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["succeeded"] == 1

    async with AsyncSessionLocal() as db:
        kept = await db.get(Candidate, cand_id)
        assert kept.tags == ["Java", source, "Kotlin"]
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == cand_id,
                Activity.action == "tags_changed",
            )
        )
        assert audit is not None and audit.details["added"] == ["Kotlin"]


async def test_bulk_add_tags_rejects_what_single_tag_rejects(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    cand_id = await _candidate([])
    resp = await app_client.post(
        "/api/candidates/bulk",
        json={
            "action": "add_tags",
            "candidate_ids": [cand_id],
            "params": {"tags": ["java, kotlin"]},
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_bulk_add_tags_respects_tag_limit(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.api.candidate_tags import MAX_STRING_TAGS

    full = [f"tag{i}" for i in range(MAX_STRING_TAGS)]
    cand_id = await _candidate(full)
    resp = await app_client.post(
        "/api/candidates/bulk",
        json={
            "action": "add_tags",
            "candidate_ids": [cand_id],
            "params": {"tags": ["nowy"]},
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item == {"candidate_id": cand_id, "ok": False, "reason": "tag_limit"}
    async with AsyncSessionLocal() as db:
        assert (await db.get(Candidate, cand_id)).tags == full
