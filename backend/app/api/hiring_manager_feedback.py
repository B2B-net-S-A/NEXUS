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
NAJNOWSZY wiersz ``client_side`` tej pary — także przypięty do spotkania
(feedback od klienta zapisany z okna wydarzenia). Do 09.2026 lista i upsert
czytały wyłącznie wiersze BEZ spotkania, więc werdykt zapisany po rozmowie
w kalendarzu był na karcie rekrutacji niewidoczny („do uzupełnienia"),
a Delivery Lead wpisywał go drugi raz obok. Zapis gasi też ``needs_attention``
na wydarzeniu tego wiersza (ta sama reguła co ``PATCH /api/interview-feedback``).

Nadpisać CUDZY werdykt może wyłącznie autor, Delivery Lead, Head of Recruitment
albo admin (HoR od 17.09.2026, decyzja Artura) — ta
sama reguła co ``PATCH /api/interview-feedback`` (``_can_edit``). Do 09.2026
upsert po parze podmieniał autora i treść bez pytania, więc drugi rekruter
kasował werdykt kolegi jednym kliknięciem „Zapisz". Odczyt stoi za
``ensure_job_read_access`` (Finance ma organizacyjny odczyt rekrutacji —
decyzja 31.08), zapis za członkostwem w zespole rekrutacji.

Odczyt zwraca ``can_record`` — czy WOŁAJĄCY przejdzie ``POST`` na tej
rekrutacji, liczone TYMI SAMYMI bramkami (sekcja pipeline z prawem zapisu,
role ``RecruiterPlus``, członkostwo w zespole z obejściem nadzoru dla DL,
brak trybu podglądu). Bez tego formularz renderował się każdemu z capability
zapisu — Finance na cudzej rekrutacji klikało „Zapisz feedback" prosto w 403.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import IMPERSONATION_HEADER, RecruiterPlus
from app.api.calendar_access import user_can_mutate_event
from app.api.interview_feedback import _can_edit as _can_edit_feedback
from app.api.recruitment_access import (
    RECRUITMENT_TRANSITION_ROLES,
    RecruitmentReadAccess,
    ensure_job_membership,
    ensure_job_read_access,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.calendar_event import CalendarEvent
from app.models.contact import Contact
from app.models.interview_feedback import (
    FeedbackSource,
    InterviewDecision,
    InterviewFeedback,
)
from app.models.job import Job
from app.models.pipeline_template import RejectionReason, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.hiring_manager_verdicts import MANAGER_MET_STAGES
from app.services.interview_feedback_actions import apply_post_feedback_actions
from app.services.rejection_reason_labels import rejection_reason_label
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

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
    # Kto zapisał werdykt i czy WOŁAJĄCY może go nadpisać. Liczone po stronie
    # serwera, żeby UI nie trzymało drugiej kopii reguły „autor / DL / admin".
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    can_edit: bool = False
    # Werdykt zebrany z okna wydarzenia w kalendarzu — karta rekrutacji mówi
    # wtedy „zapisany · z rozmowy dd.mm".
    calendar_event_id: Optional[int] = None
    event_start_time: Optional[datetime] = None
    event_title: Optional[str] = None


class HiringManagerFeedbackList(BaseModel):
    """Werdykty rekrutacji + czy wołający może w ogóle zapisać werdykt.

    ``can_record`` dotyczy REKRUTACJI, nie wiersza — formularz dla kandydata
    bez werdyktu też go potrzebuje, a pusta lista nie ma w czym go nieść.
    ``can_edit`` w wierszu zostaje osobno: mówi o nadpisaniu CUDZEGO werdyktu.
    """

    can_record: bool
    items: list[HiringManagerFeedbackResponse]


async def _can_record_verdict(
    db: AsyncSession, request: Request, user: User, *, job_id: int
) -> bool:
    """Czy ``user`` przejdzie ``POST`` na tej rekrutacji — bez rzucania wyjątku.

    Lustro bramek ``record_hiring_manager_feedback`` w tej samej kolejności:
    tryb podglądu jest tylko do odczytu (``get_authenticated_user``), router
    wymaga sekcji pipeline z prawem ZAPISU dla metody innej niż odczyt
    (``PIPELINE_SECTION_DEPENDENCIES``), trasa — ról ``RecruiterPlus``
    (``RECRUITMENT_TRANSITION_ROLES`` to ich lustro; admin przechodzi zawsze),
    a handler — ``ensure_job_membership`` z tym samym obejściem nadzoru
    (admin, HoR, Delivery Lead, TCM). Walidacja kandydata i powodu dotyczy
    konkretnego zapisu, nie prawa do niego.
    """
    if request.headers.get(IMPERSONATION_HEADER):
        return False
    if section_access_for_user(user, ProductSection.pipeline) < SectionAccess.write:
        return False
    if not (
        user.has_role(UserRole.admin)
        or user.has_any_role(*RECRUITMENT_TRANSITION_ROLES)
    ):
        return False
    try:
        await ensure_job_membership(db, user, job_id)
    except HTTPException:
        return False
    return True


def _user_can_overwrite(user: User, feedback: InterviewFeedback) -> bool:
    """Czy ``user`` może nadpisać ten werdykt — reguła ``PATCH /interview-feedback``.

    ``_can_edit`` przepuszcza autora, Delivery Leada, Head of Recruitment
    i admina; zapis stoi jednak za ``RecruiterPlus``, więc rola musi też
    należeć do zbioru, który w ogóle może zapisać werdykt — inaczej
    ``can_edit`` obiecywałby przycisk kończący się 403. (Od 17.09.2026 HoR
    jest w ``RecruiterPlus`` — parytet z rekruterem.)
    """
    return user.has_any_role(*RECRUITMENT_TRANSITION_ROLES) and _can_edit_feedback(
        user, feedback
    )


def _to_response(
    feedback: InterviewFeedback,
    *,
    job: Job,
    reason: Optional[RejectionReason],
    manager_name: Optional[str],
    veto_recorded: bool,
    veto_blockers: list[str],
    author_name: Optional[str],
    can_edit: bool,
    event: Optional[CalendarEvent] = None,
) -> HiringManagerFeedbackResponse:
    return HiringManagerFeedbackResponse(
        id=feedback.id,
        job_id=job.id,
        candidate_id=feedback.candidate_id,
        decision=feedback.decision.value if feedback.decision else "",
        rejection_reason_id=feedback.rejection_reason_id,
        rejection_reason_name=rejection_reason_label(reason.name) if reason else None,
        note=feedback.feedback_summary,
        technical_fit=feedback.technical_fit,
        soft_fit=feedback.soft_fit,
        overall_fit=feedback.overall_fit,
        hiring_manager_contact_id=job.hiring_manager_contact_id,
        hiring_manager_name=manager_name,
        blocks_future_proposals=bool(reason and reason.disqualifies_person),
        veto_recorded=veto_recorded,
        veto_blockers=veto_blockers,
        author_id=feedback.author_id,
        author_name=author_name,
        can_edit=can_edit,
        calendar_event_id=feedback.calendar_event_id,
        event_start_time=event.start_time if event is not None else None,
        event_title=event.title if event is not None else None,
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
            f"Powód „{rejection_reason_label(reason.name)}” opisuje sytuację, nie osobę — takie "
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

    # Upsert po parze (kandydat, rekrutacja) WYŁĄCZNIE na wierszu bez
    # wydarzenia. Wiersz przypięty do rozmowy opisuje TĘ rozmowę (rundę 1),
    # a werdykt z karty bywa decyzją po rundzie 2 — nadpisanie zgubiłoby
    # notatkę rundy 1. Do tego FK wiersza z wydarzeniem ma ON DELETE CASCADE:
    # werdykt z karty zapisany na takim wierszu znikałby (razem z wetem) przy
    # usunięciu spotkania. Lista i tak pokazuje ostatnio zmieniony wiersz pary
    # (`updated_at`), więc po zapisie karta widzi to, co zapisała.
    feedback = await db.scalar(
        select(InterviewFeedback)
        .where(
            InterviewFeedback.job_id == job_id,
            InterviewFeedback.candidate_id == payload.candidate_id,
            InterviewFeedback.feedback_source == FeedbackSource.client_side,
            InterviewFeedback.calendar_event_id.is_(None),
        )
        .order_by(InterviewFeedback.created_at.desc(), InterviewFeedback.id.desc())
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
    elif not _user_can_overwrite(current_user, feedback):
        # Cudzy werdykt: nadpisuje go wyłącznie autor, DL albo admin (lustro
        # `PATCH /api/interview-feedback`). Imię autora w odpowiedzi, bo bez
        # niego „brak uprawnień" nie mówi, z kim to uzgodnić.
        author_name = (
            await db.scalar(select(User.name).where(User.id == feedback.author_id))
            if feedback.author_id is not None
            else None
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Werdykt dla tego kandydata zapisał(a) {author_name or 'inna osoba'}"
                " — zmienić go może autor, Delivery Lead, Head of Recruitment"
                " albo admin."
            ),
        )

    feedback.author_id = current_user.id
    feedback.decision = payload.decision
    feedback.rejection_reason_id = reason.id if reason else None
    feedback.feedback_summary = (payload.note or "").strip() or None
    feedback.technical_fit = payload.technical_fit
    feedback.soft_fit = payload.soft_fit
    feedback.overall_fit = payload.overall_fit
    await db.flush()

    # Werdykt klienta z karty to feedback po rozmowach tej pary — gasi flagę
    # „brak feedbacku" (eskalacja T+2h) na jej rozmowach. Lustro
    # `PATCH /api/interview-feedback`: tylko tam, gdzie wołający może edytować
    # wydarzenie (właściciel / admin / HoR), żeby cudza eskalacja nie gasła
    # od zapisu osoby spoza rozmowy.
    flagged_events = (
        (
            await db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.candidate_id == payload.candidate_id,
                    CalendarEvent.job_id == job_id,
                    CalendarEvent.needs_attention.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    cleared = False
    for flagged in flagged_events:
        if user_can_mutate_event(flagged, current_user):
            flagged.needs_attention = False
            cleared = True
    if cleared:
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
        author_name=current_user.name,
        can_edit=True,
        event=None,
    )


@router.get(
    "/jobs/{job_id}/hiring-manager-feedback",
    response_model=HiringManagerFeedbackList,
)
async def list_hiring_manager_feedback(
    job_id: int,
    request: Request,
    # ODCZYT szerszy niż zapis — parytet z `GET /api/interview-feedback`
    # (`RecruitmentReadAccess`, z head_of_recruitment). `RecruiterPlus` nie
    # obejmuje HoR, a HoR ma zapis w sekcji pipeline i przechodzi membership
    # jako rola nadzoru — panel feedbacku renderował mu 403 na czystym odczycie.
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> HiringManagerFeedbackList:
    """Werdykty managera dla całej rekrutacji — po jednym na kandydata.

    Karta rozmowy pyta o CAŁĄ rekrutację raz, zamiast o jednego kandydata przy
    każdym kliknięciu w lewej kolumnie. ``can_record`` mówi, czy wołający
    przejdzie ``POST`` (patrz :func:`_can_record_verdict`).

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
    # ODCZYT, nie polecenie: Finance ma organizacyjny odczyt rekrutacji
    # (decyzja 31.08) i dostawało tu 403 z bramki członkostwa, którą chronimy
    # zapisy. `ensure_job_read_access` wpuszcza Finance, resztę kieruje do
    # tej samej bramki członkostwa co dotąd.
    await ensure_job_read_access(db, current_user, job_id)

    rows = list(
        (
            await db.execute(
                select(InterviewFeedback, RejectionReason, User.name, CalendarEvent)
                .outerjoin(
                    RejectionReason,
                    RejectionReason.id == InterviewFeedback.rejection_reason_id,
                )
                .outerjoin(User, User.id == InterviewFeedback.author_id)
                .outerjoin(
                    CalendarEvent,
                    CalendarEvent.id == InterviewFeedback.calendar_event_id,
                )
                .where(
                    InterviewFeedback.job_id == job_id,
                    InterviewFeedback.feedback_source == FeedbackSource.client_side,
                )
                .order_by(
                    InterviewFeedback.updated_at.desc(),
                    InterviewFeedback.created_at.desc(),
                    InterviewFeedback.id.desc(),
                )
            )
        ).all()
    )

    manager_name = None
    if job.hiring_manager_contact_id is not None:
        manager_name = await db.scalar(
            select(Contact.name).where(Contact.id == job.hiring_manager_contact_id)
        )

    out: list[HiringManagerFeedbackResponse] = []
    seen_candidates: set[int] = set()
    for feedback, reason, author_name, event in rows:
        # Po jednym na kandydata — najnowszy. Z wierszami z kalendarza para
        # bywa opisana dwa razy (werdykt z karty + z okna wydarzenia), a karta
        # i upsert patrzą na ten sam, najnowszy wiersz.
        if feedback.candidate_id in seen_candidates:
            continue
        seen_candidates.add(feedback.candidate_id)
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
                author_name=author_name,
                can_edit=_user_can_overwrite(current_user, feedback),
                event=event,
            )
        )
    can_record = await _can_record_verdict(db, request, current_user, job_id=job_id)
    return HiringManagerFeedbackList(can_record=can_record, items=out)
