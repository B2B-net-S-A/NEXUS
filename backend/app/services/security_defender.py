"""Źródło „Microsoft Defender” ekranu Bezpieczeństwo — NEXUS czyta je sam z Graph.

Zlecenie Artura z 28.11.2026: incydent High z Defendera wisiał od 22.11
nieprzypisany, bo nikt nie zagląda do portalu Microsoftu. Co 15 min
(``tasks/security_defender.py``) czytamy:

* ``GET /security/incidents?$expand=alerts`` — otwarte incydenty (każdy stan
  poza ``resolved``/``redirected``) i wszystkie zmienione w ostatnich 30
  dniach. Kilka zapytań zamiast jednego z ``or``, bo Graph nie obiecuje
  ``or`` w filtrze incydentów; wynik łączymy po id.
* ``GET /security/secureScores?$top=1`` — Secure Score na kafelek.

Kontrakt jak pozostałe źródła (``security_findings``/``security_events``,
źródło ``defender``, scanner ``defender``):

* incydent otwarty → znalezisko „czeka na reakcję”, klucz = id incydentu,
  waga z ``severity``; zdarzenie ``incident_open`` raz na incydent;
* ``resolved``/``redirected`` → zamknięcie znaleziska jako naprawione (także
  z wyjątkiem) i zdarzenie ``incident_resolved``;
* pełny odczyt (wszystkie strony) zamyka też otwarte znaleziska, których
  Defender już nie zwraca (scalony albo usunięty incydent);
* nowy albo wznowiony incydent High/Critical → dzwonek i mail każdemu
  aktywnemu adminowi (``security_defender_incident``).

Prywatność (repo i logi Actions są publiczne, ekran czyta każdy admin):
tytuł to ``displayName`` po ``scrub`` (bez adresów IP i e-maili, więc bez
UPN-ów), dowód to kategorie alertów, źródła wykrycia i liczba zasobów według
typu. Z ``evidence`` alertów nie czytamy żadnej wartości (konto, urządzenie,
adres) — tylko typ, a do policzenia unikalnych zasobów skrót w pamięci.
``assignedTo`` (UPN) mówi tylko „przypisany / nieprzypisany”. ``incidentWebUrl``
niesie id tenanta, więc link składamy sami z id incydentu.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.notification import NotificationType
from app.models.security import SecurityFinding, SecuritySourceState
from app.services.m365 import defender_auth
from app.services.security_ingest import (
    IngestEvent,
    IngestFinding,
    Severity,
    resolve_findings,
    scrub,
    store_events,
    upsert_findings,
)

logger = logging.getLogger(__name__)

SOURCE = "defender"
SCANNER = "defender"
GRAPH = "https://graph.microsoft.com/v1.0"
PORTAL = "https://security.microsoft.com"
TIMEOUT = httpx.Timeout(30.0)
#: Incydenty zmienione w tylu dniach wracają w odczycie (także zamknięte).
WINDOW_DAYS = 30
PAGE_SIZE = 50  # maksimum Graph dla /security/incidents
MAX_PAGES = 20  # na zapytanie; więcej = odczyt niepełny, bez zamykania brakujących
OPEN_STATUSES = ("active", "inProgress", "awaitingAction")
CLOSED_STATUSES = frozenset({"resolved", "redirected"})
BELL_SEVERITIES = frozenset({"high", "critical"})
SECURITY_LINK = "/settings?area=sys&item=security"
FINDING_ENTITY = "security_finding"

_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_CATEGORY = re.compile(r"^[A-Za-z]{1,40}$")

_SEVERITY: dict[str, Severity] = {
    "informational": "info",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}
_SEVERITY_LABEL = {
    "critical": "krytyczna",
    "high": "wysoka",
    "medium": "średnia",
    "low": "niska",
    "info": "informacja",
}

# Taktyki MITRE i kategorie Defendera (``alert.category``) po polsku.
_CATEGORY_LABEL = {
    "InitialAccess": "wstępny dostęp",
    "Execution": "uruchomienie kodu",
    "Persistence": "utrwalenie",
    "PrivilegeEscalation": "podniesienie uprawnień",
    "DefenseEvasion": "omijanie ochrony",
    "CredentialAccess": "dostęp do poświadczeń",
    "Discovery": "rozpoznanie",
    "LateralMovement": "ruch w sieci",
    "Collection": "zbieranie danych",
    "CommandAndControl": "kontrola zdalna",
    "Exfiltration": "wyprowadzanie danych",
    "Impact": "szkoda",
    "Reconnaissance": "rekonesans",
    "ResourceDevelopment": "przygotowanie zasobów",
    "Malware": "złośliwe oprogramowanie",
    "Ransomware": "ransomware",
    "UnwantedSoftware": "niechciane oprogramowanie",
    "Exploit": "wykorzystanie luki",
    "SuspiciousActivity": "podejrzana aktywność",
    "ThreatManagement": "zarządzanie zagrożeniem",
    "MailFlow": "przepływ poczty",
    "DataLossPrevention": "wyciek danych (DLP)",
}

_SERVICE_LABEL = {
    "microsoftDefenderForEndpoint": "Defender for Endpoint",
    "microsoftDefenderForIdentity": "Defender for Identity",
    "microsoftDefenderForCloudApps": "Defender for Cloud Apps",
    "microsoftDefenderForOffice365": "Defender for Office 365",
    "microsoft365Defender": "Defender XDR",
    "azureAdIdentityProtection": "Entra ID Protection",
    "microsoftAppGovernance": "App Governance",
    "dataLossPrevention": "Purview DLP",
    "microsoftDefenderForCloud": "Defender for Cloud",
    "microsoftSentinel": "Sentinel",
    "microsoftInsiderRiskManagement": "Insider Risk",
}

# Typ zasobu z ``@odata.type`` dowodu → (jeden, kilka); wartości nie czytamy.
_EVIDENCE_LABEL = {
    "userEvidence": "konto",
    "deviceEvidence": "urządzenie",
    "ipEvidence": "adres IP",
    "mailboxEvidence": "skrzynka",
    "analyzedMessageEvidence": "wiadomość",
    "mailClusterEvidence": "grupa wiadomości",
    "urlEvidence": "adres URL",
    "fileEvidence": "plik",
    "processEvidence": "proces",
    "cloudApplicationEvidence": "aplikacja w chmurze",
    "oauthApplicationEvidence": "aplikacja OAuth",
    "registryKeyEvidence": "wpis rejestru",
    "registryValueEvidence": "wpis rejestru",
    "securityGroupEvidence": "grupa",
}

STEPS = [
    "Otwórz incydent w Defenderze i przypisz go osobie, która go prowadzi",
    "Sprawdź alerty i zasoby; w razie potrzeby unieważnij sesje, zmień hasło albo odizoluj urządzenie",
    "Zamknij incydent w Defenderze z klasyfikacją — znalezisko zamknie się samo przy następnym odczycie",
]


def incident_url(incident_id: str) -> Optional[str]:
    """Link do incydentu w portalu, bez id tenanta (``incidentWebUrl`` go niesie)."""
    if not _ID.match(incident_id or ""):
        return None
    return f"{PORTAL}/incidents/{incident_id}"


def finding_link(source: str, fingerprint: str) -> Optional[str]:
    return incident_url(fingerprint) if source == SOURCE else None


def defender_severity(value: Any) -> Severity:
    """``informational`` → info; nieznana wartość (``unknownFutureValue``) → średnia."""
    return _SEVERITY.get(str(value or "").strip().lower(), "medium")


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    # Graph daje do 7 cyfr ułamka sekundy, ``fromisoformat`` przed 3.11 tylko 6.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _evidence_kind(evidence: dict[str, Any]) -> str:
    odata = str(evidence.get("@odata.type") or "")
    return odata.rsplit(".", 1)[-1] if odata else "other"


def _evidence_key(evidence: dict[str, Any]) -> str:
    """Skrót zasobu do policzenia unikalnych — tylko w pamięci, nigdzie nie zapisywany."""
    stable = {
        k: v
        for k, v in evidence.items()
        if k
        not in (
            "createdDateTime",
            "verdict",
            "remediationStatus",
            "remediationStatusDetails",
            "roles",
            "tags",
            "detailedRoles",
        )
    }
    blob = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _resources(alerts: list[dict[str, Any]]) -> dict[str, int]:
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for alert in alerts:
        for evidence in alert.get("evidence") or []:
            if not isinstance(evidence, dict):
                continue
            key = _evidence_key(evidence)
            if key in seen:
                continue
            seen.add(key)
            label = _EVIDENCE_LABEL.get(_evidence_kind(evidence), "inny zasób")
            counts[label] = counts.get(label, 0) + 1
    return counts


def _categories(alerts: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for alert in alerts:
        raw = str(alert.get("category") or "").strip()
        if not _CATEGORY.match(raw):
            continue
        label = _CATEGORY_LABEL.get(raw, raw)
        if label not in labels:
            labels.append(label)
    return labels


def _services(alerts: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for alert in alerts:
        raw = str(alert.get("serviceSource") or "").strip()
        label = _SERVICE_LABEL.get(raw)
        if label and label not in labels:
            labels.append(label)
    return labels


def incident_evidence(incident: dict[str, Any]) -> str:
    """Kategorie, liczba alertów i zasobów według typu, stan przypisania — bez wartości."""
    alerts = [a for a in incident.get("alerts") or [] if isinstance(a, dict)]
    parts: list[str] = []
    categories = _categories(alerts)
    if categories:
        parts.append("Kategoria: " + ", ".join(categories))
    parts.append(f"alerty: {len(alerts)}")
    resources = _resources(alerts)
    if resources:
        total = sum(resources.values())
        detail = ", ".join(f"{label} {n}" for label, n in sorted(resources.items()))
        parts.append(f"zasoby: {total} ({detail})")
    parts.append("przypisany" if incident.get("assignedTo") else "nieprzypisany")
    return " · ".join(parts)


def incident_location(incident: dict[str, Any]) -> str:
    """Usługi, które wykryły incydent; źródło „Defender” ekran pokazuje osobno."""
    alerts = [a for a in incident.get("alerts") or [] if isinstance(a, dict)]
    return ", ".join(_services(alerts)) or "Defender XDR"


def incident_title(incident: dict[str, Any]) -> str:
    name = scrub(str(incident.get("displayName") or ""), 200) or ""
    return name or f"Incydent {incident.get('id')}"


@dataclass
class DefenderParsed:
    open_findings: list[IngestFinding] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    events: list[IngestEvent] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)
    skipped: int = 0


def parse_incidents(incidents: list[dict[str, Any]]) -> DefenderParsed:
    """Odpowiedź Graph → znaleziska otwarte, odciski do zamknięcia i zdarzenia.

    Funkcja czysta (bez bazy i sieci) — testy idą na przykładowym JSON-ie
    z ``tests/data/security/defender_incidents_example.json``."""
    out = DefenderParsed()
    by_id: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        if not isinstance(incident, dict):
            out.skipped += 1
            continue
        incident_id = str(incident.get("id") or "")
        if not _ID.match(incident_id):
            out.skipped += 1
            continue
        by_id[incident_id] = incident
    for incident_id, incident in by_id.items():
        created = _parse_time(incident.get("createdDateTime"))
        updated = _parse_time(incident.get("lastUpdateDateTime")) or created
        if created is None:
            out.skipped += 1
            continue
        title = incident_title(incident)
        severity = defender_severity(incident.get("severity"))
        status = str(incident.get("status") or "")
        url = incident_url(incident_id)
        open_ref = f"defender:{incident_id}:open"
        out.events.append(
            IngestEvent(
                occurred_at=created,
                kind="incident_open",
                severity=severity,
                summary=f"Incydent {incident_id}: {title}"[:300],
                ref=open_ref,
            )
        )
        if url:
            out.links[open_ref] = url
        if status in CLOSED_STATUSES:
            out.resolved.append(incident_id)
            closed_ref = f"defender:{incident_id}:resolved"
            out.events.append(
                IngestEvent(
                    occurred_at=updated or created,
                    kind="incident_resolved",
                    severity="info",
                    summary=f"Incydent {incident_id} zamknięty w Defenderze: {title}"[
                        :300
                    ],
                    ref=closed_ref,
                )
            )
            if url:
                out.links[closed_ref] = url
            continue
        out.open_findings.append(
            IngestFinding(
                fingerprint=incident_id,
                severity=severity,
                title=title,
                location=incident_location(incident),
                evidence=incident_evidence(incident)[:2000],
                steps=list(STEPS),
                detected_at=created,
            )
        )
    return out


def secure_score_percent(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Ostatni Secure Score jako procent (2 miejsca) i dzień pomiaru."""
    rows = payload.get("value") or []
    if not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    try:
        current = float(row.get("currentScore"))
        maximum = float(row.get("maxScore"))
    except (TypeError, ValueError):
        return None
    if maximum <= 0:
        return None
    measured = _parse_time(row.get("createdDateTime"))
    return {
        "percent": round(current / maximum * 100, 2),
        "on": measured.date().isoformat() if measured else None,
    }


