"""CV z maila na właściwych osobach — naprawa po uciętym kluczu dokumentu (20.10.2026).

Do 20.10.2026 `attachment_handler.try_parse_cv` zapisywał `external_id`
dokumentu z maila jako pierwsze 100 znaków id załącznika z Graph. Id ma
176–180 znaków ze wspólnym początkiem skrzynki (3 964 załączniki → 13 kluczy),
więc CV z nowego maila znajdowało cudzy dokument i przepinało go na swojego
kandydata razem z cudzym plikiem (kandydat 6673 dostał CV kandydata 26224).
Kod poprawia PR #2447 (`m365_document_external_id`); ten skrypt naprawia dane.

Uruchomienie (w kontenerze backendu, po wdrożeniu #2447)::

    python -m app.cli.m365_document_repair [--exclude 6067]
    python -m app.cli.m365_document_repair [--exclude …] --apply --expected <odcisk>
    … --apply … --reread 6673   # odczyt AI profilu z nowego głównego CV

Zasady:

* załącznik CV = poczta przychodząca, `parsed_candidate_id`, `parse_error IS
  NULL`, plik na dysku zgodny z `email_attachments.sha256`. Właściciel pliku to
  `parsed_candidate_id` załącznika z tymi bajtami (nie skrót zapisany
  w dokumencie — ten przepisywało przepięcie);
* dokument m365, którego bajty nie zgadzają się z `content_sha256`, wraca do
  właściciela pliku, który nie ma jeszcze tego pliku w profilu. Dokument, który
  zły posiadacz usunął z profilu albo który synchronizacja miękko usunęła
  u niego, wraca widoczny (zdjęte `removed_at`, `source_deleted_at`,
  `removed_by`; audyt 22.10.2026, F113, decyzja Artura) — do 22.10 zostawał
  u właściciela ukryty, a jego usunięcie liczyło się jak usunięcie przez
  właściciela, więc właściciel nie dostawał też nowej kopii. Bez takiego
  właściciela (plik tylko z poczty wychodzącej) zostaje miękko usunięty u złego
  posiadacza (`source_deleted_at` / `removed_at`) — nic nie kasujemy (decyzja
  Artura z 26.09.2026: „nie usuwać nigdy żadnych CV”);
* każda osoba z załącznikiem CV, która nie ma w profilu tego pliku, dostaje
  dokument z bajtami swojego załącznika i kluczem `m365_document_external_id`.
  Bez odczytu AI. Plik, który ktoś usunął z profilu tej osoby (`removed_at`),
  nie wraca (0435). Pozostałe dokumenty m365 dostają nowy klucz;
* główne CV: zły posiadacz dostaje najnowsze własne CV (rodzaj „cv”,
  `cv_source.current_cv_filters`, bez CV do klienta), a bez niego żadne.
  Właściciel, któremu wraca plik, i osoba, która dostaje brakujący dokument,
  zachowują swoje główne CV (także „…B2B…” — ktoś je wskazał); bez głównego
  dostają najnowsze własne. Pomiar 20.10: „najnowsze” u wszystkich zmieniłoby
  główne CV z Traffita na CV z maila u osób, którym kod celowo go nie zmienił.
  Wskaźnik na kandydacie idzie za głównym CV, a nazwa albo bajty cudzego pliku
  są odpinane;
* profil złego posiadacza czytany z cudzego dokumentu (`cv_highlights.
  source_document_id`, a bez tego śladu: dokument był głównym CV i wskaźnik
  ma jego nazwę) traci przy ``--apply`` fakty z tego odczytu jak w kwarantannie
  tożsamości: tekst CV, umiejętności, doświadczenie, podsumowanie AI i wektor
  (`clear_foreign_cv_projection`; audyt 22.10.2026, F114, decyzja Artura).
  Ślad nie mówi, czy tekst był z bajtów cudzego pliku, czy z własnego
  załącznika tej osoby (błąd przepinał dokument, a czytał załącznik), więc
  próba na sucho wypisuje te osoby w ``projection_from_foreign``, a kto ma po
  naprawie główne CV, idzie do ``--reread``;
* kopie CV etapu z cudzym plikiem u złego posiadacza dostają jego bieżące CV
  (`restore_stage_copies_after_quarantine`). Próba na sucho wypisuje je razem
  z etapem karty (`client_exposure`) — CV wysłane do klienta to decyzja Artura;
* ``--apply`` wymaga ``--expected`` równego odciskowi planu z próby na sucho;
  inny stan bazy przerywa bieg przed pierwszym zapisem. Całość w jednej
  transakcji. Paragon ``app_settings['m365_document_repair_2026_10']`` niesie
  same liczby i id; ponowne ``--apply`` przy istniejącym paragonie jest
  odrzucane. Raport bez nazwisk i nazw plików (logi Actions są publiczne).

Bieg z 20–21.10.2026 poszedł przed audytem 22.10 (F113, F114), a paragon
blokuje ponowne ``--apply``. Kogo dotyczą obie luki, mówi raport tylko do
odczytu ``backend/scripts/m365_cv_repair_followup_report.sql``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text, update

logger = logging.getLogger(__name__)

RECEIPT_KEY = "m365_document_repair_2026_10"
NEW_KEY_PREFIX = "m365:"


@dataclass(frozen=True)
class MailCv:
    """Pierwszy załącznik przychodzący z danym plikiem u danej osoby."""

    candidate_id: int
    sha256: str
    attachment_id: int
    m365_attachment_id: str
    storage_path: str
    filename: str
    content_type: Optional[str]
    received_at: Optional[datetime]


@dataclass(frozen=True)
class Doc:
    id: int
    candidate_id: int
    content_sha256: Optional[str]
    file_sha256: Optional[str]
    file_size: Optional[int]
    external_id: Optional[str]
    external_source: Optional[str]
    document_kind: str
    is_primary: bool
    deleted: bool
    removed: bool
    outdated: bool
    uploaded_at: Optional[datetime]
    filename: str


@dataclass
class Plan:
    # (doc_id, holder, owner, attachment_id) — dokument wraca do właściciela.
    returns: list[tuple[int, int, int, int]] = field(default_factory=list)
    # (doc_id, holder) — cudzy plik bez właściciela z poczty przychodzącej.
    removals: list[tuple[int, int]] = field(default_factory=list)
    # (doc_id, attachment_id) — dokument zostaje, dostaje nowy klucz.
    rekeys: list[tuple[int, int]] = field(default_factory=list)
    # (candidate_id, attachment_id) — nowy dokument z bajtów załącznika.
    creates: list[tuple[int, int]] = field(default_factory=list)
    # candidate_id → (główne przed, główne po); po: id dokumentu albo
    # "att:<id>" dla nowego, None = bez głównego.
    primaries: dict[int, tuple[Optional[int], Any]] = field(default_factory=dict)
    # (candidate_id, attachment_id, powód)
    skipped: list[tuple[int, int, str]] = field(default_factory=list)
    # (doc_id, holder, sha cudzego pliku, nazwa wiersza, rozmiar) — do kopii
    # CV etapu i wskaźnika.
    foreign: list[tuple[int, int, str, str, int]] = field(default_factory=list)
    # doc_id zwracanych dokumentów, które zły posiadacz ukrył — wracają widoczne.
    restores: list[int] = field(default_factory=list)
    # (holder, doc_id, sha cudzego pliku) — profil czytany z cudzego dokumentu.
    projections: list[tuple[int, int, str]] = field(default_factory=list)
    unverifiable_doc_ids: list[int] = field(default_factory=list)
    mail_cvs: dict[int, MailCv] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = {
            "returns": sorted(self.returns),
            "removals": sorted(self.removals),
            "rekeys": sorted(self.rekeys),
            "creates": sorted(self.creates),
            "primaries": sorted(
                (cid, before, str(after))
                for cid, (before, after) in self.primaries.items()
            ),
            "restores": sorted(self.restores),
            "projections": sorted((cid, doc) for cid, doc, _ in self.projections),
        }
        digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        return digest[:12]


def _read_file(path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except OSError:
        return None


async def _mail_cvs(db, exclude: set[int], candidate_ids: Optional[list[int]]):
    from app.models.candidate import Candidate
    from app.models.m365 import Email, EmailAttachment, EmailDirection

    query = (
        select(
            EmailAttachment.id,
            EmailAttachment.parsed_candidate_id,
            EmailAttachment.sha256,
            EmailAttachment.m365_attachment_id,
            EmailAttachment.storage_path,
            EmailAttachment.filename,
            EmailAttachment.content_type,
            Email.received_at,
        )
        .join(Email, Email.id == EmailAttachment.email_id)
        .join(Candidate, Candidate.id == EmailAttachment.parsed_candidate_id)
        .where(
            EmailAttachment.parse_error.is_(None),
            EmailAttachment.sha256.is_not(None),
            Email.direction == EmailDirection.received,
        )
        .order_by(Email.received_at.asc().nulls_last(), EmailAttachment.id.asc())
    )
    if candidate_ids is not None:
        query = query.where(EmailAttachment.parsed_candidate_id.in_(candidate_ids))
    first: dict[tuple[int, str], MailCv] = {}
    for row in (await db.execute(query)).all():
        if row.parsed_candidate_id in exclude:
            continue
        key = (row.parsed_candidate_id, row.sha256)
        if key in first:
            continue
        first[key] = MailCv(
            candidate_id=row.parsed_candidate_id,
            sha256=row.sha256,
            attachment_id=row.id,
            m365_attachment_id=row.m365_attachment_id,
            storage_path=row.storage_path or "",
            filename=row.filename,
            content_type=row.content_type,
            received_at=row.received_at,
        )
    return first


async def _documents(db, candidate_ids: set[int]) -> list[Doc]:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, candidate_id, content_sha256,
                       CASE WHEN file_content IS NULL THEN NULL
                            ELSE encode(sha256(file_content), 'hex') END AS file_sha256,
                       octet_length(file_content) AS file_size,
                       external_id, external_source, document_kind::text AS kind,
                       is_primary, source_deleted_at IS NOT NULL AS deleted,
                       removed_at IS NOT NULL AS removed,
                       outdated_at IS NOT NULL AS outdated, uploaded_at, filename
                FROM candidate_documents
                WHERE external_source = 'm365'
                   OR candidate_id = ANY(:ids)
                   OR candidate_id IN (SELECT candidate_id FROM candidate_documents
                                       WHERE external_source = 'm365')
                """
            ),
            {"ids": sorted(candidate_ids)},
        )
    ).all()
    return [
        Doc(
            id=r.id,
            candidate_id=r.candidate_id,
            content_sha256=r.content_sha256,
            file_sha256=r.file_sha256,
            file_size=r.file_size,
            external_id=r.external_id,
            external_source=r.external_source,
            document_kind=r.kind,
            is_primary=r.is_primary,
            deleted=r.deleted,
            removed=r.removed,
            outdated=r.outdated,
            uploaded_at=r.uploaded_at,
            filename=r.filename or "",
        )
        for r in rows
    ]


