"""Business identity used by every aggregate active-contractor counter."""

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.analytics import metrics
from app.api import contract_analytics
from app.api.contractors import contractor_stats
from app.models.contract import ContractStatus
from app.models.user import UserRole
from app.services import contractor_identity
from app.services.contractor_identity import (
    contractor_identity_key,
    count_unique_contractors,
    summarize_active_contracts,
)
from app.core.scheduling import business_today
from tests._namesake_pair import fictional_namesakes  # noqa: F401 (fixture)

_BACKEND = Path(__file__).resolve().parents[1]


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
        _candidate(1, "  OSKAR ", "Testowy", "first@example.com"),
        _candidate(2, "Oskar", "  Test-owy ", "other@example.com"),
    ]

    assert count_unique_contractors(variants) == 1


def test_non_latin_names_are_preserved_and_deduplicated():
    variants = [
        _candidate(101, " ОЛЕНА ", "КОВАЛЬ", "first@example.com"),
        _candidate(102, "олена", "коваль", "second@example.com"),
    ]

    assert count_unique_contractors(variants) == 1


@pytest.mark.usefixtures("fictional_namesakes")
def test_only_a_namesake_pair_is_split_by_normalized_profile_email():
    namesake_variants = [
        _candidate(1, " Józef ", "Przykładowy", " FIRST@Example.com "),
        _candidate(2, "JOZEF", "Przy-kladowy", "first@example.com"),
        _candidate(3, "Józef", "Przykładowy", "second@example.com"),
    ]
    ordinary_same_name_different_email = [
        _candidate(4, "Anna", "Nowak", "one@example.com"),
        _candidate(5, "ANNA", "NOWAK", "two@example.com"),
    ]

    assert count_unique_contractors(namesake_variants) == 2
    assert count_unique_contractors(ordinary_same_name_different_email) == 1


@pytest.mark.usefixtures("fictional_namesakes")
def test_namesake_without_email_fails_closed_by_candidate_id():
    incomplete_profiles = [
        _candidate(6, "Józef", "Przykładowy", None),
        _candidate(7, "jozef", "przykladowy", " "),
    ]

    assert count_unique_contractors(incomplete_profiles) == 2


def test_placeholder_names_fall_back_to_candidate_id_instead_of_collapsing():
    unknowns = [
        _candidate(10, "?", "?", None),
        _candidate(11, "?", "?", None),
    ]

    assert count_unique_contractors(unknowns) == 2


def test_headcount_keeps_person_and_contract_totals_separate():
    oskar = _candidate(20, "Oskar", "Testowy", "oskar@example.com")
    duplicate_profile = _candidate(21, " oskar ", "TESTOWY", "duplicate@example.com")
    contracts = [
        SimpleNamespace(candidate=oskar),
        SimpleNamespace(candidate=duplicate_profile),
        SimpleNamespace(candidate=None),
    ]

    result = summarize_active_contracts(contracts)

    assert result.contractors == 1
    assert result.active_contracts == 3


@pytest.mark.usefixtures("fictional_namesakes")
def test_raw_key_normalizes_exception_email_case_and_space():
    key = contractor_identity_key("Józef", "Przykładowy", " JOZEF@EXAMPLE.COM ")

    assert key == contractor_identity_key("jozef", "przykladowy", "jozef@example.com")
    assert key == ("name_email", "jozef", "przykladowy", "jozef@example.com")


