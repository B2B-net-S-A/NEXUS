"""Ilu kandydatów obsadzono na rekrutacji — jedna definicja.

Repo liczyło to na trzy sposoby, dające różne liczby:

* `insights_delivery_leads` — z widoku `analytics_first_milestones`
  (pierwsze `hired` per para; kanonicznie);
* `reports.py` — `count(candidate_stages.id)` po WSZYSTKICH wierszach `hired`,
  więc kandydat z powtórzonym etapem liczył się dwa razy;
* `reports.py` (fill rate) — suma `headcount` zamkniętych rekrutacji.

Kanoniczna jest pierwsza: placement to PIERWSZE wejście pary (kandydat,
rekrutacja) na „Zatrudniony" (`FIRST_HIRED_PER_CANDIDATE_JOB`). Ta sama
definicja stoi za `/insights` i banerem kampanii.

Obsada rekrutacji (05.11.2026) to coś innego niż placementy w statystykach:
osoby zatrudnione w BIEŻĄCYM otwarciu (`job_opening`). Po „Otwórz ponownie”
zatrudnienie sprzed otwarcia nie zajmuje wakatu, a osoba z poprzedniego
otwarcia zatrudniona jeszcze raz zajmuje go, choć drugiego placementu nie
daje. Bez otwarcia ponownego obie liczby są równe.

Moduł NIE zmienia stanu rekrutacji ani kandydata. Zamknięcie oferty zostaje
świadomą decyzją człowieka (`POST /api/jobs/{job_id}/close`) — 99,6% ruchu
w pipelinie pochodzi z importu, więc automat działałby retroaktywnie na
tysiącach rekordów, o które nikt nie prosił.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.job_opening import in_opening_sql
from app.services.placement_exclusions import excluded_pair_exists_sql

if TYPE_CHECKING:
    from app.models.job import Job

logger = logging.getLogger(__name__)


def filled_in_opening_sql(job_ids_sql: str) -> str:
    """``(job_id, cnt)`` — osoby zatrudnione w bieżącym otwarciu rekrutacji.

    ``job_ids_sql`` to podzapytanie z identyfikatorami rekrutacji. Bez
    wykluczonych placementów (0343): seria bez CV nie zajmuje wakatu.
    """

    return f"""
        SELECT cs.job_id, count(DISTINCT cs.candidate_id) AS cnt
        FROM candidate_stages cs
        JOIN jobs oj ON oj.id = cs.job_id
        WHERE cs.stage = 'hired'
          AND cs.job_id IN ({job_ids_sql})
          AND {in_opening_sql("oj", "cs.moved_at")}
          AND NOT {excluded_pair_exists_sql("cs")}
        GROUP BY cs.job_id
    """


_FILLED_SQL = text(filled_in_opening_sql("SELECT unnest(CAST(:job_ids AS integer[]))"))


async def filled_by_job(db: AsyncSession, job_ids: Sequence[int]) -> dict[int, int]:
    """Obsada per rekrutacja — osoby zatrudnione w bieżącym otwarciu."""

    if not job_ids:
        return {}
    rows = await db.execute(_FILLED_SQL, {"job_ids": list(job_ids)})
    return {int(job_id): int(cnt) for job_id, cnt in rows.all()}


def open_vacancies(headcount: int | None, placements: int) -> int:
    """Ile wakatów zostało. Nigdy ujemnie — nadmiar obsady to nie „minus etat"."""

    return max(int(headcount or 1) - placements, 0)


def is_fully_staffed(headcount: int | None, placements: int) -> bool:
    return open_vacancies(headcount, placements) == 0


