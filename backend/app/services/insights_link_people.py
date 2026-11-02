"""Raport „kto co przyniósł” z linków (makieta D, decyzja Artura 02.11.2026).

Te same reguły co „Wyniki” właściciela linku (``career_link_results``): zgłoszenia
z ``activities.applied_via_invite`` w oknie, etap liczony po zgłoszeniu w rekrutacji
linku (link ogólny: w dowolnej). Wejścia w oknie liczą się z dziennych zapisów
(0640), które zaczynają się w dniu wdrożenia; ``visits_total`` to licznik linku.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SQL = """
WITH links AS (
    SELECT l.token, l.created_by AS owner_id, l.kind, l.job_id, l.revoked, l.visit_count,
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
           a.created_at AS applied_at,
           COALESCE(a.details->>'was_duplicate', 'false') = 'true' AS was_duplicate
    FROM activities a
    WHERE a.action = 'applied_via_invite'
      AND a.entity_type = 'candidate'
      AND a.created_at >= :since AND a.created_at < :until
    ORDER BY a.details->>'invite_token_sha256', a.entity_id, a.created_at
),
reached AS (
    SELECT links.owner_id, links.kind, apps.candidate_id, apps.was_duplicate,
           BOOL_OR(cs.id IS NOT NULL AND cs.stage::text <> 'posting') AS in_process,
           BOOL_OR(cs.stage::text = 'cv_sent') AS cv_sent,
           BOOL_OR(cs.stage::text = 'hired') AS hired
    FROM apps
    JOIN links ON links.link_key = apps.link_key
    LEFT JOIN candidate_stages cs
      ON cs.candidate_id = apps.candidate_id
     AND (links.job_id IS NULL OR cs.job_id = links.job_id)
     AND cs.moved_at >= apps.applied_at - INTERVAL '1 hour'
    GROUP BY links.owner_id, links.kind, apps.link_key, apps.candidate_id, apps.was_duplicate
),
by_owner_apps AS (
    SELECT owner_id,
           count(*) FILTER (WHERE kind = 'recruiter') AS applications_general,
           count(*) FILTER (WHERE kind <> 'recruiter') AS applications_job,
           count(*) FILTER (WHERE NOT was_duplicate) AS new_candidates,
           count(*) FILTER (WHERE in_process) AS in_process,
           count(*) FILTER (WHERE cv_sent) AS cv_sent,
           count(*) FILTER (WHERE hired) AS hired
    FROM reached
    GROUP BY owner_id
),
by_owner_visits AS (
    SELECT links.owner_id, COALESCE(sum(d.visits), 0) AS visits
    FROM candidate_invite_link_visit_days d
    JOIN links ON links.token = d.link_token
    WHERE d.day >= :since_day AND d.day < :until_day
    GROUP BY links.owner_id
),
by_owner_links AS (
    SELECT owner_id,
           BOOL_OR(kind = 'recruiter' AND NOT revoked) AS general_link,
           count(*) FILTER (WHERE kind <> 'recruiter' AND NOT revoked) AS job_links,
           COALESCE(sum(visit_count), 0) AS visits_total
    FROM links
    GROUP BY owner_id
)
SELECT u.id AS user_id, u.name, o.general_link, o.job_links, o.visits_total,
       COALESCE(v.visits, 0) AS visits,
       COALESCE(a.applications_general, 0) AS applications_general,
       COALESCE(a.applications_job, 0) AS applications_job,
       COALESCE(a.new_candidates, 0) AS new_candidates,
       COALESCE(a.in_process, 0) AS in_process,
       COALESCE(a.cv_sent, 0) AS cv_sent,
       COALESCE(a.hired, 0) AS hired
FROM by_owner_links o
JOIN users u ON u.id = o.owner_id
LEFT JOIN by_owner_apps a ON a.owner_id = o.owner_id
LEFT JOIN by_owner_visits v ON v.owner_id = o.owner_id
ORDER BY COALESCE(a.applications_general, 0) + COALESCE(a.applications_job, 0) DESC,
         o.visits_total DESC, u.name
"""

_TOTALS_SQL = """
SELECT count(*) FILTER (WHERE NOT revoked) AS links,
       count(*) FILTER (WHERE NOT revoked AND COALESCE(visit_count, 0) = 0) AS links_without_visits,
       COALESCE(sum(visit_count), 0) AS visits_total,
       (SELECT min(day) FROM candidate_invite_link_visit_days) AS visits_tracked_from
FROM candidate_invite_links
"""


async def compute_link_people(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    since_day: date,
    until_day: date,
) -> dict[str, Any]:
    rows = [
        dict(r)
        for r in (
            await db.execute(
                text(_SQL),
                {
                    "since": since,
                    "until": until,
                    "since_day": since_day,
                    "until_day": until_day,
                },
            )
        ).mappings()
    ]
    totals = dict((await db.execute(text(_TOTALS_SQL))).mappings().one())
    return {
        "rows": rows,
        "totals": {
            "links": int(totals["links"] or 0),
            "links_without_visits": int(totals["links_without_visits"] or 0),
            "visits_total": int(totals["visits_total"] or 0),
            "visits": sum(int(r["visits"]) for r in rows),
            "applications": sum(
                int(r["applications_general"]) + int(r["applications_job"])
                for r in rows
            ),
        },
        "visits_tracked_from": (
            totals["visits_tracked_from"].isoformat()
            if totals["visits_tracked_from"]
            else None
        ),
    }
