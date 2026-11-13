"""Pliki szkoleń: SharePoint, gdy admin go skonfigurował, a do tego czasu dysk serwera.

Decyzja właściciela: pliki leżą w SharePoincie (kopie robi Microsoft, dysk serwera
NEXUSA nie ma kopii poza serwerem), a NEXUS je pokazuje i pilnuje, kto je widzi.
Dostęp idzie tą samą rejestracją ``Sites.Selected`` co dokumenty kontraktów
(``services/m365/sharepoint_docs.py``), ale folder szkoleń leży na innej witrynie,
więc nadanie jej uprawnienia to ręczny krok w Azure. Bez linku w
``app_settings['trainings_sharepoint']`` albo bez poświadczeń plik zostaje na dysku
pod ``STORAGE_ROOT/trainings/<id>/files/<uuid>``.

Nagrania z Teams mają do 2 GB, dlatego plik nigdy nie trafia w całości do pamięci:
kopiujemy go kawałkami na dysk, licząc SHA-256 po drodze, a do SharePointa wysyłamy
sesją uploadu po 10 MB. Klucz pliku nie niesie nazwy od człowieka (dwa „nagranie.mp4”
w jednym szkoleniu to dwa pliki). Błędy Graphu logujemy kodem HTTP albo klasą
wyjątku, bez nazw plików.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional, Union
from urllib.parse import quote

import anyio
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse, Response, StreamingResponse

from app.core.http_headers import content_disposition
from app.models.app_setting import AppSetting
from app.models.training import TrainingFile
from app.services import storage_service
from app.services.m365 import sharepoint_docs as sp
from app.services.m365.graph_client import GraphRequestError
from app.services.trainings.errors import TrainingError

logger = logging.getLogger(__name__)

SETTINGS_KEY = "trainings_sharepoint"
DEFAULT_FOLDER_NAME = "Szkolenia"
SUBDIR = "trainings"

MAX_BYTES = 2 * 1024 * 1024 * 1024

#: Rozszerzenie → typ zapisywany w bazie. Typ od przeglądarki ignorujemy: to on
#: decyduje o ``inline`` przy odtwarzaniu, więc nie może pochodzić od uploadującego.
ALLOWED: dict[str, str] = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "mp4": "video/mp4",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "zip": "application/zip",
    "csv": "text/csv",
}

#: Projekty programów montażowych (DaVinci, Premiere, After Effects, Final Cut,
#: Vegas, Kdenlive, Camtasia, Filmora, Clipchamp/Movie Maker). Bez programu i plików
#: źródłowych nikt ich nie obejrzy, a trenerzy wysyłali je zamiast gotowego nagrania.
EDITOR_PROJECT_EXTENSIONS = frozenset(
    {
        "drp",
        "drt",
        "dra",
        "prproj",
        "aep",
        "aepx",
        "fcpxml",
        "fcpbundle",
        "veg",
        "vf",
        "kdenlive",
        "mlt",
        "camproj",
        "tscproj",
        "wfp",
        "wlmp",
        "mswmm",
    }
)
EDITOR_PROJECT_MESSAGE = (
    "Pliki projektu montażowego nie są przyjmowane. Wgraj gotowy plik MP4 albo MP3."
)
BAD_TYPE_MESSAGE = (
    "Ten typ pliku nie jest przyjmowany. Wgraj PDF, PPTX, DOCX, XLSX, MP4, M4A, MP3, "
    "PNG, JPG, ZIP albo CSV."
)
TOO_LARGE_MESSAGE = (
    "Plik jest większy niż 2 GB. Skróć nagranie albo podziel je na części."
)
EMPTY_MESSAGE = "Plik jest pusty."
MISSING_MESSAGE = "Nie ma już tego pliku w magazynie. Poproś o ponowne wgranie."

#: Typy, które przeglądarka może pokazać w karcie bez wykonania kodu na originie API.
_INLINE_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "video/mp4",
        "audio/mp4",
        "audio/mpeg",
    }
)
_CACHE_CONTROL = "private, no-store"

_COPY_CHUNK = 1024 * 1024
#: Kawałek sesji uploadu musi być wielokrotnością 320 KiB (wymóg Graphu); 10 MiB.
_UPLOAD_CHUNK = 32 * 320 * 1024
_UPLOAD_RETRIES = 3
_UPLOAD_RETRY_DELAY = 2.0
_STREAM_CHUNK = 256 * 1024
_UPLOAD_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_PASSED_HEADERS = ("content-length", "content-range")

#: Znaki, których SharePoint nie przyjmuje w nazwie pliku ani folderu.
_SP_FORBIDDEN = re.compile(r'["*:<>?/\\|#%\x00-\x1f]')
_SPACES = re.compile(r"\s+")

Source = Union[str, os.PathLike, BinaryIO, AsyncIterable[bytes], Any]


@dataclass(frozen=True)
class SpTarget:
    share_url: str
    drive_id: str
    folder_id: str


@dataclass(frozen=True)
class StoredFile:
    storage: str  # "local" | "sharepoint"
    storage_key: str  # ścieżka względem STORAGE_ROOT albo id elementu w SharePoincie
    sp_drive_id: Optional[str]
    size_bytes: int
    sha256: str
    content_type: str


# ── Ustawienia ──────────────────────────────────────────────────────────────


async def load_settings(db: AsyncSession) -> Optional[SpTarget]:
    row = await db.get(AppSetting, SETTINGS_KEY)
    value = dict(row.value or {}) if row is not None else {}
    drive_id = str(value.get("drive_id") or "")
    folder_id = str(value.get("folder_id") or "")
    if not drive_id or not folder_id:
        return None
    return SpTarget(str(value.get("share_url") or ""), drive_id, folder_id)


async def save_settings(
    db: AsyncSession,
    share_url: str,
    *,
    folder_name: str = DEFAULT_FOLDER_NAME,
    user_id: Optional[int] = None,
) -> SpTarget:
    """Link udostępnienia folderu → (dysk, folder), tak jak w dokumentach kontraktów.

    ``folder_name`` przydaje się tylko wtedy, gdy ``/shares`` odpowiada 403
    (``Sites.Selected``), a link nie niesie ścieżki folderu.
    """
    url = (share_url or "").strip()
    if not url.lower().startswith("https://"):
        raise TrainingError(
            422,
            "Wklej link do folderu w SharePoincie (zaczyna się od https://).",
            "sp_link",
        )
    if not sp.credentials_configured():
        raise TrainingError(
            409,
            "Brak konfiguracji aplikacji SharePoint w NEXUSIE — dokończ konfigurację w Azure.",
            "sp_not_configured",
        )
    try:
        async with sp.graph_client() as client:
            folder = await sp.resolve_folder(
                client, url, folder_name=folder_name or DEFAULT_FOLDER_NAME
            )
    except sp.SharePointNotConfigured:
        raise TrainingError(
            409,
            "Brak konfiguracji aplikacji SharePoint w NEXUSIE — dokończ konfigurację w Azure.",
            "sp_not_configured",
        ) from None
    except sp.SharePointFolderNotFound:
        raise TrainingError(
            422,
            "Nie znaleziono folderu pod tym linkiem albo aplikacja nie ma dostępu do witryny"
            " (nadanie dostępu do witryny szkoleń to krok w Azure).",
            "sp_folder_not_found",
        ) from None
    except GraphRequestError as exc:
        logger.warning("trainings_sp: resolve failed status=%s", exc.status)
        if exc.status in (401, 403):
            message = (
                f"SharePoint odmówił dostępu (HTTP {exc.status}) — sprawdź, czy aplikacja"
                " ma nadany dostęp do witryny szkoleń."
            )
        else:
            message = f"Błąd SharePointa (HTTP {exc.status}). Spróbuj ponownie."
        raise TrainingError(422, message, "sp_error") from None

    target = SpTarget(url, folder.drive_id, folder.item_id)
    value = {"share_url": url, "drive_id": folder.drive_id, "folder_id": folder.item_id}
    row = await db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=value, updated_by=user_id))
    else:
        row.value = value
        row.updated_by = user_id
    await db.flush()
    return target


def sharepoint_ready(target: Optional[SpTarget]) -> bool:
    return bool(
        target is not None
        and target.drive_id
        and target.folder_id
        and sp.credentials_configured()
    )


# ── Typy plików i nazwy ─────────────────────────────────────────────────────


def content_type_for(file_name: str) -> str:
    """Typ zapisywany w bazie albo ``TrainingError`` 422 z polskim zdaniem.

    Router może zawołać to przed odebraniem ciała, żeby nie czekać na 2 GB odmowy.
    """
    _, dot, ext = (file_name or "").strip().rpartition(".")
    ext = ext.lower() if dot else ""
    if ext in EDITOR_PROJECT_EXTENSIONS:
        raise TrainingError(422, EDITOR_PROJECT_MESSAGE, "editor_project")
    mime = ALLOWED.get(ext)
    if mime is None:
        raise TrainingError(422, BAD_TYPE_MESSAGE, "file_type")
    return mime


def _sp_name(value: str, *, fallback: str, limit: int) -> str:
    cleaned = _SPACES.sub(" ", _SP_FORBIDDEN.sub(" ", value or "")).strip(" .")
    if len(cleaned) > limit:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and 0 < len(ext) <= 8:
            cleaned = f"{stem[: limit - len(ext) - 1].rstrip(' .')}.{ext}"
        else:
            cleaned = cleaned[:limit].rstrip(" .")
    return cleaned or fallback


def folder_name_for(training_id: int, training_title: str) -> str:
    return f"{training_id} {_sp_name(training_title, fallback='Szkolenie', limit=100)}"


# ── Dysk lokalny ────────────────────────────────────────────────────────────


def _root() -> Path:
    # Czytane przy każdym wywołaniu: testy podmieniają ``storage_service.STORAGE_ROOT``.
    return Path(storage_service.STORAGE_ROOT)


def local_path(storage_key: str) -> Path:
    """Ścieżka pliku szkolenia na dysku, bez wyjścia poza ``STORAGE_ROOT/trainings``."""
    root = _root().resolve()
    path = (root / storage_key).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem szkoleń") from None
    return path


def _copy_sync(source: Any, target: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    opened: Optional[BinaryIO] = None
    if isinstance(source, (str, os.PathLike)):
        opened = open(source, "rb")  # noqa: SIM115 — zamykane w finally
        reader: BinaryIO = opened
    else:
        reader = source
        if hasattr(reader, "seek"):
            try:
                reader.seek(0)
            except (OSError, ValueError):
                pass
    try:
        with open(target, "wb") as out:
            while True:
                chunk = reader.read(_COPY_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise TrainingError(413, TOO_LARGE_MESSAGE, "file_too_large")
                digest.update(chunk)
                out.write(chunk)
    finally:
        if opened is not None:
            opened.close()
    return size, digest.hexdigest()


async def _copy_async(source: AsyncIterable[bytes], target: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    buffer = bytearray()
    out = await anyio.to_thread.run_sync(open, target, "wb")
    try:
        async for chunk in source:
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_BYTES:
                raise TrainingError(413, TOO_LARGE_MESSAGE, "file_too_large")
            digest.update(chunk)
            buffer += chunk
            if len(buffer) >= _COPY_CHUNK:
                data, buffer = bytes(buffer), bytearray()
                await anyio.to_thread.run_sync(out.write, data)
        if buffer:
            await anyio.to_thread.run_sync(out.write, bytes(buffer))
    finally:
        await anyio.to_thread.run_sync(out.close)
    return size, digest.hexdigest()


async def _spool_to_disk(source: Source, target: Path) -> tuple[int, str]:
    """Kopia źródła na dysk kawałkami z SHA-256; 2 GB nigdy nie są w pamięci."""
    await anyio.to_thread.run_sync(
        lambda: target.parent.mkdir(parents=True, exist_ok=True)
    )
    # ``UploadFile`` → jego ``SpooledTemporaryFile`` (synchroniczny, czytany w wątku).
    inner = getattr(source, "file", None)
    if inner is not None and hasattr(inner, "read"):
        source = inner
    if isinstance(source, AsyncIterable):
        return await _copy_async(source, target)
    return await anyio.to_thread.run_sync(_copy_sync, source, target)


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("trainings_storage: unlink failed (%s)", type(exc).__name__)


async def save(
    db: AsyncSession,
    *,
    training_id: int,
    training_title: str,
    session_year: int,
    file_name: str,
    content_type: str,
    source: Source,
) -> StoredFile:
    """Zapis pliku szkolenia.

    ``source``: ścieżka pliku, obiekt plikowy (``UploadFile`` albo jego ``.file``)
    albo asynchroniczny strumień bajtów (``request.stream()``). ``content_type`` od
    przeglądarki jest tylko podpowiedzią — zapisujemy typ wynikający z rozszerzenia.
    Gdy SharePoint jest skonfigurowany, plik idzie tam; jego awaria zostawia plik na
    dysku (``storage='local'``) zamiast kazać trenerowi wgrywać 2 GB jeszcze raz.
    """
    del content_type  # typ z rozszerzenia, patrz docstring
    mime = content_type_for(file_name)
    key_dir = f"{SUBDIR}/{int(training_id)}/files"
    file_id = uuid.uuid4().hex
    final = _root() / key_dir / file_id
    temporary = final.with_name(f"{file_id}.part")
    try:
        size, digest = await _spool_to_disk(source, temporary)
    except BaseException:
        await anyio.to_thread.run_sync(_unlink, temporary)
        raise
    if size == 0:
        await anyio.to_thread.run_sync(_unlink, temporary)
        raise TrainingError(422, EMPTY_MESSAGE, "file_empty")

    target = await load_settings(db)
    if sharepoint_ready(target):
        assert target is not None
        try:
            item = await _upload_to_sharepoint(
                target,
                path=temporary,
                size=size,
                year_folder=str(int(session_year)),
                training_folder=folder_name_for(training_id, training_title),
                file_name=_sp_name(file_name, fallback="plik", limit=200),
            )
        except Exception as exc:  # noqa: BLE001 — plik zostaje na dysku
            logger.warning(
                "trainings_sp: upload failed training=%s (%s %s), keeping local copy",
                training_id,
                type(exc).__name__,
                getattr(exc, "status", ""),
            )
        else:
            await anyio.to_thread.run_sync(_unlink, temporary)
            return StoredFile(
                storage="sharepoint",
                storage_key=str(item["id"]),
                sp_drive_id=str(
                    (item.get("parentReference") or {}).get("driveId")
                    or target.drive_id
                ),
                size_bytes=size,
                sha256=digest,
                content_type=mime,
            )

    await anyio.to_thread.run_sync(os.replace, temporary, final)
    return StoredFile(
        storage="local",
        storage_key=f"{key_dir}/{file_id}",
        sp_drive_id=None,
        size_bytes=size,
        sha256=digest,
        content_type=mime,
    )


# ── SharePoint: sesja uploadu ───────────────────────────────────────────────


def _http_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    """Klient bez nagłówka ``Authorization``: adres sesji uploadu i ``downloadUrl``
    są wstępnie uwierzytelnione, token Graphu nie może tam iść."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True)


