"""Sortowanie „Nazwisko (A-Z)" musi rozumieć polskie znaki — i nazwisko.

Dwie ciche awarie, obie na największej powierzchni produktu (lista ~49 tys.
kandydatów, cięta OFFSET/LIMIT po stronie serwera):

1. Kolacja bazy to `en_US.utf8` na musl (`postgres:16-alpine`), gdzie
   `'Łukasz' < 'Zbigniew'` jest FAŁSZEM. Kandydat na Ł/Ś/Ż/Ć/Ó/Ą/Ę/Ń nie
   wypadał „nisko" — był NIEOBECNY na każdej stronie poza kilkoma ostatnimi.
   Rekruter widzi brak, a brak wygląda jak „nie ma takiej osoby w bazie".
2. Sortowaliśmy po IMIENIU, choć etykieta w UI brzmi „Nazwisko (A-Z)".

Filtrem zakresu jest `location` (`ILIKE %scope%`, dokładna semantyka), a nie
`q` — tamten idzie przez trigramy i przy losowym tokenie bywa niedeterministyczny.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed(*, name: str, lastname: str, scope: str) -> int:
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=name,
            lastname=lastname,
            email=f"plsort-{uuid.uuid4().hex[:10]}@example.com",
            location=scope,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _cleanup(ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


async def _sorted_ids(
    app_client: AsyncClient, headers: dict, scope: str
) -> list[int]:
    resp = await app_client.get(
        "/api/candidates",
        params={"location": scope, "sort": "name", "page": 1, "page_size": 50},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()["items"]]


@pytest.mark.asyncio
async def test_polish_diacritics_sort_between_their_ascii_neighbours(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scope = uuid.uuid4().hex[:12]
    luczak = await _seed(name="Adam", lastname=f"Łuczak-{scope}", scope=scope)
    nowak = await _seed(name="Beata", lastname=f"Nowak-{scope}", scope=scope)
    swider = await _seed(name="Cezary", lastname=f"Świder-{scope}", scope=scope)
    zielinski = await _seed(name="Dorota", lastname=f"Zielinski-{scope}", scope=scope)
    try:
        ids = await _sorted_ids(app_client, app_auth_headers, scope)
        assert ids == [luczak, nowak, swider, zielinski], (
            "Ł/Ś sortują się pod kolacją bajtową — czyli za literą Z; "
            f"got={ids} expected=[Łuczak, Nowak, Świder, Zielinski]"
        )
    finally:
        await _cleanup([luczak, nowak, swider, zielinski])


@pytest.mark.asyncio
async def test_sort_name_orders_by_lastname_not_first_name(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scope = uuid.uuid4().hex[:12]
    # Imiona w kolejności ODWROTNEJ do nazwisk — jeśli sortowanie idzie po
    # imieniu, wynik wyjdzie odwrotny.
    zeta_abramczyk = await _seed(name="Zenon", lastname=f"Abramczyk-{scope}", scope=scope)
    adam_borowski = await _seed(name="Adam", lastname=f"Borowski-{scope}", scope=scope)
    try:
        ids = await _sorted_ids(app_client, app_auth_headers, scope)
        assert ids == [zeta_abramczyk, adam_borowski], (
            f'sortowanie „Nazwisko (A-Z)" idzie po imieniu; got={ids}'
        )
    finally:
        await _cleanup([zeta_abramczyk, adam_borowski])


@pytest.mark.asyncio
async def test_placeholder_lastnames_sort_last(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """„?" sortuje się przed literami, więc rekordy bez nazwiska (import
    Traffita) okupowały stronę 1 listy alfabetycznej."""
    scope = uuid.uuid4().hex[:12]
    unknown = await _seed(name="Nieznany", lastname="?", scope=scope)
    real = await _seed(name="Anna", lastname=f"Adamska-{scope}", scope=scope)
    try:
        ids = await _sorted_ids(app_client, app_auth_headers, scope)
        assert ids == [real, unknown], f"placeholder przed prawdziwym nazwiskiem: {ids}"
    finally:
        await _cleanup([unknown, real])
