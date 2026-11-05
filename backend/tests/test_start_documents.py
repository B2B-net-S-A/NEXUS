"""Dokumenty do startu: reguły bez bazy (0649, decyzje Artura 05.11.2026)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document

from app.services import notification_delivery
from app.services import start_documents as svc
from app.services import start_documents_fill as fill
from app.services import start_documents_mail as mail
from app.services import start_documents_schema as schema
from app.services.hr.calendar import WorkCalendar
from app.tasks import start_documents_sweeper as sweeper

BACKEND = Path(__file__).resolve().parents[1]
# Poprawny numer z oficjalnego algorytmu, nieprzypisany do nikogo z tej bazy.
VALID_PESEL = "44051401458"


def _document(**fields):
    base = dict(
        id=1,
        name="NDA",
        note=None,
        kind=svc.KIND_FILE,
        required=True,
        offset_days=-2,
        link_url=None,
        fill_from_agreement=False,
        template_name=None,
    )
    return SimpleNamespace(**{**base, **fields})


def _item(state: str = svc.STATE_MISSING, **fields) -> svc.ItemState:
    return svc.ItemState(document=_document(**fields), row=None, state=state)


def _pair(*items: svc.ItemState, **fields) -> svc.PairState:
    base = dict(
        candidate_id=1,
        job_id=2,
        client_id=3,
        candidate_name="Anna Testowa",
        job_title="Analityk",
        client_name="Nordea",
        stage="hired",
        start_date=date(2026, 11, 9),
        contract_id=None,
        agreement_number="1/2026",
        recruiter_id=10,
        delivery_lead_id=20,
        items=items,
        deadline=date(2026, 11, 5),
    )
    return svc.PairState(**{**base, **fields})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (VALID_PESEL, VALID_PESEL),
        (f" {VALID_PESEL[:5]} {VALID_PESEL[5:]} ", VALID_PESEL),
        ("44051401459", None),
        ("4405140145", None),
        ("440514014580", None),
        ("abcdefghijk", None),
        ("", None),
    ],
)
def test_pesel_needs_eleven_digits_and_a_correct_checksum(raw, expected) -> None:
    assert svc.normalize_pesel(raw) == expected


def test_agreement_ticks_itself_only_after_signature() -> None:
    document = _document(kind=svc.KIND_AGREEMENT)
    assert svc.item_state(document, None, agreement_signed=False) == svc.STATE_MISSING
    assert svc.item_state(document, None, agreement_signed=True) == svc.STATUS_DELIVERED


def test_decision_of_the_delivery_lead_beats_the_automatic_tick() -> None:
    document = _document(kind=svc.KIND_AGREEMENT)
    row = SimpleNamespace(status=svc.STATUS_NOT_APPLICABLE)
    assert (
        svc.item_state(document, row, agreement_signed=False)
        == svc.STATUS_NOT_APPLICABLE
    )


def test_a_file_never_ticks_itself() -> None:
    assert svc.item_state(_document(), None, agreement_signed=True) == svc.STATE_MISSING


def test_returned_document_does_not_count_as_done() -> None:
    assert not _item(svc.STATUS_RETURNED).done
    assert _item(svc.STATUS_DELIVERED).done
    assert _item(svc.STATUS_NOT_APPLICABLE).done


def test_optional_document_stays_out_of_the_set() -> None:
    state = _pair(
        _item(svc.STATUS_DELIVERED),
        _item(name="KRK"),
        _item(name="Certyfikaty", required=False),
    )
    assert (state.done_count, len(state.required)) == (1, 2)
    assert [i.document.name for i in state.missing] == ["KRK"]
    assert not state.complete


def test_only_optional_documents_missing_means_complete() -> None:
    assert _pair(_item(required=False)).complete


def test_owner_is_the_delivery_lead_when_there_is_no_recruiter() -> None:
    assert _pair(recruiter_id=None).owner_id == 20
    assert _pair().owner_id == 10


def test_deadline_counts_working_days_back_from_start() -> None:
    calendar = WorkCalendar()
    # Poniedziałek 09.11 minus 2 dni robocze to czwartek 05.11, nie sobota.
    assert svc.deadline_of([_item()], date(2026, 11, 9), calendar) == date(2026, 11, 5)


def test_deadline_ignores_what_is_done_and_optional() -> None:
    items = [
        _item(svc.STATUS_DELIVERED, offset_days=-10),
        _item(required=False, offset_days=-20),
        _item(offset_days=-1),
    ]
    assert svc.deadline_of(items, date(2026, 11, 9), WorkCalendar()) == date(
        2026, 11, 6
    )


def test_no_start_date_means_no_deadline() -> None:
    assert svc.deadline_of([_item()], None, WorkCalendar()) is None


@pytest.mark.parametrize(
    ("deadline", "tone"),
    [
        (None, "calm"),
        (date(2026, 11, 4), "late"),
        (date(2026, 11, 5), "today"),
        (date(2026, 11, 6), "calm"),
    ],
)
def test_tone_follows_the_deadline(deadline, tone) -> None:
    assert svc.tone_of(deadline, date(2026, 11, 5)) == tone


def test_working_days_between_skips_the_weekend_and_past_dates() -> None:
    calendar = WorkCalendar()
    assert svc.working_days_between(calendar, date(2026, 11, 6), date(2026, 11, 9)) == 1
    assert svc.working_days_between(calendar, date(2026, 11, 9), date(2026, 11, 2)) == 0


# ── Przypomnienia ─────────────────────────────────────────────────────────────


def test_mail_starts_five_working_days_before_start_or_after_the_deadline() -> None:
    assert sweeper.needs_mail(_pair(_item(), working_days_to_start=5))
    assert not sweeper.needs_mail(_pair(_item(), working_days_to_start=6))
    assert sweeper.needs_mail(_pair(_item(), working_days_to_start=9, tone="late"))
    assert not sweeper.needs_mail(_pair(_item(), working_days_to_start=None))


def test_delivery_lead_joins_two_working_days_before_start() -> None:
    assert sweeper.reaches_dl(_pair(_item(), working_days_to_start=2))
    assert not sweeper.reaches_dl(_pair(_item(), working_days_to_start=3))
    assert sweeper.reaches_dl(_pair(_item(), working_days_to_start=0, working=True))


def test_head_of_recruitment_only_on_the_day_of_start() -> None:
    day = date(2026, 11, 9)
    assert sweeper.reaches_hor(_pair(_item(), start_date=day), day)
    assert not sweeper.reaches_hor(_pair(_item(), start_date=day), date(2026, 11, 10))


def test_digest_lists_people_and_cuts_a_long_list() -> None:
    states = [_pair(_item(name="KRK"), candidate_name=f"Osoba {n}") for n in range(7)]
    message = sweeper.digest_message(states)
    assert "Osoba 0: KRK, start 09.11" in message
    assert "Osoba 5" not in message
    assert message.endswith("i jeszcze 2")


# ── Mail do konsultanta ───────────────────────────────────────────────────────


def _mail_pair() -> svc.PairState:
    return _pair(
        _item(svc.STATUS_DELIVERED, name="Umowa", kind=svc.KIND_AGREEMENT),
        _item(name="NDA"),
        _item(
            name="Wyciąg z KRK",
            note="i oświadczenie",
            link_url="https://ekrk.ms.gov.pl/ep-web",
        ),
        _item(name="PESEL", kind=svc.KIND_PESEL),
        _item(name="Certyfikaty", required=False),
    )


def test_list_skips_the_agreement_and_everything_already_delivered() -> None:
    texts = [line.text for line in mail.lines_for(_mail_pair().items)]
    assert not any("Umowa" in text for text in texts)
    assert texts[0] == "NDA"
    assert texts[1] == "Wyciąg z KRK: i oświadczenie"
    assert texts[3] == "Certyfikaty (jeśli jest)"


def test_pesel_is_requested_by_phone_never_by_mail() -> None:
    _subject, body, text = mail.render(_mail_pair(), [])
    assert "telefonicznie, nie mailem" in body
    assert "telefonicznie, nie mailem" in text


def test_mail_text_for_the_consultant_has_no_em_dash_and_no_second_signature() -> None:
    subject, body, text = mail.render(_mail_pair(), ["NDA.docx"])
    for content in (subject, body, text):
        assert "—" not in content
        assert "Pozdrawiamy" not in content
    assert subject == "Dokumenty przed startem u klienta Nordea"
    assert "Prosimy o komplet do 05.11." in text
    assert "Wzory są w załączniku." in text


def test_mail_escapes_text_from_the_client_list() -> None:
    state = _pair(_item(name="<b>NDA</b>", link_url='https://x.pl/"a'))
    _subject, body, _text = mail.render(state, [])
    assert "<b>NDA</b>" not in body
    assert "&lt;b&gt;NDA&lt;/b&gt;" in body
    assert 'href="https://x.pl/&quot;a"' in body


def test_filled_template_carries_the_name_of_the_person() -> None:
    document = _document(template_name="NDA.docx", fill_from_agreement=True)
    assert mail.attachment_name(document, _pair()) == "NDA Anna Testowa.docx"
    plain = _document(template_name="Wzor.pdf")
    assert mail.attachment_name(plain, _pair()) == "Wzor.pdf"


# ── Wypełnianie wzoru ─────────────────────────────────────────────────────────


def _template() -> bytes:
    document = Document()
    supplier = document.add_table(rows=1, cols=2)
    supplier.cell(0, 0).text = "Supplier's name"
    supplier.cell(0, 0).add_paragraph("B2B.net SA")
    supplier.cell(0, 1).text = "Company number"
    supplier.cell(0, 1).add_paragraph("NIP: 5711707392")
    recipient = document.add_table(rows=3, cols=2)
    recipient.cell(0, 0).text = "Consultant's name (hereinafter)"
    recipient.cell(0, 1).text = "Company number/social security number (if applicable)"
    recipient.cell(1, 0).text = "Street, box"
    recipient.cell(1, 1).text = "Contact person (if applicable)"
    recipient.cell(2, 0).text = "Postal code and city"
    recipient.cell(2, 1).text = "Telephone number (including area code)"
    document.core_properties.author = "Ktoś z firmy klienta"
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _cells(data: bytes) -> list[list[str]]:
    document = Document(io.BytesIO(data))
    return [
        [cell.text for cell in row.cells] for t in document.tables for row in t.rows
    ]


def test_template_gets_data_from_the_agreement_and_leaves_the_supplier_alone() -> None:
    values = fill.values_from_payload(
        {
            "partner_name": "Anna Testowa",
            "partner_nip": "1234567890",
            "partner_business_address": "ul. Prosta 1, 00-001 Warszawa",
            "partner_phone": "+48 500 000 000",
        }
    )
    filled = fill.fill_template(_template(), values)
    rows = _cells(filled)
    assert rows[0] == ["Supplier's name\nB2B.net SA", "Company number\nNIP: 5711707392"]
    assert rows[1][0].endswith("\nAnna Testowa")
    assert rows[1][1].endswith("\nNIP: 1234567890")
    assert rows[2][0].endswith("\nul. Prosta 1")
    assert rows[2][1] == "Contact person (if applicable)"
    assert rows[3][0].endswith("\n00-001 Warszawa")
    assert rows[3][1].endswith("\n+48 500 000 000")


def test_filled_template_has_no_author_from_the_client_file() -> None:
    filled = fill.fill_template(_template(), {"name": "Anna"})
    assert Document(io.BytesIO(filled)).core_properties.author == ""


def test_missing_data_leaves_the_cell_as_it_was() -> None:
    rows = _cells(fill.fill_template(_template(), fill.values_from_payload(None)))
    assert rows[1][0] == "Consultant's name (hereinafter)"


def test_unreadable_template_comes_back_unchanged() -> None:
    assert fill.fill_template(b"%PDF-1.4", {"name": "Anna"}) == b"%PDF-1.4"


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("ul. Prosta 1, 00-001 Warszawa", ("ul. Prosta 1", "00-001 Warszawa")),
        ("Rynek 5", ("Rynek 5", None)),
        ("  ", (None, None)),
        (None, (None, None)),
    ],
)
def test_address_splits_into_street_and_city(address, expected) -> None:
    assert fill.split_address(address) == expected


# ── Lustra i strażnicy ────────────────────────────────────────────────────────


def test_entrypoint_and_migration_use_one_source_of_ddl() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import start_documents_schema" in entrypoint
    assert "*_START_DOCUMENTS_TABLE_DDL," in entrypoint
    for statement in schema.ENUM_DDL:
        assert statement in entrypoint
    migration = (BACKEND / "alembic/versions/0649_start_documents.py").read_text(
        encoding="utf-8"
    )
    assert "from app.services.start_documents_schema import" in migration


def test_mail_kind_is_required_so_it_reaches_people() -> None:
    assert "start_documents" in notification_delivery.REQUIRED_KINDS


def test_loop_stands_still_on_staging() -> None:
    staging = (BACKEND / "app/core/staging.py").read_text(encoding="utf-8")
    assert '"start_documents_sweeper"' in staging


def test_pesel_stays_out_of_history_and_the_card() -> None:
    api = (BACKEND / "app/api/start_documents.py").read_text(encoding="utf-8")
    assert '"pesel": row' not in api
    out = api[api.index("def _item_out") : api.index("async def _names")]
    assert "row.pesel" in out  # tylko jako „czy jest wartość”
    assert '"pesel"' not in out
