"""Karta rekomendacji z notatki rekrutera i „Ułóż w zdanie” (0421, 06.10.2026).

Propozycja Olafa, decyzje Artura D1–D5 z 06.10.2026:

* rekruter wgrywa albo wkleja notatkę z rozmowy (D5 — bez automatu na każdej
  notatce); NEXUS PROPONUJE pola karty i odpowiedzi na pytania Championa,
  a zapis robi rekruter. Od 0424 notatka wypełnia jeden formularz
  screeningu, a zapis idzie przez ``PUT /api/screening-form``
  (``services/screening_form.py``);
* hasła rekrutera Luna układa w pełne zdania (``phrase``) w języku CV klienta
  (D3), także w polach opisowych karty (D4).

Zasady:

* Najpierw reguła wzoru działu (``parse_card``, bez AI), potem model dla
  tego, czego reguła nie znalazła. Pole z reguły wygrywa z modelem.
* Narodowość czyta WYŁĄCZNIE reguła — przed wysłaniem do modelu tekst
  przechodzi ``redact_card_text`` i ``strip_contacts`` (narodowość, e-mail,
  telefon, LinkedIn).
* Wartość od modelu bez dosłownego cytatu z notatki odpada; liczba, data,
  nazwa własna albo technologia, której nie ma w źródle, odrzuca zdanie
  (``phrase_guard``). Stawka z modelu musi mieć swoją liczbę w cytacie.
* AI to podpowiedź, nigdy bramka: awaria modelu zwraca to, co znalazła
  reguła, z komunikatem — nigdy 5xx. Nic tu nie zapisuje się w bazie poza
  telemetrią AI (``ai_feature``).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Mapping, Optional, Sequence

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services import candidate_claim, screening_sheets
from app.services import recommendation_cards as cards
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import (
    RECOMMENDATION_CARD_NOTE_READ,
    SCREENING_ANSWER_PHRASING,
)
from app.services.prompt_fencing import fence, json_for_prompt
from app.services.recommendation_card_parser import (
    AI_HIDDEN_FIELDS,
    normalize_field,
    parse_card,
    redact_card_text,
    strip_contacts,
    to_text,
)

logger = logging.getLogger(__name__)

READ_FEATURE = AIFeatureKey.recommendation_card_note_read
PHRASE_FEATURE = AIFeatureKey.screening_answer_phrasing

NOTE_MAX_CHARS = 20_000
NOTE_MIN_CHARS = 30
# Cytat musi mieć choć kilka znaków — trzy litery („ing”) stoją w każdej notatce.
QUOTE_MIN_CHARS = 5
PHRASE_MAX_ITEMS = 20
KEYWORDS_MAX_CHARS = 2000
SENTENCE_MAX_CHARS = 1500

# Pola, które proponuje model. Narodowość tylko z reguły (prywatność),
# manager u klienta nie jest częścią rozmowy z kandydatem.
MODEL_FIELDS: tuple[str, ...] = tuple(
    key for key in cards.REQUIRED_FIELDS if key not in AI_HIDDEN_FIELDS
)
_FIELD_HINTS: dict[str, str] = {
    "rate": "oczekiwana stawka kandydata z jednostką, np. 165 zł/h netto B2B",
    "availability": "kiedy może zacząć / okres wypowiedzenia",
    "work_mode": "zdalnie / hybrydowo (ile dni w biurze) / stacjonarnie",
    "location": "miasto zamieszkania albo pracy",
    "worked_at_client": "czy pracował już u klienta tej rekrutacji",
    "english": "poziom angielskiego",
    "red_flags": "ryzyka i zastrzeżenia; „brak”, jeśli notatka tak mówi",
    "recommendation": "dlaczego polecamy kandydata — doświadczenie i mocne strony",
    "motivation": "dlaczego szuka zmiany / czego oczekuje",
}

LANGUAGE_NAMES = {"pl": "polskim", "en": "angielskim"}

MSG_MODEL_FAILED = (
    "Luna nie odpowiedziała — pokazujemy tylko to, co odczytała reguła wzoru. "
    "Uzupełnij resztę ręcznie."
)
MSG_NOTHING_FOUND = (
    "W notatce nie ma nic, co pasowałoby do pól karty ani pytań — uzupełnij "
    "kartę ręcznie."
)
MSG_PHRASE_FAILED = "Luna nie odpowiedziała — zostaw hasła albo spróbuj ponownie."


class NoteTooShort(ValueError):
    """Notatka po odczycie ma za mało tekstu, żeby coś z niej wypełnić."""


# ── Reguły tekstowe (czyste) ───────────────────────────────────────────────


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").lower().replace("ł", "l"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def quote_in_text(quote: str, folded_source: str) -> bool:
    """Cytat (≥3 znaki) występuje w źródle po złożeniu znaków i odstępów."""
    needle = _fold(quote)
    return len(needle) >= QUOTE_MIN_CHARS and needle in folded_source


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_MONTH_STEMS = (
    "stycz",
    "lut",
    "marz",
    "marc",
    "kwie",
    "maj",
    "czerw",
    "lip",
    "sierp",
    "wrze",
    "pazdz",
    "listop",
    "grud",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_WORD_RE = re.compile(r"[^\W\d_][\w+#.\-]*", re.UNICODE)
# Słowa, które bywają pisane wielką literą w środku zdania, a nie są faktem.
_CAPITAL_STOPWORDS = frozenset(
    {
        "kandydat",
        "kandydatka",
        "kandydata",
        "kandydatowi",
        "pan",
        "pani",
        "he",
        "she",
        "they",
        "the",
        "candidate",
        "his",
        "her",
        "b2b",
    }
)


def _numbers(text: str) -> set[str]:
    return {
        match.group(0).replace(",", ".").lstrip("0") or "0"
        for match in _NUMBER_RE.finditer(text or "")
    }


# Słowo krótsze niż tyle znaków porównujemy z hasłami tylko dokładnie —
# inaczej „w”, „a”, „do” z notatki „potwierdzałyby” każdą nazwę zaczynającą
# się od tych liter („Azure”, „Docker”; przegląd bezpieczeństwa 06.10.2026).
_STEM_MIN_CHARS = 4


class _SourceWords:
    """Słowa źródła: zbiór i indeks po trzech pierwszych literach (czas liniowy)."""

    def __init__(self, folded_source: str) -> None:
        self.words: set[str] = set()
        self.by_prefix: dict[str, list[str]] = {}
        for raw in _WORD_RE.findall(folded_source):
            word = raw.strip(".-")
            if not word or word in self.words:
                continue
            self.words.add(word)
            if len(word) >= _STEM_MIN_CHARS:
                self.by_prefix.setdefault(word[:3], []).append(word)


def _has_counterpart(word: str, source: _SourceWords) -> bool:
    """Słowo ma odpowiednik w źródle z dokładnością do odmiany („Javie” ~ „java”)."""
    target = _fold(word).strip(".-")
    if not target or target in source.words:
        return True
    if len(target) < _STEM_MIN_CHARS:
        return False
    for other in source.by_prefix.get(target[:3], ()):
        if target.startswith(other) or other.startswith(target):
            return True
        common = 0
        for a, b in zip(target, other):
            if a != b:
                break
            common += 1
        if common >= max(3, min(len(target), len(other)) - 2):
            return True
    return False


def phrase_guard(sentence: str, *sources: str) -> Optional[str]:
    """Pierwszy fakt zdania, którego nie ma w źródłach — albo ``None``.

    Sprawdzane: liczby (także w datach), nazwy miesięcy, słowa pisane wielką
    literą poza początkiem zdania (nazwy firm, technologii, miast) i słowa
    z cyfrą albo znakiem ``+``/``#`` (C++, C#, Java 17). Odmiana jest
    tolerowana (wspólny rdzeń), więc „Javie” pasuje do „java”.
    """
    source = " ".join(s for s in sources if s)
    folded_source = _fold(source)
    source_numbers = _numbers(source)
    for number in _numbers(sentence):
        if number not in source_numbers:
            return number
    folded_sentence = _fold(sentence)
    for stem in _MONTH_STEMS:
        if re.search(rf"\b{stem}", folded_sentence) and not re.search(
            rf"\b{stem}", folded_source
        ):
            match = re.search(rf"\b{stem}\w*", folded_sentence)
            return match.group(0) if match else stem
    words = _SourceWords(folded_source)
    for match in _WORD_RE.finditer(sentence or ""):
        word = match.group(0).rstrip(".-")
        before = (sentence[: match.start()] or "").rstrip()
        at_start = not before or before[-1] in ".!?:;\n(„\"'"
        special = any(ch in word for ch in "+#") or any(ch.isdigit() for ch in word)
        capital = word[:1].isupper() and len(word) > 1
        if not special and (not capital or at_start):
            continue
        if _fold(word) in _CAPITAL_STOPWORDS:
            continue
        if not _has_counterpart(word, words):
            return word
    return None


def _parse_json(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def model_text(text: str) -> str:
    """Tekst notatki, który może zobaczyć model: bez narodowości i kontaktów."""
    return strip_contacts(redact_card_text(text, AI_HIDDEN_FIELDS))


def note_text(content: str) -> str:
    """Notatka jako zwykły tekst z zachowanymi wierszami (≤ ``NOTE_MAX_CHARS``)."""
    return to_text(content, limit=NOTE_MAX_CHARS)


def _language_name(language: str) -> str:
    return LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["pl"])


# ── Odczyt notatki ─────────────────────────────────────────────────────────


def _call_model(feature: AIFeatureKey, system: str, prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=model_for(feature),
        fallback_models=fallbacks_for(feature),
        max_tokens=3000,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


def validate_model_fields(parsed: Any, *, note: str) -> dict[str, dict[str, str]]:
    """Pola od modelu, którym da się ufać: znany klucz, cytat w notatce, fakty z notatki."""
    items = parsed.get("fields") if isinstance(parsed, dict) else None
    if not isinstance(items, dict):
        return {}
    folded_note = _fold(note)
    out: dict[str, dict[str, str]] = {}
    for key, item in items.items():
        if key not in MODEL_FIELDS or not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()[: cards.max_length(key)]
        quote = str(item.get("quote") or "").strip()
        if not value or not quote_in_text(quote, folded_note):
            continue
        if phrase_guard(value, note) is not None:
            continue
        # Stawka: każda liczba wartości musi stać w cytacie, nie gdzieś
        # w notatce (stawka kandydata obok stawki z poprzedniego projektu).
        if key == "rate" and not _numbers(value) <= _numbers(quote):
            continue
        out[key] = {"value": value, "quote": quote}
    return out


def validate_model_answers(
    parsed: Any, *, note: str, questions: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    """Odpowiedzi od modelu: pytanie z listy, cytat w notatce, zdanie bez nowych faktów."""
    items = parsed.get("answers") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return {}
    folded_note = _fold(note)
    out: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if qid not in questions or qid in out:
            continue
        quote = str(item.get("quote") or "").strip()
        if not quote_in_text(quote, folded_note):
            continue
        sentence = str(item.get("sentence") or "").strip()[:SENTENCE_MAX_CHARS]
        problem = phrase_guard(sentence, note, questions[qid]) if sentence else None
        out[qid] = {
            "quote": quote,
            "sentence": "" if problem else sentence,
            "problem": problem or "",
        }
    return out


def _current_answers(conversations: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    answers = conversations[0]["answers"] if conversations else []
    return {
        str(item.get("question_id") or ""): str(item.get("response") or "").strip()
        for item in answers
        if isinstance(item, Mapping) and not item.get("skipped")
    }


def structured_rate(text: str) -> Optional[dict[str, Any]]:
    """Stawka z tekstu jako PLN/h (``{amount, unit, currency}``) albo ``None``.

    Ta sama reguła co karta (``recommendation_card_parser.parse_rate``): kwota
    miesięczna, dzienna, w innej walucie albo widełki zostają tekstem.
    """
    hourly = cards.card_rate_hourly(normalize_field("rate", text))
    if hourly is None:
        return None
    return {"amount": hourly, "unit": "hourly", "currency": "PLN"}


def build_proposal(
    *,
    note: str,
    rule_fields: Mapping[str, Mapping[str, Any]],
    rule_answers: Sequence[Mapping[str, Any]],
    model_fields: Mapping[str, Mapping[str, str]],
    model_answers: Mapping[str, Mapping[str, str]],
    current_fields: Mapping[str, Mapping[str, Any]],
    questions: Mapping[str, str],
    current_answers: Mapping[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Lista „obecnie → propozycja” dla pól i pytań (czysta)."""
    fields: list[dict[str, Any]] = []
    for key in cards.EDITABLE_FIELDS:
        rule = rule_fields.get(key)
        model = model_fields.get(key)
        if rule and str(rule.get("raw") or "").strip():
            proposed = str(rule["raw"]).strip()[: cards.max_length(key)]
            origin, quote = "note_rule", None
        elif model:
            proposed, origin, quote = model["value"], "note_ai", model["quote"]
        else:
            continue
        current = current_fields.get(key) or {}
        current_raw = str(current.get("raw") or "").strip()
        entry: dict[str, Any] = {
            "key": key,
            "label": cards.DISPLAY_LABELS[key],
            "current": current_raw or None,
            "current_source": current.get("source") if current_raw else None,
            "proposed": proposed,
            "quote": quote,
            "origin": origin,
            "changed": proposed != current_raw,
        }
        if key == "rate":
            # Formularz screeningu (0424) ma pole stawki z kwotą i jednostką —
            # propozycja wypełnia je, gdy tekst da się odczytać bez zgadywania.
            entry["rate"] = structured_rate(proposed)
        fields.append(entry)
    by_number = {
        (item.get("number") if isinstance(item.get("number"), int) else index): item
        for index, item in enumerate(rule_answers, start=1)
        if isinstance(item, Mapping)
    }
    answers: list[dict[str, Any]] = []
    for number, (qid, text) in enumerate(questions.items(), start=1):
        rule = by_number.get(number)
        model = model_answers.get(qid)
        rule_text = str((rule or {}).get("answer") or "").strip()
        if rule_text:
            keywords = rule_text
        elif model:
            keywords = model["quote"]
        else:
            continue
        sentence = (model or {}).get("sentence") or ""
        problem = (model or {}).get("problem") or ""
        if sentence and rule_text and phrase_guard(sentence, rule_text, text):
            # Zdanie modelu nie zgadza się z odpowiedzią odczytaną regułą.
            problem, sentence = phrase_guard(sentence, rule_text, text) or "", ""
        answers.append(
            {
                "question_id": qid,
                "number": number,
                "question": text,
                "current": current_answers.get(qid) or None,
                "keywords": keywords[:KEYWORDS_MAX_CHARS],
                "sentence": sentence or None,
                "problem": problem or None,
            }
        )
    return {"fields": fields, "answers": answers}


