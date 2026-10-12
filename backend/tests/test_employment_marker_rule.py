"""Reguła znacznika „Pracuje u nas” — część czysta, bez bazy (12.10.2026).

Jedna funkcja ``build_markers`` rozstrzyga fazę (pracuje / kończy / zaczyna),
źródło i klientów dla każdego ekranu. Zapytania i pole w odpowiedziach API
sprawdza ``test_employment_marker.py`` (z bazą).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.candidate_conflict import ConflictType
from app.models.contract import ContractStatus
from app.models.recruitment_pipeline import PipelineStage
from app.services.employment_marker import (
    ContractRow,
    OrderRow,
    SignalRow,
    build_markers,
    marker_client_ids,
    order_end_by_contract,
    rows_from_candidate,
)

TODAY = date(2026, 10, 12)


def _contract(
    candidate_id: int = 1,
    contract_id: int = 10,
    client_id: int | None = 100,
    client_name: str | None = "Bank Przykładowy",
    start_date: date | None = date(2025, 3, 1),
) -> ContractRow:
    return ContractRow(candidate_id, contract_id, client_id, client_name, start_date)


def _signal(
    source: str,
    candidate_id: int = 1,
    client_id: int | None = 200,
    client_name: str | None = "Telekom Przykładowy",
) -> SignalRow:
    return SignalRow(candidate_id, source, client_id, client_name)  # type: ignore[arg-type]


# ── fazy z umowy ────────────────────────────────────────────────────────────


def test_live_contract_without_order_end_is_working_without_a_date():
    marker = build_markers([_contract()], [], today=TODAY)[1]

    assert marker.phase == "working"
    assert marker.source == "contract"
    assert marker.elsewhere is None
    assert [c.model_dump() for c in marker.clients] == [
        {
            "client_id": 100,
            "client_name": "Bank Przykładowy",
            "contract_id": 10,
            "phase": "working",
            "order_end_date": None,
            "starts_on": None,
            "delivery_lead_name": None,
        }
    ]


@pytest.mark.parametrize(
    "days_left, phase",
    [(0, "ending"), (30, "ending"), (31, "working"), (400, "working")],
)
def test_ending_means_order_chain_ends_within_thirty_days(days_left, phase):
    end = TODAY + timedelta(days=days_left)

    marker = build_markers([_contract()], [], today=TODAY, order_ends={10: end})[1]

    assert marker.phase == phase
    assert marker.clients[0].phase == phase
    # Data jest w znaczniku także w fazie „pracuje” — pigułka pokazuje „do …”.
    assert marker.clients[0].order_end_date == end


def test_contract_starting_in_the_future_is_starting_not_working():
    start = TODAY + timedelta(days=20)

    marker = build_markers(
        [_contract(start_date=start)],
        [],
        today=TODAY,
        # Zamówienie umowy, która jeszcze nie ruszyła, nie daje „kończy”.
        order_ends={10: TODAY + timedelta(days=5)},
    )[1]

    assert marker.phase == "starting"
    assert marker.clients[0].starts_on == start
    assert marker.clients[0].order_end_date is None


def test_signed_contract_beats_the_hired_stage_at_the_same_client():
    """Podpis w Generatorze: umowa aktywna od razu, start później, karta na
    „Zatrudniony”. Znacznik mówi „zaczyna”, a nie „pracuje”."""
    start = TODAY + timedelta(days=1)

    marker = build_markers(
        [_contract(start_date=start)],
        [_signal("pipeline", client_id=100, client_name="Bank Przykładowy")],
        today=TODAY,
    )[1]

    assert (marker.source, marker.phase) == ("contract", "starting")
    assert len(marker.clients) == 1


def test_contract_without_client_still_gives_a_marker():
    """Stare pole mówi „zatrudniony” przy każdej żywej umowie — znacznik też."""
    marker = build_markers(
        [_contract(client_id=None, client_name=None)], [], today=TODAY
    )[1]

    assert marker.phase == "working"
    assert marker.clients[0].client_id is None


# ── kilku klientów ──────────────────────────────────────────────────────────


def test_two_clients_working_wins_and_goes_first():
    marker = build_markers(
        [
            _contract(contract_id=11, client_id=101, client_name="Zeta"),
            _contract(contract_id=12, client_id=102, client_name="Alfa"),
        ],
        [],
        today=TODAY,
        order_ends={12: TODAY + timedelta(days=10)},
    )[1]

    assert marker.phase == "working"
    assert [(c.client_name, c.phase) for c in marker.clients] == [
        ("Zeta", "working"),
        ("Alfa", "ending"),
    ]


def test_working_now_and_starting_elsewhere_lists_both():
    marker = build_markers(
        [
            _contract(contract_id=11, client_id=101, client_name="Obecny"),
            _contract(
                contract_id=12,
                client_id=102,
                client_name="Nowy",
                start_date=TODAY + timedelta(days=14),
            ),
        ],
        [],
        today=TODAY,
    )[1]

    assert marker.phase == "working"
    assert [(c.client_name, c.phase) for c in marker.clients] == [
        ("Obecny", "working"),
        ("Nowy", "starting"),
    ]


def test_only_ending_clients_make_the_marker_ending():
    marker = build_markers(
        [_contract()], [], today=TODAY, order_ends={10: TODAY + timedelta(days=3)}
    )[1]

    assert marker.phase == "ending"


def test_two_contracts_at_one_client_keep_the_one_that_lasts():
    marker = build_markers(
        [
            _contract(contract_id=11),
            _contract(contract_id=12),
        ],
        [],
        today=TODAY,
        order_ends={11: TODAY + timedelta(days=7)},
    )[1]

    assert len(marker.clients) == 1
    assert marker.clients[0].contract_id == 12
    assert marker.clients[0].phase == "working"


# ── starsze sygnały ─────────────────────────────────────────────────────────


def test_manual_conflict_gives_working_without_dates():
    marker = build_markers([], [_signal("conflict")], today=TODAY)[1]

    assert (marker.source, marker.phase) == ("conflict", "working")
    assert marker.clients[0].contract_id is None
    assert marker.clients[0].order_end_date is None


def test_hired_stage_gives_working_from_the_pipeline():
    marker = build_markers([], [_signal("pipeline")], today=TODAY)[1]

    assert (marker.source, marker.phase) == ("pipeline", "working")


def test_source_order_is_contract_then_conflict_then_pipeline():
    markers = build_markers(
        [_contract(candidate_id=1)],
        [
            _signal("conflict", candidate_id=1, client_id=201),
            _signal("pipeline", candidate_id=1, client_id=202),
            _signal("conflict", candidate_id=2, client_id=201),
            _signal("pipeline", candidate_id=2, client_id=202),
            _signal("pipeline", candidate_id=3, client_id=202),
        ],
        today=TODAY,
    )

    assert {cid: m.source for cid, m in markers.items()} == {
        1: "contract",
        2: "conflict",
        3: "pipeline",
    }
    # Niższe źródło nie dokleja klientów do wyższego.
    assert [c.client_id for c in markers[1].clients] == [100]
    assert [c.client_id for c in markers[2].clients] == [201]


def test_repeated_signal_for_one_client_is_listed_once():
    marker = build_markers(
        [],
        [_signal("pipeline"), _signal("pipeline")],
        today=TODAY,
    )[1]

    assert len(marker.clients) == 1


def test_person_without_any_signal_has_no_entry():
    assert build_markers([], [], today=TODAY) == {}


# ── klient rekrutacji i Delivery Lead ───────────────────────────────────────


@pytest.mark.parametrize(
    "family, expected",
    [(None, None), ({100, 105}, False), ({300}, True), (set(), True)],
)
def test_elsewhere_compares_with_the_job_client_family(family, expected):
    marker = build_markers([_contract()], [], today=TODAY, job_client_ids=family)[1]

    assert marker.elsewhere is expected


def test_elsewhere_is_true_when_any_client_is_outside_the_family():
    marker = build_markers(
        [
            _contract(contract_id=11, client_id=100),
            _contract(contract_id=12, client_id=300, client_name="Inny"),
        ],
        [],
        today=TODAY,
        job_client_ids={100},
    )[1]

    assert marker.elsewhere is True


def test_delivery_lead_name_comes_from_the_client_map():
    markers = build_markers(
        [_contract(candidate_id=1)],
        [_signal("conflict", candidate_id=2, client_id=200)],
        today=TODAY,
        leads={100: "Karol Wzorcowy", 200: "Olga Wzorcowa"},
    )

    assert markers[1].clients[0].delivery_lead_name == "Karol Wzorcowy"
    assert markers[2].clients[0].delivery_lead_name == "Olga Wzorcowa"


def test_marker_client_ids_skips_rows_without_a_client():
    assert marker_client_ids(
        [_contract(client_id=100), _contract(client_id=None)],
        [_signal("pipeline", client_id=200), _signal("conflict", client_id=None)],
    ) == {100, 200}


# ── koniec łańcucha zamówień ────────────────────────────────────────────────


def test_order_end_is_the_earliest_ending_order_of_the_contract():
    ends = order_end_by_contract(
        [
            OrderRow(10, date(2026, 12, 31), ending=True, md_open=False),
            OrderRow(10, date(2026, 11, 30), ending=True, md_open=False),
            # Zamówienie z kontynuacją nie wyznacza końca współpracy.
            OrderRow(10, date(2026, 10, 31), ending=False, md_open=False),
            OrderRow(11, date(2026, 10, 31), ending=False, md_open=False),
        ]
    )

    assert ends == {10: date(2026, 11, 30)}


def test_open_md_budget_line_removes_the_end_date():
    """Aktywna linia MD z budżetem pracuje do wyczerpania, nie do kalendarza."""
    ends = order_end_by_contract(
        [
            OrderRow(10, date(2026, 10, 31), ending=True, md_open=False),
            OrderRow(10, date(2026, 12, 31), ending=False, md_open=True),
        ]
    )

    assert ends == {}


def test_order_without_end_date_never_sets_one():
    assert order_end_by_contract([OrderRow(10, None, ending=True, md_open=False)]) == {}


# ── wiersze z relacji wczytanych przez listę kandydatów ─────────────────────


def _client(client_id: int, name: str, display_name: str | None = None):
    return SimpleNamespace(id=client_id, name=name, display_name=display_name)


def _stage(stage_id: int, job_id: int, stage: PipelineStage, minute: int, client=None):
    return SimpleNamespace(
        id=stage_id,
        job_id=job_id,
        stage=stage,
        moved_at=datetime(2026, 10, 1, 12, minute, tzinfo=timezone.utc),
        job=SimpleNamespace(client=client),
    )


def test_rows_from_candidate_reads_live_contracts_conflicts_and_current_hired():
    bank = _client(100, "bank-zrodlowy", display_name="Bank Przykładowy")
    telekom = _client(200, "Telekom Przykładowy")
    candidate = SimpleNamespace(
        id=7,
        contracts=[
            SimpleNamespace(
                id=10,
                client_id=100,
                client=bank,
                status=ContractStatus.ending,
                start_date=date(2025, 3, 1),
            ),
            # Szkic i zakończona umowa nie są zatrudnieniem.
            SimpleNamespace(
                id=11,
                client_id=200,
                client=telekom,
                status=ContractStatus.draft,
                start_date=None,
            ),
            SimpleNamespace(
                id=12,
                client_id=200,
                client=telekom,
                status=ContractStatus.ended,
                start_date=date(2024, 1, 1),
            ),
        ],
        conflicts=[
            SimpleNamespace(
                client_id=200,
                client=telekom,
                active=True,
                type=ConflictType.current_employment,
            ),
            SimpleNamespace(
                client_id=200,
                client=telekom,
                active=False,
                type=ConflictType.current_employment,
            ),
            SimpleNamespace(
                client_id=200, client=telekom, active=True, type=ConflictType.nda
            ),
        ],
        pipeline_stages=[
            # Rekrutacja 1: dziś „Zatrudniony”.
            _stage(1, 1, PipelineStage.screening, 0, telekom),
            _stage(2, 1, PipelineStage.hired, 5, telekom),
            # Rekrutacja 2: był „Zatrudniony”, potem ruch dalej — nie liczy się.
            _stage(3, 2, PipelineStage.hired, 1, bank),
            _stage(4, 2, PipelineStage.withdrawn, 9, bank),
        ],
    )

    contracts, signals = rows_from_candidate(candidate)

    assert contracts == [ContractRow(7, 10, 100, "Bank Przykładowy", date(2025, 3, 1))]
    assert signals == [
        SignalRow(7, "conflict", 200, "Telekom Przykładowy"),
        SignalRow(7, "pipeline", 200, "Telekom Przykładowy"),
    ]


def test_rows_from_candidate_handles_empty_relations():
    candidate = SimpleNamespace(
        id=1, contracts=None, conflicts=None, pipeline_stages=None
    )

    assert rows_from_candidate(candidate) == ([], [])
