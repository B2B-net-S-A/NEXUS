"""Górny limit rozmiaru ciała żądania (audyt 22.09 r2, SEC-03 / CAND-03).

API nie stoi za Cloudflare, więc nic przed aplikacją nie tnie ciała żądania,
a publiczne formularze (kariera, `/apply`, podpis) przyjmują pliki
anonimowo. Handlery czytają pliki z limitem (``read(LIMIT + 1)``), ale
Starlette i tak przyjmował całe ciało multipart na dysk tymczasowy, a strażnik
NUL buforuje ciała JSON w pamięci — jedno żądanie z gigabajtem danych
zajmowało dysk albo RAM procesu, zanim cokolwiek odpowiedziało.

Czyste ASGI (wzorzec ``null_character_guard``): dla POST/PUT/PATCH/DELETE
``Content-Length`` ponad limit → 413 od razu, bez czytania ciała; bez
nagłówka (``Transfer-Encoding: chunked``) liczymy bajty w ``receive`` i po
przekroczeniu zwracamy 413, o ile odpowiedź jeszcze się nie zaczęła.
Middleware siedzi POD CORS, więc 413 dostaje nagłówki CORS (inaczej
przeglądarka pokazałaby „Network Error”).
"""

from __future__ import annotations

from typing import Mapping, Optional

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Metody, których ciało ktoś w aplikacji czyta. JEDNA stała dla limitu i dla
#: strażnika NUL (``null_character_guard`` ją importuje): strażnik buforuje
#: ciało DELETE w pamięci, więc DELETE poza limitem pozwalał anonimowo
#: wyczerpać pamięć jedynego procesu uvicorna (audyt 25.09.2026, runda 5).
#: GET/HEAD/OPTIONS zostają poza obiema — nikt ich ciała nie czyta, a uvicorn
#: wstrzymuje odczyt gniazda, gdy aplikacja nie odbiera danych.
REQUEST_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

REQUEST_BODY_TOO_LARGE = "request_body_too_large"


class RequestBodyTooLarge(HTTPException):
    """Rzucane z ``receive`` po przekroczeniu limitu.

    Podklasa ``HTTPException``: FastAPI przepuszcza ją z parsowania ciała bez
    zamiany na 400, a handler wyjątków odda 413 z nagłówkami CORS.
    """

    def __init__(self, limit_bytes: int) -> None:
        super().__init__(status_code=413, detail=_message(limit_bytes))
        self.limit_bytes = limit_bytes


def _message(limit_bytes: int) -> str:
    mb = max(1, limit_bytes // (1024 * 1024))
    return f"Żądanie jest za duże (limit {mb} MB). Zmniejsz plik i spróbuj ponownie."


def _declared_length(scope: Scope) -> Optional[int]:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodySizeLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int,
        path_limits: Optional[Mapping[str, int]] = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.path_limits = dict(path_limits or {})

    def _limit_for(self, path: str) -> int:
        return self.path_limits.get(path, self.max_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in REQUEST_BODY_METHODS:
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope.get("path", ""))
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await self._reject(scope, receive, send, limit)
            return

        received = 0
        overflow = False
        response_started = False
        replaced = False

        async def limited_receive() -> Message:
            nonlocal received, overflow
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    overflow = True
                    raise RequestBodyTooLarge(limit)
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started, replaced
            if replaced:
                return  # odpowiedź warstwy niżej zastąpiona przez 413
            if message["type"] == "http.response.start":
                if overflow:
                    # Warstwa niżej zamieniła przepełnienie na własny błąd
                    # (np. 400 „błąd parsowania ciała”) — mówimy prawdę: 413.
                    replaced = True
                    response_started = True
                    await self._reject(scope, receive, send, limit)
                    return
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(scope, receive, send, limit)
        except Exception:
            # Wyjątek z warstwy, która zamieniła przepełnienie na coś innego:
            # nadal odpowiadamy 413, jeśli to przepełnienie było przyczyną.
            if overflow and not response_started:
                await self._reject(scope, receive, send, limit)
                return
            raise

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": _message(limit), "code": REQUEST_BODY_TOO_LARGE},
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)
