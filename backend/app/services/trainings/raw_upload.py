"""Duży plik szkolenia jako surowe ciało żądania, czytane dopiero po bramce.

Przegląd bezpieczeństwa 13.11.2026: przy ``UploadFile``/``File()`` FastAPI parsuje
multipart PRZED zależnościami trasy (sesja panelu, token pracownika), więc wywołanie
bez logowania mogło wysłać 2 GB, które serwer zapisywał na dysk, zanim odmówił.
Trasa bez parametrów formularza nie czyta ciała, dopóki handler nie sięgnie po
``request.stream()`` — a handler startuje dopiero po bramce. Nazwa pliku przychodzi
w nagłówku ``X-File-Name`` (zakodowana jak w adresie, bo nagłówek ma tylko ASCII).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator
from urllib.parse import unquote

from fastapi import Request

from app.services.trainings.errors import TrainingError

FILE_NAME_HEADER = "x-file-name"
NAME_MAX = 255


@dataclass(frozen=True)
class RawUpload:
    file_name: str
    content_type: str
    body: AsyncIterator[bytes]


def read(request: Request) -> RawUpload:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
    if content_type.lower().startswith("multipart/"):
        raise TrainingError(
            415,
            "Wyślij sam plik, bez formularza. Odśwież stronę i spróbuj ponownie.",
            "raw_body_expected",
        )
    name = unquote(request.headers.get(FILE_NAME_HEADER) or "").replace("\x00", "")
    name = name.replace("/", "_").replace("\\", "_").strip()[:NAME_MAX]
    if not name:
        raise TrainingError(422, "Brakuje nazwy pliku.", "file_name_required")
    return RawUpload(
        file_name=name,
        content_type=content_type or "application/octet-stream",
        body=request.stream(),
    )
