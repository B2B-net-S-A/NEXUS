"""AI-sprawdzenie opisu/zakresu pod kątem znamion umowy o pracę (art. 22 §1 KP).

Użytkownik wkleja w „Opis projektu i zakres usług" dowolny tekst — ten moduł
prosi Claude o wykrycie sformułowań sugerujących stosunek pracy (podporządkowanie,
polecenia przełożonego, sztywne godziny, urlop, „wynagrodzenie za pracę" itp.)
oraz o bezpieczniejszą redakcję B2B (język rezultatu/usługi).

Reużywa klienta Anthropic z generatora CV (`analyze_with_ai`, model Sonnet),
wołany w wątku (klient SDK jest synchroniczny). Zwraca strukturę:
``{ok, issues: [{phrase, why, suggestion}], rewritten, summary}``.

Redakcja AI jest opisem projektu i zakresu usług — NIE dopisuje warunków
współpracy (ticket 5, 09.2026). Do tego dnia prompt kazał proponować „język
samodzielności, odpowiedzialności za rezultat, własnej organizacji czasu”, więc
43 z 99 umów z generatora dostało w §1 zdania typu „Partner samodzielnie
realizuje…”, których nie było w rekrutacji. Prompt tego już nie prosi, a
``_strip_added_cooperation_terms`` wycina z odpowiedzi zdania o sposobie,
relacji z Klientem, miejscu/czasie pracy i odpowiedzialności, jeśli tekst
wejściowy o nich nie mówił — model bywa nieposłuszny, a to trafia do umowy.
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
- „wynagrodzenie za pracę", podległość służbowa, etat, stanowisko w strukturze.

REDAKCJA („rewritten") to opis projektu i zakresu usług — nic więcej. Zasady:
- Korzystaj WYŁĄCZNIE z informacji zawartych w tekście do oceny. Nie dopisuj \
faktów, technologii, rezultatów ani obowiązków, których w nim nie ma.
- Ryzykowne sformułowanie USUŃ albo zamień na neutralny opis samej czynności \
(np. „wykonuje polecenia kierownika zespołu przy testach" → „testy aplikacji"). \
Nie zastępuj go zdaniem o warunkach współpracy.
- NIE dodawaj żadnych informacji, których nie ma w tekście, dotyczących:
  • sposobu realizacji usług (np. samodzielnie, niezależnie, zespołowo, \
pod nadzorem, własnymi narzędziami, z możliwością podwykonawstwa),
  • relacji z Klientem (np. bezpośrednio dla Klienta, uzgadnianie z Klientem, \
raportowanie do osób po stronie Klienta, współpraca z przedstawicielami Klienta),
  • miejsca, trybu i czasu pracy (np. zdalnie, w siedzibie, godziny, harmonogram),
  • odpowiedzialności, podległości i innych warunków współpracy (np. \
odpowiedzialność za rezultat).
Te warunki reguluje treść umowy, nie opis projektu.
- Zasada „nie dodawaj" dotyczy też pola „suggestion".

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
benefits, "remuneration for work", a position in the org structure.

The REDACTION ("rewritten") is a description of the project and the scope of \
services — nothing else. Rules:
- Use ONLY information contained in the text to assess. Do not add facts, \
technologies, results or duties that are not in it.
- REMOVE a risky phrase or replace it with a neutral description of the activity \
itself (e.g. "follows the team lead's orders when testing" → "application \
testing"). Do not replace it with a sentence about the terms of cooperation.
- Do NOT add any information that is not in the text about:
  • how the services are performed (e.g. independently, autonomously, as a team, \
under supervision, with own tools, with the option to subcontract),
  • the relationship with the Client (e.g. directly for the Client, agreeing \
with the Client, reporting to people on the Client's side, working with the \
Client's representatives),
  • place, mode and time of work (e.g. remotely, on-site, hours, schedule),
  • responsibility, subordination or other terms of cooperation (e.g. \
responsibility for results).
These terms are governed by the contract itself, not by the project description.
- The "do not add" rule applies to the "suggestion" field too.

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


# Warunki współpracy, których redakcja AI nie może DOPISAĆ (ticket 5). Zdanie
# redakcji z takim określeniem odpada, gdy tekstu wejściowego nie było w nim
# ani razu — określenie przepisane z rekrutacji zostaje. Świadomie bez
# „rezultat”: „których rezultatem są analizy” to przeformułowanie zakresu,
# a wycięcie całego zdania zabrałoby opis usług.
_COOPERATION_TERMS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # sposób realizacji usług
        r"samodziel",
        r"niezależn",
        r"zesp[oó][lł]",
        r"nadz[oó]r",
        r"pod kierun",
        r"podwykonaw",
        r"we własnym zakresie",
        r"własn\w* (warsztat|narzędzi|sprzęt|organizac|zasob|środk)",
        r"według własnego|wg własnego",
        r"independen",
        r"autonom",
        r"\bown (tools?|equipment|discretion|time|organi[sz]ation|resources)",
        r"subcontract",
        r"supervis",
        r"under the direction",
        r"\bteams?\b",
        # relacja z Klientem
        r"bezpośredni",
        r"raport",
        r"przedstawiciel",
        r"z klientem",
        r"po stronie klienta",
        r"wskazan\w* przez klienta",
        r"osob\w* wskazan",
        r"współprac",
        r"uzgad|uzgodn",
        r"\bdirectly\b",
        r"\breport",
        r"with the client",
        r"client'?s (side|representatives?)",
        r"representative",
        r"\bagree",
        r"cooperat|collaborat",
        # miejsce, tryb i czas pracy
        r"zdaln",
        r"stacjonarn",
        r"hybryd",
        r"siedzib",
        r"w biurze|biura klienta|z biura",
        r"lokalizac",
        r"miejsc\w* (wykonywania|świadczenia|realizacji|pracy)",
        r"godzin",
        r"czas\w* (pracy|świadczenia|realizacji|wykonywania)",
        r"organizac\w* czasu",
        r"harmonogram",
        r"dyspozycyjn",
        r"dni robocz",
        r"\bremote",
        r"on-?site",
        r"hybrid",
        r"\boffice",
        r"premises",
        r"\blocation",
        r"\bhours?\b",
        r"working time",
        r"schedule",
        # odpowiedzialność, podległość i inne warunki współpracy
        r"odpowiedzialn",
        r"odpowiada za",
        r"podleg",
        r"podporządk",
        r"przełożon",
        r"polece",
        r"responsib",
        r"accountab",
        r"subordinat",
        r"superior",
    )
)

# Skróty z kropką, po których zdanie się NIE kończy — bez tego „m.in. testy”
# rozpadało się na dwa kawałki i wycięcie drugiego zostawiało wiszące „m.in.”.
_ABBREVIATIONS = (
    "m.in.",
    "np.",
    "tj.",
    "tzn.",
    "itp.",
    "itd.",
    "ok.",
    "e.g.",
    "i.e.",
    "etc.",
)


def _split_sentences(text: str) -> list[str]:
    """Pokrój tekst na zdania / pozycje listy, zachowując separatory.

    Każdy element zawiera zdanie RAZEM z następującym po nim odstępem, więc
    ``"".join(...)`` odtwarza tekst co do znaku. Granica to ``.!?;`` przed
    odstępem albo nowa linia — „5.x” i „.NET” zostają w jednym kawałku.
    """
    parts = re.split(r"((?<=[.!?;])[ \t]+|\n+)", text)
    pieces: list[str] = []
    for i in range(0, len(parts), 2):
        chunk = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
        if pieces and pieces[-1].rstrip().lower().endswith(_ABBREVIATIONS):
            pieces[-1] += chunk
        else:
            pieces.append(chunk)
    return [p for p in pieces if p]


def _strip_added_cooperation_terms(text: str, source: str) -> tuple[str, int]:
    """Wytnij zdania, które DOPISUJĄ warunki współpracy nieobecne w ``source``.

    Zwraca ``(tekst, liczba_wyciętych_zdań)``. Zdanie odpada, gdy zawiera
    określenie z ``_COOPERATION_TERMS``, którego w tekście wejściowym nie było.
    """
    added = [p for p in _COOPERATION_TERMS if p.search(text) and not p.search(source)]
    if not added:
        return text, 0
    kept: list[str] = []
    removed = 0
    for piece in _split_sentences(text):
        if any(p.search(piece) for p in added):
            removed += 1
        else:
            kept.append(piece)
    result = "".join(kept).strip()
    # Wycięta ostatnia pozycja listy zostawia „…; ” albo „…,” — domknij kropką.
    if result and result[-1] in ";,:":
        result = result[:-1].rstrip() + "."
    return result, removed


def _normalize_result(data: dict, clean: str) -> dict:
    """Waliduj i znormalizuj luźny JSON modelu do stabilnego kontraktu API."""
    raw_issues = data.get("issues")
    if not isinstance(raw_issues, list):
        raise ValueError("AI issues field is not a list")
    if any(not isinstance(item, dict) for item in raw_issues):
        raise ValueError("AI issues field contains a non-object item")

    issues = []
    removed_total = 0
    for item in raw_issues:
        suggestion, removed = _strip_added_cooperation_terms(
            str(item.get("suggestion", "")), clean
        )
        removed_total += removed
        issues.append(
            {
                "phrase": str(item.get("phrase", "")),
                "why": str(item.get("why", "")),
                "suggestion": suggestion,
            }
        )
    rewritten, removed = _strip_added_cooperation_terms(
        str(data.get("rewritten") or clean), clean
    )
    removed_total += removed
    if removed_total:
        # Liczba, bez treści — opis bywa pełen nazw klienta i projektu.
        logger.info("[uop-check] dropped %d added cooperation sentences", removed_total)
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        # Redakcja wycięta do zera nie może wyczyścić pola — zostaje oryginał.
        "rewritten": rewritten or clean,
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
