"""Bliźniacze rekrutacje (0615, decyzje Artura z 28.10.2026).

* ``GET    /api/jobs/{id}/twins`` — bliźniaki rekrutacji i czy patrzący łączy.
* ``GET    /api/jobs/{id}/twins/preview?other_job_id=`` — okno „Połącz
  bliźniaka”: obie rekrutacje (budżet, tryb pracy, DL), pytania i podpowiedź
  par „to samo pytanie”.
* ``POST   /api/jobs/{id}/twins`` — połącz (oba kierunki) z parami pytań;
  dzwonek do zespołów obu rekrutacji.
* ``DELETE /api/jobs/{id}/twins/{other_id}`` — rozłącz (nikt nie znika).
* ``GET    /api/jobs/{id}/open-similar`` — kafel „Otwarte podobne”: otwarte
  podobne rekrutacje, P1 na górze, z informacją, czy patrzący może połączyć.
* ``GET    /api/job-twins/candidates?client_id=`` — „Czy to bliźniak?” na
  stronie tworzenia: DL — jego otwarte rekrutacje (najpierw tego klienta),
  HoR/admin — otwarte rekrutacje tego klienta.
* ``GET    /api/job-twins/suggestions`` — HoR/admin: możliwe bliźniaki
  z różnymi DL-ami (lista rekrutacji).
* ``POST   /api/job-twins/dismiss`` — HoR/admin: „To nie bliźniak”.

Kto łączy, sprawdza serwis (``job_twins.can_link``) — macierz authz widzi
tylko zależność trasy, regułę ról pilnuje ``test_job_twins.py``.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje ciała w czasie rejestracji trasy.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, RecruiterPlus, get_db
from app.api.job_similar import _job
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import job_twin_rules, job_twins

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


async def _briefs(db: AsyncSession, job_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Wiersz rekrutacji do okna, kafla i listy HoR: budżet i tryb pracy obok."""
    from app.services.dealbreaker_filters import (  # noqa: PLC0415
        resolve_job_budget_hourly,
    )
    from app.services.job_working_title import display_title  # noqa: PLC0415

    ids = sorted(set(job_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Job, func.coalesce(Client.display_name, Client.name), User.name)
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(User, User.id == Job.delivery_lead_id)
            .where(Job.id.in_(ids))
        )
    ).all()
    people = dict(
        (
            await db.execute(
                select(
                    CandidateStage.job_id,
                    func.count(func.distinct(CandidateStage.candidate_id)),
                )
                .where(CandidateStage.job_id.in_(ids))
                .group_by(CandidateStage.job_id)
            )
        ).all()
    )
    out: dict[int, dict[str, Any]] = {}
    for job, client_name, dl_name in rows:
        budget = resolve_job_budget_hourly(job)
        out[job.id] = {
            "id": job.id,
            "title": display_title(job),
            "reference_number": job.reference_number,
            "client_reference": job.client_reference,
            "client_id": job.client_id,
            "client_name": client_name,
            "delivery_lead_id": job.delivery_lead_id,
            "delivery_lead_name": dl_name,
            "status": job.status.value if hasattr(job.status, "value") else job.status,
            "is_open": job_twins.is_open(job),
            "p1": job.priority in job_twins.P1_PRIORITIES,
            "budget_min_hourly": (
                float(job.rate_budget_hourly_min)
                if job.rate_budget_hourly_min
                else None
            ),
            "budget_hourly": float(budget) if budget is not None else None,
            "remote_policy": (
                job.remote_policy.value
                if hasattr(job.remote_policy, "value")
                else job.remote_policy
            ),
            "onsite_days_per_week": job.onsite_days_per_week,
            "onsite_days_per_month": job.onsite_days_per_month,
            "location": job.location,
            "people_count": int(people.get(job.id, 0)),
        }
    return out


