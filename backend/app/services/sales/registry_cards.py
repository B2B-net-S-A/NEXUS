"""Dane firm z rejestrów na kartach Sprzedaży: zapis, historia karty, harmonogram.

Decyzja Artura z 13.11.2026 (krok 6 planu botów). Klient rejestrów i walidacja
odpowiedzi: ``services/sales/registry.py``.

Zapis od razu, tą samą ścieżką co ekran Firmy (``companies.apply_fields``):
puste pole i pole wpisane przez automat (rejestr albo bot ``enrich``, gdy karta
ma dokładnie jego ostatnią wartość) dostają wartość z rejestru. Pole wpisane
przez człowieka zostaje, a wartość z rejestru idzie tylko do historii karty.
NIP albo KRS z innej niezarchiwizowanej karty niczego nie zmienia (scalanie
kart jest ręczne), historia ma link do tamtej karty. Firma wykreślona,
w likwidacji albo w upadłości: wpis w historii, bez archiwizacji, a wykreślona
nie daje żadnych pól.

Bez migracji i bez biegów bota (decyzja z sesji botów 13.11): historia leży
w ``sales_companies.custom_fields``:

* ``registry_history`` — wpisy ``{at, source, lines: [{field, before, after,
  result, other_id?, other_name?, url}]}``, najnowsze na końcu, ostatnie 30;
  ``result``: ``applied``, ``kept``, ``taken``, ``inactive``. Sprawdzenie bez
  zmian nie dokłada wpisu;
* ``registry_checked_at`` i ``registry_checked_key`` (NIP i KRS karty w chwili
  sprawdzenia) — karta nie wraca przez 30 dni, chyba że zmieni się numer;
* ``registry_state`` — ostatni stan firmy w rejestrze.

Ekran pokazuje historię przez ``bot_card_history.registry_entries``.

Kiedy: noc 1:00–6:00 (krok pętli ``tasks/sales_signals.py``, paczka 30 kart na
godzinę) i zaraz po zapisaniu NIP-u albo KRS-u na karcie. Limit MF (100
zapytań ``search`` dziennie) dzielą Sprzedaż i Rozliczenia
(``services/hr/white_list.py``), więc Sprzedaż bierze najwyżej
``DAILY_MF_QUERIES``; licznik dnia i godzina ostatniej paczki nocnej leżą
w ``app_settings`` (``USAGE_KEY``). Logi to same liczby, bez nazw firm.
Reguły: ``docs/claude/sprzedaz/dane-firm-z-rejestrow.md``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import DateTime, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date
from app.models.app_setting import AppSetting
from app.models.sales import SalesCompany, SalesOpportunity
from app.services.sales import companies as company_service
from app.services.sales.bot_tasks import enrich
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
    digits_only,
    fetch_krs,
    fetch_vat,
    new_client,
    valid_krs,
    valid_nip,
    valid_regon,
)

logger = logging.getLogger(__name__)

#: Zapytania MF Sprzedaży na dzień (z limitu 100 wspólnego z Rozliczeniami).
DAILY_MF_QUERIES = 25
#: Noc: jedna paczka na godzinę między 1:00 a 6:00.
NIGHT_HOURS = (1, 6)
NIGHT_EVERY = timedelta(hours=1)
NIGHT_BATCH = MF_BATCH
#: Karta sprawdzona nie wraca przez 30 dni (zmiana NIP-u albo KRS-u wraca od razu).
RESEND_AFTER = timedelta(days=30)
#: Tyle ostatnich wpisów historii zostaje w ``custom_fields``.
HISTORY_KEEP = 30

#: ``app_settings``: ``{day, mf_queries, night_at}`` — licznik MF i ostatnia noc.
USAGE_KEY = "sales_registry_usage"
HISTORY = "registry_history"
CHECKED_AT = "registry_checked_at"
CHECKED_KEY = "registry_checked_key"
STATE = "registry_state"

#: Wynik pola w historii karty (nazwy jak w ``bot_tasks/enrich.py``).
APPLIED = "applied"
SAME = "same"
KEPT = "kept"
TAKEN = "taken"
INACTIVE = "inactive"

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


async def due_company_ids(
    db: AsyncSession, *, now: datetime, limit: int, only: Optional[list[int]] = None
) -> list[int]:
    """Karty do sprawdzenia: z NIP-em albo KRS-em, niesprawdzone z tym numerem
    albo sprawdzone ponad 30 dni temu. Najpierw z opiekunem albo trwającą szansą."""

    key = func.concat(
        func.coalesce(SalesCompany.nip, ""), "|", func.coalesce(SalesCompany.krs, "")
    )
    last_key = SalesCompany.custom_fields[CHECKED_KEY].astext
    last_at = cast(SalesCompany.custom_fields[CHECKED_AT].astext, DateTime(True))
    open_deal = exists().where(
        SalesOpportunity.company_id == SalesCompany.id,
        SalesOpportunity.status == "open",
        SalesOpportunity.archived_at.is_(None),
    )
    statement = (
        select(SalesCompany.id)
        .where(
            SalesCompany.archived_at.is_(None),
            or_(
                func.nullif(func.trim(SalesCompany.nip), "").is_not(None),
                func.nullif(func.trim(SalesCompany.krs), "").is_not(None),
            ),
            or_(
                last_key.is_(None),
                last_key != key,
                last_at.is_(None),
                last_at <= now - RESEND_AFTER,
            ),
        )
        .order_by(
            or_(SalesCompany.owner_user_id.is_not(None), open_deal).desc(),
            last_at.asc().nulls_first(),
            SalesCompany.id,
        )
        .limit(limit)
    )
    if only is not None:
        statement = statement.where(SalesCompany.id.in_(only))
    return list((await db.scalars(statement)).all())


# ── Licznik MF i noc (app_settings) ──────────────────────────────────────


def _usage_today(value: Optional[dict[str, Any]], now: datetime) -> dict[str, Any]:
    day = business_date(now).isoformat()
    value = dict(value or {})
    if value.get("day") != day:
        value = {"day": day, "mf_queries": 0, "night_at": value.get("night_at")}
    return value


async def usage(db: AsyncSession, *, now: datetime) -> dict[str, Any]:
    row = await db.get(AppSetting, USAGE_KEY)
    return _usage_today(row.value if row else None, now)


async def _reserve(
    db: AsyncSession, *, now: datetime, wanted: int, cap: int, night: bool
) -> int:
    """Zarezerwuj zapytania MF pod blokadą wiersza; zwraca, ile wolno zużyć.

    Rezerwacja przed siecią, więc dwa równoległe sprawdzenia (noc i zapis
    z ekranu) nie przekroczą dziennego limitu Sprzedaży.
    """

    row = await db.get(AppSetting, USAGE_KEY, with_for_update=True)
    value = _usage_today(row.value if row else None, now)
    granted = max(0, min(wanted, cap - int(value.get("mf_queries") or 0)))
    value["mf_queries"] = int(value.get("mf_queries") or 0) + granted
    if night:
        value["night_at"] = now.isoformat()
    if row is None:
        db.add(AppSetting(key=USAGE_KEY, value=value))
    else:
        row.value = value
    await db.commit()
    return granted


# ── Porównanie z kartą ───────────────────────────────────────────────────


def _same(key: str, current: Any, value: Any) -> bool:
    if current in (None, "") or value in (None, ""):
        return False
    if key in ("nip", "krs", "regon"):
        normalize = {
            "nip": company_service.nip_digits,
            "krs": valid_krs,
            "regon": valid_regon,
        }[key]
        return (normalize(str(current)) or digits_only(str(current))) == (
            normalize(str(value)) or digits_only(str(value))
        )
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


def registry_owned(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Ostatnia wartość, którą rejestr wpisał w każde pole karty."""

    owned: dict[str, Any] = {}
    for entry in history:
        for line in entry.get("lines") or []:
            if line.get("result") == APPLIED and line.get("field") in FIELDS:
                owned[line["field"]] = line.get("after")
    return owned


