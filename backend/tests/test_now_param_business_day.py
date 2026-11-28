"""„Teraz” podane jako parametr liczy dzień w kalendarzu firmy, nie w UTC.

Audyt 24.11.2026: `candidate_terms_apply.apply_answer` dostawał od trasy
„teraz” w UTC i robił z niego `now.date()` — o 00:30 w Warszawie to jeszcze
wczoraj. Te same funkcje niżej dziś dostają `local_now()`, ale nic tego nie
gwarantuje; każda liczy dzień przez `business_date` albo przelicza „teraz” na
Warszawę. Chwila próbna: 24.11.2026 23:30 UTC = 25.11.2026 00:30 w Warszawie.

Bez bazy: zależności z bazy są podmienione.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.services import fx_service
from app.services.hr import lifecycle_jobs
from app.tasks import start_documents_sweeper as sweeper

NIGHT_UTC = datetime(2026, 11, 24, 23, 30, tzinfo=timezone.utc)
WARSAW_DAY = date(2026, 11, 25)


class _CapturingDb:
    """Sesja, która zapamiętuje zapytanie i nic nie zwraca."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def scalars(self, statement: Any) -> list[int]:
        self.statements.append(statement)
        return []


def _claims(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    async def claim(_db: Any, kind: str, key: str, _now: datetime) -> None:
        seen.append((kind, key))
        return None

    monkeypatch.setattr(lifecycle_jobs.job_runs, "claim", claim)
    return seen


async def test_handovers_compare_last_day_with_the_warsaw_day() -> None:
    db = _CapturingDb()
    await lifecycle_jobs.run_handovers(db, NIGHT_UTC)  # type: ignore[arg-type]
    params = db.statements[0].compile(dialect=postgresql.dialect()).params
    assert WARSAW_DAY in params.values()


async def test_deactivations_ask_for_the_warsaw_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[date] = []

    async def candidates(_db: Any, today: date) -> list:
        asked.append(today)
        return []

    monkeypatch.setattr(lifecycle_jobs, "_deactivation_candidates", candidates)
    await lifecycle_jobs.run_deactivations(None, NIGHT_UTC)  # type: ignore[arg-type]
    assert asked == [WARSAW_DAY]


async def test_mass_exit_alert_is_claimed_for_the_warsaw_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _claims(monkeypatch)
    await lifecycle_jobs._alert_mass_exit(None, NIGHT_UTC, 99)  # type: ignore[arg-type]
    assert seen == [(lifecycle_jobs.MASS_EXIT_ALERT_KIND, "2026-11-25")]


async def test_monday_reminders_start_after_midnight_in_warsaw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Niedziela 29.11 23:30 UTC = poniedziałek 30.11 00:30 w Warszawie.
    seen = _claims(monkeypatch)
    sunday_night_utc = datetime(2026, 11, 29, 23, 30, tzinfo=timezone.utc)
    result = await lifecycle_jobs.run_reminders(None, sunday_night_utc)  # type: ignore[arg-type]
    assert result == {"reminders": "claimed"}
    assert seen == [(lifecycle_jobs.REMINDERS_KIND, "2026-W49")]


def test_nbp_refresh_waits_for_the_warsaw_publication_window() -> None:
    # 00:30 w Warszawie: tabela A z 25.11 wyjdzie dopiero przed południem.
    assert fx_service._should_refresh_nbp(NIGHT_UTC, date(2026, 11, 23)) is False


async def test_start_documents_wait_for_nine_in_warsaw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_db() -> None:
        raise AssertionError("przed 9:00 w Warszawie przebieg nie sięga do bazy")

    monkeypatch.setattr(sweeper, "AsyncSessionLocal", no_db)
    assert await sweeper.run_once(NIGHT_UTC) == {"recipients": 0}
