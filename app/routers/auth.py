"""
CareConnect — Authentication Router

Endpoints:
  POST /auth/register/doctor    → Create Doctor user + stub Doctor profile
  POST /auth/register/caregiver → Create Caregiver user + Caregiver profile
  POST /auth/login              → Authenticate and return JWT tokens
  GET  /api/me                  → Protected route: return current user info
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app import crud, models, schemas, security
from app.database import get_db
from app.dependencies import get_current_user
from app.config import settings

# ═══════════════════════════════════════════════════════════════════════
# ROUTER SETUP
# ═══════════════════════════════════════════════════════════════════════

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])
api_router = APIRouter(prefix="/api", tags=["Protected"])


# ═══════════════════════════════════════════════════════════════════════
# POST /auth/register/doctor
# Creates User (role=DOCTOR) + stub Doctor profile in one transaction.
# The onboarding fields are filled later via PUT /doctors/onboarding.
# ═══════════════════════════════════════════════════════════════════════


@auth_router.post(
    "/register/doctor",
    response_model=schemas.Token,
    status_code=status.HTTP_201_CREATED,
)
def register_doctor(
    payload: schemas.DoctorRegister,
    response: Response,
    db: Session = Depends(get_db),
):
    """Register a new doctor. Creates User + empty Doctor profile. Returns JWT."""

    existing = crud.get_user_by_email(db, email=payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # New users silently default to the DEFAULT_HOSPITAL_ID (frictionless onboarding)
    from app.constants import DEFAULT_HOSPITAL_ID
    hospital_id = DEFAULT_HOSPITAL_ID

    # 1. Create the User row
    db_user = crud.create_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        hospital_id=hospital_id,
        role=models.RoleEnum.DOCTOR,
    )

    # 2. Create a stub Doctor profile (onboarding fills the rest)
    crud.create_doctor_profile(
        db,
        user_id=db_user.id,
        full_name=payload.full_name,
        specialization=payload.specialization or "",
        phone_number=payload.phone_number,
    )

    # 3. Generate tokens so user is authenticated immediately
    access_token = security.create_access_token(
        data={
            "sub": str(db_user.id),
            "hospital_id": str(db_user.hospital_id),
            "type": "access",
            "role": db_user.role.value,
        }
    )
    refresh_token = security.create_refresh_token(subject=db_user.id)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,
    )

    return schemas.Token(
        access_token=access_token,
        token_type="bearer",
        user_id=db_user.id,
        role=db_user.role.value,
    )


# ═══════════════════════════════════════════════════════════════════════
# POST /auth/register/caregiver
# Creates User (role=CAREGIVER) + Caregiver profile in one transaction.
# Caregivers have no onboarding — they go straight to the dashboard.
# ═══════════════════════════════════════════════════════════════════════


@auth_router.post(
    "/register/caregiver",
    response_model=schemas.Token,
    status_code=status.HTTP_201_CREATED,
)
def register_caregiver(
    payload: schemas.CaregiverRegister,
    response: Response,
    db: Session = Depends(get_db),
):
    """Register a new caregiver. Creates User + Caregiver profile. Returns JWT."""

    existing = crud.get_user_by_email(db, email=payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # New users silently default to the DEFAULT_HOSPITAL_ID (frictionless onboarding)
    from app.constants import DEFAULT_HOSPITAL_ID
    hospital_id = DEFAULT_HOSPITAL_ID

    # 1. Create the User row
    db_user = crud.create_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        hospital_id=hospital_id,
        role=models.RoleEnum.CAREGIVER,
    )

    # 2. Create the Caregiver profile
    crud.create_caregiver_profile(
        db,
        user_id=db_user.id,
        full_name=payload.full_name,
        whatsapp_number=payload.whatsapp_number,
    )

    # 3. Generate tokens so user is authenticated immediately
    access_token = security.create_access_token(
        data={
            "sub": str(db_user.id),
            "hospital_id": str(db_user.hospital_id),
            "type": "access",
            "role": db_user.role.value,
        }
    )
    refresh_token = security.create_refresh_token(subject=db_user.id)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,
    )

    return schemas.Token(
        access_token=access_token,
        token_type="bearer",
        user_id=db_user.id,
        role=db_user.role.value,
    )


# ═══════════════════════════════════════════════════════════════════════
# POST /auth/login
# ═══════════════════════════════════════════════════════════════════════


@auth_router.post("/login", response_model=schemas.Token)
def login(
    credentials: schemas.UserLogin,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate user, return access token + set refresh cookie."""

    # 1. Verify user exists
    user = crud.get_user_by_email(db, email=credentials.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # 2. Verify password
    if not security.verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # 3. Verify user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is deactivated. Please contact support.",
        )

    # 4. Create access token
    access_token = security.create_access_token(
        data={
            "sub": str(user.id),
            "hospital_id": str(user.hospital_id),
            "type": "access",
            "role": user.role.value,
        }
    )

    # 4. Create refresh token and set as HttpOnly cookie
    refresh_token = security.create_refresh_token(subject=user.id)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,  # Set True in production with HTTPS
    )

    return schemas.Token(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        role=user.role.value,
    )

# ═══════════════════════════════════════════════════════════════════════
# POST /auth/refresh
# Uses the HttpOnly refresh cookie to issue a new access token.
# ═══════════════════════════════════════════════════════════════════════


@auth_router.post("/refresh", response_model=schemas.Token)
def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Exchange a valid refresh cookie for a new access token."""

    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired or invalid",
        )

    user = crud.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Issue new access token
    new_access = security.create_access_token(
        data={
            "sub": str(user.id),
            "hospital_id": str(user.hospital_id),
            "type": "access",
            "role": user.role.value,
        }
    )

    # Rotate refresh token
    new_refresh = security.create_refresh_token(subject=user.id)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        samesite="lax",
        secure=False,
    )

    return schemas.Token(
        access_token=new_access,
        token_type="bearer",
        user_id=user.id,
        role=user.role.value,
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /api/me (Protected Route Test)
# ═══════════════════════════════════════════════════════════════════════


@api_router.get("/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    """Return the authenticated user's identity. Proves JWT guard works."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role.value,
        "hospital_id": str(current_user.hospital_id),
        "affiliation_status": current_user.affiliation_status.value if current_user.affiliation_status else "APPROVED",
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /api/users/request-affiliation
# Request association/affiliation with a target hospital.
# Sets affiliation_status = PENDING.
# ═══════════════════════════════════════════════════════════════════════


@api_router.post("/users/request-affiliation", response_model=schemas.UserResponse)
def request_affiliation(
    payload: schemas.AffiliationRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Allows a caregiver or doctor to request affiliation with a target hospital.
    Their hospital_id is updated to the target hospital, and status is set to PENDING.
    Until approved, their RLS context will fall back to the default hospital.
    """
    # 1. Verify target hospital exists
    hospital = db.query(models.Hospital).filter(models.Hospital.id == payload.hospital_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target hospital not found."
        )

    # 2. Update user record
    current_user.hospital_id = payload.hospital_id
    current_user.affiliation_status = models.AffiliationStatusEnum.PENDING
    
    db.commit()
    db.refresh(current_user)
    return current_user

