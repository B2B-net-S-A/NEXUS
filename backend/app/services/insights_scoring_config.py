"""Odczyt i zapis konfigurowalnej punktacji Insights (decyzja D3).

Kontrakt tego modułu ma JEDNĄ regułę nadrzędną: **odczyt nigdy nie rzuca**.
Brakujący klucz, pusta tabela, a nawet brak tabeli (prod bywa z osieroconym
alembikiem — patrz safety-net w `entrypoint.sh`) kończą się wartościami
domyślnymi z kodu, nie wyjątkiem. Konfiguracja, która wywala raport, jest
gorsza niż konfiguracja domyślna: Liga Mistrzów licząca 150/15/5 jest
użyteczna, Liga Mistrzów zwracająca 500 nie jest.

Dlatego zapytanie idzie w SAVEPOINCIE. Sesja żądania jest współdzielona
z resztą handlera, a nieudany SELECT przerywa CAŁĄ transakcję („current
transaction is aborted") — bez savepointa brak tabeli nie degradowałby
punktacji do domyślnej, tylko wywracał każde następne zapytanie w tym samym
żądaniu. To jest dokładnie tryb awarii, przed którym broni się `/api/health/deep`
świeżą sesją per sonda.

Cache jest w PAMIĘCI PROCESU i krótki. Konsekwencja, której nie zamiatam:
przy wielu workerach zapis w jednym z nich jest widoczny w pozostałych
dopiero po wygaśnięciu TTL. Trzydzieści sekund to świadomy kompromis — waga
punktowa czytana jest przy każdym renderze Ligi, a jej zmiana jest zdarzeniem
rzadkim i nie ma wymogu natychmiastowości. Unieważnienie po zapisie działa
tylko lokalnie i to wystarcza, żeby admin ZOBACZYŁ efekt własnej zmiany
w odpowiedzi na własny PATCH.
"""

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_invalidate, cache_set
from app.models.insights_scoring_config import InsightsScoringConfig

logger = logging.getLogger(__name__)

_CACHE_KEY = "insights:scoring-config:v1"
CACHE_TTL_SECONDS = 30


class ScoringConfigError(ValueError):
    """Żądanie zapisu, którego nie da się spełnić — nieznany klucz albo zakres."""


@dataclass(frozen=True)
class ScoringField:
    """Opis jednego klucza: wartość domyślna, dopuszczalny zakres, etykieta.

    Etykiety są tutaj, a nie we froncie, bo tę samą listę czyta ekran ustawień
    i kafel „System punktowy" widoczny dla KAŻDEJ roli (D7). Dwie kopie opisu
    tego samego progu rozjeżdżają się przy pierwszej zmianie wartości.
    """

    key: str
    default: int
    minimum: int
    maximum: int
    group: str
    label: str
    unit: str


