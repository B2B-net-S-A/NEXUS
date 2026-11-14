"""Dane kadrowo-płacowe osoby (K7a) — zaszyfrowane, tylko dla Kadr, Płac i admina.

Decyzja Artura z 13.11.2026: PESEL i dane do ZUS/PIT trzymamy w NEXUSIE
zaszyfrowane (``TokenCipher``, jak rachunek w ``employee_billing_details``).
Zmienia to regułę z etapu 4 („identyfikator osoby w Symfonii zamiast PESEL-u”)
dla danych płacowych; dane do rozliczeń B2B nadal PESEL-u nie przyjmują.

* **Kto:** Kadry, Płace, administrator (``can_edit``); osoba, przełożony
  i zespół — 404 jak brak osoby. Swoich danych nie zmienia się samemu
  (403), administrator może.
* **Co wychodzi na zewnątrz:** PESEL wyłącznie jako maska (kropki i 4 cyfry),
  bez daty urodzenia, gdy wynika z PESEL-u (data + 4 cyfry odsłoniłyby niemal
  cały numer); numer dokumentu i rachunek — tylko ostatnie cyfry. Pełne
  wartości trafiają tylko do plików KEDU i PIT oraz paczki przelewów.
* **Ślad** (``hr_audit_events``, ``sensitivity='payroll'``): nazwy zmienionych
  pól, nigdy wartości. Logi i komunikaty błędów — bez numerów.
* **Osoba** to konto z kartoteką (zespół) albo kandydat z kontraktem
  zleceniowym u klienta (bez konta w NEXUSIE).

Pola potrzebne do liczenia (``CALC_FIELDS``) blokują zatwierdzenie listy;
pola do plików (``FILE_FIELDS``) blokują tylko KEDU i PIT.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import TokenCipherNotConfigured, get_token_cipher
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractType
from app.models.hr_payroll_lists import PayrollPersonData
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.candidate_audit import candidate_subject_reference
from app.services.hr import audit
from app.services.hr.bank.accounts import AccountError, normalize_nrb
from app.services.hr.billing_details import account_fingerprint
from app.services.hr.payroll_errors import (
    PayrollError,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_lists import pesel as pesel_rules
from app.services.hr.payroll_lists.engine import PersonTax, Ppk, birthday
from app.services.order_client_identity import nip_checksum_valid

logger = logging.getLogger(__name__)

NOT_FOUND = "Nie ma takiej osoby."
CIPHER_MISSING = (
    "Szyfrowanie danych płacowych nie jest skonfigurowane — nic nie zapisano."
)
OWN_DATA = (
    "Swoich danych płacowych nie zmieniasz sam — zrobi to druga osoba "
    "z Administracji współpracy albo Rozliczeń, albo administrator."
)
TEXT_MAX = 60
NAME_MAX = 80
DOC_TYPES = ("id_card", "passport")
KUP_KINDS = ("standard", "increased")
RELIEFS = ("family4", "return", "senior")
ADDRESS_FIELDS = (
    "country",
    "voivodeship",
    "county",
    "commune",
    "city",
    "street",
    "house_number",
    "flat_number",
    "postal_code",
    "post_office",
)
#: Bez tego lista się nie policzy rzetelnie (data urodzenia, płeć, imię i nazwisko).
CALC_FIELDS = ("identity", "first_name", "last_name")
#: Bez tego nie powstanie KEDU albo PIT-11.
FILE_FIELDS = ("address", "tax_office_code", "zus_title_code")
FIELD_LABELS: dict[str, str] = {
    "identity": "PESEL albo dokument z datą urodzenia i płcią",
    "first_name": "imię",
    "last_name": "nazwisko",
    "address": "adres zamieszkania",
    "tax_office_code": "urząd skarbowy",
    "zus_title_code": "kod tytułu ubezpieczenia",
    "bank_account": "rachunek do wypłaty",
}
_TITLE_CODE = re.compile(r"^[0-9]{6}$")
_TAX_OFFICE = re.compile(r"^[0-9]{4}$")
_POSTAL_PL = re.compile(r"^[0-9]{2}-[0-9]{3}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_DOC_NUMBER = re.compile(r"^[A-Z0-9]{5,20}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NFZ = re.compile(r"^(0[1-9]|1[0-6])R$")
_WORK_TIME = re.compile(r"^([1-9][0-9]?)/([1-9][0-9]?)$")
#: Oddziały wojewódzkie NFZ (kod do ZUA/ZZA) — alfabetycznie jak województwa.
NFZ_BY_VOIVODESHIP: dict[str, str] = {
    name: f"{index:02d}R"
    for index, name in enumerate(
        (
            "dolnośląskie",
            "kujawsko-pomorskie",
            "lubelskie",
            "lubuskie",
            "łódzkie",
            "małopolskie",
            "mazowieckie",
            "opolskie",
            "podkarpackie",
            "podlaskie",
            "pomorskie",
            "śląskie",
            "świętokrzyskie",
            "warmińsko-mazurskie",
            "wielkopolskie",
            "zachodniopomorskie",
        ),
        start=1,
    )
}


class PersonDataError(PayrollError):
    """Zła wartość w danych płacowych — komunikat bez numerów osoby."""


@dataclass(frozen=True)
class Subject:
    user_id: Optional[int] = None
    candidate_id: Optional[int] = None

    def __post_init__(self) -> None:
        if (self.user_id is None) == (self.candidate_id is None):
            raise ValueError("osoba = konto albo kandydat")

    @property
    def key(self) -> str:
        return (
            f"u{self.user_id}" if self.user_id is not None else f"c{self.candidate_id}"
        )


# ── Dostęp ────────────────────────────────────────────────────────────────────


def can_edit(user: User) -> bool:
    """Kadry, Płace i admin czytają i zmieniają dane płacowe."""

    return (
        user.has_role(UserRole.admin)
        or has_permission(user, ProductAction.people_admin)
        or has_permission(user, ProductAction.payroll)
    )


def candidate_ref(candidate_id: int) -> str:
    """Pseudonim kandydata (jak przy umowach) — łączy dokumentację płacową po
    usunięciu kandydata (klucz obcy ``SET NULL``)."""

    try:
        return candidate_subject_reference(candidate_id)
    except RuntimeError:
        raise PersonDataError(
            "Brak klucza pseudonimizacji kandydatów — nic nie zapisano.", 503
        ) from None


def ensure_not_own(actor: User, subject: Subject) -> None:
    if subject.user_id is not None and subject.user_id == actor.id:
        if not actor.has_role(UserRole.admin):
            raise PayrollForbidden(OWN_DATA)


async def subject_name(db: AsyncSession, subject: Subject) -> str:
    """Imię i nazwisko z konta albo kandydata; brak osoby albo poza zakresem = 404."""

    if subject.user_id is not None:
        row = (
            await db.execute(
                select(User.name)
                .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
                .where(User.id == subject.user_id)
            )
        ).first()
        if row is None:
            raise PayrollNotFound(NOT_FOUND)
        return str(row[0])
    has_mandate = await db.scalar(
        select(Contract.id)
        .where(
            Contract.candidate_id == subject.candidate_id,
            Contract.contract_type == ContractType.uzlecenie,
        )
        .limit(1)
    )
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname).where(
                Candidate.id == subject.candidate_id
            )
        )
    ).first()
    if has_mandate is None or row is None:
        raise PayrollNotFound(NOT_FOUND)
    return " ".join(part for part in (row[0], row[1]) if part)


# ── Walidacja pól (czyste funkcje) ───────────────────────────────────────────


def _text(raw: Any, label: str, *, limit: int = TEXT_MAX) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise PersonDataError(f"{label}: tekst.")
    text = " ".join(raw.split())
    if not text:
        return None
    if len(text) > limit or _CONTROL.search(text):
        raise PersonDataError(f"{label}: najwyżej {limit} znaków.")
    return text


def _date(raw: Any, label: str) -> Optional[date]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise PersonDataError(f"{label}: data w formacie RRRR-MM-DD.") from None


def _rate(raw: Any, label: str, low: str, high: str) -> Decimal:
    if isinstance(raw, bool):
        raise PersonDataError(f"{label}: liczba.")
    try:
        value = Decimal(str(raw).replace(",", "."))
    except InvalidOperation:
        raise PersonDataError(f"{label}: liczba.") from None
    if not value.is_finite() or not Decimal(low) <= value <= Decimal(high):
        raise PersonDataError(f"{label}: od {low} do {high}%.")
    return value.quantize(Decimal("0.01"))


def _bool(raw: Any, label: str) -> bool:
    if not isinstance(raw, bool):
        raise PersonDataError(f"{label}: tak albo nie.")
    return raw


def clean_address(raw: Any) -> Optional[dict[str, str]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PersonDataError("Adres zamieszkania: zły format.")
    out: dict[str, str] = {}
    for key in ADDRESS_FIELDS:
        value = _text(raw.get(key), "Adres zamieszkania")
        if value is not None:
            out[key] = value
    country = (out.get("country") or "PL").upper()
    if not _COUNTRY.match(country):
        raise PersonDataError("Kraj: dwuliterowy kod, np. PL.")
    out["country"] = country
    postal = out.get("postal_code")
    if country == "PL" and postal is not None and not _POSTAL_PL.match(postal):
        raise PersonDataError("Kod pocztowy: w formacie 00-000.")
    return out


def _address_complete(address: Optional[dict[str, str]]) -> bool:
    if not address:
        return False
    needed = ["city", "house_number", "postal_code"]
    if address.get("country", "PL") == "PL":
        needed += ["voivodeship", "county", "commune"]
    return all(address.get(key) for key in needed)


def _ppk(raw: Any) -> Optional[dict[str, str]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PersonDataError("PPK: zły format.")
    if not _bool(raw.get("participates", False), "PPK — uczestnictwo"):
        return None
    return {
        "employee_rate": str(
            _rate(
                raw.get("employee_rate", "2"),
                "PPK — wpłata podstawowa osoby",
                "0.5",
                "2",
            )
        ),
        "employee_extra": str(
            _rate(
                raw.get("employee_extra", "0"), "PPK — wpłata dodatkowa osoby", "0", "2"
            )
        ),
        "employer_extra": str(
            _rate(
                raw.get("employer_extra", "0"),
                "PPK — wpłata dodatkowa pracodawcy",
                "0",
                "2.5",
            )
        ),
    }


def apply_changes(
    current: dict[str, Any], changes: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Nowy komplet danych i nazwy zmienionych pól. Komunikaty bez numerów osoby.

    ``changes`` niesie tylko pola, które się zmieniają; ``None`` czyści pole.
    """

    data = dict(current)
    changed: list[str] = []

    def put(key: str, value: Any) -> None:
        # Puste pole nie zostaje w zapisie: brak klucza = wartość domyślna.
        empty = (
            value is None or value == [] or (key == "youth_relief_waived" and not value)
        )
        if data.get(key) != (None if empty else value):
            changed.append(key)
        if empty:
            data.pop(key, None)
        else:
            data[key] = value

    if "pesel" in changes:
        put("pesel", pesel_rules.clean(changes["pesel"]))
    if "document_type" in changes:
        doc_type = changes["document_type"] or None
        if doc_type is not None and doc_type not in DOC_TYPES:
            raise PersonDataError("Rodzaj dokumentu: dowód osobisty albo paszport.")
        put("document_type", doc_type)
    if "document_number" in changes:
        raw_number = changes["document_number"]
        number = _text(
            None if raw_number is None else str(raw_number), "Numer dokumentu", limit=20
        )
        number = number.replace(" ", "").upper() if number else None
        if number is not None and not _DOC_NUMBER.match(number):
            raise PersonDataError("Numer dokumentu: 5–20 liter i cyfr.")
        put("document_number", number)
    if "birth_date" in changes:
        born = _date(changes["birth_date"], "Data urodzenia")
        if born is not None and not date(1900, 1, 1) <= born <= date(2100, 1, 1):
            raise PersonDataError("Data urodzenia poza zakresem.")
        put("birth_date", born.isoformat() if born else None)
    if "sex" in changes:
        sex = changes["sex"] or None
        if sex is not None and sex not in ("F", "M"):
            raise PersonDataError("Płeć: K albo M.")
        put("sex", sex)
    for key, label, limit in (
        ("first_name", "Imię", NAME_MAX),
        ("last_name", "Nazwisko", NAME_MAX),
        ("citizenship", "Obywatelstwo", 2),
        ("tax_office_name", "Urząd skarbowy", TEXT_MAX * 2),
    ):
        if key in changes:
            value = _text(changes[key], label, limit=limit)
            if key == "citizenship" and value is not None:
                value = value.upper()
                if not _COUNTRY.match(value):
                    raise PersonDataError("Obywatelstwo: dwuliterowy kod, np. PL.")
            put(key, value)
    if "address" in changes:
        put("address", clean_address(changes["address"]))
    if "work_time" in changes:
        raw_time = _text(changes["work_time"], "Wymiar etatu", limit=5)
        match = _WORK_TIME.match(raw_time.replace(" ", "")) if raw_time else None
        if raw_time is not None and (
            match is None or int(match.group(1)) > int(match.group(2))
        ):
            raise PersonDataError("Wymiar etatu: ułamek, np. 1/1 albo 1/2.")
        put(
            "work_time",
            None if raw_time in (None, "1/1") else raw_time.replace(" ", ""),
        )
    if "nip" in changes:
        nip = "".join(ch for ch in str(changes["nip"] or "") if ch.isdigit())
        if nip and not nip_checksum_valid(nip):
            raise PersonDataError("NIP osoby: 10 cyfr z poprawną cyfrą kontrolną.")
        put("nip", nip or None)
    if "nfz_code" in changes:
        nfz = _text(changes["nfz_code"], "Oddział NFZ", limit=3)
        nfz = nfz.upper() if nfz else None
        if nfz is not None and not _NFZ.match(nfz):
            raise PersonDataError("Oddział NFZ: kod od 01R do 16R.")
        put("nfz_code", nfz)
    if "tax_office_code" in changes:
        code = _text(changes["tax_office_code"], "Kod urzędu skarbowego", limit=4)
        if code is not None and not _TAX_OFFICE.match(code):
            raise PersonDataError("Kod urzędu skarbowego: 4 cyfry.")
        put("tax_office_code", code)
    if "zus_title_code" in changes:
        code = _text(changes["zus_title_code"], "Kod tytułu ubezpieczenia", limit=8)
        code = code.replace(" ", "") if code else None
        if code is not None and not _TITLE_CODE.match(code):
            raise PersonDataError(
                "Kod tytułu ubezpieczenia: 6 cyfr (tytuł, prawo do emerytury, "
                "niepełnosprawność), np. 011000."
            )
        put("zus_title_code", code)
    if "pit2" in changes:
        fraction = changes["pit2"]
        if isinstance(fraction, bool) or fraction not in (0, 12, 24, 36):
            raise PersonDataError("PIT-2: brak, 1/12, 1/24 albo 1/36.")
        put("pit2", fraction or None)
    if "kup" in changes:
        kup = changes["kup"] or "standard"
        if kup not in KUP_KINDS:
            raise PersonDataError("Koszty uzyskania: zwykłe albo podwyższone.")
        put("kup", None if kup == "standard" else kup)
    if "reliefs" in changes:
        raw = changes["reliefs"] or []
        if not isinstance(raw, list) or any(item not in RELIEFS for item in raw):
            raise PersonDataError("Ulgi: dla rodzin 4+, na powrót, dla seniora.")
        put("reliefs", sorted(set(raw)))
    if "youth_relief_waived" in changes:
        put(
            "youth_relief_waived",
            _bool(changes["youth_relief_waived"], "Rezygnacja z ulgi dla młodych"),
        )
    if "student_exempt_until" in changes:
        until = _date(changes["student_exempt_until"], "Student do")
        put("student_exempt_until", until.isoformat() if until else None)
    for key, label in (
        ("mandate_pension_insurance", "Zlecenie — emerytalne i rentowe"),
        ("mandate_sickness_voluntary", "Zlecenie — dobrowolne chorobowe"),
        ("mandate_accident_insurance", "Zlecenie — wypadkowe"),
    ):
        if key in changes:
            put(key, _bool(changes[key], label))
    if "ppk" in changes:
        put("ppk", _ppk(changes["ppk"]))
    for key, label in (
        ("labour_fund_exempt_until", "Bez Funduszu Pracy do"),
        ("fgsp_exempt_until", "Bez FGŚP do"),
    ):
        if key in changes:
            until = _date(changes[key], label)
            put(key, until.isoformat() if until else None)
    if "bank_account" in changes:
        raw_account = changes["bank_account"]
        if raw_account in (None, ""):
            put("bank_account", None)
        else:
            try:
                put("bank_account", normalize_nrb(str(raw_account)))
            except AccountError:
                raise PersonDataError("Rachunek: 26 cyfr numeru NRB.") from None
    _check_identity(data)
    return data, changed


