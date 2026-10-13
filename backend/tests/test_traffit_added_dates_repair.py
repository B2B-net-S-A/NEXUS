"""Naprawa dat dodania kandydatów z Traffita (13.10.2026) — „W bazie od”.

Import stemplował `candidates.created_at = NOW()`, więc osoby z Traffita miały
w bazie dzień importu. Naprawa przegląda listę `/employees/` stronami, czyta
`created_at` i zmienia WYŁĄCZNIE `candidates.source_created_at`.

Część czysta (planowanie strony) biegnie bez bazy. Część z bazą: baza testowa
jest wspólna i nie jest czyszczona — każdy test bierze własne, losowe numery
osób z Traffita, a kursor ustawia sam przed biegiem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services import traffit_added_dates_repair as repair

UTC = timezone.utc

WINTER = "2026-02-19 15:32:00"
WINTER_UTC = datetime(2026, 2, 19, 14, 32, tzinfo=UTC)
SUMMER = "2019-07-10 09:00:00"
SUMMER_UTC = datetime(2019, 7, 10, 7, 0, tzinfo=UTC)


# ── Część czysta ─────────────────────────────────────────────────────────────


def test_employee_dates_read_warsaw_time_and_skip_rows_without_id() -> None:
    dates = repair.employee_dates(
        [
            {"id": 11, "created_at": WINTER},
            {"id": 12, "created_at": SUMMER},
            {"id": 13, "created_at": None},
            {"name": "bez id", "created_at": WINTER},
            "nie słownik",
        ]
    )
    assert dates == {"11": WINTER_UTC, "12": SUMMER_UTC, "13": None}


def _row(cid: int, ext: str, *, created=None, source=None) -> repair.CandidateRow:
    return repair.CandidateRow(
        candidate_id=cid,
        external_id=ext,
        created_at=created or datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
        source_created_at=source,
    )


def test_plan_page_counts_every_case() -> None:
    later = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    dates = {
        "1": SUMMER_UTC,  # nowa data
        "2": SUMMER_UTC,  # już ustawiona
        "3": WINTER_UTC,  # inna niż zapisana
        "4": None,  # Traffit bez daty
        "5": SUMMER_UTC,  # nie ma u nas
        "6": later,  # później niż wstawienie do NEXUSA (adopcja)
    }
    rows = [
        _row(101, "1"),
        _row(102, "2", source=SUMMER_UTC),
        _row(103, "3", source=SUMMER_UTC),
        _row(106, "6"),
    ]
    changes, counts = repair.plan_page(dates, rows)
    assert counts == {
        "employees": 6,
        "no_date": 1,
        "not_in_nexus": 1,
        "unchanged": 1,
        "set": 2,
        "changed": 1,
        "later_than_created": 1,
    }
    assert {(c.candidate_id, c.old, c.new) for c in changes} == {
        (101, None, SUMMER_UTC),
        (103, SUMMER_UTC, WINTER_UTC),
        (106, None, later),
    }


# ── Część z bazą ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


class _FakeTraffit:
    """Lista `/employees/` jako strony; `fail_on` = strona, na której Traffit pada."""

    def __init__(self, pages: list[list[dict]], *, fail_on: int | None = None):
        self.pages = pages
        self.fail_on = fail_on
        self.requested: list[int] = []

    async def get_pages(self, path, *, page_size=100, start_page=1, **kw):
        assert path == "/employees/"
        for number in range(start_page, len(self.pages) + 1):
            self.requested.append(number)
            if number == self.fail_on:
                raise RuntimeError("GET /employees/ page failed: HTTP 503")
            yield number, self.pages[number - 1]


def _base_emp() -> int:
    # Poza zakresem prawdziwych id Traffita i innych testów.
    return 9_000_000_000_000 + (uuid.uuid4().int % 10**9) * 1000


async def _mk_candidate(db, *, ext: str, source: str = "traffit", src_date=None) -> int:
    cid = await db.scalar(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname, source_created_at,
                created_at, updated_at
            ) VALUES (
                :e, :s, 'A', 'B', :d,
                TIMESTAMPTZ '2026-04-16 10:00:00+00', TIMESTAMPTZ '2026-05-05 10:00:00+00'
            )
            RETURNING id
            """
        ),
        {"e": ext, "s": source, "d": src_date},
    )
    return int(cid)


async def _candidate(db, cid: int):
    row = await db.execute(
        text(
            "SELECT source_created_at, created_at, updated_at FROM candidates WHERE id = :id"
        ),
        {"id": cid},
    )
    return row.one()


async def _reset(db) -> None:
    await repair._write_setting(db, repair.STATE_KEY, {"after_page": 0})
    await db.execute(
        text("DELETE FROM app_settings WHERE key = :k"), {"k": repair.DRY_RUN_KEY}
    )
    await db.commit()


