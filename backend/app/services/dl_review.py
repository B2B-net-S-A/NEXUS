"""Przegląd Delivery Leada przed wysłaniem CV do klienta — kontekst (D6, D9, D10).

Decyzje Artura z 07.10.2026 (makieta https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi,
ekran 3). DL do tej pory wpisywał stawkę do klienta od zera, bez budżetu
i marży (D9 odwraca decyzję z 23.09.2026 „przegląd bez marży”), a wymagania
klienta porównywał z CV sam. Ten moduł składa wszystko, czego DL potrzebuje
do decyzji, w JEDNYM przebiegu dla jednej rekrutacji:

* wymagania klienta a kandydat — must (krytyczne pierwsze), nice
  i doświadczenie z sekcji 4 Championa, z dowodem i jego źródłem (profil, CV,
  notatka, rozmowa = odpowiedzi ze screeningu; ``must_text_evidence``);
* ocena rekrutera z formularza screeningu (ocena, „Dlaczego ten kandydat”,
  red flags, odpowiedzi);
* ryzyka i historia u tego klienta (ostrzeżenia dopuszczalności, umowa
  u innego klienta, wcześniejsze wysyłki, deal-breaker, ponad budżet);
* do decyzji: stawka kandydata, budżet od–do, podpowiedź stawki do klienta
  (ta para → ta osoba u tego klienta), agregaty konsultantów u klienta
  (mediana marży, zakres stawek w tej samej kategorii — bez nazwisk),
  poprzednie wysyłki tej osoby, inni wysłani w tej rekrutacji, ostatni
  kontrakt.

Redakcja: kwoty z kontraktów (agregaty u klienta, koszt ostatniego kontraktu)
wyłącznie przy ``financial_access.can_read_client_finance`` dla klienta tego
kontraktu; stawki do klienta (podpowiedź, wysyłki) wyłącznie przy
``candidate_access.user_can_view_client_rate``. Stawka kandydata jest jawna
(decyzja 23.09.2026).

Kolejka porównawcza (D10) bierze te same loadery dla wszystkich osób jednej
rekrutacji naraz — stała liczba zapytań niezależnie od liczby osób.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competence_category import CompetenceCategory
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User
from app.services import champion_view, must_text_evidence
from app.services import recommendation_cards as cards
from app.services import recommendation_card_rules as card_rules
from app.services.client_consultant_rates import (
    client_consultant_summary,
    contract_hourly,
)
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.move_requirements import sheet_filled
from app.services.screening_form_rules import FIT_LABELS

logger = logging.getLogger(__name__)

QUEUE_LIMIT = 50
HOURS_PER_DAY = Decimal(8)
HOURS_PER_MONTH = Decimal(168)

# Etapy, na których osoba JUŻ poszła do klienta (lustro kolumn od „CV wysłane”).
SENT_STAGES = (
    "cv_sent",
    "client_interview",
    "acceptance",
    "negotiation",
    "onboarding",
    "hired",
)
OUTCOME_LABELS = {
    "cv_sent": "CV wysłane",
    "client_interview": "Rozmowa u klienta",
    "acceptance": "Umowa",
    "negotiation": "Umowa",
    "onboarding": "Zatrudniony",
    "hired": "Zatrudniony",
    "rejected": "Odrzucony",
    "withdrawn": "Zrezygnował",
}
SOURCE_LABELS = {
    must_text_evidence.SOURCE_PROFILE: "profil",
    must_text_evidence.SOURCE_CV: "CV",
    must_text_evidence.SOURCE_NOTE: "notatka",
    must_text_evidence.SOURCE_CONVERSATION: "rozmowa",
}
SNIPPET_ORDER = (
    must_text_evidence.SOURCE_CV,
    must_text_evidence.SOURCE_CONVERSATION,
    must_text_evidence.SOURCE_NOTE,
)
ASSESSMENT_FIELDS = (
    "recommendation",
    "motivation",
    "red_flags",
    "availability",
    "work_mode",
    "location",
    "english",
    "worked_at_client",
)


# ── Czyste reguły ────────────────────────────────────────────────────────────


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def hourly_pln(
    amount: Any, unit: Optional[str], currency: Optional[str]
) -> Optional[Decimal]:
    """Stawka → PLN/h (dzień ÷ 8, miesiąc ÷ 168); inna waluta = ``None``."""
    if amount is None:
        return None
    if str(currency or "PLN").strip().upper() != "PLN":
        return None
    try:
        value = Decimal(str(amount))
    except Exception:  # noqa: BLE001
        return None
    if value <= 0:
        return None
    unit = _value(unit) or "hourly"
    if unit == "daily":
        value = value / HOURS_PER_DAY
    elif unit == "monthly":
        value = value / HOURS_PER_MONTH
    elif unit != "hourly":
        return None
    return value.quantize(Decimal("0.01"))


def rate_dict(
    amount: Any, unit: Any, currency: Any, *, at: Any = None
) -> Optional[dict]:
    if amount is None:
        return None
    return {
        "amount": float(amount),
        "unit": _value(unit) or "hourly",
        "currency": (str(currency or "PLN")).upper(),
        "hourly_pln": _float(hourly_pln(amount, _value(unit), currency)),
        "at": at.isoformat() if isinstance(at, datetime) else at,
    }


def _float(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


@dataclass(frozen=True)
class RequirementInput:
    key: str
    label: str
    level: str  # critical | must | nice | experience
    min_years: Optional[int] = None


def job_requirement_inputs(job: Any) -> list[RequirementInput]:
    """Wymagania rekrutacji w kolejności przeglądu: krytyczne, must, nice, sekcja 4."""
    from app.services.critical_skills import effective_critical  # noqa: PLC0415
    from app.services.dz_review import job_requirements  # noqa: PLC0415

    try:
        must, nice = job_requirements(job)
    except Exception:  # noqa: BLE001 — rekrutacja bez kontraktu wymagań
        logger.warning("dl_review: job requirements failed", exc_info=True)
        must, nice = [], []
    try:
        critical = {label.casefold() for label in effective_critical(job).labels}
    except Exception:  # noqa: BLE001
        critical = set()
    out: list[RequirementInput] = []
    crit: list[RequirementInput] = []
    for index, req in enumerate(must):
        names = {req.label.casefold(), *(a.casefold() for a in req.alternatives)}
        item = RequirementInput(
            f"must:{index}",
            req.label,
            "critical" if names & critical else "must",
        )
        (crit if item.level == "critical" else out).append(item)
    out = crit + out
    out.extend(
        RequirementInput(f"nice:{index}", req.label, "nice")
        for index, req in enumerate(nice)
    )
    experience = champion_view.experience(getattr(job, "champion_profile", None))
    for kind in ("domains", "certifications", "regulations"):
        for index, item in enumerate(experience.get(kind) or []):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            years = item.get("min_years")
            try:
                years = int(years) if years not in (None, "") else None
            except (TypeError, ValueError):
                years = None
            label = f"{name} (min. {years} lat)" if years else name
            level = "experience" if item.get("level") != "nice" else "nice"
            # Lata i dziedzinę ocenia człowiek; słowo szukamy po nazwie.
            out.append(
                RequirementInput(f"experience:{kind}:{index}", label, level, years)
            )
    return out


def _search_label(item: RequirementInput) -> str:
    if item.key.startswith("experience:") and item.min_years:
        return item.label.rsplit(" (min.", 1)[0]
    return item.label


def evaluate_requirements(
    candidate: Any,
    items: Sequence[RequirementInput],
    *,
    note_texts: Iterable[str],
    conversation_texts: Iterable[str],
) -> list[dict[str, Any]]:
    """Tabela „wymaganie / kandydat / źródło / status” dla jednej osoby.

    ``unknown`` = wymaganie, którego nie da się sprawdzić słowem (zdanie,
    branża bez słownika) — DL ocenia sam; NIGDY nie jest liczone jako brak.
    """
    notes = [t for t in note_texts if t]
    conversation = [t for t in conversation_texts if t]
    labels = [_search_label(item) for item in items]
    sources = must_text_evidence.mention_sources(
        candidate, labels, note_texts=notes, conversation_texts=conversation
    )
    texts = {
        must_text_evidence.SOURCE_PROFILE: [must_text_evidence.profile_text(candidate)],
        must_text_evidence.SOURCE_CV: [must_text_evidence.cv_text(candidate)],
        must_text_evidence.SOURCE_NOTE: notes,
        must_text_evidence.SOURCE_CONVERSATION: conversation,
    }
    rows: list[dict[str, Any]] = []
    for item, search in zip(items, labels):
        found = sources.get(search)
        snippet: Optional[str] = None
        # Fragment z CV, rozmowy albo notatki; profil to lista JSON — tam
        # wystarczy źródło „profil” (fragment byłby surowym zapisem pola).
        for source in SNIPPET_ORDER:
            if not found or source not in found:
                continue
            for blob in texts.get(source, []):
                snippet = must_text_evidence.mention_snippet(search, blob)
                if snippet:
                    break
            if snippet:
                break
        status = "unknown" if found is None else ("met" if found else "missing")
        rows.append(
            {
                "key": item.key,
                "label": item.label,
                "level": item.level,
                "status": status,
                "sources": [SOURCE_LABELS[s] for s in (found or ())],
                "candidate_value": snippet,
            }
        )
    return rows


def requirements_score(rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """X/Y — spełnione krytyczne i must spośród sprawdzalnych."""
    counted = [
        r
        for r in rows
        if r["level"] in ("critical", "must") and r["status"] != "unknown"
    ]
    return sum(1 for r in counted if r["status"] == "met"), len(counted)


def conversation_texts(
    sheet: Optional[Mapping[str, Any]], card: Mapping[str, Any]
) -> list[str]:
    """Rozmowa = odpowiedzi ze screeningu i pola karty z formularza."""
    out: list[str] = []
    for answer in (sheet or {}).get("answers") or []:
        if not isinstance(answer, Mapping):
            continue
        response = str(answer.get("response") or "").strip()
        if response and not must_text_evidence.is_negative_answer(response):
            question = str(answer.get("question_text") or "").strip()
            out.append(f"{question}\n{response}" if question else response)
    for key in ("recommendation", "motivation"):
        raw = str((card.get(key) or {}).get("raw") or "").strip()
        if raw:
            out.append(raw)
    return out


def pick_client_rate_hint(
    *,
    this_pair: Optional[dict],
    same_client: Sequence[dict],
) -> Optional[dict]:
    """Podpowiedź stawki do klienta: ta para, potem ta osoba u tego klienta."""
    if this_pair is not None:
        return {**this_pair, "source": "this_pair"}
    if same_client:
        latest = max(same_client, key=lambda r: r.get("at") or "")
        return {**latest, "source": "same_client"}
    return None


def _pln_amount(value: float) -> str:
    """Kwota po polsku: pełne złote bez groszy, inaczej dwa miejsca z przecinkiem.

    Zaokrąglenie do pełnych złotych zamieniało 0,40 zł/h nadwyżki w „0 zł/h”.
    """
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".replace(".", ",")


def risks_for(
    *,
    eligibility_reason: Optional[str],
    eligibility_code: Optional[str],
    employed_elsewhere: Sequence[str],
    worked_at_client: Optional[str],
    deal_breaker_hits: int,
    over_budget_by: Optional[float],
    sent_to_client_before: Sequence[Mapping[str, Any]],
    red_flags: Optional[str],
    qc_status: Optional[str],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if eligibility_code and eligibility_code != "eligible" and eligibility_reason:
        out.append(
            {"code": eligibility_code, "label": eligibility_reason, "severity": "high"}
        )
    if deal_breaker_hits:
        out.append(
            {
                "code": "deal_breaker",
                "label": "Odpowiedź narusza „Odpada, gdy…”"
                + (f" ({deal_breaker_hits})" if deal_breaker_hits > 1 else ""),
                "severity": "high",
            }
        )
    if qc_status == "failed":
        out.append(
            {"code": "qc_failed", "label": "CV nie przeszło QC", "severity": "high"}
        )
    if over_budget_by is not None and over_budget_by > 0:
        out.append(
            {
                "code": "over_budget",
                "label": f"Stawka ponad budżet o {_pln_amount(over_budget_by)} zł/h",
                "severity": "medium",
            }
        )
    if employed_elsewhere:
        out.append(
            {
                "code": "employed_elsewhere",
                "label": "Pracuje u nas u: " + ", ".join(employed_elsewhere),
                "severity": "medium",
            }
        )
    for send in sent_to_client_before:
        when = str(send.get("sent_at") or "")[:10]
        outcome = send.get("outcome") or "CV wysłane"
        out.append(
            {
                "code": "sent_to_client_before",
                "label": f"Już u tego klienta: „{send.get('job_title')}” ({when}, {outcome})",
                "severity": "medium",
            }
        )
    if worked_at_client:
        out.append(
            {
                "code": "worked_at_client",
                "label": f"Czy pracował u klienta: {worked_at_client}",
                "severity": "info",
            }
        )
    if red_flags:
        out.append(
            {
                "code": "red_flags",
                "label": f"Red flags: {red_flags}",
                "severity": "info",
            }
        )
    return out


# ── Loadery (stała liczba zapytań na rekrutację) ─────────────────────────────


@dataclass
class PairFacts:
    candidate: Candidate
    stage_id: Optional[int] = None
    rate: Optional[dict] = None
    client_rate: Optional[dict] = None
    sheet: Optional[dict] = None
    card: dict[str, Any] = field(default_factory=dict)


async def client_family_ids(db: AsyncSession, client_id: Optional[int]) -> set[int]:
    """Klient z rodziną scalonych rekordów (duplikaty i rekord główny)."""
    if client_id is None:
        return set()
    rows = await db.execute(
        select(Client.id, Client.merged_into_client_id).where(
            or_(Client.id == client_id, Client.merged_into_client_id == client_id)
        )
    )
    out = {client_id}
    root: Optional[int] = None
    for cid, merged_into in rows.all():
        out.add(cid)
        if cid == client_id and merged_into:
            root = merged_into
    if root is not None:
        siblings = await db.execute(
            select(Client.id).where(
                or_(Client.id == root, Client.merged_into_client_id == root)
            )
        )
        out |= {cid for (cid,) in siblings.all()}
    return out


async def _pair_facts(
    db: AsyncSession, job: Job, candidate_ids: Sequence[int]
) -> dict[int, PairFacts]:
    ids = sorted(set(candidate_ids))
    candidates = (
        await db.scalars(select(Candidate).where(Candidate.id.in_(ids)))
    ).all()
    out = {c.id: PairFacts(candidate=c) for c in candidates}
    if not out:
        return out
    rows = (
        await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.candidate_id,
                CandidateStage.expected_rate_value,
                CandidateStage.expected_rate_unit,
                CandidateStage.expected_rate_currency,
                CandidateStage.client_rate_value,
                CandidateStage.client_rate_unit,
                CandidateStage.client_rate_currency,
                CandidateStage.screening_answers,
                CandidateStage.moved_at,
            )
            .where(
                CandidateStage.job_id == job.id,
                CandidateStage.candidate_id.in_(list(out)),
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        )
    ).all()
    for row in rows:
        facts = out.get(row.candidate_id)
        if facts is None:
            continue
        if facts.stage_id is None:
            facts.stage_id = row.id
        if facts.rate is None and row.expected_rate_value is not None:
            facts.rate = rate_dict(
                row.expected_rate_value,
                row.expected_rate_unit,
                row.expected_rate_currency,
                at=row.moved_at,
            )
        if facts.client_rate is None and row.client_rate_value is not None:
            facts.client_rate = rate_dict(
                row.client_rate_value,
                row.client_rate_unit,
                row.client_rate_currency,
                at=row.moved_at,
            )
        if facts.sheet is None and sheet_filled(row.screening_answers):
            facts.sheet = dict(row.screening_answers)
    processes = (
        (
            await db.execute(
                select(RecruitmentProcess)
                .where(
                    RecruitmentProcess.job_id == job.id,
                    RecruitmentProcess.candidate_id.in_(list(out)),
                )
                .order_by(
                    RecruitmentProcess.candidate_id,
                    RecruitmentProcess.attempt_no.desc(),
                    RecruitmentProcess.id.desc(),
                )
                .distinct(RecruitmentProcess.candidate_id)
            )
        )
        .scalars()
        .all()
    )
    started = {p.candidate_id: cards.attempt_started(p) for p in processes}
    cards = (
        await db.scalars(
            select(RecommendationCard).where(
                RecommendationCard.job_id == job.id,
                RecommendationCard.candidate_id.in_(list(out)),
            )
        )
    ).all()
    for card in cards:
        current, _previous = card_rules.split_fields(
            card.fields_notes or {},
            card.fields_manual or {},
            attempt_started=started.get(card.candidate_id),
        )
        out[card.candidate_id].card = current
    return out


_SENDS_SQL = text(
    """
    WITH sent AS (
        SELECT cs.candidate_id, cs.job_id, MIN(cs.moved_at) AS sent_at
          FROM candidate_stages cs
         WHERE cs.candidate_id = ANY(:ids)
           AND cs.stage::text = ANY(:sent_stages)
           AND (CAST(:only_job AS INTEGER) IS NULL OR cs.job_id = :only_job)
         GROUP BY cs.candidate_id, cs.job_id
    ),
    latest AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.stage::text AS stage,
               cs.expected_rate_value, cs.expected_rate_unit,
               cs.expected_rate_currency
          FROM candidate_stages cs
          JOIN sent s ON s.candidate_id = cs.candidate_id AND s.job_id = cs.job_id
         ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    ),
    rate AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.client_rate_value,
               cs.client_rate_unit, cs.client_rate_currency, cs.moved_at
          FROM candidate_stages cs
          JOIN sent s ON s.candidate_id = cs.candidate_id AND s.job_id = cs.job_id
         WHERE cs.client_rate_value IS NOT NULL
         ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    )
    SELECT s.candidate_id, s.job_id, s.sent_at, l.stage,
           l.expected_rate_value, l.expected_rate_unit, l.expected_rate_currency,
           r.client_rate_value, r.client_rate_unit, r.client_rate_currency,
           r.moved_at AS rate_at,
           COALESCE(NULLIF(j.working_title, ''), j.title) AS job_title,
           j.client_id, cl.name AS client_name,
           c.name AS cname, c.lastname AS clastname
      FROM sent s
      JOIN latest l ON l.candidate_id = s.candidate_id AND l.job_id = s.job_id
      LEFT JOIN rate r ON r.candidate_id = s.candidate_id AND r.job_id = s.job_id
      JOIN jobs j ON j.id = s.job_id
      LEFT JOIN clients cl ON cl.id = j.client_id
      JOIN candidates c ON c.id = s.candidate_id
     ORDER BY s.sent_at DESC
    """
)


async def _sends(
    db: AsyncSession,
    candidate_ids: Sequence[int],
    *,
    only_job: Optional[int] = None,
) -> list[Any]:
    ids = sorted({int(i) for i in candidate_ids})
    if not ids:
        return []
    return list(
        (
            await db.execute(
                _SENDS_SQL,
                {"ids": ids, "sent_stages": list(SENT_STAGES), "only_job": only_job},
            )
        ).all()
    )


async def _job_sent_candidate_ids(
    db: AsyncSession, job_id: int, exclude: int
) -> list[int]:
    rows = await db.execute(
        select(CandidateStage.candidate_id)
        .where(
            CandidateStage.job_id == job_id,
            CandidateStage.candidate_id != exclude,
            CandidateStage.stage.in_(SENT_STAGES),
        )
        .distinct()
        .limit(QUEUE_LIMIT)
    )
    return [cid for (cid,) in rows.all()]


def _send_row(row: Any, *, show_client_rate: bool, same_client: bool) -> dict[str, Any]:
    return {
        "candidate_id": row.candidate_id,
        "candidate_name": " ".join(p for p in (row.cname, row.clastname) if p)
        or "Kandydat",
        "job_id": row.job_id,
        "job_title": row.job_title,
        "client_name": row.client_name,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "outcome": OUTCOME_LABELS.get(row.stage, row.stage),
        "same_client": same_client,
        "candidate_rate": rate_dict(
            row.expected_rate_value, row.expected_rate_unit, row.expected_rate_currency
        ),
        "client_rate": (
            rate_dict(
                row.client_rate_value,
                row.client_rate_unit,
                row.client_rate_currency,
                at=row.rate_at,
            )
            if show_client_rate and row.client_rate_value is not None
            else None
        ),
    }


@dataclass(frozen=True)
class Access:
    amounts: bool  # kwoty z kontraktów klienta rekrutacji
    client_rates: bool  # stawki do klienta
    finance_boundary: Optional[frozenset[int]]
    user: User

    def amounts_for(self, client_id: Optional[int]) -> bool:
        from app.api.financial_access import can_read_client_finance  # noqa: PLC0415

        if client_id is None:
            return False
        return can_read_client_finance(
            self.user,
            client_id=client_id,
            delivery_lead_finance_client_ids=self.finance_boundary,
        )


async def access_for(db: AsyncSession, user: User, job: Job) -> Access:
    from app.api.candidate_access import user_can_view_client_rate  # noqa: PLC0415
    from app.api.financial_access import can_read_client_finance  # noqa: PLC0415
    from app.services.access_scope import (  # noqa: PLC0415
        resolve_delivery_lead_finance_client_ids,
    )

    boundary = await resolve_delivery_lead_finance_client_ids(user, db)
    amounts = job.client_id is not None and can_read_client_finance(
        user, client_id=job.client_id, delivery_lead_finance_client_ids=boundary
    )
    return Access(
        amounts=amounts,
        client_rates=user_can_view_client_rate(user),
        finance_boundary=boundary,
        user=user,
    )


@dataclass
class _Batch:
    facts: dict[int, PairFacts]
    requirement_items: list[RequirementInput]
    notes: dict[int, list[str]]
    eligibility: dict[int, Any]
    employed: dict[int, list[str]]
    sends: list[Any]
    family: set[int]
    rounds: dict[tuple[int, int], int]


async def _load_batch(
    db: AsyncSession, job: Job, candidate_ids: Sequence[int], *, now: datetime
) -> _Batch:
    from app.services import screening_fix_requests  # noqa: PLC0415
    from app.services.current_employment import (  # noqa: PLC0415
        current_employment_client_ids,
    )
    from app.services.pipeline_eligibility import (  # noqa: PLC0415
        evaluate_candidates_for_job,
    )

    facts = await _pair_facts(db, job, candidate_ids)
    ids = list(facts)
    items = job_requirement_inputs(job)
    notes = await must_text_evidence.load_evidence_note_texts(
        db, ids, [_search_label(i) for i in items]
    )
    try:
        async with db.begin_nested():
            eligibility = await evaluate_candidates_for_job(
                db, job=job, candidate_ids=ids, now=now
            )
    except Exception:  # noqa: BLE001 — ryzyko jest informacją, nie bramką
        logger.warning("dl_review: eligibility failed", exc_info=True)
        eligibility = {}
    family = await client_family_ids(db, job.client_id)
    employment = await current_employment_client_ids(db, ids, today=now.date())
    other_clients = sorted(
        {cid for owned in employment.values() for cid in owned if cid not in family}
    )
    names: dict[int, str] = {}
    if other_clients:
        names = dict(
            (
                await db.execute(
                    select(Client.id, Client.name).where(Client.id.in_(other_clients))
                )
            ).all()
        )
    employed = {
        cid: sorted(names[c] for c in owned if c in names)
        for cid, owned in employment.items()
    }
    sends = await _sends(db, ids)
    rounds = await screening_fix_requests.rounds_for_pairs(
        db, [(cid, job.id) for cid in ids]
    )
    return _Batch(facts, items, notes, eligibility, employed, sends, family, rounds)


def _assessment(facts: PairFacts) -> dict[str, Any]:
    sheet = facts.sheet or {}
    answers = [
        {
            "question": str(a.get("question_text") or "").strip() or None,
            "question_id": a.get("question_id"),
            "answer": str(a.get("response") or "").strip(),
            "deal_breaker_hit": bool(a.get("deal_breaker_hit")),
        }
        for a in sheet.get("answers") or []
        if isinstance(a, Mapping) and str(a.get("response") or "").strip()
    ]
    fit = sheet.get("overall_fit") if sheet else None
    return {
        "overall_fit": fit,
        "overall_fit_label": FIT_LABELS.get(fit) if fit else None,
        "fields": {
            key: str((facts.card.get(key) or {}).get("raw") or "").strip() or None
            for key in ASSESSMENT_FIELDS
        },
        "answers": answers,
    }


def _person(
    batch: _Batch,
    job: Job,
    candidate_id: int,
    *,
    access: Access,
    budget_max: Optional[float],
    qc_status: Optional[str],
) -> dict[str, Any]:
    facts = batch.facts[candidate_id]
    assessment = _assessment(facts)
    rows = evaluate_requirements(
        facts.candidate,
        batch.requirement_items,
        note_texts=batch.notes.get(candidate_id, []),
        conversation_texts=conversation_texts(facts.sheet, facts.card),
    )
    met, total = requirements_score(rows)
    decision = batch.eligibility.get(candidate_id)
    reason_code = _value(getattr(decision, "reason_code", None))
    hourly = (facts.rate or {}).get("hourly_pln")
    before = [
        _send_row(row, show_client_rate=access.client_rates, same_client=True)
        for row in batch.sends
        if row.candidate_id == candidate_id
        and row.job_id != job.id
        and row.client_id in batch.family
    ]
    risks = risks_for(
        eligibility_reason=getattr(decision, "reason", None),
        eligibility_code=reason_code,
        employed_elsewhere=batch.employed.get(candidate_id, []),
        worked_at_client=assessment["fields"].get("worked_at_client"),
        deal_breaker_hits=sum(
            1 for a in assessment["answers"] if a["deal_breaker_hit"]
        ),
        over_budget_by=(
            hourly - budget_max
            if hourly is not None and budget_max is not None
            else None
        ),
        sent_to_client_before=before,
        red_flags=assessment["fields"].get("red_flags"),
        qc_status=qc_status,
    )
    availability = assessment["fields"].get("availability")
    if not availability and facts.candidate.availability_date:
        availability = facts.candidate.availability_date.isoformat()
    return {
        "candidate_id": candidate_id,
        "candidate_name": " ".join(
            p for p in (facts.candidate.name, facts.candidate.lastname) if p
        )
        or "Kandydat",
        "stage_id": facts.stage_id,
        "candidate_rate": facts.rate,
        "requirements": rows,
        "requirements_met": met,
        "requirements_total": total,
        "assessment": assessment,
        "risks": risks,
        "start": availability,
        "fix_rounds": batch.rounds.get((candidate_id, job.id), 0),
        "_before": before,
    }


async def _last_contract(
    db: AsyncSession, candidate_id: int, *, access: Access, today: date
) -> Optional[dict[str, Any]]:
    contract = await db.scalar(
        select(Contract)
        .options(*RATE_SCHEDULE_LOADS)
        .where(
            Contract.candidate_id == candidate_id,
            Contract.status.in_(
                (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)
            ),
        )
        .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        .limit(1)
    )
    if contract is None:
        return None
    client_name = (
        await db.scalar(select(Client.name).where(Client.id == contract.client_id))
        if contract.client_id
        else None
    )
    shown = access.amounts_for(contract.client_id)
    on = min(contract.end_date, today) if contract.end_date else today
    cost = contract_hourly(contract, on) if shown else None
    return {
        "client_name": client_name,
        "status": _value(contract.status),
        "start_date": contract.start_date.isoformat() if contract.start_date else None,
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "cost_hourly": _float(cost),
        "redacted": not shown,
    }


def _budget(job: Job) -> dict[str, Optional[float]]:
    from app.services.dealbreaker_filters import resolve_job_budget_hourly  # noqa: PLC0415
    from app.services.job_budget_range import effective_min  # noqa: PLC0415

    return {
        "min_hourly": effective_min(job),
        "max_hourly": resolve_job_budget_hourly(job),
    }


async def build_context(
    db: AsyncSession,
    *,
    user: User,
    job: Job,
    candidate_id: int,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Wszystko do decyzji DL dla jednej pary (``GET /api/dl-review/context``)."""
    from app.services import screening_fix_requests  # noqa: PLC0415
    from app.services.candidate_rate_from import rate_summary  # noqa: PLC0415
    from app.services.move_requirements import qc_statuses  # noqa: PLC0415

    now = now or datetime.now(timezone.utc)
    today = now.date()
    access = await access_for(db, user, job)
    batch = await _load_batch(db, job, [candidate_id], now=now)
    if candidate_id not in batch.facts:
        raise LookupError("candidate")
    budget = _budget(job)
    qc = (await qc_statuses(db, [(candidate_id, job.id)])).get(
        (candidate_id, job.id)
    ) or {}
    qc_status = qc.get("status") or "unchecked"
    person = _person(
        batch,
        job,
        candidate_id,
        access=access,
        budget_max=budget["max_hourly"],
        qc_status=qc_status,
    )
    facts = batch.facts[candidate_id]
    before = person.pop("_before")
    previous_sends = [
        _send_row(
            row,
            show_client_rate=access.client_rates,
            same_client=row.client_id in batch.family,
        )
        for row in batch.sends
        if row.candidate_id == candidate_id and row.job_id != job.id
    ]
    same_client_rates = [
        {
            **send["client_rate"],
            "job_id": send["job_id"],
            "job_title": send["job_title"],
        }
        for send in before
        if send["client_rate"] is not None
    ]
    hint = (
        pick_client_rate_hint(
            this_pair=(
                {**facts.client_rate, "job_id": job.id, "job_title": None}
                if facts.client_rate
                else None
            ),
            same_client=same_client_rates,
        )
        if access.client_rates
        else None
    )
    others_ids = await _job_sent_candidate_ids(db, job.id, candidate_id)
    job_sends = [
        _send_row(row, show_client_rate=access.client_rates, same_client=True)
        for row in await _sends(db, others_ids, only_job=job.id)
    ]
    category = None
    if job.competence_category_id:
        category = await db.scalar(
            select(CompetenceCategory.name_pl).where(
                CompetenceCategory.id == job.competence_category_id
            )
        )
    client_rates = None
    if access.amounts:
        summary = await client_consultant_summary(
            db,
            client_ids=batch.family,
            category_id=job.competence_category_id,
            today=today,
        )
        client_rates = {
            "consultants": summary.consultants,
            "client_margin_median_hourly": _float(summary.client_margin_median_hourly),
            "category_name": category,
            "category_count": summary.category_count,
            "category_cost_min": _float(summary.category_cost_min),
            "category_cost_max": _float(summary.category_cost_max),
            "category_revenue_min": _float(summary.category_revenue_min),
            "category_revenue_max": _float(summary.category_revenue_max),
            "category_margin_median_hourly": _float(
                summary.category_margin_median_hourly
            ),
        }
    client_name = (
        await db.scalar(select(Client.name).where(Client.id == job.client_id))
        if job.client_id
        else None
    )
    summary_rate = rate_summary(facts.candidate)
    return {
        **person,
        "job_id": job.id,
        "client_id": job.client_id,
        "client_name": client_name,
        "category_name": category,
        "qc_status": qc_status,
        "qc_blocking_failed": int(qc.get("blocking_failed") or 0),
        "can_see_amounts": access.amounts,
        "can_see_client_rates": access.client_rates,
        "rate_from_hourly": (
            float(summary_rate["rate_from_hourly"])
            if summary_rate.get("rate_from_hourly") is not None
            else None
        ),
        "budget": budget,
        "client_rate_hint": hint,
        "client_rates": client_rates,
        "previous_sends": previous_sends,
        "job_sends": job_sends,
        "last_contract": await _last_contract(
            db, candidate_id, access=access, today=today
        ),
        "fix_options": [o.as_dict() for o in screening_fix_requests.fix_options(job)],
    }


