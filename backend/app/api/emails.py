"""
Email Communication API.
Zarządzanie szablonami emaili i symulacja wysyłki.
SMTP integration — TODO (currently console log only).
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.email_template import EmailCategory, EmailTemplate
from app.api.candidate_access import (
    CandidatePIIAccess,
    CandidateWriteAccess,
    require_candidate_write,
)
from app.api.deps import AdminUser, TacPlus

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────


class EmailTemplateCreate(BaseModel):
    name: str
    subject: str
    body: str
    category: EmailCategory = EmailCategory.general
    is_default: bool = False


class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    category: Optional[EmailCategory] = None
    is_default: Optional[bool] = None


class EmailTemplateResponse(BaseModel):
    id: int
    name: str
    subject: str
    body: str
    category: EmailCategory
    is_default: bool
    created_by: Optional[int]
    placeholders: Optional[List[str]] = None

    model_config = {"from_attributes": True}


class SendEmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    candidate_id: Optional[int] = None
    template_id: Optional[int] = None


class PreviewRequest(BaseModel):
    template_id: int
    candidate_id: Optional[int] = None


class PreviewResponse(BaseModel):
    subject: str
    body: str


# ── Default Templates ──────────────────────────────────────────────────────

# Stable name used by `rejection_email_scheduler._resolve_template` to find
# the auto-rejection template. Changing this string requires coordinated
# update of the scheduler lookup.
REJECTION_EXTERNAL_TEMPLATE_NAME = "Auto-odrzucenie (po widoczności u klienta)"


DEFAULT_TEMPLATES = [
    {
        "name": "Potwierdzenie otrzymania aplikacji",
        "category": EmailCategory.application_received,
        "subject": "Potwierdzenie aplikacji — {{job_title}}",
        "body": """Szanowny/a {{candidate_name}},

Dziękujemy za przesłanie swojej aplikacji na stanowisko {{job_title}} w {{company_name}}.

Potwierdzamy otrzymanie Twojego CV i zapewniamy, że zostanie ono dokładnie przeanalizowane przez nasz zespół rekrutacyjny. O wynikach selekcji poinformujemy Cię w ciągu 7-10 dni roboczych.

W razie pytań, nie wahaj się z nami skontaktować.

Z wyrazami szacunku,
Zespół Rekrutacji
{{company_name}}""",
        "is_default": True,
    },
    {
        "name": "Zaproszenie na screening telefoniczny",
        "category": EmailCategory.screening_invite,
        "subject": "Zaproszenie na rozmowę wstępną — {{job_title}}",
        "body": """Szanowny/a {{candidate_name}},

Dziękujemy za zainteresowanie stanowiskiem {{job_title}} w {{company_name}}.

Po zapoznaniu się z Twoją aplikacją, z przyjemnością zapraszamy Cię na krótką rozmowę wstępną (screening), która pozwoli nam lepiej poznać Twoje doświadczenie i oczekiwania.

Proponujemy spotkanie w terminie: {{interview_date}}

Czy ten termin Ci odpowiada? Jeśli nie, proszę zaproponuj alternatywny.

Rozmowa potrwa około 30 minut i odbędzie się telefonicznie/przez Zoom.

Z wyrazami szacunku,
Zespół Rekrutacji
{{company_name}}""",
        "is_default": True,
    },
    {
        "name": "Zaproszenie na rozmowę kwalifikacyjną",
        "category": EmailCategory.interview_invite,
        "subject": "Zaproszenie na rozmowę kwalifikacyjną — {{job_title}}",
        "body": """Szanowny/a {{candidate_name}},

Z przyjemnością informujemy, że Twoja aplikacja na stanowisko {{job_title}} przeszła pomyślnie etap wstępnej selekcji.

Chcielibyśmy zaprosić Cię na rozmowę kwalifikacyjną:

📅 Termin: {{interview_date}}
🏢 Lokalizacja: {{company_name}}
💼 Stanowisko: {{job_title}}

Prosimy o potwierdzenie dostępności w podanym terminie lub zaproponowanie alternatywnego.

Jeśli masz pytania dotyczące rozmowy, nie wahaj się skontaktować.

