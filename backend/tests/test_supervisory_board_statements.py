"""Rada (R4): odczyt e-Sprawozdania, pola z księgi, wskaźniki, zapis i bramki."""

from __future__ import annotations

import base64

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.board_document import BoardDocument, BoardFinancialStatement
from app.services.board import analysis
from app.services.board import statements as parser
from tests.test_sales_companies_api import _headers, _user

API = "/api/supervisory-board"
NS = "http://www.mf.gov.pl/schematy/SF/DefinicjeTypySprawozdaniaFinansowe/2018/07/09/JednostkaInnaWZlotych"


def _k(name: str, a: float, b: float, inner: str = "") -> str:
    return f"<{name}><KwotaA>{a}</KwotaA><KwotaB>{b}</KwotaB>{inner}</{name}>"


def sample_xml(year: int = 2025) -> bytes:
    """Fragment e-Sprawozdania w układzie schematu MF (rok bieżący / poprzedni)."""

    bilans = (
        "<Bilans>"
        + _k(
            "Aktywa",
            30_000_000,
            25_000_000,
            _k("Aktywa_A", 2_000_000, 1_500_000)
            + _k(
                "Aktywa_B",
                28_000_000,
                23_500_000,
                _k("Aktywa_B_I", 0, 0)
                + _k(
                    "Aktywa_B_II",
                    20_000_000,
                    18_000_000,
                    _k(
                        "Aktywa_B_II_3",
                        20_000_000,
                        18_000_000,
                        _k("Aktywa_B_II_3_A", 19_000_000, 17_000_000),
                    ),
                )
                + _k(
                    "Aktywa_B_III",
                    7_500_000,
                    5_000_000,
                    _k(
                        "Aktywa_B_III_1",
                        7_500_000,
                        5_000_000,
                        _k("Aktywa_B_III_1_C", 7_500_000, 5_000_000),
                    ),
                )
                + _k("Aktywa_B_IV", 500_000, 500_000),
            ),
        )
        + _k(
            "Pasywa",
            30_000_000,
            25_000_000,
            _k(
                "Pasywa_A",
                12_000_000,
                9_000_000,
                _k("Pasywa_A_I", 1_000_000, 1_000_000),
            )
            + _k(
                "Pasywa_B",
                18_000_000,
                16_000_000,
                _k("Pasywa_B_I", 1_000_000, 800_000)
                + _k(
                    "Pasywa_B_II",
                    1_000_000,
                    1_200_000,
                    _k(
                        "Pasywa_B_II_3",
                        1_000_000,
                        1_200_000,
                        _k("Pasywa_B_II_3_C", 1_000_000, 1_200_000),
                    ),
                )
                + _k(
                    "Pasywa_B_III",
                    16_000_000,
                    14_000_000,
                    _k(
                        "Pasywa_B_III_3",
                        16_000_000,
                        14_000_000,
                        _k("Pasywa_B_III_3_A", 2_000_000, 0)
                        + _k("Pasywa_B_III_3_D", 12_000_000, 11_000_000),
                    ),
                ),
            ),
        )
        + "</Bilans>"
    )
    rzis = (
        "<RZiS><RZiSPor>"
        + _k("A", 120_000_000, 100_000_000)
        + _k("B", 112_000_000, 94_000_000, _k("B_I", 400_000, 300_000))
        + _k("C", 8_000_000, 6_000_000)
        + _k("F", 7_800_000, 5_900_000)
        + _k("H", 300_000, 200_000)
        + _k("I", 7_500_000, 5_700_000)
        + _k("J", 1_500_000, 1_100_000)
        + _k("L", 6_000_000, 4_600_000)
        + "</RZiSPor></RZiS>"
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<JednostkaInna xmlns="{NS}"><Naglowek><OkresOd>{year}-01-01</OkresOd>'
        f"<OkresDo>{year}-12-31</OkresDo></Naglowek>{bilans}{rzis}</JednostkaInna>"
    ).encode()


