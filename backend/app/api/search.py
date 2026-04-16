from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.client import Client
from app.models.contact import Contact
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.api.deps import CurrentUser

router = APIRouter()


class CandidateSearchRequest(BaseModel):
    q: Optional[str] = None
    technologies: Optional[List[str]] = None
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None
    location: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    source: Optional[str] = None
    availability: Optional[str] = None  # "immediate", "2weeks", "1month", etc.
    stage: Optional[str] = None
    recruiter_id: Optional[int] = None
    page: int = 1
    page_size: int = 20


@router.post("/candidates")
async def advanced_candidate_search(
    body: CandidateSearchRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Advanced candidate search with filters and full-text search.
    POST /api/search/candidates
    Returns results with relevance scoring.
    """
    from sqlalchemy import func

    query = select(Candidate)
    filters = []

    # Full-text search across name, email, raw_cv_text
    if body.q:
        q = body.q.strip()
        full_text_filter = or_(
            Candidate.name.ilike(f"%{q}%"),
            Candidate.lastname.ilike(f"%{q}%"),
            Candidate.email.ilike(f"%{q}%"),
            Candidate.raw_cv_text.ilike(f"%{q}%"),
            Candidate.competence_category.ilike(f"%{q}%"),
            Candidate.ai_summary.ilike(f"%{q}%"),
        )
        filters.append(full_text_filter)

    # Location filter
    if body.location:
        filters.append(Candidate.location.ilike(f"%{body.location}%"))

    # Salary range filter
    if body.salary_min is not None:
        filters.append(Candidate.salary_expectation >= body.salary_min)
    if body.salary_max is not None:
        filters.append(Candidate.salary_expectation <= body.salary_max)

    # Source filter
    if body.source:
        filters.append(Candidate.source.ilike(f"%{body.source}%"))

    # Technologies/skills filter — search in skills JSONB
    if body.technologies:
        for tech in body.technologies:
            filters.append(
                or_(
                    Candidate.skills.cast(text("text")).ilike(f"%{tech}%"),
                    Candidate.tags.cast(text("text")).ilike(f"%{tech}%"),
                )
            )

    if filters:
        from sqlalchemy import and_

        query = query.where(and_(*filters))

    # Stage filter — join with pipeline stages
    if body.stage:
        try:
            stage_enum = PipelineStage(body.stage)
            stage_subq = (
                select(CandidateStage.candidate_id)
                .where(CandidateStage.stage == stage_enum)
                .distinct()
            )
            query = query.where(Candidate.id.in_(stage_subq))
        except ValueError:
            pass  # ignore invalid stage

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    # Pagination
    query = query.offset((body.page - 1) * body.page_size).limit(body.page_size)
    result = await db.execute(query)
    candidates = result.scalars().all()

    # Build results with simple relevance scoring
    items = []
    for c in candidates:
        score = 0
        if body.q:
            q_lower = body.q.lower()
            full_name = f"{c.name} {c.lastname}".lower()
            if q_lower in full_name:
                score += 10
            if c.email and q_lower in c.email.lower():
                score += 5
            if c.raw_cv_text and q_lower in c.raw_cv_text.lower():
                score += 3
            if c.competence_category and q_lower in c.competence_category.lower():
                score += 8

        if body.technologies:
            skills_text = str(c.skills or "").lower() + " " + str(c.tags or "").lower()
            for tech in body.technologies:
                if tech.lower() in skills_text:
                    score += 5

        items.append(
            {
                "id": c.id,
                "name": c.name,
                "lastname": c.lastname,
                "email": c.email,
                "phone": c.phone,
                "location": c.location,
                "status": c.status.value if c.status else None,
                "source": c.source,
                "competence_category": c.competence_category,
                "salary_expectation": c.salary_expectation,
                "salary_currency": c.salary_currency,
                "availability_date": c.availability_date.isoformat()
                if c.availability_date
                else None,
                "tags": c.tags,
                "skills": c.skills,
                "ai_summary": c.ai_summary,
                "avatar_url": c.avatar_url,
                "relevance_score": score,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
        )

    # Sort by relevance score (descending)
    items.sort(key=lambda x: x["relevance_score"], reverse=True)

    return {
        "total": total,
        "page": body.page,
        "page_size": body.page_size,
        "query": body.q,
        "filters_applied": {
            "technologies": body.technologies,
            "location": body.location,
            "salary_min": body.salary_min,
            "salary_max": body.salary_max,
            "source": body.source,
            "stage": body.stage,
        },
        "items": items,
    }


@router.get("/")
async def unified_search(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    entity: Optional[str] = Query(
        None, description="candidates|jobs|clients — filter by entity type"
    ),
):
    """
    Full-text search across candidates, jobs, and clients.
    Falls back to PostgreSQL ILIKE. For semantic search use /search/semantic.
    """
    results: dict[str, List[Any]] = {}

    if not entity or entity == "candidates":
        result = await db.execute(
            select(Candidate)
            .where(
                or_(
                    Candidate.name.ilike(f"%{q}%"),
                    Candidate.lastname.ilike(f"%{q}%"),
                    Candidate.email.ilike(f"%{q}%"),
                    Candidate.location.ilike(f"%{q}%"),
                )
            )
            .limit(10)
        )
        results["candidates"] = [
            {
                "id": c.id,
                "name": f"{c.name} {c.lastname}",
                "email": c.email,
                "status": c.status,
            }
            for c in result.scalars().all()
        ]

    if not entity or entity == "jobs":
        result = await db.execute(
            select(Job)
            .where(
                or_(
                    Job.title.ilike(f"%{q}%"),
                    Job.description.ilike(f"%{q}%"),
                )
            )
            .limit(10)
        )
        results["jobs"] = [
            {"id": j.id, "title": j.title, "status": j.status, "location": j.location}
            for j in result.scalars().all()
        ]

    if not entity or entity == "clients":
        result = await db.execute(
            select(Client)
            .where(
                or_(
                    Client.name.ilike(f"%{q}%"),
                    Client.industry.ilike(f"%{q}%"),
                )
            )
            .limit(10)
        )
        results["clients"] = [
            {"id": c.id, "name": c.name, "status": c.status}
            for c in result.scalars().all()
        ]

    return {"query": q, "results": results}


@router.get("/global")
async def global_search(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
):
    """
    Global live search — returns max 5 results per category (candidates, jobs, clients, contacts).
    Designed for the top search bar dropdown.
    GET /api/search/global?q=text
    """
    LIMIT = 5

    # Candidates
    cand_result = await db.execute(
        select(Candidate)
        .where(
            or_(
                Candidate.name.ilike(f"%{q}%"),
                Candidate.lastname.ilike(f"%{q}%"),
                Candidate.email.ilike(f"%{q}%"),
            )
        )
        .limit(LIMIT)
    )
    candidates = [
        {
            "id": c.id,
            "name": f"{c.name} {c.lastname}",
            "subtitle": c.email or c.competence_category or "",
            "url": f"/candidates/{c.id}",
        }
        for c in cand_result.scalars().all()
    ]

    # Jobs
    jobs_result = await db.execute(
        select(Job)
        .where(
            Job.title.ilike(f"%{q}%"),
        )
        .limit(LIMIT)
    )
    jobs_list = []
    for j in jobs_result.scalars().all():
        # Get client name via client_id
        client_name = ""
        if j.client_id:
            client_res = await db.execute(
                select(Client).where(Client.id == j.client_id)
            )
            client = client_res.scalar_one_or_none()
            if client:
                client_name = client.name
        jobs_list.append(
            {
                "id": j.id,
                "name": j.title,
                "subtitle": client_name or j.location or "",
                "url": f"/jobs/{j.id}",
            }
        )

    # Clients
    clients_result = await db.execute(
        select(Client)
        .where(
            or_(
                Client.name.ilike(f"%{q}%"),
                Client.industry.ilike(f"%{q}%"),
            )
        )
        .limit(LIMIT)
    )
    clients_list = [
        {
            "id": c.id,
            "name": c.name,
            "subtitle": c.industry or "",
            "url": "/clients",
        }
        for c in clients_result.scalars().all()
    ]

    # Contacts
    contacts_result = await db.execute(
        select(Contact)
        .where(
            or_(
                Contact.name.ilike(f"%{q}%"),
                Contact.email.ilike(f"%{q}%"),
            )
        )
        .limit(LIMIT)
    )
    contacts_list = [
        {
            "id": c.id,
            "name": c.name,
            "subtitle": c.email or c.position or "",
            "url": "/contacts",
        }
        for c in contacts_result.scalars().all()
    ]

    return {
        "query": q,
        "candidates": candidates,
        "jobs": jobs_list,
        "clients": clients_list,
        "contacts": contacts_list,
    }


class SemanticSearchRequest(BaseModel):
    query: str
    top_k: int = 20
    filters: Optional[dict] = None


@router.post("/semantic")
async def semantic_search(
    body: SemanticSearchRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Semantic candidate search using Voyage AI embeddings + Qdrant.
    POST /api/search/semantic
    Falls back to ILIKE text search when Qdrant/Voyage is unavailable.
    """
    from app.services.embedding_service import search_candidates_semantic

    q = body.query.strip()
    if not q:
        return {"query": q, "results": [], "total": 0, "search_type": "semantic"}

    # --- Semantic search via Qdrant ---
    hits = await search_candidates_semantic(q, top_k=body.top_k)

    if hits:
        candidate_ids = [h["candidate_id"] for h in hits]
        score_map = {h["candidate_id"]: h["score"] for h in hits}

        result = await db.execute(
            select(Candidate).where(Candidate.id.in_(candidate_ids))
        )
        candidates_by_id = {c.id: c for c in result.scalars().all()}

        results = []
        for cid in candidate_ids:
            c = candidates_by_id.get(cid)
            if not c:
                continue
            score = score_map.get(cid, 0.0)
            # Build a short highlight text
            highlight = ""
            if c.competence_category:
                highlight = c.competence_category
            elif c.ai_summary:
                highlight = c.ai_summary[:120]
            elif c.raw_cv_text:
                highlight = c.raw_cv_text[:120]

            results.append(
                {
                    "candidate": {
                        "id": c.id,
                        "name": c.name,
                        "lastname": c.lastname,
                        "email": c.email,
                        "phone": c.phone,
                        "location": c.location,
                        "status": c.status.value if c.status else None,
                        "competence_category": c.competence_category,
                        "salary_expectation": c.salary_expectation,
                        "salary_currency": c.salary_currency,
                        "availability_date": c.availability_date.isoformat()
                        if c.availability_date
                        else None,
                        "tags": c.tags,
                        "skills": c.skills,
                        "ai_summary": c.ai_summary,
                        "avatar_url": c.avatar_url,
                        "created_at": c.created_at.isoformat()
                        if c.created_at
                        else None,
                    },
                    "score": score,
                    "highlight": highlight,
                }
            )

        return {
            "query": q,
            "results": results,
            "total": len(results),
            "search_type": "semantic",
        }

    # --- Fallback: ILIKE text search ---
    fallback_result = await db.execute(
        select(Candidate)
        .where(
            or_(
                Candidate.name.ilike(f"%{q}%"),
                Candidate.lastname.ilike(f"%{q}%"),
                Candidate.email.ilike(f"%{q}%"),
                Candidate.competence_category.ilike(f"%{q}%"),
                Candidate.raw_cv_text.ilike(f"%{q}%"),
            )
        )
        .limit(body.top_k)
    )
    fallback_candidates = fallback_result.scalars().all()
    results = []
    for c in fallback_candidates:
        highlight = c.competence_category or (
            c.ai_summary[:120] if c.ai_summary else ""
        )
        results.append(
            {
                "candidate": {
                    "id": c.id,
                    "name": c.name,
                    "lastname": c.lastname,
                    "email": c.email,
                    "phone": c.phone,
                    "location": c.location,
                    "status": c.status.value if c.status else None,
                    "competence_category": c.competence_category,
                    "salary_expectation": c.salary_expectation,
                    "salary_currency": c.salary_currency,
                    "availability_date": c.availability_date.isoformat()
                    if c.availability_date
                    else None,
                    "tags": c.tags,
                    "skills": c.skills,
                    "ai_summary": c.ai_summary,
                    "avatar_url": c.avatar_url,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                },
                "score": None,
                "highlight": highlight,
            }
        )

    return {
        "query": q,
        "results": results,
        "total": len(results),
        "search_type": "text_fallback",
    }
