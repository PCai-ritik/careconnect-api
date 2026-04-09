from sqlalchemy.orm import Session
from sqlalchemy import and_
from app import models, security
import uuid
from datetime import datetime

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
    db: Session, user_id: uuid.UUID, full_name: str, specialization: str
):
    db_doctor = models.Doctor(
        user_id=user_id, full_name=full_name, specialization=specialization
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
    db: Session, caregiver_id: uuid.UUID, hospital_id: uuid.UUID, patient_data: dict
):
    db_patient = models.Patient(
        caregiver_id=caregiver_id, hospital_id=hospital_id, **patient_data
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


# ═══════════════════════════════════════════════════════════════════════
# 5. CLINICAL (APPOINTMENTS, RECORDS, PRESCRIPTIONS)
# ═══════════════════════════════════════════════════════════════════════


def create_appointment(
    db: Session,
    hospital_id: uuid.UUID,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    caregiver_id: uuid.UUID,
    scheduled_time: datetime,
):
    db_appointment = models.Appointment(
        hospital_id=hospital_id,
        doctor_id=doctor_id,
        patient_id=patient_id,
        caregiver_id=caregiver_id,
        scheduled_time=scheduled_time,
    )
    db.add(db_appointment)
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
