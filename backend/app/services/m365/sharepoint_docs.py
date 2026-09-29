"""SharePoint app-only dla dokumentów kontraktów (ticket 9, 0402).

Osobna rejestracja „NEXUS Contract Documents” z ``Sites.Selected`` nadanym
WYŁĄCZNIE na witrynę z folderem „Umowy pracowników”. Nie dokładamy tego
uprawnienia do rejestracji poczty ani Teams: ``Sites.Selected`` jest
bezpieczne tylko wtedy, gdy aplikacja poza tą jedną witryną nie widzi nic,
a tamte rejestracje mają już szerszy dostęp do skrzynek i kalendarzy.

Transport: ``AppGraphClient`` (ten sam retry/throttle co reszta Graphu).
Błędy logujemy kodem HTTP albo klasą wyjątku — bez nazw plików i osób.
"""

from __future__ import annotations

import base64
import logging
import threading
from dataclasses import dataclass
from typing import AsyncIterator, Optional
from urllib.parse import quote, unquote, urlparse

import msal

from app.core.config import settings
from app.services.m365.app_graph_client import AppGraphClient
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

_SCOPE = ["https://graph.microsoft.com/.default"]
_ITEM_SELECT = "id,name,size,folder,file,cTag,eTag,parentReference,lastModifiedDateTime"
DEFAULT_FOLDER_NAME = "Umowy pracowników"

_lock = threading.Lock()
_app: Optional[msal.ConfidentialClientApplication] = None
_app_key: Optional[tuple[str, str, str]] = None


class SharePointNotConfigured(RuntimeError):
    """Brak poświadczeń rejestracji albo realnego tenanta."""


class SharePointFolderNotFound(RuntimeError):
    """Link nie prowadzi do folderu, do którego aplikacja ma dostęp."""


def _tenant() -> str:
    return settings.M365_MAIL_TENANT_ID or settings.M365_TENANT_ID


def credentials_configured() -> bool:
    tenant = _tenant()
    return bool(
        settings.CONTRACT_DOCS_SP_CLIENT_ID
        and settings.CONTRACT_DOCS_SP_CLIENT_SECRET
        and tenant
        and tenant != "common"
    )


def _msal_app() -> msal.ConfidentialClientApplication:
    global _app, _app_key
    key = (
        settings.CONTRACT_DOCS_SP_CLIENT_ID,
        settings.CONTRACT_DOCS_SP_CLIENT_SECRET,
        _tenant(),
    )
    with _lock:
        if _app is None or _app_key != key:
            _app = msal.ConfidentialClientApplication(
                client_id=settings.CONTRACT_DOCS_SP_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{_tenant()}",
                client_credential=settings.CONTRACT_DOCS_SP_CLIENT_SECRET,
            )
            _app_key = key
        return _app


def acquire_sharepoint_token(*, force_refresh: bool = False) -> Optional[str]:
    if not credentials_configured():
        return None
    app = _msal_app()
    if force_refresh:
        app.remove_tokens_for_client()
    result = app.acquire_token_for_client(scopes=_SCOPE)
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        logger.warning(
            "contract_docs_sp: token acquisition failed error=%s",
            (result or {}).get("error"),
        )
        return None
    return token


def graph_client() -> AppGraphClient:
    if not credentials_configured():
        raise SharePointNotConfigured("contract docs SharePoint app not configured")
    return AppGraphClient(token_provider=acquire_sharepoint_token)


@dataclass(frozen=True)
class DriveItem:
    id: str
    name: str
    is_folder: bool
    size: Optional[int]
    c_tag: Optional[str]
    drive_id: str

    @classmethod
    def of(cls, raw: dict, drive_id: str) -> "DriveItem":
        parent = raw.get("parentReference") or {}
        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name") or ""),
            is_folder="folder" in raw,
            size=raw.get("size"),
            c_tag=raw.get("cTag") or raw.get("eTag"),
            drive_id=str(parent.get("driveId") or drive_id),
        )


@dataclass(frozen=True)
class ResolvedFolder:
    drive_id: str
    item_id: str
    name: str


