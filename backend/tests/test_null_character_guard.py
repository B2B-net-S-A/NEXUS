"""NullCharacterGuardMiddleware on raw ASGI: what it rejects and what it replays.

End-to-end coverage against PostgreSQL lives in test_search_query_validation.py;
these tests pin the edge cases without a database.
"""

import asyncio
import json

from app.core.null_character_guard import (
    NULL_CHARACTER_ERROR_TYPE,
    NullCharacterGuardMiddleware,
)


def _run(scope_overrides, chunks=(b"",), content_type=b"application/json"):
    """Run one request through the guard. Returns (app_calls, sent messages)."""
    headers = [] if content_type is None else [(b"content-type", content_type)]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/items",
        "query_string": b"",
        "headers": headers,
        **scope_overrides,
    }
    incoming = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    app_calls = []
    sent = []

    async def receive():
        if incoming:
            return incoming.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def app(app_scope, app_receive, app_send):
        body = b""
        while True:
            message = await app_receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        app_calls.append(body)
        await app_send({"type": "http.response.start", "status": 200, "headers": []})
        await app_send({"type": "http.response.body", "body": b"ok"})

    asyncio.run(NullCharacterGuardMiddleware(app)(scope, receive, send))
    return app_calls, sent


def _rejection(sent):
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 422
    return json.loads(sent[1]["body"])["detail"]


def test_clean_request_reaches_the_app_with_the_exact_body():
    body = json.dumps({"name": "Jan", "tags": ["Java", "SQL"]}).encode()
    app_calls, sent = _run({"query_string": b"q=Java&page=1"}, chunks=(body,))
    assert app_calls == [body]
    assert sent[0]["status"] == 200


def test_body_split_into_chunks_is_replayed_whole():
    body = json.dumps({"note": "x" * 5000}).encode()
    chunks = (body[:1000], body[1000:4000], body[4000:])
    app_calls, _ = _run({}, chunks=chunks)
    assert app_calls == [body]


def test_percent_encoded_nul_in_query_value_is_rejected():
    app_calls, sent = _run({"method": "GET", "query_string": b"q=Java&location=Warszawa%00"})
    assert app_calls == []
    assert _rejection(sent) == [
        {
            "type": NULL_CHARACTER_ERROR_TYPE,
            "loc": ["query", "location"],
            "msg": "Value must not contain the NUL character (U+0000)",
            "input": "Warszawa\x00",
        }
    ]


def test_nul_in_query_name_and_raw_byte_are_rejected():
    _, sent = _run({"method": "GET", "query_string": b"na%00me=1&q_all=Java\x00QA"})
    assert [error["loc"] for error in _rejection(sent)] == [
        ["query", "na\x00me"],
        ["query", "q_all"],
    ]


def test_double_encoded_nul_is_plain_text_and_passes():
    app_calls, sent = _run({"method": "GET", "query_string": b"q=%2500"})
    assert len(app_calls) == 1
    assert sent[0]["status"] == 200


def test_nul_in_decoded_path_is_rejected():
    app_calls, sent = _run({"method": "GET", "path": "/api/candidates/\x00"})
    assert app_calls == []
    assert _rejection(sent)[0]["loc"] == ["path"]


def test_nested_json_nul_reports_the_body_location():
    body = json.dumps(
        {"first_name": "Jan", "experience": [{"company": "ACME"}, {"company": "B2B\x00"}]}
    ).encode()
    app_calls, sent = _run({}, chunks=(body,))
    assert app_calls == []
    assert _rejection(sent) == [
        {
            "type": NULL_CHARACTER_ERROR_TYPE,
            "loc": ["body", "experience", 1, "company"],
            "msg": "Value must not contain the NUL character (U+0000)",
            "input": "B2B\x00",
        }
    ]


def test_nul_in_json_key_is_rejected():
    body = json.dumps({"bad\x00key": "value"}).encode()
    _, sent = _run({}, chunks=(body,))
    assert _rejection(sent)[0]["loc"] == ["body", "bad\x00key"]


def test_escaped_backslash_u0000_is_literal_text_and_passes():
    body = json.dumps({"note": "\\u0000 is how JSON writes NUL"}).encode()
    assert b"\\\\u0000" in body
    app_calls, _ = _run({}, chunks=(body,))
    assert app_calls == [body]


def test_json_body_without_content_type_is_inspected():
    body = json.dumps({"note": "a\x00b"}).encode()
    _, sent = _run({}, chunks=(body,), content_type=None)
    assert _rejection(sent)[0]["loc"] == ["body", "note"]


def test_utf16_json_body_is_inspected():
    body = json.dumps({"note": "a\x00b"}).encode("utf-16")
    _, sent = _run({}, chunks=(body,))
    assert _rejection(sent)[0]["loc"] == ["body", "note"]


def test_non_json_bodies_are_not_buffered_or_inspected():
    body = b"--boundary\r\n\x00\x00binary\r\n--boundary--"
    app_calls, sent = _run(
        {}, chunks=(body,), content_type=b"multipart/form-data; boundary=boundary"
    )
    assert app_calls == [body]
    assert sent[0]["status"] == 200


def test_malformed_json_is_left_to_fastapi():
    body = b'{"note": "\\u0000", broken'
    app_calls, sent = _run({}, chunks=(body,))
    assert app_calls == [body]
    assert sent[0]["status"] == 200


def test_error_list_and_echoed_input_are_bounded():
    body = json.dumps({"items": ["x" * 500 + "\x00"] * 50}).encode()
    _, sent = _run({}, chunks=(body,))
    errors = _rejection(sent)
    assert len(errors) == 20
    assert all(len(error["input"]) == 100 for error in errors)


def test_client_disconnect_mid_body_is_replayed_to_the_app():
    incoming = [
        {"type": "http.request", "body": b'{"note": "par', "more_body": True},
        {"type": "http.disconnect"},
    ]
    seen = []

    async def receive():
        return incoming.pop(0)

    async def app(scope, app_receive, send):
        seen.append(await app_receive())
        seen.append(await app_receive())

    scope = {"type": "http", "method": "POST", "path": "/", "query_string": b"", "headers": []}
    asyncio.run(NullCharacterGuardMiddleware(app)(scope, receive, None))
    assert seen == [
        {"type": "http.request", "body": b'{"note": "par', "more_body": True},
        {"type": "http.disconnect"},
    ]


def test_non_http_scopes_pass_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    for scope_type in ("websocket", "lifespan"):
        scope = {"type": scope_type, "query_string": b"token=%00", "path": "/\x00"}
        asyncio.run(NullCharacterGuardMiddleware(app)(scope, None, None))
    assert seen == ["websocket", "lifespan"]
