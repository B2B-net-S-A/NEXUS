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
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
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
_MAX_TARGETED_TOKENS = 2400
# Tryb all-rows zwraca KAŻDĄ osobę z dokumentu z własnym okresem — wiersz jest
# ~2× większy niż w trybie targetowanym, a Velobank potrafi mieć kilkanaście osób.
_MAX_ALL_ROWS_TOKENS = 4000
# Zwykłe formularze zachowują dotychczasowy limit. Przy wskazanym konsultancie
# dokładamy do niego wszystkie okna, w których deterministyczny matcher widzi
# możliwy zapis tej osoby — dzięki temu pozycja z dalszej strony nie znika.
_MAX_DOC_CHARS = 16000
_MAX_TARGETED_DOC_CHARS = 64000
_TARGET_CONTEXT_RADII = (1800, 900, 450, 180)
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
class ConsultantOrderRow:
    """Jedna pozycja konsultanta odczytana z tego samego wiersza/sekcji PDF."""

    consultant_name: str
    rate_client: Optional[Decimal] = None
    rate_unit: Optional[str] = None
    md_total: Optional[Decimal] = None
    uncertain: bool = True
    uncertain_reason: Optional[str] = None
    start_date: Optional[str] = None
    """Okres WŁASNY tego wiersza (ISO), gdy dokument podaje go per osoba —
    Velobank ma kolumny „Zlecenie od / Zlecenie do", Alior zakres w nawiasie pod
    nazwiskiem. ``None`` = wiersz nie ma własnego okresu i obowiązuje okres
    dokumentu (``OrderExtraction.start_date``)."""
    end_date: Optional[str] = None


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

    rate_client_md: Optional[Decimal] = None
    """Oryginalna stawka za 1 MD z dokumentu (polityka Banku Pocztowego).
    Gdy ustawiona, ``rate_client`` niesie już stawkę GODZINOWĄ po przeliczeniu
    (MD ÷ 8, w górę do 2 miejsc) — front pokazuje obie wartości obok siebie.
    Kwota FINANSOWA: podlega tej samej redakcji co ``rate_client``."""

    rate_client_gross: Optional[Decimal] = None
    """Oryginalna kwota BRUTTO z dokumentu (polityka Erste Bank Polska).
    Gdy ustawiona, ``rate_client`` niesie już kwotę NETTO (÷ 1,23) — front
    pokazuje obie wartości obok siebie, żeby operator mógł skonfrontować
    zapisaną stawkę z tym, co widzi w PDF. Kwota FINANSOWA: podlega tej samej
    redakcji co ``rate_client``."""

    consultant_ref: Optional[str] = None
    """Numer ID konsultanta odczytany z dokumentu (polityka BNP).

    W PDF-ach BNP nie ma imienia i nazwiska — jest wyłącznie ten numer. Nexus
    nie przechowuje identyfikatorów nadanych przez klienta, więc pole służy
    WZROKOWEMU potwierdzeniu przez operatora, że dokument dotyczy osoby,
    z której karty uruchomił odczyt. Nie jest kwotą, więc przeżywa redakcję
    finansową."""

    document_truncated: bool = False
    """Tekst dokumentu został UCIĘTY przed wysłaniem do modelu (limit znaków
    w trybie bez osoby docelowej). Do 09.2026 ucięcie było ciche — w trybie
    all-rows oznaczałoby poprawnie wyglądającą listę osób bez ogona tabeli,
    czyli ten sam tryb awarii co cap 10 stron OCR. Flaga istnieje po to, żeby
    automat nigdy nie zapisał zamówienia z takiego odczytu."""

    title_needs_review: bool = False
    """Klientowa polityka numeru zamówienia nie znalazła numeru w dokumencie —
    front pokazuje przy polu numeru komunikat „Sprawdź numer zamówienia".
    Flaga zamiast dopasowywania stringów w ``uncertain_reasons``, bo tamta
    lista jest REDAGOWANA dla ról bez VIEW_FINANCE (a numer nie jest kwotą,
    więc komunikat ma przeżyć redakcję)."""

    confidence: dict[str, float] = field(default_factory=dict)
    consultant_rows: list[ConsultantOrderRow] = field(default_factory=list)
    """Pozycje osobowe z dokumentu. Nie wychodzą do API; serwer używa ich
    wyłącznie do jednoznacznego wyboru stawki i MD wskazanego konsultanta."""

    consultant_rate_matched: bool = False
    consultant_md_matched: bool = False
    """Wewnętrzne dowody, które pola pochodzą z jednoznacznego wiersza osoby.
    Polityki klientowe mogą je przeliczyć, ale nie mogą utworzyć pola, którego
    matcher nie powiązał wcześniej z konsultantem."""

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

    consultant_rows: list[ConsultantOrderRow] = []
    raw_rows = data.get("consultant_rows")
    if isinstance(raw_rows, list):
        for raw_row in raw_rows[:100]:
            if not isinstance(raw_row, dict):
                continue
            consultant_name = _clean_str(raw_row.get("consultant_name"))
            if not consultant_name:
                continue
            row_uncertain_reason = _clean_str(
                raw_row.get("uncertain_reason"), max_len=200
            )
            consultant_rows.append(
                ConsultantOrderRow(
                    consultant_name=consultant_name,
                    rate_client=_normalize_amount(raw_row.get("rate_client")),
                    rate_unit=_clean_unit(raw_row.get("rate_unit")),
                    md_total=_normalize_amount(raw_row.get("md_total")),
                    start_date=_normalize_date(raw_row.get("start_date"), end=False),
                    end_date=_normalize_date(raw_row.get("end_date"), end=True),
                    # Pole jest wymagane przez prompt. Brak traktujemy fail-safe:
                    # starsza/ucięta odpowiedź modelu nie może zapisać kwoty.
                    uncertain=(
                        raw_row.get("uncertain") is not False
                        or row_uncertain_reason is not None
                    ),
                    uncertain_reason=row_uncertain_reason,
                )
            )

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
        consultant_rows=consultant_rows,
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


def _search_name_tokens(value: str) -> list[str]:
    """Tokeny pomocnicze do znalezienia nazwiska w pełnym tekście dokumentu."""

    folded = unicodedata.normalize("NFKD", (value or "").casefold())
    folded = folded.replace("ł", "l")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    raw_words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", folded)
    tokens: list[str] = []
    for raw_word in raw_words:
        parts = [part for part in raw_word.split("-") if part]
        tokens.extend(parts)
        if len(parts) > 1:
            tokens.append("".join(parts))
    return [token for token in tokens if token not in _NAME_TITLES]


def _contains_exact_tokens(required: tuple[str, ...], available: list[str]) -> bool:
    """Multiset containment: każdy wymagany człon musi wystąpić osobno."""

    remaining = list(available)
    for token in required:
        try:
            remaining.remove(token)
        except ValueError:
            return False
    return True


def _token_window_contains_consultant(
    fragment: str,
    consultant_name: str,
    consultant_given_names: Optional[str] = None,
) -> bool:
    """Czy pojedynczy fragment zawiera sąsiadujące tokeny jednej osoby."""

    for fragment_tokens in _name_token_variants(fragment):
        for target_tokens in _name_token_variants(consultant_name):
            width = len(target_tokens)
            if width > 6 or len(fragment_tokens) < width:
                continue
            for start in range(len(fragment_tokens) - width + 1):
                candidate = " ".join(fragment_tokens[start : start + width])
                if (
                    _name_match_score(
                        consultant_name,
                        candidate,
                        consultant_given_names=consultant_given_names,
                    )
                    is not None
                ):
                    return True
    return False


_CROSS_LINE_NAME_CONTEXT = {
    "brutto",
    "consultant",
    "consultantname",
    "day",
    "dzien",
    "dni",
    "eur",
    "godz",
    "godzina",
    "h",
    "hour",
    "konsultant",
    "konsultantka",
    "md",
    "miesiac",
    "month",
    "netto",
    "pln",
    "rate",
    "stawka",
    "usd",
    "zl",
    "zlotego",
    "zloty",
    "zlotych",
}


def _line_looks_like_complete_person(
    line: str,
    consultant_name: str,
    consultant_given_names: Optional[str],
) -> bool:
    """Czy jeden wiersz zawiera już pełne imię i nazwisko targetu."""

    # Jawny łącznik na końcu oznacza zawinięte, niedokończone nazwisko.
    if re.search(r"-\s*$", line.strip()):
        return False
    return _token_window_contains_consultant(
        line, consultant_name, consultant_given_names
    )


def _ordered_name_layout_matches(
    target_tokens: tuple[str, ...],
    candidate_tokens: tuple[str, ...],
    given_tokens: tuple[str, ...],
) -> bool:
    """Cross-line dopuszcza tylko układ ``imiona nazwisko`` lub odwrotny.

    Kolejność członów wewnątrz imion i nazwiska pozostaje stała. Zapobiega to
    sklejaniu naprzemiennych kolumn dwóch osób, ale nadal obsługuje zmianę
    kolejności całych grup oraz jedną bezpieczną literówkę w nazwisku.
    """

    if len(target_tokens) != len(candidate_tokens):
        return False
    if not _contains_exact_tokens(given_tokens, list(candidate_tokens)):
        return False

    surname_tokens = list(target_tokens)
    try:
        for token in given_tokens:
            surname_tokens.remove(token)
    except ValueError:
        return False

    layouts = {
        given_tokens + tuple(surname_tokens),
        tuple(surname_tokens) + given_tokens,
    }
    for layout in layouts:
        distances = [
            _safe_token_distance(expected, actual)
            for expected, actual in zip(layout, candidate_tokens)
        ]
        if any(distance is None for distance in distances):
            continue
        numeric_distances = [distance for distance in distances if distance is not None]
        if (
            any(distance == 0 for distance in numeric_distances)
            and sum(numeric_distances) <= 1
        ):
            return True
    return False


