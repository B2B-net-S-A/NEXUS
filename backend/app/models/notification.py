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
    # 0603: kontraktor z wygasłego linku prosi o nowy (podpis w NEXUSIE,
    # 27.10.2026). Własny typ, bo dzienny dedup (user+typ+wniosek) zjadałby go
    # razem z dzwonkiem o wygaśnięciu z tego samego dnia.
    signature_renewal_requested = "signature_renewal_requested"
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
    # 0508: ktoś przegląda albo zapisuje na dysk CV kandydatów ponad normę —
    # alarm bez blokady do adminów i Head of Recruitment, mail od razu
    # (`services/candidate_data_access_alerts.py`).
    candidate_data_access_alert = "candidate_data_access_alert"
    # 0612 (28.10.2026): ktoś zalogował się pierwszy raz przez Microsoft —
    # Head of Recruitment i admini decydują, kim jest, i ustawiają rekrutera;
    # mail od razu (`services/new_person_setup.py`).
    new_person_signed_in = "new_person_signed_in"
    # 0619 (28.10.2026): Head of Recruitment albo admin opublikował ogłoszenie
    # oznaczone „ważne” — do odbiorców ogłoszenia (wszyscy albo wybrane role),
    # bez autora; related_entity=(announcement, id). Mail obowiązkowy
    # (`services/announcements.py`).
    announcement_important = "announcement_important"
    # 0510: aplikacja „NEXUS Teams Prep” nie ma dostępu do kalendarza DL-a,
    # rekrutera albo Head of Recruitment (poza grupą NEXUS-Meetings-Scope) —
    # dzienna lista do dopisania, tylko admini, mail od razu
    # (`services/teams_prep_scope.py`).
    teams_prep_scope_missing = "teams_prep_scope_missing"
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
    # related_entity=(user, id). Od 16.10.2026 nie powstaje (bez dzwonka).
    board_tasks_digest = "board_tasks_digest"
    # 0348: ktoś wytypował Cię do wysłania osoby do Cpro (Nordea) —
    # related_entity=(candidate_stage, id).
    cpro_send_assigned = "cpro_send_assigned"
    # 0408: karta właśnie trafiła do TWOJEJ kolejki na Tablicy — przegląd
    # Delivery Leada, kolejka Cpro albo zwrot z kolejki Cpro
    # (`stage_handoff_recipients.TASK_REASONS`). Imienne zadanie, więc osobny
    # typ poza wyciszalnym `stage_rule`; related_entity=(candidate_stage, id).
    board_task_waiting = "board_task_waiting"
    # 0417: rekruter prosi o potwierdzenie podpisu umowy B2B z Generatora —
    # do DL-a rekrutacji (albo portfela / TCM); related_entity=(b2b_generated_contract, id).
    b2b_signature_requested = "b2b_signature_requested"
    # 0524: umowę z Generatora wygenerował ktoś inny niż osoba prowadząca
    # kandydata w rekrutacji — dzwonek do prowadzącego (placement, premia
    # i pilnowanie podpisu są jego); related_entity=(b2b_generated_contract, id).
    b2b_agreement_ready = "b2b_agreement_ready"
    # 0418: zmiana stawki kandydata w procesie (od „Zweryfikowany”) — informacja
    # dla DL, Head of Recruitment i rekrutera kandydata; related_entity=
    # (candidate_rate_change, id).
    candidate_rate_change = "candidate_rate_change"
    # 0418: wzrost stawki po wysłaniu CV — zadanie Delivery Leada (decyzja
    # o stawce do klienta albo negocjacja). Kategoria obowiązkowa.
    candidate_rate_change_task = "candidate_rate_change_task"
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
    # 0453 (17.10.2026, D5–D8): odpowiedź kandydata na zaproszenie na prep
    # (przyjął / może — sam licznik; odmówił albo proponuje inny termin —
    # dymek), zmiana prepu przez kogoś z pary (`prep_changed_yours` do
    # prowadzącego, w którego kalendarzu stoi spotkanie — dymek; reszta pary
    # `prep_changed` — licznik) i brak odpowiedzi na dobę przed prepem.
    # related_entity=(<rodzaj zdarzenia>, calendar_event.id); zmiany prepu
    # (`prep_changed*`) bez id — dzienny dedup zjadałby drugą zmianę w dniu.
    prep_candidate_response = "prep_candidate_response"
    prep_candidate_declined = "prep_candidate_declined"
    prep_changed = "prep_changed"
    prep_changed_yours = "prep_changed_yours"
    prep_no_response = "prep_no_response"
    # 0482 (20.10.2026): rozmowa u klienta bez Prepu 2 — do Delivery Leada
    # rekrutacji (licznik), related_entity=(prep2_skip, id); przekroczony próg
    # pominięć w 30 dniach — do Head of Recruitment, related_entity=(user, id),
    # raz na 30 dni na osobę.
    prep2_skipped = "prep2_skipped"
    prep2_skip_threshold = "prep2_skip_threshold"
    # 0500 (21.10.2026): rozmowa u klienta przełożona albo odwołana w NEXUSIE —
    # do Delivery Leada, rekrutera pary i właściciela wydarzenia, bez autora
    # zmiany (dymek). related_entity=(client_interview_<rodzaj>, None), link
    # do pary — jak ``prep_changed*``: dzienny dedup zjadałby drugą zmianę.
    interview_changed = "interview_changed"
    # 0507 (22.10.2026): ocena prepu gotowa — do ludzi pary (prowadzący,
    # planujący, DL rekrutacji, rekruter kandydata), licznik bez dymka.
    # related_entity=(prep_review, calendar_event.id), dedup dobowy.
    prep_review_ready = "prep_review_ready"
    # 0506 (21.10.2026): umowa przedwstępna — prośba, wystawienie, podpisy,
    # wygasanie, rezygnacja kandydata, termin umowy B2B. Do proszących,
    # obserwujących i wystawiającego, bez autora zmiany.
    # related_entity=(pre_contract_event, id) — każdy krok to osobne
    # zdarzenie, więc dzienny dedup nie zjada drugiego kroku tego samego dnia.
    pre_contract = "pre_contract"
    # 0371: automat przydziału requestów — rano JEDEN wpis na osobę („Od dziś:
    # X. Zwolnione: Y (champion)”); related_entity=(user, id), dedup dobowy.
    # Od 02.10.2026 także od razu po akceptacji propozycji: „Nowy request do
    # pracy”, related_entity=(job, id).
    request_assignment_changed = "request_assignment_changed"
    # 0371: request do decyzji DL — nowy z Traffita „Do przejrzenia”, „Klient
    # milczy” od 14 dni albo „Szukamy” bez pracy od 30 dni;
    # related_entity=(user, id), jeden zbiorczy wpis na odbiorcę i dzień.
    request_review_needed = "request_review_needed"
    # 0523 (26.10.2026): ktoś (także sam DL) otworzył rekrutację (założył
    # albo otworzył ponownie) u klienta Delivery Leada — do DL-a rekrutacji,
    # bez niego do Head of Recruitment; related_entity=(job, id). Mail
    # obowiązkowy „Nowa rekrutacja u Twojego klienta”, kilka w 10 minut
    # jednym mailem (`services/client_job_opened.py`).
    client_job_opened = "client_job_opened"
    # 0526 (27.10.2026): przypomnienia o brakujących ogłoszeniach (strona
    # kariery, Pracuj.pl, JustJoin.IT) — mail obowiązkowy, codziennie rano
    # (`services/job_ad/reminders.py`). `job_ad_missing` — rekrutacja otwarta
    # po starcie przypomnień, related_entity=(job, id); `job_ad_backlog` —
    # zbiorczy o rekrutacjach sprzed startu, related_entity=(user, id);
    # `job_ad_nudge` — DL prosi rekrutera o stronę kariery,
    # related_entity=(job, id).
    job_ad_missing = "job_ad_missing"
    job_ad_backlog = "job_ad_backlog"
    job_ad_nudge = "job_ad_nudge"
    # 0525 (27.10.2026): Head of Recruitment albo admin ustawił rekrutacji P0
    # (ultrapilne przez 24 h) — do rekruterów i Delivery Leada rekrutacji,
    # bez osoby, która ustawiła; related_entity=(job, id). Mail obowiązkowy
    # „P0 na rekrutacji” (`services/job_p0.py`).
    job_p0_set = "job_p0_set"
    # 0607 (28.10.2026): ktoś zamknął rekrutację, w której Twoje osoby stoją
    # od „CV wysłane” w górę — daj im znać; related_entity=(job, id), bez
    # osoby, która zamknęła. Mail obowiązkowy „Rekrutacja zamknięta — Twoje
    # osoby czekają” (`services/job_closed_notices.py`).
    job_closed_people_waiting = "job_closed_people_waiting"
    # 0610 (28.10.2026): Delivery Lead prosi o P0 dla swojej rekrutacji —
    # do Head of Recruitment (zatwierdza albo odrzuca); related_entity=(job, id).
    # Mail obowiązkowy jak przy P0 (`services/job_p0.py`).
    job_p0_requested = "job_p0_requested"
    # 0617 (28.10.2026): rekrutacje bez ruchu Delivery Leada — JEDEN wpis
    # dziennie na osobę: DL (14 i 21 dni), Head of Recruitment (21 dni)
    # i oboje przy zamknięciu przez NEXUS (28 dni); related_entity=(user, id).
    # Mail obowiązkowy (`services/job_idle.py`).
    job_idle_reminder = "job_idle_reminder"
    # 0374: praktykant kończy program wdrożenia (5 dni roboczych przed końcem)
    # — decyzja Head of Recruitment; related_entity=(user, id), raz na program.
    trainee_program_decision = "trainee_program_decision"
    # 0372: follow-up z kandydatem przyniósł zmianę (inna oferta, rezygnacja
    # z procesu, dostępność) — do właściciela procesu; related_entity=
    # (candidate, id).
    candidate_followup_signal = "candidate_followup_signal"
    # 0399: ktoś odpowiedział na Twoją notatkę — link prowadzi do notatki
    # głównej; related_entity=(note, id odpowiedzi).
    note_reply = "note_reply"
    # 0404: rano JEDEN skrót na rekrutację — „N zgłoszeń odrzuconych przez AI”
    # (poprzednie dni). Do prowadzącego rekrutację; related_entity=(job, id).
    application_screening_digest = "application_screening_digest"
    # 0409: propozycje automatu przydziału czekają na akceptację — JEDEN wpis
    # dziennie na Head of Recruitment z aktualną liczbą; related_entity=
    # (user, id). Osoba z propozycji nie dostaje nic, dopóki ktoś jej nie
    # zaakceptuje (wtedy `request_assignment_changed`).
    request_allocation_proposals = "request_allocation_proposals"
    # 0431: osoba, która u nas pracuje, została zatrudniona w innej rekrutacji
    # albo jej CV poszło do innego klienta — do Delivery Leada klienta,
    # u którego pracuje (admini jako zapas); related_entity=
    # (candidate_stage, id wiersza etapu). Bez maila.
    consultant_in_other_recruitment = "consultant_in_other_recruitment"
    # 0440: automat auto-CV podpiął CV firmowe po ruchu na „Zweryfikowany”
    # i QC je policzyło („CV gotowe do sprawdzenia”) albo automat go nie zrobił
    # z powodem, przy którym rekruter musi zadziałać sam. Do osoby, która
    # przesunęła kartę; related_entity=(candidate_stage, id). Bez maila.
    cv_ready = "cv_ready"
    # 0444: ktoś dodał osobę do rekrutacji z podpowiedzi „Pasuje też do”
    # (okno „Kandydaci do dodania” innej rekrutacji). Do rekruterów tej
    # rekrutacji, bez osoby, która dodała; related_entity=(candidate, id).
    # Bez maila.
    also_fits_added = "also_fits_added"
    # 0517 (23.10.2026): osoby od silnika „Nowi na 20” czekają ponad 2 dni
    # robocze na decyzję („Dzwonię” albo odrzucenie z powodem). Jeden poranny
    # dzwonek na Rekrutera; related_entity=(user, id). Bez maila.
    autofill_decisions_due = "autofill_decisions_due"
    # 0518 (23.10.2026): raport poniedziałkowy „Jakość podpowiedzi systemu”
    # gotowy — do odbiorców raportu; related_entity=(autofill_quality_report, id).
    autofill_quality_report = "autofill_quality_report"
    # 0447: „Poprzedni rekruter” — rekrutacja zeszła z P1, osoba przeszła do
    # poprzednich rekruterów (``recruiter_parked``) albo wróciła na P1 i osoba
    # znowu nad nią pracuje (``recruiter_restored``). Do osób z zespołu poza
    # tą, która zmieniła priorytet; related_entity=(job, id). Bez maila.
    recruiter_parked = "recruiter_parked"
    recruiter_restored = "recruiter_restored"
    # 0450: championi rekrutacji (D8, 15.10.2026) — Delivery Lead zapisał
    # listę championów (``champions_changed``) albo odpadł ostatni champion
    # i rekrutacja wraca do szukania (``champion_search_resumed``). Do
    # rekruterów i Delivery Leada rekrutacji poza osobą, która zmieniła listę;
    # related_entity=(job, id). Bez maila.
    champions_changed = "champions_changed"
    champion_search_resumed = "champion_search_resumed"
    # 0615: bliźniacze rekrutacje (28.10.2026) — ktoś połączył rekrutację
    # z bliźniakiem. Do rekruterów i Delivery Leadów obu rekrutacji poza
    # osobą, która połączyła; link do rekrutacji. Bez maila.
    job_twin_linked = "job_twin_linked"
    # 0451: karta weszła na etap „Akceptacja” — klient zaakceptował osobę
    # (D1–D6, 16.10.2026). Do rekrutera kandydata, prowadzącego, Delivery
    # Leada rekrutacji i każdego Head of Recruitment poza osobą, która
    # zaznaczyła; related_entity=(candidate_stage, id). Kategoria „Akceptacje
    # klienta” nie do wyciszenia; od 22.10.2026 także mail (`client_accepted`
    # w `notification_delivery.BELL_MAIL_TYPES`).
    client_accepted = "client_accepted"
    # 0452: ręczne „Potwierdź zatrudnienie”, a w Kontraktach nie ma umowy osoby
    # u klienta rekrutacji — „Pracuje u nas” liczy się wyłącznie z umowy
    # (17.10.2026). Do Delivery Leadów klienta, raz na parę osoba–rekrutacja;
    # related_entity=(candidate_stage, id). `services/hire_contract_reminder.py`.
    hire_missing_contract = "hire_missing_contract"
    # 0457: „Ludzie w NEXUSIE” — moduły kadrowe. Osobiste (odbiorcę wybiera
    # reguła modułu, nie sekcja): urlopy, timesheety, premie i stawki,
    # wejście/odejście, sprawy administracja@, sprzęt. Opieka nad konsultantem
    # (``care_contact_due``) prowadzi do kontraktu — sekcja Delivery. Lista
    # wartości: ``app/services/hr_notification_schema.py``.
    hr_leave_requested = "hr_leave_requested"
    hr_leave_decided = "hr_leave_decided"
    hr_leave_cancelled = "hr_leave_cancelled"
    hr_leave_substitute = "hr_leave_substitute"
    hr_absence_reported = "hr_absence_reported"
    hr_leave_conflict = "hr_leave_conflict"
    hr_timesheet_submitted = "hr_timesheet_submitted"
    hr_timesheet_decided = "hr_timesheet_decided"
    hr_timesheet_reminder = "hr_timesheet_reminder"
    hr_bonus_assigned = "hr_bonus_assigned"
    hr_rate_changed = "hr_rate_changed"
    hr_lifecycle_task = "hr_lifecycle_task"
    hr_work_handover = "hr_work_handover"
    admin_case_assigned = "admin_case_assigned"
    equipment_task = "equipment_task"
    equipment_protocol_signed = "equipment_protocol_signed"
    # 0479: „Przypomnij” o zwrocie sprzętu — recepcja → posiadacz z kontem.
    equipment_return_reminder = "equipment_return_reminder"
    # „Przekaż do front office” (D15): konsultant kończy projekt albo chce
    # zmiany — head pionu front office, Head of Recruitment i Delivery Leadzi;
    # osobisty (bez sekcji), bo front office nie ma sekcji Delivery.
    care_front_office_handoff = "care_front_office_handoff"
    # 0466: komunikat do konsultantów (O12) — do zatwierdzenia (head back
    # office, admin), decyzja (autor), odbity mail (opiekun: „popraw e-mail”).
    # Osobisty, link do `/care?tab=announcements` albo do kontraktu.
    care_announcement = "care_announcement"
    # 0466: rozliczenia zespołu — prośba o korektę faktury (osoba), rozliczenie
    # opłacone (osoba), rozbieżność / uznanie różnicy do drugiej osoby (Płace).
    # Bez kwot w tytule i treści; link do „Mojego czasu” albo kolejki Płac.
    hr_settlement_correction = "hr_settlement_correction"
    hr_settlement_paid = "hr_settlement_paid"
    hr_settlement_review = "hr_settlement_review"
    hr_agreement_update = "hr_agreement_update"
    # 0483: zgody na wydatki i premie poza umową — zgoda do decyzji
    # (przełożony albo zatwierdzający z Ustawień, mail z kwotą i przyciskami)
    # i decyzja do autora. Osobiste, link do „Ludzie → Akceptacje → Zgody”.
    hr_approval_requested = "hr_approval_requested"
    hr_approval_decided = "hr_approval_decided"
    # 0486: rozliczenie zgód — prośba o dopłatę (faktura wyższa o więcej niż
    # 10%) do zatwierdzającego i pytanie o odnowienie rocznej subskrypcji do
    # jej opiekuna. Link do „Akceptacji → Zgody” albo „Moich zgód”.
    hr_approval_topup_requested = "hr_approval_topup_requested"
    hr_subscription_renewal = "hr_subscription_renewal"
    care_contact_due = "care_contact_due"
    # 0475: „uzupełnij strukturę klienta X” — konsultanci bez menedżera
    # u klienta (propozycje automatu czekają na akcept Delivery Leada).
    # Sekcja Delivery, link do `/care?tab=structure&client=<id>`.
    care_client_structure = "care_client_structure"
    # 0509: „klient zatrudnia” z rozmowy opiekuna — karta „Popyt do
    # sprawdzenia” u Delivery Leada klienta. Sekcja Delivery, link
    # `/care?card=<klucz karty>`.
    care_demand_signal = "care_demand_signal"


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
