"""KEŚU klienta rozliczanego przez Jirę (roadmapa E6.3, Alior). Bez bazy.

Obieg: konsultant prowadzi Kartę Ewidencji Świadczenia Usług (KEŚU) w Jirze
klienta, opiekun akceptuje, a automat Jiry wysyła mail z KEŚU do naszego
koordynatora, który przekazuje go na rozliczenia@. Temat podaje osobę
i miesiąc, treść opiekuna i czas akceptacji, załącznik to KEŚU.

* Plik KEŚU ma rozszerzenie ``.xls``, ale w środku jest XML Spreadsheet 2003
  (z błędami: zdublowany nagłówek XML, niezamienione ``&``), więc czytamy go
  sami, bez czytnika Excela.
* Stawkę MD wstawia NEXUS (stawka klienta z kontraktu, godzinowa × długość MD),
  „Razem w PLN BRUTTO” = stawka MD / godziny MD × 1,23 × godziny + koszty
  dodatkowe, dokładnie jak formuły w pliku klienta.
* Spółka podpisuje paczkę (KEŚU ze stawką i faktury kosztów w jednym PDF), a
  klient odsyła plik z drugim podpisem. Kto podpisał, nie sprawdzamy
  (odpowiedź rozliczeń z 12.11.2026): liczy się, że w pliku są dwa podpisy.
* Oświadczeń o własnym transporcie (PESEL, dowód) nie przyjmujemy do NEXUS-a.
"""

from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html import escape
from typing import Any, Mapping, Optional, Sequence

from app.services.client_settlements.rcp_bnp import SignatureInfo
from app.services.client_settlements.rcp_checks import ProofResult, _Group, name_tokens

KESU_MIME = "application/vnd.ms-excel"
GROUP_TITLE = "KEŚU"
VAT = Decimal("1.23")
MONEY_Q = Decimal("0.01")
MD_Q = Decimal("0.001")
TOLERANCE = Decimal("0.01")
_NS = "urn:schemas-microsoft-com:office:spreadsheet"
_MAX_ROWS = 300
_MAX_COLS = 30

#: Stany KEŚU osoby w miesiącu (lista i karta Finansów).
NO_KESU = "no_kesu"
TO_COMPANY = "to_company"
AWAITING_CLIENT = "awaiting_client"
SIGNED = "signed"
STATE_LABELS = {
    NO_KESU: "Brak KEŚU",
    TO_COMPANY: "Do podpisu spółki",
    AWAITING_CLIENT: "Czeka na podpis klienta",
    SIGNED: "Podpisane przez spółkę i klienta",
}

_JIRA_SUBJECT = re.compile(
    r"Rozliczenie\s+kontraktora\s+(?P<name>.+?)\s+za\s+miesi[aą]c\s+"
    r"(?P<month>\d{1,2})[-./](?P<year>20\d{2})",
    re.IGNORECASE,
)
_KESU_SUBJECT = re.compile(r"KE[SŚ]U\b[^\n]*?\s[-–]\s*(?P<name>[^\n]+?)\s*$", re.I)
_ACCEPTED = re.compile(
    r"zaakceptowane\s+przez\s+(?P<who>.+?)\s+w\s+dniu\s+"
    r"(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.](?P<y>\d{4})"
    r"(?:\s+(?P<time>\d{1,2}:\d{2})(?::\d{2})?)?",
    re.IGNORECASE,
)
_TO_LINE = re.compile(r"^\s*(?:To|Do)\s*:\s*(?P<to>.+)$", re.IGNORECASE | re.M)
_ADDRESS = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
_STATEMENT = re.compile(
    r"o[sś]wiadczeni\w*.*(?:transport|doja[zź]d|samoch[oó]d|pojazd|przejazd)"
    r"|(?:transport|samoch[oó]d|pojazd)\w*.*o[sś]wiadczeni",
    re.IGNORECASE,
)
_BARE_AMP = re.compile(r"&(?!#?[A-Za-z0-9]+;)")


