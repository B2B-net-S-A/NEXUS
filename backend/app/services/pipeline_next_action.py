"""„Następna akcja" karty pipeline'u i to, PO CZYJEJ STRONIE jest ruch.

Lustro dwóch modułów frontu:

* ``frontend/src/lib/pipeline-next-action.ts`` — ``nextActionFor`` (etykieta,
  ton, rodzaj, właściciel ruchu),
* ``frontend/src/lib/pipeline-flow.ts`` — ``groupKeyForColumn`` i pozycyjne
  korekty ``groupKanbanColumns`` (+ ``isContractStage`` z
  ``job-flow-stages.ts`` i ``terminalOf`` z ``kanban-terminal.ts``).

Reguła żyje w dwóch językach, więc pilnuje jej JEDNA tabela przypadków:
``frontend/src/lib/__fixtures__/next-action-cases.json`` czytana przez
``tests/test_next_action_parity.py`` i przez test frontu. Zmiana reguły =
zmiana tamtego pliku i OBU implementacji.

Czysty moduł: bez bazy, bez sieci, bez importów z ``app.api``. Wejściem są
fakty o kolumnie (legacy ``stage``, ``category``, ``terminal_type``, ``name``)
— dokładnie te, które niesie ``template_column_meta`` — i trzy fakty o karcie.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Optional, Sequence

# Powyżej tylu dni na etapie karta jest „zaległa".
STUCK_DAYS = 7
# Tyle dni czekamy na drugą stronę (klienta / kandydata), zanim ruch wraca do
# rekrutera.
NUDGE_DAYS = 5
# Do tylu dni świeża karta wejściowa jest jeszcze „do analizy dziś".
FRESH_INTAKE_DAYS = 1

NO_NEXT_ACTION_LABEL = "Brak następnej akcji"

GroupKey = Literal[
    "posting", "intake", "screening", "verification", "client", "contract", "closed"
]
Owner = Literal["recruiter", "review", "client", "candidate", "delivery", "none"]
# Kiedy ruch jest po stronie rekrutera — BEZ wiedzy o karcie (patrz
# ``recruiter_owner_mode``): zawsze / dopiero po NUDGE_DAYS / nigdy.
OwnerMode = Literal["always", "after_nudge", "review", "never"]

GROUP_ORDER: tuple[GroupKey, ...] = (
    "posting",
    "intake",
    "screening",
    "verification",
    "client",
    "contract",
    "closed",
)

POSTING_STAGE = "posting"
SCREENING_STAGE = "screening"
VERIFIED_STAGE = "verified"
CV_SENT_STAGE = "cv_sent"

# Nazwy ręcznych etapów podpisu z szablonu „Default B2B" — nie mają legacy
# enuma, więc nazwa jest jedynym identyfikatorem (lustro `job-flow-stages.ts`).
CONTRACT_STAGE_NAMES: tuple[str, ...] = ("Umowa wysłana", "Umowa podpisana")
_CONTRACT_NAMES_NORMALIZED = frozenset(n.lower() for n in CONTRACT_STAGE_NAMES)

_LEGACY_TERMINAL_STAGES = frozenset({"hired", "rejected", "withdrawn"})

_KIND_FOR_GROUP: dict[str, str] = {
    "posting": "analysis",
    "intake": "analysis",
    "screening": "screening",
    "verification": "cv",
    "client": "client",
    "contract": "contract",
    "closed": "none",
}


def _plain(value: Any) -> Optional[str]:
    """Enum albo string → string; ``None`` zostaje ``None``."""
    if value is None:
        return None
    return str(getattr(value, "value", value))


@dataclass(frozen=True)
class StageColumn:
    """Kolumna tablicy widziana przez regułę — bez kart i bez liczby."""

    stage: str
    category: Optional[str] = None
    terminal_type: Optional[str] = None
    name: Optional[str] = None
    order: Optional[int] = None
    stage_def_id: Optional[int] = None

    @classmethod
    def from_meta(cls, meta: dict) -> "StageColumn":
        """Z ``template_column_meta`` / ``legacy_column_meta`` / JSON-a fixture."""
        return cls(
            stage=_plain(meta.get("stage")) or "new",
            category=_plain(meta.get("category")),
            terminal_type=_plain(meta.get("terminal_type")),
            name=meta.get("name"),
            order=meta.get("order"),
            stage_def_id=meta.get("stage_def_id"),
        )

    @classmethod
    def from_stage_def(cls, stage_def: Any) -> "StageColumn":
        """Z wiersza ``pipeline_stage_defs`` — to samo mapowanie co tablica.

        Etap bez ``legacy_enum_value`` raportuje ``new`` (jak
        ``template_column_meta``), więc grupę rozstrzyga pozycja w szablonie.
        """
        return cls(
            stage=_plain(getattr(stage_def, "legacy_enum_value", None)) or "new",
            category=_plain(getattr(stage_def, "category", None)),
            terminal_type=_plain(getattr(stage_def, "terminal_type", None)),
            name=getattr(stage_def, "name", None),
            order=getattr(stage_def, "order", None),
            stage_def_id=getattr(stage_def, "id", None),
        )


@dataclass(frozen=True)
class NextAction:
    label: str
    tone: str
    kind: str
    owner: str


def terminal_of(col: StageColumn) -> Optional[str]:
    """``terminal_type`` z definicji etapu, z fallbackiem na legacy ``stage``."""
    if col.terminal_type:
        return col.terminal_type
    return col.stage if col.stage in _LEGACY_TERMINAL_STAGES else None


def is_contract_stage(col: StageColumn) -> bool:
    """Etap kroku 08 „Umowa" (podpis → zatrudnienie → onboarding)."""
    if terminal_of(col) == "hired":
        return True
    if col.stage == "onboarding":
        return True
    return (col.name or "").strip().lower() in _CONTRACT_NAMES_NORMALIZED


