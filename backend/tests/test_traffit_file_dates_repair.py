"""Naprawa dat wgrania plików z Traffita (29.09.2026) — prawdziwy Postgres.

Dokumenty z Traffita miały puste `uploaded_at` (lista `/employees/{id}/files`
nie niesie daty), więc UI pokazywało dzień importu. Naprawa czyta datę
z detalu osoby (`files: [{filename, file_uploaded}]`), dopasowuje dokument
po prefiksie `external_id` (`<osoba>-<plik>`) i nazwie, i zmienia WYŁĄCZNIE
`uploaded_at`. Filtr, zapis warunkowy i kursor siedzą w SQL-u, więc atrapa
bazy nie dowiodłaby niczego.

Baza testowa jest wspólna i nie jest czyszczona: każdy test bierze własne,
kolejne numery osób z Traffita i ustawia kursor tuż przed nimi, a atrapa
Traffita odpowiada 404 na każdą inną osobę — cudze dokumenty nie są ruszane.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import traffit_file_dates_repair as repair

UTC = timezone.utc

WINTER = "2026-02-19 15:32:00"
WINTER_UTC = datetime(2026, 2, 19, 14, 32, tzinfo=UTC)
SUMMER = "2025-07-10 09:00:00"
SUMMER_UTC = datetime(2025, 7, 10, 7, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeTraffit:
    def __init__(self, details):
        self.details = details
        self.calls: list[str] = []

    async def _get_raw(self, path, page=1, page_size=50):
        emp = path.strip("/").split("/")[1]
        self.calls.append(emp)
        if emp not in self.details:
            return _Resp(404)
        return _Resp(200, {"id": int(emp), "files": self.details[emp]})


def _base_emp() -> int:
    # Poza zakresem prawdziwych id Traffita i innych testów.
    return 8_000_000_000_000 + (uuid.uuid4().int % 10**9) * 1000


async def _mk_candidate(db) -> int:
    cid = await db.scalar(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname, created_at, updated_at
            ) VALUES (:e, 'traffit', 'A', 'B', NOW(), NOW())
            RETURNING id
            """
        ),
        {"e": f"fd-{uuid.uuid4().hex[:10]}"},
    )
    return int(cid)


async def _mk_doc(
    db,
    cid: int,
    *,
    filename: str,
    ext: str | None,
    source: str | None = "traffit",
    uploaded_at: datetime | None = None,
) -> int:
    doc_id = await db.scalar(
        text(
            """
            INSERT INTO candidate_documents (
                candidate_id, filename, storage_key, document_kind, is_primary,
                uploaded_at, external_id, external_source, created_at, updated_at
            ) VALUES (
                :cid, :fn, :sk, 'other', false, :up, :ext, :src,
                NOW(), TIMESTAMPTZ '2026-05-05 10:00:00+00'
            )
            RETURNING id
            """
        ),
        {
            "cid": cid,
            "fn": filename,
            "sk": f"cv/test/{uuid.uuid4().hex}",
            "up": uploaded_at,
            "ext": ext,
            "src": source,
        },
    )
    return int(doc_id)


async def _set_cursor(db, after_emp: int) -> None:
    await repair._write_setting(db, repair.STATE_KEY, {"after_emp": after_emp})
    await db.execute(
        text("DELETE FROM app_settings WHERE key = :k"), {"k": repair.DRY_RUN_KEY}
    )
    await db.commit()


async def _doc(db, doc_id: int):
    row = await db.execute(
        text(
            "SELECT uploaded_at, updated_at, filename, storage_key "
            "FROM candidate_documents WHERE id = :id"
        ),
        {"id": doc_id},
    )
    return row.one()


