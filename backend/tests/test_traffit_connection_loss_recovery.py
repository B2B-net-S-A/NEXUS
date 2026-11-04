"""Zerwane połączenie w savepoincie nie kosztuje reszty fazy (audyt 25.09.2026, r2).

Po utracie połączenia (`DBAPIError.connection_invalidated`) `ROLLBACK TO
SAVEPOINT` nie ma dokąd pójść: każde kolejne `begin_nested()` rzuca
`PendingRollbackError`, cała reszta fazy to błędy przypisane wierszom, a commit
na końcu wywraca fazę. Fazy klientów, kontaktów, kandydatów, rekrutacji i
źródeł podnosiły sesję (`needs_session_rollback`), a fazy CV, plików,
aktywności, workflowów i historii etapów — nie.

Testy bez bazy: atrapa sesji zachowuje się jak SQLAlchemy po zerwaniu
połączenia (wszystko rzuca `PendingRollbackError`, dopóki ktoś nie zrobi
`rollback()`; rollback zabiera to, co nie zostało zacommitowane).
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from sqlalchemy.exc import DBAPIError, PendingRollbackError

from app.services.traffit import importer as importer_mod
from app.services.traffit.importer import TraffitImporter, needs_session_rollback

_BACKEND = Path(__file__).resolve().parents[1]
_IMPORTER = _BACKEND / "app/services/traffit/importer.py"


# ── Atrapa sesji ─────────────────────────────────────────────────────────────


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Savepoint:
    def __init__(self, db: "_FakeSession") -> None:
        self.db = db

    async def __aenter__(self):
        if self.db.broken:
            raise PendingRollbackError("session needs rollback")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    """Zapis numer `fail_on` zrywa połączenie; do `rollback()` wszystko rzuca."""

    def __init__(self, *, fail_on: int, select_rows: Optional[list] = None) -> None:
        self.fail_on = fail_on
        self.select_rows = select_rows or []
        self.writes = 0
        self.broken = False
        self.staged: list[Any] = []
        self.committed: list[Any] = []
        self.rollbacks = 0

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self)

    async def execute(self, stmt: Any, params: Any = None) -> _Rows:
        if self.broken:
            raise PendingRollbackError("session needs rollback")
        if str(stmt).lstrip().upper().startswith("SELECT"):
            return _Rows(self.select_rows)
        self.writes += 1
        if self.writes == self.fail_on:
            self.broken = True
            raise DBAPIError(
                "write",
                None,
                Exception("server closed the connection"),
                connection_invalidated=True,
            )
        self.staged.append(params)
        return _Rows([(self.writes, True, False)])

    async def commit(self) -> None:
        if self.broken:
            raise PendingRollbackError("session needs rollback")
        self.committed.extend(self.staged)
        self.staged = []

    async def rollback(self) -> None:
        self.broken = False
        self.staged = []
        self.rollbacks += 1


def _batch_lost_errors(progress) -> list[str]:
    return [m for m in progress.error_samples if "rolled back after lost" in m]


# ── Decyzja ──────────────────────────────────────────────────────────────────


def test_pending_rollback_error_also_asks_for_a_session_rollback() -> None:
    """Krok, który złapał zerwanie bez tej decyzji (log i dalej), zostawia
    sesję w `PendingRollbackError` — bez `connection_invalidated`. Łańcuch
    musi się podnieść na pierwszym kolejnym wierszu, a nie paść na commicie."""
    assert needs_session_rollback(PendingRollbackError("x"), past_savepoint=False)


# ── Fazy (wykonanie) ─────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"%PDF-1.4"
        self.headers = {"content-type": "application/pdf"}

    def json(self) -> Any:
        return self._payload


class _Http:
    async def get(self, url: str, headers: Any = None) -> _Resp:
        return _Resp()


class _FilesTraffit:
    """Traffit z jednym plikiem CV na kandydata."""

    def __init__(self) -> None:
        self._http = _Http()
        self.config = SimpleNamespace(api_base="https://traffit.test")

    async def _get_raw(self, path: str, page: int = 1, page_size: int = 50):
        return _Resp(payload=[{"id": 7, "name": "cv.pdf"}])

    async def _ensure_token(self) -> str:
        return "token"

    async def _throttle(self) -> None:
        return None


def _candidates(n: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=i, external_id=str(1000 + i)) for i in range(1, n + 1)]


@pytest.fixture
def _no_object_storage(monkeypatch):
    from app.services import object_storage

    monkeypatch.setattr(object_storage, "upload_cv", lambda **_kw: "cv/key")


@pytest.mark.asyncio
async def test_cv_phase_recovers_after_lost_connection(_no_object_storage) -> None:
    db = _FakeSession(fail_on=3, select_rows=_candidates(5))
    importer = TraffitImporter(_FilesTraffit(), db)  # type: ignore[arg-type]

    progress = await importer.import_candidates_cv(since=datetime.now(timezone.utc))

    stored = {p["id"] for p in db.committed}
    assert stored == {4, 5}, (
        "kandydaci po zerwaniu połączenia muszą się zapisać — bez rollbacku "
        f"sesji każdy kolejny pada na PendingRollbackError (zapisano {stored})"
    )
    assert db.rollbacks == 1
    # Wiersz, na którym zerwało, i niezacommitowana paczka (1, 2) — ta druga
    # jako błąd nieprzypisany, żeby watermark nie przeszedł nad nią.
    assert len(_batch_lost_errors(progress)) == 1
    assert any("cv candidate ext=1003" in m for m in progress.error_samples)


@pytest.mark.asyncio
async def test_files_phase_recovers_after_lost_connection(
    _no_object_storage, monkeypatch
) -> None:
    # Główne CV = dwa zapisy na kandydata (zdjęcie flagi + upsert), więc
    # piąty zapis to pierwszy zapis kandydata 3.
    db = _FakeSession(fail_on=5)
    importer = TraffitImporter(_FilesTraffit(), db)  # type: ignore[arg-type]

    async def targets(_since):
        return _candidates(5)

    monkeypatch.setattr(importer, "_delta_file_targets", targets)

    progress = await importer.import_candidate_files(since=datetime.now(timezone.utc))

    stored = {p["candidate_id"] for p in db.committed}
    assert stored == {4, 5}, f"zapisano {stored}"
    assert db.rollbacks == 1
    assert len(_batch_lost_errors(progress)) == 1


def _stub_lookups(importer: TraffitImporter, monkeypatch) -> None:
    async def empty_map(*_a, **_kw):
        return {}

    async def empty_set(*_a, **_kw):
        return set()

    async def no_cursor(*_a, **_kw):
        return None

    async def zero(*_a, **_kw):
        return 0

    for name in ("_build_candidate_external_id_map", "build_user_id_map"):
        monkeypatch.setattr(importer, name, empty_map)
    for name in ("_read_mode_cursor", "_write_mode_cursor", "_clear_mode_cursor"):
        monkeypatch.setattr(importer, name, no_cursor)
    monkeypatch.setattr(importer, "promote_notes", zero)
    monkeypatch.setattr(importer_mod, "backfill_rejection_notes_from_activities", zero)
    monkeypatch.setattr(
        importer_mod, "backfill_rejection_descriptions_from_activities", zero
    )
    monkeypatch.setattr(importer, "_build_job_external_id_map", empty_map)
    monkeypatch.setattr(importer, "_build_managed_job_ids", empty_set)


class _PagedTraffit:
    def __init__(self, n: int) -> None:
        self._items = [{"id": i} for i in range(1, n + 1)]

    async def total_count(self, path: str) -> int:
        return len(self._items)

    async def get_pages(self, path: str, **_kw):
        yield 1, list(self._items)


@pytest.mark.asyncio
async def test_activities_phase_recovers_after_lost_connection(monkeypatch) -> None:
    db = _FakeSession(fail_on=3)
    importer = TraffitImporter(_PagedTraffit(5), db)  # type: ignore[arg-type]
    _stub_lookups(importer, monkeypatch)
    monkeypatch.setattr(
        importer_mod,
        "traffit_activity_to_activity",
        lambda raw, _c, _u: {
            "external_id": str(raw["id"]),
            "entity_type": "candidate",
            "entity_id": raw["id"],
            "action": "traffit:Notatka",
            "details": {},
            "user_id": None,
        },
    )

    progress = await importer.import_candidate_activities(since=None)

    stored = {p["external_id"] for p in db.committed}
    assert stored == {"4", "5"}, f"zapisano {stored}"
    assert db.rollbacks == 1
    assert len(_batch_lost_errors(progress)) == 1


@pytest.mark.asyncio
async def test_pipelines_phase_replays_the_batch_after_lost_connection(
    monkeypatch,
) -> None:
    """Historia etapów trzyma wsad w `pending_rows`, więc po zerwaniu go
    odtwarza (ta sama ścieżka co przy padniętym commicie), zamiast tracić."""
    db = _FakeSession(fail_on=3)
    importer = TraffitImporter(_PagedTraffit(5), db)  # type: ignore[arg-type]
    _stub_lookups(importer, monkeypatch)

    async def stage_lookup():
        return {}, {}

    async def fallback():
        return SimpleNamespace(by_job={}, by_stage_def={}, default_id=None)

    async def probe(*_a, **_kw):
        return 5

    async def upsert_stage(payload, _reason):
        async with db.begin_nested():
            await db.execute("INSERT stage", payload)
        return True

    async def noop(*_a, **_kw):
        return {}

    monkeypatch.setattr(importer, "_build_stage_def_lookup", stage_lookup)
    monkeypatch.setattr(importer, "_build_withdrawn_fallback_reason_map", fallback)
    monkeypatch.setattr(importer, "_probe_total", probe)
    monkeypatch.setattr(importer, "_upsert_stage_row", upsert_stage)
    monkeypatch.setattr(
        importer, "_fallback_rejection_reason_id", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(importer_mod, "sync_external_observed_processes", noop)
    monkeypatch.setattr(importer_mod, "apply_imported_stage_side_effects", noop)
    monkeypatch.setattr(
        importer_mod,
        "traffit_recruitment_history_to_stage",
        lambda raw, *_a, **_kw: {
            "external_id": str(raw["id"]),
            "candidate_id": raw["id"],
            "job_id": 1,
            "stage_def_id": 1,
            "stage_legacy_enum": "verified",
        },
    )

    progress = await importer.import_pipelines(since=None)

    stored = sorted(p["external_id"] for p in db.committed)
    assert stored == ["1", "2", "4", "5"], (
        "wsad sprzed zerwania musi zostać odtworzony, a wiersze po nim zapisane "
        f"(zapisano {stored})"
    )
    assert progress.errors == 1, progress.error_samples


# ── Każdy savepoint w importerze ma decyzję o sesji ──────────────────────────

# Metody, które otwierają savepoint w środku i puszczają wyjątek wyżej.
_SAVEPOINT_HELPERS = {"_upsert_stage_row", "_upsert_candidate_document"}
_DECISIONS = {"_recover_session", "needs_session_rollback", "_replay_stage_rows"}
_BROAD = {"Exception", "BaseException"}


def _is_savepoint_site(node: ast.AST) -> bool:
    if isinstance(node, ast.AsyncWith):
        return any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "begin_nested"
            for item in node.items
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _SAVEPOINT_HELPERS
    )


def _handler_is_broad(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    return kind is None or (isinstance(kind, ast.Name) and kind.id in _BROAD)


def _handler_decides(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in _DECISIONS:
                return True
            # Bezwarunkowy rollback sesji (np. odtwarzanie wsadu wiersz po
            # wierszu) — nic nie zostaje w stanie `PendingRollbackError`.
            if name == "rollback" and isinstance(func, ast.Attribute):
                return True
    return False


def test_every_savepoint_handler_decides_about_the_session() -> None:
    """Źródło, bo luka była w KILKU fazach naraz — test wykonaniowy pokryje
    tylko te, do których go napiszemy. Dla każdego savepointu (i metody, która
    go otwiera) najbliższy `except`, który łapie wszystko, musi podnieść sesję
    po utracie połączenia (`_recover_session`/`needs_session_rollback`),
    odtworzyć wsad albo rzucić dalej."""
    tree = ast.parse(_IMPORTER.read_text(encoding="utf-8"))
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    offenders: list[str] = []
    sites = 0
    for node in ast.walk(tree):
        if not _is_savepoint_site(node):
            continue
        sites += 1
        child, parent = node, parents.get(node)
        while parent is not None and not isinstance(
            parent, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if isinstance(parent, ast.Try) and child in parent.body:
                broad = [h for h in parent.handlers if _handler_is_broad(h)]
                if broad:
                    if not all(_handler_decides(h) for h in broad):
                        offenders.append(f"importer.py:{node.lineno}")
                    break
            child, parent = parent, parents.get(parent)
    assert sites >= 20, f"skaner znalazł tylko {sites} savepointów — zepsuty?"
    assert offenders == [], (
        "savepoint bez decyzji o sesji po utracie połączenia: " + ", ".join(offenders)
    )
