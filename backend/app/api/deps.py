import logging
from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import client_ip_key
from app.core.security import (
    decode_token,
    token_authorization_version_matches,
    token_is_revoked,
)
from app.models.service_account import ServiceScope
from app.models.user import User, UserRole
from app.services.onboarding_access import onboarding_persona_for_user
from app.services.service_account_auth import (
    API_KEY_HEADER,
    ServiceKeyError,
    ServicePrincipal,
    authenticate_api_key,
    stamp_key_usage,
)

logger = logging.getLogger(__name__)

# ``auto_error=False`` — świadomie, NIE domyślne zachowanie.
#
# ``HTTPBearer(auto_error=True)`` (default) na BRAK nagłówka ``Authorization``
# rzuca **403 Not authenticated**, nie 401. To myli dwa różne stany:
#   401 = nie wiemy kim jesteś (sesja martwa)  → frontend ma wylogować,
#   403 = wiemy kim jesteś, ale nie wolno ci   → frontend ma zostać na miejscu.
# Skutek buga: po wygaśnięciu sesji localStorage tracił token, requesty szły
# bez nagłówka, backend zwracał 403, a interceptor (który reaguje wyłącznie na
# 401 — patrz frontend/src/lib/api.ts) NIE przekierowywał na /login. Użytkownik
# zostawał w powłoce aplikacji z widgetami „Brak uprawnień do tego widoku"
# zamiast wylądować na ekranie logowania.
# Dlatego walidujemy obecność poświadczeń sami i zwracamy 401.
security = HTTPBearer(auto_error=False)

# ── Admin "podgląd jako użytkownik" (impersonation) ──────────────────────────
#
# Admin może oglądać aplikację oczami dowolnego usera (rekruter, DL, TAC…),
# żeby zobaczyć jego widok: sidebar, "moje rekrutacje", KPI, dashboardy.
# Mechanika: po normalnej autoryzacji JWT (token ZAWSZE należy do admina)
# sprawdzamy nagłówek ``X-Impersonate-User-Id``. Jeśli obecny i request
# pochodzi od admina — efektywny ``current_user`` zostaje podmieniony na
# wskazanego usera. Token się NIE zmienia; podmiana żyje wyłącznie w obrębie
# requestu, więc wszystkie filtry ``current_user.id`` i ``has_role()`` widzą
# usera podglądanego.
#
# Bezpieczeństwo:
#   • tylko admin może impersonować (inaczej 403 — anomalia, audytowalna),
#   • TYLKO ODCZYT — dozwolone metody to GET/HEAD/OPTIONS (+ POST-owe
#     wyszukiwarki, które są read-only). Każda mutacja w trybie podglądu
#     zwraca 403, żeby admin nie stworzył/nie zmienił danych „jako ktoś inny".
IMPERSONATION_HEADER = "X-Impersonate-User-Id"
_IMPERSONATION_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Read-only POST-y (wyszukiwarki) — muszą działać w trybie podglądu, bo część
# list (np. kandydaci) ładuje się przez POST /api/search/*.
_IMPERSONATION_POST_ALLOW_PREFIXES = ("/api/search",)


async def _resolve_impersonation(
    request: Request,
    admin: User,
    raw_target_id: str,
    db: AsyncSession,
) -> User:
    """Podmień efektywnego usera na podglądanego (tylko dla admina, read-only)."""
    if not admin.has_role(UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tylko administrator może oglądać widok innego użytkownika",
        )

    method = request.method.upper()
    path = request.url.path
    is_read_only = method in _IMPERSONATION_SAFE_METHODS or (
        method == "POST" and path.startswith(_IMPERSONATION_POST_ALLOW_PREFIXES)
    )
    if not is_read_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Podgląd jako użytkownik jest tylko do odczytu",
        )

    try:
        target_id = int(raw_target_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nieprawidłowy nagłówek impersonacji",
        )

    if target_id == admin.id:
        return admin

    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None or not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Użytkownik do podglądu nie istnieje lub jest nieaktywny",
        )

    # Ślad dla downstream (audyt/logi) — kto kogo podgląda w tym requeście.
    request.state.impersonator_id = admin.id
    request.state.impersonated_user_id = target.id
    return target


