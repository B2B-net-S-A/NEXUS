"""Umiejętności krytyczne: które must ukrywają kandydatów (decyzje Artura 30.09.2026).

Bramka must nie działa już na KAŻDEJ pozycji must — ukrywała 41,5% osób, które
zespół potem wysyłał do klienta (audyt ``docs/audits/2026-09-30/wyszukiwanie-kandydatow.md``).
Ukrywają wyłącznie pozycje „krytyczne” — najwyżej trzy z wyboru Delivery Leada
(do 08.10.2026 dwie), a z podpowiedzi z historii najwyżej dwie; reszta must
i nice daje punkty.

Stany pola ``stack.critical`` w profilu Championa:

- ``None`` — Delivery Lead nie zdecydował: działa podpowiedź z historii,
  a przekazanie do searchu czeka na decyzję;
- ``[]`` — świadomie brak krytycznych: bramka must nie ukrywa nikogo;
- ``["Java", …]`` (najwyżej 3) — bramka na tych pozycjach. Wybrać można KAŻDĄ
  pozycję must (decyzja Artura 09.10.2026: o tym, co jest krytyczne, decyduje
  Delivery Lead, system nie odrzuca żadnej frazy). Pozycja, która nie jest
  nazwą technologii (branża, język, zdanie), ukrywa tak samo: bramka szuka
  słów jej wiersza w profilu, CV i notatkach (``critical_gate_options``).

Podpowiedź: technologie z listy must (``must_gate_terms.critical_eligible``),
które ≥90% osób wysłanych do klienta w innych rekrutacjach ma w profilu, CV
albo notatkach (≥5 rekrutacji historii); najpierw te z tytułu rekrutacji,
potem według odsetka. Statystyki liczy ``compute_stats`` raz w tygodniu
(pętla nocnego przeglądu) i trzyma w ``app_settings['critical_skill_stats']``;
do pierwszego przeliczenia działa seed z badania
(``app/data/critical_skill_stats_seed.json``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Sequence

from app.core.config import settings
from app.schemas.champion import CRITICAL_MAX
from app.services import note_kinds

logger = logging.getLogger(__name__)

STATS_KEY = "critical_skill_stats"
STATS_VERSION = 1
# Ile krytycznych wolno WYBRAĆ Delivery Leadowi — jedna stała ze schematem profilu.
MAX_CRITICAL = CRITICAL_MAX
# Podpowiedź z historii działa bez decyzji człowieka, więc zostaje przy dwóch:
# trzecia automatyczna bramka ukrywałaby więcej osób, niż zmierzono (07.10.2026).
SUGGEST_MAX = 2
SUGGEST_MIN_RATE = 0.90
SUGGEST_MIN_JOBS = 5
# Podpowiedź bierze technologię z tytułu albo z początku KRÓTKIEJ listy must
# (07.10.2026). Daleka pozycja długiej listy przepisanej z ogłoszenia („C#”
# na 7. miejscu w roli Java/Angular) ukrywała 7,1% osób zweryfikowanych przez
# zespół; z tą regułą 2,7% (pomiar na 352 rekrutacjach, 3 115 parach).
SUGGEST_MAX_POSITION = 3
SUGGEST_MAX_LIST = 8
MIN_SENT_PER_JOB = 3
RECOMPUTE_EVERY = timedelta(days=7)
_SEED_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "critical_skill_stats_seed.json"
)
# Etapy „wysłany do klienta” (widok `analytics_first_milestones`).
_SENT_STAGES = ("cv_sent", "interview", "client_interview", "acceptance", "hired")
_JOB_BATCH = 50

CriticalSource = Literal["dl", "suggested", "none"]


@dataclass(frozen=True)
class SkillStat:
    rate: float
    jobs: int


@dataclass(frozen=True)
class CriticalResolution:
    """Krytyczne jednej rekrutacji — to czyta bramka i ekran Championa."""

    labels: tuple[str, ...]
    source: CriticalSource
    suggested: tuple[str, ...]
    # ``True`` = Delivery Lead zdecydował (lista albo „Brak krytycznych”).
    decided: bool


# ── Statystyki ────────────────────────────────────────────────────────────

_cache: dict[str, Any] = {"payload": None, "index": None, "index_key": None}


def _seed_payload() -> dict:
    try:
        return json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("critical skills: seed missing or unreadable")
        return {"version": STATS_VERSION, "labels": {}}


def current_payload() -> dict:
    """Ostatnio wczytane statystyki albo seed (synchronicznie, bez bazy)."""
    payload = _cache["payload"]
    return payload if isinstance(payload, dict) else _seed_payload()


def set_payload(payload: Optional[dict]) -> None:
    _cache["payload"] = payload if isinstance(payload, dict) else None
    _cache["index"] = None


async def refresh_cache(db) -> dict:
    """Wczytaj statystyki z ``app_settings`` (brak wiersza = seed)."""
    from sqlalchemy import select

    from app.models.app_setting import AppSetting

    value = (
        await db.execute(select(AppSetting.value).where(AppSetting.key == STATS_KEY))
    ).scalar_one_or_none()
    set_payload(value if isinstance(value, dict) and value.get("labels") else None)
    return current_payload()


def _index() -> dict[str, SkillStat]:
    """Statystyki po nazwie kanonicznej technologii (średnia ważona rekrutacjami).

    Klucze zapisane są etykietami must („React.js 18+”, „java”), więc indeks
    liczy się przy odczycie — po wczytaniu słownika umiejętności.
    """
    from app.services.must_gate_terms import gate_requirement
    from app.services.scoring_service import ALIAS_MAP
    from app.services.skill_normalize import canonical_of

    payload = current_payload()
    key = (id(payload), len(ALIAS_MAP))
    if _cache["index"] is not None and _cache["index_key"] == key:
        return _cache["index"]
    weighted: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for label, entry in (payload.get("labels") or {}).items():
        if not isinstance(entry, dict):
            continue
        requirement = gate_requirement(label)
        # Etykieta „A lub B” nie mówi, ile osób ma samo A.
        if requirement is None or len(requirement.options) != 1:
            continue
        jobs = int(entry.get("jobs") or 0)
        rate = float(entry.get("rate") or 0.0)
        if jobs <= 0:
            continue
        acc = weighted[canonical_of(requirement.options[0])]
        acc[0] += rate * jobs
        acc[1] += jobs
    index = {
        canon: SkillStat(rate=round(total / jobs, 4), jobs=int(jobs))
        for canon, (total, jobs) in weighted.items()
        if jobs
    }
    _cache["index"], _cache["index_key"] = index, key
    return index


def stat_for(label: str) -> Optional[SkillStat]:
    """Statystyka pozycji must: najsłabsza z opcji („A lub B” = obie znane)."""
    from app.services.must_gate_terms import gate_requirement
    from app.services.skill_normalize import canonical_of

    requirement = gate_requirement(label)
    if requirement is None:
        return None
    index = _index()
    stats = [index.get(canonical_of(option)) for option in requirement.options]
    if any(s is None for s in stats):
        return None
    return min(stats, key=lambda s: s.rate)  # type: ignore[arg-type]


# ── Podpowiedź i efektywne krytyczne ─────────────────────────────────────


def _title(job) -> str:
    return str(getattr(job, "working_title", None) or getattr(job, "title", None) or "")


def suggest_from_must(must: Sequence[str], title: str = "") -> tuple[str, ...]:
    """Podpowiedź dla listy must (także niezapisanej — ekran /jobs/new)."""
    from app.services.must_gate_terms import critical_eligible, gate_requirement
    from app.services.must_text_evidence import mentions

    scored: list[tuple[int, float, int, str]] = []
    seen: set[str] = set()
    short_list = len(must) <= SUGGEST_MAX_LIST
    for position, label in enumerate(must):
        if not isinstance(label, str) or label.lower() in seen:
            continue
        seen.add(label.lower())
        if not critical_eligible(label):
            continue
        stat = stat_for(label)
        if stat is None or stat.jobs < SUGGEST_MIN_JOBS or stat.rate < SUGGEST_MIN_RATE:
            continue
        requirement = gate_requirement(label)
        in_title = bool(title and requirement and mentions(requirement, title))
        if not in_title and not (short_list and position < SUGGEST_MAX_POSITION):
            continue
        # Najpierw technologia z tytułu (rola „Frontend (Angular)” to Angular,
        # nie Docker z historii), potem odsetek, potem kolejność z listy.
        scored.append((0 if in_title else 1, -stat.rate, position, label))
    scored.sort()
    return tuple(label for *_rest, label in scored[:SUGGEST_MAX])


def suggest_critical(job) -> tuple[str, ...]:
    from app.services.scoring_service import job_explicit_must_skills

    return suggest_from_must(job_explicit_must_skills(job), _title(job))


def stored_critical(job) -> Optional[list[str]]:
    """Decyzja DL z profilu Championa: ``None`` = brak decyzji."""
    profile = getattr(job, "champion_profile", None)
    if not isinstance(profile, dict):
        return None
    stack = profile.get("stack")
    if not isinstance(stack, dict) or "critical" not in stack:
        return None
    value = stack.get("critical")
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, str) and v.strip()]


def match_must_labels(names: Iterable[str], must: Sequence[str]) -> tuple[str, ...]:
    """Pozycje ``must`` odpowiadające nazwom (ta sama technologia albo napis).

    Profil Championa trzyma nazwy w pisowni DL-a („React.js 18+”), a bramka
    czyta etykiety kontraktu wymagań — łączymy je po nazwie kanonicznej.
    """
    from app.services.must_gate_terms import gate_requirement
    from app.services.skill_normalize import canonical_of

    def canon_set(label: str) -> set[str]:
        requirement = gate_requirement(label)
        options = requirement.options if requirement else (label,)
        return {canonical_of(o) for o in options} | {label.strip().lower()}

    wanted = [canon_set(n) for n in names if isinstance(n, str) and n.strip()]
    matched: list[str] = []
    for label in must:
        mine = canon_set(label)
        if any(mine & w for w in wanted) and label not in matched:
            matched.append(label)
    return tuple(matched)


def effective_critical(job) -> CriticalResolution:
    """Krytyczne, na których działa bramka tej rekrutacji."""
    from app.services.scoring_service import job_explicit_must_skills

    frozen = getattr(job, "critical_effective", None)
    if isinstance(frozen, dict) and isinstance(frozen.get("labels"), list):
        # Żądanie pełnego przeglądu (`request_matching_context`) niesie
        # krytyczne z chwili startu — worker bramkuje dokładnie nimi.
        source = frozen.get("source")
        return CriticalResolution(
            labels=tuple(str(x) for x in frozen["labels"]),
            source=source if source in ("dl", "suggested", "none") else "none",
            suggested=tuple(str(x) for x in frozen.get("suggested") or ()),
            decided=bool(frozen.get("decided")),
        )
    must = job_explicit_must_skills(job)
    suggested = suggest_from_must(must, _title(job))
    stored = stored_critical(job)
    if stored is not None:
        # Wybór Delivery Leada bez filtra treści (09.10.2026) — do tej daty
        # fraza spoza technologii była tu po cichu zdejmowana.
        labels = match_must_labels(stored, must)[:MAX_CRITICAL]
        return CriticalResolution(
            labels=labels,
            source="dl" if labels else "none",
            suggested=suggested,
            decided=True,
        )
    return CriticalResolution(
        labels=suggested,
        source="suggested" if suggested else "none",
        suggested=suggested,
        decided=False,
    )


def critical_errors(
    critical: Sequence[str], must: Sequence[str]
) -> list[tuple[str, str]]:
    """Błędy wyboru krytycznych (kod, zdanie po polsku) — zapis je odrzuca."""
    errors: list[tuple[str, str]] = []
    if len(critical) > MAX_CRITICAL:
        errors.append(
            (
                "critical_too_many",
                f"Wybierz najwyżej {MAX_CRITICAL} umiejętności krytyczne.",
            )
        )
    for name in critical:
        if not match_must_labels([name], must):
            errors.append(
                (
                    "critical_not_in_must",
                    f"„{name}” nie ma na liście MUST — krytyczne wybierasz z MUST.",
                )
            )
    return errors


def _row_words_by_label(job) -> list[tuple[str, list[str]]]:
    """Wiersze obowiązkowe profilu Championa: (etykieta wiersza, słowa)."""
    from app.services.champion_requirement_rows import row_label

    profile = getattr(job, "champion_profile", None)
    stack = profile.get("stack") if isinstance(profile, dict) else None
    rows = stack.get("rows") if isinstance(stack, dict) else None
    out: list[tuple[str, list[str]]] = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or row.get("level") == "nice":
            continue
        words = [
            w.strip()
            for w in row.get("words") or ()
            if isinstance(w, str) and len(w.strip()) >= 2
        ]
        label = row_label(words) if words else ""
        if label:
            out.append((label, words))
    return out


def critical_gate_options(job) -> dict[str, tuple[str, ...]]:
    """Słowa, których bramka szuka dla krytycznych z wyboru Delivery Leada.

    Etykieta → słowa jej wiersza (``stack.rows``): w wierszu wystarczy jedno,
    więc każde z nich spełnia krytyczne — tak samo czyta je „Szukaj ręcznie”.
    Fraza bez wiersza (profil na starych polach) szuka samej siebie. Wpis
    powstaje tylko wtedy, gdy coś dodaje do ``gate_requirement``: technologia
    bez wariantów w wierszu działa jak dotąd. Podpowiedź z historii (nikt jej
    nie potwierdził) nie dostaje słów wiersza. Zamrożone żądanie pełnego
    przeglądu niesie gotowy słownik pod ``critical_effective["options"]``.
    """
    from app.services.must_gate_terms import gate_requirement
    from app.services.skill_normalize import canonical_of

    frozen = getattr(job, "critical_effective", None)
    if isinstance(frozen, dict) and isinstance(frozen.get("labels"), list):
        raw = frozen.get("options")
        if not isinstance(raw, dict):
            return {}
        return {
            str(label): tuple(str(w) for w in words)
            for label, words in raw.items()
            if isinstance(words, (list, tuple)) and words
        }
    resolution = effective_critical(job)
    if resolution.source != "dl":
        return {}
    rows = _row_words_by_label(job)
    out: dict[str, tuple[str, ...]] = {}
    for label in resolution.labels:
        words: list[str] = []
        for row_name, row_words in rows:
            if match_must_labels([row_name], [label]):
                words = row_words
                break
        requirement = gate_requirement(label)
        if requirement is None:
            out[label] = tuple(words) or (label,)
            continue
        known = {canonical_of(option) for option in requirement.options}
        extra = tuple(w for w in words if canonical_of(w.rstrip("*")) not in known)
        if extra:
            out[label] = extra
    return out


def gate_mode() -> str:
    """``critical`` (domyślnie) albo ``all`` — awaryjny powrót do bramki v8."""
    mode = str(getattr(settings, "MUST_GATE_MODE", "critical") or "critical").lower()
    return mode if mode in ("critical", "all") else "critical"


# ── Przeliczenie statystyk ───────────────────────────────────────────────


async def stats_are_stale(db, *, now: Optional[datetime] = None) -> bool:
    from sqlalchemy import select

    from app.models.app_setting import AppSetting

    value = (
        await db.execute(select(AppSetting.value).where(AppSetting.key == STATS_KEY))
    ).scalar_one_or_none()
    if not isinstance(value, dict) or value.get("version") != STATS_VERSION:
        return True
    try:
        computed = datetime.fromisoformat(str(value.get("computed_at")))
    except ValueError:
        return True
    if computed.tzinfo is None:
        computed = computed.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - computed >= RECOMPUTE_EVERY


async def compute_stats(db) -> dict:
    """Odsetek osób wysłanych do klienta, które mają daną pozycję must.

    Rekrutacje z co najmniej ``MIN_SENT_PER_JOB`` wysłanymi i must podanym
    wprost (kolumna albo stack Championa). Dowód jak w bramce v8: lista
    umiejętności, profil, CV i notatki-rozmowy sprzed otwarcia rekrutacji.
    Wynik: ``{"labels": {etykieta: {"rate", "jobs", "pairs"}}}`` — tylko
    liczby i nazwy technologii, bez osób. Tylko odczyt.
    """
    from sqlalchemy import select, text

    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.dealbreaker_filters import missing_must_skills
    from app.services.must_gate_terms import gate_requirement
    from app.services.must_text_evidence import (
        EVIDENCE_NOTE_TYPES,
        MustTextEvidence,
        evidence_note_text,
        text_met_labels,
    )
    from app.services.scoring_service import job_explicit_must_skills

    started = time.monotonic()
    rows = (
        await db.execute(
            text(
                "SELECT job_id, array_agg(DISTINCT candidate_id) FROM analytics_first_milestones "
                "WHERE job_id IS NOT NULL AND stage::text = ANY(:stages) "
                "GROUP BY job_id HAVING count(DISTINCT candidate_id) >= :min_sent"
            ),
            {"stages": list(_SENT_STAGES), "min_sent": MIN_SENT_PER_JOB},
        )
    ).all()
    sent_by_job = {int(job_id): list(ids) for job_id, ids in rows}
    coverage: dict[str, list[float]] = defaultdict(list)
    pairs: dict[str, int] = defaultdict(int)
    job_ids = sorted(sent_by_job)
    for start in range(0, len(job_ids), _JOB_BATCH):
        chunk = job_ids[start : start + _JOB_BATCH]
        jobs = (await db.execute(select(Job).where(Job.id.in_(chunk)))).scalars().all()
        work = []
        for job in jobs:
            must = [
                m
                for m in job_explicit_must_skills(job)
                if gate_requirement(m) is not None
            ]
            if must:
                work.append((job, must, sent_by_job[job.id]))
        if not work:
            continue
        need = sorted({c for _j, _m, sent in work for c in sent})
        candidates = {
            c.id: c
            for c in (
                await db.execute(select(Candidate).where(Candidate.id.in_(need)))
            ).scalars()
        }
        notes: dict[int, list[tuple[datetime, str]]] = defaultdict(list)
        for cid, at, content, kind in (
            await db.execute(
                text(
                    "SELECT candidate_id, created_at, content, kind FROM notes "
                    "WHERE candidate_id = ANY(:ids) AND source_deleted_at IS NULL "
                    "AND note_type::text = ANY(:types) "
                    f"AND {note_kinds.ai_readable_sql()}"
                ),
                {"ids": need, "types": list(EVIDENCE_NOTE_TYPES)},
            )
        ).all():
            notes[cid].append((at, evidence_note_text(kind, content)))
        for job, must, sent in work:
            cutoff = getattr(job, "opened_at", None) or getattr(job, "created_at", None)
            have: dict[str, int] = defaultdict(int)
            counted = 0
            for cid in sent:
                candidate = candidates.get(cid)
                if candidate is None:
                    continue
                note_texts = [
                    t for at, t in notes.get(cid, ()) if cutoff is None or at < cutoff
                ]
                candidate._must_text_evidence = MustTextEvidence(
                    key=tuple(must),
                    met=text_met_labels(candidate, must, note_texts),
                    has_notes=bool(note_texts),
                )
                missing = set(missing_must_skills(candidate, must))
                counted += 1
                for label in must:
                    if label not in missing:
                        have[label] += 1
            if not counted:
                continue
            for label in must:
                key = label.strip().lower()
                coverage[key].append(have[label] / counted)
                pairs[key] += counted
        db.expunge_all()
        await asyncio.sleep(0)
    labels = {
        key: {
            "rate": round(sum(values) / len(values), 4),
            "jobs": len(values),
            "pairs": pairs[key],
        }
        for key, values in sorted(coverage.items())
    }
    return {
        "version": STATS_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "jobs": len(job_ids),
        "seconds": round(time.monotonic() - started, 1),
        "labels": labels,
    }


async def recompute_and_store(db) -> dict:
    """Przelicz i zapisz statystyki (``app_settings``), odśwież pamięć procesu."""
    from sqlalchemy.dialects.postgresql import insert

    from app.models.app_setting import AppSetting

    payload = await compute_stats(db)
    await db.execute(
        insert(AppSetting)
        .values(key=STATS_KEY, value=payload)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": payload})
    )
    await db.commit()
    set_payload(payload)
    logger.info(
        "critical skills: stats recomputed (%d labels from %d jobs in %ss)",
        len(payload["labels"]),
        payload["jobs"],
        payload["seconds"],
    )
    return payload
