import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class NotificationType(str, enum.Enum):
    ai_spend_alert = "ai_spend_alert"
    recruitment_allocation_alert = "recruitment_allocation_alert"
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
    # Cotygodniowy digest top dopasowań per otwarta rekrutacja (match_digest).
    match_digest = "match_digest"
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
    # Saved-search alerts (migracja 0129). Zbiorcza notyfikacja "N nowych
    # kandydatów pasuje do zapisanego wyszukiwania X" emitowana przez
    # app/tasks/saved_search_alerts.py. Dedup dzienny przez ix_notif_dedup_daily
    # z related_entity=(saved_search, id) + dedupe_resurface (ten sam dzień
    # aktualizuje treść/licznik zamiast dokładać kolejne wpisy).
    saved_search_match = "saved_search_match"
    # Szybkie przepinanie — nowy job przypomina historyczne requesty (Tier A)
    # z kandydatami po etapach klienckich. Emitowane przez
    # `services/similar_job_notify.py` po POST /jobs (background task).
    # DB enum value: safety-net ALTER w entrypoint.sh (wzorzec kpi_coach).
    similar_job_candidates = "similar_job_candidates"
    # Deadline rekrutacji zbliża się (Job.deadline). Daily scanner
    # `app/tasks/job_deadline_alerts.py` emituje 7/3/1 dni przed deadline'em
    # do przypisanych/delegowanych osób projektu (owner recruiter + DL + TAC +
    # aktywni collaboratorzy). In-app + email (SMTP). Dedup przez
    # (type, related_entity=(job, id)) — jeden alert per próg per user na zawsze.
    # DB enum value: migracja 0211 + safety-net ALTER w entrypoint.sh.
    job_deadline_7d = "job_deadline_7d"
    job_deadline_3d = "job_deadline_3d"
    job_deadline_1d = "job_deadline_1d"
    # 0308: zamówienie zakończyło się wczoraj, a osoba nie ma u klienta
    # następnego zamówienia. Emitowane przez `services/order_gaps.py` do DL
    # przypisanych do klienta; dedup po (typ, related_entity=(order_gap, id)).
    order_missing_successor = "order_missing_successor"
    # 0324: system sam dodał kandydata do pipeline'u rekrutacji (auto-match po
    # odczycie nowego CV albo po publikacji rekrutacji). Dedup po wierszu
    # etapu, nie po rekrutacji — dwóch kandydatów tego samego dnia to dwa dzwonki.
    auto_match = "auto_match"
    # 0325: pełny przegląd bazy (Talent Radar / AI Matching w rekrutacji)
    # zakończył się albo nie powiódł — trwa ~3 min, więc autor dostaje wpis
    # w dzwonku zamiast pilnować karty. Emitowane przez
    # `services/candidate_search_worker.py`; `related_entity_id` puste (id
    # przeglądu to UUID), exactly-once daje przejście stanu runu.
    candidate_search_completed = "candidate_search_completed"
    # 0334: opublikowana rekrutacja pasuje do osób z listy „Moi ludzie"
    # rekrutera. Emitowane przez `services/my_people_matching.py`; jeden dzwonek
    # na (odbiorca, rekrutacja) — `related_entity=(job, id)`.
    my_people_match = "my_people_match"
    # 0335: tryb `propose` auto-matchu — JEDEN dzienny digest na (rekrutacja,
    # odbiorca): „N nowych propozycji z nowych CV”. Dedup dobowy po
    # related_entity=(job, id); kolejne propozycje tego dnia podbijają licznik
    # w istniejącym wpisie (`auto_match_service._notify_proposals`).
    auto_match_proposals = "auto_match_proposals"
    # 0335: TEN SAM automat rekrutacji padł 3 razy z rzędu — JEDNO powiadomienie
    # na serię, wyłącznie dla adminów (`services/automation_failures.py`).
    # Rekruterzy nie dostają nic: awaria jest wpisem w „Pracy w tle".
    automation_failing = "automation_failing"
    # 0336: zapisane wyszukiwanie po migracji na wspólną semantykę filtrów
    # zwraca inny zbiór osób — alert wstrzymany do akceptacji właściciela.
    saved_search_reapproval = "saved_search_reapproval"
    # 0338: cykl rozmowy u klienta — przekazania DL ↔ rekruter.
    # DL dodał terminy od klienta → rekruter ustala z kandydatem.
    interview_slots_requested = "interview_slots_requested"
    # Rekruter wybrał termin → DL odpowiada klientowi.
    interview_slot_chosen = "interview_slot_chosen"
    # DL potwierdził termin u klienta → rozmowa jest w kalendarzu rekrutera.
    interview_slot_confirmed = "interview_slot_confirmed"
    # Rekruter zapisał debrief po rozmowie u klienta → DL wie, jak poszło.
    interview_debrief_saved = "interview_debrief_saved"
    # 0348: kolejka „Czeka na Ciebie" (Tablica). Rano JEDEN zbiorczy wpis na
    # osobę („4 osoby czekają na DZ, 1 do wysłania do Cpro") — dedup dobowy po
    # related_entity=(user, id). Emitowane przez `check_board_tasks_digest`.
    board_tasks_digest = "board_tasks_digest"
    # 0348: ktoś wytypował Cię do wysłania osoby do Cpro (Nordea) —
    # related_entity=(candidate_stage, id).
    cpro_send_assigned = "cpro_send_assigned"
    # 0352: ktoś przejął Twoją osobę w „Nowych" (przed upływem 12 h tylko
    # DL/HoR/admin) — related_entity=(recruitment_process, id).
    candidate_claim_taken = "candidate_claim_taken"
    # 0352: podpis umowy przeniósł osobę na „Zatrudniony", a zamówienia od
    # klienta jeszcze nie ma — do Finansów; related_entity=(contract, id).
    hired_order_missing = "hired_order_missing"
    # 0370: prep z kandydatem wymaga uwagi — słaby, bez nagrania albo go brak
    # na dobę przed rozmową u klienta. Do organizatora prepu i Head of
    # Recruitment; related_entity=(calendar_event, id) — jeden wpis na sprawę.
    prep_attention = "prep_attention"
    # 0371: follow-up z kandydatem przyniósł zmianę (inna oferta, rezygnacja
    # z procesu, dostępność) — do właściciela procesu; related_entity=
    # (candidate, id).
    candidate_followup_signal = "candidate_followup_signal"


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

    # Rezerwacja wiersza przez background task ZANIM poleci SMTP. Rozdzielona
    # od `email_sent_at`, bo stemplowanie „wysłane" przed faktyczną wysyłką
    # znaczy, że crash w tym oknie gubi maila na zawsze. Tutaj crash zostawia
    # rezerwację. Po rozpoczęciu wywołania zewnętrznego dodatkowa flaga
    # email_delivery_uncertain chroni przed ponowieniem po awarii procesu.
    email_send_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Retry scheduling and quarantine for a possibly accepted delivery.
    email_next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    email_delivery_uncertain: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user={self.user_id} type={self.notification_type} read={self.is_read}>"
