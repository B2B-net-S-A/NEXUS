"""Powiadomienia portalu Nordei CPro (``noreply@onevms.se``) — rozpoznanie bez bazy.

Decyzja Artura z 24.11.2026: powiadomienia CPro trafiają regułą przekierowania
ze skrzynek DL/TCM Nordei na wsparcie@, a czytnik spraw je rozpoznaje. Do tej
pory szły imiennie do DL-a i PM-a, a ci przekazywali je ręcznie: podczas urlopu
przedłużenie z 18.11 przeleżało do 23.11, a zmiana nabywcy z 15.09.2026
(Abp S.A. → Abp Finland) nie dotarła do Finansów wcale. Ta sama pomyłka w 2025
skończyła się korektami i refakturami.

Pięć wzorców (tematy i treść z archiwum administracja@ i poczty DL-i, 2023–2026):

* ``terminated`` — „Contract terminated: <nr> - <rola>”, tabela z „Consultant”,
  „Termination reason”, „New end date” (ISO) i „Comment”,
* ``not_extended`` — „Contract <nr> will not be extended”. Sam mail CPro nie ma
  daty: DL dopisuje „End day: 12.11.2026” albo „End day 2026-12-18” przy
  przekazaniu, a bez niej koniec to koniec obecnego zamówienia,
* ``internalization`` — koniec, bo Nordea zatrudnia konsultanta („Consultant
  employed at Nordea”, „he has been internalized”); potrzebne porozumienie ze
  zdjęciem zakazu konkurencji,
* ``prolongation`` — przedłużenie do decyzji w CPro („You have N contract
  extensions to handle”, „Please indicate whether this contract should be
  prolonged… prolongation status”); decyzja najpóźniej 5 tygodni przed końcem CoA,
* ``changes`` — „Important changes made to contract <nr>”: „Please update your
  invoice reference details…”, wiersze „<pole> was updated from: <stare>,
  to: <nowe>” (line manager, cost center, NIIDS / Initiative ID, adres faktury,
  czyli nabywca) i czasem „New end date”.

Numer w temacie to numer CoA w CPro; zamówienia Nordei mają go w tytule linii
zamówienia (``notice_mail.orders_by_cpro``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Optional

TERMINATED = "terminated"
NOT_EXTENDED = "not_extended"
INTERNALIZATION = "internalization"
PROLONGATION = "prolongation"
CHANGES = "changes"
#: Zdarzenia, po których potwierdzenie otwiera sprawę wyjścia z datą.
EXIT_EVENTS: frozenset[str] = frozenset({TERMINATED, NOT_EXTENDED, INTERNALIZATION})

EVENT_LABELS: dict[str, str] = {
    TERMINATED: "Nordea kończy kontrakt w CPro",
    NOT_EXTENDED: "Nordea nie przedłuża kontraktu w CPro",
    INTERNALIZATION: "Internalizacja: Nordea zatrudnia konsultanta",
    PROLONGATION: "Przedłużenie do decyzji w CPro",
    CHANGES: "Zmiana danych do faktury w CPro",
}

LINE_MANAGER = "line_manager"
COST_CENTER = "cost_center"
NIIDS = "niids"
INVOICE_ADDRESS = "invoice_address"
END_DATE = "end_date"
OTHER = "other"
#: Pola, których zmiana zmienia nabywcę faktury (Finanse, priorytet P1).
INVOICE_PARTY_FIELDS: frozenset[str] = frozenset({INVOICE_ADDRESS})
FIELD_LABELS: dict[str, str] = {
    LINE_MANAGER: "Line manager",
    COST_CENTER: "Cost center",
    NIIDS: "NIIDS / Initiative ID",
    INVOICE_ADDRESS: "Adres faktury (nabywca)",
    END_DATE: "Data końca",
    OTHER: "Inne pole",
}
VALUE_MAX = 200

_NUMBER = r"(\d{5,7})"
_TERMINATED = re.compile(r"contract terminated:?\s*" + _NUMBER, re.IGNORECASE)
_NOT_EXTENDED = re.compile(
    r"contract\s+" + _NUMBER + r"\s+will\s+not\s+be\s+(?:extended|prolonged)",
    re.IGNORECASE,
)
# Notatka z CPro własnymi słowami („the current contract won't be prolonged”).
_NOT_PROLONGED_NOTE = re.compile(
    r"\b(?:won['’]?t|will not|is not going to|cannot|can['’]?t) be (?:prolonged|extended)\b",
    re.IGNORECASE,
)
_CHANGED = re.compile(r"important changes made to contract\s*" + _NUMBER, re.IGNORECASE)
_EXTENSIONS_TO_HANDLE = re.compile(
    r"you have\s+(\d+)\s+contract extensions?\s+to handle", re.IGNORECASE
)
_PROLONGATION_WORDS = re.compile(
    r"prolongation status|should be prolonged|set the prolongation"
    r"|prolongation request|request(?:ed)? (?:a |the )?prolongation"
    r"|has been (?:prolonged|extended)|will be (?:prolonged|extended)"
    r"|prolong with the same rate",
    re.IGNORECASE,
)
_INTERNALIZATION_WORDS = re.compile(
    r"internali[sz]\w*|internalizac\w*|internalizow\w*"
    r"|employed (?:at|by) nordea|hired by nordea",
    re.IGNORECASE,
)
# Ślad, że to CPro, gdy temat nic nie mówi (przekazanie z własnym tematem).
_CPRO_MARKERS = re.compile(
    r"onevms\.se|sent from cpro|nordea's consultant procurement system"
    r"|show coa\b|consultant\.procurement@nordea",
    re.IGNORECASE,
)
_COA_NUMBER = re.compile(
    r"(?:coa\b[^\n(]{0,200}\(|show coa[^\n(]{0,200}\()" + _NUMBER + r"\)",
    re.IGNORECASE,
)
_SUBJECT_TAIL_NUMBER = re.compile(r"\s-\s*" + _NUMBER + r"\s*$")
_DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})"
_END_DAY = re.compile(
    r"(?:new end date|end day|end date|last day|ostatni dzie[nń])\s*:?\s*" + _DATE,
    re.IGNORECASE,
)
_NEW_END_DATE = re.compile(r"new end date\s*:?\s*" + _DATE, re.IGNORECASE)
_EFFECTIVE_FROM = re.compile(
    r"(?:valid|effective)\s+(?:from|as of)\s*:?\s*" + _DATE, re.IGNORECASE
)
# Tabela „Contract terminated” po zamianie HTML na tekst: etykieta i wartość
# w jednej linii albo wartość w następnej. Etykieta tylko na początku linii —
# „To: consultant.procurement@nordea.com” w nagłówku przekazania to nie osoba.
_TABLE_CONSULTANT = re.compile(
    r"^[ \t]*(?:contract[ \t]+)?consultant[ \t]*:?[ \t]*(?:\n[ \t]*)?([^\n|@]{3,80})$",
    re.IGNORECASE | re.MULTILINE,
)
_TABLE_REASON = re.compile(
    r"^[ \t]*termination reason[ \t]*:?[ \t]*(?:\n[ \t]*)?([^\n|]{3,80})$",
    re.IGNORECASE | re.MULTILINE,
)
_TABLE_COMMENT = re.compile(
    r"^[ \t]*comment[ \t]*:?[ \t]*(?:\n[ \t]*)?([^\n|]{3,300})$",
    re.IGNORECASE | re.MULTILINE,
)
_UPDATED_LINE = re.compile(r"\bwas updated from\b", re.IGNORECASE)
# Ostatnie „, to:” dzieli starą i nową wartość: adres faktury bywa z przecinkami.
_UPDATED = re.compile(
    r"^(?P<label>.+?)\s+was updated from\s*:?\s*(?P<old>.*)\s*,\s*to\s*:?\s*(?P<new>.*)$",
    re.IGNORECASE,
)
_RECORD_END = re.compile(r"^\s*(?:show coa\b|\*\*|--\s*$)", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class FieldChange:
    key: str
    label: str
    old: Optional[str]
    new: Optional[str]


@dataclass(frozen=True)
class CproEvent:
    kind: str
    cpro_number: Optional[str] = None
    end_day: Optional[date] = None
    effective_from: Optional[date] = None
    consultant_name: Optional[str] = None
    reason: Optional[str] = None
    comment: Optional[str] = None
    changes: tuple[FieldChange, ...] = ()
    #: „You have N contract extensions to handle” — ile przedłużeń czeka.
    pending_extensions: Optional[int] = None
    evidence: tuple[str, ...] = ()

    @property
    def invoice_party_changed(self) -> bool:
        return any(change.key in INVOICE_PARTY_FIELDS for change in self.changes)

    @property
    def invoice_reference_changes(self) -> tuple[FieldChange, ...]:
        """Zmiany do faktury (bez daty końca — tę niesie propozycja końca)."""

        return tuple(change for change in self.changes if change.key != END_DATE)


def _fold(value: str) -> str:
    cleaned = value.replace("Ł", "L").replace("ł", "l")
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", cleaned)
        if not unicodedata.combining(ch)
    ).casefold()


def parse_date(value: Optional[str]) -> Optional[date]:
    """„2026-12-18” albo „18.12.2026” → data; reszta → ``None``."""

    raw = (value or "").strip()
    try:
        if "-" in raw:
            return date.fromisoformat(raw)
        day, month, year = (int(part) for part in raw.split("."))
        return date(year, month, day)
    except ValueError:
        return None


def _first_date(pattern: re.Pattern[str], text: str) -> Optional[date]:
    for match in pattern.finditer(text):
        found = parse_date(match.group(1))
        if found is not None:
            return found
    return None


def _clean(value: Optional[str], limit: int = VALUE_MAX) -> Optional[str]:
    cleaned = _SPACES.sub(" ", value or "").strip(" .,;")
    return cleaned[:limit] or None


def is_cpro_mail(
    subject: Optional[str], body: Optional[str], sender_email: Optional[str] = None
) -> bool:
    if (sender_email or "").strip().lower().endswith("@onevms.se"):
        return True
    subject = subject or ""
    if (
        _TERMINATED.search(subject)
        or _NOT_EXTENDED.search(subject)
        or _CHANGED.search(subject)
        or _EXTENSIONS_TO_HANDLE.search(subject)
    ):
        return True
    return bool(_CPRO_MARKERS.search(body or ""))


def field_key(label: str) -> str:
    folded = _fold(label)
    if "line manager" in folded:
        return LINE_MANAGER
    if "cost cent" in folded:
        return COST_CENTER
    if "niids" in folded or "initiative" in folded or "appl" in folded:
        return NIIDS
    if "end date" in folded:
        return END_DATE
    if any(
        word in folded
        for word in (
            "invoice address",
            "invoicing address",
            "billing address",
            "invoice recipient",
            "buyer",
            "legal entity",
            "invoice company",
            "invoicing company",
        )
    ):
        return INVOICE_ADDRESS
    return OTHER


def _change_records(body: str) -> list[str]:
    """Wiersze zmian; wiersz zawinięty przez klienta poczty dokleja się do swojego."""

    records: list[str] = []
    open_record = False
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if _UPDATED_LINE.search(line):
            records.append(line.strip())
            open_record = True
        elif not open_record:
            continue
        elif not line.strip() or _RECORD_END.match(line):
            open_record = False
        else:
            records[-1] = f"{records[-1]} {line.strip()}"
    return records


def field_changes(body: str) -> tuple[FieldChange, ...]:
    """Wiersze „<pole> was updated from: <stare>, to: <nowe>” z treści CPro."""

    changes: list[FieldChange] = []
    seen: set[tuple[str, Optional[str]]] = set()
    for record in _change_records(body):
        match = _UPDATED.match(_SPACES.sub(" ", record))
        if match is None:
            continue
        label = _clean(match.group("label"), 80) or ""
        new = _clean(match.group("new"))
        key = field_key(label)
        # Przekazanie cytuje ten sam mail kilka razy — jedna zmiana raz.
        if (key, new) in seen:
            continue
        seen.add((key, new))
        changes.append(
            FieldChange(key=key, label=label, old=_clean(match.group("old")), new=new)
        )
    new_end = _first_date(_NEW_END_DATE, body or "")
    if new_end is not None and all(change.key != END_DATE for change in changes):
        changes.append(
            FieldChange(
                key=END_DATE, label="New end date", old=None, new=new_end.isoformat()
            )
        )
    return tuple(changes)


def _number(subject: str, body: str) -> Optional[str]:
    for pattern in (_TERMINATED, _NOT_EXTENDED, _CHANGED):
        for text_value in (subject, body):
            match = pattern.search(text_value)
            if match:
                return match.group(1)
    tail = _SUBJECT_TAIL_NUMBER.search(subject)
    if tail:
        return tail.group(1)
    coa = _COA_NUMBER.search(body)
    return coa.group(1) if coa else None


def parse(
    subject: Optional[str],
    body: Optional[str],
    sender_email: Optional[str] = None,
) -> Optional[CproEvent]:
    """Rodzaj powiadomienia CPro albo ``None`` (to nie CPro albo nic do zrobienia).

    Treść bierzemy całą, nie tylko świeżą część: przekazanie od DL-a
    („FW: Contract terminated…”) ma tabelę CPro w cytacie.
    """

    subject = subject or ""
    body = body or ""
    if not is_cpro_mail(subject, body, sender_email):
        return None
    number = _number(subject, body)
    # „New end date” z tabeli CPro wygrywa z „Contract end date” (stary koniec).
    end_day = _first_date(_NEW_END_DATE, body) or _first_date(_END_DAY, body)
    consultant = _TABLE_CONSULTANT.search(body)
    reason = _TABLE_REASON.search(body)
    comment = _TABLE_COMMENT.search(body)
    common = dict(
        cpro_number=number,
        end_day=end_day,
        consultant_name=_clean(consultant.group(1), 80) if consultant else None,
        reason=_clean(reason.group(1), 80) if reason else None,
        comment=_clean(comment.group(1), 300) if comment else None,
    )
    internalized = bool(_INTERNALIZATION_WORDS.search(body + "\n" + subject))

    if _TERMINATED.search(subject) or _TERMINATED.search(body):
        if internalized:
            return CproEvent(
                kind=INTERNALIZATION,
                evidence=(
                    "CPro „Contract terminated”: konsultant przechodzi do Nordei",
                ),
                **common,
            )
        return CproEvent(
            kind=TERMINATED,
            evidence=("powiadomienie CPro „Contract terminated”",),
            **common,
        )
    if _NOT_EXTENDED.search(subject) or _NOT_EXTENDED.search(body):
        return CproEvent(
            kind=NOT_EXTENDED,
            evidence=(
                "powiadomienie CPro „will not be extended”"
                + ("" if end_day else " (bez daty: koniec obecnego zamówienia)"),
            ),
            **common,
        )
    if number and _NOT_PROLONGED_NOTE.search(body):
        return CproEvent(
            kind=NOT_EXTENDED,
            evidence=("notatka CPro: kontrakt nie zostanie przedłużony",),
            **common,
        )
    if _CHANGED.search(subject) or _CHANGED.search(body):
        changes = field_changes(body)
        if not changes:
            return None
        end_change = next((c for c in changes if c.key == END_DATE), None)
        return CproEvent(
            kind=CHANGES,
            cpro_number=number,
            end_day=parse_date(end_change.new) if end_change else None,
            effective_from=_first_date(_EFFECTIVE_FROM, body),
            changes=changes,
            evidence=("powiadomienie CPro „Important changes made to contract”",),
        )
    if internalized and number:
        return CproEvent(
            kind=INTERNALIZATION,
            evidence=("CPro: internalizacja konsultanta",),
            **common,
        )
    extensions = _EXTENSIONS_TO_HANDLE.search(subject) or _EXTENSIONS_TO_HANDLE.search(
        body
    )
    if extensions or _PROLONGATION_WORDS.search(body):
        return CproEvent(
            kind=PROLONGATION,
            cpro_number=number,
            end_day=end_day,
            pending_extensions=int(extensions.group(1)) if extensions else None,
            evidence=("CPro: przedłużenie do decyzji",),
        )
    return None
