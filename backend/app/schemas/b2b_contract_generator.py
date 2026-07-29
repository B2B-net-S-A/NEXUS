"""Pydantic DTOs dla Generatora Umów B2B."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Status handlowy wygenerowanej umowy i katalog powodów zamknięcia. Wartości
# muszą pokrywać się z CHECK-ami na `b2b_generated_contracts` (model + migracja
# 0202 + safety-net entrypointu) — etykiety PL żyją po stronie frontendu.
B2BContractStatus = Literal["active", "closed"]
B2BClosureReason = Literal[
    "resignation_before_signing",
    "termination",
    "mutual_agreement",
    "other",
]


class B2BRoleResponse(BaseModel):
    id: int
    category_key: str
    category_label_pl: str
    category_label_en: str
    slug: str
    name_pl: str
    name_en: str
    area_label_pl: str
    area_label_en: str
    scope_pl: list[str]
    scope_en: list[str]
    display_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class B2BRoleCreate(BaseModel):
    category_key: str
    slug: str
    name_pl: str
    name_en: str
    area_label_pl: str
    area_label_en: str
    scope_pl: list[str] = Field(default_factory=list)
    scope_en: list[str] = Field(default_factory=list)
    display_order: int = 0


class B2BRoleUpdate(BaseModel):
    category_key: Optional[str] = None
    name_pl: Optional[str] = None
    name_en: Optional[str] = None
    area_label_pl: Optional[str] = None
    area_label_en: Optional[str] = None
    scope_pl: Optional[list[str]] = None
    scope_en: Optional[list[str]] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class B2BRateStageInput(BaseModel):
    """Jeden etap stawki („stawka progresywna") w sekcji „Warunki umowy".

    ``effective_from``/``effective_to`` = „Obowiązuje od/do". Pierwszy etap może
    iść bez „od" (obowiązuje od rozpoczęcia świadczenia Usług), ostatni bez „do"
    (bezterminowo do końca umowy).
    """

    # Stawka bywa ułamkowa (np. 83,5 PLN/h) — `float`, NIE `int` (jak
    # `rate_candidate` niżej; Pydantic `int` odrzuca ułamek 422-ką).
    rate: float = Field(gt=0)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> "B2BRateStageInput":
        if (
            self.effective_from
            and self.effective_to
            and self.effective_to < self.effective_from
        ):
            raise ValueError(
                "„Obowiązuje do” nie może być wcześniejsze niż „Obowiązuje od”"
            )
        return self


_MAX_RATE_STAGES = 6


def _normalize_rate_stages(
    stages: Optional[list[B2BRateStageInput]],
) -> Optional[list[B2BRateStageInput]]:
    """Wspólna walidacja etapów stawki (render + generate).

    Sortuje chronologicznie (etap bez „od" jako pierwszy — startowy); przy
    kilku etapach każdy poza pierwszym musi mieć „Obowiązuje od", inaczej
    okresy w umowie byłyby nierozstrzygalne.
    """
    if not stages:
        return stages
    if len(stages) > _MAX_RATE_STAGES:
        raise ValueError(f"Maksymalnie {_MAX_RATE_STAGES} etapów stawki")
    ordered = sorted(
        stages,
        key=lambda s: (s.effective_from is not None, s.effective_from or date.min),
    )
    if len(ordered) > 1:
        for i, stage in enumerate(ordered[1:], start=2):
            if stage.effective_from is None:
                raise ValueError(
                    f"Etap {i} stawki progresywnej wymaga daty „Obowiązuje od”"
                )
    return ordered


class B2BGenerateRequest(BaseModel):
    # Strony — wymagane przy tworzeniu nowej umowy (gdy brak contract_id).
    candidate_id: Optional[int] = None
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    # Aktualizacja istniejącego draftu B2B zamiast tworzenia nowego.
    contract_id: Optional[int] = None

    role_id: int
    language: str = "pl"

    # Pola edytowalne umowy.
    contract_number: Optional[str] = None
    signing_date: Optional[date] = None
    start_date: date
    project_city: Optional[str] = None
    project_description: Optional[str] = None
    correspondence_address: Optional[str] = None
    # Stawka godzinowa bywa ułamkowa (np. 83,5 PLN/h) — `float`, NIE `int`.
    # `int` odrzucał 83.5 przez 422 (Pydantic wymusza liczbę całkowitą, NIE
    # zaokrągla), więc stawka trafiająca na `Contract.rate_candidate`
    # (Numeric(12,3)) musiała być ręcznie zaokrąglona do 84. Spójne z
    # `B2BRenderRequest` i `ContractCreate/Update`.
    rate_candidate: Optional[float] = None
    currency: str = "PLN"
    rate_in_words: Optional[str] = None
    # Stawka progresywna — kilka etapów (kwota + „Obowiązuje od/do") w ramach
    # jednej umowy. Brak/1 pozycja = zwykła pojedyncza stawka. Etapy trafiają
    # też do harmonogramu `Contract.candidate_rate_schedule`.
    rate_stages: Optional[list[B2BRateStageInput]] = None
    # Nadpisanie zakresu roli na poziomie tej umowy (None = użyj domyślnego).
    scope_items_override: Optional[list[str]] = None

    @field_validator("rate_stages")
    @classmethod
    def _sort_rate_stages(
        cls, v: Optional[list[B2BRateStageInput]]
    ) -> Optional[list[B2BRateStageInput]]:
        return _normalize_rate_stages(v)


class B2BGenerateResponse(BaseModel):
    contract_id: int
    draft_template_id: Optional[int] = None
    language: str


class B2BContractDetailResponse(BaseModel):
    contract_id: int
    candidate_id: Optional[int] = None
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    role_id: Optional[int] = None
    language: str
    contract_number: Optional[str] = None
    signing_date: Optional[date] = None
    start_date: Optional[date] = None
    project_city: Optional[str] = None
    project_description: Optional[str] = None
    correspondence_address: Optional[str] = None
    # Odczyt z `Contract.rate_candidate` (Numeric(12,3)) — `float`, by nie ucinać
    # groszy przy read-backu (i nie wywalać 500 na response_model dla stawki
    # ułamkowej, np. 83,5).
    rate_candidate: Optional[float] = None
    currency: Optional[str] = None
    rate_in_words: Optional[str] = None
    scope_items_override: Optional[list[str]] = None


class B2BRenderRequest(BaseModel):
    """Standalone render — wszystkie pola wprost z formularza (bez `Contract`)."""

    # Source entity links are optional for truly standalone documents, but when
    # one is supplied the pair is required and validated server-side against
    # CandidateStage. They are never inferred from partner/client names.
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    role_id: Optional[int] = None
    language: str = "pl"
    # Płeć Partnera — steruje formami gramatycznymi w komparycji/deklaracji
    # (Panem/ią, prowadzącym/cą, zwany/a, zapoznałem/am). "m" | "k".
    gender: str = "m"
    # Dane Partnera (firma) — edytowalne; pre-fill z kandydata opcjonalny.
    partner_name: Optional[str] = None
    # Imię i nazwisko w narzędniku do komparycji („z Panem Janem Kowalskim").
    # Liczone heurystycznie po stronie FE i edytowalne; pusty → mianownik.
    partner_instrumental: Optional[str] = None
    partner_legal_name: Optional[str] = None
    partner_business_address: Optional[str] = None
    partner_correspondence_address: Optional[str] = None
    partner_nip: Optional[str] = None
    partner_regon: Optional[str] = None
    partner_email: Optional[str] = None
    partner_phone: Optional[str] = None
    # Klient + projekt
    client_name: Optional[str] = None
    project_city: Optional[str] = None
    project_description: Optional[str] = None
    # Warunki
    contract_number: Optional[str] = None
    signing_date: Optional[date] = None
    start_date: Optional[date] = None
    # Tryb daty rozpoczęcia w §13: "exact" → „z dniem <data>";
    # "not_earlier" → „nie wcześniej niż <data>"; "not_later" → „nie później niż".
    start_date_mode: str = "exact"
    # Stawka godzinowa — może być ułamkowa (np. 135,5 PLN/h). `float`, NIE `int`:
    # input type="number" w formularzu wysyła „135.5", a Pydantic `int` odrzuca
    # liczbę z częścią ułamkową → 422. Formatowanie do postaci „135,50" robi
    # `format_rate` w `render_context`.
    rate_candidate: Optional[float] = None
    currency: str = "PLN"
    rate_in_words: Optional[str] = None
    # Stawka progresywna (kwota + „Obowiązuje od/do" per etap); brak/1 pozycja =
    # dotychczasowa pojedyncza stawka — stare payloady renderują się bez zmian.
    rate_stages: Optional[list[B2BRateStageInput]] = None
    scope_items_override: Optional[list[str]] = None

    @field_validator("rate_stages")
    @classmethod
    def _sort_rate_stages(
        cls, v: Optional[list[B2BRateStageInput]]
    ) -> Optional[list[B2BRateStageInput]]:
        return _normalize_rate_stages(v)

    @model_validator(mode="after")
    def _source_links_are_a_pair(self) -> "B2BRenderRequest":
        if (self.candidate_id is None) != (self.job_id is None):
            raise ValueError(
                "candidate_id i job_id muszą być przekazane razem albo pominięte"
            )
        return self


class B2BRenderHtmlResponse(BaseModel):
    html: str
    contract_number: Optional[str] = None


class B2BNextNumberResponse(BaseModel):
    contract_number: str
    year: int
    seq: int


class B2BCompanyLookupResponse(BaseModel):
    """Dane firmy z rejestru państwowego (Biała Lista MF / KRS)."""

    name: Optional[str] = None
    # Osoba fizyczna (JDG) — imię i nazwisko; dla spółek None.
    person: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None
    krs: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None


class B2BUopCheckRequest(BaseModel):
    text: str
    language: str = "pl"


class B2BUopIssue(BaseModel):
    phrase: str
    why: str
    suggestion: str


class B2BUopCheckResponse(BaseModel):
    """Wynik AI-sprawdzenia opisu pod kątem znamion umowy o pracę."""

    ok: bool
    issues: list[B2BUopIssue] = []
    rewritten: str = ""
    summary: str = ""


class B2BGeneratedContractItem(BaseModel):
    """Pozycja listy wygenerowanych umów (zakładka „Wygenerowane umowy")."""

    id: int
    contract_number: str
    partner_name: Optional[str] = None
    client_name: Optional[str] = None
    language: Optional[str] = None
    signing_date: Optional[date] = None
    created_at: Optional[str] = None
    # Imię i nazwisko osoby, która wygenerowała umowę (z users.name).
    created_by_name: Optional[str] = None
    # Czy bieżący użytkownik może usunąć ten wpis (autor wpisu lub admin).
    can_delete: bool = False
    # Czy bieżący użytkownik może edytować ten wpis (autor wpisu lub admin).
    can_edit: bool = False
    # Czy umowę da się pobrać ponownie (jest zapisany payload do re-renderu).
    can_download: bool = False
    signature_status: Literal["unsigned", "signed_both"] = "unsigned"
    signature_source: Optional[Literal["manual_confirmation", "validated_upload"]] = (
        None
    )
    # Status handlowy umowy — niezależny od statusu podpisu.
    contract_status: B2BContractStatus = "active"
    closure_reason: Optional[B2BClosureReason] = None
    closure_reason_other: Optional[str] = None
    closure_date: Optional[date] = None
    # Czy bieżący użytkownik może zmienić status umowy. W odróżnieniu od
    # ``can_edit`` NIE wygasa po podpisaniu — podpisaną umowę też się wypowiada.
    can_change_status: bool = False
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    client_id: Optional[int] = None
    contract_id: Optional[int] = None
    candidate_name: Optional[str] = None
    job_title: Optional[str] = None
    canonical_client_name: Optional[str] = None
    signed_at: Optional[str] = None
    signed_by_name: Optional[str] = None
    can_confirm_signed: bool = False
    blocked_reason: Optional[str] = None


class B2BGeneratedContractUpdate(BaseModel):
    """Edycja wpisu „Wygenerowane umowy": nazwa Klienta i/lub status umowy.

    ``client_name`` aktualizuje kolumnę (widoczną na liście) oraz
    ``render_payload['client_name']`` — dzięki temu ponowne pobranie DOCX ma już
    poprawioną nazwę, a per-klienta klauzule (§/załączniki) dobiorą się pod nią.
    Pusta/whitespace nazwa → ``None`` (kolumna jest nullowalna).

    Pola są opcjonalne i rozróżniane po ``model_fields_set`` — pominięcie pola
    zostawia je bez zmian, w odróżnieniu od jawnego przesłania ``null``. Bez
    tego dodanie statusu kasowałoby nazwę Klienta przy każdej zmianie statusu.
    """

    client_name: Optional[str] = None
    contract_status: Optional[B2BContractStatus] = None
    closure_reason: Optional[B2BClosureReason] = None
    closure_reason_other: Optional[str] = None
    closure_date: Optional[date] = None

    @model_validator(mode="after")
    def _closure_fields_match_status(self) -> "B2BGeneratedContractUpdate":
        """Lustro CHECK-a ``ck_b2b_generated_contracts_closure_coherence``.

        Walidacja tutaj daje czytelny komunikat 422 po polsku zamiast surowego
        IntegrityError z bazy — sama baza pozostaje ostateczną barierą.
        """
        if self.contract_status is None:
            if {
                "closure_reason",
                "closure_reason_other",
                "closure_date",
            } & self.model_fields_set:
                raise ValueError(
                    "Pola zamknięcia można przesłać wyłącznie razem ze statusem umowy."
                )
            return self

        if self.contract_status == "closed":
            if self.closure_reason is None:
                raise ValueError("Podaj powód zamknięcia umowy.")
            if self.closure_date is None:
                raise ValueError("Data zakończenia umowy jest obowiązkowa.")
            other = (self.closure_reason_other or "").strip()
            if self.closure_reason == "other" and not other:
                raise ValueError("Wpisz własny powód zamknięcia umowy.")
            if self.closure_reason != "other" and other:
                raise ValueError("Własny powód można podać tylko dla powodu „Inne”.")
            return self

        # active → wszystkie pola zamknięcia muszą zostać wyczyszczone.
        if self.closure_reason is not None or self.closure_date is not None:
            raise ValueError("Aktywna umowa nie może mieć powodu ani daty zakończenia.")
        if (self.closure_reason_other or "").strip():
            raise ValueError("Aktywna umowa nie może mieć powodu ani daty zakończenia.")
        return self


class B2BConfirmFullySignedRequest(BaseModel):
    """One-time legacy binding supplied only when the generated row lacks IDs."""

    candidate_id: Optional[int] = None
    job_id: Optional[int] = None

    @model_validator(mode="after")
    def _source_links_are_a_pair(self) -> "B2BConfirmFullySignedRequest":
        if (self.candidate_id is None) != (self.job_id is None):
            raise ValueError(
                "candidate_id i job_id muszą być przekazane razem albo pominięte"
            )
        return self


class B2BConfirmFullySignedResponse(BaseModel):
    outcome: Literal["created", "linked_existing", "already_processed"]
    contract_id: int
    order_id: Optional[int] = None
    candidate_id: int
    job_id: int
    client_id: int
    message: str
    generated_contract: B2BGeneratedContractItem