# Zakresy wprost z decyzji D3: 0..1000 dla punktów, 1..24 dla okien czasowych,
# 0..100 dla progów liczby placementów.
#
# Okno ma minimum 1, a nie 0: okno zerowe nie zawiera żadnego miesiąca, więc
# próg „N placementów w 0 miesięcy" jest niespełnialny z definicji i cicho
# wyłączałby całą ścieżkę awansu zamiast ją zaostrzyć.
#
# Próg placementów ma minimum 0, a nie 1: zero jest sensowną, jawną decyzją
# („nie wymagamy placementu do udziału w Lidze"), a jej brak zmuszałby do
# obchodzenia konfiguracji zmianą kodu.
SCORING_FIELDS: tuple[ScoringField, ...] = (
    ScoringField(
        key="league_points_placement",
        default=150,
        minimum=0,
        maximum=1000,
        group="league_points",
        label="Punkty za placement",
        unit="pkt",
    ),
    ScoringField(
        key="league_points_interview",
        default=15,
        minimum=0,
        maximum=1000,
        group="league_points",
        label="Punkty za rozmowę (stage `interview`)",
        unit="pkt",
    ),
    ScoringField(
        key="league_points_recommendation",
        default=5,
        minimum=0,
        maximum=1000,
        group="league_points",
        label="Punkty za rekomendację (stage `cv_sent`)",
        unit="pkt",
    ),
    ScoringField(
        key="league_min_placements_month1",
        default=1,
        minimum=0,
        maximum=100,
        group="league_qualification",
        label="Warunek udziału — 1. miesiąc kwartału",
        unit="placementów",
    ),
    ScoringField(
        key="league_min_placements_month2",
        default=2,
        minimum=0,
        maximum=100,
        group="league_qualification",
        label="Warunek udziału — 2. miesiąc kwartału",
        unit="placementów",
    ),
    ScoringField(
        key="league_min_placements_month3",
        default=3,
        minimum=0,
        maximum=100,
        group="league_qualification",
        label="Warunek udziału — 3. miesiąc kwartału (i kwartał zamknięty)",
        unit="placementów",
    ),
    ScoringField(
        key="seniority_senior_placements",
        default=6,
        minimum=0,
        maximum=100,
        group="seniority",
        label="Ścieżka rozwoju — placementy na Seniora",
        unit="placementów",
    ),
    ScoringField(
        key="seniority_senior_window_months",
        default=6,
        minimum=1,
        maximum=24,
        group="seniority",
        label="Ścieżka rozwoju — okno dla Seniora",
        unit="miesięcy",
    ),
    ScoringField(
        key="seniority_expert_placements",
        default=12,
        minimum=0,
        maximum=100,
        group="seniority",
        label="Ścieżka rozwoju — placementy na Eksperta",
        unit="placementów",
    ),
    ScoringField(
        key="seniority_expert_window_months",
        default=12,
        minimum=1,
        maximum=24,
        group="seniority",
        label="Ścieżka rozwoju — okno dla Eksperta",
        unit="miesięcy",
    ),
)

SCORING_FIELDS_BY_KEY: dict[str, ScoringField] = {f.key: f for f in SCORING_FIELDS}

# Jedyne źródło wartości domyślnych w całym repozytorium. `competitions.py`
# importuje stąd, zamiast trzymać własne stałe — inaczej „przywróć domyślne"
# i „nigdy nic nie zapisano" dawałyby dwie różne punktacje.
SCORING_DEFAULTS: dict[str, int] = {f.key: f.default for f in SCORING_FIELDS}


def validate_scoring_values(values: Mapping[str, object]) -> dict[str, int]:
    """Sprawdź klucze i zakresy; zwróć wyłącznie wartości całkowite.

    Odrzuca CAŁE żądanie przy pierwszym problemie, zamiast zapisywać część.
    Zapis częściowy dawałby punktację, której nikt nie zażądał: admin
    wysyłający trzy wagi naraz zobaczyłby błąd i dwie zmienione wagi.
    """
    if not values:
        raise ScoringConfigError("Podaj przynajmniej jedną wartość do zapisania.")

    unknown = sorted(set(values) - set(SCORING_FIELDS_BY_KEY))
    if unknown:
        raise ScoringConfigError(
            "Nieznane klucze konfiguracji: "
            + ", ".join(unknown)
            + ". Dozwolone: "
            + ", ".join(sorted(SCORING_FIELDS_BY_KEY))
        )

    cleaned: dict[str, int] = {}
    for key, raw in values.items():
        field = SCORING_FIELDS_BY_KEY[key]
        # `bool` jest podklasą `int` w Pythonie, więc `True` przeszłoby jako 1
        # i zapisało wagę, której nikt nie wpisał.
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ScoringConfigError(
                f"`{key}`: wartość musi być liczbą całkowitą (otrzymano {raw!r})."
            )
        if raw < field.minimum or raw > field.maximum:
            raise ScoringConfigError(
                f"`{key}`: dozwolony zakres to {field.minimum}..{field.maximum} "
                f"(otrzymano {raw})."
            )
        cleaned[key] = raw
    return cleaned


