from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import AfterValidator, BaseModel, model_validator

from app.models.contract import (
    ContractStatus,
    ContractTerminationReason,
    ContractType,
    ContractWorkMode,
    EngagementModel,
    OrderConsumptionUnit,
    ProlongationStatus,
    RateUnit,
)


# Cztery stany świadomie edytowalne w rejestrze klienta. Stany techniczne
# ``ready_for_signature`` i ``void`` pozostają wyłącznie w audytowanym
# lifecycle (podpis / anulowanie) i nie pojawiają się w zwykłym dropdownie.
_CONTRACT_REGISTER_STATUSES = frozenset(
    {
        ContractStatus.draft,
        ContractStatus.active,
        ContractStatus.ending,
        ContractStatus.ended,
    }
)


def _validate_contract_register_status(status: ContractStatus) -> ContractStatus:
    if status not in _CONTRACT_REGISTER_STATUSES:
        raise ValueError("Status jest dostępny wyłącznie przez lifecycle kontraktu")
    return status


# Najpierw Pydantic zamienia tekst z JSON (np. ``"active"``) na enum, potem
# walidator zawęża go do czterech stanów edytowalnych w rejestrze. ``Literal``
# z elementami enuma odrzucał zwykłe stringi jeszcze przed tą konwersją.
ContractRegisterStatus = Annotated[
    ContractStatus, AfterValidator(_validate_contract_register_status)
]


class ContractCandidateRateInput(BaseModel):
    """One step in the candidate-rate schedule sent from a create/edit form.

    ``effective_to`` ("Obowiązuje do") is the optional planned end of the step,
    used by the "stawka progresywna" editor; it is advisory (see the model).
    """

    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None


class ContractCandidateRateEntry(BaseModel):
    """One step in the candidate-rate schedule returned to the client."""

    id: int
    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractClientRateEntry(BaseModel):
    """One step in the client-rate schedule returned to the client."""

    id: int
    rate: float
    effective_from: date
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractFrameworkRateInput(BaseModel):
    """One step in the framework-rate schedule sent from a create/edit form.

    ``effective_to`` ("Obowiązuje do") is the optional planned end of the step;
    it is advisory (see the model). Mirrors ``ContractCandidateRateInput``.
    """

    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None


class ContractFrameworkRateEntry(BaseModel):
    """One step in the framework-rate schedule returned to the client."""

    id: int
    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractCreate(BaseModel):
    candidate_id: int
    client_id: int
    job_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[float] = None
    rate_client: Optional[float] = None
    # `float`, NIE `int` — stawki ramowe/widełki bywają z groszami (np. 215,60);
    # Pydantic `int` odrzuca część ułamkową 422-ką zamiast zaokrąglić.
    framework_rate: Optional[float] = None
    target_rate_min: Optional[float] = None
    target_rate_max: Optional[float] = None
    currency: str = "PLN"
    rate_unit: RateUnit = RateUnit.monthly
    billing_hours_per_month: int = 160
    # Effective-dated candidate-rate schedule (optional). When provided, drives
    # the candidate rate over time; `rate_candidate` is derived from it.
    candidate_rate_schedule: Optional[list[ContractCandidateRateInput]] = None
    # Effective-dated framework-rate schedule (optional). When provided, drives
    # the framework rate over time; `framework_rate` is derived from it.
    framework_rate_schedule: Optional[list[ContractFrameworkRateInput]] = None
    contract_type: ContractType = ContractType.b2b
    # Rejestr kontraktów per klient pozwala operatorowi jawnie wybrać stan
    # importowanej / już istniejącej umowy i ten wybór jest HONOROWANY — ale
    # jako PRZEJŚCIE, nie jako wartość wpisywana wprost do kolumny. Wiersz
    # rodzi się szkicem, a ``create_contract`` przeprowadza go do wybranego
    # stanu przez ``contract_lifecycle`` (patrz ``_apply_contract_status_change``).
    #
    # Praktyczna różnica, dla której warto było to pogodzić zamiast wybierać:
    # ``active`` (i ``ending``, bo to ``active`` z bliskim końcem) wymaga
    # kompletu pól z ``ACTIVATION_REQUIRED_FIELDS`` oraz ukończonego podpisu,
    # gdy proces podpisu ruszył; ``ended`` domyka datę końca i synchronizuje
    # zamówienia klienta. Ładunek, który tych warunków nie spełnia, dostaje
    # 409 z listą braków — zamiast umowy wchodzącej do MRR z pustymi stawkami.
    # Brak pola nadal oznacza bezpieczny ``draft``.
    status: ContractRegisterStatus = ContractStatus.draft
    documents: Optional[Any] = None
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    line_manager: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    # Per-klient rejestr (migracja 0138)
    project_code: Optional[str] = None
    prolongation_status: ProlongationStatus = ProlongationStatus.unknown
    engagement_model: EngagementModel = EngagementModel.time_based
    hours_pool_total: Optional[int] = None
    hours_pool_consumed: Optional[int] = None
    # Zużycie zamówienia (migracja 0144) — ilość + jednostka RBH/MD.
    order_consumption: Optional[float] = None
    order_consumption_unit: Optional[OrderConsumptionUnit] = None


class ContractUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[float] = None
    rate_client: Optional[float] = None
    # Effective-dated candidate-rate schedule ("stawka progresywna"). When the
    # key is present the endpoint REPLACES the whole schedule with these steps
    # and re-derives `rate_candidate` from them; omit the key to leave the
    # existing schedule untouched (backward-compatible for partial PATCHes).
    candidate_rate_schedule: Optional[list[ContractCandidateRateInput]] = None
    # Effective-dated framework-rate schedule ("stawka z umowy ramowej"). When the
    # key is present the endpoint REPLACES the whole schedule with these steps and
    # re-derives `framework_rate` from them; omit the key to leave the existing
    # schedule untouched (backward-compatible for partial PATCHes).
    framework_rate_schedule: Optional[list[ContractFrameworkRateInput]] = None
    # `float`, NIE `int` — grosze (215,60) w stawce ramowej/widełkach (jak wyżej).
    framework_rate: Optional[float] = None
    target_rate_min: Optional[float] = None
    target_rate_max: Optional[float] = None
    currency: Optional[str] = None
    rate_unit: Optional[RateUnit] = None
    billing_hours_per_month: Optional[int] = None
    contract_type: Optional[ContractType] = None
    # Rejestr klienta edytuje wszystkie cztery operacyjne stany kontraktu.
    # Dedykowane endpointy lifecycle nadal obsługują podpis, void i zakończenie
    # z metadanymi; ten PATCH zachowuje jednak jawny wybór statusu z rejestru.
    status: Optional[ContractRegisterStatus] = None
    documents: Optional[Any] = None
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    line_manager: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    termination_reason: Optional[ContractTerminationReason] = None
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None
    # Per-klient rejestr (migracja 0138) — wszystkie opcjonalne dla PATCH.
    project_code: Optional[str] = None
    prolongation_status: Optional[ProlongationStatus] = None
    engagement_model: Optional[EngagementModel] = None
    hours_pool_total: Optional[int] = None
    hours_pool_consumed: Optional[int] = None
    # Zużycie zamówienia (migracja 0144) — opcjonalne dla PATCH.
    order_consumption: Optional[float] = None
    order_consumption_unit: Optional[OrderConsumptionUnit] = None

    @model_validator(mode="after")
    def reject_explicit_null_status(self) -> "ContractUpdate":
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Status kontraktu nie może być pusty")
        return self

    @model_validator(mode="after")
    def reject_ending_without_end_date(self) -> "ContractUpdate":
        """„Kończący się" bez daty końca to kontrakt, który nigdy nie ustanie.

        ``ending`` jest w ``REVENUE_BEARING_STATUSES`` i przechodzi predykat
        ``end_date IS NULL OR end_date >= on``, więc bezterminowy wiersz
        w tym statusie liczy się jako aktywny BEZTERMINOWO i bez końca alarmuje
        skaner wygasania. Serwerowe samoleczenie (``_status_after_end_date_change``)
        jest tu wyłączone z rozmysłem — uruchamia się wyłącznie dla PATCH-a BEZ
        statusu, żeby nie nadpisywać jawnego wyboru operatora. Skoro nikt tego
        nie naprawi później, sprzeczność trzeba odrzucić od razu.

        Świadomie NIE dotyczy to ``ended``: tam handler stempluje datę dnia
        bieżącego i synchronizuje zamówienia klienta, czyli intencja „ta umowa
        się skończyła" ma pełne, udokumentowane wykonanie.

        Warunek patrzy na ``model_fields_set``, bo PATCH jest częściowy: brak
        klucza ``end_date`` znaczy „nie ruszaj daty z bazy" i może dotyczyć
        kontraktu, który datę końca ma. Odrzucamy wyłącznie ładunek sprzeczny
        sam ze sobą.
        """
        sends_null_end_date = (
            "end_date" in self.model_fields_set and self.end_date is None
        )
        if sends_null_end_date and self.status == ContractStatus.ending:
            raise ValueError(
                "Status \u201eKończący się\u201d wymaga daty zakończenia "
                "— kontrakt bezterminowy się nie kończy"
            )
        return self


