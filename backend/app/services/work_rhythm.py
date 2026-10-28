"""Rytm dnia i intensywność pracy rekruterów (decyzje Artura 28.10.2026).

Insights → „Rytm dnia”: kiedy i jak intensywnie rekruterzy pracują w NEXUSIE,
godzina po godzinie. Widzą to tylko Head of Recruitment i admin (29.10.2026);
pokazujemy tylko rekruterów i TCM (bez Delivery Leadów, Head of Recruitment
i adminów), bez formy współpracy.
Liczymy od 12.10.2026 — od tego dnia zespół pracuje w NEXUSIE.

* **Punkty pracy** — każda akcja osoby ma wagę swojego rodzaju (``KINDS``).
  Screening waży najwięcej, bo za notatką stoi rozmowa; klikanie kart mało,
  żeby nie opłacało się „nabijać”. Importy, automaty i autozapisy nie liczą się.
* **Poziom godziny** — suma punktów w godzinie wobec progów ``hour_levels``.
* **Godzina pracy** — co najmniej ``work_hour_min_points`` albo spotkanie
  w kalendarzu M365 trwające ≥ 30 min w tej godzinie; liczona 8:00–18:00.
* **Intensywność dnia (0–100)** — ½ × godziny pracy / norma godzin + ½ ×
  punkty dnia / norma punktów, każda część najwyżej 1. Pół dnia urlopu
  obniża obie normy o połowę, cały dzień urlopu nie liczy się wcale.
* **Podpowiedź dla lidera** — intensywność okresu zestawiona z CV do klienta
  (zasługa jak w celach, z migawki ``credited``) wobec mediany zespołu.

Wagi i progi edytują Head of Recruitment i admin; trzymamy je w
``app_settings['work_rhythm_rules']`` (brak wpisu = ``DEFAULT_RULES``).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ, local_day_start_utc
from app.models.app_setting import AppSetting
from app.models.oauth_client import OAuthClient
from app.models.user import User, UserRole
from app.services.credited_snapshot import CREDITED_FROM_SNAPSHOT_CTE, credited_bind
from app.services.person_workdays import absence_by_user, business_days

RULES_KEY = "work_rhythm_rules"
RHYTHM_START = date(2026, 10, 12)
MAX_WINDOW_DAYS = 31

HOURS: tuple[int, ...] = tuple(range(7, 20))
WORK_HOURS: frozenset[int] = frozenset(range(8, 18))

# Rodzaje akcji — klucze wag w ustawieniach (kolejność = kolejność na ekranie).
KINDS: tuple[str, ...] = ("screening", "client_step", "cv", "note", "action", "view")

DEFAULT_RULES: dict[str, Any] = {
    "weights": {
        "screening": 5,
        "client_step": 3,
        "cv": 3,
        "note": 2,
        "action": 1,
        "view": 0.5,
    },
    # Progi poziomów godziny = kwartyle zespołu od 12.10 (P25 3,5 · P50 11 · P75 25).
    "hour_levels": [4, 11, 25],
    "work_hour_min_points": 4,
    "norm_work_hours": 7,
    "norm_day_points": 120,
    "level_high": 75,
    "level_mid": 50,
    "diag_intensity": 60,
    "diag_results_pct": 80,
}

# Kto jest w Rytmie dnia: rekruter albo TCM, ale nie lider.
_INCLUDED_ROLES = (UserRole.recruiter, UserRole.talent_community_manager)
_EXCLUDED_ROLES = (UserRole.delivery_lead, UserRole.head_of_recruitment, UserRole.admin)
# Na razie całą zakładkę widzą tylko Head of Recruitment i admin (decyzja
# Artura 29.10.2026, po wcześniejszym „widzi cały zespół”); oni też zmieniają reguły.
VIEWER_ROLES = (UserRole.admin, UserRole.head_of_recruitment)
RULES_EDITOR_ROLES = VIEWER_ROLES


@dataclass(frozen=True)
class Rules:
    weights: Mapping[str, float]
    hour_levels: tuple[float, float, float]
    work_hour_min_points: float
    norm_work_hours: float
    norm_day_points: float
    level_high: int
    level_mid: int
    diag_intensity: int
    diag_results_pct: int

    def as_json(self) -> dict[str, Any]:
        return {
            "weights": {k: self.weights[k] for k in KINDS},
            "hour_levels": list(self.hour_levels),
            "work_hour_min_points": self.work_hour_min_points,
            "norm_work_hours": self.norm_work_hours,
            "norm_day_points": self.norm_day_points,
            "level_high": self.level_high,
            "level_mid": self.level_mid,
            "diag_intensity": self.diag_intensity,
            "diag_results_pct": self.diag_results_pct,
        }


def rules_from_json(raw: Mapping[str, Any] | None) -> Rules:
    """Reguły z zapisu; brakujące pola biorą wartość domyślną."""
    data = {**DEFAULT_RULES, **(raw or {})}
    weights = {**DEFAULT_RULES["weights"], **(data.get("weights") or {})}
    levels = tuple(float(v) for v in data["hour_levels"])
    return Rules(
        weights={k: float(weights[k]) for k in KINDS},
        hour_levels=(levels[0], levels[1], levels[2]),
        work_hour_min_points=float(data["work_hour_min_points"]),
        norm_work_hours=float(data["norm_work_hours"]),
        norm_day_points=float(data["norm_day_points"]),
        level_high=int(data["level_high"]),
        level_mid=int(data["level_mid"]),
        diag_intensity=int(data["diag_intensity"]),
        diag_results_pct=int(data["diag_results_pct"]),
    )


async def load_rules(db: AsyncSession) -> Rules:
    row = await db.get(AppSetting, RULES_KEY)
    return rules_from_json(row.value if row else None)


async def save_rules(db: AsyncSession, rules: Rules, user_id: int) -> Rules:
    row = await db.get(AppSetting, RULES_KEY)
    if row is None:
        db.add(AppSetting(key=RULES_KEY, value=rules.as_json(), updated_by=user_id))
    else:
        row.value = rules.as_json()
        row.updated_by = user_id
    await db.commit()
    return rules


# ── Czyste reguły ───────────────────────────────────────────────────────────


def hour_points(counts: Mapping[str, int], rules: Rules) -> float:
    """Punkty godziny z liczby akcji każdego rodzaju."""
    return sum(rules.weights.get(kind, 0.0) * n for kind, n in counts.items())


def hour_level(points: float, rules: Rules) -> int:
    """0 brak · 1 lekka · 2 robocza · 3 intensywna · 4 bardzo intensywna."""
    if points <= 0:
        return 0
    low, mid, high = rules.hour_levels
    if points < low:
        return 1
    if points < mid:
        return 2
    if points < high:
        return 3
    return 4


def work_hours(
    points: Mapping[int, float], meetings: Iterable[int], rules: Rules
) -> int:
    """Godziny pracy w 8:00–18:00: dość punktów albo spotkanie ≥ 30 min."""
    met = set(meetings)
    return sum(
        1
        for hour in WORK_HOURS
        if points.get(hour, 0.0) >= rules.work_hour_min_points or hour in met
    )


def day_index(
    points: Mapping[int, float],
    meetings: Iterable[int],
    rules: Rules,
    *,
    available: float = 1.0,
) -> int | None:
    """Intensywność dnia 0–100; ``available`` = część dnia bez urlopu (1, 0,5, 0)."""
    if available <= 0:
        return None
    hours = work_hours(points, meetings, rules)
    day_points = sum(points.values())
    coverage = min(1.0, hours / (rules.norm_work_hours * available))
    volume = min(1.0, day_points / (rules.norm_day_points * available))
    return round((coverage + volume) / 2 * 100)


def period_index(indexes: Iterable[int | None]) -> int | None:
    """Średnia intensywność z dni pracy (dni urlopu = ``None`` pomijamy)."""
    values = [v for v in indexes if v is not None]
    return round(sum(values) / len(values)) if values else None


def intensity_level(index: int | None, rules: Rules) -> str | None:
    if index is None:
        return None
    if index >= rules.level_high:
        return "high"
    if index >= rules.level_mid:
        return "mid"
    return "low"


def diagnose(index: int | None, results_pct: float | None, rules: Rules) -> str | None:
    """Ćwiartka: ``model`` · ``quality`` (dużo pracy, mało CV) · ``more_volume``
    (skutecznie, ale mało) · ``more_work`` (mało i mało)."""
    if index is None or results_pct is None:
        return None
    busy = index >= rules.diag_intensity
    good = results_pct >= rules.diag_results_pct
    if busy and good:
        return "model"
    if busy:
        return "quality"
    if good:
        return "more_volume"
    return "more_work"


# ── Dane ────────────────────────────────────────────────────────────────────

# Notatki pisane przez system w imieniu osoby — nie są jej pracą.
_AUTO_NOTE_SOURCES = ("system", "card_note_import", "qc_confirmation", "teams_prep")
_SKIPPED_NOTE_KINDS = ("automatch", "application_form")
# Wpisy Historii zdarzeń, które nie są osobną pracą: dublują inny zapis
# (ruch karty, odpowiedzi formularza), są autozapisem albo automatem.
_SKIPPED_ACTIONS = (
    "stage_changed",
    "created_from_cv",
    "screening_answered",
    "branded_cv_edited",
    "b2b_cv_generated",
    "b2b_cv_generated_upload",
    "sso_user_provisioned",
    "document_url_issued",
    "snapshot_created",
    "snapshot_refreshed",
    "profile_rate_scraper_reverted",
    "traffit_transfer",
    "traffit_transfer_owner_settled",
    "moved_to_proposals",
    "branded_cv_attached_by_automation",
    "cv_auto_generate_started",
    "cv_auto_generate_skipped",
    "candidate_auto_added",
    "candidate_already_in_pool",
    "synced_with_orders",
    "screening_synced_from_note",
    "auto_match_proposed",
    "auto_full_review_finished",
)
# Ten sam rodzaj zapisu u ≥ 5 osób w tej samej minucie to import, nie praca
# (staging 20.10.2026 20:24: 66 rozmów u klienta i 66 feedbacków naraz).
BURST_MIN_USERS = 5

_EVENTS_SQL = """
WITH ev AS (
    SELECT cs.moved_by AS uid, cs.moved_at AS ts, 'action' AS kind, false AS burstable
    FROM candidate_stages cs
    WHERE cs.moved_by = ANY(:ids) AND cs.stage::text <> 'posting'
      AND cs.moved_at >= :start AND cs.moved_at < :end
    UNION ALL
    SELECT r.removed_by, r.removed_at, 'action', false
    FROM candidate_stage_removals r
    WHERE r.removed_by = ANY(:ids) AND r.removed_at >= :start AND r.removed_at < :end
    UNION ALL
    SELECT n.author_id, n.created_at,
           CASE WHEN n.kind IN ('card', 'screening_facts') THEN 'screening' ELSE 'note' END,
           false
    FROM notes n
    WHERE n.author_id = ANY(:ids) AND n.created_at >= :start AND n.created_at < :end
      AND COALESCE(n.kind, '') <> ALL(:skipped_note_kinds)
      AND COALESCE(n.external_source, '') <> ALL(:auto_note_sources)
    UNION ALL
    SELECT a.user_id, a.created_at,
           CASE
               WHEN a.action = 'screening_form_saved' THEN 'screening'
               WHEN a.action = 'branded_cv_finalized' THEN 'note'
               WHEN a.action IN ('document_downloaded', 'cv_file_downloaded') THEN 'view'
               ELSE 'action'
           END,
           false
    FROM activities a
    WHERE a.user_id = ANY(:ids) AND a.created_at >= :start AND a.created_at < :end
      AND a.action <> ALL(:skipped_actions) AND a.action NOT LIKE 'traffit:%'
    UNION ALL
    SELECT c.created_by, c.created_at, 'note', true
    FROM candidates c
    WHERE c.created_by = ANY(:ids) AND c.created_at >= :start AND c.created_at < :end
    UNION ALL
    SELECT g.created_by, g.created_at, 'cv', false
    FROM cv_generated_documents g
    WHERE g.created_by = ANY(:ids) AND g.created_at >= :start AND g.created_at < :end
    UNION ALL
    SELECT m.user_id, m.sent_at, 'action', false
    FROM emails m
    WHERE m.user_id = ANY(:ids) AND m.direction::text = 'sent'
      AND m.sent_at >= :start AND m.sent_at < :end
    UNION ALL
    SELECT q.created_by_user_id, q.created_at, 'action', false
    FROM cv_qc_runs q
    WHERE q.created_by_user_id = ANY(:ids) AND q.created_at >= :start AND q.created_at < :end
    UNION ALL
    SELECT ce.created_by, ce.created_at, 'client_step', true
    FROM calendar_events ce
    WHERE ce.created_by = ANY(:ids) AND ce.event_type::text = 'client_interview'
      AND COALESCE(ce.external_source, 'manual') = 'manual'
      AND ce.created_at >= :start AND ce.created_at < :end
    UNION ALL
    SELECT f.author_id, f.created_at, 'client_step', true
    FROM interview_feedback f
    WHERE f.author_id = ANY(:ids) AND f.created_at >= :start AND f.created_at < :end
    UNION ALL
    SELECT p.scheduled_by_user_id, p.created_at, 'client_step', false
    FROM prep_meetings p
    WHERE p.scheduled_by_user_id = ANY(:ids) AND p.created_at >= :start AND p.created_at < :end
    UNION ALL
    SELECT sr.created_by, sr.created_at, 'client_step', false
    FROM client_interview_slot_requests sr
    WHERE sr.created_by = ANY(:ids) AND sr.created_at >= :start AND sr.created_at < :end
),
bursts AS (
    SELECT kind, date_trunc('minute', ts) AS minute
    FROM ev
    WHERE burstable
    GROUP BY 1, 2
    HAVING count(DISTINCT uid) >= :burst_min_users
),
local_ev AS (
    SELECT ev.uid, ev.kind, ev.ts AT TIME ZONE 'Europe/Warsaw' AS local_ts
    FROM ev
    LEFT JOIN bursts b ON b.kind = ev.kind AND b.minute = date_trunc('minute', ev.ts)
    WHERE b.minute IS NULL
)
SELECT uid,
       local_ts::date AS day,
       extract(hour FROM local_ts)::int AS hour,
       kind,
       count(*) AS n,
       min(local_ts) AS first_ts,
       max(local_ts) AS last_ts
