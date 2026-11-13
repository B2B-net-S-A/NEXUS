"""Umowa szkoleniowa: szablon, kontekst, kwoty, dane trenera i nazwa pliku (bez bazy)."""

from __future__ import annotations

import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import docx
import pytest
from docxtpl import DocxTemplate
from jinja2 import StrictUndefined

from app.models.training import Training
from app.services.cv_pdf_preview import soffice_path
from app.services.trainings import agreement
from app.services.trainings.errors import TrainingError

NBSP = " "
DAY = date(2026, 11, 13)
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)

PARTNER = {
    "full_name": "Jan Kowalski",
    "company": "Jan Kowalski Szkolenia & Doradztwo",
    "address": "ul. Prosta 1",
    "postal_city": "00-001 Warszawa",
    "nip": "1234567890",
    "regon": "123456789",
    "phone": "+48 600 000 000",
    "email": "jan@example.com",
}


def _full_training(**overrides) -> Training:
    values = dict(
        id=12,
        title="Excel dla analityków",
        topic="Tabele przestawne",
        status="accepted",
        session_date=date(2026, 11, 20),
        time_from="10:00",
        time_to="14:00",
        duration_minutes=240,
        platform="Microsoft Teams",
        expected_participants=15,
        participant_materials="Skrypt PDF\nĆwiczenia w Excelu",
        deliverables=[
            {
                "key": "materials",
                "label": "Skrypt",
                "required": True,
                "format": "PDF",
                "due_days": -2,
            },
            {
                "key": "presentation",
                "label": "Slajdy",
                "required": True,
                "format": "PPTX",
                "due_days": 3,
            },
            {
                "key": "audio",
                "label": "Nagranie",
                "required": False,
                "format": "MP3",
                "due_days": 3,
            },
            {
                "key": "other",
                "label": "Pliki ćwiczeń",
                "required": True,
                "format": "XLSX",
                "due_days": 3,
            },
        ],
        agenda=[
            {"title": "Wprowadzenie", "minutes": 30},
            {"title": "Tabele przestawne", "minutes": 90},
            {"title": "Pytania", "minutes": 0},
        ],
        own_materials="Autorski zbiór zadań z 2024 r.",
        third_party_materials="",
        extra_terms="Nagranie tylko do użytku wewnętrznego.",
        knowledge_test=False,
        fee_prep=Decimal("2000"),
        fee_delivery=Decimal("3000"),
        fee_presentation=Decimal("500"),
        fee_audio=None,
        fee_rights=Decimal("700"),
        agreement_number="SZK/12/2026",
        partner=dict(PARTNER),
    )
    values.update(overrides)
    return Training(**values)


def _minimal_training(**overrides) -> Training:
    values = dict(
        id=7,
        title="Szkolenie",
        topic="",
        status="accepted",
        session_date=None,
        time_from="",
        time_to="",
        duration_minutes=None,
        platform="",
        expected_participants=None,
        participant_materials="",
        deliverables=[],
        agenda=[],
        own_materials="",
        third_party_materials="",
        extra_terms="",
        knowledge_test=False,
        fee_prep=None,
        fee_delivery=Decimal("1000"),
        fee_presentation=None,
        fee_audio=None,
        fee_rights=None,
        agreement_number="",
        partner={},
    )
    values.update(overrides)
    return Training(**values)


def _context(training: Training, partner: dict | None = None) -> dict:
    return agreement.build_context(
        training,
        PARTNER if partner is None else partner,
        company_email="szkolenia@example.com",
        agreement_date=DAY,
    )


def _text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


# ── Szablon ──────────────────────────────────────────────────────────────────


