"""Ocena potencjału współpracy z firmą (decyzja Artura z 23.11.2026, „3 warstwy”).

1. **Z NEXUSA, bez modelu:** karta firmy, szanse i przegrane, test KSC liczony
   tutaj z PKD i wielkości (``ksc_test``). Ekran dokłada „Kogo znamy” i mapę
   decydentów z istniejących paneli.
2. **Research firmy:** bieg Bota Research w trybie ``potential``
   (``bot_tasks/potential.py``): zdarzenia z datą i źródłem, ogłoszenia IT, stos.
3. **Ocena:** model z rejestru (F54 ``sales_potential_assessment``) dostaje 1 i 2
   oraz bazę wiedzy (``potential_knowledge``) i odsyła werdykt, punkt wejścia,
   mapę 0–5, numery referencji, pytania, rzeczy do sprawdzenia, ryzyka
   i wiadomość. Numer referencji spoza bazy odpada, a tekst referencji ekran
   bierze z bazy, więc model nie dopisze zakresu.

Wynik leży w ``sales_bot_results`` (rodzaj ``potential``) obok researchu:
``payload.state`` to ``pending`` (research jest, oceny jeszcze nie),
``ready`` albo ``failed``. Ocena to dodatek: awaria modelu zostawia research
na ekranie i przycisk „Odśwież”.

Logi są publiczne: numery wyników i firm, bez nazw i treści.
Reguły: ``docs/claude/sprzedaz/ocena-potencjalu.md``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from sqlalchemy import and_, cast, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.scheduling import business_date
from app.models.ai_feature import AIFeatureKey
from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesOpportunity,
    SalesPipelineStage,
)
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import SALES_POTENTIAL_ASSESSMENT
from app.services.prompt_fencing import fence, json_for_prompt
from app.services.sales import potential_knowledge
from app.services.sales.bot_tasks.potential import OFFER_LINES, POTENTIAL
from app.services.sales.signal_targets import WINBACK_LOST_REASONS

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.sales_potential_assessment
MODEL_TIMEOUT_SECONDS = 180.0
#: Research bez oceny dłużej niż to: pętla ponawia (zadanie w tle mogło zginąć).
STALE_PENDING = timedelta(minutes=10)
MAX_ATTEMPTS = 3
LOST_WITHIN = timedelta(days=730)

KSC_TERMS = (
    "KSC (NIS2) w życiu od 03.04.2026; wniosek o wpis do wykazu do 03.10.2026, "
    "dostosowanie do 03.04.2027."
)

Verdict = Literal["NISKI", "ŚREDNI", "WYSOKI"]
Horizon = Literal["teraz", "3–6 mies.", "6–12 mies.", "ponad 12 mies."]
QuestionGroup = Literal["Biznes", "IT i zespół", "Bezpieczeństwo", "Procesy", "Zakupy"]
LINE_KEYS = tuple(OFFER_LINES)


# ── Test KSC (NIS2) z PKD i wielkości ─────────────────────────────────────────

#: Prefiks PKD → (załącznik, sektor). Najdłuższy pasujący prefiks wygrywa.
_ANNEX: dict[str, tuple[str, str]] = {
    "35.1": ("I", "energia: energia elektryczna"),
    "35.2": ("I", "energia: gaz"),
    "35.3": ("I", "energia: ciepło"),
    "06": ("I", "energia: ropa i gaz"),
    "19.2": ("I", "energia: ropa naftowa"),
    "49.1": ("I", "transport kolejowy"),
    "49.2": ("I", "transport kolejowy"),
    "49.5": ("I", "energia: transport rurociągowy"),
    "50": ("I", "transport wodny"),
    "51": ("I", "transport lotniczy"),
    "52.22": ("I", "transport wodny: porty"),
    "52.23": ("I", "transport lotniczy: porty lotnicze"),
    "64.1": ("I", "bankowość"),
    "66.1": ("I", "infrastruktura rynków finansowych"),
    "86": ("I", "zdrowie: opieka zdrowotna"),
    "21": ("I", "zdrowie: produkcja leków"),
    "36": ("I", "woda pitna"),
    "37": ("I", "ścieki"),
    "61": ("I", "infrastruktura cyfrowa: telekomunikacja"),
    "63.11": ("I", "infrastruktura cyfrowa: przetwarzanie danych i hosting"),
    "62": ("I", "zarządzanie usługami ICT (B2B)"),
    "84": ("I", "administracja publiczna"),
    "53": ("II", "usługi pocztowe i kurierskie"),
    "38": ("II", "gospodarowanie odpadami"),
    "20": ("II", "produkcja chemikaliów"),
    "10": ("II", "produkcja żywności"),
    "11": ("II", "produkcja napojów"),
    "46.3": ("II", "hurtowa dystrybucja żywności"),
    "26": ("II", "produkcja komputerów i elektroniki"),
    "27": ("II", "produkcja urządzeń elektrycznych"),
    "28": ("II", "produkcja maszyn"),
    "29": ("II", "produkcja pojazdów"),
    "30": ("II", "produkcja innego sprzętu transportowego"),
    "32.5": ("II", "produkcja wyrobów medycznych"),
    "63.12": ("II", "dostawcy usług cyfrowych"),
    "72": ("II", "badania naukowe"),
}
#: Objęte w części przypadków niezależnie od wielkości (telekomunikacja, administracja).
_ANY_SIZE = ("61", "84")


def _annex(pkd: str) -> Optional[tuple[str, str, str]]:
    best: Optional[str] = None
    for prefix in _ANNEX:
        if pkd.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return None if best is None else (best, *_ANNEX[best])


def employees_floor(*texts: Optional[str]) -> Optional[int]:
    """Dolna granica zatrudnienia z „250-999”, „1000+”, „ok. 772 (2022)”."""

    for text in texts:
        match = re.search(r"\d[\d\s]*", (text or "").replace("\xa0", " "))
        if match:
            digits = re.sub(r"\s", "", match.group(0))
            if digits.isdigit():
                return int(digits)
    return None


def ksc_test(
    pkd: Optional[str], *size_texts: Optional[str]
) -> Optional[dict[str, Any]]:
    """Wynik testu KSC: ``result``, ``entity``, ``sector``, ``why``; bez PKD ``None``.

    Kryterium obrotu i grupy kapitałowej nie liczy, dlatego zawsze „prawdopodobnie”.
    """

    if not pkd:
        return None
    floor = employees_floor(*size_texts)
    match = _annex(pkd)
    if match is None:
        return {
            "result": "PRAWDOPODOBNIE NIE",
            "entity": None,
            "sector": None,
            "why": f"PKD {pkd} poza załącznikami NIS2. Możliwa presja klientów objętych "
            "KSC na bezpieczeństwo dostawcy.",
        }
    prefix, annex, sector = match
    size = "wielkość nieznana" if floor is None else f"od {floor} osób"
    if floor is None:
        result, entity = "MOŻLIWE", None
    elif floor >= 250:
        result, entity = "PRAWDOPODOBNIE TAK", "kluczowy" if annex == "I" else "ważny"
    elif floor >= 50:
        result, entity = "PRAWDOPODOBNIE TAK", "ważny"
    elif prefix in _ANY_SIZE:
        result, entity = "MOŻLIWE", None
    else:
        result, entity = "PRAWDOPODOBNIE NIE", None
    return {
        "result": result,
        "entity": entity,
        "sector": sector,
        "why": f"PKD {pkd}: zał. {annex} ({sector}); {size}. {KSC_TERMS}",
    }


# ── Dane do modelu ────────────────────────────────────────────────────────────


async def nexus_facts(
    db: AsyncSession, company: SalesCompany, *, now: datetime
) -> dict[str, Any]:
    """Fakty z NEXUSA bez danych osób: karta, szanse otwarte i przegrane."""

    rows = (
        await db.execute(
            select(
                SalesOpportunity.title,
                SalesOpportunity.status,
                SalesOpportunity.lost_reason,
                SalesOpportunity.lost_at,
                SalesOpportunity.created_at,
                SalesPipelineStage.name,
            )
            .join(
                SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id
            )
            .where(
                SalesOpportunity.company_id == company.id,
                SalesOpportunity.archived_at.is_(None),
            )
            .order_by(SalesOpportunity.created_at.desc())
            .limit(20)
        )
    ).all()
    open_ = [
        {"tytul": title, "etap": stage, "od": created.date().isoformat()}
        for title, status, _reason, _lost, created, stage in rows
        if status == "open"
    ]
    # Powód przegranej to wolny tekst handlowca (może mieć nazwiska): do modelu idzie
    # tylko wartość ze stałej listy powodów.
    lost = [
        {
            "tytul": title,
            "powod": reason if reason in WINBACK_LOST_REASONS else "inny",
            "kiedy": lost_at.date().isoformat(),
        }
        for title, status, reason, lost_at, _created, _stage in rows
        if status == "lost" and lost_at is not None and lost_at >= now - LOST_WITHIN
    ]
    return {
        "nazwa": company.name,
        "branza": company.industry or "",
        "wielkosc": company.size_range or "",
        "miasto": company.hq_city or "",
        "klient_nexusa": company.client_id is not None,
        "szanse_otwarte": open_,
        "szanse_przegrane": lost,
    }


# ── Odpowiedź modelu ─────────────────────────────────────────────────────────


def _short(limit: int) -> Any:
    def clean(value: str) -> str:
        return " ".join(str(value or "").split())[:limit]

    return clean


Short240 = Annotated[str, AfterValidator(_short(240))]
Short300 = Annotated[str, AfterValidator(_short(300))]
Short500 = Annotated[str, AfterValidator(_short(500))]
Short900 = Annotated[str, AfterValidator(_short(900))]


class _Land(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Short240
    why: Short500 = ""


class _Fit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    line: str
    score: int = Field(ge=0, le=5)
    need: Short240 = ""
    service: Short240 = ""
    horizon: Horizon = "ponad 12 mies."

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: Any) -> int:
        try:
            return max(0, min(5, int(value)))
        except (TypeError, ValueError):
            return 0


class _Ref(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nr: str
    why: Short300 = ""


class _Question(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group: QuestionGroup
    text: Short300


class Assessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verdict: Verdict
    summary: Short900
    land: _Land
    expand: list[str] = Field(default_factory=list)
    fit: list[_Fit] = Field(default_factory=list)
    references: list[_Ref] = Field(default_factory=list)
    questions: list[_Question] = Field(default_factory=list)
    verify: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opening: Short900 = ""

    @field_validator("expand", "verify", "risks", mode="before")
    @classmethod
    def _lines(cls, value: Any) -> list[str]:
        return [
            " ".join(str(v).split())[:300] for v in (value or []) if str(v).strip()
        ][:5]


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["NISKI", "ŚREDNI", "WYSOKI"]},
        "summary": {"type": "string"},
        "land": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "why": {"type": "string"}},
            "required": ["title", "why"],
            "additionalProperties": False,
        },
        "expand": {"type": "array", "items": {"type": "string"}},
        "fit": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "enum": list(LINE_KEYS)},
                    "score": {"type": "integer"},
                    "need": {"type": "string"},
                    "service": {"type": "string"},
                    "horizon": {
                        "type": "string",
                        "enum": ["teraz", "3–6 mies.", "6–12 mies.", "ponad 12 mies."],
                    },
                },
                "required": ["line", "score", "need", "service", "horizon"],
                "additionalProperties": False,
            },
        },
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"nr": {"type": "string"}, "why": {"type": "string"}},
                "required": ["nr", "why"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group": {
                        "type": "string",
                        "enum": [
                            "Biznes",
                            "IT i zespół",
                            "Bezpieczeństwo",
                            "Procesy",
                            "Zakupy",
                        ],
                    },
                    "text": {"type": "string"},
                },
                "required": ["group", "text"],
                "additionalProperties": False,
            },
        },
        "verify": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "opening": {"type": "string"},
    },
    "required": [
        "verdict",
        "summary",
        "land",
        "expand",
        "fit",
        "references",
        "questions",
        "verify",
        "risks",
        "opening",
    ],
    "additionalProperties": False,
}


def parse_assessment(raw: str, reference_ids: set[str]) -> dict[str, Any]:
    """Co wolno pokazać: linie z naszej listy, numery referencji z bazy.

    Zepsuta odpowiedź daje wyjątek (stan ``failed``), a nie pustą ocenę.
    """

    data = json.loads(raw)
    try:
        assessment = Assessment.model_validate(data)
    except ValidationError as exc:
        raise ValueError("assessment failed validation") from exc
    fit: dict[str, dict[str, Any]] = {}
    for item in assessment.fit:
        if item.line in OFFER_LINES and item.line not in fit:
            fit[item.line] = item.model_dump()
    refs: list[dict[str, str]] = []
    for ref in assessment.references:
        if ref.nr in reference_ids and ref.nr not in {r["id"] for r in refs}:
            refs.append({"id": ref.nr, "why": ref.why})
    if not assessment.summary or not assessment.land.title:
        raise ValueError("assessment without summary or entry point")
    return {
        "verdict": assessment.verdict,
        "summary": assessment.summary,
        "land": assessment.land.model_dump(),
        "expand": assessment.expand[:4],
        "fit": sorted(
            fit.values(), key=lambda f: (-f["score"], LINE_KEYS.index(f["line"]))
        ),
        "references": refs[:4],
        "questions": [q.model_dump() for q in assessment.questions if q.text][:12],
        "verify": assessment.verify,
        "risks": assessment.risks,
        "opening": assessment.opening,
    }


def _call_model(payload: dict[str, Any], request_id: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""

    from app.services.cv_generator_b2b.provider import analyze_with_ai  # noqa: PLC0415

    return analyze_with_ai(
        SALES_POTENTIAL_ASSESSMENT.render(data=fence("dane", json_for_prompt(payload))),
        request_id,
        system=SALES_POTENTIAL_ASSESSMENT.system_prompt,
        model_override=model_for(FEATURE),
        fallback_models=list(fallbacks_for(FEATURE)),
        response_schema=RESPONSE_SCHEMA,
        total_timeout=MODEL_TIMEOUT_SECONDS,
    )


def model_payload(
    facts: dict[str, Any],
    research: dict[str, Any],
    ksc: Optional[dict[str, Any]],
    knowledge: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    return {
        "dzis": today.isoformat(),
        "firma_z_nexusa": facts,
        "research_firmy": research,
        "test_ksc": ksc,
        "linie_oferty": OFFER_LINES,
        "baza_wiedzy": knowledge,
    }


CLAIM_TTL = timedelta(minutes=15)


def _merge(values: dict[str, Any]) -> Any:
    """``payload || {...}`` w jednym UPDATE: bez czytania i nadpisywania całego JSON-a."""

    return SalesBotResult.payload.op("||")(cast(values, JSONB))


async def _claim(db: AsyncSession, result_id: int, now: datetime) -> Optional[str]:
    """Przejmij research do oceny; drugi proces (zadanie w tle, pętla) dostaje ``None``.

    Przejęcie starsze niż ``CLAIM_TTL`` (proces zginął przy wdrożeniu) wolno wziąć
    ponownie. Znaczniki czasu to ISO z UTC, więc porównanie tekstu jest poprawne.
    """

    claim = uuid.uuid4().hex[:12]
    state = SalesBotResult.payload["state"].astext
    taken = await db.execute(
        update(SalesBotResult)
        .where(
            SalesBotResult.id == result_id,
            SalesBotResult.kind == POTENTIAL,
            or_(
                state == "pending",
                and_(
                    state == "assessing",
                    SalesBotResult.payload["claimed_at"].astext
                    < (now - CLAIM_TTL).isoformat(),
                ),
            ),
        )
        .values(
            payload=_merge(
                {"state": "assessing", "claim": claim, "claimed_at": now.isoformat()}
            ),
            updated_at=now,
        )
        .returning(SalesBotResult.id)
    )
    got = taken.scalar_one_or_none()
    await db.commit()
    return claim if got is not None else None


async def assess(
    db: AsyncSession, result_id: int, *, now: Optional[datetime] = None
) -> str:
    """Ocena jednego researchu; zwraca stan po próbie (``ready``/``failed``/``pending``/pomiń).

    Najpierw przejęcie wiersza (``_claim``), więc model nie jest wołany dwa razy
    za ten sam research. Połączenie wraca do puli na czas modelu, a zapis wyniku
    idzie tylko pod tym samym przejęciem.
    """

    from app.services.llm_providers import api_key_configured  # noqa: PLC0415

    moment = now or datetime.now(timezone.utc)
    claim = await _claim(db, result_id, moment)
    if claim is None:
        return "skipped"
    row = await db.get(SalesBotResult, result_id, populate_existing=True)
    company = (
        await db.get(SalesCompany, row.company_id)
        if row is not None and row.company_id
        else None
    )
    payload = dict(row.payload or {}) if row is not None else {}
    research = payload.get("research") or {}
    attempts = int(payload.get("attempts") or 0) + 1
    ksc = (
        ksc_test(research.get("pkd"), company.size_range, research.get("employees"))
        if company is not None
        else None
    )

    async def finish(update_values: dict[str, Any]) -> None:
        await db.execute(
            update(SalesBotResult)
            .where(
                SalesBotResult.id == result_id,
                SalesBotResult.payload["claim"].astext == claim,
            )
            .values(
                payload=_merge({**update_values, "attempts": attempts, "ksc": ksc}),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    if company is None:
        await finish({"state": "failed", "error": "no_company"})
        return "failed"
    knowledge = await potential_knowledge.load(db)
    if knowledge.empty:
        await finish({"state": "failed", "error": "no_knowledge"})
        return "failed"
    if not api_key_configured(model_for(FEATURE)):
        await finish({"state": "failed", "error": "no_model"})
        return "failed"
    today = business_date(moment)  # „dzis” dla modelu to dzień firmy, nie UTC
    facts = await nexus_facts(db, company, now=moment)
    ref_ids = {ref.id for ref in knowledge.references}
    data = model_payload(
        facts, research, ksc, potential_knowledge.for_model(knowledge, today), today
    )
    company_id = company.id
    try:
        async with ai_feature(db, FEATURE, user_id=None):
            await db.commit()  # połączenie wraca do puli na czas modelu
            raw = await run_in_threadpool(_call_model, data, uuid.uuid4().hex[:12])
        assessment = parse_assessment(raw, ref_ids)
    except Exception as exc:  # noqa: BLE001 — ocena to dodatek, research zostaje
        await db.rollback()
        logger.warning(
            "sales_potential result=%s company=%s assessment failed (%s)",
            result_id,
            company_id,
            type(exc).__name__,
        )
        state = "failed" if attempts >= MAX_ATTEMPTS else "pending"
        await finish({"state": state, "error": "model"})
        return state
    await finish(
        {
            "state": "ready",
            "error": None,
            "assessment": assessment,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    logger.info("sales_potential result=%s company=%s ready", result_id, company_id)
    return "ready"


async def assess_run(run_id: int) -> int:
    """Oceny po raporcie biegu (zadanie w tle z trasy przyjęcia raportu)."""

    from app.core.database import AsyncSessionLocal  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        ids = (
            (
                await db.execute(
                    select(SalesBotResult.id).where(
                        SalesBotResult.run_id == run_id,
                        SalesBotResult.kind == POTENTIAL,
                    )
                )
            )
            .scalars()
            .all()
        )
        done = 0
        for result_id in ids:
            done += int(await assess(db, result_id) == "ready")
        return done


async def assess_stale(db: AsyncSession, *, now: datetime, limit: int = 2) -> int:
    """Pętla: research bez oceny po ``STALE_PENDING`` albo porzucone przejęcie.

    Dwie oceny na obrót (każda do 180 s), żeby krok nie zjadł 15-minutowego obrotu.
    """

    state = SalesBotResult.payload["state"].astext
    ids = (
        (
            await db.execute(
                select(SalesBotResult.id)
                .where(
                    SalesBotResult.kind == POTENTIAL,
                    or_(
                        and_(
                            state == "pending",
                            SalesBotResult.updated_at < now - STALE_PENDING,
                        ),
                        and_(
                            state == "assessing",
                            SalesBotResult.payload["claimed_at"].astext
                            < (now - CLAIM_TTL).isoformat(),
                        ),
                    ),
                )
                .order_by(SalesBotResult.updated_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    done = 0
    for result_id in ids:
        done += int(await assess(db, result_id, now=now) == "ready")
    return done


def model_ready() -> bool:
    """Model oceny ma klucz; bez niego pętla daje firmie zwykłe punkty."""

    from app.services.llm_providers import api_key_configured  # noqa: PLC0415

    return api_key_configured(model_for(FEATURE))


FRESH_FOR = timedelta(days=30)
#: Jedna próba bota na dobę: bieg wygasły albo bez firmy w raporcie nie wraca od razu.
RUN_COOLDOWN = timedelta(hours=24)


async def fresh_company_ids(
    db: AsyncSession, company_ids: list[int], *, now: datetime
) -> set[int]:
    """Firmy z researchem z ostatnich 30 dni (także z nieudaną oceną: research
    zostaje, model ponawia pętla) albo z biegiem ``potential`` z ostatniej doby."""

    from app.models.sales import SalesSignalRun  # noqa: PLC0415

    ids = sorted(set(company_ids))
    if not ids:
        return set()
    rated = await db.execute(
        select(SalesBotResult.company_id).where(
            SalesBotResult.kind == POTENTIAL,
            SalesBotResult.company_id.in_(ids),
            SalesBotResult.created_at >= now - FRESH_FOR,
        )
    )
    fresh = {int(cid) for cid in rated.scalars()}
    runs = await db.execute(
        select(SalesSignalRun.company_ids, SalesSignalRun.modes).where(
            SalesSignalRun.kind == "briefing",
            SalesSignalRun.started_at >= now - RUN_COOLDOWN,
        )
    )
    for run_ids, modes in runs.all():
        for cid in run_ids or []:
            if (modes or {}).get(str(cid)) == POTENTIAL:
                fresh.add(int(cid))
    return fresh & set(ids)


async def latest(db: AsyncSession, company_id: int) -> Optional[SalesBotResult]:
    """Najnowsza ocena firmy (także w toku); odrzucona się nie pokazuje."""

    return (
        await db.execute(
            select(SalesBotResult)
            .where(
                SalesBotResult.kind == POTENTIAL,
                SalesBotResult.company_id == company_id,
                SalesBotResult.status != "rejected",
            )
            .order_by(SalesBotResult.created_at.desc(), SalesBotResult.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
