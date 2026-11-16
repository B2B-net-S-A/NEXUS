"""Pliki szkoleń: typy, zapis na dysku z SHA-256, Range, sesja uploadu SharePointa.

Bez bazy: ``db`` to atrapa z ``get``/``add``/``flush``, Graph to atrapa klienta,
a ruch HTTP poza Graphem idzie przez ``httpx.MockTransport``.
"""

from __future__ import annotations

import hashlib
import io
import re
from types import SimpleNamespace
from typing import Any, Optional

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from app.services import storage_service
from app.services.m365 import sharepoint_docs as sp
from app.services.m365.graph_client import GraphRequestError
from app.services.trainings import storage
from app.services.trainings.errors import TrainingError

MP4 = "video/mp4"


class FakeDb:
    def __init__(self, value: Optional[dict] = None) -> None:
        self.row = SimpleNamespace(value=value) if value is not None else None
        self.added: list[Any] = []
        self.flushed = False

    async def get(self, model: Any, key: str) -> Any:
        assert key == storage.SETTINGS_KEY
        return self.row

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


SP_SETTINGS = {
    "share_url": "https://x.sharepoint.com/:f:/s/B2B/abc",
    "drive_id": "d1",
    "folder_id": "root1",
}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    return tmp_path


def _files(root) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# ── Typy plików ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "mime"),
    [
        ("Nagranie.MP4", MP4),
        ("prezentacja.pptx", storage.ALLOWED["pptx"]),
        ("audio.m4a", "audio/mp4"),
        ("audio.mp3", "audio/mpeg"),
        ("lista.csv", "text/csv"),
        ("zdjęcie.JPG", "image/jpeg"),
    ],
)
def test_allowed_types_come_from_extension(name, mime):
    assert storage.content_type_for(name) == mime


@pytest.mark.parametrize("name", ["montaz.drp", "projekt.prproj", "film.kdenlive"])
def test_editor_project_files_are_refused_with_clear_message(name):
    with pytest.raises(TrainingError) as caught:
        storage.content_type_for(name)
    assert caught.value.status == 422
    assert caught.value.code == "editor_project"
    assert caught.value.message == (
        "Pliki projektu montażowego nie są przyjmowane. Wgraj gotowy plik MP4 albo MP3."
    )


@pytest.mark.parametrize(
    "name", ["skrypt.exe", "strona.html", "bez_rozszerzenia", "obraz.svg", ""]
)
def test_other_types_are_refused(name):
    with pytest.raises(TrainingError) as caught:
        storage.content_type_for(name)
    assert (caught.value.status, caught.value.code) == (422, "file_type")


# ── Zapis lokalny ───────────────────────────────────────────────────────────


async def _save(db, source, *, name="Nagranie spotkania.mp4", **extra):
    return await storage.save(
        db,
        training_id=7,
        training_title="Cybersecurity w erze AI",
        session_year=2026,
        file_name=name,
        content_type="application/x-whatever",
        source=source,
        **extra,
    )


async def test_local_save_hashes_and_key_has_no_file_name(root):
    content = b"\x00\x01video" * 50_000
    stored = await _save(FakeDb(), io.BytesIO(content))

    assert stored.storage == "local"
    assert stored.sp_drive_id is None
    assert stored.size_bytes == len(content)
    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert stored.content_type == MP4  # z rozszerzenia, nie od przeglądarki
    assert re.fullmatch(r"trainings/7/files/[0-9a-f]{32}", stored.storage_key)
    assert "Nagranie" not in stored.storage_key
    assert (root / stored.storage_key).read_bytes() == content
    assert _files(root) == [stored.storage_key]  # bez pozostałości .part


async def test_local_save_accepts_path_upload_file_and_async_stream(
    root, tmp_path_factory
):
    from starlette.datastructures import UploadFile

    content = b"abc" * 1000
    spooled = tmp_path_factory.mktemp("spool") / "upload.bin"
    spooled.write_bytes(content)

    async def chunks():
        for start in range(0, len(content), 700):
            yield content[start : start + 700]

    upload = UploadFile(file=io.BytesIO(content), filename="x.pdf")
    for source in (spooled, str(spooled), upload, chunks()):
        stored = await _save(FakeDb(), source, name="materiały.pdf")
        assert stored.sha256 == hashlib.sha256(content).hexdigest()
        assert (root / stored.storage_key).read_bytes() == content


