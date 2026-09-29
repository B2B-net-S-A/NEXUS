"""Rejestr typów dokumentów pochodnych — JEDYNE źródło definicji.

Czytają go: API (walidacja i efekty), front (``GET /document-types`` →
generyczny formularz zamiast dziesięciu ręcznych) i szablony (klucze pól są
kluczami ``{{ doc.* }}``). Dodanie typu = wpis tutaj + szablon w
``app/templates/documents/`` + gałąź w ``effects.py``; test pilnuje, że każdy
typ ma szablon w każdym zadeklarowanym języku.

Pola ``sensitive`` (PESEL, dowód, adres zamieszkania) trafiają WYŁĄCZNIE do
wydanego pliku — ``strip_sensitive`` usuwa je przed zapisem ``render_payload``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

FieldKind = Literal[
    "text",
    "textarea",
    "date",
    "money",
    "bool",
    "select",
    "email",
    "gender",
    # Lista pozycji stawki aneksu (kwota, klient z NEXUSA, od, do) — wartość
    # to lista słowników, nie tekst. Walidacja: ``rate_items_problems``.
    "rate_items",
]

#: Grupy pól w kolejności formularza. ``change`` = treść zmiany aneksu.
FieldGroup = Literal["base", "document", "partner", "change"]


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: FieldKind = "text"
    required: bool = False
    sensitive: bool = False
    help: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    #: Pole widoczne tylko, gdy inne pole ma wartość (np. klient zwolnienia
    #: z zakazu tylko przy zaznaczonym zwolnieniu). ``(klucz, wartość)``.
    show_if: tuple[str, object] | None = None
    group: FieldGroup = "document"
    #: Przycisk „Pobierz z rejestru” przy polu (NIP): front woła
    #: ``GET /company-lookup`` i przepisuje pola odpowiedzi do pól formularza
    #: wg ``lookup_fills`` — ``(klucz odpowiedzi, klucz pola)``. Użytkownik może
    #: je potem zmienić.
    lookup: Literal["registry"] | None = None
    lookup_fills: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DocumentType:
    key: str
    label: str
    family: Literal["annex", "termination", "preliminary"]
    languages: tuple[str, ...]
    #: ``b2b`` = umowa z rejestru; ``mandate`` = umowa zlecenie (wiersz rejestru
    #: z importu albo brak); ``none`` = dokument poprzedza umowę.
    parent: Literal["b2b", "mandate", "none"]
    fields: tuple[FieldDef, ...]
    #: Opis skutku podpisu dla okna „Oznacz jako podpisany” (serwer i tak
    #: liczy listę konkretnych zmian — to tylko nagłówek).
    effect_label: str
    description: str = ""
    signatories: Literal["both", "company", "partner_and_company"] = "both"
    #: Czy dokument wymaga numerów paragrafów umowy bazowej.
    uses_refs: bool = True
    #: Typ zakładki „Generator aneksów”: przyjmuje też umowę spoza NEXUSA
    #: (dane umowy wpisane ręcznie, bez wiersza rejestru — dokument nie jest
    #: wtedy zapisywany), a wygenerowanie aktualizuje wiersz rejestru
    #: (``annex_register``). Skutki w kontrakcie dalej dopiero po podpisie.
    allows_external: bool = False
    #: Języki, w których nowego dokumentu już się nie wystawia, ale zapisany
    #: wcześniej dokument pobiera się ponownie (szablon zostaje w repo).
    legacy_languages: tuple[str, ...] = ()

    @property
    def carries_money(self) -> bool:
        """Dokument niesie kwotę (stawkę) — widoczność jak DOCX umowy bazowej."""
        return any(f.kind in ("money", "rate_items") for f in self.fields)

    @property
    def sensitive_keys(self) -> frozenset[str]:
        return frozenset(f.key for f in self.fields if f.sensitive)

    def to_public(self) -> dict:
        data = asdict(self)
        data["fields"] = [asdict(f) for f in self.fields]
        return data


# ── wspólne klocki ───────────────────────────────────────────────────────────

_CURRENCIES = tuple((c, c) for c in ("PLN", "EUR", "USD", "GBP", "CHF"))
_START_MODES = (
    ("exact", "z dniem"),
    ("not_earlier", "nie wcześniej niż"),
    ("not_later", "nie później niż"),
)
_ENTITY = (("sole_trader", "jednoosobowa działalność (JDG)"), ("company", "spółka"))
_TERMINATION_BY_COMPANY = (
    ("project_ended", "zakończenie projektu u Klienta"),
    ("client_budget_cut", "brak budżetu po stronie Klienta"),
    ("performance_issue", "niewłaściwe wykonywanie usług"),
    ("contract_breach", "naruszenie umowy"),
    ("other", "inny powód"),
)

DOCUMENT_DATE = FieldDef(
    "document_date",
    "Data dokumentu",
    "date",
    required=True,
    help="Data w nagłówku dokumentu. Domyślnie dziś.",
)

#: Dane Partnera — prefill z umowy bazowej (payload generatora albo kolumny
#: wiersza i profil kandydata). Edytowalne, bo umowa z Excela nie ma payloadu.
PARTNER_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("gender", "Płeć Partnera", "gender", required=True, group="partner"),
    FieldDef("partner_name", "Imię i nazwisko", required=True, group="partner"),
    FieldDef(
        "partner_instrumental",
        "Imię i nazwisko — narzędnik",
        help="„z Panem/Panią …”",
        group="partner",
    ),
    FieldDef("partner_legal_name", "Nazwa firmy", group="partner"),
    FieldDef("partner_business_address", "Adres siedziby firmy", group="partner"),
    FieldDef("partner_nip", "NIP", group="partner"),
    FieldDef("partner_regon", "REGON", group="partner"),
)

#: Strona umowy zlecenie — osoba fizyczna (bez firmy). PESEL i adres nie są
#: zapisywane.
MANDATE_PARTY_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("gender", "Płeć Zleceniobiorcy", "gender", required=True, group="partner"),
    FieldDef("partner_name", "Imię i nazwisko", required=True, group="partner"),
    FieldDef("partner_instrumental", "Imię i nazwisko — narzędnik", group="partner"),
    FieldDef(
        "partner_home_address",
        "Adres zamieszkania",
        required=True,
        sensitive=True,
        group="partner",
    ),
    FieldDef("pesel", "PESEL", required=True, sensitive=True, group="partner"),
    FieldDef(
        "base_signing_date",
        "Data zawarcia umowy zlecenie",
        "date",
        required=True,
        help="Umowy zlecenie nie mają numerów — identyfikuje je data.",
        group="base",
    ),
)


# ── Generator aneksów (ticket 29.09.2026) ────────────────────────────────────

_VARIANTS = (("sole_trader", "JDG"), ("company", "spółka"))
_JDG = ("partner_variant", "sole_trader")
_COMPANY = ("partner_variant", "company")

#: Dane umowy bazowej — wymagane; z rejestru uzupełniają się same, przy
#: umowie spoza NEXUSA wpisuje je człowiek.
ANNEX_CONTRACT_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("contract_number", "Numer umowy", required=True, group="base"),
    FieldDef(
        "contract_signing_date",
        "Data zawarcia umowy",
        "date",
        required=True,
        group="base",
    ),
)

ANNEX_DATE_FIELDS: tuple[FieldDef, ...] = (
    FieldDef(
        "document_date",
        "Data sporządzenia aneksu",
        "date",
        required=True,
        help="Data w nagłówku aneksu. Domyślnie dziś.",
    ),
    FieldDef(
        "effective_date",
        "Data wejścia zmian w życie",
        "date",
        required=True,
    ),
)

ANNEX_PARAGRAPH_FIELDS: tuple[FieldDef, ...] = (
    FieldDef(
        "paragraph",
        "Zmieniany paragraf (§)",
        required=True,
        help="Numer z podpisanej umowy — podpowiadamy według jej wzoru.",
        group="change",
    ),
    FieldDef("paragraph_section", "Ustęp", required=True, group="change"),
)

#: Rejestr → pola formularza przy „Pobierz z rejestru” (Biała Lista/CEIDG/KRS).
_REGISTRY_FILLS_JDG = (
    ("name", "partner_legal_name"),
    ("address", "partner_business_address"),
    ("regon", "partner_regon"),
)
_REGISTRY_FILLS_COMPANY = (
    *_REGISTRY_FILLS_JDG,
    ("krs", "partner_krs"),
    ("seat_locative", "partner_seat_locative"),
    ("registry_court", "partner_registry_court"),
    ("share_capital", "partner_share_capital"),
)

#: Partner umowy — JDG albo spółka (komparycja z KRS, jak w umowie spółki).
ANNEX_PARTNER_FIELDS: tuple[FieldDef, ...] = (
    FieldDef(
        "partner_variant",
        "Wariant Partnera",
        "select",
        required=True,
        options=_VARIANTS,
        group="partner",
    ),
    FieldDef(
        "gender",
        "Płeć",
        "gender",
        required=True,
        help="Przy spółce — płeć osoby reprezentującej spółkę.",
        group="partner",
    ),
    FieldDef(
        "partner_name",
        "Imię i nazwisko Partnera",
        required=True,
        help="Przy spółce — osoba, której dotyczy umowa (nie trafia do komparycji).",
        group="partner",
    ),
    FieldDef(
        "partner_instrumental",
        "Imię i nazwisko — narzędnik",
        help="„z Panem/Panią …”. Puste = mianownik.",
        show_if=_JDG,
        group="partner",
    ),
    FieldDef(
        "partner_legal_name",
        "Nazwa firmy (spółki)",
        required=True,
        group="partner",
    ),
    FieldDef(
        "partner_nip",
        "NIP",
        required=True,
        group="partner",
        lookup="registry",
        lookup_fills=_REGISTRY_FILLS_JDG,
        show_if=_JDG,
    ),
    FieldDef(
        "partner_nip",
        "NIP",
        required=True,
        group="partner",
        lookup="registry",
        lookup_fills=_REGISTRY_FILLS_COMPANY,
        show_if=_COMPANY,
    ),
    FieldDef(
        "partner_business_address",
        "Adres (z CEIDG / siedziby spółki)",
        required=True,
        group="partner",
    ),
    FieldDef("partner_regon", "REGON", required=True, group="partner"),
    FieldDef(
        "partner_seat_locative",
        "Siedziba — „z siedzibą …”",
        required=True,
        help="Z przyimkiem, np. „w Warszawie”, „we Wrocławiu”.",
        show_if=_COMPANY,
        group="partner",
    ),
    FieldDef("partner_krs", "KRS", required=True, show_if=_COMPANY, group="partner"),
    FieldDef(
        "partner_registry_court",
        "Sąd rejestrowy z wydziałem",
        required=True,
        help=(
            "np. „Sąd Rejonowy dla m.st. Warszawy w Warszawie, XII Wydział "
            "Gospodarczy Krajowego Rejestru Sądowego”."
        ),
        show_if=_COMPANY,
        group="partner",
    ),
    FieldDef(
        "partner_share_capital",
        "Kapitał zakładowy",
        required=True,
        help="np. „5 000,00 zł”.",
        show_if=_COMPANY,
        group="partner",
    ),
    FieldDef(
        "partner_representative_name",
        "Osoba reprezentująca — imię i nazwisko",
        required=True,
        show_if=_COMPANY,
        group="partner",
    ),
    FieldDef(
        "partner_representative_function",
        "Funkcja osoby reprezentującej",
        required=True,
        help="np. „Prezes Zarządu”.",
        show_if=_COMPANY,
        group="partner",
    ),
    FieldDef(
        "partner_representation",
        "„reprezentowaną przez …” (biernik)",
        help="Puste = „Pana/Panią <imię i nazwisko> – <funkcja>”.",
        show_if=_COMPANY,
        group="partner",
    ),
)

ANNEX_GENERATOR_TYPES: tuple[DocumentType, ...] = (
    DocumentType(
        key="annex_party_data",
        label="Aneks — uzupełnienie danych firmy",
        family="annex",
        languages=("pl",),
        # Wersja EN sprzed generatora aneksów — tylko ponowne pobranie.
        legacy_languages=("en",),
        parent="b2b",
        uses_refs=False,
        allows_external=True,
        description=(
            "Umowa zawarta z osobą fizyczną przed założeniem działalności: "
            "od aneksu Partnerem jest jej JDG."
        ),
        effect_label=(
            "Dane firmy trafią do profilu kandydata; pozycja zniknie z kolejki "
            "„Aneks uzupełnienia danych”. Wiersz rejestru (firma, NIP) "
            "zmienia się już przy wygenerowaniu."
        ),
        fields=(
            *ANNEX_CONTRACT_FIELDS,
            *ANNEX_DATE_FIELDS,
            FieldDef(
                "gender", "Płeć Partnera", "gender", required=True, group="partner"
            ),
            FieldDef("partner_name", "Imię i nazwisko", required=True, group="partner"),
            FieldDef(
                "partner_instrumental",
                "Imię i nazwisko — narzędnik",
                help="„z Panem/Panią …”. Puste = mianownik.",
                group="partner",
            ),
            FieldDef(
                "partner_home_address",
                "Adres zamieszkania",
                required=True,
                sensitive=True,
                group="partner",
            ),
            FieldDef(
                "id_document",
                "Numer dowodu osobistego",
                required=True,
                sensitive=True,
                group="partner",
            ),
            FieldDef(
                "new_nip",
                "NIP działalności",
                required=True,
                help="„Pobierz z CEIDG” uzupełni nazwę, adres i REGON.",
                group="change",
                lookup="registry",
                lookup_fills=(
                    ("name", "new_legal_name"),
                    ("address", "new_business_address"),
                    ("regon", "new_regon"),
                ),
            ),
            FieldDef("new_legal_name", "Nazwa firmy", required=True, group="change"),
            FieldDef(
                "new_business_address",
                "Adres działalności (CEIDG)",
                required=True,
                group="change",
            ),
            FieldDef("new_regon", "REGON", required=True, group="change"),
        ),
    ),
    DocumentType(
        key="annex_start_date",
        label="Aneks — zmiana daty startu",
        family="annex",
        languages=("pl",),
        parent="b2b",
        uses_refs=False,
        allows_external=True,
        description="Przesunięcie daty rozpoczęcia świadczenia usług.",
        effect_label=(
            "Kontrakt dostanie nową datę rozpoczęcia. Data w rejestrze umów "
            "zmienia się już przy wygenerowaniu."
        ),
        fields=(
            *ANNEX_CONTRACT_FIELDS,
            *ANNEX_DATE_FIELDS,
            *ANNEX_PARTNER_FIELDS,
            *ANNEX_PARAGRAPH_FIELDS,
            FieldDef(
                "current_start_date",
                "Obecna data rozpoczęcia usług",
                "date",
                required=True,
                group="change",
            ),
            FieldDef(
                "new_start_date",
                "Nowa data rozpoczęcia usług",
                "date",
                required=True,
                group="change",
            ),
        ),
    ),
    DocumentType(
        key="annex_rate_change",
        label="Aneks — zmiana stawki",
        family="annex",
        languages=("pl",),
        legacy_languages=("en",),
        parent="b2b",
        uses_refs=False,
        allows_external=True,
        description=(
            "Nowe wynagrodzenie godzinowe: jedna stawka, stawka progresywna "
            "albo różne stawki dla różnych klientów."
        ),
        effect_label=(
            "Stawki wejdą do harmonogramu stawek kontraktu (aneks w zakładce "
            "„Aneksy”). Stawka w rejestrze umów zmienia się już przy "
            "wygenerowaniu."
        ),
        fields=(
            *ANNEX_CONTRACT_FIELDS,
            *ANNEX_DATE_FIELDS,
            *ANNEX_PARTNER_FIELDS,
            *ANNEX_PARAGRAPH_FIELDS,
            FieldDef(
                "rate_items",
                "Stawki",
                "rate_items",
                required=True,
                help=(
                    "Jedna pozycja = jedna stawka. Kilka pozycji: stawka "
                    "progresywna (daty „od”) albo różne stawki dla klientów."
                ),
                group="change",
            ),
        ),
    ),
)


def _non_compete_fields() -> tuple[FieldDef, ...]:
    return (
        FieldDef(
            "release_non_compete",
            "Zwolnienie z zakazu konkurencji",
            "bool",
            help="Partner może świadczyć usługi na rzecz Klienta bez B2B.net.",
        ),
        FieldDef(
            "non_compete_client_name",
            "Klient, którego dotyczy zwolnienie",
            required=True,
            help="Pełna nazwa (z formą prawną). Obejmuje też spółki powiązane.",
            show_if=("release_non_compete", True),
        ),
    )


TYPES: dict[str, DocumentType] = {
    t.key: t
    for t in (
        *ANNEX_GENERATOR_TYPES,
        DocumentType(
            key="annex_subcontractor",
            label="Aneks — osoba skierowana (oddelegowanie)",
            family="annex",
            languages=("pl",),
            parent="b2b",
            description=(
                "Zgoda B2B.net na świadczenie usług przez osobę wskazaną przez "
                "Partnera (§ 2a „Osoby skierowane do realizacji usług”)."
            ),
            effect_label="W historii kontraktu pojawi się aneks „Osoba skierowana”.",
            fields=(
                DOCUMENT_DATE,
                *PARTNER_FIELDS,
                FieldDef(
                    "delegate_gender", "Płeć osoby skierowanej", "gender", required=True
                ),
                FieldDef(
                    "delegate_name", "Imię i nazwisko osoby skierowanej", required=True
                ),
                FieldDef(
                    "delegate_email", "E-mail osoby skierowanej", "email", required=True
                ),
                FieldDef("effective_date", "Obowiązuje od", "date", required=True),
            ),
        ),
        DocumentType(
            key="annex_mandate",
            label="Aneks do umowy zlecenie",
            family="annex",
            languages=("pl",),
            parent="mandate",
            uses_refs=False,
            description="Zmiana okresu zlecenia, stawki brutto albo dodatkowe postanowienia.",
            effect_label="W historii kontraktu zlecenie pojawi się aneks (gdy jest powiązany).",
            fields=(
                DOCUMENT_DATE,
                *MANDATE_PARTY_FIELDS,
                FieldDef("change_period", "Zmiana okresu zlecenia", "bool"),
                FieldDef(
                    "period_from",
                    "Zlecenie od",
                    "date",
                    required=True,
                    show_if=("change_period", True),
                ),
                FieldDef(
                    "period_to",
                    "Zlecenie do",
                    "date",
                    required=True,
                    show_if=("change_period", True),
                ),
                FieldDef("change_rate", "Zmiana stawki", "bool"),
                FieldDef(
                    "gross_hourly_rate",
                    "Stawka brutto za godzinę",
                    "money",
                    required=True,
                    show_if=("change_rate", True),
                ),
                FieldDef(
                    "extra_provisions",
                    "Dodatkowe postanowienia",
                    "textarea",
                    help="Każdy akapit to osobny ustęp.",
                ),
                FieldDef(
                    "effective_date", "Aneks obowiązuje od", "date", required=True
                ),
            ),
        ),
        DocumentType(
            key="termination_agreement",
            label="Porozumienie o rozwiązaniu umowy",
            family="termination",
            languages=("pl", "en"),
            parent="b2b",
            description="Rozwiązanie umowy B2B za porozumieniem stron.",
            effect_label=(
                "Kontrakt dostanie datę zakończenia (ostatni dzień świadczenia "
                "usług, powód: porozumienie stron), zamówienia zostaną "
                "domknięte, umowa w rejestrze — „Zakończona” z dniem "
                "rozwiązania umowy."
            ),
            fields=(
                DOCUMENT_DATE,
                *PARTNER_FIELDS,
                FieldDef(
                    "termination_date",
                    "Umowa ulega rozwiązaniu z dniem",
                    "date",
                    required=True,
                ),
                FieldDef(
                    "last_service_date",
                    "Ostatni dzień świadczenia usług",
                    "date",
                    required=True,
                    help="Zwykle ta sama data co rozwiązanie umowy.",
                ),
                *_non_compete_fields(),
            ),
        ),
        DocumentType(
            key="termination_agreement_mandate",
            label="Porozumienie o rozwiązaniu umowy zlecenie",
            family="termination",
            languages=("pl",),
            parent="mandate",
            uses_refs=False,
            description="Rozwiązanie umowy zlecenie za porozumieniem stron.",
            effect_label="Kontrakt zlecenie (gdy powiązany) dostanie datę zakończenia.",
            fields=(
                DOCUMENT_DATE,
                *MANDATE_PARTY_FIELDS,
                FieldDef(
                    "termination_date",
                    "Umowa ulega rozwiązaniu z dniem",
                    "date",
                    required=True,
                ),
                *_non_compete_fields(),
            ),
        ),
        DocumentType(
            key="termination_notice",
            label="Wypowiedzenie umowy (przez B2B.net)",
            family="termination",
            languages=("pl",),
            parent="b2b",
            signatories="company",
            description=(
                "Jednostronne wypowiedzenie umowy B2B przez B2B.net z zachowaniem "
                "okresu wypowiedzenia z umowy."
            ),
            effect_label=(
                "Kontrakt dostanie datę zakończenia po okresie wypowiedzenia, "
                "umowa w rejestrze — „Zakończona” z tą datą."
            ),
            fields=(
                DOCUMENT_DATE,
                *PARTNER_FIELDS,
                FieldDef(
                    "delivery_date",
                    "Data doręczenia wypowiedzenia",
                    "date",
                    required=True,
                    help="Od niej liczy się okres wypowiedzenia.",
                ),
                FieldDef(
                    "termination_date",
                    "Umowa rozwiąże się z dniem",
                    "date",
                    required=True,
                    help="Wyliczone z okresu wypowiedzenia — możesz poprawić.",
                ),
                FieldDef(
                    "termination_reason",
                    "Powód (do analityki, nie do dokumentu)",
                    "select",
                    required=True,
                    options=_TERMINATION_BY_COMPANY,
                ),
            ),
        ),
        DocumentType(
            key="notice_withdrawal",
            label="Cofnięcie wypowiedzenia (przez Partnera)",
            family="termination",
            languages=("pl",),
            parent="b2b",
            signatories="partner_and_company",
            description=(
                "Partner cofa złożone wypowiedzenie; B2B.net wyraża zgodę pod "
                "oświadczeniem."
            ),
            # Runda 10 (R10-N14-6): podpis kontraktu NIE rusza (`effects.apply`)
            # — pełne cofnięcie z zamówieniami robi „Cofnij zakończenie”.
            effect_label=(
                "Umowa w rejestrze wróci na „Aktywna”. Kontraktu podpis nie "
                "zmienia — przywróć go przyciskiem „Cofnij zakończenie” "
                "w module Kontrakty."
            ),
            fields=(
                DOCUMENT_DATE,
                *PARTNER_FIELDS,
                FieldDef(
                    "notice_delivery_date",
                    "Data złożenia wypowiedzenia przez Partnera",
                    "date",
                    required=True,
                ),
            ),
        ),
        DocumentType(
            key="preliminary_cez",
            label="Umowa przedwstępna — Centrum e-Zdrowia",
            family="preliminary",
            languages=("pl",),
            parent="none",
            uses_refs=False,
            signatories="partner_and_company",
            description=(
                "Umowa przedwstępna z kandydatem przed rozstrzygnięciem "
                "rekrutacji w Centrum e-Zdrowia (wyłączność na kandydaturę, "
                "warunki umowy przyrzeczonej)."
            ),
            effect_label=(
                "Brak zmian w kontraktach. Umowa wygaśnie po terminie albo "
                "zostanie zrealizowana, gdy powstanie umowa B2B."
            ),
            fields=(
                DOCUMENT_DATE,
                FieldDef(
                    "gender", "Płeć kandydata", "gender", required=True, group="partner"
                ),
                FieldDef(
                    "partner_name", "Imię i nazwisko", required=True, group="partner"
                ),
                FieldDef(
                    "partner_instrumental",
                    "Imię i nazwisko — narzędnik",
                    group="partner",
                ),
                FieldDef(
                    "partner_home_address",
                    "Adres zamieszkania",
                    required=True,
                    sensitive=True,
                    group="partner",
                ),
                FieldDef(
                    "id_document",
                    "Seria i numer dowodu osobistego",
                    required=True,
                    sensitive=True,
                    group="partner",
                ),
                FieldDef(
                    "id_document_issuer",
                    "Dowód wydany przez",
                    sensitive=True,
                    group="partner",
                ),
                FieldDef(
                    "pesel", "PESEL", required=True, sensitive=True, group="partner"
                ),
                FieldDef("project_number", "Numer projektu CeZ", required=True),
                FieldDef(
                    "hourly_rate",
                    "Stawka godzinowa netto w umowie przyrzeczonej",
                    "money",
                    required=True,
                ),
                FieldDef(
                    "valid_until",
                    "Umowa obowiązuje do",
                    "date",
                    required=True,
                    help="Domyślnie 60 dni od daty zawarcia.",
                ),
            ),
        ),
    )
}

#: Grupa pól numerów paragrafów — formularz pokazuje ją tylko, gdy wersja wzoru
#: umowy bazowej jest nieznana (``needs_refs`` w prefillu).
REF_LABELS: dict[str, str] = {
    "rate_paragraph": "Paragraf wynagrodzenia",
    "start_paragraph": "Paragraf daty rozpoczęcia",
    "appendix_start": "Załącznik z datą rozpoczęcia",
    "non_compete_paragraph": "Paragraf zakazu konkurencji",
    "notice_paragraph": "Paragraf wypowiedzenia",
    "notice_period_pl": "Okres wypowiedzenia",
    "notice_period_en": "Okres wypowiedzenia (EN)",
    "ip_paragraph": "Paragraf praw autorskich",
    "personal_data_paragraph": "Paragraf danych osobowych",
    "confidentiality_paragraph": "Paragraf poufności",
}


def get_type(key: str) -> DocumentType | None:
    return TYPES.get(key)


def strip_sensitive(doc_type: DocumentType, values: dict) -> dict:
    """Kopia wartości formularza bez pól wrażliwych — to trafia do bazy."""
    hidden = doc_type.sensitive_keys
    return {k: v for k, v in values.items() if k not in hidden}


def visible(field_def: FieldDef, values: dict) -> bool:
    if field_def.show_if is None:
        return True
    key, expected = field_def.show_if
    return values.get(key) == expected


def missing_required(doc_type: DocumentType, values: dict) -> list[str]:
    """Etykiety wymaganych pól bez wartości (tylko pól aktualnie widocznych)."""
    missing: list[str] = []
    for f in doc_type.fields:
        if not f.required or not visible(f, values):
            continue
        value = values.get(f.key)
        if (
            value is None
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, list) and not value)
        ):
            missing.append(f.label)
    return missing


#: Górna granica kwoty w dokumencie (wszystkie kwoty to stawki godzinowe).
#: Runda 10 (R10-N14-5): literówka „1 500 000” kończyła się 500 w słowniku
#: liczb; teraz 422 z czytelnym zdaniem, zanim cokolwiek się wyrenderuje.
MONEY_MAX = 1_000_000


def _iso_day(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


#: Najwięcej pozycji stawki w jednym aneksie (lustro formularza).
MAX_RATE_ITEMS = 10


def parse_amount(raw: object) -> float | None:
    """„1 234,50” / 150 → liczba; ``None`` = puste albo nieczytelne."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).replace(",", ".").replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def rate_items_problems(items: object) -> list[str]:
    """Zdania o pozycjach stawki, których aneks nie przyjmie.

    Kilka pozycji musi się czymś różnić — każda poza jedną potrzebuje daty
    „od” albo klienta; inaczej aneks mówiłby dwie różne stawki za tę samą
    godzinę."""
    if not isinstance(items, list) or not items:
        return []
    problems: list[str] = []
    if len(items) > MAX_RATE_ITEMS:
        problems.append(f"Aneks mieści najwyżej {MAX_RATE_ITEMS} pozycji stawki.")
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            problems.append(f"Pozycja stawki {number} jest nieczytelna.")
            continue
        amount = parse_amount(item.get("rate"))
        if amount is None:
            problems.append(f"Pozycja stawki {number}: podaj stawkę netto za godzinę.")
        elif not (0 < amount < MONEY_MAX):
            problems.append(
                f"Pozycja stawki {number}: stawka musi być większa od zera "
                "i mniejsza niż 1 000 000."
            )
        start = _iso_day(item.get("from"))
        end = _iso_day(item.get("to"))
        if item.get("from") and start is None:
            problems.append(f"Pozycja stawki {number}: nieczytelna data „od”.")
        if item.get("to") and end is None:
            problems.append(f"Pozycja stawki {number}: nieczytelna data „do”.")
        if start and end and end < start:
            problems.append(
                f"Pozycja stawki {number}: data „do” jest wcześniejsza niż „od”."
            )
    if len(items) > 1:
        loose = [
            n
            for n, item in enumerate(items, start=1)
            if isinstance(item, dict)
            and not item.get("from")
            and not item.get("client_id")
        ]
        if len(loose) > 1:
            problems.append(
                "Przy kilku stawkach każda (poza jedną) potrzebuje daty „od” albo "
                "klienta — inaczej nie wiadomo, kiedy która obowiązuje."
            )
    return problems


