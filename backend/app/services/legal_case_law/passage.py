"""Kształt pozycji źródła z kontraktu fundamentu (część A planu).

Do podmiany: po scaleniu części A import ``SourcePassage`` z
``app.services.legal`` zamiast tej lokalnej definicji (ten sam kształt:
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