def _automat_value(key: str, current: Any, owned: tuple[dict[str, Any], ...]) -> bool:
    """Pole należy do automatu, gdy karta ma dokładnie jego ostatnią wartość."""

    return any(key in values and _same(key, current, values[key]) for values in owned)


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
    db: AsyncSession,
    company: SalesCompany,
    fields: dict[str, dict[str, Any]],
    owned: tuple[dict[str, Any], ...] = (),
) -> dict[str, dict[str, Any]]:
    """Wpisz pola z rejestru na kartę; zwraca wynik każdego pola do historii.

    ``owned``: ostatnie wartości automatów (rejestr, bot ``enrich``). Pole
    z taką wartością wolno nadpisać, inne niepuste pole należy do człowieka.
    """

    outcomes: dict[str, dict[str, Any]] = {}
    updates: dict[str, Any] = {}
    for key in FIELDS:
        item = fields.get(key)
        if item is None:
            continue
        value = item["value"]
        current = getattr(company, key)
        filled = current not in (None, "") and bool(str(current).strip())
        if filled and _same(key, current, value):
            outcomes[key] = {"result": SAME}
            continue
        if filled and not _automat_value(key, current, owned):
            outcomes[key] = {"result": KEPT, "before": str(current)[:500]}
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
        outcomes[key] = {
            "result": APPLIED,
            "before": str(current)[:500] if filled else None,
        }
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


