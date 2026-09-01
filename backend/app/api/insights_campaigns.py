"""`/api/insights/campaigns` — baner kampanii rekrutacyjnej i jej CRUD.

Dwa guardy w jednym routerze, i ta różnica jest sednem:

* **GET `/active` → `CurrentUser`.** Cel kampanii jest ogłoszeniem dla całej
  firmy (decyzja D7). Baner, którego nie widzi połowa zespołu, nie jest
  kampanią.
* **Reszta → `AdminUser`.** Założenie kampanii ustawia cel, z którego
  rozliczany jest zespół, a przesunięcie okna zmienia wynik wstecz.

TRZY LICZBY, KTÓRYCH TU NIE MA W BAZIE
--------------------------------------
``placements``, ``resignations`` i ``net`` są LICZONE przy odczycie. Kolumna
z wynikiem przestaje być prawdą w chwili, w której ktoś przesunie etap albo
zakończy kontrakt wstecz — a baner pokazywałby wtedy liczbę, pod którą nie
ma żadnego błędu do zdiagnozowania.

DEFINICJE JADĄ W ODPOWIEDZI
---------------------------
Tak samo jak ``placements_definition`` w `insights_board.py`. „Rezygnacja"
ma w tej aplikacji co najmniej trzy sensowne znaczenia (patrz
``RESIGNATIONS_DEFINITION_NOTE``), a trzy różne „rezygnacje" na jednym
ekranie to dokładnie ta klasa pomyłki, którą D2 zamyka dla placementów.
Konsument dostaje slug i zdanie po polsku, żeby mógł je napisać na kaflu.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import (
    MAX_CUSTOM_PERIOD_DAYS,
    Period,
    PeriodError,
    resolve_period,
)
from app.api.deps import AdminUser, CurrentUser
from app.core.cache import cache_get, cache_invalidate, cache_set
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.recruitment_campaign import RecruitmentCampaign

logger = logging.getLogger(__name__)

router = APIRouter()

CACHE_TTL_SECONDS = 300
CACHE_PREFIX = "insights:campaigns:counts:v1"

# ── Definicje liczników ─────────────────────────────────────────────────────

# Ten sam slug co w `insights_board.py`. Gdyby baner liczył placementy inaczej
# niż kokpit zarządu, dwie liczby pod tą samą nazwą na sąsiednich ekranach
# różniłyby się bez żadnego wyjaśnienia.
PLACEMENTS_DEFINITION = "first_hired_per_candidate_job"
PLACEMENTS_DEFINITION_NOTE = (
    "Placement = PIERWSZE wejście na etap „Zatrudniony” dla pary "
    "(kandydat, rekrutacja) w oknie kampanii (widok analytics_first_milestones)."
)

# ŚWIADOMY WYBÓR SPOŚRÓD TRZECH KANDYDATUR — `backend/app/models/contract.py`:
#
# (a) `termination_reason = 'consultant_resigned'` — dosłowna „rezygnacja"
#     konsultanta. ODRZUCONE: kampania mierzy PRZYROST NETTO liczby
#     kontraktorów, a stan zabiera tak samo zakończony projekt u klienta, jak
#     i odejście na własną prośbę. Ta definicja zawyżałaby netto o wszystkie
#     zakończenia z pozostałych dziewięciu powodów, a przy `termination_reason
#     IS NULL` (większość wierszy historycznych) liczyłaby zero.
#
# (b) sam status `ended` — ODRZUCONE jako JEDYNY warunek. Status jest
#     przechowywany i przestemplowuje go nocny `_promote_statuses`, więc
#     kontrakt, któremu okres minął wczoraj, bywa jeszcze `active`. Liczenie
#     wyłącznie po statusie gubiłoby zakończenia z ostatniej doby — czyli
#     dokładnie te, o które ktoś patrzący na baner pyta.
#
# (c) PRZYJĘTE: dzień faktycznego zakończenia w oknie, dla kontraktu, który
#     kiedykolwiek żył. Dzień to `COALESCE(terminated_at, end_date)`, bo
#     `terminated_at` bywa WCZEŚNIEJSZY niż `end_date` (zerwanie przed czasem)
#     i wtedy to on jest dniem, w którym kontraktor zniknął ze stanu.
#
# Wykluczone statusy i powód każdego z osobna:
#   `draft` / `ready_for_signature` — nigdy nie ruszyły, więc nie ma czego
#       odejmować; data końca w takim wierszu to plan, nie fakt.
#   `void` — anulowanie ZAPISU (soft-delete z zachowaniem dokumentów), a nie
#       zakończenie współpracy. Policzone byłoby odejściem osoby, która nigdy
#       nie została policzona jako przyjście.
# Kontrakty bezterminowe (`end_date IS NULL` i bez `terminated_at`) odpadają
# same — `COALESCE` daje NULL, a NULL nie mieści się w żadnym oknie.
RESIGNATIONS_DEFINITION = "ended_engagement_by_effective_end_date"
RESIGNATIONS_DEFINITION_NOTE = (
    "Rezygnacja = kontrakt, którego dzień faktycznego zakończenia "
    "(data rozwiązania, a gdy jej brak — data końca) wypada w oknie kampanii. "
    "Liczą się kontrakty aktywne, kończące się i zakończone; NIE liczą się "
    "szkice, oczekujące na podpis ani anulowane. Powód zakończenia nie ma "
    "znaczenia: projekt zakończony u klienta zabiera kontraktora ze stanu tak "
    "samo jak odejście na własną prośbę."
)

_RESIGNATION_STATUSES = ["ended", "active", "ending"]


def _ratio(numerator: int, denominator: int) -> float | None:
    """Udział procentowy albo ``None`` przy zerowym mianowniku.

    NIE zwraca 0.0 — cel równy zeru znaczy „nie ma czego dzielić", a nie
    „postęp zerowy". Świadomie NIE przycinamy też do 100%: przekroczony cel
    jest faktem i ma być widoczny, a nie schowany pod pełnym paskiem.
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _campaign_window(campaign: RecruitmentCampaign) -> Period:
    """Okno kampanii jako kanoniczny ``Period`` (Europe/Warsaw, [start, end)).

    ``custom`` zamiast ręcznej arytmetyki dat: dzięki temu klucz cache'u niesie
    ``cache_suffix``, czyli granice okna. Klucz bez okna podałby liczby jednej
    kampanii pod etykietą drugiej i nikt by się nie dowiedział.
    """
    try:
        return resolve_period(
            "custom", date_from=campaign.start_date, date_to=campaign.end_date
        )
    except PeriodError as exc:
        # Zapisy są walidowane, więc to jest wyłącznie obrona przed wierszem
        # wstawionym z pominięciem API. 422 z treścią, a nie ciche `null`:
        # brak banera czytałby się jako „nie ma kampanii".
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Okno kampanii jest nieprawidłowe: {exc}",
        ) from exc


