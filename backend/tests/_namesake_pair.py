"""Fikcyjna para imienników dla testów.

Prawdziwa para stoi w kodzie wyłącznie jako skrót (repo i logi Actions są
publiczne), więc testy podmieniają ``NAMESAKE_NAME_DIGESTS`` na skrót osoby
zmyślonej. Reguła i kod pod testem zostają te same.
"""

from __future__ import annotations

import pytest

from app.services import contractor_identity


@pytest.fixture
def fictional_namesakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """„Józef Przykładowy” to w tym teście dwie różne osoby."""
    digest = contractor_identity.name_pair_digest("jozef", "przykladowy")
    monkeypatch.setattr(
        contractor_identity, "NAMESAKE_NAME_DIGESTS", frozenset({digest})
    )
