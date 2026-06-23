"""
CareConnect — Doctor Profile & Onboarding Router

Endpoints:
  GET  /doctors                   → List doctors by hospital (public)
  GET  /doctors/profile           → Get the current doctor's profile
  PUT  /doctors/onboarding        → Submit all onboarding fields
  PUT  /doctors/availability      → Set weekly availability schedule
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import select
from typing import List, Optional
import uuid

from app import crud, models, schemas
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.services import vision

router = APIRouter(prefix="/doctors", tags=["Doctors"])


# ═══════════════════════════════════════════════════════════════════════
# GET /doctors
# Public endpoint — list doctors in a hospital.
# Used by the caregiver booking wizard to select a real doctor.
# Only returns doctors who have completed onboarding.
# ═══════════════════════════════════════════════════════════════════════


@router.get("", response_model=List[schemas.DoctorResponse])
async def list_doctors(
    hospital_id: uuid.UUID = Query(..., description="Filter by hospital"),
    specialization: Optional[str] = Query(None, description="Filter by specialization"),
    db: AsyncSession = Depends(get_db),
):
    """
    List doctors in a hospital. Public — no auth required.
    Only returns onboarded doctors with their availability slots.
    Optionally filter by specialization.
    """
    stmt = (
        select(models.Doctor)
        .join(models.User, models.Doctor.user_id == models.User.id)
        .options(joinedload(models.Doctor.availability_slots))
        .where(
            models.User.hospital_id == hospital_id,
            models.Doctor.onboarding_completed == True,
        )
    )

    if specialization:
        stmt = stmt.where(models.Doctor.specialization.ilike(f"%{specialization}%"))

    stmt = stmt.order_by(models.Doctor.full_name)
    doctors = (await db.execute(stmt)).unique().scalars().all()
    return doctors


# ═══════════════════════════════════════════════════════════════════════
# GET /doctors/search
# Public endpoint — search doctors by name, specialization, or location.
# Powers the "ENT near me" / "ENT in Kamaluganja" search flow.
# ═══════════════════════════════════════════════════════════════════════


@router.get("/search", response_model=List[schemas.DoctorResponse])
async def search_doctors(
    q: str = Query(..., min_length=1, description="Search query (name, specialization, or location)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search for onboarded doctors by name, specialization, or clinic address/name.
    Public — no auth required.
    """
    search_term = f"%{q}%"
    stmt = (
        select(models.Doctor)
        .options(joinedload(models.Doctor.availability_slots))
        .where(
            models.Doctor.onboarding_completed == True,
            (
                models.Doctor.full_name.ilike(search_term)
                | models.Doctor.specialization.ilike(search_term)
                | models.Doctor.clinic_name.ilike(search_term)
                | models.Doctor.clinic_address.ilike(search_term)
            ),
        )
        .order_by(models.Doctor.full_name)
    )
    doctors = (await db.execute(stmt)).unique().scalars().all()
    return doctors


# ═══════════════════════════════════════════════════════════════════════
# GET /doctors/profile
# Return the current doctor's own profile (doctor only).
# ═══════════════════════════════════════════════════════════════════════


@router.get("/profile", response_model=schemas.DoctorResponse)
async def get_my_profile(
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return the doctor profile linked to the current authenticated user."""
    doctor = await crud.get_doctor_by_user_id(db, user_id=current_user.id) # type: ignore
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found. Please complete registration first.",
        )
    return doctor


# ═══════════════════════════════════════════════════════════════════════
# GET /doctors/dashboard-stats
# Returns aggregated stats for the doctor's dashboard home page.
# MUST be declared before /{doctor_id} so FastAPI doesn't try to parse
# the literal string "dashboard-stats" as a UUID path parameter.
# ═══════════════════════════════════════════════════════════════════════


@router.get("/dashboard-stats", response_model=schemas.DashboardStatsResponse)
async def get_dashboard_stats(
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated dashboard stats for the authenticated doctor."""
    from sqlalchemy import func as sqla_func

    doctor = await crud.get_doctor_by_user_id(db, user_id=current_user.id) # type: ignore
    if not doctor:
        return schemas.DashboardStatsResponse()

    # Join appointments → video_sessions to get actual call durations
    stmt = (
        select(
            sqla_func.count(models.VideoSession.id).label("total_completed"),
            sqla_func.coalesce(
                sqla_func.avg(models.VideoSession.actual_duration_minutes), 0
            ).label("avg_minutes"),
        )
        .join(
            models.Appointment,
            models.VideoSession.appointment_id == models.Appointment.id,
        )
        .where(
            models.Appointment.doctor_id == doctor.id,
            models.VideoSession.actual_duration_minutes.isnot(None),
        )
    )
    result = (await db.execute(stmt)).first()

    return schemas.DashboardStatsResponse(
        avg_consult_minutes=int(result.avg_minutes) if result else 0, # type: ignore
        total_completed=result.total_completed if result else 0, # type: ignore
    )


# ═══════════════════════════════════════════════════════════════════════
# PUT /doctors/onboarding
# Accepts all onboarding fields from the 3-step wizard:
#   Step 1 (Verification): license_number, hospital_affiliation, bio, etc.
#   Step 3 (Payments): consultation_fee, currency, accepted_payment_methods
# Marks onboarding_completed = True.
# MUST be declared before /{doctor_id} so "onboarding" is not parsed as UUID.
# ═══════════════════════════════════════════════════════════════════════


@router.put("/onboarding", response_model=schemas.DoctorResponse)
async def complete_onboarding(
    payload: schemas.DoctorUpdate,
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: AsyncSession = Depends(get_db),
):
    """Submit doctor onboarding data. Sets onboarding_completed to True."""
    doctor = await crud.get_doctor_by_user_id(db, user_id=current_user.id) # type: ignore
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )

    # Build update dict from only the fields that were provided
    update_data = payload.model_dump(exclude_unset=True)
    update_data["onboarding_completed"] = True

    updated_doctor = await crud.update_doctor_onboarding(
        db, doctor_id=doctor.id, update_data=update_data # type: ignore
    )
    return updated_doctor


