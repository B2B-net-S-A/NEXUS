"""Kopie umów w etapach po naprawie głównego CV (30.10.2026).

Kontrakt przebiegu:

- wybór po nazwie pliku w kopii etapu, także kopie bez SHA,
- osoba z głównym CV bez umowy: kopia dostaje to CV,
- osoba bez głównego CV: kopia zostaje pusta, nieopisany plik jej nie zastępuje,
- główne CV wciąż będące umową: kopia zostaje do decyzji człowieka,
- CV firmowe zostaje, a kopia zmieniona od próby na sucho jest pomijana,
- `--apply` wymaga paragonu naprawy profili i liczby z próby.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.cli import contract_as_cv_repair as profile_cli
from app.cli import contract_stage_copies_repair as copies_cli
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_stage_cv import CandidateStageCV
from app.services.candidate_stage_cv_service import snapshot_exists
from tests.test_contract_as_cv_repair import (
    _CONTRACT,
    _contract_primary,
    _copy,
    _other,
    _person,
    _stage_copy,
)

pytestmark = pytest.mark.asyncio

_OWN_CV = "Ewa Fikcyjna CV.pdf"


def _own_primary() -> tuple[str, CandidateDocumentKind, bool]:
    return (_OWN_CV, CandidateDocumentKind.cv, True)


async def _plan(*candidate_ids: int) -> list[copies_cli.Planned]:
    async with AsyncSessionLocal() as db:
        return await copies_cli.plan(db, candidate_ids=list(candidate_ids))


async def _with_profile_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(profile_cli, "RECEIPT_KEY", key)
    monkeypatch.setattr(copies_cli, "RECEIPT_KEY", f"test_{uuid.uuid4().hex[:8]}")
    async with AsyncSessionLocal() as db:
        await profile_cli._write_receipt(db, {"found": 0})


async def test_plan_sorts_copies_by_what_the_person_has_now() -> None:
    sha = uuid.uuid4().hex.ljust(64, "0")
    own, _ = await _person(_own_primary(), _other(_CONTRACT))
    own_copy = await _stage_copy(own, sha256=sha)
    own_no_sha = await _stage_copy(own, sha256=None)
    bare, _ = await _person(_other(_CONTRACT), _other("B2B_CV_Fikcyjna.docx"))
    bare_copy = await _stage_copy(bare, sha256=sha)
    waiting, _ = await _person(_contract_primary())
    waiting_copy = await _stage_copy(waiting, sha256=sha)

    items = await _plan(own, bare, waiting)
    report = copies_cli.summarize(items)

    by_id = {item.csv_id: item.action for item in items}
    assert by_id == {
        own_copy: "replace",
        own_no_sha: "replace",
        bare_copy: "clear",
        waiting_copy: "skip",
    }
    assert (report["found"], report["to_replace"], report["to_clear"]) == (3, 2, 1)
    assert report["left_for_a_person"] == 1
    assert _CONTRACT not in json.dumps(report)


async def test_copy_named_like_a_cv_or_job_title_is_not_touched() -> None:
    person, _ = await _person(_own_primary())
    await _stage_copy(person, sha256=None, filename="Umowa_CV_Fikcyjna.pdf")
    await _stage_copy(person, sha256=None, filename="Fikcyjna_Contract_Manager.pdf")

    assert await _plan(person) == []


async def test_copy_gets_the_main_cv_also_without_sha() -> None:
    sha = uuid.uuid4().hex.ljust(64, "0")
    person, _ = await _person(_own_primary(), _other(_CONTRACT))
    with_sha = await _stage_copy(person, sha256=sha)
    no_sha = await _stage_copy(person, sha256=None)

    stats = await copies_cli.repair(await _plan(person))

    assert (stats["replaced"], stats["cleared"], stats["failed"]) == (2, 0, 0)
    for csv_id in (with_sha, no_sha):
        fixed = await _copy(csv_id)
        assert fixed.original_cv_filename == _OWN_CV
        assert fixed.original_cv_sha256 not in (None, sha)
        assert snapshot_exists(fixed)
        assert fixed.original_snapshot_source == "contract_repair"
        # CV firmowe to osobny byt, zostaje przy swoim stanie.
        assert fixed.branded_status == "finalized"


async def test_copy_is_emptied_when_the_person_has_no_main_cv() -> None:
    person, (contract, unnamed) = await _person(
        _other(_CONTRACT), _other("B2B_CV_Fikcyjna.docx")
    )
    csv_id = await _stage_copy(person, sha256=None)

    stats = await copies_cli.repair(await _plan(person))

    assert (stats["replaced"], stats["cleared"], stats["failed"]) == (0, 1, 0)
    emptied = await _copy(csv_id)
    assert not snapshot_exists(emptied)
    assert emptied.original_cv_filename is None
    assert emptied.original_cv_sha256 is None
    assert emptied.original_snapshot_source == "contract_repair"
    async with AsyncSessionLocal() as db:
        # Plik umowy zostaje w profilu, a nieopisany plik nie zostaje głównym.
        assert (await db.get(CandidateDocument, contract)).source_deleted_at is None
        assert (await db.get(CandidateDocument, unnamed)).is_primary is False
        logged = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate_stage_cv",
                    Activity.entity_id == csv_id,
                    Activity.action == "snapshot_contract_repaired",
                )
            )
        ).one()
    assert logged.details["old_filename"] == _CONTRACT
    assert logged.details["new_filename"] is None


async def test_copy_stays_when_the_main_cv_is_still_a_contract() -> None:
    person, _ = await _person(_contract_primary())
    csv_id = await _stage_copy(person, sha256=None)

    stats = await copies_cli.repair(await _plan(person))

    assert (stats["replaced"], stats["cleared"], stats["skipped"]) == (0, 0, 1)
    assert (await _copy(csv_id)).original_cv_filename == _CONTRACT


async def test_copy_changed_since_the_dry_run_is_skipped() -> None:
    person, _ = await _person(_own_primary())
    csv_id = await _stage_copy(person, sha256=None)
    items = await _plan(person)
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateStageCV, csv_id)
        row.original_cv_filename = "Wybrane przez rekrutera CV.pdf"
        await db.commit()

    stats = await copies_cli.repair(items)

    assert (stats["replaced"], stats["skipped"]) == (0, 1)
    assert (
        await _copy(csv_id)
    ).original_cv_filename == "Wybrane przez rekrutera CV.pdf"


async def test_apply_needs_the_profile_receipt_and_the_count_from_the_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(profile_cli, "RECEIPT_KEY", f"test_{uuid.uuid4().hex[:8]}")
    monkeypatch.setattr(copies_cli, "RECEIPT_KEY", f"test_{uuid.uuid4().hex[:8]}")
    person, _ = await _person(_own_primary())
    csv_id = await _stage_copy(person, sha256=None)
    scope = [person]

    # Na sucho: same liczby i identyfikatory, nic się nie zmienia.
    assert await copies_cli.main([], candidate_ids=scope) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[0])["plan"]
    assert (report["found"], report["csv_ids"]) == (1, [csv_id])
    assert (await _copy(csv_id)).original_cv_filename == _CONTRACT

    # Bez naprawy profili kopia wybrałaby umowę jako „bieżące CV”.
    args = ["--apply", "--expected", "1"]
    assert await copies_cli.main(args, candidate_ids=scope) == 2
    assert (await _copy(csv_id)).original_cv_filename == _CONTRACT

    await _with_profile_receipt(monkeypatch)
    wrong = ["--apply", "--expected", "2"]
    assert await copies_cli.main(wrong, candidate_ids=scope) == 2
    assert (await _copy(csv_id)).original_cv_filename == _CONTRACT

    assert await copies_cli.main(args, candidate_ids=scope) == 0
    assert (await _copy(csv_id)).original_cv_filename == _OWN_CV

    # Drugi bieg odrzuca paragon.
    assert (
        await copies_cli.main(["--apply", "--expected", "0"], candidate_ids=scope) == 2
    )
