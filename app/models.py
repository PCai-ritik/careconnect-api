import uuid
import enum
from datetime import datetime, date, time
from sqlalchemy import (
    String, DateTime, Date, Time, Integer, Numeric,
    ForeignKey, Text, Boolean, Enum, Float,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ═══════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════

class RoleEnum(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    DOCTOR = "DOCTOR"
    CAREGIVER = "CAREGIVER"


class AppointmentStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentTypeEnum(str, enum.Enum):
    VIDEO = "VIDEO"
    FOLLOW_UP = "FOLLOW_UP"
    NEW_PATIENT = "NEW_PATIENT"
    IN_PERSON = "IN_PERSON"


class VideoProviderEnum(str, enum.Enum):
    LIVEKIT = "LIVEKIT"
    AGORA = "AGORA"


class TransactionStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


# ═══════════════════════════════════════════════════════════════════════
# CORE MODELS
# ═══════════════════════════════════════════════════════════════════════


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_color: Mapped[str] = mapped_column(String(7), default="#4F46E5")
    logo_url: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    users = relationship("User", back_populates="hospital")
    patients = relationship("Patient", back_populates="hospital")
    appointments = relationship("Appointment", back_populates="hospital")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hospitals.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleEnum] = mapped_column(Enum(RoleEnum), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    hospital = relationship("Hospital", back_populates="users")
    doctor_profile = relationship("Doctor", back_populates="user", uselist=False)
    caregiver_profile = relationship("Caregiver", back_populates="user", uselist=False)


# ═══════════════════════════════════════════════════════════════════════
# DOCTOR (expanded for onboarding — spec 2.3)
# ═══════════════════════════════════════════════════════════════════════


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )

    # Basic profile
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialization: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str] = mapped_column(String, nullable=True)

    # Verification / onboarding fields
    hospital_affiliation: Mapped[str] = mapped_column(String(255), nullable=True)
    years_of_experience: Mapped[str] = mapped_column(String(50), nullable=True)
    bio: Mapped[str] = mapped_column(Text, nullable=True)
    license_number: Mapped[str] = mapped_column(String(100), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Consultation settings
    consultation_duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=True
    )
    consultation_fee: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    accepted_payment_methods: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # e.g. ["upi", "card", "netbanking", "cash"]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user = relationship("User", back_populates="doctor_profile")
    availability_slots = relationship("DoctorAvailability", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    prescriptions = relationship("Prescription", back_populates="doctor")
    earnings = relationship("Transaction", back_populates="doctor")


class DoctorAvailability(Base):
    """Per-day availability slots — matches the onboarding schedule grid."""
    __tablename__ = "doctor_availability"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id"), nullable=False
    )
    day_of_week: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "Monday", "Tuesday", etc.
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    # Relationships
    doctor = relationship("Doctor", back_populates="availability_slots")


# ═══════════════════════════════════════════════════════════════════════
# CAREGIVER
# ═══════════════════════════════════════════════════════════════════════


class Caregiver(Base):
    __tablename__ = "caregivers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    whatsapp_number: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user = relationship("User", back_populates="caregiver_profile")
    patients = relationship("Patient", back_populates="caregiver")
    appointments = relationship("Appointment", back_populates="caregiver")


# ═══════════════════════════════════════════════════════════════════════
# PATIENT (expanded — spec 2.2 + 2.4)
# ═══════════════════════════════════════════════════════════════════════


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("caregivers.id"), nullable=False
    )
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hospitals.id"), nullable=False
    )

    # Core info
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    whatsapp_number: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=True)
    gender: Mapped[str] = mapped_column(String(50), nullable=True)
    blood_group: Mapped[str] = mapped_column(String(10), nullable=True)
    address: Mapped[str] = mapped_column(Text, nullable=True)
    aadhar_number: Mapped[str] = mapped_column(String(14), nullable=True)

    # Medical info (structured)
    allergies: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # e.g. ["Penicillin", "Sulfa Drugs"]
    existing_conditions: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # e.g. ["Hypertension", "Asthma"]
    medical_history_summary: Mapped[str] = mapped_column(Text, nullable=True)

    # Emergency contact
    emergency_contact_name: Mapped[str] = mapped_column(String(255), nullable=True)
    emergency_contact_phone: Mapped[str] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    caregiver = relationship("Caregiver", back_populates="patients")
    hospital = relationship("Hospital", back_populates="patients")
    appointments = relationship("Appointment", back_populates="patient")
    medical_records = relationship("MedicalRecord", back_populates="patient")