# ── Odczyt z Graph ───────────────────────────────────────────────────────────


class DefenderReadError(Exception):
    """Krótki opis do stanu źródła: klasa albo status HTTP, nigdy treść odpowiedzi."""


def error_label(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, defender_auth.DefenderTokenError):
        return f"token: {exc.code}"[:300]
    if isinstance(exc, DefenderReadError):
        return str(exc)[:300]
    return type(exc).__name__[:300]


def incident_filters(now: datetime) -> list[str]:
    since = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [f"status eq '{s}'" for s in OPEN_STATUSES] + [
        f"lastUpdateDateTime ge {since}"
    ]


class _Graph:
    """Cienki klient: token z Entra w wątku (MSAL jest synchroniczny), jedno
    odświeżenie po 401, ``@odata.nextLink`` tylko do graph.microsoft.com."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.token: Optional[str] = None

    async def _token(self, *, force: bool = False) -> str:
        if self.token is None or force:
            self.token = await asyncio.to_thread(
                defender_auth.acquire_defender_token, force_refresh=force
            )
        return self.token

    async def get(self, url: str, params: Optional[dict[str, str]] = None) -> dict:
        for attempt in (0, 1):
            token = await self._token(force=attempt == 1)
            response = await self.client.get(
                url, params=params, headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code == 401 and attempt == 0:
                continue
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise DefenderReadError("odpowiedź Graph nie jest obiektem")
            return body
        raise DefenderReadError("HTTP 401")  # pragma: no cover — pętla zwraca wyżej

    async def pages(self, url: str, params: dict[str, str]) -> tuple[list[dict], bool]:
        """Wszystkie strony (do ``MAX_PAGES``); drugi element = odczyt pełny."""
        rows: list[dict] = []
        body = await self.get(url, params)
        for _ in range(MAX_PAGES):
            rows.extend(r for r in body.get("value") or [] if isinstance(r, dict))
            next_link = body.get("@odata.nextLink")
            if not next_link:
                return rows, True
            if not str(next_link).startswith(f"{GRAPH}/"):
                raise DefenderReadError("nextLink spoza graph.microsoft.com")
            body = await self.get(str(next_link))
        return rows, False


async def fetch_incidents(
    graph: _Graph, now: datetime
) -> tuple[list[dict[str, Any]], bool]:
    merged: dict[str, dict[str, Any]] = {}
    complete = True
    for flt in incident_filters(now):
        rows, full = await graph.pages(
            f"{GRAPH}/security/incidents",
            {"$filter": flt, "$expand": "alerts", "$top": str(PAGE_SIZE)},
        )
        complete = complete and full
        for row in rows:
            merged[str(row.get("id"))] = row
    return list(merged.values()), complete


# ── Zapis i dzwonek ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DefenderSyncResult:
    configured: bool
    ok: bool = False
    open: int = 0
    new: int = 0
    closed: int = 0
    bells: int = 0


async def _state(db: AsyncSession) -> SecuritySourceState:
    state = await db.get(SecuritySourceState, SOURCE)
    if state is None:
        state = SecuritySourceState(source=SOURCE, detail={})
        db.add(state)
    return state


def needs_bell(finding: IngestFinding, before: Optional[tuple[str, str]]) -> bool:
    """Nowy, wznowiony albo podniesiony do High/Critical incydent dzwoni.
    ``before`` = (status, waga) znaleziska przed tym odczytem."""
    if finding.severity not in BELL_SEVERITIES:
        return False
    if before is None:
        return True
    status, severity = before
    return status == "fixed" or severity not in BELL_SEVERITIES


async def notify_admins(db: AsyncSession, rows: list[SecurityFinding]) -> int:
    from app.services.notification_triggers import emit  # noqa: PLC0415 — cykl importów
    from app.services.security_screen import _admin_ids  # noqa: PLC0415

    if not rows:
        return 0
    admins = await _admin_ids(db)
    sent = 0
    for row in rows:
        label = _SEVERITY_LABEL.get(row.severity, row.severity)
        title = f"Incydent w Defenderze ({label}): {row.title}"[:255]
        since = row.first_seen_at.astimezone(local_now().tzinfo)
        message = (
            f"Microsoft Defender zgłosił incydent {row.fingerprint} o wadze {label} "
            f"({since:%d.%m.%Y %H:%M}). {f'{row.evidence}. ' if row.evidence else ''}"
            "Otwórz go w Ustawienia → Bezpieczeństwo albo w portalu Defendera, "
            "przypisz osobę i zamknij z klasyfikacją."
        )
        for admin_id in admins:
            created = await emit(
                db,
                user_id=admin_id,
                title=title,
                message=message,
                ntype=NotificationType.security_defender_incident,
                related_entity_type=FINDING_ENTITY,
                related_entity_id=row.id,
                link=SECURITY_LINK,
            )
            sent += int(created is not None)
    return sent


async def apply_parsed(
    db: AsyncSession,
    parsed: DefenderParsed,
    *,
    complete: bool,
    run_id: str,
    now: datetime,
) -> tuple[int, int, int]:
    """Zapis jednego odczytu: zdarzenia, zamknięcia, znaleziska, dzwonek.
    Zwraca (nowe, zamknięte, dzwonki)."""
    fingerprints = [f.fingerprint for f in parsed.open_findings]
    before: dict[str, tuple[str, str]] = {}
    if fingerprints:
        rows = await db.execute(
            select(
                SecurityFinding.fingerprint,
                SecurityFinding.status,
                SecurityFinding.severity,
            ).where(
                SecurityFinding.source == SOURCE,
                SecurityFinding.fingerprint.in_(fingerprints),
            )
        )
        before = {fp: (status, sev) for fp, status, sev in rows.all()}
    ring = [
        f.fingerprint
        for f in parsed.open_findings
        if needs_bell(f, before.get(f.fingerprint))
    ]

    await store_events(db, SOURCE, parsed.events, links=parsed.links)
    closed = await resolve_findings(
        db, SOURCE, parsed.resolved, note="Incydent zamknięty w Defenderze", now=now
    )
    new, _updated, missing = await upsert_findings(
        db,
        SOURCE,
        parsed.open_findings,
        scanner=SCANNER,
        complete=complete,
        run_id=run_id,
        now=now,
    )
    bells = 0
    if ring:
        rows_to_ring = list(
            await db.scalars(
                select(SecurityFinding).where(
                    SecurityFinding.source == SOURCE,
                    SecurityFinding.fingerprint.in_(ring),
                )
            )
        )
        bells = await notify_admins(db, rows_to_ring)
    return new, closed + missing, bells


async def sync_defender(
    db: AsyncSession, client: httpx.AsyncClient, *, now: Optional[datetime] = None
) -> DefenderSyncResult:
    """Jeden odczyt Defendera. Bez poświadczeń nic nie robi (źródło
    „nieskonfigurowane”). Błąd odczytu zapisuje krótki opis w stanie źródła
    i niczego nie zamyka — następny bieg ponawia."""
    if not defender_auth.credentials_configured():
        return DefenderSyncResult(configured=False)
    now = now or datetime.now(timezone.utc)
    state = await _state(db)
    state.last_run_at = now
    graph = _Graph(client)
    try:
        incidents, complete = await fetch_incidents(graph, now)
    except Exception as exc:  # noqa: BLE001 — stan źródła mówi o błędzie, pętla żyje
        state.last_error = error_label(exc)
        logger.warning(
            "security_defender: incidents read failed (%s)", state.last_error
        )
        await db.commit()
        return DefenderSyncResult(configured=True)

    score: Optional[dict[str, Any]] = None
    score_error: Optional[str] = None
    try:
        score = secure_score_percent(
            await graph.get(f"{GRAPH}/security/secureScores", {"$top": "1"})
        )
    except Exception as exc:  # noqa: BLE001 — bez Secure Score incydenty i tak idą
        score_error = error_label(exc)
        logger.warning("security_defender: secure score failed (%s)", score_error)

    parsed = parse_incidents(incidents)
    # Unikalny na bieg, także gdy dwa biegi mają ten sam zegar (testy, ponowienie).
    run_id = f"defender:{uuid.uuid4().hex[:16]}"
    new, closed, bells = await apply_parsed(
        db, parsed, complete=complete, run_id=run_id, now=now
    )
    previous = dict(state.detail or {})
    if score is None and score_error and previous.get("secure_score") is not None:
        # Chwilowy błąd Secure Score nie gasi kafelka — zostaje ostatni pomiar.
        score = {
            "percent": previous.get("secure_score"),
            "on": previous.get("secure_score_on"),
        }
    state.detail = {
        "open": len(parsed.open_findings),
        "complete": complete,
        "skipped": parsed.skipped,
        "secure_score": score["percent"] if score else None,
        "secure_score_on": score["on"] if score else None,
        "secure_score_error": score_error,
    }
    state.last_error = None
    state.last_ok_at = now
    await db.commit()
    if new or closed or bells:
        logger.info(
            "security_defender: open=%s new=%s closed=%s bells=%s",
            len(parsed.open_findings),
            new,
            closed,
            bells,
        )
    return DefenderSyncResult(
        configured=True,
        ok=True,
        open=len(parsed.open_findings),
        new=new,
        closed=closed,
        bells=bells,
    )


async def sync_once(db: AsyncSession) -> DefenderSyncResult:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        return await sync_defender(db, client)
