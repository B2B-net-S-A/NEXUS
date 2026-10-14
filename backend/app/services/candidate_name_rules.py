"""Imię i nazwisko bez dopisków — jedna reguła dla każdej ścieżki (D6, 13.10.2026).

Traffit nie miał pól „zatrudniony”, „czarna lista” ani „szuka aktywnie”, więc
rekruterzy wklejali je w imię: „[ACTIVE] Jan”, „Nowak (zaakceptowany)”,
„(czarna lista) Piotr”. W NEXUSIE każda z tych informacji ma swoje miejsce
(Dostępność, Status, zatrudnienie liczone z umowy), a dopisek w imieniu psuje
wyszukiwanie, sortowanie, nagłówki CV i maile do kandydata.

Dopisek to:

- segment w nawiasie ``[...]`` albo ``(...)``, którego treść NIE jest jednym
  słowem-nazwiskiem z wielkiej litery (``Kowalska``, ``Kowalska-Nowak``) —
  „Anna (Kowalska)” to drugie nazwisko i zostaje — ALBO jest słowem statusu
  (także „(Active)”, „(Zatrudniony)”);
- słowo statusu przy nawiasie/ukośniku bez pary („/ ACTIVE] Jan”,
  „[active / Jan”) — zapis z Traffita z 18.08.2026;
- ``zatrudnion*`` w dowolnym miejscu (reguła z 0165);
- słowo statusu bez nawiasu wyłącznie na KRAWĘDZI pola („ACTIVE Jan”,
  „Kowalski passive”); samo „Active” i „Activision” zostają.

Z tej samej funkcji korzystają: mapper Traffita (import nie przywróci tego,
co zdjęła migracja 0436), odmowa 422 przy ręcznym wpisie, zdejmowanie na
ścieżkach automatycznych i sama migracja 0436.

Grupy w wyrażeniach są ZWYKŁE ``(...)``, nie ``(?:...)`` — starsze migracje
(0165, 0232) wykonywały lustra tych wzorców przez SQLAlchemy ``text()``, które
czyta ``:`` w ``(?:`` jako parametr bindowany.
"""

from __future__ import annotations

import re
from typing import Optional

NAME_MARKER_ERROR_TYPE = "candidate_name_marker"
# Nazwy pól jak w oknach „Dodaj kandydata” / „Edytuj dane” (AppShell). Pole
# „Dostępność” jest tam datą — zdanie kierowało do niego „szuka aktywnie”
# (audyt 13.10.2026).
_NAME_MARKER_MESSAGE = (
    "Imię i nazwisko bez dopisków w nawiasie. „Szuka aktywnie” ustaw w polu "
    "Dyspozycyjność („Aktywnie szuka pracy”), czarną listę — w polu Status "
    "(„Zablokowany”); zatrudnienie widać samo z umowy."
)


# Imię i nazwisko mają w bazie po 100 znaków. Dłuższej wartości nie skanujemy:
# wzorce z opcjonalnym `\s*` na początku są kwadratowe na długim ciągu spacji
# albo separatorów (20 000 spacji = ok. 30 s zablokowanej pętli zdarzeń),
# a import zbiorczy i CSV wołają regułę PRZED walidacją długości — taka
# wartość i tak odpada dalej na limicie pola.
MAX_SCANNED_NAME_LENGTH = 200


def name_marker_message() -> str:
    """Zdanie dla użytkownika przy odmowie zapisu imienia z dopiskiem."""
    return _NAME_MARKER_MESSAGE


# ── Rodzina słów statusu ────────────────────────────────────────────────────

_LETTER = r"A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_TAIL = r"[a-ząćęłńóśźż]*"

