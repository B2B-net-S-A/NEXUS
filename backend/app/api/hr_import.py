"""Import z Compassa z ekranu Ustawienia → „Import z Compassa” (plan, krok 4 i §7).

Prefiks ``/api/hr/admin/import`` (wpina ``app/main.py``). Ten sam przebieg co
``scripts/hr_compass_import.py``, tylko dla wszystkich modułów naraz:

* ``POST /dry-run`` — plik paczki (``.json`` albo ``.zip`` z jednym ``.json``,
  format w ``compass_import/BUNDLE.md``) → partie modułów i raport z liczbami.
  Moduły liczą się łańcuchem w kolejności zależności (kartoteki → urlopy → …):
  próbny zapis każdego modułu idzie do SAVEPOINT-u, następny moduł planuje na
  tym stanie, a na końcu całość jest cofana. Bez łańcucha urlopy, timesheety
  i płace przy pierwszym imporcie wyglądałyby jak „osoba bez kartoteki”.
* ``POST /{upload_id}/apply`` — zapis TEJ paczki, którą sprawdzono na sucho
  (SHA-256 z raportu musi się zgadzać z plikiem w bazie), dla wybranych
  modułów, w jednej transakcji. Tylko admin: to hurtowa zmiana danych płacowych
  i zdrowotnych. Odmowa (409), gdy sprawdzenie ma ponad 24 h albo po nim ktoś
  zapisał inną paczkę (też z wiersza poleceń).
* ``GET /batches`` — historia: kto, kiedy, SHA, stan, liczby; paczki z ekranu
  i partie ze skryptu (``source``: ``screen`` / ``script``).

Dane osobowe: surowa paczka leży w ``hr_import_uploads.bundle`` tylko do
zapisu albo 24 h (sprząta ją kolejny przebieg na sucho albo
``purge_expired_uploads``); po zapisie zostają SHA-256 i liczby. Raporty
i logi niosą liczby i identyfikatory Compassa; e-mail osoby przy pozycji
do wyjaśnienia dostaje wyłącznie administrator, w odpowiedzi na sucho.

Trasy mają ``@limiter.limit`` — dlatego moduł NIE ma ``from __future__ import
annotations`` (ciało żądania lądowałoby jako parametr query → 422).
"""

import asyncio
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Mapping, NoReturn, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission, require_roles
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.zip_guard import UnsafeArchive, assert_safe_ooxml
from app.models.hr_ops import HrImportBatch, HrImportUpload
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.hr import audit, compass_import
from app.services.hr.compass_import.bundle import MAX_BUNDLE_BYTES
from app.services.hr.compass_import.core import ModulePlan

logger = logging.getLogger(__name__)

router = APIRouter()

#: Sprawdzenie na sucho jest ważne dobę — potem paczka znika z bazy.
UPLOAD_TTL = timedelta(hours=24)
#: Plik z przeglądarki. Ciało żądania i tak tnie middleware (30 MB); paczka
#: całej bazy Compassa to kilka MB, ZIP schodzi do ułamka tego.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
#: Paczka po rozpakowaniu — ten sam bezpiecznik co ``parse_bundle``.
MAX_UNPACKED_BYTES = MAX_BUNDLE_BYTES
MAX_ZIP_ENTRIES = 10
#: Pozycji do wyjaśnienia w odpowiedzi na moduł (pełna lista jest w partii).
ATTENTION_LIMIT = 200
#: Wierszy w historii (paczki z ekranu i partie ze skryptu razem).
HISTORY_LIMIT = 50
ACTIONS = ("create", "update", "unchanged", "conflict", "skip")
LOCK_KEY = "hr_compass_import"
#: Kolumny wiersza źródła, które wskazują osobę Compassa (``profiles.id``).
PERSON_COLUMNS = ("user_id", "recipient_user_id", "person_id")

