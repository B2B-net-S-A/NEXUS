"""Dokumenty osoby — e-teczka przy kartotece (etap 5, E4).

Kto widzi (Kadry i admin zawsze, reszta według znaczników dokumentu):

* osoba — swoje dokumenty z ``visible_to_person``,
* Płace (uprawnienie „Płace”) — dokumenty z ``visible_to_payroll``,
* recepcja (uprawnienie „Sprzęt”) — dokumenty z ``visible_to_equipment``
  i protokoły sprzętu osoby,
* przełożony — NIC z e-teczki (ani listy, ani plików); kartoteka pokazuje mu
  tylko to, co już pokazywała.

Kto zmienia: wyłącznie Kadry i admin (wgranie, tytuł, „ważny do”, krąg,
usunięcie pomyłki z powodem). Dokument z generatora umów (E5) wchodzi przez
``attach_generated`` i nie da się go usunąć ręcznie — zostaje do końca
retencji (``documents_retention``).

Protokoły sprzętu nie są kopiowane: lista czyta ``equipment_protocols``
posiadacza-konta (``documents_protocols``).

Funkcje nie commitują — robi to trasa (albo wołający, np. podpis umowy w E5).
Pliki do skasowania po usunięciu dokumentu wracają do wołającego i znikają
z dysku dopiero po commicie (``documents_store.delete``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.upload_filename import fit_filename_column
from app.models.hr_document import HrDocument
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import audit, documents_store
from app.services.hr.documents_rules import DEFAULT_AUDIENCE
from app.services.hr_documents_schema import (
    DOCUMENT_KINDS,
    DOCUMENT_MIME_TYPES,
    DOCUMENT_PURPOSES,
    GENERATED_SOURCES,
    NOTE_MAX_LENGTH,
    SOURCE_REF_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

#: Źródło dokumentów z generatora umów z ludźmi (E5) — stała dla wołających.
SOURCE_AGREEMENT = "agreement"
STUDENT_STATUS = "student_status"


class HrDocumentError(ValueError):
    """Błąd z komunikatem dla użytkownika (po polsku) i kodem HTTP."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


NOT_FOUND = "Nie ma takiego dokumentu."


# ── Dostęp ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Viewer:
    user_id: int
    manage: bool
    payroll: bool
    equipment: bool


def viewer_of(user: User) -> Viewer:
    return Viewer(
        user_id=user.id,
        manage=user.has_role(UserRole.admin)
        or has_permission(user, ProductAction.people_admin),
        payroll=has_permission(user, ProductAction.payroll),
        equipment=has_permission(user, ProductAction.equipment),
    )


def can_read_person(viewer: Viewer, user_id: int) -> bool:
    """Czy e-teczka tej osoby w ogóle istnieje dla czytającego (inaczej 404)."""

    return (
        viewer.manage or viewer.payroll or viewer.equipment or viewer.user_id == user_id
    )


def can_see(viewer: Viewer, document: HrDocument) -> bool:
    if viewer.manage:
        return True
    if document.deleted_at is not None:
        return False
    return (
        (viewer.user_id == document.user_id and document.visible_to_person)
        or (viewer.payroll and document.visible_to_payroll)
        or (viewer.equipment and document.visible_to_equipment)
    )


def sees_protocols(viewer: Viewer, user_id: int) -> bool:
    return viewer.manage or viewer.equipment or viewer.user_id == user_id


# ── Walidacja ─────────────────────────────────────────────────────────────────


def _clean_title(title: Optional[str]) -> str:
    clean = " ".join((title or "").split())
    if not clean:
        raise HrDocumentError("Podaj tytuł dokumentu.")
    if len(clean) > TITLE_MAX_LENGTH:
        raise HrDocumentError(f"Tytuł może mieć najwyżej {TITLE_MAX_LENGTH} znaków.")
    return clean