async def suggest_closing_when_fully_staffed(db: AsyncSession, job: "Job") -> int:
    """Obsada kompletna → PODPOWIEDŹ zamknięcia rekrutacji, nie automat.

    Zatrudnienie nie zmieniało dotąd stanu rekrutacji: `headcount` nie był
    dekrementowany, a `close_reason = filled_by_us` nie był ustawiany nigdzie
    w kodzie pipeline'u — stąd 315 rekrutacji zamkniętych w 90 dni BEZ powodu
    i raport wygranych/przegranych bez czego liczyć wygranej.

    Automatu tu nie ma świadomie (decyzja właściciela 2026-09-03): 99,6% ruchu
    pochodzi z importu, więc automatyczne domykanie działałoby retroaktywnie na
    tysiącach rekrutacji, o które nikt nie prosił. Powiadomienie prowadzi do
    ISTNIEJĄCEGO `POST /api/jobs/{job_id}/close`, który zapisuje powód
    i loguje `Activity`.

    Wołają: `/pipeline/move` (w transakcji ruchu) i potwierdzenie podpisu B2B
    (po commicie — audyt 05.10.2026: zatrudnienie z podpisu nie dawało tej
    podpowiedzi). Savepoint i fail-soft: nigdy nie rzuca, nie cofa
    zatrudnienia. Zwraca liczbę wysłanych podpowiedzi. Wołający commituje.
    """
    from app.models.job import JobStatus  # noqa: PLC0415
    from app.models.notification import Notification, NotificationType  # noqa: PLC0415

    job_id = None
    try:
        job_id = job.id
        async with db.begin_nested():
            # Skrót: właśnie kogoś zatrudniliśmy, więc obsada >= 1. Przy
            # `headcount = 1` (default) wiemy to bez pytania widoku
            # `analytics_first_milestones` — a to gorąca ścieżka `/move`.
            headcount = int(job.headcount or 1)
            filled = (
                1
                if headcount <= 1
                else (await filled_by_job(db, [job_id])).get(job_id, 0)
            )
            if (
                not is_fully_staffed(headcount, filled)
                or job.status == JobStatus.closed
            ):
                return 0
            # Bez dedupu KAŻDE kolejne zatrudnienie na tej rekrutacji
            # rozsyłałoby ten sam komunikat do całego zespołu. Podpowiedź ma
            # być jedna — powtórka niczego nie doda, a nauczy ignorować
            # powiadomienia. Jedna na otwarcie: po „Otwórz ponownie” komplet
            # nowej obsady znów zasługuje na podpowiedź (05.11.2026).
            hinted = select(Notification.id).where(
                Notification.related_entity_type == "job",
                Notification.related_entity_id == job_id,
                Notification.notification_type == NotificationType.suggest_next_step,
            )
            if job.cycle_started_at is not None:
                hinted = hinted.where(Notification.created_at >= job.cycle_started_at)
            already_hinted = await db.scalar(hinted.limit(1))
            if already_hinted is not None:
                return 0
            # Odbiorcy = zespół TEJ rekrutacji (właściciel, DL, TAC,
            # współpracownicy) + admini z `list_job_member_ids`, nie każdy
            # DL/TAC w firmie — podpowiedź o cudzej rekrutacji uczyła
            # ignorować powiadomienia.
            from app.services.job_membership import (  # noqa: PLC0415
                list_job_member_ids,
            )
            from app.services.notification_triggers import emit  # noqa: PLC0415

            # Uczestnicy z kategorii nie dostają dzwonków rekrutacji (D7),
            # „Poprzedni rekruterzy” też nie (14.10.2026).
            recipient_ids = await list_job_member_ids(
                db, job_id, include_category_participants=False, include_parked=False
            )
            title = f"Rekrutacja '{job.title}' ma komplet obsady"
            message = (
                f"Obsadzono {filled} z {job.headcount or 1} "
                "etatów. Jeśli to koniec — zamknij rekrutację "
                "z powodem „Obsadzone przez nas”, żeby raport "
                "wygranych i przegranych miał z czego liczyć."
            )
            sent = 0
            # `emit` zapisuje w savepoincie. `ix_notif_dedup_daily` nie zna
            # typu encji, więc powiadomienie o KANDYDACIE #N z tego dnia
            # blokowało podpowiedź dla REKRUTACJI #N — a `db.add` bez flush
            # wywracał dopiero commit zatrudnienia (500 na /move).
            for uid in recipient_ids:
                notif = await emit(
                    db,
                    user_id=uid,
                    title=title,
                    message=message,
                    ntype=NotificationType.suggest_next_step,
                    related_entity_type="job",
                    related_entity_id=job_id,
                    link=f"/jobs/{job_id}",
                )
                if notif is not None:
                    sent += 1
            return sent
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — podpowiedź nie wywraca zatrudnienia
        logger.warning(
            "fully-staffed hint failed for job=%s (%s)", job_id, type(exc).__name__
        )
        return 0


__all__ = [
    "filled_by_job",
    "filled_in_opening_sql",
    "is_fully_staffed",
    "open_vacancies",
    "suggest_closing_when_fully_staffed",
]
