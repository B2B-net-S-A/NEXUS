"""Odczyty przełącznika urlopów w świeżym procesie ``web`` (22.11.2026).

Stan ``app_settings['hr_availability_source']`` żyje w pamięci procesu
(``availability_local._SOURCE``). W kontenerze ``worker`` odświeżają go pętle
co minutę, w ``web`` tylko żądania przez ``workforce_context``. Po wdrożeniu
pamięć jest zimna (``local=False``), więc miejsca, które czytały ją bez
odświeżenia, liczyły cele bez urlopów („Mój miesiąc”, mianowniki wyścigów),
panel propozycji mówił „brak danych o urlopach”, a powiadomienia rekrutacji
szły do nieobecnego zamiast do zastępcy — dopóki żądanie w tym procesie nie
przeszło przez ``workforce_context``.

Testy bez bazy: atrapa sesji zwraca ``local`` dla odczytu ustawienia.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.models.job import Job
from app.models.user import User
from app.services import job_membership, kpi_engine, person_workdays
from app.services import request_allocation_proposals
from app.services.hr import availability_local
from app.services.workforce_availability import Delegation, WorkforceContext

LEAVE_DAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=kpi_engine.WARSAW)


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self


class _Session:
    """Sesja żądania w ``web``: ``scalar`` to odczyt przełącznika."""

    def __init__(self, source: str | None):
        self.source = source
        self.switch_reads = 0

    async def scalar(self, _statement):
        self.switch_reads += 1
        return self.source


@pytest.fixture
def cold_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Świeży proces po wdrożeniu: przełącznik jeszcze nieprzeczytany."""
    monkeypatch.setitem(availability_local._SOURCE, "local", False)
    monkeypatch.setitem(availability_local._SOURCE, "checked", None)


# ── Cele i wyścigi: dni pracy bez urlopu ────────────────────────────────────


@pytest.mark.asyncio
async def test_cold_process_counts_nexus_absences(cold_process) -> None:
    db = _Session("local")
    assert await person_workdays.nexus_absences_known(db) is True
    # Drugi odczyt w tej samej minucie bez zapytania.
    assert await person_workdays.nexus_absences_known(db) is True
    assert db.switch_reads == 1


@pytest.mark.asyncio
async def test_cold_process_without_the_switch_keeps_calendar_days(
    cold_process,
) -> None:
    assert await person_workdays.nexus_absences_known(_Session(None)) is False


@pytest.mark.asyncio
async def test_cold_process_takes_leave_off_my_month(
    cold_process, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def days_off_for(_db, _user_id, _start, _end):
        return frozenset({LEAVE_DAY})

    monkeypatch.setattr(availability_local, "days_off_for", days_off_for)
    days = await kpi_engine.personal_days_off(
        _Session("local"), 7, NOW, onboarding=False
    )
    assert days == frozenset({LEAVE_DAY})


@pytest.mark.asyncio
async def test_switched_off_source_leaves_my_month_on_calendar(
    cold_process, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def days_off_for(*_args):
        raise AssertionError("bez źródła urlopów nie czytamy urlopów")

    monkeypatch.setattr(availability_local, "days_off_for", days_off_for)
    days = await kpi_engine.personal_days_off(_Session(None), 7, NOW, onboarding=False)
    assert days == frozenset()


# ── Panel propozycji przydziału ─────────────────────────────────────────────


@pytest.fixture
def fresh_leave_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fresh_context(db, **_kwargs):
        # Jak ``workforce_context``: najpierw odświeżenie przełącznika.
        if not await availability_local.refresh_source(db):
            return WorkforceContext()
        return WorkforceContext(fresh=True)

    monkeypatch.setattr(
        request_allocation_proposals, "workforce_context", fresh_context
    )


@pytest.mark.asyncio
async def test_cold_process_knows_leave_data_for_proposals(
    cold_process, fresh_leave_snapshot
) -> None:
    assert (
        await request_allocation_proposals.leave_data_known(_Session("local")) is True
    )


@pytest.mark.asyncio
async def test_switched_off_source_has_no_leave_data_for_proposals(
    cold_process, fresh_leave_snapshot
) -> None:
    assert await request_allocation_proposals.leave_data_known(_Session(None)) is False


# ── Powiadomienia rekrutacji: zastępca zamiast nieobecnego ─────────────────


OWNER, SUBSTITUTE = 11, 12


class _JobSession(_Session):
    """Rekrutacja z samym rekruterem prowadzącym (``OWNER``)."""

    def __init__(self, source: str | None):
        super().__init__(source)
        self.notified: set[int] = set()

    async def get(self, model, key):
        if model is Job:
            return SimpleNamespace(
                id=key, recruiter_id=OWNER, delivery_lead_id=None, tac_id=None
            )
        if model is User:
            return SimpleNamespace(id=key)
        raise AssertionError(model)

    async def execute(self, statement):
        params = statement.compile().params
        ids = next((v for v in params.values() if isinstance(v, (list, tuple))), None)
        if ids is None:  # współpracownicy
            return _Rows([])
        self.notified = set(ids)
        return _Rows(SimpleNamespace(id=uid) for uid in ids)

    async def scalars(self, _statement):  # przypisania do requestu
        return _Rows([])


@pytest.fixture
def owner_on_leave(monkeypatch: pytest.MonkeyPatch) -> None:
    async def context(db, **_kwargs):
        # Jak ``workforce_context``: bez włączonego źródła nie ma zastępstw.
        if not await availability_local.refresh_source(db):
            return WorkforceContext()
        cover = Delegation(OWNER, SUBSTITUTE, LEAVE_DAY, LEAVE_DAY, ("1",))
        return WorkforceContext(fresh=True, delegations={OWNER: cover})

    async def is_member(_db, _user, _job_id):
        return True

    async def section_access(_db, _users):
        return None

    monkeypatch.setattr(job_membership, "workforce_context", context)
    monkeypatch.setattr(job_membership, "is_member_of_job", is_member)
    monkeypatch.setattr(
        job_membership, "resolve_effective_section_access_for_users", section_access
    )
    monkeypatch.setattr(
        job_membership, "user_can_access_candidate_domain", lambda _u: True
    )
    monkeypatch.setattr(
        job_membership,
        "section_access_for_user",
        lambda _u, _s: job_membership.SectionAccess.write,
    )
    monkeypatch.setattr(
        job_membership.settings, "RECRUITMENT_ALLOCATION_ENABLED", False
    )


@pytest.mark.asyncio
async def test_cold_process_notifies_the_substitute(
    cold_process, owner_on_leave
) -> None:
    db = _JobSession("local")
    ids = await job_membership.list_job_member_ids(db, 5, include_admins=False)
    assert ids == [SUBSTITUTE]


@pytest.mark.asyncio
async def test_switched_off_source_notifies_the_owner(
    cold_process, owner_on_leave
) -> None:
    db = _JobSession(None)
    ids = await job_membership.list_job_member_ids(db, 5, include_admins=False)
    assert ids == [OWNER]
