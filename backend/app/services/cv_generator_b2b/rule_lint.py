"""Lint instrukcji klienta dla generatora CV — przy zapisie reguły, nie po fakcie.

Do 02.09.2026 Delivery Lead dowiadywał się, że jego instrukcja każe dopisać
fakt (i zostanie zignorowana), dopiero z ostrzeżeń na gotowym CV — trzy dni
później, u rekrutera. Tu tani model ocenia każdą linię w chwili zapisu i mówi,
która jest regułą PREZENTACJI, a która próbuje zmienić TREŚĆ, z propozycją
przepisania.

Świadomie osobny klucz kwoty (``cv_rule_lint``): inny strumień wydatku niż
generacja, inna osoba płaci (DL przy setupie, nie rekruter przy każdym CV).
Model z ``CLAUDE_MODEL_CV_BULK`` (Haiku) — zadanie klasyfikacyjne, nie
generacyjne, i nie ma sensu płacić stawki Sonneta.

Wynik jest OPINIĄ, nie bramką: lint nie blokuje zapisu. Twardą granicę trzyma
prompt generatora (instrukcja dopisująca fakty jest tam ignorowana); lint ma
tę granicę pokazać wcześniej, żeby DL nie pisał reguł, które nie działają.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.core.config import settings
from app.services.cv_generator_b2b.provider import CVGeneratorAIError, analyze_with_ai

logger = logging.getLogger(__name__)

Verdict = Literal["ok", "adds_facts", "unclear"]

LINT_SYSTEM_PROMPT = """Jesteś recenzentem instrukcji dla generatora CV w agencji rekrutacyjnej.
Generator wolno stosować WYŁĄCZNIE do PREZENTACJI faktów, które kandydat ma w swoim CV
lub notatkach ze screeningu: kolejność, dobór i liczba eksponowanych elementów, długość,
styl, słownictwo, format dat, pomijanie sekcji. Generator NIGDY nie może dopisać, zmienić
ani rozdmuchać faktu (technologii, obowiązku, lat doświadczenia, certyfikatu, projektu,
osiągnięcia, nazwy klienta docelowego w opisie kandydata).

Dostaniesz listę linii instrukcji (JSON). Dla KAŻDEJ linii zwróć obiekt:
- "index": numer linii z wejścia,
- "verdict": "ok" (czysta reguła prezentacji), "adds_facts" (każe dopisać/zmienić/rozdmuchać
  fakt albo dopasować kandydata do oferty) lub "unclear" (nie da się wykonać jednoznacznie),
- "reason": jedno zdanie po polsku, dlaczego,
- "suggestion": przepisana wersja, która zachowuje intencję w granicach prezentacji
  (pusty string, gdy verdict == "ok").

Przykłady: "bez sekcji zainteresowań" → ok. "maks. 3 projekty na stanowisko" → ok.
"podkreśl doświadczenie bankowe" → ok, jeśli chodzi o kolejność (suggestion: "jeśli kandydat
ma projekty bankowe, umieść je wyżej"). "dopisz znajomość Kubernetes" → adds_facts.
"napisz, że kandydat pracował w bankowości" → adds_facts. "ładniej" → unclear.

Odpowiedz TYLKO JSON-em: {"items": [...]}. Bez markdown, bez tekstu poza JSON."""


@dataclass(frozen=True)
class LintFinding:
    index: int
    line: str
    verdict: Verdict
    reason: str
    suggestion: str


def split_instruction_lines(text: str) -> list[str]:
    """Jedna instrukcja = jedna linia albo jedno zdanie; puste odpadają."""
    lines: list[str] = []
    for raw in (text or "").splitlines():
        for part in re.split(r"(?<=[.;])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9])", raw.strip()):
            part = part.strip()
            if part:
                lines.append(part)
    return lines


def _coerce(items: object, lines: list[str]) -> list[LintFinding]:
    out: list[LintFinding] = []
    seen: set[int] = set()
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= len(lines) or index in seen:
                continue
            verdict = str(item.get("verdict") or "unclear")
            if verdict not in ("ok", "adds_facts", "unclear"):
                verdict = "unclear"
            seen.add(index)
            out.append(
                LintFinding(
                    index=index,
                    line=lines[index],
                    verdict=verdict,  # type: ignore[arg-type]
                    reason=str(item.get("reason") or "").strip()[:500],
                    suggestion=str(item.get("suggestion") or "").strip()[:500],
                )
            )
    # Linie, o których model zapomniał, nie mogą wyglądać jak „ok" — to jest
    # dokładnie ten rodzaj ciszy, przed którym lint ma chronić.
    for index, line in enumerate(lines):
        if index not in seen:
            out.append(
                LintFinding(
                    index=index,
                    line=line,
                    verdict="unclear",
                    reason="Model nie ocenił tej linii — sprawdź ją ręcznie.",
                    suggestion="",
                )
            )
    out.sort(key=lambda f: f.index)
    return out


def lint_instructions(text: str, *, request_id: str) -> list[LintFinding]:
    """Oceń instrukcje linia po linii. Pusta lista dla pustego tekstu."""
    lines = split_instruction_lines(text)
    if not lines:
        return []
    payload = json.dumps(
        {"lines": [{"index": i, "text": line} for i, line in enumerate(lines)]},
        ensure_ascii=False,
    )
    try:
        raw = analyze_with_ai(
            payload,
            request_id,
            system=LINT_SYSTEM_PROMPT,
            model_override=settings.CLAUDE_MODEL_CV_BULK,
        )
    except CVGeneratorAIError as err:
        logger.warning("[cv_rule_lint][%s] model call failed: %s", request_id, err)
        raise
    cleaned = re.sub(r"```json\n?|```\n?", "", raw).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("[cv_rule_lint][%s] unparseable model output", request_id)
        parsed = {}
    items = parsed.get("items") if isinstance(parsed, dict) else None
    return _coerce(items, lines)
