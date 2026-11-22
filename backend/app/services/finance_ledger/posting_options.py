"""Opis faktury kosztowej do księgowania (E2 wg „Ogólnych założeń” z 18.11.2026).

Główna księgowa przysłała listę pól, które Finanse wybierają przy opisie
faktury w eBI24 (``ksiegowosc-opis-faktury-wg-ksiegowej.md``). Tu są listy
wyboru i walidacja wyborów (``decree["choices"]``) — bez bazy. Wybory leżą
w dekrecie, nie w osobnej kolumnie: „Przelicz” liczy dekret z reguły i z tych
wyborów, więc ich nie gubi.

Konta: plan kont na produkcji ma konta zespołów 4 i 7 z rodzajem „inne”
(import planu z Symfonii, K1), a reguła wymagała rodzaju „koszt”. Zamiast
przestawiać setki kont, rodzaj „koszt” dla konta netto znaczy: rodzaj „koszt”
albo „inne” w zespole 4 lub 7 (``net_account_ok``). Konto VAT: rodzaj „VAT”
albo numer z listy księgowej (``VAT_ACCOUNTS``, także analityka).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

#: Typy dokumentów zakupu z arkusza księgowej (skrót → nazwa).
DOC_TYPES: dict[str, str] = {
    "FVZ": "Faktura VAT zakup",
    "IU": "Import usług",
    "DP": "Dokument prosty",
    "FVZP": "Faktura VAT zakup pozostałe",
    "WNT": "Faktura wewnętrzna WNT",
    "FKZ": "Faktura korygująca zakup",
    "FZBO": "Faktura VAT zakup bez odliczenia VAT",
}
#: Typy z samoobliczonym VAT (rejestr naliczony + należny).
IMPORT_TYPES: tuple[str, ...] = ("IU", "WNT")
#: Typ bez odliczenia VAT (koszt = brutto, bez pozycji VAT).
NO_DEDUCTION_TYPES: tuple[str, ...] = ("FZBO",)

#: Rejestry zakupu (VAT naliczony) z arkusza księgowej.
PURCHASE_REGISTER = "Zakup"
PURCHASE_REGISTERS: tuple[str, ...] = (
    PURCHASE_REGISTER,
    "Import usług VAT naliczony",
    "Rejestr naliczony WNT",
    "Zakup Środki Trwałe",
    "Korekta Zakupu",
    "Korekta Zakupu NP. VAT",
)
#: Rejestry VAT należnego do importu usług i WNT („drugi rejestr”).
OUTPUT_REGISTERS: tuple[str, ...] = (
    "Import usług VAT należny",
    "Rejestr należny WNT",
)
CORRECTION_REGISTER = "Korekta Zakupu"
#: Samochód: druga połowa w rejestrze bez odliczenia (nazwa z próbki eBI24).
CAR_SECOND_REGISTER = "Rejestr NP VAT"
CAR_SECOND_CORRECTION_REGISTER = "Korekta Zakupu NP. VAT"
DEFAULT_INPUT_REGISTER: dict[str, str] = {
    "IU": "Import usług VAT naliczony",
    "WNT": "Rejestr naliczony WNT",
}
DEFAULT_OUTPUT_REGISTER: dict[str, str] = {
    "IU": "Import usług VAT należny",
    "WNT": "Rejestr należny WNT",
}

#: Konta VAT z arkusza: naliczony (zakup) i należny (import usług, WNT).
INPUT_VAT_ACCOUNTS: dict[str, str] = {
    "221": "VAT naliczony",
    "223": "VAT naliczony przesunięty",
    "403-302": "VAT nieodliczony",
}
OUTPUT_VAT_ACCOUNTS: dict[str, str] = {
    "226": "VAT należny import usług",
    "222": "VAT należny sprzedaż",
    "224": "VAT należny przesunięty",
}
VAT_ACCOUNTS: dict[str, str] = {**INPUT_VAT_ACCOUNTS, **OUTPUT_VAT_ACCOUNTS}
DEFAULT_OUTPUT_VAT_ACCOUNT = "226"

#: Procedury / oznaczenia JPK zakupu (atrybut JPK w Symfonii, ``JPK_V7``).
JPK_PROCEDURES: dict[str, str] = {
    "MK": "Metoda kasowa",
    "BFK": "Faktura poza KSeF (BFK)",
    "DI": "Dokument wewnętrzny / inny (DI)",
    "OFF": "Faktura w trybie offline (OFF)",
    "WEW": "Dokument wewnętrzny (WEW)",
    "VAT_RR": "Faktura VAT RR",
    "IMP": "Import towarów (IMP)",
}
#: Import usług i WNT nie mają numeru KSeF — w JPK zawsze BFK (arkusz, wiersz 183).
IMPORT_JPK = "BFK"
CASH_METHOD_JPK = "MK"

#: Zapis równoległy „5”: Wn konto zespołu 5, Ma rozliczenie kosztów.
ALLOCATION_OFFSET = "490"
#: Samochód: pozabilansowo Wn 999, Ma konto 902–903 na połowę brutto.
OFFBALANCE_DEBIT = "999"
OFFBALANCE_PREFIXES: tuple[str, ...] = ("902", "903")
IMPORT_RATES: tuple[int, ...] = (23, 8, 5)

FX_TABLE_RE = re.compile(r"\d{1,3}/[ABC]/NBP/\d{4}")
FX_RATE_MAX = Decimal("100000")
DESCRIPTION_MAX = 255
_ACCOUNT_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z\-./]*")


class ChoiceError(ValueError):
    """Zły wybór na karcie faktury (komunikat po polsku, 422)."""


@dataclass(frozen=True)
class PlanEntry:
    number: str
    kind: str
    active: bool


def _group(number: str) -> str:
    return number[:1]


def _family(number: str, wanted: str) -> bool:
    """``number`` to ``wanted`` albo jego analityka (``221`` → ``221-1``)."""

    return number == wanted or number.startswith(f"{wanted}-")


def net_account_ok(number: str, kind: str, *, car: bool = False) -> bool:
    """Konto netto: rodzaj „koszt” albo „inne” w zespole 4 lub 7.

    Samochód w leasingu księguje netto na rozrachunku leasingu w zespole 2
    (próbka eBI24 z 18.11.2026: 244-3), więc przy „Paliwo i leasingi”
    dopuszczamy też zespół 2.
    """

    if kind == "cost":
        return True
    groups = ("4", "7", "2") if car else ("4", "7")
    return kind == "other" and _group(number) in groups


def vat_account_ok(number: str, kind: str) -> bool:
    """Konto VAT: rodzaj „VAT” albo konto z listy księgowej (z analityką)."""

    if kind == "vat":
        return True
    return any(_family(number, wanted) for wanted in VAT_ACCOUNTS)


def allocation_account_ok(number: str, kind: str) -> bool:
    return _group(number) == "5" and kind in ("cost", "other")


def offbalance_account_ok(number: str) -> bool:
    return any(_family(number, prefix) for prefix in OFFBALANCE_PREFIXES)


def _account(raw: Any, label: str) -> Optional[str]:
    value = str(raw or "").replace(" ", "")
    if not value:
        return None
    if len(value) > 32 or not _ACCOUNT_RE.fullmatch(value):
        raise ChoiceError(f"{label}: niepoprawny numer konta „{str(raw)[:40]}”.")
    return value


def _in_plan(
    number: Optional[str], plan: dict[str, PlanEntry], label: str, ok: Any
) -> Optional[str]:
    if number is None:
        return None
    account = plan.get(number)
    if account is None or not account.active:
        raise ChoiceError(
            f"{label}: konta {number} nie ma w planie kont albo jest wyłączone."
        )
    if not ok(account.number, account.kind):
        raise ChoiceError(f"{label}: konto {number} nie pasuje do tego pola.")
    return number


def _one_of(raw: Any, allowed: Any, label: str) -> Optional[str]:
    value = str(raw or "").strip()
    if not value:
        return None
    if value not in allowed:
        raise ChoiceError(f"{label}: wybierz wartość z listy.")
    return value


def _flag(raw: Any) -> Optional[bool]:
    if raw is None or raw == "":
        return None
    return bool(raw)


def _day(raw: Any, label: str) -> Optional[str]:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw)).isoformat()
    except ValueError as exc:
        raise ChoiceError(f"{label}: niepoprawna data.") from exc


def _rate(raw: Any) -> Optional[str]:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ChoiceError("Kurs: niepoprawna liczba.") from exc
    if not value.is_finite() or value <= 0 or value >= FX_RATE_MAX:
        raise ChoiceError("Kurs musi być większy od zera.")
    if value != value.quantize(Decimal("0.000001")):
        raise ChoiceError("Kurs ma najwyżej sześć miejsc po przecinku.")
    return format(value.normalize(), "f")


def clean_choices(body: dict[str, Any], plan: dict[str, PlanEntry]) -> dict[str, Any]:
    """Wybory z karty → słownik do dekretu (puste pole = podpowiedź z reguły)."""

    description = " ".join(str(body.get("description") or "").split())
    if len(description) > DESCRIPTION_MAX:
        raise ChoiceError(f"Opis księgowy ma najwyżej {DESCRIPTION_MAX} znaków.")
    table = str(body.get("fx_table") or "").strip().upper()
    if table and not FX_TABLE_RE.fullmatch(table):
        raise ChoiceError("Tabela NBP: wpisz numer jak 211/A/NBP/2026.")
    import_rate = body.get("import_rate")
    if import_rate not in (None, ""):
        try:
            import_rate = int(import_rate)
        except (TypeError, ValueError):
            import_rate = None
        if import_rate not in IMPORT_RATES:
            raise ChoiceError("Stawka importu usług: 23, 8 albo 5%.")
    else:
        import_rate = None
    car = bool(body.get("car"))
    offbalance = _in_plan(
        _account(body.get("offbalance_account"), "Konto 902–903"),
        plan,
        "Konto 902–903",
        lambda number, _kind: offbalance_account_ok(number),
    )
    if offbalance and not car:
        raise ChoiceError(
            "Zapis 999 / 902–903 jest tylko dla faktur samochodowych "
            "(„Paliwo i leasingi”)."
        )
    return {
        "description": description or None,
        "doc_type": _one_of(body.get("doc_type"), DOC_TYPES, "Typ dokumentu"),
        "register": _one_of(body.get("register"), PURCHASE_REGISTERS, "Rejestr"),
        "net_account": _in_plan(
            _account(body.get("net_account"), "Konto netto"),
            plan,
            "Konto netto",
            lambda number, kind: net_account_ok(number, kind, car=car),
        ),
        "vat_account": _one_of(
            body.get("vat_account"), INPUT_VAT_ACCOUNTS, "Konto VAT"
        ),
        "output_register": _one_of(
            body.get("output_register"), OUTPUT_REGISTERS, "Rejestr VAT należnego"
        ),
        "output_vat_account": _one_of(
            body.get("output_vat_account"), OUTPUT_VAT_ACCOUNTS, "Konto VAT należnego"
        ),
        "eu": _flag(body.get("eu")),
        "service": _flag(body.get("service")),
        "import_rate": import_rate,
        "allocation_account": _in_plan(
            _account(body.get("allocation_account"), "Konto „5”"),
            plan,
            "Konto „5”",
            allocation_account_ok,
        ),
        "car": car,
        "offbalance_account": offbalance,
        "jpk_procedure": _one_of(
            body.get("jpk_procedure"), JPK_PROCEDURES, "Procedura JPK"
        ),
        "fx_date": _day(body.get("fx_date"), "Data kursu"),
        "fx_rate": _rate(body.get("fx_rate")),
        "fx_table": table or None,
        "service_date": _day(body.get("service_date"), "Data zakończenia usługi"),
    }


def static_options() -> dict[str, Any]:
    """Listy wyboru niezależne od planu kont (karta faktury)."""

    def items(values: dict[str, str]) -> list[dict[str, str]]:
        return [{"value": key, "label": label} for key, label in values.items()]

    return {
        "doc_types": items(DOC_TYPES),
        "registers": [{"value": name, "label": name} for name in PURCHASE_REGISTERS],
        "output_registers": [
            {"value": name, "label": name} for name in OUTPUT_REGISTERS
        ],
        "vat_accounts": items(INPUT_VAT_ACCOUNTS),
        "output_vat_accounts": items(OUTPUT_VAT_ACCOUNTS),
        "jpk_procedures": items(JPK_PROCEDURES),
        "import_rates": list(IMPORT_RATES),
    }
