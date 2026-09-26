"""Polkomtel — „Zlecenie wykonawcze" z tabelą konsultantów i kwotą całego zlecenia.

Układ dokumentu (Word/PDF z działu zakupów Polkomtela)::

    ZLECENIE WYKONAWCZE nr SAP 4500123456 / 2031 rok
    zawarte w dniu 30.03.2031
    …
    III. Warunki finansowe i harmonogram płatności
    1. Wartość Zlecenia albo stawki z planowaną pracochłonnością …:
       na kwotę 40 000 PLN
       na co składa się:
    | Cena netto 1MD po upuście [PLN] | Cena total [PLN] | Konsultant       |
    | 840,00 zł                       | 40 000,00 zł     | Nowak-Testowa Ewa|
    | 1 280,00 zł                     |  (scalona)       | Przykład Adam    |

Reguły (ticket 09.2026):

* **numer** — skrót + numer z linii „ZLECENIE WYKONAWCZE nr …", bez części po
  ukośniku (rok): „SAP 4500123456". Reguła ogólna (``number_after_nr``), nie
  zaszyta pod „SAP" — ten sam szablon ma Cyfrowy Polsat („CP …");
* **okres** — data rozpoczęcia z frazy „zawarte w dniu …"; koniec zawsze
  BEZTERMINOWY. Zamówienie kosztowe kończy wyczerpanie kwoty, zamówienie MD —
  wyczerpanie MD (per osoba albo wspólnej puli), nigdy data;
* **stawka** — kolumna „Cena netto 1MD po upuście [PLN]", zawsze NETTO za 1 MD
  (stała reguła klienta, bez rozpoznawania brutto/netto);
* **kwota zamówienia** — „na kwotę … PLN" albo kolumna „Cena total [PLN]",
  jako wartość CAŁEGO zlecenia (komórka scalona na wszystkie wiersze), nie per
  osoba;
* **wiersze** — każdy konsultant dostaje stawkę z SWOJEGO wiersza. Kolejność
  kolumn czytamy z nagłówka tabeli, więc zamiana kolumn w szablonie nie
  przypisze stawki sąsiedniej osobie;
* **MD** — dokument kosztowy nie podaje liczby MD i to jest poprawny odczyt,
  nie brak. Gdy MD jest w dokumencie, bywa w dwóch wariantach: kolumna MD przy
  każdej osobie albo jedna liczba na całe zlecenie („pracochłonność … MD").

Tekst wejściowy ma dwa kształty i oba są obsługiwane: PDF (pdfplumber) składa
wiersz tabeli w jedną linię, a DOCX (python-docx) wypisuje każdą komórkę jako
osobną linię, na końcu dokumentu, z komórką scaloną powtórzoną w każdym
wierszu. Dlatego tabela jest czytana jako strumień komórek, a nie linia po
linii.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.services.order_pdf_parser import (
    _names_exactly_equivalent,
    apply_consultant_row_match,
)
from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clean_person_name,
    clear_field,
    fold,
    labelled_date,
    normalize_amount,
    number_after_nr,
    set_field,
)

#: Produkcyjne ID klienta Polkomtel — to samo, które niesie
#: ``finance_order_matching.POLKOMTEL_CLIENT_ID`` (numer „SAP …" w bazie).
CANONICAL_CLIENT_IDS: frozenset[int] = frozenset({15})
CLIENT_IDS_ENV = "POLKOMTEL_ORDER_EXTRACTION_CLIENT_IDS"

#: Nagłówek dokumentu, za którym stoi „nr" — wspólny z Cyfrowym Polsatem.
NUMBER_LABEL = r"zlecenie[^\S\n]+wykonawcze"

_SIGNING_DATE_LABEL = r"zawart\w*\s+w\s+dniu"

# ── Tabela ──────────────────────────────────────────────────────────────────

_HEADER_RATE_RE = re.compile(r"cena\s+netto(?:\s+1\s*MD)?", re.IGNORECASE)
_HEADER_TOTAL_RE = re.compile(r"cena\s+total", re.IGNORECASE)
# Nagłówek kolumny osoby to CAŁE słowo („Konsultant", „Konsultanci", „Imię
# i nazwisko") — „usług konsultantów" w treści nad tabelą nie jest nagłówkiem
# i nie może odwrócić kolejności kolumn.
_HEADER_NAME_RE = re.compile(
    r"\b(?:konsultant|konsultanci|imi[ęe]\s+i\s+nazwisko)\b", re.IGNORECASE
)
# Nagłówki kolumn stoją blisko siebie (DOCX: kolejne linie komórek).
_HEADER_SPAN = 200
_HEADER_MD_RE = re.compile(
    r"(?:liczba|ilo[śs][ćc]|planowan\w*)\s+(?:MD|osobodni|dni)", re.IGNORECASE
)
# Nagłówek bywa rozbity na kilka linii (DOCX: komórka = linia), więc szukamy
# jego elementów w oknie, a nie w jednej linii.
_HEADER_WINDOW = 400
# Koniec tabeli: następny punkt sekcji III albo tabela podpisów.
# Numer punktu („2.") należy do znacznika — inaczej zostałby w tabeli jako liczba.
_TABLE_END_RE = re.compile(
    r"^[ \t]*(?:\d{1,2}\.|[IVX]{1,4}\.)?[ \t]*(?:wskazanie\s+sposobu"
    r"|kwoty\s+nale[żz]ne|harmonogram\s+p[łl]atno|rodzaj\s+licencji"
    r"|za[łl][ąa]czniki\s+do\s+zlecenia|wykonawca[ \t]*$|nabywca[ \t]*$)"
    r"|\(podpis",
    re.IGNORECASE | re.MULTILINE,
)
_FOREIGN = r"(?:EUR|USD|GBP|CHF)"
_MONEY_RE = re.compile(
    r"(?<![\d,])(\d{1,3}(?:[ \u00a0.]\d{3})*(?:,\d{2})?)[^\S\n]*(?:z[łl]|PLN)\b"
    rf"|(?<![\d,.])(\d{{1,3}}(?:[ \u00a0.]\d{{3}})*,\d{{2}})(?![\d,])(?![^\S\n]*{_FOREIGN})",
    re.IGNORECASE,
)
_FOREIGN_MONEY_RE = re.compile(
    rf"\d{{1,3}}(?:[ \u00a0.]\d{{3}})*(?:,\d{{2}})?[^\S\n]*{_FOREIGN}\b", re.IGNORECASE
)
_MD_CELL_RE = re.compile(r"(?<![\d,.])(\d{1,4}(?:,\d{1,3})?)[^\S\n]*(?:MD\b)?")
_UPPER = "A-ZĄĆĘŁŃÓŚŹŻÄÖÜÉ"
_LOWER = "a-ząćęłńóśźżäöüéè"
# Człon nazwiska: „Nowak", „NOWAK", „O'Neil"; łącznik tworzy nazwisko dwuczłonowe.
_NAME_PART = (
    rf"(?:[{_UPPER}]['’][{_UPPER}][{_LOWER}]+|[{_UPPER}][{_LOWER}]+|[{_UPPER}]{{2,}})"
)
_NAME_WORD = rf"{_NAME_PART}(?:-{_NAME_PART})?"
_NAME_RE = re.compile(
    rf"(?<![\w-])({_NAME_WORD}(?:[^\S\n]+{_NAME_WORD}){{1,3}})(?![\w-])"
)
#: Wyrazy z wielkiej litery, które w tabeli i wokół niej nie są osobami.
_NOT_A_NAME = frozenset(
    fold(word)
    for word in (
        "Cena",
        "Netto",
        "Total",
        "Konsultant",
        "Konsultanci",
        "Wykonawca",
        "Nabywca",
        "Razem",
        "Suma",
        "Wartość",
        "Zlecenia",
        "Zlecenie",
        "Stawka",
        "Kwota",
        "Liczba",
        "Ilość",
        "PLN",
        "EUR",
        "USD",
        "VAT",
        "MD",
        "SAP",
        "CP",
        "UPUŚCIE",
    )
)

# ── Kwota i MD całego zlecenia ──────────────────────────────────────────────

_ORDER_AMOUNT_RE = re.compile(
    r"na\s+kwot[ęe]\s*[:\-–]?\s*(\d{1,3}(?:[ \u00a0.]\d{3})*(?:,\d{1,2})?)\s*(?:z[łl]|PLN)",
    re.IGNORECASE,
)
_ORDER_MD_RE = re.compile(
    r"(?:pracoch[łl]onno\w*|w\s+wymiarze|liczba\s+MD|ilo[śs][ćc]\s+MD|[łl][ąa]cznie)"
    r"[^\d\n]{0,40}?(\d{1,4}(?:[.,]\d{1,3})?)\s*(?:MD|osobodni|roboczodni)\b",
    re.IGNORECASE,
)


def order_number(text: str) -> Optional[str]:
    """„SAP 4500123456" z „ZLECENIE WYKONAWCZE nr SAP 4500123456 / 2031 rok"."""
    return number_after_nr(text, label=NUMBER_LABEL)


def signing_date(text: str) -> Optional[str]:
    """Data z frazy „zawarte w dniu …" — data rozpoczęcia zlecenia (ISO)."""
    return labelled_date(_SIGNING_DATE_LABEL, text)


