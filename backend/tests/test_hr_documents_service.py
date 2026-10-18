"""E-teczka — serwis: dokument z generatora (interfejs E5), wgranie, oświadczenie studenta.

Ścieżki odmowy: zły typ pliku (HTML, DOCX z makrem), typ niezgodny z treścią,
nieznane źródło, ten sam plik drugi raz (409), osoba bez kartoteki (404),
status studenta bez daty albo przy innym rodzaju. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_document import HrDocument
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import documents, documents_rules, documents_store
from app.services.hr_documents_schema import DOCUMENT_KINDS, DOCUMENT_MIME_TYPES
from tests.hr_documents_seed import (
    docx_bytes,
    documents_on,  # noqa: F401  (fixture)
    documents_store_root,  # noqa: F401  (fixture)
    pdf_bytes,
    png_bytes,
)
from tests.hr_settlements_seed import make_user

pytestmark = pytest.mark.usefixtures("documents_on", "documents_store_root")


async def _attach(user_id: int, ref: str = "hr_agreement:1", **overrides):
    values = {
        "user_id": user_id,
        "kind": "contract",
        "title": "Umowa zlecenia z 01.11.2026",
        "content": pdf_bytes(),
        "mime": "application/pdf",
        "source": documents.SOURCE_AGREEMENT,
        "source_ref": ref,
        "valid_until": None,
        "actor_id": None,
        **overrides,
    }
    async with AsyncSessionLocal() as db:
        document = await documents.attach_generated(db, **values)
        await db.commit()
        return document


async def _count(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(HrDocument)
                .where(HrDocument.user_id == user_id)
            )
        )


async def _upload(actor_id: int, user_id: int, **overrides):
    values = {
        "user_id": user_id,
        "kind": "statement",
        "title": "Oświadczenie studenta",
        "content": pdf_bytes(),
        "file_name": "oswiadczenie.pdf",
        "valid_until": None,
        "purpose": None,
        "audience": None,
        **overrides,
    }
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        document, sync = await documents.upload(db, actor=actor, **values)
        await db.commit()
        return document, sync


async def _profile(user_id: int) -> EmployeeProfile:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
        )


# ── Słownik i magazyn ─────────────────────────────────────────────────────────


def test_every_kind_has_label_audience_and_retention() -> None:
    assert set(documents_rules.KIND_LABELS) == set(DOCUMENT_KINDS)
    assert set(documents_rules.DEFAULT_AUDIENCE) == set(DOCUMENT_KINDS)
    assert set(documents_rules.DEFAULT_RETENTION_YEARS) == set(DOCUMENT_KINDS)
    assert set(documents_store.EXTENSIONS) == set(DOCUMENT_MIME_TYPES)


def test_file_type_comes_from_content_not_name() -> None:
    assert documents_store.sniff_mime(pdf_bytes()) == "application/pdf"
    assert documents_store.sniff_mime(png_bytes()) == "image/png"
    assert documents_store.sniff_mime(docx_bytes()) == documents_store.DOCX_MIME
    assert documents_store.sniff_mime(b"<html><script>x</script></html>") is None
    with pytest.raises(documents_store.FileRejected):
        documents_store.check(b"")
    with pytest.raises(documents_store.FileRejected, match="makrami"):
        documents_store.check(docx_bytes(macro=True))


def test_retention_counts_from_end_of_exit_year() -> None:
    assert documents_rules.delete_from(date(2026, 3, 15), 10) == date(2037, 1, 1)
    assert documents_rules.delete_from(date(2026, 12, 31), 1) == date(2028, 1, 1)


@pytest.mark.parametrize(
    "raw",
    [
        {"contract": 0},
        {"contract": 51},
        {"contract": "dziesięć"},
        {"contract": True},
        {"unknown_kind": 5},
        ["contract", 10],
    ],
)
def test_retention_settings_refuse_bad_values(raw) -> None:
    with pytest.raises(documents_rules.RetentionSettingsError):
        documents_rules.parse_retention(raw)


def test_retention_settings_keep_defaults_for_missing_kinds() -> None:
    years = documents_rules.parse_retention({"other": 7})
    assert years["other"] == 7
    assert years["contract"] == documents_rules.DEFAULT_RETENTION_YEARS["contract"]


# ── attach_generated (interfejs dla E5) ───────────────────────────────────────


async def test_attach_generated_stores_file_and_is_idempotent(
    documents_store_root,  # noqa: F811
) -> None:
    person = await make_user(employment_type="zlecenie", name="Celina Testowa")
    first = await _attach(person.id, ref="hr_agreement:101")
    second = await _attach(person.id, ref="hr_agreement:101", content=pdf_bytes())

    assert second.id == first.id
    assert await _count(person.id) == 1
    assert first.source == "agreement" and first.source_ref == "hr_agreement:101"
    assert (first.visible_to_person, first.visible_to_payroll) == (True, True)
    assert first.visible_to_equipment is False
    stored = documents_store_root / first.file_path
    assert stored.is_file()
    assert f"hr_documents/{person.id}/" in first.file_path
    async with AsyncSessionLocal() as db:
        events = await db.scalar(
            select(func.count())
            .select_from(HrAuditEvent)
            .where(
                HrAuditEvent.entity_type == "hr_document",
                HrAuditEvent.entity_id == str(first.id),
                HrAuditEvent.action == "document_attached",
            )
        )
    assert events == 1


async def test_attach_generated_refuses_bad_input() -> None:
    person = await make_user(employment_type="b2b")
    async with AsyncSessionLocal() as db:
        with pytest.raises(documents.HrDocumentError, match="źródło"):
            await documents.attach_generated(
                db,
                user_id=person.id,
                kind="contract",
                title="Umowa",
                content=pdf_bytes(),
                mime="application/pdf",
                source="upload",
                source_ref="x:1",
                valid_until=None,
                actor_id=None,
            )
        with pytest.raises(documents.HrDocumentError, match="nie zgadza"):
            await documents.attach_generated(
                db,
                user_id=person.id,
                kind="contract",
                title="Umowa",
                content=png_bytes(),
                mime="application/pdf",
                source="agreement",
                source_ref="hr_agreement:2",
                valid_until=None,
                actor_id=None,
            )
        with pytest.raises(documents.HrDocumentError, match="typ"):
            await documents.attach_generated(
                db,
                user_id=person.id,
                kind="contract",
                title="Umowa",
                content=b"<html></html>",
                mime="text/html",
                source="agreement",
                source_ref="hr_agreement:3",
                valid_until=None,
                actor_id=None,
            )
        with pytest.raises(documents.HrDocumentError) as missing:
            await documents.attach_generated(
                db,
                user_id=2_000_000_000,
                kind="contract",
                title="Umowa",
                content=pdf_bytes(),
                mime="application/pdf",
                source="agreement",
                source_ref="hr_agreement:4",
                valid_until=None,
                actor_id=None,
            )
        assert missing.value.status_code == 404
    assert await _count(person.id) == 0


# ── Wgranie ───────────────────────────────────────────────────────────────────


async def test_upload_refuses_same_file_twice_and_person_without_profile() -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="b2b")
    content = pdf_bytes()
    await _upload(
        hr.id, person.id, kind="certificate", title="Zaświadczenie", content=content
    )
    with pytest.raises(documents.HrDocumentError) as twice:
        await _upload(
            hr.id, person.id, kind="certificate", title="Kopia", content=content
        )
    assert twice.value.status_code == 409

    no_profile = await make_user("recruiter", profile=False)
    with pytest.raises(documents.HrDocumentError) as missing:
        await _upload(hr.id, no_profile.id, kind="other", title="Inne")
    assert missing.value.status_code == 404


async def test_upload_refuses_html_and_macro_files() -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="b2b")
    with pytest.raises(documents.HrDocumentError, match="PDF"):
        await _upload(hr.id, person.id, content=b"<html><script></script></html>")
    with pytest.raises(documents.HrDocumentError, match="makrami"):
        await _upload(hr.id, person.id, content=docx_bytes(macro=True))
    assert await _count(person.id) == 0


async def test_upload_default_audience_follows_kind() -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="uop")
    protocol, _ = await _upload(
        hr.id, person.id, kind="protocol", title="Protokół przekazania"
    )
    other, _ = await _upload(hr.id, person.id, kind="other", title="Notatka")
    assert (
        protocol.visible_to_person,
        protocol.visible_to_payroll,
        protocol.visible_to_equipment,
    ) == (True, False, True)
    assert (other.visible_to_person, other.visible_to_payroll) == (True, False)


@pytest.mark.parametrize(
    ("kind", "valid_until", "message"),
    [
        ("certificate", date(2027, 6, 30), "oświadczenie"),
        ("statement", None, "ważny do"),
    ],
)
async def test_student_status_needs_statement_with_date(
    kind, valid_until, message
) -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="zlecenie")
    with pytest.raises(documents.HrDocumentError, match=message):
        await _upload(
            hr.id,
            person.id,
            kind=kind,
            valid_until=valid_until,
            purpose="student_status",
        )


# ── Oświadczenie studenta zasila kartotekę (bez drugiego przypomnienia) ──────


async def test_student_statement_sets_exemption_date_in_profile() -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="zlecenie", name="Celina Testowa")
    until = business_today() + timedelta(days=200)

    _, sync = await _upload(
        hr.id, person.id, valid_until=until, purpose="student_status"
    )

    assert sync == {"status": "updated", "until": until}
    profile = await _profile(person.id)
    assert profile.student_contribution_exempt is True
    assert profile.contribution_exempt_until == until


async def test_new_statement_moves_date_that_came_from_previous_one() -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="zlecenie")
    first = business_today() + timedelta(days=20)
    later = business_today() + timedelta(days=380)
    await _upload(hr.id, person.id, valid_until=first, purpose="student_status")

    _, sync = await _upload(
        hr.id, person.id, valid_until=later, purpose="student_status"
    )

    assert sync["status"] == "updated"
    assert (await _profile(person.id)).contribution_exempt_until == later


async def test_earlier_manual_date_in_profile_stays() -> None:
    """Dzień przed 26. urodzinami wpisany przez Kadry wygrywa z późniejszym oświadczeniem."""

    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    birthday_limit = business_today() + timedelta(days=90)
    person = await make_user(
        employment_type="zlecenie",
        student_contribution_exempt=True,
        contribution_exempt_until=birthday_limit,
    )

    _, sync = await _upload(
        hr.id,
        person.id,
        valid_until=business_today() + timedelta(days=300),
        purpose="student_status",
    )

    assert sync == {"status": "kept_earlier", "until": birthday_limit}
    assert (await _profile(person.id)).contribution_exempt_until == birthday_limit


async def test_statement_outside_mandate_or_in_past_does_not_touch_profile() -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    b2b = await make_user(employment_type="b2b")
    mandate = await make_user(employment_type="zlecenie")

    _, on_b2b = await _upload(
        hr.id,
        b2b.id,
        valid_until=business_today() + timedelta(days=100),
        purpose="student_status",
    )
    _, past = await _upload(
        hr.id,
        mandate.id,
        valid_until=business_today() - timedelta(days=1),
        purpose="student_status",
    )

    assert on_b2b["status"] == "not_zlecenie"
    assert past["status"] == "past"
    assert (await _profile(b2b.id)).student_contribution_exempt is False
    assert (await _profile(mandate.id)).contribution_exempt_until is None


async def test_changing_date_of_latest_statement_moves_profile_date() -> None:
    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="zlecenie")
    first = business_today() + timedelta(days=40)
    fixed = business_today() + timedelta(days=60)
    document, _ = await _upload(
        hr.id, person.id, valid_until=first, purpose="student_status"
    )

    async with AsyncSessionLocal() as db:
        actor = await db.get(User, hr.id)
        row = await db.get(HrDocument, document.id)
        _, sync = await documents.update(db, row, actor=actor, valid_until=fixed)
        await db.commit()

    assert sync["status"] == "updated"
    assert (await _profile(person.id)).contribution_exempt_until == fixed


async def test_student_statement_feeds_existing_reminder() -> None:
    """Przypomnienie dla Płac przychodzi z istniejącej pętli etapu 2 — bez nowej."""

    from app.services.hr import student_reminders

    hr = await make_user("recruiter", grants=("people_admin",), profile=False)
    person = await make_user(employment_type="zlecenie")
    until = business_today() + timedelta(days=25)
    await _upload(hr.id, person.id, valid_until=until, purpose="student_status")

    async with AsyncSessionLocal() as db:
        due = await student_reminders.due_people(db, business_today())
    assert (person.id, person.name, until) in due
