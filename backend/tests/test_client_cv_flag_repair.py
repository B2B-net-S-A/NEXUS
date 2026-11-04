"""Flagi „główne” i kopie „Oryginał CV” po #2926 (04.11.2026).

Kontrakt przebiegu:

- następcą jest plik rodzaju „cv” bez cechy firmowego; „other” nim nie jest,
  a PDF z „B2B” w nazwie jest CV kandydata,
- brak daty idzie na koniec, a plik z układem szablonu, bez nazwiska albo bez
  bajtów odpada i trafia do raportu z samym id,
- osoba z samym firmowym plikiem zostaje bez zmian,
- kopia etapu dostaje następcę tylko bez CV do klienta,
- plik firmowy zostaje w profilu, a ``--rollback`` przywraca stan sprzed zmiany,
- ``--commit`` wymaga liczb z próby i paragonu bez nazw.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.cli import client_cv_flag_repair as repair_cli
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_stage_cv import CandidateStageCV
from tests.test_candidate_stage_cv_snapshot import _seed_job, _seed_stage

pytestmark = pytest.mark.asyncio

_FIRM = "B2B_Analityk_Fikcyjna.docx"
_OWN = "Ewa Fikcyjna CV.pdf"
_CV = CandidateDocumentKind.cv
_OTHER = CandidateDocumentKind.other


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paragon osobny na test, tekst pliku bez czytników, magazyn wyłączony."""
    monkeypatch.setattr(
        repair_cli, "RECEIPT_KEY", f"test_flag_repair_{uuid.uuid4().hex[:8]}"
    )

    async def plain_text(data: bytes, filename: str) -> str:
        return data.decode(errors="ignore")

    monkeypatch.setattr(repair_cli, "_extract_text", plain_text)
    monkeypatch.setattr("app.services.object_storage.is_available", lambda: False)


