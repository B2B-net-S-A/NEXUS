from datetime import date, datetime, time
from typing import Literal, Any, List, Optional

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.models.job import (
    JobCloseReason,
    JobPriority,
    JobStatus,
    RemotePolicy,
    Seniority,
    WorkMode,
)
from app.schemas.candidate import _normalize_skill_list
from app.schemas.job_team import JobRecruiterOut
from app.schemas.matching_requirements import MatchingRequirements
from app.services.job_priority import level_of


class JobCreate(BaseModel):
    # Runda 9 (R9-N15-5): długości = kolumny `jobs`; dłuższy napis dawał
    # `StringDataRightTruncation`, czyli 500 bez CORS zamiast 422.
    title: str = Field(max_length=255)
    description: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=255)
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    # Budżet PLN/h dla kandydata (dealbreaker-switch; 0235).
    rate_budget_hourly: Optional[float] = Field(default=None, gt=0, le=2000)
    # 0420: „od” z przedziału budżetu — tylko do wyświetlania; budżetem jest
    # górna granica (`rate_budget_hourly`, services/job_budget_range.py).
    rate_budget_hourly_min: Optional[float] = Field(default=None, gt=0, le=2000)
    # 0278: bez domyślnej — „nieznane” jest stanem uczciwym, „hybrid” domyślne
    # kłamało dla każdej oferty, której nikt ręcznie nie ustawił.
    remote_policy: Optional[RemotePolicy] = None
    # Trzecia rubryka rekrutacji (obok must-have i rate_budget_hourly, 0278).
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    # „N dni w miesiącu” (0407) — gdy podane, dni w tygodniu wylicza serwer.
    onsite_days_per_month: Optional[int] = Field(default=None, ge=1, le=22)
    # Rekrutacja bez szkiców (04.10.2026): pola ``status`` NIE MA — serwer
    # zawsze zakłada rekrutację opublikowaną i przekazaną do searchu. Stary
    # klient wysyłający ``status`` jest ignorowany (``extra`` = ignore).
    priority: JobPriority = JobPriority.medium
    needs_sourcing: bool = False
    deadline: Optional[date] = None
    # 0406: godzina terminu (Europe/Warsaw); bez daty zapis ją czyści.
    deadline_time: Optional[time] = None
    # 0415: „Klient nie podał terminu” — wymagana decyzja, gdy brak daty.
    deadline_not_provided: bool = False
    # client_id: required od migracji 0120 (2026-05-27). NOT NULL na DB.
    # Tworzenie joba bez klienta zwraca 422 — orphan recordy nigdy nie wpadną
    # na listę /jobs (patrz QA sweep PR fix/qa-jobs-orphan-cleanup).
    client_id: int = Field(..., gt=0)
    recruiter_id: Optional[int] = None
    # TAC + Delivery Lead — jeśli podane jawnie, wygrywa nad auto-assignem.
    # Jawny TAC musi być przypisany do klienta; auto-assign TAC działa tylko
    # dla dokładnie jednego aktywnego przypisania klienta.
    tac_id: Optional[int] = None
    delivery_lead_id: Optional[int] = None
    # Hiring manager — Contact w firmie klienta odpowiedzialny za rekrutację
    # (migracja 0097, 2026-05-11). Nullable; od 25.09.2026 musi należeć do client_id.
    hiring_manager_contact_id: Optional[int] = None
    portals: Optional[Any] = None

    # Phase 1 structured fields
    matching_requirements: Optional[MatchingRequirements] = None
    requirements_reviewed: bool = False
    must_skills: Optional[List[Any]] = None
    nice_skills: Optional[List[Any]] = None
    seniority: Optional[Seniority] = None
    work_mode: WorkMode = WorkMode.fulltime
    # Audyt 06.10.2026 (N6): bez domyślnej „1” — 55 z 55 rekrutacji miało 1,
    # bo formularz ją podstawiał. `None` przysłane wprost = „DL nie podał”
    # (bramka przekazania), pominięte = 1 dla innych wołających.
    headcount: Optional[int] = Field(default=None, ge=1, le=1000)
    reference_number: Optional[str] = Field(default=None, max_length=50)
    # 0380: numer zapytania klienta i tytuł dla rekrutera (`job_working_title`).
    # Brak ``working_title`` = składa go serwer i przelicza przy zmianach.
    client_reference: Optional[str] = Field(default=None, max_length=120)
    working_title: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=50)
    subcategory: Optional[str] = Field(default=None, max_length=100)
    custom_fields: Optional[dict] = None
    pipeline_template_id: Optional[int] = None
    # Phase 15 / Phase D: programme / ART tag — free-text, optional.
    # Auto-populated by `extract_train_name` when left empty.
    train_name: Optional[str] = Field(default=None, max_length=128)

    # AI CC matching (migracja 0041). Jeśli `competence_category_id` podane —
    # używamy jawnie; jeśli None + `auto_suggest_cc=true` — classifier wybiera
    # top-1 (albo zostawia None gdy remis <0.10). `secondary_cc_ids` do wider
    # matchingu (max 2, validated w endpointzie).
    competence_category_id: Optional[int] = None
    secondary_cc_ids: Optional[List[int]] = None
    auto_suggest_cc: bool = True

    # "Skopiuj jako template" (zakładka Historia requestu). Gdy ustawione,
    # backend kopiuje brakujące pola (description / requirements / skills /
    # train_name / seniority / industry / subcategory / headcount / work_mode /
    # remote_policy / salary range) z source job, plus `champion_profile`
    # tylko gdy nowy job jest u tego samego klienta. Pola, które klient
    # wypełnił w formularzu, mają precedencję.
    from_job_id: Optional[int] = Field(default=None, gt=0)
    # Jeśli True i `from_job_id` ustawione — kopiujemy też pinned interview
    # questions (job_questions) z source job. Idempotent dzięki unique
    # constraint (job_id, question_id).
    copy_questions: bool = False

    # ── Rekrutacja bez szkiców (04.10.2026) ─────────────────────────────────
    # Utworzenie = Profil Championa + decyzja o hiring managerze + przekazanie
    # do searchu + publikacja w JEDNEJ transakcji. Brak czegokolwiek, czego
    # wymaga bramka przekazania, = 422 ``job_not_ready`` i żadnego wiersza.
    champion_profile: dict
    hiring_manager: "JobCreateHiringManager"
    handoff: "JobHandoffRequest"
    # Rekrutacje wskazane jako podobne już przy tworzeniu (ta sama bramka
    # dostępu co ``POST /jobs/{id}/similar``).
    similar_job_ids: List[int] = Field(default_factory=list, max_length=20)
    # Delivery Lead zmienił podpowiedź kategorii — wpis ``CcSuggestionOverride``
    # w tej samej transakcji (tylko admin i Delivery Lead, jak trasa
    # ``/cc-override``; dla innych pomijany).
    cc_override: Optional["JobCreateCcOverride"] = None
    # Niedokończony formularz na koncie autora — kasowany razem z utworzeniem.
    intake_form_id: Optional[int] = Field(default=None, gt=0)

    @field_validator("must_skills", "nice_skills", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)

    @model_validator(mode="after")
    def _budget_range(self) -> "JobCreate":
        from app.services.job_budget_range import MSG_MIN_NOT_BELOW_MAX, min_below_max

        if not min_below_max(self.rate_budget_hourly_min, self.rate_budget_hourly):
            raise ValueError(MSG_MIN_NOT_BELOW_MAX)
        return self


