"""Nazwa pliku i nagłówek kopii CV etapu = nazwa roli jak w generatorze (15.10.2026).

Zgłoszenie DL: „CV w Nexusie jest dobrze nazwane, a jak pobieram, mam dwa
razy numer”. Generator od D2 (13.10.2026) bierze do nazwy pliku i nagłówka
``cv_role_title``, a kopia CV etapu (plik Word, CV z profilu, CV z innej
rekrutacji) brała surowy ``jobs.title``. U klienta ze wzorem
``ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}`` tytuł „… (ZOB-4321)” dawał
„ZOB-4321_… (ZOB-4321)_….docx”, a kopia z innej rekrutacji miała numer
zapytania w nagłówku CV. Testy bez bazy: ``detached_copy_settings`` na
podstawionej sesji.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.job import Job
from app.services.candidate_stage_cv_service import (
    copy_filename,
    detached_copy_settings,
)

PKO_PATTERN = "ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}"
TITLE = "Tester Automatyzujący Tester Danych Senior (ZOB-4321)"


class _Session:
    """Tyle sesji, ile czyta ``detached_copy_settings``: ``get`` i aliasy klienta."""

    def __init__(self, *rows):
        self.rows = {(type(row), row.id): row for row in rows}

    async def get(self, model, ident):
        return self.rows.get((model, ident))

    async def execute(self, _statement):
        return SimpleNamespace(scalars=lambda: iter(()))


def _rule(monkeypatch, pattern: str | None) -> None:
    from app.services.cv_generator_b2b import client_rules

    async def _resolve(db, client_id):
        return object()

    monkeypatch.setattr(client_rules, "resolve_client_rule", _resolve)
    monkeypatch.setattr(
        client_rules,
        "snapshot_rule",
        lambda rule: SimpleNamespace(
            requires_rodo_consent_block=False,
            filename_pattern=pattern,
            spaces_to_underscores=False,
        ),
    )


def _world(title: str, reference: str | None, client_name: str = "Bank Fikcyjny"):
    client = Client(id=7, name=client_name)
    job = Job(id=11, title=title, client_reference=reference, client_id=client.id)
    candidate = Candidate(id=13, name="Ewa", lastname="Fikcyjna")
    csv = CandidateStageCV(id=17, job_id=job.id, candidate_id=candidate.id)
    return _Session(client, job, candidate), csv


@pytest.mark.asyncio
async def test_client_number_pattern_gets_the_number_once(monkeypatch):
    _rule(monkeypatch, PKO_PATTERN)
    db, csv = _world(TITLE, "ZOB-4321")

    settings = await detached_copy_settings(db, csv)

    assert settings.filename == (
        "ZOB-4321_Tester Automatyzujący Tester Danych Senior_Ewa Fikcyjna.docx"
    )
    # Ten sam tytuł idzie do nagłówka kopii z innej rekrutacji.
    assert settings.job_title == "Tester Automatyzujący Tester Danych Senior"


@pytest.mark.asyncio
async def test_blind_copy_keeps_the_masked_name(monkeypatch):
    _rule(monkeypatch, PKO_PATTERN)
    db, csv = _world(TITLE, "ZOB-4321")

    settings = await detached_copy_settings(db, csv, masked_name="Kandydat")

    assert settings.filename == (
        "ZOB-4321_Tester Automatyzujący Tester Danych Senior_Kandydat.docx"
    )


@pytest.mark.asyncio
async def test_client_prefix_and_bracket_number_leave_the_standard_name(monkeypatch):
    """Wzór standardowy (``B2B_{STANOWISKO}_…``): bez nazwy klienta i numeru,
    tak jak w pliku z generatora."""
    _rule(monkeypatch, "B2B_{STANOWISKO}_{IMIE_NAZWISKO}")
    db, csv = _world("Bank Fikcyjny: Senior IT Analyst (42946)", "42946")

    settings = await detached_copy_settings(db, csv)

    assert settings.filename == "B2B_Senior IT Analyst_Ewa Fikcyjna.docx"
    assert settings.job_title == "Senior IT Analyst"


@pytest.mark.asyncio
async def test_client_without_a_pattern_falls_back_to_the_role_name(monkeypatch):
    _rule(monkeypatch, None)
    db, csv = _world(TITLE, "ZOB-4321")

    settings = await detached_copy_settings(db, csv)

    assert settings.filename == (
        "Tester Automatyzujący Tester Danych Senior_Ewa Fikcyjna.docx"
    )


@pytest.mark.asyncio
async def test_title_without_codes_stays_as_it_was(monkeypatch):
    _rule(monkeypatch, PKO_PATTERN)
    db, csv = _world("Inżynier Danych (K8s)", "ZOB-4321")

    settings = await detached_copy_settings(db, csv)

    assert settings.filename == "ZOB-4321_Inżynier Danych (K8s)_Ewa Fikcyjna.docx"
    assert settings.job_title == "Inżynier Danych (K8s)"


def test_old_copy_name_is_what_the_raw_title_gave():
    """Poprawka nazw już zapisanych rozpoznaje starą nazwę tą samą funkcją."""
    rule = SimpleNamespace(filename_pattern=PKO_PATTERN, spaces_to_underscores=False)

    assert copy_filename(rule, TITLE, "Ewa Fikcyjna", "4321") == (
        "ZOB-4321_Tester Automatyzujący Tester Danych Senior (ZOB-4321)"
        "_Ewa Fikcyjna.docx"
    )
    assert copy_filename(None, "", "Ewa Fikcyjna", None) == "CV_B2B_Ewa_Fikcyjna.docx"


# ── Jednorazowa poprawka nazw już zapisanych (punkt 3 zgłoszenia) ────────────

ROLE = "Tester Automatyzujący Tester Danych Senior"
OLD_NAME = f"ZOB-4321_{ROLE} (ZOB-4321)_Ewa Fikcyjna.docx"
NEW_NAME = f"ZOB-4321_{ROLE}_Ewa Fikcyjna.docx"


def _pko():
    return SimpleNamespace(filename_pattern=PKO_PATTERN, spaces_to_underscores=False)


def test_repair_swaps_only_the_role_and_keeps_the_person_as_stored():
    from app.services.stage_cv_copy_filename_repair import renamed_copy_filename

    assert renamed_copy_filename(OLD_NAME, _pko(), TITLE, ROLE, "4321") == NEW_NAME
    # Osoba zostaje w zapisanej pisowni (imię mogło się od tego czasu zmienić).
    assert renamed_copy_filename(
        OLD_NAME.replace("Ewa Fikcyjna", "Ewa M. Fikcyjna"), _pko(), TITLE, ROLE, "4321"
    ) == NEW_NAME.replace("Ewa Fikcyjna", "Ewa M. Fikcyjna")
    blind = OLD_NAME.replace("Ewa Fikcyjna", "Kandydat")
    assert renamed_copy_filename(blind, _pko(), TITLE, ROLE, "4321") == (
        NEW_NAME.replace("Ewa Fikcyjna", "Kandydat")
    )
    underscores = SimpleNamespace(
        filename_pattern="B2B_{STANOWISKO}_{IMIE_NAZWISKO}", spaces_to_underscores=True
    )
    assert (
        renamed_copy_filename(
            "B2B_Bank_Fikcyjny_Senior_IT_Analyst_(42946)_Ewa_Fikcyjna.docx",
            underscores,
            "Bank Fikcyjny Senior IT Analyst (42946)",
            "Senior IT Analyst",
            None,
        )
        == "B2B_Senior_IT_Analyst_Ewa_Fikcyjna.docx"
    )


def test_repair_leaves_names_it_did_not_build():
    from app.services.stage_cv_copy_filename_repair import renamed_copy_filename

    # Już poprawna, zmieniona ręcznie, pusta, tytuł bez kodów.
    assert renamed_copy_filename(NEW_NAME, _pko(), TITLE, ROLE, "4321") is None
    assert renamed_copy_filename("CV_Ewa.docx", _pko(), TITLE, ROLE, "4321") is None
    assert renamed_copy_filename(None, _pko(), TITLE, ROLE, "4321") is None
    assert (
        renamed_copy_filename(
            "ZOB-4321_Inżynier Danych (K8s)_Ewa Fikcyjna.docx",
            _pko(),
            "Inżynier Danych (K8s)",
            "Inżynier Danych (K8s)",
            "4321",
        )
        is None
    )
    # Sam szkielet nazwy bez osoby to nie nazwa kopii.
    head_and_tail_only = f"ZOB-4321_{ROLE} (ZOB-4321)_.docx"
    assert (
        renamed_copy_filename(head_and_tail_only, _pko(), TITLE, ROLE, "4321") is None
    )


@pytest.mark.asyncio
async def test_repair_renames_copy_and_its_approved_versions_once(monkeypatch):
    """Z bazą (CI): wiersz kopii i jej wersje dostają nową nazwę, wersja
    o innej nazwie i ``updated_at`` zostają, drugi przebieg nic nie robi."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.cv_document_version import CvDocumentVersion
    from app.services.stage_cv_copy_filename_repair import rename_copy_filenames
    from tests.test_stage_cv_pick_from_profile import _seed

    _rule(monkeypatch, PKO_PATTERN)
    world = await _seed()
    title = f"Tester Danych {world['tag']} Senior (ZOB-4321)"
    person = f"Ewa Fikcyjna{world['tag']}"
    old = f"ZOB-4321_{title}_{person}.docx"
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.title, job.client_reference = title, "ZOB-4321"
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == world["stage_id"]
            )
        )
        csv.branded_status = "finalized"
        csv.branded_docx_filename = old
        csv.branded_render_metadata = {"source": "document"}
        await db.flush()
        for version, filename in ((1, old), (2, "Ręcznie.docx")):
            db.add(
                CvDocumentVersion(
                    candidate_stage_cv_id=csv.id,
                    version=version,
                    content_html="<p>Treść</p>",
                    content_sha256="0" * 64,
                    docx_filename=filename,
                    approved_at=datetime.now(timezone.utc),
                )
            )
        await db.commit()
        csv_id, stamp = csv.id, csv.updated_at

    async with AsyncSessionLocal() as db:
        receipt = await rename_copy_filenames(db, only_csv_ids={csv_id})
        await db.commit()

    assert receipt == {
        "copies_seen": 1,
        "renamed": 1,
        "versions_renamed": 1,
        "policy_pending": 0,
    }
    new = f"ZOB-4321_Tester Danych {world['tag']} Senior_{person}.docx"
    async with AsyncSessionLocal() as db:
        csv = await db.get(CandidateStageCV, csv_id)
        assert (csv.branded_docx_filename, csv.updated_at) == (new, stamp)
        names = (
            await db.scalars(
                select(CvDocumentVersion.docx_filename)
                .where(CvDocumentVersion.candidate_stage_cv_id == csv_id)
                .order_by(CvDocumentVersion.version)
            )
        ).all()
        assert names == [new, "Ręcznie.docx"]
        again = await rename_copy_filenames(db, only_csv_ids={csv_id})
        await db.rollback()
    assert again["renamed"] == 0