def _cross_line_context_is_name_only(
    fragment: str,
    consultant_name: str,
    consultant_given_names: Optional[str],
) -> bool:
    """W zapisie wielowierszowym nie może być członów drugiej osoby.

    Dopuszczamy wyłącznie tokeny targetu, liczby i proste etykiety stawki. Pełny
    wiersz z innym imieniem/nazwiskiem nie może więc skleić się z sąsiadem.
    """

    lines = [line for line in fragment.splitlines() if line.strip()]
    if any(
        _line_looks_like_complete_person(line, consultant_name, consultant_given_names)
        for line in lines
    ):
        return False

    target_variants = _name_token_variants(consultant_name)
    given_variants = _given_name_token_variants(consultant_name, consultant_given_names)
    for fragment_tokens in _name_token_variants(fragment):
        relevant = tuple(
            token
            for token in fragment_tokens
            if not token.isdigit() and token not in _CROSS_LINE_NAME_CONTEXT
        )
        if any(
            _ordered_name_layout_matches(target_tokens, relevant, given_tokens)
            for target_tokens in target_variants
            for given_tokens in given_variants
        ):
            return True
    return False


def _cross_line_span_is_ambiguous(lines: list[str], *, start: int, width: int) -> bool:
    """Odrzuć nierozstrzygalny układ trzech pojedynczych wierszy.

    ``Prus / Rudzińska / Natalia / Anna`` może oznaczać zarówno target w
    pierwszych trzech liniach, jak i dwie osoby zapisane kolumnami: Prus Natalia
    oraz Rudzińska Anna. Trzy nagie, jednotokenowe linie wymagają więc dowodu
    strukturalnego: sąsiedniego wiersza z etykietą/stawką. Brak sąsiada albo
    kolejny pojedynczy token pozostaje stanem do ręcznej weryfikacji.
    """

    if width != 3:
        return False
    span = lines[start : start + width]
    if not all(len(_search_name_tokens(line)) == 1 for line in span):
        return False

    neighbors = []
    if start > 0:
        neighbors.append(lines[start - 1])
    if start + width < len(lines):
        neighbors.append(lines[start + width])
    for neighbor in neighbors:
        tokens = _search_name_tokens(neighbor)
        # Sama liczba/jednostka nie wystarcza, jeśli ten sam wiersz zawiera
        # też nieznany token osoby (np. ``Anna | 1600 PLN/MD``). Wtedy nadal
        # możemy patrzeć na układ kolumnowy dwóch konsultantów i musimy
        # odmówić automatycznego dopasowania.
        if not tokens or any(
            not (token.isdigit() or token in _CROSS_LINE_NAME_CONTEXT)
            for token in tokens
        ):
            return True
    return not neighbors


def _fragment_contains_consultant(
    fragment: str,
    consultant_name: str,
    consultant_given_names: Optional[str] = None,
) -> bool:
    """Nazwa w jednym wierszu albo bezpiecznie rozbita na maks. trzy wiersze."""

    lines = [line for line in fragment.splitlines() if line.strip()]
    if any(
        _token_window_contains_consultant(line, consultant_name, consultant_given_names)
        for line in lines
    ):
        return True

    for start in range(len(lines)):
        for width in (2, 3):
            span = lines[start : start + width]
            if len(span) != width:
                continue
            if _cross_line_span_is_ambiguous(lines, start=start, width=width):
                continue
            joined = "\n".join(span)
            if _cross_line_context_is_name_only(
                joined, consultant_name, consultant_given_names
            ) and _token_window_contains_consultant(
                joined, consultant_name, consultant_given_names
            ):
                return True
    return False


def _document_mentions_consultant(
    text: str,
    consultant_name: str,
    consultant_given_names: Optional[str] = None,
) -> bool:
    """Deterministyczny dowód, że wskazana osoba rzeczywiście występuje w PDF."""

    lines = text.splitlines(keepends=True)
    return any(
        _fragment_contains_consultant(
            "".join(lines[index : index + 4]),
            consultant_name,
            consultant_given_names,
        )
        for index in range(len(lines))
    )


