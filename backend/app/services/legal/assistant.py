"""Szkic pisma asystenta prawnego (funkcja AI ``legal_assistant``, F56).

Decyzje Artura 25.11.2026 (``docs/asystent-prawny-plan.md``):

* **nic nie wychodzi samo** — ``draft`` zwraca szkic, niczego nie zapisuje
  i nie wysyła; człowiek zatwierdza na ekranie (części D–F);
* **każdy cytat sprawdza kod** — wynik niesie ``checks`` z ``citations.verify``,
  a cytat bez pokrycia ustawia ``blocked``;
* **terminy, daty, kwoty liczy kod** — wołający podaje je jako ``Entity``
  (``DATA_ROZWIAZANIA`` = „31 grudnia 2026 r.” z ``deadlines``); model widzi
  tylko znacznik. Data albo kwota wpisana przez model sama to ``issues``
  i ``blocked``;
* **dane osób do modelu tylko jako znaczniki** (``pseudonymize``), podmiana
  z powrotem po stronie NEXUSA;
* **LEX i Gofin nigdy do modelu** — fragment z takim adresem odpada;
* **próg do prawnika** — kara umowna, spór z klientem, rozwiązanie ze skutkiem
  natychmiastowym dają ``lawyer_review`` (etykieta w UI). Asystent nie jest
  poradą prawną.

Model jest dodatkiem: bez klucza, przy awarii albo wyłączonej funkcji ``draft``
oddaje fragmenty źródeł i ``error`` — ekran pokazuje je i pozwala pisać samemu.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.legal import citations, corpus
from app.services.legal.citations import CitationCheck, SourcePassage
from app.services.legal.pseudonymize import Entity, mask, unknown_tokens, unmask

logger = logging.getLogger(__name__)

KINDS: dict[str, str] = {
    "termination": "wypowiedzenie umowy",
    "annex": "aneks do umowy",
    "reply": "odpowiedź na pismo",
    "letter": "pismo do drugiej strony",
}
INSTRUCTION_MAX = 4000
PASSAGES_MAX = 20
PASSAGE_CHARS = 6000
SEARCH_HITS = 6
MAX_TOKENS = 2500
TIMEOUT_SECONDS = 90.0
#: Licencje LEX i Gofina: treść nigdy nie idzie do modelu (decyzja 5 planu).
#: Host z portem, zapytaniem albo fragmentem też („sip.lex.pl:443/x”, „gofin.pl#x”).
_LICENSED_HOSTS = re.compile(
    r"(?:^|//|\.|@)(?:lex\.pl|sip\.lex\.pl|gofin\.pl)\.?(?:[/:?#]|$)", re.I
)

_DATE_IN_TEXT = re.compile(
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|"
    r"\b\d{1,2}\s+(?:stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|"
    r"września|października|listopada|grudnia)\b",
    re.I,
)
_AMOUNT_IN_TEXT = re.compile(
    r"\b\d[\d\s.,]*\s?(?:zł|złotych|pln|eur|euro|usd)\b|"
    r"\b\d+\s?(?:dni|dzień|dnia|miesiąc\w*|miesięcy|tydzień|tygodni\w*|lat|lata|roku)\b",
    re.I,
)
_LAWYER_TRIGGERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("kara umowna", re.compile(r"kar[ayęo]\w*\s+umown", re.I)),
    ("spór z klientem", re.compile(r"\bsp[oó]r\w*|\bsąd\w*|pozw\w*", re.I)),
    (
        "rozwiązanie ze skutkiem natychmiastowym",
        re.compile(r"natychmiastow\w*|bez\s+zachowania\s+okresu\s+wypowiedzenia", re.I),
    ),
)


class DraftUnavailable(RuntimeError):
    """Model nie odpowiedział albo funkcja jest wyłączona (szkic bez tekstu)."""


@dataclass(frozen=True)
class Draft:
    text: str
    citations: list[citations.Citation]
    checks: list[CitationCheck]
    blocked: bool
    passages: list[SourcePassage] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    lawyer_review: list[str] = field(default_factory=list)
    model: Optional[str] = None
    error: Optional[str] = None


def lawyer_triggers(*texts: str) -> list[str]:
    """Powody, dla których pismo powinien zobaczyć prawnik (decyzja 7 planu)."""
    joined = "\n".join(t for t in texts if t)
    return [label for label, pattern in _LAWYER_TRIGGERS if pattern.search(joined)]


def allowed_passages(passages: Iterable[SourcePassage]) -> list[SourcePassage]:
    """Fragmenty bez treści z LEX-u i Gofina, najwyżej ``PASSAGES_MAX``."""
    out = []
    for passage in passages:
        if passage.url and _LICENSED_HOSTS.search(passage.url):
            continue
        if (
            passage.kind not in citations.PASSAGE_KINDS
            or not (passage.text or "").strip()
        ):
            continue
        out.append(passage)
    return out[:PASSAGES_MAX]


def _sources_block(
    passages: Sequence[SourcePassage], short_names: dict[str, str]
) -> str:
    from app.services.prompt_fencing import fence

    chunks = []
    for number, passage in enumerate(passages, start=1):
        if passage.kind == citations.KIND_LAW:
            head = f"[{number}] {passage.ref} {short_names.get(passage.act_key or '', '')}".strip()
        else:
            head = f"[{number}] {passage.ref} ({passage.label or passage.kind})"
        chunks.append(f"{head}\n{passage.text[:PASSAGE_CHARS]}")
    return fence("zrodla", "\n\n".join(chunks) or "(brak)")


def _tokens_block(mapping: dict[str, str]) -> str:
    from app.services.prompt_fencing import fence

    described = ", ".join(mapping) if mapping else "(brak)"
    return fence("znaczniki", f"Dostępne znaczniki: {described}")


def code_issues(model_text: str, mapping: dict[str, str]) -> list[str]:
    """Daty, kwoty i nieznane znaczniki wpisane przez model (liczy je kod)."""
    issues = []
    for match in _DATE_IN_TEXT.finditer(model_text):
        issues.append(f"Model wpisał datę „{match.group(0)}” — daty podaje kod.")
    for match in _AMOUNT_IN_TEXT.finditer(model_text):
        issues.append(
            f"Model wpisał liczbę „{match.group(0).strip()}” — terminy i kwoty podaje kod."
        )
    for token in unknown_tokens(model_text, mapping):
        issues.append(f"Model użył znacznika {token}, którego nie ma w danych.")
    return issues[:20]


def _call_model(prompt: str, system: str, model: str, fallbacks: list[str]) -> str:
    from app.services.claude_client import call_claude, text_of

    message = call_claude(
        model=model,
        fallback_models=fallbacks or None,
        max_tokens=MAX_TOKENS,
        system=system,
        total_timeout=TIMEOUT_SECONDS,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message).strip()


async def draft(
    db: AsyncSession,
    *,
    kind: str,
    instruction: str,
    passages: Sequence[SourcePassage],
    entities: Sequence[Entity],
    user_id: Optional[int] = None,
    on_date: Optional[date] = None,
) -> Draft:
    """Szkic pisma rodzaju ``kind`` ze sprawdzonymi cytatami (niczego nie zapisuje)."""
    from fastapi.concurrency import run_in_threadpool

    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import model_chain_for
    from app.services.ai_quota import ai_feature
    from app.services.llm_prompts import LEGAL_ASSISTANT_DRAFT
    from app.services.llm_providers import api_key_configured
    from app.services.prompt_fencing import fence

    if kind not in KINDS:
        raise ValueError(f"Nieznany rodzaj pisma: {kind!r}.")
    instruction = (instruction or "").strip()[:INSTRUCTION_MAX]
    sources = allowed_passages(passages)
    if not any(p.kind == citations.KIND_LAW for p in sources) and instruction:
        found = await corpus.search_provisions(
            db, f"{KINDS[kind]} {instruction}", on_date=on_date, limit=SEARCH_HITS
        )
        sources = [*sources, *(corpus.as_passage(hit) for hit in found)][:PASSAGES_MAX]
    lawyer = lawyer_triggers(instruction)
    short_names = {spec.key: spec.short_name for spec in corpus.ACTS}

    # Maska jednym przebiegiem dla polecenia i fragmentów, żeby ta sama osoba
    # miała ten sam znacznik wszędzie.
    joiner = "\n\x1e\n"
    masked_all, mapping = mask(
        joiner.join([instruction, *(p.text[:PASSAGE_CHARS] for p in sources)]), entities
    )
    pieces = masked_all.split(joiner)
    masked_instruction = pieces[0]
    masked_sources = [
        SourcePassage(p.kind, p.ref, text, p.url, p.label, p.act_key)
        for p, text in zip(sources, pieces[1:])
    ]
    for entity in entities:
        # Wartości liczone kodem (daty, kwoty) muszą mieć znacznik, nawet gdy
        # nie stoją w poleceniu ani w źródłach.
        if not any(v == entity.value.strip() for v in mapping.values()):
            _ignored, extra = mask(entity.value, [entity], detect=False)
            for token, value in extra.items():
                if token not in mapping:
                    mapping[token] = value

    chain = model_chain_for(AIFeatureKey.legal_assistant)
    if not api_key_configured(chain[0]):
        return Draft(
            text="",
            citations=[],
            checks=[],
            blocked=True,
            passages=sources,
            lawyer_review=lawyer,
            error="Brak klucza dostawcy AI — fragmenty źródeł są niżej, pismo można napisać samemu.",
        )
    prompt = LEGAL_ASSISTANT_DRAFT.render(
        kind=KINDS[kind],
        instruction=fence("polecenie", masked_instruction or "(brak)"),
        tokens=_tokens_block(mapping),
        sources=_sources_block(masked_sources, short_names),
    )
    try:
        async with ai_feature(db, AIFeatureKey.legal_assistant, user_id=user_id):
            await db.commit()
            model_text = await run_in_threadpool(
                _call_model,
                prompt,
                LEGAL_ASSISTANT_DRAFT.system_prompt or "",
                chain[0],
                chain[1:],
            )
    except Exception as exc:  # noqa: BLE001 — każda awaria modelu = szkic bez tekstu
        logger.warning("[legal] szkic pisma nieudany: %s", type(exc).__name__)
        return Draft(
            text="",
            citations=[],
            checks=[],
            blocked=True,
            passages=sources,
            lawyer_review=lawyer,
            error="Asystent nie odpowiedział — fragmenty źródeł są niżej, pismo można napisać samemu.",
        )
    issues = code_issues(model_text, mapping)
    text = unmask(model_text, mapping)
    checks = await corpus.verify_text(db, text, sources, on_date=on_date)
    found = [check.citation for check in checks]
    if not model_text:
        issues.append("Model oddał pustą odpowiedź.")
    return Draft(
        text=text,
        citations=found,
        checks=checks,
        blocked=citations.blocking(checks) or bool(issues),
        passages=sources,
        issues=issues,
        lawyer_review=lawyer_triggers(instruction, text),
        model=chain[0],
    )
