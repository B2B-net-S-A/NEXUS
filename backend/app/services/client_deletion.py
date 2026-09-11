"""Ręczne usunięcie klienta z profilu — ocena i wykonanie.

Trzy wyniki oceny, w tej kolejności:

* **blocked** — klient ma otwarte zamówienia (okresowe albo MD/kosztowe),
  żywe kontrakty (kontraktor pracuje albo umowa jest w podpisie) albo
  kandydatów w otwartych rekrutacjach. Blokada patrzy na FAKTY, a nie na
  ``clients.status`` — status bywa błędnie „aktywny" albo błędnie
  „nieaktywny", a o tym, czy współpraca trwa, mówią zamówienia i kontrakty.
* **purge** — klient jest PUSTY: żadnego śladu współpracy i żadnych innych
  powiązań (ta sama ocena co jednorazowe czyszczenie „Nieaktywnych", 0303).
  Usuwany trwale, z nagrobkiem dla syncu Traffita.
* **archive** — klient ma historię (zakończone zamówienia, umowy, archiwum
  konsultantów, kontakty…). Znika ze wszystkich list, ale jego wiersz zostaje,
  bo te dane nadal na niego wskazują — usunięcie fizyczne skasowałoby je
  kaskadą albo osierociło. Nic z historii nie jest kasowane.

Ocena jest tylko do odczytu. Wykonanie blokuje wiersz klienta (``FOR UPDATE``)
PRZED ponowną oceną: dopisanie zamówienia, kontraktu czy etapu kandydata
wskazującego na klienta bierze ``FOR KEY SHARE``, które czeka na tę blokadę —
ocena i usunięcie widzą ten sam stan. Commit należy do wołającego.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.client_identity import client_display_name
from app.services.inactive_client_cleanup import (
    SOURCE_LABELS,
    ClientEvaluation,
    evaluate_candidates,
    load_client_candidates,
)
from app.services.inactive_client_cleanup_run import purge_client

DeletionMode = Literal["blocked", "purge", "archive"]

CONFIRMATION_PHRASE = "0"

# Zamówienie okresowe jest „otwarte", dopóki nie jest zakończone ani anulowane
# — szkic też: to zamówienie w toku, czekające na uzupełnienie.
OPEN_ORDER_STATUSES = (
    ClientOrderStatus.draft,
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
)
# Zamówienie MD/kosztowe: ``exhausted`` i ``completed`` to koniec życia.
OPEN_ORDER_GROUP_STATUSES = ("draft", "active", "scheduled")
# Kontraktor „aktywny" = pracuje (active/ending) albo jego umowa jest właśnie
# podpisywana. Szkic kontraktu bez zamówienia nie jest pracującą osobą —
# otwarte zamówienie i tak blokuje osobno.
LIVE_CONTRACT_STATUSES = (
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)

# Ile pozycji pokazać przy każdej blokadzie — reszta jako licznik.
_ITEMS_LIMIT = 10

# Nazwy śladów historii w zdaniu „U tego klienta występują: …".
_HISTORY_LABELS: dict[str, str] = {
    "active_projects": "rekrutacje bez kandydatów w procesie",
    "closed_projects": "zamknięte rekrutacje",
    "archived_consultants": "archiwum konsultantów",
    "orders": "poprzednie zamówienia",
    "contracts": "umowy i kontrakty",
    "notes": "notatki w profilu",
    "sales_materials": "materiały sprzedażowe",
    "cooperation_stats": "historia kandydatów w rekrutacjach",
}


@dataclass(frozen=True)
class DeletionBlocker:
    code: str
    label: str
    count: int
    items: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "count": self.count,
            "items": list(self.items),
        }


@dataclass(frozen=True)
class HistoryItem:
    code: str
    label: str
    count: int

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "label": self.label, "count": self.count}


@dataclass(frozen=True)
class ClientDeletionAssessment:
    client_id: int
    client_name: str
    status: Optional[str]
    mode: DeletionMode
    blockers: tuple[DeletionBlocker, ...]
    history: tuple[HistoryItem, ...]
    evaluation: Optional[ClientEvaluation]

    @property
    def can_delete(self) -> bool:
        return self.mode != "blocked"

    def blocked_reason(self) -> str:
        parts = [f"{blocker.label} ({blocker.count})" for blocker in self.blockers]
        return "Usunięcie zablokowane: " + ", ".join(parts) + "."

    def history_sentence(self) -> Optional[str]:
        if not self.history:
            return None
        return (
            "U tego klienta występują: "
            + ", ".join(item.label for item in self.history)
            + "."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "status": self.status,
            "mode": self.mode,
            "can_delete": self.can_delete,
            "blockers": [blocker.as_dict() for blocker in self.blockers],
            "history": [item.as_dict() for item in self.history],
            "history_sentence": self.history_sentence(),
            "confirmation_phrase": CONFIRMATION_PHRASE,
        }


def _clip_items(values: list[str]) -> tuple[str, ...]:
    unique = list(dict.fromkeys(value for value in values if value))
    if len(unique) <= _ITEMS_LIMIT:
        return tuple(unique)
    return (*unique[:_ITEMS_LIMIT], f"… i {len(unique) - _ITEMS_LIMIT} więcej")


def _person(name: Optional[str], lastname: Optional[str]) -> Optional[str]:
    full = " ".join(part.strip() for part in (name, lastname) if part and part.strip())
    return full or None


async def _open_orders(db: AsyncSession, client_id: int) -> Optional[DeletionBlocker]:
    client_contracts = select(Contract.id).where(Contract.client_id == client_id)
    rows = (
        await db.execute(
            select(
                ClientOrder.id,
                ClientOrder.title,
                Candidate.name,
                Candidate.lastname,
            )
            .outerjoin(Contract, Contract.id == ClientOrder.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                or_(
                    ClientOrder.client_id == client_id,
                    ClientOrder.contract_id.in_(client_contracts),
                ),
                ClientOrder.status.in_(OPEN_ORDER_STATUSES),
                # Linie zamówień MD/kosztowych liczy grupa — jedno zamówienie
                # od klienta to jedna pozycja, nie tyle, ilu jest konsultantów.
                ClientOrder.order_group_id.is_(None),
            )
            .order_by(ClientOrder.id)
        )
    ).all()
    group_rows = (
        await db.execute(
            select(ClientOrderGroup.id, ClientOrderGroup.order_number)
            .where(
                ClientOrderGroup.client_id == client_id,
                ClientOrderGroup.status.in_(OPEN_ORDER_GROUP_STATUSES),
            )
            .order_by(ClientOrderGroup.id)
        )
    ).all()
    if not rows and not group_rows:
        return None
    items: list[str] = []
    for row in group_rows:
        items.append(f"Zamówienie {row.order_number}")
    for row in rows:
        who = _person(row.name, row.lastname)
        items.append(f"{row.title} — {who}" if who else row.title)
    return DeletionBlocker(
        code="open_orders",
        label="Otwarte zamówienia",
        count=len(rows) + len(group_rows),
        items=_clip_items(items),
    )


async def _live_contractors(
    db: AsyncSession, client_id: int
) -> Optional[DeletionBlocker]:
    rows = (
        await db.execute(
            select(Contract.id, Contract.status, Candidate.name, Candidate.lastname)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                Contract.client_id == client_id,
                Contract.status.in_(LIVE_CONTRACT_STATUSES),
            )
            .order_by(Contract.id)
        )
    ).all()
    if not rows:
        return None
    items = []
    for row in rows:
        who = _person(row.name, row.lastname) or f"kontrakt #{row.id}"
        if row.status == ContractStatus.ready_for_signature:
            who = f"{who} (umowa w podpisie)"
        items.append(who)
    return DeletionBlocker(
        code="active_contractors",
        label="Aktywni kontraktorzy",
        count=len(rows),
        items=_clip_items(items),
    )


async def _candidates_in_open_recruitments(
    db: AsyncSession, client_id: int
) -> Optional[DeletionBlocker]:
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                func.count(distinct(CandidateStage.candidate_id)).label("people"),
            )
            .join(CandidateStage, CandidateStage.job_id == Job.id)
            .where(Job.client_id == client_id, Job.status != JobStatus.closed)
            .group_by(Job.id, Job.title)
            .order_by(Job.id)
        )
    ).all()
    if not rows:
        return None
    total = await db.scalar(
        select(func.count(distinct(CandidateStage.candidate_id)))
        .join(Job, Job.id == CandidateStage.job_id)
        .where(Job.client_id == client_id, Job.status != JobStatus.closed)
    )
    return DeletionBlocker(
        code="candidates_in_open_recruitments",
        label="Kandydaci w otwartych rekrutacjach",
        count=int(total or 0),
        items=_clip_items(
            [f"{row.title} — kandydatów: {int(row.people)}" for row in rows]
        ),
    )


def _history_items(evaluation: ClientEvaluation) -> tuple[HistoryItem, ...]:
    items: list[HistoryItem] = []
    for code, count in evaluation.sources.items():
        if count:
            items.append(
                HistoryItem(
                    code=code,
                    label=_HISTORY_LABELS.get(code, SOURCE_LABELS.get(code, code)),
                    count=int(count),
                )
            )
    for reason in evaluation.related:
        label = str(reason.get("label") or reason.get("code") or "")
        if not label:
            continue
        items.append(
            HistoryItem(
                code=str(reason.get("table") or reason.get("code") or "related"),
                label=label[:1].lower() + label[1:],
                count=int(reason.get("count") or 1),
            )
        )
    return tuple(items)


async def assess_client_deletion(
    db: AsyncSession,
    client: Client,
    *,
    environ: Optional[dict[str, str]] = None,
) -> ClientDeletionAssessment:
    """Oceń, czy i jak można usunąć klienta. Tylko odczyt."""

    blockers = tuple(
        blocker
        for blocker in (
            await _open_orders(db, client.id),
            await _live_contractors(db, client.id),
            await _candidates_in_open_recruitments(db, client.id),
        )
        if blocker is not None
    )
    candidates = await load_client_candidates(db, [client.id])
    plan = await evaluate_candidates(db, candidates, environ=environ)
    evaluation = next(
        iter((*plan.deletable, *plan.held, *plan.kept)),
        None,
    )
    history = _history_items(evaluation) if evaluation is not None else ()
    if blockers:
        mode: DeletionMode = "blocked"
    elif evaluation is not None and evaluation.verdict == "delete":
        mode = "purge"
    else:
        mode = "archive"
    return ClientDeletionAssessment(
        client_id=client.id,
        client_name=client_display_name(client),
        status=getattr(client.status, "value", client.status),
        mode=mode,
        blockers=blockers,
        history=history,
        evaluation=evaluation,
    )


async def lock_client(db: AsyncSession, client_id: int) -> Optional[Client]:
    return await db.scalar(
        select(Client)
        .where(Client.id == client_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def execute_client_deletion(
    db: AsyncSession,
    client: Client,
    *,
    actor: User,
    environ: Optional[dict[str, str]] = None,
) -> ClientDeletionAssessment:
    """Usuń klienta według świeżej oceny. Klient musi być zablokowany.

    Zwraca ocenę, na podstawie której działano — przy ``blocked`` nic nie
    zostało zmienione.
    """

    assessment = await assess_client_deletion(db, client, environ=environ)
    if assessment.mode == "blocked":
        return assessment

    now = datetime.now(timezone.utc)
    if assessment.mode == "purge":
        assert assessment.evaluation is not None
        await purge_client(
            db,
            assessment.evaluation,
            run=None,
            actor=actor,
            purged_at=now,
            activity_action="deleted_manually",
        )
        return assessment

    client.deleted_at = now
    client.deleted_by = actor.id
    # ``archived_at`` też, bo część list filtruje wyłącznie po nim; oryginalny
    # moment archiwizacji (np. po scaleniu) zostaje.
    client.archived_at = client.archived_at or now
    client.archived_by = client.archived_by or actor.id
    db.add(
        Activity(
            entity_type="client",
            entity_id=client.id,
            action="deleted_manually",
            user_id=actor.id,
            details={
                "mode": "archive",
                "name": assessment.client_name,
                "history": [item.as_dict() for item in assessment.history],
            },
        )
    )
    await db.flush()
    return assessment
