"""Pydantic DTOs dla Generatora Umów B2B."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Status handlowy wygenerowanej umowy i katalog powodów zamknięcia. Wartości
# muszą pokrywać się z CHECK-ami na `b2b_generated_contracts` (model + migracje
# 0203/0224/0226 + safety-net entrypointu) — etykiety PL żyją po stronie
# frontendu.
#
# `in_progress` (0224) jest ustawiany WYŁĄCZNIE automatycznie: przy generowaniu
# umowy, a `active` wyłącznie przy potwierdzeniu podpisu obustronnego. Katalog
# jest jeden dla odczytu i zapisu; ręczny wybór `in_progress` odrzuca walidator
# `B2BGeneratedContractUpdate`, nie zawężony typ — patrz uzasadnienie tam.
#
# `suspended` (0226) = umowa nadal obowiązuje, ale kontraktor nie ma
# przypisanego projektu. Zasila zakładkę „Umowy bez projektu".
B2BContractStatus = Literal["active", "in_progress", "suspended", "closed"]
# Typ podmiotu Partnera. Katalog żyje w `services.b2b_contract_generator.
# entity_type`; tutaj powtórzony jako Literal, bo DTO nie może importować
# serwisu (cykl importów).
B2BPartnerEntityType = Literal["sole_trader", "company"]
# Powody zakończenia PROJEKTU (0226). Wspólne dla `closed` i `suspended` —
# jeden katalog, nie dwa: to samo zdarzenie („projekt się skończył") kończy albo
# zawiesza umowę w zależności od tego, czy szukamy kontraktorowi kolejnego
# zlecenia.
B2BClosureReason = Literal[
    "no_client_budget",
    "contractor_found_other_project",
    "contractor_health_reasons",
    "contractor_underperformance",
    "project_completed",
    "internalization",
    "other",
    # Katalog sprzed 0226 (opisywał ROZSTANIE Z PARTNEREM, nie koniec projektu).
    # Zniknął z pickera we froncie, ale zostaje tutaj i w CHECK-u, bo produkcja
    # ma wiersze `closed`, które te wartości niosą — bez nich odczyt takiego
    # wiersza wywracałby się na walidacji odpowiedzi, a historyczny powód
    # zamieniłby się w puste miejsce.
    "resignation_before_signing",
    "termination",
    "mutual_agreement",
]
# Powody wybieralne w UI — podzbiór `B2BClosureReason` bez wartości legacy.
# Serwowany przez API, żeby front i backend nie trzymały dwóch kopii kolejności.
B2B_SELECTABLE_CLOSURE_REASONS: tuple[str, ...] = (
    "no_client_budget",
    "contractor_found_other_project",
    "contractor_health_reasons",
    "contractor_underperformance",
    "project_completed",
    "internalization",
    "other",
)
# Statusy, które wymagają powodu i daty zakończenia (lustro gałęzi CHECK-a).
B2B_CLOSING_STATUSES: frozenset[str] = frozenset({"closed", "suspended"})


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
    # Typ podmiotu rozpoznany z rejestru w momencie lookupu (CEIDG → JDG,
    # KRS → spółka). Steruje wyłącznie tym, czy lista pokazuje drugą linię
    # z osobą kontaktową — treść dokumentu jest od tego niezależna.
    #
    # `Optional[str]` + walidator, NIE `Optional[Literal[...]]`, z dwóch
    # powodów. (1) Literal dałby 422 na CAŁYM `/render` za nieznaną wartość
    # podpowiedzi WYŚWIETLANIA — zły handel, bo użytkownik nie wygenerowałby
    # umowy. (2) `B2BRenderRequest(**row.render_payload)` odtwarza KAŻDY
    # historyczny payload przy ponownym pobraniu DOCX; pole wymagane albo
    # rygorystyczne zamieniłoby to w 422 dla wszystkich dotąd wygenerowanych
    # umów. CHECK w bazie zostaje ostateczną barierą.
    partner_entity_type: Optional[str] = None
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

    @field_validator("partner_entity_type")
    @classmethod
    def _known_entity_type(cls, v: Optional[str]) -> Optional[str]:
        """Nieznana wartość degraduje do ``None``, nie do 422.

        ``None`` oznacza „brak sygnału z rejestru", co serializer domyka
        heurystyką po nazwie firmy — czyli najgorszy skutek złej wartości to
        nadmiarowa druga linia, a nie zablokowane generowanie umowy.
        """
        return v if v in ("sole_trader", "company") else None

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
    # Klasyfikacja gotowa, nie surowe `source`/`krs` do interpretacji na
    # frontendzie: `source` przychodzi w czterech niespójnych formatach
    # („CEIDG", „KRS", „biala_lista", „krs", „biznes"), a wiedzę o obu źródłach
    # jednocześnie ma tylko `_merge`. Przepisanie tej tabeli prawdy do TS-a
    # znaczyłoby jej wieczne pilnowanie w dwóch miejscach.
    entity_type: Optional[B2BPartnerEntityType] = None


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
    # UWAGA: osoba fizyczna, NIE nazwa firmy. Zostaje w DTO z niezmienionym
    # znaczeniem, bo ma dwóch żywych konsumentów, którym potrzebna jest osoba:
    # etykietę w dialogu potwierdzenia podpisu i wyszukiwarkę. Nadpisanie go
    # nazwą firmy byłoby najprostszą i najgorszą wersją tej zmiany.
    partner_name: Optional[str] = None
    # Gotowe linie kolumny „Partner" — reguła rozpoznania JDG vs spółka ORAZ
    # reguła podciągu (kasująca duplikację nazwiska zawartego już w nazwie
    # firmy) żyją w serializerze, nie w komponencie. Powód: ten sam słownik form
    # prawnych musi obsłużyć zapis snapshotu przy generowaniu, a kopia w TS-ie
    # rozjechałaby się cicho — ten sam wiersz dostałby inną klasyfikację przy
    # zapisie i przy wyświetlaniu.
    partner_display_name: Optional[str] = None
    partner_secondary_line: Optional[str] = None
    # Kolumny „NIP" i „Data rozpoczęcia" na liście (snapshot z 0224). NIP jest
    # kanonicznie w samych cyfrach; `start_date` to data rozpoczęcia USŁUG,
    # nie data podpisania.
    partner_nip: Optional[str] = None
    start_date: Optional[date] = None
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

    ``job_id`` przypisuje umowie nowy projekt przy przywróceniu jej z zawieszenia
    (Ticket 6). Klient jest z niego wyprowadzany po stronie serwera — front go
    nie przesyła, żeby nie dało się zapisać pary projekt/klient, która w bazie
    do siebie nie należy.
    """

    client_name: Optional[str] = None
    contract_status: Optional[B2BContractStatus] = None
    closure_reason: Optional[B2BClosureReason] = None
    closure_reason_other: Optional[str] = None
    closure_date: Optional[date] = None
    job_id: Optional[int] = None

    @model_validator(mode="after")
    def _closure_fields_match_status(self) -> "B2BGeneratedContractUpdate":
        """Lustro CHECK-a ``ck_b2b_generated_contracts_closure_coherence``.

        Walidacja tutaj daje czytelny komunikat 422 po polsku zamiast surowego
        IntegrityError z bazy — sama baza pozostaje ostateczną barierą.

        Czego ten walidator NIE sprawdza i sprawdzić nie może: że przejście na
        „Zawieszona" wychodzi z „Aktywnej" i że przywracana umowa ma powiązany
        kontrakt. Oba wymagają znajomości BIEŻĄCEGO stanu wiersza, którego DTO
        nie widzi — egzekwuje je handler.
        """
        # `in_progress` jest stanem, PRZEZ który umowa przechodzi automatycznie,
        # nie stanem wybieranym. Odrzucane tutaj, a NIE przez zawężenie typu
        # pola do Literal["active","closed"], z dwóch powodów: (1) wąski Literal
        # daje angielskie „Input should be 'active' or 'closed'" bez wyjaśnienia,
        # czego ten plik testowy nie da się złapać przez `pytest.raises(match=)`;
        # (2) jeden katalog wartości dla odczytu i zapisu nie może się rozjechać.
        if self.contract_status == "in_progress":
            raise ValueError(
                "Status „W trakcie” ustawia system automatycznie przy "
                "generowaniu umowy — nie można go wybrać ręcznie. Umowa "
                "staje się „Aktywna” po potwierdzeniu podpisu."
            )

        if self.contract_status is None:
            # Jawne ``{"contract_status": null}`` != pominięcie pola. Bez tego
            # rozróżnienia null przechodzi walidację jako „brak zmiany statusu",
            # a potem ląduje w kolumnie NOT NULL → IntegrityError (500) zamiast
            # czytelnego 422. `contract_status` nie jest kasowalny: umowa zawsze
            # ma status.
            if "contract_status" in self.model_fields_set:
                raise ValueError("Status umowy nie może być pusty.")
            if {
                "closure_reason",
                "closure_reason_other",
                "closure_date",
            } & self.model_fields_set:
                raise ValueError(
                    "Pola zamknięcia można przesłać wyłącznie razem ze statusem umowy."
                )
            if "job_id" in self.model_fields_set:
                raise ValueError(
                    "Projekt można przypisać wyłącznie razem ze statusem „Aktywna”."
                )
            return self

        if self.contract_status in B2B_CLOSING_STATUSES:
            # Jeden komplet reguł dla obu statusów, ale komunikaty rozróżniają,
            # co się kończy: przy „Zawieszona" kończy się PROJEKT (umowa trwa),
            # przy „Zakończona" — UMOWA. Wspólny tekst kazałby użytkownikowi
            # zgadywać, o którą datę pyta formularz.
            suspending = self.contract_status == "suspended"
            subject = "projektu" if suspending else "umowy"
            if self.closure_reason is None:
                raise ValueError(f"Podaj powód zakończenia {subject}.")
            if self.closure_date is None:
                raise ValueError(f"Data zakończenia {subject} jest obowiązkowa.")
            other = (self.closure_reason_other or "").strip()
            if self.closure_reason == "other" and not other:
                raise ValueError(f"Wpisz własny powód zakończenia {subject}.")
            if self.closure_reason != "other" and other:
                raise ValueError("Własny powód można podać tylko dla powodu „Inny”.")
            if "job_id" in self.model_fields_set:
                raise ValueError(
                    "Projekt można przypisać wyłącznie razem ze statusem „Aktywna”."
                )
            return self

        # active → wszystkie pola zamknięcia muszą zostać wyczyszczone.
        if self.closure_reason is not None or self.closure_date is not None:
            raise ValueError("Aktywna umowa nie może mieć powodu ani daty zakończenia.")
        if (self.closure_reason_other or "").strip():
            raise ValueError("Aktywna umowa nie może mieć powodu ani daty zakończenia.")
        # Jawne ``{"job_id": null}`` != pominięcie pola. Przywrócenie umowy do
        # gry BEZ projektu jest dokładnie tym stanem, który opisuje „Zawieszona",
        # więc pusty projekt przy statusie „Aktywna" nie jest korektą, tylko
        # sprzecznością.
        if "job_id" in self.model_fields_set and self.job_id is None:
            raise ValueError("Wybierz projekt, do którego wraca kontraktor.")
        return self


