from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import RedirectResponse

from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.schemas.client import (
    AnyClientResponse,
    ClientCreate,
    ClientList,
    ClientResponse,
    ClientSafeResponse,
    ClientUpdate,
)
from app.services.access_scope import (
    apply_delivery_lead_client_scope,
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.client_access import ADMIN_LIKE_ROLES, CLIENT_TEAM_ROLES
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
    visible_client_predicates,
)
from app.schemas.money import to_whole_pln
from app.schemas.client_profile import (
    ActiveConsultantItem,
    CandidateBrief,
    ClientProfileHistory,
    ClientProfileResponse,
    ClientProfileSummary,
    HistoricalPlacementItem,
    LostJobItem,
    OpenJobItem,
    RecruiterBrief,
)
from app.api.contracts import _effective_rate_fields
from app.api.deps import AdminUser, OperationalUser, TacPlus

router = APIRouter()


# ── Profile helpers ───────────────────────────────────────────────────────────
#
# The Client Profile endpoint aggregates everything the UI needs in one call:
# open jobs, active consultants, historical placements, lost jobs, and a
# summary bar (MRR, LTV, avg time-to-fill). Kept as private functions to make
# the endpoint body readable — they use the Contract model's existing
# `monthly_rate_client` / `monthly_margin` properties rather than duplicating
# `_sql_monthly()` from reports.py.


def _duration_months(start: date, end: Optional[date]) -> Optional[int]:
    """Whole months between two dates (floor). None when start is missing."""
    if start is None:
        return None
    boundary = end or date.today()
    if boundary < start:
        return 0
    days = (boundary - start).days
    return max(0, days // 30)


def _contract_total_revenue(
    contract: Contract,
    boundary: Optional[date] = None,
    monthly_rate_client: Optional[object] = None,
) -> Optional[int]:
    """Cumulative revenue from a contract up to a boundary date (exclusive).

    For active contracts the caller passes `boundary=date.today()` so LTV keeps
    ticking. For ended contracts the caller passes the actual end date
    (terminated_at preferred, falls back to end_date, then today).

    ``monthly_rate_client`` lets the caller inject the rate resolved from the
    effective-dated schedule. Without it this would fall back to the legacy
    column and the archive row would show a revenue total computed from a
    different rate than the one displayed next to it in the same row.
    """
    monthly = (
        monthly_rate_client
        if monthly_rate_client is not None
        else contract.monthly_rate_client
    )
    if monthly is None or contract.start_date is None:
        return None
    months = _duration_months(contract.start_date, boundary)
    if months is None:
        return None
    return int(monthly) * int(months)


def _candidate_brief(candidate: Candidate) -> CandidateBrief:
    full_name = f"{candidate.name or ''} {candidate.lastname or ''}".strip() or "?"
    return CandidateBrief(
        id=candidate.id,
        name=full_name,
        avatar_url=candidate.avatar_url,
        competence_category=candidate.competence_category,
        linkedin=candidate.linkedin,
    )


def _recruiter_brief(user: Optional[User]) -> Optional[RecruiterBrief]:
    if user is None:
        return None
    # User model has `name` (or similar); guard against schema drift.
    name = getattr(user, "name", None) or getattr(user, "full_name", None) or user.email
    avatar = getattr(user, "avatar_url", None)
    return RecruiterBrief(id=user.id, name=name, email=user.email, avatar_url=avatar)


def _client_schema_for(user: User) -> type[ClientResponse] | type[ClientSafeResponse]:
    """Pełna projekcja (dane prawne + notatki) dla admin/HoR/DL/TAC (PR 1/7).

    Pozostałe role (recruiter/sourcer/viewer) dostają ``ClientSafeResponse``
    bez ``legal_name``/``nip``/``regon``/``notes`` — pola nie występują
    w odpowiedzi (nie są ``null``).
    """
    if user.has_any_role(*ADMIN_LIKE_ROLES, *CLIENT_TEAM_ROLES):
        return ClientResponse
    return ClientSafeResponse


def _effective_client_name():
    """Cienki alias na `client_identity.client_display_name_expression`.

    Reguła nazwy prezentowanej ma JEDNĄ definicję. Ten plik trzymał jej kopię
    dosłownie identyczną z `api/client_directory.py`, a `admin_clients_overview`
    nie miał jej wcale i pokazywał surowe `Client.name`.
    """
    return client_display_name_expression()


def _escaped_like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _serialize_client(
    client: Client,
    *,
    current_user: User,
    effective_name: Optional[str] = None,
) -> ClientResponse | ClientSafeResponse:
    schema = _client_schema_for(current_user)
    name = effective_name or client_display_name(client)
    return schema.model_validate(client).model_copy(update={"name": name})


def _merged_client_redirect(
    client: Client,
    *,
    suffix: str = "",
) -> Optional[RedirectResponse]:
    if client.merged_into_client_id is None:
        return None
    return RedirectResponse(
        url=f"/api/clients/{client.merged_into_client_id}{suffix}",
        # Merges are reversible by import run, so clients must not cache this
        # redirect permanently across a supported rollback.
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"X-Merged-From-Client-Id": str(client.id)},
    )


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