def _amount(raw: Optional[str]) -> Optional[Decimal]:
    if not raw:
        return None
    compact = raw.replace(" ", "").replace("\u00a0", "")
    # „40.000" / „1.280,00" — kropka jako separator tysięcy (polski zapis),
    # a nie część dziesiętna: bez tego „40.000 PLN" dawało 40.
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", compact):
        compact = compact.replace(".", "")
    return normalize_amount(compact)


def order_amount(text: str) -> Optional[Decimal]:
    """Kwota całego zlecenia z „na kwotę … PLN"."""
    match = _ORDER_AMOUNT_RE.search(text or "")
    return _amount(match.group(1)) if match else None


def order_md(text: str) -> Optional[Decimal]:
    """Jedna liczba MD na całe zlecenie („pracochłonność … 50 MD")."""
    match = _ORDER_MD_RE.search(text or "")
    return normalize_amount(match.group(1)) if match else None


def _header(text: str) -> Optional[tuple[int, list[str]]]:
    """Koniec nagłówka tabeli i kolejność kolumn (``rate``/``total``/``md``/``name``).

    Kotwicą jest nagłówek „Cena netto" — definiuje tabelę. Kolumny osoby, kwoty
    i MD szukamy tylko w jego bezpośrednim sąsiedztwie (najbliższe trafienie),
    więc słowo z treści nad tabelą nie przestawi kolejności kolumn.
    """
    for rate in _HEADER_RATE_RE.finditer(text):
        lo = max(0, rate.start() - _HEADER_SPAN)
        hi = min(len(text), rate.end() + _HEADER_SPAN)
        window = text[lo:hi]
        names = list(_HEADER_NAME_RE.finditer(window))
        if not names:
            continue

        def distance(match: re.Match[str]) -> int:
            start = lo + match.start()
            return start - rate.end() if start >= rate.end() else rate.start() - start

        name = min(names, key=distance)
        columns: list[tuple[int, int, str]] = [
            (rate.start(), rate.end(), "rate"),
            (lo + name.start(), lo + name.end(), "name"),
        ]
        totals = list(_HEADER_TOTAL_RE.finditer(window))
        if totals:
            total = min(totals, key=distance)
            columns.append((lo + total.start(), lo + total.end(), "total"))
        # Kolumna MD tylko wewnątrz nagłówka — „liczba MD" w treści zlecenia
        # nad tabelą nie może dopisać tabeli kolumny, której nie ma. Nagłówek
        # MD bywa też PIERWSZĄ kolumną („Liczba MD | Cena netto 1MD | …") —
        # do rundy 6 audytu był wtedy pomijany, więc liczba MD sklejała się ze
        # stawką w jedną kwotę. Stąd ten sam margines 40 znaków po lewej.
        span_lo = min(start for start, _, _ in columns)
        span_hi = max(end for _, end, _ in columns)
        for md in _HEADER_MD_RE.finditer(window):
            if span_lo - 40 <= lo + md.start() <= span_hi + 40:
                columns.append((lo + md.start(), lo + md.end(), "md"))
                break
        columns.sort()
        end = max(col_end for _, col_end, _ in columns)
        # Za nagłówkiem mogą stać jeszcze dopiski kolumn („[PLN]", „po upuście").
        line_end = text.find("\n", end)
        return (len(text) if line_end == -1 else line_end), [c[2] for c in columns]
    return None


