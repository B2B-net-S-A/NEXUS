"""„Twój ruch” — cały przepływ rekrutacji na pulpicie (04.10.2026).

Przegląd pulpitu z 04.10.2026: u rekruterów, TCM i Delivery Leadów panel
„Czeka na Ciebie” miał 0 zadań, bo pokazywał wyłącznie dalsze etapy (QC, Cpro,
prepy, follow-upy), a praca stała na początku procesu — w otwartych
rekrutacjach 1 079 osób w Ogłoszeniach i 23 w Nowych. Ten moduł liczy brakujące
sekcje przy odczycie, z NAJNOWSZEGO wiersza pary (kandydat, rekrutacja) — ta
sama reguła kolumn co Tablica (`cv_in_transit._place`):

* **Ogłoszenia** — jedna linia na rekrutację: ile osób czeka i od kiedy
  najstarsza. Rekrutacje, w których osoba jest Rekruterem (`job_team`); TCM
  dodatkowo widzi rekrutacje ze swojej kategorii (decyzja D5).
* **Nowi z blokadą** — aktywna blokada 12 h tej osoby.
* **Screening** i **Zweryfikowany** — pary, których rekruterem kandydata jest
  ta osoba (`interview_slots.default_recruiter_ids`), z brakami (arkusz,
  stawka) albo stanem QC CV.
* **Delivery Lead** — CV czekające na klienta ponad 7 dni, umowy B2B bez
  potwierdzonego podpisu, zamówienia z maila do weryfikacji.
* **Finanse** — braki zamówień, nowe PDF-y, zatrudnieni bez zamówienia,
  nieudane maile zamówień.

Każda grupa liczy się we własnym savepoincie: awaria jednej nie może zabrać
reszty ani dać 500 całego pulpitu. Poranny dzwonek (`board_tasks.digest_counts`)
tych sekcji nie liczy — Ogłoszenia są codzienną pracą, nie alarmem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, TypeVar

from sqlalchemy import and_, func, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competence_category import UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.order_gap import OrderGap
from app.models.order_mail import OrderMailDocument
from app.models.pipeline_template import PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services.access_scope import resolve_delivery_lead_client_ids
from app.services.action_permissions import ProductAction, has_permission
from app.services.board_tasks import _catalog, _Catalog, dl_portfolio_client_ids
from app.services.candidate_rate_from import effective_rate_sql
from app.services.cv_in_transit import _place
from app.services.interview_slots import default_recruiter_ids
from app.services.job_team import jobs_worked_by_clause
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

# Lista stoi nad pulpitem — dłuższa niż to przestaje być czytana.
MAX_ROWS = 20
WAITING_CLIENT_DAYS = 7
UNSIGNED_CONTRACT_DAYS = 2
HIRED_WINDOW_DAYS = 60
ORDER_MAIL_FAILED_DAYS = 14

SCREENING_COLUMN = "screening"
VERIFIED_COLUMN = "verified"
CV_SENT_COLUMN = "cv_sent"
_QC_DONE = frozenset({"passed", "overridden"})

MISSING_SHEET = "sheet"
MISSING_RATE = "rate"

T = TypeVar("T")


@dataclass(frozen=True)
class PostingRow:
    job_id: int
    job_title: str
    job_working_title: Optional[str]
    client_name: Optional[str]
    count: int
    oldest_at: datetime


@dataclass(frozen=True)
class PairRow:
    """Jedna osoba w jednej rekrutacji (Nowi, Screening, Zweryfikowany, DL)."""

    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str]
    client_name: Optional[str]
    since: datetime
    # Nowi: koniec blokady; Screening: braki; Zweryfikowany: stan QC CV.
    claimed_until: Optional[datetime] = None
    missing: tuple[str, ...] = ()
    qc_status: Optional[str] = None


@dataclass(frozen=True)
class ContractRow:
    id: int
    contract_number: str
    partner_name: Optional[str]
    client_name: Optional[str]
    created_at: datetime


@dataclass
class FlowBlock:
    postings: list[PostingRow] = field(default_factory=list)
    postings_total: int = 0
    claimed: list[PairRow] = field(default_factory=list)
    screening: list[PairRow] = field(default_factory=list)
    verified: list[PairRow] = field(default_factory=list)
    waiting_client: list[PairRow] = field(default_factory=list)
    unsigned_contracts: list[ContractRow] = field(default_factory=list)
    order_mail_review: int = 0
    # Czy osoba ma w ogóle sekcje przepływu (rekruter, TCM, DL) — front pokazuje
    # wtedy zdanie „Nic na Ciebie teraz nie czeka” zamiast ukrywać panel.
    applies: bool = False


@dataclass
class FinanceBlock:
    gaps_open: int = 0
    pdfs_new: int = 0
    order_mail_failed: int = 0
    hired_without_order: list[PairRow] = field(default_factory=list)
    hired_without_order_total: int = 0


# ── Najnowszy wiersz pary w wybranych rekrutacjach (bez okna czasu) ──────────

_LATEST_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.id, cs.candidate_id, cs.job_id, cs.stage, cs.stage_def_id,
               cs.moved_at
          FROM candidate_stages cs
         WHERE cs.job_id = ANY(:job_ids)
         ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    )
    SELECT l.id, l.candidate_id, l.job_id, l.stage, l.stage_def_id, l.moved_at,
           COALESCE(j.pipeline_template_id, :default_template_id) AS template_id,
           j.title, j.working_title, cl.name AS client_name,
           c.name AS cname, c.lastname AS clastname
      FROM latest l
      JOIN jobs j ON j.id = l.job_id
      JOIN candidates c ON c.id = l.candidate_id
      LEFT JOIN clients cl ON cl.id = j.client_id
    """
)


