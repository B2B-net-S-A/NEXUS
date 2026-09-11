"""Dopasowanie osoby z PDF-a zamówienia do KONTRAKTU u klienta.

Okno „Nowe zamówienie" (09.2026) rozpoznaje wszystkich konsultantów z jednego
dokumentu i dla każdego szuka kontraktu u TEGO klienta. Reguła tolerancji jest
celowo wąska i opisana w tickecie:

* **rdzeń** imienia i nazwiska w kontrakcie to dwa OSTATNIE wyrazy pisane
  wielką literą; wszystko przed nim („Active", „UR –", „Projekt 2") to
  **dopisek**, nie część nazwiska;
* tolerowane różnice: dopisek przed rdzeniem oraz polskie znaki diakrytyczne
  („Goceł"/„Gocel", „Łukasz"/„Lukasz"); wielkość liter i myślnik zamiast
  spacji to formatowanie, nie litera;
* **każda inna różnica w rdzeniu** (inna litera, przestawione litery, inne
  imię) oznacza brak dopasowania. System NIGDY nie zgaduje ani nie koryguje
  literówek — dlatego ten moduł nie używa ``_osa_distance`` ani odmiany,
  z których korzysta resolver poczty (``order_mail_resolver``): tam trafienie
  „z literówką" idzie do kolejki, a tu zapisałoby cudzą stawkę jednym
  kliknięciem.

Wynik (odznaka w oknie):

* ``auto`` (zielona) — zapis identyczny, bez dopisków;
* ``confirm`` (żółta) — rdzeń się zgadza, ale był dopisek (albo odwrotna
  kolejność imienia i nazwiska) — jedno kliknięcie potwierdzenia;
* ``inactive`` — osoba jest w systemie, ale jej współpraca u tego klienta jest
  ZAKOŃCZONA (jedyny kontrakt jest zakończony). Nie jest to zgoda na
  wznowienie: Delivery Lead wybiera jawnie — zostawić ją na zamówieniu jako
  zapis historyczny, wznowić współpracę, zastąpić inną osobą albo usunąć
  z zamówienia (ticket 09.2026: zamówienie nie może „utknąć" bez informacji);
* ``ambiguous`` — u klienta pasuje więcej niż jedna osoba (1 kontrakt = 1 osoba
  u danego klienta) albo ta sama osoba ma kilka aktywnych kontraktów — system
  nie wybiera żadnego;
* ``none`` (czerwona) — różnica wykracza poza tolerancję albo brak dopasowania.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Optional

MATCH_AUTO = "auto"
MATCH_CONFIRM = "confirm"
MATCH_AMBIGUOUS = "ambiguous"
MATCH_INACTIVE = "inactive"
MATCH_NONE = "none"

_LIVE_STATUSES = frozenset({"active", "ending"})
_OPEN_STATUSES = frozenset({"active", "ending", "draft", "ready_for_signature"})
_ENDED_STATUS = "ended"

# Znaki formatujące z PDF-ów, które nie są granicą słowa.
_INVISIBLE = re.compile("[\u00ad\u200b\u200c\u200d\ufeff]")
# Myślniki (także typograficzne) — separator członów, nie litera.
_DASHES = re.compile("[\u2010-\u2015-]")
_EDGE_PUNCTUATION = re.compile(r"^[\W_]+|[\W_]+$")
_NEAREST_MIN_RATIO = 0.75
_NEAREST_LIMIT = 2


def raw_words(value: Optional[str]) -> list[str]:
    """Wyrazy w ORYGINALNEJ pisowni, bez interpunkcji na brzegach.

    Samotny myślnik („UR – Jan") znika, a myślnik wewnątrz nazwiska
    („Prus-Rudzińska") zostaje — to jeden wyraz.
    """

    cleaned = _INVISIBLE.sub("", value or "")
    words: list[str] = []
    for chunk in cleaned.split():
        word = _EDGE_PUNCTUATION.sub("", chunk)
        if word:
            words.append(word)
    return words


def _fold(word: str) -> str:
    """Wielkość liter i polskie znaki poza porównaniem — nic więcej."""

    folded = unicodedata.normalize("NFKD", word.casefold()).replace("ł", "l")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", folded)


def name_tokens(words: list[str]) -> tuple[str, ...]:
    """Tokeny porównania: myślnik jest separatorem, reszta po ``_fold``."""

    tokens: list[str] = []
    for word in words:
        for part in _DASHES.split(word):
            folded = _fold(part)
            if folded:
                tokens.append(folded)
    return tuple(tokens)


@dataclass(frozen=True)
class NameParts:
    """Imię i nazwisko rozłożone na dopisek i rdzeń."""

    prefix: str
    core: tuple[str, ...]
    full: tuple[str, ...]


def split_name(value: Optional[str]) -> NameParts:
    """Rdzeń = od przedostatniego wyrazu pisanego wielką literą do końca.

    „Active Jan Kowalski" → dopisek „Active", rdzeń „Jan Kowalski".
    Gdy wyrazów z wielkiej litery jest mniej niż dwa, rdzeń jest całym zapisem
    (bez dopisku) — nie ma na czym oprzeć podziału.
    """

    words = raw_words(value)
    capitalized = [index for index, word in enumerate(words) if word[:1].isupper()]
    if len(capitalized) < 2:
        tokens = name_tokens(words)
        return NameParts(prefix="", core=tokens, full=tokens)
    start = capitalized[-2]
    return NameParts(
        prefix=" ".join(words[:start]),
        core=name_tokens(words[start:]),
        full=name_tokens(words),
    )


@dataclass(frozen=True)
class NameMatch:
    level: str
    #: Dopisek przed rdzeniem w kontrakcie (albo w dokumencie).
    contract_prefix: str = ""
    document_prefix: str = ""
    reversed_order: bool = False

    @property
    def reason(self) -> str:
        parts: list[str] = []
        if self.contract_prefix:
            parts.append(
                f"W kontrakcie przed imieniem i nazwiskiem jest dopisek "
                f"„{self.contract_prefix}” — rdzeń nazwy się zgadza"
            )
        if self.document_prefix:
            parts.append(
                f"W dokumencie przed imieniem i nazwiskiem jest dopisek "
                f"„{self.document_prefix}” — rdzeń nazwy się zgadza"
            )
        if self.reversed_order:
            parts.append("Imię i nazwisko zapisano w odwrotnej kolejności")
        if not parts:
            return "Zapis identyczny z dokumentem"
        return "; ".join(parts) + " — potwierdź, że to ta sama osoba"


def match_names(
    document_name: Optional[str], contractor_name: Optional[str]
) -> Optional[NameMatch]:
    """Porównaj osobę z dokumentu z nazwą kontraktora. ``None`` = inna osoba."""

    document = split_name(document_name)
    contract = split_name(contractor_name)
    if len(document.full) < 2 or len(contract.full) < 2:
        return None
    if document.full == contract.full:
        return NameMatch(level=MATCH_AUTO)

    variants = (
        (document.full, "", contract.full, ""),
        (document.full, "", contract.core, contract.prefix),
        (document.core, document.prefix, contract.full, ""),
        (document.core, document.prefix, contract.core, contract.prefix),
    )
    for doc_tokens, doc_prefix, contract_tokens, contract_prefix in variants:
        if len(doc_tokens) < 2 or len(contract_tokens) < 2:
            continue
        same_order = doc_tokens == contract_tokens
        if not same_order and sorted(doc_tokens) != sorted(contract_tokens):
            continue
        return NameMatch(
            level=MATCH_CONFIRM,
            contract_prefix=contract_prefix,
            document_prefix=doc_prefix,
            reversed_order=not same_order,
        )
    return None


@dataclass(frozen=True)
class ContractCandidate:
    """Kontrakt u klienta z nazwą kontraktora — materiał do dopasowania."""

    contract_id: int
    candidate_id: int
    contractor_name: str
    status: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None


@dataclass(frozen=True)
class ContractMatch:
    """Wynik dopasowania jednej osoby z dokumentu."""

    status: str
    reason: str
    contract: Optional[ContractCandidate] = None
    name_match: Optional[NameMatch] = None
    #: Kontrakty do ręcznego wyboru (``ambiguous``).
    options: tuple[ContractCandidate, ...] = ()
    #: Podpowiedź przy braku dopasowania — NIGDY nie jest wybierana sama.
    nearest: tuple[ContractCandidate, ...] = field(default_factory=tuple)


def _recency(contract: ContractCandidate) -> tuple[date, date, int]:
    return (
        contract.end_date or date.max,
        contract.start_date or date.min,
        contract.contract_id,
    )


def _nearest(
    document_name: Optional[str], contracts: list[ContractCandidate]
) -> tuple[ContractCandidate, ...]:
    """Najbliższe zapisy — wyłącznie jako tekst podpowiedzi przy czerwonej karcie."""

    document = " ".join(split_name(document_name).core)
    if not document:
        return ()
    scored: list[tuple[float, ContractCandidate]] = []
    seen: set[int] = set()
    for contract in contracts:
        if contract.candidate_id in seen:
            continue
        parts = split_name(contract.contractor_name)
        ratio = max(
            SequenceMatcher(None, document, " ".join(parts.core)).ratio(),
            SequenceMatcher(None, document, " ".join(parts.full)).ratio(),
        )
        if ratio >= _NEAREST_MIN_RATIO:
            seen.add(contract.candidate_id)
            scored.append((ratio, contract))
    scored.sort(key=lambda item: (-item[0], item[1].contract_id))
    return tuple(contract for _, contract in scored[:_NEAREST_LIMIT])


def _describe_options(options: list[ContractCandidate]) -> str:
    return "; ".join(
        f"kontrakt #{option.contract_id}"
        + (f" od {option.start_date.isoformat()}" if option.start_date else "")
        for option in options
    )


def resolve_contract(
    document_name: Optional[str], contracts: list[ContractCandidate]
) -> ContractMatch:
    """Wybierz dokładnie jeden kontrakt tej osoby albo powiedz, dlaczego nie.

    Kolejność puli: kontrakty żywe i szkice (osoba pracuje albo właśnie
    zaczyna), dopiero bez nich — zakończone (powrót po przerwie; zamówienie
    wznowi kontrakt). Dwie RÓŻNE osoby o tym samym imieniu i nazwisku u klienta
    nigdy nie są rozstrzygane automatycznie — także wtedy, gdy jedna ma
    kontrakt aktywny, a druga szkic albo zakończony kontrakt.
    """

    if len(split_name(document_name).full) < 2:
        return ContractMatch(
            status=MATCH_NONE,
            reason="Dokument nie podaje imienia i nazwiska tej pozycji — wskaż kontraktora ręcznie",
        )

    matched = [
        (contract, name_match)
        for contract in contracts
        if (name_match := match_names(document_name, contract.contractor_name))
        is not None
    ]
    open_matches = [item for item in matched if item[0].status in _OPEN_STATUSES]
    ended = [item for item in matched if item[0].status == _ENDED_STATUS]

    # „1 kontrakt = 1 osoba u klienta": dwie RÓŻNE osoby o tym imieniu
    # i nazwisku to zawsze decyzja człowieka — także gdy druga ma dziś tylko
    # zakończony kontrakt (wraca po przerwie i PDF może dotyczyć właśnie jej).
    candidate_ids = {contract.candidate_id for contract, _ in open_matches + ended}
    if len(candidate_ids) > 1:
        with_open = {contract.candidate_id for contract, _ in open_matches}
        latest_ended: dict[int, ContractCandidate] = {}
        for contract, _ in ended:
            if contract.candidate_id in with_open:
                continue
            current = latest_ended.get(contract.candidate_id)
            if current is None or _recency(contract) > _recency(current):
                latest_ended[contract.candidate_id] = contract
        options = sorted(
            [contract for contract, _ in open_matches] + list(latest_ended.values()),
            key=_recency,
        )
        return ContractMatch(
            status=MATCH_AMBIGUOUS,
            reason=(
                f"Znaleziono {len(candidate_ids)} różne osoby o tym imieniu "
                "i nazwisku u tego klienta — system nie zgaduje, wskaż "
                "właściwą osobę po numerze kontraktu lub dacie rozpoczęcia"
            ),
            options=tuple(options),
        )

    if open_matches:
        live = [item for item in open_matches if item[0].status in _LIVE_STATUSES]
        pool = live or open_matches
        if len(pool) > 1:
            return ContractMatch(
                status=MATCH_AMBIGUOUS,
                reason=(
                    f"Ta osoba ma {len(pool)} "
                    + ("aktywne kontrakty" if live else "szkice kontraktów")
                    + " u tego klienta ("
                    + _describe_options(sorted((c for c, _ in pool), key=_recency))
                    + ") — wskaż właściwy"
                ),
                options=tuple(sorted((c for c, _ in pool), key=_recency)),
            )
        contract, name_match = pool[0]
        reason = name_match.reason
        if contract.status not in _LIVE_STATUSES:
            reason += "; kontrakt nie jest jeszcze aktywny (szkic)"
        return ContractMatch(
            status=name_match.level,
            reason=reason,
            contract=contract,
            name_match=name_match,
        )

    if ended:
        contract, name_match = max(ended, key=lambda item: _recency(item[0]))
        # Różnica zapisu (dopisek, kolejność) jest informacją, nie pytaniem —
        # decyzję i tak podejmuje się przyciskami karty, więc bez „potwierdź".
        prefix = (
            name_match.reason.removesuffix(" — potwierdź, że to ta sama osoba")
            if name_match.level == MATCH_CONFIRM
            else ""
        )
        ended_on = (
            f" (kontrakt zakończony {contract.end_date.strftime('%d.%m.%Y')})"
            if contract.end_date
            else " (kontrakt zakończony)"
        )
        return ContractMatch(
            status=MATCH_INACTIVE,
            reason=(
                (prefix + "; " if prefix else "")
                + f"{_display(document_name)} nie ma już aktywnej współpracy u tego "
                f"klienta{ended_on}. Zdecyduj: zostaw tę osobę na zamówieniu jako "
                "zapis historyczny, wznów współpracę, zastąp ją inną osobą albo "
                "usuń z zamówienia"
            ),
            contract=contract,
            name_match=name_match,
        )

    nearest = _nearest(document_name, contracts)
    reason = (
        f"Nie znaleziono {_display(document_name)} w systemie — brak kontraktu "
        "z tym imieniem i nazwiskiem u tego klienta (system nie koryguje "
        "literówek ani nie zgaduje podobieństwa). Wskaż tę osobę ręcznie, "
        "zastąp ją kimś innym albo usuń z zamówienia"
    )
    return ContractMatch(status=MATCH_NONE, reason=reason, nearest=nearest)


def _display(document_name: Optional[str]) -> str:
    """Nazwa osoby z dokumentu do komunikatu — dokładnie tak, jak w PDF-ie."""

    name = " ".join(raw_words(document_name))
    return f"„{name}”" if name else "tej osoby"