async def _count_window(db: AsyncSession, window: Period) -> tuple[int, int]:
    """(placementy, rezygnacje) w oknie — z cache'em kluczowanym oknem."""
    cache_key = f"{CACHE_PREFIX}:{window.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return int(cached["placements"]), int(cached["resignations"])

    params = {"start": window.start, "end": window.end}

    # D2: PIERWSZE `hired` per para (kandydat, oferta). Widok jest
    # zdeduplikowany w swojej definicji (`rn = 1`), więc powrót kandydata do
    # etapu nie liczy się drugi raz. NIGDY surowy `candidate_stages`.
    placements = int(
        (
            await db.execute(
                text(
                    """
                    SELECT count(*) AS cnt
                    FROM analytics_first_milestones fm
                    WHERE fm.stage::text = 'hired'
                      AND fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                    """
                ),
                params,
            )
        ).scalar()
        or 0
    )

    # Rezygnacje liczymy na DATACH (kolumny `Date`), a granice bierzemy z tego
    # samego `Period` — inaczej dwie połowy jednej liczby netto opisywałyby
    # dwa różne okna.
    resignations = int(
        (
            await db.execute(
                text(
                    """
                    SELECT count(*) AS cnt
                    FROM contracts c
                    WHERE c.status::text = ANY(:statuses)
                      AND COALESCE(c.terminated_at, c.end_date) >= :start_d
                      AND COALESCE(c.terminated_at, c.end_date) < :end_d
                    """
                ),
                {
                    "statuses": _RESIGNATION_STATUSES,
                    "start_d": window.start.date(),
                    "end_d": window.end.date(),
                },
            )
        ).scalar()
        or 0
    )

    await cache_set(
        cache_key,
        {"placements": placements, "resignations": resignations},
        ttl_seconds=CACHE_TTL_SECONDS,
    )
    return placements, resignations


