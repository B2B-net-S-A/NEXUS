"""Bramka integracji: kto od tokenu OAuth wchodzi na Tablicę (06.10.2026).

Decyzja 30.09.2026 („dopasowania z portali NIE zakładają kart”) obejmowała
wyłącznie żądania z polem ``auto_match``. Integracja BEZ niego dalej zakładała
kartę w „Ogłoszeniach” — tak scraper od 01.10 do 05.10 zostawił 357 kart
(audyt 06.10.2026). Od teraz integracja wstawia osobę na Tablicę TYLKO wtedy,
gdy jest dowód, że ta osoba zgłosiła się do TEJ rekrutacji:

* zgłoszenie z formularza (``application_submissions``: ``matched_candidate_id``
  + ``job_id``),
* zdarzenie źródła z ogłoszenia (``candidate_source_events``: ``job_id``,
  kanał ``posting``),
* notatka z odpowiedziami z formularza aplikacji (``notes.kind =
  'application_form'`` z tym ``job_id``).

Bez dowodu osoba trafia do „Do przejrzenia” jako propozycja ``job_board``
(``proposals_bulk.propose_candidates_for_job``). Człowiek dodaje jak dotąd.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_EVIDENCE_SQL = text(
    """
    SELECT s.matched_candidate_id AS candidate_id
    FROM application_submissions s
    WHERE s.job_id = :job_id AND s.matched_candidate_id = ANY(:ids)
    UNION
    SELECT e.candidate_id
    FROM candidate_source_events e
    WHERE e.job_id = :job_id AND e.candidate_id = ANY(:ids)
      AND e.channel = 'posting'
    UNION
    SELECT n.candidate_id
    FROM notes n
    WHERE n.job_id = :job_id AND n.candidate_id = ANY(:ids)
      AND n.kind = 'application_form'
    """
)


async def candidates_with_application_evidence(
    db: AsyncSession, *, job_id: int, candidate_ids: Iterable[int]
) -> set[int]:
    """Osoby z dowodem zgłoszenia do tej rekrutacji (podzbiór ``candidate_ids``)."""
    ids = sorted({int(c) for c in candidate_ids})
    if not ids:
        return set()
    rows = await db.execute(_EVIDENCE_SQL, {"job_id": job_id, "ids": ids})
    return {int(r[0]) for r in rows.all() if r[0] is not None}


__all__ = ["candidates_with_application_evidence"]
