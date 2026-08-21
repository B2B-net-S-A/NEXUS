"""Kontrakt dostawy: właściwości obrazu i compose'a, których nic innego nie pilnuje.

Wspólny mianownik trzech rzeczy pinowanych tutaj: każda ma wariant „nieszkodliwej"
edycji, po której WSZYSTKO dalej jest zielone — CI przechodzi, obraz się buduje,
kontener wstaje — a prod po cichu traci właściwość, dla której to powstało.
Historia repo pokazuje, że to nie jest hipotetyczne: `mem_limit` przez miesiące
mieszkał w overlayu, którego Coolify nigdy nie czyta, i wyszło to dopiero
z `docker inspect` na żywym hoście (Memory=0, 2026-08-12).

Dlatego asercje są tu, a nie w review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[2]
# TEN plik, i tylko ten. `docker-compose.prod.yml` to referencja do ręcznej
# symulacji prod — Coolify buduje wyłącznie z docker_compose_location, więc
# cokolwiek stoi w overlayu, na produkcji nie obowiązuje.
_COMPOSE = _REPO / "docker-compose.yml"
_REQUIREMENTS = _REPO / "backend" / "requirements.txt"
_FRONTEND_DOCKERFILE = _REPO / "frontend" / "Dockerfile"

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)(ns|us|ms|s|m|h)?$")
_UNIT_SECONDS = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0, "m": 60.0, "h": 3600.0}


def _service(name: str) -> dict:
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    services = compose.get("services") or {}
    assert name in services, f"serwis {name!r} zniknął z docker-compose.yml"
    return services[name]


def _seconds(value: object) -> float:
    """Zamienia compose'owy zapis czasu ('300s', '5m', 90) na sekundy."""
    match = _DURATION.match(str(value).strip())
    assert match, f"nieczytelny zapis czasu w healthchecku: {value!r}"
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2) or "s"]


def test_backend_has_healthcheck_in_the_file_coolify_actually_reads() -> None:
    """Bez tego Coolify przełącza Traefika na kontener w chwili startu entrypointu.

    Czyli PRZED `alembic upgrade heads`, siatką DDL i seedem — a to jest okno 502
    dla ludzi w trakcie pracy przy każdym deployu. Definicja w
    docker-compose.prod.yml tego NIE załatwia i właśnie ta pomyłka już raz
    kosztowała (mem_limit).
    """
    healthcheck = _service("backend").get("healthcheck")
    assert healthcheck, (
        "serwis `backend` nie ma healthchecka w docker-compose.yml. Coolify czyta "
        "wyłącznie ten plik — healthcheck przeniesiony do docker-compose.prod.yml "
        "nie obowiązuje na produkcji."
    )
    probe = " ".join(str(part) for part in (healthcheck.get("test") or []))
    assert "/api/health" in probe, (
        f"sonda backendu nie pyta /api/health: {probe!r}. To jedyny endpoint "
        "o kontraktowym kształcie (~/.claude/rules/deployment.md) i jedyny, który "
        "sprawdza bazę — sonda TCP zieleniłaby kontener bez działającej aplikacji."
    )


def test_backend_healthcheck_start_period_covers_a_heavy_migration() -> None:
    """Za krótkie okno startu zamienia poprawkę w nowy tryb awarii.

    Nieudane sondy w `start_period` nie liczą się do `retries`, a pierwsza udana
    kończy okno natychmiast (stąd `start_interval`) — więc hojny zapas NIC nie
    kosztuje przy szybkim starcie. Za to skąpy zapas oznacza, że ciężka migracja
    (repo ma setki rewizji i udokumentowany incydent timeoutu) zostaje uznana za
    awarię w połowie `alembic upgrade`, a frontend czekający na `service_healthy`
    nie wstanie w ogóle.
    """
    healthcheck = _service("backend")["healthcheck"]
    assert _seconds(healthcheck.get("start_period", 0)) >= 120, (
        "start_period backendu jest krótszy niż 2 minuty — to mniej niż potrafi "
        "trwać `alembic upgrade heads` razem z siatką DDL, seedem i importem "
        "portfela klientów w entrypoint.sh."
    )
    assert healthcheck.get("start_interval"), (
        "brak `start_interval`: bez niego kontener czeka na pierwszą sondę pełne "
        "`interval` (15 s), więc długi start_period zamienia się w długie okno "
        "„no available server” przy KAŻDYM deployu, także tym bez migracji."
    )


