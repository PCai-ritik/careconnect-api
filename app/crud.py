from sqlalchemy.orm import Session
from sqlalchemy import and_
from app import models, security
import uuid
from datetime import datetime, date as date_type, time as time_type, timedelta

# ═══════════════════════════════════════════════════════════════════════
# 1. HOSPITAL & TENANCY
# ═══════════════════════════════════════════════════════════════════════


def create_hospital(db: Session, name: str, brand_color: str = "#4F46E5"):
    db_hospital = models.Hospital(name=name, brand_color=brand_color)
    db.add(db_hospital)
    db.commit()
    db.refresh(db_hospital)
    return db_hospital


def get_hospital(db: Session, hospital_id: uuid.UUID):
    return db.query(models.Hospital).filter(models.Hospital.id == hospital_id).first()


# ═══════════════════════════════════════════════════════════════════════
# 2. AUTHENTICATION & USERS
# ═══════════════════════════════════════════════════════════════════════


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def get_user_by_id(db: Session, user_id: str):
    return db.query(models.User).filter(models.User.id == user_id).first()


def create_user(
    db: Session,
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
    db.commit()
    db.refresh(db_user)
    return db_user


# ═══════════════════════════════════════════════════════════════════════
# 3. DOCTOR PROFILES & AVAILABILITY
# ═══════════════════════════════════════════════════════════════════════


def create_doctor_profile(
    db: Session, user_id: uuid.UUID, full_name: str, specialization: str,
    phone_number: str = None,
):
    db_doctor = models.Doctor(
        user_id=user_id, full_name=full_name, specialization=specialization,
        phone_number=phone_number,
    )
    db.add(db_doctor)
    db.commit()
    db.refresh(db_doctor)
    return db_doctor


def update_doctor_onboarding(db: Session, doctor_id: uuid.UUID, update_data: dict):
    db.query(models.Doctor).filter(models.Doctor.id == doctor_id).update(update_data)
    db.commit()
    return get_doctor_by_id(db, doctor_id)


def get_doctor_by_id(db: Session, doctor_id: uuid.UUID):
    return db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()


def get_doctor_by_user_id(db: Session, user_id: uuid.UUID):
    return db.query(models.Doctor).filter(models.Doctor.user_id == user_id).first()


def get_caregiver_by_user_id(db: Session, user_id: uuid.UUID):
    return (
        db.query(models.Caregiver)
        .filter(models.Caregiver.user_id == user_id)
        .first()
    )


def set_doctor_availability(db: Session, doctor_id: uuid.UUID, slots: list):
    # Clear existing slots first (standard practice for schedule updates)
    db.query(models.DoctorAvailability).filter(
        models.DoctorAvailability.doctor_id == doctor_id
    ).delete()
    for slot in slots:
        new_slot = models.DoctorAvailability(doctor_id=doctor_id, **slot)
        db.add(new_slot)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════
# 4. CAREGIVER & PATIENT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════


def create_caregiver_profile(
    db: Session, user_id: uuid.UUID, full_name: str, whatsapp_number: str
):
    db_caregiver = models.Caregiver(
        user_id=user_id, full_name=full_name, whatsapp_number=whatsapp_number
    )
    db.add(db_caregiver)
    db.commit()
    db.refresh(db_caregiver)
    return db_caregiver


def create_patient(
    db: Session, caregiver_id: uuid.UUID, hospital_id: uuid.UUID, patient_data: dict,
    doctor_id: uuid.UUID = None,
):
    db_patient = models.Patient(
        caregiver_id=caregiver_id, hospital_id=hospital_id,
        doctor_id=doctor_id, **patient_data
    )
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    return db_patient


def get_patients_by_caregiver(db: Session, caregiver_id: uuid.UUID):
    return (
        db.query(models.Patient)
        .filter(models.Patient.caregiver_id == caregiver_id)
        .all()
    )


def update_patient(db: Session, patient_id: uuid.UUID, data: dict):
    """Update a patient record. Only non-None fields are applied."""
    db_patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not db_patient:
        return None
    for key, value in data.items():
        if value is not None:
            setattr(db_patient, key, value)
    db.commit()
    db.refresh(db_patient)
    return db_patient


# ═══════════════════════════════════════════════════════════════════════
# 5. CLINICAL (APPOINTMENTS, RECORDS, PRESCRIPTIONS)
# ═══════════════════════════════════════════════════════════════════════


def check_slot_conflict(
    db: Session,
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

    conflict = (
        db.query(models.Appointment)
        .filter(
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
        .first()
    )
    return conflict is not None


def create_appointment(
    db: Session,
    hospital_id: uuid.UUID,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    caregiver_id: uuid.UUID = None,
    scheduled_time: datetime = None,
    duration_minutes: int = 30,
    appointment_type: models.AppointmentTypeEnum = models.AppointmentTypeEnum.VIDEO,
):
    db_appointment = models.Appointment(
        hospital_id=hospital_id,
        doctor_id=doctor_id,
        patient_id=patient_id,
        caregiver_id=caregiver_id,
        scheduled_time=scheduled_time,
        duration_minutes=duration_minutes,
        appointment_type=appointment_type,
    )
    db.add(db_appointment)
    db.commit()
    db.refresh(db_appointment)
    return db_appointment


def get_appointments(db: Session):
    """
    Fetch all appointments. RLS policies automatically filter by
    the session variables set in get_current_user (hospital, doctor/caregiver).
    """
    return (
        db.query(models.Appointment)
        .order_by(models.Appointment.scheduled_time.desc())
        .all()
    )


def get_appointment_by_id(db: Session, appointment_id: uuid.UUID):
    return (
        db.query(models.Appointment)
        .filter(models.Appointment.id == appointment_id)
        .first()
    )


def update_appointment_status(
    db: Session, appointment_id: uuid.UUID, status: models.AppointmentStatusEnum
):
    db_appointment = get_appointment_by_id(db, appointment_id)
    if not db_appointment:
        return None
    db_appointment.status = status
    db.commit()
    db.refresh(db_appointment)
    return db_appointment


def create_medical_record(
    db: Session,
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
    db.commit()
    db.refresh(db_record)
    return db_record


def get_records_by_patient(db: Session, patient_id: uuid.UUID):
    """
    Fetch all medical records for a patient, with prescriptions eager-loaded.
    RLS will automatically restrict visibility based on the user's role.
    """
    return (
        db.query(models.MedicalRecord)
        .filter(models.MedicalRecord.patient_id == patient_id)
        .order_by(models.MedicalRecord.created_at.desc())
        .all()
    )


def get_record_by_id(db: Session, record_id: uuid.UUID):
    return (
        db.query(models.MedicalRecord)
        .filter(models.MedicalRecord.id == record_id)
        .first()
    )


def add_prescriptions(
    db: Session,
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
    db.commit()


# ═══════════════════════════════════════════════════════════════════════
# 6. INFRASTRUCTURE & BUSINESS (VIDEO, TRANSACTIONS, AI)
# ═══════════════════════════════════════════════════════════════════════


def create_video_session(db: Session, appointment_id: uuid.UUID, room_name: str):
    db_session = models.VideoSession(appointment_id=appointment_id, room_name=room_name)
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session


def create_transaction(
    db: Session, doctor_id: uuid.UUID, amount: float, description: str
):
    db_tx = models.Transaction(
        doctor_id=doctor_id, amount=amount, description=description
    )
    db.add(db_tx)
    db.commit()
    db.refresh(db_tx)
    return db_tx


def create_post_call_summary(
    db: Session, appointment_id: uuid.UUID, summary_data: dict
):
    db_summary = models.PostCallSummary(appointment_id=appointment_id, **summary_data)
    db.add(db_summary)
    db.commit()
    db.refresh(db_summary)
    return db_summary


def get_available_slots(
    db: Session,
    doctor_id: uuid.UUID,
    target_date: date_type,
    slot_duration_minutes: int = 15,
) -> list:
    """
    Compute available time slots for a doctor on a given date.

    1. Look up the doctor's weekly availability for that day of week.
    2. Generate time slots of `slot_duration_minutes` within the window.
    3. Remove slots that conflict with existing CONFIRMED/IN_PROGRESS appointments.
    4. Return remaining available slots as [{start_time, end_time}, ...].
    """
    # Day name for lookup ("Monday", "Tuesday", etc.)
    day_name = target_date.strftime("%A")

    # 1. Get doctor's availability windows for this day
    availability = (
        db.query(models.DoctorAvailability)
        .filter(
            models.DoctorAvailability.doctor_id == doctor_id,
            models.DoctorAvailability.day_of_week == day_name,
            models.DoctorAvailability.is_enabled == True,
        )
        .all()
    )

    if not availability:
        return []

    # 2. Generate all possible slots from the availability windows
    all_slots = []
    for window in availability:
        current = datetime.combine(target_date, window.start_time)
        window_end = datetime.combine(target_date, window.end_time)
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

    existing = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.doctor_id == doctor_id,
            models.Appointment.status.in_([
                models.AppointmentStatusEnum.CONFIRMED,
                models.AppointmentStatusEnum.IN_PROGRESS,
                models.AppointmentStatusEnum.PENDING,
            ]),
            models.Appointment.scheduled_time >= day_start,
            models.Appointment.scheduled_time <= day_end,
        )
        .all()
    )

    # Build list of busy intervals
    busy = []
    for appt in existing:
        appt_duration = appt.duration_minutes or 30
        appt_start = appt.scheduled_time.replace(tzinfo=None)
        appt_end = appt_start + timedelta(minutes=appt_duration)
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
