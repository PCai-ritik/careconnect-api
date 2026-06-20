"""
CareConnect — Ownership & Tenant Isolation Guards

Reusable verification helpers that enforce multi-tenancy data boundaries
at the application layer. These are the **primary** defense — PostgreSQL
RLS is a secondary safety net.

Usage in routers:
    from app.ownership import verify_appointment_access, verify_patient_access

    appointment = crud.get_appointment_by_id(db, appointment_id)
    verify_appointment_access(db, appointment, current_user)
"""

import uuid
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models, crud


def _resolve_doctor_id(db: Session, user: models.User) -> uuid.UUID | None:
    """Resolve the doctors.id from a User with role=DOCTOR."""
    doctor = crud.get_doctor_by_user_id(db, user_id=user.id)
    return doctor.id if doctor else None


def _resolve_caregiver_id(db: Session, user: models.User) -> uuid.UUID | None:
    """Resolve the caregivers.id from a User with role=CAREGIVER."""
    caregiver = crud.get_caregiver_by_user_id(db, user_id=user.id)
    return caregiver.id if caregiver else None


# ═══════════════════════════════════════════════════════════════════════
# HOSPITAL BOUNDARY CHECK
# ═══════════════════════════════════════════════════════════════════════


def verify_hospital_match(
    entity_hospital_id: uuid.UUID,
    current_user: models.User,
) -> None:
    """
    Verify that an entity belongs to the current user's hospital.
    SUPER_ADMINs bypass this check (they see everything).

    Raises:
        HTTPException(403) if the hospital doesn't match.
    """
    if current_user.role == models.RoleEnum.SUPER_ADMIN:
        return  # Super admins see all tenants

    if entity_hospital_id != current_user.effective_hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied — resource belongs to a different organization.",
        )


# ═══════════════════════════════════════════════════════════════════════
# APPOINTMENT ACCESS
# ═══════════════════════════════════════════════════════════════════════


def verify_appointment_access(
    db: Session,
    appointment: models.Appointment,
    current_user: models.User,
) -> None:
    """
    Verify the current user has access to an appointment.

    Rules:
        - SUPER_ADMIN: access to all appointments (no restriction)
        - ADMIN: appointments within their hospital only
        - DOCTOR: only their own appointments
        - CAREGIVER: only appointments they booked

    Raises:
        HTTPException(403) if the user is not authorized.
    """
    if current_user.role == models.RoleEnum.SUPER_ADMIN:
        return

    # Hospital boundary — ADMIN, DOCTOR, CAREGIVER must be in the same hospital
    if appointment.hospital_id != current_user.effective_hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied — appointment belongs to a different organization.",
        )

    # ADMINs can see all appointments in their hospital
    if current_user.role == models.RoleEnum.ADMIN:
        return

    # DOCTOR must own the appointment
    if current_user.role == models.RoleEnum.DOCTOR:
        doctor_id = _resolve_doctor_id(db, current_user)
        if doctor_id and appointment.doctor_id == doctor_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied — you can only access your own appointments.",
        )

    # CAREGIVER must be the one who booked the appointment
    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver_id = _resolve_caregiver_id(db, current_user)
        if caregiver_id and appointment.caregiver_id == caregiver_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied — you can only access appointments you booked.",
        )

    # Catch-all deny
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied.",
    )


# ═══════════════════════════════════════════════════════════════════════
# PATIENT ACCESS
# ═══════════════════════════════════════════════════════════════════════


def verify_patient_access(
    db: Session,
    patient: models.Patient,
    current_user: models.User,
) -> None:
    """
    Verify the current user has access to a patient record.

    Rules:
        - SUPER_ADMIN: access to all patients
        - ADMIN: patients within their hospital only
        - DOCTOR: patients in their hospital only (they may see any
                  patient for cross-consultation, not just assigned ones)
        - CAREGIVER: only patients they manage

    Raises:
        HTTPException(403) if the user is not authorized.
    """
    if current_user.role == models.RoleEnum.SUPER_ADMIN:
        return

    # Hospital boundary for everyone else
    if patient.hospital_id != current_user.effective_hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied — patient belongs to a different organization.",
        )

    # ADMINs and DOCTORs can see any patient in their hospital
    if current_user.role in (models.RoleEnum.ADMIN, models.RoleEnum.DOCTOR):
        return

    # CAREGIVER must own the patient
    if current_user.role == models.RoleEnum.CAREGIVER:
        caregiver_id = _resolve_caregiver_id(db, current_user)
        if caregiver_id and patient.caregiver_id == caregiver_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied — you can only access patients you manage.",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied.",
    )
