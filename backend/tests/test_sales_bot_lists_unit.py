"""Bot Listy bez bazy (decyzje Artura 13.11.2026): role, wielkości, brief, „Co działa”."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.services.sales import bot_lists


@pytest.mark.parametrize(
    ("title", "role"),
    [
        ("IT Manager", "manager"),
        ("Kierownik Działu IT", "manager"),
        ("Team Lead Java", "manager"),
        ("Head of IT Department", "head"),
        ("Dyrektor Departamentu Informatyki", "head"),
        ("CTO", "cxo"),
        ("Chief Information Officer", "cxo"),
        ("Prezes Zarządu", "board"),
        ("CEO, co-founder", "board"),
        ("Analityk", "other"),
        (None, "other"),
    ],
)
def test_role_of_title(title: str | None, role: str) -> None:
    assert bot_lists.role_of(title) == role


@pytest.mark.parametrize(
    ("value", "bucket"),
    [
        ("11-50", "1-49"),
        ("51-200", "50-249"),
        ("250-999", "250-999"),
        ("201-500", "50-249"),
        ("501-1000", "250-999"),
        ("1000+", "1000+"),
        ("5000+", "1000+"),
        ("", None),
        (None, None),
    ],
)
def test_size_bucket_uses_the_lower_bound(
    value: str | None, bucket: str | None
) -> None:
    assert bot_lists.size_bucket(value) == bucket


def test_brief_defaults_and_limits() -> None:
    brief = bot_lists.Brief.model_validate({"caller_ids": [5]})
    assert brief.roles == ["manager", "head"]
    assert brief.sources == ["base"] and brief.per_caller == 40
    assert brief.include_unknown and brief.auto_refill
    for bad in (
        {"caller_ids": []},
        {"caller_ids": [5], "per_caller": 0},
        {"caller_ids": [5], "roles": ["ceo"]},
        {"caller_ids": [5], "unknown": 1},
        {"caller_ids": [5], "pkd": ["abc"]},
    ):
        with pytest.raises(ValidationError):
            bot_lists.Brief.model_validate(bad)
    brief = bot_lists.Brief.model_validate(
        {
            "caller_ids": [5],
            "pkd": ["62", "64.19z"],
            "industries": [" bank ", "bank", "x"],
        }
    )
    assert brief.pkd == ["62", "64.19Z"]
    assert brief.industries == ["bank"]


def test_rates_by_role_and_source() -> None:
    rows = [
        ("IT Manager", "meeting_booked", "Lista A"),
        ("IT Manager", "not_interested", "Lista A"),
        ("CTO", "no_answer", "Bot Listy · baza NEXUSA"),
        ("Prezes", "not_interested", "Lista A"),
    ]
    by_role = {r.role: r for r in bot_lists.rates_by(rows, "role")}
    assert (by_role["manager"].calls, by_role["manager"].meetings) == (2, 1)
    assert by_role["manager"].rate == 0.5
    assert by_role["board"].not_interested == 1
    by_source = bot_lists.rates_by(rows, "source")
    assert by_source[0].role == "Lista A" and by_source[0].calls == 3


@pytest.mark.asyncio
async def test_role_order_follows_meetings_with_smoothing(monkeypatch) -> None:
    rows = [("CTO", "meeting_booked", None)] * 3 + [("CTO", "no_answer", None)] * 20
    rows += [("IT Manager", "no_answer", None)] * 50
    rows += [("Prezes", "meeting_booked", None)]

    async def rated(_db, _campaign):
        return rows

    monkeypatch.setattr(bot_lists, "rated_records", rated)
    order = await bot_lists.role_order(object(), ["manager", "cxo", "board"])
    # CTO 3 z 23 wygrywa. Zarząd 1 z 1 po wygładzeniu (1,6/31) zostaje nad
    # Managerem bez spotkań (0,6/80), ale nie nad CTO.
    assert order[0] == "cxo"
    assert order.index("board") < order.index("manager")


def test_refill_is_due_on_monday_from_seven() -> None:
    assert bot_lists.refill_due(datetime(2026, 11, 16, 7, 0))
    assert not bot_lists.refill_due(datetime(2026, 11, 16, 6, 59))
    assert not bot_lists.refill_due(datetime(2026, 11, 17, 9, 0))