def invalid_values(doc_type: DocumentType, values: dict) -> list[str]:
    """Zdania o wartościach, których dokument nie przyjmie (poza brakami)."""
    problems: list[str] = []
    for f in doc_type.fields:
        if f.kind == "rate_items" and visible(f, values):
            problems.extend(rate_items_problems(values.get(f.key)))
    for f in doc_type.fields:
        if f.kind != "money" or not visible(f, values):
            continue
        raw = values.get(f.key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        try:
            amount = float(str(raw).replace(",", ".").replace(" ", ""))
        except ValueError:
            problems.append(f"„{f.label}” musi być kwotą.")
            continue
        if not (0 < amount < MONEY_MAX):
            problems.append(
                f"„{f.label}” musi być większa od zera i mniejsza niż 1 000 000."
            )
    # Runda 10 (R10-N14-2): ostatni dzień usług nie może wypaść po rozwiązaniu
    # umowy — koniec projektu trafia do kontraktu, rozwiązanie do rejestru.
    keys = {f.key for f in doc_type.fields}
    if {"termination_date", "last_service_date"} <= keys:
        ends = _iso_day(values.get("termination_date"))
        last = _iso_day(values.get("last_service_date"))
        if ends is not None and last is not None and last > ends:
            problems.append(
                "Ostatni dzień świadczenia usług nie może być późniejszy niż "
                "dzień rozwiązania umowy."
            )
    return problems


__all__ = [
    "DocumentType",
    "MAX_RATE_ITEMS",
    "MONEY_MAX",
    "invalid_values",
    "parse_amount",
    "rate_items_problems",
    "FieldDef",
    "REF_LABELS",
    "TYPES",
    "get_type",
    "missing_required",
    "strip_sensitive",
    "visible",
]