def _merge_text_ranges(
    ranges: list[tuple[int, int]], *, text_length: int
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        start = max(0, start)
        end = min(text_length, end)
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _join_text_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    return "\n\n[… pominięty fragment dokumentu …]\n\n".join(
        text[start:end].strip() for start, end in ranges if text[start:end].strip()
    )


def _document_text_for_prompt(
    text: str,
    consultant_name: Optional[str],
    consultant_given_names: Optional[str] = None,
) -> tuple[str, bool]:
    """Zwykły cap albo nagłówek + wszystkie okna możliwej osoby.

    Druga wartość mówi, że nawet minimalne okna nie zmieściły się w limicie.
    W takim przypadku wynik osobowy jest później celowo odrzucany do ręcznej
    weryfikacji zamiast wyboru na podstawie niepełnego dokumentu.
    """

    if not consultant_name or len(text) <= _MAX_DOC_CHARS:
        return text[:_MAX_DOC_CHARS], False

    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    hit_ranges: list[tuple[int, int]] = []
    for index in range(len(lines)):
        # Nazwa złożona może zostać rozbita przez ekstraktor PDF nawet na trzy
        # wiersze; czwarty często niesie stawkę/MD tej samej pozycji.
        fragment = "".join(lines[index : index + 4])
        if _fragment_contains_consultant(
            fragment, consultant_name, consultant_given_names
        ):
            hit_ranges.append((offsets[index], offsets[min(index + 4, len(lines))]))

    # Brak nawet tolerancyjnego śladu oznacza bezpieczny wynik bez wiersza:
    # model widzi dotychczasowy początek dokumentu, a matcher wyczyści kwotę/MD.
    if not hit_ranges:
        return text[:_MAX_DOC_CHARS], False

    for radius in _TARGET_CONTEXT_RADII:
        ranges = [(0, _MAX_DOC_CHARS)] + [
            (start - radius, end + radius) for start, end in hit_ranges
        ]
        merged = _merge_text_ranges(ranges, text_length=len(text))
        excerpt = _join_text_ranges(text, merged)
        if len(excerpt) <= _MAX_TARGETED_DOC_CHARS:
            return excerpt, False

    # Zachowaj przynajmniej pełne wiersze wszystkich trafień. Jeżeli nawet one
    # przekraczają limit, oznacz kontekst jako niepełny — żadna stawka nie może
    # wtedy zostać przypisana automatycznie.
    core_ranges = _merge_text_ranges(
        [(0, _MAX_DOC_CHARS), *hit_ranges], text_length=len(text)
    )
    excerpt = _join_text_ranges(text, core_ranges)
    return excerpt[:_MAX_TARGETED_DOC_CHARS], len(excerpt) > _MAX_TARGETED_DOC_CHARS


async def _extract_with_claude(
    text: str,
    *,
    consultant_name: Optional[str] = None,
    consultant_given_names: Optional[str] = None,
) -> Optional[OrderExtraction]:
    """Odczyt dokumentu: bez osoby docelowej (pola dokumentu) albo z nią (wiersz).

    Testy podmieniają tę funkcję fake'iem o DOKŁADNIE tej sygnaturze — dlatego
    tryb all-rows ma osobne wejście (``_extract_all_rows_with_claude``) zamiast
    kolejnego parametru tutaj.
    """
    return await _call_extraction(
        text,
        consultant_name=consultant_name,
        consultant_given_names=consultant_given_names,
        all_rows=False,
    )


async def _extract_all_rows_with_claude(text: str) -> Optional[OrderExtraction]:
    """Odczyt dokumentu z WSZYSTKIMI osobami jako wierszami (ścieżka mailowa).

    Bez osoby docelowej: model dostaje cały dokument (do limitu znaków) i ma
    wypisać każdą osobę z jej własnym okresem, stawką i MD. Pola finansowe na
    poziomie dokumentu są celowo puste — przy N osobach nie znaczą nic.
    """
    return await _call_extraction(
        text, consultant_name=None, consultant_given_names=None, all_rows=True
    )


async def _call_extraction(
    text: str,
    *,
    consultant_name: Optional[str],
    consultant_given_names: Optional[str],
    all_rows: bool,
) -> Optional[OrderExtraction]:
    # Typed field w Settings — dostęp wprost (getattr z defaultem cicho
    # re-enable'owałby kill-switch, gdyby pole zniknęło z config.py).
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY
    if not api_key or not settings.ORDER_EXTRACTION_ENABLED:
        return None

    # W trybie targetowanym przeglądamy cały wielostronicowy tekst. To CPU-bound
    # fuzzy scan, więc podobnie jak ekstrakcja pliku nie może blokować event loopu.
    document_text, target_context_incomplete = await run_in_threadpool(
        _document_text_for_prompt, text, consultant_name, consultant_given_names
    )
    target_for_prompt = (
        json.dumps(consultant_name, ensure_ascii=False)
        if consultant_name
        else "(not provided)"
    )
    prompt = ORDER_EXTRACTION.render(
        document_text=document_text,
        target_consultant=target_for_prompt,
        list_all_consultants="yes" if all_rows else "no",
    )
    if all_rows:
        max_tokens = _MAX_ALL_ROWS_TOKENS
    elif consultant_name:
        max_tokens = _MAX_TARGETED_TOKENS
    else:
        max_tokens = _MAX_TOKENS
    try:
        message = await run_in_threadpool(
            call_claude,
            messages=[{"role": "user", "content": prompt}],
            model=_MODEL,
            max_tokens=max_tokens,
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
    result = _normalize(data, source="claude")
    # Bez osoby docelowej `_document_text_for_prompt` tnie po cichu do
    # _MAX_DOC_CHARS. W trybie all-rows ogon tabeli to kolejne osoby — ucięcie
    # musi być widoczne, żeby bramka automatu odesłała dokument do człowieka.
    result.document_truncated = not consultant_name and len(text) > _MAX_DOC_CHARS
    if target_context_incomplete:
        # Nie wybieramy osoby z niepełnego zbioru potencjalnych trafień.
        result.consultant_rows = []
        result.uncertain = True
        result.uncertain_reasons.append(
            "Dokument zawiera zbyt wiele możliwych pozycji konsultanta — "
            "stawka i liczba MD wymagają ręcznej weryfikacji"
        )
    return result


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
# części dokumentu — a wybierze, bo prompt dopuszcza „a similar document
# reference", a ``Frame Agreement number`` stoi w tych dokumentach wyżej
# i wygląda równie oficjalnie.
#
# Zapis samej etykiety NIE jest stały: dokumenty Nordei mieszają „Call Off",
# „Call-Off" i „Calloff", a po etykiecie bywa „number", „no.", „nr" albo „#".
# Wąskie ``Call\\s+Off … (?:number|no\\.?)`` wypadało na każdym z tych
# wariantów, a wtedy polityka CZYŚCIŁA numer (fail-closed) i operator wpisywał
# go ręcznie — albo, przy niewłączonej bramce klienta, zostawał numer wybrany
# przez model, czyli zwykle właśnie „Frame Agreement".
#
# Etykieta i WARTOŚĆ są rozdzielone świadomie. Jedno wyrażenie „etykieta +
# pierwszy token za nią" brało dowolny token — także zwykłe SŁOWO (drugi
# nagłówek kolumny, „nr", nazwa pola), bo klasa ``[A-Z0-9…]`` z ``IGNORECASE``
# pasuje na litery. Stąd zgłoszenie „do numeru zamówienia wpisują się losowe
# słowa z dokumentu". Teraz wartość musi zawierać CYFRĘ i nie może być datą,
# a okno wyszukiwania jest ucinane na kolejnej etykiecie.
_NORDEA_CALL_OFF_LABEL_RE = re.compile(
    r"Call[\s\-]*Off\s*Agreement\s*(?:number|no\.?|nr\.?|#)?",
    re.IGNORECASE,
)

# Kontrola negatywna: „Frame Agreement number" to numer UMOWY RAMOWEJ, nie
# zamówienia. Nie służy do wyboru numeru — służy do (a) udowodnienia testem, że
# reguła nigdy go nie łapie, także gdy stoi w dokumencie przed właściwą
# etykietą, oraz (b) ucięcia okna wyszukiwania: gdy zaraz za etykietą
# Call-Off zaczyna się KOLEJNA etykieta (układ dwukolumnowy, gdzie nagłówki
# stoją w jednym wierszu, a wartości w następnym), pierwsza liczba za etykietą
# należy już do sąsiedniej kolumny. Wtedy reguła zostawia pole puste, zamiast
# wpisać numer umowy ramowej jako numer zamówienia.
_NORDEA_FRAME_NUMBER_RE = re.compile(
    r"Frame\s*Agreement\s*(?:number|no\.?|nr\.?|#)?\s*[:#\-–—]?\s*"
    r"([A-Z0-9][A-Z0-9._/\-]*)",
    re.IGNORECASE,
)

# Lista jest WĄSKA i to jest celowe: ucięcie okna kończy się pustym numerem
# (polityka jest fail-closed), więc każda nadmiarowa pozycja zamienia poprawny
# odczyt w prośbę o ręczne uzupełnienie. Zostają tylko etykiety, które w tych
# dokumentach naprawdę niosą INNY numer.
_NORDEA_COMPETING_LABEL_RE = re.compile(
    r"(?:Frame|Framework|Master)\s*Agreement|Umowa\s+ramowa|"
    r"Offer\s*(?:number|no\.?)|Project\s*(?:number|no\.?)",
    re.IGNORECASE,
)

# Kandydat na numer: ciąg znaków dopuszczalnych w numerze dokumentu. Sam
# kształt NIE wystarcza — patrz `_is_nordea_number_token`.
_NORDEA_TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9._/\-]*", re.IGNORECASE)

# Data zapisana kropkami/myślnikami przechodzi test „zawiera cyfrę", a numerem
# zamówienia nie jest.
_NORDEA_DATE_TOKEN_RE = re.compile(
    r"\A(?:\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4})\Z"
)

# Ile znaków za etykietą wolno przeszukać. Wartość stoi w tym samym wierszu
# albo w następnym; szersze okno zaczyna wciągać treść niezwiązaną z polem.
_NORDEA_VALUE_WINDOW = 160


def _is_nordea_number_token(token: str) -> bool:
    """Czy token wygląda na numer dokumentu, a nie na słowo albo datę.

    Wymóg CYFRY jest sednem poprawki. Wcześniejsze wyrażenie brało pierwszy
    token po etykiecie, więc w układzie, w którym za nagłówkiem stoi kolejne
    słowo (drugi nagłówek kolumny, „nr", nazwa pola), do pola „numer
    zamówienia" trafiało po prostu SŁOWO z dokumentu — zgłoszony objaw
    „pobiera losowe słowa".
    """

    if not any(character.isdigit() for character in token):
        return False
    return not _NORDEA_DATE_TOKEN_RE.match(token)


def nordea_call_off_agreement_number(text: str) -> Optional[str]:
    """Zwróć numer z etykiety Nordea, nigdy inny numer ani słowo z dokumentu.

    Etykieta nie ma jednego zapisu: dokumenty mieszają „Call Off", „Call-Off"
    i „Calloff", a po niej bywa „number", „no.", „nr", „#" albo nic. Wartość
    stoi raz w tym samym wierszu, raz w następnym. Dlatego reguła jest
    dwuetapowa: najpierw etykieta, potem WYBÓR wartości w oknie za nią —
    a nie jedno wyrażenie, które „bierze, co stoi dalej".
    """

    haystack = text or ""
    for label in _NORDEA_CALL_OFF_LABEL_RE.finditer(haystack):
        window = haystack[label.end() : label.end() + _NORDEA_VALUE_WINDOW]
        competing = _NORDEA_COMPETING_LABEL_RE.search(window)
        if competing is not None:
            window = window[: competing.start()]
        for token in _NORDEA_TOKEN_RE.finditer(window):
            candidate = token.group(0).strip(".-/_")
            if candidate and _is_nordea_number_token(candidate):
                return candidate
    return None


def nordea_frame_agreement_number(text: str) -> Optional[str]:
    """Numer umowy ramowej — WYŁĄCZNIE do kontroli, nigdy jako numer zamówienia."""

    match = _NORDEA_FRAME_NUMBER_RE.search(text or "")
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


# ── Bank Pocztowy: hierarchia numeru + stawka netto za 1 MD → godzinowa ─────
#
# Dwa tickety, jedna polityka deterministyczna (stosowana PO odpowiedzi LLM,
# jak reguła Nordei — model nie może wybrać atrakcyjniejszej interpretacji):
#
#  * numer zamówienia: pole „Numer pisma”, a dopiero gdy go brak — „Zamówienie
#    nr”; bez obu pól numer zostaje PUSTY i front pokazuje przy polu
#    „Sprawdź numer zamówienia” (``title_needs_review``);
#  * stawka z dokumentu jest ZAWSZE kwotą netto za 1 MD (= 8 h) — to stała
#    tego klienta, nie przedmiot niepewności. Mnożnik VAT „1,23” we wzorze
#    (np. „1600*1,23*20”) jest ignorowany: gdy wzór występuje, netto bierzemy
#    wprost z jego pierwszego czynnika, więc model nie może podstawić brutto
#    ani iloczynu. Stawka godzinowa = netto ÷ 8, zaokrąglona W GÓRĘ do 2
#    miejsc; zapisuje się wyłącznie godzinowa, oryginał MD zostaje w
#    ``rate_client_md`` do pokazania obok;
#  * liczba MD/dni ze wzoru (ostatni czynnik) jest POMIJANA — ani nie zasila
#    ``md_total``, ani nie służy do wyliczania okresu (okres wyłącznie z dat
#    „od–do” wskazanych wprost w dokumencie);
#  * komunikaty niepewności są PRZEBUDOWYWANE do białej listy trzech
#    uzasadnionych przypadków: brak numeru, brak dat „od–do”, stawka godzinowa
#    poza widełkami 80–300 zł/h. Generyczne ostrzeżenia (VAT, jednostka,
#    interpretacja liczby MD, niska ufność) są wycinane — ticket żąda, żeby
#    standardowy odczyt BP nie generował szumu. Wyjątek ŚWIADOMY: przy
#    fallbacku regexowym (AI wyłączone/padło) zostaje „Odczyt awaryjny…”,
#    bo przemilczenie, że wszystkie pola są zgadywane, byłoby gorsze niż szum.

_BP_NUMER_PISMA_RE = re.compile(
    r"(?:Numer|Nr\.?)\s+pisma\s*[:#\-]?\s*([A-Z0-9][A-Z0-9._/\-]*)",
    re.IGNORECASE,
)
# „Zamówienie nr …” — tolerujemy zapis bez polskich znaków (ekstrakcja tekstu
# z PDF potrafi zgubić diakrytyki) oraz wariant „numer”.
_BP_ZAMOWIENIE_NR_RE = re.compile(
    r"Zam[óo]wienie\s+(?:nr\.?|numer)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9._/\-]*)",
    re.IGNORECASE,
)
# Wzór z dokumentu BP: „<netto>*1,23*<liczba MD>”. Pierwszy czynnik to kwota
# netto stawki MD; reszta (VAT, liczba MD) jest ignorowana z definicji.
# Separatory tysięcy jawnie escape'owane (spacja + NBSP + wąski NBSP),
# żeby klasa znaków nie wyglądała jak dwie zwykłe spacje (konwencja
# lustrzana do ``_MD_COUNT_RE``).
_BP_NET_FORMULA_RE = re.compile(
    r"(\d[\d\u00a0\u202f ]*(?:[.,]\d{1,2})?)\s*[*x×]\s*1[.,]23\b",
    re.IGNORECASE,
)

_BP_HOURS_PER_MD = Decimal(8)
# Widełki sanity-check stawki godzinowej PO przeliczeniu (zł/h, włącznie).
_BP_HOURLY_MIN = Decimal(80)
_BP_HOURLY_MAX = Decimal(300)
# Fallback regexowy oznacza się tym powodem — jedyny generyczny komunikat,
# który polityka BP przepuszcza (patrz komentarz sekcji).
_REGEX_FALLBACK_REASON_MARKER = "Odczyt awaryjny"


def _bp_labelled_value(pattern: re.Pattern[str], text: str) -> Optional[str]:
    """Pierwsza SENSOWNA wartość pola z etykietą BP (musi nieść cyfrę).

    Guard na cyfrę łapie przypadek pustego pola, po którym ``\\s*`` przeskoczy
    do następnej linii i częściowo dopasuje POCZĄTEK kolejnej etykiety —
    numer zamówienia zawsze niesie cyfrę, etykieta nie. Iterujemy po
    wystąpieniach, bo etykieta bywa powtórzona (nagłówek/stopka strony)
    i dopiero któreś z kolei niesie wartość.
    """
    for m in pattern.finditer(text or ""):
        value = m.group(1).strip().rstrip(".")
        if value and any(ch.isdigit() for ch in value):
            return value
    return None


def bank_pocztowy_order_number(text: str) -> Optional[str]:
    """Numer wg hierarchii BP: „Numer pisma” przed „Zamówienie nr”."""
    return _bp_labelled_value(_BP_NUMER_PISMA_RE, text) or _bp_labelled_value(
        _BP_ZAMOWIENIE_NR_RE, text
    )


def bank_pocztowy_net_md_rate(text: str) -> Optional[Decimal]:
    """Kwota netto stawki MD z wzoru „<netto>*1,23*<MD>”, gdy wzór występuje."""
    m = _BP_NET_FORMULA_RE.search(text or "")
    if not m:
        return None
    return _normalize_amount(m.group(1))


def apply_bank_pocztowy_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """Nadpisz wynik parsera twardą polityką Banku Pocztowego (opis wyżej)."""

    # 1) Numer zamówienia: „Numer pisma” → „Zamówienie nr” → puste + flaga.
    number = bank_pocztowy_order_number(document_text)
    if number:
        result.title = number
        result.confidence["title"] = 1.0
    else:
        result.title = None
        result.confidence.pop("title", None)
        result.title_needs_review = True

    # 2) Stawka: netto za 1 MD → godzinowa (÷ 8, W GÓRĘ do 2 miejsc).
    net_from_formula = bank_pocztowy_net_md_rate(document_text)
    if net_from_formula is not None:
        result.rate_client = net_from_formula
        result.confidence["rate_client"] = 1.0
    rate_warning: Optional[str] = None
    if result.rate_client is not None:
        md_rate = result.rate_client
        hourly = (md_rate / _BP_HOURS_PER_MD).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
        result.rate_client_md = md_rate
        result.rate_client = hourly
        result.rate_unit = "hour"
        if hourly < _BP_HOURLY_MIN or hourly > _BP_HOURLY_MAX:
            rate_warning = (
                f"Nietypowa stawka godzinowa po przeliczeniu: {hourly} zł/h "
                f"(poza zakresem {_BP_HOURLY_MIN}–{_BP_HOURLY_MAX} zł/h) — "
                "możliwy błąd odczytu stawki z dokumentu."
            )
    else:
        # Bez stawki nie ma czego przeliczać, ale jednostka z odpowiedzi LLM
        # nie może wisieć w wyniku: u BP jednostka jest z definicji godzinowa
        # PO przeliczeniu, a „day" przy pustym polu stawki byłby sprzeczny
        # z tą inwariantą (i mylący w metadanych odpowiedzi).
        result.rate_unit = None
        result.confidence.pop("rate_unit", None)

    # 3) Liczba MD ze wzoru — pomijana w całej logice (nie zasila formularza
    #    jednoosobowego, a wpisanie jej do budżetu byłoby zgadywaniem).
    result.md_total = None
    result.confidence.pop("md_total", None)

    # 4) Komunikaty: wyłącznie biała lista (+ marker fallbacku regexowego).
    reasons: list[str] = []
    if result.source == "regex":
        reasons.extend(
            r for r in result.uncertain_reasons if _REGEX_FALLBACK_REASON_MARKER in r
        )
    if result.title is None:
        reasons.append(
            "Nie znaleziono pól „Numer pisma” ani „Zamówienie nr” — "
            "sprawdź numer zamówienia"
        )
    if not result.start_date or not result.end_date:
        reasons.append("Nie znaleziono dat okresu zamówienia (od–do)")
    if rate_warning:
        reasons.append(rate_warning)
    result.uncertain_reasons = reasons
    result.uncertain = bool(reasons)
    return result


# ── Credit Agricole: stawka wyłącznie z pola „Wynagrodzenie za 1MD" ─────────
#
# Zgłoszenie: parser wpisywał do stawki wartość z „Szacowana ilość MD", czyli
# LICZBĘ DNI zamiast kwoty. Te dwa pola stoją w dokumencie obok siebie, a sam
# prompt tego nie rozstrzyga — instrukcja „do not confuse it with the rate
# itself" już tam była i nie wystarczyła, bo model wybiera interpretację, a nie
# stosuje regułę. Dlatego jak u Nordei i Banku Pocztowego: polityka
# DETERMINISTYCZNA po odpowiedzi LLM, oparta na ETYKIETACH, nie na kolejności
# liczb w tekście.
#
# Skutek błędu jest cichy: stawka 20 zł „za MD" (bo tyle było dni) jest liczbą
# poprawną arytmetycznie i przechodzi każdą walidację zakresu — wychodzi
# dopiero na fakturze. Dlatego brak etykiety stawki NIE zostawia wartości
# zgadniętej przez model: czyścimy pole i mówimy o tym wprost. Pusta stawka do
# uzupełnienia jest odwracalna, zła stawka zapisana jako pewna — nie.

# Wartość pola stoi ZA pełną etykietą, a etykieta sama niesie cyfry („1MD",
# „8h”, „23%”) — dlatego wypełniacz między etykietą a liczbą zjada nawiasy
# w całości (`\([^)]*\)`), a nie znak po znaku. Bez tego pierwszą „liczbą po
# etykiecie" byłaby jedynka z „1MD".
_LABEL_FILLER = r"(?:\([^)]*\)|[^\S\n]|[:=\-–—.,]|\n|PLN|z\u0142|netto|brutto|VAT)*?"
# Kwota/liczba: opcjonalne separatory tysięcy (spacja, NBSP, wąski NBSP, kropka)
# + opcjonalna część dziesiętna. Normalizację zapisu robi `_normalize_amount`.
_LABELLED_NUMBER = r"(\d[\d\u00a0\u202f .]*(?:[.,]\d{1,2})?)"


def _labelled_amount(label_pattern: str, text: str) -> Optional[Decimal]:
    """Pierwsza liczba stojąca ZA etykietą (etykieta może nieść własne cyfry).

    Iterujemy po wystąpieniach, bo etykieta bywa powtórzona (nagłówek tabeli na
    kolejnej stronie) i dopiero któreś z kolei niesie wartość.
    """
    pattern = re.compile(
        label_pattern + _LABEL_FILLER + _LABELLED_NUMBER,
        re.IGNORECASE,
    )
    for match in pattern.finditer(text or ""):
        value = _normalize_amount(match.group(1))
        if value is not None:
            return value
    return None


# „Wynagrodzenie za 1MD (8h) (PLN netto)" — tolerujemy spację w „1 MD",
# brak diakrytyków i dowolny ogon nawiasów (ekstrakcja PDF gubi znaki).
_CA_MD_RATE_LABEL = r"Wynagrodzenie\s+za\s+1\s*MD"
# „Szacowana ilość MD" — także „Szacowana ilosc MD" / „Szacunkowa liczba MD".
_CA_MD_COUNT_LABEL = (
    r"Szac(?:owana|unkowa)\s+(?:ilo[\u015b s]c|ilo\u015b\u0107|liczba)\s+MD"
)


# Widełki sanity-check stawki za 1 MD (PLN netto, włącznie). Liczba MD
# omyłkowo wzięta za kwotę (objaw z ticketu) ląduje grubo poniżej dolnej
# granicy, więc pas wychwytuje dokładnie ten błąd.
_CA_MD_RATE_MIN = Decimal(200)
_CA_MD_RATE_MAX = Decimal(5000)


def _credit_agricole_labels_share_a_line(text: str) -> bool:
    """Czy obie etykiety stoją w JEDNYM wierszu (nagłówek tabeli).

    W takim układzie wartości leżą w wierszu NIŻEJ, w kolumnach, a ekstrakcja
    tekstu z PDF gubi wyrównanie — „pierwsza liczba za etykietą” trafia wtedy
    w liczbę porządkową albo w sąsiednią kolumnę. To jest dokładnie ta klasa
    pomyłki, którą ticket zgłasza, więc tu NIE ZGADUJEMY: pola zostają puste
    i operator wpisuje je ręcznie. Zła kwota zapisana jako pewna jest gorsza
    niż puste pole — wychodzi dopiero na fakturze.
    """
    rate_re = re.compile(_CA_MD_RATE_LABEL, re.IGNORECASE)
    count_re = re.compile(_CA_MD_COUNT_LABEL, re.IGNORECASE)
    return any(
        rate_re.search(line) and count_re.search(line)
        for line in (text or "").splitlines()
    )


def credit_agricole_md_rate(text: str) -> Optional[Decimal]:
    """Kwota z pola „Wynagrodzenie za 1MD (8h) (PLN netto)”."""
    if _credit_agricole_labels_share_a_line(text):
        return None
    return _labelled_amount(_CA_MD_RATE_LABEL, text)


def credit_agricole_md_count(text: str) -> Optional[Decimal]:
    """Liczba z pola „Szacowana ilość MD”."""
    if _credit_agricole_labels_share_a_line(text):
        return None
    return _labelled_amount(_CA_MD_COUNT_LABEL, text)


def apply_credit_agricole_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """Stawka WYŁĄCZNIE z pola wynagrodzenia, liczba MD WYŁĄCZNIE z pola ilości.

    Obie wartości są wyprowadzane niezależnie, każda ze swojej etykiety — więc
    zamiana miejscami jest mechanicznie niemożliwa, nawet gdy model ją
    zaproponuje.
    """
    md_rate = credit_agricole_md_rate(document_text)
    md_count = credit_agricole_md_count(document_text)
    # Powody dopisane PRZEZ TĘ POLITYKĘ zbieramy osobno od powodów modelu:
    # tamte mówiły o jego interpretacji stawki i przestały opisywać wynik,
    # te mówią o tym, co polityka właśnie zrobiła, więc muszą przeżyć filtr.
    policy_reasons: list[str] = []

    # Ta sama liczba pod obiema etykietami znaczy, że jedna z nich została
    # odczytana z cudzej kolumny — nie ma jak rozstrzygnąć która, więc stawka
    # (pole, na którym stoją pieniądze) idzie do ręcznego uzupełnienia.
    if md_rate is not None and md_count is not None and md_rate == md_count:
        md_rate = None

    if md_rate is not None:
        result.rate_client = md_rate
        # Kwota jest za 1 MD (= 8 h roboczych) — „day" to jednostka MD
        # w słowniku parsera (`_clean_unit`). Świadomie BEZ przeliczenia na
        # godziny: to była osobna decyzja Banku Pocztowego, a ten ticket prosi
        # wyłącznie o czytanie właściwego pola.
        result.rate_unit = "day"
        result.confidence["rate_client"] = 1.0
        result.confidence["rate_unit"] = 1.0
        if md_rate < _CA_MD_RATE_MIN or md_rate > _CA_MD_RATE_MAX:
            policy_reasons.append(
                f"Nietypowa stawka za 1 MD: {md_rate} zł (poza zakresem "
                f"{_CA_MD_RATE_MIN}–{_CA_MD_RATE_MAX} zł/MD) — sprawdź, czy "
                "nie została odczytana z niewłaściwej kolumny."
            )
    else:
        # Nie zostawiamy stawki wybranej przez model — to jest dokładnie ten
        # kanał, którym wchodziła liczba MD podana jako kwota.
        result.rate_client = None
        result.rate_unit = None
        result.confidence.pop("rate_client", None)
        result.confidence.pop("rate_unit", None)
        policy_reasons.append(
            "Nie znaleziono pola „Wynagrodzenie za 1MD (8h) (PLN netto)” — "
            "wpisz stawkę ręcznie"
        )

    if md_count is not None:
        result.md_total = md_count
        result.confidence["md_total"] = 1.0

    kept = [r for r in result.uncertain_reasons if "stawk" not in r.lower()]
    result.uncertain_reasons = kept + policy_reasons
    result.uncertain = bool(result.uncertain_reasons)
    return result


# ── BNP: zamówienie JEDNOOSOBOWE, konsultant po numerze ID, nie po nazwisku ─
#
# Zgłoszenie: dla BNP odczyt nie dawał ani stawki, ani liczby MD. Przyczyna nie
# leży w modelu, tylko w tożsamości: PDF BNP **nie zawiera imienia i nazwiska**
# konsultanta — niesie wyłącznie jego numer ID. Generyczny matcher
# (``apply_consultant_row_match`` + ``enforce_consultant_policy_safety``) jest
# fail-closed po nazwisku, więc dla takiego dokumentu KAŻDY odczyt kończył się
# wyczyszczeniem stawki i MD. To poprawne zachowanie dla dokumentu
# wielopozycyjnego i błędne dla BNP, bo tam **cały PDF to zamówienie jednej
# osoby** — tej, z której karty operator uruchomił odczyt.
#
# Stąd polityka klientowa (deterministyczna, po odpowiedzi LLM, jak u Nordei
# i Banku Pocztowego), a w endpointcie: dla BNP parser NIE dostaje nazwiska
# i NIE przechodzi przez bramkę bezpieczeństwa matchera.
#
#  * okres: „MM-RRRR do MM-RRRR" → start = PIERWSZY dzień miesiąca
#    początkowego, koniec = OSTATNI dzień miesiąca końcowego (faktyczna liczba
#    dni, ``calendar.monthrange``). Świadomie osobne wyrażenie od
#    ``_PERIOD_MC_RE``: tamto wymaga prefiksu „mc" i nie zna separatora „do";
#  * „Cena netto" → stawka za 1 MD (``rate_unit="day"``);
#  * „Szt." → liczba MD zamówienia;
#  * numer ID konsultanta → ``consultant_ref``, pokazywany operatorowi obok
#    pól. Nie ma go czym dopasować w bazie (Nexus nie przechowuje identyfikatora
#    nadanego przez klienta — ``candidates.external_id`` to ID z Traffita),
#    więc służy WYŁĄCZNIE wzrokowemu potwierdzeniu, że PDF dotyczy tej osoby,
#    której karta jest otwarta. Brak numeru w dokumencie jest sygnalizowany.
#
# Etykieta wygrywa z odczytem modelu, ale jej BRAK nie czyści pola (inaczej niż
# w Credit Agricole): tam kasowanie było odpowiedzią na udokumentowaną pomyłkę
# dwóch sąsiednich etykiet, tu takiego incydentu nie ma, a wyczyszczenie
# zostawiłoby operatora BNP dokładnie z tym, na co się skarży — z pustym
# formularzem. Wartość modelu zostaje więc, ale zawsze z komunikatem „sprawdź".

_BNP_MONTH_RANGE_RE = re.compile(
    # MM-RRRR … MM-RRRR. Lookbehind/lookahead odcinają ŚRODEK pełnej daty:
    # „01.08.2026 do 31.12.2026" nie może zostać odczytane jako 08-2026 →
    # 12-2026, bo przed miesiącem stoi wtedy separator daty. Separatorem
    # okresu bywa słowo „do" albo dowolna kreska; separatorem wewnątrz
    # MM-RRRR bywa „-", „." albo „/" (ekstrakcja z PDF nie jest stała).
    r"(?<![\d.,/\-])(\d{1,2})\s*[-./]\s*(\d{4})"
    r"\s*(?:do\b|[-–—_])\s*"
    r"(\d{1,2})\s*[-./]\s*(\d{4})(?![\d.,/\-])",
    re.IGNORECASE,
)

# „Cena netto" / „Cena jedn. netto" / „Cena jednostkowa netto" — wypełniacz
# między etykietą a liczbą jest ten sam co w Credit Agricole (zjada nawiasy
# w całości, więc „(PLN)" nie podstawi się za wartość, a jakiekolwiek inne
# SŁOWO — np. „Wartość" — dopasowanie przerywa).
_BNP_NET_PRICE_LABEL = r"Cena(?:\s+jedn(?:\.|ostkowa)?)?\s+netto"

# Ilość: najpierw postać „105 szt." — liczba PRZED jednostką, bo tak zapisuje
# ją większość polskich zamówień, a jednostka jest kotwicą MOCNIEJSZĄ niż
# kolejność kolumn. Dwie rzeczy w tym wyrażeniu są obroną przed cichą pomyłką
# i nie wolno ich rozluźnić:
#
#  * ``[^\S\n]*`` zamiast ``\s*`` — zwykłe ``\s*`` przechodzi przez ZNAK
#    NOWEJ LINII, więc kwota z wiersza wyżej („Cena netto: 1 040,00") sklejała
#    się z „Szt." z wiersza niżej i do liczby MD trafiała STAWKA;
#  * brak spacji w klasie cyfr — liczba MD jest z natury mała, więc spacja
#    jako separator tysięcy jest tu wyłącznie sposobem na sklejenie numeru
#    porządkowego z ilością („1 105 szt." → 1105 zamiast 105).
_BNP_QUANTITY_BEFORE_UNIT_RE = re.compile(
    r"(?<![\d.,])(\d{1,4}(?:[.,]\d{1,3})?)[^\S\n]*szt\.?(?!\w)",
    re.IGNORECASE,
)
# Fallback etykietowy WYMAGA jawnego separatora („Szt.: 105"). Bez niego
# „pierwsza liczba za etykietą" w wierszu tabeli trafia w sąsiednią kolumnę.
_BNP_QUANTITY_LABEL = r"(?:Ilo[śs][ćc]|Szt)\.?\s*[:=]"

# Numer ID konsultanta. Sam „Nr" jest w dokumencie wszędzie (numer zamówienia,
# numer pozycji), więc wymagamy słowa opisującego OSOBĘ w bezpośrednim
# sąsiedztwie — inaczej pierwszy z brzegu numer udawałby identyfikator.
_BNP_CONSULTANT_REF_RE = re.compile(
    r"(?:(?:ID|Nr\.?|Numer|Identyfikator)\s+)?"
    r"(?:konsultant|pracownik|specjalist|wykonawc)\w*\s*"
    r"(?:ID|nr\.?|numer|identyfikator)?\s*[:#\-]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9._/\-]{0,31})",
    re.IGNORECASE,
)

# Widełki sanity-check stawki za 1 MD (PLN netto, włącznie) — te same co
# w Credit Agricole. Liczba porządkowa albo ilość omyłkowo wzięta za kwotę
# ląduje grubo poniżej dolnej granicy.
_BNP_MD_RATE_MIN = Decimal(200)
_BNP_MD_RATE_MAX = Decimal(5000)


# Skan wierszowy szuka OBU etykiet w jednej linii, więc wzorce są kompilowane
# raz, na poziomie modułu — funkcja niżej biegnie dwa razy na każdy odczyt PDF
# (z ceny i z ilości).
_BNP_PRICE_LINE_RE = re.compile(_BNP_NET_PRICE_LABEL, re.IGNORECASE)
_BNP_QTY_LINE_RE = re.compile(r"\bszt\.?\b", re.IGNORECASE)


def _bnp_labels_share_a_line(text: str) -> bool:
    """Czy „Cena netto" i „Szt." stoją w JEDNYM wierszu (nagłówek tabeli).

    Ta sama pułapka co w Credit Agricole: w takim układzie wartości leżą
    w wierszu NIŻEJ, w kolumnach, a ekstrakcja tekstu z PDF gubi wyrównanie —
    „pierwsza liczba za etykietą" trafia wtedy w liczbę porządkową albo
    w sąsiednią kolumnę. Tu nie zgadujemy: zostawiamy odczyt modelu (który
    widzi tabelę jako całość) i mówimy operatorowi, żeby sprawdził.
    """
    return any(
        _BNP_PRICE_LINE_RE.search(line) and _BNP_QTY_LINE_RE.search(line)
        for line in (text or "").splitlines()
    )


def bnp_order_period(text: str) -> Optional[tuple[str, str]]:
    """Okres „MM-RRRR do MM-RRRR" → (pierwszy dzień, OSTATNI dzień) w ISO."""
    for match in _BNP_MONTH_RANGE_RE.finditer(text or ""):
        start_month, start_year = int(match.group(1)), match.group(2)
        end_month, end_year = int(match.group(3)), match.group(4)
        if not (1 <= start_month <= 12 and 1 <= end_month <= 12):
            continue
        start = _normalize_date(f"{start_year}-{start_month:02d}", end=False)
        end = _normalize_date(f"{end_year}-{end_month:02d}", end=True)
        if start and end and start <= end:
            return start, end
    return None


def bnp_net_md_rate(text: str) -> Optional[Decimal]:
    """Kwota z pola „Cena netto" — stawka za 1 MD konsultanta."""
    if _bnp_labels_share_a_line(text):
        return None
    return _labelled_amount(_BNP_NET_PRICE_LABEL, text)


def bnp_md_quantity(text: str) -> Optional[Decimal]:
    """Liczba z pola „Szt." — liczba MD objęta zamówieniem.

    Postać „105 szt." działa TAKŻE w wierszu tabeli, bo kotwicą jest sama
    jednostka stojąca tuż za liczbą, a nie kolejność kolumn. Dopiero gdy
    dokument jej nie ma, schodzimy do etykiety — a tam układ tabelaryczny
    znów jest pułapką, więc obowiązuje odmowa (jak przy cenie).
    """
    match = _BNP_QUANTITY_BEFORE_UNIT_RE.search(text or "")
    if match:
        value = _normalize_amount(match.group(1))
        if value is not None:
            return value
    if _bnp_labels_share_a_line(text):
        return None
    return _labelled_amount(_BNP_QUANTITY_LABEL, text)


def bnp_consultant_ref(text: str) -> Optional[str]:
    """Numer ID konsultanta z dokumentu; ``None`` gdy nie ma go w tekście."""
    for match in _BNP_CONSULTANT_REF_RE.finditer(text or ""):
        value = match.group(1).strip().rstrip(".,;:")
        # Identyfikator zawsze niesie cyfrę; sama etykieta („konsultanta:
        # Delivery") nie. Bez tego guardu pierwsze słowo po etykiecie
        # udawałoby numer.
        if value and any(ch.isdigit() for ch in value):
            return value[:64]
    return None


def apply_bnp_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """Nadpisz wynik parsera twardą polityką BNP (opis wyżej).

    Dokument jest z założenia JEDNOOSOBOWY, więc wszystko, co w nim stoi,
    należy do konsultanta, z którego karty uruchomiono odczyt. Polityka
    ustawia dlatego ``consultant_*_matched`` — wołający pomija dla BNP
    bramkę ``enforce_consultant_policy_safety``, ale flagi zostają spójne
    na wypadek, gdyby ktoś kiedyś wpiął tę politykę w tor z matcherem.
    """

    policy_reasons: list[str] = []

    # 1) Okres: MM-RRRR do MM-RRRR → pierwszy/ostatni dzień miesiąca.
    period = bnp_order_period(document_text)
    if period is not None:
        result.start_date, result.end_date = period
        result.confidence["start_date"] = 1.0
        result.confidence["end_date"] = 1.0
    elif not result.start_date or not result.end_date:
        policy_reasons.append(
            "Nie znaleziono okresu zamówienia w formacie MM-RRRR do MM-RRRR — "
            "sprawdź daty"
        )

    # 2) „Cena netto" → stawka za 1 MD. Jednostka jest u BNP stałą klientową,
    #    więc ustawiamy ją także wtedy, gdy kwota pochodzi z odczytu modelu:
    #    „hour"/„month" z LLM opisywałoby inny dokument niż ten.
    md_rate = bnp_net_md_rate(document_text)
    if md_rate is not None:
        result.rate_client = md_rate
        result.confidence["rate_client"] = 1.0
    elif result.rate_client is not None:
        policy_reasons.append(
            "Nie znaleziono pola „Cena netto” — sprawdź stawkę za 1 MD"
        )
    else:
        policy_reasons.append(
            "Nie znaleziono pola „Cena netto” — wpisz stawkę za 1 MD ręcznie"
        )
    if result.rate_client is not None:
        result.rate_unit = "day"
        result.confidence["rate_unit"] = 1.0
        if (
            result.rate_client < _BNP_MD_RATE_MIN
            or result.rate_client > _BNP_MD_RATE_MAX
        ):
            policy_reasons.append(
                f"Nietypowa stawka za 1 MD: {result.rate_client} zł (poza zakresem "
                f"{_BNP_MD_RATE_MIN}–{_BNP_MD_RATE_MAX} zł/MD) — sprawdź, czy nie "
                "została odczytana z niewłaściwej kolumny."
            )
    else:
        result.rate_unit = None
        result.confidence.pop("rate_unit", None)

    # 3) „Szt." → liczba MD zamówienia.
    quantity = bnp_md_quantity(document_text)
    if quantity is not None and quantity > 0:
        result.md_total = quantity
        result.confidence["md_total"] = 1.0
    elif result.md_total is not None:
        policy_reasons.append("Nie znaleziono pola „Szt.” — sprawdź liczbę MD")
    else:
        policy_reasons.append("Nie znaleziono pola „Szt.” — wpisz liczbę MD ręcznie")

    # 4) Tożsamość: numer ID konsultanta zamiast imienia i nazwiska.
    result.consultant_ref = bnp_consultant_ref(document_text)
    if result.consultant_ref is None:
        policy_reasons.append(
            "Nie znaleziono numeru ID konsultanta — potwierdź, że dokument "
            "dotyczy tej osoby"
        )

    # Dokument jednoosobowy: wartości pochodzą z jedynej pozycji, więc nie ma
    # czego dopasowywać po nazwisku.
    result.consultant_rate_matched = result.rate_client is not None
    result.consultant_md_matched = result.md_total is not None

    # Komunikaty modelu o jednostce/przeliczeniu przestały opisywać wynik —
    # jednostka jest tu regułą klientową, nie interpretacją.
    kept = [
        reason
        for reason in result.uncertain_reasons
        if "jednost" not in _fold_policy_text(reason)
        and "przeliczenie" not in _fold_policy_text(reason)
    ]
    result.uncertain_reasons = kept + [
        reason for reason in policy_reasons if reason not in kept
    ]
    result.uncertain = bool(result.uncertain_reasons)
    return result


# ── Orlen: on-site/off-site mogą mieć tę samą stawkę, ale różne pule MD ─────
#
# Wiersze tego samego konsultanta są w PDF Orlen rozbite na on-site/off-site.
# Generyczny matcher świadomie uznaje dwie pozycje z różnym ``md_total`` za
# niejednoznaczne. Dla Orlen liczba MD nie zasila jednak zamówienia: jeżeli
# wszystkie PEWNE wiersze dokładnie tej samej osoby niosą tę samą parę
# (stawka, jednostka), możemy zachować wspólną stawkę i całkowicie pominąć MD.
# Reguła pozostaje osobną polityką klientową — nie rozluźnia matchera innych
# klientów, dla których różne pozycje nadal wymagają ręcznej weryfikacji.


def _clear_rate_for_manual_entry(result: OrderExtraction) -> None:
    """Usuń stawkę i wszystkie jej pochodne przed ręcznym uzupełnieniem."""

    result.rate_client = None
    result.rate_unit = None
    result.rate_client_md = None
    result.rate_client_gross = None
    result.consultant_rate_matched = False
    for key in ("rate_client", "rate_unit", "rate_client_md", "rate_client_gross"):
        result.confidence.pop(key, None)


def _ignore_md_total(result: OrderExtraction) -> None:
    """Wymuś politykę klienta, w której liczba MD z PDF nie jest używana."""

    result.md_total = None
    result.consultant_md_matched = False
    result.confidence.pop("md_total", None)


def _fold_policy_text(value: str) -> str:
    """Tekst do bezpiecznego filtrowania klientowych powodów niepewności."""

    folded = unicodedata.normalize("NFKD", (value or "").casefold())
    folded = folded.replace("ł", "l")
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _is_md_quantity_reason(reason: str) -> bool:
    """Czy powód dotyczy wyłącznie liczby/puli MD, a nie samej stawki."""

    folded = _fold_policy_text(reason)
    return (
        re.search(r"\bmd\b", folded) is not None
        and "stawk" not in folded
        and any(marker in folded for marker in ("liczb", "ilos", "pula", "sum"))
    )


def apply_orlen_order_policy(
    result: OrderExtraction,
    document_text: str,
    *,
    consultant_name: str,
    consultant_given_names: Optional[str] = None,
) -> OrderExtraction:
    """Wybierz wspólną stawkę on/off-site targetowanej osoby, nigdy jej MD.

    ``document_text`` pozostaje w sygnaturze zgodnej z innymi politykami.
    Źródłem kwoty są wyłącznie ``consultant_rows`` już odczytane dla osoby
    wskazanej przez serwer. Różna stawka, jednostka, niepewny wiersz albo
    niejednoznaczna tożsamość zawsze kończą się pustą stawką.
    """

    del document_text
    target = (consultant_name or "").strip()
    _ignore_md_total(result)

    matches = [
        row
        for row in result.consultant_rows
        if _name_match_score(
            target,
            row.consultant_name,
            consultant_given_names=consultant_given_names,
        )
        is not None
    ]
    exact_identity = bool(matches) and all(
        _names_exactly_equivalent(target, row.consultant_name) for row in matches
    )
    common_rates = {
        (row.rate_client, row.rate_unit)
        for row in matches
        if row.rate_client is not None and row.rate_unit is not None
    }
    rows_are_safe = (
        exact_identity
        and all(
            not row.uncertain
            and row.rate_client is not None
            and row.rate_unit is not None
            for row in matches
        )
        and len(common_rates) == 1
    )

    if rows_are_safe:
        rate, unit = next(iter(common_rates))
        result.rate_client = rate
        result.rate_unit = unit
        result.rate_client_md = None
        result.rate_client_gross = None
        result.consultant_rate_matched = True
        result.uncertain_reasons = [
            reason
            for reason in result.uncertain_reasons
            if not (
                "Znaleziono więcej niż jedną pozycję pasującą do konsultanta" in reason
                or _is_md_quantity_reason(reason)
            )
        ]
        result.uncertain = bool(result.uncertain_reasons)
        return result

    _clear_rate_for_manual_entry(result)
    reason = (
        f"Pozycje on-site/off-site konsultanta „{target}” nie mają jednej "
        "pewnej stawki i jednostki — wpisz stawkę przychodową ręcznie"
    )
    if reason not in result.uncertain_reasons:
        result.uncertain_reasons.append(reason)
    result.uncertain = True
    return result


# ── PFRON: konkretny okres, bez liczby MD; stawka brutto → netto ────────────

_DATE_TOKEN_PATTERN = r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4})"
_PFRON_OD_DO_END_RE = re.compile(
    rf"\bod(?:\s+dnia)?\s+{_DATE_TOKEN_PATTERN}\s*"
    rf"(?:do(?:\s+dnia)?|[-–—])\s*(?P<end>{_DATE_TOKEN_PATTERN})",
    re.IGNORECASE,
)
_PFRON_LABELLED_RANGE_END_RE = re.compile(
    rf"(?:termin|okres)\s+realizacji(?:\s+usług)?\s*[:\-–—]?\s*"
    rf"{_DATE_TOKEN_PATTERN}\s*[-–—]\s*(?P<end>{_DATE_TOKEN_PATTERN})",
    re.IGNORECASE,
)
_PFRON_LABELLED_END_RE = re.compile(
    rf"(?:data|termin)\s+zakończenia"
    rf"(?:\s+(?:zamówienia|realizacji(?:\s+usług)?|usług))?"
    rf"\s*[:\-–—]?\s*(?P<end>{_DATE_TOKEN_PATTERN})",
    re.IGNORECASE,
)
_PFRON_SERVICE_TO_END_RE = re.compile(
    rf"(?:termin|okres)\s+realizacji(?:\s+usług)?[^\n]{{0,100}}?"
    rf"\bdo(?:\s+dnia)?\s+(?P<end>{_DATE_TOKEN_PATTERN})",
    re.IGNORECASE,
)