class ContractSiblingRef(BaseModel):
    """Inny kontrakt TEJ SAMEJ osoby (zwykle u innego klienta).

    Zasila przełącznik zakładek nazwanych po kliencie w szczegółach kontraktu
    („pracuje u N klientów"). Celowo BEZ pól kwotowych — chip nawiguje do
    pełnego widoku tamtego kontraktu, gdzie stawki podlegają zwykłej redakcji
    VIEW_FINANCE; tu nie ma czego redagować.
    """

    id: int
    client_id: int
    client_name: Optional[str] = None
    status: ContractStatus
    contract_type: ContractType
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ContractGroupMember(BaseModel):
    """Jedna umowa w ZGRUPOWANYM wierszu listy (jedna osoba × N klientów).

    Lista z ``group_by_candidate=true`` zwraca jeden wiersz na osobę; kolumny
    okresu, stawek i marży są rozbijane per klient z tych wpisów. Pola kwotowe
    podlegają tej samej redakcji VIEW_FINANCE co wiersz główny
    (``_redact_contract_finance`` czyści też członków grupy).
    """

    id: int
    client_id: int
    client_name: Optional[str] = None
    status: ContractStatus
    contract_type: ContractType
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    latest_order_end_date: Optional[date] = None
    job_title: Optional[str] = None
    rate_candidate: Optional[float] = None
    rate_client: Optional[float] = None
    margin: Optional[float] = None
    rate_unit: Optional[RateUnit] = None
    currency: Optional[str] = None


