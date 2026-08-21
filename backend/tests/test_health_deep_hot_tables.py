"""`/api/health/deep` musi sondować tabele, na których rozjazd boli najbardziej.

Ten endpoint jest jedyną bramką schematu po deployu: `.github/workflows/deploy.yml`
wywala deploy, gdy któryś check jest unhealthy. Bramka działała — tylko nie
obejmowała `candidate_stages` (pipeline: każdy ruch między etapami, każde
renderowanie Kanbana, każdy lejek KPI), `notes`, `candidate_documents`, `users`
ani `notifications`. Sonda `candidates` ich NIE pokrywa: `select(Candidate)`
rozwiązuje wyłącznie kolumny `candidates`, a relacje są leniwe — to jest ten sam
mechanizm, którym przeszedł incydent 0154 (`contract_candidate_rates.effective_to`
bez lustra w entrypoincie → całe `/api/contracts` 503 przez dobę za zielonym
deployem).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MAIN = BACKEND / "app/main.py"


def _core_checks_block() -> str:
    src = MAIN.read_text(encoding="utf-8")
    at = src.index("    core_checks = [")
    end = src.index("\n    ]", at)
    return src[at:end]


@pytest.mark.parametrize(
    "table",
    [
        "candidate_stages",
        "notes",
        "candidate_documents",
        "users",
        "notifications",
    ],
)
def test_hot_table_is_probed(table: str) -> None:
    block = _core_checks_block()
    assert re.search(rf'\("{table}",\s*\w+\)', block), (
        f"`{table}` musi być w `core_checks` — bez sondy rozjechana kolumna "
        "wjeżdża na produkcję za zielonym deployem i wychodzi dopiero jako "
        "500 bez CORS u pierwszego rekrutera, który otworzy ten moduł"
    )


def test_probed_models_are_actually_imported() -> None:
    """Brakujący import wywaliłby endpoint 500 — czyli bramkę schematu."""
    src = MAIN.read_text(encoding="utf-8")
    for symbol in (
        "from app.models.recruitment_pipeline import CandidateStage",
        "from app.models.note import Note",
        "from app.models.candidate_document import CandidateDocument",
        "from app.models.user import User",
        "from app.models.notification import Notification",
    ):
        assert symbol in src, symbol