async def get_authenticated_user(
    request: Request,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT token and return the authenticated user.

    Gdy admin wysyła nagłówek ``X-Impersonate-User-Id`` zwracamy usera
    podglądanego (read-only) zamiast właściciela tokenu — patrz sekcja
    „podgląd jako użytkownik" powyżej.

    This raw dependency is deliberately limited to recovery/profile surfaces
    that must remain reachable before first-login onboarding: ``/auth/me``,
    ``/auth/change-password`` and the scoped onboarding read/write endpoints.
    Domain routers must use ``get_current_user``/``CurrentUser`` below.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Brak / pusty nagłówek Authorization to ten sam stan co token nie do
    # zweryfikowania: sesji nie ma. Zwracamy 401 (nie 403), żeby frontend
    # jednoznacznie wylogował — patrz komentarz przy ``security`` wyżej.
    if credentials is None or not credentials.credentials:
        raise credentials_exception

    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception

    # Session-revocation floor (F-05): token wybity przed ostatnią zmianą hasła
    # jest martwy — 401, żeby frontend wylogował (nie 403). NULL floor =
    # brak unieważnienia (istniejący userzy nie są dotknięci).
    if token_is_revoked(payload, user.tokens_valid_after):
        raise credentials_exception
    # Tokens minted before the authorization-version cutover had no ``av`` and
    # are invalid by construction. The migration starts every account at 1.
    if not token_authorization_version_matches(payload, user.authorization_version):
        raise credentials_exception

    impersonate_raw = request.headers.get(IMPERSONATION_HEADER)
    if impersonate_raw:
        return await _resolve_impersonation(request, user, impersonate_raw, db)
    return user


def ensure_exclusive_role_configuration(current_user: User) -> User:
    """Reject impossible Finance/viewer hybrids before any domain access."""
    try:
        current_user.ensure_exclusive_roles()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid_exclusive_role_configuration",
        ) from exc
    return current_user


def ensure_onboarding_complete(current_user: User) -> User:
    """Fail closed for recruiter/DL domain access until onboarding completes."""

    ensure_exclusive_role_configuration(current_user)
    if (
        onboarding_persona_for_user(current_user) is not None
        and not current_user.profile_completed
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="onboarding_required",
        )
    return current_user


async def get_current_user(
    request: Request,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate and enforce the global first-login domain boundary.

    Keeping this public dependency name preserves existing FastAPI dependency
    overrides and manual callers while making every legacy ``CurrentUser`` and
    direct ``Depends(get_current_user)`` route onboarding-aware.
    """

    current_user = await get_authenticated_user(request, credentials, db)
    return ensure_onboarding_complete(current_user)


async def require_onboarded_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Backwards-compatible named guard built on the global boundary."""

    return ensure_onboarding_complete(current_user)


OnboardedUser = Annotated[User, Depends(require_onboarded_user)]


def require_roles(*roles: UserRole):
    """Dependency factory for role-based access control.

    Since migration 0110 a user may hold multiple roles
    (``User.role`` = primary, ``User.roles`` = full set). Permission checks
    evaluate against the union via ``has_any_role`` so a hybrid
    delivery_lead+TAC user passes both ``DeliveryLeadPlus`` and ``TacPlus``.
    """

    async def _check_role(
        current_user: User = Depends(require_onboarded_user),
    ) -> User:
        # Admin jest rzeczywistym superadminem także dla guardów, które historycznie
        # omijały go przez ręczne listy ról.
        if not current_user.has_role(UserRole.admin) and not current_user.has_any_role(
            *roles
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in roles]}",
            )
        return current_user

    return _check_role


# ── Named guards (hierarchiczne "role X or higher") ──────────────────────────
#
# Hierarchia:
#   admin          (5) — pełne uprawnienia, user management
#   delivery_lead  (4) — rate cards, konflikty, pipeline templates, raporty
#   talent_community_manager — szeroki odczyt biznesowy bez finansów
#   tac            (3) — operacje sourcing/pipeline, reject/offer, prep kit
#   recruiter      (2) — dodawanie kandydatów, ruchy w pipeline
#   sourcer        (2) — dodawanie kandydatów z ATS/ogłoszeń
#   finance        — wydzielona persona finansowa

AuthenticatedUser = Annotated[User, Depends(get_authenticated_user)]
CurrentUser = Annotated[User, Depends(get_current_user)]

AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]

# Moduł „Finanse" (import miesięcznych wyników kontraktorów). Dwie ROZŁĄCZNE
# publiczności, nie suma uprawnień: CHECK `ck_users_exclusive_finance_viewer_roles`
# sprawia, że użytkownik `finance` ma wyłącznie tę rolę i nigdy nie jest
# jednocześnie adminem.
FinanceModuleUser = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.finance)),
]

DeliveryLeadPlus = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.delivery_lead)),
]

