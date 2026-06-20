"""
CareConnect — Doctor Profile & Onboarding Router

Endpoints:
  GET  /doctors                   → List doctors by hospital (public)
  GET  /doctors/profile           → Get the current doctor's profile
  PUT  /doctors/onboarding        → Submit all onboarding fields
  PUT  /doctors/availability      → Set weekly availability schedule
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import select
from typing import List, Optional
import uuid

from app import crud, models, schemas
from app.database import get_db
from app.dependencies import get_current_user, require_role

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
# GET /doctors/profile
# Returns the authenticated doctor's full profile + availability slots.
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
# PUT /doctors/onboarding
# Accepts all onboarding fields from the 3-step wizard:
#   Step 1 (Verification): license_number, hospital_affiliation, bio, etc.
#   Step 3 (Payments): consultation_fee, currency, accepted_payment_methods
# Marks onboarding_completed = True.
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
# GET /doctors/dashboard-stats
# Returns aggregated stats for the doctor's dashboard home page.
# avg_consult_minutes is computed from video_sessions.actual_duration_minutes.
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
