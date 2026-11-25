"""Dostawca zadań asystenta prawnego: luki w umowach B2B wobec umowy ramowej klienta.

Kontrakt zadań (``docs/asystent-prawny-plan.md``, „Podział F / G”) należy do
części F (``app/services/legal/tasks.py``, ``GET /api/legal/tasks``); część G
daje tylko dostawcę. Rejestrację w ``TASK_PROVIDERS`` robi sesja scalająca.

Dostawca sam pilnuje zakresu (jak trasy ``/api/legal/client-fit``, czyli
treść umów ramowych): sekcja Delivery do odczytu, „Stawki i kwoty: podgląd”
i — dla Delivery Leada — wyłącznie klienci z przypisania. Bez tego zadanie
ujawniałoby treść wymogów z umowy klienta komuś, kto nie może jej otworzyć.
Jedno zadanie na klienta (klucz ``client_fit_gap:<id>:<chwila sprawdzenia>``),
tylko przy wyniku ostatniego sprawdzenia, który ekran też pokazuje; „Pomiń”
wycisza to jedno sprawdzenie, nowe z luką wraca na pasek.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.legal_client_fit import LegalClientFitCheck, LegalClientFitFinding
from app.models.user import User
from app.services.access_scope import resolve_delivery_lead_client_ids
from app.services.action_permissions import ProductAction, has_permission
from app.services.legal.tasks import LegalTaskRow
from app.services.legal_client_fit import service
from app.services.legal_client_fit.sources import SOURCE_AMENDMENT
from app.services.legal_client_fit.topics import TOPIC_BY_KEY
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)


ACTION_LABEL = "Zobacz i przygotuj aneks"


def annex_href(client_id: int) -> str:
    """Kreator „Nowy aneks” (inna zmiana) z oknem ustaleń klienta."""
    return f"/contracts/b2b-generator?tab=annexes&new=annex_custom&zgodnosc={client_id}"


def fit_task_key(client_id: int, check: LegalClientFitCheck) -> str:
    """Klucz zadania = klient + to sprawdzenie (chwila wyniku). „Pomiń” wycisza
    tylko ten wynik; kolejne sprawdzenie z luką daje nowe zadanie."""
    moment = check.checked_at or check.requested_at
    stamp = int(moment.timestamp()) if moment is not None else 0
    return f"client_fit_gap:{client_id}:{stamp}"


def _contracts_phrase(count: int) -> str:
    if count == 1:
        return "1 umowa B2B nie przenosi"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} umowy B2B nie przenoszą"
    return f"{count} umów B2B nie przenosi"


def _gaps_phrase(gaps: int, decide: int) -> str:
    parts = []
    if gaps:
        parts.append(f"luki: {gaps}")
    if decide:
        parts.append(f"do decyzji: {decide}")
    return ", ".join(parts)


async def visible_client_ids(db: AsyncSession, user: User) -> Optional[frozenset[int]]:
    """Klienci, których treść umów ramowych użytkownik może czytać; ``None`` = wszyscy.

    Pusty zbiór = brak dostępu (tak samo jak 403 na trasach).
    """
    if section_access_for_user(user, ProductSection.delivery) < SectionAccess.read:
        return frozenset()
    if not has_permission(user, ProductAction.amounts_view):
        return frozenset()
    return await resolve_delivery_lead_client_ids(user, db)


async def client_fit_tasks(db: AsyncSession, user: User) -> list[LegalTaskRow]:
    scope = await visible_client_ids(db, user)
    if scope is not None and not scope:
        return []
    stmt = (
        select(LegalClientFitFinding, LegalClientFitCheck, Client)
        .join(
            LegalClientFitCheck,
            LegalClientFitCheck.client_id == LegalClientFitFinding.client_id,
        )
        .join(Client, Client.id == LegalClientFitFinding.client_id)
        .where(
            LegalClientFitFinding.state.in_(("gap", "decide")),
            LegalClientFitCheck.status.in_(tuple(service.SHOWS_FINDINGS)),
            Client.deleted_at.is_(None),
        )
        .order_by(LegalClientFitFinding.client_id, LegalClientFitFinding.id)
    )
    if scope is not None:
        stmt = stmt.where(LegalClientFitFinding.client_id.in_(list(scope)))
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    by_client: dict[
        int, tuple[Client, LegalClientFitCheck, list[LegalClientFitFinding]]
    ] = {}
    for finding, check, client in rows:
        by_client.setdefault(client.id, (client, check, []))[2].append(finding)
    counts = await service.active_b2b_contracts(db, list(by_client))
    amendment_ids = {
        f.client_source_id
        for _c, _k, findings in by_client.values()
        for f in findings
        if f.client_source_kind == SOURCE_AMENDMENT
    }
    amendment_names: dict[int, str] = {}
    if amendment_ids:
        amendment_names = {
            int(a_id): name
            for a_id, name in (
                await db.execute(
                    select(
                        ClientContractAmendment.id, ClientContractAmendment.name
                    ).where(ClientContractAmendment.id.in_(list(amendment_ids)))
                )
            ).all()
        }

    tasks: list[LegalTaskRow] = []
    for client_id, (client, check, findings) in by_client.items():
        gaps = [f for f in findings if f.state == "gap"]
        decide = [f for f in findings if f.state == "decide"]
        kinds = {(f.client_source_kind, f.client_source_id) for f in findings}
        source = "z umowy ramowej"
        if len(kinds) == 1:
            kind, source_id = next(iter(kinds))
            if kind == SOURCE_AMENDMENT and amendment_names.get(source_id):
                source = f"z aneksu „{amendment_names[source_id]}”"
        name = (
            client.display_name or client.name or ""
        ).strip() or f"Klient #{client_id}"
        active = counts.get(client_id, 0)
        title = (
            f"{name}: {_contracts_phrase(active)} wymogów {source}"
            if active
            else f"{name}: wzór umowy B2B nie przenosi wymogów {source}"
        )
        topics = ", ".join(
            TOPIC_BY_KEY[f.topic].label if f.topic in TOPIC_BY_KEY else f.topic
            for f in (*gaps, *decide)
        )
        tasks.append(
            LegalTaskRow(
                key=fit_task_key(client_id, check),
                kind="client_fit_gap",
                severity="gap" if gaps else "warn",
                title=title,
                detail=f"{_gaps_phrase(len(gaps), len(decide))} · {topics}",
                action_label=ACTION_LABEL,
                href=annex_href(client_id),
                client_id=client_id,
                contract_id=None,
                created_at=check.checked_at or check.requested_at,
            )
        )
    return tasks
