"""Kontrole łańcucha korekt i białej listy VAT na karcie osoby (rozliczenia E4).

Uzupełnienie ``contractor_invoices.card`` (13.11.2026, test Finansów na
fakturze z sześcioma korektami): sama suma netto łańcucha nie łapała korekt,
które zerują netto, a zostawiają VAT, ani korekt ze złym „stanem przed” czy
numerem faktury korygowanej. Trzy kontrole, wszystkie jako ostrzeżenia (nic
nie blokuje przyjęcia):

* **łańcuch po netto, VAT i brutto** — faktura pierwotna i korekty, które ją
  (pośrednio) korygują: brutto = netto + VAT, a VAT po korektach = netto po
  korektach × stawka ze stanu po ostatnich pozycjach (netto 0 → VAT 0),
* **korekta kontra dokument korygowany** — numer KSeF z ``DaneFaKorygowanej``
  jest w łańcuchu, numer i data faktury korygowanej zgadzają się z tym
  dokumentem, a „stan przed” (ilość, stawka, netto per stawka) to stan tego
  dokumentu: jego pozycje, jego zmiana (korekta korekty wpisana jako osobny
  dokument) albo stan łańcucha po poprzednich dokumentach. Korekta bez zmian
  kwot to uwaga,
* **biała lista VAT** — status sprzedawcy na dzień wystawienia
  (``contractor_details.check_whitelist``): VAT od podmiotu spoza listy
  czynnych podatników nie do odliczenia, faktura bez VAT od czynnego podatnika
  do sprawdzenia; brak odpowiedzi wykazu = „nie sprawdzono”.

Pozycje są tylko w XML-u FA, który pobieramy wyłącznie dla korekt i faktur,
które korygują (``details``); bez niego kontrola mówi „nie sprawdzono”.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional, Protocol

#: ``invoiceType`` z metadanych KSeF i ``RodzajFaktury`` z XML-a.
CORRECTION_TYPES = frozenset({"Kor", "KorZal", "KorRoz", "KOR", "KOR_ZAL", "KOR_ROZ"})
_CENT = Decimal("0.01")
_ZERO = Decimal("0")
_ZERO_RATES = ("zw", "np", "oo")
#: Status z białej listy → zdanie na karcie.
WHITELIST_LABELS = {
    "active": "czynny podatnik VAT",
    "exempt": "podatnik zwolniony z VAT",
    "unregistered": "niezarejestrowany jako podatnik VAT",
    "absent": "brak w wykazie podatników VAT",
}
NOT_PAYER = frozenset({"exempt", "unregistered", "absent"})
WHITELIST_ERRORS = {
    "disabled": "Sprawdzanie białej listy VAT jest wyłączone.",
    "quota_exceeded": "Wyczerpany dzienny limit zapytań do wykazu MF.",
    "unavailable": "Wykaz podatników VAT nie odpowiadał.",
    "rejected": "Wykaz podatników VAT odrzucił zapytanie.",
    "invalid_nip": "NIP sprzedawcy ma złą sumę kontrolną.",
    "invalid_date": "Data wystawienia jest w przyszłości.",
}


class Document(Protocol):
    id: int
    ksef_number: str
    seller_nip: str
    invoice_number: Optional[str]
    invoice_type: Optional[str]
    issue_date: Optional[date]
    net_amount: Optional[Decimal]
    vat_amount: Optional[Decimal]
    gross_amount: Decimal
    details: Optional[dict[str, Any]]
    vat_whitelist: Optional[dict[str, Any]]


#: Stan pozycji: stawka → (ilość, netto, jednostka).
State = dict[str, tuple[Decimal, Decimal, Optional[str]]]


def is_correction(doc: Document) -> bool:
    if (doc.invoice_type or "") in CORRECTION_TYPES:
        return True
    return str((doc.details or {}).get("type") or "") in CORRECTION_TYPES


def _ok(doc: Document) -> bool:
    return (doc.details or {}).get("state") == "ok"


def _dec(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw)) if raw not in (None, "") else _ZERO
    except InvalidOperation:
        return _ZERO


def _money(value: Optional[Decimal]) -> Decimal:
    return Decimal(value).quantize(_CENT) if value is not None else _ZERO


def rate_key(raw: Any) -> str:
    """``23`` / ``8`` / ``zw`` / ``np`` … — tekst ``P_12`` bez dopisków."""

    text = " ".join(str(raw or "").split()).lower()
    if not text:
        return "?"
    for zero in _ZERO_RATES:
        if text.startswith(zero):
            return zero
    match = re.match(r"^(\d+(?:[.,]\d+)?)", text)
    if match:
        return str(Decimal(match.group(1).replace(",", ".")).normalize())
    return text[:8]


def rate_value(key: str) -> Optional[Decimal]:
    if key in _ZERO_RATES:
        return _ZERO
    try:
        return Decimal(key)
    except InvalidOperation:
        return None


def _rate_label(key: str) -> str:
    return key if key in _ZERO_RATES or rate_value(key) is None else f"{key}%"


def _add(state: State, rate: str, quantity: Decimal, net: Decimal, unit: Any) -> None:
    q, n, u = state.get(rate, (_ZERO, _ZERO, None))
    state[rate] = (q + quantity, n + net, u or (str(unit) if unit else None))


def _clean(state: State) -> State:
    return {r: v for r, v in state.items() if v[0] != 0 or v[1] != 0}


def _rows(doc: Document, before: bool) -> list[dict[str, Any]]:
    items = (doc.details or {}).get("items") or []
    return [
        i
        for i in items
        if isinstance(i, dict) and bool(i.get("before_correction")) == before
    ]


def _aggregate(rows: Iterable[dict[str, Any]], sign: int = 1) -> State:
    state: State = {}
    for row in rows:
        _add(
            state,
            rate_key(row.get("vat_rate")),
            sign * _dec(row.get("quantity")),
            sign * _dec(row.get("net")),
            row.get("unit"),
        )
    return _clean(state)


def state_of(doc: Document) -> State:
    """Stan po dokumencie: pozycje faktury albo pozycje „po” korekty."""

    return _aggregate(_rows(doc, before=False))


def change_of(doc: Document) -> State:
    """Zmiana wprowadzona przez korektę: k-ty wiersz „po” minus k-ty „przed”.

    Stawka zmiany to stawka wiersza „po”: korekta 96 h 22% → 112 h 23% to
    +16 h po 23% (tak liczy ją korekta tej korekty)."""

    before, after = _rows(doc, True), _rows(doc, False)
    if not before:
        return state_of(doc)
    state: State = {}
    for index, row in enumerate(after):
        prior = before[index] if index < len(before) else {}
        _add(
            state,
            rate_key(row.get("vat_rate")),
            _dec(row.get("quantity")) - _dec(prior.get("quantity")),
            _dec(row.get("net")) - _dec(prior.get("net")),
            row.get("unit"),
        )
    for row in before[len(after) :]:
        _add(
            state,
            rate_key(row.get("vat_rate")),
            -_dec(row.get("quantity")),
            -_dec(row.get("net")),
            row.get("unit"),
        )
    return _clean(state)


def _apply(state: State, doc: Document) -> State:
    if not is_correction(doc):
        return state_of(doc)
    out = dict(state)
    for rate, (q, n, unit) in _aggregate(_rows(doc, True), sign=-1).items():
        _add(out, rate, q, n, unit)
    for rate, (q, n, unit) in state_of(doc).items():
        _add(out, rate, q, n, unit)
    return _clean(out)


def _same(a: State, b: State) -> bool:
    if set(a) != set(b):
        return False
    return all(a[r][0] == b[r][0] and _money(a[r][1]) == _money(b[r][1]) for r in a)


# ── Łańcuchy ─────────────────────────────────────────────────────────────────


def _norm(number: Optional[str]) -> str:
    return " ".join(str(number or "").split()).casefold()


def _order(doc: Document) -> tuple[date, int]:
    return (doc.issue_date or date.min, doc.id or 0)


def _refs(doc: Document) -> list[dict[str, Any]]:
    refs = (doc.details or {}).get("corrected") or []
    return [r for r in refs if isinstance(r, dict)]


@dataclass
class Chain:
    root: Document
    docs: list[Document]

    @property
    def corrections(self) -> list[Document]:
        return [d for d in self.docs if is_correction(d)]


def parent_of(
    doc: Document, by_ksef: dict[str, Document], docs: list[Document]
) -> Optional[Document]:
    """Dokument korygowany: po numerze KSeF, a bez niego po numerze faktury."""

    for ref in _refs(doc):
        found = by_ksef.get(str(ref.get("ksef_number") or ""))
        if found is not None and found is not doc:
            return found
    for ref in _refs(doc):
        if ref.get("ksef_number"):
            continue
        wanted = _norm(ref.get("invoice_number"))
        for other in docs:
            if other is not doc and wanted and _norm(other.invoice_number) == wanted:
                return other
    return None


def chains(docs: list[Document]) -> list[Chain]:
    ordered = sorted(docs, key=_order)
    by_ksef = {d.ksef_number: d for d in ordered}

    def root(doc: Document, seen: set[int]) -> Document:
        if not is_correction(doc) or id(doc) in seen:
            return doc
        parent = parent_of(doc, by_ksef, ordered)
        if parent is None:
            return doc
        return root(parent, seen | {id(doc)})

    grouped: dict[int, Chain] = {}
    for doc in ordered:
        top = root(doc, set())
        grouped.setdefault(id(top), Chain(root=top, docs=[])).docs.append(doc)
    return list(grouped.values())


# ── Formatowanie ─────────────────────────────────────────────────────────────


def _pln(value: Decimal) -> str:
    text = f"{_money(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} zł"


def _qty(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


def _describe(state: State, amounts: bool) -> str:
    if not state:
        return "bez pozycji"
    parts = []
    for rate, (q, n, unit) in sorted(state.items()):
        text = f"{_qty(q)}{' ' + unit if unit else ''}, {_rate_label(rate)}"
        if amounts:
            text += f", {_pln(n)}"
        parts.append(text)
    return "; ".join(parts)


def _name(doc: Document) -> str:
    return doc.invoice_number or doc.ksef_number


def _day(raw: Any) -> Optional[str]:
    try:
        return date.fromisoformat(str(raw)[:10]).strftime("%d.%m.%Y") if raw else None
    except ValueError:
        return None


def _warn(title: str, detail: Optional[str] = None) -> dict[str, Any]:
    check: dict[str, Any] = {"state": "warn", "title": title}
    if detail:
        check["detail"] = detail
    return check


def _note(title: str, detail: Optional[str] = None) -> dict[str, Any]:
    check: dict[str, Any] = {"state": "none", "title": title}
    if detail:
        check["detail"] = detail
    return check


# ── Kontrole ─────────────────────────────────────────────────────────────────


def _reference_checks(
    doc: Document, parent: Optional[Document], amounts: bool
) -> list[dict[str, Any]]:
    refs = _refs(doc)
    if not refs:
        return [_warn(f"Korekta {_name(doc)} bez danych faktury korygowanej")]
    if parent is None:
        ref = refs[0]
        where = ref.get("ksef_number") or ref.get("invoice_number") or "bez numeru"
        return [
            _warn(
                f"Korekta {_name(doc)} wskazuje fakturę spoza rozliczenia",
                f"Faktury {where} nie ma wśród faktur tej osoby za ten miesiąc.",
            )
        ]
    ref = next((r for r in refs if r.get("ksef_number") == parent.ksef_number), refs[0])
    wrong = []
    if _norm(ref.get("invoice_number")) != _norm(parent.invoice_number):
        wrong.append(f"numer {ref.get('invoice_number') or 'brak'}")
    parent_day = parent.issue_date.isoformat() if parent.issue_date else None
    if parent_day and str(ref.get("issue_date") or "") != parent_day:
        wrong.append(f"data {_day(ref.get('issue_date')) or 'brak'}")
    if not wrong:
        return []
    title = (
        f"Zła data faktury korygowanej w {_name(doc)}"
        if len(wrong) == 1 and wrong[0].startswith("data")
        else f"Zły numer faktury korygowanej w {_name(doc)}"
    )
    when = parent.issue_date.strftime("%d.%m.%Y") if parent.issue_date else "bez daty"
    return [
        _warn(
            title,
            f"Numer KSeF wskazuje {_name(parent)} z {when}, a w korekcie wpisano: "
            f"{', '.join(wrong)}.",
        )
    ]


def _before_checks(
    doc: Document,
    parent: Optional[Document],
    chain_state: Optional[State],
    amounts: bool,
) -> list[dict[str, Any]]:
    before = _aggregate(_rows(doc, True))
    if not before or parent is None:
        return []
    if not _ok(parent):
        return [
            _note(
                f"Stan przed w {_name(doc)}: nie sprawdzono",
                f"Treść faktury {_name(parent)} nie jest jeszcze pobrana z KSeF.",
            )
        ]
    expected = state_of(parent)
    candidates = [expected]
    if is_correction(parent):
        candidates.append(change_of(parent))
    if chain_state is not None:
        candidates.append(chain_state)
    if any(_same(before, c) for c in candidates):
        return []
    return [
        _warn(
            f"Zły stan przed w korekcie {_name(doc)}",
            f"W korekcie: {_describe(before, amounts)}. "
            f"{_name(parent)} ma: {_describe(expected, amounts)}.",
        )
    ]


def _zero_check(doc: Document) -> list[dict[str, Any]]:
    if any(_money(v) != 0 for v in (doc.net_amount, doc.vat_amount, doc.gross_amount)):
        return []
    if _ok(doc) and not _same(_aggregate(_rows(doc, True)), state_of(doc)):
        return []
    reason = (doc.details or {}).get("reason")
    return [
        _note(
            f"Korekta {_name(doc)} bez zmian kwot",
            f"Powód w korekcie: {reason}." if reason else None,
        )
    ]


def _corrections_word(count: int) -> str:
    if count == 1:
        return "1 korekta"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} korekty"
    return f"{count} korekt"


def _residual(chain: Chain, amounts: bool) -> list[dict[str, Any]]:
    net = sum((_money(d.net_amount) for d in chain.docs), _ZERO)
    vat = sum((_money(d.vat_amount) for d in chain.docs), _ZERO)
    gross = sum((_money(d.gross_amount) for d in chain.docs), _ZERO)
    tolerance = _CENT * len(chain.docs)
    count = len(chain.corrections)
    summary = (
        f"Faktura {_name(chain.root)} i {_corrections_word(count)} po zsumowaniu: "
        f"netto {_pln(net)}, "
        f"VAT {_pln(vat)}, brutto {_pln(gross)}."
        if amounts
        else None
    )
    out = []
    if abs(gross - net - vat) > tolerance:
        out.append(
            _warn(
                f"Brutto korekt do {_name(chain.root)} nie zgadza się z netto i VAT",
                summary,
            )
        )
    expected: Optional[Decimal] = None
    if net == 0:
        expected = _ZERO
    elif all(_ok(d) for d in chain.docs):
        state: State = {}
        for doc in chain.docs:
            state = _apply(state, doc)
        rates = {r for r, (_, n, _) in state.items() if n != 0}
        value = rate_value(rates.pop()) if len(rates) == 1 else None
        if value is not None:
            expected = (net * value / 100).quantize(_CENT)
    if expected is not None and abs(vat - expected) > tolerance:
        left = vat - expected
        title = (
            f"Korekty zostawiają {_pln(left)} VAT"
            if amounts
            else "Korekty zostawiają VAT do skorygowania"
        )
        detail = summary
        if amounts and expected:
            detail = f"{summary} Przy tej stawce VAT powinien wynosić {_pln(expected)}."
        out.append(_warn(title, detail))
    return out


def chain_checks(docs: list[Document], *, amounts: bool) -> list[dict[str, Any]]:
    """Kontrole korekt w fakturach osoby za miesiąc (puste = brak korekt)."""

    corrections = [d for d in docs if is_correction(d)]
    if not corrections:
        return []
    checks: list[dict[str, Any]] = []
    missing = [d for d in corrections if not _ok(d)]
    if missing:
        failed = [d for d in missing if (d.details or {}).get("state") == "failed"]
        checks.append(
            _note(
                "Korekty: nie sprawdzono łańcucha",
                (
                    "Nie udało się odczytać z KSeF: "
                    if failed
                    else "Treść z KSeF jeszcze nie pobrana: "
                )
                + ", ".join(_name(d) for d in missing)
                + ".",
            )
        )
    ordered = sorted(docs, key=_order)
    by_ksef = {d.ksef_number: d for d in ordered}
    residuals: list[dict[str, Any]] = []
    for chain in chains(ordered):
        state: Optional[State] = {}
        for doc in chain.docs:
            if is_correction(doc) and _ok(doc):
                parent = parent_of(doc, by_ksef, ordered)
                checks.extend(_reference_checks(doc, parent, amounts))
                checks.extend(_before_checks(doc, parent, state, amounts))
            if is_correction(doc):
                checks.extend(_zero_check(doc))
            state = _apply(state, doc) if state is not None and _ok(doc) else None
        if not missing and not is_correction(chain.root) and chain.corrections:
            residuals.extend(_residual(chain, amounts))
    # Kwota, która zostaje w KSeF, najpierw; uwagi (bez zmian kwot,
    # nie sprawdzono) po ostrzeżeniach.
    checks = residuals + sorted(checks, key=lambda c: c["state"] != "warn")
    if not missing and not any(c["state"] == "warn" for c in checks):
        checks.insert(
            0, {"state": "ok", "title": "Korekty zgodne po netto, VAT i brutto"}
        )
    return checks


def whitelist_checks(
    docs: list[Document], *, amounts: bool, mode: str
) -> list[dict[str, Any]]:
    """Biała lista VAT na dzień wystawienia każdej faktury i korekty."""

    if not docs:
        return []
    results = [(d, d.vat_whitelist or {}) for d in docs]
    checked = [
        (d, r)
        for d, r in results
        if r.get("state") == "ok" and r.get("status") in WHITELIST_LABELS
    ]
    unchecked = [(d, r) for d, r in results if (d, r) not in checked]
    checks: list[dict[str, Any]] = []
    with_vat = [
        (d, r)
        for d, r in checked
        if r["status"] in NOT_PAYER and _money(d.vat_amount) != 0
    ]
    if with_vat:
        day = _day(with_vat[0][1].get("on_date"))
        names = ", ".join(_name(d) for d, _ in with_vat)
        detail = f"Biała lista na {day}: {WHITELIST_LABELS[with_vat[0][1]['status']]}. VAT na {names}"
        if amounts:
            detail += (
                f": {_pln(sum((_money(d.vat_amount) for d, _ in with_vat), _ZERO))}"
            )
        checks.append(
            _warn(
                "Sprzedawca nie jest podatnikiem VAT, VAT nie do odliczenia",
                detail + ".",
            )
        )
    payer_zw = [
        (d, r)
        for d, r in checked
        if r["status"] == "active"
        and not is_correction(d)
        and _money(d.vat_amount) == 0
        and _money(d.net_amount) != 0
    ]
    if payer_zw:
        names = ", ".join(_name(d) for d, _ in payer_zw)
        day = _day(payer_zw[0][1].get("on_date"))
        checks.append(
            _warn(
                "Faktura bez VAT od czynnego podatnika VAT",
                f"{names}: VAT 0 zł, a na białej liście na {day} sprzedawca ma status „Czynny”. "
                "Sprawdź podstawę zwolnienia.",
            )
        )
    if unchecked:
        if mode == "off":
            reason = WHITELIST_ERRORS["disabled"]
        else:
            codes = [r.get("code") for _, r in unchecked if r.get("state") == "error"]
            reason = (
                WHITELIST_ERRORS.get(codes[0] or "", WHITELIST_ERRORS["unavailable"])
                if codes
                else "Czeka na sprawdzenie przy pobieraniu z KSeF."
            )
        checks.append(
            _note(
                "Biała lista VAT: nie sprawdzono",
                f"{reason} Dotyczy: {', '.join(_name(d) for d, _ in unchecked)}.",
            )
        )
    elif not checks:
        status = checked[-1][1]["status"]
        checks.append(
            {"state": "ok", "title": f"Biała lista VAT: {WHITELIST_LABELS[status]}"}
        )
    return checks
