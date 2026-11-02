"""Licznik użycia obszarów: co liczymy, czego nie, i że nie psuje żądań."""

from __future__ import annotations

import csv
import io
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import access_usage_middleware
from app.core.access_usage_middleware import AccessUsageMiddleware
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.access_usage import AccessUsageDaily
from app.models.user import User, UserRole
from app.services import access_usage
from app.services.access_usage import (
    ADMINISTRACJA,
    AREA_BY_SCREEN,
    AREA_LABELS,
    EKSPORTY,
    FINANSE,
    GENERATOR_B2B,
    HR,
    KANDYDACI,
    KONTRAKTY,
    TABLICA,
    UNTRACKED_SCREENS,
    AreaUsage,
    Review,
    ReviewRow,
    area_for_request,
    build_review_rows,
)
from app.services.access_usage_schema import TABLE_DDL
from app.services.section_permissions import ProductSection
from scripts.access_usage_review import write_csv

_DB = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL")
BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _empty_buffer():
    access_usage._pending.clear()
    access_usage._last_entry.clear()
    yield
    access_usage._pending.clear()
    access_usage._last_entry.clear()


def _pending_areas() -> dict[tuple[int, str], int]:
    return {
        (user_id, area): count
        for (user_id, area, _day), count in access_usage._pending.items()
    }


# ── Obszar żądania ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("screen", "path", "area"),
    [
        ("candidates", "/api/candidates/123", KANDYDACI),
        # O obszarze decyduje ekran, nie trasa, którą ekran akurat czyta.
        ("jobs", "/api/candidates/123", TABLICA),
        ("contracts", "/api/hr/config", KONTRAKTY),
        ("contracts/b2b-generator", "/api/b2b-generator/generated", GENERATOR_B2B),
        ("contracts/new", "/api/clients", KONTRAKTY),
        ("finance", "/api/finance/order-changes", FINANSE),
        ("people/team", "/api/hr/team", HR),
        ("settings/scoring", "/api/scoring-weights", ADMINISTRACJA),
        # Eksport liczy się z trasy, z każdego ekranu i bez nagłówka.
        ("jobs", "/api/candidates/export", EKSPORTY),
        (None, "/api/contracts/register/export", EKSPORTY),
        ("clients", "/api/clients/5/orders/export", EKSPORTY),
        ("finance", "/api/invoices/export.csv", EKSPORTY),
        (None, "/api/export/candidates", EKSPORTY),
    ],
)
def test_area_for_request(screen: str | None, path: str, area: str) -> None:
    assert area_for_request(screen, path) == area


@pytest.mark.parametrize(
    ("screen", "path"),
    [
        # Pomiar 02.11.2026: pulpit sam odpytuje te trasy każdemu po wejściu.
        ("dashboard", "/api/jobs"),
        ("dashboard", "/api/kpis/me/today"),
        ("dashboard", "/api/order-mail/queue"),
        ("dashboard", "/api/finance/order-changes/summary"),
        ("dashboard", "/api/b2b-generator/esign/mine"),
        # Bez nagłówka: karta w tle, wtyczka, skrypt z tokenem osoby.
        (None, "/api/candidates/123"),
        ("", "/api/candidates/123"),
        # Własny plik osoby to nie eksport danych firmy.
        ("my-time", "/api/hr/time/me/export.csv"),
        (None, "/api/hr/time/me/export.csv"),
        ("profile", "/api/auth/me"),
        ("settings", "/api/users/me"),
        # Wartość spoza mapy nie ma którędy trafić do tabeli.
        ("x" * 40, "/api/candidates"),
        ("cokolwiek-z-zewnatrz", "/api/candidates"),
    ],
)
def test_requests_that_are_not_counted(screen: str | None, path: str) -> None:
    assert area_for_request(screen, path) is None


def test_every_frontend_screen_has_a_decision() -> None:
    """Nowy ekran ma trafić na przegląd albo świadomie poza niego, nie po cichu."""
    app_dir = BACKEND.parent / "frontend/src/app"
    screens = {
        entry.name
        for entry in app_dir.iterdir()
        if entry.is_dir()
        and not entry.name.startswith(("_", "("))
        and entry.name not in {"fonts", "403"}
    }
    decided = {screen.split("/")[0] for screen in AREA_BY_SCREEN} | UNTRACKED_SCREENS
    assert not screens - decided, (
        f"Ekrany bez decyzji: {sorted(screens - decided)}. Dopisz je do "
        "`AREA_BY_SCREEN` albo `UNTRACKED_SCREENS` w `services/access_usage.py`."
    )
    assert not set(AREA_BY_SCREEN) & UNTRACKED_SCREENS
    assert set(AREA_BY_SCREEN.values()) <= set(AREA_LABELS)


