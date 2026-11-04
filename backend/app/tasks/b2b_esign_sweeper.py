"""Podpis umowy B2B w NEXUSIE — wygasanie linków i przypomnienia (co 30 min).

* Link po terminie: wniosek ``expired``, link przestaje przyjmować pliki, nadawca
  dostaje dzwonek. Skrót linku zostaje ``EXPIRED_LINK_DAYS`` dni: kontraktor
  widzi termin i „Poproś o nowy link”, a nadawca „Wyślij nowy link” na tym
  samym PDF-ie (27.10.2026) — potem pętla go kasuje.
* Kontraktor milczy: jedno przypomnienie dzień przed końcem terminu (przy
  terminie 1 dnia — po połowie, 26.10.2026; terminy 1/3/5/7 dni, a przy
  „co 3 dni” krótki termin nie dawał żadnego) — mail ze skrzynki nadawcy BEZ
  linku (w bazie jest tylko skrót tokenu — link zostaje w pierwszym mailu)
  i dzwonek do nadawcy.
* Umowa czeka na podpis firmy: pierwsze przypomnienie po 1 dniu od podpisu
  kontraktora, potem co ``REMIND_EVERY``, zawsze w dzień roboczy 8:00–18:00
  (decyzja Artura 26.10.2026) — dzwonek i mail do reprezentanta ze skrzynki
  nadawcy. Pierwszy mail idzie od razu po podpisie kontraktora (API).
* Link kontraktora po podpisie obu stron służy do pobrania kopii przez
  ``SIGNED_COPY_DAYS`` dni; potem pętla go kasuje.

Działa także przy wyłączonym przełączniku — wnioski z pilotażu muszą wygasnąć.
Każdy wniosek w osobnej transakcji z blokadą (``SKIP LOCKED``), więc
równoległy podpis albo wycofanie wygrywa.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import (
    business_today,
    is_business_day,
    is_within_local_hours,
)
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_signing_request import OPEN_STATUSES, B2BSigningRequest
from app.models.notification import NotificationType
from app.models.user import User
from app.services import loop_heartbeat
from app.services.b2b_esign import mail as esign_mail
from app.services.b2b_esign.service import (
    EXPIRED_LINK_DAYS,
    SIGNED_COPY_DAYS,
    bell_recipients,
    handler_id,
    link_sent_at,
)
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 1800
REMIND_EVERY = timedelta(days=3)
REMIND_BEFORE_DEADLINE = timedelta(days=1)
COMPANY_FIRST_REMINDER = timedelta(days=1)
_WARSAW = ZoneInfo("Europe/Warsaw")
_LINK = "/contracts/b2b-generator?tab=generated"


def contractor_reminder_at(sent_at: datetime, expires_at: datetime) -> datetime:
    """Kiedy przypomnieć kontraktorowi: dzień przed końcem, najpóźniej w połowie."""
    return expires_at - min(REMIND_BEFORE_DEADLINE, (expires_at - sent_at) / 2)


def company_reminder_due(
    signed_at: datetime, last_reminder_at: datetime | None, now: datetime
) -> bool:
    """Przypomnieć reprezentantowi firmy? Po 1 dniu, potem co 3 dni, w pracy."""
    if not is_business_day(now) or not is_within_local_hours(
        now, start_hour=8, end_hour=18
    ):
        return False
    if last_reminder_at is None or last_reminder_at < signed_at:
        return now - signed_at >= COMPANY_FIRST_REMINDER
    return now - last_reminder_at >= REMIND_EVERY


async def _notify(db, *, user_id, title, message, ntype, request_id) -> None:
    if not user_id:
        return
    await emit_notification(
        db,
        user_id=user_id,
        title=title,
        message=message,
        ntype=ntype,
        related_entity_type="b2b_signing_request",
        related_entity_id=request_id,
        link=_LINK,
    )


async def _due_ids(now: datetime) -> list[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(B2BSigningRequest.id).where(
                or_(
                    B2BSigningRequest.status == "sent",
                    B2BSigningRequest.status == "contractor_signed",
                )
            )
        )
        return list(rows.all())


async def _handle(request_id: int, now: datetime) -> str | None:
    """Jeden wniosek: ``expired`` / ``reminded`` / ``None`` (nic do zrobienia)."""
    async with AsyncSessionLocal() as db:
        request = await db.scalar(
            select(B2BSigningRequest)
            .where(B2BSigningRequest.id == request_id)
            .with_for_update(skip_locked=True)
        )
        if request is None:
            return None
        # Lista powstała przed blokadą — wycofany albo podpisany w międzyczasie
        # wniosek nie dostaje przypomnienia.
        if request.status not in OPEN_STATUSES:
            return None
        row = await db.get(B2BGeneratedContract, request.generated_contract_id)
        number = row.contract_number if row else ""
        # Zegar przypomnień liczy się od początku bieżącego etapu: przy podpisie
        # firmy przypomnienie z etapu kontraktora nie przyspiesza kolejnego
        # (``company_reminder_due`` pomija przypomnienie sprzed ``stage_start``).
        stage_start = (
            request.contractor_signed_at
            if request.status == "contractor_signed" and request.contractor_signed_at
            else request.sent_at
        )

        if request.status == "sent" and request.expires_at <= now:
            request.status = "expired"
            request.closed_at = now
            # Nowa lista: zmiana w miejscu nie zapisałaby się w JSONB.
            request.events = [
                *(request.events or []),
                {"kind": "expired", "at": request.expires_at.isoformat()},
            ]
            # Nadawca i osoby w DW (27.10.2026) — ktoś musi wysłać nowy link.
            for watcher_id in await bell_recipients(db, request, business_today()):
                await _notify(
                    db,
                    user_id=watcher_id,
                    title=f"Link do umowy {number} wygasł",
                    message=(
                        f"{request.contractor_name} nie podpisał(a) umowy w terminie. "
                        "„Wyślij nowy link” w rejestrze wyśle ten sam PDF, więc plik "
                        "podpisany przed terminem nadal przejdzie."
                    ),
                    ntype=NotificationType.signature_failed,
                    request_id=request.id,
                )
            await db.commit()
            return "expired"

        if request.status == "contractor_signed":
            if not company_reminder_due(stage_start, request.last_reminder_at, now):
                return None
            request.last_reminder_at = now
            await _notify(
                db,
                user_id=request.company_signer_id,
                title=f"Umowa {number} nadal czeka na Twój podpis",
                message=f"{request.contractor_name} podpisał(a) umowę — brakuje podpisu B2B Network.",
                ntype=NotificationType.signature_sent,
                request_id=request.id,
            )
            await db.commit()
            signer = (
                await db.get(User, request.company_signer_id)
                if request.company_signer_id
                else None
            )
            if signer is not None and signer.email:
                subject, body = esign_mail.company_signer_message(
                    number=number,
                    contractor_name=request.contractor_name,
                    since=stage_start,
                    reminder=True,
                )
                await esign_mail.send_from(
                    db,
                    user_id=handler_id(request),
                    to=signer.email,
                    subject=subject,
                    body_html=body,
                    candidate_id=row.candidate_id if row else None,
                    request_key=(
                        f"b2b-esign-{request_id}-company-"
                        f"{now.astimezone(_WARSAW):%Y%m%d}"
                    ),
                )
            return "reminded"

        # Wysłana, kontraktor milczy — jedno przypomnienie na termin.
        # Od linku, który kontraktor ma teraz (po „Wyślij nowy link” — od niego).
        link_at = link_sent_at(request)
        if request.last_reminder_at is not None or now < contractor_reminder_at(
            link_at, request.expires_at
        ):
            return None
        request.last_reminder_at = now
        # Obsługujący (po „Przejmij obsługę” zastępca) — jego skrzynka i dzwonek.
        sender_id = handler_id(request)
        contractor_email = request.contractor_email
        contractor_name = request.contractor_name
        candidate_id = row.candidate_id if row else None
        sent_at, expires_at = link_at, request.expires_at
        deadline = expires_at.astimezone(_WARSAW).strftime("%d.%m.%Y")
        await _notify(
            db,
            user_id=sender_id,
            title=f"Umowa {number} czeka na podpis kontraktora",
            message=f"{contractor_name} jeszcze nie podpisał(a). Link ważny do {deadline}.",
            ntype=NotificationType.signature_sent,
            request_id=request.id,
        )
        await db.commit()
        subject, body = esign_mail.contractor_reminder_message(
            number=number, sent_at=sent_at, expires_at=expires_at
        )
        await esign_mail.send_from(
            db,
            user_id=sender_id,
            to=contractor_email,
            subject=subject,
            body_html=body,
            candidate_id=candidate_id,
            # Jeden mail na termin; przedłużenie albo nowy link to nowy termin.
            request_key=f"b2b-esign-{request_id}-reminder-{expires_at:%Y%m%d%H%M}",
        )
        return "reminded"


async def _close_old_copy_links(now: datetime) -> None:
    """Link do kopii podpisanej umowy żyje ``SIGNED_COPY_DAYS`` dni, wygasły
    link ``EXPIRED_LINK_DAYS`` dni od zamknięcia."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(B2BSigningRequest)
            .where(
                B2BSigningRequest.status == "expired",
                B2BSigningRequest.contractor_token_hash.is_not(None),
                B2BSigningRequest.closed_at <= now - timedelta(days=EXPIRED_LINK_DAYS),
            )
            .values(contractor_token_hash=None)
        )
        await db.execute(
            update(B2BSigningRequest)
            .where(
                B2BSigningRequest.status == "completed",
                B2BSigningRequest.contractor_token_hash.is_not(None),
                B2BSigningRequest.completed_at
                <= now - timedelta(days=SIGNED_COPY_DAYS),
            )
            .values(contractor_token_hash=None)
        )
        await db.commit()


