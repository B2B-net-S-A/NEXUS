"""
AI Job Writer — generuje ogłoszenie o pracę na podstawie danych wejściowych.
Obsługuje dwa endpointy:
  - POST /api/ai/generate-job-description  (istniejący, template-based)
  - POST /api/ai/generate-job              (nowy, integracja z Claude API lub mock)
"""

import json
import os
import logging
from typing import Literal, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, get_db
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.client import Client
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_for

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


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
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
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


class GenerateJobRequest(BaseModel):
    title: str
    client: Optional[str] = None
    seniority: Optional[str] = None  # junior, mid, senior, lead
    skills: Optional[List[str]] = []
    description_hint: Optional[str] = None


class GenerateJobResponse(BaseModel):
    title: str
    description: str
    requirements: str
    nice_to_have: str
    benefits: str
    salary_range_suggestion: str
    # Wynik szablonowy jest nie do odróżnienia od wyjścia AI — a niesie
    # zmyślone widełki płacowe i dosłowny placeholder „(uzupełnij)". Bez tego
    # pola rekruter publikował je u klienta w przekonaniu, że to AI. Wzorzec
    # istnieje już w repo (`/api/jobs/{id}/criteria` zwraca `source`).
    source: Literal["claude", "template"] = "claude"


# Model tej trasy nie ma własnego wpisu w `Settings` — literał zostaje tutaj,
# w jednym miejscu, zamiast w środku wywołania.
_JOB_WRITER_MODEL = model_for(AIFeatureKey.job_description_generator)


class _ClaudeNotConfigured(RuntimeError):
    """Brak klucza Anthropic — fakt konfiguracji wdrożenia, nie awaria dostawcy.

    Rozróżnienie jest nośne: bez klucza (dev/local) szablon jest jedyną sensowną
    odpowiedzią, natomiast padnięte wywołanie Claude'a musi wyjść jako błąd.
    """


async def _generate_with_claude(request: GenerateJobRequest) -> GenerateJobResponse:
    """Try to generate using Claude API. Raises on failure."""
    from app.services.claude_client import call_claude

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        raise _ClaudeNotConfigured("No Claude API key configured")

    seniority_label = request.seniority or "senior"
    skills_str = ", ".join(request.skills) if request.skills else "nie podano"
    client_name = request.client or "nasz klient"

    prompt = f"""Wygeneruj profesjonalne ogłoszenie o pracę w języku polskim dla stanowiska:

Tytuł: {seniority_label.title()} {request.title}
Klient: {client_name}
Poziom: {seniority_label}
Wymagane technologie/umiejętności: {skills_str}
Dodatkowy kontekst: {request.description_hint or "brak"}

Zwróć WYŁĄCZNIE poprawny JSON (bez markdown, bez komentarzy) w tej dokładnej strukturze:
{{
  "title": "pełny tytuł stanowiska",
  "description": "2-3 atrakcyjne zdania o roli i firmie",
  "requirements": "lista wymagań w formacie markdown z myślnikami, minimum 6 punktów",
  "nice_to_have": "lista dodatkowych atutów z myślnikami, 3-4 punkty",
  "benefits": "lista benefitów w formacie markdown z myślnikami, 5-7 punktów",
  "salary_range_suggestion": "propozycja widełek w formacie np. '18 000 – 28 000 PLN (B2B)'"
}}"""

    # Wspólny, odporny helper zamiast surowego `anthropic.Anthropic(...)`:
    # ten klient dziedziczył domyślny timeout SDK 600 s (przy 120 s sufitu
    # axiosa po stronie przeglądarki), nie miał backoffu na przejściowe
    # 429/529, nie karmił circuit breakera Claude'a w `/api/health` i był
    # niewidzialny dla bramki na granicy providera. Sync SDK — offload, żeby
    # runda do LLM nie blokowała jednowątkowej pętli zdarzeń.
    message = await run_in_threadpool(
        call_claude,
        model=_JOB_WRITER_MODEL,
        max_tokens=1500,
        api_key=api_key,
        # Sonnet 5 does adaptive thinking (effort=high) by default; thinking
        # tokens count toward max_tokens and would truncate this JSON output.
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )

    # Claude 5 models can lead with a non-text block (e.g. a thinking block),
    # so content[0].text may be absent/empty — collect every text block.
    raw = "".join(
        getattr(b, "text", "") or "" for b in message.content if hasattr(b, "text")
    ).strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)
    return GenerateJobResponse(
        title=data.get("title", f"{seniority_label.title()} {request.title}"),
        description=data.get("description", ""),
        requirements=data.get("requirements", ""),
        nice_to_have=data.get("nice_to_have", ""),
        benefits=data.get("benefits", ""),
        salary_range_suggestion=data.get("salary_range_suggestion", ""),
        source="claude",
    )