Z wyrazami szacunku,
Zespół Rekrutacji
{{company_name}}""",
        "is_default": True,
    },
    {
        "name": "Informacja o niezakwalifikowaniu",
        "category": EmailCategory.rejection,
        "subject": "Informacja zwrotna dotycząca Twojej aplikacji — {{job_title}}",
        "body": """Szanowny/a {{candidate_name}},

Dziękujemy za zainteresowanie stanowiskiem {{job_title}} w {{company_name}} oraz za czas poświęcony na udział w procesie rekrutacyjnym.

Po dokładnym rozpatrzeniu Twojej kandydatury, z przykrością informujemy, że tym razem zdecydowaliśmy się na innych kandydatów, których profil w pełni odpowiada aktualnym potrzebom projektu.

Decyzja ta nie jest oceną Twoich kompetencji — na wybór wpłynęło wiele czynników.

Chętnie zachowamy Twoje CV w naszej bazie danych i skontaktujemy się z Tobą przy okazji przyszłych rekrutacji na odpowiednie stanowisko.

Życzymy powodzenia w dalszych poszukiwaniach zawodowych.

Z wyrazami szacunku,
Zespół Rekrutacji
{{company_name}}""",
        "is_default": True,
    },
    {
        "name": "Oferta współpracy",
        "category": EmailCategory.offer,
        "subject": "Oferta współpracy — {{job_title}} w {{company_name}}",
        "body": """Szanowny/a {{candidate_name}},

Z prawdziwą przyjemnością informujemy, że z sukcesem przeszłaś/przeszedłeś wszystkie etapy rekrutacji na stanowisko {{job_title}} w {{company_name}}.

Chcielibyśmy złożyć Ci formalną ofertę współpracy:

💼 Stanowisko: {{job_title}}
💰 Wynagrodzenie: {{salary}}
📅 Proponowany start: {{interview_date}}

Szczegółowe warunki umowy zostaną omówione podczas spotkania. Prosimy o potwierdzenie otrzymania tej oferty oraz zainteresowania współpracą do {{interview_date}}.

Cieszymy się na możliwość współpracy!

Z wyrazami szacunku,
Zespół Rekrutacji
{{company_name}}""",
        "is_default": True,
    },
    {
        "name": "Wiadomość follow-up",
        "category": EmailCategory.general,
        "subject": "Follow-up — {{job_title}}",
        "body": """Szanowny/a {{candidate_name}},

Chciałem/am się skontaktować w sprawie Twojej aplikacji na stanowisko {{job_title}} w {{company_name}}.

Czy masz pytania dotyczące procesu rekrutacji lub stanowiska? Chętnie odpowiem na wszelkie wątpliwości.

Jeśli zaszły jakieś zmiany w Twojej sytuacji zawodowej lub dostępności, prosimy o informację.

Z wyrazami szacunku,
Zespół Rekrutacji
{{company_name}}""",
        "is_default": False,
    },
    # 0045_rejection_emails — auto-notification template used by the
    # rejection_email_scheduler. Name is load-bearing: the scheduler looks
    # it up by this exact string before falling back to any default
    # rejection template. Supports `{{#if other_processes}}` for the
    # conditional "still in X processes" block.
    {
        "name": REJECTION_EXTERNAL_TEMPLATE_NAME,
        "category": EmailCategory.rejection,
        "subject": "Informacja zwrotna — {{job_title}}",
        "body": """<p>Cześć {{candidate_name}},</p>