# Head of Recruitment + admin — zarządzanie strukturą zespołu rekrutacji
# (macierze sourcer×kategoria, TAC→DL, DL→klienci), edycja targetów KPI,
# zamykanie kwartałów Liga Mistrzów.
HeadOfRecruitmentPlus = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.head_of_recruitment)),
]

# Priority Work is owned by the Head of Recruitment as a business role.
# A plain administrator is not an implicit break-glass operator for plan
# publication, handoffs or KPI exceptions.
HeadOfRecruitmentOnly = Annotated[
    User,
    Depends(require_roles(UserRole.head_of_recruitment)),
]

# Priority Work demand routes deliberately exclude a plain administrator.
# Creation belongs to the current Delivery Lead; reads and updates are shared
# with the Head of Recruitment, with job ownership still checked in the
# handler for Delivery Leads.
PriorityDemandCreator = Annotated[
    User,
    Depends(require_roles(UserRole.delivery_lead)),
]

PriorityDemandReader = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
        )
    ),
]

TacPlus = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.delivery_lead, UserRole.tac)),
]

RecruiterPlus = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
            UserRole.tac,
            UserRole.recruiter,
            UserRole.finance,
            UserRole.sourcer,
        )
    ),
]

# R0 (plan analytics 2026-07-16): każdy operacyjny — czyli wszyscy poza
# wycofywanym viewerem `user`. Od 19.08 obejmuje też finance (decyzja
# produktowa: pełny dostęp operacyjny — patrz CLAUDE.md „Rola finance").
# W odróżnieniu od RecruiterPlus zawiera head_of_recruitment. Do feedów/danych
# z PII kandydatów, które nie są „bezpiecznymi agregatami", ale też nie
# wymagają konkretnej roli.
OperationalUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
            UserRole.tac,
            UserRole.recruiter,
            UserRole.finance,
            UserRole.sourcer,
        )
    ),
]

# Pending verification approval (migracja 0056) — admin + delivery_lead +
# head_of_recruitment mogą akceptować / odrzucać kandydatów na stage `verified`
# kiedy rate przekracza Job.salary_max. Recruiter który wrzucił NIE może sam
# akceptować — separation of duties.
ApproverPlus = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.head_of_recruitment,
        )
    ),
]

# Backwards-compatibility alias for routers still importing the old name.
# `ManagerOrAdmin` was the pre-RBAC guard for (manager, admin). After
# consolidation it maps to DeliveryLeadPlus (admin + delivery_lead) — same
# semantic: „privileged operations beyond regular recruiters".
ManagerOrAdmin = DeliveryLeadPlus


# ── DL Client Portal guards ──────────────────────────────────────────────────


