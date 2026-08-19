"""Central capability guards for the recruitment-pipeline module (M4 audit, PR-01).

P0.3 containment (audit ``docs/recruitment-pipeline-submission-placement-
module-audit-and-claude-implementation-plan-2026-07-16.md``): lifecycle
endpoints used bare ``CurrentUser`` (scorecard, screening notes, calendar,
interview feedback, rejection-email preview) so the read-only viewer/client
persona ``user`` could read candidate PII and mutate assessments, and the
``sourcer`` role could execute terminal moves (``hired``) and edit rates.

These dependencies replace bare ``CurrentUser``/too-wide guards on the
lifecycle routes. Mirrors ``candidate_access.py`` (M2 PR 1): every guard is
built on ``require_roles`` which evaluates the union of primary ``User.role``
and secondary ``User.roles`` via ``has_any_role``.

Capability → allowed roles:

- **read** (kanban, SLA overview, pipelines of a candidate, funnel/TTH
  reports, screening notes, calendar, feedback, rejection-email timeline) —
  all internal operational roles; ``user`` (viewer) excluded everywhere.
- **transition** (non-terminal stage moves) — parity with the existing
  ``RecruiterPlus`` contract (admin, delivery_lead, tac, recruiter, sourcer).
  Do not widen or narrow in a containment PR.
- **terminal transition** (``hired``/``rejected``/``withdrawn`` or a
  stage-def with terminal semantics) — sourcer intentionally excluded
  (audit P0.3: "terminalny hired nie ma ownership scope"; sourcing persona
  must not close recruitments).
- **rate edit** (candidate expected rate: PATCH expected-rate and the
  rate-bearing move to ``verified``) — admin, delivery_lead, tac, recruiter.
  Sourcer intentionally excluded (audit P0.3: expected rate używa zbyt
  szerokiego CandidateWriteAccess obejmującego sourcera).
- **assessment write** (scorecard answers, screening notes, interview
  feedback) — RecruiterPlus parity (prep-call screening is sourcer work);
  viewer excluded (was: bare ``CurrentUser``).
- **calendar write** — RecruiterPlus parity; viewer excluded (was: bare
  ``CurrentUser`` on create/update/delete/import).
- **rejection-email oversight** (read/cancel someone else's scheduled
  rejection email incl. recipient/subject/body/last_error) — admin,
  delivery_lead, head_of_recruitment; the owning recruiter always retains
  access to their own rows (checked in-endpoint, not here).

Resource scope for the *pipeline* surfaces is enforced by
``ensure_job_membership`` below (P1-PIPE-01). The role guards above answer
"may this persona touch the recruitment module at all?"; the membership gate
answers "may this persona touch *this job's* pipeline?". They compose: an
ingress runs the role dependency first (viewer excluded) and then the
membership check (non-members of the job excluded). Do NOT add a feature flag
that reverts any of these guards to plain ``CurrentUser`` or that disables the
membership gate.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import ColumnElement, and_, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import settings
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_priority import (
    PriorityMemberStatus,
    PriorityMode,
    PriorityPlanStatus,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityPlan,
    RecruitmentPriorityPlanMember,
    RecruitmentPriorityUserMode,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services.job_membership import is_member_of_job
from app.services.priority_work_policy import (
    combine_priority_modes,
    effective_priority_mode,
)

# ── Capability role sets ─────────────────────────────────────────────────────

# Everyone except the read-only viewer/client role `user`.
_INTERNAL_OPERATIONAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
    UserRole.sourcer,
)

RECRUITMENT_READ_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES

# Parity with deps.RecruiterPlus — the pre-existing move contract.
RECRUITMENT_TRANSITION_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
    UserRole.sourcer,
)

# Terminal lifecycle decisions (hired / rejected / withdrawn) — no sourcer.
# head_of_recruitment celowo NIEuwzględniony: route-level guard /move to
# RecruiterPlus (bez HoR), a containment nie poszerza dostępu — HoR w tym
# zbiorze byłby martwym wpisem sugerującym uprawnienie, którego nie ma.
RECRUITMENT_TERMINAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
)

# Candidate expected-rate edits (PATCH + rate-bearing `verified` move).
RECRUITMENT_RATE_EDIT_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
)

# Scorecards, screening notes, interview feedback.
RECRUITMENT_ASSESSMENT_WRITE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
    UserRole.sourcer,
)

CALENDAR_WRITE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
    UserRole.sourcer,
)

REJECTION_EMAIL_OVERSIGHT_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)


def user_can_terminal_transition(user: User) -> bool:
    """Non-raising check used inside /move where terminality is data-driven."""
    return user.has_any_role(*RECRUITMENT_TERMINAL_ROLES)


def user_can_edit_rates(user: User) -> bool:
    """Non-raising check for the rate-bearing move to `verified`."""
    return user.has_any_role(*RECRUITMENT_RATE_EDIT_ROLES)


def user_has_rejection_email_oversight(user: User) -> bool:
    """Multi-role-aware oversight check (fixes primary-role-only comparison)."""
    return user.has_any_role(*REJECTION_EMAIL_OVERSIGHT_ROLES)


# ── FastAPI dependencies ─────────────────────────────────────────────────────

# Read surfaces of the lifecycle module (viewer excluded).
RecruitmentReadAccess = Annotated[User, Depends(require_roles(*RECRUITMENT_READ_ROLES))]

# Candidate expected-rate mutations.
RecruitmentRateEditAccess = Annotated[
    User, Depends(require_roles(*RECRUITMENT_RATE_EDIT_ROLES))
]

# Scorecard / screening / feedback mutations.
RecruitmentAssessmentWriteAccess = Annotated[
    User, Depends(require_roles(*RECRUITMENT_ASSESSMENT_WRITE_ROLES))
]

# Calendar event mutations (create/update/delete/import/m365 invite).
CalendarWriteAccess = Annotated[User, Depends(require_roles(*CALENDAR_WRITE_ROLES))]


# ── Resource scope: job membership (P1-PIPE-01) ─────────────────────────────

# Oversight roles that see every job's pipeline regardless of membership.
# admin already short-circuits inside ``is_member_of_job``; head_of_recruitment
# is the recruitment-wide oversight persona and is added here so it is not
# forced onto every job's collaborator list.
_JOB_MEMBERSHIP_BYPASS_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
)


async def ensure_job_membership(db: AsyncSession, user: User, job_id: int) -> None:
    """Enforce that ``user`` may read/mutate ``job_id``'s pipeline.

    Fills the resource scope that the role guards above deliberately leave to a
    dedicated check (P1-PIPE-01): every pipeline ingress (kanban read, stage
    history, ``/move``, ``/bulk-move``, interview feedback) must confirm the
    caller belongs to the job before touching its pipeline. Membership =
    owner / delivery_lead / TAC / active collaborator per
    :func:`app.services.job_membership.is_member_of_job` (multi-role aware via
    ``has_any_role``), plus the oversight roles admin / head_of_recruitment.
    When Priority Work is active for this user, a current published assignment
    or ownership of an open carry-over process **that was opened in compliance
    with a published plan** also grants job scope. This is only resource access:
    the command policy still decides independently whether a new candidate/job
    pair may be opened.

    A non-member gets a uniform **403** at every ingress — the same status the
    sibling resource-scope guard ``require_dl_assigned_or_admin`` returns, so
    the module speaks one language for "authenticated but out of scope". 403
    (not 404) is chosen for consistency and because job existence is already
    discoverable to any internal role through the jobs list; there is no
    enumeration surface to protect here.
    """
    if user.has_any_role(*_JOB_MEMBERSHIP_BYPASS_ROLES):
        return
    if await is_member_of_job(db, user, job_id):
        return
    if await effective_priority_mode(db, user.id) is not PriorityMode.off:
        assignment_scope = await db.scalar(
            select(RecruitmentPriorityAssignment.id)
            .join(
                RecruitmentPriorityPlanMember,
                RecruitmentPriorityPlanMember.id
                == RecruitmentPriorityAssignment.plan_member_id,
            )
            .join(
                RecruitmentPriorityPlan,
                RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
            )
            .where(
                RecruitmentPriorityAssignment.job_id == job_id,
                RecruitmentPriorityPlanMember.user_id == user.id,
                RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
                RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
            )
            .limit(1)
        )
        # `priority_compliant_at_open IS TRUE` jest tu OBOWIĄZKOWE: samo
        # ownership otwartego procesu jest SAMONADAWALNE. Ingresy, które proces
        # otwierają (np. POST /api/candidates/from-linkedin), tej bramki nie
        # wołają, a w trybie shadow polityka wpuszcza otwarcie bez assignmentu
        # (allowed=True), ustawia wołającego właścicielem i zapisuje naruszenie
        # jako `priority_compliant_at_open=False`. Bez tego warunku jedno takie
        # wywołanie nadawałoby obcej ofercie pełny zakres — pipeline, CV, stawki,
        # generator B2B, feedback z rozmów.
        #
        # Trójstan domykamy na NIE: `.is_(True)` odrzuca i False (naruszenie
        # shadow), i NULL (wiersze legacy/backfill) — brak zamrożonego werdyktu
        # to nie jest zgodność. Werdykt jest zamrażany przy otwarciu i
        # `handoff_process` go nie zmienia, więc przekazanie własności przez HoR
        # nadal nadaje zakres nowemu właścicielowi procesu otwartego z planu.
        carry_scope = await db.scalar(
            select(RecruitmentProcess.id)
            .where(
                RecruitmentProcess.job_id == job_id,
                RecruitmentProcess.owner_user_id == user.id,
                RecruitmentProcess.status == ProcessStatus.open,
                RecruitmentProcess.priority_compliant_at_open.is_(True),
            )
            .limit(1)
        )
        if assignment_scope is not None or carry_scope is not None:
            return
    # Nieistniejąca oferta to 404, nie 403. `is_member_of_job` zwraca dla niej
    # False (brak wiersza => brak członkostwa), więc bez tego rozgałęzienia
    # bramka odpowiadałaby „nie należysz do zespołu" na ofertę, której nie ma —
    # zlewając dwa różne stany i czyniąc „ta rola ma prawo" niesprawdzalnym bez
    # pełnej fikstury (macierze ról sondują trasy identyfikatorem-wartownikiem).
    #
    # Tak, rozróżnienie 404/403 ujawnia, czy oferta istnieje. Jest to akceptowalne
    # z tego samego powodu, dla którego docstring wyżej wybrał 403 zamiast 404 dla
    # obcej oferty: istnienie oferty jest i tak odkrywalne dla każdej roli
    # wewnętrznej przez listę ofert, więc nie ma tu powierzchni enumeracji do
    # ochrony. Czego 404 NIE ujawnia — i to jest właściwość, która ma znaczenie —
    # to niczego o ZAWARTOŚCI cudzej rekrutacji: oferta istniejąca, a wołający
    # spoza jej zespołu, dalej dostaje 403 przed dotknięciem jakichkolwiek danych.
    if await db.get(Job, job_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rekrutacja nie istnieje.",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Brak dostępu do tej rekrutacji — nie należysz do jej zespołu "
            "(właściciel / delivery lead / TAC / współpracownik / "
            "aktywny assignment / carry-over)."
        ),
    )


async def ensure_optional_job_membership(
    db: AsyncSession, user: User, job_id: Optional[int]
) -> None:
    """``ensure_job_membership`` dla zasobów wiązanych z ofertą OPCJONALNIE.

    ``InterviewFeedback.job_id`` i ``ApplicationSubmission.job_id`` są nullable:
    feedback może dotyczyć rozmowy bez rekrutacji, a zgłoszenie przyjść spoza
    konkretnej oferty. Takiego wiersza nie ma do czego zawęzić — zostaje
    widoczny dla ról operacyjnych, dokładnie jak dziś. Gdy ``job_id`` JEST
    ustawiony, obowiązuje pełna bramka.

    Wydzielone w helper, żeby „NULL znaczy brak zawężenia" było jedną decyzją
    w jednym miejscu, a nie powtarzanym ``if job_id is not None`` przy każdej
    trasie — bo wtedy pierwsze pominięte ``if`` znów jest cichą dziurą.
    """
    if job_id is None:
        return
    await ensure_job_membership(db, user, job_id)


def job_scope_clause(user: User, job_id_col: ColumnElement) -> ColumnElement:
    """Fragment ``WHERE`` zawężający listę do ofert, do których user należy.

    Potrzebny tam, gdzie ``ensure_job_membership`` nie ma zastosowania, bo trasa
    nie dostaje pojedynczego ``job_id`` — listy filtrowane opcjonalnymi
    parametrami. Bez tego ``GET`` bez filtrów zwracał globalny przekrój
    (np. ostatnie 200 feedbacków ze WSZYSTKICH rekrutacji).

    Semantyka spójna z ``ensure_job_membership``:
    - role nadzorcze (admin, head_of_recruitment) widzą wszystko,
    - wiersz z ``job_id IS NULL`` nie jest zawężany (patrz
      ``ensure_optional_job_membership``),
    - reszta: właściciel / delivery lead / TAC / aktywny współpracownik,
    - gdy efektywny Priority Work nie jest ``off``: aktywny assignment lub
      ownership otwartego carry-overu założonego ZGODNIE z opublikowanym
      planem również nadaje zakres odczytu.

    Zwraca wyrażenie, nie listę id — zawężenie zostaje w jednym zapytaniu
    i nie psuje paginacji ani limitów.
    """
    if user.has_any_role(*_JOB_MEMBERSHIP_BYPASS_ROLES):
        return true()

    member_jobs = select(Job.id).where(
        or_(
            Job.recruiter_id == user.id,
            Job.delivery_lead_id == user.id,
            Job.tac_id == user.id,
            Job.id.in_(
                select(JobCollaborator.job_id).where(
                    JobCollaborator.user_id == user.id,
                    JobCollaborator.removed_from_auto_cc.is_(False),
                )
            ),
        )
    )
    scope_clauses = [job_id_col.is_(None), job_id_col.in_(member_jobs)]

    # ``job_scope_clause`` jest synchronicznym konstruktorem SQL używanym
    # wewnątrz zapytań listujących, więc per-user rollout również musi zostać
    # rozstrzygnięty w tym samym SQL. Globalne ``off`` nie może nawet rozszerzyć
    # listy o assignment/carry-over. Przy globalnym shadow/enforce wiersz
    # per-user ``off`` jest ceilingiem i wyłącza oba dodatkowe źródła scope.
    #
    # To wyłącznie zakres odczytu. Legacy owner/collaborator ani poniższy
    # assignment/carry-over nie omijają command policy przy otwieraniu nowej
    # pary kandydat-request.
    global_mode = combine_priority_modes(
        getattr(settings, "RECRUITMENT_PRIORITY_MODE", PriorityMode.off.value),
        None,
    )
    if global_mode is not PriorityMode.off:
        user_mode_is_off = exists(
            select(RecruitmentPriorityUserMode.user_id).where(
                RecruitmentPriorityUserMode.user_id == user.id,
                RecruitmentPriorityUserMode.mode == PriorityMode.off,
            )
        )
        assignment_jobs = (
            select(RecruitmentPriorityAssignment.job_id)
            .join(
                RecruitmentPriorityPlanMember,
                RecruitmentPriorityPlanMember.id
                == RecruitmentPriorityAssignment.plan_member_id,
            )
            .join(
                RecruitmentPriorityPlan,
                RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
            )
            .where(
                RecruitmentPriorityPlanMember.user_id == user.id,
                RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
                RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
            )
        )
        # Ten sam warunek zgodności co w ``ensure_job_membership`` — patrz tam po
        # uzasadnienie. Definicja carry-overu musi być identyczna w bramce i w
        # zawężeniu list, bo inaczej samonadany proces, który nie przepuszcza
        # przez bramkę, i tak wyciekałby wierszami na listach.
        carry_over_jobs = select(RecruitmentProcess.job_id).where(
            RecruitmentProcess.owner_user_id == user.id,
            RecruitmentProcess.status == ProcessStatus.open,
            RecruitmentProcess.priority_compliant_at_open.is_(True),
        )
        scope_clauses.append(
            and_(
                ~user_mode_is_off,
                or_(
                    job_id_col.in_(assignment_jobs),
                    job_id_col.in_(carry_over_jobs),
                ),
            )
        )

    return or_(*scope_clauses)


# ── Delivery Lead resource scope ─────────────────────────────────────────────
# These live here, not in ``app/api/jobs.py``, because they are needed by
# surfaces OUTSIDE the Jobs router: a Champion suggestion carries its own
# ``job_id``, and a note can be linked to a job. Importing them from
# ``jobs.py`` would be the first cross-import of that module anywhere in the
# codebase and would drag in 3 400 lines and ~25 dependencies to reach one
# guard. ``jobs.py`` re-exports them so its 26 existing call sites are
# untouched.


async def delivery_lead_job_pairs(
    current_user: User,
    db: AsyncSession,
) -> frozenset[tuple[int, int]] | None:
    """Resolve the exact legacy Job scope for a Delivery Lead.

    ``None`` means this caller uses an oversight or non-DL persona. An empty
    set is deny-all and must never fall back to the organization.
    """
    from app.services.access_scope import ScopeKind, resolve_dashboard_scope

    if current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return None
    if not current_user.has_role(UserRole.delivery_lead):
        return None

    scope = await resolve_dashboard_scope(current_user, db)
    if scope.kind is not ScopeKind.delivery_clients or scope.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery scope belongs to a different user",
        )
    return scope.allowed_client_tac_pairs


def assert_delivery_lead_job_visible(
    job: Job,
    allowed_pairs: frozenset[tuple[int, int]] | None,
) -> None:
    if allowed_pairs is None:
        return
    if (job.client_id, job.tac_id) not in allowed_pairs:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Job is outside the resolved Delivery Lead scope",
        )


async def ensure_champion_job_visible(
    job: Job,
    current_user: User,
    db: AsyncSession,
) -> None:
    """Zakres oferty dla powierzchni Championa — TAC-a włącznie.

    Osobna funkcja obok `ensure_delivery_lead_job_visible`, a nie rozszerzenie
    tamtej: tamtą wołają też `jobs.py` i `notes.py`, więc zmiana jej semantyki
    poszerzyłaby dostęp na trzech powierzchniach naraz przy okazji zmiany
    dotyczącej jednej.

    KLUCZOWA RÓŻNICA — ta funkcja ODMAWIA persony, której nie zna. Sama podmiana
    guarda z `DeliveryLeadPlus` na `TacPlus` NIE wystarczyłaby i byłaby cicho
    groźna: `delivery_lead_job_pairs` zwraca `None` (czyli „bez ograniczeń") dla
    każdego, kto nie jest Delivery Leadem. TAC dostałby więc wgląd w Championa
    KAŻDEJ oferty — czyli dokładnie ten wyciek, który zamknięto w #1069, tylko
    odtworzony inną drogą.

    Alternatywa, nie łańcuch: użytkownik może trzymać kilka ról naraz
    (`role` + `roles`), więc Delivery Lead będący jednocześnie TAC-em tej oferty
    przechodzi, nawet jeśli oferta wypada poza jego zakres delivery.
    """

    if current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return

    if current_user.has_role(UserRole.delivery_lead):
        try:
            assert_delivery_lead_job_visible(
                job, await delivery_lead_job_pairs(current_user, db)
            )
            return
        except HTTPException as exc:
            if exc.status_code != status.HTTP_403_FORBIDDEN:
                raise
            # Odmowa po stronie delivery nie kończy sprawy — ten sam człowiek
            # może być TAC-iem tej oferty. Sprawdzamy drugą ścieżkę niżej.

    # `job.tac_id` bywa NULL (oferta bez przypisanego TAC-a), a `current_user.id`
    # nigdy — więc nieprzypisana oferta wypada z zakresu, zamiast wpadać w niego
    # przez porównanie dwóch pustych wartości.
    if current_user.has_role(UserRole.tac) and job.tac_id == current_user.id:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Job is outside the caller's Champion scope",
    )


async def ensure_delivery_lead_job_visible(
    job: Job,
    current_user: User,
    db: AsyncSession,
) -> None:
    """Fail closed when a Delivery Lead addresses a job outside their scope."""
    assert_delivery_lead_job_visible(
        job, await delivery_lead_job_pairs(current_user, db)
    )
