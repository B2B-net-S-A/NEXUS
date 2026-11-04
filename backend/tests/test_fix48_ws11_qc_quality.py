"""„Jakość QC” (D6): trafność i automat stanów — testy bez bazy (audyt 48 h).

Reguła: `docs/claude/rekrutacja-tablica/qc-to-nieprawda-i-jakosc-qc.md`.
Uwaga z trafnością < 70% przy ≥ 30 pokazanych staje się informacją i wraca,
gdy trafność wzrośnie; blokada nigdy nie przechodzi sama — poniżej 90% jedno
powiadomienie do adminów na serię.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import qc_quality

NOW = datetime(2026, 10, 14, 6, tzinfo=timezone.utc)
WARNING = "must_bolded"
BLOCKING = "critical_skills"


def test_keys_used_here_are_real_checks() -> None:
    blocking, warnings = qc_quality._keys()
    assert BLOCKING in blocking and WARNING in warnings


# ── report ───────────────────────────────────────────────────────────────────


class _Db:
    """Dwa zapytania `report`: przebiegi z oknem, potem trwające pominięcia."""

    def __init__(self, runs: list, dismissals: list) -> None:
        self._answers = [runs, dismissals]
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return iter(self._answers[len(self.statements) - 1])


def _run(candidate_id: int, items: list[str], dismissed: list[str] = ()) -> tuple:
    check = {
        "key": WARNING,
        "items": [{"key": k} for k in items],
        "dismissed_items": [{"key": k} for k in dismissed],
    }
    return (candidate_id, 50, {"checks": [check]})


@pytest.mark.asyncio
async def test_report_counts_distinct_items_and_only_qc_is_wrong_reasons() -> None:
    runs = [
        _run(1, ["a", "b"]),
        # Ten sam przebieg po pominięciu: pozycja „a” jest teraz obok — dalej
        # to jedna pokazana pozycja, nie dwie.
        _run(1, ["b"], dismissed=["a"]),
        _run(2, ["a", "c", "d"]),
    ]
    dismissals = [
        (1, 50, WARNING, "a", "in_cv"),
        (2, 50, WARNING, "c", "not_needed"),  # decyzja rekrutera, nie błąd QC
        (2, 50, WARNING, "d", "other_name"),
    ]
    db = _Db(runs, dismissals)
    out = await qc_quality.report(db, now=NOW)
    stats = out[WARNING]
    assert stats["shown"] == 5  # (1,a) (1,b) (2,a) (2,c) (2,d)
    assert stats["dismissed_wrong"] == 2
    assert stats["precision"] == 0.6
    assert stats["reasons"] == {"in_cv": 1, "not_needed": 1, "other_name": 1}
    assert stats["blocking"] is False
    assert out[BLOCKING]["shown"] == 0 and out[BLOCKING]["precision"] is None
    # Przywrócone pominięcia (rekruter albo zwrot karty) nie są dowodem.
    sql = str(db.statements[1].compile(dialect=postgresql.dialect()))
    assert "cv_finding_dismissals.restored_at IS NULL" in sql


@pytest.mark.asyncio
async def test_report_ignores_a_dismissal_of_an_item_never_shown_in_the_window() -> (
    None
):
    db = _Db([_run(1, ["a"])], [(1, 50, WARNING, "z", "in_cv")])
    stats = (await qc_quality.report(db, now=NOW))[WARNING]
    assert stats["shown"] == 1 and stats["dismissed_wrong"] == 0
    assert stats["precision"] == 1.0


# ── refresh_states ───────────────────────────────────────────────────────────


@pytest.fixture
def daily(monkeypatch: pytest.MonkeyPatch):
    """Automat dzienny na podstawionych liczbach i stanie w pamięci."""
    blocking, warnings = qc_quality._keys()
    world = SimpleNamespace(
        row=SimpleNamespace(value={}),
        numbers={},
        alerts=[],
    )

    def numbers(**over):
        base = {
            key: {
                "shown": 0,
                "dismissed_wrong": 0,
                "reasons": {},
                "precision": None,
                "blocking": key in blocking,
            }
            for key in (*blocking, *warnings)
        }
        for key, (shown, precision) in over.items():
            base[key].update(shown=shown, precision=precision)
        world.numbers = base

    async def report(_db, *, now=None):
        return world.numbers

    async def locked(_db):
        return world.row

    async def alert(_db, key, precision):
        world.alerts.append((key, precision))

    monkeypatch.setattr(qc_quality, "report", report)
    monkeypatch.setattr(qc_quality, "_locked_states", locked)
    monkeypatch.setattr(qc_quality, "_alert_admins", alert)
    world.set = numbers
    return world


async def _refresh(world, **over) -> dict:
    world.set(**over)
    return await qc_quality.refresh_states(object(), now=NOW)


@pytest.mark.asyncio
async def test_warning_below_70_with_30_shown_becomes_information(daily) -> None:
    states = await _refresh(daily, **{WARNING: (30, 0.69)})
    assert states[WARNING]["auto"] == "info"
    assert states[WARNING]["since"] == NOW.isoformat()
    assert qc_quality.effective_states(states)[WARNING] == "info"


@pytest.mark.parametrize("shown, precision", [(29, 0.2), (30, 0.70), (200, 0.95)])
@pytest.mark.asyncio
async def test_warning_stays_active_below_the_sample_or_at_the_threshold(
    daily, shown: int, precision: float
) -> None:
    states = await _refresh(daily, **{WARNING: (shown, precision)})
    assert states[WARNING].get("auto") is None
    assert qc_quality.effective_states(states)[WARNING] == "active"


@pytest.mark.asyncio
async def test_warning_comes_back_when_precision_recovers(daily) -> None:
    await _refresh(daily, **{WARNING: (40, 0.5)})
    states = await _refresh(daily, **{WARNING: (40, 0.75)})
    assert states[WARNING]["auto"] is None
    assert qc_quality.effective_states(states)[WARNING] == "active"


@pytest.mark.asyncio
async def test_manual_state_wins_over_the_automat(daily) -> None:
    daily.row.value = {WARNING: {"manual": "active"}}
    states = await _refresh(daily, **{WARNING: (40, 0.1)})
    assert states[WARNING]["auto"] == "info"
    assert qc_quality.effective_states(states)[WARNING] == "active"


@pytest.mark.asyncio
async def test_blocking_never_mutes_and_alerts_once_per_series(daily) -> None:
    states = await _refresh(daily, **{BLOCKING: (30, 0.89)})
    assert daily.alerts == [(BLOCKING, 0.89)]
    assert states[BLOCKING].get("auto") is None
    assert qc_quality.effective_states(states)[BLOCKING] == "active"
    # Ta sama seria — bez drugiego powiadomienia.
    await _refresh(daily, **{BLOCKING: (35, 0.8)})
    assert len(daily.alerts) == 1
    # Trafność wróciła ≥ 90% — seria się kończy …
    states = await _refresh(daily, **{BLOCKING: (40, 0.9)})
    assert states[BLOCKING]["alerted"] is False
    # … a kolejny spadek to nowa seria i nowe powiadomienie.
    await _refresh(daily, **{BLOCKING: (45, 0.85)})
    assert daily.alerts == [(BLOCKING, 0.89), (BLOCKING, 0.85)]


@pytest.mark.asyncio
async def test_blocking_below_90_on_a_small_sample_does_not_alert(daily) -> None:
    await _refresh(daily, **{BLOCKING: (29, 0.5)})
    assert daily.alerts == []
