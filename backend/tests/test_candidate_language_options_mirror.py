"""Lista języków okna „Języki kandydata” — jedna lista w dwóch lustrach.

Front (`frontend/src/lib/candidate-languages.ts`, `LANGUAGE_OPTIONS`) pokazuje
~30 języków z polskimi nazwami i kodami ISO 639-1. Backend
(`candidate_language_writer._LANGUAGE_CODES` → `KNOWN_LANGUAGE_CODES`) musi
znać każdy z tych kodów: `PUT /languages` odrzuca kod spoza listy bez
oznaczenia „Inny…”, więc brak kodu po stronie serwera zamieniłby wybór
z listy w 422. Polska nazwa z listy musi też prowadzić do tego samego kodu,
bo importy (CV, Traffit) zapisują język po nazwie.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.candidate_profile_facts import CandidateLanguageWrite
from app.services import candidate_profile_facts as facts
from app.services.candidate_language_writer import (
    KNOWN_LANGUAGE_CODES,
    _LANGUAGE_CODES,
)

_FRONTEND_LIST = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "candidate-languages.ts"
)
_ENTRY_RE = re.compile(r'\{\s*code:\s*"([a-z]{2,3})",\s*label:\s*"([^"]+)"\s*\}')


def _frontend_options() -> list[tuple[str, str]]:
    source = _FRONTEND_LIST.read_text(encoding="utf-8")
    block = source.split("export const LANGUAGE_OPTIONS", 1)[1].split("];", 1)[0]
    return _ENTRY_RE.findall(block)


def test_frontend_list_is_the_full_one() -> None:
    options = _frontend_options()
    assert len(options) >= 30, "lista języków okna ma mieć ok. 30 pozycji"
    codes = [code for code, _label in options]
    assert len(codes) == len(set(codes)), "kod języka powtórzony na liście"


def test_backend_knows_every_frontend_language() -> None:
    for code, label in _frontend_options():
        assert code in KNOWN_LANGUAGE_CODES, f"backend nie zna kodu {code!r}"
        assert _LANGUAGE_CODES.get(label.casefold()) == code, (
            f"polska nazwa {label!r} nie prowadzi do kodu {code!r}"
        )


def _fake_db(existing_rows: list[object]) -> MagicMock:
    db = MagicMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(languages_version=1))
    results = iter([existing_rows, []])
    db.scalars = AsyncMock(
        side_effect=lambda *_a, **_k: SimpleNamespace(all=lambda: next(results))
    )
    db.flush = AsyncMock()
    return db


def _language(code: str, name: str, *, other: bool = False) -> CandidateLanguageWrite:
    return CandidateLanguageWrite(language_code=code, language_name=name, other=other)


@pytest.mark.asyncio
async def test_unknown_code_without_other_is_rejected() -> None:
    with pytest.raises(facts.UnknownLanguageCodeError) as exc:
        await facts.replace_candidate_languages(
            _fake_db([]),
            candidate_id=1,
            languages=[_language("klingonski", "klingoński")],
            expected_version=1,
            actor_id=1,
        )
    assert "klingoński" in str(exc.value)


@pytest.mark.asyncio
async def test_other_flag_and_already_stored_code_are_accepted() -> None:
    stored = SimpleNamespace(
        language_code="x-lodz",
        language_name="łódzki",
        cefr_level=None,
        is_native=False,
        is_level_unknown=True,
        deleted_at=None,
        provenance="cv",
        manual_lock=False,
        source_ref=None,
        updated_by=None,
        version=1,
    )
    await facts.replace_candidate_languages(
        _fake_db([stored]),
        candidate_id=1,
        languages=[
            _language("klingonski", "klingoński", other=True),
            _language("x-lodz", "łódzki"),
            _language("bg", "bułgarski"),
        ],
        expected_version=1,
        actor_id=1,
    )
