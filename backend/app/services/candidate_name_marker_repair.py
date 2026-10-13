"""Imię i nazwisko bez dopisków — jednorazowa korekta danych (0436, 13.10.2026).

Dopiski z Traffita („[ACTIVE] Jan”, „Nowak (zaakceptowany)”, „(czarna lista)”)
siedziały w imionach mimo migracji 0165 i 0232: tamte znały tylko część
rodziny słów, a jedna osoba miała ręczną blokadę imienia założoną przez import
(``bootstrap_mismatch``), więc sync nie mógł jej poprawić.

Korekta, wiersz po wierszu, NAJPIERW POLE, POTEM TEKST:

- dopisek czarnej listy → ``status = 'blacklisted'`` (chyba że status
  poprawił człowiek — znacznik ``_nexus_identity.status_manual``, ten sam,
  który szanuje import Traffita);
- „active”/„aktywny” → ``availability_status = 'actively_looking'``, gdy było
  ``unknown``; pole z takim dopiskiem pod ręczną blokadą wraca do wartości
  z Traffita (``_nexus_identity.traffit_name``/``traffit_lastname``, o ile ta
  sama nie ma dopisku), a blokada znika;
- pozostałe („zaakceptowany”, „ekspracownik”, notatki, certyfikaty) — tylko
  zdjęcie.

Każdy zdjęty dopisek trafia do ``cv_extracted_data.traffit_name_marker``
(ten sam klucz i kształt co w mapperze: napis z dopiskami po spacji), tylko
gdy ``cv_extracted_data`` jest obiektem — część wierszy ma tam tablicę.
Bez notatek: automaty nie piszą notatek (0399). Pole, które było samym
dopiskiem, dostaje „?” (fallback z 0232 i mappera).

Reguła jest JEDNA: ``candidate_name_rules.strip_name_markers`` — tą samą
funkcją czyści import Traffita, więc nocny sync nie przywróci dopisków.
Wstępny filtr SQL jest nadzbiorem (nawias, ukośnik albo rdzeń słowa
statusu); o zmianie decyduje Python.

Paragon ``app_settings['0436_candidate_name_markers']``: liczby i ID, bez
nazwisk. Stare wartości pod ``repair_details_0436_candidate_name_markers``
(klucz spoza wzorca paragonów, więc nie trafia do publicznego logu).

Rdzeń jest SYNCHRONICZNY, bo migracja 0436 biegnie w ``run_sync`` alembica;
faza startu w ``entrypoint.sh`` (alembic na produkcji bywa osierocony) woła
ten sam rdzeń przez ``run_candidate_name_marker_repair`` i dopiero ona
zapisuje kolejkę indeksu (``record_bulk_reindex`` jest asynchroniczny) —
także po korekcie wykonanej wcześniej przez migrację (``reindex_recorded``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.candidate_name_rules import (
    find_name_markers,
    has_active_marker,
    has_blacklist_marker,
    strip_name_markers,
)

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0436_candidate_name_markers"
DETAILS_KEY = "repair_details_0436_candidate_name_markers"
EMPTY_NAME_PLACEHOLDER = "?"

# Nadzbiór wszystkiego, co łapie `find_name_markers`: nawias albo ukośnik
# (dopiski w nawiasach i słowa statusu przy ograniczniku) oraz rdzenie słów
# statusu (gołe słowa na krawędzi, „zatrudnion*” w środku). Przekazywany jako
# parametr, nie wklejany w SQL.
PREFILTER_PATTERN = (
    r"[][()/]|activ|aktywn|passive|zatrudn|zatrun|akcept|black|czarn|pracowni"
)

_SELECT_SQL = text(
    """
    SELECT c.id,
           c.name,
           c.lastname,
           CAST(c.status AS text) AS status,
           CAST(c.availability_status AS text) AS availability_status,
           c.custom_fields #>> '{_nexus_identity,name_manual}' AS name_manual,
           c.custom_fields #>> '{_nexus_identity,lastname_manual}'
               AS lastname_manual,
           c.custom_fields #>> '{_nexus_identity,traffit_name}' AS traffit_name,
           c.custom_fields #>> '{_nexus_identity,traffit_lastname}'
               AS traffit_lastname,
           c.custom_fields #>> '{_nexus_identity,status_manual}' AS status_manual,
           jsonb_typeof(c.cv_extracted_data) = 'object' AS cv_is_object,
           CASE
             WHEN jsonb_typeof(c.cv_extracted_data) = 'object'
             THEN c.cv_extracted_data ->> 'traffit_name_marker'
           END AS name_marker
      FROM candidates c
     WHERE (c.name ~* CAST(:pattern AS text)
            OR c.lastname ~* CAST(:pattern AS text))
       AND (CAST(:only_ids AS integer[]) IS NULL
            OR c.id = ANY(CAST(:only_ids AS integer[])))
     ORDER BY c.id
       FOR UPDATE OF c
    """
)

_UPDATE_SQL = text(
    """
    UPDATE candidates
       SET name = CAST(:name AS text),
           lastname = CAST(:lastname AS text),
           status = CAST(:status AS candidatestatus),
           availability_status = CAST(:availability_status AS availabilitystatus),
           cv_extracted_data = CASE
             WHEN CAST(:provenance AS text) IS NOT NULL
                  AND jsonb_typeof(cv_extracted_data) = 'object'
             THEN jsonb_set(
                    cv_extracted_data,
                    '{traffit_name_marker}',
                    to_jsonb(CAST(:provenance AS text)),
                    true
                  )
             ELSE cv_extracted_data
           END,
           updated_at = NOW()
     WHERE id = :id
    """
)

# Zdjęcie ręcznej blokady pola — te same klucze, które czyści
# `restore_traffit_identity_fields` (candidate_identity_ownership.py).
_CLEAR_LOCK_SQL = {
    field: text(
        f"""
        UPDATE candidates
           SET custom_fields = jsonb_set(
                 custom_fields,
                 '{{_nexus_identity}}',
                 (custom_fields -> '_nexus_identity')
                   - '{field}_manual' - '{field}_set_at'
                   - '{field}_set_by' - '{field}_ownership_reason',
                 true
               )
         WHERE id = :id
           AND jsonb_typeof(custom_fields -> '_nexus_identity') = 'object'
        """
    )
    for field in ("name", "lastname")
}

# Paragon jest zarazem bramką: wstawia go pierwszy bieg, każdy następny (inny
# kontener, migracja po fazie startu) dostaje pusty RETURNING i nic nie robi.
_RECEIPT_CLAIM_SQL = text(
    """
    INSERT INTO app_settings (key, value)
    VALUES (:key, CAST(:value AS jsonb))
    ON CONFLICT (key) DO NOTHING
    RETURNING key
    """
)
_RECEIPT_SAVE_SQL = text(
    """
    INSERT INTO app_settings (key, value)
    VALUES (:key, CAST(:value AS jsonb))
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
    """
)
_RECEIPT_READ_SQL = text(
    "SELECT CAST(value AS text) FROM app_settings WHERE key = :key"
)


@dataclass(frozen=True)
class NameMarkerRow:
    """Wiersz kandydata z wstępnego filtra — tylko pola, których korekta dotyka."""

    id: int
    name: str
    lastname: str
    status: str = "active"
    availability_status: str = "unknown"
    name_manual: bool = False
    lastname_manual: bool = False
    traffit_name: Optional[str] = None
    traffit_lastname: Optional[str] = None
    status_manual: bool = False
    cv_is_object: bool = True
    name_marker: Optional[str] = None


@dataclass(frozen=True)
class NameMarkerFix:
    id: int
    name: str
    lastname: str
    status: str
    availability_status: str
    markers: tuple[str, ...]
    cleared_locks: tuple[str, ...]
    provenance: Optional[str]
    blacklist_kept_manual_status: bool
    placeholder_fields: tuple[str, ...]


def _flag(value: Any) -> bool:
    return str(value).strip().lower() == "true" if value is not None else False


def _row(mapping: Any) -> NameMarkerRow:
    return NameMarkerRow(
        id=int(mapping["id"]),
        name=mapping["name"] or "",
        lastname=mapping["lastname"] or "",
        status=mapping["status"],
        availability_status=mapping["availability_status"],
        name_manual=_flag(mapping["name_manual"]),
        lastname_manual=_flag(mapping["lastname_manual"]),
        traffit_name=mapping["traffit_name"],
        traffit_lastname=mapping["traffit_lastname"],
        status_manual=_flag(mapping["status_manual"]),
        cv_is_object=bool(mapping["cv_is_object"]),
        name_marker=mapping["name_marker"],
    )


def _provenance(existing: Optional[str], markers: Sequence[str]) -> str:
    """Dopisz zdjęte dopiski do napisu prowieniencji bez powtórzeń."""
    current = existing.strip() if isinstance(existing, str) else ""
    fresh = [marker for marker in markers if marker not in current]
    return " ".join(part for part in (current, " ".join(fresh)) if part)


def plan_fix(row: NameMarkerRow) -> Optional[NameMarkerFix]:
    """Co korekta zrobi z wierszem; ``None`` = imię i nazwisko bez dopisków."""

    name, name_markers = strip_name_markers(row.name)
    lastname, lastname_markers = strip_name_markers(row.lastname)
    markers = name_markers + lastname_markers
    if not markers:
        return None

    values = {"name": name, "lastname": lastname}
    cleared: list[str] = []
    for field, field_markers, manual, source in (
        ("name", name_markers, row.name_manual, row.traffit_name),
        ("lastname", lastname_markers, row.lastname_manual, row.traffit_lastname),
    ):
        if not (field_markers and manual and has_active_marker(field_markers)):
            continue
        source_value = (source or "").strip()
        if source_value and not find_name_markers(source_value):
            values[field] = source_value[:100]
            cleared.append(field)

    placeholders: list[str] = []
    for field in ("name", "lastname"):
        if not values[field]:
            values[field] = EMPTY_NAME_PLACEHOLDER
            placeholders.append(field)

    status = row.status
    kept_manual = False
    if has_blacklist_marker(*markers) and row.status != "blacklisted":
        if row.status_manual:
            kept_manual = True
        else:
            status = "blacklisted"

    availability = row.availability_status
    if has_active_marker(markers) and availability == "unknown":
        availability = "actively_looking"

    return NameMarkerFix(
        id=row.id,
        name=values["name"],
        lastname=values["lastname"],
        status=status,
        availability_status=availability,
        markers=tuple(markers),
        cleared_locks=tuple(cleared),
        provenance=_provenance(row.name_marker, markers) if row.cv_is_object else None,
        blacklist_kept_manual_status=kept_manual,
        placeholder_fields=tuple(placeholders),
    )


def build_receipt(
    rows: Sequence[NameMarkerRow], fixes: Sequence[NameMarkerFix]
) -> dict:
    """Paragon: liczby i ID — bez imion, nazwisk i treści dopisków."""
    by_id = {row.id: row for row in rows}
    return {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "scanned": len(rows),
        "changed": len(fixes),
        "changed_candidate_ids": [fix.id for fix in fixes],
        "markers_stripped": sum(len(fix.markers) for fix in fixes),
        "blacklisted_candidate_ids": [
            fix.id for fix in fixes if fix.status != by_id[fix.id].status
        ],
        "blacklist_kept_manual_status_ids": [
            fix.id for fix in fixes if fix.blacklist_kept_manual_status
        ],
        "actively_looking_candidate_ids": [
            fix.id
            for fix in fixes
            if fix.availability_status != by_id[fix.id].availability_status
        ],
        "name_lock_cleared_ids": [
            fix.id for fix in fixes if "name" in fix.cleared_locks
        ],
        "lastname_lock_cleared_ids": [
            fix.id for fix in fixes if "lastname" in fix.cleared_locks
        ],
        "provenance_written_ids": [
            fix.id for fix in fixes if fix.provenance is not None
        ],
        "placeholder_ids": [fix.id for fix in fixes if fix.placeholder_fields],
        "reindex_recorded": False,
    }


def _details(rows: Sequence[NameMarkerRow], fixes: Sequence[NameMarkerFix]) -> dict:
    """Stare wartości do ręcznego cofnięcia — pod kluczem spoza wzorca paragonów."""
    by_id = {row.id: row for row in rows}
    return {
        str(fix.id): {
            "name": by_id[fix.id].name,
            "lastname": by_id[fix.id].lastname,
            "status": by_id[fix.id].status,
            "availability_status": by_id[fix.id].availability_status,
            "markers": list(fix.markers),
            "cleared_locks": list(fix.cleared_locks),
        }
        for fix in fixes
    }


def apply_name_marker_repair(
    conn: Any,
    *,
    marker: str = REPAIR_MARKER,
    details_key: str = DETAILS_KEY,
    only_ids: Optional[Sequence[int]] = None,
) -> Optional[dict]:
    """Wykonaj korektę raz na synchronicznym połączeniu; ``None`` = już była.

    Wołający commituje. ``only_ids`` zawęża korektę (testy na współdzielonej
    bazie testowej); produkcja i migracja wołają bez niego.
    """

    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker})
    claimed = conn.execute(
        _RECEIPT_CLAIM_SQL, {"key": marker, "value": json.dumps({"state": "running"})}
    ).first()
    if claimed is None:
        return None

    rows = [
        _row(mapping)
        for mapping in conn.execute(
            _SELECT_SQL,
            {
                "pattern": PREFILTER_PATTERN,
                "only_ids": list(only_ids) if only_ids is not None else None,
            },
        ).mappings()
    ]
    fixes = [fix for fix in (plan_fix(row) for row in rows) if fix is not None]
    for fix in fixes:
        conn.execute(
            _UPDATE_SQL,
            {
                "id": fix.id,
                "name": fix.name,
                "lastname": fix.lastname,
                "status": fix.status,
                "availability_status": fix.availability_status,
                "provenance": fix.provenance,
            },
        )
        for field in fix.cleared_locks:
            conn.execute(_CLEAR_LOCK_SQL[field], {"id": fix.id})

    summary = build_receipt(rows, fixes)
    conn.execute(_RECEIPT_SAVE_SQL, {"key": marker, "value": json.dumps(summary)})
    if fixes:
        conn.execute(
            _RECEIPT_SAVE_SQL,
            {"key": details_key, "value": json.dumps(_details(rows, fixes))},
        )
    return summary


async def run_candidate_name_marker_repair(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    details_key: str = DETAILS_KEY,
    only_ids: Optional[Sequence[int]] = None,
) -> Optional[dict]:
    """Faza startu: korekta (jeśli jeszcze nie było) i kolejka indeksu.

    ``None`` = korekta i kolejka indeksu już zapisane. Gdy korektę wykonała
    migracja 0436 (bez kolejki — alembic jest synchroniczny), ten bieg
    dopisuje kolejkę dla jej ID i zwraca uzupełniony paragon. Wołający commituje.
    """
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    summary = await db.run_sync(
        lambda session: apply_name_marker_repair(
            session.connection(),
            marker=marker,
            details_key=details_key,
            only_ids=only_ids,
        )
    )
    if summary is None:
        raw = await db.scalar(_RECEIPT_READ_SQL, {"key": marker})
        summary = json.loads(raw) if raw else None
        if not isinstance(summary, dict) or summary.get("reindex_recorded", True):
            return None
    changed = [int(cid) for cid in summary.get("changed_candidate_ids") or []]
    if changed:
        await record_bulk_reindex(db, CANDIDATE, changed)
    summary = {**summary, "reindex_recorded": True}
    await db.execute(_RECEIPT_SAVE_SQL, {"key": marker, "value": json.dumps(summary)})
    logger.info("candidate name markers: %s", summarize_for_log(summary))
    return summary


def summarize_for_log(summary: Optional[dict]) -> str:
    """Linia do logu startu — wyłącznie liczby."""
    if summary is None:
        return "already applied"
    return (
        f"scanned={summary.get('scanned', 0)} "
        f"changed={summary.get('changed', 0)} "
        f"markers={summary.get('markers_stripped', 0)} "
        f"blacklisted={len(summary.get('blacklisted_candidate_ids') or [])} "
        f"actively_looking="
        f"{len(summary.get('actively_looking_candidate_ids') or [])} "
        f"locks_cleared="
        f"{len(summary.get('name_lock_cleared_ids') or [])}"
        f"+{len(summary.get('lastname_lock_cleared_ids') or [])}"
    )
