"""Webhooki API integracyjnego v1: adres, sekret, podpis i dostarczenie.

Adres (ochrona SSRF — przy zapisie i przed KAŻDĄ wysyłką)
---------------------------------------------------------
* tylko ``https://``, bez loginu/hasła w adresie, bez fragmentu, port 443;
* nazwa hosta rozwiązywana w DNS: KAŻDY adres musi być publiczny (bez
  loopback, sieci prywatnych, link-local i metadanych chmury, CGNAT,
  multicastu, zarezerwowanych — także IPv4 zapisanych w IPv6);
* połączenie idzie na sprawdzony adres IP (SNI i certyfikat dalej dla nazwy
  hosta), więc DNS nie podmieni celu między sprawdzeniem a wysyłką;
* przekierowania wyłączone (3xx = porażka), zmienne proxy ignorowane,
  odpowiedź nie jest czytana (liczy się tylko kod).

Podpis
------
``X-Nexus-Signature: sha256=<HMAC-SHA256 surowej treści sekretem webhooka>``.
Treść niesie ``sent_at`` — odbiorca może odrzucać stare powtórki. Sekret
(``whsec_…``) jest pokazany raz; w bazie leży zaszyfrowany Fernetem
(``core.encryption``), nigdy w logach.

Dostarczenie
------------
Co najmniej raz: zdarzenie może przyjść ponownie (np. proces padł po 2xx,
a przed zapisem kursora) — odbiorca odsiewa po ``id`` zdarzenia. Partie po
``DELIVERY_BATCH``; 2xx przesuwa kursor. Porażka = odstęp rosnący
wykładniczo (``backoff_seconds``), po ``MAX_CONSECUTIVE_FAILURES`` porażkach
z rzędu webhook jest wyłączany z powodem. Udane zdarzenie próbne
(``POST /webhooks/{id}/test``) włącza go z powrotem od zapamiętanego kursora.
Scope'y konta są czytane przy każdej wysyłce: konto wyłączone albo bez
``events:read`` nie dostaje nic, a zdarzenia spoza scope'ów są pomijane.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.encryption import get_token_cipher
from app.models.integration_event import IntegrationEvent, IntegrationWebhook
from app.models.service_account import ServiceAccount, ServiceScope, implied_scopes
from app.services.integration_events import (
    EVENT_SCOPES,
    TEST_EVENT_TYPE,
    event_payload,
    listed_jobs_clause,
)

logger = logging.getLogger(__name__)

MAX_WEBHOOKS_PER_ACCOUNT = 5
MAX_URL_LENGTH = 2048
SECRET_PREFIX = "whsec_"
SIGNATURE_HEADER = "X-Nexus-Signature"
EVENT_ID_HEADER = "X-Nexus-Event-Id"
WEBHOOK_ID_HEADER = "X-Nexus-Webhook-Id"
USER_AGENT = "NEXUS-Webhooks/1"

DELIVERY_BATCH = 100
MAX_BATCHES_PER_TICK = 10
REQUEST_TIMEOUT_SECONDS = 10.0
# Twardy sufit całej próby (DNS + połączenie + nagłówki odpowiedzi): odbiorca
# sączący odpowiedź bajt po bajcie nie trzyma pętli dłużej niż to.
ATTEMPT_DEADLINE_SECONDS = 15.0
DNS_TIMEOUT_SECONDS = 5.0
LEASE = timedelta(minutes=5)
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600
# 20 porażek z rzędu ≈ 14 h ponowień (30 s, 1 min, 2 min … potem co godzinę).
MAX_CONSECUTIVE_FAILURES = 20
# Ile adresów hosta próbujemy, gdy pierwszy nie przyjmuje połączenia.
MAX_ADDRESSES_TRIED = 3

# NAT64 (RFC 6052) niesie adres IPv4 w ostatnich 32 bitach — oceniamy ten adres.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_HOSTNAME_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62})(?:\.[a-z0-9-]{1,63})*")


# ── Adres ────────────────────────────────────────────────────────────────────


class WebhookUrlError(ValueError):
    """Adres odrzucony. ``code`` do koperty błędu, ``message`` po polsku."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class WebhookTarget:
    url: str
    host: str
    port: int
    is_ip_literal: bool


