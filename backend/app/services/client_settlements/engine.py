"""Wyliczenie rozliczenia osoby za miesiąc (roadmapa E1.4–E1.5). Bez bazy.

Wejście to MD z RCP (w E1 wpisane przez Finanse, od E2 z odczytu pliku),
reguły klienta na miesiąc i stan linii zamówienia. Wyjście to MD do zejścia,
kwoty, pozycje wyliczenia, wynik kontroli i stan.

* Nadgodziny liczą się z mnożnikiem reguły ``extra.multiplier`` i w koszcie,
  i w przychodzie, i w zejściu MD (BNP: 120%).
* MD wdrożeniowe (``order.onboarding_md``) tylko dla kontraktu, który zaczął się
  w rozliczanym albo poprzednim miesiącu: konsultant fakturuje pełną ilość,
  do klienta idą za 0 zł i nie schodzą z zamówienia. Niewykorzystane przechodzą
  na kolejny miesiąc tego samego kontraktu. Odnowienie po przerwie czeka na
  odpowiedź rozliczeń (roadmapa E0.2), więc dziś pula jest na kontrakt.
* Brak linii zamówienia albo pusta pula przy ``order.no_md_holds_invoice``
  na poziomie „Blokuje” daje stan ``no_md``: plik zostaje, faktura czeka.
* Za mało MD na linii (decyzja rozliczeń i Artura z 10.11.2026): zejdzie tyle,
  ile zostało, koszt i przychód za tę część, nadwyżka ``md_over`` czeka na
  decyzję Finansów — konsultant fakturuje tylko pulę, bez obietnicy zamówienia.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    from app.services.client_settlements.rcp_checks import ProofResult

MD_Q = Decimal("0.001")
MONEY_Q = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True)
class OrderState:
    """Linia zamówienia osoby w miesiącu, stan przed zejściem za ten miesiąc."""

    order_id: int
    number: Optional[str]
    md_total: Optional[Decimal]
    md_available: Optional[Decimal]
    rate_cost: Optional[Decimal]
    rate_revenue: Optional[Decimal]


@dataclass(frozen=True)
class Inputs:
    md_regular: Optional[Decimal]
    md_extra: Optional[Decimal]
    rules: Mapping[str, Mapping[str, Any]]
    order: Optional[OrderState]
    onboarding_used_before: Decimal = ZERO
    has_report: bool = False
    #: Kontrakt zaczął się w tym albo poprzednim miesiącu (reszta MD przechodzi
    #: na kolejny). Dawny konsultant bez rozliczeń w NEXUS-ie nie jest nowy.
    onboarding_eligible: bool = True
    #: Wynik kontroli dowodu pracy (E2); ``None`` = MD bez odczytu pliku.
    proof: Optional["ProofResult"] = None


@dataclass(frozen=True)
class Result:
    status: str
    md_onboarding: Optional[Decimal]
    md_charged: Optional[Decimal]
    md_remaining_after: Optional[Decimal]
    amount_cost: Optional[Decimal]
    amount_revenue: Optional[Decimal]
    lines: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    #: Reguła „Blokuje” nie przeszła: przyjęcie wymaga poprawy pliku.
    blocking: bool = False
    #: MD (z mnożnikiem) ponad pulę zamówienia, bez zejścia i bez zapłaty.
    md_over: Optional[Decimal] = None
    #: Dane odczytu dowodu poza kontrolami (np. ``kesu`` w E6.3).
    meta: Optional[dict[str, Any]] = None


def _md(value: Decimal) -> Decimal:
    return value.quantize(MD_Q, rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def _param_decimal(
    rules: Mapping[str, Mapping[str, Any]], key: str, name: str
) -> Optional[Decimal]:
    raw = str(rules[key]["params"].get(name, "")).replace(" ", "").replace(",", ".")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value >= 0 else None


def _level(rules: Mapping[str, Mapping[str, Any]], key: str) -> str:
    return str(rules[key]["level"])


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


def _check(state: str, title: str, detail: Optional[str] = None) -> dict[str, Any]:
    return {"state": state, "title": title, "detail": detail}


def compute(inp: Inputs) -> Result:
    if inp.md_regular is None:
        return Result(
            "checking",
            None,
            None,
            None,
            None,
            None,
            [],
            [
                {
                    "title": "RCP",
                    "checks": [
                        _check(
                            "none",
                            "Czeka na liczbę MD",
                            "Odczyt RCP przyjdzie w kolejnym etapie; do tego czasu MD wpisują Finanse.",
                        )
                    ],
                },
            ],
        )

    regular = _md(inp.md_regular)
    extra = _md(inp.md_extra or ZERO)
    rules = inp.rules
    groups: list[dict[str, Any]] = []
    warn = False
    blocked = False

    proof_blocking = False
    if inp.proof is not None:
        groups.extend(
            {"title": g["title"], "checks": list(g["checks"])} for g in inp.proof.groups
        )
        warn = warn or inp.proof.warn
        proof_blocking = inp.proof.blocking
    elif inp.has_report:
        groups.append({"title": "RCP", "checks": [_check("ok", "RCP jest w NEXUS-ie")]})
    else:
        groups.append(
            {
                "title": "RCP",
                "checks": [
                    _check(
                        "warn",
                        "MD wpisane bez pliku RCP",
                        "Plik nie wpłynął ani panelem, ani mailem.",
                    )
                ],
            }
        )
        warn = True

    multiplier = Decimal("1")
    if extra > 0:
        pct = (
            _param_decimal(rules, "extra.multiplier", "pct")
            if _level(rules, "extra.multiplier") != "off"
            else None
        )
        multiplier = (pct / 100) if pct else Decimal("1")
        check = _check(
            "ok",
            f"{_fmt(extra)} MD pracy dodatkowej × {_fmt(_md(multiplier * 100))}%",
            None if inp.proof is not None else "Akceptację mailem sprawdzi odczyt RCP.",
        )
        existing = next((g for g in groups if g["title"] == "Nadgodziny"), None)
        if existing is not None:
            existing["checks"].insert(0, check)
        else:
            groups.append({"title": "Nadgodziny", "checks": [check]})
    extra_weighted = _md(extra * multiplier)

    onboarding = ZERO
    if inp.onboarding_eligible and _level(rules, "order.onboarding_md") != "off":
        allowance = _param_decimal(rules, "order.onboarding_md", "md") or ZERO
        left = max(allowance - inp.onboarding_used_before, ZERO)
        onboarding = _md(min(left, regular))
        if onboarding > 0:
            groups.append(
                {
                    "title": "MD wdrożeniowe",
                    "checks": [
                        _check(
                            "ok",
                            f"{_fmt(onboarding)} MD za 0 zł, bez zejścia z zamówienia",
                            f"Zostaje na kolejne miesiące: {_fmt(_md(left - onboarding))} MD.",
                        )
                    ],
                }
            )

    charged = _md(regular - onboarding + extra_weighted)
    order = inp.order
    order_checks: list[dict[str, Any]] = []
    remaining_after: Optional[Decimal] = None
    over = ZERO
    hold = _level(rules, "order.no_md_holds_invoice")
    if order is None:
        order_checks.append(
            _check(
                {"block": "fail", "warn": "warn"}.get(hold, "none"),
                "Brak linii zamówienia w tym miesiącu",
                "MD nie mają z czego zejść. Faktura czeka na zamówienie albo wyjątek Finansów.",
            )
        )
        blocked = blocked or hold == "block"
        warn = warn or hold == "warn"
    elif order.md_available is None:
        order_checks.append(
            _check(
                "none",
                "Zamówienie bez puli MD na osobie",
                "Zejście liczy pula zamówienia.",
            )
        )
    else:
        remaining_after = _md(order.md_available - charged)
        available = _md(max(order.md_available, ZERO))
        if remaining_after < 0 and hold != "off" and available <= 0:
            order_checks.append(
                _check(
                    "fail" if hold == "block" else "warn",
                    "Na zamówieniu nie zostało MD",
                    f"Zejść ma {_fmt(charged)} MD. Do faktury nic; decyzja Finansów.",
                )
            )
            blocked = blocked or hold == "block"
            warn = warn or hold == "warn"
            over, charged, remaining_after = charged, ZERO, ZERO
        elif remaining_after < 0 and hold != "off":
            over = _md(-remaining_after)
            order_checks.append(
                _check(
                    "warn",
                    f"Ponad zamówienie o {_fmt(over)} MD",
                    f"Zejdzie {_fmt(available)} MD (tyle zostało) i tyle idzie do faktury; "
                    "nadwyżka czeka na decyzję Finansów.",
                )
            )
            warn = True
            charged, remaining_after = available, ZERO
        else:
            order_checks.append(
                _check(
                    "ok",
                    f"Zejdzie {_fmt(charged)} MD, zostanie {_fmt(remaining_after)} MD",
                    "Zejście przy przyjęciu RCP; ponowne przyjęcie nadpisuje miesiąc.",
                )
            )
    groups.append(
        {
            "title": f"Zamówienie {order.number}"
            if order and order.number
            else "Zamówienie",
            "checks": order_checks,
        }
    )

    cost_rate = order.rate_cost if order else None
    revenue_rate = order.rate_revenue if order else None
    lines: list[dict[str, Any]] = [
        {
            "label": "Dni zwykłe",
            "md": str(regular),
            "multiplier": "1.00",
            "rate": None if cost_rate is None else str(_money(cost_rate)),
            "net": None if cost_rate is None else str(_money(regular * cost_rate)),
        },
    ]
    if extra > 0:
        lines.append(
            {
                "label": "Praca dodatkowa",
                "md": str(extra),
                "multiplier": str(multiplier.quantize(MONEY_Q)),
                "rate": None if cost_rate is None else str(_money(cost_rate)),
                "net": None
                if cost_rate is None
                else str(_money(extra * multiplier * cost_rate)),
            }
        )
    if over > 0:
        lines.append(
            {
                "label": "Ponad zamówienie, bez zapłaty",
                "md": str(-over),
                "multiplier": "1.00",
                "rate": None if cost_rate is None else str(_money(cost_rate)),
                "net": None if cost_rate is None else str(_money(-over * cost_rate)),
            }
        )
    paid_md = regular + extra * multiplier - over
    amount_cost = None if cost_rate is None else _money(paid_md * cost_rate)
    amount_revenue = (
        None if revenue_rate is None else _money((paid_md - onboarding) * revenue_rate)
    )
    if order is not None and (cost_rate is None or revenue_rate is None):
        groups.append(
            {
                "title": "Stawki",
                "checks": [
                    _check(
                        "warn",
                        "Linia zamówienia bez stawki MD",
                        "Kwoty i marża pojawią się po uzupełnieniu stawki.",
                    )
                ],
            }
        )
        warn = True

    status = "no_md" if blocked else "warnings" if warn or proof_blocking else "ok"
    return Result(
        status,
        onboarding,
        charged,
        remaining_after,
        amount_cost,
        amount_revenue,
        lines,
        groups,
        blocking=proof_blocking,
        md_over=over if over > 0 else None,
        meta=dict(inp.proof.meta) if inp.proof is not None and inp.proof.meta else None,
    )
