"""Reordering a Traffit workflow's states must not deadlock the whole phase.

Observed on prod 2026-08-10: the `workflows` phase reported `errors: 1` with
`workflow:4` quarantined at **23 consecutive attempts**, sample:

    upsert workflow ext=4: IntegrityError(...UniqueViolationError...:
    duplicate key value violates unique constraint "uq_s...

`pipeline_stage_defs` carries two unique constraints per template —
`uq_stage_order_in_template (template_id, "order")` and
`uq_stage_name_in_template (template_id, name)` — while the importer upserts
each state SEPARATELY, keyed on `(external_source, external_id)`. Rewriting a
set of rows one at a time under a set-wide unique constraint only works if no
intermediate state collides, and a reorder in Traffit guarantees one: state B
takes order 3 while state A, which still holds order 3, has not been rewritten
yet. Postgres rejects the row mid-loop.

Two things then compounded it into total data loss for the phase:

1. The handler calls `self.db.rollback()`, which rolls back the SESSION — not
   a savepoint. The phase commits once at the very end, so one bad workflow
   discarded EVERY workflow already written in that run. `processed: 2,
   updated: 2, errors: 1` is not "1 of 2 failed"; it is "0 of 2 persisted".
2. `gone`/quarantine cannot help: the row is not transient, so 23 runs in a
   row wrote nothing and the failure never expired.

The fix defers both constraints to COMMIT so intermediate collisions inside
one workflow are legal, and wraps each workflow in a SAVEPOINT so a failure
costs that workflow only.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.traffit.importer import TraffitImporter


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


class _WorkflowTraffit:
    """Serves a fixed set of workflows, each with caller-chosen states."""

    def __init__(self, workflows: dict[str, list[dict]]):
        self.workflows = workflows
        self._http = object()

    async def total_count(self, path):
        return len(self.workflows)

    async def get_paginated(self, path, *, page_size=100, **kw):
        for wf_id in self.workflows:
            yield {"id": wf_id, "name": f"WF {wf_id}"}

    async def _get_raw(self, path, page=1, page_size=50):
        wf_id = path.rstrip("/").split("/")[-1]
        states = self.workflows[wf_id]

        class _R:
            status_code = 200

            @staticmethod
            def json():
                return {"id": wf_id, "name": f"WF {wf_id}", "states": states}

        return _R()


def _state(sid: str, name: str, order: int) -> dict:
    return {"id": sid, "name": name, "order": order, "sid": name.lower()}


async def _stage_rows(db, ext_wf: str) -> list[tuple]:
    rows = await db.execute(
        text(
            """
            SELECT d.external_id, d.name, d."order"
            FROM pipeline_stage_defs d
            JOIN pipeline_templates t ON t.id = d.template_id
            WHERE t.external_id = :e AND t.external_source = 'traffit'
            ORDER BY d."order"
            """
        ),
        {"e": ext_wf},
    )
    return [tuple(r) for r in rows]


@pytest.mark.asyncio
async def test_swapping_two_states_order_does_not_break_the_phase(db) -> None:
    """The exact prod shape: two states trade places between runs."""
    wf = f"wf-{uuid.uuid4().hex[:8]}"
    a, b = f"{wf}-a", f"{wf}-b"

    first = [_state(a, "Rozmowa", 1), _state(b, "Oferta", 2)]
    p1 = await TraffitImporter(
        _WorkflowTraffit({wf: first}), db, dry_run=False, batch_size=10
    ).import_workflows()
    assert p1.errors == 0
    assert await _stage_rows(db, wf) == [(a, "Rozmowa", 0), (b, "Oferta", 1)]

    # Traffit reorders: B now comes first. B wants order 0, which A still holds.
    second = [_state(b, "Oferta", 1), _state(a, "Rozmowa", 2)]
    p2 = await TraffitImporter(
        _WorkflowTraffit({wf: second}), db, dry_run=False, batch_size=10
    ).import_workflows()

    assert p2.errors == 0, f"reorder still fails: {p2.error_samples}"
    assert await _stage_rows(db, wf) == [(b, "Oferta", 0), (a, "Rozmowa", 1)]


@pytest.mark.asyncio
async def test_swapping_two_state_names_does_not_break_the_phase(db) -> None:
    """Same fault via the other constraint — names trade places while the
    `external_id` keys stay put, so `uq_stage_name_in_template` collides
    mid-loop. The in-batch `seen_names` dedup cannot see this: both names are
    distinct within the incoming payload."""
    wf = f"wf-{uuid.uuid4().hex[:8]}"
    a, b = f"{wf}-a", f"{wf}-b"

    first = [_state(a, "Etap I", 1), _state(b, "Etap II", 2)]
    await TraffitImporter(
        _WorkflowTraffit({wf: first}), db, dry_run=False, batch_size=10
    ).import_workflows()

    second = [_state(a, "Etap II", 1), _state(b, "Etap I", 2)]
    p2 = await TraffitImporter(
        _WorkflowTraffit({wf: second}), db, dry_run=False, batch_size=10
    ).import_workflows()

    assert p2.errors == 0, f"name swap still fails: {p2.error_samples}"
    assert await _stage_rows(db, wf) == [(a, "Etap II", 0), (b, "Etap I", 1)]


@pytest.mark.asyncio
async def test_one_bad_workflow_does_not_discard_the_others(db) -> None:
    """The amplifier, and the reason prod persisted NOTHING for 23 runs.

    A session-wide rollback in the per-workflow handler throws away every
    workflow already written in the same run, because the phase commits once
    at the end. Each workflow needs its own savepoint.
    """
    ok = f"wf-{uuid.uuid4().hex[:8]}"
    bad = f"wf-{uuid.uuid4().hex[:8]}"

    # `bad` carries a state with no id — `traffit_workflow_state_to_stage_def`
    # raises, so it fails for a reason unrelated to the constraints above.
    wfs = {
        ok: [_state(f"{ok}-a", "Rozmowa", 1)],
        bad: [{"name": "Bez id", "order": 1}],
    }
    progress = await TraffitImporter(
        _WorkflowTraffit(wfs), db, dry_run=False, batch_size=10
    ).import_workflows()

    assert progress.errors == 1
    # The healthy workflow survived the unhealthy one.
    assert await _stage_rows(db, ok) == [(f"{ok}-a", "Rozmowa", 0)]
    # …and the stats describe WRITES, not attempts. Counting inside the
    # savepoint is how prod came to report `updated: 2` for a run that
    # persisted nothing.
    assert progress.inserted + progress.updated == 1
    assert await _stage_rows(db, bad) == []


@pytest.mark.asyncio
async def test_state_retired_in_traffit_survives_and_is_rehomed(db) -> None:
    """A state removed in Traffit must NOT be deleted — `candidate_stages.
    stage_def_id` points at it, which is why the importer stopped doing
    DELETE+INSERT in the first place. It is re-homed after the live states so
    it stops occupying an order the live set now needs."""
    wf = f"wf-{uuid.uuid4().hex[:8]}"
    a, b = f"{wf}-a", f"{wf}-b"

    first = [_state(a, "Rozmowa", 1), _state(b, "Retired", 2)]
    await TraffitImporter(
        _WorkflowTraffit({wf: first}), db, dry_run=False, batch_size=10
    ).import_workflows()

    # Traffit drops B and adds C, which lands on B's old order.
    c = f"{wf}-c"
    second = [_state(a, "Rozmowa", 1), _state(c, "Nowy", 2)]
    p2 = await TraffitImporter(
        _WorkflowTraffit({wf: second}), db, dry_run=False, batch_size=10
    ).import_workflows()

    assert p2.errors == 0, f"retire+add still fails: {p2.error_samples}"
    assert await _stage_rows(db, wf) == [
        (a, "Rozmowa", 0),
        (c, "Nowy", 1),
        (b, "Retired", 2),  # kept, pushed behind the live ones
    ]


@pytest.mark.asyncio
async def test_live_state_reclaiming_a_retired_name_wins(db) -> None:
    """When a live state takes a retired state's name, the retired row yields
    — it is the stale one, and both cannot hold the name under
    `uq_stage_name_in_template`."""
    wf = f"wf-{uuid.uuid4().hex[:8]}"
    a, b = f"{wf}-a", f"{wf}-b"

    await TraffitImporter(
        _WorkflowTraffit({wf: [_state(a, "Start", 1), _state(b, "Feedback", 2)]}),
        db,
        dry_run=False,
        batch_size=10,
    ).import_workflows()

    # B disappears; A is renamed to B's old name.
    p2 = await TraffitImporter(
        _WorkflowTraffit({wf: [_state(a, "Feedback", 1)]}),
        db,
        dry_run=False,
        batch_size=10,
    ).import_workflows()

    assert p2.errors == 0, f"name reclaim still fails: {p2.error_samples}"
    assert await _stage_rows(db, wf) == [
        (a, "Feedback", 0),
        (b, f"Feedback (#{b})", 1),
    ]


@pytest.mark.asyncio
async def test_rerunning_an_unchanged_workflow_is_a_no_op(db) -> None:
    """The park/apply rewrite runs on EVERY sync, so it must be idempotent —
    otherwise the nightly delta would churn orders or names forever."""
    wf = f"wf-{uuid.uuid4().hex[:8]}"
    states = [
        _state(f"{wf}-a", "Rozmowa", 1),
        _state(f"{wf}-b", "Oferta", 2),
        _state(f"{wf}-c", "Zatrudniony", 3),
    ]
    traffit = _WorkflowTraffit({wf: states})

    await TraffitImporter(traffit, db, dry_run=False, batch_size=10).import_workflows()
    first = await _stage_rows(db, wf)
    await TraffitImporter(traffit, db, dry_run=False, batch_size=10).import_workflows()

    assert await _stage_rows(db, wf) == first


@pytest.mark.asyncio
async def test_duplicate_names_within_one_workflow_still_deduped(db) -> None:
    """Regression guard for the existing `seen_names` suffixing — Traffit's B2B
    workflow really does ship two states called "Zaakceptowany"."""
    wf = f"wf-{uuid.uuid4().hex[:8]}"
    a, b = f"{wf}-a", f"{wf}-b"

    states = [_state(a, "Zaakceptowany", 1), _state(b, "Zaakceptowany", 2)]
    progress = await TraffitImporter(
        _WorkflowTraffit({wf: states}), db, dry_run=False, batch_size=10
    ).import_workflows()

    assert progress.errors == 0
    rows = await _stage_rows(db, wf)
    assert [r[1] for r in rows] == ["Zaakceptowany", f"Zaakceptowany (#{b})"]
