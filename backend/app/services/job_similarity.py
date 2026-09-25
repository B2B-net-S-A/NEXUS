"""Podobne rekrutacje, przepięcia i status requestu (migracja 0341).

Decyzje Artura (22.09.2026):

* **Przepięcie** = osoba wysłana do klienta (etap „CV wysłane" albo dalszy
  u klienta) w rekrutacji wskazanej jako podobna. Trafia do „Do przejrzenia"
  jako propozycja ``reassign`` — nigdy wprost do pipeline'u.
* Podobne rekrutacje wskazuje rekruter albo Delivery Lead (sugestie systemu
  albo własny wybór). Połączenie działa DALEJ: kolejna osoba wysłana w jednej
  rekrutacji przepina się do drugiej sama (:func:`on_candidate_sent`).
* **Status requestu** jest liczony (:func:`request_status_subquery`) —
  „Szukamy" trwa, dopóki Delivery Lead nie oznaczy „Mamy championa".

Sugestie liczy prosta, deterministyczna miara: wspólne must-have, wspólne
słowa tytułu i ta sama kategoria kompetencji. Pula (CAŁA historia, także
zamknięte i archiwum z Traffita — tam są osoby już wysłane; decyzja Artura
24.09.2026, do tego dnia 18 miesięcy) trzymana jest
w pamięci procesu przez kilka minut, a kandydaci do porównania wybierani są
przez indeks odwrócony, więc lista rekrutacji nie porównuje każdej z każdą.

Żadna funkcja tutaj nie commituje — transakcja należy do wołającego.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import DEFAULT_TZ
from app.models.job import Job, JobStatus
from app.models.job_similar_link import JobSimilarLink
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage

logger = logging.getLogger(__name__)

# Osoba „była u klienta": od wysłania CV wzwyż.
CLIENT_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.negotiation,
    PipelineStage.onboarding,
    PipelineStage.hired,
)
# Przepinamy wysłanych, ale nie zatrudnionych (ci pracują).
REASSIGN_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.negotiation,
)
CONTRACT_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.acceptance,
    PipelineStage.negotiation,
    PipelineStage.onboarding,
)

REQUEST_STATUSES = (
    "closed",
    "filled",
    "contract",
    "champion",
    "incomplete",
    "searching",
)

# Stan requestu w JEDNYM rzędzie pigułek listy `/jobs` (25.09.2026): status
# requestu i stan pracy złożone w jedną wartość na rekrutację. Wartości się
# wykluczają, więc kilka pigułek naraz to LUB (samo `request_status` +
# `work_state` łączyły się przez AND). Kolejność = pierwszeństwo w CASE.
REQUEST_STAGES = (
    "closed",
    "filled",
    "contract",
    "champion",
    "incomplete",
    "finished",
    "client_silent",
    "to_review",
    "searching",
)

MIN_SCORE = 55
MAX_SUGGESTIONS = 5
_POOL_TTL_SECONDS = 300

_STOPWORDS = frozenset(
    {
        "senior",
        "junior",
        "mid",
        "regular",
        "lead",
        "principal",
        "staff",
        "starszy",
        "młodszy",
        "i",
        "oraz",
        "and",
        "the",
        "of",
        "w",
        "z",
        "na",
        "do",
        "dla",
        "ii",
        "iii",
        "iv",
        "sr",
        "jr",
        "b2b",
        "uop",
    }
)
_TOKEN_RE = re.compile(r"[a-ząćęłńóśźż0-9+#.]+", re.IGNORECASE)


def title_tokens(title: Optional[str]) -> frozenset[str]:
    if not title:
        return frozenset()
    out = set()
    for raw in _TOKEN_RE.findall(title.casefold()):
        token = raw.strip(".")
        if len(token) < 2 or token in _STOPWORDS or token.isdigit():
            continue
        out.add(token)
    return frozenset(out)


def skill_set(raw: Any, champion_profile: Any = None) -> frozenset[str]:
    """Must-have rekrutacji do porównania: kolumna ∪ stack MUST z profilu Championa.

    Przy wczytanej taksonomii zbiór to KANONICZNE nazwy technologii
    (``ReactJS`` i ``React`` to jedno, a zdania opisowe jak „10 lat w IT"
    odpadają). Do 22.09.2026 porównywaliśmy surowe napisy z samej kolumny —
    dwie rekrutacje testerskie z listami „Testy manualne" / „testowanie
    manualne" miały Jaccard 0, a stack z 1137 profili Championa nie trafiał do
    silnika wcale. Zmierzone na produkcji: podpowiedź dla 195 z 326 otwartych
    rekrutacji zamiast 92, przy tym samym wzorze i progu.

    Bez taksonomii (testy, start przed jej wczytaniem) — surowe napisy
    kolumny, jak przedtem.
    """
    from app.services import champion_view  # noqa: PLC0415
    from app.services.skill_normalize import (  # noqa: PLC0415
        TECH_CANONICALS,
        canonical_of,
        is_taxonomy_technology,
        iter_skill_names,
    )

    column = [n for n in iter_skill_names(raw) if n.strip()]
    if not TECH_CANONICALS:
        return frozenset(n.strip().casefold() for n in column)
    stack = champion_view.stack(champion_profile or {}).get("must")
    names = column + [n for n in iter_skill_names(stack) if n.strip()]
    return frozenset(canonical_of(n) for n in names if is_taxonomy_technology(n))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity_score(
    a_skills: frozenset[str],
    a_title: frozenset[str],
    a_cc: Optional[int],
    b_skills: frozenset[str],
    b_title: frozenset[str],
    b_cc: Optional[int],
    *,
    a_client: Optional[int] = None,
    b_client: Optional[int] = None,
) -> int:
    """0–100. Bez must-have po którejś stronie liczy tytuł i kategorię.

    Ten sam klient waży tyle, co ta sama kategoria kompetencji (bierzemy
    lepsze z dwóch, nie sumę — klient i kategoria bez wspólnego tytułu nie
    przechodzą progu). Do 25.09.2026 klient nie wchodził do miary wcale:
    „Analityk Systemowy AI/LLM (ZOB-3006)" (kategoria Infra) i „PKO BP:
    Analityk Systemowy / ZOB-1725" (kategoria PM & BA) tego samego klienta
    dostawały 30 pkt przy progu 55, a to z tamtej rekrutacji są osoby,
    które klient już zna.
    """
    title = _jaccard(a_title, b_title)
    same_cc = a_cc is not None and a_cc == b_cc
    same_client = a_client is not None and a_client == b_client
    context = 1.0 if same_cc or same_client else 0.0
    if a_skills and b_skills:
        score = 0.55 * _jaccard(a_skills, b_skills) + 0.30 * title + 0.15 * context
    else:
        score = 0.70 * title + 0.30 * context
    return round(score * 100)


@dataclass(frozen=True)
class PoolJob:
    id: int
    title: str
    client_id: Optional[int]
    reference_number: Optional[str]
    status: str
    competence_category_id: Optional[int]
    skills: frozenset[str]
    tokens: frozenset[str]
    created_at: Optional[datetime]


@dataclass
class _Pool:
    loaded_at: float = 0.0
    jobs: dict[int, PoolJob] = field(default_factory=dict)
    index: dict[str, set[int]] = field(default_factory=dict)


_pool = _Pool()


def reset_pool_cache() -> None:
    """Dla testów i po zmianie rekrutacji, gdy liczy się świeżość."""
    global _pool
    _pool = _Pool()


async def _load_pool(db: AsyncSession) -> _Pool:
    global _pool
    if _pool.jobs and time.monotonic() - _pool.loaded_at < _POOL_TTL_SECONDS:
        return _pool
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.client_id,
                Job.reference_number,
                Job.status,
                Job.competence_category_id,
                Job.must_skills,
                Job.champion_profile,
                Job.created_at,
            ).where(Job.client_id.is_not(None))
        )
    ).all()
    pool = _Pool(loaded_at=time.monotonic())
    for row in rows:
        item = PoolJob(
            id=row.id,
            title=row.title or "",
            client_id=row.client_id,
            reference_number=row.reference_number,
            status=row.status.value
            if hasattr(row.status, "value")
            else str(row.status),
            competence_category_id=row.competence_category_id,
            skills=skill_set(row.must_skills, row.champion_profile),
            tokens=title_tokens(row.title),
            created_at=row.created_at,
        )
        pool.jobs[item.id] = item
        for key in item.skills | {f"t:{t}" for t in item.tokens}:
            pool.index.setdefault(key, set()).add(item.id)
    _pool = pool
    return pool


def _rank(pool: _Pool, ref: PoolJob, exclude: set[int]) -> list[tuple[int, int]]:
    candidates: set[int] = set()
    for key in ref.skills | {f"t:{t}" for t in ref.tokens}:
        candidates |= pool.index.get(key, set())
    scored = []
    for job_id in candidates:
        if job_id in exclude or job_id == ref.id:
            continue
        other = pool.jobs[job_id]
        score = similarity_score(
            ref.skills,
            ref.tokens,
            ref.competence_category_id,
            other.skills,
            other.tokens,
            other.competence_category_id,
            a_client=ref.client_id,
            b_client=other.client_id,
        )
        if score >= MIN_SCORE:
            scored.append((job_id, score))
    scored.sort(key=lambda pair: (-pair[1], -pair[0]))
    return scored


def _as_pool_job(job: Any) -> PoolJob:
    status = getattr(job, "status", None)
    return PoolJob(
        id=getattr(job, "id", None) or 0,
        title=getattr(job, "title", "") or "",
        client_id=getattr(job, "client_id", None),
        reference_number=getattr(job, "reference_number", None),
        status=status.value if hasattr(status, "value") else str(status or ""),
        competence_category_id=getattr(job, "competence_category_id", None),
        skills=skill_set(
            getattr(job, "must_skills", None), getattr(job, "champion_profile", None)
        ),
        tokens=title_tokens(getattr(job, "title", None)),
        created_at=getattr(job, "created_at", None),
    )


async def linked_job_ids(
    db: AsyncSession, job_ids: Sequence[int]
) -> dict[int, list[int]]:
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(JobSimilarLink.job_id, JobSimilarLink.similar_job_id)
            .where(JobSimilarLink.job_id.in_(list(job_ids)))
            .order_by(JobSimilarLink.created_at, JobSimilarLink.id)
        )
    ).all()
    out: dict[int, list[int]] = {}
    for job_id, other in rows:
        out.setdefault(job_id, []).append(other)
    return out


async def sent_counts(db: AsyncSession, job_ids: Iterable[int]) -> dict[int, int]:
    """Ile RÓŻNYCH osób w rekrutacji dotarło do klienta (od „CV wysłane")."""
    ids = list(set(job_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(
                CandidateStage.job_id.in_(ids), CandidateStage.stage.in_(CLIENT_STAGES)
            )
            .group_by(CandidateStage.job_id)
        )
    ).all()
    return {job_id: int(n) for job_id, n in rows}


async def reassignable_counts(
    db: AsyncSession, target_job_id: int, source_job_ids: Iterable[int]
) -> tuple[dict[int, int], int]:
    """Ile osób z każdej rekrutacji źródłowej DA SIĘ przepiąć do celu
    i ile to różnych osób łącznie.

    Ta sama reguła co ``selectable`` w :func:`sent_people`: wiersz
    w ``REASSIGN_STAGES``, bez zatrudnienia w źródle i bez żadnego wiersza
    w celu. Na tej liczbie stoją odznaka w nagłówku, pasek w „Nowych”
    i „Najbliższy krok” — suma ``sent_count`` liczyła też zatrudnionych
    i obecnych, więc krok potrafił wisieć bez nikogo do przepięcia.
    """
    sources = [sid for sid in set(source_job_ids) if sid != target_job_id]
    if not sources:
        return {}, 0
    hired = aliased(CandidateStage)
    in_target = aliased(CandidateStage)
    rows = (
        await db.execute(
            select(CandidateStage.job_id, CandidateStage.candidate_id)
            .distinct()
            .where(
                CandidateStage.job_id.in_(sources),
                CandidateStage.stage.in_(REASSIGN_STAGES),
                ~exists().where(
                    hired.candidate_id == CandidateStage.candidate_id,
                    hired.job_id == CandidateStage.job_id,
                    hired.stage == PipelineStage.hired,
                ),
                ~exists().where(
                    in_target.candidate_id == CandidateStage.candidate_id,
                    in_target.job_id == target_job_id,
                ),
            )
        )
    ).all()
    per_job: dict[int, int] = {}
    people: set[int] = set()
    for job_id, candidate_id in rows:
        per_job[job_id] = per_job.get(job_id, 0) + 1
        people.add(candidate_id)
    return per_job, len(people)


async def reassign_counts(db: AsyncSession, job_ids: Sequence[int]) -> dict[int, int]:
    from app.models.job_proposal import JobProposal  # noqa: PLC0415

    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(JobProposal.job_id, func.count(JobProposal.id))
            .where(
                JobProposal.job_id.in_(list(job_ids)), JobProposal.source == "reassign"
            )
            .group_by(JobProposal.job_id)
        )
    ).all()
    return {job_id: int(n) for job_id, n in rows}


