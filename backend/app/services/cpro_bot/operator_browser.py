"""Pilot przez sesję WWW operatora. Rezerwacja nigdy nie oznacza braku oferty."""

from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_has_candidate_read
from app.api.candidate_stage_cv import _load_csv_for_stage
from app.api.recruitment_access import ensure_job_read_access
from app.models.cpro_bot import CproBotRun
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import cv_download_policy
from app.services.cpro_bot import flow, items, runs
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.core.scheduling import business_date


def can_use(
    user: User, *, can_send: bool, show_rate: bool, has_borrowed_data: bool = False
) -> bool:
    """Tania bramka listy; can_send/show_rate pochodzą z istniejącej polityki Cpro."""
    return bool(
        can_send
        and show_rate
        and user_has_candidate_read(user)
        and not user.has_role(UserRole.automation)
        and section_access_for_user(user, ProductSection.pipeline)
        >= SectionAccess.write
        and (not has_borrowed_data or user.has_role(UserRole.admin))
    )


def owned_by(run: CproBotRun, user_id: int) -> bool:
    return (run.request or {}).get(
        "operator_browser"
    ) is True and run.requested_by_user_id == user_id


def offer_id_from_link(value) -> str | None:
    """Tylko jednoznaczne, znane odnośniki ofert Nordea z raportów."""
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.hostname != "nordea.onevms.se"
            or url.username
            or url.password
            or url.port not in (None, 443)
            or url.fragment
        ):
            return None
        if url.path == "/nordea/vendor/OfferController":
            ids = parse_qs(url.query).get("id", [])
            raw = ids[0] if len(ids) == 1 else ""
        elif url.path.startswith("/offer/") and not url.query:
            raw = url.path.removeprefix("/offer/")
        else:
            return None
        return (
            str(int(raw))
            if raw.isascii() and raw.isdigit() and 0 < len(raw) <= 20 and int(raw) > 0
            else None
        )
    except ValueError:
        return None


async def ensure_offer_available(db: AsyncSession, run_id: int, offer_id: str) -> None:
    """Wywołujący trzyma wspólną blokadę aż do zapisu potwierdzenia."""
    rows = await db.execute(
        select(
            CproBotRun.id,
            CproBotRun.request["operator_offer_id"].as_string(),
            CproBotRun.report,
        ).where(CproBotRun.id != run_id)
    )
    for _, confirmed, report in rows:
        if (
            confirmed is not None
            and str(confirmed).isascii()
            and str(confirmed).isdigit()
            and str(int(confirmed)) == offer_id
        ):
            raise HTTPException(
                409, "Ta oferta Cpro została już przypisana do innej karty."
            )
        for entry in ((report or {}).get("items") or {}).values():
            if (
                isinstance(entry, dict)
                and offer_id_from_link(entry.get("offer_url")) == offer_id
            ):
                raise HTTPException(409, "Ta oferta Cpro występuje już w innym biegu.")


async def reservations(
    db: AsyncSession, stage_ids: Iterable[int]
) -> dict[int, CproBotRun]:
    """Jedno zapytanie dla kolejki, także po wygaśnięciu lub błędzie biegu."""
    wanted = {int(s) for s in stage_ids}
    if not wanted:
        return {}
    rows = await db.scalars(
        select(CproBotRun)
        .where(
            CproBotRun.request["operator_browser"].as_boolean().is_(True),
            CproBotRun.request["operator_absent_confirmed"].as_boolean().is_not(True),
            or_(*(CproBotRun.stage_ids.contains([s]) for s in sorted(wanted))),
        )
        .order_by(CproBotRun.id.desc())
    )
    result = {}
    for run in rows:
        for stage_id in wanted.intersection(run.stage_ids or []):
            result.setdefault(stage_id, run)
    return result


async def unresolved_stage_ids(db: AsyncSession, stage_ids: Iterable[int]) -> set[int]:
    """Starsza próba bez wyniku tej karty nie uprawnia do nowego zapisu w portalu."""
    wanted = {int(s) for s in stage_ids}
    if not wanted:
        return set()
    rows = await db.execute(
        select(CproBotRun.stage_ids, CproBotRun.report).where(
            CproBotRun.request["operator_browser"].as_boolean().is_not(True),
            or_(*(CproBotRun.stage_ids.contains([s]) for s in sorted(wanted))),
        )
    )
    return {
        stage_id
        for group, report in rows
        for stage_id in wanted.intersection(group or [])
        if not isinstance(((report or {}).get("items") or {}).get(str(stage_id)), dict)
    }


def item_for(run: CproBotRun) -> dict:
    entries = (run.request or {}).get("items") or []
    if (
        len(run.stage_ids or []) != 1
        or len(entries) != 1
        or entries[0].get("ref") != run.stage_ids[0]
    ):
        raise HTTPException(409, "Bieg nie zawiera jednej karty operatora.")
    return entries[0]


async def ensure_source_access(
    db: AsyncSession, user: User, *, stage_id: int, cv_stage_id: int, borrowed: bool
) -> None:
    if borrowed and not user.has_role(UserRole.admin):
        raise HTTPException(
            403, "Dane z innej rekrutacji wymagają kontroli administratora."
        )
    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(404, "Nie ma tej karty.")
    await ensure_job_read_access(db, user, stage.job_id)
    csv = await _load_csv_for_stage(db, cv_stage_id, user, read_access=True)
    if csv.job_id != stage.job_id and not user.has_role(UserRole.admin):
        raise HTTPException(
            403, "CV z innej rekrutacji wymaga kontroli administratora."
        )
    if csv.candidate_id != stage.candidate_id:
        raise HTTPException(409, "CV nie odpowiada osobie na karcie.")
    await cv_download_policy.ensure_can_save_file(
        db, user, filename="CV.pdf", content_type="application/pdf"
    )


