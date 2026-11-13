"""Dane firm z rejestrów na kartach Sprzedaży: zapis, historia karty, harmonogram.

Decyzja Artura z 13.11.2026 (krok 6 planu botów). Klient rejestrów i walidacja
odpowiedzi: ``services/sales/registry.py``.

Zapis od razu, tą samą ścieżką co ekran Firmy (``companies.apply_fields``),
wyłącznie w puste pola. Pole z inną wartością zostaje, a wartość z rejestru
idzie tylko do historii karty. NIP albo KRS z innej niezarchiwizowanej karty
niczego nie zmienia (scalanie kart jest ręczne), historia ma link do tamtej
karty. Firma wykreślona, w likwidacji albo w upadłości: wpis w historii, bez
archiwizacji, a wykreślona nie daje żadnych pól.

Historia karty to wiersz ``sales_bot_results`` rodzaju ``registry`` ze
statusem ``accepted`` (ten sam kształt ``payload.fields``/``outcomes`` co
zapis od razu bota ``enrich``), a każde sprawdzenie ma swój bieg
``sales_signal_runs`` (bez tokenu, od razu ``received``) z samymi liczbami.

Kiedy: noc 1:00–6:00 (krok pętli ``tasks/sales_signals.py``, paczka 30 kart na
godzinę) i zaraz po zapisaniu NIP-u albo KRS-u na karcie. Limit MF (100
zapytań ``search`` dziennie) dzielą Sprzedaż i Rozliczenia
(``services/hr/white_list.py``), więc Sprzedaż bierze najwyżej
``DAILY_MF_QUERIES``. Logi to same liczby, bez nazw firm.
Reguły: ``docs/claude/sprzedaz/dane-firm-z-rejestrow.md``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import Integer, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, local_day_start_utc
from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesOpportunity,
    SalesSignalRun,
)
from app.services.sales import companies as company_service
from app.services.sales.registry import (
    ACTIVE,
    BANKRUPTCY,
    FIELD_LIMITS,
    INVALID_NIP,
    LIQUIDATION,
    MF_BATCH,
    NOT_FOUND,
    REMOVED,
    VAT_REMOVED,
    KrsRecord,
    RegistryQuotaExceeded,
    RegistryUnavailable,
    VatRecord,
    _digits_only,
    fetch_krs,
    fetch_vat,
    new_client,
    valid_krs,
    valid_nip,
    valid_regon,
    vat_url,
)

logger = logging.getLogger(__name__)

KIND = "registry"
#: Kto w historii karty.
ACTOR = "Dane firm (automat)"

#: Zapytania MF Sprzedaży na dzień (z limitu 100 wspólnego z Rozliczeniami).
DAILY_MF_QUERIES = 25
#: Noc: jedna paczka na godzinę między 1:00 a 6:00.
NIGHT_HOURS = (1, 6)
NIGHT_EVERY = timedelta(hours=1)
NIGHT_BATCH = MF_BATCH
#: Skąd bieg (``sales_signal_runs.request.trigger``).
NIGHT = "night"
SAVE = "save"
#: Karta sprawdzona nie wraca przez 30 dni (zmiana NIP-u albo KRS-u wraca od razu).
RESEND_AFTER = timedelta(days=30)

#: Wynik pola w historii karty (nazwy jak w ``bot_tasks/enrich.py``).
APPLIED = "applied"
SAME = "same"
KEPT = "kept"
TAKEN = "taken"

#: Pola karty, które rejestr może uzupełnić, w kolejności zapisu.
FIELDS: tuple[str, ...] = (
    "legal_name",
    "nip",
    "krs",
    "regon",
    "hq_city",
    "hq_country",
)
#: Stany, przy których historia mówi „firma nieaktywna w rejestrze”.
INACTIVE_STATES: frozenset[str] = frozenset(
    {REMOVED, LIQUIDATION, BANKRUPTCY, VAT_REMOVED}
)


# ── Wybór kart ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Target:
    company_id: int
    nip: Optional[str]
    krs: Optional[str]
    key: str


def checked_key(company: SalesCompany) -> str:
    """Co sprawdzono: numery z karty, jak stoją. Ich zmiana to nowe sprawdzenie."""

    return f"{company.nip or ''}|{company.krs or ''}"


def _target(company_id: int, nip: Optional[str], krs: Optional[str]) -> Target:
    return Target(
        company_id, valid_nip(nip), valid_krs(krs), f"{nip or ''}|{krs or ''}"
    )


def _last_check():
    """Ostatnie sprawdzenie karty: kiedy i co (``payload.checked_key``)."""

    return (
        select(
            SalesBotResult.company_id.label("company_id"),
            func.max(SalesBotResult.updated_at).label("checked_at"),
        )
        .where(SalesBotResult.kind == KIND)
        .group_by(SalesBotResult.company_id)
        .subquery()
    )


async def due_company_ids(
    db: AsyncSession, *, now: datetime, limit: int, only: Optional[list[int]] = None
) -> list[int]:
    """Karty do sprawdzenia: z NIP-em albo KRS-em, niesprawdzone z tym numerem
    albo sprawdzone ponad 30 dni temu. Najpierw z opiekunem albo trwającą szansą."""

    key = func.concat(
        func.coalesce(SalesCompany.nip, ""), "|", func.coalesce(SalesCompany.krs, "")
    )
    same_key = exists().where(
        SalesBotResult.kind == KIND,
        SalesBotResult.company_id == SalesCompany.id,
        SalesBotResult.payload["checked_key"].astext == key,
        SalesBotResult.updated_at > now - RESEND_AFTER,
    )
    open_deal = exists().where(
        SalesOpportunity.company_id == SalesCompany.id,
        SalesOpportunity.status == "open",
        SalesOpportunity.archived_at.is_(None),
    )
    last = _last_check()
    statement = (
        select(SalesCompany.id)
        .outerjoin(last, last.c.company_id == SalesCompany.id)
        .where(
            SalesCompany.archived_at.is_(None),
            or_(
                func.nullif(func.trim(SalesCompany.nip), "").is_not(None),
                func.nullif(func.trim(SalesCompany.krs), "").is_not(None),
            ),
            ~same_key,
        )
        .order_by(
            or_(SalesCompany.owner_user_id.is_not(None), open_deal).desc(),
            last.c.checked_at.asc().nulls_first(),
            SalesCompany.id,
        )
        .limit(limit)
    )
    if only is not None:
        statement = statement.where(SalesCompany.id.in_(only))
    return list((await db.scalars(statement)).all())


async def mf_queries_today(db: AsyncSession, *, now: datetime) -> int:
    start = local_day_start_utc(business_date(now))
    used = await db.scalar(
        select(
            func.coalesce(
                func.sum(SalesSignalRun.report["mf_queries"].astext.cast(Integer)), 0
            )
        ).where(SalesSignalRun.kind == KIND, SalesSignalRun.started_at >= start)
    )
    return int(used or 0)


# ── Porównanie z kartą ───────────────────────────────────────────────────


def _same(key: str, current: Any, value: Any) -> bool:
    if key in ("nip", "krs", "regon"):
        normalize = {
            "nip": company_service.nip_digits,
            "krs": valid_krs,
            "regon": valid_regon,
        }[key]
        return (normalize(current) or _digits_only(current)) == value
    return (
        " ".join(str(current).split()).casefold()
        == " ".join(str(value).split()).casefold()
    )


def proposed_fields(
    vat: Optional[VatRecord], krs: Optional[KrsRecord]
) -> dict[str, dict[str, Any]]:
    """Pola z rejestru: wartość, źródło i link. Wykreślona spółka nie daje pól."""

    if krs is not None and krs.state == REMOVED:
        return {}
    active_krs = krs if krs is not None and krs.state != NOT_FOUND else None
    out: dict[str, dict[str, Any]] = {}

    def put(key: str, value: Optional[str], record: Any) -> None:
        if value and key not in out and len(value) <= FIELD_LIMITS[key]:
            out[key] = {
                "value": value,
                "source": "krs" if isinstance(record, KrsRecord) else "vat",
                "url": record.url,
            }

    for record in (active_krs, vat):
        if record is None:
            continue
        put("legal_name", record.name, record)
        put("regon", record.regon, record)
        put("hq_city", record.city, record)
    if active_krs is not None:
        put("nip", active_krs.nip, active_krs)
        put("krs", active_krs.krs, active_krs)
        put("hq_country", active_krs.country, active_krs)
    if vat is not None:
        put("nip", vat.nip, vat)
        put("krs", vat.krs, vat)
        if "hq_city" in out and "hq_country" not in out:
            put("hq_country", "PL", vat)
    return out


def registry_state(
    vat: Optional[VatRecord], krs: Optional[KrsRecord], target: Target
) -> str:
    if target.key.split("|")[0].strip() and not target.nip and krs is None:
        return INVALID_NIP
    if krs is not None and krs.state != ACTIVE and krs.state != NOT_FOUND:
        return krs.state
    if vat is not None and vat.removed:
        return VAT_REMOVED
    if vat is None and (krs is None or krs.state == NOT_FOUND):
        return NOT_FOUND
    return ACTIVE


async def _taken_by(
    db: AsyncSession, company_id: int, key: str, value: str
) -> Optional[SalesCompany]:
    """Inna niezarchiwizowana karta z tym NIP-em albo KRS-em."""

    column = SalesCompany.nip if key == "nip" else SalesCompany.krs
    digits = func.regexp_replace(column, r"\D", "", "g")
    match = digits == value if key == "nip" else func.lpad(digits, 10, "0") == value
    return (
        await db.scalars(
            select(SalesCompany)
            .where(
                SalesCompany.id != company_id, SalesCompany.archived_at.is_(None), match
            )
            .order_by(SalesCompany.id)
            .limit(1)
        )
    ).first()


async def apply_registry(
    db: AsyncSession, company: SalesCompany, fields: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Wpisz pola z rejestru w puste pola karty; zwraca wynik każdego pola do historii."""

    outcomes: dict[str, dict[str, Any]] = {}
    updates: dict[str, Any] = {}
    for key in FIELDS:
        item = fields.get(key)
        if item is None:
            continue
        value = item["value"]
        current = getattr(company, key)
        if current not in (None, "") and str(current).strip():
            if _same(key, current, value):
                outcomes[key] = {"result": SAME}
            else:
                outcomes[key] = {"result": KEPT, "current": str(current)[:500]}
            continue
        if key in ("nip", "krs"):
            other = await _taken_by(db, company.id, key, value)
            if other is not None:
                outcomes[key] = {
                    "result": TAKEN,
                    "other_id": other.id,
                    "other_name": other.name,
                }
                continue
        updates[key] = value
        outcomes[key] = {"result": APPLIED, "previous": None}
    if "hq_country" in updates and outcomes.get("hq_city", {}).get("result") not in (
        APPLIED,
        SAME,
    ):
        # Kraj z rejestru tylko razem z miastem z rejestru albo przy mieście zgodnym.
        updates.pop("hq_country")
        outcomes.pop("hq_country")
    if updates:
        company_service.apply_fields(company, updates)
    return outcomes


