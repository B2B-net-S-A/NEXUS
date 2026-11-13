"""Rodzaj ``enrich`` (G-A): bot proponuje brakujące pola karty firmy.

Do bota idzie to samo co zawsze: nazwa i domena firmy (``firms``), bez pól
``request``. Bot odsyła na firmę: domenę, stronę www, NIP, miasto siedziby,
branżę, przedział liczby pracowników i nazwę spółki matki, każde pole z własnym
źródłem. Od 13.11.2026 (decyzja Artura) pola trafiają na kartę od razu
(``apply_now``): puste pole i pole wpisane wcześniej przez bota dostają wartość,
pole wpisane przez człowieka zostaje. Wiersz ``sales_bot_results`` (status
``accepted``) to historia karty: co bot podał, co wpisał, co zostawił i dlaczego.

Zapis idzie tą samą ścieżką co ekran Firmy (``companies.apply_fields``).
Domena albo NIP z innej karty nie trafia na kartę (scalenie kart to osobny,
ręczny krok). Spółka matka staje się powiązaniem tylko wtedy, gdy pasuje
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
    owned = await _bot_owned(db, sorted(rows))
    results: list[dict[str, Any]] = []
    unknown = invalid = same = applied = kept = 0
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
        if not fields or company.archived_at is not None:
            continue
        outcomes = await apply_now(db, company, fields, owned.get(company.id, {}))
        applied += sum(1 for o in outcomes.values() if o["result"] == APPLIED)
        kept += sum(1 for o in outcomes.values() if o["result"] != APPLIED)
        results.append(
            {
                "company_id": company.id,
                "payload": {
                    "fields": fields,
                    "outcomes": outcomes,
                    "checked_at": now.isoformat(),
                },
                "fingerprint": fingerprint(company.id, fields),
            }
        )
    if results:
        # Propozycje sprzed zapisu od razu (13.11), o których nikt nie zdecydował, znikają.
        await db.execute(
            delete(SalesBotResult).where(
                SalesBotResult.kind == KIND,
                SalesBotResult.status.in_(("new", "partial")),
                SalesBotResult.company_id.in_([r["company_id"] for r in results]),
                SalesBotResult.fingerprint.notin_([r["fingerprint"] for r in results]),
            )
        )
    new = await save_results(db, run, results, now, status="accepted")
    return {
        "checked_firms": report.checked_firms,
        "sent_firms": len(run.company_ids),
        "researched_company_ids": sorted(refs | not_found),
        "results": len(results),
        "results_new": new,
        "fields": sum(len(r["payload"]["fields"]) for r in results),
        "applied_fields": applied,
        "kept_fields": kept,
        "invalid_fields": invalid,
        "same_fields": same,
        "unknown_company": unknown,
        "not_found": len(not_found),
    }


# ── Zapis od razu ────────────────────────────────────────────────────────
#
# Decyzja Artura z 13.11.2026: wynik bota trafia na kartę od razu, bez
# „Przyjmij”. Puste pole i pole, które wcześniej wpisał bot, dostają nową
# wartość; pole wpisane przez człowieka zostaje, a wersja bota idzie tylko do
# historii karty (``payload.outcomes``). Dubel domeny albo NIP-u z inną kartą
# niczego nie zmienia: scalanie kart zostaje ręczne.

#: Wynik pola w historii karty.
APPLIED = "applied"
KEPT = "kept"
TAKEN = "taken"
SKIPPED = "skipped"


def _current(company: SalesCompany, key: str) -> Any:
    if key == "parent_name":
        return company.parent_company_id
    return getattr(company, key)


def _written(key: str, item: dict[str, Any], outcome: dict[str, Any]) -> Any:
    """Wartość, którą bot wpisał na kartę (dla spółki matki: numer karty)."""

    if key == "parent_name":
        return outcome.get("parent_company_id")
    return item.get("value")


async def _bot_owned(
    db: AsyncSession, company_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """Ostatnia wartość, którą bot wpisał w pole karty (z historii wyników).

    Pole jest „bota”, dopóki karta ma dokładnie tę wartość; po ręcznej zmianie
    wartość się różni i pole należy do człowieka. Wyniki sprzed 13.11 przyjęte
    ręcznie też się liczą: wartość przyszła od bota.
    """

    if not company_ids:
        return {}
    rows = await db.execute(
        select(SalesBotResult.company_id, SalesBotResult.payload)
        .where(
            SalesBotResult.kind == KIND,
            SalesBotResult.company_id.in_(company_ids),
            SalesBotResult.status.in_(("accepted", "partial")),
        )
        .order_by(SalesBotResult.created_at, SalesBotResult.id)
    )
    owned: dict[int, dict[str, Any]] = {}
    for company_id, payload in rows.all():
        fields = (payload or {}).get("fields") or {}
        outcomes = (payload or {}).get("outcomes") or {}
        decisions = (payload or {}).get("decisions") or {}
        for key, item in fields.items():
            outcome = outcomes.get(key) or {}
            if outcome.get("result") == APPLIED:
                owned.setdefault(company_id, {})[key] = _written(key, item, outcome)
            elif decisions.get(key) == "accepted" and key != "parent_name":
                owned.setdefault(company_id, {})[key] = item.get("value")
    return owned


def _is_human(company: SalesCompany, key: str, owned: dict[str, Any]) -> bool:
    current = _current(company, key)
    if current in (None, ""):
        return False
    if key not in owned:
        return True
    if key == "parent_name":
        return current != owned[key]
    return not _same(str(current), str(owned[key]))


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
        return None, f"Nie ma karty „{name}” w kartotece."
    if len(rows) > 1:
        return None, f"Do „{name}” pasuje kilka kart."
    parent_id, grandparent_id = rows[0]
    if grandparent_id == company.id:
        return None, f"„{name}” ma tę firmę jako swoją firmę matkę."
    return parent_id, None


def _taken_outcome(other: SalesCompany) -> dict[str, Any]:
    return {"result": TAKEN, "other_id": other.id, "other_name": other.name}


async def apply_now(
    db: AsyncSession,
    company: SalesCompany,
    fields: dict[str, dict[str, Any]],
    owned: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Wpisz pola od bota na kartę; zwraca wynik każdego pola do historii.

    Zapis idzie tą samą ścieżką co ekran Firmy (``companies.apply_fields``).
    """

    outcomes: dict[str, dict[str, Any]] = {}
    updates: dict[str, Any] = {}
    for key in FIELDS:
        item = fields.get(key)
        if item is None:
            continue
        current = _current(company, key)
        if _is_human(company, key, owned):
            shown = current
            if key == "parent_name":
                shown = None
            outcomes[key] = {"result": KEPT, "current": shown}
            continue
        previous = current if current not in (None, "") else None
        value = item["value"]
        if key == "parent_name":
            parent_id, note = await _parent_match(db, company, value)
            if parent_id is None:
                outcomes[key] = {"result": SKIPPED, "note": note}
                continue
            updates["parent_company_id"] = parent_id
            outcomes[key] = {"result": APPLIED, "parent_company_id": parent_id}
            continue
        if key == "domain":
            other = await _taken_by(db, company.id, SalesCompany.domain, value)
            if other is not None:
                outcomes[key] = _taken_outcome(other)
                continue
        if key == "nip":
            other = await _taken_by(db, company.id, SalesCompany.nip, value)
            if other is not None:
                outcomes[key] = _taken_outcome(other)
                continue
        if key == "tier":
            updates["tier"] = value
            updates["size_range"] = item.get("employees")
        else:
            updates[key] = value
        outcomes[key] = {"result": APPLIED, "previous": previous}

    # Strona bez domeny na karcie: ``apply_fields`` wylicza domenę ze strony,
    # chyba że dostanie ją wprost. Domena zajęta przez inną kartę nie może tak
    # wejść tylnymi drzwiami, więc wtedy idzie wprost ``None``.
    site = updates.get("website_url")
    if site and "domain" not in updates and not company.domain:
        derived = company_service.mail_domain(site)
        blocked = outcomes.get("domain", {}).get("result") in (TAKEN, KEPT)
        if blocked or (
            derived
            and await _taken_by(db, company.id, SalesCompany.domain, derived)
            is not None
        ):
            updates["domain"] = None
    if updates:
        company_service.apply_fields(company, updates)
    return outcomes


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
)