async def _projection_sources(
    db, candidate_ids: set[int]
) -> dict[int, tuple[Optional[int], Optional[str]]]:
    """Osoba → (dokument, z którego odczytano profil; wskaźnik `cv_filename`)."""
    from app.models.candidate import Candidate

    rows = await db.execute(
        select(
            Candidate.id,
            Candidate.cv_extracted_data["cv_highlights"]["source_document_id"].astext,
            Candidate.cv_filename,
        ).where(Candidate.id.in_(sorted(candidate_ids)))
    )
    return {
        int(cid): (int(source) if source and source.isdigit() else None, pointer)
        for cid, source, pointer in rows.all()
    }


async def _quarantined_pairs(db, candidate_ids: set[int]) -> set[tuple[int, int]]:
    from app.models.candidate_source_identity_review import (
        CandidateSourceIdentityReview as Review,
    )

    rows = await db.execute(
        select(Review.candidate_id, Review.source_id).where(
            Review.candidate_id.in_(sorted(candidate_ids)),
            Review.source_kind == "document",
            Review.decision == "confirmed_mismatch",
            Review.override_at.is_(None),
        )
    )
    return {(int(c), int(s)) for c, s in rows.all()}


async def plan(
    db,
    *,
    exclude: Optional[set[int]] = None,
    candidate_ids: Optional[list[int]] = None,
) -> Plan:
    """Plan naprawy. ``candidate_ids`` zawęża bieg (testy na wspólnej bazie)."""
    from app.services.client_cv_upload import looks_like_client_cv
    from app.services.m365.attachment_handler import (
        STORAGE_ROOT,
        m365_document_external_id,
    )

    exclude = exclude or set()
    result = Plan()
    mail = await _mail_cvs(db, exclude, candidate_ids)
    by_sha: dict[str, list[MailCv]] = {}
    for item in mail.values():
        by_sha.setdefault(item.sha256, []).append(item)
        result.mail_cvs[item.attachment_id] = item

    involved = {cid for cid, _ in mail}
    docs = await _documents(db, involved)
    if candidate_ids is not None:
        allowed = set(candidate_ids)
        docs = [d for d in docs if d.candidate_id in allowed]
    docs = [d for d in docs if d.candidate_id not in exclude]
    # Stan po planie: dokument → osoba; które pliki osoba ma w profilu.
    owner_of: dict[int, int] = {d.id: d.candidate_id for d in docs}
    # Skrót z bajtów tam, gdzie je znamy: zapisany `content_sha256`
    # przepisywało przepięcie.
    sha_of: dict[int, Optional[str]] = {
        d.id: d.file_sha256 or d.content_sha256 for d in docs
    }
    gone: set[int] = {d.id for d in docs if d.deleted}
    holders: set[int] = set()
    owners: set[int] = set()

    def active_shas(candidate_id: int) -> set[str]:
        return {
            sha_of[doc_id]
            for doc_id, cid in owner_of.items()
            if cid == candidate_id and doc_id not in gone and sha_of[doc_id]
        }

    used_keys = {d.external_id for d in docs if d.external_source == "m365"}

    for doc in sorted(
        (d for d in docs if d.external_source == "m365"), key=lambda d: d.id
    ):
        if doc.file_sha256 is None:
            result.unverifiable_doc_ids.append(doc.id)
            continue
        if doc.file_sha256 == doc.content_sha256:
            source = mail.get((doc.candidate_id, doc.file_sha256))
            if source is not None and not (doc.external_id or "").startswith(
                NEW_KEY_PREFIX
            ):
                key = m365_document_external_id(source.m365_attachment_id)
                if key not in used_keys:
                    used_keys.add(key)
                    result.rekeys.append((doc.id, source.attachment_id))
            continue
        result.foreign.append(
            (
                doc.id,
                doc.candidate_id,
                doc.file_sha256,
                doc.filename,
                doc.file_size or 0,
            )
        )
        holders.add(doc.candidate_id)
        candidates = [
            item
            for item in by_sha.get(doc.file_sha256, [])
            if item.candidate_id != doc.candidate_id
            and doc.file_sha256 not in active_shas(item.candidate_id)
        ]
        target = candidates[0] if candidates else None
        if target is not None:
            key = m365_document_external_id(target.m365_attachment_id)
            if key in used_keys:
                target = None
        if target is None:
            result.removals.append((doc.id, doc.candidate_id))
            gone.add(doc.id)
        else:
            used_keys.add(key)
            result.returns.append(
                (doc.id, doc.candidate_id, target.candidate_id, target.attachment_id)
            )
            owners.add(target.candidate_id)
            owner_of[doc.id] = target.candidate_id
            if doc.deleted or doc.removed:
                # Ukrył go zły posiadacz (albo synchronizacja u niego) — u
                # właściciela plik wraca widoczny.
                result.restores.append(doc.id)
                gone.discard(doc.id)

    if result.foreign:
        sources = await _projection_sources(db, holders)
        for doc_id, holder, sha, name, _ in result.foreign:
            projected, pointer = sources.get(holder, (None, None))
            fed = projected == doc_id or (
                projected is None
                and next(d for d in docs if d.id == doc_id).is_primary
                and bool(pointer)
                and pointer.lower() == name.lower()
            )
            if fed:
                result.projections.append((holder, doc_id, sha))

    # Usunięcie liczy się u osoby, która usunęła — nie u właściciela, do
    # którego dokument wraca (F113).
    removed_by_person = {(d.candidate_id, sha_of[d.id]) for d in docs if d.removed}
    new_docs: dict[int, MailCv] = {}
    for (candidate_id, sha), item in sorted(mail.items()):
        if sha in active_shas(candidate_id):
            continue
        if (candidate_id, sha) in removed_by_person:
            result.skipped.append((candidate_id, item.attachment_id, "removed"))
            continue
        key = m365_document_external_id(item.m365_attachment_id)
        if key in used_keys:
            result.skipped.append((candidate_id, item.attachment_id, "key_taken"))
            continue
        content = await asyncio.to_thread(_read_file, STORAGE_ROOT / item.storage_path)
        if content is None:
            result.skipped.append((candidate_id, item.attachment_id, "file_missing"))
            continue
        if hashlib.sha256(content).hexdigest() != sha:
            result.skipped.append((candidate_id, item.attachment_id, "file_mismatch"))
            continue
        used_keys.add(key)
        result.creates.append((candidate_id, item.attachment_id))
        new_docs[item.attachment_id] = item

    # Główne CV po planie: zły posiadacz od nowa, reszta zachowuje swoje.
    reset = holders
    touched = holders | owners | {item.candidate_id for item in new_docs.values()}
    quarantined = await _quarantined_pairs(db, touched) if touched else set()
    doc_by_id = {d.id: d for d in docs}
    returned_from = {doc_id: att for doc_id, _, _, att in result.returns}

    def eligible(doc: Doc, candidate_id: int, *, choosing: bool = True) -> bool:
        # Wskazanego już głównego CV nie oceniamy po nazwie: „…B2B…” bywa
        # jedynym CV osoby (`cv_source.current_cv_filters`). Nazwa liczy się
        # tylko przy wyborze następcy.
        filename = doc.filename
        if doc.id in returned_from:
            filename = result.mail_cvs[returned_from[doc.id]].filename
        return (
            doc.id not in gone
            and (doc.document_kind == "cv" or doc.id in returned_from)
            and not doc.outdated
            and (candidate_id, doc.id) not in quarantined
            and not (choosing and looks_like_client_cv(filename))
        )

    for candidate_id in sorted(touched):
        mine = [
            doc_by_id[doc_id] for doc_id, cid in owner_of.items() if cid == candidate_id
        ]
        before = next(
            (
                d.id
                for d in docs
                if d.candidate_id == candidate_id
                and d.is_primary
                and not d.deleted
                and d.document_kind == "cv"
            ),
            None,
        )
        keep = (
            candidate_id not in reset
            and before is not None
            and owner_of.get(before) == candidate_id
            and eligible(doc_by_id[before], candidate_id, choosing=False)
        )
        if keep:
            continue
        options: list[tuple[datetime, int, Any]] = []
        floor = datetime.min.replace(tzinfo=timezone.utc)
        for doc in mine:
            if not eligible(doc, candidate_id):
                continue
            when = doc.uploaded_at
            if doc.id in returned_from:
                when = result.mail_cvs[returned_from[doc.id]].received_at
            options.append((when or floor, doc.id, doc.id))
        for item in new_docs.values():
            if item.candidate_id == candidate_id and not looks_like_client_cv(
                item.filename
            ):
                # Nowy dokument dostanie najwyższe id.
                options.append(
                    (
                        item.received_at or floor,
                        sys.maxsize,
                        f"att:{item.attachment_id}",
                    )
                )
        after = max(options)[2] if options else None
        if after != before:
            result.primaries[candidate_id] = (before, after)
    return result