@pytest_asyncio.fixture(autouse=True)
async def _no_earlier_run() -> None:
    """`--commit` i `--rollback` czytają ślad poprzednich biegów z `activities`."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Activity).where(
                Activity.action.in_((repair_cli._FLAG_ACTION, repair_cli._COPY_ACTION))
            )
        )
        await db.commit()


async def _person(*files: tuple) -> tuple[int, str, list[int]]:
    """Pliki: (nazwa, rodzaj, główny, data, treść albo None = z nazwiskiem)."""
    lastname = f"Fikcyjna{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        person = Candidate(name="Ewa", lastname=lastname, cv_filename=_FIRM)
        db.add(person)
        await db.flush()
        docs = [
            CandidateDocument(
                candidate_id=person.id,
                filename=filename,
                file_content=(
                    content
                    if content is not None
                    else f"CV Ewa {lastname} {uuid.uuid4().hex}".encode()
                ),
                document_kind=kind,
                is_primary=primary,
                uploaded_at=uploaded_at,
            )
            for filename, kind, primary, uploaded_at, content in files
        ]
        db.add_all(docs)
        await db.commit()
        return person.id, lastname, [doc.id for doc in docs]


def _firm_primary(uploaded_at=None) -> tuple:
    return (_FIRM, _CV, True, uploaded_at, None)


async def _copy(
    candidate_id: int,
    *,
    status: str = "none",
    source: str = "auto_create",
    filename: str = _FIRM,
    in_db: bool = False,
) -> int:
    stage_id = await _seed_stage(candidate_id, await _seed_job())
    async with AsyncSessionLocal() as db:
        from app.models.recruitment_pipeline import CandidateStage

        stage = await db.get(CandidateStage, stage_id)
        copy = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=candidate_id,
            job_id=stage.job_id,
            original_cv_filename=filename,
            original_cv_content=b"%PDF firmowe" if in_db else None,
            original_cv_storage_key=None if in_db else "stage-cv/old/key",
            original_cv_sha256=uuid.uuid4().hex.ljust(64, "0"),
            original_cv_language="pl",
            original_snapshot_at=local_now() - timedelta(days=3),
            original_snapshot_source=source,
            branded_status=status,
        )
        db.add(copy)
        await db.commit()
        return copy.id


async def _plan(*candidate_ids: int) -> tuple[list[repair_cli.Planned], dict]:
    async with AsyncSessionLocal() as db:
        return await repair_cli.plan(db, candidate_ids=list(candidate_ids))


async def _primary_ids(candidate_id: int) -> list[int]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateDocument.id).where(
                        CandidateDocument.candidate_id == candidate_id,
                        CandidateDocument.is_primary.is_(True),
                    )
                )
            ).all()
        )


async def test_other_is_not_a_successor_and_a_lone_firm_file_stays() -> None:
    other_only, _, _ = await _person(
        _firm_primary(), ("Ewa CV.pdf", _OTHER, False, None, None)
    )
    lonely, _, _ = await _person(_firm_primary())

    items, _ = await _plan(other_only, lonely)

    assert items == []


async def test_b2b_pdf_is_the_candidates_file_and_a_b2b_word_is_not() -> None:
    cid, _, (firm, second_firm, pdf) = await _person(
        _firm_primary(),
        ("B2B_inne.docx", _CV, False, local_now(), None),
        ("B2B_Ewa.pdf", _CV, False, None, None),
    )

    [item], _ = await _plan(cid)

    assert (item.client_cv_id, item.successor_id) == (firm, pdf)
    assert second_firm != item.successor_id


async def test_a_dated_file_beats_an_undated_import() -> None:
    """`uploaded_at` z Traffita to NULL, a Postgres przy DESC stawia NULL pierwszy."""
    cid, _, (_, dated, _) = await _person(
        _firm_primary(),
        ("Ewa stare.pdf", _CV, False, local_now() - timedelta(days=30), None),
        ("Ewa import.pdf", _CV, False, None, None),
    )

    [item], _ = await _plan(cid)

    assert item.successor_id == dated
    # Paczka bierze ten sam plik z datą (`current_cv_ordering`), więc naprawa go nie zmienia.
    assert item.package_changes is False


async def test_doc_yields_to_pdf_among_undated_files() -> None:
    cid, _, (_, pdf, _) = await _person(
        _firm_primary(),
        ("Ewa.pdf", _CV, False, None, None),
        ("Ewa.doc", _CV, False, None, None),
    )

    [item], _ = await _plan(cid)

    assert item.successor_id == pdf


async def test_doc_as_only_successor_does_not_change_the_generator() -> None:
    cid, _, (_, doc) = await _person(
        _firm_primary(), ("Ewa.doc", _CV, False, None, None)
    )

    [item], _ = await _plan(cid)

    assert (item.successor_id, item.successor_ext) == (doc, ".doc")
    assert item.generator_changes is False
    assert item.package_changes is False


async def test_exclude_doc_leaves_the_person_for_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, _, (_, doc) = await _person(
        _firm_primary(), ("Ewa.doc", _CV, False, None, None)
    )

    async with AsyncSessionLocal() as db:
        [item], _ = await repair_cli.plan(db, candidate_ids=[cid], exclude_doc=True)

    assert item.successor_id is None
    assert item.rejected_files == {"doc_excluded": (doc,)}


async def test_reread_reads_the_successor_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[tuple[int, int]] = []

    async def fake_read(candidate_id: int, document_id: int, **kwargs: object) -> None:
        reads.append((candidate_id, document_id))

    monkeypatch.setattr(
        "app.api.candidates._enrich_candidate_from_document_task", fake_read
    )
    cid, _, (_, own) = await _person(_firm_primary(), (_OWN, _CV, False, None, None))
    [item], _ = await _plan(cid)

    await repair_cli.repair([item])
    assert reads == []

    second, _, (_, second_own) = await _person(
        _firm_primary(), (_OWN, _CV, False, None, None)
    )
    [item], _ = await _plan(second)
    await repair_cli.repair([item], reread=True)
    assert reads == [(second, second_own)]
    assert own != second_own


async def test_template_layout_missing_name_and_empty_file_go_to_review() -> None:
    cid, _, (_, template, foreign, empty) = await _person(
        _firm_primary(),
        ("Ewa szablon.pdf", _CV, False, local_now(), b"Dlaczego nasz kandydat? Ewa"),
        ("Ewa inna.pdf", _CV, False, None, b"CV Jan Inny, doswiadczenie"),
        ("Ewa pusta.pdf", _CV, False, None, b""),
    )

    [item], _ = await _plan(cid)

    assert item.successor_id is None
    assert item.rejected_files == {
        "template_layout": (template,),
        "no_lastname": (foreign,),
        "no_bytes": (empty,),
    }
    report = repair_cli.summarize([item], {})
    assert report["without_successor"] == [cid]
    assert report["flags"] == 0


async def test_same_bytes_as_the_firm_file_are_not_a_successor() -> None:
    body = b"CV tresc wspolna"
    cid, lastname, _ = await _person()
    async with AsyncSessionLocal() as db:
        firm = CandidateDocument(
            candidate_id=cid,
            filename=_FIRM,
            file_content=body + lastname.encode(),
            document_kind=_CV,
            is_primary=True,
        )
        twin = CandidateDocument(
            candidate_id=cid,
            filename="Ewa kopia.pdf",
            file_content=body + lastname.encode(),
            document_kind=_CV,
        )
        db.add_all([firm, twin])
        await db.commit()
        twin_id = twin.id

    [item], _ = await _plan(cid)

    assert item.successor_id is None
    assert item.rejected_files == {"same_as_client_cv": (twin_id,)}


async def test_only_copies_without_client_cv_get_the_candidates_file() -> None:
    cid, _, _ = await _person(_firm_primary(), (_OWN, _CV, False, None, None))
    untouched = await _copy(cid)
    draft = await _copy(cid, status="draft")
    finalized = await _copy(cid, status="finalized")
    manual = await _copy(cid, source="manual_upload")
    in_db = await _copy(cid, in_db=True)
    candidate_named = await _copy(cid, filename=_OWN)

    [item], left = await _plan(cid)

    assert item.copy_ids == (untouched,)
    assert sorted(left) == [
        "branded_draft",
        "branded_finalized",
        "bytes_in_db",
        "manual_upload",
    ]
    assert {*left["branded_draft"], *left["branded_finalized"]} == {draft, finalized}
    assert left["manual_upload"] == [manual]
    assert left["bytes_in_db"] == [in_db]
    assert candidate_named not in item.copy_ids


async def test_person_without_a_firm_flag_gets_only_the_copy_fixed() -> None:
    cid, _, (own_primary, firm) = await _person(
        (_OWN, _CV, True, None, None),
        (_FIRM, _CV, False, local_now(), None),
    )
    copy_id = await _copy(cid)

    [item], _ = await _plan(cid)

    assert item.client_cv_id is None
    assert item.successor_id == own_primary
    assert item.copy_ids == (copy_id,)
    report = repair_cli.summarize([item], {})
    assert (report["flags"], report["copies_only_people"]) == (0, 1)
    assert firm not in report["copy_ids"]


async def test_commit_requires_numbers_writes_ids_only_and_rollback_restores(
    capsys: pytest.CaptureFixture,
) -> None:
    cid, _, (firm, own) = await _person(_firm_primary(), (_OWN, _CV, False, None, None))
    copy_id = await _copy(cid)
    async with AsyncSessionLocal() as db:
        before = await db.get(CandidateStageCV, copy_id)

    # Na sucho: nic nie zmienia, wypisuje same id i liczby.
    assert await repair_cli.main(["--dry-run"], candidate_ids=[cid]) == 0
    out = capsys.readouterr().out
    report = json.loads(out.splitlines()[0])["plan"]
    assert report["flag_ids"] == [[cid, firm, own]]
    assert report["copy_ids"] == [copy_id]
    assert _OWN not in out and _FIRM not in out
    assert await _primary_ids(cid) == [firm]

    # Liczby z próby muszą się zgadzać.
    wrong = ["--commit", "--expected-flags", "9", "--expected-copies", "1"]
    assert await repair_cli.main(wrong, candidate_ids=[cid]) == 2
    assert await _primary_ids(cid) == [firm]

    ok = ["--commit", "--expected-flags", "1", "--expected-copies", "1"]
    assert await repair_cli.main(ok, candidate_ids=[cid]) == 0
    assert await _primary_ids(cid) == [own]
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, cid)
        firm_doc = await db.get(CandidateDocument, firm)
        fixed = await db.get(CandidateStageCV, copy_id)
        receipt = await repair_cli._receipt(db)
    assert candidate.cv_filename == _OWN
    assert firm_doc.document_kind == _CV and firm_doc.source_deleted_at is None
    assert fixed.original_cv_filename == _OWN
    assert fixed.original_snapshot_source == "client_cv_repair"
    assert receipt["flags_repaired"] == 1
    assert receipt["copies_repaired"] == 1
    assert _OWN not in json.dumps(receipt) and _FIRM not in json.dumps(receipt)

    # Drugi bieg blokuje paragon.
    assert await repair_cli.main(ok, candidate_ids=[cid]) == 2

    # Cofnięcie wraca do stanu sprzed zmiany.
    capsys.readouterr()
    assert await repair_cli.main(["--rollback"]) == 0
    assert await _primary_ids(cid) == [firm]
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, cid)
        restored = await db.get(CandidateStageCV, copy_id)
    assert candidate.cv_filename == _FIRM
    assert restored.original_cv_filename == _FIRM
    assert restored.original_cv_storage_key == before.original_cv_storage_key
    assert restored.original_cv_sha256 == before.original_cv_sha256
    assert restored.original_snapshot_source == "auto_create"
    assert restored.original_snapshot_at == before.original_snapshot_at


async def test_interrupted_run_can_be_rolled_back_and_not_repeated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zapisane osoby bez paragonu: bieg przerwany przed końcem."""
    cid, _, (firm, own) = await _person(_firm_primary(), (_OWN, _CV, False, None, None))
    copy_id = await _copy(cid)
    ok = ["--commit", "--expected-flags", "1", "--expected-copies", "1"]

    async def broken(db: object, payload: object) -> None:
        raise RuntimeError("przerwany bieg")

    with monkeypatch.context() as patch:
        patch.setattr(repair_cli, "_write_receipt", broken)
        with pytest.raises(RuntimeError):
            await repair_cli.main(ok, candidate_ids=[cid])
    assert await _primary_ids(cid) == [own]

    # Drugi --commit nie nakłada się na niedokończony bieg.
    assert await repair_cli.main(ok, candidate_ids=[cid]) == 2

    assert await repair_cli.main(["--rollback"]) == 0
    assert await _primary_ids(cid) == [firm]
    async with AsyncSessionLocal() as db:
        restored = await db.get(CandidateStageCV, copy_id)
    assert restored.original_cv_filename == _FIRM


