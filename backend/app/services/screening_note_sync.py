"""Odpowiedzi z notatek do arkusza screeningu pary (decyzje Artura 07.10.2026).

Rekruterzy wpisywali odpowiedzi na pytania screeningowe w kartach
rekomendacji w Traffit (pomiar 06.10.2026: 3 560 kart, 11 662 odpowiedzi;
w NEXUSIE było 12 arkuszy). Karta (0413) trzyma je w
``recommendation_cards.note_answers``; ten moduł przepisuje je do arkusza
screeningu (``candidate_stages.screening_answers``). Zmienia regułę 0413
„odpowiedzi z notatek nie trafiają do arkusza”: arkusz z notatki od razu widzi
klient (portal, generator CV) i liczy się w ocenie pary jak arkusz człowieka.

To JEDYNE miejsce, w którym notatka pisze arkusz (strażnik
``tests/test_screening_note_sync_guard.py``). Zasady:

* Odpowiedź z notatki ma pochodzenie ``note_sync``. Arkusz „należy do
  automatu”, gdy wszystkie odpowiedzi są ``note_sync`` bez trafienia „Odpada,
  gdy…”, a ``experience_checks``, ``notes`` i ``internal_note`` są puste,
  ``overall_fit == "uncertain"``. Każdy inny niepusty arkusz jest ludzki —
  automat go nie dotyka (także jego kopii na innych wierszach pary). Zapis
  człowieka zamienia ``note_sync`` na ``note_import``.
* Przypięcie do pytań Championa (``map_note_answers``): po treści pytania
  (podobieństwo ≥ 0,5 z przewagą ≥ 0,1, jeden do jednego); po numerze tylko
  wtedy, gdy liczba odpowiedzi w notatce = liczba pytań, numeracja jest
  kompletna i nie przeczy dopasowaniom po treści. Szara strefa (0,3–0,5)
  i konflikty są pomijane, puste odpowiedzi też.
* Arkusz trafia na najnowszy wiersz etapu pary (blokada wszystkich wierszy
  pary); kopie arkusza automatu na starszych wierszach bieżącej próby
  dostają tę samą treść albo ``NULL``. Notatka sprzed bieżącej próby
  procesu nie zasila arkusza.
* ``answered_at``/``answered_by`` = data i autor notatki. Nie zapisujemy
  ``Activity screening_answered`` (liczą ją statystyki zespołu) — osobna
  akcja ``screening_synced_from_note``.
* Po zmianie arkusza wyniki dopasowania kandydata są oznaczane jako stare
  (warstwa ``champion_fit`` czyta arkusz).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError
from rapidfuzz import fuzz
from sqlalchemy import null, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.champion import (
    SCREENING_ANSWERS_MAX,
    SCREENING_TEXT_MAX_CHARS,
    ScreeningAnswerItem,
    ScreeningAnswers,
)

logger = logging.getLogger(__name__)

SYNC_ORIGIN = "note_sync"
HUMAN_ORIGIN = "note_import"
ACTIVITY_ACTION = "screening_synced_from_note"

CONTENT_MIN = 0.5
CONTENT_MARGIN = 0.1
GRAY_MIN = 0.3

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_CLEAR = "clear"
ACTION_NOOP = "noop"
ACTION_SKIP = "skip"

# Powody (raport próby uzupełnienia historii).
REASON_HUMAN_SHEET = "human_sheet"
REASON_NO_STAGE = "no_stage"
REASON_NO_JOB = "no_job"
REASON_NO_QUESTIONS = "no_questions"
REASON_NO_ANSWERS = "no_answers"
REASON_PREVIOUS_ATTEMPT = "previous_attempt"
REASON_NO_MATCH = "no_match"
REASON_UNREADABLE = "unreadable_sheet"


def enabled() -> bool:
    return bool(settings.SCREENING_NOTE_SYNC_ENABLED)


# ── Czyste reguły ────────────────────────────────────────────────────────────

_PREFIX_RE = re.compile(
    r"^\s*(?:(?:(?:pytanie|question)\b|pyt\.)\s*\d{0,2}\s*[:.)–-]?"
    r"|[pq]\s*\d{1,2}\s*[:.)–-]?|\d{1,2}\s*[:.)–-])\s*",
    re.I,
)
_NOT_WORD_RE = re.compile(r"[^\w]+")


def _normalize(text: str) -> str:
    """Treść pytania do porównania: bez numeru, polskich znaków i interpunkcji."""
    text = _PREFIX_RE.sub("", (text or "").strip(), count=1)
    text = text.lower().replace("ł", "l")
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    return _NOT_WORD_RE.sub(" ", text).strip()


def similarity(left: str, right: str) -> float:
    """Podobieństwo treści dwóch pytań, 0–1 (kolejność słów nie ma znaczenia)."""
    a, b = _normalize(left), _normalize(right)
    if not a or not b:
        return 0.0
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b)) / 100.0


@dataclass(frozen=True)
class AnswerMatch:
    question_id: str
    response: str
    how: str  # "content" | "number"
    score: Optional[float]


@dataclass(frozen=True)
class MappingResult:
    matches: tuple[AnswerMatch, ...] = ()
    skipped: Mapping[str, int] = field(default_factory=dict)

    @property
    def by_content(self) -> int:
        return sum(1 for match in self.matches if match.how == "content")

    @property
    def by_number(self) -> int:
        return sum(1 for match in self.matches if match.how == "number")


def map_note_answers(
    questions: Mapping[str, str],
    items: Sequence[Mapping[str, Any]],
    *,
    content_min: float = CONTENT_MIN,
    use_numbers: bool = True,
) -> MappingResult:
    """Odpowiedzi z notatki przypięte do pytań Championa (``{id: treść}``).

    ``questions`` w kolejności profilu — numer pytania to pozycja. Wynik
    jest jeden do jednego; wątpliwe odpowiedzi są pomijane z powodem.
    """
    question_ids = list(questions)
    skipped: Counter[str] = Counter()
    entries: list[tuple[int, Optional[int], str, str]] = []
    numbers: list[Optional[int]] = []
    rows = [item for item in items if isinstance(item, Mapping)]
    for index, item in enumerate(rows):
        number = item.get("number")
        number = (
            number
            if isinstance(number, int) and not isinstance(number, bool) and number > 0
            else None
        )
        numbers.append(number)
        answer = str(item.get("answer") or "").strip()
        if not answer:
            skipped["empty"] += 1
            continue
        entries.append((index, number, str(item.get("question") or "").strip(), answer))
    if not question_ids or not entries:
        return MappingResult((), dict(skipped))

    # Po treści pytania.
    by_content: dict[int, tuple[str, float]] = {}
    scores: dict[int, list[float]] = {}
    status: dict[int, str] = {}
    for index, _, text, _ in entries:
        if not text:
            status[index] = "no_text"
            continue
        row = [similarity(text, questions[qid]) for qid in question_ids]
        scores[index] = row
        ranked = sorted(row, reverse=True)
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else 0.0
        if best >= content_min and best - second >= CONTENT_MARGIN:
            by_content[index] = (question_ids[row.index(best)], best)
            status[index] = "content"
        elif best >= content_min:
            status[index] = "ambiguous"
        elif best >= GRAY_MIN:
            status[index] = "gray"
        else:
            status[index] = "different"
    claims = Counter(qid for qid, _ in by_content.values())
    for index, (qid, _) in list(by_content.items()):
        if claims[qid] > 1:
            del by_content[index]
            status[index] = "conflict"

    # Po numerze: komplet odpowiedzi 1..N i zgodność z dopasowaniami po treści.
    count = len(question_ids)
    numbering_ok = (
        use_numbers
        and len(numbers) == count
        and sorted(n for n in numbers if n is not None) == list(range(1, count + 1))
        and all(
            numbers[index] is not None and question_ids[numbers[index] - 1] == qid
            for index, (qid, _) in by_content.items()
        )
    )
    taken = {qid for qid, _ in by_content.values()}
    matches: list[AnswerMatch] = []
    for index, number, _, answer in entries:
        if index in by_content:
            qid, score = by_content[index]
            matches.append(AnswerMatch(qid, answer, "content", round(score, 3)))
            continue
        reason = status.get(index, "no_text")
        if numbering_ok and number is not None:
            qid = question_ids[number - 1]
            row = scores.get(index)
            allowed = reason in ("no_text", "different") or (
                reason == "ambiguous"
                and row is not None
                and row[number - 1] >= max(row) - CONTENT_MARGIN
            )
            if allowed and qid not in taken:
                taken.add(qid)
                score = round(row[number - 1], 3) if row is not None else None
                matches.append(AnswerMatch(qid, answer, "number", score))
                continue
        skipped[reason] += 1
    order = {qid: position for position, qid in enumerate(question_ids)}
    matches.sort(key=lambda match: order[match.question_id])
    return MappingResult(tuple(matches), dict(skipped))


def _parsed(raw: Any) -> Optional[ScreeningAnswers]:
    if not isinstance(raw, dict):
        return None
    try:
        return ScreeningAnswers.model_validate(raw)
    except ValidationError:
        return None


def is_blank(raw: Any) -> bool:
    """Arkusz bez żadnej treści (``None``, ``{}``, ``{"answers": []}``)."""
    if raw is None or raw == {}:
        return True
    sheet = _parsed(raw)
    if sheet is None:
        return False
    return (
        not any(
            a.response.strip() or a.deal_breaker_hit or a.skipped for a in sheet.answers
        )
        and not sheet.experience_checks
        and not sheet.notes.strip()
        and not (sheet.internal_note or "").strip()
        and sheet.overall_fit == "uncertain"
    )


def is_sync_owned(raw: Any) -> bool:
    """Arkusz w całości przepisany z notatki — tylko taki automat poprawia."""
    sheet = _parsed(raw)
    if sheet is None or not sheet.answers:
        return False
    return (
        all(
            a.origin == SYNC_ORIGIN and not a.deal_breaker_hit and not a.skipped
            for a in sheet.answers
        )
        and not sheet.experience_checks
        and not sheet.notes.strip()
        and not (sheet.internal_note or "").strip()
        and sheet.overall_fit == "uncertain"
    )


def humanize_origins(sheet: ScreeningAnswers) -> ScreeningAnswers:
    """Zapis człowieka: odpowiedzi ``note_sync`` stają się ``note_import``."""
    for answer in sheet.answers:
        if answer.origin == SYNC_ORIGIN:
            answer.origin = HUMAN_ORIGIN
    return sheet


def build_sheet(
    questions: Mapping[str, str],
    matches: Sequence[AnswerMatch],
    *,
    note_at: Optional[datetime],
    author_id: Optional[int],
    previous: Any,
) -> dict[str, Any]:
    """Arkusz automatu z dopasowanych odpowiedzi (JSON gotowy do zapisu)."""
    from app.services import screening_sheets  # noqa: PLC0415 — cykl importów

    sheet = ScreeningAnswers(
        answers=[
            ScreeningAnswerItem(
                question_id=match.question_id,
                response=match.response[:SCREENING_TEXT_MAX_CHARS],
                origin=SYNC_ORIGIN,
            )
            for match in list(matches)[:SCREENING_ANSWERS_MAX]
        ],
        overall_fit="uncertain",
    )
    screening_sheets.stamp_sheet(
        sheet,
        questions=questions,
        previous=previous if is_sync_owned(previous) else None,
        user_id=author_id,
        now=note_at or datetime.now(timezone.utc),
    )
    return sheet.model_dump(mode="json")


def _canonical(raw: Any) -> Any:
    sheet = _parsed(raw)
    return sheet.model_dump(mode="json") if sheet is not None else raw


@dataclass(frozen=True)
class RowsPlan:
    action: str
    reason: Optional[str]
    # indeks wiersza (0 = najnowszy) → nowa treść albo ``None`` (= wyczyść)
    updates: Mapping[int, Optional[dict[str, Any]]]


def plan_rows(
    sheets: Sequence[Any],
    desired: Optional[dict[str, Any]],
    *,
    reason: Optional[str] = None,
) -> RowsPlan:
    """Co zrobić z arkuszami wierszy pary (najnowszy pierwszy)."""
    if not sheets:
        return RowsPlan(ACTION_SKIP, REASON_NO_STAGE, {})
    for raw in sheets:
        if not is_blank(raw) and not is_sync_owned(raw):
            if _parsed(raw) is None:
                return RowsPlan(ACTION_SKIP, REASON_UNREADABLE, {})
            return RowsPlan(ACTION_SKIP, REASON_HUMAN_SHEET, {})
    owned = [index for index, raw in enumerate(sheets) if is_sync_owned(raw)]
    if desired is None:
        updates: dict[int, Optional[dict[str, Any]]] = {index: None for index in owned}
        return RowsPlan(ACTION_CLEAR if updates else ACTION_NOOP, reason, updates)
    target = _canonical(desired)
    updates = {}
    if _canonical(sheets[0]) != target:
        updates[0] = desired
    for index in owned:
        if index and _canonical(sheets[index]) != target:
            updates[index] = desired
    if not updates:
        return RowsPlan(ACTION_NOOP, reason, {})
    return RowsPlan(ACTION_UPDATE if owned else ACTION_CREATE, reason, updates)


# ── Baza ─────────────────────────────────────────────────────────────────────


@dataclass
class PairPlan:
    candidate_id: int
    job_id: int
    action: str
    reason: Optional[str] = None
    stage_id: Optional[int] = None
    note_id: Optional[int] = None
    question_ids: tuple[str, ...] = ()
    by_content: int = 0
    by_number: int = 0
    skipped: Mapping[str, int] = field(default_factory=dict)
    # (wiersz etapu, poprzednia treść, nowa treść) — do zapisu i do odwrócenia
    changes: list[tuple[Any, Any, Optional[dict[str, Any]]]] = field(
        default_factory=list
    )

    def summary(self) -> dict[str, Any]:
        """Same identyfikatory i liczby (raport, paragon, dziennik)."""
        return {
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "action": self.action,
            "reason": self.reason,
            "stage_id": self.stage_id,
            "note_id": self.note_id,
            "question_ids": list(self.question_ids),
            "by_content": self.by_content,
            "by_number": self.by_number,
            "rows": [row.id for row, _, _ in self.changes],
        }


def _moment(value: Any) -> Optional[datetime]:
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def plan_pair(
    db: AsyncSession, *, candidate_id: int, job_id: int, lock: bool
) -> PairPlan:
    """Plan dla pary. ``lock=True`` blokuje wiersze etapów (zapis)."""
    from app.models.job import Job  # noqa: PLC0415
    from app.models.note import Note  # noqa: PLC0415
    from app.models.recommendation_card import RecommendationCard  # noqa: PLC0415
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services import screening_sheets  # noqa: PLC0415
    from app.services.candidate_claim import load_process  # noqa: PLC0415
    from app.services.recommendation_card_rules import (  # noqa: PLC0415
        current_answers,
    )
    from app.services.recommendation_cards import attempt_started  # noqa: PLC0415

    out = PairPlan(candidate_id=candidate_id, job_id=job_id, action=ACTION_SKIP)
    query = (
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    rows = list((await db.execute(query)).scalars().all())
    if not rows:
        out.reason = REASON_NO_STAGE
        return out
    started = attempt_started(
        await load_process(db, candidate_id=candidate_id, job_id=job_id)
    )
    started = _moment(started)
    if started is not None:
        rows = [
            row
            for row in rows
            if row.moved_at is not None and _moment(row.moved_at) >= started
        ]
        if not rows:
            out.reason = REASON_PREVIOUS_ATTEMPT
            return out
    out.stage_id = rows[0].id

    profile = await db.scalar(select(Job.champion_profile).where(Job.id == job_id))
    questions = screening_sheets.question_texts(profile)
    note_answers = await db.scalar(
        select(RecommendationCard.note_answers).where(
            RecommendationCard.candidate_id == candidate_id,
            RecommendationCard.job_id == job_id,
        )
    )
    desired: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    items = (
        note_answers.get("items") if isinstance(note_answers, Mapping) else None
    ) or []
    current = current_answers(note_answers, attempt_started=started)
    if not items:
        reason = REASON_NO_ANSWERS
    elif current is None:
        reason = REASON_PREVIOUS_ATTEMPT
    elif not questions:
        reason = REASON_NO_QUESTIONS
    else:
        note_id = current.get("note_id")
        out.note_id = note_id if isinstance(note_id, int) else None
        mapping = map_note_answers(questions, current["items"])
        out.by_content, out.by_number = mapping.by_content, mapping.by_number
        out.skipped = mapping.skipped
        if not mapping.matches:
            reason = REASON_NO_MATCH
        else:
            author_id = (
                await db.scalar(select(Note.author_id).where(Note.id == out.note_id))
                if out.note_id is not None
                else None
            )
            desired = build_sheet(
                questions,
                mapping.matches,
                note_at=_moment(current.get("at")),
                author_id=author_id,
                previous=rows[0].screening_answers,
            )
            out.question_ids = tuple(m.question_id for m in mapping.matches)
    plan = plan_rows([row.screening_answers for row in rows], desired, reason=reason)
    out.action, out.reason = plan.action, plan.reason
    out.changes = [
        (rows[index], rows[index].screening_answers, value)
        for index, value in sorted(plan.updates.items())
    ]
    return out


async def apply_plan(
    db: AsyncSession,
    plan: PairPlan,
    *,
    mark_stale: bool = True,
    actor_user_id: Optional[int] = None,
) -> bool:
    """Zapis planu (wiersze już zablokowane w ``plan_pair(lock=True)``).

    ``actor_user_id`` — administrator uzupełniający historię; trafia do
    szczegółów wpisu, nie do ``user_id`` (to nie jego rozmowa).
    """
    from app.models.activity import Activity  # noqa: PLC0415

    if not plan.changes:
        return False
    for row, _, value in plan.changes:
        # ``null()`` = SQL NULL; samo ``None`` zapisałoby JSON-owe ``null``.
        row.screening_answers = value if value is not None else null()
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=plan.stage_id,
            action=ACTIVITY_ACTION,
            user_id=None,
            details={
                "candidate_id": plan.candidate_id,
                "job_id": plan.job_id,
                "note_id": plan.note_id,
                "action": plan.action,
                "question_ids": list(plan.question_ids),
                "by_content": plan.by_content,
                "by_number": plan.by_number,
                "stage_ids": [row.id for row, _, _ in plan.changes],
                **({"actor_user_id": actor_user_id} if actor_user_id else {}),
            },
        )
    )
    await db.flush()
    if mark_stale:
        from app.services.match_score_cache import (  # noqa: PLC0415
            mark_stale_for_candidate,
        )

        await mark_stale_for_candidate(db, plan.candidate_id)
    return True


async def sync_pair(db: AsyncSession, *, candidate_id: int, job_id: int) -> PairPlan:
    """Przelicz arkusz automatu pary i zapisz zmianę (bez commita)."""
    plan = await plan_pair(db, candidate_id=candidate_id, job_id=job_id, lock=True)
    await apply_plan(db, plan)
    return plan


async def sync_pair_safely(
    db: AsyncSession, *, candidate_id: Optional[int], job_id: Optional[int]
) -> Optional[PairPlan]:
    """Wywołanie z przeliczenia karty: w savepoincie, nigdy nie rzuca."""
    if candidate_id is None or job_id is None or not enabled():
        return None
    try:
        async with db.begin_nested():
            return await sync_pair(db, candidate_id=candidate_id, job_id=job_id)
    except Exception as exc:  # noqa: BLE001 — arkusz jest dodatkiem do karty
        logger.warning(
            "screening note sync failed candidate=%s job=%s (%s)",
            candidate_id,
            job_id,
            type(exc).__name__,
        )
        return None


__all__ = [
    "ACTIVITY_ACTION",
    "HUMAN_ORIGIN",
    "SYNC_ORIGIN",
    "AnswerMatch",
    "MappingResult",
    "PairPlan",
    "apply_plan",
    "build_sheet",
    "enabled",
    "humanize_origins",
    "is_blank",
    "is_sync_owned",
    "map_note_answers",
    "plan_pair",
    "plan_rows",
    "similarity",
    "sync_pair",
    "sync_pair_safely",
]
