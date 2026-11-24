"""Wypowiedzenia z poczty — reguły rozpoznania (czyste funkcje, bez bazy).

Decyzje Artura z 23.11.2026 (makiety: https://claude.ai/artifact/1npkbSQfNQEkho441q8JMH).
Czytnik spraw pyta te reguły o każdy mail i dostaje jeden z czterech rodzajów:

* ``consultant_notice`` — konsultant wypowiada umowę (albo przysyła porozumienie),
* ``client_termination`` — klient kończy albo przestawia datę końca zamówienia
  (powiadomienie CPro Nordei „Contract terminated: <nr>”, „Contract <nr> will not
  be extended”, internalizacja, „Important changes made to contract <nr>” z nową
  datą końca; wzorce w ``nordea_cpro``),
* ``date_change`` — w wątku wypowiedzenia ktoś prosi o inną datę końca,
* ``withdrawal`` — w wątku wypowiedzenia konsultant je wycofuje.

Reguły biorą tylko świeżą część treści (bez cytowanej historii), bo odpowiedź
„Re: Wypowiedzenie” cytuje oryginał i inaczej każda odpowiedź byłaby nowym
wypowiedzeniem. Słowa sprawdzone na archiwum administracja@ z 20.11.2026
(373 maile o wypowiedzeniu, 49 powiadomień CPro). Wynik to propozycja: zapis
w kontrakcie robi człowiek przyciskiem na karcie.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from app.services.admin_cases import nordea_cpro

CONSULTANT_NOTICE = "consultant_notice"
CLIENT_TERMINATION = "client_termination"
DATE_CHANGE = "date_change"
WITHDRAWAL = "withdrawal"

#: Etykieta na karcie (rodzaj propozycji).
KIND_LABELS: dict[str, str] = {
    CONSULTANT_NOTICE: "Wypowiedzenie",
    CLIENT_TERMINATION: "Klient kończy",
    DATE_CHANGE: "Zmiana daty",
    WITHDRAWAL: "Wycofanie wypowiedzenia",
}

FRESH_LIMIT = 4_000

# Początek cytowanej historii w odpowiedzi: Outlook, Gmail, home.pl, Apple Mail.
_QUOTE_MARKERS = re.compile(
    r"^\s*(?:"
    r"-{2,}\s*(?:original message|wiadomość oryginalna|oryginalna wiadomość)\s*-{2,}"
    r"|from:\s.+|od:\s.+|wysłane:\s.+|sent:\s.+"
    r"|on .+ wrote:|.+napisał\(a\):|.+napisał:|.+napisała:"
    r"|\d{1,2}\.\d{1,2}\.\d{4}.+napisał\(a\):"
    r"|>.*"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Słowa po zdjęciu ogonków (``_fold``): „wypowiedzenie”, „rozwiązanie umowy”…
_NOTICE_WORDS = re.compile(
    r"wypowiedzeni\w*|wypowiadam|wypowiedziec|wypowiadajac"
    r"|rozwiazani\w*\s+umow\w*",
)
# „Zakończenie współpracy” liczy się tylko w temacie: w treści pada też przy
# sporze o rozliczenie („wzmianka o możliwym zakończeniu współpracy”, archiwum
# 26.05.2026) i w zapowiedziach DL-i, które nie są wypowiedzeniem.
_WEAK_SUBJECT_WORDS = re.compile(r"zakonczeni\w*\s+wspolprac\w*")
_AGREEMENT_WORDS = re.compile(r"porozumieni\w*")
# Nazwa pliku: samo „rozwiaz” łapało „rozwiazanie_problemu.png” przy fakturze.
_NOTICE_ATTACHMENT = re.compile(
    r"wypowiedz|rozwiazani\w*[ _.-]*umow|porozumieni\w*[ _.-]*(?:o[ _.-]*)?rozwiaz"
)
_NOT_A_NOTICE = re.compile(
    # Pakiet medyczny, karta sportowa, zamówienie klienta — w archiwum to samo
    # słowo „rezygnacja/wypowiedzenie” dotyczy też ich.
    r"pakiet\w* medyczn|opiek\w* medyczn|multisport|karta sportow"
    r"|wypowiedzeni\w* zamowieni",
)
# Wycofanie i zmiana daty tylko z jawnym odniesieniem: „Wycofaliśmy dostęp do VPN”,
# „nieobecny do 28.11” albo „zwrot sprzętu do 05.12” w wątku nie są ani jednym, ani drugim.
_WITHDRAW_WORDS = re.compile(
    r"(?:wycof\w*|cofam|anuluj\w*|anulowac)\s+(?:\w+\s+){0,3}wypowiedz\w*"
    r"|rezygnuj\w*\s+z\s+wypowiedz\w*|jednak\s+zostaj\w*",
)
_DATE_CHANGE_WORDS = re.compile(
    r"zmian\w*\s+(?:daty|terminu|dnia)\b|prosb\w*\s+o\s+zmian\w*"
    r"|przesun\w*\s+(?:\w+\s+){0,2}(?:dat\w*|termin\w*|koniec|zakonczeni\w*|ostatni)"
    r"|chc\w*\s+go\s+jednak|jednak\s+do\s+\d",
)
_CONTRACT_NUMBER = re.compile(r"\b(\d{3,4})\s*/\s*(20\d{2})\b")
_DATE_PL = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{4}))?\b")


@dataclass(frozen=True)
class NoticeSignal:
    kind: str
    contract_number: Optional[str] = None
    cpro_number: Optional[str] = None
    client_end_date: Optional[date] = None
    new_last_day: Optional[date] = None
    consultant_name: Optional[str] = None
    reason: Optional[str] = None
    agreement: bool = False
    #: Rodzaj powiadomienia CPro (``nordea_cpro``): koniec, nieprzedłużenie,
    #: internalizacja albo zmiana daty końca w „Important changes”.
    cpro_event: Optional[str] = None
    #: Co zadecydowało — pokazywane na karcie jako „Rozpoznane po”.
    evidence: tuple[str, ...] = ()


def _fold(value: str) -> str:
    cleaned = value.replace("Ł", "L").replace("ł", "l")
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", cleaned)
        if not unicodedata.combining(ch)
    ).casefold()


def fresh_text(body: str) -> str:
    """Treść bez cytowanej historii (pierwszy znacznik cytatu ucina resztę)."""

    text = (body or "").replace("\r\n", "\n")
    match = _QUOTE_MARKERS.search(text)
    if match:
        text = text[: match.start()]
    return text[:FRESH_LIMIT]


def contract_number_in(*texts: Optional[str]) -> Optional[str]:
    for value in texts:
        match = _CONTRACT_NUMBER.search(value or "")
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return None


def first_date_in(text: str, *, today: date) -> Optional[date]:
    """Pierwsza data w tekście („18.12”, „31.12.2026”); bez roku = najbliższa przyszła."""

    for match in _DATE_PL.finditer(text or ""):
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            found = date(year, month, day)
        except ValueError:
            continue
        if not match.group(3) and found < today:
            try:
                found = date(year + 1, month, day)
            except ValueError:
                continue
        return found
    return None


def _cpro_signal(subject: str, body: str) -> Optional[NoticeSignal]:
    """Koniec u klienta z powiadomienia CPro Nordei (``nordea_cpro``).

    Propozycję końca dają: „Contract terminated”, „will not be extended”,
    internalizacja i „Important changes” z nową datą końca. Zmiana danych do
    faktury i przedłużenie to nie koniec — prowadzi je sprawa z maila
    (``nordea_cpro_case``).
    """

    event = nordea_cpro.parse(subject, body)
    if event is None:
        return None
    if event.kind in nordea_cpro.EXIT_EVENTS:
        return NoticeSignal(
            kind=CLIENT_TERMINATION,
            cpro_number=event.cpro_number,
            client_end_date=event.end_day,
            consultant_name=event.consultant_name,
            reason=event.reason,
            cpro_event=event.kind,
            evidence=event.evidence,
        )
    # „Important changes” bez nowej daty końca to zmiana referencji faktury
    # albo stawki — nie ma czego proponować przy zakończeniu.
    if event.kind == nordea_cpro.CHANGES and event.end_day is not None:
        return NoticeSignal(
            kind=CLIENT_TERMINATION,
            cpro_number=event.cpro_number,
            client_end_date=event.end_day,
            cpro_event=nordea_cpro.CHANGES,
            evidence=("powiadomienie CPro z nową datą końca",),
        )
    return None


def classify(
    *,
    subject: Optional[str],
    body: Optional[str],
    attachment_names: Iterable[str] = (),
    in_notice_thread: bool = False,
    today: date,
) -> Optional[NoticeSignal]:
    """Rodzaj maila albo ``None`` (zwykła sprawa jak dotąd).

    ``in_notice_thread`` = sprawa ma już rozpoznane wypowiedzenie albo koniec
    zamówienia; tylko wtedy szukamy wycofania i zmiany daty.
    """

    subject = subject or ""
    raw_body = body or ""
    fresh = fresh_text(raw_body)
    folded_subject = _fold(subject)
    folded_fresh = _fold(fresh)
    names = [_fold(name) for name in attachment_names if name]
    number = contract_number_in(subject, fresh)

    # W wątku już rozpoznanego końca liczy się tylko świeża odpowiedź:
    # „Re: Contract terminated” cytuje tabelę CPro i nie jest nowym końcem.
    if in_notice_thread:
        if _WITHDRAW_WORDS.search(folded_fresh):
            return NoticeSignal(
                kind=WITHDRAWAL,
                contract_number=number,
                evidence=("„wycofuję” w wątku wypowiedzenia",),
            )
        change = _DATE_CHANGE_WORDS.search(folded_fresh)
        if change:
            # Data po słowach o zmianie: „przekazano 18.12, prośba o zmianę
            # na 31.12” to 31.12. Ogonki zdjęte w ``_fold`` nie zmieniają
            # długości tekstu, więc pozycja pasuje do świeżej treści.
            new_day = first_date_in(fresh[change.start() :], today=today)
            if new_day is not None:
                return NoticeSignal(
                    kind=DATE_CHANGE,
                    contract_number=number,
                    new_last_day=new_day,
                    evidence=("prośba o inną datę w wątku wypowiedzenia",),
                )
        return None

    # Powiadomienie CPro bywa przekazane dalej („FW: Contract terminated…”) —
    # liczy się cała treść, bo tabela z datą stoi w cytacie.
    cpro = _cpro_signal(subject, raw_body)
    if cpro is not None:
        return cpro

    if _NOT_A_NOTICE.search(folded_subject) or _NOT_A_NOTICE.search(folded_fresh):
        return None
    in_subject = bool(
        _NOTICE_WORDS.search(folded_subject)
        or _WEAK_SUBJECT_WORDS.search(folded_subject)
    )
    in_body = bool(_NOTICE_WORDS.search(folded_fresh))
    attached = any(_NOTICE_ATTACHMENT.search(name) for name in names)
    # Sam temat „Re: Wypowiedzenie” bez świeżej treści o wypowiedzeniu to
    # odpowiedź w wątku, którego czytnik nie zna — nie nowe wypowiedzenie.
    is_reply = bool(re.match(r"^\s*(re|odp|aw)\s*:", subject, re.IGNORECASE))
    if not (attached or in_body or (in_subject and not is_reply)):
        return None
    evidence: list[str] = []
    if attached:
        evidence.append("załącznik z wypowiedzeniem")
    if in_subject:
        evidence.append("„wypowiedzenie” w temacie")
    if in_body:
        evidence.append("„wypowiedzenie” w treści")
    agreement = bool(
        _AGREEMENT_WORDS.search(folded_subject)
        or _AGREEMENT_WORDS.search(folded_fresh)
        or any(_AGREEMENT_WORDS.search(name) for name in names)
    )
    return NoticeSignal(
        kind=CONSULTANT_NOTICE,
        contract_number=number,
        agreement=agreement,
        evidence=tuple(evidence),
    )


def name_from_address(email: Optional[str]) -> Optional[str]:
    """``jan.kowalski@b2bnetwork.pl`` → „jan kowalski” (do klucza osoby).

    Tylko dla adresu w formie ``imie.nazwisko``: z ``jkowalski@`` nie da się
    odczytać imienia, więc nic nie zgadujemy.
    """

    if not email or "@" not in email:
        return None
    local = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._]", local) if part.isalpha()]
    if len(parts) != 2:
        return None
    return " ".join(parts)