async def get_scoring_config(db: AsyncSession) -> dict[str, int]:
    """Pełna konfiguracja: domyślne z kodu nadpisane wierszami z tabeli.

    NIGDY nie rzuca. Zwraca komplet kluczy, więc konsument nie musi nigdzie
    robić `.get(key, default)` — a to znaczy, że nie ma gdzie zapomnieć.
    """
    cached = await cache_get(_CACHE_KEY)
    if isinstance(cached, dict):
        return dict(cached)

    resolved = dict(SCORING_DEFAULTS)
    try:
        # SAVEPOINT: patrz docstring modułu. Bez niego brak tabeli zabiera
        # ze sobą całą transakcję żądania, a nie tylko tę jedną odpowiedź.
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(InsightsScoringConfig.key, InsightsScoringConfig.value)
                )
            ).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "insights scoring config unreadable (%r) — obowiązują wartości "
            "domyślne z kodu",
            exc,
        )
        return resolved

    for row in rows:
        # Klucz, którego kod już nie zna (np. po usunięciu funkcji), jest
        # IGNOROWANY, nie przepisywany do odpowiedzi — inaczej konsument
        # dostałby pole, którego znaczenia nikt nie potrafi podać.
        if row.key in SCORING_DEFAULTS:
            resolved[row.key] = int(row.value)

    await cache_set(_CACHE_KEY, dict(resolved), ttl_seconds=CACHE_TTL_SECONDS)
    return resolved


async def set_scoring_config(
    db: AsyncSession,
    values: Mapping[str, object],
    *,
    updated_by: int | None,
) -> dict[str, int]:
    """Zapisz odstępstwa od domyślnych i zwróć obowiązującą konfigurację.

    Waliduje przed dotknięciem bazy — patrz `validate_scoring_values`.
    """
    cleaned = validate_scoring_values(values)

    existing = {
        row.key: row
        for row in (
            (
                await db.execute(
                    select(InsightsScoringConfig).where(
                        InsightsScoringConfig.key.in_(list(cleaned))
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    for key, value in cleaned.items():
        row = existing.get(key)
        if row is None:
            db.add(InsightsScoringConfig(key=key, value=value, updated_by=updated_by))
        else:
            row.value = value
            row.updated_by = updated_by
    await db.commit()

    await invalidate_scoring_cache()
    return await get_scoring_config(db)


async def invalidate_scoring_cache() -> None:
    """Zdejmij cache procesu. Woła to zapis; testy wołają przed asercją."""
    await cache_invalidate(_CACHE_KEY)


def league_points_formula(config: Mapping[str, int]) -> dict[str, int]:
    """Wagi Ligi w kształcie, który front pokazuje na kaflu „System punktowy".

    Klucze (`placement`/`interview`/`recommendation`) są kontraktem z UI
    i NIE są nazwami kluczy konfiguracji — front czyta je od zawsze i zmiana
    nazw zgasiłaby kafel bez żadnego błędu.
    """
    return {
        "placement": config["league_points_placement"],
        "interview": config["league_points_interview"],
        "recommendation": config["league_points_recommendation"],
    }


def scoring_fields_payload(
    config: Mapping[str, int],
    *,
    meta: Mapping[str, Mapping[str, object]] | None = None,
    fields: Iterable[ScoringField] = SCORING_FIELDS,
) -> list[dict]:
    """Opis pól + wartość obowiązująca + czy to jeszcze wartość domyślna."""
    meta = meta or {}
    payload = []
    for field in fields:
        value = int(config[field.key])
        row_meta = meta.get(field.key, {})
        payload.append(
            {
                "key": field.key,
                "value": value,
                "default": field.default,
                "min": field.minimum,
                "max": field.maximum,
                "group": field.group,
                "label": field.label,
                "unit": field.unit,
                # `is_default` liczone z WARTOŚCI, nie z obecności wiersza:
                # wpisanie ręcznie tej samej liczby co domyślna nie jest
                # odstępstwem i nie ma powodu, żeby wyglądało inaczej.
                "is_default": value == field.default,
                "updated_at": row_meta.get("updated_at"),
                "updated_by_name": row_meta.get("updated_by_name"),
            }
        )
    return payload
