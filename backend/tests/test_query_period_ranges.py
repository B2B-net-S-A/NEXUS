"""Miesiąc i rok w parametrach zapytań: rok spoza 2000–2100 to 422, nie 500.

Fuzzing API Schemathesisem na stagingu (27.11.2026) znalazł 500 na kilku
trasach Finansów i HR dla ``month=0000-01`` i ``year=0``: wzorzec
``^[0-9]{4}-…`` przepuszczał rok 0, a ``date(0, 1, 1)`` rzucał
``ValueError``. Ten sam wzorzec był skopiowany w kilku modułach, dlatego
strażnik sprawdza cały schemat API, nie jedną trasę — nowa kopia starego
wzorca też go zaczerwieni. Zakres lat jak w ``finance._validate_period``.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

import pytest

from app.main import app


def _is_month_param(name: str, pattern: str | None) -> bool:
    """Parametr miesiąca RRRR-MM (``month``, ``period_month``…), nie np. konto 100-01."""
    return bool(
        pattern
        and ("month" in name or "period" in name)
        and re.fullmatch(pattern, "2026-11")
        and not re.fullmatch(pattern, "dowolny tekst")
    )


def _query_params() -> Iterator[tuple[str, str, str, dict[str, Any]]]:
    for path, ops in app.openapi()["paths"].items():
        for method, op in ops.items():
            for param in op.get("parameters", []):
                if param.get("in") != "query":
                    continue
                schema = param.get("schema", {})
                for alt in schema.get("anyOf", [schema]):
                    yield method.upper(), path, param["name"], alt


@pytest.fixture(scope="module")
def params() -> list[tuple[str, str, str, dict[str, Any]]]:
    return list(_query_params())


def test_month_patterns_reject_year_zero_and_month_13(params) -> None:
    month_patterns = [
        (m, p, n, a["pattern"])
        for m, p, n, a in params
        if _is_month_param(n, a.get("pattern"))
    ]
    assert month_patterns, "strażnik nie znalazł żadnego parametru miesiąca"
    accepting_bad = [
        f"{m} {p} ?{n}={bad}"
        for m, p, n, pattern in month_patterns
        for bad in ("0000-01", "1999-12", "2101-01", "2026-13", "2026-00")
        if re.fullmatch(pattern, bad)
    ]
    assert accepting_bad == []


def test_month_patterns_accept_range_edges(params) -> None:
    for m, p, n, a in params:
        pattern = a.get("pattern")
        if _is_month_param(n, pattern):
            for good in ("2000-01", "2026-12", "2099-12"):
                assert re.fullmatch(pattern, good), f"{m} {p} ?{n}={good}"


def test_days_off_year_is_bounded(params) -> None:
    [schema] = [
        a
        for m, p, n, a in params
        if m == "GET" and p == "/api/hr/admin/days-off" and n == "year"
        and a.get("type") == "integer"
    ]
    assert schema.get("minimum") == 2000
    assert schema.get("maximum") == 2100
