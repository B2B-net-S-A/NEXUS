"""Odczyt pól zamówienia z tekstu PDF/DOCX ("Zczytaj dane z dokumentu").

Wywoływane przez ``POST /api/clients/{id}/orders/extract`` w przedłużeniu
(``ExtendOrderDialog``). Nie tworzy Orderu — zwraca tylko odczytane pola, które
front wstawia do formularza (użytkownik zawsze może je poprawić przed zapisem).

Governance (jak ``cv_parser``):
- ``settings.ORDER_EXTRACTION_ENABLED`` — kill-switch bez redeploya.
- ``AIFeatureKey.order_parser`` — master toggle → feature toggle → miesięczny limit
  (bramkowane w endpointcie przez ``ai_quota.check_and_increment``).

Strategia: prymarnie Claude (elastyczne rozpoznawanie struktury i formatów
klientów — nagłówek/tabela/treść, np. BNP ``mc 06-2026_12-2026``). Gdy LLM jest
wyłączony/niedostępny lub zwróci nieparsowalny JSON — regexowy best-effort
fallback (min. okres MM-RRRR + oczywiste daty/kwoty), zawsze oznaczony jako
niepewny. Wzorzec Claude→regex lustrzany do ``cv_parser.parse_cv``.

Wszystkie odczyty są WSPARCIEM, nie źródłem prawdy: przy jakiejkolwiek
niepewności (brak wartości, kilku kandydatów, nietypowy zapis) ustawiamy
``uncertain=True`` — front renderuje wtedy baner „Sprawdź dane!".
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.services.claude_client import call_claude
from app.services.llm_prompts import ORDER_EXTRACTION

logger = logging.getLogger(__name__)

# Model przez env (spójne z candidate_summary/champion_draft/match_justification),
# z fallbackiem na typed setting.
_MODEL = os.environ.get("ORDER_PARSER_MODEL", "") or settings.ORDER_PARSER_MODEL
_MAX_TOKENS = 1200
# Cap długości promptu — zamówienia bywają wielostronicowe (załączniki), a pola
# zwykle są na 1-2 stronach; 16k znaków to bezpieczny sufit kosztu/latencji.
_MAX_DOC_CHARS = 16000
# Poniżej tego progu ufności pole współtworzy „uncertain".
_LOW_CONFIDENCE = 0.6

# Etykiety PL pól — do komunikatów „Sprawdź dane!".
_FIELD_LABELS_PL: dict[str, str] = {
    "title": "tytuł/numer zamówienia",
    "start_date": "data rozpoczęcia",
    "end_date": "data zakończenia",
    "rate_client": "stawka (klient płaci)",
    "total_value": "wartość całkowita",
    "md_total": "liczba MD",
}


@dataclass
class OrderExtraction:
    """Wynik odczytu — pola zmapują 1:1 na formularz przedłużenia."""

    title: Optional[str] = None
    start_date: Optional[str] = None  # ISO "YYYY-MM-DD"
    end_date: Optional[str] = None  # ISO "YYYY-MM-DD"
    rate_client: Optional[Decimal] = None
    rate_unit: Optional[str] = None  # "hour" | "day" | "month" | None
    total_value: Optional[Decimal] = None
    currency: Optional[str] = None
    md_total: Optional[Decimal] = None
    """Liczba MD (osobodni) objęta zamówieniem. Wielkość OPERACYJNA, nie
    finansowa — nie podlega redakcji dla ról bez ``VIEW_FINANCE``, bo to
    właśnie Delivery Lead ma ją wpisać do formularza (reguła z ``CLAUDE.md``:
    „Liczby MD są operacyjne, nie finansowe")."""

    confidence: dict[str, float] = field(default_factory=dict)
    uncertain: bool = True
    uncertain_reasons: list[str] = field(default_factory=list)
    source: str = "none"  # "claude" | "regex" | "none"


# ── Normalizacja pól ────────────────────────────────────────────────────────


def _strip_json_fences(raw: str) -> str:
    """Usuwa markdownowe ```json / ``` z odpowiedzi modelu."""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s)
    return s.strip()


