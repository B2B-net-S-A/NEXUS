"""Section-aware visibility and fan-out policy for user notifications.

Notification rows can outlive role and section-policy changes.  Their target
``user_id`` is therefore not sufficient authorization: every read, mutation,
email and realtime delivery must re-evaluate the recipient's current effective
section access.  The enum mapping below is exhaustive by design so a new
notification type cannot silently become visible to every authenticated user.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import hr_notification_schema
from app.services.notification_categories import user_muted_types
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    resolve_effective_section_access,
    resolve_effective_section_access_for_users,
    section_access_for_user,
)


logger = logging.getLogger(__name__)


# 0457: typy osobiste modułów kadrowych — odbiorcę wybiera reguła modułu
# (przełożony, zastępca, Kadry, posiadacz „Sprzętu”), nie sekcja produktu.
# „Pracownik” nie ma sekcji, a musi dostać decyzję o swoim urlopie.
HR_PERSONAL_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    NotificationType(value) for value in hr_notification_schema.PERSONAL_TYPES
)

ALWAYS_VISIBLE_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.password_reset_requested,
        NotificationType.password_changed_by_admin,
        *HR_PERSONAL_NOTIFICATION_TYPES,
        # 0617: ważne ogłoszenie — odbiorców wybiera rola z ogłoszenia, nie
        # sekcja (pulpit ma każdy, także „Pracownik” i Rada).
        NotificationType.announcement_important,
    }
)

ADMIN_ONLY_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.ai_spend_alert,
        NotificationType.automation_failing,
        NotificationType.teams_prep_scope_missing,
    }
)

# 0508: alarm o masowym przeglądaniu CV — admin i Head of Recruitment (rola
# główna albo dodatkowa), niezależnie od sekcji (decyzja Artura 22.10.2026).
HEAD_OF_RECRUITMENT_ALERT_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.candidate_data_access_alert,
        # 0612: nowa osoba po pierwszym logowaniu (decyzja Artura 28.10.2026).
        NotificationType.new_person_signed_in,
    }
)

# Context-sensitive types are handled separately below.  Every other enum
# value must appear here or in ``ALWAYS_VISIBLE_NOTIFICATION_TYPES``.
NOTIFICATION_SECTION_BY_TYPE: dict[NotificationType, ProductSection] = {
    NotificationType.recruitment_allocation_alert: ProductSection.pipeline,
    NotificationType.contract_ending: ProductSection.delivery,
    NotificationType.interview_scheduled: ProductSection.pipeline,
    NotificationType.candidate_added: ProductSection.sourcing,
    NotificationType.stage_changed: ProductSection.pipeline,
    NotificationType.new_application: ProductSection.sourcing,
    NotificationType.application_screening_digest: ProductSection.pipeline,
    NotificationType.dl_stage_stale_6h: ProductSection.pipeline,
    NotificationType.client_feedback_eobd: ProductSection.pipeline,
    NotificationType.powercalling_kpi: ProductSection.insights,
    NotificationType.candidate_feedback_1h: ProductSection.pipeline,
    NotificationType.stage_stuck_7d: ProductSection.pipeline,
    NotificationType.champion_profile_updated: ProductSection.pipeline,
    NotificationType.contract_ending_90d: ProductSection.delivery,
    NotificationType.equipment_return_due_14d: ProductSection.delivery,
    NotificationType.client_order_ending_30d: ProductSection.delivery,
    NotificationType.match_digest: ProductSection.pipeline,
    NotificationType.post_interview_t15: ProductSection.pipeline,
    NotificationType.post_interview_t45: ProductSection.pipeline,
    NotificationType.post_interview_t2h_escalation: ProductSection.pipeline,
    NotificationType.suggest_next_step: ProductSection.pipeline,
    NotificationType.kpi_coach: ProductSection.insights,
    NotificationType.contract_activated: ProductSection.delivery,
    NotificationType.rejection_email_scheduled: ProductSection.pipeline,
    NotificationType.rejection_email_sent: ProductSection.pipeline,
    NotificationType.rejection_email_cancelled: ProductSection.pipeline,
    NotificationType.rejection_email_skipped: ProductSection.pipeline,
    NotificationType.rejection_email_failed: ProductSection.pipeline,
    NotificationType.marketplace_match: ProductSection.sourcing,
    NotificationType.stage_rule: ProductSection.pipeline,
    # Podpis umów B2B (generator, podpis w NEXUSIE): dzwonki idą do nadawcy —
    # zwykle rekrutera bez sekcji Delivery — i reprezentanta firmy. Ta sama
    # bramka co trasy Generatora (Sourcing); do 22.10.2026 była Delivery
    # i rekruter nie dostawał żadnego dzwonka o swojej umowie.
    NotificationType.signature_sent: ProductSection.sourcing,
    NotificationType.signature_signed: ProductSection.sourcing,
    NotificationType.signature_rejected: ProductSection.sourcing,
    NotificationType.signature_failed: ProductSection.sourcing,
    NotificationType.signature_renewal_requested: ProductSection.sourcing,
    NotificationType.framework_contract_expiring_30d: ProductSection.delivery,
    NotificationType.framework_contract_expiring_14d: ProductSection.delivery,
    NotificationType.framework_contract_expiring_7d: ProductSection.delivery,
    NotificationType.framework_contract_signed: ProductSection.delivery,
    NotificationType.client_order_ending_14d: ProductSection.delivery,
    NotificationType.client_order_ending_7d: ProductSection.delivery,
    NotificationType.saved_search_match: ProductSection.sourcing,
    NotificationType.similar_job_candidates: ProductSection.pipeline,
    NotificationType.job_deadline_7d: ProductSection.pipeline,
    NotificationType.job_deadline_3d: ProductSection.pipeline,
    NotificationType.job_deadline_1d: ProductSection.pipeline,
    NotificationType.order_missing_successor: ProductSection.delivery,
    # 0324: system sam dodał kandydata do pipeline'u rekrutacji.
    NotificationType.auto_match: ProductSection.pipeline,
    # 0335: dzienny digest propozycji z nowych CV (nic nie weszło do pipeline'u).
    NotificationType.auto_match_proposals: ProductSection.pipeline,
    NotificationType.candidate_search_completed: ProductSection.sourcing,
    # 0334: nowa rekrutacja pasuje do „Moich ludzi" — akcją jest dodanie do
    # pipeline'u tej rekrutacji.
    NotificationType.my_people_match: ProductSection.pipeline,
    NotificationType.saved_search_reapproval: ProductSection.sourcing,
    # 0338: cykl rozmowy u klienta (terminy od klienta) — sekcja kalendarza.
    NotificationType.interview_slots_requested: ProductSection.pipeline,
    NotificationType.interview_slot_chosen: ProductSection.pipeline,
    NotificationType.interview_slot_confirmed: ProductSection.pipeline,
    NotificationType.interview_debrief_saved: ProductSection.pipeline,
    NotificationType.prep_attention: ProductSection.pipeline,
    NotificationType.prep_candidate_response: ProductSection.pipeline,
    NotificationType.prep_candidate_declined: ProductSection.pipeline,
    NotificationType.prep_changed: ProductSection.pipeline,
    NotificationType.prep_changed_yours: ProductSection.pipeline,
    NotificationType.prep_no_response: ProductSection.pipeline,
    NotificationType.prep2_skipped: ProductSection.pipeline,
    NotificationType.prep2_skip_threshold: ProductSection.pipeline,
    NotificationType.interview_changed: ProductSection.pipeline,
    NotificationType.prep_review_ready: ProductSection.pipeline,
    NotificationType.pre_contract: ProductSection.pipeline,
    NotificationType.trainee_program_decision: ProductSection.pipeline,
    NotificationType.candidate_followup_signal: ProductSection.pipeline,
    # 0399: odpowiedź na notatkę — notatki żyją za sekcją Sourcing (router).
    NotificationType.note_reply: ProductSection.sourcing,
    NotificationType.board_tasks_digest: ProductSection.pipeline,
    NotificationType.cpro_send_assigned: ProductSection.pipeline,
    NotificationType.board_task_waiting: ProductSection.pipeline,
    # 0417: link prowadzi do panelu osoby na Tablicy rekrutacji.
    NotificationType.b2b_signature_requested: ProductSection.pipeline,
    # 0524: link prowadzi do panelu osoby na Tablicy rekrutacji.
    NotificationType.b2b_agreement_ready: ProductSection.pipeline,
    NotificationType.candidate_rate_change: ProductSection.pipeline,
    NotificationType.candidate_rate_change_task: ProductSection.pipeline,
    NotificationType.request_assignment_changed: ProductSection.pipeline,
    # 0447: link prowadzi do rekrutacji (panel „Zespół”).
    NotificationType.recruiter_parked: ProductSection.pipeline,
    NotificationType.recruiter_restored: ProductSection.pipeline,
    # 0450: link prowadzi do Tablicy rekrutacji (plakietka „Championi”).
    NotificationType.champions_changed: ProductSection.pipeline,
    NotificationType.champion_search_resumed: ProductSection.pipeline,
    NotificationType.job_twin_linked: ProductSection.pipeline,
    NotificationType.request_review_needed: ProductSection.pipeline,
    # 0523: link prowadzi do rekrutacji.
    NotificationType.client_job_opened: ProductSection.pipeline,
    # 0526: przypomnienia o ogłoszeniach — link prowadzi do rekrutacji
    # albo do „Ogłoszeń do nadrobienia”.
    NotificationType.job_ad_missing: ProductSection.pipeline,
    NotificationType.job_ad_backlog: ProductSection.pipeline,
    NotificationType.job_ad_nudge: ProductSection.pipeline,
    NotificationType.job_p0_set: ProductSection.pipeline,
    NotificationType.job_p0_requested: ProductSection.pipeline,
    # 0617: rekrutacje bez ruchu — link prowadzi na rekrutację.
    NotificationType.job_idle_reminder: ProductSection.pipeline,
    # 0607: link prowadzi na Tablicę zamkniętej rekrutacji.
    NotificationType.job_closed_people_waiting: ProductSection.pipeline,
    NotificationType.request_allocation_proposals: ProductSection.pipeline,
    NotificationType.candidate_claim_taken: ProductSection.pipeline,
    NotificationType.hired_order_missing: ProductSection.finance,
    NotificationType.consultant_in_other_recruitment: ProductSection.delivery,
    # 0440: link prowadzi do panelu osoby na Tablicy rekrutacji (sekcja CV).
    NotificationType.cv_ready: ProductSection.pipeline,
    # 0444: link prowadzi do panelu osoby na Tablicy rekrutacji, do której dodano.
    NotificationType.also_fits_added: ProductSection.pipeline,
    NotificationType.autofill_decisions_due: ProductSection.pipeline,
    NotificationType.autofill_quality_report: ProductSection.insights,
    # 0451: link prowadzi do panelu osoby na Tablicy rekrutacji.
    NotificationType.client_accepted: ProductSection.pipeline,
    # 0452: link prowadzi do panelu osoby na Tablicy rekrutacji.
    NotificationType.hire_missing_contract: ProductSection.pipeline,
    # 0457: opieka nad konsultantem — link do zakładki „Opieka” kontraktu.
    NotificationType.care_contact_due: ProductSection.delivery,
    # 0475: link prowadzi do „Struktury u klientów” w Opiece (sekcja Delivery).
    NotificationType.care_client_structure: ProductSection.delivery,
    # 0509: popyt z rozmowy opiekuna — karta na tablicy „Do zrobienia” DL.
    NotificationType.care_demand_signal: ProductSection.delivery,
}

CONTEXTUAL_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.job_chat_message,
        NotificationType.job_chat_mention,
        NotificationType.note_mention,
        NotificationType.pending_verification,
    }
)


def notification_types_for_sections(
    sections: Iterable[ProductSection],
) -> frozenset[NotificationType]:
    """Typy powiadomień przypisane na stałe do wskazanych sekcji produktu.

    Typy kontekstowe (czat rekrutacji, wzmianki, weryfikacja) nie mają sekcji
    w mapie i nigdy nie trafiają do wyniku — ich sekcję ustala link.
    """
    wanted = set(sections)
    return frozenset(
        ntype
        for ntype, section in NOTIFICATION_SECTION_BY_TYPE.items()
        if section in wanted
    )


def _has_section_read(user: User, section: ProductSection) -> bool:
    return section_access_for_user(user, section) >= SectionAccess.read


def _section_for_link(link: str | None) -> ProductSection | None:
    path = (link or "").split("?", 1)[0].split("#", 1)[0]
    if path.startswith("/contracts/b2b-generator"):
        return ProductSection.sourcing
    if path.startswith(
        (
            "/candidates",
            "/talents",
            "/sourcing",
            "/applications",
            "/cv-generator",
            "/talent-radar",
        )
    ):
        return ProductSection.sourcing
    if path.startswith(("/jobs", "/calendar")):
        return ProductSection.pipeline
    if path.startswith(
        (
            "/clients",
            "/contracts",
            "/contractors",
            "/manager",
            "/my-clients",
            "/my-relationships",
            "/order-mail",
        )
    ):
        return ProductSection.delivery
    if path.startswith("/insights"):
        return ProductSection.insights
    if path.startswith("/finance"):
        return ProductSection.finance
    return None


def user_can_receive_notification(
    user: User,
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
) -> bool:
    """Evaluate one row/event against the current request-local policy."""

    if not user.is_active:
        return False
    # Wyciszenie kategorii (0349) jest decyzją samego odbiorcy, więc obowiązuje
    # także administratora. Kategorie obowiązkowe nigdy nie trafiają do zbioru.
    if notification_type in user_muted_types(user):
        return False
    # Grupa wyłączona dla wszystkich ról konta w tabeli „Kto co dostaje”.
    if notification_type in role_muted_types_of(user):
        return False
    return user_may_receive_type(
        user,
        notification_type,
        related_entity_type=related_entity_type,
        link=link,
    )


def user_can_receive_required_mail(
    user: User,
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
) -> bool:
    """Jak `user_can_receive_notification`, ale bez wyciszeń samego odbiorcy.

    Mail obowiązkowy (26.10.2026) przychodzi mimo wyciszonej kategorii
    w dzwonku; grupa wyłączona dla roli przez admina i polityka sekcji nadal
    go zatrzymują.
    """
    if not user.is_active or notification_type in role_muted_types_of(user):
        return False
    return user_may_receive_type(
        user,
        notification_type,
        related_entity_type=related_entity_type,
        link=link,
    )


def role_muted_types_of(user: User) -> frozenset[NotificationType]:
    """Typy wyłączone dla ról konta; konto bez policzonej polityki = nic."""
    return getattr(user, "role_muted_notification_types", None) or frozenset()


def user_may_receive_type(
    user: User,
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
) -> bool:
    """Polityka sekcji BEZ wyciszeń — czy ten typ w ogóle może do kogoś trafić.

    Strona „Moje konto → Powiadomienia" pyta tędy, które kategorie pokazać:
    wyciszona kategoria nie może zniknąć z listy, bo nie dałoby się jej włączyć.
    """
    if user.has_role(UserRole.admin):
        return True
    if notification_type in ADMIN_ONLY_NOTIFICATION_TYPES:
        return False
    if notification_type in HEAD_OF_RECRUITMENT_ALERT_TYPES:
        return user.has_role(UserRole.head_of_recruitment)
    if notification_type in ALWAYS_VISIBLE_NOTIFICATION_TYPES:
        return True

    if notification_type in {
        NotificationType.job_chat_message,
        NotificationType.job_chat_mention,
    }:
        section = (
            ProductSection.sourcing
            if related_entity_type == "candidate_chat_message"
            else ProductSection.pipeline
        )
        return _has_section_read(user, section)

    if notification_type == NotificationType.note_mention:
        section = _section_for_link(link)
        return section is not None and _has_section_read(user, section)

    if notification_type == NotificationType.pending_verification:
        # Requests awaiting approval contain rate/budget values and remain
        # admin-only.  The same legacy enum is also used for the safe outcome
        # message sent back to the mover, whose link points at the Job.
        return bool(
            (link or "").startswith("/jobs/")
            and _has_section_read(user, ProductSection.pipeline)
        )

    section = NOTIFICATION_SECTION_BY_TYPE.get(notification_type)
    return section is not None and _has_section_read(user, section)


def notification_visibility_predicate(user: User) -> Any:
    """SQL predicate shared by list/count/read/update notification routes.

    Łączy politykę sekcji z wyciszeniami użytkownika (0349): wyciszona
    kategoria znika z listy i z licznika nieprzeczytanych.
    """

    muted = user_muted_types(user) | role_muted_types_of(user)
    section_policy = _section_visibility_predicate(user)
    if not muted:
        return section_policy
    return and_(
        section_policy,
        Notification.notification_type.not_in(sorted(muted, key=str)),
    )


def _section_visibility_predicate(user: User) -> Any:
    if user.has_role(UserRole.admin):
        return true()

    conditions: list[Any] = [
        Notification.notification_type.in_(ALWAYS_VISIBLE_NOTIFICATION_TYPES)
    ]
    if user.has_role(UserRole.head_of_recruitment):
        conditions.append(
            Notification.notification_type.in_(HEAD_OF_RECRUITMENT_ALERT_TYPES)
        )
    allowed_fixed_types = [
        notification_type
        for notification_type, section in NOTIFICATION_SECTION_BY_TYPE.items()
        if _has_section_read(user, section)
    ]
    if allowed_fixed_types:
        conditions.append(Notification.notification_type.in_(allowed_fixed_types))

    if _has_section_read(user, ProductSection.pipeline):
        conditions.append(
            and_(
                Notification.notification_type.in_(
                    {
                        NotificationType.job_chat_message,
                        NotificationType.job_chat_mention,
                    }
                ),
                or_(
                    Notification.related_entity_type.is_(None),
                    Notification.related_entity_type != "candidate_chat_message",
                ),
            )
        )
        conditions.append(
            and_(
                Notification.notification_type == NotificationType.pending_verification,
                Notification.link.startswith("/jobs/", autoescape=True),
            )
        )
    if _has_section_read(user, ProductSection.sourcing):
        conditions.append(
            and_(
                Notification.notification_type.in_(
                    {
                        NotificationType.job_chat_message,
                        NotificationType.job_chat_mention,
                    }
                ),
                Notification.related_entity_type == "candidate_chat_message",
            )
        )

    note_link_conditions: list[Any] = []
    if _has_section_read(user, ProductSection.sourcing):
        note_link_conditions.extend(
            Notification.link.startswith(prefix, autoescape=True)
            for prefix in (
                "/candidates",
                "/talents",
                "/sourcing",
                "/applications",
                "/cv-generator",
                "/talent-radar",
                "/contracts/b2b-generator",
            )
        )
    if _has_section_read(user, ProductSection.pipeline):
        note_link_conditions.extend(
            Notification.link.startswith(prefix, autoescape=True)
            for prefix in ("/jobs", "/calendar")
        )
    if _has_section_read(user, ProductSection.delivery):
        note_link_conditions.extend(
            (
                Notification.link.startswith("/clients", autoescape=True),
                and_(
                    Notification.link.startswith("/contracts", autoescape=True),
                    ~Notification.link.startswith(
                        "/contracts/b2b-generator", autoescape=True
                    ),
                ),
                Notification.link.startswith("/contractors", autoescape=True),
                Notification.link.startswith("/manager", autoescape=True),
                Notification.link.startswith("/my-clients", autoescape=True),
                Notification.link.startswith("/my-relationships", autoescape=True),
                Notification.link.startswith("/order-mail", autoescape=True),
            )
        )
    if _has_section_read(user, ProductSection.insights):
        note_link_conditions.append(
            Notification.link.startswith("/insights", autoescape=True)
        )
    if _has_section_read(user, ProductSection.finance):
        note_link_conditions.append(
            Notification.link.startswith("/finance", autoescape=True)
        )
    if note_link_conditions:
        conditions.append(
            and_(
                Notification.notification_type == NotificationType.note_mention,
                or_(*note_link_conditions),
            )
        )

    return or_(*conditions) if conditions else false()


async def notification_recipient_has_access(
    db: AsyncSession,
    user_id: int,
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
    ignore_personal_mutes: bool = False,
) -> bool:
    """Re-read a recipient and their effective policy before side effects."""

    user = await db.get(User, user_id, populate_existing=True)
    if user is None:
        return False
    await resolve_effective_section_access(db, user)
    check = (
        user_can_receive_required_mail
        if ignore_personal_mutes
        else user_can_receive_notification
    )
    return check(
        user,
        notification_type,
        related_entity_type=related_entity_type,
        link=link,
    )


async def filter_notification_recipients(
    db: AsyncSession,
    user_ids: Iterable[int],
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
) -> list[User]:
    """Batch-resolve active recipients without per-recipient policy queries."""

    ids = sorted(set(user_ids))
    if not ids:
        return []
    users = list(
        (
            await db.scalars(
                select(User).where(User.id.in_(ids), User.is_active.is_(True))
            )
        ).all()
    )
    await resolve_effective_section_access_for_users(db, users)
    return [
        user
        for user in users
        if user_can_receive_notification(
            user,
            notification_type,
            related_entity_type=related_entity_type,
            link=link,
        )
    ]


def user_can_receive_realtime_event(user: User, event: dict[str, Any]) -> bool:
    """Apply section ceilings to known realtime payload families."""

    event_type = str(event.get("type") or "")
    # ``chat:notify`` / ``candidate-chat:notify`` zapowiadają powiadomienie
    # czatu (dymek, okienko „Czaty”), więc przechodzą tę samą bramkę co wiersz:
    # sekcja ORAZ wyciszona kategoria. Sam prefiks ``chat:`` pyta tylko o sekcję.
    if event_type in {"notification", "chat:notify", "candidate-chat:notify"}:
        data = event.get("data")
        if not isinstance(data, dict):
            return False
        raw_type = data.get("notification_type")
        try:
            notification_type = NotificationType(raw_type)
        except (TypeError, ValueError):
            logger.warning(
                "Dropping realtime notification with unknown type=%r for user_id=%s",
                raw_type,
                user.id,
            )
            return False
        return user_can_receive_notification(
            user,
            notification_type,
            related_entity_type=data.get("related_entity_type"),
            link=data.get("link"),
        )
    # „Moi ludzie” (16.10.2026): dopasowanie bez wiersza w bazie — ta sama
    # bramka co dawny wiersz ``my_people_match`` (sekcja i wyciszenie).
    if event_type == "my_people:match":
        data = event.get("data")
        if not isinstance(data, dict):
            return False
        return user_can_receive_notification(
            user,
            NotificationType.my_people_match,
            related_entity_type="job",
            link=data.get("link"),
        )
    if event_type == "kpi_nudge":
        return _has_section_read(user, ProductSection.insights)
    if event_type in {
        "champion_profile_changed",
        "pipeline_changed",
    } or event_type.startswith("chat:"):
        return _has_section_read(user, ProductSection.pipeline)
    if event_type.startswith("candidate-chat:"):
        return _has_section_read(user, ProductSection.sourcing)
    return True


def unmapped_notification_types() -> frozenset[NotificationType]:
    """Test hook: any value here is hidden for non-admins until classified."""

    return frozenset(NotificationType) - (
        ALWAYS_VISIBLE_NOTIFICATION_TYPES
        | ADMIN_ONLY_NOTIFICATION_TYPES
        | HEAD_OF_RECRUITMENT_ALERT_TYPES
        | frozenset(NOTIFICATION_SECTION_BY_TYPE)
        | CONTEXTUAL_NOTIFICATION_TYPES
    )
