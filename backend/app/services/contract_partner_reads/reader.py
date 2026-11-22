"""Odczyt danych firmy Partnera z podpisanej umowy kontraktu (E5a, 0755).

Decyzja Artura z 22.11.2026: ok. 600 kontraktorów B2B dostanie nową umowę do
podpisu, a na kopii produkcji z 19.11 tylko 117 z 491 aktywnych kontraktów B2B
miało dane firmy Partnera w Generatorze (``render_payload``). Resztę czytamy
z podpisanej umowy w Dokumentach kontraktu, a każdą propozycję potwierdza
człowiek.

Model z rejestru (``AIFeatureKey.contract_partner_read``) dostaje sam plik:
tekst PDF-u, gdy plik go ma, inaczej skan (``build_content`` czytnika stawek
F52, ta sama obsługa PDF-u i zdjęć). Nie dostaje danych z NEXUSA. Każde pole
wraca z dosłownym cytatem; kod sprawdza cyfrę kontrolną NIP-u i REGON-u,
format KRS, e-maila i telefonu, a przy pliku z tekstem — czy cytat naprawdę
stoi w pliku. Czego nie ma w dokumencie albo co nie przechodzi sprawdzenia,
zostaje ``None`` z uwagą dla człowieka; niczego nie uzupełniamy. Awaria modelu
albo śmieci w odpowiedzi = ``ReadResult("failed")`` — kontrakt i Generator
działają jak dotąd.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for
from app.services.contract_rate_documents.reader import (
    MAX_BYTES,
    build_content,
    mime_for,
)
from app.services.hr.payroll_lists.kedu import regon_checksum_valid
from app.services.order_client_identity import nip_checksum_valid

logger = logging.getLogger(__name__)

__all__ = [
    "FIELDS",
    "LABELS",
    "READER_VERSION",
    "ReadResult",
    "clean_fields",
    "clean_value",
    "mime_for",
    "parse_reply",
    "read_document",
]

READER_VERSION = "partner_read:v1"

#: Pola firmy Partnera z ``B2BRenderRequest`` (formularz Generatora), w tej
#: kolejności na ekranie. ``contract_variant`` wynika z ``partner_entity_type``.
FIELDS: tuple[str, ...] = (
    "gender",
    "partner_name",
    "partner_legal_name",
    "partner_entity_type",
    "partner_nip",
    "partner_regon",
    "partner_business_address",
    "partner_correspondence_address",
    "partner_email",
    "partner_phone",
    "partner_krs",
    "partner_seat",
    "partner_registry_court",
    "partner_share_capital",
    "partner_representative_name",
    "partner_representative_function",
    "partner_representation",
)

#: Nazwy pól na ekranie i w odmowach (uwaga kodu nie powtarza nazwy pola).
LABELS: dict[str, str] = {
    "gender": "Forma w umowie",
    "partner_name": "Imię i nazwisko",
    "partner_legal_name": "Firma",
    "partner_entity_type": "Rodzaj podmiotu",
    "partner_nip": "NIP",
    "partner_regon": "REGON",
    "partner_business_address": "Adres działalności / siedziby",
    "partner_correspondence_address": "Adres do korespondencji",
    "partner_email": "E-mail",
    "partner_phone": "Telefon",
    "partner_krs": "KRS",
    "partner_seat": "Siedziba",
    "partner_registry_court": "Sąd rejestrowy",
    "partner_share_capital": "Kapitał zakładowy",
    "partner_representative_name": "Reprezentant",
    "partner_representative_function": "Funkcja reprezentanta",
    "partner_representation": "Reprezentacja",
}

# Limity kolumn i pól ``B2BRenderRequest`` — dłuższa wartość dałaby 422
# w Generatorze albo w masowej wysyłce.
_TEXT_LIMITS: dict[str, int] = {
    "partner_name": 255,
    "partner_legal_name": 255,
    "partner_business_address": 500,
    "partner_correspondence_address": 500,
    "partner_seat": 120,
    "partner_registry_court": 400,
    "partner_share_capital": 60,
    "partner_representative_name": 255,
    "partner_representative_function": 255,
    "partner_representation": 600,
}
_KINDS: frozenset[str] = frozenset({"contract", "annex", "other"})
_READABLE: frozenset[str] = frozenset({"application/pdf", "image/jpeg", "image/png"})
_QUOTE_MAX = 240
_NUMBER_MAX = 64
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_CHARS = re.compile(r"[^\d+()\- ]")

PROMPT = """Dokument z teczki kontraktora: zwykle umowa o współpracę B2B. Strony: spółka B2B.net / B2BNET (zwana „Spółką” albo Zamawiającym) i Partner (konsultant — osoba prowadząca jednoosobową działalność gospodarczą albo spółka).
Odczytaj dane PARTNERA z oznaczenia stron (komparycji), z podpisów i z danych kontaktowych. Danych spółki B2B.net, jej reprezentantów ani klienta NIE wpisuj.
Zwróć WYŁĄCZNIE JSON:
{"document_kind": "contract" | "annex" | "other",
 "agreement_number": numer umowy (np. "1377/2026") albo null,
 "document_date": "RRRR-MM-DD" data zawarcia umowy albo null,
 "fields": {"<pole>": {"value": wartość albo null, "quote": dosłowny fragment dokumentu, z którego pochodzi wartość (do 200 znaków), albo null}}}
