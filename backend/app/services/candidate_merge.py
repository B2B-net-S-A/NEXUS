"""Scalanie duplikatów kandydatów (admin + Head of Recruitment) — PR2.

Wzór: ``contract_merge`` — plan → odcisk SHA-256 → wykonanie pod blokadą.
Ocalały kandydat (``survivor``) przejmuje wszystko, co wskazuje na duplikat,
a duplikat jest usuwany. Do tej pory scalanie robił wyłącznie skrypt
``scripts/merge_duplicate_candidates.py`` (partie z importu Talent Radar),
który przy kolizji unikalności kasował WSZYSTKIE wiersze duplikatu w tabeli.

Reguły, które łatwo cofnąć:

* **Referencje odkrywane z katalogu w chwili uruchomienia.** Każdy klucz obcy
  do ``candidates.id`` (także kolumny o innych nazwach: ``matched_candidate_id``,
  ``favorite_candidate_id``…) + kolumny ``candidate_id`` bez FK (np.
  ``candidate_contact_events``, wyniki przeglądów) + FK zadeklarowane
  w modelach, a nieobecne w bazie. Lista ręczna zgniłaby przy pierwszej nowej
  tabeli — a zapomniany FK z ``ON DELETE CASCADE`` to dane, które znikają
  razem z duplikatem.
* **Konflikt unikalności rozstrzygany PER WIERSZ.** Dla każdego unikalnego
  indeksu z kolumną kandydata szukamy par (wiersz duplikatu, wiersz
  ocalałego) o tych samych pozostałych kolumnach (z predykatem indeksu
  częściowego). Zostaje NOWSZY z pary (``updated_at``, potem ``created_at``;
  remis = ocalały), starszy jest usuwany; wszystkie inne wiersze duplikatu są
  przepinane. Nigdy „usuń wszystkie wiersze duplikatu w tabeli”.
* **Referencje polimorficzne** (``activities``, ``notifications``,
  ``traffit_entity_links.nexus_entity_id``) przepinane jawnie — nie mają FK.
* **Pola profilu:** puste po jednej stronie = bierzemy niepuste; różne po obu
  = konflikt, o którym decyduje człowiek (domyślnie ocalały). Kontakty
  duplikatu, które nie zostały wybrane, lądują w ``custom_fields.merged_
  duplicates`` — scalenie nie gubi adresu, pod którym ktoś pisał.
* **Tożsamość z Traffita:** gdy tylko duplikat pochodzi z Traffita, ocalały
  przejmuje jego ``external_id`` (inaczej nocny sync założyłby duplikat
  z powrotem). Oba z Traffita = blokada — to trzeba scalić w Traffit.
* Imię/nazwisko wybrane z duplikatu dostaje blokadę synchronizacji
  (``candidate_identity_ownership``), jak ręczna edycja.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_UNIQUE_VIOLATION = "23505"

# Tabela z triggerem append-only (blokuje UPDATE i DELETE) — migracja 0201.
_APPEND_ONLY_TRIGGERS: dict[str, str] = {
    "candidate_contact_events": "trg_candidate_contact_events_immutable",
}

# Referencje polimorficzne: (tabela, kolumna typu, wartość typu, kolumna id).
_POLYMORPHIC: tuple[tuple[str, str, str, str], ...] = (
    ("activities", "entity_type", "candidate", "entity_id"),
    ("notifications", "related_entity_type", "candidate", "related_entity_id"),
    ("traffit_entity_links", "entity_type", "candidate", "nexus_entity_id"),
)

# Konflikt unikalności, w którym o zwycięzcy decyduje STAN wiersza, nie data:
# (tabela, kolumna, wartość, która wygrywa). Akademia pamięta „nie” na zawsze
# (decyzja Artura 24.09.2026) — gdyby wygrywał nowszy wiersz, scalenie profilu
# odrzuconej osoby z jej świeżym profilem z Traffita (nowe zgłoszenie, inny
# e-mail) wracałoby ją do telefonów bez śladu wykluczenia.
_STATE_WINS: dict[str, tuple[str, str]] = {
    "academy_applications": ("status", "rejected"),
}

# Tabele, których przepinać NIE wolno (z powodem).
_SKIP_TABLES: dict[str, str] = {
    # Kolejka indeksu: wiersz duplikatu zostaje i dostaje zadanie „delete",
    # ocalały dostaje świeże przeliczenie wektora.
    "match_index_outbox": "kolejka indeksu wektorowego",
}

Choice = Literal["survivor", "duplicate"]

# (pole, etykieta PL) porównywane w oknie scalania.
MERGE_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Imię"),
    ("lastname", "Nazwisko"),
    ("email", "E-mail"),
    ("phone", "Telefon"),
    ("linkedin", "LinkedIn"),
    ("city", "Miasto"),
    ("country", "Kraj"),
    ("availability_date", "Dostępny od"),
    ("notice_period", "Okres wypowiedzenia"),
    ("years_it_experience", "Lata doświadczenia"),
    ("profile_about", "O sobie"),
    ("legal_name", "Nazwa firmy"),
    ("nip", "NIP"),
)
_FIELD_NAMES = {name for name, _ in MERGE_FIELDS}


class MergeError(Exception):
    """Odmowa (404/409/422) z komunikatem po polsku."""

    def __init__(self, status_code: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


@dataclass(frozen=True)
class Reference:
    table: str
    column: str
    has_fk: bool


@dataclass(frozen=True)
class UniqueIndex:
    name: str
    table: str
    columns: tuple[str, ...]
    has_expression: bool
    predicate: Optional[str]


@dataclass
class ReferencePlan:
    table: str
    column: str
    rows: int
    conflicts: int
    unresolvable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column,
            "rows": self.rows,
            "conflicts": self.conflicts,
            "unresolvable": self.unresolvable,
        }


@dataclass
class MergePlan:
    survivor_id: int
    duplicate_id: int
    survivor: dict[str, Any]
    duplicate: dict[str, Any]
    fields: list[dict[str, Any]] = field(default_factory=list)
    references: list[ReferencePlan] = field(default_factory=list)
    polymorphic: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, str]] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def can_apply(self) -> bool:
        return not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "survivor_id": self.survivor_id,
            "duplicate_id": self.duplicate_id,
            "survivor": self.survivor,
            "duplicate": self.duplicate,
            "fields": self.fields,
            "references": [r.as_dict() for r in self.references if r.rows],
            "polymorphic": [p for p in self.polymorphic if p["rows"]],
            "moved_rows": sum(r.rows for r in self.references)
            + sum(p["rows"] for p in self.polymorphic),
            "conflicts": sum(r.conflicts for r in self.references),
            "blockers": self.blockers,
            "can_apply": self.can_apply,
            "fingerprint": self.fingerprint,
        }


# ── Katalog ──────────────────────────────────────────────────────────────────


def _model_only_references(db_refs: set[tuple[str, str]]) -> list[Reference]:
    """FK do ``candidates.id`` zadeklarowane w modelach, a nieobecne w bazie.

    Lustro ``inactive_client_cleanup._model_only_foreign_keys``: tabela
    dopisana w modelu, której migracja jeszcze nie przeszła na tej bazie, nie
    może zostać cicho pominięta.
    """

    from app.core.database import Base

    out: list[Reference] = []
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == "candidates" and fk.column.name == "id":
                key = (table.name, fk.parent.name)
                if key not in db_refs and table.name != "candidates":
                    out.append(Reference(table.name, fk.parent.name, True))
    return out


async def discover_references(db: AsyncSession) -> list[Reference]:
    fk_rows = (
        await db.execute(
            text(
                """
                SELECT cl.relname AS table_name, att.attname AS column_name
                FROM pg_constraint con
                JOIN pg_class cl ON cl.oid = con.conrelid
                JOIN pg_namespace ns ON ns.oid = cl.relnamespace
                JOIN pg_attribute att
                  ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
                WHERE con.contype = 'f'
                  AND con.confrelid = 'candidates'::regclass
                  AND array_length(con.conkey, 1) = 1
                  AND ns.nspname = 'public'
                """
            )
        )
    ).all()
    refs: dict[tuple[str, str], Reference] = {}
    for table_name, column_name in fk_rows:
        refs[(table_name, column_name)] = Reference(table_name, column_name, True)
    loose = (
        await db.execute(
            text(
                """
                SELECT c.table_name, c.column_name
                FROM information_schema.columns c
                JOIN information_schema.tables t
                  ON t.table_schema = c.table_schema
                 AND t.table_name = c.table_name
                 AND t.table_type = 'BASE TABLE'
                WHERE c.table_schema = 'public'
                  AND c.column_name IN ('candidate_id', 'parsed_candidate_id')
                  AND c.table_name <> 'candidates'
                """
            )
        )
    ).all()
    for table_name, column_name in loose:
        refs.setdefault(
            (table_name, column_name), Reference(table_name, column_name, False)
        )
    for ref in _model_only_references(set(refs)):
        refs.setdefault((ref.table, ref.column), ref)
    return sorted(
        (
            r
            for r in refs.values()
            if _IDENT.match(r.table)
            and _IDENT.match(r.column)
            and r.table not in _SKIP_TABLES
        ),
        key=lambda r: (r.table, r.column),
    )


async def _existing_tables(db: AsyncSession, names: set[str]) -> set[str]:
    if not names:
        return set()
    rows = await db.scalars(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = ANY(:names)"
        ),
        {"names": sorted(names)},
    )
    return set(rows.all())


async def unique_indexes(db: AsyncSession) -> dict[str, list[UniqueIndex]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT ic.relname AS index_name,
                       t.relname AS table_name,
                       ARRAY(
                           SELECT a.attname
                           FROM unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
                           JOIN pg_attribute a
                             ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                           ORDER BY k.ord
                       ) AS columns,
                       (0 = ANY(i.indkey::int2[])) AS has_expression,
                       pg_get_expr(i.indpred, i.indrelid) AS predicate
                FROM pg_index i
                JOIN pg_class t ON t.oid = i.indrelid
                JOIN pg_class ic ON ic.oid = i.indexrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE i.indisunique AND n.nspname = 'public'
                """
            )
        )
    ).all()
    out: dict[str, list[UniqueIndex]] = {}
    for index_name, table_name, columns, has_expression, predicate in rows:
        out.setdefault(table_name, []).append(
            UniqueIndex(
                name=index_name,
                table=table_name,
                columns=tuple(columns or ()),
                has_expression=bool(has_expression),
                predicate=predicate,
            )
        )
    return out


