"""Jeden miesiąc roboczy (168 h = 21 MD × 8 h) — strażnik przeciw powrotowi
gołych liczb 160/176/22 w przeliczeniach stawek na kwoty miesięczne.

Audyt statystyk z 22.09.2026 zmierzył na produkcji, że ta sama stawka
godzinowa dawała MRR różny o ~10%: kontrakty liczyły 160 h (domyślne) albo
176 h (przeliczone z MD), stawka dzienna — 22 MD, a normalizacja budżetu —
168 h. Decyzja: jedna stała w ``app.core.work_time`` (lustro na froncie
w ``frontend/src/lib/work-time.ts``).

Test czyta ŹRÓDŁO modułów pieniędzy (tokenizer — komentarze i docstringi
z historią zmiany są dozwolone) i odrzuca liczbę 160/176/22/168/21 stojącą
przy operatorze mnożenia/dzielenia, w ``or``-fallbacku albo jako wartość
domyślną/przypisanie (``= 160``) oraz ``Decimal("22")``. Inne użycia tych
liczb (szerokość kolumny eksportu, limit znaków) przechodzą.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

from app.core import work_time
from app.services import order_rate_snapshots, rate_normalization

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# Moduły, które przeliczają stawki na kwoty miesięczne albo między jednostkami.
# Nowy moduł pieniędzy = dopisz go tutaj.
MONEY_MODULES = (
    "app/models/contract.py",
    "app/models/client_order.py",
    "app/schemas/contract.py",
    "app/schemas/client_order.py",
    "app/api/reports.py",
    "app/api/contract_analytics.py",
    "app/api/clients.py",
    "app/api/client_orders.py",
    "app/api/client_order_groups.py",
    "app/api/contracts.py",
    "app/analytics/metrics.py",
    "app/services/order_rate_snapshots.py",
    "app/services/contract_order_sync.py",
    "app/services/contract_order_sync_repair.py",
    "app/services/contract_hourly_rate_repair.py",
    "app/services/contract_rates.py",
    "app/services/insights_board_money.py",
    "app/services/insights_clients.py",
    "app/services/rate_normalization.py",
    "app/services/client_order_lines.py",
    "app/services/order_group_materializer.py",
    "app/services/executive_contracts.py",
    "app/services/ezdrowie_md_seed.py",
    "app/services/order_mail_apply.py",
    "app/services/b2b_contract_generator/render_context.py",
)

FORBIDDEN = {"160", "176", "22", "168", "21"}
_ARITHMETIC = {"*", "/", "//", "*=", "/=", "or", "="}
_SKIP = {
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.COMMENT,
    tokenize.INDENT,
    tokenize.DEDENT,
}


def _offenders(source: str) -> list[str]:
    tokens = [
        tok
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type not in _SKIP
    ]
    found: list[str] = []
    for index, tok in enumerate(tokens):
        prev = tokens[index - 1].string if index else ""
        nxt = tokens[index + 1].string if index + 1 < len(tokens) else ""
        if tok.type == tokenize.NUMBER and tok.string in FORBIDDEN:
            if prev in _ARITHMETIC or nxt in {"*", "/", "//"}:
                found.append(f"{tok.start[0]}: {tok.line.strip()}")
        elif (
            tok.type == tokenize.STRING
            and tok.string.strip("\"'") in FORBIDDEN
            and prev == "("
            and index >= 2
            and tokens[index - 2].string == "Decimal"
        ):
            found.append(f"{tok.start[0]}: {tok.line.strip()}")
    return found


def test_work_time_constants_are_one_consistent_month() -> None:
    assert work_time.HOURS_PER_MD == 8
    assert work_time.MD_PER_MONTH == 21
    assert work_time.HOURS_PER_MONTH == 168
    assert work_time.HOURS_PER_MONTH == work_time.MD_PER_MONTH * work_time.HOURS_PER_MD


def test_every_conversion_reads_the_same_constant() -> None:
    assert rate_normalization.MONTHLY_HOURS == work_time.HOURS_PER_MONTH
    assert rate_normalization.MONTHLY_DAYS == work_time.MD_PER_MONTH
    assert order_rate_snapshots.HOURS_PER_DAY == work_time.HOURS_PER_MD
    assert order_rate_snapshots.DAYS_PER_MONTH == work_time.MD_PER_MONTH


def test_model_and_schema_defaults_are_the_standard_month() -> None:
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract
    from app.schemas.contract import ContractCreate

    for model in (Contract, ClientOrder):
        column = model.__table__.c.billing_hours_per_month
        assert column.default.arg == work_time.HOURS_PER_MONTH
        assert column.server_default.arg == str(work_time.HOURS_PER_MONTH)
    assert (
        ContractCreate.model_fields["billing_hours_per_month"].default
        == work_time.HOURS_PER_MONTH
    )


@pytest.mark.parametrize("relative", MONEY_MODULES)
def test_money_modules_have_no_bare_month_literals(relative: str) -> None:
    path = BACKEND / relative
    assert path.exists(), f"brak modułu {relative} — zaktualizuj listę"
    offenders = _offenders(path.read_text(encoding="utf-8"))
    assert not offenders, (
        f"{relative}: gołe liczby miesiąca roboczego — użyj app.core.work_time:\n"
        + "\n".join(offenders)
    )


def test_guard_catches_the_patterns_it_was_written_for() -> None:
    """Strażnik, który nie potrafi paść, nic nie sprawdza."""
    for bad in (
        "x = rate * 22\n",
        "x = rate * (hours or 160)\n",
        "def f(hours: int = 160): pass\n",
        "HOURS = 176\n",
        'D = Decimal("22")\n',
        "x = amount / 168\n",
    ):
        assert _offenders(bad), bad
    for ok in (
        '("Rodzaj zamówienia", "order_kind", 22),\n',
        "# dawniej rate * 22\n",
        'x = "rate * 160"\n',
        "limit = max_length(160)\n",
    ):
        assert not _offenders(ok), ok


def test_frontend_mirror_uses_the_same_numbers() -> None:
    source = (REPO / "frontend/src/lib/work-time.ts").read_text(encoding="utf-8")
    assert re.search(r"export const HOURS_PER_MD = 8;", source)
    assert re.search(r"export const MD_PER_MONTH = 21;", source)
    assert re.search(
        r"export const HOURS_PER_MONTH = MD_PER_MONTH \* HOURS_PER_MD;", source
    )
