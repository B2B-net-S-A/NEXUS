"""Rejestr faktów z rozmów: arkusz screeningu i odczyt notatek (08.11.2026).

Decyzja Artura z 08.11.2026 (wariant A, raport
https://claude.ai/artifact/HgCGsxN7Nk7ENGpb6iNg2B): fakty z rozmów zapisują się
same, bez potwierdzania. Flaga ``CONVERSATION_FACTS_ENABLED`` (domyślnie false),
false = zachowanie sprzed zmiany. Reguły: ``docs/claude/screening-notatki/
rozmowy-i-profil-rejestr-faktow.md``.

Źródłem prawdy jest tabela ``candidate_conversation_facts``. Czytelnicy bramki
i wyniku (``must_text_evidence``, ``scoring_service``) to czyste funkcje nad
załadowanym kandydatem, więc czytają projekcję w
``cv_extracted_data._conversation_facts``, przebudowywaną z tabeli przy każdym
zapisie (``refresh_projection``). Projekcja przeżywa nowe CV, bo klucz jest
w ``NON_CV_EXTRACTED_KEYS``.

* Wymaganie zmapowane na słownik liczy się w każdej rekrutacji. Zdanie bez
  odpowiednika liczy się tylko w rekrutacji, w której padło.
* Status „nie ma” pochodzi wyłącznie z arkusza, i tylko nazwa dokładnie ze
  słownika działa poza tą rekrutacją: „Nie ma” przy zdaniu nie mówi, czego
  z niego brakuje.
* Kliknięcie człowieka bije odczyt modelu niezależnie od daty; z kilku kliknięć
  wygrywa najnowsze.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.candidate_conversation_fact import CandidateConversationFact as Fact

logger = logging.getLogger(__name__)

KIND_SKILL = "skill"
KIND_DOMAIN = "domain"
KIND_CERTIFICATION = "certification"
KIND_REGULATION = "regulation"
# Rodzaje z sekcji 4 Championa (`ExperienceKind`) → rodzaj w rejestrze.
KIND_BY_EXPERIENCE: Mapping[str, str] = {
    "skills": KIND_SKILL,
    "domains": KIND_DOMAIN,
    "certifications": KIND_CERTIFICATION,
    "regulations": KIND_REGULATION,
}
STATUS_CONFIRMED = "confirmed"
STATUS_ABSENT = "absent"
SOURCE_SHEET = "sheet"
SOURCE_NOTE_AI = "note_ai"
PROJECTION_KEY = "_conversation_facts"
EVIDENCE_MAX_CHARS = 500
_VALUE_MAX_CHARS = 300

# „Kafka lub RabbitMQ”, „bazy danych np. Oracle, PostgreSQL”: potwierdzenie
# mówi, że kandydat zna COŚ z listy, ale nie wiadomo co.
_ALTERNATIVE_RE = re.compile(
    r"/|\b(?:lub|albo|or|np|e\.g|eg|like|such\s+as|typu|takie\s+jak)\b", re.I
)


def enabled() -> bool:
    return bool(getattr(settings, "CONVERSATION_FACTS_ENABLED", False))


def value_key(value: str) -> str:
    """Klucz porównania nazwy: bez nadmiaru spacji i wielkości liter."""
    return " ".join((value or "").split()).casefold()[:_VALUE_MAX_CHARS]


# ── Mapowanie na słownik ─────────────────────────────────────────────────────


def _exact_term(name: str) -> Optional[str]:
    """Pozycja słownika, gdy CAŁA nazwa nią jest (także z wersją: „Java 8+”)."""
    from app.services.scoring_service import canonical_skill_names
    from app.services.skill_normalize import ALIAS_TO_CANONICAL, canonical_of
    from app.services.skill_normalize import strip_version

    for candidate in (name, strip_version(name)[0]):
        low = " ".join((candidate or "").split()).lower()
        if low and low in ALIAS_TO_CANONICAL:
            names = canonical_skill_names([canonical_of(low)])
            return names[0] if names else canonical_of(low)
    return None


def _terms_in_sentence(name: str) -> list[str]:
    """Technologie ze słownika wymienione w zdaniu, bez aliasów-zwykłych słów."""
    from app.services.scoring_service import (
        ALIAS_MAP,
        POLISH_WORD_ALIASES,
        _alias_pattern,
    )
    from app.services.skill_normalize import is_taxonomy_technology

    pattern = _alias_pattern()
    if pattern is None:
        return []
    found: list[str] = []
    for match in pattern.finditer(name):
        alias = match.group(1)
        low = alias.lower()
        # „rest” małymi literami to zwykłe słowo, tak samo „Jest”, „go”, „C”.
        if low in POLISH_WORD_ALIASES or len(low) < 2 or alias == "rest":
            continue
        term = ALIAS_MAP.get(low)
        if term and is_taxonomy_technology(term) and term not in found:
            found.append(term)
    return found


def map_requirement(name: str, status: str) -> list[str]:
    """Nazwy ze słownika, które wymaganie niesie. Pusta lista = tylko ta rekrutacja.

    Cała nazwa ze słownika liczy się przy obu statusach. Technologie wyjęte ze
    zdania („Optymalizacja zapytań PL/SQL” → PL/SQL) wyłącznie przy
    potwierdzeniu i bez wymienionych alternatyw.
    """
    exact = _exact_term(name)
    if exact is not None:
        return [exact]
    if status != STATUS_CONFIRMED:
        return []
    terms = _terms_in_sentence(name)
    if len(terms) > 1 and _ALTERNATIVE_RE.search(name):
        return []
    return terms


# ── Projekcja ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FactRow:
    """Wiersz rejestru potrzebny do projekcji (czysta funkcja bez ORM)."""

    kind: str
    value: str
    value_key: str
    terms: tuple[str, ...]
    status: str
    source: str
    job_id: Optional[int]
    noted_at: datetime


def _row(fact: Fact) -> FactRow:
    return FactRow(
        kind=fact.kind,
        value=fact.value,
        value_key=fact.value_key,
        terms=tuple(fact.canonical_terms or ()),
        status=fact.status,
        source=fact.source,
        job_id=fact.job_id,
        noted_at=fact.noted_at,
    )


def _display(term: str, value: str) -> str:
    """Nazwa do listy umiejętności: pisownia z wymagania, gdy w nim stoi."""
    found = re.search(re.escape(term), value, re.I)
    return found.group(0) if found else term


def _unique(items: Iterable[str]) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(item.casefold(), item)
    return sorted(seen.values(), key=str.casefold)


def build_projection(rows: Sequence[FactRow]) -> dict[str, Any]:
    """Skutek rejestru dla bramki i wyniku. Czysta funkcja, bez ``written``."""
    by_term: dict[str, list[FactRow]] = {}
    for row in rows:
        for term in row.terms:
            by_term.setdefault(term, []).append(row)
    confirmed: list[str] = []
    absent: list[str] = []
    names: list[str] = []
    for term, facts in by_term.items():
        sheets = [fact for fact in facts if fact.source == SOURCE_SHEET]
        deciding = max(sheets, key=lambda f: f.noted_at) if sheets else None
        if deciding is not None and deciding.status == STATUS_ABSENT:
            absent.append(term)
            continue
        confirmed.append(term)
        names.extend(_display(term, f.value) for f in facts if f.kind == KIND_SKILL)
    # Odczyt modelu bez odpowiednika w słowniku zostaje faktem o osobie (tak
    # działał przed rejestrem), a zdanie z arkusza tylko w swojej rekrutacji.
    loose = [r for r in rows if r.source == SOURCE_NOTE_AI and not r.terms]
    names.extend(r.value for r in loose if r.kind == KIND_SKILL)
    jobs: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        if row.source != SOURCE_SHEET or row.job_id is None:
            continue
        job = jobs.setdefault(str(row.job_id), {"confirmed": [], "absent": []})
        job[row.status].append(row.value_key)
    return {
        "confirmed": sorted(confirmed),
        "absent": sorted(absent),
        "skills": _unique(names),
        "texts": _unique([*confirmed, *(r.value for r in loose)]),
        "jobs": {
            key: {k: sorted(v) for k, v in job.items()} for key, job in jobs.items()
        },
    }


def _revision(projection: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in projection.items() if k in _REVISED_KEYS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


_REVISED_KEYS = ("confirmed", "absent", "skills", "texts", "jobs", "notes_read")


def _projection(candidate: Any) -> Optional[dict]:
    if not enabled():
        return None
    data = getattr(candidate, "cv_extracted_data", None)
    value = data.get(PROJECTION_KEY) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else None


def revision(candidate: Any) -> Optional[str]:
    """Wersja faktów kandydata do ``candidate_revision`` (bez faktów ``None``)."""
    projection = _projection(candidate)
    return str(projection["rev"]) if projection and projection.get("rev") else None


def absent_terms(candidate: Any) -> frozenset[str]:
    projection = _projection(candidate)
    return frozenset(projection.get("absent") or ()) if projection else frozenset()


def confirmed_terms(candidate: Any) -> frozenset[str]:
    projection = _projection(candidate)
    return frozenset(projection.get("confirmed") or ()) if projection else frozenset()


def evidence_names(candidate: Any) -> list[str]:
    """Nazwy potwierdzone w rozmowach, ważne w każdej rekrutacji."""
    projection = _projection(candidate)
    return list(projection.get("texts") or ()) if projection else []


def _job_lists(candidate: Any, job_id: Optional[int]) -> Mapping[str, Sequence[str]]:
    projection = _projection(candidate)
    jobs = projection.get("jobs") if projection else None
    if job_id is None or not isinstance(jobs, dict):
        return {}
    entry = jobs.get(str(job_id))
    return entry if isinstance(entry, dict) else {}


def job_confirmed_labels(
    candidate: Any, labels: Sequence[str], job_id: Optional[int]
) -> frozenset[str]:
    """Etykiety potwierdzone w arkuszu tej rekrutacji."""
    lists = _job_lists(candidate, job_id)
    keys = set(lists.get(STATUS_CONFIRMED) or ())
    return frozenset(label for label in labels if value_key(label) in keys)


def _term_of(option: str) -> str:
    from app.services.scoring_service import canonical_skill_names

    names = canonical_skill_names([option])
    return names[0] if names else option.strip().lower()


def narrow_requirement(requirement: Any, candidate: Any) -> Any:
    """Wymaganie bez opcji, których kandydat nie ma; bez opcji = ``None``."""
    absent = absent_terms(candidate)
    if not absent or requirement is None:
        return requirement
    kept = tuple(o for o in requirement.options if _term_of(o) not in absent)
    if len(kept) == len(requirement.options):
        return requirement
    return replace(requirement, options=kept) if kept else None


def absent_labels(
    candidate: Any,
    labels: Sequence[str],
    *,
    options: Optional[Mapping[str, Sequence[str]]] = None,
    job_id: Optional[int] = None,
) -> frozenset[str]:
    """Etykiety, których kandydat według arkusza nie ma (bramka: brak)."""
    if not enabled():
        return frozenset()
    from app.services.must_gate_terms import requirement_with_options

    job_absent = set(_job_lists(candidate, job_id).get(STATUS_ABSENT) or ())
    # „Nie ma” przy zdaniu w tej rekrutacji znaczy brak także wtedy, gdy potem
    # zaznaczono „Potwierdził” w innym wierszu z tą samą treścią.
    job_confirmed = set(_job_lists(candidate, job_id).get(STATUS_CONFIRMED) or ())
    out: set[str] = set()
    for label in labels:
        key = value_key(label)
        if key in job_absent and key not in job_confirmed:
            out.add(label)
            continue
        requirement = requirement_with_options(label, options)
        if (
            requirement is not None
            and narrow_requirement(requirement, candidate) is None
        ):
            out.add(label)
    return frozenset(out)


def adjust_known_skills(candidate: Any, known: set[str], *, curated: bool) -> set[str]:
    """Znane umiejętności po rozmowach: bez „nie ma”, z potwierdzonymi.

    Lista poprawiona ręcznie jest kompletna: rozmowa ją tylko zawęża, a dowód
    potwierdzenia bramka bierze z ``evidence_names``.
    """
    if not enabled():
        return known
    adjusted = set(known) if curated else set(known) | set(confirmed_terms(candidate))
    return adjusted - set(absent_terms(candidate))


# ── Lista umiejętności w profilu ─────────────────────────────────────────────


def _skills_locked(candidate: Any) -> bool:
    from app.services.cv_enrichment import _loaded_flag

    data = candidate.cv_extracted_data
    return bool(
        (isinstance(data, dict) and data.get("_manual_override_skills"))
        or _loaded_flag(candidate, "skills_manually_curated")
    )


def merge_skill_names(
    skills: Any, wanted: Sequence[str], written: Sequence[str]
) -> tuple[list, list[str], int]:
    """(lista umiejętności, co dopisał rejestr, ile dopisano teraz).

    Pozycje, które rejestr dopisał wcześniej, a których już nie chce, znikają.
    Pozycji spoza rejestru (CV, człowiek) ta funkcja nie zdejmuje nigdy.
    """
    wanted_folded = {name.casefold() for name in wanted}
    stale = {n.casefold() for n in written if n.casefold() not in wanted_folded}
    current = [
        item
        for item in (skills if isinstance(skills, list) else [])
        if not (
            isinstance(item, dict) and str(item.get("name", "")).casefold() in stale
        )
    ]
    have = {
        str(item.get("name", "")).casefold()
        for item in current
        if isinstance(item, dict)
    }
    still_ours = [n for n in written if n.casefold() in wanted_folded]
    added = [name for name in wanted if name.casefold() not in have]
    return (
        current + [{"name": name, "level": None} for name in added],
        _unique([*still_ours, *added]),
        len(added),
    )


def reapply_after_cv(candidate: Candidate, next_extracted: dict) -> None:
    """Nowe CV zastąpiło listę: umiejętności z rozmów wracają na nią (bez commitu).

    Wołane z ``_apply_cv_enrichment``, wyłącznie gdy odczyt zapisał ``skills``,
    więc lista poprawiona ręcznie tu nie trafia.
    """
    if not enabled():
        return
    projection = next_extracted.get(PROJECTION_KEY)
    if not isinstance(projection, dict):
        return
    wanted = list(projection.get("skills") or ())
    # Zaczynamy od pustego `written`: pozycji, które stoją też w nowym CV, cofnięcie
    # faktu nie może zdjąć.
    skills, written, _ = merge_skill_names(candidate.skills, wanted, ())
    candidate.skills = skills
    next_extracted[PROJECTION_KEY] = {**projection, "written": written}


# ── Zapis ────────────────────────────────────────────────────────────────────


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _active(db: AsyncSession, candidate_id: int) -> list[Fact]:
    return list(
        (
            await db.scalars(
                select(Fact).where(
                    Fact.candidate_id == candidate_id, Fact.retired_at.is_(None)
                )
            )
        ).all()
    )


async def refresh_projection(
    db: AsyncSession, candidate: Candidate, *, notes_read: Optional[str] = None
) -> int:
    """Przebuduj projekcję i dopisz umiejętności. Zwraca, ile pozycji doszło.

    ``notes_read`` — odcisk właśnie przeczytanych notatek: nowa notatka zmienia
    wersję profilu także wtedy, gdy nie wniosła żadnej umiejętności (stawka,
    dostępność, tryb pracy też zmieniają wynik).
    """
    await db.flush()
    # Flush z UPDATE wygasza `column_property`: bez tego lista poprawiona ręcznie
    # wyglądałaby na niezablokowaną.
    await db.refresh(candidate, attribute_names=["skills_manually_curated"])
    rows = [_row(fact) for fact in await _active(db, candidate.id)]
    data = candidate.cv_extracted_data
    extracted = dict(data) if isinstance(data, dict) else {}
    previous = extracted.get(PROJECTION_KEY)
    previous = previous if isinstance(previous, dict) else {}
    written = list(previous.get("written") or ())
    projection = build_projection(rows)
    notes_stamp = notes_read or previous.get("notes_read")
    if notes_stamp:
        projection["notes_read"] = notes_stamp
    added = 0
    if not _skills_locked(candidate):
        wanted = list(projection["skills"])
        skills, written, added = merge_skill_names(candidate.skills, wanted, written)
        if added or skills != candidate.skills:
            candidate.skills = skills
    projection["written"] = written
    projection["rev"] = _revision(projection)
    if previous == projection:
        return 0
    extracted[PROJECTION_KEY] = projection
    candidate.cv_extracted_data = extracted
    flag_modified(candidate, "cv_extracted_data")
    return added


@dataclass(frozen=True)
class SheetCheck:
    kind: str
    name: str
    status: str
    note: str = ""


def sheet_checks(raw: Any) -> list[SheetCheck]:
    """Sprawdzenia z ``screening_answers.experience_checks``, tylko rozstrzygnięte."""
    status_of = {"confirmed": STATUS_CONFIRMED, "not_confirmed": STATUS_ABSENT}
    out: list[SheetCheck] = []
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, Mapping):
            continue
        name = " ".join(str(item.get("name") or "").split())
        status = status_of.get(str(item.get("status") or ""))
        kind = KIND_BY_EXPERIENCE.get(str(item.get("kind") or "domains"))
        if name and status and kind:
            out.append(
                SheetCheck(kind, name, status, str(item.get("note") or "").strip())
            )
    return out


def _fact_terms(check: SheetCheck) -> list[str]:
    # Branże, certyfikaty i regulacje mapujemy tylko całą nazwą: technologia
    # wymieniona w opisie branży nie mówi, że kandydat ją zna.
    if check.kind == KIND_SKILL:
        return map_requirement(check.name, check.status)
    exact = _exact_term(check.name)
    return [exact] if exact else []


async def sync_sheet(
    db: AsyncSession,
    *,
    candidate: Candidate,
    job_id: int,
    stage_id: Optional[int],
    checks: Sequence[SheetCheck],
    user_id: Optional[int],
    now: datetime,
    batch: Optional[str] = None,
) -> bool:
    """Stan arkusza pary trafia do rejestru (bez commitu). Zwraca, czy się zmienił.

    Arkusz jest w całości zapisem człowieka, więc obowiązuje stan z tego
    zapisu: zdjęte kliknięcie gasi fakt. Kopie arkusza przy ruchach karty
    nie mnożą wierszy, bo kluczem jest para (osoba, rekrutacja).
    """
    existing = {
        (fact.kind, fact.value_key): fact
        for fact in (
            await db.scalars(
                select(Fact).where(
                    Fact.candidate_id == candidate.id,
                    Fact.job_id == job_id,
                    Fact.source == SOURCE_SHEET,
                    Fact.retired_at.is_(None),
                )
            )
        ).all()
    }
    wanted = {(c.kind, value_key(c.name)): c for c in checks}
    changed = False
    for key, fact in existing.items():
        if key not in wanted:
            fact.retired_at = now
            changed = True
    for key, check in wanted.items():
        evidence = check.note[:EVIDENCE_MAX_CHARS] or None
        fact = existing.get(key)
        if fact is None:
            db.add(
                Fact(
                    candidate_id=candidate.id,
                    kind=check.kind,
                    value=check.name[:_VALUE_MAX_CHARS],
                    value_key=key[1],
                    canonical_terms=_fact_terms(check),
                    status=check.status,
                    source=SOURCE_SHEET,
                    stage_id=stage_id,
                    job_id=job_id,
                    author_id=user_id,
                    evidence=evidence,
                    noted_at=now,
                    batch=batch,
                )
            )
            changed = True
        elif fact.status != check.status or fact.evidence != evidence:
            fact.canonical_terms = _fact_terms(check)
            if fact.status != check.status:
                fact.noted_at = now
            fact.status = check.status
            fact.evidence = evidence
            fact.stage_id = stage_id
            fact.author_id = user_id
            changed = True
    if changed:
        await refresh_projection(db, candidate)
    return changed


def _note_items(parsed: Mapping[str, Any]) -> list[tuple[str, str, Optional[str]]]:
    """(rodzaj, nazwa, dowód) z odczytu notatek. Braki modelu nie są faktem."""
    from app.services.cv_enrichment import normalize_llm_skills

    items: list[tuple[str, str, Optional[str]]] = []
    evidenced = parsed.get("skills_evidenced")
    evidence_by_name = {
        str(item.get("name")).casefold(): item.get("evidence")
        for item in (evidenced if isinstance(evidenced, list) else [])
        if isinstance(item, Mapping) and item.get("name")
    }
    for skill in normalize_llm_skills(list(evidenced or [])) or []:
        quote = evidence_by_name.get(skill["name"].casefold())
        items.append(
            (KIND_SKILL, skill["name"], quote if isinstance(quote, str) else None)
        )
    certifications = parsed.get("certifications")
    for name in certifications if isinstance(certifications, list) else ():
        if isinstance(name, str) and name.strip():
            items.append((KIND_CERTIFICATION, " ".join(name.split()), None))
    return items


async def record_note_facts(
    db: AsyncSession,
    *,
    candidate: Candidate,
    parsed: Mapping[str, Any],
    note_id: Optional[int],
    noted_at: datetime,
    batch: Optional[str] = None,
    notes_read: Optional[str] = None,
) -> int:
    """Fakty z odczytu notatek do rejestru (bez commitu). Zwraca, ile umiejętności doszło.

    Tylko dopisuje: kolejny odczyt, który nazwy nie powtórzył (limit 20
    notatek, inne brzmienie), faktu nie gasi. Gaszą je ``retire_note_facts``
    i skrypt cofnięcia.
    """
    existing = {
        (fact.kind, fact.value_key): fact
        for fact in (
            await db.scalars(
                select(Fact).where(
                    Fact.candidate_id == candidate.id,
                    Fact.source == SOURCE_NOTE_AI,
                    Fact.retired_at.is_(None),
                )
            )
        ).all()
    }
    changed = False
    for kind, name, quote in _note_items(parsed):
        key = (kind, value_key(name))
        evidence = quote[:EVIDENCE_MAX_CHARS] if quote else None
        fact = existing.get(key)
        if fact is not None:
            if evidence and fact.evidence != evidence:
                fact.evidence = evidence
                changed = True
            continue
        new_fact = Fact(
            candidate_id=candidate.id,
            kind=kind,
            value=name[:_VALUE_MAX_CHARS],
            value_key=key[1],
            canonical_terms=(
                map_requirement(name, STATUS_CONFIRMED)
                if kind == KIND_SKILL
                else [t for t in [_exact_term(name)] if t]
            ),
            status=STATUS_CONFIRMED,
            source=SOURCE_NOTE_AI,
            note_id=note_id,
            evidence=evidence,
            noted_at=noted_at,
            batch=batch,
        )
        db.add(new_fact)
        existing[key] = new_fact
        changed = True
    if changed or notes_read:
        return await refresh_projection(db, candidate, notes_read=notes_read)
    return 0


async def retire_note_facts(
    db: AsyncSession, *, candidate: Candidate, now: datetime
) -> None:
    """Kandydat nie ma już czytelnych notatek: gasną fakty z ich odczytu."""
    result = await db.execute(
        update(Fact)
        .where(
            Fact.candidate_id == candidate.id,
            Fact.source == SOURCE_NOTE_AI,
            Fact.retired_at.is_(None),
        )
        .values(retired_at=now)
    )
    if result.rowcount:
        await refresh_projection(db, candidate)


# ── Po zapisie: przeliczenie osoby ───────────────────────────────────────────


async def _locked_candidate(db: AsyncSession, candidate_id: int) -> Optional[Candidate]:
    # Świeży odczyt pod blokadą: obiekt z sesji mógł powstać przed nią, a piszemy
    # `skills` i `cv_extracted_data`.
    return await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def enqueue_recalculation(
    db: AsyncSession, candidate: Candidate, *, cause: Optional[str] = None
) -> None:
    """Zdarzenie ``conversation`` w kolejce auto-dopasowania i reindeks profilu."""
    from app.services import auto_match_outbox
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

    await record_bulk_reindex(db, CANDIDATE, [candidate.id])
    await auto_match_outbox.enqueue_candidate(
        db,
        candidate_id=candidate.id,
        trigger="conversation",
        profile_revision=cause or auto_match_outbox.candidate_revision(candidate),
    )


async def after_sheet_saved(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    stage_id: Optional[int],
    raw_checks: Any,
    user_id: Optional[int],
    now: datetime,
) -> bool:
    """Arkusz zapisany: fakty do rejestru i zdarzenie przeliczenia (bez commitu)."""
    if not enabled():
        return False
    candidate = await _locked_candidate(db, candidate_id)
    if candidate is None:
        return False
    changed = await sync_sheet(
        db,
        candidate=candidate,
        job_id=job_id,
        stage_id=stage_id,
        checks=sheet_checks(raw_checks),
        user_id=user_id,
        now=now,
    )
    if changed:
        await enqueue_recalculation(db, candidate)
    return changed


# Rodzaje notatek bez rozmowy: nie ma czego czytać od razu.
def _note_is_conversation(note: Any) -> bool:
    from app.services import note_kinds
    from app.services.must_text_evidence import EVIDENCE_NOTE_TYPES

    note_type = getattr(note.note_type, "value", note.note_type)
    return (
        note.candidate_id is not None
        and note_type in EVIDENCE_NOTE_TYPES
        and note.kind not in note_kinds.FACTS_EXCLUDED_KINDS
        and note.external_source != note_kinds.SYSTEM_SOURCE
    )


async def after_note_saved(db: AsyncSession, note: Any) -> None:
    """Notatka z rozmowy: odczyt tej osoby od razu, nie w nocy (bez commitu).

    Wersja ``note:<id>`` odróżnia zdarzenie od zapisu arkusza. Dzięki niej dwie
    notatki w tej samej minucie nie zwijają się do jednego odczytu.
    """
    if not enabled() or not _note_is_conversation(note):
        return
    from app.services import auto_match_outbox

    await auto_match_outbox.enqueue_candidate(
        db,
        candidate_id=note.candidate_id,
        trigger="conversation",
        profile_revision=f"note:{note.id}",
    )


# ── Odczyt do profilu ────────────────────────────────────────────────────────


async def list_for_profile(
    db: AsyncSession, *, candidate_id: int, job_scope: Any
) -> list[dict[str, Any]]:
    """Fakty do bloku „Z rozmów”, najnowsze najpierw.

    Odczyt modelu, który przegrał z kliknięciem „Nie ma”, nie jest pokazywany:
    rekruter widziałby dwie sprzeczne pozycje o jednej technologii. Rekrutacji
    spoza zakresu osoby czytającej nie nazywamy.
    """
    from app.models.job import Job
    from app.models.user import User

    candidate = await db.get(Candidate, candidate_id)
    absent = absent_terms(candidate)
    rows = (
        await db.execute(
            select(Fact, Job.title, User.name)
            .select_from(Fact)
            .outerjoin(Job, (Job.id == Fact.job_id) & job_scope)
            .outerjoin(User, User.id == Fact.author_id)
            .where(Fact.candidate_id == candidate_id, Fact.retired_at.is_(None))
            .order_by(Fact.noted_at.desc(), Fact.id.desc())
        )
    ).all()
    out: list[dict[str, Any]] = []
    for fact, title, author in rows:
        terms = list(fact.canonical_terms or ())
        if fact.source == SOURCE_NOTE_AI and terms and set(terms) <= absent:
            continue
        out_of_scope = fact.job_id is not None and title is None
        if out_of_scope and not terms:
            continue
        out.append(
            {
                "id": fact.id,
                "kind": fact.kind,
                "value": fact.value,
                "status": fact.status,
                "source": fact.source,
                "noted_at": fact.noted_at,
                "job_id": fact.job_id if title is not None else None,
                "job_title": title,
                "author_name": author,
                "evidence": None if out_of_scope else fact.evidence,
                "job_only": fact.source == SOURCE_SHEET and not terms,
            }
        )
    return out


# ── Dobór kart: weto na klienta i „nie szuka” ────────────────────────────────

# „Nie pracował wcześniej w Nordei” model potrafi wpisać jako weto (31 z 460
# wpisów na kopii z 08.11.2026), a to brak historii, nie odmowa.
_NOT_A_VETO_RE = re.compile(
    r"\bnie\s+(?:pracował\w*|współpracował\w*)\s+(?:wcześniej|dotąd|nigdy)", re.I
)
# „Za pół roku”, „aktualnie nie szuka”: bez daty liczymy od odczytu notatek.
NOT_LOOKING_TEXT_DAYS = 183


def not_looking_now(insights: Mapping[str, Any], today: Any) -> bool:
    """Czy odczyt notatek mówi, że osoba teraz nie szuka pracy.

    Data w tekście rozstrzyga. Tekst bez daty obowiązuje przez
    ``NOT_LOOKING_TEXT_DAYS`` od odczytu.
    """
    from datetime import date, timedelta

    from app.services.notes_profile_fill import _explicit_date, _month_start

    raw = insights.get("not_looking_until")
    if not isinstance(raw, str) or not raw.strip():
        return False
    stamp = insights.get("_v2_extracted_at")
    try:
        read_on = (
            datetime.fromisoformat(stamp).date() if isinstance(stamp, str) else None
        )
    except ValueError:
        read_on = None
    until = _explicit_date(raw) or _month_start(raw, read_on)
    if isinstance(until, date):
        return until >= today
    return read_on is not None and today <= read_on + timedelta(
        days=NOT_LOOKING_TEXT_DAYS
    )


def vetoes_client(insights: Mapping[str, Any], labels: Sequence[tuple]) -> bool:
    """Czy któreś weto z notatek dotyczy klienta o tych etykietach."""
    from app.services.client_off_limits import _match_label

    vetoes = insights.get("client_vetoes")
    for veto in vetoes if isinstance(vetoes, list) else ():
        if not isinstance(veto, Mapping):
            continue
        if _NOT_A_VETO_RE.search(str(veto.get("reason") or "")):
            continue
        if _match_label(str(veto.get("client") or ""), list(labels)) is not None:
            return True
    return False


async def blocked_for_job(
    db: AsyncSession, job_id: int, candidate_ids: Sequence[int]
) -> set[int]:
    """Osoby, których system nie dodaje do tej rekrutacji po odczycie notatek."""
    if not enabled() or not candidate_ids:
        return set()
    from app.core.scheduling import business_today
    from app.models.job import Job
    from app.services.client_off_limits import client_labels

    client_id = await db.scalar(select(Job.client_id).where(Job.id == job_id))
    labels = await client_labels(db, client_id) if client_id is not None else []
    today = business_today()
    rows = await db.execute(
        select(Candidate.id, Candidate.cv_extracted_data["_notes_insights"]).where(
            Candidate.id.in_(list(candidate_ids))
        )
    )
    blocked: set[int] = set()
    for candidate_id, insights in rows.all():
        if isinstance(insights, dict) and (
            not_looking_now(insights, today) or vetoes_client(insights, labels)
        ):
            blocked.add(int(candidate_id))
    return blocked
