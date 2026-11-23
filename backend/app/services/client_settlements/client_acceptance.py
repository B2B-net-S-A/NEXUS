"""Zbiorcza wysyłka dowodów pracy do akceptacji klienta i jego odpowiedź (roadmapa E6.5).

Bank Pocztowy (instrukcja rozliczeń z 18.11.2026): KCP od konsultantów zbieramy
i wysyłamy paczką na skrzynkę body leasingu banku; kontraktora rozliczamy bez
czekania, a fakturę do klienta wystawiamy po akceptacji. Bank odpisuje w wątku
paczki: „Akceptuję nadesłane KCP. Proszę o dosłanie brakujących: …”, a na
dosłane KCP „Potwierdzam”.

Decyzje Artura z 18.11.2026: paczkę szykuje NEXUS (zip z KCP i treść maila),
wysyła człowiek z Outlooka i klika „Oznacz jako wysłane”; akceptację NEXUS czyta
z odpowiedzi banku (mail z domeny adresu z reguły ``cl.client_acceptance``),
a przy niejasnej odpowiedzi Finanse klikają „Klient zaakceptował”.

Odpowiedź akceptująca obejmuje osoby wysłane przed nią, poza wymienionymi po
słowie „brakujących”. Stan osoby leży w danych przy kontrolach rozliczenia
(``service.CLIENT_ACCEPTANCE``) i przeżywa przeliczenie.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.consultant_portal import CpDocument
from app.models.user import User
from app.services.client_settlements import kcp, mail_text, redmine_timelog, service
from app.services.client_settlements.rcp_checks import name_tokens

logger = logging.getLogger(__name__)

KEY = service.CLIENT_ACCEPTANCE
DEFAULT_SUBJECT = "KCP B2Bnetwork {miesiac} {rok}"
NONE, TO_SEND, SENT, ACCEPTED = "none", "to_send", "sent", "accepted"
MONTHS_LOWER = tuple(m.lower() for m in kcp.MONTHS_PL)
_OPEN = {"checking", "ok", "warnings", "no_md", "accepted"}

# Granica cytatu w odpowiedzi: nagłówek poprzedniej wiadomości.
_QUOTE = re.compile(
    r"^\s*(?:from|od|wysłane|sent)\s*:|^\s*-{2,}\s*original|^\s*_{6,}",
    re.IGNORECASE | re.MULTILINE,
)
_ACCEPT = re.compile(
    r"\b(?:akceptuj\w*|zaakceptow\w*|potwierdzam\w*|potwierdzon\w*|akceptacj\w*)",
    re.IGNORECASE,
)
_REJECT = re.compile(
    r"\bnie\s+(?:akceptuj|potwierdzam|zaakceptow|mo[zż]emy\s+zaakceptow)|odrzuc",
    re.IGNORECASE,
)
_MISSING = re.compile(r"brakuj\w*|brak\w*\s+(?:kcp|kart)", re.IGNORECASE)


@dataclass(frozen=True)
class Params:
    email: str
    domain: str
    subject: str


@dataclass(frozen=True)
class Reply:
    sender_domain: str
    sent_at: Optional[datetime]
    month: Optional[str]
    accepted: bool
    #: Tekst po „brakujących” w najnowszej wiadomości (osoby, o które prosi klient).
    missing_text: str
    #: Pierwsza linia odpowiedzi, do pokazania przy paczce.
    quote: str


def params(rules: dict[str, dict[str, Any]]) -> Optional[Params]:
    rule = rules.get("cl.client_acceptance")
    if not rule or rule["level"] == "off":
        return None
    email = str(rule["params"].get("email") or "").strip().lower()
    subject = str(rule["params"].get("subject") or "").strip() or DEFAULT_SUBJECT
    domain = email.rsplit("@", 1)[1] if "@" in email else ""
    return Params(email=email, domain=domain, subject=subject)


def month_words(month: str) -> tuple[str, str]:
    year, mon = (int(x) for x in month.split("-"))
    return MONTHS_LOWER[mon - 1], str(year)


def subject_for(p: Params, month: str) -> str:
    word, year = month_words(month)
    return p.subject.replace("{miesiac}", word).replace("{rok}", year)


def body_for(month: str, names: list[str]) -> str:
    word, year = month_words(month)
    listed = ", ".join(names)
    return (
        "Dzień dobry,\n\n"
        f"w załączeniu przesyłam KCP naszych konsultantów za {word} {year}"
        + (f": {listed}" if listed else "")
        + ".\nProśba o akceptację.\n"
    )


def file_name(person: str) -> str:
    """„J. Kowalski.pdf” — pierwsza litera imienia i nazwisko (instrukcja BP)."""

    parts = person.split()
    if len(parts) < 2:
        return f"{person or 'KCP'}.pdf"
    return f"{parts[0][0]}. {' '.join(parts[1:])}.pdf"


# ── Stan osoby ───────────────────────────────────────────────────────────────


def state_of(s: Optional[ClientSettlement]) -> dict[str, Any]:
    value = service.meta_of(s).get(KEY)
    return value if isinstance(value, dict) else {}


def status(s: Optional[ClientSettlement]) -> str:
    st = state_of(s)
    if st.get("accepted_at"):
        return ACCEPTED
    if st.get("sent_at"):
        return SENT
    if s is not None and s.report_document_id is not None and s.status in _OPEN:
        return TO_SEND
    return NONE


def waiting(s: Optional[ClientSettlement], rules: dict[str, dict[str, Any]]) -> bool:
    """Faktura do klienta czeka na akceptację tej osoby przez klienta."""

    return (
        params(rules) is not None
        and rules["cl.after_signed_document"]["level"] != "off"
        and status(s) != ACCEPTED
    )


def _write(s: ClientSettlement, value: dict[str, Any]) -> None:
    items = [dict(c) if isinstance(c, dict) else c for c in (s.checks or [])]
    meta = next(
        (c for c in items if isinstance(c, dict) and "remaining_after" in c), None
    )
    if meta is None:
        meta = {"remaining_after": None}
        items.append(meta)
    meta[KEY] = value
    s.checks = items


def summary(s: Optional[ClientSettlement]) -> dict[str, Any]:
    st = state_of(s)
    return {
        "state": status(s),
        "sent_at": st.get("sent_at"),
        "accepted_at": st.get("accepted_at"),
        "reply": st.get("reply"),
        "source": st.get("source"),
    }


def check_group(s: Optional[ClientSettlement], p: Params) -> dict[str, Any]:
    """Grupa „Akceptacja klienta” na karcie osoby (stan, nie wynik odczytu RCP)."""

    st = state_of(s)
    current = status(s)
    checks: list[dict[str, Any]] = []
    if st.get("sent_at"):
        checks.append(
            {
                "state": "ok",
                "title": f"Wysłana do klienta {_day(st['sent_at'])}",
                "detail": f"Na {p.email}." if p.email else None,
            }
        )
    if current == ACCEPTED:
        how = f"„{st['reply']}”" if st.get("reply") else "kliknięte przez Finanse"
        checks.append(
            {
                "state": "ok",
                "title": f"Zaakceptowana {_day(st['accepted_at'])}",
                "detail": f"Odpowiedź klienta: {how}."
                if st.get("source") == "mail"
                else "Akceptację zaznaczyły Finanse.",
            }
        )
    elif current == SENT:
        checks.append(
            {
                "state": "warn",
                "title": "Czeka na akceptację klienta",
                "detail": "Faktura do klienta po akceptacji. Kontraktora rozliczamy bez czekania.",
            }
        )
    elif current == TO_SEND:
        checks.append(
            {
                "state": "warn",
                "title": "Jeszcze nie wysłana do klienta",
                "detail": "Wejdzie do paczki „Wyślij do akceptacji” nad listą miesiąca.",
            }
        )
    else:
        checks.append(
            {
                "state": "none",
                "title": "Do klienta pójdzie po wpłynięciu KCP",
                "detail": None,
            }
        )
    return {"title": "Akceptacja klienta", "checks": checks}


def _day(value: Any) -> str:
    text = str(value or "")
    return f"{text[8:10]}.{text[5:7]}.{text[:4]}" if len(text) >= 10 else text


# ── Odpowiedź klienta ────────────────────────────────────────────────────────


def top_message(body: str) -> str:
    """Najnowsza wiadomość wątku: tekst do pierwszego cytowanego nagłówka."""

    match = _QUOTE.search(body or "")
    return (body[: match.start()] if match else body or "").strip()


def _domain(sender: str) -> str:
    found = re.search(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", sender or "")
    return found.group(1).lower() if found else ""


def _month(subject: str) -> Optional[str]:
    from app.services.consultant_portal.mailbox import find_period

    found = find_period(subject or "")
    return f"{found[0]}-{found[1]:02d}" if found else None


def accepts(text: str) -> bool:
    """Tekst klienta akceptuje godziny: słowo akceptacji i żadnego odrzucenia."""

    return bool(_ACCEPT.search(text or "")) and not _REJECT.search(text or "")


def judge(mail: mail_text.Mail) -> Reply:
    top = top_message(mail.body)
    missing = _MISSING.search(top)
    lines = [line.strip() for line in top.splitlines() if line.strip()]
    greeting = re.compile(r"^(dzie[nń] dobry|witam|szanown)", re.IGNORECASE)
    first = next((line for line in lines if not greeting.match(line)), "")
    return Reply(
        sender_domain=_domain(mail.sender),
        sent_at=mail.sent_at,
        month=_month(mail.subject),
        accepted=accepts(top),
        missing_text=top[missing.end() :] if missing else "",
        quote=first[:160],
    )


def read_reply(content: bytes, mime: str) -> Optional[Reply]:
    mail = mail_text.read(content, mime)
    return judge(mail) if mail is not None else None


def named(person: str, text: str) -> bool:
    tokens = name_tokens(person)
    return bool(tokens) and tokens <= name_tokens(text)


async def _clients_for_domain(db: AsyncSession, domain: str, month: str) -> list[int]:
    if not domain:
        return []
    ids = (await db.scalars(select(ClientSettlementRuleSet.client_id).distinct())).all()
    out = []
    for client_id in ids:
        p = params(await service.rules_for(db, client_id, month))
        if p is not None and p.domain == domain:
            out.append(client_id)
    return out


async def is_client_domain(db: AsyncSession, sender: str, month: str) -> bool:
    return bool(await _clients_for_domain(db, _domain(sender), month))


async def apply_reply(
    db: AsyncSession, reply: Reply, *, month: str, now: datetime
) -> int:
    """Odpowiedź akceptująca → osoby wysłane przed nią, poza wymienionymi jako
    brakujące. Zwraca liczbę zaakceptowanych osób."""

    if not reply.accepted:
        return 0
    month = reply.month or month
    count = 0
    for client_id in await _clients_for_domain(db, reply.sender_domain, month):
        for person in await service._people(db, client_id, month):
            s = await service._settlement(
                db, person.contract.id, month, for_update=True
            )
            if status(s) != SENT or s is None:
                continue
            st = state_of(s)
            sent = _parse(st.get("sent_at"))
            if reply.sent_at and sent and sent > reply.sent_at:
                continue
            if reply.missing_text and named(person.name, reply.missing_text):
                continue
            _write(
                s,
                {
                    **st,
                    "accepted_at": (reply.sent_at or now).isoformat(),
                    "reply": reply.quote,
                    "source": "mail",
                },
            )
            count += 1
    return count


def _parse(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


async def apply(db: AsyncSession, document: CpDocument, *, now: datetime) -> int:
    """Mail od klienta (rozliczenia@ albo „Wgraj odpowiedź klienta”) z akceptacją."""

    from app.services.consultant_portal import documents as portal_documents

    if document.mime not in mail_text.MAIL_MIMES:
        return 0
    try:
        content = portal_documents.path_for(document.file_path).read_bytes()
    except OSError:
        return 0
    reply = await asyncio.to_thread(read_reply, content, document.mime)
    if reply is None:
        return 0
    month = f"{document.period_year}-{document.period_month:02d}"
    count = await apply_reply(db, reply, month=month, now=now)
    if count:
        document.contract_id = None
        if document.status == "received":
            document.status = "accepted"
            document.decided_at = now
        document.updated_at = now
    return count


# ── Finanse: paczka, wysłane, akceptacja ręczna ─────────────────────────────


async def _rows(
    db: AsyncSession, client_id: int, month: str
) -> list[tuple[service.Person, Optional[ClientSettlement]]]:
    out = []
    for person in await service._people(db, client_id, month):
        out.append((person, await service._settlement(db, person.contract.id, month)))
    return out


async def month_view(db: AsyncSession, client_id: int, month: str) -> dict[str, Any]:
    client = await db.get(Client, client_id)
    if client is None:
        raise service.SettlementError("Nie ma takiego klienta.", status=404)
    p = params(await service.rules_for(db, client_id, month))
    if p is None:
        return {"enabled": False, "client_id": client_id, "month": month}
    people = []
    batches: dict[str, dict[str, Any]] = {}
    for person, s in await _rows(db, client_id, month):
        info = {"contract_id": person.contract.id, "person": person.name, **summary(s)}
        people.append(info)
        if info["sent_at"]:
            batch = batches.setdefault(
                str(info["sent_at"])[:16],
                {
                    "sent_at": info["sent_at"],
                    "people": 0,
                    "accepted": 0,
                    "accepted_at": None,
                    "reply": None,
                },
            )
            batch["people"] += 1
            if info["state"] == ACCEPTED:
                batch["accepted"] += 1
                batch["accepted_at"] = max(
                    filter(None, [batch["accepted_at"], info["accepted_at"]])
                )
                batch["reply"] = batch["reply"] or info["reply"]
    to_send = [x for x in people if x["state"] == TO_SEND]
    return {
        "enabled": True,
        "client_id": client_id,
        "month": month,
        "email": p.email,
        "subject": subject_for(p, month),
        "body": body_for(month, [x["person"] for x in to_send]),
        "people": people,
        "batches": sorted(batches.values(), key=lambda b: str(b["sent_at"])),
        "counts": {
            state: sum(1 for x in people if x["state"] == state)
            for state in (NONE, TO_SEND, SENT, ACCEPTED)
        },
    }


async def _pick(
    db: AsyncSession, client_id: int, month: str, contract_ids: Optional[list[int]]
) -> list[tuple[service.Person, ClientSettlement]]:
    if params(await service.rules_for(db, client_id, month)) is None:
        raise service.SettlementError(
            "Klient nie ma reguły akceptacji dowodów pracy mailem.", status=404
        )
    chosen = []
    for person, s in await _rows(db, client_id, month):
        if s is None or (
            contract_ids is not None and person.contract.id not in contract_ids
        ):
            continue
        chosen.append((person, s))
    return chosen


async def card_pdf(db: AsyncSession, contract_id: int, month: str) -> tuple[bytes, str]:
    """KCP osoby w PDF: plik od konsultanta albo złożona z eksportu Redmine."""

    from app.services.consultant_portal import documents as portal_documents

    person = await service._contract(db, contract_id)
    s = await service._settlement(db, contract_id, month)
    if s is None or s.report_document_id is None:
        raise service.SettlementError("Osoba nie ma KCP za ten miesiąc.", status=404)
    report = await db.get(CpDocument, s.report_document_id)
    if report is None:
        raise service.SettlementError("Osoba nie ma KCP za ten miesiąc.", status=404)
    try:
        content = portal_documents.path_for(report.file_path).read_bytes()
    except OSError as exc:
        raise service.SettlementError(
            "Pliku KCP nie da się odczytać.", status=404
        ) from exc
    name = file_name(person.name)
    if report.mime == kcp.PDF:
        return content, name
    card = await asyncio.to_thread(
        redmine_timelog.read_card, content, report.mime, month
    )
    if card is None:
        raise service.SettlementError(
            "Plik osoby to nie KCP ani eksport z Redmine.", status=404
        )
    pdf = await asyncio.to_thread(redmine_timelog.render_pdf, card[0])
    return pdf, name


async def package(
    db: AsyncSession, client_id: int, month: str, *, only_to_send: bool = True
) -> tuple[bytes, int]:
    """Zip z KCP w PDF do wysyłki klientowi; domyślnie osoby jeszcze niewysłane."""

    buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for person, s in await _pick(db, client_id, month, None):
            if status(s) not in (
                (TO_SEND,) if only_to_send else (TO_SEND, SENT, ACCEPTED)
            ):
                continue
            try:
                content, name = await card_pdf(db, person.contract.id, month)
            except service.SettlementError:
                continue
            archive.writestr(name, content)
            count += 1
    return buffer.getvalue(), count


async def mark_sent(
    db: AsyncSession,
    client_id: int,
    month: str,
    contract_ids: list[int],
    *,
    actor: User,
    now: datetime,
) -> int:
    count = 0
    for _person, s in await _pick(db, client_id, month, contract_ids):
        if status(s) != TO_SEND:
            continue
        _write(s, {"sent_at": now.isoformat(), "sent_by": actor.id})
        s.updated_by = actor.id
        count += 1
    if not count:
        raise service.SettlementError("Żadna z tych osób nie czeka na wysyłkę.")
    return count


async def accept(
    db: AsyncSession,
    client_id: int,
    month: str,
    contract_ids: list[int],
    *,
    actor: User,
    now: datetime,
) -> int:
    count = 0
    for _person, s in await _pick(db, client_id, month, contract_ids):
        if status(s) != SENT:
            continue
        _write(
            s,
            {
                **state_of(s),
                "accepted_at": now.isoformat(),
                "accepted_by": actor.id,
                "source": "manual",
            },
        )
        s.updated_by = actor.id
        count += 1
    if not count:
        raise service.SettlementError(
            "Żadna z tych osób nie czeka na akceptację klienta: najpierw wyślij KCP."
        )
    return count
