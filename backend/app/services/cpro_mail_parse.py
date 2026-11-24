"""Odczyt maili CPro, systemu zamówień konsultantów u Nordei — bez bazy i bez AI.

Pomiar 12.10–02.11.2026 (skrzynki Delivery Leadów Nordei): mail tego samego
rodzaju ma zawsze tę samą budowę, a numer requestu w tytule to
``jobs.client_reference``. Tekstu nie interpretuje model: temat nieznanego
rodzaju daje ``None`` i mail nic nie zmienia.

Reguła: ``docs/claude/integracje/cpro-maile-nordei.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SENDER = "noreply@onevms.se"
LINK_HOST = "nordea.onevms.se"

KIND_CLOSED = "closed"
KIND_REJECTED = "rejected"
KIND_INTERVIEW = "interview"
KIND_INTERVIEW_WITHDRAWN = "interview_withdrawn"
KIND_SLOTS_CHANGED = "slots_changed"
INTERVIEW_KINDS = frozenset(
    {KIND_INTERVIEW, KIND_INTERVIEW_WITHDRAWN, KIND_SLOTS_CHANGED}
)
# „Important changes made to contract N” (24.11.2026): numer to numer Call-Off,
# czyli tytuł zamówienia Nordei w NEXUSIE, a nie numer requestu rekrutacji.
KIND_INVOICE_ADDRESS = "invoice_address"
KIND_CONTRACT_CHANGED = "contract_changed"
CONTRACT_KINDS = frozenset({KIND_INVOICE_ADDRESS, KIND_CONTRACT_CHANGED})

_REQUEST_AT_END = re.compile(r"\((\d{4,6})\)\s*$")
_REQUEST_IN_BODY = re.compile(r"\((\d{4,6})\)")
_REJECTED = re.compile(
    r"^Rejected:\s*(?P<person>.+?)\s*\((?P<request>\d{4,6})\)\s*$", re.I
)
# „Rejected: Imię Nazwisko - IT Analyst (42000)”: po myślniku jest rola, nie nazwisko.
_ROLE_SUFFIX = re.compile(r"\s+-\s+.*$")
_INTERVIEW = re.compile(
    r"^I would like to interview\s+(?P<person>.+?),\s*Request\s+(?P<request>\d{4,6})\s*$",
    re.I,
)
_CONSULTANT = re.compile(r"Consultant:\s*(?P<person>.+?)\s*Request:", re.I | re.S)
_CLOSE_REASON = re.compile(
    r"Close reason:\s*(?P<reason>.+?)\s*(?:--|This email is sent|$)", re.I | re.S
)
# Powód odrzucenia stoi między tytułem z numerem a linią „Offer: …”.
_REJECT_REASON = re.compile(r"\(\d{4,6}\)\s*(?P<reason>.*?)\s*Offer:", re.S)
_WITHDREW = re.compile(r"\b(candidate|consultant)\s+(has\s+)?withdr[ae]w", re.I)
_CONTRACT_CHANGED = re.compile(
    r"^Important changes made to contract\s+(\d{5,7})$", re.I
)
# Pola z maili 08–11.2026; kolejność jak w dzienniku, bez wartości (nazwiska, numery).
_CHANGED_FIELDS = (
    ("NIIDS", re.compile(r"NIIDS\b[^\n:]{0,60}?\s+was updated from:", re.I)),
    (
        "line manager",
        re.compile(r"Responsible line manager\s+was updated from:", re.I),
    ),
    ("cost center", re.compile(r"Cost cent(?:er|re)\s+was updated from:", re.I)),
)
_ADDRESS_CHANGED = re.compile(r"Invoice address\s+was updated from:", re.I)
# „from: F218 Nordea Bank Abp S.A., to: F206 Nordea Bank Abp Finland”; przecinek
# bywa przed nową linią, a kod (litera i cyfry) także na końcu w nawiasie „(F206)”.
_ADDRESS = re.compile(
    r"Invoice address\s+was updated from:[ \t]*(?P<old>[^\n]*?),\s*to:[ \t]*"
    r"(?P<new>[^\n]*)",
    re.I,
)
_CODE_FIRST = re.compile(r"^([A-Z]\d{2,5})\b")
_CODE_BRACKETS = re.compile(r"\(([A-Z]\d{2,5})\)")
# Wartość kończy się przed następnym polem albo linkiem do kontraktu (tekst bez <br>).
_VALUE_END = re.compile(
    r"(?:Responsible line manager|Cost cent(?:er|re)|NIIDS|Invoice address)\b"
    r"|\*\*|\(\d{5,7}\)|\s{2,}",
    re.I,
)
NAME_MAX = 80

REASON_MAX = 300


@dataclass(frozen=True)
class CproEvent:
    kind: str
    request: Optional[str]
    person: Optional[str] = None
    reason: Optional[str] = None
    #: Nowy kod adresu faktury z CPro (``F206``) przy ``KIND_INVOICE_ADDRESS``.
    invoice_code: Optional[str] = None


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def _short(text: Optional[str]) -> Optional[str]:
    cleaned = _clean(text)
    return cleaned[:REASON_MAX] if cleaned else None


def _value(raw: str) -> str:
    """Wartość pola bez doklejonego dalej tekstu (``emails.body_text`` gubi <br>)."""
    cut = _VALUE_END.search(raw)
    value = _clean(raw[: cut.start()] if cut else raw)
    # „…Abp FinlandResponsible”: w tekście bez <br> nazwa i następne pole się sklejają.
    value = re.sub(r"(?<=[a-z])(?=[A-Z][a-z]+\s+was updated)", " ", value)
    return value[:NAME_MAX].strip(" ,")


def parse_contract_change(
    subject: str, body_text: Optional[str]
) -> Optional[CproEvent]:
    """„Important changes made to contract N”: zmiana adresu faktury albo innych pól."""
    match = _CONTRACT_CHANGED.match(subject)
    if match is None:
        return None
    raw = (body_text or "").replace("\xa0", " ").replace("\r", "")
    number = match.group(1)
    address = _ADDRESS.search(raw)
    if address is not None or _ADDRESS_CHANGED.search(raw):
        # Adres faktury = nabywca. Bez odczytanego kodu to nadal zmiana nabywcy:
        # idzie do „Do ręcznego” z dzwonkiem Finansów, nie do „Bez zmian”.
        old = _value(address.group("old")) if address else ""
        new = _value(address.group("new")) if address else ""
        code = _CODE_FIRST.search(new) or _CODE_BRACKETS.search(new)
        return CproEvent(
            KIND_INVOICE_ADDRESS,
            number,
            reason=_short(f"{old} → {new}") if old or new else None,
            invoice_code=code.group(1).upper() if code else None,
        )
    fields = [label for label, pattern in _CHANGED_FIELDS if pattern.search(raw)]
    return CproEvent(KIND_CONTRACT_CHANGED, number, reason=", ".join(fields) or None)


def parse(subject: Optional[str], body_text: Optional[str]) -> Optional[CproEvent]:
    """Rodzaj zdarzenia z tematu, szczegóły z treści; ``None`` = nie dotyczy."""
    title = _clean(subject)
    body = _clean(body_text)
    if not title:
        return None

    contract = parse_contract_change(title, body_text)
    if contract is not None:
        return contract

    if "was closed" in title.lower():
        match = _REQUEST_AT_END.search(title)
        if match is None:
            return None
        reason = _CLOSE_REASON.search(body)
        return CproEvent(
            KIND_CLOSED,
            match.group(1),
            reason=_short(reason.group("reason")) if reason else None,
        )

    rejected = _REJECTED.match(title)
    if rejected is not None:
        reason = _REJECT_REASON.search(body)
        person = _ROLE_SUFFIX.sub("", rejected.group("person"))
        return CproEvent(
            KIND_REJECTED,
            rejected.group("request"),
            person=_clean(person),
            reason=_short(reason.group("reason")) if reason else None,
        )

    interview = _INTERVIEW.match(title)
    if interview is not None:
        return CproEvent(
            KIND_INTERVIEW,
            interview.group("request"),
            person=_clean(interview.group("person")),
        )

    lowered = title.lower()
    kind = None
    if lowered == "interview has been withdrawn":
        kind = KIND_INTERVIEW_WITHDRAWN
    elif lowered.startswith("interview slots have changed"):
        kind = KIND_SLOTS_CHANGED
    if kind is None:
        return None
    # Te dwa tematy nie mają numeru ani osoby: szczegóły są tylko w treści.
    consultant = _CONSULTANT.search(body)
    tail = body[consultant.end() :] if consultant else body
    request = _REQUEST_IN_BODY.search(tail)
    return CproEvent(
        kind,
        request.group(1) if request else None,
        person=_clean(consultant.group("person")) if consultant else None,
    )


def is_withdrawal(reason: Optional[str]) -> bool:
    """„Candidate withdrew” to rezygnacja, nie odrzucenie przez klienta."""
    return bool(reason and _WITHDREW.search(reason))


def has_cpro_link(body_html: Optional[str]) -> bool:
    """Prawdziwy mail CPro ma link „Show request” do systemu Nordei."""
    return LINK_HOST in (body_html or "").lower()


def normalized_name(name: Optional[str]) -> str:
    return _clean(name).casefold()
