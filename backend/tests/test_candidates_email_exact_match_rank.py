"""UAT B35: dokładny e-mail jest pierwszy w sortowaniu „relevance".

`GET /api/candidates?q=<pełny adres>&sort=relevance` liczy podobieństwo
trigramowe do „imię nazwisko e-mail". Osoba o PODOBNYM adresie i krótszym
nazwisku wygrywała z właścicielem adresu (krótszy stóg = wyższe similarity),
a paleta ⌘K otwierała ją Enterem. Właściciel dokładnego adresu ma być
pierwszy niezależnie od reszty stogu i daty utworzenia.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration]


async def _seed(name: str, lastname: str, email: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(name=name, lastname=lastname, email=email)
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _cleanup(ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_exact_email_ranks_first_under_relevance_sort(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = uuid.uuid4().hex[:10]
    email = f"osoba.{tag}@example.com"
    # Właściciel adresu ma długie imię i nazwisko — dużo trigramów spoza
    # zapytania, więc jego similarity jest NIŻSZE niż u wabika.
    owner = await _seed("Zdzisława-Bronisława", f"Placeholder-{tag}", email)
    # Wabik: adres zawiera szukany (substring → trafia w filtr), prawie puste
    # nazwisko i NOWSZY created_at — na starym sortowaniu wygrywał podwójnie.
    decoy = await _seed("A", "B", f"z{email}")
    try:
        resp = await app_client.get(
            "/api/candidates",
            params={"q": email, "sort": "relevance", "page_size": 20},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        ids = [item["id"] for item in resp.json()["items"]]
        assert owner in ids and decoy in ids, ids
        assert ids.index(owner) < ids.index(decoy), ids
        assert ids[0] == owner, ids
    finally:
        await _cleanup([owner, decoy])
