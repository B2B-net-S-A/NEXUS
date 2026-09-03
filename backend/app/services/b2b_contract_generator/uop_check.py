"""AI-sprawdzenie opisu/zakresu pod kątem znamion umowy o pracę (art. 22 §1 KP).

Użytkownik wkleja w „Opis projektu i zakres usług" dowolny tekst — ten moduł
prosi Claude o wykrycie sformułowań sugerujących stosunek pracy (podporządkowanie,
polecenia przełożonego, sztywne godziny, urlop, „wynagrodzenie za pracę" itp.)
oraz o bezpieczniejszą redakcję B2B (język rezultatu/usługi).

Reużywa klienta Anthropic z generatora CV (`analyze_with_ai`, model Sonnet),
wołany w wątku (klient SDK jest synchroniczny). Zwraca strukturę:
``{ok, issues: [{phrase, why, suggestion}], rewritten, summary}``.
"""

from __future__ import annotations

import json
import logging
import re

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_for
from app.services.cv_generator_b2b.provider import (
    CVGeneratorAIError,
    analyze_with_ai,
)

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 6000

_PROMPT_PL = """Jesteś polskim prawnikiem specjalizującym się w umowach B2B (kontrakt \
z jednoosobową działalnością gospodarczą). Oceń poniższy „opis projektu i zakres \
usług", który trafi do umowy B2B, pod kątem RYZYKA uznania współpracy za stosunek \
pracy (art. 22 §1 Kodeksu pracy).

Wskaż sformułowania, które noszą znamiona umowy o pracę, m.in.:
- podporządkowanie organizacyjne / wykonywanie poleceń przełożonego,
- sztywne godziny / czas pracy, obowiązek obecności w określonych godzinach,
- urlop, zwolnienia, świadczenia pracownicze,
- „wynagrodzenie za pracę", podległość służbowa, etat, stanowisko w strukturze,
- brak samodzielności co do sposobu i miejsca wykonania.

Zaproponuj bezpieczniejszą redakcję językiem rezultatu/usługi (samodzielność, \
odpowiedzialność za rezultat, własny warsztat i organizacja czasu, możliwość \
podwykonawstwa).

NAZEWNICTWO (obowiązkowe): na określenie strony zamawiającej usługę używaj \
WYŁĄCZNIE słowa „Klient" (ewentualnie „Klient Projektu"); NIE używaj słowa \
„Zamawiający". Na określenie strony świadczącej usługi używaj WYŁĄCZNIE słowa \
„Partner"; NIE używaj słów „Wykonawca", „Konsultant", „Zleceniobiorca", \
„Specjalista" ani imienia i nazwiska. Obie zasady zachowują spójność z \
nomenklaturą Załącznika nr 3 do umowy B2B i dotyczą zarówno pola „rewritten", \
jak i „suggestion".

Zwróć WYŁĄCZNIE poprawny JSON (bez komentarzy, bez markdown) w formacie:
{{"issues":[{{"phrase":"<cytat z tekstu>","why":"<dlaczego ryzykowne>",\
"suggestion":"<jak przeformułować>"}}],"rewritten":"<cały tekst po bezpiecznej \
redakcji>","summary":"<1 zdanie podsumowania>"}}
Jeśli tekst jest w porządku, zwróć "issues":[] oraz "rewritten" równe oryginałowi.

Tekst do oceny:
\"\"\"
{text}
\"\"\""""

_PROMPT_EN = """You are a Polish lawyer specialising in B2B contracts (with a \
sole proprietor). Assess the following "project description and scope of services" \
for the RISK of the cooperation being deemed an employment relationship \
(art. 22 §1 of the Polish Labour Code).

Flag wording bearing hallmarks of employment: organisational subordination, \
following a superior's orders, fixed working hours, leave/holidays, employee \
benefits, "remuneration for work", a position in the org structure, lack of \
autonomy as to manner and place of performance.

Propose safer wording in results/service language (autonomy, responsibility for \
results, own toolset and time organisation, possibility of subcontracting).

TERMINOLOGY (mandatory): refer to the party commissioning the services ONLY as \
„Klient" (or „Klient Projektu") — never „Zamawiający". Refer to the party \
providing the services ONLY as „Partner" — never „Wykonawca", „Konsultant", \
„Zleceniobiorca", „Specjalista", "Contractor", "Consultant" or a personal name. \
Both rules keep the wording consistent with the nomenclature of Appendix 3 \
(Załącznik nr 3) to the B2B contract and apply to both the "rewritten" and \
"suggestion" fields.

Return ONLY valid JSON (no markdown, no comments):
{{"issues":[{{"phrase":"<quote>","why":"<why risky>","suggestion":"<rephrase>"}}],\
"rewritten":"<full text after safe redaction>","summary":"<1-sentence summary>"}}
If the text is fine, return "issues":[] and "rewritten" equal to the original.

Text to assess:
\"\"\"
{text}
\"\"\""""


