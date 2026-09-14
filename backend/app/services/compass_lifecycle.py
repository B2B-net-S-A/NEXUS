"""Cykl życia pracownika: COMPASS → NEXUS (Etap 5).

COMPASS jest źródłem prawdy o zatrudnieniu — ``employment_status = 'exited'``
odbiera tam dostęp natychmiast, w trzech warstwach. NEXUS flipuje
``users.is_active`` RĘCZNIE (``/api/admin`` → soft-delete), więc konto osoby,
która odeszła, bywa aktywne jeszcze długo po ostatnim dniu pracy.

Skala jest dziś mała i to jest argument ZA zrobieniem tego teraz: 43 aktywnych,
2 ``offboarding``, 1 ``exited``, wszyscy na ``@b2bnetwork.pl``. Join po e-mailu
jest więc poprawny dla 100% rekordów — ale nie będzie: migracja domenowa jest
w toku (konta ``@inframinds.eu`` już istnieją, dziś nieaktywne). Dlatego sync
raportuje niedopasowanych w OBIE strony, tak jak D5.

CZTERY REGUŁY, KTÓRE TRZYMAJĄ TO BEZPIECZNYM
--------------------------------------------
1. **Tylko ``exited`` deaktywuje.** ``offboarding`` NIE — COMPASS sam
   przepuszcza ten status wszędzie, bo offboarding trwa po ostatnim dniu pracy
   i człowiek wciąż musi się zalogować. Traktowanie go jak odejścia odcięłoby
   ludzi w trakcie przekazywania obowiązków.

2. **Deaktywacja jest JEDNOKIERUNKOWA — nigdy nie włączamy konta z powrotem.**
   Odebranie dostępu na podstawie cudzego feedu jest odwracalne jednym
   kliknięciem admina; NADANIE dostępu automatem na podstawie feedu, który
   może być nieaktualny albo częściowy, jest zupełnie inną klasą zdarzenia.
   Powrót do pracy to decyzja człowieka.

3. **Nie ruszamy rankingów wypłacających nagrody.** Filtr ``is_active`` w
   ``competitions.py`` zostaje: wykluczanie osób, które odeszły, z NAGRÓD jest
   polityką, nie błędem. Historia firmy jest bezpieczna niezależnie —
   ``kpi_team`` od 2026-08-13 zachowuje nieaktywnych z dorobkiem w oknie, więc
   deaktywacja nie kurczy już sum firmowych.

4. **Konta bez odpowiednika w COMPASSIE zostają nietknięte.** Nieobecność
   w feedzie nie jest dowodem odejścia — może znaczyć „inna domena",
   „konto serwisowe człowieka" albo „COMPASS przysłał niepełną listę".
   Deaktywacja wymaga JAWNEGO ``exited``, nie ciszy.

5. **Osoba ``exited`` nie zachowuje dostępu — chyba że admin JAWNIE przywrócił
   konto W TYM epizodzie odejścia.** Aktywne konto osoby ``exited`` jest
   deaktywowane przy każdym przebiegu, z jednym wyjątkiem: ręczne włączenie
   przez admina (``Activity`` ``active_changed`` z ``to=True`` z
   ``PUT /api/admin/users/{id}``) NOWSZE niż początek bieżącego epizodu
   odejścia — np. osoba wróciła na umowę, której COMPASS jeszcze nie
   odnotował. Włączenia, które takiego śladu nie zostawiają (logowanie SSO
   z grupą AAD, resync grup AAD przez admina), się nie liczą: następny
   przebieg wyłącza konto ponownie, bo o odejściach decyduje COMPASS.
   Późniejsza jawna deaktywacja przez admina (``active_changed`` na ``False``
   albo ``user_deactivated``) unieważnia wcześniejsze włączenie.

   Początek epizodu to chwila, w której pętla ZOBACZYŁA zmianę statusu na
   ``exited`` (zapisywana per konto w ``app_settings['compass_lifecycle_state']``).
   Przy pierwszej obserwacji konta (brak zapisanego stanu) początkiem jest
   ostatnia deaktywacja tą pętlą (``compass_lifecycle_deactivated``), a gdy
   takiej nie ma — chwila przebiegu. Pętla sprzed 09.2026 NIE zostawiała
   żadnego śladu deaktywacji, więc włączenie sprzed wdrożenia tej reguły nie
   ma się do czego odnieść i nie chroni konta — decyzja admina podjęta po
   pierwszym przebiegu jest honorowana do końca epizodu. Dzięki temu włączenie z 2025
   nie chroni przed odejściem w 2026, a flip SSO po deaktywacji nie przywraca
   dostępu. Każda deaktywacja zostawia wpis ``Activity``
   (``compass_lifecycle_deactivated``).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.user import User

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20.0

# Dolny próg odstępu pętli (`compass_lifecycle_sync_loop` clampuje do niego).
# Trzymany TU, bo sonda `/api/health` liczy z niego próg świeżości — dwie
# kopie tej liczby rozjechałyby się przy pierwszej zmianie jednej z nich.
MIN_INTERVAL_SECONDS = 900

# Jedyny status, który odbiera dostęp. Lista jest jawna i jednoelementowa
# CELOWO — „wszystko poza active" wciągnęłoby `offboarding`.
_DEACTIVATING_STATUSES = frozenset({"exited"})

# Stan pętli per konto NEXUSA (klucz: `users.id` jako tekst): ostatnio widziany
# status COMPASSA i — dla kont `exited` — początek bieżącego epizodu odejścia.
# Wiersz `app_settings`, bez migracji — to stan pętli, nie konfiguracja.
_STATE_KEY = "compass_lifecycle_state"
_STATE_VERSION = 2

# Akcja zapisywana przy każdej deaktywacji — i szukana jako ślad w audycie.
DEACTIVATION_ACTION = "compass_lifecycle_deactivated"

# Jawne, per-użytkownik decyzje admina o aktywności konta. `active_changed`
# zapisuje wyłącznie `PUT /api/admin/users/{id}`, `user_deactivated` —
# `DELETE /api/admin/users/{id}`. Logowanie SSO i resync grup AAD przestawiają
# `is_active` bez tych wpisów, więc nie są decyzją admina w rozumieniu pętli.
_ADMIN_REENABLE_ACTION = "active_changed"
_ADMIN_ACTIVITY_DECISIONS = (_ADMIN_REENABLE_ACTION, "user_deactivated")


@dataclass
class LifecycleSyncResult:
    """Wynik przebiegu — z jawnym rachunkiem tego, czego NIE zrobiono."""

    people_received: int = 0
    matched_users: int = 0
    deactivated: list[str] = field(default_factory=list)
    already_inactive: int = 0
    # `exited` w COMPASSIE, a konto aktywne, bo admin włączył je ŚWIADOMIE
    # w tym epizodzie odejścia — w wyniku z adresem, żeby ktoś mógł to
    # zweryfikować, ale nie ruszane. Log przebiegu niesie wyłącznie liczbę
    # i identyfikatory (`skipped_reenabled_user_ids`): te konta wracają
    # w KAŻDYM przebiegu, a adres e-mail nie ma powodu lądować w logach co 6 h.
    skipped_reenabled: list[str] = field(default_factory=list)
    skipped_reenabled_user_ids: list[int] = field(default_factory=list)
    unmatched_compass_emails: list[str] = field(default_factory=list)
    nexus_users_without_compass: list[str] = field(default_factory=list)
    error: str | None = None

    def as_payload(self) -> dict:
        return {
            "people_received": self.people_received,
            "matched_users": self.matched_users,
            # Adresy, nie tylko liczba: bez nich nie da się naprawić
            # konkretnego przypadku ani sprawdzić, czy deaktywacja była trafna.
            "deactivated": sorted(self.deactivated),
            "already_inactive": self.already_inactive,
            "skipped_reenabled": sorted(self.skipped_reenabled),
            "skipped_reenabled_user_ids": sorted(self.skipped_reenabled_user_ids),
            "unmatched_compass_emails": sorted(self.unmatched_compass_emails),
            "nexus_users_without_compass": sorted(self.nexus_users_without_compass),
            "error": self.error,
        }


def _parse_timestamp(raw: object) -> Optional[datetime]:
    """ISO z zapisanego stanu → świadomy strefy `datetime` (albo `None`)."""
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


async def _load_state(db) -> tuple[dict[str, str], dict[str, datetime]]:
    """Stan z poprzedniego przebiegu: ostatnie statusy i początki epizodów odejścia.

    Pusty słownik = brak obserwacji. Stan w wersji 1 (sprzed zapisu początku
    epizodu) nie ma ``exit_since`` — takie konto traktujemy jak pierwszą
    obserwację (patrz :func:`_exit_episode_start`).
    """
    row = await db.get(AppSetting, _STATE_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    seen = value.get("last_seen")
    last_seen = (
        {str(k): str(v) for k, v in seen.items() if v is not None}
        if isinstance(seen, dict)
        else {}
    )
    raw_since = value.get("exit_since")
    exit_since: dict[str, datetime] = {}
    if isinstance(raw_since, dict):
        for key, raw in raw_since.items():
            parsed = _parse_timestamp(raw)
            if parsed is not None:
                exit_since[str(key)] = parsed
    return last_seen, exit_since


async def _save_state(
    db, last_seen: dict[str, str], exit_since: dict[str, datetime]
) -> None:
    """Zapis stanu jako UPSERT.

    Dwa kontenery nakładające się w trakcie deployu Coolify potrafią przejść
    przez pętlę jednocześnie — ``SELECT`` + ``INSERT`` dawał wtedy
    ``IntegrityError`` na kluczu głównym i przebieg padał po deaktywacjach,
    ale przed commitem. ``ON CONFLICT (key) DO UPDATE`` rozstrzyga to w bazie:
    wygrywa ostatni zapis, a oba liczyły stan z tego samego feedu.
    """
    payload = {
        "version": _STATE_VERSION,
        "last_seen": last_seen,
        "exit_since": {key: ts.isoformat() for key, ts in exit_since.items()},
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    stmt = pg_insert(AppSetting).values(key=_STATE_KEY, value=payload)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": stmt.excluded.value, "updated_at": func.now()},
        )
    )


# ── Stempel ostatniego biegu (sonda `checks.compass_lifecycle`) ──────────────
#
# Do 09.2026 jedyną informacją o tej pętli w `/api/health` było
# `classify_background_tasks` → `running`. Ta pętla łyka KAŻDY wyjątek
# (`except Exception` w `compass_lifecycle_sync_loop`), a `sync_user_lifecycle`
# wraca z `fetch_failed:` i `empty_roster` normalnie, nic nie zapisawszy —
# więc niedostępny COMPASS był nie do odróżnienia od zdrowej instalacji, a
# osoba `exited` zachowywała dostęp dokładnie tak długo, jak długo nikt nie
# czytał logów. Stempel żyje w TYM SAMYM wierszu `app_settings`, co stan
# epizodów odejścia (bez migracji); `_save_state` przepisuje wiersz w całości
# i jest wołane wyłącznie na ścieżce sukcesu, a `record_sync_outcome`
# dopisuje klucze scaleniem (`||`), więc padnięty bieg nie kasuje `last_seen`.

_STAMP_UPSERT = text(
    """
    INSERT INTO app_settings (key, value, updated_at)
    VALUES (:key, CAST(:patch AS jsonb), NOW())
    ON CONFLICT (key) DO UPDATE SET
        value = app_settings.value || EXCLUDED.value,
        updated_at = NOW()
    """
)


def public_error_kind(
    result_error: Optional[str], exc: BaseException | None = None
) -> str:
    """Kod błędu do stempla — bez treści wyjątku.

    `LifecycleSyncResult.error` niesie `fetch_failed: <str(exc)>`, a `str`
    wyjątku httpx zawiera URL, a bywa, że i fragment odpowiedzi. Do
    `app_settings` (czytanego przez `/api/health` i przegląd admina) idzie
    wyłącznie kod przed dwukropkiem i NAZWA KLASY wyjątku — to wystarcza, żeby
    odróżnić timeout od 401, a nie niesie niczego z cudzego feedu.
    """
    code = (result_error or "unknown").split(":", 1)[0].strip() or "unknown"
    if exc is not None:
        return f"{code} ({type(exc).__name__})"
    return code


async def record_sync_outcome(
    db,
    *,
    ok: bool,
    error: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Dopisz do stanu pętli wynik biegu: `last_run_at`, `last_status`,
    `last_error` i — tylko przy sukcesie — `last_success_at`.

    Scalenie, nie zamiana: ten wiersz niesie też `last_seen`/`exit_since`
    (początki epizodów odejścia), których błąd pobrania nie ma prawa skasować.
    Commit własny — wołające ścieżki awaryjne nic innego nie zapisują.
    """
    stamp_at = (now or datetime.now(timezone.utc)).isoformat()
    patch: dict[str, object] = {
        "last_run_at": stamp_at,
        "last_status": "ok" if ok else "error",
        "last_error": None if ok else (error or "unknown"),
    }
    if ok:
        patch["last_success_at"] = stamp_at
    await db.execute(_STAMP_UPSERT, {"key": _STATE_KEY, "patch": json.dumps(patch)})
    await db.commit()


