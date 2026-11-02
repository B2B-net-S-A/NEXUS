"""Staging ma punktować jak produkcja: flagi w compose i strażnik przy odświeżaniu.

02.11.2026 raport o wysłanych i pomiar #2882 policzono bez flag z produkcji.
Wyniki różniły się do 22 pkt, a na ekranach niczego nie było widać.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.core.config import Settings
from scripts.staging_ranking_parity import MAX_STALE, parity_warnings

ROOT = Path(__file__).resolve().parents[2]
RANKING_FLAGS = {
    "CHAMPION_MATCH_SIGNALS_ENABLED": "true",
    "CHAMPION_SENIORITY_PENALTY_ENABLED": "true",
    "SKILL_ALIAS_EXTENDED_ENABLED": "true",
    "HYBRID_POOL_ENABLED": "true",
    "KNOWN_PEOPLE_BOOST_ENABLED": "true",
    "KEYWORD_SEARCH_FOLDED_FTS": "true",
    "MATCH_POOL_SIZE": "2000",
}


def test_compose_sets_ranking_flags_with_a_default():
    compose = yaml.safe_load((ROOT / "docker-compose.staging.yml").read_text())
    environment = compose["services"]["backend"]["environment"]
    for name, value in RANKING_FLAGS.items():
        assert name in Settings.model_fields, f"{name} nie ma już w ustawieniach"
        # Domyślna wartość, bo `.env.staging.local` leży poza repo i bywa stary.
        assert environment[name] == f"${{{name}:-{value}}}"


def test_env_example_lists_the_same_values():
    example = (ROOT / "scripts/staging/env.staging.example").read_text()
    for name, value in RANKING_FLAGS.items():
        assert re.search(rf"^{name}={value}$", example, re.M), name


def test_refresh_warns_also_when_code_is_already_current():
    script = (ROOT / "scripts/staging/refresh_code.sh").read_text()
    before_early_exit = script.split('"Staging już jest na $SHA."')[1].split("fi", 1)[0]
    assert "check_ranking_parity" in before_early_exit
    assert script.count("check_ranking_parity") == 3  # definicja i dwa wywołania


def test_no_warning_when_stamp_matches_and_index_is_fresh():
    assert parity_warnings("a", "a", MAX_STALE) == []


def test_other_stamp_warns():
    [warning] = parity_warnings("bez-flag", "produkcja", 0)
    assert "bez-flag" in warning and "produkcja" in warning


def test_copy_without_review_warns_instead_of_passing():
    assert len(parity_warnings("a", None, 0)) == 1


def test_stale_index_warns_with_the_command_that_fixes_it():
    [warning] = parity_warnings("a", "a", MAX_STALE + 1)
    assert "reembed_collections" in warning and "--resume" in warning


def test_both_problems_are_reported_together():
    assert len(parity_warnings("a", "b", MAX_STALE + 1)) == 2
