"""Zakładka „Źródła” w Insights: portale i strona kariery, jedna tabela, osoby za liczbą.

Decyzje Artura 03.11.2026 (reguła: ``docs/claude/finanse-insights/zakladka-zrodla.md``).

Portale czytają ``candidate_source_events``. Zgłoszenie z portalu nie ma rekrutacji
(``job_id`` puste), więc etap to ruch osoby po pierwszym zgłoszeniu w oknie, w dowolnej
rekrutacji. Linki czytają ``activities.applied_via_invite`` tą samą regułą co
``insights_link_people``, żeby tabela zgadzała się z „Kto co przyniósł”.

Liczby i listy osób biorą flagi z tych samych CTE: liczba po kliknięciu nie może
rozjechać się z listą pod nią.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_source_event import UNDATED_IMPORT_NOTE_MARK
from app.services.placement_exclusions import excluded_hired_sql

SOURCE_PRACUJ = "pracuj"
SOURCE_JJIT = "jjit"
SOURCE_LINK_GENERAL = "link_general"
SOURCE_LINK_JOB = "link_job"
PORTAL_SOURCES = (SOURCE_PRACUJ, SOURCE_JJIT)
LINK_SOURCES = (SOURCE_LINK_GENERAL, SOURCE_LINK_JOB)
SOURCE_PATTERN = "^(pracuj|jjit|link_general|link_job)$"

SOURCE_LABELS = {
    SOURCE_PRACUJ: "Pracuj.pl",
    SOURCE_JJIT: "JustJoin.IT i RocketJobs",
    SOURCE_LINK_GENERAL: "Link ogólny rekrutera",
    SOURCE_LINK_JOB: "Linki do rekrutacji",
}

# `pracuj` i `jjit` wysyłają scrapery, reszta to `Portal.value` z linku aplikacji
# ogłoszeń publikowanych przez API (`job_portals.service.portal_apply_url`).
_PRACUJ_UTM = ["pracuj", "pracuj_pl"]
_JJIT_UTM = ["jjit", "justjoinit", "rocketjobs"]

# Scraper zakłada kandydata tuż przed zapisem źródła, więc nowy w bazie = założony
# najpóźniej kilka minut przed pierwszym zgłoszeniem.
_NEW_CANDIDATE_GRACE = "10 minutes"

# Kolejność Tablicy (`lib/board-stages.ts`): `interview` należy do kolumny
# „Zweryfikowany”, stoi przed `cv_sent`. Odrzucenie jest na końcu, bo najdalszy etap
# ma mówić, dokąd osoba doszła.
_STAGE_RANK = [
    "withdrawn",
    "rejected",
    "new",
    "screening",
    "prep_call",
    "interview",
    "verified",
    "cv_sent",
    "client_interview",
    "acceptance",
    "hired",
]

_COUNTS = """
    count(*) FILTER (WHERE fresh) AS fresh,
    count(*) FILTER (WHERE in_process) AS in_process,
    count(*) FILTER (WHERE verified) AS verified,
    count(*) FILTER (WHERE cv_sent) AS cv_sent,
    count(*) FILTER (WHERE hired) AS hired
"""

# Stałe nazwy kolumn z `flags`, nigdy tekst od klienta (trasa sprawdza wzorcem).
_METRIC_WHERE = {
    "people": "TRUE",
    "applications": "TRUE",
    "fresh": "flags.fresh",
    "in_process": "flags.in_process",
    "verified": "flags.verified",
    "cv_sent": "flags.cv_sent",
    "hired": "flags.hired",
}
METRIC_PATTERN = "^(" + "|".join(_METRIC_WHERE) + ")$"

_PORTAL_EVENTS = """
    ev AS (
        SELECT e.candidate_id, e.captured_at,
               CASE WHEN e.utm_source = ANY(CAST(:pracuj_utm AS text[]))
                    THEN 'pracuj' ELSE 'jjit' END AS source,
               COALESCE(substring(e.note from '— oferta: (.*)$'), '') AS offer
        FROM candidate_source_events e
        WHERE e.captured_at >= :since AND e.captured_at < :until
          AND e.utm_source = ANY(CAST(:portal_utm AS text[]))
    )