# ── Parser ───────────────────────────────────────────────────────────────────


def test_element_path_follows_annex_numbering() -> None:
    assert parser.element_path("Aktywa_B_III_1_C", None) == "assets:B.III.1.c"
    assert parser.element_path("Pasywa_B_III_3_D", None) == "liabilities:B.III.3.d"
    assert parser.element_path("Aktywa", None) == "assets:"
    assert parser.element_path("B_I", "income") == "income:B.I"
    assert parser.element_path("RZiSPor_A", "income") == "income:A"
    assert parser.element_path("A_II_1", "cashflow") == "cashflow:A.II.1"
    assert parser.element_path("OkresOd", "income") is None
    assert parser.element_path("B_I", None) is None


def test_parse_xml_reads_both_columns_and_period() -> None:
    parsed = parser.parse_xml(sample_xml())
    assert parsed.year == 2025
    assert parsed.schema_name == "JednostkaInna"
    current = parsed.amounts(0)
    assert current["revenue"] == 120_000_000
    assert current["cash"] == 7_500_000
    assert current["trade_receivables"] == 19_000_000
    assert current["st_loans"] == 2_000_000
    assert current["lt_other_financial"] == 1_000_000
    assert current["trade_payables"] == 12_000_000
    assert current["depreciation"] == 400_000
    assert current["net_profit"] == 6_000_000
    assert current["inventories"] == 0
    assert current["lt_loans"] is None  # pozycji nie ma w pliku
    previous = parsed.amounts(1)
    assert previous["revenue"] == 100_000_000 and previous["st_loans"] == 0


def test_parse_xml_unwraps_signed_xades() -> None:
    inner = base64.b64encode(sample_xml(2024)).decode()
    signed = (
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
        f'<ds:Object Id="o">{inner}</ds:Object></ds:Signature>'
    ).encode()
    assert parser.parse_xml(signed).year == 2024


@pytest.mark.parametrize(
    "content",
    [
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><JednostkaInna/>',
        b"not xml at all",
        b"<Faktura><P_1>2025-01-01</P_1></Faktura>",
        b"<JednostkaInna><Naglowek/></JednostkaInna>",
    ],
)
def test_parse_xml_rejects_entities_and_foreign_files(content: bytes) -> None:
    with pytest.raises(parser.StatementError):
        parser.parse_xml(content)


def test_parse_xml_rejects_doctype_hidden_by_padding_or_utf16() -> None:
    entity = (
        '<!DOCTYPE JednostkaInna [<!ENTITY e "999">]>'
        "<JednostkaInna><Naglowek><OkresDo>2025-12-31</OkresDo></Naglowek>"
        "<Bilans><Aktywa><KwotaA>&e;</KwotaA><KwotaB>1</KwotaB></Aktywa></Bilans>"
        "</JednostkaInna>"
    )
    padded = ('<?xml version="1.0"?><!--' + "x" * 300_000 + "-->" + entity).encode()
    utf16 = ('<?xml version="1.0" encoding="UTF-16"?>' + entity).encode("utf-16")
    for content in (padded, utf16):
        with pytest.raises(parser.StatementError):
            parser.parse_xml(content)


def test_parse_xml_scales_statement_in_thousands() -> None:
    content = sample_xml().replace(b"JednostkaInna", b"JednostkaInnaWTysiacach")
    parsed = parser.parse_xml(content)
    assert parsed.amounts(0)["revenue"] == 120_000_000_000
    assert parsed.schema_name == "JednostkaInnaWTysiacach"


def test_parse_xml_rejects_small_entity_layouts() -> None:
    content = sample_xml().replace(b"JednostkaInna", b"JednostkaMala")
    with pytest.raises(parser.StatementError, match="JednostkaInna"):
        parser.parse_xml(content)


