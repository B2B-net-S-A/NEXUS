"""One unimportable row must not freeze the Traffit delta watermark.

The sync deliberately refuses to advance ``last_synced_at`` when rows failed,
so the next delta re-covers them instead of letting them age out of the ~48h
overlap window (M2-IMP-01). That is right, and it had no bound.

Measured on production 2026-07-27: ONE candidate (``ext=48895``, a colliding
e-mail on the unique ``ix_candidates_email``) had held ``__daily__`` at
2026-07-20 — seven days. Three consequences, in ascending order of damage:

1. the delta window grows every night, so "delta" drifts towards a full scan;
2. ``checks.traffit`` is stuck on ``degraded`` forever, so the signal is noise;
3. a genuinely NEW failure changes nothing visible, because the status already
   said "errors" — the alert had stopped carrying information.

So failures are now counted per row, and a row that fails
``TRAFFIT_MAX_ROW_ATTEMPTS`` times in a row is parked: still recorded, still
surfaced to an operator, but no longer blocking the other 179 287 records.
Parking is explicit and countable, which is the opposite of the silent loss
M2-IMP-01 exists to prevent.
"""

from __future__ import annotations

from app.services.traffit.importer import PhaseProgress
from app.tasks.traffit_sync import _blocking_errors, _next_quarantine


# ── Attributing an error to a source row ────────────────────────────────────


def test_row_key_is_read_out_of_the_message() -> None:
    """41 call sites build the message; only one place parses it back."""
    p = PhaseProgress(phase="candidates")
    p.add_error("upsert candidate ext=48895: IntegrityError('duplicate key')")
    p.add_error("map client id=123: ValueError('bad payload')")
    assert p.error_refs == {"candidate:48895", "client:123"}


def test_entity_is_part_of_the_key() -> None:
    """`candidate ext=7` and `stage ext=7` are different rows, not one."""
    p = PhaseProgress(phase="mixed")
    p.add_error("upsert candidate ext=7: boom")
    p.add_error("upsert stage ext=7: boom")
    assert p.error_refs == {"candidate:7", "stage:7"}


def test_unattributable_errors_produce_no_key() -> None:
    """A phase-level failure names no row, so it can never be quarantined."""
    p = PhaseProgress(phase="clients")
    p.add_error("total_count failed: TimeoutError()")
    assert p.errors == 1
    assert p.error_refs == set()


def test_error_refs_are_capped() -> None:
    """A systemically broken phase must not balloon the stats JSONB."""
    p = PhaseProgress(phase="stages")
    for i in range(600):
        p.add_error(f"upsert stage ext={i}: boom")
    assert p.errors == 600
    assert len(p.error_refs) == 500


# ── Counting consecutive failures ───────────────────────────────────────────


def test_repeat_failure_counts_up() -> None:
    q = _next_quarantine({"candidate:48895": 3}, ["candidate:48895"])
    assert q == {"candidate:48895": 4}


def test_recovered_row_is_forgotten() -> None:
    """Importing successfully once resets the row — no credit across runs.

    Without this a flaky row would accumulate towards quarantine over months
    of unrelated failures and get parked while it was actually fine.
    """
    q = _next_quarantine({"candidate:1": 4, "candidate:2": 1}, ["candidate:2"])
    assert q == {"candidate:2": 2}
    assert "candidate:1" not in q


def test_first_failure_starts_at_one() -> None:
    assert _next_quarantine(None, ["stage:9"]) == {"stage:9": 1}


# ── Deciding whether the watermark may advance ──────────────────────────────


def test_row_below_the_limit_still_blocks() -> None:
    """Keep re-covering while the failure might still be transient."""
    assert _blocking_errors(1, ["candidate:48895"], {"candidate:48895": 4}, 5) == 1


def test_row_at_the_limit_stops_blocking() -> None:
    """The whole point: 179 287 good rows stop waiting on one bad one."""
    assert _blocking_errors(1, ["candidate:48895"], {"candidate:48895": 5}, 5) == 0