def history_entries(
    fields: dict[str, dict[str, Any]],
    outcomes: dict[str, dict[str, Any]],
    *,
    state: str,
    vat: Optional[VatRecord],
    krs: Optional[KrsRecord],
    at: datetime,
) -> list[dict[str, Any]]:
    """Wpisy historii z jednego sprawdzenia, po jednym na rejestr ze zmianą."""

    by_source: dict[str, list[dict[str, Any]]] = {}
    for key in FIELDS:
        outcome = outcomes.get(key)
        if outcome is None or outcome["result"] == SAME:
            continue
        item = fields[key]
        line: dict[str, Any] = {
            "field": key,
            "before": outcome.get("before"),
            "after": item["value"],
            "result": outcome["result"],
            "url": item["url"],
        }
        if outcome["result"] == TAKEN:
            line["other_id"] = outcome["other_id"]
            line["other_name"] = outcome["other_name"]
        by_source.setdefault(item["source"], []).append(line)
    if state in INACTIVE_STATES:
        record = vat if state == VAT_REMOVED else krs
        source = "vat" if state == VAT_REMOVED else "krs"
        by_source.setdefault(source, []).append(
            {
                "field": "state",
                "before": None,
                "after": state,
                "result": INACTIVE,
                "url": record.url if record is not None else None,
                "removed_on": krs.removed_on if krs is not None else None,
            }
        )
    return [
        {"at": at.isoformat(), "source": source, "lines": lines}
        for source, lines in by_source.items()
    ]


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
    #: Wynik na kartę: tylko dla wywołującego (skrypt próby), nie do logu.
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
    nips = list(dict.fromkeys(t.nip for t in targets if t.nip))
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
                # Karta z odpowiedzią MF dostaje wynik z samej białej listy (KRS
                # wróci za 30 dni), żeby awaria KRS nie zjadała co godzinę
                # kolejnych zapytań z limitu MF. Bez MF karta wraca w kolejnym biegu.
                lookup.krs_failed = True
                lookup.failed = not lookup.vat_done
    return found


def _count(summary: Summary, state: str, outcomes: dict[str, dict[str, Any]]) -> None:
    summary.checked += 1
    summary.inactive += state in INACTIVE_STATES
    summary.not_found += state == NOT_FOUND
    summary.invalid_nip += state == INVALID_NIP
    for outcome in outcomes.values():
        result = outcome["result"]
        summary.applied_fields += result == APPLIED
        summary.kept_fields += result == KEPT
        summary.same_fields += result == SAME
        summary.taken_fields += result == TAKEN