# Dłuższe warianty wyprzedzają ``active`` / ``aktywny``; granice literowe
# blokują trafienie ``active`` w ``[inactive]`` i w nazwisku ``Inactivewicz``.
# „akcept” = „zaakceptowany przez klienta” (ustalenie z Arturem); od
# 13.10.2026 rodzina obejmuje też „zaakceptowany”, „ekspracownik”,
# „były pracownik” i „czarna lista” — warianty z produkcji.
_STATUS_WORD_ALTERNATIVES = "|".join(
    (
        r"black\s*-?\s*list",
        r"czarn" + _TAIL + r"\s+list" + _TAIL,
        r"nieaktywn[yaei]",
        r"inactive",
        r"aktywn[yaei]",
        r"passive",
        r"active",
        r"zatrudnion(ego|ej|ych|ymi|[yaieą])?",
        r"zatrunion(ego|ej|ych|ymi|[yaieą])?",
        r"zaakceptowan" + _TAIL,
        r"akcept" + _TAIL,
        r"(eks|ex)\s*-?\s*pracowni[kc]" + _TAIL,
        r"by[łl]" + _TAIL + r"\s+pracowni[kc]" + _TAIL,
    )
)
_STATUS_MARKER_WORD = (
    r"(?<![" + _LETTER + r"])(" + _STATUS_WORD_ALTERNATIVES + r")(?![" + _LETTER + r"])"
)
_STATUS_WORD_ONLY_RE = re.compile(
    r"\A\s*(" + _STATUS_WORD_ALTERNATIVES + r")\s*\Z", re.IGNORECASE
)

# Słowo statusu przy ograniczniku bez pary: „/ ACTIVE] Jan”, „[active / Jan”.
# Ogranicznik jest WYMAGANY przynajmniej z jednej strony — samo „active” mogłoby
# być częścią nazwiska. `[\[(/]` i `[\])/]` to klasy znaków: otwierające
# i zamykające nawiasy albo ukośnik.
_STATUS_MARKER_RE = re.compile(
    r"[\[(/]\s*" + _STATUS_MARKER_WORD + r"\s*[\])/]?"
    r"|"
    r"[\[(/]?\s*" + _STATUS_MARKER_WORD + r"\s*[\])/]",
    re.IGNORECASE,
)

# Legacy „[zatrudniony]” (0165): forma w nawiasie, w okrągłym nawiasie i goła,
# w dowolnym miejscu pola. Dłuższe końcówki najpierw — alternatywa jest
# uporządkowana, więc samo „e” nie może wygrać z „ego”/„ej”.
_EMPLOYMENT_MARKER_RE = re.compile(
    r"[\[(]?\s*zatrudnion(ego|ej|ych|ymi|[yaieą])?\s*[\])]?",
    re.IGNORECASE,
)

# Bez nawiasu tylko pełny token na POCZĄTKU albo KOŃCU pola, z separatorem
# od reszty — „Activision” i „Inactivewicz” to prawdziwy tekst. ``zatrunion*``
# to zaobserwowana literówka rodziny ``zatrudnion*``.
_BARE_EDGE_MARKER_WORD = (
    r"(active|aktywny|inactive|nieaktywny|passive|"
    r"zatrunion(ego|ej|ych|ymi|[yaieą])?)"
)
_BARE_EDGE_SEPARATOR = r"(\s+|\s*[-–,;/]+\s*)"
_BARE_EDGE_PREFIX_RE = re.compile(
    r"^\s*(?P<marker>" + _BARE_EDGE_MARKER_WORD + r")" + _BARE_EDGE_SEPARATOR,
    re.IGNORECASE,
)
_BARE_EDGE_SUFFIX_RE = re.compile(
    _BARE_EDGE_SEPARATOR + r"(?P<marker>" + _BARE_EDGE_MARKER_WORD + r")\s*$",
    re.IGNORECASE,
)

# Pełna para nawiasów bez zagnieżdżenia; zagnieżdżone schodzą od środka
# w kolejnych przebiegach `_strip_bracket_segments`.
_BRACKET_SEGMENT_RE = re.compile(r"\[([^\[\]()]*)\]|\(([^\[\]()]*)\)")

# Wykrywanie czarnej listy decyduje o `status`, więc ogranicznik jest WYMAGANY
# dokładnie jak przy zdejmowaniu — bez niego nazwisko „Blacklista” dawało
# ciche wykluczenie realnej osoby z propozycji (złapane na teście migracji 0232).
_BLACKLIST_ONLY = r"(black\s*-?\s*list|czarn" + _TAIL + r"\s+list" + _TAIL + r")"
_BLACKLIST_WORD_RE = re.compile(
    r"[\[(/]\s*" + _BLACKLIST_ONLY + r"\s*[\])/]?"
    r"|"
    r"[\[(/]?\s*" + _BLACKLIST_ONLY + r"\s*[\])/]",
    re.IGNORECASE,
)
# Wewnątrz ZDJĘTEGO dopisku ogranicznik już był (nawias z kilkoma słowami:
# „(dodany do czarnej listy przez klienta)”), więc wystarcza słowo. Do
# 14.10.2026 taki nawias znikał z imienia, a status zostawał „aktywny”.
_BLACKLIST_IN_MARKER_RE = re.compile(
    r"(?<![" + _LETTER + r"])" + _BLACKLIST_ONLY, re.IGNORECASE
)

