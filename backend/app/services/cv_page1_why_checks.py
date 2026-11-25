"""Sprawdzenie zdań 1–3 „Dlaczego nasz kandydat” ze strony 1 „Nowego CV” (25.11.2026).

Decyzje Artura (warsztaty 23.11 i runda 37 z 25.11): trzy zdania bez etykiet.

1. Doświadczenie: lata w IT → lata na roli → branże → metodyka, bez rodzaju
   („przez ten czas w zespołach pracujących w Agile i Scrum”).
2. Wymagania MUST z Profilu Championa potwierdzone w CV i gdzie — bez
   „Z wymagań klienta:”.
3. Najważniejsze zadanie (`project.key_task`) z dowodem z CV albo z odpowiedzi
   na oznaczone pytanie screeningu — bez „Najważniejsze zadanie w tej roli to…”.

Model pisze, kod sprawdza (`cv_page1_why`), bez sieci i bazy — tak jak
„najmocniejszy wynik” (`cv_page1_result_checks`):

- lata w zdaniu 1 wstawia KOD w miejsce znaczników ``{LATA_IT}`` /
  ``{LATA_ROLA}`` z dat stanowisk wskazanych przez model (suma bez nakładek,
  pełne lata w dół), więc model nie liczy ani nie zaokrągla;
- każdy cytat stoi w jednym punkcie albo nazwie stanowiska jednej roli (zdanie
  3: albo w odpowiedzi ze screeningu), po słowach;
- każda liczba ze zdania stoi w cytacie, roli z cytatem albo (zdanie 1) w datach
  wskazanych ról i punkcie 1 generatora;
- MUST nazwany w zdaniu 2 ma dowód w roli z cytatem; metodyka w zdaniu 1 stoi
  w CV;
- jedno zdanie, najwyżej ``WHY_MAX_CHARS`` znaków, bez etykiety na początku,
  bez form z rodzajem („pracował”, „she”), w Blind CV bez nazw firm.

Zdanie, które nie przeszło, zostaje z kodem ``issue`` (edytor może pokazać
dlaczego), ale na stronę 1 nie idzie — slot bierze wtedy dzisiejsze punkty
generatora (`cv_layout.compose_page1_why`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from app.services.cv_page1_result_checks import (
    QUOTE_MIN_WORDS,
    RoleSource,
    _company_core,
    _numbers,
    _period_like,
    _phrase,
    _words,
    clean_text,
    is_one_sentence,
    locate_role,
    strip_bold,
)

SLOTS = ("experience", "requirements", "key_task")
WHY_MAX_CHARS = 220
MAX_EVIDENCE = 6

TOKEN_IT = "{LATA_IT}"
TOKEN_ROLE = "{LATA_ROLA}"

ISSUE_EMPTY = "empty"
ISSUE_TOO_LONG = "too_long"
ISSUE_NOT_ONE_SENTENCE = "not_one_sentence"
ISSUE_LABEL = "label"
ISSUE_GENDERED = "gendered"
ISSUE_COMPANY_NAMED = "company_named"
ISSUE_NUMBER_NOT_IN_CV = "number_not_in_cv"
ISSUE_BAD_ROLES = "bad_roles"
ISSUE_METHOD_NOT_IN_CV = "method_not_in_cv"
ISSUE_QUOTE_MISSING = "quote_missing"
ISSUE_QUOTE_NOT_IN_CV = "quote_not_in_cv"
ISSUE_MUST_UNKNOWN = "must_unknown"
ISSUE_MUST_NOT_IN_QUOTE = "must_not_in_quote"
ISSUE_MUST_WITHOUT_PROOF = "must_without_proof"
ISSUE_NO_INPUT = "no_input"

# Etykiety z makiety rundy 36, które Artur odrzucił 25.11.2026.
_LABEL = re.compile(
    r"^\s*(?:z wymagań klienta|wymagania klienta|najważniejsze zadanie|"
    r"kluczowe zadanie|doświadczenie\s*:|from the client'?s requirements|"
    r"client requirements|(?:the )?key task|(?:the )?most important task|"
    r"experience\s*:)",
    re.IGNORECASE,
)
# Formy z rodzajem — płeć kandydata nie jest znana (jak forma obowiązków z 16.11).
_GENDERED = re.compile(
    r"\b(?:był|była|pracował|pracowała|prowadził|prowadziła|zrealizował|"
    r"zrealizowała|odpowiadał|odpowiadała|wdrożył|wdrożyła|zarządzał|zarządzała|"
    r"uczestniczył|uczestniczyła|zbudował|zbudowała|stworzył|stworzyła|kierował|"
    r"kierowała|przeprowadził|przeprowadziła|dostarczył|dostarczyła|"
    r"doświadczony|doświadczona|he|she|his|her|him)\b",
    re.IGNORECASE,
)
# Metodyki, które zdanie 1 wolno nazwać tylko wtedy, gdy stoją w CV.
METHODS = (
    "Agile",
    "Scrum",
    "Kanban",
    "SAFe",
    "LeSS",
    "Waterfall",
    "PRINCE2",
    "DevOps",
    "Lean",
    "XP",
    "V-model",
    "ITIL",
)


@dataclass(frozen=True)
class WhyInputs:
    """Co poza HTML-em edytora dostaje model zdań 1–3."""

    must: tuple[str, ...] = ()
    key_task: str = ""
    # Odpowiedź kandydata na pytanie screeningu oznaczone `key_task` — bez
    # pominiętych, bez stawek i dostępności, bez zdań przeczących.
    answer: str = ""


@dataclass(frozen=True)
class WhyContext:
    """Fakty z CV, na których kod sprawdza zdania."""

    roles: tuple[RoleSource, ...]
    # Przedziały ról (początek, koniec) jako ułamek roku; ``None`` = bez dat.
    spans: tuple[Optional[tuple[float, float]], ...]
    why_points: tuple[str, ...]
    cv_text: str
    language: str = "pl"
    blind: bool = False
    inputs: WhyInputs = field(default_factory=WhyInputs)


def _role(ctx: WhyContext, index: Any) -> Optional[RoleSource]:
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    return ctx.roles[index] if 0 <= index < len(ctx.roles) else None


def _indexes(value: Any) -> Optional[list[int]]:
    """Lista numerów ról; coś innego niż lista liczb całkowitych = ``None``."""
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return None
        if item not in out:
            out.append(item)
    return out


def union_months(ctx: WhyContext, indexes: Sequence[int]) -> Optional[int]:
    """Miesiące wskazanych ról bez nakładek; ``None`` = któraś bez dat."""
    from app.services.cv_new_layout.facts import union_years

    spans = []
    for index in indexes:
        span = ctx.spans[index] if 0 <= index < len(ctx.spans) else None
        if span is None:
            return None
        spans.append(span)
    if not spans:
        return None
    return int(round(union_years(spans) * 12))


def tenure_words(months: int, language: str) -> str:
    """„12 lat” / „8 mies.” — pełne lata w dół, poniżej roku miesiące."""
    from app.services.cv_new_layout.labels import counted, labels_for

    years = months // 12
    if years >= 1:
        return counted(language, "year", years)
    return f"{max(months, 1)} {labels_for(language)['months_short']}"


def _style_issue(text: str, ctx: WhyContext) -> Optional[str]:
    plain = strip_bold(text)
    if not plain.strip():
        return ISSUE_EMPTY
    if len(plain) > WHY_MAX_CHARS:
        return ISSUE_TOO_LONG
    if not is_one_sentence(text):
        return ISSUE_NOT_ONE_SENTENCE
    if _LABEL.search(plain):
        return ISSUE_LABEL
    if _GENDERED.search(plain):
        return ISSUE_GENDERED
    if ctx.blind:
        folded = plain.casefold()
        for role in ctx.roles:
            core = _company_core(role.company.split(" · ")[0])
            if len(core) >= 3 and core.casefold() in folded:
                return ISSUE_COMPANY_NAMED
    return None


def _has_term(text: str, term: str) -> bool:
    words = _words(term)
    if not words:
        return False
    return f" {' '.join(words)} " in f" {_phrase(text)} "


def _result(slot: str, text: str, issue: Optional[str], **extra: Any) -> dict:
    out: dict[str, Any] = {"slot": slot, "text": text, "verified": issue is None}
    if issue is not None:
        out["issue"] = issue
    out.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return out


def check_experience(item: Any, ctx: WhyContext) -> dict:
    """Zdanie 1: lata ze znaczników wstawia kod, reszta liczb z dat i punktu 1."""
    item = item if isinstance(item, dict) else {}
    raw = clean_text(item.get("text"))
    it_roles = _indexes(item.get("it_roles"))
    role_roles = _indexes(item.get("role_roles"))
    if not raw:
        return _result("experience", "", ISSUE_EMPTY)
    if it_roles is None or role_roles is None:
        return _result("experience", strip_bold(raw), ISSUE_BAD_ROLES)
    text = raw
    for token, indexes in ((TOKEN_IT, it_roles), (TOKEN_ROLE, role_roles)):
        if token not in text:
            continue
        if not indexes or any(_role(ctx, i) is None for i in indexes):
            return _result("experience", strip_bold(raw), ISSUE_BAD_ROLES)
        months = union_months(ctx, indexes)
        if months is None:
            return _result("experience", strip_bold(raw), ISSUE_BAD_ROLES)
        words = tenure_words(months, ctx.language)
        # Znacznik bywa już w pogrubieniu modelu — wtedy bez drugiej pary `**`.
        text = text.replace(f"**{token}**", f"**{words}**").replace(
            token, f"**{words}**"
        )
    text = clean_text(text)
    if "{" in text or "}" in text:
        return _result("experience", strip_bold(text), ISSUE_BAD_ROLES)
    issue = _style_issue(text, ctx)
    cited = [_role(ctx, i) for i in [*it_roles, *role_roles]]
    if issue is None:
        allowed = set()
        for point in ctx.why_points[:1]:
            allowed |= _numbers(point)
        for role in cited:
            if role is not None:
                # Z dat tylko lata („od 2017”) — miesiąc „12.2025” to nie „12 lat”.
                allowed |= {n for n in _numbers(role.dates) if len(n) == 4}
        # Lata wstawione przez kod nie są do sprawdzania — reszta liczb tak.
        own = raw.replace(TOKEN_IT, " ").replace(TOKEN_ROLE, " ")
        if not _numbers(own) <= allowed:
            issue = ISSUE_NUMBER_NOT_IN_CV
    if issue is None:
        for method in METHODS:
            if _has_term(text, method) and not _has_term(ctx.cv_text, method):
                issue = ISSUE_METHOD_NOT_IN_CV
                break
    return _result(
        "experience",
        _period_like(text, list(ctx.why_points[:2])),
        issue,
        roles=sorted({*it_roles, *role_roles}),
    )


def _must_name(value: Any, must: Sequence[str]) -> Optional[str]:
    wanted = _phrase(str(value or ""))
    for name in must:
        if wanted and _phrase(name) == wanted:
            return name
    return None


def check_requirements(item: Any, ctx: WhyContext) -> dict:
    """Zdanie 2: każdy MUST nazwany w zdaniu ma cytat z roli, w której stoi."""
    must = ctx.inputs.must
    item = item if isinstance(item, dict) else {}
    text = clean_text(item.get("text"))
    if not must:
        return _result("requirements", strip_bold(text), ISSUE_NO_INPUT)
    if not text:
        return _result("requirements", "", ISSUE_EMPTY)
    issue = _style_issue(text, ctx)
    evidence: list[dict[str, str]] = []
    proven: set[str] = set()
    allowed: set[str] = set()
    raw_evidence = item.get("evidence")
    for entry in (raw_evidence if isinstance(raw_evidence, list) else [])[
        :MAX_EVIDENCE
    ]:
        if not isinstance(entry, dict):
            continue
        quote = " ".join(strip_bold(str(entry.get("quote") or "")).split())
        name = _must_name(entry.get("must"), must)
        role = locate_role(quote, list(ctx.roles), entry.get("company"))
        if issue is None:
            if name is None:
                issue = ISSUE_MUST_UNKNOWN
            elif len(_words(quote)) < QUOTE_MIN_WORDS:
                issue = ISSUE_QUOTE_MISSING
            elif role is None:
                issue = ISSUE_QUOTE_NOT_IN_CV
            elif not (
                _has_term(quote, name)
                or any(_has_term(t, name) for t in role.technologies)
            ):
                issue = ISSUE_MUST_NOT_IN_QUOTE
        if name is not None and role is not None:
            proven.add(name)
            allowed |= _numbers(quote) | _numbers(role.text)
            evidence.append({"must": name, "quote": quote, "company": role.company})
    if issue is None and not evidence:
        issue = ISSUE_QUOTE_MISSING
    if issue is None:
        for name in must:
            if _has_term(text, name) and name not in proven:
                issue = ISSUE_MUST_WITHOUT_PROOF
                break
    if issue is None:
        for name in must:
            allowed |= _numbers(name)
        if not _numbers(text) <= allowed:
            issue = ISSUE_NUMBER_NOT_IN_CV
    return _result(
        "requirements",
        _period_like(text, list(ctx.why_points[:2])),
        issue,
        evidence=evidence,
    )


def check_key_task(item: Any, ctx: WhyContext) -> dict:
    """Zdanie 3: dowód z punktu roli albo z odpowiedzi kandydata na screeningu."""
    task = ctx.inputs.key_task.strip()
    item = item if isinstance(item, dict) else {}
    text = clean_text(item.get("text"))
    if not task:
        return _result("key_task", strip_bold(text), ISSUE_NO_INPUT)
    if not text:
        return _result("key_task", "", ISSUE_EMPTY)
    quote = " ".join(strip_bold(str(item.get("quote") or "")).split())
    source = "screening" if item.get("source") == "screening" else "cv"
    issue = _style_issue(text, ctx)
    role = None
    allowed = _numbers(quote) | _numbers(task)
    if issue is None and len(_words(quote)) < QUOTE_MIN_WORDS:
        issue = ISSUE_QUOTE_MISSING
    if issue is None:
        if source == "screening":
            if f" {_phrase(quote)} " not in f" {_phrase(ctx.inputs.answer)} ":
                issue = ISSUE_QUOTE_NOT_IN_CV
            allowed |= _numbers(ctx.inputs.answer)
        else:
            role = locate_role(quote, list(ctx.roles), item.get("company"))
            if role is None:
                issue = ISSUE_QUOTE_NOT_IN_CV
            else:
                allowed |= _numbers(role.text)
    if issue is None and not _numbers(text) <= allowed:
        issue = ISSUE_NUMBER_NOT_IN_CV
    return _result(
        "key_task",
        _period_like(text, list(ctx.why_points[:2])),
        issue,
        quote=quote,
        source=source,
        company=role.company if role is not None else None,
    )


def verify_why(data: Any, ctx: WhyContext) -> list[dict]:
    """Odpowiedź modelu → trzy wpisy `page1_extras.why_generated` (slot 1–3)."""
    data = data if isinstance(data, dict) else {}
    return [
        check_experience(data.get("experience"), ctx),
        check_requirements(data.get("requirements"), ctx),
        check_key_task(data.get("key_task"), ctx),
    ]


def auto_texts(generated: Any) -> list[str]:
    """Sprawdzone zdania generatora per slot; ``""`` = slot bez zdania."""
    out = ["", "", ""]
    for index, item in enumerate(generated if isinstance(generated, list) else []):
        if index < 3 and isinstance(item, dict) and item.get("verified") is True:
            out[index] = str(item.get("text") or "").strip()
    return out


def why_slots(extras: Optional[dict]) -> list[str]:
    """`page1_extras.why` jako trzy sloty; ``""`` = slot bierze punkt generatora."""
    why = extras.get("why") if isinstance(extras, dict) else None
    slots = [
        " ".join(str(item or "").split())
        for item in (why if isinstance(why, list) else [])[:3]
    ]
    return slots + [""] * (3 - len(slots))


def merged_why(
    extras: Optional[dict], generated: list[dict], sha: str
) -> dict[str, Any]:
    """Nowe dodatki: slot poprawiony przez rekrutera zostaje, reszta bierze
    nowe sprawdzone zdanie (albo pusty slot = punkt generatora)."""
    merged = dict(extras) if isinstance(extras, dict) else {}
    before = auto_texts(merged.get("why_generated"))
    after = auto_texts(generated)
    slots = why_slots(merged)
    merged["why"] = [
        after[i] if slots[i] in ("", before[i]) else slots[i] for i in range(3)
    ]
    merged["why_generated"] = generated
    merged["why_source_sha"] = sha
    return merged
