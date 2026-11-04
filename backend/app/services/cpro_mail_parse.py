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

REASON_MAX = 300


@dataclass(frozen=True)
class CproEvent:
    kind: str
    request: Optional[str]
    person: Optional[str] = None
    reason: Optional[str] = None


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def _short(text: Optional[str]) -> Optional[str]:
    cleaned = _clean(text)
    return cleaned[:REASON_MAX] if cleaned else None


def parse(subject: Optional[str], body_text: Optional[str]) -> Optional[CproEvent]:
    """Rodzaj zdarzenia z tematu, szczegóły z treści; ``None`` = nie dotyczy."""
    title = _clean(subject)
    body = _clean(body_text)
    if not title:
        return None

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
