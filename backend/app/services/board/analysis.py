"""Analiza finansowa dla Rady (R4): wskaźniki, zdolność kredytowa, wycena.

Wejście: pola sprawozdania rocznego (``statements.FIELDS``) z e-Sprawozdania,
wpisu ręcznego albo księgi NEXUSA. Wynik jest orientacyjny — to nie jest
ocena banku ani wycena biegłego; Rada widzi założenia obok liczb.

Założenia (do zmiany suwakami w interfejsie, tu wartości domyślne):

* **zdolność kredytowa** — bank finansujący spółkę usługową bez majątku
  zwykle dopuszcza dług netto do ok. 3× EBITDA; wolny limit = 3× EBITDA
  − dług netto. Faktoring: do 85% należności z tytułu dostaw.
* **wycena** — EV = EBITDA × mnożnik; wartość kapitału = EV − dług netto.
  Inwestor finansowy (fundusz) płaci mniej (domyślnie 6×, zakres 4–8×),
  inwestor branżowy z synergiami więcej (8×, zakres 6–11×). Kontrola:
  EV / przychody, bo w body leasingu marża jest niska i mnożnik EBITDA
  może zawyżyć wartość przy jednorazowo dobrym roku.
"""

from __future__ import annotations

from typing import Any, Optional

DEBT_TO_EBITDA = 3.0
FACTORING_SHARE = 0.85
FINANCIAL_MULTIPLE = 6.0
FINANCIAL_RANGE = (4.0, 8.0)
STRATEGIC_MULTIPLE = 8.0
STRATEGIC_RANGE = (6.0, 11.0)

#: Wskaźnik → (etykieta, wzór, dolna granica „zdrowa”, górna granica, kierunek).
RATIO_NORMS: dict[str, dict[str, Any]] = {
    "current_ratio": {
        "label": "Płynność bieżąca",
        "formula": "aktywa obrotowe / zobowiązania krótkoterminowe",
        "good": [1.2, 2.0],
    },
    "quick_ratio": {
        "label": "Płynność szybka",
        "formula": "(aktywa obrotowe − zapasy − RMK) / zobowiązania krótkoterminowe",
        "good": [1.0, 1.5],
    },
    "cash_ratio": {
        "label": "Płynność gotówkowa",
        "formula": "środki pieniężne / zobowiązania krótkoterminowe",
        "good": [0.2, 0.5],
    },
    "debt_ratio": {
        "label": "Zadłużenie ogólne",
        "formula": "(pasywa − kapitał własny) / aktywa",
        "good": [0.0, 0.6],
    },
    "equity_ratio": {
        "label": "Udział kapitału własnego",
        "formula": "kapitał własny / aktywa",
        "good": [0.4, 1.0],
    },
    "net_debt_ebitda": {
        "label": "Dług netto / EBITDA",
        "formula": "(kredyty, pożyczki, leasing − gotówka) / EBITDA",
        "good": [-100.0, 3.0],
    },
    "dso": {
        "label": "Rotacja należności (dni)",
        "formula": "należności z tytułu dostaw / przychody × 365",
        "good": [0.0, 60.0],
    },
    "dpo": {
        "label": "Rotacja zobowiązań (dni)",
        "formula": "zobowiązania z tytułu dostaw / koszty operacyjne × 365",
        "good": [0.0, 60.0],
    },
    "ebitda_margin": {
        "label": "Marża EBITDA",
        "formula": "EBITDA / przychody",
        "good": [0.05, 1.0],
    },
    "net_margin": {
        "label": "Marża netto",
        "formula": "zysk netto / przychody",
        "good": [0.03, 1.0],
    },
    "roe": {
        "label": "ROE",
        "formula": "zysk netto / kapitał własny",
        "good": [0.1, 10.0],
    },
    "roa": {
        "label": "ROA",
        "formula": "zysk netto / aktywa",
        "good": [0.05, 10.0],
    },
}


def _ratio(
    num: Optional[float], den: Optional[float], digits: int = 2
) -> Optional[float]:
    if num is None or not den:
        return None
    return round(num / den, digits)


def _sum(*values: Optional[float]) -> Optional[float]:
    if all(value is None for value in values):
        return None
    return round(sum(value or 0.0 for value in values), 2)


