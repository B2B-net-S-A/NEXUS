"""„Moi ludzie" — lista rekrutera, która buduje się sama.

Rekruter wysyła tych samych ludzi do klientów raz za razem, aż któryś projekt
się zamknie. Ta lista to jego „ławka": każdy kandydat, którego ZWERYFIKOWAŁ
jako pierwszy w danej rekrutacji, a który potem doszedł do „CV Wysłane"
(ktokolwiek to CV wysłał). Decyzja Artura 21.09.2026 — ta sama intuicja co
atrybucja wyścigów („kto dowiózł człowieka"), ale liczona WPROST z historii
etapów, nie przez ``VERIFIER_ANCHORED_CTE``: tamto CTE płaci nagrody, jest
ciężkie i nie wolno go ruszać przy okazji.

Reguły (pilnuje ``tests/test_my_people.py``):

- właściciel pary (kandydat, rekrutacja) = autor PIERWSZEGO aktywnego wiersza
  ``verified`` tej pary (porządek ``moved_at, id`` jak ``pipeline_latest``);
- para bez żadnej weryfikacji (import Traffita pomija etap) → właściciel =
  autor pierwszego ``cv_sent``;
- para, która nigdy nie doszła do ``cv_sent``, nie tworzy listy;
- bez limitu czasu — porządek robi ręczne „Uśpij" (``my_people_overrides``);
- „Przypnij" dokłada osobę spoza wyliczenia;
- globalna blacklista wyklucza zawsze; osoba z żywą umową nie znika, tylko
  trafia do grupy „Pracują" (lista mówi wtedy prawdę: to Twój człowiek, ale
  dziś nie ma sensu go przepinać).

Nazwa w UI to „Moi ludzie", nie „ławka": ``EmploymentState.on_bench`` znaczy
już co innego (konsultant bez projektu).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.candidate import Candidate, CandidateStatus
from app.models.competence_category import CandidateCompetenceCategory
from app.models.my_people import MyPeopleJobMatch, MyPeopleOverride
from app.models.recruitment_pipeline import STAGE_ORDER
from app.services.current_employment import current_employment_client_ids

# Bezpiecznik, nie limit biznesowy: lista nie ma horyzontu czasu, więc po latach
# importu Traffita jeden rekruter może mieć kilkaset osób. Powyżej tej liczby
# odpowiedź mówi wprost, że jest przycięta.
MAX_ROWS = 2000

IDLE_DAYS = 30

_TERMINAL = ("hired", "rejected", "withdrawn")

_STAGE_RANK_SQL = (
    "CASE cs.stage::text "
    + " ".join(f"WHEN '{s.value}' THEN {i}" for i, s in enumerate(STAGE_ORDER))
    + " ELSE -1 END"
)
_RANK_TO_STAGE = {i: s.value for i, s in enumerate(STAGE_ORDER)}


def _owned_pairs_cte(*, single_user: bool) -> str:
    """CTE ``owned(candidate_id, job_id, owner_id)``.

    Dla jednego użytkownika zapytanie zaczyna od JEGO wierszy (indeks
    ``ix_candidate_stages_moved_by_stage``), zamiast liczyć pierwszego
    weryfikatora dla każdej pary w bazie.
    """
    scope = (
        """
        scope AS (
            SELECT DISTINCT candidate_id, job_id
            FROM candidate_stages
            WHERE moved_by = :uid AND stage IN ('verified', 'cv_sent')
        ),"""
        if single_user
        else """
        scope AS (
            SELECT DISTINCT candidate_id, job_id
            FROM candidate_stages
            WHERE stage = 'cv_sent'
        ),"""
    )
    owner_filter = (
        "WHERE COALESCE(v.moved_by, s.moved_by) = :uid"
        if single_user
        else ("WHERE COALESCE(v.moved_by, s.moved_by) IS NOT NULL")
    )
    return f"""
    WITH {scope}
    first_verified AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.moved_by
        FROM candidate_stages cs
        JOIN scope p ON p.candidate_id = cs.candidate_id AND p.job_id = cs.job_id
        WHERE cs.stage = 'verified' AND cs.verification_status = 'active'
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at, cs.id
    ),
    first_sent AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.moved_by
        FROM candidate_stages cs
        JOIN scope p ON p.candidate_id = cs.candidate_id AND p.job_id = cs.job_id
        WHERE cs.stage = 'cv_sent'
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at, cs.id
    ),
    owned AS (
        SELECT s.candidate_id, s.job_id,
               COALESCE(v.moved_by, s.moved_by) AS owner_id
        FROM first_sent s
        LEFT JOIN first_verified v
          ON v.candidate_id = s.candidate_id AND v.job_id = s.job_id
        {owner_filter}
    )
    """


@dataclass
class PersonRow:
    candidate_id: int
    full_name: str
    category_id: Optional[int] = None
    furthest_stage: Optional[str] = None
    last_sent_at: Optional[datetime] = None
    last_sent_job_title: Optional[str] = None
    last_sent_client_name: Optional[str] = None
    sent_count: int = 0
    days_since_last_send: Optional[int] = None
    expected_rate_hourly: Optional[float] = None
    availability_status: Optional[str] = None
    city: Optional[str] = None
    source: str = "auto"
    active_processes: int = 0
    working: bool = False
    snoozed: bool = False
    snooze_reason: Optional[str] = None
    snoozed_at: Optional[datetime] = None
    new_matches: int = 0


@dataclass
class MyPeople:
    rows: list[PersonRow] = field(default_factory=list)
    truncated: bool = False

    @property
    def active(self) -> list[PersonRow]:
        return [r for r in self.rows if not r.snoozed and not r.working]


async def owned_candidate_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Wyliczone osoby użytkownika (bez przypięć i uśpień)."""
    sql = _owned_pairs_cte(single_user=True) + "SELECT DISTINCT candidate_id FROM owned"
    return {int(r[0]) for r in (await db.execute(text(sql), {"uid": user_id})).all()}