class B2BStatusEventItem(BaseModel):
    """Wpis dziennika zmian statusu (dialog „Historia statusów").

    ``reason`` celowo NIE jest typowany jako ``B2BClosureReason``: dziennik jest
    zapisem tego, co się stało. Gdyby katalog powodów kiedyś się zmienił, wąski
    typ wywracałby odczyt historycznych wpisów — a to jedyne miejsce, w którym
    dane o zakończonych projektach przetrwały wyczyszczenie pól na umowie.
    """

    id: int
    from_status: Optional[str] = None
    to_status: str
    effective_date: Optional[date] = None
    reason: Optional[str] = None
    reason_other: Optional[str] = None
    job_id: Optional[int] = None
    job_title: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    changed_by_name: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class B2BConfirmFullySignedRequest(BaseModel):
    """One-time legacy binding supplied only when the generated row lacks IDs.

    ``keep_existing_contract_terms`` — świadome potwierdzenie mimo różnic
    między dokumentem a już istniejącym kontraktem tej pary (kandydat,
    rekrutacja). Serwer wtedy WIĄŻE podpisaną umowę z kontraktem, ale nie
    zmienia niczego, co na kontrakcie jest już wpisane (stawka, jednostka,
    harmonogram, daty, szczegóły B2B). Bez różnic flaga nic nie zmienia; nie
    obchodzi też żadnej innej odmowy (duplikaty kontraktorów, inny klient,
    kontrakt nie-B2B, zdublowane zamówienia, umowa już podpisana).
    """

    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    keep_existing_contract_terms: bool = False

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
    # Różnice zaakceptowane flagą ``keep_existing_contract_terms`` (etykiety
    # PL, te same co w komunikacie 409). Puste = warunki były zgodne albo
    # kontrakt powstał w tej operacji.
    acknowledged_conflicts: list[str] = Field(default_factory=list)
    # Dlaczego ``order_id`` jest puste mimo udanego podpisu: ``cost_client``
    # (typ zamówienia wybiera Delivery Lead) albo ``open_group_line`` (osoba
    # jest już na żywej linii zamówienia MD/kosztowego). ``None`` przy
    # wypełnionym ``order_id``.
    order_skipped_reason: Optional[str] = None
