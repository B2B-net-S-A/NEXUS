"""Runda 10 audytu (R10-N11): import Traffita nie nadpisuje pracy z NEXUSA.

Testy bez bazy: kształt SQL-i, przepływ faz na atrapach sesji. Zachowanie
SQL-i na prawdziwym Postgresie — `test_traffit_r10_sync_ownership_db.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.services.auto_match_outbox as auto_match_outbox_mod
import app.services.index_outbox_service as index_outbox_mod
import app.services.job_cc as job_cc_mod
import app.services.job_delivery_lead_fill as dl_fill_mod
import app.services.job_working_title as working_title_mod
import app.services.traffit.importer as importer_mod
import app.services.traffit_job_archive as archive_mod
from app.services.candidate_identity_ownership import (
    lock_changed_traffit_synced_fields,
)
from app.services.traffit.importer import (
    TraffitImporter,
    _UPDATE_CANDIDATE_ADOPT,
    _UPSERT_CANDIDATE,
    _UPSERT_CONTACT,
    _UPSERT_TALENT_POOL,
    _UPSERT_USER,
    candidate_payload_sha,
)
from app.tasks.traffit_sync import row_errors_are_advisory


# ── R10-N11-2 / N11-3: znaczniki ręcznej edycji ──────────────────────────────


@pytest.mark.parametrize("stmt", [_UPSERT_CANDIDATE, _UPDATE_CANDIDATE_ADOPT])
@pytest.mark.parametrize("field", ["phone", "linkedin", "profile_about", "status"])
def test_both_candidate_statements_respect_the_manual_marker(stmt, field) -> None:
    sql = str(stmt)
    assert f"'{{_nexus_identity,{field}_manual}}'" in sql
    assert "{manual:" not in sql


def test_upsert_respects_the_manual_email_marker() -> None:
    assert "'{_nexus_identity,email_manual}'" in str(_UPSERT_CANDIDATE)


def test_patch_marks_only_fields_that_really_changed() -> None:
    candidate = SimpleNamespace(
        external_source="traffit",
        email="a@example.test",
        phone="500000000",
        linkedin=None,
        profile_about=None,
        status=SimpleNamespace(value="blacklisted"),
        custom_fields={"_nexus_identity": {"name_manual": True}, "x": 1},
    )
    changed = lock_changed_traffit_synced_fields(
        candidate,
        {
            "email": "a@example.test",  # bez zmiany — formularz wysyła komplet
            "phone": "600000001",
            "status": SimpleNamespace(value="active"),
        },
        user_id=7,
    )
    assert changed == ["phone", "status"]
    meta = candidate.custom_fields["_nexus_identity"]
    assert meta["phone_manual"] is True and meta["status_manual"] is True
    assert "email_manual" not in meta
    assert meta["name_manual"] is True  # istniejące znaczniki zostają
    assert candidate.custom_fields["x"] == 1


def test_patch_marker_is_set_for_rows_from_other_sources_too() -> None:
    """Wiersz spoza Traffita bywa później adoptowany po mailu."""
    candidate = SimpleNamespace(
        external_source="manual",
        email=None,
        phone="1",
        linkedin=None,
        profile_about=None,
        status=None,
        custom_fields=None,
    )
    assert lock_changed_traffit_synced_fields(
        candidate, {"phone": "2"}, user_id=None
    ) == ["phone"]


# ── R10-N11-9: skrót payloadu i WHERE ────────────────────────────────────────


def test_payload_sha_is_stable_and_sensitive() -> None:
    base = {"external_id": "7", "phone": "1", "cv_extracted_data": {"a": [1, 2]}}
    same = {"cv_extracted_data": {"a": [1, 2]}, "phone": "1", "external_id": "7"}
    assert candidate_payload_sha(base) == candidate_payload_sha(same)
    assert candidate_payload_sha(base) != candidate_payload_sha({**base, "phone": "2"})


@pytest.mark.parametrize("stmt", [_UPSERT_CANDIDATE, _UPDATE_CANDIDATE_ADOPT])
def test_unchanged_record_is_not_rewritten(stmt) -> None:
    sql = str(stmt)
    assert "traffit_payload_sha" in sql
    assert "IS DISTINCT FROM CAST(:traffit_payload_sha AS text)" in sql


# ── R10-N11-4 / N11-7 / N11-11: kolumny prowadzone przez NEXUS ───────────────


def test_contact_upsert_keeps_nexus_owned_columns() -> None:
    sql = " ".join(str(_UPSERT_CONTACT).split())
    assert "is_decision_maker = contacts.is_decision_maker" in sql
    assert "COALESCE(NULLIF(contacts.name, ''), EXCLUDED.name)" in sql
    assert "client_id = EXCLUDED.client_id," not in sql
    assert ":orphan_client_id" in sql


def test_talent_pool_name_is_only_filled() -> None:
    sql = " ".join(str(_UPSERT_TALENT_POOL).split())
    assert "COALESCE(NULLIF(talent_pools.name, ''), EXCLUDED.name)" in sql


def test_user_upsert_touches_role_only_on_placeholder_accounts() -> None:
    sql = " ".join(str(_UPSERT_USER).split())
    assert "role = EXCLUDED.role," not in sql
    assert "is_active = EXCLUDED.is_active," not in sql
    assert "'!imported-from-traffit-no-login!'" in sql
    assert "users.azure_oid IS NULL" in sql


# ── R10-N11-10: kwarantanna przeglądów pełnego biegu ─────────────────────────


@pytest.mark.parametrize("phase", ["candidate_files", "candidates_cv"])
def test_full_sweep_row_errors_do_not_hold_the_watermark(phase) -> None:
    assert row_errors_are_advisory(phase, "full") is True
    assert row_errors_are_advisory(phase, "delta") is False


def test_other_phases_keep_their_behaviour() -> None:
    assert row_errors_are_advisory("candidates", "full") is False
    assert row_errors_are_advisory("candidates_cv_fields", "delta") is True


# ── Faza `jobs`: R10-N11-8 (sufiks numeru) i R10-N11-12 (savepointy) ─────────


class _Result:
    def __init__(self, row=None, rows=()):
        self._row = row
        self._rows = list(rows)
        self.rowcount = 1

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _Nested:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.db.depth += 1
        return self

    async def __aexit__(self, *a):
        self.db.depth -= 1
        return False


class _JobsDB:
    def __init__(self, refs=()) -> None:
        self.refs = list(refs)
        self.upserts: list[dict] = []
        self.depth = 0

    def begin_nested(self):
        return _Nested(self)

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "SELECT reference_number" in sql:
            return _Result(rows=self.refs)
        if params and "custom_fields" in params:  # `_UPSERT_JOB`
            self.upserts.append(dict(params))
            return _Result(row=(len(self.upserts), True, False))
        return _Result()

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _FakeTraffit:
    def __init__(self, ids) -> None:
        self.ids = ids

    async def get_paginated(self, path, **kw):
        for i in self.ids:
            yield {"id": i}


def _jobs_importer(db, monkeypatch, *, ids, reference):
    imp = TraffitImporter(_FakeTraffit(ids), db, dry_run=False, batch_size=100)
    for name, value in {
        "_probe_total": AsyncMock(return_value=len(ids)),
        "_build_client_external_id_map": AsyncMock(return_value={}),
        "_build_workflow_external_id_map": AsyncMock(return_value={}),
        "_hide_orphan_client_if_visible": AsyncMock(return_value=1),
        "_build_job_client_map": AsyncMock(return_value={}),
        "build_user_id_map": AsyncMock(return_value={}),
        "_build_job_owner_set": AsyncMock(return_value=set()),
    }.items():
        monkeypatch.setattr(imp, name, value)
    monkeypatch.setattr(
        importer_mod,
        "traffit_recruitment_to_job",
        lambda raw, *a: {
            "external_id": str(raw["id"]),
            "client_id": 1,
            "recruiter_id": None,
            "reference_number": reference,
            "status": "published",
            "title": f"Rekrutacja {raw['id']}",
            "custom_fields": {},
        },
    )
    monkeypatch.setattr(archive_mod, "archive_traffit_jobs", AsyncMock(return_value=0))
    monkeypatch.setattr(
        job_cc_mod, "classify_missing_job_ccs", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        dl_fill_mod, "fill_missing_job_delivery_leads", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        working_title_mod, "refresh_working_titles_for_ids", AsyncMock(return_value=0)
    )
    return imp


@pytest.mark.asyncio
async def test_reference_taken_by_a_nexus_job_gets_a_suffix(monkeypatch) -> None:
    """R10-N11-8: numer rekrutacji z NEXUSA (bez numeru Traffita) też zajmuje."""
    db = _JobsDB(refs=[("A/1", None)])
    imp = _jobs_importer(db, monkeypatch, ids=[5001], reference="A/1")
    monkeypatch.setattr(
        index_outbox_mod, "record_bulk_reindex", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(auto_match_outbox_mod, "enqueue_job", AsyncMock())

    progress = await imp.import_jobs(since=None)

    assert progress.errors == 0, progress.error_samples
    assert db.upserts[0]["reference_number"] == "A/1 (#5001)"


@pytest.mark.asyncio
async def test_traffit_job_keeps_its_own_reference(monkeypatch) -> None:
    db = _JobsDB(refs=[("A/1", "5001")])
    imp = _jobs_importer(db, monkeypatch, ids=[5001], reference="A/1")
    monkeypatch.setattr(
        index_outbox_mod, "record_bulk_reindex", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(auto_match_outbox_mod, "enqueue_job", AsyncMock())

    await imp.import_jobs(since=None)

    assert db.upserts[0]["reference_number"] == "A/1"


@pytest.mark.asyncio
async def test_reindex_intent_and_job_events_run_in_savepoints(monkeypatch) -> None:
    """R10-N11-12: błąd bazy tych zapisów nie może przerwać transakcji paczki."""
    db = _JobsDB()
    imp = _jobs_importer(db, monkeypatch, ids=[5001, 5002], reference=None)
    depths: dict[str, list[int]] = {"reindex": [], "event": []}

    async def _reindex(db_, entity, ids):
        depths["reindex"].append(db.depth)
        return len(ids)

    async def _enqueue(db_, **kw):
        depths["event"].append(db.depth)

    monkeypatch.setattr(index_outbox_mod, "record_bulk_reindex", _reindex)
    monkeypatch.setattr(auto_match_outbox_mod, "enqueue_job", _enqueue)

    await imp.import_jobs(since=None)

    assert depths["reindex"] and all(d >= 1 for d in depths["reindex"])
    # Zdarzenia dostają tylko rekrutacje otwarte (archiwum z Traffita zamyka
    # je w mapperze), więc tu może ich nie być — jeśli są, to w savepoincie.
    assert all(d >= 1 for d in depths["event"])


@pytest.mark.asyncio
async def test_failed_reindex_intent_does_not_stop_the_phase(monkeypatch) -> None:
    db = _JobsDB()
    imp = _jobs_importer(db, monkeypatch, ids=[5001], reference=None)

    async def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(index_outbox_mod, "record_bulk_reindex", _boom)
    monkeypatch.setattr(auto_match_outbox_mod, "enqueue_job", _boom)

    progress = await imp.import_jobs(since=None)

    assert progress.inserted == 1
    assert any("reindex intent" in m for m in progress.error_samples)


# ── R10-N11-6: CV z NEXUSA wygrywa z kopią z Traffita ────────────────────────


class _Resp:
    def __init__(self, payload=None):
        self.status_code = 200
        self._payload = payload
        self.content = b"%PDF-1.4"
        self.headers = {"content-type": "application/pdf"}

    def json(self):
        return self._payload


class _Http:
    async def get(self, url, headers=None):
        return _Resp()


class _FilesTraffit:
    def __init__(self):
        self._http = _Http()
        self.config = SimpleNamespace(api_base="https://traffit.test")

    async def _get_raw(self, path, page=1, page_size=50):
        return _Resp(payload=[{"id": 7, "name": "cv.pdf"}])

    async def _ensure_token(self):
        return "token"

    async def _throttle(self):
        return None


class _CvDB:
    """Kandydat z listy celów dostał w międzyczasie CV w NEXUSIE."""

    def __init__(self):
        self.pointer_sql: list[str] = []
        self.depth = 0

    def begin_nested(self):
        return _Nested(self)

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().upper().startswith("SELECT"):
            return _Result(rows=[SimpleNamespace(id=1, external_id="101")])
        if "UPDATE candidates SET" in sql and "cv_storage_key = :storage_key" in sql:
            self.pointer_sql.append(sql)
            res = _Result()
            res.rowcount = 0  # warunek `cv_storage_key IS NULL` odrzucił zapis
            return res
        return _Result()

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.mark.asyncio
async def test_cv_pointer_is_written_only_into_an_empty_slot(monkeypatch) -> None:
    from datetime import datetime, timezone

    from app.services import object_storage

    monkeypatch.setattr(object_storage, "upload_cv", lambda **_kw: "cv/key")
    db = _CvDB()
    imp = TraffitImporter(_FilesTraffit(), db)  # type: ignore[arg-type]

    progress = await imp.import_candidates_cv(since=datetime.now(timezone.utc))

    sql = " ".join(db.pointer_sql[0].split())
    assert "AND cv_storage_key IS NULL AND cv_file_content IS NULL" in sql
    assert progress.inserted == 0
    assert progress.skipped == 1
    assert progress.errors == 0


def test_candidate_patch_sets_the_sync_markers() -> None:
    """R10-N11-3: PATCH kandydata stawia znaczniki przed `setattr` pól."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/candidates.py").read_text(
        encoding="utf-8"
    )
    body = source[source.index("async def update_candidate(") :]
    body = body[: body.index("\n@router.", 10)]
    lock = body.index("lock_changed_traffit_synced_fields(")
    assert lock < body.index("setattr(candidate, field, value)")