async def test_too_large_and_empty_files_leave_nothing_on_disk(root, monkeypatch):
    monkeypatch.setattr(storage, "MAX_BYTES", 10)
    with pytest.raises(TrainingError) as caught:
        await _save(FakeDb(), io.BytesIO(b"x" * 11))
    assert caught.value.status == 413
    with pytest.raises(TrainingError) as caught:
        await _save(FakeDb(), io.BytesIO(b""))
    assert (caught.value.status, caught.value.code) == (422, "file_empty")
    assert _files(root) == []


async def test_refused_type_is_checked_before_reading(root):
    class Exploding(io.RawIOBase):
        def read(self, *_):  # pragma: no cover - nie może zostać zawołane
            raise AssertionError("czytanie przed sprawdzeniem typu")

    with pytest.raises(TrainingError) as caught:
        await _save(FakeDb(), Exploding(), name="projekt.drp")
    assert caught.value.code == "editor_project"


# ── Odczyt lokalny z Range ──────────────────────────────────────────────────


def _local_client(file) -> TestClient:
    async def endpoint(request: Request):
        return await storage.stream(
            file,
            range_header=request.headers.get("range"),
            download=request.query_params.get("download") == "1",
        )

    return TestClient(Starlette(routes=[Route("/f", endpoint)]))


def _local_file(root, content: bytes, *, name="Nagranie ł.mp4", mime=MP4):
    path = root / "trainings" / "7" / "files" / "abc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return SimpleNamespace(
        id=1,
        storage="local",
        storage_key="trainings/7/files/abc",
        sp_drive_id=None,
        file_name=name,
        content_type=mime,
    )