@dataclass(frozen=True)
class _Placed:
    row: Any
    column: Optional[str]
    posting: bool


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def _is_posting(catalog: _Catalog, row: Any) -> bool:
    """Ogłoszenia to etap kolumny „Nowi” — rozpoznajemy go po kodzie etapu."""

    if row.stage_def_id is None:
        return _value(row.stage) == "posting"
    effective = catalog.effective_def_id(row.template_id, row.stage_def_id)
    stage_def = catalog.defs.get(effective) if effective is not None else None
    if stage_def is None:
        return False
    return stage_def.legacy_enum_value == "posting"


async def _latest_rows(
    db: AsyncSession, catalog: _Catalog, job_ids: list[int]
) -> list[_Placed]:
    if not job_ids:
        return []
    default_template_id = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    rows = (
        await db.execute(
            _LATEST_SQL,
            {"job_ids": job_ids, "default_template_id": default_template_id},
        )
    ).all()
    out: list[_Placed] = []
    for row in rows:
        column, _badge = _place(catalog, row.template_id, row.stage_def_id, row.stage)
        out.append(_Placed(row=row, column=column, posting=_is_posting(catalog, row)))
    return out


def _name(first: Optional[str], last: Optional[str]) -> str:
    return " ".join(p for p in (first, last) if p) or "Kandydat"


def _pair_row(placed: _Placed, **extra: Any) -> PairRow:
    r = placed.row
    return PairRow(
        candidate_id=r.candidate_id,
        candidate_name=_name(r.cname, r.clastname),
        job_id=r.job_id,
        job_title=r.title,
        job_working_title=r.working_title,
        client_name=r.client_name,
        since=r.moved_at,
        **extra,
    )


# ── Zakresy rekrutacji ────────────────────────────────────────────────────────


def _in_work():
    return and_(Job.status == JobStatus.published, Job.work_state.in_(IN_WORK_STATES))


async def _recruiting_job_ids(db: AsyncSession, user: User) -> list[int]:
    """Rekrutacje w pracy, w których osoba jest Rekruterem; TCM + kategoria."""

    scope = jobs_worked_by_clause([user.id])
    if user.has_role(UserRole.talent_community_manager):
        my_categories = select(UserCompetenceCategory.competence_category_id).where(
            UserCompetenceCategory.user_id == user.id
        )
        scope = or_(scope, Job.competence_category_id.in_(my_categories))
    return list(
        (
            await db.scalars(select(Job.id).where(_in_work(), scope).order_by(Job.id))
        ).all()
    )


async def _dl_job_ids(
    db: AsyncSession, user: User, portfolio: frozenset[int]
) -> list[int]:
    """Opublikowane rekrutacje DL-a: jego z nazwy albo bez DL-a u jego klienta.

    Ta sama reguła co przegląd w „Czeka na Ciebie” (`_sees_dl_review`).
    """

    scope = Job.delivery_lead_id == user.id
    if portfolio:
        scope = or_(
            scope,
            and_(Job.delivery_lead_id.is_(None), Job.client_id.in_(sorted(portfolio))),
        )
    return list(
        (
            await db.scalars(
                select(Job.id).where(Job.status == JobStatus.published, scope)
            )
        ).all()
    )


