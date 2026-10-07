"""Znani zespołowi — punkty kolejności dla nocnych „Propozycji z bazy”.

Badanie 06.10.2026 (`docs/audits/2026-10-06/voyage-embeddings-research.md`):
60% osób zweryfikowanych w rekrutacjach z 2026 roku było wcześniej
zweryfikowanych w innej rekrutacji. Wektor tego nie wie. Dwa sygnały razem
podniosły właściwe osoby w top 100 z 33% do 52%:

- osoba doszła co najmniej do „Zweryfikowany” w jednej z
  ``KNOWN_PEOPLE_SIMILAR_JOBS`` najbardziej podobnych rekrutacji (wektory ofert),
  punkty = ``KNOWN_PEOPLE_POINTS_PER_SIMILAR_JOB`` × podobieństwo, za każdą;
- osoba była zweryfikowana w dowolnej innej rekrutacji w ostatnich
  ``KNOWN_PEOPLE_RECENT_DAYS`` dniach: ``KNOWN_PEOPLE_POINTS_RECENT``.

Decyzje Artura 07.10.2026: punkty zmieniają WYŁĄCZNIE kolejność (procent
dopasowania zostaje — zasada „canonical fit never folds process history”),
bez osobnej sekcji, bez limitu osób (do propozycji i tak trafia tylko ten, kto
pasuje), 90 dni, a osoba odrzucona wcześniej przez tego samego klienta nie
dostaje punktów.

W dowodach zostają same identyfikatory, etapy i daty — tytuły i klientów
rozwija odczyt (`api/job_proposals._history_sources`), jak przy przepięciach.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Etapy, które w badaniu znaczyły „zespół zweryfikował tę osobę”.
POSITIVE_STAGES: tuple[str, ...] = (
    "verified",
    "cv_sent",
    "interview",
    "client_interview",
    "acceptance",
    "negotiation",
    "onboarding",
    "hired",
)
#: Ile podobnych rekrutacji pokazujemy w powodzie (punkty liczą wszystkie).
MAX_REASONS = 3


@dataclass
class KnownPerson:
    points: float = 0.0
    similar: list[dict] = field(default_factory=list)
    recent: Optional[dict] = None

    def evidence(self) -> dict:
        out: dict = {"points": round(self.points, 1)}
        if self.similar:
            out["similar"] = sorted(self.similar, key=lambda s: -s.get("_sim", 0.0))[
                :MAX_REASONS
            ]
            for item in out["similar"]:
                item.pop("_sim", None)
        if self.recent:
            out["recent"] = self.recent
        return out


def enabled() -> bool:
    return bool(getattr(settings, "KNOWN_PEOPLE_BOOST_ENABLED", False))


def _iso(value) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


async def _similar_jobs(db: AsyncSession, job_id: int) -> dict[int, float]:
    """Najbardziej podobne rekrutacje z kimkolwiek zweryfikowanym (bez tej)."""
    from app.services.embedding_service import nearest_jobs_for_job_ids

    pool = [
        int(r)
        for r in (
            await db.execute(
                text(
                    "SELECT DISTINCT job_id FROM candidate_stages "
                    "WHERE stage::text = ANY(:pos) AND job_id <> :jid"
                ),
                {"pos": list(POSITIVE_STAGES), "jid": job_id},
            )
        ).scalars()
    ]
    if not pool:
        return {}
    nearest = await nearest_jobs_for_job_ids(
        [job_id], pool, limit=int(settings.KNOWN_PEOPLE_SIMILAR_JOBS)
    )
    if not nearest:
        return {}
    return {int(j): float(s) for j, s in nearest.get(job_id) or [] if s > 0}


async def _rejected_by_client(
    db: AsyncSession, client_id: Optional[int], candidate_ids: list[int]
) -> set[int]:
    """Osoby, które ten sam klient odrzucił (najnowszy wiersz pary).

    Odrzucenie przez klienta = ``ended_by='client'``; wiersze sprzed tej kolumny
    (``ended_by`` puste) liczą się, gdy osoba była wcześniej wysłana do klienta.
    Rezygnacja kandydata i odrzucenie przez nas się nie liczą.
    """
    if client_id is None or not candidate_ids:
        return set()
    rows = await db.execute(
        text(
            """
            WITH last AS (
              SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
                     cs.candidate_id, cs.job_id, cs.stage::text AS stage, cs.ended_by
              FROM candidate_stages cs
              JOIN jobs j ON j.id = cs.job_id
              WHERE j.client_id = :client AND cs.candidate_id = ANY(:ids)
              ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
            )
            SELECT DISTINCT l.candidate_id FROM last l
            WHERE l.stage = 'rejected'
              AND (l.ended_by = 'client'
                   OR (l.ended_by IS NULL AND EXISTS (
                         SELECT 1 FROM candidate_stages s2
                         WHERE s2.candidate_id = l.candidate_id AND s2.job_id = l.job_id
                           AND s2.stage::text IN ('cv_sent','client_interview',
                                                  'acceptance','negotiation'))))
            """
        ),
        {"client": client_id, "ids": candidate_ids},
    )
    return {int(r) for r in rows.scalars()}


async def known_people_for_job(
    db: AsyncSession, job, *, now: Optional[datetime] = None
) -> dict[int, KnownPerson]:
    """``{candidate_id: KnownPerson}`` dla rekrutacji. Pusty przy wyłączonej fladze.

    Nigdy nie rzuca: brak sygnału znaczy kolejność jak dotąd, a nie brak
    propozycji.
    """
    if not enabled() or job is None:
        return {}
    try:
        return await _compute(db, job, now=now or datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 — kolejność, nie warunek publikacji
        logger.exception(
            "[known_people] signal failed job=%s", getattr(job, "id", None)
        )
        return {}


async def _compute(db: AsyncSession, job, *, now: datetime) -> dict[int, KnownPerson]:
    out: dict[int, KnownPerson] = {}
    per_job = float(settings.KNOWN_PEOPLE_POINTS_PER_SIMILAR_JOB)
    recent_points = float(settings.KNOWN_PEOPLE_POINTS_RECENT)

    sims = await _similar_jobs(db, int(job.id))
    if sims:
        rows = await db.execute(
            text(
                """
                SELECT candidate_id, job_id, max(moved_at) AS at,
                       (array_agg(stage::text ORDER BY moved_at DESC))[1] AS stage
                FROM candidate_stages
                WHERE job_id = ANY(:jobs) AND stage::text = ANY(:pos)
                GROUP BY candidate_id, job_id
                """
            ),
            {"jobs": list(sims), "pos": list(POSITIVE_STAGES)},
        )
        for cid, jid, at, stage in rows.all():
            person = out.setdefault(int(cid), KnownPerson())
            sim = sims.get(int(jid), 0.0)
            person.points += per_job * sim
            person.similar.append(
                {"job_id": int(jid), "stage": stage, "at": _iso(at), "_sim": sim}
            )

    since = now - timedelta(days=int(settings.KNOWN_PEOPLE_RECENT_DAYS))
    rows = await db.execute(
        text(
            """
            SELECT DISTINCT ON (candidate_id) candidate_id, job_id, stage::text, moved_at
            FROM candidate_stages
            WHERE stage::text = ANY(:pos) AND moved_at >= :since AND job_id <> :jid
            ORDER BY candidate_id, moved_at DESC
            """
        ),
        {"pos": list(POSITIVE_STAGES), "since": since, "jid": int(job.id)},
    )
    for cid, jid, stage, at in rows.all():
        person = out.setdefault(int(cid), KnownPerson())
        person.points += recent_points
        person.recent = {"job_id": int(jid), "stage": stage, "at": _iso(at)}

    for cid in await _rejected_by_client(
        db, getattr(job, "client_id", None), list(out)
    ):
        out.pop(cid, None)
    return out
