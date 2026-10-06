"""Budżet rekrutacji „od–do” (0420): budżetem jest góra, „od” tylko do wyświetlania."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.job import JobCreate
from app.services import champion_intake, job_budget_range
from app.services.champion_draft_service import _ground_basics_rate
from app.services.champion_job_sync import overwrite_edited_job_columns
from app.services.job_request_intake import normalize_model_output
from app.services.plain_knowledge import job_brief

_BACKEND = Path(__file__).resolve().parents[1]


def _job(**kw):
    base = dict(
        rate_budget_hourly=None,
        rate_budget_hourly_min=None,
        champion_profile=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def champion_signals(monkeypatch):
    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True)


# ── effective_min ────────────────────────────────────────────────────────────


def test_explicit_min_below_budget_is_shown():
    assert (
        job_budget_range.effective_min(
            _job(rate_budget_hourly=80, rate_budget_hourly_min=60)
        )
        == 60
    )


@pytest.mark.parametrize("low", [80, 95])
def test_min_not_below_budget_is_hidden(low):
    assert (
        job_budget_range.effective_min(
            _job(rate_budget_hourly=80, rate_budget_hourly_min=low)
        )
        is None
    )


def test_min_without_budget_is_hidden():
    assert job_budget_range.effective_min(_job(rate_budget_hourly_min=60)) is None


def test_champion_range_text_gives_the_min(champion_signals):
    job = _job(
        champion_profile={"basics": {"rate_value": 140, "rate_raw": "120–140 zł/h"}}
    )
    assert job_budget_range.effective_min(job) == 120


def test_champion_range_of_a_different_budget_is_ignored(champion_signals):
    # Kolumna rekrutacji (150) wygrywa — tekst „120–140” opisuje inną liczbę.
    job = _job(
        rate_budget_hourly=150,
        champion_profile={"basics": {"rate_value": 140, "rate_raw": "120–140 zł/h"}},
    )
    assert job_budget_range.effective_min(job) is None


def test_champion_single_rate_has_no_min(champion_signals):
    job = _job(
        champion_profile={"basics": {"rate_value": 140, "rate_raw": "do 140 zł/h"}}
    )
    assert job_budget_range.effective_min(job) is None


# ── schemat i migracja ───────────────────────────────────────────────────────


def test_create_rejects_min_not_below_max():
    def check(**kw):
        return JobCreate.model_construct(**kw)._budget_range()

    with pytest.raises(ValueError, match="od"):
        check(rate_budget_hourly=80, rate_budget_hourly_min=80)
    check(rate_budget_hourly=80, rate_budget_hourly_min=60)
    check(rate_budget_hourly=None, rate_budget_hourly_min=60)


def test_entrypoint_mirrors_the_migration_column():
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert f'"{job_budget_range.COLUMN_DDL}",' in entrypoint
    migration = (_BACKEND / "alembic/versions/0420_job_budget_hourly_min.py").read_text(
        encoding="utf-8"
    )
    assert "job_budget_range.COLUMN_DDL" in migration


def test_min_is_redacted_for_viewer_and_stripped_from_list():
    from app.api.candidate_access import _VIEWER_REDACTED_JOB_FIELDS
    from app.api.jobs import _LIST_ONLY_STRIPPED_JOB_FIELDS
    from app.api.recruitment_access import JOB_MEMBER_LOCKED_FIELDS

    assert {"rate_budget_hourly_min", "effective_budget_hourly_min"} <= set(
        _VIEWER_REDACTED_JOB_FIELDS
    )
    assert "effective_budget_hourly_min" in _LIST_ONLY_STRIPPED_JOB_FIELDS
    assert "rate_budget_hourly_min" in JOB_MEMBER_LOCKED_FIELDS


# ── PATCH ────────────────────────────────────────────────────────────────────


def test_patch_rejects_min_not_below_budget():
    from app.api.jobs import _normalize_budget_range_for_update

    job = _job(rate_budget_hourly=80)
    with pytest.raises(HTTPException) as exc:
        _normalize_budget_range_for_update(job, {"rate_budget_hourly_min": 90})
    assert exc.value.status_code == 422


def test_patch_lowering_budget_below_min_clears_min():
    from app.api.jobs import _normalize_budget_range_for_update

    job = _job(rate_budget_hourly=80, rate_budget_hourly_min=60)
    updates = {"rate_budget_hourly": 55}
    _normalize_budget_range_for_update(job, updates)
    assert updates["rate_budget_hourly_min"] is None


def test_patch_keeps_min_when_budget_stays_above():
    from app.api.jobs import _normalize_budget_range_for_update

    job = _job(rate_budget_hourly=80, rate_budget_hourly_min=60)
    updates = {"rate_budget_hourly": 90}
    _normalize_budget_range_for_update(job, updates)
    assert "rate_budget_hourly_min" not in updates


def test_champion_edit_lowering_budget_clears_min(monkeypatch):
    monkeypatch.setattr(
        "app.services.requirement_contract.apply_requirement_source_update",
        lambda job, column, value: setattr(job, column, value),
    )
    job = _job(rate_budget_hourly=80, rate_budget_hourly_min=60)
    changed = overwrite_edited_job_columns(job, {"rate_value": 80}, {"rate_value": 50})
    assert job.rate_budget_hourly == 50
    assert job.rate_budget_hourly_min is None
    assert "rate_budget_hourly_min" in changed


# ── goły przedział z maila ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("60-80", (60.0, 80.0)),
        ("60 – 80", (60.0, 80.0)),
        ("Stawka: 60-80 netto", (60.0, 80.0)),
        ("od 60 do 80", (60.0, 80.0)),
        ("1100", None),
        ("60", None),
        ("15-20", None),
        ("80-60", None),
        ("300-500", None),
        ("60-80 zł/MD", None),
        ("60-80 EUR", None),
    ],
)
def test_bare_hourly_range(text, expected):
    assert champion_intake.bare_hourly_range(text) == expected


def test_request_bare_range_is_a_checked_suggestion():
    """Przypadek ze zgłoszenia: request z „60-80” bez waluty i jednostki."""
    text = "Szukamy testera. Stawka: 60-80. Praca hybrydowa."
    result = normalize_model_output({"rate_quote": "60-80"}, text)
    assert result.rate_budget_hourly == 80
    assert result.rate_budget_hourly_min == 60
    assert "Sprawdź" in (result.rate_note or "")


def test_request_range_with_unit_keeps_the_min():
    text = "Budżet 60-80 zł/h netto, zdalnie."
    result = normalize_model_output({"rate_quote": "60-80 zł/h netto"}, text)
    assert result.rate_budget_hourly == 80
    assert result.rate_budget_hourly_min == 60


def test_request_bare_range_next_to_man_day_stays_empty():
    text = "Stawka 60-80 MD, zdalnie."
    result = normalize_model_output({"rate_quote": "60-80"}, text)
    assert result.rate_budget_hourly is None
    assert result.rate_budget_hourly_min is None


def test_champion_draft_bare_range_writes_canonical_text():
    basics = {"rate_raw": "60-80", "rate_value": 70}
    note = _ground_basics_rate(basics, "Stawka 60-80, praca zdalna.")
    assert basics["rate_value"] == 80
    assert champion_intake.pln_hourly_bounds(basics["rate_raw"]) == (60.0, 80.0)
    assert "Sprawdź" in (note or "")


# ── Brief ────────────────────────────────────────────────────────────────────


def test_rate_sentence_with_range():
    inputs = {"budget_pln_hourly_b2b_net": 80, "budget_pln_hourly_b2b_net_min": 60}
    assert job_brief.rate_sentence(inputs) == "Od 60 do 80 zł netto za godzinę na B2B."
    assert job_brief.rate_sentence({"budget_pln_hourly_b2b_net": 80}).startswith(
        "Do 80"
    )


def test_brief_inputs_without_min_keep_their_shape():
    job = _job(
        rate_budget_hourly=80,
        title="Tester",
        working_title=None,
        location=None,
        work_mode=None,
        onsite_days_per_week=None,
        onsite_days_per_month=None,
    )
    kwargs = dict(
        client_name=None, client_about=None, client_process=None, role_name=None
    )
    inputs = job_brief.collect_inputs(job, **kwargs)
    assert "budget_pln_hourly_b2b_net_min" not in inputs
    job.rate_budget_hourly_min = 60
    assert (
        job_brief.collect_inputs(job, **kwargs)["budget_pln_hourly_b2b_net_min"] == 60
    )
