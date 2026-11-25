"""Eksport „Przepracowany czas” z Redmine → KCP (roadmapa E6.5). Bez bazy.

Część konsultantów Banku Pocztowego przysyła zamiast KCP sam eksport z Redmine
(kolumny Projekt, Data, Użytkownik, Aktywność, Zagadnienie, Komentarz, Godzin).
Rozliczenia składały z niego KCP ręcznie we wzorze banku; NEXUS składa ją sam
(decyzja Artura z 18.11.2026) w tym samym układzie co arkusz „KARTA”: dzień,
zagadnienia z tego dnia rozdzielone średnikiem, suma godzin dnia.

``to_kcp`` daje ``ParsedKcp`` do tych samych kontroli co karta od konsultanta,
``render_html``/``render_pdf`` — wydruk KCP do paczki dla klienta.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from html import escape
from typing import Any, Iterable, Optional

from app.services.client_settlements import xlsx
from app.services.client_settlements.kcp import (
    MONTHS_PL,
    XLSM,
    XLSX,
    KcpDay,
    ParsedKcp,
    fold,
)
from app.services.client_settlements.kcp import parse as parse_kcp
from app.services.client_settlements.rcp_bnp import _dec

logger = logging.getLogger(__name__)

MAX_ROWS = 2000
MAX_COLS = 12
_COLUMNS = {
    "projekt": "project",
    "data": "date",
    "uzytkownik": "user",
    "aktywnosc": "activity",
    "zagadnienie": "issue",
    "komentarz": "comment",
    "godzin": "hours",
}


@dataclass(frozen=True)
class TimelogEntry:
    day: date
    user: str
    issue: str
    comment: str
    hours: Decimal


@dataclass(frozen=True)
class ParsedTimelog:
    entries: tuple[TimelogEntry, ...]

    @property
    def users(self) -> list[str]:
        return [
            u for u, _ in Counter(e.user for e in self.entries if e.user).most_common()
        ]

    @property
    def month(self) -> Optional[str]:
        counts = Counter(f"{e.day.year}-{e.day.month:02d}" for e in self.entries)
        return counts.most_common(1)[0][0] if counts else None


def _day(cell: Any) -> Optional[date]:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    text = str(cell or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _header(row: list[Any]) -> Optional[dict[str, int]]:
    labels = [fold(c) for c in row]
    columns = {
        _COLUMNS[label]: i for i, label in enumerate(labels) if label in _COLUMNS
    }
    needed = {"date", "user", "issue", "hours"}
    return columns if needed <= columns.keys() else None


def parse_rows(sheets: Iterable[list[list[Any]]]) -> Optional[ParsedTimelog]:
    """Wiersze arkuszy → eksport Redmine. Bez pliku, do testów."""

    entries: list[TimelogEntry] = []
    found = False
    for rows in sheets:
        columns: Optional[dict[str, int]] = None
        for row in rows:
            if columns is None:
                columns = _header(row)
                found = found or columns is not None
                continue

            def cell(key: str, r: list[Any] = row) -> Any:
                i = columns.get(key) if columns else None
                return r[i] if i is not None and i < len(r) else None

            day = _day(cell("date"))
            hours = _dec(cell("hours"))
            if day is None or hours is None or hours <= 0:
                continue
            entries.append(
                TimelogEntry(
                    day=day,
                    user=" ".join(str(cell("user") or "").split()),
                    issue=" ".join(str(cell("issue") or "").split()),
                    comment=" ".join(str(cell("comment") or "").split()),
                    hours=hours,
                )
            )
        if found:
            # Wzór KCP banku ma eksport w arkuszu „import”; dalsze arkusze to formuły.
            break
    return ParsedTimelog(tuple(entries)) if found else None


def _sheets(content: bytes) -> Optional[list[list[list[Any]]]]:
    try:
        workbook = xlsx.load_workbook(content, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        logger.info("redmine: arkusz nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        return [
            [
                list(r)
                for r in ws.iter_rows(
                    max_row=MAX_ROWS, max_col=MAX_COLS, values_only=True
                )
            ]
            for ws in workbook.worksheets
            if ws.sheet_state == "visible"
        ]
    finally:
        workbook.close()


def parse(content: bytes, mime: str) -> Optional[ParsedTimelog]:
    if mime not in (XLSX, XLSM):
        return None
    sheets = _sheets(content)
    return parse_rows(sheets) if sheets is not None else None


def to_kcp(parsed: ParsedTimelog, month: str) -> tuple[ParsedKcp, int]:
    """KCP za miesiąc z wpisów eksportu i liczba wpisów spoza miesiąca."""

    year, mon = (int(x) for x in month.split("-"))
    issues: dict[int, list[str]] = {}
    hours: dict[int, Decimal] = {}
    outside = 0
    # Eksport idzie od najnowszych; karta czyta dzień po dniu od pierwszego.
    for entry in sorted(parsed.entries, key=lambda e: e.day):
        if (entry.day.year, entry.day.month) != (year, mon):
            outside += 1
            continue
        d = entry.day.day
        hours[d] = hours.get(d, Decimal("0")) + entry.hours
        text = entry.issue or entry.comment
        if text and text not in issues.setdefault(d, []):
            issues[d].append(text)
    days = tuple(
        KcpDay(d, "; ".join(issues.get(d, [])), hours[d]) for d in sorted(hours)
    )
    users = parsed.users
    return (
        ParsedKcp(
            person=users[0] if users else None,
            month=month,
            days=days,
            source="redmine",
        ),
        outside,
    )


def _num(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


def render_html(kcp: ParsedKcp) -> str:
    """Wydruk KCP w układzie arkusza „KARTA” wzoru banku."""

    year, mon = (int(x) for x in (kcp.month or "1970-01").split("-"))
    by_day = {d.day: d for d in kcp.days}
    rows = "".join(
        "<tr>"
        f"<td class='n'>{d}</td>"
        f"<td>{escape(by_day[d].description) if d in by_day else ''}</td>"
        f"<td class='n'>{_num(by_day[d].hours) if d in by_day else ''}</td>"
        "</tr>"
        for d in range(1, monthrange(year, mon)[1] + 1)
    )
    worked = kcp.worked_days
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>KCP {year}-{mon:02d}</title><style>"
        "@page{size:A4;margin:14mm 14mm}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:8.5pt;color:#111}"
        "h1{font-size:12pt;text-align:center;margin:0 0 8pt}"
        ".head p{margin:2pt 0;font-size:9.5pt}"
        "table{border-collapse:collapse;width:100%;margin-top:8pt}"
        "th,td{border:0.6px solid #555;padding:2pt 4pt;vertical-align:top}"
        "th{background:#eee;font-weight:600}"
        # Dzień w całości na jednej stronie, jak w Excelu wzoru banku.
        "tr{break-inside:avoid}"
        "td.n,th.n{width:11%;text-align:center}"
        ".sums td{border:none;padding:2pt 4pt}.sums td.v{text-align:right;width:15%}"
        ".sign{margin-top:22pt}"
        "</style></head><body>"
        "<h1>KARTA EWIDENCJI ŚWIADCZENIA USŁUG</h1><div class='head'>"
        f"<p>Imię i Nazwisko: {escape(kcp.person or '')}</p>"
        f"<p>Miesiąc: {MONTHS_PL[mon - 1]}</p><p>Rok: {year}</p></div>"
        "<table><thead><tr><th class='n'>Dzień miesiąca</th><th>Zagadnienia</th>"
        "<th class='n'>Liczba godzin</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<table class='sums'>"
        f"<tr><td>Suma dni przepracowanych</td><td class='v'>{worked},0</td></tr>"
        f"<tr><td>Liczba godzin czas podstawowy</td><td class='v'>{_num(kcp.total_hours)}</td></tr>"
        "<tr><td>Liczba godzin - nadgodziny</td><td class='v'></td></tr>"
        "</table>"
        "<p class='sign'>Podpis dysponenta / dysponentów budżetu:</p>"
        "</body></html>"
    )


def render_pdf(kcp: ParsedKcp) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(kcp)).write_pdf()


def read_card(content: bytes, mime: str, month: str) -> Optional[tuple[ParsedKcp, int]]:
    """KCP z pliku: karta od konsultanta albo złożona z eksportu Redmine.

    Arkusz wzoru banku z pustą „KARTA” (wartości nieprzeliczone przez Excela)
    czytamy z arkusza „import”. Zwraca KCP i liczbę wpisów spoza miesiąca."""

    card = parse_kcp(content, mime)
    if card is not None and (card.total_hours > 0 or card.declared_hours):
        return card, 0
    log = parse(content, mime)
    if log is not None and log.entries:
        return to_kcp(log, month)
    return (card, 0) if card is not None else None
