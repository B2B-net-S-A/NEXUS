"""Rytm dnia i intensywność pracy rekruterów (decyzje Artura 28.10.2026).

Insights → „Rytm dnia”: kiedy i jak intensywnie rekruterzy pracują w NEXUSIE,
godzina po godzinie. Widzą to tylko Head of Recruitment i admin (29.10.2026);
pokazujemy każdego z rolą rekrutera, także DL-i z dopisanym rekruterem
(bez samych TCM, Head of Recruitment i adminów), bez formy współpracy.
Liczymy od 12.10.2026 — od tego dnia zespół pracuje w NEXUSIE.

* **Punkty pracy** — każda akcja osoby ma wagę swojego rodzaju (``KINDS``).
  Screening waży najwięcej, bo za notatką stoi rozmowa; klikanie kart mało,
  żeby nie opłacało się „nabijać”. Importy, automaty i autozapisy nie liczą się.
* **Ochrona przed nabijaniem** (29.10.2026) — CV z automatu, ponowne zapisy
  i podglądy tej samej rzeczy, masowe akcje, powrót karty na ten sam etap
  i „nie odbiera” ponad dzienny limit nie dają punktów (``classify_events``).
* **Poziom godziny** — suma punktów w godzinie wobec progów ``hour_levels``.
* **Godzina pracy** — co najmniej ``work_hour_min_points`` albo prep
  ustawiony z NEXUSA trwający ≥ 30 min w tej godzinie; liczona 8:00–18:00.
  Godzina z samych drobnych akcji przy jednym kandydacie się nie liczy.
* **Czas pracy** (29.10.2026) — suma odcinków, w których osoba coś robi
  w NEXUSIE: akcje (także te bez punktów, poza automatem) i prepy. 30 min
  bez akcji i bez prepa = przerwa, nie praca. Minimum to 8 h dziennie (``min_work_hours``); poniżej średnio
  8 h nikt nie jest wzorem ani nie ma „wysokiej” intensywności.
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
from app.schemas.pipeline import STAGE_LABELS, PipelineStage
from app.services.credited_snapshot import CREDITED_FROM_SNAPSHOT_CTE, credited_bind
from app.services.person_workdays import absence_by_user, business_days

RULES_KEY = "work_rhythm_rules"
RHYTHM_START = date(2026, 10, 12)
MAX_WINDOW_DAYS = 31

HOURS: tuple[int, ...] = tuple(range(7, 20))
WORK_HOURS: frozenset[int] = frozenset(range(8, 18))

# Rodzaje akcji — klucze wag w ustawieniach (kolejność = kolejność na ekranie).
KINDS: tuple[str, ...] = (
    "screening",
    "client_step",
    "cv",
    "note",
    "contact",
    "action",
    "view",
)
# Rodzaje, z których jedna akcja wystarcza na godzinę pracy (za nimi stoi rozmowa
# albo dokument); reszta musi dotyczyć kilku kandydatów.
STRONG_KINDS = frozenset({"screening", "client_step", "cv"})

DEFAULT_RULES: dict[str, Any] = {
    "weights": {
        "screening": 5,
        "client_step": 3,
        "cv": 3,
        "note": 2,
        "contact": 1,
        "action": 1,
        "view": 0.5,
    },
    # Progi poziomów godziny = kwartyle zespołu od 12.10 (P25 3,5 · P50 11 · P75 25).
    "hour_levels": [4, 11, 25],
    "work_hour_min_points": 4,
    # Minimum czasu pracy dziennie i norma godzin intensywnych (decyzja Artura 29.10.2026).
    "min_work_hours": 8,
    "norm_day_points": 120,
    "level_high": 75,
    "level_mid": 50,
    "diag_intensity": 60,
    "diag_results_pct": 80,
    # Ochrona przed nabijaniem (decyzja Artura 29.10.2026). Limit 0 = bez limitu.
    "auto_cv_points": 0,
    "screening_per_candidate_day": 1,
    "repeats_per_hour": 1,
    "views_per_hour": 4,
    "bulk_per_minute": 10,
    "stage_return_points": 0,
    "contacts_per_day": 10,
    "thin_hour_candidates": 2,
    # 30 min bez akcji i bez prepa = przerwa (decyzja Artura 29.10.2026).
    "break_minutes": 30,
}
GUARD_FIELDS: tuple[str, ...] = (
    "auto_cv_points",
    "screening_per_candidate_day",
    "repeats_per_hour",
    "views_per_hour",
    "bulk_per_minute",
    "stage_return_points",
    "contacts_per_day",
    "thin_hour_candidates",
    "break_minutes",
)
_FLOAT_GUARDS = frozenset({"auto_cv_points", "stage_return_points"})

# Każdy z rolą rekrutera, także DL z dopisanym rekruterem; sam TCM nie
# (decyzja Artura 29.10.2026). HoR i admin oglądają, nie są wierszami.
_INCLUDED_ROLES = (UserRole.recruiter,)
_EXCLUDED_ROLES = (UserRole.head_of_recruitment, UserRole.admin)
# Na razie całą zakładkę widzą tylko Head of Recruitment i admin (decyzja
# Artura 29.10.2026, po wcześniejszym „widzi cały zespół”); oni też zmieniają reguły.
VIEWER_ROLES = (UserRole.admin, UserRole.head_of_recruitment)
RULES_EDITOR_ROLES = VIEWER_ROLES


@dataclass(frozen=True)
class Rules:
    weights: Mapping[str, float]
    hour_levels: tuple[float, float, float]
    work_hour_min_points: float
    min_work_hours: float
    norm_day_points: float
    level_high: int
    level_mid: int
    diag_intensity: int
    diag_results_pct: int
    auto_cv_points: float = 0
    screening_per_candidate_day: int = 1
    repeats_per_hour: int = 1
    views_per_hour: int = 4
    bulk_per_minute: int = 10
    stage_return_points: float = 0
    contacts_per_day: int = 10
    thin_hour_candidates: int = 2
    break_minutes: int = 30

    def as_json(self) -> dict[str, Any]:
        return {
            "weights": {k: self.weights[k] for k in KINDS},
            "hour_levels": list(self.hour_levels),
            "work_hour_min_points": self.work_hour_min_points,
            "min_work_hours": self.min_work_hours,
            "norm_day_points": self.norm_day_points,
            "level_high": self.level_high,
            "level_mid": self.level_mid,
            "diag_intensity": self.diag_intensity,
            "diag_results_pct": self.diag_results_pct,
            **{k: getattr(self, k) for k in GUARD_FIELDS},
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
        min_work_hours=float(data["min_work_hours"]),
        norm_day_points=float(data["norm_day_points"]),
        level_high=int(data["level_high"]),
        level_mid=int(data["level_mid"]),
        diag_intensity=int(data["diag_intensity"]),
        diag_results_pct=int(data["diag_results_pct"]),
        **{
            k: float(data[k]) if k in _FLOAT_GUARDS else int(data[k])
            for k in GUARD_FIELDS
        },
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
    points: Mapping[int, float],
    meetings: Iterable[int],
    rules: Rules,
    *,
    thin: Iterable[int] = (),
) -> int:
    """Godziny pracy w 8:00–18:00: dość punktów albo prep z NEXUSA ≥ 30 min.

    ``thin`` = godziny z samych drobnych akcji przy zbyt małej liczbie
    kandydatów — punkty zostają, ale godziną pracy nie są.
    """
    met = set(meetings)
    skip = set(thin)
    return sum(
        1
        for hour in WORK_HOURS
        if hour in met
        or (points.get(hour, 0.0) >= rules.work_hour_min_points and hour not in skip)
    )


def day_index(
    points: Mapping[int, float],
    meetings: Iterable[int],
    rules: Rules,
    *,
    available: float = 1.0,
    thin: Iterable[int] = (),
) -> int | None:
    """Intensywność dnia 0–100; ``available`` = część dnia bez urlopu (1, 0,5, 0)."""
    if available <= 0:
        return None
    hours = work_hours(points, meetings, rules, thin=thin)
    day_points = sum(points.values())
    coverage = min(1.0, hours / (rules.min_work_hours * available))
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


def gate_index(index: int | None, work_time: float | None, rules: Rules) -> int | None:
    """Poniżej minimum godzin nie ma „wysokiej” intensywności (najwyżej próg − 1)."""
    if index is None or work_time is None or work_time >= rules.min_work_hours:
        return index
    return min(index, rules.level_high - 1)


def gated_day_index(
    points: Mapping[int, float],
    meetings: Iterable[int],
    rules: Rules,
    *,
    available: float,
    work_time: float | None,
    thin: Iterable[int] = (),
) -> int | None:
    """Intensywność dnia z bramką minimum godzin (pół dnia urlopu = pół minimum)."""
    index = day_index(points, meetings, rules, available=available, thin=thin)
    if index is None or work_time is None:
        return index
    return gate_index(index, work_time / available, rules)


def diagnose(
    index: int | None,
    results_pct: float | None,
    rules: Rules,
    *,
    work_time: float | None,
) -> str | None:
    """Podpowiedź dla lidera — najpierw minimum 8 h, potem intensywność i wyniki.

    Poniżej minimum: ``short_good`` (dobre wyniki, za mało godzin) albo
    ``more_work``. Przy minimum: ``model`` · ``quality`` (dużo pracy, mało CV) ·
    ``idle`` (jest w NEXUSIE, ale mało robi).
    """
    if index is None or results_pct is None or work_time is None:
        return None
    good = results_pct >= rules.diag_results_pct
    if work_time < rules.min_work_hours:
        return "short_good" if good else "more_work"
    if index < rules.diag_intensity:
        return "idle"
    return "model" if good else "quality"


def worked_time(
    stamps: Iterable[datetime],
    meetings: Iterable[tuple[datetime, datetime]],
    rules: Rules,
) -> tuple[float, list[tuple[datetime, datetime]]]:
    """Czas pracy w godzinach i jego odcinki.

    Akcje bliżej siebie niż ``break_minutes`` (i prepy, w całości) tworzą jeden
    odcinek pracy; dłuższa cisza to przerwa. Pojedyncza akcja bez sąsiadów nie
    daje czasu — nie wiemy, ile trwała.
    """
    spans = sorted([(t, t) for t in stamps] + [(s, e) for s, e in meetings])
    if not spans:
        return 0.0, []
    gap = timedelta(minutes=rules.break_minutes)
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start - last_end < gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    # Pełne minuty w dół: 7:59:46 to 7 h 59, nigdy „8 h” po zaokrągleniu.
    minutes = int(sum((e - s).total_seconds() for s, e in merged) // 60)
    return minutes / 60, merged


@dataclass(frozen=True)
class Event:
    """Jedna akcja osoby: ``ts`` w czasie firmy (bez strefy), ``src``/``act`` —
    skąd pochodzi i co to było, ``ent`` — czego dotyczy (kandydat, karta, plik)."""

    uid: int
    ts: datetime
    kind: str
    src: str
    act: str
    ent: str


# Powody, dla których akcja nie dała punktów (klucze w „skipped” i rozkładzie dnia).
SKIP_REASONS: tuple[str, ...] = (
    "automat",
    "powtorka",
    "limit_podgladow",
    "masowa",
    "powrot",
    "limit_kontaktu",
)


def classify_events(
    events: Iterable[Event], rules: Rules
) -> list[tuple[Event, float, str | None]]:
    """Punkty każdej akcji po ochronie przed nabijaniem: ``(akcja, pkt, powód)``.

    Powód ``None`` = akcja liczy się w pełni. Kolejność ma znaczenie: pierwsza
    z serii zostaje, kolejne odpadają, więc akcje sortujemy po czasie.
    """
    ordered = sorted(events, key=lambda e: (e.uid, e.ts))
    per_minute: dict[tuple, int] = defaultdict(int)
    for e in ordered:
        per_minute[(e.uid, e.src, e.act, e.ts.replace(second=0, microsecond=0))] += 1
    seen: dict[tuple, int] = defaultdict(int)
    out: list[tuple[Event, float, str | None]] = []
    for e in ordered:
        weight = rules.weights.get(e.kind, 0.0)
        day, hour = e.ts.date(), e.ts.hour
        minute = (e.uid, e.src, e.act, e.ts.replace(second=0, microsecond=0))
        reason: str | None = None
        points = weight
        if e.src == "cv" and e.act == "auto":
            points = rules.auto_cv_points
            reason = "automat" if points < weight else None
        elif rules.bulk_per_minute and per_minute[minute] >= rules.bulk_per_minute:
            seen[("bulk", *minute)] += 1
            if seen[("bulk", *minute)] > 1:
                reason = "masowa"
        if reason is None and e.src == "stage":
            seen[("stage", e.uid, e.ent, e.act, day)] += 1
            if seen[("stage", e.uid, e.ent, e.act, day)] > 1:
                points = rules.stage_return_points
                reason = "powrot" if points < weight else None
        if reason is None and e.kind == "screening":
            seen[("scr", e.uid, e.ent, day)] += 1
            limit = rules.screening_per_candidate_day
            if limit and seen[("scr", e.uid, e.ent, day)] > limit:
                reason = "powtorka"
        elif reason is None and e.src in ("act", "cv"):
            seen[("rep", e.uid, e.src, e.act, e.ent, day, hour)] += 1
            limit = rules.repeats_per_hour
            if limit and seen[("rep", e.uid, e.src, e.act, e.ent, day, hour)] > limit:
                reason = "powtorka"
        if reason is None and e.kind == "view":
            seen[("view", e.uid, day, hour)] += 1
            limit = rules.views_per_hour
            if limit and seen[("view", e.uid, day, hour)] > limit:
                reason = "limit_podgladow"
        if reason is None and e.kind == "contact":
            seen[("contact", e.uid, day)] += 1
            limit = rules.contacts_per_day
            if limit and seen[("contact", e.uid, day)] > limit:
                reason = "limit_kontaktu"
        if reason is not None and reason not in ("automat", "powrot"):
            points = 0.0
        out.append((e, points, reason))
    return out


def thin_hours(
    classified: Iterable[tuple[Event, float, str | None]], rules: Rules
) -> set[int]:
    """Godziny „podtrzymane” drobiazgami: punkty z samych drobnych akcji przy
    mniej niż ``thin_hour_candidates`` kandydatach (4 ruchy jednej karty)."""
    if rules.thin_hour_candidates <= 1:
        return set()
    strong: set[int] = set()
    entities: dict[int, set[str]] = defaultdict(set)
    points_by_hour: dict[int, float] = defaultdict(float)
    for e, points, _ in classified:
        if points <= 0:
            continue
        points_by_hour[e.ts.hour] += points
        if e.kind in STRONG_KINDS:
            strong.add(e.ts.hour)
        entities[e.ts.hour].add(e.ent.split(":")[0])
    return {
        h
        for h, ents in entities.items()
        if h not in strong
        and len(ents) < rules.thin_hour_candidates
        and points_by_hour[h] >= rules.work_hour_min_points
    }


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
    SELECT cs.moved_by AS uid, cs.moved_at AS ts, 'action' AS kind, false AS burstable,
           'stage' AS src, cs.stage::text AS act,
           cs.candidate_id || ':' || cs.job_id AS ent
    FROM candidate_stages cs
    WHERE cs.moved_by = ANY(:ids) AND cs.stage::text <> 'posting'
      AND cs.moved_at >= :start AND cs.moved_at < :end
    UNION ALL
    SELECT r.removed_by, r.removed_at, 'action', false,
           'removal', '', r.candidate_id || ':' || r.job_id
    FROM candidate_stage_removals r
    WHERE r.removed_by = ANY(:ids) AND r.removed_at >= :start AND r.removed_at < :end
    UNION ALL
    SELECT n.author_id, n.created_at,
           CASE WHEN n.kind IN ('card', 'screening_facts') THEN 'screening'
                WHEN n.kind = 'contact_attempt' THEN 'contact'
                ELSE 'note' END,
           false, 'note', COALESCE(n.kind, ''), COALESCE(n.candidate_id::text, 'n' || n.id)
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
           false, 'act', a.action,
           CASE WHEN a.entity_type = 'candidate' THEN a.entity_id::text
                ELSE a.entity_type || '/' || COALESCE(a.entity_id::text, '') END
    FROM activities a
    WHERE a.user_id = ANY(:ids) AND a.created_at >= :start AND a.created_at < :end
      AND a.action <> ALL(:skipped_actions) AND a.action NOT LIKE 'traffit:%'
    UNION ALL
    SELECT c.created_by, c.created_at, 'note', true, 'candidate', '', c.id::text
    FROM candidates c
    WHERE c.created_by = ANY(:ids) AND c.created_at >= :start AND c.created_at < :end
    UNION ALL
    SELECT g.created_by, g.created_at, 'cv', false,
           'cv', COALESCE(g.origin, ''),
           COALESCE(g.candidate_id || ':' || COALESCE(g.job_id, 0), 'g' || g.id)
    FROM cv_generated_documents g
    WHERE g.created_by = ANY(:ids) AND g.created_at >= :start AND g.created_at < :end
    UNION ALL
    SELECT m.user_id, m.sent_at, 'action', false,
           'email', '', COALESCE(m.candidate_id::text, 'm' || m.id)
    FROM emails m
    WHERE m.user_id = ANY(:ids) AND m.direction::text = 'sent'
      AND m.sent_at >= :start AND m.sent_at < :end
    UNION ALL
    SELECT q.created_by_user_id, q.created_at, 'action', false, 'qc', '', 'q' || q.id
    FROM cv_qc_runs q
    WHERE q.created_by_user_id = ANY(:ids) AND q.created_at >= :start AND q.created_at < :end
    UNION ALL
    SELECT ce.created_by, ce.created_at, 'client_step', true,
           'interview', '', COALESCE(ce.candidate_id::text, 'e' || ce.id)
    FROM calendar_events ce
    WHERE ce.created_by = ANY(:ids) AND ce.event_type::text = 'client_interview'
      AND COALESCE(ce.external_source, 'manual') = 'manual'
      AND ce.created_at >= :start AND ce.created_at < :end
    UNION ALL
    SELECT f.author_id, f.created_at, 'client_step', true, 'feedback', '', 'f' || f.id
    FROM interview_feedback f
    WHERE f.author_id = ANY(:ids) AND f.created_at >= :start AND f.created_at < :end
    UNION ALL
    SELECT p.scheduled_by_user_id, p.created_at, 'client_step', false,
           'prep', '', p.candidate_id::text
    FROM prep_meetings p
    WHERE p.scheduled_by_user_id = ANY(:ids) AND p.created_at >= :start AND p.created_at < :end
    UNION ALL
    SELECT sr.created_by, sr.created_at, 'client_step', false, 'slots', '', 's' || sr.id
    FROM client_interview_slot_requests sr
    WHERE sr.created_by = ANY(:ids) AND sr.created_at >= :start AND sr.created_at < :end
),
bursts AS (
    SELECT kind, date_trunc('minute', ts) AS minute
    FROM ev
    WHERE burstable
    GROUP BY 1, 2
    HAVING count(DISTINCT uid) >= :burst_min_users
)
SELECT ev.uid, ev.ts AT TIME ZONE 'Europe/Warsaw' AS local_ts,
       ev.kind, ev.src, ev.act, ev.ent
FROM ev
LEFT JOIN bursts b ON b.kind = ev.kind AND b.minute = date_trunc('minute', ev.ts)
WHERE b.minute IS NULL
ORDER BY ev.uid, ev.ts
"""

