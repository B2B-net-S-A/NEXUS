"""Stanowisko i opis roli w zaproszeniu na prep (26.10.2026, decyzje D1–D3).

Prośba zespołu: automat zapraszający na prep ma od razu dawać kandydatowi
opis roli. Makiety: https://claude.ai/artifact/KzvuFKEgZTbzzwtFFax9hK.

* **Stanowisko** = nazwa roli z Profilu Championa, a gdy jej nie ma albo
  wygląda jak kod — nazwa od klienta oczyszczona jak nagłówek CV
  (:func:`cv_role_title`). Do 26.10.2026 zaproszenie brało tylko nazwę od
  klienta i Nordea dostawała „PL_IT_Developer_expert_TP#40379”.
* **Opis** składa KOD z Championa, bez AI: o projekcie, obowiązki, wymagania,
  mile widziane, tryb pracy. Nigdy stawka, budżet, notatki zespołu ani
  dyskwalifikatory — :func:`description` nie czyta tych pól. Champion bez
  opisu projektu i obowiązków = brak opisu (okno to mówi).

Okno „Zaplanuj prep” pokazuje obie wartości i pozwala je poprawić dla tego
jednego zaproszenia; poprawki nie wracają do Championa.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.services import champion_view, office_days
from app.services.job_public_profile import _client_names, _stack_names, public_params
from app.services.job_working_title import cv_role_title
from app.services.public_profile_lint import Finding, lint_public_texts

TITLE_MAX = 200
DESCRIPTION_MAX = 4000
NICE_MAX = 8
SOURCE_CHAMPION = "champion"
SOURCE_CLIENT = "client"

# Kod zamiast nazwy roli: numery zapytań, kody stanowisk, „_” Nordei,
# „Replacement” (imię zastępowanej osoby). Rok w nazwie („SQL Server 2019”)
# to nie kod — numer ma co najmniej 5 cyfr.
_CODE_LIKE = re.compile(
    r"#|_|\d{5,}|(?<![A-Za-z])(?:ZOB|RITM|PKN|EITE|PEP|TP)(?![A-Za-z])|replacement",
    re.I,
)
_LETTER = re.compile(r"[^\W\d_]")
_DUTY_SPLIT = re.compile(r"\s*(?:\n|;)\s*")
_BULLET = re.compile(r"^[\s•\-–—*·]+")
_WORK_MODE = {"remote": "zdalnie", "hybrid": "hybrydowo", "onsite": "stacjonarnie"}
# Champion zapisuje tryb po polsku; ``public_params`` czyta tylko klucze.
_WORK_MODE_PL = set(_WORK_MODE.values())


def looks_like_code(title: Optional[str]) -> bool:
    """Czy stanowisko trzeba poprawić, zanim pójdzie do kandydata."""
    text = " ".join((title or "").split())
    return not _LETTER.search(text) or bool(_CODE_LIKE.search(text))


async def title(db: AsyncSession, job: Job) -> tuple[str, str]:
    """``(stanowisko, źródło)`` — źródło ``champion`` albo ``client``."""
    names = await _client_names(db, job.client_id)
    reference = getattr(job, "client_reference", None)
    role = champion_view.basics(job).get("role_name")
    if isinstance(role, str) and role.strip():
        # Rola w Championie bywa przepisaną nazwą od klienta („Nordea: …
        # (42758)”) — przechodzi przez to samo czyszczenie.
        champion = cv_role_title(role, reference, names)
        if not looks_like_code(champion):
            return champion[:TITLE_MAX], SOURCE_CHAMPION
    return cv_role_title(job.title, reference, names)[:TITLE_MAX], SOURCE_CLIENT


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _duties(value: Any) -> list[str]:
    out = []
    for part in _DUTY_SPLIT.split(str(value or "")):
        line = _text(_BULLET.sub("", part)).rstrip(".")
        if line:
            out.append(line)
    return out


def _experience(raw: dict, level: str) -> list[str]:
    return [
        _text(item.get("name"))
        for kind in ("domains", "certifications", "regulations")
        for item in champion_view.experience(raw).get(kind) or []
        if item.get("level", "must") == level
    ]


def _unique(names: list[str], skip: set[str] = frozenset()) -> list[str]:
    seen = set(skip)
    out = []
    for name in names:
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _work_mode(job: Job) -> str:
    params = public_params(job)
    parts = []
    mode = _WORK_MODE.get(params.get("remote_policy") or "")
    if mode is None:
        champion = _text(champion_view.basics(job).get("work_mode")).lower()
        mode = champion if champion in _WORK_MODE_PL else None
    if mode:
        days = office_days.label(
            params.get("onsite_days_per_week"), params.get("onsite_days_per_month")
        )
        parts.append(f"{mode}, {days} w biurze" if days and mode != "zdalnie" else mode)
    if params.get("city"):
        parts.append(params["city"])
    return " · ".join(parts)


def description(job: Job) -> str:
    """Opis roli zwykłym tekstem (akapity, punkty „• ”). Pusty = brak opisu."""
    raw = champion_view.as_dict(job)
    project = champion_view.project(raw)
    about = _text(project.get("about"))
    duties = _duties(project.get("responsibilities"))
    if not about and not duties:
        return ""
    must = _unique(_stack_names(job, "must"))
    domains = _unique(_experience(raw, "must"), {n.casefold() for n in must})
    nice = _unique(
        _stack_names(job, "nice") + _experience(raw, "nice"),
        {n.casefold() for n in must + domains},
    )
    paragraphs = []
    if about:
        paragraphs.append(about)
    if duties:
        paragraphs.append("Zakres obowiązków:\n" + "\n".join(f"• {d}" for d in duties))
    facts = []
    if must:
        facts.append("Wymagania kluczowe: " + ", ".join(must))
    if domains:
        facts.append("Doświadczenie: " + ", ".join(domains))
    if nice:
        facts.append("Mile widziane: " + ", ".join(nice[:NICE_MAX]))
    work = _work_mode(job)
    if work:
        facts.append(f"Tryb pracy: {work}")
    if facts:
        paragraphs.append("\n".join(facts))
    return "\n\n".join(paragraphs)[:DESCRIPTION_MAX]


def findings(text: Optional[str]) -> list[Finding]:
    """Kontrola jak na stronie kariery: kwoty, kontakty, linki.

    Bez nazwy klienta — zaproszenie i tak ją podaje.
    """
    return lint_public_texts([text])