async def build_queue(
    db: AsyncSession,
    *,
    user: User,
    job: Job,
    tasks: Sequence[Any],
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Wiersze porównania (D10) — te same loadery dla wszystkich osób naraz."""
    now = now or datetime.now(timezone.utc)
    tasks = list(tasks)[:QUEUE_LIMIT]
    if not tasks:
        return []
    access = await access_for(db, user, job)
    batch = await _load_batch(db, job, [t.candidate_id for t in tasks], now=now)
    budget = _budget(job)
    out: list[dict[str, Any]] = []
    for task in tasks:
        if task.candidate_id not in batch.facts:
            continue
        person = _person(
            batch,
            job,
            task.candidate_id,
            access=access,
            budget_max=budget["max_hourly"],
            qc_status=task.qc_status,
        )
        person.pop("_before")
        assessment = person.pop("assessment")
        person.pop("requirements")
        out.append(
            {
                **person,
                "since": task.since,
                "qc_status": task.qc_status,
                "overall_fit": assessment["overall_fit"],
                "overall_fit_label": assessment["overall_fit_label"],
            }
        )
    return out


__all__ = [
    "QUEUE_LIMIT",
    "RequirementInput",
    "build_context",
    "build_queue",
    "client_family_ids",
    "conversation_texts",
    "evaluate_requirements",
    "hourly_pln",
    "job_requirement_inputs",
    "pick_client_rate_hint",
    "requirements_score",
    "risks_for",
]
