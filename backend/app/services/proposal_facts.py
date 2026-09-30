"""Fakty o osobach z propozycji rekrutacji („Dodaj kandydatów” → Propozycje).

Lista propozycji scala cztery źródła (skrzynka, przegląd bazy, podobne
projekty, rekomendacje), a dwa z nich nie niosą o osobie nic poza imieniem
i nazwiskiem — rekruter widział 17 wierszy „nie policzono · stawka —”. Ten
moduł dokłada HURTOWO (dwa zapytania niezależnie od liczby osób) to, po czym da
się osobę ocenić bez otwierania profilu: ostatnie stanowisko, lata
doświadczenia, miasto, tryb pracy, dostępność, stawkę (gdy znana i gdy rola ją
widzi) i historię u TEGO klienta — w której jego rekrutacji osoba była i do
jakiego etapu doszła.

Bez danych kontaktowych: to samo zawężenie tożsamości co wiersz skrzynki
(`_candidate_brief` w `api/job_proposals.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from app.models.recruitment_pipeline import PipelineStage
from app.schemas.pipeline import STAGE_LABELS

# Sufit jednego zapytania — tyle osób widać naraz w panelu (strony po 20–100).
MAX_FACT_CANDIDATES = 100

# Kolejność etapów „do przodu”; odrzucenie i rezygnacja nie są postępem.
_FORWARD_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.posting,
    PipelineStage.new,
    PipelineStage.prep_call,
    PipelineStage.screening,
    PipelineStage.verified,
    PipelineStage.interview,
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.negotiation,
    PipelineStage.onboarding,
    PipelineStage.hired,
)
STAGE_RANK: dict[str, int] = {stage.value: i for i, stage in enumerate(_FORWARD_STAGES)}
_CLOSED_OUTCOMES = {PipelineStage.rejected.value, PipelineStage.withdrawn.value}


def _stage_value(stage: Any) -> Optional[str]:
    value = getattr(stage, "value", stage)
    return value if isinstance(value, str) else None


def stage_label(stage: str) -> str:
    try:
        return STAGE_LABELS[PipelineStage(stage)]
    except (KeyError, ValueError):
        return stage


def current_title(candidate: Any) -> tuple[Optional[str], Optional[str]]:
    """(stanowisko, firma) — ta sama kolejność co `getCurrentTitle` na liście."""

    title = (getattr(candidate, "linkedin_current_title", None) or "").strip() or None
    company = (
        getattr(candidate, "linkedin_current_company", None) or ""
    ).strip() or None
    experience = getattr(candidate, "experience", None)
    first = experience[0] if isinstance(experience, list) and experience else None
    if isinstance(first, dict):
        if title is None:
            role = first.get("role")
            title = role.strip() if isinstance(role, str) and role.strip() else None
        if company is None:
            name = first.get("company")
            company = name.strip() if isinstance(name, str) and name.strip() else None
    return title, company


@dataclass(frozen=True)
class StageRow:
    candidate_id: int
    job_id: int
    job_title: Optional[str]
    stage: Any
    moved_at: Optional[datetime]


def client_history(rows: Iterable[StageRow]) -> dict[int, dict[str, Any]]:
    """Najdalej zaawansowana rekrutacja osoby u klienta.

    Wiersze to CAŁA historia etapów osób w innych rekrutacjach tego klienta.
    Dla każdej pary liczymy najdalszy etap „do przodu” i ostatni etap (wynik:
    odrzucony / zrezygnował / zatrudniony / w toku). Z kilku rekrutacji
    wygrywa ta, w której osoba doszła najdalej; remis — świeższa.
    """

    per_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        stage = _stage_value(row.stage)
        if stage is None:
            continue
        key = (row.candidate_id, row.job_id)
        pair = per_pair.setdefault(
            key,
            {
                "job_id": row.job_id,
                "title": row.job_title,
                "furthest": None,
                "furthest_rank": -1,
                "last": None,
                "last_at": None,
            },
        )
        rank = STAGE_RANK.get(stage)
        if rank is not None and rank > pair["furthest_rank"]:
            pair["furthest"], pair["furthest_rank"] = stage, rank
        moved = row.moved_at
        if pair["last_at"] is None or (moved is not None and moved >= pair["last_at"]):
            pair["last"], pair["last_at"] = stage, moved

    best: dict[int, dict[str, Any]] = {}
    for (candidate_id, _job_id), pair in per_pair.items():
        if pair["furthest"] is None:
            continue
        current = best.get(candidate_id)
        last_at = pair["last_at"]
        sort_key = (
            pair["furthest_rank"],
            last_at.timestamp() if last_at else float("-inf"),
        )
        if current is None or sort_key > current["_sort"]:
            best[candidate_id] = {**pair, "_sort": sort_key}

    out: dict[int, dict[str, Any]] = {}
    for candidate_id, pair in best.items():
        last = pair["last"]
        if last in _CLOSED_OUTCOMES:
            outcome = last
        elif pair["furthest"] == PipelineStage.hired.value:
            outcome = "hired"
        else:
            outcome = "in_progress"
        out[candidate_id] = {
            "job_id": pair["job_id"],
            "title": pair["title"],
            "furthest_stage": pair["furthest"],
            "furthest_stage_label": stage_label(pair["furthest"]),
            "outcome": outcome,
            "last_moved_at": pair["last_at"].isoformat() if pair["last_at"] else None,
        }
    return out


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def candidate_facts(
    candidate: Any,
    *,
    history: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Fakty jednej osoby. Stawka KANDYDATA jest jawna dla każdej roli
    (decyzja Artura 27.09.2026, R10-N7-10 — jak na profilu i liście);
    ``expected_rate_redacted`` zostaje w kształcie odpowiedzi jako ``False``.
    Stawka DO KLIENTA tu nie występuje."""
    title, company = current_title(candidate)
    availability = getattr(candidate, "availability_status", None)
    rate = getattr(candidate, "expected_rate_hourly", None)
    preferences = getattr(candidate, "preferences", None)
    remote_modes = (
        [m for m in preferences.get("remote_modes") or [] if isinstance(m, str)]
        if isinstance(preferences, dict)
        else []
    )
    return {
        "candidate_id": candidate.id,
        "title": title,
        "company": company,
        "years_experience": getattr(candidate, "years_it_experience", None),
        "city": (candidate.city or candidate.location or None),
        "max_onsite_days_per_week": getattr(
            candidate, "max_onsite_days_per_week", None
        ),
        "remote_modes": remote_modes,
        "availability_status": getattr(availability, "value", availability),
        "availability_date": _iso(getattr(candidate, "availability_date", None)),
        "expected_rate_hourly": (
            float(rate) if isinstance(rate, (int, float, Decimal)) else None
        ),
        "expected_rate_currency": getattr(candidate, "expected_rate_currency", None),
        "expected_rate_redacted": False,
        "client_history": history,
    }


async def main_cv_uploaded_on(db: Any, candidate_ids: list[int]) -> dict[int, str]:
    """Data wgrania głównego CV (ISO) — plakietka „CV z RRRR” (30.09.2026).

    Tylko prawdziwa data wgrania (``uploaded_at``); bez niej osoba nie dostaje
    plakietki — nigdy dnia importu (``created_at``), który mówi o migracji,
    nie o świeżości CV. Główne CV wygrywa, nieaktualne pliki się nie liczą.
    """
    from sqlalchemy import text

    if not candidate_ids:
        return {}
    rows = await db.execute(
        text(
            "SELECT DISTINCT ON (candidate_id) candidate_id, uploaded_at "
            "FROM candidate_documents "
            "WHERE candidate_id = ANY(:ids) AND document_kind = 'cv' "
            "AND outdated_at IS NULL "
            "ORDER BY candidate_id, is_primary DESC, uploaded_at DESC NULLS LAST"
        ),
        {"ids": list(candidate_ids)},
    )
    return {
        int(cid): uploaded.date().isoformat()
        for cid, uploaded in rows.all()
        if uploaded is not None
    }
