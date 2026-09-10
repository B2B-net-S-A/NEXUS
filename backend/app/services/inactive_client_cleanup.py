"""Jednorazowe czyszczenie zakładki „Nieaktywni klienci".

Decyzja dla każdego klienta z zakładki ma trzy wyniki:

* **keep** — którekolwiek z ośmiu źródeł „śladu współpracy" jest niepuste.
  Klient zostaje dokładnie taki, jaki był; operacja go nie dotyka.
* **hold** (lista B) — osiem źródeł jest pustych, ale klient ma INNE dane,
  które usunięcie by skasowało albo osierociło (kontakty, przypisania TAC/DL,
  reguła CV, wpisy dziennika spoza czysto technicznych, zakres w innej
  zakładce, NDA, wskazanie w konfiguracji…). Nie ruszamy go — decyzja
  należy do człowieka, a raport mówi, co znaleźliśmy.
* **delete** (lista A) — ani śladu współpracy, ani innych powiązań. Klient
  jest usuwany trwale.

„Inne powiązania" NIE są listą pisaną ręcznie. Każdy klucz obcy w bazie,
który wskazuje na ``clients.id``, jest odczytywany z katalogu Postgresa
w chwili uruchomienia. Ręczna lista starzałaby się z każdą migracją — a tabela
dopisana za pół roku, której ktoś zapomniał tu wpisać, oznaczałaby cichą
kaskadę. Z katalogu nie da się jej przeoczyć.

Trzy tabele są celowo pomijane jako powiązania, bo SĄ wpisem w katalogu, a nie
danymi o współpracy: zakres portfela (to on umieszcza klienta w zakładce),
aliasy nazwy i wiersz audytu manifestu portfela (ten ostatni nie znika — FK
zeruje powiązanie, a wiersz dostaje znacznik ``purged_at``; patrz inwariant
w ``client_portfolio_import``).

Ten moduł tylko CZYTA. Wykonanie, raport i nagrobki są w
``inactive_client_cleanup_run`` — jednorazowe (UNIQUE po ``kind`` + sprawdzenie
pod blokadą doradczą), uruchamiane wyłącznie jawnym żądaniem administratora,
nigdy przy zmianie statusu.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Collection, Iterable, Literal, Optional

from sqlalchemy import Text, cast, distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.client import Client
from app.models.client_cleanup import ClientCleanupRun
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)

logger = logging.getLogger(__name__)

CLEANUP_KIND = "inactive_clients_v1"

Verdict = Literal["keep", "hold", "delete"]

# ── Osiem źródeł „śladu współpracy" (kolejność = kolejność z ticketu) ────────

SOURCE_LABELS: dict[str, str] = {
    "active_projects": "Aktywne projekty",
    "closed_projects": "Zamknięte projekty",
    "archived_consultants": "Archiwalni konsultanci",
    "orders": "Zamówienia",
    "contracts": "Umowy / kontrakty",
    "notes": "Notatki w profilu",
    "sales_materials": "Materiały sprzedażowe",
    "cooperation_stats": "Statystyki współpracy",
}

# Tabele wskazujące na klienta, które należą do któregoś z ośmiu źródeł.
# Rekrutacje (``jobs.client_id``) liczymy osobnym zapytaniem, bo źródła 1 i 2
# dzielą je po statusie; wpis tutaj pilnuje, żeby ewentualna inna kolumna
# ``jobs`` wskazująca na klienta też nie trafiła do „innych powiązań".
_SOURCE_BY_TABLE: dict[str, str] = {
    "jobs": "active_projects",
    "contracts": "contracts",
    # Zamówienia na WSZYSTKICH etapach: okresowe, grupy MD/kosztowe i sprawy
    # offboardingowe po zakończeniu współpracy.
    "client_orders": "orders",
    "client_order_groups": "orders",
    "client_order_offboarding_cases": "orders",
    # Umowy w dowolnym statusie: kontrakty, umowy ramowe, wygenerowane B2B.
    "client_framework_contracts": "contracts",
    "b2b_generated_contracts": "contracts",
    "b2b_generated_contract_status_events": "contracts",
    # Sekcja „Materiały sprzedażowe" w profilu: one-pagery + warunki umowy.
    "client_one_pagers": "sales_materials",
    "client_contract_terms": "sales_materials",
    # Historia przychodowa z DynaReportera to też statystyka współpracy.
    "dr_clients": "cooperation_stats",
    "dr_placement_details": "cooperation_stats",
}

# Wpis w katalogu, nie dane o współpracy — patrz docstring modułu.
_STRUCTURAL_REFERENCES: frozenset[tuple[str, str]] = frozenset(
    {
        ("client_portfolio_scopes", "client_id"),
        ("client_aliases", "client_id"),
        ("client_import_rows", "matched_client_id"),
    }
)

# Czytelne nazwy dla raportu. Brak wpisu → surowa nazwa tabeli, co nadal
# mówi człowiekowi, gdzie patrzeć.
_RELATED_LABELS: dict[str, str] = {
    "contacts": "Kontakty (osoby po stronie klienta)",
    "client_tac_assignments": "Przypisani TAC",
    "delivery_lead_client_assignments": "Przypisani Delivery Leadzi",
    "client_knowledge": "Wiedza o kliencie",
    "client_playbooks": "Karta klienta (zasady współpracy)",
    "client_playbook_events": "Historia karty klienta",
    "client_cv_rules": "Reguła CV klienta",
    "client_cv_rule_events": "Historia reguły CV",
    "client_cv_rule_previews": "CV próbne reguły",
    "client_cv_rule_publications": "Publikacje reguły CV",
    "client_required_documents": "Wymagane dokumenty",
    "rate_cards": "Cennik (rate cards)",
    "calendar_events": "Wydarzenia w kalendarzu",
    "candidate_conflicts": "Konflikty kandydatów u klienta",
    "candidate_search_runs": "Wyszukiwania Talent Radar",
    "cv_generated_documents": "Wygenerowane CV",
    "dl_alerts": "Alerty Delivery Leada",
    "financial_adjustments": "Korekty finansowe",
    "interview_questions": "Pytania rekrutacyjne",
    "order_mail_documents": "Dokumenty z maila zamówień",
    "pipeline_templates": "Szablony pipeline'u",
    "candidate_rate_history": "Historia stawek",
    "recruitment_processes": "Procesy rekrutacyjne",
    "scoring_weight_profiles": "Profile wag dopasowania",
    "client_stage_notification_overrides": "Ustawienia powiadomień etapów",
    "workflow_definitions": "Definicje workflow klienta",
    "clients": "Scalone duplikaty wskazujące na tego klienta",
}

_ON_DELETE_EFFECT: dict[str, str] = {
    "c": "zostałyby usunięte razem z klientem",
    "n": "straciłyby powiązanie z klientem",
    "d": "straciłyby powiązanie z klientem",
    "r": "blokują usunięcie",
    "a": "blokują usunięcie",
}

# Wpisy dziennika opisujące SAM rekord klienta albo jego miejsce w katalogu —
# import manifestu, założenie, edycja nazwy, przesunięcie między zakładkami.
# Nie są śladem współpracy i nie giną przy usunięciu (dziennik nie ma FK).
# Każda INNA akcja (np. ``one_pager_deleted``, ``required_doc_uploaded``)
# mówi, że coś się z klientem działo, więc wstrzymuje usunięcie.
_ADMINISTRATIVE_ACTIVITY_ACTIONS: frozenset[str] = frozenset(
    {
        "created",
        "updated",
        "client_portfolio_excel_imported",
        "portfolio_scope_created",
        "portfolio_scope_updated",
        "portfolio_scope_placement_updated",
        "portfolio_scope_archived",
    }
)

# Czytelne nazwy akcji dziennika dla listy B. Nieznana akcja → surowy kod
# (lepszy niż nic: człowiek i tak znajdzie ją w dzienniku).
_ACTIVITY_ACTION_LABELS: dict[str, str] = {
    "merged": "scalenie klienta",
    "deleted": "usunięcie klienta",
    "one_pager_uploaded": "wgranie one-pagera",
    "one_pager_deleted": "usunięcie one-pagera",
    "contract_terms_updated": "zmiana warunków umowy",
    "required_doc_created": "dodanie wymaganego dokumentu",
    "required_doc_uploaded": "wgranie wymaganego dokumentu",
    "required_doc_deleted": "usunięcie wymaganego dokumentu",
    "required_docs_templates_applied": "zastosowanie szablonów dokumentów",
    "order_created": "utworzenie zamówienia",
    "order_updated": "zmiana zamówienia",
    "order_cancelled": "anulowanie zamówienia",
    "order_file_uploaded": "wgranie pliku zamówienia",
    "order_file_deleted": "usunięcie pliku zamówienia",
    "order_group_created": "utworzenie zamówienia grupowego",
    "order_group_extended": "przedłużenie zamówienia grupowego",
    "order_group_deleted": "usunięcie zamówienia grupowego",
    "order_group_line_deleted": "usunięcie linii zamówienia",
    "order_group_file_replaced": "podmiana pliku zamówienia",
    "order_group_file_deleted": "usunięcie pliku zamówienia",
    "order_line_swapped": "zamiana kontraktora",
    "contract_with_order_created": "utworzenie kontraktu z zamówieniem",
    "nordea_orders_imported": "import zamówień Nordea",
    "framework_contract_created": "utworzenie umowy ramowej",
    "framework_contract_updated": "zmiana umowy ramowej",
    "framework_contract_deleted": "usunięcie umowy ramowej",
    "framework_contract_signature_initiated": "wysłanie umowy ramowej do podpisu",
    "framework_contract_signed": "podpisanie umowy ramowej",
    "framework_contract_amendment_added": "dodanie aneksu",
    "framework_contract_amendment_deleted": "usunięcie aneksu",
    "amendment_signature_initiated": "wysłanie aneksu do podpisu",
    "amendment_signed": "podpisanie aneksu",
}

_CATEGORY_LABELS = {
    PortfolioCategory.active.value: "Aktywni",
    PortfolioCategory.relationship.value: "Relacyjni",
    PortfolioCategory.inactive.value: "Nieaktywni",
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_FOREIGN_KEYS_SQL = text(
    """
    SELECT ns.nspname  AS schema_name,
           cl.relname  AS table_name,
           att.attname AS column_name,
           con.confdeltype::text AS on_delete
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = cl.relnamespace
    JOIN pg_attribute att
      ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND con.confrelid = to_regclass('clients')
      AND cardinality(con.conkey) = 1
    ORDER BY cl.relname, att.attname
    """
)


class CleanupAlreadyExecutedError(Exception):
    """Operacja jest jednorazowa i już się odbyła."""

    def __init__(self, run: ClientCleanupRun) -> None:
        super().__init__(f"cleanup already executed (run_id={run.id})")
        self.run = run


@dataclass(frozen=True)
class ForeignKeyRef:
    schema_name: str
    table_name: str
    column_name: str
    on_delete: str


@dataclass(frozen=True)
class ClientEvaluation:
    client_id: int
    name: str
    source_name: str
    legal_name: Optional[str]
    nip: Optional[str]
    status: Optional[str]
    external_source: Optional[str]
    external_id: Optional[str]
    created_at: Optional[datetime]
    sources: dict[str, int]
    related: tuple[dict[str, Any], ...]
    verdict: Verdict

    def as_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "name": self.name,
            "legal_name": self.legal_name,
            "nip": self.nip,
            "status": self.status,
            "external_source": self.external_source,
            "external_id": self.external_id,
            "sources": [
                {"code": code, "label": SOURCE_LABELS[code], "count": count}
                for code, count in self.sources.items()
                if count
            ],
            "reasons": [dict(item) for item in self.related],
        }


@dataclass(frozen=True)
class CleanupPlan:
    evaluated_at: datetime
    deletable: tuple[ClientEvaluation, ...]
    held: tuple[ClientEvaluation, ...]
    kept: tuple[ClientEvaluation, ...]

    @property
    def candidates_count(self) -> int:
        return len(self.deletable) + len(self.held) + len(self.kept)

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "candidates_count": self.candidates_count,
            "to_delete": [item.as_dict() for item in self.deletable],
            "held": [item.as_dict() for item in self.held],
            "kept": [item.as_dict() for item in self.kept],
            "kept_by_source": kept_by_source(self.kept),
        }


@dataclass
class _Candidate:
    client_id: int
    name: str
    source_name: str
    legal_name: Optional[str]
    nip: Optional[str]
    status: Optional[str]
    notes: Optional[str]
    nda_signed: bool
    external_source: Optional[str]
    external_id: Optional[str]
    created_at: Optional[datetime]
    other_categories: tuple[str, ...]
    sources: dict[str, int] = field(
        default_factory=lambda: {code: 0 for code in SOURCE_LABELS}
    )
    related: list[dict[str, Any]] = field(default_factory=list)


def kept_by_source(kept: Iterable[ClientEvaluation]) -> dict[str, int]:
    counts = {code: 0 for code in SOURCE_LABELS}
    for item in kept:
        for code, count in item.sources.items():
            if count:
                counts[code] += 1
    return counts


def configured_client_ids(
    environ: Optional[dict[str, str]] = None,
) -> dict[int, list[str]]:
    """Klienci wskazani z nazwy w zmiennych ``*_CLIENT_IDS`` (bramki per klient).

    Usunięcie takiego klienta nic by nie zepsuło w bazie, ale zostawiłoby
    w Coolify wpis wskazujący na nieistniejący rekord — i zdradza, że ktoś
    świadomie skonfigurował dla niego zachowanie. To decyzja dla człowieka.
    """

    source = os.environ if environ is None else environ
    found: dict[int, list[str]] = defaultdict(list)
    for key, raw in source.items():
        if not key.endswith("_CLIENT_IDS") or not raw:
            continue
        for token in re.split(r"[,;\s]+", raw):
            token = token.strip()
            if token.isdigit():
                found[int(token)].append(key)
    return {client_id: sorted(keys) for client_id, keys in found.items()}


async def list_client_foreign_keys(db: AsyncSession) -> list[ForeignKeyRef]:
    rows = (await db.execute(_FOREIGN_KEYS_SQL)).all()
    return [
        ForeignKeyRef(
            schema_name=row.schema_name,
            table_name=row.table_name,
            column_name=row.column_name,
            on_delete=row.on_delete,
        )
        for row in rows
    ]


def _quoted(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"unexpected identifier in catalog: {identifier!r}")
    return f'"{identifier}"'


async def _count_foreign_key(
    db: AsyncSession, ref: ForeignKeyRef, client_ids: list[int]
) -> dict[int, int]:
    column = _quoted(ref.column_name)
    table = f"{_quoted(ref.schema_name)}.{_quoted(ref.table_name)}"
    statement = text(
        f"SELECT {column} AS client_id, count(*) AS n FROM {table} "  # noqa: S608
        f"WHERE {column} = ANY(:ids) GROUP BY {column}"
    )
    rows = (await db.execute(statement, {"ids": client_ids})).all()
    return {int(row.client_id): int(row.n) for row in rows}


def _effective_category():
    return func.coalesce(
        ClientPortfolioScope.category_override,
        ClientPortfolioScope.category,
    )


async def load_inactive_candidates(
    db: AsyncSession, restrict_ids: Optional[Collection[int]]
) -> list[_Candidate]:
    """Klienci widoczni w zakładce „Nieaktywni" — ta sama reguła co katalog."""

    effective = _effective_category()
    effective_text = cast(effective, Text)
    statement = (
        select(
            Client.id,
            client_display_name_expression().label("display_name"),
            Client.name,
            Client.legal_name,
            Client.nip,
            cast(Client.status, Text).label("status"),
            Client.notes,
            Client.nda_signed,
            Client.external_source,
            Client.external_id,
            Client.created_at,
            func.array_agg(distinct(effective_text)).label("categories"),
        )
        .join(ClientPortfolioScope, ClientPortfolioScope.client_id == Client.id)
        .where(ClientPortfolioScope.archived_at.is_(None), *visible_client_predicates())
        .group_by(Client.id)
        .having(func.bool_or(effective == PortfolioCategory.inactive))
        .order_by(Client.id)
    )
    if restrict_ids is not None:
        statement = statement.where(Client.id.in_(sorted(set(restrict_ids)) or [-1]))
    rows = (await db.execute(statement)).all()
    return [
        _Candidate(
            client_id=row.id,
            name=row.display_name or row.name,
            source_name=row.name,
            legal_name=row.legal_name,
            nip=row.nip,
            status=row.status,
            notes=row.notes,
            nda_signed=bool(row.nda_signed),
            external_source=row.external_source,
            external_id=row.external_id,
            created_at=row.created_at,
            other_categories=tuple(
                sorted(
                    category
                    for category in (row.categories or [])
                    if category and category != PortfolioCategory.inactive.value
                )
            ),
        )
        for row in rows
    ]


