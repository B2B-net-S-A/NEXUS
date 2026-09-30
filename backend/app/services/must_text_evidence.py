"""Must-have spełniony, gdy technologia jest GDZIEKOLWIEK: profil, CV, notatki.

Decyzja Artura (27.09.2026): bramka must zostaje twarda, ale kandydat ją
przechodzi, jeśli technologia stoi w jego profilu (lista umiejętności, historia
stanowisk, pola z Traffita), w tekście CV albo w notatkach rekruterów. Do tego
dnia bramka czytała wyłącznie listę umiejętności, a ta bywa krótka (lista
z Traffita) — w badaniu z 26.09 28,5% „braków” u osób wysłanych do klienta
było w CV.

Jedna reguła słowa dla wszystkich ekranów: ``keyword_terms.py_regex`` (całe
słowo, jak wyszukiwanie ręczne), aliasy ze słownika umiejętności. CV i profil
sprawdzamy w Pythonie na już załadowanych kandydatach; notatki dociąga
``attach_gate_evidence`` jednym zapytaniem na paczkę — wyłącznie notatki,
w których któreś ze słów w ogóle występuje.

Maile (``NoteType.email``) NIE są dowodem: maile z Traffita niosą treść
ogłoszenia wysłanego kandydatowi, więc „Java” w mailu nie mówi nic o nim.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional, Sequence

from app.services.keyword_terms import parse_keyword, py_regex
from app.services.must_gate_terms import GateRequirement, gate_requirement

# Notatki, które są dowodem: rozmowy, spotkania, notatki ogólne, rozmowy
# rekrutacyjne. Bez maili (patrz docstring modułu).
EVIDENCE_NOTE_TYPES = ("call", "meeting", "general", "interview")
YIELD_EVERY = 32

# Kluczy `cv_extracted_data`, które są treścią profilu (nie metadanymi).
_PROFILE_DATA_KEYS = (
    "traffit_technologie",
    "traffit_Position",
    "traffit_certificates",
    "traffit_previous_employers",
    "skills",
    "certifications",
    "projects",
    "profile_about",
    "_notes_insights",
)


@dataclass(frozen=True)
class MustTextEvidence:
    """Wynik dla jednego kandydata i jednej listy must (``key``)."""

    key: tuple[str, ...]
    met: frozenset[str]
    has_notes: bool


# Najdłuższe słowo nazwy jako tani filtr: regex idzie wyłącznie po tekstach,
# w których to słowo w ogóle występuje. Wzorce dopasowują słowa dosłownie
# (bez wielkości liter), więc filtr niczego nie gubi. Zmierzone 27.09.2026:
# bez filtra 2000 kandydatów × 10 wymagań = 5 s czystego CPU na paczkę.
_TOKEN = re.compile(r"[0-9a-ząćęłńóśźż]+")


def _prefilter_token(form: str) -> str:
    tokens = _TOKEN.findall(form.lower())
    best = max(tokens, key=len) if tokens else ""
    return best if len(best) >= 3 else ""


@lru_cache(maxsize=4096)
def _patterns(
    requirement: GateRequirement,
) -> tuple[tuple[re.Pattern[str], str, bool], ...]:
    """Wzorce całego słowa dla opcji wymagania i ich aliasów (+ słowo filtra).

    Aliasy 1–2-znakowe i zwykłe polskie słowa („go”, „jest”) szukamy tylko
    w pisowni z wymagania, z wielkością liter („Go”, „Jest”); jednoliterowych
    („R”, „C”) w tekście nie szukamy wcale — tylko w profilu.
    """
    from app.services.scoring_service import POLISH_WORD_ALIASES, skill_name_variants

    # (wzorzec, słowo filtra, z wielkością liter)
    out: list[tuple[re.Pattern[str], str, bool]] = []
    seen: set[str] = set()
    for option in requirement.options:
        forms = [option.lower(), *skill_name_variants([option])]
        for form in forms:
            form = form.strip()
            if not form or form in seen:
                continue
            seen.add(form)
            short = len(form) <= 2 or form in POLISH_WORD_ALIASES
            if short:
                if form != option.lower() or len(option.strip()) < 2:
                    continue
                cased = re.compile(
                    r"(?<![0-9A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ])"
                    + re.escape(option.strip())
                    + r"(?![0-9A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ])"
                )
                out.append((cased, _prefilter_token(form), True))
                continue
            term = parse_keyword(form.lower())
            if term is not None:
                # Bez IGNORECASE, na tekście już zamienionym na małe litery —
                # regex Pythona z IGNORECASE był tu ~3× wolniejszy.
                out.append(
                    (re.compile(py_regex(term).pattern), _prefilter_token(form), False)
                )
    return tuple(out)


def _mentions_lowered(requirement: GateRequirement, text: str, lowered: str) -> bool:
    for pattern, token, cased in _patterns(requirement):
        # Wzorce z wielkością liter (krótkie aliasy) idą po oryginale.
        haystack = text if cased else lowered
        start = 0
        if token:
            at = lowered.find(token)
            if at < 0:
                continue
            # Dopasowanie zawiera słowo filtra, więc nie zaczyna się wcześniej
            # niż długość wzorca przed nim (lookbehind widzi tekst przed `pos`).
            start = max(0, at - len(pattern.pattern))
        if pattern.search(haystack, start):
            return True
    return False


def mentions(requirement: GateRequirement, text: str) -> bool:
    """Czy tekst wymienia którąś z opcji wymagania (całe słowo, aliasy)."""
    if not text:
        return False
    return _mentions_lowered(requirement, text, text.lower())


def profile_text(candidate) -> str:
    """Tekst profilu kandydata: stanowiska, umiejętności, pola z Traffita, tagi."""
    parts: list[str] = []
    for attr in ("skills", "verified_tech", "tags", "experience"):
        value = getattr(candidate, attr, None)
        if value:
            parts.append(json.dumps(value, ensure_ascii=False, default=str))
    data = getattr(candidate, "cv_extracted_data", None)
    if isinstance(data, dict):
        for key in _PROFILE_DATA_KEYS:
            value = data.get(key)
            if value:
                parts.append(
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False, default=str)
                )
    for attr in ("current_position", "headline", "title"):
        value = getattr(candidate, attr, None)
        if isinstance(value, str) and value:
            parts.append(value)
    return "\n".join(parts)


def cv_text(candidate) -> str:
    value = getattr(candidate, "raw_cv_text", None)
    return value if isinstance(value, str) else ""


def text_met_labels(
    candidate, must: Sequence[str], note_texts: Iterable[str] = ()
) -> frozenset[str]:
    """Etykiety must, które profil, CV albo notatki wymieniają."""
    requirements = [
        (label, gate_requirement(label)) for label in must if gate_requirement(label)
    ]
    if not requirements:
        return frozenset()
    sources = [
        (text, text.lower())
        for text in (profile_text(candidate), cv_text(candidate), *note_texts)
        if text
    ]
    met: set[str] = set()
    for label, requirement in requirements:
        if any(_mentions_lowered(requirement, t, low) for t, low in sources):
            met.add(label)
    return frozenset(met)


def evidence_for(candidate, must: Sequence[str]) -> Optional[MustTextEvidence]:
    """Dowód dołączony przez ``attach_gate_evidence`` dla listy obejmującej ``must``."""
    evidence = getattr(candidate, "_must_text_evidence", None)
    # 30.09.2026: dowód dołącza się raz dla wszystkich technologii must+nice
    # oferty; bramka (krytyczne), plakietki i ocena biorą z niego podzbiór.
    if isinstance(evidence, MustTextEvidence) and set(must) <= set(evidence.key):
        return evidence
    return None


def has_any_data(candidate, evidence: Optional[MustTextEvidence]) -> bool:
    """CV, lista umiejętności albo notatki — cokolwiek, z czego da się ocenić."""
    from app.services.scoring_service import candidate_known_skill_names

    if cv_text(candidate).strip():
        return True
    if candidate_known_skill_names(candidate):
        return True
    return bool(evidence and evidence.has_notes)


def _loose_pg_pattern(must: Sequence[str]) -> Optional[str]:
    """Wstępny filtr notatek w SQL: którakolwiek forma, bez granic słowa.

    Tylko zawęża, co wraca z bazy — o dopasowaniu decyduje ``mentions``.
    """
    from app.services.scoring_service import skill_name_variants

    forms: set[str] = set()
    for label in must:
        requirement = gate_requirement(label)
        if requirement is None:
            continue
        for option in requirement.options:
            for form in [option.lower(), *skill_name_variants([option])]:
                if len(form.strip()) >= 2:
                    forms.add(form.strip())
    if not forms:
        return None
    return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))


async def attach_gate_evidence(db, candidates: Sequence, must: Sequence[str]) -> None:
    """Dołącz ``_must_text_evidence`` do kandydatów przed ``apply_dealbreakers``.

    Dwa zapytania na paczkę: kto ma notatki-dowody, i treść tych notatek,
    które wymieniają którąś z technologii. Nigdy nie rzuca dalej — błąd bazy
    zostawia kandydatów bez dołączonego dowodu, a bramka sprawdza wtedy sam
    profil i CV (``missing_must_skills``).
    """
    must = tuple(must)
    ids = [c.id for c in candidates if getattr(c, "id", None) is not None]
    if not ids:
        return
    # Pusta lista też dołącza `has_notes`: kandydat bez CV i umiejętności,
    # ale z notatką z rozmowy, nie jest „bez danych” (30.09.2026).
    pattern = _loose_pg_pattern(must) if must else None
    try:
        # Savepoint: błąd zapytania (np. regex, timeout) nie może zostawić
        # transakcji wywołującego w stanie „aborted”.
        async with db.begin_nested():
            has_notes, note_texts = await _load_notes(db, ids, pattern)
    except Exception:  # noqa: BLE001 — dowód z notatek jest dodatkiem
        import logging

        logging.getLogger(__name__).warning(
            "must evidence: notes lookup failed", exc_info=True
        )
        return
    for index, candidate in enumerate(candidates):
        # ~0,4 ms CPU na kandydata; pełny przegląd bazy żyje w procesie web,
        # więc oddajemy pętlę zdarzeń co 32 osoby (jak `canonical_fit`).
        if index and index % YIELD_EVERY == 0:
            await asyncio.sleep(0)
        cid = getattr(candidate, "id", None)
        if cid is None:
            continue
        candidate._must_text_evidence = MustTextEvidence(
            key=must,
            met=text_met_labels(candidate, must, note_texts.get(cid, ())),
            has_notes=cid in has_notes,
        )


async def _load_notes(db, ids: list[int], pattern: Optional[str]):
    from sqlalchemy import text

    note_texts: dict[int, list[str]] = {}
    rows = await db.execute(
        text(
            "SELECT DISTINCT candidate_id FROM notes "
            "WHERE candidate_id = ANY(:ids) AND source_deleted_at IS NULL "
            "AND note_type::text = ANY(:types)"
        ),
        {"ids": ids, "types": list(EVIDENCE_NOTE_TYPES)},
    )
    has_notes = {row[0] for row in rows}
    if pattern and has_notes:
        rows = await db.execute(
            text(
                "SELECT candidate_id, content FROM notes "
                "WHERE candidate_id = ANY(:ids) AND source_deleted_at IS NULL "
                "AND note_type::text = ANY(:types) AND content ~* :pattern"
            ),
            {
                "ids": sorted(has_notes),
                "types": list(EVIDENCE_NOTE_TYPES),
                "pattern": pattern,
            },
        )
        for candidate_id, content in rows:
            note_texts.setdefault(candidate_id, []).append(content or "")
    return has_notes, note_texts