def _check_identity(data: dict[str, Any]) -> None:
    number = data.get("pesel")
    if number:
        born = pesel_rules.birth_date(number)
        manual = data.get("birth_date")
        if manual and born and manual != born.isoformat():
            raise PersonDataError("Data urodzenia nie zgadza się z PESEL-em.")
        if data.get("sex") and data["sex"] != pesel_rules.sex(number):
            raise PersonDataError("Płeć nie zgadza się z PESEL-em.")
    if data.get("document_number") and not data.get("document_type"):
        raise PersonDataError("Podaj rodzaj dokumentu.")


def birth_date_of(data: dict[str, Any]) -> Optional[date]:
    number = data.get("pesel")
    if number:
        return pesel_rules.birth_date(number)
    raw = data.get("birth_date")
    return date.fromisoformat(raw) if raw else None


def work_time_of(data: dict[str, Any]) -> tuple[int, int]:
    """Wymiar etatu (licznik, mianownik); brak wpisu = pełny etat."""

    match = _WORK_TIME.match(str(data.get("work_time") or "1/1"))
    if match is None:
        return (1, 1)
    return (int(match.group(1)), int(match.group(2)))


def nfz_code_of(data: dict[str, Any]) -> Optional[str]:
    """Kod oddziału NFZ: wpisany albo z województwa adresu zamieszkania."""

    if data.get("nfz_code"):
        return str(data["nfz_code"])
    address = data.get("address") or {}
    voivodeship = str(address.get("voivodeship") or "").strip().lower()
    return NFZ_BY_VOIVODESHIP.get(voivodeship)


