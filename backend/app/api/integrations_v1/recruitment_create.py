"""Zakładanie rekrutacji z requestu klienta w API v1 (15.10.2026).

Scope ``recruitments:create``. Dwie trasy, te same ciała co ``/jobs/new``:

* **Odczyt requestu** (``POST /recruitments/read-request``) — ten sam odczyt
  AI co ``POST /api/job-intake/read`` (``job_request_intake._read``: prompt
  ``JOB_REQUEST_INTAKE``, funkcja ``champion_draft`` z rejestru modeli
  w ``ai_feature``, kontekst klienta, hiring manager dopasowany KODEM do
  kontaktów klienta). Niczego nie zapisuje. Wynik to propozycja w kształcie
  ciała ``POST /recruitments`` i braki wobec bramki „Przekaż do searchu”.
  Awaria modelu = 200 z pustą propozycją i ``ai_failed: true`` — wynik AI jest
  podpowiedzią, nigdy warunkiem. Limit tempa jak zapis (płatny model).
* **Założenie** (``POST /recruitments``) — ``job_lifecycle.apply_job_create``,
  to samo ciało co ``POST /api/jobs`` po „Utwórz i opublikuj”: wiersz
  rekrutacji, hiring manager, Profil Championa, bramka przekazania (422
  ``job_not_ready`` z listą braków ``details.blockers``), przekazanie
  (rekruter albo automat), publikacja — jedna transakcja, bez szkiców. Ciało
  v1 przechodzi na ``JobCreate`` tak, jak robi to formularz
  (``buildCreateJobPayload`` w ``lib/job-request-intake.ts``).

Decyzje dla kluczy (15.10.2026):

- autor = konto serwisowe: ``jobs.created_by`` i ``Activity.user_id`` puste,
  ``details.via`` ze stempla klucza, bez ``UserActivity``. Rdzenie dostają
  ``IntegrationActor`` i nie przechodzą bramek ról ekranu (zakres Delivery
  Leada, redaktor Championa) — o prawie decyduje scope;
- Delivery Lead jest wymagany (``delivery_lead_id``, walidacja jak wskazanie
  DL-a na ekranie) i dostaje dzwonek „Nowa rekrutacja z integracji” z nazwą
  konta — na ekranie zakłada ją zwykle sam DL, tu nikt z ludzi nie kliknął.
  Rekruter dostaje dzwonek ekranu „Nowy request do pracy”;
- klient: widoczny (ukryty, zarchiwizowany, scalony, usunięty = 404) i do
  wyboru na ``/jobs/new`` — zakładka „Aktywni” albo „Relacyjni”
  (422 ``client_not_selectable``);
- budżet (``rate_budget_hourly``, ``rate_budget_hourly_min``) to koszt —
  zapis tylko z ``amounts:write`` (403 ``insufficient_scope`` z ``fields``).
  Budżet jest warunkiem bramki przekazania, więc klucz zakładający
  rekrutacje potrzebuje w praktyce ``recruitments:create`` i ``amounts:write``.
  Budżet w propozycji odczytu pochodzi wyłącznie z cytatu z przysłanej treści
  (kod odrzuca cytat spoza tekstu), więc nie jest kwotą NEXUSA — bez redakcji;
- hiring manager: istniejący kontakt klienta albo „Klient nie podał” —
  nowej osoby (zapis kontaktu klienta) klucz nie zakłada;
- jeden rekruter, jak na ``/jobs/new``; bez niego automat przydziału (409,
  gdy automat jest wyłączony — jak na ekranie). Kolejne osoby dopisuje się
  w panelu „Zespół”;
- kategorii kompetencji nie zgadujemy przy zapisie (potwierdza ją człowiek
  albo automat podaje ją wprost) — podpowiedź niesie odczyt requestu;
- świadomie węziej niż ekran: bez szablonu (``from_job_id``), podobnych
  rekrutacji, plików, sekcji 4 Championa, wykluczeń searchu i notatek
  „do dopytania u klienta”;
- ``dry_run=true``: cały łańcuch z bramką i wycofanie, bez efektów po commicie.

Efekty po commicie jak na ekranie (``run_post_commit``): wektor rekrutacji,
migawka dopasowań, przeliczenie dopasowań, Targ, podobne rekrutacje.
Powtórka z tym samym ``Idempotency-Key`` oddaje paragon bez efektów.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import logging
from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import job_request_intake as intake_routes
from app.api.integrations_v1.common import (
    INT4_MAX,
    IntegrationRoute,
    Money,
    RecruitmentsCreate,
    dry_run_response,
    idempotent_write,
    integration_actor,
    principal_of,
    principal_rate_key,
    write_rate_limit,
)
from app.api.write_policy import _insufficient_scope
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.client import Client
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.competence_category import CompetenceCategory
from app.models.job import Job
from app.models.service_account import ServiceScope
from app.schemas.champion import CRITICAL_MAX
from app.schemas.job import JobCreate
from app.services import job_lifecycle
from app.services import job_request_intake as intake
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)
from app.services.integration_actor import IntegrationActor
from app.services.job_budget_range import MSG_MIN_NOT_BELOW_MAX, min_below_max
from app.services.job_priority import priorities_for_levels
from app.services.office_days import MSG_MONTHLY_NOT_HYBRID

logger = logging.getLogger(__name__)

router = APIRouter(route_class=IntegrationRoute)

#: Pola z kwotą (koszt: budżet dla kandydata) — zapis wymaga ``amounts:write``.
AMOUNT_FIELDS = ("rate_budget_hourly", "rate_budget_hourly_min")
# Wiersze jak w edytorze: 10 obowiązkowych + 20 mile widzianych.
MAX_REQUIREMENT_ROWS = 30
MAX_SCREENING_QUESTIONS = 10
_CHAMPION_WORK_MODE = {
    "remote": "zdalnie",
    "hybrid": "hybrydowo",
    "onsite": "stacjonarnie",
}
_SELECTABLE_CATEGORIES = (PortfolioCategory.active, PortfolioCategory.relationship)
AI_FAILED_NOTE = (
    "Odczyt AI nie powiódł się — uzupełnij pola sam albo spróbuj ponownie za chwilę."
)

# ── Wejście ──────────────────────────────────────────────────────────────────

Word = Annotated[str, Field(min_length=1, max_length=100)]
RemotePolicyIn = Literal["onsite", "hybrid", "remote"]


class RequirementRowIn(BaseModel):
    """Wiersz wymagań: słowa = warianty (wystarczy jedno z nich), poziom."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    words: list[Word] = Field(..., min_length=1, max_length=20)
    level: Literal["critical", "must", "nice"] = Field(
        "must",
        description="critical (najwyżej 3 — ukrywają kandydatów bez nich) | "
        "must | nice.",
    )


class ScreeningQuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(..., min_length=1, max_length=500)
    ideal_answer: str = Field("", max_length=500)
    deal_breaker: str = Field(
        "",
        max_length=500,
        description="Odpowiedź, która dyskwalifikuje — bramka przekazania "
        "wymaga jej przy każdym pytaniu.",
    )


class RecruitmentCreateIn(BaseModel):
    """Pola, które osoba wysyła z ``/jobs/new`` przyciskiem „Utwórz i opublikuj”.

    Bramka przekazania (rola, wymagania, budżet, tryb pracy, opis projektu,
    2 pytania z odpowiedzią dyskwalifikującą, decyzja o krytycznych, hiring
    manager, termin, kategoria, liczba osób) sprawdza komplet — brak = 422
    ``job_not_ready`` i nic nie powstaje."""

    # Literówka w nazwie pola nie może przejść po cichu jako „brak wartości”.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_id: int = Field(..., ge=1, le=INT4_MAX)
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Nazwa stanowiska od klienta — idzie do klienta (CV, nazwa pliku).",
    )
    role_name: Optional[str] = Field(
        None, max_length=255, description="Rola (Profil Championa); brak = title."
    )
    client_reference: Optional[str] = Field(
        None,
        max_length=120,
        description="Numer zapytania klienta (ZOB, SAP…). Brak = serwer czyta "
        "numer z tytułu; pusty napis = bez numeru.",
    )
    working_title: Optional[str] = Field(
        None,
        max_length=255,
        description="Tytuł dla rekrutera; brak = składa go serwer i przelicza.",
    )
    delivery_lead_id: int = Field(
        ..., ge=1, le=INT4_MAX, description="Delivery Lead, który prowadzi request."
    )
    recruiter_id: Optional[int] = Field(
        None,
        ge=1,
        le=INT4_MAX,
        description="Rekruter (rola rekrutera). Brak = automat przydziału.",
    )
    priority: Literal["p1", "p2", "accepting"] = "p1"
    competence_category_id: Optional[int] = Field(
        None,
        ge=1,
        le=INT4_MAX,
        description="Kategoria kompetencji (podpowiedź: odczyt requestu).",
    )
    requirements: list[RequirementRowIn] = Field(
        default_factory=list, max_length=MAX_REQUIREMENT_ROWS
    )
    no_critical: bool = Field(
        False,
        description="Świadome „Brak krytycznych” — gdy żaden wiersz nie jest critical.",
    )
    descriptive_requirements: list[Annotated[str, Field(max_length=1000)]] = Field(
        default_factory=list,
        max_length=20,
        description="Zdania klienta, które nie są słowami kluczowymi.",
    )
    seniority_min_years: Optional[int] = Field(None, ge=0, le=60)
    language: Optional[str] = Field(None, max_length=100)
    contract_length: Optional[str] = Field(None, max_length=255)
    start_date: Optional[str] = Field(None, max_length=100)
    rate_budget_hourly: Optional[float] = Field(
        None, gt=0, le=2000, description="Budżet dla kandydata „do”, PLN/h."
    )
    rate_budget_hourly_min: Optional[float] = Field(
        None, gt=0, le=2000, description="„Od” przedziału budżetu, PLN/h."
    )
    remote_policy: Optional[RemotePolicyIn] = None
    onsite_days_per_week: Optional[int] = Field(None, ge=0, le=7)
    onsite_days_per_month: Optional[int] = Field(
        None, ge=1, le=22, description="Tylko przy pracy hybrydowej."
    )
    location: Optional[str] = Field(
        None, max_length=255, description="Miasta biura po przecinku."
    )
    deadline: Optional[date] = None
    deadline_time: Optional[time] = None
    deadline_not_provided: bool = Field(
        False, description="„Klient nie podał terminu”."
    )
    headcount: Optional[int] = Field(None, ge=1, le=1000)
    hiring_manager_contact_id: Optional[int] = Field(
        None, ge=1, le=INT4_MAX, description="Kontakt klienta tej rekrutacji."
    )
    hiring_manager_not_provided: bool = Field(
        False, description="„Klient nie podał hiring managera”."
    )
    description: Optional[str] = Field(
        None,
        max_length=intake.MAX_REQUEST_CHARS,
        description="Treść requestu od klienta.",
    )
    project_about: Optional[str] = Field(None, max_length=5000)
    responsibilities: Optional[str] = Field(None, max_length=5000)
    selling_points: Optional[str] = Field(None, max_length=2000)
    screening_questions: list[ScreeningQuestionIn] = Field(
        default_factory=list, max_length=MAX_SCREENING_QUESTIONS
    )