def _generate_mock(request: GenerateJobRequest) -> GenerateJobResponse:
    """Fallback: generate a structured response using templates."""
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
        "- Elastyczne godziny pracy i możliwość pracy zdalnej\n"
        "- Stabilne zatrudnienie (B2B lub UoP)\n"
        "- Prywatna opieka medyczna\n"
        "- Budżet szkoleniowy i konferencyjny\n"
        "- Nowoczesne biuro w centrum miasta\n"
        "- Przyjazna atmosfera i wspierający zespół"
    )

    salary_ranges = {
        "junior": "8 000 – 14 000 PLN (B2B)",
        "mid": "14 000 – 22 000 PLN (B2B)",
        "senior": "20 000 – 32 000 PLN (B2B)",
        "lead": "28 000 – 42 000 PLN (B2B)",
    }
    salary = salary_ranges.get(seniority, "15 000 – 25 000 PLN (B2B)")

    return GenerateJobResponse(
        title=full_title,
        description=description,
        requirements=requirements,
        nice_to_have=nice_to_have,
        benefits=benefits,
        salary_range_suggestion=salary,
        source="template",
    )


@router.post("/ai/generate-job", response_model=GenerateJobResponse)
async def generate_job(
    request: GenerateJobRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/ai/generate-job
    Generates a structured job description using Claude API (or mock if no key).

    Subject to the Settings → AI quota for `job_description_generator`. Returns
    HTTP 503 if the master toggle is off, the feature is disabled, or the
    monthly limit has been hit.
    """
    # Settings → AI quota gate (Traffit gap #5).
    # Imported lazily so this module stays importable even if the AI quota
    # tables haven't been migrated yet (e.g. during 0085 rollout).
    #
    # `ai_feature(...)`, nie gołe `check_and_increment`: obciążenie i DEKLARACJA
    # w jednym kroku. Samo obciążenie nie ustawia kontekstu wywołania, więc
    # poprawnie naliczona generacja i tak logowała się na granicy providera jako
    # „UNGATED". Kontekst propaguje się do `run_in_threadpool`.
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import AIQuotaExceeded, ai_feature

    try:
        async with ai_feature(
            db, AIFeatureKey.job_description_generator, user_id=current_user.id
        ):
            # Commit the counter even if downstream Claude fails — we count the
            # admission decision, not the LLM round-trip success.
            await db.commit()
            try:
                result = await _generate_with_claude(request)
            except _ClaudeNotConfigured:
                # Brak klucza to konfiguracja wdrożenia (dev/local), nie awaria —
                # szablon jest tu jedyną sensowną odpowiedzią, ale wychodzi
                # OZNACZONY jako szablon.
                logger.warning("[AIJob] brak klucza Claude — zwracam szablon")
                return _generate_mock(request)
            except Exception as exc:
                # Awaria dostawcy NIE zwija się już po cichu do szablonu.
                # `call_claude` ponowił już przejściowe 429/529 z backoffem, więc
                # to, co tu dolatuje, jest realną awarią — a cichy szablon niesie
                # zmyślone widełki płacowe, które rekruter publikuje u klienta
                # w przekonaniu, że to wyjście AI.
                logger.exception("[AIJob] generacja przez Claude padła")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Generator ogłoszeń AI jest chwilowo niedostępny "
                        "(błąd usługi Claude). Spróbuj ponownie za chwilę."
                    ),
                ) from exc
            logger.info(f"[AIJob] Generated with Claude for: {request.title}")
            return result
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc
