"""Treść „Nowego CV” z HTML-a edytora (22.11.2026).

Oba układy CV — klasyczny Word i nowe CV w PDF — powstają z jednej treści:
HTML-a, który rekruter poprawia w edytorze (`branded_draft_html`). Ten moduł
czyta go tak samo jak `cv_approved_docx` (znaczniki `data-cv-section`,
a w starszym HTML kształt akapitów) i oddaje słownik w kształcie danych
generatora (`why_points`, `experience`, `skills`, …), który przyjmuje
`cv_new_layout.NewCvDocument.from_cv_json`.

Czego HTML nie niesie (branża stanowiska, słowa do pogrubienia z Championa),
bierze się z zapisu generatora (`fallback`), gdy pasuje do treści z edytora —
edycja zawsze wygrywa z zapisem generatora.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from lxml import html

from app.services.cv_approved_docx import (
    _DATES_ONLY,
    _DUTIES_LABELS,
    _SECTION_TITLES,
    _TECH_LABELS,
    _WRAPPERS,
    _education_row,
    _has_block_child,
    _HasImage,
    _norm_title,
    _plain,
    _segments,
    _split_leading_bold,
    _tag,
    _trim,
)
from app.services.cv_rodo_clause import is_rodo_node

_KNOWN_SECTIONS = {
    "why_points",
    "education",
    "skills",
    "certifications",
    "languages",
    "experience",
}
_ROLE_MARKERS = {"role", "employer", "duties_label", "technologies"}
_TITLE_SEPARATOR = re.compile(r"\s+[–—-]\s+")


@dataclass(frozen=True)
class EditorCvContent:
    """Treść CV z edytora w kształcie danych generatora.

    ``unmapped_sections`` to tytuły sekcji dopisanych ręcznie, których nowy
    układ nie zna — interfejs mówi o nich, zamiast gubić je po cichu.
    """

    cv_json: dict[str, Any]
    rodo_clause: str
    unmapped_sections: tuple[str, ...]


def _markdown(segments: list) -> str:
    """Tekst z pogrubieniami jako ``**…**`` (sąsiednie pogrubione kawałki razem)."""
    parts: list[str] = []
    bold_open = False
    for text, state in _trim(segments):
        text = " " if text == "\n" else text
        bold = bool(state.get("bold")) and bool(text.strip())
        if bold and not bold_open:
            lead = len(text) - len(text.lstrip())
            parts.append(text[:lead] + "**")
            text = text[lead:]
            bold_open = True
        elif not bold and bold_open and text.strip():
            last = parts.pop() if parts else ""
            stripped = last.rstrip()
            parts.append(stripped + "**" + last[len(stripped) :])
            bold_open = False
        parts.append(text)
    out = "".join(parts)
    if bold_open:
        stripped = out.rstrip()
        out = stripped + "**" + out[len(stripped) :]
    return " ".join(out.split())


def _text(segments: list) -> str:
    return " ".join(_plain(segments).replace("\n", " ").split())


def _bold_texts(segments: list) -> list[str]:
    out: list[str] = []
    current = ""
    for text, state in segments:
        if state.get("bold"):
            current += text
        elif current:
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return [" ".join(t.split()).strip(" ,;:") for t in out if t.strip(" ,;:")]


def _flatten(node: Any) -> list[Any]:
    """Bloki poziomu dokumentu — lustro `cv_approved_docx.flatten`."""
    out: list[Any] = []

    def loose(text: Optional[str]) -> None:
        if text and text.strip():
            p = html.Element("p")
            p.text = text
            out.append(p)

    loose(node.text)
    for child in node:
        if (
            _tag(child) in _WRAPPERS
            and _has_block_child(child)
            and not child.get("data-cv-section")
            and not (child.text and child.text.strip())
            and not is_rodo_node(child)
        ):
            out.extend(_flatten(child))
        else:
            out.append(child)
        loose(child.tail)
    return out


def _section_key(node: Any) -> Optional[str]:
    marker = node.get("data-cv-section")
    if marker in _KNOWN_SECTIONS:
        return marker
    return _SECTION_TITLES.get(_norm_title("".join(node.itertext())))


def _list_items(node: Any) -> list[list]:
    items: list[list] = []
    for li in node.iter("li"):
        try:
            segments = _trim(_segments(li))
        except _HasImage:
            continue
        # Lista zagnieżdżona w punkcie należy do niego, nie jest osobnym punktem.
        if li.getparent() is not None and any(
            _tag(a) == "li" for a in li.iterancestors()
        ):
            continue
        if _plain(segments).strip():
            items.append(segments)
    return items


def _split_title(text: str, fallback: dict[str, Any]) -> tuple[str, str]:
    """„Stanowisko – Imię Nazwisko” z h1; przy Blind CV sam tytuł stanowiska."""
    name = str(fallback.get("name") or "").strip()
    parts = _TITLE_SEPARATOR.split(text)
    if len(parts) >= 2:
        if name and parts[-1].strip().casefold() == name.casefold():
            return " – ".join(parts[:-1]).strip(), name
        if not name:
            return " – ".join(parts[:-1]).strip(), parts[-1].strip()
    return text.strip(), name


def _role_kind(node: Any, marked: bool) -> Optional[str]:
    marker = node.get("data-cv-section")
    if marker in _ROLE_MARKERS:
        return marker
    if marked:
        return None
    text = "".join(node.itertext())
    if _norm_title(text) in _DUTIES_LABELS:
        return "duties_label"
    if text.strip().startswith(_TECH_LABELS):
        return "technologies"
    try:
        lead, rest = _split_leading_bold(_segments(node))
    except _HasImage:
        return None
    if lead and _DATES_ONLY.fullmatch(_plain(rest).strip()):
        return "role"
    return None


def _technologies(segments: list) -> list[str]:
    plain = _text(segments)
    label = next((lab for lab in _TECH_LABELS if plain.startswith(lab)), "")
    rest = plain[len(label) :].strip()
    return [t.strip() for t in re.split(r",\s*", rest) if t.strip()]


def _split_label(segments: list) -> tuple[str, list]:
    """„Etykieta:” z początku akapitu umiejętności i reszta jako kawałki z formatowaniem."""
    plain = _plain(segments)
    colon = plain.find(":")
    if colon < 0 or colon > 60:
        return "", segments
    rest: list = []
    seen = 0
    for text, state in segments:
        end = seen + len(text)
        if end <= colon + 1:
            seen = end
            continue
        cut = max(0, colon + 1 - seen)
        rest.append((text[cut:], state))
        seen = end
    return " ".join(plain[: colon + 1].split()), _trim(rest)


def _skill(segments: list) -> dict[str, str]:
    label, rest = _split_label(segments)
    return {"label": label, "content": _text(rest)}


# Wiersz edukacji poprawiony ręcznie, bez pogrubionej uczelni: „2019 - 2022 — Ekonomia”.
_LEADING_DATES = re.compile(
    r"^\s*((?:\d{1,2}[./])?(?:19|20)\d{2}(?:\s*[-–]\s*(?:(?:\d{1,2}[./])?(?:19|20)\d{2}"
    r"|obecnie|present|currently))?)\s+[—–-]\s+(\S.*)$",
    re.I,
)


def _education(segments: list) -> dict[str, str]:
    dates, bold, rest = _education_row(segments)
    rest_text = _text(rest)
    lead = "" if dates or bold else _LEADING_DATES.match(rest_text)
    if lead:  # bez dat i uczelni na początku — daty nie idą do kierunku (#40571)
        rest_text = lead.group(2)
    degree, _, location = rest_text.partition(" · ")
    return {
        "dates": lead.group(1) if lead else _text(dates),
        "institution": _text(bold),
        "degree": degree.strip(),
        "location": location.strip(),
    }


def _match_fallback_role(
    role: dict[str, Any], roles: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    def key(value: Any) -> str:
        return " ".join(str(value or "").split()).casefold()

    for candidate in roles:
        if key(candidate.get("company")) == key(role["company"]) and key(
            candidate.get("position")
        ) == key(role["position"]):
            return candidate
    for candidate in roles:
        if key(candidate.get("company")) == key(role["company"]) and key(
            candidate.get("dates")
        ) == key(role["dates"]):
            return candidate
    return None


def cv_json_from_editor_html(
    content_html: str,
    *,
    language: str = "pl",
    blind: bool = False,
    fallback: Optional[dict[str, Any]] = None,
) -> EditorCvContent:
    """Treść CV z HTML-a edytora (już po sanitizerze) w kształcie danych generatora."""
    fallback = fallback or {}
    root = html.fragment_fromstring(content_html or "", create_parent="div")
    blocks = _flatten(root)
    marked = any(
        node.get("data-cv-section") == "role"
        for node in root.iter()
        if isinstance(node.tag, str)
    )

    position = str(
        fallback.get("presentation_position") or fallback.get("position") or ""
    )
    name = "" if blind else str(fallback.get("name") or "")
    why: list[str] = []
    skills: list[dict[str, str]] = []
    education: list[dict[str, str]] = []
    certifications: list[str] = []
    languages: list[str] = []
    experience: list[dict[str, Any]] = []
    bolded: list[str] = []
    unmapped: list[str] = []
    rodo = ""
    section: Optional[str] = None
    in_duties = False

    for node in blocks:
        if not isinstance(node.tag, str):
            continue  # komentarz albo instrukcja w szkicu zapisanym jako cały dokument (#68)
        tag = _tag(node)
        if is_rodo_node(node):
            if not rodo:
                rodo = " ".join("".join(node.itertext()).split())
            continue
        if tag == "h1":
            position, parsed_name = _split_title(
                " ".join("".join(node.itertext()).split()), fallback
            )
            name = "" if blind else parsed_name
            continue
        if tag == "hr":
            continue
        if tag == "h2":
            section = _section_key(node)
            in_duties = False
            if section is None:
                title = " ".join("".join(node.itertext()).split())
                if title:
                    unmapped.append(title)
            continue
        if node.get("data-cv-section") in _ROLE_MARKERS and section != "experience":
            # znacznik stanowiska bez nagłówka „Doświadczenie” (usunięty w edytorze, #22485):
            # stanowiska nie lądują w poprzedniej sekcji (np. w językach)
            section = "experience"
            in_duties = False
        if section is None:
            continue
        try:
            segments = _trim(_segments(node)) if tag not in {"ul", "ol"} else []
        except _HasImage:
            continue

        if section == "why_points":
            if tag in {"ul", "ol"}:
                why.extend(_markdown(s) for s in _list_items(node))
            elif _plain(segments).strip():
                why.append(_markdown(segments))
        elif section == "skills":
            if tag in {"ul", "ol"}:
                for s in _list_items(node):
                    skills.append(_skill(s))
                    bolded.extend(_bold_texts(_split_label(s)[1]))
            elif _plain(segments).strip():
                skills.append(_skill(segments))
                bolded.extend(_bold_texts(_split_label(segments)[1]))
        elif section == "education":
            rows = _list_items(node) if tag in {"ul", "ol"} else [segments]
            education.extend(_education(s) for s in rows if _plain(s).strip())
        elif section == "certifications":
            rows = _list_items(node) if tag in {"ul", "ol"} else [segments]
            certifications.extend(_text(s) for s in rows if _plain(s).strip())
        elif section == "languages":
            rows = _list_items(node) if tag in {"ul", "ol"} else [segments]
            for s in rows:
                for item in _text(s).split(" · "):
                    if item.strip():
                        languages.append(item.strip())
        elif section == "experience":
            if tag in {"ul", "ol"}:
                if experience:
                    target = experience[-1]["responsibilities"]
                    target.extend(_text(s) for s in _list_items(node))
                continue
            kind = _role_kind(node, marked) if tag in {"p", "div"} else None
            if kind == "role":
                lead, rest = _split_leading_bold(segments)
                experience.append(
                    {
                        "position": _text(lead) or _text(segments),
                        "dates": _text(rest) if lead else "",
                        "company": "",
                        "industry": "",
                        "technologies": [],
                        "responsibilities": [],
                    }
                )
                in_duties = False
            elif kind == "employer" and experience and not experience[-1]["company"]:
                experience[-1]["company"] = _text(segments)
            elif kind == "duties_label":
                in_duties = True
            elif kind == "technologies" and experience:
                experience[-1]["technologies"] = _technologies(segments)
            elif (
                experience
                and not experience[-1]["company"]
                and not marked
                and not in_duties
                and not experience[-1]["responsibilities"]
            ):
                # Starsze CV bez znaczników: firma to akapit tuż po roli.
                experience[-1]["company"] = _text(segments)
            elif experience and _plain(segments).strip():
                experience[-1]["responsibilities"].append(_text(segments))

    fallback_roles = [
        r for r in (fallback.get("experience") or []) if isinstance(r, dict)
    ]
    for role in experience:
        match = _match_fallback_role(role, fallback_roles)
        if match and match.get("industry"):
            role["industry"] = str(match["industry"])

    keywords: list[str] = []
    for item in list(fallback.get("highlight_keywords") or []) + bolded:
        item = str(item).strip()
        if item and item.casefold() not in {k.casefold() for k in keywords}:
            keywords.append(item)

    cv_json = {
        "name": name,
        "position": position,
        "presentation_position": position,
        "language": "en" if language == "en" else "pl",
        "blind_cv": bool(blind),
        "why_points": why,
        "experience": experience,
        "skills": skills,
        "education": education,
        "certifications": certifications,
        "languages": languages,
        "highlight_keywords": keywords,
    }
    return EditorCvContent(
        cv_json=cv_json, rodo_clause=rodo, unmapped_sections=tuple(unmapped)
    )


def role_gaps(
    html: Optional[str], *, language: Optional[str], blind: bool
) -> Optional[dict[str, int]]:
    """Ile stanowisk Nowe CV czyta bez dat, a ile bez firmy (``None`` = wszystko jest).

    CV wgrane z pliku w obcym formacie (np. daty i „Nazwa firmy:” nad stanowiskiem)
    traci te pola — karta i edytor ostrzegają (decyzja Artura 25.11.2026)."""
    if not html or not html.strip():
        return None
    roles = (
        cv_json_from_editor_html(
            html,
            language="en" if language == "en" else "pl",
            blind=blind,
            fallback=None,
        ).cv_json.get("experience")
        or []
    )
    gaps = {
        "without_dates": sum(1 for r in roles if not str(r.get("dates") or "").strip()),
        "without_company": 0
        if blind
        else sum(1 for r in roles if not str(r.get("company") or "").strip()),
    }
    return gaps if any(gaps.values()) else None
