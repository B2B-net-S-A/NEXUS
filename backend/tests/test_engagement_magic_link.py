"""Tests for engagement-declaration magic-link flow (Faza 2.6)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="MagicLink",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"ml-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _cleanup_candidate(cid: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.engagement_token import EngagementDeclarationToken
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(EngagementDeclarationToken).where(
                EngagementDeclarationToken.candidate_id == cid
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


async def _expire_token(token_str: str) -> None:
    """Przestaw ``expires_at`` w przeszłość dla wiersza kryjącego się za sekretem.

    Od hash-at-rest v2 (migracja 0182) kolumna ``token`` NIE trzyma sekretu —
    leży w niej nie-sekretny revoke-key ``v2$<hex>``, a sekret istnieje wyłącznie
    jako SHA-256 w ``token_sha256``. Dopasowanie ``token == token_str`` (jak
    robił ten helper przed poprawką) aktualizowało zero wierszy, więc setup po
    cichu stawał się no-opem: token nigdy nie wygasał, a 200 z endpointu było
    POPRAWNĄ odpowiedzią dla wciąż ważnego linku. Poniższy WHERE odwzorowuje
    dual-read z ``_resolve_token``, a assert na ``rowcount`` sprawia, że przy
    kolejnej zmianie schematu test padnie głośno na setupie zamiast udawać
    regresję w API.
    """
    import hashlib

    from app.core.database import AsyncSessionLocal
    from app.models.engagement_token import EngagementDeclarationToken
    from sqlalchemy import update

    digest = hashlib.sha256(token_str.encode()).hexdigest()
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(EngagementDeclarationToken)
            .where(
                (EngagementDeclarationToken.token_sha256 == digest)
                | (
                    (EngagementDeclarationToken.token == token_str)
                    & (EngagementDeclarationToken.token_sha256.is_(None))
                )
            )
            .values(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        )
        await db.commit()
    assert res.rowcount == 1, (
        "setup nie trafił w żaden wiersz engagement_declaration_tokens — token "
        "NIE został wygaszony, więc test nie sprawdziłby niczego"
    )


@pytest.mark.asyncio
async def test_magic_link_full_happy_flow(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate()
    try:
        # 1. Generate token (auth)
        gen = await app_client.post(
            f"/api/candidates/{cid}/engagement-declaration-link",
            headers=app_auth_headers,
        )
        assert gen.status_code == 201, gen.text
        body = gen.json()
        assert body["token"]
        assert "/engagement/" in body["url"]
        token = body["token"]

        # 2. Public GET (no auth) — return current flags + first name only
        view = await app_client.get(f"/api/public/engagement-declaration/{token}")
        assert view.status_code == 200
        v = view.json()
        assert v["candidate_first_name"] == "MagicLink"
        assert v["open_to_side_projects"] is False
        assert "email" not in v  # PII not leaked

        # 3. Public POST — set flags + notes
        sub = await app_client.post(
            f"/api/public/engagement-declaration/{token}",
            json={
                "open_to_side_projects": True,
                "open_to_sales_support": False,
                "open_to_expert_consult": True,
                "notes": "Tylko Python projekty.",
            },
        )
        assert sub.status_code == 200, sub.text
        s = sub.json()
        assert s["success"] is True
        assert s["candidate_first_name"] == "MagicLink"

        # 4. Verify candidate updated server-side
        full = await app_client.get(
            f"/api/candidates/{cid}", headers=app_auth_headers
        )
        c = full.json()
        assert c["open_to_side_projects"] is True
        assert c["open_to_expert_consult"] is True
        assert c["open_to_side_projects_updated_at"]
        assert "Tylko Python projekty" in (c.get("engagement_notes") or "")

        # 5. Reuse same token → 410
        reuse = await app_client.post(
            f"/api/public/engagement-declaration/{token}",
            json={
                "open_to_side_projects": False,
                "open_to_sales_support": False,
                "open_to_expert_consult": False,
            },
        )
        assert reuse.status_code == 410
    finally:
        await _cleanup_candidate(cid)


@pytest.mark.asyncio
async def test_magic_link_unknown_token_returns_404(
    app_client: AsyncClient,
):
    res = await app_client.get(
        "/api/public/engagement-declaration/totally-bogus-token"
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_magic_link_expired_token_returns_410(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate()
    try:
        gen = await app_client.post(
            f"/api/candidates/{cid}/engagement-declaration-link",
            headers=app_auth_headers,
        )
        token = gen.json()["token"]
        await _expire_token(token)

        res = await app_client.get(f"/api/public/engagement-declaration/{token}")
        assert res.status_code == 410
    finally:
        await _cleanup_candidate(cid)
