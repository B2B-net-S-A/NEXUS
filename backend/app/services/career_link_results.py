"""Wyniki linków rekrutera — zakładka „Wyniki” w oknie „Udostępnij” (etap 4).

Źródło zgłoszeń: ``activities.applied_via_invite`` (``user_id`` = właściciel
linku, ``details.invite_token_sha256`` = klucz linku, ``was_duplicate`` = osoba
była już w bazie). Ten sam zapis liczy kolumnę „Z linków” w aktywności zespołu
(``insights_team_activity``), więc obie liczby się zgadzają.

Lejek: osoba ze zgłoszenia liczy się na etapie, gdy PO zgłoszeniu pojawiła się
na nim w rekrutacji linku (link ogólny: w dowolnej rekrutacji). Wejścia to
licznik od początku istnienia linku (``visit_count``) — dat wejść nie
zapisujemy.

Makieta: https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h (plansza 4).

Lista osób (``link_people``, decyzja Artura 02.11.2026, makieta A
https://claude.ai/artifact/BcevDUToiG7AGHfgY86T5P): to samo źródło i ta sama
reguła etapu co lejek, więc liczba zgłoszeń i długość listy się zgadzają.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.my_people import my_people_membership

COUNT_KEYS = (
    "applications",
    "new_candidates",
    "existing_candidates",
    "in_process",
    "verified",
    "cv_sent",
    "hired",
)

# Etap po zgłoszeniu: AI może dodać osobę do „Nowi” po kilku minutach, a przy
# wyłączonym przeglądzie karta powstaje w tej samej transakcji (chwilę PRZED
# zapisem zdarzenia) — stąd zapas godziny wstecz.
_RESULTS_SQL = """
WITH links AS (
    SELECT l.token,
           COALESCE(
               l.token_sha256,
               encode(sha256(convert_to(l.token, 'UTF8')), 'hex')
           ) AS link_key,
           l.kind, l.slug, l.job_id, l.visit_count, l.revoked, l.expires_at
    FROM candidate_invite_links l
    WHERE l.created_by = :owner
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
      AND a.user_id = :owner
      AND (CAST(:since AS timestamptz) IS NULL OR a.created_at >= :since)
    ORDER BY a.details->>'invite_token_sha256', a.entity_id, a.created_at
),
reached AS (
    SELECT apps.link_key, apps.candidate_id, apps.was_duplicate,
           BOOL_OR(cs.id IS NOT NULL AND cs.stage::text <> 'posting') AS in_process,
           BOOL_OR(
               cs.stage::text = 'verified'
               AND cs.verification_status::text = 'active'
           ) AS verified,
           BOOL_OR(cs.stage::text = 'cv_sent') AS cv_sent,
           BOOL_OR(cs.stage::text = 'hired') AS hired
    FROM apps
    JOIN links ON links.link_key = apps.link_key
    LEFT JOIN candidate_stages cs
      ON cs.candidate_id = apps.candidate_id
     AND (links.job_id IS NULL OR cs.job_id = links.job_id)
     AND cs.moved_at >= apps.applied_at - INTERVAL '1 hour'
    GROUP BY apps.link_key, apps.candidate_id, apps.was_duplicate
)
SELECT links.token, links.kind, links.slug, links.job_id, links.visit_count,
       links.revoked, links.expires_at,
       count(reached.candidate_id) AS applications,
       count(*) FILTER (WHERE reached.candidate_id IS NOT NULL
                          AND NOT reached.was_duplicate) AS new_candidates,
       count(*) FILTER (WHERE reached.was_duplicate) AS existing_candidates,
       count(*) FILTER (WHERE reached.in_process) AS in_process,
       count(*) FILTER (WHERE reached.verified) AS verified,
       count(*) FILTER (WHERE reached.cv_sent) AS cv_sent,
       count(*) FILTER (WHERE reached.hired) AS hired
FROM links
LEFT JOIN reached ON reached.link_key = links.link_key
GROUP BY links.token, links.kind, links.slug, links.job_id, links.visit_count,
         links.revoked, links.expires_at
"""

# Bezpiecznik odpowiedzi, nie limit biznesowy; ``truncated`` mówi o przycięciu.
MAX_PEOPLE = 500

# Etap „teraz”: najnowszy wiersz po zgłoszeniu, w rekrutacji linku (link ogólny:
# w dowolnej) — ten sam warunek co ``reached`` w lejku wyżej.
_PEOPLE_SQL = """
WITH links AS (
    SELECT COALESCE(
               l.token_sha256,
               encode(sha256(convert_to(l.token, 'UTF8')), 'hex')
           ) AS link_key,
           l.kind, l.slug, l.job_id
    FROM candidate_invite_links l
    WHERE l.created_by = :owner
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
      AND a.user_id = :owner
      AND (CAST(:since AS timestamptz) IS NULL OR a.created_at >= :since)
    ORDER BY a.details->>'invite_token_sha256', a.entity_id, a.created_at
)
SELECT apps.candidate_id, apps.applied_at, apps.was_duplicate,
       links.kind, links.slug, links.job_id,
       COALESCE(link_job.working_title, link_job.title) AS job_title,
       TRIM(CONCAT(c.name, ' ', c.lastname)) AS full_name,
       now_stage.stage AS current_stage,
       now_stage.job_id AS current_job_id,
       COALESCE(now_job.working_title, now_job.title) AS current_job_title,
       screening.status AS screening_status,
       screening.outcome AS screening_outcome,
       count(*) OVER () AS total
