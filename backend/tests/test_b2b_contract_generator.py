"""Testy Generatora Umów B2B.

Czysto jednostkowe (bez DB / live-server):
  - katalog 30 ról: liczność, kategorie, unikalność, **brak znamion umowy o
    pracę** (art. 22 §1 KP) w zakresach,
  - render DOCX (docxtpl) na szablonach PL/EN: pola wypełnione, zakres roli w
    Załączniku nr 3, escapowanie XML, brak osieroconych tagów,
  - render HTML (Jinja `_jinja_env` + filtr `pl_date`) na szablonach PL/EN.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from pathlib import Path

import docx as _docx
import pytest
from docxtpl import DocxTemplate
from jinja2 import Environment

from app.api.contract_templates import _jinja_env
from app.data.b2b_roles import B2B_ROLES, CATEGORY_LABELS
from app.services.b2b_contract_generator.formatting import pl_date
from app.services.b2b_contract_generator.gender import gender_forms

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "app" / "templates" / "contract"

# Frazy o znamionach umowy o pracę — NIE mogą wystąpić w zakresach ról.
_EMPLOYMENT_DENYLIST = [
    r"podporz[aą]dkowani",
    r"polece\w*\s+prze[lł]o[zż]on",
    r"godzin\w*\s+pracy",
    r"czas\w*\s+pracy",
    r"\burlop",
    r"stosun\w*\s+pracy",
    r"wynagrodzeni\w*\s+za\s+prac",
    r"\bpodw[lł]adn",
    r"\betat",
]


def _sample_context(lang: str = "pl", gender: str = "m") -> dict:
    # rola Backend (indeks 5) — 6 bulletów (4 merytoryczne + 2 niezależność).
    scope = B2B_ROLES[5]["scope_pl"] if lang == "pl" else B2B_ROLES[5]["scope_en"]
    return {
        "candidate": {
            "full_name": "Jan Kowalski & Co",
            "legal_name": "JK Software",
            "nip": "1234567890",
            "regon": "123456789",
            "business_address": "ul. Testowa 1, 00-001 Warszawa",
            "phone": "+48 600 100 200",
            "email": "jan@example.com",
            "address": "Warszawa",
        },
        "client": {
            "name": "ACME Bank",
            "legal_name": "ACME Bank S.A.",
            "nip": "9876543210",
            "regon": None,
            "address": "Kraków",
        },
        "contract": {
            "id": 1,
            "rate_candidate": 150,
            "currency": "PLN",
            "start_date": date(2026, 7, 1),
            "end_date": None,
            "rate_unit": "hourly",
            "contract_type": "b2b",
            "billing_hours_per_month": 160,
            "project_name": None,
            "team_name": None,
            "office_location": None,
            "work_mode": None,
            "client_pm_name": None,
            "client_pm_email": None,
        },
        "b2b": {
            "contract_number": "42/2026",
            "signing_date": date(2026, 6, 5),
            "project_city": "Kraków",
            "project_description": "Rozwój platformy bankowej.",
            "correspondence_address": None,
            "rate_in_words": "sto pięćdziesiąt",
            "area_label": "Backend Software Development",
            "role_name": "Backend Software Development",
            "language": lang,
            "scope_items": scope,
            "start_clause": "z dniem 01.07.2026" if lang == "pl" else "on 01.07.2026",
            "partner_instrumental": "Jan Kowalski & Co",
            **gender_forms(gender),
        },
        "job": {"id": None, "title": None},
    }


class TestRoleCatalog:
    def test_count_and_unique_slugs(self):
        assert len(B2B_ROLES) == 30
        slugs = [r["slug"] for r in B2B_ROLES]
        assert len(set(slugs)) == 30
        assert "software-development" in slugs

    def test_category_distribution(self):
        dist = Counter(r["category_key"] for r in B2B_ROLES)
        assert dist == {
            "infra": 5,
            "dev": 7,
            "data_ai": 5,
            "security_qa": 7,
            "management": 6,
        }
        for r in B2B_ROLES:
            assert r["category_key"] in CATEGORY_LABELS

    def test_scopes_nonempty_bilingual(self):
        for r in B2B_ROLES:
            assert len(r["scope_pl"]) >= 5, r["slug"]
            assert len(r["scope_en"]) >= 5, r["slug"]
            assert r["area_label_pl"] and r["area_label_en"]

    @pytest.mark.parametrize("scope_key", ["scope_pl", "scope_en"])
    def test_no_employment_hallmarks(self, scope_key):
        """KRYTYCZNE: zakresy nie mogą nosić znamion umowy o pracę."""
        for r in B2B_ROLES:
            text = " ".join(r[scope_key]).lower()
            for pat in _EMPLOYMENT_DENYLIST:
                assert not re.search(pat, text), (
                    f"{r['slug']}/{scope_key}: zakazana fraza '{pat}'"
                )


@pytest.mark.parametrize("lang", ["pl", "en"])
class TestDocxRender:
    def test_template_present(self, lang):
        assert (TEMPLATE_DIR / f"umowa_b2b_{lang}.docx").is_file()

    def test_render_fills_all_placeholders(self, lang, tmp_path):
        env = Environment(autoescape=True)
        env.filters["pl_date"] = pl_date
        tpl = DocxTemplate(str(TEMPLATE_DIR / f"umowa_b2b_{lang}.docx"))
        ctx = _sample_context(lang)
        tpl.render(ctx, jinja_env=env)
        out = tmp_path / f"out_{lang}.docx"
        tpl.save(str(out))

        d = _docx.Document(str(out))
        full = (
            "\n".join(p.text for p in d.paragraphs)
            + "\n"
            + "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
        )
        # wszystkie tagi skonsumowane
        assert "{{" not in full and "{%" not in full
        # pola wypełnione (& poprawnie zescapowane do XML → czyta się z &)
        assert "Jan Kowalski & Co" in full
        assert "1234567890" in full  # NIP
        assert "42/2026" in full  # nr umowy
        assert "05.06.2026" in full  # filtr pl_date
        assert "Backend Software Development" in full  # obszar §1
        # „Szczegółowy zakres Usług" usunięty — opis trafia w pole „Opis projektu"
        assert "Szczegółowy zakres" not in full and "Detailed scope" not in full
        assert "Rozwój platformy bankowej." in full  # project_description w Zał.3


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_html_template_renders(lang):
    html_path = TEMPLATE_DIR / f"umowa_b2b_{lang}.html"
    assert html_path.is_file()
    ctx = _sample_context(lang)
    rendered = _jinja_env.from_string(html_path.read_text(encoding="utf-8")).render(
        **ctx
    )
    assert "{{" not in rendered and "{%" not in rendered
    assert "42/2026" in rendered
    assert "05.06.2026" in rendered
    assert "Backend Software Development" in rendered
    # „Szczegółowy zakres Usług" usunięty — brak osobnego wiersza zakresu
    assert "Szczegółowy zakres" not in rendered and "Detailed scope" not in rendered
    assert "Rozwój platformy bankowej." in rendered  # opis projektu w Zał.3


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_company_full_name_is_lowercase_net(lang, tmp_path):
    """Pełna nazwa spółki = „B2B.net S.A." (małe „net") w DOCX i HTML; skrót
    „B2BNET" (termin zdefiniowany w komparycji) pozostaje bez zmian.

    Forma „B2B.NET" (wielkie litery) nie może wystąpić nigdzie — to ona była
    zgłoszona jako błędna."""
    env = Environment(autoescape=True)
    env.filters["pl_date"] = pl_date
    tpl = DocxTemplate(str(TEMPLATE_DIR / f"umowa_b2b_{lang}.docx"))
    tpl.render(_sample_context(lang), jinja_env=env)
    out = tmp_path / f"name_{lang}.docx"
    tpl.save(str(out))
    d = _docx.Document(str(out))
    # python-docx łączy runy, więc rozbita nazwa („B2B." + „net" + „ S.A.")
    # czyta się jako spójne „B2B.net S.A.".
    docx_text = (
        "\n".join(p.text for p in d.paragraphs)
        + "\n"
        + "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    )
    html_text = _jinja_env.from_string(
        (TEMPLATE_DIR / f"umowa_b2b_{lang}.html").read_text(encoding="utf-8")
    ).render(**_sample_context(lang))

    for surface, text in (("docx", docx_text), ("html", html_text)):
        assert "B2B.NET" not in text, f"[{lang}/{surface}] została wielka „B2B.NET”"
        assert "B2B.net S.A." in text, f"[{lang}/{surface}] brak „B2B.net S.A.”"
        assert "B2BNET" in text, f"[{lang}/{surface}] zniknął skrót „B2BNET”"


def test_pl_template_gender_forms():
    """Formy zależne od płci podstawiają się; B2BNET (spółka) zostaje żeńskie."""
    html = (TEMPLATE_DIR / "umowa_b2b_pl.html").read_text(encoding="utf-8")
    tpl = _jinja_env.from_string(html)

    male = tpl.render(**_sample_context("pl", gender="m"))
    assert "Panem Jan Kowalski" in male
    assert "prowadzącym działalność" in male
    assert "zapoznałem się" in male
    assert "zwany w dalszej części umowy" in male

    female = tpl.render(**_sample_context("pl", gender="k"))
    assert "Panią Jan Kowalski" in female
    assert "prowadzącą działalność" in female
    assert "zapoznałam się" in female
    assert "zwana w dalszej części umowy" in female

    # B2BNET S.A. = spółka → „zwaną dalej Administratorem" zawsze żeńskie,
    # niezależnie od płci Partnera.
    assert "zwaną dalej „Administratorem" in male
    assert "zwaną dalej „Administratorem" in female


def test_en_template_gender_forms():
    html = (TEMPLATE_DIR / "umowa_b2b_en.html").read_text(encoding="utf-8")
    tpl = _jinja_env.from_string(html)
    assert "Mr Jan Kowalski" in tpl.render(**_sample_context("en", gender="m"))
    assert "Ms Jan Kowalski" in tpl.render(**_sample_context("en", gender="k"))


def test_rate_in_words_zloty_plural():
    from app.services.b2b_contract_generator.number_words import rate_in_words

    assert rate_in_words(120, "pl", "PLN") == "sto dwadzieścia złotych"
    assert rate_in_words(1, "pl", "PLN") == "jeden złoty"
    assert rate_in_words(2, "pl", "PLN") == "dwa złote"
    assert rate_in_words(5, "pl", "PLN") == "pięć złotych"
    assert rate_in_words(22, "pl", "PLN") == "dwadzieścia dwa złote"
    assert rate_in_words(12, "pl", "PLN") == "dwanaście złotych"
    assert rate_in_words(120, "en", "PLN") == "one hundred twenty zlotys"
    assert rate_in_words(100, "pl", "EUR") == "sto EUR"


def test_rate_in_words_with_grosze():
    """Stawka ułamkowa (135,5) → słownie z groszami, by zgadzało się z kwotą."""
    from app.services.b2b_contract_generator.number_words import rate_in_words

    assert (
        rate_in_words(135.5, "pl", "PLN")
        == "sto trzydzieści pięć złotych pięćdziesiąt groszy"
    )
    assert rate_in_words(100.01, "pl", "PLN") == "sto złotych jeden grosz"
    assert rate_in_words(2.02, "pl", "PLN") == "dwa złote dwa grosze"
    assert (
        rate_in_words(135.5, "en", "PLN")
        == "one hundred thirty five zlotys fifty groszy"
    )
    # Inna waluta → bez części groszowej (tylko kod waluty).
    assert rate_in_words(100.5, "pl", "EUR") == "sto EUR"


def test_format_rate_polish_comma():
    """Liczba całkowita → bez przecinka; ułamkowa → polski zapis „135,50"."""
    from app.services.b2b_contract_generator.formatting import format_rate

    assert format_rate(150) == "150"
    assert format_rate(150.0) == "150"
    assert format_rate(135.5) == "135,50"
    assert format_rate(99.99) == "99,99"
    assert format_rate(None) is None


