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


async def _qdrant_gdy_klient_rzuca(monkeypatch, blad: BaseException) -> str:
    """Uruchamia `/api/health` z klientem Qdranta rzucającym zadany wyjątek.

    Podmieniamy KLIENTA, nie sondę. Pierwsza wersja tego testu podmieniała całą
    `_probe_qdrant` — i przez to omijała klasyfikację, którą miała sprawdzać
    (test padał, choć kod działał poprawnie). Podmiana na poziomie klienta
    przepuszcza przez prawdziwy `_probe_qdrant`, więc testowany jest cały
    łańcuch: wyjątek klienta → rozpoznanie przyczyny → gałąź w endpoincie.
    """
    import qdrant_client

    import app.main as m

    class KlientRzucajacy:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_collections(self):
            raise blad

    monkeypatch.setattr(qdrant_client, "QdrantClient", KlientRzucajacy)
    # Wyzeruj cache rozmiaru wektora, żeby sonda faktycznie poszła do klienta.
    monkeypatch.setattr(m, "_qdrant_vector_size", None)

    async with AsyncClient(
        transport=ASGITransport(app=m.app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert response.status_code == 200, "problem z Qdrantem nie może dawać 503"
    return body["checks"]["qdrant"]


@pytest.mark.asyncio
async def test_wolny_qdrant_to_degraded_a_nie_unhealthy(monkeypatch) -> None:
    """Qdrant, który odpowiada wolno, jest ŻYWY — nie wolno go zgłaszać jako awarię.

    Regresja z przeglądu #986. Klient ma własny limit (2 s) i przy wolnej
    odpowiedzi rzuca `ResponseHandlingException` owijający `httpx.TimeoutException`
    — zwykły wyjątek, NIE `asyncio.TimeoutError`. Pierwsza wersja łapała tylko
    ten drugi, więc gałąź „degraded" była nieosiągalna: limit klienta zawsze
    wyprzedza `wait_for`, a wolny Qdrant lądował w „unhealthy". Dokładnie ten
    fałszywy alarm, któremu ta sonda miała zapobiegać.

    Zmierzone na żywej atrapie (serwer przyjmujący połączenie i nieodpowiadający):
    przed poprawką `unhealthy`, po poprawce `degraded`.
    """
    import httpx

    owiniety = RuntimeError("ResponseHandlingException")
    owiniety.__cause__ = httpx.ReadTimeout("za wolno")

    wynik = await _qdrant_gdy_klient_rzuca(monkeypatch, owiniety)
    assert wynik == "degraded", (
        "wolny (ale żywy) Qdrant znów jest raportowany jako awaria — "
        "przekroczenie czasu klienta nie jest odróżniane od realnego błędu"
    )


@pytest.mark.asyncio
async def test_zepsuty_qdrant_to_unhealthy(monkeypatch) -> None:
    """Kontrola przeciwna: błąd, który NIE jest przekroczeniem czasu, ma być awarią.

    Bez tego testu poprzedni dałoby się „naprawić", odsyłając `degraded` na
    każdy wyjątek — i sonda przestałaby wykrywać to, po co powstała: zniknięcie
    metody z biblioteki przy podbiciu wersji.
    """
    wynik = await _qdrant_gdy_klient_rzuca(
        monkeypatch,
        AttributeError("'QdrantClient' object has no attribute 'search'"),
    )
    assert wynik == "unhealthy", (
        "zniknięcie metody w bibliotece — czyli awaria z 28.07 — nie jest już "
        "raportowane jako awaria"
    )


@pytest.mark.asyncio
async def test_odmowa_polaczenia_to_unhealthy_a_nie_degraded(monkeypatch) -> None:
    """Leżący Qdrant to awaria, choć jego wyjątek jest owinięty tak samo jak wolny.

    `qdrant-client` owija oba przypadki w ten sam typ zewnętrzny, więc bez
    zaglądania w `__cause__` nie da się ich odróżnić — a odesłanie `degraded`
    na leżący serwer ukrywałoby realną awarię.
    """
    import httpx

    owiniety = RuntimeError("ResponseHandlingException")
    owiniety.__cause__ = httpx.ConnectError("odmowa połączenia")

    wynik = await _qdrant_gdy_klient_rzuca(monkeypatch, owiniety)
    assert wynik == "unhealthy", (
        "leżący Qdrant jest raportowany jako 'tylko wolny' — to ukrywa awarię"
    )


def test_rozpoznawanie_przekroczenia_czasu_patrzy_w_lancuch_przyczyn() -> None:
    """`qdrant-client` owija wyjątki `httpx`, więc typ zewnętrzny nic nie mówi.

    Odmowa połączenia (Qdrant leży) i wolna odpowiedź (Qdrant żyje) wyglądają
    tak samo z zewnątrz — rozstrzyga dopiero `__cause__`.
    """
    import httpx

    from app.main import _czy_przekroczony_czas

    owiniety_timeout = RuntimeError("ResponseHandlingException")
    owiniety_timeout.__cause__ = httpx.ReadTimeout("za wolno")
    assert _czy_przekroczony_czas(owiniety_timeout) is True

    owiniete_polaczenie = RuntimeError("ResponseHandlingException")
    owiniete_polaczenie.__cause__ = httpx.ConnectError("odmowa połączenia")
    assert _czy_przekroczony_czas(owiniete_polaczenie) is False, (
        "odmowa połączenia to leżący Qdrant, nie wolny — nie wolno jej "
        "traktować jak przekroczenia czasu"
    )

    assert _czy_przekroczony_czas(AttributeError("brak metody search")) is False


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
