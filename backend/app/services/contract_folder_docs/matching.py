"""Folder „Nazwisko Imię” ↔ kontrakt w NEXUSIE (ticket 9, 29.09.2026).

Punktem wyjścia jest NEXUS: dla osoby z kontraktu szukamy jej podfolderu, nigdy
odwrotnie — folder bez kontraktu nie zakłada niczego. Ta sama funkcja wybiera
folder przy wysyłce dokumentu z NEXUSA na SharePoint, więc oba kierunki
rozumieją nazwisko identycznie.

Nazwę dzielimy na słowa (spacja i myślnik — „Nowak-Kowalska Anna” i „Nowak
Kowalska Anna” to te same trzy słowa) i porównujemy ZBIORY po złożeniu
polskich znaków, więc kolejność „Nazwisko Imię” / „Imię Nazwisko” nie ma
znaczenia. Wynik:

* ``sure`` — te same słowa, zapisane identycznie,
* ``uncertain`` — jedyny pasujący folder, ale z różnicą, którą człowiek ma
  zobaczyć (polskie znaki, drugie imię / człon nazwiska, literówka),
* ``ambiguous`` — pasuje kilka folderów; nie zgadujemy,
* ``none`` — nic nie pasuje,
* ``excluded`` — Filip Jabłoński (dwie różne osoby o tym nazwisku; dokumenty
  dodaje człowiek, decyzja z ticketu).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.services.contract_folder_docs.classify import fold

SURE = "sure"
UNCERTAIN = "uncertain"
AMBIGUOUS = "ambiguous"
NONE = "none"
EXCLUDED = "excluded"

# Kody powodów niepewności — front tłumaczy je na zdania.
REASON_DIACRITICS = "diacritics"
REASON_PARTIAL = "partial_name"
REASON_TYPO = "typo"
REASON_SAME_NAME_PEOPLE = "same_name_people"
REASON_MULTIPLE_FOLDERS = "multiple_folders"

_SPLIT_RE = re.compile(r"[\s\-‐‑–—_]+")
_NON_ALNUM_RE = re.compile(r"[^\w]+", re.UNICODE)
_FILIP_JABLONSKI = frozenset({"filip", "jablonski"})


def _raw_word(word: str) -> str:
    """Słowo bez interpunkcji, z polskimi znakami (do wykrycia różnicy w ogonkach)."""
    return _NON_ALNUM_RE.sub("", unicodedata.normalize("NFC", word).casefold()).replace(
        "_", ""
    )


def _folded_word(word: str) -> str:
    return _NON_ALNUM_RE.sub("", fold(word)).replace("_", "")


def name_words(text: str | None) -> tuple[frozenset[str], frozenset[str]]:
    """(słowa złożone, słowa z polskimi znakami)."""
    parts = [p for p in _SPLIT_RE.split((text or "").strip()) if p]
    folded = frozenset(w for p in parts if (w := _folded_word(p)))
    raw = frozenset(w for p in parts if (w := _raw_word(p)))
    return folded, raw


def is_excluded_person(first: str | None, last: str | None) -> bool:
    folded, _ = name_words(f"{first or ''} {last or ''}")
    return folded == _FILIP_JABLONSKI


def is_excluded_folder(name: str | None) -> bool:
    folded, _ = name_words(name)
    return folded == _FILIP_JABLONSKI


@dataclass(frozen=True)
class Folder:
    """Podfolder osoby na SharePoincie (albo w podglądzie)."""

    name: str
    item_id: str | None = None
    folded: frozenset[str] = field(default_factory=frozenset)
    raw: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def of(cls, name: str, item_id: str | None = None) -> "Folder":
        folded, raw = name_words(name)
        return cls(name=name, item_id=item_id, folded=folded, raw=raw)


@dataclass(frozen=True)
class FolderMatch:
    kind: str
    folder: Folder | None = None
    reasons: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()  # nazwy folderów przy ``ambiguous``


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    edits = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(a) == len(b):
            i += 1
        j += 1
    return edits + (len(b) - j) + (len(a) - i) <= 1


def _typo_match(person: frozenset[str], folder: frozenset[str]) -> bool:
    """Te same słowa, z jedną literówką w jednym słowie (≥ 4 litery)."""
    if len(person) != len(folder) or len(person) < 2:
        return False
    only_person = person - folder
    only_folder = folder - person
    if len(only_person) != 1 or len(only_folder) != 1:
        return False
    a, b = next(iter(only_person)), next(iter(only_folder))
    return min(len(a), len(b)) >= 4 and _edit_distance_at_most_one(a, b)


def _partial_match(person: frozenset[str], folder: frozenset[str]) -> bool:
    """Drugie imię albo drugi człon nazwiska tylko po jednej stronie."""
    if person == folder:
        return False
    common = person & folder
    return len(common) >= 2 and (person <= folder or folder <= person)


def match_person(
    first: str | None, last: str | None, folders: Sequence[Folder]
) -> FolderMatch:
    """Najlepszy podfolder dla osoby z kontraktu."""
    if is_excluded_person(first, last):
        return FolderMatch(EXCLUDED)
    person, person_raw = name_words(f"{first or ''} {last or ''}")
    if len(person) < 2:
        return FolderMatch(NONE)

    def pick(hits: list[Folder], reason: str | None) -> FolderMatch | None:
        if not hits:
            return None
        if len(hits) > 1:
            return FolderMatch(
                AMBIGUOUS,
                reasons=(REASON_MULTIPLE_FOLDERS,),
                candidates=tuple(sorted(f.name for f in hits)),
            )
        folder = hits[0]
        if reason is None:
            if folder.raw == person_raw:
                return FolderMatch(SURE, folder)
            return FolderMatch(UNCERTAIN, folder, (REASON_DIACRITICS,))
        return FolderMatch(UNCERTAIN, folder, (reason,))

    for hits, reason in (
        ([f for f in folders if f.folded == person], None),
        ([f for f in folders if _partial_match(person, f.folded)], REASON_PARTIAL),
        ([f for f in folders if _typo_match(person, f.folded)], REASON_TYPO),
    ):
        result = pick(hits, reason)
        if result is not None:
            return result
    return FolderMatch(NONE)


@dataclass(frozen=True)
class ContractPerson:
    contract_id: int
    candidate_id: int | None
    first: str
    last: str


@dataclass(frozen=True)
class ContractMatch:
    contract: ContractPerson
    match: FolderMatch


def match_contracts(
    contracts: Iterable[ContractPerson], folders: Sequence[Folder]
) -> list[ContractMatch]:
    """Dopasowanie każdego kontraktu. Osoba z kilkoma kontraktami dostaje ten
    sam folder przy każdym z nich (ticket, pkt 3).

    Gdy jeden folder przypada kilku RÓŻNYM rekordom kandydata (dwie osoby
    o tym samym nazwisku albo zdublowany rekord), przypisanie zostaje, ale
    trafia na listę do weryfikacji.
    """
    results = [
        ContractMatch(c, match_person(c.first, c.last, folders)) for c in contracts
    ]
    candidates_per_folder: dict[str, set[int | None]] = {}
    for result in results:
        if result.match.folder is not None:
            candidates_per_folder.setdefault(result.match.folder.name, set()).add(
                result.contract.candidate_id
            )
    adjusted: list[ContractMatch] = []
    for result in results:
        folder = result.match.folder
        if folder is not None and len(candidates_per_folder[folder.name]) > 1:
            reasons = tuple(
                dict.fromkeys((*result.match.reasons, REASON_SAME_NAME_PEOPLE))
            )
            result = ContractMatch(
                result.contract, FolderMatch(UNCERTAIN, folder, reasons)
            )
        adjusted.append(result)
    return adjusted


def folder_display_name(first: str | None, last: str | None) -> str:
    """Nazwa nowego podfolderu przy wysyłce z NEXUSA: „Nazwisko Imię”."""
    return " ".join(p.strip() for p in (last or "", first or "") if p and p.strip())