def sex_of(data: dict[str, Any]) -> Optional[str]:
    number = data.get("pesel")
    if number:
        return pesel_rules.sex(number)
    return data.get("sex")


def missing_fields(data: dict[str, Any], *, contractor: bool) -> list[str]:
    """Brakujące pola (nazwy, bez wartości): najpierw do liczenia, potem do plików."""

    out: list[str] = []
    has_identity = bool(data.get("pesel")) or bool(
        data.get("document_type")
        and data.get("document_number")
        and data.get("birth_date")
        and data.get("sex")
    )
    if not has_identity:
        out.append("identity")
    for key in ("first_name", "last_name"):
        if not data.get(key):
            out.append(key)
    if not _address_complete(data.get("address")):
        out.append("address")
    for key in ("tax_office_code", "zus_title_code"):
        if not data.get(key):
            out.append(key)
    if contractor and not data.get("bank_account"):
        out.append("bank_account")
    return out


def blocks_calculation(missing: list[str]) -> list[str]:
    return [code for code in missing if code in CALC_FIELDS]


def blocks_files(missing: list[str]) -> list[str]:
    return [code for code in missing if code in CALC_FIELDS or code in FILE_FIELDS]


def person_tax(
    data: dict[str, Any], profile: Optional[EmployeeProfile], *, youth_age: int = 26
) -> PersonTax:
    """Dane do silnika. Student (zlecenie): kartoteka zespołu albo dane kontraktora."""

    born = birth_date_of(data)
    student_until: Optional[date] = None
    if profile is not None:
        if profile.student_contribution_exempt:
            student_until = profile.contribution_exempt_until or date.max
    elif data.get("student_exempt_until"):
        student_until = date.fromisoformat(data["student_exempt_until"])
    if student_until == date.max and born is not None:
        # Bez daty w kartotece zwolnienie trwa do dnia przed 26. urodzinami.
        student_until = birthday(born, youth_age) - timedelta(days=1)
    ppk_raw = data.get("ppk")
    ppk = (
        Ppk(
            employee_rate=Decimal(ppk_raw["employee_rate"]),
            employee_extra=Decimal(ppk_raw.get("employee_extra", "0")),
            employer_extra=Decimal(ppk_raw.get("employer_extra", "0")),
        )
        if ppk_raw
        else None
    )
    return PersonTax(
        birth_date=born,
        sex=sex_of(data),
        pit2_fraction=int(data.get("pit2") or 0),
        kup_increased=data.get("kup") == "increased",
        reliefs=frozenset(data.get("reliefs") or ()),
        youth_relief_waived=bool(data.get("youth_relief_waived")),
        student_exempt_until=student_until,
        ppk=ppk,
        labour_fund_exempt_until=_date(data.get("labour_fund_exempt_until"), "FP"),
        fgsp_exempt_until=_date(data.get("fgsp_exempt_until"), "FGŚP"),
    )