# „Szuka aktywnie” — granica literowa odcina „inactive” i „nieaktywny”.
_ACTIVE_WORD_RE = re.compile(
    r"(?<![" + _LETTER + r"])(active|aktywn" + _TAIL + r")(?![" + _LETTER + r"])",
    re.IGNORECASE,
)
# „(nie aktywny)”, „[not active]”, „(non-active)” to zaprzeczenie — przed
# 14.10.2026 dawały „szuka aktywnie”.
_NEGATED_ACTIVE_RE = re.compile(
    r"(?<![" + _LETTER + r"])(nie|not|non|no)[\s\-]*(active|aktywn" + _TAIL + r")",
    re.IGNORECASE,
)


# ── Pomocnicze ──────────────────────────────────────────────────────────────


def _normalize_name_marker_spacing(value: str) -> str:
    """Zwiń odstępy i osierocone separatory po zdjęciu dopisku."""
    return re.sub(r"\s{2,}", " ", value).strip(" -–,;/")


def _has_real_name_text(value: str) -> bool:
    """Gołe słowo z krawędzi zdejmujemy tylko, gdy zostaje co najmniej jedna litera."""
    return any(char.isalpha() for char in value)


def _is_name_word(content: str) -> bool:
    """Jedno słowo-nazwisko z wielkiej litery: „Kowalska”, „Kowalska-Nowak”."""
    word = content.strip()
    if len(word) < 2:
        return False
    for part in word.split("-"):
        letters = part.replace("'", "").replace("’", "")
        if not letters or not letters.isalpha() or not part[0].isupper():
            return False
    return True


def _is_marker_content(content: str) -> bool:
    return not _is_name_word(content) or bool(_STATUS_WORD_ONLY_RE.match(content))


def _strip_bracket_segments(value: str, found: list[str]) -> str:
    cleaned = value

    def _replace(match: re.Match[str]) -> str:
        content = match.group(1) if match.group(1) is not None else match.group(2)
        if _is_marker_content(content):
            found.append(match.group(0).strip())
            return " "
        return match.group(0)

    # Kilka przebiegów zdejmuje zagnieżdżone nawiasy od środka; nawias
    # z nazwiskiem zostaje na miejscu, więc pętla kończy się, gdy nic nie znika.
    for _ in range(4):
        updated = _BRACKET_SEGMENT_RE.sub(_replace, cleaned)
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


def _strip_bare_edge_markers(value: str) -> tuple[str, list[str]]:
    """Zdejmij pełne, gołe słowa statusu wyłącznie z krawędzi pola.

    Pętla obsługuje kilka sąsiadujących słów (``"ACTIVE PASSIVE Jan"``), ale
    każdy krok jest przyjęty dopiero wtedy, gdy po nim zostaje realny tekst —
    pojedyncze ``"Active"`` pozostaje nietknięte.
    """
    if not value:
        return value, []

    cleaned = value
    found: list[str] = []
    while True:
        prefix = _BARE_EDGE_PREFIX_RE.search(cleaned)
        if prefix is not None:
            candidate = _normalize_name_marker_spacing(
                _BARE_EDGE_PREFIX_RE.sub(" ", cleaned, count=1)
            )
            if _has_real_name_text(candidate):
                found.append(prefix.group("marker"))
                cleaned = candidate
                continue

        suffix = _BARE_EDGE_SUFFIX_RE.search(cleaned)
        if suffix is not None:
            candidate = _normalize_name_marker_spacing(
                _BARE_EDGE_SUFFIX_RE.sub(" ", cleaned, count=1)
            )
            if _has_real_name_text(candidate):
                found.append(suffix.group("marker"))
                cleaned = candidate
                continue

        break

    return cleaned, found


