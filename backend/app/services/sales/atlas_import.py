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
* **Zmiany w NEXUSIE przeżywają kolejny bieg.** Każdy zapisany wiersz dostaje
  ``synced_at = updated_at = now`` (jeden znacznik na bieg). Wiersz, którego
  ``updated_at`` jest później niż ``synced_at`` (+1 s), ktoś zmienił w NEXUSIE —
  wtedy pola, które ludzie edytują (``PROTECTED``), zostają. Wiersz bez
  ``synced_at`` (pierwszy import, 28.10.2026) odświeża się w całości.
  Opiekun i wykonawca zadania nigdy nie są czyszczone (``COALESCE``).
* **Usuwanie tylko tego, co przyszło z Atlasa** (notatki z przygotowań
  kandydata, otwarte leady z ogłoszeń). Bieg na sucho robi to samo w
  transakcji, którą skrypt wycofuje — liczby są te same co przy ``--apply``.

Pliki (Supabase Storage) przenosi osobny krok — tu tylko je liczymy.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol

from sqlalchemy import Interval, and_, case, delete, func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
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

#: Pola, które ludzie edytują w NEXUSIE — drugi bieg ich nie nadpisuje, gdy
#: wiersz zmieniono po imporcie (``updated_at > synced_at``).
PROTECTED: dict[str, frozenset[str]] = {
    "sales_companies": frozenset(
        {
            "name",
            "lifecycle_stage",
            "status",
            "tier",
            "tags",
            "owner_user_id",
            "client_id",
            "parent_company_id",
            "description",
        }
    ),
    "sales_contacts": frozenset(
        {"full_name", "title", "email", "phone", "company_id", "notes"}
    ),
    "sales_opportunities": frozenset(
        {
            "stage_id",
            "pipeline_id",
            "status",
            "title",
            "value",
            "mrr_value",
            "one_off_value",
            "margin_pct",
            "probability",
            "expected_close_date",
            "tags",
            "owner_user_id",
            "lost_reason",
            "archived_at",
        }
    ),
    "sales_activities": frozenset(
        {"done_at", "assignee_user_id", "subject", "body", "due_at"}
    ),
}
#: Ile może minąć między zapisem importu a ``updated_at`` bez uznania wiersza
#: za zmieniony w NEXUSIE.
EDIT_TOLERANCE = literal_column("INTERVAL '1 second'", type_=Interval)

# Notatki Fireflies z rozmów przygotowujących KANDYDATA do spotkania z klientem
# trafiały w Atlasie do szansy, bo spotkanie dotyczyło klienta. To rekrutacja,
# nie sprzedaż: w treści są dane osobowe kandydata (doświadczenie, stawka,
# dostępność), których handlowcy nie powinni dostać. Rozpoznajemy je po
# tytule spotkania „Przygotowanie do spotkania z <klient> - <kandydat>”:
# na produkcji 28.10.2026 wszystkie 153 takie notatki miały uczestnika spoza
# firmy, a tylko 7 miało w tytule słowo „Klientem” (bez rozróżniania wielkości liter).
FIREFLIES_SUMMARY_MARKER = "podsumowanie spotkania (fireflies"
CANDIDATE_PREP_MARKER = "przygotowanie do spotkania z klientem"
CANDIDATE_PREP_TITLE = re.compile(r"\s*przygotowanie do spotkania z\s", re.IGNORECASE)
_FIREFLIES_TITLE = re.compile(r"\*\*Spotkanie:\*\*\s*([^\n]+)")

#: Kierunek wiadomości z Outlooka w Atlasie (``incoming``/``outgoing``) → NEXUS.
DIRECTIONS = {
    "in": "in",
    "incoming": "in",
    "inbound": "in",
    "received": "in",
    "out": "out",
    "outgoing": "out",
    "outbound": "out",
    "sent": "out",
}
#: ``external_source`` aktywności zsynchronizowanych z Outlooka w Atlasie.
MSGRAPH_PREFIX = "msgraph-"

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


def is_candidate_prep_title(title: Optional[str]) -> bool:
    """Tytuł spotkania przygotowującego kandydata do rozmowy u klienta."""

    return bool(CANDIDATE_PREP_TITLE.match(title or ""))