# ── Mail z Jiry ──────────────────────────────────────────────────────────────


def is_kesu_subject(subject: str) -> bool:
    return bool(_JIRA_SUBJECT.search(subject) or _KESU_SUBJECT.search(subject))


def person_from_subject(subject: str) -> Optional[str]:
    """Osoba z tematu maila z Jiry albo „KEŚU <miesiąc> - Imię Nazwisko”."""

    found = _JIRA_SUBJECT.search(subject) or _KESU_SUBJECT.search(subject)
    if found is None:
        return None
    name = found.group("name").strip(" .,:;\"'")
    return name if 2 <= len(name) <= 120 and len(name_tokens(name)) >= 2 else None


def is_transport_statement(file_name: str) -> bool:
    """Oświadczenie o własnym transporcie (PESEL, dowód): nie trafia do NEXUS-a."""

    return bool(_STATEMENT.search(file_name or ""))


@dataclass(frozen=True)
class JiraAcceptance:
    person: str
    month: str
    approver: Optional[str]
    accepted_at: Optional[datetime]
    approver_email: Optional[str]


def _approver_email(body: str, approver: Optional[str]) -> Optional[str]:
    """Adres opiekuna z linii „To:” przekazanego maila, po imieniu i nazwisku."""

    if not approver:
        return None
    wanted = name_tokens(approver)
    for line in _TO_LINE.finditer(body):
        for address in _ADDRESS.findall(line.group("to")):
            local = address.split("@", 1)[0].replace(".", " ").replace("_", " ")
            if wanted and wanted <= name_tokens(local):
                return address
    return None


def parse_jira(subject: str, body: str) -> Optional[JiraAcceptance]:
    """Akceptacja z maila automatu Jiry (także przekazanego dalej)."""

    head = _JIRA_SUBJECT.search(subject) or _JIRA_SUBJECT.search(body)
    if head is None:
        return None
    month = f"{head.group('year')}-{int(head.group('month')):02d}"
    accepted = _ACCEPTED.search(body)
    approver = accepted.group("who").strip() if accepted else None
    when: Optional[datetime] = None
    if accepted:
        try:
            hour, minute = (
                int(x) for x in (accepted.group("time") or "0:0").split(":")
            )
            when = datetime(
                int(accepted.group("y")),
                int(accepted.group("m")),
                int(accepted.group("d")),
                hour,
                minute,
            )
        except ValueError:
            when = None
    return JiraAcceptance(
        person=head.group("name").strip(),
        month=month,
        approver=approver,
        accepted_at=when,
        approver_email=_approver_email(body, approver),
    )


# ── Plik KEŚU ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KesuDay:
    day: int
    place: str
    description: str
    hours: Decimal


@dataclass
class ParsedKesu:
    person: Optional[str]
    month: Optional[str]
    position: Optional[str]
    days: list[KesuDay] = field(default_factory=list)
    total_hours: Optional[Decimal] = None
    total_days: Optional[Decimal] = None
    extra_costs: Decimal = Decimal("0")

    @property
    def hours(self) -> Decimal:
        return sum((d.hours for d in self.days), Decimal("0"))


def is_kesu_file(content: bytes) -> bool:
    head = content[:4096].lstrip()
    return (
        head.startswith(b"<?xml")
        and b"urn:schemas-microsoft-com:office:spreadsheet" in content[:8192]
    )


