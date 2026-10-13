"""„Wymagania do poprawy” — porządki wymagań otwartych rekrutacji (D4, 13.10.2026).

Pomiar na produkcji 13.10.2026: w 34 otwartych rekrutacjach silnik czytał
kolumnę must z prozą z requestu zamiast czystych słów Championa, w wielu
must stały zdania („doświadczenie w przetargach”), technologia z komentarzem
w nawiasie wypadała z bramki, a krytyczne frazy spoza słownika ukrywały
prawie wszystkich. Decyzja Artura (wariant A): każda otwarta rekrutacja
dostaje propozycję uporządkowania, a Delivery Lead ją zatwierdza albo odrzuca.

Propozycji nie zapisujemy — ``build_proposal`` liczy ją na żywo z rekrutacji
(czysta funkcja, bez bazy). Tabela ``requirement_cleanup_decisions`` trzyma
tylko decyzję i odcisk profilu: odrzucona propozycja wraca dopiero, gdy profil
się zmieni.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_ROWS = 100

REASON_TEXT = {
    "prose_column": "AI czyta wymagania z requestu zapisane zdaniami, a nie słowa z Championa",
    "paren": "komentarz w nawiasie wyłącza technologię z wyszukiwania",
    "prose_rows": "zdania w wymaganiach — wyszukiwanie ich nie znajdzie",
    "critical_not_searchable": "krytyczne, których wyszukiwanie nie sprawdzi, ukrywają prawie wszystkich",
    "no_search_words": "brak słów do szukania — propozycje AI się nie pojawią",
}


@dataclass(frozen=True)
class CleanupProposal:
    job_id: int
    reasons: tuple[str, ...]
    before: dict
    after: dict
    profile_hash: str
    contract_reviewed: bool

    @property
    def can_apply(self) -> bool:
        return "no_search_words" not in self.reasons

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "reasons": [
                {"code": code, "text": REASON_TEXT[code]} for code in self.reasons
            ],
            "before": self.before,
            "after": {
                k: v
                for k, v in self.after.items()
                if k not in ("experience", "basics", "notes")
            },
            "profile_hash": self.profile_hash,
            "contract_reviewed": self.contract_reviewed,
            "can_apply": self.can_apply,
        }


def _names(items: Any) -> list[str]:
    out: list[str] = []
    for item in items or []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            out.append(" ".join(name.split()))
    return out


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())


def build_proposal(job: Any) -> Optional[CleanupProposal]:
    """Propozycja dla rekrutacji albo ``None``, gdy nie ma czego porządkować."""
    from app.services import champion_view
    from app.services.champion_intake import profile_hash
    from app.services.champion_requirement_rows import (
        _merge_talk,
        _row_words,
        clean_rows,
        overflow_note,
        profile_has_rows,
        row_label,
        rows_from_legacy,
        separate_talk_items,
        split_rows,
    )
    from app.services.skill_normalize import canonical_of, strip_version
    from app.services.critical_skills import effective_critical
    from app.services.must_gate_terms import gate_requirement
    from app.services.requirement_phrase import read_phrase
    from app.services.scoring_service import (
        canonical_skill_names,
        job_explicit_must_skills,
    )

    raw = getattr(job, "champion_profile", None)
    profile: dict = raw if isinstance(raw, dict) else {}
    stack = champion_view.stack(profile)
    stored_critical = stack.get("critical")
    reasons: list[str] = []
    descriptive: list[str] = []
    engine_must = list(job_explicit_must_skills(job))

    if profile_has_rows(profile):
        chosen = {_fold(c) for c in stored_critical or [] if isinstance(c, str)}
        rows = [
            {
                "words": list(r["words"]),
                "level": "critical"
                if _fold(row_label(r["words"])) in chosen
                else r["level"],
            }
            for r in clean_rows(stack.get("rows"))
        ]
    else:
        champion_must = _names(stack.get("must"))
        champion_nice = _names(stack.get("nice"))
        column_must = _names(getattr(job, "must_skills", None))
        column_nice = _names(getattr(job, "nice_skills", None))
        must = champion_must or column_must
        nice = champion_nice or column_nice
        if champion_must and {_fold(m) for m in engine_must} != {
            _fold(m) for m in canonical_skill_names(champion_must)
        }:
            reasons.append("prose_column")
            # Pozycje tylko z kolumny też przechodzą przez czytanie — nic nie
            # znika po cichu (zdanie trafi do rozmowy, technologia do wierszy).
            known = {_fold(m) for m in champion_must}
            must = [*must, *(m for m in column_must if _fold(m) not in known)]
        search = champion_view.search(profile)
        legacy = rows_from_legacy(
            must=must,
            nice=nice,
            requirements=[
                list(row)
                for row in search.get("requirements") or []
                if isinstance(row, list)
            ],
            critical=stored_critical if isinstance(stored_critical, list) else None,
            clip=False,
        )
        rows = legacy["rows"]
        descriptive = list(legacy["descriptive"])

    # Komentarz w nawiasie i zdania w wierszach — ta sama reguła co zapis.
    for row in rows:
        for word in row["words"]:
            reading = read_phrase(word)
            if reading.keyword and reading.comment and reading.keyword != word:
                if "paren" not in reasons:
                    reasons.append("paren")

    experience = champion_view.experience(profile)
    language = champion_view.basics(profile).get("language")
    patch, _notices = separate_talk_items(
        {"stack": {"rows": rows}},
        previous_experience=experience,
        previous_language=language,
    )
    # Limity wierszy liczone PO przeniesieniu zdań do rozmowy; co i tak się
    # nie mieści, idzie do opisu wymagań jak przy zapisie (`expand_patch`).
    clipped, overflow = split_rows(patch["stack"]["rows"])
    rows = [dict(r) for r in clipped]
    talk_overflow: list[str] = []

    def _keys(words: list[str]) -> set[str]:
        return {canonical_of(strip_version(w.rstrip("*"))[0]) for w in words}

    row_keys = set().union(*(_keys(r["words"]) for r in rows)) if rows else set()
    overflow_keys = _keys(overflow)

    def _in_rows(text: str) -> bool:
        requirement = gate_requirement(text)
        words = list(requirement.options) if requirement else _row_words([text])
        return bool(_keys(words) & (row_keys | overflow_keys))

    new_experience = {
        key: [dict(i) for i in value] if isinstance(value, list) else value
        for key, value in (patch.get("experience") or experience).items()
    }
    new_language = (patch.get("basics") or {}).get("language", language)
    # Zdania odłożone przez `rows_from_legacy` — język do pola „Język”, reszta
    # do sekcji 4 (tak samo jak przy zapisie wiersza).
    for sentence in descriptive:
        reading = read_phrase(sentence)
        if reading.keyword and not reading.needs_decision and _in_rows(reading.keyword):
            # Technologia w innej pisowni („ETL/ELT”, „Java 17+”) — jej słowa są
            # już wierszem; do rozmowy idzie tylko poziom z komentarza.
            if reading.talk_text and not _merge_talk(
                new_experience.setdefault("skills", []), reading.talk_text, "must"
            ):
                talk_overflow.append(reading.talk_text)
            continue
        if reading.talk == "language":
            parts = [p for p in [str(new_language or "").strip()] if p]
            if _fold(sentence) not in _fold(", ".join(parts)):
                new_language = ", ".join([*parts, sentence])
            continue
        kind = reading.talk if reading.talk in ("skills", "domains") else "skills"
        talk_text = reading.talk_text or sentence[:160].rstrip()
        if not _merge_talk(new_experience.setdefault(kind, []), talk_text, "must"):
            talk_overflow.append(talk_text)

    # Co nie zmieściło się w wierszach ani na liście do rozmowy, zostaje
    # w opisie wymagań — czyta go rekruter i generator CV; nic nie znika.
    notes: Optional[str] = None
    if overflow or talk_overflow:
        parts = [str(stack.get("notes") or "").strip()]
        if overflow:
            parts.append(overflow_note(overflow))
        if talk_overflow:
            parts.append("Do sprawdzenia w rozmowie: " + "; ".join(talk_overflow) + ".")
        notes = "\n".join(part for part in parts if part)

    # Krytyczne spoza bramki („architektura chmury”) schodzą do „musi mieć”.
    for row in rows:
        if row.get("level") == "critical" and (
            gate_requirement(row_label(row["words"])) is None
        ):
            row["level"] = "must"
            if "critical_not_searchable" not in reasons:
                reasons.append("critical_not_searchable")

    added_talk = [
        {"name": item["name"], "kind": kind, "level": item.get("level", "must")}
        for kind in ("skills", "domains")
        for item in new_experience.get(kind) or []
        if _fold(item["name"])
        not in {_fold(i.get("name", "")) for i in experience.get(kind) or []}
    ]
    if added_talk or (new_language or None) != (language or None):
        reasons.append("prose_rows")
    required = [r for r in rows if r.get("level") != "nice"]
    if not required:
        reasons.append("no_search_words")
    if not reasons:
        return None

    critical_rows = [
        row_label(r["words"]) for r in rows if r.get("level") == "critical"
    ]
    # Lista zapisana przez DL to decyzja: gdy żadna krytyczna nie zostaje,
    # zostaje „Brak krytycznych” (`[]`), nie „brak decyzji” (`None`) — inaczej
    # zapis dokłada blokadę `critical` i kończy się 422 `handoff_regression`.
    critical: Optional[list[str]] = (
        critical_rows
        if critical_rows
        else ([] if isinstance(stored_critical, list) else None)
    )
    resolution = effective_critical(job)
    contract = getattr(job, "matching_requirements", None)
    return CleanupProposal(
        job_id=getattr(job, "id", 0) or 0,
        reasons=tuple(reasons),
        before={
            # Pisownia jak na ekranie: kolumna, gdy silnik ją czyta, inaczej Champion.
            "must": _names(getattr(job, "must_skills", None))
            or _names(stack.get("must")),
            "critical": list(resolution.labels),
            "language": language or None,
        },
        after={
            "rows": [
                {"words": list(r["words"]), "level": r.get("level", "must")}
                for r in rows
            ],
            "critical": critical,
            "talk": added_talk,
            "language": new_language or None,
            "overflow": list(overflow),
            "notes": notes,
            "experience": new_experience,
        },
        profile_hash=profile_hash(job),
        contract_reviewed=bool(isinstance(contract, dict) and contract.get("reviewed")),
    )


def apply_payload(proposal: CleanupProposal) -> dict:
    """Ładunek zapisu Championa realizujący propozycję (``save_champion_core``)."""
    after = proposal.after
    payload: dict = {
        "stack": {"rows": after["rows"], "critical": after["critical"]},
        "experience": after["experience"],
    }
    if after.get("notes") is not None:
        payload["stack"]["notes"] = after["notes"]
    if after["language"] != proposal.before["language"]:
        payload["basics"] = {"language": after["language"]}
    return payload


def can_decide(user: Any, job: Any) -> bool:
    """Admin i Head of Recruitment — każda rekrutacja; Delivery Lead — swoja."""
    from app.models.user import UserRole

    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return True
    return user.has_role(UserRole.delivery_lead) and user.id in (
        getattr(job, "delivery_lead_id", None),
        getattr(job, "created_by", None),
    )


async def _decided(db: AsyncSession, job_ids: list[int]) -> dict[int, str]:
    from app.models.requirement_cleanup import RequirementCleanupDecision

    if not job_ids:
        return {}
    rows = await db.execute(
        select(
            RequirementCleanupDecision.job_id, RequirementCleanupDecision.profile_hash
        ).where(RequirementCleanupDecision.job_id.in_(job_ids))
    )
    return {job_id: digest for job_id, digest in rows.all()}


async def pending_proposal(db: AsyncSession, job: Any) -> Optional[CleanupProposal]:
    """Propozycja tej rekrutacji, o ile nikt nie zdecydował o tym profilu."""
    proposal = build_proposal(job)
    if proposal is None:
        return None
    decided = await _decided(db, [job.id])
    return None if decided.get(job.id) == proposal.profile_hash else proposal


async def load_fixes(db: AsyncSession, user: Any) -> list[dict]:
    """Lista „Wymagania do poprawy” dla pulpitu tej osoby."""
    from app.models.job import Job, JobStatus
    from app.models.user import UserRole
    from app.services.job_working_title import display_title

    sees_all = user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)
    if not sees_all and not user.has_role(UserRole.delivery_lead):
        return []
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.published, Job.is_open.is_(True))
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    if not sees_all:
        stmt = stmt.where(
            (Job.delivery_lead_id == user.id) | (Job.created_by == user.id)
        )
    jobs = (await db.scalars(stmt)).all()
    proposals = [(job, build_proposal(job)) for job in jobs]
    proposals = [(job, p) for job, p in proposals if p is not None]
    decided = await _decided(db, [job.id for job, _ in proposals])
    out: list[dict] = []
    for job, proposal in proposals:
        if decided.get(job.id) == proposal.profile_hash:
            continue
        out.append(
            {
                "job_id": job.id,
                "title": display_title(job),
                "reasons": proposal.as_dict()["reasons"],
                "can_apply": proposal.can_apply,
                "rows": len(proposal.after["rows"]),
                "talk": len(proposal.after["talk"]),
            }
        )
        if len(out) >= MAX_ROWS:
            break
    return out


async def load_fixes_safely(db: AsyncSession, user: Any) -> list[dict]:
    try:
        async with db.begin_nested():
            return await load_fixes(db, user)
    except Exception:  # noqa: BLE001 — pulpit działa bez tej listy
        logger.exception("requirement_cleanup: nie udało się policzyć listy")
        return []


async def record_decision(
    db: AsyncSession, *, job_id: int, profile_hash: str, status: str, user_id: int
) -> None:
    from sqlalchemy.dialects.postgresql import insert

    from app.models.requirement_cleanup import RequirementCleanupDecision

    stmt = insert(RequirementCleanupDecision).values(
        job_id=job_id, profile_hash=profile_hash, status=status, decided_by=user_id
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[RequirementCleanupDecision.job_id],
            set_={
                "profile_hash": stmt.excluded.profile_hash,
                "status": stmt.excluded.status,
                "decided_by": stmt.excluded.decided_by,
                "decided_at": stmt.excluded.decided_at,
            },
        )
    )
