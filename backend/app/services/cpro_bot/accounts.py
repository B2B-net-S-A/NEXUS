"""Tożsamość kont portalu, odrębna od właściciela rekrutacji w NEXUSIE."""

from typing import Literal

CproAccountName = Literal["Igor", "Marcin"]
IGOR_HINT = "Nordea Cpro – Igor"
MARCIN_HINT = "Nordea Cpro – Marcin"
ACCOUNT_NAMES: dict[str, CproAccountName] = {IGOR_HINT: "Igor", MARCIN_HINT: "Marcin"}
