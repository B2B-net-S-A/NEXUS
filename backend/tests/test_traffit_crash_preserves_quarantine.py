"""Awaria fazy Traffita nie może kasować licznika prób kwarantanny.

Kwarantanna liczy KOLEJNE porażki per wiersz i po
``TRAFFIT_MAX_ROW_ATTEMPTS`` parkuje wiersz, żeby jeden rekord nie do
zaimportowania nie mroził znacznika ``__daily__`` całej bazie. Licznik żyje
w ``traffit_sync_state.stats->'quarantine'``.

Gałąź ``except`` orkiestratora zapisywała ``stats={"error": ...}``, a
``_UPSERT_STATE`` ma ``stats = COALESCE(EXCLUDED.stats, …)`` — ``COALESCE``
broni wyłącznie przed NULL-em, więc niepusty słownik NADPISYWAŁ kolumnę
w całości i kasował licznik. Skutek jest cichy i dokładnie odwrotny do
intencji: wystarczy, że faza wywraca się raz na ≤5 biegów, a wiersz psujący
się co noc NIGDY nie dobije do limitu. Kwarantanna „działa", wygląda na
sprawną i nie parkuje niczego — a watermark stoi w nieskończoność.

Harness jest ŚWIADOMĄ kopią z ``test_traffit_watermark_on_failure.py``:
tamten plik opisuje w docstringu jeden konkretny incydent (M2-IMP-01) i nie
ma być rozcieńczany o drugi temat.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.tasks import traffit_sync
from app.tasks.traffit_sync import DAILY_MARKER, run_traffit_sync

UTC = timezone.utc
_PRIOR = datetime(2026, 7, 1, 2, 0, tzinfo=UTC)
_POISON = "candidate:48895"


# ── Test doubles ─────────────────────────────────────────────────────────────


class _FakeProgress:
    """Minimalny wynik fazy honorujący kontrakt (as_dict / errors / *_at)."""

    def __init__(self, *, errors: int = 0, error_refs: list[str] | None = None) -> None:
        self.errors = errors
        self.error_refs = set(error_refs or [])
        self.started_at = datetime.now(UTC)
        self.finished_at = datetime.now(UTC)

    def as_dict(self) -> dict:
        return {
            "processed": 1,
            "inserted": 1,
            "errors": self.errors,
            "error_refs": sorted(self.error_refs),
            "attributed_errors": self.errors if self.error_refs else 0,
        }


class _FakeClient:
    def __init__(self, *a, **k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _RecordingSession:
    """Sesja zapisująca KOLEJNOŚĆ wywołań — rollback musi poprzedzać odczyt."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def commit(self, *a, **k):
        self.calls.append("commit")

    async def rollback(self, *a, **k):
        self.calls.append("rollback")

    async def execute(self, *a, **k):
        self.calls.append("execute")
        return None


class _FakeSessionCM:
    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *a):
        return False


def _ok_phase():
    async def _factory():
        return _FakeProgress(errors=0)

    return _factory


def _raising_phase():
    async def _factory():
        raise RuntimeError("phase boom")

    return _factory


def _poison_phase():
    """Faza, która co bieg zgłasza ten sam nieimportowalny wiersz."""

    async def _factory():
        return _FakeProgress(errors=1, error_refs=[_POISON])

    return _factory


# ── Harness ──────────────────────────────────────────────────────────────────


async def _run(
    monkeypatch,
    *,
    phases,
    prior_stats=None,
    mode: str = "delta",
    session: _RecordingSession | None = None,
    get_state=None,
):
    """Uruchom ``run_traffit_sync`` na zamockowanym planie faz / DB.

    Zwraca mock ``_upsert_state``, żeby test mógł obejrzeć, co zapisano na
    wierszu fazy. ``prior_stats`` sieje ``stats`` z poprzedniego biegu — tam
    właśnie mieszka licznik prób kwarantanny.
    """
    upserts = AsyncMock()
    session = session or _RecordingSession()
    if get_state is None:
        get_state = AsyncMock(
            return_value=SimpleNamespace(last_synced_at=_PRIOR, stats=prior_stats)
        )
    monkeypatch.setattr(traffit_sync, "_upsert_state", upserts)
    monkeypatch.setattr(traffit_sync, "_get_state", get_state)
    monkeypatch.setattr(
        traffit_sync, "_phase_plan", lambda importer, since, files_since: phases
    )
    monkeypatch.setattr(traffit_sync, "TraffitImporter", lambda *a, **k: object())
    monkeypatch.setattr(traffit_sync, "TraffitClient", _FakeClient)
    monkeypatch.setattr(
        traffit_sync, "AsyncSessionLocal", lambda: _FakeSessionCM(session)
    )
    monkeypatch.setattr(
        traffit_sync.TraffitConfig, "from_env", staticmethod(lambda: object())
    )

    await run_traffit_sync(mode)
    return upserts