def _extract_json(raw: str) -> dict:
    """Wyjmij pierwszy kompletny wynik UoP z odpowiedzi Claude.

    Modele czasem dodają prose/code fence albo wstawiają dosłowny znak nowej
    linii w długim polu ``rewritten``. ``raw_decode`` ignoruje tekst po obiekcie,
    a drugi przebieg z ``strict=False`` toleruje ten bezpieczny, częsty defekt
    bez zgadywania lub przepisywania treści analizy.
    """
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    candidates = [*fenced, raw]
    last_error: ValueError | json.JSONDecodeError | None = None

    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            for strict in (True, False):
                try:
                    value, _end = json.JSONDecoder(strict=strict).raw_decode(
                        candidate, match.start()
                    )
                except json.JSONDecodeError as exc:
                    last_error = exc
                    continue
                if isinstance(value, dict) and "issues" in value:
                    return value
                last_error = ValueError("JSON object does not contain issues")

    raise ValueError("no valid UoP JSON object in AI response") from last_error


def _normalize_result(data: dict, clean: str) -> dict:
    """Waliduj i znormalizuj luźny JSON modelu do stabilnego kontraktu API."""
    raw_issues = data.get("issues")
    if not isinstance(raw_issues, list):
        raise ValueError("AI issues field is not a list")
    if any(not isinstance(item, dict) for item in raw_issues):
        raise ValueError("AI issues field contains a non-object item")

    issues = [
        {
            "phrase": str(item.get("phrase", "")),
            "why": str(item.get("why", "")),
            "suggestion": str(item.get("suggestion", "")),
        }
        for item in raw_issues
    ]
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "rewritten": str(data.get("rewritten") or clean),
        "summary": str(data.get("summary") or ""),
    }


def _uop_model() -> str:
    """Model UoP niezależny od quality-pinu generatora CV."""
    return model_for(AIFeatureKey.uop_check)


def check_employment_hallmarks(text: str, language: str = "pl") -> dict:
    """Sprawdź tekst opisu/zakresu; zwróć ``{ok, issues, rewritten, summary}``.

    Raises:
        CVGeneratorAIError: brak ANTHROPIC_API_KEY lub wyczerpane retry.
        ValueError: odpowiedź AI nie jest parsowalnym JSON-em.
    """
    clean = (text or "").strip()
    if not clean:
        return {"ok": True, "issues": [], "rewritten": "", "summary": ""}
    clean = clean[:_MAX_INPUT_CHARS]
    template = _PROMPT_EN if (language or "pl").lower().startswith("en") else _PROMPT_PL
    prompt = template.format(text=clean)
    retry_instruction = (
        "\n\nPREVIOUS RESPONSE WAS NOT VALID JSON. Return only one JSON object. "
        "Encode newlines inside string values as \\n."
        if template is _PROMPT_EN
        else "\n\nPOPRZEDNIA ODPOWIEDŹ NIE BYŁA POPRAWNYM JSON-em. "
        "Zwróć ponownie wyłącznie jeden obiekt JSON. Znaki nowej linii "
        "wewnątrz wartości tekstowych zapisz jako \\n."
    )
    parse_error: ValueError | None = None
    for attempt in range(2):
        raw = analyze_with_ai(
            prompt + (retry_instruction if attempt else ""),
            request_id="uop-check-retry" if attempt else "uop-check",
            model_override=_uop_model(),
        )
        try:
            return _normalize_result(_extract_json(raw), clean)
        except ValueError as exc:
            parse_error = exc
            logger.warning(
                "[uop-check] invalid structured response attempt=%d/2: %s",
                attempt + 1,
                exc,
            )

    raise ValueError("AI returned invalid UoP response twice") from parse_error


__all__ = ["check_employment_hallmarks", "CVGeneratorAIError"]