def _clean_str(value: Any, *, max_len: int = 255) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v[:max_len] if v else None


def _clean_currency(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = re.sub(r"[^A-Za-z]", "", value).upper()
    return v[:3] if len(v) == 3 else None


def _clean_unit(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("hour", "hourly", "godzina", "godz", "h", "/h"):
        return "hour"
    if v in ("day", "daily", "md", "mandays", "roboczodzień", "dzień", "d"):
        return "day"
    if v in ("month", "monthly", "mc", "miesiąc", "mies", "/mc"):
        return "month"
    return None


def _normalize_date(value: Any, *, end: bool) -> Optional[str]:
    """Zwraca ISO "YYYY-MM-DD" z ISO / DD.MM.RRRR / "YYYY-MM".

    Dla "YYYY-MM" (precyzja miesięczna) rozwija do pierwszego dnia (start) lub
    ostatniego dnia miesiąca (end) — obsługuje zapisy typu BNP ``mc MM-RRRR``.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", v)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{4})-(\d{1,2})", v)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            day = calendar.monthrange(y, mo)[1] if end else 1
            return f"{y:04d}-{mo:02d}-{day:02d}"

    return None


def _normalize_amount(value: Any) -> Optional[Decimal]:
    """Liczba → Decimal, tolerując PL/US separatory (ostatni separator = dziesiętny)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if not isinstance(value, str):
        return None
    s = re.sub(r"[^\d,.\-]", "", value.strip())
    if not s or s in ("-", ".", ","):
        return None
    last_comma, last_dot = s.rfind(","), s.rfind(".")
    if last_comma == -1 and last_dot == -1:
        cleaned = s
    elif last_comma > last_dot:
        # przecinek jest dziesiętny → kropki to tysiące
        cleaned = s.replace(".", "").replace(",", ".")
    else:
        # kropka jest dziesiętna → przecinki to tysiące
        cleaned = s.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _assess_uncertainty(
    result: OrderExtraction, *, llm_flag: bool
) -> tuple[bool, list[str]]:
    """Reguły niepewności — brak krytycznych pól, niska ufność, nietypowa jednostka."""
    reasons: list[str] = []
    if not result.title:
        reasons.append("Nie znaleziono numeru/tytułu zamówienia")
    if not result.start_date:
        reasons.append("Nie znaleziono daty rozpoczęcia")
    # end_date=None może być świadomie open-ended → nie wymuszamy braku jako błędu.

    for name in (
        "title",
        "start_date",
        "end_date",
        "rate_client",
        "total_value",
        "md_total",
    ):
        val = getattr(result, name)
        conf = result.confidence.get(name)
        if val is not None and conf is not None and conf < _LOW_CONFIDENCE:
            reasons.append(f"Niepewny odczyt: {_FIELD_LABELS_PL.get(name, name)}")

    if result.rate_client is not None and result.rate_unit in ("hour", "day"):
        # Formularz oczekuje stawki miesięcznej (/mc) — stawka godzinowa/dzienna
        # w PDF wymaga ręcznej weryfikacji/przeliczenia.
        reasons.append(
            "Stawka może być w innej jednostce niż miesięczna — sprawdź przeliczenie"
        )

    uncertain = bool(llm_flag) or bool(reasons)
    return uncertain, reasons


def _normalize(data: dict[str, Any], *, source: str) -> OrderExtraction:
    raw_conf = data.get("_confidence")
    conf: dict[str, float] = {}
    if isinstance(raw_conf, dict):
        for k, v in raw_conf.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                conf[str(k)] = max(0.0, min(1.0, float(v)))

    result = OrderExtraction(
        title=_clean_str(data.get("title")),
        start_date=_normalize_date(data.get("start_date"), end=False),
        end_date=_normalize_date(data.get("end_date"), end=True),
        rate_client=_normalize_amount(data.get("rate_client")),
        rate_unit=_clean_unit(data.get("rate_unit")),
        total_value=_normalize_amount(data.get("total_value")),
        currency=_clean_currency(data.get("currency")),
        md_total=_normalize_amount(data.get("md_total")),
        confidence=conf,
        source=source,
    )

    reasons = data.get("uncertain_reasons")
    # Cap ilości (6) ORAZ długości pojedynczego powodu (200) — swobodny tekst
    # od Claude bywa długi i trafia wprost do listy w banerze na FE.
    llm_reasons = (
        [str(r)[:200] for r in reasons if r][:6] if isinstance(reasons, list) else []
    )
    uncertain, extra = _assess_uncertainty(result, llm_flag=bool(data.get("uncertain")))
    result.uncertain = uncertain
    # Łączymy powody modelu z regułowymi, bez duplikatów, zachowując kolejność.
    merged: list[str] = []
    for r in llm_reasons + extra:
        if r and r not in merged:
            merged.append(r)
    result.uncertain_reasons = merged[:8]
    return result


# ── Claude (prymarny) ───────────────────────────────────────────────────────


async def _extract_with_claude(text: str) -> Optional[OrderExtraction]:
    # Typed field w Settings — dostęp wprost (getattr z defaultem cicho
    # re-enable'owałby kill-switch, gdyby pole zniknęło z config.py).
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY
    if not api_key or not settings.ORDER_EXTRACTION_ENABLED:
        return None

    prompt = ORDER_EXTRACTION.render(document_text=text[:_MAX_DOC_CHARS])
    try:
        message = await run_in_threadpool(
            call_claude,
            messages=[{"role": "user", "content": prompt}],
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            api_key=api_key,
            # Claude 5 robi adaptive thinking (effort=high) domyślnie; thinking
            # tokeny liczą się do max_tokens i ucięłyby JSON — wyłączamy.
            thinking={"type": "disabled"},
            system=ORDER_EXTRACTION.system_prompt,
        )
    except Exception as exc:  # noqa: BLE001 — degradujemy do regex fallbacku
        logger.warning("[order_parser] Claude call failed: %r", exc)
        return None

    raw = "".join(
        getattr(b, "text", "") or "" for b in message.content if hasattr(b, "text")
    )
    try:
        data = json.loads(_strip_json_fences(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("[order_parser] JSON parse failed: %r; raw=%.200s", exc, raw)
        return None
    if not isinstance(data, dict):
        return None
    return _normalize(data, source="claude")


# ── Regex fallback (best-effort, zawsze niepewny) ───────────────────────────

_PERIOD_MC_RE = re.compile(
    r"(?:mc|m-?c|miesi[ąa]ce?)\s*[:\-]?\s*(\d{1,2})[-./](\d{4})\s*[_–—-]\s*(\d{1,2})[-./](\d{4})",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{1,2}-\d{1,2})\b")
_EU_DATE_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4})\b")
_AMOUNT_RE = re.compile(
    r"(\d[\d  .]{2,}(?:[.,]\d{1,2})?)\s*(?:pln|zł|zl|eur|usd|€|\$)",
    re.IGNORECASE,
)

# Liczba MD podana wprost. Jednostka MUSI stać po liczbie — sam kontekst
# („zamówienie na 120") jest nieodróżnialny od numeru albo kwoty, a wpisanie
# przypadkowej liczby do budżetu jest gorsze niż zostawienie pola pustym.
_MD_COUNT_RE = re.compile(
    r"(\d[\d\u00a0 ]*(?:[.,]\d{1,2})?)\s*"
    r"(?:md\b|osobodni|osobodnia|osobodzie\u0144|man[- ]?days?|dni\s+roboczych)",
    re.IGNORECASE,
)

# Nordea ma w dokumentach kilka numerów (oferta, projekt, wewnętrzne
# referencje), ale numerem zamówienia jest WYŁĄCZNIE wartość pola
# ``Call Off Agreement number``. Reguła jest deterministyczna i stosowana po
# odpowiedzi LLM, żeby model nie mógł wybrać atrakcyjniejszego numeru z innej
# części dokumentu.
_NORDEA_CALL_OFF_NUMBER_RE = re.compile(
    r"Call\s+Off\s+Agreement\s+(?:number|no\.?)\s*[:#\-]?\s*"
    r"([A-Z0-9][A-Z0-9._/\-]*)",
    re.IGNORECASE,
)


def nordea_call_off_agreement_number(text: str) -> Optional[str]:
    """Zwróć numer z etykiety Nordea, nigdy inny numer z dokumentu."""

    match = _NORDEA_CALL_OFF_NUMBER_RE.search(text or "")
    return match.group(1).strip() if match else None


def enforce_nordea_order_number(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """Nadpisz wynik parsera twardą polityką numeru zamówienia Nordea.

    Brak etykiety czyści ``title`` zamiast pozostawiać numer wybrany przez AI.
    To stan jawnie niepewny do poprawienia przez operatora, ale nigdy ciche
    przypisanie numeru oferty lub projektu jako numeru zamówienia.
    """

    number = nordea_call_off_agreement_number(document_text)
    if number:
        result.title = number
        result.confidence["title"] = 1.0
        result.uncertain_reasons = [
            reason
            for reason in result.uncertain_reasons
            if "numeru/tytułu zamówienia" not in reason
        ]
        return result

    result.title = None
    result.confidence.pop("title", None)
    reason = "Nie znaleziono pola „Call Off Agreement number”"
    if reason not in result.uncertain_reasons:
        result.uncertain_reasons.append(reason)
    result.uncertain = True
    return result


def _extract_with_regex(text: str) -> OrderExtraction:
    result = OrderExtraction(source="regex", uncertain=True)

    # Okres MM-RRRR_MM-RRRR (np. BNP "mc 06-2026_12-2026").
    m = _PERIOD_MC_RE.search(text)
    if m:
        sm, sy, em, ey = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        if 1 <= sm <= 12:
            result.start_date = _normalize_date(f"{sy}-{sm:02d}", end=False)
        if 1 <= em <= 12:
            result.end_date = _normalize_date(f"{ey}-{em:02d}", end=True)

    # Gdy brak okresu MM-RRRR — pierwsze dwie daty jako start/koniec (kolejność
    # w dokumencie zwykle: start, potem koniec). Wyłącznie heurystyka.
    if not result.start_date:
        dates = _ISO_DATE_RE.findall(text) or _EU_DATE_RE.findall(text)
        if len(dates) >= 1:
            result.start_date = _normalize_date(dates[0], end=False)
        if len(dates) >= 2:
            result.end_date = _normalize_date(dates[1], end=True)

    # Pierwsza kwota z walutą jako kandydat na stawkę (bardzo zgrubne).
    a = _AMOUNT_RE.search(text)
    if a:
        result.rate_client = _normalize_amount(a.group(1))

    md = _MD_COUNT_RE.search(text)
    if md:
        result.md_total = _normalize_amount(md.group(1))

    result.uncertain_reasons = ["Odczyt awaryjny (bez AI) — zweryfikuj wszystkie pola"]
    return result


# ── Publiczne API ───────────────────────────────────────────────────────────


async def parse_order_document(text: str) -> OrderExtraction:
    """Odczytaj pola zamówienia z tekstu dokumentu. Nigdy nie rzuca."""
    text = (text or "").strip()
    if not text:
        return OrderExtraction(
            uncertain=True, uncertain_reasons=["Pusty dokument"], source="none"
        )

    result = await _extract_with_claude(text)
    if result is not None:
        return result
    return _extract_with_regex(text)
