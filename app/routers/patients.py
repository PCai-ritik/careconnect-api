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
from app.ownership import verify_hospital_match

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
    - hospital_id is auto-resolved from the current user if not provided.
    - Caregivers: caregiver_id is auto-set to their profile.
    - Doctors: doctor_id is auto-set to their profile; caregiver_id is optional.
    """

    # Auto-resolve hospital_id from current user
    if not payload.hospital_id:
        payload.hospital_id = current_user.effective_hospital_id


    # If the caller is a caregiver, override caregiver_id with their profile
    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = crud.get_caregiver_by_user_id(db, user_id=current_user.id)
        if not caregiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Caregiver profile not found.",
            )
        payload.caregiver_id = caregiver.id

    # If the caller is a doctor, auto-set doctor_id to their profile
    doctor_id = payload.doctor_id
    if current_user.role == models.RoleEnum.DOCTOR:
        doctor = crud.get_doctor_by_user_id(db, user_id=current_user.id)
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor profile not found.",
            )
        doctor_id = doctor.id

    patient_data = payload.model_dump(exclude={"caregiver_id", "hospital_id", "doctor_id"})

    db_patient = crud.create_patient(
        db,
        caregiver_id=payload.caregiver_id,
        hospital_id=payload.hospital_id,
        patient_data=patient_data,
        doctor_id=doctor_id,
    )
    return db_patient


# ═══════════════════════════════════════════════════════════════════════
# GET /patients
# Returns patients scoped by role:
#   - Doctors see only their own patients (by doctor_id)
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
    List patients scoped by role (application-level + RLS):
    - CAREGIVER: only patients linked to their caregiver profile
    - DOCTOR: only patients linked to their doctor profile (doctor_id)
    - SUPER_ADMIN: all patients in their hospital
    """
    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = crud.get_caregiver_by_user_id(db, user_id=current_user.id)
        if not caregiver:
            return []
        return (
            db.query(models.Patient)
            .filter(models.Patient.caregiver_id == caregiver.id)
            .all()
        )

    if current_user.role == models.RoleEnum.DOCTOR:
        doctor = crud.get_doctor_by_user_id(db, user_id=current_user.id)
        if not doctor:
            return []
        return (
            db.query(models.Patient)
            .filter(models.Patient.doctor_id == doctor.id)
            .all()
        )

    # Super Admins see all patients in their hospital
    return (
        db.query(models.Patient)
        .filter(models.Patient.hospital_id == current_user.effective_hospital_id)
        .all()
    )



# ═══════════════════════════════════════════════════════════════════════
# PATCH /patients/{patient_id}
# Update patient details. Caregivers can only edit their own patients.
# ═══════════════════════════════════════════════════════════════════════


@router.patch(
    "/{patient_id}", response_model=schemas.PatientResponse
)
def update_patient(
    patient_id: str,
    payload: schemas.PatientUpdate,
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR, models.RoleEnum.CAREGIVER])
    ),
    db: Session = Depends(get_db),
):
    """
    Update a patient's profile fields.
    - Caregivers: can only edit patients linked to their caregiver profile.
    - Doctors: can edit any patient in their hospital.
    """
    import uuid as _uuid

    pid = _uuid.UUID(patient_id)

    # Verify the patient exists
    db_patient = db.query(models.Patient).filter(models.Patient.id == pid).first()
    if not db_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found.",
        )

    # Caregivers can only update their own patients
    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = crud.get_caregiver_by_user_id(db, user_id=current_user.id)
        if not caregiver or db_patient.caregiver_id != caregiver.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit patients you manage.",
            )

    # Doctors can only update patients in their own hospital
    if current_user.role == models.RoleEnum.DOCTOR:
        verify_hospital_match(db_patient.hospital_id, current_user)

    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        return db_patient

    updated = crud.update_patient(db, patient_id=pid, data=update_data)
    return updated