@pytest.mark.asyncio
async def test_finance_summary_exposes_one_person_and_two_contracts(
    monkeypatch: pytest.MonkeyPatch,
):
    first_profile = _candidate(30, "Oskar", "Testowy", "first@example.com")
    duplicate_profile = _candidate(31, " OSKAR ", "testowy", "duplicate@example.com")
    contracts = [
        SimpleNamespace(
            candidate=first_profile,
            currency="PLN",
            rate_client_currency=None,
            rate_candidate_currency=None,
        ),
        SimpleNamespace(
            candidate=duplicate_profile,
            currency="PLN",
            rate_client_currency=None,
            rate_candidate_currency=None,
        ),
    ]

    async def fake_rates(_db, _currencies, _on):
        return {"PLN": Decimal("1")}

    monkeypatch.setattr(metrics, "_fx_rates_to_pln", fake_rates)
    monkeypatch.setattr(
        metrics,
        "effective_rate_fields",
        lambda _contract, _on: {
            "monthly_rate_client": Decimal("10000"),
            "monthly_rate_candidate": Decimal("8000"),
            "monthly_margin": Decimal("2000"),
        },
    )

    data, warnings, quality = await metrics._sum_finance(
        object(), contracts, on=business_today()
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
    first_profile = _candidate(40, "Oskar", "Testowy", "one@example.com")
    duplicate_profile = _candidate(41, "oskar", "TESTOWY", "two@example.com")
    far_end = business_today() + timedelta(days=90)
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
    # Roster wymaga podglądu Delivery (0410) — admin ma go zawsze; bez migawki
    # polityki decydują domyślne uprawnienia roli.
    user = SimpleNamespace(
        get_all_roles=lambda: [UserRole.admin],
        has_role=lambda role: role is UserRole.admin,
        has_any_role=lambda *roles: UserRole.admin in roles,
    )

    stats = await contractor_stats(user, _StatsDb(contracts))

    assert stats.active == 1
    assert stats.active_contracts == 2


@pytest.mark.asyncio
async def test_utilization_deduplicates_denominator_and_bench_gap_per_identity():
    """Ława to OSOBA, nie wiersz kandydata i nie kontrakt.

    Duplikaty profili fałdują się po tożsamości — inaczej utylizacja
    zmieniałaby się przy każdym scaleniu duplikatów. Mianownik to populacja
    konsultantów: Jan Bezkontraktu ma kontrakt (jest w wierszach), ale ktoś,
    kto NIGDY go nie miał, nie pojawia się tu wcale (audyt 18.09.2026 —
    dzielenie przez całą bazę CV dawało 0,8% zamiast 91,3%).
    """
    today = business_today()

    def _row(candidate, end_date):
        # Kształt wiersza = SELECT populacji (kandydat + end_date + status).
        status = ContractStatus.active if end_date is None else ContractStatus.ended
        return SimpleNamespace(**vars(candidate), end_date=end_date, status=status)

    population_rows = [
        # Oskar Testowy — dwa profile, jeden pracuje (kontrakt bez daty końca).
        _row(_candidate(50, "Oskar", "Testowy", "one@example.com"), None),
        _row(
            _candidate(51, "OSKAR", "Test-owy", "two@example.com"),
            today - timedelta(days=5),
        ),
        # Anna Nowak — dwa profile, oba zakończone: jedna osoba na ławce.
        _row(
            _candidate(52, "Anna", "Nowak", "three@example.com"),
            today - timedelta(days=10),
        ),
        _row(
            _candidate(53, "ANNA", "NOWAK", "four@example.com"),
            today - timedelta(days=4),
        ),
        # Kontrakt zakończony bez wpisanej daty końca — osoba jest na ławce,
        # ale nie wnosi przerwy do średniej.
        _row(_candidate(54, "Jan", "Bezdaty", None), today - timedelta(days=20)),
    ]
    db = _SequentialDb(
        _QueryResult(rows=population_rows),
        _QueryResult(scalar_value=2),
    )

    result = await contract_analytics.utilization(SimpleNamespace(), db)

    assert result.total_candidates == 3
    assert result.candidates_active == 1
    assert result.active_contracts == 2
    assert result.candidates_on_bench == 2
    assert result.utilization_pct == 33.3
    # Ostatnia znana data końca per osoba: Anna 4 dni, Jan 20 dni.
    assert result.avg_bench_days == 12.0


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
@pytest.mark.usefixtures("fictional_namesakes")
async def test_location_distribution_uses_lowest_profile_once_per_identity():
    rows = [
        SimpleNamespace(
            **vars(_candidate(60, "Oskar", "Testowy", "one@example.com")),
            hub_city="Warszawa",
            region="Mazowieckie",
        ),
        SimpleNamespace(
            **vars(_candidate(61, "OSKAR", "Test-owy", "two@example.com")),
            hub_city="Kraków",
            region="Małopolskie",
        ),
        SimpleNamespace(
            **vars(_candidate(62, "Józef", "Przykładowy", "first@example.com")),
            hub_city="Gdańsk",
            region="Pomorskie",
        ),
        SimpleNamespace(
            **vars(_candidate(63, "JOZEF", "PRZYKLADOWY", "second@example.com")),
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


# ── Para imienników istnieje w repo wyłącznie jako skrót ─────────────────────


def test_namesake_digests_match_the_repo_guard_list():
    """Literówka w skrócie po cichu wyłączyłaby wyjątek — trzyma go druga kopia."""
    guard = (
        _BACKEND.parent / "frontend/src/__tests__/fixtures/real-people.ts"
    ).read_text(encoding="utf-8")

    assert contractor_identity.NAMESAKE_NAME_DIGESTS
    for digest in contractor_identity.NAMESAKE_NAME_DIGESTS:
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert f'"{digest[:16]}"' in guard


def test_app_code_does_not_name_the_namesakes():
    """Strażnik repo czyta testy i dokumenty — ten wyjątek siedział w kodzie."""
    pairs_by_file: dict[str, set[tuple[str, str]]] = {}
    for root in (_BACKEND / "app", _BACKEND / "scripts"):
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".md", ".json", ".html", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8").lower()
            for letter, plain in zip("ąćęłńóśźż", "acelnoszz"):
                text = text.replace(letter, plain)
            # „_” też dzieli słowa: nazwisko w nazwie stałej to nadal nazwisko.
            words = re.findall(r"[^\W_]+", text)
            pairs_by_file[str(path.relative_to(_BACKEND))] = set(zip(words, words[1:]))

    all_pairs = set().union(*pairs_by_file.values())
    named = {
        (one, other)
        for one, other in all_pairs
        if contractor_identity.is_namesake_pair(one, other)
        or contractor_identity.is_namesake_pair(other, one)
    }

    assert len(all_pairs) > 10_000  # strażnik nie jest pusty
    assert [path for path, pairs in pairs_by_file.items() if pairs & named] == []