# Spotkanie = tylko prep ustawiony z NEXUSA (decyzja Artura 29.10.2026):
# cykliczne wpisy M365 bez uczestników to blokady kalendarza, nie rozmowy.
_MEETINGS_SQL = """
SELECT COALESCE(p.scheduled_by_user_id, p.organizer_user_id) AS uid,
       ce.start_time AT TIME ZONE 'Europe/Warsaw' AS s,
       ce.end_time AT TIME ZONE 'Europe/Warsaw' AS e
FROM prep_meetings p
JOIN calendar_events ce ON ce.id = p.calendar_event_id
WHERE ce.status::text <> 'cancelled' AND ce.end_time IS NOT NULL
  AND COALESCE(p.scheduled_by_user_id, p.organizer_user_id) = ANY(:ids)
  AND ce.start_time < :end AND ce.end_time > :start
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


def is_rhythm_person(user: User) -> bool:
    return user.has_any_role(*_INCLUDED_ROLES) and not user.has_any_role(
        *_EXCLUDED_ROLES
    )


async def rhythm_people(db: AsyncSession) -> list[User]:
    """Aktywne osoby z rolą rekrutera (bez HoR i adminów), alfabetycznie.

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
    people = [u for u in users if u.id not in integration_ids and is_rhythm_person(u)]
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
    """Dzień osoby po ochronie przed nabijaniem."""

    points: dict[int, float] = field(default_factory=lambda: defaultdict(float))
    counts: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    skipped: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    thin: set[int] = field(default_factory=set)
    stamps: list[datetime] = field(default_factory=list)
    first: datetime | None = None
    last: datetime | None = None


