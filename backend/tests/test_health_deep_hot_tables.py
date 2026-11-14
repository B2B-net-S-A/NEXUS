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

import ast
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


# Audyt 22.10.2026 (F79, decyzja Artura): tabele z 0482, 0499, 0506 i 0509
# weszły bez sondy. Siatka entrypointu bywa jedynym wdrożeniem schematu
# (alembic osierocony), więc nieudany CREATE TABLE dawał zielony deploy
# i 500 UndefinedTable przy pierwszym „Pomiń Prep 2”, przedwstępnej,
# podpisie w NEXUSIE albo ruchu karty na tablicy opieki.
@pytest.mark.parametrize(
    "table",
    [
        "prep2_skips",
        "b2b_signing_requests",
        "pre_contract_requests",
        "pre_contract_watchers",
        "pre_contract_events",
        "care_board_states",
    ],
)
def test_tables_from_october_are_probed(table: str) -> None:
    block = _core_checks_block()
    assert re.search(rf'\("{table}",\s*\w+\)', block), (
        f"`{table}` musi być w `core_checks` (audyt 22.10, F79)"
    )


def test_october_probe_models_are_imported() -> None:
    src = MAIN.read_text(encoding="utf-8")
    for symbol in (
        "Prep2Skip",
        "from app.models.b2b_signing_request import B2BSigningRequest",
        "PreContractRequest",
        "PreContractWatcher",
        "PreContractEvent",
        "from app.services.care.board_state import CARE_BOARD_STATES",
    ):
        assert symbol in src, symbol


# Księga NEXUSA (plan K1–K9, 13–14.11.2026): tabele z 0700–0702 (K1–K3)
# i 0705 (K4a) weszły bez sondy, choć wymaga jej reguła z 22.10 (F79);
# K6 (0703) dopisał swoje od razu. Lista przypina sondy, żeby nie zniknęły
# bez echa, a skaner modeli niżej łapie tabele kolejnych etapów.
LEDGER_TABLES = (
    "ledger_years",
    "ledger_periods",
    "ledger_documents",
    "ledger_lines",
    "ledger_events",
    "ledger_recurring",
    "ledger_prepayments",
    "ledger_exports",
    "ledger_export_documents",
    "ledger_assets",
    "ledger_asset_operations",
    "ledger_bank_statements",
    "ledger_bank_lines",
)


@pytest.mark.parametrize("table", LEDGER_TABLES)
def test_ledger_tables_are_probed(table: str) -> None:
    block = _core_checks_block()
    assert re.search(rf'\("{table}",\s*\w+\)', block), (
        f"`{table}` musi być w `core_checks` (reguła z 22.10, F79)"
    )


def test_every_ledger_model_table_is_probed() -> None:
    """Każda tabela `ledger_*` z modeli ma sondę od pierwszego PR-a etapu."""
    tables = {
        match.group(1)
        for path in (BACKEND / "app/models").rglob("*.py")
        for match in re.finditer(
            r'__tablename__ = "(ledger_\w+)"', path.read_text(encoding="utf-8")
        )
    }
    assert set(LEDGER_TABLES) <= tables, "skaner nie widzi modeli księgi"
    block = _core_checks_block()
    missing = sorted(t for t in tables if not re.search(rf'\("{t}",\s*\w+\)', block))
    assert not missing, (
        f"tabele księgi bez sondy w `core_checks` /api/health/deep: {missing} — "
        "dopisz je w app/main.py i do LEDGER_TABLES"
    )


def test_ledger_probe_models_are_imported() -> None:
    """Brakujący import wywaliłby endpoint 500 — czyli bramkę schematu."""
    imported = {
        alias.asname or alias.name
        for node in ast.walk(ast.parse(MAIN.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("app.models.ledger")
        for alias in node.names
    }
    probed = re.findall(r'\("ledger_\w+",\s*(\w+)\)', _core_checks_block())
    missing = sorted(model for model in probed if model not in imported)
    assert not missing, missing
