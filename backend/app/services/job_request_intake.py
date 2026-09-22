"""Nowa rekrutacja z requestu klienta — odczyt PRZED zapisem (strona /jobs/new).

Delivery Lead wkleja maila od klienta; model wypisuje z niego minimum, którego
wymaga „Przekaż do searchu” (`job_readiness.job_handoff_blockers`), a ten moduł
normalizuje odpowiedź do płaskiego kształtu formularza. Niczego nie zapisuje.

Zasady, które łatwo cofnąć „przy okazji”:

* **Budżet liczy kod, nie model.** Model cytuje fragment (`rate_quote`),
  a liczba powstaje z `champion_intake.document_rate` — tej samej reguły, której
  używa import dokumentu Championa. Stawka dzienna, w innej walucie albo
  brutto daje ``None`` i notatkę, nigdy przeliczoną liczbę.
* **Cytat musi być w tekście.** Fragment, którego nie ma w requeście (model
  go „poprawił”), nie jest dowodem — ani dla budżetu, ani dla podświetlenia.
* **Braki są jawne.** ``missing`` używa tych samych reguł co handoff: formularz
  pokazuje dokładnie to, co później by go zablokowało.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.services import champion_intake
from app.services.champion_document import folded
from app.services.llm_prompts import JOB_REQUEST_INTAKE

logger = logging.getLogger(__name__)

MAX_REQUEST_CHARS = 20_000
MIN_REQUEST_CHARS = 30
MAX_MUST = 10
MAX_NICE = 8
MAX_QUESTIONS = 6
MAX_EVIDENCE = 40

_WORK_MODES = {
    "zdalnie": "remote",
    "remote": "remote",
    "hybrydowo": "hybrid",
    "hybryda": "hybrid",
    "hybrid": "hybrid",
    "stacjonarnie": "onsite",
    "onsite": "onsite",
    "biuro": "onsite",
}

# Kody braków — te same warunki co `job_readiness` (brief + rubryki).
MISSING_ROLE = "role"
MISSING_MUST = "must"
MISSING_BUDGET = "budget"
MISSING_WORK_MODE = "work_mode"
MISSING_OFFICE_DAYS = "office_days"
MISSING_OFFICE_CITY = "office_city"
MISSING_CONTEXT = "context"
MISSING_QUESTIONS = "questions"


@dataclass(frozen=True)
class IntakeQuestion:
    question: str
    ideal_answer: str
    from_request: bool


@dataclass(frozen=True)
class RequestIntake:
    role_name: Optional[str] = None
    must: list[str] = field(default_factory=list)
    nice: list[str] = field(default_factory=list)
    seniority_min_years: Optional[int] = None
    rate_budget_hourly: Optional[float] = None
    rate_quote: Optional[str] = None
    rate_note: Optional[str] = None
    remote_policy: Optional[str] = None
    onsite_days_per_week: Optional[int] = None
    office_city: Optional[str] = None
    start_date: Optional[str] = None
    project_about: Optional[str] = None
    responsibilities: Optional[str] = None
    screening_questions: list[IntakeQuestion] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:limit] or None


def _names(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else item
        cleaned = _text(name, 80)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def _int_in(value: Any, low: int, high: int) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", folded(value)).strip()


def _in_text(fragment: str, folded_text: str) -> bool:
    return _fold(fragment) in folded_text


def _questions(value: Any) -> list[IntakeQuestion]:
    if not isinstance(value, list):
        return []
    out: list[IntakeQuestion] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question = _text(item.get("question"), 500)
        if not question:
            continue
        out.append(
            IntakeQuestion(
                question=question,
                ideal_answer=_text(item.get("ideal_answer"), 500) or "",
                from_request=bool(item.get("from_request")),
            )
        )
        if len(out) >= MAX_QUESTIONS:
            break
    return out


def missing_fields(
    *,
    role_name: Optional[str],
    must: list[str],
    rate_budget_hourly: Optional[float],
    remote_policy: Optional[str],
    onsite_days_per_week: Optional[int],
    office_city: Optional[str],
    project_about: Optional[str],
    responsibilities: Optional[str],
    questions: list[IntakeQuestion],
) -> list[str]:
    """Braki wobec „Przekaż do searchu” — lustro `job_readiness`."""
    missing: list[str] = []
    if not role_name:
        missing.append(MISSING_ROLE)
    if not must:
        missing.append(MISSING_MUST)
    if rate_budget_hourly is None:
        missing.append(MISSING_BUDGET)
    if remote_policy is None:
        missing.append(MISSING_WORK_MODE)
    elif remote_policy in ("onsite", "hybrid"):
        if onsite_days_per_week is None:
            missing.append(MISSING_OFFICE_DAYS)
        if not office_city:
            missing.append(MISSING_OFFICE_CITY)
    if not (project_about or responsibilities):
        missing.append(MISSING_CONTEXT)
    if len([q for q in questions if q.question.strip()]) < 2:
        missing.append(MISSING_QUESTIONS)
    return missing


def normalize_model_output(raw: Any, request_text: str) -> RequestIntake:
    """Odpowiedź modelu → płaski, zweryfikowany kształt formularza."""
    data = raw if isinstance(raw, dict) else {}
    folded_text = _fold(request_text)

    rate_quote = _text(data.get("rate_quote"), 200)
    rate_budget: Optional[float] = None
    rate_note: Optional[str] = None
    if rate_quote and not _in_text(rate_quote, folded_text):
        rate_quote = None
    if rate_quote:
        read = champion_intake.document_rate(rate_quote)
        if read is None:
            rate_note = (
                f"W requeście jest „{rate_quote}” — to nie jest stawka w PLN/h "
                "netto. Wpisz budżet ręcznie."
            )
        else:
            rate_budget, _is_bound = read
            bounds = champion_intake.pln_hourly_bounds(rate_quote)
            # „do 170 zł/h” to po prostu budżet 170; notatka tylko przy
            # prawdziwym przedziale, bo tam budżetem jest jego GÓRA.
            if bounds and 0 < bounds[0] < bounds[1]:
                rate_note = f"„{rate_quote}” — przyjęto górną granicę jako budżet."

    work_mode = _text(data.get("work_mode"), 30)
    remote_policy = _WORK_MODES.get((work_mode or "").casefold())
    onsite_days = _int_in(data.get("onsite_days_per_week"), 0, 7)
    office_city = _text(data.get("office_city"), 120)
    if remote_policy == "remote":
        onsite_days = None
        office_city = None

    start_date = (
        champion_intake.date(data.get("start_date")) if data.get("start_date") else None
    )

    evidence: list[str] = []
    for fragment in data.get("evidence") or []:
        cleaned = _text(fragment, 300)
        if cleaned and len(cleaned) >= 2 and _in_text(cleaned, folded_text):
            evidence.append(cleaned)
        if len(evidence) >= MAX_EVIDENCE:
            break
    if rate_quote and rate_quote not in evidence:
        evidence.append(rate_quote)

    role_name = _text(data.get("role_name"), 255)
    must = _names(data.get("must"), MAX_MUST)
    nice = [
        n
        for n in _names(data.get("nice"), MAX_NICE)
        if n.casefold() not in {m.casefold() for m in must}
    ]
    project_about = _text(data.get("project_about"), 600)
    responsibilities = _text(data.get("responsibilities"), 2000)
    questions = _questions(data.get("screening_questions"))

    return RequestIntake(
        role_name=role_name,
        must=must,
        nice=nice,
        seniority_min_years=_int_in(data.get("seniority_min_years"), 0, 40),
        rate_budget_hourly=rate_budget,
        rate_quote=rate_quote,
        rate_note=rate_note,
        remote_policy=remote_policy,
        onsite_days_per_week=onsite_days,
        office_city=office_city,
        start_date=start_date,
        project_about=project_about,
        responsibilities=responsibilities,
        screening_questions=questions,
        evidence=evidence,
        missing=missing_fields(
            role_name=role_name,
            must=must,
            rate_budget_hourly=rate_budget,
            remote_policy=remote_policy,
            onsite_days_per_week=onsite_days,
            office_city=office_city,
            project_about=project_about,
            responsibilities=responsibilities,
            questions=questions,
        ),
    )


async def read_request(
    db: AsyncSession, *, client_id: int, request_text: str
) -> RequestIntake:
    """Jeden odczyt requestu przez model. Wołający otwiera `ai_feature`."""
    from app.services.champion_draft_service import _call_claude_json

    client = await db.scalar(select(Client).where(Client.id == client_id))
    client_name = (client.name if client else None) or "nieznany klient"
    text = request_text[:MAX_REQUEST_CHARS]
    raw = await _call_claude_json(
        prompt=JOB_REQUEST_INTAKE.render(client_name=client_name, request_text=text),
        system_prompt=JOB_REQUEST_INTAKE.system_prompt or "",
        max_tokens=3000,
    )
    return normalize_model_output(raw, text)
