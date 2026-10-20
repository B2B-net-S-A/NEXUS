"""Powód „Już po rozmowie u tego hiring managera” (0484) i opis przy „Inne”.

20.10.2026: Delivery Lead odrzucał osobę, bo była już na rozmowie u managera
tej rekrutacji, i nie miał gdzie tego napisać — słownik tego nie znał, a przy
„Inne” w historii zostawało samo słowo. Seed musi być w ``entrypoint.sh``
(prod alembic bywa osierocony), jednorazowy i zgodny z migracją. Źródło czytane
jako tekst, bez wykonania heredocu.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from app.services.rejection_reason_labels import (
    HM_ALREADY_INTERVIEWED,
    WORK_MODE_MISMATCH,
    needs_description,
    rejection_reason_label,
)

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_MIGRATION_PATH = _BACKEND / "alembic" / "versions" / "0484_hm_interviewed_reason.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0484", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _data_section() -> str:
    start = _ENTRYPOINT.index("\n_DATA_STATEMENTS = [")
    end = _ENTRYPOINT.index("\n]\n", start)
    return _ENTRYPOINT[start:end]


def _shape(text: str) -> str:
    glued = re.sub(r"[\"']\s*\n\s*[\"']", "", text)
    return " ".join(glued.replace('\\"', '"').split())


def test_entrypoint_mirrors_the_migration_seed_verbatim():
    seed = " ".join(_migration().SEED_HM_INTERVIEWED_REASON.split())
    assert seed in _shape(_data_section())


def test_seed_is_one_shot_rejected_only_and_not_a_verdict():
    seed = _migration().SEED_HM_INTERVIEWED_REASON
    assert "ON CONFLICT (key) DO NOTHING RETURNING key" in seed
    assert "WHERE EXISTS (SELECT 1 FROM marker)" in seed
    assert "ON CONFLICT (template_id, name, category) DO NOTHING" in seed
    assert f"'{HM_ALREADY_INTERVIEWED}', 'rejected'::terminaltype" in seed
    assert "withdrawn" not in seed
    # Manager zna osobę — to nie jest jego odmowa, więc bez weta na przyszłość.
    assert "TRUE, FALSE, 'manual'" in seed


def test_reason_has_a_polish_label():
    assert (
        rejection_reason_label(HM_ALREADY_INTERVIEWED)
        == "Już po rozmowie u tego hiring managera"
    )


@pytest.mark.parametrize(
    "name",
    ["Inne (rejected)", "Inne (withdrawn)", "Inne", " Inne ", HM_ALREADY_INTERVIEWED],
)
def test_reasons_that_say_nothing_alone_need_a_description(name: str):
    assert needs_description(name) is True


@pytest.mark.parametrize(
    "name",
    [None, WORK_MODE_MISMATCH, "salary_mismatch", "Brak kwalifikacji", "Inne powody"],
)
def test_other_reasons_do_not_need_a_description(name):
    assert needs_description(name) is False
