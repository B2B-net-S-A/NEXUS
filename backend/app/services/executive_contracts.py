"""Struktura umów wykonawczych Centrum e-Zdrowia — logika za routerem.

Ticket „Struktura umów wykonawczych" (09.2026): umowa ramowa = część
(``cz1``…``cz6``) → 0..N umów wykonawczych, a konsultant jest przypisany do
KONKRETNEJ umowy wykonawczej, nie do części. Przypisanie żyje na
REPREZENTATYWNYM zamówieniu kontraktu (``representative_order`` — ta sama
reguła co tag na profilu), więc ekran przeglądu i profil widzą to samo.

Serwis jest wołany przez ``app/api/client_executive_contracts.py`` i ma być
reużyty przez import danych — dlatego nie zna ``HTTPException``: odmowy
biznesowe idą jako ``ValueError`` (router → 422) albo
``ExecutiveContractConflict`` (router → 409: duplikat numeru, zakończenie
umowy z żywymi przypisaniami).

Ekran przeglądu NIE preselekcjonuje żadnej umowy (decyzja z ticketu): numery
„DO UMOWY RAMOWEJ" na dokumentach są zamienione, więc każda automatyczna
podpowiedź powielałaby błąd źródła. ``suggested_framework_contract_id`` służy
wyłącznie do podświetlenia nagłówka części w selekcie.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.core.work_time import HOURS_PER_MONTH
from app.models.activity import Activity
from app.models.client_executive_contract import (
    EXECUTIVE_CONTRACT_STATUS_ACTIVE,
    EXECUTIVE_CONTRACT_STATUS_ENDED,
    ClientExecutiveContract,
)
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus, RateUnit
from app.schemas.client_executive_contract import (
    CandidateRef,
    ContractStructureResponse,
    ExecutiveContractAssignmentRequest,
    ExecutiveContractAssignmentResponse,
    ExecutiveContractBrief,
    ExecutiveContractCreate,
    ExecutiveContractRead,
    ExecutiveContractReviewResponse,
    ExecutiveContractReviewRow,
    ExecutiveContractUpdate,
    FrameworkPartRead,
)
from app.services.contractor_identity import current_contracts
from app.services.ezdrowie import PROJECT_PARTS, resolve_ezdrowie_assignment
from app.services.order_write_errors import commit_order_write
from app.services.representative_order import representative_order

DUPLICATE_NUMBER_MESSAGE = "Umowa wykonawcza o tym numerze już istnieje u tego klienta"
FRAMEWORK_NOT_PART_MESSAGE = (
    "Umowa ramowa nie jest częścią zamówienia Centrum e-Zdrowia"
)

# Kontrakty, których przypisanie jest „żywe": profil pokazuje je w „Obecnych"
# albo „Planowanych", więc zakończenie ich umowy wykonawczej zostawiłoby
# konsultanta z tagiem umowy, do której nie da się już nikogo przypisać.
_LIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)


class ExecutiveContractConflict(ValueError):
    """Odmowa, którą router zgłasza jako 409 (stan danych, nie błąd payloadu)."""


def executive_brief(executive: ClientExecutiveContract) -> ExecutiveContractBrief:
    """Wymaga załadowanej relacji ``framework_contract`` (część jest z niej)."""
    framework = executive.framework_contract
    return ExecutiveContractBrief(
        id=executive.id,
        number=executive.number,
        status=executive.status,
        framework_contract_id=executive.framework_contract_id,
        project_part=framework.project_part if framework is not None else None,
    )


def _part_position(part: Optional[str]) -> int:
    return PROJECT_PARTS.index(part) if part in PROJECT_PARTS else len(PROJECT_PARTS)


async def _framework_parts(
    db: AsyncSession, client_id: int
) -> list[ClientFrameworkContract]:
    rows = (
        await db.execute(
            select(ClientFrameworkContract)
            .options(selectinload(ClientFrameworkContract.executive_contracts))
            .where(
                ClientFrameworkContract.client_id == client_id,
                ClientFrameworkContract.project_part.is_not(None),
            )
        )
    ).scalars()
    # Kolejność części, nie kolejność wstawiania: cz.3 nie istnieje, więc
    # sortowanie po samym tekście dawałoby cz4 „obok" cz2 bez luki, ale
    # kolejność słownika jest jedynym kontraktem, jaki obiecuje odpowiedź.
    return sorted(rows, key=lambda fc: (_part_position(fc.project_part), fc.id))


async def _live_contracts(db: AsyncSession, client_id: int) -> list[Contract]:
    """Kontrakty active/ending klienta z zamówieniami — reprezentant liczony
    z pamięci (``representative_order`` wymaga załadowanej relacji)."""
    return list(
        (
            await db.execute(
                select(Contract)
                .options(
                    selectinload(Contract.candidate),
                    selectinload(Contract.client_orders),
                )
                .where(
                    Contract.client_id == client_id,
                    Contract.status.in_(_LIVE_CONTRACT_STATUSES),
                )
                .order_by(Contract.start_date.desc().nullslast(), Contract.id)
            )
        )
        .scalars()
        .all()
    )


def _assigned_counts(contracts: list[Contract]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for contract in contracts:
        order = representative_order(contract)
        if order is None or order.executive_contract_id is None:
            continue
        counts[order.executive_contract_id] = (
            counts.get(order.executive_contract_id, 0) + 1
        )
    return counts


async def load_structure(db: AsyncSession, client_id: int) -> ContractStructureResponse:
    """Umowy ramowe-części klienta (cz1, cz2, cz4, cz5, cz6) z wykonawczymi.

    ``consultants_count`` liczy KONTRAKTY (nie zamówienia), których
    reprezentatywne zamówienie wskazuje umowę — ta sama liczba, którą
    daje filtr na profilu klienta.
    """
    frameworks = await _framework_parts(db, client_id)
    counts = _assigned_counts(await _live_contracts(db, client_id))
    return ContractStructureResponse(
        framework_contracts=[
            FrameworkPartRead(
                id=fc.id,
                name=fc.name,
                project_part=fc.project_part or "",
                status=fc.status.value,
                executive_contracts=[
                    ExecutiveContractRead(
                        id=ec.id,
                        number=ec.number,
                        status=ec.status,
                        framework_contract_id=ec.framework_contract_id,
                        project_part=fc.project_part,
                        notes=ec.notes,
                        consultants_count=counts.get(ec.id, 0),
                        created_at=ec.created_at,
                    )
                    for ec in fc.executive_contracts
                ],
            )
            for fc in frameworks
        ]
    )


async def _number_taken(
    db: AsyncSession, client_id: int, number: str, *, exclude_id: Optional[int]
) -> bool:
    stmt = select(ClientExecutiveContract.id).where(
        ClientExecutiveContract.client_id == client_id,
        ClientExecutiveContract.number == number,
    )
    if exclude_id is not None:
        stmt = stmt.where(ClientExecutiveContract.id != exclude_id)
    return (await db.scalar(stmt)) is not None


async def create_executive_contract(
    db: AsyncSession,
    client_id: int,
    payload: ExecutiveContractCreate,
    user_id: Optional[int],
) -> ClientExecutiveContract:
    """Nowa umowa wykonawcza pod umową ramową-częścią TEGO klienta.

    Duplikat numeru jest sprawdzany PRZED insertem — UNIQUE w bazie i tak go
    odrzuci, ale wtedy jako IntegrityError, czyli 500 bez CORS („Network
    Error"), a nie jako zdanie po polsku.
    """
    framework = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == payload.framework_contract_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if framework is None or framework.project_part is None:
        raise ValueError(FRAMEWORK_NOT_PART_MESSAGE)
    if await _number_taken(db, client_id, payload.number, exclude_id=None):
        raise ExecutiveContractConflict(DUPLICATE_NUMBER_MESSAGE)
    executive = ClientExecutiveContract(
        client_id=client_id,
        framework_contract_id=framework.id,
        number=payload.number,
        status=EXECUTIVE_CONTRACT_STATUS_ACTIVE,
        notes=payload.notes,
        created_by_user_id=user_id,
    )
    executive.framework_contract = framework
    db.add(executive)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="executive_contract_created",
            user_id=user_id,
            details={
                "framework_contract_id": framework.id,
                "project_part": framework.project_part,
                "number": payload.number,
            },
        )
    )
    await db.commit()
    # Tylko kolumny: pełny `refresh` wygasza też relację `framework_contract`,
    # którą `executive_brief` czyta zaraz potem (lazy-load w async =
    # `MissingGreenlet`, 500 bez CORS).
    await db.refresh(executive, attribute_names=["id", "status", "created_at"])
    return executive


async def _load_executive(
    db: AsyncSession, client_id: int, executive_contract_id: int
) -> ClientExecutiveContract:
    executive = await db.scalar(
        select(ClientExecutiveContract)
        .options(selectinload(ClientExecutiveContract.framework_contract))
        .where(
            ClientExecutiveContract.id == executive_contract_id,
            ClientExecutiveContract.client_id == client_id,
        )
    )
    if executive is None:
        raise ValueError(
            "Wskazana umowa wykonawcza nie istnieje albo należy do innego klienta"
        )
    return executive


async def update_executive_contract(
    db: AsyncSession,
    client_id: int,
    executive_contract_id: int,
    payload: ExecutiveContractUpdate,
    user_id: Optional[int] = None,
) -> ClientExecutiveContract:
    """PATCH: numer, status, notatki. Pola nieprzysłane zostają bez zmian.

    ``ended`` z żywymi przypisaniami → ``ExecutiveContractConflict`` (409):
    konsultant z tagiem zakończonej umowy nie mógłby zostać przepięty, bo
    ``resolve_ezdrowie_assignment`` przyjmuje wyłącznie umowy ``active``.
    Najpierw przepisz ludzi, potem zamknij umowę.
    """
    executive = await _load_executive(db, client_id, executive_contract_id)
    data = payload.model_dump(exclude_unset=True)
    if "number" in data and data["number"] != executive.number:
        if await _number_taken(db, client_id, data["number"], exclude_id=executive.id):
            raise ExecutiveContractConflict(DUPLICATE_NUMBER_MESSAGE)
    if (
        data.get("status") == EXECUTIVE_CONTRACT_STATUS_ENDED
        and executive.status != EXECUTIVE_CONTRACT_STATUS_ENDED
    ):
        assigned = _assigned_counts(await _live_contracts(db, client_id)).get(
            executive.id, 0
        )
        # Karty MD (grupy) wskazują umowę bezpośrednio — żywa karta blokuje
        # zakończenie tak samo jak przypisany konsultant.
        live_groups = await db.scalar(
            select(func.count(ClientOrderGroup.id)).where(
                ClientOrderGroup.client_id == client_id,
                ClientOrderGroup.executive_contract_id == executive.id,
                ClientOrderGroup.status.in_(("active", "scheduled", "draft")),
            )
        )
        if live_groups:
            raise ExecutiveContractConflict(
                f"Umowa wykonawcza {executive.number} ma {live_groups} "
                "otwartych kart zamówień MD — zakończ je albo załóż pod inną umową"
            )
        if assigned:
            raise ExecutiveContractConflict(
                f"Umowa wykonawcza {executive.number} ma {assigned} "
                "przypisanych konsultantów — przepisz ich na inną umowę, "
                "zanim ją zakończysz"
            )
    changed = {
        field: value
        for field, value in data.items()
        if getattr(executive, field) != value
    }
    for field, value in changed.items():
        setattr(executive, field, value)
    if changed:
        db.add(
            Activity(
                entity_type="client",
                entity_id=client_id,
                action="executive_contract_updated",
                user_id=user_id,
                details={
                    "executive_contract_id": executive.id,
                    "number": executive.number,
                    "changed": sorted(changed),
                },
            )
        )
    await db.commit()
    await db.refresh(executive, attribute_names=["number", "status", "notes"])
    return executive


def _candidate_ref(contract: Contract) -> CandidateRef:
    candidate = contract.candidate
    if candidate is None:
        return CandidateRef(id=None, name="?")
    full_name = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
    return CandidateRef(id=candidate.id, name=full_name or "?")


async def review_rows(
    db: AsyncSession, client_id: int
) -> ExecutiveContractReviewResponse:
    """Konsultanci bez umowy wykonawczej na reprezentatywnym zamówieniu.

    „Obecny"/„planowany" wg TEJ SAMEJ reguły co profil klienta
    (``contractor_identity.current_contracts``) — inaczej ekran przeglądu
    pokazywałby kogoś w innym koszyku niż zakładka obok. Kontrakt bez żadnego
    nieanulowanego zamówienia też jest do przeglądu: przypisanie założy mu
    szkic (``assign_executive_contract``).
    """
    contracts = await _live_contracts(db, client_id)
    today = business_today()
    current_ids = {
        c.id
        for c in current_contracts(
            contracts,
            today,
            fallback_start_by_contract={
                c.id: getattr(representative_order(c, today), "start_date", None)
                for c in contracts
            },
        )
    }
    frameworks_by_part = {
        fc.project_part: fc.id for fc in await _framework_parts(db, client_id)
    }
    rows: list[ExecutiveContractReviewRow] = []
    for contract in contracts:
        order = representative_order(contract)
        if order is not None and order.executive_contract_id is not None:
            continue
        legacy_part = order.project_part if order is not None else None
        rows.append(
            ExecutiveContractReviewRow(
                contract_id=contract.id,
                candidate=_candidate_ref(contract),
                start_date=contract.start_date,
                bucket="active" if contract.id in current_ids else "planned",
                legacy_project_part=legacy_part,
                representative_order_id=order.id if order is not None else None,
                suggested_framework_contract_id=frameworks_by_part.get(legacy_part),
            )
        )
    return ExecutiveContractReviewResponse(rows=rows, total=len(rows))


def _draft_order_for(
    contract: Contract,
    *,
    executive: ClientExecutiveContract,
    project_part: Optional[str],
    user_id: Optional[int],
) -> ClientOrder:
    """Szkic zamówienia dla kontraktu bez zamówienia — minimalny zestaw pól.

    Lustro ``create_order_extension``: jednostka i godziny rozliczeniowe
    dziedziczone z kontraktu (kolumny NOT NULL z domyślnymi ``monthly``/168),
    stawki puste — to szkic do uzupełnienia, nie zamówienie od klienta.
    Tytułem jest numer umowy wykonawczej, bo to jedyna rzecz, którą o tym
    zamówieniu wiemy na pewno.
    """
    unit = contract.rate_unit or RateUnit.monthly
    return ClientOrder(
        client_id=contract.client_id,
        contract_id=contract.id,
        contract=contract,
        job_id=contract.job_id,
        title=executive.number,
        status=ClientOrderStatus.draft,
        start_date=contract.start_date,
        rate_unit=unit,
        billing_hours_per_month=contract.billing_hours_per_month or HOURS_PER_MONTH,
        executive_contract_id=executive.id,
        project_part=project_part,
        created_by_user_id=user_id,
    )


async def assign_executive_contract(
    db: AsyncSession,
    client_id: int,
    payload: ExecutiveContractAssignmentRequest,
    user_id: Optional[int],
) -> ExecutiveContractAssignmentResponse:
    """Ręczne przypisanie konsultanta do umowy wykonawczej (ekran przeglądu).

    Zapis ląduje na REPREZENTATYWNYM zamówieniu kontraktu — tym samym, które
    czyta profil — więc po przypisaniu wiersz znika z przeglądu, a tag pojawia
    się na profilu bez drugiego źródła prawdy. Część jest POCHODNĄ z umowy
    ramowej (``resolve_ezdrowie_assignment``), nigdy wpisywana osobno.
    """
    executive_id, project_part = await resolve_ezdrowie_assignment(
        db,
        client_id=client_id,
        executive_contract_id=payload.executive_contract_id,
        project_part=None,
        require=True,
    )
    executive = await _load_executive(db, client_id, executive_id)
    contract = await db.scalar(
        select(Contract)
        .options(selectinload(Contract.client_orders))
        .where(Contract.id == payload.contract_id, Contract.client_id == client_id)
    )
    if contract is None:
        raise ValueError("Kontrakt nie istnieje albo należy do innego klienta")

    order = representative_order(contract)
    if order is not None and order.order_group_id is not None:
        # Linia karty MD dziedziczy umowę z KARTY — przypisanie na linii
        # rozjechałoby tag konsultanta z nagłówkiem karty i obeszło guard
        # zakończenia umowy. Kartę zakłada się pod umową przy tworzeniu.
        raise ExecutiveContractConflict(
            "Ten konsultant jest na karcie zamówienia MD — umowę wykonawczą "
            "karty ustala się przy jej tworzeniu, nie przez przypisanie osoby"
        )
    created_draft = order is None
    if order is None:
        order = _draft_order_for(
            contract, executive=executive, project_part=project_part, user_id=user_id
        )
        db.add(order)
        await db.flush()
    else:
        order.executive_contract_id = executive.id
        order.project_part = project_part

    db.add(
        Activity(
            entity_type="client_order",
            entity_id=order.id,
            action="executive_contract_assigned",
            user_id=user_id,
            details={
                "contract_id": contract.id,
                "executive_contract_id": executive.id,
                "created_draft": created_draft,
            },
        )
    )
    await db.flush()
    await commit_order_write(db)
    return ExecutiveContractAssignmentResponse(
        contract_id=contract.id,
        order_id=order.id,
        executive_contract=executive_brief(executive),
        created_draft=created_draft,
    )