# ═══════════════════════════════════════════════════════════════════════
# POST /doctors/verify-license
# Verifies an uploaded medical license document using AI Vision.
# ═══════════════════════════════════════════════════════════════════════


@router.post("/verify-license")
async def verify_license(
    file: UploadFile = File(...),
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
):
    """
    Analyzes an uploaded image or PDF to verify if it is a medical license.
    Returns the extracted license number and state if valid.
    """
    file_bytes = await file.read()
    
    try:
        result = await vision.verify_medical_license(file_bytes, file.filename or "unknown.jpg")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze document. Please try again."
        )

    if not result.get("is_valid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded document does not appear to be a valid medical license. Please ensure the image is clear and try again."
        )
        
    return result


# ═══════════════════════════════════════════════════════════════════════
# PATCH /doctors/profile
# Update profile fields post-onboarding (e.g. phone, license, bio).
# Does NOT re-set onboarding_completed.
# ═══════════════════════════════════════════════════════════════════════


@router.patch("/profile", response_model=schemas.DoctorResponse)
async def update_profile(
    payload: schemas.DoctorUpdate,
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: AsyncSession = Depends(get_db),
):
    """Update doctor profile fields. Does not change onboarding_completed."""
    doctor = await crud.get_doctor_by_user_id(db, user_id=current_user.id) # type: ignore
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    update_data.pop("onboarding_completed", None)  # Don't touch onboarding flag

    if update_data:
        updated_doctor = await crud.update_doctor_onboarding(
            db, doctor_id=doctor.id, update_data=update_data # type: ignore
        )
        return updated_doctor
    return doctor


# ═══════════════════════════════════════════════════════════════════════
# PUT /doctors/availability
# Replaces the entire weekly schedule (Step 2 of onboarding).
# Also callable post-onboarding to update schedule from settings.
# ═══════════════════════════════════════════════════════════════════════


@router.put("/availability", status_code=status.HTTP_204_NO_CONTENT)
async def set_availability(
    slots: List[schemas.DoctorAvailabilityBase],
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: AsyncSession = Depends(get_db),
):
    """Replace the doctor's weekly availability schedule."""
    doctor = await crud.get_doctor_by_user_id(db, user_id=current_user.id) # type: ignore
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )

    slot_dicts = [s.model_dump() for s in slots]
    await crud.set_doctor_availability(db, doctor_id=doctor.id, slots=slot_dicts) # type: ignore


# ═══════════════════════════════════════════════════════════════════════
# GET /doctors/{doctor_id}
# Fetch a specific doctor's profile by ID with access control.
# Used by caregivers to view doctors for their patients.
# MUST be declared last — after all static path segments (profile,
# dashboard-stats, onboarding, verify-license, availability).
# ═══════════════════════════════════════════════════════════════════════


@router.get("/{doctor_id}", response_model=schemas.DoctorResponse)
async def get_doctor_profile(
    doctor_id: uuid.UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch a specific doctor's profile.
    
    DEFENSE-IN-DEPTH: Access control is enforced at TWO levels:
    
    1. DATABASE LEVEL (RLS Policy):
       - Doctors can see their own profile
       - Caregivers can see doctors with medical records for their assigned patients
       - Admins bypass all restrictions
       - Default: DENY
    
    2. APPLICATION LEVEL (This function):
       - Validates the same logic at the FastAPI layer
       - Provides consistent error messages
       - Protects against edge cases where RLS might be bypassed (e.g., via raw SQL)
       - Extra security if database connection is compromised
    
    This dual-layer approach ensures that even if one layer fails,
    the other still protects against unauthorized access.
    """
    doctor = await crud.get_doctor_by_id(db, doctor_id=doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )

    # If doctor, they can access their own
    if current_user.role == models.RoleEnum.DOCTOR:
        own_doctor = await crud.get_doctor_by_user_id(db, user_id=current_user.id)  # type: ignore
        if own_doctor and own_doctor.id == doctor_id:
            return doctor
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this doctor profile.",
        )

    # If caregiver, check access via patient records
    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = await crud.get_caregiver_by_user_id(db, user_id=current_user.id)  # type: ignore
        if not caregiver:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caregiver profile not found.",
            )
        has_access = await crud.can_caregiver_access_doctor(db, caregiver.id, doctor_id)  # type: ignore
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this doctor profile.",
            )
        return doctor

    # Other roles (admin, super_admin) can access
    if current_user.role in [models.RoleEnum.ADMIN, models.RoleEnum.SUPER_ADMIN]:
        return doctor

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this doctor profile.",
    )