def mandate_flags(data: dict[str, Any]) -> dict[str, bool]:
    return {
        "pension_insurance": data.get("mandate_pension_insurance", True) is not False,
        "sickness_voluntary": data.get("mandate_sickness_voluntary") is True,
        "accident_insurance": data.get("mandate_accident_insurance", True) is not False,
    }


def split_name(full: str) -> tuple[str, str]:
    """Podpowiedź z konta: ostatni wyraz to nazwisko (Kadry poprawiają)."""

    parts = full.split()
    if len(parts) < 2:
        return full, ""
    return " ".join(parts[:-1]), parts[-1]


# ── Szyfrowanie ──────────────────────────────────────────────────────────────


def encrypt(data: dict[str, Any]) -> str:
    try:
        return get_token_cipher().encrypt(json.dumps(data, sort_keys=True))
    except TokenCipherNotConfigured:
        raise PersonDataError(CIPHER_MISSING, 503) from None


def decrypt(record: PayrollPersonData) -> dict[str, Any]:
    """Treść rekordu; nieczytelna (zmieniony klucz) = błąd bez treści."""

    try:
        raw = get_token_cipher().decrypt(record.data_encrypted)
        data = json.loads(raw)
    except (TokenCipherNotConfigured, ValueError):
        logger.error("payroll person data unreadable (record %s)", record.id)
        raise PersonDataError(
            "Nie udało się odczytać danych płacowych — sprawdź klucz szyfrowania.", 503
        ) from None
    return data if isinstance(data, dict) else {}


