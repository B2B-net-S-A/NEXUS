"""Czyste reguły robota: konta, nazwiska, wiersze list Cpro. Bez przeglądarki."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

# Muszą być równe ``app.services.cpro_bot.accounts`` (pilnuje test).
IGOR_HINT = "Nordea Cpro – Igor"
MARCIN_HINT = "Nordea Cpro – Marcin"
# Delivery Lead rekrutacji → wpis konta (Dominik, 32, używa konta Marcina).
ACCOUNT_BY_DL = {
    14: (IGOR_HINT, "IGOR"),
    27: (MARCIN_HINT, "MARCIN"),
    32: (MARCIN_HINT, "MARCIN"),
}

SUBCONTRACTOR_COMPANY = "B2B.net S.A."


@dataclass(frozen=True)
class Account:
    key: str  # IGOR / MARCIN — przyrostek zmiennych środowiskowych
    username: str
    password: str
    display_name: str  # podpis konta w bocznym pasku Cpro (``.vmsSideBarProfileUser``)


class AccountProblem(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def account_for(cpro_account: object, env: Mapping[str, str] = os.environ) -> Account:
    """Konto z pozycji zlecenia; tylko DL z listy i zgodny wpis. Bez zgadywania."""

    if not isinstance(cpro_account, dict):
        raise AccountProblem("account_unknown", "Zlecenie bez konta Cpro.")
    dl_id = cpro_account.get("delivery_lead_id")
    route = ACCOUNT_BY_DL.get(dl_id) if isinstance(dl_id, int) else None
    if route is None or cpro_account.get("vault_entry") != route[0]:
        raise AccountProblem(
            "account_unknown", "Nieobsługiwany Delivery Lead albo wpis konta."
        )
    key = route[1]
    values = [
        env.get(f"CPRO_ROBOT_{key}_{part}", "").strip()
        for part in ("USERNAME", "PASSWORD", "DISPLAY_NAME")
    ]
    if not all(values):
        raise AccountProblem(
            "account_unknown", f"Robot nie ma danych konta {key.title()}."
        )
    return Account(key, *values)


def norm(text: Optional[str]) -> str:
    """Porównanie nazw: bez wielkości liter, ogonków, nadmiarowych spacji i przecinków."""

    text = unicodedata.normalize("NFKD", text or "")
    text = (
        "".join(ch for ch in text if not unicodedata.combining(ch))
        .replace("ł", "l")
        .replace("Ł", "L")
    )
    return " ".join(re.sub(r"[, ]", " ", text).split()).casefold()


def same_person(cell: str, first_name: str, last_name: str) -> bool:
    return norm(cell) == norm(f"{first_name} {last_name}")


@dataclass(frozen=True)
class OfferRow:
    offer_id: Optional[int]
    request_number: str
    profile: str
    status: str  # pierwsza kolumna statusu oferty, np. DRAFT, Selection, Rejected : Competence


_REQ = re.compile(r"^\s*(\d{4,7})\b")
_OFFER_ID = re.compile(r"[?&]id=(\d+)")


def offer_row(cells: Sequence[str], view_href: Optional[str]) -> Optional[OfferRow]:
    """Wiersz listy ``OfferController`` (Offer|Offer date|Customer|Request|Profile|…|Status|Status)."""

    if len(cells) < 8:
        return None
    req = _REQ.match(cells[3] or "")
    if not req:
        return None
    match = _OFFER_ID.search(view_href or "")
    return OfferRow(
        int(match.group(1)) if match else None,
        req.group(1),
        cells[4].strip(),
        cells[7].strip(),
    )


def offers_of(
    rows: Sequence[OfferRow], request_number: str, first_name: str, last_name: str
) -> list[OfferRow]:
    return [
        r
        for r in rows
        if r.request_number == request_number
        and same_person(r.profile, first_name, last_name)
    ]


def is_draft(row: OfferRow) -> bool:
    return norm(row.status) == "draft"


# Narodowość z karty NEXUSA jest po polsku („Amerykanin”, „ukraińskie”), lista
# Cpro ma „US - USA”. Początek słowa (po ``norm``) → kod ISO z listy Cpro.
# Kolejność ma znaczenie: dłuższe i bardziej szczegółowe początki najpierw.
_NATIONALITY_STEMS: tuple[tuple[str, str], ...] = (
    ("polak", "PL"),
    ("polka", "PL"),
    ("polsk", "PL"),
    ("polish", "PL"),
    ("ukrain", "UA"),
    ("bialorus", "BY"),
    ("belarus", "BY"),
    ("amerykan", "US"),
    ("american", "US"),
    ("usa", "US"),
    ("brytyj", "GB"),
    ("british", "GB"),
    ("anglik", "GB"),
    ("angielk", "GB"),
    ("angiel", "GB"),
    ("szkot", "GB"),
    ("walij", "GB"),
    ("niemiec", "DE"),
    ("niemk", "DE"),
    ("niemieck", "DE"),
    ("german", "DE"),
    ("hindus", "IN"),
    ("indyj", "IN"),
    ("indian", "IN"),
    ("rosjan", "RU"),
    ("rosyj", "RU"),
    ("russian", "RU"),
    ("gruzi", "GE"),
    ("gruzin", "GE"),
    ("ormian", "AM"),
    ("armen", "AM"),
    ("turek", "TR"),
    ("turczyn", "TR"),
    ("turec", "TR"),
    ("turkish", "TR"),
    ("hiszpa", "ES"),
    ("spanish", "ES"),
    ("wloch", "IT"),
    ("wlosk", "IT"),
    ("wloszk", "IT"),
    ("italian", "IT"),
    ("francu", "FR"),
    ("french", "FR"),
    ("czech", "CZ"),
    ("czesk", "CZ"),
    ("czeszk", "CZ"),
    ("slowa", "SK"),
    ("slovak", "SK"),
    ("litwin", "LT"),
    ("litew", "LT"),
    ("lotysz", "LV"),
    ("lotew", "LV"),
    ("estonczyk", "EE"),
    ("estonk", "EE"),
    ("estons", "EE"),
    ("rumun", "RO"),
    ("romanian", "RO"),
    ("wegier", "HU"),
    ("wegiersk", "HU"),
    ("wegierk", "HU"),
    ("bulgar", "BG"),
    ("serb", "RS"),
    ("chorwa", "HR"),
    ("portugal", "PT"),
    ("holend", "NL"),
    ("niderland", "NL"),
    ("dutch", "NL"),
    ("belg", "BE"),
    ("szwed", "SE"),
    ("szwedz", "SE"),
    ("norweg", "NO"),
    ("norwes", "NO"),
    ("dunczyk", "DK"),
    ("dunk", "DK"),
    ("dunsk", "DK"),
    ("danish", "DK"),
    ("finka", "FI"),
    ("finsk", "FI"),
    ("finn", "FI"),
    ("kazach", "KZ"),
    ("uzbek", "UZ"),
    ("azer", "AZ"),
    ("moldaw", "MD"),
    ("egipcj", "EG"),
    ("egips", "EG"),
    ("nigeryj", "NG"),
    ("brazyl", "BR"),
    ("meksyk", "MX"),
    ("kanadyj", "CA"),
    ("canadian", "CA"),
    ("chinczyk", "CN"),
    ("chinsk", "CN"),
    ("chinese", "CN"),
    ("wietnam", "VN"),
    ("pakista", "PK"),
    ("irland", "IE"),
    ("irish", "IE"),
    ("izrael", "IL"),
    ("austriac", "AT"),
    ("austriak", "AT"),
    ("szwajcar", "CH"),
    ("grek", "GR"),
    ("greczyn", "GR"),
    ("greck", "GR"),
)


def nationality_code(text: str) -> Optional[str]:
    """Kod kraju dla polskiej (albo angielskiej) nazwy narodowości; inaczej ``None``."""

    words = norm(text).split()
    if not words:
        return None
    word = words[0]
    for stem, code in _NATIONALITY_STEMS:
        if word.startswith(stem):
            return code.casefold()
    return None


def country_option(
    options: Sequence[tuple[str, str]], citizenship: str
) -> Optional[str]:
    """Wartość opcji „Country of citizenship” (``PL - Poland``) dla nazwy kraju albo kodu.

    Dokładna nazwa po myślniku, potem kod ISO; nic niejednoznacznego.
    """

    want = norm(citizenship)
    if not want:
        return None
    want = nationality_code(want) or want
    by_name, by_code = [], []
    for value, label in options:
        if not value or value == "0":
            continue
        code, _, name = label.partition(" - ")
        if norm(name or label) == want or norm(label) == want:
            by_name.append(value)
        elif norm(code) == want:
            by_code.append(value)
    hits = by_name or by_code
    return hits[0] if len(hits) == 1 else None


def cv_label_matches(label: str, file_name: str) -> bool:
    """Podpis CV w ofercie to nazwa pliku (z końcówką albo bez)."""

    base = re.sub(r"\.pdf$", "", file_name.strip(), flags=re.IGNORECASE)
    return norm(re.sub(r"\.pdf$", "", label.strip(), flags=re.IGNORECASE)) == norm(base)


def former_from_cv_text(text: str) -> Optional[tuple[bool, bool]]:
    """``(consultant, employee)`` z treści CV, gdy karta nie rozstrzyga.

    Brak Nordei w CV → oba „No”. Nordea w CV → nie da się bezpiecznie odróżnić
    pracownika od konsultanta: ``None`` (rozstrzyga człowiek).
    """

    return (
        None
        if re.search(r"\bnordea\b", text or "", flags=re.IGNORECASE)
        else (False, False)
    )


CLOSED_STATUSES = ("closed", "cancelled", "canceled")


def request_closed(header_text: str) -> bool:
    words = norm(header_text)
    return any(re.search(rf"\b{s}\b", words) for s in CLOSED_STATUSES)


def rate_label(rate: object) -> str:
    """Stawka tak, jak pokazuje ją widok oferty: ``196,00``."""

    return f"{float(str(rate).replace(',', '.')):.2f}".replace(".", ",")


def saved_values_visible(view_text: str, rate: object, available_from: str) -> bool:
    """Widok zapisanej oferty pokazuje stawkę i datę ze zlecenia."""

    return rate_label(rate) in (view_text or "") and available_from in (view_text or "")
