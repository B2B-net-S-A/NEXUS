"""Skrzynka „Propozycje" rekrutacji — zapis, „Pomiń", licznik otwartych.

Reguły, które łatwo cofnąć „przy okazji":

* ``added`` nigdy się nie cofa.
* „Pomiń" (``dismissed``) obowiązuje CAŁY zespół i WSZYSTKIE źródła. Kolejny
  przegląd tej samej wersji CV nie wskrzesza osoby; wraca ona wyłącznie wtedy,
  gdy przychodzi z NOWĄ wersją CV (``cv_revision`` inne niż
  ``dismissed_cv_revision``) — jako ``proposed``, z ``first_seen_at = now()``
  i flagą ``previously_dismissed`` w ``evidence``.
* Status liczy się PER PARA (kandydat, rekrutacja), nie per wiersz źródła:
  ``added`` > ``dismissed`` > ``proposed``.
* Licznik listy rekrutacji jest ZESPOŁOWY (``open_counts_for_jobs``): propozycja
  liczy się, dopóki ktoś jej nie obsłuży („Dodaj" albo „Pomiń"). Ta sama reguła
  widoczności co lista skrzynki — bez osób już w pipeline'ie tej rekrutacji
  i bez globalnej czarnej listy — więc plakietka nie obiecuje wierszy, których
  lista nie pokaże.
* ``evidence`` przechodzi przez :func:`sanitize_evidence` — wyłącznie
  nazwy/identyfikatory wymagań i liczby, nigdy wolny tekst z CV.
* Żadna funkcja tutaj nie commituje — transakcja należy do wołającego.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import case, exists, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.job_proposal import (
    JOB_PROPOSAL_SOURCES,
    JOB_PROPOSAL_STATUSES,
    JobProposal,
)
from app.models.recruitment_pipeline import CandidateStage

_UPSERT_CHUNK = 500
_MAX_NAME_LEN = 120
_MAX_REQUIREMENTS = 60
_REQUIREMENT_KEYS = ("id", "key", "level", "status")
_NAME_LIST_KEYS = ("matched_must", "matched_nice", "missing_must", "missing_nice")
# Ustawiana WYŁĄCZNIE przez serwis, gdy nowa wersja CV wskrzesza pominiętą osobę.
PREVIOUSLY_DISMISSED_KEY = "previously_dismissed"
_MAX_REVISION_LEN = 64
# Inbox: „nowa" = pierwszy raz zaproponowana w ostatniej dobie (kosmetyka).
NEW_PROPOSAL_WINDOW = timedelta(hours=24)


def _short(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:_MAX_NAME_LEN] if text else None


def _names(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    out = [_short(v) for v in values[:_MAX_REQUIREMENTS]]
    return [v for v in out if v]


def sanitize_evidence(raw: Any) -> Optional[dict]:
    """Allowlista: nazwy/identyfikatory wymagań + liczby. Reszta przepada.

    Wiersz żyje do usunięcia kandydata, więc nie może nieść cytatów z CV,
    notatek ani kontekstu użycia technologii (``candidate_evidence``,
    ``usage_context`` z pełnego przeglądu są tu świadomie odrzucane).
    """
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, Any] = {}
    requirements = []
    for item in (raw.get("requirements") or [])[:_MAX_REQUIREMENTS]:
        if not isinstance(item, Mapping):
            continue
        clean: dict[str, Any] = {}
        for key in _REQUIREMENT_KEYS:
            value = item.get(key)
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int):
                clean[key] = value
            elif (short := _short(value)) is not None:
                clean[key] = short
        if (name := _short(item.get("name"))) is not None:
            clean["name"] = name
        if any_of := _names(item.get("any_of")):
            clean["any_of"] = any_of
        if clean:
            requirements.append(clean)
    if requirements:
        out["requirements"] = requirements
    for key in _NAME_LIST_KEYS:
        if names := _names(raw.get(key)):
            out[key] = names
    counts = raw.get("counts")
    if isinstance(counts, Mapping):
        numbers = {
            str(k)[:40]: v
            for k, v in counts.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if numbers:
            out["counts"] = numbers
    if raw.get(PREVIOUSLY_DISMISSED_KEY) is True:
        out[PREVIOUSLY_DISMISSED_KEY] = True
    return out or None


def _revision(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text_value = value.strip()
    return text_value[:_MAX_REVISION_LEN] if text_value else None


def _score(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return min(max(number, Decimal("0")), Decimal("999.99"))


def _validate_source(source: str) -> None:
    if source not in JOB_PROPOSAL_SOURCES:
        raise ValueError(f"Unknown job proposal source: {source!r}")


async def upsert_proposals(
    db: AsyncSession,
    job_id: int,
    rows: Iterable[Mapping[str, Any]],
    source: str,
    run_id: Optional[str] = None,
    cv_revision: Optional[str] = None,
) -> int:
    """Zapisz propozycje jednego źródła. Zwraca liczbę przetworzonych par.

    ``rows``: ``{"candidate_id": int, "score": number|None, "evidence":
    dict|None, "cv_revision": str|None}``. Wersja CV to ta sama wartość co
    ``candidate_auto_match_log.profile_revision``
    (``auto_match_outbox.candidate_revision``); ``cv_revision`` z argumentu jest
    domyślną dla wierszy, które własnej nie niosą.

    Konflikt ``(job_id, candidate_id, source)`` odświeża ``last_seen_at``,
    ``score``, ``evidence``, ``cv_revision`` i ``run_id`` (gdy podane).
    ``status`` i ``first_seen_at`` zostają — z JEDNYM wyjątkiem: osoba pominięta
    wraca jako ``proposed``, gdy przychodzi z niepustą wersją CV inną niż ta,
    przy której ją pominięto. Ta sama wersja (albo brak wersji) nie wskrzesza.
    """
    _validate_source(source)
    default_revision = _revision(cv_revision)
    by_candidate: dict[int, dict] = {}
    for row in rows:
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, int) or isinstance(candidate_id, bool):
            continue
        # Ostatni wiersz tej samej osoby wygrywa: dwa wiersze jednej pary
        # w jednym INSERT … ON CONFLICT to błąd Postgresa (cardinality violation).
        evidence = sanitize_evidence(row.get("evidence"))
        if evidence is not None:
            # Flagę stawia wyłącznie serwis — producent nie może jej podrobić.
            evidence.pop(PREVIOUSLY_DISMISSED_KEY, None)
        by_candidate[candidate_id] = {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "source": source,
            "score": _score(row.get("score")),
            "evidence": evidence or None,
            "run_id": run_id,
            "cv_revision": _revision(row.get("cv_revision")) or default_revision,
        }
    # Rosnąco po kandydacie — stała kolejność blokad wierszy między
    # równoległymi zapisami tego samego źródła.
    values = [by_candidate[cid] for cid in sorted(by_candidate)]
    flag = literal({PREVIOUSLY_DISMISSED_KEY: True}, type_=JSONB)
    for start in range(0, len(values), _UPSERT_CHUNK):
        chunk = values[start : start + _UPSERT_CHUNK]
        stmt = pg_insert(JobProposal).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_job_proposals_pair_source",
            set_={
                "last_seen_at": func.now(),
                "score": stmt.excluded.score,
                # Flaga „wcześniej pominięty" przeżywa kolejne przeglądy.
                "evidence": case(
                    (
                        JobProposal.evidence.has_key(PREVIOUSLY_DISMISSED_KEY),
                        func.coalesce(stmt.excluded.evidence, text("'{}'::jsonb")).op(
                            "||"
                        )(flag),
                    ),
                    else_=stmt.excluded.evidence,
                ),
                "run_id": func.coalesce(stmt.excluded.run_id, JobProposal.run_id),
                "cv_revision": func.coalesce(
                    stmt.excluded.cv_revision, JobProposal.cv_revision
                ),
            },
        )
        await db.execute(stmt)
        await _resurrect_on_new_cv(
            db,
            job_id=job_id,
            source=source,
            candidate_ids=[v["candidate_id"] for v in chunk if v["cv_revision"]],
        )
    return len(values)


async def _resurrect_on_new_cv(
    db: AsyncSession, *, job_id: int, source: str, candidate_ids: Sequence[int]
) -> int:
    """Pominięta osoba z NOWĄ wersją CV wraca do skrzynki (wszystkie jej źródła).

    Wersję „przychodzącą" czytamy z wiersza tego źródła, który INSERT wyżej
    właśnie zapisał — dlatego tylko dla osób, które przyszły z niepustą wersją.
    ``IS DISTINCT FROM``: pominięcie bez zapisanej wersji też ustępuje nowej.
    """
    if not candidate_ids:
        return 0
    result = await db.execute(
        text(
            """
            UPDATE job_proposals AS p
            SET status = 'proposed',
                first_seen_at = now(),
                dismissed_at = NULL,
                dismissed_by = NULL,
                dismissed_cv_revision = NULL,
                evidence = (CASE WHEN jsonb_typeof(p.evidence) = 'object'
                                 THEN p.evidence ELSE '{}'::jsonb END)
                           || '{"previously_dismissed": true}'::jsonb
            WHERE p.job_id = :job_id
              AND p.candidate_id = ANY(:candidate_ids)
              AND p.status = 'dismissed'
              AND EXISTS (
                  SELECT 1 FROM job_proposals AS cur
                  WHERE cur.job_id = p.job_id
                    AND cur.candidate_id = p.candidate_id
                    AND cur.source = :source
                    AND cur.cv_revision IS NOT NULL
                    AND cur.cv_revision IS DISTINCT FROM p.dismissed_cv_revision
              )
            """
        ),
        {
            "job_id": job_id,
            "source": source,
            "candidate_ids": sorted(set(candidate_ids)),
        },
    )
    return int(result.rowcount or 0)


async def dismiss(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_id: int,
    user_id: Optional[int],
    cv_revision: Optional[str] = None,
) -> int:
    """„Pomiń" — dla całego zespołu i ze WSZYSTKICH źródeł. Zwraca liczbę wierszy.

    Stempluje ``dismissed_at`` i ``dismissed_cv_revision``: bieżącą wersję CV
    (podaje ją wołający — ``candidate_revision``), a gdy jej nie zna, wersję,
    dla której policzono propozycję. ``added`` zostaje nietknięte; powtórne
    pominięcie nic nie zmienia (0).
    """
    result = await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == job_id,
            JobProposal.candidate_id == candidate_id,
            JobProposal.status == "proposed",
        )
        .values(
            status="dismissed",
            dismissed_by=user_id,
            dismissed_at=func.now(),
            dismissed_cv_revision=func.coalesce(
                _revision(cv_revision), JobProposal.cv_revision
            ),
        )
    )
    return int(result.rowcount or 0)


async def is_in_pipeline(db: AsyncSession, *, job_id: int, candidate_id: int) -> bool:
    """Czy osoba ma już jakikolwiek etap w TEJ rekrutacji."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    CandidateStage.job_id == job_id,
                    CandidateStage.candidate_id == candidate_id,
                )
            )
        )
    )


