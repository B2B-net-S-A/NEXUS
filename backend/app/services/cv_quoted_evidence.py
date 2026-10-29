"""Wspólna reguła „model uzasadnia z cytatem, kod sprawdza cytat” (28.10.2026).

Wydzielone z przeglądu zgłoszeń z linku (``application_screening``, 0404),
bo tej samej reguły używa „Oceń z AI” na zaznaczonych osobach
(``ai_candidate_assessment``):

* fakty liczy KOD — must-have rekrutacji w profilu, CV i notatkach
  (``must_facts``, ta sama lista co bramka wyszukiwania);
* model dostaje rolę (``job_prompt_block``) i tekst osoby, oddaje JSON
  (``model_json``) z powodami ``{text, quote}``;
* powód zostaje tylko z cytatem, który stoi dosłownie w tekście, który
  model dostał (``keep_quoted_reasons``) — reszta to zgadywanie.

Każdy wołający sam decyduje o werdykcie: przegląd zgłoszeń może osobę
odłożyć, „Oceń z AI” tylko układa kolejność.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from app.services.prompt_fencing import fence

REASON_LIMIT = 4
REASON_TEXT_MAX = 300
QUOTE_MAX = 300
DEAL_BREAKER_MAX = 300
JOB_TEXT_LIMIT = 4_000
# Cytat krótszy niż 3 znaki („C”, „Go”) stoi w każdym CV — nie jest dowodem.
QUOTE_MIN = 3


def normalize(text: Optional[str]) -> str:
    """Porównanie cytatu z CV: bez różnic w białych znakach i wielkości liter."""
    return " ".join((text or "").replace("**", "").split()).casefold()


def keep_quoted_reasons(
    raw_reasons: Any,
    haystacks: Iterable[Optional[str]],
    *,
    limit: int = REASON_LIMIT,
) -> list[dict[str, str]]:
    """Powody z cytatem obecnym w CV albo profilu; reszta wypada.

    Zwraca najwyżej ``limit`` powodów ``{"text", "quote"}``. Powód bez
    cytatu też wypada — zdanie o kandydacie bez dowodu z jego CV jest
    zgadywaniem, a na nim nie wolno nikogo odrzucić.
    """
    if not isinstance(raw_reasons, list):
        return []
    hay = "\n".join(normalize(h) for h in haystacks if h)
    kept: list[dict[str, str]] = []
    for item in raw_reasons:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if not text or not quote:
            continue
        needle = normalize(quote)
        if len(needle) < QUOTE_MIN or needle not in hay:
            continue
        kept.append({"text": text[:REASON_TEXT_MAX], "quote": quote[:QUOTE_MAX]})
        if len(kept) >= limit:
            break
    return kept


def model_json(raw: Optional[str]) -> dict:
    """Obiekt JSON z odpowiedzi modelu (także w bloku ```json). Rzuca przy braku."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("brak JSON-a w odpowiedzi")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("odpowiedź nie jest obiektem")
    return data


def deal_breaker_conditions(job: Any) -> list[str]:
    """Warunki „Odpada, gdy…” z pytań screeningowych Championa (bez pustych)."""
    from app.services import champion_view

    out: list[str] = []
    for question in champion_view.screening_questions(
        getattr(job, "champion_profile", None)
    ):
        if not isinstance(question, dict):
            continue
        condition = " ".join(str(question.get("deal_breaker") or "").split())
        if condition and condition not in out:
            out.append(condition[:DEAL_BREAKER_MAX])
    return out


def critical_labels(job: Any) -> list[str]:
    """Umiejętności krytyczne rekrutacji (wybór DL albo podpowiedź) — bez awarii."""
    from app.services.critical_skills import effective_critical

    try:
        return list(effective_critical(job).labels)
    except Exception:  # noqa: BLE001 — opis roli dla modelu, nie bramka
        return []


def job_prompt_block(job: Any, *, with_critical: bool = False) -> str:
    """Rola dla modelu: tytuł, must, nice i „O projekcie” — bez stawek i klienta.

    ``with_critical`` dokłada umiejętności krytyczne Delivery Leada — „Oceń
    z AI” porównuje osobę z nimi; przegląd zgłoszeń ma prompt bez tej linii.
    """
    from app.services import champion_view
    from app.services.requirement_contract import (
        requirement_labels,
        requirements_for_job,
    )

    labels = requirement_labels(requirements_for_job(job))
    project = champion_view.project(getattr(job, "champion_profile", None))
    about = "\n".join(
        str(p).strip()
        for p in (project.get("about"), project.get("responsibilities"))
        if p and str(p).strip()
    )
    title = getattr(job, "working_title", None) or getattr(job, "title", "") or ""
    lines = [f"Rola: {title}"]
    if with_critical:
        critical = critical_labels(job)
        if critical:
            lines.append("Krytyczne (bez tego odpada): " + ", ".join(critical))
    if labels.get("must"):
        lines.append("Wymagane (must-have): " + ", ".join(labels["must"]))
    if labels.get("nice"):
        lines.append("Mile widziane: " + ", ".join(labels["nice"]))
    if about:
        lines.append("O projekcie:\n" + about)
    conditions = deal_breaker_conditions(job)
    if conditions:
        # 04.10.2026: model może wskazać warunek, który CV łamie — z cytatem.
        lines.append("Odpada, gdy:\n" + "\n".join(f"- {c}" for c in conditions))
    return fence("rekrutacja", "\n".join(lines)[:JOB_TEXT_LIMIT])


def must_facts(
    job: Any, candidate: Any, cv_text: str, note_texts: Iterable[str] = ()
) -> tuple[int, int]:
    """(znalezione, wszystkie) must-have technologie w profilu, CV i notatkach."""
    from app.services.must_text_evidence import text_met_labels
    from app.services.requirement_contract import search_dealbreaker_inputs

    inputs = search_dealbreaker_inputs(job)
    must = list(inputs.must_skills)
    if not must:
        return 0, 0
    texts = [t for t in (cv_text, *note_texts) if t]
    met = text_met_labels(
        candidate,
        must,
        note_texts=texts,
        options=inputs.gate_options,
    )
    return len(met), len(must)
