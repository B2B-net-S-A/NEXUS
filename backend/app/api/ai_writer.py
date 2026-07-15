"""
AI Job Writer — generuje ogłoszenie o pracę na podstawie danych wejściowych.
Obsługuje dwa endpointy:
  - POST /api/ai/generate-job-description  (istniejący, template-based)
  - POST /api/ai/generate-job              (AI; jawny błąd przy awarii)
  - POST /api/ai/generate-job/template     (jawna akcja szablonowa)
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.ai import AIError, AIRequest, ai_gateway
from app.models.ai_feature import AIFeatureKey
from app.models.user import User
from app.models.client import Client
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory

logger = logging.getLogger(__name__)
router = APIRouter()


class JobDescriptionRequest(BaseModel):
    title: str
    client_name: Optional[str] = None
    requirements: Optional[str] = None
    seniority: Optional[str] = None  # junior, mid, senior, lead


class JobDescriptionResponse(BaseModel):
    description: str
    title: str


SENIORITY_LABELS = {
    "junior": "Junior",
    "mid": "Mid",
    "senior": "Senior",
    "lead": "Lead / Tech Lead",
    "": "",
}

SENIORITY_EXPERIENCE = {
    "junior": "1–2 lat",
    "mid": "3–5 lat",
    "senior": "5+ lat",
    "lead": "7+ lat",
    "": "kilku lat",
}


def _parse_requirements(requirements_text: str) -> list[str]:
    """Parsuje wymagania z tekstu — lista punktów."""
    items = []
    for line in requirements_text.splitlines():
        line = line.strip().lstrip("•-–*·").strip()
        if line and len(line) > 2:
            items.append(line)
    return items


def _parse_selling_points(content: str) -> list[str]:
    items = []
    for line in content.splitlines():
        line = line.strip().lstrip("•-–*·").strip()
        if line:
            items.append(line)
    return items


@router.post("/ai/generate-job-description", response_model=JobDescriptionResponse)
async def generate_job_description(
    request: JobDescriptionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    title = request.title.strip()
    client_name = (request.client_name or "nasz klient").strip()
    seniority = (request.seniority or "").lower().strip()
    requirements_text = (request.requirements or "").strip()

    seniority_label = SENIORITY_LABELS.get(seniority, seniority)
    seniority_exp = SENIORITY_EXPERIENCE.get(seniority, "kilku lat")

    full_title = f"{seniority_label} {title}".strip() if seniority_label else title

    # Try to find client in DB to get selling points
    selling_points: list[str] = []
    if request.client_name:
        client_result = await db.execute(
            select(Client).where(Client.name.ilike(f"%{request.client_name}%"))
        )
        client = client_result.scalar_one_or_none()
        if client:
            sp_result = await db.execute(
                select(ClientKnowledge).where(
                    ClientKnowledge.client_id == client.id,
                    ClientKnowledge.category == KnowledgeCategory.selling_points,
                )
            )
            sp_entries = sp_result.scalars().all()
            for entry in sp_entries:
                selling_points.extend(_parse_selling_points(entry.content))

    # Parse requirements
    req_items = _parse_requirements(requirements_text) if requirements_text else []

    # Default selling points if none found
    if not selling_points:
        selling_points = [
            "Stabilne zatrudnienie na podstawie kontraktu B2B lub umowy o pracę",
            "Praca hybrydowa lub zdalna",
            "Dostęp do nowoczesnych technologii i ciekawych projektów",
            "Przyjazna atmosfera i wsparcie merytoryczne zespołu",
            "Możliwości rozwoju zawodowego i finansowania szkoleń",
        ]

    # ── BUILD DESCRIPTION ────────────────────────────────────────────────────

    sections = []

    # 1. INTRO
    intro = f"""## {full_title}

Dla naszego klienta — **{client_name}** — poszukujemy doświadczonego specjalisty na stanowisko **{full_title}**.
Dołącz do dynamicznego zespołu i rozwijaj swoją karierę w środowisku, które stawia na jakość, innowację i ciągły rozwój.
Szukamy osoby z co najmniej {seniority_exp} doświadczenia, gotowej do podjęcia nowych wyzwań."""

    sections.append(intro)

    # 2. RESPONSIBILITIES
    if req_items:
        responsibilities = ["## Zakres obowiązków\n"]
        for item in req_items[:8]:
            responsibilities.append(f"- {item}")
        sections.append("\n".join(responsibilities))

    # 3. REQUIREMENTS
    if req_items:
        requirements_section = ["\n## Wymagania\n"]
        for item in req_items[:10]:
            requirements_section.append(f"- {item}")

        # Add seniority-based defaults
        if seniority in ("senior", "lead"):
            requirements_section.append(
                "- Doświadczenie w mentoringu i wsparciu juniorów"
            )
        if seniority == "lead":
            requirements_section.append(
                "- Umiejętności przywódcze i prowadzenia zespołu technicznego"
            )
            requirements_section.append(
                "- Doświadczenie w architekturze systemów i podejmowaniu decyzji technicznych"
            )

        requirements_section.append("- Dobra znajomość języka angielskiego (min. B2)")
        requirements_section.append(
            "- Umiejętność pracy w zwinnym środowisku (Agile/Scrum)"
        )
        sections.append("\n".join(requirements_section))
    else:
        requirements_section = f"""\n## Wymagania