async def dismiss_unlisted(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_id: int,
    user_id: Optional[int],
    source: str = "full_base",
    cv_revision: Optional[str] = None,
) -> int:
    """„Pomiń" osoby, której skrzynka jeszcze nie zna (np. z wyszukiwarki).

    Zakłada wiersz od razu jako ``dismissed`` — dzięki temu kolejny przegląd tej
    samej wersji CV jej nie zaproponuje, a nowa wersja przywróci (jak zwykłe
    „Pomiń"). Konflikt pary+źródła (równoległy zapis przeglądu) = 0; wołający
    ponawia wtedy :func:`dismiss`.
    """
    _validate_source(source)
    revision = _revision(cv_revision)
    result = await db.execute(
        pg_insert(JobProposal)
        .values(
            job_id=job_id,
            candidate_id=candidate_id,
            source=source,
            status="dismissed",
            cv_revision=revision,
            dismissed_by=user_id,
            dismissed_at=func.now(),
            dismissed_cv_revision=revision,
        )
        .on_conflict_do_nothing(constraint="uq_job_proposals_pair_source")
    )
    return int(result.rowcount or 0)


async def restore(db: AsyncSession, *, job_id: int, candidate_id: int) -> int:
    """„Cofnij" pominięcie — wiersze ``dismissed`` wracają jako ``proposed``.

    ``added`` zostaje nietknięte; ``first_seen_at`` też (to cofnięcie, nie nowa
    propozycja — osoba nie dostaje plakietki „nowa"). Zwraca liczbę wierszy.
    """
    result = await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == job_id,
            JobProposal.candidate_id == candidate_id,
            JobProposal.status == "dismissed",
        )
        .values(
            status="proposed",
            dismissed_by=None,
            dismissed_at=None,
            dismissed_cv_revision=None,
        )
    )
    return int(result.rowcount or 0)


