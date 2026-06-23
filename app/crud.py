from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from app import models, security
import uuid
from datetime import datetime, date as date_type, time as time_type, timedelta

# ═══════════════════════════════════════════════════════════════════════
# 1. HOSPITAL & TENANCY
# ═══════════════════════════════════════════════════════════════════════


async def create_hospital(db: AsyncSession, name: str, brand_color: str = "#4F46E5"):
    db_hospital = models.Hospital(name=name, brand_color=brand_color)
    db.add(db_hospital)
    await db.commit()
    await db.refresh(db_hospital)
    return db_hospital


async def get_hospital(db: AsyncSession, hospital_id: uuid.UUID):
    result = await db.execute(select(models.Hospital).where(models.Hospital.id == hospital_id))
    return result.scalars().first()


# ═══════════════════════════════════════════════════════════════════════
# 2. AUTHENTICATION & USERS
# ═══════════════════════════════════════════════════════════════════════


async def get_user_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(models.User).where(models.User.email == email))
    return result.scalars().first()


async def get_user_by_id(db: AsyncSession, user_id: str):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    return result.scalars().first()


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    hospital_id: uuid.UUID,
    role: models.RoleEnum,
):
    hashed_pw = security.hash_password(password)
    db_user = models.User(
        email=email,
        password_hash=hashed_pw,
        full_name=full_name,
        hospital_id=hospital_id,
        role=role,
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


# ═══════════════════════════════════════════════════════════════════════
# 3. DOCTOR PROFILES & AVAILABILITY
# ═══════════════════════════════════════════════════════════════════════


async def create_doctor_profile(
    db: AsyncSession, user_id: uuid.UUID, full_name: str, specialization: str,
    phone_number: str | None = None,
):
    db_doctor = models.Doctor(
        user_id=user_id, full_name=full_name, specialization=specialization,
        phone_number=phone_number,
    )
    db.add(db_doctor)
    await db.commit()
    await db.refresh(db_doctor)
    return db_doctor


async def update_doctor_onboarding(db: AsyncSession, doctor_id: uuid.UUID, update_data: dict):
    doctor = await get_doctor_by_id(db, doctor_id)
    if doctor:
        for key, value in update_data.items():
            setattr(doctor, key, value)
        await db.commit()
        await db.refresh(doctor)
    return doctor


async def get_doctor_by_id(db: AsyncSession, doctor_id: uuid.UUID):
    result = await db.execute(
        select(models.Doctor)
        .where(models.Doctor.id == doctor_id)
        .options(selectinload(models.Doctor.availability_slots))
    )
    return result.scalars().first()


async def get_doctor_by_user_id(db: AsyncSession, user_id: uuid.UUID):
    result = await db.execute(
        select(models.Doctor)
        .where(models.Doctor.user_id == user_id)
        .options(selectinload(models.Doctor.availability_slots))
    )
    return result.scalars().first()


async def get_caregiver_by_user_id(db: AsyncSession, user_id: uuid.UUID):
    result = await db.execute(
        select(models.Caregiver).where(models.Caregiver.user_id == user_id)
    )
    return result.scalars().first()


async def set_doctor_availability(db: AsyncSession, doctor_id: uuid.UUID, slots: list):
    # Clear existing slots first (standard practice for schedule updates)
    existing = await db.execute(
        select(models.DoctorAvailability).where(
            models.DoctorAvailability.doctor_id == doctor_id
        )
    )
    for slot_obj in existing.scalars().all():
        await db.delete(slot_obj)
    for slot in slots:
        new_slot = models.DoctorAvailability(doctor_id=doctor_id, **slot)
        db.add(new_slot)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════
# 4. CAREGIVER & PATIENT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════


async def create_caregiver_profile(
    db: AsyncSession, user_id: uuid.UUID, full_name: str, whatsapp_number: str
):
    db_caregiver = models.Caregiver(
        user_id=user_id, full_name=full_name, whatsapp_number=whatsapp_number
    )
    db.add(db_caregiver)
    await db.commit()
    await db.refresh(db_caregiver)
    return db_caregiver


async def create_patient(
    db: AsyncSession, caregiver_id: uuid.UUID | None, hospital_id: uuid.UUID, patient_data: dict,
    doctor_id: uuid.UUID | None = None,
):
    db_patient = models.Patient(
        caregiver_id=caregiver_id, hospital_id=hospital_id,
        doctor_id=doctor_id, **patient_data
    )
    db.add(db_patient)
    await db.commit()
    await db.refresh(db_patient)
    return db_patient


async def get_patients_by_caregiver(db: AsyncSession, caregiver_id: uuid.UUID):
    result = await db.execute(
        select(models.Patient).where(models.Patient.caregiver_id == caregiver_id)
    )
    return result.scalars().all()


async def update_patient(db: AsyncSession, patient_id: uuid.UUID, data: dict):
    """Update a patient record. Only non-None fields are applied."""
    result = await db.execute(select(models.Patient).where(models.Patient.id == patient_id))
    db_patient = result.scalars().first()
    if not db_patient:
        return None
    for key, value in data.items():
        if value is not None:
            setattr(db_patient, key, value)
    await db.commit()
    await db.refresh(db_patient)
    return db_patient


# ═══════════════════════════════════════════════════════════════════════
# 5. CLINICAL (APPOINTMENTS, RECORDS, PRESCRIPTIONS)
# ═══════════════════════════════════════════════════════════════════════


async def check_slot_conflict(
    db: AsyncSession,
    doctor_id: uuid.UUID,
    scheduled_time: datetime,
    duration_minutes: int = 30,
) -> bool:
    """
    Return True if the doctor already has a CONFIRMED or IN_PROGRESS
    appointment that overlaps the requested time window.

    Overlap condition (standard interval overlap):
      existing.start < requested.end  AND  requested.start < existing.end
    """
    from datetime import timedelta
    from sqlalchemy import and_, or_, case, extract

    requested_end = scheduled_time + timedelta(minutes=duration_minutes)

    # duration_minutes can be NULL — default to 30 via COALESCE
    existing_duration = case(
        (models.Appointment.duration_minutes.isnot(None), models.Appointment.duration_minutes),
        else_=30,
    )

    result = await db.execute(
        select(models.Appointment).where(
            models.Appointment.doctor_id == doctor_id,
            models.Appointment.status.in_([
                models.AppointmentStatusEnum.CONFIRMED,
                models.AppointmentStatusEnum.IN_PROGRESS,
            ]),
            # overlap: existing.start < requested.end
            models.Appointment.scheduled_time < requested_end,
            # overlap: requested.start < existing.end
            scheduled_time < models.Appointment.scheduled_time + timedelta(minutes=1) * existing_duration,
        )
    )
    conflict = result.scalars().first()
    return conflict is not None


async def create_appointment(
    db: AsyncSession,
    hospital_id: uuid.UUID,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    caregiver_id: uuid.UUID | None = None,
    scheduled_time: datetime | None = None,
    duration_minutes: int = 30,
    appointment_type: models.AppointmentTypeEnum = models.AppointmentTypeEnum.VIDEO,
    location_address: str | None = None,
):
    db_appointment = models.Appointment(
        hospital_id=hospital_id,
        doctor_id=doctor_id,
        patient_id=patient_id,
        caregiver_id=caregiver_id,
        scheduled_time=scheduled_time,
        duration_minutes=duration_minutes,
        appointment_type=appointment_type,
        location_address=location_address,
    )
    db.add(db_appointment)
    await db.commit()
    await db.refresh(db_appointment)
    return db_appointment


async def get_appointments(db: AsyncSession):
    """
    Fetch all appointments. RLS policies automatically filter by
    the session variables set in get_current_user (hospital, doctor/caregiver).
    """
    result = await db.execute(
        select(models.Appointment).order_by(models.Appointment.scheduled_time.desc())
    )
    return result.scalars().all()


async def get_appointment_by_id(db: AsyncSession, appointment_id: uuid.UUID):
    result = await db.execute(
        select(models.Appointment).where(models.Appointment.id == appointment_id)
    )
    return result.scalars().first()


async def update_appointment_status(
    db: AsyncSession, appointment_id: uuid.UUID, status: models.AppointmentStatusEnum
):
    db_appointment = await get_appointment_by_id(db, appointment_id)
    if not db_appointment:
        return None
    db_appointment.status = status
    await db.commit()
    await db.refresh(db_appointment)
    return db_appointment


async def create_medical_record(
    db: AsyncSession,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    appointment_id: uuid.UUID,
    diagnosis: str,
    vitals: dict,
):
    db_record = models.MedicalRecord(
        patient_id=patient_id,
        doctor_id=doctor_id,
        appointment_id=appointment_id,
        diagnosis=diagnosis,
        vitals=vitals,
    )
    db.add(db_record)
    await db.commit()
    await db.refresh(db_record)
    return db_record


async def get_records_by_patient(db: AsyncSession, patient_id: uuid.UUID):
    """
    Fetch all medical records for a patient, with prescriptions eager-loaded.
    RLS will automatically restrict visibility based on the user's role.
    """
    result = await db.execute(
        select(models.MedicalRecord)
        .where(models.MedicalRecord.patient_id == patient_id)
        .options(selectinload(models.MedicalRecord.prescriptions))
        .order_by(models.MedicalRecord.created_at.desc())
    )
    return result.scalars().all()


async def get_record_by_id(db: AsyncSession, record_id: uuid.UUID):
    result = await db.execute(
        select(models.MedicalRecord)
        .where(models.MedicalRecord.id == record_id)
        .options(selectinload(models.MedicalRecord.prescriptions))
    )
    return result.scalars().first()


async def add_prescriptions(
    db: AsyncSession,
    medical_record_id: uuid.UUID,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    meds_list: list,
):
    for med in meds_list:
        new_med = models.Prescription(
            medical_record_id=medical_record_id,
            doctor_id=doctor_id,
            patient_id=patient_id,
            **med,
        )
        db.add(new_med)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════
# 6. INFRASTRUCTURE & BUSINESS (VIDEO, TRANSACTIONS, AI)
# ═══════════════════════════════════════════════════════════════════════


async def create_video_session(db: AsyncSession, appointment_id: uuid.UUID, room_name: str):
    db_session = models.VideoSession(appointment_id=appointment_id, room_name=room_name)
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)
    return db_session