async def _raw_events(
    db: AsyncSession, ids: Sequence[int], start: date, end: date
) -> list[Event]:
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
    return [
        Event(int(r.uid), r.local_ts, r.kind, r.src, r.act or "", str(r.ent))
        for r in rows
    ]


def build_cells(
    classified: Iterable[tuple[Event, float, str | None]], rules: Rules
) -> dict[tuple[int, date], DayCell]:
    by_day: dict[tuple[int, date], list[tuple[Event, float, str | None]]] = defaultdict(
        list
    )
    for item in classified:
        by_day[(item[0].uid, item[0].ts.date())].append(item)
    cells: dict[tuple[int, date], DayCell] = {}
    for key, items in by_day.items():
        cell = DayCell()
        for e, points, reason in items:
            hour = e.ts.hour
            cell.points[hour] += points
            # Akcja bez punktów (podgląd ponad limit, powtórka) to wciąż chwila
            # pracy — liczy się do czasu pracy; automat nie (Artur 29.10.2026).
            if reason != "automat":
                cell.stamps.append(e.ts)
            if reason is None:
                cell.counts[hour] += 1
            else:
                cell.skipped[reason] += rules.weights.get(e.kind, 0.0) - points
            cell.first = e.ts if cell.first is None else min(cell.first, e.ts)
            cell.last = e.ts if cell.last is None else max(cell.last, e.ts)
        cell.thin = thin_hours(items, rules)
        cells[key] = cell
    return cells