async def model_reading(
    db: AsyncSession,
    *,
    user_id: int,
    note: str,
    questions: Mapping[str, str],
    language: str,
    stats: Optional[dict[str, int]] = None,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Pola i odpowiedzi od modelu po ugruntowaniu. Rzuca przy awarii modelu.

    Wspólne dla trasy i pomiaru (``scripts/eval_recommendation_card_note.py``).
    Zwalnia połączenie z puli (commit) na czas wywołania modelu. ``stats``
    (pomiar) dostaje liczby pozycji od modelu przed i po ugruntowaniu.
    """
    prompt = RECOMMENDATION_CARD_NOTE_READ.render(
        card_fields=fence(
            "card_fields",
            json_for_prompt(
                [
                    {
                        "key": key,
                        "name": cards.DISPLAY_LABELS[key],
                        "hint": _FIELD_HINTS.get(key, ""),
                    }
                    for key in MODEL_FIELDS
                ]
            ),
        ),
        screening_questions=fence(
            "screening_questions",
            json_for_prompt(
                [{"id": qid, "question": text} for qid, text in questions.items()]
            ),
        ),
        interview_note=fence("interview_note", model_text(note)),
    )
    system = (RECOMMENDATION_CARD_NOTE_READ.system_prompt or "").replace(
        "{language_name}", _language_name(language)
    )
    async with ai_feature(db, READ_FEATURE, user_id=user_id):
        await db.commit()
        raw = await run_in_threadpool(_call_model, READ_FEATURE, system, prompt)
    parsed = _parse_json(raw)
    # Walidacja przechodzi po słowach całej notatki — poza pętlą zdarzeń
    # (jeden proces uvicorna).
    fields = await run_in_threadpool(validate_model_fields, parsed, note=note)
    answers = await run_in_threadpool(
        validate_model_answers, parsed, note=note, questions=questions
    )
    if stats is not None and isinstance(parsed, dict):
        raw_fields = parsed.get("fields")
        raw_answers = parsed.get("answers")
        stats["fields_raw"] = len(raw_fields) if isinstance(raw_fields, dict) else 0
        stats["fields_kept"] = len(fields)
        stats["answers_raw"] = len(raw_answers) if isinstance(raw_answers, list) else 0
        stats["answers_kept"] = len(answers)
        stats["sentences_kept"] = sum(1 for a in answers.values() if a["sentence"])
        stats["sentences_rejected"] = sum(1 for a in answers.values() if a["problem"])
    return fields, answers


async def read_note(
    db: AsyncSession,
    *,
    user_id: int,
    candidate: Candidate,
    job: Job,
    content: str,
) -> dict[str, Any]:
    """Propozycja karty i odpowiedzi z notatki — bez zapisu.

    ``NoteTooShort`` przy notatce krótszej niż ``NOTE_MIN_CHARS`` po odczycie.
    """
    note = note_text(content)
    if len(note) < NOTE_MIN_CHARS:
        raise NoteTooShort("Notatka ma za mało tekstu, żeby wypełnić z niej kartę.")

    process = await candidate_claim.load_process(
        db, candidate_id=candidate.id, job_id=job.id
    )
    started = cards.attempt_started(process)
    card = await cards.load_card(db, candidate_id=candidate.id, job_id=job.id)
    current_fields, _ = cards.split_fields(
        card.fields_notes if card else {},
        card.fields_manual if card else {},
        attempt_started=started,
    )
    questions = screening_sheets.question_texts(job.champion_profile)
    conversations = await screening_sheets.candidate_conversations(
        db, candidate_id=candidate.id, job_scope=CandidateStage.job_id == job.id
    )
    language = await phrase_language(db, job)
    rate_notifies = await _rate_change_notifies(db, candidate.id, job.id)

    parsed_rule = parse_card(note)
    rule_fields = {
        key: value
        for key, value in parsed_rule.fields.items()
        if key in cards.EDITABLE_FIELDS
    }
    missing_fields = [key for key in MODEL_FIELDS if key not in rule_fields]

    model_fields: dict[str, dict[str, str]] = {}
    model_answers: dict[str, dict[str, str]] = {}
    available, message = True, None
    # Pytania idą do modelu zawsze, gdy są — także te z odpowiedzią odczytaną
    # regułą: model układa z niej zdanie.
    if missing_fields or questions:
        try:
            model_fields, model_answers = await model_reading(
                db, user_id=user_id, note=note, questions=questions, language=language
            )
        except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
            logger.warning(
                "recommendation_card_assist: note read failed job=%s (%s)",
                job.id,
                type(exc).__name__,
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                logger.warning("recommendation_card_assist: rollback failed")
            available, message = False, MSG_MODEL_FAILED

    proposal = build_proposal(
        note=note,
        rule_fields=rule_fields,
        rule_answers=parsed_rule.answers,
        model_fields=model_fields,
        model_answers=model_answers,
        current_fields=current_fields,
        questions=questions,
        current_answers=_current_answers(conversations),
    )
    if available and not proposal["fields"] and not proposal["answers"]:
        message = MSG_NOTHING_FOUND
    return {
        **proposal,
        "available": available,
        "message": message,
        "language": language,
        "rate_change_notifies": rate_notifies,
        "text": note,
    }


async def _rate_change_notifies(
    db: AsyncSession, candidate_id: int, job_id: int
) -> bool:
    from app.services import candidate_rate_change as rate_change  # noqa: PLC0415

    column = await rate_change.pair_column(db, candidate_id=candidate_id, job_id=job_id)
    return column in rate_change.NOTIFY_COLUMNS


async def phrase_language(db: AsyncSession, job: Job) -> str:
    """Język zdań = język CV klienta (D3); bez reguły albo przy awarii — polski."""
    if not job.client_id:
        return "pl"
    try:
        from app.services.cv_generator_b2b.client_rules import (  # noqa: PLC0415
            resolve_client_rule,
        )

        async with db.begin_nested():
            rule = await resolve_client_rule(db, job.client_id)
    except Exception:  # noqa: BLE001 — język to podpowiedź; reguła bywa 503
        return "pl"
    language = getattr(rule, "cv_language", None) if rule is not None else None
    return language if language in LANGUAGE_NAMES else "pl"


# ── „Ułóż w zdanie” ────────────────────────────────────────────────────────


async def phrase(
    db: AsyncSession,
    *,
    user_id: int,
    items: Sequence[Mapping[str, str]],
    language: str,
) -> dict[str, Any]:
    """Zdania z haseł. Pozycja: ``key``, ``keywords``, opcjonalnie ``question``.

    Zwraca ``{"available", "message", "language", "items": [{key, sentence,
    problem}]}``; zdanie z faktem spoza haseł ma ``sentence = None``
    i ``problem`` = ten fakt.
    """
    language = language if language in LANGUAGE_NAMES else "pl"
    clean: list[dict[str, str]] = []
    for item in items[:PHRASE_MAX_ITEMS]:
        key = str(item.get("key") or "").strip()[:100]
        keywords = str(item.get("keywords") or "").strip()[:KEYWORDS_MAX_CHARS]
        if key and keywords:
            clean.append(
                {
                    "key": key,
                    "question": str(item.get("question") or "").strip()[:500],
                    "keywords": strip_contacts(keywords),
                }
            )
    if not clean:
        return {"available": True, "message": None, "language": language, "items": []}
    prompt = SCREENING_ANSWER_PHRASING.render(
        keywords=fence("keywords", json_for_prompt(clean))
    )
    system = (SCREENING_ANSWER_PHRASING.system_prompt or "").replace(
        "{language_name}", _language_name(language)
    )
    try:
        async with ai_feature(db, PHRASE_FEATURE, user_id=user_id):
            await db.commit()
            raw = await run_in_threadpool(_call_model, PHRASE_FEATURE, system, prompt)
        parsed = _parse_json(raw)
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning(
            "recommendation_card_assist: phrasing failed (%s)", type(exc).__name__
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("recommendation_card_assist: rollback failed")
        return {
            "available": False,
            "message": MSG_PHRASE_FAILED,
            "language": language,
            "items": [],
        }
    return {
        "available": True,
        "message": None,
        "language": language,
        "items": await run_in_threadpool(validate_phrases, parsed, clean),
    }


def validate_phrases(
    parsed: Any, items: Sequence[Mapping[str, str]]
) -> list[dict[str, Optional[str]]]:
    """Zdania od modelu po ``phrase_guard`` — w kolejności zapytania."""
    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    by_key: dict[str, str] = {}
    if isinstance(raw_items, list):
        for entry in raw_items:
            if isinstance(entry, dict):
                key = str(entry.get("key") or "").strip()
                sentence = str(entry.get("sentence") or "").strip()
                if key and sentence and key not in by_key:
                    by_key[key] = sentence[:SENTENCE_MAX_CHARS]
    out: list[dict[str, Optional[str]]] = []
    for item in items:
        sentence = by_key.get(item["key"])
        if not sentence:
            out.append({"key": item["key"], "sentence": None, "problem": None})
            continue
        problem = phrase_guard(sentence, item["keywords"], item.get("question") or "")
        out.append(
            {
                "key": item["key"],
                "sentence": None if problem else sentence,
                "problem": problem,
            }
        )
    return out
