"""„Pracuje u nas” — stare pole ``employment`` i filtr listy mówią to samo co
znacznik (14.10.2026) — bez bazy.

WS07 wyłączył stary etap „Zatrudniony” przy umowie u tego klienta, która się
skończyła (``hire_closed_by_contract``), ale tylko w znaczniku. Pole
``employment`` (``_derive_employment``) i filtr ``employment=at_client`` /
``available`` (``_at_client_predicate``) dalej mówiły „zatrudniony” — znacznik
i stare pole sobie przeczyły, a niezmiennik pilnuje ich zgodności.

Wariant z bazą: ``test_employment_marker.py::
test_list_marker_exists_exactly_when_employment_says_employed`` (CI).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import literal_column

from app.models.contract import ContractStatus
from app.models.recruitment_pipeline import PipelineStage
from app.schemas.candidate import EmploymentState
from app.services.employment_marker import rows_from_candidate

BANK = SimpleNamespace(id=5, name="Bank Przykładowy", display_name=None)
TELEKOM = SimpleNamespace(id=7, name="Telekom Przykładowy", display_name=None)


def _contract(contract_id: int, status: ContractStatus, *, client=BANK, **dates):
    values = {
        "start_date": date(2022, 3, 1),
        "end_date": None,
        "terminated_at": None,
        "voided_at": None,
        **dates,
    }
    return SimpleNamespace(
        id=contract_id,
        client_id=client.id,
        client=client,
        job_id=None,
        status=status,
        **values,
    )


def _hire(stage_id: int, job_id: int, client, moved_at: datetime):
    return SimpleNamespace(
        id=stage_id,
        job_id=job_id,
        stage=PipelineStage.hired,
        moved_at=moved_at,
        job=SimpleNamespace(id=job_id, client_id=client.id, client=client),
    )


def _candidate(*, contracts=(), stages=()):
    return SimpleNamespace(
        id=1, contracts=list(contracts), conflicts=[], pipeline_stages=list(stages)
    )


def test_former_consultant_is_not_employed_in_the_old_field():
    """Zatrudniony w 2022, umowa u tego klienta zakończona w 2024."""
    from app.api.candidates import _derive_employment

    candidate = _candidate(
        contracts=[_contract(10, ContractStatus.ended, end_date=date(2024, 6, 30))],
        stages=[_hire(1, 40, BANK, datetime(2022, 3, 1, 9, tzinfo=timezone.utc))],
    )

    employment = _derive_employment(candidate)

    assert employment.state == EmploymentState.on_bench
    # Znacznik mówi to samo (brak sygnału „pipeline”).
    assert rows_from_candidate(candidate) == ([], [])


def test_rehire_after_an_old_contract_ended_is_still_employed():
    from app.api.candidates import _derive_employment

    candidate = _candidate(
        contracts=[
            _contract(
                10,
                ContractStatus.ended,
                start_date=date(2020, 1, 1),
                end_date=date(2021, 12, 31),
            )
        ],
        stages=[_hire(1, 40, BANK, datetime(2022, 3, 1, 9, tzinfo=timezone.utc))],
    )

    employment = _derive_employment(candidate)

    assert employment.state == EmploymentState.employed_at_client
    assert (employment.client_id, employment.source) == (BANK.id, "pipeline")


def test_open_hire_wins_over_a_newer_hire_closed_by_its_contract():
    """Nowszy „Zatrudniony” u banku jest historią — pracuje w telekomie."""
    from app.api.candidates import _derive_employment

    candidate = _candidate(
        contracts=[_contract(10, ContractStatus.ended, end_date=date(2024, 6, 30))],
        stages=[
            _hire(1, 40, BANK, datetime(2023, 3, 1, 9, tzinfo=timezone.utc)),
            _hire(2, 41, TELEKOM, datetime(2022, 3, 1, 9, tzinfo=timezone.utc)),
        ],
    )

    employment = _derive_employment(candidate)

    assert employment.state == EmploymentState.employed_at_client
    assert (employment.client_id, employment.job_id) == (TELEKOM.id, 41)
    _, signals = rows_from_candidate(candidate)
    assert [signal.client_id for signal in signals] == [TELEKOM.id]


def test_list_filter_reads_the_marker_signal(monkeypatch):
    """``employment=at_client`` / ``available`` biorą sygnał znacznika
    (``current_hired_signal_exists``), nie gołe „stoi na Zatrudniony”."""
    from app.api import candidates as candidates_api

    monkeypatch.setattr(
        candidates_api,
        "current_hired_signal_exists",
        lambda _candidate_id: literal_column("ws14_marker_signal"),
        raising=False,
    )

    assert "ws14_marker_signal" in str(candidates_api._at_client_predicate())
