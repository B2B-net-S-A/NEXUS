"""Runda 7 (R7-X3-3): downgrade 0387 i 0386 zakłada funkcję WŁAŚCIWEJ wersji.

``FOLD_FUNCTION_DDL`` w kodzie jest w wersji 3. Downgrade 0386 podmieniał
w nim fragment wersji 2, którego już nie ma — ``alembic downgrade 0385``
zakładał więc z powrotem funkcję v3 ze znacznikiem v3, a pętla uzupełniania
uznałaby ją za bieżącą.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.services import keyword_corpus as kc

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _downgrade_sql(filename: str, monkeypatch) -> str:
    spec = importlib.util.spec_from_file_location(filename, _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()
    assert len(executed) == 1
    return executed[0]


@pytest.mark.parametrize(
    ("filename", "version", "translate"),
    [
        ("0387_keyword_fold_combining.py", 2, "'/\\-', '   '"),
        ("0386_keyword_fold_hyphen.py", 1, "'/\\', '  '"),
    ],
)
def test_downgrade_installs_the_previous_version(
    filename, version, translate, monkeypatch
):
    sql = _downgrade_sql(filename, monkeypatch)
    assert kc.parse_fold_version(sql) == version
    assert translate in sql
    assert "normalize(" not in sql
    assert "<>" not in sql
    assert sql != kc.FOLD_FUNCTION_DDL