def lifecycle_sync_verdict(
    state: Optional[dict],
    *,
    interval_seconds: int,
    now: datetime,
) -> str:
    """``"healthy"`` albo ``"degraded"`` dla ``checks.compass_lifecycle``.

    Czysta funkcja — lustro `workdays_sync_verdict`: wersja wpleciona
    w handler daje się testować wyłącznie przez gałąź `except`.

    `healthy` wymaga DWÓCH rzeczy naraz: ostatni bieg zakończył się `ok`
    (padnięty bieg degraduje od razu, nawet przy świeżym sukcesie sprzed
    godziny — to sygnał, że COMPASS właśnie przestał odpowiadać) ORAZ ostatni
    sukces nie jest starszy niż dwa odstępy pętli (jeden spóźniony bieg,
    np. przez deploy w trakcie, nie alarmuje; dwa z rzędu — tak). Odstęp
    liczony z tego samego clampu co pętla, żeby literówka w env nie dała
    progu 2 min.
    """
    if not isinstance(state, dict):
        return "degraded"
    if state.get("last_status") != "ok":
        return "degraded"
    last_success = _parse_timestamp(state.get("last_success_at"))
    if last_success is None:
        return "degraded"
    interval = max(int(interval_seconds), MIN_INTERVAL_SECONDS)
    if (now - last_success) > timedelta(seconds=2 * interval):
        return "degraded"
    return "healthy"