def _check_kind(kind: str) -> str:
    if kind not in DOCUMENT_KINDS:
        raise HrDocumentError("Nieznany rodzaj dokumentu.")
    return kind


def _check_purpose(
    purpose: Optional[str], *, kind: str, valid_until: Optional[date]
) -> Optional[str]:
    if purpose is None:
        return None
    if purpose not in DOCUMENT_PURPOSES:
        raise HrDocumentError("Nieznane przeznaczenie dokumentu.")
    if kind != "statement":
        raise HrDocumentError(
            "Status ucznia lub studenta potwierdza oświadczenie — wybierz rodzaj "
            "„oświadczenie”."
        )
    if valid_until is None:
        raise HrDocumentError(
            "Podaj „ważny do” oświadczenia — od tej daty Płace naliczą składki."
        )
    return purpose


def _check_file(content: bytes) -> tuple[str, str]:
    try:
        return documents_store.check(content)
    except documents_store.FileRejected as exc:
        raise HrDocumentError(str(exc)) from None


async def _ensure_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HrDocumentError("Nie ma takiej osoby.", 404)
    return user


# ── Dokument z generatora (interfejs dla E5) ──────────────────────────────────


async def attach_generated(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    title: str,
    content: bytes,
    mime: str,
    source: str,
    source_ref: str,
    valid_until: date | None,
    actor_id: int | None,
) -> HrDocument:
    """Dokument z generatora (np. podpisana umowa z E5) w e-teczce osoby.

    * Idempotentny po (``source``, ``source_ref``): kolejne wołanie zwraca
      istniejący dokument bez nowego pliku (także w wyścigu dwóch wołań —
      zapis idzie w SAVEPOINT, konflikt indeksu = odczyt istniejącego).
    * ``source`` z ``GENERATED_SOURCES`` (dziś ``SOURCE_AGREEMENT``),
      ``source_ref`` — stały odnośnik do rekordu źródła (np. ``"hr_agreement:15"``).
    * ``mime`` musi zgadzać się z treścią (PDF, DOCX, JPG, PNG).
    * Krąg: osoba i Płace (umowa to podstawa rozliczenia); recepcja nie.
    * Bez commita — działa w transakcji wołającego (podpis umowy).
    Błędy danych wejściowych: ``HrDocumentError`` (komunikat po polsku).
    """

    if source not in GENERATED_SOURCES:
        raise HrDocumentError("Nieznane źródło dokumentu z generatora.")
    ref = (source_ref or "").strip()
    if not ref or len(ref) > SOURCE_REF_MAX_LENGTH:
        raise HrDocumentError("Dokument z generatora wymaga odnośnika do źródła.")
    existing = await _by_source(db, source, ref)
    if existing is not None:
        return existing
    _check_kind(kind)
    clean_title = _clean_title(title)
    if mime not in DOCUMENT_MIME_TYPES:
        raise HrDocumentError("Nieobsługiwany typ pliku dokumentu.")
    sniffed, digest = _check_file(content)
    if sniffed != mime:
        raise HrDocumentError("Treść pliku nie zgadza się z podanym typem.")
    await _ensure_user(db, user_id)
    path = documents_store.save(user_id, content, mime=mime, digest=digest)
    document = HrDocument(
        user_id=user_id,
        kind=kind,
        purpose=None,
        title=clean_title,
        source=source,
        source_ref=ref,
        file_path=path,
        file_name=None,
        mime=mime,
        size_bytes=len(content),
        sha256=digest,
        valid_until=valid_until,
        visible_to_person=True,
        visible_to_payroll=True,
        visible_to_equipment=False,
        added_by=actor_id,
    )
    try:
        async with db.begin_nested():
            db.add(document)
            await db.flush()
    except IntegrityError:
        existing = await _by_source(db, source, ref)
        if existing is None:
            raise
        return existing
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="document_attached",
        details={"kind": kind, "source": source, "source_ref": ref},
    )
    return document


