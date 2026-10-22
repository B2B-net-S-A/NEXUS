"""0507: dzwonek „Prep N oceniony” do ludzi pary (22.10.2026).

Lustro enuma w entrypoincie, downgrade odmawia przy żywych wpisach, treść
mówi poziom, wynik i ile punktów trafiło do notatki na Prep 2; ocena
niedostępna nie dzwoni.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.notification import NotificationType
from app.services import prep_notifications

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0507_prep_review_ready_notification.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0506", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_adds_the_same_enum_value_as_the_migration() -> None:
    module = _migration_module()
    assert (
        f"'{NotificationType.prep_review_ready.value}'" in module.ADD_NOTIFICATION_TYPE
    )
    assert module.ADD_NOTIFICATION_TYPE in (BACKEND / "entrypoint.sh").read_text()
    source = MIGRATION.read_text()
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    assert "autocommit_block()" in upgrade


def test_downgrade_only_refuses_when_such_notifications_exist(monkeypatch) -> None:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()
    assert executed == [module.REFUSE_WITH_LIVE_ROWS]
    assert "notification_type::text = 'prep_review_ready'" in executed[0]
    assert "DROP" not in executed[0] and "DELETE" not in executed[0]


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (1, "1 punkt"),
        (3, "3 punkty"),
        (5, "5 punktów"),
        (12, "12 punktów"),
        (22, "22 punkty"),
    ],
)
def test_points_plural(n: int, text: str) -> None:
    assert prep_notifications._points(n) == text


@pytest.fixture
def captured(monkeypatch):
    sent: list[dict] = []

    async def people(db, prep):
        return {7, 8}

    async def labels(db, prep):
        return "Anna Przykładowa", "Java Developer"

    async def emit(db, **kwargs):
        sent.append(kwargs)
        return len(kwargs["user_ids"])

    monkeypatch.setattr(prep_notifications, "_pair_people", people)
    monkeypatch.setattr(prep_notifications, "_labels", labels)
    monkeypatch.setattr(prep_notifications, "_emit", emit)
    return sent


PREP1 = SimpleNamespace(
    id=1, prep_no=1, calendar_event_id=603, candidate_id=2, job_id=3
)


async def test_prep1_ready_says_how_many_points_go_to_prep2(captured) -> None:
    review = SimpleNamespace(
        status="ok",
        level="ok",
        criteria={"total": 72, "followup": [{"key": "a"}, {"key": "b"}, {"key": "c"}]},
        remaining=[],
    )
    assert (
        await prep_notifications.notify_review_ready(None, prep=PREP1, review=review)
        == 2
    )
    (sent,) = captured
    assert sent["ntype"] == NotificationType.prep_review_ready
    assert sent["title"] == "Prep 1 oceniony · OK (72%)"
    assert (
        sent["message"]
        == "Anna Przykładowa — Java Developer: 3 punkty do powtórzenia na Prepie 2."
    )
    assert sent["event_id"] == 603 and sent["entity_type"] == "prep_review"


async def test_prep2_ready_counts_improved_points(captured) -> None:
    prep2 = SimpleNamespace(**{**PREP1.__dict__, "prep_no": 2})
    review = SimpleNamespace(
        status="ok",
        level="good",
        criteria={
            "total": 88,
            "comparison": [
                {"after": "strong"},
                {"after": "strong"},
                {"after": "general"},
            ],
        },
        remaining=[],
    )
    await prep_notifications.notify_review_ready(None, prep=prep2, review=review)
    assert captured[0]["message"].endswith("Z Prepu 1 poprawione 2 z 3.")


async def test_unavailable_review_does_not_ring(captured) -> None:
    review = SimpleNamespace(
        status="unavailable", level=None, criteria={}, remaining=[]
    )
    assert (
        await prep_notifications.notify_review_ready(None, prep=PREP1, review=review)
        == 0
    )
    assert captured == []