# ── Sekcje ────────────────────────────────────────────────────────────────────


def _postings(placed: list[_Placed]) -> tuple[list[PostingRow], int]:
    by_job: dict[int, list[_Placed]] = {}
    for p in placed:
        if p.posting:
            by_job.setdefault(p.row.job_id, []).append(p)
    rows = []
    for items in by_job.values():
        first = items[0].row
        rows.append(
            PostingRow(
                job_id=first.job_id,
                job_title=first.title,
                job_working_title=first.working_title,
                client_name=first.client_name,
                count=len(items),
                oldest_at=min(i.row.moved_at for i in items),
            )
        )
    # Najstarsze zgłoszenia na górze — to one czekają najdłużej.
    rows.sort(key=lambda r: (r.oldest_at, -r.count))
    return rows[:MAX_ROWS], sum(r.count for r in rows)


async def _claimed(db: AsyncSession, user: User, now: datetime) -> list[PairRow]:
    rows = (
        await db.execute(
            select(
                RecruitmentProcess.candidate_id,
                RecruitmentProcess.job_id,
                RecruitmentProcess.claimed_until,
                Candidate.name,
                Candidate.lastname,
                Job.title,
                Job.working_title,
                Client.name,
            )
            .join(Candidate, Candidate.id == RecruitmentProcess.candidate_id)
            .join(Job, Job.id == RecruitmentProcess.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(
                RecruitmentProcess.claimed_by_user_id == user.id,
                RecruitmentProcess.claimed_until > now,
                RecruitmentProcess.status == ProcessStatus.open,
                Job.status == JobStatus.published,
            )
            .order_by(RecruitmentProcess.claimed_until)
            .limit(MAX_ROWS)
        )
    ).all()
    return [
        PairRow(
            candidate_id=cid,
            candidate_name=_name(first, last),
            job_id=jid,
            job_title=title,
            job_working_title=working,
            client_name=client,
            since=until,
            claimed_until=until,
        )
        for cid, jid, until, first, last, title, working, client in rows
    ]


async def _mine(
    db: AsyncSession, user: User, placed: list[_Placed], column: str
) -> list[_Placed]:
    """Pary w kolumnie, których rekruterem kandydata jest ta osoba."""

    in_column = [p for p in placed if p.column == column]
    if not in_column:
        return []
    owners = await default_recruiter_ids(
        db, [(p.row.candidate_id, p.row.job_id) for p in in_column]
    )
    return [
        p
        for p in in_column
        if owners.get((p.row.candidate_id, p.row.job_id)) == user.id
    ]


async def _screening(db: AsyncSession, mine: list[_Placed]) -> list[PairRow]:
    if not mine:
        return []
    from app.services import recommendation_cards  # noqa: PLC0415
    from app.services.move_requirements import sheet_filled  # noqa: PLC0415

    pairs = [(p.row.candidate_id, p.row.job_id) for p in mine]
    pair_key = tuple_(CandidateStage.candidate_id, CandidateStage.job_id)
    sheets: set[tuple[int, int]] = set()
    stage_rates: set[tuple[int, int]] = set()
    for cid, jid, answers, rate in (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.screening_answers,
                CandidateStage.expected_rate_value,
            ).where(pair_key.in_(pairs))
        )
    ).all():
        if sheet_filled(answers):
            sheets.add((cid, jid))
        if rate is not None:
            stage_rates.add((cid, jid))
    cards = await recommendation_cards.summaries_for_pairs(db, pairs)
    profile_rates = set(
        (
            await db.scalars(
                select(Candidate.id).where(
                    Candidate.id.in_({cid for cid, _ in pairs}),
                    effective_rate_sql(Candidate).is_not(None),
                )
            )
        ).all()
    )
    out = []
    for p in mine:
        key = (p.row.candidate_id, p.row.job_id)
        missing: list[str] = []
        card = cards.get(key) or {}
        if key not in sheets and not int(card.get("answers") or 0):
            missing.append(MISSING_SHEET)
        if key not in stage_rates and p.row.candidate_id not in profile_rates:
            missing.append(MISSING_RATE)
        out.append(_pair_row(p, missing=tuple(missing)))
    out.sort(key=lambda r: r.since)
    return out[:MAX_ROWS]


