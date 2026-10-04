"""„Stawka od” (0414) — reguła liczenia bez bazy.

Decyzje Artura 04.10.2026: najniższa stawka z 18 miesięcy, jawne minimum
unieważnia starsze niższe, odstające liczą się jak inne (wyłącza je człowiek),
zakres liczy się dolną granicą, bez obserwacji w oknie — ostatnia znana
z oznaczeniem „nieaktualna”.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import candidate_rate_from as rf
from app.services import candidate_rate_from_schema as schema
from app.services.candidate_rate_observations import (
    RateObservation,
    card_rate_amount,
    hourly_from_unit,
)

TODAY = date(2026, 10, 4)


def _at(y: int, m: int, d: int = 15) -> datetime:
    return datetime(y, m, d, 12, tzinfo=timezone.utc)


def _obs(key: str, amount, at: datetime, **kw) -> RateObservation:
    return RateObservation(
        key=key,
        candidate_id=1,
        amount_hourly=Decimal(str(amount)) if amount is not None else None,
        raw=None,
        at=at,
        source=kw.pop("source", "card"),
        **kw,
    )


def test_window_start_is_18_months_back_and_clips_month_end():
    assert rf.window_start(date(2026, 10, 4)) == date(2025, 4, 4)
    assert rf.window_start(date(2026, 8, 31)) == date(2025, 2, 28)


def test_lowest_rate_in_window_wins():
    result = rf.compute(
        [
            _obs("card:1", 140, _at(2026, 5)),
            _obs("card:2", 80, _at(2025, 8)),
            _obs("card:3", 135, _at(2026, 3)),
        ],
        set(),
        TODAY,
    )
    assert result.amount == Decimal("80")
    assert result.key == "card:2"
    assert not result.stale
    assert result.reasons == {
        "card:1": rf.REASON_COUNTS,
        "card:2": rf.REASON_MINIMUM,
        "card:3": rf.REASON_COUNTS,
    }
    assert result.latest_amount == Decimal("140")
    assert result.count == 3


def test_rates_older_than_window_do_not_count():
    result = rf.compute(
        [_obs("card:1", 60, _at(2022, 11)), _obs("card:2", 135, _at(2026, 3))],
        set(),
        TODAY,
    )
    assert result.amount == Decimal("135")
    assert result.reasons["card:1"] == rf.REASON_OUTSIDE_WINDOW


def test_no_rate_in_window_falls_back_to_latest_known_marked_stale():
    result = rf.compute(
        [_obs("card:1", 120, _at(2022, 1)), _obs("card:2", 140, _at(2023, 6))],
        set(),
        TODAY,
    )
    assert result.amount == Decimal("140")
    assert result.stale is True


def test_explicit_minimum_supersedes_older_lower_rates_only():
    result = rf.compute(
        [
            _obs("card:1", 80, _at(2025, 8)),
            _obs("profile:9", 130, _at(2026, 6), explicit_minimum=True),
            _obs("card:2", 120, _at(2026, 7)),  # nowsza niższa — liczy się
        ],
        set(),
        TODAY,
    )
    assert result.amount == Decimal("120")
    assert result.reasons["card:1"] == rf.REASON_SUPERSEDED


def test_explicit_minimum_alone_sets_the_floor():
    result = rf.compute(
        [
            _obs("card:1", 80, _at(2025, 8)),
            _obs("profile:9", 130, _at(2026, 6), explicit_minimum=True),
        ],
        set(),
        TODAY,
    )
    assert result.amount == Decimal("130")


def test_excluded_observation_does_not_count_and_outlier_is_not_auto_excluded():
    observations = [
        _obs("card:1", 40, _at(2026, 1)),
        _obs("card:2", 120, _at(2026, 2)),
        _obs("card:3", 130, _at(2026, 3)),
        _obs("card:4", 140, _at(2026, 4)),
    ]
    # Odstająca liczy się jak każda inna (decyzja Artura).
    assert rf.compute(observations, set(), TODAY).amount == Decimal("40")
    excluded = rf.compute(observations, {"card:1"}, TODAY)
    assert excluded.amount == Decimal("120")
    assert excluded.reasons["card:1"] == rf.REASON_EXCLUDED


def test_not_comparable_observation_is_listed_but_never_counts():
    result = rf.compute(
        [
            _obs("stage:1", None, _at(2026, 5), not_comparable=True),
            _obs("card:1", 150, _at(2026, 5)),
        ],
        set(),
        TODAY,
    )
    assert result.amount == Decimal("150")
    assert result.reasons["stage:1"] == rf.REASON_NOT_COMPARABLE


def test_tie_takes_the_newest_observation():
    result = rf.compute(
        [_obs("card:1", 100, _at(2025, 9)), _obs("card:2", 100, _at(2026, 9))],
        set(),
        TODAY,
    )
    assert result.key == "card:2"


def test_nothing_known_gives_empty_result():
    result = rf.compute([], set(), TODAY)
    assert result.amount is None and result.count == 0 and not result.stale


def test_card_range_counts_lower_bound_and_foreign_or_monthly_does_not():
    assert card_rate_amount(
        {"value": 120.0, "value_max": 140.0, "currency": "PLN", "period": "h"}
    ) == Decimal("120.0")
    assert card_rate_amount({"raw": "14 000 zł"}) is None
    assert card_rate_amount({"value": 30, "currency": "EUR", "period": "h"}) is None


def test_stage_units_convert_with_company_month():
    assert hourly_from_unit(Decimal("800"), "daily", "PLN") == Decimal("100.00")
    assert hourly_from_unit(Decimal("16800"), "monthly", "PLN") == Decimal("100.00")
    assert hourly_from_unit(Decimal("120"), "hourly", None) == Decimal("120.00")
    assert hourly_from_unit(Decimal("120"), None, "PLN") is None
    assert hourly_from_unit(Decimal("30"), "hourly", "EUR") is None


def test_effective_rate_prefers_rate_from_after_recompute(monkeypatch):
    monkeypatch.setattr(rf.settings, "CANDIDATE_RATE_FROM_ENABLED", True)
    computed = SimpleNamespace(
        rate_from_computed_at=_at(2026, 10),
        rate_from_hourly=Decimal("80"),
        expected_rate_hourly=Decimal("140"),
        expected_rate_currency="PLN",
    )
    assert rf.effective_rate(computed) == (Decimal("80"), "PLN")
    computed.rate_from_hourly = None
    assert rf.effective_rate(computed) == (None, None)
    fresh = SimpleNamespace(
        expected_rate_hourly=Decimal("140"), expected_rate_currency=None
    )
    assert rf.effective_rate(fresh) == (Decimal("140"), None)


def test_flag_off_reads_profile_rate(monkeypatch):
    monkeypatch.setattr(rf.settings, "CANDIDATE_RATE_FROM_ENABLED", False)
    computed = SimpleNamespace(
        rate_from_computed_at=_at(2026, 10),
        rate_from_hourly=Decimal("80"),
        expected_rate_hourly=Decimal("140"),
        expected_rate_currency="PLN",
    )
    assert rf.effective_rate(computed) == (Decimal("140"), "PLN")
    assert "rate_from" not in rf.effective_rate_raw_sql("c")


def test_entrypoint_imports_the_single_schema_source():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()
    assert (
        "from app.services import candidate_rate_from_schema as _rate_from"
        in entrypoint
    )
    assert "*_RATE_FROM_DDL," in entrypoint
    assert "*_RATE_FROM_BACKFILL," in entrypoint


def test_schema_marker_and_raw_sql_have_no_bind_colons():
    assert schema.BACKFILL_MARKER in schema.BACKFILL_DDL[0]
    for stmt in schema.ALL_DDL:
        # entrypoint wykonuje instrukcje wprost — dwukropek byłby parametrem.
        assert ":" not in stmt.replace("::", ""), stmt[:60]


@pytest.mark.parametrize("today", [date(2026, 1, 31), date(2026, 3, 31)])
def test_window_start_never_raises(today):
    assert rf.window_start(today) < today


def test_exclusion_applies_only_to_the_same_amount_and_date():
    old = _obs("card:5", 90, _at(2026, 5))
    decision = rf.RateDecision("card:5", Decimal("90.00"), _at(2026, 5), 7)
    assert rf.active_exclusions([old], [decision]) == {"card:5": 7}
    # Ta sama karta po nowej notatce: inna kwota i data — znowu się liczy.
    new = _obs("card:5", 130, _at(2026, 9))
    assert rf.active_exclusions([new], [decision]) == {}


def test_quick_correction_by_the_same_person_replaces_the_typo():
    from app.services.candidate_rate_observations import _without_quick_corrections

    base = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    rows = [
        {"id": 1, "candidate_id": 1, "user_id": 5, "created_at": base, "details": {}},
        {
            "id": 2,
            "candidate_id": 1,
            "user_id": 5,
            "created_at": base.replace(minute=3),
            "details": {},
        },
        {
            "id": 3,
            "candidate_id": 1,
            "user_id": 6,
            "created_at": base.replace(hour=12),
            "details": {},
        },
    ]
    assert [r["id"] for r in _without_quick_corrections(rows)] == [2, 3]


def test_staleness_reads_the_latest_rate_date(monkeypatch):
    monkeypatch.setattr(rf.settings, "CANDIDATE_RATE_FROM_ENABLED", True)
    candidate = SimpleNamespace(
        rate_from_computed_at=_at(2026, 10),
        rate_from_at=_at(2025, 12),
        rate_latest_at=_at(2026, 9),
        profile_rate_updated_at=None,
    )
    assert rf.effective_rate_at(candidate) == _at(2026, 9)
