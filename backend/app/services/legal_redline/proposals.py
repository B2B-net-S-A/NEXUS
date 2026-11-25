"""Propozycje zmian z modelu (funkcja AI ``legal_redline``).

Model dostaje polecenie, ponumerowane akapity dokumentu z danymi osób jako
znacznikami i fragmenty źródeł. Oddaje zmiany z kotwicą (akapit + dosłowny
fragment), nowym tekstem, powodem i cytatami. Kod:

* odmaskowuje tekst po stronie NEXUSA,
* sprawdza kotwicę w dokumencie (zła → zmiana odpada z powodem),
* sprawdza każdy cytat ze źródłem (``verify_sources``; bez pokrycia →
  zmiana zablokowana do przyjęcia),
* odrzuca zmianę ze znacznikiem, którego nie ma w mapie (model zgadł dane).

Wynik modelu jest dodatkiem: awaria, wyłączona funkcja albo brak polecenia
dają pustą listę i stan, a ręczna lista zmian i porównanie wersji działają.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for
from app.services.legal_redline.foundation import (
    Entity,
    SourcePassage,
    detect_entities,
    mask,
    search_law,
    unmask,
    verify_sources,
)
from app.services.legal_redline.model import (
    ChangeSource,
    Paragraph,
    RedlineChange,
    RedlineError,
)
from app.services.legal_redline.tracked import resolve_changes

logger = logging.getLogger(__name__)

ProposalStatus = Literal["ok", "failed", "off", "no_instruction", "too_long"]

DOCUMENT_REF = "dokument"
MAX_DOCUMENT_CHARS = 120_000
MAX_CHANGES = 40
_MARKER = re.compile(r"\[[A-Z_]+(?:_\d+)?\]")

PROMPT = """Jesteś prawnikiem polskiej firmy IT, która zawiera umowy B2B z kontraktorami \
i umowy z klientami. Poprawiasz dokument według polecenia użytkownika.

Dostajesz:
- POLECENIE użytkownika,
- DOKUMENT: akapity w formacie „[numer] treść”; dane osób i firm są zastąpione \
znacznikami w nawiasach kwadratowych ([PARTNER], [NIP], [EMAIL]…) — zostaw je \
bez zmian, nie wymyślaj nowych,
- ŹRÓDŁA: fragmenty w formacie „<<ref>> etykieta: treść”. Sam dokument to źródło \
o ref „dokument”.

Zasady:
- Zmieniaj tylko to, czego wymaga polecenie. Każda zmiana ma krótki powód po polsku.
- Kotwica: „paragraph” to numer akapitu, „find” to DOSŁOWNY fragment tego akapitu \
(skopiowany znak w znak, możliwie krótki, ale jednoznaczny w akapicie).
- Rodzaje: „replace” — „find” zamienia się na „new_text” (pusty „find” = dopisanie \
na końcu akapitu, pusty „new_text” = skreślenie); „insert_paragraph” — nowy akapit \
„new_text” za akapitem „paragraph”; „delete_paragraph” — skreślenie całego akapitu.
- Cytaty: w „sources” podawaj tylko dosłowne fragmenty ŹRÓDEŁ (ref + quote). \
Nie cytuj z pamięci i nie podawaj przepisów, których nie ma w ŹRÓDŁACH — wtedy \
zostaw „sources” puste, a w powodzie napisz, że podstawę trzeba sprawdzić.
- Nie licz terminów, dat ani kwot słownie i nie wpisuj nowych kwot — jeśli zmiana \
tego wymaga, opisz to w powodzie.
- Kara umowna, spór z klientem albo rozwiązanie ze skutkiem natychmiastowym: dodaj \
w „notes” zdanie, że sprawa wymaga prawnika.
- Postanowienia, które już spełniają polecenie, opisz w „notes” (jedno zdanie każde).

