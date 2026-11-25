"""Kontrakt wejścia układu „Nowe CV”: niezmienny dokument z JSON-a generatora.

Renderer nie sięga do bazy ani magazynu: wołający podaje gotowe 3 zdania
„Dlaczego”, klauzulę RODO i bajty zrzutu zgody (wymóg PKO BP).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.services.cv_new_layout.text import clean

WHY_ON_PAGE_1 = 3


@dataclass(frozen=True)
class Role:
    dates: str
    company: str
    industry: str
    position: str
    technologies: tuple[str, ...]
    responsibilities: tuple[str, ...]


@dataclass(frozen=True)
class School:
    dates: str
    degree: str
    institution: str
    location: str


@dataclass(frozen=True)
class SkillGroup:
    label: str
    content: str


@dataclass(frozen=True)
class HighlightChoice:
    """Wyróżnik ze strony 1 (`page1_extras.highlight`, Artur 25.11.2026):
    „auto” = praca u klienta rekrutacji, „custom” = wpis rekrutera, „off” = bez."""

    mode: str = "auto"
    label: str = ""
    token: str = ""
    text: str = ""


@dataclass(frozen=True)
class NewCvDocument:
    name: str
    position: str
    languages: tuple[str, ...]
    why: tuple[str, ...]
    experience: tuple[Role, ...]
    skills: tuple[SkillGroup, ...]
    education: tuple[School, ...]
    certifications: tuple[str, ...]
    highlight_keywords: tuple[str, ...]
    language: str = "pl"
    blind: bool = False
    # Miasto kandydata z profilu: pastylka obok języków; puste = bez pastylki (23.11.2026).
    location: str = ""
    # Wymagania MUST z Profilu Championa: certyfikat z tej listy idzie do wieńca.
    must_have: tuple[str, ...] = ()
    # Wieniec: „auto” (certyfikat z MUST, inaczej dyplom), „cert” albo „school”.
    wreath: str = "auto"
    # Wyróżnik i nazwy klienta rekrutacji (nazwa, wyświetlana, pełna) do automatu „praca u klienta”.
    highlight: HighlightChoice = HighlightChoice()
    client_names: tuple[str, ...] = ()
    rodo_clause_html: Optional[str] = None
    consent_image: Optional[bytes] = None
    consent_image_mime: Optional[str] = None

    @classmethod
    def from_cv_json(
        cls,
        data: dict,
        *,
        why: Optional[list[str]] = None,
        wreath: str = "auto",
        highlight: Optional[HighlightChoice] = None,
        rodo_clause_html: Optional[str] = None,
        consent_image: Optional[bytes] = None,
        consent_image_mime: Optional[str] = None,
    ) -> "NewCvDocument":
        """Dokument z `render_payload` generatora.

        `why` to ostateczne (najwyżej 3) zdania strony 1 wybrane przez wołającego;
        bez niego pierwsze 3 z `why_points`. Przy `blind_cv` nazwisko i firmy są
        maskowane jak w pliku Word (`docx_renderer.render_cv_to_bytes`,
        `public_view._mask_blind`) — payload w bazie trzyma prawdziwe wartości.
        """
        data = data if isinstance(data, dict) else {}
        language = "en" if str(data.get("language") or "pl").lower() == "en" else "pl"
        blind = bool(data.get("blind_cv"))
        points = _strings(why) if why is not None else _strings(data.get("why_points"))
        roles = tuple(
            Role(
                dates=_str(job.get("dates")),
                company=_masked_company(job, language)
                if blind
                else _str(job.get("company")),
                industry=_str(job.get("industry")),
                position=_str(job.get("position")),
                technologies=_strings(job.get("technologies")),
                responsibilities=_strings(job.get("responsibilities")),
            )
            for job in _dicts(data.get("experience"))
        )
        skills = tuple(
            SkillGroup(
                label=_str(g.get("label")).rstrip(":").strip(),
                content=clean(_str(g.get("content"))),
            )
            for g in _dicts(data.get("skills"))
            if _str(g.get("content"))
        )
        schools = tuple(
            School(
                dates=_str(e.get("dates")),
                degree=_str(e.get("degree")),
                institution=_str(e.get("institution")),
                location=_str(e.get("location")),
            )
            for e in _dicts(data.get("education"))
            if _str(e.get("degree")) or _str(e.get("institution"))
        )
        name = _str(data.get("name"))
        if blind:
            name = "Candidate" if language == "en" else "Kandydat"
        return cls(
            name=name,
            position=_str(data.get("presentation_position"))
            or _str(data.get("position")),
            languages=_strings(data.get("languages")),
            why=points[:WHY_ON_PAGE_1],
            experience=roles,
            skills=skills,
            education=schools,
            certifications=tuple(
                clean(c) for c in _strings(data.get("certifications"))
            ),
            highlight_keywords=_strings(data.get("highlight_keywords")),
            language=language,
            blind=blind,
            location=_str(data.get("candidate_location")),
            must_have=_strings(data.get("must_have")),
            wreath=wreath if wreath in ("auto", "cert", "school") else "auto",
            highlight=highlight or HighlightChoice(),
            client_names=_strings(data.get("client_names")),
            rodo_clause_html=rodo_clause_html,
            consent_image=consent_image or None,
            consent_image_mime=consent_image_mime,
        )


def _masked_company(job: dict, language: str) -> str:
    """Lustro `public_view._mask_blind` (ta sama reguła co w pliku Word)."""
    industry = _str(job.get("industry"))
    if language == "en":
        return f"Company from {industry} industry" if industry else "Company"
    return f"Firma z branży {industry}" if industry else "Firma"


def _str(value: Any) -> str:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()
    return ""


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(s for s in (_str(v) for v in value) if s)


def _dicts(value: Any) -> list[dict]:
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, dict)]
