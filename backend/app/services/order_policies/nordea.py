"""Nordea — warstwa dla układu pdfplumber: numer Call-Off, Initial Term, tabela osób.

Ciało polityki (``enforce_nordea_order_number``) zostaje w parserze; ta warstwa
działa PO nim i uzupełnia to, czego tamten ekstraktor w układzie z pipeline'u
nie widzi. W tym układzie trzy komórki nagłówka są PRZEPLECIONE po liniach::

    Nordea contact e-mail address Nordea Request number (if Frame Agreement Call Off
    applicable) number Agreement
    consultant.procurement@nordea.com number
    40517 CW2117535
    277157

„Call Off Agreement" jako ciąg występuje wyłącznie w TYTULE dokumentu (linia 2),
więc etykietowy ekstraktor trafia w okno po tytule i zwraca numer firmy
(``2858394-9``). Deterministyczna kotwica tego układu: wartości stoją w tej
samej kolejności co etykiety — numer Request, numer umowy ramowej (``CW…``),
a w NASTĘPNEJ linii, samotnie, numer Call-Off. Bierzemy więc pierwszą linię
złożoną z samych 5–7 cyfr po linii z tokenem ramowym.

Okres: „Initial Term ⏎ Start date End date ⏎ 2026-02-02 2026-11-30".
Osoby: „Łukasz Urbanowicz IT Operations - Senior Poland - 1 728 Hours 175,00 PLN
302 400,00 PLN". Quantity jest limitem, nie ilością do planu. Stawka jest
zawsze netto za godzinę; nie uzgadniamy jej z Quantity ani Subtotal.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clean_person_name,
    normalize_amount,
    normalize_date,
    set_field,
)
from app.services.order_pdf_parser import (
    _fold_policy_text,
    apply_consultant_row_match,
)

_FRAME_TOKEN_RE = re.compile(r"\b[A-Z]{1,3}\d{5,}\b")
_STANDALONE_NUMBER_RE = re.compile(r"^\s*(\d{5,7})\s*$")
_TERM_HEADER_RE = re.compile(r"Start\s+date\s+End\s+date", re.IGNORECASE)
_TWO_ISO_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})")
_AMT = r"\d[\d\s  ]*,\d{2}"
_ROW_RE = re.compile(
    rf"^(?P<name>\S+[ \t]+\S+(?:-\S+)?)[ \t]+(?P<rest>.*?)[ \t]+(?:(?:\d[\d  ]*|[-–—])[ \t]+)?(?:Hours?|Days?|Months?|MD|h|d)"
    rf"[ \t]+(?P<rate>{_AMT})[ \t]*PLN(?:[ \t]+{_AMT}[ \t]*PLN)?[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
_ORDER_TITLE_RE = re.compile(r"^[ \t]*Call[ -]?Off[ \t]+Agreement[ \t]*$", re.I | re.M)
_SUMMARY_RE = re.compile(
    r"^[ \t]*(?:(?:Order|Document|Envelope|Signing|Call[ -]?Off Agreement)[ \t]+)?"
    r"(?:Summary|Certificate[ \t]+of[ \t]+Completion)[ \t]*:?[ \t]*$",
    re.I | re.M,
)


def order_text_only(text: str) -> str:
    """Odetnij sekcję summary, także z tej samej strony i sprzed zamówienia.

    Kotwicą jest cały nagłówek, nie słowo w opisie usługi. Zachowujemy wszystkie
    strony właściwego zamówienia, w tym kontynuację tabeli. Summary poprzedzające
    zamówienie kończy się dopiero na samodzielnym tytule Call Off Agreement.
    """
    text = (text or "").replace("\r\n", "\n").replace("\f", "\n")
    while match := _SUMMARY_RE.search(text):
        if _ORDER_TITLE_RE.search(text[: match.start()]):
            return text[: match.start()].rstrip()
        order = _ORDER_TITLE_RE.search(text, match.end())
        if order is None:
            return text[: match.start()].rstrip()
        text = text[order.start() :]
    return text


def parser_text(text: str) -> str:
    """Model dostaje osobę i surową stawkę; kolumna limitu nie jest wejściem."""
    text = order_text_only(text)
    text = _ROW_RE.sub(
        lambda m: (
            f"{m.group('name')} {m.group('rest')} "
            f"Rate: {m.group('rate')} PLN/hour netto"
        ),
        text,
    )
    text = re.sub(r"Quantity[ \t]*\(max[ \t]*", "", text, flags=re.I)
    return re.sub(r"\b\d+[ \t]*h/month\)", "", text, flags=re.I)


def _resolved_reason(reason: str) -> bool:
    """Usuń tylko obawy rozstrzygnięte przez trzy sztywne reguły Nordea."""
    folded = _fold_policy_text(reason)
    # Osoba, okres, brak/nieczytelna kwota i różne stawki nadal wymagają kontroli.
    if re.search(
        r"\b(?:dat[ayę]|date\w*|okres\w*|period\w*|nazwisk\w*|osob\w*|name\w*)\b"
        r"|(?:brak|nie znaleziono|nieczyteln\w*|rozne|sprzeczne)\s+(?:kwot\w*|stawk\w*)",
        folded,
    ):
        return False
    return bool(
        re.search(r"\b(?:brutto|netto|gross|net)\b", folded)
        or re.search(r"\b(?:quantity|md_total|subtotal)\b", folded)
        or re.search(r"(?:liczb\w*|ilos\w*|pul\w*)\s+(?:md|godzin\w*)\b", folded)
        or ("stawk" in folded and "jednost" in folded)
        or ("rate" in folded and "unit" in folded)
    )


def _remaining_reasons(reason: str) -> str:
    # Model potrafi połączyć kilka niezależnych powodów średnikami.
    return "; ".join(
        part.strip()
        for part in re.split(r"[;\n]+", reason)
        if part.strip() and not _resolved_reason(part)
    )


def apply_rate_rules(result: OrderExtraction) -> OrderExtraction:
    """Netto/h bez detekcji VAT i bez ilości, także przy przeliczeniu starego planu."""
    if result.uncertain and not result.uncertain_reasons and result.consultant_rows:
        result.uncertain_reasons.append("Odczyt oznaczony przez model jako niepewny")
    for item in [result, *result.consultant_rows]:
        # Stary plan mógł już przejść błędne ÷1,23. Zachowany oryginał jest
        # kwotą z PDF-a, więc przywrócenie go jest dokładne i idempotentne.
        if item.rate_client_gross is not None:
            item.rate_client = item.rate_client_gross
        item.rate_client_gross = None
        item.rate_unit = "hour"
        item.md_total = None
        if isinstance(item, ConsultantOrderRow) and item.uncertain_reason:
            remaining = _remaining_reasons(item.uncertain_reason)
            item.uncertain_reason = remaining or None
            item.uncertain = bool(remaining)
    result.rate_client_md = None
    result.consultant_md_matched = False
    for key in ("md_total", "rate_client_md", "rate_client_gross"):
        result.confidence.pop(key, None)
    result.confidence["rate_unit"] = 1.0
    before = result.uncertain_reasons
    result.uncertain_reasons = [
        remaining for reason in before if (remaining := _remaining_reasons(reason))
    ]
    if before != result.uncertain_reasons:
        result.uncertain = bool(result.uncertain_reasons)
    for row in result.consultant_rows:
        if row.uncertain:
            reason = row.uncertain_reason or "Niepewny odczyt wiersza konsultanta"
            if reason not in result.uncertain_reasons:
                result.uncertain_reasons.append(reason)
            result.uncertain = True
    return result


def call_off_number_interleaved(text: str) -> Optional[str]:
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if _FRAME_TOKEN_RE.search(ln) and re.search(r"\b\d{4,6}\b", ln):
            for nxt in lines[i + 1 : i + 3]:
                m = _STANDALONE_NUMBER_RE.match(nxt)
                if m:
                    return m.group(1)
    return None


def initial_term(text: str) -> tuple[Optional[str], Optional[str]]:
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if _TERM_HEADER_RE.search(ln):
            for nxt in lines[i + 1 : i + 3]:
                m = _TWO_ISO_RE.search(nxt)
                if m:
                    return normalize_date(m.group(1), end=False), normalize_date(
                        m.group(2), end=True
                    )
    return None, None


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    text = order_text_only(text)
    start, end = initial_term(text)
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_RE.finditer(text or ""):
        rate = normalize_amount(m.group("rate"))
        rows.append(
            ConsultantOrderRow(
                consultant_name=clean_person_name(m.group("name")),
                start_date=start,
                end_date=end,
                rate_client=rate,
                rate_unit="hour",
                uncertain=rate is None,
                uncertain_reason="Nie znaleziono stawki" if rate is None else None,
            )
        )
    return rows


def apply_nordea_layout(
    result: OrderExtraction,
    document_text: str,
    *,
    target_consultant: Optional[str] = None,
    target_given_names: Optional[str] = None,
) -> OrderExtraction:
    """Uzupełnij wynik po ``enforce_nordea_order_number`` o układ z pipeline'u.

    Gdy kotwica przeplecionego układu TRAFIA, nadpisuje numer z ekstraktora
    etykietowego nawet wtedy, gdy tamten coś zwrócił: w tym układzie „Call Off
    Agreement" jako ciąg występuje wyłącznie w tytule dokumentu, więc okno po
    etykiecie niesie numer FIRMY (``2858394-9``), a nie zamówienia. Kotwica
    (linia z tokenem ramowym ``CW…`` + samotny numer pod nią) jest sygnaturą
    dokładnie tego układu, w którym ekstraktor etykietowy jest znany jako błędny.
    """
    document_text = order_text_only(document_text)
    result = apply_rate_rules(result)
    number = call_off_number_interleaved(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
        result.uncertain_reasons = [
            r for r in result.uncertain_reasons if "Call Off Agreement number" not in r
        ]
    start, end = initial_term(document_text)
    if start and end:
        set_field(result, "start_date", start)
        set_field(result, "end_date", end)
    rows = extract_rows(document_text)
    if len(rows) == 1 and not rows[0].uncertain and not target_consultant:
        set_field(result, "rate_client", rows[0].rate_client)
        set_field(result, "rate_unit", rows[0].rate_unit)
        result.consultant_rate_matched = True
    if rows and not result.consultant_rows:
        result.consultant_rows = rows
    if target_consultant:
        # Poprzedni matcher mógł odrzucić wiersz przez VAT/Quantity. Po
        # normalizacji nadal musi dopasować WSKAZANĄ osobę, nie pierwszą z PDF-a.
        result = apply_consultant_row_match(
            result,
            target_consultant,
            consultant_given_names=target_given_names,
            rate_unit_default="hour",
        )
    result.uncertain = bool(result.uncertain_reasons)
    return result