def _is_person(name: str) -> bool:
    words = name.split()
    return 2 <= len(words) <= 4 and not any(
        fold(part) in _NOT_A_NAME for word in words for part in word.split("-")
    )


# Kwota, której pierwsza grupa cyfr stoi po SPACJI („10 840,00") — może być
# liczbą MD z kolumny po lewej sklejoną ze stawką (runda 6 audytu).
_GLUE_RE = re.compile(r"(\d{1,3})[ \u00a0](\d{3}(?:[ \u00a0]\d{3})*(?:,\d{2})?)")


def _cells(region: str, *, with_md: bool) -> list[tuple[str, object]]:
    """Strumień komórek tabeli w kolejności czytania: kwoty, MD, osoby.

    Za kwotą ze spacją w pierwszej grupie cyfr stoi znacznik ``glue``
    (``(md, reszta, surowy tekst)``) — o tym, czy to sklejenie z kolumną MD,
    rozstrzyga dopiero wiersz (``_unglue``), bo tylko on zna kolejność kolumn.
    """
    cells: list[tuple[int, str, object]] = []
    taken: list[tuple[int, int]] = []
    for match in _MONEY_RE.finditer(region):
        raw = match.group(1) or match.group(2)
        value = _amount(raw)
        if value is not None:
            cells.append((match.start(), "money", value))
            taken.append((match.start(), match.end()))
            glue = _GLUE_RE.fullmatch(raw) if with_md else None
            if glue:
                cells.append(
                    (
                        match.start(),
                        "glue",
                        (Decimal(glue.group(1)), _amount(glue.group(2)), raw),
                    )
                )
    for match in _NAME_RE.finditer(region):
        name = clean_person_name(match.group(1))
        if _is_person(name):
            cells.append((match.start(), "name", name))
            taken.append((match.start(), match.end()))
    if with_md:
        for match in _MD_CELL_RE.finditer(region):
            if any(lo <= match.start() < hi for lo, hi in taken):
                continue
            value = normalize_amount(match.group(1))
            if value is not None and value > 0:
                cells.append((match.start(), "md", value))
    # Stabilne sortowanie: znacznik ``glue`` zostaje tuż za swoją kwotą.
    cells.sort(key=lambda cell: cell[0])
    return [(kind, value) for _, kind, value in cells]


