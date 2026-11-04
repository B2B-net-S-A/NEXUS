"""Obejście doradcze QC i pominięcia po zwrocie karty — reguła bez bazy
(audyt 48 h, 13.10.2026).

Reguły: `docs/claude/rekrutacja-tablica/qc-cv-tryb-doradczy-role-z-odczytu-potwierdzenie.md`
i `qc-to-nieprawda-i-jakosc-qc.md`.

* Obejście doradcze rekrutera dotyczy wersji CV, przy której je zrobiono, i
  tylko trybu doradczego — po zmianie CV albo po `CV_QC_ADVISORY=False`
  bramka, plakietka i przegląd DL znów mówią „do poprawy”. Obejście osoby od
  wysyłki (Delivery Lead, admin) zostaje bez końca, jak dotąd.
* Przebieg zaliczony dzięki pominięciom („To nieprawda”) przestaje
  przepuszczać, gdy zwrot karty przywrócił część tych pominięć.

Te same zachowania na bazie: `test_fix48_ws11_qc_pair_status.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.models.cv_qc_run import CvQcRun
from app.services import cv_qc as qc

AT = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def _where(*clauses) -> str:
    """SQL warunku z wartościami parametrów (klucze JSON są parametrami)."""
    compiled = select(CvQcRun.id).where(*clauses).compile(dialect=postgresql.dialect())
    return f"{compiled} {sorted(map(str, compiled.params.values()))}"


def test_advisory_override_is_tied_to_the_latest_cv(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    sql = _where(qc._override_applies())
    assert "override_advisory" in sql
    # Odcisk CV wiersza obejścia = odcisk najnowszego przebiegu tej samej pary.
    assert "cv_qc_runs.cv_fingerprint IS NOT DISTINCT FROM (SELECT" in sql
    assert "cv_qc_runs_1.candidate_id = cv_qc_runs.candidate_id" in sql
    assert "cv_qc_runs_1.job_id = cv_qc_runs.job_id" in sql


def test_live_cv_fingerprint_replaces_the_latest_run(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    stmt = select(CvQcRun.id).where(qc._override_applies("abc123"))
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "IS NOT DISTINCT FROM %(cv_fingerprint_1)s" in str(compiled)
    assert compiled.params["cv_fingerprint_1"] == "abc123"


def test_outside_advisory_mode_only_the_senders_override_counts(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", False)
    sql = _where(qc._override_applies())
    assert "override_advisory" in sql and "!=" in sql
    assert "cv_fingerprint" not in sql


def test_card_return_spends_every_unspent_advisory_override(monkeypatch) -> None:
    # Zwrot karty zużywa obejście doradcze niezależnie od CV i trybu — inaczej
    # ożyłoby po powrocie do starego CV albo do trybu doradczego.
    for advisory in (True, False):
        monkeypatch.setattr(settings, "CV_QC_ADVISORY", advisory)
        sql = _where(qc._unspent_override(), qc._is_advisory_override())
        assert "cv_fingerprint" not in sql


# ── pair_statuses: logika na podstawionych wierszach ─────────────────────────


class _Db:
    """Odpowiedzi `pair_statuses`: najnowszy przebieg pary, potem pominięcia."""

    def __init__(self, runs: list, active: list) -> None:
        self._answers = [runs, active]
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Rows(self._answers[len(self.statements) - 1])


class _Rows(list):
    """Wynik zapytania: `.all()` i iteracja."""

    def all(self):
        return list(self)


def _run(**kw) -> SimpleNamespace:
    base = dict(
        candidate_id=1,
        job_id=2,
        passed=True,
        blocking_failed=0,
        warnings_count=0,
        created_at=AT,
        dismissed=None,
        has_override=False,
        override_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _active(count: int) -> SimpleNamespace:
    return SimpleNamespace(candidate_id=1, job_id=2, active=count)


async def _status(runs: list, active: list) -> dict:
    return (await qc.pair_statuses(_Db(runs, active), [(1, 2)]))[(1, 2)]


@pytest.mark.asyncio
async def test_pass_through_dismissals_is_overridden_while_they_last() -> None:
    out = await _status([_run(dismissed="2")], [_active(2)])
    assert out == {
        "status": "overridden",
        "blocking_failed": 0,
        "ok_at": AT,
        "dismissed_blocking": 2,
        "warnings_count": 0,
    }


@pytest.mark.asyncio
async def test_returned_card_without_a_new_run_is_no_longer_passed_through() -> None:
    # Rekruter pominął dwie blokady, Delivery Lead jedną; zwrot karty
    # przywrócił dwie rekrutera — QC nie liczyło się od nowa.
    out = await _status([_run(dismissed="3")], [_active(1)])
    assert out == {
        "status": "failed",
        "blocking_failed": 2,
        "ok_at": None,
        "dismissed_blocking": 0,
        "warnings_count": 0,
    }
    out = await _status([_run(dismissed="1")], [])
    assert out["status"] == "failed" and out["blocking_failed"] == 1


@pytest.mark.asyncio
async def test_returned_dismissals_still_leave_a_senders_override() -> None:
    out = await _status([_run(dismissed="1", has_override=True, override_at=AT)], [])
    assert out["status"] == "overridden" and out["dismissed_blocking"] == 0


@pytest.mark.asyncio
async def test_plain_pass_and_plain_failure_are_unchanged() -> None:
    assert (await _status([_run()], []))["status"] == "passed"
    failed = await _status([_run(passed=False, blocking_failed=3)], [])
    assert failed == {
        "status": "failed",
        "blocking_failed": 3,
        "ok_at": None,
        "dismissed_blocking": 0,
        "warnings_count": 0,
    }


@pytest.mark.asyncio
async def test_status_query_reads_active_blocking_qc_dismissals(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    db = _Db([], [])
    await qc.pair_statuses(db, [(1, 2)])
    runs_sql, dismissals_sql = (_sql(s) for s in db.statements)
    assert "IS NOT DISTINCT FROM (SELECT cv_qc_runs_1.cv_fingerprint" in runs_sql
    assert "cv_finding_dismissals.restored_at IS NULL" in dismissals_sql
    assert "cv_finding_dismissals.blocking IS true" in dismissals_sql
    assert "cv_finding_dismissals.source = %(source_1)s" in dismissals_sql


# ── D6 (17.10.2026): przepuszczenie idzie za CV, dopóki nie ma nowej blokady ──


def _blocking(*keys: str) -> list[dict]:
    return [
        {
            "key": "no_unsupported",
            "severity": "blocking",
            "status": "fail" if keys else "pass",
            "items": [{"key": key} for key in keys],
        },
        {
            "key": "must_bolded",
            "severity": "warning",
            "status": "fail",
            "items": [{"key": "must_bolded|java|cv"}],
        },
    ]


def test_blocking_keys_count_only_failed_blocking_items() -> None:
    assert qc.blocking_keys(_blocking("a", "b")) == frozenset({"a", "b"})
    assert qc.blocking_keys(_blocking()) == frozenset()
    # Blokada bez pozycji (brak CV) też ma klucz.
    assert qc.blocking_keys(
        [{"key": "cv_present", "severity": "blocking", "status": "fail", "items": []}]
    ) == frozenset({"cv_present|#"})


class _OverrideDb:
    """Najpierw najnowszy wiersz etapu pary, potem wiersz obejścia; `flush` liczony."""

    def __init__(self, row, latest_stage_id: int = 7) -> None:
        self.answers = [latest_stage_id, row]
        self.statements: list = []
        self.flushes = 0

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return self.answers.pop(0) if self.answers else None

    async def flush(self) -> None:
        self.flushes += 1


def _override_row(fp: str, *keys: str) -> SimpleNamespace:
    return SimpleNamespace(cv_fingerprint=fp, result={"checks": _blocking(*keys)})


@pytest.mark.asyncio
async def test_override_follows_the_cv_while_no_new_blocker_appears(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    row = _override_row("old", "a", "b")
    db = _OverrideDb(row)
    # Poprawka usunęła blokadę „b”, „a” została — przepuszczenie przechodzi na nowe CV.
    assert await qc.follow_advisory_override(db, 1, 2, 7, "new", _blocking("a")) is True
    assert row.cv_fingerprint == "new"
    # Sesja ma `autoflush=False` — bez zapisu `_latest_override` zaraz potem
    # czytałby stary odcisk (bramka i panel widziałyby „bez obejścia”).
    assert db.flushes == 1
    compiled = db.statements[1].compile(dialect=postgresql.dialect())
    sql = f"{compiled} {sorted(map(str, compiled.params.values()))}"
    # Tylko niezużyte obejście doradcze tej pary.
    assert "override_advisory" in sql and "override_spent_at" in sql


@pytest.mark.asyncio
async def test_new_blocker_ends_the_override(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    row = _override_row("old", "a")
    assert (
        await qc.follow_advisory_override(
            _OverrideDb(row), 1, 2, 7, "new", _blocking("a", "c")
        )
        is False
    )
    assert row.cv_fingerprint == "old"


@pytest.mark.asyncio
async def test_follow_needs_advisory_mode_a_fingerprint_and_an_override(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", False)
    row = _override_row("old", "a")
    assert (
        await qc.follow_advisory_override(
            _OverrideDb(row), 1, 2, 7, "new", _blocking("a")
        )
        is False
    )
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    assert (
        await qc.follow_advisory_override(
            _OverrideDb(row), 1, 2, 7, None, _blocking("a")
        )
        is False
    )
    assert (
        await qc.follow_advisory_override(
            _OverrideDb(None), 1, 2, 7, "new", _blocking("a")
        )
        is False
    )
    assert row.cv_fingerprint == "old"
    # To samo CV — nic do zrobienia.
    same = _override_row("new", "a")
    assert (
        await qc.follow_advisory_override(
            _OverrideDb(same), 1, 2, 7, "new", _blocking("a")
        )
        is False
    )


@pytest.mark.asyncio
async def test_override_follows_only_from_the_pairs_latest_stage(monkeypatch) -> None:
    # Starszy wiersz etapu ma inną migawkę oryginału i inne odpowiedzi — QC
    # liczone na nim nie może przesunąć obejścia na nowe CV (przegląd PR 3).
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    row = _override_row("old", "a")
    db = _OverrideDb(row, latest_stage_id=9)
    assert (
        await qc.follow_advisory_override(db, 1, 2, 7, "new", _blocking("a")) is False
    )
    assert row.cv_fingerprint == "old" and db.flushes == 0
