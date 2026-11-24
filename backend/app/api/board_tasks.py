"""Router `/api/board-tasks` — kolejka „Czeka na Ciebie" (0348, Rekrutacja v5).

Odczyt listy (do wysłania do Cpro, wysłane do Cpro, przegląd DL przed
wysłaniem CV do klienta), kolejka Cpro całej firmy i osoba, która wysyła do
Cpro — JEDNA na firmę (`services/cpro_sender.py`, decyzja Artura 23.09.2026).
Przegląd DZ (0353) zniknął 24.09.2026 — zastąpiło go QC CV
(`/api/pipeline/stages/{id}/qc`).

Samo wrzucenie do Cpro i zwrot do rekrutera to zwykły ruch w pipeline
(`POST /api/pipeline/move`) — ta trasa nie ma własnej ścieżki zapisu etapu,
żeby reguły ruchu (wersja procesu, ostrzeżenia dopuszczalności, QC CV)
obowiązywały bez kopii.

Od 02.10.2026 lista niesie też propozycje automatu przydziału do akceptacji
(`services/request_allocation_proposals.py`) — wyłącznie dla admina i Head of
Recruitment. Decyzje zapisuje `/api/request-board` (akceptacja, zamiana,
odrzucenie). Te same osoby dostają listę informacyjną „kto prowadzi nowe
rekrutacje” (`services/new_job_leads.py`).

Od 04.10.2026 (rekrutacja bez szkiców) dochodzą dwie listy
z `services/pending_job_completion.py`: rekrutacje do dokończenia (stare
szkice i opublikowane bez przekazania do searchu) oraz niedokończone
formularze „Nowa rekrutacja” tej osoby.
"""

import logging
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_followups import FollowupRow, serialize_rows
from app.api.deps import OperationalUser
from app.api.recruitment_access import PROPOSAL_DECISION_ROLES
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services.workforce_availability import operational_owner_ids
from app.services import agreement_tasks, rate_change_tasks
from app.services import board_tasks as svc
from app.services.stage_client_rate import latest_client_rates
from app.services.cpro_bot import items as cpro_bot_items
from app.services.cpro_bot import runs as cpro_bot_runs
from app.services.cpro_bot.accounts import CproAccountName
from app.core.scheduling import business_date, local_day_start_utc
from app.services.contract_availability import load_contract_free
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services import (
    board_flow,
    candidate_followups,
    screening_calls,
    closing_candidates,
    cpro_sender,
    cv_in_transit,
    cv_topic,
    dl_send_queue,
    move_requirements,
    new_job_leads,
    new_person_setup,
    pending_job_completion,
    prep_attention,
    request_allocation_proposals,
    stage_handoff_recipients,
    stage_remarks,
)
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

from app.api.cpro_operator import router as cpro_operator_router  # noqa: E402

router.include_router(cpro_operator_router, prefix="/cpro/operator")


class BoardTaskRow(BaseModel):
    # Wiersz nieobecnego DL-a, którego oglądający zastępuje.
    on_behalf_of_name: Optional[str] = None
    kind: Literal["cpro_to_send", "cpro_sent", "dl_review"]
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    since: datetime
    process_state_version: int
    target_stage_def_id: Optional[int] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    # Tylko przegląd DL (`dl_review`); przy pozostałych rodzajach puste.
    rejected_stage_def_id: Optional[int] = None
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    expected_rate_value: Optional[float] = None
    expected_rate_unit: Optional[str] = None
    expected_rate_currency: Optional[str] = None
    screening_stage_id: Optional[int] = None
    job_sender_id: Optional[int] = None
    job_sender_name: Optional[str] = None
    # Etap powrotu do poprawy: kolejka Cpro — „QC CV” („Zwróć do rekrutera"),
    # przegląd DL — „Zweryfikowany” („Wróć do poprawy”).
    return_stage_def_id: Optional[int] = None
    # Przegląd DL i kolejka Cpro: wynik QC CV pary.
    qc_status: Optional[Literal["passed", "failed", "overridden", "unchecked"]] = None
    qc_blocking_failed: int = 0
    # R1 (07.11.2026): zdane QC z blokującymi sprawdzeniami „sprawdź ręcznie”.
    qc_manual: list[str] = Field(default_factory=list)
    # R2 (07.11.2026): luki kandydata w krytycznych — decyzja Delivery Leada.
    qc_gaps: list[str] = Field(default_factory=list)
    # QC-11 (08.11.2026): gotowy stan QC do pokazania.
    qc_state: Optional[dict] = None
    # Klient z formularzem CV (23.11.2026): ``{template, missing}``; ``None`` =
    # CV firmowe. Przegląd pokazuje wtedy formularz zamiast QC CV firmowego.
    client_form: Optional[dict] = None
    # Przegląd DL: stan karty rekomendacji; ``None`` = para nie ma karty.
    card_status: Optional[Literal["complete", "partial", "empty"]] = None
    card_missing: int = 0
    # 0380: ``job_title`` = nazwa od klienta; tytuł dla rekrutera i numer u
    # klienta osobno (Cpro dostaje nazwę i numer klienta).
    job_working_title: Optional[str] = None
    client_reference: Optional[str] = None
    # Przegląd DL: etap z CV firmowym pary (po poprawkach QC). Runda 7
    # (R7-X4-2): podgląd i „Pobierz DOCX" biorą CV etapu, nie surowy plik
    # z generatora — do klienta ma iść to, co przeszło QC.
    cv_stage_id: Optional[int] = None
    # „Do wysłania do klienta” (13.10.2026, `services/dl_send_queue.py`) —
    # tylko przegląd DL. ``ready`` = QC zdane albo przepuszczone; czas i pilność
    # liczą się od ``ready_since``; ``imported`` = etap z importu Traffita,
    # którego nikt nie ruszył w NEXUSIE (poza licznikami).
    ready: bool = False
    ready_since: Optional[datetime] = None
    waiting_workdays: int = 0
    urgency: Optional[Literal["fresh", "due", "late"]] = None
    imported: bool = False
    handed_over_by_name: Optional[str] = None
    budget_min_hourly: Optional[float] = None
    budget_max_hourly: Optional[float] = None
    deadline: Optional[date] = None
    # Przegląd DL u Nordei (13.10.2026): akceptacja do kolejki Cpro, a
    # ``target_stage_def_id`` to etap „Wysłać do Cpro”.
    cpro: bool = False


class DlSendRow(BaseModel):
    """Wiersz okienka „Do wysłania” w górnym pasku.

    Celowo węższy niż `BoardTaskRow`: przegląd otwiera się z pełnego wiersza
    (`/dl-review-row`), nie z tego — brak tu wersji procesu i etapów ruchu.
    """

    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    ready_since: datetime
    waiting_workdays: int
    urgency: Literal["fresh", "due", "late"]
    handed_over_by_name: Optional[str] = None
    # Nordea: osoba czeka na akceptację do kolejki Cpro.
    cpro: bool = False
    # Wiersz należy do nieobecnego DL-a, którego oglądający zastępuje.
    on_behalf_of_name: Optional[str] = None


class DlSendQueueResponse(BaseModel):
    ready: list[DlSendRow]
    ready_total: int
    # Kolumna „QC CV”, ale ruch ma jeszcze rekruter (QC do poprawy albo
    # niesprawdzone) — sama liczba, żeby okienko mówiło „N jeszcze u rekrutera”.
    not_ready_total: int
    imported_total: int
    worst_urgency: Optional[Literal["fresh", "due", "late"]] = None


class PrepAttentionRow(BaseModel):
    """Prep przed rozmową u klienta wymagający uwagi (0370)."""

    reason: Literal["missing", "late", "weak", "unrecorded"]
    prep_no: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    interview_event_id: int
    interview_start: datetime
    prep_event_id: Optional[int] = None
    owner_id: Optional[int] = None
    urgent: bool = False


class AllocationProposalRow(BaseModel):
    """Propozycja automatu przydziału czekająca na decyzję (02.10.2026).

    Kształt = ``request_allocation_proposals.PendingProposal``.
    """

    job_id: int
    title: str
    client_name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_slug: Optional[str] = None
    delivery_lead_name: Optional[str] = None
    priority_level: Literal["p1", "p2", "accepting"]
    deadline: Optional[date] = None
    sent: int
    user_id: int
    user_name: str
    role: Literal["recruiter"]
    fit: Literal["first", "second", "other"]
    load: int
    leave_until: Optional[date] = None
    base_matches: Optional[int] = None
    proposed_at: datetime


class NewPersonSetupRow(BaseModel):
    """Osoba do ustawienia (0612) — kształt = ``new_person_setup.NewPersonRow``."""

    user_id: int
    name: str
    email: str
    since: datetime
    # Konto po pierwszym logowaniu — nikt jeszcze nie zdecydował, kim jest.
    needs_decision: bool
    # Czego brakuje rekruterowi: "categories", "manager".
    missing: list[str] = []


