"""Dostępność i stawka osoby, która pracuje u nas — reguła bez bazy (15.10.2026).

Zgłoszenie: profil mówił „Pracuje u nas do 30.11.2026” i „Dostępność od
1.09.2026” (screening sprzed zatrudnienia). Decyzje Artura D1–D6: termin
z umowy (późniejsza z dat: dzień po końcu pracy u nas i data z profilu),
„Stawka od” = stawka z żywej umowy. Zapytania, wyzwalacze i filtr z bazą
sprawdza ``test_contract_availability_db.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import candidate_rate_from as rf
from app.services import contract_rate_from_schema as contract_schema
from app.services import scoring_service
from app.services.candidate_rate_observations import (
    CONTRACT_SOURCE,
    RateObservation,
    _contract_rate_since,
)
from app.services.contract_availability import (
    ATTRIBUTE,
    ContractFree,
    contract_free_by_clause,
    from_marker,
)
from app.services.employment_marker import ContractRow, SignalRow, build_markers

TODAY = date(2026, 10, 15)


def _contract(
    contract_id: int = 10,
    client_id: int = 100,
    start_date: date | None = date(2026, 9, 1),
    end_date: date | None = None,
    candidate_id: int = 1,
) -> ContractRow:
    return ContractRow(
        candidate_id,
        contract_id,
        client_id,
        f"Klient {client_id}",
        start_date,
        end_date,
    )


def _marker(contracts, order_ends=None):
    return build_markers(contracts, [], today=TODAY, order_ends=order_ends or {})[1]


# ── termin „wolny od” w znaczniku ───────────────────────────────────────────


def test_order_end_gives_the_day_after_as_free_from():
    marker = _marker([_contract()], {10: date(2026, 11, 30)})

    assert marker.free_from == date(2026, 12, 1)
    assert marker.free_from_basis == "work_end"


def test_two_clients_free_after_the_later_end():
    marker = _marker(
        [_contract(10, 100), _contract(11, 200)],
        {10: date(2026, 11, 30), 11: date(2026, 12, 31)},
    )

    assert marker.free_from == date(2027, 1, 1)
    assert marker.free_from_basis == "work_end"


def test_any_contract_without_end_means_no_end_date():
    marker = _marker([_contract(10, 100), _contract(11, 200)], {10: date(2026, 11, 30)})

    assert marker.free_from is None
    assert marker.free_from_basis == "no_end_date"


def test_follow_on_contract_at_the_same_client_keeps_the_person_with_us():
    # Wybór jednej umowy na klienta zostawia trwającą — reguła i tak widzi
    # kolejną umowę, więc osoba nie jest „wolna od 1.12”.
    marker = _marker(
        [_contract(10, 100), _contract(11, 100, start_date=date(2026, 12, 1))],
        {10: date(2026, 11, 30)},
    )

    assert [c.contract_id for c in marker.clients] == [10]
    assert marker.free_from is None
    assert marker.free_from_basis == "no_end_date"


def test_only_future_contracts_mean_starting():
    marker = _marker([_contract(start_date=date(2026, 11, 3))])

    assert marker.phase == "starting"
    assert marker.free_from is None
    assert marker.free_from_basis == "starting"


def test_finished_orders_give_a_past_free_from():
    marker = _marker([_contract()], {10: date(2026, 9, 30)})

    assert marker.free_from == date(2026, 10, 1)
    assert marker.free_from_basis == "work_end"


def test_contract_end_date_earlier_than_orders_wins():
    marker = _marker([_contract(end_date=date(2026, 10, 31))], {10: date(2026, 12, 31)})

    assert marker.free_from == date(2026, 11, 1)


@pytest.mark.parametrize("source", ["conflict", "pipeline"])
def test_signal_without_contract_has_no_free_from(source):
    marker = build_markers([], [SignalRow(1, source, 100, "Klient")], today=TODAY)[1]

    assert marker.free_from is None
    assert marker.free_from_basis is None
    assert from_marker(marker) is None


# ── termin = późniejsza z dat ───────────────────────────────────────────────


def test_screening_date_before_the_end_of_work_does_not_count():
    free = ContractFree(free_from=date(2026, 12, 1), basis="work_end")

    assert free.available_from(date(2026, 9, 1)) == date(2026, 12, 1)
    assert free.available_from(None) == date(2026, 12, 1)


def test_later_date_given_by_the_candidate_wins():
    free = ContractFree(free_from=date(2026, 12, 1), basis="work_end")

    assert free.available_from(date(2026, 12, 15)) == date(2026, 12, 15)


@pytest.mark.parametrize("basis", ["no_end_date", "starting"])
def test_without_end_or_before_start_there_is_no_date(basis):
    free = ContractFree(free_from=None, basis=basis)

    assert free.available_from(date(2027, 1, 1)) is None
    assert free.describe(None)


def test_from_marker_reads_the_contract_marker():
    marker = _marker([_contract()], {10: date(2026, 11, 30)})

    assert from_marker(marker) == ContractFree(date(2026, 12, 1), "work_end")


# ── filtr „Dostępny do daty” ────────────────────────────────────────────────


def test_filter_clause_excludes_people_held_by_a_live_contract():
    sql = str(
        contract_free_by_clause(1, date(2026, 11, 15), today=TODAY).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "NOT (EXISTS" in sql
    assert "contracts" in sql
    assert "start_date >" in sql


# ── ocena dopasowania ───────────────────────────────────────────────────────


def _candidate(availability_date=None, contract=None, attach=True):
    candidate = SimpleNamespace(
        availability_date=availability_date, cv_extracted_data=None
    )
    if attach:
        setattr(candidate, ATTRIBUTE, contract)
    return candidate


def _job(deadline=date(2026, 12, 1)):
    return SimpleNamespace(deadline=deadline, champion_profile=None)


# Domyślna waga dostępności bywa zerowa — test ocenia samą warstwę.
_PROFILE = scoring_service.WeightProfile(availability=5.0)


def test_scoring_uses_the_contract_date_not_the_old_screening():
    candidate = _candidate(
        date(2026, 9, 1), ContractFree(date(2026, 12, 20), "work_end")
    )

    layer = scoring_service._score_availability(candidate, _job(), _PROFILE)

    assert 0 < layer.points < layer.max_points
    assert layer.reason == "spóźnienie 19 dni (z umowy)"


def test_scoring_gives_zero_without_end_date():
    candidate = _candidate(date(2026, 9, 1), ContractFree(None, "no_end_date"))

    layer = scoring_service._score_availability(candidate, _job(), _PROFILE)

    assert layer.points == 0
    assert layer.scored
    assert "bez daty końca" in layer.reason


def test_scoring_without_contract_keeps_the_profile_date():
    on_time = scoring_service._score_availability(
        _candidate(date(2026, 9, 1), None), _job(), _PROFILE
    )
    not_attached = scoring_service._score_availability(
        _candidate(date(2026, 9, 1), attach=False), _job(), _PROFILE
    )

    assert on_time.points == on_time.max_points == 5.0
    assert not_attached.points == not_attached.max_points == 5.0


def test_champion_start_collides_with_a_contract_without_end(monkeypatch):
    monkeypatch.setattr(scoring_service, "_availability_conflict_enabled", lambda: True)
    job = SimpleNamespace(deadline=None, champion_profile={"start_date": "2026-11-01"})
    candidate = _candidate(None, ContractFree(None, "no_end_date"))

    factor, reason = scoring_service._champion_availability_conflict_factor(
        candidate, job, today=TODAY
    )

    assert factor < 1.0
    assert "bez daty końca" in reason


def test_scoring_version_names_the_contract_rule():
    assert scoring_service.scoring_algorithm_version()


# ── „Stawka od” z żywej umowy ───────────────────────────────────────────────


def _at(y: int, m: int, d: int = 15) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def _obs(key: str, amount, at: datetime, source: str = "card", **kw):
    return RateObservation(
        key=key,
        candidate_id=1,
        amount_hourly=Decimal(str(amount)),
        raw=None,
        at=at,
        source=source,
        **kw,
    )


def test_live_contract_rate_overrides_screening_and_profile():
    contract = _obs("contract:10", 150, _at(2024, 3, 1), source=CONTRACT_SOURCE)
    result = rf.compute(
        [
            contract,
            _obs("card:1", 130, _at(2026, 8)),
            # Stawka profilu z datą importu — późniejsza niż start umowy.
            _obs("profile-current", 120, _at(2026, 10, 1), source="profile"),
        ],
        set(),
        TODAY,
    )

    assert result.amount == Decimal("150")
    assert result.source == CONTRACT_SOURCE
    assert result.key == "contract:10"
    assert result.stale is False
    assert result.latest_amount == Decimal("150")
    assert result.reasons == {
        "contract:10": rf.REASON_MINIMUM,
        "card:1": rf.REASON_CONTRACT,
        "profile-current": rf.REASON_CONTRACT,
    }


def test_without_contract_the_rule_is_unchanged():
    result = rf.compute(
        [_obs("card:1", 130, _at(2026, 8)), _obs("card:2", 140, _at(2026, 9))],
        set(),
        TODAY,
    )

    assert result.amount == Decimal("130")
    assert result.source == "card"


def test_rate_since_is_the_latest_schedule_step_in_force():
    contract = SimpleNamespace(
        start_date=date(2025, 1, 1),
        candidate_rate_schedule=[
            SimpleNamespace(effective_from=date(2025, 1, 1), id=1),
            SimpleNamespace(effective_from=date(2026, 7, 1), id=2),
            SimpleNamespace(effective_from=date(2027, 1, 1), id=3),
        ],
    )

    assert _contract_rate_since(contract, TODAY) == date(2026, 7, 1)
    assert _contract_rate_since(
        SimpleNamespace(start_date=date(2025, 1, 1), candidate_rate_schedule=[]),
        TODAY,
    ) == date(2025, 1, 1)


def test_rate_summary_carries_the_source():
    computed = SimpleNamespace(
        rate_from_computed_at=_at(2026, 10),
        rate_from_hourly=Decimal("150"),
        rate_from_at=_at(2026, 9),
        rate_from_stale=False,
        rate_latest_hourly=Decimal("150"),
        rate_latest_at=_at(2026, 9),
        rate_observation_count=3,
        rate_from_source=CONTRACT_SOURCE,
        expected_rate_hourly=Decimal("130"),
        expected_rate_currency="PLN",
    )

    assert rf.rate_summary(computed)["rate_from_source"] == CONTRACT_SOURCE


# ── wyzwalacze i entrypoint ─────────────────────────────────────────────────


def test_contract_triggers_have_no_bind_colons_and_no_column_lists():
    assert contract_schema.BACKFILL_MARKER in contract_schema.BACKFILL_DDL[0]
    for stmt in contract_schema.ALL_DDL:
        # entrypoint wykonuje instrukcje wprost — dwukropek byłby parametrem.
        assert ":" not in stmt.replace("::", ""), stmt[:60]
        # Entrypoint poszerza kolumny stawek — lista kolumn w wyzwalaczu
        # zablokowałaby ALTER TYPE.
        assert "UPDATE OF" not in stmt, stmt[:60]
    body = contract_schema.TRIGGER_DDL[0]
    for column in ("status", "rate_candidate", "rate_unit", "start_date"):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in body


def test_entrypoint_wires_contract_triggers_after_the_enqueue_function():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()

    assert (
        "from app.services import contract_rate_from_schema as _contract_rate_from"
        in entrypoint
    )
    assert entrypoint.index("*_RATE_FROM_DDL,") < entrypoint.index(
        "*_CONTRACT_RATE_FROM_DDL,"
    )
    assert "*_CONTRACT_RATE_FROM_BACKFILL," in entrypoint


@pytest.mark.asyncio
async def test_window_requeue_skips_contract_rates():
    seen: list[str] = []

    class _Db:
        async def execute(self, statement, params=None):
            seen.append(str(statement))
            return SimpleNamespace(rowcount=0)

    await rf.requeue_expiring(_Db(), today=TODAY)
    await rf.requeue_live_contracts(_Db())

    assert "rate_from_source IS DISTINCT FROM 'contract'" in seen[0]
    assert "FROM contracts" in seen[1]
