"""Dni w biurze: tydzień albo miesiąc (0406) — reguła i jej lustro we froncie."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.champion import ChampionBasics
from app.services import office_days
from app.services.champion_job_sync import fill_job_columns_from_champion

_CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "frontend/src/lib/__fixtures__/office-days-cases.json"
    ).read_text(encoding="utf-8")
)
_BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", _CASES["weekly_from_monthly"])
def test_weekly_from_monthly_matches_the_shared_cases(case):
    assert office_days.weekly_from_monthly(case["month"]) == case["week"]


@pytest.mark.parametrize("case", _CASES["label"])
def test_label_matches_the_shared_cases(case):
    assert office_days.label(case["week"], case["month"]) == case["label"]


def test_monthly_entry_never_reads_as_remote():
    # Zero dni w tygodniu wyłączyłoby bramki biura — „raz w miesiącu” to biuro.
    assert all(office_days.weekly_from_monthly(m) >= 1 for m in range(1, 23))


def test_normalize_monthly_wins_and_derives_the_weekly_value():
    assert office_days.normalize(3, 2, "hybrid") == (1, 2)
    assert office_days.normalize(None, 8, None) == (2, 8)


def test_normalize_weekly_only_keeps_the_value():
    assert office_days.normalize(3, None, "onsite") == (3, None)
    assert office_days.normalize(0, None, "hybrid") == (0, None)


@pytest.mark.parametrize("mode", ["onsite", "remote"])
def test_monthly_needs_hybrid_mode(mode):
    with pytest.raises(ValueError, match="hybrydowej"):
        office_days.normalize(None, 2, mode)


def test_champion_basics_derive_weekly_and_hide_empty_monthly():
    basics = ChampionBasics.model_validate({"onsite_days_per_month": 2})
    assert basics.onsite_days_per_week == 1
    assert basics.model_dump()["onsite_days_per_month"] == 2
    # Profile sprzed 0406 nie zmieniają kształtu JSONB.
    assert "onsite_days_per_month" not in ChampionBasics().model_dump()


def test_champion_sync_fills_both_columns_from_a_monthly_entry():
    job = SimpleNamespace(
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        onsite_days_per_month=None,
        remote_policy=None,
        location=None,
    )
    filled = fill_job_columns_from_champion(
        job, {"onsite_days_per_week": 1, "onsite_days_per_month": 2}
    )
    assert job.onsite_days_per_week == 1
    assert job.onsite_days_per_month == 2
    assert {"onsite_days_per_week", "onsite_days_per_month"} <= set(filled)


def test_entrypoint_mirrors_the_migration_column():
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert f'"{office_days.COLUMN_DDL}",' in entrypoint


def _job(week=None, month=None, policy="hybrid"):
    return SimpleNamespace(
        onsite_days_per_week=week, onsite_days_per_month=month, remote_policy=policy
    )


def test_patch_monthly_entry_sets_the_weekly_value():
    from app.api.jobs import _normalize_office_days_for_update

    updates = {"onsite_days_per_month": 2}
    _normalize_office_days_for_update(_job(week=3), updates)
    assert updates == {"onsite_days_per_month": 2, "onsite_days_per_week": 1}


def test_patch_weekly_entry_clears_the_monthly_value():
    from app.api.jobs import _normalize_office_days_for_update

    updates = {"onsite_days_per_week": 2}
    _normalize_office_days_for_update(_job(week=1, month=2), updates)
    assert updates == {"onsite_days_per_week": 2, "onsite_days_per_month": None}


def test_patch_leaving_hybrid_drops_the_monthly_value_but_keeps_weekly():
    from app.api.jobs import _normalize_office_days_for_update

    updates = {"remote_policy": "onsite"}
    _normalize_office_days_for_update(_job(week=1, month=2), updates)
    assert updates == {"remote_policy": "onsite", "onsite_days_per_month": None}


def test_patch_untouched_office_days_are_left_alone():
    from app.api.jobs import _normalize_office_days_for_update

    updates = {"title": "Nowy tytuł"}
    _normalize_office_days_for_update(_job(week=1, month=2), updates)
    assert updates == {"title": "Nowy tytuł"}


def test_monthly_entry_for_onsite_work_is_a_422():
    from fastapi import HTTPException

    from app.api.jobs import _normalize_office_days_for_create

    with pytest.raises(HTTPException) as exc:
        _normalize_office_days_for_create(
            {"remote_policy": "onsite", "onsite_days_per_month": 2}
        )
    assert exc.value.status_code == 422


def test_create_derives_the_weekly_value():
    from app.api.jobs import _normalize_office_days_for_create

    payload = {"remote_policy": "hybrid", "onsite_days_per_month": 8}
    _normalize_office_days_for_create(payload)
    assert payload["onsite_days_per_week"] == 2