async def _fill_job_sources(
    db: AsyncSession, by_id: dict[int, _Candidate], ids: list[int]
) -> None:
    job_rows = (
        await db.execute(
            select(
                Job.client_id,
                func.count(Job.id).filter(Job.status != JobStatus.closed),
                func.count(Job.id).filter(Job.status == JobStatus.closed),
            )
            .where(Job.client_id.in_(ids))
            .group_by(Job.client_id)
        )
    ).all()
    for client_id, active_count, closed_count in job_rows:
        by_id[client_id].sources["active_projects"] = int(active_count)
        by_id[client_id].sources["closed_projects"] = int(closed_count)

    # Statystyki współpracy w profilu liczą się z rekrutacji i przejść
    # kandydatów przez ich pipeline — to jest to „niepuste".
    stage_rows = (
        await db.execute(
            select(Job.client_id, func.count(CandidateStage.id))
            .join(CandidateStage, CandidateStage.job_id == Job.id)
            .where(Job.client_id.in_(ids))
            .group_by(Job.client_id)
        )
    ).all()
    for client_id, count in stage_rows:
        by_id[client_id].sources["cooperation_stats"] += int(count)

    archived_rows = (
        await db.execute(
            select(Contract.client_id, func.count(Contract.id))
            .where(
                Contract.client_id.in_(ids),
                Contract.status == ContractStatus.ended,
            )
            .group_by(Contract.client_id)
        )
    ).all()
    for client_id, count in archived_rows:
        by_id[client_id].sources["archived_consultants"] = int(count)