def test_unattributable_error_always_blocks() -> None:
    """An error naming no row might be a brand-new fault.

    It must NOT ride in on a quarantined row's exemption — that would be the
    exact regression this whole mechanism is supposed to make impossible.
    """
    blocking = _blocking_errors(2, ["candidate:48895"], {"candidate:48895": 9}, 5)
    assert blocking == 1


def test_new_failure_blocks_even_beside_a_quarantined_row() -> None:
    """A fresh row appearing next to a parked one must still hold the line."""
    quarantine = {"candidate:48895": 9, "candidate:777": 1}
    blocking = _blocking_errors(2, ["candidate:48895", "candidate:777"], quarantine, 5)
    assert blocking == 1


def test_clean_phase_blocks_nothing() -> None:
    assert _blocking_errors(0, [], {}, 5) == 0


def test_one_row_failing_twice_does_not_invent_a_phantom_error() -> None:
    """Regresja z review #968 — mechanizm był cicho martwy.

    Jeden wiersz potrafi paść dwa razy w jednym runie (dotykają go dwie fazy
    albo jest ponowienie). Wtedy ``errors == 2``, a zbiór referencji ma JEDEN
    wpis. Liczenie ``total - len(error_refs)`` robiło z tego fantomowy błąd
    „nieprzypisany", który blokuje watermark ZAWSZE — więc kwarantanna nigdy
    by się nie zwolniła i cała ta maszyneria nie robiłaby nic.
    """
    refs = ["candidate:48895"]
    quarantined = {"candidate:48895": 9}

    # Bez poprawki: 2 - 1 = 1 → wiecznie zablokowane.
    assert _blocking_errors(2, refs, quarantined, 5, attributed_errors=2) == 0, (
        "zaparkowany wiersz, który padł dwukrotnie, nadal blokuje watermark"
    )

    # I ta sama para PONIŻEJ limitu wciąż blokuje — poprawka nie rozluźnia reguły.
    assert (
        _blocking_errors(2, refs, {"candidate:48895": 1}, 5, attributed_errors=2) == 1
    )


def test_attributed_count_is_taken_from_the_progress_not_the_set() -> None:
    """``PhaseProgress`` liczy przypisania osobno od zbioru referencji."""
    p = PhaseProgress(phase="candidates")
    p.add_error("upsert candidate ext=48895: boom")
    p.add_error("upsert candidate ext=48895: boom again")
    assert p.errors == 2
    assert p.error_refs == {"candidate:48895"}
    assert p.attributed_errors == 2, (
        "drugi błąd tego samego wiersza nie został policzony jako przypisany"
    )


def test_overflow_past_the_ref_cap_counts_as_unattributable() -> None:
    """500+ padających wierszy to awaria systemowa — watermark ma stać.

    Po przekroczeniu limitu referencji świadomie NIE zwiększamy licznika
    przypisań, więc nadmiar liczy się jako nieprzypisany i blokuje.
    """
    p = PhaseProgress(phase="stages")
    for i in range(600):
        p.add_error(f"upsert stage ext={i}: boom")
    assert p.attributed_errors == 500
    blocking = _blocking_errors(
        p.errors, sorted(p.error_refs), {}, 5, attributed_errors=p.attributed_errors
    )
    assert blocking > 0


def test_production_shape_unblocks_after_five_runs() -> None:
    """End-to-end on the measured prod case: 1 poison row, nothing else.

    Runs 1-4 keep the watermark frozen (the row might recover); run 5 parks it
    and the pipeline moves again.
    """
    quarantine: dict[str, int] = {}
    refs = ["candidate:48895"]
    blocked_runs = 0
    for _ in range(5):
        quarantine = _next_quarantine(quarantine, refs)
        if _blocking_errors(1, refs, quarantine, 5):
            blocked_runs += 1
    assert blocked_runs == 4, "should retry four times before parking"
    assert quarantine["candidate:48895"] == 5
    assert _blocking_errors(1, refs, quarantine, 5) == 0
