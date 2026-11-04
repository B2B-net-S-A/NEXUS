"""Kolizja e-maila w fazie `candidates` nie wstrzymuje `__daily__` (05.10.2026).

Produkcja 05.10.2026: `__daily__.last_synced_at` stał na 2026-09-28, każdy bieg
kończył się `errors`, a jedyną fazą z błędami były `candidates` — 34 wpisy
`email_collision candidate ext=…: mail należy do kandydata id=…`. Kwarantanna
(`TRAFFIT_MAX_ROW_ATTEMPTS`) miała 2 wpisy, bo licznik prób zeruje się w biegu,
który wiersza nie obejrzał (`_next_quarantine`: nieobecny = „zaimportował się”):
delta widzi wiersz tylko po zmianie u źródła, a wznowienie z kursora oddaje
błędy wcześniejszych stron jako NIEPRZYPISANE.

Kolizja to stan danych (dwie kartoteki osoby w Traffit albo duplikat
w NEXUSIE) — ponowienie jej nie naprawi. Jest więc doradcza: licznik i pary
samych identyfikatorów w statystykach fazy i w `/sync/status`, bez wstrzymania
watermarku. Każdy inny błąd fazy blokuje jak dotąd.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import traffit_status
from app.services.traffit.importer import _MAX_EMAIL_COLLISIONS, PhaseProgress
from app.tasks.traffit_sync import DAILY_MARKER, _summarize
from tests.test_traffit_watermark_on_failure import _marker_call, _run

UTC = timezone.utc


def _candidates_phase(*, collisions: int = 0, other_errors: tuple[str, ...] = ()):
    async def _factory():
        progress = PhaseProgress(phase="candidates")
        progress.processed = collisions + len(other_errors) + 10
        for n in range(collisions):
            progress.add_email_collision(35864 + n, 32144 + n)
        for msg in other_errors:
            progress.add_error(msg)
        progress.started_at = progress.finished_at = datetime.now(UTC)
        return progress

    return _factory


# ── PhaseProgress ────────────────────────────────────────────────────────────


def test_collision_is_not_an_error_and_has_no_row_ref() -> None:
    progress = PhaseProgress(phase="candidates")
    progress.add_email_collision("35864", 32144)

    assert progress.errors == 0
    assert progress.error_refs == set()
    assert progress.attributed_errors == 0
    assert progress.error_samples == []
    assert progress.email_collision_count == 1
    assert progress.email_collisions == [{"ext_id": "35864", "candidate_id": 32144}]


def test_collision_list_is_capped_but_the_count_is_not() -> None:
    progress = PhaseProgress(phase="candidates")
    for n in range(_MAX_EMAIL_COLLISIONS + 7):
        progress.add_email_collision(n, n + 1)

    assert progress.email_collision_count == _MAX_EMAIL_COLLISIONS + 7
    assert len(progress.email_collisions) == _MAX_EMAIL_COLLISIONS


def test_collisions_survive_a_resume_from_the_page_cursor() -> None:
    """Wiersze sprzed kursora nie wracają we wznowionym biegu — lista z kursora."""
    before = PhaseProgress(phase="candidates")
    before.add_email_collision("35864", 32144)
    before.add_email_collision("65891", 61002)

    resumed = PhaseProgress(phase="candidates")
    resumed.absorb_carried_collisions(before.collision_carry())
    resumed.add_email_collision("65904", 61010)

    assert resumed.errors == 0
    assert resumed.email_collision_count == 3
    assert [p["ext_id"] for p in resumed.email_collisions] == [
        "35864",
        "65891",
        "65904",
    ]


def test_absorb_ignores_garbage_from_the_cursor_jsonb() -> None:
    progress = PhaseProgress(phase="candidates")
    progress.absorb_carried_collisions(None)
    progress.absorb_carried_collisions({"count": "x"})
    progress.absorb_carried_collisions(
        {
            "count": 2,
            "pairs": ["bad", {"ext_id": "1"}, {"ext_id": "2", "candidate_id": 9}],
        }
    )

    assert progress.email_collision_count == 2
    assert progress.email_collisions == [{"ext_id": "2", "candidate_id": 9}]


def test_phase_summary_keeps_the_pairs_for_sync_status() -> None:
    progress = PhaseProgress(phase="candidates")
    progress.add_email_collision("35864", 32144)

    summary = _summarize(progress.as_dict())

    assert summary["email_collision_count"] == 1
    assert summary["email_collisions"] == [{"ext_id": "35864", "candidate_id": 32144}]
    assert summary["errors"] == 0


# ── Orkiestrator: watermark ──────────────────────────────────────────────────


async def test_collisions_alone_advance_the_daily_watermark(monkeypatch) -> None:
    upserts = await _run(
        monkeypatch,
        mode="delta",
        phases=[("candidates", _candidates_phase(collisions=34))],
    )

    daily = _marker_call(upserts, DAILY_MARKER)
    assert isinstance(daily.kwargs["last_synced_at"], datetime)
    # `checks.traffit` w /api/health czyta właśnie ten status `__daily__`.
    assert daily.kwargs["last_status"] == "ok"

    row = _marker_call(upserts, "candidates")
    assert row.kwargs["last_status"] == "ok"
    assert isinstance(row.kwargs["last_synced_at"], datetime)
    stats = row.kwargs["stats"]
    assert stats["email_collision_count"] == 34
    assert len(stats["email_collisions"]) == 34
    assert "blocking_errors" not in stats
    assert "quarantine" not in stats


async def test_collision_beside_another_row_error_still_holds_it(monkeypatch) -> None:
    upserts = await _run(
        monkeypatch,
        mode="delta",
        phases=[
            (
                "candidates",
                _candidates_phase(
                    collisions=3,
                    other_errors=("upsert candidate ext=70001: IntegrityError",),
                ),
            )
        ],
    )

    daily = _marker_call(upserts, DAILY_MARKER)
    assert daily.kwargs["last_synced_at"] is None
    assert daily.kwargs["last_status"] == "errors"

    row = _marker_call(upserts, "candidates")
    assert row.kwargs["last_status"] == "errors"
    stats = row.kwargs["stats"]
    assert stats["blocking_errors"] == 1
    assert stats["quarantine"] == {"candidate:70001": 1}
    # Kolizje widać obok, ale nie liczą się do blokady ani kwarantanny.
    assert stats["email_collision_count"] == 3


async def test_full_run_with_collisions_only_advances_both_markers(monkeypatch) -> None:
    from app.tasks.traffit_sync import FULL_MARKER

    upserts = await _run(
        monkeypatch,
        mode="full",
        phases=[("candidates", _candidates_phase(collisions=2))],
    )

    for marker in (DAILY_MARKER, FULL_MARKER):
        call = _marker_call(upserts, marker)
        assert isinstance(call.kwargs["last_synced_at"], datetime), marker
        assert call.kwargs["last_status"] == "ok", marker


# ── /sync/status ─────────────────────────────────────────────────────────────


async def test_sync_status_rolls_collisions_up_without_emails(monkeypatch) -> None:
    monkeypatch.setattr(traffit_status, "sync_is_running", lambda: False)
    finished = datetime(2026, 10, 5, 4, 50, tzinfo=UTC)
    rows = [
        SimpleNamespace(
            phase="candidates",
            last_synced_at=finished,
            last_run_started_at=finished,
            last_run_finished_at=finished,
            last_status="ok",
            cursor_at=None,
            cursor_payload=None,
            stats={
                "errors": 0,
                "email_collision_count": 2,
                "email_collisions": [
                    {"ext_id": "35864", "candidate_id": 32144},
                    {"ext_id": "65891", "candidate_id": 61002},
                ],
            },
        ),
        # Znacznik `__daily__` niesie słownik faz — nie jest liczony drugi raz.
        SimpleNamespace(
            phase=DAILY_MARKER,
            last_synced_at=finished,
            last_run_started_at=finished,
            last_run_finished_at=finished,
            last_status="ok",
            cursor_at=None,
            cursor_payload=None,
            stats={"candidates": {"email_collision_count": 2}},
        ),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(return_value=rows), scalar=AsyncMock(return_value=0)
    )

    result = await traffit_status.read_traffit_status(db)

    assert result["email_collision_count"] == 2
    assert result["email_collisions"] == [
        {
            "phase": "candidates",
            "ext_id": "35864",
            "candidate_id": 32144,
            "last_seen": finished.isoformat(),
        },
        {
            "phase": "candidates",
            "ext_id": "65891",
            "candidate_id": 61002,
            "last_seen": finished.isoformat(),
        },
    ]
    assert "@" not in repr(result["email_collisions"])
