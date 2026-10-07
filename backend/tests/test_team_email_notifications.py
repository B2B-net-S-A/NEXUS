"""Maile do zespołu (07.10.2026): mapa rodzajów, poranny skrót, kolejka maili."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.board_tasks import BoardTasksResponse
from app.models.notification import Notification, NotificationType
from app.services import daily_digest
from app.services import notification_delivery as delivery
from app.services.stage_handoff_recipients import (
    REASON_CPRO_RETURNED,
    REASON_DL_REVIEW,
    REASON_QC_RETURNED,
    TITLE_DL_REVIEW,
    TITLE_QC_RETURNED,
)
from app.tasks import daily_digest_email, notification_email_outbox as outbox

WAW = ZoneInfo("Europe/Warsaw")


# ── Rodzaje maili ───────────────────────────────────────────────────────────


def test_catalog_has_every_new_kind_and_ids_fit_the_report_table():
    ids = {item["id"] for item in delivery.CATALOG}
    assert set(delivery.IMMEDIATE_KINDS) <= ids
    assert "daily_digest" in ids and "daily_digest" in delivery.REPORT_KINDS
    # `kpi_email_report_runs.kind` to String(32).
    assert all(len(kind) <= 32 for kind in ids)


@pytest.mark.parametrize(
    ("ntype", "title", "entity", "expected"),
    [
        (
            "board_task_waiting",
            f"{TITLE_DL_REVIEW} Jan Nowak",
            "candidate_stage",
            "dl_review",
        ),
        (
            "board_task_waiting",
            f"{TITLE_QC_RETURNED} Jan Nowak",
            "candidate_stage",
            "cv_returned",
        ),
        (
            "board_task_waiting",
            "Wrócił z kolejki Cpro: Jan Nowak",
            "candidate_stage",
            "cv_returned",
        ),
        ("request_assignment_changed", "Nowy request", "job", "request_assigned"),
        # Poranny skrót przydziałów idzie w porannym mailu dnia, nie osobno.
        ("request_assignment_changed", "Zmiany od wczoraj", "user", None),
        (
            "b2b_signature_requested",
            "Prośba",
            "b2b_generated_contract",
            "signature_request",
        ),
        ("automation_failing", "Automat", None, "system_failure"),
        ("stage_rule", "CV wysłane: Jan", "candidate_stage", None),
        ("job_chat_message", "Czat", "job", None),
    ],
)
def test_immediate_email_kind(ntype, title, entity, expected):
    assert (
        delivery.immediate_email_kind(
            NotificationType(ntype), title=title, related_entity_type=entity
        )
        == expected
    )


def test_every_immediate_kind_has_a_sql_clause():
    for kind in delivery.IMMEDIATE_KINDS:
        sql = str(outbox.kind_clause(kind).compile(dialect=postgresql.dialect()))
        assert "notification_type" in sql
    with pytest.raises(ValueError):
        outbox.kind_clause("pipeline_stage")


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        (REASON_DL_REVIEW, "dl_review"),
        (REASON_QC_RETURNED, "cv_returned"),
        (REASON_CPRO_RETURNED, "cv_returned"),
    ],
)
def test_bell_titles_and_email_kind_read_the_same_constants(reason, kind):
    from app.services.stage_notification_emitter import _inapp_base

    title, _message, _link = _inapp_base(
        reason=reason,
        candidate=SimpleNamespace(id=7),
        candidate_full_name="Jan Nowak",
        stage_display_name="QC CV",
        job=SimpleNamespace(id=3, title="Java Dev", working_title=None),
        mover=SimpleNamespace(name="Anna"),
    )
    assert (
        delivery.immediate_email_kind(
            NotificationType.board_task_waiting,
            title=title,
            related_entity_type="candidate_stage",
        )
        == kind
    )


def test_settings_payload_accepts_every_kind_including_new_ones():
    from app.api.settings import NotificationDeliveryUpdate

    payload = NotificationDeliveryUpdate(
        enabled=True,
        types=[{"id": item["id"], "email_enabled": True} for item in delivery.CATALOG],
    )
    assert len(payload.types) == len(delivery.CATALOG)


# ── Poranny skrót ───────────────────────────────────────────────────────────


def _empty_tasks(**overrides) -> BoardTasksResponse:
    base = dict(
        cpro_to_send=[],
        cpro_sent=[],
        dl_review=[],
        window_days=14,
        dl_review_window_days=30,
        can_send_to_client=False,
    )
    base.update(overrides)
    return BoardTasksResponse(**base)


def _dl_row(i: int, name: str = "Jan Nowak") -> dict:
    return dict(
        kind="dl_review",
        stage_id=i,
        candidate_id=100 + i,
        candidate_name=name,
        job_id=5,
        job_title="Java Developer",
        client_name="Klient",
        since=datetime(2026, 10, 6, tzinfo=timezone.utc),
        process_state_version=1,
    )


def test_empty_queue_gives_no_sections():
    assert daily_digest.build_sections(_empty_tasks()) == []


def test_information_only_lists_do_not_make_a_digest():
    # Wysłane do Cpro to informacja — sama nie daje maila.
    tasks = _empty_tasks(cpro_sent=[{**_dl_row(1), "kind": "cpro_sent"}])
    assert daily_digest.build_sections(tasks) == []


def test_dl_review_section_links_to_review_and_caps_rows():
    tasks = _empty_tasks(dl_review=[_dl_row(i) for i in range(7)])
    sections = daily_digest.build_sections(tasks)
    assert sections[0].title.startswith("CV czeka na Twój przegląd")
    assert sections[0].total == 7
    assert len(sections[0].rows) == daily_digest.MAX_ROWS
    assert sections[0].rows[0].path == "/jobs/5?candidate=100&review=1"
    _subject, text, html = daily_digest.render("Ola", sections, date(2026, 10, 8))
    assert "i jeszcze 2" in text and "i jeszcze 2" in html


def test_counts_and_deadlines_make_sections():
    sections = daily_digest.build_sections(
        _empty_tasks(),
        open_client_cases=3,
        deadlines=((9, "SAP Consultant", date(2026, 10, 10)),),
    )
    titles = [s.title for s in sections]
    assert "Otwarte sprawy Twoich klientów i umów" in titles
    assert "Terminy Twoich rekrutacji w ciągu 7 dni" in titles


def test_render_escapes_html_from_data():
    tasks = _empty_tasks(dl_review=[_dl_row(1, name="<script>x</script>")])
    subject, _text, html = daily_digest.render(
        "<b>Ola</b>", daily_digest.build_sections(tasks), date(2026, 10, 8)
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>Ola</b>" not in html
    assert subject == "[Nexus] Twój dzień 08.10: 1 do zrobienia"


@pytest.mark.parametrize(
    ("moment", "due"),
    [
        (datetime(2026, 10, 8, 7, 59, tzinfo=WAW), False),
        (datetime(2026, 10, 8, 8, 0, tzinfo=WAW), True),
        (datetime(2026, 10, 8, 16, 59, tzinfo=WAW), True),
        (datetime(2026, 10, 8, 17, 0, tzinfo=WAW), False),
        (datetime(2026, 10, 10, 9, 0, tzinfo=WAW), False),  # sobota
        (datetime(2026, 11, 11, 9, 0, tzinfo=WAW), False),  # święto
    ],
)
def test_digest_window(moment, due):
    key = daily_digest_email.period_key(moment)
    assert (key == moment.date().isoformat()) if due else key is None


async def test_digest_not_due_outside_window_does_nothing(monkeypatch):
    async def boom(*_a, **_k):  # pragma: no cover — nie może być wołane
        raise AssertionError("send_report outside the window")

    monkeypatch.setattr(daily_digest_email.reports, "_send_report", boom)
    assert (
        await daily_digest_email.run_once(datetime(2026, 10, 10, 9, 0, tzinfo=WAW))
        == "not_due"
    )


# ── Kolejka maili natychmiast (Postgres) ────────────────────────────────────


async def test_outbox_does_nothing_when_policy_is_off(monkeypatch):
    async def off(_db):
        return delivery.DeliveryPolicy()

    monkeypatch.setattr(outbox, "load_policy", off)

    class NoDb:
        async def execute(self, *_a, **_k):  # pragma: no cover
            raise AssertionError("query with policy off")

    assert await outbox.dispatch(NoDb()) == 0


async def test_outbox_sends_once_with_kind_and_skips_old_and_unmapped(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserRole

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=5)
    policy = delivery.DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": cutoff.isoformat(),
            "types": {
                kind: {"email_enabled": True, "send_not_before": cutoff.isoformat()}
                for kind in delivery.ROUTINE_KINDS
            },
        }
    )

    async def enabled(_db):
        return policy

    monkeypatch.setattr(outbox, "load_policy", enabled)
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: policy)
    monkeypatch.setattr(outbox, "email_channel_enabled", lambda: True)
    sent: list[tuple[str, str]] = []

    def fake_send(to, subject, text_body, html_body=None):
        sent.append((to, subject))
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"outbox-{uuid.uuid4().hex}@example.invalid",
            password_hash="test-only",
            name="Outbox test",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        now = datetime.now(timezone.utc)
        rows = [
            Notification(
                user_id=user.id,
                notification_type=NotificationType.board_task_waiting,
                title=f"{TITLE_QC_RETURNED} Jan Nowak",
                message="Popraw CV.",
                link="/jobs/1?candidate=2",
                related_entity_type="candidate_stage",
                related_entity_id=None,
                created_at=now,
            ),
            # Sprzed włączenia — zaległość, bez maila.
            Notification(
                user_id=user.id,
                notification_type=NotificationType.board_task_waiting,
                title=f"{TITLE_DL_REVIEW} Stary",
                message="Stary.",
                created_at=cutoff - timedelta(minutes=5),
            ),
            # Typ spoza mapy — bez maila.
            Notification(
                user_id=user.id,
                notification_type=NotificationType.stage_rule,
                title="CV wysłane: Jan",
                message="Info.",
                created_at=now,
            ),
        ]
        db.add_all(rows)
        await db.commit()
        ids = [r.id for r in rows]
        try:
            await outbox.dispatch(db)
            await outbox.dispatch(db)  # drugi przebieg nic nie dokłada
            mine = [s for s in sent if s[0] == user.email]
            assert mine == [(user.email, f"[Nexus] {TITLE_QC_RETURNED} Jan Nowak")]
            stamped = (
                await db.execute(
                    select(Notification.id, Notification.email_sent_at).where(
                        Notification.id.in_(ids)
                    )
                )
            ).all()
            by_id = dict(stamped)
            assert by_id[ids[0]] is not None
            assert by_id[ids[1]] is None and by_id[ids[2]] is None
        finally:
            for row in rows:
                await db.delete(row)
            await db.delete(user)
            await db.commit()


async def test_one_failing_person_does_not_stop_the_digest(monkeypatch):
    class Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeDb:
        def begin_nested(self):
            return Nested()

    people = [SimpleNamespace(id=i) for i in (1, 2, 3)]

    async def recipients(_db):
        return people

    async def mail_for(_db, user, _today):
        if user.id == 1:
            raise RuntimeError("liczenie padło")
        if user.id == 2:
            return None  # nic nie czeka — bez maila
        return daily_digest_email.reports._Mail(
            "c@example.invalid", "s", "t", "<p>h</p>"
        )

    monkeypatch.setattr(daily_digest_email, "_recipients", recipients)
    monkeypatch.setattr(daily_digest_email, "_mail_for", mail_for)
    mails = await daily_digest_email._digest_mails(
        FakeDb(), datetime(2026, 10, 8, 8, 5, tzinfo=WAW)
    )
    assert [m.to for m in mails] == ["c@example.invalid"]
    assert mails[0].html == "<p>h</p>"


def test_digest_skips_accounts_without_pipeline_read(monkeypatch):
    from app.services.section_permissions import ProductSection, SectionAccess

    with_access = SimpleNamespace(id=1)
    without = SimpleNamespace(id=2)

    def access(user, section):
        assert section == ProductSection.pipeline
        return SectionAccess.read if user is with_access else SectionAccess.none

    monkeypatch.setattr(daily_digest_email, "section_access_for_user", access)
    assert daily_digest_email.with_pipeline_read([with_access, without]) == [
        with_access
    ]


def test_contract_number_is_url_encoded_in_links():
    tasks = _empty_tasks(
        agreements={
            "to_confirm": [
                dict(
                    generated_id=1,
                    contract_number="bez numeru&x",
                    reason="requested",
                    candidate_id=2,
                    candidate_name="Jan",
                    job_id=3,
                    job_title="Dev",
                )
            ]
        }
    )
    (section,) = daily_digest.build_sections(tasks)
    assert section.rows[0].path == "/contracts/b2b-generator?q=bez%20numeru%26x"
