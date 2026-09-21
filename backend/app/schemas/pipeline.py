from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.candidate_risk import CandidateOfferResponse
from app.models.contract import RateUnit
from app.models.recruitment_pipeline import (
    PipelineStage,
    StageCategory,
    VerificationStatus,
)
from app.schemas.candidate_contact import ContactCaseSummaryResponse


class StageMove(BaseModel):
    """Payload for moving a candidate to a new stage.

    Phase 1 accepts EITHER `stage` (legacy enum, resolved via default template
    legacy_enum_value) OR `stage_def_id` (new FK). At least one is required.
    Terminal moves (rejected/withdrawn) should include `rejection_reason_id`.
    """

    candidate_id: int
    job_id: int
    stage: Optional[PipelineStage] = None
    stage_def_id: Optional[int] = None
    notes: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    rejection_reason_id: Optional[int] = None
    rejection_reason: Optional[str] = None  # legacy free-text — kept for BC

    # Mail odrzucenia (0045_rejection_emails) jest OPT-IN od 17.09.2026:
    # serwer planuje wysyłkę WYŁĄCZNIE przy `True` (checkbox w oknie
    # odrzucenia, domyślnie odznaczony; kwalifikowalność sprawdza dalej
    # `maybe_schedule`). `None`/`False` = nie wysyłaj. Wcześniej `None`
    # znaczyło „serwer decyduje" i mail szedł sam po odrzuceniu z etapu klienta.
    send_rejection_email: Optional[bool] = None
    # Optional override — use a specific EmailTemplate.id instead of the
    # default rejection template.
    rejection_email_template_id: Optional[int] = None

    # ── Stawka kandydata przy ruchu na `verified` (0056, zmiana 17.09.2026) ─
    # OPCJONALNA. Do 17.09.2026 brak stawki dawał 422, a stawka ponad
    # `Job.salary_max` stawiała kartę na `pending` i czekała na admina.
    # Decyzja właściciela: żadna bramka nie zatrzymuje przepływu — stawkę
    # zapisujemy, gdy jest, a „ponad budżet" to odznaka na karcie (front liczy
    # ją z `effective_budget_hourly`), nie stan procesu.
    expected_rate_value: Optional[Decimal] = Field(None, ge=0)
    expected_rate_unit: Optional[RateUnit] = None
    expected_rate_currency: Optional[str] = Field(None, max_length=3)

    # ── Candidate offer response (migracja 0066 — Phase 17) ───────────────
    # Sensowne tylko gdy stage ∈ {acceptance, negotiation, onboarding}.
    # `declined` przed wycofaniem → post_accept dropout (10pt w risk score).
    candidate_offer_response: Optional[CandidateOfferResponse] = None

    # ── Optymistyczna współbieżność (audyt procesów F05) ──────────────────
    # `RecruitmentProcess.state_version` widziana przez klienta w chwili
    # decyzji. Podana i różna od bieżącej → 409 PIPELINE_VERSION_CONFLICT:
    # ktoś inny przesunął tę parę, zanim użytkownik kliknął z dawno otwartej
    # karty. Brak pola = zachowanie dotychczasowe (blokady serializują zapis,
    # ale nie wykrywają nieaktualnej intencji).
    expected_state_version: Optional[int] = Field(None, ge=0)

    # ── Ostrzeżenie dopuszczalności (17.09.2026) ──────────────────────────
    # Czarna lista / NDA / konkurent / weto hiring managera NIE blokują już
    # ruchu. Bez tej flagi serwer odpowiada 409 `ELIGIBILITY_WARNING` z
    # powodem po polsku; klient pyta użytkownika i powtarza TEN SAM ruch
    # z `True` — ruch przechodzi i zostaje `Activity(eligibility_acknowledged)`.
    acknowledge_eligibility: bool = False


class ClientRateUpdate(BaseModel):
    """Body dla PATCH /candidates/{id}/recruitments/{job_id}/client-rate.

    Ustawia „Stawkę do klienta" (sell rate) dla danej rekrutacji.
    `rate_value=None` → wyczyść stawkę. Gdy podana wartość bez jednostki,
    backend domyślnie przyjmuje `monthly`.
    """

    rate_value: Optional[Decimal] = Field(None, ge=0)
    rate_unit: Optional[RateUnit] = None
    rate_currency: Optional[str] = Field(default="PLN", max_length=3)


class HiringManagerVetoBrief(BaseModel):
    """A standing rejection by the hiring manager of the job being viewed."""

    hiring_manager_contact_id: int
    hiring_manager_name: Optional[str] = None
    source_job_id: int
    source_job_title: Optional[str] = None
    rejected_at: datetime
    rejection_reason_name: str
    rejection_note: Optional[str] = None