- Minimum {seniority_exp} doświadczenia na podobnym stanowisku
- Bardzo dobra znajomość wymaganych technologii
- Umiejętność samodzielnej pracy i proaktywne podejście
- Dobra znajomość języka angielskiego (min. B2)
- Doświadczenie w środowisku Agile/Scrum"""
        sections.append(requirements_section)

    # 4. OFERUJEMY (selling points)
    oferujemy = ["\n## Co oferujemy?\n"]
    for sp in selling_points[:8]:
        oferujemy.append(f"- {sp}")
    sections.append("\n".join(oferujemy))

    # 5. APPLICATION
    application = f"""\n## Jak aplikować?

Jeśli jesteś zainteresowany/a tą ofertą i spełniasz powyższe wymagania, wyślij swoje CV na adres rekrutacja@b2bnet.pl z tytułem **\"{full_title}\"**.

Skontaktujemy się z wybranymi kandydatami w ciągu 3 dni roboczych.

*Rekrutacja prowadzona przez B2B.net S.A. — IT Talent Solutions*"""
    sections.append(application)

    full_description = "\n".join(sections)

    return JobDescriptionResponse(
        description=full_description,
        title=full_title,
    )


# ── New: AI Generate Job (structured, Claude or mock) ─────────────────────────


class GeneratedSalary(BaseModel):
    """Salary facts supplied by the user, never guessed by the model."""

    model_config = ConfigDict(extra="forbid")

    min: Optional[int] = Field(default=None, ge=0)
    max: Optional[int] = Field(default=None, ge=0)
    currency: Optional[str] = None
    period: Optional[Literal["hour", "day", "month", "year"]] = None
    employment_type: Optional[Literal["b2b", "uop", "uz", "other"]] = None

    @model_validator(mode="after")
    def validate_range(self) -> "GeneratedSalary":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("salary.min cannot exceed salary.max")
        if (self.min is not None or self.max is not None) and not (
            self.currency and self.period and self.employment_type
        ):
            raise ValueError("salary units are required when an amount is present")
        return self


class GenerateJobRequest(BaseModel):
    title: str
    client: Optional[str] = None
    seniority: Optional[str] = None  # junior, mid, senior, lead
    skills: List[str] = Field(default_factory=list)
    description_hint: Optional[str] = None
    benefits: List[str] = Field(default_factory=list)
    salary: Optional[GeneratedSalary] = None


class GenerateJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    requirements: str
    nice_to_have: str
    benefits: str
    salary: Optional[GeneratedSalary] = None
    generation_source: Literal["ai", "template"]
    # Deprecated for one release. It is derived only from structured salary.
    salary_range_suggestion: str = ""


async def _generate_with_claude(
    request: GenerateJobRequest, *, user_id: int
) -> GenerateJobResponse:
    """Generate through the central gateway and enforce the response schema."""
    seniority_label = request.seniority or "senior"
    skills_str = ", ".join(request.skills) if request.skills else "nie podano"
    benefits_str = ", ".join(request.benefits) if request.benefits else "nie podano"
    client_name = request.client or "nasz klient"

    prompt = f"""Wygeneruj profesjonalne ogłoszenie o pracę w języku polskim dla stanowiska:

Tytuł: {seniority_label.title()} {request.title}
Klient: {client_name}
Poziom: {seniority_label}
Wymagane technologie/umiejętności: {skills_str}
Dodatkowy kontekst: {request.description_hint or "brak"}
Potwierdzone benefity: {benefits_str}
Potwierdzone wynagrodzenie: {request.salary.model_dump_json() if request.salary else "brak"}

