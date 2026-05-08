# CareConnect API — Complete End-to-End Testing Guide

> **Base URL:** `http://localhost:8000`
> **Start the server:** `uvicorn app.main:app --reload`
>
> This guide walks through EVERY endpoint in order. Each step uses UUIDs
> returned by previous steps — copy-paste from responses as you go.

---

## PHASE 0 — Setup: You Need a Hospital First

Before anything works, you need a `hospital_id`. If you don't have one,
create it directly in your database:

```sql
INSERT INTO hospitals (id, name, brand_color)
VALUES (gen_random_uuid(), 'CareConnect Demo Hospital', '#4F46E5')
RETURNING id;
```

Save the returned `id` — you'll use it as `{{hospital_id}}` everywhere below.

---

## STEP 1 — Register a Doctor

```
POST http://localhost:8000/auth/register/doctor
Content-Type: application/json
```

```json
{
    "email": "dr.rohan@careconnect.in",
    "password": "SecurePass123!",
    "full_name": "Dr. Rohan Mehta",
    "hospital_id": "{{hospital_id}}",
    "specialization": "General Practice"
}
```

**Response:** `201 Created`
```json
{
    "id": "{{doctor_user_id}}",   ← SAVE THIS
    "email": "dr.rohan@careconnect.in",
    "full_name": "Dr. Rohan Mehta",
    "hospital_id": "{{hospital_id}}",
    "role": "DOCTOR",
    "is_active": true,
    "created_at": "..."
}
```

---

## STEP 2 — Register a Caregiver

```
POST http://localhost:8000/auth/register/caregiver
Content-Type: application/json
```

```json
{
    "email": "ananya@careconnect.in",
    "password": "SecurePass123!",
    "full_name": "Ananya Sharma",
    "hospital_id": "{{hospital_id}}",
    "whatsapp_number": "+919876543210"
}
```

**Response:** `201 Created`
```json
{
    "id": "{{caregiver_user_id}}",   ← SAVE THIS
    "email": "ananya@careconnect.in",
    "full_name": "Ananya Sharma",
    "hospital_id": "{{hospital_id}}",
    "role": "CAREGIVER",
    "is_active": true,
    "created_at": "..."
}
```

---

## STEP 3 — Login as Doctor

```
POST http://localhost:8000/auth/login
Content-Type: application/json
```

```json
{
    "email": "dr.rohan@careconnect.in",
    "password": "SecurePass123!"
}
```

**Response:** `200 OK`
```json
{
    "access_token": "eyJhbGci...",   ← SAVE AS {{doctor_token}}
    "token_type": "bearer",
    "user_id": "{{doctor_user_id}}",
    "role": "DOCTOR"
}
```

> A `refresh_token` cookie is also set (HttpOnly). Not needed for API calls.

---

## STEP 4 — Login as Caregiver

```
POST http://localhost:8000/auth/login
Content-Type: application/json
```

```json
{
    "email": "ananya@careconnect.in",
    "password": "SecurePass123!"
}
```

**Response:** `200 OK`
```json
{
    "access_token": "eyJhbGci...",   ← SAVE AS {{caregiver_token}}
    "token_type": "bearer",
    "user_id": "{{caregiver_user_id}}",
    "role": "CAREGIVER"
}
```

---

## STEP 5 — GET /api/me (Test Auth Guard)

```
GET http://localhost:8000/api/me
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK`
```json
{
    "id": "{{doctor_user_id}}",
    "email": "dr.rohan@careconnect.in",
    "role": "DOCTOR",
    "hospital_id": "{{hospital_id}}"
}
```

**Error test:** Try without `Authorization` header → expect `401 Unauthorized`.

---

## STEP 6 — GET /doctors/profile

```
GET http://localhost:8000/doctors/profile
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK`
```json
{
    "id": "{{doctor_profile_id}}",   ← SAVE THIS (this is doctors.id, NOT users.id)
    "full_name": "Dr. Rohan Mehta",
    "specialization": "General Practice",
    "onboarding_completed": false,
    "availability_slots": [],
    ...
}
```