async def _meetings(
    db: AsyncSession, ids: Sequence[int], start: date, end: date
) -> tuple[
    dict[tuple[int, date], set[int]],
    dict[tuple[int, date], list[tuple[datetime, datetime]]],
]:
    """Prepy osoby: godziny z ≥ 30 min prepa i same odcinki (do czasu pracy)."""
    rows = (
        await db.execute(text(_MEETINGS_SQL), {"ids": list(ids), **_bounds(start, end)})
    ).all()
    hours: dict[tuple[int, date], set[int]] = defaultdict(set)
    spans: dict[tuple[int, date], list[tuple[datetime, datetime]]] = defaultdict(list)
    for row in rows:
        spans[(int(row.uid), row.s.date())].append((row.s, row.e))
        for day, hour in meeting_hours(row.s, row.e):
            hours[(int(row.uid), day)].add(hour)
    return hours, spans


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


def summarize_days(
    person_days: Sequence[Mapping[str, Any]], rules: Rules
) -> dict[str, Any]:
    """Liczby okresu osoby z jej dni.

    Liczą się tylko dni zakończone i od założenia konta: dzisiejszy dzień
    (``in_progress``) i dni przed kontem (``before_start``) zostają na ekranie,
    ale nie wchodzą do średniej, dni pracy, urlopu ani median. Czas pracy dnia
    z pół dnia urlopu przeliczamy na pełny etat (4 h z 4 = 8 h).
    """
    counted = [
        d for d in person_days if not d["before_start"] and not d.get("in_progress")
    ]
    worked = [d for d in counted if d["index"] is not None]
    worked_days = round(sum(1.0 - d["leave"] for d in counted), 1)
    timed = [
        (d["work_time"], 1.0 - d["leave"])
        for d in counted
        if d.get("work_time") is not None and d["leave"] < 1
    ]
    # Bez zaokrąglania przed porównaniem z minimum: średnia 7,96 h to nie 8 h.
    avg_work_time = statistics.mean(t / share for t, share in timed) if timed else None
    index = gate_index(period_index(d["index"] for d in worked), avg_work_time, rules)
    return {
        "index": index,
        # Bez zaokrąglenia — ta sama liczba idzie do bramki, podpowiedzi i na ekran.
        "avg_work_time": avg_work_time,
        "full_days": sum(
            1 for t, share in timed if t >= rules.min_work_hours * share - 1e-9
        ),
        "timed_days": len(timed),
        "worked_days": worked_days,
        "leave_days": round(len(counted) - worked_days, 1),
        "days_before_start": sum(1 for d in person_days if d["before_start"]),
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
    today: date | None = None,
) -> dict[str, Any]:
    """``today`` = dzień, który jeszcze trwa: widać go w „Dzień”, ale nie liczy
    się do okresu ani do CV na dzień (rano zaniżałby wynik całego zespołu)."""
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

    cells = build_cells(
        classify_events(await _raw_events(db, ids, start, end), rules), rules
    )
    meetings, meeting_spans = await _meetings(db, ids, start, end)
    absence = await absence_by_user(db, ids, start, end)
    cv_end = end - timedelta(days=1) if today is not None and end >= today else end
    cv_sent = (
        await _cv_sent(db, ids, start, cv_end)
        if with_results and cv_end >= start
        else {}
    )

    out_people: list[dict[str, Any]] = []
    for user in people:
        absent = absence.get(user.id, {})
        started = account_start(user)
        person_days: list[dict[str, Any]] = []
        for day in days:
            cell = cells.get((user.id, day), DayCell())
            spans_today = meeting_spans.get((user.id, day), [])
            met = meetings.get((user.id, day), set())
            points = {h: cell.points.get(h, 0.0) for h in range(24)}
            before_start = started is not None and day < started
            available = (
                0.0 if before_start else max(0.0, 1.0 - min(1.0, absent.get(day, 0.0)))
            )
            day_time = (
                worked_time(cell.stamps, spans_today, rules)[0]
                if available > 0
                else None
            )
            person_days.append(
                {
                    "date": day,
                    "before_start": before_start,
                    "in_progress": day == today,
                    "leave": 0.0 if before_start else round(1.0 - available, 2),
                    "points": [round(points[h], 1) for h in HOURS],
                    "levels": [hour_level(points[h], rules) for h in HOURS],
                    "counts": [cell.counts.get(h, 0) for h in HOURS],
                    "thin": [h in cell.thin for h in HOURS],
                    "skipped": {k: round(v, 1) for k, v in cell.skipped.items()},
                    "meetings": [h in met for h in HOURS],
                    "first": cell.first.strftime("%H:%M") if cell.first else None,
                    "last": cell.last.strftime("%H:%M") if cell.last else None,
                    "work_hours": work_hours(points, met, rules, thin=cell.thin)
                    if available > 0
                    else None,
                    "work_time": day_time,
                    "day_points": round(sum(points.values()), 1),
                    # Dzień, który trwa, bez bramki — rano zawsze brakuje godzin.
                    "index": gated_day_index(
                        points,
                        met,
                        rules,
                        available=available,
                        work_time=None if day == today else day_time,
                        thin=cell.thin,
                    ),
                }
            )
        entry: dict[str, Any] = {
            "user_id": user.id,
            "name": user.name,
            "days": person_days,
            **summarize_days(person_days, rules),
        }
        entry["level"] = intensity_level(entry["index"], rules)
        if with_results:
            n = cv_sent.get(user.id, 0)
            entry["cv_sent"] = n
            worked_days = entry["worked_days"]
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
            p["diagnosis"] = diagnose(
                p["index"], pct, rules, work_time=p["avg_work_time"]
            )
    return {
        "from": start,
        "to": end,
        "days": days,
        "rules": rules.as_json(),
        "people": out_people,
        "team_cv_per_day_median": team_median,
    }


