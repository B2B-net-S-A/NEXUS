"""Akceptacja kosztów delegacji przez klienta (próba IX–X 2026). Bez bazy.

RCP z kosztami delegacji zawsze dawał uwagę „Delegacja do sprawdzenia”, choć
klient te koszty zaakceptował. W próbie IX–X 2026 akceptacja miała dwie postaci:

* **RCP podpisany przez klienta:** szablon BNP ma wiersz „Koszty wyjazdu” w tym
  samym pliku, który przełożony u klienta podpisuje elektronicznie
  („dane wpisane w dokumencie traktujemy jako podstawę do rozliczenia faktury”).
  Certyfikat podpisu ma adres w domenie klienta. Finanse fakturowały dokładnie
  kwotę z RCP.
* **Mail klienta:** odpowiedź „Potwierdzam” albo „Akceptuję” z domeny klienta na
  prośbę o akceptację kosztów wyjazdu, w ``.eml``/``.msg`` albo w wydruku PDF.
  Liczy się, gdy w wątku jest kwota z RCP albo kwoty wszystkich pozycji z RCP
  (pociąg, hotel, …). Prośba z samym terminem wyjazdu albo z kwotą szacowaną
  inną niż w RCP to nie akceptacja tych kosztów.

Akceptacja z innej domeny, akceptacja samego konsultanta (także podpis jego
certyfikatem) i inna kwota zostawiają uwagę: faktury kosztów i zasadność
wyjazdu sprawdza wtedy człowiek.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from app.services.client_settlements import mail_text
from app.services.client_settlements.rcp_bnp import SignatureInfo
from app.services.client_settlements.rcp_checks import name_tokens

CENT = Decimal("0.01")
#: Wątek o wyjeździe: bez tego „Potwierdzam” pod Time Sheetem z kwotą faktury
#: wyglądałoby jak akceptacja kosztów.
TOPIC = re.compile(
    r"delegac|wyjazd|wyjeżdż|podróż|podroz|hotel|nocleg|pociąg|pociag|bilet|"
    r"travel|trip|business\s+trip",
    re.IGNORECASE,
)
#: Kwota z walutą: „610.00 PLN”, „845,40 zł”, „1 234,50 zł”. Bez waluty to bywa
#: data, godzina albo numer.
_AMOUNT = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(?:zł|zl|pln)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    title: str
    detail: Optional[str] = None


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


#: Kwota od miliona to nie koszt wyjazdu, tylko kapitał zakładowy ze stopki banku.
_MAX_AMOUNT = Decimal("1000000")


def amounts(text: str) -> list[Decimal]:
    """Kwoty z walutą, bez powtórzeń, w kolejności z tekstu."""

    found: list[Decimal] = []
    for whole, cents in _AMOUNT.findall(text or ""):
        raw = whole.replace(" ", "").replace(" ", "") + (f".{cents}" if cents else "")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        if value < _MAX_AMOUNT and all(abs(value - seen) >= CENT for seen in found):
            found.append(value)
    return found


def _same_person(signer: Optional[str], person_name: str) -> bool:
    mine, theirs = name_tokens(person_name), name_tokens(signer)
    return bool(mine and theirs and (mine <= theirs or theirs <= mine))


def by_signature(
    signatures: Sequence[SignatureInfo],
    *,
    total: Decimal,
    senders: mail_text.Senders,
    person_name: str,
    issuer: str = "",
) -> Optional[Verdict]:
    """Koszty w RCP podpisanym przez klienta: ważny podpis całego pliku,
    certyfikat z domeny klienta (i od wystawcy z reguły ``proof.signed_pdf``),
    podpisujący to nie konsultant."""

    need = issuer.strip().lower()
    for sign in signatures:
        if not (sign.intact and sign.entire_file and sign.signer_email_domain):
            continue
        if need and need not in (sign.issuer or "").lower():
            continue
        if not senders.accepts_from(f"podpis@{sign.signer_email_domain}"):
            continue
        if _same_person(sign.signer, person_name):
            continue
        when = sign.signed_at.strftime("%d.%m.%Y") if sign.signed_at else "bez daty"
        return Verdict(
            True,
            "Koszty delegacji w RCP podpisanym przez klienta",
            f"{_fmt(total)} zł brutto w pliku podpisanym przez "
            f"{sign.signer or 'osobę klienta'} ({sign.signer_email_domain}), {when}.",
        )
    return None


def by_mail(
    mails: Sequence[mail_text.Mail],
    *,
    total: Decimal,
    items: Sequence[tuple[str, Decimal]],
    senders: mail_text.Senders,
) -> Optional[Verdict]:
    """Akceptacja z maila klienta z kwotą albo pozycjami jak w RCP.

    ``None`` = w mailach nie ma akceptacji kosztów wyjazdu od klienta. Verdict
    z ``ok=False`` = klient zaakceptował inne kwoty niż w RCP."""

    wanted = [(label, value) for label, value in items if value > 0]
    other: Optional[tuple[str, list[Decimal]]] = None
    for mail in mails:
        if not TOPIC.search(mail.text):
            continue
        who = mail_text.approver(mail, senders)
        if who is None:
            continue
        found = amounts(mail.text)
        if any(abs(value - total) < CENT for value in found):
            return Verdict(
                True,
                "Akceptacja kosztów delegacji z maila klienta",
                f"{who}: {_fmt(total)} zł jak w RCP.",
            )
        if wanted and all(
            any(abs(value - amount) < CENT for value in found) for _, amount in wanted
        ):
            return Verdict(
                True,
                "Akceptacja kosztów delegacji z maila klienta",
                f"{who}: pozycje jak w RCP ("
                + ", ".join(f"{label} {_fmt(amount)} zł" for label, amount in wanted)
                + ").",
            )
        other = other or (who, found)
    if other is None:
        return None
    who, found = other
    named = ", ".join(f"{_fmt(v)} zł" for v in found) if found else "bez kwoty"
    return Verdict(
        False,
        "Akceptacja kosztów na inną kwotę",
        f"Klient ({who}) zaakceptował: {named}. W RCP {_fmt(total)} zł.",
    )


def mail_from_pdf(content: bytes) -> Optional[mail_text.Mail]:
    """Wydruk maila w PDF jako wątek do ``by_mail`` (``mail_text.from_printout``)."""

    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages[:10])
    return mail_text.from_printout(text)