async def suggestions_for_job(
    db: AsyncSession,
    job: Any,
    *,
    exclude: Iterable[int] = (),
    limit: int = MAX_SUGGESTIONS,
) -> list[tuple[PoolJob, int]]:
    """Najbardziej podobne rekrutacje (bez już połączonych). Działa też dla
    rekrutacji jeszcze niezapisanej — wystarczy obiekt z tytułem i must-have."""
    pool = await _load_pool(db)
    ref = _as_pool_job(job)
    ranked = _rank(pool, ref, set(exclude))[:limit]
    return [(pool.jobs[job_id], score) for job_id, score in ranked]


async def suggestion_summaries(
    db: AsyncSession, jobs: Sequence[Job], linked: dict[int, list[int]]
) -> dict[int, dict]:
    """Dla listy: ile podobnych (niepołączonych) rekrutacji z osobami
    wysłanymi do klienta ma każda rekrutacja. Tylko otwarte wiersze."""
    pool = await _load_pool(db)
    ranked_by_job: dict[int, list[tuple[int, int]]] = {}
    wanted: set[int] = set()
    for job in jobs:
        status = job.status.value if hasattr(job.status, "value") else job.status
        if status == JobStatus.closed.value:
            continue
        ranked = _rank(pool, _as_pool_job(job), set(linked.get(job.id, [])))[
            :MAX_SUGGESTIONS
        ]
        ranked_by_job[job.id] = ranked
        wanted.update(job_id for job_id, _ in ranked)
    sent = await sent_counts(db, wanted)
    out: dict[int, dict] = {}
    for job_id, ranked in ranked_by_job.items():
        with_people = [(jid, score) for jid, score in ranked if sent.get(jid, 0) > 0]
        if not with_people:
            continue
        first = pool.jobs[with_people[0][0]]
        out[job_id] = {
            "count": len(with_people),
            "sent_count": sum(sent.get(jid, 0) for jid, _ in with_people),
            "first": {
                "id": first.id,
                "title": first.title,
                "reference_number": first.reference_number,
            },
        }
    return out


