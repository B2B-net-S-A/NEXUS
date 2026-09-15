"""DEP-02 (audyt 14.09.2026): nieudana migracja ma być widoczna, nie ukryta.

``backend/entrypoint.sh`` CELOWO nie zatrzymuje startu, gdy ``alembic upgrade
heads`` padnie — Coolify (compose) nie ma rolling update, więc ``exit 1`` to
pętla restartów i przerwa produkcji (deploy #702, lipiec 2026). Ale do 09.2026
błąd kończył się jedną linią w logu kontenera: runtime nie mówił nic, a jedynym
sygnałem był krok alembic w deployu.

Teraz entrypoint zapisuje wynik upgrade'u do pliku, a ``/api/health`` pokazuje
``checks.migrations``:

* ``healthy`` — upgrade przy starcie przeszedł, bookmark bazy == heads kodu,
  brak osieroconych rewizji;
* ``unhealthy: …`` — rewizje się rozjechały (bookmark bazy ≠ heads kodu,
  osierocone rewizje) albo upgrade padł i nie da się odczytać rewizji;
* ``degraded: …`` — upgrade padł przy starcie, ale siatka bezpieczeństwa
  domknęła schemat i rewizje się zgadzają (np. chwilowy timeout zamka);
  ``uptime-probe.yml`` traktuje ``unhealthy`` jako błąd i otwiera issue;
  ogólny ``status`` nadal zależy wyłącznie od bazy (bez fałszywych 503);
* ``unknown`` — brak odczytu (np. baza chwilowo niedostępna).

Brak pliku statusu (start spoza entrypointu: testy, lokalny uvicorn) nie jest
awarią — ocenia się wtedy tylko rewizje.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

STATUS_FILE_ENV = "ALEMBIC_STATUS_FILE"
DEFAULT_STATUS_FILE = "/tmp/nexus-alembic-status.json"

_CREDENTIALS_RE = re.compile(r"(\w+://[^:/\s@]+:)[^@\s]+@")


def status_file_path() -> Path:
    return Path(os.environ.get(STATUS_FILE_ENV) or DEFAULT_STATUS_FILE)


def read_startup_status(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Wynik ``alembic upgrade heads`` zapisany przez entrypoint albo ``None``."""
    target = path or status_file_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "ok" in data else None


def redact(text: str) -> str:
    """Usuń hasła z adresów połączeń, zanim fragment logu trafi do Sentry."""
    return _CREDENTIALS_RE.sub(r"\1***@", text)


_REVISIONS_UNAVAILABLE: list[str] = []


def code_revisions() -> tuple[tuple[str, ...], frozenset[str]]:
    """(heads, wszystkie znane rewizje) — kod nie zmienia się w trakcie procesu.

    Porażka też jest zapamiętana: bez tego każde ``/api/health`` przechodziłoby
    synchronicznie graf migracji na pętli zdarzeń, a ``wait_for`` tego nie przerwie.
    """
    if _REVISIONS_UNAVAILABLE:
        raise RuntimeError(_REVISIONS_UNAVAILABLE[0])
    try:
        return _load_code_revisions()
    except Exception as exc:
        _REVISIONS_UNAVAILABLE.append(type(exc).__name__)
        raise


@lru_cache(maxsize=1)
def _load_code_revisions() -> tuple[tuple[str, ...], frozenset[str]]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script_location = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "alembic",
    )
    cfg = Config()
    cfg.set_main_option("script_location", script_location)
    script = ScriptDirectory.from_config(cfg)
    known = frozenset(rev.revision for rev in script.walk_revisions())
    return tuple(script.get_heads()), known


async def alembic_revision_state(session: Any) -> dict[str, Any]:
    """Bookmark bazy vs rewizje kodu. Nigdy nie rzuca — błędy jako nazwy klas."""
    from sqlalchemy import text

    out: dict[str, Any] = {}
    try:
        rows = (
            (await session.execute(text("SELECT version_num FROM alembic_version")))
            .scalars()
            .all()
        )
        out["db_versions"] = list(rows)
    except Exception as exc:  # noqa: BLE001 — diagnostyka nie może rzucać
        out["db_versions"] = []
        out["db_error"] = type(exc).__name__
    try:
        heads, known = code_revisions()
        out["code_heads"] = list(heads)
        out["orphaned"] = [v for v in out["db_versions"] if v not in known]
        out["reconcilable"] = not out["orphaned"]
    except Exception as exc:  # noqa: BLE001
        out["code_error"] = type(exc).__name__
    return out


def migrations_verdict(state: dict[str, Any], startup: Optional[dict[str, Any]]) -> str:
    """Werdykt ``checks.migrations`` z rewizji i wyniku startu."""
    startup_failed = startup is not None and not startup.get("ok")
    failure = (
        f"alembic upgrade failed at startup (exit {startup.get('exit_code')})"
        if startup_failed
        else ""
    )
    if state.get("db_error") or state.get("code_error"):
        return f"unhealthy: {failure}" if startup_failed else "unknown"
    if state.get("orphaned"):
        return f"unhealthy: orphaned revisions {','.join(state['orphaned'])}"
    db_versions = sorted(state.get("db_versions") or [])
    code_heads = sorted(state.get("code_heads") or [])
    if not db_versions:
        return f"unhealthy: {failure}" if startup_failed else "unknown"
    if db_versions != code_heads:
        return f"unhealthy: db {','.join(db_versions)} != heads {','.join(code_heads)}"
    # Chwilowa porażka przy starcie, po której rewizje się zgadzają, nie może
    # trzymać `unhealthy` (= issue co godzinę) do następnego deployu.
    return f"degraded: {failure}, revisions match" if startup_failed else "healthy"


def startup_failure_message(startup: Optional[dict[str, Any]]) -> Optional[str]:
    """Treść jednorazowego ``logger.error`` przy starcie aplikacji (→ Sentry)."""
    if startup is None or startup.get("ok"):
        return None
    tail = redact(str(startup.get("tail") or ""))[-2000:]
    return (
        "alembic upgrade heads FAILED at container start "
        f"(exit {startup.get('exit_code')}); schema relies on entrypoint safety-net. "
        f"Output tail:\n{tail}"
    )
