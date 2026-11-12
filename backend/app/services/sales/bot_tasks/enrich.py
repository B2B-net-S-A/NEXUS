"""Rodzaj ``enrich`` (G-A): bot proponuje brakujące pola karty firmy.

Do bota idzie to samo co zawsze: nazwa i domena firmy (``firms``), bez pól
``request``. Bot odsyła na firmę: domenę, stronę www, NIP, miasto siedziby,
branżę, przedział liczby pracowników i nazwę spółki matki, każde pole z własnym
źródłem. Nic nie trafia na kartę samo: wynik czeka w ``sales_bot_results``
(jeden wiersz na firmę), a handlowiec przyjmuje pola po kolei
(``POST /api/sales/bot-results/{id}/accept {fields, reject}``).

Przyjęcie idzie tą samą ścieżką zapisu co ekran Firmy (``companies.apply_fields``).
Domena albo NIP z innej karty to odmowa z nazwą tamtej karty (scalenie kart to
osobny krok, B6). Spółka matka staje się powiązaniem tylko wtedy, gdy pasuje
dokładnie jedna karta po nazwie kanonicznej.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Uzupełnianie kart”).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesOpportunity,
    SalesSignalRun,
)
from app.services.company_names import normalize_company_name
from app.services.order_client_identity import nip_checksum_valid
from app.services.sales import companies as company_service
from app.services.sales import signals
from app.services.sales.bot_tasks.base import (
    AcceptRefused,
    BotTask,
    CleanText,
    SourceUrl,
    TaskContext,
    result_fingerprint,
    save_results,
)
from app.services.sales.task_scope import live_opportunity

KIND = "enrich"

#: Pola karty, które bot może zaproponować, w kolejności na ekranie.
FIELDS: tuple[str, ...] = (
    "domain",
    "website_url",
    "nip",
    "hq_city",
    "industry",
    "tier",
    "parent_name",
)
#: Przedział liczby pracowników od bota → wielkość karty (``tier``).
#: „Strategiczna” to decyzja handlowa, nie wielkość, więc bot jej nie proponuje.
SIZE_TO_TIER: dict[str, str] = {
    "1-49": "smb",
    "50-249": "smb",
    "250-999": "mid_market",
    "1000+": "enterprise",
}
SIZE_BUCKETS = tuple(SIZE_TO_TIER)
#: Limity jak kolumny ``sales_companies``.
MAX_LEN: dict[str, int] = {
    "website_url": 500,
    "hq_city": 120,
    "industry": 255,
    "parent_name": 500,
}

#: Przycisk na karcie: ta sama firma nie wraca do bota przez 2 godziny (token żyje tyle).
MANUAL_COOLDOWN = timedelta(hours=2)
#: Noc: karty z opiekunem albo otwartą szansą i bez domeny.
NIGHT_HOURS = (1, 6)
NIGHT_BATCH = 20
NIGHT_MAX_RUNS = 5
NIGHT_EVERY = timedelta(hours=1)
#: Karta sprawdzona nocą nie wraca przez 30 dni, żeby noc nie męczyła tych samych firm.
NIGHT_RESEND_AFTER = timedelta(days=30)

ARCHIVED_DETAIL = "Firma jest w archiwum. Przywróć ją, żeby zmieniać kartę."
NOTHING_DETAIL = (
    "Nie ma pustych pól do uzupełnienia. Pola, które mają już inną wartość "
    "na karcie, przyjmij pojedynczo."
)


# ── Raport ───────────────────────────────────────────────────────────────


class FieldValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: CleanText = Field(min_length=1, max_length=500)
    source: SourceUrl = Field(max_length=1000)
    published: Optional[date] = None


class SizeValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Literal[SIZE_BUCKETS]  # type: ignore[valid-type]
    source: SourceUrl = Field(max_length=1000)
    published: Optional[date] = None


class EnrichFirm(BaseModel):
    """Pola osób i kontaktów nie istnieją, więc ich nie przyjmiemy."""

    model_config = ConfigDict(extra="forbid")

    company_ref: int
    domain: Optional[FieldValue] = None
    website_url: Optional[FieldValue] = None
    nip: Optional[FieldValue] = None
    hq_city: Optional[FieldValue] = None
    industry: Optional[FieldValue] = None
    size: Optional[SizeValue] = None
    parent_name: Optional[FieldValue] = None


class EnrichReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_firms: int = Field(ge=0, le=signals.MAX_FIRMS)
    firms: list[EnrichFirm] = Field(default_factory=list, max_length=signals.MAX_FIRMS)
    not_found: list[int] = Field(default_factory=list, max_length=signals.MAX_FIRMS)


def _task_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Dla każdej firmy z listy firms ustal dane do karty firmy w CRM: domenę "
        "firmową (z głównej strony www), adres strony www, polski NIP (10 cyfr), "
        "miasto siedziby w Polsce, branżę (krótko, po polsku), liczbę pracowników "
        f"jako jeden z przedziałów {', '.join(SIZE_BUCKETS)} oraz nazwę spółki "
        "matki (grupy kapitałowej), jeśli firma ją ma. Źródła: rejestry publiczne "
        "(KRS, CEIDG, biała lista VAT), strona firmy, komunikaty prasowe. Każde "
        "pole tylko z otwartego źródła, z jego adresem w source. Pola, którego nie "
        "potwierdzisz, nie wpisuj wcale. Firmy bez żadnego pola wpisz do not_found."
    )


def _report_format() -> dict[str, Any]:
    field = {"value": "...", "source": "https://...", "published": "RRRR-MM-DD"}
    return {
        "checked_firms": "<liczba sprawdzonych firm>",
        "firms": [
            {
                "company_ref": "<ref z firms>",
                "domain": {**field, "value": "firma.pl"},
                "website_url": {**field, "value": "https://www.firma.pl"},
                "nip": {**field, "value": "0000000000"},
                "hq_city": field,
                "industry": field,
                "size": {**field, "value": "|".join(SIZE_BUCKETS)},
                "parent_name": field,
            }
        ],
        "not_found": ["<ref firmy bez danych>"],
    }


# ── Plan (bez bazy) ──────────────────────────────────────────────────────


def normalize_nip(value: str) -> Optional[str]:
    """Polski NIP z poprawną sumą kontrolną, same cyfry; inaczej ``None``."""

    text = re.sub(r"^\s*PL", "", value.strip(), flags=re.IGNORECASE)
    if re.search(r"[^\d\s\-.]", text):
        return None
    digits = re.sub(r"\D", "", text)
    return digits if nip_checksum_valid(digits) else None


def _same(a: Optional[str], b: Optional[str]) -> bool:
    return (a or "").strip().casefold().rstrip("/") == (
        b or ""
    ).strip().casefold().rstrip("/")


def plan_fields(
    firm: EnrichFirm,
    company: SalesCompany,
    *,
    parent_name: Optional[str] = None,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Pola do decyzji, liczba odrzuconych (zła wartość) i równych karcie.

    Zła wartość jednego pola nie przekreśla raportu: pole odpada i jest liczone,
    reszta firmy i reszta firm przechodzą.
    """

    out: dict[str, dict[str, Any]] = {}
    invalid = same = 0

    def keep(key: str, value: str, item: FieldValue | SizeValue, **extra: Any) -> None:
        out[key] = {
            "value": value,
            "source": item.source,
            "published": item.published.isoformat() if item.published else None,
            **extra,
        }

    checks: list[tuple[str, Optional[FieldValue], Optional[str]]] = [
        ("domain", firm.domain, company.domain),
        ("website_url", firm.website_url, company.website_url),
        ("nip", firm.nip, company.nip),
        ("hq_city", firm.hq_city, company.hq_city),
        ("industry", firm.industry, company.industry),
        ("parent_name", firm.parent_name, parent_name),
    ]
    for key, item, current in checks:
        if item is None:
            continue
        value: Optional[str] = item.value
        if key == "domain":
            value = company_service.mail_domain(value)
        elif key == "website_url":
            try:
                value = company_service.http_url(value)
            except ValueError:
                value = None
        elif key == "nip":
            value = normalize_nip(value)
        elif key == "parent_name":
            own = normalize_company_name(company.name)
            if (
                not normalize_company_name(value)
                or normalize_company_name(value) == own
            ):
                value = None
        if not value or len(value) > MAX_LEN.get(key, 255):
            invalid += 1
            continue
        if key == "parent_name":
            if current and normalize_company_name(current) == normalize_company_name(
                value
            ):
                same += 1
                continue
        elif _same(current, value):
            same += 1
            continue
        keep(key, value, item)
    if firm.size is not None:
        tier = SIZE_TO_TIER[firm.size.value]
        if company.tier == tier:
            same += 1
        else:
            keep("tier", tier, firm.size, employees=firm.size.value)
    return out, invalid, same


