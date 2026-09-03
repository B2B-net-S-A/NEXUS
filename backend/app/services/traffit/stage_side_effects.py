"""Skutki uboczne dla etapów przychodzących z importu — wsadowo i wąsko.

Importer pisze do ``candidate_stages`` surowym ``INSERT ... ON CONFLICT``,
a nie przez warstwę komend, i tak ma zostać: ``transition_process`` robi
~10 zapytań i dwie blokady ``FOR UPDATE`` na wiersz, w kolejności blokad
*kandydat→oferta per wiersz*, podczas gdy wsadowy sync bierze *wszystkich
kandydatów → wszystkie oferty*. Przeplot tych dwóch kolejności zakleszczał się
z importem w przeszłości (komentarze w ``pipeline.py`` i
``recruitment_process_commands.py``).

Skutkiem ubocznym tej decyzji było jednak to, że KAŻDA automatyzacja pipeline'u
dotyczyła 0,4% ruchu — 131 ruchów własnych na 32 872 w 90 dniach
(``/api/admin/process-adoption``, 2026-09-02). Ten moduł domyka wybrane
skutki dla drugiej ścieżki, bez przepinania jej na komendy.

**Co WCHODZI** (idempotentne, bez efektów zewnętrznych):

* ``on_candidate_stage_change`` — przeliczenie profilu ryzyka; czysty recompute;
* ``auto_add_on_cv_sent`` — talent pool; idempotentny przez
  ``uq_pool_candidate``.

**Co ŚWIADOMIE NIE WCHODZI:**

* ``maybe_schedule`` (mail odrzucający) — jedyna z rodziny, która kończy się
  WYSYŁKĄ do kandydata. ``dispatch`` sprawdza tylko, czy bieżący etap pary to
  nadal ``rejected``; historyczne odrzucenia ten warunek PRZECHODZĄ, a
  ``scheduled_at`` liczy się od teraz. Włączenie wysłałoby maile do tysięcy
  osób odrzuconych miesiące temu.
* ``ensure_b2b_employment_draft`` (draft kontraktu przy ``hired``) — nie wysyła
  maili, ale rzuca HTTP 409 przy braku ``client_id`` i przy więcej niż jednym
  żywym kontrakcie, czyli na dwóch klasach danych historycznych. Wymaga
  własnej decyzji o tym, co zrobić z odmowami, więc nie wchodzi tu po cichu.

Wszystko jest best-effort i za commitem etapów: awaria skutku nie może cofnąć
zaimportowanego wiersza ani zatrzymać fazy.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.recruitment_pipeline import PipelineStage

logger = logging.getLogger(__name__)


async def apply_imported_stage_side_effects(
    db: AsyncSession,
    *,
    rows: Sequence[dict],
) -> dict[str, int]:
    """Odpal wąski zestaw skutków dla właśnie zaimportowanych etapów.

    ``rows`` to payloady wsadu importera (``candidate_id``, ``job_id``,
    ``stage_legacy_enum``). Zwraca licznik wykonanych skutków — do logów
    i testów, nie do sterowania przepływem.
    """

    applied = {"risk": 0, "talent_pool": 0}
    if not settings.TRAFFIT_IMPORT_SIDE_EFFECTS_ENABLED or not rows:
        return applied

    candidate_ids = sorted({int(r["candidate_id"]) for r in rows})
    cv_sent_rows = [
        r for r in rows if r.get("stage_legacy_enum") == PipelineStage.cv_sent.value
    ]

    # 1. Profil ryzyka — czysty recompute, idempotentny.
    from app.services.candidate_risk import on_candidate_stage_change

    for candidate_id in candidate_ids:
        # SAVEPOINT na wiersz, nie `db.rollback()`.
        #
        # `rollback()` cofa CAŁĄ transakcję sesji, więc jeden nieudany kandydat
        # kasowałby wszystkie wcześniejsze przeliczenia z tego wsadu — czyli
        # cicha utrata pracy proporcjonalna do rozmiaru wsadu. Ten sam wzorzec
        # stosuje importer przy fazach (`begin_nested`).
        try:
            async with db.begin_nested():
                await on_candidate_stage_change(db, candidate_id)
            applied["risk"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "import risk recompute failed cand=%s: %s", candidate_id, exc
            )

    # 2. Talent pool po wysłaniu CV — idempotentny przez unique constraint.
    if cv_sent_rows:
        from sqlalchemy import select

        from app.models.job import Job
        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        job_ids = sorted({int(r["job_id"]) for r in cv_sent_rows})
        jobs = {
            job.id: job
            for job in (
                (await db.execute(select(Job).where(Job.id.in_(job_ids))))
                .scalars()
                .all()
            )
        }
        for row in cv_sent_rows:
            job = jobs.get(int(row["job_id"]))
            if job is None:
                continue
            try:
                async with db.begin_nested():
                    await auto_add_on_cv_sent(
                        db=db,
                        candidate_id=int(row["candidate_id"]),
                        job=job,
                        user_id=row.get("moved_by"),
                        extra_activity_details={"source": "traffit_import"},
                    )
                applied["talent_pool"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "import talent-pool add failed cand=%s job=%s: %s",
                    row["candidate_id"],
                    row["job_id"],
                    exc,
                )

    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("import side-effects commit failed: %s", exc)
        await db.rollback()

    return applied


__all__ = ["apply_imported_stage_side_effects"]