def _marker_call(upserts: AsyncMock, marker: str):
    for c in upserts.call_args_list:
        if len(c.args) >= 2 and c.args[1] == marker:
            return c
    return None


def _phase_stats(upserts: AsyncMock, phase: str = "candidates") -> dict:
    call = _marker_call(upserts, phase)
    assert call is not None, f"faza {phase} nie zapisała stanu"
    return call.kwargs["stats"]


# ── Licznik prób przeżywa wywrotkę fazy ─────────────────────────────────────


async def test_crash_carries_the_quarantine_counter(monkeypatch):
    upserts = await _run(
        monkeypatch,
        phases=[("candidates", _raising_phase())],
        prior_stats={"quarantine": {_POISON: 4}},
    )
    stats = _phase_stats(upserts)
    assert stats["quarantine"] == {_POISON: 4}, (
        "wywrotka fazy skasowała licznik prób — wiersz startuje od zera"
    )
    assert "error" in stats, "wywrotka musi nadal raportować własny błąd"


async def test_crash_does_not_bump_the_counter(monkeypatch):
    """Awaria fazy to nie próba importu wiersza — karanie go byłoby cichą stratą.

    Inkrement po N wywrotkach zaparkowałby ZDROWY wiersz, który przestałby
    blokować watermark, choć nikt go nawet nie tknął.
    """
    upserts = await _run(
        monkeypatch,
        phases=[("candidates", _raising_phase())],
        prior_stats={"quarantine": {_POISON: 4}},
    )
    assert _phase_stats(upserts)["quarantine"][_POISON] == 4


async def test_crash_carries_the_parked_list(monkeypatch):
    """Zaparkowany wiersz nie może zniknąć operatorowi z /sync/status."""
    monkeypatch.setattr(traffit_sync.settings, "TRAFFIT_MAX_ROW_ATTEMPTS", 5)
    upserts = await _run(
        monkeypatch,
        phases=[("candidates", _raising_phase())],
        prior_stats={"quarantine": {_POISON: 5, "candidate:1": 1}},
    )
    stats = _phase_stats(upserts)
    assert stats["quarantined"] == [_POISON]


async def test_crash_without_previous_quarantine_writes_no_key(monkeypatch):
    """Nie wprowadzamy pustych kluczy — „nieobecny" ma dalej znaczyć zero."""
    upserts = await _run(
        monkeypatch, phases=[("candidates", _raising_phase())], prior_stats=None
    )
    stats = _phase_stats(upserts)
    assert "quarantine" not in stats
    assert "quarantined" not in stats


async def test_garbage_in_the_counter_does_not_kill_the_handler(monkeypatch):
    """`quarantine` wraca z JSONB, więc wartością bywa cokolwiek.

    Nieczytelny wpis ma zostać POMINIĘTY przy liczeniu zaparkowanych, a nie
    wysadzić obsługę wyjątku — inaczej licznik ginie CAŁEJ fazie, a wiersz
    fazy nie dostaje nawet ``last_status="error"``.
    """
    monkeypatch.setattr(traffit_sync.settings, "TRAFFIT_MAX_ROW_ATTEMPTS", 5)
    upserts = await _run(
        monkeypatch,
        phases=[("candidates", _raising_phase())],
        prior_stats={"quarantine": {_POISON: "nie-liczba", "candidate:1": 7}},
    )
    stats = _phase_stats(upserts)
    assert stats["quarantine"] == {_POISON: "nie-liczba", "candidate:1": 7}
    assert stats["quarantined"] == ["candidate:1"]


# ── Kolejność: odczyt PO rollbacku ──────────────────────────────────────────


async def test_state_is_read_after_the_rollback(monkeypatch):
    """Odczyt przed rollbackiem = PendingRollbackError WEWNĄTRZ bloku `except`.

    Sesja stoi wtedy w zepsutej transakcji i każde zapytanie rzuca — czyli
    faza nie zapisałaby nawet własnego statusu, a pętla poleciałaby dalej
    z niespójnym stanem. Kolejność jest wymogiem, nie stylem.
    """
    session = _RecordingSession()

    async def _get_state(db, phase):
        # Tylko odczyt WIERSZA FAZY; `run_traffit_sync` czyta jeszcze znacznik
        # `__daily__` na samym starcie (poza `try`), a ten nic tu nie mówi.
        if phase == "candidates":
            session.calls.append("get_state:candidates")
        return SimpleNamespace(
            last_synced_at=_PRIOR, stats={"quarantine": {_POISON: 2}}
        )

    await _run(
        monkeypatch,
        phases=[("candidates", _raising_phase())],
        session=session,
        get_state=_get_state,
    )
    assert "rollback" in session.calls, "gałąź awaryjna musi wycofać transakcję"
    assert session.calls.index("rollback") < session.calls.index("get_state:candidates")


