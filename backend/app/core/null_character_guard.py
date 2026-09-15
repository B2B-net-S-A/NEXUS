"""Reject NUL (U+0000) in a request before any of it can reach PostgreSQL.

PostgreSQL cannot store NUL in ``text`` or ``jsonb``. asyncpg raises
``CharacterNotInRepertoireError`` („invalid byte sequence for encoding "UTF8":
0x00"), which surfaced as HTTP 500 on every parameter bound into SQL:
Schemathesis found ``q`` (#1549), and ``location`` plus the advanced-search
phrases on ``/api/candidates`` failed the same way. One guard replaces a
``pattern=`` on every parameter. The 422 uses FastAPI's validation-error shape
(``detail: [{type, loc, msg, input}]``), so the frontend's ``extractErrorMsg``
shows it like any other validation error.

Covered: the query string (names and values, after ``%00`` is decoded), the
path (already decoded by the server), and ``application/json`` / ``+json``
bodies — plus bodies without a Content-Type, which FastAPI also parses as
JSON — on POST, PUT, PATCH and DELETE. Valid JSON can carry NUL only as the
``\\u0000`` escape (or as UTF-16/32 bytes), so a clean body costs one byte
scan and is never parsed here.

Not covered: multipart and urlencoded form bodies (buffering uploads here
would be worse than the gap), headers, and WebSocket or lifespan scopes,
which pass through untouched.
"""

import json
from itertools import islice
from typing import Any, Iterator, Union
from urllib.parse import parse_qsl

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NULL_CHARACTER_ERROR_TYPE = "null_character"

_NUL = "\x00"
_MESSAGE = "Value must not contain the NUL character (U+0000)"
_MAX_ERRORS = 20
_MAX_INPUT_CHARS = 100
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

Loc = list[Union[str, int]]


def _error(loc: Loc, value: str) -> dict[str, Any]:
    return {
        "type": NULL_CHARACTER_ERROR_TYPE,
        "loc": loc,
        "msg": _MESSAGE,
        "input": value[:_MAX_INPUT_CHARS],
    }


def _query_errors(query_string: bytes) -> list[dict[str, Any]]:
    if b"%00" not in query_string and b"\x00" not in query_string:
        return []
    # Same decoding as Starlette's QueryParams, so a NUL found here is exactly
    # the NUL a handler would receive.
    pairs = parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
    return [
        _error(["query", name], value)
        for name, value in pairs
        if _NUL in name or _NUL in value
    ][:_MAX_ERRORS]


def _json_errors(document: Any) -> Iterator[dict[str, Any]]:
    # Iterative walk: a deeply nested body must not hit the recursion limit.
    stack: list[tuple[Loc, Any]] = [(["body"], document)]
    while stack:
        loc, value = stack.pop()
        if isinstance(value, str):
            if _NUL in value:
                yield _error(loc, value)
        elif isinstance(value, dict):
            for key, item in reversed(list(value.items())):
                stack.append(([*loc, key], item))
                if _NUL in key:
                    stack.append(([*loc, key], key))
        elif isinstance(value, list):
            for index in range(len(value) - 1, -1, -1):
                stack.append(([*loc, index], value[index]))


def _body_may_be_json(scope: Scope) -> bool:
    if scope.get("method") not in _BODY_METHODS:
        return False
    for name, value in scope.get("headers", []):
        if name == b"content-type":
            media_type = value.split(b";", 1)[0].strip().lower()
            return media_type == b"application/json" or media_type.endswith(b"+json")
    return True


class NullCharacterGuardMiddleware:
    """Pure ASGI, so streaming responses and non-JSON bodies are untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        errors = _query_errors(scope.get("query_string", b""))
        path = scope.get("path", "")
        if _NUL in path:
            errors.append(_error(["path"], path))
        if errors:
            await self._reject(scope, receive, send, errors)
            return

        if not _body_may_be_json(scope):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        trailing: list[Message] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                trailing.append(message)
                break
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        payload = bytes(body)
        del body

        if not trailing and (b"\\u0000" in payload or b"\x00" in payload):
            try:
                document = json.loads(payload)
            except (ValueError, RecursionError):
                # Not JSON after all: FastAPI answers malformed bodies itself.
                pass
            else:
                errors = list(islice(_json_errors(document), _MAX_ERRORS))
                if errors:
                    await self._reject(scope, receive, send, errors)
                    return

        replay: list[Message] = [
            {"type": "http.request", "body": payload, "more_body": bool(trailing)},
            *trailing,
        ]

        async def replay_receive() -> Message:
            if replay:
                return replay.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(
        scope: Scope, receive: Receive, send: Send, errors: list[dict[str, Any]]
    ) -> None:
        response = JSONResponse(status_code=422, content={"detail": errors})
        await response(scope, receive, send)