# ═══════════════════════════════════════════════════════════════════════
# APPOINTMENT (expanded — spec 2.5)
# ═══════════════════════════════════════════════════════════════════════


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hospitals.id"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id"), nullable=False
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("caregivers.id"), nullable=False
    )

    scheduled_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=True)
    appointment_type: Mapped[AppointmentTypeEnum] = mapped_column(
        Enum(AppointmentTypeEnum), default=AppointmentTypeEnum.VIDEO
    )
    status: Mapped[AppointmentStatusEnum] = mapped_column(
        Enum(AppointmentStatusEnum), default=AppointmentStatusEnum.PENDING
    )
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    meeting_room_id: Mapped[str] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    hospital = relationship("Hospital", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    patient = relationship("Patient", back_populates="appointments")
    caregiver = relationship("Caregiver", back_populates="appointments")
    video_session = relationship("VideoSession", back_populates="appointment", uselist=False)
    post_call_summary = relationship("PostCallSummary", back_populates="appointment", uselist=False)
    medical_record = relationship("MedicalRecord", back_populates="appointment", uselist=False)


# ═══════════════════════════════════════════════════════════════════════
# NEW TABLE: MEDICAL RECORD
# ═══════════════════════════════════════════════════════════════════════


class MedicalRecord(Base):
    """
    One record per consultation. Maps to MockMedicalRecord (mobile)
    and ConsultationRecord (web PatientProfileSheet).
    """
    __tablename__ = "medical_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id"), nullable=False
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id"), nullable=True, unique=True
    )

    diagnosis: Mapped[str] = mapped_column(String(500), nullable=False)
    symptoms: Mapped[str] = mapped_column(Text, nullable=True)
    treatment: Mapped[str] = mapped_column(Text, nullable=True)
    follow_up_date: Mapped[date] = mapped_column(Date, nullable=True)

    # Vitals snapshot (from web ConsultationRecord)
    vitals: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # e.g. {"bp": "120/80", "pulse": "72 bpm", "temp": "98.6°F", "weight": "70 kg"}

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    patient = relationship("Patient", back_populates="medical_records")
    doctor = relationship("Doctor")
    appointment = relationship("Appointment", back_populates="medical_record")
    prescriptions = relationship("Prescription", back_populates="medical_record")


# ═══════════════════════════════════════════════════════════════════════
# NEW TABLE: PRESCRIPTION
# ═══════════════════════════════════════════════════════════════════════


class Prescription(Base):
    """
    Individual prescription line items. Links to a MedicalRecord
    and the issuing Doctor. Maps to NewPrescriptionSheet (web).
    """
    __tablename__ = "prescriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    medical_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medical_records.id"), nullable=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id"), nullable=False
    )

    medication_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[str] = mapped_column(String(100), nullable=True)
    frequency: Mapped[str] = mapped_column(String(100), nullable=True)
    duration: Mapped[str] = mapped_column(String(100), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    medical_record = relationship("MedicalRecord", back_populates="prescriptions")
    doctor = relationship("Doctor", back_populates="prescriptions")
    patient = relationship("Patient")


# ═══════════════════════════════════════════════════════════════════════
# NEW TABLE: VIDEO SESSION
# ═══════════════════════════════════════════════════════════════════════


class VideoSession(Base):
    """
    Tracks video call sessions. Stores provider tokens and the
    WhatsApp join-link token for frictionless patient entry (Pivot #2).
    """
    __tablename__ = "video_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id"), unique=True, nullable=False
    )
    provider: Mapped[VideoProviderEnum] = mapped_column(
        Enum(VideoProviderEnum), default=VideoProviderEnum.LIVEKIT
    )
    room_name: Mapped[str] = mapped_column(String(255), nullable=False)
    join_token_patient: Mapped[str] = mapped_column(
        String(500), nullable=True
    )  # Single-tap WhatsApp link token
    join_token_doctor: Mapped[str] = mapped_column(String(500), nullable=True)
    join_token_caregiver: Mapped[str] = mapped_column(String(500), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    appointment = relationship("Appointment", back_populates="video_session")


# ═══════════════════════════════════════════════════════════════════════
# NEW TABLE: TRANSACTION (Earnings)
# ═══════════════════════════════════════════════════════════════════════


class Transaction(Base):
    """
    Payment records for doctor earnings. Maps to the
    Earnings page (web) transaction list.
    """
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id"), nullable=False
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id"), nullable=True
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    status: Mapped[TransactionStatusEnum] = mapped_column(
        Enum(TransactionStatusEnum), default=TransactionStatusEnum.PENDING
    )
    direction: Mapped[str] = mapped_column(
        String(10), default="in"
    )  # "in" (earning) or "out" (payout)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    doctor = relationship("Doctor", back_populates="earnings")
    appointment = relationship("Appointment")


# ═══════════════════════════════════════════════════════════════════════
# NEW TABLE: POST-CALL SUMMARY
# ═══════════════════════════════════════════════════════════════════════


class PostCallSummary(Base):
    """
    AI-generated post-call summary. Maps to post-call-summary.tsx
    (mobile) and mockPostCallSummary in mock-data.ts.
    """
    __tablename__ = "post_call_summaries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id"), unique=True, nullable=False
    )

    diagnosis: Mapped[str] = mapped_column(String(500), nullable=True)
    symptoms: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # e.g. ["Cough", "Mild fever", "Sore throat"]
    treatment_plan: Mapped[str] = mapped_column(Text, nullable=True)
    prescriptions: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # e.g. ["Amoxicillin 500mg (3x daily for 5 days)"]
    follow_up: Mapped[str] = mapped_column(String(255), nullable=True)
    doctor_notes: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    appointment = relationship("Appointment", back_populates="post_call_summary")
