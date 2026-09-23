"""SEC-03 / CAND-03 (audyt 22.09 r2): limit ciała żądania przed handlerem."""

from __future__ import annotations

import json

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.body_size_limit import BodySizeLimitMiddleware


async def test_oversized_body_gets_413_with_cors_headers(app_client):
    from app.core.config import settings

    origin = settings.CORS_ORIGINS[0]
    body = b"x" * (settings.MAX_REQUEST_BODY_MB * 1024 * 1024 + 1024)
    response = await app_client.post(
        "/api/public/career/apply",
        content=body,
        headers={"Origin": origin, "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413, response.text[:200]
    assert response.json()["code"] == "request_body_too_large"
    # Bez nagłówków CORS przeglądarka pokazałaby „Network Error”.
    assert response.headers["access-control-allow-origin"] == origin


def test_body_limit_sits_under_cors_and_over_the_nul_guard():
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.null_character_guard import NullCharacterGuardMiddleware
    from app.main import app

    order = [middleware.cls for middleware in app.user_middleware]  # outermost first
    assert (
        order.index(CORSMiddleware)
        < order.index(BodySizeLimitMiddleware)
        < order.index(NullCharacterGuardMiddleware)
    )


async def _echo_app(scope, receive, send):
    request = Request(scope, receive)
    body = await request.body()
    await JSONResponse({"size": len(body)})(scope, receive, send)


async def _run(app, *, method="POST", path="/x", headers=(), chunks=(b"",)):
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    sent: list[dict] = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": list(headers),
        "query_string": b"",
    }
    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return status, body


@pytest.mark.asyncio
async def test_declared_length_over_limit_is_rejected_without_reading():
    app = BodySizeLimitMiddleware(_echo_app, max_bytes=10)
    status, body = await _run(
        app, headers=[(b"content-length", b"11")], chunks=(b"x" * 11,)
    )
    assert status == 413
    assert json.loads(body)["code"] == "request_body_too_large"


@pytest.mark.asyncio
async def test_chunked_body_over_limit_is_rejected():
    app = BodySizeLimitMiddleware(_echo_app, max_bytes=10)
    status, _ = await _run(app, chunks=(b"x" * 6, b"x" * 6))
    assert status == 413


@pytest.mark.asyncio
async def test_small_body_and_get_pass_through():
    app = BodySizeLimitMiddleware(_echo_app, max_bytes=10)
    status, body = await _run(app, chunks=(b"x" * 4, b"x" * 4))
    assert status == 200 and json.loads(body)["size"] == 8
    status, _ = await _run(app, method="GET", chunks=(b"x" * 50,))
    assert status == 200


@pytest.mark.asyncio
async def test_path_override_raises_the_ceiling():
    app = BodySizeLimitMiddleware(_echo_app, max_bytes=10, path_limits={"/big": 100})
    status, _ = await _run(
        app, path="/big", headers=[(b"content-length", b"50")], chunks=(b"x" * 50,)
    )
    assert status == 200


@pytest.mark.asyncio
async def test_chunked_multipart_upload_over_limit_is_413_not_400():
    """Parser formularza FastAPI nie może zamienić przepełnienia na 400."""
    from fastapi import FastAPI, File, UploadFile

    inner = FastAPI()

    @inner.post("/upload")
    async def upload(file: UploadFile = File(...)):
        return {"size": len(await file.read(1000))}

    app = BodySizeLimitMiddleware(inner, max_bytes=200)
    boundary = b"xyz"
    body = (
        b'--xyz\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n" + b"x" * 500 + b"\r\n--xyz--\r\n"
    )
    chunks = tuple(body[i : i + 64] for i in range(0, len(body), 64))
    status, payload = await _run(
        app,
        path="/upload",
        headers=[(b"content-type", b"multipart/form-data; boundary=" + boundary)],
        chunks=chunks,
    )
    assert status == 413
    assert json.loads(payload)["code"] == "request_body_too_large"
