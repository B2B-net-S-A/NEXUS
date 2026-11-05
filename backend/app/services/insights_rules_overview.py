"""Przegląd zasad NEXUSA do zakładki Insights → Zasady (decyzja Artura 05.11.2026).

Jedno pytanie na wiersz: co dziś obowiązuje i kto to ostatnio zmienił. Wartości
pochodzą z tych samych odczytów co ekrany edycji, więc przegląd nie ma własnej
kopii reguł. Zdania układają czyste funkcje `*_now`, a `last_change` równe `None`
znaczy, że nikt tej zasady nie zmienił i działa wartość domyślna.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.insights_scoring_config import InsightsScoringConfig
from app.models.kpi_target_event import KpiTargetEvent
from app.models.placement_exclusion import PlacementExclusion
from app.models.prep_meeting import PrepReviewConfigVersion
from app.models.recruitment_priority import RecruitmentPriorityAuditEvent
from app.models.scoring_weight_change import ScoringWeightChange
from app.models.user import User
from app.services import job_twin_rules, prep_review_config, qc_quality, ranking_weights, work_rhythm
from app.services.cv_qc import LABELS
from app.services.insights_scoring_config import get_scoring_config
from app.services.kpi_target_editor import build_matrix
from app.services.placement_exclusions import SERIES_THRESHOLD
from app.services.recruitment_allocation import effective_allocation_mode
from app.services.request_allocation_rules import (
    RULES_KEY as ALLOCATION_RULES_KEY,
    AllocationRules,
    load_rules as load_allocation_rules,
)

# Tryb i godzina przeglądu zapisują się inaczej niż pozostałe zasady automatu,
# więc ostatnia zmiana to późniejszy z dwóch śladów.
_ALLOCATION_EVENTS = ("allocation_rules_changed", "allocation_mode_changed")
_MODE_LABELS = {"off": "Wyłączony", "shadow": "Proponuje", "auto": "Przydziela sam"}
_TWIN_RULE_LABELS = {
    "critical": "krytyczne",
    "must": "wspólne wymagania",
    "location": "lokalizacja",
    "work_mode": "tryb pracy",
    "budget": "budżet",
    "client": "ten sam klient",
    "category": "ta sama kategoria",
    "different_dl": "różny DL",
}
_RANKING_LABELS = {
    "semantic": "Podobieństwo CV",
    "salary": "stawka",
    "skills": "umiejętności",
    "location": "lokalizacja",
    "availability": "dostępność",
}
_PREP_LABELS = {
    "must_answers": "must-have",
    "prep1_followup": "punkty z Prepu 1",
    "topics": "tematy",
    "client_questions": "pytania klienta",
    "talk_share": "proporcja rozmowy",
}


@dataclass(frozen=True)
class LastChange:
    at: datetime
    # `None` = zapis automatu, nie człowieka.
    by: Optional[str]


def _number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def allocation_now(mode: str, rules: AllocationRules) -> str:
    label = _MODE_LABELS.get(mode, mode)
    if mode == "off":
        return f"{label} · przegląd {rules.review_time}"
    scope = "P0, P1 i P2" if rules.include_p2 else "P0 i P1"
    load = "bez limitu obłożenia" if rules.max_load is None else f"limit obłożenia {rules.max_load}"
    return f"{label} · {scope} · {rules.people_per_p1} os. na P1 · {load} · przegląd {rules.review_time}"


def twin_now(rules: dict[str, Any]) -> str:
    required = [
        label for key, label in _TWIN_RULE_LABELS.items() if rules[key]["mode"] == "required"
    ]
    parts = [f"Podobieństwo od {rules['min_similarity']}%"]
    parts.append(f"wymagane: {', '.join(required)}" if required else "bez zasad wymaganych")
    parts.append(f"najwyżej {rules['max_twins']} bliźniaki")
    return " · ".join(parts)


def ranking_now(shares: dict[str, float], threshold: int) -> str:
    ordered = sorted(
        (item for item in shares.items() if item[0] in _RANKING_LABELS and item[1] > 0),
        key=lambda item: -item[1],
    )
    parts = [f"{_RANKING_LABELS[key]} {round(share)}%" for key, share in ordered]
    return " · ".join([*parts, f"próg {threshold}"])


def prep_now(weights: dict[str, int]) -> str:
    ordered = sorted(weights.items(), key=lambda item: -item[1])
    return " · ".join(f"{_PREP_LABELS.get(key, key)} {value}" for key, value in ordered)


def kpi_now(targets: dict[str, int], overrides: int) -> str:
    text = (
        f"Rekruter: {targets['daily_completed_calls']} rozmów i "
        f"{targets['daily_first_verifications']} weryfikacje dziennie · "
        f"{targets['weekly_cvs_sent']} rekomendacji tygodniowo · "
        f"{targets['monthly_placements']} placement · precyzja {targets['monthly_precision']}%"
    )
    return f"{text} · wyjątki: {overrides}" if overrides else text


def league_now(config: dict[str, int]) -> str:
    return (
        f"Placement {config['league_points_placement']} · "
        f"rozmowa {config['league_points_interview']} · "
        f"rekomendacja {config['league_points_recommendation']} · "
        f"Senior {config['seniority_senior_placements']} w {config['seniority_senior_window_months']} mies. · "
        f"Ekspert {config['seniority_expert_placements']} w {config['seniority_expert_window_months']} mies."
    )


def rhythm_now(rules: dict[str, Any]) -> str:
    weights = rules["weights"]
    return (
        f"Screening {_number(weights['screening'])} · "
        f"rozmowa u klienta {_number(weights['client_step'])} · "
        f"CV {_number(weights['cv'])} · notatka {_number(weights['note'])} · "
        f"norma {_number(rules['norm_day_points'])} pkt dziennie"
    )


def qc_now(states: dict[str, dict[str, Any]], effective: dict[str, str]) -> str:
    parts = [f"Sprawdzeń: {len(effective)}"]
    muted = sum(1 for state in effective.values() if state != "active")
    if muted:
        parts.append(f"nieaktywne: {muted}")
    measured = [
        (entry["precision"], key)
        for key, entry in states.items()
        if key in effective
        and entry.get("precision") is not None
        and (entry.get("shown") or 0) >= qc_quality.AUTO_MIN_SHOWN
    ]
    if measured:
        precision, key = min(measured)
        parts.append(f"najsłabsza trafność: {LABELS.get(key, key)} {round(precision * 100)}%")
    return " · ".join(parts)


def qc_last_change(states: dict[str, dict[str, Any]]) -> Optional[tuple[datetime, Optional[int]]]:
    """Ręczny stan sprawdzenia. `updated_at` wpisu nie mówi nic, bo automat
    przelicza w nim trafność co noc."""
    manual = [
        (datetime.fromisoformat(entry["manual_at"]), entry.get("manual_by"))
        for entry in states.values()
        if entry.get("manual_at")
    ]
    return max(manual, key=lambda item: item[0]) if manual else None


def placements_now(count: int) -> str:
    return f"Par poza statystykami: {count} · seria od {SERIES_THRESHOLD} par dziennie bez CV"


async def _user_name(db: AsyncSession, user_id: Optional[int]) -> Optional[str]:
    if user_id is None:
        return None
    return await db.scalar(select(User.name).where(User.id == user_id))


async def _setting_change(db: AsyncSession, key: str) -> Optional[LastChange]:
    """Zapis ustawienia przez człowieka; wiersz bez autora to zasiew albo automat."""
    row = (
        await db.execute(
            select(AppSetting.updated_at, User.name)
            .join(User, User.id == AppSetting.updated_by)
            .where(AppSetting.key == key)
        )
    ).first()
    return LastChange(row[0], row[1]) if row else None


async def _allocation_change(db: AsyncSession) -> Optional[LastChange]:
    setting = await _setting_change(db, ALLOCATION_RULES_KEY)
    row = (
        await db.execute(
            select(RecruitmentPriorityAuditEvent.occurred_at, User.name)
            .join(User, User.id == RecruitmentPriorityAuditEvent.actor_user_id, isouter=True)
            .where(RecruitmentPriorityAuditEvent.event_type.in_(_ALLOCATION_EVENTS))
            .order_by(RecruitmentPriorityAuditEvent.occurred_at.desc())
            .limit(1)
        )
    ).first()
    event = LastChange(row[0], row[1]) if row else None
    candidates = [change for change in (setting, event) if change]
    return max(candidates, key=lambda change: change.at) if candidates else None


async def _ranking_change(db: AsyncSession) -> Optional[LastChange]:
    row = (
        await db.execute(
            select(ScoringWeightChange.created_at, User.name)
            .join(User, User.id == ScoringWeightChange.actor_id, isouter=True)
            .order_by(ScoringWeightChange.created_at.desc())
            .limit(1)
        )
    ).first()
    return LastChange(row[0], row[1]) if row else None


async def _prep_change(db: AsyncSession) -> Optional[LastChange]:
    row = (
        await db.execute(
            select(PrepReviewConfigVersion.created_at, User.name)
            .join(User, User.id == PrepReviewConfigVersion.created_by, isouter=True)
            .order_by(PrepReviewConfigVersion.created_at.desc())
            .limit(1)
        )
    ).first()
    return LastChange(row[0], row[1]) if row else None


async def _kpi_change(db: AsyncSession) -> Optional[LastChange]:
    row = (
        await db.execute(
            select(KpiTargetEvent.created_at, KpiTargetEvent.actor_name)
            .order_by(KpiTargetEvent.created_at.desc())
            .limit(1)
        )
    ).first()
    return LastChange(row[0], row[1]) if row else None


async def _league_change(db: AsyncSession) -> Optional[LastChange]:
    # Wiersze z migracji nie mają autora: to wartości startowe, nie zmiana.
    row = (
        await db.execute(
            select(InsightsScoringConfig.updated_at, User.name)
            .join(User, User.id == InsightsScoringConfig.updated_by)
            .order_by(InsightsScoringConfig.updated_at.desc())
            .limit(1)
        )
    ).first()
    return LastChange(row[0], row[1]) if row else None


def _row(rule_id: str, now: str, last_change: Optional[LastChange]) -> dict[str, Any]:
    return {
        "id": rule_id,
        "now": now,
        "last_change": (
            {"at": last_change.at, "by": last_change.by} if last_change else None
        ),
    }


def _kpi_inputs(matrix: dict[str, Any]) -> tuple[dict[str, int], int]:
    recruiter = next(role for role in matrix["roles"] if role["role"] == "recruiter")
    targets = {key: cell["effective"] for key, cell in recruiter["targets"].items()}
    overrides = sum(
        1
        for owner in [*matrix["roles"], *matrix["users"]]
        for cell in owner["targets"].values()
        if cell.get("override") is not None
    )
    return targets, overrides


async def build_overview(db: AsyncSession, *, is_admin: bool) -> list[dict[str, Any]]:
    """Wiersze przeglądu. Trzy ostatnie zmienia wyłącznie administrator, więc
    Head of Recruitment bez tej roli ich nie dostaje."""
    prep_config, _ = await prep_review_config.current(db)
    published, profile, _ = await ranking_weights.published_panel(db)
    twin = await job_twin_rules.load(db)
    rhythm = await work_rhythm.load_rules(db)
    targets, overrides = _kpi_inputs(await build_matrix(db))

    rows = [
        _row(
            "przydzial",
            allocation_now(await effective_allocation_mode(db), await load_allocation_rules(db)),
            await _allocation_change(db),
        ),
        _row(
            "blizniaki",
            twin_now(twin.model_dump()),
            await _setting_change(db, job_twin_rules.SETTING_KEY),
        ),
        _row(
            "ranking",
            ranking_now(ranking_weights.profile_shares(profile), published.as_dict()["threshold"]),
            await _ranking_change(db),
        ),
        _row(
            "prepy",
            prep_now(prep_config.model_dump()["prep1"]["weights"]),
            await _prep_change(db),
        ),
        _row("cele", kpi_now(targets, overrides), await _kpi_change(db)),
        _row(
            "aktywnosc",
            rhythm_now(rhythm.as_json()),
            await _setting_change(db, work_rhythm.RULES_KEY),
        ),
    ]
    if not is_admin:
        return rows

    states = await qc_quality.load_states(db)
    manual = qc_last_change(states)
    qc_change = LastChange(manual[0], await _user_name(db, manual[1])) if manual else None
    placement_count = await db.scalar(select(func.count()).select_from(PlacementExclusion))
    placement_at = await db.scalar(select(func.max(PlacementExclusion.detected_at)))
    rows += [
        _row("qc", qc_now(states, qc_quality.effective_states(states)), qc_change),
        _row("liga", league_now(await get_scoring_config(db)), await _league_change(db)),
        _row(
            "placementy",
            placements_now(placement_count or 0),
            LastChange(placement_at, None) if placement_at else None,
        ),
    ]
    return rows
