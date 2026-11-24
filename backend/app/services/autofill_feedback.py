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
* ``other`` — „Inne”, z opisem, i „Porządki” (duplikat, nieaktualny
  proces), których raport jakości w ogóle nie liczy.

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
from app.services.autofill_feedback_schema import GAP_KINDS, LEARNED_FROM, REASONS

REQUIRED_CODE = "AUTOFILL_REASON_REQUIRED"
_SEARCH = frozenset(
    {
        "missing_skill",
        "too_junior",
        "overqualified",
        "other_level_or_role",
        "location_mode",
        "language",
        "no_polish",
        "weak_english",
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
        "hm_already_interviewed",
        # Kraj spoza Polski system odcina sam, więc taka osoba w „Nowych”
        # to brak kraju w profilu (24.11.2026).
        "outside_poland",
    }
)
# Jeden słownik (0745, 19.11.2026): kulturowe dopasowanie, termin dostępności
# i przyjęta inna oferta to sprawa osoby, nie wyszukiwania; rozmowa u tego
# hiring managera to dane, których system nie miał. Powody klienta zostają
# w „other”: mówią o decyzji klienta, nie o tym, kogo system dobrał.
_PERSON = frozenset(
    {
        "not_looking",
        "no_answer",
        "in_other_process",
        "client_refused",
        "contract_form",
        "culture",
        "available_too_late",
        "accepted_other_offer",
    }
)
# Powody, które mogą dotyczyć osoby u całego klienta (`whole_client`).
CLIENT_WIDE_REASONS = frozenset(
    {"client_employed", "client_refused", "client_other_vendor"}
)
# „Nie szuka pracy” (28.10.2026): do kiedy nie podsuwać — najwyżej dwa lata.
NOT_LOOKING_REASON = "not_looking"
NOT_LOOKING_MAX_DAYS = 731
# „Zatrudniony gdzie indziej” (04.11.2026): „Nie szuka” na 3 miesiące.
EMPLOYED_ELSEWHERE_DAYS = 92
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
    "no_polish": "Brak polskiego",
    "weak_english": "Angielski za słaby",
    "contract_form": "Forma umowy (UoP / B2B)",
    "cleanup": "Porządki (nie ocena osoby)",
    "culture": "Nie pasuje kulturowo",
    "available_too_late": "Dostępna za późno / wypowiedzenie",
    "accepted_other_offer": "Przyjęła inną ofertę",
    "hm_already_interviewed": "Już po rozmowie u tego hiring managera",
    "client_chose_other": "Klient wybrał innego kandydata",
    "client_interview_weak": "Rozmowa u klienta wypadła słabo",
    "client_project_closed": "Klient zamknął projekt / przetarg przegrany",
    "client_after_deadline": "Wysłany do klienta po terminie",
    "client_no_reason": "Klient nie podał powodu",
    "outside_poland": "Mieszka poza Polską",
    "other": "Inne",
}
assert set(REASON_LABELS) == set(REASONS)

# Braki przy pozycjach (12.11.2026): przy „Brak umiejętności” rekruter klika
# przy pozycji wymagania „brak”, „tylko wzmianka” albo „za mało lat”.
GAP_REASON = "missing_skill"
MAX_GAPS = 10
GAP_LABEL_MAX = 120


# Runda 5 (16.11.2026, 0717): szczegół powodu z porcji. Na 13.11 „Inna rola”
# była 49×, z opisem 0×; 22 z 45 „Inne” to porządki tablicy albo sama kropka.
CLEANUP_REASON = "cleanup"
ROLE_REASON = "other_level_or_role"
# 16.11.2026 („Kogo szukamy”): 8 odpowiedzi na „Co nie gra z rolą?”. ``level``
# zostaje ważne dla starych wpisów, ale nie ma go już na ekranie.
ROLE_KINDS = (
    "profession",
    "specialty",
    "technology",
    "lead_not_ic",
    "ic_not_lead",
    "past_role",
    "side_role",
    "domain",
    "level",
)
ROLE_WANTED_MAX = 120
AVAILABILITY_KINDS = ("not_looking", "notice", "from_date")
CLEANUP_KINDS = ("duplicate", "stale_process", "cv_broken")
# „Inne” = choć tyle liter; kropka nie mówi nic (11 z 45 „Inne” 13.11).
OTHER_NOTE_MIN_LETTERS = 3
_UNKNOWN_DETAIL = "Szczegół powodu nie pasuje do wybranego powodu."