class NewJobLeadRow(BaseModel):
    """Rekrutacja P1 z cyklem z ostatnich dni i jej prowadzący.

    Kształt = ``new_job_leads.NewJobLead``.
    """

    job_id: int
    title: str
    client_name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_slug: Optional[str] = None
    # Ilu uczestników z kategorii ma rekrutacja (bez osób z niej zdjętych).
    participants: int
    priority_level: Literal["p1", "p2", "accepting"]
    delivery_lead_name: Optional[str] = None
    # Początek bieżącego cyklu listy i co go zaczęło: przekazanie do searchu,
    # ponowne otwarcie albo wejście na P1 (14.10.2026).
    handed_off_at: datetime
    since_reason: Literal["handoff", "reopen", "p1"] = "handoff"
    lead_user_id: Optional[int] = None
    lead_name: Optional[str] = None
    lead_role: Optional[Literal["recruiter"]] = None
    # Kto wskazał prowadzącego: automat przydziału albo człowiek.
    lead_source: Optional[Literal["auto", "manual"]] = None
    assigned_by_name: Optional[str] = None
    # Jedyna osoba to propozycja automatu czekająca na akceptację — wtedy
    # pola `lead_*` opisują osobę proponowaną.
    proposed: bool = False
    # Nikt nie prowadzi: automat właśnie przydziela, rekrutacja tylko
    # przyjmuje kandydatów albo po prostu nikogo nie ma. `not_handed_off`
    # (audyt 06.10.2026, H7): opublikowana, ale nigdy nie przekazana do
    # searchu — `handed_off_at` niesie wtedy datę założenia.
    pending_reason: Optional[
        Literal["assigning", "passive", "none", "not_handed_off"]
    ] = None
    # Wiersz wrócił: w tym cyklu Head of Recruitment zdecydował o innej osobie
    # (albo nikt już nie prowadzi) — kto to był.
    returned_from_user_id: Optional[int] = None
    returned_from_name: Optional[str] = None


class PendingJobRow(BaseModel):
    """Rekrutacja do dokończenia (`pending_job_completion.PendingJob`)."""

    job_id: int
    title: str
    client_name: Optional[str] = None
    kind: Literal["legacy_draft", "published_not_handed_off"]
    created_at: datetime
    delivery_lead_name: Optional[str] = None
    # Zdania braków — ta sama lista co przycisk „Przekaż do searchu”.
    missing: list[str] = []


class PendingJobsBlock(BaseModel):
    # Dzień, od którego stare szkice zamykają się same (`None`, gdy na liście
    # nie ma szkicu albo znacznik wdrożenia jeszcze nie istnieje).
    autoclose_on: Optional[date] = None
    items: list[PendingJobRow]


class RequirementFixReason(BaseModel):
    code: str
    text: str


class RequirementFixRow(BaseModel):
    """„Wymagania do poprawy” — kształt ``requirement_cleanup.load_fixes``."""

    job_id: int
    title: str
    reasons: list[RequirementFixReason]
    can_apply: bool
    rows: int
    talk: int


class UnfinishedFormRow(BaseModel):
    """Mój formularz „Nowa rekrutacja” leżący dłużej niż 2 dni."""

    id: int
    label: str
    client_name: Optional[str] = None
    updated_at: datetime


class CvTransitRow(BaseModel):
    """Wiersz listy „Twoje CV w drodze” (`services/cv_in_transit.py`)."""

    kind: Literal[
        "rejected_by_dl",
        "sent_back",
        "cpro_returned",
        "in_review",
        "cpro_queue",
        "sent",
    ]
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    since: datetime
    actor_name: Optional[str] = None
    holder_name: Optional[str] = None
    reason: Optional[str] = None
    # Uwaga dla rekrutera zostawiona przy decyzji (początek; całość w notatce).
    remark: Optional[str] = None
    # D4 (04.10.2026): kto poprawił kartę rekomendacji od przekazania i co.
    card_edited_by: Optional[str] = None
    card_edited_fields: list[str] = []
    # D6 (08.10.2026): pola, które Delivery Lead wskazał do poprawy.
    fix_labels: list[str] = []
    # 13.10.2026, tylko „QC CV” poza Nordeą (`in_review`): stan QC pary, od
    # kiedy CV jest gotowe i czeka na Delivery Leada (dni robocze) oraz czy
    # rekruter może już przypomnieć (`POST /dl-send/{stage_id}/nudge`).
    qc_status: Optional[Literal["passed", "failed", "overridden", "unchecked"]] = None
    ready_since: Optional[datetime] = None
    waiting_workdays: int = 0
    can_nudge: bool = False


class CvInTransitBlock(BaseModel):
    returned: list[CvTransitRow]
    in_review: list[CvTransitRow]
    sent: list[CvTransitRow]
    # Liczby przed przycięciem list do `MAX_ROWS`.
    returned_total: int
    # Bez odrzuceń przez DL — tylko to, co rekruter ma poprawić (23.10.2026).
    returned_to_fix_total: int = 0
    in_review_total: int
    sent_total: int
    returned_window_days: int
    sent_window_days: int


class AgreementTaskRow(BaseModel):
    """Sprawa z grupy „Umowy” (`services/agreement_tasks.py`)."""

    generated_id: int
    contract_number: str
    # requested | hired_unsigned | closed_unsigned | closed_signed_active
    reason: str
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    since: Optional[datetime] = None
    requested_by_name: Optional[str] = None
    contract_id: Optional[int] = None


class AgreementTasksBlock(BaseModel):
    # Do potwierdzenia podpisu (prośby i „Zatrudniony” bez podpisu) i do
    # zamknięcia (karta zamknięta przy żywej umowie) — osoby z „Podpis B2B”.
    to_confirm: list[AgreementTaskRow] = []
    to_close: list[AgreementTaskRow] = []
    # Prośby tej osoby, na które czeka („U innych”).
    waiting_on_others: list[AgreementTaskRow] = []


class FlowPostingRow(BaseModel):
    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    count: int
    oldest_at: datetime


class FlowNewRequestRow(BaseModel):
    """„Nowe requesty dla Ciebie” (audyt 06.10.2026, H2)."""

    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    assigned_at: datetime
    # `None` = przydział automatu.
    assigned_by_name: Optional[str] = None


class BookedCallRow(BaseModel):
    """Umówiony telefon na screening w „Czeka na Ciebie” (03.11.2026)."""

    event_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    start_time: datetime
    note: Optional[str] = None
    in_outlook: bool = False


class FlowPairRow(BaseModel):
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    since: datetime
    claimed_until: Optional[datetime] = None
    # Screening: czego brakuje do „Zweryfikowany” (`sheet`, `rate`).
    # `why_candidate`: rekrutacja bez pytań — brakuje oceny zamiast arkusza.
    missing: list[Literal["sheet", "why_candidate", "rate"]] = []
    # Umówiony telefon tej osoby — lista „brakuje danych” mówi, kiedy będzie okazja.
    call_at: Optional[datetime] = None
    # Zweryfikowany: stan QC CV (`passed`, `failed`, `overridden`, `unchecked`).
    qc_status: Optional[str] = None


class FlowProposalPerson(BaseModel):
    candidate_id: int
    candidate_name: str
    score: Optional[float] = None


class FlowJobProposals(BaseModel):
    """Najlepsze otwarte propozycje z bazy jednej rekrutacji (07.10.2026)."""

    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    total: int
    people: list[FlowProposalPerson]


class FlowAutofillDecision(BaseModel):
    """Osoba od systemu czekająca na decyzję (silnik „Nowi na 20”, 23.10.2026)."""

    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    candidate_id: int
    candidate_name: str
    score: Optional[int] = None
    waiting_days: int


class FlowContractRow(BaseModel):
    id: int
    contract_number: str
    partner_name: Optional[str] = None
    client_name: Optional[str] = None
    created_at: datetime
    esign_status: Optional[Literal["sent", "contractor_signed"]] = None


class FlowBlockOut(BaseModel):
    """„Twój ruch” od Ogłoszeń do umowy (`services/board_flow.py`)."""

    applies: bool
    new_requests: list[FlowNewRequestRow] = []
    new_request_days: int = board_flow.NEW_REQUEST_DAYS
    postings: list[FlowPostingRow]
    postings_total: int
    claimed: list[FlowPairRow]
    screening: list[FlowPairRow]
    verified: list[FlowPairRow]
    waiting_client: list[FlowPairRow]
    waiting_client_days: int
    unsigned_contracts: list[FlowContractRow]
    order_mail_review: int
    # 07.10.2026: najlepsze propozycje nocnego przeglądu w rekrutacjach osoby.
    top_proposals: list[FlowJobProposals] = []
    top_proposals_per_job: int = board_flow.TOP_PROPOSALS_PER_JOB
    # 23.10.2026: osoby od systemu po 2 dniach roboczych bez decyzji.
    autofill_decisions: list[FlowAutofillDecision] = []
    autofill_decisions_total: int = 0


