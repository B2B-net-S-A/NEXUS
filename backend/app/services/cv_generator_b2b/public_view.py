"""Publiczny (client-safe) widok ``render_payload`` wygenerowanego CV.

Jedno źródło prawdy dla WSZYSTKIEGO, co wychodzi do hiring managera na
publicznym linku ``/cv/i/{token}``:

* odpowiedź ``GET /api/public/cv-i/{token}`` (widok classic + interaktywny),
* wejście do generacji mapy wymagań (``requirement_map.py``) — dzięki temu
  cytaty-dowody mogą pochodzić WYŁĄCZNIE z tekstu, który klient i tak widzi,
* kontekst chatu AI (``cv_interactive_chat_service.py``) — model fizycznie
  nie dostaje niczego spoza tego payloadu, więc nie może tego wygadać.

Zasady:
* ``warnings`` (bezpiecznik fabrykacji) NIGDY nie wychodzą — to informacja
  wewnętrzna dla rekrutera;
* przy ``blind_cv`` maskowanie jest lustrem logiki renderera DOCX
  (``docx_renderer.render_cv_to_bytes``): nazwisko → „Kandydat"/„Candidate",
  ``experience[].company`` → „Firma z branży X" — payload w DB trzyma
  PRAWDZIWE wartości (żeby lista wewnętrzna była identyfikowalna), więc
  maskowanie musi zajść tutaj, przed każdym publicznym użyciem;
* payload B2B z definicji nie ma sekcji kontaktowej (email/telefon/LinkedIn)
  — nie trzeba jej wycinać, ale test bezpieczeństwa i tak to asertuje.
"""

from __future__ import annotations

import copy
from typing import Any


def _mask_blind(payload: dict[str, Any]) -> None:
    """In-place lustro maskowania blind z ``render_cv_to_bytes``."""
    language = payload.get("language", "pl")
    if language == "en":
        payload["name"] = "Candidate"
        payload["first_name"] = "Candidate"
    else:
        payload["name"] = "Kandydat"
        payload["first_name"] = "Kandydat"
    for job in payload.get("experience", []) or []:
        if not isinstance(job, dict):
            continue
        industry = job.get("industry", "IT")
        if language == "en":
            job["company"] = f"Company from {industry} industry"
        else:
            job["company"] = f"Firma z branży {industry}"


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(v) for v in value if isinstance(v, (str, int, float)) and str(v).strip()
    ]


def build_public_payload(render_payload: dict[str, Any] | None) -> dict[str, Any]:
    """Zbuduj client-safe słownik z ``render_payload``.

    Zwraca WYŁĄCZNIE pola renderowane w DOCX-ie wysyłanym klientowi — nic
    diagnostycznego (``warnings``, ``content_mode``, ``mode``) i nic
    tożsamościowego przy blind.
    """
    payload = copy.deepcopy(render_payload or {})
    language = str(payload.get("language") or "pl")
    blind = bool(payload.get("blind_cv"))
    if blind:
        _mask_blind(payload)

    experience: list[dict[str, Any]] = []
    for job in payload.get("experience", []) or []:
        if not isinstance(job, dict):
            continue
        experience.append(
            {
                "dates": str(job.get("dates") or ""),
                "company": str(job.get("company") or ""),
                "industry": str(job.get("industry") or ""),
                "position": str(job.get("position") or ""),
                "responsibilities": _str_list(job.get("responsibilities")),
                "technologies": _str_list(job.get("technologies")),
            }
        )

    education: list[dict[str, Any]] = []
    for entry in payload.get("education", []) or []:
        if not isinstance(entry, dict):
            continue
        education.append(
            {
                "dates": str(entry.get("dates") or ""),
                "institution": str(entry.get("institution") or ""),
                "degree": str(entry.get("degree") or ""),
                "location": str(entry.get("location") or ""),
            }
        )

    skills: list[dict[str, Any]] = []
    for group in payload.get("skills", []) or []:
        if not isinstance(group, dict):
            continue
        skills.append(
            {
                "label": str(group.get("label") or ""),
                "content": str(group.get("content") or ""),
            }
        )

    return {
        "language": language if language in ("pl", "en") else "pl",
        "blind": blind,
        "candidate_name": str(payload.get("name") or ""),
        "position": str(payload.get("position") or ""),
        "considered_for": str(payload.get("considered_for") or "") or None,
        "why_points": _str_list(payload.get("why_points")),
        "education": education,
        "skills": skills,
        "certifications": _str_list(payload.get("certifications")),
        "languages": _str_list(payload.get("languages")),
        "experience": experience,
        "highlight_keywords": _str_list(payload.get("highlight_keywords")),
    }


def public_payload_text(public_payload: dict[str, Any]) -> str:
    """Cały client-safe tekst CV jako jeden string — do walidacji cytatów
    (dowód musi być substringiem) i jako kontekst chatu."""
    parts: list[str] = [
        public_payload.get("candidate_name") or "",
        public_payload.get("position") or "",
        public_payload.get("considered_for") or "",
        *public_payload.get("why_points", []),
        *public_payload.get("certifications", []),
        *public_payload.get("languages", []),
    ]
    for entry in public_payload.get("education", []):
        parts.extend(
            [
                entry.get("dates", ""),
                entry.get("institution", ""),
                entry.get("degree", ""),
                entry.get("location", ""),
            ]
        )
    for group in public_payload.get("skills", []):
        parts.extend([group.get("label", ""), group.get("content", "")])
    for job in public_payload.get("experience", []):
        parts.extend(
            [
                job.get("dates", ""),
                job.get("company", ""),
                job.get("industry", ""),
                job.get("position", ""),
            ]
        )
        parts.extend(job.get("responsibilities", []))
        parts.extend(job.get("technologies", []))
    return "\n".join(p for p in parts if p)