async def _fill_activity_reasons(
    db: AsyncSession, by_id: dict[int, _Candidate], ids: list[int]
) -> None:
    rows = (
        await db.execute(
            select(Activity.entity_id, Activity.action, func.count(Activity.id))
            .where(Activity.entity_type == "client", Activity.entity_id.in_(ids))
            .group_by(Activity.entity_id, Activity.action)
        )
    ).all()
    substantive: dict[int, dict[str, int]] = defaultdict(dict)
    for client_id, action, count in rows:
        if action in _ADMINISTRATIVE_ACTIVITY_ACTIONS:
            continue
        substantive[int(client_id)][str(action)] = int(count)
    for client_id, actions in substantive.items():
        candidate = by_id.get(client_id)
        if candidate is None:
            continue
        candidate.related.append(
            {
                "code": "activity",
                "label": "Wpisy w dzienniku aktywności klienta",
                "count": sum(actions.values()),
                "details": sorted(
                    _ACTIVITY_ACTION_LABELS.get(action, action) for action in actions
                ),
                "effect": "zostałyby w dzienniku bez klienta",
            }
        )


async def evaluate_inactive_clients(
    db: AsyncSession,
    *,
    restrict_ids: Optional[Collection[int]] = None,
    environ: Optional[dict[str, str]] = None,
) -> CleanupPlan:
    """Oceń każdego klienta z zakładki „Nieaktywni". Tylko odczyt."""

    candidates = await load_inactive_candidates(db, restrict_ids)
    evaluated_at = datetime.now(timezone.utc)
    if not candidates:
        return CleanupPlan(evaluated_at, (), (), ())
    by_id = {candidate.client_id: candidate for candidate in candidates}
    ids = sorted(by_id)

    # Źródło 6 — notatki w profilu (pole ``clients.notes``).
    for candidate in candidates:
        if candidate.notes and candidate.notes.strip():
            candidate.sources["notes"] = 1

    await _fill_job_sources(db, by_id, ids)

    # Każdy klucz obcy wskazujący na klienta: albo należy do jednego z ośmiu
    # źródeł, albo jest wpisem katalogu, albo jest „innym powiązaniem".
    for ref in await list_client_foreign_keys(db):
        key = (ref.table_name, ref.column_name)
        if key in _STRUCTURAL_REFERENCES:
            continue
        if key == ("jobs", "client_id"):
            # Już rozbite na aktywne/zamknięte w ``_fill_job_sources``.
            continue
        counts = await _count_foreign_key(db, ref, ids)
        if not counts:
            continue
        source = _SOURCE_BY_TABLE.get(ref.table_name)
        for client_id, count in counts.items():
            if source is not None:
                by_id[client_id].sources[source] += count
                continue
            by_id[client_id].related.append(
                {
                    "code": "foreign_key",
                    "label": _RELATED_LABELS.get(ref.table_name, ref.table_name),
                    "table": ref.table_name,
                    "column": ref.column_name,
                    "count": count,
                    "effect": _ON_DELETE_EFFECT.get(
                        ref.on_delete, "straciłyby powiązanie z klientem"
                    ),
                }
            )

    await _fill_activity_reasons(db, by_id, ids)

    configured = configured_client_ids(environ)
    for candidate in candidates:
        if candidate.other_categories:
            labels = ", ".join(
                _CATEGORY_LABELS.get(category, category)
                for category in candidate.other_categories
            )
            candidate.related.append(
                {
                    "code": "other_portfolio_tab",
                    "label": f"Klient ma też zakres w zakładce: {labels}",
                    "count": len(candidate.other_categories),
                    "effect": "zniknąłby także z tamtej zakładki",
                }
            )
        if candidate.nda_signed:
            candidate.related.append(
                {
                    "code": "nda_signed",
                    "label": "Oznaczone podpisane NDA",
                    "count": 1,
                    "effect": "informacja o NDA zostałaby usunięta",
                }
            )
        keys = configured.get(candidate.client_id)
        if keys:
            candidate.related.append(
                {
                    "code": "configuration",
                    "label": "Klient wskazany w konfiguracji: " + ", ".join(keys),
                    "count": len(keys),
                    "effect": "konfiguracja wskazywałaby nieistniejącego klienta",
                }
            )

    deletable: list[ClientEvaluation] = []
    held: list[ClientEvaluation] = []
    kept: list[ClientEvaluation] = []
    for candidate in sorted(candidates, key=lambda c: (c.name.lower(), c.client_id)):
        if any(candidate.sources.values()):
            verdict: Verdict = "keep"
        elif candidate.related:
            verdict = "hold"
        else:
            verdict = "delete"
        evaluation = ClientEvaluation(
            client_id=candidate.client_id,
            name=candidate.name,
            source_name=candidate.source_name,
            legal_name=candidate.legal_name,
            nip=candidate.nip,
            status=candidate.status,
            external_source=candidate.external_source,
            external_id=candidate.external_id,
            created_at=candidate.created_at,
            sources=dict(candidate.sources),
            related=tuple(candidate.related),
            verdict=verdict,
        )
        {"keep": kept, "hold": held, "delete": deletable}[verdict].append(evaluation)
    return CleanupPlan(evaluated_at, tuple(deletable), tuple(held), tuple(kept))
