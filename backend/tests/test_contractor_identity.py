"""Business identity used by every aggregate active-contractor counter."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.analytics import metrics
from app.api import contract_analytics
from app.api.contractors import contractor_stats
from app.models.contract import ContractStatus
from app.services.contractor_identity import (
    contractor_identity_key,
    count_unique_contractors,
    summarize_active_contracts,
)


def _candidate(
    candidate_id: int,
    first_name: str,
    last_name: str,
    email: str | None,
):
    return SimpleNamespace(
        id=candidate_id,
        name=first_name,
        lastname=last_name,
        email=email,
    )


def test_regular_contractor_key_folds_case_whitespace_punctuation_and_diacritics():
    variants = [
        _candidate(1, "  PIOTR ", "Klimczak", "first@example.com"),
        _candidate(2, "Piotr", "  Klim-czak ", "other@example.com"),
    ]

    assert count_unique_contractors(variants) == 1


def test_non_latin_names_are_preserved_and_deduplicated():
    variants = [
        _candidate(101, " ОЛЕНА ", "КОВАЛЬ", "first@example.com"),
        _candidate(102, "олена", "коваль", "second@example.com"),
    ]

    assert count_unique_contractors(variants) == 1


def test_only_filip_jablonski_is_split_by_normalized_profile_email():
    filip_variants = [
        _candidate(1, " Filip ", "Jabłoński", " FIRST@Example.com "),
        _candidate(2, "FILIP", "Jablonski", "first@example.com"),
        _candidate(3, "Filip", "Jabłoński", "second@example.com"),
    ]
    ordinary_same_name_different_email = [
        _candidate(4, "Anna", "Nowak", "one@example.com"),
        _candidate(5, "ANNA", "NOWAK", "two@example.com"),
    ]

    assert count_unique_contractors(filip_variants) == 2
    assert count_unique_contractors(ordinary_same_name_different_email) == 1


def test_filip_jablonski_without_email_fails_closed_by_candidate_id():
    incomplete_profiles = [
        _candidate(6, "Filip", "Jabłoński", None),
        _candidate(7, "filip", "jablonski", " "),
    ]

    assert count_unique_contractors(incomplete_profiles) == 2


def test_placeholder_names_fall_back_to_candidate_id_instead_of_collapsing():
    unknowns = [
        _candidate(10, "?", "?", None),
        _candidate(11, "?", "?", None),
    ]

    assert count_unique_contractors(unknowns) == 2


def test_headcount_keeps_person_and_contract_totals_separate():
    piotr = _candidate(20, "Piotr", "Klimczak", "piotr@example.com")
    duplicate_profile = _candidate(21, " piotr ", "KLIMCZAK", "duplicate@example.com")
    contracts = [
        SimpleNamespace(candidate=piotr),
        SimpleNamespace(candidate=duplicate_profile),
        SimpleNamespace(candidate=None),
    ]

    result = summarize_active_contracts(contracts)

    assert result.contractors == 1
    assert result.active_contracts == 3


def test_raw_key_normalizes_exception_email_case_and_space():
    assert contractor_identity_key(
        "Filip", "Jabłoński", " FILIP@EXAMPLE.COM "
    ) == contractor_identity_key("filip", "jablonski", "filip@example.com")


@pytest.mark.asyncio
async def test_finance_summary_exposes_one_person_and_two_contracts(
    monkeypatch: pytest.MonkeyPatch,
):
    first_profile = _candidate(30, "Piotr", "Klimczak", "first@example.com")
    duplicate_profile = _candidate(31, " PIOTR ", "klimczak", "duplicate@example.com")
    contracts = [
        SimpleNamespace(candidate=first_profile, currency="PLN"),
        SimpleNamespace(candidate=duplicate_profile, currency="PLN"),
    ]

    async def fake_rates(_db, _currencies, _on):
        return {"PLN": Decimal("1")}

    monkeypatch.setattr(metrics, "_fx_rates_to_pln", fake_rates)
    monkeypatch.setattr(
        metrics,
        "effective_rate_fields",
        lambda _contract, _on: {
            "monthly_rate_client": Decimal("10000"),
            "monthly_margin": Decimal("2000"),
        },
    )

    data, warnings, quality = await metrics._sum_finance(
        object(), contracts, on=date.today()
    )

    assert warnings == []
    assert quality == "complete"
    assert data["active_consultants"] == 1
    assert data["active_contracts"] == 2


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _StatsDb:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _statement):
        return _ScalarResult(self._rows)


class _QueryResult:
    def __init__(self, *, rows=None, scalar_value=None, one_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value
        self._one_value = one_value

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar_value

    def one(self):
        return self._one_value


class _SequentialDb:
    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, _statement):
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_contractor_stats_deduplicates_active_people_but_keeps_contract_count():
    first_profile = _candidate(40, "Piotr", "Klimczak", "one@example.com")
    duplicate_profile = _candidate(41, "piotr", "KLIMCZAK", "two@example.com")
    far_end = date.today() + timedelta(days=90)
    contracts = [
        SimpleNamespace(
            status=ContractStatus.active,
            end_date=far_end,
            candidate=first_profile,
        ),
        SimpleNamespace(
            status=ContractStatus.active,
            end_date=far_end,
            candidate=duplicate_profile,
        ),
    ]
    user = SimpleNamespace(has_any_role=lambda *_roles: True)

    stats = await contractor_stats(user, _StatsDb(contracts))

    assert stats.active == 1
    assert stats.active_contracts == 2


@pytest.mark.asyncio
async def test_utilization_deduplicates_denominator_and_bench_gap_per_identity():
    today = date.today()
    active_rows = [_candidate(50, "Piotr", "Klimczak", "one@example.com")]
    population_rows = [
        SimpleNamespace(
            **vars(_candidate(50, "Piotr", "Klimczak", "one@example.com")),
            last_end=today - timedelta(days=20),
        ),
        SimpleNamespace(
            **vars(_candidate(51, "PIOTR", "Klim-czak", "two@example.com")),
            last_end=today - timedelta(days=5),
        ),
        SimpleNamespace(
            **vars(_candidate(52, "Anna", "Nowak", "three@example.com")),
            last_end=today - timedelta(days=10),
        ),
        SimpleNamespace(
            **vars(_candidate(53, "ANNA", "NOWAK", "four@example.com")),
            last_end=today - timedelta(days=4),
        ),
        SimpleNamespace(
            **vars(_candidate(54, "Jan", "Bezkontraktu", None)),
            last_end=None,
        ),
    ]
    db = _SequentialDb(
        _QueryResult(rows=active_rows),
        _QueryResult(scalar_value=2),
        _QueryResult(rows=population_rows),
    )

    result = await contract_analytics.utilization(SimpleNamespace(), db)

    assert result.total_candidates == 3
    assert result.candidates_active == 1
    assert result.active_contracts == 2
    assert result.candidates_on_bench == 2
    assert result.utilization_pct == 33.3
    assert result.avg_bench_days == 4.0


@pytest.mark.asyncio
async def test_role_client_mix_global_person_total_is_not_sum_of_cells():
    db = _SequentialDb(
        _QueryResult(
            one_value=SimpleNamespace(contractors=1, contracts=2),
        ),
        _QueryResult(
            rows=[
                SimpleNamespace(
                    role="Developer",
                    client_id=1,
                    client_name="Client A",
                    cnt=1,
                ),
                SimpleNamespace(
                    role="Developer",
                    client_id=2,
                    client_name="Client B",
                    cnt=1,
                ),
            ]
        ),
        _QueryResult(
            rows=[SimpleNamespace(role="Developer", cnt=1)],
        ),
    )

    result = await contract_analytics.role_client_mix(SimpleNamespace(), db)

    assert result.total_active == 1
    assert result.total_active_contracts == 2
    assert [row.active_count for row in result.rows] == [1, 1]
    assert result.role_totals == {"Developer": 1}


@pytest.mark.asyncio
async def test_location_distribution_uses_lowest_profile_once_per_identity():
    rows = [
        SimpleNamespace(
            **vars(_candidate(60, "Piotr", "Klimczak", "one@example.com")),
            hub_city="Warszawa",
            region="Mazowieckie",
        ),
        SimpleNamespace(
            **vars(_candidate(61, "PIOTR", "Klim-czak", "two@example.com")),
            hub_city="Kraków",
            region="Małopolskie",
        ),
        SimpleNamespace(
            **vars(_candidate(62, "Filip", "Jabłoński", "first@example.com")),
            hub_city="Gdańsk",
            region="Pomorskie",
        ),
        SimpleNamespace(
            **vars(_candidate(63, "FILIP", "JABLONSKI", "second@example.com")),
            hub_city="Wrocław",
            region="Dolnośląskie",
        ),
    ]
    db = _SequentialDb(_QueryResult(rows=rows))

    result = await contract_analytics.location_distribution(
        SimpleNamespace(), db, active_only=True
    )

    assert result.total == 3
    assert result.total_with_hub == 3
    hubs = {row.hub_city: row.count for row in result.hubs}
    assert hubs == {"Warszawa": 1, "Gdańsk": 1, "Wrocław": 1}
