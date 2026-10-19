"""E-teczka — reguły bez bazy (audyt A2, 19.10.2026).

* retencja: 10 lat dla każdego rodzaju (decyzja Artura 19.10.2026),
* potwierdzenie nieobecności (dane o zdrowiu) widzą tylko osoba i Kadry,
* plik zapisany przed nieudanym zapisem wiersza znika z dysku,
* usunięcie oświadczenia studenta cofa datę zwolnienia, którą to
  oświadczenie wpisało (data wpisana ręcznie zostaje).

Sesja bazy jest atrapą — testy sprawdzają tylko kolejność „plik → wiersz”
i decyzje. Dane fikcyjne.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.hr import documents, documents_rules, documents_student
from app.services.hr_documents_schema import DOCUMENT_KINDS
from tests.hr_documents_seed import pdf_bytes

# ── Retencja ──────────────────────────────────────────────────────────────────


def test_default_retention_is_ten_years_for_every_kind() -> None:
    assert documents_rules.DEFAULT_RETENTION_YEARS == {
        kind: 10 for kind in DOCUMENT_KINDS
    }


# ── Krąg potwierdzenia nieobecności ───────────────────────────────────────────


@pytest.mark.parametrize(
    "audience",
    [
        documents.Audience(person=True, payroll=True, equipment=False),
        documents.Audience(person=True, payroll=False, equipment=True),
        documents.Audience(person=False, payroll=True, equipment=True),
    ],
)
def test_absence_proof_refuses_payroll_and_reception(audience) -> None:
    with pytest.raises(documents.HrDocumentError) as refused:
        documents.check_audience("absence_proof", audience)
    assert refused.value.status_code == 422
    assert refused.value.message == (
        "Potwierdzenie nieobecności widzą tylko osoba i Kadry."
    )


def test_absence_proof_for_person_or_kadry_only_and_other_kinds_pass() -> None:
    documents.check_audience(
        "absence_proof", documents.Audience(person=True, payroll=False, equipment=False)
    )
    documents.check_audience(
        "absence_proof",
        documents.Audience(person=False, payroll=False, equipment=False),
    )
    documents.check_audience(
        "contract", documents.Audience(person=True, payroll=True, equipment=True)
    )


# ── Plik po wycofanym zapisie ─────────────────────────────────────────────────


class _Boom(RuntimeError):
    pass


class _FakeSession:
    """Atrapa ``AsyncSession``: zapis wiersza (flush) albo przechodzi, albo pada."""

    def __init__(self, *, flush_error: Exception | None = None) -> None:
        self.flush_error = flush_error
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        for row in self.added:
            if getattr(row, "id", 0) is None:
                row.id = 1

    async def get(self, _model, _id):
        return SimpleNamespace(id=_id)

    @asynccontextmanager
    async def begin_nested(self):
        yield


def _files(root) -> list:
    return [path for path in root.rglob("*") if path.is_file()]


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def upload_ready(monkeypatch):
    from app.services.hr import people

    async def profile_of(_db, _user_id):
        return SimpleNamespace(user_id=_user_id)

    async def no_upload(_db, _user_id, _digest):
        return False

    async def no_previous(_db, _user_id, **_kwargs):
        return None

    monkeypatch.setattr(people, "profile_of", profile_of)
    monkeypatch.setattr(documents, "_live_upload_exists", no_upload)
    monkeypatch.setattr(documents_student, "latest_until", no_previous)


async def _upload(db, **overrides):
    values = {
        "user_id": 7,
        "kind": "statement",
        "title": "Oświadczenie studenta",
        "content": pdf_bytes(),
        "file_name": "oswiadczenie.pdf",
        "valid_until": date(2099, 6, 30),
        "purpose": "student_status",
        "audience": None,
        "actor": SimpleNamespace(id=1),
        **overrides,
    }
    return await documents.upload(db, **values)


@pytest.mark.usefixtures("upload_ready")
async def test_upload_removes_new_file_when_profile_sync_fails(
    store_root, monkeypatch
) -> None:
    async def failing_sync(*_args, **_kwargs):
        raise _Boom("kartoteka odrzuciła zapis")

    monkeypatch.setattr(documents_student, "sync", failing_sync)

    with pytest.raises(_Boom):
        await _upload(_FakeSession())

    assert _files(store_root) == []


@pytest.mark.usefixtures("upload_ready")
async def test_upload_removes_new_file_when_row_insert_fails(store_root) -> None:
    with pytest.raises(_Boom):
        await _upload(_FakeSession(flush_error=_Boom("baza")), purpose=None)

    assert _files(store_root) == []


@pytest.mark.usefixtures("upload_ready")
async def test_upload_keeps_file_that_was_on_disk_before(
    store_root, monkeypatch
) -> None:
    """Ten sam plik należy już do innego (np. usuniętego, jeszcze nie skasowanego)
    dokumentu osoby — nieudany zapis nie może go zabrać."""

    from app.services.hr import documents_store

    content = pdf_bytes()
    mime, digest = documents_store.check(content)
    existing = documents_store.save(7, content, mime=mime, digest=digest)

    async def failing_sync(*_args, **_kwargs):
        raise _Boom("kartoteka odrzuciła zapis")

    monkeypatch.setattr(documents_student, "sync", failing_sync)

    with pytest.raises(_Boom):
        await _upload(_FakeSession(), content=content)

    assert (store_root / existing).is_file()


async def test_attach_generated_removes_new_file_when_row_insert_fails(
    store_root, monkeypatch
) -> None:
    async def no_existing(_db, _source, _ref):
        return None

    monkeypatch.setattr(documents, "_by_source", no_existing)

    with pytest.raises(_Boom):
        await documents.attach_generated(
            _FakeSession(flush_error=_Boom("baza")),
            user_id=7,
            kind="contract",
            title="Umowa zlecenia",
            content=pdf_bytes(),
            mime="application/pdf",
            source=documents.SOURCE_AGREEMENT,
            source_ref="hr_agreement:1",
            valid_until=None,
            actor_id=None,
        )

    assert _files(store_root) == []


# ── Usunięcie oświadczenia studenta ───────────────────────────────────────────


def test_removed_statement_date_falls_back_to_remaining_statement() -> None:
    assert documents_student.after_removal(
        exempt=True,
        current_until=date(2027, 6, 30),
        removed_until=date(2027, 6, 30),
        remaining_until=date(2027, 2, 28),
    ) == ("restored", {"contribution_exempt_until": date(2027, 2, 28)})


def test_removed_statement_without_another_clears_exemption() -> None:
    assert documents_student.after_removal(
        exempt=True,
        current_until=date(2027, 6, 30),
        removed_until=date(2027, 6, 30),
        remaining_until=None,
    ) == (
        "cleared",
        {"student_contribution_exempt": False, "contribution_exempt_until": None},
    )


@pytest.mark.parametrize(
    ("exempt", "current_until"),
    [
        (True, date(2027, 3, 31)),  # data wpisana ręcznie (np. przed 26. urodzinami)
        (False, None),  # zwolnienie już zdjęte
        (True, None),  # znacznik bez daty — nie pochodzi z dokumentu
    ],
)
def test_removed_statement_leaves_date_it_did_not_write(exempt, current_until) -> None:
    status, values = documents_student.after_removal(
        exempt=exempt,
        current_until=current_until,
        removed_until=date(2027, 6, 30),
        remaining_until=date(2027, 2, 28),
    )
    assert status == "kept" and values is None
