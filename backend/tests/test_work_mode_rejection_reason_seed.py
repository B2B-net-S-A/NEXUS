"""Migracja 0442 (powód „Nie akceptuje trybu pracy”) i jej lustro w ``entrypoint.sh``.

Prod alembic bywa osierocony — ``_DATA_STATEMENTS`` JEST wdrożeniem, więc
seed musi tam być, musi być jednorazowy (marker w tym samym statemencie,
inaczej każdy start przywraca powód skasowany przez admina) i nie może się
rozjechać z migracją. Źródło czytane jako tekst, bez wykonania heredocu.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.services.rejection_reason_labels import (
    REJECTION_REASON_LABELS,
    WORK_MODE_MISMATCH,
    rejection_reason_label,
)

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_MIGRATION_PATH = (
    _BACKEND / "alembic" / "versions" / "0442_work_mode_rejection_reason.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("m0442", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _data_section() -> str:
    start = _ENTRYPOINT.index("\n_DATA_STATEMENTS = [")
    end = _ENTRYPOINT.index("\n]\n", start)
    return _ENTRYPOINT[start:end]


def _shape(text: str) -> str:
    # Sklejenie literałów Pythona ("a " "b") i znormalizowanie białych znaków.
    glued = re.sub(r"[\"']\s*\n\s*[\"']", "", text)
    return " ".join(glued.replace('\\"', '"').split())


def test_entrypoint_mirrors_the_migration_seed_verbatim():
    seed = " ".join(_migration().SEED_WORK_MODE_REASON.split())
    assert seed in _shape(_data_section())


def test_seed_is_one_shot_and_covers_both_categories():
    seed = _migration().SEED_WORK_MODE_REASON
    assert "ON CONFLICT (key) DO NOTHING RETURNING key" in seed
    assert "WHERE EXISTS (SELECT 1 FROM marker)" in seed
    assert "ON CONFLICT (template_id, name, category) DO NOTHING" in seed
    assert "('rejected'), ('withdrawn')" in seed
    assert f"'{WORK_MODE_MISMATCH}'" in seed
    # Powód sytuacyjny — nie blokuje ponownych zgłoszeń do hiring managera.
    assert "TRUE, FALSE, 'manual'" in seed


def test_reason_has_a_polish_label():
    assert WORK_MODE_MISMATCH in REJECTION_REASON_LABELS
    assert (
        rejection_reason_label(WORK_MODE_MISMATCH)
        == "Nie akceptuje trybu pracy (biuro / hybryda)"
    )
