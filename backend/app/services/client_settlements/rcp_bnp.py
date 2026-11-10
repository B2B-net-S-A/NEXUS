"""Odczyt RCP z szablonu BNP („Rozliczenie czasu pracy”), roadmapa E2.1.

Ten sam szablon przychodzi jako PDF (wydruk z podpisem elektronicznym przełożonego)
albo XLSX (gdy podpisu nie ma; wtedy z mailem akceptującym). Czytamy:

* nagłówek: miesiąc z pola „Rozliczenie”, nazwisko, imię, rola, numer zamówienia,
  pole „Check” z szablonu,
* godziny dzienne: wiersz „Godziny w tygodniu” i „SUMA” (31 dni + suma godzin + MD),
* podsumowanie: wiersze „OPIS PRAC” z MD, ID PRODUCT i kodem CMDB; „Godziny
  dodatkowe …” to praca dodatkowa (nadgodziny i weekend), reszta to dni zwykłe,
* koszty delegacji (suma).

Plik spoza szablonu daje ``None`` — wtedy MD wpisują Finanse. Odczyt nigdy nie
blokuje przyjęcia pliku. Podpis: tylko integralność, pokrycie pliku, wystawca,
podpisujący i czas; numeru seryjnego certyfikatu nie czytamy (u części wystawców
zawiera PESEL).
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DAYS = 31
EXTRA_PREFIX = "godziny dodatkowe"
TRAVEL_PREFIX = "wyjazd"
_NUM = r"-?\d+(?:[.,]\d+)?"


@dataclass(frozen=True)
class SummaryRow:
    label: str
    md: Decimal
    product: Optional[str]
    cmdb: Optional[str]

    @property
    def is_extra(self) -> bool:
        return self.label.lower().startswith(EXTRA_PREFIX)

    @property
    def is_travel(self) -> bool:
        return self.label.lower().startswith(TRAVEL_PREFIX)


@dataclass(frozen=True)
class ParsedRcp:
    source: str  # "pdf" | "xlsx"
    month: Optional[str]
    last_name: Optional[str]
    first_name: Optional[str]
    role: Optional[str]
    order_number: Optional[str]
    check_ok: Optional[bool]
    weekday_hours: tuple[Decimal, ...]
    day_totals: tuple[Decimal, ...]
    total_hours: Optional[Decimal]
    declared_md: Optional[Decimal]
    summary: tuple[SummaryRow, ...]
    summary_total: Optional[Decimal]
    travel_total: Optional[Decimal]

    @property
    def md_regular(self) -> Decimal:
        return sum(
            (r.md for r in self.summary if not r.is_extra and not r.is_travel),
            Decimal("0"),
        )

    @property
    def md_extra(self) -> Decimal:
        return sum((r.md for r in self.summary if r.is_extra), Decimal("0"))

    @property
    def weekend_days(self) -> tuple[int, ...]:
        """Dni z godzinami ponad „Godziny w tygodniu” (sobota, niedziela)."""

        if len(self.day_totals) != DAYS or len(self.weekday_hours) != DAYS:
            return ()
        return tuple(
            i + 1 for i in range(DAYS) if self.day_totals[i] - self.weekday_hours[i] > 0
        )


@dataclass(frozen=True)
class SignatureInfo:
    intact: bool
    entire_file: bool
    issuer: Optional[str]
    signer: Optional[str]
    signer_email_domain: Optional[str]
    signed_at: Optional[datetime]


def _dec(raw: Any) -> Optional[Decimal]:
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    text = str(raw).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _month(raw: Any) -> Optional[str]:
    if isinstance(raw, (datetime, date)):
        return f"{raw.year}-{raw.month:02d}"
    match = re.search(r"(\d{4})-(\d{2})-\d{2}", str(raw or ""))
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _clean(raw: Any) -> Optional[str]:
    text = str(raw).strip() if raw is not None else ""
    return text or None


# ── PDF ──────────────────────────────────────────────────────────────────────


def parse_pdf_text(text: str) -> Optional[ParsedRcp]:
    """Tekst strony (``pdfplumber``) → RCP. Wydzielone, żeby testy nie wymagały PDF-a."""

    lines = [line.strip() for line in text.splitlines()]
    if not any(line.startswith("Rozliczenie czasu pracy") for line in lines):
        return None
    header: dict[str, Optional[str]] = {}
    month = None
    check_ok = None
    weekday: tuple[Decimal, ...] = ()
    totals: tuple[Decimal, ...] = ()
    total_hours = declared_md = summary_total = travel_total = None
    summary: list[SummaryRow] = []
    in_summary = in_travel = False

    for line in lines:
        if month is None and (m := re.match(r"^Rozliczenie (\d{4}-\d{2}-\d{2})", line)):
            month = _month(m.group(1))
            continue
        if m := re.match(r"^Check\s+(\S+)", line):
            check_ok = m.group(1).upper() == "OK"
            continue
        for label, key in (
            ("Nazwisko", "last"),
            ("Imię", "first"),
            ("Rola", "role"),
            ("Numer zamówienia", "order"),
        ):
            if line == label or line.startswith(label + " "):
                header.setdefault(key, _clean(line[len(label) :]))
        if line.startswith("Koszty Delegacji"):
            in_travel = True
            continue
        if line.startswith("OPIS PRAC"):
            in_summary, in_travel = True, False
            continue
        if m := re.match(r"^Godziny w tygodniu\s+(.*)$", line):
            values = [_dec(v) for v in re.findall(_NUM, m.group(1))]
            if len(values) >= DAYS + 2:
                weekday = tuple(v or Decimal("0") for v in values[:DAYS])
            continue
        if in_travel and line.startswith("SUMA "):
            numbers = re.findall(_NUM, line)
            travel_total = _dec(numbers[-1]) if numbers else None
            in_travel = False
            continue
        if not totals and line.startswith("SUMA ") and not in_summary:
            values = [_dec(v) for v in re.findall(_NUM, line[5:])]
            if len(values) == DAYS + 2:
                totals = tuple(v or Decimal("0") for v in values[:DAYS])
                total_hours, declared_md = values[DAYS], values[DAYS + 1]
            continue
        if in_summary:
            if m := re.match(r"^SUMA:\s*(" + _NUM + r")", line):
                summary_total = _dec(m.group(1))
                in_summary = False
                continue
            if m := re.match(
                r"^(.*?)\s*(\d+,\d{2,4})(?:\s+(\S+))?(?:\s+(\S+))?\s*$", line
            ):
                md = _dec(m.group(2))
                if md:
                    summary.append(
                        SummaryRow(
                            m.group(1).strip(),
                            md,
                            _clean(m.group(3)),
                            _clean(m.group(4)),
                        )
                    )
    return ParsedRcp(
        source="pdf",
        month=month,
        last_name=header.get("last"),
        first_name=header.get("first"),
        role=header.get("role"),
        order_number=header.get("order"),
        check_ok=check_ok,
        weekday_hours=weekday,
        day_totals=totals,
        total_hours=total_hours,
        declared_md=declared_md,
        summary=tuple(summary),
        summary_total=summary_total,
        travel_total=travel_total,
    )


def parse_pdf(content: bytes) -> Optional[ParsedRcp]:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if not pdf.pages:
                return None
            text = pdf.pages[0].extract_text() or ""
    except Exception as exc:  # noqa: BLE001 — zły PDF to brak odczytu, nie błąd przyjęcia
        logger.info("rcp_bnp: PDF nieczytelny (%s)", type(exc).__name__)
        return None
    return parse_pdf_text(text)


# ── XLSX ─────────────────────────────────────────────────────────────────────


def _rows(content: bytes) -> Optional[list[list[Any]]]:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), data_only=True, read_only=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("rcp_bnp: XLSX nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        sheet = next(
            (ws for ws in workbook.worksheets if ws.sheet_state == "visible"), None
        )
        if sheet is None:
            return None
        return [
            list(row)
            for row in sheet.iter_rows(max_row=120, max_col=45, values_only=True)
        ]
    finally:
        workbook.close()


def _after(row: list[Any], label: str) -> Any:
    """Pierwsza niepusta wartość na prawo od komórki z etykietą."""

    for i, cell in enumerate(row):
        if isinstance(cell, str) and cell.strip() == label:
            return next((v for v in row[i + 1 :] if v not in (None, "")), None)
    return None


def parse_xlsx_rows(rows: Iterable[list[Any]]) -> Optional[ParsedRcp]:
    rows = [list(r) for r in rows]
    if not any(
        any(isinstance(c, str) and "Rozliczenie czasu pracy" in c for c in r)
        for r in rows
    ):
        return None
    header: dict[str, Any] = {}
    weekday: tuple[Decimal, ...] = ()
    totals: tuple[Decimal, ...] = ()
    total_hours = declared_md = summary_total = travel_total = None
    summary: list[SummaryRow] = []
    columns: Optional[dict[str, int]] = None
    in_travel = False

    def label_of(r: list[Any]) -> str:
        return next((c.strip() for c in r if isinstance(c, str) and c.strip()), "")

    def day_values(
        r: list[Any], start: int
    ) -> tuple[tuple[Decimal, ...], Optional[Decimal], Optional[Decimal]]:
        days = tuple(_dec(v) or Decimal("0") for v in r[start : start + DAYS])
        # Suma godzin i MD to dwie ostatnie liczby wiersza (między nimi a dniami
        # szablon ma pustą albo zerową kolumnę).
        tail = [_dec(v) for v in r[start + DAYS :] if _dec(v) is not None]
        if len(tail) < 2:
            return days, None, None
        return days, tail[-2], tail[-1]

    for r in rows:
        label = label_of(r)
        for name, key in (
            ("Rozliczenie", "month"),
            ("Nazwisko", "last"),
            ("Imię", "first"),
            ("Rola", "role"),
            ("Numer zamówienia", "order"),
            ("Check", "check"),
        ):
            if key not in header and any(
                isinstance(c, str) and c.strip() == name for c in r
            ):
                header[key] = _after(r, name)
        if label == "Godziny w tygodniu":
            start = (
                next(
                    i
                    for i, c in enumerate(r)
                    if isinstance(c, str) and c.strip() == label
                )
                + 1
            )
            weekday, _hours, _md = day_values(r, start)
        elif label == "SUMA" and not totals and weekday:
            start = (
                next(
                    i
                    for i, c in enumerate(r)
                    if isinstance(c, str) and c.strip() == "SUMA"
                )
                + 1
            )
            totals, total_hours, declared_md = day_values(r, start)
        elif label == "Koszty Delegacji":
            in_travel = True
        elif in_travel and label == "SUMA":
            numbers = [_dec(v) for v in r if _dec(v) is not None]
            travel_total = numbers[-1] if numbers else None
            in_travel = False
        elif label == "OPIS PRAC":
            columns = {}
            for i, c in enumerate(r):
                text = str(c or "").strip().lower()
                if text.startswith("mds"):
                    columns["md"] = i
                elif text.startswith("id product"):
                    columns["product"] = i
                elif text.startswith("kod aplikacji"):
                    columns["cmdb"] = i
            columns["label"] = next(
                i
                for i, c in enumerate(r)
                if isinstance(c, str) and c.strip() == "OPIS PRAC"
            )
        elif columns is not None and "md" in columns:
            if label.startswith("SUMA"):
                summary_total = (
                    _dec(_after(r, label)) if _after(r, label) is not None else None
                )
                if summary_total is None:
                    numbers = [_dec(v) for v in r if _dec(v) is not None]
                    summary_total = numbers[0] if numbers else None
                columns = None
                continue
            md = _dec(r[columns["md"]]) if columns["md"] < len(r) else None
            product = (
                _clean(r[columns["product"]])
                if "product" in columns and columns["product"] < len(r)
                else None
            )
            text = _clean(r[columns["label"]]) or ""
            # Wiersz z podpowiedzią szablonu („np.: …”) albo bez MD pomijamy; opis
            # przykładowy z wpisanymi danymi to zwykły wiersz pracy.
            if md is None or md == 0 or (product or "").lower().startswith("np."):
                continue
            cmdb = (
                _clean(r[columns["cmdb"]])
                if "cmdb" in columns and columns["cmdb"] < len(r)
                else None
            )
            summary.append(SummaryRow(text, md, product, cmdb))

    check = header.get("check")
    return ParsedRcp(
        source="xlsx",
        month=_month(header.get("month")),
        last_name=_clean(header.get("last")),
        first_name=_clean(header.get("first")),
        role=_clean(header.get("role")),
        order_number=_clean(header.get("order")),
        check_ok=None if check is None else str(check).strip().upper() == "OK",
        weekday_hours=weekday,
        day_totals=totals,
        total_hours=total_hours,
        declared_md=declared_md,
        summary=tuple(summary),
        summary_total=summary_total,
        travel_total=travel_total,
    )


def parse_xlsx(content: bytes) -> Optional[ParsedRcp]:
    rows = _rows(content)
    return parse_xlsx_rows(rows) if rows is not None else None


def parse(content: bytes, mime: str) -> Optional[ParsedRcp]:
    if mime == "application/pdf":
        return parse_pdf(content)
    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return parse_xlsx(content)
    return None


# ── Podpis ───────────────────────────────────────────────────────────────────


def signatures(content: bytes) -> list[SignatureInfo]:
    """Podpisy w PDF: integralność i pokrycie, bez łańcucha zaufania (CA banku
    jest wewnętrzne). Błąd odczytu = brak podpisów, nie wyjątek."""

    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.status import SignatureCoverageLevel
    from pyhanko_certvalidator import ValidationContext

    found: list[SignatureInfo] = []
    # Biblioteka loguje nieudane budowanie ścieżki z imieniem, nazwiskiem i mailem
    # podpisującego. Ścieżki zaufania nie budujemy (CA banku jest wewnętrzne),
    # więc te logi wyciszamy na czas odczytu.
    quiet = [logging.getLogger(name) for name in ("pyhanko", "pyhanko_certvalidator")]
    previous = [log.level for log in quiet]
    for log in quiet:
        log.setLevel(logging.CRITICAL + 1)
    try:
        reader = PdfFileReader(io.BytesIO(content), strict=False)
        for embedded in reader.embedded_signatures:
            status = validate_pdf_signature(
                embedded, ValidationContext(allow_fetching=False)
            )
            cert = embedded.signer_cert
            subject = cert.subject.native if cert is not None else {}
            issuer = cert.issuer.native if cert is not None else {}
            email = subject.get("email_address") if isinstance(subject, dict) else None
            found.append(
                SignatureInfo(
                    intact=bool(status.intact and status.valid),
                    entire_file=status.coverage == SignatureCoverageLevel.ENTIRE_FILE,
                    issuer=issuer.get("common_name")
                    if isinstance(issuer, dict)
                    else None,
                    signer=subject.get("common_name")
                    if isinstance(subject, dict)
                    else None,
                    signer_email_domain=str(email).rsplit("@", 1)[-1].lower()
                    if email
                    else None,
                    signed_at=status.signer_reported_dt,
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("rcp_bnp: podpis nieczytelny (%s)", type(exc).__name__)
        return found
    finally:
        for log, level in zip(quiet, previous):
            log.setLevel(level)
    return found