async def _verified(db: AsyncSession, mine: list[_Placed]) -> list[PairRow]:
    if not mine:
        return []
    from app.services.move_requirements import qc_statuses  # noqa: PLC0415

    statuses = await qc_statuses(db, [(p.row.candidate_id, p.row.job_id) for p in mine])
    out = [
        _pair_row(
            p,
            qc_status=str(
                (statuses.get((p.row.candidate_id, p.row.job_id)) or {}).get("status")
                or "unchecked"
            ),
        )
        for p in mine
    ]
    out.sort(key=lambda r: r.since)
    return out[:MAX_ROWS]


def _waiting_client(placed: list[_Placed], now: datetime) -> list[PairRow]:
    limit = now - timedelta(days=WAITING_CLIENT_DAYS)
    rows = [
        _pair_row(p)
        for p in placed
        if p.column == CV_SENT_COLUMN and p.row.moved_at < limit
    ]
    rows.sort(key=lambda r: r.since)
    return rows[:MAX_ROWS]


async def _unsigned_contracts(
    db: AsyncSession, user: User, portfolio: frozenset[int], now: datetime
) -> list[ContractRow]:
    scope = B2BGeneratedContract.created_by == user.id
    if portfolio:
        scope = or_(scope, B2BGeneratedContract.client_id.in_(sorted(portfolio)))
    rows = (
        await db.scalars(
            select(B2BGeneratedContract)
            .where(
                # Wiersze z Excela działu są tylko do odczytu, a import zapisuje
                # każdy bez daty podpisu jako „w trakcie” — DL nie miałby jak ich zdjąć.
                B2BGeneratedContract.source == "generator",
                B2BGeneratedContract.signature_status == "unsigned",
                B2BGeneratedContract.contract_status == "in_progress",
                B2BGeneratedContract.created_at
                < now - timedelta(days=UNSIGNED_CONTRACT_DAYS),
                scope,
            )
            .order_by(B2BGeneratedContract.created_at)
            .limit(MAX_ROWS)
        )
    ).all()
    return [
        ContractRow(
            id=row.id,
            contract_number=row.contract_number,
            partner_name=row.partner_name,
            client_name=row.client_name,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _order_mail_count(
    db: AsyncSession, user: User, outcome: str, *, since: Optional[datetime] = None
) -> int:
    query = select(func.count(OrderMailDocument.id)).where(
        OrderMailDocument.outcome == outcome
    )
    if since is not None:
        query = query.where(OrderMailDocument.created_at >= since)
    visible = await resolve_delivery_lead_client_ids(user, db)
    if visible is not None:
        if not visible:
            return 0
        query = query.where(OrderMailDocument.client_id.in_(sorted(visible)))
    return int(await db.scalar(query) or 0)


async def _gaps_open(db: AsyncSession) -> int:
    from app.services.order_gaps import gap_orders_with_ending_intent  # noqa: PLC0415

    order_ids = list(
        (
            await db.scalars(select(OrderGap.order_id).where(OrderGap.status == "open"))
        ).all()
    )
    if not order_ids:
        return 0
    ending = await gap_orders_with_ending_intent(db, order_ids)
    return sum(1 for order_id in order_ids if order_id not in ending)


async def _pdfs_new(db: AsyncSession, user: User, today: date) -> int:
    from app.services import finance_order_pdfs as pdfs  # noqa: PLC0415

    entries = await pdfs.collect_entries(
        db, window=pdfs.month_bounds(today.year, today.month)
    )
    downloaded = await pdfs.downloads_for_user(db, user.id, entries)
    return sum(1 for e in entries if (e.kind, e.id) not in downloaded)


_HIRED_SQL = text(
    """
    SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
           cs.candidate_id, cs.job_id, cs.moved_at,
           j.title, j.working_title, cl.name AS client_name,
           c.name AS cname, c.lastname AS clastname
      FROM candidate_stages cs
      JOIN jobs j ON j.id = cs.job_id
      JOIN candidates c ON c.id = cs.candidate_id
      LEFT JOIN clients cl ON cl.id = j.client_id
     WHERE cs.stage = 'hired'
       AND cs.moved_at >= :since
     ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    """
)


async def _hired_without_order(
    db: AsyncSession, now: datetime
) -> tuple[list[PairRow], int]:
    from app.services.hired_order_status import order_status_for_pairs  # noqa: PLC0415

    rows = (
        await db.execute(_HIRED_SQL, {"since": now - timedelta(days=HIRED_WINDOW_DAYS)})
    ).all()
    if not rows:
        return [], 0
    statuses = await order_status_for_pairs(
        db, [(r.candidate_id, r.job_id) for r in rows]
    )
    missing = [
        PairRow(
            candidate_id=r.candidate_id,
            candidate_name=_name(r.cname, r.clastname),
            job_id=r.job_id,
            job_title=r.title,
            job_working_title=r.working_title,
            client_name=r.client_name,
            since=r.moved_at,
        )
        for r in rows
        if statuses.get((r.candidate_id, r.job_id)) == "missing"
    ]
    missing.sort(key=lambda r: r.since)
    return missing[:MAX_ROWS], len(missing)


# ── Składanie ─────────────────────────────────────────────────────────────────


async def _safe(
    db: AsyncSession, label: str, load: Callable[[], Awaitable[T]], default: T
) -> T:
    try:
        async with db.begin_nested():
            return await load()
    except Exception:  # noqa: BLE001
        logger.exception("board_flow: nie udało się policzyć sekcji %s", label)
        return default


def _recruits(user: User) -> bool:
    return user.has_any_role(UserRole.recruiter, UserRole.talent_community_manager)


async def load_flow(
    db: AsyncSession, user: User, *, now: Optional[datetime] = None
) -> Optional[FlowBlock]:
    """Sekcje przepływu dla rekrutera, TCM i Delivery Leada (inni: ``None``)."""

    now = now or datetime.now(timezone.utc)
    recruits = _recruits(user)
    leads = user.has_role(UserRole.delivery_lead)
    if not (recruits or leads):
        return None
    block = FlowBlock(applies=True)
    catalog = await _safe(db, "katalog etapów", lambda: _catalog(db), None)
    if catalog is None:
        return block

    if recruits:

        async def recruiting() -> None:
            job_ids = await _recruiting_job_ids(db, user)
            placed = await _latest_rows(db, catalog, job_ids)
            block.postings, block.postings_total = _postings(placed)
            block.screening = await _screening(
                db, await _mine(db, user, placed, SCREENING_COLUMN)
            )
            block.verified = await _verified(
                db, await _mine(db, user, placed, VERIFIED_COLUMN)
            )

        await _safe(db, "rekrutacje rekrutera", recruiting, None)
        block.claimed = await _safe(db, "blokady", lambda: _claimed(db, user, now), [])

    if leads:
        portfolio = await _safe(
            db,
            "portfel DL",
            lambda: dl_portfolio_client_ids(db, user.id),
            frozenset(),
        )

        async def waiting() -> list[PairRow]:
            placed = await _latest_rows(
                db, catalog, await _dl_job_ids(db, user, portfolio)
            )
            return _waiting_client(placed, now)

        block.waiting_client = await _safe(db, "czeka na klienta", waiting, [])
        block.unsigned_contracts = await _safe(
            db,
            "umowy do podpisu",
            lambda: _unsigned_contracts(db, user, portfolio, now),
            [],
        )
        block.order_mail_review = await _safe(
            db,
            "zamówienia z maila",
            lambda: _order_mail_count(db, user, "needs_review"),
            0,
        )
    return block


async def load_finance(
    db: AsyncSession, user: User, *, now: Optional[datetime] = None
) -> Optional[FinanceBlock]:
    """Zadania Finansów — rola Finanse z uprawnieniem „Moduł Finanse”.

    Admin ma to uprawnienie domyślnie, ale tej pracy nie wykonuje; jego pulpit
    pokazuje stan systemu.
    """

    if not user.has_role(UserRole.finance):
        return None
    if not has_permission(user, ProductAction.finance_module):
        return None
    now = now or datetime.now(timezone.utc)
    block = FinanceBlock()
    block.gaps_open = await _safe(db, "braki zamówień", lambda: _gaps_open(db), 0)
    block.pdfs_new = await _safe(
        db, "nowe PDF-y", lambda: _pdfs_new(db, user, business_today()), 0
    )
    block.order_mail_failed = await _safe(
        db,
        "nieudane maile zamówień",
        lambda: _order_mail_count(
            db, user, "failed", since=now - timedelta(days=ORDER_MAIL_FAILED_DAYS)
        ),
        0,
    )
    hired, total = await _safe(
        db, "zatrudnieni bez zamówienia", lambda: _hired_without_order(db, now), ([], 0)
    )
    block.hired_without_order = hired
    block.hired_without_order_total = total
    return block


__all__ = [
    "ContractRow",
    "FinanceBlock",
    "FlowBlock",
    "MISSING_RATE",
    "MISSING_SHEET",
    "PairRow",
    "PostingRow",
    "load_finance",
    "load_flow",
]
