"""Regresja: ranking admina pokazuje nazwę prezentowaną i tylko realnych klientów.

Incydent (prod, 2026-08-12): `GET /api/admin/clients-overview` czytał surowe
``Client.name`` i nie filtrował kanoniczności, więc:

* **24 z 160** klientów wyświetlało się tam pod inną nazwą niż w całej reszcie
  aplikacji — np. „Nordea" (280 konsultantów) zamiast „Nordea Bank Abp",
  „ALIOR BANK" zamiast „Alior Bank S.A.". Kolumna ``name`` jest własnością
  Traffita (sync robi ``ON CONFLICT ... SET name=EXCLUDED.name``), a ręczna
  poprawka nazwy z UI pisze WYŁĄCZNIE do ``display_name`` — ten widok był
  jedynym, który pokazywał nazwę sprzed poprawki.
* **12** rekordów scalonych/ukrytych figurowało jako osobne wiersze z zerami we
  wszystkich kolumnach, czyli dla jednego realnego klienta były dwa wiersze.

Dlatego testy seedują dokładnie te dwa kształty danych, a nie „jakiegoś"
klienta. Reguły mają jedną definicję w ``app/services/client_identity.py`` —
ostatni test pilnuje, żeby aliasy w ``api/clients.py`` i
``api/client_directory.py`` nie odkleiły się od niej z powrotem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient

OVERVIEW = "/api/admin/clients-overview"


async def _fetch_overview(
    app_client: AsyncClient, headers: dict[str, str]
) -> list[dict]:
    resp = await app_client.get(OVERVIEW, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def seeded_clients() -> AsyncIterator[dict[str, object]]:
    """Klient z ręcznie poprawioną nazwą + trzy rekordy niekanoniczne.

    Sprząta po sobie w odwrotnej kolejności: ``merged_into_client_id`` ma
    ``ondelete=RESTRICT``, więc duplikat musi zniknąć przed rekordem, w który
    został scalony.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    sfx = uuid.uuid4().hex[:8]
    data: dict[str, object] = {"sfx": sfx}

    async with AsyncSessionLocal() as db:
        renamed = Client(name=f"RAW-TRAFFIT-{sfx}", display_name=f"Poprawiona-{sfx}")
        # Nazwy surowe/prezentowane wybrane tak, by sortowały się ODWROTNIE:
        # po nazwie widocznej `AA-` < `AB-`, po surowej `AB-` < `ZZ-`.
        order_a = Client(name=f"ZZ-raw-{sfx}", display_name=f"AA-widoczna-{sfx}")
        order_b = Client(name=f"AB-raw-{sfx}")
        hidden = Client(name=f"HIDDEN-{sfx}", hidden=True)
        archived = Client(
            name=f"ARCHIVED-{sfx}", archived_at=datetime.now(timezone.utc)
        )
        db.add_all([renamed, order_a, order_b, hidden, archived])
        await db.flush()

        duplicate = Client(name=f"DUPLICATE-{sfx}", merged_into_client_id=renamed.id)
        db.add(duplicate)
        await db.commit()

        data.update(
            renamed_id=renamed.id,
            order_a_id=order_a.id,
            order_b_id=order_b.id,
            hidden_id=hidden.id,
            archived_id=archived.id,
            duplicate_id=duplicate.id,
        )

    try:
        yield data
    finally:
        async with AsyncSessionLocal() as db:
            for key in (
                "duplicate_id",
                "renamed_id",
                "order_a_id",
                "order_b_id",
                "hidden_id",
                "archived_id",
            ):
                row = await db.get(Client, data[key])
                if row is not None:
                    await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_overview_shows_display_name_not_raw_traffit_name(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_clients: dict[str, object],
) -> None:
    rows = await _fetch_overview(app_client, app_auth_headers)
    sfx = seeded_clients["sfx"]

    row = next(
        (r for r in rows if r["client_id"] == seeded_clients["renamed_id"]), None
    )
    assert row is not None, "klient z poprawioną nazwą musi być w rankingu"
    assert row["name"] == f"Poprawiona-{sfx}"

    # Surowa nazwa nie może pojawić się NIGDZIE w odpowiedzi — inaczej widok
    # nadal pokazuje wartość, od której użytkownik świadomie odszedł.
    assert not [r for r in rows if r["name"] == f"RAW-TRAFFIT-{sfx}"]


@pytest.mark.asyncio
async def test_overview_omits_merged_hidden_and_archived_rows(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_clients: dict[str, object],
) -> None:
    rows = await _fetch_overview(app_client, app_auth_headers)
    ids = {r["client_id"] for r in rows}

    assert seeded_clients["renamed_id"] in ids, "rekord kanoniczny musi zostać"
    for ghost in ("duplicate_id", "hidden_id", "archived_id"):
        assert seeded_clients[ghost] not in ids, (
            f"{ghost} to widmo — nie może być na liście"
        )


@pytest.mark.asyncio
async def test_overview_orders_by_displayed_name_not_raw_name(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_clients: dict[str, object],
) -> None:
    """Kolejność na ekranie idzie po nazwie widocznej, nie po niewidocznej kolumnie.

    Oba seedy mają revenue NULL, a końcowe ``items.sort`` po revenue jest
    stabilne — więc o kolejności decyduje ``order_by`` z SQL-a.
    """
    rows = await _fetch_overview(app_client, app_auth_headers)
    positions = {r["client_id"]: i for i, r in enumerate(rows)}

    a = positions.get(seeded_clients["order_a_id"])
    b = positions.get(seeded_clients["order_b_id"])
    assert a is not None and b is not None, "oba seedy muszą być w odpowiedzi"
    # Po nazwie widocznej: AA-widoczna < AB-raw. Po surowej byłoby odwrotnie
    # (AB-raw < ZZ-raw), więc ta asercja rozróżnia obie implementacje.
    assert a < b, f"kolejność po surowej nazwie (a={a}, b={b})"


@pytest.mark.asyncio
async def test_by_dl_still_responds(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """`/by-dl` nie był zmieniany — ten test pilnuje, że nie oberwał rykoszetem.

    Endpoint NIE selektuje `Client` (agreguje po `DeliveryLeadClientAssignment`),
    więc nie dotyczy go ani nazwa, ani filtr kanoniczności.
    """
    resp = await app_client.get(f"{OVERVIEW}/by-dl", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


def test_helpers_delegate_to_single_definition() -> None:
    """Aliasy nie mogą odkleić się od wspólnej reguły.

    Reguła nazwy była w repo skopiowana dosłownie dwa razy, a ten widok nie miał
    jej wcale — właśnie tak powstał incydent. Porównanie skompilowanego SQL-a
    wychwyci ponowne rozjechanie się definicji.
    """
    from app.api.client_directory import (
        _effective_client_name as directory_name,
        _visible_client_filters as directory_filters,
    )
    from app.api.clients import _effective_client_name as clients_name
    from app.services.client_identity import (
        client_display_name_expression,
        visible_client_predicates,
    )

    canonical_name = str(client_display_name_expression())
    assert str(clients_name()) == canonical_name
    assert str(directory_name()) == canonical_name

    canonical_filters = [str(p) for p in visible_client_predicates()]
    assert [str(p) for p in directory_filters()] == canonical_filters
