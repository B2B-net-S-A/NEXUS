"""Ogłoszenie w formatach portali — czyste funkcje, bez bazy i bez modelu.

Jedna treść (``content`` + ``tech``), dwa formaty:

* Pracuj.pl — osobne pola w kolejności formularza portalu,
* JustJoin.IT — pola formularza, tech stack z poziomem i jeden opis (HTML
  oraz zwykły tekst).

Front kopiuje WYŁĄCZNIE teksty policzone tutaj dla zapisanego stanu, więc
portale nie dostają dwóch różnych wersji tej samej rekrutacji, a kontrola
(``lint``) widzi dokładnie to, co trafia do schowka. Każdy tekst idący do
HTML przechodzi przez ``html.escape``.

Widełek tu nie ma: wpisuje je człowiek w formularzu portalu (decyzja Artura
25.09.2026), a w treści ogłoszenia kwot nie podajemy.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.services.job_ad.fixed_blocks import (
    SUFFIX_KM,
    SUFFIX_KMX,
    LangBlocks,
)
from app.services.job_ad.material import AdMaterial
from app.services.job_ad.text import visible
from app.services.job_ad_schema import LANG_EN
from app.services.champion_requirement_rows import (
    ALTERNATIVE_JOINER,
    KEYWORD_MAX_CHARS,
    KEYWORD_MAX_WORDS,
)
from app.services.job_portals import jjit_payload

LEVEL_CRITICAL = "critical"
LEVEL_MUST = "must"
LEVEL_NICE = "nice"
TECH_LEVELS = (LEVEL_CRITICAL, LEVEL_MUST, LEVEL_NICE)

# Skala JustJoin.IT: 1 Nice to have · 2 Junior · 3 Regular · 4 Advanced · 5 Master.
_JJIT_LEVEL = {
    LEVEL_CRITICAL: (4, "Advanced"),
    LEVEL_MUST: (3, "Regular"),
    LEVEL_NICE: (1, "Nice to have"),
}
JJIT_TECH_LIMIT = jjit_payload.REQUIRED_LIMIT[jjit_payload.BOARD_JJIT]

_GENDER_MARKER = re.compile(
    r"\((?:k/m(?:/x)?|m/k(?:/n)?|f/m(?:/x)?|m/f(?:/[dx])?|m/w/d)\)\s*$",
    re.IGNORECASE,
)
_SUFFIX = {
    SUFFIX_KMX: {"pl": "(k/m/x)", "en": "(f/m/x)"},
    SUFFIX_KM: {"pl": "(k/m)", "en": "(f/m)"},
}

_HEADINGS = {
    "pl": {
        "about": "O projekcie",
        "terms": "Warunki współpracy",
        "responsibilities": "Twój zakres obowiązków",
        "requirements": "Wymagania",
        "nice_to_have": "Mile widziane",
        "offer": "Co oferujemy",
        "process": "Jak wygląda proces",
    },
    "en": {
        "about": "About the project",
        "terms": "Terms of cooperation",
        "responsibilities": "Your responsibilities",
        "requirements": "Requirements",
        "nice_to_have": "Nice to have",
        "offer": "What we offer",
        "process": "Recruitment process",
    },
}

_EXPERIENCE_LABELS = {"junior": "Junior", "mid": "Mid", "senior": "Senior"}
_WORKING_TIME_LABELS = {"full_time": "Full-time", "part_time": "Part-time"}
_WORKPLACE_LABELS = {"remote": "Remote", "hybrid": "Hybrid", "office": "Office"}


@dataclass(frozen=True)
class Terms:
    """Warunki z rekrutacji; start, długość i język pracy niesie treść ogłoszenia."""

    contract: str
    remote_policy: Optional[str]
    onsite_days_per_week: Optional[int]
    onsite_days_per_month: Optional[int]
    city: Optional[str]
    start: Optional[str]
    duration: Optional[str]
    language: Optional[str]
    seniority: Optional[str]
    working_time: Optional[str]


def terms_from(material: AdMaterial, content: dict[str, Any]) -> Terms:
    return Terms(
        contract=material.contract,
        remote_policy=material.remote_policy,
        onsite_days_per_week=material.onsite_days_per_week,
        onsite_days_per_month=material.onsite_days_per_month,
        city=_clean(content.get("city")) or material.city,
        start=_clean(content.get("start")) or None,
        duration=_clean(content.get("duration")) or None,
        language=_clean(content.get("language")) or None,
        seniority=material.seniority,
        working_time=material.working_time,
    )


def _clean(value: Any) -> str:
    return " ".join(visible(str(value or "")).split())


def _items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [text for text in (_clean(item) for item in value) if text]


def _lang(lang: str) -> str:
    return "en" if lang == LANG_EN else "pl"


def titled(title: str, lang: str, suffix: str) -> str:
    """Tytuł z dopiskiem — jedna konwencja zamiast sześciu z pomiaru 12.10.2026."""
    text = _clean(title)
    marker = _SUFFIX.get(suffix, {}).get(_lang(lang))
    if not text or not marker or _GENDER_MARKER.search(text):
        return text
    return f"{text} {marker}"


def _days(count: int, lang: str) -> str:
    if lang == "en":
        return f"{count} day" if count == 1 else f"{count} days"
    return f"{count} dzień" if count == 1 else f"{count} dni"


def _workplace_line(terms: Terms, lang: str) -> Optional[str]:
    mode, city = terms.remote_policy, terms.city
    if mode == "remote":
        return "remote work" if lang == "en" else "praca zdalna"
    if mode == "onsite":
        base = "on-site work" if lang == "en" else "praca stacjonarna"
        return f"{base} ({city})" if city else base
    if mode != "hybrid":
        return None
    base = "hybrid work" if lang == "en" else "praca hybrydowa"
    if terms.onsite_days_per_week:
        days = _days(terms.onsite_days_per_week, lang)
        where = "per week in the office" if lang == "en" else "w tygodniu w biurze"
        base = f"{base}: {days} {where}"
    elif terms.onsite_days_per_month:
        days = _days(terms.onsite_days_per_month, lang)
        where = "per month in the office" if lang == "en" else "w miesiącu w biurze"
        base = f"{base}: {days} {where}"
    # Miasto w nawiasie: forma „w Warszawie” wymagałaby odmiany nazwy.
    return f"{base} ({city})" if city else base


def term_lines(terms: Terms, lang: str) -> list[str]:
    """Warunki składane z pól rekrutacji — bez modelu, więc bez zmyśleń."""
    code = _lang(lang)
    en = code == "en"
    lines = [f"{terms.contract} contract" if en else f"kontrakt {terms.contract}"]
    workplace = _workplace_line(terms, code)
    if workplace:
        lines.append(workplace)
    if terms.start:
        lines.append(f"start: {terms.start}")
    if terms.duration:
        lines.append(
            f"duration: {terms.duration}" if en else f"czas trwania: {terms.duration}"
        )
    if terms.language:
        lines.append(
            f"working language: {terms.language}"
            if en
            else f"język pracy: {terms.language}"
        )
    return lines


def clean_tech(value: Any) -> list[dict[str, str]]:
    """Technologie w stałym kształcie, bez duplikatów i pustych nazw."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value if isinstance(value, (list, tuple)) else []:
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name"))[:100]
        level = item.get("level")
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        out.append(
            {"name": name, "level": level if level in TECH_LEVELS else LEVEL_MUST}
        )
    return out