async def test_rollback_keeps_a_later_human_choice() -> None:
    cid, _, (firm, own, third) = await _person(
        _firm_primary(),
        (_OWN, _CV, False, None, None),
        ("Ewa trzecie.pdf", _CV, False, None, None),
    )
    [item], _ = await _plan(cid)
    await repair_cli.repair([item])
    chosen = item.successor_id
    other = own if chosen == third else third
    async with AsyncSessionLocal() as db:
        doc = await db.get(CandidateDocument, chosen)
        doc.is_primary = False
        await db.flush()
        replacement = await db.get(CandidateDocument, other)
        replacement.is_primary = True
        await db.commit()

    stats = await repair_cli.rollback()

    assert stats["flags_kept"] >= 1
    assert await _primary_ids(cid) == [other]
    assert firm not in await _primary_ids(cid)


async def test_person_changed_since_the_dry_run_is_skipped() -> None:
    cid, _, (firm, own) = await _person(_firm_primary(), (_OWN, _CV, False, None, None))
    [item], _ = await _plan(cid)
    async with AsyncSessionLocal() as db:
        doc = await db.get(CandidateDocument, firm)
        doc.is_primary = False
        await db.commit()

    stats = await repair_cli.repair([item])

    assert stats["people_skipped"] == 1
    assert await _primary_ids(cid) == []
    assert own != firm
