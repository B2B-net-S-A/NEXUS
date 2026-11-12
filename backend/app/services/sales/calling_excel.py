"""Jednorazowe przeniesienie Excela osób dzwoniących do kolejki (decyzje Artura 11.11.2026).

Reguły: ``docs/claude/sprzedaz/dzwonienie-przeniesienie-excela.md``. W skrócie:

* **arkusz = osoba**: osobę wybiera człowiek w oknie (podpowiedź po imieniu z nazwy
  arkusza), cały arkusz trafia do jej kolejki;
* **wynik**: najpierw kolor wiersza (legenda Excela: czerwony „nie zainteresowany”, żółty
  „oferta wysłana”, niebieski „umówione spotkanie”, zielony „zainteresowany po
  spotkaniu”), a gdy koloru nie ma, słowa z komentarza po rozmowie. Komentarz bez
  rozpoznanego wyniku zostaje „nowym” rekordem i liczy się jako „do przejrzenia”;
* **data powrotu** z kolumny „Ponowny kontakt” (albo z komentarza), w innym razie domyślna
  dla wyniku jak w kolejce; data z przeszłości oznacza „dziś”;
* **wiersze „Podsumowanie”** dnia nie są osobami: idą do ``sales_call_day_totals``;
* ten sam numer w dwóch arkuszach zostaje w **późniejszym** arkuszu (przekazania robiono
  kopiowaniem wiersza do arkusza następnej osoby);
* zapis idzie przez te same bramki co import listy (``calling_import``): sprzeciw, klient
  NEXUSA, ktoś inny dzwoni, już w kampanii. Podgląd niczego nie zapisuje.

Logi są publiczne: tylko liczby.
"""

from __future__ import annotations

import colorsys
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCallCampaign, SalesCallDayTotal
from app.models.user import User
from app.services import sales_schema as schema
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.sales import calling, calling_import
from app.services.sales.calling_file import (
    EMPTY_DETAIL,
    MAX_COLUMNS,
    MAX_ROWS,
    ListFile,
    ListFileError,
    ListRow,
    clean_cell,
    columns_of,
    header_key,
    open_workbook,
    phone_digits,
    row_values,
)

logger = logging.getLogger(__name__)

MAX_SHEETS = 10
NOTE_LIMIT = 1000
TOO_MANY_SHEETS_DETAIL = f"Plik ma więcej niż {MAX_SHEETS} arkuszy."
NOT_XLSX_DETAIL = "Przeniesienie Excela przyjmuje tylko plik .xlsx (arkusz na osobę)."

NEW = schema.CALL_RECORD_NEW
REVIEW = "review"
#: Kolejność wyników w podglądzie (tak samo jak legenda Excela).
STATE_ORDER: tuple[str, ...] = (
    "no_answer",
    "call_back",
    "offer_sent",
    NEW,
    "meeting_booked",
    "not_interested",
    "bad_contact",
)

_SUMMARY = re.compile(r"wykonane\s+telefony", re.IGNORECASE)
_DAY = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?!\d)")
_ISO_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Zaprzeczenie jako osobne słowo: „spotkaNIE”, „poNIEdziałek”, „chętNIE” to nie „nie”.
_NOT_INTERESTED = re.compile(r"\bnie\s*(?:(?:jest|sa|byl|byla|byli)\s+)?zainter")
_TOTAL_LABELS: tuple[tuple[str, str], ...] = (
    ("calls", r"telefon"),
    ("talks", r"rozmow"),
    ("offers", r"ofert"),
    ("meetings", r"spotka"),
)


def _fold(value: str) -> str:
    """Małe litery bez polskich znaków: literówki w komentarzach są bez ogonków."""

    text = unicodedata.normalize("NFKD", value.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).replace("ł", "l")


# ── Wynik wiersza ─────────────────────────────────────────────────────────


def color_state(rgb: Optional[str]) -> Optional[str]:
    """Wynik z koloru wypełnienia (``FFRRGGBB``); po odcieniu, bo arkusze mają różne czerwienie."""

    if not rgb or len(rgb) != 8:
        return None
    try:
        red, green, blue = (int(rgb[i : i + 2], 16) / 255 for i in (2, 4, 6))
    except ValueError:
        return None
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    if saturation < 0.35 or lightness > 0.9 or lightness < 0.15:
        return None
    degrees = hue * 360
    if degrees < 20 or degrees >= 340:
        return "not_interested"
    if 45 <= degrees < 70:
        return "offer_sent"
    if 75 <= degrees < 165:
        return "interested"
    if 180 <= degrees < 250:
        return "meeting_booked"
    return None


