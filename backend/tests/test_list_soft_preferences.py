"""Lista kandydatów: „Mile widziane” poza umiejętnościami tylko szereguje.

Audyt 26.09.2026 (``docs/audits/2026-09-26/wyszukiwanie-reczne.md``):
„Szukaj ręcznie” wstawiało miasto i kategorię rekrutacji jako FILTRY i wycinało
55,6% osób, które zespół potem zweryfikował albo wysłał klientowi, a wiersze
wymagań nietechnicznych łączone przez I znajdowały 39%. Nowe parametry
``location_preferred``, ``competence_category_preferred`` i
``q_preferred_group`` nie zmieniają ZBIORU wyników — przesuwają pasujących na
początek (+1 za każdy spełniony sygnał, obok ``skills_preferred``).

Baza testowa jest współdzielona i nie jest czyszczona, więc każde żądanie jest
zawężone do własnych wierszy frazą ``NONCE`` w ``linkedin_current_company``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

NONCE = "zp" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}
_CC: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.competence_category import (
        CandidateCompetenceCategory,
        CompetenceCategory,
    )

    def person(key: str, **kw: Any) -> Candidate:
        return Candidate(
            name=key.capitalize(),
            lastname=f"Miekki{key}",
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            **kw,
        )

    async with AsyncSessionLocal() as db:
        cat = CompetenceCategory(
            slug=f"sp-{NONCE[:20]}",
            name_pl="Miękka",
            name_en="Soft",
            description="test",
            keywords=[],
        )
        db.add(cat)
        await db.flush()
        _CC["cat"] = cat.id
        rows = {
            "warsaw": person("warsaw", city="Warszawa", raw_cv_text="Tester."),
            "gdansk": person("gdansk", city="Gdańsk", raw_cv_text="Tester."),
            "nocity": person("nocity", raw_cv_text="Tester."),
            "bank": person("bank", city="Łódź", raw_cv_text="Tester w bankowości."),
            "primary": person(
                "primary",
                city="Łódź",
                raw_cv_text="Tester.",
                competence_category_id=cat.id,
            ),
            "secondary": person("secondary", city="Łódź", raw_cv_text="Tester."),
        }
        db.add_all(rows.values())
        await db.flush()
        db.add(
            CandidateCompetenceCategory(
                candidate_id=rows["secondary"].id,
                competence_category_id=cat.id,
                is_primary=False,
            )
        )
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


async def _order(client, headers, **params: Any) -> list[str]:
    ids = await _seed()
    query: list[tuple[str, Any]] = [
        ("q_all", NONCE),
        ("page_size", 100),
        ("semantics_version", 2),
        ("sort", "name"),
    ]
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    by_id = {v: k for k, v in ids.items()}
    return [by_id[i["id"]] for i in resp.json()["items"] if i["id"] in by_id]


ALL = {"warsaw", "gdansk", "nocity", "bank", "primary", "secondary"}


@pytest.mark.asyncio
async def test_preferred_city_ranks_but_never_filters(app_client, app_auth_headers):
    order = await _order(
        app_client, app_auth_headers, location_preferred=["Warszawa", "Gdansk"]
    )
    assert set(order) == ALL, "miasto „Mile widziane” nie może nikogo wyciąć"
    assert set(order[:2]) == {"warsaw", "gdansk"}, order


@pytest.mark.asyncio
async def test_preferred_category_counts_primary_and_secondary(
    app_client, app_auth_headers
):
    ids = await _seed()
    order = await _order(
        app_client, app_auth_headers, competence_category_preferred=[_CC["cat"]]
    )
    assert set(order) == ALL
    assert set(order[:2]) == {"primary", "secondary"}, (order, ids)


@pytest.mark.asyncio
async def test_preferred_keyword_row_ranks_but_never_filters(
    app_client, app_auth_headers
):
    order = await _order(
        app_client, app_auth_headers, q_preferred_group="bankow*|banking"
    )
    assert set(order) == ALL
    assert order[0] == "bank", order


@pytest.mark.asyncio
async def test_signals_add_up(app_client, app_auth_headers):
    order = await _order(
        app_client,
        app_auth_headers,
        location_preferred=["Łódź"],
        q_preferred_group="bankow*",
        competence_category_preferred=[_CC["cat"]],
    )
    assert set(order) == ALL
    # bank: miasto + wiersz = 2; primary/secondary: miasto + kategoria = 2;
    # warsaw/gdansk/nocity: 0 — na końcu.
    assert set(order[:3]) == {"bank", "primary", "secondary"}, order
    assert set(order[3:]) == {"warsaw", "gdansk", "nocity"}, order


@pytest.mark.asyncio
async def test_without_signals_order_is_unchanged(app_client, app_auth_headers):
    plain = await _order(app_client, app_auth_headers)
    again = await _order(app_client, app_auth_headers, location_preferred=[])
    assert plain == again
