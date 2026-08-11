"""A candidate deleted in Traffit must not freeze the sync forever.

Observed on prod 2026-08-10: `candidates_cv` reported `blocking_errors: 4` with
an empty quarantine, and the error samples were all `emp <id> files HTTP 404`.
Two faults compounded:

1. A 404 was recorded as an error at all. "Gone" is an ANSWER — the record was
   deleted at source and no number of retries changes that.
2. The message carried no `ext=`/`id=`, so `_ERROR_REF_RE` could not key it.
   `_blocking_errors` counts unattributable errors as blocking and
   `_next_quarantine` had no ref to park, so the phase watermark was frozen
   with no expiry path. Four deleted candidates held it indefinitely.

404s are now counted into `gone_upstream` (visible in /sync/status, never an
error), and every other non-200 carries `candidate ext=<id>` so a persistently
failing row can be quarantined instead of blocking the other 49k.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.traffit.importer import PhaseProgress, TraffitImporter
from app.tasks.traffit_sync import _blocking_errors, _next_quarantine


class _Row(SimpleNamespace):
    pass


class _Result:
    def __init__(self, rows, rowcount: int = 0):
        self._rows = list(rows)
        self.rowcount = rowcount

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, candidates):
        self.candidates = candidates

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        p = params or {}
        if "SELECT cursor_payload" in sql:
            return _Result([(None,)])
        if "FROM candidate_documents" in sql:
            return _Result([])
        if "FROM candidates" in sql and "external_id" in sql:
            rows = [_Row(id=cid, external_id=ext) for cid, ext in self.candidates]
            if "after_id" in p:
                rows = [r for r in rows if r.id > p["after_id"]][: p.get("limit", 99)]
            return _Result(rows)
        return _Result([])

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _StatusTraffit:
    """Answers each employee's file listing with a caller-chosen status code.

    `content_by_emp` opts a candidate into the SECOND hop: its listing then
    returns one file and the `/content` fetch answers with the given status.
    That hop is the TOCTOU case — Traffit listed the file, then deleted it
    before we downloaded it — and it has its own `gone` branch in the importer.

    Opt-in on purpose. Handing every candidate a file would silently convert
    the listing-only tests below into download tests and stop proving what
    their names claim.
    """

    def __init__(
        self, by_emp: dict[str, int], content_by_emp: dict[str, int] | None = None
    ):
        self.by_emp = by_emp
        self.content_by_emp = content_by_emp or {}
        self.config = SimpleNamespace(api_base="https://traffit.test/api")
        self._http = self

    async def _get_raw(self, path, page=1, page_size=50):
        emp = path.split("/")[2]
        code = self.by_emp.get(emp, 200)
        files = [{"id": "f1", "name": "cv.pdf"}] if emp in self.content_by_emp else []

        class _R:
            status_code = code

            @staticmethod
            def json():
                return files

        return _R()

    async def _ensure_token(self):
        return "token"

    async def _throttle(self):
        return None

    async def get(self, url, headers=None):
        """Stands in for `traffit._http.get` on the `/content` download."""
        emp = url.split("/employees/", 1)[1].split("/", 1)[0]
        code = self.content_by_emp.get(emp, 200)

        class _R:
            status_code = code
            content = b""
            headers: dict[str, str] = {}

        return _R()


def _importer(db, traffit) -> TraffitImporter:
    return TraffitImporter(traffit, db, dry_run=False, batch_size=100)


@pytest.mark.asyncio
async def test_404_is_counted_not_errored(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB([(1, "6421"), (2, "50939"), (3, "777")])
    # 410 must count the same as 404 — both mean "deleted at source".
    traffit = _StatusTraffit({"6421": 404, "50939": 410})

    progress = await _importer(db, traffit).import_candidates_cv(since=None)

    assert progress.gone_upstream == 2
    # The whole point: deleted records raise no error, so nothing blocks.
    assert progress.errors == 0
    assert _blocking_errors(progress.errors, [], {}, 5, attributed_errors=0) == 0
    assert progress.as_dict()["gone_upstream"] == 2


@pytest.mark.asyncio
async def test_other_failures_stay_errors_but_are_now_attributable(
    monkeypatch,
) -> None:
    """A 500 is still a real failure — but it must be parkable, not eternal."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB([(1, "6421")])
    traffit = _StatusTraffit({"6421": 500})

    progress = await _importer(db, traffit).import_candidates_cv(since=None)

    assert progress.errors == 1
    assert progress.gone_upstream == 0
    # Attributable — this is what the old `emp 6421 files HTTP 500` lacked.
    assert progress.error_refs == {"candidate:6421"}
    assert progress.attributed_errors == 1

    refs = sorted(progress.error_refs)
    q = _next_quarantine(None, refs)
    # Still blocking while it might be transient…
    assert _blocking_errors(progress.errors, refs, q, 3, attributed_errors=1) == 1
    for _ in range(2):
        q = _next_quarantine(q, refs)
    # …then parked, so one broken row stops holding back every other candidate.
    assert _blocking_errors(progress.errors, refs, q, 3, attributed_errors=1) == 0


@pytest.mark.asyncio
async def test_files_phase_treats_404_the_same_way(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB([(1, "6421"), (2, "999")])
    traffit = _StatusTraffit({"6421": 404})

    progress = await _importer(db, traffit).import_candidate_files(since=None)

    assert progress.gone_upstream == 1
    assert progress.errors == 0


@pytest.mark.asyncio
async def test_content_fetch_gone_is_counted_not_errored(monkeypatch) -> None:
    """The TOCTOU hop: Traffit listed the file, then deleted it before we
    downloaded it. Same answer as a missing listing — the record is gone, so
    retrying is pointless and an error here would freeze the watermark exactly
    as the listing 404 used to."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB([(1, "6421"), (2, "50939")])
    traffit = _StatusTraffit({}, content_by_emp={"6421": 404, "50939": 410})

    progress = await _importer(db, traffit).import_candidates_cv(since=None)

    assert progress.gone_upstream == 2
    assert progress.errors == 0


@pytest.mark.asyncio
async def test_content_fetch_500_stays_an_attributable_error(monkeypatch) -> None:
    """…while a genuinely failed download is still an error — and still keyed,
    so the quarantine can park it."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB([(1, "6421")])
    traffit = _StatusTraffit({}, content_by_emp={"6421": 500})

    progress = await _importer(db, traffit).import_candidates_cv(since=None)

    assert progress.gone_upstream == 0
    assert progress.errors == 1
    assert progress.error_refs == {"candidate:6421"}


@pytest.mark.asyncio
async def test_files_phase_content_fetch_gone_is_counted_too(monkeypatch) -> None:
    """`import_candidate_files` has its own copy of the branch — a fix applied
    to only one of the two phases would pass every test above."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB([(1, "6421"), (2, "50939")])
    traffit = _StatusTraffit({}, content_by_emp={"6421": 404, "50939": 410})

    progress = await _importer(db, traffit).import_candidate_files(since=None)

    assert progress.gone_upstream == 2
    assert progress.errors == 0


def test_summarize_surfaces_gone_upstream() -> None:
    from app.tasks.traffit_sync import _summarize

    progress = PhaseProgress(phase="candidates_cv")
    progress.gone_upstream = 4

    assert _summarize(progress.as_dict())["gone_upstream"] == 4
