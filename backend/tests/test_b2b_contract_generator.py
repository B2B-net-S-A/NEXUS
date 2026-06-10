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


# ── Per-klient override § 10 (Centrum e-Zdrowia, PFRON) ──────────────────────


def test_p10_override_matching():
    from app.services.b2b_contract_generator.clause_overrides import override_for_client

    assert override_for_client("Centrum e-Zdrowia", "pl")
    assert override_for_client(
        "Państwowy Fundusz Rehabilitacji Osób Niepełnosprawnych", "pl"
    )
    assert override_for_client("PFRON", "pl")
    # override działa też dla EN (treść angielska)
    assert override_for_client("Centrum e-Zdrowia", "en")
    assert override_for_client("PFRON", "en")
    # brak override: inny klient, pusty
    assert override_for_client("Nordea Bank Abp", "pl") is None
    assert override_for_client("Nordea Bank Abp", "en") is None
    assert override_for_client("", "pl") is None


def test_p10_override_en_uses_english_terminology():
    from app.services.b2b_contract_generator.clause_overrides import override_for_client

    centrum_en = override_for_client("Centrum e-Zdrowia", "en")
    pfron_en = override_for_client("PFRON", "en")
    centrum_txt = " ".join(t for _, t in centrum_en)
    pfron_txt = " ".join(t for _, t in pfron_en)
    assert "Non-Competition Clauses and Contractual Penalties" in centrum_txt
    assert "the State Treasury – Centrum e-Zdrowia" in centrum_txt
    assert "State Fund for the Rehabilitation of Disabled Persons (PFRON)" in pfron_txt
    for marker in (
        "10. The provisions of sections 6–9",
        "PLN 50,000.00",
        "Article 481 of the Civil Code",
    ):
        assert marker in centrum_txt and marker in pfron_txt
    # żaden polski marker w wersji EN
    assert "Skarb Państwa" not in centrum_txt and "Kary Umowne" not in centrum_txt


def test_p10_override_client_descriptor_in_clause6():
    from app.services.b2b_contract_generator.clause_overrides import override_for_client

    centrum = override_for_client("Centrum e-Zdrowia", "pl")
    pfron = override_for_client("PFRON", "pl")
    centrum_txt = " ".join(t for _, t in centrum)
    pfron_txt = " ".join(t for _, t in pfron)
    assert "Skarb Państwa – Centrum e-Zdrowia" in centrum_txt
    assert "PFRON" in pfron_txt and "Rehabilitacji Osób Niepełnosprawnych" in pfron_txt
    # wspólna treść (klauzule 1-5, 7-10) — identyczna poza ust. 6
    for marker in (
        "Klauzule Antykonkurencyjne i Kary Umowne",
        "50.000,00 zł",
        "art. 481",
    ):
        assert marker in centrum_txt and marker in pfron_txt


def test_p10_override_html_swaps_only_section_10():
    from app.services.b2b_contract_generator.clause_overrides import (
        apply_p10_html,
        override_for_client,
    )

    blocks = override_for_client("Centrum e-Zdrowia", "pl")
    sample = (
        "<h2>§ 9</h2>\n<p>poufne</p>\n"
        "<h2>§ 10</h2>\n<p><strong>Klauzule Antykonkurencyjne i Kary Umowne</strong></p>\n"
        "<p>W okresie obowiązywania Umowy ... powstrzymać od:</p>\n"
        "<h2>§ 11</h2>\n<p><strong>Siła wyższa</strong></p>"
    )
    out = apply_p10_html(sample, blocks)
    assert out.count("<h2>§ 10</h2>") == 1
    assert "<h2>§ 9</h2>" in out and "<h2>§ 11</h2>" in out and "Siła wyższa" in out
    assert "Skarb Państwa – Centrum e-Zdrowia" in out
    assert "10. Postanowienia ust. 6–9" in out
    # brak wzorca → bez zmian
    assert apply_p10_html("<p>brak</p>", blocks) == "<p>brak</p>"


def test_p10_override_docx_replaces_in_real_template():
    import docx as _docxlib

    from app.services.b2b_contract_generator.clause_overrides import (
        apply_p10_docx,
        override_for_client,
    )

    doc = _docxlib.Document(str(TEMPLATE_DIR / "umowa_b2b_pl.docx"))
    blocks = override_for_client("Centrum e-Zdrowia", "pl")
    assert apply_p10_docx(doc, blocks) is True
    texts = [(p.text or "").strip() for p in doc.paragraphs]
    joined = "\n".join(texts)
    # domyślny § 10 (klauzula 1 bez prefiksu numeru) zniknął, override jest
    default_c1 = (
        "W okresie obowiązywania Umowy oraz przez okres 12 (dwunastu) miesięcy "
        "po jej rozwiązaniu lub wygaśnięciu, Partner zobowiązuje się powstrzymać od:"
    )
    assert default_c1 not in texts
    assert any(t.startswith("1. W okresie obowiązywania") for t in texts)
    assert "Skarb Państwa – Centrum e-Zdrowia" in joined
    assert any(t.startswith("10. Postanowienia ust. 6–9") for t in texts)
    assert sum(1 for t in texts if t == "§ 10") == 1
    assert any(t == "§ 11" for t in texts)  # granica nienaruszona