@pytest.mark.asyncio
async def test_repair_waits_for_a_client_policy_that_is_not_synchronised(monkeypatch):
    """503 polityki klienta: wiersz pominięty, krok nie stawia markera."""
    from fastapi import HTTPException

    from app.services import stage_cv_copy_filename_repair as repair
    from app.services.cv_generator_b2b import client_rules

    async def _pending(db, client_id):
        raise HTTPException(503, "Polityka CV klienta oczekuje na synchronizację.")

    monkeypatch.setattr(client_rules, "resolve_client_rule", _pending)
    db, _csv = _world(TITLE, "ZOB-4321")

    assert await repair._job_names(db, 11) == "pending"


def test_entrypoint_runs_the_repair_after_client_references_are_filled():
    """Numer projektu i nazwa roli czytają ``client_reference``, które krok
    „client-reference-from-title” dopiero uzupełnia z nazwy."""
    from pathlib import Path

    entrypoint = (Path(__file__).parents[1] / "entrypoint.sh").read_text()
    fill = entrypoint.index('startup_phase "client-reference-from-title"')
    repair = entrypoint.index('startup_phase "stage-cv-copy-filenames"')
    assert fill < repair
    phase = entrypoint[repair : entrypoint.index("\nPY\n", repair)]
    assert "rename_copy_filenames" in phase
    assert "await db.commit()" in phase
