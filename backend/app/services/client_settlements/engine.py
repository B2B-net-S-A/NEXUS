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
* Podział na zamówienia z maila klienta (``Inputs.split``, ``order_split``):
  każde zamówienie ma własną linię, stawkę, pulę i zejście. Zamówienie
  zakończone albo bez puli w NEXUS-ie idzie jak w mailu, z uwagą „uzupełnij
  zamówienie” i bez blokady (decyzja Artura z 24.11.2026: klient sam wskazał
  zamówienie, a pule w NEXUS-ie bywają nieaktualne). Podział wchodzi tylko na
  same dni zwykłe i tylko, gdy suma z maila równa się MD rozliczenia.
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
class SplitPart:
    """Część miesiąca osoby na jednym zamówieniu według maila klienta."""

    order: OrderState
    #: Dni zwykłe na tym zamówieniu.
    md: Decimal
    #: Zamówienie zakończone w NEXUS-ie (status albo koniec przed miesiącem).
    closed: bool = False


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
    #: Podział miesiąca na zamówienia z maila klienta; pusty = jedno ``order``.
    split: tuple[SplitPart, ...] = ()


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
    #: Podział na zamówienia, gdy wszedł: na każde zamówienie ``order_id``,
    #: ``number``, ``md``, ``remaining_after``, ``closed``, kwoty i ``main``
    #: (zamówienie rozliczenia, ``ClientSettlement.order_id``).
    orders: tuple[dict[str, Any], ...] = ()


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


def _protocol_amount(
    inp: Inputs, amount_revenue: Optional[Decimal], groups: list[dict[str, Any]]
) -> bool:
    """``cl.protocol_amount``: kwota do faktury = kwota netto z protokołu klienta.

    Finanse Orlenu zakwestionowały 23.11.2026 fakturę za X: kwota z MD × stawka
    z zamówienia różniła się od protokołu o kilkaset złotych. ``True`` = uwaga."""

    level = _level(inp.rules, "cl.protocol_amount")
    raw = (inp.proof.meta.get("document_amount") if inp.proof else None) or None
    if level == "off" or raw is None:
        return False
    document = _money(Decimal(raw))
    if amount_revenue is None:
        check = _check(
            "warn",
            f"Protokół: {_fmt(document)} zł netto, kwoty do faktury brak",
            "Linia zamówienia bez stawki: porównaj kwotę z protokołem przed fakturą.",
        )
    elif abs(amount_revenue - document) < Decimal("0.01"):
        groups.append(
            {
                "title": "Kwota z protokołu",
                "checks": [
                    _check("ok", f"Do faktury {_fmt(document)} zł jak w protokole")
                ],
            }
        )
        return False
    else:
        check = _check(
            "warn",
            "Kwota do faktury inna niż w protokole klienta",
            f"Do faktury {_fmt(amount_revenue)} zł netto, w protokole {_fmt(document)} zł "
            "netto. Klient odeśle fakturę do korekty: sprawdź MD, stawkę i zamówienie (PO).",
        )
    groups.append({"title": "Kwota z protokołu", "checks": [check]})
    return True


def _split_problem(
    split: tuple[SplitPart, ...], regular: Decimal, extra: Decimal, onboarding: Decimal
) -> Optional[str]:
    """Powód, dla którego podział z maila nie wchodzi; ``None`` = wchodzi."""

    if extra > 0 or onboarding > 0:
        return (
            "Mail dzieli same dni, a rozliczenie ma pracę dodatkową albo MD "
            "wdrożeniowe: MD idą na jedno zamówienie, podziel je ręcznie."
        )
    total = _md(sum((part.md for part in split), ZERO))
    if total != regular:
        return (
            f"W mailu {_fmt(total)} MD, w rozliczeniu {_fmt(regular)} MD: MD idą na "
            "jedno zamówienie. Sprawdź mail klienta albo MD z dokumentu."
        )
    return None


