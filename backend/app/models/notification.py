import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class NotificationType(str, enum.Enum):
    contract_ending = "contract_ending"
    interview_scheduled = "interview_scheduled"
    candidate_added = "candidate_added"
    stage_changed = "stage_changed"
    new_application = "new_application"
    # Phase 13 — automated trigger alerts
    dl_stage_stale_6h = "dl_stage_stale_6h"
    client_feedback_eobd = "client_feedback_eobd"
    powercalling_kpi = "powercalling_kpi"
    candidate_feedback_1h = "candidate_feedback_1h"
    stage_stuck_7d = "stage_stuck_7d"
    # Phase 11 — realtime Champion Profile edits
    champion_profile_updated = "champion_profile_updated"
    # Kontrakty expansion — proactive contract/equipment/order reminders
    contract_ending_90d = "contract_ending_90d"
    equipment_return_due_14d = "equipment_return_due_14d"
    client_order_ending_30d = "client_order_ending_30d"
    # Phase 14 — post-interview feedback chain
    post_interview_t15 = "post_interview_t15"
    post_interview_t45 = "post_interview_t45"
    post_interview_t2h_escalation = "post_interview_t2h_escalation"
    suggest_next_step = "suggest_next_step"
    # KPI Coach — in-app praise / remind / eod_summary (DB enum value
    # `kpi_coach` dodany w migracji 0034_kpi_coach). Konkretny nudge_type
    # żyje w `kpi_nudge_log.nudge_type`; tu mamy wspólny bucket.
    kpi_coach = "kpi_coach"
    # Contractor module — fires when pipeline auto-drafts a contract on
    # `hired` OR when a draft is manually activated via
    # POST /api/contracts/{id}/activate (DB enum value added in 0045).
    contract_activated = "contract_activated"
    # Automatic candidate-rejection email (0045_rejection_emails). Five
    # lifecycle states for the scheduled email:
    #   scheduled → sent | cancelled | skipped (no M365) | failed (retries exhausted)
    rejection_email_scheduled = "rejection_email_scheduled"
    rejection_email_sent = "rejection_email_sent"
    rejection_email_cancelled = "rejection_email_cancelled"
    rejection_email_skipped = "rejection_email_skipped"
    rejection_email_failed = "rejection_email_failed"
    # Targ kandydatów — nowy projekt (create lub significant update) dopasował
    # się do kandydata w puli marketplace z score >= MARKETPLACE_SCORE_THRESHOLD.
    # Wysyłane do candidate.created_by i job.recruiter_id; dedup per para
    # (candidate_id, job_id) w marketplace_alert_log (migracja 0052).
    marketplace_match = "marketplace_match"
    # Pending verification — recruiter wrzucił kandydata na stage 'verified'
    # ze stawką poza widełkami projektu (rate > Job.salary_max). Wysyłane do
    # delivery_lead/head_of_recruitment/admin (migracja 0056).
    pending_verification = "pending_verification"
    # Job Chat — wewnętrzny czat zespołu per rekrutacja (migracja 0061).
    # `job_chat_message` — każda nowa wiadomość → notyfikacja dla każdego
    # członka projektu poza autorem.
    # `job_chat_mention` — bezpośrednie @mention; wyższy priorytet w UI.
    job_chat_message = "job_chat_message"
    job_chat_mention = "job_chat_mention"
    # Configurable stage-transition notifications (migracja 0066). Emitowane
    # przez `services/stage_notification_emitter.py`. Reguły wiszą na
    # `pipeline_stage_defs` (baseline) z możliwością override per klient
    # (`client_stage_notification_overrides`).
    stage_rule = "stage_rule"
    # @mention w zwykłej notatce (Note) lub notatce ze screeningu (ScreeningNote).
    # Wartość dodana w 0066_note_mentions. Wysyłka emaila best-effort przez
    # SMTP synchronicznie po commicie (services/mention_dispatch.py).
    note_mention = "note_mention"
    # Password reset flow (migracja 0078). `password_reset_requested` —
    # informacyjna notyfikacja po wysłaniu linka resetowego (gdy admin
    # wysłał w imieniu usera). `password_changed_by_admin` — gdy admin
    # zresetował hasło ręcznie; user dostaje in-app + email.
    password_reset_requested = "password_reset_requested"
    password_changed_by_admin = "password_changed_by_admin"
    # Autenti e-signature flow (migracja 0079_autenti_signatures).
    # `signature_sent` — kontrakt wysłany do podpisu (do sender_user_id).
    # `signature_signed` — kandydat (lub każdy signer) podpisał (do sender + recruiter).
    # `signature_rejected` — signer odmówił podpisu (do sender_user_id).
    # `signature_failed` — wysyłka nie powiodła się po retries (do sender_user_id).
    signature_sent = "signature_sent"
    signature_signed = "signature_signed"
    signature_rejected = "signature_rejected"
    signature_failed = "signature_failed"
    # Client framework contract (MSA) lifecycle (migracja 0092).
    # Daily scheduler emituje 30/14/7 dni przed `expiry_date` do każdego DL
    # przypisanego do klienta + admin/HoR. Dedup przez (type, related_entity_id, lokalny dzień).
    framework_contract_expiring_30d = "framework_contract_expiring_30d"
    framework_contract_expiring_14d = "framework_contract_expiring_14d"
    framework_contract_expiring_7d = "framework_contract_expiring_7d"
    framework_contract_signed = "framework_contract_signed"
    # ClientOrder ending — `client_order_ending_30d` istniał już od 0037, tu dokładamy
    # 14/7 dni dla dokładniejszego escalation.
    client_order_ending_14d = "client_order_ending_14d"
    client_order_ending_7d = "client_order_ending_7d"


class Notification(Base, TimestampMixin):
    """
    Powiadomienie systemowe dla użytkownika.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # URL to navigate to when clicked
    link: Mapped[Optional[str]] = mapped_column(String(1000))

    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notificationtype"),
        nullable=False,
        index=True,
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # Phase 13 — polymorphic dedup key. Pair (type, related_entity_id) + lokalny
    # dzień Warsaw tworzy unique index `ix_notif_dedup_daily`. Nie dodajemy FK
    # bo entity może być candidate_stage, call, candidate albo job.
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    related_entity_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)

    # Email fallback dla offline >15min (Phase chat-2): kiedy chat-related
    # notyfikacja przeleży 15 min nieprzeczytana i user nie był online,
    # background task wysyła email i stempluje tutaj timestamp. Zapobiega
    # podwójnym wysyłkom przy kolejnych przebiegach taska.
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user={self.user_id} type={self.notification_type} read={self.is_read}>"
