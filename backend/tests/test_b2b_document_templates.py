"""Szablony dokumentów pochodnych umowy B2B (``app/templates/documents``).

Szablony buduje ``scripts/build_b2b_document_templates.py`` ze wzorów działu.
Test renderuje KAŻDY typ z rejestru w każdym języku, dla obu płci i wariantów
(JDG/spółka, zakaz konkurencji zachowany/zwolniony) — tymi samymi funkcjami co
produkcja (``build_document_context`` + ``render_docx``/``render_html``) — i
pilnuje trzech rzeczy:

* nic nie zostaje z Jinja ani z podświetleń wzoru, a brak danych nie wychodzi
  jako „None”;
* dokument cytuje paragrafy umowy 2026 (wzory cytowały starą umowę);
* w plikach szablonów nie ma danych osób i umów ze wzorów działu — test trzyma
  wyłącznie skróty SHA-256 tych wartości, nie same wartości.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from datetime import date

import pytest

from app.services.b2b_documents.context import BaseContractInfo, build_document_context
from app.services.b2b_documents.registry import TYPES, DocumentType
from app.services.b2b_documents.render import (
    TEMPLATE_DIR,
    docx_path,
    html_path,
    render_docx,
    render_html,
    template_key,
)

PARTNER = {
    "m": {"partner_name": "Jan Próbny", "partner_instrumental": "Janem Próbnym"},
    "k": {"partner_name": "Anna Próbna", "partner_instrumental": "Anną Próbną"},
}

BASE = BaseContractInfo(
    contract_number="1600/2026",
    signing_date=date(2026, 8, 3),
    start_date=date(2026, 9, 1),
    start_date_mode="exact",
    client_name="Klient Testowy",
    client_legal_name="Klient Testowy S.A.",
)

#: Wartości jawnie rozpoznawalne w wyniku; reszta pól dostaje wartość z rodzaju.
OVERRIDES = {
    "document_date": "2026-10-05",
    "effective_date": "2026-11-01",
    "new_rate": 185.5,
    "currency": "PLN",
    "new_start_date": "2026-10-15",
    "new_start_date_mode": "not_later",
    "partner_legal_name": "Próbna Firma IT",
    "partner_business_address": "ul. Testowa 1, 00-001 Warszawa",
    "partner_nip": "1234563218",
    "partner_regon": "123456785",
    "partner_home_address": "ul. Domowa 2, 00-002 Kraków",
    "id_document": "ABC123456",
    "id_document_issuer": "Prezydent m. Krakowa",
    "pesel": "90010112345",
    "new_legal_name": "Nowa Firma Sp. z o.o.",
    "new_business_address": "ul. Firmowa 3, 00-003 Gdańsk",
    "new_nip": "9876543210",
    "new_regon": "987654321",
    "company_krs": "0000123456",
    "company_representative": "Prezes Testowy",
    "delegate_name": "Ewa Skierowana",
    "delegate_email": "ewa@example.com",
    "base_signing_date": "2025-05-06",
    "period_from": "2026-10-01",
    "period_to": "2027-03-31",
    "gross_hourly_rate": 42.5,
    "extra_provisions": "Pierwszy dodatkowy ustęp.\nDrugi dodatkowy ustęp.",
    "termination_date": "2026-10-31",
    "last_service_date": "2026-10-30",
    "non_compete_client_name": "Klient Zwolniony S.A.",
    "delivery_date": "2026-09-15",
    "notice_delivery_date": "2026-09-10",
    "project_number": "CEZ/77/2026",
    "hourly_rate": 160,
    "valid_until": "2026-12-04",
}


def _values(doc_type: DocumentType, gender: str, **extra) -> dict:
    values: dict = {}
    for f in doc_type.fields:
        if f.key in OVERRIDES:
            values[f.key] = OVERRIDES[f.key]
        elif f.kind == "bool":
            values[f.key] = True
        elif f.kind == "select":
            values[f.key] = f.options[0][0]
        elif f.kind == "gender":
            values[f.key] = gender
        else:
            values[f.key] = f"Wartość {f.key}"
    values.update(PARTNER[gender])
    values["gender"] = gender
    values.update(extra)
    return values


def _docx_text(data: bytes) -> tuple[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    text = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml))
    return xml, text


def _variants(doc_type: DocumentType) -> list[dict]:
    if doc_type.key == "annex_party_data":
        return [{"entity_type": "sole_trader"}, {"entity_type": "company"}]
    if doc_type.key.startswith("termination_agreement"):
        return [{"release_non_compete": True}, {"release_non_compete": False}]
    if doc_type.key == "annex_mandate":
        return [
            {},
            {"change_period": False, "change_rate": False, "extra_provisions": None},
        ]
    return [{}]


CASES = [
    pytest.param(t, lang, g, extra, id=f"{t.key}-{lang}-{g}-{i}")
    for t in TYPES.values()
    for lang in t.languages
    for g in ("m", "k")
    for i, extra in enumerate(_variants(t))
]


def _render(doc_type: DocumentType, lang: str, gender: str, extra: dict):
    values = _values(doc_type, gender, **extra)
    ctx = build_document_context(doc_type, values, language=lang, base=BASE, refs=None)
    key = template_key(doc_type.key, lang)
    return values, render_docx(key, ctx), render_html(key, ctx)


# Formy zależne od płci, które szablon danego typu na pewno zawiera.
GENDER_MARKERS = {
    "pl": {"m": "Panem", "k": "Panią"},
    "en": {"m": "Mr ", "k": "Ms "},
}


def _expected(doc_type: DocumentType, lang: str, values: dict) -> list[str]:
    key = doc_type.key
    out: list[str] = []
    if doc_type.parent == "b2b":
        out.append("1600/2026")
        out.append("03.08.2026")
    if key == "annex_rate_change":
        out += [
            "185,50",
            "sto osiemdziesiąt pięć" if lang == "pl" else "one hundred eighty",
        ]
        out.append("§ 6 ust. 1" if lang == "pl" else "§ 6 section 1")
        out.append("01.11.2026")
    elif key == "annex_start_date":
        out += ["§ 13 ust. 2", "Załącznik nr 3", "z dniem 01.09.2026 roku"]
        out.append("nie później niż 15.10.2026 roku")
    elif key == "annex_party_data":
        out += ["Nowa Firma Sp. z o.o.", "9876543210", "ul. Domowa 2", "ABC123456"]
        if values["entity_type"] == "company":
            out += ["0000123456", "Prezes Testowy"]
    elif key == "annex_subcontractor":
        out += [
            "Ewa Skierowana",
            "ewa@example.com",
            "§ 8 Umowy",
            "§ 7 i § 7A",
            "§ 5 Umowy",
        ]
    elif key == "annex_mandate":
        out += ["90010112345", "06.05.2025"]
        if values.get("change_period"):
            out += ["01.10.2026", "31.03.2027", "42,50", "Drugi dodatkowy ustęp."]
    elif key == "termination_agreement":
        out += ["31.10.2026", "30.10.2026"]
        if values["release_non_compete"]:
            out += [
                "Klient Zwolniony S.A.",
                "§ 10 ust. 1" if lang == "pl" else "§ 10 section 1",
            ]
    elif key == "termination_agreement_mandate":
        out += ["31.10.2026", "06.05.2025"]
        if values["release_non_compete"]:
            out.append("Klient Zwolniony S.A.")
    elif key == "termination_notice":
        out += ["§ 12 ust. 2 pkt 2", "1 (jednego) miesiąca", "15.09.2026", "31.10.2026"]
    elif key == "notice_withdrawal":
        out.append("10.09.2026")
    elif key == "preliminary_cez":
        out += ["CEZ/77/2026", "90010112345", "ABC123456", "04.12.2026", "0000387063"]
    return out


@pytest.mark.parametrize(("doc_type", "lang", "gender", "extra"), CASES)
def test_document_renders_complete(doc_type, lang, gender, extra):
    values, docx_bytes, html = _render(doc_type, lang, gender, extra)
    xml, text = _docx_text(docx_bytes)

    for leftover in ("{{", "}}", "{%", "%}"):
        assert leftover not in text, f"Jinja w DOCX: {leftover}"
        assert leftover not in html, f"Jinja w HTML: {leftover}"
    assert "None" not in text and "None" not in html
    assert "<w:highlight" not in xml, "podświetlenie wzoru zostało w dokumencie"

    nominative = lang == "en" or doc_type.key == "notice_withdrawal"
    assert values["partner_name" if nominative else "partner_instrumental"] in text

    for fragment in _expected(doc_type, lang, values):
        assert fragment in text, f"brak {fragment!r} w DOCX"
        assert _html_unescape(fragment) in _html_unescape(html), (
            f"brak {fragment!r} w HTML"
        )

    if doc_type.key == "notice_withdrawal":
        assert ("przekazałam" if gender == "k" else "przekazałem") in text
    else:
        assert GENDER_MARKERS[lang][gender] in text
        wrong = GENDER_MARKERS[lang]["m" if gender == "k" else "k"]
        if lang == "pl" and doc_type.key != "annex_subcontractor":
            assert wrong not in text

    if doc_type.key == "termination_agreement" and not values["release_non_compete"]:
        assert "Klient Zwolniony" not in text
        assert "§ 10" not in text


def _html_unescape(s: str) -> str:
    import html as _html

    return _html.unescape(s)


def test_female_forms_in_polish_party_data():
    doc_type = TYPES["annex_party_data"]
    values, docx_bytes, _ = _render(doc_type, "pl", "k", {"entity_type": "sole_trader"})
    _, text = _docx_text(docx_bytes)
    for form in (
        "zamieszkałą",
        "legitymującą się",
        "zwaną dalej „Partnerem”",
        "Pani Anna Próbna",
        "prowadząca",
    ):
        assert form in text


def test_subcontractor_delegate_gender_is_independent():
    doc_type = TYPES["annex_subcontractor"]
    values = _values(doc_type, "m", delegate_gender="k")
    ctx = build_document_context(doc_type, values, language="pl", base=BASE, refs=None)
    _, text = _docx_text(render_docx(template_key(doc_type.key, "pl"), ctx))
    assert "Pani Ewa Skierowana" in text
    assert "Panem Janem Próbnym" in text


def test_release_renumbers_paragraphs():
    doc_type = TYPES["termination_agreement"]
    _, with_release, _ = _render(doc_type, "pl", "m", {"release_non_compete": True})
    _, without, _ = _render(doc_type, "pl", "m", {"release_non_compete": False})
    assert "§ 7" in _docx_text(with_release)[1]
    assert "§ 7" not in _docx_text(without)[1]
    assert "§ 6" in _docx_text(without)[1]


def test_empty_values_render_placeholders_not_none():
    doc_type = TYPES["annex_party_data"]
    values = {"gender": "k", "entity_type": "company"}
    ctx = build_document_context(doc_type, values, language="pl", base=None, refs=None)
    _, text = _docx_text(render_docx(template_key(doc_type.key, "pl"), ctx))
    assert "None" not in text
    assert "…" in text


def test_every_registry_type_has_a_template_per_language():
    for doc_type in TYPES.values():
        for lang in doc_type.languages:
            key = template_key(doc_type.key, lang)
            assert docx_path(key).is_file(), f"brak {key}.docx"
            assert html_path(key).is_file(), f"brak {key}.html"
    expected = {
        f"{template_key(t.key, lang)}.{ext}"
        for t in TYPES.values()
        for lang in t.languages
        for ext in ("docx", "html")
    }
    assert {
        p.name for p in TEMPLATE_DIR.iterdir() if p.suffix in (".docx", ".html")
    } == expected


# Skróty SHA-256 (wartość, długość) danych ze wzorów działu: numery i daty
# przykładowych umów, nazwy klientów, autorzy w metadanych plików.
WZOR_DATA_SHA256: tuple[tuple[str, int], ...] = (
    ("9de3439ff5afa95170d375817c99f98a4724e73a4b715fcd4d797d97412c508c", 8),
    ("30871b34674f25a860261a4c71bed9318178fe798f426acb30370d48e58aacc6", 10),
    ("dad14110101486eacc211f13fe8bbca4411610713899c885221ed6541480d4aa", 9),
    ("af7a8842937aab508e7c860115c45f7156ef7d0896efc0a256e34d7eb4c390ed", 10),
    ("ce616fa59b182374654b9c1f240800446a3fdaec9f52c81c4af1833da3e297d7", 10),
    ("45f614516437f883e2ceeaa7136b9c55cc0276dde85443799b3ace6c516be920", 10),
    ("efae4b91826cdc8da40523e1ad649b8a59e8f82d89b688d27c9ac7672dbe99a3", 9),
    ("9e0723cb8fe2ca82c4cdcf172cef7755ba187d9190a3eade1324f21b02640c2a", 10),
    ("e0af0d86dc389bb43620206ee15b82b12c403251c89c924bf0c8e8edb1f7610b", 10),
    ("063de0fccec7a31e6a8d2bf3e665e0cd6900c8fa61662ff38f66977bc4f30da4", 10),
    ("45a56d9f029008095b4b9eed3e07dd7c3115c6c5c38994995c6ef8a1afca464d", 10),
    ("cd94cc9f03cd6f1bd13ee7de3597c1d043a5912b6fbd0e4595d92df809a5ebad", 10),
    ("e7bbeaca09c01292f39900fa7238c7a4dbd4b5180949a43ae4aaa78726612dc1", 10),
    ("be79c7201bba58494a9e2334b94e668ce0fc4e1cb97249fa0924af8de0aa5d0c", 10),
    ("740a02b1f3f26ec6a27ee0b50b1dbcae228c6e8a4f1e2fb8ef89bb339f3d3bd5", 7),
    ("6b79af125dd6b2db1d3229794e84933420aed9018d56041343b9bb89236039bb", 5),
    ("65bd4f5a3de2033de9da6815acdd31dcbf0b705968a4447dacf11e084a0b7ae4", 10),
    ("d5ae643c1f0321df6fdfc641a493a80a2f30c7a24708b1342124ecfa36f1883e", 10),
    ("034a2f77da5ab42197918e2c062af1fc51b71a4bf1cbb06665b8519f413986d5", 10),
    ("f1fcb51cafc34bd458c099fee896dd5d76c715c6330564d5724416e330fc48fb", 11),
    ("f739cc70ba81e5fd6f1b8e332d157273fa5cbea235054587bc1435ff4d333baf", 11),
    ("a0b8c06c42a6b7d50372dc82b9f492bec94117ca2247f01daaf7a8a6abb5ca87", 10),
    ("c343518d635c48e436df168c07939da34f11e1e7a4ed43ff5c1a7f2e6d6a9685", 10),
    ("6387c1f42eb2b1d037214084871c6a888b28263f6964b2145aaf11a46b5e4677", 11),
    ("d5b8363f2c6d9d465164e42fd92a6a96816cd71b280a79e2c59c82c667a94c6d", 11),
    ("3991db5be76a152084b81169d4334eec646f663b07448172f9cf9a91eb2d4f2c", 12),
    ("50625c4b328ed9f52f17f1af5d94d9ce6ea660c366f8f83f198c26c12a0da7b8", 5),
    ("bfa5273be90e56d37675f188d2e54d62c1811bb386f573c38e27880b5e3d24b3", 13),
    ("10f3444dcbf5a1445fc1d1a28293e9a46e2905c5e7cd9d3840e74a01d57f6332", 22),
)


def _template_texts() -> dict[str, str]:
    """Cała treść każdego pliku szablonu: tekst DOCX (wszystkie części XML bez
    znaczników — także metadane autora) i HTML."""
    out: dict[str, str] = {}
    for path in sorted(TEMPLATE_DIR.iterdir()):
        if path.suffix == ".html":
            out[path.name] = path.read_text(encoding="utf-8")
        elif path.suffix == ".docx":
            with zipfile.ZipFile(path) as zf:
                parts = []
                for name in zf.namelist():
                    if name.endswith((".xml", ".rels")):
                        xml = zf.read(name).decode("utf-8", errors="replace")
                        # Bez znaczników — tekst pocięty na runy skleja się sam.
                        parts.append(re.sub(r"<[^>]+>", "", xml))
                out[path.name] = "\n".join(parts)
    return {k: unicodedata.normalize("NFC", v) for k, v in out.items()}


def test_templates_carry_no_data_from_department_samples():
    lengths = sorted({n for _, n in WZOR_DATA_SHA256})
    wanted = {h for h, _ in WZOR_DATA_SHA256}
    leaks: list[str] = []
    for name, text in _template_texts().items():
        for n in lengths:
            for i in range(len(text) - n + 1):
                digest = hashlib.sha256(text[i : i + n].encode("utf-8")).hexdigest()
                if digest in wanted:
                    leaks.append(f"{name}: pozycja {i}")
    assert not leaks, "dane ze wzorów działu w szablonach:\n" + "\n".join(leaks)


def test_templates_have_no_sharepoint_or_addin_parts():
    for path in TEMPLATE_DIR.glob("*.docx"):
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            assert not [
                n for n in names if n.startswith(("customXml/", "word/webextensions/"))
            ]
            assert "docProps/custom.xml" not in names
            for name in names:
                if name.startswith("word/") and name.endswith(".xml"):
                    assert b"<w:highlight" not in zf.read(name), f"{path.name}:{name}"
