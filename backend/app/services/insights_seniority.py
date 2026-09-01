"""Ścieżka rozwoju (decyzja D6): poziom seniority liczony z placementów.

Zastępuje `dr_user_seniority` — jedyne miejsce, w którym `seniority_level`
w ogóle istniał. Tamta tabela ma martwego writera (409 za
`DYNAREPORTER_MODE=read_only`), a jej czytelnik ukrywa każdego bez
zaseedowanego wiersza (`dynareporter_rekrutacja.py:1193-1196`), więc ekran
kadrowy pokazywał podzbiór zespołu jako całość.

Cztery decyzje, które trzymają ten moduł uczciwym:

1. **LICZONE PRZY ODCZYCIE, NIE PRZECHOWYWANE.** Oryginał DynaReportera
   wykonywał podczas obsługi zwykłego GET-a do sześciu różnych `UPDATE users
   SET …` (`InfraReporter/server/src/routes/kpi.ts:4729-4869`) — odczyt
   mutował stan, więc kolejność wywołań zmieniała wynik, a odtworzenie
   historii było niemożliwe. Przechowywanie poziomu wymagałoby z kolei
   zadania w tle, tabeli i dziennika tylko po to, żeby poziom nie rozjechał
   się po backfillu atrybucji. Poziom jest czystą funkcją osi czasu
   placementów, więc liczymy go per żądanie.

   **Konsekwencja, której nie zamiatam:** poziom zmienia się wtedy, gdy
   zmienia się HISTORIA ATRYBUCJI — import Traffita przypisujący zaległe
   `hired` innej osobie przesuwa poziom bez żadnego zdarzenia „dziś".
   Odpowiedź niesie `total_placements` i `first_placement_month`, żeby dało
   się zobaczyć, na czym poziom stoi.

2. **BEZ DEGRADACJI.** Poziom raz osiągnięty zostaje: sprawdzamy, czy
   JAKIEKOLWIEK okno w całej historii spełniło regułę, nie czy spełnia ją
   okno bieżące. Okno służy do AWANSU, nie do cofania. Degradacja samym
   upływem czasu — bez żadnego zdarzenia po stronie osoby — jest nie do
   wytłumaczenia komuś, kogo dotyczy: poziom to stwierdzenie o tym, co ktoś
   osiągnął, a nie o tym, co robił w ostatnim kwartale. Sygnał „przestał
   dowozić" żyje w liczniku bieżącego okna, który spada do zera i jest
   widoczny obok.

3. **Konta-widma odcina `users.is_active IS TRUE`.** Import Traffita zakłada
   niedopasowanych operatorów jako konta z `is_active=False`
   (`app/services/traffit/importer.py:1427`) i przypisuje im historyczny
   ruch. Bez tego filtra reguła „N placementów w oknie" awansowałaby konta,
   za którymi nie stoi żaden pracownik, i wypisywała je z imienia i nazwiska
   obok realnego zespołu. To był bloker decyzji D6 — NIE zdejmuj tego filtra
   jako „zbędnego". Placementy takich kont nie znikają po cichu: wychodzą
   w kopercie jako `outside_pool_placements`.

4. **Placement = D2**, czyli PIERWSZE `hired` dla pary (kandydat, oferta).
   Bierzemy je z widoku `analytics_first_milestones`, który deduplikuje
   `ROW_NUMBER() OVER (PARTITION BY candidate_id, job_id, stage ORDER BY
   moved_at, id)` (migracja 0184), więc dwa wiersze `hired` dla tej samej
   pary — a import Traffita dopisuje wiersz na każde zdarzenie — liczą się
   raz. NIGDY nie liczymy surowych wierszy `candidate_stages`.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.insights_scoring_config import get_scoring_config

logger = logging.getLogger(__name__)

# Pula ścieżki rozwoju. Świadomie WĘŻSZA niż `_OPERATIONAL_ROLES`
# z `kpi_panel.py:44-49` — tamta wciąga `delivery_lead`, który nie prowadzi
# procesu rekrutacyjnego i którego placementy znaczą co innego.
#
# Różnica wobec `competitions.py:254-257`: tam predykat czyta OBA pola
# (`role` ORAZ tablicę `roles`), tutaj tylko `role`. To jest wybór, nie
# przeoczenie — ścieżka rozwoju opisuje główną rolę osoby, a nie każdą
# personę, którą ktoś dorabia. Osoba z `role='delivery_lead'` i `recruiter`
# w `roles` nie jest juniorem na ścieżce rekrutera.
SENIORITY_PATH_ROLES: tuple[str, ...] = ("sourcer", "tac", "recruiter")

LEVEL_JUNIOR = "junior"
LEVEL_SENIOR = "senior"
LEVEL_EXPERT = "expert"

# Kolejność ścieżki — używana do wyznaczenia „następnego poziomu".
LEVEL_ORDER: tuple[str, ...] = (LEVEL_JUNIOR, LEVEL_SENIOR, LEVEL_EXPERT)

# Klucze w `insights_scoring_config`. Defaulty w kodzie, jak w
# `kpi_panel.py:54-56` — brak wiersza w konfiguracji nie może oznaczać
# „próg zero", bo próg zero NIE awansowałby nikogo (patrz `_rule_met`),
# czyli ścieżka rozwoju cicho przestałaby działać.
#
# Te wartości są LUSTREM `SCORING_DEFAULTS` z `insights_scoring_config`.
# Rozjazdu pilnuje `test_defaults_mirror_the_scoring_config_source_of_truth` —
# dwa różne komplety domyślnych progów znaczyłyby, że „nigdy nic nie zapisano"
# i „przywróć domyślne" dają dwa różne poziomy tym samym ludziom.
CONFIG_KEY_SENIOR_PLACEMENTS = "seniority_senior_placements"
CONFIG_KEY_SENIOR_WINDOW = "seniority_senior_window_months"
CONFIG_KEY_EXPERT_PLACEMENTS = "seniority_expert_placements"
CONFIG_KEY_EXPERT_WINDOW = "seniority_expert_window_months"

DEFAULT_THRESHOLDS: dict[str, int] = {
    CONFIG_KEY_SENIOR_PLACEMENTS: 6,
    CONFIG_KEY_SENIOR_WINDOW: 6,
    CONFIG_KEY_EXPERT_PLACEMENTS: 12,
    CONFIG_KEY_EXPERT_WINDOW: 12,
}


@dataclass(frozen=True)
class SeniorityThresholds:
    """Progi awansu — jedno okno kroczące na poziom."""

    senior_placements: int
    senior_window_months: int
    expert_placements: int
    expert_window_months: int

    def as_payload(self) -> dict:
        return {
            "senior_placements": self.senior_placements,
            "senior_window_months": self.senior_window_months,
            "expert_placements": self.expert_placements,
            "expert_window_months": self.expert_window_months,
        }

    @property
    def cache_suffix(self) -> str:
        """Progi WCHODZĄ w klucz cache'u.

        Bez tego zmiana progu przez admina byłaby niewidoczna przez cały TTL,
        a poziom jest z progu WYLICZANY — czyli strona pokazywałaby awanse
        według reguły, która już nie obowiązuje, pod nagłówkiem z nową regułą.
        """
        return (
            f"{self.senior_placements}-{self.senior_window_months}"
            f"-{self.expert_placements}-{self.expert_window_months}"
        )


@dataclass(frozen=True)
class SeniorityRow:
    user_id: int
    name: str
    role: str
    level: str
    total_placements: int
    # 'YYYY-MM' pierwszego atrybuowanego placementu albo None. Bez tego wiersz
    # osoby, której historia jeszcze nie trafiła do NEXUSA, wygląda identycznie
    # jak wiersz osoby zatrudnionej wczoraj.
    first_placement_month: str | None
    placements_in_senior_window: int
    placements_in_expert_window: int
    placements_to_next_level: int | None
    progress_pct: float | None

    def as_payload(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "role": self.role,
            "level": self.level,
            "total_placements": self.total_placements,
            "first_placement_month": self.first_placement_month,
            "placements_in_senior_window": self.placements_in_senior_window,
            "placements_in_expert_window": self.placements_in_expert_window,
            "placements_to_next_level": self.placements_to_next_level,
            "progress_pct": self.progress_pct,
        }


@dataclass(frozen=True)
class SeniorityWindow:
    """Bieżące okno kroczące — miesiące, z których liczą się liczniki."""

    months: int
    start_month: str | None
    end_month: str

    def as_payload(self) -> dict:
        return {
            "months": self.months,
            "start_month": self.start_month,
            "end_month": self.end_month,
        }


@dataclass(frozen=True)
class SeniorityResult:
    as_of: date
    thresholds: SeniorityThresholds
    senior_window: SeniorityWindow
    expert_window: SeniorityWindow
    rows: tuple[SeniorityRow, ...]
    # Placementy, których NIE MA w żadnym wierszu tabeli. Muszą być
    # wyrenderowane obok — inaczej suma kolumny nie zgadza się z lejkiem
    # i tabela wygląda na zepsutą zamiast na niekompletną (D1).
    unattributed_placements: int
    outside_pool_placements: int


# ── Arytmetyka okien ─────────────────────────────────────────────────────────
#
# Kubełek to MIESIĄC KALENDARZOWY w Europe/Warsaw, a okno to N kolejnych
# miesięcy. Indeksujemy miesiące liczbą całkowitą, żeby „okno N miesięcy
# kończące się w M" było odejmowaniem, a nie arytmetyką dat z przypadkami
# brzegowymi na przełomie roku.


def _month_index(value: date) -> int:
    return value.year * 12 + (value.month - 1)


def _month_label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _window_sum(counts: dict[int, int], end_month: int, window_months: int) -> int:
    """Placementy w oknie ``window_months`` miesięcy kończącym się w ``end_month``."""
    if window_months <= 0:
        return 0
    start_month = end_month - window_months + 1
    return sum(n for m, n in counts.items() if start_month <= m <= end_month)


def _best_window_sum(counts: dict[int, int], window_months: int) -> int:
    """Najlepsze okno w CAŁEJ historii — to ono decyduje o awansie.

    Wystarczy sprawdzić okna kończące się w miesiącach, w których jakiś
    placement w ogóle był: przesunięcie końca okna na pusty miesiąc może
    wyłącznie wypchnąć z okna wcześniejszy miesiąc i nie dokłada niczego, więc
    maksimum zawsze wypada na miesiącu obecnym w danych. Dzięki temu nie
    trzeba iterować po każdym miesiącu osi czasu.
    """
    if window_months <= 0 or not counts:
        return 0
    return max(_window_sum(counts, m, window_months) for m in counts)


def _rule_met(counts: dict[int, int], required: int, window_months: int) -> bool:
    """Czy reguła awansu została KIEDYKOLWIEK spełniona (zapadka, bez degradacji)."""
    if required <= 0 or window_months <= 0:
        # Próg zero to konfiguracja BEZ reguły, a nie reguła spełniona przez
        # każdego. Gdyby zwracać tu True, pusty wiersz konfiguracji awansowałby
        # cały zespół — łącznie z osobami bez ani jednego placementu.
        return False
    return _best_window_sum(counts, window_months) >= required


def _progress_pct(current: int, required: int) -> float | None:
    """Postęp do progu albo ``None``, gdy progu nie ma.

    NIE zwraca 0.0 przy zerowym progu — „nie ma reguły" to co innego niż
    „reguła jest i jesteś na zerze". Świadomie NIE przycinamy też do 100%:
    osoba, która przekroczyła próg dwukrotnie, ma to widzieć.
    """
    if required <= 0:
        return None
    return round(current / required * 100, 1)


def _resolve_level(counts: dict[int, int], thresholds: SeniorityThresholds) -> str:
    """Najwyższy poziom, którego reguła została kiedykolwiek spełniona.

    Poziom eksperta NIE wymaga wcześniejszego przejścia przez seniora: obie
    reguły czytamy z konfiguracji niezależnie, więc źle ustawiony próg seniora
    (np. absurdalnie wysoki) nie może po cichu zablokować eksperta komuś, kto
    jego regułę spełnił.
    """
    if _rule_met(counts, thresholds.expert_placements, thresholds.expert_window_months):
        return LEVEL_EXPERT
    if _rule_met(counts, thresholds.senior_placements, thresholds.senior_window_months):
        return LEVEL_SENIOR
    return LEVEL_JUNIOR


# ── Konfiguracja ─────────────────────────────────────────────────────────────


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # Wiersz konfiguracji z nieliczbową wartością nie może wywalić całej
        # sekcji — wracamy na default i zostawiamy ślad w logu.
        logger.warning(
            "insights_seniority: nieliczbowy próg w insights_scoring_config (%r)",
            value,
        )
        return fallback


async def load_thresholds(db: AsyncSession) -> SeniorityThresholds:
    """Progi z `insights_scoring_config`, z defaultami w kodzie.

    Brakujący klucz spada na default — świeża instalacja bez zaseedowanej
    konfiguracji ma mieć DZIAŁAJĄCĄ regułę, a nie regułę zerową (patrz
    `_rule_met`).
    """
    config = await get_scoring_config(db)
    return SeniorityThresholds(
        senior_placements=_as_int(
            config.get(CONFIG_KEY_SENIOR_PLACEMENTS),
            DEFAULT_THRESHOLDS[CONFIG_KEY_SENIOR_PLACEMENTS],
        ),
        senior_window_months=_as_int(
            config.get(CONFIG_KEY_SENIOR_WINDOW),
            DEFAULT_THRESHOLDS[CONFIG_KEY_SENIOR_WINDOW],
        ),
        expert_placements=_as_int(
            config.get(CONFIG_KEY_EXPERT_PLACEMENTS),
            DEFAULT_THRESHOLDS[CONFIG_KEY_EXPERT_PLACEMENTS],
        ),
        expert_window_months=_as_int(
            config.get(CONFIG_KEY_EXPERT_WINDOW),
            DEFAULT_THRESHOLDS[CONFIG_KEY_EXPERT_WINDOW],
        ),
    )


# ── Zapytania ────────────────────────────────────────────────────────────────

# Pula: `role` (nie `roles`) + `is_active`. Filtr aktywności jest tu warunkiem
# POPRAWNOŚCI, nie kosmetyką — patrz punkt 3 docstringa modułu.
_POPULATION_SQL = """
    SELECT u.id AS user_id, u.name AS name, u.role::text AS role
    FROM users u
    WHERE u.role::text = ANY(:roles)
      AND u.is_active IS TRUE
