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
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


def as_dict(item: LinkResult) -> dict[str, Any]:
    data = asdict(item)
    for key in ("token", "extra", "revoked", "expires_at"):
        data.pop(key, None)
    return {**data, **item.extra}