"""

# `max`, nie `min`: osoba zweryfikowana rok temu w innej rekrutacji i znowu po tym
# zgłoszeniu ma się liczyć, a pierwsze wejście każdej pary jest osobnym wierszem.
_PORTAL_FLAGS = f"""
    reached AS (
        SELECT m.candidate_id,
               max(m.first_reached_at) FILTER (WHERE m.stage::text = 'verified') AS verified_at,
               max(m.first_reached_at) FILTER (WHERE m.stage::text = 'cv_sent') AS cv_sent_at,
               max(m.first_reached_at) FILTER (WHERE m.stage::text = 'hired') AS hired_at
        FROM analytics_first_milestones m
        WHERE m.stage::text IN ('verified', 'cv_sent', 'hired')
          AND m.candidate_id IN (SELECT candidate_id FROM f)
        GROUP BY m.candidate_id
    ),
    moved AS (
        SELECT cs.candidate_id, max(cs.moved_at) AS last_moved
        FROM candidate_stages cs
        WHERE cs.stage::text <> 'posting'
          AND cs.candidate_id IN (SELECT candidate_id FROM f)
        GROUP BY cs.candidate_id
    ),
    flags AS (
        SELECT f.*, c.name AS first_name, c.lastname AS last_name,
               c.created_at >= f.first_at - INTERVAL '{_NEW_CANDIDATE_GRACE}' AS fresh,
               COALESCE(mv.last_moved >= f.first_at, FALSE) AS in_process,
               COALESCE(r.verified_at >= f.first_at, FALSE) AS verified,
               COALESCE(r.cv_sent_at >= f.first_at, FALSE) AS cv_sent,
               COALESCE(r.hired_at >= f.first_at, FALSE) AS hired
        FROM f
        JOIN candidates c ON c.id = f.candidate_id
        LEFT JOIN moved mv ON mv.candidate_id = f.candidate_id
        LEFT JOIN reached r ON r.candidate_id = f.candidate_id
    )
"""

# Lustro `insights_link_people`: jedno zgłoszenie = para link × kandydat, etap w
# rekrutacji linku, a przy linku ogólnym w dowolnej.
_LINK_FLAGS = f"""
    links AS (
        SELECT l.token, l.created_by AS owner_id, l.job_id,
               CASE WHEN l.kind = 'recruiter' THEN 'link_general' ELSE 'link_job' END AS source,
               COALESCE(
                   l.token_sha256,
                   encode(sha256(convert_to(l.token, 'UTF8')), 'hex')
               ) AS link_key
        FROM candidate_invite_links l
    ),
    apps AS (
        SELECT DISTINCT ON (a.details->>'invite_token_sha256', a.entity_id)
               a.details->>'invite_token_sha256' AS link_key,
               a.entity_id AS candidate_id,
               a.created_at AS first_at,
               COALESCE(a.details->>'was_duplicate', 'false') = 'true' AS was_duplicate
        FROM activities a
        WHERE a.action = 'applied_via_invite'
          AND a.entity_type = 'candidate'
          AND a.created_at >= :since AND a.created_at < :until
        ORDER BY a.details->>'invite_token_sha256', a.entity_id, a.created_at
    ),
    flags AS (
        SELECT links.source, links.owner_id, links.job_id AS link_job_id,
               apps.link_key, apps.candidate_id, apps.first_at,
               NOT apps.was_duplicate AS fresh,
               COALESCE(BOOL_OR(cs.stage::text <> 'posting'), FALSE) AS in_process,
               COALESCE(BOOL_OR(cs.stage::text = 'verified'), FALSE) AS verified,
               COALESCE(BOOL_OR(cs.stage::text = 'cv_sent'), FALSE) AS cv_sent,
               COALESCE(BOOL_OR(cs.stage::text = 'hired'), FALSE) AS hired
        FROM apps
        JOIN links ON links.link_key = apps.link_key
        LEFT JOIN candidate_stages cs
          ON cs.candidate_id = apps.candidate_id
         AND (links.job_id IS NULL OR cs.job_id = links.job_id)
         AND cs.moved_at >= apps.first_at - INTERVAL '1 hour'
         AND {excluded_hired_sql("cs")}
        GROUP BY links.source, links.owner_id, links.job_id, apps.link_key,
                 apps.candidate_id, apps.first_at, apps.was_duplicate
    )
