"""Licznik „wymaga ruchu" rekrutacji — ilu kandydatów czeka na REKRUTERA.

Jedno zagregowane zapytanie na stronę listy rekrutacji (i to samo wyrażenie
jako klucz ``sort=attention``), bez ładowania kart. Reguła jest tą samą regułą
co na karcie (``services/pipeline_next_action.py``): dla każdego szablonu
liczymy RAZ, w Pythonie, tryb każdej kolumny (``always`` / ``after_nudge`` /
``never``), a SQL tylko waży wiersze bieżących etapów:

* kolumna ``always`` → każda karta,
* kolumna ``after_nudge`` (etapy klienta / oferta) → karty stojące co najmniej
  ``NUDGE_DAYS`` dni (``moved_at <= now − NUDGE_DAYS`` — dokładnie to samo co
  ``days_in_stage >= NUDGE_DAYS`` na tablicy),
* reszta (zamknięte, zatrudnieni, onboarding, karty poza szablonem) → 0.

Kubełkowanie wiersza do kolumny jest lustrem ``_bucket_by_stage_def``:
najpierw ``stage_def_id`` należący do szablonu rekrutacji, potem legacy enum
zmapowany przez ``legacy_enum_value``; rekrutacja bez szablonu (i bez
domyślnego) liczy się po legacy enumach jak gałąź legacy tablicy.

ŚWIADOME UPROSZCZENIE: weto hiring managera jest pomijane. Na tablicy karta
z wetem stojąca u klienta krócej niż ``NUDGE_DAYS`` ma właściciela
``recruiter``; tu nie — weta wymagałyby osobnego zapytania per hiring manager.
Licznik listy może więc być o takie karty NIŻSZY niż suma z tablicy.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, case, false, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.pipeline_latest import latest_stage_ids
from app.services.pipeline_next_action import (
    NUDGE_DAYS,
    StageColumn,
    owner_modes_for_columns,
)


def _enum_members(values: Sequence[str]) -> list[PipelineStage]:
    out = []
    for value in values:
        try:
            out.append(PipelineStage(value))
        except ValueError:
            continue
    return out


def _in(column, values):
    return column.in_(values) if values else false()


async def needs_action_subquery(
    db: AsyncSession,
    *,
    job_ids,
    default_template_id: Optional[int],
    now: Optional[datetime] = None,
):
    """Podzapytanie ``(job_id, needs_action_count)`` dla wskazanych rekrutacji.

    ``job_ids`` — lista id albo ``select(Job.id)`` (klucz sortowania liczy się
    nad całym przefiltrowanym zbiorem, nie nad stroną).
    """
    from app.api.pipeline import (  # noqa: PLC0415 — cykl importów
        LEGACY_COLUMN_STAGES,
        legacy_column_meta,
        template_column_meta,
    )

    moment = now or datetime.now(timezone.utc)
    nudged = CandidateStage.moved_at <= moment - timedelta(days=NUDGE_DAYS)

    defs_by_template: dict[int, list[PipelineStageDef]] = {}
    for sd in (
        await db.execute(
            select(PipelineStageDef).order_by(
                PipelineStageDef.template_id, PipelineStageDef.order
            )
        )
    ).scalars():
        defs_by_template.setdefault(sd.template_id, []).append(sd)

    effective_template = (
        func.coalesce(Job.pipeline_template_id, default_template_id)
        if default_template_id is not None
        else Job.pipeline_template_id
    )

    always: list = []
    after_nudge: list = []
    review: list = []
    for template_id, stage_defs in defs_by_template.items():
        metas = [template_column_meta(sd) for sd in stage_defs]
        modes = owner_modes_for_columns([StageColumn.from_meta(m) for m in metas])
        mode_by_def = {sd.id: mode for sd, mode in zip(stage_defs, modes)}
        # Lustro `_bucket_by_stage_def`: przy zdublowanym enumie wygrywa
        # ostatnia definicja.
        enum_to_def = {
            sd.legacy_enum_value: sd.id for sd in stage_defs if sd.legacy_enum_value
        }
        def_ids = [sd.id for sd in stage_defs]
        in_template = _in(CandidateStage.stage_def_id, def_ids)
        for mode, bucket in (
            ("always", always),
            ("after_nudge", after_nudge),
            ("review", review),
        ):
            own_ids = [i for i in def_ids if mode_by_def[i] == mode]
            enums = _enum_members(
                [e for e, def_id in enum_to_def.items() if mode_by_def[def_id] == mode]
            )
            bucket.append(
                and_(
                    effective_template == template_id,
                    or_(
                        _in(CandidateStage.stage_def_id, own_ids),
                        and_(
                            or_(
                                CandidateStage.stage_def_id.is_(None),
                                ~in_template,
                            ),
                            _in(CandidateStage.stage, enums),
                        ),
                    ),
                )
            )

    # Rekrutacja bez (niepustego) szablonu — kolumny SĄ legacy enumami.
    legacy_columns = [
        StageColumn.from_meta(legacy_column_meta(stage))
        for stage in LEGACY_COLUMN_STAGES
    ]
    legacy_modes = owner_modes_for_columns(legacy_columns)
    templated = list(defs_by_template)
    no_template = or_(
        effective_template.is_(None),
        ~_in(effective_template, templated),
    )
    for mode, bucket in (
        ("always", always),
        ("after_nudge", after_nudge),
        ("review", review),
    ):
        stages = [
            stage
            for stage, stage_mode in zip(LEGACY_COLUMN_STAGES, legacy_modes)
            if stage_mode == mode
        ]
        bucket.append(and_(no_template, _in(CandidateStage.stage, stages)))

    weight = case(
        (or_(*always), literal(1)),
        (and_(or_(*after_nudge), nudged), literal(1)),
        else_=literal(0),
    )
    # Stos wejściowy (Ogłoszenia, Nowi) — „Do przejrzenia", poza „wymaga ruchu".
    review_weight = case((or_(*review), literal(1)), else_=literal(0))
    latest = latest_stage_ids(job_ids=job_ids)
    return (
        select(
            CandidateStage.job_id.label("job_id"),
            func.coalesce(func.sum(weight), 0).label("needs_action_count"),
            func.coalesce(func.sum(review_weight), 0).label("review_count"),
        )
        .join(Job, Job.id == CandidateStage.job_id)
        .where(CandidateStage.id.in_(select(latest.c.latest_id)))
        .group_by(CandidateStage.job_id)
        .subquery()
    )


async def needs_action_counts(
    db: AsyncSession,
    *,
    job_ids: Sequence[int],
    default_template_id: Optional[int],
    now: Optional[datetime] = None,
) -> dict[int, int]:
    """Licznik dla strony listy — jedno zapytanie."""
    ids = sorted({int(j) for j in job_ids})
    if not ids:
        return {}
    sub = await needs_action_subquery(
        db, job_ids=ids, default_template_id=default_template_id, now=now
    )
    rows = await db.execute(select(sub.c.job_id, sub.c.needs_action_count))
    return {int(job_id): int(count or 0) for job_id, count in rows.all()}


async def attention_counts(
    db: AsyncSession,
    *,
    job_ids: Sequence[int],
    default_template_id: Optional[int],
    now: Optional[datetime] = None,
) -> dict[int, tuple[int, int]]:
    """``job_id → (wymaga ruchu, do przejrzenia)`` — jedno zapytanie."""
    ids = sorted({int(j) for j in job_ids})
    if not ids:
        return {}
    sub = await needs_action_subquery(
        db, job_ids=ids, default_template_id=default_template_id, now=now
    )
    rows = await db.execute(
        select(sub.c.job_id, sub.c.needs_action_count, sub.c.review_count)
    )
    return {
        int(job_id): (int(needs or 0), int(review_n or 0))
        for job_id, needs, review_n in rows.all()
    }