def test_local_stream_full_and_range_responses(root):
    content = bytes(range(100))
    client = _local_client(_local_file(root, content))

    full = client.get("/f")
    assert full.status_code == 200
    assert full.content == content
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["cache-control"] == "private, no-store"
    assert full.headers["content-disposition"].startswith("inline;")
    assert (
        "filename*=UTF-8''Nagranie%20%C5%82.mp4" in full.headers["content-disposition"]
    )

    part = client.get("/f", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == content[10:20]
    assert part.headers["content-range"] == "bytes 10-19/100"
    assert part.headers["content-length"] == "10"

    tail = client.get("/f", headers={"Range": "bytes=90-"})
    assert tail.status_code == 206
    assert tail.content == content[90:]

    beyond = client.get("/f", headers={"Range": "bytes=500-600"})
    assert beyond.status_code == 416
    assert beyond.headers["content-range"] == "bytes */100"


def test_download_and_unsafe_types_are_attachments(root):
    client = _local_client(_local_file(root, b"x" * 10))
    assert (
        client.get("/f?download=1")
        .headers["content-disposition"]
        .startswith("attachment;")
    )

    pptx = _local_client(
        _local_file(root, b"x" * 10, name="a.pptx", mime=storage.ALLOWED["pptx"])
    )
    assert pptx.get("/f").headers["content-disposition"].startswith("attachment;")


async def test_missing_or_escaping_local_file_is_404(root):
    for key in ("trainings/7/files/missing", "../../etc/passwd", "contracts/1.pdf"):
        file = SimpleNamespace(
            id=1,
            storage="local",
            storage_key=key,
            sp_drive_id=None,
            file_name="a.mp4",
            content_type=MP4,
        )
        with pytest.raises(TrainingError) as caught:
            await storage.stream(file, range_header=None, download=False)
        assert (caught.value.status, caught.value.code) == (404, "file_missing")


async def test_remove_local_file_is_best_effort(root):
    file = _local_file(root, b"abc")
    await storage.remove(file)
    assert _files(root) == []
    await storage.remove(file)  # drugi raz: brak pliku nie jest błędem
    file.storage_key = "../outside"
    await storage.remove(file)  # poza katalogiem: tylko log


# ── SharePoint ──────────────────────────────────────────────────────────────


class FakeGraph:
    def __init__(
        self, *, item: Optional[dict] = None, fail_session: bool = False
    ) -> None:
        self.posts: list[tuple[str, Any]] = []
        self.gets: list[tuple[str, Any]] = []
        self.deletes: list[str] = []
        self.item = item
        self.fail_session = fail_session

    async def __aenter__(self) -> "FakeGraph":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(self, url: str, json: Any = None, **_: Any) -> Any:
        self.posts.append((url, json))
        if url.endswith("/createUploadSession"):
            if self.fail_session:
                raise GraphRequestError(403, "denied")
            return {"uploadUrl": "https://upload.example/session/1"}
        return {
            "id": f"folder-{json['name']}",
            "name": json["name"],
            "folder": {},
            "parentReference": {"driveId": "d1"},
        }

    async def get(self, url: str, params: Any = None) -> Any:
        self.gets.append((url, params))
        if self.item is None:
            raise GraphRequestError(404, "missing")
        return self.item

    async def delete(self, url: str) -> None:
        self.deletes.append(url)


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(sp, "credentials_configured", lambda: True)
    monkeypatch.setattr(sp, "graph_client", lambda: fake)
    return fake


def _mock_http(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        storage,
        "_http_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_sharepoint_upload_goes_in_chunks_and_removes_local_copy(
    root, graph, monkeypatch
):
    monkeypatch.setattr(storage, "_UPLOAD_CHUNK", 4)
    content = b"0123456789"
    received = bytearray()
    ranges: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert "authorization" not in request.headers
        ranges.append(request.headers["content-range"])
        received.extend(request.content)
        if len(received) < len(content):
            return httpx.Response(
                202, json={"nextExpectedRanges": [f"{len(received)}-"]}
            )
        return httpx.Response(
            201, json={"id": "item-9", "parentReference": {"driveId": "d1"}}
        )

    _mock_http(monkeypatch, handler)
    stored = await storage.save(
        FakeDb(SP_SETTINGS),
        training_id=12,
        training_title="B2B Tech Sessions #01 | Cybersecurity: AI?",
        session_year=2026,
        file_name="nagranie: część 1.mp4",
        content_type=MP4,
        source=io.BytesIO(content),
    )

    assert ranges == ["bytes 0-3/10", "bytes 4-7/10", "bytes 8-9/10"]
    assert bytes(received) == content
    assert stored.storage == "sharepoint"
    assert stored.storage_key == "item-9"
    assert stored.sp_drive_id == "d1"
    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert _files(root) == []  # kopia tymczasowa usunięta

    folders = [body["name"] for url, body in graph.posts if url.endswith("/children")]
    assert folders == ["2026", "12 B2B Tech Sessions 01 Cybersecurity AI"]
    session_url, session_body = graph.posts[-1]
    assert session_url == (
        "/drives/d1/items/folder-12 B2B Tech Sessions 01 Cybersecurity AI:/"
        "nagranie%20cz%C4%99%C5%9B%C4%87%201.mp4:/createUploadSession"
    )
    assert session_body == {"item": {"@microsoft.graph.conflictBehavior": "rename"}}


async def test_sharepoint_upload_resumes_after_lost_response(root, graph, monkeypatch):
    monkeypatch.setattr(storage, "_UPLOAD_CHUNK", 4)
    monkeypatch.setattr(storage, "_UPLOAD_RETRY_DELAY", 0)
    content = b"abcdefgh"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            f"{request.method} {request.headers.get('content-range', '')}".strip()
        )
        if request.method == "GET":
            return httpx.Response(200, json={"nextExpectedRanges": ["4-"]})
        if len(calls) == 2:
            # Drugi kawałek doszedł do SharePointa, a odpowiedź zginęła — wysyłka od 4 jest prawidłowa.
            raise httpx.ReadError("lost")
        if request.headers["content-range"] == "bytes 4-7/8":
            return httpx.Response(201, json={"id": "item-1"})
        return httpx.Response(202, json={"nextExpectedRanges": ["4-"]})

    _mock_http(monkeypatch, handler)
    stored = await storage.save(
        FakeDb(SP_SETTINGS),
        training_id=1,
        training_title="T",
        session_year=2026,
        file_name="a.mp3",
        content_type="audio/mpeg",
        source=io.BytesIO(content),
    )
    assert calls == ["PUT bytes 0-3/8", "PUT bytes 4-7/8", "GET", "PUT bytes 4-7/8"]
    assert stored.storage == "sharepoint"


async def test_sharepoint_failure_keeps_file_locally(root, monkeypatch):
    fake = FakeGraph(fail_session=True)
    monkeypatch.setattr(sp, "credentials_configured", lambda: True)
    monkeypatch.setattr(sp, "graph_client", lambda: fake)
    stored = await _save(FakeDb(SP_SETTINGS), io.BytesIO(b"data"))
    assert stored.storage == "local"
    assert (root / stored.storage_key).read_bytes() == b"data"


