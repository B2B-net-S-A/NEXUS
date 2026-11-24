"""Router `/api/review-batch` — porcja dnia od Nexusa (decyzje Artura 07.11.2026).

Stan porcji osoby (licznik w pasku, kafel pulpitu), kolejka przeglądu,
„Dodaj 20 kolejnych” w rekrutacji, cel kart wg tempa i ustawienie minimum (HoR). Same decyzje
to zwykłe ruchy w pipeline (`POST /api/pipeline/move`, odrzucenie z powodem
osoby od systemu), żeby reguły ruchu obowiązywały bez kopii. Reguła:
`docs/claude/rekrutacja-tablica/porcja-dnia-minimum-przed-wyszukiwaniem.md`.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, OperationalUser
from app.api.recruitment_access import (
    ensure_job_editor,
    ensure_job_membership,
    job_edit_level,
    user_can_staff_job,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_date
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.services import review_batch as svc
from app.services import (
    job_role_profile,
    review_batch_focus,
    review_batch_streams,
    review_batch_team,
)
from app.services.request_work_state import IN_WORK_STATES
from app.services.review_batch_order import OrderFacts, polish_penalty

router = APIRouter(
    prefix="/api/review-batch",
    tags=["review-batch"],
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)


class RoleProfileIn(BaseModel):
    role: Optional[str] = Field(default=None, max_length=200)
    specialty: Optional[str] = Field(default=None, max_length=200)
    technology: Optional[str] = Field(default=None, max_length=200)
    level: str = job_role_profile.DEFAULT_LEVEL
    # Cała lista „Nie proponujemy”, jaka ma zostać (ręczne i z odrzuceń).
    excluded: list[str] = Field(default_factory=list, max_length=50)


class FocusIn(BaseModel):
    # ``None`` = powrót do kolejności z poziomów (najpierw pilne).
    job_id: Optional[int] = Field(default=None, ge=1)


class SettingsIn(BaseModel):
    minimum: int = Field(ge=1, le=svc.MAX_MINIMUM)
    # Brak pola = bez zmiany (stary front wysyła samo minimum).
    block_enabled: Optional[bool] = None
    pilot_user_ids: Optional[list[int]] = Field(default=None, max_length=200)
    min_score: Optional[float] = Field(
        default=None, ge=svc.MIN_SCORE_FLOOR, le=svc.MIN_SCORE_CEIL
    )


@router.get("/me")
async def my_batch(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Stan porcji: minimum, decyzje dziś, czekające osoby per rekrutacja."""
    from app.services.new_column_autofill import MORE_CARDS, tempo_enabled

    status = await svc.status_for(db, current_user, now=datetime.now(timezone.utc))
    return {
        **status.as_dict(),
        "more_cards": MORE_CARDS if tempo_enabled() else svc.BATCH_SIZE,
    }