async def mark_added(
    db: AsyncSession, *, job_id: int, candidate_ids: Sequence[int]
) -> int:
    """Osoby faktycznie dodane do pipeline'u → ``added`` (także z ``dismissed``)."""
    ids = sorted({int(c) for c in candidate_ids})
    if not ids:
        return 0
    result = await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == job_id,
            JobProposal.candidate_id.in_(ids),
            JobProposal.status != "added",
        )
        .values(status="added")
    )
    return int(result.rowcount or 0)


async def mark_added_fail_soft(
    db: AsyncSession, *, job_id: int, candidate_ids: Sequence[int]
) -> None:
    """``mark_added`` w savepoincie — awaria nie cofa dodania do rekrutacji."""
    import logging

    if not candidate_ids:
        return
    try:
        async with db.begin_nested():
            await mark_added(db, job_id=job_id, candidate_ids=candidate_ids)
    except Exception as exc:  # noqa: BLE001 — propozycje nigdy nie psują dodania
        logging.getLogger(__name__).warning(
            "[job_proposals] mark_added skipped job=%s: %s",
            job_id,
            type(exc).__name__,
        )


def _in_pipeline(job_col, candidate_col):
    return exists(
        select(literal(1)).where(
            CandidateStage.job_id == job_col,
            CandidateStage.candidate_id == candidate_col,
        )
    )