def _pfron_end_date_candidates(document_text: str) -> list[str]:
    """Jawne daty końca okresu usług; pozostałe daty dokumentu są ignorowane."""

    candidates: list[str] = []
    for pattern in (
        _PFRON_OD_DO_END_RE,
        _PFRON_LABELLED_RANGE_END_RE,
        _PFRON_LABELLED_END_RE,
        _PFRON_SERVICE_TO_END_RE,
    ):
        for match in pattern.finditer(document_text or ""):
            normalized = _normalize_date(match.group("end"), end=True)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
    return candidates


def pfron_end_date(document_text: str) -> Optional[str]:
    """Jedyna konkretna data końca usług PFRON albo ``None`` (fail closed)."""

    candidates = _pfron_end_date_candidates(document_text)
    return candidates[0] if len(candidates) == 1 else None


# ── PFRON i Erste: stawka w dokumencie jest BRUTTO ─────────────────────────

_GROSS_RATE_VAT_DIVISOR = Decimal("1.23")
# Alias zachowany dla zgodności kodu/testów odwołujących się do polityki Erste.
_ERSTE_VAT_DIVISOR = _GROSS_RATE_VAT_DIVISOR


def net_rate_from_gross(gross: Decimal) -> Decimal:
    """Brutto → netto przy stałym VAT 23%, zaokrąglone do 2 miejsc."""

    return (gross / _GROSS_RATE_VAT_DIVISOR).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def erste_net_from_gross(gross: Decimal) -> Decimal:
    """Kompatybilny alias historycznej funkcji konwersji Erste."""

    return net_rate_from_gross(gross)


