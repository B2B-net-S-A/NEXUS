"""Alarm o masowym pobieraniu CV (0508, 22.10.2026) — reguły bez bazy.

Progi z ruchu produkcji (30 dni do 22.10.2026): na dysk najwyżej 20 plików
dziennie. Samo przeglądanie (podgląd w NEXUSIE) alarmu nie wywołuje —
decyzja Artura 07.11.2026. Juniorów z 12.10 łapią niższe progi nowych kont
i alarm „nowe konta naraz” za zapis na dysk.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity

from app.models.notification import Notification, NotificationType
from app.models.service_account import ServiceAccount
from app.models.user import User, UserRole
from app.services import candidate_data_access_alerts as alerts
from app.services.notification_access import (
    notification_visibility_predicate,
    unmapped_notification_types,
    user_may_receive_type,
)
from app.services.notification_categories import NotificationCategory, category_for
from app.services.notification_delivery import (
    CATALOG,
    IMMEDIATE_KINDS,
    immediate_email_kind,
)
from app.services.notification_email_prefs import APPLIES, _Context
from app.services.section_permissions import ProductSection

BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=400)
NEW = NOW - timedelta(days=3)


def _usage(created: datetime, **counts: int) -> alerts.Usage:
    return alerts.Usage(
        user_id=7, name="Jan Próbny", account_created_at=created, **counts
    )


def _user(role: UserRole, *extra: UserRole) -> User:
    return User(
        id=1,
        email="x@example.com",
        name="X",
        role=role,
        roles=[role.value, *(r.value for r in extra)],
        is_active=True,
    )


def test_busy_recruiter_day_from_production_is_not_an_alarm() -> None:
    # Maksimum zapisów na dysk z 30 dni produkcji.
    usage = _usage(OLD, candidates_today=119, disk_files_today=20)
    assert alerts.reasons(usage, new_account=False) == []


def test_viewing_alone_is_never_an_alarm() -> None:
    # 07.11.2026: podgląd setek kandydatów to praca, nie alarm bezpieczeństwa.
    for created in (OLD, NEW):
        usage = _usage(created, candidates_today=500)
        assert (
            alerts.reasons(usage, new_account=alerts.is_new_account(usage, NOW)) == []
        )
    assert not hasattr(alerts, "HOUR_CANDIDATES")


def test_thresholds_are_exclusive() -> None:
    at_limit = _usage(
        OLD,
        disk_files_today=alerts.DAY_DISK_FILES,
        export_rows_today=alerts.DAY_EXPORT_ROWS,
    )
    assert alerts.reasons(at_limit, new_account=False) == []
    over = _usage(
        OLD,
        candidates_today=999,
        disk_files_today=alerts.DAY_DISK_FILES + 1,
        export_rows_today=alerts.DAY_EXPORT_ROWS + 1,
    )
    found = alerts.reasons(over, new_account=False)
    assert len(found) == 2
    assert any("na dysk" in r for r in found)
    assert any("eksport" in r for r in found)


def test_new_account_has_half_thresholds() -> None:
    # Junior z 12.10: 13 plików na dysk i eksport 101 osób.
    usage = _usage(NEW, disk_files_today=13, export_rows_today=101)
    assert alerts.is_new_account(usage, NOW)
    assert len(alerts.reasons(usage, new_account=True)) == 2
    assert alerts.reasons(usage, new_account=False) == []


def test_account_age_decides_new_account() -> None:
    assert not alerts.is_new_account(_usage(OLD), NOW)
    assert not alerts.is_new_account(
        _usage(NOW - timedelta(days=alerts.NEW_ACCOUNT_DAYS)), NOW
    )
    assert alerts.is_new_account(_usage(NOW - timedelta(days=1)), NOW)
    unknown = alerts.Usage(user_id=1, name="X", account_created_at=None)
    assert not alerts.is_new_account(unknown, NOW)


@pytest.mark.asyncio
async def test_alarm_does_not_reach_the_person_it_is_about(monkeypatch) -> None:
    """Podejrzany admin albo HoR nie dostaje uprzedzenia o własnym alarmie."""
    subject = _usage(OLD, disk_files_today=alerts.DAY_DISK_FILES + 1)
    notified: list[list[int]] = []

    async def collect(_db, _now):
        return [subject]

    async def recipients(_db):
        return [subject.user_id, 8, 9]

    async def notify(_db, ids, **_kwargs):
        notified.append(ids)
        return len(ids)

    class _Db:
        async def commit(self) -> None:
            return None

    async def no_service_usage(_db, _now):
        return []

    monkeypatch.setattr(alerts, "collect", collect)
    monkeypatch.setattr(alerts, "collect_service", no_service_usage)
    monkeypatch.setattr(alerts, "_recipients", recipients)
    monkeypatch.setattr(alerts, "_notify", notify)

    assert await alerts.scan_once(_Db(), NOW) == 2
    assert notified == [[8, 9]]


def test_alert_text_says_nothing_was_blocked_and_how_to_react() -> None:
    usage = _usage(NEW, candidates_today=55, disk_files_today=13)
    found = alerts.reasons(usage, new_account=True)
    title, message = alerts.alert_text(usage, found, new_account=True, now=NOW)
    assert title.startswith("Jan Próbny")
    assert "pobieranie" in title and "przeglądanie" not in title
    assert "55 kandydatów" in message
    assert "09.10.2026" in message  # data założenia konta w kalendarzu firmy
    assert "niczego nie zablokował" in message
    assert "Osoby i role" in message


def test_burst_text_lists_new_accounts() -> None:
    accounts = [
        alerts.Usage(user_id=i, name=f"Osoba {i}", account_created_at=NEW)
        for i in range(12)
    ]
    title, message = alerts.burst_text(accounts)
    assert title.startswith("12 nowe konta zapisują")
    assert "Osoba 0" in message and "i 2 innych" in message


def test_type_is_system_category_and_immediate_mail() -> None:
    ntype = NotificationType.candidate_data_access_alert
    assert category_for(ntype) is NotificationCategory.system
    assert "data_access_alert" in IMMEDIATE_KINDS
    assert {spec["id"] for spec in CATALOG} >= {"data_access_alert"}
    assert (
        immediate_email_kind(ntype, title="x", related_entity_type="user")
        == "data_access_alert"
    )


def test_admin_and_head_of_recruitment_see_the_alarm_recruiter_does_not() -> None:
    ntype = NotificationType.candidate_data_access_alert
    assert user_may_receive_type(_user(UserRole.admin), ntype)
    assert user_may_receive_type(_user(UserRole.head_of_recruitment), ntype)
    # Head of Recruitment jako rola dodatkowa też.
    assert user_may_receive_type(
        _user(UserRole.delivery_lead, UserRole.head_of_recruitment), ntype
    )
    assert not user_may_receive_type(_user(UserRole.recruiter), ntype)
    assert not user_may_receive_type(_user(UserRole.delivery_lead), ntype)


def test_list_predicate_shows_the_alarm_to_head_of_recruitment_only() -> None:
    def sql_for(user: User) -> str:
        user.effective_section_access = {
            section.value: "write" for section in ProductSection
        }
        return str(
            notification_visibility_predicate(user).compile(
                compile_kwargs={"literal_binds": True}
            )
        )

    assert "candidate_data_access_alert" in sql_for(_user(UserRole.head_of_recruitment))
    assert "candidate_data_access_alert" not in sql_for(_user(UserRole.recruiter))
    assert unmapped_notification_types() == frozenset()


def test_mail_applies_to_admin_and_head_of_recruitment_only() -> None:
    applies = APPLIES["data_access_alert"]
    assert applies(_user(UserRole.admin), _Context())
    assert applies(_user(UserRole.head_of_recruitment), _Context())
    assert not applies(_user(UserRole.recruiter), _Context())


def test_new_type_is_mirrored_in_entrypoint() -> None:
    source = (
        BACKEND / "alembic" / "versions" / "0508_candidate_data_access_alert.py"
    ).read_text(encoding="utf-8")
    assert "'candidate_data_access_alert'" in source
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    statement = (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
        "'candidate_data_access_alert'"
    )
    assert re.search(re.escape(f'"{statement}"'), entrypoint)


# ── Z bazą: zapytanie i przebieg skanera (sprawdza CI) ───────────────────────

# Okno w przyszłości: wspólna baza testowa nie ma w nim cudzych zdarzeń.
DB_NOW = datetime(2030, 1, 15, 10, 0, tzinfo=timezone.utc)


async def _account(db, label: str, role: UserRole, created_at: datetime) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=f"data-access-{label}-{tag}@example.com",
        password_hash=hash_password(f"T3st_{tag}!Access"),
        name=f"Dostęp {label} {tag}",
        role=role,
        roles=[role.value],
        is_active=True,
        created_at=created_at,
    )
    db.add(user)
    await db.flush()
    return user


def _event(user: User, action: str, entity_id: int, minutes_ago: int, **details):
    return Activity(
        entity_type="candidate",
        entity_id=entity_id,
        action=action,
        user_id=user.id,
        details=details,
        external_source="audit",
        created_at=DB_NOW - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_scan_alerts_admin_once_per_person_and_burst_does_not_collide() -> None:
    old = DB_NOW - timedelta(days=400)
    async with AsyncSessionLocal() as db:
        admin = await _account(db, "admin", UserRole.admin, old)
        viewer = await _account(db, "podglad", UserRole.recruiter, old)
        new_viewers = [
            await _account(
                db, f"nowy-podglad{i}", UserRole.recruiter, DB_NOW - timedelta(days=1)
            )
            for i in range(3)
        ]
        zipper = await _account(db, "zip", UserRole.recruiter, old)
        exporter = await _account(db, "eksport", UserRole.recruiter, old)
        quiet = await _account(db, "spokojny", UserRole.recruiter, old)
        juniors = [
            await _account(
                db, f"junior{i}", UserRole.recruiter, DB_NOW - timedelta(days=1)
            )
            for i in range(3)
        ]
        # Same podglądy — dużo, także z nowych kont — nie budzą alarmu.
        events = [
            _event(viewer, "document_downloaded", 900_000 + i, 10, disposition="inline")
            for i in range(200)
        ]
        events += [
            _event(v, "document_url_issued", 940_000 + n, 10, disposition="inline")
            for n, v in enumerate(new_viewers)
        ]
        # Wczoraj (przed północą Warszawy) się nie liczy do „dziś”.
        events += [
            _event(
                quiet,
                "document_downloaded",
                910_000 + i,
                60 * 12,
                disposition="attachment",
            )
            for i in range(alerts.DAY_DISK_FILES + 5)
        ]
        events += [
            _event(quiet, "document_downloaded", 920_000, 5, disposition="attachment")
        ]
        events.append(
            _event(
                zipper,
                "bulk_cv_downloaded",
                0,
                30,
                included_count=alerts.DAY_DISK_FILES + 1,
            )
        )
        events.append(
            _event(
                exporter,
                "export_requested",
                0,
                30,
                row_count=alerts.DAY_EXPORT_ROWS + 1,
            )
        )
        events += [
            _event(j, "cv_downloaded", 930_000 + n, 5) for n, j in enumerate(juniors)
        ]
        db.add_all(events)
        await db.commit()
        everyone = [admin, viewer, zipper, exporter, quiet, *juniors, *new_viewers]

    try:
        async with AsyncSessionLocal() as db:
            usages = {u.user_id: u for u in await alerts.collect(db, DB_NOW)}
        assert usages[viewer.id].candidates_today == 200
        assert usages[viewer.id].disk_files_today == 0
        assert usages[zipper.id].disk_files_today == alerts.DAY_DISK_FILES + 1
        assert usages[exporter.id].export_rows_today == alerts.DAY_EXPORT_ROWS + 1
        assert usages[quiet.id].disk_files_today == 1
        assert usages[quiet.id].candidates_today == 1

        async with AsyncSessionLocal() as db:
            await alerts.scan_once(db, DB_NOW)
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Notification.related_entity_id, Notification.title).where(
                        Notification.user_id == admin.id,
                        Notification.notification_type
                        == NotificationType.candidate_data_access_alert,
                    )
                )
            ).all()
        about = {entity for entity, _ in rows}
        assert {zipper.id, exporter.id, alerts.BURST_ENTITY_ID} <= about
        assert quiet.id not in about
        assert viewer.id not in about
        burst_titles = [t for e, t in rows if e == alerts.BURST_ENTITY_ID]
        # Alarm „nowe konta naraz” liczy 3 juniorów z zapisem, nie 3 nowe podglądy.
        assert burst_titles and burst_titles[0].startswith("3 nowe konta")
        assert len(rows) == len(about)

        # Drugi przebieg tego samego dnia nie dokłada wpisów.
        async with AsyncSessionLocal() as db:
            assert await alerts.scan_once(db, DB_NOW) == 0
    finally:
        ids = [u.id for u in everyone]
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Notification).where(
                    Notification.notification_type
                    == NotificationType.candidate_data_access_alert
                )
            )
            await db.execute(delete(Activity).where(Activity.user_id.in_(ids)))
            await db.commit()


# ── Konta serwisowe (klucze API): pobrania bez osoby ─────────────────────────


def _service(**counts: int) -> alerts.ServiceUsage:
    return alerts.ServiceUsage(account_id=7, name="Automat ATS", **counts)


def test_service_key_viewing_alone_is_never_an_alarm() -> None:
    # Ta sama reguła co dla osób (07.11.2026): liczy się tylko to, co wychodzi.
    assert alerts.service_reasons(_service(candidates_today=5000)) == []


def test_service_key_thresholds_are_exclusive() -> None:
    at_limit = _service(
        disk_files_today=alerts.SERVICE_DAY_FILES,
        export_rows_today=alerts.SERVICE_DAY_EXPORT_ROWS,
    )
    assert alerts.service_reasons(at_limit) == []
    found = alerts.service_reasons(
        _service(
            disk_files_today=alerts.SERVICE_DAY_FILES + 1,
            export_rows_today=alerts.SERVICE_DAY_EXPORT_ROWS + 1,
        )
    )
    assert len(found) == 2
    assert any("pobranych" in r for r in found)
    assert any("eksport" in r for r in found)


def test_service_key_alert_says_how_to_cut_the_key_off() -> None:
    usage = _service(candidates_today=30, disk_files_today=31)
    title, message = alerts.service_alert_text(usage, alerts.service_reasons(usage))
    assert title.startswith("Integracja Automat ATS")
    assert "pobieranie" in title
    assert message.startswith("31 CV pobranych przez API")
    assert "30 kandydatów" in message
    assert "niczego nie zablokował" in message
    assert "Klucze API" in message
    # To nie człowiek: ekran „Osoby i role” nie ma tego konta.
    assert "Osoby i role" not in message


def test_service_alarm_id_cannot_collide_with_a_person_or_the_burst() -> None:
    # Dzienny dedup patrzy na related_entity_id BEZ related_entity_type, więc
    # alarm o koncie serwisowym 7 nie może mieć id osoby 7.
    entity = alerts.service_entity_id(7)
    assert entity < alerts.BURST_ENTITY_ID
    assert entity != 7


@pytest.mark.asyncio
async def test_service_alarm_reaches_every_recipient_with_its_own_id(
    monkeypatch,
) -> None:
    flagged = _service(disk_files_today=alerts.SERVICE_DAY_FILES + 1)
    calm = alerts.ServiceUsage(account_id=8, name="Spokojny", disk_files_today=1)
    calls: list[dict] = []

    async def collect(_db, _now):
        return []

    async def collect_service(_db, _now):
        return [flagged, calm]

    async def recipients(_db):
        return [7, 9]

    async def notify(_db, ids, **kwargs):
        calls.append({"ids": ids, **kwargs})
        return len(ids)

    class _Db:
        async def commit(self) -> None:
            return None

    monkeypatch.setattr(alerts, "collect", collect)
    monkeypatch.setattr(alerts, "collect_service", collect_service)
    monkeypatch.setattr(alerts, "_recipients", recipients)
    monkeypatch.setattr(alerts, "_notify", notify)

    assert await alerts.scan_once(_Db(), NOW) == 2
    assert len(calls) == 1
    # Konto serwisowe 7 to nie osoba 7: admin o tym id też dostaje alarm.
    assert calls[0]["ids"] == [7, 9]
    assert calls[0]["entity_type"] == alerts.SERVICE_ENTITY
    assert calls[0]["entity_id"] == alerts.service_entity_id(7)
    assert calls[0]["link"] == alerts.SERVICE_LINK


@pytest.mark.asyncio
async def test_quiet_service_accounts_send_nothing(monkeypatch) -> None:
    async def empty(_db, _now):
        return []

    async def must_not_run(_db):
        raise AssertionError("bez przekroczeń nie szukamy odbiorców")

    monkeypatch.setattr(alerts, "collect", empty)
    monkeypatch.setattr(alerts, "collect_service", empty)
    monkeypatch.setattr(alerts, "_recipients", must_not_run)

    assert await alerts.scan_once(object(), NOW) == 0


SERVICE_NOW = datetime(2030, 2, 15, 10, 0, tzinfo=timezone.utc)


def _service_account(label: str) -> ServiceAccount:
    tag = uuid.uuid4().hex[:8]
    return ServiceAccount(
        slug=f"alarm-{label}-{tag}", name=f"Klucz {label}", scopes=["candidates:cv"]
    )


def _service_event(
    via: str | None,
    action: str,
    entity_id: int,
    minutes_ago: int,
    user_id: int | None = None,
    **details,
) -> Activity:
    payload = {**details, **({"via": via} if via else {})}
    return Activity(
        entity_type="candidate",
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        details=payload,
        external_source="audit",
        created_at=SERVICE_NOW - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_scan_counts_each_service_account_separately() -> None:
    limit = alerts.SERVICE_DAY_FILES
    async with AsyncSessionLocal() as db:
        admin = await _account(
            db, "admin-klucz", UserRole.admin, SERVICE_NOW - timedelta(days=400)
        )
        keys = {
            label: _service_account(label)
            for label in (
                "pobiera",
                "tekst",
                "eksport",
                "na-progu",
                "podglad",
                "wczoraj",
                "inny-klucz",
            )
        }
        db.add_all(keys.values())
        await db.flush()

        def via(label: str) -> str:
            return f"integration:{keys[label].slug}"

        events = [
            _service_event(
                via("pobiera"),
                "document_downloaded",
                970_000 + i,
                5,
                disposition="attachment",
            )
            for i in range(limit + 1)
        ]
        # Tekst CV z API nie jest plikiem, ale wychodzi z NEXUSA tak samo.
        events += [
            _service_event(via("tekst"), "cv_downloaded", 971_000 + i, 5)
            for i in range(limit + 1)
        ]
        events.append(
            _service_event(
                via("eksport"),
                "export_requested",
                0,
                5,
                row_count=alerts.SERVICE_DAY_EXPORT_ROWS + 1,
            )
        )
        events += [
            _service_event(
                via("na-progu"),
                "document_downloaded",
                972_000 + i,
                5,
                disposition="attachment",
            )
            for i in range(limit)
        ]
        events += [
            _service_event(
                via("podglad"),
                "document_downloaded",
                973_000 + i,
                5,
                disposition="inline",
            )
            for i in range(limit * 3)
        ]
        # 12 h wcześniej to już poprzedni dzień w kalendarzu firmy.
        events += [
            _service_event(
                via("wczoraj"),
                "document_downloaded",
                974_000 + i,
                60 * 12,
                disposition="attachment",
            )
            for i in range(limit + 1)
        ]
        # Dwa klucze po połowie: progi są na konto, nie na całą integrację.
        events += [
            _service_event(via("inny-klucz"), "cv_downloaded", 975_000 + i, 5)
            for i in range(limit // 2)
        ]
        # Zdarzenia, które nie są ruchem klucza: Jarvis, bez `via`, z osobą.
        events += [
            _service_event("jarvis", "cv_downloaded", 976_000 + i, 5)
            for i in range(limit + 1)
        ]
        events += [
            _service_event(None, "cv_downloaded", 977_000 + i, 5)
            for i in range(limit + 1)
        ]
        events += [
            _service_event(
                via("podglad"), "cv_downloaded", 978_000 + i, 5, user_id=admin.id
            )
            for i in range(limit + 1)
        ]
        db.add_all(events)
        await db.commit()
        entity = {label: alerts.service_entity_id(k.id) for label, k in keys.items()}
        slugs = [k.slug for k in keys.values()]
        names = {label: k.name for label, k in keys.items()}

    try:
        async with AsyncSessionLocal() as db:
            usage = {u.name: u for u in await alerts.collect_service(db, SERVICE_NOW)}
        assert usage[names["pobiera"]].disk_files_today == limit + 1
        assert usage[names["pobiera"]].candidates_today == limit + 1
        assert usage[names["tekst"]].disk_files_today == limit + 1
        assert (
            usage[names["eksport"]].export_rows_today
            == alerts.SERVICE_DAY_EXPORT_ROWS + 1
        )
        assert usage[names["na-progu"]].disk_files_today == limit
        assert usage[names["podglad"]].disk_files_today == 0
        assert usage[names["podglad"]].candidates_today == limit * 3
        assert usage[names["inny-klucz"]].disk_files_today == limit // 2
        assert names["wczoraj"] not in usage

        async with AsyncSessionLocal() as db:
            assert await alerts.scan_once(db, SERVICE_NOW) >= 3
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(
                        Notification.related_entity_id,
                        Notification.related_entity_type,
                        Notification.link,
                    ).where(
                        Notification.user_id == admin.id,
                        Notification.notification_type
                        == NotificationType.candidate_data_access_alert,
                    )
                )
            ).all()
        about = {row[0] for row in rows}
        assert {entity["pobiera"], entity["tekst"], entity["eksport"]} <= about
        for label in ("na-progu", "podglad", "wczoraj", "inny-klucz"):
            assert entity[label] not in about
        assert all(
            row[1] == alerts.SERVICE_ENTITY and row[2] == alerts.SERVICE_LINK
            for row in rows
            if row[0] < 0
        )

        # Jeden alarm dziennie na klucz i odbiorcę.
        async with AsyncSessionLocal() as db:
            assert await alerts.scan_once(db, SERVICE_NOW) == 0
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Notification).where(
                    Notification.notification_type
                    == NotificationType.candidate_data_access_alert
                )
            )
            await db.execute(
                delete(Activity).where(
                    Activity.created_at >= SERVICE_NOW - timedelta(days=2),
                    Activity.created_at <= SERVICE_NOW,
                    Activity.entity_type == "candidate",
                )
            )
            await db.execute(
                delete(ServiceAccount).where(ServiceAccount.slug.in_(slugs))
            )
            await db.execute(delete(User).where(User.id == admin.id))
            await db.commit()