class RecruitmentCreatedOut(BaseModel):
    job_id: int
    reference_number: Optional[str]
    notices: list[str] = Field(
        default_factory=list,
        description="Uwagi zapisu wymagań (np. zdanie przeniesione do „Rekruter "
        "sprawdza w rozmowie”).",
    )


class ReadRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: int = Field(..., ge=1, le=INT4_MAX)
    text: str = Field(
        ...,
        min_length=intake.MIN_REQUEST_CHARS,
        max_length=intake.MAX_REQUEST_CHARS,
        description="Treść requestu od klienta (mail, opis stanowiska).",
    )


class ProposalRequirementRowOut(BaseModel):
    words: list[str]
    level: str = Field(description="must | nice (krytyczne wybiera człowiek)")


class ProposalScreeningQuestionOut(BaseModel):
    question: str
    ideal_answer: str
    deal_breaker: str


class ProposalOut(BaseModel):
    """Propozycja pól w kształcie ciała ``POST /recruitments``."""

    client_id: int
    title: Optional[str] = Field(description="Nazwa od klienta — dosłownie z treści.")
    role_name: Optional[str]
    client_reference: Optional[str]
    requirements: list[ProposalRequirementRowOut]
    descriptive_requirements: list[str]
    seniority_min_years: Optional[int]
    language: Optional[str]
    contract_length: Optional[str]
    start_date: Optional[str]
    rate_budget_hourly: Money
    rate_budget_hourly_min: Money
    remote_policy: Optional[str]
    onsite_days_per_week: Optional[int]
    onsite_days_per_month: Optional[int]
    location: Optional[str]
    deadline: Optional[date]
    deadline_time: Optional[time]
    headcount: Optional[int]
    hiring_manager_contact_id: Optional[int]
    competence_category_id: Optional[int]
    description: str
    project_about: Optional[str]
    responsibilities: Optional[str]
    selling_points: Optional[str]
    screening_questions: list[ProposalScreeningQuestionOut]


