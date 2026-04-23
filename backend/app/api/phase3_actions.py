"""Phase 3 action endpoints — shortlist email + client proposal preview.

Lives in its own module (no `from __future__ import annotations`) so
Pydantic / FastAPI can resolve `body: SomeModel` parameters at request time
instead of seeing them as PEP-563 string forward refs (which makes FastAPI
treat the body as a query/form param and return 422).

Endpoints:
  POST /api/recommendations/send-candidate-shortlist-email
  POST /api/recommendations/prepare-client-proposal

Both endpoints are *preview-only* — they build the draft and return it. The
recruiter reviews/edit and submits via existing email tooling. Avoids the
need for a scheduled-send queue in v1.
"""

import logging
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.user import User
from app.schemas.shortlist_actions import (
    CandidateShortlistEmailRequest,
    ClientProposalRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Shortlist email ─────────────────────────────────────────────────────────


def _format_jobs_html(jobs: list[Job]) -> str:
    if not jobs:
        return "<p>—</p>"
    items: list[str] = []
    for j in jobs:
        bits: list[str] = []
        if j.location:
            bits.append(f"📍 {j.location}")
        if j.salary_min and j.salary_max:
            bits.append(f"💰 {j.salary_min:,} – {j.salary_max:,} PLN")
        if j.seniority:
            bits.append(f"🎯 {j.seniority.value}")
        meta = " · ".join(bits)
        items.append(
            f"<li><strong>{j.title}</strong>"
            + (
                f"<br><span style='color:#666;font-size:90%'>{meta}</span>"
                if meta
                else ""
            )
            + "</li>"
        )
    return "<ul style='padding-left:1.2em'>" + "".join(items) + "</ul>"


@router.post("/recommendations/send-candidate-shortlist-email")
@limiter.limit("10/minute")
async def send_candidate_shortlist_email(
    request: Request,
    body: CandidateShortlistEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cand = await db.scalar(
        select(Candidate).where(Candidate.id == body.candidate_id)
    )
    if not cand:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje")
    if not cand.email:
        raise HTTPException(
            status_code=400,
            detail=(
                "Kandydat nie ma adresu email — wpisz email na profilu i "
                "spróbuj ponownie."
            ),
        )
    if not body.job_ids:
        raise HTTPException(
            status_code=400, detail="Lista ofert nie może być pusta."
        )

    jobs_res = await db.execute(
        select(Job).where(
            Job.id.in_(body.job_ids), Job.status == JobStatus.published
        )
    )
    jobs = list(jobs_res.scalars().all())
    if not jobs:
        raise HTTPException(
            status_code=400,
            detail="Żadna z wybranych ofert nie jest opublikowana.",
        )

    subject = f"Mamy {len(jobs)} propozycji projektu dla Ciebie"
    intro = (
        f"Cześć {cand.name},\n\n"
        f"Mamy dla Ciebie {len(jobs)} aktualnie otwarte projekty, które "
        "wyglądają na dobre dopasowanie. Daj znać, czy któryś Cię "
        "interesuje — chętnie podeślę szczegóły i opowiem o kliencie.\n\n"
    )
    plain_jobs = "\n".join(
        f"- {j.title} ({j.location or 'brak lokalizacji'})" for j in jobs
    )
    text_body = intro + plain_jobs + "\n\nPozdrawiam,\nZespół B2B.net\n"
    html_body = (
        f"<p>Cześć {cand.name},</p>"
        f"<p>Mamy dla Ciebie <strong>{len(jobs)}</strong> aktualnie otwarte "
        "projekty, które wyglądają na dobre dopasowanie. Daj znać, czy "
        "któryś Cię interesuje — chętnie podeślę szczegóły.</p>"
        + _format_jobs_html(jobs)
        + "<p>Pozdrawiam,<br>Zespół B2B.net</p>"
    )

    return {
        "candidate_id": cand.id,
        "to": cand.email,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
        "job_count": len(jobs),
    }


# ── Client proposal ─────────────────────────────────────────────────────────


def _calc_experience_years(experience: list) -> int:
    """Inline equivalent of cv_generator._calc_experience_years."""
    total_days = 0
    for e in experience:
        if not isinstance(e, dict):
            continue
        start = e.get("start") or e.get("from")
        end = e.get("end") or e.get("to") or _date.today().isoformat()
        try:
            s = _date.fromisoformat(str(start)[:10])
            en = _date.fromisoformat(str(end)[:10])
            total_days += max(0, (en - s).days)
        except (ValueError, TypeError):
            continue
    return round(total_days / 365.25) if total_days else 0


def _build_client_proposal_email(
    candidate: Candidate, job: Job, blind_summary: dict
) -> dict:
    role = job.title or "tej roli"
    yrs = blind_summary.get("experience_years")
    edu = blind_summary.get("education_level") or "—"
    skills = ", ".join(blind_summary.get("skills_summary") or []) or "—"
    languages = ", ".join(blind_summary.get("languages") or []) or "—"
    cc = (
        blind_summary.get("competence_category")
        or candidate.competence_category
        or "—"
    )

    plain = (
        "Cześć,\n\n"
        f"Mamy konsultanta, który pasuje do otwartej u Was roli „{role}\".\n\n"
        "Profil (anonimowy):\n"
        f"• Doświadczenie: {yrs} lat\n"
        f"• Wykształcenie: {edu}\n"
        f"• Kompetencje: {cc}\n"
        f"• Kluczowe technologie: {skills}\n"
        f"• Języki: {languages}\n\n"
        "Daj znać, czy chcecie umówić rozmowę — w odpowiedzi prześlemy "
        "pełne CV.\n\n"
        "Pozdrawiam,\nZespół B2B.net\n"
    )
    html = (
        "<p>Cześć,</p>"
        f"<p>Mamy konsultanta, który pasuje do otwartej u Was roli "
        f"<strong>„{role}\"</strong>.</p>"
        "<p><strong>Profil (anonimowy):</strong></p>"
        "<ul>"
        f"<li>Doświadczenie: <strong>{yrs} lat</strong></li>"
        f"<li>Wykształcenie: {edu}</li>"
        f"<li>Kompetencje: {cc}</li>"
        f"<li>Kluczowe technologie: {skills}</li>"
        f"<li>Języki: {languages}</li>"
        "</ul>"
        "<p>Daj znać, czy chcecie umówić rozmowę — w odpowiedzi prześlemy "
        "pełne CV.</p>"
        "<p>Pozdrawiam,<br>Zespół B2B.net</p>"
    )
    subject = f"Propozycja kandydata na rolę „{role}\""
    return {"subject": subject, "text_body": plain, "html_body": html}


@router.post("/recommendations/prepare-client-proposal")
@limiter.limit("10/minute")
async def prepare_client_proposal(
    request: Request,
    body: ClientProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cand = await db.scalar(
        select(Candidate).where(Candidate.id == body.candidate_id)
    )
    if not cand:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje")
    job = await db.scalar(select(Job).where(Job.id == body.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Oferta nie istnieje")

    skills = cand.skills or []
    skills_summary = [
        s.get("name", "")
        for s in skills
        if isinstance(s, dict) and s.get("name")
    ]
    if not skills_summary and isinstance(skills, list):
        skills_summary = [str(s) for s in skills if isinstance(s, str)]

    experience = cand.experience or []
    experience_years = (
        cand.years_it_experience
        if cand.years_it_experience is not None
        else _calc_experience_years(experience)
    )

    education = cand.education or []
    education_level = "—"
    if isinstance(education, list) and education:
        first = education[0]
        if isinstance(first, dict):
            education_level = first.get("degree") or first.get("level") or "—"

    languages_list = cand.languages or []
    languages: list[str] = []
    for lang in languages_list:
        if isinstance(lang, dict) and lang.get("lang"):
            level = lang.get("level")
            languages.append(
                f"{lang['lang']} — {level}" if level else lang["lang"]
            )

    blind = {
        "skills_summary": skills_summary,
        "experience_years": experience_years,
        "education_level": education_level,
        "languages": languages,
        "ai_summary": cand.ai_summary,
        "competence_category": cand.competence_category,
    }

    draft = _build_client_proposal_email(cand, job, blind)

    return {
        "candidate_id": cand.id,
        "job_id": job.id,
        "client_id": job.client_id,
        "blind_summary": blind,
        "draft_email": draft,
    }