def apply_gross_to_net_rate_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """Przelicz stawkę brutto na netto raz, zachowując oryginalną wartość.

    ``rate_client_gross`` jest jednocześnie wartością do pokazania operatorowi
    i znacznikiem idempotencji. ``total_value`` pozostaje bez zmian: ticket
    dotyczy wyłącznie stawki, a charakter całkowitej kwoty dokumentu może być
    inny i nie wolno go zgadywać.
    """

    del document_text
    if result.rate_client is None:
        return result

    # Dokumenty obu objętych klientów podają tę stawkę zawsze za godzinę.
    # Jest to deterministyczna reguła klientowa, więc nie wolno zachować
    # omyłkowej etykiety MD z modelu ani wyczyścić poprawnej kwoty tylko dlatego,
    # że model pominął jednostkę.
    result.rate_unit = "hour"
    result.confidence["rate_unit"] = 1.0
    if result.rate_client_gross is not None:
        return result

    gross = result.rate_client
    result.rate_client_gross = gross
    result.rate_client = net_rate_from_gross(gross)
    result.uncertain_reasons = [
        reason
        for reason in result.uncertain_reasons
        # Ostrzeżenie „stawka może być w innej jednostce/VAT" przestało opisywać
        # wynik — przeliczenie właśnie się wydarzyło i jest deterministyczne.
        if "vat" not in _fold_policy_text(reason)
        and "przeliczenie" not in _fold_policy_text(reason)
    ]
    result.uncertain = bool(result.uncertain_reasons)
    return result