def test_template_renders_full_context():
    text = _text(agreement.render_docx(_context(_full_training())))
    assert "{{" not in text and "{%" not in text
    assert "zawarta w dniu 13.11.2026 roku" in text
    assert "Panem Jan Kowalski prowadzącym działalność" in text
    assert "pod firmą: Jan Kowalski Szkolenia & Doradztwo," in text
    assert "ul. Prosta 1, 00-001 Warszawa, NIP: 1234567890, REGON: 123456789," in text
    assert "Tel. +48 600 000 000, Adres e-mail: jan@example.com" in text
    assert "terminach: 20.11.2026 r., w godzinach 10:00–14:00." in text
    assert (
        f"6{NBSP}200,00 zł netto (słownie: sześć tysięcy dwieście złotych 00/100 netto)"
        in text
    )
    assert "Zamawiający: szkolenia@example.com" in text
    assert "Partner: jan@example.com" in text
    assert "Moduł 1:\nWprowadzenie (30 min)" in text
    assert "Moduł 2:\nTabele przestawne (1 godz. 30 min)" in text
    assert "Moduł 3:\nPytania" in text
    assert "Moduł 4:" not in text
    assert "materiały szkoleniowe dla uczestników – TAK;" in text
    assert "prezentację – TAK;" in text
    assert "pliki audio – NIE;" in text
    assert (
        f"A. Przygotowanie programu i materiałów szkoleniowych:\n2{NBSP}000,00 zł netto"
        in text
    )
    assert "D. Przygotowanie i przekazanie plików audio:\n0,00 zł netto" in text
    assert "Szkolenie nie kończy się egzaminem." in text
    assert "Nagranie tylko do użytku wewnętrznego." in text
    # Dane spółki zostają z wzoru, pól do wypełnienia nie ma.
    assert "KRS pod nr 0000387063" in text
    leftovers = [
        line
        for line in text.splitlines()
        if re.search(r"_{3,}|…{2,}|TAK / NIE|/ią|/cą", line)
        and not re.fullmatch(r"[\s_]*(ZAMAWIAJĄCY)?[\s_]*(PARTNER)?\s*", line)
    ]
    assert leftovers == []


def test_template_renders_minimal_context():
    text = _text(
        agreement.render_docx(
            _context(_minimal_training(), {"full_name": "Anna Nowak"})
        )
    )
    assert "{{" not in text and "{%" not in text
    assert "Panią Anna Nowak prowadzącą działalność" in text
    assert "zwana w dalszej części umowy" in text
    assert "REGON" not in text.split("Dane kontaktowe")[0]
    assert "Tel." not in text
    assert "terminach: w terminie wskazanym w Załączniku nr 1." in text
    assert (
        "ŁĄCZNE WYNAGRODZENIE:\n1{NBSP}000,00 zł netto".replace("{NBSP}", NBSP) in text
    )
    assert "Moduł 1:" not in text
    assert "Brak." in text


def test_every_template_tag_is_supplied_by_build_context():
    template = DocxTemplate(str(agreement.TEMPLATE_PATH))
    env = agreement.jinja_env(undefined=StrictUndefined)
    for context in (_context(_full_training()), _context(_minimal_training(), {})):
        assert template.get_undeclared_template_variables(env) <= set(context)
        # StrictUndefined: brak klucza w zagnieżdżonym słowniku też wywraca render.
        DocxTemplate(str(agreement.TEMPLATE_PATH)).render(context, jinja_env=env)


def test_template_has_no_personal_data():
    text = _text(agreement.TEMPLATE_PATH.read_bytes())
    tags = set(re.findall(r"\{\{\s*([\w.]+)", text))
    assert {
        "partner.name_instrumental",
        "partner.company",
        "partner.nip",
        "partner.email",
    } <= tags
    # Jedyne numery i adresy to dane spółki (NIP, KRS, skrzynka IOD).
    assert set(re.findall(r"\b\d{9,10}\b", text)) <= {"5711707392", "0000387063"}
    assert set(re.findall(r"[\w.]+@[\w.]+", text)) <= {"iod@b2bnetwork.pl"}


def test_multiline_fields_become_line_breaks():
    data = agreement.render_docx(_context(_full_training()))
    document = docx.Document(io.BytesIO(data))
    assert any("Skrypt PDF\nĆwiczenia w Excelu" in p.text for p in document.paragraphs)


@pytest.mark.skipif(
    soffice_path() is None, reason="brak LibreOffice (soffice) lokalnie"
)
async def test_render_pdf_with_libreoffice():
    pdf = await agreement.render_pdf(_context(_full_training()))
    assert pdf.startswith(b"%PDF-")


# ── Kontekst ─────────────────────────────────────────────────────────────────