def _campaign_identity(campaign: RecruitmentCampaign) -> dict:
    return {
        "id": campaign.id,
        "name": campaign.name,
        "emoji": campaign.emoji,
        "start_date": campaign.start_date.isoformat(),
        "end_date": campaign.end_date.isoformat(),
        "target_net": campaign.target_net,
        "is_active": campaign.is_active,
        "created_at": (
            campaign.created_at.isoformat() if campaign.created_at is not None else None
        ),
    }


async def _campaign_payload(db: AsyncSession, campaign: RecruitmentCampaign) -> dict:
    window = _campaign_window(campaign)
    placements, resignations = await _count_window(db, window)
    net = placements - resignations

    # `business_today()`, nie `date.today()`: kontener chodzi w UTC, więc
    # między północą UTC a warszawską licznik „zostało N dni" pokazywałby
    # o jeden za dużo. Objaw jest cichy — liczba jest poprawna, tylko dla
    # innego dnia.
    today = business_today()
    # Dolne cięcie do zera dotyczy WYŁĄCZNIE licznika dni: ujemna liczba dni
    # do końca nie znaczy nic, a ujemne „zostało do celu" znaczy „cel
    # przekroczony" i zostaje surowe.
    days_remaining = max((campaign.end_date - today).days, 0)

    return {
        **_campaign_identity(campaign),
        "window": window.as_payload(),
        "days_remaining": days_remaining,
        "has_started": campaign.start_date <= today,
        "placements": placements,
        "resignations": resignations,
        "net": net,
        # `None` przy celu 0 — „nie da się policzyć" to co innego niż „zero
        # postępu". Nieprzycięte do 100 — przekroczony cel jest faktem.
        "progress_pct": _ratio(net, campaign.target_net),
        # Surowe, może być ujemne: ujemna wartość = cel przekroczony o tyle.
        "remaining_to_target": campaign.target_net - net,
        "placements_definition": PLACEMENTS_DEFINITION,
        "placements_definition_note": PLACEMENTS_DEFINITION_NOTE,
        "resignations_definition": RESIGNATIONS_DEFINITION,
        "resignations_definition_note": RESIGNATIONS_DEFINITION_NOTE,
        "net_definition_note": "netto = placementy − rezygnacje",
    }


# ── Walidacja zapisu ────────────────────────────────────────────────────────


def _validate_window(start: date, end: date) -> None:
    """Reguły okna po polsku, w API — nie jako `CHECK` rzucający IntegrityError.

    Limit 366 dni nie jest arbitralny: okno kampanii wyrażamy przez
    ``resolve_period(kind="custom")``, a ten dopuszcza najwyżej
    ``MAX_CUSTOM_PERIOD_DAYS``. Bez tej bramki dałoby się zapisać kampanię,
    której własny odczyt kończy się błędem.
    """
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Data zakończenia kampanii nie może być wcześniejsza niż data startu.",
        )
    span_days = (end - start).days + 1
    if span_days > MAX_CUSTOM_PERIOD_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Kampania może trwać najwyżej {MAX_CUSTOM_PERIOD_DAYS} dni "
                f"(podano {span_days})."
            ),
        )


