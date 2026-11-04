"""Sprawy z panelu klienta: zapis, dzwonek Delivery Leada, odpowiedź.

Autor wpisuje imię i e-mail, których nikt nie weryfikuje. Dlatego na wpisany
adres nie wychodzi nic automatycznie, mail z odpowiedzią wychodzi tylko po
kliknięciu DL-a, a adres spoza domen kontaktów klienta jest oznaczony w widoku
DL-a. Dzwonek i mail do DL-a nie niosą treści od autora, bo mail z NEXUSA
z cudzym tekstem to gotowy phishing na pracownika.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client_panel import ClientPanel, ClientPanelRequest
from app.models.contact import Contact
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.user import User
from app.services.email import send_email

logger = logging.getLogger(__name__)

DAILY_WRITE_LIMIT = 30

_TITLES = {
    "question": "Klient pyta o osobę",
    "interview": "Klient prosi o rozmowę",
    "not_fit": "Klient: osoba nie pasuje",
    "requirements_change": "Klient zmienia wymagania",
}


def job_panel_link(job_id: int) -> str:
    return f"/jobs/{job_id}?win=client-panel"


async def guard_write(db: AsyncSession, panel: ClientPanel) -> None:
    """Akcje wyłączone = 403, dzienny limit panelu = 429.

    Wiersz panelu jest zablokowany do końca transakcji, żeby równoległe zapisy
    nie przeszły limitu razem.
    """
    if not panel.allow_actions:
        raise HTTPException(
            status_code=403,
            detail="Pytania i prośby są w tym panelu wyłączone. Napisz do osoby prowadzącej rekrutację.",
        )
    await db.execute(
        select(ClientPanel.id).where(ClientPanel.id == panel.id).with_for_update()
    )
    day_start = datetime.combine(
        business_today(), time.min, ZoneInfo(settings.BUSINESS_TZ)
    ).astimezone(timezone.utc)
    written = await db.scalar(
        select(func.count(ClientPanelRequest.id)).where(
            ClientPanelRequest.panel_id == panel.id,
            ClientPanelRequest.created_at >= day_start,
        )
    )
    if (written or 0) >= DAILY_WRITE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Dziś z tego panelu wysłano już dużo wiadomości. Spróbuj jutro albo napisz do osoby prowadzącej rekrutację.",
        )


async def _targets(db: AsyncSession, job: Job) -> list[int]:
    from app.services.notification_triggers import _delivery_lead_targets

    return await _delivery_lead_targets(db, job)


async def _notify(
    db: AsyncSession, job: Job, row: ClientPanelRequest, candidate_label: Optional[str]
) -> None:
    from app.services.notification_triggers import emit

    title = _TITLES[row.kind]
    about = f"{candidate_label} · {job.title}" if candidate_label else job.title
    for user_id in await _targets(db, job):
        try:
            async with db.begin_nested():
                await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=f"{about}. Czeka w panelu klienta rekrutacji.",
                    ntype=NotificationType.client_panel_request,
                    related_entity_type="client_panel_request",
                    related_entity_id=row.id,
                    link=job_panel_link(job.id),
                )
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć sprawy klienta
            logger.exception("client panel: notification failed for %s", row.id)


async def _candidate_label(
    db: AsyncSession, candidate_id: Optional[int]
) -> Optional[str]:
    if candidate_id is None:
        return None
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return None
    return (
        " ".join(p for p in (candidate.name, candidate.lastname) if p).strip() or None
    )


async def create_request(
    db: AsyncSession,
    *,
    panel: ClientPanel,
    job: Job,
    kind: str,
    author_name: str,
    author_email: str,
    body: Optional[str] = None,
    candidate_id: Optional[int] = None,
    reasons: Iterable[str] = (),
    slot_request_id: Optional[int] = None,
) -> ClientPanelRequest:
    """Zapis sprawy i dzwonek; commit robi wołający."""
    row = ClientPanelRequest(
        panel_id=panel.id,
        job_id=job.id,
        candidate_id=candidate_id,
        kind=kind,
        author_name=author_name,
        author_email=author_email.strip().lower(),
        body=(body or "").strip() or None,
        reasons=list(reasons),
        slot_request_id=slot_request_id,
    )
    db.add(row)
    await db.flush()
    await _notify(db, job, row, await _candidate_label(db, candidate_id))
    return row


def email_domain(address: Optional[str]) -> Optional[str]:
    if not address or "@" not in address:
        return None
    return address.rsplit("@", 1)[1].strip().lower() or None


async def client_contact_domains(
    db: AsyncSession, client_ids: Iterable[int]
) -> dict[int, set[str]]:
    wanted = {cid for cid in client_ids if cid}
    if not wanted:
        return {}
    rows = await db.execute(
        select(Contact.client_id, Contact.email).where(
            Contact.client_id.in_(wanted), Contact.email.is_not(None)
        )
    )
    out: dict[int, set[str]] = {}
    for client_id, address in rows.all():
        if domain := email_domain(address):
            out.setdefault(client_id, set()).add(domain)
    return out


async def list_requests(
    db: AsyncSession,
    *,
    job_id: Optional[int],
    status: Optional[str],
    scope_clause: Optional[Any],
    limit: int = 200,
) -> list[dict[str, Any]]:
    query = (
        select(
            ClientPanelRequest,
            Job.title,
            Job.client_id,
            Candidate.name,
            Candidate.lastname,
        )
        .join(Job, Job.id == ClientPanelRequest.job_id)
        .outerjoin(Candidate, Candidate.id == ClientPanelRequest.candidate_id)
        .order_by(ClientPanelRequest.created_at.desc(), ClientPanelRequest.id.desc())
        .limit(limit)
    )
    if job_id is not None:
        query = query.where(ClientPanelRequest.job_id == job_id)
    if status is not None:
        query = query.where(ClientPanelRequest.status == status)
    if scope_clause is not None:
        query = query.where(scope_clause)
    rows = (await db.execute(query)).all()
    domains = await client_contact_domains(db, [row.client_id for row in rows])
    return [
        {
            "id": row[0].id,
            "kind": row[0].kind,
            "candidate_id": row[0].candidate_id,
            "candidate_name": (
                " ".join(p for p in (row.name, row.lastname) if p).strip() or None
            ),
            "job_id": row[0].job_id,
            "job_title": row.title,
            "author_name": row[0].author_name,
            "author_email": row[0].author_email,
            "email_domain_known": email_domain(row[0].author_email)
            in domains.get(row.client_id, set()),
            "body": row[0].body,
            "reasons": row[0].reasons or [],
            "slot_request_id": row[0].slot_request_id,
            "status": row[0].status,
            "answer": row[0].answer,
            "created_at": row[0].created_at.isoformat(),
        }
        for row in rows
    ]


def _answer_mail(row: ClientPanelRequest, job_title: str) -> tuple[str, str]:
    # Bez linku do panelu i bez nazwiska: adresu nikt nie potwierdził, a link
    # otwiera panel bez logowania.
    subject = f"Odpowiedź w sprawie rekrutacji: {job_title}"[:180]
    parts = [f"Dzień dobry {row.author_name},", ""]
    if row.body:
        parts += ["Twoja wiadomość:", row.body, ""]
    parts += ["Odpowiedź:", row.answer or "", "", "B2B.net S.A."]
    return subject, "\n".join(parts)


async def answer_request(
    db: AsyncSession,
    *,
    row: ClientPanelRequest,
    answer: str,
    send_mail: bool,
    user: User,
) -> bool:
    """Odpowiedź DL-a; zwraca, czy mail wyszedł. Commit jest tutaj, przed wysyłką."""
    if row.status != "open":
        raise HTTPException(
            status_code=409, detail="Ta sprawa ma już odpowiedź albo jest zamknięta."
        )
    row.answer = answer.strip()
    row.status = "answered"
    row.answered_by = user.id
    row.answered_at = datetime.now(timezone.utc)
    job = await db.get(Job, row.job_id)
    job_title = job.title if job is not None else ""
    address = row.author_email
    reply_to = user.email
    await db.commit()
    if not send_mail:
        return False
    subject, text = _answer_mail(row, job_title)
    return bool(
        await run_in_threadpool(
            send_email, address, subject, text, None, reply_to=reply_to
        )
    )


def close_request(row: ClientPanelRequest) -> None:
    if row.status == "closed":
        raise HTTPException(status_code=409, detail="Ta sprawa jest już zamknięta.")
    row.status = "closed"