async def ensure_run_access(db: AsyncSession, run: CproBotRun, user: User) -> dict:
    if not owned_by(run, user.id):
        raise HTTPException(404, "Nie ma takiego biegu operatora.")
    item = item_for(run)
    card = ((run.request or {}).get("cards") or {}).get(str(item["ref"])) or {}
    await ensure_source_access(
        db,
        user,
        stage_id=item["ref"],
        cv_stage_id=int(card.get("cv_stage_id") or 0),
        borrowed=bool(item.get("data_from")),
    )
    return item


async def current_snapshot(db: AsyncSession, run: CproBotRun, *, now: datetime) -> bool:
    """Gotowość i pełny snapshot muszą nadal odpowiadać przypiętemu zleceniu."""
    item = item_for(run)
    fresh = await items.load_items(
        db, stage_ids=[item["ref"]], now=now, today=business_date(now)
    )
    card = ((run.request or {}).get("cards") or {}).get(str(item["ref"])) or {}
    return bool(
        len(fresh) == 1
        and fresh[0].payload == item
        and fresh[0].cv
        and fresh[0].cv.candidate_stage_id == card.get("cv_stage_id")
        and fresh[0].candidate_id == card.get("candidate_id")
        and fresh[0].job_id == card.get("job_id")
    )


async def identity_current(db: AsyncSession, run: CproBotRun) -> bool:
    item = item_for(run)
    stage = await db.get(CandidateStage, item["ref"])
    job = await db.get(Job, stage.job_id) if stage else None
    card = ((run.request or {}).get("cards") or {}).get(str(item["ref"])) or {}
    return bool(
        job
        and stage.candidate_id == card.get("candidate_id")
        and stage.job_id == card.get("job_id")
        and job.delivery_lead_id == item["cpro_account"]["delivery_lead_id"]
        and items.request_number(job.client_reference) == item["request_number"]
    )


def can_close_absent(run: CproBotRun, *, identity_matches: bool, now: datetime) -> bool:
    return bool(
        identity_matches
        and run.status in ("started", "expired", "failed")
        and not run.report
        and not run.request.get("operator_offer_id")
        and not run.request.get("operator_absent_confirmed")
        and run.token_expires_at
        and run.token_expires_at <= now
    )


def pdf_available(run: CproBotRun, *, now: datetime) -> bool:
    return bool(
        run.status == "started"
        and run.token_expires_at
        and run.token_expires_at > now
        and not runs.enabled()
    )


async def claim(
    db: AsyncSession,
    user: User,
    stage_id: int,
    *,
    delivery_lead_id: int,
    request_number: str,
    now: datetime,
) -> tuple[CproBotRun, bool]:
    # Koniec globalnej dzierżawy nie zwalnia rezerwacji tej konkretnej karty.
    await db.execute(
        update(CproBotRun)
        .where(
            CproBotRun.request["operator_browser"].as_boolean().is_(True),
            CproBotRun.status == "started",
            CproBotRun.token_expires_at <= now,
        )
        .values(
            status="expired",
            token_hash=None,
            error="Przerwana próba operatora — sprawdź istniejący DRAFT.",
        )
    )
    await db.commit()
    await runs.lock_new_run(db)
    existing = (await reservations(db, [stage_id])).get(stage_id)
    if existing is not None:
        if not owned_by(existing, user.id):
            raise HTTPException(409, "Karta ma już zlecenie innego operatora.")
        item = await ensure_run_access(db, existing, user)
        if (
            item.get("request_number") != request_number
            or (item.get("cpro_account") or {}).get("delivery_lead_id")
            != delivery_lead_id
        ):
            raise HTTPException(409, "Zlecenie dotyczy innego konta lub requestu.")
        return existing, False

    if await unresolved_stage_ids(db, [stage_id]):
        raise HTTPException(
            409,
            "Wcześniejsza próba tej karty nie ma rozstrzygnięcia — sprawdź istniejącą ofertę ręcznie.",
        )

    async def check(item: items.BotItem) -> None:
        await ensure_source_access(
            db,
            user,
            stage_id=item.stage_id,
            cv_stage_id=item.cv.candidate_stage_id if item.cv else 0,
            borrowed=bool(item.data_from),
        )

    run, _ = await flow.create_interactive_draft(
        db,
        stage_id,
        delivery_lead_id=delivery_lead_id,
        request_number=request_number,
        now=now,
        today=business_date(now),
        operator_user_id=user.id,
        operator_check=check,
    )
    return run, True


def view(run: CproBotRun, *, current: bool, allow_close_absent: bool = False) -> dict:
    item = item_for(run)
    offer = {k: v for k, v in (item.get("offer") or {}).items() if k != "cv_url"}
    return {
        "run_id": run.id,
        "stage_id": item["ref"],
        "delivery_lead_id": item["cpro_account"]["delivery_lead_id"],
        "cpro_account_name": items.cpro_account_name(item["cpro_account"]),
        "request_number": item["request_number"],
        "request_title": item.get("request_title"),
        "candidate": item["candidate"],
        "offer": offer,
        "status": run.status,
        "mode": "operator_browser",
        "submit": False,
        "reservation_released": run.request.get("operator_absent_confirmed") is True,
        "allow_close_absent": allow_close_absent,
        "allow_create": bool(
            current and pdf_available(run, now=datetime.now(timezone.utc))
        ),
        "reconcile_only": not current
        or runs.enabled()
        or run.status != "started"
        or not run.token_expires_at
        or run.token_expires_at <= datetime.now(timezone.utc),
        "offer_id": (run.request or {}).get("operator_offer_id"),
    }
