"""Umowa zlecenia z Generatora Umów (decyzje Artura 26.10.2026).

Część bez bazy: szablon (formy rodzajowe, lista czynności, DPA warunkowe,
brak metadanych wzoru), walidacja (PESEL, minimalna stawka każdego roku
okresu) i zapis formularza bez PESEL-u, dowodu i adresu.

Część z bazą (CI): wydanie przez ``/mandate/render`` zakłada wiersz rejestru
„zlecenie” bez numeru z puli B2B, „Popraw” odmawia, ponowne pobranie wydaje
plik bez danych wrażliwych, podpis zakłada kontrakt typu zlecenie z okresem
i stawką godzinową, aneks B2B nie widzi umowy zlecenia.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.schemas.b2b_contract_generator import B2BMandateRenderRequest
from app.services.b2b_contract_filename import mandate_file_name
from app.services.b2b_contract_generator import mandate

# Fikcyjny PESEL z poprawną cyfrą kontrolną (nie należy do nikogo z firmy).
PESEL = "44051401458"
RATES = {2026: Decimal("31.40"), 2027: Decimal("33.00")}


def _payload(**overrides) -> B2BMandateRenderRequest:
    data = {
        "signing_date": date(2026, 10, 27),
        "period_from": date(2026, 11, 1),
        "period_to": date(2027, 1, 31),
        "gender": "f",
        "partner_name": "Anna Testowa",
        "partner_instrumental": "Anną Testową",
        "partner_email": "anna@example.com",
        "tasks": ["administracja platformą", "wsparcie wdrożeń"],
        "gross_hourly_rate": 45.5,
        "pesel": PESEL,
        "home_address": "ul. Fikcyjna 1, 00-001 Warszawa",
        "id_document": "ABC123456",
    }
    data.update(overrides)
    return B2BMandateRenderRequest(**data)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml))


# ── Szablon ──────────────────────────────────────────────────────────────────


def test_html_preview_fills_the_parties_tasks_period_and_rate():
    html = mandate.render_html(_payload())
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert "{{" not in html and "{%" not in html
    assert "Panią Anną Testową" in text
    assert "zamieszkałą pod adresem: ul. Fikcyjna 1" in text
    assert "legitymującą się dowodem osobistym o numerze: ABC123456" in text
    assert f"PESEL: {PESEL}" in text
    assert "Zwaną dalej" in text
    assert "a) administracja platformą;" in text
    assert "b) wsparcie wdrożeń." in text
    assert "na okres od 01.11.2026 r. do 31.01.2027 r." in text
    assert (
        "45,50 zł brutto za jedną godzinę (słownie: czterdzieści pięć złotych "
        "pięćdziesiąt groszy)" in text
    )
    assert "zawarta dnia 27.10.2026 r." in text
    # Ustępy § 1 po liście czynności liczą od 2, jak w Wordzie.
    assert '<ol start="2">' in html


def test_dpa_is_optional_with_its_mention_and_annex_list_entry():
    with_dpa = mandate.render_html(_payload(dpa_purpose="obsługa systemu CRM klienta"))
    without = mandate.render_html(_payload(with_dpa=False))
    assert "UMOWA POWIERZENIA PRZETWARZANIA DANYCH OSOBOWYCH" in with_dpa
    assert "Cel przetwarzania: obsługa systemu CRM klienta" in with_dpa
    assert "Załącznik nr 2" in with_dpa
    for phrase in (
        "UMOWA POWIERZENIA PRZETWARZANIA",
        "Załącznik nr 2",
        "Strony zawierają Umowę Powierzenia",
    ):
        assert phrase not in without
    # Deklaracja Poufności zostaje zawsze.
    assert "DEKLARACJA POUFNOŚCI" in without


def test_default_dpa_purpose_is_the_text_of_the_template():
    html = mandate.render_html(_payload(dpa_purpose="  "))
    assert "Cel przetwarzania: " + mandate.DEFAULT_DPA_PURPOSE in html


def test_masculine_forms_for_a_man():
    text = re.sub(
        r"<[^>]+>",
        " ",
        mandate.render_html(
            _payload(gender="m", partner_name="Jan Testowy", partner_instrumental=None)
        ),
    )
    assert "Panem Jan Testowy" in text
    assert "zamieszkałym pod adresem" in text
    assert "zapoznałem się z niniejszą deklaracją" in text


def test_docx_has_no_placeholders_and_dots_where_sensitive_data_is_missing():
    filled = _docx_text(mandate.render_docx(_payload()))
    assert "{{" not in filled and "{%" not in filled
    assert PESEL in filled and "ABC123456" in filled
    blank = _docx_text(
        mandate.render_docx(_payload(pesel=None, id_document=None, home_address=None))
    )
    assert PESEL not in blank
    assert "PESEL: …" in blank
    assert "dowodem osobistym o numerze: …" in blank


def test_template_file_carries_no_author_or_sharepoint_parts():
    with zipfile.ZipFile(mandate.DOCX_TEMPLATE) as zf:
        names = zf.namelist()
        core = zf.read("docProps/core.xml").decode("utf-8")
        assert not [
            n for n in names if n.startswith(("customXml/", "word/webextensions/"))
        ]
        assert "docProps/custom.xml" not in names
        for name in names:
            if name.startswith("word/") and name.endswith(".xml"):
                assert b"<w:highlight" not in zf.read(name), name
    assert "<dc:creator>B2B.net S.A.</dc:creator>" in core
    assert "<cp:lastModifiedBy>NEXUS</cp:lastModifiedBy>" in core


def test_generated_file_carries_no_author_metadata():
    with zipfile.ZipFile(io.BytesIO(mandate.render_docx(_payload()))) as zf:
        core = zf.read("docProps/core.xml").decode("utf-8")
        app = zf.read("docProps/app.xml").decode("utf-8")
    assert "B2B.net S.A." not in re.sub(r"<dc:title>.*?</dc:title>", "", core)
    assert not _APP_NAMES.search(app)


_APP_NAMES = re.compile(r"<((?:\w+:)?(?:Company|Manager))>[^<]+</\1>")


def test_no_template_carries_a_company_or_manager_name():
    """Wzory działu miały w ``app.xml`` nazwę kancelarii (także jako
    ``<ap:Company>``) — repo jest publiczne, a plik idzie do Partnera."""
    root = mandate.DOCX_TEMPLATE.parents[1]
    paths = sorted([*root.glob("contract/*.docx"), *root.glob("documents/*.docx")])
    assert paths
    for path in paths:
        with zipfile.ZipFile(path) as zf:
            if "docProps/app.xml" not in zf.namelist():
                continue
            app = zf.read("docProps/app.xml").decode("utf-8")
        assert not _APP_NAMES.search(app), path.name


# ── Walidacja i zapis ────────────────────────────────────────────────────────


def test_stored_payload_has_no_sensitive_fields():
    stored = mandate.stored_payload(_payload())
    for key in ("pesel", "id_document", "home_address"):
        assert key not in stored
    assert PESEL not in str(stored)
    assert stored["kind"] == "mandate"
    # Ponowny render z zapisu działa i ma kropki w miejscu danych wrażliwych.
    again = mandate.payload_from_row(stored)
    assert again.pesel is None and again.tasks == _payload().tasks


def test_wrong_pesel_checksum_is_refused():
    with pytest.raises(mandate.MandateError, match="PESEL"):
        mandate.validate(_payload(pesel="44051401459"), RATES)


def test_minimum_rate_is_checked_for_every_year_of_the_period():
    mandate.validate(_payload(gross_hourly_rate=33), RATES)
    with pytest.raises(mandate.MandateError, match="2027 to 33,00 zł/h"):
        mandate.validate(_payload(gross_hourly_rate=32), RATES)
    with pytest.raises(mandate.MandateError, match="2026 to 31,40 zł/h"):
        mandate.validate(
            _payload(gross_hourly_rate=30, period_to=date(2026, 12, 31)), RATES
        )
    # Rok bez minimum w tabeli — bez kontroli, jak w Płacach.
    mandate.validate(
        _payload(
            gross_hourly_rate=30,
            period_from=date(2030, 1, 1),
            period_to=date(2030, 2, 1),
        ),
        RATES,
    )


def test_period_must_not_end_before_it_starts():
    with pytest.raises(ValidationError, match="Koniec zlecenia"):
        _payload(period_to=date(2026, 10, 31))


def test_at_least_one_task_is_required():
    with pytest.raises(ValidationError, match="czynność"):
        _payload(tasks=["  ", ""])


def test_mandate_label_and_file_name():
    assert mandate.mandate_label(date(2026, 10, 27)) == "Zlecenie z dnia 27.10.2026"
    assert (
        mandate_file_name("27.10.2026", "Łucja Żółć", ext="docx")
        == "Umowa zlecenia 27-10-2026 Zolc Lucja.docx"
    )


# ── Ścieżka z bazą (CI) ──────────────────────────────────────────────────────

RENDER = "/api/b2b-generator/mandate/render"


async def _seed_pair() -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Mandate Client {unique}")
        candidate = Candidate(
            name="Anna",
            lastname=f"Mandate-{unique}",
            email=f"mandate-{unique}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"Administrator {unique}",
            client_id=client.id,
            status=JobStatus.published,
        )
        db.add(job)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.onboarding,
            )
        )
        await db.commit()
        return {"candidate_id": candidate.id, "job_id": job.id, "client_id": client.id}


def _body(pair: dict[str, int], **overrides) -> dict:
    body = {
        "candidate_id": pair["candidate_id"],
        "job_id": pair["job_id"],
        "signing_date": "2026-10-27",
        "period_from": "2026-11-01",
        "period_to": "2027-01-31",
        "gender": "f",
        "partner_name": "Anna Mandate",
        "partner_email": "anna.mandate@example.com",
        "tasks": ["administracja platformą"],
        "gross_hourly_rate": 45.5,
        "pesel": PESEL,
        "home_address": "ul. Fikcyjna 1, 00-001 Warszawa",
        "id_document": "ABC123456",
        "with_dpa": True,
    }
    body.update(overrides)
    return body


async def test_mandate_render_registers_a_row_without_sensitive_data(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    pair = await _seed_pair()
    preview = await app_client.post(
        RENDER + "?format=html", json=_body(pair), headers=app_auth_headers
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["contract_number"] == "Zlecenie z dnia 27.10.2026"

    response = await app_client.post(RENDER, json=_body(pair), headers=app_auth_headers)
    assert response.status_code == 200, response.text
    assert "Umowa zlecenia 27-10-2026" in response.headers["content-disposition"]
    assert PESEL in _docx_text(response.content)
    generated_id = int(response.headers["x-generated-contract-id"])

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert row is not None
        assert row.contract_kind == "mandate"
        assert row.seq is None
        assert row.contract_number == "Zlecenie z dnia 27.10.2026"
        assert row.contract_status == "in_progress"
        assert row.client_id == pair["client_id"]
        assert row.start_date == date(2026, 11, 1)
        assert PESEL not in str(row.render_payload)
        assert "ABC123456" not in str(row.render_payload)

    again = await app_client.get(
        f"/api/b2b-generator/generated/{generated_id}/docx", headers=app_auth_headers
    )
    assert again.status_code == 200, again.text
    text = _docx_text(again.content)
    assert PESEL not in text and "PESEL: …" in text

    form = await app_client.get(
        f"/api/b2b-generator/generated/{generated_id}/form", headers=app_auth_headers
    )
    assert form.status_code == 409

    listing = await app_client.get(
        "/api/b2b-generator/generated",
        params={"q": "Anna Mandate"},
        headers=app_auth_headers,
    )
    assert listing.status_code == 200, listing.text
    item = next(i for i in listing.json() if i["id"] == generated_id)
    assert item["contract_kind"] == "mandate"
    assert item["can_edit"] is False
    assert item["can_send_esign"] is False


async def test_mandate_render_refuses_a_rate_below_the_minimum(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    pair = await _seed_pair()
    response = await app_client.post(
        RENDER,
        json=_body(pair, gross_hourly_rate=20),
        headers=app_auth_headers,
    )
    assert response.status_code == 422
    assert "Minimalna stawka na zleceniu" in response.json()["detail"]


async def test_signing_a_mandate_creates_a_mandate_contract_with_period_and_rate(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_contract_detail import B2BContractDetail
    from app.models.contract import Contract, ContractType, RateUnit

    pair = await _seed_pair()
    response = await app_client.post(RENDER, json=_body(pair), headers=app_auth_headers)
    assert response.status_code == 200, response.text
    generated_id = int(response.headers["x-generated-contract-id"])

    confirm = await app_client.post(
        f"/api/b2b-generator/generated/{generated_id}/confirm-fully-signed",
        json={},
        headers=app_auth_headers,
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["outcome"] == "created"

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, body["contract_id"])
        assert contract is not None
        assert contract.contract_type == ContractType.uzlecenie
        assert contract.start_date == date(2026, 11, 1)
        assert contract.end_date == date(2027, 1, 31)
        assert contract.rate_candidate == Decimal("45.5")
        assert contract.rate_unit == RateUnit.hourly
        assert contract.candidate_email == "anna.mandate@example.com"
        # Zlecenie nie ma szczegółów B2B (numer, firma, NIP).
        detail_id = await db.scalar(
            select(B2BContractDetail.id).where(
                B2BContractDetail.contract_id == contract.id
            )
        )
        assert detail_id is None


async def test_b2b_annex_does_not_offer_a_mandate_row(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    pair = await _seed_pair()
    name = f"Zlecenie {uuid.uuid4().hex[:6]}"
    response = await app_client.post(
        RENDER, json=_body(pair, partner_name=name), headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    generated_id = int(response.headers["x-generated-contract-id"])

    def ids(resp) -> set[int]:
        assert resp.status_code == 200, resp.text
        return {s.get("parent_generated_contract_id") for s in resp.json()}

    b2b = await app_client.get(
        "/api/b2b-generator/documents/subjects",
        params={"document_type": "annex_rate_change", "q": name},
        headers=app_auth_headers,
    )
    mandate_annex = await app_client.get(
        "/api/b2b-generator/documents/subjects",
        params={"document_type": "annex_mandate", "q": name},
        headers=app_auth_headers,
    )
    assert generated_id not in ids(b2b)
    assert generated_id in ids(mandate_annex)
