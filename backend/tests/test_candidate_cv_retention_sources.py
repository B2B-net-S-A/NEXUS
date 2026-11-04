"""Źródła CV zachowywanych przy usunięciu kandydata (runda 10, R10-V1-1).

Bez bazy: atrapa sesji odpowiada na zapytania ``retain_candidate_files`` po
treści SQL. Pilnuje, że CV firmowe etapu to treść z edytora
(``branded_draft_html``), a nie szablon papieru firmowego
(``branded_template_content``), i że plik zatwierdzonego CV etapu sprzed
wersjonowania (``branded_snapshot_path``) nie traci wskaźnika.
"""

from __future__ import annotations

import pytest

from app.services import candidate_cv_retention as retention
from app.services import object_storage

DRAFT = "<p>Edytowane CV — Zażółć</p>"
SNAPSHOT = "stage-cv-snapshots/1/cv.docx"


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self):
        self.added: list = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "branded_template_content" in sql:
            return _Result([(b"TPL", None)])
        if "branded_draft_html" in sql:
            return _Result([(DRAFT.encode("utf-8"), "text/html; charset=utf-8")])
        if "branded_snapshot_path" in sql:
            return _Result([(SNAPSHOT,)])
        if "v.snapshot_path IS NOT NULL" in sql:
            # ta sama ścieżka co w CV etapu — jeden wpis, nie dwa
            return _Result([(SNAPSHOT,)])
        return _Result([])

    def add_all(self, rows):
        self.added.extend(rows)


@pytest.mark.asyncio
async def test_stage_branded_cv_is_the_editor_draft_not_the_letterhead(monkeypatch):
    uploaded: dict[str, bytes] = {}

    def _upload(content, filename, content_type=None, *, storage_key=None):
        uploaded[storage_key] = content
        return storage_key

    monkeypatch.setattr(object_storage, "is_available", lambda: True)
    monkeypatch.setattr(object_storage, "upload_cv", _upload)
    db = _FakeDb()

    count = await retention.retain_candidate_files(
        db, 1, subject_ref="a" * 64, storage_keys=[]
    )

    assert list(uploaded.values()) == [DRAFT.encode("utf-8")]
    assert [row.storage_key for row in db.added].count(SNAPSHOT) == 1
    html_row = next(row for row in db.added if row.source == "stage_branded")
    assert html_row.content_type == "text/html; charset=utf-8"
    assert count == len(db.added) == 2


def test_letterhead_template_is_not_a_cv_source():
    sqls = " ".join(sql for _source, sql in retention._BYTE_SOURCES)
    assert "branded_template_content" not in sqls
    assert "branded_draft_html" in sqls
    paths = " ".join(sql for _source, sql in retention._PATH_SOURCES)
    assert "branded_snapshot_path" in paths