def test_render_context_accepts_fractional_rate():
    """Regresja 422: stawka ułamkowa (135.5) renderuje się — kwota „135,50"
    + spójne słownie z groszami w kontekście umowy."""
    from app.schemas.b2b_contract_generator import B2BRenderRequest
    from app.services.b2b_contract_generator.render_context import (
        build_render_context,
    )

    req = B2BRenderRequest(
        role_id=None,
        language="pl",
        partner_name="Jan Kowalski",
        start_date=date(2026, 7, 1),
        rate_candidate=135.5,
        currency="PLN",
    )
    ctx = build_render_context(req, None)
    assert ctx["contract"]["rate_candidate"] == "135,50"
    assert ctx["b2b"]["rate_in_words"] == (
        "sto trzydzieści pięć złotych pięćdziesiąt groszy"
    )


def test_generate_request_accepts_fractional_rate():
    """Regresja: stawka kandydata ułamkowa (83,5) musi przejść przez
    `B2BGenerateRequest` bez zaokrąglania. Wcześniej pole było `int` → Pydantic
    odrzucał 83.5 (422), więc do „szablonu" wchodziła zaokrąglona 84, a na
    `Contract.rate_candidate` (Numeric(12,3)) zapisywała się liczba całkowita."""
    from app.schemas.b2b_contract_generator import B2BGenerateRequest

    req = B2BGenerateRequest(
        candidate_id=1,
        client_id=2,
        role_id=3,
        start_date=date(2026, 7, 1),
        rate_candidate=83.5,
    )
    # Grosze zachowane — brak zaokrąglenia do 84.
    assert req.rate_candidate == 83.5


