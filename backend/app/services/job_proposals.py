"""Skrzynka „Propozycje" rekrutacji — zapis, „Pomiń", licznik otwartych.

Reguły, które łatwo cofnąć „przy okazji":

* ``added`` nigdy się nie cofa.
* ``expired`` (0422) — nowszy przegląd już osoby nie proponuje albo rekrutację
  zamknięto (audyt 06.10.2026, R6, :func:`expire_open_for_job`). Wiersz nie
  głosuje w statusie pary; osoba wraca jako ``proposed`` dopiero z kolejnym
  przeglądem.
* „Pomiń" (``dismissed``) obowiązuje CAŁY zespół i WSZYSTKIE źródła. Kolejny
  przegląd tej samej wersji CV nie wskrzesza osoby; wraca ona wyłącznie wtedy,
  gdy przychodzi z NOWĄ wersją CV (``cv_revision`` inne niż
  ``dismissed_cv_revision``) — jako ``proposed``, z ``first_seen_at = now()``
  i flagą ``previously_dismissed`` w ``evidence``.
* Status liczy się PER PARA (kandydat, rekrutacja), nie per wiersz źródła:
  ``added`` > ``dismissed`` > ``proposed``. Wiersze ``expired`` (0422) się
  nie liczą — para z samych takich wierszy nie jest na żadnej liście.
* ``expired`` stawia WYŁĄCZNIE nocny przegląd bazy (:func:`expire_full_base`):
  propozycja ``full_base``, której nowszy, kompletny przegląd rekrutacji już nie
  zaproponował. Powrót osoby w kolejnym przeglądzie = ``proposed``. Wierszy nie
  kasujemy — ``request_allocation`` czyta istnienie ``full_base`` jako dowód,
  że przegląd był.
* ``added`` stawia wyłącznie dodanie przez człowieka (``mark_added`` wołane
  z ``add_candidates_to_job(mark_proposals=True)``); karta z integracji albo
  automatu propozycji nie zamyka.
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

from sqlalchemy import and_, case, exists, func, literal, or_, select, text, update
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
from app.services.job_proposal_feedback_schema import DISMISS_NOTE_MAX, DISMISS_REASONS

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
# Źródła „z ogłoszeń": nowe CV w bazie i dopasowania z portali. Skrzynka dzieli
# otwarte propozycje na świeże z ogłoszeń (ostatnie POSTING_RECENT_DAYS dni)
# i resztę („z bazy") — ta sama osoba liczy się RAZ, po stronie ogłoszeń.
POSTING_SOURCES = ("new_cv", "job_board")
POSTING_RECENT_DAYS = 7
EXPIRED = "expired"
# Wygasłe propozycje tracą dowody po tylu dniach od ostatniego przeglądu, który
# je zaproponował (``tasks/queue_retention.py``); wiersz zostaje.
EXPIRED_EVIDENCE_RETENTION_DAYS = 30


def _short(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:_MAX_NAME_LEN] if text else None


_MAX_TRAINEE_NOTE = 1000


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
    reassign = raw.get("reassign")
    if isinstance(reassign, Mapping):
        # 0341: przepięcie — skąd (id rekrutacji), na jakim etapie i kiedy
        # osoba była u klienta. Same identyfikatory i data, bez treści.
        clean_reassign: dict[str, Any] = {}
        source_job = reassign.get("job_id")
        if isinstance(source_job, int) and not isinstance(source_job, bool):
            clean_reassign["job_id"] = source_job
        for key in ("stage", "sent_at"):
            if (value := _short(reassign.get(key))) is not None:
                clean_reassign[key] = value[:32]
        if clean_reassign.get("job_id") is not None:
            out["reassign"] = clean_reassign
    trainee = raw.get("trainee")
    if isinstance(trainee, Mapping):
        # 0374: przekazanie przez praktykanta po rozmowie — kto przekazał
        # i jego wiadomość dla rekrutera (świadomie tekst: po to jest).
        by_user = trainee.get("user_id")
        note = trainee.get("note")
        if isinstance(by_user, int) and not isinstance(by_user, bool):
            clean_trainee: dict[str, Any] = {"user_id": by_user}
            if isinstance(note, str) and note.strip():
                clean_trainee["note"] = note.strip()[:_MAX_TRAINEE_NOTE]
            # Kandydat deklaruje wyłącznie umowę o pracę — plakietka na karcie.
            if trainee.get("employment_only") is True:
                clean_trainee["employment_only"] = True
            out["trainee"] = clean_trainee
    auto_match = raw.get("auto_match")
    if isinstance(auto_match, Mapping):
        # 30.09.2026: dopasowanie z portalu (JJIT/RocketJobs, źródło
        # ``job_board``) — wynik, portal i trafione must-have. Same liczby
        # i nazwy wymagań, jak reszta dowodów.
        clean_auto: dict[str, Any] = {}
        auto_score = auto_match.get("score")
        if isinstance(auto_score, (int, float)) and not isinstance(auto_score, bool):
            clean_auto["score"] = int(round(auto_score))
        if (portal := _short(auto_match.get("source"))) is not None:
            clean_auto["source"] = portal[:24]
        if must_hit := _names(auto_match.get("must_hit")):
            clean_auto["must_hit"] = must_hit[:8]
        must_total = auto_match.get("must_total")
        if isinstance(must_total, int) and not isinstance(must_total, bool):
            clean_auto["must_total"] = must_total
        if clean_auto:
            out["auto_match"] = clean_auto
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
    revive_expired: bool = True,
    first_seen_at: Optional[datetime] = None,
) -> int:
    """Zapisz propozycje jednego źródła. Zwraca liczbę przetworzonych par.

    ``first_seen_at`` (06.10.2026, R7) ustawia datę NOWEGO wiersza — przeniesienie
    starej karty niesie datę otwarcia procesu zamiast dnia przeniesienia.
    Istniejącego wiersza nie zmienia (konflikt nie rusza ``first_seen_at``).

    ``rows``: ``{"candidate_id": int, "score": number|None, "evidence":
    dict|None, "cv_revision": str|None}``. Wersja CV to ta sama wartość co
    ``candidate_auto_match_log.profile_revision``
    (``auto_match_outbox.candidate_revision``); ``cv_revision`` z argumentu jest
    domyślną dla wierszy, które własnej nie niosą.

    Konflikt ``(job_id, candidate_id, source)`` odświeża ``last_seen_at``,
    ``score``, ``evidence``, ``cv_revision`` i ``run_id`` (gdy podane).
    ``status`` i ``first_seen_at`` zostają — z dwoma wyjątkami: wiersz
    ``expired`` tego źródła wraca jako ``proposed`` (osoba znowu przeszła
    przegląd; ``revive_expired=False`` to wyłącza), a osoba pominięta wraca jako
    ``proposed``, gdy przychodzi z niepustą wersją CV inną niż ta, przy której
    ją pominięto. Ta sama wersja (albo brak wersji) nie wskrzesza.
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
        if first_seen_at is not None:
            by_candidate[candidate_id]["first_seen_at"] = first_seen_at
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
                "status": (
                    case(
                        (JobProposal.status == EXPIRED, literal("proposed")),
                        else_=JobProposal.status,
                    )
                    if revive_expired
                    else JobProposal.status
                ),
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
                dismiss_reason = NULL,
                dismiss_note = NULL,
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