class ReadHintsOut(BaseModel):
    working_title_suggestion: Optional[str]
    hiring_manager_name: Optional[str] = Field(
        description="Osoba z treści (albo pisownia dopasowanego kontaktu)."
    )
    hiring_manager_position: Optional[str]
    competence_category_name: Optional[str]
    dropped_requirements: list[str] = Field(
        description="Wiersze, które nie zmieściły się w limitach."
    )


class ReadRequestOut(BaseModel):
    proposal: ProposalOut
    missing: list[str] = Field(
        description="Braki wobec bramki przekazania: role, must, budget, "
        "work_mode, office_days, office_city, context, questions, search, "
        "critical, deal_breaker."
    )
    notes: list[str]
    hints: ReadHintsOut
    ai_failed: bool = Field(
        description="Model nie odpowiedział — propozycja jest pusta, a zapis "
        "i tak jest możliwy."
    )


# ── Reguły (czyste funkcje) ──────────────────────────────────────────────────


def _validation_error(errors: list[dict[str, Any]]) -> HTTPException:
    """422 w kształcie walidacji v1 (jak ``RequestValidationError``)."""
    return HTTPException(
        422,
        detail={
            "error": "validation_error",
            "message": "Nieprawidłowe dane żądania.",
            "errors": errors,
        },
    )


def input_errors(body: RecruitmentCreateIn) -> list[dict[str, Any]]:
    """Decyzje, które formularz wymusza kontrolkami — tu błędy przy polach."""
    errors: list[dict[str, Any]] = []

    def add(field: str, message: str) -> None:
        errors.append({"loc": ["body", field], "msg": message, "type": "value_error"})

    if (body.hiring_manager_contact_id is not None) == body.hiring_manager_not_provided:
        add(
            "hiring_manager_contact_id",
            "Wskaż hiring managera (kontakt klienta) albo "
            "hiring_manager_not_provided: true — dokładnie jedno.",
        )
    if body.deadline is not None and body.deadline_not_provided:
        add("deadline_not_provided", "Podaj termin albo „Klient nie podał” — nie oba.")
    if body.deadline_time is not None and body.deadline is None:
        add("deadline_time", "Godzina terminu wymaga daty (deadline).")
    if body.rate_budget_hourly_min is not None:
        if body.rate_budget_hourly is None:
            add(
                "rate_budget_hourly_min",
                "„Od” podaje się razem z budżetem „do” (rate_budget_hourly).",
            )
        elif not min_below_max(body.rate_budget_hourly_min, body.rate_budget_hourly):
            add("rate_budget_hourly_min", MSG_MIN_NOT_BELOW_MAX)
    if body.onsite_days_per_week is not None and body.onsite_days_per_month is not None:
        add(
            "onsite_days_per_month",
            "Podaj dni w biurze w tygodniu albo w miesiącu — nie oba.",
        )
    elif body.onsite_days_per_month is not None and body.remote_policy != "hybrid":
        add("onsite_days_per_month", MSG_MONTHLY_NOT_HYBRID)
    critical = sum(row.level == "critical" for row in body.requirements)
    if critical > CRITICAL_MAX:
        add(
            "requirements",
            f"Krytyczne mogą być najwyżej {CRITICAL_MAX} wymagania.",
        )
    if critical and body.no_critical:
        add("no_critical", "„Brak krytycznych” przy wierszach krytycznych.")
    return errors


def budget_fields_without_scope(
    body: RecruitmentCreateIn, scopes: frozenset[str]
) -> list[str]:
    """Pola kwot w żądaniu, których klucz nie może zapisać (``amounts:write``)."""
    if ServiceScope.amounts_write.value in scopes:
        return []
    return [field for field in AMOUNT_FIELDS if getattr(body, field) is not None]


def _row_head(words: list[str]) -> str:
    """Pierwsze słowo bez gwiazdki — jak ``rowHead`` formularza."""
    for word in words:
        if not word.endswith("*"):
            return word
    return words[0].rstrip("*").strip() if words else ""


