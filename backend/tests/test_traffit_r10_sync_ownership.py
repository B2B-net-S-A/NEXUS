"""Runda 10 audytu (R10-N11): import Traffita nie nadpisuje pracy z NEXUSA.

Testy bez bazy: kształt SQL-i, przepływ faz na atrapach sesji. Zachowanie
SQL-i na prawdziwym Postgresie — `test_traffit_r10_sync_ownership_db.py`.
"""

from __future__ import annotations

from types import SimpleNamespace


from app.services.candidate_identity_ownership import (
    lock_changed_traffit_synced_fields,
)


# ── R10-N11-2 / N11-3: znaczniki ręcznej edycji ──────────────────────────────


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


# ── R10-N11-4 / N11-7 / N11-11: kolumny prowadzone przez NEXUS ───────────────


# ── R10-N11-10: kwarantanna przeglądów pełnego biegu ─────────────────────────


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
