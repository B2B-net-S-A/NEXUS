"""Filtr listy kandydatów „Dodany na etap” po kolumnach Tablicy (19.10.2026).

Rekruter pyta o etap tak, jak go widzi na Tablicy rekrutacji: „QC CV”,
„Zweryfikowany”, „CV wysłane”. Kod etapu (`candidate_stages.stage`) tego nie
mówi — „QC CV” ma kod `interview`, tak samo jak zwykła rozmowa techniczna
z szablonu Traffita, a „Wysłać do Cpro” ma kod `screening`. Kolumnę daje
NAZWA etapu szablonu (`pipeline_stage_defs`) razem z kodem wiersza — reguła
`board_column_for`, ta sama co na Tablicy, w blokadzie 12 h i statystykach.

Nazwa jest w Pythonie, więc tu liczymy dla każdego etapu szablonu, które
kody wiersza dają wybraną kolumnę, a SQL dostaje gotowe listy:
`stage_def_id IN (…)` (z kodami, gdy etap szablonu sam nie rozstrzyga) LUB
`stage_def_id IS NULL AND stage IN (…)` dla wierszy bez etapu szablonu.
Wzór: `insights_stage_breakdown` (mapa `stage_def_id → klucz` + reguła kodu).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import PipelineStage
from app.services.board_stage_badges import BOARD_COLUMN_ORDER, board_column_for

# Kolumny Tablicy + pasek zamkniętych — klucze `BoardColumnKey` we froncie.
STAGE_COLUMNS: tuple[str, ...] = (*BOARD_COLUMN_ORDER, "closed")

_ALL_CODES: tuple[str, ...] = tuple(stage.value for stage in PipelineStage)


@dataclass(frozen=True)
class StageDefFacts:
    """To z etapu szablonu, co czyta `board_column_for`."""

    id: int
    name: Optional[str]
    category: Optional[str] = None
    terminal_type: Optional[str] = None


@dataclass(frozen=True)
class StageColumnRule:
    """Warunek „wiersz etapu leży w jednej z kolumn” w postaci list dla SQL.

    * ``def_groups`` — pary (etapy szablonu, kody wiersza): wiersz na jednym
      z tych etapów pasuje, gdy jego kod jest na liście; ``None`` = każdy kod
      (etap szablonu sam rozstrzyga kolumnę, np. „QC CV”).
    * ``null_def_codes`` — kody wierszy bez etapu szablonu (stare wiersze,
      import bez szablonu): kolumna z samego kodu.
    """

    def_groups: tuple[tuple[tuple[int, ...], Optional[tuple[str, ...]]], ...]
    null_def_codes: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.def_groups and not self.null_def_codes


def _value(raw: Any) -> Optional[str]:
    return getattr(raw, "value", raw)


def row_column(
    name: Optional[str],
    stage: Any,
    *,
    category: Any = None,
    terminal_type: Any = None,
) -> str:
    """Kolumna Tablicy wiersza etapu — `board_column_for` z wartościami enumów."""

    return board_column_for(
        name,
        _value(stage),
        category=_value(category),
        terminal_type=_value(terminal_type),
    )


def column_rule(
    columns: Iterable[str], stage_defs: Sequence[StageDefFacts]
) -> StageColumnRule:
    """Zamienia kolumny Tablicy na etapy szablonu i kody wiersza.

    Dla każdego etapu szablonu sprawdzamy wszystkie kody wiersza tą samą
    regułą co Tablica. Etapy o tym samym zbiorze pasujących kodów trafiają do
    jednej grupy, więc SQL ma kilka warunków, a nie jeden na etap.
    """

    wanted = {c for c in columns if c in STAGE_COLUMNS}
    if not wanted:
        return StageColumnRule(def_groups=(), null_def_codes=())
    groups: dict[Optional[tuple[str, ...]], list[int]] = defaultdict(list)
    for sd in stage_defs:
        codes = tuple(
            code
            for code in _ALL_CODES
            if row_column(
                sd.name,
                code,
                category=sd.category,
                terminal_type=sd.terminal_type,
            )
            in wanted
        )
        if not codes:
            continue
        groups[None if codes == _ALL_CODES else codes].append(sd.id)
    null_def_codes = tuple(
        code for code in _ALL_CODES if row_column(None, code) in wanted
    )
    # Kolejność stała (najpierw „każdy kod”), żeby SQL i testy były powtarzalne.
    ordered = sorted(groups.items(), key=lambda item: (item[0] is not None, item[0]))
    return StageColumnRule(
        def_groups=tuple((tuple(sorted(ids)), codes) for codes, ids in ordered),
        null_def_codes=null_def_codes,
    )


def column_clause(rule: StageColumnRule, stage_def_col: Any, stage_col: Any) -> Any:
    """Warunek SQL na wierszu `candidate_stages` (albo podzapytaniu z jego kolumnami)."""

    parts: list[Any] = []
    for def_ids, codes in rule.def_groups:
        on_def = stage_def_col.in_(def_ids)
        if codes is None:
            parts.append(on_def)
        else:
            parts.append(and_(on_def, stage_col.in_([PipelineStage(c) for c in codes])))
    if rule.null_def_codes:
        parts.append(
            and_(
                stage_def_col.is_(None),
                stage_col.in_([PipelineStage(c) for c in rule.null_def_codes]),
            )
        )
    if not parts:
        return false()
    return or_(*parts)


async def load_stage_defs(db: AsyncSession) -> list[StageDefFacts]:
    rows = (
        await db.execute(
            select(
                PipelineStageDef.id,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
        )
    ).all()
    return [
        StageDefFacts(
            id=int(def_id),
            name=name,
            category=_value(category),
            terminal_type=_value(terminal_type),
        )
        for def_id, name, category, terminal_type in rows
    ]


async def load_column_rule(
    db: AsyncSession, columns: Optional[Sequence[str]]
) -> Optional[StageColumnRule]:
    """Reguła dla wybranych kolumn albo `None`, gdy filtr kolumn nie jest ustawiony."""

    if not columns:
        return None
    return column_rule(columns, await load_stage_defs(db))
