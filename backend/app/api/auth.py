from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    decode_token,
)
from app.models.activity import Activity
from app.models.user import User, UserRole
from app.schemas.user import (
    LoginRequest,
    SelfRegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.email import (
    send_email_verification_email,
    send_password_changed_notification,
    send_password_reset_email,
)
from app.services.password_reset import (
    RESET_TOKEN_TTL_MINUTES,
    cleanup_expired_tokens,
    create_reset_token,
    verify_and_consume_token,
)
from app.services.email_verification import (
    cleanup_expired_tokens as cleanup_expired_verification_tokens,
    create_verification_token,
    verify_and_consume_token as verify_and_consume_verification_token,
)
from app.api.deps import CurrentUser

# Roles that must complete first-login onboarding before the frontend unlocks
# the shell. Keep in sync with backend/app/api/onboarding.py.
_ONBOARDING_REQUIRED_ROLES = {UserRole.delivery_lead, UserRole.recruiter}

# Generic anti-enumeration response for /forgot-password — używamy
# zarówno dla istniejących, jak i nieistniejących adresów.
_FORGOT_GENERIC_DETAIL = (
    "Jeśli konto z tym adresem istnieje, wysłaliśmy link resetowy. "
    "Sprawdź skrzynkę (oraz folder spam)."
)

# Returned from /register on EVERY outcome (new account, existing-unverified,
# existing-verified) so the HTTP response never reveals whether the email is
# already registered (anti-enumeration — mirrors /forgot-password). Phrasing
# covers both "new account → check inbox" and "already have one → just log in"
# without disclosing which case applies.
_REGISTER_GENERIC_DETAIL = (
    "Jeśli to nowy adres, wysłaliśmy na niego link aktywacyjny — kliknij go, aby "
    "potwierdzić email i zalogować się (sprawdź też folder spam). Jeśli masz już "
    "konto z tym adresem, po prostu się zaloguj."
)

# Generic anti-enumeration response for /resend-verification.
_RESEND_GENERIC_DETAIL = (
    "Jeśli istnieje niepotwierdzone konto z tym adresem, wysłaliśmy nowy link "
    "aktywacyjny. Sprawdź skrzynkę (oraz folder spam)."
)

# 403 detail when a self-registered account tries to log in before confirming
# its email. Surfaced verbatim by the login page.
_EMAIL_NOT_VERIFIED_DETAIL = (
    "Potwierdź swój adres email, zanim się zalogujesz. Sprawdź skrzynkę "
    "(oraz folder spam) — wysłaliśmy tam link aktywacyjny."
)


router = APIRouter()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordTokenRequest(BaseModel):
    token: str = Field(..., min_length=64, max_length=64)
    new_password: str = Field(..., min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=64, max_length=64)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class MessageResponse(BaseModel):
    detail: str


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)
):
    """Authenticate user and return JWT tokens. Rate-limited: 5 req/min per IP."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    # Guard SSO-only userów: ``password_hash IS NULL`` po migracji 0081 oznacza
    # konto zalogowane przez Microsoft SSO i bez bcrypt hash — odmów cicho,
    # nie ujawniając czy konto istnieje.
    if (
        not user
        or not user.password_hash
        or not verify_password(data.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    # Self-registered accounts must confirm their email before first login.
    # password_hash is guaranteed set here (SSO-only users failed the check
    # above). Existing email/password users + SSO users are backfilled to
    # email_verified=True (migration 0139), so only freshly self-registered,
    # not-yet-confirmed accounts are blocked.
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_EMAIL_NOT_VERIFIED_DETAIL,
        )
    return TokenResponse(
        access_token=create_access_token(
            user.id,
            user.role.value,
            force_password_change=user.force_password_change,
            roles=[r.value for r in user.get_all_roles()],
        ),
        refresh_token=create_refresh_token(user.id),
    )


@router.post(
    "/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit("3/minute")
async def register(
    request: Request, data: SelfRegisterRequest, db: AsyncSession = Depends(get_db)
):
    """Self-service email/password registration. Rate-limited: 3 req/min per IP.

    Security invariants (this endpoint is publicly reachable):

    1. Gated by ``SELF_REGISTRATION_ENABLED`` — 503 when off.
    2. Email domain MUST be on ``SSO_ALLOWED_DOMAINS`` whitelist (shared with
       Microsoft SSO). Empty whitelist rejects everything (fail-closed).
    3. Role is ALWAYS forced to ``user`` (read-only viewer) server-side — the
       request body has no ``role`` field. An admin elevates the role later in
       the panel. This closes the prior hole where ``role`` was caller-supplied
       and anyone could self-provision an ``admin``.
    4. Account is created ``email_verified=False`` and cannot log in until the
       owner clicks the verification link emailed to them.
    5. Anti-enumeration: the response is ALWAYS the generic 201 below — never a
       409 — so the endpoint cannot be used to probe which addresses already
       have accounts (mirrors /forgot-password). The bcrypt hash is computed on
       both paths so timing does not leak existence either.
    """
    if not settings.SELF_REGISTRATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rejestracja jest obecnie wyłączona. Skontaktuj się z administratorem.",
        )

    # Normalize email (DB unique index is exact-match; SSO also lowercases).
    email = data.email.strip().lower()
    requester_ip = request.client.host if request.client else None
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")

    # Domain whitelist — fail-closed (empty list rejects every domain).
    domain = email.split("@")[-1]
    if domain not in settings.sso_allowed_domains_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="domain_forbidden",
        )

    # Compute the bcrypt hash up front so response timing is the same whether or
    # not the email already exists — bcrypt dominates the cost, so doing it on
    # both branches removes the timing oracle that would otherwise complement
    # the (now-removed) 409 enumeration signal.
    password_hash = hash_password(data.password)

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing is not None:
        # Anti-enumeration: never reveal that the email is taken. If the account
        # is still unverified, (re)send a fresh link so a legitimate owner who
        # lost the first email can still activate; if already verified, send
        # nothing (the generic message tells them to log in). No new row, no
        # role/state mutation either way.
        if existing.is_active and not existing.email_verified:
            plain_token = await create_verification_token(
                db, existing.id, requested_ip=requester_ip
            )
            send_email_verification_email(
                to_email=existing.email,
                recipient_name=existing.name,
                verify_url=f"{base}/register/verify?token={plain_token}",
            )
            db.add(
                Activity(
                    entity_type="user",
                    entity_id=existing.id,
                    action="email_verification_resent",
                    user_id=existing.id,
                    details={"ip": requester_ip, "via": "register_duplicate"},
                )
            )
            await db.flush()
        return MessageResponse(detail=_REGISTER_GENERIC_DETAIL)

    # New account. Viewer (``user``) is not in _ONBOARDING_REQUIRED_ROLES, so it
    # is exempt from the first-login onboarding gate.
    preexempt = UserRole.user not in _ONBOARDING_REQUIRED_ROLES
    user = User(
        email=email,
        password_hash=password_hash,
        name=data.name,
        role=UserRole.user,
        roles=[UserRole.user.value],
        is_active=True,
        email_verified=False,
        profile_completed=preexempt,
        profile_completed_at=func.now() if preexempt else None,
    )
    db.add(user)
    await db.flush()  # populate user.id

    plain_token = await create_verification_token(
        db, user.id, requested_ip=requester_ip
    )
    send_email_verification_email(
        to_email=user.email,
        recipient_name=user.name,
        verify_url=f"{base}/register/verify?token={plain_token}",
    )

    # Audit: self-provisioning is security-relevant (mirror SSO provisioning).
    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action="self_registered",
            user_id=user.id,  # actor = the new user themselves (no admin)
            details={
                "email": email,
                "domain": domain,
                "default_role": UserRole.user.value,
                "ip": requester_ip,
            },
        )
    )
    await db.flush()
    return MessageResponse(detail=_REGISTER_GENERIC_DETAIL)


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Confirm a self-registered account's email using the token from the link.

    Single-use token (atomic consume). On success: set ``email_verified=True``
    so the user can log in. Idempotent-ish — a second click on the same link
    fails with 400 (token already consumed), which the frontend treats as
    "already verified, go log in".
    """
    user = await verify_and_consume_verification_token(db, data.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Link aktywacyjny jest nieprawidłowy lub wygasł. Poproś o nowy.",
        )

    user.email_verified = True
    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action="email_verified",
            user_id=user.id,
            details={"ip": request.client.host if request.client else None},
        )
    )
    await db.flush()
    return None


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    data: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Re-send the verification link for an unconfirmed account.

    Anti-enumeration: always returns 200 with a generic message regardless of
    whether the email exists or is already verified. Only sends a fresh link
    when an *unverified* account is found. Rate-limited 3/min per IP.
    """
    email = data.email.strip().lower()
    requester_ip = request.client.host if request.client else None

    await cleanup_expired_verification_tokens(db)

    user = await db.scalar(select(User).where(User.email == email))
    if user is not None and user.is_active and not user.email_verified:
        plain_token = await create_verification_token(
            db, user.id, requested_ip=requester_ip
        )
        base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
        verify_url = f"{base}/register/verify?token={plain_token}"
        send_email_verification_email(
            to_email=user.email,
            recipient_name=user.name,
            verify_url=verify_url,
        )
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="email_verification_resent",
                user_id=user.id,
                details={"ip": requester_ip},
            )
        )
        await db.flush()

    return {"detail": _RESEND_GENERIC_DETAIL}


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh_token(
    request: Request, refresh_token: str, db: AsyncSession = Depends(get_db)
):
    """Exchange a refresh token for a new access token. Rate-limited: 10 req/min per IP."""
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return TokenResponse(
        access_token=create_access_token(
            user.id,
            user.role.value,
            force_password_change=user.force_password_change,
            roles=[r.value for r in user.get_all_roles()],
        ),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser):
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Self-service password change.

    Wymaga obecnego hasła (proof-of-possession) + nowego hasła min. 8 znaków.
    Rate-limited 3/min per IP. Nie ujawnia że user istnieje — wszystkie
    niepoprawne próby zwracają 401.

    Po sukcesie: clear ``force_password_change`` flag (jeśli była ustawiona
    przez admin-reset) + audit log + email notification.
    """
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if data.new_password == data.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from current",
        )
    current_user.password_hash = hash_password(data.new_password)
    current_user.force_password_change = False
    current_user.force_password_change_at = None

    db.add(
        Activity(
            entity_type="user",
            entity_id=current_user.id,
            action="password_changed_by_self",
            user_id=current_user.id,
            details={"ip": request.client.host if request.client else None},
        )
    )
    await db.flush()

    # Best-effort email notification (no-op gdy SMTP off).
    send_password_changed_notification(
        to_email=current_user.email,
        recipient_name=current_user.name,
        by_admin=False,
    )
    return None


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset link via email.

    Anti-enumeration: zawsze zwraca 200 OK z tym samym komunikatem,
    niezależnie czy email istnieje w DB. Jeśli istnieje — generujemy token
    i wysyłamy mail. Jeśli nie — silent no-op.

    Rate-limited 3/min per IP. Activity audit log dla każdego requestu
    (nawet nieznany email — ślad dla analizy bezpieczeństwa).
    """
    requester_ip = request.client.host if request.client else None

    # Lookup user (case-insensitive nie jest istotny — backend wymusza
    # email validator EmailStr, a DB ma unique index na exact match).
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    # Periodic cleanup — best-effort, nie blokujemy responsu.
    await cleanup_expired_tokens(db)

    if user is not None and user.is_active:
        plain_token = await create_reset_token(db, user.id, requested_ip=requester_ip)
        base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
        reset_url = f"{base}/login/reset?token={plain_token}"

        send_password_reset_email(
            to_email=user.email,
            recipient_name=user.name,
            reset_url=reset_url,
            expires_minutes=RESET_TOKEN_TTL_MINUTES,
        )
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="password_reset_requested",
                user_id=user.id,
                details={"ip": requester_ip, "via": "forgot_password"},
            )
        )
    else:
        # Audit log dla nieznanych adresów — pomaga w wykryciu brute-force.
        # entity_id=0 zamiast None bo Activity.entity_id jest NOT NULL.
        db.add(
            Activity(
                entity_type="user",
                entity_id=0,
                action="password_reset_requested_unknown_email",
                user_id=None,
                details={"ip": requester_ip, "email": data.email},
            )
        )

    await db.flush()
    return {"detail": _FORGOT_GENERIC_DETAIL}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def reset_password_with_token(
    request: Request,
    data: ResetPasswordTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set new password using a valid reset token from email.

    Token jest jednorazowy — atomic UPDATE w
    ``verify_and_consume_token`` zapobiega replay attack. Po sukcesie
    czyścimy ``force_password_change`` flag (gdy była ustawiona przez
    admin-reset) + audit log + email notification.
    """
    user = await verify_and_consume_token(db, data.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Link resetowy jest nieprawidłowy lub wygasł. Poproś o nowy link.",
        )

    user.password_hash = hash_password(data.new_password)
    user.force_password_change = False
    user.force_password_change_at = None

    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action="password_changed_via_token",
            user_id=user.id,
            details={"ip": request.client.host if request.client else None},
        )
    )
    await db.flush()

    send_password_changed_notification(
        to_email=user.email,
        recipient_name=user.name,
        by_admin=False,
    )
    return None
