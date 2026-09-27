"""Mail potwierdzający przyjęcie zgłoszenia ze strony kariery / linku aplikacyjnego.

Rodzaj ``application_confirmation`` w ``notification_delivery.CATALOG`` —
domyślnie WYŁĄCZONY (jak każdy rutynowy mail); włącza go admin w
Ustawieniach → Powiadomienia.

Trzy reguły, które łatwo cofnąć:

* **Treść nie zależy od tego, czy osoba była już w bazie.** Odpowiedź API na
  zgłoszenie jest celowo ogólna (P0-CAND-01: formularz nie może zdradzać, że
  e-mail jest w bazie), więc mail też. ``render_confirmation`` przyjmuje
  wyłącznie dane z formularza i z LINKU — nigdy z istniejącego profilu.
* **Tytuł rekrutacji tylko z ZATWIERDZONEGO opisu publicznego.** Wewnętrzny
  tytuł bywa nazwą klienta („… dla Banku X”); stary formularz ``/apply``
  nie wymaga opisu publicznego, więc bez zatwierdzenia mail mówi ogólnie.
* **Jeden mail na (adres, link) w 24 h.** Ponowne wysłanie formularza (np.
  poprawione CV) nie produkuje serii maili. Klucz to HMAC adresu (bez
  jawnego e-maila w tabeli) + nie-sekretny klucz linku; stare wpisy są
  sprzątane przy każdym zapisie, więc tabela nie rośnie.

Wysyłka po commicie zgłoszenia, w tle (``BackgroundTasks``), przez
``guarded_send`` w ``asyncio.to_thread`` — polityka jest sprawdzana jeszcze
raz tuż przed nadawcą. Nic tutaj nie rzuca: mail nie może cofnąć zgłoszenia.
Logi bez adresów i imion.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

KIND = "application_confirmation"
DEDUP_HOURS = 24


@dataclass(frozen=True)
class ConfirmationEmail:
    to: str
    subject: str
    text_body: str
    html_body: str


def email_key(email: str) -> str:
    """HMAC znormalizowanego adresu — tabela dedupu nie trzyma jawnego e-maila."""
    normalized = (email or "").strip().lower()
    key = (
        settings.CANDIDATE_IDENTITY_FINGERPRINT_KEY or settings.SECRET_KEY or ""
    ).encode("utf-8")
    return hmac.new(
        key, b"application-confirmation:" + normalized.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def render_confirmation(
    *, to: str, first_name: str, public_job_title: Optional[str], rodo_url: str
) -> ConfirmationEmail:
    """Czysta funkcja: te same wejścia → ten sam mail, niezależnie od bazy.

    ``first_name`` świadomie NIE trafia do treści (runda 8, R8-N4-9): formularz
    jest anonimowy, więc imię to dowolny tekst obcej osoby, a mail idzie
    z firmowej skrzynki na dowolny podany adres. Powitanie jest ogólne.
    """
    del first_name
    greeting = "Dzień dobry,"
    title = (public_job_title or "").strip() or None
    what = f"Twoje zgłoszenie na stanowisko „{title}”" if title else "Twoje zgłoszenie"
    subject = (
        f"Potwierdzenie zgłoszenia: {title}" if title else "Potwierdzenie zgłoszenia"
    )
    text_body = (
        f"{greeting}\n\n"
        f"dziękujemy — {what} dotarło do nas razem z CV.\n\n"
        "Rekruter przejrzy je i odezwie się, jeśli Twój profil będzie pasował "
        "do tej lub innej rekrutacji. Nie musisz niczego wysyłać ponownie.\n\n"
        f"Informacje o przetwarzaniu danych: {rodo_url}\n\n"
        "— Zespół rekrutacji B2B.NET S.A.\n"
        "Ta wiadomość została wysłana automatycznie — prosimy na nią nie odpowiadać."
    )
    safe_greeting = html.escape(greeting)
    safe_what = html.escape(what)
    safe_rodo = html.escape(rodo_url, quote=True)
    html_body = (
        f"<p>{safe_greeting}</p>"
        f"<p>dziękujemy — {safe_what} dotarło do nas razem z CV.</p>"
        "<p>Rekruter przejrzy je i odezwie się, jeśli Twój profil będzie pasował "
        "do tej lub innej rekrutacji. Nie musisz niczego wysyłać ponownie.</p>"
        f'<p><a href="{safe_rodo}">Informacje o przetwarzaniu danych</a></p>'
        '<hr><p style="color:#888;font-size:12px">Zespół rekrutacji B2B.NET S.A. · '
        "wiadomość wysłana automatycznie — prosimy na nią nie odpowiadać.</p>"
    )
    return ConfirmationEmail(
        to=(to or "").strip(),
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def rodo_url() -> str:
    from app.services.career_slugs import career_base_url

    return f"{career_base_url()}/rodo"


async def public_job_title(db: AsyncSession, job_id: Optional[int]) -> Optional[str]:
    """Tytuł z zatwierdzonego opisu publicznego albo ``None``."""
    if job_id is None:
        return None
    from sqlalchemy import select

    from app.models.job import Job
    from app.models.job_public_profile import JobPublicProfile
    from app.services.job_public_profile import STATUS_APPROVED, resolve_status

    job = await db.get(Job, job_id)
    if job is None:
        return None
    profile = await db.scalar(
        select(JobPublicProfile).where(JobPublicProfile.job_id == job_id)
    )
    if profile is None:
        return None
    status, _default, effective = await resolve_status(db, job, profile)
    return effective if status == STATUS_APPROVED else None


async def claim_send(db: AsyncSession, *, email: str, link_key: str) -> bool:
    """Rezerwuje wysyłkę (adres, link) na 24 h. ``True`` = wolno wysłać.

    Jedna instrukcja: wstawia wiersz albo odświeża go tylko, gdy ostatnia
    wysyłka była dawniej niż ``DEDUP_HOURS`` — dwa równoległe zgłoszenia nie
    wyślą dwóch maili.
    """
    await db.execute(
        text(
            "DELETE FROM application_confirmation_sends "
            "WHERE sent_at < now() - make_interval(hours => :h)"
        ),
        {"h": DEDUP_HOURS * 2},
    )
    claimed = await db.scalar(
        text(
            "INSERT INTO application_confirmation_sends (email_key, link_key, sent_at) "
            "VALUES (:e, :l, now()) "
            "ON CONFLICT (email_key, link_key) DO UPDATE SET sent_at = now() "
            "WHERE application_confirmation_sends.sent_at "
            "< now() - make_interval(hours => :h) "
            "RETURNING id"
        ),
        {"e": email_key(email), "l": link_key[:64], "h": DEDUP_HOURS},
    )
    return claimed is not None


async def release_claim(*, email: str, link_key: str) -> None:
    """Nieudana wysyłka nie może blokować kolejnego zgłoszenia przez 24 h."""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "DELETE FROM application_confirmation_sends "
                    "WHERE email_key = :e AND link_key = :l"
                ),
                {"e": email_key(email), "l": link_key[:64]},
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — sprzątanie nie jest krytyczne
        logger.warning("[apply-confirmation] release failed: %s", type(exc).__name__)


async def deliver(message: ConfirmationEmail, *, event_at: datetime, link_key: str):
    """Zadanie w tle: wysyłka przez ``guarded_send`` w wątku. Nigdy nie rzuca."""
    from app.services.email import send_email
    from app.services.notification_delivery import guarded_send

    try:
        sent = await asyncio.to_thread(
            guarded_send,
            KIND,
            event_at,
            send_email,
            message.to,
            message.subject,
            message.text_body,
            message.html_body,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[apply-confirmation] send failed: %s", type(exc).__name__)
        sent = False
    if not sent:
        await release_claim(email=message.to, link_key=link_key)
    return sent


async def schedule_confirmation(
    db: AsyncSession,
    *,
    background_tasks,
    email: str,
    first_name: str,
    job_id: Optional[int],
    link_key: str,
) -> bool:
    """Po commicie zgłoszenia: polityka → rezerwacja → wysyłka w tle.

    ``True`` = mail zakolejkowany. Wołane identycznie z obu gałęzi
    ``submit_application``; nigdy nie rzuca.
    """
    try:
        from app.services.notification_delivery import load_policy

        now = datetime.now(timezone.utc)
        policy = await load_policy(db)
        if not policy.allows(KIND, now):
            return False
        if not (email or "").strip():
            return False
        title = await public_job_title(db, job_id)
        if not await claim_send(db, email=email, link_key=link_key):
            await db.rollback()
            return False
        await db.commit()
        message = render_confirmation(
            to=email,
            first_name=first_name,
            public_job_title=title,
            rodo_url=rodo_url(),
        )
        background_tasks.add_task(deliver, message, event_at=now, link_key=link_key)
        return True
    except Exception as exc:  # noqa: BLE001 — mail nie cofa zgłoszenia
        logger.warning("[apply-confirmation] scheduling failed: %s", type(exc).__name__)
        try:
            await db.rollback()
        except Exception:  # pragma: no cover
            pass
        return False
