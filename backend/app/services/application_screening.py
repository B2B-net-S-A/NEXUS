"""Przegląd zgłoszeń z linku rekrutacji przed wejściem do „Nowi” (0404).

Decyzje Artura 29.09.2026: zgłoszenie z linku rekrutacji (``kind='job'``,
strona kariery i stary formularz ``/apply/{token}``) NIE otwiera procesu
w requeście. ``public_apply`` zapisuje kandydata, CV, zgodę, źródło i wiersz
``application_screenings`` (``pending``) w jednej transakcji; pętla
``application_screening`` (co 30 s) ocenia zgłoszenie po odczycie CV i dopiero
wtedy decyduje. Stały link rekrutera (``kind='recruiter'``) bez zmian.

Reguła (wzór akademii — kod liczy, model tylko uzasadnia z cytatem):

1. Fakty z KODU: must-have rekrutacji (tylko technologie, ta sama lista co
   bramka wyszukiwania — ``search_dealbreaker_inputs``) w CV i profilu
   (``must_text_evidence``) → ``must_found / must_total``; bramki twarde
   (globalna czarna lista, weto hiring managera — ``submission_block_reason``)
   → ``blocked``, bez procesu.
2. GPT-6 Luna (``AIFeatureKey.application_screening``): ``{verdict, reasons:
   [{text, quote}]}``; powód, którego cytatu nie ma w CV ani w profilu, jest
   usuwany.
3. Werdykt (``decide``): ``not_fit`` WYŁĄCZNIE wtedy, gdy model mówi
   ``not_fit`` z co najmniej jednym sprawdzonym cytatem, a kod się zgadza
   (must-have znalezione w mniej niż połowie albo rekrutacja bez must-have
   technologii). Wszystko inne — ``fits`` / ``unclear`` — wchodzi do „Nowi”.
4. Awaria modelu, brak albo nieczytelne CV → ``unclear`` i osoba wchodzi do
   „Nowi” z plakietką „AI nie oceniło”. AI nie może zgubić kandydata.

Odrzuceni zostają w bazie i na liście „Odrzuceni przez AI (N)” w rekrutacji
z przyciskiem „Dodaj mimo to” (``api/application_screenings.py``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Iterable, Optional, Sequence

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_day_start_utc, local_now
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.application_screening import ApplicationScreening
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_priority import PriorityOriginKind
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import APPLICATION_SCREENING
from app.services.prompt_fencing import fence

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.application_screening

VERDICT_FITS = "fits"
VERDICT_UNCLEAR = "unclear"
VERDICT_NOT_FIT = "not_fit"
VERDICTS = (VERDICT_FITS, VERDICT_UNCLEAR, VERDICT_NOT_FIT)

# Próg zgody kodu z modelem: „nie pasuje” tylko przy must-have znalezionych
# w MNIEJ niż połowie (decyzja Artura 29.09.2026).
MUST_RATIO_NOT_FIT = 0.5

CV_CHAR_LIMIT = 24_000
JOB_TEXT_LIMIT = 4_000
REASON_LIMIT = 4
REASON_TEXT_MAX = 300
QUOTE_MAX = 300
DEAL_BREAKER_MAX = 300

# Pętla: wiersz nowego kandydata czeka na odczyt CV (`cv_parsed_at`), najdłużej
# `WAIT_FOR_CV` — potem rusza z tym, co jest (tekst z formularza).
MIN_AGE = timedelta(seconds=20)
WAIT_FOR_CV = timedelta(minutes=10)
LEASE = timedelta(minutes=5)
BATCH = 5
# Paczka BATCH wierszy musi zmieścić się w dzierżawie LEASE.
MODEL_TOTAL_TIMEOUT_SECONDS = 50.0
MAX_ATTEMPTS = 3
DIGEST_HOUR_LOCAL = 8


# ── Reguła (czyste funkcje) ────────────────────────────────────────────────


def normalize(text: Optional[str]) -> str:
    """Porównanie cytatu z CV: bez różnic w białych znakach i wielkości liter."""
    return " ".join((text or "").replace("**", "").split()).casefold()


def keep_quoted_reasons(
    raw_reasons: Any, haystacks: Iterable[Optional[str]]
) -> list[dict[str, str]]:
    """Powody z cytatem obecnym w CV albo profilu; reszta wypada.

    Zwraca najwyżej ``REASON_LIMIT`` powodów ``{"text", "quote"}``. Powód bez
    cytatu też wypada — zdanie o kandydacie bez dowodu z jego CV jest
    zgadywaniem, a na nim nie wolno nikogo odrzucić.
    """
    if not isinstance(raw_reasons, list):
        return []
    hay = "\n".join(normalize(h) for h in haystacks if h)
    kept: list[dict[str, str]] = []
    for item in raw_reasons:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if not text or not quote:
            continue
        needle = normalize(quote)
        if len(needle) < 3 or needle not in hay:
            continue
        kept.append({"text": text[:REASON_TEXT_MAX], "quote": quote[:QUOTE_MAX]})
        if len(kept) >= REASON_LIMIT:
            break
    return kept


def _model_json(raw: Optional[str]) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("brak JSON-a w odpowiedzi")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("odpowiedź nie jest obiektem")
    return data


def parse_model(raw: Optional[str]) -> tuple[Optional[str], list]:
    """JSON modelu → (werdykt albo ``None``, surowe powody). Rzuca przy braku JSON-a."""
    data = _model_json(raw)
    verdict = data.get("verdict")
    verdict = verdict if verdict in VERDICTS else None
    reasons = data.get("reasons")
    return verdict, reasons if isinstance(reasons, list) else []


def deal_breaker_conditions(job: Any) -> list[str]:
    """Warunki „Odpada, gdy…” z pytań screeningowych Championa (bez pustych)."""
    from app.services import champion_view

    out: list[str] = []
    for question in champion_view.screening_questions(
        getattr(job, "champion_profile", None)
    ):
        if not isinstance(question, dict):
            continue
        condition = " ".join(str(question.get("deal_breaker") or "").split())
        if condition and condition not in out:
            out.append(condition[:DEAL_BREAKER_MAX])
    return out


def keep_quoted_deal_breaker(
    raw: Optional[str],
    conditions: Sequence[str],
    haystacks: Iterable[Optional[str]],
) -> Optional[dict[str, str]]:
    """Trafienie deal-breakera od modelu — tylko z cytatem z CV i znanym warunkiem.

    Model (prompt v2) może oddać ``deal_breaker: {"condition", "quote"}``.
    Zostaje WYŁĄCZNIE, gdy ``condition`` jest jednym z warunków rekrutacji,
    a ``quote`` stoi dosłownie w CV albo profilu. Awaria odczytu = ``None``
    (to plakietka, nigdy bramka). ``decide`` tego nie czyta.
    """
    try:
        data = _model_json(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    item = data.get("deal_breaker")
    if not isinstance(item, dict):
        return None
    condition = " ".join(str(item.get("condition") or "").split())
    quote = str(item.get("quote") or "").strip()
    if not condition or not quote:
        return None
    known = {normalize(c): c for c in conditions}
    matched = known.get(normalize(condition))
    if matched is None:
        return None
    hay = "\n".join(normalize(h) for h in haystacks if h)
    needle = normalize(quote)
    if len(needle) < 3 or needle not in hay:
        return None
    return {"condition": matched, "quote": quote[:QUOTE_MAX]}


def decide(
    *,
    model_verdict: Optional[str],
    kept_reasons: Sequence[dict],
    must_found: int,
    must_total: int,
) -> str:
    """Werdykt końcowy — model i kod muszą się zgodzić, żeby kogoś odrzucić.

    * brak werdyktu modelu (awaria, brak CV) → ``unclear``;
    * ``not_fit`` bez żadnego sprawdzonego cytatu → ``unclear``;
    * ``not_fit`` przy must-have znalezionych w ≥ 50% → ``unclear`` (kod
      widzi dowód przeciw); przy rekrutacji bez must-have technologii kod
      nie ma dowodu przeciw, więc decyduje cytat modelu;
    * ``fits`` przy must-have znalezionych w < 50% → ``unclear`` (plakietka
      „do sprawdzenia” zamiast obietnicy, której kod nie potwierdza).
    """
    if model_verdict not in VERDICTS:
        return VERDICT_UNCLEAR
    ratio = (must_found / must_total) if must_total > 0 else None
    if model_verdict == VERDICT_NOT_FIT:
        if not kept_reasons:
            return VERDICT_UNCLEAR
        if ratio is None or ratio < MUST_RATIO_NOT_FIT:
            return VERDICT_NOT_FIT
        return VERDICT_UNCLEAR
    if model_verdict == VERDICT_FITS:
        if ratio is not None and ratio < MUST_RATIO_NOT_FIT:
            return VERDICT_UNCLEAR
        return VERDICT_FITS
    return VERDICT_UNCLEAR


@dataclass
class ScreeningResult:
    verdict: str
    must_found: int = 0
    must_total: int = 0
    reasons: list[dict] = field(default_factory=list)
    model: Optional[str] = None
    # Kod powodu braku oceny modelu (``no_cv``, ``model_error:<Klasa>``,
    # ``screening_off``) — nigdy treść odpowiedzi.
    error: Optional[str] = None
    # 04.10.2026: warunek „Odpada, gdy…”, który według AI łamie CV
    # (`{"condition", "quote"}`, cytat sprawdzony). Tylko plakietka.
    deal_breaker: Optional[dict[str, str]] = None

    @property
    def model_assessed(self) -> bool:
        return self.error is None and self.model is not None


def job_prompt_block(job: Any) -> str:
    """Rola dla modelu: tytuł, must, nice i „O projekcie” — bez stawek i klienta."""
    from app.services import champion_view
    from app.services.requirement_contract import (
        requirement_labels,
        requirements_for_job,
    )

    labels = requirement_labels(requirements_for_job(job))
    project = champion_view.project(getattr(job, "champion_profile", None))
    about = "\n".join(
        str(p).strip()
        for p in (project.get("about"), project.get("responsibilities"))
        if p and str(p).strip()
    )
    title = getattr(job, "working_title", None) or getattr(job, "title", "") or ""
    lines = [f"Rola: {title}"]
    if labels.get("must"):
        lines.append("Wymagane (must-have): " + ", ".join(labels["must"]))
    if labels.get("nice"):
        lines.append("Mile widziane: " + ", ".join(labels["nice"]))
    if about:
        lines.append("O projekcie:\n" + about)
    conditions = deal_breaker_conditions(job)
    if conditions:
        # 04.10.2026: model może wskazać warunek, który CV łamie — z cytatem.
        lines.append("Odpada, gdy:\n" + "\n".join(f"- {c}" for c in conditions))
    return fence("rekrutacja", "\n".join(lines)[:JOB_TEXT_LIMIT])


def must_facts(job: Any, candidate: Any, cv_text: str) -> tuple[int, int]:
    """(znalezione, wszystkie) must-have technologie w profilu i CV."""
    from app.services.must_text_evidence import text_met_labels
    from app.services.requirement_contract import search_dealbreaker_inputs

    inputs = search_dealbreaker_inputs(job)
    must = list(inputs.must_skills)
    if not must:
        return 0, 0
    met = text_met_labels(
        candidate,
        must,
        note_texts=[cv_text] if cv_text else (),
        options=inputs.gate_options,
    )
    return len(met), len(must)


def entry_meta(result: ScreeningResult, *, overridden: bool = False) -> dict:
    """``recruitment_processes.entry_meta`` — plakietka „AI: …” na karcie."""
    from app.services.process_entry_meta import application_screening_entry_meta

    return application_screening_entry_meta(
        verdict=result.verdict,
        assessed=result.model_assessed,
        must_found=result.must_found,
        must_total=result.must_total,
        overridden=overridden,
        deal_breaker=(result.deal_breaker or {}).get("condition"),
    )


# ── Zapis przy zgłoszeniu ───────────────────────────────────────────────────


def screening_applies(link: Any) -> bool:
    """Czy zgłoszenie z tego linku czeka na przegląd zamiast od razu w „Nowi”."""
    return bool(
        settings.APPLICATION_SCREENING_ENABLED
        and getattr(link, "kind", None) == "job"
        and getattr(link, "job_id", None) is not None
    )


def record_pending(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    submission_id: Optional[int],
    cv_text: Optional[str],
    link: Any,
    via: str,
    first_name: str,
    last_name: str,
    utm_source: Optional[str],
) -> ApplicationScreening:
    """Wiersz ``pending`` w transakcji zgłoszenia (commit robi wołający)."""
    row = ApplicationScreening(
        submission_id=submission_id,
        candidate_id=candidate_id,
        job_id=job_id,
        status="pending",
        outcome="pending",
        cv_text=(cv_text or None) and cv_text[:CV_CHAR_LIMIT],
        context={
            "link_owner_id": link.created_by,
            "origin_assignment_id": link.origin_assignment_id,
            "priority_compliant_at_create": link.priority_compliant_at_create,
            "via": via,
            "first_name": first_name,
            "last_name": last_name,
            "utm_source": utm_source,
        },
    )
    db.add(row)
    return row


# ── Ocena ───────────────────────────────────────────────────────────────────


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        # Cała ocena (ponowienia i zapas) mieści się w dzierżawie wiersza —
        # dłuższa awaria dostawcy = `unclear`, nie druga ocena w drugim
        # kontenerze ani fałszywe „stalled” w `checks.background_tasks`.
        total_timeout=MODEL_TOTAL_TIMEOUT_SECONDS,
        model=model_for(FEATURE),
        fallback_models=fallbacks_for(FEATURE),
        max_tokens=1200,
        thinking={"type": "disabled"},
        system=APPLICATION_SCREENING.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


async def assess(
    db: AsyncSession, *, job: Any, candidate: Any, cv_text: str, use_model: bool
) -> ScreeningResult:
    """Fakty z kodu + (opcjonalnie) Luna. Nigdy nie rzuca z powodu modelu.

    Commituje sesję PRZED wywołaniem modelu — połączenie wraca do puli na czas
    odpowiedzi. Wołający nie może trzymać w tej sesji niezatwierdzonych zmian.
    """
    from app.services.must_text_evidence import profile_text

    profile = profile_text(candidate)
    found, total = must_facts(job, candidate, cv_text)
    if not use_model:
        return ScreeningResult(
            verdict=VERDICT_UNCLEAR,
            must_found=found,
            must_total=total,
            error="screening_off",
        )
    if not (cv_text or "").strip():
        return ScreeningResult(
            verdict=VERDICT_UNCLEAR, must_found=found, must_total=total, error="no_cv"
        )
    prompt = APPLICATION_SCREENING.render(
        job=job_prompt_block(job), cv=fence("cv", cv_text[:CV_CHAR_LIMIT])
    )
    try:
        async with ai_feature(db, FEATURE, user_id=None):
            await db.commit()  # zwolnij połączenie na czas modelu
            raw = await run_in_threadpool(_call_model, prompt)
        model_verdict, raw_reasons = parse_model(raw)
    except Exception as exc:  # noqa: BLE001 — AI przegląda, nigdy nie blokuje
        name = type(exc).__name__
        logger.warning("application_screening: model failed (%s)", name)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("application_screening: rollback after model failure")
        return ScreeningResult(
            verdict=VERDICT_UNCLEAR,
            must_found=found,
            must_total=total,
            error=f"model_error:{name}"[:120],
        )
    kept = keep_quoted_reasons(raw_reasons, (cv_text, profile))
    deal_breaker = keep_quoted_deal_breaker(
        raw, deal_breaker_conditions(job), (cv_text, profile)
    )
    return ScreeningResult(
        verdict=decide(
            model_verdict=model_verdict,
            kept_reasons=kept,
            must_found=found,
            must_total=total,
        ),
        must_found=found,
        must_total=total,
        reasons=kept,
        model=model_for(FEATURE),
        error=None if model_verdict is not None else "model_no_verdict",
        deal_breaker=deal_breaker,
    )


# ── Wejście do rekrutacji ───────────────────────────────────────────────────


async def pair_in_job(db: AsyncSession, *, candidate_id: int, job_id: int) -> bool:
    return (
        await db.scalar(
            select(CandidateStage.id)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .limit(1)
        )
    ) is not None


async def open_in_new(
    db: AsyncSession,
    *,
    row: ApplicationScreening,
    actor_user_id: Optional[int],
    meta: dict,
    notes: str,
) -> CandidateStage:
    """Proces w „Nowi” — te same kroki co dawniej w requeście zgłoszenia."""
    from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
    from app.services.candidate_stage_cv_service import create_original_cv_snapshot
    from app.services.recruitment_process_commands import open_process

    context = row.context if isinstance(row.context, dict) else {}
    stage = await open_process(
        db,
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        stage=PipelineStage.new,
        actor_user_id=actor_user_id,
        origin_kind=PriorityOriginKind.external_inbound,
        frozen_origin_assignment_id=context.get("origin_assignment_id"),
        frozen_priority_compliant=context.get("priority_compliant_at_create"),
        entry_source="application",
        entry_meta=meta,
        notes=notes,
    )
    await db.flush()
    await create_original_cv_snapshot(db, stage)
    await maybe_ensure_contact_opportunity(
        db,
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        source="pipeline",
        occurred_at=stage.moved_at,
    )
    return stage


def _notes_for(context: dict) -> str:
    return (
        "Aplikacja przez stronę kariery"
        if context.get("via") == "career"
        else "Aplikacja przez invite link"
    )


_UNASSESSED_NOTE = " AI nie oceniło zgłoszenia — sprawdź CV."
_UNCLEAR_NOTE = " AI: do sprawdzenia."


async def _notify(
    *,
    job_id: int,
    candidate_id: int,
    context: dict,
    blocked_reason: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """Dzwonek ``new_application`` po decyzji — ta sama treść co dawniej."""
    from app.services import public_apply

    owner_id = context.get("link_owner_id")
    link = SimpleNamespace(created_by=owner_id, job_id=job_id)
    applicant = public_apply.ApplicantInput(
        first_name=str(context.get("first_name") or ""),
        last_name=str(context.get("last_name") or ""),
        email="",
    )
    async with AsyncSessionLocal() as db:
        await public_apply._notify_owner(
            db,
            link=link,
            applicant=applicant,
            related_entity_type="candidate",
            related_entity_id=candidate_id,
            target=f"/candidates/{candidate_id}",
            duplicate=False,
            blocked_reason=blocked_reason,
            extra=extra,
        )


async def _finish(
    db: AsyncSession,
    row: ApplicationScreening,
    *,
    result: Optional[ScreeningResult],
    outcome: str,
    status: str = "done",
    error: Optional[str] = None,
) -> None:
    row.status = status
    row.outcome = outcome
    row.decided_at = datetime.now(timezone.utc)
    row.claimed_until = None
    row.cv_text = None
    if result is not None:
        row.verdict = result.verdict
        row.must_found = result.must_found
        row.must_total = result.must_total
        row.reasons = result.reasons
        row.model = result.model
        row.error = result.error
    if error is not None:
        row.error = error[:120]
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=row.candidate_id,
            action="application_screened",
            user_id=None,
            details={
                "screening_id": row.id,
                "job_id": row.job_id,
                "outcome": outcome,
                "verdict": row.verdict,
                "must_found": row.must_found,
                "must_total": row.must_total,
            },
        )
    )


async def process_one(screening_id: int) -> Optional[str]:
    """Oceń jedno zgłoszenie i zdecyduj. Zwraca wynik (``outcome``) albo ``None``."""
    from app.api.application_submissions import submission_block_reason
    from app.services import job_public_profile as jpp

    async with AsyncSessionLocal() as db:
        row = await db.get(ApplicationScreening, screening_id)
        if row is None or row.status != "pending":
            return None
        context = dict(row.context or {})
        job = await db.get(Job, row.job_id)
        candidate = await db.get(Candidate, row.candidate_id)
        if job is None or candidate is None:  # pragma: no cover — CASCADE
            return None

        # Rekrutacja zamknięta po zgłoszeniu (ręcznie albo nocnym archiwum
        # Traffita): osoba aplikowała, gdy była otwarta — przed 0404 proces
        # otwierał się od razu, więc wchodzi do „Nowi” bez oceny modelu.
        # Wynik `job_closed` gubił ją: bez procesu, dzwonka i wpisu na liście.
        job_open = jpp.job_is_open(job)
        if await pair_in_job(db, candidate_id=row.candidate_id, job_id=row.job_id):
            await _finish(db, row, result=None, outcome="already_in_job")
            await db.commit()
            return "already_in_job"
        blocked = await submission_block_reason(
            db, job_id=row.job_id, candidate_id=row.candidate_id
        )
        if blocked is not None:
            await _finish(db, row, result=None, outcome="blocked", error="blocked")
            row.reasons = [{"text": blocked[:REASON_TEXT_MAX], "quote": ""}]
            await db.commit()
            await _notify(
                job_id=row.job_id,
                candidate_id=row.candidate_id,
                context=context,
                blocked_reason=blocked,
            )
            return "blocked"

        cv_text = row.cv_text or candidate.raw_cv_text or ""
        await db.commit()
        result = await assess(
            db,
            job=job,
            candidate=candidate,
            cv_text=cv_text,
            use_model=bool(settings.APPLICATION_SCREENING_ENABLED) and job_open,
        )

        # Zapis decyzji pod blokadą wiersza: równoległy przebieg albo
        # „Dodaj mimo to” w międzyczasie wygrywa.
        locked = await db.scalar(
            select(ApplicationScreening)
            .where(ApplicationScreening.id == screening_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked is None or locked.status != "pending":
            await db.rollback()
            return None
        if result.verdict == VERDICT_NOT_FIT:
            await _finish(db, locked, result=result, outcome="screened_out")
            await db.commit()
            return "screened_out"
        if await pair_in_job(
            db, candidate_id=locked.candidate_id, job_id=locked.job_id
        ):
            await _finish(db, locked, result=result, outcome="already_in_job")
            await db.commit()
            return "already_in_job"
        await open_in_new(
            db,
            row=locked,
            actor_user_id=context.get("link_owner_id"),
            meta=entry_meta(result),
            notes=_notes_for(context),
        )
        await _finish(db, locked, result=result, outcome="added")
        await db.commit()
        await _notify(
            job_id=locked.job_id,
            candidate_id=locked.candidate_id,
            context=context,
            extra=(
                _UNASSESSED_NOTE
                if not result.model_assessed
                else _UNCLEAR_NOTE
                if result.verdict == VERDICT_UNCLEAR
                else None
            ),
        )
        return "added"


async def _give_up(screening_id: int, error: str) -> None:
    """Po ``MAX_ATTEMPTS`` nieudanych przebiegach: ``failed`` — osoba zostaje
    w bazie i na liście „Odrzuceni przez AI” z „Dodaj mimo to”."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ApplicationScreening)
            .where(ApplicationScreening.id == screening_id)
            .with_for_update()
        )
        if row is None or row.status != "pending":
            return
        if row.attempts < MAX_ATTEMPTS:
            row.claimed_until = None  # następny przebieg spróbuje od razu
            row.error = error[:120]
        else:
            await _finish(
                db,
                row,
                result=ScreeningResult(verdict=VERDICT_UNCLEAR, error=error[:120]),
                outcome="pending",
                status="failed",
            )
        await db.commit()