---

## STEP 7 — PUT /doctors/onboarding

```
PUT http://localhost:8000/doctors/onboarding
Authorization: Bearer {{doctor_token}}
Content-Type: application/json
```

```json
{
    "full_name": "Dr. Rohan Mehta",
    "specialization": "General Practice",
    "license_number": "MCI-2020-12345",
    "hospital_affiliation": "Apollo Hospitals",
    "years_of_experience": "8",
    "bio": "Experienced general practitioner specializing in elderly care.",
    "consultation_fee": 500.00,
    "currency": "INR",
    "accepted_payment_methods": ["upi", "card"]
}
```

**Response:** `200 OK` — profile with `onboarding_completed: true`

---

## STEP 8 — PUT /doctors/availability

```
PUT http://localhost:8000/doctors/availability
Authorization: Bearer {{doctor_token}}
Content-Type: application/json
```

```json
[
    { "day_of_week": "Monday", "start_time": "09:00", "end_time": "17:00", "is_enabled": true },
    { "day_of_week": "Wednesday", "start_time": "09:00", "end_time": "13:00", "is_enabled": true },
    { "day_of_week": "Friday", "start_time": "14:00", "end_time": "18:00", "is_enabled": true }
]
```

**Response:** `204 No Content`

**Verify:** Call `GET /doctors/profile` again — `availability_slots` should have 3 entries.

---

## STEP 9 — POST /patients (Add Patient as Caregiver)

```
POST http://localhost:8000/patients
Authorization: Bearer {{caregiver_token}}
Content-Type: application/json
```

```json
{
    "full_name": "Rajesh Sharma",
    "whatsapp_number": "+919876500001",
    "date_of_birth": "1952-03-15",
    "gender": "Male",
    "blood_group": "B+",
    "address": "45 MG Road, Jaipur",
    "allergies": ["Penicillin"],
    "existing_conditions": ["Hypertension", "Type 2 Diabetes"],
    "emergency_contact_name": "Ananya Sharma",
    "emergency_contact_phone": "+919876543210",
    "caregiver_id": "any-uuid-here",
    "hospital_id": "{{hospital_id}}"
}
```

> **Note:** `caregiver_id` in the body is ignored for caregivers — it's auto-resolved from their profile.

**Response:** `201 Created`
```json
{
    "id": "{{patient_id}}",   ← SAVE THIS
    "full_name": "Rajesh Sharma",
    ...
}
```

---

## STEP 10 — GET /patients (List Patients)

**As Caregiver** (sees only own patients):
```
GET http://localhost:8000/patients
Authorization: Bearer {{caregiver_token}}
```

**As Doctor** (sees all patients in hospital):
```
GET http://localhost:8000/patients
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK` — array of patients

---

## STEP 11 — POST /appointments (Book Consultation)

First, you need the `caregiver_id` (profile ID, not user ID). Get it by looking at the patient response or querying your DB:

```sql
SELECT id FROM caregivers WHERE user_id = '{{caregiver_user_id}}';
```

Save as `{{caregiver_profile_id}}`.

```
POST http://localhost:8000/appointments
Authorization: Bearer {{doctor_token}}
Content-Type: application/json
```

```json
{
    "doctor_id": "{{doctor_profile_id}}",
    "patient_id": "{{patient_id}}",
    "caregiver_id": "{{caregiver_profile_id}}",
    "hospital_id": "{{hospital_id}}",
    "scheduled_time": "2026-04-15T10:30:00+05:30",
    "duration_minutes": 30,
    "appointment_type": "VIDEO",
    "reason": "Routine checkup for elderly patient"
}
```

**Response:** `201 Created`
```json
{
    "id": "{{appointment_id}}",   ← SAVE THIS
    "status": "PENDING",
    ...
}
```

---

## STEP 12 — GET /appointments (List)

```
GET http://localhost:8000/appointments
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK` — array with the appointment from step 11.

---

## STEP 13 — GET /appointments/{id} (Detail)

