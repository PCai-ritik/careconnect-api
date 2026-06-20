"""
CareConnect — Medical Records & Prescriptions Router

Endpoints:
  POST   /medical-records                       → Create a medical record
  GET    /patients/{patient_id}/records          → List records for a patient
  GET    /medical-records/{id}                   → Get single record detail
  POST   /medical-records/{id}/prescriptions     → Add prescriptions to a record

All routes are protected by get_current_user (JWT + RLS).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid

from app import models, schemas, crud, database
from app.dependencies import get_current_user, require_role
from app.ownership import verify_patient_access, verify_hospital_match

router = APIRouter(tags=["Medical Records"])


# ═══════════════════════════════════════════════════════════════════════
# POST /medical-records — Create a medical record
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "/medical-records",
    response_model=schemas.MedicalRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_medical_record(
    payload: schemas.MedicalRecordCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR, models.RoleEnum.SUPER_ADMIN])
    ),
):
    """
    Create a new medical record after a consultation.
    Only Doctors and Admins can create records.
    Optionally includes inline prescriptions.
    """
    # ── TENANT ISOLATION: Verify patient belongs to caller's hospital ──
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found.",
        )
    verify_patient_access(db, patient, current_user)

    # Auto-resolve doctor_id from current user instead of trusting payload
    resolved_doctor_id = payload.doctor_id
    if current_user.role == models.RoleEnum.DOCTOR:
        doctor = crud.get_doctor_by_user_id(db, user_id=current_user.id)
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor profile not found.",
            )
        resolved_doctor_id = doctor.id

    # Create the core record
    record = crud.create_medical_record(
        db=db,
        patient_id=payload.patient_id,
        doctor_id=resolved_doctor_id,
        appointment_id=payload.appointment_id,
        diagnosis=payload.diagnosis,
        vitals=payload.vitals or {},
    )

    # Update optional fields that create_medical_record doesn't handle
    if payload.symptoms:
        record.symptoms = payload.symptoms
    if payload.treatment:
        record.treatment = payload.treatment
    if payload.follow_up_date:
        record.follow_up_date = payload.follow_up_date
    db.commit()
    db.refresh(record)

    # If prescriptions were included inline, create them too
    if payload.prescriptions:
        crud.add_prescriptions(
            db=db,
            medical_record_id=record.id,
            doctor_id=resolved_doctor_id,
            patient_id=payload.patient_id,
            meds_list=[p.model_dump() for p in payload.prescriptions],
        )
        db.refresh(record)

    return record


# ═══════════════════════════════════════════════════════════════════════
# GET /patients/{patient_id}/records — Patient's medical history
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/records",
    response_model=List[schemas.MedicalRecordResponse],
)
def list_patient_records(
    patient_id: uuid.UUID,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    List all medical records for a specific patient.
    Verifies the caller has access to this patient first.
    """
    # Verify the caller has access to this patient
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = crud.get_caregiver_by_user_id(db, user_id=current_user.id)
        if not caregiver or patient.caregiver_id != caregiver.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    elif current_user.role == models.RoleEnum.DOCTOR:
        if patient.hospital_id != current_user.effective_hospital_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


    return crud.get_records_by_patient(db, patient_id)


# ═══════════════════════════════════════════════════════════════════════
# GET /medical-records/{id} — Single record detail
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/medical-records/{record_id}",
    response_model=schemas.MedicalRecordResponse,
)
def get_medical_record(
    record_id: uuid.UUID,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Retrieve a single medical record with its prescriptions.
    Verifies the caller has access to the patient.
    """
    record = crud.get_record_by_id(db, record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medical record not found",
        )

    # Verify access to the patient this record belongs to
    patient = db.query(models.Patient).filter(models.Patient.id == record.patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    verify_patient_access(db, patient, current_user)

    return record


# ═══════════════════════════════════════════════════════════════════════
# POST /medical-records/{id}/prescriptions — Add prescriptions
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "/medical-records/{record_id}/prescriptions",
    status_code=status.HTTP_201_CREATED,
)
def add_prescriptions_to_record(
    record_id: uuid.UUID,
    payload: List[schemas.PrescriptionBase],
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR, models.RoleEnum.SUPER_ADMIN])
    ),
):
    """
    Add one or more prescriptions to an existing medical record.
    Only Doctors and Admins can prescribe.
    """
    # Verify the record exists
    record = crud.get_record_by_id(db, record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medical record not found",
        )

    # ── TENANT ISOLATION: Verify the patient belongs to caller's hospital ──
    patient = db.query(models.Patient).filter(models.Patient.id == record.patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    verify_patient_access(db, patient, current_user)

    crud.add_prescriptions(
        db=db,
        medical_record_id=record_id,
        doctor_id=record.doctor_id,
        patient_id=record.patient_id,
        meds_list=[p.model_dump() for p in payload],
    )

    # Refresh and return the updated record
    db.refresh(record)
    return {"message": "Prescriptions added", "record_id": str(record_id)}
