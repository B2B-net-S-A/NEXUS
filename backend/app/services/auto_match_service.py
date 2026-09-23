"""Autonomiczne dopasowanie: nowe CV → otwarte rekrutacje, nowa rekrutacja → świeże CV.

Decyzja Artura z 17.09.2026: kandydat pasujący do opublikowanej rekrutacji trafia
SAM do jej pipeline'u (etap „Ogłoszenia”, tag `auto-match`), a właściciel
rekrutacji dostaje powiadomienie.

Kolejność każdego zdarzenia:

1. pula — wyszukiwanie semantyczne (Voyage + Qdrant) w przeciwnej kolekcji;
2. odrzucenie tego, co już jest w pipeline'ie i rekrutacji nieopublikowanych;
3. ranking tym samym scoringiem co „Sugerowane rekrutacje” i C2;
4. dealbreakery rekrutacji (budżet, must-have, biuro) i bramki przypisania;
5. reguła `auto_match_rules.is_good_match` + sufit liczby dodań;
6. dodanie przez `proposals_bulk.add_candidates_to_job` — te same bramki co
   rekruter (blacklista, NDA i konflikty klienta, weto hiring managera);
7. dziennik decyzji dla KAŻDEJ rozważonej pary + powiadomienie po commicie.

Tryb (`auto_match_outbox.auto_match_mode`, 21.09.2026): `propose` (domyślny)
kończy się na kroku 5 — dobry wynik trafia do skrzynki „Propozycje" rekrutacji
(`job_proposals`, źródło `new_cv`) i do dziennego digestu; do pipeline'u nie
wchodzi NIKT. `add` wykonuje kroki 6–7 jak 17.09, `dry_run` tylko dziennik.

Dziennik (`candidate_auto_match_log`, UNIQUE na kandydat×rekrutacja×wersja CV)
jest też dedupem: ta sama wersja profilu nie wraca do tej samej rekrutacji.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.candidate_auto_match import CandidateMatchOutbox
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.services.auto_match_outbox import auto_match_mode, candidate_revision
from app.services.auto_match_rules import is_good_match

logger = logging.getLogger(__name__)

AUTO_MATCH_TAG = "auto-match"
# Ostrzeżenia scoringu, które dla automatu są blokadą (patrz `Scored.warnings`).
_BLOCKING_WARNINGS = frozenset({"active_conflict", "client_excluded"})


class AutoMatchUnavailable(RuntimeError):
    """Wyszukiwanie semantyczne nie odpowiedziało — zdarzenie wraca do kolejki."""


@dataclass(frozen=True)
class Scored:
    candidate_id: int
    job_id: int
    score: float
    matching_must: tuple[str, ...]
    gap_must: tuple[str, ...]
    penalties: tuple[str, ...]
    # Konflikt z klientem i wykluczenie klienta przez kandydata od 17.09.2026
    # tylko OSTRZEGAJĄ rekrutera (#1589). Automat nie ma kogo ostrzec, więc
    # takiego kandydata nie dodaje sam — decyzję zostawia człowiekowi.
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    candidate_id: int
    job_id: int
    score: Optional[float]
    decision: str
    reason: Optional[str] = None


def decide(
    scored: Iterable[Scored],
    *,
    min_score: float,
    require_must: bool,
    cap: int,
) -> list[Decision]:
    """Czysta decyzja: kogo dodać, kogo nie i dlaczego (od najlepszego wyniku).

    `add` oznacza wyłącznie „reguła przepuszcza i mieści się w sufcie" — samo
    dodanie może jeszcze odmówić na bramkach przypisania.
    """
    decisions: list[Decision] = []
    planned = 0
    for row in sorted(scored, key=lambda r: (-r.score, r.job_id, r.candidate_id)):
        rec = {
            "score": row.score,
            "status": "published",
            "matching_must": list(row.matching_must),
            "gap_must": list(row.gap_must),
        }
        if row.penalties or row.warnings:
            decisions.append(
                Decision(
                    row.candidate_id,
                    row.job_id,
                    row.score,
                    "penalized",
                    "; ".join(row.penalties + row.warnings)[:500],
                )
            )
        elif row.score < min_score:
            decisions.append(
                Decision(row.candidate_id, row.job_id, row.score, "below_threshold")
            )
        elif not is_good_match(rec, min_score=min_score, require_must=require_must):
            decisions.append(
                Decision(
                    row.candidate_id,
                    row.job_id,
                    row.score,
                    "must_gap",
                    ", ".join(row.gap_must)[:500] or None,
                )
            )
        elif planned >= cap:
            decisions.append(
                Decision(row.candidate_id, row.job_id, row.score, "capped")
            )
        else:
            planned += 1
            decisions.append(Decision(row.candidate_id, row.job_id, row.score, "add"))
    return decisions


def _scored_from_breakdown(breakdown) -> Scored:
    return Scored(
        candidate_id=int(breakdown.candidate_id),
        job_id=int(breakdown.job_id),
        score=round(float(breakdown.total), 2),
        matching_must=tuple(breakdown.matching_must or ()),
        gap_must=tuple(breakdown.gap_must or ()),
        penalties=tuple(breakdown.penalties or ()),
        warnings=tuple(
            w
            for w in (getattr(breakdown, "warnings", None) or ())
            if w in _BLOCKING_WARNINGS
        ),
    )


async def _logged_pairs(
    db: AsyncSession,
    pairs: list[tuple[int, int]],
    revisions: dict[int, str],
    *,
    since: Optional[datetime] = None,
) -> set[tuple[int, int]]:
    """Pary do pominięcia: już rozstrzygnięte dla bieżącej wersji CV.

    - `added` blokuje zawsze (kandydat jest w pipeline'ie);
    - `dry_run` nie blokuje nigdy — po przejściu na żywo system ma dodać tych,
      których tryb próbny zaakceptował;
    - pozostałe decyzje (w tym `proposed`) blokują, chyba że są starsze niż
      `since` (zdarzenie rekrutacji po zmianie wymagań ocenia wszystkich od nowa).
    """
    if not pairs:
        return set()
    rows = await db.execute(
        text(
            "SELECT candidate_id, job_id, profile_revision, decision, created_at "
            "FROM candidate_auto_match_log "
            "WHERE candidate_id = ANY(:cids) AND job_id = ANY(:jids)"
        ),
        {
            "cids": sorted({c for c, _ in pairs}),
            "jids": sorted({j for _, j in pairs}),
        },
    )
    wanted = set(pairs)
    blocked: set[tuple[int, int]] = set()
    for r in rows:
        key = (int(r.candidate_id), int(r.job_id))
        if key not in wanted or revisions.get(key[0]) != r.profile_revision:
            continue
        if r.decision == "added":
            blocked.add(key)
        elif r.decision == "dry_run":
            continue
        elif since is None or r.created_at >= since:
            blocked.add(key)
    return blocked


async def _write_log(
    db: AsyncSession,
    *,
    decisions: list[Decision],
    revisions: dict[int, str],
    trigger: str,
    run_id: str,
    stage_ids: dict[tuple[int, int], int],
) -> None:
    for d in decisions:
        await db.execute(
            text(
                "INSERT INTO candidate_auto_match_log "
                "(candidate_id, job_id, profile_revision, trigger, score, decision, "
                " reason, stage_id, run_id) "
                "VALUES (:cid, :jid, :rev, :trigger, :score, :decision, :reason, "
                " :stage_id, :run_id) "
                "ON CONFLICT ON CONSTRAINT uq_candidate_auto_match_log_pair_revision "
                "DO UPDATE SET trigger = EXCLUDED.trigger, score = EXCLUDED.score, "
                " decision = EXCLUDED.decision, reason = EXCLUDED.reason, "
                " stage_id = EXCLUDED.stage_id, run_id = EXCLUDED.run_id, "
                " created_at = now() "
                "WHERE candidate_auto_match_log.decision <> 'added'"
            ),
            {
                "cid": d.candidate_id,
                "jid": d.job_id,
                "rev": revisions[d.candidate_id],
                "trigger": trigger[:16],
                "score": d.score,
                "decision": d.decision,
                "reason": (d.reason or None) and d.reason[:500],
                "stage_id": stage_ids.get((d.candidate_id, d.job_id)),
                "run_id": run_id,
            },
        )


def _note(score: Optional[float], matching: int, total: int, trigger: str) -> str:
    source = "nowej rekrutacji" if trigger == "job_publish" else "odczycie CV"
    must = f" Must-have: {matching}/{total}." if total else ""
    return (
        f"Auto-match {round(score or 0)}/100 — kandydat dodany automatycznie po "
        f"{source}.{must}"
    )


async def _apply_decisions(
    db: AsyncSession,
    *,
    decisions: list[Decision],
    scored_by_pair: dict[tuple[int, int], Scored],
    jobs_by_id: dict[int, Job],
    trigger: str,
) -> tuple[list[Decision], dict[tuple[int, int], int]]:
    """Zamień plan „add” na realne dodania (albo `dry_run`/odmowę bramki)."""
    from app.api.proposals_bulk import add_candidates_to_job

    final: list[Decision] = []
    stage_ids: dict[tuple[int, int], int] = {}
    for d in decisions:
        if d.decision != "add":
            final.append(d)
            continue
        mode = auto_match_mode()
        if mode == "dry_run":
            final.append(Decision(d.candidate_id, d.job_id, d.score, "dry_run"))
            continue
        if mode == "propose":
            # Nic nie wchodzi do pipeline'u — decyzję podejmuje człowiek
            # w skrzynce „Propozycje" (`_publish_proposals`).
            final.append(Decision(d.candidate_id, d.job_id, d.score, "proposed"))
            continue
        job = jobs_by_id[d.job_id]
        scored = scored_by_pair[(d.candidate_id, d.job_id)]
        try:
            async with db.begin_nested():
                result = await add_candidates_to_job(
                    db,
                    job=job,
                    candidate_ids=[d.candidate_id],
                    actor_user_id=job.recruiter_id or job.tac_id,
                    initial_stage_legacy="posting",
                    note=_note(
                        d.score,
                        len(scored.matching_must),
                        len(scored.matching_must) + len(scored.gap_must),
                        trigger,
                    ),
                    tags=[AUTO_MATCH_TAG],
                    # Automat nikogo nie „bierze” — osoba z automatu jest
                    # wolna, a „Biorę” zakłada blokadę klikającemu (0352).
                    entry_source="auto_match",
                    claim=False,
                )
        except Exception as exc:  # noqa: BLE001 — jedna para nie wywraca biegu
            logger.warning(
                "[auto_match] add failed candidate=%s job=%s: %s",
                d.candidate_id,
                d.job_id,
                exc,
            )
            final.append(
                Decision(
                    d.candidate_id,
                    d.job_id,
                    d.score,
                    "ineligible",
                    f"błąd: {exc!r}"[:500],
                )
            )
            continue
        if d.candidate_id in result.added:
            stage_ids[(d.candidate_id, d.job_id)] = result.stage_ids[d.candidate_id]
            final.append(Decision(d.candidate_id, d.job_id, d.score, "added"))
        else:
            reason = next(
                (row for row in result.skipped if row.candidate_id == d.candidate_id),
                None,
            )
            code = reason.reason if reason is not None else None
            decision = (
                "already_in_pipeline" if code == "already_in_job" else "ineligible"
            )
            label = (
                (reason.reason_label or reason.reason) if reason is not None else None
            )
            final.append(Decision(d.candidate_id, d.job_id, d.score, decision, label))
    return final, stage_ids


async def _notify(
    db: AsyncSession,
    *,
    decisions: list[Decision],
    stage_ids: dict[tuple[int, int], int],
    jobs_by_id: dict[int, Job],
    candidates_by_id: dict[int, Candidate],
) -> int:
    from app.models.notification import NotificationType
    from app.models.user import User
    from app.services.notification_triggers import emit

    sent = 0
    for d in decisions:
        if d.decision != "added":
            continue
        job = jobs_by_id[d.job_id]
        candidate = candidates_by_id[d.candidate_id]
        recipient_ids = {uid for uid in (job.recruiter_id, job.tac_id) if uid}
        if not recipient_ids:
            continue
        active = (
            await db.scalars(
                select(User.id).where(
                    User.id.in_(recipient_ids), User.is_active.is_(True)
                )
            )
        ).all()
        name = " ".join(x for x in (candidate.name, candidate.lastname) if x).strip()
        for user_id in active:
            try:
                created = await emit(
                    db,
                    user_id=user_id,
                    title=f"Auto-match: {name or 'kandydat'} → {job.title}",
                    message=(
                        f"System dodał kandydata do rekrutacji „{job.title}” "
                        f"(dopasowanie {round(d.score or 0)}/100). Etap: Ogłoszenia."
                    ),
                    ntype=NotificationType.auto_match,
                    related_entity_type="candidate_stage",
                    related_entity_id=stage_ids.get((d.candidate_id, d.job_id)),
                    link=f"/candidates/{d.candidate_id}?job={d.job_id}",
                )
                sent += int(created is not None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[auto_match] notify failed user=%s: %s", user_id, exc)
    await db.commit()
    return sent


PROPOSALS_ACTIVITY_ENTITY = "job_automation"


async def _publish_proposals(
    db: AsyncSession,
    *,
    decisions: list[Decision],
    scored_by_pair: dict[tuple[int, int], Scored],
    revisions: dict[int, str],
    trigger: str,
    run_id: str,
) -> dict[int, int]:
    """Decyzje `proposed` → skrzynka „Propozycje" (źródło `new_cv`).

    W transakcji wołającego, razem z dziennikiem decyzji: propozycja istnieje
    dokładnie wtedy, gdy dziennik mówi `proposed`. Zwraca {job_id: liczba}.
    Dowody to WYŁĄCZNIE nazwy wymagań (allowlista `sanitize_evidence`).
    """
    from app.models.activity import Activity
    from app.services.job_proposals import upsert_proposals

    by_job: dict[int, list[dict]] = {}
    for d in decisions:
        if d.decision != "proposed":
            continue
        scored = scored_by_pair.get((d.candidate_id, d.job_id))
        by_job.setdefault(d.job_id, []).append(
            {
                "candidate_id": d.candidate_id,
                "score": d.score,
                "cv_revision": revisions.get(d.candidate_id),
                "evidence": {
                    "matched_must": list(scored.matching_must) if scored else [],
                    "missing_must": list(scored.gap_must) if scored else [],
                },
            }
        )
    counts: dict[int, int] = {}
    for job_id, rows in by_job.items():
        counts[job_id] = await upsert_proposals(
            db, job_id, rows, source="new_cv", run_id=run_id
        )
        db.add(
            Activity(
                entity_type=PROPOSALS_ACTIVITY_ENTITY,
                entity_id=job_id,
                action="auto_match_proposed",
                user_id=None,
                details={
                    "count": counts[job_id],
                    "candidate_ids": [r["candidate_id"] for r in rows][:20],
                    "trigger": trigger,
                    "run_id": run_id,
                },
            )
        )
    return counts


def _digest_text(count: int) -> str:
    if count == 1:
        return "1 nowa propozycja z nowych CV"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} nowe propozycje z nowych CV"
    return f"{count} nowych propozycji z nowych CV"


async def _notify_proposals(
    db: AsyncSession, *, proposed: dict[int, int], jobs_by_id: dict[int, Job]
) -> int:
    """JEDEN dzienny digest na (rekrutacja, odbiorca).

    Pierwsza propozycja dnia tworzy wpis (`emit` — bramka odbiorcy + dobowy
    dedup `ix_notif_dedup_daily`); kolejne tego samego dnia PODBIJAJĄ licznik
    w istniejącym wpisie zamiast dokładać następne. Licznik = osoby, którym
    dziennik decyzji dał dziś `proposed` w tej rekrutacji.
    """
    from app.core.scheduling import business_today
    from app.models.notification import Notification, NotificationType
    from app.services.notification_triggers import emit

    sent = 0
    ntype = NotificationType.auto_match_proposals
    for job_id, fresh in proposed.items():
        job = jobs_by_id.get(job_id)
        if job is None or not fresh:
            continue
        try:
            today_count = int(
                await db.scalar(
                    text(
                        "SELECT count(DISTINCT candidate_id) "
                        "FROM candidate_auto_match_log "
                        "WHERE job_id = :job_id AND decision = 'proposed' "
                        "AND (created_at AT TIME ZONE :tz)::date = :today"
                    ),
                    {
                        "job_id": job_id,
                        "tz": settings.BUSINESS_TZ,
                        "today": business_today(settings.BUSINESS_TZ),
                    },
                )
                or fresh
            )
            title = f"{_digest_text(today_count)} — {job.title}"[:255]
            message = (
                f"Rekrutacja „{job.title}”: sprawdź skrzynkę „Propozycje”. "
                "Nikt nie został dodany do procesu."
            )
            link = f"/jobs/{job_id}?tab=similar"
            for user_id in {uid for uid in (job.recruiter_id, job.tac_id) if uid}:
                created = await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    ntype=ntype,
                    related_entity_type="job",
                    related_entity_id=job_id,
                    link=link,
                )
                if created is not None:
                    sent += 1
                    continue
                # Dzisiejszy digest już jest (albo odbiorca nie ma dostępu —
                # wtedy UPDATE nie znajdzie wiersza): podbij licznik.
                existing = await db.scalar(
                    select(Notification)
                    .where(
                        Notification.user_id == user_id,
                        Notification.notification_type == ntype,
                        Notification.related_entity_type == "job",
                        Notification.related_entity_id == job_id,
                        func.date(
                            func.timezone(settings.BUSINESS_TZ, Notification.created_at)
                        )
                        == business_today(settings.BUSINESS_TZ),
                    )
                    .order_by(Notification.created_at.desc())
                    .limit(1)
                )
                if existing is not None and existing.title != title:
                    existing.title = title
                    existing.is_read = False
        except Exception as exc:  # noqa: BLE001 — digest nigdy nie psuje biegu
            logger.warning("[auto_match] digest failed job=%s: %s", job_id, exc)
            await db.rollback()
    await db.commit()
    return sent


def _summary(decisions: list[Decision], notified: int) -> dict:
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.decision] = counts.get(d.decision, 0) + 1
    return {"decisions": counts, "notified": notified}


_SCOPED_LIMIT = 300


async def scoped_similarity(
    query_text: str, *, jobs_collection: bool, ids: list[int]
) -> dict[int, float]:
    """Podobieństwo zapytania WYŁĄCZNIE do wskazanych punktów (filtr po id w Qdrancie).

    Bez zawężenia pula „150 najbliższych rekrutacji” składała się głównie
    z zamkniętych, a „200 najbliższych kandydatów” z całej bazy — filtr po
    statusie i dacie odczytu odsiewał potem prawie wszystko.
    """
    if not ids:
        return {}
    from qdrant_client.models import Filter, HasIdCondition

    from app.services import embedding_service as es

    vector = await es.generate_embedding(query_text, input_type="query")
    if vector is None:
        raise AutoMatchUnavailable("query embedding unavailable")

    def _search():
        client = es._get_qdrant_client()
        if client is None:
            raise AutoMatchUnavailable("vector store unavailable")
        try:
            return client.search(
                collection_name=es._jobs_collection()
                if jobs_collection
                else es._collection(),
                query_vector=vector,
                query_filter=Filter(must=[HasIdCondition(has_id=ids)]),
                limit=min(len(ids), _SCOPED_LIMIT),
                with_payload=False,
                with_vectors=False,
            )
        finally:
            client.close()

    import asyncio

    try:
        hits = await asyncio.to_thread(_search)
    except AutoMatchUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — każda awaria Qdranta = ponowienie
        raise AutoMatchUnavailable(f"qdrant: {exc!r}") from exc
    return {int(hit.id): float(hit.score) for hit in hits}


async def run_candidate_event(db: AsyncSession, event: CandidateMatchOutbox) -> dict:
    """Nowe albo odświeżone CV → opublikowane rekrutacje."""
    from app.services.dealbreaker_filters import apply_dealbreakers
    from app.services.embedding_service import _build_candidate_text
    from app.services.pipeline_eligibility import filter_eligible_candidates
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.scoring_service import (
        build_jobs_scoring_contexts,
        rank_jobs_for_candidate,
    )

    candidate = await db.get(Candidate, event.candidate_id)
    if candidate is None:
        return {"skipped": "candidate_missing"}
    revision = event.profile_revision or candidate_revision(candidate)
    open_job_ids = [
        int(jid)
        for jid in (
            await db.scalars(
                select(Job.id).where(
                    Job.status == JobStatus.published,
                    ~select(CandidateStage.id)
                    .where(
                        CandidateStage.job_id == Job.id,
                        CandidateStage.candidate_id == candidate.id,
                    )
                    .exists(),
                )
            )
        ).all()
    ]
    similarity = await scoped_similarity(
        _build_candidate_text(candidate), jobs_collection=True, ids=open_job_ids
    )
    if not similarity:
        return {"decisions": {}, "pool": 0}
    jobs = (await db.scalars(select(Job).where(Job.id.in_(list(similarity))))).all()
    now = datetime.now(timezone.utc)
    usable: list[Job] = []
    ineligible: list[Decision] = []
    for job in jobs:
        allowed = await filter_eligible_candidates(
            db, job=job, candidates=[candidate], now=now
        )
        if not allowed:
            ineligible.append(
                Decision(candidate.id, job.id, None, "ineligible", "bramka przypisania")
            )
            continue
        kept = apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(job))
        if not kept.kept:
            ineligible.append(
                Decision(
                    candidate.id,
                    job.id,
                    None,
                    "ineligible",
                    kept.exclusion_reasons.get(candidate.id) or "dealbreaker",
                )
            )
            continue
        usable.append(job)

    revisions = {candidate.id: revision}
    already = await _logged_pairs(
        db,
        [(candidate.id, j.id) for j in usable]
        + [(d.candidate_id, d.job_id) for d in ineligible],
        revisions,
    )
    usable = [j for j in usable if (candidate.id, j.id) not in already]
    ineligible = [d for d in ineligible if (d.candidate_id, d.job_id) not in already]

    scored: list[Scored] = []
    if usable:
        contexts = await build_jobs_scoring_contexts(db, usable, [candidate.id])
        breakdowns = await rank_jobs_for_candidate(
            candidate, usable, db, similarity_map=similarity, contexts=contexts
        )
        scored = [_scored_from_breakdown(b) for b in breakdowns]
    plan = decide(
        scored,
        min_score=settings.AUTO_MATCH_MIN_SCORE,
        require_must=settings.AUTO_MATCH_REQUIRE_MUST,
        cap=settings.AUTO_MATCH_MAX_JOBS_PER_CANDIDATE,
    )
    jobs_by_id = {j.id: j for j in usable}
    final, stage_ids = await _apply_decisions(
        db,
        decisions=plan,
        scored_by_pair={(s.candidate_id, s.job_id): s for s in scored},
        jobs_by_id=jobs_by_id,
        trigger=event.trigger,
    )
    final += ineligible
    run_id = str(uuid4())
    await _write_log(
        db,
        decisions=final,
        revisions=revisions,
        trigger=event.trigger,
        run_id=run_id,
        stage_ids=stage_ids,
    )
    proposed = await _publish_proposals(
        db,
        decisions=final,
        scored_by_pair={(s.candidate_id, s.job_id): s for s in scored},
        revisions=revisions,
        trigger=event.trigger,
        run_id=run_id,
    )
    await db.commit()
    notified = await _notify(
        db,
        decisions=final,
        stage_ids=stage_ids,
        jobs_by_id=jobs_by_id,
        candidates_by_id={candidate.id: candidate},
    )
    notified += await _notify_proposals(db, proposed=proposed, jobs_by_id=jobs_by_id)
    return {**_summary(final, notified), "pool": len(similarity), "run_id": run_id}


async def run_job_event(db: AsyncSession, event: CandidateMatchOutbox) -> dict:
    """Opublikowana rekrutacja → kandydaci z CV odczytanym w ostatnich N dniach."""
    from app.services.dealbreaker_filters import apply_dealbreakers
    from app.services.embedding_service import _build_job_text
    from app.services.pipeline_eligibility import filter_eligible_candidates
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.scoring_service import rank_candidates_for_job

    job = await db.get(Job, event.job_id)
    if job is None or job.status != JobStatus.published:
        return {"skipped": "job_not_published"}
    since = datetime.now(timezone.utc) - timedelta(
        days=max(1, settings.AUTO_MATCH_JOB_LOOKBACK_DAYS)
    )
    # Tylko profile z pełnego odczytu CV (schemat v7) z ostatnich N dni.
    # `cv_parsed_at` podbijają też nocne biegi masowe na starych CV — bez
    # warunku na schemat „świeże” obejmowałyby historyczne osoby z Traffita.
    fresh_ids = [
        int(cid)
        for cid in (
            await db.scalars(
                select(Candidate.id).where(
                    Candidate.cv_parsed_at >= since,
                    Candidate.cv_extracted_data["_profile_schema"].astext == "2",
                    ~select(CandidateStage.id)
                    .where(
                        CandidateStage.candidate_id == Candidate.id,
                        CandidateStage.job_id == job.id,
                    )
                    .exists(),
                )
            )
        ).all()
    ]
    similarity = await scoped_similarity(
        _build_job_text(job), jobs_collection=False, ids=fresh_ids
    )
    if not similarity:
        return {"decisions": {}, "pool": 0}
    candidates = (
        await db.scalars(select(Candidate).where(Candidate.id.in_(list(similarity))))
    ).all()
    now = datetime.now(timezone.utc)
    eligible = await filter_eligible_candidates(
        db, job=job, candidates=list(candidates), now=now
    )
    kept = apply_dealbreakers(eligible, inputs=search_dealbreaker_inputs(job)).kept
    revisions = {c.id: candidate_revision(c) for c in candidates}
    job_changed_at = job.updated_at or job.created_at
    already = await _logged_pairs(
        db, [(c.id, job.id) for c in kept], revisions, since=job_changed_at
    )
    kept = [c for c in kept if (c.id, job.id) not in already]

    scored: list[Scored] = []
    if kept:
        breakdowns = await rank_candidates_for_job(
            job, kept, db, similarity_map=similarity
        )
        scored = [_scored_from_breakdown(b) for b in breakdowns]
    plan = decide(
        scored,
        min_score=settings.AUTO_MATCH_MIN_SCORE,
        require_must=settings.AUTO_MATCH_REQUIRE_MUST,
        cap=settings.AUTO_MATCH_MAX_CANDIDATES_PER_JOB,
    )
    final, stage_ids = await _apply_decisions(
        db,
        decisions=plan,
        scored_by_pair={(s.candidate_id, s.job_id): s for s in scored},
        jobs_by_id={job.id: job},
        trigger=event.trigger,
    )
    run_id = str(uuid4())
    await _write_log(
        db,
        decisions=final,
        revisions=revisions,
        trigger=event.trigger,
        run_id=run_id,
        stage_ids=stage_ids,
    )
    proposed = await _publish_proposals(
        db,
        decisions=final,
        scored_by_pair={(s.candidate_id, s.job_id): s for s in scored},
        revisions=revisions,
        trigger=event.trigger,
        run_id=run_id,
    )
    await db.commit()
    notified = await _notify(
        db,
        decisions=final,
        stage_ids=stage_ids,
        jobs_by_id={job.id: job},
        candidates_by_id={c.id: c for c in candidates},
    )
    notified += await _notify_proposals(db, proposed=proposed, jobs_by_id={job.id: job})
    return {**_summary(final, notified), "pool": len(similarity), "run_id": run_id}