async def require_dl_assigned_or_admin(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: Admin globalnie OR DL z `DeliveryLeadClientAssignment`.

    FastAPI inferruje ``client_id`` z path parametru routera. Inne role
    (recruiter, sourcer, tac, user) — zawsze 403.

    Reads dla MyClients/dashboard używają tego samego guarda — DL widzi
    tylko swoich klientów (admin widzi wszystkich).
    """
    from sqlalchemy import select

    from app.models.team_structure import DeliveryLeadClientAssignment

    if current_user.has_role(UserRole.admin):
        return current_user
    if not current_user.has_role(UserRole.delivery_lead):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Delivery Leads or admin may access this",
        )
    result = await db.execute(
        select(DeliveryLeadClientAssignment).where(
            DeliveryLeadClientAssignment.client_id == client_id,
            DeliveryLeadClientAssignment.delivery_lead_user_id == current_user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not assigned to this client",
        )
    return current_user


DlAssignedOrAdmin = Annotated[User, Depends(require_dl_assigned_or_admin)]


# ── Konta serwisowe / klucze API (nagłówek X-API-Key) ────────────────────────
#
# Druga, RÓWNOLEGŁA klasa poświadczeń obok JWT użytkownika. Automatyzacja
# (cron, CI, skrypt operacyjny) nie ma jak trzymać sesji: JWT żyje 8 h i umiera
# przy zmianie hasła właściciela oraz bumpie ``authorization_version``.
# Wydłużenie ``ACCESS_TOKEN_EXPIRE_MINUTES`` jest GLOBALNE, więc płaciliby za
# nie wszyscy rekruterzy w systemie z danymi kandydatów pod RODO.
#
# Dlaczego osobny nagłówek, a nie ``Authorization: Bearer``:
#
# 1. Na ``Authorization`` jadą już trzy różne poświadczenia (access JWT,
#    refresh JWT, token OAuth klienta), rozróżniane wyłącznie claimem ``type``
#    PO zdekodowaniu. Klucz API nie jest JWT, więc czwarty typ zmusiłby parser
#    do zgadywania kształtu poświadczenia przed weryfikacją — a zgadywanie
#    przed weryfikacją to dokładnie ta klasa błędu, przez którą powstają
#    pomyłki typu tokenu.
# 2. Frontend dokleja ``Authorization`` automatycznie do KAŻDEGO wywołania
#    (interceptor w ``frontend/src/lib/api.ts``, token z ``localStorage``).
#    Klucz API, który przypadkiem tam wyląduje, byłby wysyłany wszędzie —
#    także do endpointów, dla których nie ma scope'u. Osobny nagłówek nie
#    powstaje przez przypadek.
# 3. Repo ma już precedens nagłówka maszynowego: ``X-Snapshot-Token``
#    w ``/api/admin/snapshot``. Ten mechanizm jest jego uogólnieniem —
#    tamten to jeden globalny sekret z env-a, bez terminu ważności, bez
#    rotacji, bez rewokacji i bez możliwości ustalenia, KTO go użył.
#
# Koszt: to nie jest nagłówek z RFC. Świadomy — wąskość i jednoznaczność
# wygrywają z konwencją przy poświadczeniu bez wygasania sesji.

_UNAUTHENTICATED_SERVICE = HTTPException(
    # Jeden komunikat na wszystkie porażki uwierzytelnienia kluczem. Rozróżnianie
    # „nie ma takiego klucza" / „zły sekret" / „odwołany" powiedziałoby sondującemu,
    # które identyfikatory istnieją i które konta warto atakować dalej.
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Nieprawidłowy klucz API",
)


@dataclass(frozen=True)
class Caller:
    """Kto stoi za requestem: człowiek z JWT albo konto serwisowe z kluczem.

    Endpointy dostające ``Caller`` obsługują obie ścieżki bez rozgałęziania się
    na typ poświadczenia; ``audit_label`` daje jednolity zapis „kto to zrobił"
    niezależnie od tego, którędy przyszedł.
    """

    user: Optional[User] = None
    service: Optional[ServicePrincipal] = None

    def __post_init__(self) -> None:
        # Niezmiennik: DOKŁADNIE jedno z dwóch. `_check` zawsze ustawia jedno,
        # ale `Caller` jest publiczną dataklasą i nic nie broni komuś zbudować
        # pustej. Wtedy `audit_label` zwraca "unknown" — czyli wpis audytowy
        # bez sprawcy, co jest gorsze niż wyjątek, bo wygląda na dane.
        if (self.user is None) == (self.service is None):
            raise ValueError(
                "Caller wymaga dokładnie jednego: user albo service "
                f"(user={self.user is not None}, service={self.service is not None})"
            )

    @property
    def is_service_account(self) -> bool:
        return self.service is not None

    @property
    def audit_label(self) -> str:
        if self.service is not None:
            return self.service.audit_label
        if self.user is not None:
            return f"user:{self.user.id}"
        return "unknown"


async def _authenticate_service_key(
    request: Request,
    raw_key: str,
    db: AsyncSession,
) -> ServicePrincipal:
    """Zweryfikuj ``X-API-Key`` i odnotuj użycie. 401 na każdej porażce."""
    if not settings.SERVICE_ACCOUNTS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Konta serwisowe są wyłączone (SERVICE_ACCOUNTS_ENABLED=false)",
        )

    client_ip = client_ip_key(request)
    try:
        principal, key = await authenticate_api_key(db, raw_key)
    except ServiceKeyError as exc:
        # Loguje się POWÓD i IP, nigdy poświadczenie. ``exc.reason`` to zamknięty
        # zbiór etykiet z ``service_account_auth``, więc do logu nie trafia nic
        # sterowanego przez klienta.
        logger.warning(
            "service_account.auth_failed",
            extra={
                "reason": exc.reason,
                "client_ip": client_ip,
                "path": request.url.path,
            },
        )
        raise _UNAUTHENTICATED_SERVICE from exc

    # Konto serwisowe NIE MOŻE podszywać się pod użytkownika. Impersonacja jest
    # narzędziem admina do oglądania aplikacji cudzymi oczami i zakłada człowieka,
    # który świadomie ją włączył i którego da się o to zapytać. Klucz w cronie
    # nie ma takiej odpowiedzialności, a połączenie „poświadczenie bez wygasania
    # sesji" z „widzę dane dowolnego użytkownika" znosi cały sens wąskich
    # scope'ów: klucz do syncu Traffita zobaczyłby kandydatów oczami rekrutera.
    if request.headers.get(IMPERSONATION_HEADER):
        logger.warning(
            "service_account.impersonation_rejected",
            extra={"service_account": principal.slug, "key_id": principal.key_id},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Konto serwisowe nie może podszywać się pod użytkownika",
        )

    # Stempel leci po UWIERZYTELNIENIU, a przed sprawdzeniem scope'u — czyli
    # request odrzucony 403 za brak uprawnienia też odświeża `last_used_at`.
    # To jest wybór, nie przeoczenie: `last_used_at` odpowiada na pytanie „czy
    # ktoś jeszcze tego klucza używa", a nie „czy używa go skutecznie".
    #
    # Odwrotnie byłoby gorzej. Klucz strzelający co minutę ze źle dobranym
    # scope'em wyglądałby na kompletnie nieużywany, więc operator uznałby go za
    # martwy i skasował — zamiast zobaczyć, że jakaś integracja żyje i jest
    # źle skonfigurowana. Samo odrzucenie i tak jest widoczne w logach
    # audytowych, więc informacja „strzela, ale bez uprawnień" nie ginie.
    #
    # Zachowanie jest przypięte testem (`test_scope_denied_still_stamps_usage`),
    # żeby nie zmieniło się po cichu przy refaktorze.
    await stamp_key_usage(db, key.key_id, client_ip)
    return principal


def require_service_scope(*required: ServiceScope, allow_admin_jwt: bool = True):
    """Zależność: klucz API z KOMPLETEM podanych scope'ów albo (opcjonalnie) admin.

    ``allow_admin_jwt=True`` (domyślnie) zostawia dotychczasową ścieżkę
    przeglądarkową nietkniętą: endpoint, który dotąd wymagał ``AdminUser``,
    po podmianie na tę zależność nadal działa dla admina z JWT, a dodatkowo
    przyjmuje klucz. Dzięki temu wpięcie kluczy nie jest zmianą zrywającą
    i nie trzeba duplikować endpointów.

    Fail-closed w każdym rozgałęzieniu: brak obu poświadczeń → 401, klucz bez
    scope'u → 403, JWT nie-admina → 403. Nie ma ścieżki, w której brakujący
    scope przechodzi.
    """
    required_scopes = frozenset(scope.value for scope in required)
    if not required_scopes:
        # Zależność bez wymaganych scope'ów przepuszczałaby każdy ważny klucz
        # na dowolny endpoint. To błąd programisty, więc pęka przy imporcie
        # modułu (start aplikacji), a nie przy pierwszym requeście na produkcji.
        raise ValueError("require_service_scope wymaga co najmniej jednego scope'u")

    async def _check(
        request: Request,
        credentials: Annotated[
            Optional[HTTPAuthorizationCredentials], Depends(security)
        ],
        db: AsyncSession = Depends(get_db),
    ) -> Caller:
        raw_key = request.headers.get(API_KEY_HEADER)
        if raw_key:
            principal = await _authenticate_service_key(request, raw_key, db)
            missing = required_scopes - principal.scopes
            if missing:
                logger.warning(
                    "service_account.scope_denied",
                    extra={
                        "service_account": principal.slug,
                        "key_id": principal.key_id,
                        "missing": sorted(missing),
                        "path": request.url.path,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "insufficient_scope",
                        "required": sorted(required_scopes),
                        "missing": sorted(missing),
                    },
                )
            logger.info(
                "service_account.authorized",
                extra={
                    "service_account": principal.slug,
                    "key_id": principal.key_id,
                    "scopes": sorted(required_scopes),
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            return Caller(service=principal)

        if not allow_admin_jwt:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Wymagany nagłówek {API_KEY_HEADER}",
            )

        user = await get_current_user(request, credentials, db)
        if not user.has_role(UserRole.admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requires one of roles: ['admin']",
            )
        return Caller(user=user)

    return _check


# Gotowe zależności dla powierzchni operacyjnych. Każda nazywa dokładnie jeden
# scope — endpoint nie ma jak dostać szerszego uprawnienia niż to, którego
# faktycznie potrzebuje.
TraffitSyncCaller = Annotated[
    Caller, Depends(require_service_scope(ServiceScope.traffit_sync))
]
TraffitReadCaller = Annotated[
    Caller, Depends(require_service_scope(ServiceScope.traffit_read))
]
