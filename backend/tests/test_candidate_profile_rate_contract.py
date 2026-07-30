from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.candidate import Candidate, CandidateStatus
from app.schemas.candidate import CandidateCreate, CandidateResponse, CandidateUpdate
from app.schemas.candidate_profile_facts import CandidateProfileRatePatch
from app.schemas.candidate_search import CandidateSearchRequest
from app.schemas.candidate_search_v3 import CandidateSearchQueryV3, RateFilter
from app.services.candidate_profile_rate import canonical_profile_rate_amount
from app.services.candidate_profile_rate import (
    CandidateProfileRateSchemaError,
    assert_candidate_profile_rate_schema,
)
from app.services import candidate_profile_facts as profile_facts
from app.services.match_score_cache import _breakdown_from_row
from app.services.scoring_service import _score_salary


def _error_type(model, payload: dict) -> str:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(payload)
    return exc_info.value.errors()[0]["type"]


@pytest.mark.parametrize(
    "payload",
    [
        {"salary_expectation": None},
        {"salary_currency": "PLN"},
        {"salaryExpectation": 20_000},
        {"monthlyRate": 20_000},
        {"preferences": {"rate_min": 10_000}},
    ],
)
def test_candidate_create_rejects_retired_monthly_alias_presence(payload: dict):
    assert (
        _error_type(
            CandidateCreate,
            {"name": "Jan", "lastname": "Kowalski", **payload},
        )
        == "candidate_monthly_rate_retired"
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            {"expected_rate_hourly": 150},
            "candidate_profile_rate_requires_dedicated_endpoint",
        ),
        (
            {"expected_rate_currency": "PLN"},
            "candidate_profile_rate_requires_dedicated_endpoint",
        ),
        ({"languages": []}, "candidate_languages_require_dedicated_endpoint"),
        ({"city": "Warszawa"}, "candidate_location_requires_dedicated_endpoint"),
    ],
)
def test_generic_update_cannot_bypass_typed_fact_writers(
    payload: dict,
    code: str,
):
    assert _error_type(CandidateUpdate, payload) == code


def test_legacy_create_location_is_normalized_to_canonical_city():
    candidate = CandidateCreate.model_validate(
        {
            "name": "Jan",
            "lastname": "Kowalski",
            "location": "Warszawa",
            "country": "pl",
        }
    )
    assert candidate.city == "Warszawa"
    assert candidate.country == "PL"
    assert "location" not in candidate.model_dump()


def test_profile_rate_patch_is_required_but_nullable():
    assert _error_type(CandidateProfileRatePatch, {}) == "missing"
    assert CandidateProfileRatePatch.model_validate({"amount": None}).amount is None
    assert CandidateProfileRatePatch.model_validate(
        {"amount": "123.45"}
    ).amount == Decimal("123.45")


def test_empty_candidate_rate_does_not_persist_a_default_currency():
    candidate = Candidate(name="Jan", lastname="Kowalski")

    assert candidate.expected_rate_hourly is None
    assert candidate.expected_rate_currency is None
    assert Candidate.__table__.c.expected_rate_currency.default is None