def test_frontend_waits_for_a_healthy_backend_not_merely_a_started_one() -> None:
    """Goła lista `depends_on: [backend]` jest spełniona w chwili startu kontenera.

    Czyli w trakcie migracji — frontend renderował wtedy RSC-e przeciw serwerowi,
    którego jeszcze nie ma.
    """
    depends_on = _service("frontend").get("depends_on")
    assert isinstance(depends_on, dict), (
        "frontend.depends_on wrócił do postaci listy — warunek `service_healthy` "
        f"zniknął: {depends_on!r}"
    )
    assert depends_on.get("backend", {}).get("condition") == "service_healthy", (
        f"frontend nie czeka na zdrowy backend: {depends_on!r}"
    )


def test_every_direct_python_dependency_is_pinned_exactly() -> None:
    """Zakres wersji = prod i CI mogą zainstalować różny kod z tego samego SHA.

    Coolify przebudowuje obraz ze źródeł przy KAŻDYM deployu i przy KAŻDYM
    rollbacku, więc pływający zakres sprawia, że rollback cofa kod aplikacji, ale
    nie jej zależności. Ścieżki AI są celowo fail-open, więc objawem złego bumpu
    nie jest 500, tylko po cichu pusty wynik (dokładnie tak przeszedł bump
    qdrant-client — patrz komentarz w requirements.txt).
    """
    floating: list[str] = []
    for raw in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            floating.append(line)
    assert not floating, (
        "bezpośrednie zależności bez dokładnego pinu: "
        f"{floating}. Zakres wersji podnosi się sam, przy dowolnym niezwiązanym "
        "deployu, bez ani jednego diffa i bez review."
    )


def test_frontend_image_installs_from_the_committed_lockfile() -> None:
    """`npm install` po cichu godzi rozjazd package.json <-> package-lock.json.

    Tryby awarii CI i builda produkcyjnego byłyby wtedy PRZECIWNE na tym samym
    wejściu: `npm ci` w CI przerywa (czerwono), a `npm install` w obrazie
    rozwiązuje drzewo od nowa i buduje się zielono — wysyłając na prod
    zależności, których nie przeszedł ani type-check, ani Vitest, ani Trivy
    (ten skanuje zacommitowany lock).
    """
    dockerfile = _FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
    # Interesuje nas wyłącznie etap `deps` — to on instaluje zależności.
    stages = dockerfile.split("\nFROM ")
    deps = next((s for s in stages if "AS deps" in s.splitlines()[0]), None)
    assert deps, "etap `deps` zniknął z frontend/Dockerfile — sprawdź, co go zastąpiło"
    # Komentarze POZA analizą: ten Dockerfile tłumaczy w komentarzu, czym `npm
    # install` grozi, więc naiwne szukanie podciągu w całym tekście oskarżałoby
    # plik o dokładnie tę wadę, przed którą ostrzega.
    instructions = [
        line.strip()
        for line in deps.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    installs = [ln for ln in instructions if re.search(r"\bnpm\s+(ci|install)\b", ln)]
    assert installs, "etap `deps` nie instaluje już zależności?"
    for line in installs:
        assert "npm install" not in line, (
            f"produkcyjny obraz frontendu instaluje przez `npm install`: {line!r}. "
            "Musi być `npm ci`, żeby obraz był tym samym drzewem, które przeszło CI."
        )

    copies = [ln for ln in instructions if ln.upper().startswith("COPY")]
    assert any("package-lock.json" in ln for ln in copies), (
        "etap `deps` nie kopiuje już package-lock.json — `npm ci` bez locka nie ma "
        "z czego instalować."
    )
    for line in copies:
        assert "package-lock.json*" not in line, (
            f"COPY używa glob-gwiazdki przy lockfile'u: {line!r}. Przy braku locka "
            "COPY kończy się sukcesem i awaria wychodzi dopiero jako niejasny błąd "
            "npm — zamiast wywalić build na brakującym pliku."
        )