def fingerprint(company_id: int, fields: dict[str, dict[str, Any]]) -> str:
    values = json.dumps(
        {key: item["value"] for key, item in sorted(fields.items())}, ensure_ascii=False
    )
    return result_fingerprint(KIND, company_id, values)


# ── Zapis raportu ────────────────────────────────────────────────────────


async def _parent_names(
    db: AsyncSession, companies: list[SalesCompany]
) -> dict[int, str]:
    parent_ids = {c.parent_company_id for c in companies if c.parent_company_id}
    if not parent_ids:
        return {}
    rows = await db.execute(
        select(SalesCompany.id, SalesCompany.name).where(
            SalesCompany.id.in_(parent_ids)
        )
    )
    names = dict(rows.all())
    return {
        c.id: names[c.parent_company_id]
        for c in companies
        if c.parent_company_id in names
    }


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: Any, now: datetime
) -> dict[str, Any]:
    allowed = {int(ref) for ref in run.company_ids}
    refs = {firm.company_ref for firm in report.firms} & allowed
    not_found = set(report.not_found) & allowed
    rows = await signals._companies(db, sorted(refs))
    parents = await _parent_names(db, list(rows.values()))
    results: list[dict[str, Any]] = []
    unknown = invalid = same = 0
    seen: set[int] = set()
    for firm in report.firms:
        company = rows.get(firm.company_ref)
        if company is None or firm.company_ref in seen:
            unknown += 1
            continue
        seen.add(company.id)
        fields, bad, equal = plan_fields(
            firm, company, parent_name=parents.get(company.id)
        )
        invalid += bad
        same += equal
        if not fields:
            continue
        results.append(
            {
                "company_id": company.id,
                "payload": {"fields": fields, "checked_at": now.isoformat()},
                "fingerprint": fingerprint(company.id, fields),
            }
        )
    if results:
        # Starsza propozycja, o której nikt nie zdecydował, ustępuje nowszej.
        await db.execute(
            delete(SalesBotResult).where(
                SalesBotResult.kind == KIND,
                SalesBotResult.status == "new",
                SalesBotResult.company_id.in_([r["company_id"] for r in results]),
                SalesBotResult.fingerprint.notin_([r["fingerprint"] for r in results]),
            )
        )
    new = await save_results(db, run, results, now)
    return {
        "checked_firms": report.checked_firms,
        "sent_firms": len(run.company_ids),
        "researched_company_ids": sorted(refs | not_found),
        "results": len(results),
        "results_new": new,
        "fields": sum(len(r["payload"]["fields"]) for r in results),
        "invalid_fields": invalid,
        "same_fields": same,
        "unknown_company": unknown,
        "not_found": len(not_found),
    }


