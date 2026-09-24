"""Praktykant — pula do dzwonienia i codzienne listy (0374).

Deterministycznie, bez AI. Pula = kandydaci, do których telefon NIC nie
psuje (ma telefon, nie pracuje u nas, nie jest w toczącym się procesie, nikt
z zespołu ani z praktykantów nie dzwonił niedawno, nie prosił o spokój), a do
tego mają lukę w danych. Kolejność = popyt: najpierw pasujący do otwartych
rekrutacji, potem do większej liczby rekrutacji z ostatnich miesięcy.

Listy powstają co noc (``tasks.trainee_call_lists``), a pierwsze
``GET /api/trainee/today`` dnia generuje brakującą — deploy w nocy nie może
zostawić praktykanta bez pracy. Jedna blokada doradcza na dzień: dwie listy
składane równocześnie wzięłyby tych samych ludzi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.competence_category import CompetenceCategory
from app.models.job import JobStatus
from app.models.trainee import TraineeCallItem, TraineeCallList, TraineeProgram
from app.services import trainee_rules as rules_mod

logger = logging.getLogger(__name__)

_LOCK_KEY = 71_0371  # pg_advisory_xact_lock(key, dzień)
_POOL_LIMIT = 60_000

#: Ranking puli liczony raz na dzień i reguły (60 tys. profili w Pythonie to
#: sekundy) — kolejne listy dnia biorą go z pamięci procesu i pomijają osoby
#: już rozdane dziś (``_assigned_on``).
_ranked_cache: dict[tuple[date, str], tuple[datetime, list["RankedCandidate"]]] = {}

#: Pusty ranking nie jest ostateczny (audyt 24.09.2026): liczymy go ponownie,
#: ale nie częściej niż co tyle — pusta lista praktykanta pyta przy każdym GET.
_EMPTY_RANKING_RETRY = timedelta(minutes=10)

#: Ile osób z rankingu sprawdzamy jednym zapytaniem przed wpisaniem na listę.
_RECHECK_MARGIN = 20

#: Sprawy kolejki „Do przedzwonienia”, w które praktykant nie może wchodzić.
_CONTACT_BUSY_STATES = (
    "awaiting_capacity",
    "queued",
    "callback_due",
    "cooldown",
    "handoff_pending",
    "suppressed",
)


async def load_rules(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(AppSetting, rules_mod.RULES_KEY)
    return rules_mod.normalize_rules(row.value if row else None)


async def save_rules(
    db: AsyncSession, raw: dict[str, Any], *, user_id: Optional[int]
) -> dict[str, Any]:
    rules = rules_mod.normalize_rules(raw)
    await db.execute(
        pg_insert(AppSetting)
        .values(key=rules_mod.RULES_KEY, value=rules, updated_by=user_id)
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": rules, "updated_by": user_id},
        )
    )
    return rules


# ── Pula ──────────────────────────────────────────────────────────────────


def _gap_sql(rules: dict[str, Any]) -> str:
    parts: list[str] = []
    if rules["missing_rate"]:
        parts.append(
            "c.expected_rate_hourly IS NULL OR c.profile_rate_updated_at IS NULL "
            "OR c.profile_rate_updated_at < now() - make_interval(months => :stale_months)"
        )
    if rules["missing_b2b"]:
        parts.append("c.b2b_willingness IS NULL")
    if rules["missing_work_time"]:
        parts.append("c.work_time_preference IS NULL")
    if rules["missing_work_mode"]:
        parts.append(
            "(c.max_onsite_days_per_week IS NULL AND "
            "COALESCE(jsonb_array_length(CASE WHEN jsonb_typeof("
            "c.preferences->'remote_modes') = 'array' THEN "
            "c.preferences->'remote_modes' END), 0) = 0)"
        )
    if rules["missing_consents"]:
        parts.append(
            "c.accepts_below_min_rate IS NULL OR c.accepts_more_office_days IS NULL"
        )
    if rules["missing_availability"]:
        parts.append(
            "(c.availability_status::text = 'unknown' AND c.availability_date IS NULL)"
        )
    if not parts:
        return "FALSE"
    return " OR ".join(f"({p})" for p in parts)


def _hard_conditions_sql() -> str:
    """Warunki, przy których telefon COŚ psuje — wspólne dla puli i oddzwonień.

    Ta sama lista pilnuje trzech miejsc: pełnej puli, ponownego sprawdzenia
    osób z rankingu trzymanego w pamięci przez cały dzień i oddzwonień
    „później” (audyt 24.09.2026 — oddzwonienie omijało wszystkie filtry, więc
    osoba z czarnej listy albo „nie kontaktować” wracała na listę).
    """
    busy = ", ".join(f"'{s}'" for s in _CONTACT_BUSY_STATES)
    return f"""
  c.phone IS NOT NULL
  AND length(regexp_replace(c.phone, '[^0-9]', '', 'g')) >= 9
  AND c.status::text <> 'blacklisted'
  AND c.b2b_willingness IS DISTINCT FROM 'employment_only'
  AND NOT EXISTS (
      SELECT 1 FROM contracts ct
      WHERE ct.candidate_id = c.id
        AND ct.status::text IN ('active', 'ending')
        AND (ct.start_date IS NULL OR ct.start_date <= :today))
  AND NOT EXISTS (
      SELECT 1 FROM candidate_contact_cases cc
      WHERE cc.candidate_id = c.id AND cc.state IN ({busy}))
  AND NOT EXISTS (
      SELECT 1 FROM candidate_stages cs
      JOIN jobs j ON j.id = cs.job_id
      WHERE cs.candidate_id = c.id AND j.status::text = 'published'
        AND cs.moved_at >= now() - make_interval(days => :process_days))"""


def pool_sql(rules: dict[str, Any], *, only_ids: bool = False) -> str:
    """Kandydaci do dzwonienia (bez rankingu). Jedno zapytanie.

    ``only_ids`` zawęża do ``:ids`` — ponowne sprawdzenie osób z rankingu
    policzonego rano, zanim trafią na listę (stan mógł się zmienić w ciągu dnia).
    """
    ids_filter = "\n  AND c.id = ANY(:ids)" if only_ids else ""
    return f"""
