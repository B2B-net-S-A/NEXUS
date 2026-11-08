"""Odpowiedź klienta i pierwsze CV po otwarciu rekrutacji (audyt 2, 08.11.2026).

Na ścieżce 66 zatrudnionych od karty do CV mija ok. 1 dzień, a od CV do
zatrudnienia 22,7 dnia, więc pulpit HoR i DL ma pokazywać też stronę klienta.
Dwie miary, obie w dniach roboczych kalendarza firmy (`WorkCalendar`:
Pon–Pt bez polskich świąt i dni wolnych firmy):

* **Odpowiedź klienta w 7 dni** — % CV, przy których w 7 dniach roboczych
  zapisano rozmowę u klienta, akceptację, zatrudnienie albo odrzucenie przez
  klienta. Liczy pierwszą wysyłkę pary. Odrzucenie przez rekrutera lub Delivery
  Leada nie jest odpowiedzią klienta, tak samo pusty `ended_by`
  (`known_people_signal`: pusty wpis po wysyłce to nie odrzucenie). Mianownik
  to CV, którym minęło już całe 7 dni, inaczej świeże wysyłki zaniżałyby wynik.
  Rekrutacje masowe (`MASS_REQUEST_MIN_CV` CV od początku okna, także jeszcze
  niedojrzałych) odpadają, bo jedna z nich (128 CV od 12.10.2026) przesuwała
  procent całej firmy.
* **Pierwsze CV po otwarciu** — mediana od otwarcia rekrutacji do jej pierwszego
  `cv_sent`. Start to `opened_at`, a przy jego braku `created_at` (159 ze 182
  ręcznych rekrutacji nie ma `opened_at`). Rekrutacje z importu Traffita
  odpadają: ich `created_at` to chwila importu, a karty często są starsze.
  Wysyłka sprzed startu (kopia rekrutacji, ponowne otwarcie) się nie liczy.

„Brak odpowiedzi” znaczy brak odpowiedzi zapisanej w NEXUSIE. Odrzucenia
mailem, których nikt nie odnotował, wyglądają jak milczenie klienta.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_set, cache_single_flight
from app.core.scheduling import business_date, business_today
from app.schemas.dashboard_v2 import (
    ClientResponseBoard,
    ClientResponseClientRow,
    ClientResponseSummary,
    FirstCvSummary,
    FirstCvWeek,
)
from app.services.competition_history import RESULTS_CUTOVER, cutover_utc
from app.services.hr.calendar import WorkCalendar, load_calendar
from app.services.insights_in_flight import _pairs_now
from app.services.insights_stage_breakdown import _load_def_map

RESPONSE_WORKDAYS = 7
# Cel Artura z 08.11.2026 na 6 tygodni (punkt wyjścia: baseline w pamięci projektu).
RESPONSE_TARGET_PCT = 40
RESPONSE_WINDOW_DAYS = 28
# Największa zwykła rekrutacja miała od 12.10.2026 17 CV, masowa 128.
MASS_REQUEST_MIN_CV = 30
# Poniżej tylu CV procent klienta nie decyduje o kolejności tabeli.
MIN_CLIENT_SAMPLE = 5

FIRST_CV_WINDOW_DAYS = 56
FIRST_CV_SLA_WORKDAYS = 5
FIRST_CV_TREND_WEEKS = 8

CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class SentCv:
    client_id: int
    client_name: str
    job_id: int
    sent_on: date
    responded_on: Optional[date]
    # Ile CV rekrutacja wysłała od początku okna, także jeszcze niedojrzałych.
    job_cv_count: int = 1


@dataclass(frozen=True)
class WaitingCv:
    client_id: int
    client_name: str
    entered_on: date


@dataclass(frozen=True)
class OpenedJob:
    job_id: int
    opened_on: date
    first_moved_on: Optional[date]
    first_verified_on: Optional[date]
    first_cv_on: Optional[date]


def workdays_after(calendar: WorkCalendar, start: date, end: date) -> int:
    """Dni robocze w przedziale (start, end]. Ta sama data daje 0."""

    if end <= start:
        return 0
    return len(calendar.working_days(start + timedelta(days=1), end))


def response_window(calendar: WorkCalendar, today: date) -> tuple[date, date]:
    """Daty wysyłki CV, którym minęło już całe 7 dni roboczych na odpowiedź."""

    end = today
    while workdays_after(calendar, end, today) < RESPONSE_WORKDAYS:
        end -= timedelta(days=1)
    start = end - timedelta(days=RESPONSE_WINDOW_DAYS - 1)
    # Przed 12.10.2026 etapów klienta nikt nie prowadził w NEXUSIE.
    return max(start, RESULTS_CUTOVER), end


def _pct(part: int, whole: int) -> Optional[float]:
    return round(100 * part / whole, 1) if whole else None


def responded_in_time(calendar: WorkCalendar, cv: SentCv) -> bool:
    if cv.responded_on is None:
        return False
    return workdays_after(calendar, cv.sent_on, cv.responded_on) <= RESPONSE_WORKDAYS


def _client_rows(
    kept: Sequence[SentCv],
    waiting: Sequence[WaitingCv],
    calendar: WorkCalendar,
    today: date,
) -> list[ClientResponseClientRow]:
    names: dict[int, str] = {}
    cohort: Counter[int] = Counter()
    responded: Counter[int] = Counter()
    for cv in kept:
        names[cv.client_id] = cv.client_name
        cohort[cv.client_id] += 1
        if responded_in_time(calendar, cv):
            responded[cv.client_id] += 1

    in_progress: Counter[int] = Counter()
    oldest: dict[int, date] = {}
    for item in waiting:
        names[item.client_id] = item.client_name
        in_progress[item.client_id] += 1
        known = oldest.get(item.client_id)
        if known is None or item.entered_on < known:
            oldest[item.client_id] = item.entered_on

    rows = [
        ClientResponseClientRow(
            client_id=client_id,
            client_name=name,
            cv_in_progress=in_progress[client_id],
            cohort_cv=cohort[client_id],
            responded_7d=responded[client_id],
            response_7d_pct=_pct(responded[client_id], cohort[client_id]),
            oldest_waiting_workdays=(
                workdays_after(calendar, oldest[client_id], today)
                if client_id in oldest
                else None
            ),
        )
        for client_id, name in names.items()
    ]
    # Najpierw klienci, którzy odpowiadają najrzadziej. Procent z 1–2 CV nie
    # wypycha na górę kogoś, kto dostał jedno CV.
    rows.sort(
        key=lambda row: (
            row.cohort_cv < MIN_CLIENT_SAMPLE,
            row.response_7d_pct if row.response_7d_pct is not None else 101.0,
            -row.cv_in_progress,
            row.client_name.casefold(),
        )
    )
    return rows


def summarize_responses(
    sent: Iterable[SentCv],
    waiting: Iterable[WaitingCv],
    calendar: WorkCalendar,
    today: date,
) -> ClientResponseSummary:
    window_from, window_to = response_window(calendar, today)
    in_window = [cv for cv in sent if window_from <= cv.sent_on <= window_to]
    mass = [cv for cv in in_window if cv.job_cv_count >= MASS_REQUEST_MIN_CV]
    kept = [cv for cv in in_window if cv.job_cv_count < MASS_REQUEST_MIN_CV]
    responded = sum(1 for cv in kept if responded_in_time(calendar, cv))
    waiting_list = list(waiting)
    return ClientResponseSummary(
        window_from=window_from,
        window_to=window_to,
        cohort_cv=len(kept),
        responded_7d=responded,
        response_7d_pct=_pct(responded, len(kept)),
        target_pct=RESPONSE_TARGET_PCT,
        workdays=RESPONSE_WORKDAYS,
        excluded_mass_jobs=len({cv.job_id for cv in mass}),
        excluded_mass_cv=len(mass),
        cv_in_progress=len(waiting_list),
        clients=_client_rows(kept, waiting_list, calendar, today),
    )


def _median_days(
    calendar: WorkCalendar,
    jobs: Iterable[OpenedJob],
    reached: str,
) -> Optional[float]:
    days = [
        workdays_after(calendar, job.opened_on, getattr(job, reached))
        for job in jobs
        if getattr(job, reached) is not None
    ]
    return float(statistics.median(days)) if days else None


def _sla_counts(
    calendar: WorkCalendar,
    jobs: Iterable[OpenedJob],
    today: date,
) -> tuple[int, int]:
    """(rekrutacje, którym minęło 5 dni rob.; z nich z CV w tym czasie)."""

    eligible = [
        job
        for job in jobs
        if workdays_after(calendar, job.opened_on, today) >= FIRST_CV_SLA_WORKDAYS
    ]
    within = sum(
        1
        for job in eligible
        if job.first_cv_on is not None
        and workdays_after(calendar, job.opened_on, job.first_cv_on)
        <= FIRST_CV_SLA_WORKDAYS
    )
    return len(eligible), within


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def first_cv_window_start(today: date) -> date:
    """Początek okna: 8 tygodni wstecz, ale nie przed 12.10.2026.

    Przed tą datą rekruterzy nie prowadzili etapów w NEXUSIE, więc rekrutacje
    z września wyglądałyby jak otwarte bez CV.
    """

    return max(today - timedelta(days=FIRST_CV_WINDOW_DAYS), RESULTS_CUTOVER)


def _first_cv_weeks(
    calendar: WorkCalendar,
    jobs: Sequence[OpenedJob],
    today: date,
    window_from: date,
) -> list[FirstCvWeek]:
    # Trwający tydzień nie idzie na linię: kilka dni wygląda jak załamanie.
    current = _monday(today)
    weeks: list[FirstCvWeek] = []
    for back in range(FIRST_CV_TREND_WEEKS, 0, -1):
        week_start = current - timedelta(weeks=back)
        if week_start < _monday(window_from):
            continue
        in_week = [job for job in jobs if _monday(job.opened_on) == week_start]
        eligible, within = _sla_counts(calendar, in_week, today)
        weeks.append(
            FirstCvWeek(
                week_start=week_start,
                opened_jobs=len(in_week),
                sla_eligible_jobs=eligible,
                sla_within_jobs=within,
                sla_pct=_pct(within, eligible),
                median_first_cv_workdays=_median_days(calendar, in_week, "first_cv_on"),
            )
        )
    return weeks


def summarize_first_cv(
    jobs: Iterable[OpenedJob],
    calendar: WorkCalendar,
    today: date,
) -> FirstCvSummary:
    window_from = first_cv_window_start(today)
    opened = [job for job in jobs if job.opened_on >= window_from]
    eligible, within = _sla_counts(calendar, opened, today)
    with_cv = sum(1 for job in opened if job.first_cv_on is not None)
    return FirstCvSummary(
        window_from=window_from,
        window_to=today,
        opened_jobs=len(opened),
        jobs_with_cv=with_cv,
        jobs_without_cv=len(opened) - with_cv,
        median_first_moved_workdays=_median_days(calendar, opened, "first_moved_on"),
        median_first_verified_workdays=_median_days(
            calendar, opened, "first_verified_on"
        ),
        median_first_cv_workdays=_median_days(calendar, opened, "first_cv_on"),
        sla_workdays=FIRST_CV_SLA_WORKDAYS,
        sla_eligible_jobs=eligible,
        sla_within_jobs=within,
        sla_pct=_pct(within, eligible),
        weeks=_first_cv_weeks(calendar, opened, today, window_from),
    )


_LISTED_CLIENT_SQL = """
    JOIN clients c ON c.id = j.client_id
                  AND c.hidden IS FALSE
                  AND c.deleted_at IS NULL
