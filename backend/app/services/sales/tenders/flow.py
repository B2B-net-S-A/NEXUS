"""Bieg przetargów: pobranie z BZP i TED, bramka, szanse, odsiane, zamykanie.

Wariant B (decyzja Artura 24.11.2026): ogłoszenie, które przeszło reguły, od razu
staje się szansą w lejku Przetargi na etapie „Identyfikacja” — bez „Bierzemy”.
Opiekun z reguł („Opiekun nowych szans”), termin składania ofert jako data
zamknięcia, teczka ogłoszenia jako pierwsza notatka. Odsiane leży z regułą na
ekranie i da się je przywrócić. Szansa od bramki, która stoi w „Identyfikacji”
po terminie, zamyka się sama z powodem „Termin minął”; szans założonych ręcznie
(i 42 starych kart z Atlasa) automat nie rusza.

Stan biegów (kursory, ostatni bieg) leży w ``app_settings`` pod ``STATE_KEY``.
Sieć idzie poza transakcją; przetwarzanie trzyma blokadę doradczą, więc bieg
ręczny i bieg z pętli nie założą dwóch szans z jednego ogłoszenia. Logi: same
liczby (repo i logi są publiczne).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, local_now
from app.models.app_setting import AppSetting
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
    SalesTenderNotice,
)
from app.services.company_names import normalize_company_name
from app.services.sales import history
from app.services.sales.handoff_hosts import sales_editors
from app.services.sales.lifecycle import apply_stage
from app.services.sales.tenders import rules, sources
from app.services.sales.tenders.rules import Notice, TenderRules

logger = logging.getLogger(__name__)

TENDER_PIPELINE_KEY = "atlas-tenders"
ENTRY_STAGE_KEY = "tender-identified"
LOST_STAGE_KEY = "tender-lost"
EXTERNAL_PREFIX = "tender:"
EXPIRED_REASON = "Termin minął"
OPPORTUNITY_SOURCE = "tender"
STATE_KEY = "sales_tenders_state"
#: Pierwszy bieg sięga tydzień wstecz, żeby lista nie startowała pusta.
INITIAL_DAYS = 7
#: Bieg „w toku” starszy niż godzina to bieg przerwany (restart kontenera).
RUNNING_STALE_AFTER = timedelta(hours=1)
_LOCK_KEY = 7682411

SOURCE_LABELS = {"bzp": "BZP", "ted": "TED"}
PIPELINE_MISSING = "Brak lejka „Przetargi” w Sprzedaży."
RUN_FAILED = "Bieg przerwał nieoczekiwany błąd. Szczegóły są w logu serwera."
SOURCE_FAILED = "Rejestr {name} nie odpowiedział."


class TendersNotReady(RuntimeError):
    """Brak lejka albo etapów, na których bramka zakłada szanse."""


@dataclass
class RunCounts:
    bzp: int = 0
    ted: int = 0
    it: int = 0
    created: int = 0
    rejected: int = 0
    skipped: int = 0
    closed: int = 0


@dataclass
class RunResult:
    status: str
    counts: RunCounts = field(default_factory=RunCounts)
    errors: list[str] = field(default_factory=list)


def external_ref(source: str, number: str) -> str:
    return f"{EXTERNAL_PREFIX}{source}:{number}"[:80]


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.astimezone(timezone.utc).isoformat() if moment else None


def _parse_iso(value: Any) -> Optional[datetime]:
    return sources.parse_instant(value)


def _parse_day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


async def load_state(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(AppSetting, STATE_KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


async def _save_state(db: AsyncSession, state: dict[str, Any]) -> None:
    row = await db.get(AppSetting, STATE_KEY, with_for_update=True)
    if row is None:
        db.add(AppSetting(key=STATE_KEY, value=state))
    else:
        row.value = state


async def tender_pipeline(
    db: AsyncSession,
) -> tuple[SalesPipeline, list[SalesPipelineStage]]:
    pipeline = (
        await db.execute(
            select(SalesPipeline).where(
                SalesPipeline.key == TENDER_PIPELINE_KEY,
                SalesPipeline.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if pipeline is None:
        raise TendersNotReady(PIPELINE_MISSING)
    stages = list(
        (
            await db.execute(
                select(SalesPipelineStage)
                .where(SalesPipelineStage.pipeline_id == pipeline.id)
                .order_by(SalesPipelineStage.position)
            )
        ).scalars()
    )
    if not any(stage.outcome == "open" for stage in stages):
        raise TendersNotReady(PIPELINE_MISSING)
    return pipeline, stages


def _entry_stage(stages: list[SalesPipelineStage]) -> SalesPipelineStage:
    return next(
        (stage for stage in stages if stage.key == ENTRY_STAGE_KEY),
        next(stage for stage in stages if stage.outcome == "open"),
    )


def _lost_stage(stages: list[SalesPipelineStage]) -> Optional[SalesPipelineStage]:
    return next(
        (stage for stage in stages if stage.key == LOST_STAGE_KEY),
        next((stage for stage in stages if stage.outcome == "lost"), None),
    )


async def _company(
    db: AsyncSession, notice: Notice, *, user_id: Optional[int]
) -> SalesCompany:
    """Karta zamawiającego: po NIP, potem po nazwie kanonicznej, inaczej nowa."""

    active = SalesCompany.archived_at.is_(None)
    if notice.buyer_nip:
        found = (
            await db.execute(
                select(SalesCompany)
                .where(
                    active,
                    func.regexp_replace(
                        func.coalesce(SalesCompany.nip, ""), r"\D", "", "g"
                    )
                    == notice.buyer_nip,
                )
                .order_by(SalesCompany.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if found is not None:
            return found
    normalized = normalize_company_name(notice.buyer_name) or rules.fold(
        notice.buyer_name
    )
    found = (
        await db.execute(
            select(SalesCompany)
            .where(active, SalesCompany.normalized_name == normalized)
            .order_by(SalesCompany.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if found is not None:
        return found
    company = SalesCompany(
        name=notice.buyer_name,
        normalized_name=normalized,
        nip=notice.buyer_nip,
        hq_city=(notice.buyer_city or None),
        hq_country="PL",
        source=OPPORTUNITY_SOURCE,
        created_by_user_id=user_id,
    )
    db.add(company)
    await db.flush()
    return company


def dossier(notice: Notice, match: Optional[str]) -> dict[str, Any]:
    """Teczka ogłoszenia w ``custom_fields["tender"]`` szansy."""

    return {
        "source": notice.source,
        "number": notice.number,
        "url": notice.url,
        "deadline_date": notice.deadline_date.isoformat()
        if notice.deadline_date
        else None,
        "deadline_at": _iso(notice.deadline_at),
        "published_at": _iso(notice.published_at),
        "cpv": notice.cpv_label,
        "below_eu": notice.below_eu,
        "match": match,
    }


def _note_body(notice: Notice, match: Optional[str]) -> str:
    deadline = "brak w ogłoszeniu"
    if notice.deadline_at is not None:
        local = notice.deadline_at.astimezone(ZoneInfo(DEFAULT_TZ))
        deadline = local.strftime("%d.%m.%Y, %H:%M")
    elif notice.deadline_date is not None:
        deadline = notice.deadline_date.strftime("%d.%m.%Y")
    lines = [
        f"Ogłoszenie {SOURCE_LABELS.get(notice.source, notice.source)} {notice.number}",
        f"Termin składania ofert: {deadline}",
        f"Zamawiający: {notice.buyer_name}"
        + (f", {notice.buyer_city}" if notice.buyer_city else "")
        + (f" (NIP {notice.buyer_nip})" if notice.buyer_nip else ""),
    ]
    if notice.cpv_label:
        lines.append(f"CPV: {notice.cpv_label}")
    if notice.below_eu is not None:
        lines.append("Poniżej progów UE" if notice.below_eu else "Powyżej progów UE")
    if match:
        lines.append(f"Bramka: {match}")
    if notice.url:
        lines.append(notice.url)
    return "\n".join(lines)


async def create_opportunity(
    db: AsyncSession,
    notice: Notice,
    *,
    match: Optional[str],
    owner_user_id: Optional[int],
    actor_user_id: Optional[int],
    now: datetime,
) -> SalesOpportunity:
    """Szansa w lejku Przetargi z ogłoszenia; ta sama ścieżka co założenie ręczne."""

    ref = external_ref(notice.source, notice.number)
    existing = (
        await db.execute(
            select(SalesOpportunity).where(SalesOpportunity.external_ref == ref)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    pipeline, stages = await tender_pipeline(db)
    entry = _entry_stage(stages)
    company = await _company(db, notice, user_id=actor_user_id)
    opportunity = SalesOpportunity(
        company_id=company.id,
        pipeline_id=pipeline.id,
        stage_id=entry.id,
        title=notice.title[:255],
        owner_user_id=owner_user_id,
        created_by_user_id=actor_user_id,
        source=OPPORTUNITY_SOURCE,
        external_ref=ref,
        expected_close_date=notice.deadline_date,
        custom_fields={"tender": dossier(notice, match)},
    )
    apply_stage(opportunity, entry, stages, now=now)
    db.add(opportunity)
    await db.flush()
    history.record_created(db, opportunity, user_id=actor_user_id)
    db.add(
        SalesActivity(
            kind="note",
            company_id=company.id,
            opportunity_id=opportunity.id,
            subject=f"Przetarg {SOURCE_LABELS.get(notice.source, notice.source)} {notice.number}"[
                :500
            ],
            body=_note_body(notice, match),
            occurred_at=now,
            created_by_user_id=actor_user_id,
            external_source="tender",
            external_ref=f"tender-note:{notice.source}:{notice.number}"[:80],
            web_link=(notice.url or None),
        )
    )
    return opportunity


async def _owner(db: AsyncSession, owner_user_id: Optional[int]) -> Optional[int]:
    """Opiekun z reguł, o ile dalej jest aktywnym kontem z „Sprzedaż: edycja”."""

    if owner_user_id is None:
        return None
    editors = {user.id for user in await sales_editors(db)}
    if owner_user_id in editors:
        return owner_user_id
    logger.warning("sales_tenders owner not a sales editor, creating without owner")
    return None


def notice_row(notice: Notice, decision: rules.Decision) -> SalesTenderNotice:
    return SalesTenderNotice(
        source=notice.source,
        number=notice.number,
        title=notice.title,
        buyer_name=notice.buyer_name,
        buyer_nip=notice.buyer_nip,
        buyer_city=(notice.buyer_city[:120] if notice.buyer_city else None),
        cpv=notice.cpv_label,
        order_type=notice.order_type,
        url=notice.url,
        published_at=notice.published_at,
        deadline_date=notice.deadline_date,
        deadline_at=notice.deadline_at,
        below_eu=notice.below_eu,
        status="created" if decision.passed else "rejected",
        rule=decision.rule,
        rule_detail=(decision.detail[:200] if decision.detail else None),
        match_detail=decision.match[:200],
    )


def row_notice(row: SalesTenderNotice) -> Notice:
    return Notice(
        source=row.source,
        number=row.number,
        title=row.title,
        buyer_name=row.buyer_name,
        published_at=row.published_at,
        buyer_nip=row.buyer_nip,
        buyer_city=row.buyer_city,
        cpv_codes=(),
        cpv_label=row.cpv,
        order_type=row.order_type,
        url=row.url,
        deadline_date=row.deadline_date,
        deadline_at=row.deadline_at,
        below_eu=row.below_eu,
    )


async def process(
    db: AsyncSession,
    notices: list[Notice],
    tender_rules: TenderRules,
    *,
    now: datetime,
    today: date,
    counts: RunCounts,
) -> None:
    """Bramka i zapis; wywołujący trzyma blokadę i robi commit."""

    decided: list[tuple[Notice, rules.Decision]] = []
    for notice in notices:
        decision = rules.evaluate(notice, tender_rules, today=today, now=now)
        if decision is not None:
            decided.append((notice, decision))
    counts.it = len(decided)
    if not decided:
        return
    known = {
        (source, number)
        for source, number in (
            await db.execute(
                select(SalesTenderNotice.source, SalesTenderNotice.number).where(
                    SalesTenderNotice.number.in_(sorted({n.number for n, _ in decided}))
                )
            )
        ).all()
    }
    owner = await _owner(db, tender_rules.owner_user_id)
    for notice, decision in decided:
        key = (notice.source, notice.number)
        if key in known:
            counts.skipped += 1
            continue
        known.add(key)
        row = notice_row(notice, decision)
        if decision.passed:
            opportunity = await create_opportunity(
                db,
                notice,
                match=decision.match,
                owner_user_id=owner,
                actor_user_id=None,
                now=now,
            )
            row.opportunity_id = opportunity.id
            counts.created += 1
        else:
            counts.rejected += 1
        db.add(row)


async def close_expired(db: AsyncSession, *, today: date, now: datetime) -> int:
    """Szanse od bramki w „Identyfikacji” po terminie → przegrana „Termin minął”."""

    try:
        pipeline, stages = await tender_pipeline(db)
    except TendersNotReady:
        return 0
    entry = _entry_stage(stages)
    lost = _lost_stage(stages)
    if lost is None:
        return 0
    rows = list(
        (
            await db.execute(
                select(SalesOpportunity)
                .where(
                    SalesOpportunity.pipeline_id == pipeline.id,
                    SalesOpportunity.stage_id == entry.id,
                    SalesOpportunity.status == "open",
                    SalesOpportunity.archived_at.is_(None),
                    SalesOpportunity.external_ref.like(f"{EXTERNAL_PREFIX}%"),
                    SalesOpportunity.expected_close_date < today,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for opportunity in rows:
        before = history.snapshot(opportunity)
        apply_stage(opportunity, lost, stages, now=now)
        opportunity.lost_reason = EXPIRED_REASON
        history.record_changes(db, opportunity, before, user_id=None)
    return len(rows)


def last_run_view(state: dict[str, Any], *, now: datetime) -> Optional[dict[str, Any]]:
    """Ostatni bieg do ekranu; „w toku” starszy niż godzina to bieg przerwany."""

    run = state.get("last_run")
    if not isinstance(run, dict):
        return None
    view = dict(run)
    started = _parse_iso(view.get("started_at"))
    if view.get("status") == "running" and (
        started is None or now - started > RUNNING_STALE_AFTER
    ):
        view["status"] = "failed"
        view["error"] = "Bieg został przerwany (restart serwera). Następny ruszy sam."
    return view


async def _mark_running(trigger: str, started: datetime) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        state = await load_state(db)
        state["last_run"] = {
            "status": "running",
            "trigger": trigger,
            "started_at": _iso(started),
        }
        await _save_state(db, state)
        await db.commit()
        return state


async def _finish(
    result: RunResult,
    *,
    trigger: str,
    started: datetime,
    bzp_cursor: Optional[datetime],
    ted_day: Optional[date],
) -> None:
    async with AsyncSessionLocal() as db:
        current = await load_state(db)
        if bzp_cursor is not None:
            current["bzp_cursor"] = _iso(bzp_cursor)
        if ted_day is not None:
            current["ted_day"] = ted_day.isoformat()
        current["last_run"] = {
            "status": result.status,
            "trigger": trigger,
            "started_at": _iso(started),
            "finished_at": _iso(datetime.now(timezone.utc)),
            "error": " ".join(result.errors) or None,
            "counts": asdict(result.counts),
        }
        await _save_state(db, current)
        await db.commit()


async def run(*, trigger: str) -> RunResult:
    """Jeden bieg: pobranie, bramka, zamknięcie po terminie, zapis stanu."""

    started = datetime.now(timezone.utc)
    state = await _mark_running(trigger, started)
    now_local = local_now()
    today = now_local.date()
    result = RunResult(status="ok")
    async with AsyncSessionLocal() as db:
        tender_rules = await rules.load(db)

    bzp_since = sources.bzp_since(
        _parse_iso(state.get("bzp_cursor")), now=started, initial_days=INITIAL_DAYS
    )
    ted_since = sources.ted_since(
        _parse_day(state.get("ted_day")), today=today, initial_days=INITIAL_DAYS
    )
    notices: list[Notice] = []
    bzp_cursor: Optional[datetime] = None
    ted_day: Optional[date] = None
    async with httpx.AsyncClient() as client:
        try:
            batch = await sources.fetch_bzp(client, since=bzp_since, until=today)
            notices.extend(batch.notices)
            result.counts.bzp = len(batch.notices)
            bzp_cursor = batch.cursor
        except sources.SourceError as exc:
            logger.warning("sales_tenders bzp failed: %s", exc)
            result.errors.append(SOURCE_FAILED.format(name="BZP"))
        try:
            ted = await sources.fetch_ted(client, since=ted_since, until=today)
            notices.extend(ted)
            result.counts.ted = len(ted)
            ted_day = today
        except sources.SourceError as exc:
            logger.warning("sales_tenders ted failed: %s", exc)
            result.errors.append(SOURCE_FAILED.format(name="TED"))

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY}
            )
            await process(
                db,
                notices,
                tender_rules,
                now=started,
                today=today,
                counts=result.counts,
            )
            result.counts.closed = await close_expired(db, today=today, now=started)
            await db.commit()
    except TendersNotReady as exc:
        result.errors.append(str(exc))
        result.counts = RunCounts(bzp=result.counts.bzp, ted=result.counts.ted)
        bzp_cursor, ted_day = None, None
    except Exception:  # noqa: BLE001 — bieg ma zostawić ślad na ekranie
        logger.exception("sales_tenders processing failed")
        result.errors.append(RUN_FAILED)
        result.counts = RunCounts(bzp=result.counts.bzp, ted=result.counts.ted)
        bzp_cursor, ted_day = None, None
    if result.errors:
        result.status = "failed"
    await _finish(
        result,
        trigger=trigger,
        started=started,
        bzp_cursor=bzp_cursor,
        ted_day=ted_day,
    )
    counts = result.counts
    logger.info(
        "sales_tenders run trigger=%s status=%s bzp=%d ted=%d it=%d created=%d "
        "rejected=%d skipped=%d closed=%d",
        trigger,
        result.status,
        counts.bzp,
        counts.ted,
        counts.it,
        counts.created,
        counts.rejected,
        counts.skipped,
        counts.closed,
    )
    return result


async def restore(
    db: AsyncSession, row: SalesTenderNotice, *, user_id: int, now: datetime
) -> SalesOpportunity:
    """„Przywróć” odsiane: szansa u osoby, która przywróciła; commit robi wywołujący."""

    notice = row_notice(row)
    opportunity = await create_opportunity(
        db,
        notice,
        match=row.match_detail,
        owner_user_id=user_id,
        actor_user_id=user_id,
        now=now,
    )
    row.status = "created"
    row.opportunity_id = opportunity.id
    row.decided_by_user_id = user_id
    row.decided_at = now
    return opportunity