async def _fixture(db) -> SimpleNamespace:
    base = _base_emp()
    e1, e2 = str(base + 1), str(base + 2)
    cid = await _mk_candidate(db)
    winter = await _mk_doc(db, cid, filename="CV Jan.pdf", ext=f"{e1}-11")
    summer = await _mk_doc(db, cid, filename="list.docx", ext=f"{e1}-12")
    unknown = await _mk_doc(db, cid, filename="inny.pdf", ext=f"{e1}-13")
    # Dokument scalonego kandydata — osoba z Traffita wynika z external_id.
    other = await _mk_doc(db, cid, filename="cv2.pdf", ext=f"{e2}-21")
    manual = await _mk_doc(db, cid, filename="CV Jan.pdf", ext=None, source=None)
    await db.commit()
    await _set_cursor(db, base)
    traffit = _FakeTraffit(
        {
            e1: [
                {"filename": "CV Jan.pdf", "file_uploaded": WINTER},
                {"filename": "list.docx", "file_uploaded": SUMMER},
            ],
            e2: [{"filename": "cv2.pdf", "file_uploaded": SUMMER}],
        }
    )
    return SimpleNamespace(
        base=base,
        e1=e1,
        e2=e2,
        cid=cid,
        winter=winter,
        summer=summer,
        unknown=unknown,
        other=other,
        manual=manual,
        traffit=traffit,
    )


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_and_reports_samples(db) -> None:
    fx = await _fixture(db)
    before = {i: await _doc(db, i) for i in (fx.winter, fx.summer, fx.other)}

    report = await repair.process(db, fx.traffit, dry_run=True, limit=2)
    await repair.finish_run(db, report, started=datetime.now(UTC))

    for doc_id, row in before.items():
        assert await _doc(db, doc_id) == row
    assert report["changes"]["changed"] == 3
    assert report["changes"]["no_match"] == 1
    samples = {s["document_id"]: s for s in report["samples"]}
    assert samples[fx.winter]["before"] is None
    assert samples[fx.winter]["after"] == WINTER_UTC.isoformat()
    assert len(report["samples"]) <= repair.SAMPLE_SIZE
    # Próba nie przesuwa kursora zapisu.
    state = await repair._read_setting(db, repair.STATE_KEY)
    assert state["after_emp"] == fx.base
    assert await repair.fresh_dry_run_exists(db)


@pytest.mark.asyncio
async def test_apply_sets_dates_only_and_is_idempotent(db) -> None:
    fx = await _fixture(db)
    before_manual = await _doc(db, fx.manual)
    before_winter = await _doc(db, fx.winter)

    report = await repair.process(db, fx.traffit, dry_run=False, limit=2)
    await repair.finish_run(db, report, started=datetime.now(UTC))

    winter = await _doc(db, fx.winter)
    assert winter.uploaded_at == WINTER_UTC
    # Tylko `uploaded_at` — plik, nazwa i `updated_at` bez zmian.
    assert winter.updated_at == before_winter.updated_at
    assert winter.storage_key == before_winter.storage_key
    assert (await _doc(db, fx.summer)).uploaded_at == SUMMER_UTC
    assert (await _doc(db, fx.other)).uploaded_at == SUMMER_UTC
    assert (await _doc(db, fx.unknown)).uploaded_at is None
    # Dokument spoza Traffita (ta sama nazwa) nietknięty.
    assert await _doc(db, fx.manual) == before_manual
    assert report["changes"]["changed"] == 3
    details = await repair._read_setting(db, repair.DETAILS_KEY)
    assert [fx.winter, None] in details["before"]

    # Ponowny bieg od tego samego miejsca niczego nie zmienia.
    await _set_cursor(db, fx.base)
    again = await repair.process(db, fx.traffit, dry_run=False, limit=2)
    assert again["changes"]["changed"] == 0
    assert (await _doc(db, fx.winter)).uploaded_at == WINTER_UTC


@pytest.mark.asyncio
async def test_apply_overwrites_an_import_time_date(db) -> None:
    fx = await _fixture(db)
    await db.execute(
        text("UPDATE candidate_documents SET uploaded_at = NOW() WHERE id = :id"),
        {"id": fx.winter},
    )
    await db.commit()

    await repair.process(db, fx.traffit, dry_run=False, limit=2)

    assert (await _doc(db, fx.winter)).uploaded_at == WINTER_UTC


@pytest.mark.asyncio
async def test_budget_and_cursor_resume(db) -> None:
    fx = await _fixture(db)

    first = await repair.process(db, fx.traffit, dry_run=False, limit=1)
    await repair.finish_run(db, first, started=datetime.now(UTC))

    assert fx.traffit.calls == [fx.e1]
    assert (await _doc(db, fx.other)).uploaded_at is None
    state = await repair._read_setting(db, repair.STATE_KEY)
    assert state["after_emp"] == int(fx.e1)
    assert state["finished"] is False

    second = await repair.process(db, fx.traffit, dry_run=False, limit=1)
    assert fx.traffit.calls == [fx.e1, fx.e2]
    assert (await _doc(db, fx.other)).uploaded_at == SUMMER_UTC
    assert second["after_emp_end"] == int(fx.e2)


@pytest.mark.asyncio
async def test_old_real_dates_are_not_revisited(db) -> None:
    base = _base_emp()
    emp = str(base + 1)
    cid = await _mk_candidate(db)
    real = datetime.now(UTC) - timedelta(days=400)
    doc = await _mk_doc(db, cid, filename="cv.pdf", ext=f"{emp}-1", uploaded_at=real)
    await db.commit()
    await _set_cursor(db, base)
    traffit = _FakeTraffit({emp: [{"filename": "cv.pdf", "file_uploaded": WINTER}]})

    await repair.process(db, traffit, dry_run=False, limit=1)

    assert (await _doc(db, doc)).uploaded_at == real
    assert emp not in traffit.calls