async def _twins_payload(db: AsyncSession, user: User, job: Job) -> dict[str, Any]:
    links = (await job_twins.twin_links(db, [job.id])).get(job.id, [])
    briefs = await _briefs(db, [row.similar_job_id for row in links])
    return {
        "job_id": job.id,
        "can_manage": await job_twins.can_manage(db, user, job),
        "max_twins": job_twins.MAX_TWINS,
        "twins": [
            {**briefs[row.similar_job_id], "question_pairs": row.question_pairs or []}
            for row in links
            if row.similar_job_id in briefs
        ],
    }


@router.get("/jobs/{job_id}/twins")
async def get_job_twins(
    job_id: int, user: OperationalUser, db: AsyncSession = Depends(get_db)
):
    job = await _job(db, user, job_id)
    return await _twins_payload(db, user, job)


async def _verified_missing(db: AsyncSession, source_id: int, target_id: int) -> int:
    """Osoby, które w ``source`` doszły do „Zweryfikowanego”, a w ``target``
    ich nie ma — okno mówi, że zostają tam, gdzie są (bez kopiowania)."""
    from sqlalchemy import exists  # noqa: PLC0415
    from sqlalchemy.orm import aliased  # noqa: PLC0415

    from app.services.job_similarity import CLIENT_STAGES  # noqa: PLC0415
    from app.models.recruitment_pipeline import PipelineStage  # noqa: PLC0415

    other = aliased(CandidateStage)
    return int(
        await db.scalar(
            select(func.count(func.distinct(CandidateStage.candidate_id))).where(
                CandidateStage.job_id == source_id,
                CandidateStage.stage.in_((PipelineStage.verified, *CLIENT_STAGES)),
                ~exists().where(
                    other.candidate_id == CandidateStage.candidate_id,
                    other.job_id == target_id,
                ),
            )
        )
        or 0
    )