def group_key_for_column(col: StageColumn) -> GroupKey:
    """Grupa kolumny liczona BEZ znajomości reszty tablicy."""
    # Kontrakt PRZED terminalem: „Zatrudniony" jest terminalem, ale należy do
    # „Umowa → zatrudnieni".
    if is_contract_stage(col):
        return "contract"
    if terminal_of(col) is not None or col.category == "terminal":
        return "closed"
    if col.stage == POSTING_STAGE:
        return "posting"
    if col.stage == SCREENING_STAGE:
        return "screening"
    if col.stage == VERIFIED_STAGE:
        return "verification"
    if col.stage == CV_SENT_STAGE or col.category == "external":
        return "client"
    return "intake"


def group_keys_for_columns(columns: Sequence[StageColumn]) -> list[GroupKey]:
    """Grupa KAŻDEJ kolumny, z korektami pozycyjnymi ``groupKanbanColumns``.

    Zwraca listę równoległą do ``columns`` (kolejność szablonu).
    """
    base = [group_key_for_column(c) for c in columns]
    screening_index = next(
        (i for i, c in enumerate(columns) if c.stage == SCREENING_STAGE), -1
    )
    first_client_index = next((i for i, k in enumerate(base) if k == "client"), -1)
    out: list[GroupKey] = []
    for index, key in enumerate(base):
        # Etap wewnętrzny STOJĄCY PO screeningu to weryfikacja, nie wejście.
        if key == "intake" and screening_index >= 0 and index > screening_index:
            key = "verification"
        # …a stojący między etapami klienta („Preparation Meeting") — klient.
        if (
            key == "verification"
            and first_client_index >= 0
            and index > first_client_index
        ):
            key = "client"
        out.append(key)
    return out


def _base_action(
    col: StageColumn,
    group: str,
    *,
    days: int,
    screening_done: Optional[bool],
    hm_veto: bool,
    sla_days: Optional[int],
) -> tuple[str, str, str]:
    if group == "closed":
        return ("", "normal", "none")
    if terminal_of(col) == "hired":
        return ("Przekaż do Delivery", "normal", "contract")
    if hm_veto:
        return ("Ostrzeżenie: weto HM", "gate", _KIND_FOR_GROUP.get(group, "none"))

    if group in ("posting", "intake"):
        if days <= FRESH_INTAKE_DAYS:
            return ("Analiza CV · dziś", "normal", "analysis")
        if days < STUCK_DAYS:
            return ("Umów screening", "normal", "screening")
        return (NO_NEXT_ACTION_LABEL, "due", "analysis")

    if group == "screening":
        overdue = days >= STUCK_DAYS or (sla_days is not None and days >= sla_days)
        tone = "due" if overdue else "normal"
        if screening_done is True:
            return ("Zweryfikuj i przenieś dalej", tone, "verification")
        return ("Uzupełnij arkusz screeningu", tone, "screening")

    if group == "verification":
        # Rekrutacja v5: po „Zweryfikowany" stoi „QC CV", nie klient
        # (lustro `nextActionFor`, 24.09.2026). Import leniwy: reguła nazwy
        # QC żyje w `board_stage_badges`, który ciągnie modele i polityki
        # zamówień — ten moduł ma zostać lekki przy imporcie.
        from app.services.board_stage_badges import is_qc_stage

        if is_qc_stage(col.name):
            return ("Popraw CV / wyślij", "normal", "cv")
        return ("Przygotuj CV do QC", "normal", "cv")

    if group == "client":
        if col.stage == CV_SENT_STAGE:
            return ("Umów interview / feedback klienta", "normal", "client")
        if col.stage == "client_interview":
            return ("Zbierz feedback HM", "normal", "client")
        if col.stage in ("acceptance", "negotiation"):
            return ("Reakcja kandydata na ofertę", "normal", "offer")
        return ("Feedback klienta", "normal", "client")

    if group == "contract":
        if terminal_of(col) == "hired" or col.stage == "onboarding":
            return ("Przekaż do Delivery", "normal", "contract")
        return ("Podpis umowy", "normal", "contract")

    return ("", "normal", "none")