# ── Przepięcia ────────────────────────────────────────────────────────────


def _local_day_iso(moment: Optional[datetime]) -> Optional[str]:
    """Dzień wysłania w kalendarzu firmy (Europe/Warsaw), nie UTC.

    ``moved_at`` jest w UTC — ``.date()`` datowało wysyłkę z 00:00–02:00
    czasu polskiego dniem wcześniej (audyt 25.09.2026). Czas bez strefy
    traktujemy jak UTC (tak zapisuje baza).
    """

    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date().isoformat()


def _reassign_evidence(
    source_job_id: int, stage: PipelineStage, sent_at: Optional[datetime]
) -> dict:
    return {
        "reassign": {
            "job_id": source_job_id,
            "stage": stage.value,
            "sent_at": _local_day_iso(sent_at),
        }
    }


async def _open_job_ids(db: AsyncSession, job_ids: Iterable[int]) -> set[int]:
    ids = list(set(job_ids))
    if not ids:
        return set()
    rows = (
        await db.execute(
            select(Job.id).where(Job.id.in_(ids), Job.status != JobStatus.closed)
        )
    ).scalars()
    return set(rows)


async def reassign_into(
    db: AsyncSession, target_job_id: int, source_job_ids: Sequence[int]
) -> int:
    """Osoby wysłane do klienta w ``source_job_ids`` → propozycje ``reassign``
    rekrutacji docelowej. Pomija zatrudnionych w źródle i osoby, które już są
    w pipeline'ie celu. Zwraca liczbę zapisanych par."""
    from app.services.job_proposals import upsert_proposals  # noqa: PLC0415

    sources = [sid for sid in set(source_job_ids) if sid != target_job_id]
    if not sources or not await _open_job_ids(db, [target_job_id]):
        return 0
    hired = aliased(CandidateStage)
    in_target = aliased(CandidateStage)
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.stage,
                CandidateStage.moved_at,
            )
            .where(
                CandidateStage.job_id.in_(sources),
                CandidateStage.stage.in_(REASSIGN_STAGES),
                ~exists().where(
                    hired.candidate_id == CandidateStage.candidate_id,
                    hired.job_id == CandidateStage.job_id,
                    hired.stage == PipelineStage.hired,
                ),
                ~exists().where(
                    in_target.candidate_id == CandidateStage.candidate_id,
                    in_target.job_id == target_job_id,
                ),
            )
            .order_by(CandidateStage.candidate_id, CandidateStage.moved_at.desc())
        )
    ).all()
    latest: dict[int, Any] = {}
    for row in rows:
        latest.setdefault(row.candidate_id, row)
    payload = [
        {
            "candidate_id": cid,
            "evidence": _reassign_evidence(row.job_id, row.stage, row.moved_at),
        }
        for cid, row in latest.items()
    ]
    if not payload:
        return 0
    return await upsert_proposals(db, target_job_id, payload, source="reassign")