def _next_offset(status: dict[str, Any]) -> Optional[int]:
    ranges = status.get("nextExpectedRanges") or []
    if not ranges:
        return None
    try:
        return int(str(ranges[0]).split("-", 1)[0])
    except ValueError:
        return None


def _read_at(path: Path, offset: int, length: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(offset)
        return handle.read(length)


async def _upload_session(
    http: httpx.AsyncClient, upload_url: str, path: Path, size: int
) -> dict[str, Any]:
    """Wysyłka kawałkami; po zgubionej odpowiedzi pytamy sesję, od którego bajtu
    czeka, zamiast wysyłać kawałek drugi raz na ślepo."""
    offset = 0
    failures = 0
    while True:
        length = min(_UPLOAD_CHUNK, size - offset)
        chunk = await anyio.to_thread.run_sync(_read_at, path, offset, length)
        end = offset + len(chunk) - 1
        try:
            response = await http.put(
                upload_url,
                content=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                },
            )
        except httpx.TransportError:
            response = None
        if response is not None and response.status_code in (200, 201):
            return response.json()
        if response is not None and response.status_code == 202:
            failures = 0
            expected = _next_offset(response.json())
            offset = end + 1 if expected is None else expected
            continue
        if (
            response is not None
            and response.status_code < 500
            and response.status_code
            not in (
                408,
                409,
                416,
                429,
            )
        ):
            raise GraphRequestError(response.status_code, "upload chunk rejected")
        failures += 1
        if failures > _UPLOAD_RETRIES:
            status = response.status_code if response is not None else 599
            raise GraphRequestError(status, "upload chunk retries exhausted")
        await asyncio.sleep(_UPLOAD_RETRY_DELAY * failures)
        try:
            state = await http.get(upload_url)
            if state.status_code == 200:
                expected = _next_offset(state.json())
                if expected is not None:
                    offset = expected
        except httpx.TransportError:
            pass


