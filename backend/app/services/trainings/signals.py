"""Dzwonki szkoleń (0695): kto dowiaduje się o kroku, który czeka na niego.

Do 13.11.2026 o kolejnych krokach wiedział tylko trener (maile z ``notify.py``):
TCM nie wiedział o wycenie ani pliku, reprezentant o umowie do podpisu, Finanse
o fakturze, a uczestnik o szkoleniu i nagraniu. Dzwonek nigdy nie niesie kwot.

Funkcje nie robią commita i nie podnoszą błędów: dzwonek nie cofa kroku.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationType
from app.models.training import Training, TrainingRegistration
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction

logger = logging.getLogger(__name__)

T = NotificationType


def _link(training: Training) -> str:
    return f"/trainings/{training.id}"


async def _send(
    db: AsyncSession,
    user_ids: Iterable[Optional[int]],
    training: Training,
    *,
    title: str,
    message: str,
    ntype: NotificationType,
    link: Optional[str] = None,
    exclude: Iterable[Optional[int]] = (),
) -> int:
    from app.services.hr.notify import notify_each  # noqa: PLC0415

    try:
        return await notify_each(
            db,
            user_ids,
            title=title,
            message=message,
            ntype=ntype,
            link=link or _link(training),
            related_entity_type="training",
            related_entity_id=training.id,
            exclude=exclude,
            log_tag="trainings",
            fresh=True,
        )
    except Exception:  # noqa: BLE001 — dzwonek nie cofa kroku
        logger.exception("trainings_signals: failed training=%s", training.id)
        return 0


async def organizer_ids(db: AsyncSession, training: Training) -> list[int]:
    """TCM, który zamówił szkolenie; bez niego (konto usunięte) każdy aktywny TCM."""

    if training.created_by is not None:
        active = await db.scalar(
            select(User.id).where(
                User.id == training.created_by, User.is_active.is_(True)
            )
        )
        if active is not None:
            return [active]
    users = (await db.scalars(select(User).where(User.is_active.is_(True)))).all()
    return [u.id for u in users if u.has_role(UserRole.talent_community_manager)]


async def quote_submitted(db: AsyncSession, training: Training) -> int:
    return await _send(
        db,
        await organizer_ids(db, training),
        training,
        title="Wycena szkolenia do decyzji",
        message=f"Trener przysłał agendę i wycenę: {training.title}.",
        ntype=T.training_quote,
    )


async def file_submitted(db: AsyncSession, training: Training, file_name: str) -> int:
    return await _send(
        db,
        await organizer_ids(db, training),
        training,
        title="Plik od trenera do przyjęcia",
        message=f"{file_name[:120]} · {training.title}",
        ntype=T.training_file,
    )


async def awaiting_company_signature(db: AsyncSession, training: Training) -> int:
    from app.services.b2b_esign import settings as esign_settings  # noqa: PLC0415

    current = await esign_settings.load(db)
    return await _send(
        db,
        current.company_signer_ids,
        training,
        title="Umowa szkoleniowa do podpisu",
        message=f"Trener podpisał umowę. Czeka na podpis B2B Network: {training.title}.",
        ntype=T.training_sign,
        link="/trainings?tab=sign",
    )


async def invoice_uploaded(db: AsyncSession, training: Training) -> int:
    from app.services.hr.recipients import users_with_permission  # noqa: PLC0415

    finance = await users_with_permission(db, ProductAction.finance_module)
    return await _send(
        db,
        [u.id for u in finance],
        training,
        title="Faktura trenera",
        message=f"Trener wgrał fakturę za szkolenie: {training.title}.",
        ntype=T.training_invoice,
    )


async def recording_ready(db: AsyncSession, training: Training) -> int:
    return await _send(
        db,
        await organizer_ids(db, training),
        training,
        title="Nagranie szkolenia do zatwierdzenia",
        message=f"Nagranie z Teams jest w szkoleniu: {training.title}.",
        ntype=T.training_recording,
    )


async def registered_user_ids(db: AsyncSession, training_id: int) -> list[int]:
    return [
        uid
        for uid in (
            await db.scalars(
                select(TrainingRegistration.user_id).where(
                    TrainingRegistration.training_id == training_id,
                    TrainingRegistration.user_id.is_not(None),
                )
            )
        ).all()
        if uid is not None
    ]


async def recording_available(
    db: AsyncSession, training: Training, user_ids: Iterable[int]
) -> int:
    return await _send(
        db,
        user_ids,
        training,
        title="Nagranie szkolenia jest dostępne",
        message=training.title,
        ntype=T.training_recording,
        link="/trainings?tab=recordings",
    )


async def reminder(
    db: AsyncSession, training: Training, *, soon: bool, join_url: str
) -> int:
    when = "za 15 minut" if soon else "jutro"
    hours = f", {training.time_from}" if training.time_from else ""
    return await _send(
        db,
        await registered_user_ids(db, training.id),
        training,
        title=f"Szkolenie {when}{hours}",
        message=training.title,
        ntype=T.training_reminder,
        link="/trainings",
    )
