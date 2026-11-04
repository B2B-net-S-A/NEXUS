"""Lista ``GET /api/candidates`` — D5 i D6 (19.10.2026) na prawdziwej bazie.

* ``location_places`` (kilka miast, każde z promieniem) = SUMA z województwami;
  dotychczasowe ``location`` + ``voivodeship`` łączą się dalej koniunkcją;
* ``hide_unknown_rate`` / ``hide_unknown_location`` ukrywają braki tylko
  swojego filtru, globalne ``hide_unknown`` działa jak dotąd;
* ``known_match_count`` — ile z ``total`` spełnia filtr z danymi;
* ``location_distance`` — „Pruszków · 16 km od Warszawy”.

Baza testowa jest wspólna — każde żądanie zawęża się własną frazą ``NONCE``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

NONCE = "zl" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    def person(key: str, rate: int | None = None, **kw: Any) -> Candidate:
        return Candidate(
            name=key.capitalize(),
            lastname=f"Lokalizacyjny{key}",
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            expected_rate_hourly=Decimal(rate) if rate is not None else None,
            expected_rate_currency="PLN" if rate is not None else None,
            **kw,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            "warszawa": person("warszawa", 50, city="Warszawa", country="PL"),
            "pruszkow": person("pruszkow", city="Pruszków", country="PL"),
            "lodz": person("lodz", 120, city="Łódź", country="PL"),
            "krakow": person("krakow", 40, city="Kraków", country="PL"),
            "gdynia": person("gdynia", 45, city="Gdynia", country="PL"),
            "nowhere": person("nowhere", 45),
        }
        db.add_all(rows.values())
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


async def _list_raw(client, headers, **params: Any) -> tuple[int, dict]:
    await _seed()
    query: list[tuple[str, Any]] = [
        ("q", NONCE),
        ("text_mode", "literal"),
        ("page_size", 100),
        ("semantics_version", 2),
    ]
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    return resp.status_code, resp.json()


async def _list(client, headers, **params: Any) -> dict:
    status, body = await _list_raw(client, headers, **params)
    assert status == 200, body
    return body


def _keys(body: dict) -> set[str]:
    by_id = {v: k for k, v in _IDS.items()}
    return {by_id[item["id"]] for item in body["items"] if item["id"] in by_id}


def _ordered_keys(body: dict) -> list[str]:
    by_id = {v: k for k, v in _IDS.items()}
    return [by_id[item["id"]] for item in body["items"] if item["id"] in by_id]


# ── D6: kilka miast z promieniami = suma ───────────────────────────────────


@pytest.mark.asyncio
async def test_places_are_a_union_of_cities_radii_and_voivodeships(
    app_client, app_auth_headers
):
    body = await _list(
        app_client,
        app_auth_headers,
        location_places=["Warszawa:30", "Łódź"],
        voivodeship="pomorskie",
        hide_unknown_location="true",
    )
    assert _keys(body) == {"warszawa", "pruszkow", "lodz", "gdynia"}


@pytest.mark.asyncio
async def test_two_radii_each_from_its_own_center(app_client, app_auth_headers):
    body = await _list(
        app_client,
        app_auth_headers,
        location_places=["Warszawa:30", "Kraków:20"],
        hide_unknown_location="true",
    )
    assert _keys(body) == {"warszawa", "pruszkow", "krakow"}


@pytest.mark.asyncio
async def test_old_single_city_and_voivodeship_still_combine_with_and(
    app_client, app_auth_headers
):
    body = await _list(
        app_client,
        app_auth_headers,
        location="Warszawa",
        voivodeship="pomorskie",
        hide_unknown="true",
    )
    assert _keys(body) == set()
    same_city = await _list(
        app_client,
        app_auth_headers,
        location="Warszawa",
        location_radius_km=30,
        hide_unknown="true",
    )
    assert _keys(same_city) == {"warszawa", "pruszkow"}


@pytest.mark.asyncio
async def test_row_says_how_far_from_the_center(app_client, app_auth_headers):
    body = await _list(
        app_client,
        app_auth_headers,
        location_places=["Warszawa:30"],
        hide_unknown_location="true",
    )
    by_id = {item["id"]: item for item in body["items"]}
    distance = by_id[_IDS["pruszkow"]]["location_distance"]
    assert distance["center"] == "Warszawa" and distance["place"] == "Pruszków"
    assert 10 <= distance["km"] <= 25
    # W samym środku — bez dopisku.
    assert by_id[_IDS["warszawa"]]["location_distance"] is None


@pytest.mark.asyncio
async def test_bad_places_are_422(app_client, app_auth_headers):
    status, body = await _list_raw(
        app_client, app_auth_headers, location_places=["Atlantyda:10"]
    )
    assert status == 422 and "Atlantyda" in body["detail"]
    status, body = await _list_raw(
        app_client, app_auth_headers, location_places=[f"M{i}" for i in range(11)]
    )
    assert status == 422 and "10" in body["detail"]
    status, body = await _list_raw(
        app_client, app_auth_headers, location_places=["Warszawa:500"]
    )
    assert status == 422


# ── D5: braki danych osobno dla stawki i miasta + licznik ───────────────────


@pytest.mark.asyncio
async def test_rate_unknown_shown_last_and_counted(app_client, app_auth_headers):
    body = await _list(app_client, app_auth_headers, max_rate=55)
    keys = _keys(body)
    assert keys == {"warszawa", "krakow", "gdynia", "nowhere", "pruszkow"}
    # Osoba bez stawki na końcu, z plakietką.
    assert _ordered_keys(body)[-1] == "pruszkow"
    row = next(i for i in body["items"] if i["id"] == _IDS["pruszkow"])
    assert row["unknown_fields"] == ["rate"]
    # Licznik: tylko nasze osoby się liczą w różnicy (baza jest wspólna, ale
    # `q` zawęża zbiór do NONCE).
    assert body["total"] == 5
    assert body["known_match_count"] == 4


@pytest.mark.asyncio
async def test_hide_unknown_rate_hides_only_missing_rate(app_client, app_auth_headers):
    body = await _list(
        app_client,
        app_auth_headers,
        max_rate=55,
        location_places=["Warszawa:30"],
        hide_unknown_rate="true",
    )
    # „nowhere” (bez miasta) zostaje — ukryte są tylko braki stawki.
    assert _keys(body) == {"warszawa", "nowhere"}
    assert body["known_match_count"] == 1


@pytest.mark.asyncio
async def test_hide_unknown_location_hides_only_missing_city(
    app_client, app_auth_headers
):
    body = await _list(
        app_client,
        app_auth_headers,
        max_rate=55,
        location_places=["Warszawa:30"],
        hide_unknown_location="true",
    )
    assert _keys(body) == {"warszawa", "pruszkow"}
    assert body["known_match_count"] == 1


@pytest.mark.asyncio
async def test_global_hide_unknown_unchanged_and_no_count(app_client, app_auth_headers):
    body = await _list(app_client, app_auth_headers, max_rate=55, hide_unknown="true")
    assert _keys(body) == {"warszawa", "krakow", "gdynia", "nowhere"}
    assert body["known_match_count"] is None


@pytest.mark.asyncio
async def test_no_data_filter_no_count(app_client, app_auth_headers):
    body = await _list(app_client, app_auth_headers)
    assert body["known_match_count"] is None
    assert len(_keys(body)) == 6


@pytest.mark.asyncio
async def test_v1_ignores_count_and_still_drops_missing(app_client, app_auth_headers):
    await _seed()
    resp = await app_client.get(
        "/api/candidates",
        params=[
            ("q", NONCE),
            ("text_mode", "literal"),
            ("page_size", 100),
            ("max_rate", 55),
        ],
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert _keys(body) == {"warszawa", "krakow", "gdynia", "nowhere"}
    assert body["known_match_count"] is None