def _champion_payload(body: RecruitmentCreateIn) -> dict[str, Any]:
    """Profil Championa jak ``buildChampionPayload`` formularza."""
    remote = body.remote_policy
    office = remote != "remote"
    rows = [{"words": list(row.words), "level": row.level} for row in body.requirements]
    has_critical = any(row["level"] == "critical" for row in rows)
    basics: dict[str, Any] = {
        "role_name": body.role_name or body.title,
        "rate_value": body.rate_budget_hourly,
        "work_mode": _CHAMPION_WORK_MODE[remote] if remote else None,
        "onsite_days_per_week": body.onsite_days_per_week if office else None,
        "onsite_days_per_month": body.onsite_days_per_month if office else None,
        "candidate_location_pref": (body.location or None) if office else None,
        "start_date": body.start_date or None,
        "language": body.language or None,
        "contract_length": body.contract_length or None,
    }
    if body.seniority_min_years is not None:
        basics["seniority_min_years"] = body.seniority_min_years
    # Krytyczne serwer bierze z poziomów wierszy; bez nich `[]` = świadome
    # „Brak krytycznych”, `None` = nie zdecydowano (bramka może odmówić).
    stack: dict[str, Any] = {
        "rows": rows,
        "critical": [] if not has_critical and body.no_critical else None,
    }
    if body.descriptive_requirements:
        stack["notes"] = "\n".join(body.descriptive_requirements)
    return {
        "basics": basics,
        "stack": stack,
        "project": {
            "about": body.project_about or "",
            "responsibilities": body.responsibilities or "",
        },
        "client": {"selling_points": body.selling_points or ""},
        "screening_questions": [
            {
                "id": f"q{index}",
                "question": question.question,
                "ideal_answer": question.ideal_answer,
                "deal_breaker": question.deal_breaker,
            }
            for index, question in enumerate(body.screening_questions, start=1)
        ],
    }


def job_create_payload(body: RecruitmentCreateIn) -> dict[str, Any]:
    """Ciało ``POST /api/jobs`` z pól v1 — jak ``buildCreateJobPayload``."""
    remote = body.remote_policy
    office = remote != "remote"
    deadline = None if body.deadline_not_provided else body.deadline
    payload: dict[str, Any] = {
        "title": body.title,
        "client_id": body.client_id,
        "auto_suggest_cc": True,
        "remote_policy": remote,
        "onsite_days_per_week": body.onsite_days_per_week if office else None,
        "onsite_days_per_month": body.onsite_days_per_month if office else None,
        "deadline": deadline,
        "deadline_time": body.deadline_time if deadline is not None else None,
        "deadline_not_provided": body.deadline_not_provided,
        # Pole jedzie zawsze — brak liczby osób to decyzja „nie podano”, którą
        # bramka odrzuca (`headcount`), a nie domyślne 1.
        "headcount": body.headcount,
        "priority": priorities_for_levels([body.priority])[0],
        "delivery_lead_id": body.delivery_lead_id,
        "champion_profile": _champion_payload(body),
        "hiring_manager": (
            {"not_provided": True}
            if body.hiring_manager_not_provided
            else {"contact_id": body.hiring_manager_contact_id}
        ),
        "handoff": (
            {"recruiter_id": body.recruiter_id, "channel": "linkedin"}
            if body.recruiter_id is not None
            else {"assignment_mode": "automatic", "channel": "linkedin"}
        ),
        "similar_job_ids": [],
        "cc_override": None,
        "intake_form_id": None,
    }
    if body.description:
        payload["description"] = body.description
    # Pusty napis = „To nie ten numer” (bez numeru); brak pola = numer z tytułu.
    if body.client_reference is not None:
        payload["client_reference"] = body.client_reference
    if body.competence_category_id is not None:
        payload["competence_category_id"] = body.competence_category_id
    if body.working_title:
        payload["working_title"] = body.working_title
    must = [
        _row_head(list(row.words))
        for row in body.requirements
        if row.level in ("critical", "must")
    ]
    nice = [
        _row_head(list(row.words)) for row in body.requirements if row.level == "nice"
    ]
    if must:
        payload["must_skills"] = must
    if nice:
        payload["nice_skills"] = nice
    if office and body.location:
        payload["location"] = body.location
    for field in AMOUNT_FIELDS:
        if getattr(body, field) is not None:
            payload[field] = getattr(body, field)
    return payload


def screen_job_create(body: RecruitmentCreateIn) -> JobCreate:
    """``JobCreate`` ekranu — jego walidatory jako 422 v1, nie 500."""
    errors = input_errors(body)
    if errors:
        raise _validation_error(errors)
    try:
        return JobCreate.model_validate(job_create_payload(body))
    except ValidationError as exc:
        raise _validation_error(
            [
                {
                    "loc": ["body", *err.get("loc", ())],
                    "msg": err.get("msg"),
                    "type": err.get("type"),
                }
                for err in exc.errors()
            ]
        ) from None


