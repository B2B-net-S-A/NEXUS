"""Znacznik „Pracuje u nas” po audycie 48 h (punkty 13 i 14, 14.10.2026) — bez bazy.

13. Stary etap „Zatrudniony” przy umowie, która się skończyła, dawał
    „Pracuje u nas” na zawsze (i dzwonek do Delivery Leada byłego klienta).
14. Wypowiedziana umowa z linią MD z budżetem i umowa po końcu ostatniego
    zamówienia wyglądały na „pracuje, zamówienie bez daty końca”.

Testy z bazą (zapytania i trasy) są w ``test_fix48_ws07_marker_db.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.models.contract import ContractStatus
from app.models.recruitment_pipeline import PipelineStage
from app.services.employment_marker import (
    ContractRow,
    OrderRow,
    build_markers,
    order_end_by_contract,
    rows_from_candidate,
)

TODAY = date(2026, 10, 13)
HIRED_AT = datetime(2022, 3, 1, 9, 0, tzinfo=timezone.utc)

BANK = SimpleNamespace(id=5, name="Bank Przykładowy", display_name=None)
TELEKOM = SimpleNamespace(id=7, name="Telekom Przykładowy", display_name=None)


def _contract(
    contract_id: int,
    status: ContractStatus,
    *,
    client=BANK,
    end_date: date | None = None,
    terminated_at: date | None = None,
    voided_at: datetime | None = None,
    start_date: date | None = date(2022, 3, 1),
):
    return SimpleNamespace(
        id=contract_id,
        client_id=client.id,
        client=client,
        status=status,
        start_date=start_date,
        end_date=end_date,
        terminated_at=terminated_at,
        voided_at=voided_at,
    )


def _hired_candidate(*contracts, client=BANK, hired_at: datetime = HIRED_AT):
    return SimpleNamespace(
        id=1,
        contracts=list(contracts),
        conflicts=[],
        pipeline_stages=[
            SimpleNamespace(
                id=1,
                job_id=40,
                stage=PipelineStage.hired,
                moved_at=hired_at,
                job=SimpleNamespace(client=client),
            )
        ],
    )


# ── 13: etap „Zatrudniony” nie jest już źródłem (17.10.2026) ────────────────


def test_hired_stage_never_gives_a_marker_whatever_the_contracts():
    """Audyt 13.10 zamykał stary „Zatrudniony” zakończoną umową; od 17.10.2026
    (decyzja Artura) etap w ogóle nie daje znacznika — zostają żywe umowy."""
    for contracts in (
        (_contract(10, ContractStatus.ended, end_date=date(2024, 6, 30)),),
        (
            _contract(
                10,
                ContractStatus.void,
                voided_at=datetime(2022, 4, 1, tzinfo=timezone.utc),
            ),
        ),
        (_contract(10, ContractStatus.ended, end_date=date(2021, 12, 31)),),
        (_contract(11, ContractStatus.ready_for_signature),),
        (),
    ):
        candidate = _hired_candidate(*contracts)

        assert rows_from_candidate(candidate) == []
        assert build_markers(rows_from_candidate(candidate), today=TODAY) == {}


# ── 14: data końca wypowiedzianej umowy i koniec łańcucha zamówień ──────────


def test_terminated_contract_with_an_open_md_line_shows_its_end_date():
    """Scenariusz audytu 2: umowa wypowiedziana do 23.10, linia MD z budżetem."""
    ends = order_end_by_contract(
        [OrderRow(10, date(2026, 12, 31), ending=False, md_open=True)]
    )
    row = ContractRow(1, 10, 5, "Bank", date(2025, 1, 1), end_date=date(2026, 10, 23))

    marker = build_markers([row], today=TODAY, order_ends=ends)[1]

    assert marker.phase == "ending"
    assert marker.clients[0].order_end_date == date(2026, 10, 23)


def test_contract_end_beyond_thirty_days_is_working_with_a_date():
    row = ContractRow(1, 10, 5, "Bank", date(2025, 1, 1), end_date=date(2027, 1, 31))

    marker = build_markers([row], today=TODAY)[1]

    assert marker.phase == "working"
    assert marker.clients[0].order_end_date == date(2027, 1, 31)


def test_earlier_of_order_end_and_contract_end_wins():
    row = ContractRow(1, 10, 5, "Bank", date(2025, 1, 1), end_date=date(2026, 11, 30))

    order_first = build_markers(
        [row], today=TODAY, order_ends={10: date(2026, 10, 31)}
    )[1]
    contract_first = build_markers(
        [row], today=TODAY, order_ends={10: date(2026, 12, 31)}
    )[1]

    assert order_first.clients[0].order_end_date == date(2026, 10, 31)
    assert contract_first.clients[0].order_end_date == date(2026, 11, 30)


def test_order_chain_that_already_ended_gives_its_last_day():
    """Scenariusz audytu 1: ostatnie zamówienie skończyło się wczoraj, umowa trwa."""
    ends = order_end_by_contract(
        [
            OrderRow(10, date(2026, 6, 30), ending=False, md_open=False, finished=True),
            OrderRow(
                10, date(2026, 10, 12), ending=False, md_open=False, finished=True
            ),
        ]
    )

    marker = build_markers(
        [ContractRow(1, 10, 5, "Bank", date(2025, 1, 1))],
        today=TODAY,
        order_ends=ends,
    )[1]

    assert ends == {10: date(2026, 10, 12)}
    assert marker.phase == "ending"
    assert marker.clients[0].order_end_date == date(2026, 10, 12)


def test_finished_orders_with_a_current_or_planned_one_do_not_end_the_chain():
    ends = order_end_by_contract(
        [
            OrderRow(10, date(2026, 9, 30), ending=False, md_open=False, finished=True),
            # Bieżące zamówienie bez daty końca albo zaplanowany szkic.
            OrderRow(10, None, ending=False, md_open=False),
            OrderRow(11, date(2026, 9, 30), ending=False, md_open=False, finished=True),
            OrderRow(11, date(2026, 11, 15), ending=True, md_open=False),
        ]
    )

    assert ends == {11: date(2026, 11, 15)}


def test_rows_from_candidate_carries_the_contract_end_date():
    candidate = SimpleNamespace(
        id=1,
        contracts=[
            _contract(
                10,
                ContractStatus.ending,
                end_date=date(2026, 10, 23),
                terminated_at=date(2026, 10, 1),
                start_date=date(2025, 1, 1),
            )
        ],
        conflicts=[],
        pipeline_stages=[],
    )

    contracts = rows_from_candidate(candidate)

    assert contracts == [
        ContractRow(
            1, 10, 5, "Bank Przykładowy", date(2025, 1, 1), end_date=date(2026, 10, 23)
        )
    ]