async def _row_key(db: AsyncSession, table: str) -> tuple[str, str]:
    """(kolumna, typ) identyfikujące wiersz: jednokolumnowy PK albo ``ctid``."""

    rows = (
        await db.execute(
            text(
                """
                SELECT a.attname, format_type(a.atttypid, a.atttypmod)
                FROM pg_index i
                JOIN pg_attribute a
                  ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey::int2[])
                WHERE i.indrelid = CAST(:table AS regclass) AND i.indisprimary
                """
            ),
            {"table": table},
        )
    ).all()
    if len(rows) == 1 and _IDENT.match(rows[0][0]):
        return rows[0][0], rows[0][1]
    return "ctid", "tid"


async def _table_columns(db: AsyncSession, table: str) -> set[str]:
    rows = await db.scalars(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    return set(rows.all())


# ── Konflikty unikalności ────────────────────────────────────────────────────


def _relevant_indexes(
    indexes: dict[str, list[UniqueIndex]], ref: Reference
) -> tuple[list[UniqueIndex], bool]:
    """Indeksy unikalne z kolumną referencji; drugi element: jest indeks z wyrażeniem."""

    plain: list[UniqueIndex] = []
    expression = False
    for idx in indexes.get(ref.table, []):
        if ref.column not in idx.columns:
            continue
        if idx.has_expression or not all(_IDENT.match(c) for c in idx.columns):
            expression = True
            continue
        plain.append(idx)
    return plain, expression


async def _conflict_pairs(
    db: AsyncSession,
    ref: Reference,
    idx: UniqueIndex,
    key: str,
    *,
    survivor_id: int,
    duplicate_id: int,
) -> list[tuple[str, str]]:
    """Pary (klucz wiersza duplikatu, klucz wiersza ocalałego), które się zderzą."""

    others = [c for c in idx.columns if c != ref.column]
    join = " AND ".join(f"s.{c} = d.{c}" for c in others) or "TRUE"
    predicate = ""
    if idx.predicate:
        predicate = (
            f" AND d.{key} IN (SELECT {key} FROM {ref.table} WHERE {idx.predicate})"
            f" AND s.{key} IN (SELECT {key} FROM {ref.table} WHERE {idx.predicate})"
        )
    rows = (
        await db.execute(
            text(
                f"SELECT d.{key}::text, s.{key}::text FROM {ref.table} d "
                f"JOIN {ref.table} s ON s.{ref.column} = :survivor AND {join} "
                f"WHERE d.{ref.column} = :duplicate{predicate}"
            ),
            {"survivor": survivor_id, "duplicate": duplicate_id},
        )
    ).all()
    return [(str(a), str(b)) for a, b in rows]


async def _all_conflicts(
    db: AsyncSession,
    ref: Reference,
    indexes: dict[str, list[UniqueIndex]],
    key: str,
    *,
    survivor_id: int,
    duplicate_id: int,
) -> tuple[dict[str, set[str]], bool]:
    plain, expression = _relevant_indexes(indexes, ref)
    pairs: dict[str, set[str]] = {}
    for idx in plain:
        for dup_key, surv_key in await _conflict_pairs(
            db, ref, idx, key, survivor_id=survivor_id, duplicate_id=duplicate_id
        ):
            pairs.setdefault(dup_key, set()).add(surv_key)
    return pairs, expression


# ── Pola profilu ─────────────────────────────────────────────────────────────


def _display(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    return a == b


def field_plan(survivor: Candidate, duplicate: Candidate) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, label in MERGE_FIELDS:
        s_val = getattr(survivor, name)
        d_val = getattr(duplicate, name)
        if _is_empty(s_val) and _is_empty(d_val):
            continue
        conflict = (
            not _is_empty(s_val) and not _is_empty(d_val) and not _same(s_val, d_val)
        )
        out.append(
            {
                "field": name,
                "label": label,
                "survivor": _display(s_val),
                "duplicate": _display(d_val),
                "conflict": conflict,
                # Bez konfliktu: bierzemy niepustą wartość (ocalały wygrywa remis).
                "default": "duplicate"
                if _is_empty(s_val) and not _is_empty(d_val)
                else "survivor",
            }
        )
    return out


def _person(candidate: Candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "name": candidate.name,
        "lastname": candidate.lastname,
        "email": candidate.email,
        "phone": candidate.phone,
        "city": candidate.city,
        "external_source": candidate.external_source,
        "created_at": _display(candidate.created_at),
        "updated_at": _display(candidate.updated_at),
    }


def _external(candidate: Candidate) -> Optional[tuple[str, str]]:
    if candidate.external_id and candidate.external_source not in (None, "manual"):
        return candidate.external_source, candidate.external_id
    return None


# ── Plan ─────────────────────────────────────────────────────────────────────


async def _load_pair(
    db: AsyncSession, survivor_id: int, duplicate_id: int, *, lock: bool
) -> tuple[Candidate, Candidate]:
    if survivor_id == duplicate_id:
        raise MergeError(
            422, "same_candidate", "Nie można scalić kandydata z nim samym."
        )
    stmt = (
        select(Candidate)
        .where(Candidate.id.in_([survivor_id, duplicate_id]))
        .order_by(Candidate.id)
        .execution_options(populate_existing=True)
    )
    if lock:
        # Stała kolejność (rosnąco po id): dwa scalenia tej samej pary w
        # odwrotnych kierunkach nie zakleszczą się o siebie.
        stmt = stmt.with_for_update(of=Candidate)
    found = {c.id: c for c in (await db.scalars(stmt)).all()}
    if survivor_id not in found or duplicate_id not in found:
        raise MergeError(404, "candidate_not_found", "Nie znaleziono kandydata.")
    return found[survivor_id], found[duplicate_id]


def _fingerprint(plan: MergePlan) -> str:
    body = {
        "survivor": plan.survivor_id,
        "duplicate": plan.duplicate_id,
        "survivor_updated": plan.survivor.get("updated_at"),
        "duplicate_updated": plan.duplicate.get("updated_at"),
        "fields": [(f["field"], f["survivor"], f["duplicate"]) for f in plan.fields],
        "references": sorted(
            (r.table, r.column, r.rows, r.conflicts) for r in plan.references
        ),
        "polymorphic": sorted((p["table"], p["rows"]) for p in plan.polymorphic),
        "blockers": sorted(b["code"] for b in plan.blockers),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _usable_references(db: AsyncSession) -> list[Reference]:
    refs = await discover_references(db)
    existing = await _existing_tables(db, {r.table for r in refs})
    usable: list[Reference] = []
    columns_cache: dict[str, set[str]] = {}
    for ref in refs:
        if ref.table not in existing:
            continue
        if ref.table not in columns_cache:
            columns_cache[ref.table] = await _table_columns(db, ref.table)
        if ref.column in columns_cache[ref.table]:
            usable.append(ref)
    return usable


async def build_plan(
    db: AsyncSession,
    survivor_id: int,
    duplicate_id: int,
    *,
    lock: bool = False,
) -> MergePlan:
    """Plan scalenia. Niczego nie zapisuje."""

    survivor, duplicate = await _load_pair(db, survivor_id, duplicate_id, lock=lock)
    plan = MergePlan(
        survivor_id=survivor.id,
        duplicate_id=duplicate.id,
        survivor=_person(survivor),
        duplicate=_person(duplicate),
        fields=field_plan(survivor, duplicate),
    )
    s_ext, d_ext = _external(survivor), _external(duplicate)
    if s_ext and d_ext and s_ext[0] == d_ext[0]:
        plan.blockers.append(
            {
                "code": "both_external",
                "message": (
                    "Oba profile pochodzą z tego samego systemu zewnętrznego "
                    f"({s_ext[0]}) — scal je najpierw tam, inaczej nocny import "
                    "odtworzy usunięty profil."
                ),
            }
        )

    indexes = await unique_indexes(db)
    for ref in await _usable_references(db):
        rows = await db.scalar(
            text(f"SELECT count(*) FROM {ref.table} WHERE {ref.column} = :dup"),
            {"dup": duplicate.id},
        )
        rows = int(rows or 0)
        conflicts = 0
        unresolvable = False
        if rows:
            key, _key_type = await _row_key(db, ref.table)
            pairs, expression = await _all_conflicts(
                db,
                ref,
                indexes,
                key,
                survivor_id=survivor.id,
                duplicate_id=duplicate.id,
            )
            conflicts = len(pairs)
            unresolvable = expression
        plan.references.append(
            ReferencePlan(ref.table, ref.column, rows, conflicts, unresolvable)
        )

    existing_poly = await _existing_tables(db, {t for t, *_ in _POLYMORPHIC})
    for table, type_col, type_value, id_col in _POLYMORPHIC:
        if table not in existing_poly:
            continue
        rows = await db.scalar(
            text(
                f"SELECT count(*) FROM {table} "
                f"WHERE {type_col} = :t AND {id_col} = :dup"
            ),
            {"t": type_value, "dup": duplicate.id},
        )
        plan.polymorphic.append({"table": table, "rows": int(rows or 0)})

    plan.fingerprint = _fingerprint(plan)
    return plan


# ── Wykonanie ────────────────────────────────────────────────────────────────


def _db_error_code(exc: DBAPIError) -> Optional[str]:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _unresolvable(table: str) -> MergeError:
    return MergeError(
        409,
        "merge_conflict_unresolvable",
        (
            f"Nie da się przenieść danych z tabeli „{table}” bez utraty wpisów — "
            "scalenie wycofane w całości. Zgłoś to jako błąd."
        ),
        table=table,
    )


async def _timestamp_column(db: AsyncSession, table: str) -> Optional[str]:
    columns = await _table_columns(db, table)
    for name in ("updated_at", "created_at"):
        if name in columns:
            return name
    return None


async def _timestamps(
    db: AsyncSession,
    ref: Reference,
    key: str,
    ts_col: str,
    keys: set[str],
    ids: tuple[int, int],
) -> dict[str, Any]:
    rows = (
        await db.execute(
            text(
                f"SELECT {key}::text, {ts_col} FROM {ref.table} "
                f"WHERE {ref.column} IN (:a, :b) AND {key}::text = ANY(:keys)"
            ),
            {"a": ids[0], "b": ids[1], "keys": sorted(keys)},
        )
    ).all()
    return {str(k): ts for k, ts in rows}


async def _winning_states(
    db: AsyncSession,
    ref: Reference,
    key: str,
    winning_state: tuple[str, str],
    keys: set[str],
    ids: tuple[int, int],
) -> dict[str, bool]:
    """Które wiersze mają stan, który wygrywa konflikt (np. ``rejected``)."""
    column, value = winning_state
    rows = (
        await db.execute(
            text(
                f"SELECT {key}::text, ({column} = :value) FROM {ref.table} "
                f"WHERE {ref.column} IN (:a, :b) AND {key}::text = ANY(:keys)"
            ),
            {"a": ids[0], "b": ids[1], "keys": sorted(keys), "value": value},
        )
    ).all()
    return {str(k): bool(flag) for k, flag in rows}


async def _stamp_academy_reapplied(
    db: AsyncSession, ref: Reference, key: str, kept: str, dropped: list[str]
) -> None:
    """Wykluczony wiersz wygrał z nowszym zgłoszeniem — zostaw ślad powrotu.

    Lustro naboru (``services/academy.py``): osoba odrzucona, która aplikuje
    ponownie, dostaje tylko ``reapplied_at`` (najpóźniejsze zgłoszenie).
    """
    await db.execute(
        text(
            f"UPDATE {ref.table} AS kept SET reapplied_at = sub.last_at "
            f"FROM (SELECT max(applied_at) AS last_at FROM {ref.table} "
            f"WHERE {key}::text = ANY(:dropped)) AS sub "
            f"WHERE kept.{key}::text = :kept AND sub.last_at IS NOT NULL "
            # Tylko zgłoszenie PO decyzji jest powrotem — starsze, aktywne
            # zgłoszenie z drugiego profilu niczego nie mówi o powrocie.
            "AND sub.last_at > COALESCE(kept.closed_at, kept.applied_at) "
            "AND (kept.reapplied_at IS NULL OR kept.reapplied_at < sub.last_at)"
        ),
        {"kept": kept, "dropped": sorted(dropped)},
    )


async def _delete_keys(
    db: AsyncSession, ref: Reference, key: str, keys: list[str], ids: tuple[int, int]
) -> int:
    if not keys:
        return 0
    try:
        async with db.begin_nested():
            result = await db.execute(
                text(
                    f"DELETE FROM {ref.table} WHERE {ref.column} IN (:a, :b) "
                    f"AND {key}::text = ANY(:keys)"
                ),
                {"a": ids[0], "b": ids[1], "keys": sorted(keys)},
            )
    except DBAPIError as exc:
        raise _unresolvable(ref.table) from exc
    return result.rowcount or 0


async def _repoint(
    db: AsyncSession, ref: Reference, *, survivor_id: int, duplicate_id: int
) -> int:
    trigger = _APPEND_ONLY_TRIGGERS.get(ref.table)
    if trigger is not None:
        exists = await db.scalar(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = :name "
                "AND tgrelid = CAST(:table AS regclass)"
            ),
            {"name": trigger, "table": ref.table},
        )
        trigger = trigger if exists else None
    sql = text(
        f"UPDATE {ref.table} SET {ref.column} = :survivor "
        f"WHERE {ref.column} = :duplicate"
    )
    params = {"survivor": survivor_id, "duplicate": duplicate_id}
    try:
        async with db.begin_nested():
            if trigger is not None:
                # Historia append-only przechodzi na ocalałego; trigger zdjęty
                # wyłącznie na czas UPDATE-u (transakcyjnie).
                await db.execute(
                    text(f"ALTER TABLE {ref.table} DISABLE TRIGGER {trigger}")
                )
            result = await db.execute(sql, params)
            if trigger is not None:
                await db.execute(
                    text(f"ALTER TABLE {ref.table} ENABLE TRIGGER {trigger}")
                )
    except DBAPIError as exc:
        raise _unresolvable(ref.table) from exc
    return result.rowcount or 0


async def _move_reference(
    db: AsyncSession,
    ref: Reference,
    indexes: dict[str, list[UniqueIndex]],
    *,
    survivor_id: int,
    duplicate_id: int,
) -> dict[str, int]:
    """Przepięcie jednej referencji z rozstrzygnięciem konfliktów per wiersz."""

    key, _key_type = await _row_key(db, ref.table)
    ids = (survivor_id, duplicate_id)
    pairs, _expression = await _all_conflicts(
        db, ref, indexes, key, survivor_id=survivor_id, duplicate_id=duplicate_id
    )
    replaced = 0
    if pairs:
        ts_col = await _timestamp_column(db, ref.table)
        stamps: dict[str, Any] = {}
        if ts_col is not None:
            every = set(pairs) | {k for keys in pairs.values() for k in keys}
            stamps = await _timestamps(db, ref, key, ts_col, every, ids)
        states: dict[str, bool] = {}
        winning_state = _STATE_WINS.get(ref.table)
        if winning_state is not None:
            every = set(pairs) | {k for keys in pairs.values() for k in keys}
            states = await _winning_states(db, ref, key, winning_state, every, ids)
        drop_duplicate: list[str] = []
        drop_survivor: set[str] = set()
        reapplied: list[tuple[str, list[str]]] = []
        for dup_key, surv_keys in sorted(pairs.items()):
            dup_wins = states.get(dup_key, False)
            surv_wins = any(states.get(k, False) for k in surv_keys)
            if dup_wins and not surv_wins:
                newer = True
            elif surv_wins and not dup_wins:
                newer = False
            else:
                dup_ts = stamps.get(dup_key)
                surv_ts = [stamps.get(k) for k in surv_keys]
                newer = dup_ts is not None and all(
                    ts is not None and dup_ts > ts for ts in surv_ts
                )
            if newer:
                drop_survivor.update(surv_keys)
                if dup_wins and not surv_wins:
                    reapplied.append((dup_key, list(surv_keys)))
            else:
                drop_duplicate.append(dup_key)
                if surv_wins and not dup_wins:
                    kept = next(k for k in surv_keys if states.get(k, False))
                    reapplied.append((kept, [dup_key]))
        if ref.table == "academy_applications":
            for kept, dropped in reapplied:
                await _stamp_academy_reapplied(db, ref, key, kept, dropped)
        replaced += await _delete_keys(db, ref, key, sorted(drop_survivor), ids)
        replaced += await _delete_keys(db, ref, key, drop_duplicate, ids)
    moved = await _repoint(db, ref, survivor_id=survivor_id, duplicate_id=duplicate_id)
    return {"moved": moved, "replaced": replaced}


async def _move_polymorphic(
    db: AsyncSession, *, survivor_id: int, duplicate_id: int
) -> dict[str, int]:
    moved: dict[str, int] = {}
    existing = await _existing_tables(db, {t for t, *_ in _POLYMORPHIC})
    for table, type_col, type_value, id_col in _POLYMORPHIC:
        if table not in existing:
            continue
        params = {"t": type_value, "s": survivor_id, "d": duplicate_id}
        extra = ""
        if table == "notifications":
            # Link „/candidates/{id}” też wskazuje osobę — przepisz go razem
            # z encją, inaczej powiadomienie prowadziłoby do 404.
            # Osobne parametry tekstowe: asyncpg nie przyjmie tego samego
            # parametru raz jako liczby (id), raz jako tekstu.
            params["d_link"] = f"/candidates/{duplicate_id}(?![0-9])"
            params["s_link"] = f"/candidates/{survivor_id}"
            extra = ", link = regexp_replace(link, :d_link, :s_link)"
        sql = text(
            f"UPDATE {table} SET {id_col} = :s{extra} "
            f"WHERE {type_col} = :t AND {id_col} = :d"
        )
        try:
            async with db.begin_nested():
                result = await db.execute(sql, params)
            moved[table] = result.rowcount or 0
            continue
        except DBAPIError as exc:
            if _db_error_code(exc) != _UNIQUE_VIOLATION:
                raise _unresolvable(table) from exc
        # Kolizja deduplikacji (np. dzienny dedup powiadomień): wiersz po
        # wierszu, a wiersz duplikatu, który się zderza, jest nadmiarowym
        # powtórzeniem wpisu ocalałego i znika.
        row_ids = (
            await db.scalars(
                text(f"SELECT id FROM {table} WHERE {type_col} = :t AND {id_col} = :d"),
                {"t": type_value, "d": duplicate_id},
            )
        ).all()
        count = 0
        for row_id in row_ids:
            try:
                async with db.begin_nested():
                    await db.execute(
                        text(f"UPDATE {table} SET {id_col} = :s{extra} WHERE id = :id"),
                        {
                            **{k: v for k, v in params.items() if k not in ("t", "d")},
                            "id": row_id,
                        },
                    )
                count += 1
            except DBAPIError as exc:
                if _db_error_code(exc) != _UNIQUE_VIOLATION:
                    raise _unresolvable(table) from exc
                async with db.begin_nested():
                    await db.execute(
                        text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id}
                    )
        moved[table] = count
    return moved


def _validated_choices(
    plan: MergePlan, choices: Optional[dict[str, str]]
) -> dict[str, Choice]:
    conflict_fields = {f["field"] for f in plan.fields if f["conflict"]}
    out: dict[str, Choice] = {}
    for name, value in (choices or {}).items():
        if name not in _FIELD_NAMES:
            raise MergeError(422, "unknown_field", f"Nieznane pole „{name}”.")
        if value not in ("survivor", "duplicate"):
            raise MergeError(
                422,
                "invalid_choice",
                f"Wybór dla „{name}” musi być survivor albo duplicate.",
            )
        if name in conflict_fields:
            out[name] = value  # type: ignore[assignment]
    return out


async def execute_merge(
    db: AsyncSession,
    *,
    survivor_id: int,
    duplicate_id: int,
    fingerprint: str,
    choices: Optional[dict[str, str]],
    user_id: Optional[int],
) -> dict[str, Any]:
    """Scalenie pod blokadą obu kandydatów. Commit należy do wołającego."""

    plan = await build_plan(db, survivor_id, duplicate_id, lock=True)
    if plan.fingerprint != fingerprint:
        raise MergeError(
            409,
            "fingerprint_mismatch",
            "Od podglądu dane kandydatów się zmieniły — sprawdź podgląd jeszcze raz.",
            plan=plan.as_dict(),
        )
    if plan.blockers:
        raise MergeError(
            409,
            "merge_blocked",
            "Scalenie jest zablokowane.",
            blockers=plan.blockers,
        )
    picked = _validated_choices(plan, choices)
    survivor = await db.get(Candidate, survivor_id)
    duplicate = await db.get(Candidate, duplicate_id)
    assert survivor is not None and duplicate is not None

    # Stan duplikatu PRZED usunięciem wiersza.
    dup_values = {name: getattr(duplicate, name) for name in _FIELD_NAMES}
    dup_tags = list(duplicate.tags) if isinstance(duplicate.tags, list) else []
    dup_external = _external(duplicate)
    dup_contact = {
        "candidate_id": duplicate.id,
        "email": duplicate.email,
        "phone": duplicate.phone,
        "linkedin": duplicate.linkedin,
        "merged_at": datetime.now(timezone.utc).isoformat(),
    }

    indexes = await unique_indexes(db)
    moved: dict[str, dict[str, int]] = {}
    for ref in await _usable_references(db):
        stats = await _move_reference(
            db, ref, indexes, survivor_id=survivor_id, duplicate_id=duplicate_id
        )
        if stats["moved"] or stats["replaced"]:
            moved[f"{ref.table}.{ref.column}"] = stats
    polymorphic = await _move_polymorphic(
        db, survivor_id=survivor_id, duplicate_id=duplicate_id
    )

    # Usunięcie duplikatu SQL-em, nie `db.delete`: relacje ORM z kaskadą
    # próbowałyby doczytać dzieci (w async to MissingGreenlet), a dzieci
    # już i tak wskazują na ocalałego.
    db.expunge(duplicate)
    await db.execute(
        text("DELETE FROM candidates WHERE id = :id"), {"id": duplicate_id}
    )

    updates: dict[str, Any] = {}
    for spec in plan.fields:
        name = spec["field"]
        source = (
            picked.get(name, spec["default"]) if spec["conflict"] else spec["default"]
        )
        if source == "duplicate":
            updates[name] = dup_values[name]

    custom = (
        dict(survivor.custom_fields) if isinstance(survivor.custom_fields, dict) else {}
    )
    history = list(custom.get("merged_duplicates") or [])
    history.append(dup_contact)
    custom["merged_duplicates"] = history
    survivor.custom_fields = custom

    if dup_external is not None and _external(survivor) is None:
        survivor.external_source, survivor.external_id = dup_external

    if updates:
        from app.services.candidate_identity_ownership import (
            lock_changed_traffit_identity_fields,
        )

        lock_changed_traffit_identity_fields(survivor, updates, user_id=user_id)
        for name, value in updates.items():
            setattr(survivor, name, value)

    survivor_tags = list(survivor.tags) if isinstance(survivor.tags, list) else []
    folded = {t.casefold() for t in survivor_tags if isinstance(t, str)}
    for tag in dup_tags:
        if isinstance(tag, str) and tag.casefold() not in folded:
            survivor_tags.append(tag)
            folded.add(tag.casefold())
        elif not isinstance(tag, str) and tag not in survivor_tags:
            survivor_tags.append(tag)
    survivor.tags = survivor_tags

    moved_rows = sum(s["moved"] for s in moved.values()) + sum(polymorphic.values())
    replaced_rows = sum(s["replaced"] for s in moved.values())
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=survivor_id,
            action="candidates_merged",
            user_id=user_id,
            details={
                "duplicate_id": duplicate_id,
                "moved_rows": moved_rows,
                "replaced_rows": replaced_rows,
                "tables": sorted(moved),
                "fields_from_duplicate": sorted(updates),
            },
        )
    )

    from app.models.index_outbox import IndexOutboxEvent
    from app.services.match_score_cache import mark_stale_for_candidate

    now = datetime.now(timezone.utc)
    db.add(
        IndexOutboxEvent(
            entity_type="candidate",
            entity_id=duplicate_id,
            entity_revision=int(now.timestamp() * 1_000_000),
            desired_hash="",
            operation="delete",
            status="pending",
        )
    )
    await mark_stale_for_candidate(db, survivor_id)
    await db.flush()
    try:
        from app.services.index_outbox_service import schedule_or_embed_candidate

        async with db.begin_nested():
            await schedule_or_embed_candidate(survivor_id, db)
    except Exception as exc:  # noqa: BLE001 — reindeks nie cofa scalenia
        logger.warning(
            "[candidate_merge] reindex failed survivor=%s: %s",
            survivor_id,
            type(exc).__name__,
        )
    return {
        "survivor_id": survivor_id,
        "duplicate_id": duplicate_id,
        "moved_rows": moved_rows,
        "replaced_rows": replaced_rows,
        "fields_from_duplicate": sorted(updates),
    }


async def drop_duplicate_vector(duplicate_id: int) -> None:
    """Po commicie: natychmiastowa próba skasowania wektora (retry w outboxie)."""

    from app.services.embedding_service import delete_candidate_embedding

    try:
        await delete_candidate_embedding(duplicate_id)
    except Exception:  # noqa: BLE001 — retry stoi w outboxie
        logger.warning("[candidate_merge] vector cleanup deferred id=%s", duplicate_id)