_OUTCOME_ORDER = {
    "in_progress": 0,
    "rejected_by_client": 1,
    "rejected": 2,
    "withdrawn": 3,
    "hired": 4,
}


async def sent_people(
    db: AsyncSession, target_job_id: int, source_job_ids: Sequence[int]
) -> dict[int, list[dict]]:
    """Osoby wysłane do klienta w ``source_job_ids`` — do panelu przepięć.

    Ta sama reguła „był u klienta" co :func:`reassign_into`: jakikolwiek
    wiersz w ``REASSIGN_STAGES``. Zatrudnieni w źródle i osoby, które już są
    w rekrutacji docelowej, wracają z ``selectable=False`` — panel ich
    pokazuje, ale nie da się ich przepiąć (decyzja Artura 25.09.2026).

    Wynik pamięta, jak skończył się tamten proces (``outcome``), bo odrzucony
    przez klienta też jest zaznaczany i rekruter ma to widzieć przed kliknięciem.
    """
    from app.models.candidate import Candidate  # noqa: PLC0415

    sources = [sid for sid in dict.fromkeys(source_job_ids) if sid != target_job_id]
    if not sources:
        return {}
    reached = aliased(CandidateStage)
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.stage,
                CandidateStage.moved_at,
                CandidateStage.ended_by,
                Candidate.name,
                Candidate.lastname,
            )
            .join(Candidate, Candidate.id == CandidateStage.candidate_id)
            .where(
                CandidateStage.job_id.in_(sources),
                exists().where(
                    reached.candidate_id == CandidateStage.candidate_id,
                    reached.job_id == CandidateStage.job_id,
                    reached.stage.in_(REASSIGN_STAGES),
                ),
            )
            .order_by(
                CandidateStage.job_id,
                CandidateStage.candidate_id,
                CandidateStage.moved_at,
                CandidateStage.id,
            )
        )
    ).all()
    candidate_ids = {row.candidate_id for row in rows}
    in_target: set[int] = set()
    if candidate_ids:
        in_target = set(
            (
                await db.execute(
                    select(CandidateStage.candidate_id).where(
                        CandidateStage.job_id == target_job_id,
                        CandidateStage.candidate_id.in_(list(candidate_ids)),
                    )
                )
            ).scalars()
        )

    pairs: dict[tuple[int, int], list[Any]] = {}
    for row in rows:
        pairs.setdefault((row.job_id, row.candidate_id), []).append(row)

    client_order = {stage: i for i, stage in enumerate(CLIENT_STAGES)}
    out: dict[int, list[dict]] = {sid: [] for sid in sources}
    for (job_id, candidate_id), history in pairs.items():
        sent_rows = [r for r in history if r.stage in REASSIGN_STAGES]
        hired = any(r.stage == PipelineStage.hired for r in history)
        furthest = max(
            (r.stage for r in history if r.stage in client_order),
            key=lambda stage: client_order[stage],
        )
        latest = history[-1]
        if hired:
            outcome = "hired"
        elif latest.stage == PipelineStage.rejected:
            outcome = (
                "rejected_by_client" if latest.ended_by == "client" else "rejected"
            )
        elif latest.stage == PipelineStage.withdrawn:
            outcome = "withdrawn"
        else:
            outcome = "in_progress"
        last_sent = sent_rows[-1]
        already = candidate_id in in_target
        out[job_id].append(
            {
                "candidate_id": candidate_id,
                "name": f"{latest.name or ''} {latest.lastname or ''}".strip(),
                "furthest_stage": furthest.value,
                "sent_at": _local_day_iso(sent_rows[0].moved_at),
                "outcome": outcome,
                "already_in_job": already,
                "selectable": not hired and not already,
                "reassign_stage": last_sent.stage.value,
                "reassign_at": last_sent.moved_at,
            }
        )
    for people in out.values():
        people.sort(
            key=lambda p: (
                not p["selectable"],
                _OUTCOME_ORDER.get(p["outcome"], 9),
                p["sent_at"] or "",
            )
        )
    return out