def _dismiss_reason(reason: Optional[str]) -> Optional[str]:
    """Powód spoza słownika CHECK-a to błąd programisty, nie danych."""
    if reason is None:
        return None
    if reason not in DISMISS_REASONS:
        raise ValueError(f"Nieznany powód pominięcia: {reason!r}")
    return reason


def _dismiss_note(note: Optional[str]) -> Optional[str]:
    clean = (note or "").strip()
    return clean[:DISMISS_NOTE_MAX] or None


async def dismiss(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_id: int,
    user_id: Optional[int],
    cv_revision: Optional[str] = None,
    reason: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    """„Pomiń" — dla całego zespołu i ze WSZYSTKICH źródeł. Zwraca liczbę wierszy.

    ``reason``/``note`` (0405) to powód decyzji — trasa wymaga powodu, ale
    wołający wewnętrzni (testy, automaty) mogą go nie znać.

    Stempluje ``dismissed_at`` i ``dismissed_cv_revision``: bieżącą wersję CV
    (podaje ją wołający — ``candidate_revision``), a gdy jej nie zna, wersję,
    dla której policzono propozycję. ``added`` zostaje nietknięte; powtórne
    pominięcie nic nie zmienia (0). Wygasły wiersz (``expired``) też dostaje
    pominięcie — osoba bywa widoczna z innego źródła (podobne projekty), a bez
    tego „Pomiń” nic by nie zapisało i wróciłaby po odświeżeniu.
    """
    result = await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == job_id,
            JobProposal.candidate_id == candidate_id,
            JobProposal.status.in_(("proposed", EXPIRED)),
        )
        .values(
            status="dismissed",
            dismissed_by=user_id,
            dismissed_at=func.now(),
            dismissed_cv_revision=func.coalesce(
                _revision(cv_revision), JobProposal.cv_revision
            ),
            dismiss_reason=_dismiss_reason(reason),
            dismiss_note=_dismiss_note(note),
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
    reason: Optional[str] = None,
    note: Optional[str] = None,
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
            dismiss_reason=_dismiss_reason(reason),
            dismiss_note=_dismiss_note(note),
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
            dismiss_reason=None,
            dismiss_note=None,
        )
    )
    return int(result.rowcount or 0)