"""

# Placementy per (osoba, miesiąc). Bez JOIN-a do `users` — potrzebujemy też
# wierszy przypisanych do kont SPOZA puli, żeby móc je policzyć w kopercie
# zamiast po cichu zgubić.
_PLACEMENTS_SQL = """
    SELECT fm.first_moved_by AS user_id,
           date_trunc(
               'month', fm.first_reached_at AT TIME ZONE 'Europe/Warsaw'
           )::date AS month,
           count(*) AS cnt
    FROM analytics_first_milestones fm
    WHERE fm.stage = 'hired'
      AND (fm.first_reached_at AT TIME ZONE 'Europe/Warsaw')::date <= :as_of
    GROUP BY 1, 2
"""


async def compute_seniority(
    db: AsyncSession, *, as_of: date, thresholds: SeniorityThresholds
) -> SeniorityResult:
    """Ścieżka rozwoju całej puli na dzień ``as_of``.

    ``as_of`` odcina placementy PÓŹNIEJSZE — dzięki temu odpowiedź jest
    deterministyczna i daje się odtworzyć („jak to wyglądało na koniec
    kwartału"), a testy nie zależą od dnia uruchomienia.
    """
    population = (
        (await db.execute(text(_POPULATION_SQL), {"roles": list(SENIORITY_PATH_ROLES)}))
        .mappings()
        .all()
    )
    pool = {int(r["user_id"]): (r["name"], str(r["role"] or "")) for r in population}

    placement_rows = (
        (await db.execute(text(_PLACEMENTS_SQL), {"as_of": as_of})).mappings().all()
    )

    per_user: dict[int, dict[int, int]] = {}
    unattributed = 0
    outside_pool = 0
    for row in placement_rows:
        cnt = int(row["cnt"])
        raw_user = row["user_id"]
        if raw_user is None:
            # Operator z importu bez odpowiednika w NEXUSIE. NIE wolno go
            # wyciąć po cichu — bez tej liczby suma tabeli nie zgadza się
            # z lejkiem i tabela czyta się jak błąd, a nie jak niekompletność.
            unattributed += cnt
            continue
        user_id = int(raw_user)
        if user_id not in pool:
            # Inna rola albo konto-widmo (`is_active=false`) z importu.
            outside_pool += cnt
            continue
        per_user.setdefault(user_id, {})[_month_index(row["month"])] = cnt

    current_month = _month_index(as_of)
    senior_window = SeniorityWindow(
        months=thresholds.senior_window_months,
        start_month=_month_label(current_month - thresholds.senior_window_months + 1)
        if thresholds.senior_window_months > 0
        else None,
        end_month=_month_label(current_month),
    )
    expert_window = SeniorityWindow(
        months=thresholds.expert_window_months,
        start_month=_month_label(current_month - thresholds.expert_window_months + 1)
        if thresholds.expert_window_months > 0
        else None,
        end_month=_month_label(current_month),
    )

    rows: list[SeniorityRow] = []
    for user_id, (name, role) in pool.items():
        counts = per_user.get(user_id, {})
        level = _resolve_level(counts, thresholds)
        in_senior = _window_sum(counts, current_month, thresholds.senior_window_months)
        in_expert = _window_sum(counts, current_month, thresholds.expert_window_months)

        if level == LEVEL_EXPERT:
            # Nie ma następnego poziomu — „ile brakuje" nie ma odpowiedzi,
            # a 0 czytałoby się jako „awans tuż-tuż".
            to_next: int | None = None
            progress: float | None = None
        elif level == LEVEL_SENIOR:
            to_next = (
                max(0, thresholds.expert_placements - in_expert)
                if thresholds.expert_placements > 0
                else None
            )
            progress = _progress_pct(in_expert, thresholds.expert_placements)
        else:
            to_next = (
                max(0, thresholds.senior_placements - in_senior)
                if thresholds.senior_placements > 0
                else None
            )
            progress = _progress_pct(in_senior, thresholds.senior_placements)

        rows.append(
            SeniorityRow(
                user_id=user_id,
                name=name,
                role=role,
                level=level,
                total_placements=sum(counts.values()),
                first_placement_month=_month_label(min(counts)) if counts else None,
                placements_in_senior_window=in_senior,
                placements_in_expert_window=in_expert,
                placements_to_next_level=to_next,
                progress_pct=progress,
            )
        )

    # Kolejność: najwyższy poziom, potem dorobek, potem nazwisko. Stabilna,
    # żeby dwa odczyty tych samych danych dały tę samą listę.
    rows.sort(
        key=lambda r: (
            -LEVEL_ORDER.index(r.level),
            -r.total_placements,
            r.name.casefold(),
        )
    )

    return SeniorityResult(
        as_of=as_of,
        thresholds=thresholds,
        senior_window=senior_window,
        expert_window=expert_window,
        rows=tuple(rows),
        unattributed_placements=unattributed,
        outside_pool_placements=outside_pool,
    )
