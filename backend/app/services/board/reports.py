"""Raporty PDF dla Rady (R7): miesięczny, roczny i budżet.

Uwagi Rady z 18.11.2026: „pobierz raport — archiwum raportów + nowe
comiesięczne, roczne, budżety”. Raport liczy się z bieżących danych przy
pobraniu (te same funkcje co pulpit, budżet i zakładka Firma); admin może go
zapisać w archiwum (``board_reports``), żeby wersja omawiana na posiedzeniu
nie zmieniała się, gdy spłyną spóźnione faktury kosztowe.

Bez nazwisk konsultantów — klient, rola i powód zejścia.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import escape
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_document import BoardCashPosition
from app.services.board import budget, financials, outlook, people, summary

MONTHS = (
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
ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")
KIND_LABELS = {
    "monthly": "Raport miesięczny",
    "annual": "Raport roczny",
    "budget": "Budżet i prognoza",
}
_TZ = ZoneInfo("Europe/Warsaw")


class ReportError(ValueError):
    """Okres raportu poza danymi (komunikat dla użytkownika)."""


def file_name(kind: str, year: int, month: Optional[int]) -> str:
    if kind == "monthly" and month:
        return f"Rada-raport-{year}-{month:02d}.pdf"
    return f"Rada-{'raport' if kind == 'annual' else 'budzet'}-{year}.pdf"


def title(kind: str, year: int, month: Optional[int]) -> str:
    if kind == "monthly" and month:
        return f"{KIND_LABELS[kind]} — {MONTHS[month - 1]} {year}"
    return f"{KIND_LABELS[kind]} {year}"


def check_period(kind: str, year: int, month: Optional[int], today: date) -> None:
    if kind not in KIND_LABELS:
        raise ReportError("Nieznany rodzaj raportu.")
    if not 2020 <= year <= today.year + 1:
        raise ReportError("Rok poza zakresem danych.")
    if kind == "monthly":
        if month is None or not 1 <= month <= 12:
            raise ReportError("Raport miesięczny wymaga miesiąca.")
        if (year, month) > (today.year, today.month):
            raise ReportError("Ten miesiąc jeszcze się nie zaczął.")
    elif month is not None:
        raise ReportError("Miesiąc podaje się tylko w raporcie miesięcznym.")
    if kind == "annual" and year > today.year:
        raise ReportError("Ten rok jeszcze się nie zaczął.")


def month_figures(
    rows: list[summary.MonthRow], year: int, month: int
) -> dict[str, Any]:
    only = [r for r in rows if r.year == year and r.month == month]
    return summary.year_figures(only, year, 12)


# ── formatowanie ─────────────────────────────────────────────────────────────


def mln(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f}%".replace(".", ",")


def delta_pct(current: Optional[float], base: Optional[float]) -> str:
    if current is None or not base:
        return "—"
    change = 100 * (current - base) / abs(base)
    return f"{'+' if change >= 0 else ''}{change:.1f}%".replace(".", ",")


def _table(
    head: list[str],
    rows: list[list[str]],
    strong: frozenset[int] = frozenset(),
    left: frozenset[int] = frozenset({0}),
) -> str:
    """Tabela raportu; kolumny ``left`` (tekst) do lewej, reszta (kwoty) do prawej."""

    def cls(col: int) -> str:
        return " class='l'" if col in left else ""

    cells = "".join(f"<th{cls(c)}>{escape(h)}</th>" for c, h in enumerate(head))
    body = "".join(
        "<tr"
        + (" class='strong'" if i in strong else "")
        + ">"
        + "".join(f"<td{cls(c)}>{escape(v)}</td>" for c, v in enumerate(row))
        + "</tr>"
        for i, row in enumerate(rows)
    )
    return f"<table><thead><tr>{cells}</tr></thead><tbody>{body}</tbody></table>"


def _figures_rows(columns: list[dict[str, Any]]) -> list[list[str]]:
    def line(label: str, key: str, fmt=mln) -> list[str]:
        return [label] + [fmt(c.get(key)) for c in columns]

    return [
        line("Sprzedaż", "sales"),
        line("Koszty kontraktorów", "contractors"),
        line("Marża na kontraktorach", "contractor_margin"),
        line("Marża na kontraktorach %", "contractor_margin_pct", pct),
        line("Koszty biurowe", "office"),
        line("Zysk brutto", "result"),
        line("Zysk brutto %", "result_pct", pct),
    ]


def _page(heading: str, generated: datetime, sections: list[str]) -> str:
    stamp = generated.astimezone(_TZ).strftime("%d.%m.%Y %H:%M")
    return (
        "<!doctype html><html lang='pl'><head><meta charset='utf-8'><style>"
        "@page{size:A4;margin:16mm 14mm 18mm;"
        "@bottom-right{content:'str. ' counter(page) ' z ' counter(pages);"
        "font-size:8pt;color:#6b7280}}"
        "body{font-family:'DejaVu Sans',Arial,sans-serif;font-size:9.5pt;color:#111827}"
        "h1{font-size:15pt;margin:0 0 2pt}h2{font-size:11pt;margin:14pt 0 5pt;"
        "border-bottom:1px solid #d1d5db;padding-bottom:2pt}"
        ".meta{color:#6b7280;font-size:8.5pt;margin:0 0 8pt}"
        "table{width:100%;border-collapse:collapse;margin:2pt 0 4pt}"
        "th,td{border:1px solid #d1d5db;padding:3pt 5pt;text-align:right}"
        "th.l,td.l{text-align:left}"
        "th{background:#f3f4f6;font-weight:600;font-size:8.5pt}"
        "tr.strong td{font-weight:700}"
        ".note{color:#4b5563;font-size:8pt;margin:3pt 0}"
        "ul{margin:2pt 0;padding-left:14pt}li{margin:1pt 0}"
        "</style></head><body>"
        f"<h1>{escape(heading)}</h1>"
        f"<p class='meta'>B2B.net S.A. · dla Rady Nadzorczej · wygenerowano {stamp} "
        "z NEXUSA · kwoty w mln zł netto</p>" + "".join(sections) + "</body></html>"
    )


SOURCE_NOTE = (
    "<p class='note'>Faktury z archiwum eBI24 według daty sprzedaży. Koszty "
    "kontraktorów = faktury z folderu „Kontraktorzy”, koszty biurowe = pozostałe "
    "faktury kosztowe. Zysk brutto nie obejmuje płac UoP, ZUS i amortyzacji — "
    "nie zastępuje RZiS.</p>"
)


def _exits_section(
    view: dict[str, Any], heading: str, *, with_items: bool = True
) -> str:
    ex = view["exits"]
    flows = view["flows"]
    contractors = view["contractors"]
    parts = [
        f"<h2>{escape(heading)}</h2>",
        _table(
            ["", "Liczba"],
            [
                ["Kontraktorzy pracujący na koniec okresu", str(contractors["active"])],
                ["Klienci z kontraktorami", str(contractors["clients"])],
                ["Placementy", str(view["placements"]["count"])],
                ["Rozpoczęli pracę", str(flows["starts"])],
                ["Zejścia", str(flows["ends"])],
                ["w tym rezygnacje konsultantów", str(flows["resignations"])],
            ],
        ),
    ]
    if contractors["by_client"]:
        parts.append(
            _table(
                ["Klient", "Kontraktorzy"],
                [
                    [row["client"], str(row["count"])]
                    for row in contractors["by_client"]
                ],
            )
        )
    if ex["items"]:
        parts.append(
            "<p class='note'>Powody zejść: "
            + escape(", ".join(f"{r['label']} {r['count']}" for r in ex["by_reason"]))
            + "</p>"
        )
        if not with_items:
            return "".join(parts)
        parts.append(
            _table(
                [
                    "Koniec",
                    "Klient",
                    "Powód",
                    "Kto zakończył",
                    "Czego się nauczyliśmy",
                ],
                [
                    [
                        date.fromisoformat(item["ended_on"]).strftime("%d.%m.%Y"),
                        item["client"],
                        item["reason_label"],
                        item["party"] or "—",
                        item["lessons"] or "—",
                    ]
                    for item in ex["items"]
                ],
                left=frozenset({0, 1, 2, 3, 4}),
            )
        )
    return "".join(parts)


async def _people(db: AsyncSession, first: date, last: date) -> dict[str, Any]:
    span = last - first
    prev_last = first - timedelta(days=1)
    prev_first = prev_last - span
    return await people.people_view(
        db,
        window=(first, last),
        previous=(prev_first, prev_last),
        bounds=(_start(first), _start(last + timedelta(days=1))),
        previous_bounds=(_start(prev_first), _start(prev_last + timedelta(days=1))),
    )


def _start(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=_TZ)


async def _cash_on(db: AsyncSession, day: date) -> Optional[BoardCashPosition]:
    return (
        await db.execute(
            select(BoardCashPosition)
            .where(BoardCashPosition.as_of <= day)
            .order_by(BoardCashPosition.as_of.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def monthly_html(
    db: AsyncSession, year: int, month: int, today: date, now: datetime
) -> str:
    rows = await summary.month_rows(db, year - 1)
    first, last = budget.month_bounds(year, month)
    last = min(last, today)
    complete = (year, month) in summary.complete_cost_months(rows)
    sales_complete = (year, month) in summary.complete_sales_months(rows) and (
        year,
        month,
    ) < (today.year, today.month)
    plans = (await summary.budget_sales(db, [year])).get(str(year), [None] * 12)
    plan_month = plans[month - 1]
    plan_ytd_values = [p for p in plans[:month] if p is not None]
    plan_ytd = round(sum(plan_ytd_values), 2) if plan_ytd_values else None
    current = month_figures(rows, year, month)
    previous = month_figures(rows, year - 1, month)
    ytd = summary.year_figures(rows, year, month)
    ytd_prev = summary.year_figures(rows, year - 1, month)
    sections = [
        "<h2>Wynik miesiąca i narastająco</h2>",
        _table(
            [
                "",
                f"{ROMAN[month - 1]} {year}",
                f"{ROMAN[month - 1]} {year - 1}",
                f"I–{ROMAN[month - 1]} {year}",
                f"I–{ROMAN[month - 1]} {year - 1}",
            ],
            _figures_rows([current, previous, ytd, ytd_prev]),
            strong=frozenset({5}),
        ),
        SOURCE_NOTE,
    ]
    if not sales_complete:
        sections.append(
            "<p class='note'><b>Faktury sprzedaży za ten miesiąc nie są jeszcze "
            "kompletne</b> (wystawia się je na początku następnego miesiąca) — "
            "sprzedaż i odchylenia są niepełne.</p>"
        )
    elif not complete:
        sections.append(
            "<p class='note'>Koszty tego miesiąca jeszcze spływają — zysk brutto "
            "jest zawyżony do czasu zaksięgowania wszystkich faktur kosztowych.</p>"
        )
    sections.append("<h2>Sprzedaż wobec budżetu i roku poprzedniego</h2>")
    sections.append(
        _table(
            ["", "Wykonanie", "Budżet", "Odchylenie od budżetu", f"Wobec {year - 1}"],
            [
                [
                    f"{ROMAN[month - 1]} {year}",
                    mln(current["sales"]),
                    mln(plan_month),
                    delta_pct(current["sales"], plan_month),
                    delta_pct(current["sales"], previous["sales"]),
                ],
                [
                    f"I–{ROMAN[month - 1]} {year}",
                    mln(ytd["sales"]),
                    mln(plan_ytd),
                    delta_pct(ytd["sales"], plan_ytd),
                    delta_pct(ytd["sales"], ytd_prev["sales"]),
                ],
            ],
        )
    )
    cash = await _cash_on(db, last)
    if cash is not None:
        sections.append(
            f"<p>Stan gotówki na {cash.as_of.strftime('%d.%m.%Y')}: "
            f"<b>{mln(float(cash.amount) / 1_000_000)} mln zł</b>"
            + (f" ({escape(cash.note)})" if cash.note else "")
            + ".</p>"
        )
    clients = await summary.top_clients(db, first, budget.month_bounds(year, month)[1])
    if clients:
        sections.append("<h2>Najwięksi klienci miesiąca</h2>")
        sections.append(
            _table(
                ["Klient", "Sprzedaż", "Udział"],
                [[c["name"], mln(c["sales"]), pct(c["share"])] for c in clients],
            )
        )
    sections.append(
        _exits_section(await _people(db, first, last), "Kontraktorzy w miesiącu")
    )
    return _page(title("monthly", year, month), now, sections)


async def annual_html(db: AsyncSession, year: int, today: date, now: datetime) -> str:
    rows = await summary.month_rows(db, year - 1)
    last_month = 12 if year < today.year else today.month
    plans = (await summary.budget_sales(db, [year])).get(str(year), [None] * 12)
    months = [month_figures(rows, year, m) for m in range(1, last_month + 1)]
    total = summary.year_figures(rows, year, last_month)
    total_prev = summary.year_figures(rows, year - 1, last_month)
    head = [""] + [ROMAN[m] for m in range(last_month)] + ["Razem", f"{year - 1}"]
    lines = _figures_rows(months + [total, total_prev])
    lines.insert(
        1,
        ["Budżet sprzedaży"]
        + [mln(plans[m]) for m in range(last_month)]
        + [mln(sum(p for p in plans[:last_month] if p is not None) or None), "—"],
    )
    sections = [
        "<h2>Miesiące</h2>",
        _table(head, lines, strong=frozenset({6})),
        SOURCE_NOTE,
    ]
    view = await financials.analysis_view(db, today)
    statement = next((y for y in view["years"] if y["year"] == year), None)
    if statement is not None:
        a, m = statement["amounts"], statement["metrics"]

        def p(value: Optional[float]) -> str:
            return mln(None if value is None else value / 1_000_000)

        sections.append(f"<h2>Sprawozdanie finansowe {year}</h2>")
        sections.append(
            _table(
                ["Pozycja", "mln zł"],
                [
                    ["Przychody netto ze sprzedaży", p(a.get("revenue"))],
                    ["EBITDA", p(m.get("ebitda"))],
                    ["Zysk netto", p(a.get("net_profit"))],
                    ["Środki pieniężne", p(a.get("cash"))],
                    ["Dług netto", p(m.get("net_debt"))],
                    ["Kapitał własny", p(a.get("equity"))],
                ],
            )
        )
        sections.append(
            f"<p class='note'>Źródło: {escape(statement['source_label'])}.</p>"
        )
    first = date(year, 1, 1)
    last = date(year, 12, 31) if year < today.year else today
    sections.append(
        _exits_section(
            await _people(db, first, last), "Kontraktorzy w roku", with_items=False
        )
    )
    return _page(title("annual", year, None), now, sections)


async def budget_html(db: AsyncSession, year: int, today: date, now: datetime) -> str:
    view = await budget.budget_view(db, year, today)
    real = view.get("realization")
    head = [
        "Miesiąc",
        "Budżet sprzedaży",
        "Wykonanie / prognoza",
        "Rodzaj",
        "Odchylenie",
    ]
    lines = []
    for m in view["months"]:
        value = (
            m["sales"]
            if m["kind"] == "actual"
            else (None if real is None else round((m["potential"] or 0) * real, 2))
        )
        lines.append(
            [
                ROMAN[m["month"] - 1],
                mln(m["plan_sales"]),
                mln(value),
                "wykonanie" if m["kind"] == "actual" else "prognoza bez przedłużeń",
                delta_pct(value, m["plan_sales"]),
            ]
        )
    end = outlook.year_end(view)
    status = view["budget"]["status"] if view["budget"] else None
    sections = [
        "<p>"
        + (
            "Budżet przyjęty uchwałą Rady."
            if status == "adopted"
            else "Budżet w wersji roboczej."
            if status == "draft"
            else "Budżetu na ten rok nie wpisano — tabela pokazuje samo wykonanie i prognozę."
        )
        + "</p>",
        "<h2>Sprzedaż: budżet, wykonanie i prognoza</h2>",
        _table(head, lines, left=frozenset({0, 3})),
        "<h2>Symulacja roku</h2>",
        _table(
            ["", "Bez przedłużeń", "Wszystkie przedłużone"],
            [
                [
                    "Sprzedaż w roku",
                    mln(end.get("sales_low")),
                    mln(end.get("sales_high")),
                ],
                [
                    "Zysk brutto",
                    mln(end.get("profit_low")),
                    mln(end.get("profit_high")),
                ],
                [
                    "Budżet sprzedaży",
                    mln(end.get("plan_sales")),
                    mln(end.get("plan_sales")),
                ],
            ],
        ),
        "<p class='note'>Prognoza: potencjał aktywnych kontraktów (stawka klienta × dni "
        "robocze) × realizacja z ostatnich 3 pełnych miesięcy"
        + (f" ({pct(100 * real)})" if real is not None else "")
        + ". Zysk brutto = sprzedaż × (1 − udział kosztów z faktur w 12 miesiącach"
        " kroczących).</p>",
        SOURCE_NOTE,
    ]
    return _page(title("budget", year, None), now, sections)


async def render_html(
    db: AsyncSession,
    kind: str,
    year: int,
    month: Optional[int],
    today: date,
    now: datetime,
) -> str:
    check_period(kind, year, month, today)
    if kind == "monthly":
        return await monthly_html(db, year, month or 1, today, now)
    if kind == "annual":
        return await annual_html(db, year, today, now)
    return await budget_html(db, year, today, now)


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()