# ── Rozkład dnia osoby (kliknięcie w dzień) ─────────────────────────────────

_SRC_LABELS = {
    "removal": "Usunięcie z rekrutacji",
    "candidate": "Dodany kandydat",
    "email": "Wysłany mail",
    "qc": "QC CV",
    "interview": "Rozmowa u klienta umówiona",
    "feedback": "Feedback z rozmowy u klienta",
    "prep": "Prep umówiony",
    "slots": "Prośba o terminy rozmowy",
}
_NOTE_LABELS = {
    "card": "Karta screeningu",
    "screening_facts": "Fakty z rozmowy (screening)",
    "contact_attempt": "Próba kontaktu („nie odbiera”)",
    "scheduling": "Notatka: umówienie",
    "status": "Notatka: status",
    "contractor": "Notatka kontraktora",
}
_ACTION_LABELS = {
    "document_downloaded": "Podgląd dokumentu",
    "cv_file_downloaded": "Podgląd CV",
    "screening_form_saved": "Formularz screeningu",
    "recommendation_card_updated": "Karta rekomendacji",
    "candidate_rate_change_requested": "Prośba o zmianę stawki",
    "branded_cv_finalized": "Finalizacja CV",
    "candidate_claimed": "Przejęcie kandydata",
    "cv_uploaded": "Wgranie CV",
    "cv_qc_confirmed": "QC CV potwierdzone",
    "removed_from_recruitment": "Usunięcie z rekrutacji",
    "proposal_inbox_opened": "Otwarcie propozycji z bazy",
    "cv_qc_fix_applied": "Poprawka po QC CV",
    "cv_command_ai": "Poprawka CV z AI",
    "document_uploaded": "Wgranie dokumentu",
    "branded_cv_new_version": "Nowa wersja CV",
    "client_rate_changed": "Zmiana stawki dla klienta",
    "champion_profile_updated": "Profil Championa",
}


