"""Odczyty CV z podglądu w tabeli `cv_preview_reads` (`services/cv_preview_cache.py`).

Do 24.11.2026 pamięć procesu: przy dwóch procesach web `/from-cv` w drugim procesie
czytał CV modelem jeszcze raz. Tu: drugi proces Pythona widzi zapis, najwyżej N
wierszy (najdawniej użyty wypada), TTL i sprzątanie wygasłych, zbyt długi tekst nie
jest trzymany, pierwszy zapis wygrywa, treść da się odczytać tylko z plikiem w ręku,
awaria tabeli to brak wpisu (nie błąd), lustro DDL w migracji i `entrypoint.sh`.

Każdy test wgrywa własne bajty (uuid), bo wiersze żyją w bazie do 30 min.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.cv_preview_read import CvPreviewRead
from app.services import cv_preview_cache
from app.services.cv_preview_cache import content_sha256
from app.services.cv_preview_reads_schema import TABLE_DDL

BACKEND = Path(__file__).resolve().parents[1]


def _content(tag: str) -> bytes:
    return f"%PDF-1.4 {tag} {uuid.uuid4().hex}".encode()


async def _payload(content: bytes):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text("SELECT payload FROM cv_preview_reads WHERE sha256 = :sha256"),
            {"sha256": content_sha256(content)},
        )


async def _expire(content: bytes) -> None:
    """Wiersz jak po 30 minutach (czas liczy baza, więc przesuwamy `expires_at`)."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE cv_preview_reads SET expires_at = now() - INTERVAL '1 second' "
                "WHERE sha256 = :sha256"
            ),
            {"sha256": content_sha256(content)},
        )
        await db.commit()


# ── drugi proces ──────────────────────────────────────────────────────────────

_SECOND_PROCESS = """
import asyncio, json, sys

from app.core.database import engine
from app.services import cv_preview_cache


async def main():
    read = await cv_preview_cache.recall(bytes.fromhex(sys.argv[1]))
    await engine.dispose()
    body = None if read is None else {"parsed": read.parsed, "raw_text": read.raw_text}
    print("READ=" + json.dumps(body))


asyncio.run(main())
"""


async def _read_in_another_process(content: bytes):
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _SECOND_PROCESS,
        content.hex(),
        cwd=str(BACKEND),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    assert proc.returncode == 0, err.decode("utf-8", "replace")[-3000:]
    lines = [line for line in out.decode().splitlines() if line.startswith("READ=")]
    assert lines, out.decode("utf-8", "replace")[-3000:]
    return json.loads(lines[-1][len("READ=") :])


async def test_read_saved_in_one_process_is_read_by_another_python_process() -> None:
    content = _content("procesy")
    parsed = {"first_name": "Druga", "skills": [{"name": "Python"}], "_source": "t"}
    stored = await cv_preview_cache.remember(content, parsed=parsed, raw_text="Tekst")
    assert stored is not None and stored.parsed == parsed

    assert await _read_in_another_process(content) == {
        "parsed": parsed,
        "raw_text": "Tekst",
    }
    # Inny plik: drugi proces nie dostaje cudzego odczytu.
    assert await _read_in_another_process(_content("inny")) is None


# ── limity ────────────────────────────────────────────────────────────────────


async def test_inserting_more_than_max_evicts_the_least_recently_used(
    monkeypatch,
) -> None:
    monkeypatch.setattr(cv_preview_cache, "MAX_ENTRIES", 2)
    first, second, third = _content("a"), _content("b"), _content("c")
    await cv_preview_cache.remember(first, parsed={"i": 1}, raw_text="x")
    await cv_preview_cache.remember(second, parsed={"i": 2}, raw_text="x")
    assert (await cv_preview_cache.recall(first)).parsed == {"i": 1}  # najświeższy

    await cv_preview_cache.remember(third, parsed={"i": 3}, raw_text="x")

    assert await _payload(second) is None
    assert (await cv_preview_cache.recall(first)).parsed == {"i": 1}
    assert (await cv_preview_cache.recall(third)).parsed == {"i": 3}


async def test_expired_row_is_a_miss_and_is_swept() -> None:
    content = _content("ttl")
    await cv_preview_cache.remember(content, parsed={"i": 1}, raw_text="x")
    await _expire(content)

    assert await cv_preview_cache.recall(content) is None
    assert await _payload(content) is None


async def test_other_expired_rows_are_swept_on_write() -> None:
    old, new = _content("stary"), _content("nowy")
    await cv_preview_cache.remember(old, parsed={}, raw_text="x")
    await _expire(old)

    await cv_preview_cache.remember(new, parsed={}, raw_text="x")

    assert await _payload(old) is None
    assert await _payload(new) is not None


async def test_long_raw_text_is_not_kept_but_the_parse_is(monkeypatch) -> None:
    monkeypatch.setattr(cv_preview_cache, "MAX_RAW_TEXT_CHARS", 10)
    long, short = _content("długi"), _content("krótki")
    await cv_preview_cache.remember(
        long, parsed={"first_name": "Anna"}, raw_text="x" * 11
    )
    await cv_preview_cache.remember(short, parsed={}, raw_text="krótki")

    read = await cv_preview_cache.recall(long)
    assert read.raw_text is None
    assert read.parsed == {"first_name": "Anna"}
    assert (await cv_preview_cache.recall(short)).raw_text == "krótki"