async def expire_open_for_job(db: AsyncSession, *, job_id: int) -> int:
    """Zamknięcie rekrutacji wygasza jej otwarte propozycje (0422, R6).

    Do 06.10.2026 172 propozycje wisiały w zamkniętych rekrutacjach i liczyły
    się w skrótach. ``added`` i ``dismissed`` zostają — to decyzje ludzi.
    Samo ponowne otwarcie ich nie wskrzesza; osoba wraca jako ``proposed``
    dopiero, gdy zaproponuje ją kolejny przegląd (``upsert_proposals``).
    Zwraca liczbę wierszy.
    """
    result = await db.execute(
        update(JobProposal)
        .where(JobProposal.job_id == job_id, JobProposal.status == "proposed")
        .values(status=EXPIRED)
        .execution_options(synchronize_session=False)
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


async def expire_full_base(db: AsyncSession, *, job_id: int, run_id: str) -> int:
    """Otwarte propozycje nocnego przeglądu, których przegląd ``run_id`` już nie daje → ``expired``.

    Woła wyłącznie publikacja NAJNOWSZEGO przeglądu rekrutacji
    (``auto_full_review._publish``). Wygasa wyłącznie osoba, którą ten przegląd
    naprawdę OCENIŁ i nie zaproponował (wiersz ``evaluated`` ze zmierzonym
    podobieństwem albo odrzucony przez filtry), oraz osoba spoza jego populacji
    (usunięta, na czarnej liście, już w rekrutacji). Osoba bez oceny — awaria
    partii, zmiana w trakcie przeglądu (``failed``), ``stale``,
    ``missing_index``, ``unavailable`` — zostaje: brak oceny to nie „nie pasuje”
    (przegląd #2058: nocny import Traffita i zmiana modelu wektorów gasiłyby
    propozycje osób, których nikt nie ocenił). Publikacja stempluje ``run_id``
    każdej zaproponowanej osoby, więc „nie zaproponował” = inny ``run_id``.
    Pominięte i dodane zostają. Zwraca liczbę wierszy.
    """
    from app.models.candidate_search_run import CandidateSearchResult

    row = CandidateSearchResult
    in_run = (row.run_id == run_id) & (row.candidate_id == JobProposal.candidate_id)
    evaluated_not_proposed = exists(
        select(literal(1)).where(
            in_run,
            row.state == "evaluated",
            or_(row.measurement == "measured", row.eligible.is_(False)),
        )
    )
    outside_population = ~exists(select(literal(1)).where(in_run))
    result = await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == job_id,
            JobProposal.source == "full_base",
            JobProposal.status == "proposed",
            JobProposal.run_id.is_distinct_from(run_id),
            or_(evaluated_not_proposed, outside_population),
        )
        .values(status=EXPIRED)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