class FinanceBlockOut(BaseModel):
    gaps_open: int
    pdfs_new: int
    order_mail_failed: int
    hired_without_order: list[FlowPairRow]
    hired_without_order_total: int


class RateChangeTaskRow(BaseModel):
    """Sprawa zmiany stawki kandydata (`services/rate_change_tasks.py`)."""

    change_id: int
    # decide | negotiate | waiting
    reason: str
    status: str
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    previous_label: Optional[str] = None
    requested_label: str
    agreed_label: Optional[str] = None
    negotiator_name: Optional[str] = None
    negotiation_due: Optional[date] = None
    since: datetime
    waiting_on: Optional[str] = None


class BoardTasksResponse(BaseModel):
    cpro_to_send: list[BoardTaskRow]
    cpro_sent: list[BoardTaskRow]
    dl_review: list[BoardTaskRow]
    window_days: int
    dl_review_window_days: int
    # Ruch na „CV wysłane" ze stawką do klienta (u klientów spoza Nordei)
    # wykonuje wyłącznie osoba z uprawnieniem `recruitment_manage` (domyślnie
    # admin i Delivery Lead) — Head of Recruitment widzi kolejkę, ale serwer
    # odmówiłby mu wysyłki.
    can_send_to_client: bool
    # 0370: brak prepu, prep słaby albo bez nagrania — organizator i HoR.
    prep_attention: list[PrepAttentionRow] = []
    # 0372: follow-up z kandydatem, gdy klient milczy — telefony tej osoby
    # (termin do końca jutra) i kandydaci, u których prowadzi proces, a dzwoni
    # ktoś inny.
    booked_calls: list[BookedCallRow] = []
    followups: list[FollowupRow] = []
    followups_by_others: list[FollowupRow] = []
    # Czy ta osoba może ustawić osobę od Cpro (admin albo DL Nordei) — front
    # pokazuje przełącznik także wtedy, gdy nie widzi żadnego zadania Cpro.
    can_set_cpro_sender: bool = False
    # 02.10.2026: propozycje automatu przydziału do akceptacji. Wiersze dostaje
    # wyłącznie osoba, która o nich decyduje (admin, Head of Recruitment).
    allocation_proposals: list[AllocationProposalRow] = []
    can_decide_proposals: bool = False
    # Czy urlopy z Compassa są włączone i świeże. Bez tego puste „na urlopie
    # do” znaczy „nie wiadomo”, a nie „osoba dziś pracuje”.
    allocation_leave_known: bool = False
    # Kto prowadzi rekrutacje przekazane do searchu w ostatnich dniach — lista
    # informacyjna, tylko dla admina i Head of Recruitment.
    new_job_leads: list[NewJobLeadRow] = []
    # 0612 (28.10.2026): „Nowe osoby do ustawienia” — admin i Head of
    # Recruitment. `None` = liczenie się nie powiodło.
    new_people: Optional[list[NewPersonSetupRow]] = []
    # „Twoje CV w drodze” — druga strona przekazań, dla rekrutera kandydata.
    # `None` = osoba usunęła listę z pulpitu albo liczenie się nie powiodło.
    cv_in_transit: Optional[CvInTransitBlock] = None
    # 04.10.2026: rekrutacje do dokończenia. `None` = osoba ich nie widzi
    # (tylko DL, HoR i admin) albo nie ma żadnej.
    pending_jobs: Optional[PendingJobsBlock] = None
    unfinished_forms: list[UnfinishedFormRow] = []
    # 13.10.2026 (D4): porządki wymagań otwartych rekrutacji — Delivery Lead
    # swoich, Head of Recruitment i admin wszystkich.
    # `None` = liczenie się nie powiodło (awaria nie wygląda jak „nic do poprawy”).
    requirement_fixes: Optional[list[RequirementFixRow]] = []
    # 04.10.2026: umowy z Generatora — prośby o podpis i rozjazdy z Tablicą.
    # `None` = liczenie się nie powiodło.
    agreements: Optional[AgreementTasksBlock] = None
    # 04.10.2026: cały przepływ (Ogłoszenia, Nowi z blokadą, Screening,
    # Zweryfikowany, sprawy DL). `None` = rola bez tych sekcji.
    flow: Optional[FlowBlockOut] = None
    # 04.10.2026: praca Finansów (braki, PDF-y, zatrudnieni bez zamówienia).
    finance: Optional[FinanceBlockOut] = None
    # 0418: zmiany stawki kandydata — decyzja DL i negocjacja („Twój ruch”),
    # zgłoszenia czekające na innych („U innych”).
    rate_changes: list[RateChangeTaskRow] = []
    rate_changes_by_others: list[RateChangeTaskRow] = []


class CproSenderRead(BaseModel):
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    until: Optional[date] = None
    fallback_user_id: Optional[int] = None
    fallback_user_name: Optional[str] = None
    set_by_name: Optional[str] = None
    set_at: Optional[datetime] = None
    # Czy PYTAJĄCY może zmienić osobę (`cpro_sender.can_set_sender`).
    can_set: bool = False


class CproSenderUpdate(BaseModel):
    # `null` = nikt nie wysyła (kolejka wraca do DL / Head of Recruitment).
    user_id: Optional[int] = None
    # Ostatni dzień zastępstwa; potem wraca poprzednia osoba.
    until: Optional[date] = None


class CproQueueCv(BaseModel):
    # Etap z CV firmowym pary — wtedy plik bierzemy z etapu (po QC), nie
    # z generatora (runda 7, R7-X4-2).
    stage_id: Optional[int] = None
    generated_document_id: Optional[int] = None
    document_id: Optional[int] = None
    # CV etapu jest szkicem: akceptacja DL-a nie zdołała go zatwierdzić
    # (`cv_dl_accept_finalize`), więc „CV” pobierze plik „SZKIC_…”.
    draft: bool = False
    # Szkic czeka na kontrolę AI w tle po akceptacji DL-a; po niej zostanie
    # zatwierdzony i „CV” da plik bez „SZKIC_” (10.11.2026).
    review_pending: bool = False


class CproBotItem(BaseModel):
    """Bot Cpro przy osobie, gdy działa tryb szkiców albo wysyłki.

    ``blocked`` — braki w NEXUSIE (lista w ``blockers``), ``ready`` — bot
    weźmie osobę w najbliższym biegu, ``working`` — bot wypełnia Cpro,
    ``submitted`` — oferta wysłana (``moved=False``: kartę trzeba przesunąć
    ręcznie), ``draft`` — szkic do oceny w trybie draft, ``failed``/``skipped`` — bot nie
    wrzucił (``message``), ``retry`` — bieg padł, bot spróbuje jeszcze raz.
    """

    state: Literal[
        "blocked",
        "ready",
        "working",
        "submitted",
        "draft",
        "failed",
        "skipped",
        "retry",
    ]
    mode: Literal["draft", "submit"] = "submit"
    retry_allowed: bool = True
    blockers: list[str] = Field(default_factory=list)
    message: Optional[str] = None
    offer_url: Optional[str] = None
    cpro_status: Optional[str] = None
    at: Optional[datetime] = None
    moved: Optional[bool] = None
    data_from: list[str] = Field(default_factory=list)


class CproBotSummary(BaseModel):
    mode: Literal["draft", "submit"] = "submit"
    configured: bool
    working: bool
    last_run_at: Optional[datetime] = None
    sent_today: int = 0
    drafts_today: int = 0
    awaiting_review: int = 0
    can_retry: bool = False


class CproOperatorDraft(BaseModel):
    delivery_lead_id: int
    cpro_account_name: Optional[CproAccountName] = None
    request_number: str
    state: Literal["ready", "started", "received"]
    run_id: Optional[int] = None


class CproOperatorStatus(BaseModel):
    delivery_lead_id: int
    cpro_account_name: Optional[CproAccountName] = None
    request_number: str
    state: Literal["working", "draft"]
    offer_id: Optional[str] = None


class CproQueueItem(BaseModel):
    stage_id: int
    candidate_id: int
    candidate_name: str
    since: datetime
    process_state_version: int
    target_stage_def_id: Optional[int] = None
    return_stage_def_id: Optional[int] = None
    client_rate_value: Optional[float] = None
    client_rate_unit: Optional[str] = None
    client_rate_currency: Optional[str] = None
    availability: Optional[date] = None
    qc_status: Literal["passed", "failed", "overridden", "unchecked"] = "unchecked"
    qc_blocking_failed: int = 0
    # QC-11 (08.11.2026): gotowy stan QC do pokazania.
    qc_state: Optional[dict] = None
    cv: Optional[CproQueueCv] = None
    # Kto włożył osobę do kolejki i kiedy. Od 13.10.2026 robi to wyłącznie
    # Delivery Lead po akceptacji (``accepted``); wcześniej także rekruter —
    # taka karta ma ``accepted=False`` („Bez akceptacji DL”).
    accepted: bool = False
    accepted_by_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    # Uwaga Delivery Leada zapisana przy akceptacji (`stage_remarks`).
    dl_note: Optional[str] = None
    # Bot Cpro; ``None``, gdy oba tryby automatu są wyłączone.
    bot: Optional[CproBotItem] = None
    operator_draft: Optional[CproOperatorDraft] = None
    operator_status: Optional[CproOperatorStatus] = None