async def owners_by_candidate(db: AsyncSession) -> dict[int, set[int]]:
    """``{candidate_id: {user_id, ...}}`` dla WSZYSTKICH rekruterów.

    Ręczne decyzje są już uwzględnione: uśpienie zdejmuje osobę z listy danego
    użytkownika, przypięcie ją dokłada. Czyta całą historię ``cv_sent`` —
    wołane wyłącznie z pracy w tle (publikacja rekrutacji).
    """
    sql = (
        _owned_pairs_cte(single_user=False)
        + "SELECT DISTINCT candidate_id, owner_id FROM owned"
    )
    out: dict[int, set[int]] = {}
    for cid, uid in (await db.execute(text(sql))).all():
        out.setdefault(int(cid), set()).add(int(uid))
    for ov in (await db.scalars(select(MyPeopleOverride))).all():
        owners = out.setdefault(ov.candidate_id, set())
        if ov.kind == "snoozed":
            owners.discard(ov.user_id)
        else:
            owners.add(ov.user_id)
    return {cid: users for cid, users in out.items() if users}


async def _pair_stats(db: AsyncSession, user_id: int) -> dict[int, dict]:
    sql = (
        _owned_pairs_cte(single_user=True)
        + f"""
    , agg AS (
        SELECT o.candidate_id,
               COUNT(DISTINCT o.job_id) FILTER (WHERE cs.stage = 'cv_sent') AS sent_count,
               MAX({_STAGE_RANK_SQL}) AS furthest_rank
        FROM owned o
        JOIN candidate_stages cs
          ON cs.candidate_id = o.candidate_id AND cs.job_id = o.job_id
        GROUP BY o.candidate_id
    ),
    last_send AS (
        SELECT DISTINCT ON (o.candidate_id)
               o.candidate_id, cs.moved_at, j.title, cl.name AS client_name
        FROM owned o
        JOIN candidate_stages cs
          ON cs.candidate_id = o.candidate_id AND cs.job_id = o.job_id
         AND cs.stage = 'cv_sent'
        JOIN jobs j ON j.id = o.job_id
        LEFT JOIN clients cl ON cl.id = j.client_id
        ORDER BY o.candidate_id, cs.moved_at DESC, cs.id DESC
    )
    SELECT a.candidate_id, a.sent_count, a.furthest_rank,
           l.moved_at, l.title, l.client_name
    FROM agg a LEFT JOIN last_send l ON l.candidate_id = a.candidate_id
    """
    )
    out: dict[int, dict] = {}
    for cid, sent, rank, moved_at, title, client in (
        await db.execute(text(sql), {"uid": user_id})
    ).all():
        out[int(cid)] = {
            "sent_count": int(sent or 0),
            "furthest_stage": _RANK_TO_STAGE.get(int(rank))
            if rank is not None
            else None,
            "last_sent_at": moved_at,
            "last_sent_job_title": title,
            "last_sent_client_name": client,
        }
    return out


