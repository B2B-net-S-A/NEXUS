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

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select

from app.core.scheduling import business_today
from app.models.autofill_feedback import AutofillFeedback
from app.models.candidate import AvailabilityStatus, Candidate
from app.models.job import Job
from app.models.recruitment_process import RecruitmentProcess
from app.services import candidate_claim
from app.services.autofill_feedback_schema import LEARNED_FROM, REASONS

REQUIRED_CODE = "AUTOFILL_REASON_REQUIRED"
_SEARCH = frozenset(
    {
        "missing_skill",
        "too_junior",
        "overqualified",
        "other_level_or_role",
        "location_mode",
        "language",
    }
)
# „Pracuje u klienta” (często przez inną firmę, bez śladu w CV) = system nie
# miał danych; „Nie chce do klienta” = sprawa osoby (27.10.2026). Błędny
# numer i zgłoszenie przez inną firmę — też dane, których system nie miał
# (28.10.2026).
_DATA = frozenset(
    {
        "outdated_cv",
        "profile_mismatch",
        "wrong_phone",
        "client_employed",
        "client_other_vendor",
    }
)
_PERSON = frozenset({"not_looking", "no_answer", "in_other_process", "client_refused"})
# Powody, które mogą dotyczyć osoby u całego klienta (`whole_client`).
CLIENT_WIDE_REASONS = frozenset(
    {"client_employed", "client_refused", "client_other_vendor"}
)
# „Nie szuka pracy” (28.10.2026): do kiedy nie podsuwać — najwyżej dwa lata.
NOT_LOOKING_REASON = "not_looking"
NOT_LOOKING_MAX_DAYS = 731
# Kolumny, w których decyzja o osobie od systemu jeszcze trwa.
DECISION_COLUMNS = candidate_claim.CLAIM_COLUMNS

REASON_LABELS: dict[str, str] = {
    "missing_skill": "Brak kluczowej umiejętności",
    "too_junior": "Za mało doświadczenia",
    "overqualified": "Za wysoki poziom (overqualified)",
    "other_level_or_role": "Inny poziom lub inna rola",
    "location_mode": "Lokalizacja lub tryb pracy",
    "language": "Język",
    "too_expensive": "Za droga",
    "outdated_cv": "CV nieaktualne",
    "profile_mismatch": "Profil w bazie się nie zgadza",
    "wrong_phone": "Błędny numer telefonu",
    "not_looking": "Nie szuka pracy",
    "no_answer": "Nie odbiera (3 próby)",
    "in_other_process": "Już u nas w innym procesie",
    "client_employed": "Pracuje u tego klienta (też przez inną firmę)",
    "client_refused": "Nie chce do tego klienta",
    "client_other_vendor": "Zgłoszony do klienta przez inną firmę",
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
    not_looking_until: Optional[date] = None,
) -> None:
    """422 przed zapisem ruchu: brak powodu przy osobie od systemu, powód przy
    innej osobie, „Inne” bez opisu albo zła data „Nie szuka do”."""
    if not_looking_until is not None:
        if reason != NOT_LOOKING_REASON:
            raise HTTPException(
                status_code=422,
                detail="Datę „Nie szuka do” podaje się tylko przy powodzie „Nie szuka pracy”.",
            )
        today = business_today()
        if (
            not today
            < not_looking_until
            <= today + timedelta(days=NOT_LOOKING_MAX_DAYS)
        ):
            raise HTTPException(
                status_code=422,
                detail="„Nie szuka do” to data w przyszłości, najwyżej za dwa lata.",
            )
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
    whole_client: bool = False,
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
        whole_client=bool(whole_client) and reason in CLIENT_WIDE_REASONS,
        created_by=actor_id,
    )
    db.add(row)
    return row


async def mark_not_looking(db, *, candidate_id: int, until: date) -> Optional[dict]:
    """„Nie szuka pracy” z datą (28.10.2026): profil dostaje status „Nie szuka”
    i „Dostępny od” = ta data; silnik pomija osobę do tej daty
    (``new_column_autofill.not_looking_now``). Zwraca zmianę do audytu."""
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        return None
    before = {
        "availability_status": getattr(
            candidate.availability_status, "value", candidate.availability_status
        ),
        "availability_date": (
            candidate.availability_date.isoformat()
            if candidate.availability_date
            else None
        ),
    }
    candidate.availability_status = AvailabilityStatus.not_looking
    candidate.availability_date = until
    return {
        "before": before,
        "after": {
            "availability_status": AvailabilityStatus.not_looking.value,
            "availability_date": until.isoformat(),
        },
    }
