"""Zwrot karty a pominięte uwagi QC (D5) — kto traci pominięcie (audyt 48 h).

Reguła: `docs/claude/rekrutacja-tablica/qc-to-nieprawda-i-jakosc-qc.md`.
Zwrot karty przywraca pominięcia uwag blokujących osób BEZ prawa wysyłki
(`recruitment_manage`). Prawo wysyłki to uprawnienie z ekranu „Osoby i role”,
zapisane w bazie — nie domyślny zestaw roli. Do 13.10.2026 funkcja czytała
domyślne role: rekruter, któremu admin nadał prawo wysyłki, tracił pominięcie,
a Delivery Lead, któremu je odebrano — zachowywał.

Testy z bazą (stan na Tablicy po zwrocie karty) są w
`test_fix48_ws11_qc_pair_status.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.models.user import User, UserRole
from app.services import cv_finding_dismissals as dismissals
from app.services import effective_access

# Prawo wysyłki zapisane w bazie (panel „Osoby i role”), inne niż domyślne roli.
DB_GRANTS = {
    10: "none",  # rekruter bez prawa wysyłki
    20: "manage",  # Delivery Lead
    30: "manage",  # rekruter, któremu admin nadał prawo wysyłki
    40: "none",  # Delivery Lead, któremu admin je odebrał
}


class _Db:
    def __init__(self, rows: list, users: list) -> None:
        self._scalars = [rows, users]
        self.updates: list = []

    async def scalars(self, _stmt):
        return SimpleNamespace(all=lambda answer=self._scalars.pop(0): answer)

    async def execute(self, stmt):
        self.updates.append(stmt)


@pytest.fixture
def db_permissions(monkeypatch: pytest.MonkeyPatch):
    async def resolve(_db, users) -> None:
        for user in users:
            user.effective_action_access = {
                "recruitment_manage": DB_GRANTS.get(user.id, "none")
            }

    monkeypatch.setattr(effective_access, "resolve_effective_access", resolve)


def _restored_ids(db: _Db) -> list[int]:
    assert len(db.updates) == 1
    params = db.updates[0].compile(dialect=postgresql.dialect()).params
    assert params["restored_reason"] == "card_returned"
    (ids,) = [v for v in params.values() if isinstance(v, list)]
    return sorted(ids)


@pytest.mark.asyncio
async def test_only_dismissals_of_people_without_send_right_in_the_db_are_spent(
    db_permissions,
) -> None:
    rows = [
        SimpleNamespace(id=1, dismissed_by_user_id=10),
        SimpleNamespace(id=2, dismissed_by_user_id=20),
        SimpleNamespace(id=3, dismissed_by_user_id=30),
        SimpleNamespace(id=4, dismissed_by_user_id=40),
        # Autor usunięty (SET NULL) — nikt nie stoi za pominięciem.
        SimpleNamespace(id=5, dismissed_by_user_id=None),
    ]
    users = [
        User(id=10, role=UserRole.recruiter, roles=[]),
        User(id=20, role=UserRole.delivery_lead, roles=[]),
        User(id=30, role=UserRole.recruiter, roles=[]),
        User(id=40, role=UserRole.delivery_lead, roles=[]),
    ]
    db = _Db(rows, users)
    spent = await dismissals.restore_on_card_return(db, 1, 2)
    assert spent == 3
    assert _restored_ids(db) == [1, 4, 5]


@pytest.mark.asyncio
async def test_dismissal_of_a_delivery_lead_survives_the_return(
    db_permissions,
) -> None:
    db = _Db(
        [SimpleNamespace(id=2, dismissed_by_user_id=20)],
        [User(id=20, role=UserRole.delivery_lead, roles=[])],
    )
    assert await dismissals.restore_on_card_return(db, 1, 2) == 0
    assert db.updates == []


@pytest.mark.asyncio
async def test_pair_without_blocking_dismissals_writes_nothing() -> None:
    db = _Db([], [])
    assert await dismissals.restore_on_card_return(db, 1, 2) == 0
    assert db.updates == []