async def client_exposure(db, items: Plan) -> list[dict[str, Any]]:
    """Kopie CV etapu z cudzym plikiem u złego posiadacza — tylko odczyt."""
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.recruitment_pipeline import CandidateStage

    found: list[dict[str, Any]] = []
    for _, holder, sha, _, _ in items.foreign:
        rows = (
            await db.execute(
                select(
                    CandidateStageCV.id,
                    CandidateStageCV.job_id,
                    CandidateStageCV.candidate_stage_id,
                    CandidateStageCV.branded_status,
                    CandidateStageCV.generated_document_id,
                    CandidateStage.stage,
                )
                .join(
                    CandidateStage,
                    CandidateStage.id == CandidateStageCV.candidate_stage_id,
                )
                .where(
                    CandidateStageCV.candidate_id == holder,
                    CandidateStageCV.original_cv_sha256 == sha,
                )
            )
        ).all()
        for row in rows:
            generated = await db.scalar(
                select(CvGeneratedDocument.id)
                .where(CvGeneratedDocument.stage_id == row.candidate_stage_id)
                .limit(1)
            )
            # Najdalszy etap tej osoby w tej rekrutacji.
            stages = (
                await db.scalars(
                    select(CandidateStage.stage).where(
                        CandidateStage.candidate_id == holder,
                        CandidateStage.job_id == row.job_id,
                    )
                )
            ).all()
            found.append(
                {
                    "candidate_id": holder,
                    "job_id": row.job_id,
                    "stage_cv_id": row.id,
                    "stage": getattr(row.stage, "value", str(row.stage)),
                    "job_stages": sorted({getattr(s, "value", str(s)) for s in stages}),
                    "branded_status": row.branded_status,
                    "generated_document": (row.generated_document_id or generated),
                }
            )
    return found