def test_one_entry_per_gap_but_every_export_counts(monkeypatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(access_usage.time, "monotonic", lambda: clock["now"])

    for _ in range(5):
        access_usage.record_entry(7, KANDYDACI)
    access_usage.record_entry(7, TABLICA)
    for _ in range(3):
        access_usage.record_entry(7, EKSPORTY)
    assert _pending_areas() == {(7, KANDYDACI): 1, (7, TABLICA): 1, (7, EKSPORTY): 3}

    clock["now"] += access_usage.ENTRY_GAP_SECONDS
    access_usage.record_entry(7, KANDYDACI)
    assert _pending_areas()[(7, KANDYDACI)] == 2


def test_new_day_starts_a_new_entry_inside_the_gap(monkeypatch) -> None:
    monkeypatch.setattr(access_usage.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(access_usage, "business_today", lambda: date(2026, 11, 2))
    access_usage.record_entry(7, KANDYDACI)
    monkeypatch.setattr(access_usage, "business_today", lambda: date(2026, 11, 3))
    access_usage.record_entry(7, KANDYDACI)

    assert access_usage._pending[(7, KANDYDACI, date(2026, 11, 2))] == 1
    assert access_usage._pending[(7, KANDYDACI, date(2026, 11, 3))] == 1


# ── Middleware ────────────────────────────────────────────────────────────────


class _PassThrough(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


def _counted_app() -> FastAPI:
    """Układ jak w aplikacji: `BaseHTTPMiddleware` między trasą a licznikiem."""

    app = FastAPI()

    @app.get("/api/candidates/{candidate_id}")
    async def candidate(candidate_id: int, request: Request):
        request.state.access_usage_user_id = 7
        return {"id": candidate_id}

    @app.get("/api/candidates/{candidate_id}/denied")
    async def denied(candidate_id: int, request: Request):
        request.state.access_usage_user_id = 7
        raise HTTPException(status_code=403, detail="nie")

    @app.get("/api/contracts/anonymous")
    async def anonymous():
        return {}

    app.add_middleware(_PassThrough)
    app.add_middleware(AccessUsageMiddleware)
    return app


async def _get(
    app: FastAPI, *paths: str, screen: str | None = "candidates"
) -> list[int]:
    headers = {"X-Nexus-Screen": screen} if screen else {}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return [(await client.get(path, headers=headers)).status_code for path in paths]


async def test_switched_off_by_default_counts_nothing() -> None:
    assert settings.ACCESS_USAGE_COUNTER_ENABLED is False

    assert await _get(_counted_app(), "/api/candidates/1") == [200]

    assert not access_usage._pending


async def test_counts_a_successful_entry_of_a_known_person(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ACCESS_USAGE_COUNTER_ENABLED", True)

    await _get(_counted_app(), "/api/candidates/1", "/api/candidates/2?q=tajne")

    # Dwa żądania tego samego ekranu to jedno wejście.
    assert _pending_areas() == {(7, KANDYDACI): 1}


async def test_background_request_from_the_dashboard_is_not_counted(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ACCESS_USAGE_COUNTER_ENABLED", True)

    await _get(_counted_app(), "/api/candidates/1", screen="dashboard")
    await _get(_counted_app(), "/api/candidates/1", screen=None)

    assert not access_usage._pending


async def test_does_not_count_denial_or_anonymous(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ACCESS_USAGE_COUNTER_ENABLED", True)

    statuses = await _get(
        _counted_app(), "/api/candidates/1/denied", "/api/contracts/anonymous"
    )

    assert statuses == [403, 200]
    assert not access_usage._pending


async def test_stored_key_holds_no_record_ids_or_query(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ACCESS_USAGE_COUNTER_ENABLED", True)

    await _get(_counted_app(), "/api/candidates/424242?q=Kowalski")

    assert list(access_usage._pending)[0][:2] == (7, KANDYDACI)
    assert "424242" not in repr(access_usage._pending)
    assert "Kowalski" not in repr(access_usage._pending)


async def test_counter_failure_does_not_break_the_response(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ACCESS_USAGE_COUNTER_ENABLED", True)

    def boom(_user_id: int, _area: str) -> None:
        raise RuntimeError("licznik padł")

    monkeypatch.setattr(access_usage_middleware, "record_entry", boom)

    assert await _get(_counted_app(), "/api/candidates/1") == [200]


# ── Zapis ─────────────────────────────────────────────────────────────────────


class _BrokenSession:
    async def __aenter__(self):
        raise ConnectionError("baza leży")

    async def __aexit__(self, *_exc):
        return False


async def test_failed_flush_keeps_the_counts_for_the_next_try(monkeypatch) -> None:
    monkeypatch.setattr(access_usage, "AsyncSessionLocal", _BrokenSession)
    access_usage.record_entry(7, EKSPORTY)
    access_usage.record_entry(7, EKSPORTY)

    with pytest.raises(ConnectionError):
        await access_usage.flush_pending()

    assert _pending_areas() == {(7, EKSPORTY): 2}


async def test_empty_flush_does_not_touch_the_database(monkeypatch) -> None:
    monkeypatch.setattr(access_usage, "AsyncSessionLocal", _BrokenSession)

    assert await access_usage.flush_pending() == 0


# ── Lista do przeglądu ────────────────────────────────────────────────────────


def _person(user_id: int, role: UserRole, **sections: str) -> User:
    user = User(
        id=user_id, email=f"osoba{user_id}@example.test", name=f"Osoba {user_id}"
    )
    user.role = role
    user.roles = [role.value]
    user.effective_section_access = {
        section.value: sections.get(section.value, "none") for section in ProductSection
    }
    user.effective_action_access = {}
    return user


def test_review_lists_access_with_zero_and_skips_areas_without_access() -> None:
    person = _person(1, UserRole.recruiter, sourcing="write", pipeline="write")
    usage = {
        (1, KANDYDACI): AreaUsage(
            entries=40, active_days=12, last_day=date(2026, 11, 2)
        )
    }

    rows = {row.area: row for row in build_review_rows([person], usage)}

    assert set(rows) == {KANDYDACI, TABLICA}
    assert rows[KANDYDACI].unused is False
    assert rows[KANDYDACI].active_days == 12
    assert rows[TABLICA].entries == 0
    assert rows[TABLICA].unused is True


def test_review_shows_entries_without_access_but_not_as_unused() -> None:
    person = _person(1, UserRole.recruiter, sourcing="read")
    usage = {
        (1, FINANSE): AreaUsage(entries=3, active_days=1, last_day=date(2026, 11, 2))
    }

    rows = {row.area: row for row in build_review_rows([person], usage)}

    assert rows[FINANSE].has_access is False
    assert rows[FINANSE].unused is False


def test_exports_have_no_single_gate_so_never_read_as_unused() -> None:
    person = _person(1, UserRole.recruiter, sourcing="write")
    usage = {
        (1, EKSPORTY): AreaUsage(entries=2, active_days=2, last_day=date(2026, 11, 1))
    }

    without_use = {row.area for row in build_review_rows([person], {})}
    rows = {row.area: row for row in build_review_rows([person], usage)}

    assert EKSPORTY not in without_use
    assert rows[EKSPORTY].has_access is None
    assert rows[EKSPORTY].unused is False


def test_review_csv_filters_unused_only() -> None:
    def row(area: str, has_access: bool | None, entries: int) -> ReviewRow:
        return ReviewRow(
            user_id=1,
            full_name="Osoba",
            email="osoba@example.test",
            roles=("recruiter",),
            area=area,
            has_access=has_access,
            entries=entries,
            active_days=1 if entries else 0,
            last_day=date(2026, 11, 2) if entries else None,
        )

    review = Review(
        since=date(2026, 10, 6),
        until=date(2026, 11, 2),
        collected_days=28,
        rows=(row(KANDYDACI, True, 9), row(TABLICA, True, 0), row(EKSPORTY, None, 2)),
    )

    out = io.StringIO()
    assert write_csv(review, out, unused_only=True) == 1
    parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert [line["obszar"] for line in parsed] == [AREA_LABELS[TABLICA]]
    assert parsed[0]["ma_dostep"] == "tak"
    assert parsed[0]["wejscia"] == "0"


# ── Rejestry i lustro schematu ────────────────────────────────────────────────


def test_schema_has_one_source_and_a_mirror() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import access_usage_schema" in entrypoint
    assert "*_ACCESS_USAGE_TABLE_DDL," in entrypoint
    migration = (BACKEND / "alembic/versions/0630_access_usage_daily.py").read_text(
        encoding="utf-8"
    )
    assert "from app.services.access_usage_schema import TABLE_DDL" in migration


def test_model_columns_match_the_ddl() -> None:
    columns = {
        line.split()[0]
        for line in TABLE_DDL[0].splitlines()[1:]
        if line.split()[0] not in {"PRIMARY", ")"}
    }
    assert columns == set(AccessUsageDaily.__table__.columns.keys())


def test_table_holds_only_the_agreed_columns() -> None:
    """Rozszerzenie o treść albo id rekordu to nowa decyzja, nie dopisek w PR-ze."""
    assert set(AccessUsageDaily.__table__.columns.keys()) == {
        "user_id",
        "area",
        "day",
        "entries",
    }


def test_retention_is_90_days() -> None:
    assert settings.ACCESS_USAGE_RETENTION_DAYS == 90


def test_header_is_allowed_by_cors() -> None:
    """Bez tego włączony licznik wywróciłby w przeglądarce każde żądanie."""
    from app.main import app

    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert "X-Nexus-Screen" in cors.kwargs["allow_headers"]


# ── Na bazie ──────────────────────────────────────────────────────────────────


async def _user(role: str) -> tuple[int, dict[str, str]]:
    from app.core.security import create_access_token

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"usage-{role}-{tag}@example.com",
            name=f"Licznik {role} {tag}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(
            user.id,
            role,
            roles=[role],
            authorization_version=user.authorization_version,
        )
        return user.id, {"Authorization": f"Bearer {token}"}


async def _rows(user_id: int) -> dict[tuple[str, date], int]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text(
                "SELECT area, day, entries FROM access_usage_daily "
                "WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
        return {(row.area, row.day): row.entries for row in rows}


async def _insert_row(user_id: int, area: str, day: date, entries: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(AccessUsageDaily(user_id=user_id, area=area, day=day, entries=entries))
        await db.commit()


@_DB
async def test_flush_adds_up_across_flushes() -> None:
    user_id, _headers = await _user("recruiter")
    today = business_today()

    access_usage.record_entry(user_id, EKSPORTY)
    access_usage.record_entry(user_id, EKSPORTY)
    access_usage.record_entry(user_id, TABLICA)
    assert await access_usage.flush_pending() == 2
    access_usage.record_entry(user_id, EKSPORTY)
    assert await access_usage.flush_pending() == 1

    assert await _rows(user_id) == {(EKSPORTY, today): 3, (TABLICA, today): 1}
    assert not access_usage._pending


@_DB
async def test_flush_skips_an_account_deleted_in_the_meantime() -> None:
    user_id, _headers = await _user("recruiter")
    access_usage.record_entry(user_id, KANDYDACI)
    access_usage.record_entry(2_000_000_000, KANDYDACI)

    await access_usage.flush_pending()

    assert await _rows(user_id) == {(KANDYDACI, business_today()): 1}
    assert not access_usage._pending


@_DB
async def test_prune_removes_rows_past_retention_only() -> None:
    user_id, _headers = await _user("recruiter")
    today = date(2026, 11, 2)
    cutoff = today - timedelta(days=90)
    await _insert_row(user_id, KANDYDACI, cutoff - timedelta(days=1), 5)
    await _insert_row(user_id, TABLICA, cutoff, 6)

    await access_usage.prune_expired(today=today)

    assert await _rows(user_id) == {(TABLICA, cutoff): 6}


@_DB
async def test_real_request_counts_the_person_and_ignores_admin_preview(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "ACCESS_USAGE_COUNTER_ENABLED", True)
    user_id, headers = await _user("recruiter")

    own = await app_client.get(
        "/api/jobs", headers={**headers, "X-Nexus-Screen": "jobs"}
    )
    assert own.status_code == 200
    assert _pending_areas() == {(user_id, TABLICA): 1}

    access_usage._pending.clear()
    access_usage._last_entry.clear()
    preview = await app_client.get(
        "/api/jobs",
        headers={
            **app_auth_headers,
            "X-Impersonate-User-Id": str(user_id),
            "X-Nexus-Screen": "jobs",
        },
    )
    assert preview.status_code == 200
    assert not access_usage._pending


@_DB
async def test_denied_request_is_not_counted(
    app_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "ACCESS_USAGE_COUNTER_ENABLED", True)
    _user_id, headers = await _user("recruiter")

    denied = await app_client.get(
        "/api/finance/order-changes", headers={**headers, "X-Nexus-Screen": "finance"}
    )

    assert denied.status_code == 403
    assert not access_usage._pending


@_DB
async def test_load_review_reads_the_window_and_real_access() -> None:
    user_id, _headers = await _user("recruiter")
    today = date(2026, 11, 2)
    await _insert_row(user_id, KANDYDACI, today, 4)
    await _insert_row(user_id, KANDYDACI, today - timedelta(days=3), 6)
    await _insert_row(user_id, KANDYDACI, today - timedelta(days=28), 100)

    async with AsyncSessionLocal() as db:
        review = await access_usage.load_review(db, days=28, today=today)

    rows = {row.area: row for row in review.rows if row.user_id == user_id}
    assert review.since == today - timedelta(days=27)
    assert rows[KANDYDACI].entries == 10
    assert rows[KANDYDACI].active_days == 2
    assert rows[KANDYDACI].last_day == today
    assert rows[TABLICA].unused is True
    assert FINANSE not in rows
    # Inne testy też piszą do tej tabeli, więc tylko dolna granica.
    assert review.collected_days >= 2