def _client_title_with_reference(
    title: Optional[str], reference: Optional[str]
) -> Optional[str]:
    """Nazwa od klienta z numerem w nawiasie, gdy numeru w niej nie ma —
    jak ``clientTitleWithReference`` formularza."""
    base = (title or "").strip()
    ref = " ".join((reference or "").split())
    if not base:
        return None
    if not ref or ref.casefold() in base.casefold():
        return base
    return f"{base} ({ref})"


def _money(value: Any) -> Optional[Decimal]:
    return Decimal(str(value)) if value is not None else None


def read_response(client_id: int, text: str, read: Optional[dict]) -> dict[str, Any]:
    """Odpowiedź ``read-request`` z odczytu ekranu (``RequestIntake.as_dict``).

    ``read=None`` (awaria modelu) = pusta propozycja z treścią requestu jako
    opisem i pełną listą braków — zapis i tak jest możliwy."""
    ai_failed = read is None
    data: dict[str, Any] = (
        read
        or intake.RequestIntake(
            missing=intake.missing_fields(
                role_name=None,
                must=[],
                rate_budget_hourly=None,
                remote_policy=None,
                onsite_days_per_week=None,
                office_city=None,
                project_about=None,
                responsibilities=None,
                questions=[],
                search_requirements=[],
            )
        ).as_dict()
    )
    remote = data.get("remote_policy")
    cities = [city for city in data.get("office_cities") or [] if city]
    location = ", ".join(cities) if cities else data.get("office_city")
    # Dni w biurze: jedno z dwóch, jak pole formularza — przy wpisie
    # miesięcznym liczbę tygodniową wylicza serwer przy zapisie.
    per_month = data.get("onsite_days_per_month")
    per_week = None if per_month is not None else data.get("onsite_days_per_week")
    notes = list(data.get("advisories") or [])
    if data.get("rate_note"):
        notes.append(data["rate_note"])
    if ai_failed:
        notes.append(AI_FAILED_NOTE)
    hm_name = data.get("hiring_manager_contact_name") or data.get("hiring_manager_name")
    return {
        "proposal": {
            "client_id": client_id,
            "title": _client_title_with_reference(
                data.get("client_title"), data.get("client_reference")
            ),
            "role_name": data.get("role_name"),
            "client_reference": data.get("client_reference"),
            "requirements": [
                {"words": list(row.get("words") or []), "level": row.get("level")}
                for row in data.get("requirements") or []
                if row.get("words")
            ],
            "descriptive_requirements": list(
                data.get("descriptive_requirements") or []
            ),
            "seniority_min_years": data.get("seniority_min_years"),
            "language": data.get("language"),
            "contract_length": data.get("contract_length"),
            "start_date": data.get("start_date"),
            "rate_budget_hourly": _money(data.get("rate_budget_hourly")),
            "rate_budget_hourly_min": _money(data.get("rate_budget_hourly_min")),
            "remote_policy": remote,
            "onsite_days_per_week": per_week,
            "onsite_days_per_month": per_month,
            "location": None if remote == "remote" else (location or None),
            "deadline": data.get("deadline"),
            "deadline_time": data.get("deadline_time")
            if data.get("deadline")
            else None,
            "headcount": data.get("headcount"),
            "hiring_manager_contact_id": data.get("hiring_manager_contact_id"),
            "competence_category_id": None,
            "description": text,
            "project_about": data.get("project_about"),
            "responsibilities": data.get("responsibilities"),
            "selling_points": data.get("selling_points"),
            "screening_questions": [
                {
                    "question": question.get("question") or "",
                    "ideal_answer": question.get("ideal_answer") or "",
                    "deal_breaker": question.get("deal_breaker") or "",
                }
                for question in data.get("screening_questions") or []
                if question.get("question")
            ],
        },
        "missing": list(data.get("missing") or []),
        "notes": notes,
        "hints": {
            "working_title_suggestion": data.get("working_title_suggestion"),
            "hiring_manager_name": hm_name,
            "hiring_manager_position": data.get("hiring_manager_position"),
            "competence_category_name": None,
            "dropped_requirements": list(data.get("dropped") or []),
        },
        "ai_failed": ai_failed,
    }


# ── Baza ─────────────────────────────────────────────────────────────────────


async def _assert_visible_client(db: AsyncSession, client_id: int) -> None:
    """Klient ukryty, zarchiwizowany, scalony albo usunięty nie istnieje dla
    klucza (jak ``GET /clients``)."""
    found = await db.scalar(
        select(Client.id).where(Client.id == client_id, *visible_client_predicates())
    )
    if found is None:
        raise HTTPException(404, detail="Klient nie istnieje.")