# ── Odczyt i zapis ───────────────────────────────────────────────────────────


async def load_record(
    db: AsyncSession, subject: Subject, *, lock: bool = False
) -> Optional[PayrollPersonData]:
    query = select(PayrollPersonData)
    if subject.user_id is not None:
        query = query.where(PayrollPersonData.user_id == subject.user_id)
    else:
        query = query.where(PayrollPersonData.candidate_id == subject.candidate_id)
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


async def records_for(
    db: AsyncSession, user_ids: set[int], candidate_ids: set[int]
) -> dict[str, PayrollPersonData]:
    """Rekordy wielu osób naraz: klucz ``u<id>`` albo ``c<id>``."""

    out: dict[str, PayrollPersonData] = {}
    if user_ids:
        for record in await db.scalars(
            select(PayrollPersonData).where(PayrollPersonData.user_id.in_(user_ids))
        ):
            out[f"u{record.user_id}"] = record
    if candidate_ids:
        for record in await db.scalars(
            select(PayrollPersonData).where(
                PayrollPersonData.candidate_id.in_(candidate_ids)
            )
        ):
            out[f"c{record.candidate_id}"] = record
    return out


async def records_by_keys(
    db: AsyncSession, keys: set[str]
) -> dict[str, PayrollPersonData]:
    """Rekordy po kluczach osoby z list płac: ``u<konto>``, ``c<kandydat>``
    albo ``r<pseudonim>`` (kandydat usunięty — ``SET NULL`` zostawia pseudonim)."""

    user_ids = {int(k[1:]) for k in keys if k.startswith("u") and k[1:].isdigit()}
    candidate_ids = {int(k[1:]) for k in keys if k.startswith("c") and k[1:].isdigit()}
    refs = {k[1:] for k in keys if k.startswith("r") and len(k) > 1}
    out = await records_for(db, user_ids, candidate_ids)
    if refs:
        for record in await db.scalars(
            select(PayrollPersonData).where(PayrollPersonData.candidate_ref.in_(refs))
        ):
            out[f"r{record.candidate_ref}"] = record
    return out


