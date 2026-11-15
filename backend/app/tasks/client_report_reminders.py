"""Raporty dla klientów: przypomnienia o terminie (co godzinę, działa od 9:00
w dni robocze).

Decyzja Artura 15.11.2026: osoba przygotowująca raport dostaje dzwonek
``client_report_due`` kilka dni roboczych przed terminem i raz po terminie,
gdy okres nie ma zapisanej wysyłki. Komu i o którym okresie, liczy czysta
funkcja ``services/client_reports/reminders.plan_reminders``; tu tylko odczyt
z bazy i zapis przez ``notification_triggers.emit`` (zastępstwa przez
``notification_route``, polityka sekcji i wyciszeń, dymek po commicie, dzienny
bezpiecznik ``ix_notif_dedup_daily`` w savepoincie).

Epizod (adresat, definicja, okres, rodzaj) wychodzi raz: fraza epizodu stoi
w treści, a „już wysłano” pyta o ``Notification.addressee_id``, więc
przekazanie zastępcy nie wysyła przypomnienia codziennie od nowa. Restart przy
wdrożeniu niczego nie powtarza. W weekend i święta pętla nie dzwoni; pasma
terminów są szersze niż jeden dzień, więc nic nie ginie.

Wzorzec: ``tasks/dl_portal_expiry_scanner.py`` (pasma progów, klucz epizodu
w treści) i ``tasks/start_documents_sweeper.py`` (godzina startu).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, is_business_day, local_now
from app.models.client_report import ClientReportDefinition
from app.models.notification import Notification, NotificationType
from app.services import loop_heartbeat
from app.services.client_reports import catalog, reminders, schedule
from app.services.dl_alerts import client_not_deleted_clause
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
FIRST_HOUR = 9
ENTITY_TYPE = "client_report_definition"
#: Epizod trwa najwyżej kilka dni (pasmo + weekend), więc to z zapasem.
_ALREADY_SENT_LOOKBACK_DAYS = 45


async def _already_sent(
    db: AsyncSession, definition_ids: list[int]
) -> dict[tuple[int, int], list[str]]:
    since = datetime.now(timezone.utc) - timedelta(days=_ALREADY_SENT_LOOKBACK_DAYS)
    rows = await db.execute(
        select(
            Notification.addressee_id,
            Notification.related_entity_id,
            Notification.message,
        ).where(
            Notification.notification_type == NotificationType.client_report_due,
            Notification.related_entity_type == ENTITY_TYPE,
            Notification.related_entity_id.in_(definition_ids),
            Notification.created_at >= since,
        )
    )
    out: dict[tuple[int, int], list[str]] = defaultdict(list)
    for addressee_id, definition_id, message in rows.all():
        out[(addressee_id, definition_id)].append(message or "")
    return out


async def send_reminders(db: AsyncSession, today: date) -> int:
    """Wyślij dzisiejsze przypomnienia; zwraca liczbę nowych wierszy."""
    definitions = list(
        await db.scalars(
            select(ClientReportDefinition).where(
                ClientReportDefinition.status == "active",
                ClientReportDefinition.rhythm.in_(sorted(schedule.CALENDAR_RHYTHMS)),
                client_not_deleted_clause(ClientReportDefinition.client_id),
            )
        )
    )
    if not definitions:
        return 0
    ids = [d.id for d in definitions]
    sent = {
        definition_id: set(by_period)
        for definition_id, by_period in (await catalog.sent_periods(db, ids)).items()
    }
    dl_clients = {
        d.client_id
        for d in definitions
        if d.preparer_user_id is None and d.preparer == "dl"
    }
    assignments = await catalog.dl_assignments(db, dl_clients) if dl_clients else {}
    planned = reminders.plan_reminders(
        definitions,
        today=today,
        sent=sent,
        assignments=assignments,
        already_sent=await _already_sent(db, ids),
    )
    if not planned:
        return 0
    names = await catalog.client_names(db, {r.client_id for r in planned})
    created = 0
    for reminder in planned:
        row = await emit(
            db,
            user_id=reminder.user_id,
            title=reminders.title(reminder, today),
            message=reminders.message(reminder, names.get(reminder.client_id)),
            ntype=NotificationType.client_report_due,
            related_entity_type=ENTITY_TYPE,
            related_entity_id=reminder.definition_id,
            link=reminders.link(reminder),
        )
        if row is not None:
            created += 1
    return created


async def run_once(now: datetime | None = None) -> int:
    moment = now or local_now()
    if moment.hour < FIRST_HOUR or not is_business_day(moment):
        return 0
    async with AsyncSessionLocal() as db:
        try:
            created = await send_reminders(db, business_date(moment))
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return created


async def client_report_reminders_loop() -> None:
    beat = loop_heartbeat.register(
        "client_report_reminders", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    while True:
        beat.tick()
        try:
            created = await run_once()
            if created:
                logger.info("client_report_reminders: %s przypomnień", created)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("client_report_reminders_loop iteration failed")
        await asyncio.sleep(INTERVAL_SECONDS)