async def propose_selected(
    db: AsyncSession, target_job_id: int, people: Sequence[Mapping[str, Any]]
) -> int:
    """Przepięcie wskazane ręcznie: propozycja ``reassign`` z dowodem źródła,
    w statusie ``proposed`` — także gdy wcześniej ją pominięto albo cel jest
    zamknięty. Dzięki temu dodanie do pipeline'u zapisze wejście jako
    „przepięcie" z rekrutacją źródłową (``proposals_bulk._reassign_sources``).
    """
    from app.models.job_proposal import JobProposal  # noqa: PLC0415
    from app.services.job_proposals import upsert_proposals  # noqa: PLC0415

    payload = [
        {
            "candidate_id": p["candidate_id"],
            "evidence": _reassign_evidence(
                p["source_job_id"],
                PipelineStage(p["reassign_stage"]),
                p.get("reassign_at"),
            ),
        }
        for p in people
    ]
    if not payload:
        return 0
    written = await upsert_proposals(db, target_job_id, payload, source="reassign")
    # Rekruter wybrał te osoby teraz — wcześniejsze „Pomiń" tej propozycji
    # nie może zamienić przepięcia w zwykłe ręczne dodanie. `added` też:
    # po „Cofnij” osoby nie ma w celu (wołający sprawdził `selectable`), a
    # propozycja została `added` — bez tego ponowne przepięcie szło jako
    # ręczne dodanie, bez rekrutacji źródłowej na karcie.
    await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == target_job_id,
            JobProposal.source == "reassign",
            JobProposal.candidate_id.in_([p["candidate_id"] for p in people]),
            JobProposal.status.in_(("dismissed", "added")),
        )
        .values(
            status="proposed",
            dismissed_by=None,
            dismissed_at=None,
            dismissed_cv_revision=None,
        )
    )
    return written


