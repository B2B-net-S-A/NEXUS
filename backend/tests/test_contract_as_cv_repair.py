"""Umowa jako główne CV — naprawa profili z importu Traffita (30.10.2026).

Import oznaczał jako główne CV pierwszy PDF osoby, bez patrzenia na nazwę.
Kontrakt naprawy:

- wybór po nazwie pliku: umowa bez CV w nazwie; „Contract Manager” to stanowisko,
- plik zostaje w profilu, ale traci „główne CV” i nie może wrócić jako bieżące,
- następcą zostaje tylko plik z CV w nazwie; bez niego profil jest bez głównego CV,
- `--apply` wymaga liczby z próby, a paragon blokuje drugi bieg.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.cli import contract_as_cv_repair as repair_cli
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services.cv_source import get_current_cv

pytestmark = pytest.mark.asyncio

_CONTRACT = "Umowa B2B nr 1_Fikcyjna Ewa_sign.pdf"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (_CONTRACT, True),
        ("umowa.PDF", True),
        ("Umów_zlecenia.pdf", True),
        ("contract_2026.pdf", True),
        ("Framework Agreement.pdf", True),
        ("Ewa Fikcyjna CV.pdf", False),
        ("Umowa_CV_Fikcyjna.pdf", False),
        ("Ewa_Fikcyjna_Contract_Manager.pdf", False),
        ("Ewa Fikcyjna.pdf", False),
    ],
)
async def test_contract_name_recognition(filename: str, expected: bool) -> None:
    assert repair_cli.looks_like_contract(filename) is expected


async def _person(
    *files: tuple[str, CandidateDocumentKind, bool], pointer: str | None = None
) -> tuple[int, list[int]]:
    async with AsyncSessionLocal() as db:
        person = Candidate(
            name="Ewa",
            lastname=f"Fikcyjna-{uuid.uuid4().hex[:8]}",
            cv_filename=pointer,
            cv_storage_key=f"cv/test/{uuid.uuid4().hex}.pdf" if pointer else None,
        )
        db.add(person)
        await db.flush()
        docs = [
            CandidateDocument(
                candidate_id=person.id,
                filename=filename,
                file_content=b"%PDF " + uuid.uuid4().hex.encode(),
                document_kind=kind,
                is_primary=primary,
            )
            for filename, kind, primary in files
        ]
        db.add_all(docs)
        await db.commit()
        return person.id, [doc.id for doc in docs]


async def _doc(doc_id: int) -> CandidateDocument:
    async with AsyncSessionLocal() as db:
        return await db.get(CandidateDocument, doc_id)


async def _candidate(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


def _contract_primary() -> tuple[str, CandidateDocumentKind, bool]:
    return (_CONTRACT, CandidateDocumentKind.cv, True)


def _other(filename: str) -> tuple[str, CandidateDocumentKind, bool]:
    return (filename, CandidateDocumentKind.other, False)


async def test_plan_picks_only_a_cv_named_successor() -> None:
    with_cv, (contract, own_cv, _) = await _person(
        _contract_primary(), _other("Ewa Fikcyjna CV.pdf"), _other("skan.pdf")
    )
    unnamed, _ = await _person(_contract_primary(), _other("skan.pdf"))
    client_cv, _ = await _person(_contract_primary(), _other("B2B_CV_Fikcyjna.docx"))
    second_contract, _ = await _person(_contract_primary(), _other("Umowa_CV_2.pdf"))
    lonely, _ = await _person(_contract_primary())
    ordinary, _ = await _person(("Ewa CV.pdf", CandidateDocumentKind.cv, True))

    async with AsyncSessionLocal() as db:
        items = await repair_cli.plan(
            db,
            candidate_ids=[
                with_cv,
                unnamed,
                client_cv,
                second_contract,
                lonely,
                ordinary,
            ],
        )
    by_person = {item.candidate_id: item for item in items}

    assert ordinary not in by_person
    assert by_person[with_cv].contract_id == contract
    assert by_person[with_cv].successor_id == own_cv
    for person in (unnamed, client_cv, second_contract, lonely):
        assert by_person[person].successor_id is None


async def test_apply_requires_the_count_from_the_dry_run_and_writes_a_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(repair_cli, "RECEIPT_KEY", f"test_{uuid.uuid4().hex[:8]}")
    with_cv, (contract, own_cv) = await _person(
        _contract_primary(), _other("Ewa Fikcyjna CV.pdf"), pointer=_CONTRACT
    )
    lonely, (lonely_contract,) = await _person(_contract_primary(), pointer=_CONTRACT)
    scope = [with_cv, lonely]

    # Na sucho: same liczby i identyfikatory, nic się nie zmienia.
    assert await repair_cli.main([], candidate_ids=scope, reread=False) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[0])["plan"]
    assert (report["found"], report["with_successor"]) == (2, 1)
    assert report["candidate_ids"] == sorted(scope)
    assert _CONTRACT not in json.dumps(report)
    assert (await _doc(contract)).is_primary is True

    assert (
        await repair_cli.main(
            ["--apply", "--expected", "1"], candidate_ids=scope, reread=False
        )
        == 2
    )
    assert (await _doc(contract)).is_primary is True

    assert (
        await repair_cli.main(
            ["--apply", "--expected", "2"], candidate_ids=scope, reread=False
        )
        == 0
    )

    # Umowa zostaje w profilu, ale nie jest już CV.
    fixed = await _doc(contract)
    assert fixed.is_primary is False
    assert fixed.document_kind == CandidateDocumentKind.other
    assert fixed.outdated_at is not None
    assert fixed.source_deleted_at is None

    # Plik z CV w nazwie zostaje głównym, wskaźnik idzie za nim.
    successor = await _doc(own_cv)
    assert successor.is_primary is True
    assert successor.document_kind == CandidateDocumentKind.cv
    assert (await _candidate(with_cv)).cv_filename == "Ewa Fikcyjna CV.pdf"

    # Bez następcy profil nie ma głównego CV, a wskaźnik nie wskazuje umowy.
    alone = await _doc(lonely_contract)
    assert alone.is_primary is False
    assert alone.outdated_at is not None
    person = await _candidate(lonely)
    assert person.cv_filename is None
    assert person.cv_storage_key is None
    async with AsyncSessionLocal() as db:
        assert await get_current_cv(db, await db.get(Candidate, lonely)) is None

        logged = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == with_cv,
                    Activity.action == "primary_cv_repaired_from_contract",
                )
            )
        ).one()
    assert logged.details == {
        "contract_document_id": contract,
        "successor_document_id": own_cv,
    }

    # Drugi bieg odrzuca paragon.
    assert (
        await repair_cli.main(
            ["--apply", "--expected", "0"], candidate_ids=scope, reread=False
        )
        == 2
    )


async def test_person_who_chose_another_cv_since_the_dry_run_is_skipped() -> None:
    person, (contract, own_cv) = await _person(
        _contract_primary(), _other("Ewa Fikcyjna CV.pdf")
    )
    async with AsyncSessionLocal() as db:
        items = await repair_cli.plan(db, candidate_ids=[person])

    async with AsyncSessionLocal() as db:
        chosen = await db.get(CandidateDocument, contract)
        chosen.is_primary = False
        await db.commit()

    stats = await repair_cli.repair(items, reread=False)

    assert (stats["repaired"], stats["skipped"]) == (0, 1)
    untouched = await _doc(contract)
    assert untouched.document_kind == CandidateDocumentKind.cv
    assert untouched.outdated_at is None
    assert (await _doc(own_cv)).is_primary is False