def share_token(url: str) -> str:
    """Kodowanie linku udostępnienia dla ``/shares/{token}`` (dokumentacja Graph)."""
    encoded = base64.urlsafe_b64encode(url.strip().encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=")


def parse_site_url(url: str) -> tuple[str, Optional[str], Optional[str]]:
    """(host, ścieżka witryny ``/sites/X``, ścieżka folderu w bibliotece albo None).

    Link udostępnienia (``/:f:/s/Share_B2B/<token>``) nie niesie ścieżki
    folderu — wtedy trzeci element to None i folder szukamy po nazwie.
    """
    parsed = urlparse(url.strip())
    host = parsed.netloc
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    site_path: Optional[str] = None
    folder_path: Optional[str] = None
    if len(parts) >= 3 and parts[0].startswith(":") and parts[1] in {"s", "sites"}:
        site_path = f"/sites/{parts[2]}"
    elif len(parts) >= 2 and parts[0] in {"sites", "teams"}:
        site_path = f"/{parts[0]}/{parts[1]}"
        rest = parts[2:]
        # „Shared Documents/…”, „Dokumenty udostępnione/…” — pierwszy segment
        # to biblioteka, reszta to ścieżka folderu w niej.
        if len(rest) >= 2:
            folder_path = "/".join(rest[1:])
    return host, site_path, folder_path


async def resolve_folder(
    client: AppGraphClient, url: str, *, folder_name: str = DEFAULT_FOLDER_NAME
) -> ResolvedFolder:
    """Link → folder. Najpierw ``/shares`` (działa przy szerszych uprawnieniach),
    potem witryna z adresu + ścieżka albo wyszukanie folderu po nazwie."""
    try:
        raw = await client.get(
            f"/shares/{share_token(url)}/driveItem", params={"$select": _ITEM_SELECT}
        )
        if "folder" in raw:
            parent = raw.get("parentReference") or {}
            return ResolvedFolder(
                str(parent["driveId"]), str(raw["id"]), raw.get("name", "")
            )
    except GraphRequestError as exc:
        # Przy `Sites.Selected` `/shares` odpowiada 403 — to oczekiwane.
        logger.info("contract_docs_sp: /shares unavailable status=%s", exc.status)

    host, site_path, folder_path = parse_site_url(url)
    if not host or not site_path:
        raise SharePointFolderNotFound("link bez witryny SharePoint")
    site = await client.get(f"/sites/{host}:{site_path}", params={"$select": "id"})
    drives = await client.get(
        f"/sites/{site['id']}/drives", params={"$select": "id,name"}
    )
    target = (folder_name or DEFAULT_FOLDER_NAME).strip().casefold()
    for drive in drives.get("value") or []:
        drive_id = str(drive["id"])
        if folder_path:
            try:
                raw = await client.get(
                    f"/drives/{drive_id}/root:/{quote(folder_path)}",
                    params={"$select": _ITEM_SELECT},
                )
            except GraphRequestError:
                continue
            if "folder" in raw:
                return ResolvedFolder(drive_id, str(raw["id"]), raw.get("name", ""))
            continue
        try:
            found = await client.get(
                f"/drives/{drive_id}/root/search(q='{quote(folder_name)}')",
                params={"$select": _ITEM_SELECT},
            )
        except GraphRequestError:
            continue
        for raw in found.get("value") or []:
            if (
                "folder" in raw
                and str(raw.get("name", "")).strip().casefold() == target
            ):
                return ResolvedFolder(drive_id, str(raw["id"]), raw.get("name", ""))
    raise SharePointFolderNotFound("folder nie znaleziony albo brak dostępu")


async def list_children(
    client: AppGraphClient, drive_id: str, item_id: str
) -> AsyncIterator[DriveItem]:
    async for page in client.paginate(
        f"/drives/{drive_id}/items/{item_id}/children",
        params={"$select": _ITEM_SELECT, "$top": "200"},
    ):
        for raw in page.get("value") or []:
            yield DriveItem.of(raw, drive_id)


@dataclass(frozen=True)
class PersonFile:
    folder: DriveItem  # podfolder osoby (pierwszy poziom)
    item: DriveItem
    relative_path: str  # ścieżka wewnątrz folderu osoby


@dataclass
class FolderListing:
    person_folders: list[DriveItem]
    files: list[PersonFile]
    loose_files: list[DriveItem]  # pliki luzem w folderze głównym


async def list_person_files(
    client: AppGraphClient, drive_id: str, root_item_id: str, *, max_depth: int = 6
) -> FolderListing:
    """Spis folderu: podfoldery pierwszego poziomu = osoby, pliki w nich
    (także w podkatalogach) należą do tej osoby."""
    listing = FolderListing(person_folders=[], files=[], loose_files=[])
    async for child in list_children(client, drive_id, root_item_id):
        if child.is_folder:
            listing.person_folders.append(child)
        else:
            listing.loose_files.append(child)
    for person in listing.person_folders:
        stack: list[tuple[str, str, int]] = [(person.id, "", 0)]
        while stack:
            item_id, prefix, depth = stack.pop()
            async for child in list_children(client, person.drive_id, item_id):
                path = f"{prefix}{child.name}"
                if child.is_folder:
                    if depth + 1 <= max_depth:
                        stack.append((child.id, f"{path}/", depth + 1))
                    continue
                listing.files.append(PersonFile(person, child, path))
    return listing


async def download(client: AppGraphClient, drive_id: str, item_id: str) -> bytes:
    return await client.download(f"/drives/{drive_id}/items/{item_id}/content")


async def ensure_person_folder(
    client: AppGraphClient, drive_id: str, root_item_id: str, name: str
) -> DriveItem:
    """Podfolder osoby — istniejący albo nowo założony."""
    try:
        raw = await client.post(
            f"/drives/{drive_id}/items/{root_item_id}/children",
            json={
                "name": name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            },
        )
        return DriveItem.of(raw, drive_id)
    except GraphRequestError as exc:
        if exc.status != 409:
            raise
    raw = await client.get(
        f"/drives/{drive_id}/items/{root_item_id}:/{quote(name)}",
        params={"$select": _ITEM_SELECT},
    )
    return DriveItem.of(raw, drive_id)


async def upload_file(
    client: AppGraphClient,
    drive_id: str,
    folder_item_id: str,
    filename: str,
    content: bytes,
    content_type: str | None,
) -> DriveItem:
    raw = await client.put_content(
        f"/drives/{drive_id}/items/{folder_item_id}:/{quote(filename)}:/content"
        "?@microsoft.graph.conflictBehavior=rename",
        content,
        content_type=content_type or "application/octet-stream",
    )
    return DriveItem.of(raw, drive_id)
