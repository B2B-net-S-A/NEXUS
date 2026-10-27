"""Import CRM Atlasa do Sprzedaży NEXUSA (D1 = B, 26.10.2026).

Źródło jest wymienne (``AtlasSource``): prawdziwy bieg czyta bazę Atlasa
(``scripts/import_atlas_sales.py``, połączenie tylko do odczytu), testy podają
listy słowników. Zasady, które nie są kosmetyką:

* **Idempotencja.** Każdy wiersz dostaje ``external_ref`` (``atlas:<tabela>:<id>``)
  i zapis idzie przez ``ON CONFLICT (external_ref) DO UPDATE`` — drugi bieg
  aktualizuje, nie dubluje. Lejek ``sales`` mapujemy na istniejący lejek
  NEXUSA (``SALES_STAGE_MAP``), pozostałe lejki Atlasa powstają obok.
* **Śmieci w kartotece.** ~31% firm przy szansach to nazwiska albo puste nazwy
  (raport ``docs/nexus-atlas-company-people-completion-report.md`` w repo
  ATLAS). Firma, która wygląda na osobę i nie ma szans, kontaktów ani
  aktywności, nie wchodzi. Taka, do której coś się odwołuje, wchodzi z tagiem
  ``ATLAS_REVIEW_TAG`` — inaczej szansa straciłaby firmę.
* **Szansa zawsze ma firmę.** Szansa bez ``company_id`` (Atlas trzymał samą
  nazwę) łączy się z firmą o tej samej nazwie kanonicznej albo dostaje nową.
* **Ludzie po e-mailu.** Opiekunów i autorów mapujemy na konta NEXUSA po
  adresie (Atlas nie miał tabeli użytkowników, tylko UUID-y Supabase).
  Brak konta = pole puste i liczba w raporcie.
* **Raport bez danych osobowych** — same liczby; repo i logi Actions są
  publiczne, a raport idzie do paragonu migracji.

Pliki (Supabase Storage) przenosi osobny krok — tu tylko je liczymy.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesPipeline,
    SalesLead,
    SalesPipelineStage,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.company_names import normalize_company_name
from app.services.sales.companies import nip_digits
from app.services.sales.leads import is_existing_client

logger = logging.getLogger(__name__)

ATLAS_REVIEW_TAG = "atlas: do przejrzenia"
UNNAMED_COMPANY = "Firma z Atlasa bez nazwy"
BATCH = 500

#: Etapy lejka „sales” Atlasa (migracja kpi01) → klucze etapów NEXUSA.
SALES_STAGE_MAP: dict[str, str] = {
    "stage-lead": "lead",
    "stage-contact": "qualifying-meeting",
    "stage-meeting": "qualified",
    "stage-proposal": "offer-sent",
    "stage-negotiation": "not-qualified",
    "stage-won": "won",
    "stage-lost": "lost",
}
ATLAS_SALES_PIPELINE = "sales"

# Heurystyka z ATLAS ``scripts/measure_nexus_match_rate.py``: dwa słowa
# z wielkiej litery bez formy prawnej i słów typowych dla organizacji.
_ORG_HINTS = re.compile(
    r"\b(bank|group|grupa|polska|polsk|sp|s\.a|systems?|tech|soft|cloud|data|"
    r"centrum|urząd|urzad|gmina|instytut|szpital|uniwersytet|ministerstwo|"
    r"fundacja|zakład|zaklad|przedsiębiorstwo|przedsiebiorstwo|it|dev|lab|"
    r"consulting|solutions?|media|energia|energy|serwis|service|"
    r"corp|corporation|ltd|limited|inc|llc|gmbh|ag|a\.g|bv|b\.v|nv|n\.v|"
    r"oy|ab|as|a\.s|plc|sarl|spa|srl)\b",
    re.IGNORECASE,
)


def looks_like_person_name(name: str) -> bool:
    cleaned = (name or "").strip()
    if _ORG_HINTS.search(cleaned):
        return False
    parts = cleaned.split()
    return len(parts) == 2 and all(
        p[:1].isupper() and p[1:].islower() for p in parts if p
    )


def is_junk_company(name: Optional[str]) -> bool:
    """Pusta nazwa albo nazwisko zamiast firmy."""

    return not (name or "").strip() or looks_like_person_name(name or "")


def _ref(table: str, atlas_id: Any) -> str:
    return f"atlas:{table}:{atlas_id}"


def _clip(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value[:limit] or None


def _money(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount >= 0 else None


def _choice(value: Any, allowed: Sequence[str]) -> Optional[str]:
    return value if isinstance(value, str) and value in allowed else None


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


class AtlasSource(Protocol):
    async def people(self) -> list[dict[str, Any]]: ...
    async def pipelines(self) -> list[dict[str, Any]]: ...
    async def stages(self) -> list[dict[str, Any]]: ...
    async def companies(self) -> list[dict[str, Any]]: ...
    async def contacts(self) -> list[dict[str, Any]]: ...
    async def company_contacts(self) -> list[dict[str, Any]]: ...
    async def deals(self) -> list[dict[str, Any]]: ...
    async def deal_contacts(self) -> list[dict[str, Any]]: ...
    async def deal_activities(self) -> list[dict[str, Any]]: ...
    async def company_activities(self) -> list[dict[str, Any]]: ...
    async def deal_notes(self) -> list[dict[str, Any]]: ...
    async def company_notes(self) -> list[dict[str, Any]]: ...
    async def linkedin_leads(self) -> list[dict[str, Any]]: ...
    async def press_signals(self) -> list[dict[str, Any]]: ...
    async def attachments_count(self) -> int: ...


@dataclass
class ImportReport:
    """Same liczby — bez nazw, e-maili i treści (paragon migracji jest publiczny)."""

    counts: Counter = field(default_factory=Counter)

    def add(self, key: str, amount: int = 1) -> None:
        self.counts[key] += amount

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.counts.items()))


@dataclass
class _Context:
    users_by_email: dict[str, int]
    email_by_atlas_user: dict[str, str]
    report: ImportReport
    now: datetime


def _user_id(
    ctx: _Context, *, email: Any = None, atlas_user: Any = None
) -> Optional[int]:
    address = (email or "").strip().lower() if isinstance(email, str) else ""
    if not address and atlas_user:
        address = ctx.email_by_atlas_user.get(str(atlas_user), "")
    if not address:
        return None
    found = ctx.users_by_email.get(address)
    if found is None:
        ctx.report.add("person_references_without_nexus_account")
    return found


async def _upsert(
    db: AsyncSession,
    model: Any,
    rows: list[dict[str, Any]],
    *,
    keep: Iterable[str] = (),
) -> dict[str, int]:
    """Wstaw albo zaktualizuj po ``external_ref``; zwraca ``external_ref → id``.

    ``keep`` — kolumny, których drugi bieg nie nadpisuje (np. opiekun zmieniony
    już w NEXUSIE w okresie przejściowym).
    """

    ids: dict[str, int] = {}
    keep = set(keep) | {"id", "external_ref", "created_at"}
    for start in range(0, len(rows), BATCH):
        chunk = rows[start : start + BATCH]
        if not chunk:
            continue
        stmt = insert(model).values(chunk)
        update = {
            column: stmt.excluded[column] for column in chunk[0] if column not in keep
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_ref"],
            index_where=text("external_ref IS NOT NULL"),
            set_=update,
        ).returning(model.id, model.external_ref)
        for row_id, ref in (await db.execute(stmt)).all():
            ids[ref] = row_id
    return ids


# ── Lejki ────────────────────────────────────────────────────────────────


async def _import_pipelines(
    db: AsyncSession, source: AtlasSource, ctx: _Context
) -> dict[str, tuple[int, int]]:
    """Etap Atlasa → (lejek NEXUSA, etap NEXUSA)."""

    pipelines = {row["id"]: row for row in await source.pipelines()}
    stages = await source.stages()
    by_pipeline: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        by_pipeline.setdefault(stage["pipeline_id"], []).append(stage)

    sales = (
        await db.execute(
            select(SalesPipeline).where(
                SalesPipeline.key == schema.DEFAULT_PIPELINE_KEY
            )
        )
    ).scalar_one()
    sales_stages = {
        stage.key: stage
        for stage in (
            await db.execute(
                select(SalesPipelineStage).where(
                    SalesPipelineStage.pipeline_id == sales.id
                )
            )
        ).scalars()
    }

    mapping: dict[str, tuple[int, int]] = {}
    for atlas_pipeline_id, pipeline in pipelines.items():
        own = sorted(
            by_pipeline.get(atlas_pipeline_id, []), key=lambda s: s["position"]
        )
        if atlas_pipeline_id == ATLAS_SALES_PIPELINE:
            for stage in own:
                key = SALES_STAGE_MAP.get(stage["id"])
                if key is None:
                    # Etap dodany w Atlasie z panelu admina — wynikiem do
                    # najbliższego odpowiednika, otwarty na start lejka.
                    key = (
                        "won"
                        if stage.get("is_won")
                        else "lost"
                        if stage.get("is_lost")
                        else "lead"
                    )
                    ctx.report.add("stages_mapped_by_outcome")
                mapping[stage["id"]] = (sales.id, sales_stages[key].id)
            continue

        key = f"atlas-{atlas_pipeline_id}"[:40]
        row = {
            "key": key,
            "name": _clip(pipeline.get("name"), 120) or key,
            "position": 10 + len(mapping),
            "is_default": False,
            "archived_at": ctx.now if pipeline.get("is_hidden") else None,
        }
        stmt = insert(SalesPipeline).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"name": stmt.excluded.name, "archived_at": stmt.excluded.archived_at},
        ).returning(SalesPipeline.id)
        nexus_pipeline_id = (await db.execute(stmt)).scalar_one()
        ctx.report.add("pipelines_extra")
        for stage in own:
            outcome = (
                "won"
                if stage.get("is_won")
                else "lost"
                if stage.get("is_lost")
                else "open"
            )
            values = {
                "pipeline_id": nexus_pipeline_id,
                "key": _clip(stage["id"], 60),
                "name": _clip(stage.get("name"), 120) or stage["id"],
                "position": int(stage.get("position") or 0),
                "probability": max(0, min(100, int(stage.get("probability") or 0))),
                "outcome": outcome,
                "qualifies": False,
                "color": _clip(stage.get("color"), 16),
            }
            stage_stmt = insert(SalesPipelineStage).values(values)
            stage_stmt = stage_stmt.on_conflict_do_update(
                constraint="uq_sales_pipeline_stages_key",
                set_={
                    name: stage_stmt.excluded[name]
                    for name in ("name", "position", "probability", "outcome", "color")
                },
            ).returning(SalesPipelineStage.id)
            mapping[stage["id"]] = (
                nexus_pipeline_id,
                (await db.execute(stage_stmt)).scalar_one(),
            )
    ctx.report.add("stages_mapped", len(mapping))
    return mapping


# ── Firmy ────────────────────────────────────────────────────────────────


def _company_row(
    company: Mapping[str, Any], ctx: _Context, *, review: bool
) -> dict[str, Any]:
    name = _clip(company.get("name"), 500) or UNNAMED_COMPANY
    tags = [str(tag) for tag in _list(company.get("tags"))][:30]
    if review:
        tags.append(ATLAS_REVIEW_TAG)
    return {
        "external_ref": _ref("companies", company["id"]),
        "name": name,
        "legal_name": _clip(company.get("legal_name"), 500),
        "normalized_name": normalize_company_name(name) or name.lower(),
        "nip": nip_digits(company.get("nip")),
        "krs": _clip(company.get("krs_id"), 20),
        "regon": _clip(company.get("regon"), 14),
        "domain": _clip(company.get("domain"), 255),
        "website_url": _clip(company.get("website_url"), 500),
        "linkedin_url": _clip(company.get("linkedin_url"), 500),
        "industry": _clip(company.get("industry"), 255),
        "size_range": _clip(company.get("employee_range") or company.get("size"), 40),
        "hq_city": _clip(company.get("hq_city"), 120),
        "hq_country": _clip(company.get("hq_country"), 2),
        "description": company.get("description") or None,
        "lifecycle_stage": _choice(
            company.get("lifecycle_stage"), schema.COMPANY_LIFECYCLES
        )
        or "lead",
        "tier": _choice(company.get("account_tier"), schema.COMPANY_TIERS),
        "status": _choice(company.get("status"), schema.COMPANY_STATUSES) or "active",
        "tags": tags,
        "source": _clip(company.get("source") or "atlas", 60),
        "owner_user_id": _user_id(
            ctx,
            email=company.get("owner_email"),
            atlas_user=company.get("owner_user_id"),
        ),
        "custom_fields": {"atlas": _dict(company.get("custom_fields"))}
        if company.get("custom_fields")
        else {},
        "created_at": company.get("created_at") or ctx.now,
    }


async def _client_links(db: AsyncSession) -> tuple[dict[str, int], dict[str, int]]:
    """Klienci NEXUSA po NIP i po jednoznacznej nazwie kanonicznej."""

    by_nip: dict[str, int] = {}
    by_name: dict[str, Optional[int]] = {}
    rows = await db.execute(
        select(Client.id, Client.name, Client.nip).where(
            Client.merged_into_client_id.is_(None), Client.deleted_at.is_(None)
        )
    )
    for client_id, name, nip in rows.all():
        digits = nip_digits(nip)
        if digits:
            by_nip.setdefault(digits, client_id)
        canonical = normalize_company_name(name or "")
        if canonical:
            by_name[canonical] = None if canonical in by_name else client_id
    return by_nip, {k: v for k, v in by_name.items() if v is not None}


async def _import_companies(
    db: AsyncSession,
    source: AtlasSource,
    ctx: _Context,
    referenced: set[str],
) -> dict[str, int]:
    companies = await source.companies()
    rows = []
    parents: list[tuple[str, str]] = []
    for company in companies:
        atlas_id = str(company["id"])
        junk = is_junk_company(company.get("name"))
        if junk and atlas_id not in referenced:
            ctx.report.add("companies_skipped_junk")
            continue
        if junk:
            ctx.report.add("companies_review")
        rows.append(_company_row(company, ctx, review=junk))
        if company.get("parent_company_id"):
            parents.append((atlas_id, str(company["parent_company_id"])))
    ids = await _upsert(db, SalesCompany, rows, keep={"owner_user_id", "client_id"})
    ctx.report.add("companies_imported", len(ids))

    linked = 0
    for child, parent in parents:
        child_id = ids.get(_ref("companies", child))
        parent_id = ids.get(_ref("companies", parent))
        if child_id and parent_id and child_id != parent_id:
            await db.execute(
                SalesCompany.__table__.update()
                .where(SalesCompany.id == child_id)
                .values(parent_company_id=parent_id)
            )
            linked += 1
    ctx.report.add("companies_parent_links", linked)

    # Firma, która jest już klientem w NEXUSIE (ten sam NIP albo jednoznaczna
    # nazwa) — łączymy od razu, żeby panel i karta mówiły to samo.
    by_nip, by_name = await _client_links(db)
    taken = set(
        (
            await db.execute(
                select(SalesCompany.client_id).where(
                    SalesCompany.client_id.is_not(None)
                )
            )
        ).scalars()
    )
    for row in rows:
        company_id = ids.get(row["external_ref"])
        client_id = by_nip.get(row["nip"] or "") or by_name.get(row["normalized_name"])
        if company_id and client_id and client_id not in taken:
            await db.execute(
                SalesCompany.__table__.update()
                .where(SalesCompany.id == company_id, SalesCompany.client_id.is_(None))
                .values(client_id=client_id)
            )
            taken.add(client_id)
            ctx.report.add("companies_linked_to_clients")
    return ids


# ── Kontakty ─────────────────────────────────────────────────────────────


async def _import_contacts(
    db: AsyncSession, source: AtlasSource, ctx: _Context, companies: Mapping[str, int]
) -> dict[str, int]:
    bridge: dict[str, str] = {}
    for link in await source.company_contacts():
        contact = str(link["contact_id"])
        if link.get("is_primary_employer") or contact not in bridge:
            bridge[contact] = str(link["company_id"])
    rows = []
    for contact in await source.contacts():
        atlas_id = str(contact["id"])
        company = contact.get("primary_company_id") or bridge.get(atlas_id)
        full_name = _clip(contact.get("full_name"), 255) or _clip(
            f"{contact.get('first_name') or ''} {contact.get('last_name') or ''}", 255
        )
        if not full_name:
            ctx.report.add("contacts_skipped_nameless")
            continue
        email = _clip(contact.get("email"), 255)
        rows.append(
            {
                "external_ref": _ref("contacts", atlas_id),
                "company_id": companies.get(_ref("companies", company))
                if company
                else None,
                "full_name": full_name,
                "first_name": _clip(contact.get("first_name"), 120),
                "last_name": _clip(contact.get("last_name"), 120),
                "title": _clip(contact.get("title"), 255),
                "email": email.lower() if email else None,
                "phone": _clip(contact.get("phone"), 60),
                "mobile_phone": _clip(contact.get("mobile_phone"), 60),
                "linkedin_url": _clip(contact.get("linkedin_url"), 500),
                "seniority": _clip(contact.get("seniority"), 40),
                "department": _clip(contact.get("department"), 120),
                "is_executive": bool(contact.get("is_cxo")),
                "notes": contact.get("notes") or None,
                "source": _clip(contact.get("source") or "atlas", 40),
                "created_at": contact.get("created_at") or ctx.now,
            }
        )
    ids = await _upsert(db, SalesContact, rows)
    ctx.report.add("contacts_imported", len(ids))
    return ids


# ── Szanse ───────────────────────────────────────────────────────────────


async def _company_for_orphan(
    db: AsyncSession,
    ctx: _Context,
    companies: dict[str, int],
    name: Optional[str],
) -> int:
    """Szansa bez firmy: ta sama nazwa kanoniczna albo nowa firma z nazwy."""

    label = (name or "").strip() or UNNAMED_COMPANY
    canonical = normalize_company_name(label) or label.lower()
    existing = (
        await db.execute(
            select(SalesCompany.id)
            .where(SalesCompany.normalized_name == canonical)
            .order_by(SalesCompany.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        ctx.report.add("opportunities_company_adopted")
        return existing
    ref = _ref("deal-company", canonical)[:80]
    if ref in companies:
        return companies[ref]
    created = await _upsert(
        db,
        SalesCompany,
        [
            {
                "external_ref": ref,
                "name": label[:500],
                "normalized_name": canonical[:500],
                "tags": [ATLAS_REVIEW_TAG],
                "source": "atlas",
                "created_at": ctx.now,
            }
        ],
    )
    companies.update(created)
    ctx.report.add("opportunities_company_created")
    return created[ref]


async def _import_deals(
    db: AsyncSession,
    source: AtlasSource,
    ctx: _Context,
    companies: dict[str, int],
    contacts: Mapping[str, int],
    stages: Mapping[str, tuple[int, int]],
) -> dict[str, int]:
    rows = []
    for deal in await source.deals():
        stage = stages.get(str(deal.get("stage_id")))
        if stage is None:
            ctx.report.add("opportunities_skipped_unknown_stage")
            continue
        company_id = companies.get(_ref("companies", deal.get("company_id")))
        if company_id is None:
            company_id = await _company_for_orphan(
                db, ctx, companies, deal.get("company_name")
            )
        status = _choice(deal.get("status"), schema.OPPORTUNITY_STATUSES) or "open"
        custom = _dict(deal.get("custom_fields"))
        for key in ("products", "subscription_items"):
            if deal.get(key):
                custom[key] = deal[key]
        roles = []
        if deal.get("contact_role"):
            roles.append({"title": str(deal["contact_role"])[:200], "count": 1})
        rows.append(
            {
                "external_ref": _ref("deals", deal["id"]),
                "company_id": company_id,
                "pipeline_id": stage[0],
                "stage_id": stage[1],
                "title": _clip(deal.get("title"), 255) or "Szansa z Atlasa",
                "description": deal.get("description") or None,
                "status": status,
                "service_line": _choice(deal.get("service_line"), schema.SERVICE_LINES),
                "value": _money(deal.get("value")),
                "mrr_value": _money(deal.get("mrr_value")),
                "one_off_value": _money(deal.get("one_off_value")),
                "margin_pct": _money(deal.get("margin_pct"))
                if deal.get("margin_pct") is not None
                and abs(float(deal["margin_pct"])) <= 100
                else None,
                "currency": (_clip(deal.get("currency"), 3) or "PLN").upper(),
                "contract_months": deal.get("contract_months"),
                "probability": max(0, min(100, int(deal.get("probability") or 0))),
                "expected_close_date": deal.get("expected_close_date"),
                "qualified_at": deal.get("qualified_at"),
                "won_at": deal.get("won_at") if status == "won" else None,
                "lost_at": deal.get("lost_at") if status == "lost" else None,
                "lost_reason": _clip(deal.get("lost_reason"), 500),
                "primary_contact_id": contacts.get(
                    _ref("contacts", deal.get("primary_contact_id"))
                ),
                "roles": roles,
                "source": _clip(
                    deal.get("source_tag") or deal.get("origin_module"), 60
                ),
                "campaign": _clip(deal.get("source_campaign"), 120),
                "tags": [str(tag) for tag in _list(deal.get("tags"))][:30],
                "custom_fields": {"atlas": custom} if custom else {},
                "owner_user_id": _user_id(
                    ctx,
                    email=deal.get("owner_email"),
                    atlas_user=deal.get("owner_user_id"),
                ),
                "last_activity_at": deal.get("last_activity_at"),
                "keep_open_until": deal.get("keep_open_until"),
                "archived_at": deal.get("archived_at"),
                "archived_reason": _clip(deal.get("archived_reason"), 255),
                "created_at": deal.get("created_at") or ctx.now,
            }
        )
    ids = await _upsert(db, SalesOpportunity, rows, keep={"owner_user_id"})
    ctx.report.add("opportunities_imported", len(ids))

    links = []
    for link in await source.deal_contacts():
        opportunity_id = ids.get(_ref("deals", link["deal_id"]))
        contact_id = contacts.get(_ref("contacts", link["contact_id"]))
        if opportunity_id and contact_id:
            links.append(
                {
                    "opportunity_id": opportunity_id,
                    "contact_id": contact_id,
                    "role": _choice(link.get("role"), schema.CONTACT_ROLES),
                }
            )
    for start in range(0, len(links), BATCH):
        stmt = insert(SalesOpportunityContact).values(links[start : start + BATCH])
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="pk_sales_opportunity_contacts",
                set_={"role": stmt.excluded.role},
            )
        )
    ctx.report.add("opportunity_contacts_imported", len(links))
    return ids


# ── Aktywności i notatki ─────────────────────────────────────────────────


def _activity_kind(value: Any) -> str:
    return _choice(value, schema.ACTIVITY_KINDS) or "note"


async def _import_activities(
    db: AsyncSession,
    source: AtlasSource,
    ctx: _Context,
    companies: Mapping[str, int],
    contacts: Mapping[str, int],
    deals: Mapping[str, int],
    deal_company: Mapping[int, int],
) -> None:
    rows: list[dict[str, Any]] = []

    def common(row: Mapping[str, Any], table: str) -> dict[str, Any]:
        return {
            "external_ref": _ref(table, row["id"]),
            "contact_id": contacts.get(_ref("contacts", row.get("contact_id"))),
            "created_by_user_id": _user_id(
                ctx,
                email=row.get("created_by"),
                atlas_user=row.get("created_by_user_id"),
            ),
            "created_at": row.get("created_at") or ctx.now,
        }

    for row in await source.deal_activities():
        opportunity_id = deals.get(_ref("deals", row.get("deal_id")))
        kind = _activity_kind(row.get("activity_type"))
        done_at = row.get("done_at") or (
            row.get("occurred_at") if row.get("done") else None
        )
        rows.append(
            {
                **common(row, "deal_activities"),
                "kind": kind,
                "opportunity_id": opportunity_id,
                "company_id": deal_company.get(opportunity_id)
                if opportunity_id
                else None,
                "subject": _clip(row.get("subject"), 500),
                "body": row.get("description") or None,
                "priority": _choice(row.get("priority"), schema.PRIORITIES),
                "due_at": row.get("due_date"),
                "occurred_at": row.get("occurred_at"),
                "done_at": done_at if (row.get("done") or kind != "task") else None,
                "assignee_user_id": _user_id(ctx, atlas_user=row.get("owner_user_id"))
                if kind == "task"
                else None,
                "external_source": "atlas",
            }
        )
    for row in await source.company_activities():
        opportunity_id = deals.get(_ref("deals", row.get("deal_id")))
        kind = _activity_kind(row.get("activity_type"))
        rows.append(
            {
                **common(row, "company_activities"),
                "kind": kind,
                "opportunity_id": opportunity_id,
                "company_id": companies.get(_ref("companies", row.get("company_id"))),
                "subject": _clip(row.get("subject"), 500),
                "body": row.get("description") or None,
                "priority": None,
                "due_at": row.get("due_date"),
                "occurred_at": row.get("created_at"),
                "done_at": row.get("done_at")
                or (
                    row.get("created_at") if kind != "task" or row.get("done") else None
                ),
                "assignee_user_id": None,
                "external_source": _clip(row.get("external_source") or "atlas", 40),
            }
        )
    for table, rows_in, owner_key, owner_map in (
        ("deal_notes", await source.deal_notes(), "deal_id", deals),
        ("company_notes", await source.company_notes(), "company_id", companies),
    ):
        for row in rows_in:
            owner = owner_map.get(
                _ref(
                    "deals" if owner_key == "deal_id" else "companies",
                    row.get(owner_key),
                )
            )
            content = (row.get("content") or "").strip()
            if not content:
                ctx.report.add("notes_skipped_empty")
                continue
            rows.append(
                {
                    **common(row, table),
                    "kind": "note",
                    "opportunity_id": owner if owner_key == "deal_id" else None,
                    "company_id": (
                        deal_company.get(owner) if owner_key == "deal_id" else owner
                    )
                    if owner
                    else None,
                    "subject": None,
                    "body": content,
                    "priority": None,
                    "due_at": None,
                    "occurred_at": row.get("created_at"),
                    "done_at": row.get("created_at"),
                    "is_pinned": bool(row.get("is_pinned")),
                    "assignee_user_id": None,
                    "external_source": "atlas",
                }
            )
    # Jeden kształt wiersza w paczce (insert wielowierszowy).
    for row in rows:
        row.setdefault("is_pinned", False)
    ids = await _upsert(db, SalesActivity, rows)
    ctx.report.add("activities_imported", len(ids))


# ── Leady ────────────────────────────────────────────────────────────────

#: Otwarte statusy leadów Atlasa → status skrzynki NEXUSA. Zamienione,
#: odrzucone i zarchiwizowane nie przechodzą — ich ślad to szanse.
_OPEN_LEAD_STATUSES = {
    "new": "new",
    "reviewing": "new",
    "qualified": "new",
    "contacted": "contacted",
}


def _lead_score(value: Any) -> int:
    try:
        return max(0, min(100, int(value or 0)))
    except (TypeError, ValueError):
        return 0


async def _import_leads(
    db: AsyncSession, source: AtlasSource, ctx: _Context, companies: Mapping[str, int]
) -> None:
    """LinkedIn i prasa (z ogłoszeniami) z Atlasa → skrzynka leadów.

    ``compass_signals`` („Od konsultantów”) celowo nie przechodzą: popyt
    u istniejących klientów idzie do DL (decyzja Artura 22.10.2026). Tak samo
    lead z firmy, która jest już klientem NEXUSA.
    """

    rows: list[dict[str, Any]] = []
    for row in await source.linkedin_leads():
        status = _OPEN_LEAD_STATUSES.get(str(row.get("status") or "new"))
        if status is None or row.get("archived_at"):
            ctx.report.add("leads_skipped_closed")
            continue
        text_value = row.get("summary") or row.get("post_content") or ""
        rows.append(
            {
                "fingerprint": _ref("linkedin_leads", row["id"]),
                "source": "linkedin",
                "status": status,
                "title": _clip(text_value, 500) or "Post na LinkedIn",
                "summary": row.get("post_content") or None,
                "company_name": _clip(row.get("company_name"), 500),
                "company_id": companies.get(_ref("companies", row.get("company_id"))),
                "url": _clip(row.get("linkedin_profile_url"), 1000),
                "score": _lead_score(row.get("score")),
                "signal_at": row.get("last_seen_at") or row.get("first_seen_at"),
                "payload": {
                    key: row[key]
                    for key in ("persona_tag", "grade", "recommended_offer")
                    if row.get(key)
                },
            }
        )
    for row in await source.press_signals():
        status = _OPEN_LEAD_STATUSES.get(str(row.get("status") or "new"))
        if status is None or row.get("archived_at"):
            ctx.report.add("leads_skipped_closed")
            continue
        rows.append(
            {
                "fingerprint": _ref("press_signals", row["id"]),
                "source": "job_board"
                if row.get("source_category") == "job_board"
                else "press",
                "status": status,
                "title": _clip(row.get("article_title"), 500) or "Sygnał z prasy",
                "summary": row.get("ai_summary") or None,
                "company_name": _clip(row.get("company_name"), 500),
                "company_id": companies.get(_ref("companies", row.get("company_id"))),
                "url": _clip(row.get("article_url"), 1000),
                "score": _lead_score(row.get("score")),
                "signal_at": row.get("published_at") or row.get("first_seen_at"),
                "payload": {
                    key: row[key] for key in ("trigger_type", "source") if row.get(key)
                },
            }
        )
    kept = []
    for row in rows:
        if row["company_name"] and await is_existing_client(db, row["company_name"]):
            ctx.report.add("leads_skipped_existing_client")
            continue
        kept.append(row)
    for start in range(0, len(kept), BATCH):
        stmt = insert(SalesLead).values(kept[start : start + BATCH])
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_sales_leads_fingerprint",
                # Status i odrzucenie należą do handlowca — drugi bieg ich nie cofa.
                set_={
                    name: stmt.excluded[name]
                    for name in (
                        "title",
                        "summary",
                        "company_name",
                        "url",
                        "score",
                        "signal_at",
                        "payload",
                    )
                },
            )
        )
    ctx.report.add("leads_imported", len(kept))


# ── Całość ───────────────────────────────────────────────────────────────


async def _referenced_companies(source: AtlasSource) -> set[str]:
    referenced: set[str] = set()
    for row in await source.deals():
        if row.get("company_id"):
            referenced.add(str(row["company_id"]))
    for row in await source.contacts():
        if row.get("primary_company_id"):
            referenced.add(str(row["primary_company_id"]))
    for row in await source.company_contacts():
        referenced.add(str(row["company_id"]))
    for loader in (source.company_activities, source.company_notes):
        for row in await loader():
            if row.get("company_id"):
                referenced.add(str(row["company_id"]))
    return referenced


async def run_import(
    db: AsyncSession, source: AtlasSource, *, now: Optional[datetime] = None
) -> ImportReport:
    """Cały import w transakcji wołającego — on decyduje o commit / rollback."""

    report = ImportReport()
    users = (
        await db.execute(
            select(func.lower(User.email), User.id).where(User.email.is_not(None))
        )
    ).all()
    email_by_atlas_user: dict[str, str] = {}
    for person in await source.people():
        if person.get("user_id") and person.get("email"):
            email_by_atlas_user[str(person["user_id"])] = (
                str(person["email"]).strip().lower()
            )
    ctx = _Context(
        users_by_email={email: user_id for email, user_id in users},
        email_by_atlas_user=email_by_atlas_user,
        report=report,
        now=now or datetime.now(timezone.utc),
    )
    stages = await _import_pipelines(db, source, ctx)
    companies = await _import_companies(
        db, source, ctx, await _referenced_companies(source)
    )
    contacts = await _import_contacts(db, source, ctx, companies)
    deals = await _import_deals(db, source, ctx, companies, contacts, stages)
    deal_company = dict(
        (
            await db.execute(
                select(SalesOpportunity.id, SalesOpportunity.company_id).where(
                    SalesOpportunity.id.in_(list(deals.values()) or [-1])
                )
            )
        ).all()
    )
    await _import_activities(db, source, ctx, companies, contacts, deals, deal_company)
    await _import_leads(db, source, ctx, companies)
    report.add("files_pending_storage_copy", await source.attachments_count())
    logger.info("[atlas-import] %s", report.as_dict())
    return report