async def _assert_selectable_client(db: AsyncSession, client_id: int) -> None:
    """Rekrutację zakłada się u klienta z wyboru ``/jobs/new`` — zakładka
    „Aktywni” albo „Relacyjni” (``clients-lookup?contract_eligible=true``)."""
    category = func.coalesce(
        ClientPortfolioScope.category_override, ClientPortfolioScope.category
    )
    found = await db.scalar(
        select(ClientPortfolioScope.id)
        .where(
            ClientPortfolioScope.client_id == client_id,
            ClientPortfolioScope.archived_at.is_(None),
            category.in_(_SELECTABLE_CATEGORIES),
        )
        .limit(1)
    )
    if found is None:
        raise HTTPException(
            422,
            detail={
                "error": "client_not_selectable",
                "message": "Rekrutację zakłada się u klienta z zakładki "
                "„Aktywni” albo „Relacyjni” — jak wybór klienta na ekranie "
                "nowej rekrutacji.",
            },
        )


async def _assert_active_category(db: AsyncSession, category_id: Optional[int]) -> None:
    """Kategoria tylko z aktywnych — jak lista na ``/jobs/new``. Nieaktywna
    dopisałaby swoich członków jako współpracowników (``sync_cc_participants``)."""
    if category_id is None:
        return
    active = await db.scalar(
        select(CompetenceCategory.is_active).where(CompetenceCategory.id == category_id)
    )
    if not active:
        raise HTTPException(
            422,
            detail={
                "error": "category_not_active",
                "message": "Kategoria kompetencji nie istnieje albo jest nieaktywna.",
            },
        )


async def _read_with_ai(db: AsyncSession, client_id: int, text: str) -> Optional[dict]:
    """Odczyt ekranu (``job_request_intake._read``) albo ``None`` przy awarii.

    Każda awaria odczytu (model, limit, odpowiedź nie do odczytania) to
    podpowiedź, której nie ma — w logu sama klasa wyjątku, bez treści."""
    try:
        return await intake_routes._read(db, None, client_id, text)
    except Exception as exc:  # noqa: BLE001 — wynik AI nigdy nie jest warunkiem
        logger.warning(
            "integrations_v1: read-request bez odczytu AI: %s", type(exc).__name__
        )
        await db.rollback()
        return None


async def _suggest_category(
    db: AsyncSession, proposal: dict[str, Any], text: str
) -> tuple[Optional[int], Optional[str]]:
    """Podpowiedź kategorii jak ``POST /api/job-intake/category-suggestion``."""
    from app.models.competence_category import CompetenceCategory
    from app.services.job_cc import resolve_job_cc_id

    title = " ".join(
        part.strip()
        for part in (proposal.get("role_name"), proposal.get("title"))
        if part and part.strip()
    )
    if not title:
        return None, None
    rows = proposal.get("requirements") or []
    try:
        async with db.begin_nested():
            cc_id = await resolve_job_cc_id(
                SimpleNamespace(
                    id=None,
                    title=title,
                    description=text,
                    requirements=None,
                    subcategory=None,
                    industry=None,
                    must_skills=[
                        _row_head(r["words"]) for r in rows if r["level"] != "nice"
                    ],
                    nice_skills=[
                        _row_head(r["words"]) for r in rows if r["level"] == "nice"
                    ],
                ),
                db,
            )
            if cc_id is None:
                return None, None
            name = await db.scalar(
                select(CompetenceCategory.name_pl).where(
                    CompetenceCategory.id == cc_id,
                    CompetenceCategory.is_active.is_(True),
                )
            )
    except Exception:  # noqa: BLE001 — podpowiedź to dodatek, decyduje wołający
        logger.warning(
            "integrations_v1: podpowiedź kategorii nie wyszła", exc_info=True
        )
        return None, None
    return (cc_id, name) if name is not None else (None, None)


async def _notify_delivery_lead(
    db: AsyncSession, job: Job, actor: IntegrationActor
) -> None:
    """Dzwonek dla Delivery Leada: rekrutację założyła integracja, nie on.

    Ten sam typ co przydział requestu (``request_assignment_changed``).
    Savepoint: nieudany dzwonek nie cofa założenia."""
    from app.models.notification import NotificationType
    from app.services.job_working_title import display_title
    from app.services.notification_triggers import emit

    if job.delivery_lead_id is None:
        return
    client_name = await db.scalar(
        select(client_display_name_expression()).where(Client.id == job.client_id)
    )
    title = display_title(job)
    where = f"{title} · {client_name}" if client_name else title
    try:
        async with db.begin_nested():
            await emit(
                db,
                user_id=job.delivery_lead_id,
                title="Nowa rekrutacja z integracji",
                message=f"{actor.name} założyła rekrutację: {where}",
                ntype=NotificationType.request_assignment_changed,
                related_entity_type="job",
                related_entity_id=job.id,
                link=f"/jobs/{job.id}",
            )
    except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć założenia
        logger.exception(
            "integrations_v1: dzwonek dla Delivery Leada nie wyszedł job=%s", job.id
        )