def is_candidate_prep_note(content: Optional[str]) -> bool:
    """Podsumowanie Fireflies z przygotowania kandydata (patrz znaczniki wyżej)."""

    text = content or ""
    lowered = text.lower()
    if FIREFLIES_SUMMARY_MARKER not in lowered:
        return False
    title = _FIREFLIES_TITLE.search(text)
    return CANDIDATE_PREP_MARKER in lowered or bool(
        title and is_candidate_prep_title(title.group(1))
    )


def _has_identifiers(company: Mapping[str, Any]) -> bool:
    """Domena, strona, NIP albo KRS — to firma, nawet gdy nazwa wygląda na nazwisko."""

    return any(
        str(company.get(key) or "").strip()
        for key in ("domain", "website_url", "nip", "krs_id", "krs")
    )


def _direction(value: Any) -> Optional[str]:
    return DIRECTIONS.get(str(value or "").strip().lower())


def _minutes(value: Any) -> Optional[int]:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if minutes >= 0 else None


def _whole(value: Any, limit: int) -> Optional[str]:
    """Identyfikator albo link: ucięty byłby błędny, więc za długi = brak."""

    text_value = str(value or "").strip()
    return text_value if text_value and len(text_value) <= limit else None


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


def _choice(
    value: Any,
    allowed: Sequence[str],
    report: Optional["ImportReport"] = None,
    name: str = "",
) -> Optional[str]:
    """Wartość ze słownika NEXUSA albo ``None``; spoza słownika liczy ``invalid_<name>``."""

    if isinstance(value, str) and value in allowed:
        return value
    if report is not None and value not in (None, ""):
        report.add(f"invalid_{name}")
    return None


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

    # Opcjonalne (starszy Atlas ich nie ma): ``company_attachments``,
    # ``company_team_members``, ``meeting_transcripts`` — czytane przez
    # ``_optional``; brak metody albo tabeli = pusta lista.


async def _optional(source: AtlasSource, name: str) -> list[dict[str, Any]]:
    loader = getattr(source, name, None)
    return list(await loader()) if loader is not None else []


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
    #: Opiekun z Atlasa po rozwiązaniu na konto NEXUSA (id Atlasa → user id).
    company_owner: dict[str, Optional[int]] = field(default_factory=dict)
    deal_owner: dict[str, Optional[int]] = field(default_factory=dict)
    #: Firma scalona w NEXUSIE → firma docelowa (po całym łańcuchu scaleń).
    merged: dict[int, int] = field(default_factory=dict)
    #: Kontakty, które ten import już kiedyś zsynchronizował (przed biegiem).
    synced_contact_refs: set[str] = field(default_factory=set)


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


def _edited_in_nexus(table: Any) -> Any:
    """Wiersz zmieniony w NEXUSIE po ostatnim zapisie importu.

    ``synced_at IS NULL`` (wiersze z pierwszego importu) = niezmieniony.
    """

    return and_(
        table.c.synced_at.is_not(None),
        table.c.updated_at > table.c.synced_at + EDIT_TOLERANCE,
    )