class CandidateStageResponse(BaseModel):
    id: int
    candidate_id: int
    job_id: int
    stage: PipelineStage
    stage_def_id: Optional[int] = None
    rejection_reason_id: Optional[int] = None
    moved_at: datetime
    moved_by: Optional[int]
    notes: Optional[str]
    rating: Optional[int]
    created_at: datetime
    days_in_stage: Optional[int] = None
    # Candidate name/lastname — populated by Kanban endpoint to render card titles.
    name: Optional[str] = None
    lastname: Optional[str] = None
    # Who assigned this candidate to the recruitment (= mover on the EARLIEST
    # CandidateStage of this candidate/job pair) and when. Populated by the
    # Kanban endpoint so cards can show "kto przypisał kandydata do rekrutacji"
    # on hover. Distinct from `moved_by` which is the current-stage mover.
    added_to_job_by_name: Optional[str] = None
    added_to_job_at: Optional[datetime] = None
    # Set when this move caused a rejection email to be queued; lets the FE
    # show a "Cofnij wysyłkę" toast and anchor the cancel link.
    scheduled_rejection_email_id: Optional[int] = None
    # This job's hiring manager already rejected the candidate after an
    # interview elsewhere. Populated by the Kanban endpoint only — the manager
    # is implicit there (it is this job's), so the card needs no name, and the
    # recruiter learns *before* dragging the card rather than from a 409.
    hm_veto: Optional["HiringManagerVetoBrief"] = None
    contact_case: Optional[ContactCaseSummaryResponse] = None
    # F05: `RecruitmentProcess.state_version` najnowszego procesu pary
    # (0 = proces jeszcze nie istnieje). Wypełniane przez tablicę kanbanu
    # i odpowiedź `POST /pipeline/move`; front odsyła ją jako
    # `expected_state_version`. `None` = endpoint jej nie liczy (np. historia).
    process_state_version: Optional[int] = None
    # Odznaki karty (17.09.2026, „okna po ruchu → odznaki"): czy NA TYM
    # wierszu zapisano arkusz screeningu / scorecard. Zamiast otwierać
    # formularz po ruchu karta pokazuje „do uzupełnienia". Wypełnia tablica.
    screening_done: bool = False
    scorecard_done: bool = False
    # Stawka z PROFILU kandydata (`Candidate.expected_rate_hourly`, PLN/h) —
    # podpowiedź w oknie „Zweryfikowany". Wypełnia tylko tablica.
    candidate_expected_rate_hourly: Optional[Decimal] = None
    # ── Tabela rekrutacji „wersja 3" (09.2026) — wypełnia tylko tablica ────
    # Rekruter karty: właściciel procesu, a bez niego osoba, która dodała
    # kandydata do rekrutacji. `moved_by` to mover BIEŻĄCEGO etapu — co innego.
    recruiter_id: Optional[int] = None
    recruiter_name: Optional[str] = None
    # Dostępność z profilu kandydata — te same nazwy pól co w wynikach
    # wyszukiwania (`availability_status` / `availability_date`).
    availability_status: Optional[str] = None
    availability_date: Optional[date] = None
    # Kody ostrzeżeń karty: `hm_veto`, `budget_exceeded` + miękkie ostrzeżenia
    # polityki dopuszczalności (`client_nda`, `client_blacklist`,
    # `client_competitor`, `client_current_employment`,
    # `client_excluded_by_candidate`, `blacklisted`). Informacja, nie blokada.
    warnings: list[str] = Field(default_factory=list)
    # Po czyjej stronie jest ruch (`services/pipeline_next_action.py`):
    # recruiter | client | candidate | delivery | none. `None` = endpoint jej
    # nie liczy (historia, odpowiedź ruchu, karta poza szablonem).
    next_action_owner: Optional[str] = None

    # ── Stawka z ruchu na „Zweryfikowany" (0056) ─────────────────────────
    # `verification_status` zostaje w odpowiedzi, ale od 17.09.2026 ruch
    # nigdy nie ustawia `pending` (migracja 0323 odblokowała stare wiersze,
    # a bramka „Oczekuje" została usunięta z kodu). Wiersz historyczny
    # `pending` jest raportowany jako `active`.
    verification_status: VerificationStatus = VerificationStatus.active
    expected_rate_value: Optional[Decimal] = None
    expected_rate_unit: Optional[RateUnit] = None
    expected_rate_currency: Optional[str] = None
    budget_max_at_move: Optional[int] = None
    # Informacja (decyzja 17.09.2026, bramka „Oczekuje" usunięta): stawka
    # zapisana przy ruchu przekracza budżet zamrożony na etapie. Karta na
    # tablicy pokazuje odznakę „ponad budżet"; nic nie blokuje.
    budget_exceeded: bool = False
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[int] = None
    rejected_at: Optional[datetime] = None
    rejection_note: Optional[str] = None

    # ── Reakcja kandydata na ofertę (migracja 0066) ───────────────────────
    # Zapisywana wyłącznie przez `POST /pipeline/move` przy wycofaniu po
    # akceptacji. `None` = nie zapisano; `pending` to JAWNA wartość znacząca
    # „czekamy na odpowiedź" — dlatego nie da się jej udawać brakiem pola.
    candidate_offer_response: Optional[CandidateOfferResponse] = None

    model_config = {"from_attributes": True}


