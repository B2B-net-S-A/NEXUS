"""Instrukcja obsługi zamówień ma nie rozjechać się z kodem, który opisuje.

Ta instrukcja (Pomoc → Procedury) mówi Delivery Leadowi rzeczy, które sprawdza
się tylko w kodzie: które pole wypełni się samo z PDF-a, przez co system dzieli
stawkę u Erste, ile dni przed końcem zamówienia przyjdzie alert. Taka treść
psuje się nie wtedy, gdy zmieni się proces w firmie, tylko wtedy, gdy ktoś
zmieni parser albo próg alertu — a wtedy nikt nie ma powodu wchodzić do modułu
Pomoc. Nieaktualna instrukcja jest gorsza od żadnej: czyta się ją z zaufaniem
i działa według niej bez sprawdzania.

Dlatego przypomnienie jest tutaj, w CI, na tej samej ścieżce co zmiana kodu.
Test porównuje odciski plików z logiką zamówień z odciskami zapisanymi przy
ostatnim przeglądzie instrukcji. Rozjazd = ktoś zmienił zachowanie systemu,
więc ktoś ma przeczytać instrukcję i potwierdzić, że nadal jest prawdziwa.

Test NIE twierdzi, że treść jest błędna — nie da się tego stwierdzić maszynowo.
Twierdzi, że nikt jej nie przejrzał po zmianie. Przegląd zakończony wnioskiem
„ta zmiana nie dotyczy instrukcji" jest w pełni poprawny i też kończy się
przestemplowaniem.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.data.procedures import (
    ORDERS_LOGIC_SOURCES,
    ORDERS_PROCEDURE,
    REPO_ROOT,
    STAMP_PATH,
    current_digests,
    load_stamp,
)

_RESTAMP_HINT = (
    "\n\nCo zrobić:\n"
    "  1. Otwórz app/data/procedures/"
    f"{ORDERS_PROCEDURE.filename} i sprawdź, czy nadal opisuje prawdę.\n"
    "  2. Popraw akapity, których zmiana dotyczy (albo nie popraw nic, jeśli nie dotyczy).\n"
    "  3. cd backend && python scripts/stamp_orders_procedure.py\n"
    "  4. Zacommituj instrukcję razem ze stemplem."
)


def _frontend_available() -> bool:
    return (REPO_ROOT / "frontend").is_dir()


def _watched(relative: str) -> bool:
    """Czy ten wpis da się sprawdzić w tym checkoucie."""
    if relative.startswith("frontend/"):
        return _frontend_available()
    return True


def test_watched_sources_exist() -> None:
    """Każdy obserwowany plik istnieje — przeniesiony musi być przedeklarowany.

    Bez tej asercji przeniesienie pliku CICHO wyłączałoby przypominanie o nim:
    odcisk „missing" jest stabilny, więc po jednym przestemplowaniu ten plik
    mógłby się już zmieniać dowolnie, nie budząc nikogo.
    """
    missing = [
        relative
        for relative in ORDERS_LOGIC_SOURCES
        if _watched(relative) and not (REPO_ROOT / relative).is_file()
    ]
    assert not missing, (
        "Te pliki z listy ORDERS_LOGIC_SOURCES nie istnieją:\n  · "
        + "\n  · ".join(missing)
        + "\n\nJeżeli zostały przeniesione — popraw ścieżki w "
        "app/data/procedures/__init__.py.\nJeżeli usunięte — usuń wpis "
        "i przejrzyj instrukcję, bo zniknął kawałek opisanej logiki."
    )


def test_orders_procedure_reviewed_after_logic_change() -> None:
    """Zmiana logiki zamówień wymusza przegląd instrukcji dla Delivery Leada."""
    stamped = load_stamp()["sources"]
    current = current_digests()

    drifted = sorted(
        relative
        for relative in ORDERS_LOGIC_SOURCES
        if _watched(relative) and stamped.get(relative) != current[relative]
    )

    assert not drifted, (
        "Zmieniła się logika procesu zamówień, a instrukcja w Pomoc → Procedury\n"
        "(„" + ORDERS_PROCEDURE.title + "”) nie została od tego czasu przejrzana.\n\n"
        "Zmienione pliki:\n  · " + "\n  · ".join(drifted) + _RESTAMP_HINT
    )


def test_stamp_covers_exactly_the_watched_list() -> None:
    """Stempel i lista obserwowanych plików opisują ten sam zbiór.

    Dopisanie pliku do listy bez przestemplowania dałoby test, który przechodzi
    (brak wpisu != rozjazd odcisków byłby porównaniem ``None != None``, gdyby
    ktoś kiedyś uprościł asercję wyżej), a usunięcie pliku z listy zostawiłoby
    w stemplu martwy wpis, który po cichu rośnie z każdym ticketem.
    """
    stamped = set(load_stamp()["sources"])
    declared = set(ORDERS_LOGIC_SOURCES)
    assert stamped == declared, (
        "Stempel rozjechał się z listą ORDERS_LOGIC_SOURCES.\n"
        f"Tylko w stemplu: {sorted(stamped - declared) or '—'}\n"
        f"Tylko na liście: {sorted(declared - stamped) or '—'}" + _RESTAMP_HINT
    )


def test_procedure_content_is_seedable() -> None:
    """Plik z treścią istnieje, jest niepusty i niesie datę przeglądu."""
    content = ORDERS_PROCEDURE.read()
    assert len(content) > 2000, (
        "Treść instrukcji wygląda na okrojoną — plik ma "
        f"{len(content)} znaków. Seed wysłałby to na produkcję."
    )
    reviewed = re.findall(
        r"^> \*\*Zgodność z systemem sprawdzona:\*\* (\d{4}-\d{2}-\d{2})$",
        content,
        flags=re.MULTILINE,
    )
    assert len(reviewed) == 1, (
        "Instrukcja musi zawierać DOKŁADNIE jedną linię z datą przeglądu "
        "w formacie `> **Zgodność z systemem sprawdzona:** RRRR-MM-DD` — "
        f"znaleziono {len(reviewed)}. Tę linię przestawia "
        "scripts/stamp_orders_procedure.py."
    )
    assert reviewed[0] == load_stamp()["reviewed_at"], (
        "Data widoczna w instrukcji różni się od daty w stemplu — czytelnik "
        "zobaczyłby inną świeżość, niż faktycznie potwierdzono." + _RESTAMP_HINT
    )


# Klienci, dla których moduł zamówień zachowuje się inaczej niż domyślnie.
# Lista jest jawna: bramki idą po `client_id` z env, więc nazwy klientów nie
# występują w kodzie i nie da się ich wyprowadzić automatycznie. Ten test
# broni przed usunięciem sekcji przy edycji treści.
_REQUIRED_CLIENT_SECTIONS = (
    "BNP",
    "Nordea",
    "Bank Pocztowy",
    "Polkomtel",
    "Cyfrowy Polsat",
    "Lotte Wedel",
    "BIK",
    "Credit Agricole",
    "Erste",
    "Orlen",
    "PFRON",
    # Serwer wymusza tu wybór części umowy (`validate_project_part(...,
    # require=True)`), więc bez tej sekcji instrukcja przemilczałaby pole,
    # bez którego zapis zamówienia u tego klienta po prostu nie przechodzi.
    "Centrum e-Zdrowia",
    # Polityki odczytu PDF z korpusu 09.2026 — każda ma własny plik w
    # order_policies/ (patrz ORDERS_LOGIC_SOURCES). Audyt 09.2026 wykrył, że
    # instrukcja ich nie opisywała (a Alior twierdził „brak reguły”), więc
    # przypinamy je jawnie: sekcja per polityka z własnym plikiem.
    "PKO BP",
    "KIR",
    "mLeasing",
    "VeloBank",
    "Cardif",
    "Alior",
)


def test_procedure_covers_every_client_with_dedicated_logic() -> None:
    """Każdy klient z własną regułą ma w instrukcji swoją sekcję."""
    content = ORDERS_PROCEDURE.read()
    absent = [name for name in _REQUIRED_CLIENT_SECTIONS if name not in content]
    assert not absent, (
        "Instrukcja nie wspomina klientów, dla których moduł zamówień działa "
        "inaczej niż domyślnie:\n  · " + "\n  · ".join(absent) + "\n\n"
        "Delivery Lead szuka w niej swojego klienta po nazwie — brak sekcji "
        "czyta się jak „u tego klienta nie ma nic szczególnego”."
    )


def test_seed_channels_agree_on_the_same_procedure() -> None:
    """Migracja i safety-net z entrypointu sieją TĘ SAMĄ procedurę.

    Dwa kanały istnieją, bo alembic na produkcji bywa osierocony. Rozjazd
    slugów oznaczałby dwa wiersze w module Pomoc: jeden aktualny, drugi
    z treścią sprzed wdrożenia — i nic w aplikacji nie mówiłoby, który jest
    który.
    """
    migration = next(
        (REPO_ROOT / "backend" / "alembic" / "versions").glob("*orders_procedure*.py"),
        None,
    )
    assert migration is not None, (
        "Nie znalazłem migracji siejącej instrukcję zamówień "
        "(alembic/versions/*orders_procedure*.py)."
    )
    entrypoint = (REPO_ROOT / "backend" / "entrypoint.sh").read_text(encoding="utf-8")
    migration_src = migration.read_text(encoding="utf-8")

    assert ORDERS_PROCEDURE.slug in migration_src, (
        f"migracja nie odwołuje się do sluga „{ORDERS_PROCEDURE.slug}”. "
        "Oba kanały muszą siać ten sam wiersz."
    )

    # Entrypoint nie importuje `app` (to samodzielny skrypt na asyncpg), więc
    # metadanych nie da się tam współdzielić przez import — są przepisane.
    # Przepisane znaczy: mogą się rozjechać, więc porównujemy je wprost.
    declared = re.search(
        r"^_REPO_PROCEDURES = (\[.*?\n\])$", entrypoint, flags=re.MULTILINE | re.DOTALL
    )
    assert declared, (
        "Nie znalazłem `_REPO_PROCEDURES` w entrypoint.sh — safety-net "
        "przestałby siać instrukcję na produkcji, gdzie alembic bywa osierocony."
    )
    mirrored = {row["slug"]: row for row in ast.literal_eval(declared.group(1))}
    assert ORDERS_PROCEDURE.slug in mirrored, (
        f"entrypoint.sh nie sieje „{ORDERS_PROCEDURE.slug}”."
    )
    row = mirrored[ORDERS_PROCEDURE.slug]
    assert (row["title"], row["sort_order"], row["filename"]) == (
        ORDERS_PROCEDURE.title,
        ORDERS_PROCEDURE.sort_order,
        ORDERS_PROCEDURE.filename,
    ), (
        "Metadane procedury w entrypoint.sh rozjechały się z "
        "app/data/procedures/__init__.py:\n"
        f"  entrypoint: {row['title']!r}, sort_order={row['sort_order']}, "
        f"plik={row['filename']!r}\n"
        f"  moduł:      {ORDERS_PROCEDURE.title!r}, "
        f"sort_order={ORDERS_PROCEDURE.sort_order}, "
        f"plik={ORDERS_PROCEDURE.filename!r}\n"
        "Kanał, który wygra na danym środowisku, zależy od tego, czy alembic "
        "jest aktualny — czyli od przypadku."
    )


# Progi, które instrukcja podaje czytelnikowi jako konkretne liczby, a które
# mieszkają w `app/core/config.py`. Tego pliku NIE ma na liście obserwowanych:
# zmienia się dwa razy częściej niż całe API zamówień (Sentry, AI, Traffit…),
# więc jego odcisk budziłby test przy zmianach, które instrukcji nie dotyczą —
# a guard, który krzyczy bez powodu, uczy się go obchodzić. Zamiast odcisku
# pliku przypinamy DOKŁADNIE te wartości, które padają w treści.
_QUOTED_THRESHOLDS = {
    "DL_ALERT_MD_THRESHOLD": (15.0, "próg alertu „mało MD” — 15 dni"),
    "DL_ALERT_REPEAT_DAYS": (7, "powtórka spraw z pulpitu — co 7 dni"),
}


def test_quoted_thresholds_still_match_configuration() -> None:
    """Liczby cytowane w instrukcji zgadzają się z domyślną konfiguracją."""
    from app.core.config import settings

    drifted = [
        f"{name}: instrukcja mówi {expected}, konfiguracja ma "
        f"{getattr(settings, name)} ({label})"
        for name, (expected, label) in _QUOTED_THRESHOLDS.items()
        if getattr(settings, name) != expected
    ]
    assert not drifted, (
        "Zmieniły się progi, które instrukcja podaje czytelnikowi jako konkretne\n"
        "liczby:\n  · " + "\n  · ".join(drifted) + "\n\n"
        "Popraw liczby w treści instrukcji, a potem zaktualizuj oczekiwania\n"
        "w _QUOTED_THRESHOLDS w tym pliku." + _RESTAMP_HINT
    )


def test_stamp_file_is_committed() -> None:
    assert STAMP_PATH.is_file(), (
        f"Brak {STAMP_PATH.name}. Wygeneruj go: "
        "cd backend && python scripts/stamp_orders_procedure.py"
    )


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "frontend").is_dir(),
    reason="checkout bez katalogu frontend/ — nie ma czego porównać",
)
def test_frontend_sources_are_watched_too() -> None:
    """Lista obserwowanych obejmuje też ekrany, nie tylko API.

    Instrukcja podaje etykiety przycisków i pól. Zmiana nazwy pola we froncie
    dezaktualizuje ją dokładnie tak samo jak zmiana reguły w backendzie, a jest
    o wiele łatwiejsza do przeoczenia, bo „to tylko tekst”.
    """
    frontend_entries = [
        relative
        for relative in ORDERS_LOGIC_SOURCES
        if relative.startswith("frontend/")
    ]
    assert frontend_entries, (
        "Z listy zniknęły wszystkie pliki frontendowe — instrukcja przestałaby "
        "reagować na zmiany etykiet, które sama cytuje."
    )
