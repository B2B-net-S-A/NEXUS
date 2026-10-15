"""Odczyty rekrutacji dla API integracyjnego v1 (scope ``recruitments:read``).

Warstwa nad funkcjami ekranów rekrutacji: liczy to samo co lista, Tablica,
Profil Championa i dziennik ruchów, ale BEZ efektów ubocznych ekranu —
``GET /api/jobs/{id}/champion-profile`` oznacza powiadomienia jako przeczytane
i robi commit, a tutaj nic nie zapisujemy.

Kwoty dzieli ``MoneyVisibility`` (poziom liczy trasa z ``common.amount_level``,
moduł nie zna scope'ów):

* sprzedaż — stawka do klienta na karcie Tablicy (``client_rate_*``);
* koszt — budżet rekrutacji dla kandydata (``rate_budget_hourly*``,
  ``effective_budget_hourly*``, ``salary_min/max``), stawka Championa
  (``basics.rate_value`` i tekst ``basics.rate_raw``) oraz oczekiwania
  kandydata na karcie (``expected_rate_*``, ``budget_max_at_move``,
  ``budget_exceeded``).

Pole schowane = ``None``. Importy ``app.api.pipeline`` są leniwe — moduły
ekranów mają cykl importów z warstwą usług (jak ``job_needs_action``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
)
from app.models.recruitment_pipeline import CandidateStage
from app.services import champion_view


# ── Kwoty ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MoneyVisibility:
    """Które kwoty widzi klucz: ``sales`` — sprzedaż, ``costs`` — koszt."""

    sales: bool
    costs: bool

    @property
    def amounts_redacted(self) -> bool:
        return not self.sales

    @property
    def costs_redacted(self) -> bool:
        return not self.costs


def as_money(value: Any) -> Optional[Decimal]:
    """Kwota z kolumny albo wyliczenia; float przez ``str``, żeby nie zgubić groszy."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class ClientRate:
    value: Decimal
    unit: Optional[str]
    currency: Optional[str]


# Pola karty Tablicy według rodzaju kwoty — jedna lista dla trasy i testów.
CARD_SALES_FIELDS: tuple[str, ...] = (
    "client_rate_value",
    "client_rate_unit",
    "client_rate_currency",
)
CARD_COST_FIELDS: tuple[str, ...] = (
    "expected_rate_value",
    "expected_rate_unit",
    "expected_rate_currency",
    "budget_max_at_move",
    "budget_exceeded",
)
JOB_BUDGET_FIELDS: tuple[str, ...] = (
    "rate_budget_hourly",
    "rate_budget_hourly_min",
    "effective_budget_hourly",
    "effective_budget_hourly_min",
    "salary_min",
    "salary_max",
)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def card_money(
    card: Mapping[str, Any],
    *,
    client_rate: Optional[ClientRate],
    visibility: MoneyVisibility,
) -> dict[str, Any]:
    """Kwoty jednej karty Tablicy według poziomu klucza.

    Stawkę do klienta podaje wołający (``latest_client_rates``): Tablica
    zbudowana bez patrzącego (``viewer=None``) zeruje ją jak rekruterowi.
    """
    out: dict[str, Any] = {
        "amounts_redacted": visibility.amounts_redacted,
        "costs_redacted": visibility.costs_redacted,
    }
    if visibility.sales and client_rate is not None:
        out["client_rate_value"] = client_rate.value
        out["client_rate_unit"] = client_rate.unit
        out["client_rate_currency"] = client_rate.currency
    else:
        out.update({key: None for key in CARD_SALES_FIELDS})
    if visibility.costs:
        out["expected_rate_value"] = as_money(card.get("expected_rate_value"))
        out["expected_rate_unit"] = _enum_value(card.get("expected_rate_unit"))
        out["expected_rate_currency"] = card.get("expected_rate_currency")
        out["budget_max_at_move"] = as_money(card.get("budget_max_at_move"))
        out["budget_exceeded"] = bool(card.get("budget_exceeded"))
    else:
        out.update({key: None for key in CARD_COST_FIELDS})
    return out