def _table(text: str) -> Optional[tuple[list[str], list[tuple[str, object]]]]:
    """Kolejność kolumn i strumień komórek tabeli konsultantów."""
    header = _header(text)
    if header is None:
        return None
    start, columns = header
    stop = _TABLE_END_RE.search(text, start)
    region = text[start : stop.start() if stop else len(text)]
    return columns, _cells(region, with_md="md" in columns)


def _moneys(cells: list[tuple[str, object]]) -> list[Decimal]:
    return [value for kind, value in cells if kind == "money"]  # type: ignore[misc]


def _row_totals(
    text: str, columns: list[str], cells: list[tuple[str, object]]
) -> frozenset[Decimal]:
    """Kwoty, których NIE wolno wziąć za stawkę osoby.

    „Na kwotę … PLN" oraz — gdy tabela ma kolumnę „Cena total", a kwot jest
    więcej niż osób — największa kwota tabeli. Komórka scalona stoi w PDF-ie
    osobną linią między wierszami (trafiłaby do bufora następnej osoby),
    a w DOCX powtarza się przy każdym wierszu; bywa też INNA niż „na kwotę"
    (i wtedy o rozbieżności mówi osobny powód, ale stawką nie zostaje). Kwoty
    per wiersz rozstrzyga dalej kolejność kolumn.
    """
    totals: set[Decimal] = set()
    stated = order_amount(text)
    if stated is not None:
        totals.add(stated)
    amounts = _moneys(cells)
    people = sum(1 for kind, _ in cells if kind == "name")
    if "total" in columns and len(amounts) > people and len(set(amounts)) > 1:
        totals.add(max(amounts))
    return frozenset(totals)


def _row(
    ordinal: int,
    name: str,
    moneys: list[Decimal],
    mds: list[Decimal],
    *,
    columns: list[str],
    totals: frozenset[Decimal],
    paired_totals: bool,
    glued: Optional[str] = None,
) -> ConsultantOrderRow:
    reasons: list[str] = []
    rates = [value for value in moneys if value not in totals]
    if len(rates) == 2 and paired_totals:
        # KAŻDY wiersz tabeli ma parę „stawka + kwota osoby": stawką jest
        # komórka kolumny „Cena netto", po tej stronie „Cena total", po której
        # stoi w nagłówku. Bez tej regularności dwie kwoty w wierszu znaczą, że
        # do bufora wpadła kwota cudzego wiersza (nierozpoznane nazwisko,
        # nazwisko złamane na dwie linie) — wtedy nie wybieramy żadnej.
        rate_first = columns.index("rate") < columns.index("total")
        rates = [rates[0] if rate_first else rates[-1]]
    rate = rates[0] if len(rates) == 1 else None
    if rate is None:
        reasons.append(
            "nie udało się jednoznacznie odczytać stawki z kolumny „Cena netto 1MD” "
            "— sprawdź stawkę z dokumentem"
        )
    md = mds[0] if len(mds) == 1 else None
    if len(mds) > 1:
        reasons.append("w wierszu jest kilka liczb MD — sprawdź limit MD tej osoby")
    if glued is not None and not (
        md is not None
        and rate is not None
        and any(value == md * rate for value in moneys if value != rate)
    ):
        # Liczba MD i kwota stały w jednej linii ze spacją — bez dowodu
        # (MD × stawka = kwota osoby) podział jest zgadywaniem (runda 6 audytu).
        reasons.append(
            f"liczba MD mogła skleić się z kwotą w sąsiedniej kolumnie („{glued}”) "
            "— sprawdź stawkę i liczbę MD z dokumentem"
        )
    return ConsultantOrderRow(
        consultant_name=name,
        rate_client=rate,
        rate_unit="day" if rate is not None else None,
        md_total=md,
        uncertain=bool(reasons),
        uncertain_reason=(f"{ordinal}. osoba w tabeli: " + "; ".join(reasons))
        if reasons
        else None,
    )