# ── Trasy ────────────────────────────────────────────────────────────────────


@router.post(
    "/recruitments/read-request",
    response_model=ReadRequestOut,
    summary="Odczytaj request klienta (AI)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def read_recruitment_request(
    request: Request,
    body: ReadRequestIn,
    caller: RecruitmentsCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ten sam odczyt AI co „Wklej treść” na ekranie nowej rekrutacji. Niczego
    nie zapisuje: oddaje propozycję pól w kształcie ``POST /recruitments``
    (budżet tylko z cytatu z treści, hiring manager dopasowany do kontaktów
    klienta, podpowiedź kategorii), braki wobec bramki przekazania i uwagi.
    Krytycznych nie wybiera — to decyzja człowieka. Awaria modelu = 200
    z pustą propozycją i ``ai_failed: true``. Klient ukryty albo usunięty → 404."""
    await _assert_visible_client(db, body.client_id)
    read = await _read_with_ai(db, body.client_id, body.text)
    out = read_response(body.client_id, body.text, read)
    if read is not None:
        cc_id, cc_name = await _suggest_category(db, out["proposal"], body.text)
        out["proposal"]["competence_category_id"] = cc_id
        out["hints"]["competence_category_name"] = cc_name
    return out


@router.post(
    "/recruitments",
    response_model=RecruitmentCreatedOut,
    status_code=201,
    summary="Załóż rekrutację",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def create_recruitment(
    request: Request,
    body: RecruitmentCreateIn,
    caller: RecruitmentsCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(
        False,
        description="Cały zapis z bramką przekazania i wycofanie — bez efektów.",
    ),
) -> Response:
    """Jak „Utwórz i opublikuj” na ekranie nowej rekrutacji: rekrutacja
    powstaje od razu przekazana do searchu i opublikowana — albo wcale (422
    ``job_not_ready`` z ``details.blockers``). Autor = konto serwisowe.
    Budżet wymaga ``amounts:write`` (403 ``insufficient_scope``). Klient
    ukryty albo usunięty → 404, spoza „Aktywnych” i „Relacyjnych” → 422
    ``client_not_selectable``; hiring manager spoza kontaktów klienta,
    Delivery Lead bez roli albo rekruter bez roli rekrutera → odmowa jak na
    ekranie. Bez ``recruiter_id`` przydziela automat (409, gdy wyłączony).
    ``dry_run=true`` → 200 ``{"valid": true, "notices": […]}``."""
    blocked = budget_fields_without_scope(body, principal_of(caller).scopes)
    if blocked:
        raise _insufficient_scope(
            ServiceScope.amounts_write,
            "Budżet rekrutacji to kwota (koszt) — zapis wymaga scope'u amounts:write.",
            fields=blocked,
        )
    data = screen_job_create(body)
    actor = integration_actor(caller)
    # Próba nie oddaje zadań w tle (FastAPI dołącza je do każdej odpowiedzi).
    effects = job_lifecycle.PostCommit(None if dry_run else background_tasks)
    created: list[Job] = []

    async def run():
        await _assert_visible_client(db, body.client_id)
        await _assert_selectable_client(db, body.client_id)
        await _assert_active_category(db, body.competence_category_id)
        job = await job_lifecycle.apply_job_create(db, data, actor, effects)
        notices = list(effects.results.get("notices") or [])
        if dry_run:
            return 200, {"valid": True, "notices": notices}
        await _notify_delivery_lead(db, job, actor)
        created.append(job)
        return 201, {
            "job_id": job.id,
            "reference_number": job.reference_number,
            "notices": notices,
        }

    if dry_run:
        return await dry_run_response(db, run)
    response = await idempotent_write(
        request, db, caller, payload=body.model_dump(mode="json"), run=run
    )
    # Po commicie (powtórka z paragonu nie woła `run` — efektów drugi raz nie
    # ma): wektor, migawka dopasowań, przeliczenie, Targ — jak na ekranie.
    if created:
        await job_lifecycle.run_post_commit(effects)
    return response