async def link_jobs(
    db: AsyncSession, job_id: int, other_ids: Sequence[int], *, user_id: Optional[int]
) -> tuple[int, int]:
    """Połącz rekrutacje (oba kierunki) i od razu przepnij osoby w obie strony.

    Zwraca ``(liczba nowych połączeń, osoby przepięte DO job_id)``."""
    others = sorted({oid for oid in other_ids if oid != job_id})
    if not others:
        return 0, 0
    existing = set((await linked_job_ids(db, [job_id])).get(job_id, []))
    values = []
    for oid in others:
        values.append({"job_id": job_id, "similar_job_id": oid, "created_by": user_id})
        values.append({"job_id": oid, "similar_job_id": job_id, "created_by": user_id})
    await db.execute(
        pg_insert(JobSimilarLink)
        .values(values)
        .on_conflict_do_nothing(constraint="uq_job_similar_links_pair")
    )
    reassigned = await reassign_into(db, job_id, others)
    for oid in others:
        await reassign_into(db, oid, [job_id])
    return len([o for o in others if o not in existing]), reassigned


async def unlink_jobs(db: AsyncSession, job_id: int, other_id: int) -> int:
    from sqlalchemy import delete  # noqa: PLC0415

    result = await db.execute(
        delete(JobSimilarLink).where(
            or_(
                and_(
                    JobSimilarLink.job_id == job_id,
                    JobSimilarLink.similar_job_id == other_id,
                ),
                and_(
                    JobSimilarLink.job_id == other_id,
                    JobSimilarLink.similar_job_id == job_id,
                ),
            )
        )
    )
    return int(result.rowcount or 0)