```
GET http://localhost:8000/appointments/{{appointment_id}}
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK` — single appointment object.

---

## STEP 14 — PATCH /appointments/{id}/status (Confirm)

```
PATCH http://localhost:8000/appointments/{{appointment_id}}/status
Authorization: Bearer {{doctor_token}}
Content-Type: application/json
```

```json
{ "status": "CONFIRMED" }
```

**Response:** `200 OK` — appointment with `"status": "CONFIRMED"`.

**Test the full lifecycle:**
- `{ "status": "IN_PROGRESS" }` → consultation starts
- `{ "status": "COMPLETED" }` → consultation ends

**RBAC test:** Try with `{{caregiver_token}}` → expect `403 Forbidden`.

---

## STEP 15 — POST /medical-records (Create Record)

```
POST http://localhost:8000/medical-records
Authorization: Bearer {{doctor_token}}
Content-Type: application/json
```

```json
{
    "patient_id": "{{patient_id}}",
    "doctor_id": "{{doctor_profile_id}}",
    "appointment_id": "{{appointment_id}}",
    "diagnosis": "Controlled Hypertension with mild seasonal allergy",
    "symptoms": "Elevated BP readings, nasal congestion, mild headache",
    "treatment": "Continue existing BP medication. Added antihistamine for allergy relief.",
    "follow_up_date": "2026-05-01",
    "vitals": {
        "blood_pressure": "140/90",
        "heart_rate": "78 bpm",
        "temperature": "98.4°F",
        "spo2": "97%"
    },
    "prescriptions": [
        {
            "medication_name": "Amlodipine",
            "dosage": "5mg",
            "frequency": "Once daily",
            "duration": "30 days",
            "notes": "Take in the morning with water"
        },
        {
            "medication_name": "Cetirizine",
            "dosage": "10mg",
            "frequency": "Once daily at night",
            "duration": "7 days",
            "notes": "For seasonal allergy relief"
        }
    ]
}
```

**Response:** `201 Created`
```json
{
    "id": "{{record_id}}",   ← SAVE THIS
    "patient_id": "{{patient_id}}",
    "doctor_id": "{{doctor_profile_id}}",
    "appointment_id": "{{appointment_id}}",
    "diagnosis": "Controlled Hypertension with mild seasonal allergy",
    "symptoms": "...",
    "treatment": "...",
    "follow_up_date": "2026-05-01",
    "vitals": { "blood_pressure": "140/90", ... },
    "prescriptions": [
        {
            "id": "...",
            "medication_name": "Amlodipine",
            "dosage": "5mg",
            ...
        },
        {
            "id": "...",
            "medication_name": "Cetirizine",
            ...
        }
    ],
    "created_at": "..."
}
```

**RBAC test:** Try with `{{caregiver_token}}` → expect `403 Forbidden`.

---

## STEP 16 — GET /patients/{id}/records (Patient History)

```
GET http://localhost:8000/patients/{{patient_id}}/records
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK`
```json
[
    {
        "id": "{{record_id}}",
        "diagnosis": "Controlled Hypertension with mild seasonal allergy",
        "prescriptions": [ ... ],
        ...
    }
]
```

**Also test with caregiver token** — caregiver should be able to see their patient's records.

---

## STEP 17 — GET /medical-records/{id} (Single Record)

```
GET http://localhost:8000/medical-records/{{record_id}}
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK` — full record with prescriptions.

**Error test:** Use a random UUID → expect `404 Not Found`.

---

## STEP 18 — POST /medical-records/{id}/prescriptions (Add More Meds)

```
POST http://localhost:8000/medical-records/{{record_id}}/prescriptions
Authorization: Bearer {{doctor_token}}
Content-Type: application/json
```

```json
[
    {
        "medication_name": "Vitamin D3",
        "dosage": "60,000 IU",
        "frequency": "Once weekly",
        "duration": "8 weeks",
        "notes": "Take with a fatty meal for better absorption"
    }
]
```