MSG_LOCKED = "Trwa inny import z Compassa — spróbuj za chwilę."
MSG_NOT_FOUND = "Nie ma takiej partii importu."
MSG_EXPIRED = "Sprawdzenie na sucho wygasło (ważne 24 h) — wgraj paczkę ponownie."
MSG_SUPERSEDED = (
    "Po tym sprawdzeniu zapisano inną paczkę — sprawdź paczkę na sucho ponownie."
)
MSG_APPLIED = (
    "Ta paczka jest już zapisana. Wgraj ją ponownie, jeśli chcesz sprawdzić, "
    "czy coś się zmieniło."
)
MSG_SHA_MISMATCH = (
    "To nie jest paczka sprawdzona na sucho (inna suma SHA-256) — "
    "sprawdź paczkę ponownie."
)
MSG_MODULE_FAILED = (
    "Próbny zapis modułu przerwał błąd — zapis też by się nie udał. "
    "Szczegóły są w logu serwera."
)


def require_hr_import_reader():
    """Na sucho i historia: Kadry (uprawnienie „Kadry”; admin ma je zawsze)."""

    gate = require_permission(ProductAction.people_admin)

    async def _check(user: User = Depends(gate)) -> User:
        return user

    return _check


def require_hr_import_writer():
    """Zapis: wyłącznie administrator (hurtem dane płacowe i zdrowotne)."""

    gate = require_roles(UserRole.admin)

    async def _check(user: User = Depends(gate)) -> User:
        return user

    return _check


HrImportReader = Annotated[User, Depends(require_hr_import_reader())]
HrImportWriter = Annotated[User, Depends(require_hr_import_writer())]


class ApplyIn(BaseModel):
    bundle_sha256: str = Field(min_length=64, max_length=64)
    modules: list[str] = Field(min_length=1, max_length=len(compass_import.IMPORTERS))


@dataclass(frozen=True)
class _ModuleRun:
    module: str
    plan: Optional[ModulePlan]
    failed: bool


# ── Plik paczki ──────────────────────────────────────────────────────────────


def _unpack(content: bytes) -> bytes:
    """``.json`` bez zmian; ``.zip`` → jedyny plik ``.json`` z limitem rozmiaru."""

    if not content.startswith(b"PK"):
        return content
    try:
        assert_safe_ooxml(content)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise HTTPException(422, "Archiwum ma za dużo plików.")
            files = [
                entry
                for entry in entries
                if not entry.is_dir() and not entry.filename.startswith("__MACOSX/")
            ]
            if len(files) != 1 or not files[0].filename.lower().endswith(".json"):
                raise HTTPException(
                    422, "W archiwum ma być dokładnie jeden plik .json z paczką."
                )
            if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
                raise HTTPException(413, _too_big_unpacked())
            with archive.open(files[0]) as handle:
                raw = handle.read(MAX_UNPACKED_BYTES + 1)
    except UnsafeArchive as exc:
        raise HTTPException(413, _too_big_unpacked()) from exc
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise HTTPException(422, "Nie da się otworzyć archiwum ZIP.") from exc
    if len(raw) > MAX_UNPACKED_BYTES:
        raise HTTPException(413, _too_big_unpacked())
    return raw


def _too_big_unpacked() -> str:
    return (
        f"Paczka po rozpakowaniu przekracza {MAX_UNPACKED_BYTES // (1024 * 1024)} MB."
    )


def _load_bundle(content: bytes) -> tuple[bytes, compass_import.Bundle]:
    raw = _unpack(content)
    try:
        return raw, compass_import.parse_bundle(raw)
    except compass_import.BundleError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _read_upload(file: UploadFile) -> bytes:
    # Odczyt z limitem + 1 bajt: za duży plik nigdy nie trafia w całości do RAM.
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(422, "Plik paczki jest pusty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"Plik jest większy niż {MAX_UPLOAD_BYTES // (1024 * 1024)} MB — "
            "spakuj paczkę do .zip.",
        )
    return content


# ── Przebieg ─────────────────────────────────────────────────────────────────


async def _take_lock(db: AsyncSession) -> None:
    locked = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": LOCK_KEY}
    )
    if not locked:
        raise HTTPException(409, MSG_LOCKED)