def _representative_order(contract: Contract):
    """Zamówienie reprezentujące kontrakt „na dziś".

    1 kontrakt = N zamówień/przedłużeń, a wiersz konsultanta jest per-KONTRAKT.
    Reguła lustrzana do FE ``splitOrders.activeOrder``: najnowsze ROZPOCZĘTE
    zamówienie (start_date ≤ dziś, nullowe traktowane jak rozpoczęte), a gdy
    wszystkie dopiero przyszłe — najbliższe nadchodzące. Anulowane pomijamy.
    Dzięki temu zaplanowane przedłużenie nie przejmuje wiersza przed startem.
    """
    orders = [
        o
        for o in (contract.client_orders or [])
        if o.status != ClientOrderStatus.cancelled
    ]
    if not orders:
        return None
    today = date.today()
    started = [o for o in orders if o.start_date is None or o.start_date <= today]
    if started:
        return max(started, key=lambda o: (o.start_date or date.min, o.id))
    return min(orders, key=lambda o: (o.start_date or date.max, o.id))


def _representative_project_part(contract: Contract) -> Optional[str]:
    """„Część umowy" e-Zdrowia dla wiersza konsultanta (ticket #3).

    Part żyje na ZAMÓWIENIU — edycja części na bieżącym zamówieniu natychmiast
    przestawia filtr Profilu.
    """
    order = _representative_order(contract)
    return order.project_part if order is not None else None


def _resolve_job(contract: Contract) -> tuple[Optional[int], Optional[str], bool]:
    """Rekrutacja pokazywana pod nazwiskiem konsultanta.

    Zwraca ``(job_id, job_title, from_order)``.

    ``Contract.job_id`` jest kanonicznym źródłem, ale **na produkcji jest pusty
    w całej bazie** (zmierzone 2026-08-14 na 10 klientach: zero trafień), więc
    kolumna nie pokazywałaby niczego u nikogo. Fallback bierze rekrutację
    z REPREZENTATYWNEGO zamówienia — tego samego, z którego liczy się „część
    umowy", więc obie informacje w wierszu opisują ten sam moment.

    ``from_order=True`` NIE jest kosmetyką: to inna proweniencja. `Contract.job_id`
    mówi „z tej rekrutacji wziął się ten placement", a `ClientOrder.job_id` —
    „z tej rekrutacji wzięło się bieżące zamówienie". Dla kontraktu przedłużanego
    to bywa inna rekrutacja niż pierwotna, więc UI musi móc to rozróżnić zamiast
    milcząco mieszać dwa znaczenia w jednej kolumnie.
    """
    if contract.job_id is not None:
        return (
            contract.job_id,
            contract.job.title if contract.job else None,
            False,
        )
    order = _representative_order(contract)
    if order is None or order.job_id is None:
        return None, None, False
    return order.job_id, order.job.title if order.job else None, True


