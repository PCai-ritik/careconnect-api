from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List, Dict
from datetime import datetime, date, time
import uuid
from app.models import (
    RoleEnum,
    AppointmentStatusEnum,
    AppointmentTypeEnum,
    VideoProviderEnum,
    TransactionStatusEnum,
)

# ═══════════════════════════════════════════════════════════════════════
# SHARED CONFIG
# ═══════════════════════════════════════════════════════════════════════


class BaseSchema(BaseModel):
    # This allows Pydantic to read data from SQLAlchemy objects
    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════════
# AUTH & USER SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class UserBase(BaseSchema):
    email: EmailStr
    full_name: str
    hospital_id: uuid.UUID
    role: RoleEnum


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class DoctorRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    hospital_id: Optional[uuid.UUID] = None
    specialization: Optional[str] = ""
    phone_number: Optional[str] = None


class CaregiverRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    hospital_id: Optional[uuid.UUID] = None
    whatsapp_number: str


class UserResponse(UserBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: uuid.UUID
    role: str


class TokenData(BaseModel):
    user_id: Optional[str] = None
    hospital_id: Optional[str] = None
    role: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# HOSPITAL SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class HospitalBase(BaseSchema):
    name: str
    brand_color: str = "#4F46E5"
    logo_url: Optional[str] = None


class HospitalCreate(HospitalBase):
    pass


class HospitalResponse(HospitalBase):
    id: uuid.UUID
    created_at: datetime


class HospitalListItem(BaseSchema):
    """Lightweight hospital info for registration dropdowns."""
    id: uuid.UUID
    name: str


class HospitalBrandingResponse(BaseSchema):
    """Hospital branding for white-label theming."""
    name: str
    brand_color: str
    logo_url: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# CAREGIVER SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class CaregiverBase(BaseSchema):
    full_name: str
    whatsapp_number: str


class CaregiverCreate(CaregiverBase):
    user_id: uuid.UUID


class CaregiverResponse(CaregiverBase):
    id: uuid.UUID
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════
# DOCTOR & AVAILABILITY
# ═══════════════════════════════════════════════════════════════════════


class DoctorAvailabilityBase(BaseSchema):
    day_of_week: str
    start_time: time
    end_time: time
    is_enabled: bool = True


class DoctorAvailabilityCreate(DoctorAvailabilityBase):
    pass


class DoctorBase(BaseSchema):
    full_name: str
    specialization: str
    phone_number: Optional[str] = None
    avatar_url: Optional[str] = None
    hospital_affiliation: Optional[str] = None
    years_of_experience: Optional[str] = None
    bio: Optional[str] = None
    license_number: Optional[str] = None
    consultation_duration_minutes: Optional[int] = 30
    consultation_fee: Optional[float] = None
    currency: str = "INR"
    accepted_payment_methods: Optional[List[str]] = None


class DoctorCreate(DoctorBase):
    user_id: uuid.UUID


class DoctorUpdate(DoctorBase):
    onboarding_completed: bool = True


class DoctorResponse(DoctorBase):
    id: uuid.UUID
    onboarding_completed: bool
    availability_slots: List[DoctorAvailabilityBase] = []


# ═══════════════════════════════════════════════════════════════════════
# PATIENT & MEDICAL SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class PatientBase(BaseSchema):
    full_name: str
    whatsapp_number: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    address: Optional[str] = None
    aadhar_number: Optional[str] = None
    allergies: Optional[List[str]] = None
    existing_conditions: Optional[List[str]] = None
    medical_history_summary: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class PatientCreate(PatientBase):
    caregiver_id: Optional[uuid.UUID] = None
    doctor_id: Optional[uuid.UUID] = None
    hospital_id: Optional[uuid.UUID] = None
    aadhar_number: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class PatientResponse(PatientBase):
    id: uuid.UUID
    doctor_id: Optional[uuid.UUID] = None
    hospital_id: uuid.UUID
    created_at: datetime


class PatientUpdate(BaseSchema):
    """Partial update — all fields optional."""
    full_name: Optional[str] = None
    whatsapp_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    address: Optional[str] = None
    aadhar_number: Optional[str] = None
    allergies: Optional[List[str]] = None
    existing_conditions: Optional[List[str]] = None
    medical_history_summary: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    doctor_id: Optional[uuid.UUID] = None


# ═══════════════════════════════════════════════════════════════════════
# CLINICAL SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class AppointmentBase(BaseSchema):
    scheduled_time: datetime
    duration_minutes: Optional[int] = 30
    appointment_type: AppointmentTypeEnum = AppointmentTypeEnum.VIDEO
    reason: Optional[str] = None


class AppointmentCreate(AppointmentBase):
    doctor_id: uuid.UUID
    appointment_type: AppointmentTypeEnum = AppointmentTypeEnum.VIDEO
    patient_id: uuid.UUID
    caregiver_id: Optional[uuid.UUID] = None
    hospital_id: uuid.UUID


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatusEnum


class AppointmentResponse(AppointmentBase):
    id: uuid.UUID
    hospital_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    caregiver_id: Optional[uuid.UUID] = None
    status: AppointmentStatusEnum
    meeting_room_id: Optional[str] = None
    created_at: datetime


class PrescriptionBase(BaseSchema):
    medication_name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    notes: Optional[str] = None


class PrescriptionCreate(PrescriptionBase):
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    medical_record_id: Optional[uuid.UUID] = None


class PrescriptionResponse(PrescriptionBase):
    id: uuid.UUID
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    medical_record_id: Optional[uuid.UUID] = None
    created_at: datetime


class MedicalRecordBase(BaseSchema):
    diagnosis: str
    symptoms: Optional[str] = None
    treatment: Optional[str] = None
    follow_up_date: Optional[date] = None
    vitals: Optional[Dict[str, str]] = None


class MedicalRecordCreate(MedicalRecordBase):
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    prescriptions: List[PrescriptionBase] = []


class MedicalRecordResponse(MedicalRecordBase):
    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    prescriptions: List[PrescriptionResponse] = []
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════
# VIDEO SESSION SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class VideoSessionCreate(BaseSchema):
    appointment_id: uuid.UUID
    room_name: str
    provider: VideoProviderEnum = VideoProviderEnum.LIVEKIT


class VideoSessionResponse(BaseSchema):
    id: uuid.UUID
    appointment_id: uuid.UUID
    provider: VideoProviderEnum
    room_name: str
    join_token_patient: Optional[str] = None
    join_token_doctor: Optional[str] = None
    join_token_caregiver: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime


class VideoJoinResponse(BaseSchema):
    """Lightweight response for join endpoints — returns only the caller's token."""
    room_name: str
    join_token: str
    patient_join_token: Optional[str] = None


class PatientJoinResponse(BaseSchema):
    """Response for the public patient join endpoint. Includes livekit_url
    because the patient has no app config — everything comes from this response."""
    room_name: str
    join_token: str
    livekit_url: str


# ═══════════════════════════════════════════════════════════════════════
# TRANSACTION SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class TransactionCreate(BaseSchema):
    doctor_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    description: str
    amount: float
    currency: str = "INR"
    direction: str = "in"


class TransactionResponse(BaseSchema):
    id: uuid.UUID
    doctor_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    description: str
    amount: float
    currency: str
    status: TransactionStatusEnum
    direction: str
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════
# POST-CALL SUMMARY SCHEMAS
# ═══════════════════════════════════════════════════════════════════════


class PostCallSummaryCreate(BaseSchema):
    appointment_id: uuid.UUID
    diagnosis: Optional[str] = None
    symptoms: Optional[List[str]] = None
    treatment_plan: Optional[str] = None
    prescriptions: Optional[List[str]] = None
    follow_up: Optional[str] = None
    doctor_notes: Optional[str] = None


class PostCallSummaryResponse(BaseSchema):
    id: uuid.UUID
    appointment_id: uuid.UUID
    diagnosis: Optional[str] = None
    symptoms: Optional[List[str]] = None
    treatment_plan: Optional[str] = None
    prescriptions: Optional[List[str]] = None
    follow_up: Optional[str] = None
    doctor_notes: Optional[str] = None
    summary: Optional[str] = None          # Full bilingual JSON from the AI pipeline
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════════════


class DashboardStatsResponse(BaseSchema):
    """Aggregated stats for the doctor's dashboard home page."""
    avg_consult_minutes: int = 0
    total_completed: int = 0


# ═══════════════════════════════════════════════════════════════════════
# AVAILABLE SLOTS
# ═══════════════════════════════════════════════════════════════════════


class AvailableSlotResponse(BaseSchema):
    """A single available time slot on a given day."""
    start_time: str   # HH:MM
    end_time: str     # HH:MM


# ═══════════════════════════════════════════════════════════════════════
# DOCTOR NOTES
# ═══════════════════════════════════════════════════════════════════════


class DoctorNoteCreate(BaseSchema):
    """Create a private note during a consultation."""
    appointment_id: uuid.UUID
    content: str


class DoctorNoteResponse(BaseSchema):
    """Doctor note with server-assigned fields."""
    id: uuid.UUID
    appointment_id: uuid.UUID
    doctor_id: uuid.UUID
    content: str
    created_at: datetime