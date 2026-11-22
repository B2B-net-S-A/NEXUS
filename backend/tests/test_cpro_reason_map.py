"""Powód odrzucenia z treści maila CPro (B7, 19.11.2026) — bez bazy.

Od #3040 człowiek przy „Odrzuca klient” wybiera „Inne” w 5% odrzuceń, a automat
CPro wpisywał „Inne” w 100%. Teksty niżej to treści z produkcji bez imion
i nazwisk. Seed 0740 musi mieć lustro w ``entrypoint.sh``.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from app.services.cpro_reason_map import (
    CULTURE_FIT,
    NO_EXPERIENCE,
    TECH_REQUIREMENTS,
    client_text,
    reason_label_for,
    reason_name_for,
)
from app.services.cpro_rejection_reason_repair import summarize_for_log
from app.services.rejection_reason_labels import (
    CLIENT_CHOSE_OTHER,
    CLIENT_INTERVIEW_WEAK,
    CLIENT_NO_REASON,
    CLIENT_NOT_A_VERDICT,
    CLIENT_OTHER_VENDOR,
    WORK_MODE_MISMATCH,
    needs_description,
    rejection_reason_label,
)

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_MIGRATION_PATH = _BACKEND / "alembic" / "versions" / "0740_cpro_client_reasons.py"
_FRONT_MIRROR = (
    _BACKEND.parent / "frontend" / "src" / "lib" / "rejection-reasons.ts"
).read_text(encoding="utf-8")


def _migration():
    spec = importlib.util.spec_from_file_location("m0741", _MIGRATION_PATH)
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Duplikat albo tańsza oferta innego dostawcy, także gdy pada „another”.
        ("He was offered by another vendor with better price.", CLIENT_OTHER_VENDOR),
        ("rejected w other provider already", CLIENT_OTHER_VENDOR),
        ("Duplicated and more expensive offer", CLIENT_OTHER_VENDOR),
        (
            "duplicate application. Got the same cv from multiple vendors",
            CLIENT_OTHER_VENDOR,
        ),
        # Grzecznościowa formułka o innych kandydatach nie ocenia tej osoby.
        (
            "We have decided to proceed with another candidates whose qualifications "
            "and experience more closely align with the requirements of this engagement.",
            CLIENT_CHOSE_OTHER,
        ),
        ("other candidate was selected for the role", CLIENT_CHOSE_OTHER),
        (
            "Looking at other profiles even more precise for the task",
            CLIENT_CHOSE_OTHER,
        ),
        (
            "decision to hire another consultant before proceeding to interview",
            CLIENT_CHOSE_OTHER,
        ),
        ("Candidate is not selected for Interviews.", CLIENT_NO_REASON),
        (
            "After careful consideration, unfortunately, we have decided to decline this offer.",
            CLIENT_NO_REASON,
        ),
        (
            "requested location is Łódź. Candidate lives elsewhere, how can we come to "
            "the office 3 times during the week ?",
            WORK_MODE_MISMATCH,
        ),
        (
            "After a look and interviews we don't see that this is a match for the team.",
            CULTURE_FIT,
        ),
        ("Interview result was not positive", CLIENT_INTERVIEW_WEAK),
        (
            "Couldn't introduce himself very well. He couldn't clearly explain elements of DoD.",
            CLIENT_INTERVIEW_WEAK,
        ),
        (
            "Based on the interview we had, we concluded that the skillset and experience "
            "does not fully match the CV. We have therefore decided to move on with other "
            "candidates.",
            CLIENT_INTERVIEW_WEAK,
        ),
        ("Insufficient PM experience", NO_EXPERIENCE),
        ("No PM exp", NO_EXPERIENCE),
        ("PM profile not strong enough", NO_EXPERIENCE),
        ("Not enought relevant programme management experience", NO_EXPERIENCE),
        ("Not the exact skill set", TECH_REQUIREMENTS),
        ("too IT heavy profile", TECH_REQUIREMENTS),
        (
            "profile is too technical for this program, otherwise good profile",
            TECH_REQUIREMENTS,
        ),
        ("profile don't seem to match our need", TECH_REQUIREMENTS),
        (
            "competence does not match requirements, but a solid QA background.",
            TECH_REQUIREMENTS,
        ),
    ],
)
def test_client_text_maps_to_a_reason(text: str, expected: str) -> None:
    assert reason_name_for(text) == expected
    assert reason_name_for(f"Z CPro: {text}") == expected


@pytest.mark.parametrize(
    "text",
    [
        "Not available anymore!",
        "I just had a chat with him, he will stay in his current company for now",
        "Feedback from previous team is not good enough",
        # „Service Domain” to nie „domain knowledge”.
        "Currently employed by my Service Domain and I decided to not prolong the contract.",
    ],
)
def test_text_without_a_match_stays_other(text: str) -> None:
    assert reason_name_for(text) is None
    assert reason_label_for(text) == "Inne"


@pytest.mark.parametrize("empty", [None, "", "   ", "Z CPro", "Z CPro:   "])
def test_mail_without_text_means_client_gave_no_reason(empty) -> None:
    assert reason_name_for(empty) == CLIENT_NO_REASON


def test_client_text_strips_only_the_note_prefix() -> None:
    assert client_text("Z CPro:  No PM   exp ") == "No PM exp"
    assert client_text("Not exact profile") == "Not exact profile"


def test_banner_label_follows_the_reason_and_withdrawal() -> None:
    assert reason_label_for("Insufficient PM experience") == "Za mało doświadczenia"
    assert reason_label_for("Duplicated and more expensive offer") == (
        "Pracuje u klienta / zgłoszona przez inną firmę"
    )
    assert reason_label_for("Candidate withdrew from the process") == (
        "Kandydat się wycofał"
    )


def test_new_reasons_have_labels_and_need_no_description() -> None:
    assert (
        rejection_reason_label(CLIENT_OTHER_VENDOR)
        == "Pracuje u klienta / zgłoszona przez inną firmę"
    )
    assert (
        rejection_reason_label(CLIENT_INTERVIEW_WEAK)
        == "Rozmowa u klienta wypadła słabo"
    )
    assert not needs_description(CLIENT_OTHER_VENDOR)
    assert not needs_description(CLIENT_INTERVIEW_WEAK)


def test_other_vendor_is_not_a_verdict_but_weak_interview_is() -> None:
    assert CLIENT_OTHER_VENDOR in CLIENT_NOT_A_VERDICT
    assert CLIENT_INTERVIEW_WEAK not in CLIENT_NOT_A_VERDICT


def test_entrypoint_mirrors_the_migration_seed_verbatim() -> None:
    seed = " ".join(_migration().SEED_CPRO_CLIENT_REASONS.split())
    assert seed in _shape(_data_section())


def test_seed_is_one_shot_and_weak_interview_disqualifies() -> None:
    seed = _migration().SEED_CPRO_CLIENT_REASONS
    assert "ON CONFLICT (key) DO NOTHING RETURNING key" in seed
    assert "WHERE EXISTS (SELECT 1 FROM marker)" in seed
    assert "ON CONFLICT (template_id, name, category) DO NOTHING" in seed
    assert "'rejected'::terminaltype" in seed
    # Słaba rozmowa uruchamia weto hiring managera, inny dostawca nie.
    assert "(1, 'client_other_vendor', FALSE)" in seed
    assert "(2, 'client_interview_weak', TRUE)" in seed
    assert "UPDATE " not in seed.upper()


def test_front_shows_weak_interview_only_when_the_client_ends() -> None:
    # Od 19.11.2026 (jeden słownik) kto wybiera powód, mówi `close_reasons`;
    # inny dostawca to „Pracuje u klienta / zgłoszona przez inną firmę”.
    from app.services import close_reasons as cr

    weak = next(r for r in cr.CLOSE_REASONS if r.rejected == CLIENT_INTERVIEW_WEAK)
    vendor = next(r for r in cr.CLOSE_REASONS if r.rejected == CLIENT_OTHER_VENDOR)
    assert weak.who == {cr.CLIENT}
    assert vendor.who == {cr.RECRUITER, cr.CLIENT}
    assert f'"{CLIENT_OTHER_VENDOR}"' in _FRONT_MIRROR
    assert f'"{CLIENT_INTERVIEW_WEAK}"' in _FRONT_MIRROR


def test_repair_log_has_only_counts() -> None:
    assert summarize_for_log(None) == "already applied"
    line = summarize_for_log(
        {
            "scanned": 3,
            "moved": {CLIENT_CHOSE_OTHER: 2},
            "kept_other": {"no_match": 1},
            "rows": [[11, 6, 1019], [12, 6, 1019]],
        }
    )
    assert line == "moved 2/3 (client_chose_other=2); kept as other: no_match=1"