Odpowiedz wyłącznie JSON-em:
{"changes": [{"paragraph": 0, "kind": "replace", "find": "...", "new_text": "...", \
"reason": "...", "sources": [{"ref": "...", "quote": "..."}]}], "notes": ["..."]}"""


@dataclass(frozen=True)
class DroppedChange:
    paragraph: int | None
    reason: str


@dataclass
class Proposal:
    status: ProposalStatus
    changes: list[RedlineChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dropped: list[DroppedChange] = field(default_factory=list)
    model: str | None = None


def _document_block(paragraphs: list[Paragraph]) -> str:
    return "\n".join(f"[{p.index}] {p.text}" for p in paragraphs if p.text.strip())


def _sources_block(passages: list[SourcePassage]) -> str:
    return "\n\n".join(
        f"<<{p.ref}>> {p.label or p.ref}: {p.text}" for p in passages if p.ref != DOCUMENT_REF
    )


def build_messages(
    instruction: str, masked_document: str, passages: list[SourcePassage]
) -> list[dict[str, Any]]:
    sources = _sources_block(passages) or "(brak źródeł poza dokumentem)"
    content = (
        f"POLECENIE:\n{instruction.strip()}\n\nDOKUMENT:\n{masked_document}\n\n"
        f"ŹRÓDŁA:\n{sources}\n\n{PROMPT}"
    )
    return [{"role": "user", "content": content}]


def _call_model(messages: list[dict[str, Any]]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_for(AIFeatureKey.legal_redline),
        fallback_models=list(fallbacks_for(AIFeatureKey.legal_redline)),
        max_tokens=8000,
        temperature=0,
        thinking={"type": "disabled"},
        messages=messages,
    )
    return text_of(message)


def _json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None


def parse_reply(
    reply: str,
    *,
    paragraphs: list[Paragraph],
    mapping: dict[str, str],
    passages: list[SourcePassage],
) -> Proposal:
    """Odpowiedź modelu → zmiany sprawdzone kodem (kotwica, znaczniki, cytaty)."""

    raw = _json_object(reply)
    if raw is None:
        return Proposal(status="failed")
    texts = [p.text for p in paragraphs]
    proposal = Proposal(status="ok")
    for note in raw.get("notes") or []:
        if isinstance(note, str) and note.strip():
            proposal.notes.append(unmask(note.strip(), mapping))
    for n, item in enumerate((raw.get("changes") or [])[:MAX_CHANGES]):
        if not isinstance(item, dict):
            continue
        para = item.get("paragraph")
        kind = item.get("kind") or "replace"
        if not isinstance(para, int) or kind not in ("replace", "insert_paragraph", "delete_paragraph"):
            proposal.dropped.append(DroppedChange(para if isinstance(para, int) else None, "Zła kotwica zmiany."))
            continue
        masked_new = str(item.get("new_text") or "")
        unknown = [m for m in _MARKER.findall(masked_new) if m not in mapping]
        if unknown:
            proposal.dropped.append(
                DroppedChange(para, f"Zmiana wpisuje dane, których nie ma w dokumencie ({', '.join(unknown)}).")
            )
            continue
        sources = tuple(
            ChangeSource(
                ref=str(s.get("ref") or ""),
                label="",
                quote=unmask(str(s.get("quote") or ""), mapping),
            )
            for s in item.get("sources") or []
            if isinstance(s, dict)
        )
        change = RedlineChange(
            id=f"a{n + 1}",
            kind=kind,
            paragraph=para,
            find=unmask(str(item.get("find") or ""), mapping),
            new_text=unmask(masked_new, mapping),
            reason=unmask(str(item.get("reason") or ""), mapping),
            sources=tuple(verify_sources(list(sources), passages)),
        )
        if kind == "delete_paragraph" and 0 <= para < len(texts):
            change = replace(change, find=texts[para])
        try:
            change = resolve_changes(texts, [change])[0]
        except RedlineError as exc:
            proposal.dropped.append(DroppedChange(para, str(exc)))
            continue
        try:
            resolve_changes(texts, [*proposal.changes, change])
        except RedlineError as exc:
            proposal.dropped.append(DroppedChange(para, str(exc)))
            continue
        proposal.changes.append(change)
    return proposal


async def propose(
    db: Any,
    *,
    paragraphs: list[Paragraph],
    instruction: str,
    entities: list[Entity],
    user_id: int | None,
    extra_passages: list[SourcePassage] | None = None,
) -> Proposal:
    """Propozycje modelu dla dokumentu; ``ai_feature`` deklaruje i nalicza wywołanie."""

    from app.services.ai_quota import AIQuotaExceeded, ai_feature  # noqa: PLC0415

    if not instruction.strip():
        return Proposal(status="no_instruction")
    document = _document_block(paragraphs)
    if len(document) > MAX_DOCUMENT_CHARS:
        return Proposal(status="too_long")
    all_entities = [*entities, *detect_entities(document)]
    masked_document, mapping = mask(document, all_entities)
    law = await search_law(db, instruction)
    passages = [
        SourcePassage(kind="contract", ref=DOCUMENT_REF, text=document, label="Dokument"),
        *law,
        *(extra_passages or []),
    ]
    masked_passages = [
        SourcePassage(kind=p.kind, ref=p.ref, text=mask(p.text, all_entities)[0], url=p.url, label=p.label)
        for p in passages
    ]
    messages = build_messages(instruction, masked_document, masked_passages)
    try:
        async with ai_feature(db, AIFeatureKey.legal_redline, user_id=user_id):
            await db.commit()  # połączenie wraca do puli na czas modelu
            reply = await run_in_threadpool(_call_model, messages)
    except AIQuotaExceeded:
        return Proposal(status="off")
    except Exception as exc:  # noqa: BLE001 — propozycje to dodatek, ręczna ścieżka działa
        logger.warning("legal_redline: propozycje nieudane (%s)", type(exc).__name__)
        return Proposal(status="failed")
    proposal = parse_reply(reply, paragraphs=paragraphs, mapping=mapping, passages=passages)
    proposal.model = model_for(AIFeatureKey.legal_redline)
    return proposal