def test_detail_response_preserves_fractional_rate():
    """Read-back stawki ułamkowej z Contract (Numeric(12,3)) nie może się ucinać
    ani wywalać 500 na response_model — pole `float`, nie `int`."""
    from decimal import Decimal

    from app.schemas.b2b_contract_generator import B2BContractDetailResponse

    resp = B2BContractDetailResponse(
        contract_id=1,
        language="pl",
        rate_candidate=Decimal("83.5"),
    )
    assert resp.rate_candidate == 83.5


def test_render_payload_roundtrip_redownload():
    """Ponowne pobranie z listy: payload zapisany jak w logu
    (``model_dump(mode="json")``) odtwarza się w ``B2BRenderRequest`` i
    re-renderuje do prawidłowego DOCX, z numerem nadpisanym z wiersza logu."""
    import io

    from docx import Document

    from app.schemas.b2b_contract_generator import B2BRenderRequest
    from app.services.b2b_contract_generator.docx_renderer import (
        render_from_context,
    )
    from app.services.b2b_contract_generator.render_context import (
        build_render_context,
    )

    req = B2BRenderRequest(
        role_id=None,
        language="pl",
        partner_name="Jan Kowalski",
        client_name="Nordea Bank Abp",
        project_city="Warszawa",
        project_description="Usługi QA i automatyzacja testów.",
        signing_date=date(2026, 6, 16),
        start_date=date(2026, 7, 1),
        rate_candidate=150,
    )
    # Dokładnie tak zapisujemy w b2b_generated_contracts.render_payload …
    stored = req.model_dump(mode="json")
    # … i tak odtwarzamy w GET /generated/{id}/docx.
    restored = B2BRenderRequest(**stored)
    assert restored.signing_date == date(2026, 6, 16)  # data wraca z ISO-stringa

    ctx = build_render_context(restored, None)
    ctx["b2b"]["contract_number"] = "1436/2026"  # numer bierzemy z wiersza logu
    data = render_from_context(ctx, language="pl")

    assert data[:2] == b"PK"  # DOCX = archiwum ZIP
    full = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    assert "1436/2026" in full  # numer odtworzony w dokumencie


