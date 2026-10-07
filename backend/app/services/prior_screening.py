"""Odpowiedzi z wcześniejszych rozmów kandydata w ocenie AI (``prior_screening``).

Kandydat odpowiadał już na pytania screeningowe w innych rekrutacjach. Gdy
pytanie TEJ rekrutacji jest tym samym pytaniem (bez AI: słowa treści + te same
technologie), wcześniejsza odpowiedź mówi coś o kandydacie, zanim ktokolwiek
do niego zadzwoni. Warstwa jest DODATKIEM do kanonicznego fitu:

* materiał — najnowszy wypełniony arkusz kandydata w każdej INNEJ rekrutacji
  (reguła ``screening_sheets.candidate_conversations``: najnowszy arkusz pary,
  który daje odpowiedzi — sam z pominięciami nie zasłania starszego), bez
  odpowiedzi pominiętych
  (``skipped``) i przyjętych z podpowiedzi przepięcia (``reassign_suggested`` —
  to echo wcześniejszej rozmowy, nie nowa wiedza);
* pytania tej rekrutacji o stawkę, dostępność, lokalizację i tryb pracy są
  pomijane — mają własne warstwy oceny;
* wydźwięk odpowiedzi (``polarity``): −1 przy przeczeniu (słownik negacji
  z ``must_text_evidence``), +1 przy jawnym potwierdzeniu, ``None`` gdy nie da
  się powiedzieć;
* punkty ``MAX_POINTS × pos / (pos + neg)``; brak dopasowań albo same ``None``
  = warstwa bez oceny (wynik bez zmian);
* deal-breaker = pytanie TEJ rekrutacji ma warunek (``deal_breaker``),
  a dopasowana wcześniejsza odpowiedź była oceniona jako trafienie
  (``deal_breaker_hit``) — 0 pkt i plakietka. Samo „nie” nim nie jest (pytania
  odwrotne: „Czy potrzebujesz wizy?”), cudzy warunek bez naszego też nie.
  Nigdy nie ukrywa kandydata.

Wyłącznik ``PRIOR_SCREENING_LAYER_ENABLED`` (domyślnie OFF): przy OFF odcisk
żądania, ``scoring_algorithm_version`` i ``ScoreBreakdown.as_dict`` są bajt
w bajt jak przed tą warstwą. Zmiana progu, budżetu albo reguły dopasowania =
podbicie ``VERSION`` (wchodzi do odcisku żądania).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

VERSION = "prior-screening-v1"
# Budżet warstwy w punktach (pomiar 3/5/8 rozstrzyga przed włączeniem).
MAX_POINTS = 5.0
# Jaccard słów treści pytań (kalibracja w pomiarze).
MATCH_THRESHOLD = 0.6
# Długość „rdzenia” słowa: polska odmiana („doświadczenie/-a/-em”) daje ten sam.
_STEM_CHARS = 6
_QUESTION_MAX_CHARS = 2000

STATUS_DEAL_BREAKER = "deal_breaker"
STATUS_ANSWERED = "answered"

# Origins odpowiedzi, które nie są nową wiedzą o kandydacie.
_IGNORED_ORIGINS = frozenset({"reassign_suggested"})

_STOPWORD_LIST = {
    # PL
    "czy",
    "jak",
    "jaki",
    "jaka",
    "jakie",
    "jakich",
    "jakim",
    "jakiej",
    "ile",
    "kiedy",
    "gdzie",
    "dlaczego",
    "oraz",
    "albo",
    "lub",
    "się",
    "jest",
    "był",
    "była",
    "było",
    "być",
    "ma",
    "mial",
    "miał",
    "masz",
    "posiada",
    "posiadasz",
    "kandydat",
    "kandydata",
    "kandydatka",
    "pan",
    "pani",
    "tego",
    "tej",
    "ten",
    "ta",
    "to",
    "te",
    "tym",
    "który",
    "która",
    "które",
    "którym",
    "proszę",
    "prosze",
    "opisz",
    "opisać",
    "powiedz",
    "jego",
    "jej",
    "ich",
    "swoje",
    "swoim",
    "swój",
    "przy",
    "dla",
    "nad",
    "pod",
    "przez",
    "bez",
    "też",
    "także",
    "lat",
    "roku",
    "rok",
    "lata",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "do",
    "does",
    "did",
    "you",
    "your",
    "have",
    "has",
    "had",
    "what",
    "how",
    "which",
    "when",
    "where",
    "why",
    "is",
    "are",
    "was",
    "were",
    "be",
    "any",
    "candidate",
    "please",
    "describe",
    "about",
}

# Pytania o rzeczy, które mają własną warstwę (stawka, dostępność,
# lokalizacja, tryb pracy). Dopasowanie po tekście bez polskich znaków.
_OWN_LAYER_QUESTION_RE = re.compile(
    r"\b(?:stawk\w*|wynagrodz\w*|zarob\w*|oczekiwan\w*\s+finans\w*|rate|salary"
    r"|b2b\s+netto|pln|zl\b|dostepn\w*|availab\w*|wypowiedzen\w*|notice"
    r"|od\s+kiedy|rozpocz\w*|start\s+date|lokaliz\w*|miast\w*|biur\w*"
    r"|zdaln\w*|hybryd\w*|stacjonar\w*|remote|office|onsite|on-site"
    r"|relokac\w*|relocat\w*|dojazd\w*|dojezd\w*|tryb\w*\s+pracy)\b"
)

# Jawne potwierdzenie w odpowiedzi (po złożeniu bez polskich znaków).
_POSITIVE_ANSWER_RE = re.compile(
    r"^\W*(?:tak|yes|owszem|oczywiscie|jasne|zgadza|potwierdz\w*)\b"
    r"|\b\d+(?:[.,]\d+)?\s*\+?\s*(?:lat\w*|rok\w*|years?|yrs?|miesi\w*|months?)\b"
    r"|\b(?:zna|pracowal\w*|pracuje|uzywal\w*|uzywa|korzysta\w*|posiada"
    r"|ma\s+doswiadcz\w*|komercyjn\w*|wdrazal\w*|projektowal\w*|prowadzil\w*)\b"
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def enabled() -> bool:
    return bool(getattr(settings, "PRIOR_SCREENING_LAYER_ENABLED", False))


def _fold(text: str) -> str:
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


_STOPWORDS = frozenset(_fold(word) for word in _STOPWORD_LIST)


def content_words(text: str) -> frozenset[str]:
    """Słowa treści pytania: bez polskich znaków, bez słów pomocniczych, rdzenie."""
    out = set()
    for word in _WORD_RE.findall(_fold(text)):
        if len(word) < 3 or word in _STOPWORDS or word.isdigit():
            continue
        out.add(word[:_STEM_CHARS])
    return frozenset(out)


def technologies(text: str) -> frozenset[str]:
    """Technologie ze słownika (kanoniczne nazwy) wymienione w tekście."""
    from app.services import scoring_service

    pattern = scoring_service._alias_pattern()
    if pattern is None or not text:
        return frozenset()
    found = set()
    for match in pattern.finditer(text):
        alias = match.group(1).lower()
        if alias in scoring_service._ROLE_WORDS:
            continue
        canonical = scoring_service.ALIAS_MAP.get(alias)
        if canonical:
            found.add(canonical)
    return frozenset(found)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def has_own_layer(question: str) -> bool:
    """Pytanie o stawkę, dostępność, lokalizację albo tryb pracy."""
    return bool(_OWN_LAYER_QUESTION_RE.search(_fold(question)))


def questions_match(current: str, prior: str) -> Optional[float]:
    """Podobieństwo pytań albo ``None``, gdy to nie to samo pytanie.

    Warunek technologii: każda technologia ze słownika w pytaniu tej
    rekrutacji musi stać też w pytaniu wcześniejszym — „Ile lat z Javą?”
    i „Ile lat z Pythonem?” mają te same słowa treści, ale inną odpowiedź.
    """
    score = jaccard(content_words(current), content_words(prior))
    if score < MATCH_THRESHOLD:
        return None
    if not technologies(current) <= technologies(prior):
        return None
    return score


def polarity(response: Optional[str]) -> Optional[int]:
    """+1 jawne potwierdzenie, −1 przeczenie, ``None`` gdy nie wiadomo."""
    from app.services.must_text_evidence import is_negative_answer

    text = (response or "").strip()
    if not text:
        return None
    if is_negative_answer(text):
        return -1
    if _POSITIVE_ANSWER_RE.search(_fold(text)):
        return 1
    return None


@dataclass(frozen=True)
class PriorAnswer:
    """Jedna odpowiedź z arkusza innej rekrutacji."""

    job_id: int
    question: str
    response: str
    deal_breaker_hit: bool
    answered_at: Optional[datetime]


@dataclass(frozen=True)
class PriorScreeningMaterial:
    """Materiał dołączony do kandydata przez ``attach_prior_screening``."""

    target_job_id: Optional[int]
    answers: tuple[PriorAnswer, ...]


@dataclass(frozen=True)
class PriorMatch:
    """Pytanie TEJ rekrutacji z dopasowaną wcześniejszą odpowiedzią."""

    question_id: str
    question: str
    polarity: Optional[int]
    deal_breaker: bool
    similarity: float
    answered_at: Optional[datetime]

    def as_evidence(self) -> dict:
        # Bez tytułu, klienta i treści odpowiedzi z innej rekrutacji —
        # ta ostatnia bywa pełna nazw innego klienta.
        return {
            "question_id": self.question_id,
            "question": self.question[:300],
            "polarity": self.polarity,
            "deal_breaker": self.deal_breaker,
            "similarity": round(self.similarity, 2),
            "answered_at": (self.answered_at.isoformat() if self.answered_at else None),
        }


@dataclass(frozen=True)
class PriorScreeningResult:
    matches: tuple[PriorMatch, ...]
    positive: int
    negative: int
    deal_breaker: bool

    @property
    def scored(self) -> bool:
        return self.deal_breaker or (self.positive + self.negative) > 0

    @property
    def points(self) -> float:
        if not self.scored or self.deal_breaker:
            return 0.0
        return MAX_POINTS * self.positive / (self.positive + self.negative)

    @property
    def status(self) -> Optional[str]:
        if self.deal_breaker:
            return STATUS_DEAL_BREAKER
        if self.scored:
            return STATUS_ANSWERED
        return None

    def reason(self) -> str:
        if self.deal_breaker:
            return "wcześniej: deal-breaker / odpowiedział „nie”"
        if not self.scored:
            if self.matches:
                return "wcześniejsze odpowiedzi bez jednoznacznego wydźwięku"
            return "brak wcześniejszych odpowiedzi na podobne pytania"
        return f"wcześniejsze rozmowy: {self.positive} × tak, {self.negative} × nie"

    def evidence(self) -> list[dict]:
        return [match.as_evidence() for match in self.matches]


def current_questions(job) -> list[dict]:
    from app.services import champion_view

    out = []
    for question in champion_view.screening_questions(
        getattr(job, "champion_profile", None)
    ):
        if not isinstance(question, Mapping):
            continue
        text = str(question.get("question") or "").strip()
        if not text or has_own_layer(text):
            continue
        out.append(
            {
                "id": str(question.get("id") or "").strip(),
                "question": text[:_QUESTION_MAX_CHARS],
                "deal_breaker": bool(str(question.get("deal_breaker") or "").strip()),
            }
        )
    return out


def material_for(candidate, job) -> Optional[PriorScreeningMaterial]:
    """Materiał dołączony dla TEJ rekrutacji (inna rekrutacja = brak)."""
    material = getattr(candidate, "_prior_screening", None)
    if not isinstance(material, PriorScreeningMaterial):
        return None
    if material.target_job_id != getattr(job, "id", None):
        return None
    return material


def evaluate(candidate, job) -> Optional[PriorScreeningResult]:
    """Wynik warstwy albo ``None``, gdy materiału nie dołączono (awaria, OFF)."""
    material = material_for(candidate, job)
    if material is None:
        return None
    matches: list[PriorMatch] = []
    for question in current_questions(job):
        best: Optional[tuple[float, datetime, PriorAnswer]] = None
        for answer in material.answers:
            score = questions_match(question["question"], answer.question)
            if score is None:
                continue
            when = answer.answered_at or datetime.min.replace(tzinfo=timezone.utc)
            if best is None or (score, when) > (best[0], best[1]):
                best = (score, when, answer)
        if best is None:
            continue
        score, _, answer = best
        sign = polarity(answer.response)
        matches.append(
            PriorMatch(
                question_id=question["id"],
                question=question["question"],
                polarity=sign,
                # Deal-breaker tylko wtedy, gdy TA rekrutacja ma warunek przy
                # pytaniu, a wcześniejsza odpowiedź była oceniona jako trafienie.
                # Samo „nie” nim nie jest („Czy potrzebujesz wizy?” — „nie” to
                # dobra odpowiedź), a cudzy próg (5 lat) nie jest naszym (2 lata).
                deal_breaker=question["deal_breaker"] and answer.deal_breaker_hit,
                similarity=score,
                answered_at=answer.answered_at,
            )
        )
    return PriorScreeningResult(
        matches=tuple(matches),
        positive=sum(1 for m in matches if m.polarity == 1),
        negative=sum(1 for m in matches if m.polarity == -1),
        deal_breaker=any(m.deal_breaker for m in matches),
    )


def layer_for(candidate, job):
    """``LayerResult`` warstwy albo ``None`` (bez materiału)."""
    from app.services.scoring_service import LayerResult

    result = evaluate(candidate, job)
    if result is None:
        return None
    if not result.scored:
        # Bez oceny: ani licznik, ani mianownik — wynik jak bez warstwy.
        return LayerResult(
            points=0.0,
            max_points=0.0,
            reason=result.reason(),
            status="unknown",
            scored=False,
        )
    return LayerResult(
        points=result.points,
        max_points=MAX_POINTS,
        reason=result.reason(),
        status=result.status,
    )


def _moment(value: Any) -> Optional[datetime]:
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def answers_from_sheet(
    job_id: int,
    sheet: Any,
    texts: Mapping[str, str],
    *,
    moved_at: Optional[datetime] = None,
    before: Optional[datetime] = None,
) -> list[PriorAnswer]:
    """Odpowiedzi jednego arkusza, które są materiałem (czysta funkcja)."""
    if not isinstance(sheet, Mapping):
        return []
    answered_at = _moment(sheet.get("answered_at")) or _moment(moved_at)
    if before is not None:
        cutoff = _moment(before)
        if answered_at is None or cutoff is None or answered_at >= cutoff:
            return []
    out = []
    for answer in sheet.get("answers") or []:
        if not isinstance(answer, Mapping):
            continue
        if answer.get("skipped") or answer.get("origin") in _IGNORED_ORIGINS:
            continue
        response = str(answer.get("response") or "").strip()
        if not response:
            continue
        question = str(
            answer.get("question_text")
            or texts.get(str(answer.get("question_id") or "").strip())
            or ""
        ).strip()
        if not question:
            continue
        out.append(
            PriorAnswer(
                job_id=job_id,
                question=question[:_QUESTION_MAX_CHARS],
                response=response[:2000],
                deal_breaker_hit=bool(answer.get("deal_breaker_hit")),
                answered_at=answered_at,
            )
        )
    return out


def _needs_profile(sheet: Any) -> bool:
    answers = sheet.get("answers") if isinstance(sheet, Mapping) else None
    return any(
        isinstance(a, Mapping) and not a.get("question_text") for a in answers or []
    )


async def _load_material(
    db, ids: Sequence[int], target_job_id: Optional[int], before
) -> dict[int, list[PriorAnswer]]:
    from sqlalchemy import case, func, select

    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from app.services.screening_sheets import question_texts

    answers_col = CandidateStage.screening_answers["answers"]
    query = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.screening_answers,
            CandidateStage.moved_at,
        )
        .where(
            CandidateStage.candidate_id.in_(list(ids)),
            CandidateStage.job_id.isnot(None),
            CandidateStage.screening_answers.isnot(None),
            # CASE: Postgres nie gwarantuje kolejności warunków w AND, więc
            # `jsonb_array_length` na obiekcie wywracałby całe zapytanie.
            case(
                (
                    func.jsonb_typeof(answers_col) == "array",
                    func.jsonb_array_length(answers_col),
                ),
                else_=0,
            )
            > 0,
        )
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    if target_job_id is not None:
        query = query.where(CandidateStage.job_id != target_job_id)
    if before is not None:
        query = query.where(CandidateStage.moved_at < before)
    rows = (await db.execute(query)).all()
    profile_job_ids = sorted(
        {job_id for _, job_id, raw, _ in rows if _needs_profile(raw)}
    )
    texts: dict[int, dict[str, str]] = {}
    if profile_job_ids:
        for job_id, profile in (
            await db.execute(
                select(Job.id, Job.champion_profile).where(Job.id.in_(profile_job_ids))
            )
        ).all():
            texts[job_id] = question_texts(profile)
    # Najnowszy arkusz pary, który daje odpowiedzi — arkusz z samymi
    # pominięciami nie zasłania starszego z prawdziwymi odpowiedziami.
    out: dict[int, list[PriorAnswer]] = {}
    taken: set[tuple[int, int]] = set()
    for candidate_id, job_id, raw, moved_at in rows:
        if (candidate_id, job_id) in taken:
            continue
        found = answers_from_sheet(
            job_id, raw, texts.get(job_id, {}), moved_at=moved_at, before=before
        )
        if found:
            taken.add((candidate_id, job_id))
            out.setdefault(candidate_id, []).extend(found)
    return out


async def attach_prior_screening(
    db, job, candidates: Iterable, before: Optional[datetime] = None
) -> None:
    """Dołącz ``_prior_screening`` do kandydatów przed oceną.

    ``before`` ogranicza materiał do arkuszy sprzed tej chwili (pomiar bez
    przecieku). Nigdy nie rzuca: błąd zapytania zostawia kandydatów bez
    materiału, a ocena idzie wtedy bez tej warstwy.
    """
    candidates = [c for c in candidates if getattr(c, "id", None) is not None]
    if db is None or not candidates:
        return
    target_job_id = getattr(job, "id", None)
    if not current_questions(job):
        # Rekrutacja bez pytań do porównania (Radar, brak pytań screeningu):
        # warstwa i tak byłaby bez oceny — pusty materiał bez zapytania.
        for candidate in candidates:
            candidate._prior_screening = PriorScreeningMaterial(
                target_job_id=target_job_id, answers=()
            )
        return
    try:
        async with db.begin_nested():
            material = await _load_material(
                db, [c.id for c in candidates], target_job_id, before
            )
    except Exception:  # noqa: BLE001 — warstwa jest dodatkiem do oceny
        logger.warning("prior screening: lookup failed", exc_info=True)
        return
    for candidate in candidates:
        candidate._prior_screening = PriorScreeningMaterial(
            target_job_id=target_job_id,
            answers=tuple(material.get(candidate.id, ())),
        )
