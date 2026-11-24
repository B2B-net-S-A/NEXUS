"""Tick pętli triggerów commituje raz, po wszystkich triggerach (audyt R3, 24.11.2026).

Przypomnienia o zmianie stawki ustawiały dzienną flagę w pamięci procesu
przed commitem. Gdy późniejszy trigger (``_client_job_opened``,
``_job_ad_reminders``) rzucił wyjątek, cały tick szedł w rollback, a flaga
zostawała — przypomnienia tego dnia już nie wychodziły. Teraz dzienny dedup
robi ``emit`` (``ix_notif_dedup_daily``), a oba triggery mają własny
savepoint jak ``departure_care``. Bez bazy.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from app.services import notification_triggers as nt

# Środa 07.10.2026, 10:00 czasu firmy — dzień roboczy, okno 8–17.
_NOW = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)


class _Rows:
    def all(self) -> list:
        return []


class _FakeDb:
    def __init__(self) -> None:
        self.queries = 0

    @asynccontextmanager
    async def begin_nested(self):
        yield

    async def scalars(self, _stmt):
        self.queries += 1
        return _Rows()


async def test_rate_change_reminders_run_again_after_a_rolled_back_tick():
    from app.services import candidate_rate_change as svc

    db = _FakeDb()
    assert await svc.send_reminders(db, _NOW) == 0
    # Tick wycofany po przypomnieniach — kolejny tick tego dnia musi
    # przejrzeć sprawy jeszcze raz, a nie uznać dnia za załatwiony.
    assert await svc.send_reminders(db, _NOW) == 0
    assert db.queries == 2


async def test_client_job_opened_failure_does_not_break_the_tick(monkeypatch):
    from app.services import client_job_opened

    async def boom(_db, _now):
        raise RuntimeError("awaria")

    monkeypatch.setattr(client_job_opened, "emit_opened", boom)
    assert await nt._client_job_opened(_FakeDb(), _NOW) == 0


async def test_job_ad_reminders_failure_does_not_break_the_tick(monkeypatch):
    from app.services.job_ad import reminders

    async def boom(_db, _now):
        raise RuntimeError("awaria")

    monkeypatch.setattr(reminders, "send_daily", boom)
    assert await nt._job_ad_reminders(_FakeDb(), _NOW) == 0