SELECT c.id, c.competence_category_id, c.skills, c.expected_rate_hourly,
       c.profile_rate_updated_at, c.b2b_willingness, c.work_time_preference,
       c.preferences, c.max_onsite_days_per_week, c.accepts_below_min_rate,
       c.accepts_more_office_days, c.availability_status, c.availability_date
FROM candidates c
WHERE {_hard_conditions_sql()}{ids_filter}
  AND (c.call_facts_verified_at IS NULL
       OR c.call_facts_verified_at < now() - make_interval(days => :verified_days))
  AND (c.last_contacted_at IS NULL
       OR c.last_contacted_at < now() - make_interval(days => :contact_days))
  AND ({_gap_sql(rules)})
  AND NOT EXISTS (
      SELECT 1 FROM calls cl
      WHERE cl.candidate_id = c.id
        AND (cl.contact_outcome = 'do_not_contact'
             OR COALESCE(cl.started_at, cl.created_at)
                >= now() - make_interval(days => :contact_days)))
  AND NOT EXISTS (
      SELECT 1 FROM trainee_call_items ti
      WHERE ti.candidate_id = c.id
        AND (ti.list_date >= :recall_since
             OR ti.outcome = 'declined'
             OR (ti.outcome = 'wrong' AND ti.phone_snapshot = c.phone)))
LIMIT {_POOL_LIMIT}
"""


def callback_sql() -> str:
    """Oddzwonienia „później”, które nadal wolno wykonać.

    Te same twarde warunki co pula. Świeżość kontaktu liczy się z pominięciem
    telefonu tego samego praktykanta (to on umówił oddzwonienie), a luka
    w danych nie jest wymagana (kandydat prosił o telefon).
    """
    return f"""
SELECT c.id
FROM candidates c
WHERE c.id = ANY(:ids) AND {_hard_conditions_sql()}
  AND (c.call_facts_verified_at IS NULL
       OR c.call_facts_verified_at < now() - make_interval(days => :verified_days))
  AND NOT EXISTS (
      SELECT 1 FROM calls cl
      WHERE cl.candidate_id = c.id
        AND (cl.contact_outcome = 'do_not_contact'
             OR (cl.user_id IS DISTINCT FROM :trainee_id
                 AND COALESCE(cl.started_at, cl.created_at)
                     >= now() - make_interval(days => :contact_days))))
  AND NOT EXISTS (
      SELECT 1 FROM trainee_call_items ti
      WHERE ti.candidate_id = c.id
        AND (ti.outcome = 'declined'
             OR (ti.outcome = 'wrong' AND ti.phone_snapshot = c.phone)
             OR (ti.user_id <> :trainee_id AND ti.list_date >= :recall_since)))
