"""Wspólna reguła „model uzasadnia z cytatem, kod sprawdza cytat” (28.10.2026).

Wydzielone z przeglądu zgłoszeń z linku (``application_screening``, 0404),
bo tej samej reguły używa „Oceń z AI” na zaznaczonych osobach
(``ai_candidate_assessment``):

* fakty liczy KOD — must-have rekrutacji w profilu, CV i notatkach
  (``must_facts``, ta sama lista co bramka wyszukiwania);
* model dostaje rolę (``job_prompt_block``) i tekst osoby, oddaje JSON
  (``model_json``) z powodami ``{text, quote}``;
* powód zostaje tylko z cytatem, który stoi w tekście, który model dostał
  (``keep_quoted_reasons``) — reszta to zgadywanie. „Stoi” = dosłownie
  albo, dla cytatu od 6 słów, ≥ 80% jego trójek słów jest w tekście
  (``quote_matcher``, 09.11.2026): PDF wtrąca daty i nagłówki w środek
  zdania, a model cytuje zdanie sklejone.

Każdy wołający sam decyduje o werdykcie: przegląd zgłoszeń może osobę
odłożyć, „Oceń z AI” tylko układa kolejność.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable, Iterable, Optional

from app.services.prompt_fencing import fence

REASON_LIMIT = 4
REASON_TEXT_MAX = 300
QUOTE_MAX = 300
DEAL_BREAKER_MAX = 300
JOB_TEXT_LIMIT = 4_000
# Cytat krótszy niż 3 znaki („C”, „Go”) stoi w każdym CV — nie jest dowodem.
QUOTE_MIN = 3
# Cytat niedosłowny (09.11.2026): ``raw_cv_text`` z PDF bywa przeplatany
# datami i nagłówkami w środku zdania („optimize/\n01-2021 – Present\nimprove
# JIRA…”), a model cytuje zdanie sklejone. Pomiar na stagingu 09.11.2026
# (ok. 500 ocen CV): 176 z 1 490 cytatów (12%) było prawdziwych, ale
# niedosłownych; próg niżej przepuszczał je i dalej odrzucał 79 zmyślonych.
# Krótszy cytat musi stać dosłownie — kilka słów składa się z byle czego.
FUZZY_MIN_WORDS = 6
FUZZY_MIN_SHARE = 0.8
_ELLIPSIS = re.compile(r"\[?(?:\.\.\.|…)\]?")
_WORD = re.compile(r"[a-z0-9]+")


def normalize(text: Optional[str]) -> str:
    """Porównanie cytatu z CV: bez różnic w białych znakach i wielkości liter."""
    return " ".join((text or "").replace("**", "").split()).casefold()


def _words(text: Optional[str]) -> list[str]:
    """Same słowa: bez znaków diakrytycznych i interpunkcji (NFKD, [a-z0-9])."""
    folded = unicodedata.normalize("NFKD", normalize(text).replace("ł", "l"))
    return _WORD.findall(folded.encode("ascii", "ignore").decode())


def _trigrams(words: list[str]) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + 3]) for i in range(len(words) - 2)]


def quote_matcher(
    haystacks: Iterable[Optional[str]],
) -> Callable[[Optional[str]], bool]:
    """Sprawdzarka „czy cytat stoi w tych tekstach” — jedna reguła dla wszystkich.

    Cytat stoi, gdy jest dosłownie (``normalize``, co najmniej ``QUOTE_MIN``
    znaków) albo ma ≥ ``FUZZY_MIN_WORDS`` słów i ≥ ``FUZZY_MIN_SHARE`` jego
    trójek słów jest w tekście — przestawione albo zmyślone słowa nie dają
    trójek. Wielokropek („…”, „...”, „[...]”) dzieli cytat na fragmenty i
    każdy musi stać sam, tymi samymi regułami: łączenie nie daje więcej niż
    dwa osobne cytaty, a rekruter widzi, że coś pominięto.
    """
    texts = [h for h in haystacks if h]
    hay = "\n".join(normalize(h) for h in texts)
    grams: Optional[set[tuple[str, ...]]] = None

    def fragment_found(fragment: str) -> bool:
        nonlocal grams
        needle = normalize(fragment)
        if len(needle) >= QUOTE_MIN and needle in hay:
            return True
        words = _words(fragment)
        if len(words) < FUZZY_MIN_WORDS:
            return False
        if grams is None:
            grams = {g for h in texts for g in _trigrams(_words(h))}
        wanted = _trigrams(words)
        return sum(g in grams for g in wanted) >= FUZZY_MIN_SHARE * len(wanted)

    def found(quote: Optional[str]) -> bool:
        text = str(quote or "")
        needle = normalize(text)
        if len(needle) >= QUOTE_MIN and needle in hay:
            return True
        fragments = [f for f in _ELLIPSIS.split(text) if _words(f)]
        return bool(fragments) and all(fragment_found(f) for f in fragments)

    return found


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
    found = quote_matcher(haystacks)
    kept: list[dict[str, str]] = []
    for item in raw_reasons:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if not text or not quote:
            continue
        if not found(quote):
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