async def _by_source(db: AsyncSession, source: str, ref: str) -> Optional[HrDocument]:
    return await db.scalar(
        select(HrDocument).where(
            HrDocument.source == source, HrDocument.source_ref == ref
        )
    )


# ── Wgranie i zmiany (Kadry) ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Audience:
    person: bool
    payroll: bool
    equipment: bool


def default_audience(kind: str) -> Audience:
    person, payroll, equipment = DEFAULT_AUDIENCE[_check_kind(kind)]
    return Audience(person=person, payroll=payroll, equipment=equipment)


async def upload(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    title: str,
    content: bytes,
    file_name: Optional[str],
    valid_until: Optional[date],
    purpose: Optional[str],
    audience: Optional[Audience],
    actor: User,
) -> tuple[HrDocument, Optional[dict[str, Any]]]:
    """Dokument wgrany przez Kadry; zwraca (dokument, wynik zasilenia kartoteki).

    Drugi raz ten sam plik tej samej osobie = 409. Oświadczenie o statusie
    ucznia/studenta zasila kartotekę (``documents_student.sync``).
    """

    from app.services.hr import documents_student, people

    _check_kind(kind)
    clean_title = _clean_title(title)
    purpose = _check_purpose(purpose, kind=kind, valid_until=valid_until)
    if await people.profile_of(db, user_id) is None:
        raise HrDocumentError("Nie ma takiej kartoteki.", 404)
    mime, digest = _check_file(content)
    if await _live_upload_exists(db, user_id, digest):
        raise HrDocumentError("Ten plik jest już w dokumentach tej osoby.", 409)
    chosen = audience or default_audience(kind)
    previous_until = (
        await documents_student.latest_until(db, user_id) if purpose else None
    )
    path = documents_store.save(user_id, content, mime=mime, digest=digest)
    document = HrDocument(
        user_id=user_id,
        kind=kind,
        purpose=purpose,
        title=clean_title,
        source="upload",
        source_ref=None,
        file_path=path,
        file_name=clean_file_name(file_name),
        mime=mime,
        size_bytes=len(content),
        sha256=digest,
        valid_until=valid_until,
        visible_to_person=chosen.person,
        visible_to_payroll=chosen.payroll,
        visible_to_equipment=chosen.equipment,
        added_by=actor.id,
    )
    try:
        async with db.begin_nested():
            db.add(document)
            await db.flush()
    except IntegrityError:
        raise HrDocumentError(
            "Ten plik jest już w dokumentach tej osoby.", 409
        ) from None
    sync = None
    if purpose == STUDENT_STATUS and valid_until is not None:
        sync = await documents_student.sync(
            db,
            user_id=user_id,
            until=valid_until,
            came_from=previous_until,
            actor=actor,
        )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="document_uploaded",
        details={
            "kind": kind,
            "purpose": purpose,
            "audience": _audience_details(document),
            **({"profile_sync": sync["status"]} if sync else {}),
        },
    )
    return document, sync


def clean_file_name(file_name: Optional[str]) -> Optional[str]:
    name = (file_name or "").replace("\x00", "").strip()
    if not name:
        return None
    return fit_filename_column(name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])


def _audience_details(document: HrDocument) -> list[str]:
    return [
        label
        for label, flag in (
            ("person", document.visible_to_person),
            ("payroll", document.visible_to_payroll),
            ("equipment", document.visible_to_equipment),
        )
        if flag
    ]


async def _live_upload_exists(db: AsyncSession, user_id: int, digest: str) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    HrDocument.user_id == user_id,
                    HrDocument.sha256 == digest,
                    HrDocument.source == "upload",
                    HrDocument.deleted_at.is_(None),
                )
            )
        )
    )


_UNSET: Any = object()