"""


def _pool_params(rules: dict[str, Any], today: date) -> dict[str, Any]:
    return {
        "stale_months": int(rules["rate_stale_months"]),
        "verified_days": int(rules["verified_recently_days"]),
        "contact_days": int(rules["my_people_contact_days"]),
        "process_days": int(rules["process_active_days"]),
        "recall_since": today - timedelta(days=int(rules["trainee_recall_days"])),
        "today": today,
    }


@dataclass(frozen=True)
class RankedCandidate:
    candidate_id: int
    competence_category_id: Optional[int]
    demand: rules_mod.Demand
    missing: tuple[str, ...]
    stack_display: tuple[str, ...]


async def _demand_index(
    db: AsyncSession, rules: dict[str, Any]
) -> dict[str, list[rules_mod.DemandJob]]:
    from app.services.job_similarity import _load_pool  # noqa: PLC0415

    pool = await _load_pool(db)
    since = datetime.now(timezone.utc) - timedelta(
        days=round(int(rules["window_months"]) * 30.44)
    )
    jobs = [
        rules_mod.DemandJob(
            id=job.id,
            skills=job.skills,
            competence_category_id=job.competence_category_id,
            is_open=job.status == JobStatus.published.value,
        )
        for job in pool.jobs.values()
        if job.created_at is None or job.created_at >= since
    ]
    return rules_mod.build_index(jobs)


def _candidate_skills(raw: Any) -> tuple[frozenset[str], dict[str, str]]:
    from app.services.job_similarity import skill_set  # noqa: PLC0415
    from app.services.skill_normalize import canonical_of, iter_skill_names  # noqa: PLC0415

    display: dict[str, str] = {}
    for name in iter_skill_names(raw):
        display.setdefault(canonical_of(name), name.strip())
    return skill_set(raw), display


async def rank_pool(
    db: AsyncSession, rules: dict[str, Any], *, today: date
) -> list[RankedCandidate]:
    """Cała pula w kolejności dzwonienia (odsiana progiem ``min_fits``)."""
    index = await _demand_index(db, rules)
    now = datetime.now(timezone.utc)
    rows = (await db.execute(text(pool_sql(rules)), _pool_params(rules, today))).all()
    ranked: list[tuple[tuple, RankedCandidate]] = []
    min_fits = int(rules["min_fits"])
    for row in rows:
        skills, display = _candidate_skills(row.skills)
        demand = rules_mod.demand_for(skills, row.competence_category_id, index)
        if demand.fits < min_fits:
            continue
        missing = rules_mod.missing_codes(row, rules, now=now)
        if not missing:
            continue
        item = RankedCandidate(
            candidate_id=row.id,
            competence_category_id=row.competence_category_id,
            demand=demand,
            missing=tuple(missing),
            stack_display=tuple(display.get(s, s) for s in demand.stack),
        )
        ranked.append((rules_mod.rank_key(row.id, demand, missing), item))
    ranked.sort(key=lambda pair: pair[0])
    return [item for _, item in ranked]


async def pool_stats(
    db: AsyncSession, rules: dict[str, Any], *, today: date
) -> dict[str, Any]:
    """Wielkość puli, pasujący do otwartych i rozkład po kategoriach."""
    ranked = await rank_pool(db, rules, today=today)
    names = {
        cc.id: cc.name_pl for cc in (await db.scalars(select(CompetenceCategory))).all()
    }
    counts: dict[str, int] = {}
    for item in ranked:
        name = names.get(item.competence_category_id or -1, "Bez kategorii")
        counts[name] = counts.get(name, 0) + 1
    return {
        "size": len(ranked),
        "open_fit": sum(1 for item in ranked if item.demand.open_fits > 0),
        "by_category": [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def store_pool_stats(db: AsyncSession, stats: dict[str, Any]) -> None:
    await db.execute(
        pg_insert(AppSetting)
        .values(key=rules_mod.POOL_STATS_KEY, value=stats)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": stats})
    )


async def load_pool_stats(db: AsyncSession) -> Optional[dict[str, Any]]:
    row = await db.get(AppSetting, rules_mod.POOL_STATS_KEY)
    return dict(row.value) if row and isinstance(row.value, dict) else None


# ── Listy ─────────────────────────────────────────────────────────────────


def _reasons(item: RankedCandidate) -> dict[str, Any]:
    return {
        "fits": item.demand.fits,
        "open_fits": item.demand.open_fits,
        "stack": list(item.stack_display),
        "missing": list(item.missing),
        "job_ids": list(item.demand.job_ids[:50]),
    }


async def active_programs(db: AsyncSession, *, today: date) -> list[TraineeProgram]:
    from app.models.user import User, UserRole  # noqa: PLC0415

    rows = (
        await db.scalars(
            select(TraineeProgram)
            .join(User, User.id == TraineeProgram.user_id)
            .where(
                TraineeProgram.status == "active",
                TraineeProgram.start_date <= today,
                User.is_active.is_(True),
                User.role == UserRole.trainee,
            )
            .order_by(TraineeProgram.user_id)
        )
    ).all()
    return list(rows)


async def list_for(
    db: AsyncSession, user_id: int, list_date: date
) -> Optional[TraineeCallList]:
    return await db.scalar(
        select(TraineeCallList).where(
            TraineeCallList.user_id == user_id,
            TraineeCallList.list_date == list_date,
        )
    )


async def _scheduled_later(
    db: AsyncSession, user_id: int, today: date
) -> list[TraineeCallItem]:
    rows = await db.scalars(
        select(TraineeCallItem)
        .where(
            TraineeCallItem.user_id == user_id,
            TraineeCallItem.outcome == "later",
            TraineeCallItem.later_date == today,
        )
        .order_by(TraineeCallItem.id)
    )
    return list(rows.all())


async def _callable_ranked(
    db: AsyncSession, ids: list[int], rules: dict[str, Any], today: date
) -> set[int]:
    """Kto z porannego rankingu NADAL nadaje się do telefonu (te same warunki)."""
    if not ids:
        return set()
    rows = await db.execute(
        text(pool_sql(rules, only_ids=True)),
        {**_pool_params(rules, today), "ids": ids},
    )
    return {row.id for row in rows}


async def _callable_callbacks(
    db: AsyncSession,
    ids: list[int],
    rules: dict[str, Any],
    today: date,
    *,
    trainee_id: int,
) -> set[int]:
    if not ids:
        return set()
    rows = await db.execute(
        text(callback_sql()),
        {**_pool_params(rules, today), "ids": ids, "trainee_id": trainee_id},
    )
    return {row.id for row in rows}


async def _lists_to_fill(
    db: AsyncSession, programs: list[TraineeProgram], today: date
) -> list[tuple[TraineeProgram, Optional[TraineeCallList]]]:
    """Programy bez listy na dziś albo z listą PUSTĄ (audyt 24.09.2026).

    Pusta lista była ostateczna: pula pusta o 5:00 (np. za ostry próg w
    regułach) zostawiała praktykanta bez pracy na cały dzień, także po
    poprawieniu reguł. Lista z pozycjami nie jest nigdy przebudowywana.
    """
    todo: list[tuple[TraineeProgram, Optional[TraineeCallList]]] = []
    for program in programs:
        existing = await list_for(db, program.user_id, today)
        if existing is None:
            todo.append((program, None))
            continue
        if existing.size:
            continue
        has_items = await db.scalar(
            select(TraineeCallItem.id)
            .where(TraineeCallItem.list_id == existing.id)
            .limit(1)
        )
        if has_items is None:
            todo.append((program, existing))
    return todo


async def generate_lists(
    db: AsyncSession,
    programs: list[TraineeProgram],
    *,
    today: date,
    ranked: Optional[list[RankedCandidate]] = None,
) -> dict[int, int]:
    """Listy na ``today`` dla programów, które ich nie mają albo mają pustą.

    Zwraca ``{user_id: liczba pozycji}`` dla list założonych albo uzupełnionych
    w tym wywołaniu. Nie commituje — wołający kończy transakcję (blokada
    doradcza trzyma się do jej końca, więc równoległe wywołanie zobaczy gotowe
    listy).
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k, :d)"),
        {"k": _LOCK_KEY, "d": today.toordinal()},
    )
    todo = await _lists_to_fill(db, programs, today)
    if not todo:
        return {}
    rules = await load_rules(db)
    if ranked is None:
        ranked = await cached_ranking(db, rules, today=today)
    assigned = await _assigned_on(db, today)
    cursor = 0
    created: dict[int, int] = {}
    skipped_callbacks = 0
    for program, call_list in todo:
        if call_list is None:
            call_list = TraineeCallList(
                user_id=program.user_id, list_date=today, size=0
            )
            db.add(call_list)
            await db.flush()
        position = 0
        taken: set[int] = assigned
        callbacks = await _scheduled_later(db, program.user_id, today)
        allowed_callbacks = await _callable_callbacks(
            db,
            sorted({later.candidate_id for later in callbacks}),
            rules,
            today,
            trainee_id=program.user_id,
        )
        for later in callbacks:
            if later.candidate_id in taken:
                continue
            if later.candidate_id not in allowed_callbacks:
                # Kandydat od czasu umówienia oddzwonienia wszedł w proces,
                # dostał umowę, prosił o spokój albo trafił na czarną listę.
                skipped_callbacks += 1
                continue
            taken.add(later.candidate_id)
            position += 1
            reasons = dict(later.reasons or {})
            reasons["callback"] = True
            db.add(
                TraineeCallItem(
                    list_id=call_list.id,
                    user_id=program.user_id,
                    candidate_id=later.candidate_id,
                    list_date=today,
                    position=position,
                    reasons=reasons,
                )
            )
        while position < program.daily_list_size and cursor < len(ranked):
            # Ranking policzono rano; stan kandydata mógł się zmienić w ciągu
            # dnia — każdą paczkę sprawdzamy ponownie warunkami puli.
            need = program.daily_list_size - position
            batch: list[tuple[int, RankedCandidate]] = []
            scan = cursor
            while scan < len(ranked) and len(batch) < need + _RECHECK_MARGIN:
                item = ranked[scan]
                if item.candidate_id not in taken:
                    batch.append((scan, item))
                scan += 1
            if not batch:
                cursor = scan
                break
            allowed = await _callable_ranked(
                db, [item.candidate_id for _, item in batch], rules, today
            )
            cursor = scan
            for index, item in batch:
                if position >= program.daily_list_size:
                    # Reszta paczki czeka na następny program z kolejki.
                    cursor = index
                    break
                if item.candidate_id not in allowed:
                    continue
                taken.add(item.candidate_id)
                position += 1
                db.add(
                    TraineeCallItem(
                        list_id=call_list.id,
                        user_id=program.user_id,
                        candidate_id=item.candidate_id,
                        list_date=today,
                        position=position,
                        reasons=_reasons(item),
                    )
                )
        call_list.size = position
        created[program.user_id] = position
        await db.flush()
    logger.info(
        "trainee call lists generated date=%s lists=%s pool=%s skipped_callbacks=%s",
        today.isoformat(),
        created,
        len(ranked),
        skipped_callbacks,
    )
    return created


