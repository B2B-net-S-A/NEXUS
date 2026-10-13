"""Traffit wyłączony na stałe (decyzja Artura 14.10.2026) — wejścia odmawiają.

Do 14.10 import zatrzymywała tylko zmienna `TRAFFIT_SYNC_ENABLED=false`, którą
da się włączyć z powrotem, a część torów (przeniesienie fal, scalenie
bliźniaków, naprawy dat i notatek, poller kontaktów, zapis JJIT do Traffita)
jej nie czytała. Te testy pilnują, że żadne wejście nie dochodzi do Traffita,
także z flagami ustawionymi na „włączone”.

Bez bazy: trasy wołane wprost (ciało handlera, po bramce uprawnień), pętle
z podmienionym snem, CLI w procesie. Pełna ścieżka HTTP z logowaniem admina
jest w `test_fix48_ws08_admin_traffit_http.py` (wymaga Postgresa).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api import admin_traffit
from app.core.config import Settings, settings
from app.core.rate_limit import limiter
from app.services.traffit_retired import (
    TRAFFIT_RETIRED_MESSAGE,
    TRAFFIT_RETIRED_ON,
    TraffitRetiredError,
    refuse_traffit,
)
from tests.test_uptime_probe_health_checks import _payload, requires_jq
from tests.test_uptime_probe_health_checks import _run as _run_probe

MESSAGE = (
    "Traffit jest wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita."
)


def _never(*_args, **_kwargs):
    raise AssertionError("wejście Traffita doszło dalej niż strażnik")


async def _never_async(*_args, **_kwargs):
    raise AssertionError("wejście Traffita doszło dalej niż strażnik")


# ── Strażnik i flagi ─────────────────────────────────────────────────────────


def test_guard_refuses_with_the_decision_message() -> None:
    assert TRAFFIT_RETIRED_MESSAGE == MESSAGE
    assert TRAFFIT_RETIRED_ON.isoformat() == "2026-10-14"
    with pytest.raises(TraffitRetiredError) as exc:
        refuse_traffit("test")
    assert str(exc.value) == MESSAGE
    assert exc.value.entry == "test"
    # Nie `RuntimeError`: `TraffitConfig.from_env()` zgłasza brak sekretów jako
    # RuntimeError i wołający łapią go jako „pomiń bieg” — wyłączenie nie może
    # się pod to podszyć.
    assert not isinstance(exc.value, RuntimeError)


def test_traffit_flags_stay_off_even_when_env_turns_them_on(monkeypatch) -> None:
    monkeypatch.setenv("TRAFFIT_SYNC_ENABLED", "true")
    monkeypatch.setenv("CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED", "true")
    fresh = Settings()
    assert fresh.TRAFFIT_SYNC_ENABLED is False
    assert fresh.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED is False

    explicit = Settings(
        TRAFFIT_SYNC_ENABLED=True, CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED=True
    )
    assert explicit.TRAFFIT_SYNC_ENABLED is False
    assert explicit.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED is False


# ── Pętle w tle ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_sync_loop_does_not_start_even_with_flag_on(
    monkeypatch, caplog
) -> None:
    from app.tasks import traffit_sync

    # `setattr` omija walidator ustawień — symuluje kogoś, kto „włączył” flagę.
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    monkeypatch.setattr(traffit_sync.asyncio, "sleep", _never_async)
    monkeypatch.setattr(traffit_sync, "run_traffit_sync", _never_async)
    monkeypatch.setattr(traffit_sync, "AsyncSessionLocal", _never)

    with caplog.at_level(logging.INFO, logger=traffit_sync.logger.name):
        result = await asyncio.wait_for(traffit_sync.traffit_daily_sync_loop(), 2)

    assert result is None
    lines = [r.getMessage() for r in caplog.records if MESSAGE in r.getMessage()]
    assert len(lines) == 1, caplog.text


@pytest.mark.asyncio
async def test_contact_intake_loop_does_not_start_even_with_flags_on(
    monkeypatch, caplog
) -> None:
    from app.tasks import candidate_contact_traffit as intake

    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_ACTIVATION_AT",
        datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(intake.asyncio, "sleep", _never_async)
    monkeypatch.setattr(intake, "_poll_traffit_config", _never)
    monkeypatch.setattr(intake, "TraffitClient", _never)

    with caplog.at_level(logging.INFO, logger=intake.logger.name):
        result = await asyncio.wait_for(intake.traffit_contact_intake_loop(), 2)

    assert result is None
    lines = [r.getMessage() for r in caplog.records if MESSAGE in r.getMessage()]
    assert len(lines) == 1, caplog.text


# ── CLI ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["import_traffit", "--phase", "reconcile"],
        ["import_traffit", "--phase", "candidates", "--dry-run"],
    ],
)
def test_cli_exits_nonzero_with_the_message(monkeypatch, capsys, argv) -> None:
    from app.cli import import_traffit

    monkeypatch.setattr(import_traffit.sys, "argv", argv)
    monkeypatch.setattr(import_traffit, "_run", _never_async)
    monkeypatch.setattr(import_traffit, "TraffitClient", _never)

    with pytest.raises(SystemExit) as exc:
        import_traffit.main()

    assert exc.value.code not in (0, None)
    assert MESSAGE in capsys.readouterr().err


# ── JJIT: zapis kandydata do Traffita ────────────────────────────────────────


@pytest.mark.asyncio
async def test_jjit_writer_never_calls_traffit(monkeypatch) -> None:
    from app.services.integrations.jjit.traffit_writer import TraffitWriter

    monkeypatch.setenv("TRAFFIT_TENANT", "fikcyjny")
    monkeypatch.setenv("JJIT_TRAFFIT_CLIENT_ID", "id")
    monkeypatch.setenv("JJIT_TRAFFIT_CLIENT_SECRET", "sekret")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"access_token": "t", "id": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        writer = TraffitWriter(http)
        # Runner JJIT omija Traffita, gdy zapis nie jest skonfigurowany —
        # kandydat idzie wtedy tylko do NEXUSA.
        assert writer.configured is False
        assert await writer.search_by_email("anna@example.com") is None
        with pytest.raises(TraffitRetiredError):
            await writer.create_candidate({"email": "anna@example.com"})
        with pytest.raises(TraffitRetiredError):
            await writer.upload_cv(1, b"%PDF", "cv.pdf", "application/pdf")

    assert calls == []


# ── Trasy admina: 410 zamiast importu (także próba) ──────────────────────────

_CALLER = SimpleNamespace(user=SimpleNamespace(id=1), audit_label="admin:test")


def _route_calls():
    """Każda trasa POST admin_traffit z jawnymi parametrami (bez `Query(...)`)."""
    return [
        (
            "sync delta",
            lambda: admin_traffit.trigger_traffit_sync(
                request=None, _caller=_CALLER, mode="delta", phases=None
            ),
        ),
        (
            "sync full",
            lambda: admin_traffit.trigger_traffit_sync(
                request=None, _caller=_CALLER, mode="full", phases="candidates"
            ),
        ),
        (
            "notes-repair próba",
            lambda: admin_traffit.trigger_traffit_notes_repair(
                request=None, _caller=_CALLER, dry_run=True, db=object()
            ),
        ),
        (
            "notes-repair zapis",
            lambda: admin_traffit.trigger_traffit_notes_repair(
                request=None, _caller=_CALLER, dry_run=False, db=object()
            ),
        ),
        (
            "notes-repair/recruitments",
            lambda: admin_traffit.trigger_traffit_note_recruitments(
                request=None, _caller=_CALLER, dry_run=True, limit=10, db=object()
            ),
        ),
        (
            "file-dates-repair",
            lambda: admin_traffit.trigger_traffit_file_dates_repair(
                request=None, _caller=_CALLER, dry_run=True, limit=10, db=object()
            ),
        ),
        (
            "added-dates-repair",
            lambda: admin_traffit.trigger_traffit_added_dates_repair(
                request=None, _caller=_CALLER, dry_run=True, pages=1, db=object()
            ),
        ),
        (
            "transfer próba",
            lambda: admin_traffit.trigger_traffit_transfer(
                request=None,
                caller=_CALLER,
                dry_run=True,
                client_id=1,
                job_ids=None,
                active_days=30,
                include_twins=False,
                db=object(),
            ),
        ),
        (
            "transfer bez fali",
            lambda: admin_traffit.trigger_traffit_transfer(
                request=None,
                caller=_CALLER,
                dry_run=False,
                client_id=None,
                job_ids=None,
                active_days=30,
                include_twins=True,
                db=object(),
            ),
        ),
        (
            "twins-merge próba",
            lambda: admin_traffit.trigger_traffit_twins_merge(
                request=None, caller=_CALLER, dry_run=True, job_ids="1", db=object()
            ),
        ),
        (
            "twins-merge zapis",
            lambda: admin_traffit.trigger_traffit_twins_merge(
                request=None, caller=_CALLER, dry_run=False, job_ids=None, db=object()
            ),
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,call", _route_calls(), ids=[n for n, _ in _route_calls()]
)
async def test_every_import_route_answers_410(monkeypatch, name, call) -> None:
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    monkeypatch.setattr(admin_traffit, "spawn", _never)
    monkeypatch.setattr(
        admin_traffit, "TraffitConfig", SimpleNamespace(from_env=_never)
    )

    with pytest.raises(HTTPException) as exc:
        await call()

    assert exc.value.status_code == 410, name
    assert exc.value.detail == MESSAGE


def test_every_post_route_of_the_module_is_covered() -> None:
    """Nowa trasa POST w admin_traffit musi dostać strażnika i wpis wyżej."""
    posts = sorted(
        route.endpoint.__name__
        for route in admin_traffit.router.routes
        if "POST" in getattr(route, "methods", set())
    )
    assert posts == [
        "trigger_traffit_added_dates_repair",
        "trigger_traffit_file_dates_repair",
        "trigger_traffit_note_recruitments",
        "trigger_traffit_notes_repair",
        "trigger_traffit_sync",
        "trigger_traffit_transfer",
        "trigger_traffit_twins_merge",
    ]


# ── Status i health: odczyt zostaje, bez łączenia się z Traffitem ────────────


class _FakeDb:
    async def execute(self, *_args, **_kwargs):
        return []

    async def scalar(self, *_args, **_kwargs):
        return 0


@pytest.mark.asyncio
async def test_status_payload_says_traffit_is_retired(monkeypatch) -> None:
    from app.services.traffit_status import read_traffit_status

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    body = await read_traffit_status(_FakeDb())
    assert body["enabled"] is False
    assert body["retired_on"] == "2026-10-14"
    assert body["retired_message"] == MESSAGE


@pytest.mark.asyncio
async def test_health_reports_traffit_disabled_without_reading_the_watermark(
    monkeypatch,
) -> None:
    """Flaga „włączona” i sekrety ustawione: stary kod szedł do bazy po
    `__daily__` (i bez bazy dawał `degraded`). Teraz stała wartość."""
    from app.main import app

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    monkeypatch.setenv("TRAFFIT_TENANT", "fikcyjny")
    monkeypatch.setenv("TRAFFIT_CLIENT_SECRET", "sekret")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        response = await ac.get("/api/health")

    assert response.json()["checks"]["traffit"] == "disabled"


@requires_jq
def test_disabled_traffit_check_does_not_page(tmp_path: Path) -> None:
    """`disabled` nie otwiera alarmu w uptime-probe (najwyżej ostrzeżenie,
    jak dotychczasowe `unconfigured`)."""
    code, outputs, annotations = _run_probe(tmp_path, _payload(traffit="disabled"))
    assert code == 0
    assert outputs.get("fail") == "0"
    assert not [a for a in annotations if a.startswith("::error") and "traffit" in a]