async def create_transaction(
    db: AsyncSession, doctor_id: uuid.UUID, amount: float, description: str
):
    db_tx = models.Transaction(
        doctor_id=doctor_id, amount=amount, description=description
    )
    db.add(db_tx)
    await db.commit()
    await db.refresh(db_tx)
    return db_tx


async def create_post_call_summary(
    db: AsyncSession, appointment_id: uuid.UUID, summary_data: dict
):
    db_summary = models.PostCallSummary(appointment_id=appointment_id, **summary_data)
    db.add(db_summary)
    await db.commit()
    await db.refresh(db_summary)
    return db_summary


async def get_post_call_summary(
    db: AsyncSession, appointment_id: uuid.UUID
):
    """Retrieve the AI-generated post-call summary for an appointment."""
    result = await db.execute(
        select(models.PostCallSummary).where(models.PostCallSummary.appointment_id == appointment_id)
    )
    return result.scalars().first()


async def get_available_slots(
    db: AsyncSession,
    doctor_id: uuid.UUID,
    target_date: date_type,
    slot_duration_minutes: int = 15,
    appointment_type: str | None = None,
) -> list:
    """
    Compute available time slots for a doctor on a given date.

    1. Look up the doctor's weekly availability for that day of week.
    2. Generate time slots of `slot_duration_minutes` within the window.
    3. Remove slots that conflict with existing CONFIRMED/IN_PROGRESS appointments.
    4. Return remaining available slots as [{start_time, end_time}, ...].
    """
    from sqlalchemy import func

    # Day name for lookup ("Monday", "Tuesday", etc.)
    day_name = target_date.strftime("%A").upper()

    # 1. Get doctor's availability windows for this day
    stmt = select(models.DoctorAvailability).where(
        models.DoctorAvailability.doctor_id == doctor_id,
        func.upper(models.DoctorAvailability.day_of_week) == day_name,
        models.DoctorAvailability.is_enabled == True,
    )
    
    if appointment_type:
        stmt = stmt.where(models.DoctorAvailability.appointment_type == appointment_type)

    result = await db.execute(stmt)
    availability = list(result.scalars().all())

    if not availability:
        return []

    # 2. Generate all possible slots from the availability windows
    all_slots = []
    for _window in availability:
        window: models.DoctorAvailability = _window
        current = datetime.combine(target_date, window.start_time)  # type: ignore
        window_end = datetime.combine(target_date, window.end_time)  # type: ignore
        while current + timedelta(minutes=slot_duration_minutes) <= window_end:
            slot_end = current + timedelta(minutes=slot_duration_minutes)
            all_slots.append({
                "start": current,
                "end": slot_end,
            })
            current = slot_end

    if not all_slots:
        return []

    # 3. Fetch existing appointments on this date
    day_start = datetime.combine(target_date, time_type(0, 0))
    day_end = datetime.combine(target_date, time_type(23, 59, 59))

    result = await db.execute(
        select(models.Appointment).where(
            models.Appointment.doctor_id == doctor_id,
            models.Appointment.status.in_([
                models.AppointmentStatusEnum.CONFIRMED,
                models.AppointmentStatusEnum.IN_PROGRESS,
                models.AppointmentStatusEnum.PENDING,
            ]),
            models.Appointment.scheduled_time >= day_start,
            models.Appointment.scheduled_time <= day_end,
        )
    )
    existing = result.scalars().all()

    # Build list of busy intervals
    busy = []
    for _appt in existing:
        appt: models.Appointment = _appt
        appt_duration = appt.duration_minutes or 30  # type: ignore
        appt_start = appt.scheduled_time.replace(tzinfo=None)  # type: ignore
        appt_end = appt_start + timedelta(minutes=appt_duration)  # type: ignore
        busy.append((appt_start, appt_end))

    # 4. Filter out conflicting slots
    available = []
    for slot in all_slots:
        conflicts = any(
            slot["start"] < busy_end and slot["end"] > busy_start
            for busy_start, busy_end in busy
        )
        if not conflicts:
            available.append({
                "start_time": slot["start"].strftime("%H:%M"),
                "end_time": slot["end"].strftime("%H:%M"),
            })

    return available