def test_clean_manual_rejects_unknown_fields_and_huge_amounts() -> None:
    assert parser.clean_manual({"revenue": "1000.5"})["revenue"] == 1000.5
    with pytest.raises(parser.StatementError):
        parser.clean_manual({"zysk": 1})
    with pytest.raises(parser.StatementError):
        parser.clean_manual({"revenue": 1e12})


def test_ledger_paths_map_tree_numbers_and_grosze() -> None:
    report = {
        "balance": {
            "assets_total": 10_000_00,
            "liabilities_total": 10_000_00,
            "assets": [
                {
                    "number": "B",
                    "amount": 9_000_00,
                    "children": [
                        {
                            "number": "III",
                            "amount": 4_000_00,
                            "children": [
                                {
                                    "number": "1",
                                    "amount": 4_000_00,
                                    "children": [
                                        {
                                            "number": "c)",
                                            "amount": 4_000_00,
                                            "children": [],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "liabilities": [],
        },
        "income": {
            "lines": [
                {"number": "A", "amount": 50_000_00, "children": []},
                {
                    "number": "B",
                    "amount": 45_000_00,
                    "children": [{"number": "I", "amount": 1_000_00}],
                },
                {"number": "F", "amount": 5_000_00, "children": []},
            ]
        },
    }
    amounts = parser.normalize(parser.ledger_paths(report))
    assert amounts["cash"] == 4000.0
    assert amounts["total_assets"] == 10000.0
    assert amounts["revenue"] == 50000.0
    assert amounts["depreciation"] == 1000.0


# ── Wskaźniki ────────────────────────────────────────────────────────────────


def test_metrics_credit_and_valuation_from_statement() -> None:
    v = parser.parse_xml(sample_xml()).amounts(0)
    m = analysis.metrics(v)
    assert m["ebitda"] == 8_200_000
    assert m["financial_debt"] == 3_000_000
    assert m["net_debt"] == -4_500_000  # więcej gotówki niż długu
    assert m["current_ratio"] == 1.75
    assert m["quick_ratio"] == round(27_500_000 / 16_000_000, 2)
    assert m["dso"] == round(19_000_000 / 120_000_000 * 365)
    assert m["net_debt_ebitda"] == round(-4_500_000 / 8_200_000, 2)
    c = analysis.credit(v, m)
    assert c["max_net_debt"] == 24_600_000
    assert c["headroom"] == 29_100_000
    assert c["factoring_limit"] == 16_150_000
    val = analysis.valuation(v, m)
    assert val["financial"]["ev"] == 49_200_000
    assert val["financial"]["equity"] == 53_700_000
    assert val["strategic"]["ev"] == 65_600_000


def test_metrics_without_data_give_none_not_zero() -> None:
    m = analysis.metrics({key: None for key in parser.FIELD_KEYS})
    assert all(value is None for value in m.values())
    loss = analysis.metrics({"operating_profit": -1_000_000, "depreciation": 100_000})
    assert loss["ebitda"] == -900_000 and loss["net_debt_ebitda"] is None
    assert analysis.valuation({}, loss)["financial"]["ev"] is None


def test_analyse_years_adds_growth() -> None:
    rows = analysis.analyse_years(
        [
            {"year": 2025, "amounts": {"revenue": 120.0}},
            {"year": 2024, "amounts": {"revenue": 100.0}},
        ]
    )
    assert [row["year"] for row in rows] == [2024, 2025]
    assert rows[1]["growth"]["revenue"] == 20.0
    assert rows[0]["growth"]["revenue"] is None


# ── API ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def _clean_statements():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoardFinancialStatement))
        await db.execute(delete(BoardDocument))
        await db.commit()
    yield


async def test_import_xml_fills_year_and_previous_year(
    app_client, _clean_statements
) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    response = await app_client.post(
        f"{API}/statements/import",
        headers=_headers(admin),
        files={"file": ("sf2025.xml", sample_xml(), "application/xml")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["year"] == 2025 and body["previous_year_filled"] is True
    assert body["fields_found"] >= 15

    view = (await app_client.get(f"{API}/analysis", headers=_headers(board))).json()
    years = {row["year"]: row for row in view["years"]}
    assert years[2025]["source"] == "xml"
    assert years[2024]["source"] == "xml_prev"
    assert years[2025]["metrics"]["ebitda"] == 8_200_000
    assert years[2025]["growth"]["revenue"] == 20.0

    doc = await app_client.get(
        f"{API}/documents/{body['document_id']}/file", headers=_headers(board)
    )
    assert doc.status_code == 200 and doc.content.startswith(b"<?xml")

    # Wpis ręczny za 2024 wygrywa z kolumną „rok poprzedni” i nie jest nadpisany
    # przez kolejny import pliku za 2025.
    manual = await app_client.put(
        f"{API}/statements/2024",
        headers=_headers(admin),
        json={"amounts": {"revenue": 99_000_000}, "note": "z PDF"},
    )
    assert manual.status_code == 200, manual.text
    again = await app_client.post(
        f"{API}/statements/import",
        headers=_headers(admin),
        files={"file": ("sf2025.xml", sample_xml(), "application/xml")},
    )
    assert again.json()["previous_year_filled"] is False
    view = (await app_client.get(f"{API}/analysis", headers=_headers(board))).json()
    years = {row["year"]: row for row in view["years"]}
    assert years[2024]["source"] == "manual"
    assert years[2024]["amounts"]["revenue"] == 99_000_000


async def test_reimport_reuses_the_same_document(app_client, _clean_statements) -> None:
    admin = await _user(role="admin")
    ids = set()
    for _ in range(2):
        response = await app_client.post(
            f"{API}/statements/import",
            headers=_headers(admin),
            files={"file": ("sf2025.xml", sample_xml(), "application/xml")},
        )
        assert response.status_code == 200, response.text
        ids.add(response.json()["document_id"])
    assert len(ids) == 1
    async with AsyncSessionLocal() as db:
        docs = (
            (
                await db.execute(
                    select(BoardDocument).where(
                        BoardDocument.category == "financial_statement"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(docs) == 1


async def test_statements_board_reads_admin_writes_others_denied(
    app_client, _clean_statements
) -> None:
    board = await _user(role="board")
    finance = await _user(role="finance")
    recruiter = await _user(role="recruiter")
    for user in (finance, recruiter):
        response = await app_client.get(f"{API}/analysis", headers=_headers(user))
        assert response.status_code == 403, (user.role, response.text)
    assert (
        await app_client.get(f"{API}/analysis", headers=_headers(board))
    ).status_code == 200
    denied = await app_client.put(
        f"{API}/statements/2024", headers=_headers(board), json={"amounts": {}}
    )
    assert denied.status_code == 403
    upload = await app_client.post(
        f"{API}/statements/import",
        headers=_headers(board),
        files={"file": ("sf.xml", sample_xml(), "application/xml")},
    )
    assert upload.status_code == 403


async def test_import_rejects_wrong_files(app_client, _clean_statements) -> None:
    admin = await _user(role="admin")
    pdf = await app_client.post(
        f"{API}/statements/import",
        headers=_headers(admin),
        files={"file": ("sf.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert pdf.status_code == 422
    foreign = await app_client.post(
        f"{API}/statements/import",
        headers=_headers(admin),
        files={"file": ("fa.xml", b"<Faktura/>", "application/xml")},
    )
    assert foreign.status_code == 422
    assert "JednostkaInna" in foreign.json()["detail"]
    future = await app_client.put(
        f"{API}/statements/2999", headers=_headers(admin), json={"amounts": {}}
    )
    assert future.status_code == 422
    unknown = await app_client.put(
        f"{API}/statements/2024", headers=_headers(admin), json={"amounts": {"x": 1}}
    )
    assert unknown.status_code == 422
    missing = await app_client.delete(f"{API}/statements/2020", headers=_headers(admin))
    assert missing.status_code == 404