def parse_webhook_url(raw: str) -> WebhookTarget:
    """Sprawdzenie adresu bez sieci (schemat, host, port, długość)."""
    value = (raw or "").strip()
    if not value or len(value) > MAX_URL_LENGTH:
        raise WebhookUrlError(
            "invalid_webhook_url",
            f"Adres webhooka jest wymagany i ma najwyżej {MAX_URL_LENGTH} znaków.",
        )
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise WebhookUrlError(
            "invalid_webhook_url", "Adres webhooka jest niepoprawny."
        ) from None
    if parts.scheme.lower() != "https":
        raise WebhookUrlError(
            "webhook_url_not_https", "Adres webhooka musi zaczynać się od https://."
        )
    if parts.username is not None or parts.password is not None:
        raise WebhookUrlError(
            "invalid_webhook_url",
            "Adres webhooka nie może zawierać loginu ani hasła.",
        )
    if parts.fragment:
        raise WebhookUrlError(
            "invalid_webhook_url", "Adres webhooka nie może mieć fragmentu (#…)."
        )
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise WebhookUrlError("invalid_webhook_url", "Adres webhooka nie ma hosta.")
    if port not in (None, 443):
        raise WebhookUrlError(
            "webhook_url_port", "Webhook może używać wyłącznie portu 443 (https)."
        )
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    if not is_ip:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise WebhookUrlError(
                "invalid_webhook_url", "Nazwa hosta webhooka jest niepoprawna."
            ) from None
        if not _HOSTNAME_RE.fullmatch(host):
            raise WebhookUrlError(
                "invalid_webhook_url", "Nazwa hosta webhooka jest niepoprawna."
            )
    netloc = f"[{host}]" if is_ip and ":" in host else host
    url = urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))
    return WebhookTarget(url=url, host=host, port=443, is_ip_literal=is_ip)


def is_public_address(ip: str) -> bool:
    """Adres routowalny w internecie — nic lokalnego, prywatnego ani specjalnego."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped or addr.sixtofour
        if addr in _NAT64:
            mapped = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        if mapped is not None:
            return is_public_address(str(mapped))
        if addr.teredo is not None or addr.is_site_local:
            return False
    return bool(
        addr.is_global
        and not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        )
    )


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.wait_for(
        asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM),
        timeout=DNS_TIMEOUT_SECONDS,
    )
    return list(dict.fromkeys(info[4][0] for info in infos))


async def resolve_public_addresses(target: WebhookTarget) -> list[str]:
    """Adresy hosta — wszystkie publiczne, inaczej ``WebhookUrlError``."""
    if target.is_ip_literal:
        addresses = [target.host]
    else:
        try:
            addresses = await _resolve(target.host, target.port)
        except (asyncio.TimeoutError, OSError, UnicodeError):
            raise WebhookUrlError(
                "webhook_url_unresolvable",
                "Nie udało się ustalić adresu hosta webhooka (DNS).",
            ) from None
    if not addresses:
        raise WebhookUrlError(
            "webhook_url_unresolvable",
            "Nie udało się ustalić adresu hosta webhooka (DNS).",
        )
    if not all(is_public_address(ip) for ip in addresses):
        raise WebhookUrlError(
            "webhook_url_not_public",
            "Adres webhooka prowadzi do sieci wewnętrznej albo adresu "
            "specjalnego — dozwolone są wyłącznie publiczne adresy.",
        )
    # IPv4 najpierw: kontener bywa bez łączności IPv6, a host z dwoma
    # stosami zwraca zwykle najpierw adres v6.
    return sorted(addresses, key=lambda ip: ":" in ip)


async def validate_webhook_url(raw: str) -> str:
    """Pełne sprawdzenie przy zapisie; zwraca adres w postaci znormalizowanej."""
    target = parse_webhook_url(raw)
    await resolve_public_addresses(target)
    return target.url


def display_url(url: str) -> str:
    """Adres do ekranu admina: bez parametrów (bywają w nich tokeny odbiorcy)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "?"
    suffix = "?…" if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) + suffix


# ── Sekret i podpis ──────────────────────────────────────────────────────────


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def encrypt_secret(secret: str) -> str:
    """Rzuca ``TokenCipherNotConfigured``, gdy klucz szyfrowania nie jest ustawiony."""
    return get_token_cipher().encrypt(secret)


