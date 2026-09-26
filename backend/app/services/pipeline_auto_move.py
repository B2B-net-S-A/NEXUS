"""Automatyczny ruch karty do przodu (Pipeline v4, 23.09.2026).

Zdarzenie spoza tablicy (terminy od klienta, podpisana umowa) mówi, gdzie
kandydat JUŻ jest w procesie — karta ma tam pojechać sama, bez klikania.
Reguła jest jedna i wąska:

* karta rusza się WYŁĄCZNIE do przodu — kandydat, który jest już na etapie
  docelowym albo dalej, zostaje tam, gdzie jest (ktoś mógł go przesunąć
  ręcznie dalej, a automat nie ma prawa go cofnąć);
* proces zamknięty (odrzucony, wycofany, zatrudniony, „Rezerwa") nie jest
  ruszany — automat nie otwiera zamkniętej historii;
* para bez żadnego etapu nie powstaje — automat nie zakłada rekrutacji
  (``transition_process(require_existing=True)``, jak podpis umowy);
* kandydat z globalnej czarnej listy albo z wetem hiring managera zostaje na
  miejscu — na tablicy taki ruch wymaga świadomego „Przenieś mimo to”
  (``ELIGIBILITY_WARNING``), a automat nie ma kogo zapytać (runda 7, N7-3).

Efekty, które ``/pipeline/move`` robi przy tym samym ruchu, robi też automat:
przepięcie do podobnych rekrutacji (``on_candidate_sent``) w transakcji, a
powiadomienia o etapie i profil ryzyka — ``run_after_commit`` PO commicie
wołającego (runda 7, N7-4).

„Wcześniej” liczy się po pozycji w SZABLONIE rekrutacji (``PipelineStageDef
.order``): etapy własne szablonu mają kod ``new`` i sam kod niczego nie mówi.
Etap z obcego szablonu (import Traffita) porównujemy po kolumnie Tablicy
(``board_column_for``), a wiersz bez definicji etapu — po ``STAGE_ORDER``.

Funkcja nie commituje i nie rzuca w przypadkach „nie dotyczy” — zwraca
``None``. Rozsyłka ``pipeline_changed`` należy do wołającego, PO commicie.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_pipeline import STAGE_ORDER, CandidateStage, PipelineStage
from app.models.user import User
from app.services.board_stage_badges import BOARD_COLUMN_ORDER, board_column_for
from app.services.candidate_contact_hooks import maybe_close_contact_opportunity
from app.services.priority_work_policy import PriorityWorkLocked
from app.services.recruitment_process_commands import transition_process

logger = logging.getLogger(__name__)

_TERMINAL_STAGES = frozenset(
    {PipelineStage.hired, PipelineStage.rejected, PipelineStage.withdrawn}
)
# Kolejność kolumn Tablicy (8 kolumn od 24.09.2026, jedno źródło w
# `board_stage_badges`); „closed” nie ma pozycji — to koniec.
_COLUMN_RANK = {column: rank for rank, column in enumerate(BOARD_COLUMN_ORDER)}


def _enum_value(value) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


async def _template_id(db: AsyncSession, job: Job) -> Optional[int]:
    if job.pipeline_template_id is not None:
        return job.pipeline_template_id
    return await db.scalar(
        select(PipelineTemplate.id)
        .where(PipelineTemplate.is_default.is_(True))
        .order_by(PipelineTemplate.id)
        .limit(1)
    )


async def _target_stage_def(
    db: AsyncSession, template_id: Optional[int], target: PipelineStage
) -> Optional[PipelineStageDef]:
    """Pierwszy (najniższy ``order``) etap szablonu z kodem docelowym.

    Dla celu nieterminalnego pomijamy etapy terminalne — kolumna „Rozmowa
    u klienta” nie może trafić na etap zamykający proces.
    """
    if template_id is None:
        return None
    query = select(PipelineStageDef).where(
        PipelineStageDef.template_id == template_id,
        PipelineStageDef.legacy_enum_value == target.value,
    )
    if target not in _TERMINAL_STAGES:
        query = query.where(PipelineStageDef.is_terminal.is_(False))
    return await db.scalar(
        query.order_by(PipelineStageDef.order, PipelineStageDef.id).limit(1)
    )


def _column(stage: PipelineStage, stage_def: Optional[PipelineStageDef]) -> str:
    return board_column_for(
        stage_def.name if stage_def is not None else None,
        _enum_value(stage),
        category=_enum_value(stage_def.category) if stage_def is not None else None,
        terminal_type=(
            _enum_value(stage_def.terminal_type) if stage_def is not None else None
        ),
    )


def is_closed(stage: PipelineStage, stage_def: Optional[PipelineStageDef]) -> bool:
    """Proces zamknięty — automat go nie rusza."""
    if stage in _TERMINAL_STAGES:
        return True
    if stage_def is not None and stage_def.is_terminal:
        return True
    return _column(stage, stage_def) in ("closed", "hired")


def is_before(
    *,
    stage: PipelineStage,
    stage_def: Optional[PipelineStageDef],
    target: PipelineStage,
    target_def: Optional[PipelineStageDef],
    template_id: Optional[int],
) -> bool:
    """Czy bieżący etap pary leży PRZED etapem docelowym."""
    if (
        stage_def is not None
        and target_def is not None
        and stage_def.template_id == template_id
    ):
        return stage_def.order < target_def.order
    if stage_def is not None:
        current_rank = _COLUMN_RANK.get(_column(stage, stage_def))
        target_rank = _COLUMN_RANK.get(_column(target, target_def))
        if current_rank is None or target_rank is None:
            return False
        return current_rank < target_rank
    if stage not in STAGE_ORDER or target not in STAGE_ORDER:
        return False
    return STAGE_ORDER.index(stage) < STAGE_ORDER.index(target)


async def auto_advance(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    target: PipelineStage,
    actor_user_id: Optional[int],
    source: str,
    note: str,
) -> Optional[CandidateStage]:
    """Przesuń kartę pary na ``target``, jeśli jest wcześniej w procesie.

    Zwraca nowy wiersz etapu albo ``None``, gdy nic się nie zmieniło (brak
    pary, proces zamknięty, karta już na etapie docelowym albo dalej, brak
    otwartego procesu przy zamkniętej historii).
    """
    # Ta sama kolejność blokad co `transition_process` i /pipeline/move:
    # kandydat → rekrutacja. Blokada kandydata serializuje równoległe ruchy
    # tej pary, więc odczyt najnowszego etapu niżej nie wymaga osobnej.
    locked = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if locked is None:
        return None
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        return None

    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest is None:
        return None
    latest_def = (
        await db.get(PipelineStageDef, latest.stage_def_id)
        if latest.stage_def_id is not None
        else None
    )
    if is_closed(latest.stage, latest_def):
        return None

    template_id = await _template_id(db, job)
    target_def = await _target_stage_def(db, template_id, target)
    if not is_before(
        stage=latest.stage,
        stage_def=latest_def,
        target=target,
        target_def=target_def,
        template_id=template_id,
    ):
        return None

    if target not in (PipelineStage.rejected, PipelineStage.withdrawn):
        from app.services.hiring_manager_verdicts import (  # noqa: PLC0415
            puts_candidate_before_client,
        )
        from app.services.pipeline_eligibility import (  # noqa: PLC0415
            check_candidate_move_eligibility,
        )

        block = await check_candidate_move_eligibility(
            db,
            candidate_id=candidate_id,
            job=job,
            now=datetime.now(timezone.utc),
            enforce_manager_verdict=puts_candidate_before_client(target),
            acknowledged=True,
        )
        if block is not None:
            # Ślad, dlaczego karta nie pojechała — bez treści powodu (ta bywa
            # nazwiskiem hiring managera); kod wystarcza do wyjaśnienia.
            db.add(
                Activity(
                    entity_type="pipeline",
                    entity_id=latest.id,
                    action="auto_advance_skipped",
                    user_id=actor_user_id,
                    details={
                        "candidate_id": candidate_id,
                        "job_id": job_id,
                        "stage": target.value,
                        "source": source,
                        "reason_code": block.reason_code,
                    },
                )
            )
            return None

    try:
        stage = await transition_process(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            stage=target,
            stage_def_id=target_def.id if target_def is not None else None,
            moved_at=datetime.now(timezone.utc),
            actor_user_id=actor_user_id,
            require_existing=True,
            notes=note,
        )
    except PriorityWorkLocked:
        # Automat nie zakłada nowej rekrutacji jako efektu ubocznego — brak
        # otwartego procesu zostaje do decyzji człowieka.
        logger.warning(
            "auto_advance skipped (%s): no open process for candidate %s / job %s",
            source,
            candidate_id,
            job_id,
        )
        return None

    if target in _TERMINAL_STAGES:
        await maybe_close_contact_opportunity(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            actor_user_id=actor_user_id,
            reason=f"pipeline_terminal:{target.value}",
            occurred_at=stage.moved_at,
        )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=actor_user_id,
            details={
                "candidate_id": candidate_id,
                "job_id": job_id,
                "from_stage": _enum_value(latest.stage),
                "from_stage_def_id": latest.stage_def_id,
                "stage": target.value,
                "stage_def_id": stage.stage_def_id,
                "source": source,
            },
        )
    )
    # Przepięcie do połączonych rekrutacji — jak `/move`. Własny savepoint,
    # nigdy nie rzuca.
    from app.services.job_similarity import on_candidate_sent  # noqa: PLC0415

    await on_candidate_sent(db, job_id=job_id, candidate_id=candidate_id, stage=target)
    return stage


async def run_after_commit(
    db: AsyncSession, *, stage_id: int, mover: Optional[User]
) -> None:
    """Efekty po ZATWIERDZONYM ruchu automatu — lustro bloku po commicie `/move`.

    Reguły powiadomień o etapie (0066) i profil ryzyka. Każdy efekt w swoim
    savepoincie i ze swoim commitem; nigdy nie rzuca — ruch jest już trwały.
    """
    from app.schemas.pipeline import STAGE_LABELS  # noqa: PLC0415
    from app.services.candidate_risk import compute_risk  # noqa: PLC0415
    from app.services.stage_notification_emitter import (  # noqa: PLC0415
        notify_stage_change,
    )

    try:
        stage = await db.get(CandidateStage, stage_id)
        if stage is None:
            return
        candidate_id, job_id = stage.candidate_id, stage.job_id
        previous = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
                CandidateStage.id != stage_id,
                CandidateStage.moved_at <= stage.moved_at,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        stage_def = (
            await db.get(PipelineStageDef, stage.stage_def_id)
            if stage.stage_def_id is not None
            else None
        )
        display = (
            stage_def.name
            if stage_def is not None
            else STAGE_LABELS.get(stage.stage, _enum_value(stage.stage))
        )
        job = await db.get(Job, job_id)
        candidate = await db.get(Candidate, candidate_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_advance after-commit load failed: %s", type(exc).__name__)
        return

    async def _notify() -> None:
        if job is not None and candidate is not None:
            await notify_stage_change(
                db,
                new_stage=stage,
                previous_stage=previous,
                job=job,
                candidate=candidate,
                mover=mover,
                stage_display_name=display,
            )

    async def _risk() -> None:
        # `compute_risk`, nie `on_candidate_stage_change` — tamten połyka
        # wyjątek bazy wewnątrz savepointu.
        await compute_risk(db, candidate_id)

    for label, effect in (("stage_notif", _notify), ("risk", _risk)):
        # Savepoint, nie `db.rollback()` sesji: rollback wygaszałby `stage`,
        # `job` i `candidate` dla kolejnego efektu (MissingGreenlet).
        try:
            async with db.begin_nested():
                await effect()
        except Exception as exc:  # noqa: BLE001 — efekt nie cofa ruchu
            logger.warning(
                "auto_advance %s failed for stage %s: %s",
                label,
                stage_id,
                type(exc).__name__,
            )
            continue
        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "auto_advance %s commit failed for stage %s: %s",
                label,
                stage_id,
                type(exc).__name__,
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return
