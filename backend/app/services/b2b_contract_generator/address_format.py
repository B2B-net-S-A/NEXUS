"""Adres z rejestru w zapisie do umowy: „ul. Testowa 12/3, 00-001 Warszawa”.

Biała Lista i CEIDG zwracają adres WIELKIMI LITERAMI i zwykle bez „ul.”, a dział
umów poprawiał to ręcznie w każdej umowie (zgłoszenie 03.11.2026). Formatujemy
tylko to, co wypełnia generator z rejestru. We wpisie człowieka porządkujemy sam
numer domu (``tidy_house_number``), a wydane umowy zostają bez zmian.

Moduł-liść, bez sieci i bazy, jak ``formatting``.
"""

from __future__ import annotations

import re

_ABBREVIATED_TYPES = {
    "UL": "ul.",
    "ULICA": "ul.",
    "AL": "al.",
    "PL": "pl.",
    "OS": "os.",
}
# Nazwa sama mówi, czym jest ta droga — „ul. Aleja Zgody” byłoby błędem.
_NAMED_TYPES = frozenset(
    {"ALEJA", "ALEJE", "PLAC", "OSIEDLE", "RONDO", "SKWER", "BULWAR", "PARK", "RYNEK"}
)
# Tytuły przed nazwiskiem patrona: „ul. dr. Jana Testowego”, „ul. św. Jana”.
_TITLES = frozenset(
    {"DR", "ŚW", "GEN", "KS", "PROF", "INŻ", "PŁK", "MJR", "KPT", "POR", "BP", "ABP"}
)
_MINOR_WORDS = frozenset(
    {"I", "W", "WE", "Z", "ZE", "NA", "NAD", "POD", "PRZY", "DO", "OD", "ZA", "K"}
)
_UNIT_WORDS = frozenset({"LOK", "M", "NR"})
_ROMAN = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_LETTERS = re.compile(r"[^\W\d_]+")
_STREET_TYPE_GLUED = re.compile(r"^(UL|AL|PL|OS)\.(?=\S)", re.IGNORECASE)
# „, nr 12, lok. 5” z wydruku CEIDG. Litera po spacji należy do numeru („36 E”),
# ale „m” już nie: w „nr 10 m 71” otwiera numer lokalu.
_HOUSE_NUMBER = re.compile(
    r"(?:,\s*|\s+)nr\.?\s*(\d[^\s,;]*(?:\s[a-ln-z](?=[\s,;]|$))?)"
    r"(?:,?\s+(?:lok(?:al)?\.?|m\.?)\s*(\w[^\s,;]*))?",
    re.IGNORECASE,
)


def _has_digit(word: str) -> bool:
    return any(ch.isdigit() for ch in word)


def _has_letter(word: str) -> bool:
    return any(ch.isalpha() for ch in word)


def _title(word: str) -> str:
    return _LETTERS.sub(lambda m: m.group(0).capitalize(), word)


def _word_case(word: str, previous: str | None, following: str | None) -> str:
    """Jedno słowo zapisane WIELKIMI LITERAMI → zapis zwykły. Numer („118E/31”)
    i słowo z małymi literami (ktoś już je poprawił) zostają bez zmian."""
    if _has_digit(word) or not word.isupper():
        return word
    core = word.rstrip(".,;")
    tail = word[len(core) :]
    if core in _TITLES:
        return core.lower() + tail
    if core in _UNIT_WORDS and previous is not None and _has_digit(previous):
        return core.lower() + tail
    if core in _MINOR_WORDS and previous is not None and _has_letter(previous):
        # „Żwirki i Wigury”, ale „Mieszka I 12” — po „I” stoi tam numer domu.
        if core != "I" or (following is not None and not _has_digit(following)):
            return core.lower() + tail
    if len(core) > 1 and _ROMAN.match(core):
        return word
    return _title(word)


def _part_case(part: str) -> str:
    words = part.split(" ")
    return " ".join(
        _word_case(
            word,
            words[i - 1] if i else None,
            words[i + 1] if i + 1 < len(words) else None,
        )
        for i, word in enumerate(words)
    )


def _street_name(street: str) -> str:
    """„Nowa Wieś 80B” → „Nowa Wieś”; „3 Maja 5” → „3 Maja”."""
    words = street.split(" ")
    last_number = max((i for i, w in enumerate(words) if _has_digit(w)), default=None)
    return " ".join(words[:last_number] if last_number else words)


def _city(tail: str) -> str:
    return re.sub(r"^\d{2}-\d{3}\s*", "", tail).strip()


def _with_street_type(
    street: str, formatted: str, tail: str, has_street: bool | None
) -> str:
    first, _, rest = formatted.partition(" ")
    key = first.rstrip(".").upper()
    if key in _ABBREVIATED_TYPES:
        return f"{_ABBREVIATED_TYPES[key]} {rest}".strip()
    if key in _NAMED_TYPES or has_street is False or not _has_letter(street):
        return formatted
    name = _street_name(street)
    if not name or (has_street is None and name.casefold() == _city(tail).casefold()):
        return formatted
    return f"ul. {formatted}"


def tidy_house_number(address: str | None) -> str | None:
    """„ul. Polna, nr 12, lok. 5, …” → „ul. Polna 12/5, …”. Reszta bez zmian."""
    if not address:
        return address

    def compact(match: re.Match[str]) -> str:
        number, unit = match.groups()
        return f" {number}/{unit}" if unit else f" {number}"

    return _HOUSE_NUMBER.sub(compact, address, count=1)


def format_registry_address(
    address: str | None, *, has_street: bool | None = None
) -> str | None:
    """Adres z rejestru w zapisie do umowy.

    ``has_street``: czy rejestr podał ulicę osobnym polem (CEIDG API). ``None`` =
    nie wiadomo (Biała Lista zwraca jeden napis), wtedy miejscowość bez ulic
    poznajemy po tym, że przy numerze stoi nazwa miejscowości. Wsi z pocztą
    w innej miejscowości tak nie rozpoznamy: dostanie „ul.”, a człowiek widzi
    adres w formularzu i może go poprawić.
    """
    text = re.sub(r"\s+", " ", address or "").strip()
    if not text:
        return None
    text = tidy_house_number(text) or text
    text = _STREET_TYPE_GLUED.sub(lambda m: f"{m.group(0)} ", text)
    street, separator, tail = text.partition(",")
    tail = tail.strip()
    formatted = _with_street_type(street, _part_case(street), tail, has_street)
    return f"{formatted}{separator} {_part_case(tail)}" if separator else formatted