def apply_pfron_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """Pomiń MD, zapisz jawną datę końca i przelicz stawkę brutto na netto."""

    _ignore_md_total(result)
    candidates = _pfron_end_date_candidates(document_text)
    end_date = candidates[0] if len(candidates) == 1 else None

    result.uncertain_reasons = [
        reason
        for reason in result.uncertain_reasons
        if not _is_md_quantity_reason(reason)
        and "przedluz" not in _fold_policy_text(reason)
        and not (
            end_date is not None and "data zakonczenia" in _fold_policy_text(reason)
        )
    ]
    if end_date is not None:
        result.end_date = end_date
        result.confidence["end_date"] = 1.0
    else:
        result.end_date = None
        result.confidence.pop("end_date", None)
        reason = (
            "Nie znaleziono jednej konkretnej daty zakończenia okresu usług "
            "PFRON — wpisz datę ręcznie"
        )
        if reason not in result.uncertain_reasons:
            result.uncertain_reasons.append(reason)

    result.uncertain = bool(result.uncertain_reasons)
    return apply_gross_to_net_rate_policy(result, document_text)


def apply_erste_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """Kompatybilna polityka Erste delegująca do wspólnej konwersji brutto."""

    return apply_gross_to_net_rate_policy(result, document_text)


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