async def claim_batch(limit: int = BATCH) -> list[int]:
    """Weź gotowe wiersze (``FOR UPDATE SKIP LOCKED``) i załóż dzierżawę."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        ids = (
            await db.scalars(
                select(ApplicationScreening.id)
                .join(Candidate, Candidate.id == ApplicationScreening.candidate_id)
                .where(
                    ApplicationScreening.status == "pending",
                    ApplicationScreening.created_at < now - MIN_AGE,
                    or_(
                        ApplicationScreening.claimed_until.is_(None),
                        ApplicationScreening.claimed_until < now,
                    ),
                    or_(
                        # Istniejący kandydat: profil już jest, CV z formularza
                        # leży w `cv_text`.
                        ApplicationScreening.submission_id.is_not(None),
                        Candidate.cv_parsed_at.is_not(None),
                        ApplicationScreening.created_at < now - WAIT_FOR_CV,
                    ),
                )
                .order_by(ApplicationScreening.created_at)
                .limit(limit)
                .with_for_update(of=ApplicationScreening, skip_locked=True)
            )
        ).all()
        if ids:
            await db.execute(
                update(ApplicationScreening)
                .where(ApplicationScreening.id.in_(ids))
                .values(
                    claimed_until=now + LEASE,
                    attempts=ApplicationScreening.attempts + 1,
                )
            )
        await db.commit()
        return list(ids)


async def run_once() -> dict[str, int]:
    """Jeden przebieg pętli: ocena gotowych zgłoszeń + poranny skrót."""
    stats: dict[str, int] = {}
    for screening_id in await claim_batch():
        try:
            outcome = await process_one(screening_id)
        except Exception as exc:  # noqa: BLE001 — jeden wiersz nie blokuje reszty
            logger.warning(
                "application_screening: row=%s failed (%s)",
                screening_id,
                type(exc).__name__,
            )
            detail = (
                f"http_{exc.status_code}"
                if isinstance(exc, HTTPException)
                else type(exc).__name__
            )
            await _give_up(screening_id, detail)
            outcome = "error"
        if outcome:
            stats[outcome] = stats.get(outcome, 0) + 1
    digests = await send_daily_digests()
    if digests:
        stats["digests"] = digests
    return stats


# ── Poranny skrót odrzuconych ───────────────────────────────────────────────


def _rejected_noun(n: int) -> str:
    if n == 1:
        return "zgłoszenie"
    last, last_two = n % 10, n % 100
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return "zgłoszenia"
    return "zgłoszeń"


async def send_daily_digests() -> int:
    """Od 8:00 (czas firmy) JEDEN wpis na rekrutację: odrzuceni z poprzednich dni.

    Bez maila. Odbiorca: prowadzący rekrutację, a bez niego Delivery Lead.
    ``digested_at`` zamyka wiersze; dobowy dedup ``emit`` chroni przed
    powtórką przy równoległym przebiegu.
    """
    from app.services.notification_triggers import emit

    if local_now().hour < DIGEST_HOUR_LOCAL:
        return 0
    day_start = local_day_start_utc(business_today())
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ApplicationScreening.job_id, func.count())
                .where(
                    ApplicationScreening.outcome == "screened_out",
                    ApplicationScreening.overridden_at.is_(None),
                    ApplicationScreening.digested_at.is_(None),
                    ApplicationScreening.decided_at < day_start,
                )
                .group_by(ApplicationScreening.job_id)
            )
        ).all()
        sent = 0
        for job_id, count in rows:
            job = await db.get(Job, job_id)
            recipient = None
            if job is not None:
                recipient = job.recruiter_id or job.delivery_lead_id
            if recipient is not None and job is not None:
                title = getattr(job, "working_title", None) or job.title
                await emit(
                    db,
                    user_id=recipient,
                    title="Zgłoszenia odrzucone przez AI",
                    message=(
                        f"{count} {_rejected_noun(count)} do rekrutacji „{title}” "
                        "AI uznało za niepasujące. Lista „Odrzuceni przez AI” "
                        "w kolumnie „Nowi” — z powodem i „Dodaj mimo to”."
                    ),
                    ntype=NotificationType.application_screening_digest,
                    related_entity_type="job",
                    related_entity_id=job_id,
                    link=f"/jobs/{job_id}",
                )
                sent += 1
            await db.execute(
                update(ApplicationScreening)
                .where(
                    ApplicationScreening.job_id == job_id,
                    ApplicationScreening.outcome == "screened_out",
                    ApplicationScreening.digested_at.is_(None),
                    ApplicationScreening.decided_at < day_start,
                )
                .values(digested_at=datetime.now(timezone.utc))
            )
        await db.commit()
        return sent


# ── „Dodaj mimo to” ─────────────────────────────────────────────────────────

LISTED_OUTCOMES = ("screened_out",)


def listed_clause():
    """Wiersze na liście „Odrzuceni przez AI”: odrzuceni i nieudane oceny."""
    return and_(
        ApplicationScreening.overridden_at.is_(None),
        or_(
            ApplicationScreening.outcome.in_(LISTED_OUTCOMES),
            ApplicationScreening.status == "failed",
        ),
    )


async def add_despite(
    db: AsyncSession, *, job_id: int, screening_id: int, user_id: int
) -> ApplicationScreening:
    """„Dodaj mimo to” — proces w „Nowi”, ślad kto i kiedy. Commit robi wołający."""
    from app.api.application_submissions import submission_block_reason

    row = await db.scalar(
        select(ApplicationScreening)
        .where(
            ApplicationScreening.id == screening_id,
            ApplicationScreening.job_id == job_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Nie ma takiego zgłoszenia w tej rekrutacji.")
    listed = row.overridden_at is None and (
        row.outcome in LISTED_OUTCOMES or row.status == "failed"
    )
    if not listed:
        raise HTTPException(409, "To zgłoszenie jest już rozstrzygnięte.")
    if await pair_in_job(db, candidate_id=row.candidate_id, job_id=job_id):
        raise HTTPException(409, "Ta osoba jest już w tej rekrutacji.")
    blocked = await submission_block_reason(
        db, job_id=job_id, candidate_id=row.candidate_id
    )
    if blocked is not None:
        raise HTTPException(409, blocked)
    context = dict(row.context or {})
    result = ScreeningResult(
        verdict=row.verdict or VERDICT_UNCLEAR,
        must_found=row.must_found or 0,
        must_total=row.must_total or 0,
        model=row.model,
        error=row.error,
    )
    await open_in_new(
        db,
        row=row,
        actor_user_id=user_id,
        meta=entry_meta(result, overridden=True),
        notes=_notes_for(context),
    )
    now = datetime.now(timezone.utc)
    row.outcome = "added"
    row.status = "done"
    row.overridden_by = user_id
    row.overridden_at = now
    row.decided_at = row.decided_at or now
    row.cv_text = None
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=row.candidate_id,
            action="application_screening_overridden",
            user_id=user_id,
            details={
                "screening_id": row.id,
                "job_id": job_id,
                "verdict": row.verdict,
            },
        )
    )
    return row
