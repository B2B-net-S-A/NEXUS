"""``scripts/notification_mail_reconcile.py`` — ręczne rozstrzygnięcie niepewnej wysyłki.

Flaga ``email_delivery_uncertain`` chroni przed duplikatem maila, więc
narzędzie, które ją zdejmuje, musi odmówić wszystkiego poza jawnie podanym,
naprawdę niepewnym rekordem. Testy bez bazy: argumenty, maskowanie adresu,
rozpoznanie ścieżki i odmowy. Testy z bazą: podgląd nic nie zmienia, oba
tryby zapisują to, co czyta pętla wysyłki, a odmowa jednego rekordu
zatrzymuje cały bieg.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.tasks import chat_email_fallback, notification_email_outbox
from scripts import notification_mail_reconcile as tool

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


# ── bez bazy ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["--delivered"],  # bez id
        ["--resend", "--apply"],  # bez id
        ["12"],  # bez trybu
        ["12", "--delivered", "--resend"],  # dwa tryby
        ["abc", "--delivered"],  # id nie jest liczbą
        [str(i) for i in range(tool.MAX_IDS + 1)] + ["--resend"],  # masowo
    ],
)
def test_refuses_without_explicit_ids_and_one_mode(argv):
    with pytest.raises(SystemExit) as exc:
        tool.parse_args(argv)
    assert exc.value.code == 2


def test_dry_run_is_the_default_and_ids_deduplicated():
    args = tool.parse_args(["7", "7", "9", "--delivered"])
    assert args.ids == [7, 9]
    assert args.mode == "delivered"
    assert args.apply is False


def test_mask_email_keeps_only_first_letter_and_domain():
    assert tool.mask_email("jan.kowalski@example.test") == "j***@example.test"
    assert tool.mask_email(None) == "(brak adresu)"
    assert tool.mask_email("bez-malpy") == "(brak adresu)"


@pytest.mark.parametrize(
    ("ntype", "title", "entity", "path"),
    [
        (NotificationType.job_chat_message, "x", None, "chat_email_fallback"),
        (NotificationType.job_chat_mention, "x", None, "chat_email_fallback"),
        (NotificationType.job_deadline_1d, "x", "job", "job_deadline_alerts"),
        (
            NotificationType.board_task_waiting,
            "CV czeka na przegląd",
            None,
            "notification_email_outbox:dl_review",
        ),
        (NotificationType.request_assignment_changed, "x", "user", None),
    ],
)
def test_mail_path_matches_the_sending_loop(ntype, title, entity, path):
    notif = Notification(
        notification_type=ntype, title=title, related_entity_type=entity
    )
    assert tool.mail_path(notif) == path


def _row(**overrides) -> tool.Row:
    values = dict(
        id=1,
        notification_type="board_task_waiting",
        path="notification_email_outbox:dl_review",
        created_at=NOW - timedelta(hours=14),
        send_started_at=NOW - timedelta(hours=14),
        sent_at=None,
        uncertain=True,
        is_read=False,
        recipient="j***@example.test",
    )
    values.update(overrides)
    return tool.Row(**values)


def test_refuses_record_without_flag():
    rows = {1: _row(uncertain=False)}
    problems = tool.refusals(rows, [1], "delivered", NOW)
    assert len(problems) == 1 and "brak `email_delivery_uncertain`" in problems[0]


def test_refuses_missing_and_already_sent_records():
    rows = {1: _row(sent_at=NOW)}
    problems = tool.refusals(rows, [1, 2], "resend", NOW)
    assert "już ma `email_sent_at`" in problems[0]
    assert "nie ma takiego" in problems[1]


def test_resend_refused_when_no_loop_would_send_it():
    old = {1: _row(created_at=NOW - timedelta(hours=25))}
    assert "outbox go już nie wyśle" in tool.refusals(old, [1], "resend", NOW)[0]
    # Oznaczenie dostawy starego rekordu jest w porządku — nic nie wysyła.
    assert tool.refusals(old, [1], "delivered", NOW) == []

    orphan = {1: _row(path=None)}
    assert "nie ma pętli wysyłki" in tool.refusals(orphan, [1], "resend", NOW)[0]


def test_flagged_records_pass_in_both_modes():
    rows = {1: _row(), 2: _row(id=2, path="chat_email_fallback")}
    assert tool.refusals(rows, [1, 2], "resend", NOW) == []
    assert tool.refusals(rows, [1, 2], "delivered", NOW) == []


# ── z bazą (Postgres w CI) ──────────────────────────────────────────────────


@pytest.fixture
async def seeded():
    """Osoba + powiadomienia: dwa niepewne (outbox, czat) i jedno bez flagi."""
    attempt = datetime.now(timezone.utc) - timedelta(hours=1)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"reconcile-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("T3st_pass_xxxxxxx!"),
            name="Reconcile",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()

        def notif(ntype, title, uncertain):
            return Notification(
                user_id=user.id,
                title=title,
                message="m",
                notification_type=ntype,
                is_read=False,
                created_at=attempt - timedelta(minutes=20),
                email_send_started_at=attempt,
                email_delivery_uncertain=uncertain,
            )

        outbox = notif(NotificationType.board_task_waiting, "CV czeka", True)
        chat = notif(NotificationType.job_chat_message, "Wiadomość", True)
        clean = notif(NotificationType.board_task_waiting, "CV czeka", False)
        db.add_all([outbox, chat, clean])
        await db.commit()
        ids = {"outbox": outbox.id, "chat": chat.id, "clean": clean.id}
        user_id = user.id
    yield {**ids, "attempt": attempt}
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def _state(notif_id: int) -> Notification:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Notification).where(Notification.id == notif_id))


async def test_dry_run_changes_nothing(seeded, capsys):
    async with AsyncSessionLocal() as db:
        code = await tool.run(db, [seeded["outbox"]], "delivered", do_apply=False)
    assert code == tool.EXIT_OK
    row = await _state(seeded["outbox"])
    assert row.email_delivery_uncertain is True
    assert row.email_sent_at is None
    out = capsys.readouterr().out
    assert "board_task_waiting" in out and "r***@example.com" in out
    assert "reconcile-" not in out  # adres tylko zamaskowany


async def test_refusal_of_one_record_stops_the_whole_run(seeded, capsys):
    async with AsyncSessionLocal() as db:
        code = await tool.run(
            db, [seeded["outbox"], seeded["clean"]], "resend", do_apply=True
        )
    assert code == tool.EXIT_REFUSED
    assert "brak `email_delivery_uncertain`" in capsys.readouterr().err
    row = await _state(seeded["outbox"])
    assert row.email_delivery_uncertain is True


async def test_delivered_stamps_the_attempt_time(seeded):
    async with AsyncSessionLocal() as db:
        code = await tool.run(db, [seeded["outbox"]], "delivered", do_apply=True)
    assert code == tool.EXIT_OK
    row = await _state(seeded["outbox"])
    assert row.email_delivery_uncertain is False
    assert row.email_sent_at == row.email_send_started_at
    assert abs(row.email_sent_at - seeded["attempt"]) < timedelta(seconds=1)
    # Pętla go już nie weźmie.
    async with AsyncSessionLocal() as db:
        assert await notification_email_outbox._claim(db, seeded["outbox"]) is False


async def test_resend_makes_both_loops_claim_the_record_again(seeded):
    ids = [seeded["outbox"], seeded["chat"]]
    async with AsyncSessionLocal() as db:
        code = await tool.run(db, ids, "resend", do_apply=True)
    assert code == tool.EXIT_OK
    for notif_id in ids:
        row = await _state(notif_id)
        assert row.email_delivery_uncertain is False
        assert row.email_sent_at is None
        assert row.email_next_attempt_at is None
    async with AsyncSessionLocal() as db:
        assert await notification_email_outbox._claim(db, seeded["outbox"]) is True
        assert await chat_email_fallback._claim_notification(db, seeded["chat"]) is True


async def test_second_run_is_refused_after_the_flag_is_gone(seeded):
    async with AsyncSessionLocal() as db:
        assert await tool.run(db, [seeded["chat"]], "resend", do_apply=True) == 0
    async with AsyncSessionLocal() as db:
        code = await tool.run(db, [seeded["chat"]], "resend", do_apply=True)
    assert code == tool.EXIT_REFUSED
