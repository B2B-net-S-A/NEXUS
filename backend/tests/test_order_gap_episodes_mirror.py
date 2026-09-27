"""Lustro DDL 0391 w ``entrypoint.sh`` (runda 10, R10-N4-1/3).

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem. Bez kolumny
``episode`` pada każdy odczyt braku przez ORM (pętla ``order_gaps``, widok
Finansów), a bez nowego indeksu i zdjętego starego więzu drugi brak tego
samego zamówienia dalej nie powstaje.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _migration():
    path = BACKEND / "alembic" / "versions" / "0391_fin_order_gap_episodes.py"
    spec = importlib.util.spec_from_file_location("m0391", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_entrypoint_mirrors_every_0391_statement_in_order() -> None:
    entrypoint = _flat((BACKEND / "entrypoint.sh").read_text())
    positions = []
    for statement in _migration().DDL_STATEMENTS:
        flat = _flat(statement)
        assert flat in entrypoint, statement[:80]
        positions.append(entrypoint.index(flat))
    # Indeks przed zdjęciem więzu — tabela nigdy nie jest bez unikalności.
    assert positions == sorted(positions)


def test_model_declares_the_pair_unique_and_the_episode_column() -> None:
    from app.models.order_gap import OrderGap

    table = OrderGap.__table__
    assert "episode" in table.columns
    unique = {
        index.name: [column.name for column in index.columns]
        for index in table.indexes
        if index.unique
    }
    assert unique.get("ux_order_gaps_order_ended") == ["order_id", "ended_on"]
    assert not any(
        getattr(constraint, "name", None) == "uq_order_gaps_order_id"
        for constraint in table.constraints
    )


def test_downgrade_refuses_when_an_order_has_several_gaps() -> None:
    assert "HAVING count(*) > 1" in _migration().REFUSE_WITH_DUPLICATES