def summarize(items: Plan, exposure: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    for _, _, reason in items.skipped:
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "fingerprint": items.fingerprint(),
        "mail_cvs": len(items.mail_cvs),
        "mail_candidates": len({m.candidate_id for m in items.mail_cvs.values()}),
        "foreign_documents": len(items.foreign),
        "returned": [
            {
                "doc": d,
                "from": h,
                "to": o,
                "attachment": a,
                "restored": d in items.restores,
            }
            for d, h, o, a in items.returns
        ],
        "soft_removed": [{"doc": d, "from": h} for d, h in items.removals],
        "rekeyed_doc_ids": [d for d, _ in items.rekeys],
        "created": [{"candidate": c, "attachment": a} for c, a in items.creates],
        "primary_changes": [
            {"candidate": c, "before": b, "after": a}
            for c, (b, a) in sorted(items.primaries.items())
        ],
        "skipped": reasons,
        "skipped_items": [
            {"candidate": c, "attachment": a, "reason": r} for c, a, r in items.skipped
        ],
        "unverifiable_doc_ids": items.unverifiable_doc_ids,
        "projection_from_foreign": [
            {"candidate": c, "doc": d} for c, d, _ in items.projections
        ],
        "client_exposure": exposure,
    }


async def repair(db, items: Plan, *, now: Optional[datetime] = None) -> dict[str, int]:
    """Zapis planu w bieżącej transakcji (commit robi wołający)."""
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services.candidate_identity_quarantine import (
        clear_foreign_cv_projection,
    )
    from app.services.candidate_stage_cv_service import (
        restore_stage_copies_after_quarantine,
    )
    from app.services.m365.attachment_handler import (
        STORAGE_ROOT,
        m365_document_external_id,
    )

    now = now or datetime.now(timezone.utc)
    stats = {
        "returned": 0,
        "soft_removed": 0,
        "rekeyed": 0,
        "created": 0,
        "primary_changed": 0,
        "pointer_detached": 0,
        "stage_copies": 0,
        "restored": 0,
        "projections_cleared": 0,
    }
    touched = (
        {h for _, h, _, _ in items.returns}
        | {o for _, _, o, _ in items.returns}
        | {h for _, h in items.removals}
        | {c for c, _ in items.creates}
        | set(items.primaries)
    )
    history: dict[int, dict[str, list]] = {
        cid: {"returned_doc_ids": [], "removed_doc_ids": [], "created_doc_ids": []}
        for cid in touched
    }
    # Częściowy UNIQUE na aktywne główne CV: najpierw zdjęcie flagi tam, gdzie
    # główne CV się zmienia albo dokument zmienia osobę.
    moving = [d for d, _, _, _ in items.returns] + [d for d, _ in items.removals]
    if items.primaries:
        await db.execute(
            update(CandidateDocument)
            .where(
                CandidateDocument.candidate_id.in_(sorted(items.primaries)),
                CandidateDocument.document_kind == CandidateDocumentKind.cv,
                CandidateDocument.is_primary.is_(True),
            )
            .values(is_primary=False)
            .execution_options(synchronize_session=False)
        )
    if moving:
        await db.execute(
            update(CandidateDocument)
            .where(CandidateDocument.id.in_(moving))
            .values(is_primary=False)
            .execution_options(synchronize_session=False)
        )
    await db.flush()

    foreign: dict[int, list[tuple[str, str]]] = {}
    file_of: dict[int, tuple[str, int]] = {}
    for doc_id, holder, sha, name, size in items.foreign:
        foreign.setdefault(holder, []).append((sha, name))
        file_of[doc_id] = (sha, size)
    for doc_id, holder in items.removals:
        doc = await db.get(CandidateDocument, doc_id, populate_existing=True)
        doc.content_sha256, doc.size_bytes = file_of[doc_id]
        doc.source_deleted_at = doc.source_deleted_at or now
        doc.removed_at = doc.removed_at or now
        history[holder]["removed_doc_ids"].append(doc_id)
        stats["soft_removed"] += 1
    restores = set(items.restores)
    for doc_id, holder, owner, attachment_id in items.returns:
        source = items.mail_cvs[attachment_id]
        doc = await db.get(CandidateDocument, doc_id, populate_existing=True)
        doc.candidate_id = owner
        doc.content_sha256 = source.sha256
        doc.external_id = m365_document_external_id(source.m365_attachment_id)
        doc.filename = source.filename
        doc.content_type = source.content_type
        doc.size_bytes = file_of[doc_id][1]
        doc.uploaded_at = source.received_at
        doc.uploaded_by = None
        doc.document_kind = CandidateDocumentKind.cv
        if doc_id in restores:
            doc.source_deleted_at = None
            doc.removed_at = None
            doc.removed_by = None
            stats["restored"] += 1
        history[holder]["removed_doc_ids"].append(doc_id)
        history[owner]["returned_doc_ids"].append(doc_id)
        stats["returned"] += 1
    await db.flush()
    for doc_id, attachment_id in items.rekeys:
        doc = await db.get(CandidateDocument, doc_id)
        doc.external_id = m365_document_external_id(
            items.mail_cvs[attachment_id].m365_attachment_id
        )
        stats["rekeyed"] += 1

    created: dict[int, CandidateDocument] = {}
    for candidate_id, attachment_id in items.creates:
        source = items.mail_cvs[attachment_id]
        content = await asyncio.to_thread(
            _read_file, STORAGE_ROOT / source.storage_path
        )
        if content is None or hashlib.sha256(content).hexdigest() != source.sha256:
            raise RuntimeError(f"plik załącznika {attachment_id} zmienił się od planu")
        doc = CandidateDocument(
            candidate_id=candidate_id,
            filename=source.filename,
            file_content=content,
            content_type=source.content_type,
            size_bytes=len(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            uploaded_at=source.received_at or now,
            external_source="m365",
            external_id=m365_document_external_id(source.m365_attachment_id),
            content_sha256=source.sha256,
        )
        db.add(doc)
        await db.flush()
        created[attachment_id] = doc
        history[candidate_id]["created_doc_ids"].append(doc.id)
        stats["created"] += 1

    primary_after: dict[int, Optional[CandidateDocument]] = {}
    for candidate_id, (_, after) in sorted(items.primaries.items()):
        if after is None:
            primary_after[candidate_id] = None
        elif isinstance(after, str):
            primary_after[candidate_id] = created[int(after.split(":", 1)[1])]
        else:
            primary_after[candidate_id] = await db.get(CandidateDocument, after)
        doc = primary_after[candidate_id]
        if doc is not None:
            doc.is_primary = True
        stats["primary_changed"] += 1
    await db.flush()

    for candidate_id in sorted(touched):
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id).with_for_update()
        )
        if candidate is None:
            continue
        # Fakty z cudzego dokumentu przed wskaźnikiem: czyszczenie nie rusza
        # `cv_filename`, prowadzi go niżej ten skrypt (F114).
        projection_cleared = False
        for holder, doc_id, sha in items.projections:
            if holder != candidate_id:
                continue
            await clear_foreign_cv_projection(
                db, candidate_id=candidate_id, document_id=doc_id, document_hash=sha
            )
            projection_cleared = True
            stats["projections_cleared"] += 1
        # Najpierw cudzy plik we wskaźniku (nazwa albo bajty), potem nazwa
        # nowego głównego CV — „CV.pdf” bywa nazwą obu plików.
        detached = False
        pointer_bytes_sha = (
            hashlib.sha256(candidate.cv_file_content).hexdigest()
            if candidate.cv_file_content is not None
            else None
        )
        for sha, name in foreign.get(candidate_id, []):
            if candidate.cv_filename and candidate.cv_filename.lower() == name.lower():
                candidate.cv_filename = None
                detached = True
            if pointer_bytes_sha == sha:
                candidate.cv_file_content = None
                detached = True
        stats["pointer_detached"] += detached
        if candidate_id in primary_after:
            new_primary = primary_after[candidate_id]
            candidate.cv_filename = new_primary.filename if new_primary else None
        await db.flush()
        for sha, _ in foreign.get(candidate_id, []):
            stats["stage_copies"] += await restore_stage_copies_after_quarantine(
                db,
                candidate=candidate,
                quarantined_sha256=sha,
                source="m365_document_repair",
                action="snapshot_m365_document_repaired",
            )
        before, after = items.primaries.get(candidate_id, (None, None))
        doc_after = primary_after.get(candidate_id)
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate_id,
                action="m365_documents_repaired",
                details={
                    **history[candidate_id],
                    "primary_before": before,
                    "primary_after": (doc_after.id if doc_after is not None else None)
                    if candidate_id in items.primaries
                    else before,
                    "projection_cleared": projection_cleared,
                },
            )
        )
    await db.flush()
    return stats