def _rows_carry_own_totals(
    text: str,
    columns: list[str],
    buffers: list[_Buffer],
) -> bool:
    """Czy KAŻDY wiersz ma parę „stawka + kwota tej osoby" (a nie cudzą kwotę).

    Dowody, wszystkie naraz: tabela ma kolumnę „Cena total", każdy wiersz ma
    dokładnie dwie kwoty (poza kwotą zlecenia), kwota osoby jest większa od jej
    stawki, a suma kwot osób zgadza się z „na kwotę …" — bez tej ostatniej
    kwota osoby musi pokrywać choć dwa MD. Dwie kwoty w wierszu bez tych
    dowodów znaczą, że do bufora wpadła kwota wiersza, którego nazwiska nie
    rozpoznano (wielkie litery, nazwisko złamane na dwie linie) — wtedy stawki
    NIE zgadujemy.
    """
    if "total" not in columns or not buffers:
        return False
    stated = order_amount(text)
    rate_first = columns.index("rate") < columns.index("total")
    row_totals: list[Decimal] = []
    for _, row_moneys, _, _ in buffers:
        values = [value for value in row_moneys if value != stated]
        if len(values) != 2:
            return False
        rate, own = (values[0], values[1]) if rate_first else (values[1], values[0])
        if own <= rate:
            return False
        if stated is None and own < rate * 2:
            return False
        row_totals.append(own)
    return stated is None or sum(row_totals, Decimal("0")) == stated


_Buffer = tuple[str, list[Decimal], list[Decimal], Optional[str]]


def _buffers(
    text: str, columns: list[str], cells: list[tuple[str, object]]
) -> tuple[list[_Buffer], list[Decimal]]:
    """Komórki pogrupowane w wiersze osób + kwoty bez osoby.

    Czwarty element wiersza to surowy tekst kwoty rozdzielonej na liczbę MD
    i kwotę (``_unglue``) albo ``None``.
    """
    name_first = columns.index("name") < columns.index("rate")
    raw_buffers: list[tuple[str, list[Decimal], list[Decimal], dict[int, tuple]]] = []
    moneys: list[Decimal] = []
    mds: list[Decimal] = []
    glues: dict[int, tuple] = {}
    pending: Optional[str] = None
    leftover: list[Decimal] = []
    for kind, value in cells:
        if kind == "name":
            if name_first:
                # Kolumna osoby otwiera wiersz: komórki za nią należą do niej.
                if pending is not None:
                    raw_buffers.append((pending, moneys, mds, glues))
                elif moneys:
                    leftover.extend(moneys)
                pending = str(value)
            else:
                # Kolumna osoby zamyka wiersz: kwoty przed nią należą do niej.
                raw_buffers.append((str(value), moneys, mds, glues))
            moneys, mds, glues = [], [], {}
        elif kind == "money":
            moneys.append(value)  # type: ignore[arg-type]
        elif kind == "glue":
            glues[len(moneys) - 1] = value  # type: ignore[assignment]
        else:
            mds.append(value)  # type: ignore[arg-type]
    if name_first and pending is not None:
        raw_buffers.append((pending, moneys, mds, glues))
    else:
        leftover.extend(moneys)
    stated = order_amount(text)
    return [_unglue(buffer, columns, stated) for buffer in raw_buffers], leftover