async def update(
    db: AsyncSession,
    document: HrDocument,
    *,
    actor: User,
    title: Any = _UNSET,
    valid_until: Any = _UNSET,
    audience: Optional[Audience] = None,
) -> tuple[HrDocument, Optional[dict[str, Any]]]:
    """Tytuł, „ważny do” i krąg (Kadry). Rodzaju i pliku się nie zmienia."""

    from app.services.hr import documents_student

    if document.deleted_at is not None:
        raise HrDocumentError("Dokument został usunięty — nie da się go zmienić.", 409)
    changed: list[str] = []
    previous_until = document.valid_until
    if title is not _UNSET:
        clean = _clean_title(title)
        if clean != document.title:
            document.title = clean
            changed.append("title")
    if valid_until is not _UNSET and valid_until != document.valid_until:
        if document.purpose == STUDENT_STATUS and valid_until is None:
            raise HrDocumentError(
                "Oświadczenie o statusie ucznia lub studenta musi mieć „ważny do”."
            )
        document.valid_until = valid_until
        changed.append("valid_until")
    if audience is not None:
        if document.source != "upload" and not audience.person:
            raise HrDocumentError(
                "Umowa z generatora zostaje widoczna dla osoby, której dotyczy."
            )
        for field, value in (
            ("visible_to_person", audience.person),
            ("visible_to_payroll", audience.payroll),
            ("visible_to_equipment", audience.equipment),
        ):
            if getattr(document, field) != value:
                setattr(document, field, value)
                changed.append(field)
    sync = None
    if not changed:
        return document, None
    document.updated_by = actor.id
    await db.flush()
    if (
        "valid_until" in changed
        and document.purpose == STUDENT_STATUS
        and document.valid_until is not None
        # Starsze oświadczenie nie przesuwa daty, którą wpisało nowsze.
        and await documents_student.latest_document_id(db, document.user_id)
        == document.id
    ):
        sync = await documents_student.sync(
            db,
            user_id=document.user_id,
            until=document.valid_until,
            came_from=previous_until,
            actor=actor,
        )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=document.user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="document_updated",
        details={
            "fields": changed,
            **({"profile_sync": sync["status"]} if sync else {}),
        },
    )
    return document, sync


async def remove(
    db: AsyncSession, document: HrDocument, *, note: Optional[str], actor: User
) -> Optional[str]:
    """Usuwa pomyłkowo wgrany dokument (z powodem); zwraca plik do skasowania.

    Dokument z generatora umów jest dowodem podpisanej umowy — 409; znika
    dopiero po terminie przechowywania (lista retencji).
    """

    if document.deleted_at is not None:
        raise HrDocumentError("Ten dokument jest już usunięty.", 409)
    if document.source != "upload":
        raise HrDocumentError(
            "Umowy z generatora nie usuwa się ręcznie — zostaje do końca okresu "
            "przechowywania.",
            409,
        )
    clean = " ".join((note or "").split())
    if not clean:
        raise HrDocumentError("Napisz, dlaczego usuwasz dokument.")
    if len(clean) > NOTE_MAX_LENGTH:
        raise HrDocumentError(f"Powód może mieć najwyżej {NOTE_MAX_LENGTH} znaków.")
    orphan = await mark_deleted(
        db, document, reason="mistake", note=clean, actor_id=actor.id
    )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=document.user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="document_removed",
        details={"reason": "mistake", "kind": document.kind},
    )
    return orphan


async def mark_deleted(
    db: AsyncSession,
    document: HrDocument,
    *,
    reason: str,
    note: Optional[str],
    actor_id: int,
) -> Optional[str]:
    """Zdejmuje plik z dokumentu (wiersz zostaje jako ślad); zwraca plik do skasowania.

    Plik o tej samej treści może należeć do innego żywego dokumentu tej osoby
    (np. wgrana kopia umowy z generatora) — wtedy zostaje na dysku.
    """

    path = document.file_path
    document.deleted_at = datetime.now(timezone.utc)
    document.deleted_by = actor_id
    document.deletion_reason = reason
    document.deletion_note = note
    document.file_path = None
    await db.flush()
    if path is None:
        return None
    shared = await db.scalar(
        select(
            exists().where(
                HrDocument.file_path == path,
                HrDocument.id != document.id,
                HrDocument.deleted_at.is_(None),
            )
        )
    )
    return None if shared else path


