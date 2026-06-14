"""
CareConnect — Appointments Router

Endpoints:
  POST   /appointments                   → Book a consultation
  GET    /appointments                   → List appointments (RLS-filtered)
  GET    /appointments/{id}              → Get single appointment detail
  GET    /appointments/{id}/summary      → Get AI post-call summary
  PATCH  /appointments/{id}/status       → Update appointment status
  POST   /appointments/{id}/start-session → Start video session (Doctor)
  GET    /appointments/{id}/join         → Get join token for current user
  GET    /appointments/{id}/join-patient → Public patient join (token-based)

All routes are protected by get_current_user, which:
  1. Validates the JWT
  2. SETs PostgreSQL RLS session variables for tenant isolation
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone, date as date_type
import uuid

from app import models, schemas, crud, database
from app.dependencies import get_current_user, require_role
from app.services import video

router = APIRouter(prefix="/appointments", tags=["Appointments"])


# ═══════════════════════════════════════════════════════════════════════
# POST /appointments — Book a consultation
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "",
    response_model=schemas.AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_appointment(
    payload: schemas.AppointmentCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Create a new appointment.
    - Doctors: must provide all IDs explicitly.
    - Caregivers: their hospital_id is auto-resolved; they must provide
      doctor_id and patient_id.
    """
    # Verify the doctor exists
    doctor = crud.get_doctor_by_id(db, payload.doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found",
        )

    # Check for slot collision — reject if the doctor already has an
    # active appointment overlapping this time window
    duration = payload.duration_minutes or 30
    if crud.check_slot_conflict(
        db,
        doctor_id=payload.doctor_id,
        scheduled_time=payload.scheduled_time,
        duration_minutes=duration,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This time slot is already booked. Please choose a different time.",
        )

    # Auto-resolve caregiver_id from the current user if not provided
    caregiver_id = payload.caregiver_id
    if not caregiver_id and current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = crud.get_caregiver_by_user_id(db, user_id=current_user.id)
        if caregiver:
            caregiver_id = caregiver.id

    appointment = crud.create_appointment(
        db=db,
        hospital_id=payload.hospital_id,
        doctor_id=payload.doctor_id,
        patient_id=payload.patient_id,
        caregiver_id=caregiver_id,
        scheduled_time=payload.scheduled_time,
        duration_minutes=duration,
        appointment_type=payload.appointment_type,
    )
    return appointment