def job_budget(job: Job, *, visibility: MoneyVisibility) -> dict[str, Any]:
    """Budżet rekrutacji dla kandydata (PLN/h, a ``salary_*`` PLN/mies.) — koszt.

    ``effective_*`` to ta sama reguła co nagłówek rekrutacji
    (``JobResponse.effective_budget_hourly``): jawne pole, a bez niego stawka
    Championa.
    """
    if not visibility.costs:
        return {key: None for key in JOB_BUDGET_FIELDS}
    from app.services.dealbreaker_filters import resolve_job_budget_hourly
    from app.services.job_budget_range import effective_min

    return {
        "rate_budget_hourly": as_money(job.rate_budget_hourly),
        "rate_budget_hourly_min": as_money(job.rate_budget_hourly_min),
        "effective_budget_hourly": as_money(resolve_job_budget_hourly(job)),
        "effective_budget_hourly_min": as_money(effective_min(job)),
        "salary_min": as_money(job.salary_min),
        "salary_max": as_money(job.salary_max),
    }


async def latest_client_rates(db: AsyncSession, job_id: int) -> dict[int, ClientRate]:
    """Stawka do klienta każdej pary: ostatnia niepusta w rekrutacji.

    Ta sama reguła co karta Tablicy (``carried_client_rate`` w
    ``build_kanban_view``): wiersze pary od najnowszego ``(moved_at, id)``.
    """
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.client_rate_value,
            CandidateStage.client_rate_unit,
            CandidateStage.client_rate_currency,
        )
        .where(
            CandidateStage.job_id == job_id,
            CandidateStage.client_rate_value.is_not(None),
        )
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .distinct(CandidateStage.candidate_id)
    )
    return {
        cid: ClientRate(value=value, unit=_enum_value(unit), currency=currency)
        for cid, value, unit, currency in rows.all()
    }


# ── Wymagania (Profil Championa) bez efektów ubocznych ───────────────────────


