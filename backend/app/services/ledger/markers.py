"""Pozycje kont w sprawozdaniu (K8a) — znaczniki MF z JPK_KR_PD(1).

Decyzja Artura z 16.11.2026: jedno przypisanie konta służy sprawozdaniu
(bilans, RZiS w wariancie porównawczym), e-Sprawozdaniu (K8b) i JPK_KR_PD
(K8c), więc pozycją konta jest **znacznik ze słownika MF** „jednostki
pozostałe” (typ ``TMapKontaPOZ`` w schemacie JPK_KR_PD(1) v1-1, pobranym
z gov.pl 16.11.2026 do ``jpk_kr_schema/schemat.xsd``). Słownik i opisy
pozycji czytamy z tego pliku — nie przepisujemy 244 kodów ręcznie.

* ``finance_accounts.report_line`` trzyma ``KOD`` albo ``KOD_Wn/KOD_Ma`` —
  drugi wariant dla kont, których saldo raz jest należnością, a raz
  zobowiązaniem (rozrachunki): saldo Wn analityki idzie pod pierwszy znacznik,
  saldo Ma pod drugi. Inne wartości odrzuca zapis konta (422).
* Znacznik konta: wpis przy koncie albo przy koncie nadrzędnym (``201-2-1000``
  → ``201-2`` → ``201``), potem reguła po numerze (wzorcowy plan kont),
  potem brak. Reguły są tylko tam, gdzie numer jest jednoznaczny — numeracja
  zespołu 4 zależy od planu spółki (K6 księguje amortyzację na 401), więc
  400–405 czekają na wpis księgowej.
* Konta 9 (pozabilansowe) nie wchodzą do sprawozdań; konta 5 i 490
  (rozliczenie kosztów na MPK, K2) pomija wariant porównawczy — muszą się
  znosić, co sprawdza ``statements``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional
from xml.etree import ElementTree

from app.services.finance_ledger.costs import LedgerError
from app.services.ledger_schema import REPORT_LINE_MAX

SCHEMA = Path(__file__).with_name("jpk_kr_schema") / "schemat.xsd"
DICTIONARY_TYPE = "TMapKontaPOZ"
_XSD = "{http://www.w3.org/2001/XMLSchema}"
#: Końcówki kodów aktywów, które korygują pozycję (odpisy, umorzenie, odchylenia)
#: — należą do pozycji nadrzędnej, nie tworzą własnej. Tylko ``BA…``: w RZiS
#: ``RPJ_RKM_O`` to podatek „Odroczony”, osobna pozycja (przegląd K8a).
ADJUSTMENT_SUFFIXES = ("_A", "_U", "_O")
#: Pierwsze segmenty kont spoza sprawozdań i spoza wariantu porównawczego.
OFF_BALANCE_PREFIX = "9"
COST_ALLOCATION_PREFIXES = ("5", "490")

GROUP_ASSETS = "assets"
GROUP_LIABILITIES = "liabilities"
GROUP_RESULT = "result"
GROUP_OTHER = "other"


@dataclass(frozen=True)
class Marker:
    code: str
    path: tuple[str, ...]

    @property
    def group(self) -> str:
        if self.code.startswith("BA"):
            return GROUP_ASSETS
        if self.code.startswith("BP"):
            return GROUP_LIABILITIES
        if self.code.startswith("R"):
            return GROUP_RESULT
        return GROUP_OTHER

    @property
    def position(self) -> tuple[str, ...]:
        """Ścieżka pozycji sprawozdania (bez nagłówka AKTYWA/PASYWA/WYNIKOWE)."""

        path = self.path[1:]
        if self.group == GROUP_ASSETS and self.code.endswith(ADJUSTMENT_SUFFIXES):
            path = path[:-1]
        return path

    @property
    def comparative(self) -> bool:
        """Czy znacznik ma pozycję w RZiS w wariancie porównawczym."""

        return self.group == GROUP_RESULT and self.code.startswith("RP")

    @property
    def label(self) -> str:
        return " · ".join(part.split(" / ")[0] for part in self.position)


@lru_cache(maxsize=1)
def dictionary() -> dict[str, Marker]:
    """Słownik MF w kolejności ze schematu (kolejność = układ załącznika 1)."""

    root = ElementTree.parse(SCHEMA).getroot()
    for simple in root.iter(f"{_XSD}simpleType"):
        if simple.get("name") != DICTIONARY_TYPE:
            continue
        out: dict[str, Marker] = {}
        for item in simple.iter(f"{_XSD}enumeration"):
            code = item.get("value") or ""
            doc = item.find(f"{_XSD}annotation/{_XSD}documentation")
            text = " ".join((doc.text or "").split()) if doc is not None else ""
            out[code] = Marker(code, tuple(part.strip() for part in text.split(" | ")))
        return out
    raise RuntimeError(f"Brak słownika {DICTIONARY_TYPE} w {SCHEMA.name}")


@dataclass(frozen=True)
class Pair:
    """Znacznik dla salda Wn i dla salda Ma (zwykle ten sam)."""

    debit: str
    credit: str

    @property
    def text(self) -> str:
        return (
            self.debit if self.debit == self.credit else f"{self.debit}/{self.credit}"
        )


def _pair(debit: str, credit: Optional[str] = None) -> Pair:
    return Pair(debit, credit or debit)


#: Reguły po początku pierwszego segmentu numeru (najdłuższy wygrywa).
RULES: dict[str, Pair] = {
    "10": _pair("BABIII1c1_SPKR"),
    "13": _pair("BABIII1c1_SPKR", "BPBIII3a"),
    "14": _pair("BABIII1c1_SPKR"),
    "20": _pair("BABII3a_D12", "BPBIII3d_D12"),
    "22": _pair("BABII3b", "BPBIII3g"),
    "23": _pair("BABII3c_W", "BPBIII3h"),
    "24": _pair("BABII3c_W", "BPBIII3i"),
    "64": _pair("BABIV", "BPBIV2_K"),
    "402": _pair("RPBIII"),
    "409": _pair("RPBVII"),
    "70": _pair("RPAI_RKAI_POZ"),
    "73": _pair("RPAIV_RKAII_POZ"),
    "750": _pair("RPGV_RKJV_POZ"),
    "751": _pair("RPHIV_RKKIV_POZ"),
    "760": _pair("RPDIV_RKGIV_P"),
    "761": _pair("RPEIII_RKHIII_P"),
    "801": _pair("BPAI"),
    "820": _pair("BPAV"),
    "860": _pair("BPAVI"),
    "870": _pair("RPJ_RKM_B"),
}

SOURCE_OWN = "own"
SOURCE_PARENT = "parent"
SOURCE_RULE = "rule"
SOURCE_EXCLUDED = "excluded"
SOURCE_NONE = "none"


def first_segment(number: str) -> str:
    return number.split("-")[0]


def excluded(number: str) -> Optional[str]:
    """Powód, dla którego konto nie wchodzi do sprawozdań porównawczych."""

    head = first_segment(number)
    if head.startswith(OFF_BALANCE_PREFIX):
        return "pozabilansowe"
    if head.startswith(COST_ALLOCATION_PREFIXES):
        return "rozliczenie kosztów (wariant kalkulacyjny)"
    return None


def parse(raw: Optional[str]) -> Optional[Pair]:
    """``report_line`` z bazy → para znaczników; śmieci → ``None``."""

    value = (raw or "").strip()
    if not value:
        return None
    parts = value.split("/")
    known = dictionary()
    if len(parts) > 2 or any(part not in known for part in parts):
        return None
    return _pair(parts[0], parts[1] if len(parts) == 2 else None)


def clean_report_line(raw: object) -> Optional[str]:
    """Wpis z formularza planu kont → ``KOD`` / ``KOD_Wn/KOD_Ma`` albo 422."""

    value = "".join(str(raw or "").split())
    if not value:
        return None
    if len(value) > REPORT_LINE_MAX:
        raise LedgerError("Pozycja sprawozdania jest za długa.", status=422)
    parts = value.split("/")
    known = dictionary()
    if len(parts) > 2 or not all(parts):
        raise LedgerError(
            "Pozycja sprawozdania to znacznik MF (np. RPBIII) albo para "
            "„znacznik salda Wn/znacznik salda Ma” (np. BABII3a_D12/BPBIII3d_D12).",
            status=422,
        )
    unknown = [part for part in parts if part not in known]
    if unknown:
        raise LedgerError(
            f"Nie ma znacznika {unknown[0]} w słowniku MF (JPK_KR_PD, jednostki pozostałe).",
            status=422,
        )
    if len(parts) == 2:
        groups = {known[part].group for part in parts}
        if not groups <= {GROUP_ASSETS, GROUP_LIABILITIES}:
            raise LedgerError(
                "Parę znaczników (saldo Wn/saldo Ma) ma tylko konto bilansowe.",
                status=422,
            )
        if parts[0] == parts[1]:
            return parts[0]
    return value


def rule_for(number: str) -> Optional[Pair]:
    head = first_segment(number)
    for size in range(len(head), 0, -1):
        rule = RULES.get(head[:size])
        if rule is not None:
            return rule
    return None


def candidates(number: str) -> list[str]:
    """``201-2-1000`` → ``["201-2-1000", "201-2", "201"]``."""

    parts = number.split("-")
    return ["-".join(parts[:size]) for size in range(len(parts), 0, -1)]


def resolve(
    number: str, own: Mapping[str, Optional[str]]
) -> tuple[Optional[Pair], str]:
    """Znacznik konta i skąd pochodzi (``own`` = report_line z planu kont)."""

    if excluded(number):
        return None, SOURCE_EXCLUDED
    for index, candidate in enumerate(candidates(number)):
        pair = parse(own.get(candidate))
        if pair is not None:
            return pair, SOURCE_OWN if index == 0 else SOURCE_PARENT
    rule = rule_for(number)
    if rule is not None:
        return rule, SOURCE_RULE
    return None, SOURCE_NONE


def describe(pair: Optional[Pair]) -> Optional[dict[str, object]]:
    if pair is None:
        return None
    known = dictionary()
    return {
        "text": pair.text,
        "debit": {"code": pair.debit, "label": known[pair.debit].label},
        "credit": {"code": pair.credit, "label": known[pair.credit].label},
    }


def catalogue() -> list[dict[str, str]]:
    """Słownik do wyboru na ekranie: kod, grupa, opis pozycji."""

    return [
        {"code": marker.code, "group": marker.group, "label": marker.label}
        for marker in dictionary().values()
    ]
