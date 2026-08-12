"""Typ podmiotu Partnera (JDG vs spółka) i linie kolumny „Partner".

DLACZEGO TO ISTNIEJE. Nazwa JDG w CEIDG z mocy prawa zawiera imię i nazwisko
właściciela („Management Services - Jan Kowalski"), a nazwa spółki nie musi
zawierać żadnego nazwiska. Dlatego w rejestrze umów dla JDG pokazujemy TYLKO
nazwę firmy, a dla spółki dokładamy drugą linię z osobą — inaczej albo
dublujemy nazwisko, albo ukrywamy osobę kontaktową spółki.

DLACZEGO OSOBNY MODUŁ, NIE `registry_lookup`. Ta klasyfikacja jest potrzebna
w serializerze listy, czyli na ścieżce read-only bez sieci, a `registry_lookup`
ciąga `httpx` i `settings`. Rozdzielenie I/O od czystej reguły pozwala też
testować ją bez mockowania HTTP — czego `registry_lookup` do dziś nie ma.

DWA MECHANIZMY, NIE JEDEN. Sygnał z rejestru (CEIDG vs KRS) jest twardy, ale
istnieje wyłącznie dla umów generowanych od migracji 0224. Wiersze historyczne
mają `partner_entity_type = NULL`, więc dla nich decyduje heurystyka po formie
prawnej w nazwie. Do tego dochodzi reguła podciągu w `partner_display_lines`,
która kasuje duplikację nawet wtedy, gdy oba mechanizmy się mylą.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

SOLE_TRADER: Final[str] = "sole_trader"
COMPANY: Final[str] = "company"
PARTNER_ENTITY_TYPES: Final[tuple[str, ...]] = (SOLE_TRADER, COMPANY)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_COMBINING = re.compile(r"[̀-ͯ]")
_DIGITS = re.compile(r"\D")

# `ł` i `Ł` NIE rozkładają się w NFD/NFKD, więc samo
# `normalize("NFKD", "spółka").encode("ascii", "ignore")` daje „spoka" — literę
# gubi się w całości. Dlatego podmieniamy je JAWNIE, PRZED normalizacją.
# Ten sam błąd siedzi w `_ascii_filename` (tam nieszkodliwy, bo dotyczy nazwy
# pliku); poprawny wzór to `foldText` z frontendu.
_PRE_FOLD = str.maketrans({"ł": "l", "Ł": "L"})

# Ogon oddziału zagranicznego: „Nordea Bank Abp S.A. Oddział w Polsce" ma formę
# prawną w ŚRODKU, nie na końcu. Bez obcięcia tego ogona wzorce zakotwiczone na
# końcu (grupy A1/A2) nie trafiłyby.
_BRANCH_TAIL: Final[frozenset[str]] = frozenset(
    {"oddzial", "w", "polsce", "spolki", "zagranicznej", "przedsiebiorcy"}
)

# ── Grupa U: formy jednoznaczne, dopasowanie GDZIEKOLWIEK ────────────────────
# Na „zbitce" (nazwa bez znaków niealfanumerycznych), bo interpunkcja tej
# rodziny jest kompletnie nieregularna: „Sp. z o.o." / „sp.zo.o." / „SPZOO" /
# „Sp. z O.O." to wszystko ta sama forma i wszystkie dają zbitkę `spzoo`.
_SQUASHED_ANYWHERE: Final[tuple[str, ...]] = (
    "spzoo",
    "spolkazoo",
    "spolkazograniczonaodpowiedzialnoscia",
    "zograniczonaodpowiedzialnoscia",
    "spolkaakcyjna",
    "prostaspolkaakcyjna",
    "spolkakomandytowoakcyjna",
    "spolkakomandytowa",
    "spolkajawna",
    "spolkapartnerska",
    "spolkacywilna",
)

# Krótkie skróty na zbitce muszą być zakotwiczone na KOŃCU — `spk` wewnątrz
# nazwy to zbieg liter, `spk` na końcu to spółka komandytowa.
#
# Bez `spzoospk` (forma złożona „sp. z o.o. sp. k."): `str.endswith(tuple)`
# zwraca True dla KTÓREGOKOLWIEK elementu, a każdy string kończący się na
# `spzoospk` kończy się też na `spk` — wpis nigdy nie zmieniałby wyniku. Ta
# forma i tak wychodzi wcześniej, bo `spzoo` jest w `_SQUASHED_ANYWHERE`.
_SQUASHED_SUFFIX: Final[tuple[str, ...]] = ("spk", "spka", "spj", "spp")

# Pojedyncze tokeny jednoznaczne — dopasowanie gdziekolwiek w strumieniu.
_TOKEN_ANYWHERE: Final[frozenset[str]] = frozenset(
    {
        "spolka",
        "fundacja",
        "stowarzyszenie",
        "spoldzielnia",
        "gmbh",
        "ltd",
        "limited",
        "llc",
        "plc",
        "inc",
        "incorporated",
        "sarl",
        "srl",
        "sas",
        "aps",
        "kft",
        "ohg",
        "pte",
        "oyj",
    }
)

# ── Grupa A1: formy kropkowane, wymagany KONIEC strumienia ───────────────────
# Rozpad na jednoliterowe tokeny bierze się z kropek i sam jest wystarczająco
# mocnym sygnałem, więc NIE wymagamy wielkich liter. To celowo obsługuje `s.c.`,
# które w Polsce pisze się MAŁYMI („Jan Kowalski i Anna Nowak s.c.").
_DOTTED_SUFFIX: Final[tuple[tuple[str, ...], ...]] = (
    ("s", "a"),
    ("s", "c"),
    ("p", "s", "a"),
    ("s", "p", "a"),
    ("s", "k", "a"),
    ("s", "r", "o"),
    ("a", "s"),
)

# ── Grupa A2: nagie skróty — KONIEC strumienia ORAZ wielkie litery w oryginale ─
# „Nordea Bank Abp SA" to spółka; „Kancelaria SA Jan Kowalski" i „Sasin
# Consulting" nie. Nagie `spa` świadomie POZA słownikiem: włoskie `S.p.A.` łapie
# grupa A1, a bez tego wykluczenia „Salon Anna Nowak SPA" fałszywie stałoby się
# spółką.
_BARE_SUFFIX: Final[frozenset[str]] = frozenset(
    {"sa", "sc", "ska", "psa", "as", "ab", "ag", "oy", "bv", "nv", "sl", "kg", "sro"}
)


def fold_company_text(value: str | None) -> str:
    """Nazwa → `a-z0-9` rozdzielone pojedynczymi spacjami.

    Kolejność ma znaczenie: `ł` przed NFD (patrz `_PRE_FOLD`).
    """
    if not value:
        return ""
    pre = value.translate(_PRE_FOLD).lower()
    decomposed = _COMBINING.sub("", unicodedata.normalize("NFD", pre))
    return _NON_ALNUM.sub(" ", decomposed).strip()


def _token_pairs(name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Zwróć (tokeny po foldzie, tokeny surowe) o odpowiadających sobie indeksach.

    Dwa strumienie dzielone tym samym rozdzielaczem, żeby test „czy w oryginale
    było WIELKIMI" był zwykłym `raw[i].isupper()` — bez mapowania offsetów.
    """
    raw = [t for t in re.split(r"[^0-9A-Za-zÀ-ɏ]+", name) if t]
    folded, kept_raw = [], []
    for token in raw:
        f = fold_company_text(token)
        if f:
            folded.append(f)
            kept_raw.append(token)
    return tuple(folded), tuple(kept_raw)


