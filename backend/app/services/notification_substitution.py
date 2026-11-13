"""Komu oddać powiadomienie, gdy adresat jest dziś zastępowany (09.11.2026).

Decyzja Artura z 02.11.2026: dzwonki o bieżącej pracy idą tylko do zastępcy,
który ją przejął. Do 09.11 robiło to kilka miejsc w kodzie, a ponad 50 źródeł
wysyłało je do osoby na urlopie. Dlatego decyzja zapada w jednym wyjściu,
``notification_triggers.emit``, a nie u każdego producenta.

Nowy typ powiadomienia musi trafić do jednej z dwóch list poniżej; bez tego pada
``tests/test_notification_substitution.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationType as T
from app.models.user import User
from app.services.workforce_availability import (
    SUBSTITUTE_CAPABILITIES,
    user_roles,
    workforce_context,
)

logger = logging.getLogger(__name__)

#: Klucz w ``AsyncSession.info``: kto wykonał żądanie (``api.deps``).
ACTOR_KEY = "notification_actor_id"

#: Praca, która nie może czekać do powrotu osoby.
CURRENT_WORK_TYPES: frozenset[T] = frozenset(
    {
        T.also_fits_added,
        T.application_screening_digest,
        T.auto_match,
        T.auto_match_proposals,
        T.autofill_decisions_due,
        T.b2b_agreement_ready,
        T.b2b_signature_requested,
        T.board_task_waiting,
        T.board_tasks_digest,
        T.candidate_claim_taken,
        T.candidate_feedback_1h,
        T.candidate_followup_signal,
        T.candidate_rate_change,
        T.candidate_rate_change_task,
        T.champion_profile_updated,
        T.champion_search_resumed,
        T.champions_changed,
        T.client_accepted,
        T.client_feedback_eobd,
        T.client_job_opened,
        T.client_order_ending_14d,
        T.client_order_ending_30d,
        T.client_order_ending_7d,
        T.client_panel_request,
        T.consultant_in_other_recruitment,
        T.contract_activated,
        T.contract_ending,
        T.contract_ending_90d,
        T.cpro_candidate_rejected,
        T.cpro_close_needs_decision,
        T.cpro_interview_change,
        T.cv_ready,
        T.departed_pairs_care,
        T.dl_stage_stale_6h,
        T.framework_contract_expiring_14d,
        T.framework_contract_expiring_30d,
        T.framework_contract_expiring_7d,
        T.framework_contract_signed,
        T.hire_missing_contract,
        T.interview_changed,
        T.interview_debrief_saved,
        T.interview_scheduled,
        T.interview_slot_chosen,
        T.interview_slot_confirmed,
        T.interview_slots_requested,
        T.job_ad_backlog,
        T.job_ad_missing,
        T.job_ad_nudge,
        T.job_closed_people_waiting,
        T.job_deadline_1d,
        T.job_deadline_3d,
        T.job_deadline_7d,
        T.job_idle_reminder,
        T.job_p0_overdue,
        T.job_p0_set,
        T.job_twin_linked,
        T.marketplace_match,
        T.match_digest,
        T.new_application,
        T.order_missing_successor,
        T.pending_verification,
        T.post_interview_t15,
        T.post_interview_t2h_escalation,
        T.post_interview_t45,
        T.pre_contract,
        T.prep2_skipped,
        T.prep_attention,
        T.prep_candidate_declined,
        T.prep_candidate_response,
        T.prep_changed,
        T.prep_changed_yours,
        T.prep_no_response,
        T.prep_review_ready,
        T.recruiter_parked,
        T.recruiter_restored,
        T.rejection_email_cancelled,
        T.rejection_email_failed,
        T.rejection_email_scheduled,
        T.rejection_email_sent,
        T.rejection_email_skipped,
        T.request_assignment_changed,
        T.request_review_needed,
        T.signature_failed,
        T.signature_rejected,
        T.signature_renewal_requested,
        T.signature_sent,
        T.signature_signed,
        T.similar_job_candidates,
        T.stage_changed,
        T.stage_rule,
        T.stage_stuck_7d,
        T.start_documents,
        T.start_documents_due,
        T.start_documents_reminder,
        T.start_documents_returned,
        T.suggest_next_step,
        # 0696: szkolenia — wycena, plik od trenera, umowa do podpisu, faktura.
        T.training_file,
        T.training_invoice,
        T.training_quote,
        T.training_sign,
    }
)

#: Zostają u osoby: jej konto, pieniądze, kadry, wzmianki i własne listy. Kolejka
#: Cpro ma własnego zastępcę z wniosku (``cpro_sender``), opieka też swój silnik.
PERSONAL_TYPES: frozenset[T] = frozenset(
    {
        T.admin_case_assigned,
        T.ai_spend_alert,
        T.announcement_important,
        T.autofill_quality_report,
        T.automation_failing,
        T.back_office_assigned,
        T.back_office_escalated,
        T.candidate_added,
        T.candidate_data_access_alert,
        T.candidate_search_completed,
        T.care_announcement,
        T.care_client_structure,
        T.care_contact_due,
        T.care_demand_signal,
        T.care_front_office_handoff,
        T.cpro_send_assigned,
        T.equipment_protocol_signed,
        T.equipment_return_due_14d,
        T.equipment_return_reminder,
        T.equipment_task,
        T.hired_order_missing,
        T.hr_absence_reported,
        T.hr_agreement_update,
        T.hr_approval_decided,
        T.hr_approval_requested,
        T.hr_approval_topup_requested,
        T.hr_bonus_assigned,
        T.hr_leave_cancelled,
        T.hr_leave_conflict,
        T.hr_leave_decided,
        T.hr_leave_requested,
        T.hr_leave_substitute,
        T.hr_lifecycle_task,
        T.hr_m365_scope_missing,
        T.hr_rate_changed,
        T.hr_settlement_correction,
        T.hr_settlement_paid,
        T.hr_settlement_review,
        T.hr_subscription_renewal,
        T.hr_timesheet_decided,
        T.hr_timesheet_reminder,
        T.hr_timesheet_submitted,
        T.hr_work_handover,
        T.job_chat_mention,
        T.job_chat_message,
        T.job_p0_requested,
        T.kpi_coach,
        T.my_people_match,
        T.new_person_signed_in,
        T.note_mention,
        T.note_reply,
        T.own_hiring_update,
        T.password_changed_by_admin,
        T.password_reset_requested,
        T.portal_low_rating,
        T.portal_monthly_review,
        # 0696: przypomnienie o szkoleniu i nagranie dostępne / do zatwierdzenia.
        T.training_recording,
        T.training_reminder,
        T.powercalling_kpi,
        T.prep2_skip_threshold,
        T.recruitment_allocation_alert,
        T.request_allocation_proposals,
        T.saved_search_match,
        T.saved_search_reapproval,
        T.teams_prep_scope_missing,
        T.trainee_program_decision,
    }
)

#: Role, których pracę przekazuje silnik zastępstw — tylko o nich ostrzegamy.
#: Finanse i pracownik zastępców mają, ale ich sprawy idą innymi ścieżkami.
_REPORTED_ROLES = (
    "delivery_lead",
    "head_of_recruitment",
    "talent_community_manager",
    "recruiter",
)


@dataclass(frozen=True, slots=True)
class Route:
    user_id: int
    on_behalf_of: Optional[int] = None
    skip: bool = False


async def notification_route(
    db: AsyncSession, user_id: int, notification_type: T
) -> Route:
    """Dokąd iść ma wiersz. Awaria silnika zostawia nominalnego adresata."""
    if notification_type not in CURRENT_WORK_TYPES:
        return Route(user_id)
    try:
        context = await workforce_context(db)
    except Exception:  # noqa: BLE001 — powiadomienie nie może przez to zginąć
        logger.exception("substitution: workforce context failed")
        return Route(user_id)
    performer = context.performer(user_id)
    if performer is None or performer == user_id:
        return Route(user_id)
    # Zastępca sam wykonał ruch za nieobecną osobę: producent porównał autora
    # z nominalnym adresatem, więc o własnej akcji dowiedziałby się dzwonkiem.
    if performer == db.info.get(ACTOR_KEY):
        return Route(user_id, skip=True)
    return Route(performer, on_behalf_of=user_id)


def substitute_role_gap(owner: User, substitute: User) -> Optional[str]:
    """Rola nieobecnej osoby, której pracy ten zastępca nie przejmie, albo None."""
    owner_roles = user_roles(owner)
    target_roles = user_roles(substitute)
    if "admin" in target_roles:
        return None
    for role in _REPORTED_ROLES:
        if role in owner_roles and not target_roles & SUBSTITUTE_CAPABILITIES[role]:
            return role
    return None