<p>Dziękujemy za zaangażowanie w proces rekrutacyjny na stanowisko <strong>{{job_title}}</strong>.
Po analizie zebranych informacji zwrotnych podjęliśmy decyzję o zakończeniu współpracy
przy tym konkretnym procesie.</p>
{{#if other_processes}}<p>Nadal rozważamy Cię w <strong>{{other_processes_count}}</strong>
innych otwartych procesach: {{other_processes_list}}. Jeśli pojawią się nowe informacje,
dam znać.</p>{{/if}}
<p>Bardzo dziękuję za poświęcony czas i życzę powodzenia w dalszych poszukiwaniach.</p>
<p>Pozdrawiam,<br>{{recruiter_name}}</p>""",
        "is_default": False,
    },
]

AVAILABLE_PLACEHOLDERS = [
    "{{candidate_name}}",
    "{{job_title}}",
    "{{company_name}}",
    "{{interview_date}}",
    "{{salary}}",
    "{{recruiter_name}}",
    "{{recruiter_email}}",
    "{{application_date}}",
]


# ── Helpers ────────────────────────────────────────────────────────────────


def _render_template(
    subject: str, body: str, candidate: Optional[Candidate] = None
) -> tuple[str, str]:
    """Substitute only placeholders we can resolve from real data.

    P0.2: the previous version substituted hardcoded business values
    ("Senior Java Developer", a 2025 date, a fixed salary band, a fake
    recruiter) regardless of the selected recruitment — the recruiter could
    copy or send false terms. We now substitute only values we actually have
    (the candidate's own name) and leave every other ``{{token}}`` unresolved
    so it is visibly a blank the author must fill before sending.
    """
    placeholders = {}
    if candidate is not None:
        full_name = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        if full_name:
            placeholders["{{candidate_name}}"] = full_name

    rendered_subject = subject
    rendered_body = body
    for key, value in placeholders.items():
        rendered_subject = rendered_subject.replace(key, value)
        rendered_body = rendered_body.replace(key, value)
    return rendered_subject, rendered_body


def _extract_placeholders(text: str) -> List[str]:
    """Extract {{placeholder}} patterns from template text."""
    import re

    found = re.findall(r"\{\{[a-z_]+\}\}", text)
    return list(set(found))


# ── Email Templates CRUD ───────────────────────────────────────────────────


@router.get("/email-templates", response_model=List[EmailTemplateResponse])
async def list_email_templates(
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    category: Optional[EmailCategory] = None,
):
    """Lista wszystkich szablonów emaili."""
    query = select(EmailTemplate).order_by(
        EmailTemplate.is_default.desc(), EmailTemplate.name
    )
    if category:
        query = query.where(EmailTemplate.category == category)
    result = await db.execute(query)
    templates = list(result.scalars().all())
    return [
        EmailTemplateResponse(
            id=t.id,
            name=t.name,
            subject=t.subject,
            body=t.body,
            category=t.category,
            is_default=t.is_default,
            created_by=t.created_by,
            placeholders=_extract_placeholders(t.subject + " " + t.body),
        )
        for t in templates
    ]


@router.get("/email-templates/{template_id}", response_model=EmailTemplateResponse)
async def get_email_template(
    template_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz szablon emaila po ID."""
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Szablon nie znaleziony")
    return EmailTemplateResponse(
        id=template.id,
        name=template.name,
        subject=template.subject,
        body=template.body,
        category=template.category,
        is_default=template.is_default,
        created_by=template.created_by,
        placeholders=_extract_placeholders(template.subject + " " + template.body),
    )


@router.post(
    "/email-templates",
    response_model=EmailTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_candidate_write)],
)
async def create_email_template(
    data: EmailTemplateCreate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Utwórz nowy szablon emaila.

    Security: TAC+ only. Templates are shared system-wide and used for
    candidate-facing emails (rejection, offer, scheduling). Sourcer/recruiter
    must not be able to author them — separation of duties for outbound
    candidate communications.
    """
    template = EmailTemplate(
        **data.model_dump(),
        created_by=current_user.id,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return EmailTemplateResponse(
        id=template.id,
        name=template.name,
        subject=template.subject,
        body=template.body,
        category=template.category,
        is_default=template.is_default,
        created_by=template.created_by,
        placeholders=_extract_placeholders(template.subject + " " + template.body),
    )


@router.put(
    "/email-templates/{template_id}",
    response_model=EmailTemplateResponse,
    dependencies=[Depends(require_candidate_write)],
)
async def update_email_template(
    template_id: int,
    data: EmailTemplateUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Zaktualizuj szablon emaila.

    Security: TAC+ only — same rationale as create_email_template.
    """
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Szablon nie znaleziony")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(template, k, v)
    await db.flush()
    await db.refresh(template)
    return EmailTemplateResponse(
        id=template.id,
        name=template.name,
        subject=template.subject,
        body=template.body,
        category=template.category,
        is_default=template.is_default,
        created_by=template.created_by,
        placeholders=_extract_placeholders(template.subject + " " + template.body),
    )


@router.delete("/email-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_template(
    template_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Usuń szablon emaila.

    Security: admin only — templates are shared system-wide; deletion is
    irreversible and may break ongoing campaigns. Recruiters/TACs who want a
    template gone should ask an admin or update it instead.
    """
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Szablon nie znaleziony")
    await db.delete(template)


@router.post("/email-templates/{template_id}/preview", response_model=PreviewResponse)
async def preview_template_by_id(
    template_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    candidate_id: Optional[int] = None,
):
    """Podgląd wyrenderowanego szablonu z przykładowymi danymi."""
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Szablon nie znaleziony")

    candidate = None
    if candidate_id:
        cand_result = await db.execute(
            select(Candidate).where(Candidate.id == candidate_id)
        )
        candidate = cand_result.scalar_one_or_none()

    rendered_subject, rendered_body = _render_template(
        template.subject, template.body, candidate
    )
    return PreviewResponse(subject=rendered_subject, body=rendered_body)


@router.post("/email-templates/{template_id}/send")
async def send_test_email(
    template_id: int,
    current_user: CandidateWriteAccess,
):
    """Legacy simulated test-send — permanently disabled (Module 6, P0.1).

    This stub never sent anything: it logged the full rendered body to stdout
    (shipped to Loki) and reported the message as "wysłany". It now returns
    ``410 Gone`` and does no logging. No frontend uses it.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "LEGACY_EMAIL_SIMULATION_DISABLED",
            "message": "Symulowana wysyłka testowa została wyłączona.",
        },
    )


@router.post("/email-templates/seed")
async def seed_default_templates(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Seed default Polish email templates if none exist.
    Idempotent — won't duplicate if templates already exist.

    Security: admin only — seed creates the canonical rejection/offer/etc
    templates that every recruiter uses. Should be run once per environment
    by an admin during initial provisioning, not by arbitrary authenticated
    users.
    """
    existing = (await db.execute(select(EmailTemplate))).scalars().all()
    if existing:
        return {
            "status": "skipped",
            "message": f"Szablony już istnieją ({len(existing)} szt.)",
        }

    created = 0
    for tpl in DEFAULT_TEMPLATES:
        template = EmailTemplate(
            name=tpl["name"],
            subject=tpl["subject"],
            body=tpl["body"],
            category=tpl["category"],
            is_default=tpl["is_default"],
            created_by=current_user.id,
        )
        db.add(template)
        created += 1

    await db.flush()
    return {"status": "seeded", "message": f"Dodano {created} domyślnych szablonów"}


# ── Send Email (legacy simulation — DISABLED) ──────────────────────────────


@router.post("/emails/send")
async def send_email(
    data: SendEmailRequest,
    current_user: CandidateWriteAccess,
):
    """Legacy simulated send — permanently disabled (Module 6, finding P0.1).

    This endpoint never talked to SMTP or Graph; it logged the message and
    wrote ``Activity(action="email_sent")``, so the UI reported a delivery
    that never happened and the candidate history recorded a fake send.

    It now returns ``410 Gone`` and writes nothing. Real outbound mail goes
    through the Microsoft 365 composer (``/api/candidates/{id}/emails/compose``).
    A temporarily-unavailable real integration must return ``503`` from its own
    endpoint — never a fake success here.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "LEGACY_EMAIL_SIMULATION_DISABLED",
            "message": (
                "Symulowana wysyłka została wyłączona. Użyj kompozytora "
                "Microsoft 365, aby wysłać wiadomość, albo skopiuj treść do "
                "swojej aplikacji pocztowej."
            ),
        },
    )


# ── Preview ────────────────────────────────────────────────────────────────


@router.post("/emails/preview", response_model=PreviewResponse)
async def preview_email(
    data: PreviewRequest,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Podgląd wyrenderowanego szablonu z podstawionymi placeholderami."""
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == data.template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Szablon nie znaleziony")

    candidate = None
    if data.candidate_id:
        cand_result = await db.execute(
            select(Candidate).where(Candidate.id == data.candidate_id)
        )
        candidate = cand_result.scalar_one_or_none()

    rendered_subject, rendered_body = _render_template(
        template.subject, template.body, candidate
    )
    return PreviewResponse(subject=rendered_subject, body=rendered_body)