async def _upsert(
    db: AsyncSession,
    model: Any,
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    fill: Iterable[str] = (),
    custom: Optional[Mapping[str, Callable[[Any, Any], Any]]] = None,
) -> dict[str, int]:
    """Wstaw albo zaktualizuj po ``external_ref``; zwraca ``external_ref → id``.

    * ``synced_at = updated_at = now`` w każdym wierszu;
    * kolumny z ``PROTECTED`` w wierszu zmienionym w NEXUSIE zostają (także
      ``updated_at`` i ``synced_at``, żeby kolejny bieg nadal widział zmianę);
    * ``fill`` — ``COALESCE(obecna, nowa)``: import uzupełnia, nigdy nie czyści
      (opiekun, wykonawca zadania);
    * ``custom`` — kolumna → ``f(tabela, excluded)`` dla reguł spoza tych dwóch.
    """

    ids: dict[str, int] = {}
    table = model.__table__
    keep = {"id", "external_ref", "created_at"}
    fill = set(fill)
    tracked = "synced_at" in table.c
    protected = PROTECTED.get(table.name, frozenset()) | {"updated_at", "synced_at"}
    edited = _edited_in_nexus(table) if tracked else None
    if tracked:
        for row in rows:
            row["synced_at"] = row["updated_at"] = now
    for start in range(0, len(rows), BATCH):
        chunk = rows[start : start + BATCH]
        if not chunk:
            continue
        stmt = insert(model).values(chunk)
        update = {}
        for column in chunk[0]:
            if column in keep:
                continue
            value = stmt.excluded[column]
            if custom and column in custom:
                value = custom[column](table, stmt.excluded)
            elif column in fill:
                value = func.coalesce(table.c[column], value)
            if edited is not None and column in protected:
                value = case((edited, table.c[column]), else_=value)
            update[column] = value
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
    report = ctx.report
    owner_user_id = _user_id(
        ctx,
        email=company.get("owner_email"),
        atlas_user=company.get("owner_user_id"),
    )
    ctx.company_owner[str(company["id"])] = owner_user_id
    # Opiekun bez konta w NEXUSIE zostaje jako etykieta (Atlas: ``owner_name``,
    # po imporcie z Pipedrive ``custom_fields.pipedrive_owner_name``).
    owner_label = None
    if owner_user_id is None:
        owner_label = _clip(company.get("owner_name"), 120) or _clip(
            _dict(company.get("custom_fields")).get("pipedrive_owner_name"), 120
        )
        if owner_label:
            report.add("companies_owner_label")
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
            company.get("lifecycle_stage"),
            schema.COMPANY_LIFECYCLES,
            report,
            "lifecycle_stage",
        )
        or "lead",
        "tier": _choice(
            company.get("account_tier"), schema.COMPANY_TIERS, report, "tier"
        ),
        "status": _choice(
            company.get("status"), schema.COMPANY_STATUSES, report, "company_status"
        )
        or "active",
        "tags": tags,
        "source": _clip(company.get("source") or "atlas", 60),
        "owner_user_id": owner_user_id,
        "owner_label": owner_label,
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
            if not _has_identifiers(company):
                ctx.report.add("companies_skipped_junk")
                continue
            ctx.report.add("companies_kept_by_domain_or_registry")
        if junk:
            ctx.report.add("companies_review")
        rows.append(_company_row(company, ctx, review=junk))
        if company.get("parent_company_id"):
            parents.append((atlas_id, str(company["parent_company_id"])))
    ids = await _upsert(
        db,
        SalesCompany,
        rows,
        now=ctx.now,
        fill={"owner_user_id"},
        # Etykieta opiekuna tylko, dopóki firma nie ma opiekuna z kontem
        # (przypisanego w NEXUSIE albo rozwiązanego z Atlasa).
        custom={
            "owner_label": lambda table, new: case(
                (
                    func.coalesce(table.c.owner_user_id, new.owner_user_id).is_not(
                        None
                    ),
                    table.c.owner_label,
                ),
                else_=new.owner_label,
            ),
            # Klucze dopisane w NEXUSIE (``merged_into`` po scaleniu) zostają,
            # klucz ``atlas`` idzie za Atlasem.
            "custom_fields": lambda table, new: func.coalesce(
                table.c.custom_fields, text("'{}'::jsonb")
            ).op("||")(new.custom_fields),
        },
    )
    ctx.report.add("companies_imported", len(ids))

    # Firma scalona w NEXUSIE zostaje w archiwum; wszystko, co import do niej
    # przypina (osoby, powiązania, szanse, aktywności, leady), idzie do
    # firmy docelowej. ``own`` to wiersze samych firm (rodzic, klient).
    own = ids
    ctx.merged = await company_merge_targets(db, ctx.report)
    ids = {
        ref: ctx.merged.get(company_id, company_id) for ref, company_id in own.items()
    }
    ctx.report.add(
        "companies_redirected_to_merge_target",
        sum(1 for ref in own if own[ref] != ids[ref]),
    )

    # Dalsze zapisy importu dotyczą tylko wierszy zapisanych w tym biegu
    # i niezmienionych w NEXUSIE (``synced_at`` = znacznik biegu); ustawiają
    # ``updated_at`` na ten sam znacznik, żeby nie udawać edycji człowieka.
    written_now = SalesCompany.synced_at == ctx.now
    linked = 0
    for child, parent in parents:
        child_id = own.get(_ref("companies", child))
        parent_id = ids.get(_ref("companies", parent))
        if child_id and parent_id and child_id != parent_id:
            await db.execute(
                SalesCompany.__table__.update()
                .where(SalesCompany.id == child_id, written_now)
                .values(parent_company_id=parent_id, updated_at=ctx.now)
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
        company_id = own.get(row["external_ref"])
        client_id = by_nip.get(row["nip"] or "") or by_name.get(row["normalized_name"])
        if company_id and client_id and client_id not in taken:
            await db.execute(
                SalesCompany.__table__.update()
                .where(
                    SalesCompany.id == company_id,
                    SalesCompany.client_id.is_(None),
                    written_now,
                )
                .values(client_id=client_id, updated_at=ctx.now)
            )
            taken.add(client_id)
            ctx.report.add("companies_linked_to_clients")
    return ids


# ── Kontakty ─────────────────────────────────────────────────────────────


async def _import_contacts(
    db: AsyncSession, source: AtlasSource, ctx: _Context, companies: Mapping[str, int]
) -> dict[str, int]:
    links_by_contact: dict[str, list[Mapping[str, Any]]] = {}
    for link in await source.company_contacts():
        links_by_contact.setdefault(str(link["contact_id"]), []).append(link)

    def primary_company(contact: Mapping[str, Any]) -> Optional[int]:
        """Główna firma: główny pracodawca obecnie → obecna → ``primary_company_id`` → pierwsza."""

        links = links_by_contact.get(str(contact["id"]), [])
        current = [link for link in links if link.get("is_current", True)]
        candidates = [
            *(
                link["company_id"]
                for link in current
                if link.get("is_primary_employer")
            ),
            *(link["company_id"] for link in current),
            contact.get("primary_company_id"),
            *(link["company_id"] for link in links),
        ]
        for atlas_company in candidates:
            company_id = companies.get(_ref("companies", atlas_company))
            if atlas_company and company_id:
                return company_id
        return None

    rows = []
    for contact in await source.contacts():
        atlas_id = str(contact["id"])
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
                "company_id": primary_company(contact),
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
    ids = await _upsert(db, SalesContact, rows, now=ctx.now)
    ctx.report.add("contacts_imported", len(ids))
    await _import_company_contacts(db, ctx, companies, ids, links_by_contact)
    return ids


async def _import_company_contacts(
    db: AsyncSession,
    ctx: _Context,
    companies: Mapping[str, int],
    contacts: Mapping[str, int],
    links_by_contact: Mapping[str, list[Mapping[str, Any]]],
) -> None:
    """Osoba w wielu firmach (Atlas ``company_contacts``) + powiązanie z firmą główną.

    Tabela nie ma ``synced_at``, więc import tylko uzupełnia tekst (``COALESCE``)
    i może zakończyć zatrudnienie (``is_current``), niczego nie czyści.
    """

    rows: dict[tuple[int, int], dict[str, Any]] = {}
    for atlas_contact, links in links_by_contact.items():
        contact_id = contacts.get(_ref("contacts", atlas_contact))
        for link in links:
            company_id = companies.get(_ref("companies", link.get("company_id")))
            if contact_id is None or company_id is None:
                ctx.report.add("company_contacts_skipped_unresolved")
                continue
            rows[(company_id, contact_id)] = {
                "company_id": company_id,
                "contact_id": contact_id,
                "role": _clip(link.get("role"), 60),
                "title": _clip(link.get("title_at_company"), 255),
                "is_primary": False,
                "is_current": bool(link.get("is_current", True)),
                "started_at": link.get("started_at"),
                "ended_at": link.get("ended_at"),
                # Atlas ma klucz złożony (firma, osoba) — bez własnego id.
                "external_ref": _ref("company_contacts", link["id"])
                if link.get("id")
                else "atlas:company_contacts",
            }
    table = SalesCompanyContact.__table__
    # Powiązanie usunięte w NEXUSIE nie może wracać przy każdym biegu, a tabela
    # nie ma ``synced_at``. Reguła: nowe powiązania dostają tylko osoby, których
    # ten import jeszcze nie synchronizował (pierwszy import 28.10 nie znał
    # ``company_contacts``, nowe osoby). Osobie już zsynchronizowanej import
    # tylko poprawia istniejące powiązania. Cena: powiązanie dodane w Atlasie
    # po jej synchronizacji nie przyjdzie — Atlas jest wygaszany.
    synced = {contacts[ref] for ref in ctx.synced_contact_refs if ref in contacts}
    existing = set()
    if synced:
        existing = set(
            (
                await db.execute(
                    select(table.c.company_id, table.c.contact_id).where(
                        table.c.contact_id.in_(list(synced))
                    )
                )
            ).all()
        )
    for key in [key for key in rows if key[1] in synced and key not in existing]:
        del rows[key]
        ctx.report.add("company_contacts_not_reinserted")
    values = list(rows.values())
    for start in range(0, len(values), BATCH):
        stmt = insert(SalesCompanyContact).values(values[start : start + BATCH])
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["company_id", "contact_id"],
                set_={
                    **{
                        name: func.coalesce(table.c[name], stmt.excluded[name])
                        for name in (
                            "role",
                            "title",
                            "started_at",
                            "ended_at",
                            "external_ref",
                        )
                    },
                    "is_current": and_(table.c.is_current, stmt.excluded.is_current),
                },
            )
        )
    ctx.report.add("company_contacts_imported", len(values))

    # Firma główna kontaktu (``sales_contacts.company_id``, po ewentualnej
    # zmianie w NEXUSIE) zawsze ma powiązanie z ``is_primary``; inne go tracą.
    contact_ids = list(contacts.values())
    if not contact_ids:
        return
    contact_table = SalesContact.__table__
    primary = insert(SalesCompanyContact).from_select(
        ["company_id", "contact_id", "title", "is_primary"],
        select(
            contact_table.c.company_id,
            contact_table.c.id,
            contact_table.c.title,
            literal_column("true"),
        ).where(
            contact_table.c.id.in_(contact_ids),
            contact_table.c.company_id.is_not(None),
        ),
    )
    result = await db.execute(
        primary.on_conflict_do_update(
            index_elements=["company_id", "contact_id"],
            set_={"is_primary": True},
        )
    )
    ctx.report.add("company_contacts_primary", result.rowcount or 0)
    await db.execute(
        table.update()
        .where(
            table.c.contact_id == contact_table.c.id,
            contact_table.c.id.in_(contact_ids),
            table.c.is_primary.is_(True),
            table.c.company_id.is_distinct_from(contact_table.c.company_id),
        )
        .values(is_primary=False)
    )


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
        return ctx.merged.get(existing, existing)
    # Skrót, nie obcięcie: dwie długie nazwy o wspólnym początku dawały ten sam
    # klucz i druga szansa dostawała firmę pierwszej.
    ref = _ref("deal-company", hashlib.sha256(canonical.encode()).hexdigest()[:40])
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
        now=ctx.now,
    )
    created = {key: ctx.merged.get(value, value) for key, value in created.items()}
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
        status = (
            _choice(
                deal.get("status"),
                schema.OPPORTUNITY_STATUSES,
                ctx.report,
                "opportunity_status",
            )
            or "open"
        )
        owner_user_id = _user_id(
            ctx,
            email=deal.get("owner_email"),
            atlas_user=deal.get("owner_user_id"),
        )
        ctx.deal_owner[str(deal["id"])] = owner_user_id
        custom = _dict(deal.get("custom_fields"))
        # `contact_name` / `contact_role` to osoba u klienta i jej stanowisko
        # („CTO”) — nie rola do obsadzenia, więc nie trafia do `roles`.
        for key in ("products", "subscription_items", "contact_name", "contact_role"):
            if deal.get(key):
                custom[key] = deal[key]
        roles: list[dict[str, Any]] = []
        rows.append(
            {
                "external_ref": _ref("deals", deal["id"]),
                "company_id": company_id,
                "pipeline_id": stage[0],
                "stage_id": stage[1],
                "title": _clip(deal.get("title"), 255) or "Szansa z Atlasa",
                "description": deal.get("description") or None,
                "status": status,
                "service_line": _choice(
                    deal.get("service_line"),
                    schema.SERVICE_LINES,
                    ctx.report,
                    "service_line",
                ),
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
                "owner_user_id": owner_user_id,
                "last_activity_at": deal.get("last_activity_at"),
                "keep_open_until": deal.get("keep_open_until"),
                "archived_at": deal.get("archived_at"),
                "archived_reason": _clip(deal.get("archived_reason"), 255),
                "created_at": deal.get("created_at") or ctx.now,
            }
        )
    ids = await _upsert(db, SalesOpportunity, rows, now=ctx.now, fill={"owner_user_id"})
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
                    "role": _choice(
                        link.get("role"),
                        schema.CONTACT_ROLES,
                        ctx.report,
                        "contact_role",
                    ),
                }
            )
    for start in range(0, len(links), BATCH):
        stmt = insert(SalesOpportunityContact).values(links[start : start + BATCH])
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="pk_sales_opportunity_contacts",
                # Rola spoza słownika (NULL) nie czyści roli nadanej w NEXUSIE.
                set_={
                    "role": func.coalesce(
                        stmt.excluded.role, SalesOpportunityContact.__table__.c.role
                    )
                },
            )
        )
    ctx.report.add("opportunity_contacts_imported", len(links))
    return ids


