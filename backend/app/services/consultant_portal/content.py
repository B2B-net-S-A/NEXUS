"""Treści portalu: nagłówek, FAQ, „Twoje sprawy” i nowe zgłoszenie.

„Twoje sprawy” to lista dozwolona, a nie filtr po kontrakcie: do kontraktu są
przypięte też sprawy automatyczne (wejście, wyjście, koniec współpracy) i rozmowy
o stawce, których konsultant nie powinien czytać. Pokazujemy więc wyłącznie:

* zgłoszenia z portalu (``source='portal'``, klucz ``portal:…``),
* maile, które sam napisał (``source='mail'`` i jego adres w wiadomości),

i nigdy obszaru ``negotiation``. Z wiersza wychodzi tylko tytuł, stan, osoba i „kto
na kogo czeka”: bez opisu, komentarzy, checklisty i treści maili, bo tam są notatki
wewnętrzne.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.client import Client
from app.models.consultant_portal import CpFaqItem
from app.models.contract import Contract
from app.models.user import User
from app.services.admin_cases import rules
from app.services.admin_cases.hooks import _care_owner_id
from app.services.admin_cases.service import (
    AutomaticCase,
    module_enabled,
    open_automatic_case,
)
from app.services.consultant_portal import portal_mail
from app.services.consultant_portal.auth import PortalContext, PortalError
from app.services.consultant_portal_schema import QUESTION_MAX, TOPICS

#: Prefiks klucza spraw, które konsultant widzi jako swoje.
CASE_KEY_PREFIX = "portal:"
TOPIC_LABELS: dict[str, str] = {
    "invoice": "Faktury i płatności",
    "contract": "Umowa, aneks, stawka",
    "leave": "Urlop i nieobecność",
    "access": "Sprzęt i dostępy",
    "next": "Koniec projektu i nowy projekt",
    "data": "Zmiana danych",
}
#: Zespół, który prowadzi temat (podpowiedź przy wyborze osoby).
TOPIC_TEAMS: dict[str, str] = {
    "invoice": "finance",
    "contract": "contracts",
    "leave": "care",
    "access": "care",
    "next": "care",
    "data": "finance",
}
CASE_TITLE_MAX = 120
CASE_BODY_MAX = 5_000
CASES_PER_DAY = 10
CASES_LISTED = 50
ANSWER_MAX = 5_000
CASES_OFF = "Zgłoszenia są chwilowo niedostępne. Napisz do nas mailem."
TOO_MANY_CASES = "Dziś założono już dużo zgłoszeń. Spróbuj jutro albo napisz mailem."


async def overview(db: AsyncSession, context: PortalContext) -> dict[str, Any]:
    contract = await db.get(Contract, context.consultant.contract_id)
    client = await db.get(Client, contract.client_id) if contract else None
    return {
        "first_name": context.consultant.first_name,
        "client": (client.display_name or client.name) if client else None,
        "since": contract.start_date.isoformat()
        if contract and contract.start_date
        else None,
        "until": contract.end_date.isoformat()
        if contract and contract.end_date
        else None,
        "support_email": portal_mail.mailbox(),
        "topics": [{"key": key, "label": TOPIC_LABELS[key]} for key in TOPICS],
    }


# ── FAQ ──────────────────────────────────────────────────────────────────────


def faq_row(item: CpFaqItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "topic": item.topic,
        "question": item.question,
        "answer": item.answer,
        "position": item.position,
    }


async def published_faq(db: AsyncSession) -> list[dict[str, Any]]:
    items = (
        await db.scalars(
            select(CpFaqItem)
            .where(CpFaqItem.published.is_(True))
            .order_by(CpFaqItem.topic, CpFaqItem.position, CpFaqItem.id)
        )
    ).all()
    return [faq_row(item) for item in items]


# ── Twoje sprawy ─────────────────────────────────────────────────────────────


def visible_cases_clause(contract_ids: tuple[int, ...], email: str):
    own_mail = exists().where(
        AdminCaseMessage.case_id == AdminCase.id,
        func.lower(AdminCaseMessage.sender_email) == email,
    )
    return and_(
        AdminCase.contract_id.in_(contract_ids),
        AdminCase.area != "negotiation",
        or_(
            and_(
                AdminCase.source == "portal",
                AdminCase.source_key.like(f"{CASE_KEY_PREFIX}%"),
            ),
            and_(AdminCase.source == "mail", own_mail),
        ),
    )


def waiting_label(status: str, owner: Optional[str]) -> dict[str, str]:
    """„Kto na kogo czeka”: ``who`` to ``nobody``, ``us``, ``other`` albo ``done``.

    Stałe etykiety: wolny tekst „Czeka na” z karty pisze pracownik dla zespołu
    i nie może wyjść do osoby spoza firmy.
    """

    if status in ("done", "closed"):
        return {"who": "done", "label": "Załatwione"}
    if status == "waiting":
        return {"who": "other", "label": "Czekamy na odpowiedź"}
    if owner is None:
        return {"who": "nobody", "label": "Czeka na przydzielenie osoby"}
    return {"who": "us", "label": f"Po naszej stronie: {owner}"}


async def own_cases(db: AsyncSession, context: PortalContext) -> list[dict[str, Any]]:
    consultant = context.consultant
    rows = (
        await db.execute(
            select(AdminCase, User.name)
            .outerjoin(User, User.id == AdminCase.assignee_user_id)
            .where(visible_cases_clause(consultant.contract_ids, consultant.email))
            .order_by(AdminCase.updated_at.desc(), AdminCase.id.desc())
            .limit(CASES_LISTED)
        )
    ).all()
    return [
        {
            "id": case.id,
            "title": case.title,
            "status": case.status,
            "owner": owner,
            "waiting": waiting_label(case.status, owner),
            "created_at": case.created_at.isoformat(),
            "updated_at": case.updated_at.isoformat(),
        }
        for case, owner in rows
    ]


async def open_portal_case(
    db: AsyncSession,
    *,
    contract_id: int,
    title: str,
    description: Optional[str],
    now: datetime,
) -> AdminCase:
    assignee = await _care_owner_id(db, contract_id)
    case, _created = await open_automatic_case(
        db,
        AutomaticCase(
            title=title[: rules.TITLE_MAX],
            area="administration",
            priority="P2",
            source="portal",
            source_key=f"{CASE_KEY_PREFIX}{uuid4().hex}",
            description=description,
            contract_id=contract_id,
            assignee_user_id=assignee,
        ),
    )
    return case


async def new_request(
    db: AsyncSession,
    context: PortalContext,
    *,
    topic: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    if not await module_enabled(db):
        raise PortalError(CASES_OFF, status=503, code="cases_off")
    consultant = context.consultant
    now = local_now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = await db.scalar(
        select(func.count())
        .select_from(AdminCase)
        .where(
            AdminCase.contract_id.in_(consultant.contract_ids),
            AdminCase.source == "portal",
            AdminCase.created_at >= day_start,
        )
    )
    if (today_count or 0) >= CASES_PER_DAY:
        raise PortalError(TOO_MANY_CASES, status=429, code="cases_limit")
    clean_title = " ".join(title.replace("\x00", "").split())[:CASE_TITLE_MAX]
    clean_body = body.replace("\x00", "").strip()[:CASE_BODY_MAX]
    if not clean_title or not clean_body:
        raise PortalError("Podaj temat i opis sprawy.")
    case = await open_portal_case(
        db,
        contract_id=consultant.contract_id,
        title=clean_title,
        description=f"Temat: {TOPIC_LABELS[topic]}\n\n{clean_body}",
        now=now,
    )
    return {"id": case.id, "title": case.title, "status": case.status}


# ── Edycja FAQ (back office) ─────────────────────────────────────────────────


def clean_faq(question: str, answer: str) -> tuple[str, str]:
    clean_question = " ".join(question.replace("\x00", "").split())[:QUESTION_MAX]
    clean_answer = answer.replace("\x00", "").strip()[:ANSWER_MAX]
    if not clean_question or not clean_answer:
        raise PortalError("Podaj pytanie i odpowiedź.")
    return clean_question, clean_answer