# ── Numeracja umów: parser numeru + sugestia kolejnego wolnego ───────────────


def test_parse_seq_extracts_numeric_prefix():
    from app.api.b2b_contract_generator import _parse_seq

    assert _parse_seq("1434/2026") == 1434
    assert _parse_seq("  8 / 2026 ") == 8  # tolerancja na spacje
    assert _parse_seq("1/2026", 2026) == 1
    # year-guard: numer z innego roku nie pasuje do podanego roku
    assert _parse_seq("1434/2025", 2026) is None
    # nie-pasujące formaty → None (a NIE wyjątek)
    assert _parse_seq("1434") is None
    assert _parse_seq("1434-2026") is None
    assert _parse_seq("abc/2026") is None
    assert _parse_seq("") is None
    assert _parse_seq(None) is None


def test_next_seq_uses_max_numeric_prefix_not_row_count():
    """Sugestia = max(realny numer) + 1, odporna na duplikaty i śmieciowe seq.

    Replikuje logikę `_next_seq` na pythonie (bez DB): zbiór numerów taki jak na
    prodzie (1,2,3,4,1433,1434,1434-duplikat) → kolejny WOLNY = 1435, NIE 8."""
    from app.api.b2b_contract_generator import _parse_seq

    numbers = [
        "1/2026",
        "2/2026",
        "3/2026",
        "4/2026",
        "1433/2026",
        "1434/2026",
        "1434/2026",
    ]
    year = 2026
    parsed = [s for n in numbers if (s := _parse_seq(n, year)) is not None]
    assert max(parsed) + 1 == 1435
    # pusty rok → start od 1
    assert (
        max([s for n in [] if (s := _parse_seq(n, year)) is not None], default=0) + 1
    ) == 1