class CproQueueJob(BaseModel):
    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_reference: Optional[str] = None
    client_name: Optional[str] = None
    oldest_since: datetime
    items: list[CproQueueItem]


class CproQueueResponse(BaseModel):
    sender: CproSenderRead
    jobs: list[CproQueueJob]
    sent_today: int
    bot: Optional[CproBotSummary] = None


@router.get("", response_model=BoardTasksResponse)
async def list_board_tasks(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> BoardTasksResponse:
    return await build_board_tasks(db, current_user)


async def build_board_tasks(db: AsyncSession, current_user: User) -> BoardTasksResponse:
    """Cała kolejka „Czeka na Ciebie” tej osoby.

    Wspólna dla ekranu i porannego maila (`tasks/daily_digest_email.py`), żeby
    mail nie mówił czego innego niż pulpit. Pętla w tle musi przed wywołaniem
    dołączyć do konta politykę dostępu (`resolve_effective_access`).
    """
    snapshot = await svc.load_snapshot(db)
    portfolio = await svc.dl_review_portfolio(db, current_user)
    mine = svc.tasks_for_user(snapshot, current_user, portfolio=portfolio)
    preps = prep_attention.for_user(
        await prep_attention.load_prep_attention(db, datetime.now(timezone.utc)),
        current_user,
    )
    names, titles = await prep_attention.labels(db, preps)
    now = datetime.now(timezone.utc)
    today = candidate_followups.local_date(now)
    all_followups = await candidate_followups.load_followups_safely(db, now=now)
    followups = await serialize_rows(
        db,
        candidate_followups.for_user(all_followups, current_user, today=today),
        today=today,
    )
    followups_by_others = await serialize_rows(
        db,
        candidate_followups.others_for_user(all_followups, current_user),
        today=today,
    )
    can_decide_proposals = current_user.has_any_role(*PROPOSAL_DECISION_ROLES)
    proposals, leave_known = (
        await request_allocation_proposals.load_panel_safely(db)
        if can_decide_proposals
        else ([], False)
    )
    job_leads = (
        await new_job_leads.load_safely(db, now=now) if can_decide_proposals else []
    )
    people_rows = (
        await new_person_setup.load_rows_safely(db) if can_decide_proposals else []
    )
    # Finanse i Back office nie przekazują CV — lista „Twoje CV w drodze” ich nie dotyczy.
    transit = (
        None
        if _finance_only(current_user)
        else await cv_in_transit.load_safely(
            db, current_user, portfolio=portfolio, now=now
        )
    )
    flow = await board_flow.load_flow(db, current_user, now=now)
    finance = await board_flow.load_finance(db, current_user, now=now)
    pending = await pending_job_completion.load_pending_jobs_safely(db, current_user)
    from app.services import requirement_cleanup

    fixes = await requirement_cleanup.load_fixes_safely(db, current_user)
    agreements = await agreement_tasks.load_safely(
        db, current_user, portfolio=portfolio
    )
    rate_tasks = await rate_change_tasks.load_safely(db, current_user, now=now)
    unfinished = await pending_job_completion.load_unfinished_forms_safely(
        db, current_user, now=now
    )
    dl_review = mine[svc.KIND_DL_REVIEW]
    dl_cvs = (
        await move_requirements.company_cv_refs(
            db, [(t.candidate_id, t.job_id) for t in dl_review]
        )
        if dl_review
        else {}
    )
    calls = await screening_calls.for_user_safely(db, current_user)
    flow_out = _flow_block(flow, skip_contract_ids=_agreement_ids(agreements))
    if flow_out is not None:
        starts = {(c.candidate_id, c.job_id): c.start_time for c in calls}
        for row in flow_out.screening:
            row.call_at = starts.get((row.candidate_id, row.job_id))
        # „Twoje blokady” proszą o decyzję przed końcem blokady, a umówiony
        # telefon już nią jest: osoba stoi na liście telefonów.
        flow_out.claimed = [
            row
            for row in flow_out.claimed
            if (row.candidate_id, row.job_id) not in starts
        ]
    inherited_leads = await _inherited_lead_names(db, current_user)
    return BoardTasksResponse(
        booked_calls=[
            BookedCallRow(
                event_id=c.event_id,
                candidate_id=c.candidate_id,
                candidate_name=c.candidate_name,
                job_id=c.job_id,
                job_title=c.job_title,
                job_working_title=c.job_working_title,
                client_name=c.client_name,
                start_time=c.start_time,
                note=c.note,
                in_outlook=c.in_outlook,
            )
            for c in calls
        ],
        followups=followups,
        followups_by_others=followups_by_others,
        cpro_to_send=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_TO_SEND]],
        # Najdłużej czekające na Nordeę na górze — wysłane rośnie w czasie.
        cpro_sent=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_SENT]],
        dl_review=[
            BoardTaskRow(
                **t.as_dict(),
                cv_stage_id=(dl_cvs.get((t.candidate_id, t.job_id)) or {}).get(
                    "stage_id"
                ),
                on_behalf_of_name=inherited_leads.get(t.delivery_lead_id),
            )
            for t in dl_review
        ],
        window_days=svc.WINDOW_DAYS,
        dl_review_window_days=svc.DL_REVIEW_WINDOW_DAYS,
        # Ta sama reguła co `/move` na „CV wysłane” poza Nordeą
        # (`pipeline_move_rules.assert_client_send_allowed`).
        can_send_to_client=has_permission(
            current_user, ProductAction.recruitment_manage
        ),
        can_set_cpro_sender=await cpro_sender.can_set_sender(db, current_user),
        allocation_proposals=[AllocationProposalRow(**asdict(p)) for p in proposals],
        can_decide_proposals=can_decide_proposals,
        allocation_leave_known=leave_known,
        new_job_leads=[NewJobLeadRow(**asdict(lead)) for lead in job_leads],
        new_people=(
            None
            if people_rows is None
            else [NewPersonSetupRow(**row.as_dict()) for row in people_rows]
        ),
        cv_in_transit=_transit_block(transit),
        pending_jobs=(
            PendingJobsBlock(
                autoclose_on=pending.autoclose_on,
                items=[PendingJobRow(**asdict(item)) for item in pending.items],
            )
            if pending is not None
            else None
        ),
        unfinished_forms=[UnfinishedFormRow(**asdict(f)) for f in unfinished],
        requirement_fixes=(
            None if fixes is None else [RequirementFixRow(**row) for row in fixes]
        ),
        rate_changes=[
            RateChangeTaskRow(**asdict(t))
            for t in (rate_tasks.mine if rate_tasks else [])
        ],
        rate_changes_by_others=[
            RateChangeTaskRow(**asdict(t))
            for t in (rate_tasks.by_others if rate_tasks else [])
        ],
        agreements=(
            AgreementTasksBlock(
                to_confirm=[
                    AgreementTaskRow(**asdict(t)) for t in agreements.to_confirm
                ],
                to_close=[AgreementTaskRow(**asdict(t)) for t in agreements.to_close],
                waiting_on_others=[
                    AgreementTaskRow(**asdict(t)) for t in agreements.waiting_on_others
                ],
            )
            if agreements is not None
            else None
        ),
        flow=flow_out,
        finance=_finance_block(finance),
        prep_attention=[
            PrepAttentionRow(
                reason=a.reason,
                prep_no=a.prep_no,
                candidate_id=a.candidate_id,
                candidate_name=names.get(a.candidate_id, f"Kandydat #{a.candidate_id}"),
                job_id=a.job_id,
                job_title=titles.get(a.job_id, f"Rekrutacja #{a.job_id}"),
                interview_event_id=a.interview_event_id,
                interview_start=a.interview_start,
                prep_event_id=a.prep_event_id,
                owner_id=a.owner_id,
                urgent=a.urgent,
            )
            for a in preps
        ],
    )


def _finance_only(user: User) -> bool:
    return bool(user.get_all_roles() & {UserRole.finance, UserRole.back_office})


def _pair(row: board_flow.PairRow) -> FlowPairRow:
    data = asdict(row)
    data["missing"] = list(row.missing)
    return FlowPairRow(**data)


def _agreement_ids(agreements) -> frozenset[int]:
    """Umowy, które grupa „Umowy” już pokazuje — przepływ ich nie dubluje."""
    if agreements is None:
        return frozenset()
    rows = (*agreements.to_confirm, *agreements.to_close, *agreements.waiting_on_others)
    return frozenset(t.generated_id for t in rows)


