"""Wyniki konkursów sprzed NEXUS-a — DynaReporter do 11.10.2026.

Decyzja Artura 15.10.2026: zespół liczy wyniki w NEXUS-ie od 12.10.2026.
Wcześniej wynik każdej osoby wpisywano tygodniowo do DynaReportera
(`kpi_body_leasing`, w NEXUS-ie `dr_kpi_body_leasing`) i z tych liczb
ogłaszano Ligę Mistrzów i wyścigi. NEXUS liczył te same okresy z historii
Traffita, a tam punkt dostaje osoba, która przesunęła kartę (często Delivery
Lead) — stąd inne podia niż ogłoszone.

Zasada źródła — jedna, bez sumowania tych samych dni:

* okres w całości przed `RESULTS_CUTOVER` — wynik z DynaReportera, rozliczony
  raz skryptem `scripts/settle_competitions_from_dynareporter.py` i zamrożony;
* okres przecinający cutover (Q4 2026, październik 2026) — dni do 11.10
  z `dr_kpi_body_leasing`, od 12.10 na żywo z NEXUS-a;
* okres po cutoverze — wyłącznie NEXUS.

Reguły DynaReportera (`dr_*` niżej) odtworzono na jego oficjalnych wynikach
I–VI 2026 — zgodność 12/12, łącznie z majem bez zwycięzcy wyścigu
rekomendacji. Różnią się od reguł NEXUS-a w trzech miejscach: próg
weryfikacji liczy dni PRZEPRACOWANE z raportu (nie dni robocze kalendarza),
precyzja obowiązuje od kwietnia 2026, a lider kwartału jest wykluczony
z wyścigów tylko w ostatnim miesiącu kwartału.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from fractions import Fraction
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, local_day_start_utc

# Pierwszy dzień, który liczy NEXUS. Fakt biznesowy (start pracy zespołu
# w NEXUS-ie), nie ustawienie — zmiana przesunęłaby granicę rozliczonych już
# i wypłaconych okresów.
RESULTS_CUTOVER = date(2026, 10, 12)
# Pierwszy dzień tygodniowych wpisów DynaReportera (decyzja Artura 17.10.2026):
# od niego klienci placementów są z `dr_placement_details`, wcześniej z raportu
# Rady (`dr_board_placement_clients`). Wpisy sprzed tego dnia DynaReporter nie
# prowadził — zespół uzupełnia je ręcznie (`scripts/import_dr_manual_fill.py`),
# a widok `analytics_kpi_milestones` liczy je od 0472.
DR_HISTORY_START = date(2026, 1, 1)

SOURCE_NEXUS = "nexus"
SOURCE_DYNAREPORTER = "dynareporter"
SOURCE_MIXED = "mixed"

MIXED_SOURCE_NOTE = (
    "Dni do 11.10.2026 z DynaReportera, od 12.10.2026 liczy NEXUS — "
    "żaden dzień nie jest liczony dwa razy."
)
DYNAREPORTER_SOURCE_NOTE = (
    "Wynik z DynaReportera — rozliczony przy przejściu na NEXUS (12.10.2026)."
)
DYNAREPORTER_OFFICIAL_NOTE = (
    "Oficjalny wynik ogłoszony w DynaReporterze — przeniesiony bez zmian."
)

# Reguły wyścigów DynaReportera (patrz docstring modułu).
DR_VERIFICATIONS_PER_WORKED_DAY = 4
DR_PRECISION_PCT = 75
DR_PRECISION_FROM_MONTH = "2026-04"
DR_DEFAULT_DAYS_WORKED = 5
DR_LEAGUE_MIN_PLACEMENTS = 3


def cutover_utc() -> datetime:
    """Północ 12.10.2026 w Warszawie, w UTC — granica `reached_at`."""
    return local_day_start_utc(RESULTS_CUTOVER)


def live_window(start: datetime, end: datetime) -> Optional[tuple[datetime, datetime]]:
    """Część okna, którą liczy NEXUS na żywo (`None` = żadna)."""
    live_start = max(start, cutover_utc())
    return (live_start, end) if live_start < end else None


def dr_window(start: datetime, end: datetime) -> Optional[tuple[datetime, datetime]]:
    """Część okna sprzed cutoveru — liczby z `dr_kpi_body_leasing` (`None` = żadna)."""
    dr_end = min(end, cutover_utc())
    return (start, dr_end) if start < dr_end else None


def board_start(start: datetime) -> datetime:
    """Początek części okna, którą wolno liczyć z ruchów Tablicy.

    Decyzja Artura 18.10.2026: przed 12.10.2026 statystyki nie biorą ruchów
    Tablicy (import z Traffita) — ekrany, których DynaReporter nie zna (lejek po
    etapach, źródła, czas do zatrudnienia, hit ratio), liczą od tego dnia,
    a wcześniejsze dni pokazują jako brak danych.
    """
    return max(start, cutover_utc())


def window_source(start: datetime, end: datetime) -> str:
    has_dr = dr_window(start, end) is not None
    has_live = live_window(start, end) is not None
    if has_dr and has_live:
        return SOURCE_MIXED
    return SOURCE_DYNAREPORTER if has_dr else SOURCE_NEXUS


# ── Liczniki z DynaReportera dla okresu mieszanego ──────────────────────


@dataclass(frozen=True)
class DrCounts:
    """Suma tygodniowych wpisów jednej osoby w oknie."""

    verifications: int = 0
    recommendations: int = 0
    interviews: int = 0
    placements: int = 0
    days_worked: int = 0

    def plus(self, other: "DrCounts") -> "DrCounts":
        return DrCounts(
            verifications=self.verifications + other.verifications,
            recommendations=self.recommendations + other.recommendations,
            interviews=self.interviews + other.interviews,
            placements=self.placements + other.placements,
            days_worked=self.days_worked + other.days_worked,
        )


@dataclass(frozen=True)
class DrPersonCounts:
    user_id: int
    name: str
    role: str
    counts: DrCounts


async def dr_counts_by_user(
    db: AsyncSession, start: datetime, end: datetime
) -> dict[int, DrPersonCounts]:
    """Wpisy DynaReportera z części okna przed cutoverem.

    Populacja jak w rankingach na żywo (aktywni z rolą rekrutera): ta funkcja
    zasila wyłącznie okresy trwające, a w nich osoba, która odeszła, nie gra.
    Wpis jest tygodniem w obrębie jednego miesiąca, a `report_date` to jego
    pierwszy dzień — porównanie dat kalendarzowych wystarcza, bo cutover
    (poniedziałek) i granice miesięcy są początkami wpisów.
    """
    window = dr_window(start, end)
    if window is None:
        return {}
    rows = (
        await db.execute(
            text(
                """
                SELECT u.id, u.name, u.role::text AS role,
                       sum(k.verifications) AS verifications,
                       sum(k.recommendations) AS recommendations,
                       sum(k.interviews) AS interviews,
                       sum(k.placements) AS placements,
                       sum(COALESCE(k.days_worked, :default_days)) AS days_worked
                FROM dr_kpi_body_leasing k
                JOIN users u ON u.id = k.user_id
                WHERE k.is_draft IS FALSE
                  AND k.report_date >= :start_day
                  AND k.report_date < :end_day
                  AND (
                      u.role::text = 'recruiter'
                      OR u.roles ? 'recruiter'
                  )
                  AND u.is_active IS TRUE
                GROUP BY u.id, u.name, u.role
                """
            ),
            {
                "start_day": _local_day(window[0]),
                "end_day": _local_day(window[1]),
                "default_days": DR_DEFAULT_DAYS_WORKED,
            },
        )
    ).all()
    return {
        r.id: DrPersonCounts(
            user_id=r.id,
            name=r.name,
            role=r.role,
            counts=DrCounts(
                verifications=int(r.verifications or 0),
                recommendations=int(r.recommendations or 0),
                interviews=int(r.interviews or 0),
                placements=int(r.placements or 0),
                days_worked=int(r.days_worked or 0),
            ),
        )
        for r in rows
    }


def _local_day(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


# ── Reguły DynaReportera (rozliczenie okresów sprzed cutoveru) ──────────


# Miesiąc → osoba → liczniki. Klucz miesiąca w formacie okresu wyścigu.
DrMonthly = Mapping[str, Mapping[int, DrCounts]]


@dataclass
class DrEntry:
    """Pozycja rankingu z danych DynaReportera.

    Ten sam kształt co `RankedUser` (`user_id`, `metric_value`, `extras`,
    `to_dict`), bo idzie przez te same `order_with_ties` i `award_ranked_rows`
    co ranking na żywo — zamrożony wynik ma identyczny format.
    """

    user_id: int
    name: str
    metric_value: int
    hit_ratio: Optional[float] = None
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "metric_value": self.metric_value,
            "hit_ratio": self.hit_ratio,
            **self.extras,
        }


def quarter_months(year: int, quarter: int) -> list[str]:
    first = (quarter - 1) * 3 + 1
    return [f"{year}-{m:02d}" for m in range(first, first + 3)]


def _sum_months(monthly: DrMonthly, months: Iterable[str]) -> dict[int, DrCounts]:
    totals: dict[int, DrCounts] = {}
    for month in months:
        for user_id, counts in monthly.get(month, {}).items():
            totals[user_id] = totals.get(user_id, DrCounts()).plus(counts)
    return totals


def dr_league(
    monthly: DrMonthly,
    months: Iterable[str],
    *,
    weights: Mapping[str, int],
    names: Mapping[int, str],
    min_placements: int = DR_LEAGUE_MIN_PLACEMENTS,
) -> list[DrEntry]:
    """Liga Mistrzów z wpisów DynaReportera — punkty z wag, próg placementów.

    Niezakwalifikowani zostają na liście (`qualified=False`), jak w rankingu
    na żywo. Osoba bez punktów nie gra (DynaReporter pokazywał tylko wpisy).
    """
    entries = []
    for user_id, c in _sum_months(monthly, months).items():
        points = (
            c.placements * weights["placement"]
            + c.interviews * weights["interview"]
            + c.recommendations * weights["recommendation"]
        )
        if points <= 0:
            continue
        reasons = [] if c.placements >= min_placements else ["MIN_PLACEMENTS_NOT_MET"]
        entries.append(
            DrEntry(
                user_id=user_id,
                name=names.get(user_id, f"#{user_id}"),
                metric_value=points,
                extras={
                    "placements": c.placements,
                    "interviews": c.interviews,
                    "recommendations": c.recommendations,
                    "verifications": c.verifications,
                    "qualified": not reasons,
                    "required_placements": min_placements,
                    "disqualification_reasons": reasons,
                },
            )
        )
    entries.sort(key=lambda e: (-e.metric_value, e.user_id))
    return entries


def dr_excluded_quarter_leaders(
    monthly: DrMonthly,
    month: str,
    *,
    weights: Mapping[str, int],
    min_placements: int = DR_LEAGUE_MIN_PLACEMENTS,
) -> set[int]:
    """Lider Ligi wykluczony z wyścigów — tylko w OSTATNIM miesiącu kwartału.

    Remis na szczycie wyklucza wszystkich remisujących (jak w NEXUS-ie).
    """
    year, mon = (int(part) for part in month.split("-"))
    if mon % 3 != 0:
        return set()
    league = [
        e
        for e in dr_league(
            monthly,
            quarter_months(year, (mon - 1) // 3 + 1),
            weights=weights,
            names={},
            min_placements=min_placements,
        )
        if e.extras["qualified"]
    ]
    if not league:
        return set()
    top = league[0].metric_value
    return {e.user_id for e in league if e.metric_value == top}


def dr_recommendation_race(
    counts: Mapping[int, DrCounts],
    month: str,
    *,
    names: Mapping[int, str],
) -> list[DrEntry]:
    """Wyścig rekomendacji DynaReportera.

    Warunek: co najmniej 4 weryfikacje na dzień PRZEPRACOWANY (`days_worked`
    z raportu, nie kalendarz) i — od kwietnia 2026 — precyzja ≥ 75%.
    W rankingu osoby z co najmniej jedną rekomendacją.
    """
    entries = []
    for user_id, c in counts.items():
        if c.recommendations < 1:
            continue
        days = c.days_worked if c.days_worked > 0 else 1
        per_day = Fraction(c.verifications, days)
        reasons = []
        if per_day < DR_VERIFICATIONS_PER_WORKED_DAY:
            reasons.append("MIN_VERIFICATIONS_NOT_MET")
        if (
            month >= DR_PRECISION_FROM_MONTH
            and 100 * c.recommendations < DR_PRECISION_PCT * c.verifications
        ):
            reasons.append("MIN_PRECISION_NOT_MET")
        precision = (
            round(100.0 * c.recommendations / c.verifications, 1)
            if c.verifications
            else 0.0
        )
        entries.append(
            DrEntry(
                user_id=user_id,
                name=names.get(user_id, f"#{user_id}"),
                metric_value=c.recommendations,
                extras={
                    "verifications": c.verifications,
                    "recommendations": c.recommendations,
                    "precision_pct": precision,
                    "workdays": c.days_worked,
                    "workdays_source": "dynareporter",
                    "per_day": round(float(per_day), 2),
                    "qualified": not reasons,
                    "disqualification_reasons": reasons,
                },
            )
        )
    entries.sort(key=lambda e: (-e.metric_value, e.user_id))
    return entries


def dr_placement_race(
    counts: Mapping[int, DrCounts], *, names: Mapping[int, str]
) -> list[DrEntry]:
    """Wyścig placementów DynaReportera — kto ma ich najwięcej (bez progu)."""
    entries = [
        DrEntry(
            user_id=user_id,
            name=names.get(user_id, f"#{user_id}"),
            metric_value=c.placements,
            extras={"placements": c.placements},
        )
        for user_id, c in counts.items()
        if c.placements >= 1
    ]
    entries.sort(key=lambda e: (-e.metric_value, e.user_id))
    return entries


def dr_dl_league(
    monthly: DrMonthly, months: Iterable[str], *, names: Mapping[int, str]
) -> list[DrEntry]:
    """Liga DL z miesięcznych wpisów DL w DynaReporterze (decyzja Artura 18.10.2026).

    DynaReporter Ligi DL nie prowadził; Q1–Q3 2026 liczymy z jego wpisów DL
    (`dr_kpi_delivery_lead.placements`). Próg ligi — co najmniej
    `DR_LEAGUE_MIN_PLACEMENTS` placementów; progu hit ratio nie ma, bo
    rekrutacji zamkniętych DynaReporter nie prowadził.
    """
    totals = _sum_months(monthly, months)
    entries = [
        DrEntry(
            user_id=user_id,
            name=names.get(user_id, f"#{user_id}"),
            metric_value=c.placements,
            extras={
                "placements": c.placements,
                "qualified": c.placements >= DR_LEAGUE_MIN_PLACEMENTS,
                "hit_ratio_basis": "dynareporter_without_hit_ratio",
            },
        )
        for user_id, c in totals.items()
        if c.placements >= 1
    ]
    entries.sort(key=lambda e: (-e.metric_value, e.user_id))
    return entries


def precision_tiebreak(entry: DrEntry) -> tuple:
    """Remis w wyścigu rekomendacji: wyższa precyzja (bez momentu ostatniej
    rekomendacji — tygodniowe wpisy go nie znają)."""
    verified = int(entry.extras.get("verifications") or 0)
    recommendations = int(entry.extras.get("recommendations") or 0)
    return (Fraction(recommendations, verified) if verified else Fraction(0),)


# ── Rozliczenie jednego okresu sprzed cutoveru ──────────────────────────


@dataclass
class DrSettlement:
    """Zamrożony wynik okresu z DynaReportera — to, co zapisze skrypt.

    `winners` → wiersze `competition_winners`, `details` → zamknięcie okresu
    (`competition_period_closures.details`) w formacie `freeze_competition`
    plus źródło i lista do wyświetlenia. `official_mismatch` niepusty = wynik
    policzony nie zgadza się z ogłoszonym w DynaReporterze; skrypt wtedy nic
    nie zapisuje.
    """

    competition_type: str
    period: str
    status: str
    winners: list[dict]
    details: dict
    official_mismatch: Optional[str] = None


def settle_dr_period(
    competition_type: str,
    period: str,
    monthly: DrMonthly,
    *,
    names: Mapping[int, str],
    weights: Mapping[str, int],
    official: Sequence[int] = (),
    official_settled: bool = False,
) -> DrSettlement:
    """Rozlicza okres regułami DynaReportera, kolejnością nagrodową NEXUS-a.

    `official` — ogłoszone podium DynaReportera (user_id po miejscach). Remis,
    który wtedy rozstrzygnął admin, zostaje rozstrzygnięty tak samo; podium
    sprzeczne z policzonym zatrzymuje zapis (`official_mismatch`).
    `official_settled` — DynaReporter ten okres rozliczył (także „bez
    zwycięzcy”), więc wynik jest oficjalny, nie policzony teraz.
    """
    # Import w funkcji: `competitions` importuje ten moduł (okresy mieszane).
    from app.models.competition_period_closure import (
        CLOSURE_FROZEN,
        CLOSURE_NO_WINNER,
        CLOSURE_TIE_PENDING,
    )
    from app.models.competition_winner import CompetitionType
    from app.services.competition_rules import PODIUM_ROWS, order_with_ties
    from app.services.competitions import (
        AwardOrder,
        _prize_for,
        award_ranked_rows,
        paid_slots,
        parse_month,
        parse_quarter,
    )

    ctype = CompetitionType(competition_type)
    primary = lambda e: (e.metric_value,)  # noqa: E731
    excluded: set[int] = set()
    exclusion_quarter: Optional[str] = None
    if ctype == CompetitionType.quarterly_champions_recruiter:
        year, quarter = parse_quarter(period)
        ranked = dr_league(
            monthly, quarter_months(year, quarter), weights=weights, names=names
        )
        award = [e for e in ranked if e.extras["qualified"]]
        ordered, ties = order_with_ties(
            award,
            primary=primary,
            tiebreak=None,
            paid_slots=paid_slots(ctype, period),
            admin_on_tie=True,
            reason="points_tie",
        )
        rule = "dynareporter:points→admin"
    elif ctype == CompetitionType.quarterly_champions_dl:
        year, quarter = parse_quarter(period)
        ranked = dr_dl_league(monthly, quarter_months(year, quarter), names=names)
        award = [e for e in ranked if e.extras["qualified"]]
        ordered, ties = order_with_ties(
            award,
            primary=primary,
            tiebreak=None,
            paid_slots=paid_slots(ctype, period),
            admin_on_tie=True,
            reason="placements_tie",
        )
        rule = "dynareporter:dl_placements→admin"
    elif ctype in (
        CompetitionType.monthly_recommendations,
        CompetitionType.monthly_placements,
    ):
        year, month = parse_month(period)
        excluded = dr_excluded_quarter_leaders(monthly, period, weights=weights)
        exclusion_quarter = f"Q{(month - 1) // 3 + 1} {year}"
        counts = monthly.get(period, {})
        if ctype == CompetitionType.monthly_recommendations:
            ranked = dr_recommendation_race(counts, period, names=names)
            award = [
                e for e in ranked if e.extras["qualified"] and e.user_id not in excluded
            ]
            ordered, ties = order_with_ties(
                award,
                primary=primary,
                tiebreak=precision_tiebreak,
                paid_slots=paid_slots(ctype, period),
                admin_on_tie=True,
                reason="recommendations",
            )
            rule = "dynareporter:recommendations→precision→admin"
        else:
            ranked = dr_placement_race(counts, names=names)
            award = [e for e in ranked if e.user_id not in excluded]
            ordered, ties = order_with_ties(
                award,
                primary=primary,
                tiebreak=None,
                paid_slots=paid_slots(ctype, period),
                admin_on_tie=True,
                reason="placements_tie",
            )
            rule = "dynareporter:placements→admin"
    else:
        raise ValueError(f"DynaReporter nie rozliczał typu {competition_type}")

    mismatch = None
    if official:
        ordered, ties, mismatch = _apply_official(list(ordered), ties, list(official))
    elif official_settled and ordered:
        # DynaReporter rozliczył okres bez zwycięzcy, a przeliczenie kogoś
        # nagradza — to niezgodność danych, nie „wynik przeniesiony bez zmian”.
        mismatch = (
            "DynaReporter ogłosił brak zwycięzcy, policzony "
            f"user_id={ordered[0].user_id}"
        )

    order = AwardOrder(
        ordered=ordered,
        ties=ties,
        excluded_user_ids=sorted(excluded),
        exclusion_source="dynareporter_quarter_leader" if excluded else None,
        exclusion_quarter=exclusion_quarter if excluded else None,
        tie_break_rule=rule,
        period=period,
    )
    held = {pos for tie in ties for pos in tie.positions}
    if ties:
        status = CLOSURE_TIE_PENDING
    elif ordered:
        status = CLOSURE_FROZEN
    else:
        status = CLOSURE_NO_WINNER
    winners = [
        {
            "rank": idx,
            "user_id": entry.user_id,
            "metric_value": entry.metric_value,
            "prize_pln": _prize_for(ctype, idx, period),
        }
        for idx, entry in enumerate(ordered[:PODIUM_ROWS], start=1)
        if idx not in held
    ]
    details = {
        "source": SOURCE_DYNAREPORTER,
        "source_note": (
            DYNAREPORTER_OFFICIAL_NOTE if official_settled else DYNAREPORTER_SOURCE_NOTE
        ),
        "rules": "dynareporter_2026",
        "freeze_reason": "dynareporter_settlement",
        "closure_status": status,
        "excluded_user_ids": order.excluded_user_ids,
        "exclusion_source": order.exclusion_source,
        "exclusion_quarter": order.exclusion_quarter,
        "tie_break_rule": rule,
        "ties": [tie.to_dict() for tie in ties],
        "top": [entry.to_dict() for entry in ordered[:10]],
        # Lista z numeracją nagrodową (jak `/current`) i lista wyścigu w kolejności
        # wyniku z flagą wykluczenia (jak `/monthly-races`).
        "rows": award_ranked_rows(ctype, ranked, order),
        "ranking": [
            {**entry.to_dict(), "excluded": entry.user_id in excluded}
            for entry in ranked
        ],
    }
    return DrSettlement(
        competition_type=competition_type,
        period=period,
        status=status,
        winners=winners,
        details=details,
        official_mismatch=mismatch,
    )


def _apply_official(ordered: list, ties: list, official: list[int]):
    """Ogłoszone podium rozstrzyga remis tak, jak zrobił to wtedy admin.

    Zwraca (kolejność, pozostałe remisy, opis niezgodności albo `None`).
    Oficjalna osoba może zająć miejsce tylko wtedy, gdy policzony wynik już
    ją tam stawia albo gdy stoi w remisie obejmującym to miejsce — inaczej to
    niezgodność danych, nie decyzja admina.
    """
    for rank, user_id in enumerate(official, start=1):
        ids = [entry.user_id for entry in ordered]
        if len(ids) >= rank and ids[rank - 1] == user_id:
            continue
        tie = next(
            (t for t in ties if rank in t.positions and user_id in t.user_ids), None
        )
        if tie is None:
            return (
                ordered,
                ties,
                (
                    f"miejsce {rank}: ogłoszony user_id={user_id}, policzony "
                    f"{ids[rank - 1] if len(ids) >= rank else 'brak'}"
                ),
            )
        moved = next(entry for entry in ordered if entry.user_id == user_id)
        ordered.remove(moved)
        ordered.insert(rank - 1, moved)
    # Ogłoszone miejsca są rozstrzygnięte; reszta remisu — miejsca za ogłoszonym
    # podium i osoby, których na nim nie ma — dalej czeka na admina. Inaczej
    # o nagrodzie za nieogłoszone miejsce decydowałby numer konta.
    from app.services.competition_rules import TieGroup

    placed = set(official)
    remaining = []
    for tie in ties:
        positions = [pos for pos in tie.positions if pos > len(official)]
        users = [uid for uid in tie.user_ids if uid not in placed]
        if positions and len(users) > 1:
            remaining.append(
                TieGroup(
                    positions=positions,
                    user_ids=users,
                    reason=tie.reason,
                    entries=[e for e in tie.entries if int(e["user_id"]) in users],
                )
            )
    return ordered, remaining, None