def test_amounts_total_and_words():
    fees = _context(_full_training())["fees"]
    assert fees["prep"] == f"2{NBSP}000,00"
    assert fees["audio"] == "0,00"
    assert fees["total"] == f"6{NBSP}200,00"
    assert fees["total_words"] == "sześć tysięcy dwieście złotych 00/100"
    assert agreement.format_money(Decimal("1234567.5")) == f"1{NBSP}234{NBSP}567,50"
    odd = _context(_full_training(fee_rights=Decimal("700.55")))["fees"]
    assert odd["total"] == f"6{NBSP}200,55"
    assert odd["total_words"].endswith("złotych 55/100")


def test_deliverables_flags_formats_and_due_dates():
    deliv = _context(_full_training())["deliv"]
    assert deliv["materials"] == {
        "flag": "TAK",
        "format": "PDF",
        "due": "2 dni przed szkoleniem (do 18.11.2026 r.)",
    }
    assert deliv["audio"]["flag"] == "NIE"
    assert deliv["audio"]["format"] == "nie dotyczy"
    assert deliv["other"] == "Pliki ćwiczeń"
    assert deliv["files_format"] == (
        "materiały dla uczestników: PDF; prezentacja: PPTX; Pliki ćwiczeń: XLSX"
    )
    assert "prezentacja: 3 dni po szkoleniu (do 23.11.2026 r.)" in deliv["files_due"]
    assert agreement.due_text(1, None) == "1 dzień po szkoleniu"
    assert (
        agreement.due_text(0, date(2026, 11, 20))
        == "w dniu szkolenia (do 20.11.2026 r.)"
    )
    minimal = _context(_minimal_training())["deliv"]
    assert minimal["files_format"] == "nie dotyczy"
    assert minimal["other"] == "brak"


def test_rights_list_works_from_deliverables():
    rights = _context(_full_training())["rights"]
    assert rights["works"] == (
        "program i agenda szkolenia; materiały dla uczestników; prezentacja; Pliki ćwiczeń"
    )
    assert rights["third_party"] == "brak"


def test_knowledge_test_wording():
    assert (
        _context(_full_training())["exam_text"] == "Szkolenie nie kończy się egzaminem."
    )
    with_test = _context(_full_training(knowledge_test=True))["exam_text"]
    assert "testem wiedzy" in with_test and "bez egzaminu" in with_test
    text = _text(agreement.render_docx(_context(_full_training(knowledge_test=True))))
    assert with_test in text


def test_gender_forms_from_payload_beat_first_name_guess():
    assert _context(_full_training(), {**PARTNER, "gender": "f"})["g"]["pan"] == "Panią"
    assert (
        _context(_full_training(), {"full_name": "Kuba Nowak"})["g"]["pan"] == "Panem"
    )
    assert (
        _context(_full_training(), {"full_name": "Ewa Nowak"})["g"]["zwany"] == "zwana"
    )


# ── Dane trenera ─────────────────────────────────────────────────────────────


def test_missing_partner_fields_lists_polish_labels():
    assert agreement.missing_partner_fields(PARTNER) == []
    assert agreement.missing_partner_fields({"full_name": "Jan", "nip": "  "}) == [
        "nazwa firmy",
        "adres działalności",
        "NIP",
        "adres e-mail",
    ]
    assert agreement.PARTNER_REQUIRED == (
        "full_name",
        "company",
        "address",
        "nip",
        "email",
    )


def test_split_address():
    assert agreement.split_address("ul. Prosta 1, 00-001 Warszawa") == (
        "ul. Prosta 1",
        "00-001 Warszawa",
    )
    assert agreement.split_address("Prosta 1 00-001 Stare Miasto") == (
        "Prosta 1",
        "00-001 Stare Miasto",
    )
    assert agreement.split_address("Prosta 1") == ("Prosta 1", "")