def _unglue(
    buffer: tuple[str, list[Decimal], list[Decimal], dict[int, tuple]],
    columns: list[str],
    stated: Optional[Decimal],
) -> _Buffer:
    """Rozdziel liczbę MD sklejoną z kwotą kolumny stojącej tuż za nią.

    pdfplumber składa wiersz „10 | 840,00 zł" w „10 840,00 zł", a spacja jest
    też separatorem tysięcy — ``_MONEY_RE`` czytało to jako 10 840,00 i MD
    znikało (runda 6 audytu). Gdy w nagłówku kolumna MD stoi tuż przed kolumną
    kwoty, wiersz nie ma osobnej komórki MD, a właściwa (k-ta) kwota wiersza
    ma spację w pierwszej grupie, dzielimy ją na MD i kwotę — i oznaczamy,
    żeby ``_row`` zażądał dowodu arytmetycznego albo sprawdzenia.
    """
    name, moneys, mds, glues = buffer
    if "md" not in columns or mds:
        return name, moneys, mds, None
    md_at = columns.index("md")
    if md_at + 1 >= len(columns) or columns[md_at + 1] not in ("rate", "total"):
        return name, moneys, mds, None
    index = sum(1 for column in columns[:md_at] if column in ("rate", "total"))
    glue = glues.get(index)
    if glue is None or index >= len(moneys) or moneys[index] == stated:
        return name, moneys, mds, None
    md, rest, raw = glue
    if md <= 0 or rest is None or rest <= 0:
        return name, moneys, mds, None
    return name, [*moneys[:index], rest, *moneys[index + 1 :]], [md], raw


def _parse_table(text: str) -> tuple[list[ConsultantOrderRow], list[str]]:
    """Wiersze konsultantów i zastrzeżenia do całej tabeli."""
    text = text or ""
    table = _table(text)
    if table is None:
        return [], []
    columns, cells = table
    totals = _row_totals(text, columns, cells)
    buffers, leftover = _buffers(text, columns, cells)

    paired_totals = _rows_carry_own_totals(text, columns, buffers)
    if paired_totals:
        # Kwoty per osoba są podsumowaniami wierszy, nie komórką scaloną — nie
        # wolno ich odrzucać jako „kwoty zlecenia" (największa z nich nią nie jest).
        stated = order_amount(text)
        totals = frozenset({stated}) if stated is not None else frozenset()
    rows = [
        _row(
            index,
            name,
            row_moneys,
            row_mds,
            columns=columns,
            totals=totals,
            paired_totals=paired_totals,
            glued=glued,
        )
        for index, (name, row_moneys, row_mds, glued) in enumerate(buffers, start=1)
    ]
    reasons: list[str] = []
    stray = [value for value in leftover if value not in totals]
    if stray:
        reasons.append(
            "W tabeli są kwoty, których nie da się przypisać do żadnej osoby ("
            + ", ".join(str(value) for value in stray)
            + ") — porównaj osoby i stawki z dokumentem"
        )
    return rows, reasons


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    """Wiersze konsultantów z tabeli (deterministycznie, stawka z WŁASNEGO wiersza)."""
    return _parse_table(text)[0]


def table_total(text: str) -> Optional[Decimal]:
    """Kwota z kolumny „Cena total [PLN]" — łączna, nie per osoba.

    Komórka scalona (jedna kwota na wszystkie wiersze) jest kwotą zlecenia.
    Kwoty różne w każdym wierszu to podsumowania per osoba — wartością
    zlecenia jest wtedy ich suma.
    """
    table = _table(text or "")
    if table is None:
        return None
    columns, cells = table
    if "total" not in columns:
        return None
    rates = {row.rate_client for row in extract_rows(text) if row.rate_client}
    # Kwoty po rozdzieleniu sklejonej liczby MD — surowe ``cells`` niosłyby
    # „10 840,00" zamiast stawki 840,00 (runda 6 audytu).
    buffers, leftover = _buffers(text, columns, cells)
    amounts = [*leftover, *(value for _, moneys, _, _ in buffers for value in moneys)]
    others = [value for value in amounts if value not in rates]
    distinct = list(dict.fromkeys(others))
    if not distinct:
        return None
    if len(distinct) == 1:
        return distinct[0]
    return sum(distinct, Decimal("0"))