async def _latest_lifecycle_deactivation(db, user_id: int) -> Optional[datetime]:
    """Kiedy ta pętla ostatnio wyłączyła konto (``compass_lifecycle_deactivated``).

    Pętla sprzed 09.2026 ustawiała wyłącznie ``is_active = False`` — bez
    ``Activity`` ani innego znacznika — więc jej deaktywacje nie mają śladu,
    do którego dałoby się tu sięgnąć.
    """
    return await db.scalar(
        select(func.max(Activity.created_at)).where(
            Activity.entity_type == "user",
            Activity.entity_id == user_id,
            Activity.action == DEACTIVATION_ACTION,
        )
    )


async def _exit_episode_start(
    db,
    user_id: int,
    *,
    previous: Optional[str],
    stored: Optional[datetime],
    observed_at: datetime,
) -> datetime:
    """Początek bieżącego epizodu odejścia tego konta.

    - COMPASS mówił ``exited`` już poprzednio → epizod trwa od zapisanej chwili;
    - poprzednio inny status → epizod zaczyna się TERAZ (pętla właśnie
      zobaczyła zmianę na ``exited``);
    - pierwsza obserwacja (albo stan bez zapisanego początku) → ostatnia
      deaktywacja tą pętlą, a gdy jej nie ma — chwila przebiegu.
    """
    if previous in _DEACTIVATING_STATUSES and stored is not None:
        return stored
    if previous is not None and previous not in _DEACTIVATING_STATUSES:
        return observed_at
    return await _latest_lifecycle_deactivation(db, user_id) or observed_at


