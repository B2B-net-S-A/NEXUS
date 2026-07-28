"""Filtr umiejętności musi obejmować CAŁĄ rodzinę aliasów, nie jedną pisownię.

Dlaczego ten plik istnieje. Tabela `skill_aliases` (458 wpisów na produkcji)
mapuje warianty na nazwę kanoniczną, ale dane kandydatów NIE są kanonizowane —
w bazie leży dosłownie to, co przyszło z CV albo z importu. Zmierzone na
produkcji 2026-07-28 (55 428 kandydatów), rodzina „Microsoft SQL Server":

    mssql=21, ms sql=18, sql server=18, microsoft sql server=9, microsoft sql=3

Główna lista sprowadzała ZAPYTANIE do nazwy kanonicznej i szukała wyłącznie jej
dosłownego brzmienia, więc zwracała **9 z ponad 60** — te same 9 niezależnie od
tego, który wariant wpisał rekruter. Wyszukiwarka strukturalna nie normalizowała
nic, więc zwracała tyle, ile dosłownych trafień miała wpisana pisownia. Żadna z
powierzchni nie była nadzbiorem drugiej.

Skala poza MSSQL: HTML gubił 35 z 76, REST API 34 z 69, Java 27 ze 152,
CSS 24 z 71, Kafka 17 z 65.

Filtr „nie ma X" jest TWARDY — pominięty kandydat wygląda dokładnie tak samo jak
nieistniejący, więc rozjazd był z ekranu niewidoczny.
"""

from __future__ import annotations

import pytest

from app.services.scoring_service import (
    ALIAS_MAP,
    canonical_skill_names,
    set_alias_map,
    skill_name_variants,
    skill_variant_groups,
)

# Wycinek prawdziwej mapy z produkcji (alias -> kanoniczna, małymi literami).
RODZINA_MSSQL = {
    "mssql": "microsoft sql server",
    "ms sql": "microsoft sql server",
    "sql server": "microsoft sql server",
    "microsoft sql": "microsoft sql server",
    "microsoft sql server": "microsoft sql server",
    "golang": "go",
    "go lang": "go",
    "go": "go",
    "python": "python",
}


@pytest.fixture(autouse=True)
def _mapa_aliasow():
    """Podstawia wycinek mapy i przywraca poprzedni stan po teście."""
    poprzednia = dict(ALIAS_MAP)
    set_alias_map(RODZINA_MSSQL)
    yield
    set_alias_map(poprzednia)


@pytest.mark.parametrize(
    "wpisane",
    ["MSSQL", "MS SQL", "SQL Server", "Microsoft SQL", "Microsoft SQL Server"],
)
def test_kazdy_wariant_rozwija_sie_w_te_sama_pelna_rodzine(wpisane: str) -> None:
    """Rekruter ma dostać ten sam komplet, cokolwiek wpisze.

    To jest sedno poprawki: wcześniej każda z tych pisowni dawała inny wynik
    (albo — na głównej liście — ten sam, ale zawężony do 9 z ponad 60 osób).
    """
    warianty = set(skill_name_variants([wpisane]))
    assert warianty == {
        "microsoft sql server",
        "mssql",
        "ms sql",
        "sql server",
        "microsoft sql",
    }, f"{wpisane!r} nie rozwinęło się w pełną rodzinę: {sorted(warianty)}"


def test_kanoniczna_jest_pierwsza() -> None:
    """Kolejność nie jest przypadkowa — nazwa kanoniczna prowadzi rodzinę."""
    assert skill_name_variants(["MSSQL"])[0] == "microsoft sql server"


def test_grupy_nie_zlewaja_roznych_umiejetnosci() -> None:
    """Granice między umiejętnościami muszą przetrwać rozwinięcie.

    Bez tego „ma MSSQL ORAZ Pythona" zamienia się w „ma wszystkie pisownie
    MSSQL naraz" — zapytanie, które nie zwróci nikogo. Ta pułapka jest jedynym
    powodem, dla którego `skill_variant_groups` istnieje obok
    `skill_name_variants`.
    """
    grupy = skill_variant_groups(["MSSQL", "Python"])
    assert len(grupy) == 2, f"oczekiwano dwóch rodzin, jest {len(grupy)}"
    assert set(grupy[0]) == {
        "microsoft sql server",
        "mssql",
        "ms sql",
        "sql server",
        "microsoft sql",
    }
    assert grupy[1] == ["python"]


