"""Podpis umowy B2B w NEXUSIE — wygasanie linków i przypomnienia (co 30 min).

* Link po terminie: wniosek ``expired``, link przestaje działać, nadawca dostaje
  dzwonek (może wysłać ponownie albo przejść na drogę zwykłą).
* Kontraktor milczy ``REMIND_EVERY`` od wysyłki albo ostatniego przypomnienia:
  mail ze skrzynki nadawcy BEZ linku (w bazie jest tylko skrót tokenu — link
  zostaje w pierwszym mailu) i dzwonek do nadawcy.
* Umowa czeka na podpis firmy dłużej niż ``REMIND_EVERY``: dzwonek do
  reprezentanta.

Działa także przy wyłączonym przełączniku — wnioski z pilotażu muszą wygasnąć.
Każdy wniosek w osobnej transakcji z blokadą (``SKIP LOCKED``), więc
równoległy podpis albo wycofanie wygrywa.
"""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_signing_request import OPEN_STATUSES, B2BSigningRequest
from app.models.notification import NotificationType
from app.services import loop_heartbeat
from app.services.b2b_esign import mail as esign_mail
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 1800
REMIND_EVERY = timedelta(days=3)
_WARSAW = ZoneInfo("Europe/Warsaw")
_LINK = "/contracts/b2b-generator?tab=generated"


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
        # firmy przypomnienie z etapu kontraktora nie przyspiesza kolejnego.
        stage_start = (
            request.contractor_signed_at
            if request.status == "contractor_signed" and request.contractor_signed_at
            else request.sent_at
        )
        last = max(
            [stage_start]
            + ([request.last_reminder_at] if request.last_reminder_at else [])
        )

        if request.status == "sent" and request.expires_at <= now:
            request.status = "expired"
            request.contractor_token_hash = None
            request.closed_at = now
            await _notify(
                db,
                user_id=request.sent_by,
                title=f"Link do umowy {number} wygasł",
                message=(
                    f"{request.contractor_name} nie podpisał(a) umowy w terminie. "
                    "Wyślij ją ponownie w NEXUSIE albo jak dotąd mailem."
                ),
                ntype=NotificationType.signature_failed,
                request_id=request.id,
            )
            await db.commit()
            return "expired"

        if now - last < REMIND_EVERY:
            return None
        request.last_reminder_at = now

        if request.status == "contractor_signed":
            await _notify(
                db,
                user_id=request.company_signer_id,
                title=f"Umowa {number} nadal czeka na Twój podpis",
                message=f"{request.contractor_name} podpisał(a) umowę — brakuje podpisu B2B Network.",
                ntype=NotificationType.signature_sent,
                request_id=request.id,
            )
            await db.commit()
            return "reminded"

        # Wysłana, kontraktor milczy.
        sender_id = request.sent_by
        contractor_email = request.contractor_email
        contractor_name = request.contractor_name
        candidate_id = row.candidate_id if row else None
        sent_on = request.sent_at.astimezone(_WARSAW).strftime("%d.%m.%Y")
        deadline = request.expires_at.astimezone(_WARSAW).strftime("%d.%m.%Y")
        reminder_no = int((now - request.sent_at) / REMIND_EVERY)
        await _notify(
            db,
            user_id=sender_id,
            title=f"Umowa {number} czeka na podpis kontraktora",
            message=f"{contractor_name} jeszcze nie podpisał(a). Link ważny do {deadline}.",
            ntype=NotificationType.signature_sent,
            request_id=request.id,
        )
        await db.commit()
        body = (
            f"<p>Dzień dobry {html.escape(contractor_name)},</p>"
            f"<p>przypominamy o umowie B2B nr {html.escape(number)}, którą "
            f"wysłaliśmy do podpisu {sent_on}. Link do podpisu jest w tamtym "
            f"mailu i działa do {deadline}.</p>"
            "<p>Jeśli nie masz podpisu kwalifikowanego albo link nie działa, "
            "odpisz na tę wiadomość.</p><p>Pozdrawiamy<br>B2B Network</p>"
        )
        await esign_mail.send_from(
            db,
            user_id=sender_id,
            to=contractor_email,
            subject=f"Przypomnienie: umowa B2B nr {number} czeka na podpis",
            body_html=body,
            candidate_id=candidate_id,
            request_key=f"b2b-esign-{request_id}-reminder-{reminder_no}",
        )
        return "reminded"


async def sweep(now: datetime | None = None) -> dict[str, int]:
    moment = now or datetime.now(timezone.utc)
    counts = {"expired": 0, "reminded": 0}
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
