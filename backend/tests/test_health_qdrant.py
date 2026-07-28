"""`/api/health` musi mówić prawdę o Qdrancie — i to WYKONUJĄC jego wywołanie.

Dlaczego ten plik istnieje. 2026-07-28 podbicie `qdrant-client` 1.12.1 → 1.18.0
usunęło `QdrantClient.search()`. Padło siedem wywołań w kodzie (wyszukiwanie
semantyczne, matching, podpowiedzi do pul, klasyfikacja CC) i przez dwie godziny
nic tego nie pokazało:

* CI nie ma Qdranta, więc żaden test nie dotknął tej ścieżki,
* `/api/health` nie miał klucza `qdrant` — pokazywał `healthy`,
* wyjątek na ścieżce wyszukiwania jest połykany i zwraca pustą listę, więc
  użytkownik widzi „brak wyników", a nie awarię.

Sonda sprawdzająca samą ŁĄCZNOŚĆ byłaby wtedy zielona: serwer Qdranta działał
bez zarzutu, niezgodna była biblioteka po naszej stronie. Dlatego sonda robi
prawdziwe zapytanie tą samą metodą, której używa `embedding_service` — i dlatego
poniżej stoi test strukturalny, który nie pozwoli jej z powrotem osłabić do
pingu.
"""

from __future__ import annotations

import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

# Bez Qdranta (CI) sonda kończy się `unhealthy` — to jest poprawna odpowiedź,
# nie porażka testu. Zamrażamy zbiór dopuszczalnych wartości, nie jedną z nich.
DOZWOLONE = {"healthy", "degraded", "misconfigured", "unhealthy"}


@pytest.mark.asyncio
async def test_health_raportuje_qdrant() -> None:
    """Klucz `qdrant` ma być w odpowiedzi ZAWSZE — jego brak był luką."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    checks = response.json()["checks"]
    assert "qdrant" in checks, (
        "`/api/health` znów nie mówi nic o Qdrancie — dokładnie ten stan sprawił, "
        "że dwugodzinna awaria wyszukiwania wektorowego była niewidoczna"
    )
    assert checks["qdrant"] in DOZWOLONE, f"nieznana wartość: {checks['qdrant']!r}"


@pytest.mark.asyncio
async def test_brak_qdranta_nie_kladzie_aplikacji() -> None:
    """Utrata wektorów to utrata funkcji, nie utrata aplikacji.

    W CI Qdranta nie ma, więc ten test biegnie w realnym scenariuszu „Qdrant
    nieosiągalny". Odpowiedź musi zostać 200/`healthy`, bo healthcheck Dockera
    restartuje kontener po 503 — a restart nie naprawi ani niezgodnej biblioteki,
    ani cudzego serwera, tylko dołoży przestój do awarii.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    body = response.json()
    if body["checks"].get("database") != "healthy":
        pytest.skip("brak bazy — ten test rozstrzyga tylko o wpływie Qdranta")

    assert response.status_code == 200
    assert body["status"] == "healthy", (
        "niedostępny Qdrant przestawił globalny status — to zamienia awarię "
        "wyszukiwania w restart-pętlę całego backendu"
    )


def test_sonda_wykonuje_prawdziwe_zapytanie() -> None:
    """Sonda nie może zdegenerować się do pingu.

    To jedyny test, który pilnuje SENSU tej sondy. Ping (`get_collections`) był
    zielony przez całą awarię 28.07, bo serwer był zdrowy. Wykrywalne jest
    dopiero wywołanie tej samej metody, z której korzysta aplikacja.
    """
    from app.main import _probe_qdrant

    zrodlo = inspect.getsource(_probe_qdrant)

    # Świadomie NIE zamrażamy nazwy metody: migracja siedmiu wywołań na
    # `query_points()` jest zaplanowana i ten test nie może jej blokować.
    # Zamrażamy to, co ma wartość — że sonda WYSYŁA wektor, zamiast pytać
    # serwer, czy żyje.
    wykonuje_zapytanie = "client.search(" in zrodlo or "client.query_points(" in zrodlo
    assert wykonuje_zapytanie, (
        "sonda Qdranta nie wywołuje już ani `search`, ani `query_points` — czyli "
        "sprawdza tylko, czy serwer odpowiada. Awaria z 28.07 (metoda usunięta "
        "z biblioteki, serwer zdrowy) przeszłaby przez taką sondę niezauważona"
    )
    assert "query_vector" in zrodlo or "query=" in zrodlo, (
        "sonda nie przekazuje już wektora — to nie jest zapytanie, tylko atrapa"
    )
