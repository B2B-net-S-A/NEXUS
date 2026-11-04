"""„Pracuje u nas” — stare pole ``employment`` i filtr listy mówią to samo co
znacznik — bez bazy.

14.10.2026 (WS14) wyrównało pole ``employment`` (``_derive_employment``)
i filtr ``employment=at_client`` / ``available`` (``_at_client_predicate``)
ze znacznikiem przy starym etapie „Zatrudniony”. Od 17.10.2026 (decyzja
Artura) wszystkie trzy czytają wyłącznie żywą umowę: etap „Zatrudniony” bez
umowy i ręczny konflikt ``current_employment`` nie dają „zatrudniony”.

Wariant z bazą: ``test_employment_marker.py::
test_list_marker_exists_exactly_when_employment_says_employed`` (CI).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.candidate_conflict import ConflictType
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


def _candidate(*, contracts=(), stages=(), conflicts=()):
    return SimpleNamespace(
        id=1,
        contracts=list(contracts),
        conflicts=list(conflicts),
        pipeline_stages=list(stages),
    )


def test_former_consultant_is_not_employed_in_the_old_field():
    """Zatrudniony w 2022, umowa u tego klienta zakończona w 2024."""
    from app.api.candidates import _derive_employment

    candidate = _candidate(
        contracts=[_contract(10, ContractStatus.ended, end_date=date(2024, 6, 30))],
        stages=[_hire(1, 40, BANK, datetime(2022, 3, 1, 9, tzinfo=timezone.utc))],
    )

    assert _derive_employment(candidate).state == EmploymentState.on_bench
    assert rows_from_candidate(candidate) == []


def test_fresh_hire_without_a_contract_is_not_employed():
    """Ręczne „Potwierdź zatrudnienie” wczoraj, umowy jeszcze nie ma — do
    17.10.2026 to było „Pracuje u nas” przez 12 miesięcy."""
    from app.api.candidates import _derive_employment

    candidate = _candidate(
        stages=[_hire(1, 40, BANK, datetime.now(timezone.utc) - timedelta(days=1))],
    )

    employment = _derive_employment(candidate)

    assert employment.state == EmploymentState.on_bench
    assert employment.source == "none"
    assert rows_from_candidate(candidate) == []


def test_manual_employment_conflict_is_not_employment():
    from app.api.candidates import _derive_employment

    candidate = _candidate(
        conflicts=[
            SimpleNamespace(
                client_id=TELEKOM.id,
                client=TELEKOM,
                active=True,
                type=ConflictType.current_employment,
            )
        ],
    )

    assert _derive_employment(candidate).state == EmploymentState.on_bench
    assert rows_from_candidate(candidate) == []


def test_live_contract_is_employment_in_both_places():
    from app.api.candidates import _derive_employment

    candidate = _candidate(
        contracts=[_contract(10, ContractStatus.active, client=TELEKOM)],
        stages=[_hire(1, 40, BANK, datetime.now(timezone.utc) - timedelta(days=1))],
    )

    employment = _derive_employment(candidate)

    assert employment.state == EmploymentState.employed_at_client
    assert (employment.client_id, employment.source) == (TELEKOM.id, "contract")
    assert [row.client_id for row in rows_from_candidate(candidate)] == [TELEKOM.id]


def test_list_filter_reads_only_live_contracts():
    """``employment=at_client`` / ``available`` — ta sama reguła co znacznik."""
    from app.api import candidates as candidates_api

    sql = str(candidates_api._at_client_predicate())

    assert "contracts" in sql
    assert "candidate_stages" not in sql
    assert "candidate_conflicts" not in sql