def metrics(v: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    """Wskaźniki roku z pól sprawozdania (brak pola = brak wskaźnika)."""

    ebitda = (
        _sum(v.get("operating_profit"), v.get("depreciation"))
        if v.get("operating_profit") is not None
        else None
    )
    financial_debt = _sum(
        v.get("lt_loans"),
        v.get("lt_other_financial"),
        v.get("st_loans"),
        v.get("st_other_financial"),
    )
    cash = v.get("cash")
    net_debt = (
        round((financial_debt or 0.0) - (cash or 0.0), 2)
        if financial_debt is not None or cash is not None
        else None
    )
    st = v.get("st_liabilities")
    current = v.get("current_assets")
    quick_base = (
        round(
            current - (v.get("inventories") or 0.0) - (v.get("prepayments") or 0.0), 2
        )
        if current is not None
        else None
    )
    assets = v.get("total_assets")
    equity = v.get("equity")
    revenue = v.get("revenue")
    liabilities = (
        round(assets - equity, 2) if assets is not None and equity is not None else None
    )

    def days(num: Optional[float], den: Optional[float]) -> Optional[float]:
        value = _ratio(num, den, 4)
        return None if value is None else round(value * 365, 0)

    return {
        "ebitda": ebitda,
        "financial_debt": financial_debt,
        "net_debt": net_debt,
        "current_ratio": _ratio(current, st),
        "quick_ratio": _ratio(quick_base, st),
        "cash_ratio": _ratio(cash, st),
        "debt_ratio": _ratio(liabilities, assets),
        "equity_ratio": _ratio(equity, assets),
        "net_debt_ebitda": _ratio(net_debt, ebitda) if ebitda and ebitda > 0 else None,
        "dso": days(v.get("trade_receivables"), revenue),
        "dpo": days(v.get("trade_payables"), v.get("operating_costs")),
        "ebitda_margin": _ratio(ebitda, revenue, 4),
        "net_margin": _ratio(v.get("net_profit"), revenue, 4),
        "roe": _ratio(v.get("net_profit"), equity, 4)
        if equity and equity > 0
        else None,
        "roa": _ratio(v.get("net_profit"), assets, 4),
    }


def credit(
    v: dict[str, Optional[float]], m: dict[str, Optional[float]]
) -> dict[str, Any]:
    """Zdolność kredytowa przy domyślnych założeniach (interfejs je zmienia)."""

    ebitda = m.get("ebitda")
    net_debt = m.get("net_debt") or 0.0
    max_debt = round(DEBT_TO_EBITDA * ebitda, 2) if ebitda and ebitda > 0 else None
    receivables = v.get("trade_receivables")
    return {
        "debt_to_ebitda": DEBT_TO_EBITDA,
        "max_net_debt": max_debt,
        "headroom": round(max_debt - net_debt, 2) if max_debt is not None else None,
        "factoring_share": FACTORING_SHARE,
        "factoring_limit": round(receivables * FACTORING_SHARE, 2)
        if receivables
        else None,
    }


def valuation(
    v: dict[str, Optional[float]], m: dict[str, Optional[float]]
) -> dict[str, Any]:
    ebitda = m.get("ebitda")
    net_debt = m.get("net_debt") or 0.0
    revenue = v.get("revenue")

    def investor(multiple: float, low: float, high: float) -> dict[str, Any]:
        if not ebitda or ebitda <= 0:
            return {"multiple": multiple, "range": [low, high], "ev": None}
        ev = round(ebitda * multiple, 2)
        return {
            "multiple": multiple,
            "range": [low, high],
            "ev": ev,
            "equity": round(ev - net_debt, 2),
            "equity_low": round(ebitda * low - net_debt, 2),
            "equity_high": round(ebitda * high - net_debt, 2),
            "ev_to_revenue": _ratio(ev, revenue),
        }

    return {
        "financial": investor(FINANCIAL_MULTIPLE, *FINANCIAL_RANGE),
        "strategic": investor(STRATEGIC_MULTIPLE, *STRATEGIC_RANGE),
    }


def growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or not previous:
        return None
    return round(100 * (current - previous) / abs(previous), 1)


def analyse_years(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wiersze lat (rosnąco) z wskaźnikami i dynamiką rok do roku."""

    ordered = sorted(rows, key=lambda row: row["year"])
    out: list[dict[str, Any]] = []
    previous: Optional[dict[str, Any]] = None
    for row in ordered:
        v = row["amounts"]
        m = metrics(v)
        entry = {
            **row,
            "metrics": m,
            "credit": credit(v, m),
            "valuation": valuation(v, m),
            "growth": {
                "revenue": growth(
                    v.get("revenue"), (previous or {}).get("amounts", {}).get("revenue")
                ),
                "ebitda": growth(
                    m.get("ebitda"), (previous or {}).get("metrics", {}).get("ebitda")
                ),
                "net_profit": growth(
                    v.get("net_profit"),
                    (previous or {}).get("amounts", {}).get("net_profit"),
                ),
            },
        }
        out.append(entry)
        previous = entry
    return out