def _trim_branch_tail(
    folded: tuple[str, ...], raw: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    end = len(folded)
    while end > 0 and folded[end - 1] in _BRANCH_TAIL:
        end -= 1
    # Same tokeny ogona (bez nazwy) to nie nazwa oddziału — nic nie obcinamy.
    return (folded[:end], raw[:end]) if end else (folded, raw)


def entity_type_from_registry(source: str | None, krs: str | None) -> str | None:
    """Twardy sygnał z rejestru. ``None`` = rejestr nie rozstrzyga.

    Porównania po ``.upper()``, bo ``source`` przychodzi w czterech
    niespójnych formatach (``"CEIDG"``, ``"KRS"``, ``"biala_lista"``,
    ``"krs"``, ``"biznes"``) — patrz `registry_lookup`.
    """
    if krs and _DIGITS.sub("", str(krs)):
        # Numer KRS mają wyłącznie podmioty rejestrowe. Sprawdzane PIERWSZE:
        # konflikt sygnałów jest wątpliwością, a wątpliwość idzie na spółkę.
        return COMPANY
    src = (source or "").strip().upper()
    if src == "CEIDG":
        return SOLE_TRADER
    if src == "KRS":
        return COMPANY
    if src == "BIALA_LISTA":
        # Istniejąca reguła z `_merge`: brak KRS w Białej Liście = JDG.
        return SOLE_TRADER
    return None


def entity_type_from_company_name(name: str | None) -> str | None:
    """Heurystyka po formie prawnej w nazwie. ``None`` = brak oznaczenia.

    Zwraca ``None``, a nie ``SOLE_TRADER``, żeby „nie ma formy prawnej" dało
    się odróżnić od „rozstrzygnięto na JDG". Domknięcie na spółkę robi
    `resolve_partner_entity_type`, w jednym miejscu.
    """
    folded_all = fold_company_text(name)
    if not folded_all:
        return None

    squashed = folded_all.replace(" ", "")
    if any(needle in squashed for needle in _SQUASHED_ANYWHERE):
        return COMPANY
    if squashed.endswith(_SQUASHED_SUFFIX):
        return COMPANY

    folded, raw = _trim_branch_tail(*_token_pairs(name))
    if not folded:
        return None

    if any(token in _TOKEN_ANYWHERE for token in folded):
        return COMPANY

    for sequence in _DOTTED_SUFFIX:
        if len(folded) > len(sequence) and folded[-len(sequence) :] == sequence:
            return COMPANY

    # Nagi skrót: ostatni token, w oryginale pisany WIELKIMI. `len(folded) > 1`
    # — sama nazwa złożona z jednego skrótu nie jest formą prawną.
    if len(folded) > 1 and folded[-1] in _BARE_SUFFIX and raw[-1].isupper():
        return COMPANY

    return None


def resolve_partner_entity_type(*, stored: str | None, legal_name: str | None) -> str:
    """Rozstrzygnięty typ podmiotu — NIGDY ``None``.

    Łańcuch: snapshot z rejestru → heurystyka po nazwie → ``company``.

    Snapshot BIJE heurystykę, bo ticket wymaga, żeby wynik rozpoznania był
    zapisany w momencie generowania i „nie przeliczany później". Domknięcie na
    ``company`` realizuje regułę „niejednoznaczne → spółka": nadmiarowa druga
    linia nie szkodzi, a jej brak przy faktycznej spółce ukrywa osobę.
    """
    if stored in PARTNER_ENTITY_TYPES:
        return str(stored)
    return entity_type_from_company_name(legal_name) or COMPANY


def partner_display_lines(
    *,
    legal_name: str | None,
    person_name: str | None,
    entity_type: str,
) -> tuple[str | None, str | None]:
    """(główna linia kolumny „Partner", linia drugorzędna albo ``None``)."""
    legal = (legal_name or "").strip()
    person = (person_name or "").strip()

    # Wiersz historyczny bez zapisanej nazwy firmy: pokazujemy osobę, jak przed
    # migracją 0224. Klasyfikacja jest tu NIEISTOTNA — gdyby decydowała, wiersz
    # z `partner_name = "ZW Software Sp. z o.o."` i pustą nazwą firmy wypisałby
    # tę firmę DWA RAZY, w dwóch rozmiarach czcionki.
    if not legal:
        return (person or None, None)
    if entity_type == SOLE_TRADER or not person:
        return (legal, None)

    # Nazwa JDG z mocy prawa zawiera właściciela, więc podciąg kasuje duplikację
    # nawet bez sygnału z rejestru. Porównanie na stringach otoczonych spacjami,
    # żeby „Jan Kowal" nie trafiło w „Jan Kowalski".
    folded_legal = f" {fold_company_text(legal)} "
    folded_person = f" {fold_company_text(person)} "
    if folded_person.strip() and folded_person in folded_legal:
        return (legal, None)

    return (legal, person)
