"""Zasiew testów e-teczki (etap 5, E4). Dane fikcyjne — repo jest publiczne.

* ``documents_on`` — wszystkie moduły „Ludzi” włączone, pusta tabela
  ``hr_documents`` i domyślne okresy przechowywania (przed i po teście),
* ``documents_store_root`` — magazyn plików w katalogu tymczasowym testu,
* ``documents_routes`` — trasy modułu w aplikacji testowej, dopóki koordynator
  nie wepnie ich w ``main.py``,
* pliki: najmniejszy PDF, PNG i DOCX (z makrem i bez) zbudowane w pamięci.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.hr_document import HrDocument
from app.services.hr_documents_schema import RETENTION_SETTING
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr_settlements_seed import set_setting

PREFIX = "/api/hr/documents"


def pdf_bytes(marker: str | None = None) -> bytes:
    """Najmniejszy PDF z unikalną treścią (inny skrót przy każdym wołaniu)."""

    tag = marker or uuid.uuid4().hex
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n% "
        + tag.encode()
        + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )


def png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes + b"\x00" * 16


def docx_bytes(*, macro: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml", f"<w:document>{uuid.uuid4().hex}</w:document>"
        )
        if macro:
            archive.writestr("word/vbaProject.bin", b"\x00\x01")
    return buffer.getvalue()


async def wipe_documents() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(HrDocument))
        await db.commit()


async def _modules_value():
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )


@pytest_asyncio.fixture
async def documents_on():
    previous = await _modules_value()
    await set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    await set_setting(RETENTION_SETTING, None)
    await wipe_documents()
    yield
    await wipe_documents()
    await set_setting(RETENTION_SETTING, None)
    await set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


@pytest_asyncio.fixture
async def documents_people_off():
    previous = await _modules_value()
    await set_setting(
        HR_MODULES_SETTING, {key: key != "people" for key in HR_MODULE_KEYS}
    )
    await wipe_documents()
    yield
    await wipe_documents()
    await set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


@pytest.fixture
def documents_store_root(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def documents_routes():
    from app.api import hr_documents
    from app.main import app

    before = list(app.router.routes)
    added = False
    if f"{PREFIX}/retention" not in {getattr(route, "path", "") for route in before}:
        app.include_router(hr_documents.router, prefix=PREFIX, tags=["hr"])
        added = True
    yield
    if added:
        app.router.routes[:] = before


__all__ = [
    "PREFIX",
    "docx_bytes",
    "documents_on",
    "documents_people_off",
    "documents_routes",
    "documents_store_root",
    "pdf_bytes",
    "png_bytes",
    "wipe_documents",
]