def event_label(src: str, act: str) -> str:
    """Nazwa akcji w rozkładzie dnia."""
    if src == "stage":
        try:
            stage = STAGE_LABELS.get(PipelineStage(act), act)
        except ValueError:
            stage = act
        return f"Ruch karty → {stage}"
    if src == "note":
        return _NOTE_LABELS.get(act, "Notatka")
    if src == "act":
        return _ACTION_LABELS.get(act, f"Inny zapis ({act})")
    if src == "cv":
        return "CV z automatu" if act == "auto" else "Wygenerowane CV"
    return _SRC_LABELS.get(src, src)


def candidate_id_of(src: str, ent: str) -> int | None:
    """Kandydat, którego dotyczy akcja (``kandydat:rekrutacja`` albo samo id)."""
    head = ent.split(":", 1)[0] if src in ("stage", "removal", "cv") else ent
    return int(head) if head.isdigit() else None


async def build_day(db: AsyncSession, user_id: int, day: date) -> dict[str, Any] | None:
    """Akcje osoby z jednego dnia: co się liczy, a co odpadło i dlaczego.

    ``None`` = osoby nie ma w Rytmie dnia. Import wielu osób naraz rozpoznajemy
    po całym zespole, więc zdarzenia bierzemy dla wszystkich i zawężamy potem.
    """
    rules = await load_rules(db)
    people = await rhythm_people(db)
    person = next((u for u in people if u.id == user_id), None)
    if person is None:
        return None
    raw = await _raw_events(db, [u.id for u in people], day, day)
    classified = [c for c in classify_events(raw, rules) if c[0].uid == user_id]
    cell = build_cells(classified, rules).get((user_id, day), DayCell())
    hours, spans = await _meetings(db, [user_id], day, day)
    met = hours.get((user_id, day), set())
    time_h, work_spans = worked_time(cell.stamps, spans.get((user_id, day), []), rules)
    cand_ids = {cid for e, _, _ in classified if (cid := candidate_id_of(e.src, e.ent))}
    names: dict[int, str] = {}
    if cand_ids:
        rows = await db.execute(
            text("SELECT id, name, lastname FROM candidates WHERE id = ANY(:ids)"),
            {"ids": sorted(cand_ids)},
        )
        names = {
            int(r.id): " ".join(p for p in (r.name, r.lastname) if p) for r in rows
        }
    return {
        "user_id": user_id,
        "name": person.name,
        "date": day,
        "points": [round(cell.points.get(h, 0.0), 1) for h in HOURS],
        "meetings": [h in met for h in HOURS],
        "thin": [h in cell.thin for h in HOURS],
        "skipped": {k: round(v, 1) for k, v in cell.skipped.items()},
        "work_time": round(time_h, 2),
        "spans": [[s.strftime("%H:%M"), e.strftime("%H:%M")] for s, e in work_spans],
        "events": [
            {
                "time": e.ts.strftime("%H:%M"),
                "hour": e.ts.hour,
                "kind": e.kind,
                "label": event_label(e.src, e.act),
                "candidate": names.get(candidate_id_of(e.src, e.ent) or 0),
                "points": round(points, 2),
                "weight": rules.weights.get(e.kind, 0.0),
                "reason": reason,
            }
            for e, points, reason in classified
        ],
    }
