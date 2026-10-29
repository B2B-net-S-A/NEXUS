"""„Karta przed CV” — odczyt wzoru Worda klienta, wartości i zapis pliku. Bez AI, bez bazy.

Credit Agricole wymaga z każdym CV jednostronicowej karty dostawcy (decyzje
Artura 29.10.2026, ``docs/claude/generator-cv/karta-przed-cv-credit-agricole.md``).
Wzór to zwykły dokument z akapitami „Etykieta: xxx” — bez tabel, bez pól
formularza:

* ``Imie i nazwisko`` — cały akapit jest miejscem na imię i nazwisko,
* ``Rola: xxx``, ``Profil kompetencji: xxx``, ``Lokalizacja: xxxxxx``,
* ``Poziom doświadczenia: Junior/Specjalista/Expert`` — lista do wyboru,
* ``Staż: x doświadczenia komercyjnego`` — tylko „x” zamienia się na „7 lat”,
* ``Dostępność: xx.xxxx`` i ``Lokalizacja:`` w jednym akapicie, rozdzielone
  złamaniem wiersza,
* ``Wynagrodzenie: xxxx,00 PLN netto za 1 MD``.

Pole znajduje się po etykiecie (bez wielkości liter i polskich znaków),
a zmienia się wyłącznie miejsce na wartość za etykietą — do złamania wiersza
albo następnej etykiety — z formatowaniem przebiegu, w którym stało. Reszta
dokumentu (nagłówek, blok „Opiekun po stronie dostawcy” z łączami) zostaje
bajt w bajt. Tabel wzór nie ma i ten moduł ich nie czyta.
"""

from __future__ import annotations

import copy
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from html.parser import HTMLParser
from typing import Any, Iterable, Optional

from docx.text.run import Run

from app.services import client_form_structure

NAME = "name"
ROLE = "role"
LEVEL = "level"
EXPERIENCE = "experience"
PROFILE = "profile"
AVAILABILITY = "availability"
LOCATION = "location"
RATE = "rate"

# Kolejność pól na karcie i ich nazwy w interfejsie.
FIELD_LABELS: dict[str, str] = {
    NAME: "Imię i nazwisko",
    ROLE: "Rola",
    LEVEL: "Poziom doświadczenia",
    EXPERIENCE: "Staż",
    PROFILE: "Profil kompetencji",
    AVAILABILITY: "Dostępność",
    LOCATION: "Lokalizacja",
    RATE: "Wynagrodzenie",
}
# Etykieta wzoru po normalizacji → pole.
_LABEL_FIELDS: dict[str, str] = {
    "imie i nazwisko": NAME,
    "rola": ROLE,
    "poziom doswiadczenia": LEVEL,
    "staz": EXPERIENCE,
    "profil kompetencji": PROFILE,
    "dostepnosc": AVAILABILITY,
    "lokalizacja": LOCATION,
    "wynagrodzenie": RATE,
}
# Mniej rozpoznanych etykiet to nie karta, tylko inny dokument.
MIN_FIELDS = 4
MAX_TEMPLATE_BYTES = 5 * 1024 * 1024

LEVELS = ("Junior", "Specjalista", "Expert")

MSG_NOT_DOCX = "Wzór karty musi być plikiem Word (.docx)."
MSG_BROKEN = "Nie da się odczytać pliku Word — zapisz go w Wordzie od nowa."
MSG_TOO_BIG = "Plik Word jest za duży (najwyżej 5 MB)."
MSG_MACROS = "Plik z makrami nie może być wzorem — zapisz go jako zwykły .docx."
MSG_NOT_SHEET = (
    "NEXUS nie rozpoznał w tym pliku karty przed CV — potrzebne są co najmniej "
    "4 etykiety z: Imię i nazwisko, Rola, Poziom doświadczenia, Staż, Profil "
    "kompetencji, Dostępność, Lokalizacja, Wynagrodzenie."
)