def _tech_names(label: str) -> list[str]:
    """Nazwy technologii z etykiety wymagania.

    Etykieta bywa zdaniem klienta („min. 5 lat w bankowości…”) albo wierszem
    z zamiennikami („Kafka lub RabbitMQ”). Lista technologii portalu bierze
    tylko krótkie pozycje — zdanie zostaje w wymaganiach, których pilnuje model.
    """
    names = []
    for part in label.split(ALTERNATIVE_JOINER):
        name = _clean(part)
        if (
            name
            and len(name) <= KEYWORD_MAX_CHARS
            and len(name.split()) <= KEYWORD_MAX_WORDS
        ):
            names.append(name)
    return names


def tech_from_material(material: AdMaterial) -> list[dict[str, str]]:
    critical = {name.casefold() for name in material.critical}
    rows: list[dict[str, str]] = []
    for label in material.must:
        level = LEVEL_CRITICAL if label.casefold() in critical else LEVEL_MUST
        rows.extend({"name": name, "level": level} for name in _tech_names(label))
    for label in material.nice:
        rows.extend({"name": name, "level": LEVEL_NICE} for name in _tech_names(label))
    return clean_tech(rows)


def _by_level(tech: list[dict[str, str]]) -> list[dict[str, str]]:
    order = {LEVEL_CRITICAL: 0, LEVEL_MUST: 1, LEVEL_NICE: 2}
    return sorted(tech, key=lambda item: order[item["level"]])


