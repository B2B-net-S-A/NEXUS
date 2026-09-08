"""Werdykt hiring managera po rozmowie u klienta (krok 07 „Rozmowy i decyzja").

Do 09.2026 to, co manager powiedział po rozmowie, dało się zapisać wyłącznie
jako SKUTEK UBOCZNY odrzucenia: `POST /api/pipeline/move` na etap terminalny
z powodem ze słownika. Dopóki rekruter nie zamknął kandydata, werdykt żył
w notatce wolnym tekstem — nie dało się z niego policzyć ani lejka, ani
odpowiedzi na pytanie „czy ten manager zablokuje go przy następnej okazji".
Ten endpoint daje werdyktowi własne miejsce, PRZED decyzją o ruchu.

Trzy rzeczy, których ten endpoint CELOWO nie robi:

1. **Nie tworzy weta.** Weto nie jest wierszem w bazie — ``services/
   hiring_manager_verdicts`` WYPROWADZA je z ``candidate_stages`` (etap
   ``rejected`` + powód z ``RejectionReason.disqualifies_person`` + wcześniejszy
   etap, na którym manager kandydata poznał). Zapis „blokuje ponowne
   propozycje" jako osobnej flagi obok tamtej reguły byłby drugim źródłem
   prawdy, które przy pierwszej rozbieżności zacznie kłamać: UI mówiłoby
   „zablokowany", a ``/pipeline/move`` przepuszczałby ruch. Zamiast tego
   odpowiedź NAZYWA stan faktyczny (``blocks_future_proposals``,
   ``veto_recorded``, ``veto_blockers``), a samo weto powstaje tam, gdzie
   powstawało zawsze — przy terminalnym ruchu.

2. **Nie przenosi kandydata.** Ruch na etap ma własną, ciężką ścieżkę
   (bramka dopuszczalności, modale stawek, mail odrzucenia z 15-minutowym
   „Cofnij", talent pool, przeliczenie ryzyka). Powielenie jej tutaj byłoby
   drugą implementacją najbardziej obciążonej trasy w pipelinie.

3. **Nie zmienia słownika powodów.** ``disqualifies_person`` jest cechą POWODU,
   nie zdarzenia — przestawienie jej zmienia znaczenie historycznych odrzuceń
   w całej firmie i jest operacją administratora (``/api/pipeline-templates``).

Zapis idzie do ``InterviewFeedback`` z ``feedback_source=client_side`` — tabela
istnieje dokładnie po to („recruiter/DL zebrał feedback od klienta po
rozmowie") i niesie już ``decision``, oceny 1-5 i podsumowanie. Migracja 0278
zdejmuje z niej wymóg ``calendar_event_id`` (klient często umawia się
z kandydatem sam, poza kalendarzem NEXUSA) i dokłada ``rejection_reason_id``.

Jeden werdykt na parę (kandydat, rekrutacja): powtórne wywołanie NADPISUJE
wiersz bez spotkania zamiast hodować stos. Werdykty przypięte do konkretnego
``CalendarEvent`` zostają nietknięte — te edytuje ``PATCH /api/interview-feedback``.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.recruitment_access import RecruitmentReadAccess, ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.contact import Contact
from app.models.interview_feedback import (
    FeedbackSource,
    InterviewDecision,
    InterviewFeedback,
)
from app.models.job import Job
from app.models.pipeline_template import RejectionReason, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.hiring_manager_verdicts import MANAGER_MET_STAGES
from app.services.interview_feedback_actions import apply_post_feedback_actions

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class HiringManagerFeedbackRequest(BaseModel):
    """Co manager powiedział o tym kandydacie na tej rekrutacji."""

    candidate_id: int = Field(..., gt=0)
    decision: InterviewDecision
    # Powód ze słownika szablonu. Wymagany wyłącznie „moralnie" przy `reject` —
    # walidacja tego NIE wymusza, bo manager bywa lakoniczny, a odmowa zapisu
    # werdyktu z powodu braku etykiety kończy się werdyktem zapisanym nigdzie.
    rejection_reason_id: Optional[int] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=8000)
    technical_fit: Optional[int] = Field(default=None, ge=1, le=5)
    soft_fit: Optional[int] = Field(default=None, ge=1, le=5)
    overall_fit: Optional[int] = Field(default=None, ge=1, le=5)


class HiringManagerFeedbackResponse(BaseModel):
    """Werdykt + PRAWDA o wecie, a nie deklaracja intencji.

    ``blocks_future_proposals`` mówi o WYBRANYM POWODZIE („czy odrzucenie z tym
    powodem w ogóle może zablokować"), ``veto_recorded`` o STANIE FAKTYCZNYM
    („czy weto już stoi"), a ``veto_blockers`` wypisuje po polsku, czego jeszcze
    brakuje. Bez tych trzech osobnych pól UI musiałoby zgadywać, a zgadywanie
    kończy się chipem „Weto HM", którego backend nie egzekwuje.
    """

    id: int
    job_id: int
    candidate_id: int
    decision: str
    rejection_reason_id: Optional[int] = None
    rejection_reason_name: Optional[str] = None
    note: Optional[str] = None
    technical_fit: Optional[int] = None
    soft_fit: Optional[int] = None
    overall_fit: Optional[int] = None
    hiring_manager_contact_id: Optional[int] = None
    hiring_manager_name: Optional[str] = None
    blocks_future_proposals: bool = False
    veto_recorded: bool = False
    veto_blockers: list[str] = []


def _to_response(
    feedback: InterviewFeedback,
    *,
    job: Job,
    reason: Optional[RejectionReason],
    manager_name: Optional[str],
    veto_recorded: bool,
    veto_blockers: list[str],
) -> HiringManagerFeedbackResponse:
    return HiringManagerFeedbackResponse(
        id=feedback.id,
        job_id=job.id,
        candidate_id=feedback.candidate_id,
        decision=feedback.decision.value if feedback.decision else "",
        rejection_reason_id=feedback.rejection_reason_id,
        rejection_reason_name=reason.name if reason else None,
        note=feedback.feedback_summary,
        technical_fit=feedback.technical_fit,
        soft_fit=feedback.soft_fit,
        overall_fit=feedback.overall_fit,
        hiring_manager_contact_id=job.hiring_manager_contact_id,
        hiring_manager_name=manager_name,
        blocks_future_proposals=bool(reason and reason.disqualifies_person),
        veto_recorded=veto_recorded,
        veto_blockers=veto_blockers,
    )


async def _resolve_reason(
    db: AsyncSession, *, job: Job, reason_id: Optional[int]
) -> Optional[RejectionReason]:
    """Powód musi należeć do szablonu TEJ rekrutacji i dotyczyć odrzucenia.

    Bez tej kontroli dałoby się przypiąć powód z cudzego szablonu — a silnik
    weta czyta powód po FK, więc odczytałby go jako pełnoprawny werdykt.
    Lustro walidacji z ``POST /api/pipeline/move``.
    """
    if reason_id is None:
        return None
    reason = await db.get(RejectionReason, reason_id)
    if reason is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nie znaleziono powodu odrzucenia.",
        )
    if reason.category is not TerminalType.rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Ten powód opisuje wycofanie kandydata, nie decyzję klienta. "
                "Wybierz powód z kategorii „odrzucony”."
            ),
        )
    # Rekrutacja bez szablonu (import z Traffita) korzysta z powodów szablonu
    # domyślnego — wtedy nie ma czego porównywać i przepuszczamy.
    if job.pipeline_template_id and reason.template_id != job.pipeline_template_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ten powód należy do innego szablonu procesu niż ta rekrutacja.",
        )
    return reason


async def _veto_state(
    db: AsyncSession, *, job: Job, candidate_id: int, reason: Optional[RejectionReason]
) -> tuple[bool, list[str]]:
    """Czy weto na tej parze JUŻ stoi — i czego brakuje, żeby stanęło.

    Liczone dokładnie tymi warunkami, którymi liczy je ``load_manager_rejections``
    (minus wykluczenie ``S != T``, bo tam pytamy o INNE rekrutacje, a tu o TĘ).
    Kopiowanie warunków jest tu świadome i wąskie: chodzi o wypisanie
    użytkownikowi, czego brakuje, a nie o drugą bramkę ruchu.
    """
    blockers: list[str] = []
    if job.hiring_manager_contact_id is None:
        blockers.append(
            "Rekrutacja nie ma przypisanego hiring managera — bez niego weto "
            "nie ma komu przypisać kandydata."
        )
    if reason is None:
        blockers.append("Werdykt nie ma powodu ze słownika.")
    elif not reason.disqualifies_person:
        blockers.append(
            f"Powód „{reason.name}” opisuje sytuację, nie osobę — takie "
            "odrzucenie nie blokuje kolejnych propozycji."
        )

    # Najpóźniejsze odrzucenie z powodem-werdyktem: silnik (`load_manager_rejections`)
    # wymaga, żeby spotkanie z managerem POPRZEDZAŁO odrzucenie
    # (`met.moved_at <= rejected.moved_at`). Agregat „był kiedyś client_interview
    # i był kiedyś rejected" pasowałby też do `rejected → wznowienie →
    # client_interview`, czyli odwrotnej historii — UI mówiłoby „weto stoi",
    # a `/pipeline/move` przepuszczałby ruch.
    rejected_moved_at = await db.scalar(
        select(CandidateStage.moved_at)
        .join(RejectionReason, RejectionReason.id == CandidateStage.rejection_reason_id)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job.id,
            CandidateStage.stage == PipelineStage.rejected,
            RejectionReason.disqualifies_person.is_(True),
        )
        .order_by(CandidateStage.moved_at.desc())
        .limit(1)
    )
    if rejected_moved_at is None:
        blockers.append(
            "Kandydat nie został jeszcze odrzucony na tej rekrutacji z powodem "
            "oznaczonym jako werdykt o osobie."
        )

    met_query = select(CandidateStage.id).where(
        CandidateStage.candidate_id == candidate_id,
        CandidateStage.job_id == job.id,
        CandidateStage.stage.in_(tuple(MANAGER_MET_STAGES)),
    )
    if rejected_moved_at is not None:
        met_query = met_query.where(CandidateStage.moved_at <= rejected_moved_at)
    met_stage = await db.scalar(met_query.limit(1))
    if met_stage is None:
        blockers.append(
            "Kandydat nie był na etapie, na którym manager go poznał "
            "(Interview Klient / Akceptacja / Negocjacje), PRZED tym odrzuceniem."
            if rejected_moved_at is not None
            else "Kandydat nie był jeszcze na etapie, na którym manager go poznał "
            "(Interview Klient / Akceptacja / Negocjacje)."
        )

    recorded = job.hiring_manager_contact_id is not None and (
        met_stage is not None and rejected_moved_at is not None
    )
    return recorded, blockers


@router.post(
    "/jobs/{job_id}/hiring-manager-feedback",
    response_model=HiringManagerFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_hiring_manager_feedback(
    job_id: int,
    payload: HiringManagerFeedbackRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> HiringManagerFeedbackResponse:
    """Zapisz werdykt hiring managera o kandydacie na tej rekrutacji."""
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono rekrutacji."
        )
    await ensure_job_membership(db, current_user, job_id)

    candidate_in_pipeline = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == payload.candidate_id,
            CandidateStage.job_id == job_id,
        )
        .limit(1)
    )
    if candidate_in_pipeline is None:
        # 404 na kandydacie, a nie 422 na polu: dla wołającego to „nie ma go
        # w tym procesie", a nie „wpisałeś zły format".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ten kandydat nie jest w procesie tej rekrutacji.",
        )

    reason = await _resolve_reason(db, job=job, reason_id=payload.rejection_reason_id)

    # Upsert po parze (kandydat, rekrutacja) wśród wierszy BEZ spotkania.
    # Wiersze przypięte do `CalendarEvent` zostają nietknięte — mają własną
    # ścieżkę edycji i własne miejsce w kalendarzu.
    feedback = await db.scalar(
        select(InterviewFeedback)
        .where(
            InterviewFeedback.job_id == job_id,
            InterviewFeedback.candidate_id == payload.candidate_id,
            InterviewFeedback.feedback_source == FeedbackSource.client_side,
            InterviewFeedback.calendar_event_id.is_(None),
        )
        .order_by(InterviewFeedback.created_at.desc())
        .limit(1)
    )
    created = feedback is None
    if feedback is None:
        feedback = InterviewFeedback(
            calendar_event_id=None,
            candidate_id=payload.candidate_id,
            job_id=job_id,
            feedback_source=FeedbackSource.client_side,
        )
        db.add(feedback)

    feedback.author_id = current_user.id
    feedback.decision = payload.decision
    feedback.rejection_reason_id = reason.id if reason else None
    feedback.feedback_summary = (payload.note or "").strip() or None
    feedback.technical_fit = payload.technical_fit
    feedback.soft_fit = payload.soft_fit
    feedback.overall_fit = payload.overall_fit
    await db.flush()

    # Powiadomienie „klient idzie dalej / klient odpada — zaproponuj next step"
    # do rekrutera prowadzącego. Best-effort jak w `POST /api/interview-feedback`:
    # nieudane powiadomienie nie może skasować zapisanego werdyktu.
    try:
        await apply_post_feedback_actions(db, feedback)
    except Exception:  # noqa: BLE001
        logger.exception(
            "apply_post_feedback_actions failed for hiring-manager feedback id=%s",
            feedback.id,
        )

    veto_recorded, veto_blockers = await _veto_state(
        db, job=job, candidate_id=payload.candidate_id, reason=reason
    )

    manager_name = None
    if job.hiring_manager_contact_id is not None:
        manager_name = await db.scalar(
            select(Contact.name).where(Contact.id == job.hiring_manager_contact_id)
        )

    await db.commit()
    await db.refresh(feedback)

    logger.info(
        "hiring-manager feedback %s job=%s candidate=%s decision=%s",
        "created" if created else "updated",
        job_id,
        payload.candidate_id,
        payload.decision.value,
    )
    return _to_response(
        feedback,
        job=job,
        reason=reason,
        manager_name=manager_name,
        veto_recorded=veto_recorded,
        veto_blockers=veto_blockers,
    )


@router.get(
    "/jobs/{job_id}/hiring-manager-feedback",
    response_model=list[HiringManagerFeedbackResponse],
)
async def list_hiring_manager_feedback(
    job_id: int,
    # ODCZYT szerszy niż zapis — parytet z `GET /api/interview-feedback`
    # (`RecruitmentReadAccess`, z head_of_recruitment). `RecruiterPlus` nie
    # obejmuje HoR, a HoR ma zapis w sekcji pipeline i przechodzi membership
    # jako rola nadzoru — panel feedbacku renderował mu 403 na czystym odczycie.
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> list[HiringManagerFeedbackResponse]:
    """Werdykty managera dla całej rekrutacji — po jednym na kandydata.

    Karta rozmowy pyta o CAŁĄ rekrutację raz, zamiast o jednego kandydata przy
    każdym kliknięciu w lewej kolumnie.

    ``_veto_state`` liczy się per wiersz (dwa lekkie ``SELECT ... LIMIT 1``), bo
    zależy od historii etapów KONKRETNEJ pary. Zbiór jest z natury mały —
    werdykty klienta powstają dla kandydatów, którzy dotarli do rozmowy — więc
    batch nie jest tu wart komplikacji. Gdyby kiedyś zaczęło ich być kilkaset,
    to jest miejsce do przepisania na jedno zapytanie z ``GROUP BY``.
    """
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono rekrutacji."
        )
    await ensure_job_membership(db, current_user, job_id)

    rows = list(
        (
            await db.execute(
                select(InterviewFeedback, RejectionReason)
                .outerjoin(
                    RejectionReason,
                    RejectionReason.id == InterviewFeedback.rejection_reason_id,
                )
                .where(
                    InterviewFeedback.job_id == job_id,
                    InterviewFeedback.feedback_source == FeedbackSource.client_side,
                    InterviewFeedback.calendar_event_id.is_(None),
                )
                .order_by(InterviewFeedback.created_at.desc())
            )
        ).all()
    )

    manager_name = None
    if job.hiring_manager_contact_id is not None:
        manager_name = await db.scalar(
            select(Contact.name).where(Contact.id == job.hiring_manager_contact_id)
        )

    out: list[HiringManagerFeedbackResponse] = []
    for feedback, reason in rows:
        veto_recorded, veto_blockers = await _veto_state(
            db, job=job, candidate_id=feedback.candidate_id, reason=reason
        )
        out.append(
            _to_response(
                feedback,
                job=job,
                reason=reason,
                manager_name=manager_name,
                veto_recorded=veto_recorded,
                veto_blockers=veto_blockers,
            )
        )
    return out