# Komunikaty kontroli paczki formularza CV → zdania o karcie.
_PACKAGE_MESSAGES = {
    client_form_structure.MSG_NOT_DOCX: MSG_NOT_DOCX,
    client_form_structure.MSG_BROKEN: MSG_BROKEN,
    client_form_structure.MSG_TOO_BIG: MSG_TOO_BIG,
    client_form_structure.MSG_MACROS: MSG_MACROS,
}


class SheetRejected(Exception):
    """Plik nie nadaje się na wzór karty — zdanie dla użytkownika."""


# ── Normalizacja ─────────────────────────────────────────────────────────────

_EXTRA_BASE = {"ł": "l", "Ł": "l"}


def _fold_char(char: str) -> str:
    """Jeden znak → mała litera bez ogonka; długość tekstu się nie zmienia."""
    if char in _EXTRA_BASE:
        return _EXTRA_BASE[char]
    base = unicodedata.normalize("NFKD", char)[:1] or char
    return base.lower() if len(base.lower()) == 1 else char


def fold(text: str) -> str:
    return "".join(_fold_char(char) for char in text)


_LABEL_RE = re.compile(
    r"(?<![a-z0-9])("
    + "|".join(r"\s+".join(map(re.escape, label.split())) for label in _LABEL_FIELDS)
    + r")\s*\*?\s*:"
)
_PLACEHOLDER_RE = re.compile(r"(?<![a-z0-9])x+(?:[ .,]x+)*(?![a-z0-9])")
_RATE_PLACEHOLDER_RE = re.compile(r"(?<![a-z0-9])x+(?:[ .]x+)*(?:,00|,xx)?(?![a-z0-9])")
_LEVELS_RE = re.compile(r"junior\s*/\s*specjalista\s*/\s*expert")


def _label_key(raw: str) -> str:
    return " ".join(fold(raw).split())


# ── Odczyt wzoru ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Slot:
    """Miejsce na wartość pola: akapit, przebiegi segmentu i zakres znaków."""

    field: str
    label: str  # etykieta ze wzoru, np. „Rola:”
    paragraph: int
    runs: tuple[int, ...]  # indeksy w ``paragraph.runs``
    start: int  # zakres miejsca na wartość w tekście segmentu
    end: int
    region_end: int  # koniec segmentu pola (do łamania wiersza / etykiety)
    suffix: str  # tekst wzoru za miejscem na wartość („ doświadczenia komercyjnego”)


@dataclass(frozen=True)
class SheetStructure:
    slots: tuple[Slot, ...]
    # Układ do podglądu: {"kind": "field", "id"} albo {"kind": "text", "text", "bold"}.
    layout: tuple[dict[str, Any], ...]

    def fields(self) -> list[dict[str, str]]:
        return [
            {"id": slot.field, "label": FIELD_LABELS[slot.field]} for slot in self.slots
        ]

    def slot(self, field: str) -> Optional[Slot]:
        return next((slot for slot in self.slots if slot.field == field), None)


def _split_break_runs(paragraph: Any) -> None:
    """Przebieg „tekst + złamanie + tekst” → osobne przebiegi z tym samym
    formatowaniem. Word po Shift+Enter potrafi zapisać złamanie w jednym
    przebiegu z następną etykietą („\\nLokalizacja:”) — bez podziału etykieta
    znikałaby razem z przebiegiem-granicą."""
    for run in list(paragraph.runs):
        text = run.text
        if "\n" not in text or text == "\n":
            continue
        parts = text.split("\n")
        run.text = parts[0]
        anchor = run._r
        for part in parts[1:]:
            for piece in ("\n", part):
                if not piece:
                    continue
                clone = copy.deepcopy(run._r)
                anchor.addnext(clone)
                Run(clone, run._parent).text = piece
                anchor = clone
        if not parts[0]:
            run._r.getparent().remove(run._r)