def _with_split(
    inp: Inputs,
    regular: Decimal,
    groups: list[dict[str, Any]],
    *,
    warn: bool,
    proof_blocking: bool,
) -> Result:
    """Rozliczenie podzielone na zamówienia z maila klienta: linia, stawka, pula
    i zejście każdego zamówienia. Ponad pulę i zamówienie zakończone idą jak
    w mailu, z uwagą (decyzja Artura z 24.11.2026)."""

    parts = [(part, _md(part.md)) for part in inp.split]
    # Zamówienie rozliczenia: z największą liczbą MD, przy remisie pierwsze z maila.
    main = max(range(len(parts)), key=lambda i: (parts[i][1], -i))
    # Reszta z zaokrąglenia części (12,5 h / 8 = 1,5625) idzie na zamówienie
    # rozliczenia: suma części = MD rozliczenia, zejście i koszt jak na jednym.
    rest = sum((md for i, (_part, md) in enumerate(parts) if i != main), ZERO)
    parts[main] = (parts[main][0], _md(regular - rest))
    groups.append(
        {
            "title": "Podział na zamówienia",
            "checks": [
                _check(
                    "ok",
                    "Podział według maila klienta",
                    "; ".join(
                        f"{part.order.number or 'zamówienie bez numeru'}: {_fmt(md)} MD"
                        for part, md in parts
                    ),
                )
            ],
        }
    )
    lines: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    cost_total: Optional[Decimal] = ZERO
    revenue_total: Optional[Decimal] = ZERO
    for index, (part, md) in enumerate(parts):
        order = part.order
        available = order.md_available
        remaining = None if available is None else _md(available - md)
        if part.closed or (remaining is not None and remaining < 0):
            left = (
                ""
                if available is None
                else f" W puli zostało {_fmt(_md(max(available, ZERO)))} MD."
            )
            check = _check(
                "warn",
                "Zamówienie zakończone w NEXUS-ie"
                if part.closed
                else f"Ponad pulę zamówienia o {_fmt(-(remaining or ZERO))} MD",
                f"Mail klienta każe rozliczyć na nim {_fmt(md)} MD.{left} Zejdzie "
                "całość i tyle idzie do faktury: uzupełnij zamówienie w NEXUS-ie.",
            )
            warn = True
        elif remaining is not None:
            check = _check(
                "ok",
                f"Zejdzie {_fmt(md)} MD, zostanie {_fmt(remaining)} MD",
                "Zejście przy przyjęciu RCP; ponowne przyjęcie nadpisuje miesiąc.",
            )
        else:
            check = _check("none", f"{_fmt(md)} MD, zamówienie bez puli MD na osobie")
        groups.append(
            {
                "title": f"Zamówienie {order.number}" if order.number else "Zamówienie",
                "checks": [check],
            }
        )
        cost = None if order.rate_cost is None else _money(md * order.rate_cost)
        revenue = (
            None if order.rate_revenue is None else _money(md * order.rate_revenue)
        )
        cost_total = None if cost is None or cost_total is None else cost_total + cost
        revenue_total = (
            None
            if revenue is None or revenue_total is None
            else revenue_total + revenue
        )
        lines.append(
            {
                "label": f"Dni zwykłe, zamówienie {order.number}"
                if order.number
                else "Dni zwykłe",
                "md": str(md),
                "multiplier": "1.00",
                "rate": None
                if order.rate_cost is None
                else str(_money(order.rate_cost)),
                "net": None if cost is None else str(cost),
                "order_id": order.order_id,
            }
        )
        orders.append(
            {
                "order_id": order.order_id,
                "number": order.number,
                "md": str(md),
                "remaining_after": None if remaining is None else str(remaining),
                "closed": part.closed,
                "amount_cost": None if cost is None else str(cost),
                "amount_revenue": None if revenue is None else str(revenue),
                "main": index == main,
            }
        )
    if any(p.order.rate_cost is None or p.order.rate_revenue is None for p, _ in parts):
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
    if _protocol_amount(inp, revenue_total, groups):
        warn = True
    main_remaining = orders[main]["remaining_after"]
    return Result(
        "warnings" if warn or proof_blocking else "ok",
        ZERO,
        regular,
        None if main_remaining is None else Decimal(main_remaining),
        cost_total,
        revenue_total,
        lines,
        groups,
        blocking=proof_blocking,
        meta=dict(inp.proof.meta) if inp.proof is not None and inp.proof.meta else None,
        orders=tuple(orders),
    )


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
    if inp.split:
        problem = _split_problem(inp.split, regular, extra, onboarding)
        if problem is None:
            return _with_split(
                inp, regular, groups, warn=warn, proof_blocking=proof_blocking
            )
        groups.append(
            {
                "title": "Podział na zamówienia",
                "checks": [
                    _check("warn", "Podział z maila klienta nie wszedł", problem)
                ],
            }
        )
        warn = True
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
    if _protocol_amount(inp, amount_revenue, groups):
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