def comment_state(comment: Optional[str]) -> Optional[str]:
    """Wynik ze słów komentarza; ``None`` = brak komentarza, ``REVIEW`` = bez wyniku."""

    text = _fold(comment or "").strip()
    if not text or text in ("brak", "none", "-"):
        return None
    if re.search(r"nie odb|nie odebr|zajet|nie odpow", text):
        return "no_answer"
    if _NOT_INTERESTED.search(text):
        return "not_interested"
    if re.search(r"brak danych|infolini|zla firma|nieprawid|zly numer|jednoosob", text):
        return "bad_contact"
    if re.search(r"ofert|prezentac", text):
        return "offer_sent"
    if re.search(r"urlop|zadzwo|dzwoni|oddzwo|po poludniu|\d{1,2}\.\d{1,2}", text):
        return "call_back"
    return REVIEW


def parse_day(value: Any, today: date) -> Optional[date]:
    """Dzień z komórki: data, „2026-11-04”, „27.07” albo „16.11.2026”.

    Bez roku: bieżący, a gdy wypada po dzisiejszym, poprzedni (arkusz opisuje przeszłość
    albo najbliższe dni).
    """

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")
    iso = _ISO_DAY.search(text)
    if iso:
        try:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        except ValueError:
            return None
    match = _DAY.search(text)
    if not match:
        return None
    day, month = int(match[1]), int(match[2])
    year = int(match[3]) if match[3] else today.year
    try:
        found = date(year, month, day)
    except ValueError:
        return None
    if not match[3] and found > today + timedelta(days=60):
        found = found.replace(year=year - 1)
    return found


def callback_for(state: str, requested: Optional[date], today: date) -> Optional[date]:
    if state == "not_interested":
        return calling.resolve_callback(state, None, today)
    if state not in calling.RETURNING_STATES:
        return None
    if requested is not None:
        return max(requested, today)
    return calling.default_callback(state, today)


# ── Arkusze ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExcelRow:
    row: ListRow
    state: str
    callback_on: Optional[date]
    review: bool = False


@dataclass(frozen=True)
class DayTotal:
    day: date
    calls: int
    talks: int
    offers: int
    meetings: int


@dataclass
class Sheet:
    title: str
    rows: list[ExcelRow] = field(default_factory=list)
    without_company: int = 0
    days: dict[date, DayTotal] = field(default_factory=dict)
    duplicate_days: int = 0
    #: Wiersze, które zostały w późniejszym arkuszu (ten sam numer).
    moved: int = 0


def _summary(cells: list[Any], today: date) -> Optional[DayTotal]:
    """Wiersz „Podsumowanie”: liczby po etykietach w tej samej albo następnej komórce."""

    tokens = [cell for cell in cells if cell not in (None, "")]
    day = next(
        (found for found in (parse_day(cell, today) for cell in tokens) if found), None
    )
    values: dict[str, int] = {}
    for index, token in enumerate(tokens):
        if not isinstance(token, str):
            continue
        folded = _fold(token)
        for key, pattern in _TOTAL_LABELS:
            if key in values or not re.search(pattern, folded):
                continue
            inline = re.search(r":\s*(\d+)", token)
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if inline:
                values[key] = int(inline[1])
            elif isinstance(following, (int, float)):
                values[key] = int(following)
            elif isinstance(following, str) and following.strip().isdigit():
                values[key] = int(following.strip())
    if day is None or len(values) < len(_TOTAL_LABELS):
        return None
    return DayTotal(day=day, **values)


def _fill_rgb(cell: Any) -> Optional[str]:
    fill = getattr(cell, "fill", None)
    if fill is None or fill.fill_type is None:
        return None
    color = fill.fgColor
    return color.rgb if getattr(color, "type", None) == "rgb" else None


def _row_color(row: tuple[Any, ...], width: int) -> Optional[str]:
    states = [color_state(_fill_rgb(cell)) for cell in row[:width]]
    found = [state for state in states if state]
    return max(set(found), key=found.count) if found else None


def _extra_columns(header: list[Any]) -> dict[str, int]:
    """Kolumny Excela dzwoniących, których nie zna zwykły import."""

    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = header_key(cell)
        if key.startswith("komentarz po rozmowie") and "comment" not in found:
            found["comment"] = index
        elif key.startswith("ponowny kontakt") and "callback" not in found:
            found["callback"] = index
    return found


