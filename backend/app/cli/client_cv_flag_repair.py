"""Flagi „główne” i kopie „Oryginał CV” po #2926 — naprawa danych (04.11.2026).

#2926 sprawił, że firmowy Word „B2B_….docx” ustępuje CV kandydata jako źródło
generatora (`cv_source.current_cv_ordering`), ale stare dane zostały: firmowy
plik ma dalej flagę „główne” (profil, odczyt AI), a kopie etapu wskazują go jako
„Oryginał CV”, z którym porównuje QC. Pomiar na kopii z 04.11.2026 i decyzja:
`docs/claude/generator-cv/firmowe-cv-ustepuje-cv-kandydata.md`.

Uruchomienie (w kontenerze backendu)::

    python -m app.cli.client_cv_flag_repair --dry-run
    python -m app.cli.client_cv_flag_repair --commit --expected-flags N --expected-copies M
    python -m app.cli.client_cv_flag_repair --rollback

Zasady:

* zakres: osoba z flagą na firmowym Wordzie albo z kopią „Oryginał CV” z firmowego
  Worda, która ma też plik rodzaju „cv” bez cechy firmowego. „Other” nie jest
  następcą (import Traffita nie klasyfikuje plików), a PDF „B2B” jest CV kandydata;
* następca: główny plik niefirmowy, a bez niego najnowszy z datą, potem PDF/DOCX
  przed DOC, potem najwyższe id. `uploaded_at` i `content_sha256` plików z Traffita
  to zwykle NULL, więc kolejność jawnie stawia brak daty na końcu, a SHA liczymy
  z bajtów;
* bajty każdego kandydata na następcę są czytane: plik bez bajtów, nieczytelny,
  bez nazwiska osoby, z układem szablonu, z umową w nazwie albo z treścią firmowego
  odpada i trafia na listę do przeglądu z samym id;
* flaga przechodzi na następcę, plik firmowy zostaje w profilu z rodzajem „cv”.
  Nic nie jest kasowane ani w bazie, ani w magazynie;
* kopia etapu dostaje następcę tylko bez CV do klienta (`branded_status="none"`).
  Szkic i zatwierdzone CV porównują się ze swoim wzorem, plik wgrany ręcznie jest
  wyborem rekrutera, a kopia z bajtami w bazie nie dałaby się cofnąć. Raport je liczy;
* AI nie czyta profilu od nowa bez ``--reread``, bo tego ``--rollback`` nie cofnie.
  Plik DOC bywa następcą, chyba że podano ``--exclude-doc``: nie ma podglądu
  w przeglądarce, a generator go nie czyta (zostaje przy firmowym Wordzie);
* ``--commit`` wymaga liczb z próby na sucho. Każda osoba w osobnej transakcji,
  stan sprawdzany pod blokadą. Paragon
  ``app_settings['client_cv_flag_repair_2026_11']`` niesie same id i liczby, a stan
  sprzed zmiany leży w `activities`, skąd czyta go ``--rollback``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import case, func, or_, select, text, update

logger = logging.getLogger(__name__)

RECEIPT_KEY = "client_cv_flag_repair_2026_11"
_SOURCE = "client_cv_repair"
_FLAG_ACTION = "primary_cv_flag_repaired"
_COPY_ACTION = "snapshot_client_cv_flag_repaired"
_REREAD_TRIGGER = "cv_repair"
_CV_EXT = (".pdf", ".doc", ".docx")
_MIN_NAME_PART = 3


@dataclass(frozen=True)
class Planned:
    candidate_id: int
    # Plik firmowy z flagą. None: flaga jest w porządku, zostają same kopie.
    client_cv_id: Optional[int]
    successor_id: Optional[int] = None
    successor_ext: Optional[str] = None
    successor_sha256: Optional[str] = None
    copy_ids: tuple[int, ...] = ()
    # Plik, który dziś biorą paczka i generator (przed zmianą flagi).
    package_changes: bool = False
    generator_changes: bool = False
    rejected_files: dict[str, tuple[int, ...]] = field(default_factory=dict)


def _ext(filename: Optional[str]) -> str:
    return os.path.splitext((filename or "").lower())[1]


def _firm_copy_clause() -> Any:
    """Kopia etapu z firmowego Worda (lustro `cv_source.client_cv_file_clause`)."""
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.services.client_cv_upload import CLIENT_CV_NAME

    return (
        CandidateStageCV.original_cv_filename.op("~*")(CLIENT_CV_NAME.pattern)
    ) & func.lower(CandidateStageCV.original_cv_filename).like("%.docx")


def _candidate_file_filters() -> tuple:
    """Plik, który może zastąpić firmowy: rodzaj „cv”, niefirmowy, PDF/DOC/DOCX."""
    from sqlalchemy import not_

    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services.cv_source import client_cv_file_clause, current_cv_filters

    return (
        CandidateDocument.document_kind == CandidateDocumentKind.cv,
        not_(client_cv_file_clause()),
        or_(
            *(func.lower(CandidateDocument.filename).like(f"%{ext}") for ext in _CV_EXT)
        ),
        *current_cv_filters(),
    )


def _successor_ordering() -> tuple:
    """Główny, data (brak na końcu: Postgres przy DESC stawia NULL pierwszy), PDF/DOCX."""
    from app.models.candidate_document import CandidateDocument

    return (
        CandidateDocument.is_primary.desc(),
        CandidateDocument.uploaded_at.desc().nulls_last(),
        case(
            (func.lower(CandidateDocument.filename).like("%.doc"), 1),
            else_=0,
        ),
        CandidateDocument.id.desc(),
    )


async def _document_bytes(db, document_id: int, storage_key: Optional[str]) -> Any:
    """Bajty pliku z magazynu, a bez klucza z bazy. ``None`` przy awarii magazynu."""
    from app.models.candidate_document import CandidateDocument
    from app.services import object_storage

    if storage_key:
        try:
            return await run_in_threadpool(object_storage.download_cv, storage_key)
        except Exception as error:  # noqa: BLE001 — plik bez bajtów odpada z planu
            logger.warning(
                "client_cv_flag_repair doc=%s download failed: %s",
                document_id,
                type(error).__name__,
            )
            return None
    content = await db.scalar(
        select(CandidateDocument.file_content).where(
            CandidateDocument.id == document_id
        )
    )
    return bytes(content) if content else None


async def _extract_text(data: bytes, filename: str) -> str:
    from app.services.cv_backfill import _extract_text_from_bytes

    return await _extract_text_from_bytes(data, filename)


def _fold(value: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", value or "")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return plain.replace("ł", "l").replace("Ł", "L").casefold()


def _has_lastname(lastname: Optional[str], cv_text: str) -> bool:
    folded = _fold(cv_text)
    parts = [
        part
        for part in _fold(lastname or "").replace("-", " ").split()
        if len(part) >= _MIN_NAME_PART
    ]
    return bool(parts) and any(part in folded for part in parts)


def _has_template_layout(data: bytes, filename: str, cv_text: str) -> bool:
    """Układ szablonu B2B także w PDF, DOC i Wordzie bez „B2B” w nazwie.

    Word sprawdza ta sama reguła co okno „Użyj gotowego CV”. W tekście PDF i DOC
    liczą się te same linie: etykieta „Nazwa firmy:” bywa w zwykłym CV, dlatego
    sama nie wystarcza, potrzebna jest para etykiet przy kilku stanowiskach.
    """
    from app.services import cv_docx_import
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    if _ext(filename) == ".docx":
        try:
            if cv_docx_import.docx_to_editor_html(data).b2b_template:
                return True
        except Exception:  # noqa: BLE001 — PDF pod nazwą .docx czyta tekst niżej
            pass
    folded = _fold(cv_text)
    for labels in TRANSLATIONS.values():
        if _fold(labels["why"]) in folded:
            return True
        if (
            folded.count(_fold(labels["company_name"])) >= 2
            and folded.count(_fold(labels["position"])) >= 2
        ):
            return True
    return False


async def _file_problem(
    data: Optional[bytes],
    filename: str,
    lastname: Optional[str],
    client_cv_sha256: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """(powód odrzucenia albo ``None``, SHA z bajtów)."""
    from app.cli.contract_as_cv_repair import looks_like_contract

    if not data:
        return "no_bytes", None
    digest = hashlib.sha256(data).hexdigest()
    if digest == client_cv_sha256:
        return "same_as_client_cv", digest
    if looks_like_contract(filename):
        return "contract", digest
    try:
        cv_text = await _extract_text(data, filename)
    except Exception as error:  # noqa: BLE001 — nieczytelny plik idzie do przeglądu
        logger.warning(
            "client_cv_flag_repair text failed: %s",
            type(error).__name__,
        )
        cv_text = ""
    if not cv_text.strip():
        return "unreadable", digest
    if _has_template_layout(data, filename, cv_text):
        return "template_layout", digest
    if not _has_lastname(lastname, cv_text):
        return "no_lastname", digest
    return None, digest


async def _today_picks(db, candidate_id: int) -> tuple[Optional[int], Optional[int]]:
    """Plik, który dziś biorą paczka CV i generator (ten sam wybór co `get_current_cv`)."""
    from app.models.candidate_document import CandidateDocument
    from app.services.cv_generator_b2b.standalone_service import (
        _supported_cv_doc_filter,
    )
    from app.services.cv_source import current_cv_filters, current_cv_ordering

    base = (
        select(CandidateDocument.id)
        .where(CandidateDocument.candidate_id == candidate_id, *current_cv_filters())
        # Bez id na końcu, jak `get_current_cv`: między plikami bez daty wybór jest
        # dziś przypadkowy, a raport ma powiedzieć, co faktycznie się zmieni.
        .order_by(*current_cv_ordering())
        .limit(1)
    )
    package = await db.scalar(
        base.where(
            or_(
                *(
                    func.lower(CandidateDocument.filename).like(f"%{ext}")
                    for ext in _CV_EXT
                )
            )
        )
    )
    generator = await db.scalar(base.where(_supported_cv_doc_filter()))
    return package, generator


async def _scope(
    db, candidate_ids: Optional[list[int]]
) -> tuple[dict[int, int], dict[int, list[Any]]]:
    """Flagi na firmowym Wordzie i kopie z niego u osób z plikiem kandydata."""
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.services.cv_source import client_cv_file_clause

    has_file = (
        select(CandidateDocument.candidate_id)
        .where(*_candidate_file_filters())
        .distinct()
    )
    flags_q = select(CandidateDocument.candidate_id, CandidateDocument.id).where(
        CandidateDocument.is_primary.is_(True),
        CandidateDocument.document_kind == CandidateDocumentKind.cv,
        CandidateDocument.source_deleted_at.is_(None),
        client_cv_file_clause(),
        CandidateDocument.candidate_id.in_(has_file),
    )
    copies_q = select(
        CandidateStageCV.candidate_id,
        CandidateStageCV.id,
        CandidateStageCV.branded_status,
        CandidateStageCV.original_snapshot_source,
        CandidateStageCV.original_cv_content.isnot(None).label("has_bytes"),
    ).where(_firm_copy_clause(), CandidateStageCV.candidate_id.in_(has_file))
    if candidate_ids is not None:
        flags_q = flags_q.where(CandidateDocument.candidate_id.in_(candidate_ids))
        copies_q = copies_q.where(CandidateStageCV.candidate_id.in_(candidate_ids))
    flags = {row[0]: row[1] for row in (await db.execute(flags_q)).all()}
    copies: dict[int, list[Any]] = {}
    for row in (await db.execute(copies_q)).all():
        copies.setdefault(row.candidate_id, []).append(row)
    return flags, copies


def _copy_left_reason(row: Any) -> Optional[str]:
    """Dlaczego kopia zostaje. ``None``: dostaje plik kandydata."""
    if row.has_bytes:
        return "bytes_in_db"
    if row.original_snapshot_source == "manual_upload":
        return "manual_upload"
    if (row.branded_status or "none") != "none":
        return f"branded_{row.branded_status}"
    return None


async def plan(
    db, *, candidate_ids: Optional[list[int]] = None, exclude_doc: bool = False
) -> tuple[list[Planned], dict[str, list[int]]]:
    """Osoby do naprawy i kopie, które zostają. Czyta bajty, niczego nie zapisuje."""
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument

    flags, copies = await _scope(db, candidate_ids)
    items: list[Planned] = []
    left: dict[str, list[int]] = {}
    for candidate_id in sorted({*flags, *copies}):
        planned_copies: list[int] = []
        for row in copies.get(candidate_id, []):
            reason = _copy_left_reason(row)
            if reason is None:
                planned_copies.append(row.id)
            else:
                left.setdefault(reason, []).append(row.id)
        client_cv_id = flags.get(candidate_id)
        if client_cv_id is None and not planned_copies:
            continue

        lastname = await db.scalar(
            select(Candidate.lastname).where(Candidate.id == candidate_id)
        )
        client_sha = None
        if client_cv_id is not None:
            key = await db.scalar(
                select(CandidateDocument.storage_key).where(
                    CandidateDocument.id == client_cv_id
                )
            )
            client_bytes = await _document_bytes(db, client_cv_id, key)
            client_sha = (
                hashlib.sha256(client_bytes).hexdigest() if client_bytes else None
            )

        files = (
            await db.execute(
                select(
                    CandidateDocument.id,
                    CandidateDocument.filename,
                    CandidateDocument.storage_key,
                )
                .where(
                    CandidateDocument.candidate_id == candidate_id,
                    *_candidate_file_filters(),
                )
                .order_by(*_successor_ordering())
            )
        ).all()
        successor_id = successor_ext = successor_sha = None
        rejected: dict[str, list[int]] = {}
        for doc_id, filename, storage_key in files:
            if exclude_doc and _ext(filename) == ".doc":
                rejected.setdefault("doc_excluded", []).append(doc_id)
                continue
            data = await _document_bytes(db, doc_id, storage_key)
            problem, digest = await _file_problem(
                data, filename or "", lastname, client_sha
            )
            if problem is not None:
                rejected.setdefault(problem, []).append(doc_id)
                continue
            successor_id, successor_ext, successor_sha = (
                doc_id,
                _ext(filename),
                digest,
            )
            break
        package, generator = await _today_picks(db, candidate_id)
        items.append(
            Planned(
                candidate_id=candidate_id,
                client_cv_id=client_cv_id,
                successor_id=successor_id,
                successor_ext=successor_ext,
                successor_sha256=successor_sha,
                copy_ids=tuple(planned_copies) if successor_id else (),
                package_changes=bool(successor_id and package != successor_id),
                # Generator nie czyta DOC, więc taka flaga nie zmienia jego wyboru.
                generator_changes=bool(
                    successor_id
                    and successor_ext != ".doc"
                    and generator != successor_id
                ),
                rejected_files={k: tuple(v) for k, v in rejected.items()},
            )
        )
    return items, left


def summarize(items: list[Planned], left: dict[str, list[int]]) -> dict[str, Any]:
    """Raport: same id i liczby, bez nazw plików i osób (logi bywają publiczne)."""
    ready = [item for item in items if item.successor_id is not None]
    flips = [item for item in ready if item.client_cv_id is not None]
    rejected: dict[str, list[int]] = {}
    for item in items:
        for reason, doc_ids in item.rejected_files.items():
            rejected.setdefault(reason, []).extend(doc_ids)
    return {
        "people": len(items),
        "flags": len(flips),
        "copies": sum(len(item.copy_ids) for item in ready),
        "people_with_copies": sum(1 for item in ready if item.copy_ids),
        "copies_only_people": sum(1 for item in ready if item.client_cv_id is None),
        "successor_ext": dict(Counter(item.successor_ext for item in flips)),
        "without_successor": [
            item.candidate_id for item in items if item.successor_id is None
        ],
        "rejected_files": rejected,
        "copies_left": {reason: len(ids) for reason, ids in sorted(left.items())},
        "package_changes": [
            item.candidate_id for item in flips if item.package_changes
        ],
        "generator_changes": [
            item.candidate_id for item in flips if item.generator_changes
        ],
        # Trójki osoba, plik firmowy, następca.
        "flag_ids": [
            [item.candidate_id, item.client_cv_id, item.successor_id] for item in flips
        ],
        "copy_ids": [copy_id for item in ready for copy_id in item.copy_ids],
    }


async def repair_one(db, item: Planned) -> Optional[dict[str, Any]]:
    """Flaga i kopie jednej osoby. Zwraca liczniki albo ``None``, gdy stan się zmienił.

    Stan sprawdzamy jeszcze raz pod blokadą: od próby na sucho ktoś mógł wskazać
    inne główne CV, usunąć plik albo zacząć pracę nad CV do klienta.
    """
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.services.candidate_identity_quarantine import ReplacedPrimaryCv
    from app.services.candidate_stage_cv_service import refresh_original_cv_snapshot
    from app.services.cv_source import CurrentCV

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{RECEIPT_KEY}:{item.candidate_id}"},
    )
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == item.candidate_id).with_for_update()
    )
    successor = await db.scalar(
        select(CandidateDocument).where(
            CandidateDocument.id == item.successor_id,
            CandidateDocument.candidate_id == item.candidate_id,
            *_candidate_file_filters(),
        )
    )
    if candidate is None or successor is None:
        return None

    replaced = None
    if item.client_cv_id is not None:
        client_cv = await db.get(CandidateDocument, item.client_cv_id)
        if (
            client_cv is None
            or not client_cv.is_primary
            or client_cv.source_deleted_at is not None
        ):
            return None
        old_filename = candidate.cv_filename
        replaced = ReplacedPrimaryCv(document_id=client_cv.id, cv_filename=old_filename)
        # Częściowy UNIQUE na aktywne główne CV: najpierw zdjęcie flagi w bazie.
        await db.execute(
            update(CandidateDocument)
            .where(
                CandidateDocument.candidate_id == candidate.id,
                CandidateDocument.document_kind == CandidateDocumentKind.cv,
                CandidateDocument.is_primary.is_(True),
            )
            .values(is_primary=False)
            .execution_options(synchronize_session=False)
        )
        await db.refresh(client_cv)
        successor.is_primary = True
        candidate.cv_filename = successor.filename
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate.id,
                action=_FLAG_ACTION,
                details={
                    "client_cv_document_id": client_cv.id,
                    "successor_document_id": successor.id,
                    "old_cv_filename": old_filename,
                },
            )
        )
        await db.flush()

    copies = 0
    copies_skipped = 0
    if item.copy_ids:
        data = await _document_bytes(db, successor.id, successor.storage_key)
        if not data or hashlib.sha256(data).hexdigest() != item.successor_sha256:
            await db.rollback()
            return None
        current = CurrentCV(
            content=data,
            filename=successor.filename,
            language=candidate.cv_language,
            source="document_storage" if successor.storage_key else "document_bytea",
        )
        for copy_id in item.copy_ids:
            copy = await db.scalar(
                select(CandidateStageCV)
                .where(CandidateStageCV.id == copy_id, _firm_copy_clause())
                .with_for_update()
            )
            if (
                copy is None
                or copy.original_cv_content is not None
                or copy.original_snapshot_source == "manual_upload"
                or (copy.branded_status or "none") != "none"
            ):
                copies_skipped += 1
                continue
            before = {
                "old_filename": copy.original_cv_filename,
                "old_storage_key": copy.original_cv_storage_key,
                "old_sha256": copy.original_cv_sha256,
                "old_language": copy.original_cv_language,
                "old_source": copy.original_snapshot_source,
                "old_at": (
                    copy.original_snapshot_at.isoformat()
                    if copy.original_snapshot_at
                    else None
                ),
            }
            await refresh_original_cv_snapshot(
                db,
                copy.candidate_stage_id,
                user_id=None,
                source=_SOURCE,
                current=current,
            )
            db.add(
                Activity(
                    entity_type="candidate_stage_cv",
                    entity_id=copy.id,
                    action=_COPY_ACTION,
                    details={**before, "new_sha256": copy.original_cv_sha256},
                )
            )
            copies += 1
    await db.commit()
    return {
        "replaced": replaced,
        "copies": copies,
        "copies_skipped": copies_skipped,
    }


async def repair(
    items: list[Planned],
    *,
    session_factory: Optional[Callable] = None,
    reread: bool = False,
) -> dict[str, int]:
    """Naprawa osób z następcą, każda w osobnej transakcji. Zwraca liczniki."""
    from app.models.candidate import Candidate

    if session_factory is None:
        from app.core.database import AsyncSessionLocal as session_factory

    stats = {
        "flags_repaired": 0,
        "copies_repaired": 0,
        "copies_skipped": 0,
        "people_skipped": 0,
        "failed": 0,
        "profile_reread": 0,
    }
    for item in items:
        if item.successor_id is None:
            continue
        try:
            async with session_factory() as db:
                before = await db.scalar(
                    select(Candidate.cv_parsed_at).where(
                        Candidate.id == item.candidate_id
                    )
                )
                done = await repair_one(db, item)
            if done is None:
                stats["people_skipped"] += 1
                continue
            stats["copies_repaired"] += done["copies"]
            stats["copies_skipped"] += done["copies_skipped"]
            if done["replaced"] is None:
                continue
            stats["flags_repaired"] += 1
            if not reread:
                continue
            from app.api.candidates import _enrich_candidate_from_document_task

            await _enrich_candidate_from_document_task(
                item.candidate_id,
                item.successor_id,
                trigger=_REREAD_TRIGGER,
                replaced_primary=done["replaced"],
            )
            async with session_factory() as db:
                after = await db.scalar(
                    select(Candidate.cv_parsed_at).where(
                        Candidate.id == item.candidate_id
                    )
                )
            if after is not None and after != before:
                stats["profile_reread"] += 1
        except Exception as error:  # noqa: BLE001 — jedna osoba nie zatrzymuje reszty
            logger.warning(
                "client_cv_flag_repair candidate=%s failed: %s",
                item.candidate_id,
                type(error).__name__,
            )
            stats["failed"] += 1
    return stats


async def rollback(*, session_factory: Optional[Callable] = None) -> dict[str, int]:
    """Stan sprzed naprawy z `activities`. Nowsza zmiana człowieka zostaje."""
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.models.candidate_stage_cv import CandidateStageCV

    if session_factory is None:
        from app.core.database import AsyncSessionLocal as session_factory

    stats = {
        "flags_restored": 0,
        "flags_kept": 0,
        "copies_restored": 0,
        "copies_kept": 0,
    }
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(Activity.action, Activity.entity_id, Activity.details)
                .where(Activity.action.in_((_FLAG_ACTION, _COPY_ACTION)))
                .order_by(Activity.id)
            )
        ).all()
    for action, entity_id, details in rows:
        async with session_factory() as db:
            if action == _COPY_ACTION:
                copy = await db.scalar(
                    select(CandidateStageCV)
                    .where(CandidateStageCV.id == entity_id)
                    .with_for_update()
                )
                if (
                    copy is None
                    or copy.original_snapshot_source != _SOURCE
                    or copy.original_cv_sha256 != details["new_sha256"]
                ):
                    stats["copies_kept"] += 1
                    continue
                copy.original_cv_filename = details["old_filename"]
                copy.original_cv_storage_key = details["old_storage_key"]
                copy.original_cv_content = None
                copy.original_cv_sha256 = details["old_sha256"]
                copy.original_cv_language = details["old_language"]
                copy.original_snapshot_source = details["old_source"]
                copy.original_snapshot_at = (
                    datetime.fromisoformat(details["old_at"])
                    if details["old_at"]
                    else None
                )
                stats["copies_restored"] += 1
            else:
                candidate = await db.scalar(
                    select(Candidate).where(Candidate.id == entity_id).with_for_update()
                )
                client_cv = await db.get(
                    CandidateDocument, details["client_cv_document_id"]
                )
                successor = await db.get(
                    CandidateDocument, details["successor_document_id"]
                )
                if (
                    candidate is None
                    or client_cv is None
                    or successor is None
                    or not successor.is_primary
                    or client_cv.source_deleted_at is not None
                ):
                    stats["flags_kept"] += 1
                    continue
                await db.execute(
                    update(CandidateDocument)
                    .where(
                        CandidateDocument.candidate_id == entity_id,
                        CandidateDocument.document_kind == CandidateDocumentKind.cv,
                        CandidateDocument.is_primary.is_(True),
                    )
                    .values(is_primary=False)
                    .execution_options(synchronize_session=False)
                )
                await db.refresh(successor)
                client_cv.is_primary = True
                candidate.cv_filename = details["old_cv_filename"]
                stats["flags_restored"] += 1
            await db.commit()
    return stats


async def _receipt(db) -> Optional[dict[str, Any]]:
    return await db.scalar(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
    )


async def _earlier_run_exists(db) -> bool:
    from app.models.activity import Activity

    return bool(
        await db.scalar(
            select(Activity.id)
            .where(Activity.action.in_((_FLAG_ACTION, _COPY_ACTION)))
            .limit(1)
        )
    )


async def _write_receipt(db, payload: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                                            updated_at = NOW()
            """
        ),
        {"k": RECEIPT_KEY, "v": json.dumps(payload)},
    )
    await db.commit()


