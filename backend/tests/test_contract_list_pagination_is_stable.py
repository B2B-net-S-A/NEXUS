"""Stronicowanie rejestru umów musi być deterministyczne.

``list_contracts`` robiło ``offset/limit`` BEZ ``order_by``. Postgres zwraca
wtedy wiersze w kolejności skanu, a każdy ``UPDATE`` tworzy nową wersję krotki
i przesuwa wiersz na koniec — więc czytelnik, który pobrał stronę 1 przed
cudzym zapisem, a stronę 2 po nim, NIE zobaczy jednej umowy na ŻADNEJ stronie,
a inną zobaczy dwa razy. Przy ~296 stronach rejestru i kilku osobach
pracujących równolegle to nie jest przypadek brzegowy.

Odtworzone na żywej bazie przed poprawką: po semantycznie pustym
``UPDATE contracts SET project_name = project_name WHERE id = 73`` z okna
czytelnika wypadła umowa 375, a 73 pokazała się dwukrotnie.

Testy sprawdzają WŁASNOŚĆ (kolejność i rozłączność stron), a nie obecność
konkretnego wywołania — dzięki temu przechodzą przy każdej poprawnej zmianie
sortowania i padają przy każdej, która determinizm odbiera.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _page(app_client: AsyncClient, headers: dict, page: int, size: int = 20):
    resp = await app_client.get(
        f"/api/contracts?page={page}&page_size={size}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_contract_list_is_ordered_by_a_unique_key(
    app_client: AsyncClient, app_auth_headers: dict
):
    body = await _page(app_client, app_auth_headers, 1)
    ids = [it["id"] for it in body.get("items", [])]
    if len(ids) < 2:
        pytest.skip("za mało umów w bazie, żeby ocenić kolejność")
    assert ids == sorted(ids, reverse=True), (
        "lista umów nie jest posortowana malejąco po unikalnym kluczu — bez "
        f"tego stronicowanie gubi i dubluje wiersze; otrzymano {ids[:10]}"
    )


async def test_contract_list_pages_do_not_overlap(
    app_client: AsyncClient, app_auth_headers: dict
):
    first = await _page(app_client, app_auth_headers, 1, size=5)
    if first.get("total", 0) < 10:
        pytest.skip("za mało umów w bazie, żeby porównać dwie strony")
    second = await _page(app_client, app_auth_headers, 2, size=5)

    a = [it["id"] for it in first["items"]]
    b = [it["id"] for it in second["items"]]
    overlap = set(a) & set(b)
    assert not overlap, (
        f"te same umowy na stronie 1 i 2: {sorted(overlap)} — czytelnik widzi "
        "je dwa razy, a tyle samo innych nie zobaczy wcale"
    )
    assert min(a) > max(b), (
        "strony nie są rozłącznymi wycinkami jednego porządku "
        f"(strona1 min={min(a)}, strona2 max={max(b)})"
    )


async def test_contractors_list_breaks_ties_on_a_unique_key(
    app_client: AsyncClient, app_auth_headers: dict
):
    """``(kubełek statusu, start_date)`` nie rozstrzyga remisów.

    W bazie harnessu było 76 grup o identycznej parze — ta sama klasa co brak
    ``ORDER BY``, tylko rzadsza, więc trudniejsza do złapania.
    """
    resp = await app_client.get(
        "/api/contractors?page=1&page_size=50", headers=app_auth_headers
    )
    if resp.status_code == 403:
        pytest.skip("rola testowa nie ma dostępu do modułu kontraktorów")
    assert resp.status_code == 200, resp.text
    items = resp.json().get("items", [])
    if len(items) < 2:
        pytest.skip("za mało kontraktorów w bazie")

    # Wiersz kontraktora ma `contract_id`, nie `id` — kolejność ustala
    # `Contract.id`, więc to jest ten sam klucz pod inną nazwą.
    groups: dict[tuple, list[int]] = {}
    for it in items:
        groups.setdefault((it.get("status"), it.get("start_date")), []).append(
            it["contract_id"]
        )
    tied = {k: v for k, v in groups.items() if len(v) > 1}
    if not tied:
        pytest.skip(
            "w tej bazie nie ma dwóch kontraktorów o tej samej parze "
            "(status, start_date) — nie ma remisu do rozstrzygnięcia"
        )
    for key, ids in tied.items():
        assert ids == sorted(ids, reverse=True), (
            f"remis {key} nie jest rozstrzygnięty malejącym id: {ids}"
        )