async def _admin_reenabled_since(db, user_id: int, episode_start: datetime) -> bool:
    """Czy admin JAWNIE włączył to konto po początku bieżącego epizodu odejścia.

    Liczy się wyłącznie OSTATNIA jawna decyzja admina o aktywności konta
    (``active_changed`` z ``PUT /api/admin/users/{id}`` albo ``user_deactivated``
    z ``DELETE``): musi być włączeniem (``details.to is True``) i być nowsza niż
    ``episode_start``. Włączenie sprzed odejścia nie jest decyzją o TYM
    odejściu, a włączenie odwołane późniejszą deaktywacją admina — nie jest
    decyzją w ogóle. Flipy bez takiego śladu (SSO, resync AAD) nie liczą się.
    """
    latest: Optional[Activity] = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "user",
            Activity.entity_id == user_id,
            Activity.action.in_(_ADMIN_ACTIVITY_DECISIONS),
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(1)
    )
    if latest is None or latest.action != _ADMIN_REENABLE_ACTION:
        return False
    details = latest.details
    if not (isinstance(details, dict) and details.get("to") is True):
        return False
    return latest.created_at > episode_start


async def fetch_roster() -> dict:
    """Pobiera listę osób z COMPASSA.

    Sekret leci NAGŁÓWKIEM, nigdy w query stringu — te lądują w logach
    dostępowych pośredników, a ten sekret ma żyć długo (lustro decyzji z D5).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(
            settings.COMPASS_LIFECYCLE_URL,
            headers={"Authorization": f"Bearer {settings.COMPASS_LIFECYCLE_SECRET}"},
        )
        response.raise_for_status()
        return response.json()


async def sync_user_lifecycle(db) -> LifecycleSyncResult:
    """Deaktywuje w NEXUSIE konta osób, które w COMPASSIE mają ``exited``."""
    result = LifecycleSyncResult()

    if not settings.COMPASS_LIFECYCLE_ENABLED:
        result.error = "disabled"
        return result
    if not (settings.COMPASS_LIFECYCLE_URL and settings.COMPASS_LIFECYCLE_SECRET):
        result.error = "unconfigured"
        return result

    try:
        payload = await fetch_roster()
    except Exception as exc:  # noqa: BLE001 — awaria COMPASSA nie jest nasza
        result.error = f"fetch_failed: {exc}"
        logger.warning("compass_lifecycle fetch failed: %s", exc)
        await record_sync_outcome(
            db, ok=False, error=public_error_kind(result.error, exc)
        )
        return result

    people = payload.get("people") or []
    result.people_received = len(people)

    # Pusta lista NIE jest sygnałem „wszyscy odeszli" — jest sygnałem, że coś
    # jest nie tak po drugiej stronie. Bez tego bezpiecznika awaria eksportu
    # w COMPASSIE deaktywowałaby dokładnie zero osób (bo nic nie ma statusu
    # `exited`), ale każdy żywy user trafiłby na listę „bez odpowiednika" —
    # a to jest wtedy szum, nie informacja.
    if not people:
        result.error = "empty_roster"
        await record_sync_outcome(db, ok=False, error=public_error_kind(result.error))
        return result

    by_email: dict[str, str] = {}
    for person in people:
        email = (person.get("email") or "").strip().lower()
        if email:
            by_email[email] = (person.get("employment_status") or "").strip().lower()

    users = (await db.execute(select(User))).scalars().all()
    nexus_emails = {(u.email or "").strip().lower() for u in users if u.email}

    for email in by_email:
        if email not in nexus_emails:
            result.unmatched_compass_emails.append(email)

    # Zegar BAZY, nie aplikacji: z nim porównujemy `Activity.created_at`
    # (server_default `now()`), więc obie strony porównania biorą czas z tego
    # samego źródła.
    observed_at: datetime = await db.scalar(select(func.now()))
    last_seen, exit_since = await _load_state(db)
    for user in users:
        email = (user.email or "").strip().lower()
        status = by_email.get(email)
        if status is None:
            # Tylko AKTYWNI są raportowani jako „bez odpowiednika" — konto
            # dawno wyłączone nie jest problemem do rozwiązania. Ostatnia
            # obserwacja zostaje: nieobecność w feedzie nie jest statusem.
            if user.is_active:
                result.nexus_users_without_compass.append(email or f"#{user.id}")
            continue

        result.matched_users += 1
        key = str(user.id)
        previous = last_seen.get(key)
        last_seen[key] = status
        if status not in _DEACTIVATING_STATUSES:
            # Epizod odejścia (jeśli był) się skończył — kolejne `exited` będzie
            # NOWYM odejściem i włączenie admina sprzed niego nie będzie się liczyć.
            exit_since.pop(key, None)
            continue

        episode_start = await _exit_episode_start(
            db,
            user.id,
            previous=previous,
            stored=exit_since.get(key),
            observed_at=observed_at,
        )
        exit_since[key] = episode_start
        if not user.is_active:
            result.already_inactive += 1
            continue
        if await _admin_reenabled_since(db, user.id, episode_start):
            # Admin włączył konto świadomie PO początku tego odejścia (np. powrót
            # na umowę, której COMPASS jeszcze nie zna) — zostaje włączone.
            result.skipped_reenabled.append(email)
            result.skipped_reenabled_user_ids.append(user.id)
            continue

        user.is_active = False
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action=DEACTIVATION_ACTION,
                user_id=None,
                details={
                    "target_email": email,
                    "compass_status": status,
                    "previous_compass_status": previous,
                    "exit_episode_started_at": episode_start.isoformat(),
                    "source": "compass_lifecycle_sync",
                },
            )
        )
        result.deactivated.append(email)

    # Stan zapisujemy przy KAŻDYM udanym przebiegu — to on niesie początek
    # epizodu odejścia, do którego porównujemy włączenia admina.
    # Kolejność load-bearing: `_save_state` ZASTĘPUJE całą wartość wiersza,
    # a `record_sync_outcome` dokleja stemple scaleniem jsonb — odwrotna
    # kolejność kasowałaby `last_run_at`/`last_status` przy każdym czystym biegu.
    await _save_state(db, last_seen, exit_since)
    await db.commit()
    # Stempel sukcesu PO commicie stanu — bieg, który padł na zapisie epizodów,
    # nie może raportować `ok` (wyjątek stąd łapie pętla i stempluje błąd).
    await record_sync_outcome(db, ok=True)
    if result.deactivated:
        logger.info(
            "compass_lifecycle deactivated=%s emails=%s",
            len(result.deactivated),
            sorted(result.deactivated),
        )
    if result.skipped_reenabled_user_ids:
        # Te konta wracają w KAŻDYM przebiegu — tylko liczba i identyfikatory.
        logger.info(
            "compass_lifecycle kept_reenabled=%s user_ids=%s",
            len(result.skipped_reenabled_user_ids),
            sorted(result.skipped_reenabled_user_ids),
        )

    return result


__all__ = [
    "DEACTIVATION_ACTION",
    "MIN_INTERVAL_SECONDS",
    "LifecycleSyncResult",
    "fetch_roster",
    "lifecycle_sync_verdict",
    "public_error_kind",
    "record_sync_outcome",
    "sync_user_lifecycle",
]
