"""Rejestr generatorów raportów klienta.

Generator to kod wspólny dla wszystkich klientów: klucz, zakres danych,
wymagane uprawnienie i funkcja, która z danych NEXUSA za okres składa podgląd
i plik. Różnice między klientami (kolumny, jednostki, progi rabatu) idą
w ``params`` definicji, nie w kodzie — nowy klient z takim samym raportem to
nowy wiersz w ``client_report_definitions``, bez zmian tutaj.

Czego tu nie robimy (decyzja 15.11.2026): listy id klientów ani gałęzi
``if client == …`` w generatorze, osobnej trasy per klient, drugiego silnika
rozliczeń (RCP, KEŚU i timesheety zostają w ``client_settlements``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.schedule import Period

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class ParamField:
    """Pole parametru definicji (formularz na froncie i walidacja)."""

    key: str
    label: str
    kind: str  # "bool" | "text" | "number" | "tiers"
    default: Any = None
    hint: Optional[str] = None


@dataclass(frozen=True)
class SummaryLine:
    label: str
    value: str
    strong: bool = False


@dataclass(frozen=True)
class Sheet:
    name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    #: Szerokości kolumn w znakach; brak = 16.
    widths: tuple[int, ...] = ()
    #: Zdanie nad tabelą (np. „uzupełnij przed wysłaniem”).
    note: Optional[str] = None


@dataclass(frozen=True)
class ReportContext:
    client_id: int
    client_name: str
    period: Period
    params: Mapping[str, Any]
    today: date


@dataclass(frozen=True)
class ReportData:
    """Wynik generatora: podgląd w oknie pobrania i treść pliku."""

    lines: tuple[SummaryLine, ...]
    sheets: tuple[Sheet, ...] = ()
    #: Kontrole przed wysłaniem — DL widzi je w oknie, plik i tak powstaje.
    checks: tuple[str, ...] = ()
    #: Gotowy plik generatora z własnym szablonem (np. arkusze BNP).
    file_bytes: Optional[bytes] = None
    file_name: Optional[str] = None


Loader = Callable[[AsyncSession, ReportContext], Awaitable[ReportData]]


@dataclass(frozen=True)
class Generator:
    key: str
    label: str
    description: str
    rhythms: tuple[str, ...]
    loader: Loader
    #: Plik ma kwoty — wymaga „Stawki i kwoty: podgląd”.
    needs_amounts: bool = False
    #: Plik ma stawki do klienta (``user_can_view_client_rate``).
    needs_client_rate: bool = False
    params: tuple[ParamField, ...] = field(default_factory=tuple)
    #: Arkusz, którego pierwsze wiersze okno pobrania pokazuje w podglądzie.
    preview_sheet: Optional[str] = None


_REGISTRY: dict[str, Generator] = {}


def register(generator: Generator) -> Generator:
    if generator.key in _REGISTRY:
        raise RuntimeError(f"Generator {generator.key} zarejestrowany dwa razy")
    _REGISTRY[generator.key] = generator
    return generator


def get_generator(key: Optional[str]) -> Optional[Generator]:
    _ensure_loaded()
    return _REGISTRY.get(key or "")


def all_generators() -> tuple[Generator, ...]:
    _ensure_loaded()
    return tuple(sorted(_REGISTRY.values(), key=lambda g: g.label))


def _ensure_loaded() -> None:
    # Moduły generatorów rejestrują się przy imporcie; import leniwy, bo
    # generator BNP sięga do modułu trasy, który importuje ten rejestr.
    from app.services.client_reports import generators  # noqa: F401


def clean_params(generator: Generator, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Zostawia tylko znane pola i sprawdza ich typy; reszta odpada."""
    raw = raw or {}
    out: dict[str, Any] = {}
    for spec in generator.params:
        if spec.key not in raw:
            continue
        value = raw[spec.key]
        if spec.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"„{spec.label}”: tak albo nie.")
        elif spec.kind == "text":
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError(f"„{spec.label}”: tekst do 200 znaków.")
        elif spec.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"„{spec.label}”: liczba.")
        elif spec.kind == "tiers":
            value = _clean_tiers(spec, value)
        out[spec.key] = value
    return out


def _clean_tiers(spec: ParamField, value: Any) -> list[dict[str, float | None]]:
    """Progi rabatu (przykład z fikcyjnymi liczbami):
    ``[{"up_to": 1000000, "rate": 1}, {"up_to": null, "rate": 2}]``.
    """
    if not isinstance(value, list) or not 1 <= len(value) <= 6:
        raise ValueError(f"„{spec.label}”: od 1 do 6 progów.")
    tiers: list[dict[str, float | None]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"„{spec.label}”: zły próg.")
        up_to, rate = item.get("up_to"), item.get("rate")
        if up_to is not None and (
            isinstance(up_to, bool) or not isinstance(up_to, (int, float)) or up_to <= 0
        ):
            raise ValueError(f"„{spec.label}”: górna granica progu musi być dodatnia.")
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not 0 <= rate <= 100
        ):
            raise ValueError(f"„{spec.label}”: stawka rabatu od 0 do 100%.")
        tiers.append(
            {"up_to": float(up_to) if up_to is not None else None, "rate": float(rate)}
        )
    return tiers


def param(ctx: ReportContext, generator: Generator, key: str) -> Any:
    for spec in generator.params:
        if spec.key == key:
            return ctx.params.get(key, spec.default)
    raise KeyError(key)


def file_slug(text: str, limit: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")
    return (slug or "raport")[:limit]


def report_file_name(client_name: str, report_name: str, period: Period) -> str:
    return f"{file_slug(client_name, 30)}_{file_slug(report_name)}_{period.key}.xlsx"


def format_amount(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.2f}".replace(",", " ").replace(".", ",")


def build_tabular_workbook(sheets: Sequence[Sheet], title: str) -> bytes:
    """Prosty skoroszyt: nagłówek, opcjonalna uwaga, wiersze przez ``safe_row``."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from app.core.export_safety import safe_row

    book = Workbook()
    book.remove(book.active)
    for sheet in sheets or (Sheet("Raport", ("Brak danych",), ()),):
        ws = book.create_sheet(sheet.name[:31])
        ws.append(safe_row([title]))
        ws["A1"].font = Font(bold=True, size=12)
        start = 3
        if sheet.note:
            ws.append(safe_row([sheet.note]))
            ws["A2"].font = Font(italic=True)
        ws.append([])
        ws.append(safe_row(sheet.headers))
        header_row = start + (1 if sheet.note else 0)
        fill = PatternFill("solid", fgColor="E7EDF3")
        for index in range(1, len(sheet.headers) + 1):
            cell = ws.cell(row=header_row, column=index)
            cell.font = Font(bold=True)
            cell.fill = fill
        for row in sheet.rows:
            ws.append(safe_row(row))
        for index in range(1, len(sheet.headers) + 1):
            width = sheet.widths[index - 1] if index - 1 < len(sheet.widths) else 16
            ws.column_dimensions[get_column_letter(index)].width = width
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()