# ── Dopasowanie konkretnego konsultanta ────────────────────────────────────

_NAME_TITLES = {
    "dr",
    "inz",
    "mgr",
    "mr",
    "mrs",
    "ms",
    "pan",
    "pani",
}


def _name_token_variants(value: str, *, min_tokens: int = 2) -> set[tuple[str, ...]]:
    """Warianty tokenów nazwiska: myślnik jako separator albo bez znaku.

    Dzięki temu ``Prus-Rudzińska Natalia``, ``Natalia Prus Rudzińska`` oraz
    OCR-owe ``Natalia PrusRudzinska`` trafiają do tej samej przestrzeni, bez
    utraty granic pozostałych członów imienia i nazwiska.
    """

    folded = unicodedata.normalize("NFKD", (value or "").casefold())
    folded = folded.replace("ł", "l")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^a-z0-9\-\s]", " ", folded)
    words = [word.strip("-") for word in folded.split() if word.strip("-")]
    if not words:
        return set()

    split_tokens = [
        part
        for word in words
        for part in word.split("-")
        if part and part not in _NAME_TITLES
    ]
    joined_tokens = [
        word.replace("-", "")
        for word in words
        if word.replace("-", "") not in _NAME_TITLES
    ]
    variants = {tuple(split_tokens), tuple(joined_tokens)}
    return {variant for variant in variants if len(variant) >= min_tokens}


def _given_name_token_variants(
    target: str, consultant_given_names: Optional[str]
) -> set[tuple[str, ...]]:
    """Dokładne człony imienia/imion, oddzielone od nazwiska w bazie.

    Produkcyjny endpoint przekazuje pole ``Candidate.name`` osobno. Domyślna
    heurystyka istnieje wyłącznie dla wewnętrznych/starszych wywołań i zakłada
    kanoniczny zapis „imię [drugie imię] nazwisko".
    """

    source = (consultant_given_names or "").strip()
    if not source:
        words = (target or "").split()
        source = " ".join(words[:-1]) if len(words) >= 2 else ""
    return _name_token_variants(source, min_tokens=1)


def _safe_token_distance(expected: str, actual: str) -> Optional[int]:
    """Dokładny token albo jedna wewnętrzna zamiana sąsiednich znaków.

    Substytucja/wstawienie/usunięcie może tworzyć inne realne nazwisko
    (``Nowak``/``Nowik``), więc trafia do ręcznej weryfikacji. Transpozycja
    typu ``Rudzinska``/``Rudzniska`` zachowuje dokładnie ten sam zestaw liter
    i jest znacznie mniej kolizyjną, typową literówką/OCR.
    """

    if expected == actual:
        return 0
    if len(expected) < 5 or len(expected) != len(actual):
        return None
    differences = [
        index
        for index, (left_char, right_char) in enumerate(zip(expected, actual))
        if left_char != right_char
    ]
    if len(differences) != 2 or differences[1] != differences[0] + 1:
        return None
    first, second = differences
    if first == 0 or second == len(expected) - 1:
        return None
    if expected[first] == actual[second] and expected[second] == actual[first]:
        return 1
    return None