**Response:** `201 Created`
```json
{
    "message": "Prescriptions added",
    "record_id": "{{record_id}}"
}
```

**Verify:** Call `GET /medical-records/{{record_id}}` again — `prescriptions` array should now have 3 entries.

---

## STEP 19 — GET /health (Sanity Check)

```
GET http://localhost:8000/health
```

No auth needed.

**Response:** `200 OK`
```json
{ "status": "ok", "service": "careconnect-api" }
```

---

## STEP 20 — POST /appointments/{id}/start-session (Start Video Call)

> **Prerequisite:** The appointment must exist. Ideally confirm it first (Step 14).
> Use the `{{appointment_id}}` from Step 11.

```
POST http://localhost:8000/appointments/{{appointment_id}}/start-session
Authorization: Bearer {{doctor_token}}
```

No request body needed.

**Response:** `201 Created`
```json
{
    "room_name": "cc-{{appointment_id}}",
    "join_token": "eyJhbGci..."   ← This is the DOCTOR's LiveKit join token
}
```

**Side effects:**
- A `video_sessions` row is created with tokens for all 3 participants.
- The appointment status is automatically set to `IN_PROGRESS`.

**Error tests:**
- Repeat the same POST → expect `409 Conflict` ("A video session already exists for this appointment.")
- Try with `{{caregiver_token}}` → expect `403 Forbidden` (only Doctors can start sessions)

---

## STEP 21 — GET /appointments/{id}/join (Get Your Join Token)

**As Doctor:**
```
GET http://localhost:8000/appointments/{{appointment_id}}/join
Authorization: Bearer {{doctor_token}}
```

**Response:** `200 OK`
```json
{
    "room_name": "cc-{{appointment_id}}",
    "join_token": "eyJhbGci..."   ← Doctor's token
}
```

**As Caregiver:**
```
GET http://localhost:8000/appointments/{{appointment_id}}/join
Authorization: Bearer {{caregiver_token}}
```

**Response:** `200 OK`
```json
{
    "room_name": "cc-{{appointment_id}}",
    "join_token": "eyJhbGci..."   ← Caregiver's token (different from doctor's)
}
```

**Error test:** Call without starting a session first on a different appointment → expect `404 Not Found`.

---

## Complete Endpoint Reference

| # | Method | Endpoint | Auth | Role Guard |
|---|---|---|---|---|
| 1 | `POST` | `/auth/register/doctor` | ✗ | Public |
| 2 | `POST` | `/auth/register/caregiver` | ✗ | Public |
| 3 | `POST` | `/auth/login` | ✗ | Public |
| 4 | `GET` | `/api/me` | ✓ | Any |
| 5 | `GET` | `/doctors/profile` | ✓ | Doctor |
| 6 | `PUT` | `/doctors/onboarding` | ✓ | Doctor |
| 7 | `PUT` | `/doctors/availability` | ✓ | Doctor |
| 8 | `POST` | `/patients` | ✓ | Doctor, Caregiver |
| 9 | `GET` | `/patients` | ✓ | Doctor, Caregiver, Admin |
| 10 | `POST` | `/appointments` | ✓ | Any |
| 11 | `GET` | `/appointments` | ✓ | Any (RLS-filtered) |
| 12 | `GET` | `/appointments/{id}` | ✓ | Any (RLS-filtered) |
| 13 | `PATCH` | `/appointments/{id}/status` | ✓ | Doctor, Admin |
| 14 | `POST` | `/appointments/{id}/start-session` | ✓ | Doctor |
| 15 | `GET` | `/appointments/{id}/join` | ✓ | Any (RLS-filtered) |
| 16 | `POST` | `/medical-records` | ✓ | Doctor, Admin |
| 17 | `GET` | `/patients/{id}/records` | ✓ | Any (RLS-filtered) |
| 18 | `GET` | `/medical-records/{id}` | ✓ | Any (RLS-filtered) |
| 19 | `POST` | `/medical-records/{id}/prescriptions` | ✓ | Doctor, Admin |
| 20 | `GET` | `/health` | ✗ | Public |
