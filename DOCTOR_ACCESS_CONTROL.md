# Doctor Profile Access Control Implementation

## Problem
Caregivers on the CareConnect dashboard couldn't access doctor profiles because the endpoint was protected by Row-Level Security (RLS), preventing them from seeing public doctor information.

## Solution: Defense-in-Depth Security

We implemented **dual-layer access control** to ensure security at both database and application levels:

### Layer 1: Database-Level RLS Policies

**File:** `alembic/versions/c2d8f9e4a1b3_add_doctor_caregiver_access_rls.py`

Created four RLS policies on the `doctors` table:

1. **Admin Bypass** (`doctors_admin_bypass`)
   - Admins with `SUPER_ADMIN` role can access all doctor profiles
   - Allows administrative flexibility

2. **Doctor Self-Access** (`doctors_own_profile`)
   - Doctors can view their own profile
   - Uses `app.current_doctor_id` session variable

3. **Caregiver Conditional Access** (`doctors_caregiver_access`)
   - Caregivers can ONLY see doctors who have medical records for their assigned patients
   - Query: `EXISTS (SELECT ... FROM medical_records WHERE doctor_id = doctors.id AND patient_caregiver_id = current_caregiver_id)`
   - This is the key policy that enforces the relationship

4. **Default Deny** (`doctors_deny_default`)
   - All other access attempts are blocked
   - Secure-by-default approach

### Layer 2: Application-Level Validation

**File:** `app/routers/doctors.py` - New endpoint `GET /doctors/{doctor_id}`

The FastAPI endpoint replicates the same access control logic:

```python
@router.get("/{doctor_id}", response_model=schemas.DoctorResponse)
async def get_doctor_profile(doctor_id, current_user, db):
    # Validates:
    # - Doctors can access their own profile
    # - Caregivers can access doctors with records for their patients
    # - Admins can access all profiles
```

**CRUD Function:** `app/crud.py` - New function `can_caregiver_access_doctor()`

```python
async def can_caregiver_access_doctor(db, caregiver_id, doctor_id) -> bool:
    """
    Check if caregiver has access by verifying:
    1. Patient is assigned to caregiver
    2. Doctor has medical records for that patient
    """
```

## Why Both Layers?

1. **Database RLS**: Protects against:
   - Direct SQL queries bypassing FastAPI
   - Connection compromise
   - Accidental raw SQL operations

2. **Application Validation**: Protects against:
   - RLS policy bugs or misconfigurations
   - Business logic edge cases
   - Provides clear error messages

## To Deploy

Run the migration:
```bash
cd careconnect-api
alembic upgrade head
```

This will:
1. Enable RLS on the `doctors` table
2. Create all four policies
3. Log the revision in `alembic_version` table

## Caregiver Flow

```
Caregiver views patient record
  ↓
Fetches doctor profile via GET /doctors/{doctor_id}
  ↓
Application layer checks: Can this caregiver access this doctor?
  ↓
Database RLS policy also checks: Does the doctor have records for this caregiver's patients?
  ↓
Both pass → Profile returned
Both fail → 403 Forbidden
```

## Security Notes

- **No information leakage**: Caregivers can't enumerate doctors through 404s (same 403 for "not found" vs "no access")
- **Role-based bypass**: Admin role bypasses RLS entirely (intended for account management)
- **Session-based**: Uses PostgreSQL session variables set in `app/dependencies.py`
- **Testable**: Each layer can be tested independently
