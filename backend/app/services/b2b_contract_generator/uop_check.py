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

from app.services.cv_generator_b2b.ai_client import (
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
WYŁĄCZNIE słowa „Klient" (ewentualnie „Klient Projektu"). NIE używaj słowa \
„Zamawiający" — dla zachowania spójności z nomenklaturą Załącznika nr 3 do umowy \
B2B. Dotyczy to zarówno pola „rewritten", jak i „suggestion".

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
„Klient" (or „Klient Projektu") — never „Zamawiający" — to stay consistent with \
the nomenclature of Appendix 3 (Załącznik nr 3) to the B2B contract. This applies \
to both the "rewritten" and "suggestion" fields.

Return ONLY valid JSON (no markdown, no comments):
{{"issues":[{{"phrase":"<quote>","why":"<why risky>","suggestion":"<rephrase>"}}],\
"rewritten":"<full text after safe redaction>","summary":"<1-sentence summary>"}}
If the text is fine, return "issues":[] and "rewritten" equal to the original.

Text to assess:
\"\"\"
{text}
\"\"\""""


def _extract_json(raw: str) -> dict:
    """Wyjmij obiekt JSON z odpowiedzi (czasem owinięty w ```json ... ```)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in AI response")
    return json.loads(candidate[start : end + 1])


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
    raw = analyze_with_ai(template.format(text=clean), request_id="uop-check")
    data = _extract_json(raw)
    issues = data.get("issues") or []
    return {
        "ok": len(issues) == 0,
        "issues": [
            {
                "phrase": str(i.get("phrase", "")),
                "why": str(i.get("why", "")),
                "suggestion": str(i.get("suggestion", "")),
            }
            for i in issues
            if isinstance(i, dict)
        ],
        "rewritten": str(data.get("rewritten") or clean),
        "summary": str(data.get("summary") or ""),
    }


__all__ = ["check_employment_hallmarks", "CVGeneratorAIError"]
