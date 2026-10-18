"""Wzory umów z ludźmi (etap 5, E5) — pliki DOCX od Kadr, z wersjami.

Treści prawnej umów NEXUS nie pisze: Kadry wgrywają własny wzór (B2B biura,
zlecenie, UoP, aneks) z polami ``{{ … }}`` z listy ``FIELDS``. Plik przychodzi
od człowieka, więc przechodzi tę samą kontrolę co wzory protokołów sprzętu
(``services/equipment/protocol_template``): paczka bez makr, osadzonych
obiektów i łączy zewnętrznych, limit rozmiaru, wypełnianie WYŁĄCZNIE
w sandboksie jinja2 z listą dozwolonych węzłów (bez pętli — umowa ich nie
potrzebuje) i ``StrictUndefined``, próbne wypełnienie fikcyjną umową przed
zapisem. Sandboksu się tu nie kopiuje — moduł korzysta z tamtego.

Wzoru nie kasuje się ani nie podmienia: nowy plik to nowa wersja (1, 2, 3…),
a umowa pamięta wersję, z której powstała. Wycofany wzór nie trafia do nowych
umów; umowy z niego dalej się z niego odtwarzają.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from jinja2 import TemplateError
from jinja2.exceptions import SecurityError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_agreement import (
    HrAgreement,
    HrAgreementTemplate,
    HrAgreementTemplateVersion,
)
from app.models.user import User
from app.services.equipment import protocol_template as sandbox
from app.services.equipment.protocol_template import TemplateRejected
from app.services.hr import audit
from app.services.hr.agreements_errors import (
    AgreementConflict,
    AgreementError,
    AgreementNotFound,
)
from app.services.hr_agreements_schema import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    TEMPLATE_KINDS,
    TEMPLATE_MAX_BYTES,
)

DOCX_MEDIA_TYPE = sandbox.DOCX_MEDIA_TYPE

KIND_LABELS: dict[str, str] = {
    "b2b": "Umowa B2B",
    "zlecenie": "Umowa zlecenia",
    "uop": "Umowa o pracę",
    "annex": "Aneks",
}

#: Pola umowy (kontekst ``agreements_document.context_for``) z opisem dla Kadr.
#: Bez PESEL-u, numeru dowodu i adresu — tożsamość potwierdza Autenti, a dane
#: wpisane w treść wzoru zostają w pliku Kadr, nie w NEXUSIE.
FIELDS: dict[str, str] = {
    "person_name": "imię i nazwisko osoby",
    "employment_form": "forma współpracy (np. „umowa zlecenia”)",
    "rate": "stawka za godzinę (np. 32,00)",
    "rate_words": "stawka słownie, tylko w złotych (np. trzydzieści dwa złote 00/100)",
    "currency": "waluta stawki (PLN, EUR, USD)",
    "rate_basis": "„netto” na B2B, „brutto” na zleceniu i umowie o pracę",
    "start_date": "od kiedy (dd.mm.rrrr)",
    "end_date": "do kiedy (dd.mm.rrrr) — puste przy umowie bez daty końca",
    "indefinite": "umowa bez daty końca — do warunku {% if indefinite %}…{% endif %}",
    "hours_confirmation": (
        "potwierdzanie godzin (art. 8b) — do warunku {% if hours_confirmation %}"
    ),
    "payout_day": "dzień wypłaty w następnym miesiącu (np. 10)",
    "coordinator_name": "koordynator, który potwierdza godziny",
    "agreement_date": "data zawarcia (dd.mm.rrrr)",
    "base_agreement_date": "w aneksie: data zmienianej umowy (dd.mm.rrrr)",
}
#: Bez tych pól nie wiadomo, kogo, od kiedy i za ile dotyczy umowa.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    kind: ("person_name", "rate", "start_date") for kind in TEMPLATE_KINDS
}


def sample_context(kind: str) -> dict[str, Any]:
    """Fikcyjna umowa do próbnego wypełnienia (te same pola co prawdziwa)."""

    return {
        "person_name": "Anna Przykładowa",
        "employment_form": {
            "b2b": "umowa B2B",
            "zlecenie": "umowa zlecenia",
            "uop": "umowa o pracę",
            "annex": "umowa zlecenia",
        }[kind],
        "rate": "32,00",
        "rate_words": "trzydzieści dwa złote 00/100",
        "currency": "PLN",
        "rate_basis": "netto" if kind == "b2b" else "brutto",
        "start_date": "01.11.2026",
        "end_date": "",
        "indefinite": True,
        "hours_confirmation": True,
        "payout_day": 10,
        "coordinator_name": "Marta Przełożona",
        "agreement_date": "25.10.2026",
        "base_agreement_date": "01.03.2026" if kind == "annex" else "",
    }


def field_rows() -> Iterable[dict[str, str]]:
    for key, label in FIELDS.items():
        yield {"field": key, "label": label}


def _short(error: Exception) -> str:
    text_value = " ".join(str(error).split())
    return text_value[:200] or error.__class__.__name__


def check_upload(filename: str, content: bytes, kind: str) -> list[str]:
    """Walidacja wgranego wzoru; zwraca użyte pola albo ``TemplateRejected``."""

    if kind not in TEMPLATE_KINDS:
        raise TemplateRejected(
            "Wybierz rodzaj wzoru: B2B, zlecenie, umowa o pracę albo aneks."
        )
    if not (filename or "").lower().endswith(".docx"):
        raise TemplateRejected("Wgraj plik Word w formacie .docx.")
    if not content or len(content) > TEMPLATE_MAX_BYTES:
        raise TemplateRejected("Plik jest pusty albo większy niż 2 MB.")
    # Ta sama kontrola paczki co wzory protokołów (makra, osadzone obiekty, łącza).
    sandbox._check_package(content)
    try:
        fields = sandbox.template_fields(content)
    except TemplateRejected as exc:
        if "Pętla" in str(exc):
            # Zdanie sandboksu mówi o pozycjach protokołu — umowa pętli nie ma.
            raise TemplateRejected(
                "Pętla nie jest dostępna we wzorze umowy — wstaw same pola i warunki."
            ) from exc
        raise
    unknown = sorted(fields - set(FIELDS))
    if unknown:
        raise TemplateRejected(
            "Wzór ma pola, których umowa nie zna: "
            + ", ".join(unknown)
            + ". Dostępne pola: "
            + ", ".join(FIELDS)
            + "."
        )
    missing = [field for field in REQUIRED_FIELDS[kind] if field not in fields]
    if missing:
        raise TemplateRejected(
            "Wzór nie ma wymaganych pól: " + ", ".join(missing) + "."
        )
    try:
        sandbox.render_uploaded(content, sample_context(kind))
    except SecurityError as exc:
        raise TemplateRejected(
            "Wzór próbuje sięgnąć poza dane umowy — takiego wzoru nie da się użyć."
        ) from exc
    except TemplateError as exc:
        raise TemplateRejected(f"Wzór nie daje się wypełnić: {_short(exc)}") from exc
    except Exception as exc:
        raise TemplateRejected("Wzór nie daje się wypełnić.") from exc
    return sorted(fields)


def render(content: bytes, context: dict[str, Any]) -> bytes:
    """Wzór z pliku wypełniony w sandboksie; błąd = ``AgreementError`` dla Kadr."""

    try:
        return sandbox.render_uploaded(content, context)
    except (SecurityError, TemplateError) as exc:
        raise AgreementError(
            "Tego wzoru nie da się wypełnić — wgraj poprawioną wersję wzoru."
        ) from exc


def sample_document(content: bytes, kind: str) -> bytes:
    """Wzór wypełniony fikcyjną umową — podgląd dla Kadr."""

    return render(content, sample_context(kind))


# ── Rejestr wzorów ────────────────────────────────────────────────────────────


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise AgreementError("Nazwij wzór, np. „Zlecenie — recepcja”.")
    if len(name) > NAME_MAX_LENGTH:
        raise AgreementError(
            f"Nazwa wzoru może mieć najwyżej {NAME_MAX_LENGTH} znaków."
        )
    return name


def _clean_description(value: Any) -> Optional[str]:
    text_value = " ".join(str(value or "").split())
    if len(text_value) > DESCRIPTION_MAX_LENGTH:
        raise AgreementError(
            f"Opis wzoru może mieć najwyżej {DESCRIPTION_MAX_LENGTH} znaków."
        )
    return text_value or None


_ACTIVE_NAME_INDEX = "ux_hr_agreement_templates_active_name"


def _duplicate_name(kind: str, name: str) -> AgreementConflict:
    return AgreementConflict(
        f"Wzór „{name}” ({KIND_LABELS[kind].lower()}) już jest — wybierz inną nazwę "
        "albo dodaj nową wersję istniejącego wzoru."
    )


async def _ensure_unique_name(
    db: AsyncSession, kind: str, name: str, *, exclude_id: Optional[int] = None
) -> None:
    query = select(HrAgreementTemplate.id).where(
        HrAgreementTemplate.kind == kind,
        HrAgreementTemplate.is_active.is_(True),
        func.lower(HrAgreementTemplate.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.where(HrAgreementTemplate.id != exclude_id)
    if await db.scalar(query.limit(1)) is not None:
        raise _duplicate_name(kind, name)


async def _flush_unique(db: AsyncSession, template: HrAgreementTemplate) -> None:
    """Dwa równoczesne wgrania tej samej nazwy: drugie zatrzymuje unikat bazy (409)."""

    kind, name = template.kind, template.name
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if _ACTIVE_NAME_INDEX not in str(exc.orig):
            raise
        raise _duplicate_name(kind, name) from exc


def _checked_fields(filename: str, content: bytes, kind: str) -> list[str]:
    try:
        return check_upload(filename, content, kind)
    except TemplateRejected as exc:
        raise AgreementError(str(exc)) from exc


def _version(
    template_id: int,
    number: int,
    filename: str,
    content: bytes,
    fields: list[str],
    actor: User,
) -> HrAgreementTemplateVersion:
    return HrAgreementTemplateVersion(
        template_id=template_id,
        version=number,
        file_name=Path(filename).name[:255] or "wzor.docx",
        content=content,
        file_sha256=hashlib.sha256(content).hexdigest(),
        file_size=len(content),
        fields=fields,
        created_by=actor.id,
    )


async def create_template(
    db: AsyncSession,
    *,
    kind: str,
    name: Any,
    description: Any,
    filename: str,
    content: bytes,
    actor: User,
) -> HrAgreementTemplate:
    """Nowy wzór z wersją 1 (po ``check_upload``; odmowa = 422)."""

    clean = _clean_name(name)
    fields = _checked_fields(filename, content, kind)
    await _ensure_unique_name(db, kind, clean)
    template = HrAgreementTemplate(
        kind=kind,
        name=clean,
        description=_clean_description(description),
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(template)
    await _flush_unique(db, template)
    db.add(_version(template.id, 1, filename, content, fields, actor))
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="hr_agreement_template",
        entity_id=template.id,
        action="template_uploaded",
        details={"kind": kind, "version": 1, "fields": fields},
    )
    return template


async def get_template(db: AsyncSession, template_id: int) -> HrAgreementTemplate:
    template = await db.get(HrAgreementTemplate, template_id)
    if template is None:
        raise AgreementNotFound("Nie ma takiego wzoru umowy.")
    return template


async def add_version(
    db: AsyncSession, template_id: int, *, filename: str, content: bytes, actor: User
) -> HrAgreementTemplateVersion:
    """Nowa wersja pliku wzoru; numer pod blokadą wiersza wzoru."""

    template = await db.scalar(
        select(HrAgreementTemplate)
        .where(HrAgreementTemplate.id == template_id)
        .with_for_update()
    )
    if template is None:
        raise AgreementNotFound("Nie ma takiego wzoru umowy.")
    if not template.is_active:
        raise AgreementConflict(
            "Wzór jest wycofany — przywróć go przed dodaniem wersji."
        )
    fields = _checked_fields(filename, content, template.kind)
    last = await db.scalar(
        select(func.max(HrAgreementTemplateVersion.version)).where(
            HrAgreementTemplateVersion.template_id == template_id
        )
    )
    version = _version(
        template.id, int(last or 0) + 1, filename, content, fields, actor
    )
    db.add(version)
    template.updated_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="hr_agreement_template",
        entity_id=template.id,
        action="template_version_added",
        details={"version": version.version, "fields": fields},
    )
    return version


async def update_template(
    db: AsyncSession, template_id: int, values: Mapping[str, Any], *, actor: User
) -> HrAgreementTemplate:
    """Nazwa, opis, wycofanie i przywrócenie. Treść pliku zmienia nowa wersja."""

    template = await get_template(db, template_id)
    if "name" in values and values["name"] is not None:
        name = _clean_name(values["name"])
        if template.is_active:
            await _ensure_unique_name(db, template.kind, name, exclude_id=template.id)
        template.name = name
    if "description" in values:
        template.description = _clean_description(values["description"])
    if values.get("is_active") is False:
        template.is_active = False
    elif values.get("is_active") is True and not template.is_active:
        await _ensure_unique_name(
            db, template.kind, template.name, exclude_id=template.id
        )
        template.is_active = True
    template.updated_by = actor.id
    await _flush_unique(db, template)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="hr_agreement_template",
        entity_id=template.id,
        action="template_updated",
        details={"fields": sorted(values), "is_active": template.is_active},
    )
    return template


async def latest_version(
    db: AsyncSession, template_id: int
) -> Optional[HrAgreementTemplateVersion]:
    return await db.scalar(
        select(HrAgreementTemplateVersion)
        .where(HrAgreementTemplateVersion.template_id == template_id)
        .order_by(HrAgreementTemplateVersion.version.desc())
        .limit(1)
    )


async def version_with_template(
    db: AsyncSession, version_id: int
) -> tuple[HrAgreementTemplateVersion, HrAgreementTemplate]:
    version = await db.get(HrAgreementTemplateVersion, version_id)
    if version is None:
        raise AgreementNotFound("Nie ma takiej wersji wzoru.")
    template = await get_template(db, version.template_id)
    return version, template


async def version_content(db: AsyncSession, version_id: int) -> bytes:
    content = await db.scalar(
        select(HrAgreementTemplateVersion.content).where(
            HrAgreementTemplateVersion.id == version_id
        )
    )
    if content is None:
        raise AgreementNotFound("Nie ma takiej wersji wzoru.")
    return content


def version_payload(
    version: HrAgreementTemplateVersion, *, agreements: int = 0
) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "file_name": version.file_name,
        "file_size": version.file_size,
        "fields": list(version.fields or []),
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "agreements": agreements,
    }


async def list_templates(db: AsyncSession, *, active_only: bool = False) -> list[dict]:
    """Wzory z wersjami (najnowsza pierwsza) i liczbą umów z każdej wersji."""

    query = select(HrAgreementTemplate).order_by(
        HrAgreementTemplate.is_active.desc(),
        HrAgreementTemplate.kind,
        HrAgreementTemplate.name,
    )
    if active_only:
        query = query.where(HrAgreementTemplate.is_active.is_(True))
    templates = list((await db.scalars(query)).all())
    if not templates:
        return []
    ids = [template.id for template in templates]
    versions: dict[int, list[HrAgreementTemplateVersion]] = defaultdict(list)
    for version in (
        await db.scalars(
            select(HrAgreementTemplateVersion)
            .where(HrAgreementTemplateVersion.template_id.in_(ids))
            .order_by(HrAgreementTemplateVersion.version.desc())
        )
    ).all():
        versions[version.template_id].append(version)
    usage = {
        version_id: int(count)
        for version_id, count in (
            await db.execute(
                select(HrAgreement.template_version_id, func.count())
                .join(
                    HrAgreementTemplateVersion,
                    HrAgreementTemplateVersion.id == HrAgreement.template_version_id,
                )
                .where(HrAgreementTemplateVersion.template_id.in_(ids))
                .group_by(HrAgreement.template_version_id)
            )
        ).all()
    }
    return [
        {
            "id": template.id,
            "kind": template.kind,
            "kind_label": KIND_LABELS[template.kind],
            "name": template.name,
            "description": template.description,
            "is_active": template.is_active,
            "versions": [
                version_payload(version, agreements=usage.get(version.id, 0))
                for version in versions[template.id]
            ],
        }
        for template in templates
    ]


__all__ = [
    "DOCX_MEDIA_TYPE",
    "FIELDS",
    "KIND_LABELS",
    "REQUIRED_FIELDS",
    "add_version",
    "check_upload",
    "create_template",
    "field_rows",
    "get_template",
    "latest_version",
    "list_templates",
    "render",
    "sample_context",
    "sample_document",
    "update_template",
    "version_content",
    "version_payload",
    "version_with_template",
]
