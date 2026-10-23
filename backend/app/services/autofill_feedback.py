"""Odrzucenie osoby od systemu z powodem (silnik „Nowi na 20”, 23.10.2026).

Decyzja Artura: kto wyrzuca osobę dodaną przez system, podaje powód, a z
powodów poprawiamy wyszukiwanie. Żeby nie wyciągać fałszywych wniosków,
każdy powód trafia do jednego z koszy raportu:

* ``search`` — błąd wyszukiwania (system miał dane i dobrał źle), np. brak
  kluczowej umiejętności, inny poziom, za droga przy ZNANEJ stawce powyżej
  budżetu;
* ``data`` — brak albo nieaktualność danych, np. za droga, gdy system stawki
  nie znał, nieaktualne CV;
* ``person`` — sprawa osoby (nie szuka, nie odbiera, już u nas w procesie);
* ``other`` — „Inne”, z opisem.

Kosz liczy się przy zapisie z migawki ``entry_meta`` procesu (co system
wiedział w chwili dodania), nie z dzisiejszego profilu. Reguła wymagania
powodu: ruch na „Odrzucony” osoby od systemu, która stoi w „Nowych” albo
„Screeningu” (dalej osoba ma już zwykłą historię procesu).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select

from app.models.autofill_feedback import AutofillFeedback
from app.models.job import Job
from app.models.recruitment_process import RecruitmentProcess
from app.services import candidate_claim
from app.services.autofill_feedback_schema import LEARNED_FROM, REASONS

REQUIRED_CODE = "AUTOFILL_REASON_REQUIRED"
_SEARCH = frozenset(
    {"missing_skill", "too_junior", "other_level_or_role", "location_mode", "language"}
)
_DATA = frozenset({"outdated_cv", "profile_mismatch"})
_PERSON = frozenset({"not_looking", "no_answer", "in_other_process"})
# Kolumny, w których decyzja o osobie od systemu jeszcze trwa.
DECISION_COLUMNS = candidate_claim.CLAIM_COLUMNS

REASON_LABELS: dict[str, str] = {
    "missing_skill": "Brak kluczowej umiejętności",
    "too_junior": "Za mało doświadczenia",
    "other_level_or_role": "Inny poziom lub inna rola",
    "location_mode": "Lokalizacja lub tryb pracy",
    "language": "Język",
    "too_expensive": "Za droga",
    "outdated_cv": "CV nieaktualne",
    "profile_mismatch": "Profil w bazie się nie zgadza",
    "not_looking": "Nie szuka pracy",
    "no_answer": "Nie odbiera (3 próby)",
    "in_other_process": "Już u nas w innym procesie",
    "other": "Inne",
}
assert set(REASON_LABELS) == set(REASONS)


def bucket_for(reason: str, *, snapshot: Any, budget_hourly: Optional[float]) -> str:
    """Kosz raportu z powodu i migawki tego, co system wiedział."""
    if reason in _SEARCH:
        return "search"
    if reason in _DATA:
        return "data"
    if reason in _PERSON:
        return "person"
    if reason == "too_expensive":
        known = (
            (snapshot or {}).get("rate_from_hourly")
            if isinstance(snapshot, dict)
            else None
        )
        if (
            isinstance(known, (int, float))
            and budget_hourly is not None
            and known > budget_hourly
        ):
            return "search"
        return "data"
    return "other"


async def system_process_in_decision(
    db, *, candidate_id: int, job_id: int, from_column: Optional[str]
) -> Optional[RecruitmentProcess]:
    """Proces osoby od systemu, o której decyzja jeszcze trwa — albo ``None``."""
    if from_column not in DECISION_COLUMNS:
        return None
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
    )
    if process is None or process.entry_source != candidate_claim.ENTRY_SYSTEM:
        return None
    return process


def validate(
    *,
    process: Optional[RecruitmentProcess],
    reason: Optional[str],
    learned_from: Optional[str],
    note: Optional[str],
) -> None:
    """422 przed zapisem ruchu: brak powodu przy osobie od systemu, powód przy
    innej osobie albo „Inne” bez opisu."""
    if process is None:
        if reason is not None or learned_from is not None:
            raise HTTPException(
                status_code=422,
                detail="Powód dla systemu podaje się tylko przy osobie od systemu.",
            )
        return
    if reason is None or learned_from is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": REQUIRED_CODE,
                "message": (
                    "Osobę od systemu odrzuca się z powodem: wybierz, dlaczego "
                    "odpada i skąd to wiesz. Powody uczą system."
                ),
            },
        )
    if reason not in REASONS or learned_from not in LEARNED_FROM:
        raise HTTPException(status_code=422, detail="Nieznany powód odrzucenia.")
    if reason == "other" and not (note or "").strip():
        raise HTTPException(status_code=422, detail="Przy „Inne” opisz powód.")


async def record(
    db,
    *,
    process: RecruitmentProcess,
    job: Job,
    stage_id: Optional[int],
    reason: str,
    learned_from: str,
    rate_hourly: Optional[Decimal],
    note: Optional[str],
    actor_id: Optional[int],
) -> AutofillFeedback:
    from app.services.dealbreaker_filters import resolve_job_budget_hourly

    snapshot = process.entry_meta if isinstance(process.entry_meta, dict) else None
    row = AutofillFeedback(
        job_id=process.job_id,
        candidate_id=process.candidate_id,
        stage_id=stage_id,
        reason=reason,
        learned_from=learned_from,
        bucket=bucket_for(
            reason, snapshot=snapshot, budget_hourly=resolve_job_budget_hourly(job)
        ),
        rate_hourly=rate_hourly,
        note=(note or "").strip()[:500] or None,
        snapshot=snapshot,
        created_by=actor_id,
    )
    db.add(row)
    return row
