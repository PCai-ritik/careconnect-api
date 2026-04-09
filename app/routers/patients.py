"""
CareConnect — Patient Management Router

Patients are NOT authenticated users. They are data entities
managed by Caregivers and Doctors via the AddPatient modal/sheet.

Endpoints:
  POST /patients       → Register a new patient (Doctor or Caregiver)
  GET  /patients       → List patients (scoped by role via RLS)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app import crud, models, schemas
from app.database import get_db
from app.dependencies import get_current_user, require_role

router = APIRouter(prefix="/patients", tags=["Patients"])


# ═══════════════════════════════════════════════════════════════════════
# POST /patients
# Doctors and Caregivers can add patients.
# - Caregiver: caregiver_id is resolved from their profile automatically.
# - Doctor: must provide caregiver_id in the body (the patient's caregiver).
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "", response_model=schemas.PatientResponse, status_code=status.HTTP_201_CREATED
)
def add_patient(
    payload: schemas.PatientCreate,
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR, models.RoleEnum.CAREGIVER])
    ),
    db: Session = Depends(get_db),
):
    """
    Register a new patient.
    - Caregivers: caregiver_id is auto-set to the current user's profile.
    - Doctors: caregiver_id must be provided in the request body.
    """

    # If the caller is a caregiver, override caregiver_id with their profile
    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = crud.get_caregiver_by_user_id(db, user_id=current_user.id)
        if not caregiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Caregiver profile not found.",
            )
        payload.caregiver_id = caregiver.id

    patient_data = payload.model_dump(exclude={"caregiver_id", "hospital_id"})

    db_patient = crud.create_patient(
        db,
        caregiver_id=payload.caregiver_id,
        hospital_id=payload.hospital_id,
        patient_data=patient_data,
    )
    return db_patient


# ═══════════════════════════════════════════════════════════════════════
# GET /patients
# Returns patients scoped by RLS:
#   - Doctors see all patients in their hospital
#   - Caregivers see only patients they manage
# ═══════════════════════════════════════════════════════════════════════


@router.get("", response_model=List[schemas.PatientResponse])
def list_patients(
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR, models.RoleEnum.CAREGIVER, models.RoleEnum.SUPER_ADMIN])
    ),
    db: Session = Depends(get_db),
):
    """
    List patients. RLS automatically scopes results:
    - DOCTOR / SUPER_ADMIN: all patients in their hospital
    - CAREGIVER: only patients linked to their caregiver profile
    """
    patients = db.query(models.Patient).all()
    return patients