# ── Przyjęcie ────────────────────────────────────────────────────────────


def _current(company: SalesCompany, key: str) -> Any:
    if key == "parent_name":
        return company.parent_company_id
    return getattr(company, key)


def _choice(
    fields: dict[str, Any], decisions: dict[str, str], choice: Optional[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Pola do przyjęcia i do odrzucenia; bez listy pól przyjmuje tylko puste na karcie."""

    choice = choice or {}
    open_keys = [key for key in FIELDS if key in fields and key not in decisions]
    wanted = choice.get("fields")
    rejected = list(dict.fromkeys(choice.get("reject") or []))
    for key in [*(wanted or []), *rejected]:
        if key not in FIELDS:
            raise AcceptRefused(f"Nieznane pole karty: {key}.")
    rejected = [key for key in rejected if key in open_keys]
    if wanted is None:
        return open_keys, rejected
    chosen = [key for key in open_keys if key in wanted and key not in rejected]
    return chosen, rejected


async def _taken_by(
    db: AsyncSession, company_id: int, column: Any, value: str
) -> Optional[SalesCompany]:
    return (
        await db.execute(
            select(SalesCompany)
            .where(
                func.lower(column) == value.lower(),
                SalesCompany.id != company_id,
                SalesCompany.archived_at.is_(None),
            )
            .order_by(SalesCompany.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def _parent_match(
    db: AsyncSession, company: SalesCompany, name: str
) -> tuple[Optional[int], Optional[str]]:
    canonical = normalize_company_name(name)
    rows = (
        await db.execute(
            select(SalesCompany.id, SalesCompany.parent_company_id)
            .where(
                SalesCompany.normalized_name == canonical,
                SalesCompany.id != company.id,
                SalesCompany.archived_at.is_(None),
            )
            .limit(2)
        )
    ).all()
    if not rows:
        return None, f"Nie ma karty „{name}” w kartotece. Firmę matkę ustaw ręcznie."
    if len(rows) > 1:
        return None, f"Do „{name}” pasuje kilka kart. Firmę matkę wybierz ręcznie."
    parent_id, grandparent_id = rows[0]
    if grandparent_id == company.id:
        return (
            None,
            f"„{name}” ma tę firmę jako swoją firmę matkę. Sprawdź powiązanie ręcznie.",
        )
    return parent_id, None


async def _accept(
    db: AsyncSession,
    result: SalesBotResult,
    user_id: int,
    now: datetime,
    choice: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = dict(result.payload or {})
    fields: dict[str, dict[str, Any]] = payload.get("fields") or {}
    decisions: dict[str, str] = dict(payload.get("decisions") or {})
    company = (
        await db.get(SalesCompany, result.company_id, with_for_update=True)
        if result.company_id
        else None
    )
    if company is None or company.archived_at is not None:
        raise AcceptRefused(ARCHIVED_DETAIL)
    chosen, rejected = _choice(fields, decisions, choice)
    if (choice or {}).get("fields") is None:
        # „Przyjmij wszystkie”: tylko pola puste na karcie, nadpisanie zawsze z wyboru.
        chosen = [k for k in chosen if k not in rejected and not _current(company, k)]
        if not chosen and not rejected:
            raise AcceptRefused(NOTHING_DETAIL)
    if not chosen and not rejected:
        raise AcceptRefused("Wybierz pola do przyjęcia albo odrzucenia.")

    updates: dict[str, Any] = {}
    applied: list[str] = []
    notes: list[str] = []
    for key in chosen:
        value = fields[key]["value"]
        if key == "parent_name":
            parent_id, note = await _parent_match(db, company, value)
            if note:
                notes.append(note)
                continue
            updates["parent_company_id"] = parent_id
        elif key == "tier":
            updates["tier"] = value
            updates["size_range"] = fields[key].get("employees")
        else:
            updates[key] = value
        applied.append(key)

    domain = updates.get("domain")
    derived = False
    if domain is None and "website_url" in updates and not company.domain:
        domain = company_service.mail_domain(updates["website_url"])
        derived = True
    if domain:
        other = await _taken_by(db, company.id, SalesCompany.domain, domain)
        if other is not None and not derived:
            raise AcceptRefused(
                f"Domena {domain} jest już na karcie „{other.name}”. "
                "Najpierw scal karty albo popraw domenę na tamtej karcie."
            )
        if other is not None:
            # Domena wyliczona ze strony nie trafia na kartę, gdy ma ją inna karta.
            updates["domain"] = None
            notes.append(
                f"Domena {domain} ze strony jest już na karcie „{other.name}”, "
                "więc nie wpisaliśmy jej tutaj."
            )
    if "nip" in updates:
        other = await _taken_by(db, company.id, SalesCompany.nip, updates["nip"])
        if other is not None:
            raise AcceptRefused(
                f"NIP {updates['nip']} jest już na karcie „{other.name}”. "
                "Najpierw scal karty albo popraw NIP na tamtej karcie."
            )

    if updates:
        company_service.apply_fields(company, updates)
    for key in applied:
        decisions[key] = "accepted"
    for key in rejected:
        decisions[key] = "rejected"
    payload["decisions"] = decisions
    result.payload = payload
    still_open = [key for key in fields if key not in decisions]
    if still_open:
        result.status = "partial" if decisions else "new"
    else:
        result.status = "accepted" if "accepted" in decisions.values() else "rejected"
    if decisions:
        result.decided_by_user_id = user_id
        result.decided_at = now
    result.updated_at = now
    return {
        "id": result.id,
        "status": result.status,
        "company_id": company.id,
        "applied": applied,
        "rejected": rejected,
        "notes": notes,
    }


# ── Noc ──────────────────────────────────────────────────────────────────


async def night_company_ids(db: AsyncSession, *, now: datetime) -> list[int]:
    """Karty bez domeny z opiekunem albo otwartą szansą, których noc dawno nie sprawdzała."""

    recent = await db.execute(
        select(SalesSignalRun.company_ids).where(
            SalesSignalRun.kind == KIND,
            SalesSignalRun.started_at >= now - NIGHT_RESEND_AFTER,
        )
    )
    skip = sorted({int(cid) for ids in recent.scalars() for cid in ids})
    open_opportunity = exists(
        select(SalesOpportunity.id).where(
            SalesOpportunity.company_id == SalesCompany.id, live_opportunity()
        )
    )
    open_result = exists(
        select(SalesBotResult.id).where(
            SalesBotResult.company_id == SalesCompany.id,
            SalesBotResult.kind == KIND,
            SalesBotResult.status.in_(("new", "partial")),
        )
    )
    rows = await db.execute(
        select(SalesCompany.id)
        .where(
            SalesCompany.archived_at.is_(None),
            or_(SalesCompany.domain.is_(None), SalesCompany.domain == ""),
            or_(SalesCompany.owner_user_id.is_not(None), open_opportunity),
            ~open_result,
            *([SalesCompany.id.notin_(skip)] if skip else []),
        )
        .order_by(SalesCompany.id)
        .limit(NIGHT_BATCH)
    )
    return list(rows.scalars())


ENRICH = BotTask(
    kind=KIND,
    task_text=_task_text,
    report_format=_report_format,
    report_model=EnrichReport,
    ingest=_ingest,
    accept=_accept,
)