def _grid(content: bytes) -> Optional[list[dict[int, tuple[str, Optional[str]]]]]:
    """Wiersze arkusza: {kolumna: (tekst, typ)}, z ``ss:Index`` i scaleniami."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("cp1250", "replace")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    start = text.find("<Workbook")
    if start < 0:
        return None
    try:
        root = ET.fromstring(_BARE_AMP.sub("&amp;", text[start:]))
    except ET.ParseError:
        return None
    sheet = root.find(f"{{{_NS}}}Worksheet")
    table = sheet.find(f"{{{_NS}}}Table") if sheet is not None else None
    if table is None:
        return None
    rows: list[dict[int, tuple[str, Optional[str]]]] = []
    row_no = 0
    for row in table.findall(f"{{{_NS}}}Row")[:_MAX_ROWS]:
        index = row.get(f"{{{_NS}}}Index")
        row_no = int(index) if index and index.isdigit() else row_no + 1
        if row_no > _MAX_ROWS:
            # KEŚU ma ok. 50 wierszy; numer z pliku z zewnątrz nie może
            # rozdmuchać listy pustych wierszy.
            return None
        while len(rows) < row_no - 1:
            rows.append({})
        cells: dict[int, tuple[str, Optional[str]]] = {}
        col = 0
        for cell in row.findall(f"{{{_NS}}}Cell"):
            ci = cell.get(f"{{{_NS}}}Index")
            col = int(ci) if ci and ci.isdigit() else col + 1
            if col > _MAX_COLS:
                break
            data = cell.find(f"{{{_NS}}}Data")
            if data is not None:
                value = "".join(data.itertext())
                cells[col] = (value, data.get(f"{{{_NS}}}Type"))
            merge = cell.get(f"{{{_NS}}}MergeAcross")
            if merge and merge.isdigit():
                col += int(merge)
        rows.append(cells)
    return rows


def _dec(raw: Optional[str]) -> Optional[Decimal]:
    if raw is None:
        return None
    cleaned = raw.replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _label(raw: str) -> str:
    return " ".join(raw.lower().split())


def parse(content: bytes) -> Optional[ParsedKesu]:
    """KEŚU z pliku XML Spreadsheet 2003; inny plik = ``None``."""

    if not is_kesu_file(content):
        return None
    rows = _grid(content)
    if not rows or not any(
        "karta ewidencji" in _label(v[0]) for r in rows[:5] for v in r.values()
    ):
        return None
    kesu = ParsedKesu(person=None, month=None, position=None)
    header: Optional[dict[str, int]] = None
    year: Optional[int] = None
    month: Optional[int] = None
    for cells in rows:
        texts = {c: v[0] for c, v in cells.items()}
        first = _label(texts.get(min(texts), "")) if texts else ""
        for value in texts.values():
            lowered = _label(value)
            if lowered.startswith("imię i nazwisko:") or lowered.startswith(
                "imie i nazwisko:"
            ):
                kesu.person = value.split(":", 1)[1].strip() or None
            elif lowered.startswith("stanowisko:"):
                kesu.position = value.split(":", 1)[1].strip() or None
            elif lowered.startswith("rok:"):
                digits = re.search(r"20\d{2}", value)
                year = int(digits.group(0)) if digits else year
        if first.startswith("miesiąc") or first.startswith("miesiac"):
            numbers = [
                v
                for c, v in sorted(texts.items())
                if re.fullmatch(r"\d{1,2}", v.strip())
            ]
            month = int(numbers[0]) if numbers else month
            continue
        if header is None and any(_label(v) == "dzień" for v in texts.values()):
            header = {}
            for col, value in texts.items():
                lowered = _label(value)
                if lowered == "dzień":
                    header["day"] = col
                elif lowered.startswith("miejsce"):
                    header["place"] = col
                elif lowered.startswith("opis"):
                    header["description"] = col
                elif lowered.startswith("liczba godzin"):
                    header["hours"] = col
            continue
        if first.startswith("suma godzin"):
            kesu.total_hours = _dec(_after(cells, min(texts)))
            continue
        if first.startswith("suma dni"):
            kesu.total_days = _dec(_after(cells, min(texts)))
            continue
        if first.startswith("suma kosztów") or first.startswith("suma kosztow"):
            kesu.extra_costs = _dec(_after(cells, min(texts))) or Decimal("0")
            continue
        if header and "day" in header and "hours" in header:
            day_raw = texts.get(header["day"], "").strip()
            if re.fullmatch(r"\d{1,2}", day_raw) and 1 <= int(day_raw) <= 31:
                hours = _dec(texts.get(header["hours"])) or Decimal("0")
                kesu.days.append(
                    KesuDay(
                        day=int(day_raw),
                        place=texts.get(header.get("place", -1), "").strip(),
                        description=texts.get(
                            header.get("description", -1), ""
                        ).strip(),
                        hours=hours,
                    )
                )
    if header is None or not kesu.days:
        return None
    if year and month and 1 <= month <= 12:
        kesu.month = f"{year}-{month:02d}"
    return kesu


def _after(cells: dict[int, tuple[str, Optional[str]]], col: int) -> Optional[str]:
    later = [c for c in sorted(cells) if c > col]
    return cells[later[0]][0] if later else None


# ── Kwoty i podpisy ──────────────────────────────────────────────────────────


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Amounts:
    rate_md: Decimal
    fee_gross: Decimal
    extra_costs: Decimal
    total_gross: Decimal


def amounts(
    hours: Decimal, rate_md: Decimal, extra_costs: Decimal, *, md_hours: Decimal
) -> Amounts:
    """Kwoty KEŚU jak w formułach klienta: (stawka MD / h w MD) × 1,23 × godziny."""

    fee = _money(rate_md / md_hours * VAT * hours)
    return Amounts(rate_md, fee, _money(extra_costs), _money(fee + extra_costs))


def signature_state(found: Sequence[Sequence[SignatureInfo]]) -> str:
    """Najlepszy stan z podpisanych PDF-ów KEŚU osoby w miesiącu.

    Dwa ważne podpisy w jednym pliku (spółka i klient) = podpisane, jeden =
    czeka na klienta. Podpisu nie przypisujemy do osoby (decyzja z 12.11).
    """

    best = 0
    for signatures in found:
        intact = [s for s in signatures if s.intact]
        if intact and any(s.entire_file for s in intact):
            best = max(best, len(intact))
    if best >= 2:
        return SIGNED
    if best == 1:
        return AWAITING_CLIENT
    return TO_COMPANY


# ── Kontrole ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rates:
    """Stawka MD do KEŚU: z kontraktu, a dla porównania z linii zamówienia."""

    contract_md: Optional[Decimal]
    order_md: Optional[Decimal]

    @property
    def used(self) -> Optional[Decimal]:
        return self.contract_md if self.contract_md is not None else self.order_md


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


def evaluate(
    kesu: ParsedKesu,
    *,
    month: str,
    person_name: str,
    jira: Optional[JiraAcceptance],
    signatures: Sequence[Sequence[SignatureInfo]],
    rates: Rates,
    cost_invoices: int,
    rules: Mapping[str, Mapping[str, Any]],
) -> ProofResult:
    """MD z KEŚU, grupy kontroli i ``meta['kesu']`` dla karty i listy Finansów.

    Kwot nie ma w tytułach kontroli (widzą je wszyscy z modułem Finansów);
    kwoty są w ``meta`` i API oddaje je tylko kontom z dostępem do kwot.
    """

    md_hours = Decimal(
        str(rules["fields.md_hours"]["params"].get("hours") or "8").replace(",", ".")
    )
    if md_hours <= 0:
        md_hours = Decimal("8")
    hours = kesu.hours
    result = ProofResult(
        md_regular=(hours / md_hours).quantize(MD_Q, rounding=ROUND_HALF_UP),
        md_extra=None,
    )
    group = _Group(result, rules, GROUP_TITLE)
    if jira is not None and jira.approver:
        when = jira.accepted_at.strftime("%d.%m.%Y %H:%M") if jira.accepted_at else ""
        group.ok(
            "Akceptacja opiekuna w Jirze",
            ", ".join(x for x in (jira.approver, when, "automat Jira") if x),
        )
    else:
        group.checks.append(
            {
                "state": "warn",
                "title": "Brak maila z Jiry z akceptacją opiekuna",
                "detail": "KEŚU bez maila automatu Jiry: opiekuna i adres do wysyłki "
                "wpisz ręcznie.",
            }
        )
        result.warn = True
    if kesu.month == month:
        group.ok(f"KEŚU za {month}")
    else:
        group.fail(
            "proof.month", "KEŚU za inny miesiąc", f"W pliku: {kesu.month or 'brak'}."
        )
    kesu_names = name_tokens(kesu.person)
    if kesu_names and (
        kesu_names <= name_tokens(person_name) or name_tokens(person_name) <= kesu_names
    ):
        group.ok("Imię i nazwisko jak w kontrakcie")
    else:
        group.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    worked = sum(1 for d in kesu.days if d.hours > 0)
    group.ok(f"{_fmt(hours)} h, {worked} dni")
    if group.on("fields.md_hours"):
        declared_ok = (
            kesu.total_hours is None or abs(kesu.total_hours - hours) <= TOLERANCE
        )
        days_ok = (
            kesu.total_days is None
            or abs(kesu.total_days - hours / md_hours) <= TOLERANCE
        )
        if not (declared_ok and days_ok):
            group.fail(
                "fields.md_hours",
                "Sumy KEŚU nie zgadzają się z godzinami dni",
                f"Dni: {_fmt(hours)} h; „Suma godzin”: {_fmt(kesu.total_hours or Decimal(0))} h; "
                f"„Suma dni”: {_fmt(kesu.total_days or Decimal(0))}.",
            )
    if group.on("fields.day_limit") and kesu.days:
        limit = Decimal(
            str(rules["fields.day_limit"]["params"].get("hours") or "24").replace(
                ",", "."
            )
        )
        worst = max(kesu.days, key=lambda d: d.hours)
        if worst.hours > limit:
            group.fail(
                "fields.day_limit",
                f"{_fmt(worst.hours)} h w dniu {worst.day}",
                f"Limit {_fmt(limit)} h.",
            )
    if rates.used is None:
        group.checks.append(
            {
                "state": "warn",
                "title": "Brak stawki klienta w kontrakcie i na zamówieniu",
                "detail": "Bez stawki MD NEXUS nie policzy „Razem w PLN BRUTTO”.",
            }
        )
        result.warn = True
    elif rates.contract_md is None:
        group.checks.append(
            {
                "state": "warn",
                "title": "Stawka MD z zamówienia, kontrakt jej nie ma",
                "detail": "Uzupełnij stawkę klienta w kontrakcie.",
            }
        )
        result.warn = True
    elif (
        rates.order_md is not None
        and abs(rates.order_md - rates.contract_md) > TOLERANCE
    ):
        group.checks.append(
            {
                "state": "warn",
                "title": "Stawka MD w kontrakcie inna niż na zamówieniu",
                "detail": "Różnica jest na karcie przy KEŚU. Sprawdź, która jest właściwa.",
            }
        )
        result.warn = True
    else:
        group.ok("Stawka MD z kontraktu wstawiona, „Razem brutto” policzone")
    state = signature_state(signatures)
    if state == SIGNED:
        group.ok("Podpis spółki i klienta w odesłanym KEŚU")
    elif state == AWAITING_CLIENT:
        group.info(
            "Czeka na podpis klienta", "Bez niego nie wystawimy faktury do klienta."
        )
    else:
        group.info("Do podpisu spółki", "Pobierz paczkę, podpisz i wyślij do opiekuna.")
    group.close()

    if kesu.extra_costs > 0:
        costs = _Group(result, rules, "Koszty dodatkowe")
        if rules["travel.extra_costs_confirm"]["level"] != "off":
            # Ta kontrola nigdy nie blokuje sama (odpowiedź rozliczeń z 12.11).
            costs.checks.append(
                {
                    "state": "warn",
                    "title": "Koszty dodatkowe w KEŚU",
                    "detail": "Przed odrzuceniem albo oznaczeniem jako błąd potwierdź "
                    "u osoby rozliczającej klienta.",
                    "rule": "travel.extra_costs_confirm",
                }
            )
            result.warn = True
        if cost_invoices:
            costs.ok(
                f"Faktury kosztów z maila z Jiry: {cost_invoices}",
                "Idą w paczce do podpisu.",
            )
        else:
            costs.checks.append(
                {
                    "state": "warn",
                    "title": "Brak faktury kosztów w mailu z Jiry",
                    "detail": None,
                }
            )
            result.warn = True
        costs.close()

    sums = (
        amounts(hours, rates.used, kesu.extra_costs, md_hours=md_hours)
        if rates.used is not None
        else None
    )
    result.meta["kesu"] = {
        "state": state,
        "approver": jira.approver if jira else None,
        "approver_email": jira.approver_email if jira else None,
        "accepted_at": jira.accepted_at.isoformat()
        if jira and jira.accepted_at
        else None,
        "hours": f"{hours:.2f}",
        "days": worked,
        "md_hours": f"{md_hours:f}",
        "rate_md": None if sums is None else f"{sums.rate_md:.2f}",
        "rate_contract": None
        if rates.contract_md is None
        else f"{rates.contract_md:.2f}",
        "rate_order": None if rates.order_md is None else f"{rates.order_md:.2f}",
        "fee_gross": None if sums is None else f"{sums.fee_gross:.2f}",
        "extra_costs": f"{_money(kesu.extra_costs):.2f}",
        "total_gross": None if sums is None else f"{sums.total_gross:.2f}",
    }
    return result


# ── Paczka do podpisu i mail do opiekuna ─────────────────────────────────────


_MONTHS_PL = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


def _pl(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return text


def render_html(
    kesu: ParsedKesu, *, rate_md: Decimal, md_hours: Decimal, month: str
) -> str:
    """KEŚU ze stawką do druku: układ i formuły jak w pliku klienta."""

    year, mon = (int(x) for x in month.split("-"))
    per_day = rate_md / md_hours * VAT
    rows = "".join(
        "<tr>"
        f"<td class='n'>{d.day}</td><td>{escape(d.place)}</td>"
        f"<td class='desc'>{escape(d.description).replace(chr(10), '<br>')}</td>"
        f"<td class='n'>{_fmt(d.hours)}</td>"
        f"<td class='n'>{_pl(rate_md) if d.hours > 0 else ''}</td>"
        f"<td class='n'>{_pl(_money(per_day * d.hours))}</td>"
        "</tr>"
        for d in kesu.days
    )
    sums = amounts(kesu.hours, rate_md, kesu.extra_costs, md_hours=md_hours)
    summary = (
        ("Suma godzin przepracowanych", _fmt(kesu.hours)),
        ("Suma dni przepracowanych", f"{kesu.hours / md_hours:.2f}"),
        ("Suma kosztów dodatkowych", _pl(sums.extra_costs)),
        ("Wartość przekazanych praw autorskich", _pl(sums.fee_gross)),
        ("Razem w PLN BRUTTO", _pl(sums.total_gross)),
    )
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>KEŚU {year}-{mon:02d}</title><style>"
        "@page{size:A4 landscape;margin:12mm 12mm}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:8pt;color:#111}"
        "h1{font-size:12pt;margin:0 0 6pt}p{margin:1pt 0}"
        "table{border-collapse:collapse;width:100%;margin-top:6pt}"
        "th,td{border:0.5px solid #888;padding:2pt 3pt;vertical-align:top}"
        "th{background:#eee;font-weight:600;text-align:left}"
        ".n{text-align:right;white-space:nowrap}.desc{width:52%}"
        ".sum td:first-child{font-weight:600;width:40%}.sum{width:55%}"
        ".sign{margin-top:22pt;width:100%}.sign td{border:0;width:50%;padding-top:30pt}"
        "</style></head><body>"
        "<h1>Karta Ewidencji Świadczenia Usług</h1>"
        f"<p>Imię i nazwisko: {escape(kesu.person or '')}</p>"
        f"<p>Stanowisko: {escape(kesu.position or '')}</p>"
        f"<p>Miesiąc: {mon} ({_MONTHS_PL[mon - 1]}) &nbsp; Rok: {year}</p>"
        "<table><thead><tr><th>Dzień</th><th>Miejsce świadczenia usług</th>"
        "<th>Opis wykonywanych zadań</th><th>Liczba godzin (P)</th>"
        "<th>Stawka MD PLN netto</th><th>Wynagrodzenie PLN Brutto</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<table class='sum'>"
        + "".join(
            f"<tr><td>{escape(k)}</td><td class='n'>{escape(v)}</td></tr>"
            for k, v in summary
        )
        + "</table>"
        "<table class='sign'><tr><td>Dostawca:</td><td>Zamawiający:</td></tr></table>"
        "</body></html>"
    )


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def merge_pdfs(first: bytes, extra: Sequence[bytes]) -> bytes:
    """Jeden PDF: KEŚU, a za nim strony faktur kosztów (pyHanko, bez nowej zależności).

    Strona dołączanego pliku idzie jako obraz wektorowy (XObject) na nowej
    stronie tego samego rozmiaru, więc paczka nie przenosi starych podpisów
    ani formularzy z faktur.
    """

    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.writer import copy_into_new_writer

    writer = copy_into_new_writer(PdfFileReader(io.BytesIO(first), strict=False))
    for blob in extra:
        reader = PdfFileReader(io.BytesIO(blob), strict=False)
        count = int(reader.root["/Pages"]["/Count"])
        for index in range(count):
            page, _ = reader.find_page_for_modification(index)
            box = page.get_object().get("/MediaBox") or [0, 0, 595.28, 841.89]
            xobject = writer.import_page_as_xobject(reader, page_ix=index)
            content = writer.add_object(generic.StreamObject(stream_data=b"q /P0 Do Q"))
            writer.insert_page(
                generic.DictionaryObject(
                    {
                        generic.NameObject("/Type"): generic.NameObject("/Page"),
                        generic.NameObject("/MediaBox"): generic.ArrayObject(
                            [generic.FloatObject(float(v)) for v in box]
                        ),
                        generic.NameObject("/Resources"): generic.DictionaryObject(
                            {
                                generic.NameObject(
                                    "/XObject"
                                ): generic.DictionaryObject(
                                    {generic.NameObject("/P0"): xobject}
                                )
                            }
                        ),
                        generic.NameObject("/Contents"): content,
                    }
                )
            )
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def package_name(person: str, month: str) -> str:
    year, mon = month.split("-")
    folded = unicodedata.normalize("NFKD", person.replace("ł", "l").replace("Ł", "L"))
    safe = re.sub(r"[^A-Za-z0-9]+", "_", folded.encode("ascii", "ignore").decode())
    safe = safe.strip("_")
    return f"KESU_{safe or 'osoba'}_{mon}.{year}.pdf"


def mail_draft(
    *, person: str, month: str, approver: Optional[str], approver_email: Optional[str]
) -> dict[str, Optional[str]]:
    """Mail do opiekuna z maila z Jiry, ze wzoru rozliczeń."""

    mon = int(month.split("-")[1])
    first = person.split()[0] if person.split() else person
    return {
        "to": approver_email,
        "to_name": approver,
        "subject": f"KEŚU {_MONTHS_PL[mon - 1]} - {person}",
        "body": (
            "Dzień dobry,\n\n"
            f"W załączeniu KEŚU ({first}) z naszym podpisem. "
            "Prośba o podpis po Państwa stronie. Dziękuję.\n\nPozdrawiam,"
        ),
    }