# ── Aktywności i notatki ─────────────────────────────────────────────────


def _activity_kind(value: Any, report: ImportReport) -> str:
    return _choice(value, schema.ACTIVITY_KINDS, report, "activity_kind") or "note"


#: Każdy wiersz aktywności ma te same klucze (insert wielowierszowy).
_ACTIVITY_DEFAULTS: dict[str, Any] = {
    "contact_id": None,
    "opportunity_id": None,
    "company_id": None,
    "subject": None,
    "body": None,
    "priority": None,
    "due_at": None,
    "occurred_at": None,
    "done_at": None,
    "is_pinned": False,
    "assignee_user_id": None,
    "external_source": "atlas",
    "external_id": None,
    "web_link": None,
    "direction": None,
    "duration_minutes": None,
}


def _transcript_body(row: Mapping[str, Any]) -> Optional[str]:
    """Podsumowanie, zadania do zrobienia, potem pełny zapis rozmowy."""

    parts = []
    overview = (row.get("summary_overview") or "").strip()
    if overview:
        parts.append(overview)
    items = [str(item).strip() for item in _list(row.get("summary_action_items"))]
    items = [item for item in items if item]
    if items:
        parts.append("Do zrobienia:\n" + "\n".join(f"- {item}" for item in items))
    head = "\n\n".join(parts)
    transcript = (row.get("transcript_text") or "").strip()
    if transcript:
        return f"{head}\n\n---\n\n{transcript}" if head else transcript
    return head or None


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
    report = ctx.report

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
        kind = _activity_kind(row.get("activity_type"), report)
        done_at = row.get("done_at") or (
            row.get("occurred_at") if row.get("done") else None
        )
        # Atlas (Task Center) liczy wykonawcę przy odczycie: właściciel wiersza,
        # a przy szansie jej opiekun.
        assignee = _user_id(ctx, atlas_user=row.get("owner_user_id")) or (
            ctx.deal_owner.get(str(row.get("deal_id")))
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
                "priority": _choice(
                    row.get("priority"), schema.PRIORITIES, report, "priority"
                ),
                "due_at": row.get("due_date"),
                "occurred_at": row.get("occurred_at"),
                "done_at": done_at if (row.get("done") or kind != "task") else None,
                "assignee_user_id": assignee,
                "duration_minutes": _minutes(row.get("duration_minutes")),
            }
        )
    for row in await source.company_activities():
        opportunity_id = deals.get(_ref("deals", row.get("deal_id")))
        kind = _activity_kind(row.get("activity_type"), report)
        base = common(row, "company_activities")
        external_source = _clip(row.get("external_source") or "atlas", 40)
        synced = (external_source or "").startswith(MSGRAPH_PREFIX)
        if synced:
            # Outlook: Atlas trzyma czas wiadomości/spotkania w ``due_date``
            # (ATLAS deals.py) — to historia, nie termin.
            occurred = row.get("due_date") or row.get("created_at")
            due_at, done_at = None, occurred
        else:
            occurred = row.get("created_at")
            due_at = row.get("due_date")
            open_item = kind in schema.TASK_KINDS and not row.get("done")
            done_at = None if open_item else (row.get("done_at") or occurred)
        assignee = None
        if kind in schema.TASK_KINDS and not row.get("done") and not synced:
            assignee = base["created_by_user_id"] or ctx.company_owner.get(
                str(row.get("company_id"))
            )
        direction = _direction(row.get("direction"))
        if row.get("direction") and direction is None:
            report.add("invalid_direction")
        rows.append(
            {
                **base,
                "kind": kind,
                "opportunity_id": opportunity_id,
                "company_id": companies.get(_ref("companies", row.get("company_id"))),
                "subject": _clip(row.get("subject"), 500),
                "body": row.get("description") or None,
                "due_at": due_at,
                "occurred_at": occurred,
                "done_at": done_at,
                "assignee_user_id": assignee,
                "external_source": external_source,
                "external_id": _whole(row.get("external_id"), 255),
                "web_link": _whole(row.get("external_web_link"), 2000),
                "direction": direction,
                "duration_minutes": _minutes(row.get("duration_minutes")),
            }
        )
        if row.get("external_id") and rows[-1]["external_id"] is None:
            report.add("activities_external_id_too_long")

    prep_refs: list[str] = []
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
                report.add("notes_skipped_empty")
                continue
            if is_candidate_prep_note(content):
                report.add("notes_candidate_prep_skipped")
                prep_refs.append(_ref(table, row["id"]))
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
                    "body": content,
                    "occurred_at": row.get("created_at"),
                    "done_at": row.get("created_at"),
                    "is_pinned": bool(row.get("is_pinned")),
                }
            )

    for row in await _optional(source, "meeting_transcripts"):
        if not row.get("deal_id") or row.get("status") == "internal":
            continue
        title = row.get("meeting_title") or ""
        if (
            is_candidate_prep_title(title)
            or CANDIDATE_PREP_MARKER
            in f"{title}\n{row.get('summary_overview') or ''}".lower()
        ):
            report.add("transcripts_candidate_prep_skipped")
            continue
        opportunity_id = deals.get(_ref("deals", row.get("deal_id")))
        if opportunity_id is None:
            report.add("transcripts_skipped_deal_not_imported")
            continue
        when = row.get("meeting_date") or row.get("created_at")
        rows.append(
            {
                "external_ref": _ref("meeting_transcripts", row["id"]),
                "created_by_user_id": _user_id(ctx, email=row.get("host_email")),
                "created_at": row.get("created_at") or when or ctx.now,
                "kind": "meeting",
                "opportunity_id": opportunity_id,
                "company_id": deal_company.get(opportunity_id),
                "subject": _clip(title, 500),
                "body": _transcript_body(row),
                "occurred_at": when,
                "done_at": when,
                "external_source": "fireflies",
                "duration_minutes": _minutes(row.get("duration_minutes")),
            }
        )
        report.add("transcripts_imported")

    rows = [{**_ACTIVITY_DEFAULTS, **row} for row in rows]
    ids = await _upsert(db, SalesActivity, rows, now=ctx.now, fill={"assignee_user_id"})
    report.add("activities_imported", len(ids))

    # Notatki z przygotowania kandydata z pierwszego importu — tylko te z Atlasa.
    removed = 0
    for start in range(0, len(prep_refs), BATCH):
        result = await db.execute(
            delete(SalesActivity).where(
                SalesActivity.external_source == "atlas",
                SalesActivity.external_ref.in_(prep_refs[start : start + BATCH]),
            )
        )
        removed += result.rowcount or 0
    report.add("notes_candidate_prep_removed", removed)