async def test_state_read_failure_does_not_swallow_the_phase_status(monkeypatch):
    """Padnięty odczyt degraduje do stanu sprzed poprawki, nie do braku zapisu."""

    async def _boom(db, phase):
        # Padnięcie WYŁĄCZNIE na wierszu fazy: odczyt znacznika `__daily__`
        # jest poza `try` i jego awaria to zupełnie inny scenariusz.
        if phase == "candidates":
            raise RuntimeError("select boom")
        return SimpleNamespace(last_synced_at=_PRIOR, stats=None)

    upserts = await _run(
        monkeypatch, phases=[("candidates", _raising_phase())], get_state=_boom
    )
    call = _marker_call(upserts, "candidates")
    assert call is not None
    assert call.kwargs["last_status"] == "error"
    assert "error" in call.kwargs["stats"]
    assert "quarantine" not in call.kwargs["stats"]


async def test_crash_stamps_its_own_run_timestamps(monkeypatch):
    """Wiersz fazy po wywrotce nie może nieść znaczników z UDANEGO biegu.

    ``_UPSERT_STATE`` COALESCE-uje pominięte znaczniki, więc nieprzekazanie ich
    zostawiało w ``/sync/status`` datę ostatniego SUKCESU pod statusem
    „error" — sygnał mówiący coś przeciwnego do prawdy.
    """
    upserts = await _run(monkeypatch, phases=[("candidates", _raising_phase())])
    call = _marker_call(upserts, "candidates")
    assert isinstance(call.kwargs["last_run_started_at"], datetime)
    assert isinstance(call.kwargs["last_run_finished_at"], datetime)


# ── Ścieżka sukcesu bez zmian (strażnik przeciwko `jsonb ||`) ───────────────


async def test_clean_run_still_replaces_stats_wholesale(monkeypatch):
    """Czysty bieg NADPISUJE stats — „nieobecny klucz ⇒ zero" zostaje.

    To jest strażnik przeciwko „krótszemu" wariantowi poprawki
    (``stats = traffit_sync_state.stats || EXCLUDED.stats`` w ``_UPSERT_STATE``):
    ``||`` jest płytkie i GLOBALNE, więc faza, która wyzdrowiała, w
    nieskończoność niosłaby wczorajsze ``blocking_errors`` i ``quarantined``,
    a ``/sync/status`` raportowałby awarię, której nie ma. Razem
    z ``test_recovered_row_loses_its_accumulated_attempts`` ten test mówi,
    dlaczego SQL zostaje bez zmian.
    """
    upserts = await _run(
        monkeypatch,
        phases=[("candidates", _ok_phase())],
        prior_stats={"quarantine": {_POISON: 4}, "blocking_errors": 3},
    )
    stats = _phase_stats(upserts)
    assert "quarantine" not in stats
    assert "blocking_errors" not in stats


# ── Dowód end-to-end ────────────────────────────────────────────────────────


async def test_poison_row_reaches_quarantine_across_a_crashy_phase(monkeypatch):
    """Najważniejszy test tego pliku: wiersz DOCHODZI do limitu mimo wywrotki.

    Sześć biegów, w trzecim faza wywraca się zamiast zwrócić wynik; ``stats``
    zapisane w biegu N są ``prior_stats`` biegu N+1 — dokładnie tak, jak
    zachowuje się kolumna JSONB między nocami.

    Przed poprawką wywrotka zerowała licznik, więc po szóstym biegu stał on na
    3 zamiast 5, ``quarantined`` nie powstawał, a ``__daily__`` nie ruszał się
    NIGDY. Test jest o TEJ własności, nie o pojedynczym zapisie.
    """
    monkeypatch.setattr(traffit_sync.settings, "TRAFFIT_MAX_ROW_ATTEMPTS", 5)
    crash_at = 3
    stats: dict | None = None
    for run_no in range(1, 7):
        phase = _raising_phase() if run_no == crash_at else _poison_phase()
        upserts = await _run(
            monkeypatch, phases=[("candidates", phase)], prior_stats=stats
        )
        stats = _phase_stats(upserts)

    assert stats["quarantine"][_POISON] == 5, (
        "licznik prób nie przeżył wywrotki — wiersz nigdy nie dobije do limitu"
    )
    assert stats["quarantined"] == [_POISON]
    # Zaparkowany wiersz przestaje mrozić globalny watermark delty.
    daily = _marker_call(upserts, DAILY_MARKER)
    assert isinstance(daily.kwargs["last_synced_at"], datetime), (
        "watermark nadal zamrożony mimo zaparkowanego wiersza"
    )