def decrypt_secret(ciphertext: str) -> str:
    return get_token_cipher().decrypt(ciphertext)


def sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_body(
    webhook_id: int, events: list[dict[str, Any]], sent_at: datetime
) -> bytes:
    return json.dumps(
        {
            "webhook_id": webhook_id,
            "sent_at": sent_at.isoformat(),
            "events": events,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_event(webhook_id: int, now: datetime) -> dict[str, Any]:
    return {
        "id": 0,
        "type": TEST_EVENT_TYPE,
        "occurred_at": now.isoformat(),
        "refs": {"webhook_id": webhook_id},
    }


# ── Wysyłka ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status: Optional[int]
    error: Optional[str]


def _pinned_url(target: WebhookTarget, ip: str) -> str:
    parts = urlsplit(target.url)
    netloc = f"[{ip}]" if ":" in ip else ip
    return urlunsplit(("https", netloc, parts.path, parts.query, ""))


def new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
    )


async def post_signed(
    client: httpx.AsyncClient,
    *,
    url: str,
    secret: str,
    webhook_id: int,
    last_event_id: int,
    body: bytes,
) -> DeliveryResult:
    """Jedna próba wysyłki (SSRF sprawdzany tu, tuż przed połączeniem)."""
    try:
        target = parse_webhook_url(url)
        addresses = await resolve_public_addresses(target)
    except WebhookUrlError as exc:
        return DeliveryResult(False, None, exc.code)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Host": target.host if ":" not in target.host else f"[{target.host}]",
        SIGNATURE_HEADER: sign(secret, body),
        EVENT_ID_HEADER: str(last_event_id),
        WEBHOOK_ID_HEADER: str(webhook_id),
    }
    extensions = {} if target.is_ip_literal else {"sni_hostname": target.host}

    async def _send() -> int:
        # Odpowiedź nie jest czytana — liczy się kod; treść odbiorcy nie
        # trafia do pamięci ani do logów.
        last_error: Optional[httpx.ConnectError] = None
        for ip in addresses[:MAX_ADDRESSES_TRIED]:
            try:
                async with client.stream(
                    "POST",
                    _pinned_url(target, ip),
                    content=body,
                    headers=headers,
                    extensions=extensions,
                ) as response:
                    return response.status_code
            except httpx.ConnectError as exc:
                last_error = exc
        raise last_error or httpx.ConnectError("brak adresu")

    try:
        status = await asyncio.wait_for(_send(), timeout=ATTEMPT_DEADLINE_SECONDS)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return DeliveryResult(False, None, "timeout")
    except httpx.HTTPError as exc:
        return DeliveryResult(False, None, f"network:{type(exc).__name__}"[:120])
    except Exception as exc:  # noqa: BLE001 — porażka z odstępem, nie pętla co 10 s
        return DeliveryResult(False, None, f"error:{type(exc).__name__}"[:120])
    if 200 <= status < 300:
        return DeliveryResult(True, status, None)
    if 300 <= status < 400:
        return DeliveryResult(False, status, "redirect_not_followed")
    return DeliveryResult(False, status, f"http_{status}")


def backoff_seconds(failure_count: int) -> int:
    """Odstęp po ``failure_count``-tej porażce z rzędu: 30 s, 60 s, … do 1 h."""
    exponent = max(0, failure_count - 1)
    return min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** min(exponent, 16)))


# ── Jeden webhook w jednym biegu pętli ──────────────────────────────────────


async def due_webhook_ids(db: AsyncSession, now: datetime) -> list[int]:
    """Webhooki do obsłużenia teraz: aktywne po odstępie albo z próbą w kolejce."""
    rows = await db.execute(
        select(IntegrationWebhook.id)
        .where(
            or_(
                IntegrationWebhook.test_requested_at.isnot(None),
                (IntegrationWebhook.is_active.is_(True))
                & (
                    IntegrationWebhook.next_attempt_at.is_(None)
                    | (IntegrationWebhook.next_attempt_at <= now)
                ),
            ),
            or_(
                IntegrationWebhook.lease_until.is_(None),
                IntegrationWebhook.lease_until < now,
            ),
        )
        .order_by(IntegrationWebhook.id)
    )
    ids = list(rows.scalars())
    await db.commit()
    return ids


