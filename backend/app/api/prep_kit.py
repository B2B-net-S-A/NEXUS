"""
AI Prep Kit Generator — generuje zestaw przygotowawczy dla kandydata do rozmowy.
Aggregates data from DB: Job, Client, ClientKnowledge, Candidate, ScreeningNotes.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.candidate_access import CandidatePIIAccess
from app.api.deps import get_db
from app.models.job import Job
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_note import ScreeningNote
from app.services.client_access import (
    assert_client_exists,
    deny,
    resolve_client_access,
)
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.question_suggestions import suggest_questions_for_prep

router = APIRouter()


class PrepKitRequest(BaseModel):
    job_id: int
    candidate_id: int


class PrepKitResponse(BaseModel):
    client_overview: str
    likely_questions: list[str]
    # Rozszerzone pytania z metadata (source_tier, cosine_score, ideal_answer...).
    # Non-breaking: stare frontendy używają `likely_questions` (list[str]).
    likely_questions_meta: list[dict] = []
    candidate_strengths: list[str]
    candidate_gaps: list[str]
    selling_points: list[str]
    recommended_strategy: str


def _parse_list_content(content: str) -> list[str]:
    """Parsuje treść knowledge entry — rozdziela po nowych liniach lub myślnikach."""
    items = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        # Remove leading bullet chars
        line = line.lstrip("•-–*·").strip()
        if line:
            items.append(line)
    return items if items else [content.strip()]


def _salary_info_for_overview(job: Job, *, include_finance: bool = False) -> str:
    """Format job budget only for callers with the explicit finance capability."""

    if not include_finance:
        return ""
    if job.salary_min and job.salary_max:
        return (
            f" Widełki wynagrodzenia: {job.salary_min:,}–{job.salary_max:,} PLN/mies."
        )
    if job.salary_min:
        return f" Wynagrodzenie od {job.salary_min:,} PLN/mies."
    if job.salary_max:
        return f" Wynagrodzenie do {job.salary_max:,} PLN/mies."
    return ""


@router.post("/prep-kit/generate", response_model=PrepKitResponse)
async def generate_prep_kit(
    request: PrepKitRequest,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    # ── Fetch Job ────────────────────────────────────────────────────────────
    job_result = await db.execute(select(Job).where(Job.id == request.job_id))
    job: Optional[Job] = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")

    # The legacy client-access resolver deliberately grants every Delivery Lead
    # organization-wide access. Dashboard/RBAC v2 uses the authoritative
    # DeliveryLeadClientAssignment boundary instead, including jobs without a
    # client (which are outside a plain DL's scope).
    assert_delivery_lead_client_visible(
        job.client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )

    # ── Fetch Candidate ──────────────────────────────────────────────────────
    cand_result = await db.execute(
        select(Candidate).where(Candidate.id == request.candidate_id)
    )
    candidate: Optional[Candidate] = cand_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Nie znaleziono kandydata")

    # ── Verify candidate is in pipeline ─────────────────────────────────────
    stage_result = await db.execute(
        select(CandidateStage).where(
            CandidateStage.candidate_id == request.candidate_id,
            CandidateStage.job_id == request.job_id,
        )
    )
    stages = stage_result.scalars().all()

    # ── Per-client containment (M1B-SEC-01) ─────────────────────────────────
    # Everything below that is client-specific — the overview (tech_stack /
    # culture / general), selling_points and the Tier-3 interview questions —
    # is derived from ClientKnowledge for job.client_id. Gate it behind the
    # same per-client access already enforced on GET /clients/{id}/knowledge,
    # so a recruiter assigned only to client A cannot pass client B's job_id
    # and read B's private knowledge (cross-team BOLA). The candidate-side data
    # stays gated by the CandidatePIIAccess role dependency above.
    if job.client_id:
        await assert_client_exists(db, job.client_id)
        access = await resolve_client_access(db, current_user, job.client_id)
        if not access.can_view_knowledge:
            raise deny("brak dostępu do wiedzy tego klienta")

    # ── Fetch Client ──────────────────────────────────────────────────────────
    client: Optional[Client] = None
    if job.client_id:
        client_result = await db.execute(
            select(Client).where(Client.id == job.client_id)
        )
        client = client_result.scalar_one_or_none()

    # ── Fetch Client Knowledge ─────────────────────────────────────────────
    knowledge_entries: list[ClientKnowledge] = []
    if job.client_id:
        k_result = await db.execute(
            select(ClientKnowledge).where(ClientKnowledge.client_id == job.client_id)
        )
        knowledge_entries = k_result.scalars().all()

    # ── Fetch Screening Notes ─────────────────────────────────────────────
    sn_result = await db.execute(
        select(ScreeningNote)
        .where(ScreeningNote.candidate_id == request.candidate_id)
        .order_by(ScreeningNote.created_at.desc())
    )
    screening_notes = sn_result.scalars().all()

    # ── BUILD PREP KIT ───────────────────────────────────────────────────────

    # 1. CLIENT OVERVIEW
    client_name = client.name if client else "Klient"
    client_industry = getattr(client, "industry", None) or "IT"
    job_remote = {
        "onsite": "praca stacjonarna",
        "hybrid": "tryb hybrydowy",
        "remote": "praca zdalna",
    }.get(job.remote_policy.value if job.remote_policy else "hybrid", "tryb hybrydowy")

    salary_info = _salary_info_for_overview(
        job,
        include_finance=user_has_capability(
            current_user, AnalyticsCapability.VIEW_FINANCE
        ),
    )

    tech_parts = []
    culture_parts = []
    for entry in knowledge_entries:
        if entry.category == KnowledgeCategory.tech_stack:
            tech_parts.extend(_parse_list_content(entry.content))
        elif entry.category == KnowledgeCategory.culture:
            culture_parts.extend(_parse_list_content(entry.content))
        elif entry.category == KnowledgeCategory.general:
            culture_parts.append(entry.content.strip())

    tech_summary = ", ".join(tech_parts[:5]) if tech_parts else ""
    culture_summary = " ".join(culture_parts[:2]) if culture_parts else ""

    overview_lines = [
        f"{client_name} — firma z branży {client_industry}.",
        f"Rekrutacja na stanowisko: {job.title}.",
        f"Model pracy: {job_remote}.{salary_info}",
    ]
    if tech_summary:
        overview_lines.append(f"Stack technologiczny: {tech_summary}.")
    if job.description:
        desc_short = job.description[:300].strip()
        if len(job.description) > 300:
            desc_short += "..."
        overview_lines.append(f"Opis roli: {desc_short}")
    if culture_summary:
        overview_lines.append(f"Kultura firmy: {culture_summary}")

    client_overview = "\n".join(overview_lines)

    # 2. LIKELY QUESTIONS — 4-tier waterfall (pinned → legacy → similar jobs →
    # client knowledge → auto-gen). Dokumentacja: question_suggestions.py.
    suggestions = await suggest_questions_for_prep(db=db, job=job, target_count=10)
    likely_questions_meta = [s.to_dict() for s in suggestions[:10]]
    likely_questions = [s["text"] for s in likely_questions_meta]

    # 3. CANDIDATE STRENGTHS
    strengths = []

    # From skills
    skills = candidate.skills or []
    if isinstance(skills, list):
        for sk in skills[:6]:
            if isinstance(sk, dict):
                skill_name = sk.get("name", "")
                level = sk.get("level", "")
                years = sk.get("years", "")
                if skill_name:
                    parts = [skill_name]
                    if level:
                        parts.append(f"poziom {level}")
                    if years:
                        parts.append(f"{years} lat doświadczenia")
                    strengths.append(", ".join(parts))
            elif isinstance(sk, str):
                strengths.append(sk)

    # From experience
    experience = candidate.experience or []
    if isinstance(experience, list) and experience:
        latest = experience[0] if isinstance(experience[0], dict) else None
        if latest:
            role = latest.get("role", "")
            company = latest.get("company", "")
            if role and company:
                strengths.append(f"Ostatnio: {role} @ {company}")

    # From screening notes — verified skills (confirmed)
    for sn in screening_notes[:2]:
        verified = sn.verified_skills or []
        if isinstance(verified, list):
            for skill in verified:
                if isinstance(skill, dict) and skill.get("level") == "confirmed":
                    strengths.append(
                        f"{skill.get('skill', '')} (potwierdzone screeningiem)"
                    )

    # Competence category
    if candidate.competence_category:
        strengths.append(f"Specjalizacja: {candidate.competence_category}")

    # Languages
    langs = candidate.languages or []
    if isinstance(langs, list) and langs:
        lang_strs = []
        for lang in langs[:3]:
            if isinstance(lang, dict):
                lang_strs.append(f"{lang.get('lang', '')} ({lang.get('level', '')})")
        if lang_strs:
            strengths.append(f"Języki: {', '.join(lang_strs)}")

    if not strengths:
        strengths = ["Brak szczegółowych danych profilu — uzupełnij profil kandydata"]

    strengths = strengths[:8]

    # 4. CANDIDATE GAPS
    gaps = []

    # Check required technologies from job vs candidate skills
    candidate_skill_names = set()
    for sk in skills if isinstance(skills, list) else []:
        if isinstance(sk, dict):
            candidate_skill_names.add(sk.get("name", "").lower())
        elif isinstance(sk, str):
            candidate_skill_names.add(sk.lower())

    # From tech stack knowledge
    for tech in tech_parts[:5]:
        if tech and tech.lower() not in candidate_skill_names:
            gaps.append(f"Brak {tech} w profilu — może być pytanie")

    # From screening red_flags
    for sn in screening_notes[:2]:
        if sn.red_flags:
            gaps.append(f"Red flag ze screeningu: {sn.red_flags[:100]}")
        verified = sn.verified_skills or []
        for sk in verified if isinstance(verified, list) else []:
            if isinstance(sk, dict) and sk.get("level") == "none":
                gaps.append(f"Brak umiejętności: {sk.get('skill', '')}")

    if not gaps:
        gaps = ["Brak zidentyfikowanych luk — profil pasuje do wymagań"]

    gaps = gaps[:6]

    # 5. SELLING POINTS
    selling_points = []
    for entry in knowledge_entries:
        if entry.category == KnowledgeCategory.selling_points:
            selling_points.extend(_parse_list_content(entry.content))

    # Add job-specific selling points
    if job.remote_policy and job.remote_policy.value == "remote":
        selling_points.append("W pełni zdalna praca")
    elif job.remote_policy and job.remote_policy.value == "hybrid":
        selling_points.append("Tryb hybrydowy")

    if salary_info:
        selling_points.append(f"Konkurencyjne wynagrodzenie — {salary_info.strip()}")

    if not selling_points:
        selling_points = [
            "Stabilne środowisko pracy",
            "Możliwości rozwoju zawodowego",
            "Praca z nowoczesnymi technologiami",
        ]

    selling_points = selling_points[:8]

    # 6. RECOMMENDED STRATEGY
    strategy_parts = []

    # Based on screening motivation
    motivations = []
    for sn in screening_notes[:2]:
        if sn.motivation_primary:
            motivations.append(sn.motivation_primary.value)
        if sn.motivation_secondary:
            motivations.append(sn.motivation_secondary.value)

    motivation_strategy = {
        "money": "Podkreślić widełki finansowe i możliwości wzrostu wynagrodzenia",
        "growth": "Pokazać ścieżkę kariery i możliwości awansu technicznego",
        "project": "Opisać ciekawe wyzwania projektowe i innowacyjność",
        "team": "Opowiedzieć o kulturze zespołu i atmosferze pracy",
        "work_mode": "Podkreślić elastyczność pracy i tryb hybrydowy/zdalny",
        "stability": "Zaakcentować stabilność firmy i długoterminowe kontrakty",
        "technology": "Skupić się na nowoczesnym stacku i ekscytujących technologiach",
        "location": "Omówić lokalizację biura i opcje dojazdu",
    }

    for mot in motivations[:2]:
        if mot in motivation_strategy:
            strategy_parts.append(motivation_strategy[mot])

    # Based on latest stage
    if stages:
        latest_stage = max(stages, key=lambda s: s.moved_at)
        stage_strategies = {
            "screening": "Na etapie screeningu — zbadać motywację i dopasowanie kulturowe",
            "interview": "Kandydat jest na etapie rozmowy — przygotować konkretne pytania techniczne",
            "technical": "Etap techniczny — skupić się na weryfikacji kompetencji hard skills",
            "offer": "Etap oferty — mieć gotową argumentację negocjacyjną",
        }
        stage_val = (
            latest_stage.stage.value
            if hasattr(latest_stage.stage, "value")
            else str(latest_stage.stage)
        )
        if stage_val in stage_strategies:
            strategy_parts.append(stage_strategies[stage_val])

    # Check counteroffer risk
    for sn in screening_notes[:1]:
        if sn.counteroffer_risk and sn.counteroffer_risk.value == "high":
            strategy_parts.append(
                "⚠️ Wysokie ryzyko counteroffer — wzmocnić argumenty i przyspieszyć decyzję"
            )

    if not strategy_parts:
        strategy_parts = [
            f"Zaprezentować kandydata jako dopasowanego do roli {job.title}",
            "Podkreślić kluczowe umiejętności pasujące do wymagań klienta",
            "Przygotować odpowiedzi na pytania o doświadczenie z wymaganymi technologiami",
        ]

    recommended_strategy = ". ".join(strategy_parts[:4]) + "."

    return PrepKitResponse(
        client_overview=client_overview,
        likely_questions=likely_questions,
        likely_questions_meta=likely_questions_meta,
        candidate_strengths=strengths,
        candidate_gaps=gaps,
        selling_points=selling_points,
        recommended_strategy=recommended_strategy,
    )