async def _receipt_exists(db) -> bool:
    return bool(
        await db.scalar(
            text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
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


async def main(
    argv: Optional[list[str]] = None,
    *,
    candidate_ids: Optional[list[int]] = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--exclude",
        type=int,
        action="append",
        default=[],
        help="kandydat pomijany w całości (np. profil z cudzymi mailami)",
    )
    parser.add_argument(
        "--expected", help="odcisk planu z próby na sucho (wymagany z --apply)"
    )
    parser.add_argument(
        "--reread",
        type=int,
        action="append",
        default=[],
        help="po zapisie odczyt AI profilu z nowego głównego CV (np. profil "
        "wyczyszczony przez kwarantannę po cudzym pliku)",
    )
    args = parser.parse_args(argv)
    exclude = set(args.exclude)

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    async with AsyncSessionLocal() as db:
        if args.apply:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": RECEIPT_KEY},
            )
        items = await plan(db, exclude=exclude, candidate_ids=candidate_ids)
        report = summarize(items, await client_exposure(db, items))
        report["excluded"] = sorted(exclude)
        print(json.dumps({"plan": report}, ensure_ascii=False, default=str))
        if not args.apply:
            print(
                "Na sucho — nic nie zmieniono. Zapis: --apply --expected "
                f"{report['fingerprint']}"
                + "".join(f" --exclude {cid}" for cid in sorted(exclude))
            )
            return 0
        if await _receipt_exists(db):
            print(f"Paragon {RECEIPT_KEY} już jest — przerywam.", file=sys.stderr)
            return 2
        if args.expected != report["fingerprint"]:
            print(
                f"Plan różni się od próby: odcisk {report['fingerprint']}, "
                f"oczekiwano {args.expected} — przerywam.",
                file=sys.stderr,
            )
            return 2
        stats = await repair(db, items)
        receipt = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint": report["fingerprint"],
            "excluded": sorted(exclude),
            "foreign_documents": report["foreign_documents"],
            "skipped": report["skipped"],
            **stats,
        }
        await _write_receipt(db, receipt)
        await db.commit()
        new_primary = {
            cid: doc_id
            for cid, doc_id in (
                await db.execute(
                    select(CandidateDocument.candidate_id, CandidateDocument.id).where(
                        CandidateDocument.candidate_id.in_(args.reread),
                        CandidateDocument.document_kind == CandidateDocumentKind.cv,
                        CandidateDocument.is_primary.is_(True),
                        CandidateDocument.source_deleted_at.is_(None),
                    )
                )
            ).all()
        }
    print(json.dumps(receipt, ensure_ascii=False))
    if args.reread:
        from app.api.candidates import _enrich_candidate_from_document_task

        for cid in args.reread:
            if cid not in items.primaries or cid not in new_primary:
                print(f"Odczyt {cid} pominięty — bez nowego głównego CV.")
                continue
            await _enrich_candidate_from_document_task(
                cid, new_primary[cid], trigger="cv_repair"
            )
            print(f"Odczyt profilu {cid} z dokumentu {new_primary[cid]}.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
