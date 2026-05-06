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
from app.schemas.user import LoginRequest, TokenResponse, UserCreate, UserResponse
from app.services.email import (
    send_password_changed_notification,
    send_password_reset_email,
)
from app.services.password_reset import (
    RESET_TOKEN_TTL_MINUTES,
    cleanup_expired_tokens,
    create_reset_token,
    verify_and_consume_token,
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


router = APIRouter()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordTokenRequest(BaseModel):
    token: str = Field(..., min_length=64, max_length=64)
    new_password: str = Field(..., min_length=8, max_length=128)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)
):
    """Authenticate user and return JWT tokens. Rate-limited: 5 req/min per IP."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    return TokenResponse(
        access_token=create_access_token(
            user.id,
            user.role.value,
            force_password_change=user.force_password_change,
        ),
        refresh_token=create_refresh_token(user.id),
    )


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit("3/minute")
async def register(
    request: Request, data: UserCreate, db: AsyncSession = Depends(get_db)
):
    """Register a new user. Rate-limited: 3 req/min per IP."""
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    preexempt = data.role not in _ONBOARDING_REQUIRED_ROLES
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        role=data.role,
        profile_completed=preexempt,
        profile_completed_at=func.now() if preexempt else None,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


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
        plain_token = await create_reset_token(
            db, user.id, requested_ip=requester_ip
        )
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
