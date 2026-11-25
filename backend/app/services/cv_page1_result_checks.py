"""Sprawdzenie zdań „najmocniejszy wynik” ze strony 1 „Nowego CV” (22.11.2026).

Model proponuje do czterech wyników z całego CV, każdy z dosłownym cytatem
(`cv_page1_results`). Tu kod decyduje, które z nich wolno postawić na stronie 1
(`verified`), bez sieci i bez bazy:

- cytat stoi w jednym punkcie (albo nazwie stanowiska) jednej roli z CV —
  porównanie po słowach, więc wielkość liter, cudzysłowy, myślniki i drobna
  interpunkcja nie mają znaczenia, a zmienione słowo już tak;
- każda liczba ze zdania stoi w cytacie albo w tekście tej samej roli;
- zdanie jest jedno i mieści się w ``TEXT_MAX_CHARS`` znakach (bez ``**``);
- w Blind CV zdanie nie nazywa firmy z listy stanowisk.

Zdanie, które powtarza punkt 1 albo 2 strony 1 (lata, technologie), znika.
Niesprawdzone zostają z kodem ``issue`` — edytor może je pokazać, ale strona 1
ich nie bierze (`cv_layout.chosen_result`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Optional

MAX_RESULTS = 4
# Ile propozycji modelu w ogóle czytamy — więcej to szum, nie wybór.
MAX_CANDIDATES = 8
TEXT_MAX_CHARS = 170
QUOTE_MIN_WORDS = 4
# Zdanie, które dzieli z punktem 1 albo 2 tyle słów (rdzeni), to ten sam punkt.
PAGE1_OVERLAP = 0.6

ISSUE_QUOTE_MISSING = "quote_missing"
ISSUE_QUOTE_NOT_IN_CV = "quote_not_in_cv"
ISSUE_TOO_LONG = "too_long"
ISSUE_NOT_ONE_SENTENCE = "not_one_sentence"
ISSUE_NUMBER_NOT_IN_CV = "number_not_in_cv"
ISSUE_COMPANY_NAMED = "company_named"

_FOLD = str.maketrans(
    {
        "„": '"',
        "”": '"',
        "“": '"',
        "«": '"',
        "»": '"',
        "‚": "'",
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "‑": "-",
        "−": "-",
        " ": " ",
        " ": " ",
        " ": " ",
    }
)
_WORD = re.compile(r"[^\W_]+")
_DIGITS = re.compile(r"\d+")
# „1 000”, „1,000”, „1.000” → „1000” (po obu stronach porównania tak samo).
_THOUSANDS = re.compile(r"(?<=\d)[ ,.](?=\d{3}(?!\d))")
_LIST_MARKER = re.compile(r"^(?:[-•–]\s+|\d{1,2}[.)]\s+)")
_TENURE = re.compile(
    r"\b\d+(?:[.,]\d+)?\+?\s*(?:lat|lata|roku|years?)\b.{0,24}?"
    r"\b(?:doświadczenia|experience)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"([.!?])\s+(?=\S)")
_ABBREVIATIONS = frozenset(
    {
        "ok",
        "np",
        "m.in",
        "tj",
        "tzw",
        "itd",
        "itp",
        "ds",
        "tys",
        "mln",
        "mld",
        "nr",
        "sp",
        "s.a",
        "o.o",
        "z.o.o",
        "dr",
        "prof",
        "e.g",
        "i.e",
        "approx",
        "vs",
        "etc",
        "inc",
        "ltd",
        "co",
        "no",
        "st",
    }
)


@dataclass(frozen=True)
class RoleSource:
    """Jedna rola z CV: tekst do cytatu (punkty i nazwa stanowiska) i do liczb."""

    index: int
    company: str
    position: str
    dates: str
    duties: tuple[str, ...]
    technologies: tuple[str, ...]

    @property
    def units(self) -> tuple[str, ...]:
        """Fragmenty, w których musi stać cały cytat — jeden punkt albo stanowisko."""
        return tuple(u for u in (*self.duties, self.position) if u.strip())

    @property
    def text(self) -> str:
        return " ".join(
            (
                self.position,
                self.company,
                self.dates,
                *self.duties,
                ", ".join(self.technologies),
            )
        )


def strip_bold(text: str) -> str:
    return str(text or "").replace("**", "")


def source_sha(html: Optional[str]) -> str:
    """Odcisk HTML-a edytora, z którego policzono wyniki (`results_source_sha`)."""
    return hashlib.sha256((html or "").encode("utf-8")).hexdigest()


def roles_from_cv_json(cv_json: dict[str, Any]) -> list[RoleSource]:
    """Role z treści edytora (`cv_new_content.cv_json_from_editor_html`)."""
    roles: list[RoleSource] = []
    for index, role in enumerate(cv_json.get("experience") or []):
        if not isinstance(role, dict):
            continue
        duties = tuple(
            " ".join(str(d).split())
            for d in role.get("responsibilities") or []
            if str(d or "").strip()
        )
        roles.append(
            RoleSource(
                index=index,
                company=" ".join(str(role.get("company") or "").split()),
                position=" ".join(str(role.get("position") or "").split()),
                dates=" ".join(str(role.get("dates") or "").split()),
                duties=duties,
                technologies=tuple(
                    str(t).strip() for t in role.get("technologies") or [] if t
                ),
            )
        )
    return roles


def _words(text: str) -> list[str]:
    return _WORD.findall(strip_bold(text).translate(_FOLD).casefold())


def _phrase(text: str) -> str:
    return " ".join(_words(text))


def _numbers(text: str) -> set[str]:
    plain = strip_bold(text).translate(_FOLD)
    return set(_DIGITS.findall(_THOUSANDS.sub("", plain)))


_STOPWORDS = frozenset(
    {
        "with",
        "from",
        "that",
        "this",
        "into",
        "over",
        "while",
        "which",
        "oraz",
        "przez",
        "jako",
        "także",
        "ponad",
        "około",
        "który",
        "która",
        "które",
    }
)


def _stems(text: str) -> set[str]:
    return {
        w[:6]
        for w in _words(text)
        if len(w) >= 4 and not w.isdigit() and w not in _STOPWORDS
    }


def clean_text(value: Any) -> str:
    """Jedna linia, bez znaku listy; nieparzyste ``**`` = bez pogrubień."""
    text = " ".join(str(value or "").split())
    text = _LIST_MARKER.sub("", text)
    text = text.replace("****", "")
    if text.count("**") % 2:
        text = text.replace("**", "")
    return text.strip()


def repeats_page1(text: str, page1: list[str]) -> bool:
    """Zdanie o latach doświadczenia albo powtórka punktu 1 lub 2."""
    if _TENURE.search(strip_bold(text)):
        return True
    mine = _stems(text)
    for point in page1:
        theirs = _stems(point)
        smaller = min(len(mine), len(theirs))
        if smaller >= 3 and len(mine & theirs) / smaller >= PAGE1_OVERLAP:
            return True
    return False


def is_one_sentence(text: str) -> bool:
    plain = strip_bold(text).strip()
    if not plain or "\n" in plain:
        return False
    body = plain.rstrip(" .!?")
    for match in _SENTENCE_BREAK.finditer(body):
        following = body[match.end() :]
        if not following[:1].isupper():
            continue  # „ok. 30%”, „np. dla …”
        if match.group(1) == ".":
            before = body[: match.start()].split(" ")[-1].casefold()
            if before in _ABBREVIATIONS or len(before.replace(".", "")) <= 1:
                continue  # „Sp. z o.o.”, „S.A. ”, inicjał
            if "." in before:
                continue  # skrót z kropkami w środku („m.in.”, „S.A.”)
        return False
    return True


def locate_role(
    quote: str, roles: list[RoleSource], company: Any = None
) -> Optional[RoleSource]:
    """Rola, w której jednym punkcie (albo nazwie stanowiska) stoi cały cytat."""
    words = _words(quote)
    if len(words) < QUOTE_MIN_WORDS:
        return None
    needle = f" {' '.join(words)} "
    hits = [
        role
        for role in roles
        if any(needle in f" {_phrase(unit)} " for unit in role.units)
    ]
    if not hits:
        return None
    wanted = " ".join(str(company or "").split()).casefold()
    for role in hits:
        if wanted and role.company.casefold() == wanted:
            return role
    return hits[0]


def _company_core(company: str) -> str:
    return re.split(r"\s*[(\[]", company, maxsplit=1)[0].strip()


def find_issue(
    text: str,
    quote: str,
    role: Optional[RoleSource],
    roles: list[RoleSource],
    *,
    blind: bool,
) -> Optional[str]:
    """Pierwszy powód, dla którego zdanie nie może stanąć na stronie 1."""
    if len(_words(quote)) < QUOTE_MIN_WORDS:
        return ISSUE_QUOTE_MISSING
    if role is None:
        return ISSUE_QUOTE_NOT_IN_CV
    if len(strip_bold(text)) > TEXT_MAX_CHARS:
        return ISSUE_TOO_LONG
    if not is_one_sentence(text):
        return ISSUE_NOT_ONE_SENTENCE
    if not _numbers(text) <= _numbers(quote) | _numbers(role.text):
        return ISSUE_NUMBER_NOT_IN_CV
    if blind:
        folded = strip_bold(text).casefold()
        for other in roles:
            core = _company_core(other.company)
            if len(core) >= 3 and core.casefold() in folded:
                return ISSUE_COMPANY_NAMED
    return None


def _period_like(text: str, page1: list[str]) -> str:
    """Kropka na końcu jak w punktach 1–2 tego CV (generator pisze różnie)."""
    ends = [p.rstrip().endswith(".") for p in page1 if p.strip()]
    if not ends:
        return text
    if all(ends) and not text.endswith((".", "!", "?")):
        return text + "."
    if not any(ends) and text.endswith(".") and not text.endswith(".."):
        return text[:-1].rstrip()
    return text


def verify_results(
    items: Any,
    roles: list[RoleSource],
    why_points: list[str],
    *,
    blind: bool = False,
) -> list[dict[str, Any]]:
    """Propozycje modelu → lista do `page1_extras.results`, sprawdzone pierwsze.

    Kolejność modelu (od najmocniejszego) zostaje w obu grupach, więc
    ``result_index`` 0 to najmocniejszy SPRAWDZONY wynik.
    """
    page1 = [str(p) for p in (why_points or [])[:2] if str(p or "").strip()]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(items or [])[:MAX_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        text = clean_text(item.get("text"))
        key = _phrase(text)
        if not key or key in seen or repeats_page1(text, page1):
            continue
        seen.add(key)
        quote = " ".join(strip_bold(str(item.get("quote") or "")).split())
        role = locate_role(quote, roles, item.get("company"))
        issue = find_issue(text, quote, role, roles, blind=blind)
        result: dict[str, Any] = {
            "text": _period_like(text, page1),
            "quote": quote,
            "company": role.company
            if role is not None
            else " ".join(str(item.get("company") or "").split()),
            "verified": issue is None,
        }
        if issue is not None:
            result["issue"] = issue
        out.append(result)
    out.sort(key=lambda r: not r["verified"])
    return out[:MAX_RESULTS]


def merged_extras(
    extras: Optional[dict], results: list[dict[str, Any]], sha: str
) -> dict[str, Any]:
    """Nowe dodatki strony 1: inne klucze bez zmian, wybór od zera tylko przy
    innych wynikach (rekruter mógł wybrać drugi wynik z tej samej listy)."""
    merged = dict(extras) if isinstance(extras, dict) else {}
    changed = merged.get("results") != results
    merged["results"] = results
    merged["results_source_sha"] = sha
    if changed or "result_index" not in merged:
        merged["result_index"] = 0
    return merged


ISSUE_STALE = "stale"


def rechecked_extras(
    extras: Optional[dict],
    html: Optional[str],
    cv_json: dict[str, Any],
    *,
    blind: bool = False,
) -> Optional[dict]:
    """Dodatki strony 1 z wynikami sprawdzonymi na bieżącej treści CV (render).

    `verified` dotyczy HTML-a, z którego policzono wyniki (`results_source_sha`).
    Gdy treść jest inna (rekruter usunął rolę, zmienił liczbę), każdy wynik
    oznaczony jako sprawdzony przechodzi kontrolę jeszcze raz na bieżących rolach
    — sam kod, bez sieci. Niesprawdzony dostaje ``verified: False``, więc strona 1
    bierze trzeci punkt generatora. Zwraca nowy słownik; zapisanych dodatków
    nie zmienia (wyniki od nowa liczy przycisk albo bieg w tle).
    """
    if not isinstance(extras, dict):
        return extras
    results = extras.get("results")
    if not isinstance(results, list) or extras.get("results_source_sha") == source_sha(
        html
    ):
        return extras
    roles = roles_from_cv_json(cv_json)
    why = [str(p) for p in cv_json.get("why_points") or []]
    return {
        **extras,
        "results": [_still_verified(item, roles, why, blind) for item in results],
    }


def _still_verified(
    item: Any, roles: list[RoleSource], why: list[str], blind: bool
) -> Any:
    if not isinstance(item, dict) or item.get("verified") is not True:
        return item
    again = verify_results([item], roles, why, blind=blind)
    if again and again[0]["verified"]:
        return item
    issue = again[0].get("issue") if again else ISSUE_STALE
    return {**item, "verified": False, "issue": issue}