def _note(comment: Optional[str], remarks: Optional[str]) -> Optional[str]:
    parts = [part for part in (comment, remarks) if part]
    if not parts:
        return None
    return f"Z Excela: {' · '.join(parts)}"[:NOTE_LIMIT]


def _parse_sheet(sheet: Any, today: date) -> Sheet:
    parsed = Sheet(title=str(sheet.title)[:120])
    rows = sheet.iter_rows(max_row=MAX_ROWS + 2, max_col=MAX_COLUMNS)
    columns: Optional[dict[str, int]] = None
    extra: dict[str, int] = {}
    width = 0
    for line, row in enumerate(rows, start=1):
        cells = [cell.value for cell in row]
        if columns is None:
            if sum(1 for cell in cells if clean_cell(cell, 255)) < 3:
                continue
            try:
                columns = columns_of(cells)
            except ListFileError:
                return parsed
            extra = _extra_columns(cells)
            width = max([*columns.values(), *extra.values()]) + 1
            continue
        joined = " ".join(str(cell) for cell in cells if cell not in (None, ""))
        if _SUMMARY.search(joined):
            total = _summary(cells, today)
            if total is not None:
                if total.day in parsed.days:
                    parsed.duplicate_days += 1
                parsed.days[total.day] = total
            continue
        values = row_values(line, cells, columns)
        if values is None:
            continue
        if not values["company"]:
            parsed.without_company += 1
            continue
        comment = (
            clean_cell(cells[extra["comment"]], 500) if "comment" in extra else None
        )
        values["note"] = _note(comment, values.get("note"))
        by_comment = comment_state(comment)
        state = _row_color(row, width) or by_comment or NEW
        review = state == REVIEW
        if state in (REVIEW, NEW):
            state = NEW
        elif state == "interested":
            state = "meeting_booked"
        requested = (
            parse_day(cells[extra["callback"]], today) if "callback" in extra else None
        ) or (parse_day(comment, today) if by_comment == "call_back" else None)
        parsed.rows.append(
            ExcelRow(
                row=ListRow(**values),
                state=state,
                callback_on=callback_for(state, requested, today),
                review=review,
            )
        )
    return parsed


def _dedupe(sheets: list[Sheet]) -> None:
    """Ten sam numer w kilku arkuszach zostaje w ostatnim (przekazanie = kopia wiersza)."""

    seen: set[str] = set()
    for sheet in reversed(sheets):
        kept: list[ExcelRow] = []
        for item in sheet.rows:
            digits = phone_digits(item.row.phone)
            key = digits[-9:] if digits else None
            if key and key in seen:
                sheet.moved += 1
                continue
            if key:
                seen.add(key)
            kept.append(item)
        sheet.rows = kept


def parse_workbook(filename: str, payload: bytes, today: date) -> list[Sheet]:
    """Arkusze z wierszami i podsumowaniami; ``ListFileError`` z komunikatem, gdy plik odpada."""

    if not (filename or "").lower().endswith(".xlsx"):
        raise ListFileError(NOT_XLSX_DETAIL)
    workbook = open_workbook(payload, read_only=False)
    try:
        visible = [
            sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"
        ]
        if len(visible) > MAX_SHEETS:
            raise ListFileError(TOO_MANY_SHEETS_DETAIL)
        sheets = [_parse_sheet(sheet, today) for sheet in visible]
    finally:
        workbook.close()
    sheets = [sheet for sheet in sheets if sheet.rows or sheet.days]
    if not sheets:
        raise ListFileError(EMPTY_DETAIL)
    _dedupe(sheets)
    return sheets


# ── Podgląd i zapis ───────────────────────────────────────────────────────


async def sales_editors(db: AsyncSession) -> list[tuple[int, str]]:
    """Aktywne osoby z „Sprzedaż: edycja”: lista wyboru „arkusz → osoba” i podpowiedź."""

    users = list(
        (
            await db.execute(
                select(User).where(User.is_active.is_(True)).order_by(User.name)
            )
        ).scalars()
    )
    await resolve_effective_access(db, users)
    return [
        (user.id, user.name)
        for user in users
        if has_permission(user, ProductAction.sales_edit)
    ]


def suggest(title: str, people: list[tuple[int, str]]) -> Optional[int]:
    """Osoba po imieniu z nazwy arkusza („Bianca” → „Bianca …”); przy dwóch pasujących nikt."""

    key = _fold(title).strip()
    if not key:
        return None
    matches = [
        user_id
        for user_id, name in people
        if _fold(name).split()[:1] == [key] or _fold(name) == key
    ]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class SheetPlan:
    title: str
    assignee_id: Optional[int]
    rows: int
    #: Wyniki rekordów, które trafią do kolejki.
    states: dict[str, int]
    review: int
    #: Los wierszy z bramek importu (np. „dzwoni ktoś inny”).
    fates: dict[str, int]
    addable: int
    without_company: int
    moved: int
    days: int
    duplicate_days: int
    totals: dict[str, int]


