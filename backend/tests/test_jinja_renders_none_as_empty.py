"""Puste pole nie może trafić do dokumentu jako napis „None".

``SandboxedEnvironment`` z ``StrictUndefined`` broni WYŁĄCZNIE przed literówką
w nazwie zmiennej. Wartość, która istnieje i jest ``None``, Jinja renderuje
jako czteroznakowy napis „None" — a kontekst obu rendererów celowo zwraca
``None`` dla pól nieuzupełnionych.

Skutek był w dwóch miejscach, oba wychodzące poza system:

* umowa: ``{{ client.nip }}`` dawało „NIP None" w dokumencie prawnym, a
  ``GET /api/contracts/{id}/draft`` renderuje RAZ i ZAPISUJE wynik do
  ``draft_content_html`` — więc uzupełnienie NIP-u później już nie naprawia
  zapisanego szkicu. Klientów bez NIP-u jest 11 505 z 11 899;
* mail: ``_candidate_ctx`` zwraca ``None`` dla ``full_name``, ``phone``,
  ``location``, ``linkedin``, a odbiorcą jest KANDYDAT.

``finalize`` musi zamieniać wyłącznie ``None``. ``False`` i ``0`` to
prawidłowe wartości, nie brak danych — zamiana ich na pusty napis byłaby
drugim błędem tej samej rodziny, tylko w drugą stronę.
"""

import pytest

from app.api.contract_templates import _jinja_env as contract_env
from app.api.user_email_templates import _jinja_env as email_env

ENVS = [
    pytest.param(contract_env, id="contract_templates"),
    pytest.param(email_env, id="user_email_templates"),
]


@pytest.mark.parametrize("env", ENVS)
def test_none_renders_as_empty_string(env):
    out = env.from_string("NIP {{ client.nip }}|").render(client={"nip": None})
    assert out == "NIP |", (
        f'puste pole trafiło do dokumentu jako {out!r} — literalne „None" '
        "zostaje utrwalone w zapisanym szkicu i w wysłanym mailu"
    )


@pytest.mark.parametrize("env", ENVS)
def test_false_and_zero_survive_untouched(env):
    """Wartości fałszywe, ale PRAWIDŁOWE, muszą przejść bez zmiany."""
    out = env.from_string("[{{ a }}][{{ b }}][{{ c }}]").render(a=False, b=0, c="")
    assert out == "[False][0][]", (
        f"finalize zjadł prawidłową wartość: {out!r} — 0 i False to dane, "
        "nie brak danych"
    )


@pytest.mark.parametrize("env", ENVS)
def test_real_values_render_normally(env):
    out = env.from_string("NIP {{ client.nip }}").render(client={"nip": "1234567890"})
    assert out == "NIP 1234567890"


def test_contract_env_still_rejects_a_typo_in_the_variable_name():
    """``finalize`` NIE MOŻE osłabić ``StrictUndefined``.

    Rozróżnienie „pole puste" (renderuj nic) od „pola nie ma" (błąd autora
    szablonu) jest tym, co pozwala złapać literówkę zanim trafi do umowy.
    """
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        contract_env.from_string("{{ nie_ma_takiej_zmiennej }}").render()
