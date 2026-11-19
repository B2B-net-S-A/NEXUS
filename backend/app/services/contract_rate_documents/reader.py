"""Odczyt stawki Partnera z pliku umowy albo aneksu (F52, 0739).

Model z rejestru (``AIFeatureKey.contract_document_rate_read``) dostaje sam plik
z Dokumentów kontraktu: tekst PDF-u, gdy plik go ma, inaczej skan (blok
``document`` albo zdjęcie). Nie dostaje stawek z NEXUSA — różnicę z
harmonogramem liczy kod (``compare.py``). Wynik to propozycja z cytatem; awaria
modelu albo śmieci w odpowiedzi = ``ReadResult("failed")``, kontrakt działa
jak dotąd.

Prompt v2 z odczytu 1164 plików na kopii produkcji 18.11.2026: stawki za
nadgodziny, dyżury i weekendy idą do ``other_rates`` (w v1 model wpisywał je
jako kolejny krok tego samego dnia, np. 141 = 94 × 1,5), a krok aneksu liczy
się od dnia z paragrafu o wejściu w życie, nie od daty sporządzenia.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for

logger = logging.getLogger(__name__)

READER_VERSION = "rate_read:v2"
MAX_BYTES = 30 * 1024 * 1024
#: Plik z warstwą tekstu: co najmniej tyle znaków na stronę, inaczej to skan.
MIN_TEXT_PER_PAGE = 60
MAX_TEXT_CHARS = 120_000
KINDS: frozenset[str] = frozenset({"contract", "annex", "termination", "other"})
UNITS: frozenset[str] = frozenset({"hour", "day", "month"})
_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
_QUOTE_MAX = 600
_LABEL_MAX = 120
_NUMBER_MAX = 64

PROMPT = """Dokument z teczki kontraktora: umowa o współpracę B2B, aneks do niej albo inny dokument (Partner = konsultant, B2BNET/B2B.net = spółka).
Odczytaj wynagrodzenie Partnera. Zwróć WYŁĄCZNIE JSON:
{"kind": "contract" | "annex" | "termination" | "other",
 "agreement_number": numer umowy, której dotyczy (np. "1377/2026") albo null,
 "document_date": "RRRR-MM-DD" data sporządzenia albo null,
 "changes_rate": true/false — czy dokument USTALA albo ZMIENIA stawkę Partnera,
 "rate_steps": [{"rate": liczba, "currency": "PLN"|"EUR"|"USD"|..., "unit": "hour"|"day"|"month",
                 "from": "RRRR-MM-DD" albo null, "to": "RRRR-MM-DD" albo null, "condition": warunek inny niż data albo null}],
 "effective_from": "RRRR-MM-DD" dzień wejścia w życie zmian albo null,
 "other_rates": [{"rate": liczba, "unit": "hour"|"day"|"month", "label": krótki opis}],
 "quote": dosłowny fragment klauzuli o stawce (do 400 znaków) albo null}