"""


def _portal_params(since: datetime, until: datetime) -> dict[str, Any]:
    return {
        "since": since,
        "until": until,
        "pracuj_utm": _PRACUJ_UTM,
        "portal_utm": [*_PRACUJ_UTM, *_JJIT_UTM],
    }


def _row_counts(row: Any) -> dict[str, int]:
    return {
        "people": int(row.people or 0),
        "applications": int(row.applications or 0),
        "fresh": int(row.fresh or 0),
        "in_process": int(row.in_process or 0),
        "verified": int(row.verified or 0),
        "cv_sent": int(row.cv_sent or 0),
        "hired": int(row.hired or 0),
    }


_EMPTY_COUNTS = {
    "people": 0,
    "applications": 0,
    "fresh": 0,
    "in_process": 0,
    "verified": 0,
    "cv_sent": 0,
    "hired": 0,
}


async def compute_sources(
    db: AsyncSession, *, since: datetime, until: datetime
) -> dict[str, Any]:
    """Tabela zakładki. „Razem” liczy osobę raz, więc nie jest sumą wierszy."""
    params = _portal_params(since, until)
    by_source = await db.execute(
        text(
            f"""
            WITH {_PORTAL_EVENTS},
            f AS (
                SELECT source, candidate_id, min(captured_at) AS first_at,
                       count(*) AS applications
                FROM ev GROUP BY source, candidate_id
            ),
            {_PORTAL_FLAGS}
            SELECT source, count(*) AS people, sum(applications) AS applications, {_COUNTS}
            FROM flags GROUP BY source
            """
        ),
        params,
    )
    portal_counts = {row.source: _row_counts(row) for row in by_source}
    portals_total = (
        await db.execute(
            text(
                f"""
                WITH {_PORTAL_EVENTS},
                f AS (
                    SELECT candidate_id, min(captured_at) AS first_at,
                           count(*) AS applications
                    FROM ev GROUP BY candidate_id
                ),
                {_PORTAL_FLAGS}
                SELECT count(*) AS people, sum(applications) AS applications, {_COUNTS}
                FROM flags
                """
            ),
            params,
        )
    ).one()
    links = await db.execute(
        text(
            f"""
            WITH {_LINK_FLAGS}
            SELECT source, count(DISTINCT candidate_id) AS people,
                   count(*) AS applications, {_COUNTS}
            FROM flags GROUP BY GROUPING SETS ((source), ())
            """
        ),
        {"since": since, "until": until},
    )
    link_rows = {row.source: _row_counts(row) for row in links}
    coverage = (
        await db.execute(
            text(
                """
                SELECT count(*) AS total,
                       count(*) FILTER (
                           WHERE NOT EXISTS (
                               SELECT 1 FROM candidate_source_events e
                               WHERE e.candidate_id = c.id
                                 AND COALESCE(e.note, '') NOT LIKE '%' || :undated
                           )
                       ) AS without_source
                FROM candidates c
                WHERE c.created_at >= :since AND c.created_at < :until
                """
            ),
            {"since": since, "until": until, "undated": UNDATED_IMPORT_NOTE_MARK},
        )
    ).one()
    return {
        "portals": [
            {
                "source": key,
                "label": SOURCE_LABELS[key],
                **portal_counts.get(key, _EMPTY_COUNTS),
            }
            for key in PORTAL_SOURCES
        ],
        "portals_total": _row_counts(portals_total),
        "career": [
            {
                "source": key,
                "label": SOURCE_LABELS[key],
                **link_rows.get(key, _EMPTY_COUNTS),
            }
            for key in LINK_SOURCES
        ],
        "career_total": link_rows.get(None, _EMPTY_COUNTS),
        "new_candidates_total": int(coverage.total or 0),
        "new_candidates_without_source": int(coverage.without_source or 0),
    }


async def compute_portal_offers(
    db: AsyncSession,
    *,
    source: str,
    since: datetime,
    until: datetime,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Ogłoszenia jednego portalu z tym samym lejkiem, od najwięcej zgłoszeń."""
    result = await db.execute(
        text(
            f"""
            WITH {_PORTAL_EVENTS},
            f AS (
                SELECT offer, candidate_id, min(captured_at) AS first_at,
                       count(*) AS applications
                FROM ev WHERE source = :source GROUP BY offer, candidate_id
            ),
            {_PORTAL_FLAGS}
            SELECT offer, count(*) AS people, sum(applications) AS applications, {_COUNTS},
                   count(*) OVER () AS total_offers
            FROM flags GROUP BY offer
            ORDER BY sum(applications) DESC, offer
            LIMIT :limit OFFSET :offset
            """
        ),
        {
            **_portal_params(since, until),
            "source": source,
            "limit": limit,
            "offset": offset,
        },
    )
    rows = result.all()
    return {
        "total": int(rows[0].total_offers) if rows else 0,
        "rows": [{"offer": row.offer, **_row_counts(row)} for row in rows],
    }