def _name_token_multiset_score(
    target_tokens: tuple[str, ...], candidate_tokens: tuple[str, ...]
) -> Optional[float]:
    """Koszt równoważny permutacjom, bez silniowej liczby porównań.

    Pełna zgodność multizbiorów kosztuje zero. Przy literówce po odjęciu
    wspólnych tokenów musi zostać dokładnie jedna para, a jej jedyną dozwoloną
    różnicą jest bezpieczna wewnętrzna transpozycja. Wymagamy też co najmniej
    jednego dokładnego tokenu, tak jak w dotychczasowym matcherze.
    """

    target_counts = Counter(target_tokens)
    candidate_counts = Counter(candidate_tokens)
    common_counts = target_counts & candidate_counts
    exact_matches = sum(common_counts.values())

    if exact_matches == len(target_tokens):
        return 0.0
    if exact_matches == 0:
        return None

    remaining_target = list((target_counts - common_counts).elements())
    remaining_candidate = list((candidate_counts - common_counts).elements())
    if len(remaining_target) != 1 or len(remaining_candidate) != 1:
        return None

    expected = remaining_target[0]
    actual = remaining_candidate[0]
    if _safe_token_distance(expected, actual) != 1:
        return None
    return 1 / max(len(expected), len(actual))


def _name_match_score(
    target: str,
    candidate: str,
    *,
    consultant_given_names: Optional[str] = None,
) -> Optional[float]:
    """Najniższy bezpieczny koszt dopasowania; ``None`` = inna osoba.

    Każdy człon musi znaleźć odpowiednik, wszystkie imiona muszą być identyczne,
    a w całym nazwisku dopuszczamy najwyżej jedną literówkę. Sama zgodność
    imienia nie wystarczy więc do dopasowania zupełnie innego nazwiska.
    """

    given_name_variants = _given_name_token_variants(target, consultant_given_names)
    if not given_name_variants:
        return None

    best: Optional[float] = None
    for target_tokens in _name_token_variants(target):
        for candidate_tokens in _name_token_variants(candidate):
            if len(target_tokens) != len(candidate_tokens) or len(target_tokens) > 6:
                continue
            if not any(
                _contains_exact_tokens(given_tokens, list(candidate_tokens))
                for given_tokens in given_name_variants
            ):
                continue
            score = _name_token_multiset_score(target_tokens, candidate_tokens)
            if score is not None and (best is None or score < best):
                best = score
    return best


def _names_exactly_equivalent(left: str, right: str) -> bool:
    """Równość po kolejności/diakrytykach/myślniku, ale nigdy po literówce."""

    return any(
        sorted(left_tokens) == sorted(right_tokens)
        for left_tokens in _name_token_variants(left)
        for right_tokens in _name_token_variants(right)
    )


def apply_consultant_row_match(
    result: OrderExtraction,
    consultant_name: str,
    *,
    consultant_given_names: Optional[str] = None,
    rate_unit_default: Optional[str] = None,
) -> OrderExtraction:
    """Wybierz dokładnie jeden wiersz tej osoby albo wyczyść stawkę i MD.

    Nie korzystamy z top-levelowej stawki wybranej przez model ani z pierwszej
    kwoty regexowego fallbacku. Bez jednoznacznej pozycji automatyczny zapis
    finansowy jest zabroniony i formularz dostaje jawny stan ręcznej kontroli.
    """

    target = (consultant_name or "").strip()
    result.consultant_rate_matched = False
    result.consultant_md_matched = False
    matches: list[tuple[float, ConsultantOrderRow]] = []
    unique_rows: list[ConsultantOrderRow] = []
    for row in result.consultant_rows:
        if any(
            _names_exactly_equivalent(row.consultant_name, existing.consultant_name)
            and row.rate_client == existing.rate_client
            and row.rate_unit == existing.rate_unit
            and row.md_total == existing.md_total
            and row.uncertain == existing.uncertain
            for existing in unique_rows
        ):
            continue
        unique_rows.append(row)
        score = _name_match_score(
            target,
            row.consultant_name,
            consultant_given_names=consultant_given_names,
        )
        if score is not None:
            matches.append((score, row))

    # Zawsze usuń globalny/losowy wybór przed rozstrzygnięciem konkretnej osoby.
    result.rate_client = None
    result.rate_unit = None
    result.rate_client_md = None
    result.rate_client_gross = None
    result.md_total = None
    for key in (
        "rate_client",
        "rate_unit",
        "rate_client_md",
        "rate_client_gross",
        "md_total",
    ):
        result.confidence.pop(key, None)

    if len(matches) == 1:
        row = matches[0][1]
        result.md_total = row.md_total
        if row.uncertain:
            result.uncertain = True
            reason = row.uncertain_reason or (
                f"Nie można jednoznacznie powiązać stawki i liczby MD z pozycją "
                f"konsultanta „{target}” — wpisz je ręcznie"
            )
            if reason not in result.uncertain_reasons:
                result.uncertain_reasons.append(reason)
            # Nawet MD zostaje puste: flaga mówi, że cały wiersz/sekcja nie jest
            # jednoznacznie związany z osobą.
            result.md_total = None
            return result
        result.consultant_md_matched = row.md_total is not None
        matched_rate_unit = row.rate_unit or rate_unit_default
        if row.rate_client is not None and matched_rate_unit is None:
            result.uncertain = True
            result.uncertain_reasons.append(
                f"W pozycji konsultanta „{target}” nie znaleziono jednostki stawki — "
                "wpisz stawkę przychodową ręcznie"
            )
            return result
        result.rate_client = row.rate_client
        result.rate_unit = matched_rate_unit
        result.consultant_rate_matched = (
            row.rate_client is not None and matched_rate_unit is not None
        )
        if row.rate_client is None:
            result.rate_unit = None
            result.uncertain = True
            result.uncertain_reasons.append(
                f"W pozycji konsultanta „{target}” nie znaleziono stawki przychodowej — wpisz ją ręcznie"
            )
        return result

    result.uncertain = True
    if len(matches) > 1:
        reason = (
            f"Znaleziono więcej niż jedną pozycję pasującą do konsultanta „{target}” — "
            "stawka i liczba MD wymagają ręcznej weryfikacji"
        )
    else:
        reason = (
            f"Nie znaleziono jednoznacznej pozycji konsultanta „{target}” — "
            "stawka i liczba MD wymagają ręcznej weryfikacji"
        )
    if reason not in result.uncertain_reasons:
        result.uncertain_reasons.append(reason)
    return result


def enforce_consultant_policy_safety(result: OrderExtraction) -> OrderExtraction:
    """Po politykach zachowaj tylko pola mające dowód z wiersza konsultanta.

    Poprawne przeliczenie (np. brutto→netto Erste) zostaje zachowane, bo matcher
    potwierdził wejściową stawkę. Po no-match żadna polityka nie może natomiast
    odtworzyć stawki ani MD z globalnej etykiety dokumentu.
    """

    if not result.consultant_rate_matched:
        result.rate_client = None
        result.rate_unit = None
        result.rate_client_md = None
        result.rate_client_gross = None
        for key in (
            "rate_client",
            "rate_unit",
            "rate_client_md",
            "rate_client_gross",
        ):
            result.confidence.pop(key, None)
        result.uncertain = True
        reason = (
            "Stawka przychodowa nie pochodzi z jednoznacznego wiersza "
            "konsultanta — wpisz ją ręcznie"
        )
        if reason not in result.uncertain_reasons:
            result.uncertain_reasons.append(reason)
    if not result.consultant_md_matched:
        result.md_total = None
        result.confidence.pop("md_total", None)
    return result


# ── Publiczne API ───────────────────────────────────────────────────────────


async def parse_order_document(
    text: str,
    *,
    consultant_name: Optional[str] = None,
    consultant_given_names: Optional[str] = None,
    consultant_rate_unit_default: Optional[str] = None,
    all_rows: bool = False,
) -> OrderExtraction:
    """Odczytaj pola zamówienia z tekstu dokumentu. Na treści nigdy nie rzuca.

    ``all_rows=True`` (ścieżka mailowa) zwraca KAŻDĄ osobę z dokumentu
    w ``consultant_rows`` z jej własnym okresem — bez wyboru jednej i bez
    zwijania do pól dokumentu. Jest wykluczające z ``consultant_name``: tryb
    targetowany wybiera jedną osobę, all-rows żadnej; podanie obu to błąd
    programisty, nie danych, więc ``ValueError``.
    """
    if all_rows and consultant_name:
        raise ValueError("all_rows=True wyklucza consultant_name")

    text = (text or "").strip()
    if not text:
        return OrderExtraction(
            uncertain=True, uncertain_reasons=["Pusty dokument"], source="none"
        )

    if all_rows:
        result = await _extract_all_rows_with_claude(text)
    else:
        result = await _extract_with_claude(
            text,
            consultant_name=consultant_name,
            consultant_given_names=consultant_given_names,
        )
    if result is None:
        # Fallback regexowy nie zna wierszy osób — w trybie all-rows zwraca pusty
        # zbiór z `source="regex"`, a to jest dla bramki automatu wystarczający
        # powód, żeby dokument poszedł do człowieka.
        result = _extract_with_regex(text)
    if consultant_name:
        # Model dostaje nazwę w prompcie, więc jego własna lista wierszy nie jest
        # dowodem obecności osoby. Gdy pełny tekst nie zawiera nawet bezpiecznego
        # wariantu nazwy, odrzucamy ewentualnie zahalucynowany wiersz fail-closed.
        target_present = await run_in_threadpool(
            _document_mentions_consultant,
            text,
            consultant_name,
            consultant_given_names,
        )
        if not target_present:
            result.consultant_rows = []
        result = apply_consultant_row_match(
            result,
            consultant_name,
            consultant_given_names=consultant_given_names,
            rate_unit_default=consultant_rate_unit_default,
        )
    return result
