"""Czytnik skrzynki ``rozliczenia@``: drugi kanał dokumentów konsultanta.

Wzór: ``order_mail_ingest`` (wspólnej warstwy skrzynek nie ma). Czytamy przez rejestrację
„NEXUS Kadry”, tylko do odczytu: nic w skrzynce nie zmieniamy. Skrzynka i dostęp nie są
jeszcze skonfigurowane, dlatego brak ``CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX`` albo tokenu
daje czytelny stan w ``cp_mailbox_state``, a nie wyjątek.

* Wyłączony portal = czytnik nie rusza. W pilotażu bierze wyłącznie nadawców z pilotażu:
  reszta firmy nadal rozlicza się po staremu i jej maili nie dotykamy.
* Nadawcę dopasowujemy po adresie z kontraktu. Adres można podrobić, dlatego dokument
  z maila zawsze czeka na decyzję Finansów, a nieznany nadawca (tylko w stanie ``all``)
  daje kartę do ręcznego przypisania.
* Znacznik idzie z zakładką 2 h, a duplikaty zamyka unikat na (wiadomość, plik).
  Do logu trafia klasa błędu, nigdy adres ani temat.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.client_settlement import ClientSettlement
from app.models.consultant_portal import CpMailboxState
from app.models.contract import Contract
from app.models.user import User
from app.services.client_settlements import kesu
from app.services.consultant_portal import documents, identity, portal_settings
from app.services.consultant_portal.auth import PortalError
from app.services.m365.app_graph_client import AppGraphClient, AppOnlyTokenUnavailable
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

OVERLAP = timedelta(hours=2)
INITIAL_LOOKBACK = timedelta(days=3)
MAX_MESSAGES_PER_RUN = 200
_MESSAGE_SELECT = "id,subject,from,receivedDateTime,hasAttachments"
_FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"
_REPORT = re.compile(
    r"raport|timesheet|ewidencj|godzin|ke[sś]u|rozliczenie\s+kontraktora", re.IGNORECASE
)
_INVOICE = re.compile(r"faktur|invoice|(?:^|[^a-z])fv(?:[^a-z]|$)", re.IGNORECASE)
_PERIOD_NUMERIC = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])[./_-](20\d{2})(?!\d)")
_PERIOD_ISO = re.compile(r"(?<!\d)(20\d{2})[./_-](0?[1-9]|1[0-2])(?!\d)")
_MONTH_STEMS = (
    "stycz",
    "lut",
    "mar",
    "kwie",
    "maj",
    "czerw",
    "lip",
    "sierp",
    "wrze",
    "pa[zź]dziern",
    "listopad",
    "grud",
)
_PERIOD_WORD = re.compile(
    r"(" + "|".join(_MONTH_STEMS) + r")\w*\s+(20\d{2})", re.IGNORECASE
)


class SettlementsMailbox(Protocol):
    async def list_messages(self, since: datetime) -> list[dict[str, Any]]: ...

    async def attachments(self, message_id: str) -> list[dict[str, Any]]: ...

    async def mime(self, message_id: str) -> Optional[bytes]: ...


def mailbox_upn() -> Optional[str]:
    return (settings.CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX or "").strip() or None


class GraphSettlementsMailbox:
    """Skrzynka przez Graph app-only. Ścieżki zawsze ``/users/{upn}/…``."""

    def __init__(self, upn: str) -> None:
        self._prefix = f"/users/{quote(upn, safe='@.')}"

    def _client(self) -> AppGraphClient:
        from app.services.hr.m365.auth import acquire_hr_token

        return AppGraphClient(token_provider=acquire_hr_token)

    async def list_messages(self, since: datetime) -> list[dict[str, Any]]:
        moment = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$filter": f"receivedDateTime ge {moment}",
            "$select": _MESSAGE_SELECT,
            "$orderby": "receivedDateTime asc",
            "$top": "50",
        }
        out: list[dict[str, Any]] = []
        async with self._client() as client:
            async for page in client.paginate(
                f"{self._prefix}/mailFolders/Inbox/messages", params=params
            ):
                out.extend(page.get("value", []))
                if len(out) >= MAX_MESSAGES_PER_RUN:
                    return out[:MAX_MESSAGES_PER_RUN]
        return out

    async def attachments(self, message_id: str) -> list[dict[str, Any]]:
        async with self._client() as client:
            page = await client.get(
                f"{self._prefix}/messages/{quote(message_id, safe='')}/attachments"
            )
        return list((page or {}).get("value") or [])

    async def mime(self, message_id: str) -> Optional[bytes]:
        """Cały mail (MIME), np. z Jiry: treść niesie opiekuna i czas akceptacji."""

        async with self._client() as client:
            return await client.download(
                f"{self._prefix}/messages/{quote(message_id, safe='')}/$value"
            )


def classify_kind(subject: str, file_name: str) -> str:
    """Raport albo faktura z nazwy pliku, potem z tematu; domyślnie faktura."""

    for text in (file_name, subject):
        if _INVOICE.search(text):
            return "invoice"
        if _REPORT.search(text):
            return "report"
    return "invoice"


def find_period(text: str) -> Optional[tuple[int, int]]:
    """(rok, miesiąc) z tekstu: „10/2026”, „2026-10”, „październik 2026”."""

    match = _PERIOD_ISO.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = _PERIOD_NUMERIC.search(text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = _PERIOD_WORD.search(text)
    if match:
        stem = match.group(1).lower()
        for index, pattern in enumerate(_MONTH_STEMS, start=1):
            if re.fullmatch(pattern, stem):
                return int(match.group(2)), index
    return None


def period_for(subject: str, file_name: str, received: date) -> tuple[int, int, bool]:
    """Okres pliku; bez znaku w treści: miesiąc przed datą maila, z flagą „zgadnięty”."""

    found = find_period(file_name) or find_period(subject)
    if found:
        return found[0], found[1], False
    total = received.year * 12 + received.month - 2
    return total // 12, total % 12 + 1, True


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sender(message: dict[str, Any]) -> str:
    address = ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    return identity.normalize_email(address)


async def _state(db: AsyncSession) -> Optional[CpMailboxState]:
    return await db.get(CpMailboxState, 1)


async def _write_state(
    db: AsyncSession,
    *,
    now: datetime,
    status: str,
    error: Optional[str] = None,
    seen: Optional[datetime] = None,
) -> None:
    values: dict[str, Any] = {
        "last_run_at": now,
        "last_status": status,
        "last_error": error,
    }
    if seen is not None:
        values["last_seen_received_at"] = seen
    await db.execute(
        insert(CpMailboxState)
        .values(id=1, **values)
        .on_conflict_do_update(index_elements=[CpMailboxState.id], set_=values)
    )
    await db.commit()


async def _ingest_message(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    state: portal_settings.PortalSettings,
    today: date,
    now: datetime,
) -> tuple[int, int]:
    """(nowe, pominięte). Reguła pilotażu przed odczytem załączników."""

    if not message.get("hasAttachments"):
        return 0, 0
    sender = _sender(message)
    subject = str(message.get("subject") or "")
    by_subject = await _kesu_contract(db, subject, sender, state=state, today=today)
    contract = by_subject or await identity.resolve_by_email(
        db, sender, settings=state, today=today
    )
    if contract is None and state.state != "all":
        return 0, 1
    contract_id = contract.id if contract else None
    received = _parse_time(message.get("receivedDateTime")) or now
    created = skipped = 0
    if kesu.parse_jira(subject, "") is not None:
        made = await _store_jira_mail(
            db,
            mailbox,
            message,
            contract_id=contract_id,
            subject=subject,
            received=received,
            now=now,
            sender=sender,
        )
        created += made
    for attachment in await mailbox.attachments(str(message["id"])):
        if attachment.get("@odata.type") != _FILE_ATTACHMENT or attachment.get(
            "isInline"
        ):
            continue
        raw = attachment.get("contentBytes")
        if not isinstance(raw, str):
            continue
        name = str(attachment.get("name") or "")
        if kesu.is_kesu_subject(subject) and kesu.is_transport_statement(name):
            # Oświadczenie o własnym transporcie ma PESEL i dowód: nie w NEXUS-ie
            # (odpowiedź rozliczeń z 12.11.2026), rozliczenia dosyłają je osobno.
            skipped += 1
            continue
        try:
            content = base64.b64decode(raw, validate=True)
        except ValueError:
            skipped += 1
            continue
        year, month, guessed = period_for(subject, name, received.date())
        try:
            stored = await documents.store(
                db,
                contract_id=contract_id,
                kind=classify_kind(subject, name),
                year=year,
                month=month,
                content=content,
                file_name=name or None,
                channel="mailbox",
                now=now,
                period_guessed=guessed,
                graph_message_id=str(message["id"])[:512],
                sender_email=sender[:320] or None,
            )
        except PortalError:
            # Plik spoza listy typów (np. podpis graficzny w innym formacie).
            skipped += 1
            continue
        created += 0 if stored.duplicate else 1
    return created, skipped


async def _kesu_contract(
    db: AsyncSession,
    subject: str,
    sender: str,
    *,
    state: portal_settings.PortalSettings,
    today: date,
) -> Optional[Contract]:
    """KEŚU (E6.3): osoba z tematu, ale tylko z zaufanego kanału.

    Mail z Jiry przekazuje koordynator, więc nadawcą musi być aktywne konto
    NEXUS-a (osoba z tematu ma pierwszeństwo przed kontraktem nadawcy, gdyby
    koordynator sam miał kontrakt). Odpowiedź „KEŚU … - osoba” przychodzi od
    klienta: przypisujemy ją tylko z domeny opiekuna z maila z Jiry tej osoby.
    Inny nadawca = zwykła ścieżka (adres z kontraktu albo karta do przypisania),
    bo sam temat może napisać każdy.
    """

    person = kesu.person_from_subject(subject)
    if person is None or "@" not in sender:
        return None
    if kesu.parse_jira(subject, "") is not None:
        staff = await db.scalar(
            select(User.id).where(
                func.lower(User.email) == sender, User.is_active.is_(True)
            )
        )
        if staff is None:
            return None
        return await identity.resolve_by_name(db, person, settings=state, today=today)
    contract = await identity.resolve_by_name(db, person, settings=state, today=today)
    if contract is None:
        return None
    from app.services.client_settlements import service as settlements

    domain = sender.rsplit("@", 1)[1]
    recent = (
        await db.scalars(
            select(ClientSettlement)
            .where(ClientSettlement.contract_id == contract.id)
            .order_by(ClientSettlement.period_month.desc())
            .limit(3)
        )
    ).all()
    for settlement in recent:
        approver = (settlements.meta_of(settlement).get("kesu") or {}).get(
            "approver_email"
        )
        if approver and str(approver).lower().rsplit("@", 1)[-1] == domain:
            return contract
    return None


async def _store_jira_mail(
    db: AsyncSession,
    mailbox: SettlementsMailbox,
    message: dict[str, Any],
    *,
    contract_id: Optional[int],
    subject: str,
    received: datetime,
    now: datetime,
    sender: str,
) -> int:
    """Mail z Jiry jako EML przy KEŚU: z treści bierzemy opiekuna i czas akceptacji."""

    reader = getattr(mailbox, "mime", None)
    if reader is None:
        return 0
    try:
        content = await reader(str(message["id"]))
    except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
        code = (
            f"http_{exc.status}" if isinstance(exc, GraphRequestError) else "no_token"
        )
        logger.warning("consultant_portal_mailbox: jira mime failed %s", code)
        return 0
    if not content:
        return 0
    year, month, guessed = period_for(subject, "", received.date())
    try:
        stored = await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=year,
            month=month,
            content=content,
            file_name=f"Akceptacja Jira {month:02d}-{year}.eml",
            channel="mailbox",
            now=now,
            period_guessed=guessed,
            graph_message_id=str(message["id"])[:512],
            sender_email=sender[:320] or None,
        )
    except PortalError:
        return 0
    return 0 if stored.duplicate else 1


async def run_once(
    db: AsyncSession,
    *,
    mailbox: Optional[SettlementsMailbox] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    state = await portal_settings.load(db)
    if not state.is_on:
        return {"status": "disabled"}
    upn = mailbox_upn()
    if mailbox is None and upn is None:
        await _write_state(db, now=moment, status="disabled", error="no_mailbox")
        return {"status": "disabled", "reason": "no_mailbox"}
    reader: SettlementsMailbox = mailbox or GraphSettlementsMailbox(upn or "")
    current = await _state(db)
    seen = current.last_seen_received_at if current else None
    since = (seen - OVERLAP) if seen else moment - INITIAL_LOOKBACK
    today = business_today()
    try:
        messages = await reader.list_messages(since)
    except (GraphRequestError, AppOnlyTokenUnavailable) as exc:
        code = (
            f"http_{exc.status}" if isinstance(exc, GraphRequestError) else "no_token"
        )
        logger.warning("consultant_portal_mailbox: list failed %s", code)
        await _write_state(db, now=moment, status="error", error=code)
        return {"status": "error", "reason": code}
    created = skipped = failed = 0
    newest = seen
    for message in messages:
        try:
            async with db.begin_nested():
                made, ignored = await _ingest_message(
                    db, reader, message, state=state, today=today, now=moment
                )
            created += made
            skipped += ignored
        except Exception as exc:  # noqa: BLE001 — jedna wiadomość nie zatrzymuje reszty
            failed += 1
            logger.warning(
                "consultant_portal_mailbox: message failed (%s)", type(exc).__name__
            )
            # Znacznik nie idzie poza pierwszą porażkę: spróbujemy jej ponownie.
            break
        received = _parse_time(message.get("receivedDateTime"))
        if received and (newest is None or received > newest):
            newest = received
    await _write_state(
        db,
        now=moment,
        status="partial" if failed else "ok",
        error=None,
        seen=newest,
    )
    return {
        "status": "partial" if failed else "ok",
        "messages": len(messages),
        "created": created,
        "skipped": skipped,
        "failed": failed,
    }


async def status(db: AsyncSession) -> dict[str, Any]:
    row = await db.scalar(select(CpMailboxState).where(CpMailboxState.id == 1))
    return {
        "configured": mailbox_upn() is not None,
        "last_run_at": row.last_run_at.isoformat() if row and row.last_run_at else None,
        "last_status": row.last_status if row else None,
        "last_error": row.last_error if row else None,
    }