def _globally_blacklisted(candidate_col):
    return exists(
        select(literal(1)).where(
            Candidate.id == candidate_col,
            Candidate.status == CandidateStatus.blacklisted,
        )
    )


def _pair_status():
    """Status pary z wierszy źródeł: added > dismissed > proposed."""
    return case(
        (func.bool_or(JobProposal.status == "added"), "added"),
        (func.bool_or(JobProposal.status == "dismissed"), "dismissed"),
        else_="proposed",
    )


async def open_counts_for_jobs(
    db: AsyncSession, job_ids: Sequence[int]
) -> dict[int, int]:
    """Ile osób czeka w skrzynce rekrutacji — ZESPOŁOWO, nie per użytkownik.

    Jedno zapytanie dla całej strony listy. Ta sama widoczność co
    :func:`list_for_job` ze ``status="proposed"``. Rekrutacje bez otwartych
    propozycji nie trafiają do słownika (wołający czyta ``.get(job_id, 0)``).
    """
    ids = sorted({int(j) for j in job_ids})
    if not ids:
        return {}
    pairs = (
        select(
            JobProposal.job_id.label("job_id"),
            JobProposal.candidate_id.label("candidate_id"),
        )
        .where(
            JobProposal.job_id.in_(ids),
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id),
            ~_globally_blacklisted(JobProposal.candidate_id),
        )
        .group_by(JobProposal.job_id, JobProposal.candidate_id)
        .having(_pair_status() == "proposed")
        .subquery()
    )
    rows = await db.execute(
        select(pairs.c.job_id, func.count()).group_by(pairs.c.job_id)
    )
    return {int(job_id): int(n) for job_id, n in rows.all()}