@router.get("", response_model=ClientList)
async def list_clients(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = None,
):
    delivery_lead_client_ids = await resolve_delivery_lead_client_ids(
        current_user,
        db,
    )
    effective_name = _effective_client_name()
    query = (
        select(Client, effective_name.label("effective_name"))
        .where(*visible_client_predicates())
        .order_by(func.lower(effective_name).asc(), Client.id.asc())
    )
    query = apply_delivery_lead_client_scope(
        query,
        Client.id,
        delivery_lead_client_ids,
    )
    normalized_q = (q or "").strip()
    if normalized_q:
        pattern = _escaped_like_pattern(normalized_q)
        query = query.where(
            or_(
                effective_name.ilike(pattern, escape="\\"),
                Client.name.ilike(pattern, escape="\\"),
            )
        )
    total = (
        await db.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
    ).scalar_one()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return ClientList(
        items=[
            _serialize_client(
                client,
                current_user=current_user,
                effective_name=canonical_name,
            )
            for client, canonical_name in result.all()
        ],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    data: ClientCreate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    portfolio_category: PortfolioCategory = Query(PortfolioCategory.active),
):
    """Create a client and its initial local directory scope atomically.

    ``portfolio_category`` deliberately comes from the currently selected
    directory tab; direct API callers may make the same explicit choice.
    """

    client = Client(**data.model_dump())
    db.add(client)
    await db.flush()
    scope = ClientPortfolioScope(
        client_id=client.id,
        category=portfolio_category,
        source_system="manual",
    )
    db.add(scope)
    await db.flush()
    db.add(
        Activity(
            entity_type="client",
            entity_id=client.id,
            action="created",
            user_id=current_user.id,
            details={
                "portfolio_scope_id": scope.id,
                "portfolio_category": portfolio_category.value,
            },
        )
    )
    await db.flush()
    await db.refresh(client)
    return client