def _fixed(plan: ModulePlan) -> compass_import.Planner:
    async def planner(_db: AsyncSession, _bundle: compass_import.Bundle) -> ModulePlan:
        return plan

    return planner


def _failure(exc: Exception) -> str:
    # Do logu tylko typ i nazwa ograniczenia — treść błędu bazy niesie wartości.
    constraint = getattr(getattr(exc, "orig", None), "constraint_name", None)
    return f"{type(exc).__name__}" + (f" ({constraint})" if constraint else "")


async def _simulate_chain(
    db: AsyncSession, bundle: compass_import.Bundle, actor_id: int
) -> list[_ModuleRun]:
    """Plan każdego modułu na stanie po próbnym zapisie modułów wcześniejszych."""

    runs: list[_ModuleRun] = []
    chain = await db.begin_nested()
    try:
        for module, importer in compass_import.IMPORTERS.items():
            plan: Optional[ModulePlan] = None
            try:
                async with db.begin_nested():
                    plan = await importer.plan(db, bundle)
                    trial, _ = await compass_import.dry_run(
                        db,
                        module=module,
                        bundle=bundle,
                        planner=_fixed(plan),
                        actor_user_id=actor_id,
                    )
                    await compass_import.apply(
                        db,
                        batch=trial,
                        bundle=bundle,
                        planner=_fixed(plan),
                        applier=importer.apply,
                        actor_user_id=actor_id,
                    )
            except Exception as exc:  # noqa: BLE001 — błąd modułu trafia do raportu
                logger.warning(
                    "hr import dry-run: module %s failed: %s", module, _failure(exc)
                )
                runs.append(_ModuleRun(module, plan, failed=True))
                continue
            runs.append(_ModuleRun(module, plan, failed=False))
    finally:
        await chain.rollback()
    return runs


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    counts = report.get("counts") or {}
    return {
        "total": int(report.get("total") or 0),
        "counts": {action: int(counts.get(action, 0)) for action in ACTIONS},
        "reasons": dict(report.get("reasons") or {}),
        "extra": dict(report.get("extra") or {}),
        "attention_total": len(report.get("attention") or ()),
    }


def _attention_emails(
    bundle: compass_import.Bundle, items: list[Mapping[str, Any]]
) -> dict[str, str]:
    """E-mail osoby Compassa przy pozycji do wyjaśnienia (tylko dla admina)."""

    profiles = {str(row.get("id")): row for row in bundle.rows("profiles")}
    tables: dict[str, dict[str, Mapping[str, Any]]] = {}
    found: dict[str, str] = {}
    for item in items:
        table, _, raw_id = str(item.get("source_id") or "").partition(":")
        if table == "profiles":
            person = profiles.get(raw_id)
        else:
            if table not in tables:
                tables[table] = {str(row.get("id")): row for row in bundle.rows(table)}
            source = tables[table].get(raw_id) or {}
            compass_id = next(
                (source[column] for column in PERSON_COLUMNS if source.get(column)),
                None,
            )
            person = profiles.get(str(compass_id)) if compass_id else None
        email = (person or {}).get("email")
        if email:
            found[str(item["source_id"])] = str(email).strip()
    return found


async def purge_expired_uploads(db: AsyncSession) -> int:
    """Paczki po terminie tracą surowe dane (do pętli albo przed przebiegiem)."""

    result = await db.execute(
        update(HrImportUpload)
        .where(
            HrImportUpload.status == "dry_run",
            HrImportUpload.expires_at <= func.now(),
        )
        .values(status="expired", bundle=None)
    )
    return result.rowcount or 0


