"""Biuro Informacji Kredytowej (BIK) — zamówienie SAP z pozycjami per konsultant.

Układ z pipeline'u (pdfplumber; PDF z SAP-a gubi spacje między wyrazami, więc
nazwisko bywa sklejone z imieniem i z kodem profilu)::

    Numer/datazamówienia
    02-486 Warszawa                              ← adres w tej samej kolumnie
    4500067890/20260819                          ← NUMER / DATA (RRRRMMDD)
    TERMIN DOSTAWY
    01.11.2026                                   ← NIE jest końcem zamówienia
    Na fakturze proszę powołać się na nr zamówienia : 4500067890
    Poz.Przedmiot Ilośćzamów. Jedn. Cenajednostk. Wart.netto
    10 RozwójProduktówPożyczkowychJ.Kowalski 64,000 SZT 1.200,00 76.800,00
    ProfilUR-JanKowalski
    Obowiązująca stawkazaosobęwynosi1200,-zł/MD
    Wwymiarze64MD(roboczodni).RozliczeniewtrybieT&M.
    20 …
    Łącz.wart.nettobezVAT 245.200,00 PLN

Reguły (ticket 09.2026):

* **wspólne dla zamówienia** — numer to część „Numer/data zamówienia" przed
  ukośnikiem, data (po ukośniku) jest datą ROZPOCZĘCIA; koniec zamówienia jest
  zawsze bezterminowy (zamówienie BIK kończy wyczerpanie limitu MD, nie data —
  patrz ``order_md_exhaustion``). „Termin dostawy" świadomie pomijamy: to po
  nim model zgadywał datę końca;
* **per pozycja** — każda linia „Poz." to jeden konsultant: liczba z kolumny
  „Ilość zamów." (jednostka SZT) jest jego limitem MD, „Cena jednostk." jego
  stawką przychodową PLN/MD. „Wart.netto" i „Łącz. wart. netto" NIE są
  przenoszone do zamówienia — iloczyn służy wyłącznie kontroli odczytu;
* **nazwisko** — gdziekolwiek w treści pozycji, z myślnikiem albo bez niego.
  Kotwicą jest linia „Profil …"; bez niej szukamy dokładnie jednego ciągu
  dwóch wyrazów pisanych wielką literą. Czego nie da się jednoznacznie ustalić,
  zostaje PUSTE z powodem po polsku — pozycja z pustym nazwiskiem nie przejdzie
  bramki automatu, a writer maila odmówi założenia osoby bez imienia i nazwiska.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Optional

from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clear_field,
    fold,
    normalize_amount,
    set_field,
)
from app.services.order_pdf_parser import (
    _name_match_score,
    apply_consultant_row_match,
)

#: Produkcyjne ID klienta BIK (ticket korekty 29.08.2026; to samo ID przypina
#: ``order_types._PINNED_ALLOWED_ORDER_TYPES``). Env dopisuje duplikat rekordu
#: w innym środowisku — jedna zmienna steruje odczytem PDF i końcem zamówienia.
CANONICAL_CLIENT_IDS: frozenset[int] = frozenset({18})
CLIENT_IDS_ENV = "BIK_ORDER_CLIENT_IDS"

# ── Numer i data zamówienia ──────────────────────────────────────────────────

_NUMBER_DATE_LABEL_RE = re.compile(r"Numer\s*/\s*data\s*zam[óo]wienia", re.IGNORECASE)
# „4500067890/20260819" — numer i data RRRRMMDD rozdzielone ukośnikiem. Poza
# cyframi i ukośnikiem po obu stronach, żeby nie kroić dłuższych identyfikatorów.
_NUMBER_DATE_RE = re.compile(r"(?<![\d/])(\d{5,12})\s*/\s*(\d{8})(?![\d/])")
# Etykieta w nagłówku i właściwa wartość są rozdzielone kolumną adresu
# („02-486 Warszawa"), więc szukamy w oknie za etykietą, nie w tej samej linii.
_LABEL_WINDOW = 400
_INVOICE_NUMBER_RE = re.compile(
    r"nr\s*zam[óo]wienia\s*[:.]?\s*(\d{5,12})(?!\d)", re.IGNORECASE
)

# ── Tabela pozycji ───────────────────────────────────────────────────────────

_QTY = r"\d{1,3}(?:[.\u00a0 ]\d{3})*(?:,\d{1,3})?"
_MONEY = r"\d{1,3}(?:[.\u00a0 ]\d{3})*,\d{2}"
_ROW_RE = re.compile(
    rf"^[ \t]*(?P<pos>\d{{1,4}})[ \t]+(?P<desc>\S.*?)[ \t]+(?P<qty>{_QTY})[ \t]+"
    rf"(?P<unit>[A-Za-zŁł\-]{{1,6}}\.?)[ \t]+(?P<price>{_MONEY})"
    rf"(?:[ \t]+(?P<net>{_MONEY}))?[ \t]*$",
    re.MULTILINE,
)
_TABLE_END_RE = re.compile(
    r"^[ \t]*(?:_{5,}|[ŁL][aą]cz\.?\s*wart|Zam[óo]wienie\s*do\s*umowy)",
    re.IGNORECASE | re.MULTILINE,
)
#: Jednostki, które BIK stosuje dla limitu MD. Ticket: „SZT" = MD.
_MD_UNITS = frozenset({"szt", "szt.", "md"})
_NET_HEADER_RE = re.compile(r"Wart\.?\s*netto|netto\s*bez\s*VAT", re.IGNORECASE)

# Kontrola krzyżowa z prozą pozycji — wyłącznie ostrzega, nie nadpisuje.
_PROSE_RATE_RE = re.compile(
    r"wynosi\s*(\d{1,3}(?:[.\u00a0 ]?\d{3})*(?:,\d{2})?)\s*(?:,\s*-)?\s*z[łl]\s*/\s*MD",
    re.IGNORECASE,
)
_PROSE_MD_RE = re.compile(r"wymiarze\s*(\d+(?:[.,]\d+)?)\s*MD", re.IGNORECASE)

# ── Imię i nazwisko ──────────────────────────────────────────────────────────

_UPPER = "A-ZĄĆĘŁŃÓŚŹŻÄÖÜÉ"
_LOWER = "a-ząćęłńóśźżäöüéè"
_NAME_WORD_RE = re.compile(rf"[{_UPPER}][{_LOWER}]+")
_COMPOUND_NAME_RE = re.compile(rf"[{_UPPER}][{_LOWER}]+-[{_UPPER}][{_LOWER}]+")
_INITIAL_SURNAME_RE = re.compile(
    rf"(?<![{_UPPER}{_LOWER}])([{_UPPER}])\.\s?([{_UPPER}][{_LOWER}]+)"
)
_PROFILE_RE = re.compile(r"\bProfil\b", re.IGNORECASE)
_DASH_RE = re.compile(r"[-–—]")
#: Wyrazy z wielkiej litery, które w pozycjach BIK nie są nazwiskami. Służą
#: wyłącznie ścieżce BEZ linii „Profil" — przy niej nazwisko stoi za kotwicą.
_NOT_A_NAME = frozenset(
    fold(word)
    for word in (
        "Profil",
        "Obowiązująca",
        "Stawka",
        "Rozliczenie",
        "Rozwój",
        "Wsparcie",
        "Utrzymanie",
        "Usługa",
        "Usługi",
        "Zamówienie",
        "Pozycja",
        "Przedmiot",
        "Projekt",
        "Analiza",
        "Specjalista",
        "Konsultant",
        "Programista",
        "Wymiarze",
        "Senior",
        "Junior",
        "Regular",
    )
)


def _split_glued(text: str) -> str:
    """Rozdziel wyrazy sklejone przez PDF z SAP-a („ProfilUR-JanKowalski").

    Granicą jest przejście mała→wielka litera, koniec skrótu przed wyrazem
    („URKrzysztof" → „UR Krzysztof") i kropka inicjału („J.Kowalski").
    """
    text = re.sub(rf"(?<=[{_LOWER}])(?=[{_UPPER}])", " ", text)
    text = re.sub(rf"(?<=[{_UPPER}])(?=[{_UPPER}][{_LOWER}])", " ", text)
    return re.sub(rf"(?<=[{_UPPER}]\.)(?=[{_UPPER}])", " ", text)


def _is_capitalized(token: str) -> bool:
    return bool(_NAME_WORD_RE.fullmatch(token) or _COMPOUND_NAME_RE.fullmatch(token))


def _is_name_word(token: str) -> bool:
    return _is_capitalized(token) and fold(token) not in _NOT_A_NAME


def _tokens(text: str) -> list[str]:
    """Wyrazy linii; myślnik i interpunkcja są osobnymi tokenami-separatorami.

    ``-`` = myślnik (separator profilu od osoby), ``|`` = przecinek, dwukropek,
    nawias — rozdziela sąsiednie osoby („Jan Nowak, Piotr Zieliński").
    Wyjątek: nazwisko dwuczłonowe („Nowak-Kowalska") zostaje jednym tokenem —
    myślnik między DWOMA wyrazami z wielkiej litery nie jest separatorem.
    """
    out: list[str] = []
    for chunk in re.split(r"(\s+|[,;:()/]+)", _split_glued(text)):
        if not chunk or chunk.isspace():
            continue
        if re.fullmatch(r"[,;:()/]+", chunk):
            out.append("|")
        elif _DASH_RE.search(chunk) and not _COMPOUND_NAME_RE.fullmatch(chunk):
            for index, part in enumerate(_DASH_RE.split(chunk)):
                if index:
                    out.append("-")
                if part:
                    out.append(part)
        else:
            out.append(chunk)
    return out


def _capital_runs(tokens: list[str]) -> list[tuple[int, list[str]]]:
    """Maksymalne ciągi wyrazów z wielkiej litery: ``(indeks startu, wyrazy)``.

    Ciąg liczymy po WSZYSTKICH wyrazach z wielkiej litery (także „Rozwój"),
    a dopiero potem sprawdzamy, czy to osoba: dzięki temu opis pozycji
    „Rozwój Strumienia Detalicznego" jest jedną frazą z trzech wyrazów, a nie
    „nazwiskiem" „Strumienia Detalicznego" po odcięciu pierwszego wyrazu.
    """
    runs: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 0
    for index, token in enumerate(tokens):
        if _is_capitalized(token):
            if not current:
                start = index
            current.append(token)
        elif current:
            runs.append((start, current))
            current = []
    if current:
        runs.append((start, current))
    return runs


def _is_person(run: list[str], *, max_words: int) -> bool:
    return 2 <= len(run) <= max_words and all(_is_name_word(t) for t in run)


def _name_from_profile_line(line: str) -> tuple[Optional[str], Optional[str]]:
    """Nazwisko z linii „Profil <kod> [-] Imię Nazwisko"; ``(nazwa, powód)``.

    ``(None, None)`` = w linii nie ma „Profil". Linia z „Profil", z której nie
    da się odczytać osoby, zwraca powód — i jest wiążąca: nie szukamy wtedy
    nazwiska gdzie indziej, bo BIK wskazuje osobę właśnie w tej linii.
    """
    line = _split_glued(line)
    match = _PROFILE_RE.search(line)
    if match is None:
        return None, None
    tokens = _tokens(line[match.end() :])
    if "-" in tokens:
        last_dash = len(tokens) - 1 - tokens[::-1].index("-")
        runs = _capital_runs(tokens[last_dash + 1 :])
        run = runs[0][1] if runs and runs[0][0] == 0 else []
        if _is_person(run, max_words=3):
            return " ".join(run), None
        return None, "po myślniku w linii „Profil” nie ma imienia i nazwiska"
    runs = _capital_runs(tokens)
    if not runs:
        return None, "linia „Profil” nie zawiera imienia i nazwiska"
    run = runs[-1][1]
    if _is_person(run, max_words=2):
        return " ".join(run), None
    return None, (
        f"w linii „Profil” nie da się oddzielić profilu od osoby („{' '.join(run)}”)"
    )


def _initial_and_surname(text: str) -> Optional[tuple[str, str]]:
    """Podpis inicjałem w opisie pozycji („J.Kowalski" → ``("J", "Kowalski")``)."""
    match = _INITIAL_SURNAME_RE.search(_split_glued(text))
    return (match.group(1), match.group(2)) if match else None


def _fits_initial(name: str, initial: tuple[str, str]) -> bool:
    tokens = name.split()
    surnames = {fold(part) for part in tokens[-1].split("-")}
    return fold(initial[1]) in surnames and fold(tokens[0][:1]) == fold(initial[0])


def _name_from_free_text(
    lines: list[str], initial: Optional[tuple[str, str]]
) -> tuple[Optional[str], Optional[str]]:
    """Bez linii „Profil": dokładnie jeden ciąg dwóch wyrazów z wielkiej litery.

    Ciąg trzech wyrazów przyjmujemy tylko za myślnikiem (dwa imiona). Podpis
    inicjałem z opisu pozycji zawęża kandydatów — opis bywa ciągiem dwóch
    rzeczowników z wielkiej litery („Produktów Pożyczkowych").
    """
    found: dict[str, str] = {}
    for line in lines:
        tokens = _tokens(line)
        for start, run in _capital_runs(tokens):
            after_dash = start > 0 and tokens[start - 1] == "-"
            if _is_person(run, max_words=3 if after_dash else 2):
                name = " ".join(run)
                found.setdefault(fold(name), name)
    candidates = list(found.values())
    if initial is not None:
        candidates = [name for name in candidates if _fits_initial(name, initial)]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, "w treści pozycji nie znaleziono imienia i nazwiska"
    return None, (
        "w treści pozycji jest kilka możliwych osób ("
        + ", ".join(f"„{name}”" for name in candidates)
        + ")"
    )


def _consultant_name(desc: str, block_lines: list[str]) -> tuple[str, Optional[str]]:
    """Imię i nazwisko z treści pozycji; ``("", powód)``, gdy niejednoznaczne."""
    lines = [desc, *block_lines]
    initial = _initial_and_surname(desc)
    name: Optional[str] = None
    profile_reason: Optional[str] = None
    for line in lines:
        name, profile_reason = _name_from_profile_line(line)
        if profile_reason:
            return "", profile_reason
        if name:
            break
    if name is None:
        name, free_reason = _name_from_free_text(lines, initial)
        if name is None:
            return "", free_reason
    if initial is not None and not _fits_initial(name, initial):
        return "", (
            f"inicjał i nazwisko w opisie („{initial[0]}. {initial[1]}”) nie "
            f"zgadzają się z osobą z profilu („{name}”)"
        )
    return name, None


# ── Odczyt ───────────────────────────────────────────────────────────────────


def _iso_from_compact(value: str) -> Optional[str]:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])).isoformat()
    except ValueError:
        return None


def order_number_and_date(text: str) -> tuple[Optional[str], Optional[str]]:
    """``(numer, data ISO)`` z pola „Numer/data zamówienia"."""
    text = text or ""
    label = _NUMBER_DATE_LABEL_RE.search(text)
    match = None
    if label is not None:
        match = _NUMBER_DATE_RE.search(text, label.end(), label.end() + _LABEL_WINDOW)
    if match is None:
        match = _NUMBER_DATE_RE.search(text)
    if match is None:
        return None, None
    return match.group(1), _iso_from_compact(match.group(2))


def invoice_order_number(text: str) -> Optional[str]:
    """Numer z „Na fakturze proszę powołać się na nr zamówienia : …"."""
    match = _INVOICE_NUMBER_RE.search(text or "")
    return match.group(1) if match else None


def _amount(value: Optional[str]) -> Optional[Decimal]:
    return (
        normalize_amount(value.replace(" ", "").replace("\u00a0", ""))
        if value
        else None
    )


def _row_checks(
    unit: str,
    md: Optional[Decimal],
    rate: Optional[Decimal],
    net: Optional[Decimal],
    block: str,
) -> list[str]:
    """Kontrole odczytu pozycji. Ostrzegają — żadna nie nadpisuje wartości."""
    reasons: list[str] = []
    if fold(unit) not in _MD_UNITS:
        reasons.append(
            f"nieoczekiwana jednostka „{unit}” — w zamówieniach BIK liczba "
            "w kolumnie „Ilość zamów.” to MD (jednostka SZT)"
        )
    if md is None or md <= 0 or rate is None or rate <= 0:
        reasons.append("nieczytelna liczba MD albo cena jednostkowa")
        return reasons
    # „Wart.netto" nie trafia do zamówienia; iloczyn potwierdza tylko, że liczba
    # MD i cena zostały odczytane z tej samej pozycji bez przekłamania cyfr.
    if net is not None and abs(md * rate - net) > Decimal("0.01"):
        reasons.append(
            f"ilość × cena ({md.normalize()} × {rate}) nie zgadza się z wartością "
            f"netto pozycji ({net}) — sprawdź liczbę MD i stawkę"
        )
    prose_rate = _PROSE_RATE_RE.search(block)
    if prose_rate and _amount(prose_rate.group(1)) != rate:
        reasons.append(
            f"stawka w opisie ({prose_rate.group(1)} zł/MD) różni się od ceny "
            f"jednostkowej z tabeli ({rate})"
        )
    prose_md = _PROSE_MD_RE.search(block)
    if prose_md and normalize_amount(prose_md.group(1)) != md:
        reasons.append(
            f"liczba MD w opisie ({prose_md.group(1)}) różni się od ilości "
            f"z tabeli ({md.normalize()})"
        )
    return reasons


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    """Pozycje konsultantów (deterministycznie, każda z WŁASNYM limitem i stawką)."""
    text = text or ""
    _, start = order_number_and_date(text)
    matches = list(_ROW_RE.finditer(text))
    rows: list[ConsultantOrderRow] = []
    for index, match in enumerate(matches):
        block_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(text)
        )
        table_end = _TABLE_END_RE.search(text, match.end(), block_end)
        if table_end is not None:
            block_end = table_end.start()
        block = text[match.end() : block_end]
        block_lines = [line.strip() for line in block.splitlines() if line.strip()]
        pos = match.group("pos")
        md = _amount(match.group("qty"))
        rate = _amount(match.group("price"))
        net = _amount(match.group("net"))
        name, name_reason = _consultant_name(match.group("desc"), block_lines)
        reasons = _row_checks(match.group("unit"), md, rate, net, block)
        if name_reason:
            reasons.insert(
                0,
                "nie udało się jednoznacznie odczytać imienia i nazwiska konsultanta "
                f"— {name_reason}",
            )
        rows.append(
            ConsultantOrderRow(
                consultant_name=name,
                md_total=md,
                rate_client=rate,
                rate_unit="day",
                start_date=start,
                end_date=None,
                uncertain=bool(reasons),
                uncertain_reason=(
                    f"Pozycja {pos}: " + "; ".join(reasons) if reasons else None
                ),
            )
        )
    return rows


def apply_bik_order_policy(
    result: OrderExtraction,
    document_text: str,
    *,
    target_consultant: Optional[str] = None,
    target_given_names: Optional[str] = None,
) -> OrderExtraction:
    reasons: list[str] = []
    number, order_date = order_number_and_date(document_text)
    invoice_number = invoice_order_number(document_text)
    if number is None and invoice_number is not None:
        number = invoice_number
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
        if invoice_number and invoice_number != number:
            reasons.append(
                f"Numer z pola „Numer/data zamówienia” ({number}) różni się od numeru "
                f"do powołania na fakturze ({invoice_number}) — sprawdź numer"
            )
    else:
        clear_field(result, "title")
        result.title_needs_review = True
        reasons.append(
            "Nie znaleziono pola „Numer/data zamówienia” — sprawdź numer zamówienia"
        )

    if order_date:
        set_field(result, "start_date", order_date)
    else:
        clear_field(result, "start_date")
        reasons.append(
            "Nie znaleziono daty zamówienia (część po ukośniku w „Numer/data "
            "zamówienia”) — wpisz datę rozpoczęcia ręcznie"
        )
    # Bezterminowo z reguły klienta — koniec wyznacza wyczerpanie limitu MD.
    clear_field(result, "end_date")
    # „Łącz. wart. netto" nie jest budżetem zamówienia MD.
    clear_field(result, "total_value")
    result.currency = "PLN"
    result.consultant_ref = None
    result.rate_client_md = None
    result.rate_client_gross = None

    rows = extract_rows(document_text)
    result.consultant_rows = rows
    # Każda cena jednostkowa BIK jest za 1 MD — jednostka jest wspólna.
    set_field(result, "rate_unit", "day")
    if len(rows) == 1 and not rows[0].uncertain:
        set_field(result, "rate_client", rows[0].rate_client)
        set_field(result, "md_total", rows[0].md_total)
        result.consultant_rate_matched = True
        result.consultant_md_matched = True
    else:
        # Wiele osób: stawka i limit MD istnieją wyłącznie per pozycja.
        clear_field(result, "rate_client")
        clear_field(result, "md_total")
        result.consultant_rate_matched = False
        result.consultant_md_matched = False
    if not rows:
        reasons.append(
            "Nie rozpoznano pozycji zamówienia (Poz. / Ilość zamów. / Cena jednostk.) "
            "— wpisz konsultantów ręcznie"
        )
    row_reasons = [row.uncertain_reason for row in rows if row.uncertain_reason]

    # Pola wspólne i tabela pozycji są odczytem deterministycznym — zastępują
    # zastrzeżenia modelu, który interpretował ten sam dokument bez reguł BIK.
    result.uncertain_reasons = reasons
    if target_consultant:
        # Odczyt z karty jednej osoby: zastrzeżenia do CUDZYCH pozycji są
        # szumem — chyba że właśnie przez nie tej osoby nie udało się znaleźć.
        hits = [
            row
            for row in rows
            if row.consultant_name
            and _name_match_score(
                target_consultant,
                row.consultant_name,
                consultant_given_names=target_given_names,
            )
            is not None
        ]
        if len(hits) != 1:
            result.uncertain_reasons.extend(row_reasons)
        result = apply_consultant_row_match(
            result,
            target_consultant,
            consultant_given_names=target_given_names,
            rate_unit_default="day",
        )
    else:
        result.uncertain_reasons.extend(row_reasons)
    result.uncertain = bool(result.uncertain_reasons)
    return result


def apply_rate_rules(
    result: OrderExtraction, document_text: str
) -> Optional[OrderExtraction]:
    """Ceny jednostkowe BIK są netto — kolumna obok to „Wart.netto".

    Zwraca ``None``, gdy dokument nie niesie tego nagłówka: wtedy o rodzaju
    stawki decyduje ogólne rozpoznanie brutto/netto (``apply_document_rate_kind``).
    """
    if not _NET_HEADER_RE.search(document_text or ""):
        return None
    result.rate_client_gross = None
    for row in result.consultant_rows:
        row.rate_client_gross = None
    return result