def test_entrypoint_guards_profile_rate_type_conversion_with_catalog_and_timeouts():
    entrypoint = (
        Path(__file__).resolve().parents[1] / "entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert '_PROFILE_RATE_TARGET_TYPE = "numeric(10,2)"' in entrypoint
    assert "format_type(attribute.atttypid, attribute.atttypmod)" in entrypoint
    assert "attribute.attrelid = to_regclass('candidates')" in entrypoint
    assert "if current_type == _PROFILE_RATE_TARGET_TYPE" in entrypoint
    assert "SET LOCAL lock_timeout = '5s'" in entrypoint
    assert "SET LOCAL statement_timeout = '30s'" in entrypoint
    assert "await _ensure_profile_rate_numeric(conn)" in entrypoint


class _ProfileRateSchemaConnection:
    def __init__(self, observed_type: str | None):
        self.observed_type = observed_type

    async def scalar(self, _statement):
        return self.observed_type


async def test_profile_rate_schema_assertion_accepts_only_exact_numeric_contract():
    await assert_candidate_profile_rate_schema(
        _ProfileRateSchemaConnection("numeric(10,2)")
    )

    for observed_type in (None, "integer", "numeric", "numeric(12,2)"):
        with pytest.raises(CandidateProfileRateSchemaError):
            await assert_candidate_profile_rate_schema(
                _ProfileRateSchemaConnection(observed_type)
            )


def test_lifespan_refuses_traffic_before_saved_search_sweep_on_schema_mismatch():
    main_source = (
        Path(__file__).resolve().parents[1] / "app" / "main.py"
    ).read_text(encoding="utf-8")

    schema_assertion = main_source.index(
        "await assert_candidate_profile_rate_schema(_profile_rate_schema_conn)"
    )
    saved_search_sweep = main_source.index(
        "retired_searches = await retire_candidate_saved_searches"
    )
    assert schema_assertion < saved_search_sweep


class _FakeProfileRateSession:
    def __init__(self, candidate: Candidate):
        self.candidate = candidate
        self.added: list[object] = []
        self.flushes = 0

    async def scalar(self, _statement):
        return self.candidate

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1


async def test_profile_rate_clear_removes_amount_and_currency_and_increments_occ(
    monkeypatch,
):
    candidate = Candidate(
        id=7,
        name="Jan",
        lastname="Kowalski",
        expected_rate_hourly=Decimal("123.45"),
        expected_rate_currency="PLN",
        profile_rate_version=4,
    )
    session = _FakeProfileRateSession(candidate)
    stale_calls: list[int] = []

    async def _mark_stale(_db, candidate_id: int) -> int:
        stale_calls.append(candidate_id)
        return 0

    monkeypatch.setattr(
        "app.services.match_score_cache.mark_stale_for_candidate",
        _mark_stale,
    )

    updated = await profile_facts.update_candidate_profile_rate(
        session,  # type: ignore[arg-type]
        candidate_id=7,
        amount=None,
        expected_version=4,
        actor_id=11,
    )

    assert updated.expected_rate_hourly is None
    assert updated.expected_rate_currency is None
    assert updated.profile_rate_version == 5
    assert updated.profile_rate_updated_at is not None
    assert session.flushes == 1
    assert stale_calls == [7]
    assert len(session.added) == 1
    audit = session.added[0]
    assert audit.details["old_amount"] == "123.45"  # type: ignore[attr-defined]
    assert audit.details["new_amount"] is None  # type: ignore[attr-defined]
    assert audit.details["new_currency"] is None  # type: ignore[attr-defined]


async def test_profile_rate_occ_conflict_does_not_mutate_or_invalidate(monkeypatch):
    candidate = Candidate(
        id=7,
        name="Jan",
        lastname="Kowalski",
        expected_rate_hourly=Decimal("123.45"),
        expected_rate_currency="PLN",
        profile_rate_version=4,
    )
    session = _FakeProfileRateSession(candidate)

    async def _unexpected_stale(*_args, **_kwargs):
        pytest.fail("stale marking must happen only after a successful OCC check")

    monkeypatch.setattr(
        "app.services.match_score_cache.mark_stale_for_candidate",
        _unexpected_stale,
    )

    with pytest.raises(
        profile_facts.ProfileFactsVersionConflictError,
        match="profile facts version is 4",
    ):
        await profile_facts.update_candidate_profile_rate(
            session,  # type: ignore[arg-type]
            candidate_id=7,
            amount=Decimal("200.00"),
            expected_version=3,
            actor_id=11,
        )

    assert candidate.expected_rate_hourly == Decimal("123.45")
    assert candidate.expected_rate_currency == "PLN"
    assert candidate.profile_rate_version == 4
    assert session.added == []
    assert session.flushes == 0


@pytest.mark.parametrize(
    ("currency", "expected"),
    [
        (None, Decimal("123.45")),
        ("", Decimal("123.45")),
        ("pln", Decimal("123.45")),
        ("EUR", None),
        ("USD", None),
    ],
)
def test_only_pln_or_documented_legacy_null_is_a_canonical_profile_rate(
    currency: str | None,
    expected: Decimal | None,
):
    assert canonical_profile_rate_amount("123.45", currency) == expected


def _candidate_response_payload(**overrides):  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc)
    payload = {
        "id": 7,
        "name": "Jan",
        "lastname": "Kowalski",
        "email": None,
        "phone": None,
        "location": None,
        "linkedin": None,
        "expected_rate_hourly": "160.00",
        "expected_rate_currency": "PLN",
        "availability_date": None,
        "source": None,
        "status": CandidateStatus.active,
        "tags": None,
        "skills": None,
        "experience": None,
        "education": None,
        "languages": None,
        "preferences": {"remote_modes": ["remote"], "rate_min": 100},
        "cv_filename": None,
        "cv_parsed_at": None,
        "notes_count": 0,
        "last_contacted_at": None,
        "embedding_id": None,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return payload


def test_candidate_response_hides_foreign_legacy_rate_and_finance_preferences():
    response = CandidateResponse.model_validate(
        _candidate_response_payload(expected_rate_currency="EUR")
    )
    assert response.expected_rate_hourly is None
    assert response.expected_rate_currency is None
    assert response.preferences == {"remote_modes": ["remote"]}
    dumped = response.model_dump()
    assert "salary_expectation" not in dumped
    assert "salary_currency" not in dumped


@pytest.mark.parametrize(
    "payload",
    [
        {"min_salary": 10_000},
        {"salaryMax": None},
        {"filters": {"monthly_rate": 10_000}},
    ],
)
def test_search_rejects_every_retired_alias_instead_of_broadening(payload: dict):
    assert (
        _error_type(CandidateSearchRequest, payload) == "candidate_monthly_rate_retired"
    )


def test_v3_rejects_monthly_alias_and_unit_with_domain_code():
    assert (
        _error_type(
            CandidateSearchQueryV3,
            {"hard_filters": {"salaryExpectation": None}},
        )
        == "candidate_monthly_rate_retired"
    )
    assert (
        _error_type(RateFilter, {"unit": "monthly", "max": 20_000})
        == "candidate_monthly_rate_retired"
    )


def test_foreign_legacy_rate_is_not_comparable_and_does_not_reduce_score():
    candidate = SimpleNamespace(
        expected_rate_hourly=Decimal("50.00"),
        expected_rate_currency="EUR",
    )
    job = SimpleNamespace(salary_min=20_000, salary_max=30_000)
    result = _score_salary(candidate, job)
    assert result.status == "not_comparable"
    assert result.points == result.max_points
    assert "50" not in result.reason
    assert "EUR" not in result.reason


def test_not_comparable_status_survives_match_cache_round_trip():
    row = SimpleNamespace(
        candidate_id=7,
        job_id=11,
        total_score=100,
        breakdown={
            "salary": {
                "points": 10,
                "max": 10,
                "reason": "not_comparable",
                "status": "not_comparable",
            }
        },
    )
    result = _breakdown_from_row(row)
    assert result.salary.status == "not_comparable"
