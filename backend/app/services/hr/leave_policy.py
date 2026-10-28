"""Reguły urlopów — czyste funkcje bez bazy („Ludzie w NEXUSIE”, E1).

Przeniesione z Compassa (``lib/actions/internal-leave.ts``,
``lib/hr/leave-balance.ts``) z naprawionymi błędami:

* **pula per rok kalendarzowy dnia** — urlop 29.12–02.01 zjada pulę dwóch lat,
  Compass liczył cały wniosek do roku startu (HF-08),
* **B2B: zużycie puli liczą dni płatne**, nie wszystkie dni wniosku — dni
  bezpłatne nie zjadają puli płatnej (HF-09),
* **limity ustawowe**: urlop na żądanie 4 dni w roku, opieka nad dzieckiem
  (art. 188 KP) 2 dni w roku — Compass ich nie pilnował,
* **nikt nie decyduje o własnym wniosku**, także admin,
* **przekierowanie poczty tylko do skrzynki firmy** — zastępca z adresem spoza
  domen ``SSO_ALLOWED_DOMAINS`` nie dostanie kopii poczty (Compass tego nie
  sprawdzał).

Dzień jest niepodzielny: przy puli B2B mniejszej niż pełny dzień ten dzień
idzie jako bezpłatny (pół dnia mieści się w połówce puli).

Na zleceniu puli płatnych dni nie ma nigdy (D6, ``pool_applies``) — także
wtedy, gdy w bazie został wiersz puli z czasu innej formy.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr.calendar import WorkCalendar
from app.services.hr.employment_terms import reports_absence, terms
from app.services.hr_foundation_schema import EmploymentType
from app.services.hr_leave_schema import HALF_DAYS, LEAVE_TYPES

#: Rodzaje, które zużywają pulę urlopu wypoczynkowego.
POOL_TYPES: frozenset[str] = frozenset({"vacation", "on_demand"})
#: Formy bez puli płatnych dni (D6): na zleceniu nieobecność jest zawsze bez
#: wynagrodzenia. Wiersz ``leave_entitlements`` z czasu innej formy (pula
#: umowy o pracę przed zmianą na zlecenie) zostaje w bazie jako historia, ale
#: plan dni, podgląd, saldo i most do godzin liczą osobę jak bez puli.
NO_POOL_FORMS: frozenset[str] = frozenset({EmploymentType.zlecenie.value})
#: Rodzaje zatwierdzane od razu (zwolnienie lekarskie nie czeka na decyzję).
AUTO_APPROVED_TYPES: frozenset[str] = frozenset({"sick_leave"})
#: Rodzaje, których rodzaj i notatka są danymi o zdrowiu (``sensitivity=health``).
HEALTH_TYPES: frozenset[str] = frozenset({"sick_leave"})

#: Indeks, który pilnuje, że aktywne wnioski osoby się nie nakładają (jeden
#: aktywny wiersz dnia na osobę) — po nim rozpoznajemy wyścig dwóch zapisów.
ACTIVE_DAY_UNIQUE = "uq_leave_request_days_user_day_active"

ON_DEMAND_YEARLY_LIMIT = Decimal("4")
CHILDCARE_YEARLY_LIMIT = Decimal("2")

#: Wymiar urlopu na umowie o pracę (art. 154 KP): 20 dni przy stażu poniżej
#: 10 lat, 26 od 10 lat. Od 01.05.2026 do stażu wliczają się lata na zleceniu
#: i działalności z zaświadczenia ZUS (etap 2, D9) — Kadry wpisują staż.
SENIORITY_THRESHOLD_YEARS = 10
ENTITLEMENT_SHORT = 20
ENTITLEMENT_LONG = 26

FULL_DAY = Decimal("1.0")
HALF_DAY = Decimal("0.5")

LEAVE_TYPE_LABELS: dict[str, str] = {
    "vacation": "Urlop wypoczynkowy",
    "on_demand": "Urlop na żądanie",
    "occasional": "Urlop okolicznościowy",
    "childcare": "Opieka nad dzieckiem (art. 188)",
    "care_leave": "Urlop opiekuńczy",
    "force_majeure": "Siła wyższa",
    "sick_leave": "Zwolnienie lekarskie (L4)",
    "maternity": "Urlop macierzyński",
    "paternity": "Urlop ojcowski",
    "parental_leave": "Urlop rodzicielski",
    "childrearing": "Urlop wychowawczy",
    "unpaid_leave": "Urlop bezpłatny",
    "blood_donation": "Oddanie krwi",
    "training": "Urlop szkoleniowy",
    "holiday_in_lieu": "Odbiór dnia za święto",
    "other": "Inna nieobecność",
}

assert set(LEAVE_TYPE_LABELS) == set(LEAVE_TYPES)


def type_label(leave_type: Optional[str], employment_type: Optional[str]) -> str:
    """Nazwa rodzaju dla kręgu D6, w słowach formy (etap 2, D4).

    Na B2B i zleceniu jedyny rodzaj to dni z puli wypoczynkowej — nie „urlop
    wypoczynkowy”, tylko „Przerwa w świadczeniu usług” albo „Nieobecność”.
    """

    if leave_type in POOL_TYPES and reports_absence(employment_type):
        words = terms(employment_type)["absence"]
        return words[:1].upper() + words[1:]
    return LEAVE_TYPE_LABELS.get(leave_type or "", leave_type or "Nieobecność")


def statutory_entitlement(
    employment_type: Optional[str], seniority_years: Optional[int]
) -> Optional[int]:
    """Podpowiedź wymiaru (20/26) — tylko umowa o pracę ze znanym stażem.

    Tylko podpowiedź: pulę roku zatwierdzają Kadry (proporcja przy starcie
    w trakcie roku, część etatu — to ich decyzja).
    """

    if employment_type != "uop" or seniority_years is None:
        return None
    if seniority_years >= SENIORITY_THRESHOLD_YEARS:
        return ENTITLEMENT_LONG
    return ENTITLEMENT_SHORT


def pool_applies(employment_type: Optional[str]) -> bool:
    """Czy pula płatnych dni z ``leave_entitlements`` liczy się przy tej formie."""

    return employment_type not in NO_POOL_FORMS


class LeavePolicyError(ValueError):
    """Reguła nie pozwala na wniosek — komunikat po polsku dla osoby."""


def allowed_types(employment_type: str) -> tuple[str, ...]:
    """Rodzaje, o które osoba może wnioskować (B2B i zlecenie: tylko urlop)."""

    if reports_absence(employment_type):
        return ("vacation",)
    return LEAVE_TYPES


def validate_shape(
    *,
    leave_type: str,
    start: date,
    end: date,
    half_day: Optional[str],
    employment_type: str,
    for_self: bool,
) -> None:
    if leave_type not in LEAVE_TYPES:
        raise LeavePolicyError("Nieznany rodzaj nieobecności.")
    if end < start:
        raise LeavePolicyError("Data końca nie może być przed datą początku.")
    if half_day is not None:
        if half_day not in HALF_DAYS:
            raise LeavePolicyError("Pół dnia to rano albo po południu.")
        if start != end:
            raise LeavePolicyError("Pół dnia można wybrać tylko przy jednym dniu.")
    if (end - start).days > 366:
        raise LeavePolicyError("Wniosek może obejmować najwyżej rok.")
    if leave_type not in allowed_types(employment_type):
        label = "B2B" if employment_type == "b2b" else "umowie zlecenie"
        raise LeavePolicyError(
            f"Na {label} można wnioskować wyłącznie o urlop wypoczynkowy."
            if for_self
            else f"Osobie na {label} można wpisać wyłącznie urlop wypoczynkowy."
        )
    if leave_type == "holiday_in_lieu" and employment_type != "uop":
        raise LeavePolicyError(
            "Odbiór dnia za święto przysługuje tylko na umowie o pracę."
        )


def requested_days(
    calendar: WorkCalendar, start: date, end: date, half_day: Optional[str]
) -> list[tuple[date, Decimal]]:
    """Dni robocze wniosku z ułamkiem (pół dnia = 0,5 tylko przy jednym dniu)."""

    days = calendar.working_days(start, end)
    if half_day is not None and len(days) == 1:
        return [(days[0], HALF_DAY)]
    return [(day, FULL_DAY) for day in days]


@dataclass(frozen=True)
class PoolYear:
    """Stan puli osoby w roku przed nowym wnioskiem."""

    year: int
    entitlement_days: Optional[Decimal]
    carried_over_days: Decimal = Decimal("0")
    used_initial_days: Decimal = Decimal("0")
    #: Aktywne (oczekujące + zatwierdzone) dni płatne z puli w tym roku.
    booked_paid_days: Decimal = Decimal("0")
    on_demand_days: Decimal = Decimal("0")
    childcare_days: Decimal = Decimal("0")

    @property
    def has_pool(self) -> bool:
        return self.entitlement_days is not None

    @property
    def remaining(self) -> Optional[Decimal]:
        if self.entitlement_days is None:
            return None
        return (
            self.entitlement_days
            + self.carried_over_days
            - self.used_initial_days
            - self.booked_paid_days
        )


@dataclass(frozen=True)
class DayPlan:
    day: date
    fraction: Decimal
    paid: bool


@dataclass(frozen=True)
class YearSplit:
    year: int
    requested: Decimal
    paid: Decimal
    unpaid: Decimal
    has_pool: bool
    remaining_before: Optional[Decimal]
    remaining_after: Optional[Decimal]


@dataclass(frozen=True)
class PaidSplit:
    total: Decimal
    paid: Decimal
    unpaid: Decimal


def split_days(days: Iterable[tuple[Decimal, bool]], *, leave_type: str) -> PaidSplit:
    """Dni wniosku: razem, płatne z puli i bezpłatne — JEDNA reguła.

    Liczy ją złożenie wniosku (``plan_days``), przeliczenie po dniu wolnym
    firmy, import z Compassa i odczyt wniosku; kolumny ``paid_days`` /
    ``unpaid_days`` w ``leave_requests`` to zapisany wynik tej funkcji z dni
    wniosku (``leave_request_days``). Bezpłatny jest dzień rodzaju z puli bez
    pokrycia w puli (kontraktor ponad pulę albo bez puli) — tak samo liczy
    saldo roku (``leave_balance``). Inne rodzaje (L4, opieka, urlop
    bezpłatny) nie zużywają puli: płatne i bezpłatne to 0.
    """

    total = paid = unpaid = Decimal("0")
    pool = leave_type in POOL_TYPES
    for fraction, is_paid in days:
        total += fraction
        if is_paid:
            paid += fraction
        elif pool:
            unpaid += fraction
    return PaidSplit(total=total, paid=paid, unpaid=unpaid)


@dataclass(frozen=True)
class LeavePlan:
    days: tuple[DayPlan, ...]
    years: tuple[YearSplit, ...] = field(default_factory=tuple)
    leave_type: str = ""

    @property
    def split(self) -> PaidSplit:
        return split_days(
            ((d.fraction, d.paid) for d in self.days), leave_type=self.leave_type
        )

    @property
    def total(self) -> Decimal:
        return self.split.total

    @property
    def paid(self) -> Decimal:
        return self.split.paid

    @property
    def unpaid(self) -> Decimal:
        """Dni bezpłatne rodzaju z puli (B2B ponad pulę albo bez puli)."""

        return self.split.unpaid


def _fmt(value: Decimal) -> str:
    text = f"{value.normalize():f}"
    return text.replace(".", ",")


def plan_days(
    *,
    leave_type: str,
    employment_type: str,
    days: Sequence[tuple[date, Decimal]],
    pools: dict[int, PoolYear],
) -> LeavePlan:
    """Podział dni na płatne i bezpłatne oraz limity — per rok kalendarzowy.

    ``pools`` niesie stan puli przed wnioskiem dla każdego roku z ``days``
    (brak wpisu = rok bez puli; na zleceniu pula się nie liczy —
    ``pool_applies``). Rzuca ``LeavePolicyError`` przy przekroczeniu
    twardego limitu umowy o pracę i limitów ustawowych.
    """

    if not days:
        raise LeavePolicyError("W wybranym okresie nie ma dni roboczych.")
    by_year: dict[int, list[tuple[date, Decimal]]] = {}
    for day, fraction in days:
        by_year.setdefault(day.year, []).append((day, fraction))

    contractor = reports_absence(employment_type)
    with_pool = pool_applies(employment_type)
    planned: list[DayPlan] = []
    years: list[YearSplit] = []
    for year in sorted(by_year):
        chunk = by_year[year]
        pool = pools.get(year) or PoolYear(year=year, entitlement_days=None)
        if not with_pool:
            pool = replace(
                pool,
                entitlement_days=None,
                carried_over_days=Decimal("0"),
                used_initial_days=Decimal("0"),
            )
        requested = sum((fraction for _, fraction in chunk), Decimal("0"))

        if leave_type == "on_demand" and (
            pool.on_demand_days + requested > ON_DEMAND_YEARLY_LIMIT
        ):
            left = max(Decimal("0"), ON_DEMAND_YEARLY_LIMIT - pool.on_demand_days)
            raise LeavePolicyError(
                f"Urlop na żądanie to najwyżej {_fmt(ON_DEMAND_YEARLY_LIMIT)} dni "
                f"w roku — w {year} zostało {_fmt(left)}."
            )
        if (
            leave_type == "childcare"
            and not contractor
            and pool.childcare_days + requested > CHILDCARE_YEARLY_LIMIT
        ):
            left = max(Decimal("0"), CHILDCARE_YEARLY_LIMIT - pool.childcare_days)
            raise LeavePolicyError(
                "Opieka nad dzieckiem (art. 188) to najwyżej "
                f"{_fmt(CHILDCARE_YEARLY_LIMIT)} dni w roku — w {year} "
                f"zostało {_fmt(left)}."
            )

        if leave_type not in POOL_TYPES:
            planned.extend(DayPlan(day, fraction, False) for day, fraction in chunk)
            years.append(
                YearSplit(
                    year=year,
                    requested=requested,
                    paid=Decimal("0"),
                    unpaid=Decimal("0"),
                    has_pool=pool.has_pool,
                    remaining_before=pool.remaining,
                    remaining_after=pool.remaining,
                )
            )
            continue

        remaining = pool.remaining
        if not contractor:
            # Umowa o pracę: z wymiarem twardy limit, bez wymiaru bez limitu.
            if remaining is not None and requested > remaining:
                raise LeavePolicyError(
                    f"W {year} zostało {_fmt(max(remaining, Decimal('0')))} dni "
                    f"urlopu, a wniosek to {_fmt(requested)} dni roboczych. "
                    "Na nadwyżkę złóż osobny wniosek o urlop bezpłatny."
                )
            planned.extend(DayPlan(day, fraction, True) for day, fraction in chunk)
            paid = requested
        elif remaining is None:
            planned.extend(DayPlan(day, fraction, False) for day, fraction in chunk)
            paid = Decimal("0")
        else:
            available = max(remaining, Decimal("0"))
            paid = Decimal("0")
            for day, fraction in chunk:
                is_paid = fraction <= available
                if is_paid:
                    available -= fraction
                    paid += fraction
                planned.append(DayPlan(day, fraction, is_paid))
        years.append(
            YearSplit(
                year=year,
                requested=requested,
                paid=paid,
                unpaid=requested - paid,
                has_pool=pool.has_pool,
                remaining_before=remaining,
                remaining_after=None if remaining is None else remaining - paid,
            )
        )
    return LeavePlan(days=tuple(planned), years=tuple(years), leave_type=leave_type)


# ── Kto co może ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Actor:
    """Uprawnienia działającej osoby względem urlopów."""

    user_id: int
    is_admin: bool = False
    is_people_admin: bool = False

    @property
    def sees_everyone(self) -> bool:
        return self.is_admin or self.is_people_admin


def actor_of(user: User) -> Actor:
    return Actor(
        user_id=user.id,
        is_admin=user.has_role(UserRole.admin),
        is_people_admin=has_permission(user, ProductAction.people_admin),
    )


def can_decide(
    actor: Actor, *, subject_user_id: int, subject_manager_id: Optional[int]
) -> bool:
    """Akceptuje przełożony swojego człowieka, Kadry i admin — nikt siebie."""

    if actor.user_id == subject_user_id:
        return False
    if actor.sees_everyone:
        return True
    return subject_manager_id is not None and subject_manager_id == actor.user_id


def can_see_type(
    viewer: Actor, *, subject_user_id: int, subject_manager_id: Optional[int]
) -> bool:
    """D6: rodzaj nieobecności widzą osoba, jej przełożony i Kadry (+ admin)."""

    if viewer.user_id == subject_user_id or viewer.sees_everyone:
        return True
    return subject_manager_id is not None and subject_manager_id == viewer.user_id


# ── Zastępca nieobecnego przełożonego ─────────────────────────────────────────

#: Rodzaje planowe — ich rodzaj widzi i o nich decyduje także zastępca
#: przełożonego, który jest dziś na urlopie. Pozostałe (L4, urlop opiekuńczy
#: z powodów medycznych, siła wyższa z powodu choroby lub wypadku, macierzyński,
#: oddanie krwi) mówią o zdrowiu osoby albo jej bliskich: zastępca nie należy do
#: kręgu D6, widzi „Nieobecność” i tylko przyjmuje do wiadomości — decyduje
#: przełożony po powrocie albo Kadry.
SUBSTITUTE_VISIBLE_TYPES: frozenset[str] = frozenset(
    {
        "vacation",
        "on_demand",
        "occasional",
        "childcare",
        "paternity",
        "parental_leave",
        "childrearing",
        "unpaid_leave",
        "training",
        "holiday_in_lieu",
        "other",
    }
)

assert SUBSTITUTE_VISIBLE_TYPES <= set(LEAVE_TYPES)
assert not SUBSTITUTE_VISIBLE_TYPES & HEALTH_TYPES

SUBSTITUTE_ACK_ONLY = (
    "O tej nieobecności decyduje przełożony albo Kadry — w zastępstwie "
    "przyjmujesz ją tylko do wiadomości."
)


def substitute_sees_type(leave_type: str) -> bool:
    return leave_type in SUBSTITUTE_VISIBLE_TYPES


def covering_manager(
    actor_id: int,
    *,
    subject_user_id: int,
    subject_manager_id: Optional[int],
    covered_manager_ids: Iterable[int],
) -> Optional[int]:
    """Za kogo ``actor_id`` decyduje w zastępstwie (``None`` = nie zastępuje).

    ``covered_manager_ids`` to przełożeni, których osoba zastępuje dziś (jest
    zastępcą w ich zatwierdzonym urlopie). Zakres to wyłącznie podwładni
    nieobecnego przełożonego — nie on sam i nie osoba zastępująca.
    """

    if actor_id == subject_user_id or subject_manager_id is None:
        return None
    if subject_manager_id == actor_id:
        return None
    return (
        subject_manager_id if subject_manager_id in set(covered_manager_ids) else None
    )


def own_cancel_refusal(
    *, status: str, start: date, today: date, reported: bool = False
) -> Optional[str]:
    """Powód, dla którego osoba NIE może sama anulować wniosku (None = może).

    Oczekujący i zatwierdzony — tylko przed pierwszym dniem (``today`` =
    ``business_today()``: Compass liczył „dziś” w UTC i wieczorem pozwalał
    anulować urlop, który zaczął się o północy w Warszawie). Od pierwszego dnia
    osoba faktycznie była nieobecna, więc cofa to przełożony albo Kadry — także
    niezatwierdzony wniosek (decyzja Artura 28.10.2026).
    ``reported`` — zgłoszenie z B2B albo zlecenia (D5): trwające anulują Kadry,
    koordynator nie (anulowanie przez niego to odrzucenie pod inną nazwą).
    """

    if status == "pending":
        if start > today:
            return None
        return (
            "Ten wniosek dotyczy terminu, który już trwa albo minął — anulować "
            "albo odrzucić go może przełożony albo Kadry."
        )
    if status == "approved":
        if start > today:
            return None
        if reported:
            return "Ten termin już trwa albo minął — anulować go mogą Kadry."
        return "Ten urlop już trwa albo minął — anulować go może przełożony albo Kadry."
    return "Ten wniosek jest już zamknięty."


def team_cancel_refusal(*, status: str) -> Optional[str]:
    if status in ("pending", "approved"):
        return None
    return "Ten wniosek jest już zamknięty."


CANCEL_REASON_MIN = 3
CANCEL_REASON_MAX = 500
# Powód w treści dymka osoby; mail ucina treść przed nim (``hr_mail``).
CANCEL_REASON_LABEL = "Powód: "


def approver_cancel_refusal(
    *, start: date, today: date, reason: Optional[str]
) -> Optional[str]:
    """Powód cofnięcia przez przełożonego albo Kadry (None = w porządku).

    Od pierwszego dnia (``start <= today``) powód jest wymagany: dni wracają
    do raportu godzin i statów, a osoba dostaje go w powiadomieniu (decyzja
    Artura 28.10.2026). Przed pierwszym dniem — opcjonalny. ``reason`` już
    przycięty albo surowy; puste = brak.
    """

    text = (reason or "").strip()
    if not text:
        if start > today:
            return None
        return (
            "Ten termin już trwa albo minął — podaj powód cofnięcia, osoba "
            "zobaczy go w powiadomieniu."
        )
    if len(text) < CANCEL_REASON_MIN:
        return f"Powód musi mieć co najmniej {CANCEL_REASON_MIN} znaki."
    if len(text) > CANCEL_REASON_MAX:
        return f"Powód może mieć najwyżej {CANCEL_REASON_MAX} znaków."
    return None


FORWARD_OUTSIDE_COMPANY = (
    "Przekierowanie poczty działa tylko na adres w domenie firmy — "
    "wybrany zastępca ma adres spoza niej."
)


def forward_target_allowed(
    address: Optional[str], company_domains: Iterable[str]
) -> bool:
    """Adres zastępcy w jednej z domen firmy (``SSO_ALLOWED_DOMAINS``).

    Bez skonfigurowanych domen nie ma z czym porównać (lokalnie, testy) — tak
    samo filtr reguły nie wyklucza wtedy żadnej domeny firmy. Na produkcji lista
    jest ustawiona, bo przez nią wpuszcza logowanie Microsoft.
    """

    domains = {d.strip().lower().lstrip("@") for d in company_domains if d.strip()}
    if not domains:
        return True
    if not address or "@" not in address:
        return False
    return address.rsplit("@", 1)[1].strip().lower() in domains


def overlapping(
    ranges: Iterable[tuple[date, date]], start: date, end: date
) -> Optional[tuple[date, date]]:
    """Pierwszy zakres, który nachodzi na ``[start, end]`` (włącznie)."""

    for other_start, other_end in ranges:
        if other_start <= end and other_end >= start:
            return other_start, other_end
    return None