async def _upload_to_sharepoint(
    target: SpTarget,
    *,
    path: Path,
    size: int,
    year_folder: str,
    training_folder: str,
    file_name: str,
) -> dict[str, Any]:
    async with sp.graph_client() as client:
        year = await sp.ensure_person_folder(
            client, target.drive_id, target.folder_id, year_folder
        )
        folder = await sp.ensure_person_folder(
            client, year.drive_id, year.id, training_folder
        )
        session = await client.post(
            f"/drives/{folder.drive_id}/items/{folder.id}:/{quote(file_name)}:/createUploadSession",
            json={"item": {"@microsoft.graph.conflictBehavior": "rename"}},
        )
    upload_url = str(session["uploadUrl"])
    async with _http_client(_UPLOAD_TIMEOUT) as http:
        try:
            return await _upload_session(http, upload_url, path, size)
        except BaseException:
            try:
                await http.delete(upload_url)
            except Exception:  # noqa: BLE001 — sesja i tak wygaśnie po kilku dniach
                pass
            raise


# ── Odczyt ──────────────────────────────────────────────────────────────────


def _headers(file: TrainingFile, download: bool) -> dict[str, str]:
    mime = (
        (file.content_type or "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    disposition = "inline" if not download and mime in _INLINE_TYPES else "attachment"
    return {
        "Content-Disposition": content_disposition(file.file_name, disposition, "plik"),
        "Cache-Control": _CACHE_CONTROL,
        "Accept-Ranges": "bytes",
    }


async def stream(
    file: TrainingFile, *, range_header: Optional[str], download: bool
) -> Response:
    """Odpowiedź z plikiem, z obsługą ``Range`` (przewijanie nagrania).

    Dysk: ``FileResponse`` Starlette sam obsługuje ``Range``/``If-Range`` (206, 416,
    kilka zakresów) z nagłówków żądania, więc ``range_header`` dotyczy tylko
    SharePointa. SharePoint: ``downloadUrl`` elementu (to tam przekierowuje
    ``/content``) z przekazanym ``Range``, ciało strumieniowane bez buforowania.
    """
    headers = _headers(file, download)
    media_type = file.content_type or "application/octet-stream"
    if file.storage == "sharepoint":
        return await _stream_sharepoint(file, range_header, headers, media_type)
    try:
        path = local_path(file.storage_key)
    except FileNotFoundError:
        raise TrainingError(404, MISSING_MESSAGE, "file_missing") from None
    if not await anyio.to_thread.run_sync(path.is_file):
        raise TrainingError(404, MISSING_MESSAGE, "file_missing")
    return FileResponse(path, media_type=media_type, headers=headers)


async def _download_url(file: TrainingFile) -> str:
    try:
        async with sp.graph_client() as client:
            item = await client.get(
                f"/drives/{file.sp_drive_id}/items/{file.storage_key}",
                params={"$select": "id,@microsoft.graph.downloadUrl"},
            )
    except sp.SharePointNotConfigured:
        raise TrainingError(
            503,
            "SharePoint jest teraz niedostępny dla NEXUSA. Spróbuj później.",
            "sp_unavailable",
        ) from None
    except GraphRequestError as exc:
        logger.warning("trainings_sp: item lookup failed status=%s", exc.status)
        if exc.status == 404:
            raise TrainingError(404, MISSING_MESSAGE, "file_missing") from None
        raise TrainingError(
            502, "SharePoint nie oddał pliku. Spróbuj ponownie za chwilę.", "sp_error"
        ) from None
    url = item.get("@microsoft.graph.downloadUrl") if isinstance(item, dict) else None
    if not url:
        raise TrainingError(404, MISSING_MESSAGE, "file_missing")
    return str(url)


async def _stream_sharepoint(
    file: TrainingFile,
    range_header: Optional[str],
    headers: dict[str, str],
    media_type: str,
) -> Response:
    url = await _download_url(file)
    http = _http_client(_DOWNLOAD_TIMEOUT)
    # Bez kompresji po drodze: ``Content-Length`` i ``Content-Range`` muszą
    # zgadzać się z bajtami pliku, które oddajemy przeglądarce.
    request_headers = {"Accept-Encoding": "identity"}
    if range_header:
        request_headers["Range"] = range_header
    try:
        upstream = await http.send(
            http.build_request("GET", url, headers=request_headers), stream=True
        )
    except httpx.TransportError as exc:
        await http.aclose()
        logger.warning("trainings_sp: download failed (%s)", type(exc).__name__)
        raise TrainingError(
            502, "SharePoint nie oddał pliku. Spróbuj ponownie za chwilę.", "sp_error"
        ) from None

    status = upstream.status_code
    if status not in (200, 206, 416):
        await upstream.aclose()
        await http.aclose()
        logger.warning("trainings_sp: download status=%s", status)
        if status == 404:
            raise TrainingError(404, MISSING_MESSAGE, "file_missing")
        raise TrainingError(
            502, "SharePoint nie oddał pliku. Spróbuj ponownie za chwilę.", "sp_error"
        )
    for name in _PASSED_HEADERS:
        value = upstream.headers.get(name)
        if value:
            headers[name] = value
    if upstream.headers.get("content-encoding", "identity").lower() != "identity":
        # Mimo ``identity`` przyszło skompresowane: ``aiter_bytes`` rozpakuje
        # ciało, więc długość z nagłówka już się nie zgadza.
        headers.pop("content-length", None)

    async def body() -> AsyncIterable[bytes]:
        try:
            async for chunk in upstream.aiter_bytes(_STREAM_CHUNK):
                yield chunk
        finally:
            await upstream.aclose()
            await http.aclose()

    return StreamingResponse(
        body(), status_code=status, headers=headers, media_type=media_type
    )


# ── Usuwanie ────────────────────────────────────────────────────────────────


async def remove(file: TrainingFile) -> None:
    """Usunięcie pliku z magazynu — najlepszym wysiłkiem; błąd tylko w logu."""
    try:
        if file.storage == "sharepoint":
            if not file.sp_drive_id or not file.storage_key:
                return
            async with sp.graph_client() as client:
                await client.delete(
                    f"/drives/{file.sp_drive_id}/items/{file.storage_key}"
                )
            return
        path = local_path(file.storage_key)
        await anyio.to_thread.run_sync(_unlink, path)
    except GraphRequestError as exc:
        if exc.status != 404:
            logger.warning(
                "trainings_storage: remove failed id=%s status=%s", file.id, exc.status
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "trainings_storage: remove failed id=%s (%s)", file.id, type(exc).__name__
        )