FROM apps
JOIN links ON links.link_key = apps.link_key
JOIN candidates c ON c.id = apps.candidate_id
LEFT JOIN jobs link_job ON link_job.id = links.job_id
LEFT JOIN LATERAL (
    SELECT cs.stage::text AS stage, cs.job_id
    FROM candidate_stages cs
    WHERE cs.candidate_id = apps.candidate_id
      AND (links.job_id IS NULL OR cs.job_id = links.job_id)
      AND cs.stage::text <> 'posting'
      AND cs.moved_at >= apps.applied_at - INTERVAL '1 hour'
    ORDER BY cs.moved_at DESC, cs.id DESC
    LIMIT 1
) now_stage ON TRUE
LEFT JOIN jobs now_job ON now_job.id = now_stage.job_id
LEFT JOIN LATERAL (
    SELECT s.status::text AS status, s.outcome::text AS outcome
    FROM application_screenings s
    WHERE s.candidate_id = apps.candidate_id
      AND links.job_id IS NOT NULL
      AND s.job_id = links.job_id
    ORDER BY s.created_at DESC
    LIMIT 1
) screening ON TRUE
ORDER BY apps.applied_at DESC, apps.candidate_id
LIMIT :limit
"""

# Linki jednej rekrutacji w zespole (makieta C, 02.11.2026). Zgłoszenia jak
# w lejku: unikalne osoby, właściciel linku w ``user_id``.
_JOB_TEAM_LINKS_SQL = """
SELECT l.created_by AS owner_id, u.name AS owner_name, l.slug, l.label, l.created_at,
       l.visit_count AS visits, l.revoked, l.expires_at,
       (
           SELECT count(DISTINCT a.entity_id)
           FROM activities a
           WHERE a.action = 'applied_via_invite'
             AND a.entity_type = 'candidate'
             AND a.user_id = l.created_by
             AND a.details->>'invite_token_sha256' = COALESCE(
                 l.token_sha256, encode(sha256(convert_to(l.token, 'UTF8')), 'hex')
             )
       ) AS applications
FROM candidate_invite_links l
JOIN users u ON u.id = l.created_by
WHERE l.job_id = :job_id AND l.kind = 'job'
ORDER BY l.revoked, l.visit_count DESC, l.created_at DESC
"""


@dataclass
class LinkResult:
    token: str
    kind: str
    slug: Optional[str]
    job_id: Optional[int]
    visits: int
    revoked: bool = False
    expires_at: Optional[datetime] = None
    applications: int = 0
    new_candidates: int = 0
    existing_candidates: int = 0
    in_process: int = 0
    verified: int = 0
    cv_sent: int = 0
    hired: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {key: int(getattr(self, key)) for key in COUNT_KEYS}


async def link_results(
    db: AsyncSession, owner_id: int, since: Optional[datetime]
) -> list[LinkResult]:
    """Wiersz na każdy link osoby (także wycofany), z liczbami w oknie."""
    rows = (
        await db.execute(text(_RESULTS_SQL), {"owner": owner_id, "since": since})
    ).mappings()
    return [
        LinkResult(
            token=r["token"],
            kind=r["kind"] or "job",
            slug=r["slug"],
            job_id=r["job_id"],
            visits=int(r["visit_count"] or 0),
            revoked=bool(r["revoked"]),
            expires_at=r["expires_at"],
            **{key: int(r[key] or 0) for key in COUNT_KEYS},
        )
        for r in rows
    ]


async def link_people(
    db: AsyncSession, owner_id: int, since: Optional[datetime]
) -> tuple[list[dict[str, Any]], int]:
    """Kto zgłosił się z linków osoby, najnowsi pierwsi, i łączna liczba zgłoszeń."""
    rows = [
        dict(r)
        for r in (
            await db.execute(
                text(_PEOPLE_SQL),
                {"owner": owner_id, "since": since, "limit": MAX_PEOPLE},
            )
        ).mappings()
    ]
    total = int(rows[0]["total"]) if rows else 0
    listed = await my_people_membership(
        db, owner_id, [int(r["candidate_id"]) for r in rows]
    )
    return (
        [{**row, "in_my_people": int(row["candidate_id"]) in listed} for row in rows],
        total,
    )


async def job_team_links(db: AsyncSession, job_id: int) -> list[dict[str, Any]]:
    """Wszystkie linki rekrutacji: kto je ma i co przyniosły."""
    return [
        dict(row)
        for row in (
            await db.execute(text(_JOB_TEAM_LINKS_SQL), {"job_id": job_id})
        ).mappings()
    ]


def as_dict(item: LinkResult) -> dict[str, Any]:
    data = asdict(item)
    for key in ("token", "extra", "revoked", "expires_at"):
        data.pop(key, None)
    return {**data, **item.extra}