class KanbanColumn(BaseModel):
    stage: PipelineStage
    category: StageCategory
    count: int
    items: List[CandidateStageResponse]
    # Phase 1 additions (optional, BC)
    stage_def_id: Optional[int] = None
    name: Optional[str] = None
    order: Optional[int] = None
    # KTÓRY terminal, nie tylko „czy terminal".
    #
    # `stage` dla kolumny bez mapowania na legacy enum degraduje do `new`, a
    # `category` mówi najwyżej „terminal". Frontend rozpoznawał hired/rejected/
    # withdrawn po `stage`, więc dla WŁASNEGO etapu terminalnego:
    #   - „odrzucony" nie otwierał modala powodu → backend odbijał 422,
    #   - „zatrudniony" pomijał potwierdzenie, mimo że backend i tak uruchamiał
    #     skutki uboczne (draft kontraktu + zamówienie klienta).
    # To pole niesie tę informację wprost. Pozostaje opcjonalne — kolumny
    # nieterminalne mają `None`.
    terminal_type: Optional[Literal["hired", "rejected", "withdrawn"]] = None


class OffTemplateColumn(BaseModel):
    """Karty, których etap nie ma kolumny w szablonie tej rekrutacji.

    Powstał, bo bucketowanie tablicy miało dwie ścieżki wyjścia i brak trzeciej:
    karta, która nie trafiła w żadną kolumnę, **znikała bez śladu** — bez
    kolumny, bez licznika, bez ostrzeżenia. Produkcyjny „Default B2B" nie ma
    kolumny dla etapu `interview`, więc pomiar z 2026-09-02 pokazał 1 633
    niewidoczne karty na 1 009 z 3 950 rekrutacji.

    **ŚWIADOMIE bez `stage`, `stage_def_id`, `category` i `terminal_type`.**
    Bez identyfikatora na drucie kubełek jest nieadresowalny jako cel
    `POST /api/pipeline/move`, więc nie da się do niego przenieść kandydata —
    ani przeciągnięciem, ani zbiorczo. Gdyby niósł `stage`, front wysłałby go
    w ruchu (`sendMove` posyła `stage: dst.stage`), backend rozwiązałby etap po
    `legacy_enum_value` i **po cichu** przeniósłby kandydata na przypadkowy
    etap. Nie uzupełniaj tych pól przez analogię do `KanbanColumn` — pilnuje
    tego `test_off_template_bucket_carries_no_move_target_identity`.
    """

    name: str
    count: int
    items: List[CandidateStageResponse]
    # Nazwy etapów, na których te karty stoją. Bez nich rekruter widzi kubełek,
    # ale nie wie, skąd karta przyszła ani dokąd ją wyprowadzić.
    missing_stage_labels: List[str] = Field(default_factory=list)


class KanbanView(BaseModel):
    job_id: int
    columns: List[KanbanColumn]
    # `None` na zdrowej tablicy — stale pusty kubełek na 2 941 rekrutacjach bez
    # sierot uczyłby go ignorować.
    off_template: Optional[OffTemplateColumn] = None


class MyNextStepsJob(BaseModel):
    """One of the caller's open recruitments with its full board."""

    job_id: int
    title: str
    client_name: Optional[str] = None
    view: KanbanView


class MyNextStepsResponse(BaseModel):
    jobs: List[MyNextStepsJob]
    # The list is capped (nearest deadline first); True = more exist.
    truncated: bool = False


class StageInfo(BaseModel):
    stage: PipelineStage
    category: StageCategory
    label: str
    order: int
    # Phase 1: new elastic fields (None for the synthetic terminal stages)
    stage_def_id: Optional[int] = None
    is_terminal: bool = False


# Polish labels for all stages
STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.posting: "Ogłoszenia",
    PipelineStage.new: "Nowi / Analiza CV",
    PipelineStage.prep_call: "Preparation Call",
    PipelineStage.screening: "Screening",
    PipelineStage.verified: "Zweryfikowany",
    PipelineStage.interview: "Interview Wewnętrzny",
    PipelineStage.cv_sent: "CV Wysłane",
    PipelineStage.client_interview: "Interview Klient",
    PipelineStage.acceptance: "Akceptacja",
    PipelineStage.negotiation: "Negocjacje",
    PipelineStage.onboarding: "Onboarding",
    PipelineStage.hired: "Zatrudniony",
    PipelineStage.rejected: "Odrzucony",
    PipelineStage.withdrawn: "Wycofany",
}