class ContractResponse(BaseModel):
    id: int
    # NULL = umowa odpięta od usuniętego kandydata (migracja 0225). Rejestr umów
    # MUSI takie wiersze pokazywać — na umowie wiszą faktury i podpisy, których
    # retencja nie zależy od obecności osoby w bazie rekrutacyjnej. Gdyby to
    # pole zostało nienullowalne, pierwsze usunięcie kandydata wywracałoby
    # walidację odpowiedzi i cały rejestr zwracałby 500.
    # (`ContractCreate.candidate_id` zostaje `int` — umowy bez kandydata się
    # nie zakłada, tylko się z niego odpina.)
    candidate_id: Optional[int] = None
    client_id: int
    job_id: Optional[int]
    start_date: Optional[date] = None
    end_date: Optional[date]
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[float]
    rate_client: Optional[float]
    framework_rate: Optional[float] = None
    target_rate_min: Optional[float] = None
    target_rate_max: Optional[float] = None
    currency: Optional[str] = None
    rate_unit: Optional[RateUnit] = None
    billing_hours_per_month: Optional[int] = None
    margin: Optional[float]
    # Effective-dated candidate-rate schedule (oldest → newest). Empty for
    # contracts created before the schedule feature.
    candidate_rate_schedule: list[ContractCandidateRateEntry] = []
    # Effective-dated client-rate schedule (oldest → newest). Empty until a
    # `rate_change` amendment first defers the client rate to a future date.
    client_rate_schedule: list[ContractClientRateEntry] = []
    # Effective-dated framework-rate schedule (oldest → newest). Empty for
    # contracts without a planned framework-rate change (the common case).
    framework_rate_schedule: list[ContractFrameworkRateEntry] = []
    contract_type: ContractType
    status: ContractStatus
    documents: Optional[Any]
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    line_manager: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    termination_reason: Optional[ContractTerminationReason] = None
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None
    # Per-klient rejestr (migracja 0138)
    project_code: Optional[str] = None
    prolongation_status: ProlongationStatus = ProlongationStatus.unknown
    engagement_model: EngagementModel = EngagementModel.time_based
    hours_pool_total: Optional[int] = None
    hours_pool_consumed: Optional[int] = None
    # Zużycie zamówienia (migracja 0144) — ilość + jednostka RBH/MD.
    order_consumption: Optional[float] = None
    order_consumption_unit: Optional[OrderConsumptionUnit] = None
    # Computed (model properties) — pozostałe godziny i % zużycia puli.
    hours_pool_remaining: Optional[int] = None
    hours_pool_usage_pct: Optional[float] = None
    # Draft body provenance (migracja 0058) — `content_html` itself is fetched
    # via the dedicated /draft endpoint to keep list payloads small.
    draft_template_id: Optional[int] = None
    draft_updated_at: Optional[datetime] = None
    draft_updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # Denormalized names — populated when relations are eager-loaded.
    candidate_name: Optional[str] = None
    client_name: Optional[str] = None
    job_title: Optional[str] = None
    # DL Portal refactor 2026-05-11: data końca aktualnego zamówienia klienta.
    # Z `Contract.client_orders` — najnowszy Order po end_date. Różny semantycznie
    # od `Contract.end_date` (umowa B2B z konsultantem, zwykle dłuższa) vs
    # `latest_order_end_date` (PDF od klienta, zwykle krótszy horyzont 3-6mc).
    latest_order_end_date: Optional[date] = None
    # Konsolidacja kontraktorów wieloklientowych: przy `group_by_candidate=true`
    # lista zwraca jeden wiersz na OSOBĘ, a wszystkie jej umowy (spełniające
    # aktywne filtry) lądują tutaj — także gdy jest tylko jedna, żeby FE nie
    # musiał rozróżniać „wiersz stary" od „wiersz zgrupowany". W trybie płaskim
    # (domyślnym) pole zostaje puste.
    group_members: list[ContractGroupMember] = []

    model_config = {"from_attributes": True}


class ContractTerminateRequest(BaseModel):
    """Payload dla dedykowanego POST /{id}/terminate."""

    termination_reason: ContractTerminationReason
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None  # default = today


class ContractBenchmarkComparison(BaseModel):
    """Porównanie stawki kontraktu vs nasza średnia vs rynek."""

    contract_rate_monthly: Optional[int] = None
    internal_avg_monthly: Optional[int] = None
    internal_median_monthly: Optional[int] = None
    internal_sample_size: int = 0
    market_min: Optional[int] = None
    market_median: Optional[int] = None
    market_max: Optional[int] = None
    market_source: Optional[str] = None
    market_source_date: Optional[date] = None
    role_used: Optional[str] = None
    currency: str = "PLN"


class ContractTimelineItem(BaseModel):
    """Połączony feed notes+calls per kontrakt (timeline)."""

    id: int
    kind: str  # "note" | "call"
    at: datetime
    summary: Optional[str] = None
    content: Optional[str] = None
    sub_type: Optional[str] = None  # note_type lub direction
    status: Optional[str] = None
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    duration_seconds: Optional[int] = None

    model_config = {"from_attributes": True}


class ContractList(BaseModel):
    items: list[ContractResponse]
    total: int
    page: int
    page_size: int


class ContractEurPlnRate(BaseModel):
    """NBP table A snapshot used for the EUR amounts on contract detail."""

    rate: float
    effective_date: date
    source: str = "NBP"
    table: str = "A"


class ContractDetailResponse(ContractResponse):
    """Extended response for the contract detail page — includes denormalized names."""

    candidate_name: Optional[str] = None
    client_name: Optional[str] = None
    job_title: Optional[str] = None
    monthly_rate_candidate: Optional[float] = None
    monthly_rate_client: Optional[float] = None
    monthly_margin: Optional[float] = None
    # Present only for EUR contracts visible to a VIEW_FINANCE caller. The
    # effective date belongs to NBP and can intentionally precede today on a
    # weekend, holiday, or before the new table is published.
    eur_pln_rate: Optional[ContractEurPlnRate] = None
    # Pozostałe kontrakty tej samej osoby (bez `void`), zawężone do klientów
    # widocznych dla wołającego (scope Delivery Leada). FE renderuje z nich
    # przełącznik zakładek nazwanych po kliencie („pracuje u N klientów").
    related_contracts: list[ContractSiblingRef] = []

    model_config = {"from_attributes": True}