_JOB_UPDATE_NOT_NULL_FIELDS = {
    "title": "Nazwa rekrutacji",
    "status": "Status",
    "priority": "Priorytet",
    "needs_sourcing": "Potrzebny search",
    "work_mode": "Wymiar pracy",
    "headcount": "Liczba osób",
    "client_id": "Klient",
    "hiring_manager_not_provided": "Hiring manager: klient nie podał",
    "deadline_not_provided": "Termin: klient nie podał",
}


class JobUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=255)
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    # Budżet PLN/h dla kandydata (dealbreaker-switch; 0235).
    rate_budget_hourly: Optional[float] = Field(default=None, gt=0, le=2000)
    # 0420: „od” z przedziału budżetu — tylko do wyświetlania; budżetem jest
    # górna granica (`rate_budget_hourly`, services/job_budget_range.py).
    rate_budget_hourly_min: Optional[float] = Field(default=None, gt=0, le=2000)
    remote_policy: Optional[RemotePolicy] = None
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    onsite_days_per_month: Optional[int] = Field(default=None, ge=1, le=22)
    status: Optional[JobStatus] = None
    priority: Optional[JobPriority] = None
    needs_sourcing: Optional[bool] = None
    deadline: Optional[date] = None
    # 0406: godzina terminu (Europe/Warsaw); bez daty zapis ją czyści.
    deadline_time: Optional[time] = None
    # 0415: „Klient nie podał” — zapis daty / kontaktu i tak zeruje flagę.
    deadline_not_provided: Optional[bool] = None
    hiring_manager_not_provided: Optional[bool] = None
    client_id: Optional[int] = None
    recruiter_id: Optional[int] = None
    tac_id: Optional[int] = None
    delivery_lead_id: Optional[int] = None
    hiring_manager_contact_id: Optional[int] = None
    portals: Optional[Any] = None

    # Phase 1 structured fields
    matching_requirements: Optional[MatchingRequirements] = None
    requirements_reviewed: bool = False
    must_skills: Optional[List[Any]] = None
    nice_skills: Optional[List[Any]] = None
    seniority: Optional[Seniority] = None
    work_mode: Optional[WorkMode] = None
    headcount: Optional[int] = Field(default=None, ge=1, le=1000)
    reference_number: Optional[str] = Field(default=None, max_length=50)
    client_reference: Optional[str] = Field(default=None, max_length=120)
    # Wartość = ręczny tytuł (automat wyłączony); pusty napis albo null =
    # powrót do tytułu składanego automatycznie.
    working_title: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=50)
    subcategory: Optional[str] = Field(default=None, max_length=100)
    custom_fields: Optional[dict] = None
    pipeline_template_id: Optional[int] = None
    competence_category_id: Optional[int] = None
    secondary_cc_ids: Optional[List[int]] = None
    # Phase 15 / Phase D: allow DL to set/override train_name explicitly.
    train_name: Optional[str] = Field(default=None, max_length=128)

    @field_validator("must_skills", "nice_skills", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)

    # Kolumny NOT NULL w `jobs` (runda 6 audytu): pole pominięte zostaje bez
    # zmian, ale jawny `null` był wpisywany w wiersz i kończył się 500
    # z bazy. Walidator nie biegnie dla pola pominiętego (brak
    # `validate_default`), więc łapie wyłącznie jawne `null`.
    @field_validator(*_JOB_UPDATE_NOT_NULL_FIELDS, mode="before")
    @classmethod
    def _reject_null_for_required_columns(cls, v: Any, info: Any) -> Any:
        if v is None:
            raise ValueError(
                f"Pole „{_JOB_UPDATE_NOT_NULL_FIELDS[info.field_name]}” "
                "nie może być puste."
            )
        return v


