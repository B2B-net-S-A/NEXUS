"""Lustro DDL dodatkowych numerów nabywcy (0779) w ``entrypoint.sh``.

Alembic na produkcji bywa osierocony, więc ``entrypoint.sh`` jest wdrożeniem:
każde polecenie z ``buyer_numbers_schema.DDL`` musi tam być dosłownie.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services.client_invoicing.buyer_numbers_schema import DDL

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_entrypoint_mirrors_every_statement() -> None:
    raw = ENTRYPOINT.read_text(encoding="utf-8")
    # Literały Pythona w entrypoincie: sklejamy sąsiednie "…" "…" w jeden tekst.
    joined = _flat(re.sub(r'"\s*\n\s*"', "", raw))
    for statement in DDL:
        assert _flat(statement) in joined, statement[:60]


def test_migration_runs_the_shared_ddl() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/0779_client_buyer_numbers.py"
    ).read_text(encoding="utf-8")
    assert (
        "from app.services.client_invoicing.buyer_numbers_schema import DDL"
        in migration
    )
    assert 'down_revision = "0778_b2b_document_preliminary_jdg"' in migration