def delete_files(paths: Iterable[Optional[str]]) -> None:
    """Kasuje pliki PO commicie (błąd dysku nie cofa usunięcia w bazie)."""

    for path in paths:
        if not path:
            continue
        try:
            documents_store.delete(path)
        except OSError as exc:
            logger.error(
                "[hr_documents] nie udało się skasować pliku (%s)", type(exc).__name__
            )


# ── Odczyt ────────────────────────────────────────────────────────────────────


async def get_document(db: AsyncSession, document_id: int) -> HrDocument:
    document = await db.get(HrDocument, document_id)
    if document is None:
        raise HrDocumentError(NOT_FOUND, 404)
    return document


async def readable_document(
    db: AsyncSession, document_id: int, viewer: Viewer
) -> HrDocument:
    """Dokument, który czytający może zobaczyć; inaczej 404 (bez zdradzania istnienia)."""

    document = await get_document(db, document_id)
    if not can_see(viewer, document):
        raise HrDocumentError(NOT_FOUND, 404)
    return document


def file_of(document: HrDocument) -> Path:
    if document.deleted_at is not None or not document.file_path:
        raise HrDocumentError("Plik tego dokumentu został usunięty.", 404)
    try:
        return documents_store.path_for(document.file_path)
    except FileNotFoundError:
        raise HrDocumentError("Brak pliku tego dokumentu w magazynie.", 404) from None


def download_name(document: HrDocument) -> str:
    if document.file_name:
        return document.file_name
    extension = documents_store.EXTENSIONS.get(document.mime, "bin")
    return f"{document.title}.{extension}"


async def documents_of(
    db: AsyncSession, user_id: int, viewer: Viewer
) -> list[HrDocument]:
    rows = (
        await db.scalars(
            select(HrDocument)
            .where(HrDocument.user_id == user_id)
            .order_by(HrDocument.created_at.desc(), HrDocument.id.desc())
        )
    ).all()
    return [row for row in rows if can_see(viewer, row)]


async def names_of(db: AsyncSession, ids: Iterable[Optional[int]]) -> dict[int, str]:
    wanted = {value for value in ids if value}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return dict(rows.all())


def payload(
    document: HrDocument, viewer: Viewer, names: dict[int, str]
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": document.id,
        "user_id": document.user_id,
        "kind": document.kind,
        "purpose": document.purpose,
        "title": document.title,
        "source": document.source,
        "source_ref": document.source_ref,
        "leave_request_id": str(document.leave_request_id)
        if document.leave_request_id
        else None,
        "file_name": document.file_name,
        "mime": document.mime,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "valid_until": document.valid_until,
        "audience": {
            "person": document.visible_to_person,
            "payroll": document.visible_to_payroll,
            "equipment": document.visible_to_equipment,
        },
        "added_by_name": names.get(document.added_by) if document.added_by else None,
        "created_at": document.created_at,
        "deleted": document.deleted_at is not None,
    }
    if viewer.manage:
        out["deleted_at"] = document.deleted_at
        out["deletion_reason"] = document.deletion_reason
        out["deleted_by_name"] = (
            names.get(document.deleted_by) if document.deleted_by else None
        )
    return out


__all__ = [
    "Audience",
    "HrDocumentError",
    "SOURCE_AGREEMENT",
    "STUDENT_STATUS",
    "Viewer",
    "attach_generated",
    "can_read_person",
    "can_see",
    "default_audience",
    "delete_files",
    "documents_of",
    "file_of",
    "get_document",
    "mark_deleted",
    "payload",
    "readable_document",
    "remove",
    "sees_protocols",
    "update",
    "upload",
    "viewer_of",
]