async def _claim(db: AsyncSession, webhook_id: int, now: datetime) -> bool:
    result = await db.execute(
        update(IntegrationWebhook)
        .where(
            IntegrationWebhook.id == webhook_id,
            or_(
                IntegrationWebhook.lease_until.is_(None),
                IntegrationWebhook.lease_until < now,
            ),
        )
        .values(lease_until=now + LEASE)
        .returning(IntegrationWebhook.id)
    )
    claimed = result.scalar_one_or_none() is not None
    await db.commit()
    return claimed


async def _release(db: AsyncSession, webhook_id: int) -> None:
    await db.execute(
        update(IntegrationWebhook)
        .where(IntegrationWebhook.id == webhook_id)
        .values(lease_until=None)
    )
    await db.commit()


async def _visible_scopes(db: AsyncSession, account_id: int) -> Optional[set[str]]:
    """Scope'y zdarzeń, które konto widzi TERAZ; ``None`` = nic nie wysyłać."""
    account = await db.get(ServiceAccount, account_id, populate_existing=True)
    if account is None or not account.is_active:
        return None
    effective = implied_scopes(account.granted_scopes())
    if ServiceScope.events_read.value not in effective:
        return None
    return set(effective) & EVENT_SCOPES


def _record(hook: IntegrationWebhook, result: DeliveryResult, now: datetime) -> None:
    hook.last_delivery_at = now
    hook.last_status = result.status
    hook.last_error = None if result.ok else (result.error or "error")[:120]


def _disable(hook: IntegrationWebhook, now: datetime, reason: str) -> None:
    hook.is_active = False
    hook.disabled_at = now
    hook.disabled_reason = reason[:255]


def _secret_or_disable(hook: IntegrationWebhook, now: datetime) -> Optional[str]:
    """Jawny sekret albo ``None`` + wyłączenie (np. zmieniony klucz szyfrowania).

    Bez wyłączenia taki webhook wracałby z tym samym wyjątkiem w każdym biegu.
    """
    try:
        return decrypt_secret(hook.secret_ct)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "integration_webhooks: sekret webhooka %d nie do odczytu (%s)",
            hook.id,
            type(exc).__name__,
        )
        hook.test_requested_at = None
        hook.last_error = "secret_unreadable"
        _disable(
            hook,
            now,
            "Sekretu podpisu nie da się odczytać (zmieniony klucz szyfrowania) — "
            "usuń webhook i załóż go ponownie.",
        )
        return None


async def _send_test(
    db: AsyncSession, client: httpx.AsyncClient, hook: IntegrationWebhook, now: datetime
) -> None:
    """Zdarzenie próbne. Nie liczy się do serii porażek; sukces włącza webhook."""
    secret = _secret_or_disable(hook, now)
    if secret is None:
        await db.commit()
        return
    hook.test_requested_at = None
    body = build_body(hook.id, [test_event(hook.id, now)], now)
    await db.commit()  # połączenie wraca do puli przed wysyłką
    result = await post_signed(
        client,
        url=hook.url,
        secret=secret,
        webhook_id=hook.id,
        last_event_id=0,
        body=body,
    )
    _record(hook, result, now)
    if result.ok and not hook.is_active:
        hook.is_active = True
        hook.failure_count = 0
        hook.next_attempt_at = None
        hook.disabled_reason = None
        hook.disabled_at = None
    await db.commit()