async def _names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    wanted = {user_id for user_id in ids if user_id is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {user_id: name for user_id, name in rows.all()}


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.isoformat() if moment else None


def _view(
    upload: HrImportUpload,
    names: Mapping[int, str],
    *,
    now: datetime,
    attention: Optional[Mapping[str, list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    report = upload.report or {}
    dry = report.get("dry_run") or {}
    applied = report.get("applied") or {}
    status = upload.status
    if status == "dry_run" and upload.expires_at <= now:
        status = "expired"
    modules = []
    for module, importer in compass_import.IMPORTERS.items():
        summary = dry.get(module)
        if summary is None:
            continue
        entry: dict[str, Any] = {
            "module": module,
            "label": importer.label,
            **summary,
            "applied": applied.get(module),
        }
        if attention is not None:
            entry["attention"] = attention.get(module, [])
        modules.append(entry)
    return {
        "id": upload.id,
        "source": "screen",
        "status": status,
        "bundle_sha256": upload.bundle_sha256,
        "size_bytes": upload.size_bytes,
        "exported_at": report.get("exported_at"),
        "created_at": _iso(upload.created_at),
        "created_by_name": names.get(upload.created_by) if upload.created_by else None,
        "expires_at": _iso(upload.expires_at),
        "applied_at": _iso(upload.applied_at),
        "applied_by_name": names.get(upload.applied_by) if upload.applied_by else None,
        "applied_modules": list(report.get("applied_modules") or []),
        "modules": modules,
    }


def _script_view(
    batch: HrImportBatch,
    names: Mapping[int, str],
    *,
    last_applied_at: Optional[datetime],
) -> dict[str, Any]:
    """Partia z ``scripts/hr_compass_import.py``: jeden moduł, bez paczki w bazie.

    Kształt jak ``_view``, żeby historia była jedną listą. Sprawdzenie na sucho
    sprzed późniejszego zapisu (dowolnej partii) jest nieaktualne, tak jak na
    ekranie; terminu 24 h skrypt nie ma, bo paczka nie leży w bazie.
    """

    report = batch.report or {}
    applied = report.get("applied")
    status = batch.status
    if (
        status == "dry_run"
        and last_applied_at is not None
        and batch.created_at < last_applied_at
    ):
        status = "superseded"
    importer = compass_import.IMPORTERS.get(batch.module)
    module = {
        "module": batch.module,
        "label": importer.label if importer else batch.module,
        **_summary(report.get("dry_run") or {}),
        "error": None,
        "applied": (
            {**_summary(applied), "written": dict(applied.get("written") or {})}
            if applied
            else None
        ),
    }
    return {
        "id": batch.id,
        "source": "script",
        "status": status,
        "bundle_sha256": batch.bundle_sha256,
        "size_bytes": None,
        "exported_at": report.get("exported_at"),
        "created_at": _iso(batch.created_at),
        "created_by_name": names.get(batch.created_by) if batch.created_by else None,
        "expires_at": None,
        "applied_at": _iso(batch.applied_at),
        "applied_by_name": names.get(batch.applied_by) if batch.applied_by else None,
        "applied_modules": [batch.module] if batch.status == "applied" else [],
        "modules": [module],
    }


# ── Trasy ────────────────────────────────────────────────────────────────────


@router.post("/dry-run")
@limiter.limit("6/minute", key_func=user_or_ip_key)
async def dry_run_upload(
    request: Request,  # wymagane przez limiter slowapi
    current_user: HrImportReader,
    file: UploadFile = File(..., description="Paczka eksportu Compassa (.json/.zip)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    actor_id = current_user.id
    is_admin = current_user.has_role(UserRole.admin)
    content = await _read_upload(file)
    raw, bundle = await asyncio.to_thread(_load_bundle, content)

    await _take_lock(db)
    await purge_expired_uploads(db)
    runs = await _simulate_chain(db, bundle, actor_id)

    batch_ids: dict[str, int] = {}
    summaries: dict[str, dict[str, Any]] = {}
    attention: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        if run.failed or run.plan is None:
            summaries[run.module] = {**_summary({}), "error": MSG_MODULE_FAILED}
            continue
        batch, _ = await compass_import.dry_run(
            db,
            module=run.module,
            bundle=bundle,
            planner=_fixed(run.plan),
            actor_user_id=actor_id,
        )
        batch_ids[run.module] = batch.id
        report = batch.report["dry_run"]
        summaries[run.module] = {**_summary(report), "error": None}
        attention[run.module] = [
            dict(item) for item in report["attention"][:ATTENTION_LIMIT]
        ]

    if is_admin:
        emails = _attention_emails(
            bundle, [item for items in attention.values() for item in items]
        )
        for items in attention.values():
            for item in items:
                item["email"] = emails.get(item["source_id"])

    now = await db.scalar(select(func.now()))
    upload = HrImportUpload(
        bundle_sha256=bundle.sha256,
        size_bytes=len(raw),
        bundle=raw,
        status="dry_run",
        batch_ids=batch_ids,
        report={"exported_at": bundle.exported_at, "dry_run": summaries},
        created_by=actor_id,
        created_at=now,
        expires_at=now + UPLOAD_TTL,
    )
    db.add(upload)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="hr_import_upload",
        entity_id=upload.id,
        action="compass_import_dry_run",
        details={
            "bundle_sha256": bundle.sha256,
            "counts": {module: s["counts"] for module, s in summaries.items()},
        },
    )
    await db.commit()
    logger.info(
        "hr import dry-run: upload=%s sha=%s modules=%s",
        upload.id,
        bundle.sha256[:12],
        {module: s["counts"] for module, s in summaries.items()},
    )
    names = await _names(db, {actor_id})
    return _view(upload, names, now=now, attention=attention)


async def _refuse(
    db: AsyncSession, upload: HrImportUpload, status: str, detail: str
) -> NoReturn:
    """Partia przestaje czekać: bez surowej paczki, z powodem w stanie."""

    upload.status = status
    upload.bundle = None
    await db.commit()
    raise HTTPException(409, detail)


@router.post("/{upload_id}/apply")
@limiter.limit("6/minute", key_func=user_or_ip_key)
async def apply_upload(
    request: Request,  # wymagane przez limiter slowapi
    upload_id: int,
    payload: ApplyIn,
    current_user: HrImportWriter,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    actor_id = current_user.id
    unknown = sorted(set(payload.modules) - set(compass_import.IMPORTERS))
    if unknown:
        raise HTTPException(422, f"Nieznany moduł importu: {', '.join(unknown)}.")
    selected = [m for m in compass_import.IMPORTERS if m in set(payload.modules)]

    await _take_lock(db)
    upload = await db.get(HrImportUpload, upload_id, with_for_update=True)
    if upload is None:
        raise HTTPException(404, MSG_NOT_FOUND)
    if upload.status != "dry_run":
        raise HTTPException(
            409,
            {
                "applied": MSG_APPLIED,
                "superseded": MSG_SUPERSEDED,
            }.get(upload.status, MSG_EXPIRED),
        )
    now = await db.scalar(select(func.now()))
    if upload.expires_at <= now:
        await _refuse(db, upload, "expired", MSG_EXPIRED)
    if payload.bundle_sha256 != upload.bundle_sha256:
        raise HTTPException(409, MSG_SHA_MISMATCH)
    later = await db.scalar(
        select(func.count())
        .select_from(HrImportBatch)
        .where(
            HrImportBatch.status == "applied",
            HrImportBatch.applied_at > upload.created_at,
        )
    )
    if later:
        await _refuse(db, upload, "superseded", MSG_SUPERSEDED)

    raw = await db.scalar(
        select(HrImportUpload.bundle).where(HrImportUpload.id == upload.id)
    )
    if raw is None:
        await _refuse(db, upload, "expired", MSG_EXPIRED)
    bundle = await asyncio.to_thread(compass_import.parse_bundle, raw)
    if bundle.sha256 != upload.bundle_sha256:
        raise HTTPException(409, MSG_SHA_MISMATCH)

    dry = (upload.report or {}).get("dry_run") or {}
    failed = [m for m in selected if (dry.get(m) or {}).get("error")]
    if failed or any(m not in upload.batch_ids for m in selected):
        labels = ", ".join(
            compass_import.IMPORTERS[m].label for m in failed or selected
        )
        raise HTTPException(
            422, f"Ten moduł nie przeszedł sprawdzenia na sucho: {labels}."
        )
    pending_profiles = ((dry.get("profiles") or {}).get("counts") or {}).get("create")
    if "profiles" not in selected and pending_profiles:
        raise HTTPException(
            422,
            "Najpierw kartoteki: paczka zakłada nowe kartoteki, a pozostałe moduły "
            "łączą osoby przez kartoteki. Zaznacz też „"
            f"{compass_import.IMPORTERS['profiles'].label}”.",
        )

    applied: dict[str, dict[str, Any]] = {}
    for module in selected:
        importer = compass_import.IMPORTERS[module]
        batch = await db.get(HrImportBatch, int(upload.batch_ids[module]))
        if batch is None:
            raise HTTPException(409, MSG_SUPERSEDED)
        try:
            written = await compass_import.apply(
                db,
                batch=batch,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=actor_id,
            )
        except compass_import.ImportFlowError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            logger.error(
                "hr import apply: upload=%s module %s failed: %s",
                upload.id,
                module,
                _failure(exc),
            )
            raise HTTPException(
                500,
                f"Zapis modułu „{importer.label}” przerwał błąd — nic nie zapisano. "
                "Szczegóły są w logu serwera.",
            ) from exc
        applied[module] = {
            **_summary(batch.report["applied"]),
            "written": dict(written),
        }

    upload.status = "applied"
    upload.bundle = None
    upload.applied_by = actor_id
    upload.applied_at = now
    upload.report = {
        **(upload.report or {}),
        "applied": applied,
        "applied_modules": selected,
    }
    # Inne sprawdzenia na sucho liczyły stan sprzed tego zapisu — nieaktualne.
    await db.execute(
        update(HrImportUpload)
        .where(HrImportUpload.status == "dry_run", HrImportUpload.id != upload.id)
        .values(status="superseded", bundle=None)
    )
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="hr_import_upload",
        entity_id=upload.id,
        action="compass_import_apply",
        details={
            "bundle_sha256": upload.bundle_sha256,
            "modules": selected,
            "written": {module: a["written"] for module, a in applied.items()},
        },
    )
    await db.commit()
    logger.info(
        "hr import apply: upload=%s sha=%s written=%s",
        upload.id,
        upload.bundle_sha256[:12],
        {module: a["written"] for module, a in applied.items()},
    )
    names = await _names(db, {upload.created_by, upload.applied_by})
    return _view(upload, names, now=now)


@router.get("/batches")
async def list_uploads(
    _: HrImportReader,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Paczki z ekranu i partie ze skryptu w jednej liście, od najnowszych.

    Partie paczki z ekranu wskazuje ``HrImportUpload.batch_ids``; partia bez
    takiej paczki przyszła z wiersza poleceń (import 18.10.2026 szedł skryptem
    i ekran pokazywał „nie było importu”).
    """

    uploads = (
        await db.scalars(
            select(HrImportUpload)
            .order_by(HrImportUpload.id.desc())
            .limit(HISTORY_LIMIT)
        )
    ).all()
    from_screen = {
        int(batch_id)
        for batch_ids in (await db.scalars(select(HrImportUpload.batch_ids))).all()
        for batch_id in (batch_ids or {}).values()
    }
    scripted = (
        await db.scalars(
            select(HrImportBatch)
            .where(HrImportBatch.id.not_in(from_screen))
            .order_by(HrImportBatch.id.desc())
            .limit(HISTORY_LIMIT)
        )
    ).all()
    now = await db.scalar(select(func.now()))
    last_applied_at = await db.scalar(select(func.max(HrImportBatch.applied_at)))
    people = [*uploads, *scripted]
    names = await _names(
        db, {p.created_by for p in people} | {p.applied_by for p in people}
    )
    rows = [
        *((u.created_at, _view(u, names, now=now)) for u in uploads),
        *(
            (b.created_at, _script_view(b, names, last_applied_at=last_applied_at))
            for b in scripted
        ),
    ]
    rows.sort(key=lambda row: row[0], reverse=True)
    return [view for _, view in rows[:HISTORY_LIMIT]]