# ── API modułu ──────────────────────────────────────────────────────────────


def strip_name_markers(value: Optional[str]) -> tuple[str, list[str]]:
    """Imię/nazwisko bez dopisków i lista zdjętych dopisków (surowy tekst).

    Bez dopisku zwraca wartość BEZ ZMIAN (także odstępy). Może zwrócić ``""``,
    gdy pole było samym dopiskiem — wołający stosuje własny fallback (mapper
    Traffita: część adresu e-mail albo „?”).
    """
    if not value:
        return value or "", []
    if len(value) > MAX_SCANNED_NAME_LENGTH:
        return value, []
    found: list[str] = []
    # 1. Pełne pary nawiasów — przed regułami statusu, bo „(zaakceptowany
    #    przez klienta)” musi zniknąć w całości, a nie od „(” do pierwszego słowa.
    cleaned = _strip_bracket_segments(value, found)
    # 2. „zatrudnion*” w dowolnym miejscu (reguła z 0165).
    found += [m.group(0).strip() for m in _EMPLOYMENT_MARKER_RE.finditer(cleaned)]
    cleaned = _EMPLOYMENT_MARKER_RE.sub(" ", cleaned)
    # 3. Słowo statusu przy ograniczniku bez pary.
    found += [m.group(0).strip() for m in _STATUS_MARKER_RE.finditer(cleaned)]
    cleaned = _STATUS_MARKER_RE.sub(" ", cleaned)
    found = [marker for marker in found if marker]
    if found:
        cleaned = _normalize_name_marker_spacing(cleaned)
    # 4. Gołe słowa na krawędzi pola.
    cleaned, bare = _strip_bare_edge_markers(cleaned)
    found += bare
    if not found:
        return value, []
    return cleaned, found


def find_name_markers(value: Optional[str]) -> list[str]:
    """Dopiski obecne w imieniu albo nazwisku — pusta lista, gdy ich nie ma."""
    return strip_name_markers(value)[1]


def without_name_markers(value: Optional[str]) -> Optional[str]:
    """Ścieżki automatyczne: dopisek znika bez odmowy.

    Gdy po zdjęciu nie zostałoby nic, wartość zostaje bez zmian — puste imię
    jest gorsze niż dopisek, a pustego pola wołający nie umiałby uzupełnić.
    """
    if not value:
        return value
    cleaned, markers = strip_name_markers(value)
    if not markers or not cleaned:
        return value
    return cleaned


def _has_blacklist(value: Optional[str]) -> bool:
    if not value or len(value) > MAX_SCANNED_NAME_LENGTH:
        return False
    if _BLACKLIST_WORD_RE.search(value) is not None:
        return True
    return any(
        _BLACKLIST_IN_MARKER_RE.search(marker)
        for marker in strip_name_markers(value)[1]
    )


def has_blacklist_marker(*values: Optional[str]) -> bool:
    """Czy którekolwiek z pól niesie dopisek czarnej listy (w dowolnym zapisie).

    Przyjmuje surowe imię/nazwisko (import, mapper Traffita) albo zdjęte już
    dopiski (korekta 0436) — także wielowyrazowy nawias z „czarną listą”.
    """
    return any(_has_blacklist(value) for value in values)


def has_active_marker(markers: list[str]) -> bool:
    """Czy wśród zdjętych dopisków jest „szuka aktywnie” (active / aktywny).

    Zaprzeczenie („nie aktywny”, „not active”) nie jest „szuka aktywnie”.
    """
    return any(
        _ACTIVE_WORD_RE.search(_NEGATED_ACTIVE_RE.sub(" ", marker))
        for marker in markers
    )


def strip_employment_marker(value: str) -> str:
    """Zdejmij sam legacy ``[zatrudniony]`` (0165) — bez reszty reguły.

    ``"Kowalski - zatrudniony"`` → ``"Kowalski"``. Może zwrócić ``""``, gdy
    pole było samym dopiskiem.
    """
    if (
        not value
        or len(value) > MAX_SCANNED_NAME_LENGTH
        or "zatrudnion" not in value.lower()
    ):
        return value
    cleaned = _EMPLOYMENT_MARKER_RE.sub(" ", value)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" -–,;")
