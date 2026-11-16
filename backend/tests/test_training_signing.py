"""Podpis umowy szkoleniowej: czyste kroki (odcisk, wyrok, reprezentanci) bez bazy."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.services.b2b_esign.verdict import Fingerprint
from app.services.signing.provider import ValidationReport
from app.services.trainings import agreement, signing
from app.services.trainings.errors import TrainingError

FROZEN = b"%PDF-1.7\numowa szkoleniowa\n%%EOF\n"
SIGNED = FROZEN + b"podpis PAdES trenera\n%%EOF\n"


class FakeValidator:
    def __init__(self, signers: list[str], *, level: str = "QESig", authoritative=True):
        self.authoritative = authoritative
        self.calls = 0
        self._results = [
            {"signer": f"CN={name}", "indication": "TOTAL_PASSED", "level": level}
            for name in signers
        ]

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        self.calls += 1
        return ValidationReport(
            is_qes=True,
            indication="TOTAL_PASSED",
            signature_results=self._results,
        )


def _codes(error: pytest.ExceptionInfo) -> tuple[int, str]:
    return error.value.status, error.value.code


# ── Plik ─────────────────────────────────────────────────────────────────────


def test_check_pdf_rejects_non_pdf_and_too_big(monkeypatch):
    with pytest.raises(TrainingError) as error:
        signing.check_pdf(b"PK\x03\x04 docx")
    assert _codes(error) == (415, "not_pdf")
    monkeypatch.setattr(signing, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(TrainingError) as error:
        signing.check_pdf(b"%PDF-" + b"x" * 20)
    assert _codes(error) == (413, "too_big")


def test_builds_on_accepts_appended_signature():
    signing.check_builds_on(SIGNED, Fingerprint.of(FROZEN))


def test_same_file_is_not_signed_and_changed_file_is_not_built_on():
    previous = Fingerprint.of(FROZEN)
    with pytest.raises(TrainingError) as error:
        signing.check_builds_on(FROZEN, previous)
    assert _codes(error) == (422, "not_signed")
    resaved = FROZEN.replace(b"umowa", b"UMOWA") + b"podpis"
    with pytest.raises(TrainingError) as error:
        signing.check_builds_on(resaved, previous)
    assert _codes(error) == (422, "not_built_on")


def test_fingerprint_of_checks_stored_sha(tmp_path, monkeypatch):
    monkeypatch.setattr(agreement.storage_service, "STORAGE_ROOT", tmp_path)
    path = agreement.store_file(5, "umowa.pdf", FROZEN)
    assert path == "trainings/5/agreement/umowa.pdf"
    found = signing.fingerprint_of(path, expected_sha256=Fingerprint.of(FROZEN).sha256)
    assert found == Fingerprint.of(FROZEN)
    with pytest.raises(TrainingError) as error:
        signing.fingerprint_of(path, expected_sha256="0" * 64)
    assert _codes(error) == (409, "agreement_changed")
    with pytest.raises(TrainingError) as error:
        signing.fingerprint_of("trainings/5/agreement/brak.pdf")
    assert _codes(error) == (409, "file_missing")
    with pytest.raises(TrainingError):
        signing.fingerprint_of("../poza.pdf")


# ── Wyrok walidacji ──────────────────────────────────────────────────────────


async def test_trainer_signature_accepted_for_named_partner():
    validator = FakeValidator(["Kowalski Jan Piotr"])
    await signing.validate_signature(
        SIGNED, validator, required_signers=["Jan Kowalski"]
    )
    assert validator.calls == 1


@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        (FakeValidator(["Anna Nowak"]), (422, "missing_signer")),
        (FakeValidator(["Jan Kowalski"], level="AdESig"), (422, "not_qualified")),
        (FakeValidator(["Jan Kowalski"], authoritative=False), (503, "no_validator")),
        (FakeValidator([]), (422, "not_signed")),
    ],
)
async def test_trainer_signature_refusals(validator, expected):
    with pytest.raises(TrainingError) as error:
        await signing.validate_signature(
            SIGNED, validator, required_signers=["Jan Kowalski"]
        )
    assert _codes(error) == expected


async def test_company_signature_needs_one_representative_and_the_trainer():
    names = ["Adam Reprezentant", "Oskar Pełnomocnik"]
    both = FakeValidator(["Jan Kowalski", "Adam Reprezentant"])
    await signing.validate_signature(
        SIGNED, both, required_signers=["Jan Kowalski"], any_of_signers=names
    )
    only_trainer = FakeValidator(["Jan Kowalski"])
    with pytest.raises(TrainingError) as error:
        await signing.validate_signature(
            SIGNED,
            only_trainer,
            required_signers=["Jan Kowalski"],
            any_of_signers=names,
        )
    assert _codes(error) == (422, "missing_signer")


# ── Reprezentanci i dane umowy ───────────────────────────────────────────────


def test_representative_names_keep_settings_order_and_fall_back_to_uploader():
    names = {3: "Oskar Pełnomocnik", 1: "Adam Reprezentant", 9: "  "}
    assert signing.representative_names((1, 3, 9, 4), names, fallback="X") == [
        "Adam Reprezentant",
        "Oskar Pełnomocnik",
    ]
    assert signing.representative_names((9,), names, fallback="Oskar Pełnomocnik") == [
        "Oskar Pełnomocnik"
    ]


def test_trainer_name_comes_from_partner_snapshot():
    assert signing.trainer_name(
        SimpleNamespace(partner={"full_name": " Jan Kowalski "})
    ) == ("Jan Kowalski")
    with pytest.raises(TrainingError) as error:
        signing.trainer_name(SimpleNamespace(partner={}))
    assert _codes(error) == (409, "partner_missing")


def test_messages_for_the_trainer_have_no_em_dash():
    messages = [
        value
        for name, value in vars(signing).items()
        if name.startswith("MSG_") and isinstance(value, str)
    ]
    messages += [
        value
        for name, value in vars(agreement).items()
        if name.startswith("MSG_") and isinstance(value, str)
    ]
    assert messages and all("—" not in m for m in messages)
    # Komunikaty z kodu (np. brak danych trenera) też bez „—”.
    assert "—" not in inspect.getsource(signing.verdict_error)


# ── Przebieg z sesją-atrapą (blokada i ponowne sprawdzenie) ──────────────────


class FakeDb:
    """``get``/``scalar`` zwracają ten sam wiersz; ``on_commit`` udaje zmianę
    w innej transakcji w trakcie walidacji."""

    def __init__(self, training, *, on_commit=None, names=None):
        self.training = training
        self.on_commit = on_commit
        self.names = names or {}
        self.commits = 0
        self.flushed = False

    async def get(self, model, key):
        return self.training if key == self.training.id else None

    async def commit(self):
        self.commits += 1
        if self.on_commit:
            self.on_commit(self.training)

    async def scalar(self, statement):
        return self.training

    async def execute(self, statement):
        return SimpleNamespace(all=lambda: list(self.names.items()))

    async def flush(self):
        self.flushed = True


def _training(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr(agreement.storage_service, "STORAGE_ROOT", tmp_path)
    values = dict(
        id=12,
        status="accepted",
        partner={"full_name": "Jan Kowalski"},
        agreement_pdf_path=agreement.store_file(12, "umowa.pdf", FROZEN),
        agreement_pdf_sha256=Fingerprint.of(FROZEN).sha256,
        trainer_signed_at=None,
        trainer_signed_pdf_path=None,
        company_signed_pdf_path=None,
        company_signed_at=None,
        company_signed_by=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_trainer_upload_stores_file_and_moves_status(tmp_path, monkeypatch):
    training = _training(tmp_path, monkeypatch)
    db = FakeDb(training)
    result = await signing.trainer_upload(
        db, 12, SIGNED, now="TERAZ", validator=FakeValidator(["Jan Kowalski"])
    )
    assert result.status == "trainer_signed" and result.trainer_signed_at == "TERAZ"
    assert (tmp_path / result.trainer_signed_pdf_path).read_bytes() == SIGNED
    assert db.commits == 1 and db.flushed


async def test_trainer_upload_rechecks_fingerprint_under_lock(tmp_path, monkeypatch):
    training = _training(tmp_path, monkeypatch)

    def regenerated(row):
        row.agreement_pdf_sha256 = "f" * 64

    with pytest.raises(TrainingError) as error:
        await signing.trainer_upload(
            FakeDb(training, on_commit=regenerated),
            12,
            SIGNED,
            now="TERAZ",
            validator=FakeValidator(["Jan Kowalski"]),
        )
    assert _codes(error) == (409, "race")
    assert training.status == "accepted" and training.trainer_signed_pdf_path is None


async def test_trainer_upload_refuses_wrong_status_before_validation(
    tmp_path, monkeypatch
):
    validator = FakeValidator(["Jan Kowalski"])
    with pytest.raises(TrainingError) as error:
        await signing.trainer_upload(
            FakeDb(_training(tmp_path, monkeypatch, status="quoted")),
            12,
            SIGNED,
            now="TERAZ",
            validator=validator,
        )
    assert _codes(error) == (409, "wrong_status")
    assert validator.calls == 0


def _settings(signer_ids):
    async def load(db):
        return SimpleNamespace(company_signer_ids=signer_ids)

    return load


async def test_company_upload_by_listed_signer_with_representative_signature(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(signing.esign_settings, "load", _settings((1, 3)))
    training = _training(tmp_path, monkeypatch, status="trainer_signed")
    training.trainer_signed_pdf_path = agreement.store_file(12, "trener.pdf", SIGNED)
    final = SIGNED + b"podpis firmy\n%%EOF\n"
    olaf = SimpleNamespace(id=3, name="Oskar Pełnomocnik")
    db = FakeDb(training, names={1: "Adam Reprezentant", 3: "Oskar Pełnomocnik"})
    result = await signing.company_upload(
        db,
        12,
        final,
        user=olaf,
        now="TERAZ",
        validator=FakeValidator(["Jan Kowalski", "Adam Reprezentant"]),
    )
    assert result.status == "signed" and result.company_signed_by == 3
    assert (tmp_path / result.company_signed_pdf_path).read_bytes() == final


async def test_company_upload_refuses_user_outside_signer_list(tmp_path, monkeypatch):
    monkeypatch.setattr(signing.esign_settings, "load", _settings((1,)))
    training = _training(tmp_path, monkeypatch, status="trainer_signed")
    with pytest.raises(TrainingError) as error:
        await signing.company_upload(
            FakeDb(training),
            12,
            SIGNED,
            user=SimpleNamespace(id=7, name="Ktoś"),
            now="TERAZ",
            validator=FakeValidator([]),
        )
    assert _codes(error) == (403, "not_signer")


async def test_company_upload_waits_for_trainer(tmp_path, monkeypatch):
    monkeypatch.setattr(signing.esign_settings, "load", _settings((1,)))
    with pytest.raises(TrainingError) as error:
        await signing.company_upload(
            FakeDb(_training(tmp_path, monkeypatch)),
            12,
            SIGNED,
            user=SimpleNamespace(id=1, name="Adam Reprezentant"),
            now="TERAZ",
            validator=FakeValidator([]),
        )
    assert _codes(error) == (409, "wrong_status")


async def test_is_company_signer(monkeypatch):
    monkeypatch.setattr(signing.esign_settings, "load", _settings((1, 3)))
    assert await signing.is_company_signer(None, SimpleNamespace(id=3))
    assert not await signing.is_company_signer(None, SimpleNamespace(id=4))