"rate_steps" to WYŁĄCZNIE podstawowa stawka Partnera za zwykłą godzinę (albo dzień, miesiąc) pracy i jej zmiany w czasie. Stawki za nadgodziny, dyżury, gotowość, pracę w nocy, weekendy i święta, dodatki procentowe, stawka dla klienta, kary i limity NIE są krokami — wpisz je do "other_rates".
Każdy krok ma własny okres "from"–"to". Jeśli kolejny krok zaczyna się po upływie czasu liczonego od rozpoczęcia (np. "po 3 miesiącach"), a data rozpoczęcia jest w dokumencie, wylicz datę; inaczej from=null i warunek w "condition".
Stawka progresywna = kilka kroków, każdy z własnym okresem. Krok zależny od warunku innego niż data (np. "po okresie próbnym") ma from=null i warunek w "condition".
Aneks zmieniający stawkę: krok od dnia wejścia w życie (§ o wejściu w życie), nie od daty sporządzenia.
Niczego nie zgaduj; czego nie ma, wpisz null."""


@dataclass(frozen=True)
class ReadResult:
    status: str  # "read" | "failed" | "skipped"
    fields: dict[str, Any] = field(default_factory=dict)
    mode: Optional[str] = None  # "text" | "pdf" | "image"

    def as_json(self) -> dict[str, Any]:
        return {
            "version": READER_VERSION,
            "status": self.status,
            "mode": self.mode,
            **self.fields,
        }


def mime_for(filename: str, content_type: Optional[str]) -> Optional[str]:
    """Typ, który model przeczyta, albo ``None`` (DOCX i inne — pomijamy)."""

    by_ext = _MIME_BY_EXT.get(PurePath(filename or "").suffix.lower())
    if by_ext:
        return by_ext
    return content_type if content_type in _MIME_BY_EXT.values() else None


def _iso_date(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip()[:10]).isoformat()
    except ValueError:
        return None


def _rate(raw: Any) -> Optional[float]:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        raw = raw.replace(" ", "").replace(",", ".")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0 or value >= 1_000_000:
        return None
    return float(value.quantize(Decimal("0.01")))


def _text(raw: Any, limit: int) -> Optional[str]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()[:limit]


def _currency(raw: Any) -> str:
    if isinstance(raw, str) and len(raw.strip()) == 3 and raw.strip().isalpha():
        return raw.strip().upper()
    return "PLN"


def _steps(raw: Any) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        rate = _rate(item.get("rate"))
        unit = item.get("unit")
        if rate is None or unit not in UNITS:
            continue
        steps.append(
            {
                "rate": rate,
                "currency": _currency(item.get("currency")),
                "unit": unit,
                "from": _iso_date(item.get("from")),
                "to": _iso_date(item.get("to")),
                "condition": _text(item.get("condition"), _LABEL_MAX),
            }
        )
    return steps[:12]


def _other_rates(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        rate = _rate(item.get("rate"))
        if rate is None:
            continue
        out.append(
            {
                "rate": rate,
                "unit": item.get("unit") if item.get("unit") in UNITS else None,
                "label": _text(item.get("label"), _LABEL_MAX),
            }
        )
    return out[:12]


def clean_fields(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw.get("kind")
    steps = _steps(raw.get("rate_steps"))
    return {
        "kind": kind if kind in KINDS else "other",
        "agreement_number": _text(raw.get("agreement_number"), _NUMBER_MAX),
        "document_date": _iso_date(raw.get("document_date")),
        "changes_rate": bool(raw.get("changes_rate")) and bool(steps),
        "rate_steps": steps,
        "effective_from": _iso_date(raw.get("effective_from")),
        "other_rates": _other_rates(raw.get("other_rates")),
        "quote": _text(raw.get("quote"), _QUOTE_MAX),
    }


def parse_reply(text: str, mode: Optional[str] = None) -> ReadResult:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return ReadResult("failed", mode=mode)
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return ReadResult("failed", mode=mode)
    if not isinstance(raw, dict):
        return ReadResult("failed", mode=mode)
    return ReadResult("read", clean_fields(raw), mode=mode)


def pdf_pages_text(content: bytes) -> list[str]:
    """Tekst stron PDF-u; pusta lista, gdy pliku nie da się otworzyć."""

    import pdfplumber  # type: ignore[import-untyped]

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return [(page.extract_text() or "") for page in pdf.pages]
    except Exception:  # noqa: BLE001 — uszkodzony PDF czyta model jako skan
        return []


def build_content(
    filename: str, content: bytes, mime: str
) -> tuple[list[dict[str, Any]], str]:
    """Bloki wiadomości dla modelu i tryb odczytu (tekst, PDF albo zdjęcie)."""

    name = f"Nazwa pliku: {filename}"
    if mime == "application/pdf":
        pages = pdf_pages_text(content)
        chars = sum(len(page) for page in pages)
        if pages and chars >= MIN_TEXT_PER_PAGE * len(pages):
            body = "\n\n".join(
                f"[strona {i + 1}]\n{page}" for i, page in enumerate(pages)
            )[:MAX_TEXT_CHARS]
            return [
                {"type": "text", "text": f"{name}\n<dokument>\n{body}\n</dokument>"}
            ], "text"
        kind, mode = "document", "pdf"
    else:
        kind, mode = "image", "image"
    data = base64.b64encode(content).decode("ascii")
    block = {
        "type": kind,
        "source": {"type": "base64", "media_type": mime, "data": data},
    }
    return [block, {"type": "text", "text": name}], mode


def _call_model(blocks: list[dict[str, Any]]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_for(AIFeatureKey.contract_document_rate_read),
        fallback_models=list(fallbacks_for(AIFeatureKey.contract_document_rate_read)),
        max_tokens=1200,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[
            {"role": "user", "content": [*blocks, {"type": "text", "text": PROMPT}]}
        ],
    )
    return text_of(message)


async def read_document(content: bytes, mime: str, filename: str) -> ReadResult:
    """Wywołanie modelu (wołający deklaruje ``ai_feature``); awaria = ``failed``."""

    if mime not in _MIME_BY_EXT.values() or len(content) > MAX_BYTES:
        return ReadResult("skipped")
    blocks, mode = await run_in_threadpool(build_content, filename, content, mime)
    try:
        reply = await run_in_threadpool(_call_model, blocks)
    except Exception as exc:  # noqa: BLE001 — odczyt to dodatek, kontrakt działa dalej
        logger.warning(
            "contract_rate_documents: odczyt nieudany (%s)", type(exc).__name__
        )
        return ReadResult("failed", mode=mode)
    return parse_reply(reply, mode)
