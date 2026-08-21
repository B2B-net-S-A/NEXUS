"""Każda nowa wartość ``aifeaturekey`` musi mieć lustro w ``entrypoint.sh``.

Prod alembic bywa OSIEROCONY (patrz CLAUDE.md — dlatego entrypoint niesie
safety-net DDL). Konsekwencja jest asymetryczna i dlatego cicha: sama migracja
wystarcza w CI, więc test jednostkowy, przegląd i zielony pipeline nic nie
zauważą, a na produkcji brak wartości enuma zamienia KAŻDY zapis do
``ai_features``/``ai_usage_log`` w ``InvalidTextRepresentationError`` — czyli
funkcja AI, która „przeszła", jest tam martwa.

Ten kontrakt czyta OBIE strony ze źródeł, a nie z listy wpisanej ręcznie:
lista pisana ręcznie starzeje się dokładnie w tym samym momencie, w którym
przestaje pilnować (nowy klucz = nowy wpis, o którym trzeba pamiętać — a to
jest ten sam rodzaj pamiętania, który tu zawodzi).

Świadome ograniczenie: sprawdzamy wyłącznie wartości dokładane przez
``ALTER TYPE ... ADD VALUE``. Klucze z pierwotnego ``CREATE TYPE`` (0085)
lustra nie potrzebują — typ powstaje razem z nimi.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.ai_feature import AIFeatureKey

_BACKEND = Path(__file__).resolve().parents[1]
_VERSIONS = _BACKEND / "alembic" / "versions"
_ENTRYPOINT = _BACKEND / "entrypoint.sh"

_ADD_VALUE = re.compile(
    r"ALTER TYPE aifeaturekey ADD VALUE(?: IF NOT EXISTS)? '([a-z_]+)'"
)
# Seed wiersza w ai_features — w migracjach i w entrypoincie ten sam kształt
# (`INSERT ... SELECT '<klucz>'`), rozbity na sklejane literały stringów.
_SEED = re.compile(r"SELECT '([a-z_]+)', TRUE, 0, ")


def _migration_sources() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(_VERSIONS.glob("0*.py"))
    )


def _entrypoint_source() -> str:
    return _ENTRYPOINT.read_text(encoding="utf-8")


def test_every_migrated_enum_value_is_mirrored_in_entrypoint() -> None:
    migrated = set(_ADD_VALUE.findall(_migration_sources()))
    mirrored = set(_ADD_VALUE.findall(_entrypoint_source()))

    assert migrated, "Regex przestał trafiać w ALTER TYPE — test nic nie pilnuje."
    missing = migrated - mirrored
    assert not missing, (
        f"Wartości aifeaturekey bez lustra w entrypoint.sh: {sorted(missing)}. "
        "Na produkcji (osierocony alembic) każdy INSERT do ai_features / "
        "ai_usage_log dla tego klucza padnie InvalidTextRepresentationError, "
        "mimo zielonego CI."
    )


def test_every_migrated_enum_value_has_a_seed_row_in_entrypoint() -> None:
    """Brak wiersza w ``ai_features`` nie blokuje wywołania (kwota jest
    fail-open) — czyni funkcję NIEWIDOCZNĄ w Ustawieniach → AI, czyli nie do
    ograniczenia przez administratora i nie do policzenia w raporcie zużycia.

    Oczekiwany zbiór bierzemy z literałów ``ALTER TYPE`` (te są wypisane wprost
    w każdej rewizji), a nie z seedów: kilka starszych migracji składa seed
    z f-stringa, więc nazwa klucza nie występuje tam w źródle dosłownie.
    """
    migrated = set(_ADD_VALUE.findall(_migration_sources()))
    seeded = set(_SEED.findall(_entrypoint_source())) & _FEATURE_VALUES

    assert migrated, "Regex przestał trafiać w ALTER TYPE — test nic nie pilnuje."
    missing = migrated - seeded
    assert not missing, (
        f"Wartości aifeaturekey bez seedu w entrypoint.sh: {sorted(missing)}. "
        "Funkcja nie pokaże się w Ustawieniach → AI, więc nie da się jej "
        "ograniczyć ani zobaczyć jej zużycia."
    )


_FEATURE_VALUES = {k.value for k in AIFeatureKey}


def test_mirrored_values_are_real_enum_members() -> None:
    """Literówka w entrypoincie jest niema: ``ADD VALUE IF NOT EXISTS`` na
    nieistniejącej nazwie przechodzi bez błędu i zostawia funkcję martwą."""
    unknown = set(_ADD_VALUE.findall(_entrypoint_source())) - _FEATURE_VALUES
    assert not unknown, (
        f"entrypoint.sh dodaje wartości aifeaturekey nieznane Pythonowi: "
        f"{sorted(unknown)} — literówka albo pozostałość po usuniętym kluczu."
    )


def test_new_wave_keys_are_covered_end_to_end() -> None:
    """Kotwica na dwie powierzchnie z tej fali: generator CV B2B (najdroższe
    wywołanie Claude'a w produkcie) i MINDY. Obie stały poza systemem kwot,
    bo nie miały klucza, którym można by je ograniczyć."""
    migrations = _migration_sources()
    entrypoint = _entrypoint_source()
    for key in ("cv_generator", "mindy_chat"):
        assert key in _FEATURE_VALUES
        assert f"ADD VALUE IF NOT EXISTS '{key}'" in migrations, key
        assert f"ADD VALUE IF NOT EXISTS '{key}'" in entrypoint, key
        assert f"SELECT '{key}', TRUE, 0, " in migrations, key
        assert f"SELECT '{key}', TRUE, 0, " in entrypoint, key