def fingerprint(company_id: int, payload: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "fields": {k: v["value"] for k, v in payload["fields"].items()},
            "outcomes": {k: v["result"] for k, v in payload["outcomes"].items()},
            "state": payload["state"],
            "vat_status": payload.get("vat_status"),
            "checked_key": payload["checked_key"],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return f"{KIND}|{company_id}|{hashlib.sha256(material.encode()).hexdigest()[:40]}"


async def _record(
    db: AsyncSession,
    run: SalesSignalRun,
    company: SalesCompany,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    """Wpis historii karty; to samo sprawdzenie drugi raz odświeża tylko datę."""

    statement = insert(SalesBotResult).values(
        run_id=run.id,
        kind=KIND,
        company_id=company.id,
        status="accepted",
        payload=payload,
        fingerprint=fingerprint(company.id, payload),
        decided_at=now,
        created_at=now,
        updated_at=now,
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_sales_bot_results_fingerprint",
            set_={
                "payload": statement.excluded.payload,
                "run_id": statement.excluded.run_id,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )


# ── Sprawdzenie ──────────────────────────────────────────────────────────


@dataclass
class Summary:
    companies: int = 0
    checked: int = 0
    applied_fields: int = 0
    kept_fields: int = 0
    same_fields: int = 0
    taken_fields: int = 0
    inactive: int = 0
    not_found: int = 0
    invalid_nip: int = 0
    errors: int = 0
    mf_queries: int = 0
    krs_queries: int = 0
    quota_exceeded: bool = False
    states: dict[str, int] = field(default_factory=dict)
    #: Wynik na kartę (``payload`` historii): tylko dla wywołującego, nie do logu.
    cards: dict[int, dict[str, Any]] = field(default_factory=dict)

    def report(self) -> dict[str, Any]:
        return {
            "companies": self.companies,
            "checked": self.checked,
            "applied_fields": self.applied_fields,
            "kept_fields": self.kept_fields,
            "same_fields": self.same_fields,
            "taken_fields": self.taken_fields,
            "inactive": self.inactive,
            "not_found": self.not_found,
            "invalid_nip": self.invalid_nip,
            "errors": self.errors,
            "mf_queries": self.mf_queries,
            "krs_queries": self.krs_queries,
            "quota_exceeded": self.quota_exceeded,
        }


@dataclass
class _Lookup:
    vat: Optional[VatRecord] = None
    vat_done: bool = False
    krs: Optional[KrsRecord] = None
    krs_failed: bool = False
    failed: bool = False


async def _lookups(
    client: httpx.AsyncClient,
    targets: list[Target],
    on_date: date,
    mf_budget: int,
    summary: Summary,
) -> dict[int, _Lookup]:
    found = {t.company_id: _Lookup() for t in targets}
    with_nip = [t for t in targets if t.nip]
    nips = list(dict.fromkeys(t.nip for t in with_nip))
    vat: dict[str, Optional[VatRecord]] = {}
    for start in range(0, len(nips), MF_BATCH):
        if summary.mf_queries >= mf_budget or summary.quota_exceeded:
            break
        chunk = nips[start : start + MF_BATCH]
        summary.mf_queries += 1
        try:
            vat.update(await fetch_vat(client, chunk, on_date))
        except RegistryQuotaExceeded:
            summary.quota_exceeded = True
        except RegistryUnavailable:
            pass
    for target in targets:
        lookup = found[target.company_id]
        if target.nip:
            if target.nip not in vat:
                # Bez odpowiedzi MF (limit, awaria): karta wraca w kolejnym biegu.
                lookup.failed = True
                continue
            lookup.vat, lookup.vat_done = vat[target.nip], True
        krs = target.krs or (lookup.vat.krs if lookup.vat else None)
        if krs:
            summary.krs_queries += 1
            try:
                lookup.krs = await fetch_krs(client, krs)
            except RegistryUnavailable:
                # Karta z odpowiedzią MF dostaje wpis z samej białej listy (KRS
                # wróci za 30 dni), żeby awaria KRS nie zjadała co godzinę
                # kolejnych zapytań z limitu MF. Bez MF karta wraca w kolejnym biegu.
                lookup.krs_failed = True
                lookup.failed = not lookup.vat_done
    return found


async def check_companies(
    db: AsyncSession,
    company_ids: list[int],
    *,
    now: datetime,
    client: Optional[httpx.AsyncClient] = None,
    mf_budget: int = DAILY_MF_QUERIES,
    requested_by_user_id: Optional[int] = None,
    dry_run: bool = False,
    trigger: str = SAVE,
) -> Summary:
    """Sprawdź karty w rejestrach i zapisz wynik; commit robi ta funkcja.

    Zapytania do rejestrów idą poza transakcją: najpierw odczyt numerów, potem
    sieć, na końcu blokada wierszy, ponowne porównanie z kartą i zapis.
    ``dry_run`` (skrypt próby): ten sam przebieg bez biegu i historii, na końcu
    wycofanie; wynik kart w ``summary.cards``.
    """

    summary = Summary()
    rows = (
        await db.execute(
            select(SalesCompany.id, SalesCompany.nip, SalesCompany.krs).where(
                SalesCompany.id.in_(company_ids), SalesCompany.archived_at.is_(None)
            )
        )
    ).all()
    targets = [_target(*row) for row in rows]
    summary.companies = len(targets)
    if not targets:
        return summary
    remaining = max(0, mf_budget - await mf_queries_today(db, now=now))
    await db.rollback()

    on_date = business_date(now)
    own = client is None
    client = client or new_client()
    try:
        found = await _lookups(client, targets, on_date, remaining, summary)
    finally:
        if own:
            await client.aclose()

    run: Optional[SalesSignalRun] = None
    if not dry_run:
        run = SalesSignalRun(
            kind=KIND,
            status="received",
            company_ids=[t.company_id for t in targets],
            started_at=now,
            received_at=now,
            requested_by_user_id=requested_by_user_id,
            request={"trigger": trigger},
        )
        db.add(run)
        await db.flush()
    for target in targets:
        lookup = found[target.company_id]
        if lookup.failed:
            summary.errors += 1
            continue
        company = await db.get(SalesCompany, target.company_id, with_for_update=True)
        if company is None or company.archived_at is not None:
            continue
        if checked_key(company) != target.key:
            # Ktoś zmienił NIP albo KRS w trakcie: wynik dotyczy starych numerów.
            continue
        state = registry_state(lookup.vat, lookup.krs, target)
        fields = proposed_fields(lookup.vat, lookup.krs)
        outcomes = await apply_registry(db, company, fields)
        sources = {
            name: record.url
            for name, record in (("vat", lookup.vat), ("krs", lookup.krs))
            if record is not None
        }
        if target.nip and lookup.vat is None and lookup.vat_done:
            sources["vat"] = vat_url(target.nip, on_date)
        payload: dict[str, Any] = {
            "actor": ACTOR,
            "checked_at": now.isoformat(),
            "checked_key": checked_key(company),
            "state": state,
            "vat_status": lookup.vat.vat_status if lookup.vat else None,
            "removed_on": lookup.krs.removed_on if lookup.krs else None,
            "krs_unavailable": lookup.krs_failed,
            "sources": sources,
            "fields": fields,
            "outcomes": outcomes,
        }
        if run is not None:
            await _record(db, run, company, payload, now)
        summary.cards[company.id] = payload
        summary.checked += 1
        summary.states[state] = summary.states.get(state, 0) + 1
        summary.inactive += state in INACTIVE_STATES
        summary.not_found += state == NOT_FOUND
        summary.invalid_nip += state == INVALID_NIP
        for outcome in outcomes.values():
            result = outcome["result"]
            summary.applied_fields += result == APPLIED
            summary.kept_fields += result == KEPT
            summary.same_fields += result == SAME
            summary.taken_fields += result == TAKEN
    if run is None:
        await db.rollback()
        return summary
    run.report = summary.report()
    if summary.checked == 0 and summary.errors:
        run.status, run.error = "failed", "rejestr bez odpowiedzi"
    await db.commit()
    logger.info(
        "sales_registry run=%s companies=%d checked=%d applied=%d kept=%d same=%d "
        "taken=%d inactive=%d not_found=%d errors=%d mf=%d krs=%d quota=%s",
        run.id,
        summary.companies,
        summary.checked,
        summary.applied_fields,
        summary.kept_fields,
        summary.same_fields,
        summary.taken_fields,
        summary.inactive,
        summary.not_found,
        summary.errors,
        summary.mf_queries,
        summary.krs_queries,
        summary.quota_exceeded,
    )
    return summary


# ── Kiedy ────────────────────────────────────────────────────────────────


def enabled() -> bool:
    return bool(settings.SALES_REGISTRY_ENABLED)


async def night_step(db: AsyncSession, *, now: datetime, local: datetime) -> int:
    """Krok nocny pętli ``sales_signals``: jedna paczka na godzinę od 1:00 do 6:00."""

    start, end = NIGHT_HOURS
    if not enabled() or not start <= local.hour < end:
        return 0
    night = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )
    last = await db.scalar(
        select(func.max(SalesSignalRun.started_at)).where(
            SalesSignalRun.kind == KIND,
            # Bieg po zapisie (ekran, raport bota w nocy) nie zjada godziny nocy.
            SalesSignalRun.request["trigger"].astext == NIGHT,
            SalesSignalRun.started_at >= night,
        )
    )
    if last is not None and last > now - NIGHT_EVERY:
        return 0
    if await mf_queries_today(db, now=now) >= DAILY_MF_QUERIES:
        return 0
    ids = await due_company_ids(db, now=now, limit=NIGHT_BATCH)
    if not ids:
        return 0
    try:
        summary = await check_companies(db, ids, now=now, trigger=NIGHT)
    except Exception as exc:  # noqa: BLE001
        # Komunikat błędu bazy niesie parametry zapytania (nazwy, NIP-y), a logi
        # są publiczne: sam typ wyjątku.
        await db.rollback()
        logger.warning("sales_registry night failed: %s", type(exc).__name__)
        return 0
    return summary.checked


async def check_after_save(
    company_ids: list[int], *, user_id: Optional[int] = None
) -> None:
    """Po zapisaniu NIP-u albo KRS-u (ekran Firmy, bot): od razu, we własnej sesji."""

    if not enabled() or not company_ids:
        return
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        ids = await due_company_ids(db, now=now, limit=MF_BATCH, only=company_ids)
        if not ids:
            return
        try:
            await check_companies(db, ids, now=now, requested_by_user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            # Jak w ``night_step``: bez parametrów zapytania w publicznym logu.
            logger.warning("sales_registry after save failed: %s", type(exc).__name__)


def identifiers_changed(before: str, company: SalesCompany) -> bool:
    """Zapis zmienił NIP albo KRS karty (``before`` = ``checked_key`` sprzed zapisu)."""

    return before != checked_key(company) and bool(company.nip or company.krs)