class CcSuggestion(BaseModel):
    """Pojedyncza sugestia CC z wyjaśnieniem decyzji."""

    competence_category_id: int
    slug: str
    name_pl: str
    score: float  # 0..1
    confidence_band: str  # "high" | "medium" | "low"
    keywords_matched: List[str] = []


class CcSuggestionsResponse(BaseModel):
    """Zwracana z POST /jobs (response) i POST /jobs/{id}/classify-cc."""

    top: Optional[CcSuggestion] = None
    alternatives: List[CcSuggestion] = []
    tie: bool = False  # True gdy |top-1 − top-2| < 0.10


class CcOverrideRequest(BaseModel):
    """Log override gdy DL zmienia sugerowaną CC."""

    suggested_cc_id: Optional[int] = None
    final_cc_id: Optional[int] = None
    suggested_score: Optional[float] = None


class UserBrief(BaseModel):
    """Minimal user projection embedded in job owner/collaborator responses."""

    id: int
    email: str
    name: str
    role: Optional[str] = None
    roles: list[str] = Field(default_factory=list)
    # Runda 9 (R9-V2-2): nieaktywny prowadzący = brak prowadzącego (front
    # pokazuje wtedy „Przejmij”, a `POST …/claim` je przyjmuje).
    is_active: bool = True

    model_config = {"from_attributes": True}

    @field_validator("role", mode="before")
    @classmethod
    def _role_to_str(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return getattr(v, "value", str(v))


class JobCollaboratorBrief(UserBrief):
    """Współpracownik rekrutacji: ``manual`` (dodany ręcznie) albo ``auto_cc``
    (cała kategoria kompetencji). „Rekruterem” rekrutacji są tylko ręczni."""

    source: str = "manual"


class JobResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    requirements: Optional[str]
    location: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    rate_budget_hourly: Optional[float] = None
    rate_budget_hourly_min: Optional[float] = None
    # 0278: nullable — patrz komentarz w JobCreate.
    remote_policy: Optional[RemotePolicy] = None
    onsite_days_per_week: Optional[int] = None
    onsite_days_per_month: Optional[int] = None
    status: JobStatus
    # Czy rekrutacja jest aktywnie prowadzona w NEXUSIE (0270). NIE to samo co
    # `status`, który jest lustrem Traffita — patrz `models/job.py`.
    is_open: bool = False
    # Skąd pochodzi rekrutacja ('traffit'/'manual') — baner o imporcie tylko dla Traffita.
    external_source: Optional[str] = None
    # 0325: „Rekrutacja prowadzona w NEXUSIE" + ślad przełączenia.
    managed_in_nexus: bool = False
    managed_in_nexus_at: Optional[datetime] = None
    managed_in_nexus_by: Optional[int] = None
    priority: JobPriority
    needs_sourcing: bool = False
    # 0341: Delivery Lead oznaczył „Mamy championa" — dalej nie szukamy.
    champion_found_at: Optional[datetime] = None
    # 0341: status requestu liczony przez `job_similarity.request_status_expr`
    # (closed · filled · contract · champion · incomplete · searching).
    request_status: Optional[str] = None
    # 0371: stan pracy nad requestem prowadzony w NEXUSIE (to_review ·
    # searching · client_silent · finished) i stan widoczny dla ludzi —
    # `request_work_state.visible_state` (champion przy „Szukamy”).
    work_state: str = "to_review"
    visible_work_state: Optional[str] = None
    # Tablica (22.09.2026): odznaka „Gotowy do Cpro" istnieje tylko u Nordei.
    cpro_enabled: bool = False
    # 0353: osoba, która wysyła do Cpro kandydatów tej rekrutacji (Nordea).
    cpro_sender_id: Optional[int] = None
    cpro_sender_name: Optional[str] = None
    deadline: Optional[date]
    deadline_time: Optional[time] = None
    deadline_not_provided: bool = False
    client_id: Optional[int]
    client_name: Optional[str] = None  # denormalized (coalesce(display_name, name))
    recruiter_id: Optional[int]
    tac_id: Optional[int] = None
    delivery_lead_id: Optional[int] = None
    hiring_manager_contact_id: Optional[int] = None
    hiring_manager_name: Optional[str] = None  # denormalized
    hiring_manager_not_provided: bool = False
    created_by: Optional[int]
    portals: Optional[Any]
    matching_requirements: Optional[MatchingRequirements] = None
    requirements_reviewed: bool = False
    must_skills: Optional[Any] = None
    nice_skills: Optional[Any] = None
    seniority: Optional[Seniority] = None
    work_mode: WorkMode = WorkMode.fulltime
    headcount: int = 1
    reference_number: Optional[str] = None
    client_reference: Optional[str] = None
    working_title: Optional[str] = None
    working_title_auto: bool = True
    industry: Optional[str] = None
    subcategory: Optional[str] = None
    custom_fields: Optional[Any] = None
    champion_profile: Optional[Any] = None
    embedding_id: Optional[str] = None
    criteria_generated_at: Optional[datetime] = None
    pipeline_template_id: Optional[int] = None
    competence_category_id: Optional[int] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_reason: Optional[JobCloseReason] = None
    close_notes: Optional[str] = None
    # Phase 15 / Phase D: programme tag surfaced to UI for autocomplete.
    train_name: Optional[str] = None
    # Hydrated ownership data added by api/jobs.get_job and assign/release
    # endpoints. ``primary_owner`` mirrors ``recruiter_id`` resolved to a
    # ``UserBrief`` so the UI does not need to do a second fetch to render the
    # owner badge. Both are ``None``/empty when the job is unassigned.
    primary_owner: Optional[UserBrief] = None
    collaborators: list[JobCollaboratorBrief] = []
    # Rola „Rekruter” (02.10.2026): osoby, które pracują nad rekrutacją —
    # prowadzący, aktywne przypisania i ręcznie dopisani współpracownicy —
    # plus propozycje automatu z ``proposed=True`` (`services/job_team`).
    # Wypełniają lista i ``GET /api/jobs/{id}``; inne odpowiedzi niosą pustą.
    recruiters: list[JobRecruiterOut] = []
    # Delivery Lead rozwinięty do ``UserBrief`` — wypełniają lista
    # (``GET /api/jobs``, „DL: …” obok rekrutera; zgłoszenie 30.09.2026) i
    # ``GET /api/jobs/{id}`` (Brief Profilu Championa, 04.10.2026).
    # Nazwa inna niż relacja ORM `Job.delivery_lead` — `model_validate(job)`
    # czytałby ją leniwie (MissingGreenlet → 500 na liście).
    delivery_lead_user: Optional[UserBrief] = None
    # Czy bieżący użytkownik może zapisać „stawkę do klienta" w tej rekrutacji
    # (`user_can_write_client_rate`: role zarządcze/Finanse albo właściciel/
    # twórca rekrutacji). Ustawiane tylko przez `GET /api/jobs/{id}`; tablica
    # pipeline i warsztat CV pokazują modal/pole stawki wyłącznie przy `True`.
    can_write_client_rate: Optional[bool] = None
    # Czy bieżący użytkownik redaguje treść rekrutacji (opis, ogłoszenia,
    # Champion) — admin, Delivery Lead, TAC albo osoba prowadząca rekrutację
    # i jej współpracownicy (decyzja 22.09.2026). `can_manage` = także cykl
    # życia i pola zablokowane dla zespołu (status, klient, obsada, widełki).
    # Ustawiane tylko przez `GET /api/jobs/{id}`.
    can_edit: Optional[bool] = None
    can_manage: Optional[bool] = None
    # Czy bieżący użytkownik przydziela i zdejmuje rekruterów (bramka
    # `/owner`: admin, Delivery Lead, Head of Recruitment) i czy ustawia
    # priorytet (te role + TAC). Head of Recruitment ma oba bez `can_manage`.
    # Ustawiane tylko przez `GET /api/jobs/{id}`.
    can_staff: Optional[bool] = None
    can_set_priority: Optional[bool] = None
    # Migawka dopasowań z przekazania do searchu — tylko odpowiedź
    # ``POST /api/jobs`` (rekrutacja bez szkiców, 04.10.2026).
    snapshot_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def priority_level(self) -> str:
        """Priorytet w trzech poziomach: ``p1`` · ``p2`` · ``accepting``.

        Ekrany i filtry mówią poziomami, kolumna zostaje przy czterech
        wartościach enuma (`services/job_priority`). Pole wyliczane, żeby każda
        odpowiedź (lista, szczegóły, PATCH) niosła je tą samą regułą.
        """
        return level_of(self.priority)

    @computed_field
    @property
    def opened_effective_at(self) -> datetime:
        """Data otwarcia do pokazania: ``opened_at``, a bez niej ``created_at``.

        ``opened_at`` stempluje tylko import Traffita — rekrutacja założona
        w NEXUSIE ma je puste. Filtr ``opened_from``/``opened_to`` listy liczy
        tą samą wartością.
        """
        return self.opened_at or self.created_at

    @computed_field
    @property
    def has_budget_hourly(self) -> bool:
        """Czy oferta ma ROZWIĄZYWALNY budżet PLN/h (jawne pole lub stawka
        Championa) — czyli czy sufit budżetowy ma na czym działać.

        Bool zamiast kwoty świadomie: `rate_budget_hourly` podlega redakcji
        finansowej dla viewera (`_VIEWER_REDACTED_JOB_FIELDS`), a UI potrzebuje
        wyłącznie informacji „jest co pilnować", żeby nie renderować aktywnego
        przełącznika, którego kliknięcie nic nie zmienia (review #1207).
        Liczone tą samą funkcją co filtr, więc nie może się z nim rozjechać.
        """
        from app.services.dealbreaker_filters import resolve_job_budget_hourly

        return resolve_job_budget_hourly(self) is not None

    @computed_field
    @property
    def effective_budget_hourly(self) -> Optional[float]:
        """Budżet PLN/h, którego używa wyszukiwanie (jawne pole lub Champion).

        Jedno źródło dla nagłówka rekrutacji, paska AI Matching i doku oferty
        (UAT B62/B72) — wcześniej każdy ekran czytał inne pole i ta sama
        rekrutacja miała budżet w nagłówku, a „brak danych” w doku. Pole jest
        redagowane dla viewera jak `rate_budget_hourly` i zdejmowane z listy
        razem z Profilem Championa.
        """
        from app.services.dealbreaker_filters import resolve_job_budget_hourly

        return resolve_job_budget_hourly(self)

    @computed_field
    @property
    def effective_budget_hourly_min(self) -> Optional[float]:
        """Dolna granica budżetu („60–80 zł/h”) — tylko do wyświetlania.

        Jawne „od” albo przedział z tekstu stawki Championa; None, gdy nie
        jest mniejsze od budżetu (`job_budget_range.effective_min`).
        """
        from app.services.job_budget_range import effective_min

        return effective_min(self)


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int


class JobOwnerAssignment(BaseModel):
    """Set/change the primary owner (`jobs.recruiter_id`).

    Admin + Delivery Lead only. To clear the assignment use
    DELETE /api/jobs/{id}/owner instead — this payload requires a target user.
    """

    user_id: int


class JobCollaboratorAdd(BaseModel):
    """Add a collaborator (read-only participant) to a job."""

    user_id: int


class JobCloseRequest(BaseModel):
    """Payload for POST /jobs/{id}/close — records why the job was closed."""

    reason: JobCloseReason
    notes: Optional[str] = None


class JobManageInNexusRequest(BaseModel):
    """Body `POST /api/jobs/{id}/manage-in-nexus`."""

    enabled: bool


class HiringManagerNewPerson(BaseModel):
    """Osoba wpisana ręcznie — serwis zakłada ją jako kontakt klienta."""

    name: str = Field(min_length=1, max_length=255)
    position: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = None

    @field_validator("position", "email", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class JobHiringManagerRequest(BaseModel):
    """Body `PUT /api/jobs/{id}/hiring-manager` — dokładnie jedno z czterech.

    ``not_provided`` (0415) = „Klient nie podał” — wymagana decyzja bramki
    przekazania, gdy hiring managera nie ma.
    """

    contact_id: Optional[int] = Field(default=None, gt=0)
    new_person: Optional[HiringManagerNewPerson] = None
    clear: bool = False
    not_provided: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> "JobHiringManagerRequest":
        chosen = sum(
            (
                self.contact_id is not None,
                self.new_person is not None,
                self.clear,
                self.not_provided,
            )
        )
        if chosen != 1:
            raise ValueError(
                "Wybierz osobę z listy, wpisz nową, zaznacz „Klient nie podał” "
                "albo wyczyść pole — jedno z czterech."
            )
        return self


class JobCreateHiringManager(BaseModel):
    """Hiring manager przy zakładaniu rekrutacji — kontakt, nowa osoba albo
    „Klient nie podał”. Pustej decyzji nie ma (rekrutacja bez szkiców)."""

    contact_id: Optional[int] = Field(default=None, gt=0)
    new_person: Optional[HiringManagerNewPerson] = None
    not_provided: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> "JobCreateHiringManager":
        chosen = sum(
            (
                self.contact_id is not None,
                self.new_person is not None,
                self.not_provided,
            )
        )
        if chosen != 1:
            raise ValueError(
                "Wybierz hiring managera z listy, wpisz nową osobę albo zaznacz "
                "„Klient nie podał”."
            )
        return self


class JobCreateCcOverride(BaseModel):
    """Podpowiedź kategorii, którą Delivery Lead zmienił przy zakładaniu."""

    suggested_cc_id: Optional[int] = Field(default=None, gt=0)
    suggested_score: Optional[float] = None


class HiringManagerOption(BaseModel):
    """Pozycja listy wyboru HM — bez danych kontaktowych."""

    id: int
    name: str
    position: Optional[str] = None


class JobHandoffRequest(BaseModel):
    """Payload for POST /jobs/{id}/handoff ("Przekaż do searchu").

    The Delivery Lead assigns the recruiter who will work the recruitment and
    starts the (Champion-aware) ranking. ``recruiter_id`` binds the recruiter as
    the job's owner for the pilot; the Priority Work roster is a later
    enhancement.
    """

    recruiter_id: Optional[int] = Field(default=None, gt=0)
    assignment_mode: Literal["manual", "automatic"] = "manual"
    channel: Literal["linkedin", "database", "mixed"] = "linkedin"
    top_k: Optional[int] = Field(default=None, gt=0)


class JobPublishRequest(JobHandoffRequest):
    """Body `POST /api/jobs/{id}/publish` — ponowne otwarcie rekrutacji.

    Otwarcie zamkniętej rekrutacji (i dokończenie starego szkicu) przechodzi
    tę samą bramkę co przekazanie do searchu, więc niesie przekazanie.
    """

    reason: Optional[str] = Field(default=None, max_length=500)


JobCreate.model_rebuild()