def test_powtorzona_umiejetnosc_daje_jedna_rodzine() -> None:
    """Dwie pisownie tej samej rzeczy to jedna umiejętność, nie dwie.

    Istotne przy łączeniu AND: inaczej „MSSQL i SQL Server" wymagałoby dwóch
    niezależnych trafień w tę samą rodzinę.
    """
    assert len(skill_variant_groups(["MSSQL", "SQL Server"])) == 1


def test_nieznana_umiejetnosc_przechodzi_bez_zmian() -> None:
    """Brak w mapie nie może niczego gubić ani wymyślać."""
    assert skill_name_variants(["Zzzqqqniema"]) == ["zzzqqqniema"]
    assert skill_variant_groups(["Zzzqqqniema"]) == [["zzzqqqniema"]]


def test_pusta_mapa_zachowuje_sie_jak_brak_aliasow() -> None:
    """Testy i narzędzia offline działają bez bazy — nie wolno tego zepsuć."""
    set_alias_map({})
    assert skill_name_variants(["MSSQL", "Python"]) == ["mssql", "python"]
    assert skill_variant_groups(["MSSQL"]) == [["mssql"]]


def test_canonical_skill_names_nadal_zwija() -> None:
    """Stara funkcja ma ZOSTAĆ zwijająca — używa jej scoring.

    Porównanie dwóch zbiorów umiejętności (kandydat kontra oferta) wymaga
    postaci kanonicznej. Rozwinięcie na warianty zawyżyłoby tam trafienia.
    Rozdzielenie tych dwóch zastosowań jest celowe.
    """
    assert canonical_skill_names(["MSSQL", "SQL Server"]) == ["microsoft sql server"]


def test_predykat_rozwija_rodzine_wiec_obie_powierzchnie_ja_dostaja() -> None:
    """Rozwinięcie MUSI siedzieć w predykacie, nie w miejscach wywołania.

    To jedyny punkt wspólny `GET /api/candidates` i `POST /api/search/candidates`.
    Poprawka wpięta w wywołania da się pominąć przy dopisywaniu kolejnego
    endpointu — i dokładnie tak powstał poprzedni rozjazd (#960 naprawił jedną
    powierzchnię, druga została ze swoją kopią logiki aż do #983).
    """
    from app.services.structured_candidate_search import _skill_match

    sql = str(_skill_match("MSSQL").compile(compile_kwargs={"literal_binds": True}))
    for wariant in (
        "mssql",
        "ms sql",
        "sql server",
        "microsoft sql server",
        "microsoft sql",
    ):
        assert f'"{wariant}"' in sql, (
            f"predykat nie szuka wariantu {wariant!r} — rodzina nie jest rozwijana"
        )
    assert "strpos" in sql, "predykat przestał używać strpos (patrz #983)"


def test_predykat_bez_mapy_szuka_dokladnie_tego_co_wpisano() -> None:
    """Bez taksonomii (testy, narzędzia offline) zachowanie ma być nienaruszone."""
    from app.services.structured_candidate_search import _skill_match

    set_alias_map({})
    sql = str(_skill_match("Rust").compile(compile_kwargs={"literal_binds": True}))
    assert '"rust"' in sql
    assert sql.count("strpos") == 2, (
        "bez mapy predykat powinien mieć dokładnie dwa sprawdzenia "
        "(oba kodowania JSON jednej igły)"
    )


def test_podmiana_mapy_uniewaznia_indeks_odwrotny() -> None:
    """`set_alias_map` musi czyścić cache rodzin, inaczej zostaje stary świat."""
    assert "golang" in skill_name_variants(["Go"])
    set_alias_map({"python": "python"})
    assert skill_name_variants(["Go"]) == ["go"], (
        "indeks odwrotny nie został unieważniony — rodziny pochodzą ze starej mapy"
    )