async def _assigned_on(db: AsyncSession, day: date) -> set[int]:
    rows = await db.scalars(
        select(TraineeCallItem.candidate_id).where(TraineeCallItem.list_date == day)
    )
    return set(rows.all())


async def cached_ranking(
    db: AsyncSession, rules: dict[str, Any], *, today: date
) -> list[RankedCandidate]:
    key = (today, repr(sorted(rules.items())))
    cached = _ranked_cache.get(key)
    now = datetime.now(timezone.utc)
    if cached is not None and (cached[1] or now - cached[0] < _EMPTY_RANKING_RETRY):
        return cached[1]
    _ranked_cache.clear()
    ranking = await rank_pool(db, rules, today=today)
    _ranked_cache[key] = (now, ranking)
    return ranking


def reset_ranking_cache() -> None:
    _ranked_cache.clear()


async def ensure_list(
    db: AsyncSession, program: TraineeProgram, *, today: date
) -> Optional[TraineeCallList]:
    """Lista na dziś — założona, jeśli jej brak, i uzupełniona, jeśli pusta
    (dzień roboczy, program trwa)."""
    existing = await list_for(db, program.user_id, today)
    if existing is not None and existing.size:
        return existing
    if not rules_mod.is_workday(today) or program.status != "active":
        return existing
    if program.start_date > today:
        return existing
    await generate_lists(db, [program], today=today)
    await db.commit()
    return await list_for(db, program.user_id, today)