def _flow_block(
    flow: Optional[board_flow.FlowBlock],
    *,
    skip_contract_ids: frozenset[int] = frozenset(),
) -> Optional[FlowBlockOut]:
    if flow is None:
        return None
    return FlowBlockOut(
        applies=flow.applies,
        new_requests=[FlowNewRequestRow(**asdict(r)) for r in flow.new_requests],
        postings=[FlowPostingRow(**asdict(r)) for r in flow.postings],
        postings_total=flow.postings_total,
        claimed=[_pair(r) for r in flow.claimed],
        screening=[_pair(r) for r in flow.screening],
        verified=[_pair(r) for r in flow.verified],
        waiting_client=[_pair(r) for r in flow.waiting_client],
        waiting_client_days=board_flow.WAITING_CLIENT_DAYS,
        unsigned_contracts=[
            FlowContractRow(**asdict(r))
            for r in flow.unsigned_contracts
            if r.id not in skip_contract_ids
        ],
        order_mail_review=flow.order_mail_review,
        top_proposals=[
            FlowJobProposals(
                job_id=r.job_id,
                job_title=r.job_title,
                job_working_title=r.job_working_title,
                client_name=r.client_name,
                total=r.total,
                people=[FlowProposalPerson(**asdict(p)) for p in r.people],
            )
            for r in flow.top_proposals
        ],
        autofill_decisions=[
            FlowAutofillDecision(**asdict(r)) for r in flow.autofill_decisions
        ],
        autofill_decisions_total=flow.autofill_decisions_total,
    )


def _finance_block(
    finance: Optional[board_flow.FinanceBlock],
) -> Optional[FinanceBlockOut]:
    if finance is None:
        return None
    return FinanceBlockOut(
        gaps_open=finance.gaps_open,
        pdfs_new=finance.pdfs_new,
        order_mail_failed=finance.order_mail_failed,
        hired_without_order=[_pair(r) for r in finance.hired_without_order],
        hired_without_order_total=finance.hired_without_order_total,
    )


def _transit_block(
    transit: Optional[cv_in_transit.CvInTransit],
) -> Optional[CvInTransitBlock]:
    if transit is None:
        return None
    return CvInTransitBlock(
        returned=[CvTransitRow(**asdict(r)) for r in transit.returned],
        in_review=[CvTransitRow(**asdict(r)) for r in transit.in_review],
        sent=[CvTransitRow(**asdict(r)) for r in transit.sent],
        returned_total=transit.returned_total,
        returned_to_fix_total=transit.returned_to_fix_total,
        in_review_total=transit.in_review_total,
        sent_total=transit.sent_total,
        returned_window_days=cv_in_transit.RETURNED_WINDOW_DAYS,
        sent_window_days=cv_in_transit.SENT_WINDOW_DAYS,
    )


class DlReviewRowResponse(BaseModel):
    row: BoardTaskRow
    can_send_to_client: bool


@router.get("/dl-review-row", response_model=DlReviewRowResponse)
async def get_dl_review_row(
    candidate_id: int,
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> DlReviewRowResponse:
    """Zadanie przeglądu DL dla jednej pary — ten sam wiersz co na pulpicie.

    Tablica i link z dzwonka „CV do przeglądu” (`?review=1`) otwierały
    przegląd z wiersza składanego w przeglądarce, bez etapu CV po QC, osoby
    weryfikującej i stanu karty (04.10.2026). Bramka jak wysyłka do klienta
    (`recruitment_manage`) i odczyt rekrutacji; 404, gdy osoba nie czeka na
    przegląd (nie stoi w „QC CV” albo klient wysyła przez Cpro).
    """
    from app.api.recruitment_access import ensure_job_read_access  # noqa: PLC0415

    if not has_permission(current_user, ProductAction.recruitment_manage):
        raise HTTPException(
            status_code=403,
            detail="Przegląd przed wysłaniem do klienta robi Delivery Lead.",
        )
    await ensure_job_read_access(db, current_user, job_id)
    snapshot = await svc.load_snapshot(db, pair=(candidate_id, job_id))
    task = next(
        (
            t
            for t in snapshot.tasks
            if t.kind == svc.KIND_DL_REVIEW
            and t.candidate_id == candidate_id
            and t.job_id == job_id
        ),
        None,
    )
    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Ta osoba nie czeka na przegląd przed wysłaniem do klienta.",
        )
    cvs = await move_requirements.company_cv_refs(db, [(candidate_id, job_id)])
    return DlReviewRowResponse(
        row=BoardTaskRow(
            **task.as_dict(),
            cv_stage_id=(cvs.get((candidate_id, job_id)) or {}).get("stage_id"),
        ),
        can_send_to_client=True,
    )


# Okienko w górnym pasku — dłuższa lista jest na pulpicie.
DL_SEND_ROWS = 30


@router.get("/dl-send", response_model=DlSendQueueResponse)
async def get_dl_send_queue(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> DlSendQueueResponse:
    """„Do wysłania do klienta” patrzącego — licznik górnego paska i menu.

    Lekkie (wiersze + stan QC, zakres w SQL): pasek pyta o to na każdej
    stronie, a pełna kolejka z historią par zostaje w `GET /api/board-tasks`.
    Liczy STAN, nie zdarzenia — wiersz znika po wysłaniu, odrzuceniu albo
    cofnięciu karty, nie po przeczytaniu. Konto bez roli Delivery Leada
    dostaje zera bez zapytań.
    """
    if not current_user.has_role(UserRole.delivery_lead):
        return DlSendQueueResponse(
            ready=[], ready_total=0, not_ready_total=0, imported_total=0
        )
    portfolio = await svc.dl_review_portfolio(db, current_user)
    return await _dl_send_payload(db, current_user, portfolio)


async def _inherited_lead_names(db: AsyncSession, user: User) -> dict[int, str]:
    """Imiona osób, które oglądający dziś zastępuje — podpis wierszy przeglądu."""
    inherited = operational_owner_ids(user) - {user.id}
    if not inherited:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(inherited)))
    return dict(rows.all())


async def _dl_send_payload(
    db: AsyncSession, current_user: User, portfolio: frozenset[int]
) -> DlSendQueueResponse:
    """Kolejka „Do wysłania” Delivery Leada — pigułka i ikona „CV” liczą to samo."""
    rows = await dl_send_queue.load_for_viewer(db, current_user, portfolio=portfolio)
    ready = sorted(
        (t for t in rows if dl_send_queue.counts_for_reviewer(t)),
        key=lambda t: t.ready_since,
    )
    shown = ready[:DL_SEND_ROWS]
    await dl_send_queue.attach_handed_over_names(db, shown)
    lead_names = await _inherited_lead_names(db, current_user)
    return DlSendQueueResponse(
        ready=[
            DlSendRow(
                stage_id=t.stage_id,
                candidate_id=t.candidate_id,
                candidate_name=t.candidate_name,
                job_id=t.job_id,
                job_title=t.job_title,
                job_working_title=t.job_working_title,
                client_name=t.client_name,
                ready_since=t.ready_since,
                waiting_workdays=t.waiting_workdays,
                urgency=t.urgency,
                handed_over_by_name=t.handed_over_by_name,
                cpro=t.cpro,
                on_behalf_of_name=lead_names.get(t.delivery_lead_id),
            )
            for t in shown
        ],
        ready_total=len(ready),
        not_ready_total=sum(1 for t in rows if not t.ready and not t.imported),
        imported_total=sum(1 for t in rows if t.imported),
        worst_urgency=dl_send_queue.worst_urgency(ready),
    )


class ClosingCandidateRow(BaseModel):
    """Wiersz kafelka „Kandydaci do zamknięcia” (`closing_candidates.load`)."""

    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: Optional[str] = None
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    step: Literal["accepted", "sent", "signed"]
    since: datetime
    delivery_lead_name: Optional[str] = None
    recruiter_name: Optional[str] = None
    candidate_rate_value: Optional[Decimal] = None
    candidate_rate_unit: Optional[str] = None
    candidate_rate_currency: Optional[str] = None
    client_rate_value: Optional[Decimal] = None
    client_rate_unit: Optional[str] = None
    client_rate_currency: Optional[str] = None


class ClosingCandidatesResponse(BaseModel):
    rows: list[ClosingCandidateRow]
    total: int
    # Liczniki filtra kroków — ze wszystkich osób, także spoza `rows`.
    step_counts: dict[Literal["accepted", "sent", "signed"], int]
    # Bez prawa do stawki do klienta kafelek nie pokazuje przychodu ani marży.
    show_client_rate: bool