def _segments(paragraph: Any) -> list[list[int]]:
    """Przebiegi akapitu podzielone na złamaniach wiersza.

    Przebieg ze złamaniem jest granicą i sam do żadnego segmentu nie należy —
    tak jak ``'\\n'`` między „Dostępność” a „Lokalizacja” we wzorze CA.
    """
    out: list[list[int]] = [[]]
    for index, run in enumerate(paragraph.runs):
        if "\n" in run.text:
            out.append([])
            continue
        out[-1].append(index)
    return [segment for segment in out if segment]


def _placeholder(field: str, folded: str, start: int, end: int) -> tuple[int, int]:
    region = folded[start:end]
    if field == LEVEL:
        match = _LEVELS_RE.search(region)
        if match:
            return start + match.start(), start + match.end()
    pattern = _RATE_PLACEHOLDER_RE if field == RATE else _PLACEHOLDER_RE
    match = pattern.search(region)
    if match:
        return start + match.start(), start + match.end()
    # Bez „xxx”: miejscem jest cała treść za etykietą (albo jej koniec).
    stripped = region.strip()
    if not stripped:
        return end, end
    lead = len(region) - len(region.lstrip())
    return start + lead, start + lead + len(stripped)


def _segment_slots(paragraph: Any, p_index: int, segment: list[int]) -> list[Slot]:
    texts = [paragraph.runs[i].text for i in segment]
    text = "".join(texts)
    folded = fold(text)
    matches = list(_LABEL_RE.finditer(folded))
    slots: list[Slot] = []
    if not matches:
        # „Imie i nazwisko” bez dwukropka: cały segment to miejsce na wartość.
        if _LABEL_FIELDS.get(_label_key(text)) == NAME:
            lead = len(text) - len(text.lstrip())
            stripped = text.strip()
            slots.append(
                Slot(
                    field=NAME,
                    label="",
                    paragraph=p_index,
                    runs=tuple(segment),
                    start=lead,
                    end=lead + len(stripped),
                    region_end=len(text),
                    suffix="",
                )
            )
        return slots
    for position, match in enumerate(matches):
        field = _LABEL_FIELDS[_label_key(match.group(1))]
        region_end = (
            matches[position + 1].start() if position + 1 < len(matches) else len(text)
        )
        start, end = _placeholder(field, folded, match.end(), region_end)
        slots.append(
            Slot(
                field=field,
                label=text[match.start() : match.end()].strip(),
                paragraph=p_index,
                runs=tuple(segment),
                start=start,
                end=end,
                region_end=region_end,
                suffix=text[end:region_end].rstrip(),
            )
        )
    return slots


def _open(content: bytes) -> Any:
    if len(content) > MAX_TEMPLATE_BYTES:
        raise SheetRejected(MSG_TOO_BIG)
    try:
        return client_form_structure.open_document(content)
    except client_form_structure.FormRejected as exc:
        raise SheetRejected(_PACKAGE_MESSAGES.get(str(exc), MSG_BROKEN)) from exc


def _structure(document: Any) -> SheetStructure:
    slots: list[Slot] = []
    seen: set[str] = set()
    layout: list[dict[str, Any]] = []
    for p_index, paragraph in enumerate(document.paragraphs):
        _split_break_runs(paragraph)
        found: list[Slot] = []
        for segment in _segments(paragraph):
            for slot in _segment_slots(paragraph, p_index, segment):
                if slot.field in seen:
                    continue
                seen.add(slot.field)
                found.append(slot)
        if found:
            slots.extend(found)
            layout.extend({"kind": "field", "id": slot.field} for slot in found)
            continue
        runs = [run for run in paragraph.runs if run.text.strip()]
        bold = bool(runs) and all(run.bold for run in runs)
        # ``paragraph.text`` niesie też tekst łączy (adresy e-mail opiekunów).
        for line in paragraph.text.split("\n"):
            if line.strip():
                layout.append({"kind": "text", "text": line.strip(), "bold": bold})
    return SheetStructure(slots=tuple(slots), layout=tuple(layout))


def read_template(content: bytes) -> SheetStructure:
    """Pola wzoru karty; odmowa (nie DOCX, makra, za mało etykiet) = ``SheetRejected``."""
    structure = _structure(_open(content))
    if len(structure.slots) < MIN_FIELDS:
        raise SheetRejected(MSG_NOT_SHEET)
    return structure


