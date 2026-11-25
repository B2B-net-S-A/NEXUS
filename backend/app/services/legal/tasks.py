"""Zadania asystenta prawnego w tle listy i strony kontraktu (właściciel: część F).

Kontrakt z planu (``docs/asystent-prawny-plan.md``, „Podział F / G”): każdy
dostawca ``TaskProvider`` zwraca ``LegalTaskRow`` i **sam pilnuje zakresu
klientów i bramek** pytającego; ``collect`` sumuje dostawców, usuwa powtórki
klucza i zadania zamknięte w ``legal_assistant_tasks`` (0783). Zadań nie
zapisujemy — liczą się z danych przy odczycie, więc nie ma pętli w tle.

Dostawca części F: „szkic odpowiedzi na wypowiedzenie czeka” — kontrakt B2B
z wypowiedzeniem złożonym przez Partnera (``agreement_termination_party =
consultant``, tryb ``notice``), umowa jeszcze trwa, a pisma nikt nie
zatwierdził. Część G dopisuje swojego dostawcę (``client_fit_tasks``)
do ``TASK_PROVIDERS`` przy scalaniu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from typing import Awaitable, Callable, Literal, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.financial_access import can_read_client_finance
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.legal_assistant_task import LegalAssistantTask
from app.models.user import User
from app.services.access_scope import (
    apply_delivery_lead_client_scope,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.legal.tasks_schema import STATUS_DISMISSED, STATUS_DONE

logger = logging.getLogger(__name__)

TaskKind = Literal["notice_reply", "client_fit_gap", "template_review"]
Severity = Literal["info", "warn", "gap"]

KIND_NOTICE_REPLY: TaskKind = "notice_reply"
#: Najwyżej tyle zadań jednego dostawcy na pasku (reszta to zaległości do
#: przejrzenia na liście „Umowa nierozwiązana”).
PROVIDER_LIMIT = 50


@dataclass(frozen=True)
class LegalTaskRow:
    key: str  # stabilny, bez duplikatów
    kind: TaskKind
    severity: Severity
    title: str
    detail: str
    action_label: str
    href: str
    client_id: int | None
    contract_id: int | None
    created_at: datetime


TaskProvider = Callable[[AsyncSession, User], Awaitable[list[LegalTaskRow]]]


def notice_task_key(contract_id: int, signed_on: date) -> str:
    """Klucz zadania po wypowiedzeniu: kontrakt + dzień złożenia (nowe wypowiedzenie = nowe zadanie)."""
    return f"notice_reply:{contract_id}:{signed_on.isoformat()}"


def letter_href(contract_id: int, kind: str = "notice_reply") -> str:
    return f"/contracts/{contract_id}?pismo={kind}"


def _person(row: Contract, candidate: Optional[Candidate]) -> str:
    if candidate is not None:
        full = " ".join(p for p in (candidate.name, candidate.lastname) if p).strip()
        if full:
            return full
    return f"Kontrakt #{row.id}"


def notice_rows(
    rows: Sequence[tuple[Contract, Optional[Candidate], Optional[Client]]],
) -> list[LegalTaskRow]:
    """Wiersze zadań z kontraktów z wypowiedzeniem Partnera — jedno na wypowiedzenie.

    Dwa kontrakty jednej osoby z tym samym dniem wypowiedzenia (kolejne projekty
    na jednej umowie B2B) to jedno wypowiedzenie i jedno pismo — zostaje
    najnowszy kontrakt.
    """
    out: dict[tuple[object, date], LegalTaskRow] = {}
    for contract, candidate, client in sorted(
        rows, key=lambda r: r[0].id, reverse=True
    ):
        signed_on = contract.agreement_termination_signed_on
        if signed_on is None:
            continue
        person = contract.candidate_id or f"contract:{contract.id}"
        if (person, signed_on) in out:
            continue
        last_day = contract.agreement_last_day
        client_name = (
            (client.display_name or client.name) if client is not None else None
        )
        detail = " · ".join(
            part
            for part in (
                f"Wypowiedzenie Partnera z {signed_on:%d.%m.%Y}",
                f"ostatni dzień umowy {last_day:%d.%m.%Y}" if last_day else None,
                client_name,
            )
            if part
        )
        out[(person, signed_on)] = LegalTaskRow(
            key=notice_task_key(contract.id, signed_on),
            kind=KIND_NOTICE_REPLY,
            severity="info",
            title=f"{_person(contract, candidate)}: szkic odpowiedzi na wypowiedzenie czeka",
            detail=detail,
            action_label="Otwórz szkic",
            href=letter_href(contract.id),
            client_id=contract.client_id,
            contract_id=contract.id,
            # Ze strefą firmy: dostawca zgodności daje ``checked_at`` ze strefą,
            # a ``merge_rows`` sortuje oba razem (naiwna data = TypeError, 500).
            created_at=datetime.combine(
                signed_on, time(12), tzinfo=ZoneInfo(DEFAULT_TZ)
            ),
        )
    return list(out.values())


async def notice_reply_tasks(db: AsyncSession, user: User) -> list[LegalTaskRow]:
    """Dostawca F: wypowiedzenia Partnerów bez zatwierdzonej odpowiedzi.

    Zakres = bramka treści umowy (pobranie dokumentu kontraktu): „Stawki
    i kwoty: podgląd” albo Moduł Finanse, a konto z rolą Delivery Leada —
    tylko klienci z przypisania. Pismo czyta podpisaną umowę, więc bez tej
    bramki zadanie prowadziłoby do odmowy.
    """
    finance_ids = await resolve_delivery_lead_finance_client_ids(user, db)
    stmt = (
        select(Contract, Candidate, Client)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(
            Contract.contract_type == ContractType.b2b,
            Contract.status != ContractStatus.void,
            Contract.agreement_termination_party == "consultant",
            Contract.agreement_termination_mode == "notice",
            Contract.agreement_termination_signed_on.is_not(None),
            Contract.agreement_last_day >= business_today(),
        )
        .order_by(Contract.agreement_termination_signed_on.desc(), Contract.id.desc())
        .limit(PROVIDER_LIMIT * 2)
    )
    stmt = apply_delivery_lead_client_scope(stmt, Contract.client_id, finance_ids)
    rows = [
        (contract, candidate, client)
        for contract, candidate, client in (await db.execute(stmt)).all()
        if can_read_client_finance(
            user,
            client_id=contract.client_id,
            delivery_lead_finance_client_ids=finance_ids,
        )
    ]
    return notice_rows(rows)[:PROVIDER_LIMIT]


async def _client_fit_tasks(db: AsyncSession, user: User) -> list[LegalTaskRow]:
    """Część G: luki wobec umowy ramowej klienta.

    Import w funkcji, bo ``legal_client_fit.task_provider`` sam importuje
    ``LegalTaskRow`` z tego modułu.
    """
    from app.services.legal_client_fit.task_provider import client_fit_tasks

    return await client_fit_tasks(db, user)


#: Dostawcy zadań: wypowiedzenia (część F) i zgodność z umową klienta (część G).
TASK_PROVIDERS: list[TaskProvider] = [notice_reply_tasks, _client_fit_tasks]


async def closed_keys(db: AsyncSession, keys: Sequence[str]) -> set[str]:
    if not keys:
        return set()
    rows = await db.execute(
        select(LegalAssistantTask.task_key).where(
            LegalAssistantTask.task_key.in_(list(keys))
        )
    )
    return set(rows.scalars().all())


def merge_rows(
    batches: Sequence[Sequence[LegalTaskRow]], closed: set[str]
) -> list[LegalTaskRow]:
    """Suma dostawców bez powtórek klucza i bez zadań zamkniętych, najnowsze pierwsze."""
    seen: dict[str, LegalTaskRow] = {}
    for batch in batches:
        for row in batch:
            if row.key in closed or row.key in seen:
                continue
            seen[row.key] = row
    return sorted(seen.values(), key=lambda r: _aware(r.created_at), reverse=True)


def _aware(moment: datetime) -> datetime:
    """Naiwna data dostawcy = czas firmy (Europe/Warsaw), żeby sortowanie nie padało."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=ZoneInfo(DEFAULT_TZ))
    return moment


