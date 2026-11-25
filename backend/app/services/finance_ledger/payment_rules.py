"""Przelewy faktur kosztowych (E3) — reguły bez bazy.

* **Tryb przelewu** z flag kolejki: „Zapłata na konto US” = przelew na rachunek
  urzędu (rachunek tylko ręcznie), „MPP” = podzielona płatność, „NIE MPP” =
  zwykły; bez flag — MPP, gdy faktura w złotych ma co najmniej 15 000 zł
  brutto (wskazówka do potwierdzenia przy paczce, nie decyzja). MPP tylko
  w złotych.
* **Tytuł**: numer faktury i numer KSeF w osobnych liniach (Elixir-O: 4 × 35
  znaków; numer KSeF ma 35 znaków, więc nie jest cięty). Od 1.01.2027 numer
  KSeF przy fakturze z KSeF jest obowiązkowy (art. 108g VAT) — brak blokuje
  wiersz. Decyduje data płatności (data wykonania paczki), nie dzień planu.
  Jeden przelew płaci jedną fakturę, więc zbiorczy identyfikator KSeF nie jest
  potrzebny. MPP:
  ``/VAT/{vat}/IDC/{NIP}/INV/{numer}/TXT/{tekst}`` (VAT z przecinkiem,
  w ``TXT`` numer KSeF, a bez niego numer faktury).
* **Biała lista**: rachunek spoza wykazu (albo niesprawdzony) przy fakturze
  powyżej 15 000 zł brutto to ostrzeżenie, które ktoś musi świadomie odhaczyć
  (art. 117ba Ordynacji i art. 15d CIT). Tryb ``off`` = „nie sprawdzono”.
* **Art. 105a VAT**: od tego dostawcy w miesiącu ponad 50 000 zł netto, a ta
  faktura poniżej progu MPP — podpowiedź „rozważ MPP” (solidarna
  odpowiedzialność za usługi z zał. 16, np. PKWiU 62.01; jej nie ma przy
  zapłacie w MPP). Bez XML-a kosztów nie znamy PKWiU, więc to tylko wskazówka.
* **Obciążenie z wyciągu** → wpis: numer KSeF w tytule, potem numer faktury
  (całym słowem albo pole ``/INV/``; wspólny numer wielu dostawców
  rozstrzyga rachunek, NIP z ``/IDC/`` albo nazwa odbiorcy), potem pozycja
  paczki (ten sam rachunek i kwota). Kwota równa pozostałej = zapłacona; mniejsza przy wskazanej
  fakturze = częściowa; większa, faktura opłacona albo kilka pasujących =
  „do sprawdzenia”.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.services.client_invoicing.payments import mpp_vat
from app.services.hr.bank.accounts import AccountError, normalize_nrb
from app.services.hr.bank.parsed import StatementLine
from app.services.hr.bank.titles import (
    KSEF_TITLE_FROM,
    KSEF_TITLE_LABELS,
    LINE_LENGTH,
    MAX_LINES,
    clean,
    ksef_numbers_in,
    number_in_title,
)

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
MPP_THRESHOLD = Decimal("15000.00")
WHITE_LIST_THRESHOLD = Decimal("15000.00")
ART_105A_MONTHLY_NET = Decimal("50000.00")

#: Powody, dla których wiersz nie może wejść do paczki.
BLOCK_LABELS: dict[str, str] = {
    "payroll_path": "Faktura osoby zespołu — zapłatę prowadzą Płace (rozliczenie miesiąca).",
    "stage": "Faktura nie jest przyjęta do kolejki (poczekalnia albo odrzucona).",
    "hold": "Flaga „Wstrzymać płatność”.",
    "duplicate": "Flaga „Duplikat”.",
    "paid": "Już zapłacona.",
    "in_batch": "Już w paczce, która czeka (nieaktualną paczkę anuluj).",
    "no_amount": "Brak kwoty brutto do zapłaty.",
    "no_account": "Brak rachunku odbiorcy — wpisz go na karcie faktury.",
    "bad_account": "Rachunek odbiorcy ma zły format albo sumę kontrolną.",
    "domestic_account": "Przelew w złotych idzie na rachunek krajowy (26 cyfr).",
    "tax_office_manual": "„Zapłata na konto US” — rachunek urzędu wpisz ręcznie na karcie.",
    "no_invoice_number": "Brak numeru faktury do tytułu przelewu.",
    "no_ksef_number": KSEF_TITLE_LABELS["no_ksef_number"],
    "mpp_currency": "Podzielona płatność (MPP) działa tylko w złotych.",
    "mpp_no_nip": "MPP wymaga NIP-u sprzedawcy.",
    "mpp_no_vat": "MPP wymaga kwoty VAT z faktury.",
    "title_too_long": "Tytuł MPP nie mieści się w 4 liniach po 35 znaków.",
    "client_signature": "Zapłata czeka na podpis klienta na KEŚU (reguła rozliczeń klienta).",
    "correction": "Korekta — kwotę rozliczamy na fakturze pierwotnej, nie osobnym przelewem.",
    "correction_orphan": "Korekta (albo kwota ujemna) bez znanej faktury pierwotnej — "
    "sprawdź ręcznie, którą fakturę pomniejsza.",
    "corrected_out": "Faktura skorygowana do zera albo poniżej — nie ma czego płacić.",
    "dispute": "Spór / wstrzymane na rozliczeniu kontraktora — płatność czeka na "
    "zwolnienie.",
    "garnishment": "Zajęcie wierzytelności: kwoty dla organu nie da się policzyć — "
    "płatność czeka na decyzję księgowej.",
    "white_list_not_listed": "Rachunek kontraktora nie jest w wykazie VAT na dziś — "
    "płatność wstrzymana do powrotu rachunku do wykazu albo zmiany rachunku.",
    "white_list_unchecked": "Wykaz VAT nie odpowiedział — płatność kontraktora czeka "
    "na sprawdzenie rachunku (błąd wykazu to nie zgoda).",
}
#: Ostrzeżenia do świadomego odhaczenia przy tworzeniu paczki.
ACK_LABELS: dict[str, str] = {
    "white_list": "Rachunek nie jest potwierdzony w wykazie VAT, a faktura ma ponad "
    "15 000 zł brutto — zapłata może nie być kosztem i grozi solidarną "
    "odpowiedzialnością za VAT.",
    "client_signature": "Zapłata czeka na podpis klienta na KEŚU — reguła klienta "
    "ostrzega, nie blokuje (rozliczenia klientów).",
    "account_manual": "Rachunek wpisany ręcznie i niepotwierdzony w wykazie VAT — "
    "sprawdź go u dostawcy przed zapłatą (niezależnie od kwoty).",
    "mpp_suggested": "Faktura od 15 000 zł brutto bez flagi MPP / NIE MPP — sprawdź, "
    "czy podzielona płatność jest obowiązkowa (zał. 15).",
    "garnishment": "Zajęcie wierzytelności: część płatności idzie na rachunek organu "
    "— sprawdź podział przed paczką.",
    "double_payment": "Możliwa podwójna zapłata: inna faktura tego dostawcy ma tę samą "
    "kwotę albo ten sam numer — sprawdź przed paczką.",
}
HINT_LABELS: dict[str, str] = {
    "art_105a": "Od tego dostawcy w miesiącu ponad 50 000 zł netto — przy usługach "
    "z zał. 16 (np. PKWiU 62.01) rozważ MPP (art. 105a).",
    "ksef_from_2027": "Od 1.01.2027 numer KSeF w tytule będzie obowiązkowy.",
}
WHITE_LIST_LABELS: dict[str, str] = {
    "listed": "W wykazie VAT",
    "not_listed": "Brak w wykazie VAT",
    "unchecked": "Wykaz nie odpowiedział — niesprawdzony",
    "off": "Nie sprawdzono (sprawdzanie wyłączone)",
    "no_nip": "Nie sprawdzono (brak NIP-u)",
    "foreign": "Nie dotyczy (rachunek zagraniczny)",
    "tax_office": "Nie dotyczy (rachunek urzędu)",
    "skipped": "Nie sprawdzano (wiersz zablokowany)",
    "garnished": "Nie dotyczy (całość płatności idzie do organu)",
}
MODE_LABELS: dict[str, str] = {
    "standard": "Zwykły",
    "mpp": "MPP",
    "tax_office": "Konto US",
}
DEBIT_REASON_LABELS: dict[str, str] = {
    "amount_exceeds": "Kwota większa niż pozostało do zapłaty faktury.",
    "already_paid": "Faktura była już zapłacona — sprawdź, czy to nie podwójna zapłata.",
    "currency_differs": "Waluta przelewu inna niż waluta faktury.",
    "ambiguous": "Pasuje do kilku faktur — wybierz właściwą.",
    "amount_differs": "Numer faktury w tytule, ale kwota inna niż do zapłaty — "
    "sprawdź, czy to ta faktura.",
}


class PaymentRuleError(ValueError):
    """Wiersz nie może wejść do paczki; ``code`` z ``BLOCK_LABELS``."""

    def __init__(self, code: str) -> None:
        super().__init__(BLOCK_LABELS.get(code, code))
        self.code = code


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT)


# ── Rachunek ─────────────────────────────────────────────────────────────────

_SEPARATORS = re.compile(r"[\s\-.]+")


def _iban_valid(iban: str) -> bool:
    moved = iban[4:] + iban[:4]
    digits = "".join(str(int(char, 36)) for char in moved)
    remainder = 0
    for start in range(0, len(digits), 9):
        remainder = int(f"{remainder}{digits[start : start + 9]}") % 97
    return remainder == 1


def normalize_account(raw: Optional[str]) -> str:
    """Rachunek polski → 26 cyfr NRB; zagraniczny → IBAN wielkimi literami.

    Zły numer = ``PaymentRuleError('bad_account')`` (bez numeru w komunikacie).
    """

    value = _SEPARATORS.sub("", (raw or "").strip()).upper()
    if not value:
        raise PaymentRuleError("no_account")
    if value.isdigit() or value.startswith("PL"):
        try:
            return normalize_nrb(value)
        except AccountError as exc:
            raise PaymentRuleError("bad_account") from exc
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", value) or not _iban_valid(
        value
    ):
        raise PaymentRuleError("bad_account")
    return value


def is_domestic(account: str) -> bool:
    return account.isdigit() and len(account) == 26


def masked(account: Optional[str]) -> Optional[str]:
    return f"•• {account[-4:]}" if account else None


# ── Tryb i tytuł ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Mode:
    mode: str
    #: MPP wynika tylko z kwoty (bez flagi) — do potwierdzenia przy paczce.
    suggested: bool = False


def mode_for(flags: Iterable[str], gross: Decimal, currency: str) -> Mode:
    current = set(flags)
    if "tax_office_account" in current:
        return Mode("tax_office")
    if "mpp" in current:
        if currency != "PLN":
            raise PaymentRuleError("mpp_currency")
        return Mode("mpp")
    if "no_mpp" in current:
        return Mode("standard")
    if currency == "PLN" and gross >= MPP_THRESHOLD:
        return Mode("mpp", suggested=True)
    return Mode("standard")


def _vat_text(vat: Decimal) -> str:
    return f"{money(vat):.2f}".replace(".", ",")


def _chunks(text: str) -> list[str]:
    return [
        text[index : index + LINE_LENGTH] for index in range(0, len(text), LINE_LENGTH)
    ]


def title_lines(
    *,
    mode: str,
    invoice_number: Optional[str],
    ksef_number: Optional[str],
    from_ksef: bool,
    vat_amount: Optional[Decimal],
    seller_nip: Optional[str],
    pay_date: date,
) -> list[str]:
    """Linie tytułu (Elixir-O: najwyżej 4 po 35 znaków) albo ``PaymentRuleError``.

    ``pay_date`` — data płatności (wykonania przelewu): od niej zależy obowiązek
    numeru KSeF, nie od dnia, w którym ktoś składa paczkę.
    """

    number = clean(invoice_number or "")
    ksef = clean(ksef_number or "").upper() or None
    if from_ksef and not ksef and pay_date >= KSEF_TITLE_FROM:
        raise PaymentRuleError("no_ksef_number")
    if mode == "mpp":
        if not seller_nip:
            raise PaymentRuleError("mpp_no_nip")
        if vat_amount is None:
            raise PaymentRuleError("mpp_no_vat")
        if not number:
            raise PaymentRuleError("no_invoice_number")
        # Ukośnik jest separatorem komunikatu MPP — w numerze faktury go zostawiamy
        # (bank czyta pole INV do następnego „/XXX/”), ale bez znaków psujących plik.
        text_ = (
            f"/VAT/{_vat_text(vat_amount)}/IDC/{seller_nip}/INV/{number[:LINE_LENGTH]}"
            f"/TXT/{ksef or number[:LINE_LENGTH]}"
        )
        lines = _chunks(text_)
        if len(lines) > MAX_LINES:
            raise PaymentRuleError("title_too_long")
        return lines
    if not number and not ksef:
        raise PaymentRuleError("no_invoice_number")
    lines = [number[:LINE_LENGTH]] if number else []
    if ksef:
        lines.append(ksef[:LINE_LENGTH])
    return lines[:MAX_LINES]


def needs_white_list_ack(
    *, mode: str, currency: str, gross: Decimal, white_list_state: str
) -> bool:
    if mode == "tax_office" or currency != "PLN":
        return False
    return gross > WHITE_LIST_THRESHOLD and white_list_state != "listed"


def contractor_white_list_block(white_list_state: str) -> Optional[str]:
    """Faktura z dziennika „Kontraktorzy”: rachunek spoza wykazu VAT albo
    niesprawdzony (wykaz nie odpowiedział) blokuje płatność w dniu paczki,
    niezależnie od kwoty (decyzja Artura 23.11.2026). Tryb ``off``, brak
    NIP-u i rachunek zagraniczny zostają przy dotychczasowych ostrzeżeniach."""

    if white_list_state == "not_listed":
        return "white_list_not_listed"
    if white_list_state == "unchecked":
        return "white_list_unchecked"
    return None


def art_105a_hint(
    *, mode: str, gross: Decimal, currency: str, month_net: Optional[Decimal]
) -> bool:
    if mode == "mpp" or currency != "PLN" or month_net is None:
        return False
    return gross < MPP_THRESHOLD and month_net > ART_105A_MONTHLY_NET


# ── Obciążenie z wyciągu ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CostCandidate:
    """Faktura kosztowa w kształcie potrzebnym do dopasowania obciążenia."""

    entry_id: int
    currency: str
    gross: Decimal
    paid: Decimal
    invoice_number: Optional[str]
    ksef_number: Optional[str]
    #: Rachunki odbiorcy, które znamy (bieżący i z aktywnej pozycji paczki).
    accounts: frozenset[str] = field(default_factory=frozenset)
    #: Kwota aktywnej pozycji paczki (``None`` = poza paczką).
    batch_amount: Optional[Decimal] = None
    batch_account: Optional[str] = None
    #: Przelewy do organów z aktywnej pozycji paczki (zajęcie): (rachunek, kwota).
    batch_transfers: tuple[tuple[str, Decimal], ...] = ()
    #: NIP i nazwa sprzedawcy — rozstrzygają numer faktury wspólny dla wielu
    #: dostawców, gdy rachunku odbiorcy nie znamy (faktury z KSeF go nie mają).
    seller_nip: Optional[str] = None
    seller_name: Optional[str] = None

    @property
    def remaining(self) -> Decimal:
        return money(self.gross - self.paid)


@dataclass(frozen=True)
class DebitDecision:
    entry_id: Optional[int]
    related: bool
    reason: str
    amount: Optional[Decimal] = None
    candidates: tuple[int, ...] = ()

    @property
    def partial(self) -> bool:
        return self.reason.endswith("_partial")


_MPP_INV = re.compile(r"/INV/\s*([^/]+?)\s*(?:/|$)", re.IGNORECASE)
_MPP_IDC = re.compile(r"/IDC/\s*(\d{10})\s*/", re.IGNORECASE)
_WORD = re.compile(r"[a-z]{3,}")
#: Forma prawna i słowa z nazw wielu firm — nie odróżniają sprzedawców.
_NAME_NOISE = frozenset(
    "spolka akcyjna ograniczona odpowiedzialnoscia komandytowa jawna cywilna "
    "firma uslugi uslugowa consulting konsulting services group polska".split()
)


def _number_in_title(
    number: Optional[str], title: str, mpp_number: Optional[str]
) -> bool:
    if not number:
        return False
    if mpp_number and " ".join(number.split()).lower() == mpp_number.lower():
        return True
    return number_in_title(number, title)


def _shadowed(found: CostCandidate, others: Sequence[CostCandidate]) -> bool:
    """Numer zawarty w dłuższym numerze, który też jest w tytule („1/10/2026”
    w „FV/1/10/2026”) — tytuł wskazuje dłuższy."""

    mine = " ".join((found.invoice_number or "").split()).lower()
    return any(
        mine != theirs and mine in theirs
        for theirs in (
            " ".join((other.invoice_number or "").split()).lower() for other in others
        )
    )


def _name_words(name: Optional[str]) -> set[str]:
    plain = unicodedata.normalize("NFKD", (name or "").lower())
    text = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return set(_WORD.findall(text.replace("ł", "l"))) - _NAME_NOISE


def _same_seller(found: CostCandidate, counterparty_name: str) -> bool:
    """Co najmniej dwa słowa nazwy sprzedawcy w nazwie odbiorcy przelewu
    (imię i nazwisko jednoosobowej firmy) — jedno słowo to za mało."""

    return len(_name_words(found.seller_name) & _name_words(counterparty_name)) >= 2


def _settle(
    found: CostCandidate, amount: Decimal, title: str, how: str, *, partial_ok: bool
) -> DebitDecision:
    remaining = found.remaining
    hint = (found.entry_id,)
    if remaining <= ZERO:
        return DebitDecision(None, True, "already_paid", candidates=hint)
    if amount == remaining:
        return DebitDecision(found.entry_id, True, how, amount)
    vat = mpp_vat(title)
    if vat is not None and money(amount + vat) == remaining:
        # MPP: z rachunku głównego schodzi netto, VAT z rachunku VAT.
        return DebitDecision(found.entry_id, True, f"{how}_mpp", money(amount + vat))
    if amount < remaining and partial_ok:
        return DebitDecision(found.entry_id, True, f"{how}_partial", amount)
    if amount > remaining:
        return DebitDecision(None, True, "amount_exceeds", candidates=hint)
    return DebitDecision(None, True, "amount_differs", candidates=hint)


def decide_debit(
    line: StatementLine, candidates: Sequence[CostCandidate]
) -> DebitDecision:
    """Dopasowanie jednego obciążenia do faktury kosztowej (bez bazy)."""

    amount = money(line.amount)
    title = line.title or ""
    account = line.counterparty_account

    numbers = set(ksef_numbers_in(title))
    if numbers:
        by_ksef = [c for c in candidates if c.ksef_number and c.ksef_number in numbers]
        if len(by_ksef) == 1:
            found = by_ksef[0]
            if found.currency != line.currency:
                return DebitDecision(
                    None, True, "currency_differs", candidates=(found.entry_id,)
                )
            return _settle(found, amount, title, "ksef", partial_ok=True)
        if len(by_ksef) > 1:
            return DebitDecision(
                None, True, "ambiguous", candidates=tuple(c.entry_id for c in by_ksef)
            )

    mpp = _MPP_INV.search(title)
    mpp_number = " ".join(mpp.group(1).split()) if mpp else None
    by_number = [
        c
        for c in candidates
        if c.currency == line.currency
        and _number_in_title(c.invoice_number, title, mpp_number)
    ]
    if by_number:
        by_number = [c for c in by_number if not _shadowed(c, by_number)]
        # Numery faktur powtarzają się u różnych dostawców — rozstrzyga rachunek
        # odbiorcy, potem NIP sprzedawcy z pola /IDC/ (MPP), a w zwykłym
        # przelewie nazwa odbiorcy; bez nich kwota równa pozostałej do zapłaty.
        # Rachunek i NIP potwierdzają dostawcę, więc pozwalają na zapłatę
        # częściową (np. potrącenie z faktury); sama nazwa tylko zawęża.
        idc = _MPP_IDC.search(title)
        nip = idc.group(1) if idc else None
        confirmed = False
        same_account = (
            [c for c in by_number if account in c.accounts] if account else []
        )
        same_nip = [c for c in by_number if nip and c.seller_nip == nip]
        same_name = (
            [c for c in by_number if _same_seller(c, line.counterparty_name)]
            if nip is None
            else []
        )
        if same_account:
            by_number, confirmed = same_account, True
        elif same_nip:
            by_number, confirmed = same_nip, True
        elif same_name:
            by_number = same_name
        open_ = [c for c in by_number if c.remaining > ZERO] or by_number
        if len(open_) == 1:
            found = open_[0]
            return _settle(found, amount, title, "invoice_number", partial_ok=confirmed)
        fitting = [c for c in open_ if c.remaining == amount]
        if len(fitting) == 1:
            return DebitDecision(fitting[0].entry_id, True, "invoice_number", amount)
        return DebitDecision(
            None, True, "ambiguous", candidates=tuple(c.entry_id for c in open_)
        )

    if account:
        vat = mpp_vat(title)
        fitting = []
        for c in candidates:
            if c.currency != line.currency:
                continue
            pairs = list(c.batch_transfers)
            if c.batch_amount is not None and c.batch_account:
                pairs.append((c.batch_account, c.batch_amount))
            if any(
                pair_account == account
                and (
                    pair_amount == amount
                    or (vat is not None and money(amount + vat) == pair_amount)
                )
                for pair_account, pair_amount in pairs
            ):
                fitting.append(c)
        if len(fitting) == 1:
            found = fitting[0]
            # Kwota i rachunek to dokładnie nasz przelew z paczki — przy
            # podziale (zajęcie) to część płatności, więc częściowa jest w porządku.
            return _settle(
                found, amount, title, "batch", partial_ok=bool(found.batch_transfers)
            )
        if len(fitting) > 1:
            return DebitDecision(
                None, True, "ambiguous", candidates=tuple(c.entry_id for c in fitting)
            )
    return DebitDecision(None, False, "unrelated")


__all__ = [
    "ACK_LABELS",
    "BLOCK_LABELS",
    "CostCandidate",
    "DEBIT_REASON_LABELS",
    "DebitDecision",
    "HINT_LABELS",
    "KSEF_TITLE_FROM",
    "MODE_LABELS",
    "MPP_THRESHOLD",
    "Mode",
    "PaymentRuleError",
    "WHITE_LIST_LABELS",
    "WHITE_LIST_THRESHOLD",
    "art_105a_hint",
    "contractor_white_list_block",
    "decide_debit",
    "is_domestic",
    "masked",
    "mode_for",
    "needs_white_list_ack",
    "normalize_account",
    "title_lines",
]