def test_validate_contract_number_canonicalizes():
    """Numer zapisywany jest TYLKO w postaci kanonicznej — „1434 / 2026"
    musi stać się „1434/2026", inaczej ominąłby string-owy check duplikatów."""
    from fastapi import HTTPException

    from app.api.b2b_contract_generator import _validate_contract_number

    assert _validate_contract_number("1434/2026", "1/2026") == (
        1434,
        2026,
        "1434/2026",
    )
    # spacje wokół „/" → kanonikalizacja
    assert _validate_contract_number("1434 / 2026", "1/2026") == (
        1434,
        2026,
        "1434/2026",
    )
    # wiodące zero → kanonikalizacja liczbowa
    assert _validate_contract_number("007/2026", "1/2026") == (7, 2026, "7/2026")

    # złe formaty → 422 z sugestią w komunikacie
    for bad in ("1434", "1434-2026", "abc/2026", "1434/26"):
        with pytest.raises(HTTPException) as exc:
            _validate_contract_number(bad, "1435/2026")
        assert exc.value.status_code == 422
        assert "1435/2026" in exc.value.detail


def test_generated_contract_unique_year_seq_constraint():
    """DB odrzuca drugi wiersz z tą samą parą (year, seq) — ochrona przed
    duplikatem numeru także przy race'ie równoległych renderów (SELECT-check
    w API tego nie łapie). Prod-incydent: id=6 i id=7 oba „1434/2026"."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.models.b2b_generated_contract import B2BGeneratedContract

    engine = create_engine("sqlite://")
    B2BGeneratedContract.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            B2BGeneratedContract(year=2026, seq=1434, contract_number="1434/2026")
        )
        session.commit()

        # inna para (year, seq) → OK
        session.add(
            B2BGeneratedContract(year=2026, seq=1435, contract_number="1435/2026")
        )
        session.commit()

        # duplikat (year, seq) → IntegrityError z constraintu UNIQUE
        session.add(
            B2BGeneratedContract(year=2026, seq=1434, contract_number="1434/2026")
        )
        with pytest.raises(IntegrityError):
            session.commit()


# ── Per-klient modyfikacje umowy (silnik operacji) ──────────────────────────


def _blocks_of(ops, op_kind, target=None):
    for kind, tgt, blocks in ops:
        if kind == op_kind and (target is None or tgt == target):
            return blocks
    return ()


def test_overrides_matching_pl_en():
    from app.services.b2b_contract_generator.clause_overrides import (
        has_override,
        overrides_for_client,
    )

    for name in ("Centrum e-Zdrowia", "PFRON", "BNP Paribas Bank Polska S.A."):
        assert overrides_for_client(name, "pl")
        assert overrides_for_client(name, "en")
        assert has_override(name)
    assert overrides_for_client("Nordea Bank Abp", "pl") == []
    assert overrides_for_client("", "pl") == []


def test_p10_replace_section_op_centrum_pfron():
    from app.services.b2b_contract_generator.clause_overrides import (
        overrides_for_client,
    )

    cen = overrides_for_client("Centrum e-Zdrowia", "pl")
    assert cen[0][0] == "replace_section" and cen[0][1] == 10
    txt = " ".join(t for _, t in _blocks_of(cen, "replace_section", 10))
    assert "Skarb Państwa – Centrum e-Zdrowia" in txt
    assert "10. Postanowienia ust. 6–9" in txt
    pf = overrides_for_client("PFRON", "en")
    pftxt = " ".join(t for _, t in _blocks_of(pf, "replace_section", 10))
    assert "State Fund for the Rehabilitation of Disabled Persons (PFRON)" in pftxt
    assert "Non-Competition Clauses and Contractual Penalties" in pftxt


def test_bnp_ops_replace_s4_and_zal1_sentence():
    from app.services.b2b_contract_generator.clause_overrides import (
        overrides_for_client,
    )

    pl = overrides_for_client("BNP Paribas Bank Polska S.A.", "pl")
    kinds = [k for k, _, _ in pl]
    assert "replace_section" in kinds and "after_sentence" in kinds
    s4 = " ".join(t for _, t in _blocks_of(pl, "replace_section", 4))
    assert "Ogólne zasady współpracy" in s4
    assert "15. Postanowienia ust. 13" in s4
    assert "Kodeksie Postępowania Grupy BNP" in s4
    # after_sentence: anchor + treść
    for kind, anchor, blocks in pl:
        if kind == "after_sentence":
            assert "z niniejszą deklaracją, rozumiem jej treść" == anchor
            assert "zapoznałem się z Kodeksem Postępowania Grupy BNP" in blocks[0][1]
    en = overrides_for_client("BNP Paribas Bank Polska S.A.", "en")
    s4en = " ".join(t for _, t in _blocks_of(en, "replace_section", 4))
    assert "General Principles of Cooperation" in s4en
    assert "15. The provisions of section 13" in s4en


def test_engine_replace_section_on_real_pl_template():
    import docx as _docxlib

    from app.services.b2b_contract_generator.clause_overrides import (
        apply_ops_docx,
        overrides_for_client,
    )

    doc = _docxlib.Document(str(TEMPLATE_DIR / "umowa_b2b_pl.docx"))
    ops = overrides_for_client("BNP Paribas Bank Polska S.A.", "pl")
    assert apply_ops_docx(doc, ops) == 2
    texts = [(p.text or "").strip() for p in doc.paragraphs]
    joined = "\n".join(texts)
    assert any(t.startswith("15. Postanowienia ust. 13") for t in texts)  # nowy §4
    assert not any(
        t.startswith("Postanowienia ust. 8 nie mają") for t in texts
    )  # stary §4
    assert sum(1 for t in texts if t == "§ 4") == 1
    assert any(t == "§ 5" for t in texts)  # granica
    assert "zapoznałem się z Kodeksem Postępowania Grupy BNP" in joined  # Zał.1


def test_engine_html_ops_swaps_only_targets():
    from app.services.b2b_contract_generator.clause_overrides import (
        apply_ops_html,
        overrides_for_client,
    )

    sample = (
        "<h2>§ 3</h2>\n<p>three</p>\n<h2>§ 4</h2>\n<p><strong>Ogólne</strong></p>\n"
        "<p>old four</p>\n<h2>§ 5</h2>\n<p>five</p>\n"
        "<p>Oświadczam, iż zapoznałem się z niniejszą deklaracją, rozumiem jej treść"
        " i zobowiązuję się.</p>\n<p>after</p>"
    )
    out = apply_ops_html(sample, overrides_for_client("BNP Paribas", "pl"))
    assert out.count("<h2>§ 4</h2>") == 1
    assert "<h2>§ 3</h2>" in out and "<h2>§ 5</h2>" in out
    assert "15. Postanowienia ust. 13" in out
    assert "old four" not in out
    assert "zapoznałem się z Kodeksem Postępowania Grupy BNP" in out


def _render_docx_with_overrides(client_name: str, lang: str = "pl"):
    """Render szablonu DOCX + per-klient operacje (bez DB) → Document."""
    from app.services.b2b_contract_generator.clause_overrides import (
        apply_ops_docx,
        overrides_for_client,
    )

    doc = _docx.Document(str(TEMPLATE_DIR / f"umowa_b2b_{lang}.docx"))
    apply_ops_docx(doc, overrides_for_client(client_name, lang))
    return doc


def test_alior_zalacznik3_single_signature_after_table():
    """Załącznik nr 3: pod oświadczeniem (po tabeli) tylko JEDEN podpis.

    Szablon ma już blok podpisu po tabeli; nie wolno dokładać drugiego.
    """
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    doc = _render_docx_with_overrides("Alior Bank S.A.", "pl")
    seen_tbl = False
    pairs = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:tbl"):
            seen_tbl = True
            continue
        if seen_tbl and child.tag == qn("w:p"):
            t = (Paragraph(child, doc).text or "").strip()
            if "B2B.net S.A." in t and "Partner" in t:
                pairs += 1
    assert pairs == 1, f"oczekiwano 1 podpisu po tabeli, jest {pairs}"


@pytest.mark.parametrize(
    ("client_name", "section"),
    [("Alior Bank S.A.", r"§\s*4\s*A"), ("BNP Paribas Bank Polska S.A.", r"§\s*4")],
)
def test_injected_clause_paragraphs_have_no_left_indent(client_name, section):
    """Klauzule numerowane (`p`) wstrzykiwane do § 4A/§ 4 nie mają wcięcia
    akapitu — flush jak natywne paragrafy umowy (left_indent=None)."""
    doc = _render_docx_with_overrides(client_name, "pl")
    in_sec = False
    checked = 0
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if re.fullmatch(section, t):
            in_sec = True
            continue
        if in_sec and re.fullmatch(r"§\s*\d+\s*A?", t):
            break
        # tylko klauzule numerowane („1.", „2.") = kind `p`; podpunkty a)/b)
        # (kind `i`) zachowują wcięcie 0.5" celowo.
        if in_sec and re.match(r"\d+\.", t) and len(t) > 80:
            assert p.paragraph_format.left_indent is None
            checked += 1
    assert checked > 0, "nie znaleziono akapitów klauzul do weryfikacji wcięcia"


# ── PATCH /generated/{id} — korekta nazwy Klienta (in-process, real DB) ───────


async def _seed_generated_contract(created_by: int, client_name: str) -> int:
    """Wstaw wiersz `b2b_generated_contracts` z zapisanym payloadem (jak render
    DOCX) i zwróć jego id. `seq`/numer z UUID → brak kolizji z UNIQUE(year, seq)
    przy powtórnym uruchomieniu testu na tej samej bazie."""
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    seq = 100000 + (uuid.uuid4().int % 800000)
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name="Jan Kowalski",
            client_name=client_name,
            language="pl",
            created_by=created_by,
            render_payload={
                "language": "pl",
                "client_name": client_name,
                "currency": "PLN",
            },
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _admin_user_id(app_client) -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None, "app_client nie zaseedował admina"
    return uid


async def test_patch_generated_updates_client_name_and_payload(
    app_client, app_auth_headers
):
    """PATCH poprawia nazwę Klienta w kolumnie *oraz* w `render_payload` — żeby
    ponowne pobranie DOCX (i klauzule per-klient) używały już poprawnej nazwy."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    admin_id = await _admin_user_id(app_client)
    rid = await _seed_generated_contract(admin_id, "Nordea Bank Abp")  # literówka

    resp = await app_client.patch(
        f"/api/b2b-generator/generated/{rid}",
        headers=app_auth_headers,
        json={"client_name": "Nordea Bank Abp S.A. Oddział w Polsce"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["client_name"] == "Nordea Bank Abp S.A. Oddział w Polsce"
    assert body["can_edit"] is True

    # Kolumna i render_payload zsynchronizowane w DB.
    async with AsyncSessionLocal() as db:
        fresh = await db.get(B2BGeneratedContract, rid)
        assert fresh.client_name == "Nordea Bank Abp S.A. Oddział w Polsce"
        assert (
            fresh.render_payload["client_name"]
            == "Nordea Bank Abp S.A. Oddział w Polsce"
        )


async def test_patch_generated_trims_and_lists_corrected_name(
    app_client, app_auth_headers
):
    """Whitespace jest przycinany, a lista `/generated` pokazuje poprawioną nazwę."""
    admin_id = await _admin_user_id(app_client)
    rid = await _seed_generated_contract(admin_id, "Aliior Bank")  # literówka

    resp = await app_client.patch(
        f"/api/b2b-generator/generated/{rid}",
        headers=app_auth_headers,
        json={"client_name": "  Alior Bank S.A.  "},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_name"] == "Alior Bank S.A."

    listing = await app_client.get(
        "/api/b2b-generator/generated",
        headers=app_auth_headers,
        params={"limit": 200},
    )
    assert listing.status_code == 200, listing.text
    match = next((x for x in listing.json() if x["id"] == rid), None)
    assert match is not None
    assert match["client_name"] == "Alior Bank S.A."
    assert match["can_edit"] is True


async def test_patch_generated_missing_row_404(app_client, app_auth_headers):
    resp = await app_client.patch(
        "/api/b2b-generator/generated/999999999",
        headers=app_auth_headers,
        json={"client_name": "Cokolwiek"},
    )
    assert resp.status_code == 404