# Wygasłe propozycje po ``EXPIRED_EVIDENCE_RETENTION_DAYS`` tracą dowody (nazwy
# wymagań); zostaje sam wiersz i flaga „wcześniej pominięty”. Paczkami — tak
# woła ją `tasks/queue_retention._prune` (`:cutoff`, `:batch`).
PRUNE_EXPIRED_EVIDENCE = text(
    """
    UPDATE job_proposals
       SET evidence = CASE
               WHEN jsonb_typeof(evidence) = 'object'
                    AND evidence ? 'previously_dismissed'
               THEN '{"previously_dismissed": true}'::jsonb
               ELSE '{}'::jsonb
           END
     WHERE id IN (
        SELECT id FROM job_proposals
         WHERE status = 'expired'
           AND last_seen_at < :cutoff
           AND evidence IS NOT NULL
           AND evidence <> '{}'::jsonb
           AND evidence <> '{"previously_dismissed": true}'::jsonb
         ORDER BY last_seen_at
         LIMIT :batch
     )
    """
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
    """Status pary z wierszy źródeł: added > dismissed > proposed.

    Wiersze ``expired`` nie głosują: para z samych takich wierszy ma status
    ``expired`` i nie stoi na żadnej liście. Zapytania i tak odsiewają je
    w ``WHERE`` (:func:`_live`), żeby nie liczyły się do wyniku ani źródeł.
    """
    return case(
        (func.bool_or(JobProposal.status == "added"), "added"),
        (func.bool_or(JobProposal.status == "dismissed"), "dismissed"),
        (func.bool_or(JobProposal.status == "proposed"), "proposed"),
        else_=EXPIRED,
    )


def _live():
    """Wiersz bierze udział w statusie pary (``expired`` — nie)."""
    return JobProposal.status != EXPIRED


async def open_counts_for_jobs(
    db: AsyncSession, job_ids: Sequence[int], *, source: Optional[str] = None
) -> dict[int, int]:
    """Ile osób czeka w skrzynce rekrutacji — ZESPOŁOWO, nie per użytkownik.

    Jedno zapytanie dla całej strony listy. Ta sama widoczność co
    :func:`list_for_job` ze ``status="proposed"``. Rekrutacje bez otwartych
    propozycji nie trafiają do słownika (wołający czyta ``.get(job_id, 0)``).
    ``source`` zawęża do par, które ma dane źródło (np. ``full_base`` —
    nocny przegląd bazy); status pary liczy się jak zwykle ze wszystkich.
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
            _live(),
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id),
            ~_globally_blacklisted(JobProposal.candidate_id),
        )
        .group_by(JobProposal.job_id, JobProposal.candidate_id)
        .having(
            _pair_status() == "proposed",
            *(
                (func.bool_or(JobProposal.source == source),)
                if source is not None
                else ()
            ),
        )
        .subquery()
    )
    rows = await db.execute(
        select(pairs.c.job_id, func.count()).group_by(pairs.c.job_id)
    )
    return {int(job_id): int(n) for job_id, n in rows.all()}


async def fresh_open_pairs(
    db: AsyncSession,
    *,
    since: datetime,
    sources: Sequence[str],
    job_ids_subquery: Any,
) -> list[tuple[int, int]]:
    """Otwarte pary (rekrutacja, kandydat), których pierwszy wiersz z ``sources``
    pojawił się od ``since`` — najlepszy wynik pierwszy w obrębie rekrutacji.

    Ta sama widoczność co skrzynka (bez osób w rekrutacji i czarnej listy,
    status pary ``proposed``). Czyta poranny dzwonek „Do przejrzenia”.
    """
    first_seen = func.min(JobProposal.first_seen_at).filter(
        JobProposal.source.in_(list(sources))
    )
    rows = await db.execute(
        select(JobProposal.job_id, JobProposal.candidate_id)
        .where(
            JobProposal.job_id.in_(job_ids_subquery),
            _live(),
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id),
            ~_globally_blacklisted(JobProposal.candidate_id),
        )
        .group_by(JobProposal.job_id, JobProposal.candidate_id)
        .having(_pair_status() == "proposed", first_seen >= since)
        .order_by(
            JobProposal.job_id,
            func.max(JobProposal.score).desc().nullslast(),
            JobProposal.candidate_id,
        )
    )
    return [(int(job_id), int(cid)) for job_id, cid in rows.all()]


# Runda 10 (R10-N7-1): sufit listy pominiętych w odpowiedzi skrzynki — pamięć
# widoku, nie raport. Rekrutacja z tysiącami pominięć to i tak wyjątek.
MAX_DISMISSED_IDS = 5000


async def dismissed_candidate_ids(
    db: AsyncSession, *, job_id: int, limit: int = MAX_DISMISSED_IDS
) -> list[int]:
    """Osoby pominięte w tej rekrutacji (status pary ``dismissed``).

    Front odsiewa je ze WSZYSTKICH źródeł propozycji (żywy przegląd, podobne
    projekty, rekomendacje) — te źródła nie czytają ``job_proposals``, więc bez
    tej listy „Pomiń" działało wyłącznie w skrzynce, a osoba wracała po
    odświeżeniu strony. Najnowsze pominięcia pierwsze (sufit ``limit``).
    """
    rows = await db.execute(
        select(JobProposal.candidate_id)
        .where(JobProposal.job_id == job_id, _live())
        .group_by(JobProposal.candidate_id)
        .having(_pair_status() == "dismissed")
        .order_by(func.max(JobProposal.dismissed_at).desc().nullslast())
        .limit(limit)
    )
    return [int(cid) for (cid,) in rows.all()]


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
    # Kiedy osoba ostatnio przyszła ze źródła „z ogłoszeń” (`POSTING_SOURCES`);
    # `None` = żaden wiersz pary nie pochodzi z ogłoszeń.
    posting_seen_at: Optional[datetime] = None


def _posting_seen_at():
    return func.max(JobProposal.first_seen_at).filter(
        JobProposal.source.in_(POSTING_SOURCES)
    )


def _pairs_for_job(job_id: int, status: str, *columns):
    """Pary (kandydat, rekrutacja) o danym statusie — jedna pozycja na osobę.

    Jedyna definicja „co jest na liście”: czytają ją strona skrzynki
    (:func:`list_for_job`) i podział licznika (:func:`open_split_counts`),
    więc suma podziału nie może rozjechać się z ``total`` listy.
    """
    grouped = (
        select(JobProposal.candidate_id.label("candidate_id"), *columns)
        .where(JobProposal.job_id == job_id, _live())
        .group_by(JobProposal.candidate_id)
        .having(_pair_status() == status)
    )
    if status == "proposed":
        grouped = grouped.where(
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id),
            ~_globally_blacklisted(JobProposal.candidate_id),
        )
    return grouped


async def open_split_counts(
    db: AsyncSession, *, job_id: int, since: datetime
) -> dict[str, int]:
    """Otwarte propozycje w podziale: świeże z ogłoszeń i reszta („z bazy”).

    ``postings_recent`` = osoby, które mają wiersz ze źródła z
    ``POSTING_SOURCES`` zaproponowany od ``since``; ``base`` = pozostałe.
    Te same pary co :func:`list_for_job` ze ``status="proposed"``, więc
    ``postings_recent + base`` równa się ``total`` listy (przed ukryciem
    osób przez bramkę widoczności na stronie).
    """
    recent = func.coalesce(
        func.bool_or(
            and_(
                JobProposal.source.in_(POSTING_SOURCES),
                JobProposal.first_seen_at >= since,
            )
        ),
        False,
    )
    sub = _pairs_for_job(job_id, "proposed", recent.label("posting_recent")).subquery()
    row = (
        await db.execute(
            select(
                func.count().filter(sub.c.posting_recent),
                func.count().filter(~sub.c.posting_recent),
            ).select_from(sub)
        )
    ).one()
    return {"postings_recent": int(row[0] or 0), "base": int(row[1] or 0)}


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
    grouped = _pairs_for_job(
        job_id,
        status,
        func.array_agg(func.distinct(JobProposal.source)).label("sources"),
        func.max(JobProposal.score).label("score"),
        func.min(JobProposal.first_seen_at).label("first_seen_at"),
        func.max(JobProposal.first_seen_at).label("newest_seen_at"),
        func.max(JobProposal.last_seen_at).label("last_seen_at"),
        # 0341: przepięcia (osoby już wysłane do klienta przy podobnym
        # requeście) stoją w kolejce przed resztą propozycji.
        func.bool_or(JobProposal.source == "reassign").label("is_reassign"),
        _posting_seen_at().label("posting_seen_at"),
    )
    sub = grouped.subquery()
    total = int(await db.scalar(select(func.count()).select_from(sub)) or 0)
    page = (
        await db.execute(
            select(sub)
            .order_by(
                sub.c.is_reassign.desc(),
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
                _live(),
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
            posting_seen_at=row.posting_seen_at,
        )
        for row in page
    ]
    return out, total


@dataclass(frozen=True)
class TopProposal:
    job_id: int
    candidate_id: int
    score: Optional[float]


async def top_open_by_job(
    db: AsyncSession,
    job_ids: Sequence[int],
    *,
    source: str = "full_base",
    per_job: int = 3,
) -> list[TopProposal]:
    """Najlepsze otwarte propozycje danego źródła — po ``per_job`` na rekrutację.

    Ta sama widoczność co lista skrzynki (:func:`_pairs_for_job`): bez
    wierszy ``expired``, bez osób już w pipeline'ie i z globalnej czarnej
    listy, status pary ``proposed``. Kolejność: wynik źródła malejąco, potem
    kandydat (stabilna). Jedno zapytanie dla wszystkich rekrutacji.
    """
    _validate_source(source)
    ids = sorted({int(j) for j in job_ids})
    if not ids or per_job <= 0:
        return []
    pairs = (
        select(
            JobProposal.job_id.label("job_id"),
            JobProposal.candidate_id.label("candidate_id"),
            func.max(JobProposal.score)
            .filter(JobProposal.source == source)
            .label("score"),
        )
        .where(
            JobProposal.job_id.in_(ids),
            _live(),
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id),
            ~_globally_blacklisted(JobProposal.candidate_id),
        )
        .group_by(JobProposal.job_id, JobProposal.candidate_id)
        .having(
            _pair_status() == "proposed",
            func.bool_or(JobProposal.source == source),
        )
        .subquery()
    )
    ranked = select(
        pairs.c.job_id,
        pairs.c.candidate_id,
        pairs.c.score,
        func.row_number()
        .over(
            partition_by=pairs.c.job_id,
            order_by=(pairs.c.score.desc().nullslast(), pairs.c.candidate_id),
        )
        .label("rank"),
    ).subquery()
    rows = await db.execute(
        select(ranked.c.job_id, ranked.c.candidate_id, ranked.c.score)
        .where(ranked.c.rank <= per_job)
        .order_by(ranked.c.job_id, ranked.c.rank)
    )
    return [
        TopProposal(
            job_id=int(job_id),
            candidate_id=int(candidate_id),
            score=float(score) if score is not None else None,
        )
        for job_id, candidate_id, score in rows.all()
    ]
