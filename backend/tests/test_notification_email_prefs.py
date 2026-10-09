"""„Maile do Ciebie” — własne wyłączniki maili konta (0427, 09.10.2026)."""

import ast
import importlib.util
from pathlib import Path

import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import notification_delivery as delivery
from app.services import notification_email_prefs as prefs
from app.services.notification_categories import types_in

_BACKEND = Path(__file__).resolve().parents[1]
_AT = "2026-10-09T08:00:00+00:00"

# Moduł wysyłający → rodzaje maili, które z niego wychodzą.
_SENDERS = {
    "app/tasks/notification_email_outbox.py": delivery.IMMEDIATE_KINDS,
    "app/tasks/chat_email_fallback.py": ("chat_unread",),
    "app/services/mention_dispatch.py": ("mentions",),
    "app/services/stage_notification_emitter.py": ("pipeline_stage",),
    "app/services/candidate_rate_change.py": ("rate_change",),
    "app/tasks/job_deadline_alerts.py": ("job_deadline",),
    "app/services/dl_alerts.py": ("delivery_alert",),
    "app/tasks/kpi_email_reports.py": ("kpi_weekly_report", "board_monthly_report"),
}


def _user(role: UserRole, *extra: UserRole, **fields) -> User:
    return User(
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value, *(r.value for r in extra)],
        is_active=True,
        daily_digest_email_enabled=True,
        email_opt_outs={},
        muted_notification_categories={},
        **fields,
    )


def _applies(user: User, ctx: prefs._Context = prefs._Context()) -> set[str]:
    return {kind for kind in prefs.OPTABLE_KINDS if prefs.APPLIES[kind](user, ctx)}


# ── Kontrakty statyczne (bez bazy) ──────────────────────────────────────────


def test_every_account_email_kind_has_an_applies_rule():
    catalog = {spec["id"] for spec in delivery.CATALOG}
    assert set(prefs.OPTABLE_KINDS) == catalog - {"application_confirmation"}
    # Nowy rodzaj w katalogu bez reguły „kogo dotyczy” nie może przejść po cichu.
    assert set(prefs.APPLIES) == set(prefs.OPTABLE_KINDS)
    assert not {spec["id"] for spec in delivery.SECURITY_CATALOG} & set(
        prefs.OPTABLE_KINDS
    )


def test_every_sender_asks_about_the_account_opt_out():
    covered: set[str] = set()
    for path, kinds in _SENDERS.items():
        tree = ast.parse((_BACKEND / path).read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"email_opted_out", "email_wanted"}
        ]
        assert calls, f"{path} wysyła maile bez pytania o wyłącznik konta"
        covered |= set(kinds)
    # Poranny skrót odsiewa konta własną kolumną już w zapytaniu.
    digest = (_BACKEND / "app/tasks/daily_digest_email.py").read_text(encoding="utf-8")
    assert "User.daily_digest_email_enabled.is_(True)" in digest
    covered.add(delivery.DIGEST_KIND)
    assert covered == set(prefs.OPTABLE_KINDS)


