"""„Kluczowe w tej rekrutacji” na karcie porcji dnia (R2 + R4, 12.11.2026).

Raport z 323 odrzuceń porcji z 09–12.11 i makiety:
https://claude.ai/artifact/PqmctW9taWS8mXwmGfrFSM. Reguła:
``docs/claude/rekrutacja-tablica/porcja-kluczowe-dowod-i-polski.md``.

Karta zamiast dziesięciu „?” pokazuje krytyczne rekrutacji z poziomem dowodu
i polski:

* **dowód krytycznej** — ``experience``: oś technologii z odczytu CV
  (``candidate_skill_usage.months``) ma przy niej miesiące stanowisk albo
  projektów; ``mention``: jest w CV albo na liście umiejętności, bez dat;
  ``none``: nigdzie. Dowód tylko informuje: od 15.10 wzmianka wysyłała do
  klienta tak samo dobrze jak doświadczenie (10,8% wobec 10,7% na 1 720 kartach),
  więc nikt przez to nie wypada z porcji (decyzja Artura 12.11.2026);
* **polski** — ojczysty z profilu, z CV po polsku albo z polskiego imienia
  i nazwiska; poziom z profilu; „nie zna” tylko po odrzuceniu „Brak polskiego”.
  Imię i nazwisko wyłącznie podnosi status: nigdy nie oznacza braku polskiego,
  bo wtedy decydowałoby pochodzenie, a nie język.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import func, select

POLISH_CODES = ("pl", "pol")
NO_POLISH_REASON = "no_polish"

_POLISH_LETTERS = re.compile(r"[ąćęłńóśźż]", re.IGNORECASE)
# Końcówki nazwisk; tylko podnoszą status, więc lista może być szeroka.
_POLISH_SURNAME_ENDINGS = (
    "ski",
    "ska",
    "cki",
    "cka",
    "dzki",
    "dzka",
    "wicz",
    "czyk",
    "czak",
    "iak",
    "ak",
    "ek",
)
# Rekrutacja, która wprost mówi, że polski nie jest potrzebny. Bez kotwic
# i ``\m``: ten sam wzorzec idzie do Postgresa (``~*``) w silniku „Nowych”.
NO_POLISH_NEEDED_RE = (
    r"english only|only english|bez polskiego|bez j[eę]zyka polskiego"
    r"|polski nie|polish not|no polish|not polish|nie wymaga polskiego"
    r"|polski niewymagany|niewymagany polski"
)
_NO_POLISH_NEEDED = re.compile(NO_POLISH_NEEDED_RE, re.IGNORECASE)


def polish_name(name: Optional[str], lastname: Optional[str]) -> bool:
    """Imię albo nazwisko z polską literą, albo nazwisko z polską końcówką."""
    full = f"{name or ''} {lastname or ''}"
    if _POLISH_LETTERS.search(full):
        return True
    last = (lastname or "").strip().lower()
    return bool(last) and last.endswith(_POLISH_SURNAME_ENDINGS)


def polish_status(
    *,
    native: bool,
    level: Optional[str],
    cv_polish: bool,
    name_polish: bool,
    refused_at: Optional[str],
) -> dict[str, str]:
    """Stan polskiego na karcie: ``native`` / ``level`` / ``no`` / ``unknown``.

    Profil wygrywa ze wszystkim; odrzucenie „Brak polskiego” wygrywa z CV
    i z imieniem i nazwiskiem."""
    if native:
        return {"state": "native", "detail": "ojczysty w profilu"}
    if level:
        return {"state": "level", "detail": f"{level} w profilu"}
    if refused_at:
        return {"state": "no", "detail": f"odrzucona za brak polskiego {refused_at}"}
    if cv_polish:
        return {"state": "native", "detail": "ojczysty: CV po polsku"}
    if name_polish:
        return {"state": "native", "detail": "ojczysty: polskie imię i nazwisko"}
    return {"state": "unknown", "detail": "brak danych — sprawdź"}


def evidence_state(*, months: Optional[int], text_hit: bool, skill_hit: bool) -> str:
    if months and months > 0:
        return "experience"
    if text_hit or skill_hit:
        return "mention"
    return "none"


def _years_months(months: int) -> str:
    years, rest = divmod(months, 12)
    parts = []
    if years:
        word = (
            "rok"
            if years == 1
            else (
                "lata"
                if 2 <= years % 10 <= 4 and not 12 <= years % 100 <= 14
                else "lat"
            )
        )
        parts.append(f"{years} {word}")
    if rest:
        parts.append(f"{rest} mies.")
    return " ".join(parts)


def evidence_detail(state: str, months: Optional[int]) -> str:
    if state == "experience" and months:
        return f"{_years_months(months)} w stanowiskach"
    if state == "mention":
        return "w CV albo umiejętnościach, bez dat"
    return "brak w CV i profilu"


def job_needs_polish(language: Optional[str]) -> bool:
    """Polski jest potrzebny, chyba że rekrutacja wprost mówi inaczej. Pole
    języka w profilu rekrutacji często pomija polski przy polskich bankach
    (12.11.2026: 39 z ok. 90 rekrutacji bez pola, reszta zwykle „Angielski”)."""
    return not _NO_POLISH_NEEDED.search(language or "")


def job_language(job) -> Optional[str]:
    profile = getattr(job, "champion_profile", None)
    basics = profile.get("basics") if isinstance(profile, dict) else None
    value = basics.get("language") if isinstance(basics, dict) else None
    return value if isinstance(value, str) else None


def _text_hit(text: str, variants: Iterable[str]) -> bool:
    for variant in variants:
        if not variant:
            continue
        if re.search(rf"(?<![\w+#.]){re.escape(variant)}(?![\w+#])", text):
            return True
    return False


async def evidence_for(
    db, candidates: Iterable[Any], labels: Iterable[str]
) -> dict[tuple[int, str], tuple[str, int]]:
    """``{(candidate_id, label): (stan, miesiące)}`` — dowód pozycji u osób.

    Jedno zapytanie o oś technologii; reszta z CV i listy umiejętności osoby.
    Wspólne dla karty porcji i reguły rekrutacji (``job_learned_rules``)."""
    from app.models.candidate_skill_usage import CandidateSkillUsage
    from app.services.scoring_service import (
        candidate_skill_names,
        skill_name_variants,
        skill_present,
    )

    people = {c.id: c for c in candidates}
    variants = {
        label: [v for v in skill_name_variants([label]) if v] or [label.casefold()]
        for label in {lb.strip() for lb in labels if lb and lb.strip()}
    }
    if not people or not variants:
        return {}
    keys = sorted({key for family in variants.values() for key in family})
    rows = (
        await db.execute(
            select(
                CandidateSkillUsage.candidate_id,
                CandidateSkillUsage.skill_canonical,
                func.max(CandidateSkillUsage.months),
            )
            .where(
                CandidateSkillUsage.candidate_id.in_(sorted(people)),
                CandidateSkillUsage.skill_canonical.in_(keys),
                CandidateSkillUsage.months > 0,
            )
            .group_by(
                CandidateSkillUsage.candidate_id,
                CandidateSkillUsage.skill_canonical,
            )
        )
    ).all()
    usage = {(cid, key): int(months) for cid, key, months in rows}
    out: dict[tuple[int, str], tuple[str, int]] = {}
    for cid, candidate in people.items():
        text = (getattr(candidate, "raw_cv_text", None) or "").casefold()
        skills = candidate_skill_names(candidate)
        for label, family in variants.items():
            months = max((usage.get((cid, key), 0) for key in family), default=0)
            state = evidence_state(
                months=months,
                text_hit=_text_hit(text, family),
                skill_hit=skill_present(label, skills),
            )
            out[(cid, label)] = (state, months)
    return out


async def key_facts_for(db, cards: list[tuple[int, Any, Any]]) -> dict[int, dict]:
    """``{process_id: {"critical": [...], "polish": {...}}}`` dla kart porcji.

    ``cards`` = ``(process_id, job, candidate)``. Trzy zapytania na całą
    kolejkę: oś technologii, języki i odrzucenia „Brak polskiego”."""
    from app.models.autofill_feedback import AutofillFeedback
    from app.models.candidate_language import CandidateLanguage
    from app.services.critical_skills import stored_critical

    if not cards:
        return {}
    candidate_ids = sorted({c.id for _, _, c in cards})
    labels_by_job: dict[int, list[str]] = {}
    for _, job, _ in cards:
        if job.id not in labels_by_job:
            labels_by_job[job.id] = [
                label.strip() for label in (stored_critical(job) or []) if label.strip()
            ]
    evidence = await evidence_for(
        db,
        {c.id: c for _, _, c in cards}.values(),
        [label for labels in labels_by_job.values() for label in labels],
    )

    polish_rows = (
        await db.execute(
            select(
                CandidateLanguage.candidate_id,
                CandidateLanguage.is_native,
                CandidateLanguage.cefr_level,
            ).where(
                CandidateLanguage.candidate_id.in_(candidate_ids),
                func.lower(CandidateLanguage.language_code).in_(POLISH_CODES),
            )
        )
    ).all()
    polish_profile: dict[int, tuple[bool, Optional[str]]] = {}
    for cid, native, level in polish_rows:
        was_native, was_level = polish_profile.get(cid, (False, None))
        polish_profile[cid] = (was_native or bool(native), was_level or level)

    refused: dict[int, date] = {
        cid: when.date() if hasattr(when, "date") else when
        for cid, when in (
            await db.execute(
                select(
                    AutofillFeedback.candidate_id, func.max(AutofillFeedback.created_at)
                )
                .where(
                    AutofillFeedback.candidate_id.in_(candidate_ids),
                    AutofillFeedback.reason == NO_POLISH_REASON,
                )
                .group_by(AutofillFeedback.candidate_id)
            )
        ).all()
    }

    out: dict[int, dict] = {}
    for process_id, job, candidate in cards:
        critical = []
        for label in labels_by_job.get(job.id, []):
            state, months = evidence.get((candidate.id, label), ("none", 0))
            critical.append(
                {
                    "label": label,
                    "state": state,
                    "detail": evidence_detail(state, months),
                }
            )
        native, level = polish_profile.get(candidate.id, (False, None))
        when = refused.get(candidate.id)
        out[process_id] = {
            "critical": critical,
            "polish": polish_status(
                native=native,
                level=level,
                cv_polish=(getattr(candidate, "cv_language", None) or "").lower()
                in POLISH_CODES,
                name_polish=polish_name(
                    candidate.name, getattr(candidate, "lastname", None)
                ),
                refused_at=when.isoformat() if when else None,
            ),
        }
    return out
