"""Widok „Po ludzku” rekrutacji i jego odświeżanie.

``build_view`` tylko czyta (GET nic nie zapisuje i nie woła AI) i mówi przez
``stale``, czy profil zmienił się od ostatniej generacji. ``refresh`` robi
resztę: dopasowuje rolę, uzupełnia brakujące hasła słowniczka, rolę i opis
klienta researchem (najwyżej ``REQUEST_RESEARCH_BUDGET`` w żądaniu, reszta
w tle) i liczy teksty rekrutacji.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_playbook import ClientPlaybook
from app.models.competence_category import CompetenceCategory
from app.models.job import Job, JobStatus
from app.models.plain_knowledge import JobPlainBrief, PlainTerm, RoleProfile
from app.services.plain_knowledge import job_brief, knowledge, role_matcher

logger = logging.getLogger(__name__)

REQUEST_RESEARCH_BUDGET = 3
MIN_HIRES_FOR_TITLES = 3


def _sources(value: Any) -> list[dict[str, str]]:
    out = []
    for item in value or []:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            out.append(
                {
                    "url": item["url"],
                    "title": str(item.get("title") or item["url"])[:200],
                }
            )
    return out[:8]


async def _client_and_playbook(
    db: AsyncSession, client_id: Optional[int]
) -> tuple[Optional[Client], Optional[ClientPlaybook]]:
    if not client_id:
        return None, None
    client = await db.get(Client, client_id)
    playbook = await db.scalar(
        select(ClientPlaybook).where(ClientPlaybook.client_id == client_id)
    )
    return client, playbook


def _client_name(client: Optional[Client]) -> Optional[str]:
    if client is None:
        return None
    return (client.display_name or client.name or "").strip() or None


def _client_usable(client: Optional[Client]) -> bool:
    return bool(
        client is not None
        and client.deleted_at is None
        and client.merged_into_client_id is None
        and _client_name(client)
    )


async def _category_slug(db: AsyncSession, job: Job) -> Optional[str]:
    if not job.competence_category_id:
        return None
    return await db.scalar(
        select(CompetenceCategory.slug).where(
            CompetenceCategory.id == job.competence_category_id
        )
    )


async def role_stats(db: AsyncSession, role_id: int) -> dict[str, Any]:
    """Liczby z historii NEXUSA dla roli — BEZ stawek (decyzja 29.09.2026)."""
    jobs, clients = (
        await db.execute(
            select(func.count(Job.id), func.count(func.distinct(Job.client_id))).where(
                Job.role_profile_id == role_id
            )
        )
    ).one()
    hired_rows = (
        await db.execute(
            text(
                """
                SELECT NULLIF(btrim(COALESCE(c.experience->0->>'role', c.linkedin_current_title, '')), '') AS title
                  FROM analytics_first_milestones fm
                  JOIN jobs j ON j.id = fm.job_id
                  JOIN candidates c ON c.id = fm.candidate_id
                 WHERE fm.stage = 'hired' AND j.role_profile_id = :role_id
                """
            ),
            {"role_id": role_id},
        )
    ).all()
    hires = len(hired_rows)
    titles: list[dict[str, Any]] = []
    if hires >= MIN_HIRES_FOR_TITLES:
        counts: dict[str, int] = {}
        for (title,) in hired_rows:
            if title:
                counts[title[:80]] = counts.get(title[:80], 0) + 1
        titles = [
            {"title": t, "count": n}
            for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        ]
    return {
        "jobs": int(jobs or 0),
        "clients": int(clients or 0),
        "hires": hires,
        "hired_titles": titles,
    }


def role_payload(role: RoleProfile) -> dict[str, Any]:
    return {
        "id": role.id,
        "slug": role.slug,
        "name": role.name,
        "summary": role.summary,
        "example": role.example,
        "day_to_day": list(role.day_to_day or []),
        "candidate_questions": list(role.candidate_questions or []),
        "typical_skills": list(role.typical_skills or []),
        "sources": _sources(role.sources),
        "origin": role.origin,
        "status": role.status,
        "updated_at": role.updated_at,
    }


def term_payload(
    entry: dict[str, Any], row: Optional[PlainTerm], note: Optional[str]
) -> dict[str, Any]:
    ready = row is not None and row.status == "ready"
    return {
        "term_key": entry["term_key"],
        "display_name": (
            row.display_name if ready and row.display_name else entry["display_name"]
        ),
        "level": entry["level"],
        "level_label": entry["level_label"],
        "status": row.status if row is not None else "missing",
        "summary": row.summary if ready else None,
        "does": row.does if ready else None,
        "cv_hints": list(row.cv_hints or []) if ready else [],
        "confused_with": row.confused_with if ready else None,
        "in_this_project": note,
        "sources": _sources(row.sources) if ready else [],
        "origin": row.origin if row is not None else None,
    }


async def current_inputs(
    db: AsyncSession, job: Job
) -> tuple[
    dict[str, Any], Optional[Client], Optional[ClientPlaybook], Optional[RoleProfile]
]:
    client, playbook = await _client_and_playbook(db, job.client_id)
    role = (
        await db.get(RoleProfile, job.role_profile_id) if job.role_profile_id else None
    )
    inputs = job_brief.collect_inputs(
        job,
        client_name=_client_name(client),
        client_about=playbook.about_for_candidate if playbook else None,
        client_process=playbook.process_rules_md if playbook else None,
        role_name=role.name if role else None,
    )
    return inputs, client, playbook, role


async def build_view(
    db: AsyncSession,
    job: Job,
    *,
    can_refresh: bool,
    can_change_role: bool,
) -> dict[str, Any]:
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import model_for

    inputs, client, playbook, role = await current_inputs(db, job)
    brief = await db.get(JobPlainBrief, job.id)
    digest = job_brief.inputs_hash(inputs, model_for(AIFeatureKey.champion_draft))
    status = brief.status if brief else "none"
    stale = brief is None or brief.status == "none" or brief.inputs_hash != digest
    notes = dict((brief.term_notes or {}) if brief else {})
    entries = job_brief.job_terms(job)
    rows = await knowledge.terms_by_key(db, [e["term_key"] for e in entries])
    role_view = None
    if role is not None:
        role_view = {
            **role_payload(role),
            "assignment": job.role_profile_source or "auto",
            "stats": await role_stats(db, role.id),
        }
    client_view = None
    if client is not None:
        client_view = {
            "id": client.id,
            "name": _client_name(client),
            "about": (playbook.about_for_candidate or None) if playbook else None,
            "origin": (playbook.about_for_candidate_origin or "manual")
            if playbook and playbook.about_for_candidate
            else None,
            "sources": _sources(playbook.about_for_candidate_sources)
            if playbook
            else [],
        }
    ready = brief is not None and brief.status in ("ready", "failed")
    return {
        "job_id": job.id,
        "status": status,
        "stale": stale,
        "is_open": job.status == JobStatus.published,
        "can_refresh": can_refresh,
        "can_change_role": can_change_role,
        "generated_at": brief.generated_at if brief else None,
        "message": brief.message if brief else None,
        "one_liner": brief.one_liner if ready else None,
        "example": brief.example if ready else None,
        "day_to_day": list(brief.day_to_day or []) if ready else [],
        "pitch": brief.pitch if ready else None,
        "candidate_qa": list(brief.candidate_qa or []) if ready else [],
        "screening_plain": list(brief.screening_plain or []) if ready else [],
        "glossary": [
            term_payload(e, rows.get(e["term_key"]), notes.get(e["term_key"]))
            for e in entries
        ],
        "role": role_view,
        "client": client_view,
    }


# ── odświeżanie ─────────────────────────────────────────────────────────────


async def assign_role(
    db: AsyncSession, job: Job
) -> tuple[Optional[int], Optional[tuple[str, str, dict, list]]]:
    """Dopasowuje rolę. Zwraca (id roli, dane nowej roli do researchu albo None)."""
    if job.role_profile_source == "manual" and job.role_profile_id:
        return job.role_profile_id, None
    category = await _category_slug(db, job)
    roles = (
        await db.execute(
            select(RoleProfile.id, RoleProfile.match_rules).where(
                RoleProfile.status == "ready"
            )
        )
    ).all()
    title, skills = role_matcher.job_signals(job)
    best = role_matcher.best_role(
        [role_matcher.rules_of(rid, rules) for rid, rules in roles],
        title,
        skills,
        category,
    )
    if best is not None:
        if job.role_profile_id != best:
            job.role_profile_id = best
            job.role_profile_source = "auto"
            await db.commit()
        return best, None
    if job.role_profile_id:
        return job.role_profile_id, None
    name, rules, skill_list = role_matcher.rules_for_new_role(job, category)
    return None, (knowledge.slugify(name), name, rules, skill_list)


async def _research_role(
    db: AsyncSession,
    job_id: int,
    spec: tuple[str, str, dict, list],
    user_id: Optional[int],
) -> None:
    from app.services.plain_knowledge.research import research

    slug, name, rules, skills = spec
    if await knowledge.claim_role(db, slug, name, rules, skills):
        result = await research(db, "role", name, skills=skills, user_id=user_id)
        await knowledge.finish_role(db, slug, result)
    role_id = await db.scalar(select(RoleProfile.id).where(RoleProfile.slug == slug))
    if role_id is None:
        return
    job = await db.get(Job, job_id, with_for_update=True, populate_existing=True)
    if job is not None and not job.role_profile_id:
        job.role_profile_id = role_id
        job.role_profile_source = "auto"
    await db.commit()


async def _research_term(
    db: AsyncSession, key: str, display: str, user_id: Optional[int]
) -> None:
    from app.services.plain_knowledge.research import research

    if await knowledge.claim_term(db, key, display):
        result = await research(db, "term", display, user_id=user_id)
        await knowledge.finish_term(db, key, result)


async def _run_research(
    db: AsyncSession,
    tasks: list[tuple[str, Any]],
    job_id: int,
    client: Optional[tuple[int, str]],
    user_id: Optional[int],
) -> None:
    for kind, payload in tasks:
        try:
            if kind == "role":
                await _research_role(db, job_id, payload, user_id)
            elif kind == "term":
                await _research_term(db, payload[0], payload[1], user_id)
            elif kind == "client" and client is not None:
                await knowledge.fill_client_about(
                    db, client[0], client[1], user_id=user_id
                )
        except Exception as exc:  # noqa: BLE001 — AI to dodatek
            await db.rollback()
            logger.warning(
                "plain_knowledge research task failed: %s %s", kind, type(exc).__name__
            )


async def _background(
    job_id: int,
    tasks: list[tuple[str, Any]],
    client: Optional[tuple[int, str]],
    user_id: Optional[int],
) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await _run_research(db, tasks, job_id, client, user_id)
        job = await db.get(Job, job_id)
        if job is not None:
            inputs, *_ = await current_inputs(db, job)
            await job_brief.generate(db, job, inputs, user_id=user_id)


async def refresh(db: AsyncSession, job_id: int, *, user_id: Optional[int]) -> None:
    """Uzupełnia wiedzę i liczy teksty. Nie rzuca z powodu AI."""
    from app.core.tasks import spawn
    from app.services.plain_knowledge.research import enabled

    job = await db.get(Job, job_id)
    if job is None:
        return
    _role_id, new_role = await assign_role(db, job)
    job = await db.get(Job, job_id, populate_existing=True)
    tasks: list[tuple[str, Any]] = []
    if new_role is not None:
        tasks.append(("role", new_role))
    entries = job_brief.job_terms(job)
    rows = await knowledge.terms_by_key(db, [e["term_key"] for e in entries])
    for entry in entries:
        if knowledge.needs_research(rows.get(entry["term_key"])):
            tasks.append(("term", (entry["term_key"], entry["display_name"])))
    client, playbook = await _client_and_playbook(db, job.client_id)
    client_ref = (client.id, _client_name(client)) if _client_usable(client) else None
    if client_ref and knowledge.client_about_missing(playbook):
        tasks.append(("client", None))

    if tasks and enabled():
        now, later = tasks[:REQUEST_RESEARCH_BUDGET], tasks[REQUEST_RESEARCH_BUDGET:]
        await _run_research(db, now, job_id, client_ref, user_id)
        if later:
            spawn(
                _background(job_id, later, client_ref, user_id),
                label=f"plain_knowledge:{job_id}",
            )
    job = await db.get(Job, job_id, populate_existing=True)
    if job is None:
        return
    inputs, *_ = await current_inputs(db, job)
    await job_brief.generate(db, job, inputs, user_id=user_id)
