"""AI-sprawdzenie opisu/zakresu pod kątem znamion umowy o pracę (art. 22 §1 KP).

Użytkownik wkleja w „Opis projektu i zakres usług" dowolny tekst — ten moduł
prosi Claude o wykrycie sformułowań sugerujących stosunek pracy (podporządkowanie,
polecenia przełożonego, sztywne godziny, urlop, „wynagrodzenie za pracę" itp.)
oraz o bezpieczniejszą redakcję B2B (język rezultatu/usługi).

Najpierw uruchamia deterministyczne reguły, następnie przekazuje ich wynik do
Sonnet przez centralny gateway. Wynik jest zawsze doradczy i ma ``input_hash``.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.ai import AIError, AIRequest, ai_gateway
from app.models.ai_feature import AIFeatureKey

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


class _Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phrase: str
    why: str
    suggestion: str


class _AIUopResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issues: list[_Issue] = Field(default_factory=list)
    rewritten: str
    summary: str


_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(?:polece(?:ń|nia)|przełożon(?:ego|ej)|podległo(?:ść|ści))\b", re.I
        ),
        "Sformułowanie może wskazywać na podporządkowanie służbowe.",
        "Opisz uzgodniony rezultat i samodzielność wykonawcy.",
    ),
    (
        re.compile(
            r"\b(?:godzin(?:y|ach)|czas pracy|od\s+\d{1,2}[:.]\d{2}\s+do)\b", re.I
        ),
        "Sztywne godziny mogą przypominać organizację czasu pracy pracownika.",
        "Wskaż termin lub dostępność rezultatu bez narzucania godzin pracy.",
    ),
    (
        re.compile(
            r"\b(?:urlop|zwolnieni(?:e|a)|świadczeni(?:e|a) pracownicze)\b", re.I
        ),
        "To pojęcie jest charakterystyczne dla stosunku pracy.",
        "Użyj zasad przerwy w świadczeniu usług uzgodnionych między stronami.",
    ),
    (
        re.compile(
            r"\b(?:wynagrodzenie za pracę|etat|stanowisko w strukturze)\b", re.I
        ),
        "Terminologia bezpośrednio nawiązuje do zatrudnienia pracowniczego.",
        "Użyj wynagrodzenia za wykonane usługi lub uzgodniony rezultat.",
    ),
)


def _rule_issues(text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern, why, suggestion in _RULES:
        for match in pattern.finditer(text):
            phrase = match.group(0)
            key = phrase.casefold()
            if key in seen:
                continue
            seen.add(key)
            issues.append({"phrase": phrase, "why": why, "suggestion": suggestion})
    return issues


async def check_employment_hallmarks(
    text: str, language: str = "pl", *, user_id: Optional[int] = None
) -> dict:
    """Sprawdź tekst opisu/zakresu; zwróć ``{ok, issues, rewritten, summary}``.

    Raises:
        Funkcja nie podejmuje decyzji prawnej; odpowiedź wymaga potwierdzenia.
    """
    clean = (text or "").strip()
    if not clean:
        return {
            "ok": True,
            "issues": [],
            "rewritten": "",
            "summary": "",
            "input_hash": hashlib.sha256(b"").hexdigest(),
            "analysis_mode": "rules_only",
            "requires_confirmation": True,
        }
    clean = clean[:_MAX_INPUT_CHARS]
    input_hash = hashlib.sha256(
        f"{language.lower()}:{clean}".encode("utf-8")
    ).hexdigest()
    deterministic = _rule_issues(clean)
    template = _PROMPT_EN if (language or "pl").lower().startswith("en") else _PROMPT_PL
    prompt = template.format(text=clean)
    prompt += (
        "\n\nDeterministyczny silnik wykrył poniższe frazy. Nie wolno ich usuwać "
        "z issues; możesz dodać tylko frazę będącą dokładnym cytatem z tekstu:\n"
        + json.dumps(deterministic, ensure_ascii=False)
    )

    def validate(value: object) -> _AIUopResult:
        result = _AIUopResult.model_validate(value)
        source_lower = clean.casefold()
        if any(issue.phrase.casefold() not in source_lower for issue in result.issues):
            raise ValueError("AI issue phrase is not present in source")
        returned = {issue.phrase.casefold() for issue in result.issues}
        if any(issue["phrase"].casefold() not in returned for issue in deterministic):
            raise ValueError("AI omitted a deterministic rule issue")
        return result

    analysis_mode = "rules_ai"
    try:
        gateway_result = await ai_gateway.call(
            AIRequest(
                feature=AIFeatureKey.uop_analysis,
                user_id=user_id,
                subject_type="b2b_contract_draft",
                messages=[
                    {
                        "role": "system",
                        "content": "To analiza doradcza. Nie wydawaj decyzji prawnej i zwróć wyłącznie JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                prompt_version="uop_rules_sonnet_v2",
                schema_version="uop_result_v2",
                structured_validator=validate,
                pii=True,
            )
        )
        model_result: _AIUopResult = gateway_result.content
        issues = [item.model_dump() for item in model_result.issues]
        rewritten = model_result.rewritten
        summary = model_result.summary
    except AIError as exc:
        logger.warning("uop analysis degraded code=%s", exc.code)
        analysis_mode = "rules_only"
        issues = deterministic
        rewritten = clean
        summary = (
            "Wykryto ryzykowne sformułowania regułami deterministycznymi; "
            "redakcja AI jest chwilowo niedostępna."
            if issues
            else "Reguły deterministyczne nie wykryły znamion stosunku pracy."
        )
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "rewritten": rewritten,
        "summary": summary,
        "input_hash": input_hash,
        "analysis_mode": analysis_mode,
        "requires_confirmation": True,
    }


__all__ = ["check_employment_hallmarks"]
