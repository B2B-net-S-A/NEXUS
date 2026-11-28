"""Przyjmowanie zdarzeń i znalezisk bezpieczeństwa (0800).

Kontrakt dla źródeł (CrowdSec, Falco, Wazuh, CI) jest w
``docs/claude/ui/ekran-bezpieczenstwo.md``. Trzy wejścia, jeden zapis:

* format ogólny (``IngestBatch``) — CrowdSec przez szablon pluginu HTTP,
  krok w workflow CI, skrypt integracji Wazuha;
* natywne zdarzenie Falco z Falcosidekicka (``falco_to_event``);
* natywny alert Wazuha (``wazuh_to_event``);
* webhook Grafany (unified alerting, ``grafana_to_batch``): alert „firing”
  to znalezisko, „resolved” je zamyka.

Prywatność: repo i logi Actions są publiczne, a zdarzenia z serwera niosą
adresy atakujących i czasem loginy. ``scrub`` zamienia w każdym tekście
adresy IPv4/IPv6 i e-maile, zanim cokolwiek trafi do bazy. Z Falco i Wazuha
bierzemy tylko nazwę reguły i kontenera/agenta — nie ``output``, ``full_log``
ani ``data`` (linia poleceń bywa z sekretem).
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import SecurityEvent, SecurityFinding, SecuritySourceState

Severity = Literal["info", "low", "medium", "high", "critical"]
IngestSource = Literal[
    "crowdsec", "falco", "wazuh", "ci", "defectdojo", "pentest", "grafana"
]

MAX_EVENTS = 500
MAX_FINDINGS = 200

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Kropka po adresie to zwykle koniec zdania („Blocked 203.0.113.7.”) — odrzucamy
# tylko ciąg dalszy liczby (cyfra albo „.cyfra”), nie samą kropkę.
_IPV4 = re.compile(
    r"(?<!\d)(?<!\d\.)(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?!\d)(?!\.\d)"
)
# Kandydat na IPv6: co najmniej dwa dwukropki w ciągu znaków szesnastkowych.
_IPV6 = re.compile(
    r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:/\d{1,3})?(?![\w:])"
)
_KIND = r"^[a-z0-9_.-]{1,40}$"
_SCANNER = r"^[a-z0-9_-]{1,40}$"


def _is_ipv6(text: str) -> bool:
    try:
        ipaddress.IPv6Address(text.split("/", 1)[0])
    except ValueError:
        return False
    return True


def scrub(text: Optional[str], limit: int) -> Optional[str]:
    """Tekst bez adresów IP i e-maili, ucięty do ``limit`` znaków."""
    if text is None:
        return None
    cleaned = _EMAIL.sub("[e-mail]", text)
    cleaned = _IPV4.sub("[adres IP]", cleaned)
    cleaned = _IPV6.sub(
        lambda m: "[adres IP]" if _is_ipv6(m.group(0)) else m.group(0), cleaned
    )
    cleaned = cleaned.strip()
    return cleaned[:limit]


class IngestEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime
    kind: str = Field(pattern=_KIND)
    severity: Severity = "info"
    summary: str = Field(min_length=1, max_length=300)
    count: int = Field(default=1, ge=1, le=1_000_000)
    ref: Optional[str] = Field(default=None, min_length=1, max_length=120)

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at musi mieć strefę czasową (np. ...Z)")
        return value


class IngestFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(min_length=1, max_length=200)
    severity: Severity
    title: str = Field(min_length=1, max_length=200)
    location: Optional[str] = Field(default=None, max_length=300)
    evidence: Optional[str] = Field(default=None, max_length=2000)
    impact: Optional[str] = Field(default=None, max_length=2000)
    steps: list[str] = Field(default_factory=list, max_length=10)
    detected_at: Optional[datetime] = None

    @field_validator("steps")
    @classmethod
    def _steps(cls, value: list[str]) -> list[str]:
        if any(len(step) > 300 for step in value):
            raise ValueError("krok ma najwyżej 300 znaków")
        return value


class IngestBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: IngestSource
    scanner: Optional[str] = Field(default=None, pattern=_SCANNER)
    # Pełny skan w kilku paczkach: każda paczka biegu niesie ten sam `run_id`,
    # `complete: true` tylko ostatnia.
    run_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,80}$")
    complete: bool = False
    events: list[IngestEvent] = Field(default_factory=list, max_length=MAX_EVENTS)
    findings: list[IngestFinding] = Field(default_factory=list, max_length=MAX_FINDINGS)

    @field_validator("complete")
    @classmethod
    def _complete_needs_scanner(cls, value: bool, info: Any) -> bool:
        if value and not info.data.get("scanner"):
            raise ValueError("complete wymaga pola scanner")
        return value

    @field_validator("findings")
    @classmethod
    def _one_per_fingerprint(
        cls, value: list["IngestFinding"]
    ) -> list["IngestFinding"]:
        return dedupe_findings(value)


def dedupe_findings(findings: list[IngestFinding]) -> list[IngestFinding]:
    """Jeden wpis na odcisk (ostatni wygrywa) — skanery powtarzają to samo trafienie,
    a dwa wiersze o jednym odcisku złamałyby unikalny indeks i całą paczkę."""
    by_fingerprint: dict[str, IngestFinding] = {}
    for item in findings:
        by_fingerprint[item.fingerprint] = item
    return list(by_fingerprint.values())


@dataclass(frozen=True)
class IngestResult:
    accepted_events: int = 0
    skipped_duplicates: int = 0
    findings_new: int = 0
    findings_updated: int = 0
    findings_closed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "accepted_events": self.accepted_events,
            "skipped_duplicates": self.skipped_duplicates,
            "findings_new": self.findings_new,
            "findings_updated": self.findings_updated,
            "findings_closed": self.findings_closed,
        }


# ── Natywne formaty ──────────────────────────────────────────────────────────

_FALCO_SEVERITY: dict[str, Severity] = {
    "emergency": "critical",
    "alert": "critical",
    "critical": "critical",
    "error": "high",
    "warning": "medium",
    "notice": "low",
    "informational": "info",
    "info": "info",
    "debug": "info",
}


class FalcoEvent(BaseModel):
    """Zdarzenie z Falcosidekicka. Reszta pól (``output``…) jest ignorowana."""

    model_config = ConfigDict(extra="ignore")

    uuid: Optional[str] = Field(default=None, max_length=100)
    rule: str = Field(min_length=1, max_length=200)
    priority: str = Field(min_length=1, max_length=20)
    time: datetime
    output_fields: dict[str, Any] = Field(default_factory=dict)


def falco_to_event(event: FalcoEvent) -> IngestEvent:
    container = event.output_fields.get("container.name")
    where = (
        f" · kontener {container}" if isinstance(container, str) and container else ""
    )
    occurred = (
        event.time if event.time.tzinfo else event.time.replace(tzinfo=timezone.utc)
    )
    return IngestEvent(
        occurred_at=occurred,
        kind="runtime_alert",
        severity=_FALCO_SEVERITY.get(event.priority.strip().lower(), "medium"),
        summary=(event.rule + where)[:300],
        ref=f"falco:{event.uuid}" if event.uuid else None,
    )


class WazuhRule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: int = Field(ge=0, le=16)
    description: str = Field(min_length=1, max_length=300)
    id: Optional[str] = Field(default=None, max_length=20)
    groups: list[str] = Field(default_factory=list)


class WazuhAgent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(default=None, max_length=100)


class WazuhAlert(BaseModel):
    """Alert Wazuha z integracji. ``full_log``, ``data``, ``srcip`` są pomijane."""

    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = Field(default=None, max_length=60)
    timestamp: datetime
    rule: WazuhRule
    agent: WazuhAgent = Field(default_factory=WazuhAgent)


def wazuh_severity(level: int) -> Severity:
    if level <= 3:
        return "info"
    if level <= 6:
        return "low"
    if level <= 9:
        return "medium"
    if level <= 12:
        return "high"
    return "critical"


def _wazuh_kind(groups: list[str]) -> str:
    joined = {g.lower() for g in groups}
    if joined & {"syscheck", "syscheck_file", "syscheck_entry_modified"}:
        return "fim_change"
    if joined & {"authentication_failed", "authentication_failures", "invalid_login"}:
        return "auth_failure"
    if "vulnerability-detector" in joined:
        return "vuln_detected"
    return "rule_alert"


def wazuh_to_event(alert: WazuhAlert) -> IngestEvent:
    agent = f" · {alert.agent.name}" if alert.agent.name else ""
    occurred = (
        alert.timestamp
        if alert.timestamp.tzinfo
        else alert.timestamp.replace(tzinfo=timezone.utc)
    )
    return IngestEvent(
        occurred_at=occurred,
        kind=_wazuh_kind(alert.rule.groups),
        severity=wazuh_severity(alert.rule.level),
        summary=(alert.rule.description + agent)[:300],
        ref=f"wazuh:{alert.id}" if alert.id else None,
    )


class GrafanaAlert(BaseModel):
    """Jeden alert z webhooka Grafany. Wartości ``labels`` poza nazwą reguły,
    folderem i wagą nie są czytane — bywa w nich instancja, adres albo login."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: Optional[datetime] = None
    # Grafana liczy odcisk z etykiet (16 znaków szesnastkowych) — ten sam alert
    # w powtórce co kilka minut ma ten sam odcisk.
    fingerprint: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")


