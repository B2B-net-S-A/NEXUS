"""Forma obowiązków w CV: EN w czasie przeszłym, PL forma rzeczownikowa.

Decyzja Artura z 16.11.2026 po zgłoszeniu z zespołu („nie upgrade, a
upgraded”). Pomiar na stagingu: 254 z 772 angielskich CV z 45 dni miało
w jednym dokumencie „Develop…” i „Developed…”, a 229 z 603 polskich mieszało
„Wdrażanie…” z „Wdrażała…”. Reguła musi stać w każdym prompcie, który pisze
obowiązki: domyślnej ścieżce `legacy_v7`, przebudowanej `v10` i redakcji
z faktów, w każdym trybie treści i w CV anonimowym.
"""

import pytest

from app.services.cv_generator_b2b.editorial_prompt import MODES, editorial_prompt
from app.services.cv_generator_b2b.legacy_v7.prompts import (
    _CONTENT_MODE_ADDENDA as LEGACY_MODES,
)
from app.services.cv_generator_b2b.legacy_v7.prompts import (
    get_prompt as legacy_prompt,
)
from app.services.cv_generator_b2b.prompts import (
    _CONTENT_MODE_ADDENDA as REBUILT_MODES,
)
from app.services.cv_generator_b2b.prompts import get_prompt as rebuilt_prompt

EN_RULE = "FORM OF RESPONSIBILITIES"
PL_RULE = "FORMA OBOWIĄZKÓW"


@pytest.mark.parametrize("blind", [False, True])
@pytest.mark.parametrize(
    ("build", "modes"),
    [(legacy_prompt, LEGACY_MODES), (rebuilt_prompt, REBUILT_MODES)],
    ids=["legacy_v7", "v10"],
)
def test_every_extraction_prompt_fixes_the_responsibility_form(build, modes, blind):
    for mode in modes:
        en = build("en", blind, mode)
        pl = build("pl", blind, mode)
        assert EN_RULE in en and "simple past" in en
        assert PL_RULE in pl and "Wdrażanie" in pl
        # Każdy język dostaje swoją regułę, nie obie naraz.
        assert PL_RULE not in en
        assert EN_RULE not in pl


@pytest.mark.parametrize("mode", list(MODES))
def test_editorial_prompt_fixes_the_responsibility_form(mode):
    en = editorial_prompt("en", mode)
    pl = editorial_prompt("pl", mode)
    assert EN_RULE in en and "simple past" in en
    assert PL_RULE in pl and "Wdrażanie" in pl
    assert PL_RULE not in en
    assert EN_RULE not in pl


def test_rule_changes_only_the_form_not_the_facts():
    for prompt in (
        legacy_prompt("en", False, "basic"),
        rebuilt_prompt("en", False, "basic"),
        editorial_prompt("en", "basic"),
    ):
        assert "including the current one" in prompt
        assert "Change ONLY the grammatical form" in prompt
    for prompt in (
        legacy_prompt("pl", False, "basic"),
        rebuilt_prompt("pl", False, "basic"),
        editorial_prompt("pl", "basic"),
    ):
        assert "także obecnej" in prompt
        assert "WYŁĄCZNIE formę gramatyczną" in prompt