# ═══════════════════════════════════════════════════════════════════════
# GET /appointments/available-slots — Available time slots for a doctor
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/available-slots",
    response_model=List[schemas.AvailableSlotResponse],
)
def get_available_slots(
    doctor_id: uuid.UUID = Query(..., description="Doctor to check slots for"),
    date: str = Query(..., description="Target date as YYYY-MM-DD"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Return available 15-minute time slots for a doctor on a given date.
    Uses the doctor's weekly availability schedule minus existing appointments.
    """
    try:
        target_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD.",
        )

    doctor = crud.get_doctor_by_id(db, doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found",
        )

    slots = crud.get_available_slots(db, doctor_id=doctor_id, target_date=target_date)
    return slots


# ═══════════════════════════════════════════════════════════════════════
# GET /appointments — List all appointments (RLS-scoped)
# ═══════════════════════════════════════════════════════════════════════


@router.get("", response_model=List[schemas.AppointmentResponse])
def list_appointments(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    List appointments scoped by role (application-level + RLS):
      - Doctor: only their own appointments
      - Caregiver: only appointments they booked
      - Admin: all appointments in their hospital
    """
    query = db.query(models.Appointment)

    if current_user.role == models.RoleEnum.DOCTOR:
        doctor = (
            db.query(models.Doctor.id)
            .filter(models.Doctor.user_id == current_user.id)
            .first()
        )
        if not doctor:
            return []
        query = query.filter(models.Appointment.doctor_id == doctor.id)
    elif current_user.role == models.RoleEnum.CAREGIVER:
        caregiver = (
            db.query(models.Caregiver.id)
            .filter(models.Caregiver.user_id == current_user.id)
            .first()
        )
        if not caregiver:
            return []
        query = query.filter(models.Appointment.caregiver_id == caregiver.id)
    else:
        # Admin / Super Admin — scope to hospital
        query = query.filter(models.Appointment.hospital_id == current_user.effective_hospital_id)


    return query.order_by(models.Appointment.scheduled_time.desc()).all()


# ═══════════════════════════════════════════════════════════════════════
# GET /appointments/{id} — Single appointment detail
# ═══════════════════════════════════════════════════════════════════════


@router.get("/{appointment_id}", response_model=schemas.AppointmentResponse)
def get_appointment(
    appointment_id: uuid.UUID,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Retrieve a single appointment by ID.
    RLS ensures the user can only see appointments they have access to.
    """
    appointment = crud.get_appointment_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    return appointment


# ═══════════════════════════════════════════════════════════════════════
# GET /appointments/{id}/summary — Post-call AI summary
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/{appointment_id}/summary",
    response_model=schemas.PostCallSummaryResponse,
)
def get_appointment_summary(
    appointment_id: uuid.UUID,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Retrieve the AI-generated post-call summary for an appointment.

    Accessible by both doctors and caregivers — RLS ensures they can only
    see summaries for their own appointments.  Returns 404 if the summary
    hasn't been generated yet (AI pipeline still running).
    """
    # First verify the appointment exists and the user has access (RLS)
    appointment = crud.get_appointment_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    summary = crud.get_post_call_summary(db, appointment_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Summary not yet available — the AI pipeline may still be processing.",
        )
    return summary


# ═══════════════════════════════════════════════════════════════════════
# PATCH /appointments/{id}/status — Update appointment status
# ═══════════════════════════════════════════════════════════════════════


@router.patch("/{appointment_id}/status", response_model=schemas.AppointmentResponse)
def update_appointment_status(
    appointment_id: uuid.UUID,
    payload: schemas.AppointmentStatusUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR, models.RoleEnum.SUPER_ADMIN])
    ),
):
    """
    Update the status of an appointment.
    Only Doctors and Admins can complete/cancel appointments.

    Valid transitions:
      CONFIRMED → IN_PROGRESS (consultation starts)
      IN_PROGRESS → COMPLETED (consultation ends)
      Any → CANCELLED (emergency reschedule)
    """
    appointment = crud.update_appointment_status(
        db, appointment_id, payload.status
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    return appointment


# ═══════════════════════════════════════════════════════════════════════
# POST /appointments/{id}/start-session — Start a video consultation
# Only Doctors can start a session. Creates the LiveKit room,
# generates join tokens for all three participants, and persists
# a VideoSession row.
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "/{appointment_id}/start-session",
    response_model=schemas.VideoJoinResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_video_session(
    appointment_id: uuid.UUID,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(
        require_role([models.RoleEnum.DOCTOR])
    ),
):
    """
    Start a video consultation for an appointment.

    1. Verifies the appointment exists.
    2. Ensures no session already exists (409 if duplicate).
    3. Creates a LiveKit room and generates join tokens for
       Doctor, Patient, and Caregiver.
    4. Persists a VideoSession row and moves the appointment to IN_PROGRESS.
    """
    # 1. Verify appointment exists
    appointment = crud.get_appointment_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    # 2. Standard Check (Catches normal sequential duplicates)
    existing = (
        db.query(models.VideoSession)
        .filter(models.VideoSession.appointment_id == appointment_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A video session already exists for this appointment.",
        )

    # 3. Create LiveKit room + generate tokens
    room_name = f"cc-{appointment_id}"
    video.create_room(room_name)

    doctor_token = video.create_join_token(
        room_name,
        identity=f"doctor-{appointment.doctor_id}",
        name="Doctor",
    )
    patient_token = video.create_join_token(
        room_name,
        identity=f"patient-{appointment.patient_id}",
        name="Patient",
    )
    caregiver_token = video.create_join_token(
        room_name,
        identity=f"caregiver-{appointment.caregiver_id}",
        name="Caregiver",
    )

    # 4. Persist VideoSession
    session = models.VideoSession(
        appointment_id=appointment_id,
        room_name=room_name,
        join_token_doctor=doctor_token,
        join_token_patient=patient_token,
        join_token_caregiver=caregiver_token,
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    appointment.status = models.AppointmentStatusEnum.IN_PROGRESS

    # 5. Commit with Race-Condition Protection
    #    Commit BEFORE starting Egress so that concurrent requests
    #    (e.g. React Strict Mode double-fire) hit IntegrityError here
    #    and bail out — only the winning request proceeds to step 6.
    from sqlalchemy.exc import IntegrityError
    try:
        db.commit()
        db.refresh(session)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A video session already exists for this appointment.",
        )

    # 6. Start Egress recording — AFTER commit succeeds.
    #    This guarantees only one Egress instance per appointment.
    #    Audio-only OGG saved to shared Docker volume (/out).
    #    When the call ends, LiveKit fires an 'egress_ended' webhook
    #    that triggers the AI pipeline (transcription → summary → DB).
    import logging
    try:
        video.start_room_composite_egress(room_name)
    except Exception as e:
        # Don't block the session if egress fails — the call can still
        # proceed, just without recording. Log the error for debugging.
        logging.getLogger(__name__).error(
            "Failed to start Egress recording for room %s: %s", room_name, e
        )

    return schemas.VideoJoinResponse(
        room_name=room_name,
        join_token=doctor_token,
        patient_join_token=patient_token,
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /appointments/{id}/join — Retrieve the caller's join token
# Returns the room name and the token that matches the current user's
# role (Doctor or Caregiver). Patient flow via WhatsApp is TBD.
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/{appointment_id}/join",
    response_model=schemas.VideoJoinResponse,
)
def get_join_token(
    appointment_id: uuid.UUID,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Retrieve the join token for the current user's role.

    - DOCTOR → join_token_doctor
    - CAREGIVER → join_token_caregiver
    - Patient flow (WhatsApp deep link) will be added later.
    """
    session = (
        db.query(models.VideoSession)
        .filter(models.VideoSession.appointment_id == appointment_id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video session found for this appointment.",
        )

    # Resolve the correct token based on the caller's role
    if current_user.role == models.RoleEnum.DOCTOR:
        token = session.join_token_doctor
    elif current_user.role == models.RoleEnum.CAREGIVER:
        token = session.join_token_caregiver
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient join flow is not yet supported via this endpoint.",
        )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Join token not available for your role.",
        )

    return schemas.VideoJoinResponse(
        room_name=session.room_name,
        join_token=token,
        patient_join_token=session.join_token_patient,
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /appointments/{id}/join-patient — Public patient join
# No auth required. The token query param acts as the credential.
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/{appointment_id}/join-patient",
    response_model=schemas.PatientJoinResponse,
)
def join_as_patient(
    appointment_id: uuid.UUID,
    token: str,
    db: Session = Depends(database.get_db),
):
    """
    Public patient join — no authentication required.

    The `token` query parameter is the pre-generated patient join token.
    We verify it matches the stored token, then return everything the
    patient's browser needs to connect to the LiveKit room.
    """
    from app.config import settings

    session = (
        db.query(models.VideoSession)
        .filter(models.VideoSession.appointment_id == appointment_id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video session found for this appointment.",
        )

    # Verify the token matches the stored patient token
    if token != session.join_token_patient:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid join token.",
        )

    return schemas.PatientJoinResponse(
        room_name=session.room_name,
        join_token=session.join_token_patient,
        livekit_url=settings.LIVEKIT_URL,
    )
