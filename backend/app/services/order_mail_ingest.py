"""Pobieranie zamówień ze skrzynki kopii w M365 → dziennik ``order_mail_documents``.

Cienki reader na ``GraphClient`` (tylko Inbox, tylko wiadomości z załącznikami,
tylko PDF-y), celowo OBOK ``m365/sync.py``: tamten sync zakłada wiersze
``emails`` na osiach czasu kandydatów i uruchamia matcher kandydatów, a
zamówienia klientów nie są pocztą żadnego rekrutera. Tu nie powstaje ani jeden
wiersz ``emails``/``email_attachments``.

Przebieg per załącznik: SHA-256 → dedup (ten sam PDF w nowym mailu =
``duplicate_attachment`` wskazujący na pierwowzór) → zapis bajtów → tekst
z metadanymi (re-ekstrakcja przy literowaniu spacjami, cap OCR) →
rozpoznanie klienta (numery rejestrowe ∩ ``clients.nip``, markery, domena) →
odczyt all-rows + polityki klientowe → wpis w dzienniku. Zapis do zamówień
(bramka automatu, planer, writer) jest warstwą wyżej (P4) i czyta ten dziennik.

Idempotencja: Coolify restartuje kontener przy każdym pushu na main, więc bieg
przerwany w połowie jest normalny. Wiersz istniejący dla (Message-ID, SHA)
jest pomijany; wiadomości pytamy od watermarku minus nakładka.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import io
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.m365 import M365Connection
from app.models.order_mail import (
    CONNECTION_PURPOSE_ORDERS,
    GATE_AUTO,
    OUTCOME_AUTO_APPLIED,
    OUTCOME_DUPLICATE,
    OUTCOME_FAILED,
    OUTCOME_IGNORED_NO_PDF,
    OUTCOME_IGNORED_SENDER,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_UNRECOGNIZED,
    OrderMailDocument,
)
from app.services import storage_service
from app.services.m365.app_graph_client import AppGraphClient
from app.services.m365.app_mail import app_only_credentials_configured
from app.services.m365.graph_client import GraphClient
from app.services.order_client_identity import (
    ClientIdentification,
    ClientRegistry,
    identify_client,
    normalize_registry_id,
)
from app.services.order_document_text import OrderDocumentText, extract_order_text
from app.services.order_mail_gate import GateInput, evaluate
from app.services.order_mail_planner import ExistingOrder, plan_document
from app.services.order_mail_resolver import load_roster, resolve_rows
from app.services.order_pdf_parser import OrderExtraction, parse_order_document
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    client_ids_from_env,
    policy_by_key,
)
from app.services.order_policies.known_clients import (
    KNOWN_MARKERS,
    KNOWN_SENDER_DOMAINS,
)

logger = logging.getLogger(__name__)

_ingest_lock = asyncio.Lock()
_MESSAGE_SELECT = (
    "id,internetMessageId,subject,from,sender,receivedDateTime,hasAttachments"
)
_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


def ingest_is_running() -> bool:
    return _ingest_lock.locked()


@dataclass
class IngestStats:
    messages: int = 0
    attachments: int = 0
    ignored_no_pdf: int = 0
    ignored_sender: int = 0
    duplicates: int = 0
    unrecognized: int = 0
    needs_review: int = 0
    skipped_existing: int = 0
    failed: int = 0
    max_received_at: Optional[datetime] = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out = dataclasses.asdict(self)
        out["max_received_at"] = (
            self.max_received_at.isoformat() if self.max_received_at else None
        )
        out["errors"] = self.errors[:20]
        return out


# ── Połączenie skrzynki zamówień ─────────────────────────────────────────────


def auth_mode() -> str:
    """``delegated`` (OAuth użytkownika-bota) albo ``app`` (client_credentials)."""
    mode = (settings.ORDER_MAIL_AUTH_MODE or "delegated").strip().lower()
    return "app" if mode == "app" else "delegated"


def mailbox_prefix() -> str:
    """Prefiks ścieżek Graph dla skrzynki zamówień.

    Delegated: ``/me`` (token JEST użytkownikiem). App-only: ``/users/{upn}`` —
    token nie ma tożsamości użytkownika, więc ``/me`` zwraca 400/401; skrzynkę
    wskazuje ``ORDER_MAIL_UPN``, a Application Access Policy pilnuje, żeby
    żaden inny UPN pod tą ścieżką nie zadziałał.
    """
    if auth_mode() == "app":
        return f"/users/{(settings.ORDER_MAIL_UPN or '').strip()}"
    return "/me"


def app_only_ready() -> bool:
    """Tryb app-only ma komplet: UPN skrzynki + poświadczenia + realny tenant."""
    return (
        bool((settings.ORDER_MAIL_UPN or "").strip())
        and app_only_credentials_configured()
    )


async def find_orders_connection(db: AsyncSession) -> Optional[M365Connection]:
    """Aktywne połączenie skrzynki zamówień; self-healing po UPN.

    Połączenie powstaje zwykłym OAuth-em (użytkownik-bot loguje się jako
    właściciel skrzynki), więc w chwili powstania ma ``purpose='personal'``.
    Gdy jego UPN równa się ``ORDER_MAIL_UPN``, przestawiamy je na ``orders``
    tutaj — bez tego pierwszy tick syncu osobistego zaczyna backfill 12 miesięcy
    zamówień klientów na osie czasu kandydatów.
    """
    upn = (settings.ORDER_MAIL_UPN or "").strip().lower()
    if not upn:
        return None
    conn = await db.scalar(
        select(M365Connection)
        .where(func.lower(M365Connection.mailbox_upn) == upn)
        .where(M365Connection.is_active.is_(True))
        .order_by(M365Connection.updated_at.desc())
        .limit(1)
    )
    if conn is None:
        return None
    if conn.purpose != CONNECTION_PURPOSE_ORDERS:
        conn.purpose = CONNECTION_PURPOSE_ORDERS
        await db.commit()
        logger.info("order_mail: connection id=%s marked purpose=orders", conn.id)
    return conn


# ── Rejestr klientów z bazy ──────────────────────────────────────────────────


async def build_registry_from_db(db: AsyncSession) -> ClientRegistry:
    """NIP-y z ``clients.nip`` → klucz = ``client_id`` jako tekst; markery/domeny z kodu.

    Klucze markerów to klucze POLITYK (``cardif``, ``pfron``…), rozwiązywane
    do ``client_id`` przez env tej polityki (``resolve_client_id``). Jeden
    mechanizm bramkowania — żadnej drugiej listy ID do utrzymania.
    """
    rows = await db.execute(select(Client.id, Client.nip).where(Client.nip.isnot(None)))
    by_id: dict[str, str] = {}
    for client_id, nip in rows.all():
        norm = normalize_registry_id(nip or "")
        if norm:
            by_id[norm] = str(client_id)
    return ClientRegistry(
        by_registry_id=by_id, markers=KNOWN_MARKERS, sender_domains=KNOWN_SENDER_DOMAINS
    )


def resolve_client_id(
    ident: ClientIdentification,
) -> tuple[Optional[int], Optional[str]]:
    """(client_id, klucz polityki) z wyniku rozpoznania.

    Trafienie po numerze rejestrowym niesie ``client_id`` wprost. Trafienie po
    markerze/domenie niesie klucz polityki — ``client_id`` bierzemy z env tej
    polityki, ale tylko gdy jest tam DOKŁADNIE jeden; dwa to niejednoznaczność.
    """
    if not ident.client_key:
        return None, None
    if ident.method == "registry_id" and ident.client_key.isdigit():
        return int(ident.client_key), None
    try:
        policy = policy_by_key(ident.client_key)
    except KeyError:
        return None, ident.client_key
    ids = client_ids_from_env(policy.env_var)
    if len(ids) == 1:
        return next(iter(ids)), policy.key
    return None, policy.key


# ── Serializacja wyniku odczytu ──────────────────────────────────────────────


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if dataclasses.is_dataclass(value):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def extraction_to_json(extraction: OrderExtraction) -> dict[str, Any]:
    return _jsonable(extraction)


def document_meta_to_json(
    doc: OrderDocumentText, extraction: OrderExtraction
) -> dict[str, Any]:
    return {
        "page_count": doc.page_count,
        "ocr_used": doc.ocr_used,
        "ocr_capped": doc.ocr_capped,
        "reextracted_with": doc.reextracted_with,
        "letter_spacing_ratio": doc.letter_spacing_ratio,
        "text_chars": len(doc.text),
        "document_truncated": extraction.document_truncated,
    }


# ── Nadawca ──────────────────────────────────────────────────────────────────


def sender_allowed(domain: Optional[str]) -> bool:
    allow = {
        d.strip().lower()
        for d in settings.ORDER_MAIL_SENDER_ALLOWLIST.split(",")
        if d.strip()
    }
    if not allow:
        return True
    return bool(domain) and domain.lower() in allow


def _sender_of(msg: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    for key in ("from", "sender"):
        addr = ((msg.get(key) or {}).get("emailAddress") or {}).get("address")
        if addr:
            addr = addr.strip().lower()
            return addr, addr.rsplit("@", 1)[-1] if "@" in addr else None
    return None, None


def _parse_graph_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ── Przetwarzanie ────────────────────────────────────────────────────────────


async def _existing(
    db: AsyncSession, message_id: str, sha: Optional[str]
) -> Optional[OrderMailDocument]:
    stmt = select(OrderMailDocument).where(
        OrderMailDocument.internet_message_id == message_id
    )
    stmt = (
        stmt.where(OrderMailDocument.attachment_sha256 == sha)
        if sha
        else stmt.where(OrderMailDocument.attachment_sha256.is_(None))
    )
    return await db.scalar(stmt.limit(1))


async def _first_with_sha(db: AsyncSession, sha: str) -> Optional[OrderMailDocument]:
    return await db.scalar(
        select(OrderMailDocument)
        .where(OrderMailDocument.attachment_sha256 == sha)
        .order_by(OrderMailDocument.id.asc())
        .limit(1)
    )


def _base_row(conn: Optional[M365Connection], msg: dict[str, Any]) -> OrderMailDocument:
    sender, domain = _sender_of(msg)
    return OrderMailDocument(
        # App-only nie ma wiersza połączenia — kolumna jest NULL-owalna od 0264.
        connection_id=conn.id if conn is not None else None,
        internet_message_id=(msg.get("internetMessageId") or msg.get("id") or "")[:998],
        m365_message_id=(msg.get("id") or "")[:512] or None,
        received_at=_parse_graph_dt(msg.get("receivedDateTime")),
        sender_email=sender,
        sender_domain=domain,
        subject=(msg.get("subject") or "")[:1000] or None,
    )


async def process_pdf_bytes(
    db: AsyncSession,
    row: OrderMailDocument,
    payload: bytes,
    *,
    registry: ClientRegistry,
) -> OrderMailDocument:
    """Tekst → rozpoznanie → odczyt → polityki → wynik. Wspólne dla maila i testów."""
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, prefix="nexus_om_"
        ) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        doc = await run_in_threadpool(
            extract_order_text, tmp_path, row.attachment_name or "zamowienie.pdf"
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    ident = identify_client(doc.text, registry, sender_email=row.sender_email)
    client_id, policy_key = resolve_client_id(ident)
    row.identification_method = ident.method
    row.identification_reason = ident.reason
    row.client_key = policy_key or (ident.client_key if ident.client_key else None)
    row.client_id = client_id

    extraction = await parse_order_document(doc.text, all_rows=True)
    policies = active_policies(client_id) if client_id is not None else []
    extraction, applied = apply_policies(
        extraction, PolicyContext(document_text=doc.text), policies
    )
    row.client_policy = " + ".join(applied) or None
    row.extraction = extraction_to_json(extraction)
    row.document_meta = document_meta_to_json(doc, extraction)
    row.outcome = (
        OUTCOME_NEEDS_REVIEW if client_id is not None else OUTCOME_UNRECOGNIZED
    )
    if client_id is None:
        return row

    # ── Bramka automatu: resolver → planer → werdykt (zawsze zapisany) ──────
    await _plan_and_gate(db, row, extraction, doc, policies, client_id, ident.method)
    if row.gate_verdict == GATE_AUTO and settings.ORDER_MAIL_AUTOAPPLY_ENABLED:
        from app.services.order_mail_apply import apply_document  # cykl importów

        result = await apply_document(db, row, actor_user_id=None)
        row.outcome = OUTCOME_AUTO_APPLIED if result.ok else OUTCOME_NEEDS_REVIEW
        if not result.ok:
            row.error = (
                result.error or "; ".join(r.error for r in result.rows if r.error)
            )[:2000]
    return row


async def _plan_and_gate(db, row, extraction, doc, policies, client_id, method) -> None:
    """Dopasuj osoby do rostera, zaplanuj zapis, oceń bramką; zapisz na wierszu."""
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract
    from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
    from app.services.multi_consultant_orders import is_multi_consultant_client

    roster = await load_roster(db, client_id)
    resolved = resolve_rows(extraction.consultant_rows, roster)
    contract_ids = {r.contract_id for r in resolved if r.contract_id}
    existing: dict[int, list[ExistingOrder]] = {}
    current_rates: dict[int, tuple[Optional[Decimal], Optional[str]]] = {}
    if contract_ids:
        orders = (
            (
                await db.execute(
                    select(ClientOrder).where(ClientOrder.contract_id.in_(contract_ids))
                )
            )
            .scalars()
            .all()
        )
        for o in orders:
            existing.setdefault(o.contract_id, []).append(
                ExistingOrder(
                    id=o.id,
                    status=o.status.value
                    if hasattr(o.status, "value")
                    else str(o.status),
                    title=o.title or "",
                    start_date=o.start_date,
                    end_date=o.end_date,
                    order_group_id=o.order_group_id,
                    has_file=bool(o.file_path),
                )
            )
        contracts = (
            (
                await db.execute(
                    select(Contract)
                    .options(*RATE_SCHEDULE_LOADS)
                    .where(Contract.id.in_(contract_ids))
                )
            )
            .scalars()
            .all()
        )
        today = datetime.now(timezone.utc).date()
        for c in contracts:
            try:
                eff = effective_rate_fields(c, today)
                raw_unit = eff.get("rate_unit") or c.rate_unit
                unit = raw_unit.value if hasattr(raw_unit, "value") else str(raw_unit)
                unit_key = {"hourly": "hour", "daily": "day", "monthly": "month"}.get(
                    unit, unit
                )
                current_rates[c.id] = (eff.get("rate_client"), unit_key)
            except Exception:  # noqa: BLE001 — stawka bieżąca jest tylko kontrolą
                continue
    proposal = plan_document(
        client_id=client_id,
        extraction=extraction,
        resolved=resolved,
        existing_orders_by_contract=existing,
        is_group_client=is_multi_consultant_client(client_id),
        today=datetime.now(timezone.utc).date(),
    )
    det_rows: list = []
    for policy in policies:
        if policy.extract_rows is not None:
            det_rows = policy.extract_rows(doc.text)
            break
    verdict = evaluate(
        GateInput(
            identification_method=method,
            policies_applied=tuple(p.display_name for p in policies),
            extraction=extraction,
            document_truncated=extraction.document_truncated,
            ocr_capped=doc.ocr_capped,
            resolved=tuple(resolved),
            proposal=proposal,
            deterministic_rows=tuple(det_rows),
            current_rates=current_rates,
            autoapply_enabled=settings.ORDER_MAIL_AUTOAPPLY_ENABLED,
            excluded_client_ids=client_ids_from_env(
                "ORDER_MAIL_AUTOAPPLY_EXCLUDE_CLIENT_IDS"
            ),
        )
    )
    row.gate_verdict = verdict.verdict
    row.gate_reasons = verdict.reasons
    row.proposal = {
        "client_id": proposal.client_id,
        "order_number": proposal.order_number,
        "is_group_client": proposal.is_group_client,
        "blocking": proposal.blocking,
        "rows": [r.__dict__ for r in proposal.rows],
        "resolved": [r.__dict__ for r in resolved],
    }


async def notify_review(db, row) -> int:
    """Alert dla Delivery Leadów klienta (fallback: admini) o zamówieniu do weryfikacji.

    ``dl_alerts``, nie ``notifications``: mierzy kto i kiedy załatwił sprawę,
    powtórka co 7 dni jest nowym wierszem, bez ``ALTER TYPE`` na enumie.
    ``emit`` zwraca ``[]`` przy braku DL — dlatego fallback na adminów jest
    napisany tu wprost, a nie zostawiony przypadkowi.
    """
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole
    from app.services.dl_alerts import emit as emit_dl_alert

    if row.client_id is None or row.id is None:
        return 0
    dl_ids = list(
        (
            await db.execute(
                select(DeliveryLeadClientAssignment.delivery_lead_user_id).where(
                    DeliveryLeadClientAssignment.client_id == row.client_id
                )
            )
        ).scalars()
    )
    if not dl_ids:
        dl_ids = list(
            (
                await db.execute(
                    select(User.id).where(
                        User.role == UserRole.admin, User.is_active.is_(True)
                    )
                )
            ).scalars()
        )
    if not dl_ids:
        return 0
    title = (row.extraction or {}).get("title") or row.attachment_name or "zamówienie"
    created = await emit_dl_alert(
        db,
        alert_type="order_mail_review",
        user_ids=dl_ids,
        client_id=row.client_id,
        entity_key=f"order_mail:{row.id}",
        title=f"Sprawdź zamówienie z maila: {title}",
        message=(
            "Zamówienie z maila wymaga weryfikacji dopasowania: "
            + "; ".join((row.gate_reasons or [])[:3])
        )[:2000],
        link=f"/order-mail?doc={row.id}",
        payload={"document_id": row.id, "outcome": row.outcome},
        repeat_every_days=7,
    )
    return len(created)


async def _process_message(
    db: AsyncSession,
    gc: GraphClient,
    conn: Optional[M365Connection],
    msg: dict[str, Any],
    stats: IngestStats,
    registry: ClientRegistry,
) -> None:
    message_id = msg.get("internetMessageId") or msg.get("id")
    if not message_id:
        return
    stats.messages += 1
    received = _parse_graph_dt(msg.get("receivedDateTime"))
    if received and (stats.max_received_at is None or received > stats.max_received_at):
        stats.max_received_at = received

    _sender, domain = _sender_of(msg)
    if not sender_allowed(domain):
        if await _existing(db, message_id, None) is None:
            row = _base_row(conn, msg)
            row.outcome = OUTCOME_IGNORED_SENDER
            db.add(row)
            await db.commit()
        stats.ignored_sender += 1
        return

    try:
        page = await gc.get(f"{mailbox_prefix()}/messages/{msg['id']}/attachments")
    except Exception as exc:  # noqa: BLE001
        stats.failed += 1
        stats.errors.append(f"attachments {message_id[:40]}: {exc!r}"[:300])
        return
    pdfs = [
        att
        for att in page.get("value", [])
        if att.get("@odata.type") == "#microsoft.graph.fileAttachment"
        and (
            (att.get("name") or "").lower().endswith(".pdf")
            or (att.get("contentType") or "").lower() in _PDF_CONTENT_TYPES
        )
    ]
    if not pdfs:
        if await _existing(db, message_id, None) is None:
            row = _base_row(conn, msg)
            row.outcome = OUTCOME_IGNORED_NO_PDF
            db.add(row)
            await db.commit()
        stats.ignored_no_pdf += 1
        return

    max_bytes = settings.ORDER_MAIL_MAX_ATTACHMENT_MB * 1024 * 1024
    for att in pdfs:
        stats.attachments += 1
        raw_b64 = att.get("contentBytes")
        if not raw_b64:
            stats.failed += 1
            stats.errors.append(f"no contentBytes {message_id[:40]}")
            continue
        payload = base64.b64decode(raw_b64)
        if len(payload) > max_bytes:
            stats.failed += 1
            stats.errors.append(f"too large {att.get('name')!r} ({len(payload)} B)")
            continue
        sha = hashlib.sha256(payload).hexdigest()
        if await _existing(db, message_id, sha) is not None:
            stats.skipped_existing += 1
            continue

        row = _base_row(conn, msg)
        row.attachment_name = (att.get("name") or "zamowienie.pdf")[:255]
        row.attachment_sha256 = sha
        row.attachment_size = len(payload)

        original = await _first_with_sha(db, sha)
        if original is not None:
            row.outcome = OUTCOME_DUPLICATE
            row.duplicate_of_id = original.id
            row.storage_path = original.storage_path
            row.client_id = original.client_id
            row.client_key = original.client_key
            db.add(row)
            await db.commit()
            stats.duplicates += 1
            continue

        try:
            rel, _size = await run_in_threadpool(
                storage_service.save_order_mail_attachment,
                sha,
                row.attachment_name,
                io.BytesIO(payload),
            )
            row.storage_path = rel
            await process_pdf_bytes(db, row, payload, registry=registry)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "order_mail: processing failed for %s", row.attachment_name
            )
            row.outcome = OUTCOME_FAILED
            row.error = repr(exc)[:2000]
            stats.failed += 1
        db.add(row)
        await db.commit()
        if row.outcome == OUTCOME_NEEDS_REVIEW:
            stats.needs_review += 1
            try:
                await notify_review(db, row)
            except Exception:  # noqa: BLE001 — alert nie może wywrócić biegu
                logger.exception("order_mail: notify_review failed for doc %s", row.id)
        elif row.outcome == OUTCOME_UNRECOGNIZED:
            stats.unrecognized += 1


# ── Stan pętli ───────────────────────────────────────────────────────────────


async def read_state(db: AsyncSession) -> Optional[dict[str, Any]]:
    row = await db.execute(
        text(
            "SELECT last_run_started_at, last_run_finished_at, last_status, "
            "last_error, last_seen_received_at, stats FROM order_mail_sync_state WHERE id = 1"
        )
    )
    r = row.fetchone()
    if r is None:
        return None
    return {
        "last_run_started_at": r[0],
        "last_run_finished_at": r[1],
        "last_status": r[2],
        "last_error": r[3],
        "last_seen_received_at": r[4],
        "stats": r[5],
    }


async def _write_state(db: AsyncSession, **fields: Any) -> None:
    """Upsert jednowierszowego stanu. ``stats`` jedzie jako tekst rzutowany na jsonb."""
    if isinstance(fields.get("stats"), dict):
        fields["stats"] = json.dumps(fields["stats"], default=str)
    cols = ", ".join(fields)
    params = ", ".join(
        f"CAST(:{k} AS jsonb)" if k == "stats" else f":{k}" for k in fields
    )
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields)
    await db.execute(
        text(
            f"INSERT INTO order_mail_sync_state (id, {cols}, updated_at) "
            f"VALUES (1, {params}, NOW()) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = NOW()"
        ),
        fields,
    )
    await db.commit()


def compute_since(state: Optional[dict[str, Any]], now: datetime) -> datetime:
    """Od kiedy pytać skrzynkę: watermark minus nakładka; pierwszy bieg = lookback."""
    last_seen = state.get("last_seen_received_at") if state else None
    if last_seen:
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        return last_seen - timedelta(hours=settings.ORDER_MAIL_OVERLAP_HOURS)
    return now - timedelta(days=settings.ORDER_MAIL_INITIAL_LOOKBACK_DAYS)


# ── Bieg ─────────────────────────────────────────────────────────────────────


async def run_order_mail_ingest(
    *, reason: str = "scheduled", since: Optional[datetime] = None
) -> IngestStats:
    """Jeden bieg pobierania. Nie rzuca; wynik i błąd lądują w stanie pętli."""
    stats = IngestStats()
    if _ingest_lock.locked():
        stats.errors.append("already running")
        return stats
    async with _ingest_lock:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            state = await read_state(db)
            await _write_state(
                db, last_run_started_at=now, last_status="running", last_error=None
            )
            conn: Optional[M365Connection] = None
            if auth_mode() == "app":
                if not app_only_ready():
                    await _write_state(
                        db,
                        last_run_finished_at=datetime.now(timezone.utc),
                        last_status="error",
                        last_error=(
                            "app-only reader misconfigured: need ORDER_MAIL_UPN,"
                            " M365_CLIENT_ID, M365_CLIENT_SECRET and a real tenant"
                            " in M365_MAIL_TENANT_ID"
                        ),
                    )
                    stats.errors.append("app_only_misconfigured")
                    return stats
                client_cm = AppGraphClient()
            else:
                conn = await find_orders_connection(db)
                if conn is None:
                    await _write_state(
                        db,
                        last_run_finished_at=datetime.now(timezone.utc),
                        last_status="error",
                        last_error="no active M365 connection for ORDER_MAIL_UPN",
                    )
                    stats.errors.append("no_connection")
                    return stats
                client_cm = GraphClient(conn, db)
            registry = await build_registry_from_db(db)
            effective_since = since or compute_since(state, now)
            logger.info(
                "order_mail ingest start (%s) since=%s mode=%s conn=%s",
                reason,
                effective_since.isoformat(),
                auth_mode(),
                conn.id if conn is not None else None,
            )
            try:
                async with client_cm as gc:
                    params = {
                        "$filter": (
                            f"receivedDateTime ge {effective_since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
                            " and hasAttachments eq true"
                        ),
                        "$select": _MESSAGE_SELECT,
                        "$orderby": "receivedDateTime asc",
                        "$top": "50",
                    }
                    async for page in gc.paginate(
                        f"{mailbox_prefix()}/mailFolders/Inbox/messages", params=params
                    ):
                        for msg in page.get("value", []):
                            await _process_message(db, gc, conn, msg, stats, registry)
                status = "ok" if not stats.failed else "partial"
                await _write_state(
                    db,
                    last_run_finished_at=datetime.now(timezone.utc),
                    last_status=status,
                    last_error=None
                    if status == "ok"
                    else "; ".join(stats.errors[:5])[:2000],
                    last_seen_received_at=stats.max_received_at
                    or (state or {}).get("last_seen_received_at"),
                    stats=stats.as_dict(),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("order_mail ingest failed")
                stats.errors.append(repr(exc)[:300])
                await _write_state(
                    db,
                    last_run_finished_at=datetime.now(timezone.utc),
                    last_status="error",
                    last_error=repr(exc)[:2000],
                    stats=stats.as_dict(),
                )
    logger.info("order_mail ingest done: %s", stats.as_dict())
    return stats
