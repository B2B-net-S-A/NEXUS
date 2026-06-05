"""Testy Generatora Umów B2B.

Czysto jednostkowe (bez DB / live-server):
  - katalog 29 ról: liczność, kategorie, unikalność, **brak znamion umowy o
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
            **gender_forms(gender),
        },
        "job": {"id": None, "title": None},
    }


class TestRoleCatalog:
    def test_count_and_unique_slugs(self):
        assert len(B2B_ROLES) == 29
        slugs = [r["slug"] for r in B2B_ROLES]
        assert len(set(slugs)) == 29

    def test_category_distribution(self):
        dist = Counter(r["category_key"] for r in B2B_ROLES)
        assert dist == {
            "infra": 5,
            "dev": 6,
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
        # zakres roli w ostatnim wierszu tabeli Załącznika nr 3
        scope_cell = d.tables[0].rows[-1].cells[1].text
        assert scope_cell.count("•") == len(ctx["b2b"]["scope_items"])


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
    # zakres jako lista <li> (tyle ile bulletów roli)
    assert rendered.count("<li>") == len(ctx["b2b"]["scope_items"])


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
