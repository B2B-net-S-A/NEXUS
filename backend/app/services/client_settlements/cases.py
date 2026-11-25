"""Karta sprawy rozliczenia: co dalej z rozliczeniem, którego automat nie przyjmuje.

Próby na kopiach produkcji 25.11.2026 (bez Nordei): automat przyjmuje sam
208 z 239 przypadków w IX–X i 208 z 258 w VI–VIII. Reszta to głównie wady, które
poprawia ktoś poza Finansami. Cel Artura: ręcznie tylko pojedyncze przypadki, a
każdy z nich ma gotowe „co dalej”: do kogo, jakim kanałem, z jaką treścią i z
terminami. Reguły: ``docs/claude/finanse-insights/rozliczenia-karta-sprawy-co-dalej.md``.

* **Sprawa** = rozliczenie (kontrakt × miesiąc) × kto działa: konsultant,
  akceptujący u klienta, Delivery Lead (przy kwocie z protokołu — opiekun) albo
  Finanse. Rozliczenie „Bez uwag” i przyjęte nie ma spraw, więc sprawa znika sama,
  gdy nowy dokument przeliczy rozliczenie bez wady albo Finanse je przyjmą.
* **Powód i adresat** z ``feedback.py`` (katalog wad, ``target_for``,
  ``compose_mail``), liczone tak, jakby wysyłka poza firmę była włączona. Wpis
  „wysłałbym” w ``sends`` przy ``external=off`` to dzwonek opiekuna, a nie mail
  do konsultanta, więc treść składają te same funkcje, a nie dziennik. Problemy
  zamówienia (ponad pulę, zamówienie zakończone, stawka linii, linia bez stawki,
  brak linii) to sprawa Delivery Leada, jak karty ``dl_alerts_scanner``. Reszta
  uwag ``warn``/``fail`` to decyzja Finansów, bez maila i telefonu.
* **Terminy** w dniach roboczych firmy od dnia 0 (wpływ raportu; przy karcie DL
  dzień karty): mail od razu, +3 przypomnienie, +5 telefon, +7 eskalacja do
  opiekuna (DL/KAM). Krok zrobiony później przesuwa następne o tę samą liczbę
  dni. Nowy raport zaczyna sprawę od nowa.
* **Nic nie wychodzi samo** (decyzja Artura z 25.11.2026). „Wyślij” wysyła
  przygotowany mail dopiero po kliknięciu, tym samym nadawcą co informacja zwrotna
  przy ``external=all`` (``portal_mail.default_mailer``); „Zadzwoniłem” zapisuje
  wynik. Ślad: ``hr_audit_events`` (``client_settlement_case``), a przy wadach
  z katalogu także wpis w ``client_settlement_feedback.sends``, żeby automat po
  włączeniu nie wysłał tego samego drugi raz tego dnia.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.client_settlement import ClientSettlement
from app.models.client_settlement_feedback import ClientSettlementFeedback
from app.models.consultant_portal import CpDocument
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.dl_alert import (
    ALERT_MISSING_REVENUE_RATE,
    ALERT_SETTLEMENT_OVER_ORDER,
    ALERT_SETTLEMENT_RATE_MISMATCH,
    DL_ALERT_STATUS_HANDLED,
    DlAlert,
)
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.care.announcement_mail import GraphMailer, MailOutcome
from app.services.client_order_lines import format_period_month
from app.services.client_settlements import feedback, line_rate, order_issues, reminders
from app.services.client_settlements.service import SettlementError
from app.services.consultant_portal import identity, portal_mail
from app.services.contract_candidate_contact import resolve_contact
from app.services.hr import audit
from app.services.person_workdays import business_days

logger = logging.getLogger(__name__)

# ── Kto działa ──────────────────────────────────────────────────────────────

CONSULTANT = "consultant"
CLIENT = "client"
DL = "dl"
FINANCE = "finance"
ACTORS: tuple[str, ...] = (CONSULTANT, CLIENT, DL, FINANCE)
ACTOR_LABELS: dict[str, str] = {
    CONSULTANT: "Konsultant",
    CLIENT: "Akceptujący u klienta",
    DL: "Delivery Lead",
    FINANCE: "Finanse",
}
#: Odbiorca wady z katalogu ``feedback`` → kto działa.
AUDIENCE_ACTOR: dict[str, str] = {
    feedback.CONSULTANT: CONSULTANT,
    feedback.CLIENT: CLIENT,
    feedback.OWNER: DL,
}
#: „Bez uwag” i przyjęte: sprawy nie ma.
CLOSED_STATUSES = ("ok", "accepted")

# Powody spoza katalogu wad (kody tylko na karcie, bez wiersza w bazie).
OVER = order_issues.OVER
ORDER_CLOSED = "order.closed"
ORDER_OVER = "order.md_over"
LINE_RATE = line_rate.RULE_KEY
NO_RATE = "order.no_rate"
NO_LINE = "order.no_line"
FINANCE_CHECK = "finance.check"
UNREAD = "finance.unread"
NO_RATE_TITLE = "Linia zamówienia bez stawki"
NO_LINE_TITLE = "Brak linii zamówienia"

# ── Terminy ─────────────────────────────────────────────────────────────────

MAIL, REMINDER, CALL, ESCALATION, DECISION = (
    "mail",
    "reminder",
    "call",
    "escalation",
    "decision",
)
#: (krok, dzień roboczy od dnia 0) — plan z 25.11.2026: mail, +3 przypomnienie,
#: +5 telefon back office, +7 eskalacja do DL/KAM.
PLAN: tuple[tuple[str, int], ...] = (
    (MAIL, 0),
    (REMINDER, 3),
    (CALL, 5),
    (ESCALATION, 7),
)
#: Finanse rozstrzygają uwagę same: jeden krok z terminem jak przypomnienie.
FINANCE_PLAN: tuple[tuple[str, int], ...] = ((DECISION, 3),)
STEP_LABELS: dict[str, str] = {
    MAIL: "Mail",
    REMINDER: "Przypomnienie",
    CALL: "Telefon",
    ESCALATION: "Eskalacja do DL/KAM",
    DECISION: "Decyzja Finansów",
}
DONE, OVERDUE, TODAY, UPCOMING, PLANNED = (
    "done",
    "overdue",
    "today",
    "upcoming",
    "planned",
)

# ── Ślad ────────────────────────────────────────────────────────────────────

ENTITY = "client_settlement_case"
ACTION_MAIL = "settlement_case_mail"
ACTION_CALL = "settlement_case_call"
EXTRA = "extra"
CALL_RESULTS: dict[str, str] = {
    "reached": "rozmowa",
    "no_answer": "nie odebrał(a)",
    "wrong_number": "zły numer",
}
NOTE_MAX = 500
SENT_OUTCOMES = ("sent", "simulated")

WHY_TEXT: dict[str, str] = {
    "no_acceptor": (
        "W prośbie o akceptację nie ma adresu akceptującego: piszemy do "
        "konsultanta, żeby dopytał."
    ),
    "no_email": (
        "Brak adresu konsultanta w kontrakcie i w kartotece: piszemy do opiekuna "
        "z prośbą o przekazanie."
    ),
    "no_owner": "Brak opiekuna kontraktu, opiekuna klienta i DL-a klienta.",
    "no_recipient": "Brak adresata: nie ma adresu konsultanta ani opiekuna.",
}
OWNER_SOURCE_TEXT: dict[str, str] = {
    "contract_care": "opiekun kontraktu",
    "client_care": "opiekun klienta",
    "client_dl": "Delivery Lead klienta",
}


def default_mailer() -> Optional[Any]:
    """Ten sam nadawca co informacja zwrotna przy ``external=all``; ``None`` = brak.

    Przy prawdziwej skrzynce „Odpowiedz do” = adres rozliczeń: poprawiony plik
    od konsultanta albo akceptacja klienta wraca do poczty, którą NEXUS czyta,
    a nie do skrzynki wsparcia."""

    mailer = portal_mail.default_mailer()
    reply_to = reminders.settlements_address()
    mailbox = portal_mail.mailbox()
    if isinstance(mailer, GraphMailer) and reply_to and mailbox:
        return GraphMailer(mailbox, reply_to=reply_to)
    return mailer


#: Pole modułu, żeby test podstawił atrapę nadawcy.
mailer_factory = default_mailer


# ── Czyste klocki: powody ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Reason:
    """Jeden powód sprawy po polsku. ``found`` = wada z katalogu ``feedback``."""

    code: str
    title: str
    detail: Optional[str] = None
    found: Optional[feedback.Found] = None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "title": self.title, "detail": self.detail}


def _md(value: Any) -> str:
    text = f"{value:f}" if hasattr(value, "is_finite") else str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _checks(checks: Sequence[Any]) -> Iterable[Mapping[str, Any]]:
    for group in checks or []:
        if not isinstance(group, dict):
            continue
        for check in group.get("checks") or []:
            if isinstance(check, dict) and check.get("state") in ("warn", "fail"):
                yield check


def classify(
    *,
    status: str,
    checks: Sequence[Any],
    month: str,
    fix_reason: Optional[str] = None,
    report_mime: Optional[str] = None,
    report_sender: Optional[str] = None,
    consultant_reports: bool = True,
    issues: Sequence[order_issues.OrderIssue] = (),
    mismatches: Sequence[Mapping[str, Any]] = (),
    order_number: Optional[str] = None,
    numbers: Optional[Mapping[int, str]] = None,
) -> dict[str, list[Reason]]:
    """Powody sprawy według tego, kto działa (czysta funkcja, bez bazy).

    Kolejność: wady z katalogu ``feedback`` (te same, które dostają komunikat),
    problemy zamówienia (Delivery Lead), reszta uwag (Finanse). Bez kwot w
    powodach Delivery Leada — tytuł uwagi „Stawka linii” je niesie, więc powód
    składamy z rozjazdu, jak karta ``rule_settlement_rate_mismatch``."""

    if status in CLOSED_STATUSES:
        return {}
    numbers = numbers or {}
    out: dict[str, list[Reason]] = {}

    def add(actor: str, reason: Reason) -> None:
        bucket = out.setdefault(actor, [])
        if all(r.code != reason.code or r.title != reason.title for r in bucket):
            bucket.append(reason)

    for found in feedback.defects_in(
        status=status,
        checks=checks,
        fix_reason=fix_reason,
        report_mime=report_mime,
        report_sender=report_sender,
        consultant_reports=consultant_reports,
    ):
        defect = feedback.BY_CODE[found.code]
        # Informacja bez poprawki (kosmetyka przy dobrym MD, ``Defect.notice``)
        # idzie do konsultanta „na przyszłość” i niczego nie blokuje: to nie sprawa.
        if getattr(defect, "notice", False):
            continue
        add(
            AUDIENCE_ACTOR[defect.audience],
            Reason(found.code, defect.title, found.detail, found),
        )

    label = format_period_month(month)
    for issue in issues:
        number = issue.number or numbers.get(issue.order_id) or "bez numeru"
        if issue.kind == order_issues.CLOSED:
            add(
                DL,
                Reason(
                    ORDER_CLOSED,
                    f"Zamówienie {number} zakończone w NEXUS-ie",
                    f"Mail klienta każe rozliczyć na nim {_md(issue.md)} MD. "
                    "Przywróć albo przedłuż zamówienie przed fakturą.",
                ),
            )
        else:
            add(
                DL,
                Reason(
                    ORDER_OVER,
                    f"{_md(issue.md)} MD ponad pulę zamówienia {number}",
                    "Do faktury idzie tylko pula. Przedłuż albo uzupełnij "
                    "zamówienie przed fakturą.",
                ),
            )
    for item in mismatches:
        order_id = int(item["order_id"])
        number = item.get("number") or numbers.get(order_id) or "bez numeru"
        against = " i ".join(
            text
            for text, present in (
                ("kontrakt", item.get("contract")),
                ("ostatnia faktura", item.get("invoice")),
            )
            if present
        )
        add(
            DL,
            Reason(
                LINE_RATE,
                f"Stawka linii zamówienia {number} inna niż {against or 'kontrakt'}",
                "„Do faktury” liczy się ze stawki linii. Sprawdź i popraw linię "
                "przed fakturą.",
            ),
        )

    for check in _checks(checks):
        if feedback.match(check) is not None:
            continue
        rule = check.get("rule")
        title = str(check.get("title") or "")
        if rule in (ORDER_OVER, ORDER_CLOSED):
            if not issues:
                add(DL, Reason(str(rule), title, check.get("detail")))
            continue
        if rule == LINE_RATE:
            if not mismatches:
                add(
                    DL,
                    Reason(
                        LINE_RATE,
                        "Stawka linii zamówienia inna niż kontrakt albo faktura",
                        "Sprawdź i popraw linię przed fakturą.",
                    ),
                )
            continue
        if title.startswith(NO_RATE_TITLE):
            add(
                DL,
                Reason(
                    NO_RATE,
                    f"Linia zamówienia {order_number or 'tej osoby'} bez stawki MD",
                    "Uzupełnij stawkę przychodową i kosztową linii: kwoty i marża "
                    "policzą się same.",
                ),
            )
            continue
        if title.startswith(NO_LINE_TITLE):
            add(
                DL,
                Reason(
                    NO_LINE,
                    f"Brak linii zamówienia na {label}",
                    "MD nie mają z czego zejść. Dodaj osobę do zamówienia przed "
                    "fakturą.",
                ),
            )
            continue
        add(FINANCE, Reason(FINANCE_CHECK, title, check.get("detail")))

    # Klient rozliczany z raportu klienta (T4T, Nordea): MD przyjdą z jego
    # raportu, więc nieodczytany plik konsultanta nie jest sprawą (próba IX–X:
    # 14 z 23 spraw Finansów za październik to była Nordea).
    if status == "checking" and not out and consultant_reports:
        add(
            FINANCE,
            Reason(
                UNREAD,
                "Nieodczytany plik: brak MD",
                "NEXUS nie odczytał MD z raportu. Sprawdź plik i wpisz MD na "
                "karcie rozliczenia.",
            ),
        )
    return {actor: out[actor] for actor in ACTORS if actor in out}


# ── Czyste klocki: terminy ──────────────────────────────────────────────────


def first_business_day(day: date) -> date:
    """``day`` albo najbliższy dzień roboczy po nim (kalendarz firmy)."""

    return business_days(day, day + timedelta(days=14))[0]


def add_business_days(day: date, count: int) -> date:
    if count <= 0:
        return day
    return business_days(day + timedelta(days=1), day + timedelta(days=count * 2 + 14))[
        count - 1
    ]


def business_days_between(start: date, end: date) -> int:
    """Dni robocze po ``start`` do ``end`` włącznie (0, gdy ``end <= start``)."""

    if end <= start:
        return 0
    return len(business_days(start + timedelta(days=1), end))


@dataclass(frozen=True)
class Done:
    on: date
    by: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class Step:
    key: str
    due: date
    state: str
    done: Optional[Done] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": STEP_LABELS[self.key],
            "due": self.due.isoformat(),
            "state": self.state,
            "done_on": self.done.on.isoformat() if self.done else None,
            "done_by": self.done.by if self.done else None,
            "note": self.done.note if self.done else None,
        }


def schedule(
    day0: date,
    today: date,
    done: Mapping[str, Done],
    plan: Sequence[tuple[str, int]] = PLAN,
) -> list[Step]:
    """Kroki sprawy z terminami (czysta funkcja).

    Termin kroku = dzień 0 + przesunięcie z planu, ale nie wcześniej niż
    najpóźniejszy z poprzednich kroków + ta sama różnica dni (krok zrobiony
    później przesuwa następne; telefon przed przypomnieniem nie przyspiesza
    eskalacji). Bieżący krok to pierwszy niezrobiony: ``overdue``, ``today``
    albo ``upcoming``. Kolejne są ``planned`` — liczone od dziś, gdy bieżący
    jest zaległy, bo przypomnienie dzień po pierwszym mailu nie ma sensu."""

    start = first_business_day(day0)
    steps: list[Step] = []
    base: Optional[date] = None
    previous = 0
    current_seen = False
    for key, offset in plan:
        due = add_business_days(start, offset)
        if base is not None:
            due = max(due, add_business_days(base, offset - previous))
        made = done.get(key)
        if made is not None:
            state = DONE
            reached = made.on
        elif not current_seen:
            current_seen = True
            state = OVERDUE if due < today else TODAY if due == today else UPCOMING
            reached = max(due, today)
        else:
            state = PLANNED
            reached = due
        base = reached if base is None else max(base, reached)
        previous = offset
        steps.append(Step(key, due, state, made))
    return steps


def current_step(steps: Sequence[Step]) -> Optional[Step]:
    return next((s for s in steps if s.state != DONE), None)


def next_mail_step(done: Mapping[str, Done]) -> str:
    """Który krok zalicza wysłany mail do osoby, która działa."""

    if MAIL not in done:
        return MAIL
    if REMINDER not in done:
        return REMINDER
    return EXTRA


# ── Czyste klocki: telefon i skrypt ─────────────────────────────────────────


@dataclass(frozen=True)
class Phone:
    who: str
    name: Optional[str]
    number: Optional[str]
    source: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "who": self.who,
            "name": self.name,
            "number": self.number,
            "source": self.source,
        }


def _first_sentence(text: str) -> str:
    clean = " ".join(text.split())
    return clean.split(". ", 1)[0].rstrip(".")


class _Blank(dict):
    """Pole spoza listy (nowa instrukcja w katalogu) zostaje puste, nie wywraca karty."""

    def __missing__(self, key: str) -> str:
        return ""


def instruction_text(
    instruction: str, ctx: feedback.Context, found: feedback.Found, address: str
) -> str:
    """Instrukcja wady z katalogu z wypełnionymi polami (te same co w ``feedback``).

    Mail składa ``feedback.compose_mail``; tu tylko zdanie do skryptu rozmowy
    i opis dla opiekuna."""

    return instruction.format_map(
        _Blank(
            month=format_period_month(ctx.month),
            address=address,
            client=ctx.client_name,
            person=ctx.person,
            detail=found.detail or "",
            private=" z adresu firmowego, nie z prywatnej skrzynki"
            if found.private
            else "",
        )
    ).replace(" ()", "")


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lower_first(text: str) -> str:
    """„PDF z RCP…” zostaje, „Prośba o…” → „prośba o…” (skrót nie jest zdaniem)."""

    if len(text) > 1 and text[1].isupper():
        return text
    return text[:1].lower() + text[1:]


def _titles(reasons: Sequence[Reason]) -> str:
    return "; ".join(_lower_first(r.title) for r in reasons)


def script_for(
    actor: str,
    *,
    ctx: feedback.Context,
    reasons: Sequence[Reason],
    need: Optional[str],
    address: str,
    mailed_on: Optional[date],
) -> list[str]:
    """2–4 zdania do rozmowy: sytuacja, czego brakuje, czego potrzebujemy."""

    label = format_period_month(ctx.month)
    mailed = (
        f"Szczegóły wysłaliśmy mailem {mailed_on:%d.%m}."
        if mailed_on is not None
        else None
    )
    if actor == CONSULTANT:
        lines = [
            "Dzień dobry, dzwonię z zespołu rozliczeń B2Bnetwork w sprawie "
            f"rozliczenia za {label} u klienta {ctx.client_name}.",
            f"Do poprawy: {_titles(reasons)}.",
            f"Co zrobić: {_lower_first(need)}." if need else None,
            mailed or f"Poprawkę prosimy przesłać na {address}.",
        ]
    elif actor == CLIENT:
        lines = [
            "Dzień dobry, dzwonię z B2Bnetwork w sprawie akceptacji czasu pracy "
            f"konsultanta {ctx.person} za {label}.",
            f"Sytuacja: {_titles(reasons)}.",
            "Potrzebujemy odpowiedzi „Akceptuję” na prośbę o akceptację godzin, "
            f"z kopią na {address}.",
            mailed,
        ]
    elif actor == DL:
        lines = [
            f"Dzwonię w sprawie rozliczenia {ctx.person} u klienta "
            f"{ctx.client_name} za {label}.",
            f"Czeka na: {_titles(reasons)}.",
            "Potrzebujemy poprawki w NEXUS-ie przed fakturą: rozliczenie "
            "przeliczy się samo.",
            mailed,
        ]
    else:
        return []
    return [line for line in lines if line][:4]


# ── Treść maili ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Recipient:
    kind: str
    label: str
    name: Optional[str] = None
    address: Optional[str] = None
    cc: Optional[str] = None
    why: Optional[str] = None
    user_id: Optional[int] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "name": self.name,
            "address": self.address,
            "cc": self.cc,
            "why": self.why,
            "why_text": WHY_TEXT.get(self.why or ""),
        }


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str
    cc: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "to": self.to,
            "cc": self.cc,
            "subject": self.subject,
            "text": self.text,
        }


def _wrap(text: str) -> str:
    return f"Dzień dobry,\n\n{text}\n\n{feedback.SIGNATURE}"


def compose_dl_mail(
    ctx: feedback.Context,
    reasons: Sequence[Reason],
    *,
    reminder: bool,
    card_on: Optional[date],
) -> tuple[str, str]:
    """Mail do Delivery Leada albo opiekuna (bez kwot: tak jak karta DL)."""

    label = format_period_month(ctx.month)
    lead = "Przypomnienie: " if reminder else ""
    subject = f"{lead}Rozliczenie za {label}: {ctx.person}, {ctx.client_name}"
    lines = [
        f"{n}. {r.title}." + (f"\n   {r.detail}" if r.detail else "")
        for n, r in enumerate(reasons, start=1)
    ]
    orders = any(r.found is None for r in reasons)
    card = (
        f"\n\nTo samo masz w kartach „Moi klienci” od {card_on:%d.%m}."
        if card_on
        else ""
    )
    text = (
        f"rozliczenie {ctx.person} za {label} u klienta {ctx.client_name} "
        "czeka na:\n\n"
        + "\n\n".join(lines)
        + (
            "\n\nPo zmianie zamówienia rozliczenie przeliczy się samo."
            if orders
            else ""
        )
        + card
    )
    return subject, _wrap(text)


ESCALATION_ASK: dict[str, str] = {
    CONSULTANT: (
        "Prosimy o kontakt z konsultantem: bez poprawki nie rozliczymy miesiąca "
        "ani faktury konsultanta."
    ),
    CLIENT: (
        "Prosimy o kontakt z akceptującym u klienta: bez akceptacji godzin nie "
        "wystawimy faktury."
    ),
    DL: "Prosimy o pomoc w domknięciu zamówienia przed fakturą.",
}


def compose_escalation(
    actor: str,
    ctx: feedback.Context,
    reasons: Sequence[Reason],
    *,
    day0: date,
    history: Sequence[str],
) -> tuple[str, str]:
    label = format_period_month(ctx.month)
    subject = f"Eskalacja: rozliczenie za {label}: {ctx.person}, {ctx.client_name}"
    done = (
        "\n\nCo już zrobiliśmy:\n" + "\n".join(f"- {line}" for line in history)
        if history
        else "\n\nMail i telefon jeszcze nie przyniosły poprawki."
    )
    text = (
        f"rozliczenie {ctx.person} za {label} u klienta {ctx.client_name} czeka "
        f"od {day0:%d.%m} ({ACTOR_LABELS[actor].lower()}): {_titles(reasons)}."
        + done
        + f"\n\n{ESCALATION_ASK[actor]}"
    )
    return subject, _wrap(text)


# ── Sprawa ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LogEntry:
    at: datetime
    action: str
    actor: str
    step: str
    by: Optional[str]
    details: Mapping[str, Any]

    @property
    def on(self) -> date:
        return self.at.astimezone(ZoneInfo(DEFAULT_TZ)).date()

    @property
    def ok(self) -> bool:
        if self.action == ACTION_CALL:
            return True
        return self.details.get("outcome") in SENT_OUTCOMES

    def as_dict(self) -> dict[str, Any]:
        d = self.details
        return {
            "on": self.at.astimezone(ZoneInfo(DEFAULT_TZ)).isoformat(),
            "action": "call" if self.action == ACTION_CALL else "mail",
            "step": self.step,
            "by": self.by,
            "to": d.get("to_label"),
            "address": d.get("address"),
            "outcome": d.get("outcome"),
            "result": d.get("result"),
            "result_label": CALL_RESULTS.get(str(d.get("result") or "")),
            "note": d.get("note"),
        }


@dataclass(frozen=True)
class DlCard:
    created_on: date
    mail_sent: bool
    handled: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "created_on": self.created_on.isoformat(),
            "mail_sent": self.mail_sent,
            "handled": self.handled,
        }


@dataclass
class Case:
    settlement_id: int
    contract_id: int
    client_id: int
    client_name: str
    person: str
    month: str
    status: str
    actor: str
    reasons: list[Reason]
    day0: date
    steps: list[Step]
    recipient: Optional[Recipient] = None
    mail: Optional[Mail] = None
    mail_step: Optional[str] = None
    escalation_to: Optional[Recipient] = None
    escalation_mail: Optional[Mail] = None
    phones: list[Phone] = field(default_factory=list)
    script: list[str] = field(default_factory=list)
    dl_card: Optional[DlCard] = None
    log: list[LogEntry] = field(default_factory=list)
    today: Optional[date] = None

    @property
    def key(self) -> str:
        return f"{self.settlement_id}:{self.actor}"

    @property
    def current(self) -> Optional[Step]:
        return current_step(self.steps)

    @property
    def overdue_days(self) -> int:
        step = self.current
        if step is None or step.state != OVERDUE or self.today is None:
            return 0
        return business_days_between(step.due, self.today)

    def as_dict(self, *, full: bool = True) -> dict[str, Any]:
        step = self.current
        out: dict[str, Any] = {
            "key": self.key,
            "settlement_id": self.settlement_id,
            "contract_id": self.contract_id,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "person": self.person,
            "month": self.month,
            "status": self.status,
            "actor": self.actor,
            "actor_label": ACTOR_LABELS[self.actor],
            "reasons": [r.as_dict() for r in self.reasons],
            "recipient": self.recipient.as_dict() if self.recipient else None,
            "day0": self.day0.isoformat(),
            "current": step.as_dict() if step else None,
            "overdue_days": self.overdue_days,
            "dl_card": self.dl_card.as_dict() if self.dl_card else None,
        }
        if not full:
            return out
        out.update(
            {
                "steps": [s.as_dict() for s in self.steps],
                "mail": self.mail.as_dict() if self.mail else None,
                "mail_step": self.mail_step,
                "escalation": {
                    "to": self.escalation_to.as_dict() if self.escalation_to else None,
                    "mail": self.escalation_mail.as_dict()
                    if self.escalation_mail
                    else None,
                },
                "phones": [p.as_dict() for p in self.phones],
                "script": list(self.script),
                "log": [entry.as_dict() for entry in self.log],
            }
        )
        return out


# ── Baza: odczyt ────────────────────────────────────────────────────────────


@dataclass
class _Row:
    s: ClientSettlement
    client_name: str
    person: str
    consultant_email: Optional[str]
    consultant_phone: Optional[str]
    consultant_phone_source: Optional[str]
    pm_contact_id: Optional[int]
    contract_owner: Optional[int]
    client_owner: Optional[int]
    report_mime: Optional[str]
    report_sender: Optional[str]
    report_at: Optional[datetime]


_EVENT_SETTLEMENT = re.compile(r":settlement:(\d+):")


def _local(at: datetime) -> date:
    return at.astimezone(ZoneInfo(DEFAULT_TZ)).date()


async def _rows(
    db: AsyncSession,
    *,
    month: Optional[str] = None,
    client_id: Optional[int] = None,
    contract_id: Optional[int] = None,
    settlement_id: Optional[int] = None,
) -> list[_Row]:
    stmt = (
        select(
            ClientSettlement,
            Client.name,
            reminders._FULL_NAME,
            Contract.candidate_email,
            Contract.candidate_phone,
            Contract.client_pm_contact_id,
            Candidate.email,
            Candidate.phone,
            reminders._CONTRACTS_CARE.c.care_owner_user_id,
            reminders._CLIENTS_CARE.c.default_care_owner_user_id,
            CpDocument.mime,
            CpDocument.sender_email,
            CpDocument.created_at,
        )
        .join(Contract, Contract.id == ClientSettlement.contract_id)
        .join(Client, Client.id == ClientSettlement.client_id)
        .join(reminders._CONTRACTS_CARE, reminders._CONTRACTS_CARE.c.id == Contract.id)
        .join(
            reminders._CLIENTS_CARE,
            reminders._CLIENTS_CARE.c.id == ClientSettlement.client_id,
        )
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(CpDocument, CpDocument.id == ClientSettlement.report_document_id)
        .where(
            ClientSettlement.kind == "actual",
            ClientSettlement.status.not_in(CLOSED_STATUSES),
        )
        .order_by(Client.name, reminders._FULL_NAME, ClientSettlement.id)
    )
    if month is not None:
        stmt = stmt.where(ClientSettlement.period_month == month)
    if client_id is not None:
        stmt = stmt.where(ClientSettlement.client_id == client_id)
    if contract_id is not None:
        stmt = stmt.where(ClientSettlement.contract_id == contract_id)
    if settlement_id is not None:
        stmt = stmt.where(ClientSettlement.id == settlement_id)
    out = []
    found = (await db.execute(stmt)).all()
    # Decyzja Artura z 26.11.2026: adres, z którego konsultant sam pisze do rozliczeń.
    written = await reminders.consultant_addresses(
        db, {row[0].contract_id for row in found}, today=business_today()
    )
    for row in found:
        (s, client_name, person, c_email, c_phone, pm_id, k_email, k_phone) = row[:8]
        contact = resolve_contact(
            contract_email=c_email,
            contract_phone=c_phone,
            candidate=_Profile(k_email, k_phone),
        )
        out.append(
            _Row(
                s=s,
                client_name=client_name,
                person=person or f"Kontrakt {s.contract_id}",
                # Adres jak w ``feedback``: z poczty, potem kontrakt, potem kartoteka.
                consultant_email=written.get(s.contract_id)
                or identity.normalize_email(contact.email)
                or None,
                consultant_phone=contact.phone,
                consultant_phone_source={
                    "contract": "z kontraktu",
                    "candidate_profile": "z kartoteki kandydata",
                }.get(contact.phone_source or ""),
                pm_contact_id=pm_id,
                contract_owner=row[8],
                client_owner=row[9],
                report_mime=row[10],
                report_sender=row[11],
                report_at=row[12],
            )
        )
    return out


@dataclass(frozen=True)
class _Profile:
    email: Optional[str]
    phone: Optional[str]


async def _order_numbers(db: AsyncSession, order_ids: set[int]) -> dict[int, str]:
    if not order_ids:
        return {}
    from app.services.client_settlements.service import number_from_title

    rows = await db.execute(
        select(ClientOrder.id, ClientOrderGroup.order_number, ClientOrder.title)
        .outerjoin(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(ClientOrder.id.in_(order_ids))
    )
    return {
        oid: number or number_from_title(title) or "bez numeru"
        for oid, number, title in rows.all()
    }


async def _dl_cards(db: AsyncSession, rows: Sequence[_Row]) -> dict[int, DlCard]:
    """Karty DL tej sprawy: ponad zamówienie i stawka linii (klucz rozliczenia)
    oraz brak stawki przychodowej na zamówieniu rozliczenia. Bieżący epizod."""

    if not rows:
        return {}
    by_order = {r.s.order_id: r.s.id for r in rows if r.s.order_id}
    alerts = (
        await db.scalars(
            select(DlAlert).where(
                DlAlert.alert_type.in_(
                    (
                        ALERT_SETTLEMENT_OVER_ORDER,
                        ALERT_SETTLEMENT_RATE_MISMATCH,
                        ALERT_MISSING_REVENUE_RATE,
                    )
                ),
                DlAlert.client_id.in_({r.s.client_id for r in rows}),
                DlAlert.episode_closed_at.is_(None),
            )
        )
    ).all()
    ids = {r.s.id for r in rows}
    cards: dict[int, DlCard] = {}
    for alert in alerts:
        settlement_id: Optional[int] = None
        if alert.alert_type == ALERT_MISSING_REVENUE_RATE:
            settlement_id = by_order.get(alert.order_id)
        else:
            found = _EVENT_SETTLEMENT.search(alert.event_key or alert.dedupe_key or "")
            settlement_id = int(found.group(1)) if found else None
        if settlement_id not in ids:
            continue
        day = _local(alert.created_at)
        old = cards.get(settlement_id)
        cards[settlement_id] = DlCard(
            created_on=min(day, old.created_on) if old else day,
            mail_sent=(old.mail_sent if old else False)
            or alert.email_sent_at is not None,
            handled=(old.handled if old else False)
            or alert.status == DL_ALERT_STATUS_HANDLED,
        )
    return cards


async def _logs(
    db: AsyncSession, settlement_ids: set[int]
) -> dict[int, list[LogEntry]]:
    if not settlement_ids:
        return {}
    rows = (
        await db.execute(
            select(HrAuditEvent, User.name, User.email)
            .outerjoin(User, User.id == HrAuditEvent.actor_user_id)
            .where(
                HrAuditEvent.entity_type == ENTITY,
                HrAuditEvent.entity_id.in_([str(i) for i in settlement_ids]),
                HrAuditEvent.action.in_((ACTION_MAIL, ACTION_CALL)),
            )
            .order_by(HrAuditEvent.created_at, HrAuditEvent.id)
        )
    ).all()
    out: dict[int, list[LogEntry]] = {}
    for event, name, email in rows:
        details = dict(event.details or {})
        out.setdefault(int(event.entity_id), []).append(
            LogEntry(
                at=event.created_at,
                action=event.action,
                actor=str(details.get("actor") or ""),
                step=str(details.get("step") or ""),
                by=name or email,
                details=details,
            )
        )
    return out


async def _contacts(
    db: AsyncSession, rows: Sequence[_Row], acceptors: set[str]
) -> tuple[dict[tuple[int, str], Contact], dict[int, Contact]]:
    """Kontakty klientów: akceptujący po adresie i PM z kontraktu po id."""

    by_mail: dict[tuple[int, str], Contact] = {}
    by_id: dict[int, Contact] = {}
    client_ids = {r.s.client_id for r in rows}
    if acceptors and client_ids:
        for contact in (
            await db.scalars(
                select(Contact).where(
                    Contact.client_id.in_(client_ids),
                    func.lower(func.trim(Contact.email)).in_(acceptors),
                )
            )
        ).all():
            key = (contact.client_id, identity.normalize_email(contact.email))
            # Wpis z numerem wygrywa z duplikatem bez numeru.
            if key not in by_mail or (contact.phone and not by_mail[key].phone):
                by_mail[key] = contact
    pm_ids = {r.pm_contact_id for r in rows if r.pm_contact_id}
    if pm_ids:
        for contact in (
            await db.scalars(select(Contact).where(Contact.id.in_(pm_ids)))
        ).all():
            by_id[contact.id] = contact
    return by_mail, by_id


async def _employee_phones(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(EmployeeProfile.user_id, EmployeeProfile.phone).where(
            EmployeeProfile.user_id.in_(user_ids),
            EmployeeProfile.phone.is_not(None),
        )
    )
    return {uid: phone.strip() for uid, phone in rows.all() if phone and phone.strip()}


def _owner_recipient(
    owner: Optional[reminders.Owner], why: Optional[str] = None
) -> Optional[Recipient]:
    if owner is None:
        return None
    return Recipient(
        kind="owner",
        label=_cap(OWNER_SOURCE_TEXT.get(owner.source, "opiekun")),
        name=owner.name,
        address=owner.email,
        why=why,
        user_id=owner.user_id,
    )


def _user_recipient(user: User, label: str) -> Recipient:
    return Recipient(
        kind="owner",
        label=label,
        name=user.name or user.email,
        address=user.email,
        user_id=user.id,
    )


def _done_from_log(
    entries: Sequence[LogEntry], actor: str, day0: date
) -> dict[str, Done]:
    """Kroki zrobione w bieżącym epizodzie (wpisy od dnia 0, tego, kto działa)."""

    done: dict[str, Done] = {}
    for entry in entries:
        if entry.actor != actor or entry.on < day0 or not entry.ok:
            continue
        if entry.step in (MAIL, REMINDER, CALL, ESCALATION) and entry.step not in done:
            note = None
            if entry.action == ACTION_CALL:
                note = CALL_RESULTS.get(str(entry.details.get("result") or ""))
            elif entry.details.get("outcome") == "simulated":
                note = "symulacja: nic nie wyszło"
            done[entry.step] = Done(on=entry.on, by=entry.by, note=note)
    return done


def _history(steps: Sequence[Step], recipient: Optional[Recipient]) -> list[str]:
    out = []
    for step in steps:
        if step.done is None or step.key == ESCALATION:
            continue
        what = {
            MAIL: f"mail {step.done.on:%d.%m}",
            REMINDER: f"przypomnienie {step.done.on:%d.%m}",
            CALL: f"telefon {step.done.on:%d.%m}"
            + (f" ({step.done.note})" if step.done.note else ""),
        }.get(step.key)
        if what:
            out.append(
                what
                + (
                    f" do: {recipient.label.lower()}"
                    if recipient and step.key != CALL
                    else ""
                )
            )
    return out


async def build(
    db: AsyncSession,
    today: date,
    *,
    month: Optional[str] = None,
    client_id: Optional[int] = None,
    contract_id: Optional[int] = None,
    settlement_id: Optional[int] = None,
) -> list[Case]:
    """Sprawy rozliczeń (bez zapisu): powody, adresat, mail, telefon, terminy."""

    rows = await _rows(
        db,
        month=month,
        client_id=client_id,
        contract_id=contract_id,
        settlement_id=settlement_id,
    )
    if not rows:
        return []
    months = {r.s.period_month for r in rows}
    client_ids = {r.s.client_id for r in rows}
    from_client: set[tuple[int, str]] = set()
    for m in months:
        ids = {r.s.client_id for r in rows if r.s.period_month == m}
        from_client |= {
            (cid, m) for cid in await reminders.client_hours_clients(db, ids, m)
        }
    meta = {r.s.id: order_issues._meta(r.s) for r in rows}
    issues = {r.s.id: order_issues.issues_of(r.s) for r in rows}
    mismatches = {r.s.id: line_rate.mismatches_of(meta[r.s.id]) for r in rows}
    numbers = await _order_numbers(
        db,
        {r.s.order_id for r in rows if r.s.order_id}
        | {i.order_id for items in issues.values() for i in items}
        | {int(m["order_id"]) for items in mismatches.values() for m in items},
    )
    leads = await reminders._client_leads(db, client_ids)
    users = await reminders._active_users(
        db,
        {
            uid
            for r in rows
            for uid in (r.contract_owner, r.client_owner)
            if uid is not None
        }
        | set(leads.values()),
    )
    phones = await _employee_phones(db, set(users))
    cards = await _dl_cards(db, rows)
    logs = await _logs(db, {r.s.id for r in rows})
    address = reminders.settlements_address() or "adres rozliczeń"

    classified: dict[int, dict[str, list[Reason]]] = {}
    acceptors: set[str] = set()
    for r in rows:
        classified[r.s.id] = classify(
            status=r.s.status,
            checks=list(r.s.checks or []),
            month=r.s.period_month,
            fix_reason=r.s.fix_reason,
            report_mime=r.report_mime,
            report_sender=r.report_sender,
            consultant_reports=(r.s.client_id, r.s.period_month) not in from_client,
            issues=issues[r.s.id],
            mismatches=mismatches[r.s.id],
            order_number=numbers.get(r.s.order_id) if r.s.order_id else None,
            numbers=numbers,
        )
        for reason in classified[r.s.id].get(CLIENT, []):
            if reason.found and reason.found.acceptor:
                acceptors.add(identity.normalize_email(reason.found.acceptor))
    by_mail, by_id = await _contacts(db, rows, acceptors)

    out: list[Case] = []
    for r in rows:
        owner = reminders.pick_owner(
            contract_owner=r.contract_owner,
            client_owner=r.client_owner,
            client_lead=leads.get(r.s.client_id),
            users=users,
        )
        ctx = feedback.Context(
            contract_id=r.s.contract_id,
            client_id=r.s.client_id,
            client_name=r.client_name,
            person=r.person,
            month=r.s.period_month,
            settlement_id=r.s.id,
        )
        report_day = _local(r.report_at) if r.report_at else _local(r.s.created_at)
        for actor, reasons in classified[r.s.id].items():
            card = cards.get(r.s.id) if actor == DL else None
            day0 = card.created_on if card else report_day
            entries = logs.get(r.s.id, [])
            done = _done_from_log(entries, actor, day0)
            if card is not None and MAIL not in done:
                done[MAIL] = Done(on=card.created_on, note="karta DL (automat)")
            plan = FINANCE_PLAN if actor == FINANCE else PLAN
            steps = schedule(day0, today, done, plan)
            case = Case(
                settlement_id=r.s.id,
                contract_id=r.s.contract_id,
                client_id=r.s.client_id,
                client_name=r.client_name,
                person=r.person,
                month=r.s.period_month,
                status=r.s.status,
                actor=actor,
                reasons=reasons,
                day0=first_business_day(day0),
                steps=steps,
                dl_card=card,
                log=[e for e in entries if e.actor == actor and e.on >= day0],
                today=today,
            )
            if actor != FINANCE:
                _fill_contact(
                    case,
                    r,
                    ctx=ctx,
                    owner=owner,
                    lead=users.get(leads.get(r.s.client_id) or 0),
                    users=users,
                    phones=phones,
                    by_mail=by_mail,
                    by_id=by_id,
                    address=address,
                    done=done,
                )
            out.append(case)
    return out


def _fill_contact(
    case: Case,
    r: _Row,
    *,
    ctx: feedback.Context,
    owner: Optional[reminders.Owner],
    lead: Optional[User],
    users: Mapping[int, User],
    phones: Mapping[int, str],
    by_mail: Mapping[tuple[int, str], Contact],
    by_id: Mapping[int, Contact],
    address: str,
    done: Mapping[str, Done],
) -> None:
    """Adresat, gotowy mail, telefon, skrypt i eskalacja jednej sprawy."""

    reminder = MAIL in done
    case.mail_step = next_mail_step(done)
    consultant_phone = Phone(
        "Konsultant", r.person, r.consultant_phone, r.consultant_phone_source
    )
    mailed_on = done[MAIL].on if MAIL in done else None
    need: Optional[str] = None

    if case.actor in (CONSULTANT, CLIENT):
        who = feedback.Who(
            consultant_email=r.consultant_email, owner=owner, panel_open=True
        )
        everyone = feedback.Settings(mode="on", external="all")
        pairs = [
            (
                reason,
                *feedback.target_for(
                    feedback.BY_CODE[reason.code], reason.found, who, everyone
                ),
            )
            for reason in case.reasons
            if reason.found is not None
        ]
        target = pairs[0][1]
        items = [
            feedback.Item(0, feedback.BY_CODE[reason.code], reason.found, instruction)
            for reason, t, instruction in pairs
            if t.key == target.key
        ]
        need = _first_sentence(
            instruction_text(items[0].instruction, ctx, items[0].found, address)
        )
        if target.kind in (feedback.CONSULTANT, feedback.CLIENT):
            subject, text = feedback.compose_mail(
                target, ctx, items, address, reminder=reminder
            )
            case.recipient = Recipient(
                kind=target.kind,
                label=ACTOR_LABELS[CONSULTANT]
                if target.kind == feedback.CONSULTANT
                else ACTOR_LABELS[CLIENT],
                name=r.person if target.kind == feedback.CONSULTANT else None,
                address=target.address,
                cc=target.cc,
                why=target.why,
            )
            case.mail = Mail(
                to=target.address or "", subject=subject, text=text, cc=target.cc
            )
        elif target.kind == feedback.OWNER and owner is not None:
            title, message = feedback.compose_bell(target, ctx, items, address)
            case.recipient = _owner_recipient(owner, why=target.why)
            if owner.email:
                case.mail = Mail(
                    to=owner.email,
                    subject=("Przypomnienie: " if reminder else "") + title,
                    text=_wrap(message),
                )
        else:
            case.recipient = Recipient(
                kind="none", label="Brak adresata", why="no_recipient"
            )
        case.phones = [consultant_phone]
        if case.actor == CLIENT:
            acceptor = next(
                (
                    r_.found.acceptor
                    for r_ in case.reasons
                    if r_.found and r_.found.acceptor
                ),
                None,
            )
            contact = (
                by_mail.get((r.s.client_id, identity.normalize_email(acceptor)))
                if acceptor
                else None
            )
            if contact is not None:
                person_phone = Phone(
                    "Akceptujący u klienta",
                    contact.name or acceptor,
                    (contact.phone or "").strip() or None,
                    "z kontaktów klienta",
                )
            elif r.pm_contact_id and r.pm_contact_id in by_id:
                pm = by_id[r.pm_contact_id]
                person_phone = Phone(
                    "PM u klienta (z kontraktu)",
                    pm.name,
                    (pm.phone or "").strip() or None,
                    "z kontaktów klienta",
                )
            else:
                person_phone = Phone("Akceptujący u klienta", acceptor, None, None)
            case.phones = [person_phone, consultant_phone]
    else:  # Delivery Lead (zamówienie) albo opiekun (kwota z protokołu)
        orders = any(reason.found is None for reason in case.reasons)
        if orders and lead is not None:
            dl_recipient = _user_recipient(lead, "Delivery Lead klienta")
        else:
            dl_recipient = _owner_recipient(owner)
        parts: list[Reason] = []
        for reason in case.reasons:
            if reason.found is not None and dl_recipient is not None:
                defect = feedback.BY_CODE[reason.code]
                parts.append(
                    replace(
                        reason,
                        detail=instruction_text(
                            defect.instruction, ctx, reason.found, address
                        ),
                    )
                )
            else:
                parts.append(reason)
        case.recipient = dl_recipient or Recipient(
            kind="none", label="Brak adresata", why="no_owner"
        )
        if dl_recipient is not None and dl_recipient.address:
            subject, text = compose_dl_mail(
                ctx,
                parts,
                reminder=reminder,
                card_on=case.dl_card.created_on if case.dl_card else None,
            )
            case.mail = Mail(to=dl_recipient.address, subject=subject, text=text)
        case.phones = [
            Phone(
                dl_recipient.label if dl_recipient else "Delivery Lead",
                dl_recipient.name if dl_recipient else None,
                phones.get(dl_recipient.user_id or 0) if dl_recipient else None,
                "z profilu pracownika" if dl_recipient else None,
            )
        ]
    # Eskalacja do opiekuna (DL/KAM), ale nie do osoby, do której już piszemy.
    # Przy sprawie Delivery Leada najpierw opiekun klienta (KAM).
    chain = (
        ((r.client_owner, "client_care"), (r.contract_owner, "contract_care"))
        if case.actor == DL
        else (
            (r.contract_owner, "contract_care"),
            (r.client_owner, "client_care"),
            (lead.id if lead else None, "client_dl"),
        )
    )
    skip = case.recipient.user_id if case.recipient else None
    escalate: Optional[Recipient] = None
    for uid, source in chain:
        user = users.get(uid) if uid is not None else None
        if user is not None and user.id != skip:
            escalate = _user_recipient(user, _cap(OWNER_SOURCE_TEXT[source]))
            break
    case.script = script_for(
        case.actor,
        ctx=ctx,
        reasons=case.reasons,
        need=need,
        address=address,
        mailed_on=mailed_on,
    )
    case.escalation_to = escalate
    if escalate is not None and escalate.address:
        subject, text = compose_escalation(
            case.actor,
            ctx,
            case.reasons,
            day0=case.day0,
            history=_history(case.steps, case.recipient),
        )
        case.escalation_mail = Mail(to=escalate.address, subject=subject, text=text)


async def cases_for_contract(
    db: AsyncSession, contract_id: int, month: str, today: date
) -> list[Case]:
    return await build(db, today, month=month, contract_id=contract_id)


async def month_list(
    db: AsyncSession, month: str, today: date, *, client_id: Optional[int] = None
) -> dict[str, Any]:
    """Lista spraw miesiąca: wiersze bez treści maili, liczby do filtrów."""

    cases = await build(db, today, month=month, client_id=client_id)
    cases.sort(
        key=lambda c: (
            -c.overdue_days,
            c.current.due if c.current else date.max,
            c.client_name,
            c.person,
        )
    )
    clients: dict[int, dict[str, Any]] = {}
    for case in cases:
        entry = clients.setdefault(
            case.client_id,
            {"client_id": case.client_id, "name": case.client_name, "count": 0},
        )
        entry["count"] += 1
    return {
        "month": month,
        "today": today.isoformat(),
        "counts": {
            "all": len(cases),
            **{actor: sum(1 for c in cases if c.actor == actor) for actor in ACTORS},
            "overdue": sum(1 for c in cases if c.overdue_days > 0),
        },
        "clients": sorted(clients.values(), key=lambda c: c["name"]),
        "cases": [case.as_dict(full=False) for case in cases],
    }


# ── Zapis: ręczna wysyłka i telefon ─────────────────────────────────────────


async def _one(db: AsyncSession, settlement_id: int, actor: str, today: date) -> Case:
    if actor not in ACTORS:
        raise SettlementError("Nieznany adresat sprawy.", status=422)
    found = next(
        (
            c
            for c in await build(db, today, settlement_id=settlement_id)
            if c.actor == actor
        ),
        None,
    )
    if found is None:
        raise SettlementError(
            "Tej sprawy już nie ma: wada zniknęła albo rozliczenie przyjęto."
        )
    return found


def _outcome(result: Optional[MailOutcome]) -> str:
    if result is None:
        return "blocked"
    if result.status == "accepted":
        return "simulated" if result.simulated else "sent"
    return "failed"


async def _mark_feedback(
    db: AsyncSession, case: Case, mail: Mail, by: User, today: date, outcome: str
) -> None:
    """Wady z katalogu: wysłany ręcznie mail też jest komunikatem, żeby automat
    po włączeniu nie wysłał tego samego drugi raz tego dnia (``last_sent_on``)."""

    codes = [r.code for r in case.reasons if r.found is not None]
    if not codes:
        return
    rows = (
        await db.scalars(
            select(ClientSettlementFeedback).where(
                ClientSettlementFeedback.contract_id == case.contract_id,
                ClientSettlementFeedback.period_month == case.month,
                ClientSettlementFeedback.code.in_(codes),
                ClientSettlementFeedback.resolved_on.is_(None),
            )
        )
    ).all()
    entry = {
        "on": today.isoformat(),
        "mode": "manual",
        "to": case.recipient.kind if case.recipient else None,
        "channel": "mail",
        "address": mail.to,
        "cc": mail.cc,
        "by_user_id": by.id,
        "codes": codes,
        "subject": mail.subject,
        "text": mail.text,
        "outcome": outcome,
    }
    for row in rows:
        row.sends = [*(row.sends or []), entry]
        row.last_sent_on = today
        row.send_count = (row.send_count or 0) + 1


async def send_mail(
    db: AsyncSession,
    settlement_id: int,
    actor: str,
    *,
    escalation: bool,
    by: User,
    today: date,
) -> tuple[str, Case]:
    """„Wyślij” z karty sprawy: przygotowany mail, po kliknięciu (bez commita).

    Treść i adresat liczą się na serwerze od nowa — front niczego nie podaje.
    Drugi mail do tej samej osoby tego dnia = 409 (podwójne kliknięcie)."""

    case = await _one(db, settlement_id, actor, today)
    mail = case.escalation_mail if escalation else case.mail
    if mail is None or not mail.to:
        raise SettlementError(
            "Brak adresu do eskalacji."
            if escalation
            else "Brak adresata dla tej sprawy.",
        )
    step = ESCALATION if escalation else case.mail_step or MAIL
    # Jeden mail dziennie do tej samej osoby (podwójne kliknięcie albo dwie
    # osoby naraz); eskalacja idzie do kogoś innego, więc liczy się osobno.
    if any(
        e.action == ACTION_MAIL
        and e.ok
        and e.on == today
        and (e.step == ESCALATION) == escalation
        for e in case.log
    ):
        raise SettlementError("Ten mail poszedł już dziś.")
    mailer = mailer_factory()
    if mailer is None:
        raise SettlementError(
            "Wysyłka maili z NEXUS-a jest wyłączona (brak nadawcy). Skopiuj treść "
            "i wyślij z Outlooka.",
        )
    try:
        if mail.cc:
            result = await mailer.send(
                to=mail.to, subject=mail.subject, text=mail.text, cc=mail.cc
            )
        else:
            result = await mailer.send(to=mail.to, subject=mail.subject, text=mail.text)
    except Exception:  # noqa: BLE001 — błąd skrzynki ma wrócić jako komunikat
        logger.exception("settlement_case: mail settlement=%s", settlement_id)
        result = MailOutcome("uncertain", "exception")
    outcome = _outcome(result)
    to = case.escalation_to if escalation else case.recipient
    audit.record(
        db,
        actor_user_id=by.id,
        subject_user_id=None,
        entity_type=ENTITY,
        entity_id=settlement_id,
        action=ACTION_MAIL,
        details={
            "actor": actor,
            "step": step,
            "month": case.month,
            "contract_id": case.contract_id,
            "to_kind": to.kind if to else None,
            "to_label": to.label if to else None,
            "address": mail.to,
            "cc": mail.cc,
            "subject": mail.subject,
            "codes": [r.code for r in case.reasons],
            "outcome": outcome,
        },
    )
    if outcome in SENT_OUTCOMES and not escalation:
        await _mark_feedback(db, case, mail, by, today, outcome)
    await db.flush()
    return outcome, case


async def log_call(
    db: AsyncSession,
    settlement_id: int,
    actor: str,
    *,
    result: str,
    note: Optional[str],
    by: User,
    today: date,
) -> Case:
    """„Zadzwoniłem”: wynik rozmowy w śladzie sprawy (bez commita)."""

    if result not in CALL_RESULTS:
        raise SettlementError("Nieznany wynik rozmowy.", status=422)
    case = await _one(db, settlement_id, actor, today)
    if actor == FINANCE:
        raise SettlementError("Finanse rozstrzygają tę sprawę na karcie, bez telefonu.")
    clean = " ".join((note or "").split())[:NOTE_MAX] or None
    audit.record(
        db,
        actor_user_id=by.id,
        subject_user_id=None,
        entity_type=ENTITY,
        entity_id=settlement_id,
        action=ACTION_CALL,
        details={
            "actor": actor,
            "step": CALL,
            "month": case.month,
            "contract_id": case.contract_id,
            "result": result,
            "note": clean,
        },
    )
    await db.flush()
    return case