async def active_process_counts(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, int]:
    """Ile opublikowanych rekrutacji trzyma dziś osobę na etapie niekońcowym."""
    ids = sorted({int(c) for c in candidate_ids})
    if not ids:
        return {}
    sql = """
    SELECT latest.candidate_id, COUNT(*)
    FROM (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.stage::text AS stage
        FROM candidate_stages cs
        WHERE cs.candidate_id = ANY(:ids)
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    ) latest
    JOIN jobs j ON j.id = latest.job_id AND j.status = 'published'
    WHERE latest.stage <> ALL(:terminal)
    GROUP BY latest.candidate_id
    """
    rows = await db.execute(text(sql), {"ids": ids, "terminal": list(_TERMINAL)})
    return {int(cid): int(n) for cid, n in rows.all()}


async def _primary_categories(
    db: AsyncSession, candidate_ids: list[int]
) -> dict[int, int]:
    if not candidate_ids:
        return {}
    rows = await db.execute(
        select(
            CandidateCompetenceCategory.candidate_id,
            CandidateCompetenceCategory.competence_category_id,
        ).where(
            CandidateCompetenceCategory.candidate_id.in_(candidate_ids),
            CandidateCompetenceCategory.is_primary.is_(True),
        )
    )
    return {int(cid): int(cc) for cid, cc in rows.all()}


async def _unseen_match_counts(db: AsyncSession, user_id: int) -> dict[int, int]:
    rows = await db.execute(
        text(
            "SELECT candidate_id, COUNT(*) FROM my_people_job_matches "
            "WHERE user_id = :uid AND seen_at IS NULL GROUP BY candidate_id"
        ),
        {"uid": user_id},
    )
    return {int(cid): int(n) for cid, n in rows.all()}