# ═══════════════════════════════════════════════════════════════════════
# 7. DOCTOR NOTES
# ═══════════════════════════════════════════════════════════════════════


async def create_doctor_note(
    db: AsyncSession,
    appointment_id: uuid.UUID,
    doctor_id: uuid.UUID,
    content: str,
):
    """Create a private doctor note linked to an appointment."""
    db_note = models.DoctorNote(
        appointment_id=appointment_id,
        doctor_id=doctor_id,
        content=content,
    )
    db.add(db_note)
    await db.commit()
    await db.refresh(db_note)
    return db_note


async def get_notes_by_appointment(db: AsyncSession, appointment_id: uuid.UUID):
    """Fetch all doctor notes for a given appointment, oldest first."""
    result = await db.execute(
        select(models.DoctorNote)
        .where(models.DoctorNote.appointment_id == appointment_id)
        .order_by(models.DoctorNote.created_at.asc())
    )
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# ACCESS CONTROL: Doctor Profile Access for Caregivers
# ═══════════════════════════════════════════════════════════════════════


async def can_caregiver_access_doctor(
    db: AsyncSession, caregiver_id: uuid.UUID, doctor_id: uuid.UUID
) -> bool:
    """
    Check if a caregiver can access a doctor's profile.
    Returns True if the doctor has created medical records for any patient
    assigned to this caregiver.
    """
    stmt = (
        select(models.MedicalRecord)
        .join(models.Patient, models.MedicalRecord.patient_id == models.Patient.id)
        .where(
            models.Patient.caregiver_id == caregiver_id,
            models.MedicalRecord.doctor_id == doctor_id,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first() is not None