def apply_polkomtel_order_policy(
    result: OrderExtraction,
    document_text: str,
    *,
    target_consultant: Optional[str] = None,
    target_given_names: Optional[str] = None,
) -> OrderExtraction:
    if not is_executive_order(document_text):
        # Aneks, zamówienie okresowe albo inny szablon: reguły „Zlecenia
        # wykonawczego" (bezterminowo, stawka za MD, kwota zlecenia) mogłyby tu
        # przepisać poprawny odczyt. Zostaje odczyt ogólny — z jawną uwagą,
        # żeby nazwa reguły klienta przy odczycie nie udawała, że zadziałała.
        result.uncertain_reasons = [
            *result.uncertain_reasons,
            "Dokument nie ma nagłówka „ZLECENIE WYKONAWCZE nr …” — reguły odczytu "
            "Polkomtela nie zostały zastosowane, sprawdź wszystkie pola",
        ]
        result.uncertain = True
        return result

    reasons: list[str] = []
    model_rows = list(result.consultant_rows)

    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    else:
        clear_field(result, "title")
        result.title_needs_review = True
        reasons.append(
            "Nie znaleziono numeru w linii „ZLECENIE WYKONAWCZE nr …” — sprawdź "
            "numer zamówienia"
        )

    start = signing_date(document_text)
    if start:
        set_field(result, "start_date", start)
    else:
        clear_field(result, "start_date")
        reasons.append(
            "Nie znaleziono daty „zawarte w dniu …” — wpisz datę rozpoczęcia ręcznie"
        )
    # Bezterminowo z reguły klienta — koniec wyznacza wyczerpanie kwoty albo MD.
    clear_field(result, "end_date")

    amount = order_amount(document_text)
    in_table = table_total(document_text)
    total = amount if amount is not None else in_table
    if total is not None:
        set_field(result, "total_value", total)
        result.currency = "PLN"
    else:
        clear_field(result, "total_value")
    if _FOREIGN_MONEY_RE.search(document_text or ""):
        # „Cena netto … [PLN]" to kontrakt szablonu; kwoty w innej walucie
        # nie są czytane jako stawki — człowiek musi je ocenić.
        reasons.append(
            "W dokumencie są kwoty w innej walucie niż PLN — sprawdź stawki "
            "i kwotę zamówienia"
        )
    if amount is not None and in_table is not None and amount != in_table:
        reasons.append(
            f"Kwota zlecenia („na kwotę” {amount}) różni się od kolumny „Cena total” "
            f"({in_table}) — sprawdź kwotę zamówienia"
        )

    rows, table_reasons = _parse_table(document_text)
    reasons.extend(table_reasons)
    reasons.extend(_cross_check_with_model(rows, model_rows))
    result.consultant_ref = None
    result.rate_client_md = None
    result.rate_client_gross = None
    if rows:
        result.consultant_rows = rows
    else:
        reasons.append(
            "Nie rozpoznano tabeli konsultantów („Cena netto 1MD” / „Konsultant”) "
            "— porównaj osoby i stawki z dokumentem"
        )
    set_field(result, "rate_unit", "day")
    if len(rows) == 1 and not rows[0].uncertain:
        set_field(result, "rate_client", rows[0].rate_client)
        result.consultant_rate_matched = True
    else:
        # Kilka osób: stawka istnieje wyłącznie per wiersz.
        clear_field(result, "rate_client")
        result.consultant_rate_matched = False

    # MD w dwóch wariantach: przy każdej osobie (kolumna) albo jedna liczba na
    # całe zlecenie. Brak obu to poprawny odczyt zamówienia kosztowego.
    pool_md = order_md(document_text)
    if pool_md is not None and not any(row.md_total is not None for row in rows):
        set_field(result, "md_total", pool_md)
    elif len(rows) == 1 and rows[0].md_total is not None:
        set_field(result, "md_total", rows[0].md_total)
        result.consultant_md_matched = True
    else:
        clear_field(result, "md_total")
        result.consultant_md_matched = False

    # Numer, okres, kwota i tabela są odczytem deterministycznym — zastępują
    # zastrzeżenia modelu, który czytał ten sam dokument bez reguł klienta
    # (m.in. „brak informacji o liczbie MD" przy zamówieniu kosztowym).
    reasons.extend(row.uncertain_reason for row in rows if row.uncertain_reason)
    result.uncertain_reasons = reasons
    if target_consultant and rows:
        # Odczyt z karty jednej osoby („Dodaj konsultanta"): stawka z JEJ
        # wiersza tabeli — jak u BIK. Brak jednoznacznego wiersza czyści stawkę.
        result = apply_consultant_row_match(
            result,
            target_consultant,
            consultant_given_names=target_given_names,
            rate_unit_default="day",
        )
    result.uncertain = bool(result.uncertain_reasons)
    return result