def jjit_tech_stack(tech: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for item in _by_level(tech)[:JJIT_TECH_LIMIT]:
        level, label = _JJIT_LEVEL[item["level"]]
        rows.append(
            {
                "name": item["name"],
                "level": level,
                "label": label,
                "source": item["level"],
            }
        )
    return rows


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"


def _ol(items: list[str]) -> str:
    return "<ol>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ol>"


def _paragraphs(text: str) -> list[str]:
    return [_clean(p) for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()]


def _p(text: str) -> str:
    return "".join(f"<p>{html.escape(p)}</p>" for p in _paragraphs(text))


def _text_field(key: str, label: str, text: str) -> dict[str, Any]:
    paragraphs = _paragraphs(text)
    return {
        "key": key,
        "label": label,
        "kind": "text",
        "text": "\n\n".join(paragraphs),
        "html": _p(text),
        "items": [],
        "auto_count": 0,
        "fixed_count": 0,
    }


def _list_field(
    key: str,
    label: str,
    items: list[str],
    *,
    ordered: bool = False,
    auto_count: int = 0,
    fixed_count: int = 0,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "kind": "ordered" if ordered else "list",
        "text": "\n".join(items),
        "html": (_ol(items) if ordered else _ul(items)) if items else "",
        "items": items,
        # Pierwsze `auto_count` punktów pochodzi z pól rekrutacji, ostatnie
        # `fixed_count` — ze stałego bloku z Ustawień; środek edytuje rekruter.
        "auto_count": auto_count,
        "fixed_count": fixed_count,
    }


def _pracuj_params(terms: Terms) -> list[str]:
    """Wybory w formularzu Pracuj.pl (nie tekst do wklejenia)."""
    seniority = {
        "junior": "młodszy specjalista / młodsza specjalistka (junior)",
        "mid": "specjalista / specjalistka (mid / regular)",
        "senior": "starszy specjalista / starsza specjalistka (senior)",
        "lead": "ekspert / ekspertka",
        "architect": "ekspert / ekspertka",
    }.get(terms.seniority or "")
    workplace = {
        "remote": "praca zdalna",
        "hybrid": "praca hybrydowa",
        "onsite": "praca stacjonarna",
    }.get(terms.remote_policy or "")
    working_time = {"fulltime": "pełny etat", "parttime": "część etatu"}.get(
        terms.working_time or ""
    )
    chips = [
        seniority,
        f"kontrakt {terms.contract}",
        working_time,
        workplace,
        terms.city,
    ]
    return [chip for chip in chips if chip]


def pracuj_view(
    content: dict[str, Any],
    tech: list[dict[str, str]],
    terms: Terms,
    blocks: LangBlocks,
    *,
    lang: str,
    title: str,
) -> dict[str, Any]:
    auto = term_lines(terms, lang)
    own = _items(content.get("offer"))
    fixed = list(blocks.offer)
    required = [t["name"] for t in tech if t["level"] != LEVEL_NICE]
    optional = [t["name"] for t in tech if t["level"] == LEVEL_NICE]
    about = str(content.get("about") or "")
    fields = [
        _text_field("title", "Tytuł stanowiska", title),
        # Formularz Pracuj.pl nie ma pola na zdanie wstępu — bez opisu projektu
        # jego miejsce zajmuje wstęp, żeby pole nie zostało puste.
        _text_field(
            "about",
            "O projekcie",
            about if _clean(about) else str(content.get("lead") or ""),
        ),
        _list_field(
            "responsibilities",
            "Twój zakres obowiązków",
            _items(content.get("responsibilities")),
        ),
        _list_field(
            "requirements", "Nasze wymagania", _items(content.get("requirements"))
        ),
        _list_field(
            "nice_to_have", "Mile widziane", _items(content.get("nice_to_have"))
        ),
        _list_field(
            "offer",
            "To oferujemy",
            [*auto, *own, *fixed],
            auto_count=len(auto),
            fixed_count=len(fixed),
        ),
        _list_field("tech_required", "Technologie wymagane", required),
        _list_field("tech_optional", "Technologie mile widziane", optional),
        _list_field(
            "process",
            "Etapy rekrutacji",
            list(blocks.process),
            ordered=True,
            fixed_count=len(blocks.process),
        ),
    ]
    return {"fields": fields, "params": _pracuj_params(terms)}


def _jjit_form_fields(terms: Terms, title: str) -> list[dict[str, str]]:
    options = jjit_payload.default_options(
        {
            "remote_policy": terms.remote_policy,
            "seniority": terms.seniority,
            "onsite_days_per_week": terms.onsite_days_per_week,
            "city": terms.city,
        },
        work_mode=terms.working_time,
    )
    rows = [
        ("title", "Tytuł", title),
        (
            "experience",
            "Doświadczenie",
            _EXPERIENCE_LABELS.get(options.get("experience_level") or ""),
        ),
        (
            "employment",
            "Zatrudnienie",
            " · ".join(
                part
                for part in (
                    terms.contract,
                    _WORKING_TIME_LABELS.get(options.get("working_time") or ""),
                )
                if part
            ),
        ),
        (
            "workplace",
            "Tryb pracy",
            _WORKPLACE_LABELS.get(options.get("workplace_type") or ""),
        ),
        (
            "office_days",
            "Dni w biurze",
            str(options["office_days"]) if options.get("office_days") else None,
        ),
        ("city", "Miasto", options.get("city")),
    ]
    return [
        {"key": key, "label": label, "value": value}
        for key, label, value in rows
        if value
    ]


def _section(
    key: str,
    heading: Optional[str],
    *,
    text: str = "",
    items: Optional[list[str]] = None,
    ordered: bool = False,
    fixed_count: int = 0,
) -> Optional[dict[str, Any]]:
    items = items or []
    if not _clean(text) and not items:
        return None
    return {
        "key": key,
        "heading": heading,
        "kind": "ordered" if ordered else ("list" if items else "text"),
        "text": "\n\n".join(_paragraphs(text)),
        "items": items,
        "fixed_count": fixed_count,
    }


def _body_html(sections: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for section in sections:
        if section["heading"]:
            parts.append(f"<h3>{html.escape(section['heading'])}</h3>")
        if section["kind"] == "text":
            parts.append(_p(section["text"]))
        elif section["kind"] == "ordered":
            parts.append(_ol(section["items"]))
        else:
            parts.append(_ul(section["items"]))
    return "".join(parts)


def _body_text(sections: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for section in sections:
        lines: list[str] = [section["heading"]] if section["heading"] else []
        if section["kind"] == "text":
            lines.append(section["text"])
        elif section["kind"] == "ordered":
            lines.extend(f"{i}. {item}" for i, item in enumerate(section["items"], 1))
        else:
            lines.extend(f"• {item}" for item in section["items"])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def jjit_view(
    content: dict[str, Any],
    tech: list[dict[str, str]],
    terms: Terms,
    blocks: LangBlocks,
    *,
    lang: str,
    title: str,
) -> dict[str, Any]:
    headings = _HEADINGS[_lang(lang)]
    own_offer = _items(content.get("offer"))
    fixed_offer = list(blocks.offer)
    candidates = [
        _section("lead", None, text=str(content.get("lead") or "")),
        _section("about", headings["about"], text=str(content.get("about") or "")),
        _section("terms", headings["terms"], items=term_lines(terms, lang)),
        _section(
            "responsibilities",
            headings["responsibilities"],
            items=_items(content.get("responsibilities")),
        ),
        _section(
            "requirements",
            headings["requirements"],
            items=_items(content.get("requirements")),
        ),
        _section(
            "nice_to_have",
            headings["nice_to_have"],
            items=_items(content.get("nice_to_have")),
        ),
        _section(
            "offer",
            headings["offer"],
            items=[*own_offer, *fixed_offer],
            fixed_count=len(fixed_offer),
        ),
        _section(
            "process",
            headings["process"],
            items=list(blocks.process),
            ordered=True,
            fixed_count=len(blocks.process),
        ),
        _section("company", None, text=blocks.about),
    ]
    sections = [section for section in candidates if section is not None]
    return {
        "form_fields": _jjit_form_fields(terms, title),
        "tech_stack": jjit_tech_stack(tech),
        "tech_overflow": max(0, len(tech) - JJIT_TECH_LIMIT),
        "sections": sections,
        "body_html": _body_html(sections),
        "body_text": _body_text(sections),
    }


def render_ad(
    content: dict[str, Any],
    tech: Any,
    material: AdMaterial,
    blocks: LangBlocks,
    *,
    lang: str,
    title_suffix: str,
) -> dict[str, Any]:
    """Teksty do skopiowania dla obu portali — z zapisanego stanu ogłoszenia."""
    stack = clean_tech(tech)
    terms = terms_from(material, content)
    title = titled(str(content.get("title") or material.title), lang, title_suffix)
    return {
        "title": title,
        "pracuj": pracuj_view(content, stack, terms, blocks, lang=lang, title=title),
        "jjit": jjit_view(content, stack, terms, blocks, lang=lang, title=title),
    }


def rendered_texts(rendered: dict[str, Any]) -> list[str]:
    """Każdy napis, który może trafić do schowka — wejście kontroli ``lint``.

    Kontrola pól ``content`` nie wystarcza: miasto idzie z rekrutacji, a
    „co oferujemy”, etapy i zdanie o firmie ze stałych bloków.
    """
    texts: list[str] = [rendered["title"], *rendered["pracuj"]["params"]]
    for field in rendered["pracuj"]["fields"]:
        texts.extend(field["items"] or [field["text"]])
    jjit = rendered["jjit"]
    texts.extend(row["value"] for row in jjit["form_fields"])
    texts.extend(row["name"] for row in jjit["tech_stack"])
    for section in jjit["sections"]:
        texts.extend(section["items"] or [section["text"]])
    return [text for text in texts if text]