# ── Zapis pliku ──────────────────────────────────────────────────────────────


def _replace(runs: list[Any], start: int, end: int, new: str) -> None:
    """Zamień znaki ``[start, end)`` segmentu na ``new`` — w przebiegu, gdzie
    zaczyna się miejsce na wartość, z jego formatowaniem."""
    position = 0
    inserted = False
    for index, run in enumerate(runs):
        text = run.text
        run_start, run_end = position, position + len(text)
        position = run_end
        if start == end:
            # Wstawienie: do przebiegu, w którym punkt leży wewnątrz, albo za
            # ostatnim przebiegiem segmentu.
            last = index == len(runs) - 1
            if inserted or not (
                run_start <= start < run_end or (last and start == run_end)
            ):
                continue
            local = start - run_start
            if run.bold and local == len(text):
                # Za pogrubioną etykietą: nowy przebieg bez pogrubienia.
                clone = copy.deepcopy(run._r)
                run._r.addnext(clone)
                added = Run(clone, run._parent)
                added.text = new
                added.bold = False
            else:
                run.text = text[:local] + new + text[local:]
            inserted = True
            continue
        if run_end <= start or run_start >= end:
            continue
        local_start = max(start, run_start) - run_start
        local_end = min(end, run_end) - run_start
        if not inserted:
            run.text = text[:local_start] + new + text[local_end:]
            inserted = True
        else:
            run.text = text[:local_start] + text[local_end:]


# Znaki, których XML Worda nie przyjmie (sterujące, U+FFFE/U+FFFF, połówki
# surogatów) — lxml rzuca na nich przy zapisie, a imię albo tytuł rekrutacji
# wyciągnięty z PDF-a potrafi je nieść.
_NOT_IN_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


def clean_value(raw: Optional[str]) -> str:
    """Wartość pola gotowa do Worda: bez znaków spoza XML, jedna linia."""
    return " ".join(_NOT_IN_XML.sub("", raw or "").split())


def render(content: bytes, values: dict[str, str]) -> bytes:
    """Wzór z wpisanymi wartościami. Puste pole: znika miejsce na wartość
    i tekst wzoru za nim („x doświadczenia komercyjnego” → nic)."""
    document = _open(content)
    structure = _structure(document)
    # Od końca akapitu: wstawiony przebieg albo zmiana długości tekstu nie
    # przesuwa pól, które stoją wcześniej. Pozycja przebiegu, nie znaku —
    # znaki liczą się od początku własnego wiersza (segmentu).
    order = sorted(
        structure.slots, key=lambda s: (s.paragraph, s.runs[0], s.start), reverse=True
    )
    for slot in order:
        paragraph = document.paragraphs[slot.paragraph]
        runs = [paragraph.runs[i] for i in slot.runs]
        value = clean_value(values.get(slot.field))
        if value:
            start, end = slot.start, slot.end
            if start == end == slot.region_end:
                text = "".join(run.text for run in runs)
                if not text[:start].endswith((" ", "\t")):
                    value = " " + value
            _replace(runs, start, end, value)
        else:
            _replace(runs, slot.start, slot.region_end, "")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


# ── Wartości ─────────────────────────────────────────────────────────────────


def level_for_years(years: Optional[float]) -> Optional[str]:
    """< 3 lata — Junior, 3–7 — Specjalista, od 8 — Expert (decyzja 29.10.2026)."""
    if years is None or years < 0:
        return None
    if years < 3:
        return "Junior"
    if years < 8:
        return "Specjalista"
    return "Expert"


def years_word(count: int) -> str:
    """1 rok, 2–4 lata, 5–21 lat, 22–24 lata… (polska liczba mnoga)."""
    if count == 1:
        return "rok"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "lata"
    return "lat"


