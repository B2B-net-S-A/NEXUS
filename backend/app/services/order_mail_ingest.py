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
from typing import Any, Awaitable, Callable, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.m365 import M365Connection
from app.models.order_mail import (
    CONNECTION_PURPOSE_ORDERS,
    GATE_AUTO,
    GATE_REVIEW,
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
from app.services.ai_quota import AIQuotaExceeded, ai_feature
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
from app.services.order_mail_gate import (
    CODE_AI_RETRY_EXHAUSTED,
    CODE_AUTOAPPLY_DISABLED,
    CODE_NON_ORDER,
    CODE_UNKNOWN,
    CODE_WRITE_FAILED,
    GateInput,
    evaluate,
)
from app.services.order_mail_planner import ExistingOrder, plan_document
from app.services.order_mail_resolver import (
    MATCH_NONE,
    annotate_known_elsewhere,
    load_people_outside_roster,
    load_roster,
    resolve_rows,
)
from app.services.order_rate_snapshots import (
    contract_rate_in_unit,
    order_unit_for_contract,
)
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    OrderExtraction,
    parse_order_document,
)
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    apply_rate_kind,
    client_ids_from_env,
    is_client_in_policy,
    open_ended_period,
    policy_by_key,
    prepare_document_text,
    prepare_parser_text,
    reapplies_on_refresh,
    rule_versions,
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
#: Activity, które zostawia writer (``order_mail_apply``) na zapisanym zamówieniu.
#: ``order_mail_renewal`` = powrót po przerwie (nowe zamówienie, od 10.09.2026);
#: bez niej draft powrotu bez PDF-u wyglądałby jak pusty szkic do nadpisania.
_MAIL_ORDER_ACTIONS = (
    "order_mail_fill_draft",
    "order_mail_reactivate",
    "order_mail_created",
    "order_mail_new_draft",
    "order_mail_renewal",
)


def ingest_is_running() -> bool:
    return _ingest_lock.locked()


# ── Wyłącznik automatu ───────────────────────────────────────────────────────

#: Powód zatrzymania pewnego planu w kolejce, gdy automat jest wyłączony.
AUTOAPPLY_DISABLED_REASON = (
    "Automatyczny zapis jest wyłączony — plan przeszedł wszystkie kontrole, "
    "sprawdź go i zastosuj ręcznie"
)


def autoapply_enabled() -> bool:
    """Czy werdykt „auto" wolno zapisać bez człowieka (``ORDER_MAIL_AUTOAPPLY_ENABLED``)."""
    return bool(settings.ORDER_MAIL_AUTOAPPLY_ENABLED)


def hold_when_autoapply_disabled(row: OrderMailDocument) -> bool:
    """Wyłącznik automatu — JEDNO miejsce dla każdego zapisu bez człowieka.

    Bramka (``order_mail_gate.evaluate``) zostaje czysta: ocenia dokument, nie
    konfigurację, więc „auto" dalej znaczy „plan jest pewny". O tym, czy pewny
    plan wolno zapisać bez kliknięcia „Zastosuj", decyduje flaga — sprawdzana
    tu przez wszystkie trzy ścieżki writera bez aktora (odczyt maila,
    „Przelicz plan", jednorazowe sprzątanie kolejki). Do 10.09.2026 flaga była
    ignorowana i nie dało się wyłączyć automatu bez deployu.

    Zwraca ``True``, gdy dokument został zatrzymany w kolejce — wołający NIE
    może wtedy uruchomić writera. Ręczne „Zastosuj" (z aktorem) flagi nie czyta.
    """
    if row.gate_verdict != GATE_AUTO or autoapply_enabled():
        return False
    row.gate_verdict = GATE_REVIEW
    set_gate_hold(row, [(CODE_AUTOAPPLY_DISABLED, AUTOAPPLY_DISABLED_REASON)])
    row.outcome = OUTCOME_NEEDS_REVIEW
    return True


# Referencje do biegów uruchomionych „w tle" z requestu. ``asyncio.create_task``
# bez trzymanej referencji to zadanie, które interpreter może zebrać w połowie
# biegu (dokumentacja asyncio mówi o tym wprost) — zebrane zadanie nie zapisuje
# końca i w stanie zostaje ``running`` bez końca. Wzorzec z ``api/cortex.py``.
_bg_tasks: set[asyncio.Task] = set()


def start_ingest_task(*, reason: str, since: Optional[datetime] = None) -> asyncio.Task:
    """Uruchom bieg w tle i trzymaj referencję do zadania do jego końca."""
    task = asyncio.create_task(run_order_mail_ingest(reason=reason, since=since))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


@dataclass
class IngestStats:
    """Liczniki jednego biegu.

    ``messages`` to wszystkie wiadomości z okna zapytania (watermark minus
    nakładka, więc te same wiadomości wracają w kolejnych biegach);
    ``new_messages`` — tylko te, dla których powstał choć jeden wpis
    w dzienniku. Operator pyta o drugą liczbę („ile przyszło nowych"),
    pierwsza jest miarą kosztu Graph.
    """

    reason: str = "scheduled"
    messages: int = 0
    new_messages: int = 0
    attachments: int = 0
    ignored_no_pdf: int = 0
    ignored_sender: int = 0
    duplicates: int = 0
    unrecognized: int = 0
    auto_applied: int = 0
    needs_review: int = 0
    skipped_existing: int = 0
    failed: int = 0
    #: Godzinowa ponowna weryfikacja wstrzymanych wpisów
    #: (``order_mail_recheck.run_recheck``): ile obejrzano, ile zapisało się
    #: automatem, ile dalej czeka i ile wysłało kartę do Delivery Leada.
    rechecked: int = 0
    recheck_applied: int = 0
    recheck_held: int = 0
    recheck_alerts: int = 0
    #: Wpisy z odczytem awaryjnym (bez AI), dla których ponowiono odczyt AI
    #: (``retry_ai_fallback_documents``): ile prób, ile się udało, ile z nich
    #: zapisało się automatem.
    ai_retried: int = 0
    ai_recovered: int = 0
    ai_recovered_auto_applied: int = 0
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


#: Ile razy wolno pójść za ``merged_into_client_id``. Endpoint scalania nie
#: pozwala wskazać celu, który sam jest scalony, więc realne łańcuchy mają
#: długość 1 — limit jest tylko bezpiecznikiem na dane spoza API.
_MERGE_CHAIN_LIMIT = 5


