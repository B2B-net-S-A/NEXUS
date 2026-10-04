"""Cykl życia rekrutacji bez szkiców — rdzenie bez commitu (04.10.2026).

Decyzja Artura 04.10.2026: rekrutacja nigdy nie jest szkicem. Utworzenie =
przekazanie do searchu = publikacja, w JEDNYM żądaniu i JEDNEJ transakcji;
ponowne otwarcie zamkniętej rekrutacji przechodzi tę samą bramkę.

Żeby to złożyć z istniejących kroków, każdy krok (założenie, zapis Championa,
decyzja o hiring managerze, przekazanie, publikacja, zamknięcie) jest tu
**rdzeniem**: robi wyłącznie ``flush``, nigdy ``commit``, a wszystko, co musi
iść PO commicie (wektor oferty, migawka dopasowań, auto-match w tle, WebSocket,
Targ), odkłada do :class:`PostCommit`. Trasy w ``api/jobs.py`` wołają rdzeń,
commitują i dopiero wtedy uruchamiają efekty — więc dotychczasowe trasy
zachowują się jak przedtem, a ``POST /api/jobs`` składa kilka rdzeni w jedną
transakcję: odmowa bramki (422) cofa wszystko (``get_db`` robi rollback na
każdy wyjątek).

Kolejność blokad wszędzie ta sama: ``allocation_lock`` → wiersz rekrutacji
``FOR UPDATE`` (jak ``/owner`` i przebieg automatu przydziału).

Pomocniki tras (walidacja właścicieli, ekstrakcja „train name”, odbiorcy
powiadomień Championa) zostają w ``api/jobs.py`` i są czytane leniwie przez
:func:`_api` — moduł tras importuje ten moduł na starcie, więc import w drugą
stronę na poziomie modułu byłby cykliczny. Czytanie przez atrybut modułu
zostawia też w mocy ``monkeypatch`` testów na ``app.api.jobs``.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_invalidate
from app.core.config import settings
from app.models.activity import Activity
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services import champion_view
from app.services.job_readiness import (
    handoff_blocker_codes,
    job_handoff_blocker_items,
    new_handoff_blockers,
)

logger = logging.getLogger(__name__)

Step = Callable[[], Awaitable[Any]]


def _api():
    from app.api import jobs  # noqa: PLC0415 — cykl: api.jobs importuje ten moduł

    return jobs


# ── Efekty po commicie ────────────────────────────────────────────────────────


class PostCommit:
    """Kroki do wykonania PO commicie transakcji, w kolejności dodania.

    ``add`` — krok wykonywany przez :func:`run_post_commit` (wynik ląduje
    w ``results[name]``). ``later`` — zadanie w tle (``BackgroundTasks``
    żądania); bez ``background_tasks`` wykonywane jak zwykły krok.
    """

    def __init__(self, background_tasks: Any = None) -> None:
        self.background_tasks = background_tasks
        self._steps: list[tuple[str, Step]] = []
        self.results: dict[str, Any] = {}

    def add(self, name: str, step: Step) -> None:
        self._steps.append((name, step))

    def later(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if self.background_tasks is not None:
            self.background_tasks.add_task(fn, *args, **kwargs)
            return

        async def _run() -> Any:
            result = fn(*args, **kwargs)
            if hasattr(result, "__await__"):
                return await result
            return result

        self._steps.append((getattr(fn, "__name__", "task"), _run))


async def run_post_commit(effects: PostCommit) -> PostCommit:
    """Wykonaj efekty — każdy osobno; awaria jednego trafia do logu i nie
    zatrzymuje kolejnych ani nie cofa już zatwierdzonego zapisu."""
    index = 0
    while index < len(effects._steps):
        name, step = effects._steps[index]
        index += 1
        try:
            effects.results[name] = await step()
        except Exception:  # noqa: BLE001 — efekt po commicie nigdy nie wywraca zapisu
            logger.exception(
                "[job_lifecycle] efekt po commicie nie powiódł się: %s", name
            )
    return effects


# ── Bramka i ochrona przed nowym brakiem ──────────────────────────────────────

MSG_NOT_CREATED = "Rekrutacja nie powstała — uzupełnij braki."
MSG_NOT_REOPENED = "Rekrutacji nie da się otworzyć — uzupełnij braki."
MSG_REGRESSION = (
    "Tej zmiany nie da się zapisać — rekrutacja jest w pracy, a zapis "
    "zostawiłby brak, którego wcześniej nie było."
)


def ensure_handoff_ready(
    job: Job, *, message: str = MSG_NOT_CREATED, include_open: bool = False
) -> None:
    """422 ``job_not_ready`` z listą braków ``[{code, message}]``.

    Bramka jest ta sama co przy „Przekaż do searchu”
    (``job_handoff_blocker_items``) plus twarda walidacja Championa
    (``enforce_operation``) — ta druga jest podzbiorem pierwszej, ale zostaje
    jako bezpiecznik zgodności z ręcznym przekazaniem.
    """
    items = job_handoff_blocker_items(job, include_open=include_open)
    if items:
        raise HTTPException(
            status_code=422,
            detail={"code": "job_not_ready", "message": message, "blockers": items},
        )
    from app.services.champion_intake import enforce_operation

    enforce_operation(job, "handoff")


def regression_baseline(job: Job) -> Optional[set[str]]:
    """Kody braków PRZED zapisem — tylko dla rekrutacji w pracy (``published``).

    Szkic i zamknięta rekrutacja nie są chronione: szkic jest dokańczany,
    a zamknięta przechodzi bramkę przy ponownym otwarciu.
    """
    if job.status != JobStatus.published:
        return None
    return handoff_blocker_codes(job)


def assert_no_new_handoff_blockers(before: Optional[set[str]], job: Job) -> None:
    """Zapis rekrutacji w pracy odmawia 422 WYŁĄCZNIE przy nowym braku.

    Porównanie po KODACH (zdania braków Championa niosą wartości). Brak, który
    był już przed zapisem, nie blokuje — stare rekrutacje bez terminu albo
    hiring managera dalej da się redagować.
    """
    if before is None or job.status != JobStatus.published:
        return
    added = new_handoff_blockers(before, job)
    if added:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "handoff_regression",
                "message": MSG_REGRESSION,
                "blockers": added,
            },
        )


def clear_decision_flags(job: Job) -> None:
    """Zapisana wartość zdejmuje „Klient nie podał” (0415)."""
    if job.hiring_manager_contact_id is not None:
        job.hiring_manager_not_provided = False
    if job.deadline is not None:
        job.deadline_not_provided = False


# ── Założenie rekrutacji ──────────────────────────────────────────────────────

# Pola ``JobCreate``, które nie są kolumnami ``jobs`` — każde ma własny krok.
_CREATE_EXCLUDED_FIELDS = {
    "auto_suggest_cc",
    "secondary_cc_ids",
    "from_job_id",
    "copy_questions",
    "champion_profile",
    "hiring_manager",
    "handoff",
    "similar_job_ids",
    "cc_override",
    "intake_form_id",
}


async def create_job_core(
    db: AsyncSession, data: Any, current_user: User, effects: PostCommit
) -> Job:
    """Wiersz rekrutacji (szkic w obrębie transakcji) — bez commitu.

    Logika z dawnego ``create_job``: kopia z szablonu, właściciele z przypisań
    klienta, numer referencyjny, tytuł dla rekrutera, kategorie poboczne,
    pytania z szablonu i wpis w historii. Uczestnicy kategorii
    (``sync_cc_participants``) w savepoincie tej samej transakcji. Wektor
    oferty, klasyfikator kategorii (tylko gdy jej brak), Targ i podobne
    rekrutacje — po commicie.
    """
    from app.api.recruitment_access import delivery_lead_job_pairs
    from app.api.clients_team import TAC_ASSIGNABLE_ROLES
    from app.services.auto_assign_owners import resolve_default_owners
    from app.services.client_access import assert_client_assignable

    api = _api()
    api._assert_delivery_lead_finance_write(data.model_fields_set, current_user)
    # Runda 7 (R7-X5-4): rekrutacja u usuniętego albo scalonego klienta nie
    # trafiłaby do żadnego rejestru.
    await assert_client_assignable(db, data.client_id)
    delivery_lead_pairs = await delivery_lead_job_pairs(current_user, db)

    payload = data.model_dump(exclude=_CREATE_EXCLUDED_FIELDS)
    secondary_cc_ids = data.secondary_cc_ids or []
    auto_suggest = data.auto_suggest_cc
    api._normalize_deadline_time(payload, None)
    if payload.get("deadline") is not None:
        payload["deadline_not_provided"] = False

    # "Skopiuj jako template" — dociąg pól z source jobu zanim wstawimy nowy.
    # Pola, które caller już wpisał w formularzu, mają precedencję (sprawdzamy
    # `not payload.get(field)` — `None`, pusty string, pusta lista wszystkie
    # liczą się jako "brak"). `champion_profile` kopiujemy TYLKO gdy nowy
    # request jest u tego samego klienta — championship to charakterystyka
    # kandydata u konkretnego klienta. Profil z żądania nakłada się na kopię
    # w kroku zapisu Championa (`save_champion_core`).
    src_job: Optional[Job] = None
    if data.from_job_id is not None:
        src_job = (
            await db.execute(select(Job).where(Job.id == data.from_job_id))
        ).scalar_one_or_none()
        if src_job is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"from_job_id: source job {data.from_job_id} not found",
            )
        api._assert_delivery_lead_job_visible(src_job, delivery_lead_pairs)
        copy_fields = (
            "description",
            "requirements",
            "must_skills",
            "nice_skills",
            "train_name",
            "seniority",
            "subcategory",
            "industry",
            "headcount",
            "work_mode",
            "remote_policy",
            "salary_min",
            "salary_max",
        )
        for field in copy_fields:
            if not payload.get(field):
                value = getattr(src_job, field, None)
                if isinstance(value, list):
                    payload[field] = list(value)
                elif isinstance(value, dict):
                    payload[field] = dict(value)
                else:
                    payload[field] = value
        same_client = payload.get("client_id") == src_job.client_id
        if same_client and src_job.champion_profile:
            payload["champion_profile"] = dict(src_job.champion_profile)

    if data.from_job_id is not None and not api._may_write_salary_range(current_user):
        # A template must not become a side channel for copying recruitment
        # budget fields into a role created by someone who may not set them.
        payload["salary_min"] = None
        payload["salary_max"] = None

    api._normalize_office_days_for_create(payload)

    if payload.get("champion_profile"):
        # Kopia z szablonu idzie AS STORED (`copy_profile`) — ponowny odczyt
        # jako świeży dokument dawał nowej rekrutacji pusty budżet, gdy
        # gramatyka nie umiała przeczytać zapisanego tekstu stawki.
        from app.services.champion_intake import copy_profile

        payload["champion_profile"] = copy_profile(
            payload["champion_profile"], current_user.id
        )

    # Validate explicit owner overrides (tac_id / delivery_lead_id) before we
    # hit `resolve_default_owners`. Override always wins, but only when it
    # points to a real active user with an allowed role.
    if data.tac_id is not None:
        await api._validate_owner_override(
            db,
            user_id=data.tac_id,
            allowed_roles=TAC_ASSIGNABLE_ROLES,
            field="tac_id",
        )
        await api._validate_tac_client_assignment(
            db,
            user_id=data.tac_id,
            client_id=payload["client_id"],
        )
    if data.delivery_lead_id is not None:
        await api._validate_owner_override(
            db,
            user_id=data.delivery_lead_id,
            allowed_roles={
                UserRole.delivery_lead,
                UserRole.admin,
                UserRole.head_of_recruitment,
            },
            field="delivery_lead_id",
        )
    # Runda 8 (R8-X1-3): prowadzący jak w „Przekaż do searchu” — nieistniejące
    # id dawało IntegrityError (500 bez CORS), a nieaktywne konto zostawało
    # „Prowadzi” przy osobie, której nie ma.
    if data.recruiter_id is not None:
        await api._validate_owner_override(
            db,
            user_id=data.recruiter_id,
            allowed_roles=set(api._HANDOFF_RECRUITER_ROLES),
            field="recruiter_id",
        )

    # Auto-assign from Client ↔ TAC/DL assignments when the caller left the
    # field empty. Override semantics: if caller supplied the value, we
    # never touch it here.
    if payload.get("tac_id") is None or payload.get("delivery_lead_id") is None:
        resolved = await resolve_default_owners(db, payload.get("client_id"))
        if payload.get("tac_id") is None:
            if resolved.tac_selection_required:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "TAC_OWNER_REQUIRED",
                        "message": (
                            "Client has multiple assigned TACs; choose the "
                            "request owner explicitly"
                        ),
                    },
                )
            payload["tac_id"] = resolved.tac_id
        if payload.get("delivery_lead_id") is None:
            payload["delivery_lead_id"] = resolved.delivery_lead_id
            # Główny DL klienta wpisany automatycznie — idzie za jego zmianą
            # (`job_delivery_lead_fill`, 0376).
            payload["delivery_lead_auto_filled"] = resolved.delivery_lead_id is not None

    # A Delivery Lead creating a recruitment without a resolved client-side
    # DL (no head DL assigned, or none at all) becomes its DL themselves —
    # otherwise the recruitment they just made would have no DL and never
    # show up in their own queue. Precedence: explicit `delivery_lead_id` >
    # the client's head DL (`resolve_default_owners` above) > the creator.
    # `recruiter_id` is untouched — this is about ownership, not authorship.
    if payload.get("delivery_lead_id") is None and current_user.has_role(
        UserRole.delivery_lead
    ):
        payload["delivery_lead_id"] = current_user.id

    if (
        delivery_lead_pairs is not None
        and (
            payload.get("client_id"),
            payload.get("tac_id"),
        )
        not in delivery_lead_pairs
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Job is outside the resolved Delivery Lead scope",
        )

    # Phase 15 / Phase D: auto-extract train_name if the caller didn't set it.
    # Best-effort — never blocks save. Regex + per-client dictionary.
    if not payload.get("train_name"):
        payload["train_name"] = await api._auto_extract_train_name(
            db=db,
            title=payload.get("title") or "",
            description=payload.get("description") or "",
            client_id=payload.get("client_id"),
        )

    # 0380: numer u klienta i tytuł dla rekrutera. Jawny tytuł = ręczny
    # (automat wyłączony); brak = składa go `job_working_title` niżej.
    from app.services.job_working_title import (
        normalize_client_reference,
        reference_from_title,
        refresh_working_title,
    )

    # 02.10.2026: numer klienta stoi w nazwie od klienta („… (ZOB 48213)”) —
    # bez pola w żądaniu bierzemy go z tytułu, żeby CV i Cpro go miały. Pole
    # wysłane puste to decyzja człowieka („To nie ten numer”): zostaje puste.
    payload["client_reference"] = normalize_client_reference(
        payload.get("client_reference")
    )
    if "client_reference" not in data.model_fields_set:
        payload["client_reference"] = reference_from_title(payload.get("title"))
    manual_working_title = (payload.get("working_title") or "").strip() or None
    payload["working_title"] = manual_working_title
    payload["working_title_auto"] = manual_working_title is None

    if payload.get("hiring_manager_contact_id") is not None:
        from app.services.job_hiring_manager import assert_contact_of_client

        await assert_contact_of_client(
            db,
            contact_id=payload["hiring_manager_contact_id"],
            client_id=payload.get("client_id"),
        )
        payload["hiring_manager_not_provided"] = False
    await api._assert_job_references_valid(
        db,
        pipeline_template_id=payload.get("pipeline_template_id"),
        competence_category_id=payload.get("competence_category_id"),
        secondary_cc_ids=secondary_cc_ids,
        reference_number=payload.get("reference_number"),
    )

    # Szkic istnieje WYŁĄCZNIE w obrębie tej transakcji — publikuje go
    # `publish_core` na końcu tego samego żądania.
    job = Job(**payload, status=JobStatus.draft, created_by=current_user.id)

    # Per-client pipeline template auto-pick (Traffit gap #1). If caller
    # didn't pin one explicitly, prefer a non-archived template tied to
    # this job's client; fall back to the global is_default template.
    if job.pipeline_template_id is None:
        from app.models.pipeline_template import PipelineTemplate

        chosen_template_id: Optional[int] = None
        if job.client_id is not None:
            chosen_template_id = await db.scalar(
                select(PipelineTemplate.id)
                .where(
                    PipelineTemplate.client_id == job.client_id,
                    PipelineTemplate.archived.is_(False),
                )
                .order_by(
                    PipelineTemplate.is_default.desc(), PipelineTemplate.id.desc()
                )
                .limit(1)
            )
        if chosen_template_id is None:
            chosen_template_id = await db.scalar(
                select(PipelineTemplate.id)
                .where(
                    PipelineTemplate.is_default.is_(True),
                    PipelineTemplate.archived.is_(False),
                )
                .limit(1)
            )
        if chosen_template_id is not None:
            job.pipeline_template_id = chosen_template_id

    db.add(job)
    await db.flush()

    await refresh_working_title(db, job)

    # Auto-generate a human-readable reference number (Traffit parity) when
    # the caller didn't supply one. Done post-flush so we have the persisted
    # client_id; the UNIQUE constraint backstops concurrent creates.
    if not job.reference_number:
        from app.core.scheduling import business_today
        from app.services.job_reference import generate_job_reference_number

        # Rok numeru = rok kalendarza firmy (Europe/Warsaw).
        job.reference_number = await generate_job_reference_number(
            db,
            client_id=job.client_id,
            year=business_today().year,
        )

    if secondary_cc_ids:
        from app.models.cc_feedback import JobSecondaryCc

        for cc_id in secondary_cc_ids[:2]:  # cap at 2
            db.add(JobSecondaryCc(job_id=job.id, competence_category_id=cc_id))

    activity_action = "created"
    activity_details: Optional[dict] = None
    if src_job is not None:
        activity_action = "created_from_template"
        activity_details = {"source_job_id": src_job.id}
        # Bez archiwum rozmów (0383): przypięte pytanie wchodzi do oceny prepu
        # — kopia hurtem dałaby każdemu prepowi nowej rekrutacji ocenę „słaby”.
        if data.copy_questions:
            from app.models.interview_question import (
                InterviewQuestion,
                InterviewQuestionSource,
                JobQuestion,
            )

            existing_links = (
                await db.execute(
                    select(
                        JobQuestion.question_id,
                        JobQuestion.is_pinned,
                        JobQuestion.added_by_source,
                        JobQuestion.order_index,
                    )
                    .join(
                        InterviewQuestion,
                        InterviewQuestion.id == JobQuestion.question_id,
                    )
                    .where(
                        JobQuestion.job_id == src_job.id,
                        InterviewQuestion.source
                        != InterviewQuestionSource.legacy_import,
                    )
                )
            ).all()
            for question_id, is_pinned, added_by_source, order_index in existing_links:
                db.add(
                    JobQuestion(
                        job_id=job.id,
                        question_id=question_id,
                        is_pinned=is_pinned,
                        added_by_source=added_by_source,
                        order_index=order_index,
                        added_by_user_id=current_user.id,
                    )
                )

    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action=activity_action,
            user_id=current_user.id,
            details=activity_details,
        )
    )

    # Uczestnicy = wszystkie osoby kategorii (1. i 2. priorytet), w tej samej
    # transakcji. Savepoint: błąd synchronizacji nie zrywa transakcji —
    # listę wyrówna pętla godzinowa.
    if job.competence_category_id is not None:
        await _sync_participants_safely(db, job.id, current_user.id)

    job_id = job.id
    actor_id = current_user.id

    # Wektor oferty — odwrotne dopasowanie (kandydat → rekrutacje).
    effects.add("embed", lambda: api._maybe_embed_job(job_id, db))

    # Klasyfikator kategorii ma własny commit — tylko jako efekt po commicie
    # i tylko bez kategorii (w przepływie bez szkiców kategoria jest zawsze).
    if job.competence_category_id is None and auto_suggest:
        effects.add(
            "classify_cc", lambda: _classify_cc_after_commit(db, job_id, actor_id)
        )

    # Targ kandydatów (0052-0054) i powiadomienia o podobnych rekrutacjach.
    if settings.MARKETPLACE_ENABLED:
        from app.services.marketplace_service import run_marketplace_scan_safe

        effects.later(run_marketplace_scan_safe, job_id)
    if settings.SIMILAR_JOB_NOTIFY_ENABLED:
        from app.services.similar_job_notify import run_similar_job_notify_safe

        effects.later(run_similar_job_notify_safe, job_id)
    return job


async def _sync_participants_safely(
    db: AsyncSession, job_id: int, actor_id: int
) -> None:
    from app.services.auto_cc_collaborators import sync_cc_participants

    try:
        async with db.begin_nested():
            await sync_cc_participants(db, job_ids=[job_id], added_by=actor_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "[Job] synchronizacja uczestników kategorii nie powiodła się (job %s)",
            job_id,
        )


async def _classify_cc_after_commit(
    db: AsyncSession, job_id: int, actor_id: int
) -> None:
    from app.services.job_cc import resolve_job_cc_id

    job = await db.get(Job, job_id)
    if job is None or job.competence_category_id is not None:
        return
    cc_id = await resolve_job_cc_id(job, db)
    if cc_id is None:
        return
    job.competence_category_id = cc_id
    await _sync_participants_safely(db, job_id, actor_id)
    await db.commit()


# ── Hiring manager ────────────────────────────────────────────────────────────


async def apply_hiring_manager_decision(
    db: AsyncSession, job: Job, decision: Any, current_user: User
) -> dict:
    """Kontakt z listy, nowa osoba, „Klient nie podał” albo wyczyszczenie.

    ``decision`` ma pola ``contact_id``/``new_person``/``not_provided`` (oraz
    opcjonalnie ``clear``) — dokładnie jedno ustawione (walidator schematu).
    Nową osobę zakłada ``find_or_create_contact`` jako kontakt KLIENTA tej
    rekrutacji. Zmiana HM, którego weto niosą pary, wymaga admina albo HoR.
    """
    from app.services.job_hiring_manager import (
        assert_contact_of_client,
        find_or_create_contact,
    )

    previous = job.hiring_manager_contact_id
    previous_flag = bool(job.hiring_manager_not_provided)
    created = False
    not_provided = bool(getattr(decision, "not_provided", False))
    if not_provided or getattr(decision, "clear", False):
        contact_id = None
    elif decision.contact_id is not None:
        contact = await assert_contact_of_client(
            db, contact_id=decision.contact_id, client_id=job.client_id
        )
        contact_id = contact.id
    else:
        person = decision.new_person
        assert person is not None  # walidator schematu: dokładnie jedno
        resolved = await find_or_create_contact(
            db,
            client_id=job.client_id,
            name=person.name,
            position=person.position,
            email=str(person.email) if person.email else None,
            actor_id=current_user.id,
            job_id=job.id,
        )
        contact_id, created = resolved.contact.id, resolved.created

    if contact_id != previous:
        await _api()._assert_may_change_vetoing_manager(
            db, current_user, job_id=job.id, previous=previous
        )
        job.hiring_manager_contact_id = contact_id
    job.hiring_manager_not_provided = not_provided and contact_id is None
    changed = contact_id != previous or job.hiring_manager_not_provided != previous_flag
    if changed:
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action="hiring_manager_changed",
                user_id=current_user.id,
                details={
                    "previous": previous,
                    "contact_id": contact_id,
                    "contact_created": created,
                    "not_provided": job.hiring_manager_not_provided,
                },
            )
        )
    return {
        "previous": previous,
        "contact_id": contact_id,
        "created": created,
        "changed": changed,
    }


# ── Profil Championa ──────────────────────────────────────────────────────────


async def save_champion_core(
    db: AsyncSession,
    job: Job,
    payload: Optional[dict],
    current_user: User,
    effects: PostCommit,
    *,
    imported: bool = False,
    expected_fingerprint: Optional[str] = None,
    sync_fields: Optional[list[str]] = None,
    notify: bool = True,
) -> dict:
    """Upsert Profilu Championa na zablokowanym wierszu — bez commitu.

    Logika z dawnego ``_save_champion_profile``. Przy zmianie treści
    powiadamia zespół rekrutacji (``notify``; przy zakładaniu rekrutacji
    pomijane — nowa rekrutacja nie ma jeszcze kogo informować o „zmianie”).
    Przeliczenie dopasowań, auto-match i WebSocket — po commicie.

    Rekrutacja w pracy (``published``) jest chroniona przed nowym brakiem
    (``assert_no_new_handoff_blockers``) na obu ścieżkach zapisu.
    """
    from app.api.champion_intake import invalid_champion_profile
    from app.api.recruitment_access import ensure_champion_job_editor
    from app.schemas.champion import ChampionProfile
    from app.services.champion_intake import (
        fingerprint,
        response_context,
        sync_selected_rubrics,
        sync_skill_column,
        user_edit,
    )
    from app.services.champion_job_sync import (
        fill_job_columns_from_champion,
        overwrite_edited_job_columns,
    )
    from app.services.champion_profile_events import (
        diff_champion_profile,
        summarize_sections,
    )
    from app.services.champion_requirement_rows import expand_patch
    from app.services.job_matching_refresh import refresh_job_matching
    from app.services.job_working_title import refresh_working_title
    from app.services.requirement_contract import apply_requirement_source_update

    api = _api()
    await api._ensure_delivery_lead_job_visible(job, current_user, db)
    # Champion redaguje DL/admin oraz osoba prowadząca rekrutację i jej
    # współpracownicy (decyzja 22.09.2026); TAC tylko we własnych ofertach.
    await ensure_champion_job_editor(job, current_user, db)

    if expected_fingerprint is not None and fingerprint(job) != expected_fingerprint:
        logger.info("champion_import_conflict job_id=%s", job.id)
        raise HTTPException(
            409,
            {
                "message": "Rekrutacja zmieniła się. Sprawdź aktualne różnice.",
                "champion_profile": api._champion_response(job.champion_profile),
                **response_context(job),
            },
        )
    baseline = regression_baseline(job)
    old_profile = dict(job.champion_profile or {})
    normalized_old = ChampionProfile.model_validate(old_profile).model_dump(mode="json")

    # Wiersze wymagań (02.10.2026): `stack.rows` jest źródłem, a `must`,
    # `nice`, `critical` i `search.requirements` wyprowadza serwer.
    payload = expand_patch(payload)
    try:
        new_profile = user_edit(
            old_profile,
            payload or {},
            current_user.id,
            imported=imported,
            actor_name=(current_user.name or "").strip() or current_user.email,
        )
        profile = ChampionProfile.model_validate(new_profile)
    except (ValueError, TypeError, AttributeError) as exc:
        raise invalid_champion_profile(exc) from exc
    # Explicit reconciliation can change recruitment columns even when the
    # profile text stays the same; an empty selection performs no writes.
    sync_selected_rubrics(job, new_profile, sync_fields or [])

    # Sekcja 3 „Stack technologiczny” ma odpowiednik w KOLUMNACH oferty, które
    # czyta scoring, `requirement_map` i filtry wyszukiwarki.
    stack_must = [{"name": item.name, "level": None} for item in profile.stack.must]
    stack_nice = [{"name": item.name, "level": None} for item in profile.stack.nice]
    matching_columns_before = deepcopy(
        (job.must_skills, job.nice_skills, job.matching_requirements)
    )
    # Synchronizujemy, gdy edytor PRZYSŁAŁ sekcję `stack` — także pustą.
    patch_stack = (payload or {}).get("stack")
    if isinstance(patch_stack, dict) and patch_stack.get("critical"):
        # Krytyczne wybiera się z MUST i tylko spośród technologii ze słownika
        # (30.09.2026) — zły wybór = 422 po polsku, nic się nie zapisuje.
        from app.services.critical_skills import critical_errors
        from app.services.scoring_service import job_explicit_must_skills

        must_names = [item.name for item in profile.stack.must] or list(
            job_explicit_must_skills(job)
        )
        errors = critical_errors(profile.stack.critical or [], must_names)
        if errors:
            raise HTTPException(422, errors[0][1])
    if "stack" in (payload or {}):
        # Sam wybór krytycznych nie zmienia kolumn MUST/NICE rekrutacji.
        stack_changed = champion_view.without_critical(
            normalized_old["stack"]
        ) != champion_view.without_critical(new_profile["stack"])
        for key, items, column in (
            ("must", stack_must, "must_skills"),
            ("nice", stack_nice, "nice_skills"),
        ):
            empty_unreviewed = (
                getattr(job, column) is None and job.matching_requirements is None
            )
            if (
                (not imported and stack_changed)
                or empty_unreviewed
                or key in (sync_fields or [])
            ):
                sync_skill_column(job, key, items)

    # Sekcja 1 „Podstawowe informacje” → kolumny oferty (FILL_EMPTY), a pole
    # ZMIENIONE ręcznie w tym zapisie nadpisuje kolumnę (30.09.2026).
    columns_filled = (
        []
        if imported
        else overwrite_edited_job_columns(
            job, normalized_old.get("basics") or {}, new_profile.get("basics") or {}
        )
    )
    columns_filled += fill_job_columns_from_champion(job, profile.basics.model_dump())

    fields_changed = diff_champion_profile(normalized_old, new_profile)
    intake_changed = normalized_old.get("intake") != new_profile.get("intake")
    # Zapis, który nie zmienia WYMAGAŃ roli, nie przelicza dopasowań i nie
    # budzi automatów (runda 3 audytu 25.09.2026).
    requirements_unchanged = (
        not imported
        and bool(fields_changed)
        and not intake_changed
        and not columns_filled
        and not sync_fields
        and deepcopy((job.must_skills, job.nice_skills, job.matching_requirements))
        == matching_columns_before
        and champion_view.requirement_source(
            normalized_old, ignored=champion_view.RANKING_IGNORED_KEYS
        )
        == champion_view.requirement_source(
            new_profile, ignored=champion_view.RANKING_IGNORED_KEYS
        )
    )
    job_id = job.id
    if not fields_changed and not imported and old_profile and not intake_changed:
        # Brak zmiany TREŚCI profilu nie znaczy brak zmiany dla silnika
        # matchingu: `columns_filled`/synchronizacja stacku żyją na `job`.
        await refresh_working_title(db, job)
        clear_decision_flags(job)
        assert_no_new_handoff_blockers(baseline, job)
        if columns_filled or sync_fields or "stack" in (payload or {}):
            effects.add("refresh_matching", lambda: refresh_job_matching(job_id, db))
        return {
            "job_id": job.id,
            "champion_profile": api._champion_response(job.champion_profile),
            **response_context(job),
        }

    apply_requirement_source_update(job, "champion_profile", new_profile)
    # 0380: tytuł dla rekrutera idzie za Championem, dopóki nikt go nie zmienił.
    await refresh_working_title(db, job)
    clear_decision_flags(job)
    assert_no_new_handoff_blockers(baseline, job)
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="champion_profile_updated",
            user_id=current_user.id,
        )
    )

    editor_name = (current_user.name or "Ktoś").strip() or "Ktoś"
    sections_pl = summarize_sections(fields_changed)
    title = "Profil Championa zaktualizowany"
    message_text = (
        f"{editor_name} zmienił {sections_pl} dla: {job.title}"
        if sections_pl
        else f"{editor_name} zaktualizował profil dla: {job.title}"
    )
    # Front zna zakładkę `champion`; `champion-profile` zostaje jako alias.
    link = f"/jobs/{job_id}?tab=champion"
    recipients: list[int] = []
    if notify:
        from app.api.notifications import create_notification

        recipients = await api._champion_profile_recipients(
            db, job, exclude_user_id=current_user.id, link=link
        )
        for recipient_id in recipients:
            await create_notification(
                db=db,
                user_id=recipient_id,
                title=title,
                message=message_text,
                notification_type=NotificationType.champion_profile_updated,
                link=link,
                related_entity_type="job",
                related_entity_id=job_id,
                dedupe_resurface=True,
            )

    # P0-A: edycja Championa zmienia wektor i wagi scoringu — przeliczenie,
    # żeby praca DL-a dotarła do rankingu rekrutera.
    if not requirements_unchanged:
        effects.add("refresh_matching", lambda: refresh_job_matching(job_id, db))
    # Opublikowana rekrutacja wraca do auto-matchu i nocnego przeglądu bazy
    # (21.09.2026). Własna sesja, nigdy nie rzuca.
    if job.status == JobStatus.published and not requirements_unchanged:
        from app.services.auto_match_outbox import enqueue_job_safe

        effects.add("enqueue_auto_match", lambda: enqueue_job_safe(job_id))

    if recipients:
        effects.add(
            "champion_ws",
            lambda: _notify_champion_ws(
                recipients,
                job_id=job_id,
                title=title,
                message_text=message_text,
                link=link,
                editor_id=current_user.id,
                editor_name=editor_name,
                fields_changed=fields_changed,
            ),
        )

    return {
        "job_id": job_id,
        "champion_profile": api._champion_response(job.champion_profile),
        **response_context(job),
    }


async def _notify_champion_ws(
    recipients: list[int],
    *,
    job_id: int,
    title: str,
    message_text: str,
    link: str,
    editor_id: int,
    editor_name: str,
    fields_changed: Any,
) -> None:
    from app.api.ws import manager as ws_manager

    now_iso = datetime.now(timezone.utc).isoformat()
    bell_event = {
        "type": "notification",
        "data": {
            "title": title,
            "message": message_text,
            "link": link,
            "notification_type": NotificationType.champion_profile_updated.value,
            "related_entity_type": "job",
            "related_entity_id": job_id,
            "created_at": now_iso,
        },
    }
    live_event = {
        "type": "champion_profile_changed",
        "data": {
            "job_id": job_id,
            "updated_by_user_id": editor_id,
            "updated_by_name": editor_name,
            "updated_at": now_iso,
            "fields_changed": fields_changed,
        },
    }
    for recipient_id in recipients:
        try:
            await ws_manager.notify_user(recipient_id, bell_event)
            await ws_manager.notify_user(recipient_id, live_event)
        except Exception as e:  # pragma: no cover — WS push nigdy nie psuje zapisu
            logger.warning(
                "[Champion Profile] WS notify failed user=%s job=%s: %s",
                recipient_id,
                job_id,
                e,
            )


# ── Przekazanie do searchu ────────────────────────────────────────────────────


async def handoff_core(
    db: AsyncSession,
    job: Job,
    payload: Any,
    current_user: User,
    effects: PostCommit,
) -> dict:
    """„Przekaż do searchu” — bez commitu; bramkę braków sprawdza wołający.

    Wołający trzyma ``allocation_lock`` i blokadę wiersza rekrutacji. Migawka
    dopasowań powstaje po commicie (wynik w ``effects.results["snapshot_id"]``).
    """
    from app.models.recruitment_priority import PriorityChannel
    from app.services.recruitment_allocation import assign_operator
    from app.services.request_work_state import set_work_state

    api = _api()
    # Don't start a search for a closed recruitment — the ranking would be wasted
    # work on a job nobody is filling (PR #1036 review follow-up).
    if job.status == JobStatus.closed:
        raise HTTPException(
            status_code=409,
            detail="Rekrutacja jest zamknięta — nie można jej przekazać do searchu.",
        )

    top_k = payload.top_k or settings.MATCH_MAX_RESULTS
    job_id = job.id
    actor_id = current_user.id
    effects.add(
        "snapshot_id",
        lambda: _queue_handoff_ranking(
            job_id, top_k=top_k, created_by=actor_id, effects=effects
        ),
    )
    if payload.assignment_mode == "automatic":
        if not settings.RECRUITMENT_ALLOCATION_ENABLED:
            raise HTTPException(409, "Automatyczny przydział nie jest jeszcze włączony")
        # Tryb `off`: pętla nikogo nie zaproponuje ani nie przydzieli, więc
        # request stałby w „Szukamy” bez rekrutera i bez sygnału dla kogokolwiek.
        if await api._allocation_mode(db) == "off":
            raise HTTPException(
                409,
                "Automat przydziału jest wyłączony — wybierz rekrutera ręcznie.",
            )
        if job.recruiter_id is not None:
            raise HTTPException(409, "Rekrutacja ma już rekrutera; zmień go ręcznie")
        job.is_open = True
        job.needs_sourcing = True
        job.favorite_sourcing_paused = False
        # 0371: przydział robi automat na „Szukamy kandydatów”.
        await set_work_state(db, job, "searching", actor_id=actor_id, reason="handoff")
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="handed_off_to_search",
                user_id=actor_id,
                details={"assignment_mode": "automatic"},
            )
        )
        return {
            "status": "queued",
            "job_id": job_id,
            "recruiter_id": None,
            "allocation_request_id": None,
        }
    if payload.recruiter_id is None:
        raise HTTPException(422, "Wybierz rekrutera albo przydział automatyczny")

    recruiter = await db.scalar(select(User).where(User.id == payload.recruiter_id))
    if recruiter is None or not recruiter.is_active:
        raise HTTPException(
            status_code=422,
            detail="Wybrany rekruter nie istnieje lub jest nieaktywny.",
        )
    if not recruiter.has_any_role(*api._HANDOFF_RECRUITER_ROLES):
        raise HTTPException(
            status_code=422,
            detail="Wybrany użytkownik nie może prowadzić rekrutacji.",
        )

    previous_owner_id = job.recruiter_id
    await assign_operator(
        db,
        job=job,
        assignee=recruiter,
        channel=PriorityChannel(payload.channel),
        actor_user_id=actor_id,
        source="manual_handoff",
        as_owner=True,
    )
    job.is_open = True
    job.needs_sourcing = True
    job.favorite_sourcing_paused = False
    await set_work_state(db, job, "searching", actor_id=actor_id, reason="handoff")
    # Ponowne przekazanie innej osobie zastępuje rekrutera jak `/owner`.
    await api._sync_work_assignments_with_owner(
        db,
        job=job,
        previous_owner_id=previous_owner_id,
        owner=recruiter,
        actor_id=actor_id,
    )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="handed_off_to_search",
            user_id=actor_id,
        )
    )
    # Osoba wskazana ręcznie dowiaduje się od razu (#2010, 04.10.2026) — także
    # przy tworzeniu rekrutacji, które przekazuje ją w tej samej transakcji.
    # Bez dzwonka dla siebie i przy ponowieniu przekazania tej samej osobie.
    # `notify_assigned` pracuje w savepoincie i nie robi commita.
    if recruiter.id not in (actor_id, previous_owner_id):
        from app.models.client import Client  # noqa: PLC0415
        from app.services.job_working_title import display_title  # noqa: PLC0415
        from app.services.request_allocation_notices import (  # noqa: PLC0415
            notify_assigned,
        )

        client_name = (
            await db.scalar(select(Client.name).where(Client.id == job.client_id))
            if job.client_id is not None
            else None
        )
        await notify_assigned(
            db,
            job_id=job_id,
            title=display_title(job),
            client_name=client_name,
            user_id=recruiter.id,
        )
    return {"status": "handed_off", "job_id": job_id, "recruiter_id": recruiter.id}


async def _queue_handoff_ranking(
    job_id: int, *, top_k: int, created_by: int, effects: PostCommit
) -> int:
    """Migawka dopasowań po przekazaniu do searchu — liczona w tle."""
    from app.models.proposal_snapshot import SOURCE_HANDOFF
    from app.tasks.compute_proposals import (
        compute_proposal_for_job,
        create_pending_snapshot,
    )

    snapshot_id = await create_pending_snapshot(
        job_id, top_k=top_k, source=SOURCE_HANDOFF, created_by=created_by
    )
    effects.later(compute_proposal_for_job, snapshot_id, job_id, top_k=top_k)
    return snapshot_id


# ── Publikacja i ponowne otwarcie ─────────────────────────────────────────────


async def publish_core(
    db: AsyncSession,
    job: Job,
    current_user: User,
    effects: PostCommit,
    *,
    reason: Optional[str] = None,
    sync_status_payload: bool = True,
) -> bool:
    """Status ``published`` (i ponowne otwarcie zamkniętej) — bez commitu.

    Zwraca, czy status się zmienił. Zamknięta rekrutacja wraca do „Do
    przejrzenia” (lustro zamknięcia) i — jeśli pochodzi z Traffita — do NEXUSA.
    ``sync_status_payload=False`` przy zakładaniu: punktu oferty w Qdrancie
    jeszcze nie ma, status wpisze do niego pierwszy embed (efekt ``embed``).
    """
    from app.services.auto_match_outbox import enqueue_job
    from app.services.client_access import assert_client_assignable
    from app.services.request_work_state import (
        WORK_STATE_FINISHED,
        WORK_STATE_REOPENED,
        set_work_state,
    )

    api = _api()
    status_changes = job.status != JobStatus.published
    reopened = job.status == JobStatus.closed
    if reopened:
        # Runda 9 (R9-N4-1): jak PATCH — klient usunięty/scalony = 422.
        await assert_client_assignable(db, job.client_id)
        job.closed_at = None
        api._take_over_reopened_traffit_job(db, job, current_user)
        if job.work_state == WORK_STATE_FINISHED:
            await set_work_state(
                db,
                job,
                WORK_STATE_REOPENED,
                actor_id=current_user.id,
                reason="job_reopened",
            )
    job.status = JobStatus.published
    details: Optional[dict] = None
    if reopened or reason:
        details = {"reopened": reopened}
        if reason:
            details["reason"] = reason
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="published",
            user_id=current_user.id,
            details=details,
        )
    )
    await enqueue_job(db, job_id=job.id, trigger="job_publish")
    if status_changes and sync_status_payload:
        effects.add("status_payload", lambda: api._sync_job_status_payload(job))
        if reopened:
            effects.add("reports_cache", lambda: cache_invalidate("reports:clients"))
    return status_changes


# ── Zamknięcie ────────────────────────────────────────────────────────────────


async def close_job_core(
    db: AsyncSession,
    job: Job,
    *,
    reason: JobCloseReason,
    notes: Optional[str],
    actor_id: Optional[int],
    effects: PostCommit,
) -> None:
    """Zamknięcie z powodem — bez commitu; wołający trzyma blokadę wiersza.

    Atomically: status → closed, closed_at = now, close_reason + close_notes.
    Zamknięta rekrutacja nie jest przez nikogo prowadzona (``is_open``),
    jest „Zakończona” w porządku requestów i zamyka ogłoszenia na portalach.
    """
    from app.services.candidate_contact_hooks import (
        maybe_close_job_contact_opportunities,
    )
    from app.services.job_portals.service import close_live_postings
    from app.services.request_work_state import set_work_state

    api = _api()
    job.status = JobStatus.closed
    job.closed_at = datetime.now(timezone.utc)
    job.is_open = False
    job.close_reason = reason
    job.close_notes = notes
    await set_work_state(db, job, "finished", actor_id=actor_id, reason="job_closed")
    await close_live_postings(db, job.id)
    await maybe_close_job_contact_opportunities(
        db,
        job_id=job.id,
        actor_user_id=actor_id,
        reason="job_closed",
        occurred_at=job.closed_at,
    )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="closed",
            user_id=actor_id,
            details={"reason": reason.value, "notes": notes},
        )
    )
    effects.add("reports_cache", lambda: cache_invalidate("reports:clients"))
    effects.add("status_payload", lambda: api._sync_job_status_payload(job))


# ── Zakładanie: podobne rekrutacje, kategoria, formularz ──────────────────────


async def link_similar_on_create(
    db: AsyncSession, job: Job, job_ids: list[int], current_user: User
) -> None:
    """Rekrutacje wskazane jako podobne na ``/jobs/new`` — ta sama bramka
    dostępu co ``POST /jobs/{id}/similar`` (SEC-05: połączenie przepina osoby
    wysłane do klienta w OBU kierunkach)."""
    if not job_ids:
        return
    from app.api.job_similar import _other_jobs
    from app.services import job_similarity as sim

    wanted = await _other_jobs(db, current_user, job.id, list(job_ids))
    if not wanted:
        return
    _linked, reassigned = await sim.link_jobs(
        db, job.id, wanted, user_id=current_user.id
    )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="similar_jobs_linked",
            user_id=current_user.id,
            details={"job_ids": wanted, "reassigned": reassigned},
        )
    )


def record_cc_override(
    db: AsyncSession, job: Job, override: Any, current_user: User
) -> bool:
    """Zmieniona podpowiedź kategorii — tylko admin i Delivery Lead, jak trasa
    ``/cc-override`` (inaczej pomijane, więc macierz uprawnień się nie zmienia)."""
    if override is None or not current_user.has_any_role(
        UserRole.admin, UserRole.delivery_lead
    ):
        return False
    from app.models.cc_feedback import CcSuggestionOverride

    db.add(
        CcSuggestionOverride(
            job_id=job.id,
            suggested_cc_id=override.suggested_cc_id,
            final_cc_id=job.competence_category_id,
            suggested_score=override.suggested_score,
            user_id=current_user.id,
        )
    )
    return True


async def delete_intake_form(
    db: AsyncSession, form_id: Optional[int], user_id: int
) -> None:
    """Niedokończony formularz autora znika razem z utworzeniem rekrutacji —
    w tej samej transakcji (cudzy formularz: nic się nie dzieje)."""
    if form_id is None:
        return
    await db.execute(
        text("DELETE FROM job_intake_forms WHERE id = :id AND user_id = :uid"),
        {"id": form_id, "uid": user_id},
    )
