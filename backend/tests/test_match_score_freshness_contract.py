"""Kontrakt świeżości cache dopasowań — jedna definicja, zero kopii.

Znalezisko #32 (P0): ``/jobs/{id}/pipeline-scores`` miał własny warunek „świeży"
bez predykatu ``scoring_algorithm_version``. Po bumpie wag wiersz sprzed zmiany
przechodził jako aktualny, więc nie trafiał do zbioru „do przeliczenia" i nie
dostawał podobieństwa semantycznego — a potem był liczony z ``None`` (0 z 60
punktów) i zapisywany jako świeży pod NOWĄ wersją. Zaniżony pierścień na kanbanie
zostawał na zawsze.

Trzecia kopia tej samej reguły siedziała w ``api/search.py`` (endpoint
tylko-do-odczytu: nie truł cache'a, ale pokazywał wynik poprzedniego algorytmu
obok bieżącego).

Obie kopie były wierne — powielały to, co obiecywał docstring modułu
(„A row is considered fresh iff stale == False"), nieaktualizowany po dołożeniu
predykatu wersji. Dlatego test pilnuje KODU, nie dokumentacji.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.models.match_score import CandidateJobMatchScore
from app.services.match_score_cache import fresh_score_conditions
from app.services.scoring_service import scoring_algorithm_version

APP = Path(__file__).resolve().parents[1] / "app"

# Jedyny moduł, któremu wolno wymienić `stale` z ręki — bo definiuje regułę.
_DEFINITION_SITE = "services/match_score_cache.py"


def _compiles(cond) -> str:
    return str(cond.compile(compile_kwargs={"literal_binds": True}))


def test_conditions_carry_both_halves_of_freshness():
    conds = fresh_score_conditions(job_id=42, profile_id=1, candidate_ids=[7])
    sql = " ".join(_compiles(c) for c in conds)
    assert "stale is false" in sql.lower()
    assert "scoring_algorithm_version" in sql
    assert scoring_algorithm_version() in sql
    assert "job_id" in sql and "profile_id" in sql


def test_candidate_ids_is_optional():
    """Unieważnianie całej oferty nie zna listy kandydatów."""
    conds = fresh_score_conditions(job_id=42, profile_id=1)
    sql = " ".join(_compiles(c) for c in conds)
    assert "candidate_id in" not in sql.lower()
    assert "scoring_algorithm_version" in sql


def test_no_hand_written_freshness_predicate_anywhere_in_app():
    """Czwarta kopia reguły ma paść tutaj, a nie na produkcji.

    Skutek pominięcia predykatu wersji jest CICHY — nie wyjątek, tylko inna
    liczba — więc nic poza tym testem go nie złapie.
    """
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel == _DEFINITION_SITE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "stale"
                and isinstance(node.value, ast.Name)
                and node.value.id == CandidateJobMatchScore.__name__
            ):
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "warunek świeżości cache napisany z ręki zamiast fresh_score_conditions(): "
        + ", ".join(offenders)
    )
