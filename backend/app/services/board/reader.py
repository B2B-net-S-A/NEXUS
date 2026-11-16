"""Odczyt skanu dokumentu korporacyjnego (F51, 0725).

Model z rejestru (``AIFeatureKey.board_document_read``) dostaje sam plik
wgrany przez admina — uchwałę, protokół albo regulamin. Wynik to propozycja:
rodzaj, organ, numer, data i przedmiot wracają do admina do zatwierdzenia
i nigdy nie nadpisują pól, które admin już wpisał. Awaria modelu albo śmieci
w odpowiedzi = ``ReadResult("failed")`` — dokument zostaje, admin wpisuje
pola sam.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for
from app.services.board_documents_schema import CATEGORIES, ORGANS

logger = logging.getLogger(__name__)

READER_VERSION = "board_read:v1"
SUPPORTED_MIME: frozenset[str] = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/webp"}
)
_SUBJECT_MAX = 600
_NUMBER_MAX = 64

PROMPT = """Odczytaj dane z dokumentu korporacyjnego polskiej spółki akcyjnej (uchwała, protokół, regulamin, statut, sprawozdanie).
Zwróć WYŁĄCZNIE obiekt JSON:
{"category": jedno z ["statute","rules_management","rules_supervisory","minutes_general","minutes_supervisory","minutes_management",
  "resolution_general","resolution_supervisory","resolution_management","financial_statement","other"],
 "organ": "general" (Walne Zgromadzenie), "supervisory" (Rada Nadzorcza), "management" (Zarząd) albo null,
 "number": numer uchwały lub protokołu (np. "3/2026") albo null,
 "doc_date": "RRRR-MM-DD" (data podjęcia uchwały, posiedzenia albo dokumentu) albo null,
 "subject": przedmiot dokumentu jednym zdaniem po polsku (np. "zatwierdzenie sprawozdania finansowego za 2025") albo null,
 "votes": przy uchwale {"for": liczba, "against": liczba, "abstain": liczba} albo null}
Gdy czegoś nie ma w dokumencie, wpisz null — niczego nie zgaduj. Nie przepisuj imion, nazwisk ani numerów PESEL."""


@dataclass(frozen=True)
class ReadResult:
    status: str  # "read" | "failed"
    fields: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {"version": READER_VERSION, "status": self.status, **self.fields}


def _iso_date(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip()[:10]).isoformat()
    except ValueError:
        return None


def _count(raw: Any) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 10000 else None


def clean_fields(raw: dict[str, Any]) -> dict[str, Any]:
    category = raw.get("category")
    organ = raw.get("organ")
    number = raw.get("number")
    subject = raw.get("subject")
    votes = raw.get("votes")
    clean_votes = None
    if isinstance(votes, dict):
        counted = {k: _count(votes.get(k)) for k in ("for", "against", "abstain")}
        if any(v is not None for v in counted.values()):
            clean_votes = counted
    return {
        "category": category if category in CATEGORIES else None,
        "organ": organ if organ in ORGANS else None,
        "number": str(number).strip()[:_NUMBER_MAX] if isinstance(number, (str, int)) and str(number).strip() else None,
        "doc_date": _iso_date(raw.get("doc_date")),
        "subject": subject.strip()[:_SUBJECT_MAX] if isinstance(subject, str) and subject.strip() else None,
        "votes": clean_votes,
    }


def parse_reply(text: str) -> ReadResult:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return ReadResult("failed")
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return ReadResult("failed")
    if not isinstance(raw, dict):
        return ReadResult("failed")
    fields = clean_fields(raw)
    if not any(fields[k] for k in ("category", "number", "doc_date", "subject")):
        return ReadResult("failed", fields)
    return ReadResult("read", fields)


def _content_block(content: bytes, mime: str) -> dict[str, Any]:
    data = base64.b64encode(content).decode("ascii")
    kind = "document" if mime == "application/pdf" else "image"
    return {"type": kind, "source": {"type": "base64", "media_type": mime, "data": data}}


def _call_model(content: bytes, mime: str) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_for(AIFeatureKey.board_document_read),
        fallback_models=list(fallbacks_for(AIFeatureKey.board_document_read)),
        max_tokens=600,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[
            {
                "role": "user",
                "content": [_content_block(content, mime), {"type": "text", "text": PROMPT}],
            }
        ],
    )
    return text_of(message)


async def read_document(content: bytes, mime: str) -> ReadResult:
    """Wywołanie modelu (wołający deklaruje ``ai_feature``); awaria = ``failed``."""

    if mime not in SUPPORTED_MIME:
        return ReadResult("failed")
    try:
        reply = await run_in_threadpool(_call_model, content, mime)
    except Exception as exc:  # noqa: BLE001 — odczyt to dodatek, dokument zostaje
        logger.warning("board: odczyt dokumentu nieudany (%s)", type(exc).__name__)
        return ReadResult("failed")
    return parse_reply(reply)