def payload(
    subject: Subject,
    name: str,
    record: Optional[PayrollPersonData],
    data: dict[str, Any],
    *,
    editable: bool,
    today: date,
    youth_age: int = 26,
) -> dict[str, Any]:
    """Odpowiedź z maskami: bez PESEL-u, numeru dokumentu i rachunku."""

    contractor = subject.candidate_id is not None
    missing = missing_fields(data, contractor=contractor)
    first, last = split_name(name)
    born = birth_date_of(data)
    youth_until = birthday(born, youth_age) if born else None
    document = data.get("document_number")
    return {
        "subject": subject.key,
        "user_id": subject.user_id,
        "candidate_id": subject.candidate_id,
        "name": name,
        "exists": record is not None,
        "can_edit": editable,
        "pesel_masked": pesel_rules.masked(record.pesel_last4 if record else None),
        "document_type": data.get("document_type"),
        "document_masked": f"•••{document[-3:]}" if document else None,
        # Data urodzenia tylko wpisana ręcznie (bez PESEL-u) — inaczej z maską
        # PESEL-u odsłoniłaby prawie cały numer.
        "birth_date": None if data.get("pesel") else data.get("birth_date"),
        "sex": None if data.get("pesel") else data.get("sex"),
        "first_name": data.get("first_name") or first,
        "last_name": data.get("last_name") or last,
        "names_confirmed": bool(data.get("first_name") and data.get("last_name")),
        "citizenship": data.get("citizenship"),
        "address": data.get("address"),
        "tax_office_code": data.get("tax_office_code"),
        "tax_office_name": data.get("tax_office_name"),
        "zus_title_code": data.get("zus_title_code"),
        "nfz_code": nfz_code_of(data),
        "nip": data.get("nip"),
        "work_time": "{}/{}".format(*work_time_of(data)),
        "pit2": int(data.get("pit2") or 0),
        "kup": data.get("kup") or "standard",
        "reliefs": list(data.get("reliefs") or []),
        "youth_relief_waived": bool(data.get("youth_relief_waived")),
        "youth_relief_now": bool(
            youth_until and today <= youth_until and not data.get("youth_relief_waived")
        ),
        "student_exempt_until": data.get("student_exempt_until"),
        "mandate": mandate_flags(data),
        "ppk": data.get("ppk"),
        "labour_fund_exempt_until": data.get("labour_fund_exempt_until"),
        "fgsp_exempt_until": data.get("fgsp_exempt_until"),
        "bank_account_last4": record.account_last4 if record else None,
        "missing": missing,
        "missing_labels": [FIELD_LABELS[code] for code in missing],
        "blocks_calculation": blocks_calculation(missing),
        "updated_at": record.updated_at.isoformat()
        if record and record.updated_at
        else None,
        "version": record.version if record else 0,
    }


