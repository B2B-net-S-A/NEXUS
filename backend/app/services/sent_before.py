"""„Wysłany wcześniej” — osoba, którą w ostatnim roku wysłaliśmy do klienta
w innej rekrutacji (decyzja Artura z 20.11.2026, Z1 i Z3).

Raport: https://claude.ai/artifact/2jac9hsRwpqE4yGpERqXDx. Z 325 CV wysłanych
09–19.11 aż 204 to osoby już przez nas sprawdzone, a wśród kart od systemu
osoba wysłana wcześniej trafia do klienta w 12,2% (wszystkie karty 7,9%).
Sam screening bez wysyłki nie podnosi trafności (3,0%), więc liczy się
wyłącznie etap „CV wysłane”. Silnik szukał dotąd po treści CV i takie osoby
spoza puli 150 nie wchodziły wcale; z 89 sprawdzonych wysłanych ręcznie 53
miało w ostatnim przeglądzie wynik od 50%.

Co z tego wynika w silniku:

* pula przeglądu dokłada do ``POOL_EXTRA`` takich osób od ``MIN_SCORE``
  ponad 150 najlepszych (``auto_full_review.refresh_autofill_pool``);
* porcja i dopełnianie biorą je od ``MIN_SCORE`` zamiast progu porcji;
* kolejność dostaje ``known_queue_points.SENT_POINTS``;
* budżet i odległość od biura nie wycinają ich, tylko ostrzegają
  (``new_column_autofill._by_rules``);
* karta pokazuje, gdzie i kiedy osoba była wysłana.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import select, text

DAYS = 365
# Próg wyniku dla osób wysłanych wcześniej: 53 z 89 sprawdzonych, wysłanych
# ręcznie 09–19.11, miało od 50% (31 od 65%, poniżej 50% żadna).
MIN_SCORE = 50.0
# Ile takich osób pula przeglądu bierze ponad 150 najlepszych.
POOL_EXTRA = 30
EVIDENCE_KEY = "sent_before"
META_KEY = "sent_before"


@dataclass(frozen=True)
class SentBefore:
    count: int
    last_days: int
    last_job_title: str

    def as_dict(self) -> dict:
        return asdict(self)


def is_sent_before(evidence_or_meta: object) -> bool:
    """Flaga w dowodach puli albo w migawce karty."""
    return isinstance(evidence_or_meta, dict) and bool(
        evidence_or_meta.get(EVIDENCE_KEY)
    )


def sent_elsewhere_select(job_id: Optional[int], *, now: datetime):
    """``SELECT candidate_id`` osób wysłanych do klienta w innej rekrutacji
    w ostatnich ``DAYS`` dniach — do zawężeń w zapytaniach silnika."""
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    query = select(CandidateStage.candidate_id).where(
        CandidateStage.stage == PipelineStage.cv_sent,
        CandidateStage.moved_at >= now - timedelta(days=DAYS),
    )
    if job_id is not None:
        query = query.where(CandidateStage.job_id != job_id)
    return query


async def facts_for(
    db,
    *,
    job_id: Optional[int],
    candidate_ids: Iterable[int],
    now: datetime,
) -> dict[int, SentBefore]:
    """Osoby wysłane do klienta w innej rekrutacji w ostatnich ``DAYS`` dniach.

    ``count`` liczy rekrutacje, ``last_*`` opisuje ostatnią wysyłkę. Osób bez
    wysyłki nie ma w wyniku."""
    ids = sorted({int(cid) for cid in candidate_ids})
    if not ids:
        return {}
    rows = await db.execute(
        text(
            """
            SELECT cs.candidate_id, cs.job_id, MAX(cs.moved_at) AS sent_at,
                   MAX(j.title) AS title
            FROM candidate_stages cs
            JOIN jobs j ON j.id = cs.job_id
            WHERE cs.candidate_id = ANY(:ids)
              AND cs.stage::text = 'cv_sent'
              AND cs.moved_at >= :since
              AND (CAST(:job AS integer) IS NULL OR cs.job_id <> CAST(:job AS integer))
            GROUP BY cs.candidate_id, cs.job_id
            """
        ),
        {"ids": ids, "since": now - timedelta(days=DAYS), "job": job_id},
    )
    by_person: dict[int, list[tuple[datetime, str]]] = {}
    for cid, _jid, sent_at, title in rows.all():
        by_person.setdefault(int(cid), []).append((sent_at, title or ""))
    out: dict[int, SentBefore] = {}
    for cid, sends in by_person.items():
        last_at, last_title = max(sends, key=lambda s: s[0])
        out[cid] = SentBefore(
            count=len(sends),
            last_days=max(0, (now - last_at).days),
            last_job_title=last_title,
        )
    return out


async def ids_for(
    db, *, job_id: Optional[int], candidate_ids: Iterable[int], now: datetime
) -> set[int]:
    return set(await facts_for(db, job_id=job_id, candidate_ids=candidate_ids, now=now))