async def compute_link_breakdown(
    db: AsyncSession, *, source: str, since: datetime, until: datetime
) -> dict[str, Any]:
    """Link ogólny po właścicielu, linki do rekrutacji po rekrutacji."""
    if source == SOURCE_LINK_GENERAL:
        key_column, join, label = (
            "flags.owner_id",
            "LEFT JOIN users u ON u.id = flags.owner_id",
            "u.name",
        )
    else:
        key_column, join, label = (
            "flags.link_job_id",
            "LEFT JOIN jobs j ON j.id = flags.link_job_id",
            "j.title",
        )
    result = await db.execute(
        text(
            f"""
            WITH {_LINK_FLAGS}
            SELECT {key_column} AS key, {label} AS label,
                   count(DISTINCT flags.candidate_id) AS people,
                   count(*) AS applications, {_COUNTS}
            FROM flags {join}
            WHERE flags.source = :source
            GROUP BY {key_column}, {label}
            ORDER BY count(*) DESC, {label}
            """
        ),
        {"since": since, "until": until, "source": source},
    )
    return {
        "rows": [
            {"key": row.key, "label": row.label or "—", **_row_counts(row)}
            for row in result
        ]
    }


async def compute_people(
    db: AsyncSession,
    *,
    source: str,
    metric: str,
    since: datetime,
    until: datetime,
    offer: Optional[str] = None,
    owner_id: Optional[int] = None,
    job_id: Optional[int] = None,
    limit: int = 40,
    offset: int = 0,
) -> dict[str, Any]:
    """Osoby za liczbą: najdalszy etap najpierw, potem najnowsze zgłoszenie."""
    where = _METRIC_WHERE[metric]
    if source in PORTAL_SOURCES:
        statement, params = _portal_people_sql(where, offer, since, until, source)
    else:
        statement, params = _link_people_sql(
            where, metric, owner_id, job_id, since, until, source
        )
    result = await db.execute(
        text(statement),
        {
            **params,
            "stage_rank": _STAGE_RANK,
            "limit": limit,
            "offset": offset,
        },
    )
    rows = result.all()
    return {
        "total": int(rows[0].total) if rows else 0,
        "rows": [
            {
                "candidate_id": row.candidate_id,
                "name": " ".join(
                    part for part in (row.first_name, row.last_name) if part
                ),
                "applied_at": row.first_at.isoformat(),
                "applications": int(row.applications),
                "offer": row.offer,
                "link_owner": row.link_owner,
                "link_job_id": row.link_job_id,
                "link_job_title": row.link_job_title,
                "stage": row.stage,
                "job_id": row.job_id,
                "job_title": row.job_title,
            }
            for row in rows
        ],
    }