async def _send_events(
    db: AsyncSession,
    client: httpx.AsyncClient,
    hook: IntegrationWebhook,
    scopes: set[str],
    now: datetime,
) -> str:
    secret = _secret_or_disable(hook, now)
    if secret is None:
        await db.commit()
        return "failed"
    types = [t for t in (hook.event_types or []) if isinstance(t, str)]
    for _ in range(MAX_BATCHES_PER_TICK):
        upper = await db.scalar(select(func.max(IntegrationEvent.id)))
        if upper is None or upper <= hook.last_event_id or not scopes:
            if upper is not None and upper > hook.last_event_id:
                hook.last_event_id = upper
            await db.commit()
            return "idle"
        query = select(IntegrationEvent).where(
            IntegrationEvent.id > hook.last_event_id,
            IntegrationEvent.id <= upper,
            IntegrationEvent.scope.in_(sorted(scopes)),
            listed_jobs_clause(),
        )
        if types:
            query = query.where(IntegrationEvent.type.in_(types))
        rows = list(
            (
                await db.execute(
                    query.order_by(IntegrationEvent.id).limit(DELIVERY_BATCH + 1)
                )
            ).scalars()
        )
        more = len(rows) > DELIVERY_BATCH
        batch = rows[:DELIVERY_BATCH]
        if not batch:
            # Nic widocznego do granicy — kursor przeskakuje cudze zdarzenia.
            hook.last_event_id = upper
            await db.commit()
            return "idle"
        events = [event_payload(row) for row in batch]
        cursor_after = batch[-1].id if more else upper
        body = build_body(hook.id, events, datetime.now(timezone.utc))
        await db.commit()  # połączenie wraca do puli przed wysyłką
        result = await post_signed(
            client,
            url=hook.url,
            secret=secret,
            webhook_id=hook.id,
            last_event_id=batch[-1].id,
            body=body,
        )
        _record(hook, result, now)
        if not result.ok:
            hook.failure_count = (hook.failure_count or 0) + 1
            hook.next_attempt_at = now + timedelta(
                seconds=backoff_seconds(hook.failure_count)
            )
            if hook.failure_count >= MAX_CONSECUTIVE_FAILURES:
                _disable(
                    hook,
                    now,
                    f"{hook.failure_count} nieudanych prób z rzędu "
                    f"(ostatnio: {hook.last_error})",
                )
                logger.warning(
                    "integration_webhooks: webhook %d wyłączony po %d porażkach",
                    hook.id,
                    hook.failure_count,
                )
            await db.commit()
            return "failed"
        hook.last_event_id = cursor_after
        hook.failure_count = 0
        hook.next_attempt_at = None
        await db.commit()
        if not more:
            return "delivered"
    return "delivered"


async def deliver_webhook(
    db: AsyncSession,
    client: httpx.AsyncClient,
    webhook_id: int,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Obsłuż jeden webhook: rezerwacja → próba (jeśli zamówiona) → zdarzenia.

    Zwraca etykietę wyniku do logów i testów: ``busy`` (inny proces ma
    rezerwację), ``gone``, ``skipped`` (wyłączony, odstęp, konto bez prawa),
    ``idle``, ``delivered``, ``failed``.
    """
    now = now or datetime.now(timezone.utc)
    if not await _claim(db, webhook_id, now):
        return "busy"
    try:
        hook = await db.get(IntegrationWebhook, webhook_id, populate_existing=True)
        if hook is None:
            return "gone"
        scopes = await _visible_scopes(db, hook.service_account_id)
        if scopes is None:
            # Konto wyłączone albo bez ``events:read`` — próba też nie wychodzi.
            hook.test_requested_at = None
            await db.commit()
            return "skipped"
        if hook.test_requested_at is not None:
            await _send_test(db, client, hook, now)
        if not hook.is_active or (
            hook.next_attempt_at is not None and hook.next_attempt_at > now
        ):
            await db.commit()
            return "skipped"
        return await _send_events(db, client, hook, scopes, now)
    except StaleDataError:
        # Webhook usunięty (trasą albo z kontem) w trakcie wysyłki.
        return "gone"
    finally:
        try:
            await db.rollback()
            await _release(db, webhook_id)
        except Exception:  # noqa: BLE001 — rezerwacja i tak wygaśnie po LEASE
            logger.warning(
                "integration_webhooks: nie zwolniono rezerwacji webhooka %d",
                webhook_id,
            )


__all__ = [
    "DELIVERY_BATCH",
    "DeliveryResult",
    "EVENT_ID_HEADER",
    "MAX_CONSECUTIVE_FAILURES",
    "MAX_WEBHOOKS_PER_ACCOUNT",
    "SIGNATURE_HEADER",
    "WebhookTarget",
    "WebhookUrlError",
    "backoff_seconds",
    "build_body",
    "decrypt_secret",
    "deliver_webhook",
    "display_url",
    "due_webhook_ids",
    "encrypt_secret",
    "is_public_address",
    "new_http_client",
    "new_secret",
    "parse_webhook_url",
    "post_signed",
    "resolve_public_addresses",
    "sign",
    "validate_webhook_url",
]