def _days_since(moment: Optional[datetime], today: date) -> Optional[int]:
    """Dni od znacznika do ``today`` (kalendarz firmy, ``business_today``).

    Znacznik z bazy jest w UTC — jego DZIEŃ liczymy też w strefie firmy, inaczej
    przez 1–2 h na dobę (wysyłka po 22:00/23:00 UTC) wynik był przesunięty
    o dzień.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local_day = moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()
    return max(0, (today - local_day).days)


def _sort_key(row: PersonRow) -> tuple:
    rank = next(
        (i for i, s in enumerate(STAGE_ORDER) if s.value == row.furthest_stage), -1
    )
    sent = row.last_sent_at.timestamp() if row.last_sent_at else 0.0
    return (-rank, -sent, row.full_name.lower())


async def load_my_people(db: AsyncSession, user_id: int) -> MyPeople:
    stats = await _pair_stats(db, user_id)
    overrides = {
        ov.candidate_id: ov
        for ov in (
            await db.scalars(
                select(MyPeopleOverride).where(MyPeopleOverride.user_id == user_id)
            )
        ).all()
    }
    # Uśpieni też jadą w odpowiedzi (grupa „Uśpieni") — inaczej nie da się ich
    # przywrócić z tego samego ekranu.
    ids = sorted(set(stats) | set(overrides))
    if not ids:
        return MyPeople()

    candidates = {
        c.id: c
        for c in (
            await db.scalars(
                select(Candidate).where(
                    Candidate.id.in_(ids),
                    Candidate.status != CandidateStatus.blacklisted,
                )
            )
        ).all()
    }
    ids = [cid for cid in ids if cid in candidates]
    today = business_today()
    categories = await _primary_categories(db, ids)
    employment = await current_employment_client_ids(db, ids, today=today)
    processes = await active_process_counts(db, ids)
    unseen = await _unseen_match_counts(db, user_id)

    rows: list[PersonRow] = []
    for cid in ids:
        cand = candidates[cid]
        st = stats.get(cid, {})
        ov = overrides.get(cid)
        rate = cand.expected_rate_hourly
        availability = cand.availability_status
        rows.append(
            PersonRow(
                candidate_id=cid,
                full_name=f"{cand.name or ''} {cand.lastname or ''}".strip(),
                category_id=categories.get(cid, cand.competence_category_id),
                furthest_stage=st.get("furthest_stage"),
                last_sent_at=st.get("last_sent_at"),
                last_sent_job_title=st.get("last_sent_job_title"),
                last_sent_client_name=st.get("last_sent_client_name"),
                sent_count=st.get("sent_count", 0),
                days_since_last_send=_days_since(st.get("last_sent_at"), today),
                expected_rate_hourly=float(rate) if rate is not None else None,
                availability_status=getattr(availability, "value", availability),
                city=cand.city,
                source="auto" if cid in stats else "pinned",
                active_processes=processes.get(cid, 0),
                working=bool(employment.get(cid)),
                snoozed=bool(ov and ov.kind == "snoozed"),
                snooze_reason=ov.reason if ov and ov.kind == "snoozed" else None,
                snoozed_at=ov.created_at if ov and ov.kind == "snoozed" else None,
                new_matches=unseen.get(cid, 0),
            )
        )
    rows.sort(key=_sort_key)
    truncated = len(rows) > MAX_ROWS
    return MyPeople(rows=rows[:MAX_ROWS], truncated=truncated)


async def unseen_matches(
    db: AsyncSession, user_id: int, *, limit: int = 5
) -> list[dict]:
    """Najnowsze nieobejrzane dopasowania — treść dymka awatara."""
    rows = await db.execute(
        text(
            """
            SELECT m.job_id, j.title, m.candidate_id,
                   c.name || ' ' || c.lastname AS full_name, m.score, m.created_at
            FROM my_people_job_matches m
            JOIN jobs j ON j.id = m.job_id AND j.status = 'published'
            JOIN candidates c ON c.id = m.candidate_id
            WHERE m.user_id = :uid AND m.seen_at IS NULL
            ORDER BY m.created_at DESC, m.score DESC NULLS LAST
            LIMIT :limit
            """
        ),
        {"uid": user_id, "limit": limit},
    )
    return [
        {
            "job_id": int(job_id),
            "job_title": title,
            "candidate_id": int(cid),
            "full_name": name,
            "score": float(score) if score is not None else None,
            "created_at": created,
        }
        for job_id, title, cid, name, score, created in rows.all()
    ]


async def unseen_totals(db: AsyncSession, user_id: int) -> tuple[int, int]:
    """``(liczba dopasowań, liczba rekrutacji)`` — tylko opublikowane rekrutacje."""
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*), COUNT(DISTINCT m.job_id)
                FROM my_people_job_matches m
                JOIN jobs j ON j.id = m.job_id AND j.status = 'published'
                WHERE m.user_id = :uid AND m.seen_at IS NULL
                """
            ),
            {"uid": user_id},
        )
    ).one()
    return int(row[0]), int(row[1])


async def mark_matches_seen(
    db: AsyncSession, user_id: int, *, job_id: Optional[int] = None
) -> int:
    stmt = (
        MyPeopleJobMatch.__table__.update()
        .where(
            MyPeopleJobMatch.user_id == user_id,
            MyPeopleJobMatch.seen_at.is_(None),
        )
        .values(seen_at=datetime.now(timezone.utc))
    )
    if job_id is not None:
        stmt = stmt.where(MyPeopleJobMatch.job_id == job_id)
    result = await db.execute(stmt)
    return int(result.rowcount or 0)
