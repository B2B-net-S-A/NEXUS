"""Dowody wymagań z CV dla panelu klienta (02.11.2026). Czyste funkcje, bez AI.

Dowód to wyłącznie treść pliku, który poszedł do klienta. Screening, notatki
i ramka „Dlaczego nasz kandydat” nie są dowodem, a edukacja i klauzula zgody
się nie liczą, bo nie mówią, czego osoba używała w pracy.

Status wymagania:

- ``project``: stoi w opisie doświadczenia (firma i daty w dowodzie),
- ``list``: stoi tylko w umiejętnościach, certyfikatach albo językach,
- ``none``: nie ma go w CV albo Delivery Lead odrzucił dowód.

Wejściem jest HTML CV etapu: ten sam, z którego renderuje się plik Word, także
dla pliku wgranego (``cv_docx_import`` zapisuje go w tym samym kształcie).
Dopasowanie technologii to te same pętle, które pogrubiają je w CV
(``docx_renderer``). Wymaganie bez technologii („aplikacji webowych”) dopasowuje
się po rdzeniach słów, zawsze z granicą wyrazu, więc „webhook” nie jest aplikacją
webową, a BigQuery do analiz nie jest chmurą.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Literal, Optional

from lxml import html as lxml_html
from lxml.etree import ParserError

from app.services.cv_approved_docx import _SECTION_TITLES, _TECH_LABELS, _norm_title
from app.services.cv_generator_b2b.docx_renderer import (
    _WORD_CHARS,
    _core_keyword,
    _extract_keyword_terms,
    _is_generic_phrase,
    compile_keyword_patterns,
    highlight_spans,
)
from app.services.cv_rodo_clause import is_rodo_text

Status = Literal["project", "list", "none"]

MAX_ITEMS = 3
QUOTE_MAX = 220

_LIST_SECTIONS = {
    "skills": "Umiejętności",
    "certifications": "Certyfikaty",
    "languages": "Języki",
}
_SECTION_MARKERS = {*_LIST_SECTIONS, "experience", "why_points", "education"}
_DATES_RE = re.compile(
    r"(?:\d{2}[./])?\d{4}\s*[-–—]\s*(?:(?:\d{2}[./])?\d{4}|obecnie|present|now|nadal)\s*$",
    re.IGNORECASE,
)
_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}
_WS_RE = re.compile(r"\s+")
_POLISH_ENDINGS = (
    "ych",
    "ich",
    "ami",
    "ach",
    "owi",
    "ego",
    "emu",
    "ymi",
    "imi",
    "ów",
    "om",
    "em",
    "ie",
    "ia",
    "y",
    "i",
    "e",
    "a",
    "ą",
    "ę",
    "u",
    "o",
)
_MIN_STEM = 4
_WORD_GAP = r"(?:[\s\-/,]+[^\s]+){0,2}[\s\-/,]+"

# Pojęcia z synonimami, których nie dadzą rdzenie słów. Lista jest krótka, bo
# każdy wpis to decyzja, co klient uzna za dowód. „Chmura” nie obejmuje usług
# pojedynczego dostawcy (BigQuery, S3), tylko samego dostawcę.
_CONCEPTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\baplikacj\w*\s+(webow|internetow)|\bweb\s*app", re.I),
        r"aplikacj\w*\s+(?:webow|internetow)\w*|web\s*app\w*|web\s+application\w*",
    ),
    (
        re.compile(r"\bmikro[\s-]*(us[łl]ug|serwis)|\bmicro[\s-]*service", re.I),
        r"mikro[\s-]*(?:us[łl]ug|serwis)\w*|micro[\s-]*services?",
    ),
    (
        re.compile(r"^(?:\w+\s+)?(?:chmur\w*|cloud)$", re.I),
        r"chmur\w*|cloud|AWS|Azure|GCP|Google\s+Cloud",
    ),
)


@dataclass(frozen=True)
class Requirement:
    key: str
    label: str


@dataclass(frozen=True)
class Block:
    """Akapit albo punkt CV, który może być dowodem."""

    kind: Literal["project", "list"]
    text: str
    where: Optional[str] = None
    dates: Optional[str] = None
    # Sama wzmianka w wierszu „Technologie:”, bez opisu, co osoba robiła.
    bare: bool = False
    # Nazwa stanowiska: dowód, ale słabszy niż opis pracy.
    heading: bool = False

    @property
    def rank(self) -> int:
        return 2 if self.bare else 1 if self.heading else 0


@dataclass(frozen=True)
class EvidenceItem:
    kind: Literal["project", "list"]
    quote: str
    term: str
    where: Optional[str]
    dates: Optional[str]
    bare: bool = False


@dataclass(frozen=True)
class Evidence:
    status: Status
    items: tuple[EvidenceItem, ...] = ()

    @property
    def weak(self) -> bool:
        """Dowód do sprawdzenia przez Delivery Leada: sama lista albo technologie."""
        if self.status == "list":
            return True
        return self.status == "project" and all(item.bare for item in self.items)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "l"))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def requirement_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(label)).strip("-")


def requirements_from_job(
    must_skills: Optional[Iterable[Any]], nice_skills: Optional[Iterable[Any]]
) -> list[Requirement]:
    """Wymagania rekrutacji: nazwy z ``must_skills`` i ``nice_skills``, bez powtórek."""
    out: dict[str, Requirement] = {}
    for item in [*(must_skills or []), *(nice_skills or [])]:
        label = item.get("name") if isinstance(item, dict) else item
        if not isinstance(label, str) or not (label := _WS_RE.sub(" ", label).strip()):
            continue
        key = requirement_key(label)
        if key and key not in out:
            out[key] = Requirement(key=key, label=label)
    return list(out.values())


def _stem(word: str) -> str:
    lowered = word.casefold()
    for ending in _POLISH_ENDINGS:
        if lowered.endswith(ending) and len(lowered) - len(ending) >= _MIN_STEM:
            return lowered[: -len(ending)]
    return lowered


def _stem_pattern(term: str) -> Optional[re.Pattern[str]]:
    core = _core_keyword(term).strip()
    if len(core) < 2 or _is_generic_phrase(core):
        return None
    words = [word for word in re.split(r"[\s/]+", core) if word]
    if not words:
        return None
    body = _WORD_GAP.join(
        re.escape(_stem(word)) + rf"[{_WORD_CHARS}]*" for word in words
    )
    return re.compile(rf"(?<![{_WORD_CHARS}]){body}", re.IGNORECASE)


@lru_cache(maxsize=512)
def patterns_for(label: str) -> tuple[re.Pattern[str], ...]:
    """Wzorce wymagania: technologie jak w CV, a bez nich rdzenie słów.

    Lista panelu liczy każde wymaganie dla każdej osoby przy każdym wejściu.
    """
    patterns: list[re.Pattern[str]] = []
    for term in _extract_keyword_terms(label) or [label]:
        technical = compile_keyword_patterns([term])
        patterns.extend(technical)
        concept = next((p for test, p in _CONCEPTS if test.search(term.strip())), None)
        if concept is not None:
            patterns.append(
                re.compile(
                    rf"(?<![{_WORD_CHARS}])(?:{concept})(?![{_WORD_CHARS}])",
                    re.IGNORECASE,
                )
            )
        elif not technical and (stemmed := _stem_pattern(term)) is not None:
            patterns.append(stemmed)
    return tuple(patterns)


def _text(node: Any) -> str:
    return _WS_RE.sub(" ", "".join(node.itertext())).strip()


def _employer(text: str) -> str:
    # „Booksy Inc. · IT”: branża nie jest częścią nazwy firmy.
    return text.split("·", 1)[0].strip()


def _role(text: str) -> tuple[str, Optional[str]]:
    match = _DATES_RE.search(text)
    if match is None:
        return text, None
    return text[: match.start()].strip(), match.group(0).strip()


def blocks_from_html(document: Optional[str]) -> list[Block]:
    """Sekcje CV z HTML-a etapu; czego nie rozpozna, nie jest dowodem."""
    if not document or not document.strip():
        return []
    try:
        root = lxml_html.fromstring(document)
    except (ParserError, ValueError):
        return []
    blocks: list[Block] = []
    section: Optional[str] = None
    where: Optional[str] = None
    dates: Optional[str] = None
    for node in root.iter():
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag not in _BLOCK_TAGS:
            continue
        text = _text(node)
        if not text:
            continue
        marker = node.get("data-cv-section")
        title = _SECTION_TITLES.get(_norm_title(text))
        if marker in _SECTION_MARKERS or title is not None or tag == "h1":
            section = marker if marker in _SECTION_MARKERS else title
            where, dates = None, None
            continue
        if (
            marker == "rodo"
            or "rodo" in (node.get("class") or "")
            or is_rodo_text(text)
        ):
            continue
        if section in _LIST_SECTIONS:
            blocks.append(Block("list", text, where=_LIST_SECTIONS[section]))
            continue
        if section != "experience":
            continue
        css = node.get("class") or ""
        if marker == "role" or "job-head" in css:
            position, dates = _role(text)
            where = None
            blocks.append(Block("project", position, dates=dates, heading=True))
            continue
        if marker == "employer" or "job-co" in css:
            where = _employer(text)
            # Stanowisko stoi przed firmą: dokładamy firmę do jego wiersza.
            if blocks and blocks[-1].heading and blocks[-1].where is None:
                last = blocks[-1]
                blocks[-1] = Block(
                    "project", last.text, where=where, dates=last.dates, heading=True
                )
            continue
        if marker == "duties_label":
            continue
        if marker == "technologies" or text.startswith(_TECH_LABELS):
            blocks.append(Block("project", text, where=where, dates=dates, bare=True))
            continue
        blocks.append(Block("project", text, where=where, dates=dates))
    return blocks


def _quote(text: str, start: int, end: int) -> str:
    """Dosłowny fragment CV, bo front szuka go w PDF-ie; bez wielokropków."""
    if len(text) <= QUOTE_MAX:
        return text
    left = max(0, start - (QUOTE_MAX - (end - start)) // 2)
    right = min(len(text), left + QUOTE_MAX)
    left = max(0, right - QUOTE_MAX)
    if left > 0 and (space := text.find(" ", left, start)) != -1:
        left = space + 1
    if right < len(text) and (space := text.rfind(" ", end, right)) != -1:
        right = space
    return text[left:right].strip()


def _item(block: Block, span: tuple[int, int]) -> EvidenceItem:
    start, end = span
    return EvidenceItem(
        kind=block.kind,
        quote=_quote(block.text, start, end),
        term=block.text[start:end],
        where=block.where,
        dates=block.dates,
        bare=block.bare,
    )


def evidence_for(
    blocks: Iterable[Block], label: str, *, rejected: bool = False
) -> Evidence:
    """Status i dowody jednego wymagania."""
    if rejected:
        return Evidence("none")
    patterns = list(patterns_for(label))
    projects: dict[tuple[Optional[str], Optional[str]], tuple[int, EvidenceItem]] = {}
    listed: list[EvidenceItem] = []
    for block in blocks:
        spans = highlight_spans(block.text, patterns)
        if not spans:
            continue
        item = _item(block, spans[0])
        if block.kind == "list":
            listed.append(item)
            continue
        # Jeden dowód na stanowisko: opis pracy, potem nazwa, potem technologie.
        job = (block.where, block.dates)
        if job not in projects or block.rank < projects[job][0]:
            projects[job] = (block.rank, item)
    if projects:
        items = [item for _, item in projects.values()]
        return Evidence("project", tuple(items[:MAX_ITEMS]))
    if listed:
        return Evidence("list", tuple(listed[:MAX_ITEMS]))
    return Evidence("none")


def evidence_map(
    document: Optional[str],
    requirements: Iterable[Requirement],
    rejected: Iterable[str] = (),
) -> dict[str, Evidence]:
    blocks = blocks_from_html(document)
    refused = set(rejected)
    return {
        req.key: evidence_for(blocks, req.label, rejected=req.key in refused)
        for req in requirements
    }


def counts(evidence: dict[str, Evidence]) -> tuple[int, int, int]:
    """Ile wymagań w projektach, ile tylko na liście, ilu brakuje."""
    statuses = [item.status for item in evidence.values()]
    return statuses.count("project"), statuses.count("list"), statuses.count("none")
