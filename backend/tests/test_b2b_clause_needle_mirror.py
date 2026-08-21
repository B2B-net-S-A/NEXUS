"""Lustro rejestru klauzul B2B: frontend vs backend + normalizacja nazwy Klienta.

Baner „ten klient ma specyficzne zapisy" w Generatorze Umów B2B to JEDYNY sygnał,
jaki rekruter dostaje przed wydaniem dokumentu — nie ma pola w odpowiedzi API, nie
ma odpowiednika negatywnego, nie ma linii w wierszu rejestru. Gdy lista needle'i
po stronie frontendu rozjedzie się z `CLIENT_OVERRIDES`, backend nadal podmienia
§ 10 (zakaz konkurencji + kary umowne), a baner milczy — i to się już zdarzyło:
commit poszerzający needle „e-zdrowia" o „e-zdrowie"/„ezdrowie" zaktualizował
lustro w `ContractRegisterDialog.tsx`, a `hasSpecialClauses` pominął.

Testy w obu językach asertowały wtedy różne zbiory nazw, więc CI było zielone po
obu stronach. Ten plik czyta JEDNO źródło z każdej strony i porównuje je wprost.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TSX = (
    _REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "v2"
    / "pages"
    / "B2BContractGeneratorV2.tsx"
)


def _tsx_source() -> str:
    if not (_REPO_ROOT / "frontend").is_dir():
        # Checkout bez frontendu (obraz tylko-backend) — nie ma czego porównać.
        # Świadomie NIE skip przy samym braku pliku: przeniesienie komponentu
        # bez przeniesienia lustra to dokładnie ten rozjazd, który tu łapiemy.
        pytest.skip("brak katalogu frontend/ w tym checkoucie")
    assert _TSX.is_file(), (
        f"Nie znaleziono {_TSX} — jeśli komponent został przeniesiony, "
        "zaktualizuj ścieżkę w tym teście razem z nim."
    )
    return _TSX.read_text(encoding="utf-8")


def _tsx_string_array(source: str, const_name: str) -> list[str]:
    """Wyłuskaj tablicę stringów `export const <name> = [...]` z pliku .tsx."""
    m = re.search(rf"export const {const_name} = \[(.*?)\];", source, flags=re.DOTALL)
    assert m, f"Nie znaleziono tablicy {const_name} w {_TSX.name}"
    return [
        unicodedata.normalize("NFC", x) for x in re.findall(r'"([^"]*)"', m.group(1))
    ]


def _backend_needles() -> tuple[set[str], set[str]]:
    """(needle'e dające modyfikacje, needle'e świadomie puste) z rejestru."""
    from app.services.b2b_contract_generator.clause_override_content import (
        CLIENT_OVERRIDES,
    )

    positive: set[str] = set()
    negative: set[str] = set()
    for needles, ops_builder in CLIENT_OVERRIDES:
        bucket = negative if not ops_builder("pl") else positive
        bucket.update(unicodedata.normalize("NFC", n) for n in needles)
    return (positive, negative)


def test_frontend_needle_lists_mirror_the_backend_registry():
    """Obie listy needle'i muszą być identyczne — co do znaku."""
    source = _tsx_source()
    fe_positive = set(_tsx_string_array(source, "CLAUSE_OVERRIDE_NEEDLES"))
    fe_negative = set(_tsx_string_array(source, "CLAUSE_OVERRIDE_NEEDLES_NONE"))
    be_positive, be_negative = _backend_needles()

    assert fe_positive == be_positive, (
        "Lista needle'i w B2BContractGeneratorV2.tsx rozjechała się z "
        f"CLIENT_OVERRIDES. Brak we froncie: {sorted(be_positive - fe_positive)}; "
        f"nadmiarowe: {sorted(fe_positive - be_positive)}."
    )
    assert fe_negative == be_negative, (
        "Lista needle'i „bez modyfikacji” rozjechała się z CLIENT_OVERRIDES. "
        f"Brak we froncie: {sorted(be_negative - fe_negative)}; "
        f"nadmiarowe: {sorted(fe_negative - be_negative)}."
    )


def test_frontend_normalizes_like_the_backend_matcher():
    """Front musi robić NFC + zwinięcie białych znaków, tak jak `_norm`."""
    source = _tsx_source()
    fn = source[source.index("export function hasSpecialClauses") :][:900]
    assert '.normalize("NFC")' in fn, (
        "hasSpecialClauses nie normalizuje do NFC — nazwa wklejona w NFD "
        "(wizualnie identyczna) nie trafi needle'a z diakrytykami."
    )
    assert "replace(/\\s+/g" in fn, (
        "hasSpecialClauses nie zwija ciągów białych znaków — „Biuro  Informacji "
        "Kredytowej” trafia backend, a baner milczy."
    )


@pytest.mark.parametrize(
    "raw",
    [
        "PAŃSTWOWY FUNDUSZ REHABILITACJI OSÓB NIEPEŁNOSPRAWNYCH",
        "Centrum e-Zdrowia",
        "E-Zdrowie",
        "Biuro  Informacji  Kredytowej S.A.",
    ],
)
def test_backend_matcher_is_unicode_form_agnostic(raw):
    """NFD i NFC tej samej nazwy muszą dać ten sam wpis rejestru.

    Kanoniczna nazwa PFRON nie zawiera podciągu „pfron" — łapie ją WYŁĄCZNIE
    needle z diakrytykami, więc forma zdekomponowana (wklejka z macOS) cicho
    gubiła wynegocjowany § 10 i renderowała klauzulę domyślną.
    """
    from app.services.b2b_contract_generator.clause_overrides import resolve_override

    nfc = unicodedata.normalize("NFC", raw)
    nfd = unicodedata.normalize("NFD", raw)
    assert nfc != nfd or "ń" not in raw.lower()  # sanity: formy są różne bajtowo
    key_nfc, ops_nfc = resolve_override(nfc, "pl")
    key_nfd, ops_nfd = resolve_override(nfd, "pl")
    assert key_nfc is not None, f"{raw!r} przestał trafiać rejestr"
    assert (key_nfd, ops_nfd) == (key_nfc, ops_nfc)