@router.get("/closing", response_model=ClosingCandidatesResponse)
async def get_closing_candidates(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ClosingCandidatesResponse:
    """Kandydaci w kolumnie „Akceptacja i umowa” — kafelek pulpitu (20.10.2026)."""
    from app.api.candidate_access import user_can_view_client_rate

    show_client_rate = user_can_view_client_rate(current_user)
    result = await closing_candidates.load(db, current_user)
    return ClosingCandidatesResponse(
        rows=[
            ClosingCandidateRow(
                candidate_id=row.candidate_id,
                candidate_name=row.candidate_name,
                job_id=row.job_id,
                job_title=row.job_title,
                job_working_title=row.job_working_title,
                client_name=row.client_name,
                step=row.step,
                since=row.since,
                delivery_lead_name=row.delivery_lead_name,
                recruiter_name=row.recruiter_name,
                **closing_candidates.rate_fields(
                    row.rate, show_client_rate=show_client_rate
                ),
            )
            for row in result.rows
        ],
        total=result.total,
        step_counts=result.step_counts,
        show_client_rate=show_client_rate,
    )


class DepartedCareRow(BaseModel):
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    column: str
    moved_at: Optional[datetime] = None
    caretaker_user_id: int
    caretaker_name: str


class DepartedCareGroup(BaseModel):
    departed_user_id: int
    departed_name: str
    since: datetime
    pairs: int
    jobs: int
    clients: list[str]
    columns: dict[str, int]
    rows: list[DepartedCareRow]


class DepartedCareOverdue(BaseModel):
    user_id: int
    name: str
    pairs: int
    departed: list[str]
    since: datetime


class DepartedCareResponse(BaseModel):
    """Kandydaci po osobach, które odeszły — opieka Delivery Leada (28.10.2026)."""

    groups: list[DepartedCareGroup]
    total: int
    # Head of Recruitment i admin: niedomknięte po 10 dniach roboczych, per DL.
    overdue: list[DepartedCareOverdue] = []
    escalate_after_days: int


@router.get("/departed-care", response_model=DepartedCareResponse)
async def get_departed_care(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> DepartedCareResponse:
    """Kafel „Po osobach, które odeszły” i lista do domknięcia
    (``services/departure_care.py``)."""
    from app.services import departure_care

    groups = departure_care.rows_payload(
        await departure_care.open_care(db, caretaker_id=current_user.id)
    )
    overdue = (
        await departure_care.overdue_by_caretaker(db)
        if current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)
        else []
    )
    return DepartedCareResponse(
        groups=groups,
        total=sum(g["pairs"] for g in groups),
        overdue=overdue,
        escalate_after_days=departure_care.ESCALATE_AFTER_DAYS,
    )


class CvCheckRow(BaseModel):
    """Auto-CV gotowe do sprawdzenia (`cv_topic.load_to_check`)."""

    document_id: int
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str] = None
    client_name: Optional[str] = None
    since: datetime


class CvTopicRecruiter(BaseModel):
    to_check: list[CvCheckRow]
    to_fix: list[CvTransitRow]
    with_dl: list[CvTransitRow]
    sent: list[CvTransitRow]


class CvTopicDl(BaseModel):
    to_send: list[DlSendRow]
    to_send_total: int
    worst_urgency: Optional[Literal["fresh", "due", "late"]] = None
    # W „QC CV”, ale ruch ma rekruter (QC do poprawy albo niesprawdzone).
    with_recruiters_total: int
    sent_today: list[CvTransitRow]


class CvTopicResponse(BaseModel):
    """Ikona „CV” w górnym pasku (16.10.2026, zamiast pigułki „Do wysłania”)."""

    # CV, na które czekamy na tę osobę: do sprawdzenia + do poprawy
    # (rekruter) i gotowe do wysłania (Delivery Lead).
    badge: int
    recruiter: Optional[CvTopicRecruiter] = None
    dl: Optional[CvTopicDl] = None


_CV_RECRUITER_ROLES = (UserRole.recruiter, UserRole.delivery_lead)


@router.get("/cv", response_model=CvTopicResponse)
async def get_cv_topic(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CvTopicResponse:
    """Ikona „CV”: moje CV w rekrutacjach ze STANU, nie ze zdarzeń.

    Rekruter (i Delivery Lead, który sam przesuwa karty): do sprawdzenia,
    do poprawy, u Delivery Leada, wysłane. Delivery Lead: do wysłania do
    klienta (ta sama lista co `/dl-send`), u rekruterów, wysłane dziś. Konto
    bez tych ról dostaje pustą odpowiedź bez zapytań — ikona się nie pokazuje.
    """
    as_recruiter = any(current_user.has_role(r) for r in _CV_RECRUITER_ROLES)
    as_dl = current_user.has_role(UserRole.delivery_lead)
    if not (as_recruiter or as_dl):
        return CvTopicResponse(badge=0)
    portfolio = (
        await svc.dl_review_portfolio(db, current_user) if as_dl else frozenset()
    )
    recruiter: Optional[cv_topic.RecruiterCv] = None
    if as_recruiter:
        recruiter = await cv_topic.load_recruiter(db, current_user, portfolio=portfolio)
    dl: Optional[CvTopicDl] = None
    if as_dl:
        queue = await _dl_send_payload(db, current_user, portfolio)
        sent_today = await cv_topic.load_sent_today(
            db, current_user, portfolio=portfolio
        )
        dl = CvTopicDl(
            to_send=queue.ready,
            to_send_total=queue.ready_total,
            worst_urgency=queue.worst_urgency,
            with_recruiters_total=queue.not_ready_total,
            sent_today=[CvTransitRow(**asdict(r)) for r in sent_today],
        )
    return CvTopicResponse(
        badge=cv_topic.badge_for(
            recruiter=recruiter, dl_to_send=dl.to_send_total if dl else 0
        ),
        recruiter=(
            CvTopicRecruiter(
                to_check=[CvCheckRow(**asdict(r)) for r in recruiter.to_check],
                to_fix=[CvTransitRow(**asdict(r)) for r in recruiter.to_fix],
                with_dl=[CvTransitRow(**asdict(r)) for r in recruiter.with_dl],
                sent=[CvTransitRow(**asdict(r)) for r in recruiter.sent],
            )
            if recruiter
            else None
        ),
        dl=dl,
    )


class DlSendNudgeResponse(BaseModel):
    sent: bool
    # Ilu Delivery Leadów dostało dzwonek (tylko przy ``sent``).
    recipients: Optional[int] = None
    # Dlaczego nic nie poszło: dziś już ktoś o tej karcie przypomniał.
    reason: Optional[Literal["already_today"]] = None


@router.post(
    "/dl-send/{stage_id}/nudge",
    response_model=DlSendNudgeResponse,
    response_model_exclude_none=True,
)
async def nudge_dl_send(
    stage_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> DlSendNudgeResponse:
    """„Przypomnij” w „Twoje CV w drodze”: rekruter przypomina Delivery
    Leadowi o CV gotowym do wysłania (13.10.2026).

    Przypomnieć może osoba, która przekazała kartę do „QC CV”, albo rekruter
    kandydata — ta sama reguła „moje” co lista (`cv_in_transit`) — i dopiero,
    gdy gotowe CV czeka ``LATE_WORKDAYS`` dni roboczych. Dzwonek jest zadaniem
    (`board_task_waiting`) i prowadzi prosto do przeglądu; drugie
    przypomnienie tego samego dnia nic nie wysyła (indeks dobowy dzwonka).
    """

    stage = await db.get(CandidateStage, stage_id)
    task = None
    if stage is not None:
        rows = await dl_send_queue.load_rows(
            db, scope=dl_send_queue.Scope(pair=(stage.candidate_id, stage.job_id))
        )
        task = next((t for t in rows if t.stage_id == stage_id), None)
    if task is None:
        # Karta poszła dalej, rekrutacja zamknięta albo klient z kolejką Cpro.
        raise HTTPException(
            status_code=404,
            detail="Ta osoba nie czeka już na wysyłkę do klienta.",
        )
    recruiter_id = (
        None
        if task.moved_by == current_user.id
        else await stage_handoff_recipients.pair_recruiter_id(
            db, candidate_id=task.candidate_id, job_id=task.job_id
        )
    )
    if current_user.id not in (task.moved_by, recruiter_id):
        logger.info(
            "dl_send_nudge: odmowa — user=%s nie przekazał etapu %s i nie "
            "prowadzi kandydata",
            current_user.id,
            stage_id,
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Przypomnieć może osoba, która przekazała CV, albo rekruter kandydata."
            ),
        )
    if not dl_send_queue.counts_for_reviewer(task):
        raise HTTPException(
            status_code=409,
            detail="CV nie przeszło jeszcze QC — ruch jest po Twojej stronie.",
        )
    if task.waiting_workdays < dl_send_queue.LATE_WORKDAYS:
        raise HTTPException(
            status_code=409,
            detail="Przypomnieć można po 2 dniach roboczych czekania.",
        )
    job = await db.get(Job, task.job_id)
    recipients = [
        uid
        for uid in await stage_handoff_recipients._dl_reviewers(db, job)
        if uid != current_user.id
    ]
    if not recipients:
        logger.info(
            "dl_send_nudge: etap %s, rekrutacja %s — brak Delivery Leada do "
            "powiadomienia",
            stage_id,
            task.job_id,
        )
        raise HTTPException(
            status_code=409,
            detail="Ta rekrutacja nie ma Delivery Leada — nie ma komu przypomnieć.",
        )
    who = current_user.name or "Ktoś z zespołu"
    job_title = task.job_working_title or task.job_title
    notified: list[int] = []
    for user_id in recipients:
        notif = await emit(
            db,
            user_id=user_id,
            title=f"{stage_handoff_recipients.TITLE_DL_NUDGE} {task.candidate_name}",
            message=(
                f"{who} przypomina: CV kandydata {task.candidate_name} "
                f"w rekrutacji „{job_title}” czeka na wysyłkę do klienta od "
                f"{task.waiting_workdays} dni roboczych."
            ),
            ntype=NotificationType.board_task_waiting,
            related_entity_type="candidate_stage",
            related_entity_id=stage_id,
            link=f"/jobs/{task.job_id}?candidate={task.candidate_id}&review=1",
        )
        if notif is not None:
            notified.append(user_id)
    if not notified:
        logger.info(
            "dl_send_nudge: etap %s — dzwonek już dziś wysłany, nic nie zapisano",
            stage_id,
        )
        return DlSendNudgeResponse(sent=False, reason="already_today")
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage_id,
            action="dl_send_nudge",
            user_id=current_user.id,
            details={
                "candidate_id": task.candidate_id,
                "job_id": task.job_id,
                "recipients": notified,
            },
        )
    )
    await db.commit()
    return DlSendNudgeResponse(sent=True, recipients=len(notified))


