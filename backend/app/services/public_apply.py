"""Przyjęcie publicznego zgłoszenia z linku aplikacyjnego — jedna ścieżka.

Wołają ją dwa endpointy: stary ``POST /api/public/apply/{token}`` (formularz
``/apply/[token]``) i ``POST /api/public/career/apply`` (strona kariery,
link po slugu). Do 0339 cała logika siedziała w handlerze starego endpointu,
więc drugi endpoint byłby kopią, która rozjeżdża się przy pierwszej poprawce.

Dwie gałęzie, obie kończą się identycznym ogólnym 201 (odpowiedź nie zdradza,
czy e-mail już był w bazie):

* **nowy e-mail** — kandydat powstaje z ``created_by`` = właściciel linku.
  Link rekrutacji otwiera proces na etapie „Nowy"; stały link rekrutera NIE
  otwiera procesu, za to przypina osobę w „Moich ludziach" właściciela
  (lista liczy się z etapów, więc bez przypięcia kandydat by tam nie trafił);
* **e-mail już w bazie** (P0-CAND-01) — pola profilu NIE są nadpisywane,
  ale zgłoszenie trafia tam, gdzie trafiłoby od nowej osoby (decyzja Artura
  22.09.2026 — kolejka „Zgłoszenia” przez całe życie nie dostała ani jednego
  wpisu, a rekruter i tak chce tę osobę w rekrutacji): CV dochodzi do profilu
  jako dodatkowy, NIE główny dokument, link rekrutacji otwiera proces na
  etapie „Nowy”, stały link przypina osobę w „Moich ludziach”. Wiersz
  ``application_submissions`` zostaje jako zapis zgłoszenia (status
  ``linked``) — tam żyją nowe pola (stawka, dostępność, miasto, tryb pracy)
  i zgoda. Osoba na globalnej czarnej liście nie wchodzi do procesu ani na
  listę — zostaje sam dokument i powiadomienie.

Zgoda jest zapisywana w tej samej transakcji co kandydat/zgłoszenie. Po
commicie właściciel linku dostaje powiadomienie ``new_application`` — nigdy
nie wywraca odpowiedzi (kandydat już jest w bazie).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.application_submission import (
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_consent import CONSENT_KIND_RECRUITMENT, CandidateConsent
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job
from app.models.my_people import MyPeopleOverride
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_priority import PriorityOriginKind
from app.models.user_activity import UserActionType, UserActivity
from app.services.career_consent import (
    CONSENT_TEXT_SHA256,
    CONSENT_TEXT_VERSION,
    consent_given,
)

logger = logging.getLogger(__name__)

WORK_MODES = ("remote", "hybrid", "onsite", "any")
RATE_MIN = Decimal("1")
RATE_MAX = Decimal("10000")
CITY_MAX = 120


def field_error(field_name: str, message: str, value: Any = None) -> HTTPException:
    """422 w kształcie walidacji FastAPI (``detail`` = lista z ``loc``).

    Front (``lib/apply-form-errors.ts``) stawia komunikat przy polu po
    ``loc: ["body", <pole>]`` — ten sam kształt co błędy ``Form(...)``.
    """
    return HTTPException(
        status_code=422,
        detail=[
            {
                "type": "value_error",
                "loc": ["body", field_name],
                "msg": message,
                "input": value,
            }
        ],
    )


def require_consent(value: Optional[str]) -> None:
    if not consent_given(value):
        raise field_error(
            "consent",
            "Zaznacz zgodę na przetwarzanie danych — bez niej nie możemy "
            "przyjąć zgłoszenia.",
            value,
        )


@dataclass
class ApplicantInput:
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    message: Optional[str] = None
    expected_rate_hourly: Optional[Decimal] = None
    availability_date: Optional[date] = None
    city: Optional[str] = None
    work_mode: Optional[str] = None
    utm: dict[str, Optional[str]] = field(default_factory=dict)


def parse_optional_fields(
    *,
    expected_rate_hourly: Optional[str],
    availability_date: Optional[str],
    city: Optional[str],
    work_mode: Optional[str],
) -> dict[str, Any]:
    """Opcjonalne pola formularza jako tekst → wartości albo 422 przy polu.

    Tekst, nie typy FastAPI: formularze wysyłają puste stringi dla
    niewypełnionych pól, a ``Form(date)`` odrzuciłby ``""`` zamiast uznać je
    za brak wartości.
    """
    out: dict[str, Any] = {
        "expected_rate_hourly": None,
        "availability_date": None,
        "city": None,
        "work_mode": None,
    }
    raw_rate = (expected_rate_hourly or "").strip().replace(" ", "").replace(",", ".")
    if raw_rate:
        try:
            rate = Decimal(raw_rate)
        except InvalidOperation:
            raise field_error(
                "expected_rate_hourly",
                "Podaj stawkę jako liczbę.",
                expected_rate_hourly,
            ) from None
        if not rate.is_finite() or rate < RATE_MIN or rate > RATE_MAX:
            raise field_error(
                "expected_rate_hourly",
                "Stawka musi mieścić się między 1 a 10 000 zł/h.",
                expected_rate_hourly,
            )
        out["expected_rate_hourly"] = rate.quantize(Decimal("0.01"))
    raw_date = (availability_date or "").strip()
    if raw_date:
        try:
            out["availability_date"] = date.fromisoformat(raw_date)
        except ValueError:
            raise field_error(
                "availability_date",
                "Podaj datę w formacie RRRR-MM-DD.",
                availability_date,
            ) from None
    raw_city = (city or "").strip()
    if raw_city:
        if len(raw_city) > CITY_MAX:
            raise field_error(
                "city", f"Miasto może mieć najwyżej {CITY_MAX} znaków.", city
            )
        out["city"] = raw_city
    raw_mode = (work_mode or "").strip().lower()
    if raw_mode:
        if raw_mode not in WORK_MODES:
            raise field_error("work_mode", "Wybierz tryb pracy z listy.", work_mode)
        out["work_mode"] = raw_mode
    return out


def link_key(link: CandidateInviteLink) -> str:
    """Nie-sekretny klucz linku: SHA-256 sekretu (v2) albo PK (legacy)."""
    if link.token_sha256:
        return link.token_sha256
    return hashlib.sha256(link.token.encode()).hexdigest()


@dataclass
class LinkRef:
    link: CandidateInviteLink
    digest: str
    # Krótki, nie-sekretny prefiks do `Candidate.source` i Activity.
    audit_prefix: str
    via: str  # "invite_link" (stary formularz) | "career" (strona kariery)


def _remote_modes(work_mode: Optional[str]) -> Optional[list[str]]:
    if work_mode is None:
        return None
    if work_mode == "any":
        return ["remote", "hybrid", "onsite"]
    return [work_mode]


def _optional_payload(applicant: ApplicantInput) -> dict[str, Any]:
    return {
        "expected_rate_hourly": (
            str(applicant.expected_rate_hourly)
            if applicant.expected_rate_hourly is not None
            else None
        ),
        "availability_date": (
            applicant.availability_date.isoformat()
            if applicant.availability_date
            else None
        ),
        "city": applicant.city,
        "work_mode": applicant.work_mode,
    }


def _consent_row(ref: LinkRef, **subject: int) -> CandidateConsent:
    return CandidateConsent(
        kind=CONSENT_KIND_RECRUITMENT,
        text_version=CONSENT_TEXT_VERSION,
        text_sha256=CONSENT_TEXT_SHA256,
        given_at=datetime.now(timezone.utc),
        invite_link_key=ref.digest,
        **subject,
    )


async def submit_application(
    db: AsyncSession,
    *,
    ref: LinkRef,
    applicant: ApplicantInput,
    cv: UploadFile,
    content: bytes,
    background_tasks: BackgroundTasks,
) -> dict:
    """Obie gałęzie zgłoszenia; commit w środku. Zwraca ogólne 201."""
    from app.api import public_share

    link = ref.link
    normalized_email = applicant.email.strip().lower()
    existing = await db.scalar(
        select(Candidate).where(func.lower(Candidate.email) == normalized_email)
    )

    if existing is not None:
        existing_id = existing.id
        blacklisted = existing.status == CandidateStatus.blacklisted
        _submission_id, blocked_reason = await _record_duplicate_application(
            db,
            ref=ref,
            applicant=applicant,
            cv=cv,
            content=content,
            existing=existing,
            blacklisted=blacklisted,
        )
        await db.commit()
        await _notify_owner(
            db,
            link=link,
            applicant=applicant,
            related_entity_type="candidate",
            related_entity_id=existing_id,
            target=f"/candidates/{existing_id}",
            duplicate=True,
            blacklisted=blacklisted,
            blocked_reason=blocked_reason,
        )
        return {"ok": True, "status": "received"}

    candidate = await _create_candidate(
        db, ref=ref, applicant=applicant, cv=cv, content=content
    )
    await db.commit()
    candidate_id = candidate.id

    await _notify_owner(
        db,
        link=link,
        applicant=applicant,
        related_entity_type="candidate",
        related_entity_id=candidate_id,
        target=f"/candidates/{candidate_id}",
        duplicate=False,
    )

    # Lookup przez moduł (nie import nazwy): testy podmieniają
    # `public_share._invite_post_apply_task`.
    background_tasks.add_task(public_share._invite_post_apply_task, candidate_id)
    return {"ok": True, "status": "received"}


async def _record_duplicate_application(
    db: AsyncSession,
    *,
    ref: LinkRef,
    applicant: ApplicantInput,
    cv: UploadFile,
    content: bytes,
    existing: Candidate,
    blacklisted: bool,
) -> tuple[int, Optional[str]]:
    """Zwraca (id zgłoszenia, powód nieotwarcia procesu albo ``None``)."""
    from app.api import public_share
    from app.api.application_submissions import (
        _attach_cv_as_document,
        _ensure_submission_process,
        submission_block_reason,
    )
    from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
    from app.services.candidate_stage_cv_service import create_original_cv_snapshot

    link = ref.link
    object_key, cv_bytes, raw_text = await public_share._persist_submission_cv(
        cv, content
    )
    submission = ApplicationSubmission(
        invite_link_token_sha256=ref.digest,
        job_id=link.job_id,
        status=ApplicationSubmissionStatus.linked.value,
        reviewed_at=datetime.now(timezone.utc),
        submitted_first_name=applicant.first_name,
        submitted_last_name=applicant.last_name,
        submitted_email=applicant.email,
        submitted_phone=applicant.phone,
        submitted_linkedin=applicant.linkedin,
        submitted_message=applicant.message,
        matched_candidate_id=existing.id,
        cv_object_key=object_key,
        cv_file_content=cv_bytes,
        cv_filename=(cv.filename or "cv.pdf"),
        cv_content_type=cv.content_type,
        cv_size_bytes=len(content),
        raw_cv_text=raw_text,
        raw_payload={
            "origin_assignment_id": link.origin_assignment_id,
            "priority_compliant_at_create": link.priority_compliant_at_create,
            "first_name": applicant.first_name,
            "last_name": applicant.last_name,
            "email": applicant.email,
            "phone": applicant.phone,
            "linkedin": applicant.linkedin,
            "message": applicant.message,
            **_optional_payload(applicant),
            "link_kind": link.kind,
            "via": ref.via,
            "consent": {
                "kind": CONSENT_KIND_RECRUITMENT,
                "text_version": CONSENT_TEXT_VERSION,
            },
            "utm": {
                "source": applicant.utm.get("source"),
                "medium": applicant.utm.get("medium"),
                "campaign": applicant.utm.get("campaign"),
                "term": applicant.utm.get("term"),
                "content": applicant.utm.get("content"),
            },
        },
    )
    db.add(submission)
    await db.flush()
    db.add(_consent_row(ref, application_submission_id=submission.id))

    # CV jako dodatkowy dokument — nigdy główny: e-mail to za mało, żeby
    # cudzy plik zastąpił CV, na którym pracuje zespół.
    await _attach_cv_as_document(db, existing.id, submission)
    opened_stage = None
    blocked_reason: Optional[str] = None
    if not blacklisted:
        if link.job_id is not None:
            # Audyt 22.09 r2 (CAND-01): weto hiring managera tej rekrutacji
            # (ta sama bramka co przypisanie) — CV zostaje przy profilu, proces
            # się nie otwiera, a właściciel linku dostaje powód w dzwonku.
            # Publicznie nic się nie zmienia (ogólne 201, bez enumeracji).
            blocked_reason = await submission_block_reason(
                db, job_id=link.job_id, candidate_id=existing.id
            )
        if link.job_id is not None and blocked_reason is None:
            opened_stage = await _ensure_submission_process(
                db,
                submission=submission,
                candidate_id=existing.id,
                actor_user_id=link.created_by,
            )
        elif link.job_id is None:
            await db.execute(
                pg_insert(MyPeopleOverride)
                .values(
                    user_id=link.created_by, candidate_id=existing.id, kind="pinned"
                )
                .on_conflict_do_nothing(
                    constraint="uq_my_people_overrides_user_candidate"
                )
            )
    if opened_stage is not None:
        await db.flush()
        await create_original_cv_snapshot(db, opened_stage)
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=existing.id,
            job_id=opened_stage.job_id,
            source="pipeline",
            occurred_at=opened_stage.moved_at,
        )

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=existing.id,
            action="applied_via_invite",
            user_id=link.created_by,
            details={
                "invite_token": ref.audit_prefix,
                "invite_token_sha256": ref.digest,
                "job_id": link.job_id,
                "link_kind": link.kind,
                "via": ref.via,
                "was_duplicate": True,
                "submission_id": submission.id,
                "process_opened": opened_stage is not None,
                "blacklisted": blacklisted,
                "process_blocked": blocked_reason is not None,
            },
        )
    )
    link.use_count += 1
    link.last_used_at = datetime.now(timezone.utc)
    return submission.id, blocked_reason


async def _create_candidate(
    db: AsyncSession,
    *,
    ref: LinkRef,
    applicant: ApplicantInput,
    cv: UploadFile,
    content: bytes,
) -> Candidate:
    from app.api import public_share
    from app.models.candidate_source_event import (
        CandidateSourceEvent,
        SourceChannel,
    )
    from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
    from app.services.candidate_stage_cv_service import create_original_cv_snapshot
    from app.services.recruitment_process_commands import open_process

    link = ref.link
    now = datetime.now(timezone.utc)
    remote_modes = _remote_modes(applicant.work_mode)
    # Stawka jako argumenty konstruktora, nie przypisania po fakcie: to pola
    # KANDYDATA, a kontrakt writera etapów (`test_priority_work_writer_
    # architecture`) czyta przypisanie `*.expected_rate_currency` jako zapis
    # krytycznego pola CandidateStage.
    rate_fields: dict[str, Any] = {}
    if applicant.expected_rate_hourly is not None:
        rate_fields = {
            "expected_rate_hourly": applicant.expected_rate_hourly,
            "expected_rate_currency": "PLN",
            "profile_rate_updated_at": now,
        }
    candidate = Candidate(
        name=applicant.first_name,
        lastname=applicant.last_name,
        email=applicant.email,
        phone=applicant.phone,
        linkedin=applicant.linkedin,
        source=f"invite_link:{ref.audit_prefix}",
        status=CandidateStatus.active,
        created_by=link.created_by,
        profile_about=applicant.message,
        city=applicant.city,
        availability_date=applicant.availability_date,
        preferences={"remote_modes": remote_modes} if remote_modes else {},
        **rate_fields,
    )
    db.add(candidate)
    await db.flush()
    # Intencja indeksu w tej samej transakcji co kandydat: rekord ma być w
    # matchingu nawet wtedy, gdy odczyt CV w tle się nie powiedzie. Pełny wektor
    # liczy potem `finish_cv_ingest`. Savepoint — awaria indeksu nie może cofnąć
    # zgłoszenia.
    from app.services.index_outbox_service import schedule_or_embed_candidate

    try:
        async with db.begin_nested():
            await schedule_or_embed_candidate(candidate.id, db)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[apply] index intent failed candidate=%s: %s", candidate.id, exc
        )
    db.add(_consent_row(ref, candidate_id=candidate.id))

    stored_filename, _raw_text = await public_share._persist_cv(
        candidate.id, cv, content
    )
    db.add(
        CandidateDocument(
            candidate_id=candidate.id,
            filename=stored_filename,
            file_content=content,
            content_type=cv.content_type,
            size_bytes=len(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            uploaded_at=now,
            external_source="invite_link",
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
    )
    await db.flush()

    if link.job_id is not None:
        stage_exists = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate.id,
                CandidateStage.job_id == link.job_id,
            )
        )
        if stage_exists is None:
            new_stage = await open_process(
                db,
                candidate_id=candidate.id,
                job_id=link.job_id,
                stage=PipelineStage.new,
                actor_user_id=link.created_by,
                origin_kind=PriorityOriginKind.external_inbound,
                frozen_origin_assignment_id=link.origin_assignment_id,
                frozen_priority_compliant=link.priority_compliant_at_create,
                notes=(
                    "Aplikacja przez stronę kariery"
                    if ref.via == "career"
                    else "Aplikacja przez invite link"
                ),
            )
            await create_original_cv_snapshot(db, new_stage)
            await maybe_ensure_contact_opportunity(
                db,
                candidate_id=candidate.id,
                job_id=link.job_id,
                source="pipeline",
                occurred_at=new_stage.moved_at,
            )
    else:
        # Stały link rekrutera: bez procesu. „Moi ludzie" liczy się z etapów,
        # więc bez przypięcia nowa osoba nie pokazałaby się właścicielowi.
        await db.execute(
            pg_insert(MyPeopleOverride)
            .values(user_id=link.created_by, candidate_id=candidate.id, kind="pinned")
            .on_conflict_do_nothing(constraint="uq_my_people_overrides_user_candidate")
        )

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="applied_via_invite",
            user_id=link.created_by,
            details={
                "invite_token": ref.audit_prefix,
                "invite_token_sha256": ref.digest,
                "job_id": link.job_id,
                "link_kind": link.kind,
                "via": ref.via,
                "was_duplicate": False,
            },
        )
    )
    db.add(
        UserActivity(
            user_id=link.created_by,
            action_type=UserActionType.candidate_added,
            entity_type="candidate",
            entity_id=candidate.id,
            details={
                "name": f"{candidate.name} {candidate.lastname}",
                "source": "invite_link",
                "invite_token": ref.audit_prefix,
                "invite_token_sha256": ref.digest,
                "was_duplicate": False,
            },
        )
    )
    link.use_count += 1
    link.last_used_at = now
    db.add(
        CandidateSourceEvent(
            candidate_id=candidate.id,
            channel=SourceChannel.posting,
            job_id=link.job_id,
            utm_source=applicant.utm.get("source"),
            utm_medium=applicant.utm.get("medium"),
            utm_campaign=applicant.utm.get("campaign"),
            utm_term=applicant.utm.get("term"),
            utm_content=applicant.utm.get("content"),
        )
    )
    return candidate


async def _notify_owner(
    db: AsyncSession,
    *,
    link: CandidateInviteLink,
    applicant: ApplicantInput,
    related_entity_type: str,
    related_entity_id: int,
    target: str,
    duplicate: bool,
    blacklisted: bool = False,
    blocked_reason: Optional[str] = None,
) -> None:
    """Dzwonek dla właściciela linku. Po commicie, nigdy nie rzuca."""
    owner_id = link.created_by
    job_id = link.job_id
    try:
        from app.services.notification_triggers import emit

        job_title: Optional[str] = None
        if job_id is not None:
            job_title = await db.scalar(select(Job.title).where(Job.id == job_id))
        person = f"{applicant.first_name} {applicant.last_name}".strip()
        where = (
            f"przez link do rekrutacji „{job_title}”"
            if job_title
            else "przez Twój stały link"
        )
        message = f"{person} wysłał(a) CV {where}."
        if blacklisted:
            message += (
                " Ta osoba jest na czarnej liście — CV dołączono do profilu, "
                "ale nie dodano jej do rekrutacji."
            )
        elif blocked_reason:
            message += (
                " CV dołączono do profilu, ale nie dodano tej osoby do "
                f"rekrutacji: {blocked_reason}"
            )
        elif duplicate:
            message += (
                " Ta osoba była już w bazie — nowe CV dołączono do jej profilu "
                "jako dodatkowy dokument, dane profilu bez zmian."
            )
        await emit(
            db,
            user_id=owner_id,
            title="Nowe zgłoszenie z linku aplikacyjnego",
            message=message,
            ntype=NotificationType.new_application,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            link=target,
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — powiadomienie nie cofa zgłoszenia
        logger.warning(
            "[apply] new_application notification failed link_owner=%s: %s",
            owner_id,
            type(exc).__name__,
        )
        try:
            await db.rollback()
        except Exception:  # pragma: no cover
            pass
