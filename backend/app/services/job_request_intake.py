"""Nowa rekrutacja z requestu klienta — odczyt PRZED zapisem (strona /jobs/new).

Delivery Lead wkleja maila od klienta; model wypisuje z niego minimum, którego
wymaga „Przekaż do searchu” (`job_readiness.job_handoff_blockers`), a ten moduł
normalizuje odpowiedź do płaskiego kształtu formularza. Niczego nie zapisuje.

Zasady, które łatwo cofnąć „przy okazji”:

* **Budżet liczy kod, nie model.** Model cytuje fragment (`rate_quote`),
  a liczba powstaje z `champion_intake.pln_hourly_bounds` — gramatyki stawki
  PLN/h z importu dokumentu Championa. Stawka dzienna, w innej walucie, brutto
  albo goła liczba bez waluty i jednostki (REC-07) daje ``None`` i notatkę,
  nigdy przeliczoną liczbę.
* **Cytat musi być w tekście.** Fragment, którego nie ma w requeście (model
  go „poprawił”), nie jest dowodem — ani dla budżetu, ani dla podświetlenia.
* **Braki są jawne.** ``missing`` używa tych samych reguł co handoff: formularz
  pokazuje dokładnie to, co później by go zablokowało.
* **Od v2 model proponuje cały profil.** Fakty sekcji „Doświadczenie poza
  stackiem” (dziedzina, certyfikaty, regulacje) wchodzą wyłącznie z cytatem
  obecnym w mailu. Propozycje (frazy, firmy docelowe, argumenty, pytania do
  klienta) niosą ``provenance`` — formularz mówi DL, skąd pochodzą.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field, replace
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
MAX_EXPERIENCE = 8
MAX_ASK_CLIENT = 5
MAX_DISQUALIFIERS = 8
_BASES = ("request", "client_history", "ai")

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
    # ── od v2: reszta profilu Championa ──
    language: Optional[str] = None
    contract_length: Optional[str] = None
    experience: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"domains": [], "certifications": [], "regulations": []}
    )
    search_keywords: Optional[str] = None
    target_companies: Optional[str] = None
    disqualifiers: list[str] = field(default_factory=list)
    selling_points: Optional[str] = None
    ask_client: list[str] = field(default_factory=list)
    # Ścieżka pola formularza → "request" | "client_history" | "ai".
    provenance: dict[str, str] = field(default_factory=dict)
    # ── od v3 (0380): trzy nazwy rekrutacji ──
    # Dosłowne fragmenty zapytania: nazwa stanowiska od klienta i jego numer.
    client_title: Optional[str] = None
    client_reference: Optional[str] = None
    # Tytuł dla rekrutera złożony KODEM z pól wyżej (`job_working_title`).
    working_title_suggestion: Optional[str] = None
    # ── od v4 (25.09.2026): hiring manager z treści requestu ──
    # Dosłowne cytaty (zwykle podpis maila). `hiring_manager_contact_id` to
    # istniejący kontakt klienta dopasowany KODEM (`job_hiring_manager`) —
    # nazwy kontaktów nie trafiają do promptu.
    hiring_manager_name: Optional[str] = None
    hiring_manager_position: Optional[str] = None
    hiring_manager_email: Optional[str] = None
    hiring_manager_contact_id: Optional[int] = None

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


def _basis(value: Any, default: str = "ai") -> str:
    return value if isinstance(value, str) and value in _BASES else default


def _experience(value: Any, folded_text: str) -> dict[str, list[dict[str, Any]]]:
    """Pozycje sekcji 4 — WYŁĄCZNIE te, których cytat jest w mailu.

    Dziedzina czy certyfikat bez cytatu to zgadywanie modelu (np. „bankowość”
    wywnioskowana z nazwy klienta). Takiej pozycji nie pokazujemy wcale —
    DL dopisze ją sam, jeśli wie ze swojej rozmowy.
    """
    data = value if isinstance(value, dict) else {}
    out: dict[str, list[dict[str, Any]]] = {}
    for key in ("domains", "certifications", "regulations"):
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in data.get(key) or []:
            if not isinstance(raw, dict):
                continue
            name = _text(raw.get("name"), 120)
            quote = _text(raw.get("quote"), 300)
            if not name or not quote or not _in_text(quote, folded_text):
                continue
            if name.casefold() in seen:
                continue
            seen.add(name.casefold())
            items.append(
                {
                    "name": name,
                    "level": "nice" if raw.get("level") == "nice" else "must",
                    "min_years": _int_in(raw.get("min_years"), 0, 40)
                    if key == "domains"
                    else None,
                    "quote": quote,
                }
            )
            if len(items) >= MAX_EXPERIENCE:
                break
        out[key] = items
    return out


def _strings(value: Any, limit: int, cap: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        cleaned = _text(item, cap)
        if cleaned and cleaned not in out:
            out.append(cleaned)
        if len(out) >= limit:
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
        # Audyt 22.09 r2 (REC-07): tylko cytat z JAWNĄ walutą i jednostką
        # godzinową (`pln_hourly_bounds`). `document_rate` przyjmuje też gołą
        # liczbę („1100”), którą rekruter pisze równie często jako stawkę za MD
        # — budżet 1100 PLN/h to cicha pomyłka o rząd wielkości.
        bounds = champion_intake.pln_hourly_bounds(rate_quote)
        value = champion_intake.rate(bounds[1]) if bounds else None
        if value is None:
            rate_note = (
                f"W requeście jest „{rate_quote}” — to nie jest stawka w PLN/h "
                "netto (brak waluty albo jednostki). Wpisz budżet ręcznie."
            )
        else:
            rate_budget = value
            # „do 170 zł/h” to po prostu budżet 170; notatka tylko przy
            # prawdziwym przedziale, bo tam budżetem jest jego GÓRA.
            if 0 < bounds[0] < bounds[1]:
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
    # Nazwa i numer od klienta: tylko dosłowny fragment zapytania — inaczej
    # do CV i do Cpro poszłoby coś, czego klient nie napisał.
    client_title = _text(data.get("client_title"), 255)
    if client_title and not _in_text(client_title, folded_text):
        client_title = None
    client_reference = _text(data.get("client_reference"), 120)
    if client_reference and not _in_text(client_reference, folded_text):
        client_reference = None
    # Hiring manager: ta sama reguła dosłownego cytatu. Bez imienia i nazwiska
    # stanowisko i e-mail nie mają kogo opisać, więc odpadają razem z nim.
    hm_name = _text(data.get("hiring_manager_name"), 255)
    if hm_name and not _in_text(hm_name, folded_text):
        hm_name = None
    hm_position = _text(data.get("hiring_manager_position"), 255) if hm_name else None
    if hm_position and not _in_text(hm_position, folded_text):
        hm_position = None
    hm_email = _text(data.get("hiring_manager_email"), 255) if hm_name else None
    if hm_email and ("@" not in hm_email or not _in_text(hm_email, folded_text)):
        hm_email = None
    for quote in (client_title, client_reference, hm_name):
        if quote and quote not in evidence:
            evidence.append(quote)
    must = _names(data.get("must"), MAX_MUST)
    nice = [
        n
        for n in _names(data.get("nice"), MAX_NICE)
        if n.casefold() not in {m.casefold() for m in must}
    ]
    project_about = _text(data.get("project_about"), 600)
    responsibilities = _text(data.get("responsibilities"), 2000)
    questions = _questions(data.get("screening_questions"))

    experience = _experience(data.get("experience"), folded_text)
    for items in experience.values():
        for item in items:
            if item["quote"] not in evidence:
                evidence.append(item["quote"])
    search = data.get("search") if isinstance(data.get("search"), dict) else {}
    search_keywords = _text(search.get("keywords"), 500)
    target_companies = _text(search.get("target_companies"), 500)
    disqualifiers = _strings(search.get("disqualifiers"), MAX_DISQUALIFIERS, 200)
    selling_raw = data.get("selling_points")
    selling = selling_raw if isinstance(selling_raw, dict) else {}
    selling_points = _text(selling.get("text"), 800)
    ask_client = _strings(data.get("ask_client"), MAX_ASK_CLIENT, 300)

    provenance: dict[str, str] = {}
    for key, present in (
        ("role", role_name),
        ("must", must),
        ("nice", nice),
        ("seniority", data.get("seniority_min_years") is not None),
        ("rate", rate_budget is not None),
        ("work_mode", remote_policy),
        ("about", project_about),
        ("responsibilities", responsibilities),
        ("experience", any(experience.values())),
    ):
        if present:
            provenance[key] = "request"
    search_basis = _basis(search.get("basis"))
    for key, present in (
        ("search_keywords", search_keywords),
        ("target_companies", target_companies),
        ("disqualifiers", disqualifiers),
    ):
        if present:
            provenance[key] = search_basis
    if selling_points:
        provenance["selling_points"] = _basis(selling.get("basis"))
    if questions:
        provenance["questions"] = (
            "request" if all(q.from_request for q in questions) else "ai"
        )
    if ask_client:
        provenance["ask_client"] = "ai"
    for key, present in (
        ("client_title", client_title),
        ("client_reference", client_reference),
        ("hiring_manager", hm_name),
    ):
        if present:
            provenance[key] = "request"

    from app.services.job_working_title import compose_working_title

    seniority_min_years = _int_in(data.get("seniority_min_years"), 0, 40)
    working_title_suggestion = compose_working_title(
        role_name,
        must,
        seniority_min_years,
        next(
            (
                d["name"]
                for d in experience.get("domains", [])
                if d.get("level") == "must"
            ),
            None,
        ),
    )

    return RequestIntake(
        role_name=role_name,
        must=must,
        nice=nice,
        seniority_min_years=seniority_min_years,
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
        language=_text(data.get("language"), 50),
        contract_length=_text(data.get("contract_length"), 255),
        experience=experience,
        search_keywords=search_keywords,
        target_companies=target_companies,
        disqualifiers=disqualifiers,
        selling_points=selling_points,
        ask_client=ask_client,
        provenance=provenance,
        client_title=client_title,
        client_reference=client_reference,
        working_title_suggestion=working_title_suggestion,
        hiring_manager_name=hm_name,
        hiring_manager_position=hm_position,
        hiring_manager_email=hm_email,
    )


async def read_request(
    db: AsyncSession, *, client_id: int, request_text: str
) -> RequestIntake:
    """Jeden odczyt requestu przez model. Wołający otwiera `ai_feature`."""
    from app.services.champion_draft_service import _call_claude_json

    from app.services.champion_client_context import (
        load_client_context,
        render_client_context,
    )
    from app.services.prompt_fencing import neutralize_tags

    client = await db.scalar(select(Client).where(Client.id == client_id))
    client_name = (client.name if client else None) or "nieznany klient"
    text = request_text[:MAX_REQUEST_CHARS]
    try:
        # Savepoint: padnięte zapytanie nie może zostawić sesji w przerwanej
        # transakcji, w której `ai_feature` zapisuje zużycie.
        async with db.begin_nested():
            context = await load_client_context(
                db, client_id=client_id, request_text=text
            )
    except Exception:  # noqa: BLE001 — kontekst to dodatek, nie warunek odczytu
        logger.warning("job_request_intake: client context unavailable", exc_info=True)
        context = None
    raw = await _call_claude_json(
        prompt=JOB_REQUEST_INTAKE.render(
            client_name=client_name,
            client_context=render_client_context(context),
            request_text=neutralize_tags(text),
        ),
        system_prompt=JOB_REQUEST_INTAKE.system_prompt or "",
        max_tokens=6000,
    )
    return await match_hiring_manager(
        db, client_id=client_id, intake=normalize_model_output(raw, text)
    )


async def match_hiring_manager(
    db: AsyncSession, *, client_id: int, intake: RequestIntake
) -> RequestIntake:
    """Wskazuje istniejący kontakt klienta, jeśli to ta sama osoba co w mailu.

    Tym samym matcherem co zapis HM (`job_hiring_manager`), żeby podpowiedź
    i zapis nie rozjechały się (podpowiedź „nowa osoba”, zapis „istniejący”).
    Awaria dopasowania nie psuje odczytu — zostaje sama podpowiedź nazwiska.
    """
    if not intake.hiring_manager_name:
        return intake
    from app.services.job_hiring_manager import match_client_contact

    try:
        async with db.begin_nested():
            contact = await match_client_contact(
                db,
                client_id=client_id,
                name=intake.hiring_manager_name,
                email=intake.hiring_manager_email,
            )
    except Exception:  # noqa: BLE001 — podpowiedź to dodatek, nie warunek odczytu
        logger.warning("job_request_intake: hiring manager match failed", exc_info=True)
        return intake
    if contact is None:
        return intake
    return replace(intake, hiring_manager_contact_id=contact.id)