@router.get("/cpro/sender", response_model=CproSenderRead)
async def get_cpro_sender(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproSenderRead:
    """Kto dziś wysyła kandydatów Nordei do Cpro (po wygaśnięciu zastępstwa)."""

    state = await cpro_sender.effective_sender(db)
    return CproSenderRead(
        **await cpro_sender.describe(db, state),
        can_set=await cpro_sender.can_set_sender(db, current_user),
    )


@router.put("/cpro/sender", response_model=CproSenderRead)
async def set_cpro_sender(
    body: CproSenderUpdate,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproSenderRead:
    """Ustawia JEDNĄ osobę na całą firmę (decyzja Artura 23.09.2026).

    Od 25.09.2026 zmienia WYŁĄCZNIE admin albo Delivery Lead przypisany do
    Nordei (`cpro_sender.can_set_sender`): osoba od Cpro widzi w kolejce
    stawki do klienta, więc rekruter ustawiający siebie omijał #1742.
    `until` = zastępstwo: po tej dacie wraca osoba, która wysyłała wcześniej.
    """

    if not await cpro_sender.can_set_sender(db, current_user):
        raise HTTPException(status_code=403, detail=cpro_sender.SET_SENDER_FORBIDDEN)
    if body.user_id is not None:
        await svc.load_assignee(db, body.user_id)
    before, after = await cpro_sender.set_sender(
        db, user_id=body.user_id, until=body.until, actor=current_user
    )
    db.add(
        Activity(
            entity_type="user",
            entity_id=current_user.id,
            action="cpro_sender_changed",
            user_id=current_user.id,
            details={
                "from": before.user_id,
                "to": after.user_id,
                "until": after.until.isoformat() if after.until else None,
                "fallback_user_id": after.fallback_user_id,
            },
        )
    )
    if after.user_id is not None and after.user_id != before.user_id:
        snapshot = await svc.load_snapshot(db)
        waiting = sum(1 for t in snapshot.tasks if t.kind == svc.KIND_CPRO_TO_SEND)
        await cpro_sender.notify_new_sender(
            db,
            sender_id=after.user_id,
            until=after.until,
            waiting=waiting,
            actor=current_user,
        )
    await db.commit()
    return CproSenderRead(**await cpro_sender.describe(db, after), can_set=True)


@router.get("/cpro/queue", response_model=CproQueueResponse)
async def get_cpro_queue(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproQueueResponse:
    """Kolejka Cpro całej firmy, pogrupowana po rekrutacji.

    Widzi ją każdy z dostępem do kolejki — osoba od Cpro zmienia się często
    (zastępstwa), a zastępca musi widzieć, co czeka, zanim go ustawią.
    „✓ Wrzucone" i „Zwróć do rekrutera" to zwykłe `POST /api/pipeline/move`.
    """

    now = datetime.now(timezone.utc)
    # Stawkę do klienta widzą role z `CLIENT_RATE_VIEW_ROLES` (decyzja
    # 23.09.2026, #1742) oraz osoba od Cpro — to ona wpisuje ją do Cpro.
    from app.api.candidate_access import user_can_view_client_rate

    show_rate = user_can_view_client_rate(current_user) or (
        (await cpro_sender.effective_sender(db, now)).user_id == current_user.id
    )
    snapshot = await svc.load_snapshot(db, now=now)
    to_send = [t for t in snapshot.tasks if t.kind == svc.KIND_CPRO_TO_SEND]
    pairs = [(t.candidate_id, t.job_id) for t in to_send]
    rates = await latest_client_rates(db, pairs)
    cvs = await move_requirements.company_cv_refs(db, pairs)
    from app.services.cv_dl_accept_finalize import review_pending_stage_ids

    reviewing = await review_pending_stage_ids(
        db, [cv["stage_id"] for cv in cvs.values() if cv["source"] == "branded_draft"]
    )
    availability = await _availability(db, {t.candidate_id for t in to_send})
    mover_ids = {t.moved_by for t in to_send if t.moved_by is not None}
    movers = (
        {
            u.id: u
            for u in (
                await db.scalars(select(User).where(User.id.in_(mover_ids)))
            ).all()
        }
        if mover_ids
        else {}
    )
    # „✓ Zaakceptował(a)” czyta prawo wysyłki z bazy (panel „Osoby i role”),
    # nie z domyślnego zestawu roli — konto z tabeli nie ma polityki żądania.
    await resolve_effective_access(db, movers.values())
    dl_notes = await stage_remarks.for_stages(db, [t.stage_id for t in to_send])

    jobs: dict[int, CproQueueJob] = {}
    for t in to_send:
        pair = (t.candidate_id, t.job_id)
        # Bez osoby na firmę wrzuca osoba zapasowa rekrutacji — to ona
        # wpisuje stawkę do Cpro, więc widzi ją przy swoich zadaniach.
        fallback_sender = (
            snapshot.firm_sender_id is None and t.assignee_id == current_user.id
        )
        rate = rates.get(pair) if show_rate or fallback_sender else None
        cv = cvs.get(pair)
        mover = movers.get(t.moved_by) if t.moved_by is not None else None
        item = CproQueueItem(
            stage_id=t.stage_id,
            candidate_id=t.candidate_id,
            candidate_name=t.candidate_name,
            since=t.since,
            process_state_version=t.process_state_version,
            target_stage_def_id=t.target_stage_def_id,
            return_stage_def_id=t.return_stage_def_id,
            client_rate_value=rate[0] if rate else None,
            client_rate_unit=rate[1] if rate else None,
            client_rate_currency=rate[2] if rate else None,
            availability=availability.get(t.candidate_id),
            qc_status=t.qc_status or "unchecked",
            qc_blocking_failed=t.qc_blocking_failed,
            qc_state=t.qc_state,
            cv=(
                CproQueueCv(
                    stage_id=cv["stage_id"],
                    generated_document_id=cv["generated_document_id"],
                    document_id=cv["document_id"],
                    draft=cv["source"] == "branded_draft",
                    review_pending=cv["stage_id"] in reviewing,
                )
                if cv
                else None
            ),
            accepted=mover is not None
            and has_permission(mover, ProductAction.recruitment_manage),
            accepted_by_name=mover.name if mover is not None else None,
            accepted_at=t.since,
            dl_note=stage_remarks.short(dl_notes.get(t.stage_id)),
        )
        group = jobs.get(t.job_id)
        if group is None:
            group = CproQueueJob(
                job_id=t.job_id,
                job_title=t.job_title,
                job_working_title=t.job_working_title,
                client_reference=t.client_reference,
                client_name=t.client_name,
                oldest_since=t.since,
                items=[],
            )
            jobs[t.job_id] = group
        group.items.append(item)
        group.oldest_since = min(group.oldest_since, t.since)

    # „Wysłane dziś" liczy dzień w kalendarzu firmy, nie UTC.
    tz = ZoneInfo(settings.BUSINESS_TZ)
    today = now.astimezone(tz).date()
    sent_today = sum(
        1
        for t in snapshot.tasks
        if t.kind == svc.KIND_CPRO_SENT and t.since.astimezone(tz).date() == today
    )
    sender = await cpro_sender.effective_sender(db, now)
    bot_summary: Optional[CproBotSummary] = None
    if cpro_bot_runs.worker_enabled():
        bot_summary = await _attach_bot(
            db, jobs, to_send, now=now, today=today, user=current_user
        )
    elif to_send:
        await _attach_operator_drafts(
            db,
            jobs,
            to_send,
            user=current_user,
            show_rate=show_rate,
            now=now,
            today=today,
        )
    return CproQueueResponse(
        sender=CproSenderRead(
            **await cpro_sender.describe(db, sender),
            can_set=await cpro_sender.can_set_sender(db, current_user),
        ),
        jobs=sorted(jobs.values(), key=lambda g: g.oldest_since),
        sent_today=sent_today,
        bot=bot_summary,
    )


async def _attach_operator_drafts(
    db: AsyncSession,
    jobs: dict[int, CproQueueJob],
    tasks: list[svc.BoardTask],
    *,
    user: User,
    show_rate: bool,
    now: datetime,
    today: date,
) -> None:
    from app.services.cpro_bot import operator_browser

    can_send = await cpro_sender.can_send_to_cpro(db, user, now)
    if not operator_browser.can_use(user, can_send=can_send, show_rate=show_rate):
        return
    rows = {row.stage_id: row for group in jobs.values() for row in group.items}
    reservations = await operator_browser.reservations(db, rows)
    blocked = await cpro_bot_runs.recorded_offer_stage_ids(db, rows)
    blocked.update(await operator_browser.unresolved_stage_ids(db, rows))
    items = await cpro_bot_items.load_items(db, tasks=tasks, now=now, today=today)
    for item in items:
        if not operator_browser.can_use(
            user,
            can_send=can_send,
            show_rate=show_rate,
            has_borrowed_data=bool(item.data_from),
        ):
            continue
        run = reservations.get(item.stage_id)
        if run is not None:
            payload = operator_browser.item_for(run)
            if not operator_browser.owned_by(run, user.id):
                confirmed = run.status == "received"
                rows[item.stage_id].operator_status = CproOperatorStatus(
                    delivery_lead_id=payload["cpro_account"]["delivery_lead_id"],
                    cpro_account_name=cpro_bot_items.cpro_account_name(
                        payload["cpro_account"]
                    ),
                    request_number=payload["request_number"],
                    state="draft" if confirmed else "working",
                    offer_id=run.request.get("operator_offer_id")
                    if confirmed
                    else None,
                )
                continue
            rows[item.stage_id].operator_draft = CproOperatorDraft(
                delivery_lead_id=payload["cpro_account"]["delivery_lead_id"],
                cpro_account_name=cpro_bot_items.cpro_account_name(
                    payload["cpro_account"]
                ),
                request_number=payload["request_number"],
                run_id=run.id,
                state="received" if run.status == "received" else "started",
            )
        elif item.payload and not item.blockers and item.stage_id not in blocked:
            rows[item.stage_id].operator_draft = CproOperatorDraft(
                delivery_lead_id=item.payload["cpro_account"]["delivery_lead_id"],
                cpro_account_name=cpro_bot_items.cpro_account_name(
                    item.payload["cpro_account"]
                ),
                request_number=item.payload["request_number"],
                state="ready",
            )


def bot_item_view(
    item: Optional["cpro_bot_items.BotItem"],
    state: Optional["cpro_bot_runs.ItemState"],
    *,
    draft_only: bool = False,
    retry_allowed: bool = True,
) -> Optional[CproBotItem]:
    """Stan bota przy osobie: braki wygrywają, potem wynik ostatniego biegu."""

    if item is None:
        return None
    data_from = list(item.data_from)
    mode = "draft" if draft_only else "submit"
    # Gotowy szkic nie znika z oceny Sandry, gdy później zmieniono dane lub
    # CV w NEXUSIE. Nie oferujemy przez to ponownego utworzenia oferty.
    existing_offer = (
        draft_only and state is not None and state.state in ("draft", "submitted")
    )
    if item.payload is None and not existing_offer:
        return CproBotItem(
            state="blocked",
            mode=mode,
            retry_allowed=retry_allowed,
            blockers=list(item.blockers),
            data_from=data_from,
        )
    if state is None:
        return CproBotItem(
            state="ready", mode=mode, retry_allowed=retry_allowed, data_from=data_from
        )
    return CproBotItem(
        state=state.state,  # type: ignore[arg-type]
        mode=mode,
        retry_allowed=retry_allowed,
        blockers=list(item.blockers),
        message=state.message,
        offer_url=state.offer_url,
        cpro_status=state.cpro_status,
        at=state.at,
        moved=state.moved if state.state == "submitted" else None,
        data_from=data_from,
    )


async def _attach_bot(
    db: AsyncSession,
    jobs: dict[int, "CproQueueJob"],
    tasks: list,
    *,
    now: datetime,
    today: date,
    user: User,
) -> CproBotSummary:
    """Stan bota przy każdej osobie kolejki i linia o bocie nad listą."""

    from app.models.cpro_bot import CproBotRun  # noqa: PLC0415

    bot_items = {
        i.stage_id: i
        for i in await cpro_bot_items.load_items(db, now=now, today=today, tasks=tasks)
    }
    states = await cpro_bot_runs.item_states(db, list(bot_items), now=now)
    draft_only = cpro_bot_runs.auto_draft_enabled()
    recorded_offers = (
        await cpro_bot_runs.recorded_offer_stage_ids(db, list(bot_items))
        if draft_only
        else set()
    )
    for group in jobs.values():
        for queued in group.items:
            queued.bot = bot_item_view(
                bot_items.get(queued.stage_id),
                states.get(queued.stage_id),
                draft_only=draft_only,
                retry_allowed=queued.stage_id not in recorded_offers,
            )
    last = await db.scalar(select(func.max(CproBotRun.started_at)))
    day_start = local_day_start_utc(today)
    received_today = (
        await db.execute(
            select(CproBotRun.submit, CproBotRun.report).where(
                CproBotRun.received_at >= day_start
            )
        )
    ).all()
    sent_today = sum(
        int(((run.report or {}).get("counts") or {}).get("submitted", 0))
        for run in received_today
        if run.submit
    )
    drafted_today = {
        ref
        for run in received_today
        if not run.submit
        for ref, outcome in ((run.report or {}).get("items") or {}).items()
        if isinstance(outcome, dict) and outcome.get("outcome") == "draft"
    }
    return CproBotSummary(
        mode="draft" if draft_only else "submit",
        configured=cpro_bot_runs.configured(),
        working=await cpro_bot_runs.has_open_run(db),
        last_run_at=last,
        sent_today=sent_today,
        drafts_today=len(drafted_today),
        awaiting_review=sum(
            queued.bot is not None and queued.bot.state == "draft"
            for group in jobs.values()
            for queued in group.items
        ),
        can_retry=await cpro_sender.can_send_to_cpro(db, user, now),
    )


class CproBotRetryResponse(BaseModel):
    run_id: int
    status: str


@router.post("/cpro/bot/{stage_id}/retry", response_model=CproBotRetryResponse)
async def retry_cpro_bot(
    stage_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproBotRetryResponse:
    """„Ponów botem”: osoba od Cpro, admin, DL albo HoR zleca botowi jedną kartę.

    Odmowa (braki, bot już wysłał, bieg trwa) to 409 z polskim powodem.
    """

    from app.services.cpro_bot import flow as cpro_bot_flow  # noqa: PLC0415

    if not cpro_bot_runs.worker_enabled():
        raise HTTPException(status_code=409, detail="Bot Cpro jest wyłączony.")
    now = datetime.now(timezone.utc)
    if not await cpro_sender.can_send_to_cpro(db, current_user, now):
        raise HTTPException(
            status_code=403,
            detail="Bota zleca osoba od Cpro, Delivery Lead, Head of Recruitment albo admin.",
        )
    try:
        run = await cpro_bot_flow.start_chosen(
            db,
            [stage_id],
            now=now,
            today=business_date(now),
            requested_by_user_id=current_user.id,
            submit=not cpro_bot_runs.auto_draft_enabled(),
        )
    except cpro_bot_flow.NotReady as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from None
    return CproBotRetryResponse(run_id=run.id, status=run.status)


async def _availability(db: AsyncSession, candidate_ids: set[int]) -> dict[int, date]:
    """Termin dostępności; osoba z żywą umową — z umowy (15.10.2026), bez
    daty końca albo przed startem umowy — bez terminu."""
    if not candidate_ids:
        return {}
    rows = await db.execute(
        select(Candidate.id, Candidate.availability_date).where(
            Candidate.id.in_(sorted(candidate_ids)),
        )
    )
    profile: dict[int, Optional[date]] = dict(rows.all())
    contract = await load_contract_free(db, candidate_ids)
    out: dict[int, date] = {}
    for candidate_id, profile_date in profile.items():
        free = contract.get(candidate_id)
        day = free.available_from(profile_date) if free is not None else profile_date
        if day is not None:
            out[candidate_id] = day
    return out