@router.get("/me/focus")
async def my_focus_options(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """„Nad którą rekrutacją pracujesz dziś?”: rekrutacje osoby, ile w każdej
    masz osób z porcji i kto już ją dziś wybrał (``review_batch_focus``)."""
    return await review_batch_focus.options_for(
        db, current_user, now=datetime.now(timezone.utc)
    )


@router.get("/me/focus/{job_id}")
async def my_focus_preview(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Podgląd wyboru jednej rekrutacji: ile osób przyjdzie z niej naprawdę (po
    regułach dopełniania), ile z pozostałych i ile wróci do zespołu."""
    return await review_batch_focus.preview_for(
        db, current_user, job_id, now=datetime.now(timezone.utc)
    )


@router.put("/me/focus")
async def choose_focus(
    payload: FocusIn,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Wybór rekrutacji na dziś: porcja bierze osoby najpierw stamtąd, a
    nieruszone osoby z innych rekrutacji wracają do puli zespołu."""
    result = await review_batch_focus.choose(
        db, current_user, payload.job_id, now=datetime.now(timezone.utc)
    )
    await db.commit()
    return result


def _position(candidate: Candidate) -> Optional[str]:
    data = (
        candidate.cv_extracted_data
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    value = data.get("current_position") or candidate.linkedin_current_title
    return str(value)[:120] if value else None


def _order_note(card: svc.PendingCard) -> dict:
    """Dlaczego karta stoi na tym miejscu: te same powody co na Tablicy."""
    facts = card.facts if isinstance(card.facts, OrderFacts) else OrderFacts()
    return {
        "known": facts.known.as_dict() if facts.known is not None else None,
        "order_active": facts.bonus.active,
        "order_in_budget": facts.bonus.in_budget,
        "order_polish_later": polish_penalty(facts.bonus.polish) > 0,
        "order_leader_gap": facts.bonus.leader_gap,
    }


def _requirements(card: svc.PendingCard) -> Optional[dict]:
    facts = card.facts if isinstance(card.facts, OrderFacts) else None
    steps = facts.steps if facts is not None else None
    return steps.as_dict() if steps is not None else None


def _client_recent(card: svc.PendingCard, titles: dict[int, str]) -> Optional[dict]:
    facts = card.facts if isinstance(card.facts, OrderFacts) else None
    known = facts.known if facts is not None else None
    if known is None or known.client_recent_job_id is None:
        return None
    return {
        "days": known.client_recent_days,
        "job_id": known.client_recent_job_id,
        "job_title": titles.get(known.client_recent_job_id, ""),
    }


@router.get("/me/queue")
async def my_queue(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    """Osoby z porcji w kolejności przeglądu (rekrutacja po rekrutacji, w każdej
    od najlepszej; 17.11.2026). Każdy wiersz niesie migawkę karty i id etapu
    do ruchu, a ``runs`` mówi, ile osób z której rekrutacji idzie po kolei
    w całej kolejce, nie tylko na tej stronie; ``stale`` tak samo liczy odłożone."""
    now = datetime.now(timezone.utc)
    whole = await svc.review_queue(db, current_user, now=now, limit=None)
    cards = whole[:limit]
    if not cards:
        return {"items": [], "runs": []}
    candidate_ids = {c.candidate_id for c in cards}
    job_ids = {c.job_id for c in cards}
    candidates = {
        c.id: c
        for c in (
            await db.scalars(select(Candidate).where(Candidate.id.in_(candidate_ids)))
        ).all()
    }
    jobs = {
        j.id: j
        for j in (await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
    }
    metas = dict(
        (
            await db.execute(
                select(RecruitmentProcess.id, RecruitmentProcess.entry_meta).where(
                    RecruitmentProcess.id.in_([c.process_id for c in cards])
                )
            )
        ).all()
    )
    stage_rows = (
        await db.execute(
            select(
                CandidateStage.id, CandidateStage.job_id, CandidateStage.candidate_id
            )
            .where(
                CandidateStage.job_id.in_(job_ids),
                CandidateStage.candidate_id.in_(candidate_ids),
            )
            .order_by(CandidateStage.moved_at.asc(), CandidateStage.id.asc())
        )
    ).all()
    latest_stage = {(job_id, cid): sid for sid, job_id, cid in stage_rows}
    # „Masz tę osobę, bo: jesteś przypisana (…) · P0 do …” (10.11.2026).
    from app.services import job_p0
    from app.services.job_team import recruiters_for_jobs, working
    from app.services.review_batch_plan import tier_key, tier_of

    via = {
        job_id: person.via
        for job_id, people in (await recruiters_for_jobs(db, job_ids)).items()
        for person in working(people)
        if person.user_id == current_user.id
    }
    focus = (await review_batch_focus.read_focus(db)).get(current_user.id)
    # „Kluczowe w tej rekrutacji”: krytyczne z dowodem i polski (12.11.2026).
    from app.services.review_batch_facts import key_facts_for

    key_facts = await key_facts_for(
        db,
        [
            (card.process_id, jobs[card.job_id], candidates[card.candidate_id])
            for card in cards
            if card.job_id in jobs and card.candidate_id in candidates
        ],
    )
    # „Wysłany wcześniej” (20.11.2026): gdzie i kiedy osoba poszła już do klienta.
    from app.services import sent_before
    from app.services.process_entry_meta import caution_views

    sent = await sent_before.facts_for(
        db, job_id=None, candidate_ids=candidate_ids, now=now
    )
    # „Wysłany do tego klienta” (R4, 22.11.2026): tytuł rekrutacji, do której poszedł.
    recent_ids = {
        card.facts.known.client_recent_job_id
        for card in cards
        if isinstance(card.facts, OrderFacts)
        and card.facts.known is not None
        and card.facts.known.client_recent_job_id is not None
    }
    recent_titles = (
        {
            int(job_id): title or ""
            for job_id, title in (
                await db.execute(
                    select(Job.id, Job.title).where(Job.id.in_(recent_ids))
                )
            ).all()
        }
        if recent_ids
        else {}
    )
    items = []
    for card in cards:
        person = candidates.get(card.candidate_id)
        job = jobs.get(card.job_id)
        if person is None or job is None:
            continue
        meta = metas.get(card.process_id) or {}
        items.append(
            {
                "process_id": card.process_id,
                "stage_id": latest_stage.get((card.job_id, card.candidate_id)),
                "job_id": job.id,
                "job_title": job.title or "",
                "candidate_id": person.id,
                "name": person.name,
                "city": person.city,
                "years": person.years_it_experience,
                "position": _position(person),
                "score": card.score,
                "matched_must": meta.get("matched_must") or [],
                "missing_must": meta.get("missing_must") or [],
                "rate_from_hourly": meta.get("rate_from_hourly"),
                "rate_currency": meta.get("rate_currency"),
                "availability_status": meta.get("availability_status"),
                "cautions": caution_views(meta.get("cautions")),
                "sent_before": (
                    sent[card.candidate_id].as_dict()
                    if card.candidate_id in sent
                    else None
                ),
                "budget_hourly": (
                    float(job.rate_budget_hourly)
                    if job.rate_budget_hourly is not None
                    else None
                ),
                **_order_note(card),
                "client_recent": _client_recent(card, recent_titles),
                # Odłożona na koniec porcji: bez decyzji od 2 dni roboczych (R5).
                "stale": svc.is_stale(card, now),
                "opened_on": (
                    business_date(card.opened_at).isoformat()
                    if card.opened_at is not None
                    else None
                ),
                "key_facts": key_facts.get(card.process_id),
                # Schodki po wymaganiach (23.11.2026): „Musi mieć 7 z 10” na karcie.
                "requirements": _requirements(card),
                "why": {
                    "source": tier_key(tier_of(job, now)),
                    "via": via.get(job.id),
                    "p0_until": (
                        job.p0_until.isoformat()
                        if job_p0.is_active(job, now) and job.p0_until is not None
                        else None
                    ),
                    # Rekrutacja wybrana na dziś (``review_batch_focus``).
                    "chosen": focus is not None and focus.job_id == job.id,
                },
            }
        )
    # Reguła rekrutacji z powtarzanych braków (R1, 12.11.2026) — linia nad kartą.
    from app.services.job_learned_rules import rules_for_jobs

    learned = await rules_for_jobs(db, job_ids)
    # Profil „Kogo szukamy” i „Nie proponujemy” (16.11.2026) — blok nad kartą.
    profiles = await job_role_profile.profiles_for_jobs(db, jobs.values())
    return {
        "items": items,
        "job_rules": {
            str(job_id): [rule.as_dict() for rule in rules]
            for job_id, rules in learned.items()
        },
        "job_profiles": {str(job_id): profile for job_id, profile in profiles.items()},
        "runs": [
            {"job_id": job_id, "count": count}
            for job_id, count in svc.queue_runs(whole)
        ],
        # Odłożone z całej kolejki, nie tylko z tej strony (linia „Na końcu porcji”).
        "stale": svc.stale_summary(whole, now),
    }


async def _job_or_404(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    return job


@router.get("/jobs/{job_id}/profile")
async def get_role_profile(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Profil „Kogo szukamy” rekrutacji z listą „Nie proponujemy”."""
    await ensure_job_membership(db, current_user, job_id)
    job = await _job_or_404(db, job_id)
    profile = (await job_role_profile.profiles_for_jobs(db, [job]))[job.id]
    return {**profile, "can_edit": await _can_edit_profile(db, current_user, job)}


async def _can_edit_profile(db: AsyncSession, user, job: Job) -> bool:
    """Rekruter przypisany do rekrutacji (jak „Dodaj kolejnych”), Delivery Lead
    w swoim zakresie, Head of Recruitment i admin."""
    if await user_can_staff_job(db, user, job):
        return True
    team = (await svc.recruiter_ids_for_jobs(db, [job.id])).get(job.id, [])
    return user.id in team


@router.put("/jobs/{job_id}/profile")
async def put_role_profile(
    job_id: int,
    payload: RoleProfileIn,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """„Popraw” w porcji: rola, specjalizacja, technologia, poziom i lista
    „Nie proponujemy”. Ręczny wpis działa od następnego dokładania kart."""
    job = await _job_or_404(db, job_id)
    if not await _can_edit_profile(db, current_user, job):
        raise HTTPException(
            status_code=403,
            detail=(
                "Profil „Kogo szukamy” poprawia rekruter tej rekrutacji, "
                "Delivery Lead albo Head of Recruitment."
            ),
        )
    profile = await job_role_profile.save_profile(
        db, job, payload.model_dump(), user_id=current_user.id
    )
    await db.commit()
    return {**profile, "can_edit": True}


def _in_work(job: Job) -> bool:
    return job.status == JobStatus.published and job.work_state in IN_WORK_STATES


@router.get("/jobs/{job_id}/tempo")
async def job_tempo(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Plakietka „cel N” i przycisk „Dodaj 10 kolejnych” przy kolumnie „Nowi”."""
    from app.services import new_column_autofill as autofill

    if not autofill.tempo_enabled():
        return {"enabled": False}
    await ensure_job_membership(db, current_user, job_id)
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    now = datetime.now(timezone.utc)
    tempo = (await autofill.tempo_for_jobs(db, [job_id], now))[job_id]
    return {
        "enabled": True,
        "tier": tempo.tier,
        "target": tempo.target,
        "decisions": tempo.decisions,
        "waiting": await autofill.waiting_system_cards(db, job_id),
        "more_cards": autofill.MORE_CARDS,
        "can_add_more": _in_work(job)
        and await job_edit_level(db, current_user, job) is not None,
    }


async def _add_more_by_tempo(db: AsyncSession, user, job_id: int) -> dict:
    """„Dodaj 10 kolejnych”: każda osoba z prawem edycji rekrutacji, także bez
    porcji. W porcji rekruter najpierw przegląda swoje osoby, jak dotąd."""
    from app.services.new_column_autofill import MORE_CARDS, fill_job

    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    await ensure_job_editor(db, user, job)
    if not _in_work(job):
        raise HTTPException(status_code=409, detail="Ta rekrutacja nie jest w pracy.")
    now = datetime.now(timezone.utc)
    team = (
        (await svc.recruiter_ids_for_jobs(db, [job_id])).get(job_id, [])
        if svc.enabled()
        else []
    )
    if user.id in team:
        min_score = (await svc.read_settings(db)).min_score
        mine = svc.batch_cards(
            await svc.pending_cards(db, job_ids=[job_id], owner_id=user.id),
            now,
            min_score,
        )
        if mine:
            raise HTTPException(
                status_code=409,
                detail=f"Najpierw przejrzyj swoje osoby w tej rekrutacji ({len(mine)}).",
            )
    added = await fill_job(
        db,
        job_id,
        now=now,
        batch=bool(team),
        extra_for=user.id if user.id in team else None,
        extra_cards=MORE_CARDS,
    )
    await db.commit()
    return {"added": len(added)}


@router.post("/jobs/{job_id}/more")
async def add_more(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """„Dodaj 20 kolejnych”: tylko rekruter tej rekrutacji, gdy jego część
    porcji w niej jest przejrzana. Nowe osoby trafiają do klikającego. Przy
    celu wg tempa zastępuje go „Dodaj 10 kolejnych” (``_add_more_by_tempo``)."""
    from app.services.new_column_autofill import fill_job, tempo_enabled

    if tempo_enabled():
        return await _add_more_by_tempo(db, current_user, job_id)
    if not svc.enabled():
        raise HTTPException(status_code=409, detail="Porcja dnia jest wyłączona.")
    min_score = (await svc.read_settings(db)).min_score
    team = (await svc.recruiter_ids_for_jobs(db, [job_id])).get(job_id, [])
    if current_user.id not in team:
        raise HTTPException(
            status_code=403,
            detail="Kolejne osoby dobiera rekruter przypisany do tej rekrutacji.",
        )
    now = datetime.now(timezone.utc)
    mine = svc.batch_cards(
        await svc.pending_cards(db, job_ids=[job_id], owner_id=current_user.id),
        now,
        min_score,
    )
    if mine:
        raise HTTPException(
            status_code=409,
            detail=f"Najpierw przejrzyj swoje osoby w tej rekrutacji ({len(mine)}).",
        )
    added = await fill_job(
        db,
        job_id,
        now=now,
        batch=True,
        extra_for=current_user.id,
    )
    await db.commit()
    return {"added": len(added)}


@router.get("/settings")
async def get_settings(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    value = await svc.read_settings(db)
    out = {
        **value.as_dict(),
        "batch_size": svc.BATCH_SIZE,
        "max_age_days": svc.MAX_AGE_DAYS,
        "enabled": svc.enabled(),
    }
    if svc.can_edit_settings(current_user):
        # Lista do wyboru pilota — tylko dla tych, którzy ją ustawiają.
        out["recruiters"] = await svc.batch_recruiters(db)
    return out


@router.get("/team")
async def team_today(
    _current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Kto ile dziś zdecydował, kto utknął na blokadzie i dwa strumienie
    wysłanych CV — dla Head of Recruitment i admina."""
    now = datetime.now(timezone.utc)
    view = await review_batch_team.team_view(db, now=now)
    view["streams"] = await review_batch_streams.weekly_streams(db, now=now)
    return view


@router.put("/settings")
async def put_settings(
    payload: SettingsIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Minimum decyzji dziennie, wyłącznik blokady i pilot — ustawia Head of
    Recruitment i admin."""
    current = await svc.read_settings(db)
    value = svc.BatchSettings(
        minimum=payload.minimum,
        block_enabled=(
            current.block_enabled
            if payload.block_enabled is None
            else payload.block_enabled
        ),
        pilot_user_ids=(
            current.pilot_user_ids
            if payload.pilot_user_ids is None
            else tuple(sorted(set(payload.pilot_user_ids)))
        ),
        min_score=current.min_score if payload.min_score is None else payload.min_score,
    )
    error = svc.validation_error(value)
    if error:
        raise HTTPException(status_code=422, detail=error)
    await svc.write_settings(db, value, user_id=current_user.id)
    await db.commit()
    return value.as_dict()