Pola (wszystkie klucze w "fields"):
- "gender": "m" albo "k" — z form „Panem”/„Panią”, „zwanym”/„zwaną”, „prowadzącym”/„prowadzącą”;
- "partner_name": imię i nazwisko Partnera (właściciela działalności); przy spółce imię i nazwisko osoby skierowanej do realizacji usług, jeśli umowa ją podaje;
- "partner_legal_name": pełna firma (nazwa) działalności albo spółki Partnera;
- "partner_entity_type": "sole_trader" (jednoosobowa działalność, CEIDG) albo "company" (spółka wpisana do KRS);
- "partner_nip", "partner_regon": numery Partnera;
- "partner_business_address": adres prowadzenia działalności albo siedziby (ulica, numer, kod, miejscowość);
- "partner_correspondence_address": adres do korespondencji, tylko gdy umowa podaje inny niż powyższy;
- "partner_email", "partner_phone": e-mail i telefon Partnera (nie spółki B2B.net);
- tylko przy spółce: "partner_krs", "partner_seat" (miejscowość siedziby), "partner_registry_court" (sąd rejestrowy z wydziałem), "partner_share_capital" (kapitał zakładowy), "partner_representative_name" i "partner_representative_function" (osoba reprezentująca spółkę i jej funkcja), "partner_representation" (fragment po „reprezentowaną przez”).
Wartość przepisz dokładnie tak, jak stoi w dokumencie. Czego nie ma w dokumencie, wpisz null — niczego nie zgaduj i nie uzupełniaj z wiedzy ogólnej. Nie przepisuj stawek, kwot ani numerów rachunków."""


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


def _iso_date(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip()[:10]).isoformat()
    except ValueError:
        return None


def _text(raw: Any, limit: int) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    value = " ".join(raw.split())
    return value[:limit] or None


def _digits(raw: Any) -> str:
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = str(raw)
    return "".join(ch for ch in raw if ch.isdigit()) if isinstance(raw, str) else ""


def clean_value(name: str, raw: Any) -> tuple[Optional[str], Optional[str]]:
    """Wartość pola po sprawdzeniu i uwaga dla człowieka (``None`` = bez uwag).

    Ta sama funkcja czyści propozycję modelu i poprawkę wpisaną przez
    człowieka przy „Zastosuj”, więc oba źródła przechodzą te same reguły.
    """

    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    if name == "gender":
        value = raw.strip().lower() if isinstance(raw, str) else None
        return (value, None) if value in ("m", "k") else (None, None)
    if name == "partner_entity_type":
        value = raw.strip() if isinstance(raw, str) else None
        if value in ("sole_trader", "company"):
            return value, None
        return None, None
    if name == "partner_nip":
        digits = _digits(raw)
        if not nip_checksum_valid(digits):
            return None, "numer nie ma 10 cyfr z poprawną cyfrą kontrolną."
        if digits == "".join(ch for ch in settings.KSEF_CONTEXT_NIP if ch.isdigit()):
            return None, "to NIP spółki B2B.net, nie Partnera."
        return digits, None
    if name == "partner_regon":
        digits = _digits(raw)
        # KRS zapisuje 9-cyfrowy REGON jako 14 cyfr z „00000” na końcu.
        if len(digits) == 14 and digits.endswith("00000"):
            digits = digits[:9]
        if not regon_checksum_valid(digits):
            return (
                None,
                "numer nie ma 9 albo 14 cyfr z poprawną cyfrą kontrolną.",
            )
        return digits, None
    if name == "partner_krs":
        digits = _digits(raw)
        if not digits or len(digits) > 10 or not int(digits):
            return None, "numer nie ma do 10 cyfr."
        return digits.zfill(10), None
    if name == "partner_email":
        value = _text(raw, 255)
        value = value.lower() if value else None
        if not value or not _EMAIL_RE.match(value):
            return None, "adres nie wygląda na poprawny."
        return value, None
    if name == "partner_phone":
        value = _text(raw, 30)
        digits = _digits(value)
        if not value or _PHONE_CHARS.search(value) or not 9 <= len(digits) <= 15:
            return None, "numer nie wygląda na poprawny."
        return value, None
    limit = _TEXT_LIMITS.get(name)
    if limit is None:
        return None, None
    return _text(raw, limit), None


def _squash(text: str) -> str:
    return " ".join(text.replace("­", "").split()).casefold()


def _quote_found(quote: Optional[str], document_text: Optional[str]) -> Optional[bool]:
    """Czy cytat stoi w tekście pliku; ``None`` = skan, nie da się sprawdzić."""

    if quote is None or document_text is None:
        return None
    return _squash(quote) in _squash(document_text)


def clean_fields(
    raw: dict[str, Any], document_text: Optional[str] = None
) -> dict[str, Any]:
    """Odpowiedź modelu w kształcie zapisywanym w ``result``."""

    raw_fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    fields: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, str]] = []
    for name in FIELDS:
        item = raw_fields.get(name)
        if not isinstance(item, dict):
            item = {"value": item, "quote": None}
        value, issue = clean_value(name, item.get("value"))
        quote = _text(item.get("quote"), _QUOTE_MAX)
        fields[name] = {
            "value": value,
            "quote": quote,
            "quote_found": _quote_found(quote, document_text),
        }
        if issue:
            issues.append({"field": name, "message": issue})
        elif value is not None and fields[name]["quote_found"] is False:
            issues.append(
                {
                    "field": name,
                    "message": "cytatu nie ma w tekście pliku — sprawdź wartość w umowie.",
                }
            )
    # Spółka jest w KRS; JDG nie ma numeru KRS. Nic więcej nie wnioskujemy.
    if (
        fields["partner_entity_type"]["value"] is None
        and fields["partner_krs"]["value"]
    ):
        fields["partner_entity_type"]["value"] = "company"
    entity_type = fields["partner_entity_type"]["value"]
    kind = raw.get("document_kind")
    kind = kind if kind in _KINDS else "other"
    if kind != "contract":
        issues.insert(
            0,
            {
                "field": "document_kind",
                "message": "Plik nie wygląda na umowę o współpracę — sprawdź, czy to dane Partnera.",
            },
        )
    return {
        "document_kind": kind,
        "agreement_number": _text(raw.get("agreement_number"), _NUMBER_MAX),
        "document_date": _iso_date(raw.get("document_date")),
        "contract_variant": {"company": "company", "sole_trader": "jdg"}.get(
            entity_type or ""
        ),
        "fields": fields,
        "issues": issues,
    }


def parse_reply(
    text: str, mode: Optional[str] = None, document_text: Optional[str] = None
) -> ReadResult:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return ReadResult("failed", mode=mode)
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return ReadResult("failed", mode=mode)
    if not isinstance(raw, dict):
        return ReadResult("failed", mode=mode)
    return ReadResult("read", clean_fields(raw, document_text), mode=mode)


def _call_model(blocks: list[dict[str, Any]]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_for(AIFeatureKey.contract_partner_read),
        fallback_models=list(fallbacks_for(AIFeatureKey.contract_partner_read)),
        max_tokens=2000,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[
            {"role": "user", "content": [*blocks, {"type": "text", "text": PROMPT}]}
        ],
    )
    return text_of(message)


async def read_document(content: bytes, mime: str, filename: str) -> ReadResult:
    """Wywołanie modelu (wołający deklaruje ``ai_feature``); awaria = ``failed``."""

    if mime not in _READABLE or len(content) > MAX_BYTES:
        return ReadResult("skipped")
    blocks, mode = await run_in_threadpool(build_content, filename, content, mime)
    document_text = blocks[0]["text"] if mode == "text" else None
    try:
        reply = await run_in_threadpool(_call_model, blocks)
    except Exception as exc:  # noqa: BLE001 — odczyt to dodatek, kontrakt działa dalej
        logger.warning(
            "contract_partner_reads: odczyt nieudany (%s)", type(exc).__name__
        )
        return ReadResult("failed", mode=mode)
    return parse_reply(reply, mode, document_text)
