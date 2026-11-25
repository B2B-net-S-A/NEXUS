"""Reguła wypowiedzenia z treści podpisanej umowy — wzorce tekstu, bez modelu.

W obiegu są umowy z różnych wersji wzoru (makiety asystenta, 25.11.2026):

* wzór z 2025 r.: okres „liczony od kolejnego miesiąca”, wypowiedzenie
  „w formie pisemnej pod rygorem nieważności”, doręczenie „osobiście lub
  pocztą za potwierdzeniem odbioru”;
* dzisiejszy wzór (``templates/contract/umowa_b2b_pl.html`` § 12): okres
  „ze skutkiem na koniec miesiąca kalendarzowego”, forma pisemna lub
  dokumentowa, doręczenie także mailem.

Pismo do Partnera musi iść za tym, co PODPISAŁ, więc reguła pochodzi z pliku
w Dokumentach kontraktu, nie ze wzoru. Gdy tekst nie mówi jednoznacznie
(kilka różnych okresów, okres w miesiącach bez sposobu liczenia, brak zapisu)
wynik to ``rule=None`` z powodem — termin policzy wtedy człowiek.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.services.contract_document_text.structure import Sentence, ref_of, sentences

PERIOD_END_OF_MONTH = "end_of_month"
PERIOD_FROM_NEXT_MONTH = "from_next_month"
PERIOD_DAYS = "days"

FORM_WRITTEN = "written"
FORM_DOCUMENTARY = "documentary"
FORM_ELECTRONIC = "electronic"

DELIVERY_IN_PERSON = "in_person"
DELIVERY_POST = "post"
DELIVERY_EMAIL = "email"

_WORD_NUMBERS = {
    "jed": 1,
    "dw": 2,
    "trz": 3,
    "czt": 4,
    "cze": 4,
    "pie": 5,
    "sze": 6,
}

# Na tekście bez polskich znaków (``fold``).
_DURATION = re.compile(
    r"(?<![\w/])(\d{1,3}|jed\w*?|dw\w*?|trz\w*?|czter\w*?|piec\w*?|szesc\w*?)"
    r"\s*-?\s*(?:\(\s*[a-z]+\s*\)\s*)?"
    r"(miesi\w*|dni\w*|dzien\w*|tygod\w*)"
)
_COMPOUND = re.compile(r"\b(jedno|dwu|trzy)(miesiec\w*|tygodn\w*)")
_TERMINATION = re.compile(r"wypowiedz")
_PERIOD_CONTEXT = re.compile(r"okres|zachowaniem|wypowiedzeniem")
_IMMEDIATE = re.compile(r"natychmiast|bez zachowania")
_END_OF_MONTH = re.compile(
    r"(koni\w*|koncem|ostatni\w*\s+dni\w*)\s+(?:\w+\s+){0,2}miesiac"
)
_NEXT_MONTH = re.compile(
    r"od\s+(?:pierwszego\s+dnia\s+)?(?:kolejn|nastepn)\w*\s+(?:\w+\s+)?miesiac"
)
_FORM_SUBJECT = re.compile(r"wypowiedz|rozwiaz")
_WRITTEN = re.compile(
    r"form\w*\s+pisemn|pisemn\w*\s+(?:lub|albo|i)\s+(?:w\s+)?(?:form\w*\s+)?dokumentow"
)
_DOCUMENTARY = re.compile(r"dokumentow\w*")
_ELECTRONIC_FORM = re.compile(r"form\w*\s+elektroniczn")
_NULLITY = re.compile(r"rygor\w*\s+niewaznosci")
_IN_PERSON = re.compile(r"osobisc")
_EMAIL = re.compile(r"\b(?:e-?)?mail|poczt\w*\s+elektroniczn|drog\w*\s+elektroniczn")
_POST = re.compile(r"\bpoczt\w*|list\w*\s+polecon|potwierdzeniem\s+odbioru|kurier")
_DELIVERY_HINT = re.compile(r"dorecz|przesl|wysyl|skladan|zlozon|osobisc|poczt|mail")


@dataclass(frozen=True)
class Clause:
    """Zdanie z umowy, z którego wynika część reguły."""

    text: str
    section: Optional[str]
    point: Optional[str]
    offset: int

    @property
    def ref(self) -> Optional[str]:
        return ref_of(self.section, self.point)


@dataclass(frozen=True)
class TerminationRule:
    period_kind: str
    period_months: Optional[int]
    period_days: Optional[int]
    period_clause: Clause
    forms: tuple[str, ...] = ()
    under_nullity: bool = False
    form_clause: Optional[Clause] = None
    delivery: tuple[str, ...] = ()
    delivery_clause: Optional[Clause] = None
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TerminationParse:
    rule: Optional[TerminationRule]
    reason: Optional[str]


def _clause(sentence: Sentence) -> Clause:
    return Clause(sentence.text, sentence.section, sentence.point, sentence.offset)


def _number(token: str) -> Optional[int]:
    if token.isdigit():
        return int(token)
    if "dziest" in token or "nasci" in token:
        # „trzydziestu”, „czternastu” — dziesiątki słownie stoją przy cyfrach
        # w nawiasie, a pierwsza litera dałaby zły okres.
        return None
    for prefix, value in _WORD_NUMBERS.items():
        if token.startswith(prefix):
            return value
    return None


def _duration(folded: str) -> Optional[tuple[str, int]]:
    """(``months`` | ``days``, liczba) z pierwszej długości w zdaniu."""
    compound = _COMPOUND.search(folded)
    if compound:
        value = {"jedno": 1, "dwu": 2, "trzy": 3}[compound.group(1)]
        unit = compound.group(2)
        return ("months", value) if unit.startswith("miesi") else ("days", 7 * value)
    for match in _DURATION.finditer(folded):
        value = _number(match.group(1))
        if value is None or value == 0:
            continue
        unit = match.group(2)
        if unit.startswith("miesi"):
            return "months", value
        if unit.startswith("tygod"):
            return "days", 7 * value
        return "days", value
    return None


def _anchor(folded: str) -> Optional[str]:
    end = bool(_END_OF_MONTH.search(folded))
    following = bool(_NEXT_MONTH.search(folded))
    if end and following:
        return "both"
    if end:
        return PERIOD_END_OF_MONTH
    if following:
        return PERIOD_FROM_NEXT_MONTH
    return None


_LIST_ITEM = re.compile(r"(?:^|(?<=\s))[a-h][.)]\s+|;")


def _fragments(folded: str) -> list[str]:
    """Punkty wyliczenia w jednym zdaniu („a. za porozumieniem … d. w trybie
    natychmiastowym”) — każdy oceniany osobno, bo tryb natychmiastowy w punkcie
    d nie unieważnia okresu z punktu b."""
    return [part for part in _LIST_ITEM.split(folded) if part.strip()]


def _period_candidates(
    found: list[Sentence],
) -> list[tuple[str, str, int, Sentence]]:
    """(rodzaj, jednostka, liczba, zdanie) dla każdego zapisu o okresie wypowiedzenia."""
    out: list[tuple[str, str, int, Sentence]] = []
    for index, sentence in enumerate(found):
        for folded in _fragments(sentence.folded):
            if not _TERMINATION.search(folded) or not _PERIOD_CONTEXT.search(folded):
                continue
            duration = _duration(folded)
            if duration is None:
                continue
            anchor = _anchor(folded)
            if _IMMEDIATE.search(folded) and not anchor:
                continue
            unit, value = duration
            if anchor is None:
                # Sposób liczenia bywa w następnym zdaniu tego samego akapitu
                # („Okres wypowiedzenia wynosi 1 miesiąc. Okres ten liczy się…”).
                following = found[index + 1] if index + 1 < len(found) else None
                if following is not None and following.paragraph == sentence.paragraph:
                    anchor = _anchor(following.folded)
            if anchor is None and unit == "days":
                anchor = PERIOD_DAYS
            out.append((anchor or "", unit, value, sentence))
    return out


def _form(found: list[Sentence]) -> tuple[tuple[str, ...], bool, Optional[Sentence]]:
    for sentence in found:
        folded = sentence.folded
        if not _FORM_SUBJECT.search(folded):
            continue
        forms: list[str] = []
        if _WRITTEN.search(folded) or re.search(r"pisemn", folded):
            forms.append(FORM_WRITTEN)
        if _DOCUMENTARY.search(folded) and re.search(r"form|pisemn", folded):
            forms.append(FORM_DOCUMENTARY)
        if _ELECTRONIC_FORM.search(folded):
            forms.append(FORM_ELECTRONIC)
        if forms and re.search(r"form", folded):
            return tuple(forms), bool(_NULLITY.search(folded)), sentence
    return (), False, None


def _delivery(
    found: list[Sentence], anchor: Optional[Sentence]
) -> tuple[tuple[str, ...], Optional[Sentence]]:
    """Sposoby doręczenia z zdania o formie i najbliższych zdań tego paragrafu."""
    if anchor is None:
        return (), None
    start = found.index(anchor)
    window = [s for s in found[start : start + 4] if s.section == anchor.section]
    for sentence in window:
        folded = sentence.folded
        if not _DELIVERY_HINT.search(folded):
            continue
        ways: list[str] = []
        if _IN_PERSON.search(folded):
            ways.append(DELIVERY_IN_PERSON)
        without_email = _EMAIL.sub(" ", folded)
        if _POST.search(without_email):
            ways.append(DELIVERY_POST)
        # „kwalifikowany podpis elektroniczny” to forma, nie doręczenie mailem.
        if _EMAIL.search(folded.replace("podpis elektroniczny", "")):
            ways.append(DELIVERY_EMAIL)
        if ways:
            return tuple(ways), sentence
    return (), None


def parse_termination(text: str) -> TerminationParse:
    """Okres wypowiedzenia, forma i doręczenie z tekstu jednej umowy (albo aneksu)."""
    if not text or not text.strip():
        return TerminationParse(None, "Dokument nie ma treści do przeczytania.")
    found = sentences(text)
    candidates = _period_candidates(found)
    if not candidates:
        return TerminationParse(None, "W treści nie ma zapisu o okresie wypowiedzenia.")
    distinct = {(kind, unit, value) for kind, unit, value, _ in candidates}
    if len(distinct) > 1:
        refs = ", ".join(
            dict.fromkeys(
                ref_of(s.section, s.point) or "bez paragrafu"
                for *_rest, s in candidates
            )
        )
        return TerminationParse(
            None,
            "Umowa podaje więcej niż jeden okres wypowiedzenia "
            f"({refs}) — który obowiązuje, musi ocenić człowiek.",
        )
    kind, unit, value, sentence = candidates[0]
    if kind == "both":
        return TerminationParse(
            None,
            "Zapis o okresie wypowiedzenia mówi i o końcu miesiąca, i o kolejnym "
            "miesiącu — sposób liczenia musi ocenić człowiek.",
        )
    if not kind:
        return TerminationParse(
            None,
            "Okres wypowiedzenia w miesiącach bez sposobu liczenia (koniec miesiąca "
            "albo od kolejnego miesiąca) — termin musi policzyć człowiek.",
        )
    forms, nullity, form_sentence = _form(found)
    delivery, delivery_sentence = _delivery(found, form_sentence or sentence)
    notes: list[str] = []
    if not forms:
        notes.append("Nie znaleziono zapisu o formie wypowiedzenia.")
    if not delivery:
        notes.append("Nie znaleziono zapisu o sposobie doręczenia.")
    return TerminationParse(
        TerminationRule(
            period_kind=kind,
            period_months=value if unit == "months" else None,
            period_days=value if unit == "days" else None,
            period_clause=_clause(sentence),
            forms=forms,
            under_nullity=nullity,
            form_clause=_clause(form_sentence) if form_sentence else None,
            delivery=delivery,
            delivery_clause=_clause(delivery_sentence) if delivery_sentence else None,
            notes=tuple(notes),
        ),
        None,
    )