async def _canonical_client_ids(
    db: AsyncSession, ids: set[int]
) -> dict[int, Optional[int]]:
    """ID → klient KANONICZNY (koniec łańcucha ``merged_into_client_id``).

    ``None`` = łańcuch się nie kończy (cykl albo dłuższy niż limit) — wtedy
    wolimy „nie rozpoznano klienta" niż zgadywanie.
    """
    pointers: dict[int, Optional[int]] = {}
    frontier = set(ids)
    for _ in range(_MERGE_CHAIN_LIMIT):
        missing = frontier - pointers.keys()
        if not missing:
            break
        rows = await db.execute(
            select(Client.id, Client.merged_into_client_id).where(
                Client.id.in_(missing)
            )
        )
        for client_id, target in rows.all():
            pointers[client_id] = target
        frontier = {t for t in pointers.values() if t is not None}

    def follow(client_id: int) -> Optional[int]:
        seen: set[int] = set()
        while client_id not in seen:
            seen.add(client_id)
            if client_id not in pointers:
                return None
            target = pointers[client_id]
            if target is None:
                return client_id
            client_id = target
        return None

    return {client_id: follow(client_id) for client_id in ids}


async def build_registry_from_db(db: AsyncSession) -> ClientRegistry:
    """NIP-y z ``clients.nip`` → klucz = ``client_id`` jako tekst; markery/domeny z kodu.

    Klucze markerów to klucze POLITYK (``cardif``, ``pfron``…), rozwiązywane
    do ``client_id`` przez env tej polityki (``resolve_client_id``). Jeden
    mechanizm bramkowania — żadnej drugiej listy ID do utrzymania.

    Numer prowadzi do klienta KANONICZNEGO: scalenie duplikatu nie przepisuje
    danych, więc NIP zostaje na scalonym wierszu (``merged_into_client_id``).
    Bez pójścia za tym wskazaniem dokument dalej lądowałby na pustym duplikacie
    — z pustym rosterem i każdą osobą jako „nowy kontraktor" — czyli scalenie
    klienta nie naprawiałoby poczty zamówień wcale.

    Ten sam numer na DWÓCH różnych klientach kanonicznych to niejednoznaczność:
    wypada z rejestru, żeby dokument trafił do kolejki zamiast do rekordu
    wybranego kolejnością wierszy.
    """
    rows = await db.execute(select(Client.id, Client.nip).where(Client.nip.isnot(None)))
    with_nip = [
        (client_id, norm)
        for client_id, nip in rows.all()
        if (norm := normalize_registry_id(nip or ""))
    ]
    canonical = await _canonical_client_ids(db, {cid for cid, _ in with_nip})
    by_registry: dict[str, set[int]] = {}
    for client_id, norm in with_nip:
        target = canonical.get(client_id)
        if target is not None:
            by_registry.setdefault(norm, set()).add(target)
    return ClientRegistry(
        by_registry_id={
            norm: str(next(iter(targets)))
            for norm, targets in by_registry.items()
            if len(targets) == 1
        },
        markers=KNOWN_MARKERS,
        sender_domains=KNOWN_SENDER_DOMAINS,
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


async def resolve_order_client_id(
    db: AsyncSession, ident: ClientIdentification
) -> tuple[Optional[int], Optional[str]]:
    """PFRON: jeden aktywny rekord z jawnej puli polityki, także przy starym env.

    Kategoria katalogu (z ręcznym nadpisaniem) jest niezależna od statusu
    Traffita. Nie rozszerzamy dopasowania na podobne nazwy innych klientów.
    """
    client_id, key = resolve_client_id(ident)
    if key != "pfron" and not is_client_in_policy("pfron", client_id):
        return client_id, key
    policy = policy_by_key("pfron")
    ids = policy.canonical_client_ids | client_ids_from_env(policy.env_var)
    active_scope = (
        select(ClientPortfolioScope.id)
        .where(
            ClientPortfolioScope.client_id == Client.id,
            ClientPortfolioScope.archived_at.is_(None),
            func.coalesce(
                ClientPortfolioScope.category_override, ClientPortfolioScope.category
            )
            == PortfolioCategory.active,
        )
        .exists()
    )
    active_ids = (
        (
            await db.execute(
                select(Client.id).where(
                    Client.id.in_(ids),
                    Client.hidden.is_(False),
                    Client.archived_at.is_(None),
                    Client.merged_into_client_id.is_(None),
                    active_scope,
                )
            )
        )
        .scalars()
        .all()
    )
    return (active_ids[0] if len(active_ids) == 1 else None), "pfron"


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


def _stamp_rule_versions(row: OrderMailDocument, policies: list) -> None:
    """Zapamiętaj, którymi wersjami reguł klienta przeczytano dokument.

    Nowy słownik zamiast mutacji: kolumna JSON nie śledzi zmian w miejscu.
    """
    row.document_meta = {
        **(row.document_meta or {}),
        "rule_versions": rule_versions(policies),
    }


#: Klucze ``document_meta`` prowadzone przez ponowny odczyt AI — przeżywają
#: „Przelicz plan", który przepisuje resztę metadanych dokumentu od zera.
_AI_RETRY_META_KEYS = (
    "ai_retry_attempts",
    "ai_retry_last_at",
    "ai_retry_last_failure",
    "ai_recovered_at",
    # 0312: ślad godzinowej ponownej weryfikacji `{attempts, category, last_at}`.
    # „Przelicz plan" nie może go kasować — inaczej licznik „trzech prób
    # z rzędu" zerowałby się przy każdym przeliczeniu i karta dla Delivery
    # Leada nigdy by nie wyszła.
    "recheck",
)


def _ai_retry_meta(meta: Optional[dict[str, Any]]) -> dict[str, Any]:
    return {k: v for k, v in (meta or {}).items() if k in _AI_RETRY_META_KEYS}


def gate_hold_pairs(row: OrderMailDocument) -> list[tuple[str, str]]:
    """Zapisane powody sparowane z kodami, odporne na wpisy sprzed 0312.

    Wiersz sprzed wdrożenia ma ``gate_reasons`` bez ``gate_reason_codes``; gołe
    ``zip`` zgubiłoby wtedy WSZYSTKIE powody, bo krótsza lista ucina parowanie.
    """
    reasons = row.gate_reasons or []
    codes = row.gate_reason_codes or []
    return [
        (codes[i] if i < len(codes) and codes[i] else CODE_UNKNOWN, text)
        for i, text in enumerate(reasons)
    ]


def set_gate_hold(row: OrderMailDocument, pairs: list[tuple[str, str]]) -> None:
    """Zapisz powody wstrzymania RAZEM z ich kodami — jedno miejsce dla obu pól.

    Kilka ścieżek nadpisuje ``gate_reasons`` poza bramką (wyłącznik automatu,
    nieudany zapis writera, wyczerpany ponowny odczyt AI). Gdyby któraś z nich
    zapomniała o kodach, godzinowa ponowna weryfikacja czytałaby pustą listę
    i zakwalifikowała dokument jako „inny powód" — czyli zaczęłaby alarmować
    Delivery Leada o czymś, co sama wyłączyła.
    """
    row.gate_reasons = [text for _, text in pairs]
    row.gate_reason_codes = [code for code, _ in pairs]


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
    client_id, policy_key = await resolve_order_client_id(db, ident)
    row.identification_method = ident.method
    row.identification_reason = ident.reason
    row.client_key = policy_key or (ident.client_key if ident.client_key else None)
    row.client_id = client_id

    policies = active_policies(client_id) if client_id is not None else []
    if any(p.key == "nordea" for p in policies):
        from app.services.order_policies.nordea import non_order_reason

        reason = non_order_reason(doc.text)
        if reason:
            row.outcome = "dismissed"
            row.client_policy = "Nordea"
            row.extraction = None
            row.proposal = None
            row.gate_verdict = None
            set_gate_hold(row, [(CODE_NON_ORDER, reason)])
            row.document_meta = {"ignored_non_order": True, "reason": reason}
            return row
    doc = dataclasses.replace(doc, text=prepare_document_text(doc.text, policies))
    extraction = await read_order_with_model(
        db, prepare_parser_text(doc.text, policies), fallback_when_blocked=True
    )
    extraction, applied = apply_policies(
        extraction,
        PolicyContext(document_text=doc.text, filename=row.attachment_name),
        policies,
    )
    extraction = apply_rate_kind(extraction, doc.text, policies)
    row.client_policy = " + ".join(applied) or None
    row.extraction = extraction_to_json(extraction)
    row.document_meta = document_meta_to_json(doc, extraction)
    _stamp_rule_versions(row, policies)
    row.outcome = (
        OUTCOME_NEEDS_REVIEW if client_id is not None else OUTCOME_UNRECOGNIZED
    )
    if client_id is None:
        return row

    # ── Bramka automatu: resolver → planer → werdykt (zawsze zapisany) ──────
    await _plan_and_gate(db, row, extraction, doc, policies, client_id, ident.method)
    if hold_when_autoapply_disabled(row):
        return row
    if row.gate_verdict == GATE_AUTO:
        from app.services.order_mail_apply import apply_document  # cykl importów

        db.add(row)
        await db.flush()
        result = await apply_document(db, row, actor_user_id=None)
        row.outcome = OUTCOME_AUTO_APPLIED if result.ok else OUTCOME_NEEDS_REVIEW
        if not result.ok:
            row.gate_verdict = "review"
            set_gate_hold(
                row,
                [
                    (
                        CODE_WRITE_FAILED,
                        "Nie udało się zapisać zamówienia: "
                        + (
                            result.error
                            or "; ".join(r.error for r in result.rows if r.error)
                        ),
                    )
                ],
            )
            row.error = (
                result.error or "; ".join(r.error for r in result.rows if r.error)
            )[:2000]
    return row


def restore_extraction(data):
    def restore(cls, data):
        values = {
            f.name: data[f.name] for f in dataclasses.fields(cls) if f.name in data
        }
        for key in (
            "rate_client",
            "rate_client_gross",
            "rate_client_md",
            "md_total",
            "total_value",
        ):
            if values.get(key) is not None:
                values[key] = Decimal(str(values[key]))
        return cls(**values)

    extraction = restore(OrderExtraction, data or {})
    extraction.consultant_rows = [
        restore(ConsultantOrderRow, value)
        for value in (data or {}).get("consultant_rows", [])
    ]
    if (data or {}).get("model_rows") is not None:
        extraction.model_rows = [
            restore(ConsultantOrderRow, value) for value in data["model_rows"]
        ]
    return extraction


async def _follow_client_merge(db: AsyncSession, row: OrderMailDocument) -> None:
    """Dokument przypięty do scalonego duplikatu przechodzi na klienta kanonicznego.

    Scalenie („Scal z…") jest stwierdzeniem, że oba wiersze to TEN SAM klient.
    Dokument nie może zostać przy duplikacie: jego roster bywa pusty, a wtedy
    KAŻDA osoba z maila wygląda na nowego kontraktora. Bez tego kroku scalenie
    naprawiałoby wyłącznie maile przychodzące PO nim — a dokument, który już
    czeka w kolejce, zostałby ze starym rekordem na zawsze (poprawka musi
    dosięgnąć kolejki, nie tylko nowych wiadomości).

    Ruch jest jednokierunkowy i bez zgadywania: idziemy wyłącznie za jawnym
    ``merged_into_client_id``, nigdy za podobieństwem nazwy.
    """
    if not row.client_id:
        return
    canonical = (await _canonical_client_ids(db, {row.client_id})).get(row.client_id)
    if canonical is None or canonical == row.client_id:
        return
    previous = row.client_id
    row.client_id = canonical
    row.identification_reason = " ".join(
        filter(
            None,
            (
                (row.identification_reason or "").strip(),
                f"Rekord klienta #{previous} został scalony — dokument "
                f"przeniesiony na klienta #{canonical}.",
            ),
        )
    )
    logger.info(
        "order_mail: document id=%s moved from merged client %s to %s",
        row.id,
        previous,
        canonical,
    )


async def refresh_review_plan(db: AsyncSession, row: OrderMailDocument) -> None:
    """Przelicz utrwalony odczyt z PDF-em i bieżącym rosterem, bez writera.

    PFRON ponownie rozpoznaje aktywnego klienta i pola ze źródłowego PDF-a.
    Klienci, u których tabela PDF-a jest źródłem prawdy (Nordea, Alior), mają
    regułę zastosowaną ponownie na zapisanym odczycie. Pozostali zachowują numer
    i okres. Bez modelu; zapis rozstrzyga wywołujący na podstawie werdyktu.

    Rozpoznany klient jest zachowywany, ale scalony duplikat NIE jest klientem —
    dokument przechodzi wtedy na rekord kanoniczny (``_follow_client_merge``);
    PFRON tego kroku nie potrzebuje, bo rozpoznaje klienta od nowa.
    """

    extraction = restore_extraction(row.extraction)
    path = storage_service.get_order_mail_attachment_path(row.storage_path)
    doc = await run_in_threadpool(
        extract_order_text, str(path), row.attachment_name or "zamowienie.pdf"
    )
    if getattr(row, "client_key", None) == "pfron" or is_client_in_policy(
        "pfron", row.client_id
    ):
        registry = await build_registry_from_db(db)
        ident = identify_client(
            doc.text, registry, sender_email=getattr(row, "sender_email", None)
        )
        client_id, key = await resolve_order_client_id(db, ident)
        if key != "pfron" or client_id is None:
            raise ValueError("Nie rozpoznano jednoznacznie aktywnego klienta PFRON")
        row.client_id = client_id
        row.client_key = key
        row.identification_method = ident.method
        row.identification_reason = ident.reason
        extraction, applied = apply_policies(
            extraction,
            PolicyContext(document_text=doc.text, filename=row.attachment_name),
            active_policies(client_id),
        )
        row.client_policy = " + ".join(applied) or None
    else:
        # Poza PFRON-em zachowujemy rozpoznanego klienta — ale scalony duplikat
        # nie jest klientem. Krok musi wyprzedzić dobór polityk i rostera, bo od
        # rekordu zależy cała reszta przeliczenia. (PFRON rozpoznaje klienta od
        # nowa wyżej, więc nie ma tam czego przenosić.)
        await _follow_client_merge(db, row)
    policies = active_policies(row.client_id)
    doc = dataclasses.replace(doc, text=prepare_document_text(doc.text, policies))
    if reapplies_on_refresh(policies):
        # Tabela z PDF-a jest źródłem prawdy (Nordea, Alior): reguła klienta
        # działa ponownie na zapisanym odczycie, bez modelu. Dokument sprzed
        # poprawki reguły nie może zostać w kolejce z jej starymi powodami.
        extraction, applied = apply_policies(
            extraction,
            PolicyContext(
                document_text=doc.text, filename=row.attachment_name, reapplied=True
            ),
            policies,
        )
        row.client_policy = " + ".join(applied) or None
    if any(p.key == "nordea" for p in policies):
        # Stary model mógł dodać osoby z summary. Przeliczenie korzysta z
        # właściwej tabeli PDF-a, zachowując zaakceptowany numer i okres.
        extraction.consultant_rows = policy_by_key("nordea").extract_rows(doc.text)
    extraction = apply_rate_kind(extraction, doc.text, policies)
    row.extraction = extraction_to_json(extraction)
    row.document_meta = {
        **_ai_retry_meta(getattr(row, "document_meta", None)),
        **document_meta_to_json(doc, extraction),
    }
    _stamp_rule_versions(row, policies)
    await _plan_and_gate(
        db,
        row,
        extraction,
        doc,
        policies,
        row.client_id,
        row.identification_method,
    )
    row.error = None


async def replan_and_apply(
    db: AsyncSession,
    row: OrderMailDocument,
    *,
    actor_user_id: Optional[int],
    before_apply: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    """„Przelicz plan": nowy plan z zapisanego odczytu, a pewny plan — zapis.

    Jedno miejsce dla przycisku w kolejce i dla przeliczenia po zmianie reguły
    klienta (``order_mail_recheck``). Zapis pewnego planu jest tu
    AUTOMATYCZNY (nikt nie kliknął „Zastosuj"), więc słucha wyłącznika automatu
    i nie zdejmuje blokad zarezerwowanych dla zatwierdzenia (imiennik z bazy,
    dopasowanie niedokładne). ``actor_user_id`` służy wyłącznie atrybucji;
    ``before_apply`` pozwala sprawdzić uprawnienia do rekordu PO przeliczeniu
    (PFRON może zmienić klienta), a przed zapisem. Nie commituje.
    """
    await refresh_review_plan(db, row)
    if before_apply is not None:
        await before_apply()
    if hold_when_autoapply_disabled(row) or row.gate_verdict != GATE_AUTO:
        return
    from app.services.order_mail_apply import apply_document  # cykl importów

    result = await apply_document(
        db, row, actor_user_id=actor_user_id, confirmed_by_human=False
    )
    if result.ok:
        row.outcome = OUTCOME_AUTO_APPLIED
        return
    error = result.error or "; ".join(r.error for r in result.rows if r.error)
    row.gate_verdict = GATE_REVIEW
    row.error = error[:2000]
    set_gate_hold(
        row, [(CODE_WRITE_FAILED, "Nie udało się zapisać zamówienia: " + error)]
    )


def _replannable(row: OrderMailDocument) -> bool:
    """Te same warunki co przycisk „Przelicz plan" w kolejce.

    Brak pliku to ODPOWIEDŹ „nie da się przeliczyć", nie awaria: helper
    magazynu RZUCA ``FileNotFoundError`` dla ścieżki, której nie ma (plik
    znika przy retencji, przeniesieniu wolumenu, ręcznym sprzątaniu).
    Bez tego przechwycenia godzinowa ponowna weryfikacja wywracała się na
    takim wpisie w KAŻDYM biegu, licznik prób nigdy nie ruszał z miejsca,
    a karta dla Delivery Leada nie wychodziła nigdy.
    """
    if not row.client_id or not row.extraction or not row.storage_path:
        return False
    if row.applied_order_id or ((row.proposal or {}).get("apply_result") or {}).get(
        "rows"
    ):
        return False
    try:
        path = storage_service.get_order_mail_attachment_path(row.storage_path)
    except (FileNotFoundError, ValueError):
        return False
    return path.is_file()


#: Ile razy ponawiamy odczyt AI dla jednego wpisu z odczytem awaryjnym. Bieg
#: skrzynki jest co godzinę, więc to kilka godzin na przejściową awarię
#: dostawcy albo restart kontenera w trakcie odczytu — trwale nieczytelny
#: dokument nie może płacić za model w każdym biegu.
MAX_AI_RETRY_ATTEMPTS = 3


def ai_extraction_available() -> bool:
    """Czy odczyt AI w ogóle może się udać (klucz DOSTAWCY + włącznik funkcji).

    Klucz musi dotyczyć dostawcy modelu z rejestru (od 16.09.2026 odczyt
    zamówień idzie na GPT Luna), a nie Anthropic na sztywno. Ta funkcja
    decyduje, czy otworzyć bramkę kwot — pytanie o cudzy klucz kończyło się
    wywołaniem modelu POZA kwotą: niewidocznym dla wyłącznika, limitu i alarmu
    wydatków (pod `AI_QUOTA_STRICT` wprost `AIQuotaUngated`).
    """
    from app.services.ai_models import model_for
    from app.services.llm_providers import api_key_configured

    return bool(api_key_configured(model_for(AIFeatureKey.order_parser))) and bool(
        settings.ORDER_EXTRACTION_ENABLED
    )


def _quota_block_reason(exc: AIQuotaExceeded) -> str:
    return f"odczyt AI zablokowany w ustawieniach AI ({exc.reason})"


async def read_order_with_model(
    db: AsyncSession,
    parser_text: str,
    *,
    fallback_when_blocked: bool,
    release_connection: bool = False,
) -> OrderExtraction:
    """Odczyt all-rows modelem pod kwotą ``order_parser`` (aktor: system).

    Do 09.2026 poczta zamówień wołała model POZA bramką: każde wywołanie było
    „UNGATED”, nie trafiało do ``ai_operations``/``ai_provider_calls``, więc nie
    widziały go ani wyłącznik funkcji w Ustawieniach → AI, ani limit, ani alarm
    wydatków — telemetria pokazywała wyłącznie ręczne odczyty z formularzy.

    Operacja powstaje tylko wtedy, gdy model może ruszyć (klucz i
    ``ORDER_EXTRACTION_ENABLED``); bez tego parser od razu daje odczyt awaryjny
    z własnym powodem, jak dotąd, i nic nie nalicza.

    Odmowa kwoty (wyłączona funkcja, limit) NIE zatrzymuje poczty: przy
    ``fallback_when_blocked`` dokument dostaje odczyt awaryjny z powodem
    widocznym w kolejce, a ponowienie odczytu AI spróbuje, gdy kwota pozwoli.
    Bez tej flagi wyjątek leci do wołającego (ponowienie nie zużywa wtedy próby).

    ``release_connection`` oddaje połączenie po przyjęciu operacji — ponowienie
    w tle nie może trzymać transakcji przez minuty odpowiedzi modelu.
    """
    if not ai_extraction_available():
        return await parse_order_document(parser_text, all_rows=True)
    try:
        async with ai_feature(db, AIFeatureKey.order_parser):
            if release_connection:
                await db.commit()
            return await parse_order_document(parser_text, all_rows=True)
    except AIQuotaExceeded as exc:
        if not fallback_when_blocked:
            raise
        logger.warning("order_mail: odczyt AI zablokowany przez kwotę: %s", exc)
        return await parse_order_document(
            parser_text, all_rows=True, ai_blocked_reason=_quota_block_reason(exc)
        )


def _needs_ai_retry(row: Optional[OrderMailDocument]) -> bool:
    if row is None or row.outcome != OUTCOME_NEEDS_REVIEW or not row.client_id:
        return False
    if (row.extraction or {}).get("source") != "regex":
        return False
    attempts = int((row.document_meta or {}).get("ai_retry_attempts") or 0)
    return attempts < MAX_AI_RETRY_ATTEMPTS and _replannable(row)


async def _reread_document_text(row: OrderMailDocument) -> OrderDocumentText:
    path = storage_service.get_order_mail_attachment_path(row.storage_path)
    return await run_in_threadpool(
        extract_order_text, str(path), row.attachment_name or "zamowienie.pdf"
    )


async def retry_ai_fallback_documents(db: AsyncSession, stats: IngestStats) -> None:
    """Ponów odczyt AI dla wpisów w kolejce, które dostały odczyt awaryjny.

    Odczyt awaryjny (bez AI) nigdy nie zapisuje się automatem, a jego pola są
    zgadywane — do 09.2026 taki wpis czekał na człowieka, choć przyczyną była
    zwykle chwilowa awaria: przeciążenie dostawcy albo restart kontenera przy
    deployu w chwili odczytu maila (PKO BP, 14.09). Każdy bieg skrzynki próbuje
    ponownie, najwyżej ``MAX_AI_RETRY_ATTEMPTS`` razy na wpis. Udany odczyt
    przechodzi dokładnie tę ścieżkę co nowy mail: reguły klienta, rodzaj stawki,
    plan i bramka — pewny plan zapisuje się automatem (gdy automat włączony).
    Nieudana próba zapisuje powód na wpisie, więc widać go w kolejce.

    Wywołanie modelu idzie POZA blokadą wiersza (trwa do minut); zapis
    sprawdza warunki ponownie pod ``FOR UPDATE``. Każdy wpis to osobna
    transakcja.
    """
    if not ai_extraction_available():
        return
    ids = list(
        (
            await db.scalars(
                select(OrderMailDocument.id)
                .where(
                    OrderMailDocument.outcome == OUTCOME_NEEDS_REVIEW,
                    OrderMailDocument.client_id.is_not(None),
                    OrderMailDocument.applied_order_id.is_(None),
                )
                .order_by(OrderMailDocument.id)
            )
        ).all()
    )
    for doc_id in ids:
        row = await db.get(OrderMailDocument, doc_id)
        if not _needs_ai_retry(row):
            continue
        extraction_before = row.extraction
        policies = active_policies(row.client_id)
        await db.commit()  # oddaj połączenie na czas wywołania modelu
        try:
            doc = await _reread_document_text(row)
            doc = dataclasses.replace(
                doc, text=prepare_document_text(doc.text, policies)
            )
            parsed = await read_order_with_model(
                db,
                prepare_parser_text(doc.text, policies),
                fallback_when_blocked=False,
                release_connection=True,
            )
        except AIQuotaExceeded as exc:
            # Kwota to decyzja administratora, nie awaria dokumentu: próba nie
            # zużywa limitu ponowień, a pozostałe wpisy poczekają na bieg, w
            # którym kwota znów pozwoli (ta sama funkcja zablokuje każdy z nich).
            logger.warning(
                "order_mail: ponowienie odczytu AI wstrzymane przez kwotę: %s", exc
            )
            await db.rollback()
            break
        except Exception as exc:  # noqa: BLE001 — jeden wpis nie wywraca biegu
            logger.exception("order_mail: AI re-read failed for doc %s", doc_id)
            parsed = None
            failure = f"błąd ponownego odczytu ({type(exc).__name__})"
        else:
            failure = parsed.ai_failure if parsed.source != "claude" else None

        row = await db.get(
            OrderMailDocument, doc_id, with_for_update=True, populate_existing=True
        )
        if not _needs_ai_retry(row) or row.extraction != extraction_before:
            await db.commit()  # ktoś zdążył wpis zastosować, odrzucić albo przeliczyć
            continue
        stats.ai_retried += 1
        attempts = int((row.document_meta or {}).get("ai_retry_attempts") or 0) + 1
        now = datetime.now(timezone.utc).isoformat()
        try:
            if parsed is None or parsed.source != "claude":
                await _record_failed_ai_retry(db, row, attempts, now, failure)
            else:
                await _apply_recovered_ai_read(
                    db, row, parsed, doc, policies, attempts, now
                )
                stats.ai_recovered += 1
                if row.outcome == OUTCOME_AUTO_APPLIED:
                    stats.ai_recovered_auto_applied += 1
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — jeden wpis nie wywraca biegu
            logger.exception("order_mail: AI re-read apply failed for doc %s", doc_id)
            await db.rollback()
            row = await db.get(OrderMailDocument, doc_id, with_for_update=True)
            row.document_meta = {
                **(row.document_meta or {}),
                "ai_retry_attempts": attempts,
                "ai_retry_last_at": now,
                "ai_retry_last_failure": f"błąd zapisu ({type(exc).__name__})",
            }
            await db.commit()
            stats.errors.append(f"ai retry doc {doc_id}: {exc!r}"[:300])


async def _record_failed_ai_retry(
    db: AsyncSession,
    row: OrderMailDocument,
    attempts: int,
    now: str,
    failure: Optional[str],
) -> None:
    """Nieudana próba: powód na odczycie i w metadanych, plan przeliczony bez AI."""
    stored = restore_extraction(row.extraction)
    stored.ai_failure = failure or stored.ai_failure
    row.extraction = extraction_to_json(stored)
    row.document_meta = {
        **(row.document_meta or {}),
        "ai_retry_attempts": attempts,
        "ai_retry_last_at": now,
        "ai_retry_last_failure": failure,
    }
    await refresh_review_plan(db, row)
    if attempts >= MAX_AI_RETRY_ATTEMPTS:
        set_gate_hold(
            row,
            [
                *gate_hold_pairs(row),
                (
                    CODE_AI_RETRY_EXHAUSTED,
                    f"Ponowny odczyt AI nie powiódł się {attempts}× — sprawdź pola "
                    "z PDF i zastosuj ręcznie albo odrzuć",
                ),
            ],
        )


async def _apply_recovered_ai_read(
    db: AsyncSession,
    row: OrderMailDocument,
    extraction: OrderExtraction,
    doc: OrderDocumentText,
    policies: list,
    attempts: int,
    now: str,
) -> None:
    """Udany odczyt AI: ta sama ścieżka co nowy mail, potem plan i ewentualny zapis."""
    extraction, applied = apply_policies(
        extraction,
        PolicyContext(document_text=doc.text, filename=row.attachment_name),
        policies,
    )
    extraction = apply_rate_kind(extraction, doc.text, policies)
    row.client_policy = " + ".join(applied) or None
    row.extraction = extraction_to_json(extraction)
    row.document_meta = {
        **(row.document_meta or {}),
        **document_meta_to_json(doc, extraction),
        "ai_retry_attempts": attempts,
        "ai_retry_last_at": now,
        "ai_retry_last_failure": None,
        "ai_recovered_at": now,
    }
    _stamp_rule_versions(row, policies)
    await replan_and_apply(db, row, actor_user_id=None)


async def current_proposal(db, extraction, client_id):
    from app.services.order_types import suggested_order_type
    from app.models.activity import Activity
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract
    from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
    from app.services.multi_consultant_orders import is_multi_consultant_client

    roster = await load_roster(db, client_id)
    resolved = resolve_rows(extraction.consultant_rows, roster)
    # Brak w rosterze != nowa osoba. Zanim plan zaproponuje nowego kontraktora,
    # sprawdź, czy ktoś o dokładnie tym imieniu i nazwisku nie jest już w bazie
    # (np. u drugiego, zdublowanego rekordu tego samego klienta).
    unmatched = [r.row_name for r in resolved if r.match_kind == MATCH_NONE]
    if unmatched:
        resolved = annotate_known_elsewhere(
            resolved,
            await load_people_outside_roster(db, client_id=client_id, names=unmatched),
        )
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
        # Zamówienia zapisane już z maila (writer zostawia Activity
        # ``order_mail_*``): ich szkic niesie tamten PDF i nie może zostać
        # nadpisany kolejnym dokumentem tej samej osoby.
        mail_order_ids = (
            set(
                (
                    await db.execute(
                        select(Activity.entity_id).where(
                            Activity.entity_type == "client_order",
                            Activity.entity_id.in_([o.id for o in orders]),
                            Activity.action.in_(_MAIL_ORDER_ACTIONS),
                        )
                    )
                ).scalars()
            )
            if orders
            else set()
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
                    rate_client=o.rate_client,
                    rate_unit=o.rate_unit.value
                    if hasattr(o.rate_unit, "value")
                    else o.rate_unit,
                    from_order_mail=o.id in mail_order_ids,
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
                # Kontrakt przeliczony z MD jest w zł/h, a zamówienia tej osoby
                # w MD — bramka porównuje stawki tylko w tej samej jednostce, więc
                # stawka bieżąca idzie w jednostce zamówień (ticket 14.09.2026).
                order_unit = order_unit_for_contract(c)
                unit_key = {"hourly": "hour", "daily": "day", "monthly": "month"}[
                    order_unit.value
                ]
                current_rates[c.id] = (
                    contract_rate_in_unit(eff.get("rate_client"), c, order_unit),
                    unit_key,
                )
            except Exception:  # noqa: BLE001 — stawka bieżąca jest tylko kontrolą
                continue
    proposal = plan_document(
        client_id=client_id,
        extraction=extraction,
        resolved=resolved,
        existing_orders_by_contract=existing,
        is_group_client=is_multi_consultant_client(client_id),
        today=datetime.now(timezone.utc).date(),
        order_type=(await suggested_order_type(db, client_id)).value,
    )
    return proposal, resolved, current_rates


async def _plan_and_gate(db, row, extraction, doc, policies, client_id, method) -> None:
    """Dopasuj osoby do rostera, zaplanuj zapis, oceń bramką; zapisz na wierszu."""
    proposal, resolved, current_rates = await current_proposal(
        db, extraction, client_id
    )
    det_rows: list = []
    for policy in policies:
        if policy.extract_rows is not None:
            det_rows = policy.extract_rows(doc.text)
            break
    verdict = evaluate(
        GateInput(
            identification_method=method,
            trusted_policy_identity=(
                "pfron" if is_client_in_policy("pfron", client_id) else None
            ),
            open_ended_period=open_ended_period(policies),
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
    row.gate_reason_codes = verdict.codes
    row.proposal = {
        "client_id": proposal.client_id,
        "order_number": proposal.order_number,
        "is_group_client": proposal.is_group_client,
        "blocking": proposal.blocking,
        "rows": [r.__dict__ for r in proposal.rows],
        "resolved": [r.__dict__ for r in resolved],
    }


def _mail_candidate_names(row) -> list[str]:
    """Imiona i nazwiska osób z odczytu dokumentu (bez duplikatów, w kolejności)."""
    extraction = row.extraction or {}
    names: list[str] = []
    candidates = [extraction.get("consultant_name")]
    for item in extraction.get("consultant_rows") or []:
        if isinstance(item, dict):
            candidates.append(item.get("consultant_name"))
    for raw in candidates:
        name = " ".join(str(raw).split()) if raw else ""
        if name and name not in names:
            names.append(name)
    return names


async def notify_review(
    db,
    row,
    *,
    recipient_scope=None,
    live_event_keys: Optional[set[str]] = None,
) -> int:
    """Karta „Zamówienie do [klient] czeka na weryfikację" w panelu „Moi klienci".

    Odbiorcy: Delivery Leadzi klienta z rolą i dostępem do sekcji Delivery
    (``dl_user_ids_for_client`` — do 09.2026 surowe przypisania, bez sprawdzenia
    roli), a gdy klient nie ma DL — aktywni admini, żeby sprawa nie przepadła.

    ``dl_alerts``, nie ``notifications``: mierzy kto i kiedy załatwił sprawę,
    powtórka co 7 dni jest nowym wierszem (ponawia ją dobowy skaner,
    ``rule_order_mail_review``). ``live_event_keys`` wypełnia skaner, żeby
    zamknąć karty dokumentów, które opuściły kolejkę.
    """
    from app.models.client import Client
    from app.models.user import User, UserRole
    from app.services.client_identity import client_display_name_expression
    from app.services.dl_alerts import dl_user_ids_for_client, event_key_for
    from app.services.dl_alerts import emit as emit_dl_alert

    if row.client_id is None or row.id is None:
        return 0
    dl_ids = await dl_user_ids_for_client(db, row.client_id, scope=recipient_scope)
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
    entity_key = f"order_mail:{row.id}"
    if live_event_keys is not None:
        live_event_keys.update(
            event_key_for("order_mail_review", entity_key, uid) for uid in dl_ids
        )
    client_name = (
        await db.scalar(
            select(client_display_name_expression()).where(Client.id == row.client_id)
        )
    ) or "klienta"
    people = _mail_candidate_names(row)
    received = row.received_at.date().isoformat() if row.received_at else None
    if people:
        who = ", ".join(people[:3]) + (
            f" i {len(people) - 3} innych" if len(people) > 3 else ""
        )
        message = (
            f"Zamówienie dla {who} do {client_name} czeka na ręczną weryfikację "
            "w zakładce Zamówienia z maila."
        )
    else:
        message = (
            f"Zamówienie do {client_name} czeka na ręczną weryfikację "
            "w zakładce Zamówienia z maila."
        )
    reasons = "; ".join((row.gate_reasons or [])[:3])
    if reasons:
        message = f"{message} Powód: {reasons}"
    title = (row.extraction or {}).get("title") or row.attachment_name or "zamówienie"
    created = await emit_dl_alert(
        db,
        alert_type="order_mail_review",
        user_ids=dl_ids,
        client_id=row.client_id,
        entity_key=entity_key,
        title=f"Sprawdź zamówienie z maila: {title}"[:255],
        message=message[:2000],
        link=f"/order-mail?doc={row.id}",
        payload={
            "document_id": row.id,
            "outcome": row.outcome,
            "candidate_name": people[0] if len(people) == 1 else None,
            "candidate_names": people,
            "received_at": received,
        },
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
) -> bool:
    """Przetwórz jedną wiadomość. ``True`` = powstał choć jeden wpis w dzienniku."""
    message_id = msg.get("internetMessageId") or msg.get("id")
    if not message_id:
        return False
    stats.messages += 1
    added = False
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
            added = True
        stats.ignored_sender += 1
        return added

    try:
        page = await gc.get(f"{mailbox_prefix()}/messages/{msg['id']}/attachments")
    except Exception as exc:  # noqa: BLE001
        stats.failed += 1
        stats.errors.append(f"attachments {message_id[:40]}: {exc!r}"[:300])
        return False
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
            added = True
        stats.ignored_no_pdf += 1
        return added

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
            added = True
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
        added = True
        if row.outcome == OUTCOME_NEEDS_REVIEW:
            stats.needs_review += 1
            # Karty dla Delivery Leada NIE wystawia już pierwsze wstrzymanie:
            # od 0312 zamówienie dostaje trzy godzinowe próby automatycznego
            # dokończenia, a te, które czeka na podpis umowy, nie alarmuje
            # nigdy. Decyduje `order_mail_recheck._maybe_alert` (i dobowy
            # skaner, tą samą regułą `should_alert`).
        elif row.outcome == OUTCOME_AUTO_APPLIED:
            stats.auto_applied += 1
        elif row.outcome == OUTCOME_UNRECOGNIZED:
            stats.unrecognized += 1
    return added


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


STATUS_INTERRUPTED = "interrupted"
_COMPLETED_STATUSES = ("ok", "partial", "error")


def poll_interval_minutes() -> int:
    """Odstęp między biegami z podłogą 5 min (zero = pętla bez przerwy)."""
    return max(5, int(settings.ORDER_MAIL_POLL_INTERVAL_MINUTES or 0))


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value


def completed_record(
    stats: IngestStats,
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    error: Optional[str],
) -> dict[str, Any]:
    """Samodzielny zapis ostatniego ZAKOŃCZONEGO biegu — trafia do ``stats``.

    Wiersz stanu ma jedną parę start/koniec, a bieg, który właśnie trwa (albo
    został przerwany), nadpisuje start. Bez tego rekordu liczniki w ``stats``
    nie dałoby się jednoznacznie przypisać do biegu, który je wyprodukował.
    """
    return {
        **stats.as_dict(),
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
        "status": status,
        "error": error,
    }


def sync_snapshot(state: Optional[dict[str, Any]], *, running: bool) -> dict[str, Any]:
    """Stan pobierania w kształcie dla API kolejki i admina.

    ``last_status='running'`` w bazie znaczy tylko „bieg się zaczął". Czy trwa,
    wie wyłącznie blokada w TYM procesie: gdy jej nie ma, bieg został przerwany
    (restart kontenera przy deployu — u nas kilka razy dziennie) i końca nie
    zapisał. Taki bieg pokazujemy jako ``interrupted``, nie jako wieczne
    „trwa"; następny tick pętli i tak uruchomi go od nowa.
    """
    state = state or {}
    last_status = state.get("last_status")
    stats = state.get("stats") or {}
    last_completed = None
    if stats.get("finished_at") or (
        # Zapisy sprzed rekordu (bez ``finished_at`` w ``stats``): koniec
        # bierzemy z kolumny — tylko gdy ostatni start faktycznie się zakończył.
        stats and last_status in _COMPLETED_STATUSES
    ):
        last_completed = {
            "reason": stats.get("reason") or "scheduled",
            "started_at": stats.get("started_at")
            or _iso(state.get("last_run_started_at")),
            "finished_at": stats.get("finished_at")
            or _iso(state.get("last_run_finished_at")),
            "status": stats.get("status") or last_status,
            "error": stats.get("error", state.get("last_error")),
            "messages": int(stats.get("messages") or 0),
            "new_messages": int(stats.get("new_messages") or 0),
            "attachments": int(stats.get("attachments") or 0),
            "auto_applied": int(stats.get("auto_applied") or 0),
            "needs_review": int(stats.get("needs_review") or 0),
            "unrecognized": int(stats.get("unrecognized") or 0),
            "duplicates": int(stats.get("duplicates") or 0),
            "skipped_existing": int(stats.get("skipped_existing") or 0),
            "ignored_no_pdf": int(stats.get("ignored_no_pdf") or 0),
            "ignored_sender": int(stats.get("ignored_sender") or 0),
            "failed": int(stats.get("failed") or 0),
            "rechecked": int(stats.get("rechecked") or 0),
            "recheck_applied": int(stats.get("recheck_applied") or 0),
            "recheck_held": int(stats.get("recheck_held") or 0),
            "recheck_alerts": int(stats.get("recheck_alerts") or 0),
            "ai_retried": int(stats.get("ai_retried") or 0),
            "ai_recovered": int(stats.get("ai_recovered") or 0),
            "ai_recovered_auto_applied": int(
                stats.get("ai_recovered_auto_applied") or 0
            ),
            "errors": list(stats.get("errors") or []),
        }
    return {
        "enabled": bool(settings.ORDER_MAIL_INGEST_ENABLED),
        "interval_minutes": poll_interval_minutes(),
        "autoapply_enabled": autoapply_enabled(),
        "running": running,
        "started_at": _iso(state.get("last_run_started_at")),
        "interrupted": last_status == "running" and not running,
        "last_completed": last_completed,
    }


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
    stats = IngestStats(reason=reason)
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
            # Najpierw wstrzymane wpisy z kolejki — lokalnie, bez Graph, więc
            # także przy awarii skrzynki. Przelicza KAŻDY z nich (nie tylko te
            # na starej wersji reguły klienta): przyczyna wstrzymania znika
            # najczęściej gdzie indziej — po podpisaniu umowy albo po
            # uzupełnieniu NIP-u u klienta.
            try:
                from app.services.order_mail_recheck import run_recheck

                recheck = await run_recheck(db, trigger=reason)
                stats.rechecked = recheck.checked
                stats.recheck_applied = recheck.applied
                stats.recheck_held = recheck.held
                stats.recheck_alerts = recheck.alerts
            except Exception as exc:  # noqa: BLE001 — przeliczenie nie wywraca biegu
                logger.exception("order_mail: recheck of held documents failed")
                await db.rollback()
                stats.errors.append(f"recheck: {exc!r}"[:300])
            # Potem wpisy z odczytem awaryjnym (AI niedostępne przy odczycie
            # maila) — też lokalnie, z zachowanego PDF-a.
            try:
                await retry_ai_fallback_documents(db, stats)
            except Exception as exc:  # noqa: BLE001 — ponowienie nie wywraca biegu
                logger.exception("order_mail: AI re-read of fallback documents failed")
                await db.rollback()
                stats.errors.append(f"ai retry: {exc!r}"[:300])
            # Rejestr i okno PRZED wyborem klienta Graph: konstruktor klienta
            # otwiera pulę httpx, więc między nim a `async with` nie może stać
            # nic, co potrafi rzucić (inaczej pula nigdy nie jest zamykana).
            registry = await build_registry_from_db(db)
            effective_since = since or compute_since(state, now)
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
                    from app.core.operation_telemetry import record_job_outcome

                    record_job_outcome(
                        "order_mail",
                        False,
                        interval_seconds=poll_interval_minutes() * 60,
                    )
                    return stats
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
                    from app.core.operation_telemetry import record_job_outcome

                    record_job_outcome(
                        "order_mail",
                        False,
                        interval_seconds=poll_interval_minutes() * 60,
                    )
                    return stats
            logger.info(
                "order_mail ingest start (%s) since=%s mode=%s conn=%s",
                reason,
                effective_since.isoformat(),
                auth_mode(),
                conn.id if conn is not None else None,
            )
            try:
                async with (
                    AppGraphClient() if conn is None else GraphClient(conn, db)
                ) as gc:
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
                            if await _process_message(
                                db, gc, conn, msg, stats, registry
                            ):
                                stats.new_messages += 1
                status = "ok" if not (stats.failed or stats.errors) else "partial"
                error = None if status == "ok" else "; ".join(stats.errors[:5])[:2000]
                finished = datetime.now(timezone.utc)
                await _write_state(
                    db,
                    last_run_finished_at=finished,
                    last_status=status,
                    last_error=error,
                    # Watermark nie może się COFNĄĆ: bieg ręczny z jawnym
                    # ``since`` (backfill) ogląda starsze wiadomości niż
                    # ostatnio widziana i bez tego przesuwałby okno wstecz.
                    last_seen_received_at=_latest(
                        stats.max_received_at,
                        (state or {}).get("last_seen_received_at"),
                    ),
                    stats=completed_record(
                        stats,
                        started_at=now,
                        finished_at=finished,
                        status=status,
                        error=error,
                    ),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("order_mail ingest failed")
                stats.errors.append(repr(exc)[:300])
                # Sesja po padniętym zapytaniu wymaga rollbacku — inaczej sam
                # zapis stanu „error" padnie i wiersz zostanie na „running".
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    logger.exception("order_mail: rollback after failure failed")
                finished = datetime.now(timezone.utc)
                try:
                    await _write_state(
                        db,
                        last_run_finished_at=finished,
                        last_status="error",
                        last_error=repr(exc)[:2000],
                        stats=completed_record(
                            stats,
                            started_at=now,
                            finished_at=finished,
                            status="error",
                            error=repr(exc)[:2000],
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("order_mail: could not persist failed run state")
    from app.core.operation_telemetry import record_job_outcome

    record_job_outcome(
        "order_mail", not stats.errors, interval_seconds=poll_interval_minutes() * 60
    )
    logger.info("order_mail ingest done: errors=%d", len(stats.errors))
    return stats


def _latest(*values: Optional[datetime]) -> Optional[datetime]:
    known = []
    for value in values:
        if value is None:
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        known.append(value)
    return max(known) if known else None
