from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.candidate_risk import CandidateOfferResponse
from app.models.contract import RateUnit
from app.models.recruitment_pipeline import (
    PipelineStage,
    StageCategory,
    VerificationStatus,
)
from app.schemas.candidate import EmploymentMarker
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
    # Uwaga dla rekrutera przy decyzji (wysyłka, „Wróć do poprawy”,
    # odrzucenie) — zapisywana jako notatka pary (`services/stage_remarks.py`).
    # Stawka do klienta ma własne pola niżej i tu nie trafia.
    recruiter_remark: Optional[str] = Field(None, max_length=2000)
    # D6 (08.10.2026): „Wróć do poprawy” z „QC CV” na „Zweryfikowany” — pola
    # do poprawy (`services/screening_fix_requests.py`): `question:<id>`,
    # `field:<pole karty>`, `field:overall_fit`, `candidate_rate`, `cv`.
    # Przy innym ruchu albo u Nordei → 422 `FIX_FIELDS_NOT_ALLOWED`.
    fix_fields: Optional[list[str]] = Field(None, max_length=30)
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
    # Temat i treść poprawione w podglądzie okna odrzucenia (13.10.2026) —
    # zwykły tekst, tylko przy jednej osobie. Brak pól = treść domyślna.
    # Temat do 998 znaków jak kolumna: domyślny „Informacja zwrotna — {tytuł}”
    # przy tytule rekrutacji do 255 znaków ma ~276 (przegląd PR #2185).
    rejection_email_subject: Optional[str] = Field(None, max_length=998)
    rejection_email_body: Optional[str] = Field(None, max_length=5000)
    # Dopisek o pozostałych rekrutacjach osoby (17.10.2026, D2) — `None`/`True`
    # = dopisz, gdy osoba jest w innych rekrutacjach od „Zweryfikowany”;
    # `False` = odznaczone w oknie, zwykłe zakończenie.
    rejection_email_other_processes: Optional[bool] = None
    # Wspólny mail (17.10.2026, D3) — `None`/`True` = gdy do osoby czeka już
    # mail odrzucenia z innej rekrutacji, wychodzi jeden o obu; `False` = osobny.
    rejection_email_merge: Optional[bool] = None
    # Powód „Nie akceptuje trybu pracy” (`work_mode_mismatch`, 14.10.2026):
    # ile dni w biurze kandydat akceptuje (0 = tylko zdalnie). Przy tym
    # powodzie wymagane, przy każdym innym → 422. `save_to_profile` = zapis
    # trybu pracy na profilu (ptaszek w oknie, domyślnie włączony).
    work_mode_max_onsite_days: Optional[int] = Field(None, ge=0, le=4)
    work_mode_save_to_profile: bool = True

    # ── Stawka kandydata przy ruchu na `verified` (0056, zmiana 17.09.2026) ─
    # OPCJONALNA. Do 17.09.2026 brak stawki dawał 422, a stawka ponad
    # `Job.salary_max` stawiała kartę na `pending` i czekała na admina.
    # Decyzja właściciela: żadna bramka nie zatrzymuje przepływu — stawkę
    # zapisujemy, gdy jest, a „ponad budżet" to odznaka na karcie (front liczy
    # ją z `effective_budget_hourly`), nie stan procesu.
    expected_rate_value: Optional[Decimal] = Field(None, ge=0)
    expected_rate_unit: Optional[RateUnit] = None
    expected_rate_currency: Optional[str] = Field(None, max_length=3)
    # „To jego nowe minimum” (0414): stawka z okna „Zweryfikowany” trafia też do
    # profilu jako jawne minimum — starsze, niższe stawki przestają się liczyć
    # do „Stawki od”. Działa tylko dla stawki w PLN.
    expected_rate_is_minimum: bool = False

    # ── Ręczny ruch na „Zatrudniony” (D2, 04.10.2026) ─────────────────────
    # Jak podpisano umowę spoza Generatora B2B; bez pola ruch na `hired`
    # dostaje 422 `HIRED_SIGNED_VIA_REQUIRED`. „other” wymaga opisu.
    hired_signed_via: Optional[Literal["b2b_offline", "uop", "zlecenie", "other"]] = (
        None
    )
    hired_signed_note: Optional[str] = Field(None, max_length=500)
    # 12.10.2026 (D3): osoba ma już trwającą umowę u innego klienta — co
    # z obecną współpracą. Serwer pola nie wymaga (okno zatrudnienia pyta, gdy
    # karta niesie znacznik „Pracuje u nas” u innego klienta); odpowiedź
    # trafia do dzwonka Delivery Leada obecnego klienta i do historii profilu.
    # Umów ani zamówień nie zmienia.
    hired_current_engagement: Optional[
        Literal["switch", "parallel", "ask_delivery_lead"]
    ] = None

    # ── Candidate offer response (migracja 0066 — Phase 17) ───────────────
    # Sensowne tylko gdy stage ∈ {acceptance, negotiation, onboarding}.
    # `declined` przed wycofaniem → post_accept dropout (10pt w risk score).
    candidate_offer_response: Optional[CandidateOfferResponse] = None

    # ── „Klient zaakceptował” (0451, 16.10.2026) ──────────────────────────
    # Wyłącznie przy ruchu na etap `acceptance` (inaczej 422). Brak daty =
    # akceptacja z dnia ruchu; start opcjonalny, nie przed akceptacją.
    client_accepted_on: Optional[date] = None
    planned_start_on: Optional[date] = None

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

    # ── Kto wysyła do Cpro (0348, Nordea) ─────────────────────────────────
    # Wyłącznie przy ruchu na etap „Wysłać do Cpro" (odznaka „Gotowy do
    # Cpro"): za każdym razem wysyła ktoś inny, więc osobę typuje ten, kto
    # oznacza gotowość. Przy innym etapie → 422.
    task_assignee_id: Optional[int] = Field(None, ge=1)

    # ── Pipeline v4 (23.09.2026) ───────────────────────────────────────────
    # Stawka do klienta w TYM SAMYM żądaniu co ruch na „CV wysłane". Poza
    # Nordeą wymagana i wpisuje ją Delivery Lead (`pipeline_move_rules`).
    client_rate_value: Optional[Decimal] = Field(None, gt=0)
    client_rate_unit: Optional[RateUnit] = None
    client_rate_currency: Optional[str] = Field(None, max_length=3)
    # Kto zakończył proces (ruch terminalny): kandydat | my | DL | klient.
    ended_by: Optional[Literal["candidate", "recruiter", "delivery_lead", "client"]] = (
        None
    )

    @field_validator("rejection_email_subject")
    @classmethod
    def _subject_one_line(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        one_line = " ".join(value.split())
        if not one_line:
            raise ValueError("Temat maila nie może być pusty.")
        return one_line

    @field_validator("rejection_email_body")
    @classmethod
    def _body_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("Treść maila nie może być pusta.")
        return value


class ClientRateUpdate(BaseModel):
    """Body dla PATCH /candidates/{id}/recruitments/{job_id}/client-rate.

    Ustawia „Stawkę do klienta" (sell rate) dla danej rekrutacji.
    `rate_value=None` → wyczyść stawkę. Gdy podana wartość bez jednostki,
    backend domyślnie przyjmuje `monthly`.
    """

    rate_value: Optional[Decimal] = Field(None, ge=0)
    rate_unit: Optional[RateUnit] = None
    rate_currency: Optional[str] = Field(default="PLN", max_length=3)
    # Zmiana po wysyłce CV (20.10.2026): powód do audytu i notatka DL-a
    # (wpis `dl_rate`). Wpis przy ruchu karty i stare wywołania ich nie niosą.
    reason: Optional[Literal["client_negotiated", "send_mistake", "other"]] = None
    note: Optional[str] = Field(default=None, max_length=500)


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
    # Numer tej osoby — filtr „Kto dodał” na Tablicy (14.10.2026).
    added_to_job_by_id: Optional[int] = None
    added_to_job_at: Optional[datetime] = None
    # Kto zweryfikował (najnowszy wiersz „Zweryfikowany” pary) — karta od tej
    # kolumny pokazuje tę osobę zamiast dodającej (20.10.2026). Tylko kanban.
    verified_by_name: Optional[str] = None
    verified_by_id: Optional[int] = None
    verified_at: Optional[datetime] = None
    # Karty w „Odrzuconych” i „Rezygnacjach” (19.10.2026): etykieta powodu
    # i kto zamknął kartę — ramka w panelu osoby i linia na karcie. Wypełnia
    # tylko Tablica; `None` przy innych etapach i gdzie indziej.
    rejection_reason_name: Optional[str] = None
    closed_by_name: Optional[str] = None
    # Set when this move caused a rejection email to be queued; lets the FE
    # show a "Cofnij wysyłkę" toast and anchor the cancel link.
    scheduled_rejection_email_id: Optional[int] = None
    # Runda 9 (R9-N11-2): los zaznaczonego maila odrzucenia — `scheduled`
    # albo powód, dla którego go NIE zaplanowano (`no_mailbox`,
    # `not_client_visible`, `no_candidate_email`, `no_permission`). `None`,
    # gdy nikt o mail nie prosił. Okno pokazuje powód zamiast ciszy.
    rejection_email_status: Optional[str] = None
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
    # Rekrutacja bez pytań screeningowych (13.10.2026): zamiast arkusza
    # wymagane jest „Dlaczego ten kandydat” — `screening_done` znaczy wtedy
    # „ocena wpisana”, a karta nie prosi o arkusz. `None` = zwykły arkusz.
    screening_requirement: Optional[str] = None
    # Karta liczy się do „Czeka na Ciebie” przeglądu DL (opublikowana
    # rekrutacja, etap nie z importu Traffita) — ta sama definicja co pas
    # „Do wysłania do klienta” (audyt 13.10.2026). `None` = endpoint nie liczy.
    dl_send_counts: Optional[bool] = None
    scorecard_done: bool = False
    # Auto-CV (21.09.2026): na TYM wierszu etapu leży gotowe CV zakolejkowane
    # przez system i nikt go jeszcze nie zatwierdził — „CV gotowe w tle —
    # sprawdź i wyślij". Wypełnia tylko tablica.
    auto_cv_ready: bool = False
    # Droga rekrutera do DL (14.10.2026): automat CV właśnie generuje szkic dla
    # TEGO wiersza etapu („CV w przygotowaniu…”) — `"processing"`, inaczej
    # `None`. Wypełnia tylko tablica.
    auto_cv_state: Optional[Literal["processing"]] = None
    # Para ma CV firmowe (`move_requirements.company_cv_refs` — ta sama reguła
    # co wymaganie ruchu na „QC CV”). `None` = endpoint tego nie liczy
    # (ruch, historia). Wypełnia tylko tablica.
    company_cv: Optional[bool] = None
    # QC CV (Rekrutacja v5, 0361): `{"status": "passed|failed|overridden|
    # unchecked", "blocking_failed": int, "warnings_count": int, …}` —
    # najnowszy przebieg pary (`cv_qc.pair_statuses`). Wypełnia tylko tablica.
    qc: Optional[dict] = None
    # Karta rekomendacji (0413): `{"status": "complete|partial|empty",
    # "missing": int, "answers": int, "rate_hourly": float | None}` albo `None`,
    # gdy pary nie ma jeszcze w `recommendation_cards`. `rate_hourly` to stawka
    # kandydata z karty (PLN/h) — podpowiedź w oknie stawki przy ruchu na
    # „Zweryfikowany”. Wypełnia tylko tablica.
    card: Optional[dict] = None
    # Notatki „nie odebrał” tej osoby (w tej rekrutacji i bez rekrutacji).
    contact_attempts: int = 0
    # Stawka z PROFILU kandydata (`Candidate.expected_rate_hourly`, PLN/h) —
    # podpowiedź w oknie „Zweryfikowany". Wypełnia tylko tablica.
    candidate_expected_rate_hourly: Optional[Decimal] = None
    # „Stawka od” (0414): najniższa stawka z 18 miesięcy — podpowiedź w oknie
    # „Zweryfikowany”, gdy karta tej rekrutacji nie ma stawki.
    candidate_rate_from_hourly: Optional[Decimal] = None
    # ── Tabela rekrutacji „wersja 3" (09.2026) — wypełnia tylko tablica ────
    # Rekruter karty: właściciel procesu, a bez niego osoba, która dodała
    # kandydata do rekrutacji. `moved_by` to mover BIEŻĄCEGO etapu — co innego.
    recruiter_id: Optional[int] = None
    recruiter_name: Optional[str] = None
    # 0348: kto wysyła osobę do Cpro — tylko na wierszu „Wysłać do Cpro".
    # Nazwisko wypełnia tablica.
    task_assignee_id: Optional[int] = None
    task_assignee_name: Optional[str] = None
    # Dostępność z profilu kandydata — te same nazwy pól co w wynikach
    # wyszukiwania (`availability_status` / `availability_date`).
    availability_status: Optional[str] = None
    availability_date: Optional[date] = None
    # Minimum dla DL przed „Zweryfikowany” (21.10.2026): klucze pól karty bez
    # treści (`move_requirements.board_minimum_missing`). Tylko na Tablicy;
    # `None` = endpoint nie liczy.
    minimum_missing: Optional[list[str]] = None
    # „W bazie od” (0437): kiedy osoba weszła do bazy (`candidate_added_date`),
    # czy data jest dokładna (import z Traffita bez daty u źródła = nie) i kto
    # ją dodał. Tylko na Tablicy (`build_kanban_view`); ruch i historia — None.
    candidate_added_at: Optional[datetime] = None
    candidate_added_exact: bool = False
    candidate_added_by_name: Optional[str] = None
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

    # ── Pipeline v4 (0352, 23.09.2026) ────────────────────────────────────
    # Kto zakończył proces (tylko wiersz terminalny).
    ended_by: Optional[str] = None
    # Stawka, za którą osobę wysłano do klienta (najnowszy wiersz pary).
    client_rate_value: Optional[Decimal] = None
    client_rate_unit: Optional[RateUnit] = None
    client_rate_currency: Optional[str] = None
    # Poniżej wypełnia tylko tablica:
    # skąd osoba weszła (added_manual|application|proposal|reassign|auto_match|
    # import; `None` = proces sprzed 0352) i rekrutacja przepięcia.
    entry_source: Optional[str] = None
    # 0399: wynik automatu przy wejściu („Auto-match 67/100 · JJIT”) —
    # {"score", "source", "must_hit", "must_total"}; `None` = wejście ręczne.
    entry_auto_match: Optional[dict] = None
    # 0404: przegląd zgłoszenia z linku rekrutacji — {"verdict", "assessed",
    # "must_found", "must_total", "overridden"}; `None` = wejście bez przeglądu.
    entry_ai_screening: Optional[dict] = None
    # Off-limits (21.10.2026): osoba z firmy z aktywnym zamówieniem dodana
    # po potwierdzeniu „sama się zgłosiła” — {"client_name", "company", "how",
    # "how_label", "confirmed_by_id", "confirmed_by_name", "confirmed_at"}.
    entry_off_limits: Optional[dict] = None
    # Etap 2 linków (19.10.2026): właściciel linku rekrutacji, z którego
    # osoba się zgłosiła — plakietka „Z Twojego linku” / „Z linku Marty N.”.
    entry_link_owner_id: Optional[int] = None
    entry_link_owner_name: Optional[str] = None
    # …i właściciele innych linków, z których osoba zgłosiła się PONOWNIE, gdy
    # już była w rekrutacji — „Zgłosił się też z Twojego linku”. Karta i
    # blokada prowadzącego bez zmian.
    reapplied_via_links: List["ReappliedViaLink"] = Field(default_factory=list)
    reassign_from_job_id: Optional[int] = None
    reassign_from_title: Optional[str] = None
    # Numer rekrutacji źródłowej („ZOB-1725") — odznaka „↻ z …" na karcie.
    reassign_from_reference: Optional[str] = None
    # 0450 (D3): żywy champion tej rekrutacji — złota plakietka na karcie
    # i przy nazwisku w panelu osoby.
    is_champion: bool = False
    # Blokada 12 h w „Nowych": kto i do kiedy; `can_take` = czy patrzący
    # może kliknąć „Biorę"/„Przejmij".
    claim_user_id: Optional[int] = None
    claim_user_name: Optional[str] = None
    claim_until: Optional[datetime] = None
    can_take: bool = False
    # Odznaka terminarza rozmowy u klienta (`interview_badges_for_job`):
    # {kind, label, tone, at}.
    interview_badge: Optional[dict] = None
    # 0372: follow-up z kandydatem, gdy klient milczy — kto dzwoni i kiedy:
    # {caller_id, caller_name, due_on, state, overdue_days, process_count}.
    followup: Optional[dict] = None
    # 0418: otwarta sprawa zmiany stawki kandydata (zgłoszona / w negocjacji /
    # ustalona): {id, status, requires_decision, previous_hourly,
    # requested_hourly, requested_label, agreed_hourly, negotiator_name, ...}.
    rate_change: Optional[dict] = None
    # „Zatrudniony": czy jest uzupełnione zamówienie (complete|missing).
    order_status: Optional[str] = None
    # 17.10.2026: „Zatrudniony” z ostatniego roku, a w Kontraktach nie ma
    # umowy tej osoby u klienta rekrutacji (`services/hire_contract_reminder`).
    missing_contract: bool = False
    # 04.10.2026: umowa B2B z Generatora tej pary (rejestr jest źródłem):
    # {id, number, contract_status, signature_status, created_at, signed_at,
    # signature_requested_at, contract_id}; brak = para bez umowy.
    agreement: Optional[dict] = None
    # 0451: ostatnia akceptacja klienta pary — {stage_id, accepted_on,
    # planned_start_on, marked_at, marked_by_name}; front rysuje ją tylko
    # w kolumnie „Akceptacja i umowa”.
    client_acceptance: Optional[dict] = None
    # 0505: umowa przedwstępna pary — `{id, state, label, tone, detail}`
    # z `services/pre_contracts.badge` (front tylko pokazuje).
    pre_contract: Optional[dict] = None
    # Znacznik „Pracuje u nas” (`services/employment_marker.py`); `elsewhere`
    # liczone względem klienta tej rekrutacji. Pulpit „Moje następne kroki”
    # go nie niesie (do 25 tablic w jednej odpowiedzi).
    employment_marker: Optional[EmploymentMarker] = None
    # „+1 rekrutacja” (14.10.2026): inne niezamknięte rekrutacje, w których ta
    # osoba stoi w „Nowych”/„Screeningu” (`services/also_fits.py`), najwyżej 5.
    # Tylko Tablica; pulpit „Moje następne kroki” — pusta lista.
    other_open_jobs: List["OtherOpenJob"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class OtherOpenJob(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    column: str


class ReappliedViaLink(BaseModel):
    owner_id: int
    owner_name: Optional[str] = None


CandidateStageResponse.model_rebuild()


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
    # Przegląd przed wysłaniem do klienta w tej rekrutacji należy do patrzącego
    # (`board_tasks.reviews_as_dl`) — karta w „QC CV” mówi mu „Czeka na Ciebie”.
    # To nie jest prawo wysyłki: to ma każdy z `recruitment_manage`.
    viewer_owns_dl_review: bool = False


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
