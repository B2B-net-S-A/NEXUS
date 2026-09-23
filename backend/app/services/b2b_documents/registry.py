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
from typing import Literal

FieldKind = Literal[
    "text", "textarea", "date", "money", "bool", "select", "email", "gender"
]


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
    group: str = "document"


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
        DocumentType(
            key="annex_rate_change",
            label="Aneks — zmiana stawki",
            family="annex",
            languages=("pl", "en"),
            parent="b2b",
            description="Zmiana wynagrodzenia godzinowego Partnera.",
            effect_label=(
                "Nowa stawka wejdzie do harmonogramu stawek kontraktu od dnia "
                "wejścia w życie (aneks w zakładce „Aneksy”)."
            ),
            fields=(
                DOCUMENT_DATE,
                *PARTNER_FIELDS,
                FieldDef(
                    "effective_date",
                    "Nowa stawka obowiązuje od",
                    "date",
                    required=True,
                ),
                FieldDef(
                    "new_rate", "Nowa stawka godzinowa netto", "money", required=True
                ),
                FieldDef(
                    "currency", "Waluta", "select", required=True, options=_CURRENCIES
                ),
            ),
        ),
        DocumentType(
            key="annex_start_date",
            label="Aneks — zmiana daty rozpoczęcia",
            family="annex",
            languages=("pl",),
            parent="b2b",
            description="Przesunięcie daty rozpoczęcia świadczenia usług.",
            effect_label="Kontrakt i umowa w rejestrze dostaną nową datę rozpoczęcia.",
            fields=(
                DOCUMENT_DATE,
                *PARTNER_FIELDS,
                FieldDef(
                    "new_start_date",
                    "Nowa data rozpoczęcia usług",
                    "date",
                    required=True,
                ),
                FieldDef(
                    "new_start_date_mode",
                    "Tryb daty",
                    "select",
                    required=True,
                    options=_START_MODES,
                ),
            ),
        ),
        DocumentType(
            key="annex_party_data",
            label="Aneks — uzupełnienie danych firmy",
            family="annex",
            languages=("pl", "en"),
            parent="b2b",
            description=(
                "Umowa zawarta przed założeniem działalności: od dnia aneksu "
                "Partnerem jest firma (JDG albo spółka)."
            ),
            effect_label=(
                "Dane firmy trafią do profilu kandydata i do rejestru umów; "
                "pozycja zniknie z kolejki „Aneks uzupełnienia danych”."
            ),
            fields=(
                DOCUMENT_DATE,
                FieldDef(
                    "gender", "Płeć Partnera", "gender", required=True, group="partner"
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
                    sensitive=True,
                    group="partner",
                ),
                FieldDef(
                    "entity_type",
                    "Forma działalności",
                    "select",
                    required=True,
                    options=_ENTITY,
                ),
                FieldDef("new_legal_name", "Nazwa firmy", required=True),
                FieldDef("new_business_address", "Adres siedziby", required=True),
                FieldDef(
                    "new_nip", "NIP", required=True, help="Uzupełnia się z rejestru."
                ),
                FieldDef("new_regon", "REGON", required=True),
                FieldDef(
                    "company_krs",
                    "KRS",
                    show_if=("entity_type", "company"),
                    required=True,
                ),
                FieldDef(
                    "company_representative",
                    "Reprezentant spółki",
                    show_if=("entity_type", "company"),
                    required=True,
                ),
                FieldDef(
                    "effective_date", "Zmiana obowiązuje od", "date", required=True
                ),
            ),
        ),
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
                "Kontrakt dostanie datę zakończenia (powód: porozumienie stron), "
                "zamówienia zostaną domknięte, umowa w rejestrze — „Zakończona”."
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
            effect_label=(
                "Kontrakt wróci do aktywnych (bez daty zakończenia), umowa "
                "w rejestrze — „Aktywna”."
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
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(f.label)
    return missing


__all__ = [
    "DocumentType",
    "FieldDef",
    "REF_LABELS",
    "TYPES",
    "get_type",
    "missing_required",
    "strip_sensitive",
    "visible",
]
