"""Wzory protokołów wgrane przez recepcję (etap 3, O3).

Plik od człowieka wypełnia się wyłącznie w sandboxie jinja2: wzór, który
próbuje sięgnąć do atrybutów Pythona, nie wykonuje kodu ani przy wgraniu, ani
przy wypełnianiu protokołu. Protokół wydania i zwrotu kontraktu bierze wzór
z pakietu klienta. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import pytest_asyncio
from jinja2.exceptions import SecurityError, TemplateError
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.equipment import EquipmentProtocol, EquipmentProtocolTemplate
from app.models.user import UserRole
from app.services.equipment import protocol_template as tpl
from app.services.equipment import protocols
from app.services.equipment.holders import resolve_holder
from tests.client_onboarding_support import (
    DEPOSIT_PARAGRAPHS,
    PREFIX,
    deposit_template,
    document_text,
    docx_bytes,
    ensure_router_mounted,
    headers,
    make_client,
    make_contract,
    make_user,
    modules_state,
    tag,
)

pytestmark = pytest.mark.asyncio

DOCX = tpl.DOCX_MEDIA_TYPE


# ── Sprawdzenie pliku (bez bazy) ──────────────────────────────────────────────


def _rejected(
    content: bytes, kind: str = "wydanie", filename: str = "wzor.docx"
) -> str:
    with pytest.raises(tpl.TemplateRejected) as caught:
        tpl.check_upload(filename, content, kind)
    return str(caught.value)


def test_standard_templates_pass_their_own_check() -> None:
    for kind in ("wydanie", "zwrot"):
        fields = tpl.check_upload(
            "standard.docx", tpl.standard_template_bytes(kind), kind
        )
        assert set(tpl.REQUIRED_FIELDS[kind]) <= set(fields)


def test_deposit_template_is_accepted_with_its_fields() -> None:
    fields = tpl.check_upload("kaucja.docx", deposit_template(), "wydanie")
    assert fields == sorted(
        {
            "number",
            "protocol_date",
            "holder_name",
            "issuer_name",
            "lines",
            "total",
            "total_words",
        }
    )


def test_only_docx_within_size_limit() -> None:
    assert "Word w formacie .docx" in _rejected(deposit_template(), filename="wzor.doc")
    assert "pusty albo większy" in _rejected(b"")
    assert "pusty albo większy" in _rejected(b"PK" + b"0" * tpl.MAX_UPLOAD_BYTES)
    assert "To nie jest plik Word" in _rejected(b"%PDF-1.7 nie docx")


def test_zip_without_word_document_and_macro_package_are_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("inne.txt", "x")
    assert "To nie jest plik Word" in _rejected(buffer.getvalue())

    source = zipfile.ZipFile(io.BytesIO(deposit_template()))
    macro = io.BytesIO()
    with zipfile.ZipFile(macro, "w") as package:
        for item in source.infolist():
            package.writestr(item, source.read(item.filename))
        package.writestr("word/vbaProject.bin", b"\x00makro")
    assert "makrami" in _rejected(macro.getvalue())


def _with_part(name: str, data: str) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(deposit_template()))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == name:
                payload = data.encode("utf-8")
            package.writestr(item, payload)
        if name not in source.namelist():
            package.writestr(name, data)
    return buffer.getvalue()


_RELS_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?><Relationships '
    'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
)
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def test_external_template_image_and_embedded_object_are_refused() -> None:
    """LibreOffice przy konwersji pobrałby zasób z sieci z serwera (SSRF)."""
    for rel in (
        f'<Relationship Id="rId90" Type="{_REL_TYPE}attachedTemplate" '
        'Target="http://example.com/wzor.dotx" TargetMode="External"/>',
        f'<Relationship Id="rId91" Type="{_REL_TYPE}image" '
        'Target="http://169.254.169.254/obraz.png" TargetMode="External"/>',
    ):
        rels = _RELS_HEAD + rel + "</Relationships>"
        message = _rejected(_with_part("word/_rels/settings.xml.rels", rels))
        assert "spoza dokumentu" in message
    embedded = _with_part("word/embeddings/oleObject1.bin", "x")
    assert "osadzonymi obiektami" in _rejected(embedded)


def test_plain_hyperlink_in_template_is_accepted() -> None:
    rels = (
        _RELS_HEAD + f'<Relationship Id="rId92" Type="{_REL_TYPE}hyperlink" '
        'Target="https://example.com" TargetMode="External"/></Relationships>'
    )
    content = _with_part("word/_rels/footer9.xml.rels", rels)
    assert "number" in tpl.check_upload("wzor.docx", content, "wydanie")


def test_zip_bomb_is_refused_before_reading_fields() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<w:document/>")
        package.writestr("word/bomba.xml", b"0" * (tpl.MAX_UNPACKED_BYTES + 1))
    assert len(buffer.getvalue()) < tpl.MAX_UPLOAD_BYTES
    assert "po rozpakowaniu" in _rejected(buffer.getvalue())


def test_unknown_and_missing_fields_are_named() -> None:
    unknown = _rejected(docx_bytes(*DEPOSIT_PARAGRAPHS, "PESEL: {{ pesel }}"))
    assert "pesel" in unknown and "Dostępne pola" in unknown
    missing = _rejected(docx_bytes("Protokół {{ number }} dla {{ holder_name }}"))
    assert "protocol_date" in missing and "lines" in missing


def test_syntax_error_in_fields_is_refused_with_reason() -> None:
    message = _rejected(docx_bytes(*DEPOSIT_PARAGRAPHS, "{{ number "))
    assert message.startswith("Błąd w polach wzoru")


# Wyrażenia, które w zwykłym jinja2 sięgnęłyby do Pythona (klasy, globalne
# funkcji, moduł ``os``) albo zjadły pamięć. Pierwsze to klasyczne SSTI:
# w zwykłym ``Environment`` (jak przy wbudowanym standardzie) wykonuje
# ``touch`` i plik znacznika powstaje — sprawdzone ręcznie 17.10.2026.
_ESCAPES = (
    "{% for c in number.__class__.__mro__[1].__subclasses__() %}"
    "{% if c.__name__ == '_wrap_close' %}"
    "{{ c.__init__.__globals__['system']('touch {marker}') }}"
    "{% endif %}{% endfor %}",
    "{{ lines.__class__.__mro__[1].__subclasses__() }}",
    "{{ number.__class__.__base__.__subclasses__() }}",
    "{{ lines.__init__.__globals__ }}",
    "{{ number.__class__.__init__.__globals__['os'].system('touch {marker}') }}",
    "{{ 'a' * 100000000 }}",
    "{{ '%100000000s' % 'a' }}",
    "{{ 9 ** 9 ** 9 }}",
)


@pytest.mark.parametrize("expression", _ESCAPES)
def test_template_reaching_python_internals_runs_no_code(
    expression: str, tmp_path: Path
) -> None:
    marker = tmp_path / "wykonano"
    content = docx_bytes(
        *DEPOSIT_PARAGRAPHS, expression.replace("{marker}", str(marker))
    )
    message = _rejected(content)
    assert "sięgnąć poza dane protokołu" in message or "Błąd w polach" in message
    assert not marker.exists()
    # Wypełnianie protokołu też idzie przez sandbox — nie tylko sprawdzenie
    # (pętla po czymś innym niż pozycje odpada już przy czytaniu wzoru).
    with pytest.raises((SecurityError, TemplateError)):
        tpl.render_uploaded(content, tpl._sample_context("wydanie"))
    assert not marker.exists()


@pytest.mark.parametrize(
    "statement",
    (
        "{% macro m(x) %}{{ m(x ~ x) }}{% endmacro %}{{ m('a') }}",
        "{% include 'inny.docx' %}",
        "{% for i in range(100000) %}{{ i }}{% endfor %}",
        "{{ number|center(100000000) }}",
    ),
)
def test_macros_includes_globals_and_wide_filters_are_unavailable(
    statement: str,
) -> None:
    _rejected(docx_bytes(*DEPOSIT_PARAGRAPHS, statement))


# Małe wzory, które w sandboksie z listą zakazanych węzłów zajmowały pamięć
# albo procesor (przegląd bezpieczeństwa 17.10.2026): wywołanie metody pola,
# podwajanie napisu przez ``set``, pętla po znakach pola i pętla w pętli.
_AMPLIFIERS = (
    "{{ holder_name.ljust(2000000000) }}",
    "{% set s = holder_name %}{% set s = s ~ s %}{% set s = s ~ s %}{{ s }}",
    "{{ holder_name ~ holder_name }}",
    "{% for c in holder_name %}{{ c }}{% endfor %}",
    "{% for a in lines %}{% for b in lines %}{{ b.name }}{% endfor %}{% endfor %}",
    "{% with s = holder_name %}{{ s }}{% endwith %}",
    "{% filter upper %}{{ holder_name }}{% endfilter %}",
)


@pytest.mark.parametrize("statement", _AMPLIFIERS)
def test_templates_that_amplify_memory_or_time_are_refused(statement: str) -> None:
    message = _rejected(docx_bytes(*DEPOSIT_PARAGRAPHS, statement))
    assert message.startswith("Błąd w polach wzoru")
    with pytest.raises(TemplateError):
        tpl.render_uploaded(
            docx_bytes(*DEPOSIT_PARAGRAPHS, statement), tpl._sample_context("wydanie")
        )


def test_arithmetic_is_not_available_in_templates() -> None:
    """Mnożenie wielkich liczb zajmowało procesor przy każdym wypełnieniu."""
    big = "9" * 4000
    for statement in (
        "{{ holder_name + number }}",
        "{% if " + "*".join([big] * 5) + " > 0 %}x{% endif %}",
        "{{ -lines|length }}",
    ):
        assert _rejected(docx_bytes(*DEPOSIT_PARAGRAPHS, statement)).startswith(
            "Błąd w polach wzoru"
        )


def test_package_part_in_other_letter_case_is_422_not_500() -> None:
    source = zipfile.ZipFile(io.BytesIO(deposit_template()))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for item in source.infolist():
            name = item.filename
            if name == "[Content_Types].xml":
                name = "[content_types].xml"
            package.writestr(name, source.read(item.filename))
    message = _rejected(buffer.getvalue())
    assert message


def test_template_with_too_many_fields_is_refused() -> None:
    crowded = "{{ number }}" * (tpl.MAX_TEMPLATE_NODES + 1)
    message = _rejected(docx_bytes(*DEPOSIT_PARAGRAPHS, crowded))
    assert "za dużo pól" in message


def test_uploaded_template_fills_with_protocol_data() -> None:
    rendered = tpl.render_uploaded(deposit_template(), tpl._sample_context("wydanie"))
    text_value = document_text(rendered)
    assert "PROTOKÓŁ Z KAUCJĄ nr PZO/2026/01/001" in text_value
    assert "Anna Przykładowa" in text_value
    assert "1. Laptop przykładowy 14 cali (TEST0001) 1234,56" in text_value


def test_uploaded_template_may_print_signature_notes() -> None:
    content = docx_bytes(
        *DEPOSIT_PARAGRAPHS,
        "Odbierający: {{ holder_signature }}",
        "Recepcja: {{ issuer_signature }}",
    )
    fields = tpl.check_upload("kaucja-podpis.docx", content, "wydanie")
    assert {"holder_signature", "issuer_signature"} <= set(fields)
    context = {
        **tpl._sample_context("wydanie"),
        "holder_signature": "Potwierdzono elektronicznie linkiem z NEXUSA",
    }
    assert "Odbierający: Potwierdzono elektronicznie linkiem z NEXUSA" in document_text(
        tpl.render_uploaded(content, context)
    )


# ── Trasy i wybór wzoru w protokole (baza) ────────────────────────────────────


@pytest_asyncio.fixture
async def modules_on():
    ensure_router_mounted()
    async with modules_state(True):
        yield


async def _upload(app_client, user, content: bytes, *, kind="wydanie", name=None):
    return await app_client.post(
        "/api/equipment/protocol-templates",
        files={"file": ("kaucja.docx", content, DOCX)},
        data={"kind": kind, "name": name or f"Z kaucją {tag()}"},
        headers=headers(user),
    )


async def test_reception_uploads_lists_and_downloads_templates(
    app_client, modules_on
) -> None:
    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    recruiter = await make_user(UserRole.recruiter)
    refused = await _upload(app_client, recruiter, deposit_template())
    assert refused.status_code == 403

    created = await _upload(app_client, reception, deposit_template())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "wydanie" and "lines" in body["fields"]

    listing = await app_client.get(
        "/api/equipment/protocol-templates", headers=headers(reception)
    )
    assert listing.status_code == 200
    payload = listing.json()
    assert body["id"] in [item["id"] for item in payload["items"]]
    assert {"field": "line.name", "label": "nazwa sprzętu", "scope": "line"} in payload[
        "fields"
    ]

    original = await app_client.get(
        f"/api/equipment/protocol-templates/{body['id']}/file",
        headers=headers(reception),
    )
    assert original.status_code == 200 and original.content == deposit_template()
    sample = await app_client.get(
        f"/api/equipment/protocol-templates/{body['id']}/sample",
        headers=headers(reception),
    )
    assert sample.status_code == 200
    assert "Anna Przykładowa" in document_text(sample.content)
    standard = await app_client.get(
        "/api/equipment/protocol-templates/standard/zwrot", headers=headers(reception)
    )
    assert standard.status_code == 200
    assert standard.content == tpl.standard_template_bytes("zwrot")


async def test_upload_refusals_answer_422_and_duplicates_409(
    app_client, modules_on
) -> None:
    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    hostile = docx_bytes(*DEPOSIT_PARAGRAPHS, "{{ lines.__class__.__mro__ }}")
    refused = await _upload(app_client, reception, hostile)
    assert refused.status_code == 422
    assert "poza dane protokołu" in refused.json()["detail"]

    name = f"Zwrot u klienta {tag()}"
    first = await _upload(app_client, reception, deposit_template(), name=name)
    assert first.status_code == 201
    twin = await _upload(app_client, reception, deposit_template(), name=name.upper())
    assert twin.status_code == 409
    other_kind = await _upload(
        app_client, reception, deposit_template(), name=name, kind="zwrot"
    )
    assert other_kind.status_code == 201


async def test_two_uploads_with_one_name_at_once_answer_409_not_500(
    app_client, modules_on, monkeypatch
) -> None:
    """Dwa równoczesne wgrania: oba przechodzą sprawdzenie nazwy, unikat bazy
    zatrzymuje drugie — odpowiedź 409 z powodem, nie 500."""

    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    name = f"Wyścig {tag()}"
    first = await _upload(app_client, reception, deposit_template(), name=name)
    assert first.status_code == 201, first.text

    async def unseen(db, kind, name, *, exclude_id=None):
        # Druga sesja sprawdzała nazwę, zanim pierwsza się zapisała.
        return None

    monkeypatch.setattr(tpl, "_ensure_unique_name", unseen)
    twin = await _upload(app_client, reception, deposit_template(), name=name)
    assert twin.status_code == 409, twin.text
    assert "już jest" in twin.json()["detail"]
    withdrawn = await app_client.patch(
        f"/api/equipment/protocol-templates/{first.json()['id']}",
        json={"is_active": False},
        headers=headers(reception),
    )
    assert withdrawn.status_code == 200
    second = await _upload(app_client, reception, deposit_template(), name=name)
    assert second.status_code == 201
    revived = await app_client.patch(
        f"/api/equipment/protocol-templates/{first.json()['id']}",
        json={"is_active": True},
        headers=headers(reception),
    )
    assert revived.status_code == 409, revived.text


async def test_template_used_by_a_pack_cannot_be_withdrawn(
    app_client, modules_on
) -> None:
    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    template = (await _upload(app_client, reception, deposit_template())).json()
    client_id = await make_client()
    saved = await app_client.put(
        f"{PREFIX}/clients/{client_id}/pack",
        json={"equipment": {"issue_template_id": template["id"]}},
        headers=headers(reception),
    )
    assert saved.status_code == 200, saved.text

    withdraw = await app_client.patch(
        f"/api/equipment/protocol-templates/{template['id']}",
        json={"is_active": False},
        headers=headers(reception),
    )
    assert withdraw.status_code == 409
    assert "pakiecie 1 klienta" in withdraw.json()["detail"]

    await app_client.put(
        f"{PREFIX}/clients/{client_id}/pack",
        json={"equipment": {"issue_template_id": None}},
        headers=headers(reception),
    )
    withdraw = await app_client.patch(
        f"/api/equipment/protocol-templates/{template['id']}",
        json={"is_active": False},
        headers=headers(reception),
    )
    assert withdraw.status_code == 200 and withdraw.json()["is_active"] is False


async def test_contract_protocol_uses_template_from_client_pack(
    app_client, modules_on
) -> None:
    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    template = (await _upload(app_client, reception, deposit_template())).json()
    with_pack = await make_client(provider="nasz")
    without_pack = await make_client(provider="nasz")
    assert (
        await app_client.put(
            f"{PREFIX}/clients/{with_pack}/pack",
            json={"equipment": {"issue_template_id": template["id"]}},
            headers=headers(reception),
        )
    ).status_code == 200
    contract_with = await make_contract(with_pack)
    contract_without = await make_contract(without_pack)

    async with AsyncSessionLocal() as db:
        actor = await db.get(type(reception), reception.id)
        line = {"category": "laptop", "name": "Laptop testowy", "unit_value": None}
        chosen = await protocols.create_protocol(
            db,
            kind="wydanie",
            holder=await resolve_holder(db, "contract", contract_with),
            lines=[line],
            protocol_date=business_today(),
            actor=actor,
        )
        standard = await protocols.create_protocol(
            db,
            kind="wydanie",
            holder=await resolve_holder(db, "contract", contract_without),
            lines=[line],
            protocol_date=business_today(),
            actor=actor,
        )
        # Zwrot nie ma wzoru w pakiecie — standard, mimo wzoru wydania.
        returned = await protocols.create_protocol(
            db,
            kind="zwrot",
            holder=await resolve_holder(db, "contract", contract_with),
            lines=[{**line, "condition": "sprawny"}],
            protocol_date=business_today(),
            actor=actor,
        )
        assert chosen.template_id == template["id"]
        assert chosen.template_version == f"wzor-{template['id']}"
        assert standard.template_id is None and returned.template_id is None
        assert "PROTOKÓŁ Z KAUCJĄ" in document_text(
            await protocols.render_docx(db, chosen)
        )
        assert "ZDAWCZO-ODBIORCZY" in document_text(
            await protocols.render_docx(db, standard)
        )
        await db.rollback()


async def test_withdrawn_template_is_not_used_for_new_protocols(
    app_client, modules_on
) -> None:
    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    template = (await _upload(app_client, reception, deposit_template())).json()
    client_id = await make_client()
    await app_client.put(
        f"{PREFIX}/clients/{client_id}/pack",
        json={"equipment": {"issue_template_id": template["id"]}},
        headers=headers(reception),
    )
    contract_id = await make_contract(client_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(EquipmentProtocolTemplate, template["id"])
        row.is_active = False  # wycofany z pominięciem trasy (np. ręcznie)
        await db.flush()
        protocol = await protocols.create_protocol(
            db,
            kind="wydanie",
            holder=await resolve_holder(db, "contract", contract_id),
            lines=[{"category": "laptop", "name": "Laptop testowy"}],
            protocol_date=business_today(),
            actor=reception,
        )
        assert protocol.template_id is None
        await db.rollback()
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(EquipmentProtocol.id).where(
                    EquipmentProtocol.template_id == template["id"]
                )
            )
        ) is None


async def test_protocol_download_uses_the_template_from_the_pack(
    app_client, modules_on
) -> None:
    """Pobrany plik Word protokołu (trasa, nie tylko serwis) jest z wzoru pakietu."""

    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    template = (await _upload(app_client, reception, deposit_template())).json()
    client_id = await make_client(provider="nasz")
    assert (
        await app_client.put(
            f"{PREFIX}/clients/{client_id}/pack",
            json={"equipment": {"issue_template_id": template["id"]}},
            headers=headers(reception),
        )
    ).status_code == 200
    contract_id = await make_contract(client_id)
    async with AsyncSessionLocal() as db:
        actor = await db.get(type(reception), reception.id)
        protocol = await protocols.create_protocol(
            db,
            kind="wydanie",
            holder=await resolve_holder(db, "contract", contract_id),
            lines=[
                {"category": "laptop", "name": "Laptop testowy", "unit_value": None}
            ],
            protocol_date=business_today(),
            actor=actor,
        )
        await db.commit()
        protocol_id = protocol.id
    response = await app_client.get(
        f"/api/equipment/protocols/{protocol_id}/document.docx",
        headers=headers(reception),
    )
    assert response.status_code == 200, response.text
    assert "PROTOKÓŁ Z KAUCJĄ" in document_text(response.content)