@router.get("/jobs/{job_id}/twins/preview")
async def preview_job_twin(
    job_id: int,
    user: RecruiterPlus,
    other_job_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    other = await db.get(Job, other_job_id)
    if other is None or other.id == job.id:
        raise HTTPException(404, "Nie ma takiej rekrutacji.")
    if not await job_twins.can_link(db, user, job, other):
        raise HTTPException(
            403,
            "Delivery Lead łączy tylko swoje rekrutacje. "
            "Rekrutacje innych DL-i łączy Head of Recruitment albo admin.",
        )
    rules = await job_twin_rules.load(db)
    own_q = job_twins.question_texts(job)
    other_q = job_twins.question_texts(other)
    checks = job_twin_rules.evaluate(
        rules, job_twin_rules.facts_of(job), job_twin_rules.facts_of(other)
    )
    existing = next(
        (
            row
            for row in (await job_twins.twin_links(db, [job.id])).get(job.id, [])
            if row.similar_job_id == other.id
        ),
        None,
    )
    briefs = await _briefs(db, [job.id, other.id])
    return {
        "job": {
            **briefs[job.id],
            "questions": [{"id": k, "text": v} for k, v in own_q.items()],
        },
        "other": {
            **briefs[other.id],
            "questions": [{"id": k, "text": v} for k, v in other_q.items()],
        },
        "already_twin": existing is not None,
        "question_pairs": (
            existing.question_pairs or []
            if existing is not None
            else job_twins.suggest_question_pairs(
                own_q, other_q, job_twin_rules.PAIR_HINT_THRESHOLDS[rules.pair_hint]
            )
        ),
        # Zasady z Ustawień (29.10.2026): „Wymagane” tylko filtruje listę —
        # łączyć wolno, okno pokazuje, czego para nie spełnia.
        "rules": [c.as_dict() for c in checks],
        "verified_not_in_other": await _verified_missing(db, job.id, other.id),
        "verified_not_in_job": await _verified_missing(db, other.id, job.id),
    }


class QuestionPairBody(BaseModel):
    own: str = Field(min_length=1, max_length=40)
    other: str = Field(min_length=1, max_length=40)


class LinkTwinBody(BaseModel):
    other_job_id: int = Field(gt=0)
    question_pairs: list[QuestionPairBody] = Field(default_factory=list, max_length=40)


@router.post("/jobs/{job_id}/twins")
async def link_job_twin(
    job_id: int,
    body: LinkTwinBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    created = await job_twins.link(
        db,
        user=user,
        job_id=job.id,
        other_id=body.other_job_id,
        question_pairs=[pair.model_dump() for pair in body.question_pairs],
    )
    if created:
        other = await db.get(Job, body.other_job_id)
        await job_twins.notify_linked(db, job=job, other=other, actor_id=user.id)
    job_twins.reset_suggestion_cache()
    await db.commit()
    payload = await _twins_payload(db, user, job)
    return {**payload, "linked_now": created}


@router.delete("/jobs/{job_id}/twins/{other_id}")
async def unlink_job_twin(
    job_id: int,
    other_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    removed = await job_twins.unlink(db, user=user, job_id=job.id, other_id=other_id)
    job_twins.reset_suggestion_cache()
    await db.commit()
    payload = await _twins_payload(db, user, job)
    return {**payload, "unlinked_now": removed}


@router.get("/jobs/{job_id}/open-similar")
async def get_open_similar_jobs(
    job_id: int, user: OperationalUser, db: AsyncSession = Depends(get_db)
):
    """Kafel „Otwarte podobne” — tylko otwarte, P1 na górze. Zamknięte zostają
    w „Podobnych rekrutacjach” (przepięcia)."""
    job = await _job(db, user, job_id)
    rules = await job_twin_rules.load(db)
    ranked = await job_twins.open_similar(db, job, rules.open_similar_limit)
    briefs = await _briefs(db, [jid for jid, _ in ranked])
    facts = await job_twin_rules.facts_for(db, [job.id, *(jid for jid, _ in ranked)])
    twins = set(await job_twins.twin_ids(db, job.id))
    full = len(twins) >= min(job_twins.MAX_TWINS, rules.max_twins)
    can_any = await job_twins.can_manage(db, user, job)
    items = []
    for jid, similarity in ranked:
        brief = briefs.get(jid)
        if brief is None:
            continue
        other = await db.get(Job, jid)
        can_twin = (
            can_any
            and jid not in twins
            and not full
            and await job_twins.can_link(db, user, job, other)
        )
        checks = (
            job_twin_rules.evaluate(rules, facts[job.id], facts[jid])
            if job.id in facts and jid in facts
            else []
        )
        failed = job_twin_rules.required_failures(checks)
        if not job_twin_rules.similarity_ok(rules, similarity):
            failed = [
                job_twin_rules.RuleCheck(
                    "similarity",
                    "required",
                    False,
                    f"{similarity}% (od {rules.min_similarity}%)",
                ),
                *failed,
            ]
        items.append(
            {
                **brief,
                "similarity": similarity,
                "twin": jid in twins,
                "can_twin": can_twin,
                "twin_limit_reached": full and jid not in twins,
                # Zasady bliźniaków: niespełnione wymagane i ostrzeżenia.
                "rule_failures": [c.as_dict() for c in failed],
                "rule_warnings": [c.as_dict() for c in job_twin_rules.warnings(checks)],
            }
        )
    return {"job_id": job.id, "items": items}


CANDIDATES_LIMIT = 30


@router.get("/job-twins/candidates")
async def get_twin_candidates(
    user: RecruiterPlus,
    client_id: Optional[int] = Query(None, gt=0),
    db: AsyncSession = Depends(get_db),
):
    """Rekrutacje do zaznaczenia jako bliźniak nowej rekrutacji (przed zapisem).

    Połączenie powstaje po utworzeniu (``POST …/twins``) i tam przechodzi
    pełne sprawdzenie uprawnień — ta lista tylko podpowiada."""
    from sqlalchemy import case  # noqa: PLC0415

    if user.has_any_role(*job_twins.LINK_ALL_ROLES):
        if client_id is None:
            return {"items": []}
        scope = Job.client_id == client_id
    elif user.has_any_role("delivery_lead"):
        scope = Job.delivery_lead_id == user.id
    else:
        return {"items": []}
    order = [Job.created_at.desc(), Job.id.desc()]
    if client_id is not None:
        order.insert(0, case((Job.client_id == client_id, 0), else_=1))
    ids = list(
        (
            await db.execute(
                select(Job.id)
                .where(
                    scope,
                    Job.status != JobStatus.closed,
                    Job.work_state.in_(job_twins._work_states()),  # noqa: SLF001
                )
                .order_by(*order)
                .limit(CANDIDATES_LIMIT)
            )
        ).scalars()
    )
    briefs = await _briefs(db, ids)
    return {"items": [briefs[i] for i in ids if i in briefs]}


def _require_hor(user: User) -> None:
    if not user.has_any_role(*job_twins.LINK_ALL_ROLES):
        raise HTTPException(
            403, "Propozycje bliźniaków widzi Head of Recruitment i admin."
        )


@router.get("/job-twins/suggestions")
async def get_twin_suggestions(user: RecruiterPlus, db: AsyncSession = Depends(get_db)):
    _require_hor(user)
    rules = await job_twin_rules.load(db)
    items = await job_twins.suggestions(db)
    briefs = await _briefs(
        db, [i.job_id for i, _ in items] + [i.other_id for i, _ in items]
    )
    return {
        "min_similarity": rules.min_similarity,
        "items": [
            {
                "similarity": item.similarity,
                "job": briefs[item.job_id],
                "other": briefs[item.other_id],
                "warnings": [c.as_dict() for c in warns],
            }
            for item, warns in items
            if item.job_id in briefs and item.other_id in briefs
        ],
    }


# ── Zasady bliźniaków (Ustawienia → Rekrutacja, 29.10.2026) ────────────────


def _rules_payload(rules: job_twin_rules.TwinRules, user: User) -> dict[str, Any]:
    return {
        "rules": rules.model_dump(),
        "defaults": job_twin_rules.defaults().model_dump(),
        "labels": job_twin_rules.RULE_LABELS,
        "can_edit": user.has_any_role(*job_twins.LINK_ALL_ROLES),
    }


@router.get("/job-twins/rules")
async def get_twin_rules(user: RecruiterPlus, db: AsyncSession = Depends(get_db)):
    return _rules_payload(await job_twin_rules.load(db), user)


@router.put("/job-twins/rules")
async def save_twin_rules(
    body: job_twin_rules.TwinRules,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    if not user.has_any_role(*job_twins.LINK_ALL_ROLES):
        raise HTTPException(
            403, "Zasady bliźniaków zmienia Head of Recruitment i admin."
        )
    saved = await job_twin_rules.save(db, body, user_id=user.id)
    job_twins.reset_suggestion_cache()
    await db.commit()
    return _rules_payload(saved, user)


@router.post("/job-twins/rules/preview")
async def preview_twin_rules(
    body: job_twin_rules.TwinRules,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Ile par przejdzie przy zasadach z formularza — przed zapisem."""
    _require_hor(user)
    return await job_twins.rules_preview(db, body)


class DismissTwinBody(BaseModel):
    job_ids: list[int] = Field(min_length=2, max_length=2)


@router.post("/job-twins/dismiss")
async def dismiss_twin_suggestion(
    body: DismissTwinBody, user: RecruiterPlus, db: AsyncSession = Depends(get_db)
) -> dict[str, Optional[bool]]:
    _require_hor(user)
    a, b = body.job_ids
    known = set((await db.execute(select(Job.id).where(Job.id.in_([a, b])))).scalars())
    if {a, b} - known:
        raise HTTPException(404, "Nie ma takiej rekrutacji.")
    await job_twins.dismiss(db, user=user, job_id=a, other_id=b)
    await db.commit()
    return {"dismissed": True}