_EXECUTIVE_ORDER_RE = re.compile(NUMBER_LABEL + r"[^\S\n]+nr\b", re.IGNORECASE)


def is_executive_order(text: str) -> bool:
    """Czy dokument jest „Zleceniem wykonawczym nr …" — tylko wtedy reguły działają."""
    return bool(_EXECUTIVE_ORDER_RE.search(text or ""))


def _cross_check_with_model(
    rows: list[ConsultantOrderRow], model_rows: list[ConsultantOrderRow]
) -> list[str]:
    """Niezależne potwierdzenie tabeli: odczyt modelu tego samego dokumentu.

    Reguła tabeli zastępuje wiersze modelu, więc bramka poczty porównywałaby
    tabelę z samą sobą. Tu model jest drugim, niezależnym czytelnikiem: gdy
    podał stawkę tej samej osoby i jest ona inna niż w tabeli — albo zna osobę,
    której tabela nie ma — wiersz idzie do sprawdzenia. Brak stawki u modelu
    niczego nie rozstrzyga (model zeruje stawki przy niepewności).
    """
    if not model_rows or not rows:
        return []
    reasons: list[str] = []
    for index, row in enumerate(rows, start=1):
        same = [
            model
            for model in model_rows
            if model.consultant_name
            and _names_exactly_equivalent(model.consultant_name, row.consultant_name)
        ]
        if len(same) != 1:
            continue
        model = same[0]
        if (
            model.rate_client is not None
            and model.rate_unit in (None, "day")
            and row.rate_client is not None
            and model.rate_client != row.rate_client
        ):
            row.uncertain = True
            note = (
                f"stawka z tabeli ({row.rate_client}) różni się od odczytu AI "
                f"({model.rate_client}) — sprawdź, która jest właściwa"
            )
            row.uncertain_reason = (
                f"{row.uncertain_reason}; {note}"
                if row.uncertain_reason
                else f"{index}. osoba w tabeli: {note}"
            )
    missing = [
        model.consultant_name
        for model in model_rows
        if model.consultant_name
        and not any(
            _names_exactly_equivalent(model.consultant_name, row.consultant_name)
            for row in rows
        )
    ]
    if missing:
        reasons.append(
            "Odczyt AI wskazuje osoby, których nie ma w odczycie tabeli ("
            + ", ".join(f"„{name}”" for name in missing)
            + ") — porównaj listę konsultantów z dokumentem"
        )
    return reasons


def apply_rate_rules(
    result: OrderExtraction, document_text: str
) -> Optional[OrderExtraction]:
    """„Cena netto 1MD po upuście" — stawka Polkomtela jest zawsze NETTO.

    Idempotentne jak u Nordei, PKO BP i Aliora: odczyt, który przeszedł już
    ÷ 1,23 (zapisany przed regułą, wiersze modelu bez tabeli), wraca do kwoty
    z PDF-a. Samo zerowanie oryginału zostawiało zaniżoną stawkę netto
    bez śladu przeliczenia (audyt 24.09, N3).

    Wyłącznie w „Zleceniu wykonawczym nr …" (jak reszta reguł tego klienta
    i jak BIK sprawdza swój nagłówek). Inny szablon zwraca ``None`` — o rodzaju
    stawki decyduje ogólne rozpoznanie brutto/netto; „zawsze netto" podnosiło
    tam kwotę brutto o VAT (audyt 24.09.2026).
    """
    if not is_executive_order(document_text):
        return None
    for item in [result, *result.consultant_rows]:
        if item.rate_client_gross is not None:
            item.rate_client, item.rate_client_gross = item.rate_client_gross, None
    result.confidence.pop("rate_client_gross", None)
    return result


# ── Cyfrowy Polsat: ten sam szablon „Zlecenie wykonawcze", sama reguła numeru ──

CYFROWY_POLSAT_CANONICAL_CLIENT_IDS: frozenset[int] = frozenset({38339})
CYFROWY_POLSAT_CLIENT_IDS_ENV = "CYFROWY_POLSAT_ORDER_EXTRACTION_CLIENT_IDS"


def apply_cyfrowy_polsat_order_number(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    """„CP 1234" z „ZLECENIE WYKONAWCZE nr CP 1234 / 2031 rok".

    Wyłącznie numer: Cyfrowy Polsat ma też zamówienia okresowe, więc okres
    i stawki zostają przy odczycie ogólnym. Brak linii z numerem nie czyści
    odczytu modelu — reguła niczego nie zgaduje w dokumencie innego kształtu.
    """
    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    return result