class ContractActivityEntry(BaseModel):
    id: int
    action: str
    details: Optional[Any] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractRateHistoryEntry(BaseModel):
    id: int
    # ``None`` when redacted for non-VIEW_FINANCE readers (P0.12).
    rate: Optional[float] = None
    currency: Optional[str] = None
    contract_type: str
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Contractor module ────────────────────────────────────────────────────────
# These schemas back the `/api/contractors` router and the new draft→active
# activation endpoint. The contractor view aggregates Contracts with status
# IN (draft, active, ending); drafts are exposed separately as "do uzupełnienia".


class ContractActivateRequest(BaseModel):
    """Payload for POST /api/contracts/{id}/activate.

    Empty body — the assumption is that the client has already PATCH-ed the
    contract with the required fields. The activation endpoint only validates
    and flips the status. A future iteration may accept inline field updates
    here to collapse PATCH+activate into one call.
    """


class ContractReopenRequest(BaseModel):
    """Payload for POST /api/contracts/{id}/reopen — audited revert to `draft`.

    Replaces the removed free ``PATCH {status: draft}`` write. The optional
    reason is recorded in the audit trail.
    """

    reason: Optional[str] = None


class ContractVoidRequest(BaseModel):
    """Payload for POST /api/contracts/{id}/void — soft-delete (annul).

    Used instead of a hard DELETE for executed/active contracts so documents and
    signature evidence are preserved.
    """

    reason: Optional[str] = None


# ── Editable draft (migracja 0058) ───────────────────────────────────────


class ContractTemplateBrief(BaseModel):
    """Minimal template descriptor returned with the draft so the FE can
    render the "Wybierz szablon" dropdown without a second roundtrip."""

    id: int
    name: str
    contract_type: str
    is_default: bool

    model_config = {"from_attributes": True}


class ContractDraftResponse(BaseModel):
    """Full draft state for the editor."""

    contract_id: int
    content_html: Optional[str] = None
    template_id: Optional[int] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
    updated_by_name: Optional[str] = None
    available_templates: list[ContractTemplateBrief] = []
    # When True the FE knows it should warn the user that no default template
    # is configured for this contract_type and it has to pick one manually.
    rendered_from_default: bool = False


class ContractDraftUpdate(BaseModel):
    """Partial update — either swap the template (re-render) OR save edited
    HTML, never both at once. Validated in the endpoint."""

    template_id: Optional[int] = None
    content_html: Optional[str] = None


class ContractDraftFinalizeResponse(BaseModel):
    """Result of POST /{id}/draft/finalize."""

    contract_id: int
    status: ContractStatus
    document_id: Optional[int] = None
    document_filename: Optional[str] = None


class ContractorCandidateRef(BaseModel):
    id: int
    name: str
    lastname: str
    email: Optional[str] = None


class ContractorListItem(BaseModel):
    """Single row in the Contractors list view."""

    contract_id: int
    candidate: ContractorCandidateRef
    # client_id potrzebny akcji „Zakończ projekt" (ticket #5) — modal
    # terminacji invaliduje cache per-klient (profil, zamówienia).
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    job_title: Optional[str] = None
    status: ContractStatus
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_candidate: Optional[float] = None
    rate_client: Optional[float] = None
    rate_unit: Optional[RateUnit] = None
    currency: Optional[str] = None
    margin: Optional[float] = None
    contract_type: ContractType
    work_mode: Optional[ContractWorkMode] = None
    # Only populated for drafts — lists the required fields still missing
    # so the UI can badge the row ("3 braki") and skip the full detail fetch.
    missing_fields: list[str] = []


class ContractorList(BaseModel):
    items: list[ContractorListItem]
    total: int
    page: int
    page_size: int


class ContractorStats(BaseModel):
    """Counts for the admin dashboard widget + tab headers."""

    draft: int = 0
    drafts_incomplete: int = 0
    active: int = 0
    ending: int = 0


class RegisterSubcategoriesResponse(BaseModel):
    """Distinct `Job.subcategory` values powering the register subcategory filter."""

    subcategories: list[str]
