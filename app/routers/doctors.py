"""
CareConnect — Doctor Profile & Onboarding Router

Endpoints:
  GET  /doctors/profile           → Get the current doctor's profile
  PUT  /doctors/onboarding        → Submit all onboarding fields
  PUT  /doctors/availability      → Set weekly availability schedule
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app import crud, models, schemas
from app.database import get_db
from app.dependencies import get_current_user, require_role

router = APIRouter(prefix="/doctors", tags=["Doctors"])


# ═══════════════════════════════════════════════════════════════════════
# GET /doctors/profile
# Returns the authenticated doctor's full profile + availability slots.
# ═══════════════════════════════════════════════════════════════════════


@router.get("/profile", response_model=schemas.DoctorResponse)
def get_my_profile(
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: Session = Depends(get_db),
):
    """Return the doctor profile linked to the current authenticated user."""
    doctor = crud.get_doctor_by_user_id(db, user_id=current_user.id)
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
def complete_onboarding(
    payload: schemas.DoctorUpdate,
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: Session = Depends(get_db),
):
    """Submit doctor onboarding data. Sets onboarding_completed to True."""
    doctor = crud.get_doctor_by_user_id(db, user_id=current_user.id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )

    # Build update dict from only the fields that were provided
    update_data = payload.model_dump(exclude_unset=True)
    update_data["onboarding_completed"] = True

    updated_doctor = crud.update_doctor_onboarding(
        db, doctor_id=doctor.id, update_data=update_data
    )
    return updated_doctor


# ═══════════════════════════════════════════════════════════════════════
# PUT /doctors/availability
# Replaces the entire weekly schedule (Step 2 of onboarding).
# Also callable post-onboarding to update schedule from settings.
# ═══════════════════════════════════════════════════════════════════════


@router.put("/availability", status_code=status.HTTP_204_NO_CONTENT)
def set_availability(
    slots: List[schemas.DoctorAvailabilityBase],
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
    db: Session = Depends(get_db),
):
    """Replace the doctor's weekly availability schedule."""
    doctor = crud.get_doctor_by_user_id(db, user_id=current_user.id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )

    slot_dicts = [s.model_dump() for s in slots]
    crud.set_doctor_availability(db, doctor_id=doctor.id, slots=slot_dicts)
