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

Wynik jest OPINIĄ, nie bramką: lint nie blokuje zapisu. Kontrola końcowych faktów w generatorze pozostaje osobną bramką; lint ma
tę granicę pokazać wcześniej, żeby DL nie pisał reguł, które nie działają.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.services.cv_generator_b2b.provider import CVGeneratorAIError, analyze_with_ai
from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_for

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


LINT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {
                        "type": "string",
                        "enum": ["ok", "adds_facts", "unclear"],
                    },
                    "reason": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["index", "verdict", "reason", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _coerce(items: object, lines: list[str]) -> list[LintFinding]:
    """A malformed/ambiguous review cannot lend any line an 'ok' verdict."""
    out: list[LintFinding] = []
    seen: set[int] = set()
    valid = isinstance(items, list) and len(items) == len(lines)
    if valid:
        for item in items:
            if (
                not isinstance(item, dict)
                or set(item) != {"index", "verdict", "reason", "suggestion"}
                or type(item["index"]) is not int
                or item["index"] not in range(len(lines))
                or item["index"] in seen
                or item["verdict"] not in ("ok", "adds_facts", "unclear")
                or not isinstance(item["reason"], str)
                or not item["reason"].strip()
                or len(item["reason"]) > 500
                or not isinstance(item["suggestion"], str)
                or len(item["suggestion"]) > 500
            ):
                valid = False
                break
            index = item["index"]
            seen.add(index)
            out.append(
                LintFinding(
                    index,
                    lines[index],
                    item["verdict"],
                    item["reason"].strip(),
                    item["suggestion"].strip(),
                )
            )
    if not valid:
        return [
            LintFinding(
                index,
                line,
                "unclear",
                "Odpowiedź oceny jest niekompletna lub nieprawidłowa — ponów ocenę instrukcji.",
                "",
            )
            for index, line in enumerate(lines)
        ]
    return sorted(out, key=lambda finding: finding.index)


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
            model_override=model_for(AIFeatureKey.cv_rule_lint),
            response_schema=LINT_RESPONSE_SCHEMA,
        )
    except CVGeneratorAIError as err:
        logger.warning("[cv_rule_lint][%s] model call failed: %s", request_id, err)
        raise
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[cv_rule_lint][%s] unparseable model output", request_id)
        parsed = {}
    items = (
        parsed["items"]
        if isinstance(parsed, dict) and set(parsed) == {"items"}
        else None
    )
    return _coerce(items, lines)