def _clean_emoji(value: str | None) -> str | None:
    """Pusty string to brak emoji, nie emoji o zerowej długości."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    emoji: str | None = Field(None, max_length=16)
    start_date: date
    end_date: date
    target_net: int = Field(0, ge=0, le=100_000)
    is_active: bool = False


class CampaignUpdate(BaseModel):
    """Zapis CZĘŚCIOWY — pominięte pole zostaje bez zmian.

    Wszystkie pola są `Optional`, więc rozstrzyga `model_fields_set`. Bez tego
    zmiana samej flagi `is_active` wyczyściłaby nazwę i okno.
    """

    name: str | None = Field(None, min_length=1, max_length=200)
    emoji: str | None = Field(None, max_length=16)
    start_date: date | None = None
    end_date: date | None = None
    target_net: int | None = Field(None, ge=0, le=100_000)
    is_active: bool | None = None


async def _deactivate_others(db: AsyncSession, keep_id: int | None) -> None:
    """Aktywna jest DOKŁADNIE jedna kampania.

    Baner renderuje jedną; dwie aktywne znaczyłyby, że o tym, którą widzisz,
    decyduje sortowanie. Wyłączamy tu, a nie `UNIQUE INDEX ... WHERE is_active`,
    bo tamto wymusiłoby na operatorze dwa żądania w poprawnej kolejności, żeby
    przełączyć kampanię — i zostawiłoby okno bez żadnej aktywnej.
    """
    stmt = update(RecruitmentCampaign).values(is_active=False)
    stmt = stmt.where(RecruitmentCampaign.is_active.is_(True))
    if keep_id is not None:
        stmt = stmt.where(RecruitmentCampaign.id != keep_id)
    await db.execute(stmt)


async def _get_or_404(db: AsyncSession, campaign_id: int) -> RecruitmentCampaign:
    campaign = await db.get(RecruitmentCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Kampania {campaign_id} nie istnieje.",
        )
    return campaign


# ── Odczyt (D7: każda zalogowana rola) ──────────────────────────────────────


@router.get("/active")
async def read_active_campaign(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Aktywna kampania z policzonymi liczbami albo ``null``.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7): cel kampanii jest
    ogłoszeniem dla całej firmy, a nie danymi wrażliwymi — liczniki są
    zagregowane, bez ani jednego nazwiska.

    ``null`` znaczy DOKŁADNIE „nie ma aktywnej kampanii" i nic więcej. Awaria
    kończy się kodem błędu, nie pustką — inaczej konsument nie odróżniłby
    braku kampanii od niedziałającego serwera.
    """
    campaign = (
        await db.execute(
            select(RecruitmentCampaign)
            .where(RecruitmentCampaign.is_active.is_(True))
            # Deterministyczna kolejność mimo `_deactivate_others`: wiersze
            # bywają wstawiane z pominięciem API (migracja, ręczny SQL), a
            # baner losujący kampanię byłby gorszy od banera przewidywalnego.
            .order_by(
                RecruitmentCampaign.start_date.desc(), RecruitmentCampaign.id.desc()
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if campaign is None:
        return None
    return await _campaign_payload(db, campaign)


# ── CRUD (admin) ────────────────────────────────────────────────────────────


@router.get("")
async def list_campaigns(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Wszystkie kampanie — ekran zarządzania.

    Bez liczników: lista służy do edycji definicji, a policzenie okna dla
    każdego wiersza oznaczałoby dwa zapytania na kampanię.
    """
    rows = (
        (
            await db.execute(
                select(RecruitmentCampaign).order_by(
                    RecruitmentCampaign.start_date.desc(),
                    RecruitmentCampaign.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return {"campaigns": [_campaign_identity(c) for c in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    _validate_window(payload.start_date, payload.end_date)

    campaign = RecruitmentCampaign(
        name=payload.name.strip(),
        emoji=_clean_emoji(payload.emoji),
        start_date=payload.start_date,
        end_date=payload.end_date,
        target_net=payload.target_net,
        is_active=payload.is_active,
        created_by=current_user.id,
    )
    db.add(campaign)
    await db.flush()
    if payload.is_active:
        await _deactivate_others(db, keep_id=campaign.id)
    await db.commit()
    await db.refresh(campaign)
    await cache_invalidate(CACHE_PREFIX)
    return await _campaign_payload(db, campaign)


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    campaign = await _get_or_404(db, campaign_id)
    fields = payload.model_dump(exclude_unset=True)

    # Okno walidujemy po ZŁOŻENIU zmiany ze stanem bieżącym: przesunięcie samej
    # daty startu poza datę końca inaczej przeszłoby bez słowa.
    new_start = fields.get("start_date", campaign.start_date)
    new_end = fields.get("end_date", campaign.end_date)
    _validate_window(new_start, new_end)

    if "name" in fields and fields["name"] is not None:
        campaign.name = fields["name"].strip()
    if "emoji" in fields:
        campaign.emoji = _clean_emoji(fields["emoji"])
    if "start_date" in fields and fields["start_date"] is not None:
        campaign.start_date = fields["start_date"]
    if "end_date" in fields and fields["end_date"] is not None:
        campaign.end_date = fields["end_date"]
    if "target_net" in fields and fields["target_net"] is not None:
        campaign.target_net = fields["target_net"]
    if "is_active" in fields and fields["is_active"] is not None:
        campaign.is_active = fields["is_active"]
        if campaign.is_active:
            await _deactivate_others(db, keep_id=campaign.id)

    await db.commit()
    await db.refresh(campaign)
    await cache_invalidate(CACHE_PREFIX)
    return await _campaign_payload(db, campaign)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Twarde usunięcie — kampania nie ma historii do zachowania.

    Wszystkie liczby są wyliczane z `candidate_stages` i `contracts`, więc
    skasowanie wiersza nie kasuje żadnego faktu; zostaje wyłącznie ogłoszenie.
    """
    campaign = await _get_or_404(db, campaign_id)
    await db.delete(campaign)
    await db.commit()
    await cache_invalidate(CACHE_PREFIX)
    return None
