"""Jedna globalna kolejność blokad dla operacji wielo-parowych.

Kolejność: **wszyscy kandydaci operacji (rosnąco po id) → dopiero potem oferty
(rosnąco po id) → reszta.** Wsadowy `sync_external_observed_processes` trzymał
się jej od początku; wywołujący w pętli (bulk-move, bulk-proposals) przeplatali
kandydat→oferta→kandydat, czyli czekali na kolejnego kandydata trzymając już
blokadę oferty — ABBA z wsadem Traffita. Bulk-proposals dodatkowo iterował
surową listę z requestu, więc dwa nakładające się requesty z odwróconą
kolejnością zakleszczały się o siebie.

Kolejność blokad testujemy strukturalnie (kolejność instrukcji / kształt
zapytania), nie wyścigiem — wyścig nie byłby deterministyczny, a kolejność
instrukcji jest dokładnie tym, co defekt naruszał.
"""

from __future__ import annotations

import inspect

from app.api import client_order_groups as order_groups_api
from app.api import contracts as contracts_api
from app.api import pipeline as pipeline_api
from app.api import proposals_bulk
from app.services import recruitment_process_commands as commands
from app.services.recruitment_process_commands import (
    canonical_candidate_lock_order,
    lock_candidates_stmt,
)


# ── faza 1: kanonizacja listy kandydatów ─────────────────────────────────────


def test_canonical_order_sorts_and_dedupes() -> None:
    assert canonical_candidate_lock_order([9, 5, 9, 1, 5]) == [1, 5, 9]


def test_canonical_order_is_stable_for_reversed_inputs() -> None:
    """Sedno P2-19: dwa requesty z odwróconą listą dostają tę samą kolejność."""

    assert canonical_candidate_lock_order([3, 7, 11]) == canonical_candidate_lock_order(
        [11, 7, 3]
    )


def test_canonical_order_accepts_any_iterable() -> None:
    assert canonical_candidate_lock_order(i for i in (4, 2, 4)) == [2, 4]


def test_lock_statement_is_ordered_and_locking() -> None:
    # Nie kompilujemy statementu: `compile()` konfiguruje WSZYSTKIE mappery
    # i wywraca się na niepowiązanym `CortexSkillFact -> Skill`. Kształt
    # (FOR UPDATE, ORDER BY, posortowane id) czytamy wprost ze statementu.
    stmt = lock_candidates_stmt([3, 1, 3])

    assert stmt._for_update_arg is not None
    assert [str(clause) for clause in stmt._order_by_clauses] == ["candidates.id"]
    assert stmt.whereclause.right.value == [1, 3]


# ── faza 2: wszyscy wywołujący trzymają się tej samej kolejności ─────────────


def test_batch_sync_locks_candidates_before_jobs() -> None:
    src = inspect.getsource(commands.sync_external_observed_processes)

    assert src.index("lock_candidates_stmt(") < src.index("select(Job)")


def test_bulk_move_locks_all_candidates_before_the_first_job_lock() -> None:
    src = inspect.getsource(pipeline_api.bulk_move_candidates)

    # `transition_process` bierze blokadę oferty; komplet kandydatów musi być
    # zablokowany wcześniej, inaczej pętla przeplata kandydat→oferta→kandydat.
    assert src.index("lock_candidates_stmt(") < src.index("transition_process(")
    assert "canonical_candidate_lock_order(data.candidate_ids)" in src


def test_bulk_add_proposals_locks_all_candidates_before_the_first_job_lock() -> None:
    src = inspect.getsource(proposals_bulk.bulk_add_proposals)

    assert src.index("canonical_candidate_lock_order(") < src.index("with_for_update()")
    assert src.index("with_for_update()") < src.index("open_process(")
    assert ".order_by(Candidate.id)" in src


def test_bulk_add_proposals_never_iterates_the_raw_client_list() -> None:
    src = inspect.getsource(proposals_bulk.bulk_add_proposals)

    assert "for candidate_id in body.candidate_ids:" not in src
    assert "for candidate_id in lock_ordered_ids:" in src


def test_bulk_contract_termination_uses_one_lock_order() -> None:
    src = inspect.getsource(contracts_api.bulk_mark_ended)

    assert src.index(".order_by(Contract.id.asc())") < src.index(
        "_apply_contract_status_change("
    )
    assert src.index(".with_for_update()") < src.index("_apply_contract_status_change(")
    assert "for c in sorted(contracts, key=lambda contract: contract.id):" in src


def test_md_offboarding_resolution_locks_source_and_target_in_one_order() -> None:
    src = inspect.getsource(order_groups_api.resolve_md_offboarding_case)
    line_lock = src.split("locked_lines_result = await db.execute(", 1)[1].split(
        "locked_lines = {", 1
    )[0]

    assert line_lock.index("ClientOrder.id.in_(line_ids)") < line_lock.index(
        ".order_by(ClientOrder.id.asc())"
    )
    assert line_lock.index(".order_by(ClientOrder.id.asc())") < line_lock.index(
        ".with_for_update()"
    )
    assert line_lock.index(".with_for_update()") < line_lock.index(
        ".execution_options(populate_existing=True)"
    )
    assert "target = locked_lines.get(payload.target_order_id)" in src