def _text(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _words(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [w.strip() for w in value if isinstance(w, str) and w.strip()]


_ROW_LEVELS = ("critical", "must", "nice")


def _search_rows(stack: Mapping[str, Any]) -> list[dict]:
    """Wiersze „Szukamy po tych słowach” (``stack.rows``); poziom spoza listy = must."""
    out: list[dict] = []
    for row in stack.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        words = _words(row.get("words"))
        if not words:
            continue
        level = row.get("level")
        out.append({"words": words, "level": level if level in _ROW_LEVELS else "must"})
    return out


def _experience_items(items: Any) -> list[dict]:
    out: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"))
        if name is None:
            continue
        level = item.get("level")
        out.append(
            {
                "name": name,
                "level": level if level in ("must", "nice") else "must",
                "min_years": _int(item.get("min_years")),
                "note": item.get("note") if isinstance(item.get("note"), str) else "",
            }
        )
    return out


def _screening_questions(job: Job) -> list[dict]:
    out: list[dict] = []
    for question in champion_view.screening_questions(job):
        if not isinstance(question, Mapping):
            continue
        text = _text(question.get("question"))
        if text is None:
            continue
        out.append(
            {
                "id": str(question.get("id") or ""),
                "question": text,
                "ideal_answer": _text(question.get("ideal_answer")) or "",
                "deal_breaker": _text(question.get("deal_breaker")) or "",
            }
        )
    return out


def requirements_view(job: Job, *, visibility: MoneyVisibility) -> dict[str, Any]:
    """Wymagania rekrutacji — dwie listy (13.10.2026) i Champion, bez zapisu.

    * „Szukamy po tych słowach” — wiersze wymagań (``stack.rows``) i listy
      must / nice z kontraktu wymagań (``champion_intake.effective_skill_names``,
      to samo co ``job_values`` edytora);
    * „Rekruter sprawdza w rozmowie” — sekcja 4 Championa ``experience``
      (``skills``, dziedziny, certyfikaty, regulacje); nie filtruje kandydatów.

    Krytyczne liczy ``critical_skills.effective_critical`` — to samo, na czym
    działa bramka propozycji AI. Stawka Championa to koszt.
    """
    from app.services.champion_intake import effective_skill_names
    from app.services.critical_skills import effective_critical
    from app.services.requirement_contract import stored_contract

    profile = champion_view.as_dict(job)
    basics = champion_view.basics(job)
    stack = champion_view.stack(job)
    experience = champion_view.experience(job)
    project = champion_view.project(job)
    critical = effective_critical(job)
    contract = stored_contract(job)
    stack_notes = stack.get("notes")
    experience_notes = experience.get("notes")

    return {
        "job_id": job.id,
        "title": job.title,
        "has_champion_profile": bool(profile),
        "role_name": _text(basics.get("role_name")),
        "seniority_min_years": champion_view.seniority_min_years(job),
        "language": _text(basics.get("language")),
        "work_mode": _text(basics.get("work_mode")),
        "onsite_days_per_week": _int(basics.get("onsite_days_per_week")),
        "candidate_location_pref": _text(basics.get("candidate_location_pref")),
        "start_date": _text(basics.get("start_date")),
        "contract_length": _text(basics.get("contract_length")),
        "must_skills": list(effective_skill_names(job, "must")),
        "nice_skills": list(effective_skill_names(job, "nice")),
        "critical": {
            "effective": list(critical.labels),
            "source": critical.source,
            "decided": critical.decided,
            "suggested": list(critical.suggested),
        },
        "search_rows": _search_rows(stack),
        "requirements_reviewed": (
            contract.reviewed
            if contract is not None
            else bool(job.requirements_reviewed)
        ),
        "requirement_groups": [
            {"any_of": list(group.any_of), "level": group.level}
            for group in (contract.all_of if contract is not None else [])
        ],
        "talk_checks": {
            "skills": _experience_items(experience.get("skills")),
            "domains": _experience_items(experience.get("domains")),
            "certifications": _experience_items(experience.get("certifications")),
            "regulations": _experience_items(experience.get("regulations")),
            "notes": experience_notes if isinstance(experience_notes, str) else "",
        },
        "stack_notes": stack_notes if isinstance(stack_notes, str) else "",
        "disqualifiers": champion_view.disqualifiers(job),
        "requirements_text": job.requirements,
        "project_about": _text(project.get("about")) or "",
        "project_responsibilities": _text(project.get("responsibilities")) or "",
        "screening_questions": _screening_questions(job),
        "amounts_redacted": visibility.amounts_redacted,
        "costs_redacted": visibility.costs_redacted,
        "champion_rate_hourly": (
            as_money(champion_view.hourly_rate(job)) if visibility.costs else None
        ),
        "champion_rate_raw": (
            _text(basics.get("rate_raw")) if visibility.costs else None
        ),
    }


# ── Kolumny i liczniki Tablicy ───────────────────────────────────────────────


def _column_dict(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Kolumna jako słownik z wartościami enumów; kolumna legacy (bez szablonu)
    nie ma ``stage_def_id`` ani ``order`` — dostaje ``None``."""
    out = {"stage_def_id": None, "order": None, **meta}
    out["stage"] = _enum_value(out.get("stage"))
    out["category"] = _enum_value(out.get("category"))
    return out


@dataclass(frozen=True)
class StageCounts:
    columns: list[dict]
    off_template: int
    candidates: int


async def stage_counts_for_jobs(
    db: AsyncSession, jobs: Sequence[Job]
) -> dict[int, StageCounts]:
    """Osoby w kolumnach Tablicy — te same kolumny i to samo kubełkowanie co
    ``GET /api/jobs?include_stage_counts`` (bieżący etap pary, jedno
    ``GROUP BY`` na stronę)."""
    from app.api.pipeline import (  # noqa: PLC0415 — cykl importów
        StageTally,
        _default_template_id,
        legacy_stage_column_summaries,
        stage_column_summaries,
    )
    from app.services.pipeline_latest import latest_stage_ids

    job_ids = [job.id for job in jobs]
    if not job_ids:
        return {}
    latest = latest_stage_ids(job_ids=job_ids)
    tally_rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.stage_def_id,
                CandidateStage.stage,
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(CandidateStage.id.in_(select(latest.c.latest_id)))
            .group_by(
                CandidateStage.job_id,
                CandidateStage.stage_def_id,
                CandidateStage.stage,
            )
        )
    ).all()
    tallies: dict[int, list] = {}
    for job_id, stage_def_id, stage, n in tally_rows:
        tallies.setdefault(job_id, []).append(
            StageTally(stage_def_id=stage_def_id, stage=stage, count=int(n))
        )

    default_template_id = await _default_template_id(db)
    template_ids = {
        tid
        for tid in (job.pipeline_template_id or default_template_id for job in jobs)
        if tid is not None
    }
    defs_by_template: dict[int, list[PipelineStageDef]] = {}
    all_defs: dict[int, PipelineStageDef] = {}
    if template_ids:
        for sd in (
            await db.execute(
                select(PipelineStageDef).order_by(
                    PipelineStageDef.template_id, PipelineStageDef.order
                )
            )
        ).scalars():
            all_defs[sd.id] = sd
            if sd.template_id in template_ids:
                defs_by_template.setdefault(sd.template_id, []).append(sd)

    out: dict[int, StageCounts] = {}
    for job in jobs:
        tid = job.pipeline_template_id or default_template_id
        entries = tallies.get(job.id, [])
        if tid is not None and defs_by_template.get(tid):
            columns, off = stage_column_summaries(
                defs_by_template[tid],
                entries,
                {i: d for i, d in all_defs.items() if d.template_id != tid},
            )
        else:
            columns, off = legacy_stage_column_summaries(entries)
        out[job.id] = StageCounts(
            columns=[_column_dict(c) for c in columns],
            off_template=off,
            candidates=sum(t.count for t in entries),
        )
    return out


async def stage_definitions(
    db: AsyncSession, job: Job
) -> tuple[Optional[PipelineTemplate], list[dict]]:
    """Kolumny szablonu rekrutacji — te same definicje co kolumny Tablicy
    (``template_column_meta``; bez szablonu kolumny legacy enumów)."""
    from app.api.pipeline import (  # noqa: PLC0415 — cykl importów
        LEGACY_COLUMN_STAGES,
        _default_template_id,
        legacy_column_meta,
        template_column_meta,
    )

    template_id = job.pipeline_template_id or await _default_template_id(db)
    if template_id is not None:
        template = await db.get(PipelineTemplate, template_id)
        defs = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == template_id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )
        return template, [
            {**_column_dict(template_column_meta(sd)), "is_terminal": sd.is_terminal}
            for sd in defs
        ]
    stages = []
    for order, stage in enumerate(LEGACY_COLUMN_STAGES):
        meta = _column_dict(legacy_column_meta(stage))
        stages.append(
            {
                **meta,
                "stage_def_id": None,
                "order": order,
                "is_terminal": meta.get("terminal_type") is not None,
            }
        )
    return None, stages


# ── Dziennik ruchów ──────────────────────────────────────────────────────────


async def job_moves_page(
    db: AsyncSession,
    job_id: int,
    *,
    page: int,
    page_size: int,
    candidate_id: Optional[int] = None,
) -> tuple[list[dict], int]:
    """Ruchy etapów rekrutacji od najnowszych — zapytanie dziennika ekranu
    (``_JOB_MOVES_SQL``) plus powód odrzucenia i „kto zakończył” z wierszy strony."""
    from app.api.pipeline import (  # noqa: PLC0415 — cykl importów
        _JOB_MOVES_COUNT_SQL,
        _JOB_MOVES_SQL,
        _move_stage_label,
    )

    offset = (page - 1) * page_size
    scope = {"job_id": job_id, "candidate_id": candidate_id}
    rows = (
        await db.execute(
            _JOB_MOVES_SQL, {**scope, "limit": page_size, "offset": offset}
        )
    ).all()
    if rows:
        total = int(rows[0].total)
    elif offset:
        # Strona za końcem listy nie niesie wiersza z `total`.
        total = int(await db.scalar(_JOB_MOVES_COUNT_SQL, scope) or 0)
    else:
        total = 0
    extra: dict[int, tuple] = {}
    if rows:
        reason_rows = await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.rejection_reason_id,
                RejectionReason.name,
                CandidateStage.ended_by,
            )
            .outerjoin(
                RejectionReason,
                RejectionReason.id == CandidateStage.rejection_reason_id,
            )
            .where(CandidateStage.id.in_([row.id for row in rows]))
        )
        extra = {
            stage_id: (reason_id, reason_name, ended_by)
            for stage_id, reason_id, reason_name, ended_by in reason_rows.all()
        }
    items = []
    for row in rows:
        reason_id, reason_name, ended_by = extra.get(row.id, (None, None, None))
        name = (
            f"{row.candidate_first_name or ''} {row.candidate_lastname or ''}".strip()
            or None
        )
        items.append(
            {
                "id": row.id,
                "candidate": {"id": row.candidate_id, "name": name},
                "from_stage": row.prev_stage,
                "from_stage_name": _move_stage_label(
                    row.prev_stage_name, row.prev_stage
                ),
                "to_stage": row.stage,
                "to_stage_name": _move_stage_label(row.stage_name, row.stage),
                "moved_by": (
                    {"id": row.moved_by, "name": row.moved_by_name}
                    if row.moved_by is not None
                    else None
                ),
                "moved_at": row.moved_at,
                # Wiersze z importu niosą `external_source='traffit'`.
                "source": "traffit" if row.external_source == "traffit" else "nexus",
                "rejection_reason": (
                    {"id": reason_id, "name": reason_name}
                    if reason_id is not None
                    else None
                ),
                "ended_by": ended_by,
            }
        )
    return items, total
