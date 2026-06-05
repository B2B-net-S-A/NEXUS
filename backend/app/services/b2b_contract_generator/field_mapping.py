"""Budowa kontekstu docxtpl dla umowy B2B.

Reużywa `_contract_vars` (ta sama przestrzeń nazw co szablony HTML), więc jeden
zestaw danych zasila DOCX i HTML. Zakres usług renderuje się w DOCX przez
docxtpl paragraph-loop nad `b2b.scope_items` — bez dodatkowych kluczy.
"""

from __future__ import annotations

from app.api.contract_templates import _contract_vars
from app.models.contract import Contract


def build_docx_context(contract: Contract) -> dict:
    return _contract_vars(contract)