_FURTHEST_STAGE = """
    LEFT JOIN LATERAL (
        SELECT cs.stage::text AS stage, cs.job_id, j.title AS job_title
        FROM candidate_stages cs
        JOIN jobs j ON j.id = cs.job_id
        WHERE cs.candidate_id = flags.candidate_id
          AND cs.stage::text <> 'posting'
          AND {window}
          AND {excluded}
        ORDER BY array_position(CAST(:stage_rank AS text[]), cs.stage::text) DESC NULLS LAST,
                 cs.moved_at DESC
        LIMIT 1
    ) st ON TRUE
"""

_PAGE = """
    ORDER BY array_position(CAST(:stage_rank AS text[]), st.stage) DESC NULLS LAST,
             flags.first_at DESC, flags.candidate_id
    LIMIT :limit OFFSET :offset
"""


def _portal_people_sql(
    where: str,
    offer: Optional[str],
    since: datetime,
    until: datetime,
    source: str,
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {**_portal_params(since, until), "source": source}
    offer_filter = ""
    if offer is not None:
        offer_filter = "AND offer = :offer"
        params["offer"] = offer
    stage = _FURTHEST_STAGE.format(
        window="cs.moved_at >= flags.first_at", excluded=excluded_hired_sql("cs")
    )
    return (
        f"""
        WITH {_PORTAL_EVENTS},
        f AS (
            SELECT candidate_id, min(captured_at) AS first_at, count(*) AS applications,
                   (array_agg(offer ORDER BY captured_at DESC))[1] AS offer
            FROM ev WHERE source = :source {offer_filter}
            GROUP BY candidate_id
        ),
        {_PORTAL_FLAGS}
        SELECT flags.candidate_id, flags.first_name, flags.last_name, flags.first_at,
               flags.applications, NULLIF(flags.offer, '') AS offer,
               NULL::text AS link_owner, NULL::int AS link_job_id,
               NULL::text AS link_job_title,
               st.stage, st.job_id, st.job_title, count(*) OVER () AS total
        FROM flags {stage}
        WHERE {where}
        {_PAGE}
        """,
        params,
    )


def _link_people_sql(
    where: str,
    metric: str,
    owner_id: Optional[int],
    job_id: Optional[int],
    since: datetime,
    until: datetime,
    source: str,
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {"since": since, "until": until, "source": source}
    filters = ["flags.source = :source", where]
    if owner_id is not None:
        filters.append("flags.owner_id = :owner_id")
        params["owner_id"] = owner_id
    if job_id is not None:
        filters.append("flags.link_job_id = :link_job_id")
        params["link_job_id"] = job_id
    stage = _FURTHEST_STAGE.format(
        window=(
            "(flags.link_job_id IS NULL OR cs.job_id = flags.link_job_id) "
            "AND cs.moved_at >= flags.first_at - INTERVAL '1 hour'"
        ),
        excluded=excluded_hired_sql("cs"),
    )
    # „Osoby” liczą kandydata raz, pozostałe liczby są po zgłoszeniu, jak w tabeli.
    one_per_person = ""
    if metric == "people":
        one_per_person = """
            AND (flags.candidate_id, flags.first_at) IN (
                SELECT candidate_id, min(first_at) FROM flags
                WHERE source = :source GROUP BY candidate_id
            )
        """
    return (
        f"""
        WITH {_LINK_FLAGS}
        SELECT flags.candidate_id, c.name AS first_name, c.lastname AS last_name,
               flags.first_at, 1 AS applications, NULL::text AS offer,
               u.name AS link_owner, flags.link_job_id,
               lj.title AS link_job_title,
               st.stage, st.job_id, st.job_title, count(*) OVER () AS total
        FROM flags
        JOIN candidates c ON c.id = flags.candidate_id
        LEFT JOIN users u ON u.id = flags.owner_id
        LEFT JOIN jobs lj ON lj.id = flags.link_job_id
        {stage}
        WHERE {" AND ".join(filters)} {one_per_person}
        {_PAGE}
        """,
        params,
    )