async def test_disabled_ttl_stores_nothing(monkeypatch) -> None:
    monkeypatch.setattr(cv_preview_cache, "TTL_SECONDS", 0)
    content = _content("wyłączone")
    assert await cv_preview_cache.remember(content, parsed={}, raw_text="x") is None
    assert await _payload(content) is None


# ── jeden odczyt na plik ──────────────────────────────────────────────────────


async def test_first_read_wins_while_the_row_is_alive() -> None:
    """Drugi proces bez wspólnej blokady przeczytał ten sam plik inaczej.

    Podgląd ma pokazać odczyt z tabeli, bo ten zapisze `/from-cv`.
    """
    content = _content("pierwszy")
    first = await cv_preview_cache.remember(content, parsed={"r": 1}, raw_text="x")
    second = await cv_preview_cache.remember(content, parsed={"r": 2}, raw_text="y")

    assert first.parsed == second.parsed == {"r": 1}
    assert (await cv_preview_cache.recall(content)).parsed == {"r": 1}

    await _expire(content)
    fresh = await cv_preview_cache.remember(content, parsed={"r": 2}, raw_text="y")
    assert fresh.parsed == {"r": 2}
    assert (await cv_preview_cache.recall(content)).raw_text == "y"


async def test_unreadable_live_row_is_replaced() -> None:
    content = _content("zepsuty")
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO cv_preview_reads (sha256, payload, expires_at) "
                "VALUES (:sha256, :payload, now() + INTERVAL '10 minutes')"
            ),
            {"sha256": content_sha256(content), "payload": b"nie-fernet"},
        )
        await db.commit()

    assert await cv_preview_cache.recall(content) is None
    stored = await cv_preview_cache.remember(content, parsed={"r": 1}, raw_text="x")
    assert stored.parsed == {"r": 1}
    assert (await cv_preview_cache.recall(content)).parsed == {"r": 1}


async def test_forget_deletes_the_row() -> None:
    content = _content("zapisany")
    await cv_preview_cache.remember(content, parsed={}, raw_text="x")
    await cv_preview_cache.forget(content)
    assert await _payload(content) is None
    assert await cv_preview_cache.recall(content) is None


# ── dane osobowe ──────────────────────────────────────────────────────────────


async def test_row_is_unreadable_without_the_file() -> None:
    """Kopia bazy, staging z kopii i odczyt produkcji nie widzą treści CV."""
    content = _content("rodo")
    marker = f"anna.{uuid.uuid4().hex[:8]}@example.com"
    await cv_preview_cache.remember(
        content, parsed={"email": marker}, raw_text=f"CV, kontakt {marker}"
    )

    payload = bytes(await _payload(content))
    assert marker.encode() not in payload
    with pytest.raises(InvalidToken):
        cv_preview_cache._cipher(_content("inny plik")).decrypt(payload)
    # Klucz wiersza (SHA-256 pliku, jawny w tabeli) to nie klucz szyfrowania.
    with pytest.raises(InvalidToken):
        cv_preview_cache._cipher(content_sha256(content).encode()).decrypt(payload)


async def test_table_failure_is_a_miss_not_an_error(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=cv_preview_cache.__name__)

    class _Broken:
        async def __aenter__(self):
            raise ConnectionRefusedError("baza leży")

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(cv_preview_cache, "AsyncSessionLocal", lambda: _Broken())
    content = _content("awaria")
    secret = "Tajne CV kandydata"

    assert await cv_preview_cache.recall(content) is None
    assert (
        await cv_preview_cache.remember(content, parsed={"x": secret}, raw_text=secret)
        is None
    )
    await cv_preview_cache.forget(content)
    assert "ConnectionRefusedError" in caplog.text
    assert secret not in caplog.text


async def test_read_outside_json_is_not_stored(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=cv_preview_cache.__name__)
    content = _content("zbiór")
    stored = await cv_preview_cache.remember(
        content, parsed={"skills": {"Python"}}, raw_text="x"
    )
    assert stored is None
    assert await _payload(content) is None
    assert "Python" not in caplog.text


# ── lustro schematu ───────────────────────────────────────────────────────────


def test_schema_has_one_source_and_a_mirror() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import cv_preview_reads_schema" in entrypoint
    assert "*_CV_PREVIEW_READS_DDL," in entrypoint
    (migration,) = (BACKEND / "alembic" / "versions").glob("*_cv_preview_reads.py")
    source = migration.read_text(encoding="utf-8")
    assert "from app.services.cv_preview_reads_schema import TABLE_DDL" in source


def test_deep_health_probes_the_table() -> None:
    """Brak tabeli nic nie wywraca, tylko cicho wraca drugi odczyt modelem."""
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.models.cv_preview_read import CvPreviewRead" in main
    assert '("cv_preview_reads", CvPreviewRead),' in main


def test_model_columns_match_the_ddl() -> None:
    columns = {
        line.split()[0]
        for line in TABLE_DDL[0].splitlines()[1:]
        if line.split()[0] != ")"
    }
    assert columns == set(CvPreviewRead.__table__.columns.keys())


def test_table_holds_only_the_agreed_columns() -> None:
    """Jawny tekst albo id kandydata w tej tabeli to nowa decyzja, nie dopisek."""
    assert set(CvPreviewRead.__table__.columns.keys()) == {
        "sha256",
        "payload",
        "expires_at",
        "used_at",
    }
