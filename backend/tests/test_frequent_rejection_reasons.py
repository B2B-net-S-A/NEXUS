"""Sześć powodów odrzucenia zamiast ręcznego opisu pod „Inne” (0646, 04.11.2026).

Seed musi być w ``entrypoint.sh`` (prod alembic bywa osierocony), jednorazowy
i zgodny z migracją. Źródło czytane jako tekst, bez wykonania heredocu.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from app.services.insights_stage_breakdown import summarize_closed_by
from app.services.rejection_reason_labels import (
    CLIENT_CHOSE_OTHER,
    CLIENT_CONFLICT,
    CLIENT_NO_REASON,
    CONTRACT_FORM,
    NO_CONTACT,
    NOT_LOOKING_FOR_WORK,
    needs_description,
    rejection_reason_label,
)

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_MIGRATION_PATH = (
    _BACKEND / "alembic" / "versions" / "0646_frequent_rejection_reasons.py"
)
_FRONT_MIRROR = (
    _BACKEND.parent / "frontend" / "src" / "lib" / "rejection-reasons.ts"
).read_text(encoding="utf-8")

NEW_REASONS = {
    NOT_LOOKING_FOR_WORK: "Nie szuka pracy lub niezainteresowany",
    CLIENT_CONFLICT: "Pracuje u klienta lub nie chce do klienta",
    CONTRACT_FORM: "Forma umowy (UoP, B2B, etat)",
    NO_CONTACT: "Brak kontaktu",
    CLIENT_NO_REASON: "Klient nie podał powodu",
    CLIENT_CHOSE_OTHER: "Klient wybrał kogoś innego",
}


def _migration():
    spec = importlib.util.spec_from_file_location("m0646", _MIGRATION_PATH)
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
    seed = " ".join(_migration().SEED_FREQUENT_REJECTION_REASONS.split())
    assert seed in _shape(_data_section())


def test_seed_is_one_shot_rejected_only_and_not_a_verdict():
    seed = _migration().SEED_FREQUENT_REJECTION_REASONS
    assert "ON CONFLICT (key) DO NOTHING RETURNING key" in seed
    assert "WHERE EXISTS (SELECT 1 FROM marker)" in seed
    assert "ON CONFLICT (template_id, name, category) DO NOTHING" in seed
    assert "'rejected'::terminaltype" in seed
    assert "withdrawn" not in seed
    # Powód opisuje sytuację, nie osobę, więc bez weta na przyszłość.
    assert "TRUE, FALSE, 'manual'" in seed
    # Stare wpisy zostają: migracja niczego nie przepina.
    assert "UPDATE " not in seed.upper()


def test_seed_downgrade_and_labels_name_the_same_six_reasons():
    module = _migration()
    assert set(module.REASON_KEYS) == set(NEW_REASONS)
    for key in NEW_REASONS:
        assert f"'{key}'" in module.SEED_FREQUENT_REJECTION_REASONS
        assert f"'{key}'" in module.REFUSE_WITH_LIVE_ROWS


def test_downgrade_refuses_when_history_points_at_the_reasons():
    guard = _migration().REFUSE_WITH_LIVE_ROWS
    assert "candidate_stages" in guard
    assert "interview_feedback" in guard
    assert "RAISE EXCEPTION" in guard


@pytest.mark.parametrize(("key", "label"), NEW_REASONS.items())
def test_each_reason_has_a_polish_label(key: str, label: str):
    assert rejection_reason_label(key) == label


@pytest.mark.parametrize("key", NEW_REASONS)
def test_the_choice_replaces_writing_so_no_description_is_needed(key: str):
    assert needs_description(key) is False


def test_other_still_needs_a_description():
    assert needs_description("Inne (rejected)") is True


@pytest.mark.parametrize("key", NEW_REASONS)
def test_frontend_mirror_knows_each_key(key: str):
    assert f'"{key}"' in _FRONT_MIRROR


def test_insights_show_the_label_not_the_key():
    groups = [
        {"who": "client", "count": 5, "reason_name": CLIENT_NO_REASON},
        {"who": "client", "count": 3, "reason_name": CLIENT_CHOSE_OTHER},
    ]
    summary = summarize_closed_by(groups)
    client = next(row for row in summary if row["key"] == "client")
    assert [(r["label"], r["count"]) for r in client["top_reasons"]] == [
        ("Klient nie podał powodu", 5),
        ("Klient wybrał kogoś innego", 3),
    ]


def test_new_reason_outside_the_top_three_stays_named_in_the_other_row():
    groups = [
        {"who": "recruiter", "count": 9, "reason_name": "Brak doświadczenia"},
        {
            "who": "recruiter",
            "count": 8,
            "reason_name": "Za wysokie oczekiwania finansowe",
        },
        {
            "who": "recruiter",
            "count": 7,
            "reason_name": "Nie spełnia wymagań technicznych",
        },
        {"who": "recruiter", "count": 2, "reason_name": NO_CONTACT},
    ]
    recruiter = next(
        row for row in summarize_closed_by(groups) if row["key"] == "recruiter"
    )
    other = next(r for r in recruiter["top_reasons"] if r["kind"] == "other")
    assert other["details"] == ["Brak kontaktu (2)"]