async def collect(
    db: AsyncSession,
    user: User,
    providers: Optional[Sequence[TaskProvider]] = None,
) -> list[LegalTaskRow]:
    """Zadania asystenta dla pytającego. Awaria dostawcy idzie wyżej (500), nie
    znika jako pusta lista — pusty pasek znaczy „nic do zrobienia”."""
    batches = [await provider(db, user) for provider in (providers or TASK_PROVIDERS)]
    keys = [row.key for batch in batches for row in batch]
    return merge_rows(batches, await closed_keys(db, keys))


async def close_task(
    db: AsyncSession,
    *,
    key: str,
    kind: str,
    status: str,
    user_id: Optional[int],
    contract_id: Optional[int],
    client_id: Optional[int],
    letter_kind: Optional[str] = None,
) -> None:
    """Zamyka zadanie (``done`` po „Zatwierdzam”, ``dismissed`` po „Pomiń”); idempotentne."""
    if status not in (STATUS_DONE, STATUS_DISMISSED):
        raise ValueError(f"Nieznany stan zadania: {status!r}.")
    stmt = insert(LegalAssistantTask).values(
        task_key=key,
        kind=kind,
        status=status,
        contract_id=contract_id,
        client_id=client_id,
        letter_kind=letter_kind,
        resolved_by=user_id,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[LegalAssistantTask.task_key],
            set_={
                "status": stmt.excluded.status,
                "letter_kind": stmt.excluded.letter_kind,
                "resolved_by": stmt.excluded.resolved_by,
                "resolved_at": func.now(),
            },
        )
    )
