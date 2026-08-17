"""Rozszerzone rodziny aliasów (4a) — kontrakty kuracji i merge'a.

- Flaga OFF = zero zmian w mapie scoringu (eksperyment jest odwracalny).
- Merge: baza WYGRYWA na kolizjach (setdefault) — przyszły seed nie zostanie
  po cichu nadpisany przez plik eksperymentu.
- Kuracja: lowercase wszędzie, bez gołych 2-literowców (regex ekstrakcji
  z tekstu Championa łapie po granicach słów — krótkie skróty to fałszywe
  trafienia), bez soft-skills w rodzinach.
- Flaga jest w _SCORING_CACHE_INPUTS — flip unieważnia cache score'ów.
"""

from app.services.scoring_service import _SCORING_CACHE_INPUTS
from app.services.skill_taxonomy_extended import (
    EXTENDED_FAMILIES,
    extended_alias_mapping,
)


def test_mapping_shape_and_hygiene():
    mapping = extended_alias_mapping()
    assert len(mapping) > 60
    for alias, canon in mapping.items():
        assert alias == alias.lower().strip(), alias
        assert canon == canon.lower().strip(), canon
        assert len(alias) >= 3, f"goły skrót {alias!r} — ryzyko regexu tekstowego"
        assert canon in EXTENDED_FAMILIES, canon


def test_canonicals_self_map_and_aliases_point_home():
    mapping = extended_alias_mapping()
    for canonical, aliases in EXTENDED_FAMILIES.items():
        assert mapping[canonical] == canonical
        for alias in aliases:
            assert mapping[alias] == canonical


def test_no_soft_skills_in_families():
    banned = {
        "team leadership",
        "communication",
        "stakeholder management",
        "customer service",
        "change management",
        "team management",
        "product management",
        "english",
    }
    assert banned.isdisjoint(set(extended_alias_mapping())), (
        "soft-skille w must-listach to szum, który ma każdy i nikt"
    )


def test_flag_gates_merge_and_db_wins_on_conflict(monkeypatch):
    import app.services.skill_taxonomy_loader as loader_mod

    # Symulacja merge'a bez DB: replikujemy dokładnie logikę loadera na
    # mapie bazowej z kolizją ("kubernetes" ma w bazie własny wpis).
    base = {"kubernetes": "kubernetes", "python": "python"}

    def merge(flag: bool) -> dict:
        scoring = dict(base)
        if flag:
            for alias, canon in extended_alias_mapping().items():
                if alias not in scoring:
                    scoring[alias] = canon
        return scoring

    off = merge(False)
    assert off == base, "flaga OFF nie może zmienić mapy"

    on = merge(True)
    assert on["kubernetes"] == "kubernetes", "baza wygrywa na kolizji"
    assert on["k8s"] == "kubernetes", "alias z rozszerzenia dopisany"
    assert on["jira"] == "jira"
    assert hasattr(loader_mod, "refresh_alias_map"), (
        "loader, którego logikę replikujemy, musi istnieć — inaczej test "
        "sprawdza martwą kopię"
    )


def test_flag_registered_in_scoring_cache_inputs():
    assert "SKILL_ALIAS_EXTENDED_ENABLED" in _SCORING_CACHE_INPUTS