async def sweep(now: datetime | None = None) -> dict[str, int]:
    moment = now or datetime.now(timezone.utc)
    counts = {"expired": 0, "reminded": 0}
    try:
        await _close_old_copy_links(moment)
    except Exception:  # noqa: BLE001 — przypomnienia idą mimo to
        logger.exception("[b2b_esign] zamykanie linków do kopii nie wyszło")
    for request_id in await _due_ids(moment):
        try:
            outcome = await _handle(request_id, moment)
        except Exception:  # noqa: BLE001 — jeden wniosek nie zatrzymuje reszty
            logger.exception(
                "[b2b_esign] przegląd wniosku %d nie powiódł się", request_id
            )
            continue
        if outcome:
            counts[outcome] += 1
    return counts


async def _prewarm_trusted_list() -> None:
    """Lista zaufanych UE wczytana przy starcie — pierwszy kontraktor nie czeka
    ok. 20 s na jej pobranie (pomiar 22.10.2026). Awaria = pobierze się przy
    pierwszej walidacji."""
    from app.core.config import settings  # noqa: PLC0415
    from app.services.b2b_esign.qualified import trusted_registry  # noqa: PLC0415

    if settings.B2B_ESIGN_VALIDATOR.strip().lower() == "dss":
        return
    try:
        await trusted_registry()
    except Exception:  # noqa: BLE001
        logger.warning(
            "[b2b_esign] wstępne pobranie listy UE nie wyszło", exc_info=True
        )


async def b2b_esign_sweeper_loop() -> None:
    beat = loop_heartbeat.register(
        "b2b_esign_sweeper", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    await _prewarm_trusted_list()
    while True:
        beat.tick()
        try:
            counts = await sweep()
            if any(counts.values()):
                logger.info("[b2b_esign] przegląd: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[b2b_esign] przegląd nie powiódł się")
        await asyncio.sleep(INTERVAL_SECONDS)
