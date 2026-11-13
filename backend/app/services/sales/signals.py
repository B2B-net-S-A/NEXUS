"""Kanał sygnałów z bota researchu (Grok Bot): bieg, token, przyjęcie raportu.

NEXUS zakłada bieg z listą firm i jednorazowym tokenem, wysyła botowi same nazwy
i domeny firm (komputery bota stoją w USA) i czeka na jeden raport pod
``POST /api/integrations/sales-signals/runs/{id}``. Raport to dane niezaufane:
bot czyta cudze strony, więc pola są stałe, z limitami, linki tylko http(s),
firma tylko z listy biegu i żadnych automatycznych działań poza zapisem leada
i punktów do rozmowy. Decyzję, czy dzwonić, podejmuje handlowiec.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_date
from app.models.sales import (
    SalesCompany,
    SalesCompanyBriefing,
    SalesLead,
    SalesSignalRun,
)
from app.services.sales import client_gate
from app.services.sales.companies import http_url, mail_domain

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TOKEN_TTL = timedelta(hours=2)
MAX_SIGNALS = 50
MAX_POINTS = 4
MAX_FIRMS = 200
#: Sygnał starszy niż okno nie jest „teraz”; próba z 09.11 liczyła 120 dni.
SIGNAL_WINDOW_DAYS = 120
LEAD_SOURCE = "research"
ORIGIN = "grok"
STRENGTH_SCORE: dict[str, int] = {"strong": 85, "medium": 60, "weak": 30}
SIGNAL_TYPES: tuple[str, ...] = (
    "hiring",
    "restructuring",
    "program",
    "contract",
    "investment",
    "leadership",
    "other",
)
#: Powody odrzucenia na ekranie; wracają do bota w następnym biegu.
REJECT_REASONS: tuple[str, ...] = (
    "Nieaktualne",
    "Nie nasza usługa",
    "Już wiemy",
    "Słabe źródło",
    "Inna firma",
)
INVALID_TOKEN_DETAIL = "Nieważny token biegu."


def enabled() -> bool:
    return bool(settings.SALES_SIGNALS_ENABLED)


def configured(kind: Optional[str] = None) -> bool:
    """Webhook gotowy: dla rodzaju jego bota, bez rodzaju choć jednego bota
    poza Cognism (własna para albo wspólna, ``bots.webhook``)."""

    from app.services.sales import bots

    if kind is not None:
        bot = bots.bot_for(kind)
        return bot is not None and all(bots.webhook(bot))
    return any(all(bots.webhook(bot)) for bot in bots.BOTS if bot != bots.COGNISM)


def people_enabled() -> bool:
    return bool(settings.SALES_COGNISM_PEOPLE_ENABLED)


def people_configured() -> bool:
    return bool(
        settings.GROK_BOT_PEOPLE_WEBHOOK_URL and settings.GROK_BOT_PEOPLE_WEBHOOK_KEY
    )


# ── Raport bota ──────────────────────────────────────────────────────────


def _clean(value: str) -> str:
    """Bez znaków sterujących i nadmiarowych spacji; tekst idzie wprost na ekran."""

    text = "".join(ch if ch.isprintable() or ch == "\n" else " " for ch in value)
    return " ".join(part for part in text.replace("\n", " ").split(" ") if part)


MAX_URL = 1000


def _required_url(value: str) -> str:
    url = http_url(value)
    if not url:
        raise ValueError("Wymagany adres http(s) źródła.")
    # Długość dopiero po dopisaniu „https://” do gołej domeny: kolumna ma 1000 znaków.
    if len(url) > MAX_URL:
        raise ValueError("Adres źródła jest za długi.")
    return url


def _required_text(value: str) -> str:
    """``min_length`` liczy przed czyszczeniem, więc pusty wynik sprawdzamy tutaj:
    inaczej CHECK tytułu w bazie zwraca 500 i przepada cały raport."""

    cleaned = _clean(value)
    if not cleaned:
        raise ValueError("Pole nie może być puste.")
    return cleaned


class ReportSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ref: int
    type: Literal[SIGNAL_TYPES]  # type: ignore[valid-type]
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=1500)
    why_now: str = Field(default="", max_length=800)
    url: str = Field(min_length=1, max_length=1000)
    published: date
    strength: Literal["strong", "medium", "weak"]

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _required_url(value)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("summary", "why_now")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)


class ReportPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=400)
    url: Optional[str] = Field(default=None, max_length=1000)
    published: Optional[date] = None

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("url")
    @classmethod
    def _url(cls, value: Optional[str]) -> Optional[str]:
        return _required_url(value) if value else None


class ReportBriefing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ref: int
    points: list[ReportPoint] = Field(min_length=1, max_length=MAX_POINTS)


class RunReport(BaseModel):
    """Jeden raport na bieg. Pola osób nie istnieją, więc ich nie przyjmiemy."""

    model_config = ConfigDict(extra="forbid")

    checked_firms: int = Field(ge=0, le=MAX_FIRMS)
    signals: list[ReportSignal] = Field(default_factory=list, max_length=MAX_SIGNALS)
    briefings: list[ReportBriefing] = Field(default_factory=list, max_length=MAX_FIRMS)
    no_signal: list[int] = Field(default_factory=list, max_length=MAX_FIRMS)


# ── Token biegu ──────────────────────────────────────────────────────────


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(run: SalesSignalRun, token: Optional[str], now: datetime) -> bool:
    """Token tylko dla tego biegu, tylko raz i tylko przed wygaśnięciem."""

    if not token or run.status != "started" or not run.token_hash:
        return False
    if run.token_expires_at is None or run.token_expires_at <= now:
        return False
    return hmac.compare_digest(run.token_hash, hash_token(token))


def new_run(
    kind: str,
    company_ids: list[int],
    *,
    now: datetime,
    modes: Optional[dict[int, str]] = None,
    request: Optional[dict[str, Any]] = None,
    requested_by_user_id: Optional[int] = None,
) -> tuple[SalesSignalRun, str]:
    token = secrets.token_urlsafe(32)
    run = SalesSignalRun(
        kind=kind,
        status="started",
        company_ids=sorted(set(company_ids)),
        modes={str(k): v for k, v in (modes or {}).items()},
        request=dict(request or {}),
        requested_by_user_id=requested_by_user_id,
        token_hash=hash_token(token),
        token_expires_at=now + TOKEN_TTL,
        started_at=now,
    )
    return run, token


# ── Plan przyjęcia (bez bazy, żeby dało się go przetestować) ─────────────


@dataclass(frozen=True)
class CompanyInfo:
    id: int
    name: str
    owner_user_id: Optional[int]


@dataclass
class IntakePlan:
    leads: list[dict[str, Any]] = field(default_factory=list)
    briefings: list[dict[str, Any]] = field(default_factory=list)
    outside_window: list[dict[str, str]] = field(default_factory=list)
    nexus_clients: list[dict[str, Optional[str]]] = field(default_factory=list)
    unknown_company: int = 0
    duplicates: int = 0


def fingerprint(company_id: int, url: str) -> str:
    digest = hashlib.sha256(f"{company_id}|{url.lower()}".encode()).hexdigest()
    return f"{LEAD_SOURCE}|{digest[:48]}"


def _domain(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def plan_intake(
    run: SalesSignalRun,
    report: RunReport,
    companies: dict[int, CompanyInfo],
    clients: dict[int, client_gate.ClientMatch],
    *,
    today: date,
) -> IntakePlan:
    """Co z raportu trafi do bazy, a co i dlaczego odpada."""

    allowed = {int(ref) for ref in run.company_ids}
    plan = IntakePlan()
    seen: set[str] = set()
    oldest = today - timedelta(days=SIGNAL_WINDOW_DAYS)
    for signal in report.signals:
        company = companies.get(signal.company_ref)
        if signal.company_ref not in allowed or company is None:
            plan.unknown_company += 1
            continue
        if signal.published < oldest or signal.published > today + timedelta(days=1):
            plan.outside_window.append(
                {
                    "company": company.name,
                    "title": signal.title,
                    "published": signal.published.isoformat(),
                }
            )
            continue
        match = clients.get(company.id)
        if match is not None:
            plan.nexus_clients.append(
                {
                    "company": company.name,
                    "client": match.client_name,
                    "delivery_lead": match.delivery_lead,
                }
            )
            continue
        key = fingerprint(company.id, signal.url)
        if key in seen:
            plan.duplicates += 1
            continue
        seen.add(key)
        plan.leads.append(
            {
                "source": LEAD_SOURCE,
                "title": signal.title,
                "summary": signal.summary or None,
                "company_name": company.name,
                "company_id": company.id,
                "url": signal.url,
                "score": STRENGTH_SCORE[signal.strength],
                "signal_at": datetime.combine(
                    signal.published, time(12), tzinfo=timezone.utc
                ),
                "fingerprint": key,
                "assignee_user_id": company.owner_user_id,
                "payload": {
                    "origin": ORIGIN,
                    "run_id": run.id,
                    "type": signal.type,
                    "strength": signal.strength,
                    "why_now": signal.why_now,
                    "published": signal.published.isoformat(),
                    "domain": _domain(signal.url),
                },
            }
        )
    for briefing in report.briefings:
        if briefing.company_ref not in allowed or briefing.company_ref not in companies:
            plan.unknown_company += 1
            continue
        plan.briefings.append(
            {
                "company_id": briefing.company_ref,
                "mode": (run.modes or {}).get(str(briefing.company_ref), "first_call"),
                "points": [
                    {
                        "text": point.text,
                        "url": point.url,
                        "published": point.published.isoformat()
                        if point.published
                        else None,
                    }
                    for point in briefing.points
                ],
                "run_id": run.id,
            }
        )
    if run.kind == "briefing":
        # Firma ``ongoing`` z ``no_signal``: bot sprawdził i nic nowego nie znalazł.
        # Pusty wiersz to odpowiedź (przy ofercie „Do decyzji” ekran mówi to wprost),
        # a nie brak biegu; po 6 dniach firma wraca do bota jak każda inna.
        briefed = {values["company_id"] for values in plan.briefings}
        for ref in report.no_signal:
            if (
                ref in allowed
                and ref in companies
                and ref not in briefed
                and (run.modes or {}).get(str(ref)) == "ongoing"
            ):
                briefed.add(ref)
                plan.briefings.append(
                    {
                        "company_id": ref,
                        "mode": "ongoing",
                        "points": [],
                        "run_id": run.id,
                    }
                )
    return plan


# ── Zapis ────────────────────────────────────────────────────────────────


async def _companies(db: AsyncSession, ids: list[int]) -> dict[int, SalesCompany]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(SalesCompany).where(
                SalesCompany.id.in_(ids), SalesCompany.archived_at.is_(None)
            )
        )
    ).scalars()
    return {company.id: company for company in rows}


async def ingest(
    db: AsyncSession, run: SalesSignalRun, report: RunReport, *, now: datetime
) -> dict[str, Any]:
    """Zapisz raport biegu. Lead nie nadpisuje statusu, który ustawił handlowiec."""

    refs = (
        {s.company_ref for s in report.signals}
        | {b.company_ref for b in report.briefings}
        | set(report.no_signal)
    )
    rows = await _companies(db, sorted(refs & {int(r) for r in run.company_ids}))
    companies = {
        cid: CompanyInfo(id=cid, name=c.name, owner_user_id=c.owner_user_id)
        for cid, c in rows.items()
    }
    signal_ids = {s.company_ref for s in report.signals if s.company_ref in rows}
    clients = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=cid,
                client_id=rows[cid].client_id,
                normalized_name=rows[cid].normalized_name,
            )
            for cid in sorted(signal_ids)
        ],
    )
    plan = plan_intake(run, report, companies, clients, today=business_date(now))

    new = 0
    for values in plan.leads:
        statement = insert(SalesLead).values(**values, status="new")
        statement = statement.on_conflict_do_update(
            constraint="uq_sales_leads_fingerprint",
            set_={
                "title": statement.excluded.title,
                "summary": statement.excluded.summary,
                "score": statement.excluded.score,
                "signal_at": statement.excluded.signal_at,
                "payload": statement.excluded.payload,
                "updated_at": now,
            },
        ).returning(literal_column("(xmax = 0)"))
        # ``xmax = 0`` tylko w wierszu właśnie wstawionym, nie w zaktualizowanym.
        new += int(bool((await db.execute(statement)).scalar_one()))
    for values in plan.briefings:
        statement = insert(SalesCompanyBriefing).values(**values, generated_at=now)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["company_id"],
                set_={
                    "mode": statement.excluded.mode,
                    "points": statement.excluded.points,
                    "run_id": statement.excluded.run_id,
                    "generated_at": now,
                },
            )
        )

    quiet_ids = sorted({ref for ref in report.no_signal if ref in rows})
    summary = {
        "checked_firms": report.checked_firms,
        "sent_firms": len(run.company_ids),
        "researched_company_ids": sorted(rows),
        "signals_in": len(report.signals),
        "leads": len(plan.leads),
        "leads_new": new,
        "by_strength": {
            strength: sum(
                1 for lead in plan.leads if lead["payload"]["strength"] == strength
            )
            for strength in STRENGTH_SCORE
        },
        "briefings": len(plan.briefings),
        "quiet": [rows[ref].name for ref in quiet_ids if ref in rows],
        "dropped": {
            "outside_window": plan.outside_window,
            "nexus_clients": plan.nexus_clients,
            "unknown_company": plan.unknown_company,
            "duplicates": plan.duplicates,
        },
    }
    run.status = "received"
    run.received_at = now
    run.token_hash = None
    run.report = summary
    # Logi są publiczne: same liczby.
    logger.info(
        "sales_signals run=%s kind=%s received signals=%d leads=%d new=%d briefings=%d "
        "window=%d clients=%d unknown=%d",
        run.id,
        run.kind,
        len(report.signals),
        len(plan.leads),
        new,
        len(plan.briefings),
        len(plan.outside_window),
        len(plan.nexus_clients),
        plan.unknown_company,
    )
    return summary


# ── Start biegu ──────────────────────────────────────────────────────────


def callback_url(run_id: int) -> str:
    base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/api/integrations/sales-signals/runs/{run_id}"


def feedback_from_rows(rows: Any) -> dict[str, Any]:
    """Powody odrzuceń i znane linki dla bota.

    Powód idzie tylko z listy ``REJECT_REASONS``: API przyjmuje dowolny tekst, a to,
    co trafia do bota, wychodzi poza UE, więc wpis z nazwiskiem albo telefonem nie
    może tam wyjść.
    """

    rejected = [
        {"ref": cid, "title": title, "reason": reason}
        for cid, title, _url, status, reason in rows
        if status == "dismissed" and reason in REJECT_REASONS
    ][:50]
    seen_urls = sorted({url for _cid, _t, url, _s, _r in rows if url})[:200]
    return {"rejected": rejected, "seen_urls": seen_urls}


async def _feedback(db: AsyncSession, company_ids: list[int]) -> dict[str, Any]:
    """Powody odrzuceń i znane adresy: bot nie powtarza tego, co już mamy."""

    rows = (
        await db.execute(
            select(
                SalesLead.company_id,
                SalesLead.title,
                SalesLead.url,
                SalesLead.status,
                SalesLead.dismissed_reason,
            )
            .where(
                SalesLead.source == LEAD_SOURCE,
                SalesLead.company_id.in_(company_ids),
            )
            .order_by(SalesLead.updated_at.desc())
            .limit(300)
        )
    ).all()
    return feedback_from_rows(rows)


def webhook_body(
    run: SalesSignalRun,
    token: str,
    companies: list[SalesCompany],
    feedback: dict[str, Any],
) -> dict[str, Any]:
    """Treść dla bota: nazwy, domeny, NIP i KRS firm, bez osób, CV i kontaktów.

    v2 (0684) dokłada ``task`` i ``report_format`` z rejestru zadań oraz ``request``
    biegu, czyli pola, które rodzaj sam wysyła botowi. Pola v1 zostają, bo rutyna
    z poleceniem v1 dalej obsługuje ``signals`` i ``briefing``.
    """

    from app.services.sales import bot_tasks

    task = bot_tasks.for_run(run)
    if task is None:
        raise ValueError("Nieznany rodzaj zadania bota.")
    modes = run.modes or {}
    request = dict(run.request or {})
    cognism = run.kind == "people" and request.get("source") == "cognism"
    firms = [
        {
            "ref": company.id,
            "name": company.name,
            "domain": (
                mail_domain(company.domain) or mail_domain(company.website_url)
                if cognism
                else company.domain or None
            ),
            **(
                {"legal_name": company.legal_name}
                if cognism and company.legal_name
                else {}
            ),
            # NIP i KRS firmy mogą iść do bota (decyzja Artura 13.11.2026):
            # identyfikatory firm, publiczne w KRS, bez danych osób.
            **({"nip": company.nip} if company.nip else {}),
            **({"krs": company.krs} if company.krs else {}),
            **({"mode": modes[str(company.id)]} if str(company.id) in modes else {}),
        }
        for company in companies
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.id,
        "kind": run.kind,
        "callback_url": callback_url(run.id),
        "token": token,
        "expires_at": run.token_expires_at.isoformat()
        if run.token_expires_at
        else None,
        "window_days": SIGNAL_WINDOW_DAYS,
        "max_signals": MAX_SIGNALS,
        "max_points": MAX_POINTS,
        "signal_types": list(SIGNAL_TYPES),
        "firms": firms,
        **feedback,
        "task": task.task_text(
            run, bot_tasks.TaskContext(firms=tuple(firms), request=request)
        ),
        "report_format": task.report_format(),
        "request": request,
    }


async def start_run(
    db: AsyncSession,
    kind: str,
    company_ids: list[int],
    *,
    now: Optional[datetime] = None,
    modes: Optional[dict[int, str]] = None,
    client: Optional[httpx.AsyncClient] = None,
    request: Optional[dict[str, Any]] = None,
    requested_by_user_id: Optional[int] = None,
) -> Optional[SalesSignalRun]:
    """Załóż bieg i wywołaj webhook bota. Bez firm albo konfiguracji: nic.

    Rodzaj spoza rejestru zadań i rodzaj inny niż ``signals``/``briefing`` przy
    wyłączonym ``SALES_BOT_TASKS_ENABLED``: nic. ``request`` sprawdza model rodzaju
    (``BotTask.request_model``); niedozwolone pola to ``ValueError``.
    """

    from app.services.sales import bot_tasks, bots

    task = bot_tasks.get(kind)
    if task is None:
        return None
    cognism = kind == "people" and (request or {}).get("source") == "cognism"
    if not (people_enabled() if cognism else bot_tasks.allowed_to_start(kind)):
        return None
    checked_request = task.validate_request(request)
    # Każdy rodzaj należy do jednego z czterech botów (13.11.2026): własny
    # webhook bota albo wspólny; bot wstrzymany na ekranie Boty nie startuje.
    bot = bots.bot_for(kind, request)
    if bot is None:
        return None
    webhook_url, webhook_key = bots.webhook(bot)
    if not (webhook_url and webhook_key):
        return None
    if await bots.is_paused(db, bot):
        logger.info("sales_signals kind=%s bot=%s paused", kind, bot)
        return None
    moment = now or datetime.now(timezone.utc)
    rows = await _companies(db, company_ids[:MAX_FIRMS])
    if task.needs_firms and not rows:
        return None
    if cognism and any(
        firm["company_ref"] not in rows for firm in checked_request.get("employers", [])
    ):
        raise ValueError("Potwierdzona firma Cognism nie należy do biegu.")
    run, token = new_run(
        kind,
        list(rows),
        now=moment,
        modes=modes,
        request=checked_request,
        requested_by_user_id=requested_by_user_id,
    )
    db.add(run)
    await db.flush()
    feedback = (
        await _feedback(db, list(rows))
        if task.lead_feedback
        else {"rejected": [], "seen_urls": []}
    )
    body = webhook_body(run, token, [rows[cid] for cid in sorted(rows)], feedback)
    await db.commit()
    run_id = run.id
    headers = {"Authorization": f"Bearer {webhook_key}"}
    error: Optional[str] = None
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=20.0) as own:
                response = await own.post(webhook_url, json=body, headers=headers)
        else:
            response = await client.post(webhook_url, json=body, headers=headers)
        response.raise_for_status()
    except httpx.TimeoutException:
        # Nie wiadomo, czy bot dostał zlecenie: bieg zostaje otwarty z tokenem,
        # a bez raportu zamknie go ``expire_runs`` po terminie tokenu.
        logger.warning("sales_signals run=%s kind=%s webhook timeout", run_id, kind)
    except httpx.HTTPStatusError as exc:
        error = f"webhook HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        error = f"webhook {type(exc).__name__}"[:255]
    if error is not None:
        await _close_open_run(db, run_id, status="failed", error=error)
        logger.warning("sales_signals run=%s kind=%s failed: %s", run_id, kind, error)
    await db.refresh(run)
    logger.info(
        "sales_signals run=%s kind=%s firms=%d status=%s",
        run_id,
        kind,
        len(rows),
        run.status,
    )
    return run


async def _close_open_run(
    db: AsyncSession, run_id: int, *, status: str, error: str
) -> bool:
    """Zamknij bieg tylko, gdy wciąż czeka: raport przyjęty w międzyczasie wygrywa."""

    result = await db.execute(
        update(SalesSignalRun)
        .where(SalesSignalRun.id == run_id, SalesSignalRun.status == "started")
        .values(status=status, token_hash=None, error=error)
    )
    await db.commit()
    return bool(result.rowcount)


async def expire_runs(db: AsyncSession, *, now: datetime) -> int:
    """Bieg bez raportu po terminie tokenu: ``expired`` i ostrzeżenie w logu."""

    rows = (
        await db.execute(
            update(SalesSignalRun)
            .where(
                SalesSignalRun.status == "started",
                SalesSignalRun.token_expires_at < now,
            )
            .values(status="expired", token_hash=None, error="brak raportu")
            .returning(SalesSignalRun.id, SalesSignalRun.kind)
        )
    ).all()
    await db.commit()
    for run_id, kind in rows:
        logger.warning(
            "sales_signals run=%s kind=%s expired without report", run_id, kind
        )
    return len(rows)


# ── „Mój dzień”: nowe sygnały osoby ──────────────────────────────────────

MY_DAY_LIMIT = 3
MY_DAY_WITHIN = timedelta(days=14)


async def my_day_signals(
    db: AsyncSession, user_id: int, *, now: datetime
) -> list[SalesLead]:
    """Najwyżej trzy nowe sygnały z ostatnich 14 dni: przypisane do osoby albo
    przy firmie, której jest opiekunem. Słaby sygnał też, ale oznaczony na ekranie."""

    if not enabled():
        return []
    rows = await db.execute(
        select(SalesLead)
        .outerjoin(SalesCompany, SalesCompany.id == SalesLead.company_id)
        .where(
            SalesLead.source == LEAD_SOURCE,
            SalesLead.status == "new",
            SalesLead.created_at >= now - MY_DAY_WITHIN,
            (SalesLead.assignee_user_id == user_id)
            | (SalesCompany.owner_user_id == user_id),
        )
        .order_by(
            SalesLead.score.desc(),
            SalesLead.signal_at.desc().nulls_last(),
            SalesLead.id.desc(),
        )
        .limit(MY_DAY_LIMIT)
    )
    return list(rows.scalars())
