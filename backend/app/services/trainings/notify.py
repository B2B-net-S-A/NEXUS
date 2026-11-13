"""Maile do trenera o kolejnym kroku szkolenia.

Idą przez ``portal_mail.send``, więc sprawdzają wyłącznik panelu konsultanta dla
kontraktu: zamknięty panel = brak maila, a krok i tak widać po zalogowaniu. Mail nie
niesie linku z tokenem, tylko adres panelu, bo link logowania wysyła sam panel.
Awaria wysyłki niczego nie cofa (zmiana jest już zapisana), zostaje w logu.
Tekst dla osoby spoza firmy bez myślników „—” (jak w obiegu podpisu B2B).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.training import Training
from app.services.consultant_portal import portal_mail

logger = logging.getLogger(__name__)

SIGN_OFF = "Zaloguj się do panelu konsultanta: {url}"


async def _send(db: AsyncSession, training: Training, subject: str, body: str) -> None:
    if training.trainer_contract_id is None:
        return
    email: Optional[str] = await db.scalar(
        select(Contract.candidate_email).where(
            Contract.id == training.trainer_contract_id
        )
    )
    if not email:
        return
    text = "\n\n".join(
        [
            "Dzień dobry,",
            body,
            SIGN_OFF.format(url=portal_mail.portal_url("/szkolenia")),
        ]
    )
    try:
        await portal_mail.send(
            db,
            contract_id=training.trainer_contract_id,
            to=email,
            subject=subject,
            text=text,
        )
    except Exception:  # noqa: BLE001 — mail nie cofa zapisanego kroku
        logger.exception("trainings_notify: send failed training=%s", training.id)


async def order_sent(db: AsyncSession, training: Training) -> None:
    await _send(
        db,
        training,
        f"Zamówienie szkolenia do wyceny: {training.title}",
        "Mamy dla Ciebie zamówienie szkolenia. W panelu zobaczysz termin, czas i pliki, "
        "które trzeba będzie przekazać. Uzupełnij agendę i wycenę w pozycjach A–E.",
    )


async def quote_returned(db: AsyncSession, training: Training) -> None:
    await _send(
        db,
        training,
        f"Wycena do poprawy: {training.title}",
        "Odesłaliśmy wycenę z uwagą. Treść uwagi i formularz znajdziesz w panelu.",
    )


async def agreement_ready(db: AsyncSession, training: Training) -> None:
    await _send(
        db,
        training,
        f"Umowa szkoleniowa do podpisu: {training.title}",
        "Przyjęliśmy Twoją wycenę. Umowa z Załącznikiem nr 1 czeka w panelu. Pobierz PDF, "
        "podpisz go podpisem kwalifikowanym i wgraj podpisany plik w tym samym miejscu.",
    )


async def agreement_signed(db: AsyncSession, training: Training) -> None:
    await _send(
        db,
        training,
        f"Umowa szkoleniowa podpisana: {training.title}",
        "Umowę podpisały obie strony. Podpisany PDF jest w panelu. Po szkoleniu przekażesz "
        "tam pliki z Załącznika nr 1.",
    )


async def file_reviewed(
    db: AsyncSession, training: Training, *, accepted: bool
) -> None:
    if accepted and training.invoice_ready_at is None:
        return
    if accepted:
        body = (
            "Przyjęliśmy wszystkie pliki z Załącznika nr 1. Możesz wystawić fakturę "
            "i wgrać ją w panelu przy tym szkoleniu."
        )
        subject = f"Możesz wystawić fakturę: {training.title}"
    else:
        body = (
            "Jeden z przekazanych plików wymaga poprawy. Uwagę i termin poprawy "
            "znajdziesz w panelu."
        )
        subject = f"Plik do poprawy: {training.title}"
    await _send(db, training, subject, body)
