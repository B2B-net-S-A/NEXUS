"""`@wszyscy` w czacie i notatkach rekrutacji (13.11.2026).

Znacznik oznacza osoby przypisane do rekrutacji (`list_job_assigned_ids`),
nie cały „zespół” z nagłówka czatu (admini spoza zespołu, uczestnicy
kategorii, poprzedni rekruterzy). Testy bez bazy — ścieżka czatu z bazą
jest w `test_job_chat.py`.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import mention_parser
from app.services.mention_parser import (
    has_everyone_mention,
    has_mention,
    parse_mentions,
    parse_mentions_global,
)


@pytest.mark.parametrize(
    "content",
    [
        "@wszyscy proszę o statusy",
        "Hej @Wszyscy, jutro sync",
        "(@WSZYSCY)",
        "koniec zdania @wszyscy",
        "@wszyscy\nnowa linia",
    ],
)
def test_everyone_token_is_recognised(content: str) -> None:
    assert has_everyone_mention(content)
    assert has_mention(content)


@pytest.mark.parametrize(
    "content",
    [
        "napisz na biuro@wszyscy.pl",
        "@wszyscy@firma.pl to adres",
        "@wszyscyX",
        "wszyscy bez małpy",
        "",
    ],
)
def test_lookalikes_are_not_everyone(content: str) -> None:
    assert not has_everyone_mention(content)


async def test_everyone_expands_to_assigned_people(monkeypatch) -> None:
    assigned = AsyncMock(return_value=[3, 5, 8])
    monkeypatch.setattr(mention_parser, "_assigned_ids", assigned)

    async def allowed(db, *, section=None, user_ids=None):
        # 8 nie ma odczytu rekrutacji — reguła wzmianek dalej obowiązuje.
        return [SimpleNamespace(id=uid) for uid in sorted(user_ids or ()) if uid != 8]

    monkeypatch.setattr(mention_parser, "mentionable_users", allowed)

    assert await parse_mentions(MagicMock(), "@wszyscy proszę o statusy", 42) == [3, 5]
    assigned.assert_awaited_once()
    assert assigned.await_args.args[1] == 42


async def test_without_token_assigned_list_is_not_loaded(monkeypatch) -> None:
    assigned = AsyncMock(return_value=[3])
    monkeypatch.setattr(mention_parser, "_assigned_ids", assigned)

    async def allowed(db, *, section=None, user_ids=None):
        return [SimpleNamespace(id=uid) for uid in sorted(user_ids or ())]

    monkeypatch.setattr(mention_parser, "mentionable_users", allowed)

    assert await parse_mentions(MagicMock(), "wszyscy bez małpy", 42) == []
    assigned.assert_not_awaited()


async def test_note_without_recruitment_ignores_everyone(monkeypatch) -> None:
    """Notatka kandydata bez rekrutacji nie ma zespołu — `@wszyscy` to tekst."""
    assigned = AsyncMock(return_value=[3])
    monkeypatch.setattr(mention_parser, "_assigned_ids", assigned)

    assert await parse_mentions_global(MagicMock(), "@wszyscy uwaga") == []
    assigned.assert_not_awaited()