async def main(
    argv: Optional[list[str]] = None,
    *,
    candidate_ids: Optional[list[int]] = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--commit", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--expected-flags", type=int)
    parser.add_argument("--expected-copies", type=int)
    parser.add_argument(
        "--exclude-doc",
        action="store_true",
        help="plik DOC nie zostaje następcą: bez podglądu w przeglądarce, generator go nie czyta",
    )
    parser.add_argument(
        "--reread",
        action="store_true",
        help="po zmianie flagi AI czyta profil od nowa; tego --rollback nie cofnie",
    )
    args = parser.parse_args(argv)

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        receipt = await _receipt(db)
        if args.rollback:
            # Bez wymogu paragonu: przerwany bieg ma już zapisane osoby, a paragon
            # powstaje na końcu. Stan sprzed zmiany i tak leży w `activities`.
            if receipt is not None and receipt.get("rolled_back"):
                print(f"Paragon {RECEIPT_KEY}: już cofnięte.", file=sys.stderr)
                return 2
            stats = await rollback()
            await _write_receipt(db, {**(receipt or {}), "rolled_back": stats})
            print(json.dumps({"rollback": stats}, ensure_ascii=False))
            return 0
        if args.commit and receipt is not None:
            print(f"Paragon {RECEIPT_KEY} już jest — przerywam.", file=sys.stderr)
            return 2
        if args.commit and await _earlier_run_exists(db):
            print(
                "Wcześniejszy bieg nie zostawił paragonu — najpierw --rollback.",
                file=sys.stderr,
            )
            return 2
        items, left = await plan(
            db, candidate_ids=candidate_ids, exclude_doc=args.exclude_doc
        )
    report = summarize(items, left)
    print(json.dumps({"plan": report}, ensure_ascii=False))
    if args.dry_run:
        print(
            "Na sucho — nic nie zmieniono. Dalej: --commit "
            f"--expected-flags {report['flags']} --expected-copies {report['copies']}"
        )
        return 0
    if (args.expected_flags, args.expected_copies) != (
        report["flags"],
        report["copies"],
    ):
        print(
            f"Stan bazy różni się od próby: {report['flags']} flag, "
            f"{report['copies']} kopii — przerywam.",
            file=sys.stderr,
        )
        return 2
    stats = await repair(items, reread=args.reread)
    payload = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        **report,
        **stats,
    }
    async with AsyncSessionLocal() as db:
        await _write_receipt(db, payload)
    print(json.dumps({"receipt": stats}, ensure_ascii=False))
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