def test_partner_from_sources_prefers_b2b_payload_then_candidate():
    contract = SimpleNamespace(candidate_email="jan@example.com", candidate_phone=None)
    generated = SimpleNamespace(
        render_payload={
            "partner_name": "Jan Kowalski",
            "partner_instrumental": "Janem Kowalskim",
            "gender": "m",
            "partner_legal_name": "JK Szkolenia",
            "partner_business_address": "ul. Prosta 1, 00-001 Warszawa",
            "partner_nip": "1234567890",
            "partner_regon": "",
            "partner_phone": "600000000",
            "partner_email": "inny@example.com",
        },
        partner_name="Jan Kowalski",
        partner_legal_name=None,
        partner_nip=None,
    )
    candidate = SimpleNamespace(
        name="Jan",
        lastname="Kowalski",
        legal_name="Stara nazwa",
        nip="999",
        regon="123456789",
        business_address="",
        phone="700",
        email="c@example.com",
    )
    partner = agreement.partner_from_sources(
        contract=contract, generated=generated, candidate=candidate
    )
    assert partner == {
        "full_name": "Jan Kowalski",
        "company": "JK Szkolenia",
        "address": "ul. Prosta 1",
        "postal_city": "00-001 Warszawa",
        "nip": "1234567890",
        "regon": "123456789",
        "phone": "600000000",
        "email": "jan@example.com",
        "gender": "m",
        "name_instrumental": "Janem Kowalskim",
    }
    only_candidate = agreement.partner_from_sources(
        contract=contract, candidate=candidate
    )
    assert only_candidate["full_name"] == "Jan Kowalski"
    assert only_candidate["company"] == "Stara nazwa"
    assert only_candidate["gender"] == "" and only_candidate["name_instrumental"] == ""
    assert set(only_candidate) == set(agreement.PARTNER_KEYS) | set(
        agreement.EXTRA_KEYS
    )


# ── Nazwa pliku ──────────────────────────────────────────────────────────────


def test_file_name_has_no_polish_characters():
    training = _full_training(
        partner={"full_name": "Łukasz Żółć"}, agreement_number="SZK/12/2026"
    )
    name = agreement.file_name(training)
    assert name == "Umowa szkoleniowa SZK-12-2026 Zolc Lukasz.pdf"
    assert name.isascii()
    assert agreement.file_name(training, suffix="podpisana") == (
        "Umowa szkoleniowa SZK-12-2026 Zolc Lukasz podpisana.pdf"
    )


# ── Generowanie ──────────────────────────────────────────────────────────────


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(agreement.storage_service, "STORAGE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def fake_pdf(monkeypatch):
    seen: list[dict] = []

    async def render(context):
        seen.append(context)
        return b"%PDF-1.7 umowa " + context["agreement_date"].encode()

    monkeypatch.setattr(agreement, "render_pdf", render)
    return seen


async def test_generate_freezes_pdf_and_snapshot(storage, fake_pdf):
    training = _full_training(agreement_number="", partner={})
    await agreement.generate(
        None,
        training,
        partner={**PARTNER, "junk": "x"},
        company_email="s@example.com",
        now=NOW,
    )
    assert training.agreement_number == "SZK/12/2026"
    assert (
        training.partner["full_name"] == "Jan Kowalski"
        and "junk" not in training.partner
    )
    stored = (storage / training.agreement_pdf_path).read_bytes()
    assert stored.startswith(b"%PDF-")
    assert training.agreement_pdf_path.startswith("trainings/12/agreement/")
    assert training.agreement_pdf_sha256 == agreement.hashlib.sha256(stored).hexdigest()
    assert training.agreement_generated_at == NOW
    assert fake_pdf[0]["company_email"] == "s@example.com"


async def test_generate_refuses_incomplete_partner(storage, fake_pdf):
    with pytest.raises(TrainingError) as error:
        await agreement.generate(
            None,
            _full_training(),
            partner={"full_name": "Jan"},
            company_email="",
            now=NOW,
        )
    assert error.value.status == 422 and error.value.code == "partner_incomplete"
    assert "NIP" in error.value.message
    assert fake_pdf == []


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"status": "quoted"}, "wrong_status"),
        ({"trainer_signed_at": NOW}, "already_signed"),
        (
            {
                "fee_prep": None,
                "fee_delivery": None,
                "fee_presentation": None,
                "fee_rights": None,
            },
            "fees_missing",
        ),
    ],
)
async def test_generate_refusals(storage, fake_pdf, overrides, code):
    with pytest.raises(TrainingError) as error:
        await agreement.generate(
            None,
            _full_training(**overrides),
            partner=PARTNER,
            company_email="",
            now=NOW,
        )
    assert error.value.code == code


async def test_regenerate_before_trainer_signs_keeps_number(storage, fake_pdf):
    training = _full_training(agreement_number="SZK/12/2025")
    await agreement.generate(None, training, partner=PARTNER, company_email="", now=NOW)
    assert training.agreement_number == "SZK/12/2025"