@router.get("/{client_id}", response_model=AnyClientResponse)
async def get_client(
    client_id: int, current_user: OperationalUser, db: AsyncSession = Depends(get_db)
):
    assert_delivery_lead_client_visible(
        client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    merged_redirect = _merged_client_redirect(client)
    if merged_redirect is not None:
        return merged_redirect
    if client.hidden or client.archived_at is not None:
        raise HTTPException(status_code=404, detail="Client not found")
    return _serialize_client(client, current_user=current_user)


@router.get("/{client_id}/profile", response_model=ClientProfileResponse)
async def get_client_profile(
    client_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Aggregated profile view — open jobs + active consultants + history.

    Powers the "Profil" tab in the client detail page. One endpoint replaces
    four round-trips from the frontend. MRR/LTV are computed from the
    Contract model's own `monthly_rate_client` / `monthly_margin` properties
    so the math stays consistent with the Contracts module.
    """
    assert_delivery_lead_client_visible(
        client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )
    # 404 early so we don't hand back empty sections for a phantom client.
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    merged_redirect = _merged_client_redirect(client, suffix="/profile")
    if merged_redirect is not None:
        return merged_redirect
    if client.hidden or client.archived_at is not None:
        raise HTTPException(status_code=404, detail="Client not found")

    today = date.today()

    # ── 1. Open jobs ──────────────────────────────────────────────────────
    # `published` jobs with a candidate-count subquery + recruiter join.
    candidate_count_sq = (
        select(
            CandidateStage.job_id,
            func.count(distinct(CandidateStage.candidate_id)).label("cnt"),
        )
        .group_by(CandidateStage.job_id)
        .subquery()
    )

    open_jobs_stmt = (
        select(Job, candidate_count_sq.c.cnt, User)
        .outerjoin(candidate_count_sq, candidate_count_sq.c.job_id == Job.id)
        .outerjoin(User, User.id == Job.recruiter_id)
        .where(Job.client_id == client_id, Job.status == JobStatus.published)
        .order_by(Job.created_at.desc())
    )
    open_rows = (await db.execute(open_jobs_stmt)).all()

    open_jobs: list[OpenJobItem] = []
    for job, cnt, recruiter_user in open_rows:
        created = job.created_at
        days_open = (datetime.now(timezone.utc) - created).days if created else 0
        open_jobs.append(
            OpenJobItem(
                id=job.id,
                title=job.title,
                seniority=job.seniority,
                priority=job.priority,
                days_open=max(0, days_open),
                candidate_count=int(cnt or 0),
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                recruiter=_recruiter_brief(recruiter_user),
                created_at=created,
            )
        )

    # ── 2. Active consultants ─────────────────────────────────────────────
    active_stmt = (
        select(Contract)
        .where(
            Contract.client_id == client_id,
            Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
        )
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.job),
            # Zamówienia + ich rekrutacje: „część umowy" e-Zdrowia (ticket #3)
            # ORAZ fallback kolumny „rekrutacja", gdy `Contract.job_id` jest
            # pusty. Bez `.selectinload(ClientOrder.job)` odczyt tytułu robi
            # lazy-load w async → MissingGreenlet 500 bez CORS.
            selectinload(Contract.client_orders).selectinload(ClientOrder.job),
            # Trzy harmonogramy stawek — WYMAGANE przez `_effective_rate_fields`.
            # Bez nich helper sięga po relację leniwie i w async leci
            # `MissingGreenlet` (500 bez nagłówków CORS, w UI „Nie udało się
            # wczytać profilu"). Ta sama pułapka pilnowana jest w 9 innych
            # miejscach serializujących kontrakt.
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .order_by(Contract.start_date.desc())
    )
    active_contracts = list((await db.execute(active_stmt)).scalars().all())

    # Stawki liczone z HARMONOGRAMÓW, nie z kolumn `contracts.rate_*`.
    # Kolumna niesie wartość zapisaną przy ostatnim zapisie kontraktu, więc
    # stawka progresywna albo aneks z datą, która już nadeszła, pokazywały tu
    # STARĄ kwotę — a wraz z nią złą marżę i zaniżone „Aktywne MRR". Ticket każe
    # te liczby wyeksponować w osobnych kolumnach; eksponowanie złej liczby jest
    # gorsze niż jej brak.
    active_rates = {c.id: _effective_rate_fields(c, today) for c in active_contracts}

    active_consultants: list[ActiveConsultantItem] = []
    for c in active_contracts:
        if c.candidate is None:
            continue
        rates = active_rates[c.id]
        job_id, job_title, job_from_order = _resolve_job(c)
        active_consultants.append(
            ActiveConsultantItem(
                contract_id=c.id,
                candidate=_candidate_brief(c.candidate),
                job_id=job_id,
                job_title=job_title,
                job_from_order=job_from_order,
                start_date=c.start_date,
                end_date=c.end_date,
                days_to_end=_days_to(c.end_date),
                monthly_rate_client=rates["monthly_rate_client"],
                monthly_rate_candidate=rates["monthly_rate_candidate"],
                monthly_margin=rates["monthly_margin"],
                currency=c.currency or "PLN",
                project_part=_representative_project_part(c),
            )
        )

    # ── 3. Historical placements (ended contracts) ────────────────────────
    ended_stmt = (
        select(Contract)
        .where(
            Contract.client_id == client_id,
            Contract.status == ContractStatus.ended,
        )
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.job),
            # Archiwum pokazuje tę samą kolumnę „rekrutacja" co „Obecni", więc
            # potrzebuje tego samego fallbacku na zamówienie.
            selectinload(Contract.client_orders).selectinload(ClientOrder.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .order_by(
            func.coalesce(Contract.terminated_at, Contract.end_date).desc().nullslast(),
            Contract.id.desc(),
        )
        .limit(100)
    )
    ended_contracts = list((await db.execute(ended_stmt)).scalars().all())

    # Archiwum to zapis HISTORYCZNY, więc stawka jest rozwiązywana na dzień
    # zakończenia, nie na dziś. Krok harmonogramu zaplanowany PO zakończeniu
    # projektu nigdy nie obowiązywał w jego trakcie i nie ma prawa pojawić się
    # w wierszu archiwalnym.
    ended_boundaries = {
        c.id: (c.terminated_at or c.end_date or today) for c in ended_contracts
    }
    ended_rates = {
        c.id: _effective_rate_fields(c, ended_boundaries[c.id]) for c in ended_contracts
    }

    placements: list[HistoricalPlacementItem] = []
    for c in ended_contracts:
        if c.candidate is None:
            continue
        end_boundary = ended_boundaries[c.id]
        rates = ended_rates[c.id]
        job_id, job_title, job_from_order = _resolve_job(c)
        duration = _duration_months(c.start_date, end_boundary)
        placements.append(
            HistoricalPlacementItem(
                contract_id=c.id,
                candidate=_candidate_brief(c.candidate),
                job_id=job_id,
                job_title=job_title,
                job_from_order=job_from_order,
                start_date=c.start_date,
                end_date=c.end_date,
                terminated_at=c.terminated_at,
                termination_reason=c.termination_reason,
                duration_months=duration,
                monthly_rate_client=rates["monthly_rate_client"],
                monthly_rate_candidate=rates["monthly_rate_candidate"],
                monthly_margin=rates["monthly_margin"],
                total_revenue=_contract_total_revenue(
                    c, end_boundary, rates["monthly_rate_client"]
                ),
            )
        )

    # ── 4. Lost jobs (closed without matching contract) ───────────────────
    placed_job_ids_stmt = select(distinct(Contract.job_id)).where(
        Contract.client_id == client_id, Contract.job_id.is_not(None)
    )
    placed_job_ids = {
        row for row in (await db.execute(placed_job_ids_stmt)).scalars().all() if row
    }

    lost_stmt = (
        select(Job, candidate_count_sq.c.cnt)
        .outerjoin(candidate_count_sq, candidate_count_sq.c.job_id == Job.id)
        .where(Job.client_id == client_id, Job.status == JobStatus.closed)
        .order_by(Job.closed_at.desc().nullslast(), Job.updated_at.desc())
        .limit(100)
    )
    lost_rows = (await db.execute(lost_stmt)).all()

    lost_jobs: list[LostJobItem] = []
    for job, cnt in lost_rows:
        if job.id in placed_job_ids:
            continue  # closed + placed = shown under placements, not lost
        lost_jobs.append(
            LostJobItem(
                job_id=job.id,
                title=job.title,
                closed_at=job.closed_at,
                close_reason=job.close_reason,
                close_notes=job.close_notes,
                candidate_count_reached=int(cnt or 0),
            )
        )

    # ── 5. Summary metrics ────────────────────────────────────────────────
    # Ten sam słownik stawek, z którego liczą się wiersze — inaczej kafel
    # „Aktywne MRR" byłby sumą innych liczb niż te widoczne pod nim, a
    # użytkownik nie miałby jak zgadnąć, która wersja jest prawdziwa.
    # `to_whole_pln` na SKŁADNIKACH, nie na wyniku: każdy wiersz jest
    # zaokrąglany osobno przez `WholePLN`, więc suma surowych `Decimal`-i
    # zaokrąglona raz na końcu potrafi różnić się od sumy kolumny o złotówkę
    # (zmierzone na prodzie: Alior 59 211 vs 59 212). Kafel ma być sumą tego,
    # co użytkownik WIDZI pod nim.
    active_mrr = sum(
        to_whole_pln(active_rates[c.id]["monthly_margin"] or 0)
        for c in active_contracts
    )

    # LTV = cumulative revenue so far. For active contracts use today as the
    # boundary so the number keeps ticking; for ended use the real end date.
    ltv = 0
    for c in active_contracts:
        rev = _contract_total_revenue(
            c, today, active_rates[c.id]["monthly_rate_client"]
        )
        if rev:
            ltv += rev
    for c in ended_contracts:
        rev = _contract_total_revenue(
            c, ended_boundaries[c.id], ended_rates[c.id]["monthly_rate_client"]
        )
        if rev:
            ltv += rev

    # avg_time_to_fill = mean (Contract.start_date - Job.created_at) for placed
    # jobs. Uses both active and ended contracts that have a job_id.
    fill_days: list[int] = []
    for c in list(active_contracts) + list(ended_contracts):
        if c.job is None or c.start_date is None or c.job.created_at is None:
            continue
        job_created = (
            c.job.created_at.date()
            if hasattr(c.job.created_at, "date")
            else c.job.created_at
        )
        delta = (c.start_date - job_created).days
        if delta >= 0:
            fill_days.append(delta)
    avg_ttf = (sum(fill_days) / len(fill_days)) if fill_days else None

    total_placements = len(active_consultants) + len(placements)

    summary = ClientProfileSummary(
        open_jobs=len(open_jobs),
        active_consultants=len(active_consultants),
        total_placements=total_placements,
        active_mrr=int(active_mrr),
        ltv=int(ltv),
        avg_time_to_fill_days=round(avg_ttf, 1) if avg_ttf is not None else None,
    )

    response = ClientProfileResponse(
        summary=summary,
        open_jobs=open_jobs,
        active_consultants=active_consultants,
        historical=ClientProfileHistory(placements=placements, lost_jobs=lost_jobs),
    )

    # R0 (plan 2026-07-16): stawki/marże/MRR/LTV tylko dla VIEW_FINANCE
    # (delivery_lead, admin). Pozostałe role widzą profil operacyjny.
    from app.analytics.capabilities import AnalyticsCapability, user_has_capability

    if not user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE):
        response.summary.active_mrr = None
        response.summary.ltv = None
        for job in response.open_jobs:
            job.salary_min = None
            job.salary_max = None
        for consultant in response.active_consultants:
            consultant.monthly_rate_client = None
            consultant.monthly_rate_candidate = None
            consultant.monthly_margin = None
        for placement in response.historical.placements:
            placement.total_revenue = None
            # Archiwum pokazuje ten sam komplet stawek co „Obecni konsultanci",
            # więc musi być redagowane tak samo — inaczej rola bez VIEW_FINANCE
            # zobaczyłaby w archiwum dokładnie te kwoty, które ukrywamy jej
            # w zakładce obok.
            placement.monthly_rate_client = None
            placement.monthly_rate_candidate = None
            placement.monthly_margin = None

    return response


@router.patch("/{client_id}", response_model=AnyClientResponse)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    assert_delivery_lead_client_visible(
        client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(client, k, v)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="updated",
            user_id=current_user.id,
            # Tylko NAZWY pól — wartości (np. notes) mogą być wrażliwe
            # i nie należą do dziennika audytu (PR 1/7).
            details={"fields": sorted(updates)},
        )
    )
    await db.flush()
    await db.refresh(client)
    # Serializacja jak w get_client — `name` = coalesce(display_name, name).
    # Surowy ORM zwracał tu client.name, więc odpowiedź PATCH po edycji
    # display_name pokazywała starą nazwę (wyglądało jak brak zapisu).
    return _serialize_client(client, current_user=current_user)


@router.post("/{client_id}/merge-into/{target_id}", response_model=AnyClientResponse)
async def merge_client_into(
    client_id: int,
    target_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Kanonizacja duplikatu: archiwizuje ``client_id`` i wskazuje na ``target_id``.

    Historia (joby, kontrakty, aktywności) ZOSTAJE na scalanym wierszu — merge
    nie przepisuje danych, tylko chowa duplikat z katalogu/lookupów
    (``merged_into_client_id IS NULL`` filtry) i przekierowuje detail 307-ką
    (``_merged_client_redirect``). Pierwszy klient tej ścieżki: e-Zdrowie
    37721 → 115 (Faza B); kolejni kandydaci: rodzina „BNP *".
    """
    if client_id == target_id:
        raise HTTPException(
            status_code=422, detail="Nie można scalić klienta z samym sobą"
        )
    source = await db.scalar(select(Client).where(Client.id == client_id))
    if source is None:
        raise HTTPException(status_code=404, detail="Client not found")
    target = await db.scalar(select(Client).where(Client.id == target_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Target client not found")
    if target.merged_into_client_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Cel scalenia sam jest scalony — wskaż klienta kanonicznego",
        )
    if target.hidden or target.archived_at is not None:
        raise HTTPException(
            status_code=409, detail="Cel scalenia jest ukryty/zarchiwizowany"
        )
    if source.merged_into_client_id is not None:
        if source.merged_into_client_id == target_id:
            # Idempotentny replay — już scalone dokładnie tak, jak proszono.
            return _serialize_client(source, current_user=current_user)
        raise HTTPException(
            status_code=409,
            detail=f"Klient jest już scalony z id={source.merged_into_client_id}",
        )

    source.merged_into_client_id = target_id
    # Wcześniej zarchiwizowane źródło to legalny kandydat do scalenia —
    # zachowujemy ORYGINALNY moment/autora archiwizacji (review #1054), merge
    # tylko dokłada wskazanie kanonicznego rekordu.
    source.archived_at = source.archived_at or datetime.now(timezone.utc)
    source.archived_by = source.archived_by or current_user.id
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="merged",
            user_id=current_user.id,
            details={"merged_into_client_id": target_id},
        )
    )
    await db.flush()
    await db.refresh(source)
    return _serialize_client(source, current_user=current_user)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int, current_user: AdminUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await db.delete(client)