# ── Leady ────────────────────────────────────────────────────────────────

#: Otwarte statusy leadów Atlasa → status skrzynki NEXUSA. Zamienione,
#: odrzucone i zarchiwizowane nie przechodzą — ich ślad to szanse.
_OPEN_LEAD_STATUSES = {
    "new": "new",
    "reviewing": "new",
    "qualified": "new",
    "contacted": "contacted",
}


#: Klucze kontaktu bezpośredniego, których nie kopiujemy z ``person`` leada
#: LinkedIn (skrzynka leadów to sygnał o firmie; kontakt zakłada handlowiec).
_PERSON_CONTACT_KEYS = re.compile(r"e-?mail|phone|telefon|mobile", re.IGNORECASE)


def _structured(row: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    """Słowniki z Atlasa w całości (``person`` bez e-maili i telefonów)."""

    out: dict[str, Any] = {}
    for key in keys:
        value = _dict(row.get(key))
        if key == "person":
            value = {
                k: v for k, v in value.items() if not _PERSON_CONTACT_KEYS.search(k)
            }
        if value:
            out[key] = value
    return out


def _lead_score(value: Any) -> int:
    try:
        return max(0, min(100, int(value or 0)))
    except (TypeError, ValueError):
        return 0


async def _import_leads(
    db: AsyncSession, source: AtlasSource, ctx: _Context, companies: Mapping[str, int]
) -> None:
    """LinkedIn i prasa z Atlasa → skrzynka leadów (ogłoszenia już nie).

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
                    **{
                        key: row[key]
                        for key in ("persona_tag", "grade", "recommended_offer")
                        if row.get(key)
                    },
                    **_structured(row, "person", "score_breakdown"),
                },
            }
        )
    for row in await source.press_signals():
        if row.get("source_category") == "job_board":
            # Skan ogłoszeń odrzucony 27.10.2026 (celował w firmy spoza IT).
            ctx.report.add("leads_skipped_job_board")
            continue
        status = _OPEN_LEAD_STATUSES.get(str(row.get("status") or "new"))
        if status is None or row.get("archived_at"):
            ctx.report.add("leads_skipped_closed")
            continue
        rows.append(
            {
                "fingerprint": _ref("press_signals", row["id"]),
                "source": "press",
                "status": status,
                "title": _clip(row.get("article_title"), 500) or "Sygnał z prasy",
                "summary": row.get("ai_summary") or None,
                "company_name": _clip(row.get("company_name"), 500),
                "company_id": companies.get(_ref("companies", row.get("company_id"))),
                "url": _clip(row.get("article_url"), 1000),
                "score": _lead_score(row.get("score")),
                "signal_at": row.get("published_at") or row.get("first_seen_at"),
                "payload": {
                    **{
                        key: row[key]
                        for key in ("trigger_type", "source")
                        if row.get(key)
                    },
                    **_structured(row, "trigger_details", "score_breakdown"),
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

    # Otwarte leady z ogłoszeń z pierwszego importu — decyzje handlowca
    # (kontakt, odrzucenie, szansa) zostają.
    removed = await db.execute(
        delete(SalesLead).where(
            SalesLead.source == "job_board",
            SalesLead.status == "new",
            SalesLead.fingerprint.like("atlas:press_signals:%"),
        )
    )
    ctx.report.add("leads_job_board_removed", removed.rowcount or 0)


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
    for loader in (
        source.company_activities,
        source.company_notes,
        source.linkedin_leads,
        source.press_signals,
    ):
        for row in await loader():
            if row.get("company_id"):
                referenced.add(str(row["company_id"]))
    for name in ("company_attachments", "company_team_members"):
        for row in await _optional(source, name):
            if row.get("company_id"):
                referenced.add(str(row["company_id"]))
    return referenced


async def company_merge_targets(
    db: AsyncSession, report: Optional[ImportReport] = None
) -> dict[int, int]:
    """Firma scalona (``custom_fields.merged_into``) → ostateczna firma docelowa.

    Łańcuch A→B→C daje A→C. Cykl (nie powinien powstać, ale dane bywają
    ręcznie poprawiane) zostawia firmy bez przekierowania i liczy
    ``companies_merge_cycle``.
    """

    rows = await db.execute(
        select(SalesCompany.id, SalesCompany.custom_fields["merged_into"].astext).where(
            SalesCompany.custom_fields.has_key("merged_into")
        )
    )
    direct: dict[int, int] = {}
    for company_id, target in rows.all():
        try:
            direct[company_id] = int(target)
        except (TypeError, ValueError):
            continue
    final: dict[int, int] = {}
    for start in direct:
        seen, current = {start}, start
        while current in direct:
            current = direct[current]
            if current in seen:
                if report is not None:
                    report.add("companies_merge_cycle")
                break
            seen.add(current)
        else:
            final[start] = current
    return final


async def _baseline_first_import(db: AsyncSession, report: ImportReport) -> None:
    """Wiersze z pierwszego importu (28.10.2026, bez ``synced_at``) dostają znacznik.

    Pierwszy import zapisał wszystko w jednej transakcji, więc wspólny
    ``updated_at`` (najmniejszy w tabeli) to chwila importu; wiersz z późniejszym
    ``updated_at`` zmieniono w NEXUSIE i jego pola chronimy. Biegnie w tej samej
    transakcji co import — na sucho jest wycofywane.
    """

    for model in (SalesCompany, SalesContact, SalesOpportunity, SalesActivity):
        table = model.__table__
        first_import = and_(
            table.c.synced_at.is_(None), table.c.external_ref.like("atlas:%")
        )
        baseline = (
            select(func.min(table.c.updated_at)).where(first_import).scalar_subquery()
        )
        # ``updated_at`` podany wprost — inaczej ``onupdate`` zatarłby różnicę.
        await db.execute(
            table.update()
            .where(first_import)
            .values(synced_at=baseline, updated_at=table.c.updated_at)
        )
        edited = await db.scalar(
            select(func.count())
            .select_from(table)
            .where(table.c.external_ref.like("atlas:%"), _edited_in_nexus(table))
        )
        report.add(f"edited_in_nexus_{table.name}", int(edited or 0))


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
    ctx.synced_contact_refs = set(
        (
            await db.execute(
                select(SalesContact.external_ref).where(
                    SalesContact.external_ref.like("atlas:%"),
                    SalesContact.synced_at.is_not(None),
                )
            )
        ).scalars()
    )
    await _baseline_first_import(db, report)
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