def _owner(
    col: StageColumn, group: str, kind: str, *, days: int, hm_veto: bool
) -> Owner:
    if group == "closed" or kind == "none":
        return "none"
    if terminal_of(col) == "hired" or col.stage == "onboarding":
        return "delivery"
    if hm_veto:
        return "recruiter"
    # Stos wejściowy to przegląd, nie „wymaga ruchu" (decyzja 21.09.2026).
    if group in ("posting", "intake"):
        return "review"
    if group != "client":
        return "recruiter"
    if days >= NUDGE_DAYS:
        return "recruiter"
    return "candidate" if kind == "offer" else "client"


def next_action_for(
    col: StageColumn,
    *,
    days_in_stage: Optional[int] = None,
    screening_done: Optional[bool] = None,
    hm_veto: bool = False,
    group: Optional[str] = None,
    sla_days: Optional[int] = None,
) -> NextAction:
    """Co dalej z kartą — z faktów, które karta niesie (lustro ``nextActionFor``).

    ``group`` podaje wołający, który zna całą tablicę
    (``group_keys_for_columns``); bez niej kolumna klasyfikuje się sama, ale
    własny etap wewnętrzny PO screeningu wyjdzie wtedy jako wejściowy.
    """
    resolved = group or group_key_for_column(col)
    days = days_in_stage or 0
    label, tone, kind = _base_action(
        col,
        resolved,
        days=days,
        screening_done=screening_done,
        hm_veto=hm_veto,
        sla_days=sla_days,
    )
    return NextAction(
        label=label,
        tone=tone,
        kind=kind,
        owner=_owner(col, resolved, kind, days=days, hm_veto=hm_veto),
    )


def recruiter_owner_mode(col: StageColumn, group: str) -> OwnerMode:
    """Kiedy właścicielem ruchu na tej kolumnie jest rekruter — BEZ karty.

    Służy agregatom (licznik „wymaga ruchu" na liście rekrutacji), które nie
    ładują kart. Właściciel zależy od karty tylko w dwóch miejscach:

    * ``days_in_stage`` na etapach klienta — stąd tryb ``after_nudge``,
    * weto hiring managera — na etapie klienta PRZED upływem ``NUDGE_DAYS``
      oddaje ruch rekruterowi. Agregat świadomie to POMIJA (weto wymaga
      osobnego zapytania per rekrutacja z hiring managerem); licznik listy może
      więc być o takie karty NIŻSZY niż tablica. ``screening_done`` zmienia
      etykietę, nie właściciela.
    """
    probe = next_action_for(col, days_in_stage=0, group=group)
    if probe.owner == "recruiter":
        return "always"
    if probe.owner == "review":
        return "review"
    if probe.owner in ("client", "candidate"):
        return "after_nudge"
    return "never"


def owner_modes_for_columns(columns: Sequence[StageColumn]) -> list[OwnerMode]:
    """Tryb właściciela każdej kolumny szablonu (lista równoległa)."""
    groups = group_keys_for_columns(columns)
    return [recruiter_owner_mode(c, g) for c, g in zip(columns, groups)]


def count_recruiter_owned(
    modes: Iterable[OwnerMode], tallies: Iterable[tuple[int, int]]
) -> int:
    """Suma kart „po stronie rekrutera".

    ``tallies`` — równolegle do ``modes`` — to pary ``(wszystkie, po_nudge)``:
    liczba kart kolumny i ile z nich stoi co najmniej ``NUDGE_DAYS`` dni.
    """
    total = 0
    for mode, (all_cards, nudged) in zip(modes, tallies):
        if mode == "always":
            total += all_cards
        elif mode == "after_nudge":
            total += nudged
    return total