"""
_CLIENT_SCOPE_SQL = (
    "(CAST(:client_ids AS integer[]) IS NULL "
    "OR j.client_id = ANY(CAST(:client_ids AS integer[])))"
)


async def _load_sent_cvs(
    db: AsyncSession,
    window_from: date,
    window_to: date,
    client_ids: Optional[Sequence[int]],
) -> list[SentCv]:
    rows = (
        await db.execute(
            text(
                f"""
                WITH cv AS (
                  SELECT cs.candidate_id, cs.job_id, min(cs.moved_at) AS sent_at
                  FROM candidate_stages cs
                  WHERE cs.stage::text = 'cv_sent'
                  GROUP BY cs.candidate_id, cs.job_id
                ),
                sized AS (
                  SELECT cv.*,
                         (cv.sent_at AT TIME ZONE 'Europe/Warsaw')::date AS sent_on,
                         count(*) FILTER (
                           WHERE (cv.sent_at AT TIME ZONE 'Europe/Warsaw')::date
                                 >= :window_from
                         ) OVER (PARTITION BY cv.job_id) AS job_cv_count
                  FROM cv
                )
                SELECT j.client_id, c.name AS client_name, cv.job_id,
                       cv.sent_on, cv.job_cv_count,
                       (
                         SELECT (min(s.moved_at) AT TIME ZONE 'Europe/Warsaw')::date
                         FROM candidate_stages s
                         WHERE s.candidate_id = cv.candidate_id
                           AND s.job_id = cv.job_id
                           AND s.moved_at > cv.sent_at
                           AND (
                             s.stage::text IN ('client_interview', 'acceptance', 'hired')
                             OR (s.stage::text = 'rejected' AND s.ended_by = 'client')
                           )
                       ) AS responded_on
                FROM sized cv
                JOIN jobs j ON j.id = cv.job_id
                {_LISTED_CLIENT_SQL}
                WHERE cv.sent_on BETWEEN :window_from AND :window_to
                  AND {_CLIENT_SCOPE_SQL}
                """
            ),
            {
                "window_from": window_from,
                "window_to": window_to,
                "client_ids": list(client_ids) if client_ids is not None else None,
            },
        )
    ).all()
    return [
        SentCv(
            client_id=int(row.client_id),
            client_name=row.client_name,
            job_id=int(row.job_id),
            sent_on=row.sent_on,
            responded_on=row.responded_on,
            job_cv_count=int(row.job_cv_count),
        )
        for row in rows
    ]


async def _load_waiting_cvs(
    db: AsyncSession,
    client_ids: Optional[Sequence[int]],
) -> list[WaitingCv]:
    """Pary w kolumnie „Wysłane do klienta”: ta sama reguła co „W drodze”."""

    def_ids, def_keys = await _load_def_map(db)
    pairs = await _pairs_now(
        db,
        {
            "def_ids": def_ids,
            "def_keys": def_keys,
            "job_ids": None,
            "since": cutover_utc(),
            "owner_kind": None,
            "owner_id": None,
        },
    )
    allowed = set(client_ids) if client_ids is not None else None
    listed = {
        int(row.id)
        for row in (
            await db.execute(
                text(
                    "SELECT id FROM clients WHERE hidden IS FALSE AND deleted_at IS NULL"
                )
            )
        ).all()
    }
    waiting: list[WaitingCv] = []
    for pair in pairs:
        client_id = pair["client_id"]
        if pair["col"] != "cv_sent" or client_id not in listed:
            continue
        if allowed is not None and client_id not in allowed:
            continue
        waiting.append(
            WaitingCv(
                client_id=int(client_id),
                client_name=pair["client_name"],
                entered_on=business_date(pair["entered_at"]),
            )
        )
    return waiting


async def _load_opened_jobs(
    db: AsyncSession,
    window_from: date,
    client_ids: Optional[Sequence[int]],
) -> list[OpenedJob]:
    rows = (
        await db.execute(
            text(
                f"""
                SELECT j.id,
                       (COALESCE(j.opened_at, j.created_at)
                        AT TIME ZONE 'Europe/Warsaw')::date AS opened_on,
                       x.first_moved_on, x.first_verified_on, x.first_cv_on
                FROM jobs j
                {_LISTED_CLIENT_SQL}
                LEFT JOIN LATERAL (
                  SELECT
                    (min(cs.moved_at) FILTER (WHERE cs.stage::text <> 'new')
                       AT TIME ZONE 'Europe/Warsaw')::date AS first_moved_on,
                    (min(cs.moved_at) FILTER (WHERE cs.stage::text = 'verified')
                       AT TIME ZONE 'Europe/Warsaw')::date AS first_verified_on,
                    (min(cs.moved_at) FILTER (WHERE cs.stage::text = 'cv_sent')
                       AT TIME ZONE 'Europe/Warsaw')::date AS first_cv_on
                  FROM candidate_stages cs
                  WHERE cs.job_id = j.id
                    AND cs.moved_at >= GREATEST(
                          j.created_at, COALESCE(j.opened_at, j.created_at)
                        )
                ) x ON TRUE
                WHERE COALESCE(j.external_source, 'manual') <> 'traffit'
                  AND j.status::text <> 'draft'
                  AND (COALESCE(j.opened_at, j.created_at)
                       AT TIME ZONE 'Europe/Warsaw')::date >= :window_from
                  AND {_CLIENT_SCOPE_SQL}
                """
            ),
            {
                "window_from": window_from,
                "client_ids": list(client_ids) if client_ids is not None else None,
            },
        )
    ).all()
    return [
        OpenedJob(
            job_id=int(row.id),
            opened_on=row.opened_on,
            first_moved_on=row.first_moved_on,
            first_verified_on=row.first_verified_on,
            first_cv_on=row.first_cv_on,
        )
        for row in rows
    ]


async def compute_first_cv(
    db: AsyncSession,
    today: date,
    client_ids: Optional[Sequence[int]] = None,
) -> FirstCvSummary:
    window_from = first_cv_window_start(today)
    jobs = await _load_opened_jobs(db, window_from, client_ids)
    calendar = await load_calendar(db, window_from, today)
    return summarize_first_cv(jobs, calendar, today)


async def compute_client_response_board(
    db: AsyncSession,
    today: date,
    client_ids: Optional[Sequence[int]] = None,
) -> ClientResponseBoard:
    """Kafelki i tabela per klient. `client_ids=None` = cała firma."""

    # Okno kohorty zależy tylko od weekendów i świąt przy 7 dniach roboczych;
    # dni wolne firmy z ostatnich 2 miesięcy wczytuje wstępny kalendarz.
    base = await load_calendar(db, today - timedelta(days=60), today)
    window_from, window_to = response_window(base, today)
    sent = await _load_sent_cvs(db, window_from, window_to, client_ids)
    waiting = await _load_waiting_cvs(db, client_ids)
    oldest = min(
        (item.entered_on for item in waiting),
        default=window_from,
    )
    calendar = await load_calendar(db, min(oldest, window_from), today)
    return ClientResponseBoard(
        response=summarize_responses(sent, waiting, calendar, today),
        first_cv=await compute_first_cv(db, today, client_ids),
    )


async def cached_client_response_board(
    db: AsyncSession,
    client_ids: Optional[Sequence[int]] = None,
) -> ClientResponseBoard:
    today = business_today()
    scope_key = (
        "all" if client_ids is None else ",".join(str(c) for c in sorted(client_ids))
    )
    cache_key = f"client-response:v1:{today.isoformat()}:{scope_key}"
    async with cache_single_flight(cache_key, db=db):
        cached = await cache_get(cache_key)
        if cached is not None:
            return ClientResponseBoard.model_validate(cached)
        board = await compute_client_response_board(db, today, client_ids)
        await cache_set(
            cache_key, board.model_dump(mode="json"), ttl_seconds=CACHE_TTL_SECONDS
        )
        return board