class GrafanaWebhook(BaseModel):
    """Ciało webhooka kontaktu Grafany. Reszta pól (``receiver``,
    ``commonLabels``, ``message``…) jest ignorowana."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    alerts: list[GrafanaAlert] = Field(default_factory=list, max_length=MAX_FINDINGS)


_GRAFANA_SEVERITY: dict[str, Severity] = {
    "critical": "high",
    "high": "high",
    "warning": "medium",
}


def grafana_severity(labels: dict[str, str]) -> Severity:
    return _GRAFANA_SEVERITY.get(labels.get("severity", "").strip().lower(), "low")


def _grafana_where(alert: GrafanaAlert) -> Optional[str]:
    """Folder reguły; źródło „Grafana” ekran pokazuje osobnym chipem."""
    folder = alert.labels.get("grafana_folder", "").strip()
    return f"folder {folder}" if folder else None


@dataclass(frozen=True)
class GrafanaIngest:
    batch: IngestBatch
    resolved: list[str]


def grafana_to_batch(payload: GrafanaWebhook) -> GrafanaIngest:
    """Firing → znalezisko o kluczu z ``fingerprint`` i zdarzenie; resolved →
    zdarzenie i odcisk do zamknięcia. Ref zdarzenia z odcisku, początku alertu
    i stanu, więc powtórka webhooka nie dubluje strumienia."""
    events: list[IngestEvent] = []
    findings: list[IngestFinding] = []
    resolved: list[str] = []
    for alert in payload.alerts:
        rule = (alert.labels.get("alertname") or "").strip() or "Alert Grafany"
        where = _grafana_where(alert)
        summary = (alert.annotations.get("summary") or "").strip() or None
        severity = grafana_severity(alert.labels)
        started = (
            alert.startsAt
            if alert.startsAt.tzinfo
            else alert.startsAt.replace(tzinfo=timezone.utc)
        )
        firing = alert.status == "firing"
        ended = alert.endsAt if alert.endsAt and alert.endsAt.year > 1 else None
        if ended is not None and ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)
        events.append(
            IngestEvent(
                occurred_at=started if firing else (ended or started),
                kind="alert_firing" if firing else "alert_resolved",
                severity=severity if firing else "info",
                summary=(f"{rule} · {where}" + ("" if firing else " — ustąpił"))[:300],
                ref=(
                    f"grafana:{alert.fingerprint}:{int(started.timestamp())}:"
                    f"{alert.status}"
                ),
            )
        )
        if firing:
            findings.append(
                IngestFinding(
                    fingerprint=alert.fingerprint,
                    severity=severity,
                    title=rule[:200],
                    location=where[:300] if where else None,
                    evidence=summary[:2000] if summary else None,
                    steps=[
                        "Otwórz regułę w Grafanie i sprawdź przyczynę",
                        "Gdy alert ustąpi, znalezisko zamknie się samo",
                    ],
                    detected_at=started,
                )
            )
        else:
            resolved.append(alert.fingerprint)
    # Ten sam odcisk jako firing i resolved w jednej paczce: wygrywa resolved.
    gone = set(resolved)
    findings = [f for f in findings if f.fingerprint not in gone]
    return GrafanaIngest(
        IngestBatch(
            source="grafana", scanner="grafana", events=events, findings=findings
        ),
        resolved,
    )


# ── Zapis ────────────────────────────────────────────────────────────────────


async def store_events(
    db: AsyncSession,
    source: str,
    events: list[IngestEvent],
    *,
    service_account_id: Optional[int] = None,
    links: Optional[dict[str, str]] = None,
) -> tuple[int, int]:
    """Wstawia zdarzenia; ten sam ``(source, ref)`` drugi raz jest pomijany.

    ``links`` (ref → adres) tylko z kodu NEXUSA (bieg w GitHub Actions);
    źródła zewnętrzne linków nie przysyłają.
    """
    links = links or {}
    if not events:
        return 0, 0
    rows = [
        {
            "source": source,
            "kind": e.kind,
            "severity": e.severity,
            "summary": scrub(e.summary, 300) or "—",
            "count": e.count,
            "ref": e.ref,
            "link": links.get(e.ref) if e.ref else None,
            "occurred_at": e.occurred_at,
            "service_account_id": service_account_id,
        }
        for e in events
    ]
    stmt = (
        pg_insert(SecurityEvent)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["source", "ref"], index_where=SecurityEvent.ref.isnot(None)
        )
        .returning(SecurityEvent.id)
    )
    inserted = len((await db.execute(stmt)).all())
    return inserted, len(rows) - inserted


async def upsert_findings(
    db: AsyncSession,
    source: str,
    findings: list[IngestFinding],
    *,
    scanner: Optional[str] = None,
    complete: bool = False,
    run_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> tuple[int, int, int]:
    """Nowe znaleziska, aktualizacja znanych, zamknięcie nieobecnych w pełnym skanie.

    Status ustawiony w NEXUSIE (wyjątek, właściciel) zostaje. Znalezisko
    zamknięte jako naprawione, które wraca w skanie, otwiera się ponownie.
    Z ``run_id`` pełny skan zamyka to, czego nie przyniosła żadna paczka tego
    biegu; bez niego — to, czego nie ma w tej paczce.
    """
    now = now or datetime.now(timezone.utc)
    findings = dedupe_findings(findings)
    new = updated = 0
    fingerprints = [f.fingerprint for f in findings]
    existing: dict[str, SecurityFinding] = {}
    if fingerprints:
        rows = await db.scalars(
            select(SecurityFinding).where(
                SecurityFinding.source == source,
                SecurityFinding.fingerprint.in_(fingerprints),
            )
        )
        existing = {row.fingerprint: row for row in rows}
    for item in findings:
        fields = {
            "severity": item.severity,
            "title": scrub(item.title, 200) or item.fingerprint[:200],
            "location": scrub(item.location, 300),
            "evidence": scrub(item.evidence, 2000),
            "impact": scrub(item.impact, 2000),
            "steps": [scrub(step, 300) for step in item.steps],
            "last_seen_at": now,
            "last_run_id": run_id,
            "updated_at": now,
        }
        row = existing.get(item.fingerprint)
        if row is None:
            db.add(
                SecurityFinding(
                    source=source,
                    scanner=scanner,
                    fingerprint=item.fingerprint,
                    status="open",
                    first_seen_at=item.detected_at or now,
                    **fields,
                )
            )
            new += 1
            continue
        for key, value in fields.items():
            setattr(row, key, value)
        if scanner:
            row.scanner = scanner
        if row.status == "fixed":
            row.status = "open"
            row.closed_at = None
            row.closed_by_user_id = None
            row.closed_note = None
        updated += 1
    closed = 0
    if complete and scanner:
        await db.flush()
        missing = (
            SecurityFinding.last_run_id.is_distinct_from(run_id)
            if run_id
            else (
                SecurityFinding.fingerprint.notin_(fingerprints)
                if fingerprints
                else true()
            )
        )
        result = await db.execute(
            update(SecurityFinding)
            .where(
                SecurityFinding.source == source,
                SecurityFinding.scanner == scanner,
                SecurityFinding.status != "fixed",
                missing,
            )
            .values(
                status="fixed",
                closed_at=now,
                closed_note="Nie ma go w pełnym skanie",
                updated_at=func.now(),
            )
        )
        closed = result.rowcount or 0
    await db.flush()
    return new, updated, closed


async def resolve_findings(
    db: AsyncSession,
    source: str,
    fingerprints: list[str],
    *,
    note: str,
    now: Optional[datetime] = None,
) -> int:
    """Źródło mówi, że problem ustąpił — zamyka znalezisko, także z wyjątkiem."""
    if not fingerprints:
        return 0
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(SecurityFinding)
        .where(
            SecurityFinding.source == source,
            SecurityFinding.fingerprint.in_(fingerprints),
            SecurityFinding.status != "fixed",
        )
        .values(
            status="fixed",
            closed_at=now,
            closed_note=note,
            last_seen_at=now,
            updated_at=func.now(),
        )
    )
    return result.rowcount or 0


class SourceOwnedByOtherAccount(Exception):
    """Źródło jest przypięte do innego, aktywnego konta serwisowego."""


async def claim_source(db: AsyncSession, source: str, service_account_id: int) -> None:
    """Pierwsze konto, które pisze do źródła, dostaje je na wyłączność.

    Bo klucz Falco leży w pliku na serwerze NEXUSA, a bez przypięcia mógłby
    nadpisać znaleziska DefectDojo albo zamknąć je pustym pełnym skanem.
    Wyłączone albo usunięte konto zwalnia źródło (rotacja kluczy zostaje
    w tym samym koncie, więc jej to nie dotyczy).
    """
    from app.models.service_account import ServiceAccount  # noqa: PLC0415

    await db.execute(
        pg_insert(SecuritySourceState)
        .values(source=source, detail={})
        .on_conflict_do_nothing(index_elements=["source"])
    )
    state = await db.scalar(
        select(SecuritySourceState)
        .where(SecuritySourceState.source == source)
        .with_for_update()
    )
    owner = state.owner_service_account_id
    if owner is not None and owner != service_account_id:
        owner_active = await db.scalar(
            select(ServiceAccount.is_active).where(ServiceAccount.id == owner)
        )
        if owner_active:
            raise SourceOwnedByOtherAccount(source)
    state.owner_service_account_id = service_account_id


async def mark_source_seen(db: AsyncSession, source: str) -> None:
    """Źródło się odezwało — także pustą paczką (timer DefectDojo bez zmian)."""
    now = datetime.now(timezone.utc)
    stmt = pg_insert(SecuritySourceState).values(
        source=source, last_ok_at=now, detail={}
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["source"], set_={"last_ok_at": now, "last_error": None}
        )
    )


async def ingest_batch(
    db: AsyncSession,
    batch: IngestBatch,
    *,
    service_account_id: Optional[int] = None,
    resolved: Optional[list[str]] = None,
) -> IngestResult:
    if service_account_id is not None:
        await claim_source(db, batch.source, service_account_id)
    accepted, skipped = await store_events(
        db, batch.source, batch.events, service_account_id=service_account_id
    )
    new, updated, closed = await upsert_findings(
        db,
        batch.source,
        batch.findings,
        scanner=batch.scanner,
        complete=batch.complete,
        run_id=batch.run_id,
    )
    closed += await resolve_findings(
        db, batch.source, resolved or [], note="Źródło zgłosiło, że problem ustąpił"
    )
    await mark_source_seen(db, batch.source)
    await db.commit()
    return IngestResult(accepted, skipped, new, updated, closed)
