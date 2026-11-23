"""Kto dostanie nową umowę i z jakimi danymi (E5b) — czyste reguły, bez bazy.

Jedna osoba = jeden aktywny kontrakt B2B (``contracts.status = active``,
``contract_type = b2b``). Dane umowy biorą się z ostatniego podpisanego wiersza
Generatora tej osoby albo kontraktu (``render_payload``), a bez niego z danych
firmy potwierdzonych na „Dane firm z umów” (E5a, ``confirmed``) i z kontraktu.

Treści umowy nie zgadujemy (decyzja Artura 22.11.2026): czego brakuje do
formularza Generatora, to pole w ``missing`` i pozycja „Do sprawdzenia”;
co mogło się zmienić od ostatniej umowy (aneks, inna stawka w kontrakcie,
inny klient), to uwaga w ``issues`` i też „Do sprawdzenia”. Listę pól
i etykiety bierzemy z formularza Generatora (``lib/b2b-generator-wizard.ts``,
``b2bFormMissing``), żeby człowiek widział te same nazwy w obu miejscach.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, Mapping, Optional, Sequence

#: Ile dni przed końcem umowy osoba nie dostaje nowej (okno wysyłki).
ENDING_WITHIN_DAYS = 30
#: Doba robocza w umowie dziennej (rejestr Generatora: 68 zł/h = 544 zł/dzień).
HOURS_PER_DAY = 8

Status = Literal["ready", "needs_review", "skipped"]

REASON_ENDING = "ending_soon"
REASON_OPEN_REQUEST = "open_request"
REASON_IN_BATCH = "in_batch"
REASON_NO_PARTNER_DATA = "no_partner_data"
REASON_NO_EMAIL = "no_email"
REASON_SEVERAL_CONTRACTS = "several_contracts"
REASON_MISSING = "missing_data"

#: Powody pominięcia i sprawdzenia — w tej kolejności rozstrzyga ``assess``.
REASON_LABELS: dict[str, str] = {
    REASON_ENDING: "Umowa kończy się w ciągu 30 dni",
    REASON_OPEN_REQUEST: "Umowa tej osoby czeka już na podpis w NEXUSIE",
    REASON_IN_BATCH: "Osoba jest już w masowej wysyłce",
    REASON_NO_PARTNER_DATA: "Brak danych firmy Partnera",
    REASON_NO_EMAIL: "Brak adresu e-mail",
    REASON_SEVERAL_CONTRACTS: "Osoba ma kilka aktywnych kontraktów B2B",
    REASON_MISSING: "Brakuje danych do umowy",
}

ISSUE_RATE_DIFFERS = "Stawka w ostatniej umowie różni się od stawki w kontrakcie."
ISSUE_RATE_UNIT = "Kontrakt ma stawkę miesięczną: sprawdź stawkę godzinową w umowie."
ISSUE_CURRENCY = "Waluta ostatniej umowy różni się od waluty kontraktu."
ISSUE_PROGRESSIVE = "Ostatnia umowa ma stawkę progresywną: sprawdź etapy."
ISSUE_ANNEX = "Do ostatniej umowy jest aneks: dane mogły się zmienić."
ISSUE_DATA_ANNEX = "Ostatnia umowa czeka na aneks uzupełnienia danych firmy."
ISSUE_OTHER_CLIENT = "Ostatnia umowa dotyczy innego klienta niż kontrakt."
ISSUE_PENDING_DRAFT = "W rejestrze czeka niepodpisana umowa tej osoby."
ISSUE_ROLE_GONE = "Obszaru usług z ostatniej umowy nie ma już w katalogu."

#: Pola firmy Partnera, które masowa wysyłka bierze z ``confirmed`` (E5a).
CONFIRMED_FIELDS: tuple[str, ...] = (
    "gender",
    "partner_name",
    "partner_legal_name",
    "partner_entity_type",
    "partner_nip",
    "partner_regon",
    "partner_business_address",
    "partner_correspondence_address",
    "partner_email",
    "partner_phone",
    "partner_krs",
    "partner_seat",
    "partner_registry_court",
    "partner_share_capital",
    "partner_representative_name",
    "partner_representative_function",
    "partner_representation",
)

#: Metadane wydania starej umowy — nowa dostaje własne przy ``/render``.
_ISSUE_METADATA = ("_clause_override", "_notices_email")


@dataclass(frozen=True)
class Person:
    """Aktywny kontrakt B2B jednej osoby — fakty z kontraktu i profilu."""

    contract_id: int
    candidate_id: int
    candidate_name: str
    client_id: Optional[int]
    client_name: str
    job_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    agreement_last_day: Optional[date] = None
    rate: Optional[Decimal] = None
    rate_unit: Optional[str] = None
    currency: Optional[str] = None
    is_replacement: Optional[bool] = None
    replaced_contract_id: Optional[int] = None
    fte: Optional[Decimal] = None
    is_client_referral: Optional[bool] = None
    candidate_email: Optional[str] = None
    active_b2b_contracts: int = 1


@dataclass(frozen=True)
class Source:
    """Ostatni podpisany wiersz Generatora tej osoby albo kontraktu."""

    id: int
    payload: Mapping[str, Any]
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    created_by: Optional[int] = None
    needs_business_data_annex: bool = False
    has_annex: bool = False


@dataclass(frozen=True)
class Assessment:
    status: Status
    reason: Optional[str] = None
    missing: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    payload: Optional[dict[str, Any]] = None
    contractor_email: Optional[str] = None
    source_id: Optional[int] = None
    data_source: Optional[Literal["generator", "confirmed"]] = None
    extra: dict[str, Any] = field(default_factory=dict)


def effective_end(person: Person) -> Optional[date]:
    """Koniec umowy: data końca kontraktu albo ostatni dzień po wypowiedzeniu."""
    days = [d for d in (person.end_date, person.agreement_last_day) if d is not None]
    return min(days) if days else None


def ends_soon(person: Person, today: date) -> bool:
    end = effective_end(person)
    return end is not None and end <= today + timedelta(days=ENDING_WITHIN_DAYS)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _single_rate(payload: Mapping[str, Any]) -> Optional[float]:
    stages = payload.get("rate_stages") or []
    if isinstance(stages, list) and len(stages) == 1:
        rate = (stages[0] or {}).get("rate")
        if isinstance(rate, (int, float)):
            return float(rate)
    rate = payload.get("rate_candidate")
    return float(rate) if isinstance(rate, (int, float)) else None


def missing_fields(payload: Mapping[str, Any]) -> list[str]:
    """Braki formularza Generatora — te same etykiety co ``b2bFormMissing``."""
    out: list[str] = []

    def need(ok: bool, label: str) -> None:
        if not ok:
            out.append(label)

    need(payload.get("job_id") is not None, "Rekrutacja")
    # Płeć steruje formami w komparycji; formularz ma ją zawsze, odczyt z umowy
    # (E5a) nie zawsze — domyślnego „m” nie zakładamy.
    need(_text(payload.get("gender")).lower() in ("m", "k", "f"), "Forma w umowie")
    need(
        payload.get("role_id") is not None or bool(payload.get("scope_items_override")),
        "Obszar usług",
    )
    is_company = payload.get("contract_variant") == "company"
    if is_company:
        for key, label in (
            ("partner_krs", "KRS"),
            ("partner_seat_locative", "Siedziba spółki"),
            ("partner_registry_court", "Sąd rejestrowy i wydział"),
            ("partner_share_capital", "Kapitał zakładowy"),
            ("partner_representative_name", "Osoba reprezentująca spółkę"),
            ("partner_representative_function", "Funkcja osoby reprezentującej"),
            ("partner_representation", "Reprezentacja w komparycji"),
        ):
            need(bool(_text(payload.get(key))), label)
    else:
        need(bool(_text(payload.get("partner_name"))), "Imię i nazwisko Partnera")
        need(
            bool(_text(payload.get("partner_instrumental"))),
            "Imię i nazwisko (narzędnik)",
        )
    need(bool(_text(payload.get("partner_legal_name"))), "Nazwa Firmy")
    need(bool(_text(payload.get("partner_nip"))), "NIP")
    need(bool(_text(payload.get("partner_regon"))), "REGON")
    need(
        bool(_text(payload.get("partner_business_address"))),
        "Adres siedziby firmy" if is_company else "Adres z CEIDG",
    )
    need(bool(_text(payload.get("partner_email"))), "E-mail")
    need(bool(_text(payload.get("partner_phone"))), "Telefon")
    need(bool(_text(payload.get("client_name"))), "Pełna nazwa Klienta")
    need(bool(_text(payload.get("project_city"))), "Miasto Klienta")
    need(bool(_text(payload.get("project_description"))), "Opis projektu")
    need(bool(payload.get("start_date")), "Data rozpoczęcia")
    stages = payload.get("rate_stages") or []
    if isinstance(stages, list) and len(stages) > 1:
        for index, stage in enumerate(stages, start=1):
            rate = (stage or {}).get("rate")
            need(
                isinstance(rate, (int, float)) and rate > 0,
                f"Stawka godzinowa (etap {index})",
            )
    else:
        rate = _single_rate(payload)
        need(rate is not None and rate > 0, "Stawka godzinowa")
    if payload.get("job_id") is not None:
        need(payload.get("is_replacement") is not None, "Replacement")
        need(payload.get("fte") is not None, "Wymiar FTE")
        if payload.get("is_replacement") is True:
            need(payload.get("replaced_contract_id") is not None, "Replacement za kogo")
    return out


def _rate_issues(payload: Mapping[str, Any], person: Person) -> list[str]:
    stages = payload.get("rate_stages") or []
    if isinstance(stages, list) and len(stages) > 1:
        return [ISSUE_PROGRESSIVE]
    rate = _single_rate(payload)
    if rate is None or person.rate is None:
        return []
    issues: list[str] = []
    currency = _text(payload.get("currency")) or "PLN"
    if person.currency and person.currency.upper() != currency.upper():
        issues.append(ISSUE_CURRENCY)
    contract_rate = float(person.rate)
    if person.rate_unit == "hourly":
        expected = rate
    elif person.rate_unit == "daily":
        expected = rate * HOURS_PER_DAY
    else:
        return [*issues, ISSUE_RATE_UNIT]
    if abs(expected - contract_rate) > 0.005:
        issues.append(ISSUE_RATE_DIFFERS)
    return issues


def _from_source(source: Source, person: Person) -> dict[str, Any]:
    payload = copy.deepcopy(dict(source.payload))
    for key in _ISSUE_METADATA:
        payload.pop(key, None)
    if payload.get("job_id") is None and person.job_id is not None:
        payload["job_id"] = person.job_id
    return payload


def _from_confirmed(confirmed: Mapping[str, Any], person: Person) -> dict[str, Any]:
    """Dane firmy potwierdzone przez człowieka + to, co kontrakt mówi wprost.

    Nazwy Klienta, miasta, opisu projektu i obszaru usług kontrakt nie zna —
    zostają puste i pozycja idzie do sprawdzenia. Stawkę bierzemy tylko
    godzinową w PLN."""
    values = confirmed.get("fields") or {}
    payload: dict[str, Any] = {
        name: values.get(name) for name in CONFIRMED_FIELDS if values.get(name)
    }
    variant = confirmed.get("contract_variant")
    if variant in ("jdg", "company"):
        payload["contract_variant"] = variant
    payload["job_id"] = person.job_id
    # Nazwy Klienta nie składamy z kartoteki: po niej rejestr klauzul wybiera
    # klauzule klienta (``resolve_override``), więc inna pisownia dałaby umowę
    # bez nich. Zostaje pusta — pozycja i tak idzie do sprawdzenia.
    payload["start_date"] = person.start_date.isoformat() if person.start_date else None
    if (
        person.rate is not None
        and person.rate_unit == "hourly"
        and (person.currency or "PLN").upper() == "PLN"
    ):
        payload["rate_candidate"] = float(person.rate)
        payload["currency"] = "PLN"
    payload["is_replacement"] = person.is_replacement
    payload["replaced_contract_id"] = person.replaced_contract_id
    payload["fte"] = str(person.fte) if person.fte is not None else None
    payload["is_client_referral"] = person.is_client_referral
    return payload


def assess(
    person: Person,
    *,
    today: date,
    skip_ending: bool,
    source: Optional[Source] = None,
    confirmed: Optional[Mapping[str, Any]] = None,
    open_request: bool = False,
    live_batch_id: Optional[int] = None,
    pending_draft: bool = False,
    known_role_ids: Optional[frozenset[int]] = None,
) -> Assessment:
    """Gotowa / do sprawdzenia / pominięta — z powodem i brakami.

    Kolejność powodów jest stała: koniec umowy (gdy pomijamy), wniosek
    o podpis w toku, inna masowa wysyłka, brak danych firmy, brak e-maila,
    kilka kontraktów, braki i uwagi."""
    if skip_ending and ends_soon(person, today):
        return Assessment(status="skipped", reason=REASON_ENDING)
    if open_request:
        return Assessment(status="skipped", reason=REASON_OPEN_REQUEST)
    if live_batch_id is not None:
        return Assessment(
            status="skipped", reason=REASON_IN_BATCH, extra={"batch_id": live_batch_id}
        )
    if source is not None:
        payload = _from_source(source, person)
        data_source: Literal["generator", "confirmed"] = "generator"
    elif confirmed:
        payload = _from_confirmed(confirmed, person)
        data_source = "confirmed"
    else:
        return Assessment(status="skipped", reason=REASON_NO_PARTNER_DATA)
    # Adres jak w oknie „Wyślij do podpisu”: e-mail z umowy, potem z profilu.
    email = _text(payload.get("partner_email")) or _text(person.candidate_email)
    payload["candidate_id"] = person.candidate_id
    payload["contract_number"] = None
    payload["signing_date"] = today.isoformat()
    common = {
        "payload": payload,
        "contractor_email": email or None,
        "source_id": source.id if source else None,
        "data_source": data_source,
    }
    if not email:
        return Assessment(
            status="skipped",
            reason=REASON_NO_EMAIL,
            missing=tuple(missing_fields(payload)),
            **common,
        )
    if person.active_b2b_contracts > 1:
        return Assessment(
            status="needs_review", reason=REASON_SEVERAL_CONTRACTS, **common
        )
    missing = missing_fields(payload)
    issues: list[str] = []
    role_id = payload.get("role_id")
    if (
        known_role_ids is not None
        and role_id is not None
        and role_id not in known_role_ids
    ):
        issues.append(ISSUE_ROLE_GONE)
    if source is not None:
        issues += _rate_issues(payload, person)
        if source.has_annex:
            issues.append(ISSUE_ANNEX)
        if source.needs_business_data_annex:
            issues.append(ISSUE_DATA_ANNEX)
        if source.client_id is not None and source.client_id != person.client_id:
            issues.append(ISSUE_OTHER_CLIENT)
    if pending_draft:
        issues.append(ISSUE_PENDING_DRAFT)
    if missing or issues:
        return Assessment(
            status="needs_review",
            reason=REASON_MISSING,
            missing=tuple(missing),
            issues=tuple(issues),
            **common,
        )
    return Assessment(status="ready", **common)


def reason_label(reason: Optional[str]) -> Optional[str]:
    return REASON_LABELS.get(reason or "")


def describe(missing: Sequence[str], issues: Sequence[str]) -> str:
    """Jedno zdanie do pozycji paczki: braki, potem uwagi."""
    parts: list[str] = []
    if missing:
        parts.append("Brakuje: " + ", ".join(missing) + ".")
    parts.extend(issues)
    return " ".join(parts)
