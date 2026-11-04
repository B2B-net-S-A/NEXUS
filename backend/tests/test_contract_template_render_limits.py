"""Runda 11 (SEC): szablony umów renderują się w tym samym ograniczonym
środowisku Jinja co szablony maili autora (runda 9/10).

Szablon umowy pisze Delivery Lead, a render szedł zwykłym ``render()`` — bez
sufitu operacji, czasu, pamięci ani długości wyniku. ``{{ 'a' * 10**9 }}``,
``|join`` z tysiącem kopii długiego napisu albo ``|replace`` budowały w jednym
wywołaniu kodu C napis wielu GB i zabijały jedyny proces uvicorna.
"""

from __future__ import annotations

import time
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from jinja2.exceptions import SecurityError, UndefinedError

from app.api import contract_templates, user_email_templates

_ATTACKS = [
    "{{ 'a' * 10**9 }}",
    "{{ 'a' * 1000000000 }}",
    "{% set s = 'x' * 100000 %}{{ ([s] * 100000) | join('') }}",
    "{% set s = 'x' * 100000 %}{{ s ~ s ~ s ~ s ~ s ~ s }}",
    "{% set s = 'x' * 100000 %}{{ s | replace('x', s) }}",
    "{% set s = 'x' * 100000 %}{{ s + s + s + s + s + s }}",
    "{{ '%999999999s' % 'a' }}",
]


def test_contract_env_is_the_shared_bounded_sandbox() -> None:
    # Jedno środowisko dla maili i umów — poprawka sufitów w jednym miejscu
    # obejmuje obie powierzchnie.
    assert isinstance(
        contract_templates._jinja_env, user_email_templates._BoundedSandbox
    )


@pytest.mark.parametrize("source", _ATTACKS)
def test_huge_intermediate_results_are_refused_fast(source: str) -> None:
    started = time.monotonic()
    with pytest.raises(SecurityError):
        contract_templates.render_contract_template(source, {})
    assert time.monotonic() - started < 2.0


def test_render_stops_at_the_time_limit() -> None:
    source = (
        "{% for a in range(100000) %}{% for b in range(100000) %}"
        "{% endfor %}{% endfor %}"
    )
    started = time.monotonic()
    with pytest.raises(SecurityError):
        contract_templates.render_contract_template(source, {})
    assert time.monotonic() - started < 5.0


def test_normal_template_renders_as_before() -> None:
    source = (
        "<h1>Umowa {{ contract.id }}</h1>"
        "<p>NIP {{ client.nip }}</p>"
        "{% for s in stages %}<li>{{ s }}</li>{% endfor %}"
        "<p>{{ 'Kowalski' | upper }} {{ ['a', 'b'] | join(', ') }}</p>"
        "<p>{{ start | pl_date }}</p>"
    )
    rendered = contract_templates.render_contract_template(
        source,
        {
            "contract": {"id": 7},
            "client": {"nip": None},
            "stages": ["<b>1</b>", "2"],
            "start": date(2026, 9, 1),
        },
    )
    assert "<h1>Umowa 7</h1>" in rendered
    # `None` = pusty napis, nie "None".
    assert "<p>NIP </p>" in rendered
    # autoescape jak dotąd.
    assert "&lt;b&gt;1&lt;/b&gt;" in rendered
    assert "KOWALSKI a, b" in rendered
    assert "None" not in rendered


def test_typo_in_variable_still_fails_loudly() -> None:
    with pytest.raises(UndefinedError):
        contract_templates.render_contract_template("{{ contrakt.id }}", {})


def test_sandbox_still_blocks_class_traversal() -> None:
    with pytest.raises(SecurityError):
        contract_templates.render_contract_template("{{ ''.__class__.__mro__ }}", {})


@pytest.mark.asyncio
async def test_render_endpoint_returns_422_for_an_explosive_template(
    monkeypatch,
) -> None:
    # 3 MB wyniku — przed poprawką endpoint oddawał go jako 200.
    tpl = SimpleNamespace(
        id=1,
        name="Bomba",
        language="pl",
        content_jinja="{% set s = 'x' * 100000 %}{{ ([s] * 30) | join('') }}",
    )
    contract = SimpleNamespace(id=5, client_id=None)
    db = AsyncMock()
    db.scalar.side_effect = [tpl, contract]
    monkeypatch.setattr(
        contract_templates, "assert_contract_legal_client_access", AsyncMock()
    )
    monkeypatch.setattr(
        contract_templates, "_contract_vars", MagicMock(return_value={})
    )

    with pytest.raises(HTTPException) as caught:
        await contract_templates.render_template_for_contract(
            template_id=1, current_user=MagicMock(), db=db, contract_id=5
        )
    assert caught.value.status_code == 422
    assert "limit" in str(caught.value.detail)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_real_b2b_templates_render_within_the_limits(lang: str) -> None:
    """Wzory umów B2B (≈36 KB) mieszczą się w limitach z zapasem."""
    from tests.test_b2b_contract_generator import TEMPLATE_DIR, _sample_context

    source = (TEMPLATE_DIR / f"umowa_b2b_{lang}.html").read_text(encoding="utf-8")
    rendered = contract_templates.render_contract_template(
        source, _sample_context(lang)
    )
    assert "42/2026" in rendered
    assert "{{" not in rendered
