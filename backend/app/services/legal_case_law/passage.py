"""Kształt pozycji źródła z kontraktu fundamentu (część A planu).

Do podmiany: po scaleniu części A ``from app.services.legal.citations import
SourcePassage`` zamiast tej lokalnej definicji (ten sam kształt pozycyjnie:
``kind``, ``ref``, ``text``, ``url``, ``label``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SourcePassage:
    kind: str  # law | contract | client | template | case
    ref: str
    text: str
    url: Optional[str]
    label: str
