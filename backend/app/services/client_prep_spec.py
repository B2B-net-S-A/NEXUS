"""„Specyfika na prep” w karcie klienta (F2, decyzje Artura z 24.11.2026).

Osiem stałych pól, które rekruter omawia z kandydatem po fundamentach
(Ustawienia → Ocena prepów → „Przygotowanie”). Każde pole to lista krótkich
punktów; puste pole karta pokazuje jako „zapytaj DL-a przed prepem”. Pytań,
które padają u klienta, tu nie ma — są w banku pytań z rozmów.

Prowadzi Delivery Lead w tym samym formularzu co resztę karty (zapis =
obowiązuje, wersja i historia jak dla innych pól). Wyjątki od warunków stop
z fundamentów (np. umowa o pracę w Tauronie) stoją w polu „Forma współpracy”.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field, StringConstraints

PREP_SPEC_FIELDS: tuple[tuple[str, str], ...] = (
    ("work_mode", "Tryb pracy i biuro"),
    ("language", "Język rozmowy"),
    ("interview", "Przebieg rozmowy"),
    ("focus", "Na co zwracają uwagę"),
    ("questions", "Typ pytań"),
    ("rejections", "Za co klient odrzuca"),
    ("highlights", "Co wyróżnia klienta"),
    ("cooperation", "Forma współpracy"),
)
PREP_SPEC_KEYS: tuple[str, ...] = tuple(key for key, _ in PREP_SPEC_FIELDS)
MAX_LINES = 12
MAX_LINE = 300

SpecLine = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_LINE)]
SpecLines = Annotated[list[SpecLine], Field(default_factory=list, max_length=MAX_LINES)]


class PrepSpec(BaseModel):
    work_mode: SpecLines
    language: SpecLines
    interview: SpecLines
    focus: SpecLines
    questions: SpecLines
    rejections: SpecLines
    highlights: SpecLines
    cooperation: SpecLines


def normalize_prep_spec(spec: Optional[Any]) -> Optional[dict[str, list[str]]]:
    """Wszystkie osiem kluczy, bez pustych linii; ``None``, gdy nic nie zostało."""

    if spec is None:
        return None
    model = spec if isinstance(spec, PrepSpec) else PrepSpec.model_validate(spec)
    out = {
        key: [line for line in getattr(model, key) if line] for key in PREP_SPEC_KEYS
    }
    return out if any(out.values()) else None