@dataclass(frozen=True)
class ProposalRow:
    candidate_id: int
    sources: list[str]
    score: Optional[float]
    evidence: Optional[dict]
    first_seen_at: datetime
    last_seen_at: datetime
    is_new: bool
    status: str
    # Przegląd, z którego pochodzi propozycja (wiersz o najwyższym wyniku, który
    # go niesie). Bez FK — retencja kasuje przeglądy, więc bywa już nieaktualny.
    run_id: Optional[str] = None


async def list_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    status: str = "proposed",
    limit: int = 20,
    offset: int = 0,
    now: Optional[datetime] = None,
) -> tuple[list[ProposalRow], int]:
    """Strona propozycji — jedna pozycja na OSOBĘ, ze złożonymi źródłami.

    Kolejność: wynik malejąco (brak wyniku na końcu), potem najnowsze, potem id
    — stabilna między stronami. ``is_new`` = zaproponowana (albo przywrócona po
    nowym CV) w ciągu ostatnich 24 h; czysto kosmetyczne.
    """
    if status not in JOB_PROPOSAL_STATUSES:
        raise ValueError(f"Unknown job proposal status: {status!r}")
    new_since = (now or datetime.now(timezone.utc)) - NEW_PROPOSAL_WINDOW
    grouped = (
        select(
            JobProposal.candidate_id.label("candidate_id"),
            func.array_agg(func.distinct(JobProposal.source)).label("sources"),
            func.max(JobProposal.score).label("score"),
            func.min(JobProposal.first_seen_at).label("first_seen_at"),
            func.max(JobProposal.first_seen_at).label("newest_seen_at"),
            func.max(JobProposal.last_seen_at).label("last_seen_at"),
        )
        .where(JobProposal.job_id == job_id)
        .group_by(JobProposal.candidate_id)
        .having(_pair_status() == status)
    )
    if status == "proposed":
        grouped = grouped.where(
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id),
            ~_globally_blacklisted(JobProposal.candidate_id),
        )
    sub = grouped.subquery()
    total = int(await db.scalar(select(func.count()).select_from(sub)) or 0)
    page = (
        await db.execute(
            select(sub)
            .order_by(
                sub.c.score.desc().nullslast(),
                sub.c.newest_seen_at.desc(),
                sub.c.candidate_id,
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    candidate_ids = [row.candidate_id for row in page]
    evidence_by_candidate: dict[int, Optional[dict]] = {}
    run_by_candidate: dict[int, str] = {}
    if candidate_ids:
        # Dowody z wiersza o najwyższym wyniku (jedno zapytanie na stronę);
        # flaga „wcześniej pominięty" liczy się z KAŻDEGO wiersza pary.
        evidence_rows = await db.execute(
            select(JobProposal.candidate_id, JobProposal.evidence, JobProposal.run_id)
            .where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id.in_(candidate_ids),
            )
            .order_by(
                JobProposal.candidate_id,
                JobProposal.score.desc().nullslast(),
                JobProposal.id,
            )
        )
        flagged: set[int] = set()
        for cid, evidence, run_id in evidence_rows.all():
            evidence_by_candidate.setdefault(cid, evidence)
            if run_id and cid not in run_by_candidate:
                run_by_candidate[cid] = run_id
            if isinstance(evidence, dict) and evidence.get(PREVIOUSLY_DISMISSED_KEY):
                flagged.add(cid)
        for cid in flagged:
            evidence_by_candidate[cid] = {
                **(evidence_by_candidate.get(cid) or {}),
                PREVIOUSLY_DISMISSED_KEY: True,
            }
    out = [
        ProposalRow(
            candidate_id=row.candidate_id,
            sources=sorted(row.sources or []),
            score=float(row.score) if row.score is not None else None,
            evidence=evidence_by_candidate.get(row.candidate_id),
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            is_new=row.newest_seen_at >= new_since,
            status=status,
            run_id=run_by_candidate.get(row.candidate_id),
        )
        for row in page
    ]
    return out, total