async def on_candidate_sent(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_id: int,
    stage: PipelineStage,
    sent_at: Optional[datetime] = None,
) -> int:
    """Hak ruchu w pipeline: osoba weszła do klienta → przepnij do połączonych.

    ``sent_at`` — chwila ruchu, gdy nie jest „teraz" (import Traffita,
    audyt 22.09 r2 REC-01); trafia do dowodu propozycji.

    Nie rzuca — przepięcie jest dodatkiem, ruch musi się zapisać zawsze."""
    from app.services.job_proposals import upsert_proposals  # noqa: PLC0415

    if stage not in REASSIGN_STAGES:
        return 0
    try:
        async with db.begin_nested():
            targets = (
                (
                    await db.execute(
                        select(JobSimilarLink.job_id).where(
                            JobSimilarLink.similar_job_id == job_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            open_targets = await _open_job_ids(db, targets)
            if not open_targets:
                return 0
            already = set(
                (
                    await db.execute(
                        select(CandidateStage.job_id).where(
                            CandidateStage.candidate_id == candidate_id,
                            CandidateStage.job_id.in_(list(open_targets)),
                        )
                    )
                ).scalars()
            )
            now = sent_at or datetime.now(timezone.utc)
            written = 0
            for target in sorted(open_targets - already):
                written += await upsert_proposals(
                    db,
                    target,
                    [
                        {
                            "candidate_id": candidate_id,
                            "evidence": _reassign_evidence(job_id, stage, now),
                        }
                    ],
                    source="reassign",
                )
            return written
    except Exception:  # noqa: BLE001 — dodatek do ruchu, nigdy jego warunek
        logger.exception(
            "job_similarity.on_candidate_sent failed job=%s candidate=%s",
            job_id,
            candidate_id,
        )
        return 0


# ── Status requestu ───────────────────────────────────────────────────────


def request_status_subquery(job_ids: Any):
    """``(job_id, hired_n, contract_n)`` z BIEŻĄCYCH etapów par.

    ``job_ids`` — lista albo podzapytanie. Etap „Umowa …" z szablonu nie ma
    własnego legacy-enuma, więc rozpoznajemy go po nazwie definicji etapu."""
    from app.services.pipeline_latest import latest_stage_ids  # noqa: PLC0415

    latest = latest_stage_ids(job_ids=job_ids)
    contract_hit = or_(
        CandidateStage.stage.in_(CONTRACT_STAGES),
        func.lower(PipelineStageDef.name).like("umowa%"),
    )
    return (
        select(
            CandidateStage.job_id.label("job_id"),
            func.count(
                func.distinct(
                    case(
                        (
                            CandidateStage.stage == PipelineStage.hired,
                            CandidateStage.candidate_id,
                        )
                    )
                )
            ).label("hired_n"),
            func.count(
                func.distinct(case((contract_hit, CandidateStage.candidate_id)))
            ).label("contract_n"),
        )
        .outerjoin(PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id)
        .where(CandidateStage.id.in_(select(latest.c.latest_id)))
        .group_by(CandidateStage.job_id)
        .subquery()
    )


def request_status_expr(sq):
    """Jedna reguła statusu — filtr listy i wiersz listy czytają to samo."""
    hired = func.coalesce(sq.c.hired_n, 0)
    return case(
        (Job.status == JobStatus.closed, "closed"),
        (and_(hired > 0, hired >= func.greatest(Job.headcount, 1)), "filled"),
        (func.coalesce(sq.c.contract_n, 0) > 0, "contract"),
        (Job.champion_found_at.is_not(None), "champion"),
        (Job.status == JobStatus.draft, "incomplete"),
        else_="searching",
    )


def request_stage_expr(sq):
    """Jedna wartość stanu requestu na rekrutację (lista `/jobs`, 25.09.2026).

    Najpierw fakty z pipeline'u i championa (jak ``request_status_expr``),
    potem stan pracy prowadzony w NEXUSIE (`jobs.work_state`). Szkic jest
    „Do uzupełnienia” niezależnie od stanu pracy."""
    hired = func.coalesce(sq.c.hired_n, 0)
    return case(
        (Job.status == JobStatus.closed, "closed"),
        (and_(hired > 0, hired >= func.greatest(Job.headcount, 1)), "filled"),
        (func.coalesce(sq.c.contract_n, 0) > 0, "contract"),
        (Job.champion_found_at.is_not(None), "champion"),
        (Job.status == JobStatus.draft, "incomplete"),
        (Job.work_state == "finished", "finished"),
        (Job.work_state == "client_silent", "client_silent"),
        (Job.work_state == "searching", "searching"),
        else_="to_review",
    )


async def request_statuses_and_stages(
    db: AsyncSession, job_ids: Sequence[int]
) -> dict[int, tuple[str, str]]:
    """``{job_id: (request_status, request_stage)}`` jednym zapytaniem."""
    if not job_ids:
        return {}
    sq = request_status_subquery(list(job_ids))
    rows = (
        await db.execute(
            select(Job.id, request_status_expr(sq), request_stage_expr(sq))
            .outerjoin(sq, sq.c.job_id == Job.id)
            .where(Job.id.in_(list(job_ids)))
        )
    ).all()
    return {job_id: (status, stage) for job_id, status, stage in rows}


async def request_statuses(db: AsyncSession, job_ids: Sequence[int]) -> dict[int, str]:
    if not job_ids:
        return {}
    sq = request_status_subquery(list(job_ids))
    rows = (
        await db.execute(
            select(Job.id, request_status_expr(sq))
            .outerjoin(sq, sq.c.job_id == Job.id)
            .where(Job.id.in_(list(job_ids)))
        )
    ).all()
    return {job_id: status for job_id, status in rows}
