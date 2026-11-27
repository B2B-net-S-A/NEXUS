"""Poligon dla obecnych: tylko luki (decyzja Artura 16.11.2026).

Obecni rekruterzy nie przechodzą całego poligonu od nowa. Analiza 60 dni pracy
16 rekruterów (nocna kopia produkcji, 15.11) pokazała, że rdzeń procesu zna
każdy, a luki są różne u każdej osoby (2–11 funkcji). Dlatego:

* **Funkcje i sygnały użycia** (``FEATURES``): ważne funkcje rekrutera i to,
  po czym w bazie widać, że osoba ich użyła (dziennik ``activities``,
  ``user_activities``, notatki, przeglądy bazy...). Okno: 60 dni.
* **Zaliczenie z pracy**: kampania (HoR, ``POST /api/novelties/poligon/luki``)
  zalicza każdemu ćwiczenia poligonu z funkcji, których używa — wiersz
  ``novelty_progress`` z ``completed_via = 'used'`` („użyciem w pracy”, bez
  migracji). Lista zaliczonych z pracy leży w ustawieniu kampanii, żeby mapa
  mogła je oznaczyć „z pracy”.
* **Ćwiczenia narzędzi** (16.11.2026): osiem funkcji z luk dostało ćwiczenia
  (telefon screeningowy, termin u klienta, CV z pliku, zapisane wyszukiwanie,
  lista, czat, asystent CV, Jarvis) — kto ich używa, ma je zaliczone z pracy.
* **Termin**: do terminu poligon tylko prosi; po terminie blokuje jak u nowej
  osoby (ten sam wyłącznik ``poligon_gate``). Dzień ćwiczeń nie wypada ze
  statystyk — to kilkanaście–kilkadziesiąt minut, nie dzień.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User

#: Ustawienie kampanii w ``app_settings``.
LUKI_KEY = "poligon_luki"
#: Okno pracy, z której liczymy użycie funkcji.
WINDOW_DAYS = 60
#: Domyślny termin kampanii (dni kalendarzowe od startu).
DEFAULT_DUE_DAYS = 7
#: Role, którym kampania nie dotyczy, nawet jeśli mają też rolę rekrutera.
_LEADER_ROLES = {"admin", "head_of_recruitment"}

#: Ćwiczenia listy rekrutacji zalicza każdy, kto w ogóle pracuje w NEXUSIE.
_LIST_EXERCISES = (
    "poligon-lista-zakres",
    "poligon-lista-filtry",
    "poligon-lista-otworz",
)


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    group: str
    #: Ćwiczenia poligonu, które ta funkcja zalicza z pracy.
    exercises: tuple[str, ...]
    #: Zapytanie: wiersze ``(user_id)`` osób, które użyły funkcji od ``:since``.
    sql: str


def _act(action: str) -> str:
    return (
        "SELECT user_id FROM activities WHERE user_id = ANY(:ids) "
        f"AND created_at > :since AND action = '{action}'"
    )


FEATURES: tuple[Feature, ...] = (
    Feature(
        "tablica_ruch",
        "Ruch karty na Tablicy",
        "Rdzeń procesu",
        ("poligon-tablica-przesun",),
        _act("stage_changed"),
    ),
    Feature(
        "biore",
        "„Biorę”",
        "Rdzeń procesu",
        ("poligon-tablica-biore",),
        _act("candidate_claimed"),
    ),
    Feature(
        "screening",
        "Formularz screeningu",
        "Rdzeń procesu",
        ("poligon-screening-otworz", "poligon-screening-zapisz"),
        _act("screening_form_saved"),
    ),
    Feature(
        "zweryfikowany",
        "„Przygotowanie CV” przez bramkę",
        "Rdzeń procesu",
        ("poligon-screening-bramka", "poligon-screening-zweryfikuj"),
        _act("stage_changed") + " AND details::jsonb->>'stage' = 'verified'",
    ),
    Feature(
        "karta_rekomendacji",
        "„Dlaczego ten kandydat”",
        "Rdzeń procesu",
        (),
        _act("recommendation_card_updated"),
    ),
    Feature(
        "odrzucenie",
        "Odrzucenie z powodem",
        "Rdzeń procesu",
        ("poligon-panel-odrzuc",),
        "SELECT moved_by FROM candidate_stages WHERE moved_by = ANY(:ids) "
        "AND stage = 'rejected' AND moved_at > :since "
        "AND rejection_reason_id IS NOT NULL",
    ),
    Feature(
        "stawka",
        "Zmiana stawki w procesie",
        "Rdzeń procesu",
        (),
        _act("candidate_rate_change_requested"),
    ),
    Feature(
        "cv_klient",
        "CV dla klienta",
        "Rdzeń procesu",
        ("poligon-rekomendacja-cv",),
        "SELECT user_id FROM activities WHERE user_id = ANY(:ids) "
        "AND created_at > :since "
        "AND action IN ('b2b_cv_generated', 'branded_cv_finalized')",
    ),
    Feature(
        "qc_cv",
        "QC CV",
        "Rdzeń procesu",
        ("poligon-rekomendacja-qc",),
        _act("cv_qc_confirmed"),
    ),
    Feature(
        "notatka",
        "Notatka po rozmowie",
        "Kandydaci i źródła",
        ("poligon-panel-notatka",),
        "SELECT user_id FROM user_activities WHERE user_id = ANY(:ids) "
        "AND created_at > :since AND action_type = 'note_added'",
    ),
    Feature(
        "skrzynka",
        "Skrzynka propozycji",
        "Kandydaci i źródła",
        ("poligon-tablica-zrodla",),
        _act("proposal_inbox_opened"),
    ),
    Feature(
        "przeglad_bazy",
        "Przegląd całej bazy",
        "Kandydaci i źródła",
        ("poligon-baza-szukaj",),
        "SELECT created_by FROM candidate_search_runs "
        "WHERE created_by = ANY(:ids) AND created_at > :since",
    ),
    Feature(
        "przypisanie",
        "Przypisanie z bazy",
        "Kandydaci i źródła",
        ("poligon-baza-profil", "poligon-baza-przypisz"),
        "SELECT user_id FROM user_activities WHERE user_id = ANY(:ids) "
        "AND created_at > :since AND action_type = 'candidate_added'",
    ),
    Feature(
        "cv_z_pliku",
        "Nowa osoba z pliku CV",
        "Kandydaci i źródła",
        ("poligon-zrodla-cv-z-pliku",),
        _act("created_from_cv"),
    ),
    Feature(
        "moi_ludzie",
        "Decyzja w „Moi ludzie”",
        "Kandydaci i źródła",
        ("poligon-tablica-moi-ludzie",),
        "SELECT user_id FROM my_people_overrides "
        "WHERE user_id = ANY(:ids) AND created_at > :since",
    ),
    Feature(
        "zapisane_wyszukiwanie",
        "Zapisane wyszukiwanie z alertem",
        "Kandydaci i źródła",
        ("poligon-baza-zapisane-wyszukiwanie",),
        "SELECT user_id FROM saved_searches WHERE user_id = ANY(:ids)",
    ),
    Feature(
        "pula",
        "Pula talentów",
        "Kandydaci i źródła",
        ("poligon-baza-lista",),
        "SELECT added_by FROM talent_pool_memberships "
        "WHERE added_by = ANY(:ids) AND added_at > :since "
        "AND coalesce(source_event, '') NOT LIKE '%auto%'",
    ),
    Feature(
        "screening_kalendarz",
        "Screening w kalendarzu",
        "Klient i kalendarz",
        ("poligon-kalendarz-telefon",),
        _act("screening_call_booked"),
    ),
    Feature(
        "terminy_klient",
        "Terminy rozmowy u klienta",
        "Klient i kalendarz",
        # Funkcja ma dwie strony: DL wpisuje terminy (``created_by``), rekruter
        # wybiera z kandydatem (``recruiter_id``). Użycie którejkolwiek zalicza
        # ćwiczenie tej strony, która jest na ścieżce osoby (16.11.2026).
        ("poligon-kalendarz-termin-klienta", "poligon-dl-terminy-klienta"),
        "SELECT v.uid FROM client_interview_slot_requests r, "
        "LATERAL (VALUES (r.recruiter_id), (r.created_by)) AS v(uid) "
        "WHERE v.uid = ANY(:ids) AND r.created_at > :since",
    ),
    Feature(
        "dostepnosc",
        "Dostępność i tryb pracy",
        "Klient i kalendarz",
        (),
        "SELECT user_id FROM activities WHERE user_id = ANY(:ids) "
        "AND created_at > :since AND action IN "
        "('candidate_availability_changed', 'candidate_work_mode_changed')",
    ),
    Feature(
        "wzmianka",
        "Wzmianka „@”",
        "Zespół i AI",
        ("poligon-panel-wzmianka",),
        "SELECT n.author_id FROM note_mentions m JOIN notes n ON n.id = m.note_id "
        "WHERE n.author_id = ANY(:ids) AND m.created_at > :since",
    ),
    Feature(
        "czat",
        "Czat rekrutacji",
        "Zespół i AI",
        ("poligon-zespol-czat",),
        "SELECT author_id FROM job_chat_messages "
        "WHERE author_id = ANY(:ids) AND created_at > :since",
    ),
    Feature(
        "polecenie_ai_cv",
        "Polecenie AI w CV",
        "Zespół i AI",
        ("poligon-zespol-cv-ai",),
        _act("cv_command_ai"),
    ),
    Feature(
        "jarvis",
        "Jarvis",
        "Zespół i AI",
        ("poligon-zespol-jarvis",),
        "SELECT user_id FROM jarvis_conversations "
        "WHERE user_id = ANY(:ids) AND created_at > :since",
    ),
)

_BY_KEY = {f.key: f for f in FEATURES}


def usage_sql() -> str:
    """Jedno zapytanie: ``(feature, user_id)`` dla każdej użytej funkcji."""
    parts = [
        f"SELECT DISTINCT '{f.key}' AS feature, x.uid AS user_id "
        f"FROM ({f.sql}) AS x(uid) WHERE x.uid IS NOT NULL"
        for f in FEATURES
    ]
    return "\nUNION ALL\n".join(parts)


async def feature_usage(
    db: AsyncSession, user_ids: Iterable[int], now: datetime
) -> dict[int, set[str]]:
    """Funkcje użyte przez każdą osobę w oknie ``WINDOW_DAYS``."""
    ids = sorted({int(u) for u in user_ids})
    out: dict[int, set[str]] = {uid: set() for uid in ids}
    if not ids:
        return out
    rows = await db.execute(
        text(usage_sql()), {"ids": ids, "since": now - timedelta(days=WINDOW_DAYS)}
    )
    for feature, uid in rows.all():
        out.setdefault(int(uid), set()).add(str(feature))
    return out


def credited_exercises(used: set[str], path: Iterable[str]) -> list[str]:
    """Ćwiczenia ścieżki osoby, które zalicza jej praca."""
    allowed = list(path)
    credited: set[str] = set(_LIST_EXERCISES) if used else set()
    for key in used:
        feature = _BY_KEY.get(key)
        if feature:
            credited.update(feature.exercises)
    return [eid for eid in allowed if eid in credited]


def is_target(user: Any) -> bool:
    """Kogo dotyczy kampania: aktywny rekruter bez roli kierowniczej."""
    try:
        roles = {getattr(r, "value", str(r)) for r in user.get_all_roles()}
    except Exception:  # noqa: BLE001 — rola główna wystarcza jako zapas
        roles = {getattr(user.role, "value", str(user.role))}
    return bool(user.is_active) and "recruiter" in roles and not roles & _LEADER_ROLES


async def targets(db: AsyncSession) -> list[User]:
    users = (await db.execute(select(User).where(User.is_active.is_(True)))).scalars()
    return sorted(
        (u for u in users if is_target(u)), key=lambda u: (u.name or "", u.id)
    )


# ── Kampania w app_settings ────────────────────────────────────────────────


async def load_campaign(db: AsyncSession) -> Optional[dict[str, Any]]:
    row = await db.get(AppSetting, LUKI_KEY)
    if row is None or not isinstance(row.value, dict) or not row.value.get("due"):
        return None
    return row.value


def campaign_entry(
    campaign: Optional[dict[str, Any]], user_id: int
) -> Optional[dict[str, Any]]:
    """Wpis osoby w kampanii: termin i ćwiczenia zaliczone z pracy."""
    if not campaign:
        return None
    entry = (campaign.get("users") or {}).get(str(user_id))
    if entry is None:
        return None
    return {"due": campaign["due"], "credited_ids": list(entry.get("credited", []))}


def overdue(due: str, today: date) -> bool:
    """Po terminie poligon blokuje — od dnia po terminie."""
    return today > date.fromisoformat(due)


def default_due(today: date) -> date:
    return today + timedelta(days=DEFAULT_DUE_DAYS)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