def experience_text(years: Optional[int]) -> Optional[str]:
    if years is None or years < 0:
        return None
    return f"{years} {years_word(years)}"


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    # Ostatni dzień miesiąca, gdy dzień wypada poza nim (31.01 + 1 mies.).
    for candidate_day in range(day.day, 27, -1):
        try:
            return date(year, month, candidate_day)
        except ValueError:
            continue
    return date(year, month, min(day.day, 28))


def _notice_label(count: int, unit: str) -> str:
    if unit == "months":
        return f"{count} mies."
    if unit == "weeks":
        return f"{count} tyg."
    return f"{count} {'dzień' if count == 1 else 'dni'}"


def availability_text(
    *,
    available_from: Optional[date],
    notice_period: Optional[int],
    notice_unit: Optional[str],
    today: date,
) -> Optional[str]:
    """„MM.RRRR” z daty dostępności albo z okresu wypowiedzenia od dziś.

    Data z przeszłości to „od teraz” — karta nie może podać klientowi
    miesiąca, który minął.
    """
    if available_from is not None:
        day = max(available_from, today)
        return f"{day.month:02d}.{day.year}"
    if notice_period and notice_period > 0:
        unit = notice_unit or "days"  # NULL = dni (stare profile)
        if unit == "months":
            day = _add_months(today, notice_period)
        elif unit == "weeks":
            day = today + timedelta(weeks=notice_period)
        else:
            day = today + timedelta(days=notice_period)
        label = _notice_label(notice_period, unit)
        return f"{day.month:02d}.{day.year} ({label} wypowiedzenia)"
    return None


HOURS_PER_MD = 8


def md_rate(value: Optional[float], unit: Optional[str]) -> Optional[Decimal]:
    """Stawka za 1 MD: godzinowa × 8, dzienna bez zmian; miesięcznej nie przeliczamy."""
    if value is None or value <= 0:
        return None
    amount = Decimal(str(value))
    if unit == "hourly":
        amount *= HOURS_PER_MD
    elif unit != "daily":
        return None
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def amount_text(amount: Decimal) -> str:
    """1298.64 → „1 298,64”, 1300 → „1 300,00”."""
    whole, _, cents = f"{amount:,.2f}".partition(".")
    return f"{whole.replace(',', ' ')},{cents}"


class _WhyBold(HTMLParser):
    """Pogrubienia z sekcji „Dlaczego nasz kandydat” CV firmowego."""

    _HEADINGS = {"h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.heading: Optional[str] = None  # tekst bieżącego nagłówka
        self.bold_depth = 0
        self.current: list[str] = []
        self.terms: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in self._HEADINGS:
            section = dict(attrs).get("data-cv-section")
            self.inside = section == "why_points"
            self.heading = "" if section is None else None
        elif tag in ("b", "strong") and self.inside:
            self.bold_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HEADINGS:
            if self.heading is not None and "dlaczego" in fold(self.heading):
                self.inside = True
            self.heading = None
        elif tag in ("b", "strong") and self.bold_depth:
            self.bold_depth -= 1
            if not self.bold_depth:
                self.terms.append("".join(self.current))
                self.current = []

    def handle_data(self, data: str) -> None:
        if self.heading is not None:
            self.heading += data
        if self.bold_depth:
            self.current.append(data)


PROFILE_MAX_TERMS = 12
VALUE_MAX = 500


def _unique(terms: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in terms:
        term = " ".join(raw.split()).strip(" ,;:.-–")
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            out.append(term)
    return out[:PROFILE_MAX_TERMS]


def profile_from_cv_html(html: Optional[str]) -> list[str]:
    if not html:
        return []
    parser = _WhyBold()
    parser.feed(html)
    parser.close()
    return _unique(parser.terms)


def _skill_names(items: Any) -> list[str]:
    names: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return names


def profile_from_skills(must_skills: Any, candidate_skills: Any) -> list[str]:
    """Umiejętności obowiązkowe rekrutacji, które osoba ma w profilu."""
    have = {fold(name).strip() for name in _skill_names(candidate_skills)}
    return _unique(
        name for name in _skill_names(must_skills) if fold(name).strip() in have
    )
