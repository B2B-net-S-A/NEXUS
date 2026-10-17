"""Karta „Zatrudniony” bez umowy w Kontraktach — część czysta (17.10.2026).

Zapytania i dzwonek na żywej bazie: ``test_hire_contract_reminder_db.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import hire_contract_reminder as reminder

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def no_db(monkeypatch):
    """Rodzina klienta = sam klient; umowy ma osoba 2."""

    async def family(_db, client_id):
        return {client_id}

    async def with_contract(_db, *, candidate_ids, client_ids):
        return {cid for cid in candidate_ids if cid == 2}

    monkeypatch.setattr(reminder, "job_client_family", family)
    monkeypatch.setattr(reminder, "candidates_with_contract", with_contract)


@pytest.mark.asyncio
async def test_recent_hire_without_a_contract_is_missing_one(no_db):
    missing = await reminder.missing_contract_ids(
        None,
        job_client_id=5,
        hired=[
            (1, NOW - timedelta(days=3)),
            # Ma umowę u klienta — nic nie brakuje.
            (2, NOW - timedelta(days=3)),
            # Zatrudnienie sprzed ponad roku (Traffit) — to historia.
            (3, NOW - timedelta(days=reminder.MISSING_CONTRACT_HIRE_DAYS + 1)),
            (4, None),
        ],
        now=NOW,
    )

    assert missing == {1}


@pytest.mark.asyncio
async def test_recruitment_without_a_client_marks_nothing(no_db):
    assert (
        await reminder.missing_contract_ids(
            None, job_client_id=None, hired=[(1, NOW)], now=NOW
        )
        == set()
    )


def test_bell_names_the_gap_and_carries_no_amounts():
    title, message = reminder.bell_content(
        candidate_name="Ewa Przykładowa",
        job_title="Java Developer",
        job_client_name="Bank Przykładowy",
        mover_name="Olga Wzorcowa",
    )

    assert title == "Wpisz umowę: Ewa Przykładowa"
    assert "Olga Wzorcowa potwierdził(a) zatrudnienie" in message
    assert "„Java Developer” (Bank Przykładowy)" in message
    assert "W Kontraktach nie ma jej umowy" in message
    assert "zł" not in message and "PLN" not in message


def test_bell_without_a_mover_or_client_still_reads():
    _, message = reminder.bell_content(
        candidate_name="Ewa Przykładowa",
        job_title="Tester",
        job_client_name=None,
        mover_name=None,
    )

    assert message.startswith("Ktoś z zespołu potwierdził(a)")
    assert "„Tester”." in message
