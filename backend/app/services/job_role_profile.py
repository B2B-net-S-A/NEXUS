"""Profil „Kogo szukamy” rekrutacji i lista „Nie proponujemy” (16.11.2026).

Pomiar na 1 948 decyzjach porcji (15.10–16.11): „Inna rola” to 28% odrzuceń
16.11, szczegół kliknięto przy 15 z 68, a 37% decyzji jest w rekrutacjach,
których tytułu ``role_family.family_of`` nie rozpoznaje, więc filtr roli nic
tam nie robi. Tytuł osoby nie rozstrzyga (ta sama rola dostaje „Pasuje” i „Inna
rola”), a reguły z samych tytułów dały +0,5 pkt — stąd profil, który zespół
poprawia sam, i lista ról, których w tej rekrutacji nie proponujemy.

* Profil bez zapisu liczy się z tytułu (``family_of`` → ``LABELS``), poziom
  „lider” przy lead/head/manager/kierownik/architect, technologia z pierwszej
  krytycznej profilu Championa.
* „Nie proponujemy” = wpisy ręczne (działają od razu) i etykiety „Osoba to: X”
  z odrzuceń „Inna rola” (``autofill_feedback.detail.person_role``): od
  ``EXCLUDE_MIN`` takich samych (casefold) w jednej rekrutacji — chyba że
  w tej rekrutacji osoba z takim stanowiskiem przeszła dalej niż „Nowi”
  (bezpiecznik: ten sam tytuł bywa przyjmowany i odrzucany).
* Silnik „Nowych” (``new_column_autofill._allowed``) nie dokłada osoby, której
  obecne stanowisko (``role_family.current_position``) zawiera taką etykietę
  całymi słowami. Karty, które już stoją, zostają.

Reguła: ``docs/claude/rekrutacja-tablica/porcja-kogo-szukamy.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import select

from app.services.job_role_profile_schema import LEVELS

EXCLUDE_MIN = 3
TEXT_MAX = 120
MAX_EXCLUDED = 20
DEFAULT_LEVEL = "dowolny"
_LEAD_TITLE = re.compile(
    r"\b(?:lead\w*|head|manager|kierownik\w*|architect\w*|architekt\w*)\b",
    re.IGNORECASE,
)


def label_key(label: Optional[str]) -> str:
    """Klucz porównania etykiety: bez nadmiarowych spacji, casefold."""
    return " ".join(str(label or "").split()).casefold()


def _clean_text(value: Any) -> Optional[str]:
    text = " ".join(str(value or "").split())[:TEXT_MAX]
    return text or None


def default_level(title: Optional[str]) -> str:
    return "lider" if title and _LEAD_TITLE.search(title) else DEFAULT_LEVEL


def default_profile(job) -> dict:
    """Profil bez zapisu: rola z tytułu, poziom z tytułu, technologia z krytycznych."""
    from app.services.critical_skills import stored_critical
    from app.services.role_family import LABELS, family_of

    title = getattr(job, "title", None)
    family = family_of(title)
    critical = [c.strip() for c in (stored_critical(job) or []) if c.strip()]
    return {
        "role": LABELS[family] if family else None,
        "specialty": None,
        "technology": critical[0] if critical else None,
        "level": default_level(title),
    }


@dataclass(frozen=True)
class Learned:
    label: str
    count: int


def learned_from_details(details: Iterable[Any]) -> dict[str, Learned]:
    """``{klucz: Learned}`` z ``detail`` odrzuceń „Inna rola” jednej rekrutacji.
    Wyświetlana etykieta = pierwsza pisownia."""
    out: dict[str, Learned] = {}
    for detail in details:
        if not isinstance(detail, dict):
            continue
        label = _clean_text(detail.get("person_role"))
        if not label:
            continue
        key = label_key(label)
        found = out.get(key)
        out[key] = Learned(
            found.label if found else label, (found.count if found else 0) + 1
        )
    return out


def build_profile(
    job,
    row,
    learned: dict[str, Learned],
    accepted_positions: Sequence[Optional[str]] = (),
) -> dict:
    """Profil do API i filtra: zapisany wiersz albo wartości domyślne, plus lista."""
    saved = row is not None
    base = (
        {
            "role": row.role,
            "specialty": row.specialty,
            "technology": row.technology,
            "level": row.level if row.level in LEVELS else DEFAULT_LEVEL,
        }
        if saved
        else default_profile(job)
    )
    manual = [m for m in ((row.excluded if saved else None) or []) if label_key(m)]
    dismissed = {label_key(d) for d in ((row.dismissed if saved else None) or [])}
    excluded: list[dict] = []
    seen: set[str] = set()
    for label in manual:
        key = label_key(label)
        if key in seen:
            continue
        seen.add(key)
        hit = learned.get(key)
        excluded.append(
            {"label": label, "count": hit.count if hit else 0, "source": "manual"}
        )
    learning: list[dict] = []
    for key, hit in sorted(learned.items(), key=lambda kv: (-kv[1].count, kv[0])):
        if key in seen:
            continue
        accepted = hit.count >= EXCLUDE_MIN and any(
            names_role(p, key) for p in accepted_positions
        )
        if hit.count >= EXCLUDE_MIN and key not in dismissed and not accepted:
            excluded.append(
                {"label": hit.label, "count": hit.count, "source": "rejections"}
            )
        else:
            entry = {
                "label": hit.label,
                "count": hit.count,
                "dismissed": key in dismissed,
            }
            if accepted:
                entry["accepted"] = True
            learning.append(entry)
    return {
        "job_id": job.id,
        **base,
        "saved": saved,
        "excluded": excluded,
        "learning": learning,
        "exclude_min": EXCLUDE_MIN,
    }


async def _learned_for_jobs(
    db, job_ids: Sequence[int]
) -> dict[int, dict[str, Learned]]:
    from app.models.autofill_feedback import AutofillFeedback
    from app.services.autofill_feedback import ROLE_REASON

    by_job: dict[int, list[Any]] = {}
    for job_id, detail in (
        await db.execute(
            select(AutofillFeedback.job_id, AutofillFeedback.detail).where(
                AutofillFeedback.job_id.in_(list(job_ids)),
                AutofillFeedback.reason == ROLE_REASON,
                AutofillFeedback.detail.has_key("person_role"),
            )
        )
    ).all():
        by_job.setdefault(job_id, []).append(detail)
    return {job_id: learned_from_details(rows) for job_id, rows in by_job.items()}


async def profiles_for_jobs(db, jobs: Iterable[Any]) -> dict[int, dict]:
    """Profile rekrutacji hurtowo: dwa zapytania na całą kolejkę."""
    from app.models.job_role_profile import JobRoleProfile

    by_id = {job.id: job for job in jobs}
    if not by_id:
        return {}
    ids = sorted(by_id)
    rows = {
        row.job_id: row
        for row in (
            await db.scalars(
                select(JobRoleProfile).where(JobRoleProfile.job_id.in_(ids))
            )
        ).all()
    }
    learned = await _learned_for_jobs(db, ids)
    accepted = await _accepted_positions(
        db,
        [
            job_id
            for job_id, hits in learned.items()
            if any(hit.count >= EXCLUDE_MIN for hit in hits.values())
        ],
    )
    return {
        job_id: build_profile(
            job, rows.get(job_id), learned.get(job_id, {}), accepted.get(job_id, ())
        )
        for job_id, job in by_id.items()
    }


# Etapy „dalej niż Nowi”, czyli osoba, którą zespół w tej rekrutacji przyjął.
_ACCEPTED_STAGES = (
    "prep_call",
    "screening",
    "verified",
    "interview",
    "cv_sent",
    "client_interview",
    "acceptance",
    "negotiation",
    "onboarding",
    "hired",
)


async def _accepted_positions(db, job_ids: Sequence[int]) -> dict[int, list[str]]:
    """Obecne stanowiska osób, które w rekrutacji przeszły dalej niż „Nowi”."""
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.role_family import current_position

    if not job_ids:
        return {}
    pairs = (
        await db.execute(
            select(CandidateStage.job_id, CandidateStage.candidate_id)
            .where(
                CandidateStage.job_id.in_(list(job_ids)),
                CandidateStage.stage.in_([PipelineStage(v) for v in _ACCEPTED_STAGES]),
            )
            .distinct()
        )
    ).all()
    if not pairs:
        return {}
    people = {
        row.id: current_position(row)
        for row in (
            await db.execute(
                select(
                    Candidate.id,
                    Candidate.cv_extracted_data,
                    Candidate.linkedin_current_title,
                    Candidate.linkedin_current_company,
                    Candidate.experience,
                ).where(Candidate.id.in_({c for _, c in pairs}))
            )
        ).all()
    }
    out: dict[int, list[str]] = {}
    for job_id, candidate_id in pairs:
        position = people.get(candidate_id)
        if position:
            out.setdefault(job_id, []).append(position)
    return out


def names_role(position: Optional[str], key: str) -> bool:
    """Czy stanowisko zawiera etykietę całymi słowami (casefold)."""
    if not position or not key:
        return False
    return re.search(rf"(?<!\w){re.escape(key)}(?!\w)", label_key(position)) is not None


def excluded_keys(profile: dict) -> list[str]:
    return [
        label_key(e["label"])
        for e in profile.get("excluded") or []
        if label_key(e["label"])
    ]


async def keep_role_allowed(db, job, candidates: list[Any]) -> set[int]:
    """Id osób, których obecne stanowisko nie jest na liście „Nie proponujemy”."""
    from app.services.role_family import current_position

    ids = {c.id for c in candidates}
    if not ids:
        return ids
    profile = (await profiles_for_jobs(db, [job])).get(job.id) or {}
    keys = excluded_keys(profile)
    if not keys:
        return ids
    return {
        c.id
        for c in candidates
        if not any(names_role(current_position(c), key) for key in keys)
    }


def clean_payload(raw: dict) -> dict:
    """Pola z ``PUT``: teksty przycięte, poziom z listy, lista bez powtórzeń."""
    level = raw.get("level") or DEFAULT_LEVEL
    if level not in LEVELS:
        raise HTTPException(status_code=422, detail="Nieznany poziom roli.")
    excluded: list[str] = []
    seen: set[str] = set()
    for item in raw.get("excluded") or []:
        label = _clean_text(item)
        if not label or label_key(label) in seen:
            continue
        seen.add(label_key(label))
        excluded.append(label)
    if len(excluded) > MAX_EXCLUDED:
        raise HTTPException(
            status_code=422,
            detail=f"„Nie proponujemy” ma najwyżej {MAX_EXCLUDED} pozycji.",
        )
    return {
        "role": _clean_text(raw.get("role")),
        "specialty": _clean_text(raw.get("specialty")),
        "technology": _clean_text(raw.get("technology")),
        "level": level,
        "excluded": excluded,
    }


async def save_profile(db, job, raw: dict, *, user_id: Optional[int]) -> dict:
    """Zapis „Popraw”. ``excluded`` z ekranu = cała lista, jaką ma być: etykieta
    z odrzuceń, która została, dalej liczy się „z odrzuceń”; zdjęta trafia do
    ``dismissed``; reszta to wpisy ręczne."""
    from datetime import datetime, timezone

    from app.models.job_role_profile import JobRoleProfile

    data = clean_payload(raw)
    learned = (await _learned_for_jobs(db, [job.id])).get(job.id, {})
    row = await db.get(JobRoleProfile, job.id)
    learned_on = {key for key, hit in learned.items() if hit.count >= EXCLUDE_MIN}
    wanted = {label_key(label) for label in data["excluded"]}
    before = {label_key(d) for d in ((row.dismissed if row else None) or [])}
    if row is None:
        row = JobRoleProfile(job_id=job.id)
        db.add(row)
    row.role = data["role"]
    row.specialty = data["specialty"]
    row.technology = data["technology"]
    row.level = data["level"]
    row.excluded = [
        label for label in data["excluded"] if label_key(label) not in learned_on
    ]
    row.dismissed = sorted((learned_on | before) - wanted)
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return build_profile(job, row, learned)