def clean_detail(reason: Optional[str], raw: Any) -> Optional[dict]:
    """Szczegół powodu z żądania albo ``None``. Klucze zależą od powodu:
    „Inna rola” — ``role_kind``, ``role_wanted`` i ``person_role`` (z niego
    uczy się „Nie proponujemy”, ``job_role_profile``), „Nie szuka” —
    ``availability``, „Porządki” — ``cleanup`` (wymagany). Inny klucz albo
    wartość spoza listy = 422."""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail=_UNKNOWN_DETAIL)
    allowed = {
        ROLE_REASON: {"role_kind", "role_wanted", "person_role"},
        NOT_LOOKING_REASON: {"availability"},
        CLEANUP_REASON: {"cleanup"},
    }.get(reason or "", set())
    if set(raw) - allowed:
        raise HTTPException(status_code=422, detail=_UNKNOWN_DETAIL)
    out: dict = {}
    if raw.get("role_kind") is not None:
        if raw["role_kind"] not in ROLE_KINDS:
            raise HTTPException(status_code=422, detail=_UNKNOWN_DETAIL)
        out["role_kind"] = raw["role_kind"]
    wanted = str(raw.get("role_wanted") or "").strip()[:ROLE_WANTED_MAX]
    if wanted:
        out["role_wanted"] = wanted
    person = " ".join(str(raw.get("person_role") or "").split())[:ROLE_WANTED_MAX]
    if person:
        out["person_role"] = person
    if raw.get("availability") is not None:
        if raw["availability"] not in AVAILABILITY_KINDS:
            raise HTTPException(status_code=422, detail=_UNKNOWN_DETAIL)
        out["availability"] = raw["availability"]
    if reason == CLEANUP_REASON:
        if raw.get("cleanup") not in CLEANUP_KINDS:
            raise HTTPException(
                status_code=422, detail="Przy „Porządkach” wybierz, czego dotyczą."
            )
        out["cleanup"] = raw["cleanup"]
    return out or None


def clean_gaps(raw: Any) -> list[dict]:
    """Braki z żądania: znane rodzaje, bez pustych i powtórzeń (pierwszy wygrywa),
    najwyżej ``MAX_GAPS``. Nieznany rodzaj = 422."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw or []:
        label = str((item or {}).get("label") or "").strip()[:GAP_LABEL_MAX]
        kind = (item or {}).get("kind")
        if kind not in GAP_KINDS:
            raise HTTPException(status_code=422, detail="Nieznany rodzaj braku.")
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        out.append({"label": label, "kind": kind})
        if len(out) == MAX_GAPS:
            break
    return out


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


def check_not_looking_until(until: date) -> None:
    """422, gdy „Nie szuka do” nie jest datą od jutra do dwóch lat. Ta sama
    reguła przy osobie od systemu i przy karcie dodanej ręcznie (19.11.2026)."""
    today = business_today()
    if not today < until <= today + timedelta(days=NOT_LOOKING_MAX_DAYS):
        raise HTTPException(
            status_code=422,
            detail="„Nie szuka do” to data w przyszłości, najwyżej za dwa lata.",
        )


def validate(
    *,
    process: Optional[RecruitmentProcess],
    reason: Optional[str],
    learned_from: Optional[str],
    note: Optional[str],
    not_looking_until: Optional[date] = None,
    gaps: Optional[list] = None,
    detail: Optional[dict] = None,
) -> None:
    """422 przed zapisem ruchu: brak powodu przy osobie od systemu, powód przy
    innej osobie, „Inne” bez opisu albo zła data „Nie szuka do”."""
    if not_looking_until is not None:
        if reason != NOT_LOOKING_REASON:
            raise HTTPException(
                status_code=422,
                detail="Datę „Nie szuka do” podaje się tylko przy powodzie „Nie szuka pracy”.",
            )
        check_not_looking_until(not_looking_until)
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
    if reason == "other" and (
        sum(ch.isalpha() for ch in (note or "")) < OTHER_NOTE_MIN_LETTERS
    ):
        raise HTTPException(status_code=422, detail="Przy „Inne” opisz powód słowami.")
    clean_detail(reason, detail)
    if gaps:
        clean_gaps(gaps)
    if gaps and reason != GAP_REASON:
        raise HTTPException(
            status_code=422,
            detail="Braki przy pozycjach podaje się tylko przy „Brak umiejętności”.",
        )


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
    gaps: Optional[list] = None,
    detail: Optional[dict] = None,
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
        gaps=clean_gaps(gaps) if reason == GAP_REASON and gaps else None,
        detail=clean_detail(reason, detail),
        created_by=actor_id,
    )
    db.add(row)
    return row


async def mark_employed_elsewhere(db, *, candidate_id: int) -> Optional[dict]:
    """Odrzucenie „Zatrudniony gdzie indziej” (04.11.2026): 41 ze 159 takich osób
    dostało potem 61 kart od systemu i żadna nie doszła do „Zweryfikowany”.
    Dłuższego „Nie szuka” nie skraca. Zwraca zmianę do audytu albo ``None``."""
    until = business_today() + timedelta(days=EMPLOYED_ELSEWHERE_DAYS)
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if (
        candidate is None
        or candidate.availability_status == AvailabilityStatus.not_looking
        and (
            candidate.availability_date is None or candidate.availability_date >= until
        )
    ):
        return None
    return await mark_not_looking(db, candidate_id=candidate_id, until=until)


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