async def _fixture(db) -> SimpleNamespace:
    base = _base_emp()
    e1, e2, e3 = str(base + 1), str(base + 2), str(base + 3)
    first = await _mk_candidate(db, ext=e1)
    second = await _mk_candidate(db, ext=e2)
    # Wiersz NEXUSA z tym samym numerem w innym źródle — nie dotykamy.
    foreign = await _mk_candidate(db, ext=e1, source="talent_radar")
    await db.commit()
    await _reset(db)
    traffit = _FakeTraffit(
        [
            [{"id": int(e1), "created_at": SUMMER}, {"id": int(e3), "created_at": WINTER}],
            [{"id": int(e2), "created_at": WINTER}],
        ]
    )
    return SimpleNamespace(first=first, second=second, foreign=foreign, traffit=traffit)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_and_reports(db) -> None:
    fx = await _fixture(db)
    before = await _candidate(db, fx.first)

    report = await repair.process(db, fx.traffit, dry_run=True, pages=10)
    await repair.finish_run(db, report, started=datetime.now(UTC))

    assert await _candidate(db, fx.first) == before
    assert report["counts"]["set"] == 2
    assert report["counts"]["not_in_nexus"] == 1
    assert report["pass_complete"] is True
    assert report["traffit_rows"]["total"] >= 2
    samples = {s["candidate_id"]: s for s in report["samples"]}
    assert samples[fx.first] == {
        "candidate_id": fx.first,
        "before": None,
        "after": SUMMER_UTC.isoformat(),
    }
    assert report["dates"] == {"min": SUMMER_UTC.isoformat(), "max": WINTER_UTC.isoformat()}
    # Próba nie przesuwa kursora zapisu.
    state = await repair._read_setting(db, repair.STATE_KEY)
    assert state["after_page"] == 0
    assert await repair.fresh_dry_run_exists(db)


@pytest.mark.asyncio
async def test_apply_sets_only_the_source_date_and_is_idempotent(db) -> None:
    fx = await _fixture(db)
    before = await _candidate(db, fx.first)
    foreign_before = await _candidate(db, fx.foreign)

    report = await repair.process(db, fx.traffit, dry_run=False, pages=10)
    await repair.finish_run(db, report, started=datetime.now(UTC))

    first = await _candidate(db, fx.first)
    assert first.source_created_at == SUMMER_UTC
    # Tylko `source_created_at` — `created_at` i `updated_at` bez zmian.
    assert first.created_at == before.created_at
    assert first.updated_at == before.updated_at
    assert (await _candidate(db, fx.second)).source_created_at == WINTER_UTC
    assert await _candidate(db, fx.foreign) == foreign_before
    details = await repair._read_setting(db, repair.DETAILS_KEY)
    assert [fx.first, None] in details["before"]
    state = await repair._read_setting(db, repair.STATE_KEY)
    assert state["finished"] is True
    assert state["after_page"] == 0

    again = await repair.process(db, fx.traffit, dry_run=False, pages=10)
    assert again["counts"]["set"] == 0
    assert again["counts"]["changed"] == 0
    assert again["counts"]["unchanged"] == 2


@pytest.mark.asyncio
async def test_page_budget_and_cursor_resume(db) -> None:
    fx = await _fixture(db)

    first = await repair.process(db, fx.traffit, dry_run=False, pages=1)
    await repair.finish_run(db, first, started=datetime.now(UTC))

    assert first["pass_complete"] is False
    assert (await _candidate(db, fx.first)).source_created_at == SUMMER_UTC
    assert (await _candidate(db, fx.second)).source_created_at is None
    state = await repair._read_setting(db, repair.STATE_KEY)
    assert state["after_page"] == 1

    second = await repair.process(db, fx.traffit, dry_run=False, pages=1)
    assert fx.traffit.requested[-1] == 2
    assert second["after_page_start"] == 1
    assert (await _candidate(db, fx.second)).source_created_at == WINTER_UTC


@pytest.mark.asyncio
async def test_traffit_error_stops_with_cursor_before_the_failed_page(db) -> None:
    fx = await _fixture(db)
    fx.traffit.fail_on = 2

    report = await repair.process(db, fx.traffit, dry_run=False, pages=10)
    await repair.finish_run(db, report, started=datetime.now(UTC))

    assert report["stopped_on_error"] is True
    assert report["pass_complete"] is False
    assert report["error"] == "RuntimeError"
    state = await repair._read_setting(db, repair.STATE_KEY)
    assert state["after_page"] == 1
    assert (await _candidate(db, fx.second)).source_created_at is None


@pytest.mark.asyncio
async def test_dry_run_freshness_expires(db) -> None:
    await repair._write_setting(
        db,
        repair.DRY_RUN_KEY,
        {"finished_at": (datetime.now(UTC) - timedelta(days=8)).isoformat()},
    )
    await db.commit()
    assert not await repair.fresh_dry_run_exists(db)


@pytest.mark.asyncio
async def test_apply_without_a_dry_run_is_refused(
    app_client, app_auth_headers, monkeypatch
) -> None:
    from app.core.database import AsyncSessionLocal

    monkeypatch.setenv("TRAFFIT_TENANT", "test")
    monkeypatch.setenv("TRAFFIT_CLIENT_ID", "id")
    monkeypatch.setenv("TRAFFIT_CLIENT_SECRET", "secret")
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM app_settings WHERE key = :k"), {"k": repair.DRY_RUN_KEY}
        )
        await session.commit()

    resp = await app_client.post(
        "/api/admin/traffit/added-dates-repair?dry_run=false", headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    assert "przebieg próbny" in resp.json()["detail"]
