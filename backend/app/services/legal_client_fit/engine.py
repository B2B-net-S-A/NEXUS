"""Porównanie wymogów umowy klienta z naszym wzorem (funkcja AI ``legal_client_fit``, F59).

Model wskazuje temat, stan i dwa cytaty (fragment klienta ``K…``, fragment
naszego wzoru ``T…``). Wszystko inne robi kod:

* **każdy cytat sprawdza ``citations.verify``** z tekstem fragmentu, który
  model wskazał; ustalenie z cytatem bez pokrycia odpada (``Dropped``) —
  nie trafia do bazy ani na ekran;
* ``ok`` i ``decide`` wymagają też naszego cytatu; ``gap`` może mieć „brak”
  po naszej stronie;
* oznaczenie fragmentu klienta (§, ust.) liczy kod z układu dokumentu,
  następny krok bierze z katalogu tematów;
* treść do aneksu odpada, gdy wpisuje liczbę, której nie ma w cytacie
  klienta, albo znacznik danych spoza mapy (model zgadł dane);
* dane osób idą do modelu wyłącznie jako znaczniki (``pseudonymize``).

Bez modelu (brak klucza, funkcja wyłączona, awaria) wynik ma status
``unavailable`` albo ``failed`` i żadnych ustaleń — ekran mówi „sprawdzenie
niedostępne”, nic nie udaje zgodności.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.services.legal import citations
from app.services.legal.assistant import lawyer_triggers
from app.services.legal.citations import SourcePassage
from app.services.legal.pseudonymize import Entity, mask, unknown_tokens, unmask
from app.services.legal_client_fit.sources import (
    ClientPassage,
    TemplatePassage,
    client_ref,
)
from app.services.legal_client_fit.topics import (
    DECIDE_STEP,
    TOPIC_BY_KEY,
    TOPICS,
    Topic,
)

logger = logging.getLogger(__name__)

Status = Literal["done", "unavailable", "failed"]
STATES = ("ok", "gap", "decide")
SUMMARY_MAX = 400
QUOTE_MAX = 1500
ANNEX_TEXT_MAX = 2000
MAX_TOKENS = 6000
TIMEOUT_SECONDS = 180.0

MSG_NO_KEY = (
    "Sprawdzenie niedostępne: brak klucza dostawcy AI. NEXUS nie ocenia "
    "zgodności bez modelu — porównaj umowę klienta z wzorem samodzielnie."
)
MSG_OFF = (
    "Sprawdzenie niedostępne: funkcja AI „Asystent prawny — zgodność z umową "
    "klienta” jest wyłączona albo wyczerpała limit."
)
MSG_FAILED = (
    "Sprawdzenie nie udało się — model nie odpowiedział. Spróbuj ponownie "
    "za kilka minut."
)

#: Liczba jako osobny wyraz — „B2BNET” czy „ISO 27001” w nazwie to nie termin.
_DIGITS = re.compile(r"(?<![^\W\d_])\d+(?![^\W\d_])")
#: Cudzysłowy w środku cytatu (umowy piszą „Klient”) — weryfikator wyciąga
#: cytat między cudzysłowami, więc w próbce zamieniamy je na apostrof po obu
#: stronach porównania.
_QUOTE_CHARS = re.compile(r"[„”“\"«»]")


@dataclass(frozen=True)
class Finding:
    topic: str
    state: str
    summary: str
    client_quote: str
    client_ref: str
    client_source_kind: str
    client_source_id: int
    our_quote: Optional[str]
    our_ref: Optional[str]
    next_step: Optional[str]
    annex_text: Optional[str]
    lawyer_review: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dropped:
    topic: Optional[str]
    reason: str


@dataclass
class FitOutcome:
    status: Status
    findings: list[Finding] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    message: Optional[str] = None
    model: Optional[str] = None


# ── sprawdzenie cytatu ──────────────────────────────────────────────────────


def quote_verified(quote: str, passage_text: str, kind: str) -> bool:
    """Czy ``quote`` stoi dosłownie w ``passage_text`` — sprawdza ``citations.verify``.

    Próbka „§ 1 umowy „cytat”” odwołuje się do jedynego fragmentu „§ 1”, więc
    werdykt zależy wyłącznie od zgodności cytatu z tekstem (wielkość liter,
    odstępy, myślniki i „(…)” jak w weryfikatorze fundamentu).
    """
    quote = (quote or "").strip()
    if len(quote) < 3 or not (passage_text or "").strip():
        return False
    probe_quote = _QUOTE_CHARS.sub("'", quote)
    probe = SourcePassage(
        kind=kind, ref="§ 1", text=_QUOTE_CHARS.sub("'", passage_text)
    )
    checks = citations.verify(f"§ 1 umowy „{probe_quote}”", [probe])
    return (
        len(checks) == 1
        and checks[0].citation.quote is not None
        and checks[0].status == citations.STATUS_OK
    )


def _numbers_from_client_only(text: str, client_quote: str) -> bool:
    allowed = set(_DIGITS.findall(client_quote))
    return all(number in allowed for number in _DIGITS.findall(text))


# ── prompt ──────────────────────────────────────────────────────────────────


def _topics_block(topics: Sequence[Topic]) -> str:
    from app.services.prompt_fencing import fence

    lines = [f"- {t.key}: {t.label} (w naszym wzorze szukaj: {t.ours})" for t in topics]
    return fence("tematy", "\n".join(lines))


def _client_block(passages: Sequence[ClientPassage], texts: Sequence[str]) -> str:
    from app.services.prompt_fencing import fence

    body = "\n\n".join(
        f"[{p.key}] {p.document_label}\n{text}" for p, text in zip(passages, texts)
    )
    return fence("umowa_klienta", body or "(brak)")


def _ours_block(passages: Sequence[TemplatePassage], texts: Sequence[str]) -> str:
    from app.services.prompt_fencing import fence

    body = "\n\n".join(f"[{p.key}] {p.ref}\n{text}" for p, text in zip(passages, texts))
    return fence("nasz_wzor", body or "(brak)")


def build_prompt(
    client: Sequence[ClientPassage],
    ours: Sequence[TemplatePassage],
    entities: Sequence[Entity],
    topics: Sequence[Topic] = TOPICS,
) -> tuple[str, dict[str, str]]:
    """Prompt z danymi osób zamienionymi na znaczniki i mapa znaczników."""
    from app.services.llm_prompts import LEGAL_CLIENT_FIT

    joiner = "\n\x1e\n"
    masked, mapping = mask(
        joiner.join([*(p.text for p in client), *(p.text for p in ours)]), entities
    )
    pieces = masked.split(joiner)
    client_texts = pieces[: len(client)]
    our_texts = pieces[len(client) :]
    prompt = LEGAL_CLIENT_FIT.render(
        topics=_topics_block(topics),
        client=_client_block(client, client_texts),
        ours=_ours_block(ours, our_texts),
    )
    return prompt, mapping


# ── odpowiedź modelu ────────────────────────────────────────────────────────


def _json_object(text: str) -> Optional[dict[str, Any]]:
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None


def _side(item: dict[str, Any], key: str) -> tuple[Optional[str], Optional[str]]:
    side = item.get(key)
    if not isinstance(side, dict):
        return None, None
    source = side.get("source")
    quote = side.get("quote")
    return (
        str(source).strip() if source else None,
        str(quote).strip()[:QUOTE_MAX] if quote else None,
    )


def parse_reply(
    reply: str,
    *,
    client: Sequence[ClientPassage],
    ours: Sequence[TemplatePassage],
    mapping: dict[str, str],
    whole_texts: dict[tuple[str, int], str],
) -> tuple[Optional[list[Finding]], list[Dropped]]:
    """Ustalenia z odpowiedzi modelu, każde z cytatami sprawdzonymi kodem.

    ``None`` = odpowiedź nie jest obiektem JSON (model zawiódł).
    """
    raw = _json_object(reply)
    if raw is None or not isinstance(raw.get("findings"), list):
        return None, []
    client_by_key = {p.key: p for p in client}
    ours_by_key = {p.key: p for p in ours}
    findings: list[Finding] = []
    dropped: list[Dropped] = []
    seen: set[str] = set()
    for item in raw["findings"]:
        if not isinstance(item, dict):
            continue
        topic = TOPIC_BY_KEY.get(str(item.get("topic") or ""))
        if topic is None:
            dropped.append(Dropped(None, "Temat spoza katalogu."))
            continue
        if topic.key in seen:
            dropped.append(Dropped(topic.key, "Drugie ustalenie tego samego tematu."))
            continue
        state = str(item.get("state") or "")
        if state not in STATES:
            dropped.append(Dropped(topic.key, "Nieznany stan ustalenia."))
            continue

        client_key, client_quote = _side(item, "client")
        passage = client_by_key.get(client_key or "")
        client_quote = unmask(client_quote or "", mapping)
        if passage is None or not quote_verified(client_quote, passage.text, "client"):
            dropped.append(
                Dropped(
                    topic.key, "Cytatu klienta nie ma we wskazanym fragmencie umowy."
                )
            )
            continue

        our_key, our_quote = _side(item, "ours")
        our_passage: Optional[TemplatePassage] = None
        if our_key or our_quote:
            our_passage = ours_by_key.get(our_key or "")
            our_quote = unmask(our_quote or "", mapping)
            if our_passage is None or not quote_verified(
                our_quote, our_passage.text, "template"
            ):
                dropped.append(
                    Dropped(
                        topic.key,
                        "Naszego cytatu nie ma we wskazanym paragrafie wzoru.",
                    )
                )
                continue
        else:
            our_quote = None
        if state != "gap" and our_passage is None:
            dropped.append(
                Dropped(topic.key, "Zgodność albo decyzja bez cytatu z naszego wzoru.")
            )
            continue

        annex_text: Optional[str] = None
        raw_annex = str(item.get("annex_text") or "").strip()[:ANNEX_TEXT_MAX]
        if state != "ok" and raw_annex:
            if unknown_tokens(raw_annex, mapping):
                annex_text = None
            else:
                candidate = unmask(raw_annex, mapping)
                if _numbers_from_client_only(candidate, client_quote):
                    annex_text = candidate

        summary = unmask(str(item.get("summary") or "").strip(), mapping)[:SUMMARY_MAX]
        findings.append(
            Finding(
                topic=topic.key,
                state=state,
                summary=summary or topic.label,
                client_quote=client_quote,
                client_ref=client_ref(
                    passage,
                    client_quote,
                    whole_texts.get((passage.source_kind, passage.source_id)),
                ),
                client_source_kind=passage.source_kind,
                client_source_id=passage.source_id,
                our_quote=our_quote if our_passage else None,
                our_ref=our_passage.ref if our_passage else None,
                next_step=(
                    topic.gap_step
                    if state == "gap"
                    else DECIDE_STEP
                    if state == "decide"
                    else None
                ),
                annex_text=annex_text,
                lawyer_review=tuple(lawyer_triggers(client_quote, annex_text or "")),
            )
        )
        seen.add(topic.key)
    return findings, dropped


# ── model ───────────────────────────────────────────────────────────────────


def _call_model(prompt: str, system: str) -> str:
    from app.services.ai_models import fallbacks_for, model_for
    from app.services.claude_client import call_claude, text_of

    message = call_claude(
        model=model_for(AIFeatureKey.legal_client_fit),
        fallback_models=list(fallbacks_for(AIFeatureKey.legal_client_fit)) or None,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=system,
        total_timeout=TIMEOUT_SECONDS,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def compare(
    db: AsyncSession,
    *,
    client: Sequence[ClientPassage],
    ours: Sequence[TemplatePassage],
    entities: Sequence[Entity],
    whole_texts: dict[tuple[str, int], str],
) -> FitOutcome:
    """Ustalenia dla klienta; bez modelu — status bez ustaleń (nic nie udaje zgodności)."""
    from fastapi.concurrency import run_in_threadpool

    from app.services.ai_models import model_for
    from app.services.ai_quota import AIQuotaExceeded, ai_feature
    from app.services.llm_prompts import LEGAL_CLIENT_FIT
    from app.services.llm_providers import api_key_configured

    model = model_for(AIFeatureKey.legal_client_fit)
    if not api_key_configured(model):
        return FitOutcome(status="unavailable", message=MSG_NO_KEY)
    prompt, mapping = build_prompt(client, ours, entities)
    try:
        async with ai_feature(db, AIFeatureKey.legal_client_fit):
            await db.commit()  # połączenie wraca do puli na czas modelu
            reply = await run_in_threadpool(
                _call_model, prompt, LEGAL_CLIENT_FIT.system_prompt or ""
            )
    except AIQuotaExceeded:
        return FitOutcome(status="unavailable", message=MSG_OFF)
    except Exception as exc:  # noqa: BLE001 — zgodność to dodatek, ekran mówi „niedostępne”
        logger.warning(
            "[legal_client_fit] model nie odpowiedział: %s", type(exc).__name__
        )
        return FitOutcome(status="failed", message=MSG_FAILED)
    findings, dropped = parse_reply(
        reply, client=client, ours=ours, mapping=mapping, whole_texts=whole_texts
    )
    if findings is None:
        return FitOutcome(status="failed", message=MSG_FAILED, model=model)
    if dropped:
        logger.info(
            "[legal_client_fit] odrzucone ustalenia bez pokrycia: %d", len(dropped)
        )
    return FitOutcome(status="done", findings=findings, dropped=dropped, model=model)