async def check_companies(
    db: AsyncSession,
    company_ids: list[int],
    *,
    now: datetime,
    client: Optional[httpx.AsyncClient] = None,
    mf_budget: int = DAILY_MF_QUERIES,
    night: bool = False,
    dry_run: bool = False,
) -> Summary:
    """Sprawdź karty w rejestrach i zapisz wynik; commit robi ta funkcja.

    Kolejność: odczyt numerów i rezerwacja zapytań MF (commit), sieć poza
    transakcją, na końcu blokada wiersza karty, ponowne porównanie numerów
    i zapis. ``dry_run`` (skrypt próby): bez rezerwacji, na końcu wycofanie;
    wynik kart w ``summary.cards``.
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
    wanted = math.ceil(len({t.nip for t in targets if t.nip}) / MF_BATCH)
    if dry_run:
        used = int((await usage(db, now=now)).get("mf_queries") or 0)
        granted = max(0, min(wanted, mf_budget - used))
        await db.rollback()
    else:
        granted = await _reserve(db, now=now, wanted=wanted, cap=mf_budget, night=night)

    on_date = business_date(now)
    own = client is None
    client = client or new_client()
    try:
        found = await _lookups(client, targets, on_date, granted, summary)
    finally:
        if own:
            await client.aclose()

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
        custom = dict(company.custom_fields or {})
        history = list(custom.get(HISTORY) or [])
        bot = (await enrich._bot_owned(db, [company.id])).get(company.id, {})
        state = registry_state(lookup.vat, lookup.krs, target)
        fields = proposed_fields(lookup.vat, lookup.krs)
        outcomes = await apply_registry(
            db, company, fields, owned=(registry_owned(history), bot)
        )
        entries = history_entries(
            fields, outcomes, state=state, vat=lookup.vat, krs=lookup.krs, at=now
        )
        company.custom_fields = {
            **custom,
            HISTORY: (history + entries)[-HISTORY_KEEP:],
            CHECKED_AT: now.isoformat(),
            CHECKED_KEY: checked_key(company),
            STATE: state,
        }
        summary.cards[company.id] = {
            "state": state,
            "vat_status": lookup.vat.vat_status if lookup.vat else None,
            "krs_unavailable": lookup.krs_failed,
            "fields": fields,
            "outcomes": outcomes,
            "entries": entries,
        }
        _count(summary, state, outcomes)
    if dry_run:
        await db.rollback()
        return summary
    await db.commit()
    logger.info(
        "sales_registry companies=%d checked=%d applied=%d kept=%d same=%d "
        "taken=%d inactive=%d not_found=%d errors=%d mf=%d krs=%d quota=%s night=%s",
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
        night,
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
    today = await usage(db, now=now)
    last = today.get("night_at")
    # Sprawdzenie po zapisie (ekran, raport bota w nocy) nie zjada godziny nocy.
    if last and datetime.fromisoformat(last) > now - NIGHT_EVERY:
        return 0
    if int(today.get("mf_queries") or 0) >= DAILY_MF_QUERIES:
        return 0
    ids = await due_company_ids(db, now=now, limit=NIGHT_BATCH)
    if not ids:
        return 0
    try:
        summary = await check_companies(db, ids, now=now, night=True)
    except Exception as exc:  # noqa: BLE001
        # Komunikat błędu bazy niesie parametry zapytania (nazwy, NIP-y), a logi
        # są publiczne: sam typ wyjątku.
        await db.rollback()
        logger.warning("sales_registry night failed: %s", type(exc).__name__)
        return 0
    return summary.checked


async def check_after_save(company_ids: list[int]) -> None:
    """Po zapisaniu NIP-u albo KRS-u (ekran Firmy, bot): od razu, we własnej sesji."""

    if not enabled() or not company_ids:
        return
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        ids = await due_company_ids(db, now=now, limit=MF_BATCH, only=company_ids)
        if not ids:
            return
        try:
            await check_companies(db, ids, now=now)
        except Exception as exc:  # noqa: BLE001
            # Jak w ``night_step``: bez parametrów zapytania w publicznym logu.
            logger.warning("sales_registry after save failed: %s", type(exc).__name__)


def identifiers_changed(before: str, company: SalesCompany) -> bool:
    """Zapis zmienił NIP albo KRS karty (``before`` = ``checked_key`` sprzed zapisu)."""

    return before != checked_key(company) and bool(company.nip or company.krs)
