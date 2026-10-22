"""Dzienna kontrola zakresu aplikacji prepów w Teams (0510) — bez bazy i Grapha.

22.10.2026 dziesięć osób (DL, Head of Recruitment, rekruterzy) było poza grupą
NEXUS-Meetings-Scope i dostawało 409 przy planowaniu prepu, a komunikat nie
mówił, KOGO dopisać. Pilnujemy: klasyfikacji odpowiedzi Grapha, treści alarmu
dla adminów, komunikatu z nazwiskiem prowadzącego i rejestracji typu.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.notification import NotificationType
from app.services import notification_access as na
from app.services import prep_meetings, teams_prep_scope as tps
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    NotificationCategory,
)
from app.services.notification_delivery import notification_kind

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, "ok"),
        (403, "outside"),
        (404, "no_mailbox"),
        (429, "unknown"),
        (500, "unknown"),
    ],
)
def test_classify_graph_status(status, expected) -> None:
    assert tps.classify(status) == expected


def _p(uid: int, name: str) -> tps.Person:
    return tps.Person(user_id=uid, name=name, email=f"{name.lower()}@example.test")


def test_alert_lists_people_with_addresses_and_the_fix() -> None:
    title, message = tps.alert_text([_p(1, "Anna"), _p(2, "Bartek")], [])
    assert title == "2 osób nie może prowadzić prepów w Teams"
    assert "Anna (anna@example.test), Bartek (bartek@example.test)" in message
    assert f"Add-DistributionGroupMember -Identity {tps.SCOPE_GROUP}" in message
    assert "Bez skrzynki" not in message


def test_alert_separates_missing_mailboxes() -> None:
    title, message = tps.alert_text([], [_p(3, "Celina")])
    assert title == "1 osoba nie może prowadzić prepów w Teams"
    assert "Bez skrzynki w Microsoft 365: Celina (celina@example.test)" in message
    assert "Poza grupą" not in message


def test_refusal_names_the_organizer() -> None:
    who = SimpleNamespace(name="Jan Nowak", email="jan.nowak@example.test")
    detail = prep_meetings.scope_refused_detail(who)
    assert "Jan Nowak (jan.nowak@example.test)" in detail
    assert "Wybierz innego prowadzącego" in detail


def test_refusal_without_name_uses_address_once() -> None:
    who = SimpleNamespace(name=None, email="x@example.test")
    detail = prep_meetings.scope_refused_detail(who)
    assert detail.count("x@example.test") == 1


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def scan(monkeypatch):
    people = [_p(1, "Anna"), _p(2, "Bartek"), _p(3, "Celina"), _p(4, "Dawid")]
    emitted: list[dict] = []

    async def fake_organizers(_db):
        return people

    async def fake_admins(_db):
        return [100, 101]

    async def fake_emit(_db, **kwargs):
        emitted.append(kwargs)
        return object()

    monkeypatch.setattr(prep_meetings, "app_only_ready", lambda: True)
    monkeypatch.setattr(tps, "organizers", fake_organizers)
    monkeypatch.setattr(tps, "_admin_ids", fake_admins)
    monkeypatch.setattr(
        "app.services.notification_triggers.emit", fake_emit, raising=True
    )
    return emitted


async def test_scan_alerts_admins_once_each(scan) -> None:
    answers = {
        "anna@example.test": "ok",
        "bartek@example.test": "outside",
        "celina@example.test": "no_mailbox",
        "dawid@example.test": "unknown",
    }

    async def probe(email):
        return answers[email]

    db = _FakeDb()
    sent = await tps.scan_once(db, probe=probe)
    assert sent == 2 and db.commits == 1
    assert {e["user_id"] for e in scan} == {100, 101}
    first = scan[0]
    assert first["ntype"] == NotificationType.teams_prep_scope_missing
    assert (first["related_entity_type"], first["related_entity_id"]) == (
        tps.ENTITY_TYPE,
        tps.ENTITY_ID,
    )
    assert "Bartek" in first["message"] and "Celina" in first["message"]
    # „Nie wiadomo” (np. 429) nie trafia na listę do dopisania.
    assert "Anna" not in first["message"] and "Dawid" not in first["message"]


async def test_scan_is_silent_when_everyone_is_in_scope(scan) -> None:
    async def probe(_email):
        return "ok"

    db = _FakeDb()
    assert await tps.scan_once(db, probe=probe) == 0
    assert scan == [] and db.commits == 0


async def test_scan_skips_without_app_only_config(scan, monkeypatch) -> None:
    monkeypatch.setattr(prep_meetings, "app_only_ready", lambda: False)

    async def probe(_email):  # pragma: no cover - nie może być wołane
        raise AssertionError("probe without app-only config")

    assert await tps.scan_once(_FakeDb(), probe=probe) == 0


def test_type_is_admin_only_system_and_mailed_at_once() -> None:
    t = NotificationType.teams_prep_scope_missing
    assert t in na.ADMIN_ONLY_NOTIFICATION_TYPES
    assert CATEGORY_BY_TYPE[t] == NotificationCategory.system
    assert notification_kind(t) == "system_failure"


def test_new_type_is_mirrored_in_entrypoint_and_migration() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    enum_block = entrypoint.split("_ENUM_STATEMENTS = [", 1)[1].split("\n]", 1)[0]
    assert "ADD VALUE IF NOT EXISTS 'teams_prep_scope_missing'" in enum_block
    migration = next(
        (BACKEND / "alembic" / "versions").glob("*_teams_prep_scope_alert.py")
    )
    assert re.search(
        r"ADD VALUE IF NOT EXISTS 'teams_prep_scope_missing'", migration.read_text()
    )


def test_loop_is_registered_in_lifespan() -> None:
    main = (BACKEND / "app" / "main.py").read_text()
    assert '"teams_prep_scope_alerts": asyncio.create_task(' in main
