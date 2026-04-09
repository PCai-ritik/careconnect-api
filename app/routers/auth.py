"""
CareConnect — Authentication Router

Endpoints:
  POST /auth/register/doctor    → Create Doctor user + stub Doctor profile
  POST /auth/register/caregiver → Create Caregiver user + Caregiver profile
  POST /auth/login              → Authenticate and return JWT tokens
  GET  /api/me                  → Protected route: return current user info
"""

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from app import crud, models, schemas, security
from app.database import get_db
from app.dependencies import get_current_user

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
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_doctor(
    payload: schemas.DoctorRegister, db: Session = Depends(get_db)
):
    """Register a new doctor. Creates User + empty Doctor profile."""

    existing = crud.get_user_by_email(db, email=payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # 1. Create the User row
    db_user = crud.create_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        hospital_id=payload.hospital_id,
        role=models.RoleEnum.DOCTOR,
    )

    # 2. Create a stub Doctor profile (onboarding fills the rest)
    crud.create_doctor_profile(
        db,
        user_id=db_user.id,
        full_name=payload.full_name,
        specialization=payload.specialization or "",
    )

    return db_user


# ═══════════════════════════════════════════════════════════════════════
# POST /auth/register/caregiver
# Creates User (role=CAREGIVER) + Caregiver profile in one transaction.
# Caregivers have no onboarding — they go straight to the dashboard.
# ═══════════════════════════════════════════════════════════════════════


@auth_router.post(
    "/register/caregiver",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_caregiver(
    payload: schemas.CaregiverRegister, db: Session = Depends(get_db)
):
    """Register a new caregiver. Creates User + Caregiver profile."""

    existing = crud.get_user_by_email(db, email=payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # 1. Create the User row
    db_user = crud.create_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        hospital_id=payload.hospital_id,
        role=models.RoleEnum.CAREGIVER,
    )

    # 2. Create the Caregiver profile
    crud.create_caregiver_profile(
        db,
        user_id=db_user.id,
        full_name=payload.full_name,
        whatsapp_number=payload.whatsapp_number,
    )

    return db_user


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

    # 3. Create access token
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
# GET /api/me (Protected Route Test)
# ═══════════════════════════════════════════════════════════════════════


@api_router.get("/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    """Return the authenticated user's identity. Proves JWT guard works."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role.value,
        "hospital_id": str(current_user.hospital_id),
    }
