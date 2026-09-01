"""Faza DDL w ``entrypoint.sh``: limity zamków + odzyskiwanie po INVALID indeksie.

Dwie regresje, które nie mają żadnego objawu poza zwisem albo cichym brakiem
ograniczenia UNIQUE:

1. DDL bez ``lock_timeout`` nie wywala się — USTAWIA SIĘ W KOLEJCE po ACCESS
   EXCLUSIVE, a za nim każdy kolejny czytelnik gorącej tabeli. Kontener nie
   pada, więc ``|| echo ... continuing`` niczego nie łapie.
2. ``CREATE INDEX CONCURRENTLY`` anulowany po timeoucie zostawia indeks
   ``indisvalid = false``. ``IF NOT EXISTS`` widzi wtedy samą nazwę i pomija
   go NA ZAWSZE — cztery pozycje z listy są UNIQUE i niosą inwarianty
   biznesowe, więc trwale martwe ograniczenie nie wymusza niczego.

Test wykonuje realny blok Pythona z entrypointu na atrapie połączenia, zamiast
grepować po źródle: guard enumerujący bez guardu wykonującego przepuściłby
zmianę kolejności faz.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = BACKEND / "entrypoint.sh"


def _load_backfill_module():
    """Wytnij heredoc `python - <<'PY'` z fazą backfillu i zaimportuj go."""
    lines = ENTRYPOINT.read_text(encoding="utf-8").split("\n")
    start = next(
        i + 1
        for i, line in enumerate(lines)
        if line.startswith("python - <<'PY'") and "column backfill" in line
    )
    end = start
    while lines[end] != "PY":
        end += 1
    # Ostatnia linia bloku odpala backfill przy imporcie — odcinamy ją.
    body = [line for line in lines[start:end] if not line.startswith("asyncio.run(")]

    module_path = Path(tempfile.mkdtemp(prefix="entrypoint_block_")) / "block.py"
    module_path.write_text("\n".join(body), encoding="utf-8")

    sys.modules.setdefault("asyncpg", types.ModuleType("asyncpg"))
    spec = importlib.util.spec_from_file_location(
        "_entrypoint_backfill_block", module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EP = _load_backfill_module()


class _FakeConn:
    """Atrapa asyncpg: zapisuje instrukcje, nie dotyka bazy."""

    def __init__(self, invalid_indexes: list[str] | None = None):
        self.executed: list[str] = []
        self._invalid = invalid_indexes or []

    async def execute(self, stmt, *args):
        self.executed.append(stmt)
        return "OK"

    async def fetch(self, query, *args):
        assert "indisvalid" in query
        return [{"relname": name} for name in self._invalid]

    async def fetchval(self, query, *args):
        # Krótkie spięcie `_ensure_profile_rate_numeric` — typ już docelowy.
        return EP._PROFILE_RATE_TARGET_TYPE

    async def close(self):
        return None


def _index_phase_start(executed: list[str]) -> int:
    return next(i for i, s in enumerate(executed) if "INDEX CONCURRENTLY" in s.upper())


# ── Nazwy indeksów ──────────────────────────────────────────────────────────


def test_kazda_deklaracja_indeksu_oddaje_swoja_nazwe():
    # Nieodczytana nazwa = nieprawidłowy indeks, którego nigdy nie skasujemy.
    names = EP._declared_index_names(EP._INDEX_STATEMENTS)
    assert len(names) == len(EP._INDEX_STATEMENTS)
    for stmt in EP._INDEX_STATEMENTS:
        assert EP._INDEX_NAME_RE.search(stmt), stmt


def test_nazwa_czytana_takze_z_wariantu_unique():
    names = EP._declared_index_names(
        [
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_probe ON t (a)",
            "CREATE INDEX IF NOT EXISTS ix_probe ON t (b)",
            "create index concurrently ix_lower ON t (c)",
        ]
    )
    assert names == {"ux_probe", "ix_probe", "ix_lower"}


# ── Odzyskiwanie po INVALID ─────────────────────────────────────────────────


def test_nieprawidlowy_indeks_z_listy_jest_kasowany_przed_odbudowa():
    target = sorted(EP._declared_index_names(EP._INDEX_STATEMENTS))[0]
    conn = _FakeConn(invalid_indexes=[target])
    asyncio.run(EP._drop_invalid_indexes(conn, EP._INDEX_STATEMENTS))
    assert any(
        s.startswith("DROP INDEX CONCURRENTLY IF EXISTS") and target in s
        for s in conn.executed
    ), conn.executed


def test_cudzy_nieprawidlowy_indeks_zostaje_nietkniety():
    # Ręczna operacja DBA nie jest naszą własnością — nie kasujemy jej.
    conn = _FakeConn(invalid_indexes=["ix_reczny_indeks_dba"])
    asyncio.run(EP._drop_invalid_indexes(conn, EP._INDEX_STATEMENTS))
    assert not any(s.startswith("DROP INDEX") for s in conn.executed), conn.executed


def test_brak_nieprawidlowych_indeksow_nie_wykonuje_niczego():
    conn = _FakeConn(invalid_indexes=[])
    asyncio.run(EP._drop_invalid_indexes(conn, EP._INDEX_STATEMENTS))
    assert conn.executed == []


def test_cztery_pozycje_unique_wciaz_sa_na_liscie():
    # Komentarz nad listą twierdził, że brakujących UNIQUE jest zero; dziś nie
    # jest to prawda i to właśnie one niosą inwarianty biznesowe.
    unique = [s for s in EP._INDEX_STATEMENTS if "UNIQUE INDEX" in s.upper()]
    assert len(unique) >= 4, unique


# ── Limity zamków wokół faz ─────────────────────────────────────────────────


def _run_backfill(monkeypatch) -> _FakeConn:
    conn = _FakeConn()

    async def _connect(url):
        return conn

    fake_asyncpg = types.SimpleNamespace(connect=_connect)
    monkeypatch.setattr(EP, "asyncpg", fake_asyncpg, raising=False)
    asyncio.run(EP.backfill())
    return conn


def test_lock_timeout_ustawiony_zanim_poleci_pierwszy_alter(monkeypatch):
    conn = _run_backfill(monkeypatch)
    first_guard = next(
        i for i, s in enumerate(conn.executed) if s.startswith("SET lock_timeout")
    )
    first_ddl = next(
        i
        for i, s in enumerate(conn.executed)
        if s.upper().lstrip().startswith(("ALTER TABLE", "CREATE TABLE", "DO $$"))
    )
    assert conn.executed[first_guard] == "SET lock_timeout = '3s'"
    assert first_guard < first_ddl, conn.executed[: first_ddl + 1]


def test_faza_indeksow_zdejmuje_lock_timeout(monkeypatch):
    # CREATE INDEX CONCURRENTLY z definicji CZEKA na wydrenowanie transakcji
    # i robi to nie blokując zapisów — 3 s zamieniłoby normalne oczekiwanie
    # w porażkę (i w kolejny nieprawidłowy indeks).
    conn = _run_backfill(monkeypatch)
    idx = _index_phase_start(conn.executed)
    before = [s for s in conn.executed[:idx] if s.startswith("SET lock_timeout")]
    assert before[-1] == "SET lock_timeout = 0", before


def test_faza_indeksow_ma_swoj_statement_timeout(monkeypatch):
    conn = _run_backfill(monkeypatch)
    idx = _index_phase_start(conn.executed)
    before = [s for s in conn.executed[:idx] if s.startswith("SET statement_timeout")]
    assert before[-1] == "SET statement_timeout = '120s'", before


def test_backfille_danych_nie_dostaja_limitu_czasu(monkeypatch):
    # `_DATA_STATEMENTS` to seedy i przeliczenia (rankowanie ~136 tys.
    # dokumentów), którym wolno trwać. Limit CZEKANIA NA ZAMEK zostaje.
    conn = _run_backfill(monkeypatch)
    first_data = conn.executed.index(EP._DATA_STATEMENTS[0])
    stmt_guards = [
        s for s in conn.executed[:first_data] if s.startswith("SET statement_timeout")
    ]
    lock_guards = [
        s for s in conn.executed[:first_data] if s.startswith("SET lock_timeout")
    ]
    assert stmt_guards[-1] == "SET statement_timeout = 0", stmt_guards
    assert lock_guards[-1] == "SET lock_timeout = '3s'", lock_guards


def test_limity_sa_zdejmowane_na_koncu(monkeypatch):
    conn = _run_backfill(monkeypatch)
    assert "SET statement_timeout = 0" in conn.executed[-3:]
    assert "SET lock_timeout = 0" in conn.executed[-3:]