async def get(
    db: AsyncSession, *, actor: User, subject: Subject, today: date
) -> dict[str, Any]:
    if not can_edit(actor):
        raise PayrollNotFound(NOT_FOUND)
    name = await subject_name(db, subject)
    record = await load_record(db, subject)
    data = decrypt(record) if record else {}
    return payload(
        subject,
        name,
        record,
        data,
        editable=not (
            subject.user_id == actor.id and not actor.has_role(UserRole.admin)
        ),
        today=today,
    )


async def update(
    db: AsyncSession,
    *,
    actor: User,
    subject: Subject,
    changes: dict[str, Any],
    expected_version: Optional[int],
    today: date,
) -> dict[str, Any]:
    """Zmiana danych (bez commita). Inna wersja niż oczekiwana = 409."""

    if not can_edit(actor):
        raise PayrollNotFound(NOT_FOUND)
    name = await subject_name(db, subject)
    ensure_not_own(actor, subject)
    record = await load_record(db, subject, lock=True)
    current = decrypt(record) if record else {}
    if (
        expected_version is not None
        and (record.version if record else 0) != expected_version
    ):
        raise PayrollError(
            "Dane tej osoby zmienił w międzyczasie ktoś inny — odśwież i wpisz zmiany "
            "jeszcze raz.",
            409,
            code="stale_person_data",
        )
    data, changed = apply_changes(current, changes)
    if not changed:
        return payload(subject, name, record, data, editable=True, today=today)
    number = data.get("pesel")
    try:
        pesel_hmac = pesel_rules.fingerprint(number) if number else None
        account = data.get("bank_account")
        account_hmac = account_fingerprint(account) if account else None
    except TokenCipherNotConfigured:
        raise PersonDataError(CIPHER_MISSING, 503) from None
    if pesel_hmac is not None:
        owner = await db.scalar(
            select(PayrollPersonData.id).where(
                PayrollPersonData.pesel_hmac == pesel_hmac,
                PayrollPersonData.id != (record.id if record else 0),
            )
        )
        if owner is not None:
            raise PayrollError(
                "Ten PESEL ma już w danych płacowych inna osoba — sprawdź numer.",
                409,
                code="pesel_taken",
            )
    encrypted = encrypt(data)
    missing = missing_fields(data, contractor=subject.candidate_id is not None)
    if record is None:
        record = PayrollPersonData(
            user_id=subject.user_id,
            candidate_id=subject.candidate_id,
            candidate_ref=candidate_ref(subject.candidate_id)
            if subject.candidate_id is not None
            else None,
            data_encrypted=encrypted,
            version=1,
        )
        db.add(record)
    else:
        record.data_encrypted = encrypted
        record.version = (record.version or 0) + 1
    record.pesel_hmac = pesel_hmac
    record.pesel_last4 = pesel_rules.last4(number) if number else None
    record.account_hmac = account_hmac
    record.account_last4 = (
        data["bank_account"][-4:] if data.get("bank_account") else None
    )
    record.missing = missing
    record.updated_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=subject.user_id,
        entity_type="payroll_person_data",
        entity_id=record.id,
        action="payroll_person_data_updated",
        sensitivity="payroll",
        details={
            "fields": sorted(changed),
            "candidate_id": subject.candidate_id,
            "missing": missing,
        },
    )
    await db.flush()
    # ``updated_at`` liczy baza (``onupdate``) — po UPDATE atrybut wygasa, a leniwy
    # odczyt w sesji async kończy się MissingGreenlet (500 przy drugim zapisie).
    await db.refresh(record, attribute_names=["updated_at"])
    return payload(subject, name, record, data, editable=True, today=today)


__all__ = [
    "CALC_FIELDS",
    "FIELD_LABELS",
    "FILE_FIELDS",
    "PersonDataError",
    "Subject",
    "apply_changes",
    "birth_date_of",
    "blocks_calculation",
    "blocks_files",
    "can_edit",
    "decrypt",
    "encrypt",
    "get",
    "load_record",
    "mandate_flags",
    "missing_fields",
    "nfz_code_of",
    "work_time_of",
    "payload",
    "person_tax",
    "records_by_keys",
    "records_for",
    "sex_of",
    "split_name",
    "update",
]