async def test_without_credentials_settings_do_not_send_to_sharepoint(
    root, monkeypatch
):
    monkeypatch.setattr(sp, "credentials_configured", lambda: False)
    assert (
        storage.sharepoint_ready(await storage.load_settings(FakeDb(SP_SETTINGS)))
        is False
    )
    stored = await _save(FakeDb(SP_SETTINGS), io.BytesIO(b"data"))
    assert stored.storage == "local"


async def test_save_settings_needs_credentials_and_resolves_link(monkeypatch):
    monkeypatch.setattr(sp, "credentials_configured", lambda: False)
    with pytest.raises(TrainingError) as caught:
        await storage.save_settings(FakeDb(), "https://x.sharepoint.com/:f:/s/B2B/abc")
    assert (caught.value.status, caught.value.code) == (409, "sp_not_configured")

    with pytest.raises(TrainingError) as caught:
        await storage.save_settings(FakeDb(), "nie link")
    assert caught.value.status == 422

    fake = FakeGraph()
    monkeypatch.setattr(sp, "credentials_configured", lambda: True)
    monkeypatch.setattr(sp, "graph_client", lambda: fake)

    async def not_found(client, url, *, folder_name):
        raise sp.SharePointFolderNotFound("x")

    monkeypatch.setattr(sp, "resolve_folder", not_found)
    with pytest.raises(TrainingError) as caught:
        await storage.save_settings(FakeDb(), "https://x.sharepoint.com/:f:/s/B2B/abc")
    assert (caught.value.status, caught.value.code) == (422, "sp_folder_not_found")

    async def found(client, url, *, folder_name):
        return sp.ResolvedFolder("drive-x", "folder-x", folder_name)

    monkeypatch.setattr(sp, "resolve_folder", found)
    db = FakeDb()
    target = await storage.save_settings(
        db, " https://x.sharepoint.com/:f:/s/B2B/abc ", user_id=5
    )
    assert target == storage.SpTarget(
        "https://x.sharepoint.com/:f:/s/B2B/abc", "drive-x", "folder-x"
    )
    assert db.added[0].value == {
        "share_url": "https://x.sharepoint.com/:f:/s/B2B/abc",
        "drive_id": "drive-x",
        "folder_id": "folder-x",
    }
    assert db.flushed
    assert storage.sharepoint_ready(target)


def _sp_file(**extra: Any) -> SimpleNamespace:
    base = dict(
        id=3,
        storage="sharepoint",
        storage_key="item-9",
        sp_drive_id="d1",
        file_name="Nagranie.mp4",
        content_type=MP4,
    )
    base.update(extra)
    return SimpleNamespace(**base)


async def _body(response) -> bytes:
    out = bytearray()
    async for chunk in response.body_iterator:
        out.extend(chunk)
    return bytes(out)


async def test_sharepoint_stream_passes_range_and_streams_body(graph, monkeypatch):
    graph.item = {
        "id": "item-9",
        "@microsoft.graph.downloadUrl": "https://dl.example/file?tempauth=x",
    }
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(
            206,
            content=b"4567",
            headers={
                "Content-Range": "bytes 4-7/10",
                "Content-Length": "4",
                "Content-Type": "application/octet-stream",
            },
        )

    _mock_http(monkeypatch, handler)
    response = await storage.stream(_sp_file(), range_header="bytes=4-7", download=True)

    assert graph.gets == [
        ("/drives/d1/items/item-9", {"$select": "id,@microsoft.graph.downloadUrl"})
    ]
    assert seen["url"] == "https://dl.example/file?tempauth=x"
    assert seen["headers"]["range"] == "bytes=4-7"
    assert seen["headers"]["accept-encoding"] == "identity"
    assert "authorization" not in seen["headers"]
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 4-7/10"
    assert response.headers["content-length"] == "4"
    assert response.headers["content-type"] == MP4
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert await _body(response) == b"4567"


async def test_sharepoint_stream_without_range_and_missing_item(graph, monkeypatch):
    graph.item = {
        "id": "item-9",
        "@microsoft.graph.downloadUrl": "https://dl.example/f",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "range" not in request.headers
        return httpx.Response(200, content=b"whole")

    _mock_http(monkeypatch, handler)
    response = await storage.stream(_sp_file(), range_header=None, download=False)
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("inline;")
    assert await _body(response) == b"whole"

    graph.item = None
    with pytest.raises(TrainingError) as caught:
        await storage.stream(_sp_file(), range_header=None, download=False)
    assert (caught.value.status, caught.value.code) == (404, "file_missing")


async def test_remove_sharepoint_item(graph):
    await storage.remove(_sp_file())
    assert graph.deletes == ["/drives/d1/items/item-9"]