Zwróć WYŁĄCZNIE poprawny JSON (bez markdown, bez komentarzy) w tej dokładnej strukturze:
{{
  "title": "pełny tytuł stanowiska",
  "description": "2-3 atrakcyjne zdania o roli i firmie",
  "requirements": "lista wymagań w formacie markdown z myślnikami, minimum 6 punktów",
  "nice_to_have": "lista dodatkowych atutów z myślnikami, 3-4 punkty",
  "benefits": "wyłącznie benefity podane w kontekście; pusty tekst jeśli ich nie podano",
  "salary": {request.salary.model_dump_json() if request.salary else "null"},
  "generation_source": "ai",
  "salary_range_suggestion": ""
}}"""

    def validate_output(value: object) -> GenerateJobResponse:
        output = GenerateJobResponse.model_validate(value)
        if output.generation_source != "ai":
            raise ValueError("AI endpoint returned a non-AI generation source")
        if output.salary != request.salary:
            raise ValueError("AI changed or invented salary")
        expected_benefits = {item.strip() for item in request.benefits if item.strip()}
        if not expected_benefits and output.benefits.strip():
            raise ValueError("AI invented benefits")
        if expected_benefits and not all(
            benefit in output.benefits for benefit in expected_benefits
        ):
            raise ValueError("AI omitted a confirmed benefit")
        output.salary_range_suggestion = _legacy_salary_text(output.salary)
        return output

    result = await ai_gateway.call(
        AIRequest(
            feature=AIFeatureKey.job_writer,
            user_id=user_id,
            subject_type="job_draft",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Nie wymyślaj stawek, benefitów, lokalizacji ani warunków. "
                        "Powtarzaj tylko fakty z wejścia i zwróć wyłącznie JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            prompt_version="job_writer_v2",
            schema_version="job_writer_response_v2",
            structured_validator=validate_output,
            pii=True,
        )
    )
    return result.content


def _legacy_salary_text(salary: Optional[GeneratedSalary]) -> str:
    """One-release compatibility field derived from structured salary only."""
    if salary is None or (salary.min is None and salary.max is None):
        return ""
    amounts = (
        f"{salary.min}–{salary.max}"
        if salary.min is not None and salary.max is not None
        else str(salary.min if salary.min is not None else salary.max)
    )
    return f"{amounts} {salary.currency} / {salary.period} ({salary.employment_type})"


def _generate_mock(request: GenerateJobRequest) -> GenerateJobResponse:
    """Explicit template action; never an automatic AI fallback."""
    seniority = (request.seniority or "senior").lower()
    title = request.title.strip()
    client_name = request.client or "nasz klient"

    seniority_labels = {
        "junior": "Junior",
        "mid": "Mid",
        "senior": "Senior",
        "lead": "Lead",
    }
    seniority_exp = {
        "junior": "1–2 lat",
        "mid": "3–5 lat",
        "senior": "5+ lat",
        "lead": "7+ lat",
    }

    seniority_label = seniority_labels.get(seniority, "Senior")
    exp = seniority_exp.get(seniority, "5+ lat")
    full_title = f"{seniority_label} {title}"

    skills = request.skills or []
    skills_md = (
        "\n".join(f"- {s}" for s in skills)
        if skills
        else "- Wymagane technologie (uzupełnij)"
    )

    extra_reqs = ""
    if seniority in ("senior", "lead"):
        extra_reqs += "\n- Doświadczenie w mentoringu juniorów"
    if seniority == "lead":
        extra_reqs += "\n- Umiejętność prowadzenia zespołu technicznego\n- Doświadczenie w projektowaniu architektury"

    description = (
        f"Dla {client_name} szukamy doświadczonego {full_title}. "
        f"Dołącz do dynamicznego zespołu i realizuj ambitne projekty technologiczne. "
        f"Szukamy osoby z co najmniej {exp} doświadczenia, gotowej na nowe wyzwania."
    )

    hint = request.description_hint
    if hint:
        description += f" {hint}"

    requirements = f"{skills_md}{extra_reqs}\n- Dobra znajomość języka angielskiego (min. B2)\n- Doświadczenie z Agile/Scrum"

    nice_to_have = (
        "- Doświadczenie w pracy z dużymi systemami\n"
        "- Znajomość DevOps / CI/CD\n"
        "- Certyfikaty branżowe\n"
        "- Doświadczenie w pracy zdalnej"
    )

    benefits = (
        "\n".join(f"- {item}" for item in request.benefits)
        if request.benefits
        else "- Uzupełnij benefity potwierdzone przez klienta"
    )

    return GenerateJobResponse(
        title=full_title,
        description=description,
        requirements=requirements,
        nice_to_have=nice_to_have,
        benefits=benefits,
        salary=request.salary,
        generation_source="template",
        salary_range_suggestion=_legacy_salary_text(request.salary),
    )


@router.post("/ai/generate-job", response_model=GenerateJobResponse)
async def generate_job(
    request: GenerateJobRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    POST /api/ai/generate-job
    Generates a structured job description through the versioned AI gateway.
    Failures are explicit; this endpoint never returns a hidden template.
    """
    try:
        result = await _generate_with_claude(request, user_id=current_user.id)
        logger.info("job_writer generation succeeded source=ai")
        return result
    except AIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "reason": str(exc)},
        ) from exc


@router.post("/ai/generate-job/template", response_model=GenerateJobResponse)
async def generate_job_template(
    request: GenerateJobRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a clearly labelled template only after an explicit user action."""
    del current_user
    return _generate_mock(request)