FROM local_ev
GROUP BY 1, 2, 3, 4
"""

_MEETINGS_SQL = """
SELECT COALESCE(created_by, operational_owner_id) AS uid,
       start_time AT TIME ZONE 'Europe/Warsaw' AS s,
       end_time AT TIME ZONE 'Europe/Warsaw' AS e
FROM calendar_events
WHERE external_source = 'microsoft365' AND NOT all_day
  AND status::text <> 'cancelled' AND end_time IS NOT NULL
  AND COALESCE(created_by, operational_owner_id) = ANY(:ids)
  AND start_time < :end AND end_time > :start
"""

# Zasługa z migawki `credited` (reguła 27.10.2026: konsumenci nie liczą
# `VERIFIER_ANCHORED_CTE` sami); zawężenie do etapu i okna jak w SQL-u niżej.
_CV_SENT_SQL = (
    CREDITED_FROM_SNAPSHOT_CTE
    + """
SELECT credit_user AS uid, count(*) AS n
FROM credited
WHERE stage = 'cv_sent' AND credit_user = ANY(:ids)
  AND reached_at >= :start AND reached_at < :end
GROUP BY credit_user
"""
)


def _bounds(start: date, end: date) -> dict[str, datetime]:
    """Granice okna w kalendarzu firmy (od północy ``start`` do północy po ``end``)."""
    return {
        "start": local_day_start_utc(start),
        "end": local_day_start_utc(end + timedelta(days=1)),
    }


async def rhythm_people(db: AsyncSession) -> list[User]:
    """Aktywni rekruterzy i TCM bez ról lidera, alfabetycznie.

    Konto, w imieniu którego działa integracja (``oauth_clients.acting_user_id``,
    np. „Integracje: …” z rolą TCM), nie jest człowiekiem — pomijamy je.
    """
    users = (
        (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    )
    integration_ids = set(
        (
            await db.execute(
                select(OAuthClient.acting_user_id).where(
                    OAuthClient.acting_user_id.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    people = [
        u
        for u in users
        if u.id not in integration_ids
        and u.has_any_role(*_INCLUDED_ROLES)
        and not u.has_any_role(*_EXCLUDED_ROLES)
    ]
    return sorted(people, key=lambda u: (u.name or "").lower())


def account_start(user: User) -> date | None:
    """Pierwszy dzień osoby w NEXUSIE (dzień założenia konta, kalendarz firmy).

    Dni przed nim nie liczą się do wskaźnika — nowa osoba nie ma „zer” za czas,
    zanim dostała konto.
    """
    created = getattr(user, "created_at", None)
    if created is None:
        return None
    if created.tzinfo is None:
        return created.date()
    return created.astimezone(ZoneInfo(DEFAULT_TZ)).date()


@dataclass
class DayCell:
    counts: dict[int, dict[str, int]] = field(default_factory=lambda: defaultdict(dict))
    first: datetime | None = None
    last: datetime | None = None


async def _events(
    db: AsyncSession, ids: Sequence[int], start: date, end: date
) -> dict[tuple[int, date], DayCell]:
    rows = (
        await db.execute(
            text(_EVENTS_SQL),
            {
                "ids": list(ids),
                **_bounds(start, end),
                "skipped_note_kinds": list(_SKIPPED_NOTE_KINDS),
                "auto_note_sources": list(_AUTO_NOTE_SOURCES),
                "skipped_actions": list(_SKIPPED_ACTIONS),
                "burst_min_users": BURST_MIN_USERS,
            },
        )
    ).all()
    cells: dict[tuple[int, date], DayCell] = defaultdict(DayCell)
    for row in rows:
        cell = cells[(int(row.uid), row.day)]
        cell.counts[int(row.hour)][row.kind] = int(row.n)
        cell.first = (
            row.first_ts if cell.first is None else min(cell.first, row.first_ts)
        )
        cell.last = row.last_ts if cell.last is None else max(cell.last, row.last_ts)
    return cells


async def _meetings(
    db: AsyncSession, ids: Sequence[int], start: date, end: date
) -> dict[tuple[int, date], set[int]]:
    rows = (
        await db.execute(text(_MEETINGS_SQL), {"ids": list(ids), **_bounds(start, end)})
    ).all()
    out: dict[tuple[int, date], set[int]] = defaultdict(set)
    for row in rows:
        out_hours = meeting_hours(row.s, row.e)
        for day, hour in out_hours:
            out[(int(row.uid), day)].add(hour)
    return out


def meeting_hours(start: datetime, end: datetime) -> list[tuple[date, int]]:
    """Godziny, w których spotkanie trwało co najmniej 30 minut."""
    out: list[tuple[date, int]] = []
    slot = start.replace(minute=0, second=0, microsecond=0)
    while slot < end:
        overlap = min(end, slot + timedelta(hours=1)) - max(start, slot)
        if overlap >= timedelta(minutes=30):
            out.append((slot.date(), slot.hour))
        slot += timedelta(hours=1)
    return out


async def _cv_sent(
    db: AsyncSession, ids: Sequence[int], start: date, end: date
) -> dict[int, int]:
    bounds = _bounds(start, end)
    params = {
        "ids": list(ids),
        **bounds,
        **await credited_bind(
            db, stage="cv_sent", since=bounds["start"], until=bounds["end"]
        ),
    }
    rows = (await db.execute(text(_CV_SENT_SQL), params)).all()
    return {int(r.uid): int(r.n) for r in rows}


def clamp_window(
    date_from: date | None, date_to: date | None, today: date
) -> tuple[date, date]:
    """Okno widoku: domyślnie 10 ostatnich dni roboczych, nie wcześniej niż 12.10."""
    end = min(date_to or today, today)
    if date_from is None:
        days = business_days(end - timedelta(days=21), end)[-10:]
        start = days[0] if days else end
    else:
        start = date_from
    start = max(start, RHYTHM_START, end - timedelta(days=MAX_WINDOW_DAYS - 1))
    return min(start, end), end


async def build_rhythm(
    db: AsyncSession,
    *,
    start: date,
    end: date,
    with_results: bool,
) -> dict[str, Any]:
    rules = await load_rules(db)
    people = await rhythm_people(db)
    ids = [u.id for u in people]
    days = business_days(start, end)
    if not ids or not days:
        return {
            "from": start,
            "to": end,
            "days": days,
            "rules": rules.as_json(),
            "people": [],
            "team_cv_per_day_median": None,
        }

    cells = await _events(db, ids, start, end)
    meetings = await _meetings(db, ids, start, end)
    absence = await absence_by_user(db, ids, start, end)
    cv_sent = await _cv_sent(db, ids, start, end) if with_results else {}

    out_people: list[dict[str, Any]] = []
    for user in people:
        absent = absence.get(user.id, {})
        started = account_start(user)
        person_days: list[dict[str, Any]] = []
        for day in days:
            cell = cells.get((user.id, day), DayCell())
            met = meetings.get((user.id, day), set())
            points = {h: hour_points(cell.counts.get(h, {}), rules) for h in range(24)}
            before_start = started is not None and day < started
            available = (
                0.0 if before_start else max(0.0, 1.0 - min(1.0, absent.get(day, 0.0)))
            )
            person_days.append(
                {
                    "date": day,
                    "before_start": before_start,
                    "leave": 0.0 if before_start else round(1.0 - available, 2),
                    "points": [round(points[h], 1) for h in HOURS],
                    "levels": [hour_level(points[h], rules) for h in HOURS],
                    "counts": [sum(cell.counts.get(h, {}).values()) for h in HOURS],
                    "meetings": [h in met for h in HOURS],
                    "first": cell.first.strftime("%H:%M") if cell.first else None,
                    "last": cell.last.strftime("%H:%M") if cell.last else None,
                    "work_hours": work_hours(points, met, rules)
                    if available > 0
                    else None,
                    "day_points": round(sum(points.values()), 1),
                    "index": day_index(points, met, rules, available=available),
                }
            )
        worked = [d for d in person_days if d["index"] is not None]
        index = period_index(d["index"] for d in worked)
        counted = [d for d in person_days if not d["before_start"]]
        worked_days = round(sum(1.0 - d["leave"] for d in counted), 1)
        entry: dict[str, Any] = {
            "user_id": user.id,
            "name": user.name,
            "days": person_days,
            "index": index,
            "level": intensity_level(index, rules),
            "worked_days": worked_days,
            "leave_days": round(len(counted) - worked_days, 1),
            "days_before_start": len(person_days) - len(counted),
            "avg_work_hours": (
                round(statistics.mean(d["work_hours"] for d in worked), 1)
                if worked
                else None
            ),
            "median_points": (
                round(statistics.median(d["day_points"] for d in worked))
                if worked
                else None
            ),
        }
        if with_results:
            n = cv_sent.get(user.id, 0)
            entry["cv_sent"] = n
            entry["cv_per_day"] = round(n / worked_days, 2) if worked_days else None
        out_people.append(entry)

    team_median: float | None = None
    if with_results:
        rates = [p["cv_per_day"] for p in out_people if p["cv_per_day"] is not None]
        team_median = statistics.median(rates) if rates else None
        for p in out_people:
            pct = (
                round(p["cv_per_day"] / team_median * 100)
                if team_median and p["cv_per_day"] is not None
                else None
            )
            p["results_pct"] = pct
            p["diagnosis"] = diagnose(p["index"], pct, rules)
    return {
        "from": start,
        "to": end,
        "days": days,
        "rules": rules.as_json(),
        "people": out_people,
        "team_cv_per_day_median": team_median,
    }