def test_entrypoint_mirrors_the_email_opt_outs_migration():
    path = _BACKEND / "alembic" / "versions" / "0427_user_email_opt_outs.py"
    spec = importlib.util.spec_from_file_location("m0427", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert migration.ADD_EMAIL_OPT_OUTS in entrypoint
    assert "IF NOT EXISTS" in migration.ADD_EMAIL_OPT_OUTS
    assert User.__table__.c.email_opt_outs.nullable is False


def test_opt_out_rule_reads_the_column_for_the_digest_and_json_for_the_rest():
    user = _user(UserRole.recruiter)
    assert not any(delivery.email_opted_out(user, k) for k in prefs.OPTABLE_KINDS)
    user.email_opt_outs = {"mentions": _AT, "cv_returned": ""}
    assert delivery.email_opted_out(user, "mentions")
    # Pusty znacznik nie jest wyłączeniem.
    assert not delivery.email_opted_out(user, "cv_returned")
    assert not delivery.email_opted_out(user, "daily_digest")
    user.daily_digest_email_enabled = False
    assert delivery.email_opted_out(user, "daily_digest")
    # Obiekt bez pól (atrapy w starszych testach) = nic nie wyłączone.
    assert not delivery.email_opted_out(object(), "mentions")
    assert not delivery.email_opted_out(object(), "daily_digest")
    assert delivery.email_wanted(object(), "mentions", None)


def test_reenabled_email_does_not_replay_events_from_the_switched_off_period():
    user = _user(UserRole.recruiter)
    resumed = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
    user.email_opt_outs = {delivery.RESUMED_KEY: {"job_deadline": resumed.isoformat()}}
    assert not delivery.email_opted_out(user, "job_deadline")
    assert delivery.email_resumed_at(user, "job_deadline") == resumed
    # Zdarzenie sprzed włączenia nie wychodzi; od chwili włączenia — tak.
    assert not delivery.email_wanted(user, "job_deadline", resumed - timedelta(days=21))
    assert delivery.email_wanted(user, "job_deadline", resumed)
    assert delivery.email_wanted(user, "job_deadline", resumed + timedelta(minutes=1))
    assert not delivery.email_wanted(user, "job_deadline", None)
    # Inny rodzaj nie ma progu.
    assert delivery.email_wanted(user, "mentions", resumed - timedelta(days=21))
    # `_resumed` nie jest rodzajem maila — nikt nie widzi go jako wyłączenia.
    assert not delivery.email_opted_out(user, delivery.RESUMED_KEY)


def test_queue_clause_keeps_switched_off_accounts_out_of_the_batch_in_sql():
    # Lustro `email_wanted` w zapytaniu: wiersz konta z wyłączonym mailem nie
    # może zająć paczki ani wrócić jako zaległość po ponownym włączeniu.
    clause = delivery.email_queue_clause("job_deadline", Notification.created_at)
    sql = str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "users.email_opt_outs ? 'job_deadline'" in sql
    assert "'{_resumed, job_deadline}'" in sql
    assert "notifications.created_at >=" in sql
    for path in (
        "app/tasks/job_deadline_alerts.py",
        "app/services/dl_alerts.py",
        "app/tasks/notification_email_outbox.py",
        "app/tasks/chat_email_fallback.py",
    ):
        source = (_BACKEND / path).read_text(encoding="utf-8")
        assert "email_queue_clause(" in source, path


# ── Kogo dotyczy który mail ─────────────────────────────────────────────────


def test_recruiter_sees_recruiter_emails_and_not_delivery_or_reports():
    applies = _applies(_user(UserRole.recruiter))
    assert {
        "daily_digest",
        "cv_returned",
        "request_assigned",
        "mentions",
        "chat_unread",
        "job_deadline",
        "pipeline_stage",
    } <= applies
    assert not applies & {
        "dl_review",
        "rate_change",
        "delivery_alert",
        "system_failure",
        "kpi_weekly_report",
        "board_monthly_report",
    }


def test_cpro_sender_gets_the_review_email_without_the_delivery_lead_role():
    user = _user(UserRole.recruiter)
    user.id = 90
    assert "dl_review" not in _applies(user)
    assert "dl_review" in _applies(user, prefs._Context(frozenset({90})))


def test_delivery_lead_admin_head_and_finance_get_their_own_emails():
    lead = _applies(_user(UserRole.delivery_lead))
    assert {"dl_review", "rate_change", "delivery_alert", "signature_request"} <= lead
    assert "system_failure" not in lead

    admin = _applies(_user(UserRole.admin))
    assert "system_failure" in admin
    # Admin bez roli ze skrótu nie dostaje skrótu ani alertów klientów.
    assert not admin & {"daily_digest", "delivery_alert", "rate_change"}

    head = _applies(_user(UserRole.head_of_recruitment))
    assert "kpi_weekly_report" in head
    assert "board_monthly_report" not in head

    finance = _applies(_user(UserRole.finance))
    assert {"daily_digest", "board_monthly_report"} <= finance
    # Czat nie wysyła maili kontom Finansów (lustro `chat_email_fallback`).
    assert "chat_unread" not in finance


# ── Stan wiersza w „Moje” ───────────────────────────────────────────────────


def _spec(kind: str) -> dict:
    return next(spec for spec in delivery.CATALOG if spec["id"] == kind)


def test_row_state_names_who_switched_the_email_off():
    user = _user(UserRole.recruiter)
    on = prefs._item(user, _spec("job_deadline"), company_enabled=True)
    assert (on["state"], on["receiving"], on["note"]) == ("on", True, None)

    company = prefs._item(user, _spec("job_deadline"), company_enabled=False)
    assert company["state"] == "company_off"
    assert company["self_enabled"] is True and company["receiving"] is False

    user.email_opt_outs = {"job_deadline": _AT}
    mine = prefs._item(user, _spec("job_deadline"), company_enabled=True)
    assert (mine["state"], mine["self_enabled"]) == ("self_off", False)
    # Firmowe wyłączenie wygrywa w opisie, własny wybór zostaje zapamiętany.
    both = prefs._item(user, _spec("job_deadline"), company_enabled=False)
    assert (both["state"], both["self_enabled"]) == ("company_off", False)


def test_muted_bell_category_stops_the_email_that_follows_it():
    user = _user(UserRole.recruiter)
    user.muted_notification_categories = {"deadlines": _AT}
    muted = prefs._item(user, _spec("job_deadline"), company_enabled=True)
    assert muted["state"] == "bell_muted" and muted["receiving"] is False
    assert "wyłączona przez Ciebie w dzwonku" in muted["note"]

    by_role = _user(UserRole.recruiter)
    by_role.role_muted_notification_types = frozenset(
        {NotificationType.job_chat_message}
    )
    chat = prefs._item(by_role, _spec("chat_unread"), company_enabled=True)
    assert chat["state"] == "role_muted"
    assert "tylko wzmianki z czatu" in chat["note"]
    # Maile-zadania stoją za kategorią obowiązkową — wyciszenie ich nie dotyczy.
    task = prefs._item(user, _spec("cv_returned"), company_enabled=True)
    assert task["state"] == "on"


def test_bell_types_behind_emails_sit_in_mutable_categories():
    from app.services.notification_categories import NotificationCategory

    expected = {
        "chat_unread": NotificationCategory.chat,
        "pipeline_stage": NotificationCategory.pipeline,
        "job_deadline": NotificationCategory.deadlines,
    }
    for kind, bell_type in prefs.BELL_TYPE_BY_KIND.items():
        assert bell_type in types_in(expected[kind])
        assert delivery.notification_kind(bell_type) == kind


# ── Zapis ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_switching_an_email_off_and_on_again():
    user = _user(UserRole.recruiter)
    before = user.email_opt_outs
    await prefs.set_enabled(object(), user, "mentions", False)
    assert set(user.email_opt_outs) == {"mentions"}
    # Nowy słownik — SQLAlchemy nie widzi zmian wewnątrz JSONB.
    assert user.email_opt_outs is not before
    first = user.email_opt_outs["mentions"]
    await prefs.set_enabled(object(), user, "mentions", False)
    assert user.email_opt_outs["mentions"] == first

    await prefs.set_enabled(object(), user, "daily_digest", False)
    assert user.daily_digest_email_enabled is False
    assert "daily_digest" not in user.email_opt_outs

    await prefs.set_enabled(object(), user, "mentions", True)
    await prefs.set_enabled(object(), user, "daily_digest", True)
    # Zostaje sam czas ponownego włączenia — próg dla zaległych zdarzeń.
    assert set(user.email_opt_outs) == {delivery.RESUMED_KEY}
    assert delivery.email_resumed_at(user, "mentions") is not None
    assert not delivery.email_opted_out(user, "mentions")
    assert user.daily_digest_email_enabled is True
    # Włączenie maila, który nie był wyłączony, niczego nie zapisuje.
    await prefs.set_enabled(object(), user, "cv_returned", True)
    assert delivery.email_resumed_at(user, "cv_returned") is None
    # Ponowne wyłączenie zdejmuje próg.
    await prefs.set_enabled(object(), user, "mentions", False)
    assert set(user.email_opt_outs) == {"mentions"}


@pytest.mark.asyncio
async def test_unknown_and_foreign_emails_are_refused():
    user = _user(UserRole.recruiter)
    for kind in ("application_confirmation", "password_reset", "nope"):
        with pytest.raises(prefs.UnknownEmailKind):
            await prefs.set_enabled(object(), user, kind, False)
    with pytest.raises(prefs.EmailKindNotApplicable):
        await prefs.set_enabled(object(), user, "system_failure", False)
    assert user.email_opt_outs == {}
    # Włączenie z powrotem jest dozwolone zawsze (np. po zmianie roli).
    user.email_opt_outs = {"system_failure": _AT}
    await prefs.set_enabled(object(), user, "system_failure", True)
    assert not delivery.email_opted_out(user, "system_failure")


def test_immediate_email_queue_skips_an_account_that_switched_it_off():
    from app.tasks.notification_email_outbox import _can_receive

    admin = _user(UserRole.admin)
    created = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
    notif = Notification(
        notification_type=NotificationType.automation_failing,
        title="Automat padł 3 razy",
        message="…",
        created_at=created,
    )
    assert _can_receive(admin, notif, "system_failure")
    admin.email_opt_outs = {"system_failure": _AT}
    assert not _can_receive(admin, notif, "system_failure")
    # Inny rodzaj tego samego konta zostaje.
    assert _can_receive(admin, notif, "request_assigned")
    # Włączony z powrotem po zdarzeniu — zaległość nie wychodzi.
    admin.email_opt_outs = {
        delivery.RESUMED_KEY: {
            "system_failure": (created + timedelta(hours=1)).isoformat()
        }
    }
    assert not _can_receive(admin, notif, "system_failure")


# ── Trasy (z bazą) ──────────────────────────────────────────────────────────


async def _admin(app_client: AsyncClient) -> User:
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def _reset(user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.email_opt_outs = {}
        user.daily_digest_email_enabled = True
        await db.commit()


@pytest.mark.asyncio
async def test_account_reads_and_switches_its_own_emails(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    admin = await _admin(app_client)
    try:
        view = await app_client.get(
            "/api/users/me/email-notifications", headers=app_auth_headers
        )
        assert view.status_code == 200
        body = view.json()
        mine = {item["id"]: item for item in body["items"]}
        assert mine["system_failure"]["self_enabled"] is True
        assert {ref["id"] for ref in body["always_on"]} == {
            spec["id"] for spec in delivery.SECURITY_CATALOG
        }
        listed = set(mine) | {ref["id"] for ref in body["not_applicable"]}
        assert listed == set(prefs.OPTABLE_KINDS)

        saved = await app_client.put(
            "/api/users/me/email-notifications/system_failure",
            headers=app_auth_headers,
            json={"enabled": False},
        )
        assert saved.status_code == 200
        row = next(i for i in saved.json()["items"] if i["id"] == "system_failure")
        assert row["self_enabled"] is False and row["receiving"] is False
        assert row["state"] in {"self_off", "company_off"}

        from app.models.notification import Notification as Notif

        def in_queue(event_at):
            return select(User.id).where(
                User.id == admin.id,
                delivery.email_queue_clause("system_failure", event_at),
            )

        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            stored = await db.get(User, admin.id)
            assert set(stored.email_opt_outs) == {"system_failure"}
            summary = await prefs.opt_out_summary(db)
            # Kolejka maili odsiewa konto już w zapytaniu.
            assert (await db.scalar(in_queue(now))) is None
            assert Notif.created_at is not None
        assert (admin.name or admin.email) in summary["system_failure"]

        # Administrator widzi w „Maile”, kto wyłączył mail sobie.
        overview = await app_client.get(
            "/api/settings/notification-delivery", headers=app_auth_headers
        )
        assert overview.status_code == 200
        by_kind = {item["id"]: item for item in overview.json()["types"]}
        assert (admin.name or admin.email) in by_kind["system_failure"]["self_disabled"]
        assert by_kind["password_reset"]["self_disabled"] == []

        back = await app_client.put(
            "/api/users/me/email-notifications/system_failure",
            headers=app_auth_headers,
            json={"enabled": True},
        )
        assert back.status_code == 200
        async with AsyncSessionLocal() as db:
            stored = await db.get(User, admin.id)
            assert not delivery.email_opted_out(stored, "system_failure")
            # Po włączeniu: nowe zdarzenia wracają do kolejki, zaległe nie.
            later = datetime.now(timezone.utc) + timedelta(minutes=1)
            assert (await db.scalar(in_queue(later))) == admin.id
            assert (await db.scalar(in_queue(now - timedelta(days=1)))) is None
            # Rodzaj, którego konto nie ruszało, nie ma żadnego progu.
            untouched = select(User.id).where(
                User.id == admin.id,
                delivery.email_queue_clause("cv_returned", now - timedelta(days=30)),
            )
            assert (await db.scalar(untouched)) == admin.id
    finally:
        await _reset(admin.id)


@pytest.mark.asyncio
async def test_route_refuses_unknown_and_foreign_emails(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    admin = await _admin(app_client)
    try:
        unknown = await app_client.put(
            "/api/users/me/email-notifications/application_confirmation",
            headers=app_auth_headers,
            json={"enabled": False},
        )
        assert unknown.status_code == 422
        if not admin.has_any_role(UserRole.delivery_lead):
            foreign = await app_client.put(
                "/api/users/me/email-notifications/rate_change",
                headers=app_auth_headers,
                json={"enabled": False},
            )
            assert foreign.status_code == 422
        async with AsyncSessionLocal() as db:
            assert (await db.get(User, admin.id)).email_opt_outs == {}
    finally:
        await _reset(admin.id)
