"""
CareConnect — Doctor Notes Router

Endpoints:
  POST  /doctor-notes                  → Create a private note (Doctor only)
  GET   /doctor-notes/{appointment_id} → List notes for an appointment

Notes are private, real-time annotations taken by the doctor during a
video consultation. They serve as high-priority context for the AI
post-call summary pipeline.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid

from app import models, schemas, crud, database
from app.dependencies import get_current_user, require_role
from app.ownership import verify_appointment_access

router = APIRouter(prefix="/doctor-notes", tags=["Doctor Notes"])


# ═══════════════════════════════════════════════════════════════════════
# POST /doctor-notes — Create a note during a consultation
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "",
    response_model=schemas.DoctorNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_doctor_note(
    payload: schemas.DoctorNoteCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
):
    """
    Create a private doctor note for an appointment.

    Only Doctors can create notes. The doctor_id is auto-resolved
    from the current user's profile — no need to pass it explicitly.
    """
    # Resolve the doctor profile from the current user
    doctor = crud.get_doctor_by_user_id(db, user_id=current_user.id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found for current user.",
        )

    # Verify the appointment exists
    appointment = crud.get_appointment_by_id(db, payload.appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )

    # Verify this doctor owns the appointment
    if appointment.doctor_id != doctor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only add notes to your own appointments.",
        )

    note = crud.create_doctor_note(
        db=db,
        appointment_id=payload.appointment_id,
        doctor_id=doctor.id,
        content=payload.content,
    )
    return note


# ═══════════════════════════════════════════════════════════════════════
# GET /doctor-notes/{appointment_id} — List notes for an appointment
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/{appointment_id}",
    response_model=List[schemas.DoctorNoteResponse],
)
def list_doctor_notes(
    appointment_id: uuid.UUID,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR, models.RoleEnum.SUPER_ADMIN])
    ),
):
    """
    List all doctor notes for a given appointment.

    Only the owning Doctor or a Super Admin can view notes.
    Notes are returned in chronological order (oldest first).
    """
    # Verify the appointment exists
    appointment = crud.get_appointment_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )

    # Verify caller has access to this appointment (hospital + role check)
    verify_appointment_access(db, appointment, current_user)

    return crud.get_notes_by_appointment(db, appointment_id)