def _totals(sheet: Sheet) -> dict[str, int]:
    return {
        key: sum(getattr(day, key) for day in sheet.days.values())
        for key, _ in _TOTAL_LABELS
    }


def _listing(sheet: Sheet) -> ListFile:
    return ListFile(
        rows=[item.row for item in sheet.rows], without_company=sheet.without_company
    )


def _overrides(sheet: Sheet) -> dict[int, calling_import.RecordOverride]:
    return {
        item.row.line: calling_import.RecordOverride(
            state=item.state,
            callback_on=item.callback_on,
            attempts=0 if item.state == NEW else 1,
        )
        for item in sheet.rows
    }


async def plan_sheets(
    db: AsyncSession,
    campaign: SalesCallCampaign,
    sheets: list[Sheet],
    assignees: dict[str, int],
    people: list[tuple[int, str]],
    *,
    user_id: int,
) -> list[SheetPlan]:
    """Bieg na sucho: zapis arkusz po arkuszu w savepoincie, który się cofa.

    Zapis idzie po kolei, więc firma z wcześniejszego arkusza jest już w kolejce,
    gdy przychodzi późniejszy (``other_caller``). Planowanie każdego arkusza osobno
    obiecywało więcej, niż zapis dodawał (audyt 12.11.2026).
    """

    campaign_id = campaign.id
    plans: list[SheetPlan] = []
    dry_run = await db.begin_nested()
    try:
        for sheet in sheets:
            assignee = assignees.get(sheet.title) or suggest(sheet.title, people)
            by_line = {item.row.line: item for item in sheet.rows}
            states: dict[str, int] = {}
            fates: dict[str, int] = {}
            addable = 0
            if assignee is not None and sheet.rows:
                plan, _ = await calling_import.apply_import(
                    db,
                    campaign_id,
                    _listing(sheet),
                    contact_source=calling_import.CONTACT_SOURCE,
                    assignee_id=assignee,
                    user_id=user_id,
                    overrides=_overrides(sheet),
                )
                fates = {fate: n for fate, n in plan.counts.items() if n}
                for row_plan in plan.rows:
                    if row_plan.fate in calling_import.ADDABLE:
                        addable += 1
                        state = by_line[row_plan.row.line].state
                        states[state] = states.get(state, 0) + 1
            plans.append(
                SheetPlan(
                    title=sheet.title,
                    assignee_id=assignee,
                    rows=len(sheet.rows),
                    states=states,
                    review=sum(1 for item in sheet.rows if item.review),
                    fates=fates,
                    addable=addable,
                    without_company=sheet.without_company,
                    moved=sheet.moved,
                    days=len(sheet.days),
                    duplicate_days=sheet.duplicate_days,
                    totals=_totals(sheet),
                )
            )
    finally:
        await dry_run.rollback()
    return plans


@dataclass(frozen=True)
class TransferResult:
    added: int
    days: int


async def apply_sheets(
    db: AsyncSession,
    campaign_id: int,
    sheets: list[Sheet],
    assignees: dict[str, int],
    *,
    contact_source: str,
    user_id: int,
) -> TransferResult:
    """Zapis po bramkach importu i podsumowania dni; bez commita."""

    added = 0
    days = 0
    for sheet in sheets:
        assignee = assignees[sheet.title]
        if sheet.rows:
            _, count = await calling_import.apply_import(
                db,
                campaign_id,
                _listing(sheet),
                contact_source=contact_source,
                assignee_id=assignee,
                user_id=user_id,
                overrides=_overrides(sheet),
            )
            added += count
        for total in sheet.days.values():
            values = {
                "calls": total.calls,
                "talks": total.talks,
                "offers": total.offers,
                "meetings": total.meetings,
            }
            await db.execute(
                insert(SalesCallDayTotal)
                .values(
                    user_id=assignee,
                    day=total.day,
                    source=schema.CALL_DAY_TOTALS_EXCEL,
                    created_by_user_id=user_id,
                    **values,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "day", "source"], set_=values
                )
            )
            days += 1
    await db.flush()
    logger.info(
        "sales_calling excel campaign=%s sheets=%d added=%d days=%d",
        campaign_id,
        len(sheets),
        added,
        days,
    )
    return TransferResult(added=added, days=days)
